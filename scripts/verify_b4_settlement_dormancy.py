#!/usr/bin/env python3
"""Tier 5 B4.2, fourth dormancy candidate ("inactive settlements") —
verifies `SimulationEngine._update_settlement_dormancy`/`_settlement_
fingerprint` and `_job_target`'s dormant-exclusion, real production-
path checks against a real `SimulationEngine`/`World`, no unittest,
same standalone-script convention as every sibling `verify_*.py`."""
from __future__ import annotations

import asyncio
import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.settlement.buildings import Settlement
from hearthmind.simulation.engine import (
    SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD,
    SimulationEngine,
    _settlement_fingerprint,
)

CHECKS = 0
FAILURES: list[str] = []
_TMPDIR = tempfile.mkdtemp()
_COUNTER = 0


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def make_engine() -> SimulationEngine:
    global _COUNTER
    _COUNTER += 1
    db_path = f"{_TMPDIR}/b4_settlement_dormancy_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=777,
        initial_population=8, width=24, height=24,
    )
    return SimulationEngine.load_or_create(conn, cfg)


async def main() -> int:
    eng = make_engine()
    settlement = eng.world.settlement
    settlement.name = "Testford"
    key = str(settlement.id)

    # First check registers, never sleeps immediately.
    eng._update_settlement_dormancy()
    check("fresh settlement registers ACTIVE (never asleep on first check)",
          eng._settlement_dormancy.is_scheduled(key))
    check("fresh settlement's fingerprint recorded", settlement.id in eng._settlement_fingerprint)

    # Unchanged fingerprint for the threshold's worth of checks -> sleeps.
    # (Force population/era/buildings/tech_level all static across checks —
    # no ticking, so nothing else can perturb the fingerprint.)
    for _ in range(SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD - 1):
        eng._update_settlement_dormancy()
    check("idle settlement still awake just below threshold", eng._settlement_dormancy.is_scheduled(key))
    eng._update_settlement_dormancy()
    check("idle settlement asleep once threshold crossed", not eng._settlement_dormancy.is_scheduled(key))

    # A real era advance wakes it immediately.
    settlement.era = "bronze_age"
    eng._update_settlement_dormancy()
    check("a real era advance wakes a sleeping settlement immediately",
          eng._settlement_dormancy.is_scheduled(key))
    check("waking resets the idle-check counter", eng._settlement_idle_checks[settlement.id] == 0)

    # A settlement removed from World.settlements drops out of tracking.
    eng.world.settlements = [s for s in eng.world.settlements if s.id != settlement.id]
    eng._update_settlement_dormancy()
    check("a removed settlement is no longer tracked", settlement.id not in eng._settlement_fingerprint)

    # `_job_target`'s round-robin excludes a sleeping settlement from its
    # candidate pool, falls back to the full list when every named
    # settlement is asleep at once.
    eng2 = make_engine()
    s2a = eng2.world.settlement
    s2a.name = "Active Town"
    s2b = Settlement(id=1, name="Sleepy Town")
    eng2.world.settlements.append(s2b)
    for _ in range(SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng2._update_settlement_dormancy()
    # Wake "Active Town" via a real era advance right before the real roll.
    s2a.era = "bronze_age"
    eng2._update_settlement_dormancy()
    check("active settlement awake, sleepy settlement asleep after divergent history",
          eng2._settlement_dormancy.is_scheduled(str(s2a.id))
          and not eng2._settlement_dormancy.is_scheduled(str(s2b.id)))

    minutes_per_month = eng2.world.config.minutes_per_day * (eng2.world.config.days_per_month[0])
    ticks_per_month = max(1, minutes_per_month // max(1, eng2.world.config.sim_minutes_per_tick))
    rotation_targets = set()
    for month in range(24):
        eng2.world.clock.tick_count = month * ticks_per_month
        rotation_targets.add(eng2._job_target().name)
    check("dormant-exclusion narrows the round-robin pool to just the awake settlement",
          rotation_targets == {"Active Town"})

    # Fallback: everything asleep -> full list, `_job_target` never stalls.
    eng3 = make_engine()
    s3a = eng3.world.settlement
    s3a.name = "Quiet One"
    s3b = Settlement(id=1, name="Quiet Two")
    eng3.world.settlements.append(s3b)
    for _ in range(SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng3._update_settlement_dormancy()
    check("both settlements genuinely asleep after sustained idleness",
          not eng3._settlement_dormancy.is_scheduled(str(s3a.id))
          and not eng3._settlement_dormancy.is_scheduled(str(s3b.id)))
    minutes_per_month3 = eng3.world.config.minutes_per_day * (eng3.world.config.days_per_month[0])
    ticks_per_month3 = max(1, minutes_per_month3 // max(1, eng3.world.config.sim_minutes_per_tick))
    rotation_targets3 = set()
    for month in range(24):
        eng3.world.clock.tick_count = month * ticks_per_month3
        rotation_targets3.add(eng3._job_target().name)
    check("fallback to the full list when every settlement is asleep at once",
          rotation_targets3 == {"Quiet One", "Quiet Two"})

    # Single-settlement worlds are unaffected in the common case: with only
    # one named settlement, `_job_target` always returns it regardless of
    # dormancy state (the "awake" pool is empty -> fallback -> the one
    # settlement is still the only entry in the full list).
    eng4 = make_engine()
    s4 = eng4.world.settlement
    s4.name = "Lonetown"
    for _ in range(SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng4._update_settlement_dormancy()
    check("a lone settlement is genuinely asleep after sustained idleness",
          not eng4._settlement_dormancy.is_scheduled(str(s4.id)))
    check("but _job_target still returns the one real settlement (fallback, real no-op)",
          eng4._job_target().name == "Lonetown")

    # Fingerprint is a pure function of real coarse structural state.
    check("_settlement_fingerprint reflects population/era/buildings/tech_level",
          _settlement_fingerprint(s4, 5) == (5, s4.era, len(s4.buildings), s4.tech_level))
    fp_before = _settlement_fingerprint(s4, 5)
    s4.tech_level += 1
    fp_after = _settlement_fingerprint(s4, 5)
    check("_settlement_fingerprint changes with a real tech_level bump", fp_before != fp_after)

    # Real dispatch wiring: the settlement_dormancy scheduler's own
    # registered Task fires `_update_settlement_dormancy` only on a real
    # month_end publish (same ON_EVENT machinery the three siblings use).
    eng5 = make_engine()
    s5 = eng5.world.settlement
    s5.name = "Dispatchville"
    check("not yet tracked before any real dispatch", s5.id not in eng5._settlement_fingerprint)
    eng5._runtime_scheduler_settlement_dormancy.event_bus.publish("month_end")
    eng5._runtime_scheduler_settlement_dormancy.run_tick()
    check("a real month_end dispatch through the registered Task tracks the settlement",
          s5.id in eng5._settlement_fingerprint)

    # Real production-path smoke test: drive the actual tick loop (not a
    # direct method call) through several real month_end boundaries and
    # confirm the mechanism runs without crashing and a real settlement
    # stays reachable via _job_target throughout.
    eng6 = make_engine()
    s6 = eng6.world.settlement
    s6.name = "Smoketown"
    for _ in range(3000):
        eng6._tick_once()
    check("a real 3000-tick production run tracks the settlement without crashing",
          s6.id in eng6._settlement_fingerprint)
    check("_job_target still resolves to a real settlement after a real production run",
          eng6._job_target().name == "Smoketown")

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
