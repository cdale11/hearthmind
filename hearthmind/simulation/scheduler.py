"""Tier 5 B2/B3 — Budgets & scheduling; dirty tracking & the event bus.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rules 2, 3, 9]:
builds on B1's `task_graph.py` (`Task`/`TaskRegistry`/`topological_
order`) to become the thing that would actually *execute* a
`TaskRegistry`'s tasks against real per-subsystem time budgets (B2),
gated by whether each task's declared trigger says it's even due to
run this tick at all (B3.1/B3.2, via `reactivity.py`'s `DirtyTracker`/
`EventBus`).

**Not wired into the live tick loop yet — same "never big-bang"
discipline as B1.** No import from this module exists anywhere in
`simulation/engine.py`; this ships the budgeted/reactive scheduler
itself, verified against synthetic task sets (`scripts/verify_
scheduler.py`), not yet given real subsystem tasks to run. Migrating a
real subsystem onto B1+B2+B3 together, one at a time, remains open
future Part B work (B0.3/B1.4).

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
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

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

    def budget_for(self, subsystem: str) -> SubsystemBudget:
        if subsystem not in self._budgets:
            self._budgets[subsystem] = SubsystemBudget(subsystem=subsystem)
        return self._budgets[subsystem]

    def _max_deferrals(self, task: Task) -> int:
        return DEFAULT_MAX_DEFERRALS.get(task.priority_class, 1)

    def _is_due(self, task: Task, observed: dict[str, int]) -> bool:
        if task.trigger is TriggerKind.ON_DIRTY:
            if not task.reads:
                return False  # nothing declared to react to -- use PERIODIC for an unconditional task
            return self.dirty_tracker.is_dirty_for(task.reads, observed)
        if task.trigger is TriggerKind.ON_EVENT:
            return self.event_bus.is_pending(task.event_types)
        return True  # PERIODIC, and PREDICTED (not yet specially handled)

    def _run_one(self, task: Task, report: TickReport, budget: SubsystemBudget, observed: dict[str, int], *args, **kwargs) -> None:
        start = time.perf_counter()
        try:
            task.fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed silently
            report.errors[task.id] = repr(exc)
        elapsed = time.perf_counter() - start
        budget.consumed_this_tick += elapsed
        self._deferral_counts[task.id] = 0
        if task.writes:
            self.dirty_tracker.mark_written(task.writes)
        if task.trigger is TriggerKind.ON_DIRTY:
            self.dirty_tracker.mark_observed(task.reads, observed)

    def run_tick(self, *args, tick_time_budget_seconds: float | None = None, **kwargs) -> TickReport:
        report = TickReport()
        tick_start = time.perf_counter()
        order = self._registry.topological_order()

        spare_capacity_candidates: list[str] = []
        for task_id in order:
            task = self._registry.get(task_id)
            observed = self._observed_versions.setdefault(task_id, {})

            if not self._is_due(task, observed):
                report.skipped_clean.append(task_id)
                continue

            budget = self.budget_for(task.subsystem)

            if task.priority_class is PriorityClass.CRITICAL:
                self._run_one(task, report, budget, observed, *args, **kwargs)
                report.ran.append(task_id)
                continue

            deferral_count = self._deferral_counts.get(task_id, 0)
            force_run = deferral_count >= self._max_deferrals(task)

            if not force_run and budget.remaining() <= 0.0:
                report.deferred.append(task_id)
                self._deferral_counts[task_id] = deferral_count + 1
                if task.priority_class in (PriorityClass.BACKGROUND, PriorityClass.IDLE_ONLY):
                    spare_capacity_candidates.append(task_id)
                continue

            self._run_one(task, report, budget, observed, *args, **kwargs)
            report.ran.append(task_id)
            if force_run and deferral_count > 0:
                report.promoted.append(task_id)

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
                self._run_one(task, report, budget, observed, *args, **kwargs)
                report.deferred.remove(task_id)
                report.ran.append(task_id)
                report.ran_via_spare_capacity.append(task_id)

        self.event_bus.clear()
        for budget in self._budgets.values():
            budget.reset_tick()
        return report
