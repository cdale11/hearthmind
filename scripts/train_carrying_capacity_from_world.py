#!/usr/bin/env python3
"""Roadmap Group 1's real offline trainer: `hearthmind.ml.carrying_
capacity.CarryingCapacityModel`, wired into `Population.carrying_
capacity` as a bounded correction on top of the hand-tuned formula
(see that module's own docstring for the full design and the honest
label-derivation limitation).

**Needs no live-LLM training-recorder archive** -- like `train_
embedding_from_world.py`/`train_value_model_from_archive.py`, this
trains straight from a real, already-persisted `World`'s own db --
specifically its `metrics` table (`persistence/database.py`,
`SimulationEngine._log_daily_metrics`), a real per-sim-day time series
of `population`/`avg_hunger`/`deaths_starvation`/`materials`/
`currency`/`buildings_standing`/`tech_level` that has been logging
since long before this trainer existed.

**Honest gap, stated plainly** (same discipline as `train_value_model_
from_archive.py`'s own "one snapshot in time" note): `metrics` rows
are WORLD-scoped, summed across every named settlement -- a multi-
settlement world trains against the world aggregate, an approximation
of any one settlement's own real ceiling, not a genuine per-settlement
history. A world that hasn't ticked far enough to have accumulated a
real, meaningfully-varied `metrics` history (few rows, or a history
that never once saw elevated hunger) will train a model whose
correction stays close to a no-op -- that's the honest, correct
outcome for "not enough evidence yet," not a bug to work around.

Usage:
    python3 scripts/train_carrying_capacity_from_world.py \\
        --db-path /path/to/world/hearthmind.db \\
        --out-dir /path/to/world/

Writes carrying_capacity_model_weights.json -- see `hearthmind.
simulation.engine.CARRYING_CAPACITY_MODEL_FILENAME`/`_carrying_
capacity_model_path_for` for the exact name `SimulationEngine` looks
for.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")

from hearthmind.ml.carrying_capacity import (
    CarryingCapacityModel, carrying_capacity_features, compute_carrying_capacity_label, make_training_example,
)

MIN_EXAMPLES_REQUIRED = 10
METRICS_HISTORY_LIMIT = 5000
"""`persistence.snapshot.QUERY_LIMIT_MAX` -- the most `recent_metrics`
will ever return regardless of what's requested; asking for this many
just means "give me everything retained" without needing to know the
world's own `Config.metrics_log_retention` setting."""


def load_world_and_metrics(db_path: str):
    """Loads the real, already-persisted `World` plus its real
    `metrics` time series -- the same load path `server.py`/
    `SimulationEngine` themselves use for the world, and the same
    `recent_metrics` query `GET /metrics` uses for the history, not a
    parallel reader for either."""
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.persistence.snapshot import load_latest_snapshot, recent_metrics

    conn = connect(db_path)
    world = load_latest_snapshot(conn, Config(db_path=db_path))
    if world is None:
        raise ValueError(f"no snapshot found in {db_path!r} -- has this world ever ticked and saved?")
    rows = recent_metrics(conn, limit=METRICS_HISTORY_LIMIT)
    return world, rows


def build_examples(rows: list[dict]) -> list:
    """One example per real historical `metrics` row (oldest-first,
    `recent_metrics`'s own contract), each paired with a self-
    supervised label derived from that SAME row's real hunger reading
    plus the real starvation-death delta since the PRIOR row -- see
    `compute_carrying_capacity_label`'s own docstring for the exact
    formula and what it honestly is/isn't evidence of. The very first
    row has no prior row to diff against, so its starvation delta is
    0 (no claim of pressure, not a missing-data crash)."""
    examples = []
    prev_deaths = None
    for row in rows:
        population = float(row.get("population", 0))
        avg_hunger = float(row.get("avg_hunger", 0.0))
        deaths_starvation = float(row.get("deaths_starvation", 0))
        starvation_delta = 0.0 if prev_deaths is None else max(0.0, deaths_starvation - prev_deaths)
        prev_deaths = deaths_starvation

        if population <= 0.0:
            continue
        features = carrying_capacity_features(
            population=population, avg_hunger=avg_hunger,
            avg_energy=float(row.get("avg_energy", 0.0)), materials=float(row.get("materials", 0.0)),
            currency=float(row.get("currency", 0.0)), buildings_standing=float(row.get("buildings_standing", 0)),
            tech_level=float(row.get("tech_level", 0)),
        )
        label = compute_carrying_capacity_label(population, avg_hunger, starvation_delta)
        examples.append(make_training_example(features, label))
    return examples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, help="Path to your world's SQLite db")
    parser.add_argument("--out-dir", required=True, help="Directory to write carrying_capacity_model_weights.json into (your world's db directory)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--lr", type=float, default=0.01)
    args = parser.parse_args()

    world, rows = load_world_and_metrics(args.db_path)
    print(f"Loaded world at tick {world.clock.tick_count}, {len(rows)} real `metrics` row(s) "
          f"(one per sim-day this world has been running with a live SimulationEngine).")

    examples = build_examples(rows)
    print(f"Built {len(examples)} real (state, self-supervised label) pairs from the world's own history.")

    if len(examples) < MIN_EXAMPLES_REQUIRED:
        print(f"Not enough recorded `metrics` history (need at least {MIN_EXAMPLES_REQUIRED} usable days) — "
              "let this world run (and save) longer before trying again. A world's `metrics` table only "
              "grows while a real SimulationEngine has been ticking it, not on a fresh/rarely-run world.")
        return 1

    model = CarryingCapacityModel.new(seed=args.seed)
    model.train(examples, epochs=args.epochs, learning_rate=args.lr, seed=args.seed)
    loss = model.evaluate(examples)
    print(f"Training-set MSE (CAPACITY_OUTPUT_SCALE-scaled units): {loss:.4f}")

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "carrying_capacity_model_weights.json")
    model.save(out_path)
    print(f"Wrote trained weights to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
