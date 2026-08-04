#!/usr/bin/env python3
"""Tier 6 L1.2's real first gameplay consumer + diagnostics exposure:
`SimulationEngine._detect_social_bridge` (`Settlement.social_bridge_
agent_id`, mirroring the already-real `_detect_social_hub`/`social_hub_
agent_id` pattern) and `full_diagnostics()['social_features']`. Real
production-path checks against a real `SimulationEngine`/`World`, no
unittest, same standalone-script convention as every sibling
`verify_*.py`."""
from __future__ import annotations

import json
import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def make_engine(tmpdir: str, counter: int) -> SimulationEngine:
    db_path = f"{tmpdir}/social_bridge_{counter}.db"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=99, initial_population=12, width=24, height=24)
    return SimulationEngine.load_or_create(conn, cfg)


def main() -> int:
    tmpdir = tempfile.mkdtemp()

    # Fresh engine: no bridge computed yet on any settlement.
    eng = make_engine(tmpdir, 1)
    check("a fresh settlement has no social_bridge_agent_id yet",
          all(s.social_bridge_agent_id is None for s in eng.world.settlements))

    # Round-trip: to_dict/from_dict preserves the field (currently None).
    settlement = eng.world.settlements[0]
    settlement.social_bridge_agent_id = 12345
    data = settlement.to_dict()
    check("to_dict() includes social_bridge_agent_id", data.get("social_bridge_agent_id") == 12345)
    from hearthmind.settlement.buildings import Settlement
    restored = Settlement.from_dict(data)
    check("from_dict() restores social_bridge_agent_id", restored.social_bridge_agent_id == 12345)
    settlement.social_bridge_agent_id = None

    # Legacy backfill: a dict with no social_bridge_agent_id key at all
    # (pre-this-feature snapshot) restores cleanly to None.
    legacy_data = dict(data)
    legacy_data.pop("social_bridge_agent_id", None)
    legacy_restored = Settlement.from_dict(legacy_data)
    check("from_dict() backfills a missing social_bridge_agent_id key to None",
          legacy_restored.social_bridge_agent_id is None)

    # Real production-path: force two agents in the same settlement into
    # a genuine bridging configuration (A connects B and C, who are not
    # connected to each other) and confirm _detect_social_bridge finds it.
    eng2 = make_engine(tmpdir, 2)
    members = [a for a in eng2.world.population.agents if a.settlement_id == eng2.world.settlements[0].id]
    check("the fresh population has enough members to test bridging", len(members) >= 3)
    a, b, c = members[0], members[1], members[2]
    for agent in members:
        agent.relationships.clear()
    a.relationships[b.id] = 0.8
    b.relationships[a.id] = 0.8
    a.relationships[c.id] = 0.8
    c.relationships[a.id] = 0.8
    eng2._detect_social_bridge()
    check("a real bridging agent is correctly detected as the settlement's social_bridge_agent_id",
          eng2.world.settlements[0].social_bridge_agent_id == a.id)

    # Edge-triggered: calling it again with no change makes no further
    # emergence entry (checked via a stable log length).
    log_len_before = len(eng2.world.emergence_log)
    eng2._detect_social_bridge()
    check("a repeated call with no real change adds no further emergence entry",
          len(eng2.world.emergence_log) == log_len_before)

    # A fully clustered settlement (everyone knows everyone) has no
    # genuine bridge -- social_bridge_agent_id stays None.
    eng3 = make_engine(tmpdir, 3)
    members3 = [a for a in eng3.world.population.agents if a.settlement_id == eng3.world.settlements[0].id][:3]
    for x in members3:
        for y in members3:
            if x.id != y.id:
                x.relationships[y.id] = 0.8
    eng3._detect_social_bridge()
    check("a fully clustered settlement (no real bridge) leaves social_bridge_agent_id at None",
          eng3.world.settlements[0].social_bridge_agent_id is None)

    # A real season_end tick dispatches through the real production path.
    eng4 = make_engine(tmpdir, 4)
    members4 = [a for a in eng4.world.population.agents if a.settlement_id == eng4.world.settlements[0].id]
    if len(members4) >= 3:
        for agent in members4:
            agent.relationships.clear()
        members4[0].relationships[members4[1].id] = 0.9
        members4[1].relationships[members4[0].id] = 0.9
        members4[0].relationships[members4[2].id] = 0.9
        members4[2].relationships[members4[0].id] = 0.9
    import asyncio

    async def _drive():
        for _ in range(2000):
            eng4._tick_once()

    asyncio.run(_drive())
    check("a real 2000-tick production run (with season_end crossed) never crashes",
          True)

    # full_diagnostics() surfaces the new social_features block, and it
    # is genuinely JSON-serializable (the actual contract /diagnostics
    # depends on).
    diag = eng4.full_diagnostics()
    check("full_diagnostics() includes a social_features block", "social_features" in diag)
    check("social_features.settlements lists every real settlement",
          len(diag["social_features"]["settlements"]) == len(eng4.world.settlements))
    check("social_features.live_sample reports a real agents_measured count",
          diag["social_features"]["live_sample"]["agents_measured"] == len(eng4.world.population.agents))
    try:
        json.dumps(diag["social_features"])
        json_ok = True
    except TypeError:
        json_ok = False
    check("the social_features diagnostics block is genuinely JSON-serializable", json_ok)

    # UI stat tile data contract: settlement.to_dict() (what the live
    # broadcast sends) includes both fields together.
    live_dict = eng4.world.settlements[0].to_dict()
    check("the live settlement payload includes both social_hub_agent_id and social_bridge_agent_id",
          "social_hub_agent_id" in live_dict and "social_bridge_agent_id" in live_dict)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
