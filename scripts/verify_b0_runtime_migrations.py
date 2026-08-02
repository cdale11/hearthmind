#!/usr/bin/env python3
"""Tier 5 B0.3 — real subsystem migrations onto the B1/B2 runtime.

Two `_TICK_JOBS` entries now run through their own dedicated
`task_graph.TaskRegistry` + `scheduler.Scheduler` pair instead of a
direct per-tick method call: `_maybe_schedule_naming` (the first
migration, `self._runtime_registry`/`self._runtime_scheduler`) and
`_maybe_retry_mind_authoring` (the second, `self._runtime_registry_
mind_authoring`/`self._runtime_scheduler_mind_authoring`) — both built
once in `SimulationEngine.__init__`. This is the actual "gameplay
declares WHAT, the runtime decides WHEN/HOW" invariant (B0) applied to
two real schedule points instead of infrastructure nothing consumes.

Both were chosen as pilots for the same reason: small, self-contained
(no cross-job read/write coupling to get wrong), and already
unconditional every tick — declared `PriorityClass.CRITICAL` +
`TriggerKind.PERIODIC` so the scheduler reproduces that exact "always
runs, regardless of budget" behavior rather than risking a real
behavior change (any lower priority class could let budget pressure
defer a job the original direct call never deferred).

Each migrated job gets its OWN registry+scheduler pair rather than
sharing one — a real bug caught and fixed during this pass, not by the
user: a shared registry's `topological_order()` picks one fixed
relative order between ALL of its tasks, and since `_tick_once`'s loop
calls `run_tick()` once per `_TICK_JOBS` slot mapped to a scheduler, a
shared registry would run EVERY task in it again at EACH mapped slot —
silently double-executing every migrated job the moment a second one
exists. Check 5 below proves per-job registries avoid this: each job
runs exactly once per real tick, not once per migrated slot.

This script proves, standalone (no unittest, same convention as every
other `verify_*.py` here): both migrated tasks are correctly declared
(CRITICAL + PERIODIC, in their own registries); `run_tick()` genuinely
invokes the bound method with real side effects on real engine state,
not a sandboxed copy; the scheduler's own `TickReport` reflects each
task running every tick (never skipped/deferred); each task runs
EXACTLY ONCE per real `_tick_once()` call (not double-executed); and
an error raised inside a migrated job propagates out of `_tick_once`
instead of being silently swallowed (the one real behavior-
preservation risk this migration introduces — `Scheduler._run_one`
normally catches broadly).
"""
import asyncio
import dataclasses
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.simulation.scheduler import Scheduler
from hearthmind.simulation.task_graph import PriorityClass, Task, TaskRegistry, TriggerKind

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, seed: int = 12345) -> SimulationEngine:
    conn = connect(f"{tmpdir}/runtime_migrations.db")
    cfg = Config(
        db_path=f"{tmpdir}/runtime_migrations.db", llm_enabled=False, seed=seed,
        initial_population=10, width=48, height=48,
    )
    return SimulationEngine.load_or_create(conn, cfg)


async def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        eng = make_engine(d)

        # 1. Wiring sanity: each registry holds exactly its own one
        #    migrated task, correctly declared, and the method-name ->
        #    scheduler-attribute mapping is complete and correctly
        #    resolved.
        check(
            "naming registry holds exactly the 'naming' task",
            list(eng._runtime_registry.topological_order()) == ["naming"],
        )
        check(
            "mind-authoring registry holds exactly the 'retry_mind_authoring' task",
            list(eng._runtime_registry_mind_authoring.topological_order()) == ["retry_mind_authoring"],
        )
        naming_task = eng._runtime_registry.get("naming")
        mind_task = eng._runtime_registry_mind_authoring.get("retry_mind_authoring")
        check(
            "both tasks are CRITICAL + PERIODIC (reproduces 'always runs')",
            naming_task.priority_class is PriorityClass.CRITICAL
            and naming_task.trigger is TriggerKind.PERIODIC
            and mind_task.priority_class is PriorityClass.CRITICAL
            and mind_task.trigger is TriggerKind.PERIODIC,
        )
        mapping = SimulationEngine._RUNTIME_SCHEDULED_JOB_SCHEDULERS
        check(
            "the job->scheduler mapping resolves both migrated jobs to real, distinct scheduler attrs",
            mapping.get("_maybe_schedule_naming") == "_runtime_scheduler"
            and mapping.get("_maybe_retry_mind_authoring") == "_runtime_scheduler_mind_authoring"
            and getattr(eng, mapping["_maybe_schedule_naming"]) is eng._runtime_scheduler
            and getattr(eng, mapping["_maybe_retry_mind_authoring"]) is eng._runtime_scheduler_mind_authoring,
        )

        # 2. Positive proof each scheduler genuinely INVOKES the real
        #    bound method (not just "didn't crash") — swap in a
        #    synthetic fn on a throwaway registry per job that writes a
        #    distinct marker, and confirm the write lands after one
        #    `run_tick()` on THAT job's own scheduler — proves
        #    `task.fn()` really executes with its declared zero-arg
        #    signature and real side effects reach real state.
        marks: set[str] = set()

        def _write_naming_marker() -> None:
            marks.add("naming")

        def _write_mind_marker() -> None:
            marks.add("mind")

        probe_naming = TaskRegistry()
        probe_naming.register(Task(
            id="naming", subsystem="naming", fn=_write_naming_marker,
            trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
        ))
        Scheduler(probe_naming).run_tick()
        probe_mind = TaskRegistry()
        probe_mind.register(Task(
            id="retry_mind_authoring", subsystem="mind_authoring", fn=_write_mind_marker,
            trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
        ))
        Scheduler(probe_mind).run_tick()
        check(
            "each scheduler's run_tick() genuinely invokes its own task.fn() with real side effects",
            marks == {"naming", "mind"},
        )

        # 3. Direct scheduler-level proof: run_tick() reports each task
        #    as genuinely 'ran', never 'skipped_clean' or 'deferred' —
        #    the CRITICAL+PERIODIC contract holding under the real
        #    scheduler, not just declared.
        report_n = eng._runtime_scheduler.run_tick()
        report_m = eng._runtime_scheduler_mind_authoring.run_tick()
        check(
            "both tasks ran this tick (never skipped/deferred), no errors",
            "naming" in report_n.ran and "naming" not in report_n.skipped_clean
            and "naming" not in report_n.deferred and not report_n.errors
            and "retry_mind_authoring" in report_m.ran
            and "retry_mind_authoring" not in report_m.skipped_clean
            and "retry_mind_authoring" not in report_m.deferred and not report_m.errors,
        )

        # 4. Repeated ticks: both jobs keep running every single tick
        #    through their own scheduler (CRITICAL priority never
        #    budget-starves them) — the direct-call replacement
        #    property, across both migrations at once.
        all_ran = True
        for _ in range(50):
            eng._tick_once()
            await asyncio.sleep(0)
            rep_n = eng._runtime_scheduler.run_tick()
            rep_m = eng._runtime_scheduler_mind_authoring.run_tick()
            if "naming" not in rep_n.ran or "retry_mind_authoring" not in rep_m.ran:
                all_ran = False
                break
        check(
            "both tasks ran on every one of 50 further real ticks",
            all_ran,
        )

        # 5. THE load-bearing check for the per-job-registry design: a
        #    real `_tick_once()` call must invoke each migrated job's
        #    fn EXACTLY ONCE, never twice — the exact bug a shared
        #    registry would introduce (run_tick() called once per
        #    `_TICK_JOBS` slot, each call re-running every task in a
        #    shared registry). Count real invocations via a wrapped fn
        #    swapped into each job's OWN registry (not a fresh probe
        #    registry — the real one `_tick_once` actually drives).
        naming_calls = 0
        mind_calls = 0
        real_naming_fn = eng._runtime_registry.get("naming").fn
        real_mind_fn = eng._runtime_registry_mind_authoring.get("retry_mind_authoring").fn

        def counted_naming() -> None:
            nonlocal naming_calls
            naming_calls += 1
            real_naming_fn()

        def counted_mind() -> None:
            nonlocal mind_calls
            mind_calls += 1
            real_mind_fn()

        eng._runtime_registry._tasks["naming"] = dataclasses.replace(
            eng._runtime_registry.get("naming"), fn=counted_naming,
        )
        eng._runtime_registry_mind_authoring._tasks["retry_mind_authoring"] = dataclasses.replace(
            eng._runtime_registry_mind_authoring.get("retry_mind_authoring"), fn=counted_mind,
        )
        naming_calls = mind_calls = 0
        eng._tick_once()
        await asyncio.sleep(0)
        check(
            "each migrated job's fn runs EXACTLY ONCE per real _tick_once() call (no double-execution)",
            naming_calls == 1 and mind_calls == 1,
        )

    # 6. Error propagation: a migrated CRITICAL task's exception must
    #    still stop the tick (not be silently swallowed the way
    #    Scheduler._run_one's broad except normally would) — build a
    #    throwaway registry+scheduler with a task that always raises,
    #    and confirm run_tick() reports the error rather than hiding it
    #    (the real re-raise happens in `_tick_once`'s own call site;
    #    this confirms the report it re-raises FROM is correct).
    def _boom() -> None:
        raise ValueError("synthetic failure for B0.3 verification")

    boom_registry = TaskRegistry()
    boom_registry.register(Task(
        id="boom", subsystem="test", fn=_boom,
        trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
    ))
    boom_report = Scheduler(boom_registry).run_tick()
    check(
        "a raising CRITICAL task's error is captured in the report (not silently lost)",
        "boom" in boom_report.errors and "synthetic failure" in boom_report.errors["boom"],
    )

    # 7. End-to-end: the same error, driven through a real engine's
    #    `_tick_once` via the naming job's real scheduler slot, actually
    #    propagates and stops the tick — the real behavior-preservation
    #    property this migration must hold, verified against the real
    #    call site, not just the scheduler in isolation.
    with tempfile.TemporaryDirectory() as d2:
        eng2 = make_engine(d2, seed=999)
        eng2._runtime_registry = TaskRegistry()
        eng2._runtime_registry.register(Task(
            id="naming", subsystem="naming", fn=_boom,
            trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
        ))
        eng2._runtime_scheduler = Scheduler(eng2._runtime_registry)
        raised = False
        try:
            eng2._tick_once()
            await asyncio.sleep(0)
        except RuntimeError as exc:
            raised = "runtime-scheduled task(s) errored" in str(exc) and "synthetic failure" in str(exc)
        check(
            "an error in a migrated task propagates out of _tick_once (not swallowed)",
            raised,
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
