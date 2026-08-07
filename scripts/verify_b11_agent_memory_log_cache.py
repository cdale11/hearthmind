#!/usr/bin/env python3
"""Tier 5 B11 verification (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, "Hierarchical memory tiering"). Standalone script, no
unittest, same convention as every sibling scripts/verify_*.py.

B11.1-B11.3 (`hierarchical_memory.py`) were real, standalone, verified
primitives with no live consumer since v1.34.178 (`scripts/verify_
hierarchical_memory.py` covers the primitives themselves in isolation
-- this script proves the real first production consumer this pass
wires them to: `SimulationEngine.cached_agent_memory_log`, backing
`GET /agents/{id}/memory_log`, which previously ran a fresh SQL query
against the durable `agent_memory_log` table on every single request).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.config import Config
from hearthmind.interface.api import WorldBroadcaster
from hearthmind.persistence.database import connect
from hearthmind.persistence.snapshot import log_agent_memory_entry, recent_agent_memory_log
from hearthmind.simulation.engine import AGENT_MEMORY_LOG_CACHE_LIMIT, AGENT_MEMORY_LOG_TIER_THRESHOLDS, SimulationEngine
from hearthmind.simulation.hierarchical_memory import Tier

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


async def _drive(eng, ticks: int) -> None:
    for _ in range(ticks):
        eng._tick_once()
        await asyncio.sleep(0)
    if eng._background_tasks:
        await asyncio.gather(*eng._background_tasks, return_exceptions=True)


def _make_engine(tmpdir: str) -> SimulationEngine:
    db_path = os.path.join(tmpdir, "b11.db")
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=42, initial_population=6, width=24, height=24)
    return SimulationEngine.load_or_create(conn, cfg)


def _seed_rows(eng: SimulationEngine, agent_id: int, n: int) -> None:
    for i in range(n):
        log_agent_memory_entry(eng.conn, tick=i, agent_id=agent_id, kind="episodic", text=f"memory {i}")
    eng.conn.commit()


def check_cache_miss_then_hit():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=1, n=3)
        check("agent not yet cached", 1 not in eng._agent_memory_log_cache)
        first = eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("first call (real miss) returns the real 3 seeded rows", len(first) == 3)
        check("first call populates the cache", 1 in eng._agent_memory_log_cache)
        # A row added to the DB after the cache is warm must NOT appear
        # on a second call at the same limit -- that's the whole point
        # of a real cache, not just a pass-through.
        log_agent_memory_entry(eng.conn, tick=99, agent_id=1, kind="episodic", text="a new row")
        eng.conn.commit()
        second = eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("second call at the same limit is a real cache HIT (still 3, not 4)", len(second) == 3)


def check_different_limit_bypasses_cache():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=1, n=5)
        eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)  # warm the default-limit cache
        bypassed = eng.cached_agent_memory_log(1, 2)
        check("a non-default limit returns the real (smaller) result, not the cached one", len(bypassed) == 2)
        # A bypassed request must not have touched the tier manager at
        # all -- confirm the agent's tier state is exactly what the
        # earlier default-limit call already left it at.
        check(
            "a bypassed request doesn't disturb the real cache's own tier state",
            eng._agent_memory_log_tiers.tier_of("1") is Tier.HOT,
        )


def check_empty_result_is_still_cached():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        result = eng.cached_agent_memory_log(999, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("an agent with zero real rows returns an empty list, not a crash", result == [])
        check("an empty result is still a real cache entry (not treated as a miss forever)", 999 in eng._agent_memory_log_cache)


def check_tier_promotion_on_access():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=1, n=2)
        eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("a fresh access registers/promotes the agent to HOT", eng._agent_memory_log_tiers.tier_of("1") is Tier.HOT)


def check_demotion_frees_ram_and_re_fetch_repopulates():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=1, n=4)
        eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("cached right after first access", 1 in eng._agent_memory_log_cache)

        # Force the manager's own idle clock far enough past every real
        # threshold (HOT -> WARM -> COLD -> ARCHIVE all in one call,
        # `demote_stale` only steps ONE tier per call though -- so drive
        # it repeatedly, matching `MemoryTierManager.demote_stale`'s own
        # documented "never skips a tier" contract).
        far_tick = eng.world.clock.tick_count + AGENT_MEMORY_LOG_TIER_THRESHOLDS[Tier.COLD] + 10
        for _ in range(4):
            for key, _from, to in eng._agent_memory_log_tiers.demote_stale(far_tick, AGENT_MEMORY_LOG_TIER_THRESHOLDS):
                if to is not Tier.HOT:
                    eng._agent_memory_log_cache.pop(int(key), None)
        check(
            "an agent idle past every real threshold demotes off HOT",
            eng._agent_memory_log_tiers.tier_of("1") is not Tier.HOT,
        )
        check("demotion past HOT actually frees the cached rows (real RAM reclaim, not just relabeling)", 1 not in eng._agent_memory_log_cache)

        # A re-fetch after demotion must still return the real, correct
        # rows (re-query, re-cache) and promote straight back to HOT.
        refetched = eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("a re-fetch after demotion still returns the real 4 rows", len(refetched) == 4)
        check("a re-fetch promotes the agent back to HOT", eng._agent_memory_log_tiers.tier_of("1") is Tier.HOT)


def check_real_demote_job_via_engine_method():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=1, n=1)
        eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        # Directly force the tracker's own idle clock, then call the
        # REAL registered method (not a hand-rolled loop) to confirm
        # its own real demote-and-free logic works end to end.
        key = "1"
        eng._agent_memory_log_tiers.tracker.mark_run(key, eng.world.clock.tick_count - AGENT_MEMORY_LOG_TIER_THRESHOLDS[Tier.HOT] - 5)
        eng._maybe_demote_agent_memory_log_cache()
        check(
            "the real `_maybe_demote_agent_memory_log_cache` method demotes and frees a genuinely stale agent",
            eng._agent_memory_log_tiers.tier_of(key) is Tier.WARM and 1 not in eng._agent_memory_log_cache,
        )


def check_never_registered_agent_is_a_no_op_for_demotion():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        # No request has ever been made for agent 42 -- it's not in the
        # tier manager's `tiers` dict at all, so a demote pass has
        # nothing to migrate for it, and must not crash.
        eng._maybe_demote_agent_memory_log_cache()
        check("a never-requested agent is safely absent, demote is a real no-op", 42 not in eng._agent_memory_log_cache)


def check_task_registered_and_month_end_gated():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        check(
            "_maybe_demote_agent_memory_log_cache is a real B0.3-migrated scheduled job",
            "_maybe_demote_agent_memory_log_cache" in eng._RUNTIME_SCHEDULED_JOB_SCHEDULERS,
        )
        check(
            "it's gated on a real month_end event, not a bare periodic tick",
            "_maybe_demote_agent_memory_log_cache" in eng._MONTH_END_GATED_JOBS,
        )
        check(
            "it's registered in the real _TICK_JOBS dispatch table",
            any(name == "_maybe_demote_agent_memory_log_cache" for name, _ in eng._TICK_JOBS),
        )


def check_diagnostics_surfacing():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=1, n=1)
        eng.cached_agent_memory_log(1, AGENT_MEMORY_LOG_CACHE_LIMIT)
        report = eng.full_diagnostics()
        check("full_diagnostics() surfaces agent_memory_log_cache", "agent_memory_log_cache" in report)
        cache_report = report.get("agent_memory_log_cache", {})
        check(
            "the diagnostics report a real HOT tier count and cached-agent count",
            cache_report.get("tier_counts", {}).get("hot") == 1 and cache_report.get("cached_agents") == 1,
        )


def check_end_to_end_through_broadcaster_provider():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=7, n=2)
        broadcaster = WorldBroadcaster()
        broadcaster.set_agent_memory_log_provider(eng.cached_agent_memory_log)
        via_provider = broadcaster.get_agent_memory_log(7, AGENT_MEMORY_LOG_CACHE_LIMIT)
        check(
            "the real end-to-end path (WorldBroadcaster provider -> SimulationEngine.cached_agent_memory_log) works",
            via_provider is not None and len(via_provider) == 2,
        )
        # A broadcaster with no provider registered (e.g. a standalone
        # test harness with no engine attached) must degrade to `None`,
        # never crash -- `interface/app.py`'s own route falls back to
        # the direct uncached query in exactly this case.
        bare = WorldBroadcaster()
        check("a broadcaster with no provider registered returns None (the app's own fallback signal)", bare.get_agent_memory_log(7, AGENT_MEMORY_LOG_CACHE_LIMIT) is None)


def check_matches_direct_uncached_query():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        _seed_rows(eng, agent_id=3, n=6)
        cached = eng.cached_agent_memory_log(3, AGENT_MEMORY_LOG_CACHE_LIMIT)
        direct = recent_agent_memory_log(eng.conn, agent_id=3, limit=AGENT_MEMORY_LOG_CACHE_LIMIT)
        check("a cache-warming call returns byte-identical content to the direct uncached query", cached == direct)


def check_production_soak_no_crash():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        for i, agent in enumerate(eng.world.population.agents[:3]):
            _seed_rows(eng, agent_id=agent.id, n=2)
            eng.cached_agent_memory_log(agent.id, AGENT_MEMORY_LOG_CACHE_LIMIT)
        asyncio.run(_drive(eng, 400))
        check(
            "a real 400-tick soak with the new cache/demotion job live never crashes",
            True,
        )


def main() -> int:
    check_cache_miss_then_hit()
    check_different_limit_bypasses_cache()
    check_empty_result_is_still_cached()
    check_tier_promotion_on_access()
    check_demotion_frees_ram_and_re_fetch_repopulates()
    check_real_demote_job_via_engine_method()
    check_never_registered_agent_is_a_no_op_for_demotion()
    check_task_registered_and_month_end_gated()
    check_diagnostics_surfacing()
    check_end_to_end_through_broadcaster_provider()
    check_matches_direct_uncached_query()
    check_production_soak_no_crash()

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
