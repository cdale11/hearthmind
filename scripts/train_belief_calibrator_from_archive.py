#!/usr/bin/env python3
"""Tier 6 L4.1's real offline trainer: `hearthmind.ml.belief_
calibration.BeliefConfidenceCalibrator`, wired (roadmap Phase 2) into
`SimulationEngine._maybe_schedule_self_tuning`'s conviction gate.

**Needs no live-LLM training-recorder archive at all** -- unlike most
Tier 6 trainers, the real (asserted confidence, real settled outcome)
pairs this model needs already live entirely inside a running world's
own `World.reflection_notebook` (`entry["confidence"]`/`entry
["status"]`), so this trains straight from a real, already-persisted
World the same way `train_embedding_from_world.py` does -- no export
step needed first.

Usage:
    python3 scripts/train_belief_calibrator_from_archive.py \\
        --db-path /path/to/world/hearthmind.db \\
        --out-dir /path/to/world/

Writes belief_calibrator_weights.json -- see `hearthmind.simulation.
engine.BELIEF_CALIBRATOR_FILENAME`/`_belief_calibrator_path_for` for
the exact name `SimulationEngine` looks for.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")

from hearthmind.ml.belief_calibration import BeliefConfidenceCalibrator, calibration_gap, extract_calibration_examples

MIN_EXAMPLES_REQUIRED = 10


def load_world(db_path: str):
    """Loads the real, already-persisted `World` at `db_path` -- the
    same load path `server.py`/`SimulationEngine` themselves use, not
    a parallel reader."""
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.persistence.snapshot import load_latest_snapshot

    conn = connect(db_path)
    world = load_latest_snapshot(conn, Config(db_path=db_path))
    if world is None:
        raise ValueError(f"no snapshot found in {db_path!r} -- has this world ever ticked and saved?")
    return world


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, help="Path to your world's SQLite db")
    parser.add_argument("--out-dir", required=True, help="Directory to write belief_calibrator_weights.json into (your world's db directory)")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--lr", type=float, default=0.1)
    args = parser.parse_args()

    world = load_world(args.db_path)
    print(f"Loaded world at tick {world.clock.tick_count}, "
          f"{len(world.reflection_notebook)} reflection_notebook entries total.")

    examples = extract_calibration_examples(world.reflection_notebook)
    print(f"Extracted {len(examples)} real settled (stated confidence, held-up-or-not) pairs "
          f"({sum(1 for _, y in examples if y == 1.0)} supported, "
          f"{sum(1 for _, y in examples if y == 0.0)} rejected). "
          f"'open'/'superseded' entries carry no settled outcome and are correctly excluded.")

    if len(examples) < MIN_EXAMPLES_REQUIRED:
        print(f"Not enough settled hypotheses (need at least {MIN_EXAMPLES_REQUIRED}) — "
              "let this world run longer (with the LLM enabled) before trying again. "
              "Reflection's own multi-cycle evidence loop settles hypotheses slowly by design.")
        return 1

    gap = calibration_gap(examples)
    if gap is not None:
        direction = "OVERconfident" if gap > 0 else "UNDERconfident" if gap < 0 else "well-calibrated"
        print(f"Pre-training calibration gap: {gap:+.3f} (stated confidence is systematically {direction}).")

    calibrator = BeliefConfidenceCalibrator().fit(examples, epochs=args.epochs, lr=args.lr)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "belief_calibrator_weights.json")
    calibrator.save(out_path)
    print(f"Wrote trained weights to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
