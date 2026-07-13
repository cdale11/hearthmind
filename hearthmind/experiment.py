"""Headless batch experiment runner — the A/B harness that makes the
per-sim-day `metrics` table (persistence/database.py) scientifically
useful. Runs N seeds under a chosen configuration (LLM on/off, Phase G
intensity, tick budget) with no API server and no wall-clock pacing,
then exports each run's metrics time-series to CSV — one file per run,
one row per sim-day, ready for pandas/spreadsheet comparison.

This is deliberately a *runner*, not an analysis suite: the July 2026
architecture review's finding was that Hearthmind could not answer
"did the LLM measurably change macro outcomes?" because no fixed-cadence
series existed and no tool produced comparable runs. The metrics table
closed the first gap; this closes the second. Typical ablation:

    hearthmind-experiment --seeds 1,2,3 --ticks 30000 --no-llm --label baseline
    hearthmind-experiment --seeds 1,2,3 --ticks 30000 --label with-llm

then compare the paired CSVs. Runs use an in-memory database (nothing
here should ever touch a real world's save) and the real
SimulationEngine, so every mechanic — including fallback cognition,
backpressure, and the town brain — behaves exactly as in a live run.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from hearthmind.config import Config
from hearthmind.persistence import database
from hearthmind.simulation.engine import SimulationEngine

PROGRESS_EVERY_TICKS = 5000
"""Coarse stderr progress marker so a long multi-seed batch is visibly
alive without drowning the terminal."""


async def _run_one(seed: int, ticks: int, llm_enabled: bool, phase_g_intensity: float):
    conn = database.connect(":memory:")
    config = Config(
        seed=seed, llm_enabled=llm_enabled, api_enabled=False, db_path=":memory:",
        phase_g_intensity=phase_g_intensity,
        snapshot_every_ticks=10**9,  # snapshots are dead weight for a throwaway run
    )
    engine = SimulationEngine.load_or_create(conn, config)
    for tick in range(ticks):
        engine._tick_once()
        if engine._background_tasks:
            # Let LLM/fallback jobs resolve between ticks, same ordering a
            # live run's event loop gives them — without this, results
            # would all apply in one burst at the end.
            await asyncio.gather(*list(engine._background_tasks), return_exceptions=True)
        if (tick + 1) % PROGRESS_EVERY_TICKS == 0:
            print(f"  seed {seed}: tick {tick + 1}/{ticks}", file=sys.stderr)
    return conn, engine.world


def _export_metrics(conn, out_path: Path) -> int:
    rows = conn.execute("SELECT tick, metrics_json FROM metrics ORDER BY id").fetchall()
    if not rows:
        return 0
    # Union of keys across rows, so a mid-run metrics-schema addition
    # doesn't silently drop columns.
    keys: list[str] = []
    parsed = []
    for tick, metrics_json in rows:
        entry = json.loads(metrics_json)
        entry["tick"] = tick
        parsed.append(entry)
        for key in entry:
            if key not in keys:
                keys.append(key)
    with out_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(parsed)
    return len(parsed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seeds", default="1", help="comma-separated world seeds, e.g. 1,2,3")
    parser.add_argument("--ticks", type=int, default=20000, help="ticks to simulate per run")
    parser.add_argument("--no-llm", action="store_true", help="deterministic fallbacks only (ablation baseline)")
    parser.add_argument("--phase-g-intensity", type=float, default=1.0, help="0.0 disables temperament drift and omens")
    parser.add_argument("--label", default="run", help="prefix for output CSV filenames")
    parser.add_argument("--out", default="experiments", help="output directory for CSVs")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    for seed in seeds:
        print(f"running: seed={seed} ticks={args.ticks} llm={not args.no_llm} "
              f"phase_g={args.phase_g_intensity}", file=sys.stderr)
        conn, world = asyncio.run(
            _run_one(seed, args.ticks, llm_enabled=not args.no_llm,
                     phase_g_intensity=args.phase_g_intensity)
        )
        out_path = out_dir / f"{args.label}_seed{seed}.csv"
        row_count = _export_metrics(conn, out_path)
        summary = world.population.summary()
        print(f"  -> {out_path} ({row_count} sim-days; final pop {summary['total']}, "
              f"starved {world.population.deaths_starvation}, "
              f"old age {world.population.deaths_old_age})", file=sys.stderr)
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
