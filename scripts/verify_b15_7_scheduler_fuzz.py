#!/usr/bin/env python3
"""B15.7 "Fuzz the scheduler" (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B — The Adaptive Runtime, B15's semantic-safety section). B15.1's
own `scripts/verify_replay_hash.py` proves replay-hash equivalence for
ONE fixed default runtime config; B15.2's own text is the broader
claim this script actually stress-tests: "the deterministic Body is
replay-identical regardless of any runtime decision -- budgets,
dormancy, batching, parallelism, host."

The correct reading of that claim, worked out carefully before writing
this script (recorded here since it's easy to get wrong): it does NOT
mean two DIFFERENT runtime configs must produce the SAME world state
-- B15.2's own "adaptive" half explicitly allows cognition breadth
(and therefore which settlement/institution/idea's Mind-layer content
gets attention this cycle -- beliefs, narration, dormancy-narrowed
`_job_target` rotations) to legitimately differ by hardware/config,
with "the same seed on different hardware produces different stories"
named as an ACCEPTED consequence, not a bug. What must hold is the
narrower, real claim B15.1 already proves for ONE config: for a GIVEN
randomized runtime configuration, running that SAME configuration
twice must still be byte-identical -- no hidden real-threading race,
unseeded RNG, or unstable dict/set iteration order sneaking into any
runtime knob's own code path. This script is `verify_replay_hash.py`'s
own technique (two independent subprocess runs, `World.to_dict()`
hashed per tick), looped over K RANDOMIZED runtime configurations
instead of the one fixed default -- a fuzz in the literal sense: it
can catch a nondeterminism bug that the single default config's own
values happen not to exercise (e.g., a dormancy threshold that only
diverges at a specific idle-check boundary, or a concurrency limit
that only races above some queue depth).

Three runtime dimensions randomized per trial, matching B15.7's own
named list ("task order/budgets/dormancy"): `Config.llm_max_
concurrent` (budgets/parallelism -- LLM is disabled for this whole
script so this is inert w.r.t. real LLM calls, but still exercises
`CognitionRunner`'s semaphore-sizing code path); `Config.snapshot_
every_ticks` (batching -- the persistence cadence); and `SimulationEngine.
_last_strategy.dormancy_aggressiveness` (dormancy -- forced directly
post-construction, same field `_dormancy_idle_threshold` already reads,
see that method's own docstring). "Task order" itself has no live
fuzz surface in the real engine: every B0.3-migrated job runs through
its OWN dedicated single-task `Scheduler` (see `engine.py`'s own
`_RUNTIME_SCHEDULED_JOB_SCHEDULERS` comment for why -- a shared
registry would double-execute tasks), so there is no multi-task
registration order left to reorder in production; `scripts/verify_
scheduler.py`/`verify_task_graph.py` already separately prove the
standalone B1/B2 primitives themselves are registration-order-
independent for a synthetic multi-task registry.

Usage: python3 scripts/verify_b15_7_scheduler_fuzz.py [--trials N] [--ticks N] [--seed S]
"""
from __future__ import annotations

import argparse
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parent.parent

_CONCURRENCY_CHOICES = (1, 2, 3, 4)
_SNAPSHOT_INTERVAL_CHOICES = (10, 40, 60, 200)
_DORMANCY_CHOICES = ("low", "normal", "high")

# The subprocess entry point: constructs one engine under a caller-
# supplied randomized runtime config, ticks it, and prints one
# World.to_dict() hash per tick -- the same shape `verify_replay_
# hash.py`'s own `_SUBPROCESS_DRIVER` uses, extended with the three
# fuzzed knobs.
_SUBPROCESS_DRIVER = """
import asyncio, hashlib, json, sys, tempfile
sys.path.insert(0, {root!r})
from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.simulation.hardware_profile import Strategy

def _hash(world):
    payload = json.dumps(world.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

async def main():
    with tempfile.TemporaryDirectory() as d:
        conn = connect(f"{{d}}/fuzz.db")
        cfg = Config(
            db_path=f"{{d}}/fuzz.db", llm_enabled=False, seed={seed},
            initial_population=10, width={width}, height={height},
            llm_max_concurrent={llm_max_concurrent}, snapshot_every_ticks={snapshot_every_ticks},
        )
        eng = SimulationEngine.load_or_create(conn, cfg)
        eng._last_strategy = Strategy(
            llm_max_concurrent_hint={llm_max_concurrent}, worker_count_hint=1,
            cache_size_hint="normal", dormancy_aggressiveness={dormancy_aggressiveness!r},
        )
        for _ in range({ticks}):
            eng._tick_once()
            await asyncio.sleep(0)
            print(_hash(eng.world))

asyncio.run(main())
"""


def _run_subprocess(seed: int, ticks: int, width: int, height: int, config: dict) -> list[str]:
    script = _SUBPROCESS_DRIVER.format(
        root=str(_ROOT), seed=seed, ticks=ticks, width=width, height=height, **config,
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, cwd=str(_ROOT),
    )
    return result.stdout.strip().splitlines()


def _random_config(rng: random.Random) -> dict:
    return {
        "llm_max_concurrent": rng.choice(_CONCURRENCY_CHOICES),
        "snapshot_every_ticks": rng.choice(_SNAPSHOT_INTERVAL_CHOICES),
        "dormancy_aggressiveness": rng.choice(_DORMANCY_CHOICES),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=8)
    parser.add_argument("--ticks", type=int, default=300)
    parser.add_argument("--seed", type=int, default=777, help="World seed held fixed across every trial.")
    parser.add_argument("--fuzz-seed", type=int, default=2026, help="Seeds the config-randomizer itself.")
    parser.add_argument("--width", type=int, default=40)
    parser.add_argument("--height", type=int, default=40)
    args = parser.parse_args()

    rng = random.Random(args.fuzz_seed)
    exit_code = 0
    for trial in range(args.trials):
        config = _random_config(rng)
        hashes_a = _run_subprocess(args.seed, args.ticks, args.width, args.height, config)
        hashes_b = _run_subprocess(args.seed, args.ticks, args.width, args.height, config)
        label = (
            f"trial {trial + 1}/{args.trials} (llm_max_concurrent={config['llm_max_concurrent']}, "
            f"snapshot_every_ticks={config['snapshot_every_ticks']}, "
            f"dormancy_aggressiveness={config['dormancy_aggressiveness']!r})"
        )
        if hashes_a == hashes_b and len(hashes_a) == args.ticks:
            print(f"{label}: MATCH (two independent replays under this randomized config, identical every tick)")
            continue
        exit_code = 1
        if len(hashes_a) != args.ticks or len(hashes_b) != args.ticks:
            print(f"{label}: MISMATCH — expected {args.ticks} hashes, got {len(hashes_a)}/{len(hashes_b)} "
                  f"(a run likely crashed under this config)")
            continue
        first_divergence = next(
            (i for i, (a, b) in enumerate(zip(hashes_a, hashes_b)) if a != b), None,
        )
        print(f"{label}: MISMATCH — replay first diverges at tick {first_divergence}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
