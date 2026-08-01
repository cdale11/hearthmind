"""B9 -- Hierarchical timescales (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, Hard Rule 10). Standalone infrastructure, same "never big-bang"
discipline as every other Tier 5 Runtime module (task_graph.py,
scheduler.py, reactivity.py, dormancy.py, profiling.py, tuning.py,
hardware_profile.py, forecasting.py) -- nothing here is imported by
`simulation/engine.py` or wired into the live tick loop yet.

B9.1 `TimescaleLadder`: the doc's own named ladder (tick -> minute ->
     hour -> day -> week -> month -> season -> year), with each rung's
     minimum real-tick interval computed from a world's OWN calendar
     shape (`SimClock`'s own `sim_minutes_per_tick`/`minutes_per_day`/
     `days_per_month` conventions) rather than a guessed constant --
     "a task declared MONTH" means one real calendar month on THIS
     world's clock, whatever its tick rate is. `clamp_interval`/
     `enforce` are the real enforcement: a task's own configured
     interval can never be shorter than its declared timescale's
     floor -- the scheduler raises it, it doesn't just suggest one.
B9.2 `ElapsedTimeTracker`: generalizes `DormancyManager.wake()`'s own
     "always return the real elapsed tick count" contract (B4.3) to
     any task that might be skipped for a while, not just a dormant
     entity -- the mechanism that makes "running a slow system less
     often is mathematically equivalent, not an approximation" true
     in practice for a generic consumer.
`TimescaleGate` ties both together into the one call a real scheduled
task would make: "is this task due yet, and if so, how much real time
actually elapsed since it last ran?"

B9.3 (a live audit of the ~200 real per-tick call sites in `engine.py`
for timescale mismatch) is explicitly NOT attempted here -- same
"needs individual live judgment, not a mechanism" class as B3.3's own
audit deferral. This ships the tool such an audit would use to convert
a finding into a real enforced timescale, not the audit itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TIMESCALE_ORDER = ["tick", "minute", "hour", "day", "week", "month", "season", "year"]


@dataclass
class TimescaleLadder:
    """B9.1. Minimum real-tick interval per named timescale."""

    min_tick_interval: dict

    @classmethod
    def from_calendar(
        cls,
        sim_minutes_per_tick: float,
        minutes_per_day: int,
        days_per_month: list,
        months_per_season: int = 3,
        days_per_year: int = 365,
    ) -> "TimescaleLadder":
        """Derives every rung's floor from the SAME calendar shape
        `SimClock` already uses -- so "a day" here means exactly what
        `SimClock.day_index` crossing means on this world's clock, not
        an independently-guessed number of ticks."""
        sim_minutes_per_tick = max(1e-9, sim_minutes_per_tick)
        ticks_per_day = max(1, round(minutes_per_day / sim_minutes_per_tick))
        avg_days_per_month = (sum(days_per_month) / len(days_per_month)) if days_per_month else 30.0
        ticks_per_month = max(1, round(ticks_per_day * avg_days_per_month))
        intervals = {
            "tick": 1,
            "minute": max(1, round(1.0 / sim_minutes_per_tick)),
            "hour": max(1, round(60.0 / sim_minutes_per_tick)),
            "day": ticks_per_day,
            "week": ticks_per_day * 7,
            "month": ticks_per_month,
            "season": max(1, round(ticks_per_month * months_per_season)),
            "year": max(1, round(ticks_per_day * days_per_year)),
        }
        return cls(min_tick_interval=intervals)

    def floor_for(self, timescale: str) -> int:
        return self.min_tick_interval.get(timescale, 1)

    def rank(self, timescale: str) -> int:
        return TIMESCALE_ORDER.index(timescale) if timescale in TIMESCALE_ORDER else 0

    def is_slower_than(self, a: str, b: str) -> bool:
        """True if timescale `a` sits further down the ladder (a
        genuinely slower cadence) than `b`."""
        return self.rank(a) > self.rank(b)

    def enforce(self, timescale: str, requested_interval: int) -> tuple:
        """The real B9.1 enforcement: a task's own configured run
        interval can never be shorter than its declared timescale's
        calendar floor. Returns `(enforced_interval, was_clamped)`."""
        floor = self.floor_for(timescale)
        if requested_interval < floor:
            return floor, True
        return requested_interval, False


@dataclass
class ElapsedTimeTracker:
    """B9.2. Per-task last-run tick, so any consumer can integrate over
    the REAL elapsed time since it last ran instead of assuming a
    fixed step -- the same contract `DormancyManager.wake()` already
    guarantees for B4.3, generalized beyond dormancy specifically."""

    _last_run: dict = field(default_factory=dict)

    def has_baseline(self, task_id: str) -> bool:
        return task_id in self._last_run

    def elapsed_since(self, task_id: str, tick: int):
        """Non-mutating: the real elapsed ticks since this task's last
        recorded run, or `None` if it has never run before (there is
        no real baseline to integrate from yet)."""
        last = self._last_run.get(task_id)
        if last is None:
            return None
        return max(0, tick - last)

    def mark_run(self, task_id: str, tick: int) -> None:
        self._last_run[task_id] = tick


@dataclass
class TimescaleGate:
    """Combines B9.1 + B9.2 into the one call a real scheduled task
    would make: "is this due, and if so, how much real time elapsed?"
    """

    ladder: TimescaleLadder
    tracker: ElapsedTimeTracker = field(default_factory=ElapsedTimeTracker)

    def check(self, task_id: str, timescale: str, tick: int) -> tuple:
        """Returns `(due, elapsed_ticks)`. A task with no prior
        baseline establishes one now and reports not-due (there is no
        real elapsed history yet to judge against) -- the NEXT check
        is the first one that can genuinely fire. When due, the new
        baseline is committed; when not due, the existing baseline is
        left untouched so elapsed time keeps accumulating correctly
        across repeated non-firing checks, exactly the semantics B9.2
        needs to stay a real Δt integration rather than an
        approximation."""
        elapsed = self.tracker.elapsed_since(task_id, tick)
        if elapsed is None:
            self.tracker.mark_run(task_id, tick)
            return False, 0
        floor = self.ladder.floor_for(timescale)
        if elapsed >= floor:
            self.tracker.mark_run(task_id, tick)
            return True, elapsed
        return False, elapsed
