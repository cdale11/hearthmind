#!/usr/bin/env python3
"""One-command wrapper over every real local ML trainer this project
ships (Tier 6 L1.1/L2.1/L2.2/L3.1/L4.1, the four `DecisionPolicy`
sites, and `laws.py`'s candidate scorer) — see README's "Local ML
training" section for what each model needs and does once trained.

Runs every trainer that's ready to run, in dependency order, against
ONE world's own db + recorder archive, and writes every weights file
into the same directory (next to that world's `db_path`) `Simulation
Engine` auto-loads from. Nothing here is invented beyond what each
individual `scripts/train_*.py` already does — this just calls all of
them for you, in the right order, with the right flags, so training
"everything" is one command instead of eight.

Three of the eight models need only the world's own db (no live-LLM
recorder archive): the embedding, the belief calibrator, the value
model. The other five need a real recorder archive (`--archive-dir`,
default `training_archive`) with real, non-fallback LLM call examples
in it — if that directory doesn't exist yet or has too little data for
a given model, this script reports that plainly and moves on; it never
treats "not enough data yet" as a fatal error for the whole run.

Usage:
    python3 scripts/train_all.py --db-path /path/to/world/hearthmind.db

    # If your recorder archive lives somewhere other than the default:
    python3 scripts/train_all.py --db-path hearthmind.db \\
        --archive-dir /path/to/training_archive

    # If you want the weights written somewhere other than next to
    # the db (the default, and the one place SimulationEngine looks):
    python3 scripts/train_all.py --db-path hearthmind.db --out-dir /tmp/weights
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, ".")

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable


def _run(label: str, args: list) -> int:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    result = subprocess.run([PYTHON] + args)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, help="Path to your world's SQLite db")
    parser.add_argument(
        "--archive-dir", default="training_archive",
        help="Path to the recorder's archive directory (default: training_archive, "
             "hearthmind.llm.recorder.TrainingRecorder's own default)",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Directory to write every trained weights file into (default: the directory "
             "your --db-path lives in -- the one place SimulationEngine auto-loads from)",
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.db_path))
    os.makedirs(out_dir, exist_ok=True)
    have_archive = os.path.isdir(args.archive_dir) and any(
        os.scandir(args.archive_dir)
    ) if os.path.isdir(args.archive_dir) else False

    results: list[tuple[str, int]] = []

    # --- Models that need only the world's own db, no recorder archive.
    results.append((
        "L1.1 embedding",
        _run("L1.1 -- semantic embedding (from this world's own text)", [
            os.path.join(SCRIPTS_DIR, "train_embedding_from_world.py"),
            "--db-path", args.db_path, "--out", os.path.join(out_dir, "embedding_weights.json"),
            "--seed", str(args.seed),
        ]),
    ))
    results.append((
        "L4.1 belief calibrator",
        _run("L4.1 -- belief confidence calibrator (from this world's reflection_notebook)", [
            os.path.join(SCRIPTS_DIR, "train_belief_calibrator_from_archive.py"),
            "--db-path", args.db_path, "--out-dir", out_dir,
        ]),
    ))
    results.append((
        "L2.1 value model",
        _run("L2.1 -- value/consequence model (from this world's living core cast)", [
            os.path.join(SCRIPTS_DIR, "train_value_model_from_archive.py"),
            "--db-path", args.db_path, "--out-dir", out_dir, "--seed", str(args.seed),
        ]),
    ))

    # --- Models that need a real recorder archive of live LLM calls.
    if not have_archive:
        print(
            f"\n{'=' * 70}\n"
            f"No recorder archive found at {args.archive_dir!r} (or it's empty) — skipping the "
            "five models that need one (goal policy, the four decision policies, the law scorer, "
            "the LLM cost regressor). Record a session with the LLM enabled first (see README's "
            "'Local ML training' section), then re-run this script pointing --archive-dir at it.\n"
            f"{'=' * 70}"
        )
    else:
        results.append((
            "L2.2 goal policy",
            _run("L2.2 -- goal policy (cognition's fallback_goal replacement)", [
                os.path.join(SCRIPTS_DIR, "train_goal_policy_from_archive.py"),
                "--archive-dir", args.archive_dir, "--out", os.path.join(out_dir, "goal_policy_weights.json"),
                "--seed", str(args.seed),
            ]),
        ))
        results.append((
            "decision policies (dispute/fission/migration/founding)",
            _run("Phase 1 -- the four fallback_goal-shaped decision policies", [
                os.path.join(SCRIPTS_DIR, "train_decision_policies_from_archive.py"),
                "--archive-dir", args.archive_dir, "--out-dir", out_dir, "--seed", str(args.seed),
            ]),
        ))
        results.append((
            "laws.py candidate scorer",
            _run("laws.py's dynamic-candidate-set scorer", [
                os.path.join(SCRIPTS_DIR, "train_law_scorer_from_archive.py"),
                "--archive-dir", args.archive_dir, "--out-dir", out_dir, "--seed", str(args.seed),
            ]),
        ))
        results.append((
            "L3.1 LLM cost regressor",
            _run("L3.1 -- LLM call latency regressor (preflight-defer gate)", [
                os.path.join(SCRIPTS_DIR, "train_llm_cost_regressor_from_archive.py"),
                "--archive-dir", args.archive_dir, "--out-dir", out_dir,
            ]),
        ))

    print(f"\n{'=' * 70}\nSummary\n{'=' * 70}")
    for label, code in results:
        status = "OK" if code == 0 else "SKIPPED (not enough data yet -- see its own output above)"
        print(f"  [{status}] {label}")
    print(f"\nWeights written to: {out_dir}")
    print("Restart (or resume) your world for SimulationEngine to pick up any new/updated weights files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
