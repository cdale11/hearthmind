#!/usr/bin/env python3
"""Standalone verification for hearthmind/simulation/hardware_profile.py
(B7 -- Hardware model, docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B).
Same convention as every sibling scripts/verify_*.py: no unittest, no
CI pipeline, run manually.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.hardware_profile import (
    Aggressiveness,
    GoodCitizenPolicy,
    HostProbe,
    MachineProfile,
    host_fingerprint,
    select_strategy,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_probe_sample_never_raises_and_has_sane_types():
    probe = HostProbe.sample()
    check("probe: logical_cores is a positive int or None", probe.logical_cores is None or probe.logical_cores > 0)
    check("probe: gpu_present is a bool", isinstance(probe.gpu_present, bool))
    check("probe: timestamp is set", probe.timestamp > 0)
    d = probe.to_dict()
    check("probe: to_dict includes every field", set(d.keys()) == set(probe.__dataclass_fields__.keys()))


def check_probe_without_storage_bench_skips_it():
    probe = HostProbe.sample(run_storage_bench=False)
    check(
        "probe: run_storage_bench=False leaves both storage fields None",
        probe.storage_write_mb_s is None and probe.storage_read_mb_s is None,
    )


def check_host_fingerprint_stable():
    a = host_fingerprint()
    b = host_fingerprint()
    check("host_fingerprint: stable across two calls on the same process", a == b, f"{a} vs {b}")
    check("host_fingerprint: reasonable length", len(a) == 16)


def check_machine_profile_ema():
    profile = MachineProfile(host_fingerprint="test-host")
    profile.record_llm_throughput(10.0)
    check("machine profile: first sample sets the value directly", profile.measured_llm_throughput_tokens_per_s == 10.0)
    profile.record_llm_throughput(20.0)
    v = profile.measured_llm_throughput_tokens_per_s
    check(
        "machine profile: EMA moves toward the new sample without jumping all the way there",
        10.0 < v < 20.0,
        f"v={v}",
    )
    for _ in range(50):
        profile.record_llm_throughput(20.0)
    check("machine profile: EMA converges to a sustained new value", abs(profile.measured_llm_throughput_tokens_per_s - 20.0) < 0.01)


def check_machine_profile_round_trip():
    profile = MachineProfile(host_fingerprint="abc123", sessions_recorded=3, optimal_worker_count=4)
    profile.record_llm_throughput(15.5)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "profile.json")
        profile.save(path)
        loaded = MachineProfile.load(path)
        check("machine profile: round-trip preserves fields", loaded.to_dict() == profile.to_dict())

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "profile.json")
        fresh = MachineProfile.load_or_create(path)
        check("machine profile: load_or_create makes a fresh profile when no file exists", fresh.sessions_recorded == 0)
        fresh.record_session()
        fresh.save(path)
        again = MachineProfile.load_or_create(path)
        check("machine profile: load_or_create loads the saved file on a second call", again.sessions_recorded == 1)

    import json
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "bad.json")
        with open(path, "w") as f:
            json.dump({"schema_version": 999, "host_fingerprint": "x"}, f)
        raised = False
        try:
            MachineProfile.load(path)
        except ValueError:
            raised = True
        check("machine profile: load rejects an unsupported schema_version", raised)


def _profile(**kwargs):
    return HostProbe(
        logical_cores=kwargs.get("logical_cores", 4),
        usable_cores=kwargs.get("usable_cores", kwargs.get("logical_cores", 4)),
        mem_total_mb=kwargs.get("mem_total_mb", 4096.0),
        mem_available_mb=kwargs.get("mem_available_mb", 2048.0),
        swap_used_mb=kwargs.get("swap_used_mb", 0.0),
        swap_total_mb=kwargs.get("swap_total_mb", 0.0),
        load_avg_1m=kwargs.get("load_avg_1m", 1.0),
        storage_write_mb_s=None,
        storage_read_mb_s=None,
        gpu_present=False,
        thermal_state=kwargs.get("thermal_state", "nominal"),
        timestamp=0.0,
    )


def check_select_strategy_scales_with_hardware():
    beefy = _profile(logical_cores=16, usable_cores=16, mem_total_mb=32768, mem_available_mb=20000, load_avg_1m=2.0)
    modest = _profile(logical_cores=2, usable_cores=2, mem_total_mb=2048, mem_available_mb=1000, load_avg_1m=0.5)
    beefy_strategy = select_strategy(beefy)
    modest_strategy = select_strategy(modest)
    check(
        "select_strategy: a many-core/high-RAM host gets more LLM concurrency than a modest one",
        beefy_strategy.llm_max_concurrent_hint > modest_strategy.llm_max_concurrent_hint,
        f"{beefy_strategy.llm_max_concurrent_hint} vs {modest_strategy.llm_max_concurrent_hint}",
    )
    check(
        "select_strategy: a many-core host gets more worker hints",
        beefy_strategy.worker_count_hint > modest_strategy.worker_count_hint,
    )
    check("select_strategy: beefy host gets a large cache hint", beefy_strategy.cache_size_hint == "large")
    check("select_strategy: modest host gets a small cache hint", modest_strategy.cache_size_hint == "small")


def check_select_strategy_reacts_to_pressure():
    healthy = _profile(mem_total_mb=8192, mem_available_mb=6000, swap_used_mb=0.0, thermal_state="nominal")
    pressured = _profile(mem_total_mb=8192, mem_available_mb=800, swap_used_mb=500.0, thermal_state="nominal")
    healthy_strategy = select_strategy(healthy)
    pressured_strategy = select_strategy(pressured)
    check(
        "select_strategy: memory/swap pressure lowers LLM concurrency vs. a healthy read",
        pressured_strategy.llm_max_concurrent_hint <= healthy_strategy.llm_max_concurrent_hint,
    )
    check("select_strategy: pressure raises dormancy aggressiveness", pressured_strategy.dormancy_aggressiveness == "high")

    throttled = _profile(mem_total_mb=8192, mem_available_mb=6000, thermal_state="throttled")
    throttled_strategy = select_strategy(throttled)
    check("select_strategy: thermal throttling also raises dormancy aggressiveness", throttled_strategy.dormancy_aggressiveness == "high")


def check_select_strategy_honours_profile_worker_override():
    probe = _profile()
    profile = MachineProfile(host_fingerprint="x", optimal_worker_count=7)
    strategy = select_strategy(probe, profile=profile)
    check("select_strategy: a machine profile's measured worker count overrides the generic hint", strategy.worker_count_hint == 7)


def check_good_citizen_policy_backs_off_under_pressure():
    policy_conservative = GoodCitizenPolicy(aggressiveness=Aggressiveness.CONSERVATIVE)
    policy_aggressive = GoodCitizenPolicy(aggressiveness=Aggressiveness.AGGRESSIVE)

    tight_mem = _profile(mem_total_mb=8192, mem_available_mb=1000)  # ~12% available
    check(
        "good citizen: conservative policy backs off at moderate memory pressure",
        policy_conservative.should_back_off(tight_mem),
    )
    check(
        "good citizen: aggressive policy tolerates the same pressure without backing off",
        not policy_aggressive.should_back_off(tight_mem),
    )

    plenty = _profile(mem_total_mb=8192, mem_available_mb=6000, load_avg_1m=0.5)
    check("good citizen: no policy backs off on a genuinely healthy read", not policy_conservative.should_back_off(plenty))

    swapping = _profile(mem_total_mb=8192, mem_available_mb=6000, swap_used_mb=100.0)
    check("good citizen: conservative policy backs off on ANY swap use", policy_conservative.should_back_off(swapping))
    check("good citizen: aggressive policy tolerates light swap use", not policy_aggressive.should_back_off(swapping))

    high_load = _profile(logical_cores=4, usable_cores=4, mem_total_mb=8192, mem_available_mb=6000, load_avg_1m=20.0)
    check("good citizen: extreme external load triggers back-off even at aggressive setting", policy_aggressive.should_back_off(high_load))

    throttled = _profile(mem_total_mb=8192, mem_available_mb=6000, thermal_state="throttled")
    check("good citizen: thermal throttling always triggers back-off", policy_aggressive.should_back_off(throttled))


def main():
    check_probe_sample_never_raises_and_has_sane_types()
    check_probe_without_storage_bench_skips_it()
    check_host_fingerprint_stable()
    check_machine_profile_ema()
    check_machine_profile_round_trip()
    check_select_strategy_scales_with_hardware()
    check_select_strategy_reacts_to_pressure()
    check_select_strategy_honours_profile_worker_override()
    check_good_citizen_policy_backs_off_under_pressure()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
