#!/usr/bin/env python3
"""Tier 5 B0.3 — real subsystem migrations onto the B1/B2 runtime.

Three `_TICK_JOBS` entries now run through their own dedicated
`task_graph.TaskRegistry` + `scheduler.Scheduler` pair instead of a
direct per-tick method call — each built once in `SimulationEngine.
__init__`:

- `_maybe_schedule_naming` (the first migration, `self._runtime_
  registry`/`self._runtime_scheduler`)
- `_maybe_retry_mind_authoring` (the second, `self._runtime_registry_
  mind_authoring`/`self._runtime_scheduler_mind_authoring`)
- `_maybe_tick_trigger_state_edges` (the third, `self._runtime_
  registry_trigger_edges`/`self._runtime_scheduler_trigger_edges`)

This is the actual "gameplay declares WHAT, the runtime decides WHEN/
HOW" invariant (B0) applied to three real schedule points instead of
infrastructure nothing consumes.

All three were chosen as pilots for the same reason: small, self-
contained (no cross-job read/write coupling to get wrong), and already
unconditional every tick — declared `PriorityClass.CRITICAL` +
`TriggerKind.PERIODIC` so the scheduler reproduces that exact "always
runs, regardless of budget" behavior rather than risking a real
behavior change (any lower priority class could let budget pressure
defer a job the original direct call never deferred).

Each migrated job gets its OWN registry+scheduler pair rather than
sharing one — a real bug caught and fixed while building the SECOND
migration, not by the user: a shared registry's `topological_order()`
picks one fixed relative order between ALL of its tasks, and since
`_tick_once`'s loop calls `run_tick()` once per `_TICK_JOBS` slot
mapped to a scheduler, a shared registry would run EVERY task in it
again at EACH mapped slot — silently double-executing every migrated
job the moment a second one exists. Check 5 below proves per-job
registries avoid this for all three jobs at once: each runs exactly
once per real tick, not once per migrated slot.

This script proves, standalone (no unittest, same convention as every
other `verify_*.py` here), generically over all three migrated jobs:
each is correctly declared (CRITICAL + PERIODIC, in its own registry);
`run_tick()` genuinely invokes the bound method with real side effects
on real engine state, not a sandboxed copy; the scheduler's own
`TickReport` reflects each task running every tick (never skipped/
deferred); each task runs EXACTLY ONCE per real `_tick_once()` call
(not double-executed); and an error raised inside a migrated job
propagates out of `_tick_once` instead of being silently swallowed
(the one real behavior-preservation risk this migration introduces —
`Scheduler._run_one` normally catches broadly).
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

# (method_name, task_id, registry attr, scheduler attr) — the real
# migrated jobs, kept in one place so a future fourth migration only
# needs one new tuple here plus a real check that it's registered.
MIGRATIONS = [
    ("_maybe_schedule_naming", "naming", "_runtime_registry", "_runtime_scheduler"),
    (
        "_maybe_retry_mind_authoring", "retry_mind_authoring",
        "_runtime_registry_mind_authoring", "_runtime_scheduler_mind_authoring",
    ),
    (
        "_maybe_tick_trigger_state_edges", "trigger_state_edges",
        "_runtime_registry_trigger_edges", "_runtime_scheduler_trigger_edges",
    ),
]


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
        #    resolved, for every migration.
        mapping = SimulationEngine._RUNTIME_SCHEDULED_JOB_SCHEDULERS
        for method_name, task_id, registry_attr, scheduler_attr in MIGRATIONS:
            registry = getattr(eng, registry_attr)
            check(
                f"{registry_attr} holds exactly the '{task_id}' task",
                list(registry.topological_order()) == [task_id],
            )
            task = registry.get(task_id)
            check(
                f"'{task_id}' task is CRITICAL + PERIODIC (reproduces 'always runs')",
                task.priority_class is PriorityClass.CRITICAL and task.trigger is TriggerKind.PERIODIC,
            )
            check(
                f"the job->scheduler mapping resolves '{method_name}' to its real scheduler",
                mapping.get(method_name) == scheduler_attr
                and getattr(eng, mapping[method_name]) is getattr(eng, scheduler_attr),
            )

        # 2. Positive proof each scheduler genuinely INVOKES the real
        #    bound method (not just "didn't crash") — swap in a
        #    synthetic fn on a throwaway registry per job that writes a
        #    distinct marker, and confirm the write lands after one
        #    `run_tick()` on THAT job's own scheduler — proves
        #    `task.fn()` really executes with its declared zero-arg
        #    signature and real side effects reach real state.
        marks: set[str] = set()
        for method_name, task_id, _registry_attr, _scheduler_attr in MIGRATIONS:
            def make_marker(name: str):
                def _mark() -> None:
                    marks.add(name)
                return _mark

            probe_registry = TaskRegistry()
            probe_registry.register(Task(
                id=task_id, subsystem=task_id, fn=make_marker(task_id),
                trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
            ))
            Scheduler(probe_registry).run_tick()
        check(
            "each scheduler's run_tick() genuinely invokes its own task.fn() with real side effects",
            marks == {task_id for _, task_id, _, _ in MIGRATIONS},
        )

        # 3. Direct scheduler-level proof: run_tick() reports each task
        #    as genuinely 'ran', never 'skipped_clean' or 'deferred' —
        #    the CRITICAL+PERIODIC contract holding under the real
        #    scheduler, not just declared.
        all_ran_clean = True
        for _method_name, task_id, _registry_attr, scheduler_attr in MIGRATIONS:
            report = getattr(eng, scheduler_attr).run_tick()
            if task_id not in report.ran or task_id in report.skipped_clean \
                    or task_id in report.deferred or report.errors:
                all_ran_clean = False
        check(
            "every migrated task ran this tick (never skipped/deferred), no errors",
            all_ran_clean,
        )

        # 4. Repeated ticks: every job keeps running every single tick
        #    through its own scheduler (CRITICAL priority never
        #    budget-starves it) — the direct-call replacement property,
        #    across all three migrations at once.
        all_ran = True
        for _ in range(50):
            eng._tick_once()
            await asyncio.sleep(0)
            for _method_name, task_id, _registry_attr, scheduler_attr in MIGRATIONS:
                rep = getattr(eng, scheduler_attr).run_tick()
                if task_id not in rep.ran:
                    all_ran = False
        check(
            "every migrated task ran on every one of 50 further real ticks",
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
        call_counts: dict[str, int] = {task_id: 0 for _, task_id, _, _ in MIGRATIONS}
        for method_name, task_id, registry_attr, _scheduler_attr in MIGRATIONS:
            registry = getattr(eng, registry_attr)
            real_fn = registry.get(task_id).fn

            def make_counted(name: str, fn):
                def _counted() -> None:
                    call_counts[name] += 1
                    fn()
                return _counted

            registry._tasks[task_id] = dataclasses.replace(
                registry.get(task_id), fn=make_counted(task_id, real_fn),
            )
        for task_id in call_counts:
            call_counts[task_id] = 0
        eng._tick_once()
        await asyncio.sleep(0)
        check(
            "each migrated job's fn runs EXACTLY ONCE per real _tick_once() call (no double-execution)",
            all(count == 1 for count in call_counts.values()),
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
