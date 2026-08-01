#!/usr/bin/env python3
"""Standalone verification for B14 (Persistence & background work,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.persistence_scheduling import (
    SnapshotKind,
    SnapshotPolicy,
    SnapshotScheduler,
    batch_size_for_storage,
    register_snapshot_tunables,
)
from hearthmind.simulation.tuning import TunableRegistry

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


QUIET = [1.0, 1.0, 1.0]
BUSY = [95.0, 98.0, 99.0]
CAPACITY = 100.0


def check_invalid_policy_rejected():
    raised_min_max = False
    try:
        SnapshotPolicy(min_interval_ticks=1000, max_interval_ticks=100)
    except ValueError:
        raised_min_max = True
    check("SnapshotPolicy: min > max is rejected", raised_min_max)

    raised_full = False
    try:
        SnapshotPolicy(min_interval_ticks=10, max_interval_ticks=100, full_snapshot_every=0)
    except ValueError:
        raised_full = True
    check("SnapshotPolicy: full_snapshot_every < 1 is rejected", raised_full)


def check_first_check_never_fires():
    policy = SnapshotPolicy(min_interval_ticks=100, max_interval_ticks=1000)
    sched = SnapshotScheduler(policy=policy)
    due = sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)
    check("due: the very first check establishes a baseline but never fires", due is False)


def check_not_due_before_min_even_if_quiet():
    policy = SnapshotPolicy(min_interval_ticks=100, max_interval_ticks=1000)
    sched = SnapshotScheduler(policy=policy)
    sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)
    due = sched.due(tick=50, recent_loads=QUIET, capacity=CAPACITY)
    check("due: not due before min_interval_ticks, even under a genuinely quiet window", due is False)


def check_due_at_min_interval_when_quiet():
    policy = SnapshotPolicy(min_interval_ticks=100, max_interval_ticks=1000)
    sched = SnapshotScheduler(policy=policy)
    sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)
    due = sched.due(tick=100, recent_loads=QUIET, capacity=CAPACITY)
    check("due: idle-preferring -- fires at min_interval_ticks once the system is genuinely quiet", due is True)


def check_not_due_at_min_interval_when_busy():
    policy = SnapshotPolicy(min_interval_ticks=100, max_interval_ticks=1000)
    sched = SnapshotScheduler(policy=policy)
    sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)
    due = sched.due(tick=100, recent_loads=BUSY, capacity=CAPACITY)
    check("due: past min_interval_ticks but genuinely busy -- correctly waits, not due yet", due is False)


def check_forced_at_max_interval_even_if_busy():
    policy = SnapshotPolicy(min_interval_ticks=100, max_interval_ticks=1000)
    sched = SnapshotScheduler(policy=policy)
    sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)
    due = sched.due(tick=1000, recent_loads=BUSY, capacity=CAPACITY)
    check("due: the hard ceiling forces a snapshot at max_interval_ticks regardless of load", due is True)


def check_clock_resets_only_on_a_real_due_result():
    policy = SnapshotPolicy(min_interval_ticks=100, max_interval_ticks=1000)
    sched = SnapshotScheduler(policy=policy)
    sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)
    # A busy check past min does NOT reset the clock -- elapsed keeps
    # accumulating from the original baseline, not this failed check.
    sched.due(tick=150, recent_loads=BUSY, capacity=CAPACITY)
    due_at_original_max = sched.due(tick=1000, recent_loads=BUSY, capacity=CAPACITY)
    check(
        "due: a non-firing check never resets the idle clock -- max_interval is still measured from the real baseline",
        due_at_original_max is True,
    )


def check_full_incremental_cadence():
    policy = SnapshotPolicy(min_interval_ticks=10, max_interval_ticks=10, full_snapshot_every=3)
    sched = SnapshotScheduler(policy=policy)
    kinds = [sched.plan() for _ in range(7)]
    expected = [
        SnapshotKind.FULL, SnapshotKind.INCREMENTAL, SnapshotKind.INCREMENTAL,
        SnapshotKind.FULL, SnapshotKind.INCREMENTAL, SnapshotKind.INCREMENTAL,
        SnapshotKind.FULL,
    ]
    check("plan: every Nth DUE snapshot is FULL, the rest INCREMENTAL", kinds == expected, str(kinds))


def check_end_to_end_due_then_plan():
    policy = SnapshotPolicy(min_interval_ticks=50, max_interval_ticks=500, full_snapshot_every=2)
    sched = SnapshotScheduler(policy=policy)
    sched.due(tick=0, recent_loads=QUIET, capacity=CAPACITY)  # baseline
    first_due = sched.due(tick=50, recent_loads=QUIET, capacity=CAPACITY)
    first_kind = sched.plan() if first_due else None
    second_due = sched.due(tick=100, recent_loads=QUIET, capacity=CAPACITY)
    second_kind = sched.plan() if second_due else None
    check("end-to-end: first genuinely due snapshot is FULL", first_due and first_kind is SnapshotKind.FULL)
    check("end-to-end: second genuinely due snapshot is INCREMENTAL", second_due and second_kind is SnapshotKind.INCREMENTAL)


def check_batch_size_scales_with_storage_speed():
    slow = batch_size_for_storage(storage_write_mb_s=10.0, target_write_latency_s=0.1, min_batch_bytes=4096, max_batch_bytes=100_000_000)
    fast = batch_size_for_storage(storage_write_mb_s=500.0, target_write_latency_s=0.1, min_batch_bytes=4096, max_batch_bytes=100_000_000)
    check("batch_size_for_storage: faster measured storage earns a genuinely larger batch", fast > slow, f"slow={slow} fast={fast}")


def check_batch_size_falls_back_conservative_when_unmeasured():
    unmeasured = batch_size_for_storage(storage_write_mb_s=None, target_write_latency_s=0.1, min_batch_bytes=4096, max_batch_bytes=100_000_000)
    zero = batch_size_for_storage(storage_write_mb_s=0.0, target_write_latency_s=0.1, min_batch_bytes=4096, max_batch_bytes=100_000_000)
    check("batch_size_for_storage: unmeasured storage falls back to the conservative floor, not a guess", unmeasured == 4096)
    check("batch_size_for_storage: zero/invalid measured speed also falls back to the floor", zero == 4096)


def check_batch_size_clamped_to_max():
    huge = batch_size_for_storage(storage_write_mb_s=10_000.0, target_write_latency_s=10.0, min_batch_bytes=4096, max_batch_bytes=1_000_000)
    check("batch_size_for_storage: never exceeds max_batch_bytes even for very fast storage", huge == 1_000_000)


def check_register_snapshot_tunables_mirrors_real_bounds():
    policy = SnapshotPolicy(min_interval_ticks=200, max_interval_ticks=2000)
    registry = TunableRegistry()
    register_snapshot_tunables(registry, policy)
    check(
        "B14.1/(B6.1): registered tunables mirror the real policy bounds",
        registry.get("snapshot_min_interval_ticks").value == 200.0 and registry.get("snapshot_max_interval_ticks").value == 2000.0,
    )
    from hearthmind.simulation.tuning import SafetyClass
    check(
        "B14.1: snapshot cadence tunables are SAFE (cadence never changes simulation outcomes, only when we persist)",
        registry.get("snapshot_min_interval_ticks").safety_class is SafetyClass.SAFE
        and registry.get("snapshot_max_interval_ticks").safety_class is SafetyClass.SAFE,
    )


def main():
    check_invalid_policy_rejected()
    check_first_check_never_fires()
    check_not_due_before_min_even_if_quiet()
    check_due_at_min_interval_when_quiet()
    check_not_due_at_min_interval_when_busy()
    check_forced_at_max_interval_even_if_busy()
    check_clock_resets_only_on_a_real_due_result()
    check_full_incremental_cadence()
    check_end_to_end_due_then_plan()
    check_batch_size_scales_with_storage_speed()
    check_batch_size_falls_back_conservative_when_unmeasured()
    check_batch_size_clamped_to_max()
    check_register_snapshot_tunables_mirrors_real_bounds()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
