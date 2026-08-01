#!/usr/bin/env python3
"""Tier 5 B2 verification (budgets & scheduling).

Standalone verification script, not a unittest — same convention as
every other verify_*.py in this directory. Exercises `hearthmind.
simulation.scheduler` against a synthetic task set (this module is not
wired into the live tick loop yet, per B1/B2's own "never big-bang").

Checks:
  1. A CRITICAL task always runs, even with zero remaining budget.
  2. A STANDARD task whose subsystem is out of budget is DEFERRED, not
     skipped — it stays a candidate and its deferral count increments.
  3. B2.2's bounded deferral: a repeatedly budget-starved task is
     force-run ("promoted") once its deferral count crosses its
     priority class's bound — no starvation.
  4. B2.3's overrun tracking: a subsystem that spends past its own
     budget in a tick accrues real `debt_seconds`, and that debt
     persists (never silently reset) across ticks.
  5. B2.5's work-conserving pass: a deferred BACKGROUND task runs
     within the SAME tick when spare overall tick-time capacity exists,
     rather than waiting for a future tick.
"""
from __future__ import annotations

import sys

from hearthmind.simulation.scheduler import DEFAULT_MAX_DEFERRALS, Scheduler, SubsystemBudget
from hearthmind.simulation.task_graph import PriorityClass, Task, TaskRegistry, TriggerKind


def _slow(seconds: float):
    def _fn():
        # Busy-wait rather than time.sleep — this module is execution-
        # layer code (simulation/, not world/agents/settlement/economy),
        # so B0's invariant doesn't forbid time.sleep here, but a busy
        # loop keeps the check independent of OS scheduler granularity
        # at these very small durations.
        import time
        start = time.perf_counter()
        while time.perf_counter() - start < seconds:
            pass
    return _fn


def _fast():
    pass


def check_critical_always_runs() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="c", subsystem="core", fn=_fast, trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.CRITICAL))
    sched = Scheduler(reg, {"core": SubsystemBudget(subsystem="core", seconds_per_tick=0.0)})
    report = sched.run_tick()
    assert report.ran == ["c"], report.ran
    assert not report.deferred, report.deferred


def check_standard_deferred_not_skipped() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=_slow(0.01), trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.STANDARD))
    sched = Scheduler(reg, {"x": SubsystemBudget(subsystem="x", seconds_per_tick=0.0)})
    report = sched.run_tick()
    assert report.deferred == ["a"], report.deferred
    assert not report.ran, report.ran
    assert sched._deferral_counts["a"] == 1


def check_bounded_deferral_promotes() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=_fast, trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.DEFERRABLE))
    sched = Scheduler(reg, {"x": SubsystemBudget(subsystem="x", seconds_per_tick=0.0)})
    bound = DEFAULT_MAX_DEFERRALS[PriorityClass.DEFERRABLE]
    for _ in range(bound):
        report = sched.run_tick()
        assert report.deferred == ["a"], report.deferred
    # One more tick: deferral count has now reached the bound -> forced.
    report = sched.run_tick()
    assert report.ran == ["a"], report.ran
    assert report.promoted == ["a"], report.promoted


def check_overrun_debt_persists() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=_slow(0.02), trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.CRITICAL))
    budget = SubsystemBudget(subsystem="x", seconds_per_tick=0.001)
    sched = Scheduler(reg, {"x": budget})
    sched.run_tick()
    assert budget.debt_seconds > 0, budget.debt_seconds
    debt_after_first = budget.debt_seconds
    sched.run_tick()
    assert budget.debt_seconds > debt_after_first, (debt_after_first, budget.debt_seconds)


def check_work_conserving_spare_capacity() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="bg", subsystem="x", fn=_fast, trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.BACKGROUND))
    sched = Scheduler(reg, {"x": SubsystemBudget(subsystem="x", seconds_per_tick=0.0)})
    # No overall tick_time_budget_seconds -> stays deferred (baseline).
    report = sched.run_tick()
    assert report.deferred == ["bg"], report.deferred

    # Fresh scheduler, now WITH spare overall tick time available.
    reg2 = TaskRegistry()
    reg2.register(Task(id="bg", subsystem="x", fn=_fast, trigger=TriggerKind.PERIODIC,
                        priority_class=PriorityClass.BACKGROUND))
    sched2 = Scheduler(reg2, {"x": SubsystemBudget(subsystem="x", seconds_per_tick=0.0)})
    report2 = sched2.run_tick(tick_time_budget_seconds=1.0)
    assert report2.ran == ["bg"], report2.ran
    assert report2.ran_via_spare_capacity == ["bg"], report2.ran_via_spare_capacity
    assert not report2.deferred, report2.deferred


def main() -> int:
    checks = [
        check_critical_always_runs,
        check_standard_deferred_not_skipped,
        check_bounded_deferral_promotes,
        check_overrun_debt_persists,
        check_work_conserving_spare_capacity,
    ]
    for check in checks:
        check()
        print(f"OK: {check.__name__}")
    print(f"Scheduler verification OK — {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
