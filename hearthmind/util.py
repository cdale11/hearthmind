"""Tiny cross-cutting helpers shared across subsystems.

Deliberately dependency-free (stdlib only) so any module can import it
without risking an import cycle — this is the bottom of the dependency
graph. Keep it that way: only genuinely universal, stateless helpers
belong here, never anything that imports a domain module.
"""

from __future__ import annotations

import hashlib
import random


def clamp(value: float, low: float, high: float) -> float:
    """Constrain `value` to the closed interval [low, high].

    Replaces the `max(low, min(high, value))` idiom that recurs across
    the bounded-random-walk math (temperament, player standing,
    cross-settlement relations) and the -1..1 belief/trust axes. A named
    helper reads as intent ("this quantity is bounded") and removes the
    easy-to-flip nesting where a stray `min`/`max` swap silently inverts
    a bound. Assumes `low <= high` (every call site passes literals)."""
    return max(low, min(high, value))


def namespaced_rng(seed: int, tick: int, namespace: str) -> random.Random:
    """A `random.Random` seeded deterministically from
    (seed, tick, namespace) — the project's standing pattern for giving
    each stochastic decision site its own independent, reproducible
    entropy stream so unrelated systems never share (or perturb) one
    another's rolls. Determinism itself is not a project requirement
    (see CLAUDE.md), but this namespacing is the natural, cheap way to
    keep per-site RNG independent, so it stays. Previously copy-pasted
    verbatim into population.py / world/state.py / simulation/engine.py;
    consolidated here as the single source of truth."""
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def namespaced_roll(seed: int, tick: int, namespace: str) -> float:
    """A single deterministic float in [0, 1) from
    (seed, tick, namespace) — the lighter-weight sibling of
    `namespaced_rng` for the rare engine-level rolls (invention, omen
    chance, etc.) that need one number, not a full `random.Random`."""
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF
