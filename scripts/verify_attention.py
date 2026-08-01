#!/usr/bin/env python3
"""Standalone verification for B2.4 (Attention-follows-change,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.attention import (
    RegionActivityTracker,
    RegionAttentionGate,
    attention_interval,
)
from hearthmind.simulation.timescales import TimescaleLadder

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _ladder():
    return TimescaleLadder.from_calendar(sim_minutes_per_tick=5.0, minutes_per_day=1440, days_per_month=[30] * 12)


def check_activity_starts_at_zero():
    tracker = RegionActivityTracker(decay_half_life_ticks=100.0)
    check("activity_score: an untouched region reads exactly zero", tracker.activity_score((0, 0), tick=0) == 0.0)


def check_record_write_increases_activity():
    tracker = RegionActivityTracker(decay_half_life_ticks=100.0)
    tracker.record_write((0, 0), tick=0)
    check("record_write: a real write raises the region's activity above zero", tracker.activity_score((0, 0), tick=0) > 0.0)


def check_activity_decays_by_a_real_half_life():
    tracker = RegionActivityTracker(decay_half_life_ticks=100.0)
    tracker.record_write((0, 0), tick=0)
    initial = tracker.activity_score((0, 0), tick=0)
    after_one_half_life = tracker.activity_score((0, 0), tick=100)
    check(
        "activity_score: decays to ~half after exactly one half-life with no further writes",
        abs(after_one_half_life - initial * 0.5) < 1e-9,
        f"initial={initial} after={after_one_half_life}",
    )


def check_repeated_writes_accumulate():
    tracker = RegionActivityTracker(decay_half_life_ticks=1_000_000.0)  # effectively no decay over this short window
    for tick in range(5):
        tracker.record_write((0, 0), tick=tick)
    check("record_write: several real writes accumulate real activity, not just a flag", tracker.activity_score((0, 0), tick=5) > 1.0)


def check_regions_are_independent():
    tracker = RegionActivityTracker(decay_half_life_ticks=100.0)
    tracker.record_write((0, 0), tick=0)
    check("activity_score: a write to one region never bleeds into a different region", tracker.activity_score((1, 1), tick=0) == 0.0)


def check_attention_interval_never_below_floor():
    ladder = _ladder()
    floor = ladder.floor_for("day")
    for activity in (0.0, 1.0, 5.0, 100.0, 1_000_000.0):
        interval = attention_interval(ladder, "day", activity_score=activity, max_activity_for_full_compression=5.0)
        check(f"attention_interval: never violates the real timescale floor (activity={activity})", interval >= floor)


def check_attention_interval_at_zero_activity_is_the_ceiling():
    ladder = _ladder()
    floor = ladder.floor_for("day")
    interval = attention_interval(ladder, "day", activity_score=0.0, max_activity_for_full_compression=5.0, ceiling_multiplier=3.0)
    check("attention_interval: a genuinely quiet region (zero activity) stretches to the full configured ceiling", interval == floor * 3)


def check_attention_interval_at_max_activity_is_the_floor():
    ladder = _ladder()
    floor = ladder.floor_for("day")
    interval = attention_interval(ladder, "day", activity_score=5.0, max_activity_for_full_compression=5.0, ceiling_multiplier=3.0)
    check("attention_interval: activity at/above the compression cap compresses fully down to the real floor", interval == floor)


def check_attention_interval_monotonic_in_activity():
    ladder = _ladder()
    low = attention_interval(ladder, "day", activity_score=1.0, max_activity_for_full_compression=5.0)
    high = attention_interval(ladder, "day", activity_score=4.0, max_activity_for_full_compression=5.0)
    check("attention_interval: more activity never means a LONGER interval than less activity", high <= low, f"low={low} high={high}")


def check_gate_first_check_never_fires():
    ladder = _ladder()
    gate = RegionAttentionGate(ladder=ladder, activity=RegionActivityTracker(decay_half_life_ticks=1000.0))
    due, elapsed = gate.check((0, 0), "day", tick=0)
    check("RegionAttentionGate: the very first check establishes a baseline but never fires", due is False and elapsed == 0)


def check_gate_busy_region_checked_sooner_than_quiet_region():
    """The load-bearing check: 'attention follows change' -- a region
    with real recent writes gets re-checked at a genuinely SHORTER
    real interval than an equally-timescaled but quiet region."""
    ladder = _ladder()
    day_floor = ladder.floor_for("day")

    busy_activity = RegionActivityTracker(decay_half_life_ticks=1_000_000.0)
    quiet_activity = RegionActivityTracker(decay_half_life_ticks=1_000_000.0)
    for tick in range(6):
        busy_activity.record_write((0, 0), tick=tick)
    # quiet_activity gets no writes at all.

    busy_gate = RegionAttentionGate(ladder=ladder, activity=busy_activity, max_activity_for_full_compression=5.0)
    quiet_gate = RegionAttentionGate(ladder=ladder, activity=quiet_activity, max_activity_for_full_compression=5.0)

    busy_gate.check((0, 0), "day", tick=0)   # establish baseline
    quiet_gate.check((0, 0), "day", tick=0)  # establish baseline

    # Check right at the floor -- the busy region (fully compressed) should be due; the quiet one (stretched toward the ceiling) should not be.
    busy_due, _ = busy_gate.check((0, 0), "day", tick=day_floor)
    quiet_due, _ = quiet_gate.check((0, 0), "day", tick=day_floor)
    check("RegionAttentionGate: a busy region is due right at the real timescale floor", busy_due is True)
    check("RegionAttentionGate: an equally-timescaled QUIET region is NOT yet due at that same floor -- it earned a stretched interval", quiet_due is False)

    # The quiet region eventually becomes due once its own (longer, but still bounded) interval elapses.
    quiet_due_later, _ = quiet_gate.check((0, 0), "day", tick=day_floor * 3)
    check("RegionAttentionGate: the quiet region is still due eventually, bounded by the real ceiling", quiet_due_later is True)


def check_gate_never_fires_faster_than_the_real_floor_even_at_extreme_activity():
    ladder = _ladder()
    day_floor = ladder.floor_for("day")
    # A fast decay half-life (e.g. 1 tick) with writes every tick self-limits
    # to a low steady-state (geometric series 1 + 0.5 + 0.25 + ... = 2) --
    # not "extreme." A slow decay relative to the write rate is what
    # actually produces sustained, unboundedly-high activity here.
    activity = RegionActivityTracker(decay_half_life_ticks=1_000_000.0)
    for tick in range(1000):
        activity.record_write((0, 0), tick=tick)  # extreme, saturated activity
    gate = RegionAttentionGate(ladder=ladder, activity=activity, max_activity_for_full_compression=5.0)
    gate.check((0, 0), "day", tick=0)
    due_before_floor, _ = gate.check((0, 0), "day", tick=day_floor - 1)
    check(
        "RegionAttentionGate: even under extreme sustained activity, never fires before the real timescale floor is reached (B9's own guarantee holds)",
        due_before_floor is False,
    )
    due_at_floor, _ = gate.check((0, 0), "day", tick=day_floor)
    check("RegionAttentionGate: a maximally-active region fires exactly at the floor, not before", due_at_floor is True)


def main():
    check_activity_starts_at_zero()
    check_record_write_increases_activity()
    check_activity_decays_by_a_real_half_life()
    check_repeated_writes_accumulate()
    check_regions_are_independent()
    check_attention_interval_never_below_floor()
    check_attention_interval_at_zero_activity_is_the_ceiling()
    check_attention_interval_at_max_activity_is_the_floor()
    check_attention_interval_monotonic_in_activity()
    check_gate_first_check_never_fires()
    check_gate_busy_region_checked_sooner_than_quiet_region()
    check_gate_never_fires_faster_than_the_real_floor_even_at_extreme_activity()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
