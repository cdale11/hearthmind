#!/usr/bin/env python3
"""Tier 5 B7 (Hardware model) wired to a real control point.

Explicit user follow-up ("B7"), continuing the Part-B closing sequence
(B6 v1.34.198, B2 v1.34.199, B3 v1.34.200). B7.1-B7.4 (`simulation/
hardware_profile.py`: `HostProbe`/`MachineProfile`/`select_strategy`/
`GoodCitizenPolicy`) were real, verified pure functions since
v1.34.173, but had zero real call sites anywhere in `engine.py` or
`server.py` -- B7.4's own docstring named exactly this gap: "'lower
priority for background work' itself needs a real scheduler to lower
priority IN -- that's B2's job... `should_back_off` is the input
signal such a scheduler would consult, not the mechanism."

Now that B6's `_maybe_tune_llm_concurrency` is a real, live scheduler
(v1.34.198), it is exactly that consumer. A real `HostProbe.sample()`
reading (storage micro-benchmark skipped -- irrelevant to citizenship,
needless disk I/O on a check that runs at most once a day) is taken
every non-skipped call; `GoodCitizenPolicy.should_back_off(probe)`
(BALANCED aggressiveness) acts as a DOWNWARD-ONLY veto layered on top
of the existing latency-driven `BangBangController` decision -- it can
force a step down (or cancel an unwanted step up) that latency alone
wouldn't have produced, but it never blocks or reverses a decrease
latency itself already decided.

This script proves, standalone (no unittest): a healthy host with a
latency reading inside the controller's own hysteresis dead zone stays
a genuine no-op (nothing logged); a pressured host under otherwise-
identical conditions forces a real, logged one-step decrease
(`host_pressure_veto: True`); a pressured host doesn't prevent a
latency-driven decrease that was already happening (no double-step);
a pressured host cancels (not amplifies) an unwanted latency-driven
increase, landing back at the starting value with no logged change
(a real semantic choice, not a bug -- see the module's own "only log
real changes" discipline); and the real semaphore/backpressure state
stays consistent with whatever the final value actually is.
"""
import asyncio
import sys
import tempfile
from unittest import mock

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import ADAPTIVE_CONCURRENCY_TARGET_MS, BACKPRESSURE_BACKLOG_PER_SLOT, SimulationEngine
from hearthmind.simulation.hardware_profile import HostProbe

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, llm_max_concurrent: int = 4) -> SimulationEngine:
    conn = connect(f"{tmpdir}/b7_citizenship.db")
    cfg = Config(
        db_path=f"{tmpdir}/b7_citizenship.db", llm_enabled=True, seed=1,
        initial_population=5, width=32, height=32, llm_max_concurrent=llm_max_concurrent,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def fill_latency(eng: SimulationEngine, ms: float, count: int = 30) -> None:
    eng._cognition_runner._latencies_ms.clear()
    for _ in range(count):
        eng._cognition_runner._latencies_ms.append(ms)
    eng._cognition_runner.calls_attempted = max(eng._cognition_runner.calls_attempted, count)


HEALTHY_PROBE = HostProbe(
    logical_cores=8, usable_cores=8, mem_total_mb=16000, mem_available_mb=8000,
    swap_used_mb=0, swap_total_mb=0, load_avg_1m=1.0, storage_write_mb_s=None,
    storage_read_mb_s=None, gpu_present=False, thermal_state="nominal", timestamp=0.0,
)
PRESSURED_PROBE = HostProbe(
    logical_cores=8, usable_cores=8, mem_total_mb=8192, mem_available_mb=500,
    swap_used_mb=200, swap_total_mb=1000, load_avg_1m=1.0, storage_write_mb_s=None,
    storage_read_mb_s=None, gpu_present=False, thermal_state="nominal", timestamp=0.0,
)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Healthy host + latency inside the dead zone: a genuine
        #    no-op, nothing logged.
        eng1 = make_engine(tmpdir)
        fill_latency(eng1, ADAPTIVE_CONCURRENCY_TARGET_MS)
        before1 = eng1._tuning_registry.get("llm_max_concurrent").value
        with mock.patch.object(HostProbe, "sample", return_value=HEALTHY_PROBE):
            eng1._maybe_tune_llm_concurrency()
        after1 = eng1._tuning_registry.get("llm_max_concurrent").value
        check("healthy host + dead-zone latency: true no-op", after1 == before1)
        check("healthy host + dead-zone latency: nothing logged", len(eng1._adaptive_tuning_log) == 0)

        # 2. Pressured host + latency inside the dead zone: the host
        #    veto ALONE forces a real, logged one-step decrease.
        eng2 = make_engine(tmpdir)
        fill_latency(eng2, ADAPTIVE_CONCURRENCY_TARGET_MS)
        before2 = eng2._tuning_registry.get("llm_max_concurrent").value
        with mock.patch.object(HostProbe, "sample", return_value=PRESSURED_PROBE):
            eng2._maybe_tune_llm_concurrency()
        after2 = eng2._tuning_registry.get("llm_max_concurrent").value
        check("pressured host + dead-zone latency: forces exactly one step down", after2 == before2 - 1)
        check(
            "pressured host + dead-zone latency: logged with host_pressure_veto=True",
            bool(eng2._adaptive_tuning_log) and eng2._adaptive_tuning_log[-1]["host_pressure_veto"] is True,
        )
        check(
            "the real backpressure limit reflects the vetoed value, not the pre-veto one",
            eng2._backpressure_limit == int(after2) * BACKPRESSURE_BACKLOG_PER_SLOT,
        )

        # 3. Pressured host doesn't block a latency-driven DECREASE
        #    already happening -- no double-step, still exactly one.
        #    (Polarity: raising concurrency plausibly RAISES latency
        #    toward the target, so latency far ABOVE target is what
        #    drives bang-bang to decrease concurrency -- the controller
        #    is already easing off before the host veto even applies.)
        eng3 = make_engine(tmpdir, llm_max_concurrent=4)
        fill_latency(eng3, ADAPTIVE_CONCURRENCY_TARGET_MS * 3)  # far above target -> bang-bang alone wants to decrease
        before3 = eng3._tuning_registry.get("llm_max_concurrent").value
        with mock.patch.object(HostProbe, "sample", return_value=PRESSURED_PROBE):
            eng3._maybe_tune_llm_concurrency()
        after3 = eng3._tuning_registry.get("llm_max_concurrent").value
        check(
            "pressured host doesn't double-step a latency-driven decrease already in progress",
            after3 == before3 - 1,
        )
        check(
            "a latency-driven decrease (not host-caused) is NOT flagged host_pressure_veto",
            eng3._adaptive_tuning_log[-1]["host_pressure_veto"] is False,
        )

        # 4. Pressured host CANCELS (doesn't amplify) an unwanted
        #    latency-driven increase -- lands back at the start, no
        #    logged change (a real design choice: the veto prevented a
        #    mistake, it isn't punitive beyond that). Latency far BELOW
        #    target is what drives bang-bang to increase concurrency.
        eng4 = make_engine(tmpdir, llm_max_concurrent=4)
        fill_latency(eng4, 0.0)  # far below target -> bang-bang alone wants to increase
        before4 = eng4._tuning_registry.get("llm_max_concurrent").value
        with mock.patch.object(HostProbe, "sample", return_value=PRESSURED_PROBE):
            eng4._maybe_tune_llm_concurrency()
        after4 = eng4._tuning_registry.get("llm_max_concurrent").value
        check("pressured host cancels an unwanted latency-driven increase", after4 == before4)
        check("a fully-cancelled increase logs nothing (net no-op)", len(eng4._adaptive_tuning_log) == 0)

        # 4b. "Cheap next tier intel" bonus, same batch: full_
        #     diagnostics() surfaces the real, live HostProbe reading
        #     just sampled by the call above -- not a stub.
        diag4 = eng4.full_diagnostics()
        host_probe_diag = diag4.get("host_probe")
        check("full_diagnostics() exposes a real host_probe reading after a real sample", host_probe_diag is not None)
        check(
            "the surfaced should_back_off matches the real policy's own verdict for the pressured probe",
            host_probe_diag is not None and host_probe_diag["should_back_off"] is True,
        )
        check(
            "the surfaced mem_available_mb matches the real probe's own value, not a fabricated one",
            host_probe_diag is not None and host_probe_diag["mem_available_mb"] == PRESSURED_PROBE.mem_available_mb,
        )

        # 4c. Before any real sample has happened, host_probe is an
        #     honest None, never a fabricated placeholder.
        eng4b = make_engine(tmpdir)
        check(
            "full_diagnostics() reports host_probe=None before any real sample has occurred",
            eng4b.full_diagnostics()["host_probe"] is None,
        )

        # 5. Disabled LLM: the whole method (including the new host
        #    probe) is skipped entirely -- no real HostProbe.sample()
        #    call at all when there's nothing to measure.
        conn5 = connect(f"{tmpdir}/b7_disabled.db")
        cfg5 = Config(db_path=f"{tmpdir}/b7_disabled.db", llm_enabled=False, seed=2, initial_population=5, width=32, height=32)
        eng5 = SimulationEngine.load_or_create(conn5, cfg5)
        sample_called = False

        def _tracking_sample(*_a, **_kw):
            nonlocal sample_called
            sample_called = True
            return HEALTHY_PROBE

        with mock.patch.object(HostProbe, "sample", side_effect=_tracking_sample):
            eng5._maybe_tune_llm_concurrency()
        check("LLM-disabled engine never samples HostProbe at all", not sample_called)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
