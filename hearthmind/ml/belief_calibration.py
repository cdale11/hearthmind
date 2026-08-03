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

Standalone infrastructure, same "never big-bang" discipline as every
other Tier 6 module shipped so far -- not wired into any real
consumer this pass (`_maybe_schedule_self_tuning`/`town_brain`/etc.
reading a RAW `reflection_pillar.subject_confidence()`/entry `
confidence` today, uncalibrated). Needs real settled-hypothesis
history from a live world this offline environment has no archive to
source, same reasoning L0/L2.1/L3.1/L3.2 all shipped under.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.ml.primitives import PlattCalibrator

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
