"""Tier 7 HCA Stage A, A1 (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md
§2.3/§3, Layer 1's amended five-method interface): `predict()`/
`error()` on specialists, precision-weighted surprise scoring.

The direct fix for the soak-measured problem HCA itself was written
against: 93% of a 64k-tick soak's emergence log was `unexplained_
shift`, almost all of it "content agent decided to socialize" — the
most predictable event possible, reaching the log purely because it
OCCURRED, never because it was surprising. §2.3's formula:

    surprise = |actual - predicted| / (sigma + eps)

A specialist that keeps a cheap running forward model of its own
signal computes this in a handful of lines, with no machine learning
at all (`learn()` — a real trained forward model superseding the
running average — is G1's job applied to a specialist family; the
hand-set running mean here is deliberately the "legitimate, cheap
STARTING point," per §2.5a's own wording, not the permanent ceiling).
Precision-weighting (dividing by the running standard deviation) is
what stops a chronically noisy channel hijacking attention just by
being noisy, and is also what lets a REPEATED signal's surprise fall
toward zero the more consistently it repeats, while a rare, sharply-
deviating signal scores high the moment it occurs.

`SurpriseSpecialist` is the shared primitive: one running forward
model per string key (a subject/kind/subsystem/settlement key, or any
other keyed scalar signal an L1 specialist wants to score), Welford's
online algorithm for O(1)-per-observation mean/variance with no stored
history. Deliberately NOT wired into any real production job this
pass — `world/emergence.py`'s own consumer (gating the emergence log
on surprise instead of occurrence) is A2, a distinct, larger item that
depends on this primitive existing first. Same "ship the interface,
wire the first real consumer next" discipline every prior Stage A/G/L
item in this codebase has used."""
from __future__ import annotations

SURPRISE_VARIANCE_EPSILON = 0.05
"""Precision floor added to the running standard deviation before
dividing — keeps a specialist's own surprise score from blowing up
toward infinity for a signal that has been perfectly constant so far
(stdev genuinely 0.0), and keeps a barely-noisy signal's surprise from
swinging wildly on the first couple of observations before its running
variance has had a chance to stabilize. Scaled to the same [0, 1]
magnitude range every `Observation.magnitude` (`world/emergence.py`)
already uses -- a reasoned starting point, not a live measurement (this
codebase has no live archive to tune it against yet, same "reasoned,
not measured" discipline several other constants here already use)."""


class SurpriseSpecialist:
    """L1's `predict()`/`observe()`/`error()` interface (HCA §3), keyed
    by an arbitrary string so ONE instance can score many independent
    signals (e.g. one per `f"{subsystem}:{kind}"` emergence-log
    category, or one per settlement, or one per agent) without needing
    a separate tracker object per key. `bid()`/`learn()` are explicitly
    out of scope for A1 -- Stage A's own item only asks for `predict()`/
    `error()`; `bid()` is Stage B's territory (coalition formation over
    a real workspace, which doesn't exist yet) and a trained `learn()`
    forward model is G1/G2's already-shipped `LearningSpecialist`
    machinery applied to a NEW specialist family, not reinvented here."""

    def __init__(self) -> None:
        self._count: dict[str, int] = {}
        self._mean: dict[str, float] = {}
        self._m2: dict[str, float] = {}  # Welford's running sum of squared deviations

    def predict(self, key: str) -> float:
        """What this specialist expects `key`'s next observation to be
        -- its running mean, or `0.0` (a neutral "nothing has ever
        happened here yet" prior) for a never-observed key."""
        return self._mean.get(key, 0.0)

    def stdev(self, key: str) -> float:
        """`key`'s running (population) standard deviation -- `0.0`
        for a key with fewer than two observations, a genuinely
        constant signal, or an unobserved key (all three read as "no
        variance evidence yet," handled by `SURPRISE_VARIANCE_EPSILON`
        at the one real caller, `error()`, rather than here)."""
        n = self._count.get(key, 0)
        if n < 2:
            return 0.0
        return (self._m2[key] / n) ** 0.5

    def error(self, key: str, value: float) -> float:
        """Precision-weighted surprise for `value` against `key`'s
        CURRENT prediction -- `|value - predict(key)| / (stdev(key) +
        SURPRISE_VARIANCE_EPSILON)`. Call this BEFORE `observe()` for
        the same `(key, value)` pair; calling it after would score
        `value` against a prediction already updated to include it,
        which is not a real prediction error."""
        predicted = self.predict(key)
        return abs(value - predicted) / (self.stdev(key) + SURPRISE_VARIANCE_EPSILON)

    def observe(self, key: str, value: float) -> None:
        """Folds `value` into `key`'s running mean/variance (Welford's
        online algorithm -- O(1) per call, no stored history)."""
        n = self._count.get(key, 0) + 1
        mean = self._mean.get(key, 0.0)
        delta = value - mean
        mean += delta / n
        delta2 = value - mean
        self._count[key] = n
        self._mean[key] = mean
        self._m2[key] = self._m2.get(key, 0.0) + delta * delta2

    def score(self, key: str, value: float) -> float:
        """The one call a real consumer (A2's future emergence-log
        gate, or any other L1 caller) actually makes: scores `value`
        against `key`'s prediction, THEN folds it into the running
        model -- atomic, in the correct order, so no caller can
        accidentally call `observe()` before `error()` and silently
        get a zero score for every genuinely novel signal."""
        surprise = self.error(key, value)
        self.observe(key, value)
        return surprise
