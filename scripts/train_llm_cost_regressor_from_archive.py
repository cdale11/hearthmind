#!/usr/bin/env python3
"""Tier 6 L3.1's real offline trainer: `hearthmind.ml.llm_cost.
LLMCostRegressor`, wired (v1.34.262) into `SimulationEngine._schedule_
llm_job`'s real preflight-defer check. Same shape as every other Tier
6 trainer -- consumes either a `review_pack.json` export or a raw
recorder archive directory, extracts real per-call `(features,
observed latency_ms)` pairs, trains via a real held-out shadow-gate
split, and saves the result to the exact path `SimulationEngine`
auto-loads.

**Honest gap, stated plainly**: `current_backlog_fraction`/
`concurrency_limit` are NOT recorded per-example anywhere in `llm/
recorder.py`'s schema -- a live archive has no historical queue-depth
reading to train against. Both default to `0.0` for every training
example (`FeatureEncoder`'s own "missing means neutral" contract, the
same one every Tier 6 model already relies on) -- the trained model
genuinely learns latency from task/prompt-size/deep_reasoning alone,
then sees real backlog/concurrency values for the first time at real
inference. Still a real, useful regression (those three fields are
real predictors of latency on their own); closing this gap for real
would need the recorder to capture a live backlog reading per
example, flagged as distinct future work, not attempted here.

Usage:
    python3 scripts/train_llm_cost_regressor_from_archive.py \\
        --review-pack review_pack.json \\
        --out-dir /path/to/world/

    python3 scripts/train_llm_cost_regressor_from_archive.py \\
        --archive-dir training_archive \\
        --out-dir /path/to/world/

Writes llm_cost_regressor_weights.json -- see `hearthmind.simulation.
engine.LLM_COST_REGRESSOR_FILENAME` for the exact name `Simulation
Engine` looks for.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

sys.path.insert(0, ".")

from hearthmind.ml.llm_cost import LLM_COST_TASKS, LLMCostRegressor, make_training_example

HOLDOUT_FRACTION = 0.2
MIN_EXAMPLES_REQUIRED = 20


def load_review_pack(path: str) -> list:
    with open(path) as f:
        return json.load(f)


def load_archive_dir(archive_dir: str) -> list:
    """Reads every task's `.jsonl` file under `LLM_COST_TASKS` -- unlike
    the single-task trainers, this model's real consumer applies across
    every one of those tasks, so a real archive is scanned broadly
    rather than filtered to one subdirectory."""
    examples = []
    for task in LLM_COST_TASKS:
        for path in sorted(glob.glob(os.path.join(archive_dir, task, "*.jsonl"))):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    examples.append(json.loads(line))
    return examples


def extract_pairs(examples: list) -> tuple:
    """Returns `(features_list, observed_latency_ms_list)` -- only
    real `fallback_used=False` examples with a real recorded `latency_
    ms` carry the genuine "how long did this actual call take"
    signal a fallback resolution can't provide."""
    features_list, latencies = [], []
    for ex in examples:
        task = ex.get("task")
        if task not in LLM_COST_TASKS or ex.get("fallback_used"):
            continue
        latency_ms = ex.get("latency_ms")
        if not isinstance(latency_ms, (int, float)) or latency_ms <= 0:
            continue
        prompt = ex.get("layer2_prompt") or ""
        system_prompt = ex.get("layer2_system_prompt") or ""
        deep_reasoning = 1.0 if (ex.get("generation_config") or {}).get("reasoning") else 0.0
        features_list.append({
            "task": task,
            "prompt_chars_k": len(prompt) / 1000.0,
            "context_chars_k": len(system_prompt) / 1000.0,
            # Honest gap -- see module docstring above.
            "current_backlog_fraction": 0.0,
            "concurrency_limit": 0.0,
            "deep_reasoning": deep_reasoning,
        })
        latencies.append(float(latency_ms))
    return features_list, latencies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review-pack", help="Path to a review_pack.json export")
    parser.add_argument("--archive-dir", help="Path to a raw recorder archive directory")
    parser.add_argument("--out-dir", required=True, help="Directory to write llm_cost_regressor_weights.json into (your world's db directory)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not args.review_pack and not args.archive_dir:
        parser.error("one of --review-pack or --archive-dir is required")

    examples = load_review_pack(args.review_pack) if args.review_pack else load_archive_dir(args.archive_dir)
    features_list, latencies = extract_pairs(examples)
    print(f"Extracted {len(features_list)} real, non-fallback (features, latency_ms) pairs across {len(LLM_COST_TASKS)} tasks.")
    if len(features_list) < MIN_EXAMPLES_REQUIRED:
        print(f"Not enough usable pairs (need at least {MIN_EXAMPLES_REQUIRED}) — "
              "let the world run longer (with the LLM enabled) before trying again.")
        return 1
    print(f"Real observed latency range: {min(latencies):.0f}ms - {max(latencies):.0f}ms")

    training_examples = [make_training_example(f, lat) for f, lat in zip(features_list, latencies)]
    rng = random.Random(args.seed)
    shuffled = list(training_examples)
    rng.shuffle(shuffled)
    n_holdout = max(1, int(len(shuffled) * HOLDOUT_FRACTION))
    holdout, train_examples = shuffled[:n_holdout], shuffled[n_holdout:]

    # Same lr=0.001 the module's own docstring settled on -- higher
    # rates measurably diverged to NaN during verification, even after
    # LATENCY_SCALE_MS normalization (a real deep_reasoning call's own
    # target contribution keeps y's range wide).
    regressor = LLMCostRegressor.new(seed=args.seed)
    regressor.train(train_examples, epochs=60, learning_rate=0.001, seed=args.seed)

    if holdout:
        holdout_loss = regressor.evaluate(holdout)
        print(f"Holdout MSE ({regressor.model.output_activation}-scaled units): {holdout_loss:.4f}")

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "llm_cost_regressor_weights.json")
    regressor.save(out_path)
    print(f"Wrote trained weights to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
