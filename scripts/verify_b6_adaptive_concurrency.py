#!/usr/bin/env python3
"""Tier 5 B6 — adaptive tuning wired to a real control point.

Explicit user choice (via `AskUserQuestion`, after Part B's B0.3 was
fully closed): of the several Part B items shipped as standalone
modules but "not wired into any real control point," B6's adaptive
tuning gets wired first. `SimulationEngine._maybe_tune_llm_concurrency`
(simulation/engine.py) now runs a real `BangBangController` against a
real `TunableRegistry` (simulation/tuning.py) once a day, driven by
`CognitionRunner.stats()`'s own already-tracked rolling p95 latency —
the same real signal CLAUDE.md's own long documented manual-retune
history for `llm_max_concurrent` (4 -> 2 -> 1 -> 2 -> 1 -> 2) was
always driven by, now automated instead of requiring a person to read
a `/diagnostics` dump and pick a new number by hand.

A real change resizes the ACTUAL concurrency gate in-flight LLM calls
run through — `CognitionRunner.resize_concurrency()`, backed by a new
`llm/jobs.py`'s `_ResizableSemaphore` (grows by releasing new permits
immediately; shrinks by swallowing that many future releases instead
of forcibly reclaiming a permit already held, so an in-flight call is
never interrupted).

This script proves, standalone (no unittest, same convention as every
other `verify_*.py` here): the resizable semaphore's grow/shrink
correctness under real concurrent `asyncio` tasks (including the
load-bearing case — shrinking while permits are held doesn't disrupt
the holder, and the effective limit only actually drops once enough
releases have been swallowed); `_maybe_tune_llm_concurrency`'s real
gates (LLM disabled -> no-op, insufficient evidence -> no-op); a
genuine severe-latency reading lowers live concurrency and actually
resizes the real semaphore, logging the change; a genuine healthy-
latency reading raises it back; the bounded ±1 step and legal-range
clamp hold under repeated calls; and a no-op check is never logged
(only genuine changes are).

Tier 5 B7.3's later real wiring (`select_strategy`'s output as a
downward-only cap, see `verify_b7_hardware_citizenship.py`/`verify_
b8_predictive_scheduling.py`) means `_maybe_tune_llm_concurrency` now
consults a SECOND real signal alongside B6's own bang-bang controller
— this script's own scenarios (deliberately moving `llm_max_concurrent`
up to 4, above `select_strategy`'s own hardcoded ceiling of 3) patch
`select_strategy` to a permissive stand-in for the duration of these
checks so B6's bang-bang mechanics are proven in isolation, exactly as
this script's own stated scope always was — B7.3's real interaction
with B6 is covered by the two scripts named above, not duplicated here.
"""
import asyncio
import sys
import tempfile
from unittest import mock

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.llm.jobs import _ResizableSemaphore
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    ADAPTIVE_CONCURRENCY_HYSTERESIS_MS, ADAPTIVE_CONCURRENCY_MIN_EVIDENCE, ADAPTIVE_CONCURRENCY_TARGET_MS,
    SimulationEngine,
)
from hearthmind.simulation.hardware_profile import Strategy

_PERMISSIVE_STRATEGY = Strategy(
    llm_max_concurrent_hint=8, worker_count_hint=8, cache_size_hint="large", dormancy_aggressiveness="low",
)

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, seed: int = 1, llm_max_concurrent: int = 4) -> SimulationEngine:
    conn = connect(f"{tmpdir}/adaptive_concurrency.db")
    cfg = Config(
        db_path=f"{tmpdir}/adaptive_concurrency.db", llm_enabled=False, seed=seed,
        initial_population=5, width=32, height=32, llm_max_concurrent=llm_max_concurrent,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def fill_latency(eng: SimulationEngine, ms: float, count: int) -> None:
    eng._cognition_runner._latencies_ms.clear()
    for _ in range(count):
        eng._cognition_runner._latencies_ms.append(ms)
    eng._cognition_runner.calls_attempted = max(eng._cognition_runner.calls_attempted, count)


async def main() -> None:
    # 1. Resizable semaphore: grow correctness.
    sem = _ResizableSemaphore(1)
    await sem.acquire()
    sem.resize(3)
    check("resize() up releases new permits immediately", sem.limit == 3)
    grew_ok = True
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0.2)
        await asyncio.wait_for(sem.acquire(), timeout=0.2)
    except asyncio.TimeoutError:
        grew_ok = False
    check("two more acquires succeed immediately after growing to 3", grew_ok)

    # 2. Resizable semaphore: shrink correctness -- the load-bearing case.
    #    Shrinking while permits are held must not disrupt the holder,
    #    and the effective limit only actually drops once enough
    #    releases have been swallowed.
    sem2 = _ResizableSemaphore(3)
    await sem2.acquire()
    await sem2.acquire()
    await sem2.acquire()
    sem2.resize(1)
    check("resize() down never forcibly reclaims a held permit", sem2._pending_shrink == 2)
    sem2.release()
    sem2.release()
    check("two swallowed releases don't reopen a slot", sem2._pending_shrink == 0)
    # third release genuinely frees the one real remaining slot
    sem2.release()
    acquired = False

    async def _try_acquire() -> None:
        nonlocal acquired
        await sem2.acquire()
        acquired = True

    task = asyncio.create_task(_try_acquire())
    await asyncio.sleep(0.05)
    check("exactly one real permit is available after shrinking to 1", acquired)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # a second concurrent acquire is genuinely blocked at the new limit
    acquired2 = False

    async def _try_acquire2() -> None:
        nonlocal acquired2
        await sem2.acquire()
        acquired2 = True

    task2 = asyncio.create_task(_try_acquire2())
    await asyncio.sleep(0.05)
    check("a second acquire is genuinely blocked once the shrunk limit (1) is held", not acquired2)
    task2.cancel()
    try:
        await task2
    except asyncio.CancelledError:
        pass

    # 3-8. Real SimulationEngine._maybe_tune_llm_concurrency, driven end
    #      to end (not a synthetic stand-in), including its real gates.
    #      `select_strategy` patched permissive for this whole block —
    #      see the module docstring's note on B7.3.
    strategy_patch = mock.patch("hearthmind.simulation.engine.select_strategy", return_value=_PERMISSIVE_STRATEGY)
    strategy_patch.start()
    with tempfile.TemporaryDirectory() as d:
        eng = make_engine(d, llm_max_concurrent=4)

        # LLM disabled -> genuine no-op even with severe latency data.
        fill_latency(eng, 90_000.0, 30)
        before = eng._tuning_registry.get("llm_max_concurrent").value
        eng._maybe_tune_llm_concurrency()
        check(
            "LLM disabled: no-op regardless of measured latency",
            eng._tuning_registry.get("llm_max_concurrent").value == before
            and len(eng._adaptive_tuning_log) == 0,
        )

        eng._cognition_runner.client = object()  # enable

        # Insufficient evidence -> genuine no-op.
        eng._cognition_runner._latencies_ms.clear()
        eng._cognition_runner._latencies_ms.append(90_000.0)
        eng._cognition_runner.calls_attempted = 1
        check("calls_attempted below min-evidence floor is a real gate", 1 < ADAPTIVE_CONCURRENCY_MIN_EVIDENCE)
        eng._maybe_tune_llm_concurrency()
        check(
            "insufficient evidence: no-op even with severe latency present",
            eng._tuning_registry.get("llm_max_concurrent").value == before
            and len(eng._adaptive_tuning_log) == 0,
        )

        # Severe measured latency genuinely lowers live concurrency AND
        # resizes the real semaphore in step, logging exactly one entry.
        fill_latency(eng, 90_000.0, 30)
        sem_limit_before = eng._cognition_runner._semaphore.limit
        eng._maybe_tune_llm_concurrency()
        after_severe = eng._tuning_registry.get("llm_max_concurrent").value
        check(
            "severe latency lowers the live concurrency value by exactly one step",
            after_severe == before - 1,
        )
        check(
            "the REAL semaphore's limit tracks the new value (not just the Tunable)",
            eng._cognition_runner._semaphore.limit == after_severe
            and eng._cognition_runner._semaphore.limit == sem_limit_before - 1,
        )
        check(
            "CognitionRunner.max_concurrent (read by backpressure math) tracks the new value",
            eng._cognition_runner.max_concurrent == after_severe,
        )
        check("a genuine change is logged exactly once", len(eng._adaptive_tuning_log) == 1)
        entry = eng._adaptive_tuning_log[-1]
        check(
            "the logged entry records real before/after/measured values",
            entry["before"] == before and entry["after"] == after_severe
            and entry["measured_p95_ms"] >= ADAPTIVE_CONCURRENCY_TARGET_MS + ADAPTIVE_CONCURRENCY_HYSTERESIS_MS,
        )

        # Healthy measured latency genuinely raises it back.
        fill_latency(eng, 5_000.0, 30)
        eng._maybe_tune_llm_concurrency()
        after_healthy = eng._tuning_registry.get("llm_max_concurrent").value
        check("healthy latency raises live concurrency back up by one step", after_healthy == after_severe + 1)
        check("a second genuine change is logged", len(eng._adaptive_tuning_log) == 2)

        # A reading squarely inside the hysteresis dead-zone is a
        # genuine no-op, not logged.
        fill_latency(eng, ADAPTIVE_CONCURRENCY_TARGET_MS, 30)
        before_deadzone = eng._tuning_registry.get("llm_max_concurrent").value
        log_len_before = len(eng._adaptive_tuning_log)
        eng._maybe_tune_llm_concurrency()
        check(
            "a reading at the target (inside the hysteresis dead-zone) is a real no-op",
            eng._tuning_registry.get("llm_max_concurrent").value == before_deadzone
            and len(eng._adaptive_tuning_log) == log_len_before,
        )

        # Repeated severe readings never overshoot the registered legal
        # range (min_value=1) -- the Tunable's own clamp holds.
        eng2_registry_min = eng._tuning_registry.get("llm_max_concurrent").min_value
        for _ in range(20):
            fill_latency(eng, 90_000.0, 30)
            eng._maybe_tune_llm_concurrency()
        check(
            "repeated severe readings never push concurrency below the registered floor",
            eng._tuning_registry.get("llm_max_concurrent").value >= eng2_registry_min,
        )

        # Diagnostics surfacing: the live value (not the frozen config
        # default) is what _diagnostics_snapshot reports.
        snap = eng._diagnostics_snapshot()
        check(
            "_diagnostics_snapshot reports the LIVE concurrency value, distinct from the static default",
            snap["llm_max_concurrent"] == eng._cognition_runner.max_concurrent
            and snap["llm_max_concurrent_static_default"] == 4,
        )
        full = eng.full_diagnostics()
        check(
            "full_diagnostics exposes the real adaptive_tuning_log_recent",
            "adaptive_tuning_log_recent" in full and len(full["adaptive_tuning_log_recent"]) > 0,
        )
    strategy_patch.stop()

    # 9. A fresh engine seeded from a non-default config.llm_max_
    #    concurrent starts the controller at that real value, not the
    #    tuning module's own hardcoded default (2) -- a CLI override
    #    must be respected as the real starting point.
    with tempfile.TemporaryDirectory() as d2:
        eng3 = make_engine(d2, seed=2, llm_max_concurrent=6)
        check(
            "the tuning registry is seeded from the real config value, not tuning.py's own default",
            eng3._tuning_registry.get("llm_max_concurrent").value == 6,
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
