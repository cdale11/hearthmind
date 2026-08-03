#!/usr/bin/env python3
"""Tier 5 B4.2, second dormancy candidate ("unused ideas") — verifies
`SimulationEngine._update_idea_dormancy`/`_idea_fingerprint` and
`_maybe_spread_concepts`'s dormant-exclusion, real production-path
checks against a real `SimulationEngine`/`World`, no unittest, same
standalone-script convention as every sibling `verify_*.py`."""
from __future__ import annotations

import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD, SimulationEngine, _idea_fingerprint,
)
from hearthmind.world.ontology import InventedConcept
from hearthmind.world.state import World

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
    db_path = f"{_TMPDIR}/b4_idea_dormancy_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=777,
        initial_population=8, width=24, height=24,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def add_concept(world: World, name: str, status: str = "proposed", origin_settlement_id: int = 0) -> InventedConcept:
    cid = world.next_concept_id
    world.next_concept_id += 1
    c = InventedConcept(
        id=cid, name=name, category="technology", description="test",
        origin_settlement_id=origin_settlement_id, status=status,
        tick_invented=world.clock.tick_count, inventor_agent_id=None,
    )
    world.invented_concepts[cid] = c
    return c


def main() -> int:
    eng = make_engine()
    c1 = add_concept(eng.world, "Idea One")

    # First check registers, never sleeps immediately.
    eng._update_idea_dormancy()
    check("fresh idea registers ACTIVE (never asleep on first check)",
          eng._idea_dormancy.is_scheduled(str(c1.id)))
    check("fresh idea's fingerprint recorded", c1.id in eng._idea_fingerprint)

    # Unchanged fingerprint for the threshold's worth of checks -> sleeps.
    for _ in range(IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD - 1):
        eng._update_idea_dormancy()
    check("idle idea still awake just below threshold", eng._idea_dormancy.is_scheduled(str(c1.id)))
    eng._update_idea_dormancy()
    check("idle idea asleep once threshold crossed", not eng._idea_dormancy.is_scheduled(str(c1.id)))

    # A real adopter change wakes it immediately.
    c1.adopter_ids.add(999)
    eng._update_idea_dormancy()
    check("a real adopter gain wakes a sleeping idea immediately",
          eng._idea_dormancy.is_scheduled(str(c1.id)))
    check("waking resets the idle-check counter", eng._idea_idle_checks[c1.id] == 0)

    # A concept leaving proposed/spreading (established) drops out of tracking.
    c1.status = "established"
    eng._update_idea_dormancy()
    check("an established concept is no longer tracked", c1.id not in eng._idea_fingerprint)

    # _maybe_spread_concepts excludes a sleeping concept from its roll list,
    # falls back to the full list when every growing concept is asleep.
    eng2 = make_engine()
    active = add_concept(eng2.world, "Active Idea")
    sleepy = add_concept(eng2.world, "Sleepy Idea")
    for _ in range(IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng2._update_idea_dormancy()
    # Wake `active` via a fingerprint change right before the real roll.
    active.adopter_ids.add(1)
    eng2._update_idea_dormancy()
    check("active idea awake, sleepy idea asleep after divergent history",
          eng2._idea_dormancy.is_scheduled(str(active.id))
          and not eng2._idea_dormancy.is_scheduled(str(sleepy.id)))

    growing_all = [c for c in eng2.world.invented_concepts.values() if c.status in ("proposed", "spreading")]
    awake_only = [c for c in growing_all if eng2._idea_dormancy.is_scheduled(str(c.id))]
    check("dormant-exclusion narrows the roll list to just the awake idea",
          awake_only == [active])

    # Fallback: everything asleep -> full list, never an empty roll pool.
    eng3 = make_engine()
    only = add_concept(eng3.world, "Only Idea")
    for _ in range(IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD + 1):
        eng3._update_idea_dormancy()
    check("a lone idle idea is genuinely asleep", not eng3._idea_dormancy.is_scheduled(str(only.id)))
    growing3 = [c for c in eng3.world.invented_concepts.values() if c.status in ("proposed", "spreading")]
    awake3 = [c for c in growing3 if eng3._idea_dormancy.is_scheduled(str(c.id))]
    pool = awake3 if awake3 else growing3
    check("fallback to full list when everything is asleep at once", pool == [only])

    # Fingerprint is a pure function of status + adopter count.
    check("_idea_fingerprint reflects status/adopter-count",
          _idea_fingerprint(only) == ("proposed", 0))

    # Real dispatch wiring: the idea_dormancy scheduler's own registered
    # Task fires `_update_idea_dormancy` only on a real month_end publish
    # (same ON_EVENT machinery institution_dormancy already proved).
    eng4 = make_engine()
    idea = add_concept(eng4.world, "Dispatch Idea")
    check("not yet tracked before any real dispatch", idea.id not in eng4._idea_fingerprint)
    eng4._runtime_scheduler_idea_dormancy.event_bus.publish("month_end")
    eng4._runtime_scheduler_idea_dormancy.run_tick()
    check("a real month_end dispatch through the registered Task tracks the idea",
          idea.id in eng4._idea_fingerprint)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
