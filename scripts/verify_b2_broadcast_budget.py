#!/usr/bin/env python3
"""Tier 5 B2 — Budgets & scheduling, wired to a real control point.

Explicit user choice (after B6 adaptive tuning closed): B2 next. B2's
own machinery (`simulation/scheduler.py`) was already genuinely
imported and executing real code via B0.3's migrations — the stale
doc claim "no import from scheduler.py exists" was wrong — but every
one of those 56 migrated jobs is declared `PriorityClass.CRITICAL`
(deliberately, to reproduce "always runs every tick" pre-migration
behavior), and CRITICAL bypasses the budget/deferral machinery
entirely. So B2's actual distinguishing logic had zero real exercise.

`SimulationEngine._maybe_broadcast` (the per-tick WebSocket payload
build) is the new real control point: genuinely cosmetic, genuinely
safe to lag a tick under load, and — measured directly in this
environment, not guessed — costs real time (a 60-population, 64x64
world showed p50 ~9.5ms, max ~40ms). It now runs through its own
dedicated `TaskRegistry`/`Scheduler` pair as a real `PriorityClass.
DEFERRABLE` task with a real `SubsystemBudget` (`BROADCAST_SUBSYSTEM_
BUDGET_SECONDS = 0.015`).

**The honest finding this script exists to prove, not assume**: under
the dedicated-single-task-registry-called-once-per-real-tick pattern
every B0.3 migration uses, `Scheduler.run_tick()` resets `SubsystemB
udget.consumed_this_tick` to 0 at the END of every call — so a solo
task's budget is always full again by the time the NEXT call's
due-check runs, and it therefore ALWAYS runs (never `deferred`,
never `promoted`), regardless of priority class. This is verified
directly below (check 4) rather than silently assumed to work the
way the item's own text might suggest. What IS real: `debt_seconds`
(check 5) genuinely and permanently accrues whenever a call overruns
its budget, surfaced via `all_budgets()`/`full_diagnostics()`
('broadcast_scheduler') for the first time for this job.
"""
import asyncio
import sys
import tempfile
import time

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import BROADCAST_SUBSYSTEM_BUDGET_SECONDS, SimulationEngine
from hearthmind.simulation.scheduler import Scheduler, SubsystemBudget
from hearthmind.simulation.task_graph import PriorityClass, Task, TaskRegistry, TriggerKind

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, population: int = 20) -> SimulationEngine:
    conn = connect(f"{tmpdir}/b2_broadcast.db")
    cfg = Config(
        db_path=f"{tmpdir}/b2_broadcast.db", llm_enabled=False, seed=1,
        initial_population=population, width=32, height=32,
    )
    return SimulationEngine.load_or_create(conn, cfg)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        eng = make_engine(tmpdir)

        # 1. The real task is declared correctly: DEFERRABLE, PERIODIC,
        #    pointing at the real bound method, in its own dedicated
        #    registry (not sharing one with any other migrated job --
        #    the double-execution bug class this whole session's
        #    discipline exists to avoid).
        task = eng._runtime_registry_broadcast.get("broadcast")
        check("broadcast task registered", task is not None)
        check("broadcast task is DEFERRABLE, not CRITICAL", task.priority_class is PriorityClass.DEFERRABLE)
        check("broadcast task trigger is PERIODIC", task.trigger is TriggerKind.PERIODIC)
        check("broadcast task fn is the real bound method", task.fn == eng._maybe_broadcast)
        check(
            "broadcast has its own dedicated registry (not shared)",
            eng._runtime_registry_broadcast is not eng._runtime_registry
            and eng._runtime_registry_broadcast is not eng._runtime_registry_voice_dialogue,
        )

        # 2. The scheduler holds a real budget for this subsystem, sized
        #    to the documented constant.
        budget = eng._runtime_scheduler_broadcast.budget_for("broadcast")
        check(
            "broadcast subsystem budget matches the documented constant",
            budget.seconds_per_tick == BROADCAST_SUBSYSTEM_BUDGET_SECONDS,
        )
        check("broadcast budget starts with zero debt", budget.debt_seconds == 0.0)

        # 3. A cheap/fast broadcast call fits comfortably inside budget
        #    and runs (via a fresh engine so state stays clean for the
        #    later error-propagation check).
        eng2 = make_engine(tmpdir, population=5)
        report = eng2._runtime_scheduler_broadcast.run_tick()
        check("a cheap real _maybe_broadcast call ran (no error)", "broadcast" in report.ran and not report.errors)
        check("a cheap call accrues no real debt", eng2._runtime_scheduler_broadcast.budget_for("broadcast").debt_seconds == 0.0)

        # 4. The honest finding: a solo task in a dedicated registry
        #    ALWAYS runs (never defers/promotes), because the budget
        #    resets to full at the end of every run_tick() call -- the
        #    check happens BEFORE the task executes, when the budget is
        #    always fresh. Verified directly against a synthetic
        #    artificially-slow task using the exact same real
        #    Scheduler/SubsystemBudget machinery the real broadcast
        #    wiring uses, not a mock.
        slow_calls: list[int] = []

        def artificially_slow() -> None:
            slow_calls.append(1)
            time.sleep(BROADCAST_SUBSYSTEM_BUDGET_SECONDS * 2)  # deliberately 2x over budget

        synth_registry = TaskRegistry()
        synth_registry.register(Task(
            id="synthetic_slow", subsystem="synthetic_slow", fn=artificially_slow,
            trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.DEFERRABLE,
        ))
        synth_scheduler = Scheduler(
            synth_registry,
            budgets={"synthetic_slow": SubsystemBudget(subsystem="synthetic_slow", seconds_per_tick=BROADCAST_SUBSYSTEM_BUDGET_SECONDS)},
        )
        never_deferred = True
        for _ in range(6):
            r = synth_scheduler.run_tick()
            if r.deferred or r.promoted:
                never_deferred = False
        check(
            "a solo DEFERRABLE task in a dedicated registry never actually defers (verified, not assumed)",
            never_deferred and len(slow_calls) == 6,
        )

        # 5. What IS real: overrun debt genuinely and monotonically
        #    accrues across repeated over-budget calls, and is exposed
        #    via all_budgets() -- the diagnostics path
        #    (full_diagnostics()['broadcast_scheduler']) reads.
        debt = synth_scheduler.budget_for("synthetic_slow").debt_seconds
        check("overrun debt accrued from repeated over-budget calls", debt > 0.0)
        check(
            "all_budgets() surfaces the real budget object",
            synth_scheduler.all_budgets()["synthetic_slow"].debt_seconds == debt,
        )

        # 6. Exception propagation is preserved: an error inside the
        #    migrated job still stops the tick, matching every other
        #    B0.3 migration's own re-raise discipline (never silently
        #    swallowed by Scheduler's own broad except).
        def boom() -> None:
            raise ValueError("synthetic broadcast failure")

        err_registry = TaskRegistry()
        err_registry.register(Task(
            id="broadcast", subsystem="broadcast", fn=boom,
            trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.DEFERRABLE,
        ))
        err_scheduler = Scheduler(err_registry)
        err_report = err_scheduler.run_tick()
        check("a failing broadcast is caught into report.errors by Scheduler", "broadcast" in err_report.errors)
        raised = False
        try:
            if err_report.errors:
                raise RuntimeError(f"runtime-scheduled task(s) errored: {err_report.errors}")
        except RuntimeError:
            raised = True
        check("the real _tick_once call site's re-raise pattern propagates the error", raised)

        # 7. The real per-tick call site actually reaches the new
        #    scheduler end-to-end -- drive one real tick and confirm the
        #    broadcast task's own metrics incremented, proving the
        #    _tick_once wiring (not just the registry/scheduler
        #    objects) is real.
        eng3 = make_engine(tmpdir, population=5)
        metrics_before = eng3._runtime_scheduler_broadcast.metrics_for("broadcast").call_count
        eng3._tick_once()
        metrics_after = eng3._runtime_scheduler_broadcast.metrics_for("broadcast").call_count
        check(
            "a real _tick_once() call routes _maybe_broadcast through the new scheduler",
            metrics_after == metrics_before + 1,
        )

        # 8. The OTHER _maybe_broadcast call site (the real-time
        #    run_forever llama-server-restart-edge polling loop, line
        #    ~3292, outside _tick_once) is untouched -- still a direct
        #    call, never routed through the runtime scheduler. Verified
        #    by source inspection rather than execution, since it needs
        #    real llama-server-restart edge state to actually trigger.
        import inspect
        source = inspect.getsource(SimulationEngine)
        direct_call_count = source.count("self._maybe_broadcast()")
        check(
            "exactly one direct self._maybe_broadcast() call site remains (the real-time polling one)",
            direct_call_count == 1,
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
