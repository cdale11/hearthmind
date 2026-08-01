"""Tier 5 B2/B3/B5 — Budgets & scheduling; dirty tracking & the event
bus; continuous profiling.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rules 2, 3, 5, 9,
15]: builds on B1's `task_graph.py` (`Task`/`TaskRegistry`/
`topological_order`) to become the thing that would actually *execute*
a `TaskRegistry`'s tasks against real per-subsystem time budgets (B2),
gated by whether each task's declared trigger says it's even due to
run this tick at all (B3.1/B3.2, via `reactivity.py`'s `DirtyTracker`/
`EventBus`), with every task's real fate recorded always-on (B5.1's
per-task metrics, B5.4's "explain this tick" trace — `profiling.py`).

**Not wired into the live tick loop yet — same "never big-bang"
discipline as B1.** No import from this module exists anywhere in
`simulation/engine.py`; this ships the budgeted/reactive/profiled
scheduler itself, verified against synthetic task sets (`scripts/
verify_scheduler.py`), not yet given real subsystem tasks to run.
Migrating a real subsystem onto B1+B2+B3 together, one at a time,
remains open future Part B work (B0.3/B1.4).

**B2.4 explicitly NOT attempted this pass** — its own text says it
"requires B10's timescales and B11's locality to be honest," and
neither exists yet. Faking a per-region activity score without real
timescale/locality machinery behind it would be worse than not having
one; left open, not stubbed.

**B3.3 (audit current per-tick polling, convert genuine polling-in-
disguise to B3.1/B3.2) also NOT attempted this pass** — it's a real
case-by-case audit of the ~200 live schedule points in `engine.py`
(B0.3), each needing individual judgment and live replay-hash
verification, not a mechanism to build; left open as real future work,
same as B1.4's actual migration.

**B5.3 (a real `/diagnostics/runtime` endpoint + dev-console wiring)
also NOT attempted this pass** — there's no real engine subsystem
running through `Scheduler` yet to expose. See `profiling.py`'s own
docstring for why B5.3's "no black box" review rule is instead a
structural guarantee here rather than something a CI rule enforces.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from .profiling import TaskMetrics, TaskTraceEntry, TickTrace, new_tick_trace_history
from .reactivity import DirtyTracker, EventBus
from .task_graph import PriorityClass, Task, TaskRegistry, TriggerKind

# B2.1's own text: "a time slice per tick/frame, adaptive (B6)." B6
# (continuous profiling driving adaptive budgets) doesn't exist yet, so
# this stays a static per-subsystem dial until it does — an honest
# placeholder, not a faked adaptive one.
DEFAULT_BUDGET_SECONDS = 0.002

# B2.2's bounded-deferral rule: a task deferred this many consecutive
# ticks is force-run (promoted) regardless of remaining budget — nothing
# may starve, since silent starvation would change simulation outcomes
# (Hard Rule 1). CRITICAL tasks are never deferred in the first place,
# so their bound is moot; kept for completeness/lookup uniformity.
DEFAULT_MAX_DEFERRALS: dict[PriorityClass, int] = {
    PriorityClass.CRITICAL: 0,
    PriorityClass.STANDARD: 1,
    PriorityClass.DEFERRABLE: 3,
    PriorityClass.BACKGROUND: 8,
    PriorityClass.IDLE_ONLY: 20,
}


@dataclass
class SubsystemBudget:
    """B2.1's per-subsystem execution budget + B2.3's overrun tracking."""

    subsystem: str
    seconds_per_tick: float = DEFAULT_BUDGET_SECONDS
    consumed_this_tick: float = 0.0
    debt_seconds: float = 0.0  # cumulative overrun carried forward, never reset

    def remaining(self) -> float:
        return max(0.0, self.seconds_per_tick - self.consumed_this_tick)

    def reset_tick(self) -> None:
        overrun = self.consumed_this_tick - self.seconds_per_tick
        if overrun > 0:
            self.debt_seconds += overrun
        self.consumed_this_tick = 0.0


@dataclass
class TickReport:
    """What actually happened this tick — the B15 diagnostics surface
    this module doesn't itself expose yet (no `/diagnostics/runtime`
    endpoint exists), but every field here is real, not placeholder."""

    ran: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)  # force-run past their deferral bound
    ran_via_spare_capacity: list[str] = field(default_factory=list)  # B2.5
    skipped_clean: list[str] = field(default_factory=list)  # B3.1/B3.2: not due, never touched budget
    errors: dict[str, str] = field(default_factory=dict)


class Scheduler:
    """B2's budgeted executor over a B1 `TaskRegistry`.

    Runs the registry's tasks in B1.3's deterministic topological
    order, charging each task's measured wall-clock cost against its
    subsystem's per-tick budget (B2.1). A task whose subsystem is out
    of budget this tick is DEFERRED, never skipped (B2.3) — it stays
    eligible next tick and its deferral count increments; once that
    count reaches its priority class's bound (B2.2), the task is
    force-run this tick regardless of remaining budget (`promoted`).
    CRITICAL tasks always run, budget or not — "must run this tick" is
    the definition of the class.

    B2.5's work-conserving pass runs after the main loop: if the
    overall tick still has spare wall-clock time (a separate,
    optional `tick_time_budget_seconds` — the shared ceiling, distinct
    from any one subsystem's own dial) and BACKGROUND/IDLE_ONLY tasks
    were deferred this tick purely for budget reasons, run them now
    rather than leaving real spare capacity idle.

    B3.1/B3.2's reactivity gate runs BEFORE any of the above, for
    every task regardless of priority class (including CRITICAL — a
    critical task that has nothing new to react to still doesn't need
    to run): an `ON_DIRTY` task only counts as due once `DirtyTracker`
    shows one of its `reads` has advanced since it last ran; an
    `ON_EVENT` task only counts as due if one of its `event_types` was
    published to `EventBus` this tick. A task that isn't due is
    `skipped_clean` — it never touches the budget/deferral machinery
    at all, which is the actual CPU win B3.1 names as "the single
    biggest available." `PERIODIC` (and `PREDICTED`, not specially
    handled yet — see the module docstring) tasks stay unconditionally
    due every tick, unchanged from B2's original behavior.
    """

    def __init__(
        self,
        registry: TaskRegistry,
        budgets: dict[str, SubsystemBudget] | None = None,
        dirty_tracker: DirtyTracker | None = None,
        event_bus: EventBus | None = None,
    ):
        self._registry = registry
        self._budgets: dict[str, SubsystemBudget] = budgets if budgets is not None else {}
        self._deferral_counts: dict[str, int] = {}
        self.dirty_tracker = dirty_tracker if dirty_tracker is not None else DirtyTracker()
        self.event_bus = event_bus if event_bus is not None else EventBus()
        self._observed_versions: dict[str, dict[str, int]] = {}
        self._tick_number = 0
        # B5.1: every task gets a metrics entry the moment it's first
        # processed — there is no code path to register a task and
        # never have it metered (see profiling.py's own "no black box"
        # note).
        self._metrics: dict[str, TaskMetrics] = {}
        # B5.4: bounded ring buffer of full per-tick traces.
        self.tick_traces: deque[TickTrace] = new_tick_trace_history()

    def budget_for(self, subsystem: str) -> SubsystemBudget:
        if subsystem not in self._budgets:
            self._budgets[subsystem] = SubsystemBudget(subsystem=subsystem)
        return self._budgets[subsystem]

    def all_budgets(self) -> dict[str, SubsystemBudget]:
        """B5.3's read-only accessor -- same shape as `all_metrics()`,
        added so a diagnostics report never has to reach into
        `Scheduler`'s own private `_budgets` dict directly."""
        return dict(self._budgets)

    def metrics_for(self, task_id: str) -> TaskMetrics:
        if task_id not in self._metrics:
            self._metrics[task_id] = TaskMetrics(task_id=task_id)
        return self._metrics[task_id]

    def all_metrics(self) -> dict[str, TaskMetrics]:
        return dict(self._metrics)

    def _max_deferrals(self, task: Task) -> int:
        return DEFAULT_MAX_DEFERRALS.get(task.priority_class, 1)

    def _due_and_reason(self, task: Task, observed: dict[str, int]) -> tuple[bool, str]:
        """B5.4: not just whether a task is due, but the real, specific
        reason why — "which trigger fired" per the item's own text."""
        if task.trigger is TriggerKind.ON_DIRTY:
            if not task.reads:
                return False, "ON_DIRTY with no declared reads -- never fires (use PERIODIC instead)"
            reads = sorted(task.reads)
            if self.dirty_tracker.is_dirty_for(task.reads, observed):
                return True, f"ON_DIRTY: reads {reads} changed since last observed"
            return False, f"ON_DIRTY: reads {reads} unchanged -- clean"
        if task.trigger is TriggerKind.ON_EVENT:
            pending = sorted(self.event_bus.pending().intersection(task.event_types))
            if pending:
                return True, f"ON_EVENT: {pending} published this tick"
            return False, f"ON_EVENT: none of {sorted(task.event_types)} pending this tick"
        if task.trigger is TriggerKind.PREDICTED:
            return True, "PREDICTED: not yet specially handled -- defaults to always due"
        return True, "PERIODIC: unconditionally due"

    def _run_one(self, task: Task, report: TickReport, budget: SubsystemBudget, observed: dict[str, int], *args, **kwargs) -> str | None:
        """Runs the task, updates its budget/dirty-tracking/metrics
        state, and returns an error repr (or None on success) — the
        caller decides how that error is recorded into the report/trace."""
        metrics = self.metrics_for(task.id)
        start = time.perf_counter()
        error: str | None = None
        try:
            task.fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed silently
            error = repr(exc)
            report.errors[task.id] = error
        elapsed = time.perf_counter() - start
        budget.consumed_this_tick += elapsed
        self._deferral_counts[task.id] = 0
        metrics.record_run(elapsed, errored=error is not None)
        if task.writes:
            self.dirty_tracker.mark_written(task.writes)
        if task.trigger is TriggerKind.ON_DIRTY:
            self.dirty_tracker.mark_observed(task.reads, observed)
        return error

    def run_tick(self, *args, tick_time_budget_seconds: float | None = None, **kwargs) -> TickReport:
        report = TickReport()
        trace = TickTrace(tick=self._tick_number)
        tick_start = time.perf_counter()
        order = self._registry.topological_order()

        spare_capacity_candidates: list[str] = []
        for task_id in order:
            task = self._registry.get(task_id)
            observed = self._observed_versions.setdefault(task_id, {})
            metrics = self.metrics_for(task_id)
            metrics.ticks_observed += 1

            due, reason = self._due_and_reason(task, observed)
            if not due:
                report.skipped_clean.append(task_id)
                metrics.skipped_clean_count += 1
                trace.entries.append(TaskTraceEntry(
                    task_id=task_id, subsystem=task.subsystem, trigger=task.trigger.value,
                    outcome="skipped_clean", reason=reason, cost_seconds=None,
                ))
                continue

            budget = self.budget_for(task.subsystem)

            if task.priority_class is PriorityClass.CRITICAL:
                cost_start = time.perf_counter()
                error = self._run_one(task, report, budget, observed, *args, **kwargs)
                report.ran.append(task_id)
                trace.entries.append(TaskTraceEntry(
                    task_id=task_id, subsystem=task.subsystem, trigger=task.trigger.value,
                    outcome="error" if error else "ran",
                    reason=reason + " | CRITICAL: runs regardless of budget",
                    cost_seconds=time.perf_counter() - cost_start,
                ))
                continue

            deferral_count = self._deferral_counts.get(task_id, 0)
            max_deferrals = self._max_deferrals(task)
            force_run = deferral_count >= max_deferrals

            if not force_run and budget.remaining() <= 0.0:
                report.deferred.append(task_id)
                metrics.deferred_count += 1
                self._deferral_counts[task_id] = deferral_count + 1
                if task.priority_class in (PriorityClass.BACKGROUND, PriorityClass.IDLE_ONLY):
                    spare_capacity_candidates.append(task_id)
                trace.entries.append(TaskTraceEntry(
                    task_id=task_id, subsystem=task.subsystem, trigger=task.trigger.value,
                    outcome="deferred",
                    reason=reason + f" | budget exhausted for {task.subsystem!r} (remaining={budget.remaining():.6f}s)",
                    cost_seconds=None,
                ))
                continue

            cost_start = time.perf_counter()
            error = self._run_one(task, report, budget, observed, *args, **kwargs)
            report.ran.append(task_id)
            promoted = force_run and deferral_count > 0
            if promoted:
                report.promoted.append(task_id)
                metrics.promoted_count += 1
            trace.entries.append(TaskTraceEntry(
                task_id=task_id, subsystem=task.subsystem, trigger=task.trigger.value,
                outcome="error" if error else "ran",
                reason=reason + (
                    f" | deferral bound reached ({deferral_count} >= {max_deferrals}) -- force-run"
                    if promoted else ""
                ),
                cost_seconds=time.perf_counter() - cost_start,
                promoted=promoted,
            ))

        # B2.5: work-conserving — spare overall tick time runs deferred
        # background/idle-only work rather than sitting idle. Deliberately
        # NOT reallocating one subsystem's spare per-subsystem budget to
        # another subsystem's over-budget tasks — a subsystem's own dial
        # stays its own; this only spends genuinely UNUSED overall tick
        # time, tracked separately from the per-subsystem budgets above.
        if tick_time_budget_seconds is not None:
            for task_id in spare_capacity_candidates:
                elapsed_so_far = time.perf_counter() - tick_start
                if elapsed_so_far >= tick_time_budget_seconds:
                    break
                task = self._registry.get(task_id)
                budget = self.budget_for(task.subsystem)
                observed = self._observed_versions.setdefault(task_id, {})
                cost_start = time.perf_counter()
                error = self._run_one(task, report, budget, observed, *args, **kwargs)
                report.deferred.remove(task_id)
                report.ran.append(task_id)
                report.ran_via_spare_capacity.append(task_id)
                self.metrics_for(task_id).ran_via_spare_capacity_count += 1
                existing = trace.entry_for(task_id)
                if existing is not None:
                    existing.outcome = "error" if error else "ran"
                    existing.ran_via_spare_capacity = True
                    existing.cost_seconds = time.perf_counter() - cost_start
                    existing.reason += " | ran via B2.5 spare overall tick-time capacity"

        self.event_bus.clear()
        for budget in self._budgets.values():
            budget.reset_tick()
        self.tick_traces.append(trace)
        self._tick_number += 1
        return report
