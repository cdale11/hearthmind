#!/usr/bin/env python3
"""Tier 6 Phase 1's real offline trainer for the four `fallback_*`-
shaped decision sites (docs/ROADMAP-2026-07-REMAINING.md): `llm/
dispute.py`'s `fallback_dispute`, `llm/fission.py` and `llm/migration.
py`'s `fallback_decision`, and `llm/founding.py`'s `fallback_founding`.
Same shape as `scripts/train_goal_policy_from_archive.py` -- consumes
either a `review_pack.json` export or a raw recorder archive directory,
extracts real `fallback_used=False` `(structured_input, outcome)`
pairs per site, trains via a real held-out shadow-gate split, and
saves each site's weights to the exact path `SimulationEngine`
auto-loads.

Trains whichever of the four sites has enough real recorded examples
in the given archive -- a site with too few examples is reported and
skipped, never trained on an unrepresentative handful. `llm/laws.py`'s
"which hardship becomes a law" is deliberately NOT included here, same
reason `hearthmind.ml.decision_policy`'s own docstring gives (a
dynamic-candidate-set decision, not a fixed closed class).

Usage:
    python3 scripts/train_decision_policies_from_archive.py \\
        --review-pack review_pack.json \\
        --out-dir /path/to/world/

    python3 scripts/train_decision_policies_from_archive.py \\
        --archive-dir training_archive \\
        --out-dir /path/to/world/

Writes (whichever have enough data): dispute_policy_weights.json,
fission_policy_weights.json, migration_policy_weights.json,
founding_policy_weights.json -- see `hearthmind.simulation.engine.
DECISION_POLICY_FILENAMES` for the exact names `SimulationEngine`
looks for.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
from collections import Counter

sys.path.insert(0, ".")

from hearthmind.ml.decision_policy import (
    DISPUTE_POLICY_CONFIG, FISSION_POLICY_CONFIG, FOUNDING_POLICY_CONFIG, MIGRATION_POLICY_CONFIG,
    DecisionPolicy, build_distillation_examples,
)

HOLDOUT_FRACTION = 0.2
MIN_EXAMPLES_REQUIRED = 20

# task_name -> (filename, config, outcome_extractor(layer4_parsed_output) -> class-or-None)
_SITES = {
    "dispute": (
        "dispute_policy_weights.json", DISPUTE_POLICY_CONFIG,
        lambda parsed: parsed.get("outcome"),
    ),
    "fission": (
        "fission_policy_weights.json", FISSION_POLICY_CONFIG,
        lambda parsed: "depart" if parsed.get("depart") else "stay" if "depart" in parsed else None,
    ),
    "migration_decision": (
        "migration_policy_weights.json", MIGRATION_POLICY_CONFIG,
        lambda parsed: "depart" if parsed.get("depart") else "stay" if "depart" in parsed else None,
    ),
    "guild_founding": (
        "founding_policy_weights.json", FOUNDING_POLICY_CONFIG,
        lambda parsed: "found" if parsed.get("found") else "decline" if "found" in parsed else None,
    ),
}


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


def extract_pairs(examples: list, task: str, outcome_fn) -> tuple:
    states, classes = [], []
    for ex in examples:
        if ex.get("task") != task or ex.get("fallback_used"):
            continue
        structured_input = ex.get("layer1_structured_input") or {}
        parsed = ex.get("layer4_parsed_output") or {}
        cls_value = outcome_fn(parsed)
        if not structured_input or cls_value is None:
            continue
        states.append(structured_input)
        classes.append(cls_value)
    return states, classes


def train_one(config, states: list, classes: list, seed: int = 0):
    examples = build_distillation_examples(config, states, classes)
    if len(examples) < MIN_EXAMPLES_REQUIRED:
        return None, len(examples)
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n_holdout = max(1, int(len(shuffled) * HOLDOUT_FRACTION))
    holdout, train_examples = shuffled[:n_holdout], shuffled[n_holdout:]

    # Same lr=0.003/epochs=200 settled on for goal_policy against a
    # real ~400-example archive -- see train_goal_policy_from_
    # archive.py's own comment for the full plain-SGD-divergence
    # reasoning this reuses rather than re-deriving.
    policy = DecisionPolicy(config, seed=seed)
    result = policy.learn(train_examples, holdout, tick=0, epochs=200, learning_rate=0.003, seed=seed)

    correct = 0
    for ex in holdout:
        pred = policy.specialist.predict(ex.x)
        predicted_idx = pred.index(max(pred))
        true_idx = ex.y.index(1.0)
        if predicted_idx == true_idx:
            correct += 1
    holdout_accuracy = correct / len(holdout) if holdout else 0.0
    return (policy, result.accepted, holdout_accuracy), len(examples)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review-pack", help="Path to a review_pack.json export")
    parser.add_argument("--archive-dir", help="Path to a raw recorder archive directory")
    parser.add_argument("--out-dir", required=True, help="Directory to write trained weights files into (your world's db directory)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not args.review_pack and not args.archive_dir:
        parser.error("one of --review-pack or --archive-dir is required")

    review_pack = load_review_pack(args.review_pack) if args.review_pack else None
    os.makedirs(args.out_dir, exist_ok=True)

    trained_any = False
    for task, (filename, config, outcome_fn) in _SITES.items():
        examples = review_pack if review_pack is not None else load_archive_dir(args.archive_dir, task)
        states, classes = extract_pairs(examples, task, outcome_fn)
        print(f"\n[{task}] extracted {len(states)} real, non-fallback (state, outcome) pairs.")
        if states:
            print(f"[{task}] outcome distribution: {dict(Counter(classes))}")

        result, n_examples = train_one(config, states, classes, seed=args.seed)
        if result is None:
            print(f"[{task}] SKIPPED — only {n_examples} usable pairs, need at least {MIN_EXAMPLES_REQUIRED}.")
            continue
        policy, accepted, holdout_accuracy = result
        print(f"[{task}] Shadow gate: {'ACCEPTED' if accepted else 'REJECTED (kept fresh/prior weights)'}")
        print(f"[{task}] Holdout accuracy: {holdout_accuracy:.1%}")
        out_path = os.path.join(args.out_dir, filename)
        policy.save(out_path)
        print(f"[{task}] Wrote trained weights to {out_path}")
        trained_any = True

    if not trained_any:
        print("\nNo site had enough real recorded examples to train — let the world run "
              "longer (with the LLM enabled) before trying again.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
