#!/usr/bin/env python3
"""Standalone verification for B9 (Hierarchical timescales,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.timescales import (
    TIMESCALE_ORDER,
    ElapsedTimeTracker,
    TimescaleGate,
    TimescaleLadder,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _default_ladder():
    # Matches the real project default calendar shape (real.365-day
    # year, 12 months, UK-style day counts) at a representative tick
    # rate -- same values `Config`'s own defaults use, hand-supplied
    # here so this module stays fully decoupled from Config.
    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return TimescaleLadder.from_calendar(
        sim_minutes_per_tick=5, minutes_per_day=1440, days_per_month=days_per_month
    )


def check_ladder_ordering_is_monotonic():
    ladder = _default_ladder()
    floors = [ladder.floor_for(name) for name in TIMESCALE_ORDER]
    check(
        "ladder: every rung's floor is >= the rung before it (monotonically slower)",
        all(floors[i] <= floors[i + 1] for i in range(len(floors) - 1)),
        str(floors),
    )
    check("ladder: tick floor is always exactly 1", ladder.floor_for("tick") == 1)
    check("ladder: an unrecognized name degrades to floor 1, not a crash", ladder.floor_for("nonsense") == 1)


def check_ladder_derives_a_real_day_from_the_calendar():
    ladder = _default_ladder()
    # 1440 minutes/day at 5 sim-minutes/tick -> 288 ticks/day, exactly.
    check("ladder: day floor matches hand-computed calendar math", ladder.floor_for("day") == 288, str(ladder.floor_for("day")))
    check("ladder: week floor is exactly 7 real days", ladder.floor_for("week") == 288 * 7)

    faster_ladder = TimescaleLadder.from_calendar(
        sim_minutes_per_tick=1, minutes_per_day=1440, days_per_month=[30] * 12
    )
    check(
        "ladder: a faster tick rate produces a LARGER tick-count floor for the same calendar day",
        faster_ladder.floor_for("day") > ladder.floor_for("day"),
        f"{faster_ladder.floor_for('day')} vs {ladder.floor_for('day')}",
    )


def check_rank_and_is_slower_than():
    ladder = _default_ladder()
    check("ladder: year ranks below (slower than) tick", ladder.is_slower_than("year", "tick"))
    check("ladder: tick is never slower than year", not ladder.is_slower_than("tick", "year"))
    check("ladder: a timescale is never slower than itself", not ladder.is_slower_than("month", "month"))


def check_enforce_clamps_a_too_fast_interval():
    ladder = _default_ladder()
    day_floor = ladder.floor_for("day")

    enforced, clamped = ladder.enforce("day", requested_interval=1)
    check("enforce: a per-tick request against a 'day' timescale is clamped up to the real floor", enforced == day_floor and clamped)

    enforced2, clamped2 = ladder.enforce("day", requested_interval=day_floor * 2)
    check("enforce: a request already at or above the floor is left unchanged", enforced2 == day_floor * 2 and not clamped2)

    enforced3, clamped3 = ladder.enforce("tick", requested_interval=1)
    check("enforce: a 'tick' timescale never needs clamping at interval 1", enforced3 == 1 and not clamped3)


def check_elapsed_time_tracker_reports_real_deltas():
    tracker = ElapsedTimeTracker()
    check("tracker: no baseline yet for an unknown task", not tracker.has_baseline("t1"))
    check("tracker: elapsed_since with no baseline is None, not 0 (no real history to report)", tracker.elapsed_since("t1", 100) is None)

    tracker.mark_run("t1", 100)
    check("tracker: has_baseline true after a mark_run", tracker.has_baseline("t1"))
    check("tracker: elapsed_since is 0 immediately after marking at the same tick", tracker.elapsed_since("t1", 100) == 0)
    check("tracker: elapsed_since reports the real gap after ticks pass", tracker.elapsed_since("t1", 175) == 75)

    # A non-mutating peek must not itself move the baseline.
    tracker.elapsed_since("t1", 175)
    check("tracker: elapsed_since is non-mutating -- repeated peeks report the same value", tracker.elapsed_since("t1", 200) == 100)


def check_timescale_gate_end_to_end():
    ladder = _default_ladder()
    gate = TimescaleGate(ladder=ladder)
    day_floor = ladder.floor_for("day")

    due0, elapsed0 = gate.check("village_report", "day", tick=0)
    check("gate: a brand-new task is never due on its first observation (no real history yet)", not due0 and elapsed0 == 0)

    due1, elapsed1 = gate.check("village_report", "day", tick=day_floor // 2)
    check("gate: not yet due before its declared timescale's floor has elapsed", not due1)

    due2, elapsed2 = gate.check("village_report", "day", tick=day_floor)
    check("gate: due exactly once the real elapsed time reaches the floor", due2 and elapsed2 == day_floor, f"due={due2} elapsed={elapsed2}")

    due3, elapsed3 = gate.check("village_report", "day", tick=day_floor + 1)
    check("gate: not due again immediately after just firing", not due3)

    due4, elapsed4 = gate.check("village_report", "day", tick=day_floor * 2)
    check(
        "gate: elapsed is measured from the last REAL firing, not from the last no-op check",
        due4 and elapsed4 == day_floor,
        f"due={due4} elapsed={elapsed4}",
    )


def check_two_tasks_at_different_timescales_are_independent():
    ladder = _default_ladder()
    gate = TimescaleGate(ladder=ladder)
    day_floor = ladder.floor_for("day")
    month_floor = ladder.floor_for("month")

    gate.check("daily_job", "day", tick=0)
    gate.check("monthly_job", "month", tick=0)

    due_daily, _ = gate.check("daily_job", "day", tick=day_floor)
    due_monthly, _ = gate.check("monthly_job", "month", tick=day_floor)
    check("gate: a daily-scale task fires once a real day has elapsed", due_daily)
    check("gate: a monthly-scale task does NOT fire after only a day has elapsed", not due_monthly)

    due_monthly2, elapsed_monthly2 = gate.check("monthly_job", "month", tick=month_floor)
    check("gate: the monthly-scale task fires once a real month has elapsed", due_monthly2 and elapsed_monthly2 == month_floor)


def main():
    check_ladder_ordering_is_monotonic()
    check_ladder_derives_a_real_day_from_the_calendar()
    check_rank_and_is_slower_than()
    check_enforce_clamps_a_too_fast_interval()
    check_elapsed_time_tracker_reports_real_deltas()
    check_timescale_gate_end_to_end()
    check_two_tasks_at_different_timescales_are_independent()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
