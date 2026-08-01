"""Tier 5 B2 — Budgets & scheduling.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rules 2, 9]:
builds on B1's `task_graph.py` (`Task`/`TaskRegistry`/`topological_
order`) to become the thing that would actually *execute* a
`TaskRegistry`'s tasks against real per-subsystem time budgets.

**Not wired into the live tick loop yet — same "never big-bang"
discipline as B1.** No import from this module exists anywhere in
`simulation/engine.py`; this ships the budgeted scheduler itself,
verified against a synthetic task set (`scripts/verify_scheduler.py`),
not yet given real subsystem tasks to run. Migrating a real subsystem
onto B1+B2 together, one at a time, remains open future Part B work
(B0.3/B1.4).

**B2.4 explicitly NOT attempted this pass** — its own text says it
"requires B10's timescales and B11's locality to be honest," and
neither exists yet. Faking a per-region activity score without real
timescale/locality machinery behind it would be worse than not having
one; left open, not stubbed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .task_graph import PriorityClass, Task, TaskRegistry

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
    """

    def __init__(self, registry: TaskRegistry, budgets: dict[str, SubsystemBudget] | None = None):
        self._registry = registry
        self._budgets: dict[str, SubsystemBudget] = budgets if budgets is not None else {}
        self._deferral_counts: dict[str, int] = {}

    def budget_for(self, subsystem: str) -> SubsystemBudget:
        if subsystem not in self._budgets:
            self._budgets[subsystem] = SubsystemBudget(subsystem=subsystem)
        return self._budgets[subsystem]

    def _max_deferrals(self, task: Task) -> int:
        return DEFAULT_MAX_DEFERRALS.get(task.priority_class, 1)

    def _run_one(self, task: Task, report: TickReport, budget: SubsystemBudget, *args, **kwargs) -> None:
        start = time.perf_counter()
        try:
            task.fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — recorded, not swallowed silently
            report.errors[task.id] = repr(exc)
        elapsed = time.perf_counter() - start
        budget.consumed_this_tick += elapsed
        self._deferral_counts[task.id] = 0

    def run_tick(self, *args, tick_time_budget_seconds: float | None = None, **kwargs) -> TickReport:
        report = TickReport()
        tick_start = time.perf_counter()
        order = self._registry.topological_order()

        spare_capacity_candidates: list[str] = []
        for task_id in order:
            task = self._registry.get(task_id)
            if task.priority_class is PriorityClass.CRITICAL:
                budget = self.budget_for(task.subsystem)
                self._run_one(task, report, budget, *args, **kwargs)
                report.ran.append(task_id)
                continue

            budget = self.budget_for(task.subsystem)
            deferral_count = self._deferral_counts.get(task_id, 0)
            force_run = deferral_count >= self._max_deferrals(task)

            if not force_run and budget.remaining() <= 0.0:
                report.deferred.append(task_id)
                self._deferral_counts[task_id] = deferral_count + 1
                if task.priority_class in (PriorityClass.BACKGROUND, PriorityClass.IDLE_ONLY):
                    spare_capacity_candidates.append(task_id)
                continue

            self._run_one(task, report, budget, *args, **kwargs)
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
                self._run_one(task, report, budget, *args, **kwargs)
                report.deferred.remove(task_id)
                report.ran.append(task_id)
                report.ran_via_spare_capacity.append(task_id)

        for budget in self._budgets.values():
            budget.reset_tick()
        return report
