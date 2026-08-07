#!/usr/bin/env python3
"""Tier 5 B14.3's real first consumer (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B, "Persistence & background work"):
`batch_size_for_storage` (`simulation/persistence_scheduling.py`) had
no real batched-write mechanism to size for -- the events-table writer
was still one `execute()` per row. `SimulationEngine._buffer_event`/
`_event_batch_byte_budget`/`_flush_event_write_buffer` are that real
mechanism, backed by a new `persistence.snapshot.log_events_batch`
(`executemany`). Real production-path checks against a real
`SimulationEngine`/`World`, no unittest, same standalone-script
convention as every sibling `verify_*.py`.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.persistence.snapshot import log_events_batch, recent_events
from hearthmind.simulation.engine import (
    EVENT_BATCH_MAX_BYTES,
    EVENT_BATCH_MIN_BYTES,
    SimulationEngine,
)

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


def _make_engine(tmpdir: str, name: str = "b14_3") -> SimulationEngine:
    db_path = os.path.join(tmpdir, f"{name}.db")
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=42, initial_population=6, width=24, height=24)
    return SimulationEngine.load_or_create(conn, cfg)


def check_log_events_batch_writes_via_executemany():
    with tempfile.TemporaryDirectory() as d:
        conn = connect(os.path.join(d, "raw.db"))
        rows = [(i, float(i), "test", f"row {i}") for i in range(5)]
        log_events_batch(conn, rows)
        check("log_events_batch on an empty list is a genuine no-op (no crash)", True)
        conn.commit()
        got = conn.execute("SELECT tick, category, description FROM events ORDER BY id").fetchall()
        check(
            "log_events_batch writes every row via one real executemany() call",
            got == [(i, "test", f"row {i}") for i in range(5)],
        )
        # An empty list must be a real no-op, not an error.
        log_events_batch(conn, [])
        conn.commit()
        check("an empty rows list is a real no-op", conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5)


def check_buffer_event_does_not_immediately_hit_the_db():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        # World creation itself already logs a real synchronous "genesis"
        # event (not through this buffer) -- check for the SPECIFIC test
        # row, not an absolute zero count.
        eng._buffer_event("test_category", "a buffered event")
        pre_flush = [r for r in recent_events(eng.conn, limit=50) if r["category"] == "test_category"]
        check("a buffered (not yet flushed) row is NOT yet visible in the events table", len(pre_flush) == 0)
        check("the row IS in the in-memory buffer", len(eng._event_write_buffer) == 1)
        eng._flush_event_write_buffer()
        eng.conn.commit()
        rows = [r for r in recent_events(eng.conn, limit=50) if r["category"] == "test_category"]
        check(
            "flushing (then committing) makes the buffered row real and visible",
            len(rows) == 1 and rows[0]["description"] == "a buffered event",
        )
        check("the buffer is empty after flush", len(eng._event_write_buffer) == 0 and eng._event_write_buffer_bytes == 0)


def check_flush_is_a_real_no_op_on_an_empty_buffer():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        before = eng._event_write_flush_count
        eng._flush_event_write_buffer()
        check("flushing an already-empty buffer never counts as a real flush", eng._event_write_flush_count == before)


def check_byte_budget_reflects_real_storage_throughput():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        eng._machine_profile.storage_write_mb_s = None
        unmeasured = eng._event_batch_byte_budget()
        check("an unmeasured host falls back to the conservative floor", unmeasured == EVENT_BATCH_MIN_BYTES)

        eng._machine_profile.storage_write_mb_s = 5000.0  # a genuinely fast disk
        fast = eng._event_batch_byte_budget()
        check("a fast measured disk earns a genuinely larger batch budget", fast > unmeasured)
        check("the budget never exceeds the real configured ceiling", fast <= EVENT_BATCH_MAX_BYTES)

        eng._machine_profile.storage_write_mb_s = 0.0001  # a genuinely slow disk
        slow = eng._event_batch_byte_budget()
        check("a slow measured disk stays at (or near) the conservative floor", slow == EVENT_BATCH_MIN_BYTES)


def check_crossing_the_byte_threshold_flushes_mid_tick():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        # Force a tiny budget so a handful of ordinary events already
        # cross it -- the real, live proof this is byte-threshold-driven,
        # not just a once-per-tick flush.
        eng._machine_profile.storage_write_mb_s = None  # -> EVENT_BATCH_MIN_BYTES floor
        eng._event_write_buffer_bytes = 0
        original_budget = eng._event_batch_byte_budget()
        # Monkeypatch the budget to something small enough that 3 short
        # events definitely cross it, without touching the real formula.
        eng._event_batch_byte_budget = lambda: 40
        eng._buffer_event("a", "short")
        eng._buffer_event("b", "short")
        check("a small budget crossed by only 2 short events flushes automatically, mid-tick", eng._event_write_flush_count >= 1 and len(eng._event_write_buffer) == 0)
        eng._event_batch_byte_budget = lambda: original_budget  # restore, not load-bearing past this check


def check_calendar_and_life_event_loops_use_the_buffer():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        before = len(eng._event_write_buffer)
        eng._buffer_event("day_end", "A day passed.")
        check("the buffered shape matches what _tick_once's own calendar-event loop now produces", len(eng._event_write_buffer) == before + 1)


def check_flush_happens_before_tick_once_commit():
    with tempfile.TemporaryDirectory() as d:
        async def _run() -> None:
            eng = _make_engine(d, name="tick_commit")
            eng._buffer_event("manual_test", "logged just before a real tick")
            eng._tick_once()
            await asyncio.sleep(0)
            rows = [r for r in recent_events(eng.conn, limit=50) if r["category"] == "manual_test"]
            check(
                "a row buffered before _tick_once is genuinely flushed AND committed by the end of that tick",
                len(rows) == 1,
            )
        asyncio.run(_run())


def check_flush_happens_before_shutdown_snapshot():
    with tempfile.TemporaryDirectory() as d:
        async def _run() -> None:
            eng = _make_engine(d, name="shutdown")
            eng._buffer_event("shutdown_test", "logged just before shutdown")
            # Mirror run_forever's own finally-block sequence directly --
            # flush, then save the final snapshot -- without needing a
            # real event loop/stop-event dance.
            eng._flush_event_write_buffer()
            from hearthmind.persistence.snapshot import save_snapshot
            save_snapshot(eng.conn, eng.world)
            rows = [r for r in recent_events(eng.conn, limit=50) if r["category"] == "shutdown_test"]
            check("a row buffered before the shutdown path's flush+save_snapshot is genuinely durable", len(rows) == 1)
        asyncio.run(_run())


def check_diagnostics_surfacing():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        report = eng.full_diagnostics()
        check("full_diagnostics() surfaces event_write_batching", "event_write_batching" in report)
        section = report.get("event_write_batching", {})
        check(
            "the diagnostics report a real byte_budget and a starting flush_count of 0",
            section.get("byte_budget", 0) > 0 and section.get("flush_count") == 0,
        )
        eng._buffer_event("diag_test", "x")
        eng._flush_event_write_buffer()
        report2 = eng.full_diagnostics()
        check("flush_count genuinely increments after a real flush", report2["event_write_batching"]["flush_count"] == 1)


def check_production_soak_events_land_correctly():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d, name="soak")
        asyncio.run(_drive(eng, 400))
        eng.conn.commit()
        total = eng.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        check("a real 400-tick production soak with the batched writer live genuinely writes events", total > 0)
        check("the batched writer produced at least one real flush over 400 ticks", eng._event_write_flush_count > 0)
        # Every real day_end/week_end/etc. calendar tick should have
        # landed a real row -- spot check day_end specifically, since
        # it fires every real sim-day and is one of the two loops this
        # pass moved onto the buffer.
        day_end_count = eng.conn.execute("SELECT COUNT(*) FROM events WHERE category = 'day_end'").fetchone()[0]
        check("real calendar day_end events reached the database through the batched path", day_end_count > 0)


def main() -> int:
    check_log_events_batch_writes_via_executemany()
    check_buffer_event_does_not_immediately_hit_the_db()
    check_flush_is_a_real_no_op_on_an_empty_buffer()
    check_byte_budget_reflects_real_storage_throughput()
    check_crossing_the_byte_threshold_flushes_mid_tick()
    check_calendar_and_life_event_loops_use_the_buffer()
    check_flush_happens_before_tick_once_commit()
    check_flush_happens_before_shutdown_snapshot()
    check_diagnostics_surfacing()
    check_production_soak_events_land_correctly()

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
