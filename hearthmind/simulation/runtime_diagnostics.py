"""B5.3 -- Expose everything at `/diagnostics/runtime` + dev console
(docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rules 5, 15]).
Standalone infrastructure, same "never big-bang" discipline as every
other Tier 5 Runtime module -- not wired into `simulation/engine.py`/
`server.py`'s real `/diagnostics` endpoint yet.

`profiling.py`'s own docstring already explains why this was deferred:
"there's no real engine subsystem running through `Scheduler` yet to
expose." That structural blocker is still true -- nothing in this
pass gives `Scheduler` a real subsystem to run. What this module DOES
close is the mechanical half: a real function that turns a `Scheduler`
instance's already-real B5.1/B2.1/B2.3/B5.4 data (`TaskMetrics`,
`SubsystemBudget`, `TickTrace`) into the exact JSON-shaped payload a
`/diagnostics/runtime` route would return, and a matching plain-text
formatter for the dev console -- verified against a REAL `Scheduler`
running real (if synthetic) tasks through real ticks, not asserted
against a mocked shape. Once a real subsystem is migrated onto
`Scheduler` (B0.3/B1.4's own still-open migration), wiring this
report into an actual HTTP route and dev-console panel is a small,
mechanical follow-up -- this pass ships the report-building logic
itself, the part that's genuinely reusable regardless of when that
migration happens.
"""
from __future__ import annotations


def runtime_diagnostics_report(scheduler) -> dict:
    """The `/diagnostics/runtime` JSON payload shape. Reads ONLY
    already-real `Scheduler` state (`all_metrics()`, its own internal
    per-subsystem budgets via `budget_for`, `tick_traces`) -- never
    invents a number, never estimates. `task_id` is threaded through
    from `TaskMetrics` itself, so the report never has to guess a
    task's subsystem membership from string parsing."""
    tasks = []
    for task_id, metrics in sorted(scheduler.all_metrics().items()):
        tasks.append({
            "task_id": task_id,
            "call_count": metrics.call_count,
            "error_count": metrics.error_count,
            "skipped_clean_count": metrics.skipped_clean_count,
            "deferred_count": metrics.deferred_count,
            "promoted_count": metrics.promoted_count,
            "ran_via_spare_capacity_count": metrics.ran_via_spare_capacity_count,
            "total_wall_seconds": metrics.total_wall_seconds,
            "mean_wall_seconds": metrics.mean_wall_seconds(),
            "idle_ratio": metrics.idle_ratio(),
        })

    subsystems = []
    for subsystem, budget in sorted(scheduler.all_budgets().items()):
        subsystems.append({
            "subsystem": subsystem,
            "seconds_per_tick": budget.seconds_per_tick,
            "consumed_this_tick": budget.consumed_this_tick,
            "debt_seconds": budget.debt_seconds,
        })

    latest_trace = scheduler.tick_traces[-1] if scheduler.tick_traces else None
    latest_tick = None
    if latest_trace is not None:
        latest_tick = {
            "tick": latest_trace.tick,
            "entries": [
                {
                    "task_id": e.task_id,
                    "subsystem": e.subsystem,
                    "trigger": e.trigger,
                    "outcome": e.outcome,
                    "reason": e.reason,
                    "cost_seconds": e.cost_seconds,
                    "promoted": e.promoted,
                    "ran_via_spare_capacity": e.ran_via_spare_capacity,
                }
                for e in latest_trace.entries
            ],
        }

    return {
        "tick_traces_available": len(scheduler.tick_traces),
        "tasks": tasks,
        "subsystems": subsystems,
        "latest_tick": latest_tick,
    }


def explain_tick(scheduler, tick: int) -> dict | None:
    """B5.4's own "explain this tick," exposed as a real lookup rather
    than requiring a caller to linearly scan `scheduler.tick_traces`
    itself. Returns `None` for a tick that has aged out of the bounded
    ring buffer or never happened -- an honest "no longer known," never
    a fabricated trace."""
    for trace in scheduler.tick_traces:
        if trace.tick == tick:
            return {
                "tick": trace.tick,
                "entries": [
                    {
                        "task_id": e.task_id,
                        "subsystem": e.subsystem,
                        "trigger": e.trigger,
                        "outcome": e.outcome,
                        "reason": e.reason,
                        "cost_seconds": e.cost_seconds,
                        "promoted": e.promoted,
                        "ran_via_spare_capacity": e.ran_via_spare_capacity,
                    }
                    for e in trace.entries
                ],
            }
    return None


def format_runtime_diagnostics_text(scheduler) -> str:
    """The dev-console plain-text counterpart to `runtime_diagnostics_
    report` -- same data, formatted for a human eyeballing the console
    rather than a JSON consumer. No new data source; a pure
    presentation layer over the same report."""
    report = runtime_diagnostics_report(scheduler)
    lines = ["Runtime diagnostics", "===================", ""]

    lines.append(f"Subsystems ({len(report['subsystems'])}):")
    for s in report["subsystems"]:
        lines.append(
            f"  {s['subsystem']}: {s['consumed_this_tick']:.6f}s / {s['seconds_per_tick']:.6f}s"
            f" this tick, debt={s['debt_seconds']:.6f}s"
        )
    lines.append("")

    lines.append(f"Tasks ({len(report['tasks'])}):")
    for t in report["tasks"]:
        lines.append(
            f"  {t['task_id']}: calls={t['call_count']} errors={t['error_count']} "
            f"skipped_clean={t['skipped_clean_count']} deferred={t['deferred_count']} "
            f"promoted={t['promoted_count']} idle_ratio={t['idle_ratio']:.3f} "
            f"mean_wall={t['mean_wall_seconds']:.6f}s"
        )
    lines.append("")

    if report["latest_tick"] is not None:
        lt = report["latest_tick"]
        lines.append(f"Latest tick trace (tick={lt['tick']}):")
        for e in lt["entries"]:
            promoted = " [PROMOTED]" if e["promoted"] else ""
            spare = " [SPARE-CAPACITY]" if e["ran_via_spare_capacity"] else ""
            lines.append(f"  {e['task_id']} ({e['subsystem']}): {e['outcome']}{promoted}{spare} -- {e['reason']}")
    else:
        lines.append("Latest tick trace: none recorded yet.")

    return "\n".join(lines)
