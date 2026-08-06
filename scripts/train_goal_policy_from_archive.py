#!/usr/bin/env python3
"""Tier 6 L2.2's real offline trainer: consumes a real training-recorder
archive (either a `review_pack.json` export from `POST /recorder/
export-review-pack` / `scripts/recorder_tools.py export-review-pack`,
or a raw recorder archive directory of `<task>/<date>.jsonl` files) and
trains a `hearthmind.ml.goal_policy.GoalPolicy` via Phase 1 distillation
(teacher->student, from the real recorded `(structured_input, goal)`
pairs) -- Phase 2 (outcome-reweighted refinement) needs a real per-
example outcome label this project has no automated way to derive yet
(L2.1's own still-open job) and is deliberately not attempted here.

Only real `cognition`-task examples with `fallback_used=False` (a
genuine LLM answer, not another fallback draw) are used -- training on
the fallback's own output would be exactly the self-reinforcing loop
this project's standing guard exists to prevent.

Output: a weights file at the path `SimulationEngine` loads
automatically (`<directory next to your world's db_path>/goal_policy_
weights.json` -- see `hearthmind.simulation.engine.GOAL_POLICY_
FILENAME`/`_goal_policy_path_for`). Absent that file, every world runs
the exact original deterministic fallback -- dropping this file in is
the entire "wire it live" step.

Usage:
    python3 scripts/train_goal_policy_from_archive.py \\
        --review-pack review_pack.json \\
        --out /path/to/world/goal_policy_weights.json

    python3 scripts/train_goal_policy_from_archive.py \\
        --archive-dir training_archive \\
        --out /path/to/world/goal_policy_weights.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys

sys.path.insert(0, ".")

from hearthmind.ml.goal_policy import GOAL_VALUES, GoalPolicy, build_distillation_examples

# `layer1_structured_input`'s real field names (cognition.py's
# `_schedule_due_cognition`/`_run_cognition` structured_input dict) do
# NOT match GOAL_POLICY_SCHEMA's flat field names one-to-one -- traits/
# emotions arrive as nested dicts there, flat scalars here. This is the
# one real mapping between the two shapes.
HOLDOUT_FRACTION = 0.2
MIN_EXAMPLES_REQUIRED = 20


def to_goal_policy_state(structured_input: dict) -> dict:
    """`layer1_structured_input` (`SimulationEngine._schedule_due_
    cognition`'s `context_snapshot`, see `llm/cognition.py`) never
    actually recorded a `materials_critical` flag -- that signal only
    ever reaches the DETERMINISTIC fallback path (`fallback_goal`'s
    own `materials_critical` param), never the live-LLM prompt this
    archive's `cognition` examples were recorded from. Defaults to
    0.0 honestly rather than fabricating a value the real archive
    never captured."""
    traits = structured_input.get("traits") or {}
    emotions = structured_input.get("emotions") or {}
    return {
        "hunger": structured_input.get("hunger", 0.0),
        "energy": structured_input.get("energy", 0.0),
        "trait_resilience": traits.get("resilience", 0.0),
        "trait_sociability": traits.get("sociability", 0.0),
        "trait_ambition": traits.get("ambition", 0.0),
        "trait_openness": traits.get("openness", 0.0),
        "emotion_fear": emotions.get("fear", 0.0),
        "emotion_grief": emotions.get("grief", 0.0),
        "emotion_joy": emotions.get("joy", 0.0),
        "emotion_anger": emotions.get("anger", 0.0),
        "materials_critical": 0.0,
        "has_plan": 1.0 if structured_input.get("plan_intent") else 0.0,
    }


def load_review_pack(path: str) -> list:
    with open(path) as f:
        return json.load(f)


def load_archive_dir(archive_dir: str) -> list:
    """Reads every `<archive_dir>/cognition/*.jsonl` file directly --
    the raw recorder shape, one JSON object per line, same as `llm/
    recorder.py` writes and `scripts/recorder_tools.py` already reads
    for `stats`/`training-readiness`."""
    examples = []
    for path in sorted(glob.glob(os.path.join(archive_dir, "cognition", "*.jsonl"))):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                examples.append(json.loads(line))
    return examples


def extract_cognition_pairs(examples: list) -> tuple:
    """Returns `(states, goals)` -- only real, non-fallback `cognition`
    examples with a well-formed `layer4_parsed_output.goal`."""
    states, goals = [], []
    for ex in examples:
        if ex.get("task") != "cognition":
            continue
        if ex.get("fallback_used"):
            continue
        structured_input = ex.get("layer1_structured_input") or {}
        parsed = ex.get("layer4_parsed_output") or {}
        goal = parsed.get("goal")
        if not structured_input or goal not in GOAL_VALUES:
            continue
        states.append(to_goal_policy_state(structured_input))
        goals.append(goal)
    return states, goals


def train(states: list, goals: list, seed: int = 0) -> tuple:
    """Real held-out split (never trained on), matching this project's
    own standing shadow-gate discipline -- returns `(policy, accepted,
    holdout_accuracy)`."""
    examples = build_distillation_examples(states, goals)
    if len(examples) < MIN_EXAMPLES_REQUIRED:
        raise ValueError(
            f"only {len(examples)} usable real (state, goal) pairs found -- "
            f"need at least {MIN_EXAMPLES_REQUIRED} to train a meaningful policy"
        )
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    n_holdout = max(1, int(len(shuffled) * HOLDOUT_FRACTION))
    holdout, train_examples = shuffled[:n_holdout], shuffled[n_holdout:]

    # lr=0.003/epochs=200: measured directly against this project's own
    # real archives, not the module's bare defaults -- the same plain-
    # SGD numeric-divergence class already fixed once for the workload
    # forecaster (v1.34.257) reproduces here too: lr=0.05 (this script's
    # first draft) and even the shared L2.2/G1 default lr=0.03 reliably
    # diverge the candidate to a holdout loss WORSE than an untrained
    # random model within a realistic epoch count on a real 400+-example
    # archive, so the shadow gate (correctly) rejects every retrain
    # attempt. lr=0.003 is the highest rate found stable across a real
    # multi-epoch sweep (100-300 epochs) against this project's own
    # uploaded archive -- re-tune from a live holdout-accuracy reading
    # if a future archive's own feature distribution proves different.
    policy = GoalPolicy(seed=seed)
    result = policy.learn(train_examples, holdout, tick=0, epochs=200, learning_rate=0.003, seed=seed)

    correct = 0
    for ex in holdout:
        pred = policy.specialist.predict(ex.x)
        predicted_idx = pred.index(max(pred))
        true_idx = ex.y.index(1.0)
        if predicted_idx == true_idx:
            correct += 1
    holdout_accuracy = correct / len(holdout) if holdout else 0.0
    return policy, result.accepted, holdout_accuracy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review-pack", help="Path to a review_pack.json export")
    parser.add_argument("--archive-dir", help="Path to a raw recorder archive directory")
    parser.add_argument("--out", required=True, help="Output path for the trained weights JSON")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if not args.review_pack and not args.archive_dir:
        parser.error("one of --review-pack or --archive-dir is required")

    examples = load_review_pack(args.review_pack) if args.review_pack else load_archive_dir(args.archive_dir)
    print(f"Loaded {len(examples)} total recorded examples.")

    states, goals = extract_cognition_pairs(examples)
    print(f"Extracted {len(states)} real, non-fallback (state, goal) cognition pairs.")
    if states:
        from collections import Counter
        print(f"Goal distribution: {dict(Counter(goals))}")

    try:
        policy, accepted, holdout_accuracy = train(states, goals, seed=args.seed)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Shadow gate: {'ACCEPTED' if accepted else 'REJECTED (kept the fresh/prior weights instead)'}")
    print(f"Holdout accuracy: {holdout_accuracy:.1%}")

    policy.save(args.out)
    print(f"Wrote trained weights to {args.out}")
    print("Drop this file next to your world's db_path as 'goal_policy_weights.json' to wire it live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
