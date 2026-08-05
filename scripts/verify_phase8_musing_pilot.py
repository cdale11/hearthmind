#!/usr/bin/env python3
"""Tier 7 HCA Phase 8, step 1 (docs/ROADMAP-2026-07-REMAINING.md,
explicit user instruction "Start phase 8"): the pilot — wiring Stage
C's chunk/dispatch ladder (C1's `detect_no_change`, C2's `ChunkStore`,
C3's `dispatch_impasse`) into `SimulationEngine._maybe_schedule_
musing`, the first real production `_schedule_llm_job` call site to
actually consult a real `Impasse`/`DispatchOutcome` pair.

Verifies the real production method directly, driving the real clock
across real day_end boundaries and seeding a real, static open
`reflection_notebook` hypothesis so `_musing_subject()` has a genuine,
unchanging real subject to classify against (same "advance the clock,
call the real registered method" technique `verify_ml_g2_workload_
forecaster.py`/`verify_e4_learning_chart.py` already established).
C3's own stated test (">30% of real cycles resolve without an LLM
call") is measured live over a real multi-day soak on this pilot job
specifically, not re-asserted from the synthetic proof `verify_c3_
dispatch.py` already gave the primitive."""
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


def ticks_per_day(eng) -> int:
    return eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick


def call_musing(eng) -> None:
    """Drives `_maybe_schedule_musing` the way a real `_tick_once()` call
    would present it: `_reserved_this_tick` is a real, working, already-
    shipped (v0.81.0) same-tick reservation counter that every job in
    the codebase relies on, reset only at the top of a real `_tick_
    once()` — see `_effective_backlog`'s docstring. This test drives the
    method directly, tick-by-simulated-day, never through a real
    `_tick_once()`, so it must reproduce that same reset itself or the
    counter accumulates forever across calls that were never really
    concurrent and falsely trips backpressure from the second call
    onward — a test-harness gap, not a production one."""
    eng._reserved_this_tick = 0
    eng._maybe_schedule_musing(["day_end"])


def make_engine(seed: int):
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    d = tempfile.mkdtemp()
    conn = connect(f"{d}/p8.db")
    cfg = Config(db_path=f"{d}/p8.db", llm_enabled=False, seed=seed, initial_population=4, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


def seed_static_hypothesis(eng, text: str = "the same standing question") -> None:
    """A single real, never-superseded open hypothesis -- the real
    signal `_musing_subject()` picks up as "the newest open
    hypothesis" and keeps picking, unchanged, since nothing newer is
    ever added in this test."""
    entry_id = eng.world.next_reflection_entry_id
    eng.world.next_reflection_entry_id += 1
    eng.world.reflection_notebook.append({
        "id": entry_id, "created_tick": eng.world.clock.tick_count, "kind": "hypothesis",
        "subject": "test", "content": text, "confidence": 0.5,
        "evidence_for": [], "evidence_against": [], "evidence_against_hint": "", "status": "open",
    })


async def main_async() -> int:
    from hearthmind.cognition.impasse import ImpasseKind, detect_no_change
    from hearthmind.simulation.engine import MUSING_NO_CHANGE_STREAK_THRESHOLD

    # --- C1's classifier itself, hand-checked against this pilot's
    #     own real usage shape ---
    below = detect_no_change("musing:x", MUSING_NO_CHANGE_STREAK_THRESHOLD - 1, MUSING_NO_CHANGE_STREAK_THRESHOLD)
    check("a streak below the pilot's own threshold classifies no impasse", below is None)
    at = detect_no_change("musing:x", MUSING_NO_CHANGE_STREAK_THRESHOLD, MUSING_NO_CHANGE_STREAK_THRESHOLD)
    check("a streak AT the pilot's own threshold classifies a real no_change impasse",
          at is not None and at.kind is ImpasseKind.NO_CHANGE)

    # --- end to end: a real SimulationEngine, real day_end boundaries,
    #     a real static subject ---
    eng = make_engine(seed=23)
    seed_static_hypothesis(eng)

    check("a fresh musing chunk store starts empty",
          eng._musing_chunk_store.size() == 0)

    # Day 1: subject_key changes from None -> real subject -> streak
    # resets to 0 -> below threshold -> the direct, unwrapped path
    # fires exactly as before this pass.
    before = len(eng.world.musings)
    call_musing(eng)
    await asyncio.sleep(0)
    check("day 1 (streak 0, below threshold) schedules directly and produces a real musing",
          len(eng.world.musings) == before + 1 and eng._musing_no_change_streak == 0)
    check("day 1 never touches the chunk store (impasse was None)",
          eng._musing_chunk_store.size() == 0)

    # Day 2: same real static subject -> streak 1, still below
    # MUSING_NO_CHANGE_STREAK_THRESHOLD (2) -> still direct.
    eng.world.clock.tick_count += ticks_per_day(eng)
    before = len(eng.world.musings)
    call_musing(eng)
    await asyncio.sleep(0)
    check("day 2 (streak 1, still below threshold) still schedules directly",
          len(eng.world.musings) == before + 1 and eng._musing_no_change_streak == 1)
    check("day 2 still never touches the chunk store",
          eng._musing_chunk_store.size() == 0)

    # Day 3: streak now 2 (>= threshold) -- the FIRST real no_change
    # impasse. dispatch_impasse finds no chunk yet, so its LLM tier
    # (schedule_musing) still fires -- a real musing is still produced
    # -- but the real resolution now compiles a real chunk.
    eng.world.clock.tick_count += ticks_per_day(eng)
    before = len(eng.world.musings)
    call_musing(eng)
    await asyncio.sleep(0)
    check("day 3 (streak crosses threshold, no chunk yet) still schedules a real musing",
          len(eng.world.musings) == before + 1)
    check("day 3 is the real first LLM-tier dispatch that compiles a real chunk",
          eng._musing_chunk_store.size() == 1)

    # Day 4: the identical real stagnant subject -- dispatch_impasse's
    # cheap chunk-lookup now hits, schedule_musing is NEVER called,
    # and no new musing is appended.
    eng.world.clock.tick_count += ticks_per_day(eng)
    before = len(eng.world.musings)
    call_musing(eng)
    await asyncio.sleep(0)
    check("day 4 (identical stagnant subject) hits the real chunk and produces NO new musing",
          len(eng.world.musings) == before)
    check("the chunk records a real hit",
          next(iter(eng._musing_chunk_store._chunks.values())).hit_count == 1)

    # --- subject genuinely changes: streak resets, direct path
    #     resumes immediately, even with a populated chunk store ---
    seed_static_hypothesis(eng, text="a genuinely different question")
    eng.world.clock.tick_count += ticks_per_day(eng)
    before = len(eng.world.musings)
    call_musing(eng)
    await asyncio.sleep(0)
    check("a real subject change resets the streak and resumes direct scheduling immediately",
          eng._musing_no_change_streak == 0 and len(eng.world.musings) == before + 1)

    # --- C3's own stated live-soak bar: over many real days with an
    #     UNCHANGING subject, strictly more than 30% of real day_end
    #     musing opportunities resolve with NO new musing produced
    #     (a real chunk hit, no LLM call reached) ---
    eng2 = make_engine(seed=29)
    seed_static_hypothesis(eng2)
    SOAK_DAYS = 40
    opportunities = 0
    resolved_without_llm = 0
    for _ in range(SOAK_DAYS):
        eng2.world.clock.tick_count += ticks_per_day(eng2)
        before_count = len(eng2.world.musings)
        call_musing(eng2)
        await asyncio.sleep(0)
        opportunities += 1
        if len(eng2.world.musings) == before_count:
            resolved_without_llm += 1
    fraction = resolved_without_llm / opportunities
    check(f"real {SOAK_DAYS}-day soak on a static subject: {resolved_without_llm}/{opportunities} "
          f"({fraction:.1%}) real opportunities resolved without reaching the LLM -- clears C3's >30% bar",
          fraction > 0.30)

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
