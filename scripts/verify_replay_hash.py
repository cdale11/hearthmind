#!/usr/bin/env python3
"""B15.1 "Replay-hash equivalence test in CI" (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B — The Adaptive Runtime). The doc's own SEQUENCE
names this the very first Runtime item to build: "the safety net every
later change leans on." Nothing in Part B (task scheduling, budgets,
dormancy, parallelism) exists yet in this codebase — this script ships
the baseline it depends on: mechanical proof that, TODAY, the same
seed with the LLM disabled produces byte-identical world state across
two fully independent runs. Every future runtime feature (B2 budgets,
B4 dormancy, B10 locality-driven parallelism, B13 self-tuning) must be
checked against this SAME script with its own toggle enabled/disabled
— see B15.1's own text — once one exists to toggle; until then, this
is "replay-hash holds with no runtime at all," the floor the doc's
"strict Body, adaptive cognition-breadth" boundary (B15.2) is built on.

Deliberately a standalone script, not a pytest suite — CLAUDE.md's
standing rule is that the automated test suite is unused; verification
is live diagnostic reports plus ad-hoc scripts run in this environment,
same precedent as `verify_native_soak.py` (which this script mirrors
in structure: per-tick `World.to_dict()` hashing, `sort_keys=True` so
dict-insertion order never causes a false-positive divergence, a real
`SimulationEngine.load_or_create` over a real sqlite file rather than
an in-memory shortcut). The one deliberate difference: `verify_native_
soak.py` compares native-vs-Python-fallback of the SAME process; this
compares two INDEPENDENT process runs of the identical config (default
`--processes`, real subprocess isolation, since that's what a genuine
"same seed on a different run/machine" replay claim actually needs to
survive — Python's hash randomization, thread/OS scheduling jitter,
and any accidental reliance on object-identity ordering would only
ever surface across a real process boundary, never within one).

Usage: python3 scripts/verify_replay_hash.py [--ticks N] [--seeds S,S,S]
       [--in-process]   # faster, weaker: skip subprocess isolation
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parent.parent


def _state_hash(world) -> str:
    payload = json.dumps(world.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


async def _run_in_process(seed: int, ticks: int, width: int, height: int) -> list[str]:
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    hashes: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        conn = connect(f"{d}/replay.db")
        cfg = Config(
            db_path=f"{d}/replay.db", llm_enabled=False, seed=seed,
            initial_population=10, width=width, height=height,
        )
        eng = SimulationEngine.load_or_create(conn, cfg)
        for _ in range(ticks):
            eng._tick_once()
            await asyncio.sleep(0)
            hashes.append(_state_hash(eng.world))
    return hashes


# The subprocess entry point: prints one hash per line to stdout so the
# parent process can capture a per-tick hash sequence exactly like the
# in-process path does, without importing this module's own argparse
# CLI into a child that only needs the one function.
_SUBPROCESS_DRIVER = """
import asyncio, hashlib, json, sys, tempfile
sys.path.insert(0, {root!r})
from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

def _hash(world):
    payload = json.dumps(world.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

async def main():
    with tempfile.TemporaryDirectory() as d:
        conn = connect(f"{{d}}/replay.db")
        cfg = Config(
            db_path=f"{{d}}/replay.db", llm_enabled=False, seed={seed},
            initial_population=10, width={width}, height={height},
        )
        eng = SimulationEngine.load_or_create(conn, cfg)
        for _ in range({ticks}):
            eng._tick_once()
            await asyncio.sleep(0)
            print(_hash(eng.world))

asyncio.run(main())
"""


def _run_subprocess(seed: int, ticks: int, width: int, height: int) -> list[str]:
    script = _SUBPROCESS_DRIVER.format(root=str(_ROOT), seed=seed, ticks=ticks, width=width, height=height)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, cwd=str(_ROOT),
    )
    return result.stdout.strip().splitlines()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticks", type=int, default=3000)
    parser.add_argument("--seeds", type=str, default="1,55,999")
    parser.add_argument("--width", type=int, default=48)
    parser.add_argument("--height", type=int, default=48)
    parser.add_argument(
        "--in-process", action="store_true",
        help="Run both replay attempts in this same process (faster, but doesn't exercise a real "
             "process boundary — hash randomization/OS scheduling differences can't surface).",
    )
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]

    exit_code = 0
    for seed in seeds:
        if args.in_process:
            hashes_a = await _run_in_process(seed, args.ticks, args.width, args.height)
            hashes_b = await _run_in_process(seed, args.ticks, args.width, args.height)
        else:
            hashes_a = _run_subprocess(seed, args.ticks, args.width, args.height)
            hashes_b = _run_subprocess(seed, args.ticks, args.width, args.height)
        if hashes_a == hashes_b and len(hashes_a) == args.ticks:
            print(f"seed={seed} ticks={args.ticks}: MATCH (two independent replays, identical world state every tick)")
            continue
        exit_code = 1
        if len(hashes_a) != args.ticks or len(hashes_b) != args.ticks:
            print(f"seed={seed}: MISMATCH — expected {args.ticks} hashes, got {len(hashes_a)}/{len(hashes_b)} "
                  f"(a run likely crashed; check stderr by re-running with --in-process for a traceback)")
            continue
        first_divergence = next(
            (i for i, (a, b) in enumerate(zip(hashes_a, hashes_b)) if a != b), None,
        )
        print(f"seed={seed}: MISMATCH — replay first diverges at tick {first_divergence}")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
