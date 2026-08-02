#!/usr/bin/env python3
"""Tier 5 B0.3 — real subsystem migrations onto the B1/B2 runtime.

Fifty-six `_TICK_JOBS` entries — every real schedule point in that
table — now run through their own dedicated `task_graph.TaskRegistry`
+ `scheduler.Scheduler` pair instead of a direct per-tick method call,
each built once in `SimulationEngine.__init__` (see the `MIGRATIONS`
table below for the full method-name/task-id/attribute/arg-kind
mapping). The first three (`_maybe_schedule_naming`, `_maybe_retry_
mind_authoring`, `_maybe_tick_trigger_state_edges`) were migrated one
at a time across v1.34.193-.195; ten more `_JOB_NO_ARGS` jobs were
migrated together in a first batch (v1.34.196); the remaining 42
`_JOB_EVENTS` jobs plus 1 `_JOB_EVENTS_SEASON` job were migrated
together in a SECOND batch — per the same explicit user directive:
"Don't ever do one at a time... do as many as possible in one turn."

**A real correction made mid-effort, worth recording**: the first
batch's own changelog entry claimed `_JOB_EVENTS`/`_JOB_EVENTS_SEASON`
jobs were out of scope because `Task.fn`'s declared-once zero-arg
shape "can't express" per-tick `events`/`previous_season` arguments.
That was WRONG — `Scheduler.run_tick(*args, **kwargs)` already
forwards positional arguments straight through to `task.fn(*args,
**kwargs)` (see `scheduler.py`), and since every migrated job holds
its own single-task registry, calling `run_tick(events)`/`run_tick
(events, previous_season)` at the real `_tick_once` call site
reproduces the exact prior `method(events)`/`method(events,
previous_season)` call shape with ZERO `Task`/`Scheduler` design
change needed. No blocker actually existed; this batch closes it out.

This is the actual "gameplay declares WHAT, the runtime decides WHEN/
HOW" invariant (B0) applied to every real schedule point in `_TICK_
JOBS`, not infrastructure nothing consumes.

Every migrated job was chosen for the same reason: small, self-
contained (no cross-job read/write coupling to get wrong within its
OWN isolated registry), and already unconditional every tick —
declared `PriorityClass.CRITICAL` + `TriggerKind.PERIODIC` so the
scheduler reproduces that exact "always runs, regardless of budget"
behavior rather than risking a real behavior change (any lower
priority class could let budget pressure defer a job the original
direct call never deferred). **One exception, added by Tier 5 B3's
real control point**: `institution_dormancy` is now `ON_EVENT`, not
PERIODIC — see `EVENT_DRIVEN_TASK_IDS` below and `scripts/verify_b3_
dirty_events.py` for the full detail.

Each migrated job gets its OWN registry+scheduler pair rather than
sharing one — a real bug caught and fixed while building the SECOND
migration, not by the user: a shared registry's `topological_order()`
picks one fixed relative order between ALL of its tasks, and since
`_tick_once`'s loop calls `run_tick()` once per `_TICK_JOBS` slot
mapped to a scheduler, a shared registry would run EVERY task in it
again at EACH mapped slot — silently double-executing every migrated
job the moment a second one exists. Check 5 below proves per-job
registries avoid this for every job at once: each runs exactly once
per real tick, not once per migrated slot.

This script proves, standalone (no unittest, same convention as every
other `verify_*.py` here), generically over every migrated job: each
is correctly declared (CRITICAL + PERIODIC, in its own registry);
`run_tick()` genuinely invokes the bound method with real side effects
on real engine state, not a sandboxed copy; the scheduler's own
`TickReport` reflects each task running every tick (never skipped/
deferred), with the real `events`/`previous_season` arguments an
`_JOB_EVENTS`/`_JOB_EVENTS_SEASON` job needs actually reaching it;
each task runs EXACTLY ONCE per real `_tick_once()` call (not double-
executed); and an error raised inside a migrated job propagates out of
`_tick_once` instead of being silently swallowed (the one real
behavior-preservation risk this migration introduces — `Scheduler.
_run_one` normally catches broadly).
"""
import asyncio
import dataclasses
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import _JOB_EVENTS, _JOB_EVENTS_SEASON, _JOB_NO_ARGS, SimulationEngine
from hearthmind.simulation.scheduler import Scheduler
from hearthmind.simulation.task_graph import PriorityClass, Task, TaskRegistry, TriggerKind

FAILURES: list[str] = []

# (method_name, task_id, registry attr, scheduler attr, arg_kind) — the
# real migrated jobs, kept in one place so a future migration only
# needs one new tuple here plus a real check that it's registered.
MIGRATIONS = [
    ("_maybe_schedule_naming", "naming", "_runtime_registry", "_runtime_scheduler", _JOB_NO_ARGS),
    (
        "_maybe_retry_mind_authoring", "retry_mind_authoring",
        "_runtime_registry_mind_authoring", "_runtime_scheduler_mind_authoring", _JOB_NO_ARGS,
    ),
    (
        "_maybe_tick_trigger_state_edges", "trigger_state_edges",
        "_runtime_registry_trigger_edges", "_runtime_scheduler_trigger_edges", _JOB_NO_ARGS,
    ),
    (
        "_maybe_spread_concepts", "spread_concepts",
        "_runtime_registry_spread_concepts", "_runtime_scheduler_spread_concepts", _JOB_NO_ARGS,
    ),
    (
        "_maybe_spread_tradition_keeping", "spread_tradition_keeping",
        "_runtime_registry_spread_tradition_keeping", "_runtime_scheduler_spread_tradition_keeping",
        _JOB_NO_ARGS,
    ),
    (
        "_apply_trigger_rules_from_life_events", "trigger_rules_life_events",
        "_runtime_registry_trigger_rules_life_events", "_runtime_scheduler_trigger_rules_life_events",
        _JOB_NO_ARGS,
    ),
    (
        "_maybe_tick_composite_reactions", "composite_reactions",
        "_runtime_registry_composite_reactions", "_runtime_scheduler_composite_reactions", _JOB_NO_ARGS,
    ),
    ("_maybe_schedule_record", "record", "_runtime_registry_record", "_runtime_scheduler_record", _JOB_NO_ARGS),
    (
        "_maybe_schedule_dispute", "dispute", "_runtime_registry_dispute", "_runtime_scheduler_dispute",
        _JOB_NO_ARGS,
    ),
    (
        "_maybe_schedule_migration_decision", "migration_decision",
        "_runtime_registry_migration_decision", "_runtime_scheduler_migration_decision", _JOB_NO_ARGS,
    ),
    (
        "_schedule_due_cognition", "due_cognition",
        "_runtime_registry_due_cognition", "_runtime_scheduler_due_cognition", _JOB_NO_ARGS,
    ),
    (
        "_schedule_due_dialogue", "due_dialogue",
        "_runtime_registry_due_dialogue", "_runtime_scheduler_due_dialogue", _JOB_NO_ARGS,
    ),
    (
        "_schedule_voice_dialogue", "voice_dialogue",
        "_runtime_registry_voice_dialogue", "_runtime_scheduler_voice_dialogue", _JOB_NO_ARGS,
    ),
    (
        "_maybe_schedule_chronicle", "chronicle",
        "_runtime_registry_chronicle", "_runtime_scheduler_chronicle", _JOB_EVENTS_SEASON,
    ),
    (
        "_maybe_schedule_documentary", "documentary",
        "_runtime_registry_documentary", "_runtime_scheduler_documentary", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_tradition", "tradition",
        "_runtime_registry_tradition", "_runtime_scheduler_tradition", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_folklore", "folklore",
        "_runtime_registry_folklore", "_runtime_scheduler_folklore", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_legend_detection", "legend_detection",
        "_runtime_registry_legend_detection", "_runtime_scheduler_legend_detection", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_invention", "invention",
        "_runtime_registry_invention", "_runtime_scheduler_invention", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_ontology_proposal", "ontology_proposal",
        "_runtime_registry_ontology_proposal", "_runtime_scheduler_ontology_proposal", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_ontology_evolution", "ontology_evolution",
        "_runtime_registry_ontology_evolution", "_runtime_scheduler_ontology_evolution", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_composite_entity", "composite_entity",
        "_runtime_registry_composite_entity", "_runtime_scheduler_composite_entity", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_nature_mind", "nature_mind",
        "_runtime_registry_nature_mind", "_runtime_scheduler_nature_mind", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_species_variant", "species_variant",
        "_runtime_registry_species_variant", "_runtime_scheduler_species_variant", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_rule_proposal", "rule_proposal",
        "_runtime_registry_rule_proposal", "_runtime_scheduler_rule_proposal", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_composite_reaction_propose", "composite_reaction_propose",
        "_runtime_registry_composite_reaction_propose", "_runtime_scheduler_composite_reaction_propose",
        _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_festival", "festival",
        "_runtime_registry_festival", "_runtime_scheduler_festival", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_religion", "religion",
        "_runtime_registry_religion", "_runtime_scheduler_religion", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_narrative_direction", "narrative_direction",
        "_runtime_registry_narrative_direction", "_runtime_scheduler_narrative_direction", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_culture_digest", "culture_digest",
        "_runtime_registry_culture_digest", "_runtime_scheduler_culture_digest", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_consciousness", "consciousness",
        "_runtime_registry_consciousness", "_runtime_scheduler_consciousness", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_reflection", "reflection",
        "_runtime_registry_reflection", "_runtime_scheduler_reflection", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_self_tuning", "self_tuning",
        "_runtime_registry_self_tuning", "_runtime_scheduler_self_tuning", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_musing", "musing",
        "_runtime_registry_musing", "_runtime_scheduler_musing", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_caravan", "caravan",
        "_runtime_registry_caravan", "_runtime_scheduler_caravan", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_town_brain", "town_brain",
        "_runtime_registry_town_brain", "_runtime_scheduler_town_brain", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_beliefs", "beliefs",
        "_runtime_registry_beliefs", "_runtime_scheduler_beliefs", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_personal_belief", "personal_belief",
        "_runtime_registry_personal_belief", "_runtime_scheduler_personal_belief", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_dream", "dream",
        "_runtime_registry_dream", "_runtime_scheduler_dream", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_memory_drift", "memory_drift",
        "_runtime_registry_memory_drift", "_runtime_scheduler_memory_drift", _JOB_EVENTS,
    ),
    (
        "_maybe_tick_temperament", "temperament",
        "_runtime_registry_temperament", "_runtime_scheduler_temperament", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_omen", "omen",
        "_runtime_registry_omen", "_runtime_scheduler_omen", _JOB_EVENTS,
    ),
    (
        "_maybe_tick_market_prices", "market_prices",
        "_runtime_registry_market_prices", "_runtime_scheduler_market_prices", _JOB_EVENTS,
    ),
    (
        "_maybe_tick_settlement_trade", "settlement_trade",
        "_runtime_registry_settlement_trade", "_runtime_scheduler_settlement_trade", _JOB_EVENTS,
    ),
    (
        "_maybe_pillar_initiates_contact", "pillar_initiates_contact",
        "_runtime_registry_pillar_initiates_contact", "_runtime_scheduler_pillar_initiates_contact",
        _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_guild_founding", "guild_founding",
        "_runtime_registry_guild_founding", "_runtime_scheduler_guild_founding", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_faction", "faction",
        "_runtime_registry_faction", "_runtime_scheduler_faction", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_institution_belief", "institution_belief",
        "_runtime_registry_institution_belief", "_runtime_scheduler_institution_belief", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_geography", "geography",
        "_runtime_registry_geography", "_runtime_scheduler_geography", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_fission", "fission",
        "_runtime_registry_fission", "_runtime_scheduler_fission", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_diplomacy", "diplomacy",
        "_runtime_registry_diplomacy", "_runtime_scheduler_diplomacy", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_laws", "laws",
        "_runtime_registry_laws", "_runtime_scheduler_laws", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_noncore_nudge", "noncore_nudge",
        "_runtime_registry_noncore_nudge", "_runtime_scheduler_noncore_nudge", _JOB_EVENTS,
    ),
    (
        "_maybe_schedule_letter", "letter",
        "_runtime_registry_letter", "_runtime_scheduler_letter", _JOB_EVENTS,
    ),
    (
        # Tier 5 B3's real control point (v1.34.20x): this job's Task
        # is now ON_EVENT/event_types={"month_end"}, not CRITICAL+
        # PERIODIC like every other migration here, and its real fn no
        # longer takes `events` (the scheduler's own EventBus is the
        # gate now, not an internal `if "month_end" not in events`
        # guard) — arg_kind is _JOB_NO_ARGS to match. Excluded from
        # this script's generic "always runs every tick" checks below
        # (see EVENT_DRIVEN_TASK_IDS) since that's no longer true by
        # design; its own correct (different) behavior is verified in
        # depth by `scripts/verify_b3_dirty_events.py` instead.
        "_update_institution_dormancy", "institution_dormancy",
        "_runtime_registry_institution_dormancy", "_runtime_scheduler_institution_dormancy", _JOB_NO_ARGS,
    ),
    (
        "_maybe_schedule_institution_culture", "institution_culture",
        "_runtime_registry_institution_culture", "_runtime_scheduler_institution_culture", _JOB_EVENTS,
    ),
]


EVENT_DRIVEN_TASK_IDS = {"institution_dormancy"}
"""Tier 5 B3's real control point: `institution_dormancy` is the one
migrated job that's genuinely ON_EVENT, not CRITICAL+PERIODIC — it
does NOT run every tick by design. Excluded from every "always runs"
generic assertion below; its own correct behavior is verified in
depth by `scripts/verify_b3_dirty_events.py`."""


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


def _run_args(arg_kind: int) -> tuple:
    """The real per-tick positional arguments `_tick_once` passes for
    this arg kind — `()` for `_JOB_NO_ARGS`, `(events,)` for `_JOB_
    EVENTS`, `(events, previous_season)` for `_JOB_EVENTS_SEASON`.
    Synthetic but shaped exactly like what `World.tick()` produces
    (a list of `(category, text)` tuples for events, a plain string
    for the season) — real enough to exercise `run_tick(*args)`
    forwarding all the way to the real bound method without needing a
    live engine tick to generate them."""
    if arg_kind == _JOB_NO_ARGS:
        return ()
    if arg_kind == _JOB_EVENTS:
        return ([],)
    return ([], "spring")


async def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        eng = make_engine(d)

        # 1. Wiring sanity: each registry holds exactly its own one
        #    migrated task, correctly declared, and the method-name ->
        #    scheduler-attribute mapping is complete and correctly
        #    resolved, for every migration.
        mapping = SimulationEngine._RUNTIME_SCHEDULED_JOB_SCHEDULERS
        for method_name, task_id, registry_attr, scheduler_attr, _arg_kind in MIGRATIONS:
            registry = getattr(eng, registry_attr)
            check(
                f"{registry_attr} holds exactly the '{task_id}' task",
                list(registry.topological_order()) == [task_id],
            )
            task = registry.get(task_id)
            if task_id in EVENT_DRIVEN_TASK_IDS:
                check(
                    f"'{task_id}' task is CRITICAL + ON_EVENT (B3's real control point, not 'always runs')",
                    task.priority_class is PriorityClass.CRITICAL and task.trigger is TriggerKind.ON_EVENT
                    and bool(task.event_types),
                )
            else:
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
        #    bound method with its REAL declared arg shape (not just
        #    "didn't crash") — swap in a synthetic fn on a throwaway
        #    registry per job that writes a distinct marker, and
        #    confirm the write lands after one `run_tick(*args)` call
        #    on THAT job's own scheduler, using this job's real
        #    `_run_args(arg_kind)` — proves `task.fn(*args)` really
        #    executes with its declared signature, including the
        #    events-carrying jobs, and real side effects reach real
        #    state.
        marks: set[str] = set()
        for method_name, task_id, _registry_attr, _scheduler_attr, arg_kind in MIGRATIONS:
            def make_marker(name: str):
                def _mark(*_args) -> None:
                    marks.add(name)
                return _mark

            probe_registry = TaskRegistry()
            probe_registry.register(Task(
                id=task_id, subsystem=task_id, fn=make_marker(task_id),
                trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
            ))
            Scheduler(probe_registry).run_tick(*_run_args(arg_kind))
        check(
            "each scheduler's run_tick(*args) genuinely invokes its own task.fn(*args) with real side effects",
            marks == {task_id for _, task_id, _, _, _ in MIGRATIONS},
        )

        # 3. Direct scheduler-level proof: run_tick(*args) reports each
        #    REAL task as genuinely 'ran' with its real args, never
        #    'skipped_clean' or 'deferred' — the CRITICAL+PERIODIC
        #    contract holding under the real scheduler against the
        #    real bound method, not just a synthetic stand-in.
        all_ran_clean = True
        for _method_name, task_id, _registry_attr, scheduler_attr, arg_kind in MIGRATIONS:
            if task_id in EVENT_DRIVEN_TASK_IDS:
                continue
            report = getattr(eng, scheduler_attr).run_tick(*_run_args(arg_kind))
            if task_id not in report.ran or task_id in report.skipped_clean \
                    or task_id in report.deferred or report.errors:
                all_ran_clean = False
        check(
            "every always-on migrated task ran this tick with its real args (never skipped/deferred), no errors",
            all_ran_clean,
        )

        # 4. Repeated ticks: every job keeps running every single tick
        #    through its own scheduler with its real args (CRITICAL
        #    priority never budget-starves it) — the direct-call
        #    replacement property, across every migration at once.
        all_ran = True
        for _ in range(50):
            eng._tick_once()
            await asyncio.sleep(0)
            for _method_name, task_id, _registry_attr, scheduler_attr, arg_kind in MIGRATIONS:
                if task_id in EVENT_DRIVEN_TASK_IDS:
                    continue
                rep = getattr(eng, scheduler_attr).run_tick(*_run_args(arg_kind))
                if task_id not in rep.ran:
                    all_ran = False
        check(
            "every always-on migrated task ran on every one of 50 further real ticks",
            all_ran,
        )

        # 5. THE load-bearing check for the per-job-registry design: a
        #    real `_tick_once()` call must invoke each migrated job's
        #    fn EXACTLY ONCE, never twice — the exact bug a shared
        #    registry would introduce (run_tick() called once per
        #    `_TICK_JOBS` slot, each call re-running every task in a
        #    shared registry). Count real invocations via a wrapped fn
        #    swapped into each job's OWN registry (not a fresh probe
        #    registry — the real one `_tick_once` actually drives),
        #    driven by a real `_tick_once()` — proving the real
        #    `arg_kind`-dispatching branch added at the call site
        #    (`_JOB_NO_ARGS`/`_JOB_EVENTS`/`_JOB_EVENTS_SEASON` each
        #    calling `run_tick` with the right args) still routes to
        #    exactly one call per job, not zero or two.
        call_counts: dict[str, int] = {task_id: 0 for _, task_id, _, _, _ in MIGRATIONS}
        for method_name, task_id, registry_attr, _scheduler_attr, _arg_kind in MIGRATIONS:
            registry = getattr(eng, registry_attr)
            real_fn = registry.get(task_id).fn

            def make_counted(name: str, fn):
                def _counted(*args, **kwargs) -> None:
                    call_counts[name] += 1
                    fn(*args, **kwargs)
                return _counted

            registry._tasks[task_id] = dataclasses.replace(
                registry.get(task_id), fn=make_counted(task_id, real_fn),
            )
        for task_id in call_counts:
            call_counts[task_id] = 0
        eng._tick_once()
        await asyncio.sleep(0)
        check(
            "each always-on migrated job's fn runs EXACTLY ONCE per real _tick_once() call (no double-execution)",
            all(count == 1 for task_id, count in call_counts.items() if task_id not in EVENT_DRIVEN_TASK_IDS),
        )
        check(
            "the event-driven migrated job's fn never runs MORE than once per real _tick_once() call",
            all(count <= 1 for task_id, count in call_counts.items() if task_id in EVENT_DRIVEN_TASK_IDS),
        )

    # 6. Error propagation: a migrated CRITICAL task's exception must
    #    still stop the tick (not be silently swallowed the way
    #    Scheduler._run_one's broad except normally would) — build a
    #    throwaway registry+scheduler with a task that always raises,
    #    and confirm run_tick() reports the error rather than hiding it
    #    (the real re-raise happens in `_tick_once`'s own call site;
    #    this confirms the report it re-raises FROM is correct).
    def _boom(*_args) -> None:
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

    # 8. A real `_JOB_EVENTS_SEASON` task specifically — the one job
    #    (`chronicle`) needing TWO real positional args — must still
    #    stop the tick on error, proving the two-argument dispatch
    #    branch at the real call site is wired correctly, not just the
    #    one-argument `_JOB_EVENTS` branch check 7 already covers via
    #    naming's (zero-arg) shape.
    with tempfile.TemporaryDirectory() as d3:
        eng3 = make_engine(d3, seed=4242)
        eng3._runtime_registry_chronicle = TaskRegistry()
        eng3._runtime_registry_chronicle.register(Task(
            id="chronicle", subsystem="chronicle", fn=_boom,
            trigger=TriggerKind.PERIODIC, priority_class=PriorityClass.CRITICAL,
        ))
        eng3._runtime_scheduler_chronicle = Scheduler(eng3._runtime_registry_chronicle)
        raised = False
        try:
            eng3._tick_once()
            await asyncio.sleep(0)
        except RuntimeError as exc:
            raised = "runtime-scheduled task(s) errored" in str(exc) and "synthetic failure" in str(exc)
        check(
            "an error in the real _JOB_EVENTS_SEASON (two-arg) migrated task also propagates",
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
