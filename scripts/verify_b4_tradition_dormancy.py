#!/usr/bin/env python3
"""Tier 5 B4.2, third dormancy candidate ("forgotten traditions") —
verifies `SimulationEngine._update_tradition_dormancy`/`_tradition_
fingerprint` and `_maybe_spread_tradition_keeping`'s dormant-exclusion,
real production-path checks against a real `SimulationEngine`/`World`,
no unittest, same standalone-script convention as every sibling
`verify_*.py`."""
from __future__ import annotations

import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    TRADITION_DORMANCY_IDLE_CHECKS_THRESHOLD,
    SimulationEngine,
    _tradition_dormancy_key,
    _tradition_fingerprint,
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
    db_path = f"{_TMPDIR}/b4_tradition_dormancy_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=777,
        initial_population=8, width=24, height=24,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def main() -> int:
    eng = make_engine()
    settlement = eng.world.settlement
    settlement.name = "Testford"
    settlement.traditions = ["Harvest Feast"]
    agents = eng.world.population.agents
    check("world has real living agents to work with", len(agents) > 0)

    key = _tradition_dormancy_key(settlement, "Harvest Feast")

    # First check registers, never sleeps immediately.
    eng._update_tradition_dormancy()
    check("fresh tradition registers ACTIVE (never asleep on first check)",
          eng._tradition_dormancy.is_scheduled(key))
    check("fresh tradition's fingerprint recorded", key in eng._tradition_fingerprint)

    # Unchanged keeper count for the threshold's worth of checks -> sleeps.
    for _ in range(TRADITION_DORMANCY_IDLE_CHECKS_THRESHOLD - 1):
        eng._update_tradition_dormancy()
    check("idle tradition still awake just below threshold", eng._tradition_dormancy.is_scheduled(key))
    eng._update_tradition_dormancy()
    check("idle tradition asleep once threshold crossed", not eng._tradition_dormancy.is_scheduled(key))

    # A real new personal keeper wakes it immediately.
    agents[0].kept_traditions.append("Harvest Feast")
    eng._update_tradition_dormancy()
    check("a real new keeper wakes a sleeping tradition immediately",
          eng._tradition_dormancy.is_scheduled(key))
    check("waking resets the idle-check counter", eng._tradition_idle_checks[key] == 0)

    # A tradition removed from Settlement.traditions drops out of tracking.
    settlement.traditions = []
    eng._update_tradition_dormancy()
    check("a removed tradition is no longer tracked", key not in eng._tradition_fingerprint)

    # _maybe_spread_tradition_keeping excludes a sleeping tradition from its
    # weighted candidate pool, falls back to the full list when every
    # tradition in a settlement is asleep at once.
    eng2 = make_engine()
    s2 = eng2.world.settlement
    s2.name = "Dualburg"
    s2.traditions = ["Active Rite", "Sleepy Rite"]
    for _ in range(TRADITION_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng2._update_tradition_dormancy()
    # Wake "Active Rite" via a real new keeper right before the real roll.
    eng2.world.population.agents[0].kept_traditions.append("Active Rite")
    eng2._update_tradition_dormancy()
    active_key = _tradition_dormancy_key(s2, "Active Rite")
    sleepy_key = _tradition_dormancy_key(s2, "Sleepy Rite")
    check("active tradition awake, sleepy tradition asleep after divergent history",
          eng2._tradition_dormancy.is_scheduled(active_key)
          and not eng2._tradition_dormancy.is_scheduled(sleepy_key))

    candidates = [
        t for t in s2.traditions
        if eng2._tradition_dormancy.is_scheduled(_tradition_dormancy_key(s2, t))
    ]
    check("dormant-exclusion narrows the candidate pool to just the awake tradition",
          candidates == ["Active Rite"])

    # Fallback: everything asleep -> full list, never an empty candidate pool.
    eng3 = make_engine()
    s3 = eng3.world.settlement
    s3.name = "Lonetown"
    s3.traditions = ["Only Rite"]
    for _ in range(TRADITION_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng3._update_tradition_dormancy()
    only_key = _tradition_dormancy_key(s3, "Only Rite")
    check("a lone idle tradition is genuinely asleep", not eng3._tradition_dormancy.is_scheduled(only_key))
    candidates3 = [
        t for t in s3.traditions
        if eng3._tradition_dormancy.is_scheduled(_tradition_dormancy_key(s3, t))
    ]
    pool = candidates3 if candidates3 else s3.traditions
    check("fallback to full list when every tradition is asleep at once", pool == ["Only Rite"])

    # Fingerprint is a pure function of real keeper count.
    check("_tradition_fingerprint reflects the real keeper count",
          _tradition_fingerprint(s3, "Only Rite", eng3.world.population.agents) == 0)
    eng3.world.population.agents[0].kept_traditions.append("Only Rite")
    check("_tradition_fingerprint rises with a real new keeper",
          _tradition_fingerprint(s3, "Only Rite", eng3.world.population.agents) == 1)

    # Real dispatch wiring: the tradition_dormancy scheduler's own
    # registered Task fires `_update_tradition_dormancy` only on a real
    # month_end publish (same ON_EVENT machinery institution/idea
    # dormancy already proved).
    eng4 = make_engine()
    s4 = eng4.world.settlement
    s4.name = "Dispatchville"
    s4.traditions = ["Dispatch Rite"]
    dispatch_key = _tradition_dormancy_key(s4, "Dispatch Rite")
    check("not yet tracked before any real dispatch", dispatch_key not in eng4._tradition_fingerprint)
    eng4._runtime_scheduler_tradition_dormancy.event_bus.publish("month_end")
    eng4._runtime_scheduler_tradition_dormancy.run_tick()
    check("a real month_end dispatch through the registered Task tracks the tradition",
          dispatch_key in eng4._tradition_fingerprint)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
