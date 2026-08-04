#!/usr/bin/env python3
"""Explicit user directive ("keep building adaptive runtime to what I
originally wanted"): the real automatic monthly cadence for Tier 5
B13's `HypothesisLoop` over `llm_max_concurrent`
(`SimulationEngine._maybe_auto_llm_concurrency_hypothesis`), gated so
it can never fight `_maybe_tune_llm_concurrency`'s own live daily
`BangBangController` over the same tunable. Real production-path
checks against a real `SimulationEngine`/`World`, no unittest, same
standalone-script convention as every sibling `verify_*.py`."""
from __future__ import annotations

import asyncio
import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS, SimulationEngine
from hearthmind.simulation.hardware_profile import Strategy

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


def make_engine(llm_enabled: bool = True) -> SimulationEngine:
    global _COUNTER
    _COUNTER += 1
    db_path = f"{_TMPDIR}/auto_hyp_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=llm_enabled, seed=321, initial_population=8, width=20, height=20)
    return SimulationEngine.load_or_create(conn, cfg)


async def _call_and_drain(eng: SimulationEngine, fn, *args) -> None:
    """`asyncio.create_task` (used inside `_spawn_llm_concurrency_
    hypothesis`) needs a running loop, so both the call that MIGHT
    spawn a task and the drain that waits for it must run inside the
    same `asyncio.run`."""
    fn(*args)
    for _ in range(50):
        if not eng._llm_concurrency_hypothesis_running:
            return
        await asyncio.sleep(0.05)


def ticks_per_day(eng: SimulationEngine) -> int:
    return eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick


def strategy(hint: int) -> Strategy:
    return Strategy(
        llm_max_concurrent_hint=hint, worker_count_hint=4, cache_size_hint="normal",
        dormancy_aggressiveness="normal",
    )


def main() -> int:
    # LLM disabled: never spawns, regardless of month_end (no running
    # loop needed -- the early return happens before create_task).
    eng1 = make_engine(llm_enabled=False)
    eng1._last_strategy = strategy(9)
    eng1._maybe_auto_llm_concurrency_hypothesis(["month_end"])
    check("LLM-disabled engine never spawns an automatic hypothesis", not eng1._llm_concurrency_hypothesis_running)

    # No month_end event: no-op even with everything else eligible.
    eng2 = make_engine(llm_enabled=True)
    eng2._last_strategy = strategy(9)
    eng2._maybe_auto_llm_concurrency_hypothesis(["day_end"])
    check("a non-month_end tick never spawns an automatic hypothesis", not eng2._llm_concurrency_hypothesis_running)

    # No select_strategy reading taken yet (_last_strategy is None): skip.
    eng3 = make_engine(llm_enabled=True)
    check("_last_strategy starts None on a fresh engine", eng3._last_strategy is None)
    eng3._maybe_auto_llm_concurrency_hypothesis(["month_end"])
    check("no real select_strategy reading yet means no automatic hypothesis fires",
          not eng3._llm_concurrency_hypothesis_running)

    # Hint matches the current value: nothing to genuinely test, skip.
    eng4 = make_engine(llm_enabled=True)
    current = int(eng4._tuning_registry.get("llm_max_concurrent").value)
    eng4._last_strategy = strategy(current)
    eng4._maybe_auto_llm_concurrency_hypothesis(["month_end"])
    check("a hint that already matches the current value never spawns a hypothesis",
          not eng4._llm_concurrency_hypothesis_running)

    # A real change within the quiet window (the reactive controller
    # just adjusted) blocks the automatic hypothesis this month.
    eng5 = make_engine(llm_enabled=True)
    different_hint = current + 3
    eng5._last_strategy = strategy(different_hint)
    eng5._adaptive_tuning_log.append({
        "tick": eng5.world.clock.tick_count, "tunable": "llm_max_concurrent",
        "before": 1, "after": 2, "measured_p95_ms": 1000.0, "target_ms": 500.0,
        "host_pressure_veto": False, "strategy_cap_applied": False,
    })
    eng5._maybe_auto_llm_concurrency_hypothesis(["month_end"])
    check("a very recent real reactive-controller change blocks the automatic hypothesis (not quiet yet)",
          not eng5._llm_concurrency_hypothesis_running)

    # A real change OUTSIDE the quiet window (long enough ago) no
    # longer blocks it -- the automatic hypothesis genuinely fires.
    eng6 = make_engine(llm_enabled=True)
    eng6._last_strategy = strategy(different_hint)
    # Same real "advance the clock directly rather than tick through
    # it" technique this codebase's own dormancy verify scripts use
    # (see CLAUDE.md's B4.2 pilot entries) -- a fresh engine starts at
    # tick 0, so there's otherwise no way to place a real log entry far
    # enough in the past to test genuine quiescence.
    eng6.world.clock.tick_count = (LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS + 30) * ticks_per_day(eng6)
    old_tick = eng6.world.clock.tick_count - (LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS + 5) * ticks_per_day(eng6)
    eng6._adaptive_tuning_log.append({
        "tick": max(old_tick, 0), "tunable": "llm_max_concurrent",
        "before": 1, "after": 2, "measured_p95_ms": 1000.0, "target_ms": 500.0,
        "host_pressure_veto": False, "strategy_cap_applied": False,
    })
    asyncio.run(_call_and_drain(eng6, eng6._maybe_auto_llm_concurrency_hypothesis, ["month_end"]))
    check("a genuinely quiet reactive-controller history lets the automatic hypothesis genuinely run to completion",
          eng6._last_llm_concurrency_hypothesis is not None
          and eng6._last_llm_concurrency_hypothesis.get("source") == "auto"
          and not eng6._llm_concurrency_hypothesis_running)

    # An empty adaptive_tuning_log (no reactive change ever) is treated
    # as quiet from the start -- the automatic hypothesis can fire.
    eng7 = make_engine(llm_enabled=True)
    eng7._last_strategy = strategy(different_hint)
    check("a fresh engine's adaptive_tuning_log starts empty", len(eng7._adaptive_tuning_log) == 0)
    asyncio.run(_call_and_drain(eng7, eng7._maybe_auto_llm_concurrency_hypothesis, ["month_end"]))
    check("an empty reactive-controller history (never adjusted) lets the automatic hypothesis run to completion",
          eng7._last_llm_concurrency_hypothesis is not None
          and eng7._last_llm_concurrency_hypothesis.get("source") == "auto")

    # Already running: a second automatic call is silently dropped, not
    # queued or stacked (shared _spawn_llm_concurrency_hypothesis path).
    eng8 = make_engine(llm_enabled=True)
    eng8._last_strategy = strategy(different_hint)
    eng8._llm_concurrency_hypothesis_running = True
    eng8._maybe_auto_llm_concurrency_hypothesis(["month_end"])
    check("a hypothesis already in flight blocks a second automatic request from spawning a fresh one",
          eng8._last_llm_concurrency_hypothesis is None)

    # The manual dev-console/API path still works unchanged (source
    # tagged "manual") and is still gated one-at-a-time by the shared
    # spawn helper.
    eng9 = make_engine(llm_enabled=True)
    asyncio.run(_call_and_drain(
        eng9, eng9._maybe_start_llm_concurrency_hypothesis, {"proposed_value": 3, "hypothesis": "manual test"},
    ))
    check("the manual trigger still spawns and completes a real hypothesis run, tagged source=manual",
          eng9._last_llm_concurrency_hypothesis is not None
          and eng9._last_llm_concurrency_hypothesis.get("source") == "manual")

    # A real production-path drive: a 2000-tick run with LLM disabled
    # never crashes even though the automatic job is registered in
    # _TICK_JOBS and dispatched every real month_end tick.
    eng10 = make_engine(llm_enabled=False)

    async def _drive():
        for _ in range(2000):
            eng10._tick_once()

    asyncio.run(_drive())
    check("a real 2000-tick production run with the automatic job registered never crashes", True)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
