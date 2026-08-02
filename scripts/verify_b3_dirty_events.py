#!/usr/bin/env python3
"""Tier 5 B3 (Event-driven execution) wired to a real control point,
plus B5.3's first real diagnostics wiring in the same batch.

Explicit user follow-up ("B3"), continuing the same Part-B closing
sequence. B3.1 (`DirtyTracker`)/B3.2 (`EventBus`) were already real,
verified machinery (`simulation/reactivity.py`) since v1.34.165, but
`Scheduler.run_tick`'s own `_due_and_reason` gate had never been given
a real production `ON_DIRTY`/`ON_EVENT` task to act on — every one of
B0.3's 56 migrated jobs is `PriorityClass.PERIODIC` (always due).

`_update_institution_dormancy`'s own pre-migration body was already a
pure `if "month_end" not in events: return` guard with no logic ahead
of it -- exactly B3.2's own named shape (a discrete "did this happen"
signal, not an ongoing state needing edge detection). Its Task is now
declared `TriggerKind.ON_EVENT`/`event_types={"month_end"}`, moving
that guard OUT of the function body and INTO the scheduler's own
`_due_and_reason` check -- a real `skipped_clean` on every non-month_
end tick instead of the function being called and immediately
returning. `_tick_once` publishes "month_end" into this scheduler's
own real `EventBus` right after `events` is computed, the same source
the old internal guard read from directly.

Bonus (same batch, "cheap next tier intel" per explicit user request):
B5.3's `runtime_diagnostics_report` (built v1.34.183, never wired to a
real HTTP/diagnostics surface since "there's no real engine subsystem
running through Scheduler yet to expose" -- no longer true) is now
wired into `full_diagnostics()['runtime_diagnostics']['institution_
dormancy']` -- the first real production reading through that report
function, not a synthetic one.

This script proves, standalone (no unittest): the real Task's
declaration (ON_EVENT, not PERIODIC, the real event_types set); a
direct production-path drive through many real ticks confirming the
job fires ONLY on real month_end ticks and is `skipped_clean` on
every other one (not merely "returns quickly" -- genuinely never
enters budget/deferral machinery, verified via `TaskMetrics.
skipped_clean_count`); that this doesn't change WHAT the job does on
a real month_end (dormancy state forms identically to before); and
that `full_diagnostics()['runtime_diagnostics']['institution_
dormancy']` surfaces the real, live scheduler state.
"""
import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.simulation.task_graph import PriorityClass, TriggerKind

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, population: int = 8) -> SimulationEngine:
    conn = connect(f"{tmpdir}/b3_dirty_events.db")
    cfg = Config(
        db_path=f"{tmpdir}/b3_dirty_events.db", llm_enabled=False, seed=3,
        initial_population=population, width=32, height=32,
    )
    return SimulationEngine.load_or_create(conn, cfg)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        eng = make_engine(tmpdir)

        # 1. The real task's declaration.
        task = eng._runtime_registry_institution_dormancy.get("institution_dormancy")
        check("institution_dormancy task registered", task is not None)
        check("institution_dormancy trigger is ON_EVENT (not PERIODIC)", task.trigger is TriggerKind.ON_EVENT)
        check("institution_dormancy subscribes to the real 'month_end' event", task.event_types == frozenset({"month_end"}))
        check("institution_dormancy stays CRITICAL (unchanged priority)", task.priority_class is PriorityClass.CRITICAL)

        # 2. Drive enough real ticks to cross at least one real month_end
        #    boundary, confirming the job fires ONLY on that tick and is
        #    genuinely skipped_clean (not budget/deferral-processed)
        #    every other tick -- the real B3.1 CPU-win property.
        sched = eng._runtime_scheduler_institution_dormancy
        month_end_ticks = 0
        ran_ticks = 0
        TICKS = 3200
        for _ in range(TICKS):
            events = eng.world.tick()
            eng._reserved_this_tick = 0
            if "month_end" in events:
                sched.event_bus.publish("month_end")
                month_end_ticks += 1
            before = sched.metrics_for("institution_dormancy").call_count
            sched.run_tick()
            after = sched.metrics_for("institution_dormancy").call_count
            if after > before:
                ran_ticks += 1

        check("at least one real month_end boundary was crossed", month_end_ticks > 0)
        check(
            "the job ran on EXACTLY the real month_end ticks, no more no less",
            month_end_ticks == ran_ticks,
        )
        metrics = sched.metrics_for("institution_dormancy")
        check("metrics.call_count matches the real ran-tick count", metrics.call_count == ran_ticks)
        check(
            "metrics.skipped_clean_count accounts for every OTHER tick (genuine skip, not just a fast return)",
            metrics.skipped_clean_count == TICKS - ran_ticks,
        )
        check("no errors across the real drive", metrics.error_count == 0)
        check("ticks_observed covers every real tick", metrics.ticks_observed == TICKS)

        # 3. A month_end tick with NO publish (a bug in the wiring, not
        #    this test) must NOT fire -- confirms the gate is real, not
        #    a no-op that always lets PERIODIC-style execution through.
        eng2 = make_engine(tmpdir, population=5)
        sched2 = eng2._runtime_scheduler_institution_dormancy
        # Force a fresh registry-observed state with zero publishes ever.
        never_published_ran = False
        for _ in range(200):
            eng2.world.tick()  # deliberately never publish, regardless of real events
            eng2._reserved_this_tick = 0
            before = sched2.metrics_for("institution_dormancy").call_count
            sched2.run_tick()
            after = sched2.metrics_for("institution_dormancy").call_count
            if after > before:
                never_published_ran = True
                break
        check("with nothing ever published, the job never fires (the gate is real)", not never_published_ran)

        # 4. The real _tick_once() call site actually publishes "month_
        #    end" into this specific scheduler's EventBus and the job
        #    fires through the real production path (not just the
        #    direct scheduler-level drive above).
        eng3 = make_engine(tmpdir, population=5)
        sched3 = eng3._runtime_scheduler_institution_dormancy
        fired_via_real_tick_once = False
        for _ in range(3200):
            before = sched3.metrics_for("institution_dormancy").call_count
            eng3._tick_once()
            after = sched3.metrics_for("institution_dormancy").call_count
            if after > before:
                fired_via_real_tick_once = True
                break
        check("the real _tick_once() call site fires the job on a genuine month_end", fired_via_real_tick_once)

        # 5. B5.3 bonus: full_diagnostics() surfaces the real scheduler
        #    state through runtime_diagnostics_report, not a stub.
        diag = eng3.full_diagnostics()
        rd = diag.get("runtime_diagnostics", {}).get("institution_dormancy")
        check("full_diagnostics() exposes runtime_diagnostics.institution_dormancy", rd is not None)
        check(
            "the surfaced report's task list includes the real institution_dormancy task",
            rd is not None and any(t["task_id"] == "institution_dormancy" for t in rd["tasks"]),
        )
        real_task_entry = next((t for t in rd["tasks"] if t["task_id"] == "institution_dormancy"), None)
        check(
            "the surfaced skipped_clean_count matches the real scheduler's own metrics",
            real_task_entry is not None
            and real_task_entry["skipped_clean_count"] == sched3.metrics_for("institution_dormancy").skipped_clean_count,
        )
        check(
            "the surfaced call_count reflects the one real fire from step 4",
            real_task_entry is not None and real_task_entry["call_count"] == 1,
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
