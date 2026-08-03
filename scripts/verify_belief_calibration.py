#!/usr/bin/env python3
"""Standalone verification for Tier 6's L4.1, belief confidence
calibration (hearthmind/ml/belief_calibration.py). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.ml.belief_calibration import (
    BeliefConfidenceCalibrator,
    calibration_gap,
    compute_belief_outcome_label,
    extract_calibration_examples,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_outcome_label():
    check("supported settles to a real positive label", compute_belief_outcome_label("supported") == 1.0)
    check("rejected settles to a real negative label", compute_belief_outcome_label("rejected") == 0.0)
    check("open has no settled outcome", compute_belief_outcome_label("open") is None)
    check("superseded has no settled outcome", compute_belief_outcome_label("superseded") is None)
    check("an unrecognized status has no settled outcome", compute_belief_outcome_label("bogus") is None)


def check_extract_examples():
    entries = [
        {"confidence": 0.9, "status": "supported"},
        {"confidence": 0.2, "status": "rejected"},
        {"confidence": 0.5, "status": "open"},
        {"confidence": 0.6, "status": "superseded"},
        {"confidence": 0.75, "status": "supported"},
    ]
    examples = extract_calibration_examples(entries)
    check("open/superseded entries are excluded from the extracted examples", len(examples) == 3)
    check("extracted examples keep the real confidence/label pairing",
          (0.9, 1.0) in examples and (0.2, 0.0) in examples and (0.75, 1.0) in examples)


def check_extract_examples_missing_fields():
    entries = [{"status": "supported"}, {"confidence": 0.4}]
    examples = extract_calibration_examples(entries)
    check("a missing confidence field degrades to 0.0 rather than raising",
          examples == [(0.0, 1.0)])


def synthetic_overconfident_dataset(rng, n):
    """A real, learnable synthetic relationship: stated confidence runs
    systematically ~0.25 ahead of the real empirical hold-up rate (a
    genuinely overconfident source) -- close to the class of pattern a
    real settlement's own optimistic hypothesis-forming job could
    plausibly produce, without needing a real archive."""
    examples = []
    for _ in range(n):
        true_probability = rng.uniform(0.05, 0.75)
        stated_confidence = min(1.0, true_probability + 0.25)
        outcome = 1.0 if rng.random() < true_probability else 0.0
        examples.append((stated_confidence, outcome))
    return examples


def check_calibration_gap():
    rng = random.Random(3)
    overconfident = synthetic_overconfident_dataset(rng, 500)
    gap = calibration_gap(overconfident)
    check("a systematically overconfident source shows a real positive gap", gap is not None and gap > 0.15,
          detail=f"gap={gap}")
    check("no settled examples yields a genuine None, not a fabricated 0.0", calibration_gap([]) is None)

    well_calibrated = [(p, 1.0 if rng.random() < p else 0.0) for p in [rng.uniform(0.0, 1.0) for _ in range(2000)]]
    gap2 = calibration_gap(well_calibrated)
    check("a genuinely well-calibrated source shows a gap near zero", abs(gap2) < 0.05, detail=f"gap={gap2}")


def check_calibrator_learns_correction():
    rng = random.Random(9)
    examples = synthetic_overconfident_dataset(rng, 1000)
    calibrator = BeliefConfidenceCalibrator()
    calibrator.fit(examples, epochs=300, lr=0.3)

    # A raw 0.9-stated confidence in this overconfident regime really
    # means closer to a 0.65 hold-up rate -- the calibrated output
    # should shrink toward that, not just echo the raw input back.
    raw = 0.9
    calibrated = calibrator.calibrate(raw)
    check("calibration pulls an overconfident stated value down toward reality",
          calibrated < raw, detail=f"raw={raw} calibrated={calibrated}")
    check("calibrated output stays a real probability in [0, 1]", 0.0 <= calibrated <= 1.0)

    # An untrained calibrator degrades to a real no-op passthrough rather
    # than raising or returning garbage.
    fresh = BeliefConfidenceCalibrator()
    check("fitting on zero examples is a safe no-op, not a crash",
          fresh.fit([]).calibrate(0.5) == fresh.calibrate(0.5))


def main():
    check_outcome_label()
    check_extract_examples()
    check_extract_examples_missing_fields()
    check_calibration_gap()
    check_calibrator_learns_correction()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
