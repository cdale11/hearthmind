"""Tier 5 B5 — Continuous profiling.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rules 5, 15]:
"No 'profiling mode' — profiling *is* the runtime." `TaskMetrics` is
B5.1's always-on per-task counters (a bounded ring buffer of recent
wall-time samples, not raw logs); `TickTrace`/`TaskTraceEntry` are
B5.4's "explain this tick" full execution trace, built every tick into
a bounded history so "why didn't X run?" is always answerable once
work moves off "everything runs every tick" (B1's own scheduling).

**B5.1/B5.4 shipped this pass; B5.3 (a real `/diagnostics/runtime`
endpoint + dev-console wiring) explicitly NOT attempted** — same
discipline as every prior B-item: no import from this module exists
in `simulation/engine.py`, and there's no real engine subsystem
running through `Scheduler` yet to expose. B5.3's own "no subsystem
may be a black box" review rule is instead a real STRUCTURAL
guarantee here: `Scheduler` (see `scheduler.py`) creates a
`TaskMetrics` entry for every task the moment it's first processed —
there is no code path for a registered task to avoid being metered,
so the CI-rule version of this requirement is moot by construction.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from hearthmind.cognition.workspace import Domain

SPECIALIST_DOMAIN = Domain.MACHINE
"""Tier 7 HCA Stage H, H2: `TaskMetrics` is the Adaptive Runtime
specialist family's real `observe()` (see `hearthmind.cognition.
runtime_specialist`'s own module docstring for the full family
mapping) -- this file already imports nothing from `hearthmind.world`/
`.agents`/`.settlement`/`.economy`, so the marker alone makes `scripts/
verify_runtime_invariant.py`'s write-scope check real against this
real production module."""

# B5.1: "ring-buffer aggregates, not raw logs" — bounds memory
# regardless of run length. 200 samples is enough for p50/p95-style
# eyeballing without ever growing unbounded.
METRICS_SAMPLE_HISTORY = 200

# B5.4: bounded history of full per-tick traces, same "ring buffer,
# not raw logs" discipline. 500 ticks is a few minutes of real-time
# tick history at this project's typical 1s/tick default — enough to
# answer "why didn't X run three ticks ago" without unbounded growth.
TICK_TRACE_HISTORY = 500


@dataclass
class TaskMetrics:
    """B5.1's per-task counters. Of the item's own named list (CPU
    time, wall time, call count, wake frequency, idle ratio, queue
    depth, cache hit rate, memory delta, budget utilization, deferral
    debt), only the ones with a real meaning at this module's current
    abstraction are tracked here — "queue depth"/"cache hit rate" have
    no real mechanism to read from yet (no per-task queue or cache
    exists anywhere in this runtime), and "memory delta" would need
    real per-call `tracemalloc` sampling this pass doesn't add (a
    real, not-yet-built follow-up, not silently skipped). Wall time
    (`perf_counter`) doubles as the CPU-time proxy for a single-
    threaded synchronous scheduler, where the two are the same thing.
    """

    task_id: str
    call_count: int = 0
    error_count: int = 0
    skipped_clean_count: int = 0
    deferred_count: int = 0
    promoted_count: int = 0
    ran_via_spare_capacity_count: int = 0
    total_wall_seconds: float = 0.0
    recent_wall_seconds: deque[float] = field(
        default_factory=lambda: deque(maxlen=METRICS_SAMPLE_HISTORY)
    )
    ticks_observed: int = 0  # every tick this task was even considered, run or not

    def record_run(self, elapsed_seconds: float, errored: bool) -> None:
        self.call_count += 1
        self.total_wall_seconds += elapsed_seconds
        self.recent_wall_seconds.append(elapsed_seconds)
        if errored:
            self.error_count += 1

    def idle_ratio(self) -> float:
        """B5.1's "idle ratio" — the fraction of ticks this task was
        considered but didn't actually run (clean-skipped or
        deferred), the real signal for "is this task's trigger mostly
        finding nothing to do.\""""
        if self.ticks_observed == 0:
            return 0.0
        idle = self.ticks_observed - self.call_count
        return idle / self.ticks_observed

    def mean_wall_seconds(self) -> float:
        if not self.recent_wall_seconds:
            return 0.0
        return sum(self.recent_wall_seconds) / len(self.recent_wall_seconds)


@dataclass
class TaskTraceEntry:
    """One task's real fate this tick, for B5.4's "explain this tick."
    `reason` is a real, specific human-readable string (which trigger
    fired and why, or why not) — never a generic placeholder."""

    task_id: str
    subsystem: str
    trigger: str  # TriggerKind.value, kept as str so this module never imports task_graph
    outcome: str  # "ran" | "deferred" | "skipped_clean" | "error"
    reason: str
    cost_seconds: float | None
    promoted: bool = False
    ran_via_spare_capacity: bool = False


@dataclass
class TickTrace:
    """B5.4's full per-tick trace — every task that was considered,
    what happened to it, and why. `Scheduler.run_tick` builds one of
    these every tick (cheap — the data is already computed as part of
    normal scheduling, this just records it in one place instead of
    discarding it) and appends it to a bounded ring buffer."""

    tick: int
    entries: list[TaskTraceEntry] = field(default_factory=list)

    def entry_for(self, task_id: str) -> TaskTraceEntry | None:
        for entry in self.entries:
            if entry.task_id == task_id:
                return entry
        return None


def new_tick_trace_history() -> deque[TickTrace]:
    return deque(maxlen=TICK_TRACE_HISTORY)
