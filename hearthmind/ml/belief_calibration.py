"""Tier 6, L4.1 -- Belief confidence calibration (docs/ML-ARCHITECTURE-
2026-08-01.md: "maps asserted confidence -> empirically calibrated
confidence... deliberately NOT an ANN -- this is a solved 1-D
statistical problem"). `hearthmind.ml.primitives.PlattCalibrator`
already ships this exact primitive (its own docstring names L4.1 as
its motivation, since v1.34.171's L0 substrate filing) -- what was
never built is the domain-specific half: which real recorded outcome
counts as ground truth, and how a real belief-holding-structure's
stated confidence becomes a training example. This module is that
wiring, same "ship the substrate, wire the domain" split as every
other Tier 6 model.

**Real, already-recorded ground truth**: `World.reflection_notebook`
entries (`simulation/engine.py`) carry both a `confidence` field and a
`status` that eventually settles to `"supported"` (confidence crossed
`REFLECTION_SUPPORTED_THRESHOLD`) or `"rejected"` (crossed `REFLECTION_
REJECTED_THRESHOLD`) via `_reevaluate_reflection_hypotheses`'s own
multi-cycle evidence loop -- a genuine "did this stated belief hold up"
outcome, not an invented label. `"open"`/`"superseded"` entries carry
no settled outcome yet and are correctly excluded from training, not
treated as a negative.

**Wired (roadmap Phase 2, L4.1, explicit user instruction):**
`SimulationEngine._maybe_schedule_self_tuning`'s C2 "propose
experiment" conviction gate (the one place a hypothesis's raw
`confidence` is compared against a threshold to decide whether it's
trustworthy enough to INITIATE a real sandboxed self-tuning
experiment ahead of the normal "supported" promotion) now runs the
stated confidence through this calibrator first, when a trained
weights file is loaded next to the world's `db_path` -- see `BELIEF_
CALIBRATOR_FILENAME` in `simulation/engine.py`. No weights file means
the raw stated confidence is used directly, byte-for-byte identical to
prior behavior -- same never-auto-created, per-world discipline as
`GoalPolicy`/`LLMCostRegressor`. Every OTHER reader of `reflection_
notebook`/`reflection_pillar` confidence stays uncalibrated this
pass -- a single real, representative consumer, not a sweep. Needs
real settled-hypothesis history from a live world; see `scripts/
train_belief_calibrator_from_archive.py` and README's "Local ML
training" section.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from hearthmind.ml.primitives import PlattCalibrator

BELIEF_CALIBRATOR_SCHEMA_VERSION = 1
"""Roadmap Phase 2, L4.1 (explicit user instruction: "wire L2.1 and
L4.1 like you did the other ones"): the persistence this module was
missing before it could gain a real engine-side consumer — same
schema-versioned/kind-tagged blob shape as `LLMCostRegressor`/
`GoalPolicy`, wrapping `PlattCalibrator.to_dict()`/`from_dict()` (which
itself carries no schema/kind check of its own)."""

# The doc's own named outcomes: a hypothesis that settled to
# "supported" really did hold up (label 1.0); one that settled to
# "rejected" really did not (label 0.0). "open" (still being tested)
# and "superseded" (replaced before ever settling either way) carry no
# real true/false outcome -- neither a positive nor a negative example,
# so they're excluded from calibration training entirely rather than
# guessed at.
_SETTLED_OUTCOME_LABELS = {"supported": 1.0, "rejected": 0.0}


def compute_belief_outcome_label(status: str) -> float | None:
    """The real training label for one settled belief/hypothesis:
    1.0 if it held up (`"supported"`), 0.0 if it didn't (`"rejected"`),
    `None` for anything not yet settled (`"open"`/`"superseded"`) --
    `None` is the caller's signal to skip this entry, never a value to
    train on."""
    return _SETTLED_OUTCOME_LABELS.get(status)


def extract_calibration_examples(entries: list) -> list:
    """Pulls (asserted confidence, real settled outcome) pairs from a
    real `World.reflection_notebook`-shaped list of dicts (each with
    `confidence`/`status` keys) -- the one place this model's training
    data is assembled, so a live-world archive loader and this
    function would produce identical pairs. Entries with no settled
    outcome are silently skipped, not defaulted to either label."""
    examples = []
    for entry in entries:
        label = compute_belief_outcome_label(entry.get("status", ""))
        if label is None:
            continue
        examples.append((float(entry.get("confidence", 0.0)), label))
    return examples


@dataclass
class BeliefConfidenceCalibrator:
    """Thin domain wrapper over `PlattCalibrator` -- this class owns
    nothing but the calibrator instance itself; fitting/predicting is
    entirely `PlattCalibrator`'s own job, same "the model class is
    generic, the wrapper is the domain application" split every other
    Tier 6 model uses. `calibrate()`'s output is always a real
    probability in [0, 1] (sigmoid-bounded by construction), never the
    raw asserted confidence passed straight through."""

    calibrator: PlattCalibrator = field(default_factory=PlattCalibrator)

    def fit(self, examples: list, epochs: int = 200, lr: float = 0.1) -> "BeliefConfidenceCalibrator":
        if not examples:
            return self
        scores = [x for x, _ in examples]
        labels = [y for _, y in examples]
        self.calibrator.fit(scores, labels, epochs=epochs, lr=lr)
        return self

    def calibrate(self, asserted_confidence: float) -> float:
        return self.calibrator.calibrate(asserted_confidence)

    def to_dict(self) -> dict:
        return {
            "schema_version": BELIEF_CALIBRATOR_SCHEMA_VERSION, "kind": "belief_calibrator",
            "calibrator": self.calibrator.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BeliefConfidenceCalibrator":
        if d.get("schema_version") != BELIEF_CALIBRATOR_SCHEMA_VERSION:
            raise ValueError(f"unsupported belief_calibrator schema_version={d.get('schema_version')!r}")
        if d.get("kind") != "belief_calibrator":
            raise ValueError(f"weights file is for {d.get('kind')!r}, not 'belief_calibrator'")
        return cls(calibrator=PlattCalibrator.from_dict(d["calibrator"]))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "BeliefConfidenceCalibrator":
        with open(path) as f:
            return cls.from_dict(json.load(f))


def calibration_gap(examples: list) -> float | None:
    """A real, model-free diagnostic: the mean signed difference
    between stated confidence and the real empirical rate of settling
    "supported" -- positive means beliefs are systematically
    OVERconfident (stated confidence runs ahead of how often they
    actually hold up), negative means systematically UNDERconfident.
    `None` with no settled examples to measure against. This is the
    number that would justify calibration existing at all -- a
    genuinely well-calibrated source (gap near 0) gains nothing from
    it."""
    if not examples:
        return None
    mean_confidence = sum(x for x, _ in examples) / len(examples)
    empirical_rate = sum(y for _, y in examples) / len(examples)
    return mean_confidence - empirical_rate
