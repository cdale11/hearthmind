#!/usr/bin/env python3
"""Tier 5 B8 (Predictive scheduling) wired to a real control point, plus
closing B7.2/B7.3's own flagged gaps in the same batch.

Explicit user follow-up: "B8 and MachineProfile persistence and
select_strategy's output still have no real call site — flagged for
later" — continuing the Part-B closing sequence (B6 v1.34.198, B2
v1.34.199, B3 v1.34.200, B7 v1.34.201). B8.1-B8.4 (`simulation/
forecasting.py`) and B7.2/B7.3 (`simulation/hardware_profile.py`) were
real, verified pure functions/dataclasses with zero real call sites —
this closes the three flagged pieces named in the instruction.

Scope, stated honestly: B8.1 (`WorkloadForecaster`, a real MLP that
needs training data from an archived run) and its two direct
consumers, B8.2 (`plan_reservation`) and B8.3 (`ForecastAccuracyTracker`
— scores a forecaster's OWN predictions against later-observed
outcomes), all depend on a real trained model existing first. Wiring
them honestly means training one, which needs a real recorder archive
this pass has no reason to fabricate — real future work, same "no
fine-tuning run itself is implemented" scope trim this project's own
FT items already used. What DOES wire cleanly, standalone, this pass:

- B7.2 `MachineProfile` persistence: `SimulationEngine.__init__` loads
  a real, host-fingerprinted profile from a file next to `Config.
  db_path` (or keeps one in-RAM only for `:memory:`), records a
  session, and `_maybe_refresh_machine_profile` (monthly) saves it back
  to disk after refining its storage-benchmark EMA from a real probe —
  it now genuinely survives a restart instead of resetting every
  session.
- B7.3 `select_strategy`'s output: `_maybe_tune_llm_concurrency`
  (already B6/B7.4's real control point) now also consults `select_
  strategy(probe, profile)` as a THIRD signal — a downward-only cap on
  top of the existing latency-driven step and host-pressure veto,
  logged with `strategy_cap_applied: True`.
- B8.4 `is_quiet_window`: gates `_maybe_refresh_machine_profile`'s own
  real disk I/O (the storage micro-benchmark) into a genuinely quiet
  LLM-backlog period, read from a real bounded history `_maybe_tune_
  llm_concurrency` samples daily — "schedule expensive maintenance...
  into predicted-quiet periods," B8.4's own stated purpose, applied to
  this exact kind of work.

This script proves, standalone (no unittest): the profile persists
across two independent `SimulationEngine` constructions against the
same real db path; a `:memory:` db path never touches disk and never
crashes; a corrupted profile file degrades to a fresh profile rather
than crashing startup; `select_strategy`'s hint genuinely caps a
would-be increase past what modest hardware supports, independent of
the host-pressure veto; a real-hardware probe's hint does NOT
needlessly clamp a healthy step; the daily backlog sample fires even
when the LLM is disabled or under-evidenced (the two cases `_maybe_
tune_llm_concurrency` itself skips); `_maybe_refresh_machine_profile`
only runs its real storage benchmark during a genuinely quiet window,
never during a busy one, and never off a non-month_end tick; and
`full_diagnostics()` surfaces real profile/strategy state, honestly
`None` before any real reading exists.
"""
import asyncio
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine, _load_or_create_machine_profile, _machine_profile_path_for
from hearthmind.simulation.hardware_profile import HostProbe, host_fingerprint

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, db_name: str = "b8.db", llm_max_concurrent: int = 4, llm_enabled: bool = True) -> SimulationEngine:
    db_path = f"{tmpdir}/{db_name}" if db_name != ":memory:" else ":memory:"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=llm_enabled, seed=1,
        initial_population=5, width=32, height=32, llm_max_concurrent=llm_max_concurrent,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def refresh_machine_profile(eng: SimulationEngine, events: list[str]) -> None:
    """Roadmap Phase 3, H1 "per-domain budgets": `_maybe_refresh_
    machine_profile` now only SUBMITS its own real bid into `self.
    _machine_workspace` once its own real gate (month_end + a genuinely
    quiet backlog window) clears -- the actual storage-benchmark work
    only runs once `_maybe_resolve_machine_domain` arbitrates the
    cycle, same shared resolution point `_maybe_advance_escalation_
    ladder`'s own bid now goes through too. A real production month_end
    tick always ALSO crosses a real day boundary (confirmed elsewhere
    in this codebase -- a month boundary is a day boundary), so `events`
    must carry BOTH for this helper to reproduce a genuine production
    cycle, not just `["month_end"]` alone."""
    eng._maybe_refresh_machine_profile(events)
    eng._maybe_resolve_machine_domain(events)


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
MODEST_PROBE = HostProbe(
    logical_cores=2, usable_cores=2, mem_total_mb=2000, mem_available_mb=1000,
    swap_used_mb=0, swap_total_mb=0, load_avg_1m=0.5, storage_write_mb_s=None,
    storage_read_mb_s=None, gpu_present=False, thermal_state="nominal", timestamp=0.0,
)
BENCHMARK_PROBE = HostProbe(
    logical_cores=8, usable_cores=8, mem_total_mb=16000, mem_available_mb=8000,
    swap_used_mb=0, swap_total_mb=0, load_avg_1m=1.0, storage_write_mb_s=250.0,
    storage_read_mb_s=500.0, gpu_present=False, thermal_state="nominal", timestamp=0.0,
)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. B7.2 persistence: two independent engines against the SAME
        #    real db path -- the second one loads what the first saved.
        eng_a = make_engine(tmpdir, db_name="persist.db")
        check(
            "a fresh world's profile starts with no storage benchmark yet",
            eng_a._machine_profile.storage_write_mb_s is None,
        )
        for _ in range(40):
            eng_a._recent_llm_backlog_samples.append(0.0)  # a quiet history
        with mock.patch.object(HostProbe, "sample", return_value=BENCHMARK_PROBE):
            refresh_machine_profile(eng_a, ["month_end", "day_end"])
        check(
            "a real quiet-window refresh records the real storage benchmark",
            eng_a._machine_profile.storage_write_mb_s == BENCHMARK_PROBE.storage_write_mb_s,
        )
        profile_path = eng_a._machine_profile_path
        check("the profile path is a real file next to db_path", profile_path is not None and os.path.isfile(profile_path))

        eng_b = make_engine(tmpdir, db_name="persist.db")
        check(
            "a second engine against the same db_path loads the FIRST engine's saved profile",
            eng_b._machine_profile.storage_write_mb_s == BENCHMARK_PROBE.storage_write_mb_s,
        )
        check(
            "loading an existing profile does not reset sessions_recorded",
            eng_b._machine_profile.sessions_recorded == 2,  # eng_a's session + eng_b's own
        )

        # 2. :memory: db_path never touches disk, never crashes.
        eng_mem = make_engine(tmpdir, db_name=":memory:")
        check("an in-memory world's profile path is None", eng_mem._machine_profile_path is None)
        for _ in range(40):
            eng_mem._recent_llm_backlog_samples.append(0.0)
        with mock.patch.object(HostProbe, "sample", return_value=BENCHMARK_PROBE):
            refresh_machine_profile(eng_mem, ["month_end", "day_end"])  # must not raise
        check(
            "an in-memory world still refines its in-RAM profile from a real benchmark",
            eng_mem._machine_profile.storage_write_mb_s == BENCHMARK_PROBE.storage_write_mb_s,
        )

        # 3. A corrupted profile file degrades to a fresh profile
        #    rather than crashing engine construction.
        corrupt_db = f"{tmpdir}/corrupt.db"
        corrupt_profile_path = _machine_profile_path_for(corrupt_db)
        os.makedirs(os.path.dirname(corrupt_profile_path), exist_ok=True)
        with open(corrupt_profile_path, "w") as f:
            f.write("{not valid json")
        eng_corrupt = make_engine(tmpdir, db_name="corrupt.db")
        check(
            "a corrupted profile file never crashes startup -- falls back to a fresh profile",
            eng_corrupt._machine_profile.host_fingerprint == host_fingerprint(),
        )

        # 3b. Direct helper checks (the same fallback, exercised without
        #     going through a full engine construction).
        check(
            "_load_or_create_machine_profile degrades an unsupported schema_version, not raises",
            _load_or_create_machine_profile(_write_bad_schema(tmpdir)).host_fingerprint == host_fingerprint(),
        )
        check(
            "_machine_profile_path_for(':memory:') is honestly None",
            _machine_profile_path_for(":memory:") is None,
        )

        # 4. B7.3 select_strategy's real cap: modest hardware limits a
        #    would-be latency-driven INCREASE to its own hint, entirely
        #    independent of the host-pressure veto (MODEST_PROBE reports
        #    no memory/swap/thermal pressure at all).
        eng_cap = make_engine(tmpdir, db_name="cap.db", llm_max_concurrent=4)
        fill_latency(eng_cap, 0.0)  # far below target -> bang-bang alone wants to increase
        before_cap = eng_cap._tuning_registry.get("llm_max_concurrent").value
        with mock.patch.object(HostProbe, "sample", return_value=MODEST_PROBE):
            eng_cap._maybe_tune_llm_concurrency()
        after_cap = eng_cap._tuning_registry.get("llm_max_concurrent").value
        check(
            "modest hardware's select_strategy hint caps a latency-driven increase",
            after_cap == 1 and after_cap < before_cap + 1,
        )
        check(
            "the cap is logged as strategy_cap_applied, not a host-pressure veto",
            eng_cap._adaptive_tuning_log[-1]["strategy_cap_applied"] is True
            and eng_cap._adaptive_tuning_log[-1]["host_pressure_veto"] is False,
        )
        check(
            "the real semaphore/backpressure state reflects the capped value",
            eng_cap._cognition_runner.max_concurrent == 1,
        )

        # 5. A real-hardware probe's hint does NOT needlessly clamp an
        #    ordinary healthy step -- the cap is a real ceiling, not a
        #    constant tax on every change.
        eng_healthy = make_engine(tmpdir, db_name="healthy.db", llm_max_concurrent=2)
        fill_latency(eng_healthy, 0.0)  # -> wants to increase from 2 to 3
        with mock.patch.object(HostProbe, "sample", return_value=HEALTHY_PROBE):
            eng_healthy._maybe_tune_llm_concurrency()
        after_healthy = eng_healthy._tuning_registry.get("llm_max_concurrent").value
        check(
            "healthy hardware's hint (3) does not clamp a step that stays within it",
            after_healthy == 3 and eng_healthy._adaptive_tuning_log[-1]["strategy_cap_applied"] is False,
        )

        # 6. B8.4's real control point: the daily backlog sample fires
        #    even when the LLM is disabled or under-evidenced -- the two
        #    cases the tuning check itself skips.
        eng_disabled = make_engine(tmpdir, db_name="disabled.db", llm_enabled=False)
        check("a disabled engine starts with an empty backlog history", len(eng_disabled._recent_llm_backlog_samples) == 0)
        eng_disabled._maybe_tune_llm_concurrency()
        check(
            "a disabled engine still records a real backlog sample despite skipping tuning entirely",
            len(eng_disabled._recent_llm_backlog_samples) == 1,
        )

        eng_sparse = make_engine(tmpdir, db_name="sparse.db")
        eng_sparse._cognition_runner.calls_attempted = 1  # below ADAPTIVE_CONCURRENCY_MIN_EVIDENCE
        with mock.patch.object(HostProbe, "sample", return_value=HEALTHY_PROBE):
            eng_sparse._maybe_tune_llm_concurrency()
        check(
            "an under-evidenced engine still records a real backlog sample despite skipping tuning",
            len(eng_sparse._recent_llm_backlog_samples) == 1,
        )

        # 7. _maybe_refresh_machine_profile: only runs its real
        #    benchmark during a genuinely quiet window, never a busy
        #    one, and never off a non-month_end tick.
        eng_gate = make_engine(tmpdir, db_name="gate.db")
        bench_calls = []

        def _tracking_sample(**kw):
            bench_calls.append(kw)
            return BENCHMARK_PROBE

        with mock.patch.object(HostProbe, "sample", side_effect=_tracking_sample):
            eng_gate._maybe_refresh_machine_profile([])  # not month_end
        check("a non-month_end tick never samples for the profile refresh", bench_calls == [])

        for _ in range(40):
            eng_gate._recent_llm_backlog_samples.append(1000.0)  # a genuinely busy history
        with mock.patch.object(HostProbe, "sample", side_effect=_tracking_sample):
            eng_gate._maybe_refresh_machine_profile(["month_end"])
        check("a busy backlog history skips the real storage benchmark entirely", bench_calls == [])
        check(
            "the profile is genuinely untouched when the busy-window refresh is skipped",
            eng_gate._machine_profile.storage_write_mb_s is None,
        )

        eng_gate._recent_llm_backlog_samples.clear()
        for _ in range(40):
            eng_gate._recent_llm_backlog_samples.append(0.0)  # now genuinely quiet
        with mock.patch.object(HostProbe, "sample", side_effect=_tracking_sample):
            refresh_machine_profile(eng_gate, ["month_end", "day_end"])
        check("a quiet-window month_end tick runs exactly one real storage benchmark", len(bench_calls) == 1)
        check(
            "that real benchmark call asked for the actual storage micro-benchmark, not a cheap probe",
            bench_calls[0].get("run_storage_bench") is True,
        )

        # 8. full_diagnostics() surfaces real profile/strategy state,
        #    honestly None before any real reading exists.
        eng_diag = make_engine(tmpdir, db_name="diag.db")
        diag_before = eng_diag.full_diagnostics()["machine_profile"]
        check(
            "full_diagnostics() reports last_strategy=None before any real _maybe_tune_llm_concurrency call",
            diag_before["last_strategy"] is None,
        )
        check("full_diagnostics() reports the real host_fingerprint", diag_before["host_fingerprint"] == host_fingerprint())
        fill_latency(eng_diag, 0.0)
        with mock.patch.object(HostProbe, "sample", return_value=HEALTHY_PROBE):
            eng_diag._maybe_tune_llm_concurrency()
        diag_after = eng_diag.full_diagnostics()["machine_profile"]
        check(
            "full_diagnostics() reflects the real select_strategy verdict after a real call",
            diag_after["last_strategy"] is not None and diag_after["last_strategy"]["llm_max_concurrent_hint"] == 3,
        )
        check(
            "full_diagnostics() reports the real 'is this a quiet window' verdict",
            diag_after["recent_llm_backlog_is_quiet_window"] in (True, False),
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


def _write_bad_schema(tmpdir: str) -> str:
    path = f"{tmpdir}/bad_schema_profile.json"
    with open(path, "w") as f:
        json.dump({"schema_version": 999, "host_fingerprint": "whatever"}, f)
    return path


if __name__ == "__main__":
    asyncio.run(main())
