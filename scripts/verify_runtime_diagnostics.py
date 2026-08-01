#!/usr/bin/env python3
"""Standalone verification for B5.3 (Expose everything at
`/diagnostics/runtime` + dev console, docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B). Same convention as every sibling scripts/
verify_*.py: no unittest, no CI pipeline, run manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.runtime_diagnostics import (
    explain_tick,
    format_runtime_diagnostics_text,
    runtime_diagnostics_report,
)
from hearthmind.simulation.scheduler import Scheduler, SubsystemBudget
from hearthmind.simulation.task_graph import PriorityClass, Task, TaskRegistry, TriggerKind

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _fast():
    return None


def _build_real_scheduler():
    """A real Scheduler over a real TaskRegistry with real tasks run
    through real ticks -- not a mocked shape. One PERIODIC task that
    always runs, one deliberately over-budget task that defers, and
    one ON_DIRTY task that starts clean (never fires)."""
    reg = TaskRegistry()
    reg.register(Task(id="periodic_a", subsystem="core", fn=_fast,
                       trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.STANDARD))
    reg.register(Task(id="deferred_b", subsystem="slow", fn=_fast,
                       trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.DEFERRABLE))
    reg.register(Task(id="dirty_c", subsystem="core", fn=_fast,
                       trigger=TriggerKind.ON_DIRTY, reads=frozenset({"never_written"}),
                       priority_class=PriorityClass.STANDARD))
    sched = Scheduler(reg, {
        "core": SubsystemBudget(subsystem="core", seconds_per_tick=1.0),
        "slow": SubsystemBudget(subsystem="slow", seconds_per_tick=0.0),  # forces deferred_b to defer, then promote past its DEFERRABLE bound
    })
    # DEFAULT_MAX_DEFERRALS[DEFERRABLE] == 3 -- deferred_b defers on
    # ticks 0-2, then is force-run ("promoted") on tick 3, which is
    # the tick that actually consumes real wall time against its
    # zero-budget subsystem and accrues real debt. 5 ticks gives that
    # promotion room to happen and be observed.
    for _ in range(5):
        sched.run_tick()
    return sched


def check_report_shape_and_real_data():
    sched = _build_real_scheduler()
    report = runtime_diagnostics_report(sched)

    check("report: has the expected top-level keys", set(report.keys()) == {"tick_traces_available", "tasks", "subsystems", "latest_tick"})
    check("report: tick_traces_available reflects real recorded ticks", report["tick_traces_available"] == 5)

    task_ids = {t["task_id"] for t in report["tasks"]}
    check("report: every real registered task appears exactly once", task_ids == {"periodic_a", "deferred_b", "dirty_c"})

    periodic = next(t for t in report["tasks"] if t["task_id"] == "periodic_a")
    check("report: periodic_a's real call_count matches the number of ticks run", periodic["call_count"] == 5)

    dirty = next(t for t in report["tasks"] if t["task_id"] == "dirty_c")
    check("report: dirty_c (never-written reads) has zero real calls -- it was skipped_clean every tick", dirty["call_count"] == 0 and dirty["skipped_clean_count"] == 5)

    subsystem_names = {s["subsystem"] for s in report["subsystems"]}
    check("report: both real subsystems are present", subsystem_names == {"core", "slow"})
    slow_budget = next(s for s in report["subsystems"] if s["subsystem"] == "slow")
    check("report: the deliberately zero-budget subsystem shows real accrued debt", slow_budget["debt_seconds"] > 0.0)


def check_latest_tick_matches_the_real_scheduler_trace():
    sched = _build_real_scheduler()
    report = runtime_diagnostics_report(sched)
    real_trace = sched.tick_traces[-1]
    check(
        "report: latest_tick reflects the REAL scheduler's own most recent TickTrace, not a stale/synthetic one",
        report["latest_tick"]["tick"] == real_trace.tick and len(report["latest_tick"]["entries"]) == len(real_trace.entries),
    )
    check(
        "report: latest_tick entries carry the real per-task outcome and reason strings",
        all(e["reason"] for e in report["latest_tick"]["entries"]),
    )


def check_empty_scheduler_reports_honestly():
    reg = TaskRegistry()
    sched = Scheduler(reg)
    report = runtime_diagnostics_report(sched)
    check("report: a scheduler with no ticks run yet reports zero traces, not a crash", report["tick_traces_available"] == 0)
    check("report: latest_tick is honestly None when nothing has run", report["latest_tick"] is None)


def check_explain_tick_finds_a_real_tick():
    sched = _build_real_scheduler()
    explanation = explain_tick(sched, tick=1)
    check("explain_tick: finds the real trace for a tick that actually happened", explanation is not None and explanation["tick"] == 1)
    check("explain_tick: contains every real task's outcome for that tick", {e["task_id"] for e in explanation["entries"]} == {"periodic_a", "deferred_b", "dirty_c"})


def check_explain_tick_honestly_returns_none_for_unknown_tick():
    sched = _build_real_scheduler()
    explanation = explain_tick(sched, tick=99999)
    check("explain_tick: a tick that never happened (or aged out) returns None, not a fabricated trace", explanation is None)


def check_text_formatter_is_real_and_non_empty():
    sched = _build_real_scheduler()
    text = format_runtime_diagnostics_text(sched)
    check("format_runtime_diagnostics_text: produces real, non-empty output", isinstance(text, str) and len(text) > 0)
    check("format_runtime_diagnostics_text: mentions every real task by name", all(task_id in text for task_id in ("periodic_a", "deferred_b", "dirty_c")))
    check("format_runtime_diagnostics_text: mentions every real subsystem by name", "core" in text and "slow" in text)


def check_scheduler_all_budgets_accessor_matches_budget_for():
    sched = _build_real_scheduler()
    all_budgets = sched.all_budgets()
    check("Scheduler.all_budgets: returns every real subsystem budget registered so far", set(all_budgets.keys()) == {"core", "slow"})
    check("Scheduler.all_budgets: the SAME object budget_for() would return (not a stale copy of the value)", all_budgets["slow"].debt_seconds == sched.budget_for("slow").debt_seconds)


def main():
    check_report_shape_and_real_data()
    check_latest_tick_matches_the_real_scheduler_trace()
    check_empty_scheduler_reports_honestly()
    check_explain_tick_finds_a_real_tick()
    check_explain_tick_honestly_returns_none_for_unknown_tick()
    check_text_formatter_is_real_and_non_empty()
    check_scheduler_all_budgets_accessor_matches_budget_for()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
