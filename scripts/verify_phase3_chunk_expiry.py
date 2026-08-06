#!/usr/bin/env python3
"""Roadmap Phase 3 (docs/ROADMAP-2026-07-REMAINING.md, explicit user
instruction "start phase 3"): a real chunk-expiry mechanism for Stage
C's `ChunkStore`/`dispatch_impasse`, unblocking a safe sweep of
`SimulationEngine._maybe_schedule_rule_proposal` into the dispatch
ladder — HCA's own worked example, "family lines dying out, 590
occurrences, no rule," made real for a second production job (the
first, `_maybe_schedule_musing`, shipped Phase 8, see `scripts/
verify_phase8_musing_pilot.py`).

Two things verified here that neither `scripts/verify_c2_chunking.py`
nor `scripts/verify_c3_dispatch.py` cover (both predate this pass and
were re-run unmodified to confirm zero regression against their own,
pre-Phase-3, non-expiry test suites): (1) `ChunkStore.compile()`'s new
`ttl_ticks`/`lookup()`'s new `tick` params, including the real deletion-
on-expiry behavior and the `tick=None`/`ttl_ticks=None` backward-
compatibility default; (2) the real production wiring in
`_maybe_schedule_rule_proposal` — a genuinely stuck institution
recurring past `RULE_PROPOSAL_NO_CHANGE_STREAK_THRESHOLD` consecutive
real seasonal firings routes through the dispatch ladder exactly the
way the musing pilot proved, AND a chunked outcome genuinely expires
and re-deliberates once `RULE_PROPOSAL_CHUNK_TTL_YEARS` has elapsed —
the real fix for the one limitation the musing pilot's own docstring
flagged as accepted-not-engineered-around."""
from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(seed: int):
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    d = tempfile.mkdtemp()
    conn = connect(f"{d}/p3.db")
    cfg = Config(db_path=f"{d}/p3.db", llm_enabled=False, seed=seed, initial_population=4, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


def seed_stuck_institution(eng, settlement, name: str, unmet: int):
    from hearthmind.settlement.institutions import Institution, InstitutionKind

    inst_id = max((i.id for i in settlement.institutions), default=0) + 1
    inst = Institution(
        id=inst_id, kind=InstitutionKind.COUNCIL, founding_tick=eng.world.clock.tick_count,
        name=name, objective="secure more materials", objective_ticks_unmet=unmet,
    )
    settlement.institutions.append(inst)
    return inst


def call_rule_proposal(eng) -> int:
    """Drives `_maybe_schedule_rule_proposal` the way a real
    `_tick_once()` would present it, same real-scheduler-reset
    technique `verify_phase8_musing_pilot.py`'s own `call_musing`
    established. Returns the number of real `_schedule_llm_job` calls
    this one firing made (`_reserved_this_tick` is incremented
    synchronously the instant a job is scheduled — see its own
    docstring — so this is a genuine, zero-await observable for
    "did the LLM tier actually fire this call")."""
    eng._reserved_this_tick = 0
    eng._maybe_schedule_rule_proposal(["season_end"])
    return eng._reserved_this_tick


async def main_async() -> int:
    from hearthmind.cognition.chunk import ChunkStore
    from hearthmind.cognition.dispatch import dispatch_impasse
    from hearthmind.cognition.impasse import ImpasseKind, detect_no_change
    from hearthmind.settlement.institutions import INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD
    from hearthmind.simulation.engine import RULE_PROPOSAL_CHUNK_TTL_YEARS, RULE_PROPOSAL_NO_CHANGE_STREAK_THRESHOLD

    # --- ChunkStore.compile()/lookup(): the real TTL/expiry mechanism
    #     itself, isolated from any production call site ---
    impasse = detect_no_change("rule_propose:1:1", RULE_PROPOSAL_NO_CHANGE_STREAK_THRESHOLD, RULE_PROPOSAL_NO_CHANGE_STREAK_THRESHOLD)
    check("a real no_change impasse exists to compile against", impasse is not None and impasse.kind is ImpasseKind.NO_CHANGE)

    store = ChunkStore()
    chunk_no_ttl = store.compile(impasse, "cached_decision", {"scheduled": True, "tick": 100}, tick=100)
    check("ttl_ticks=None (the default) leaves expires_at_tick unset", chunk_no_ttl.expires_at_tick is None)
    check("a never-expiring chunk is still found at an arbitrarily distant real tick",
          store.lookup(impasse, tick=10_000_000) is chunk_no_ttl)
    check("a never-expiring chunk is still found with no tick argument at all",
          store.lookup(impasse) is chunk_no_ttl)

    store2 = ChunkStore()
    chunk_ttl = store2.compile(impasse, "cached_decision", {"scheduled": True, "tick": 100}, tick=100, ttl_ticks=10)
    check("a real ttl_ticks sets the real expires_at_tick (tick + ttl_ticks)", chunk_ttl.expires_at_tick == 110)
    check("looked up before its own expiry, the chunk is still a real hit",
          store2.lookup(impasse, tick=109) is chunk_ttl)
    check("looked up with no tick argument at all, expiry is skipped entirely — always a hit",
          store2.lookup(impasse, tick=None) is chunk_ttl)
    check("the store still holds exactly one chunk before expiry", store2.size() == 1)
    expired_lookup = store2.lookup(impasse, tick=110)
    check("looked up AT its own expires_at_tick, the chunk reads as a genuine miss", expired_lookup is None)
    check("the expired chunk was genuinely deleted, not just hidden", store2.size() == 0)

    # --- dispatch_impasse: ttl_ticks/tick threaded through end to end ---
    store3 = ChunkStore()
    calls = {"n": 0}

    def llm_resolver_1() -> dict:
        calls["n"] += 1
        return {"scheduled": True, "call": calls["n"]}

    outcome1 = dispatch_impasse(impasse, store3, tick=0, llm_resolver=llm_resolver_1, ttl_ticks=5)
    check("a fresh dispatch with no chunk yet genuinely reaches the LLM tier",
          outcome1.resolved_via == "llm" and calls["n"] == 1)
    check("the LLM-tier resolution compiled a real chunk with the real TTL applied",
          outcome1.chunk is not None and outcome1.chunk.expires_at_tick == 5)

    outcome2 = dispatch_impasse(impasse, store3, tick=4, llm_resolver=llm_resolver_1, ttl_ticks=5)
    check("looked up before expiry, the SAME impasse hits the chunk instead of the LLM tier",
          outcome2.resolved_via == "chunk" and calls["n"] == 1)

    outcome3 = dispatch_impasse(impasse, store3, tick=5, llm_resolver=llm_resolver_1, ttl_ticks=5)
    check("looked up AT the chunk's own real expiry tick, the LLM tier fires again",
          outcome3.resolved_via == "llm" and calls["n"] == 2)
    check("the re-deliberation compiled a genuinely new chunk, not the stale one",
          outcome3.chunk is not None and outcome3.chunk.expires_at_tick == 10)

    # --- the real per-world TTL computation, hand-checked ---
    eng = make_engine(seed=41)
    cfg = eng.world.config
    expected_ticks_per_year = (sum(cfg.days_per_month) * cfg.minutes_per_day) // cfg.sim_minutes_per_tick
    expected_ttl = expected_ticks_per_year * RULE_PROPOSAL_CHUNK_TTL_YEARS
    check("_rule_proposal_chunk_ttl_ticks() matches the real config's own calendar math by hand",
          eng._rule_proposal_chunk_ttl_ticks() == expected_ttl)
    check("the computed TTL is a real, positive, multi-year span of ticks", expected_ttl > 0)

    # --- real end-to-end production wiring: _maybe_schedule_rule_
    #     proposal, a real SimulationEngine, real season_end firings ---
    eng2 = make_engine(seed=43)
    settlement = eng2.world.settlement
    settlement.name = "Testville"
    inst_a = seed_stuck_institution(eng2, settlement, "council of elders", INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)

    check("a fresh rule-proposal chunk store starts empty", eng2._rule_proposal_chunk_store.size() == 0)

    # Season 1: subject_key changes from None -> real subject -> streak
    # resets to 0 -> below RULE_PROPOSAL_NO_CHANGE_STREAK_THRESHOLD ->
    # the direct, unwrapped path fires exactly as before this pass.
    scheduled = call_rule_proposal(eng2)
    await asyncio.sleep(0)
    check("season 1 (streak 0, below threshold) schedules the LLM job directly", scheduled > 0)
    check("season 1 never touches the chunk store (impasse was None)", eng2._rule_proposal_chunk_store.size() == 0)
    check("the real subject key was recorded", eng2._rule_proposal_last_subject_key == f"{settlement.id}:{inst_a.id}")

    # Season 2: same real stuck institution -> streak 1, still below
    # RULE_PROPOSAL_NO_CHANGE_STREAK_THRESHOLD (2) -> still direct.
    eng2.world.clock.tick_count += 1000
    scheduled = call_rule_proposal(eng2)
    await asyncio.sleep(0)
    check("season 2 (streak 1, still below threshold) still schedules directly",
          scheduled > 0 and eng2._rule_proposal_no_change_streak == 1)
    check("season 2 still never touches the chunk store", eng2._rule_proposal_chunk_store.size() == 0)

    # Season 3: streak now 2 (>= threshold) -- the FIRST real no_change
    # impasse. dispatch_impasse finds no chunk yet, so its LLM tier
    # still fires -- but the real resolution now compiles a real chunk.
    eng2.world.clock.tick_count += 1000
    scheduled = call_rule_proposal(eng2)
    await asyncio.sleep(0)
    check("season 3 (streak crosses threshold, no chunk yet) still schedules the LLM job", scheduled > 0)
    check("season 3 is the real first LLM-tier dispatch that compiles a real chunk",
          eng2._rule_proposal_chunk_store.size() == 1)
    compiled_chunk = next(iter(eng2._rule_proposal_chunk_store._chunks.values()))
    check("the compiled chunk carries the real, non-infinite TTL",
          compiled_chunk.expires_at_tick == compiled_chunk.created_tick + expected_ttl)

    # Season 4: the identical real stuck institution, well before the
    # chunk's own expiry -- dispatch_impasse's cheap chunk-lookup hits,
    # the LLM job is NEVER scheduled again.
    eng2.world.clock.tick_count += 1000
    scheduled = call_rule_proposal(eng2)
    await asyncio.sleep(0)
    check("season 4 (identical stuck institution, before expiry) hits the real chunk and schedules nothing",
          scheduled == 0)
    check("the chunk records a real hit", compiled_chunk.hit_count == 1)

    # Real expiry: jump the clock to (and past) the compiled chunk's own
    # real expires_at_tick -- the SAME recurring impasse now reads as a
    # genuine miss, deletes the stale chunk, and pays for one more real
    # deliberation instead of being suppressed forever.
    eng2.world.clock.tick_count = compiled_chunk.expires_at_tick
    scheduled = call_rule_proposal(eng2)
    await asyncio.sleep(0)
    check("past the chunk's own real expiry, the LLM tier genuinely fires again", scheduled > 0)
    check("the expired chunk was replaced by a genuinely new one (fresh created_tick)",
          eng2._rule_proposal_chunk_store.size() == 1
          and next(iter(eng2._rule_proposal_chunk_store._chunks.values())).created_tick
          == eng2.world.clock.tick_count)

    # A genuinely different worst-stuck institution resets the streak
    # and resumes direct scheduling immediately, even with a populated
    # chunk store for the OLD institution's subject key.
    inst_b = seed_stuck_institution(eng2, settlement, "guild of smiths", INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD + 5)
    store_size_before = eng2._rule_proposal_chunk_store.size()
    eng2.world.clock.tick_count += 1000
    scheduled = call_rule_proposal(eng2)
    await asyncio.sleep(0)
    check("a genuinely different stuck institution resets the streak and schedules directly",
          scheduled > 0 and eng2._rule_proposal_no_change_streak == 0
          and eng2._rule_proposal_last_subject_key == f"{settlement.id}:{inst_b.id}")
    check("switching institutions never touches the OLD institution's own chunk",
          eng2._rule_proposal_chunk_store.size() == store_size_before)

    # Drain any real background tasks (the sandboxed rule-registration
    # closures) so the process exits cleanly.
    if eng2._background_tasks:
        await asyncio.gather(*list(eng2._background_tasks), return_exceptions=True)
    if eng._background_tasks:
        await asyncio.gather(*list(eng._background_tasks), return_exceptions=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
