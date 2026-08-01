"""L5 -- the lifelong/continual learning loop (docs/ML-ARCHITECTURE-
2026-08-01.md's new L5 section, added v1.34.172 to close a real gap:
without this, "weights are per-world state" only makes two worlds
diverge at generation/training time -- nothing kept a world's models
actually LEARNING over the years of simulated play that follow.

Three pieces close the loop:
  - `ReplayBuffer`: a bounded reservoir sample spanning a model's
    WHOLE training history, not a sliding window -- so a later
    continual retrain can rehearse old lessons alongside new ones
    instead of catastrophically forgetting them.
  - `CheckpointHistory`: a bounded, versioned log of past weight blobs
    per world, so an automated retrain that regresses can be rolled
    back.
  - `passes_shadow_gate`: the safety check a candidate retrain must
    clear (evaluated against held-out recent examples before its
    weights ever replace the live ones) -- the same "a change that
    regresses is rejected without a judgment call" discipline B15's
    replay-hash gate already established for determinism, applied
    here to model quality instead.

Still standalone substrate, same "never big-bang" discipline as every
other Tier 5/6 module: nothing here is wired into a real simulated-
time-triggered retrain cadence yet. That needs the B1-B2 scheduler to
actually be wired into the live tick loop first (still unbuilt --
see CLAUDE.md's B0.3 migration note), plus a real per-model decision
of what cadence to retrain on (season? year? N new recorder examples?)
-- explicitly flagged as open, real future work, not attempted here.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class ReplayBuffer:
    """Reservoir-sampled bounded buffer (Algorithm R): after
    `capacity` insertions, each new item replaces a uniformly-random
    existing slot with probability `capacity / n_seen`. The classic
    guarantee -- every item ever inserted has an equal, exactly
    computable chance of still being present regardless of how long
    ago it arrived -- is what lets rehearsal cover a model's whole
    lived history rather than just its most recent slice."""

    capacity: int
    seed: int = 0
    _items: list = field(default_factory=list)
    _n_seen: int = 0
    _rng: object = field(default=None, repr=False)

    def __post_init__(self):
        if self._rng is None:
            self._rng = random.Random(self.seed)

    def add(self, item) -> None:
        self._n_seen += 1
        if len(self._items) < self.capacity:
            self._items.append(item)
            return
        j = self._rng.randint(0, self._n_seen - 1)
        if j < self.capacity:
            self._items[j] = item

    def sample(self, n: int) -> list:
        n = min(n, len(self._items))
        return self._rng.sample(self._items, n) if n else []

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class Checkpoint:
    tick: int
    weights: dict  # a primitives.MLP.to_dict()-shaped blob
    metric: float  # held-out loss/score at save time, for rollback comparison


@dataclass
class CheckpointHistory:
    """Bounded, oldest-evicted log of past weight-blob versions --
    lets an automated retrain roll back if a shadow-eval gate ever
    lets a regression through undetected at swap time."""

    capacity: int = 20
    _entries: list = field(default_factory=list)

    def push(self, tick: int, weights: dict, metric: float) -> None:
        self._entries.append(Checkpoint(tick=tick, weights=weights, metric=metric))
        if len(self._entries) > self.capacity:
            self._entries.pop(0)

    def latest(self):
        return self._entries[-1] if self._entries else None

    def rollback(self):
        """Discard the current (latest) checkpoint and return the one
        before it, or None if there's nothing to roll back to."""
        if len(self._entries) < 2:
            return None
        self._entries.pop()
        return self._entries[-1]

    def __len__(self) -> int:
        return len(self._entries)


def passes_shadow_gate(candidate_metric: float, baseline_metric: float, tolerance: float = 0.0) -> bool:
    """A candidate retrain must be at least as good as the live
    baseline (this assumes LOWER is better, matching every loss the
    L0 trainer produces) to replace it. `tolerance` allows a small,
    explicit amount of noise slack rather than rejecting on any
    nondeterministic wobble between runs."""
    return candidate_metric <= baseline_metric + tolerance
