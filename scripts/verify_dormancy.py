#!/usr/bin/env python3
"""Tier 5 B4 verification (dormancy).

Standalone verification script, not a unittest — same convention as
every other verify_*.py in this directory. Exercises `hearthmind.
simulation.dormancy.DormancyManager` directly; no real Hearthmind
entity has been migrated onto it yet (B4.2), so there is no live
engine state to soak-test — see the module's own docstring.

Checks 1-6 exercise the lifecycle state machine directly. Check 7 is
B4.4's chaos-testing technique: since no real subsystem exists yet to
point a real replay-hash chaos test at, this demonstrates the same
technique against a synthetic "accumulator" entity — random force-
sleep/wake sequences (many seeds) must still produce the exact same
final value as a no-dormancy baseline, proving B4.3's lossless-wake
catch-up integration actually holds, not just look plausible.
"""
from __future__ import annotations

import random
import sys

from hearthmind.simulation.dormancy import DormancyManager, DormancyState


def check_register_starts_active() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    assert mgr.state_of("a") is DormancyState.ACTIVE
    assert mgr.is_scheduled("a") is True


def check_sleep_dormant_unschedules() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    mgr.sleep("a", tick=5, target=DormancyState.DORMANT)
    assert mgr.state_of("a") is DormancyState.DORMANT
    assert mgr.is_scheduled("a") is False


def check_sleep_drowsy_stays_scheduled() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    mgr.sleep("a", tick=5, target=DormancyState.DROWSY)
    assert mgr.state_of("a") is DormancyState.DROWSY
    assert mgr.is_scheduled("a") is True  # "dormant = zero work," drowsy isn't dormant


def check_wake_returns_real_elapsed() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    mgr.sleep("a", tick=10, target=DormancyState.DORMANT)
    elapsed = mgr.wake("a", tick=37)
    assert elapsed == 27, elapsed
    assert mgr.state_of("a") is DormancyState.ACTIVE
    assert mgr.is_scheduled("a") is True


def check_wake_on_active_is_safe_noop() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    assert mgr.wake("a", tick=100) == 0
    assert mgr.state_of("a") is DormancyState.ACTIVE


def check_archived_symmetric_with_dormant() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    mgr.sleep("a", tick=3, target=DormancyState.ARCHIVED)
    assert mgr.is_scheduled("a") is False
    elapsed = mgr.wake("a", tick=50)
    assert elapsed == 47, elapsed


def check_double_sleep_preserves_original_clock() -> None:
    mgr = DormancyManager()
    mgr.register("a", tick=0)
    mgr.sleep("a", tick=10, target=DormancyState.DORMANT)
    mgr.sleep("a", tick=25, target=DormancyState.ARCHIVED)  # already unscheduled -- no-op
    elapsed = mgr.wake("a", tick=40)
    # If the second sleep() had reset the clock to 25, elapsed would be
    # 15, not 30 -- the original tick=10 anchor must be preserved.
    assert elapsed == 30, elapsed


def _run_baseline(ticks: int) -> int:
    return ticks


def _run_chaos(ticks: int, seed: int) -> int:
    rng = random.Random(seed)
    mgr = DormancyManager()
    mgr.register("acc", tick=0)
    value = 0
    for tick in range(1, ticks + 1):
        if mgr.is_scheduled("acc"):
            value += 1
        state = mgr.state_of("acc")
        if state is DormancyState.ACTIVE and rng.random() < 0.1:
            mgr.sleep("acc", tick, target=DormancyState.DORMANT)
        elif state is DormancyState.DORMANT and rng.random() < 0.2:
            value += mgr.wake("acc", tick)  # deterministic elapsed-time catch-up
    value += mgr.wake("acc", ticks)  # force-flush any still-pending dormancy
    return value


def check_chaos_dormancy_matches_no_dormancy_baseline() -> None:
    ticks = 500
    baseline = _run_baseline(ticks)
    for seed in range(20):
        chaos_value = _run_chaos(ticks, seed)
        assert chaos_value == baseline, (seed, chaos_value, baseline)


def main() -> int:
    checks = [
        check_register_starts_active,
        check_sleep_dormant_unschedules,
        check_sleep_drowsy_stays_scheduled,
        check_wake_returns_real_elapsed,
        check_wake_on_active_is_safe_noop,
        check_archived_symmetric_with_dormant,
        check_double_sleep_preserves_original_clock,
        check_chaos_dormancy_matches_no_dormancy_baseline,
    ]
    for check in checks:
        check()
        print(f"OK: {check.__name__}")
    print(f"Dormancy verification OK — {len(checks)} checks passed (chaos test: 20 seeds x {500} ticks).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
