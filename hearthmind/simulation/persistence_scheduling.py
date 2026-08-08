"""B14 -- Persistence & background work (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B). Standalone infrastructure, same "never
big-bang" discipline as every other Tier 5 Runtime module -- not
wired into `simulation/engine.py`/`persistence/database.py`'s real
snapshot cadence yet.

Deliberately reuses three already-shipped Runtime primitives rather
than building parallel ones:

  - B14.1's "scheduled, budgeted, idle-preferring, adaptive frequency"
    reuses B9.2's `ElapsedTimeTracker` (elapsed-time integration) and
    B8.4's `is_quiet_window` (the real idle-preference signal) directly.
  - B14.1's "adaptive frequency (B6.1)" is real B6 `Tunable`s
    (`register_snapshot_tunables`), same metadata-only discipline
    B6.3 already established for the LLM-pacing constants -- this
    doesn't rewire a live cadence, it makes the cadence's own bounds a
    real tunable a future B13 `HypothesisLoop` could retune.
  - B14.3's "storage-speed-aware batching from the machine profile
    (B7.2)" reads `HostProbe.storage_write_mb_s` directly -- no second
    storage-speed detector.

B14.1 `SnapshotScheduler.due`: a snapshot is due once EITHER its
     `min_interval_ticks` has elapsed AND the system is genuinely quiet
     (`is_quiet_window`, idle-preferring) OR its `max_interval_ticks`
     has elapsed regardless of load (a hard ceiling -- a permanently
     busy world must still snapshot eventually, never wait forever).
     The very first check after construction never fires (there is no
     real elapsed baseline yet to judge against) -- same contract
     `TimescaleGate.check` already established.
B14.2 `SnapshotScheduler.plan`: every `full_snapshot_every`-th DUE
     snapshot is a real FULL snapshot; every other due snapshot is
     INCREMENTAL. This module stays storage-format-agnostic (same
     discipline B11/B12 hold) -- it decides WHICH KIND is due, never
     how a diff is computed or written; a real caller supplies its own
     `diff_fn`/writer against `persistence/database.py`'s actual
     snapshot format.
B14.3 `batch_size_for_storage`: solves for a write-batch size that
     keeps a single write's real wall-clock cost near a target latency
     ceiling, given the profile's OWN measured `storage_write_mb_s` --
     faster storage earns a larger batch (fewer, bigger writes);
     slower storage or an unmeasured host stays conservative. A pure
     function of `HostProbe`/`MachineProfile` data, never a hardware-
     specific branch in gameplay code, per B7.3's own precedent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from hearthmind.simulation.forecasting import is_quiet_window
from hearthmind.simulation.timescales import ElapsedTimeTracker
from hearthmind.util import clamp

SNAPSHOT_TASK_KEY = "snapshot"


class SnapshotKind(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


@dataclass
class SnapshotPolicy:
    """B14.1/B14.2's real bounds. `min_interval_ticks`: never snapshot
    more often than this, even if the system sits idle the whole time.
    `max_interval_ticks`: always snapshot by this point, regardless of
    load -- the hard ceiling. `full_snapshot_every`: every Nth real due
    snapshot is FULL; the rest are INCREMENTAL."""

    min_interval_ticks: int
    max_interval_ticks: int
    full_snapshot_every: int = 5
    idle_threshold_fraction: float = 0.3

    def __post_init__(self) -> None:
        if self.min_interval_ticks > self.max_interval_ticks:
            raise ValueError("min_interval_ticks cannot exceed max_interval_ticks")
        if self.full_snapshot_every < 1:
            raise ValueError("full_snapshot_every must be >= 1")


@dataclass
class SnapshotScheduler:
    """B14.1/B14.2. `snapshot_count` is the real count of DUE snapshots
    actually granted so far (not every `due` check) -- `plan`'s FULL/
    INCREMENTAL cadence is measured against this, not against ticks."""

    policy: SnapshotPolicy
    tracker: ElapsedTimeTracker = field(default_factory=ElapsedTimeTracker)
    snapshot_count: int = 0

    def due(self, tick: int, recent_loads: list, capacity: float) -> bool:
        """B14.1. `recent_loads`/`capacity` feed `is_quiet_window`
        directly -- the real idle-preference signal, not a second
        heuristic. Marks a new baseline whenever it returns True (a
        real snapshot just happened) or on the very first call (no
        prior baseline to integrate from yet)."""
        elapsed = self.tracker.elapsed_since(SNAPSHOT_TASK_KEY, tick)
        if elapsed is None:
            self.tracker.mark_run(SNAPSHOT_TASK_KEY, tick)
            return False

        forced = elapsed >= self.policy.max_interval_ticks
        idle_eligible = elapsed >= self.policy.min_interval_ticks and is_quiet_window(
            recent_loads, capacity, threshold_fraction=self.policy.idle_threshold_fraction
        )
        result = forced or idle_eligible
        if result:
            self.tracker.mark_run(SNAPSHOT_TASK_KEY, tick)
        return result

    def plan(self) -> SnapshotKind:
        """B14.2. Call only once a `due()` check has actually returned
        True -- this records the real snapshot count and decides
        FULL vs INCREMENTAL for THIS one."""
        self.snapshot_count += 1
        if self.snapshot_count % self.policy.full_snapshot_every == 1:
            return SnapshotKind.FULL
        return SnapshotKind.INCREMENTAL


def register_snapshot_tunables(registry, policy: SnapshotPolicy) -> None:
    """B14.1's "(B6.1)" tie-in: mirrors this scheduler's own real
    interval bounds into B6's `TunableRegistry` as real `Tunable`s --
    metadata only, same discipline `register_llm_pacing_tunables`
    (B6.3) already established; does not rewire `SnapshotScheduler`
    itself to read from the registry live. A future B13 `HypothesisLoop`
    retuning `snapshot_min_interval_ticks`/`snapshot_max_interval_ticks`
    would need its own live-diagnostic-driven pass, same as every past
    retune of a Tier 5 constant."""
    from hearthmind.simulation.tuning import SafetyClass, Tunable

    registry.register(Tunable(
        name="snapshot_min_interval_ticks", value=float(policy.min_interval_ticks),
        min_value=1.0, max_value=float(policy.max_interval_ticks), step=10.0,
        safety_class=SafetyClass.SAFE,
        description="SnapshotPolicy.min_interval_ticks -- never snapshot more often than this even when idle.",
    ))
    registry.register(Tunable(
        name="snapshot_max_interval_ticks", value=float(policy.max_interval_ticks),
        min_value=float(policy.min_interval_ticks), max_value=float(policy.max_interval_ticks) * 10.0, step=10.0,
        safety_class=SafetyClass.SAFE,
        description="SnapshotPolicy.max_interval_ticks -- always snapshot by this point regardless of load.",
    ))


def batch_size_for_storage(
    storage_write_mb_s: Optional[float],
    target_write_latency_s: float,
    min_batch_bytes: int,
    max_batch_bytes: int,
) -> int:
    """B14.3. Solves `batch_bytes = write_speed * target_latency` --
    the batch size that keeps one write's real wall-clock cost near
    the target ceiling given THIS host's own measured throughput
    (`HostProbe.storage_write_mb_s`, B7.1/B7.2). An unmeasured/zero
    speed (host probe couldn't benchmark storage) falls back to the
    conservative floor rather than guessing a large batch."""
    if storage_write_mb_s is None or storage_write_mb_s <= 0:
        return min_batch_bytes
    ideal = int(storage_write_mb_s * 1_000_000 * target_write_latency_s)
    return clamp(ideal, min_batch_bytes, max_batch_bytes)
