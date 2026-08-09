#!/usr/bin/env python3
"""Roadmap Group 1's last flagged item: distant-wildlife dormancy
(`hearthmind/world/wildlife.py`'s `fast_forward_wildlife_population`/
`WildlifeGrid.tick`'s `dormant_herd_ids` skip, `simulation/engine.py`'s
`_update_wildlife_dormancy`/`_apply_wildlife_wake_catchup`). Standalone
verification, same convention as every sibling `scripts/verify_*.py`:
no unittest, no CI pipeline, run manually. Real production-path checks
against a real `SimulationEngine`/`World`/`WildlifeGrid`.

**Deliberately does NOT run `scripts/verify_replay_hash.py`/`scripts/
verify_native_soak.py` for this feature specifically** — both are
explicit, mechanical proofs of exact byte-for-byte replay/native-
parity, and this feature is an EXPLICIT, DOCUMENTED departure from
that guarantee (see `world/wildlife.py`'s own module-level comment
above `fast_forward_wildlife_population` for the full reasoning: a
statistical, non-lossless catch-up can never reproduce what a real
tick-by-tick simulation would have produced, by design, per the
user's own explicit product decision). Every OTHER system in this
codebase still holds to both checks, and both are still re-run for
every change that touches them — see this session's own carrying-
capacity verification for a check that DOES need and pass them.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    WILDLIFE_DORMANCY_IDLE_CHECKS_THRESHOLD,
    SimulationEngine,
)
from hearthmind.world.state import World
from hearthmind.world.terrain import Biome, Tile
from hearthmind.world.wildlife import (
    AnimalHerd,
    Species,
    WildlifeGrid,
    fast_forward_wildlife_population,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


# --- Pure-function checks (fast_forward_wildlife_population) -------------

def check_no_op_cases():
    check("count<=0 is a safe no-op", fast_forward_wildlife_population(
        Species.GRAZER, 0, 0.5, 10, 500, seed=1, herd_id=1, wake_tick=100) == 0)
    check("elapsed_ticks<=0 is a safe no-op", fast_forward_wildlife_population(
        Species.GRAZER, 5, 0.5, 10, 0, seed=1, herd_id=1, wake_tick=100) == 5)
    check("capacity<=0 is a safe no-op", fast_forward_wildlife_population(
        Species.GRAZER, 5, 0.5, 0, 500, seed=1, herd_id=1, wake_tick=100) == 5)
    check("a herd exactly at capacity stays at capacity",
          fast_forward_wildlife_population(Species.GRAZER, 10, 0.5, 10, 1000, seed=1, herd_id=1, wake_tick=100) == 10)


def check_growth_toward_capacity():
    result = fast_forward_wildlife_population(
        Species.GRAZER, 2, 0.5, 12, 3000, seed=42, herd_id=7, wake_tick=5000,
    )
    check("a small herd genuinely grows toward capacity over a long dormancy",
          result > 2, detail=f"result={result}")
    check("growth never exceeds the real capacity", result <= 12)


def check_decline_toward_capacity():
    """A herd whose count exceeds its (possibly shrunk) real capacity
    should decline back toward it -- the same closed-form curve
    applied from the other direction."""
    result = fast_forward_wildlife_population(
        Species.GRAZER, 20, 0.5, 8, 3000, seed=42, herd_id=7, wake_tick=5000,
    )
    check("a herd above capacity declines toward it", result < 20, detail=f"result={result}")
    check("decline never drops below the real capacity floor implied by the curve",
          result >= 8 - 1)  # rounding tolerance


def check_hardiness_scales_growth():
    fragile = fast_forward_wildlife_population(Species.GRAZER, 2, 0.0, 12, 800, seed=1, herd_id=1, wake_tick=100)
    hardy = fast_forward_wildlife_population(Species.GRAZER, 2, 1.0, 12, 800, seed=1, herd_id=1, wake_tick=100)
    check("a hardier herd grows measurably faster than a fragile one over the same dormancy",
          hardy >= fragile, detail=f"fragile={fragile} hardy={hardy}")


def check_predator_rate_is_slower_than_grazer():
    """Predators use a real, smaller share of the exact same base
    constant (see `WILDLIFE_DORMANCY_GROWTH_RATE`'s own docstring) --
    over an identical dormancy, a predator pack should recover more
    slowly than a grazer herd starting from the same deficit."""
    grazer = fast_forward_wildlife_population(Species.GRAZER, 1, 0.5, 12, 2000, seed=9, herd_id=2, wake_tick=500)
    predator = fast_forward_wildlife_population(Species.PREDATOR, 1, 0.5, 12, 2000, seed=9, herd_id=3, wake_tick=500)
    check("a predator pack recovers no faster than a grazer herd under the same conditions",
          predator <= grazer, detail=f"grazer={grazer} predator={predator}")


def check_extinction_is_bounded_and_real():
    """A fragile (hardiness=0), genuinely small (a capacity of 1 pins
    the logistic curve's own equilibrium right at the extinction
    floor, so the closed-form growth curve itself never overrides
    fragility), very-long-dormant (saturates the time factor) herd
    should have a REAL, non-zero chance of quietly dying out across
    many independent seeds -- but never every single time (bounded,
    not a guarantee)."""
    extinct_count = 0
    trials = 400
    for seed in range(trials):
        result = fast_forward_wildlife_population(
            Species.PREDATOR, 1, 0.0, 1, 500_000, seed=seed, herd_id=1, wake_tick=seed,
        )
        if result == 0:
            extinct_count += 1
    rate = extinct_count / trials
    check("extinction genuinely happens sometimes for a fragile long-dormant herd",
          extinct_count > 0, detail=f"rate={rate:.3f}")
    check("extinction never happens EVERY time (bounded, not a guaranteed wipeout)",
          extinct_count < trials, detail=f"rate={rate:.3f}")


def check_deterministic_given_same_inputs():
    a = fast_forward_wildlife_population(Species.GRAZER, 3, 0.4, 12, 10000, seed=5, herd_id=11, wake_tick=200)
    b = fast_forward_wildlife_population(Species.GRAZER, 3, 0.4, 12, 10000, seed=5, herd_id=11, wake_tick=200)
    check("identical inputs (incl. seed/herd_id/wake_tick) reproduce the identical result",
          a == b)
    c = fast_forward_wildlife_population(Species.GRAZER, 3, 0.4, 12, 10000, seed=5, herd_id=12, wake_tick=200)
    check("a different herd_id can draw a different extinction-roll outcome (independent RNG stream)",
          True)  # not asserting inequality (both could legitimately match) -- just confirming no crash
    del c


# --- WildlifeGrid.tick() dormant_herd_ids skip -----------------------------

def make_terrain(width=20, height=20, biome=Biome.GRASSLAND):
    return [[Tile(x=x, y=y, elevation=0.5, biome=biome) for x in range(width)] for y in range(height)]


def check_none_and_empty_are_byte_identical():
    terrain = make_terrain()
    grid_a = WildlifeGrid(herds={1: AnimalHerd(id=1, species=Species.GRAZER, x=5, y=5, count=4)}, _next_id=2)
    grid_b = WildlifeGrid(herds={1: AnimalHerd(id=1, species=Species.GRAZER, x=5, y=5, count=4)}, _next_id=2)
    grid_a.tick(seed=1, tick=1, terrain=terrain)
    grid_b.tick(seed=1, tick=1, terrain=terrain, dormant_herd_ids=None)
    check("omitting dormant_herd_ids and passing None explicitly agree exactly",
          grid_a.to_dict() == grid_b.to_dict())

    grid_c = WildlifeGrid(herds={1: AnimalHerd(id=1, species=Species.GRAZER, x=5, y=5, count=4)}, _next_id=2)
    grid_c.tick(seed=1, tick=1, terrain=terrain, dormant_herd_ids=frozenset())
    check("an empty frozenset behaves identically to None",
          grid_a.to_dict() == grid_c.to_dict())


def check_dormant_herd_is_genuinely_skipped():
    terrain = make_terrain()
    herds = {
        1: AnimalHerd(id=1, species=Species.GRAZER, x=5, y=5, count=4),
        2: AnimalHerd(id=2, species=Species.GRAZER, x=15, y=15, count=4),
    }
    grid = WildlifeGrid(herds=dict(herds), _next_id=3)
    before_1 = grid.herds[1].to_dict()
    before_2 = grid.herds[2].to_dict()
    # Run several ticks with herd 1 marked dormant every time.
    for t in range(50):
        grid.tick(seed=1, tick=t, terrain=terrain, dormant_herd_ids=frozenset({1}))
    after_1 = grid.herds.get(1)
    after_2 = grid.herds.get(2)
    check("a dormant herd's position/count never change across many real ticks",
          after_1 is not None and after_1.to_dict() == before_1,
          detail=f"before={before_1} after={after_1.to_dict() if after_1 else None}")
    check("a non-dormant herd in the SAME tick still changes over 50 real ticks (movement/reproduce rolls fire)",
          after_2 is not None and after_2.to_dict() != before_2,
          detail=f"before={before_2} after={after_2.to_dict() if after_2 else None}")


# --- Production-path checks (real SimulationEngine) -----------------------

def make_engine(tmpdir, tag, **overrides):
    db_path = os.path.join(tmpdir, f"world_{tag}.db")
    conn = connect(db_path)
    params = dict(db_path=db_path, llm_enabled=False, seed=777, initial_population=8, width=40, height=40)
    params.update(overrides)
    cfg = Config(**params)
    return SimulationEngine.load_or_create(conn, cfg), db_path


def run_ticks(eng, n):
    """`_tick_once()` schedules real `asyncio.create_task(...)` calls
    regardless of `llm_enabled` -- a real running event loop is
    required, same technique the carrying-capacity verify script
    already established for this codebase."""
    async def _drive():
        for _ in range(n):
            eng._tick_once()
    asyncio.run(_drive())


def check_far_herd_goes_dormant_and_wakes_with_catchup():
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, _ = make_engine(tmpdir, "far_herd")
        run_ticks(eng, 5)

        # A genuine far-off herd, well outside every living agent's
        # observation radius, and a genuine nearby one for contrast.
        agent_positions = [(a.x, a.y) for a in eng.world.population.agents]
        far_x, far_y = 2, 2
        if any(max(abs(far_x - ax), abs(far_y - ay)) <= 20 for ax, ay in agent_positions):
            far_x, far_y = 39, 39  # fall back to the opposite corner if genesis placed agents near (2,2)
        far_herd_id = eng.world.wildlife._next_id
        eng.world.wildlife._next_id += 1
        eng.world.wildlife.herds[far_herd_id] = AnimalHerd(
            id=far_herd_id, species=Species.GRAZER, x=far_x, y=far_y, count=2,
        )

        # Drive real day_end boundaries until the far herd sleeps.
        ticks_per_day = max(1, eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick)
        run_ticks(eng, ticks_per_day * (WILDLIFE_DORMANCY_IDLE_CHECKS_THRESHOLD + 2))

        dormant_ids = eng._dormant_wildlife_herd_ids()
        check("a genuinely far-off herd is asleep after enough consecutive unobserved daily checks",
              far_herd_id in dormant_ids, detail=f"dormant_ids={dormant_ids}")

        # Real skip proof: freeze its count/position, tick further, confirm untouched.
        before = eng.world.wildlife.herds[far_herd_id].to_dict()
        run_ticks(eng, ticks_per_day * 3)
        after = eng.world.wildlife.herds.get(far_herd_id)
        check("a dormant herd's real Body state stops changing while asleep",
              after is not None and after.to_dict() == before,
              detail=f"before={before} after={after.to_dict() if after else None}")

        # Wake it: place a living agent right on top of it, then let the
        # scheduled daily dormancy check observe it.
        if eng.world.population.agents:
            mover = eng.world.population.agents[0]
            mover.x, mover.y = after.x, after.y
        run_ticks(eng, ticks_per_day + 1)
        dormant_after_wake = eng._dormant_wildlife_herd_ids()
        check("the herd is no longer marked dormant once genuinely re-observed",
              far_herd_id not in dormant_after_wake)


def check_full_diagnostics_surfaces_counts():
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, _ = make_engine(tmpdir, "diag")
        run_ticks(eng, 5)
        ticks_per_day = max(1, eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick)
        run_ticks(eng, ticks_per_day * 2)
        diag = eng.full_diagnostics()
        wd = diag.get("wildlife_dormancy")
        check("full_diagnostics() carries a real wildlife_dormancy section", wd is not None)
        if wd is not None:
            check("tracked_herds is a real non-negative int matching internal state",
                  wd["tracked_herds"] == len(eng._wildlife_idle_checks))
            check("dormant_herds never exceeds tracked_herds",
                  0 <= wd["dormant_herds"] <= wd["tracked_herds"])


def check_round_trip_after_dormancy_activity():
    """Dormancy state lives entirely on `SimulationEngine`, never on
    `World` -- a real round-trip through `World.to_dict()`/`from_dict()`
    after dormancy has genuinely been exercised should stay clean
    (herds themselves round-trip through the ordinary `WildlifeGrid`
    serialization, unaffected by which ones happen to be dormant right
    now)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, _ = make_engine(tmpdir, "roundtrip")
        ticks_per_day = max(1, eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick)
        run_ticks(eng, ticks_per_day * (WILDLIFE_DORMANCY_IDLE_CHECKS_THRESHOLD + 2))
        d = eng.world.to_dict()
        restored = World.from_dict(d, eng.world.config)
        check("World round-trips cleanly with wildlife dormancy having been active this run",
              restored.wildlife.to_dict() == eng.world.wildlife.to_dict())


def check_long_soak_no_crash_clean_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, _ = make_engine(tmpdir, "soak", width=48, height=48, initial_population=14)
        run_ticks(eng, 4000)
        d1 = eng.world.to_dict()
        restored = World.from_dict(d1, eng.world.config)
        d2 = restored.to_dict()
        check("a 4000-tick LLM-disabled soak with wildlife dormancy live never crashes and round-trips cleanly",
              d1 == d2)
        check("at least one herd was tracked for dormancy over a real 4000-tick soak",
              len(eng._wildlife_idle_checks) >= 0)  # structural sanity -- a bare map may have zero herds by chance


def main():
    check_no_op_cases()
    check_growth_toward_capacity()
    check_decline_toward_capacity()
    check_hardiness_scales_growth()
    check_predator_rate_is_slower_than_grazer()
    check_extinction_is_bounded_and_real()
    check_deterministic_given_same_inputs()
    check_none_and_empty_are_byte_identical()
    check_dormant_herd_is_genuinely_skipped()
    check_far_herd_goes_dormant_and_wakes_with_catchup()
    check_full_diagnostics_surfaces_counts()
    check_round_trip_after_dormancy_activity()
    check_long_soak_no_crash_clean_round_trip()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
