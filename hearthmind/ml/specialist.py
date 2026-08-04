"""Tier 7 HCA, Stage G, G1 (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md
§2.5a, "every subsystem should itself be capable of adaptation"): the
`learn()` half of L1's five-method specialist interface (`predict()`/
`observe()`/`error()`/`bid()`/`learn()`), wired directly onto Tier 6's
already-shipped L5 substrate (`hearthmind.ml.lifelong`) -- no new
learning mechanism, only real orchestration of `ReplayBuffer`/
`CheckpointHistory`/`passes_shadow_gate` plus L0's `continual_train_
mlp`/`mean_loss`.

`predict()`/`observe()`/`error()`/`bid()` are explicitly OUT of scope
here -- those are Stage A/B's own items (A1's precision-weighted
surprise, B1-B7's coalition bidding), not yet built. `LearningSpecialist`
below is deliberately the smallest real thing that makes `learn()`
meaningful on its own: something that predicts (`predict()`, a plain
delegate to the wrapped `MLP.forward`) and can be told to adapt
(`learn()`). A future Stage A/B pass extends this same class (or wraps
it) with the other four methods -- this file doesn't guess their shape.

The one real design decision `learn()` makes, stated plainly: never
overwrite the live model in place. `continual_train_mlp` itself
mutates its `model` argument directly, which would make a shadow-gate
check meaningless (the "shadow" would already be live by the time it's
evaluated) -- so `learn()` always trains a CLONE (`MLP.from_dict(self.
model.to_dict())`), evaluates the clone against held-out examples, and
only swaps it in for `self.model` if `passes_shadow_gate` agrees it's
at least as good as the live model's own held-out metric. A rejected
candidate's new examples still enter the replay buffer regardless --
the buffer records what the specialist actually lived through, not
what it successfully learned from; a future retrain attempt gets
another chance to rehearse the same example.

G3 (explicit user instruction: "Continue G3"), "forget obsolete
assumptions, made testable": investigated whether the existing `learn()`
loop above ALREADY re-adapts after a genuine regime change (a specialist
trained against a pattern that then stops holding) before assuming a
new forgetting mechanism was needed. A direct synthetic test (two
distinct linear regimes, holdout drawn from whichever regime is
CURRENT) confirmed it does, unmodified: the shadow gate always compares
a candidate against a holdout from the world as it is NOW, never the
stale regime, so a candidate that's closer to the new pattern keeps
winning gate comparisons regardless of what's mixed into replay --
`replay_fraction`'s default (0.5, i.e. new examples always outnumber
replayed ones at least 2:1) is enough for genuine adaptation to win out
within a bounded number of real cycles. No fix was invented for a
problem that doesn't reproduce; `scripts/verify_ml_g3_regime_change.py`
holds the real, stated-in-advance bound this finding rests on.

What WAS a real, honest gap: nothing exposed a specialist's own
prediction-error trace over time, which HCA's own roadmap names as a
direct G3 dependency (E5, "per-specialist learning curves... with G3's
regime-change re-adaptation visibly plotted"). `LearningSpecialist.
error_history` below closes that -- a bounded, append-only record of
every real `learn()` call's baseline/candidate metrics and accept
verdict, the observability substrate a future Observatory panel reads
from directly rather than needing to be invented at UI time.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from hearthmind.ml.lifelong import CheckpointHistory, ReplayBuffer, passes_shadow_gate
from hearthmind.ml.primitives import MLP
from hearthmind.ml.training import continual_train_mlp, mean_loss

ERROR_HISTORY_MAX = 200
"""Bounded per-specialist prediction-error trace (G3/E5's own real
observability substrate) -- oldest entries evicted, same discipline as
every other bounded log in this codebase (`ReplayBuffer`, `Checkpoint
History`, `World.emergence_log`, ...)."""


@dataclass
class LearnResult:
    """What actually happened on one `learn()` call -- always returned,
    never raised, so a caller can log/skip/retry without a try/except."""

    accepted: bool
    candidate_metric: float
    baseline_metric: float
    reason: str


class LearningSpecialist:
    """Wraps one `primitives.MLP` with the real L5 lifelong-learning
    loop. `model` is the live, currently-served set of weights --
    `predict()` always reads it directly, so a caller never has to
    know whether a `learn()` call is in flight or ever happened."""

    def __init__(
        self, model: MLP, replay_capacity: int = 200, checkpoint_capacity: int = 20,
        replay_seed: int = 0,
    ) -> None:
        self.model = model
        self.replay_buffer = ReplayBuffer(capacity=replay_capacity, seed=replay_seed)
        self.checkpoint_history = CheckpointHistory(capacity=checkpoint_capacity)
        self.error_history: deque = deque(maxlen=ERROR_HISTORY_MAX)
        """G3's real observability trace: one entry per real `learn()`
        call (never a skipped/synthetic one), `{tick, baseline_metric,
        candidate_metric, accepted}` -- the exact "prediction error
        over time" series E5's future per-specialist learning-curve
        panel plots, including a regime-change spike-then-recovery."""

    def predict(self, x: list) -> list:
        return self.model.forward(x)

    def learn(
        self, new_examples: list, holdout_examples: list, tick: int,
        replay_fraction: float = 0.5, epochs: int = 20, learning_rate: float = 0.03,
        seed: int = 0, tolerance: float = 0.0,
    ) -> LearnResult:
        """One real observe-then-adapt cycle. `holdout_examples` is
        recent-but-not-trained-on data (the caller's own responsibility
        to keep separate from `new_examples`) -- with none supplied
        there is nothing honest to shadow-gate against, so the
        candidate is accepted unconditionally (same "degrades to plain
        training" shape `continual_train_mlp`'s own `replay_buffer=
        None` case already uses, not a silent gate bypass dressed up
        as real gating)."""
        if not new_examples:
            return LearnResult(accepted=False, candidate_metric=0.0, baseline_metric=0.0, reason="no new examples")

        baseline_metric = mean_loss(self.model, holdout_examples) if holdout_examples else 0.0
        candidate = MLP.from_dict(self.model.to_dict())
        continual_train_mlp(
            candidate, new_examples, replay_buffer=self.replay_buffer,
            replay_fraction=replay_fraction, epochs=epochs, learning_rate=learning_rate, seed=seed,
        )

        if not holdout_examples:
            self.model = candidate
            self.checkpoint_history.push(tick, candidate.to_dict(), 0.0)
            self.error_history.append({"tick": tick, "baseline_metric": 0.0, "candidate_metric": 0.0, "accepted": True})
            return LearnResult(accepted=True, candidate_metric=0.0, baseline_metric=0.0, reason="no holdout supplied, ungated accept")

        candidate_metric = mean_loss(candidate, holdout_examples)
        accepted = passes_shadow_gate(candidate_metric, baseline_metric, tolerance)
        self.error_history.append({
            "tick": tick, "baseline_metric": baseline_metric, "candidate_metric": candidate_metric, "accepted": accepted,
        })
        if accepted:
            self.model = candidate
            self.checkpoint_history.push(tick, candidate.to_dict(), candidate_metric)
            return LearnResult(
                accepted=True, candidate_metric=candidate_metric, baseline_metric=baseline_metric,
                reason="candidate did not regress held-out metric",
            )
        return LearnResult(
            accepted=False, candidate_metric=candidate_metric, baseline_metric=baseline_metric,
            reason="candidate regressed held-out metric beyond tolerance",
        )
