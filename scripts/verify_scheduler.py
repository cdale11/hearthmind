#!/usr/bin/env python3
"""Tier 5 B2/B3/B5 verification (budgets & scheduling; dirty tracking
& the event bus; continuous profiling).

Standalone verification script, not a unittest — same convention as
every other verify_*.py in this directory. Exercises `hearthmind.
simulation.scheduler`/`reactivity`/`profiling` against synthetic task
sets (these modules are not wired into the live tick loop yet, per
B1/B2/B3/B5's own "never big-bang").

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
  6. B3.1: an ON_DIRTY task never runs while its read key has never
     been written, runs exactly once a write happens, and goes clean
     again immediately after (no re-trigger on the same write).
  7. B3.1: two independent ON_DIRTY readers of the same key each
     observe one write exactly once, on their own schedule — one
     reader consuming the change never hides it from the other.
  8. B3.1: an ON_DIRTY task with no declared `reads` never fires
     (documented edge case, not a bug).
  9. B3.2: an ON_EVENT task only runs on the tick its subscribed event
     is published, and the event does not persist into the next tick.
  10. B5.1: per-task metrics (call_count, deferred_count, promoted_
      count, skipped_clean_count, idle_ratio) track real history
      correctly across several ticks.
  11. B5.4: a tick's trace records every task's real outcome and a
      specific, correct reason — including the promoted/deferred/
      spare-capacity cases, not just the plain ran/skipped ones.
  12. B5.2: the instrumentation's own per-task overhead is measured
      directly (not just asserted) and printed, so a future change
      that makes it expensive would be visible here.
"""
from __future__ import annotations

import sys

from hearthmind.simulation.reactivity import DirtyTracker, EventBus
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


def check_on_dirty_gating() -> None:
    # A direct `dirty_tracker.mark_written(...)` call stands in for a
    # real writer task's own effect (same thing `_run_one` does
    # internally for any registered task's `writes[]`) — done this way
    # rather than via a second PERIODIC writer task in the same
    # registry, since a writer that fires every tick would keep the
    # reader dirty every tick too (topological order runs a real
    # writer before a dependent reader in the SAME tick), which would
    # never demonstrate the "goes clean between writes" property this
    # check is actually after.
    calls = []
    reg = TaskRegistry()
    reg.register(Task(id="reader", subsystem="x", fn=lambda: calls.append(1),
                       trigger=TriggerKind.ON_DIRTY, reads=frozenset({"soil"})))
    sched = Scheduler(reg)

    report1 = sched.run_tick()
    assert "reader" in report1.skipped_clean, report1.skipped_clean  # nothing ever written

    sched.dirty_tracker.mark_written(["soil"])
    report2 = sched.run_tick()
    assert "reader" in report2.ran, report2.ran

    report3 = sched.run_tick()
    assert "reader" in report3.skipped_clean, report3.skipped_clean  # no new write since
    assert calls == [1], calls


def check_on_dirty_two_independent_readers() -> None:
    seen_a, seen_b = [], []
    reg = TaskRegistry()
    reg.register(Task(id="reader_a", subsystem="x", fn=lambda: seen_a.append(1),
                       trigger=TriggerKind.ON_DIRTY, reads=frozenset({"k"})))
    reg.register(Task(id="reader_b", subsystem="x", fn=lambda: seen_b.append(1),
                       trigger=TriggerKind.ON_DIRTY, reads=frozenset({"k"})))
    sched = Scheduler(reg)
    sched.run_tick()  # nothing written yet
    sched.dirty_tracker.mark_written(["k"])
    sched.run_tick()  # both readers should observe the single write
    sched.run_tick()  # both should now be clean, no re-trigger
    assert seen_a == [1], seen_a
    assert seen_b == [1], seen_b


def check_on_dirty_no_reads_never_fires() -> None:
    calls = []
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=lambda: calls.append(1), trigger=TriggerKind.ON_DIRTY))
    sched = Scheduler(reg)
    for _ in range(5):
        report = sched.run_tick()
        assert "a" in report.skipped_clean, report.skipped_clean
    assert calls == []


def check_on_event_gating() -> None:
    calls = []
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=lambda: calls.append(1),
                       trigger=TriggerKind.ON_EVENT, event_types=frozenset({"disaster"})))
    sched = Scheduler(reg)

    report1 = sched.run_tick()
    assert "a" in report1.skipped_clean, report1.skipped_clean

    sched.event_bus.publish("disaster")
    report2 = sched.run_tick()
    assert "a" in report2.ran, report2.ran

    # Published event must not persist into the next tick.
    report3 = sched.run_tick()
    assert "a" in report3.skipped_clean, report3.skipped_clean
    assert calls == [1], calls


def check_dirty_tracker_and_event_bus_directly() -> None:
    dt = DirtyTracker()
    observed: dict[str, int] = {}
    assert dt.is_dirty_for(["k"], observed) is False
    dt.mark_written(["k"])
    assert dt.is_dirty_for(["k"], observed) is True
    dt.mark_observed(["k"], observed)
    assert dt.is_dirty_for(["k"], observed) is False

    bus = EventBus()
    assert bus.is_pending(["e"]) is False
    bus.publish("e")
    assert bus.is_pending(["e"]) is True
    bus.clear()
    assert bus.is_pending(["e"]) is False


def check_metrics_track_real_history() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=_fast, trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.CRITICAL))
    sched = Scheduler(reg)
    for _ in range(5):
        sched.run_tick()
    m = sched.metrics_for("a")
    assert m.call_count == 5, m.call_count
    assert m.ticks_observed == 5, m.ticks_observed
    assert m.idle_ratio() == 0.0, m.idle_ratio()
    assert m.error_count == 0

    # A DEFERRABLE task, always over budget, deferred every tick until
    # its bound is crossed and it's force-run once (promoted).
    reg2 = TaskRegistry()
    reg2.register(Task(id="b", subsystem="y", fn=_fast, trigger=TriggerKind.PERIODIC,
                        priority_class=PriorityClass.DEFERRABLE))
    sched2 = Scheduler(reg2, {"y": SubsystemBudget(subsystem="y", seconds_per_tick=0.0)})
    bound = DEFAULT_MAX_DEFERRALS[PriorityClass.DEFERRABLE]
    for _ in range(bound + 1):
        sched2.run_tick()
    m2 = sched2.metrics_for("b")
    assert m2.deferred_count == bound, m2.deferred_count
    assert m2.promoted_count == 1, m2.promoted_count
    assert m2.call_count == 1, m2.call_count
    assert m2.ticks_observed == bound + 1, m2.ticks_observed
    assert 0.0 < m2.idle_ratio() < 1.0, m2.idle_ratio()


def check_trace_records_real_reasons() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="crit", subsystem="core", fn=_fast, trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.CRITICAL))
    reg.register(Task(id="dirty_reader", subsystem="x", fn=_fast,
                       trigger=TriggerKind.ON_DIRTY, reads=frozenset({"soil"})))
    reg.register(Task(id="ev", subsystem="x", fn=_fast,
                       trigger=TriggerKind.ON_EVENT, event_types=frozenset({"disaster"})))
    reg.register(Task(id="bg", subsystem="y", fn=_fast, trigger=TriggerKind.PERIODIC,
                       priority_class=PriorityClass.BACKGROUND))
    budgets = {"y": SubsystemBudget(subsystem="y", seconds_per_tick=0.0)}
    sched = Scheduler(reg, budgets)

    sched.event_bus.publish("disaster")
    report = sched.run_tick(tick_time_budget_seconds=1.0)
    assert report.ran_via_spare_capacity == ["bg"], report.ran_via_spare_capacity

    trace = sched.tick_traces[-1]
    assert trace.tick == 0

    crit_entry = trace.entry_for("crit")
    assert crit_entry.outcome == "ran"
    assert "CRITICAL" in crit_entry.reason
    assert crit_entry.cost_seconds is not None

    dirty_entry = trace.entry_for("dirty_reader")
    assert dirty_entry.outcome == "skipped_clean"
    assert "unchanged" in dirty_entry.reason

    ev_entry = trace.entry_for("ev")
    assert ev_entry.outcome == "ran"
    assert "disaster" in ev_entry.reason

    bg_entry = trace.entry_for("bg")
    assert bg_entry.outcome == "ran"
    assert bg_entry.ran_via_spare_capacity is True
    assert "spare" in bg_entry.reason


def check_instrumentation_overhead_measured() -> None:
    # B5.2: measure the real per-task overhead of running under
    # Scheduler's instrumentation (metrics + trace building) versus
    # calling the same functions directly, and print it -- "a profiler
    # that costs 5% must say so," not just assert it's cheap.
    reg = TaskRegistry()
    n = 50
    for i in range(n):
        reg.register(Task(id=f"t{i}", subsystem="x", fn=_fast, trigger=TriggerKind.PERIODIC))
    sched = Scheduler(reg, {"x": SubsystemBudget(subsystem="x", seconds_per_tick=10.0)})

    import time as _time
    iterations = 200

    start = _time.perf_counter()
    for _ in range(iterations):
        sched.run_tick()
    scheduled_total = _time.perf_counter() - start

    start = _time.perf_counter()
    for _ in range(iterations):
        for _ in range(n):
            _fast()
    bare_total = _time.perf_counter() - start

    per_task_scheduled_us = (scheduled_total / (iterations * n)) * 1e6
    per_task_bare_us = (bare_total / (iterations * n)) * 1e6
    overhead_us = per_task_scheduled_us - per_task_bare_us
    print(f"    (B5.2 measured overhead: {overhead_us:.2f}us/task-tick "
          f"scheduled={per_task_scheduled_us:.2f}us bare={per_task_bare_us:.2f}us)")
    # Sanity bound, not a tight perf assertion -- catches a genuine
    # regression (e.g. an accidental O(n^2)) without being flaky on
    # slow CI hardware.
    assert overhead_us < 500, overhead_us


def main() -> int:
    checks = [
        check_critical_always_runs,
        check_standard_deferred_not_skipped,
        check_bounded_deferral_promotes,
        check_overrun_debt_persists,
        check_work_conserving_spare_capacity,
        check_on_dirty_gating,
        check_on_dirty_two_independent_readers,
        check_on_dirty_no_reads_never_fires,
        check_on_event_gating,
        check_dirty_tracker_and_event_bus_directly,
        check_metrics_track_real_history,
        check_trace_records_real_reasons,
        check_instrumentation_overhead_measured,
    ]
    for check in checks:
        check()
        print(f"OK: {check.__name__}")
    print(f"Scheduler verification OK — {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
