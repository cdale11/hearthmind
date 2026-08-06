#!/usr/bin/env python3
"""Trains `hearthmind.ml.law_scorer.LawCandidateScorer` -- the real
mechanism `llm/laws.py`'s "which hardship becomes a law" was excluded
from `scripts/train_decision_policies_from_archive.py` for (a
dynamic-candidate-set scoring problem, not a fixed closed class -- see
`hearthmind/ml/law_scorer.py`'s own docstring). Same shape as every
other Tier 6 trainer: consumes either a `review_pack.json` export or a
raw recorder archive directory, extracts real `fallback_used=False`
`laws` task pairs, trains via a real held-out shadow-gate split, and
saves the result to the exact path `SimulationEngine` auto-loads.

Usage:
    python3 scripts/train_law_scorer_from_archive.py \\
        --review-pack review_pack.json \\
        --out-dir /path/to/world/

    python3 scripts/train_law_scorer_from_archive.py \\
        --archive-dir training_archive \\
        --out-dir /path/to/world/

Writes law_scorer_weights.json -- see `hearthmind.simulation.engine.
LAW_SCORER_FILENAME` for the exact name `SimulationEngine` looks for.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

sys.path.insert(0, ".")

from hearthmind.ml.law_scorer import LawCandidateScorer, build_training_examples

HOLDOUT_FRACTION = 0.2
MIN_EXAMPLES_REQUIRED = 20


def load_review_pack(path: str) -> list:
    with open(path) as f:
        return json.load(f)


def load_archive_dir(archive_dir: str, task: str) -> list:
    examples = []
    for path in sorted(glob.glob(os.path.join(archive_dir, task, "*.jsonl"))):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                examples.append(json.loads(line))
    return examples


def extract_pairs(examples: list) -> tuple:
    """Returns `(candidate_features, forms_labels)` -- each feature is
    a real `(occurrences, pillar_confidence, initiated_by_conviction)`
    tuple straight off `_maybe_schedule_laws`'s own real `structured_
    input`. A recorded example predating that wiring (no `occurrences`
    key at all) is skipped, not coerced."""
    features, labels = [], []
    for ex in examples:
        if ex.get("task") != "laws" or ex.get("fallback_used"):
            continue
        state = ex.get("layer1_structured_input") or {}
        if "occurrences" not in state:
            continue
        parsed = ex.get("layer4_parsed_output") or {}
        forms = parsed.get("forms")
        if not isinstance(forms, bool):
            continue
        features.append((
            state.get("occurrences", 0),
            state.get("pillar_confidence", 0.0),
            bool(state.get("initiated_by_conviction", False)),
        ))
        labels.append(forms)
    return features, labels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review-pack", help="Path to a review_pack.json export")
    parser.add_argument("--archive-dir", help="Path to a raw recorder archive directory")
    parser.add_argument("--out-dir", required=True, help="Directory to write law_scorer_weights.json into (your world's db directory)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not args.review_pack and not args.archive_dir:
        parser.error("one of --review-pack or --archive-dir is required")

    examples = load_review_pack(args.review_pack) if args.review_pack else load_archive_dir(args.archive_dir, "laws")
    features, labels = extract_pairs(examples)
    print(f"Extracted {len(features)} real, non-fallback (state, forms) pairs from the 'laws' task.")
    if len(features) < MIN_EXAMPLES_REQUIRED:
        print(f"Not enough usable pairs (need at least {MIN_EXAMPLES_REQUIRED}) — "
              "let the world run longer (with the LLM enabled) before trying again.")
        return 1
    formed = sum(1 for label in labels if label)
    print(f"Real outcome distribution: forms=True {formed}, forms=False {len(labels) - formed}")

    training_examples = build_training_examples(features, labels)
    rng = random.Random(args.seed)
    shuffled = list(training_examples)
    rng.shuffle(shuffled)
    n_holdout = max(1, int(len(shuffled) * HOLDOUT_FRACTION))
    holdout, train_examples = shuffled[:n_holdout], shuffled[n_holdout:]

    # Same lr=0.003/epochs=200 settled on for goal_policy/decision_
    # policies against a real archive -- see train_goal_policy_from_
    # archive.py's own comment for the plain-SGD-divergence reasoning.
    scorer = LawCandidateScorer(seed=args.seed)
    result = scorer.learn(train_examples, holdout, tick=0, epochs=200, learning_rate=0.003, seed=args.seed)
    print(f"Shadow gate: {'ACCEPTED' if result.accepted else 'REJECTED (kept fresh weights)'}")

    correct = 0
    for ex in holdout:
        predicted = scorer.specialist.predict(ex.x)[0] >= 0.5
        actual = ex.y[0] >= 0.5
        if predicted == actual:
            correct += 1
    holdout_accuracy = correct / len(holdout) if holdout else 0.0
    print(f"Holdout accuracy: {holdout_accuracy:.1%}")

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "law_scorer_weights.json")
    scorer.save(out_path)
    print(f"Wrote trained weights to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
