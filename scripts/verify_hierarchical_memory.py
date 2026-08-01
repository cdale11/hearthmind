#!/usr/bin/env python3
"""Standalone verification for B11 (Hierarchical memory,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.hierarchical_memory import (
    MemoryTierManager,
    Tier,
    TransparentHandle,
    pressure_response,
)
from hearthmind.simulation.hardware_profile import Aggressiveness, GoodCitizenPolicy, HostProbe

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_register_and_default_tier():
    mgr = MemoryTierManager()
    check("tier_of: an unregistered key defaults to hot", mgr.tier_of("unknown") == Tier.HOT)
    mgr.register("k1", tick=0, tier=Tier.WARM)
    check("register: sets the requested initial tier", mgr.tier_of("k1") == Tier.WARM)


def check_touch_promotes_and_resets_clock():
    mgr = MemoryTierManager()
    mgr.register("k1", tick=0, tier=Tier.COLD)
    mgr.touch("k1", tick=50)
    check("touch: promotes back to hot regardless of prior tier", mgr.tier_of("k1") == Tier.HOT)
    check("touch: resets the idle clock", mgr.tracker.elapsed_since("k1", tick=50) == 0)


THRESHOLDS = {Tier.HOT: 100, Tier.WARM: 200, Tier.COLD: 300}


def check_demote_stale_moves_one_tier_at_a_time():
    mgr = MemoryTierManager()
    mgr.register("k1", tick=0, tier=Tier.HOT)

    migrations = mgr.demote_stale(tick=50, thresholds=THRESHOLDS)
    check("demote_stale: no migration before the threshold is reached", migrations == [] and mgr.tier_of("k1") == Tier.HOT)

    migrations2 = mgr.demote_stale(tick=100, thresholds=THRESHOLDS)
    check("demote_stale: exactly one step down once the threshold is reached", migrations2 == [("k1", Tier.HOT, Tier.WARM)], str(migrations2))
    check("demote_stale: tier actually updated", mgr.tier_of("k1") == Tier.WARM)

    # It should NOT jump straight to cold just because a huge amount of
    # time has passed since the ORIGINAL registration -- demote_stale
    # resets the idle baseline on every real migration (it calls
    # mark_run internally via the tracker), so the next demotion is
    # measured from THIS migration, not from tick 0.
    migrations3 = mgr.demote_stale(tick=105, thresholds=THRESHOLDS)
    check("demote_stale: no further migration immediately after the last one (idle clock reset)", migrations3 == [])


def check_demote_stale_full_ladder_and_archive_floor():
    mgr = MemoryTierManager()
    mgr.register("k1", tick=0, tier=Tier.HOT)

    tick = 0
    # HOT -> WARM
    tick += THRESHOLDS[Tier.HOT]
    mgr.demote_stale(tick=tick, thresholds=THRESHOLDS)
    check("ladder: reached warm", mgr.tier_of("k1") == Tier.WARM)

    # WARM -> COLD
    tick += THRESHOLDS[Tier.WARM]
    mgr.demote_stale(tick=tick, thresholds=THRESHOLDS)
    check("ladder: reached cold", mgr.tier_of("k1") == Tier.COLD)

    # COLD -> ARCHIVE
    tick += THRESHOLDS[Tier.COLD]
    mgr.demote_stale(tick=tick, thresholds=THRESHOLDS)
    check("ladder: reached archive", mgr.tier_of("k1") == Tier.ARCHIVE)

    # ARCHIVE has no threshold entry -- must never demote further, even
    # given an enormous amount of additional idle time.
    tick += 1_000_000
    migrations = mgr.demote_stale(tick=tick, thresholds=THRESHOLDS)
    check("ladder: archive is a real floor -- no further demotion, ever", migrations == [] and mgr.tier_of("k1") == Tier.ARCHIVE)


def check_regularly_touched_key_never_demotes():
    mgr = MemoryTierManager()
    mgr.register("k1", tick=0, tier=Tier.HOT)
    tick = 0
    for _ in range(20):
        tick += 50  # always well under THRESHOLDS[Tier.HOT] == 100
        mgr.touch("k1", tick=tick)
        mgr.demote_stale(tick=tick, thresholds=THRESHOLDS)
    check(
        "access-driven migration: a key touched regularly (below every threshold) is never demoted",
        mgr.tier_of("k1") == Tier.HOT,
    )


def check_transparent_handle_faults_in_and_promotes():
    mgr = MemoryTierManager()
    mgr.register("k1", tick=0, tier=Tier.COLD)
    fetch_log = []

    def load_fn(key, tier):
        fetch_log.append((key, tier))
        return f"value-for-{key}"

    handle = TransparentHandle(manager=mgr, load_fn=load_fn)
    value = handle.get("k1", tick=500)

    check("transparent handle: returns the loaded value", value == "value-for-k1")
    check("transparent handle: load_fn was told the REAL tier it faulted in from (cold)", fetch_log == [("k1", Tier.COLD)])
    check("transparent handle: a read promotes the key back to hot", mgr.tier_of("k1") == Tier.HOT)
    check("transparent handle: a read resets the idle clock", mgr.tracker.elapsed_since("k1", tick=500) == 0)

    # A second read of an already-hot key is indistinguishable to the
    # caller -- same call shape, no special-casing needed by gameplay
    # code (the whole point of B11.3).
    value2 = handle.get("k1", tick=550)
    check("transparent handle: reading an already-hot key works identically", value2 == "value-for-k1")


def check_pressure_response_uses_aggressive_thresholds_under_pressure():
    base = {Tier.HOT: 1000}
    aggressive = {Tier.HOT: 10}

    mgr_pressured = MemoryTierManager()
    mgr_pressured.register("k1", tick=0, tier=Tier.HOT)
    pressured_probe = HostProbe(
        logical_cores=4, usable_cores=4, mem_total_mb=8192, mem_available_mb=500,
        swap_used_mb=200.0, swap_total_mb=2000.0, load_avg_1m=1.0,
        storage_write_mb_s=None, storage_read_mb_s=None, gpu_present=False,
        thermal_state="nominal", timestamp=0.0,
    )
    conservative = GoodCitizenPolicy(aggressiveness=Aggressiveness.CONSERVATIVE)
    migrations = pressure_response(mgr_pressured, tick=50, base_thresholds=base, aggressive_thresholds=aggressive, policy=conservative, probe=pressured_probe)
    check(
        "pressure_response: under real memory pressure, the tighter threshold demotes a key the base threshold wouldn't have yet",
        len(migrations) == 1,
        str(migrations),
    )

    mgr_healthy = MemoryTierManager()
    mgr_healthy.register("k1", tick=0, tier=Tier.HOT)
    healthy_probe = HostProbe(
        logical_cores=4, usable_cores=4, mem_total_mb=8192, mem_available_mb=6000,
        swap_used_mb=0.0, swap_total_mb=2000.0, load_avg_1m=0.5,
        storage_write_mb_s=None, storage_read_mb_s=None, gpu_present=False,
        thermal_state="nominal", timestamp=0.0,
    )
    migrations2 = pressure_response(mgr_healthy, tick=50, base_thresholds=base, aggressive_thresholds=aggressive, policy=conservative, probe=healthy_probe)
    check(
        "pressure_response: a healthy read uses the base threshold, same key does NOT demote yet",
        migrations2 == [],
    )


def main():
    check_register_and_default_tier()
    check_touch_promotes_and_resets_clock()
    check_demote_stale_moves_one_tier_at_a_time()
    check_demote_stale_full_ladder_and_archive_floor()
    check_regularly_touched_key_never_demotes()
    check_transparent_handle_faults_in_and_promotes()
    check_pressure_response_uses_aggressive_thresholds_under_pressure()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
