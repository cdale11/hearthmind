#!/usr/bin/env python3
"""Explicit user directive ("ship phase 0"): the four cheap, already-
flagged Adaptive Runtime gaps named in `docs/ROADMAP-2026-07-
REMAINING.md`'s "Phase 0" — `select_strategy`'s `dormancy_
aggressiveness`/`cache_size_hint` hints wired to real consumers,
`TunableRegistry`'s three pacing constants made genuinely live instead
of metadata-only, and B5.3's runtime-diagnostics aggregate extended
from one scheduler to every real one. Real production-path checks
against a real `SimulationEngine`/`World`, no unittest, same
standalone-script convention as every sibling `verify_*.py`."""
from __future__ import annotations

import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import EMERGENCE_LOG_MAX_STORED, SimulationEngine
from hearthmind.simulation.hardware_profile import Strategy

CHECKS = 0
FAILURES: list[str] = []
_TMPDIR = tempfile.mkdtemp()
_COUNTER = 0


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def make_engine() -> SimulationEngine:
    global _COUNTER
    _COUNTER += 1
    db_path = f"{_TMPDIR}/phase0_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=707, initial_population=6, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


def strategy(dormancy: str = "normal", cache: str = "normal") -> Strategy:
    return Strategy(
        llm_max_concurrent_hint=2, worker_count_hint=4,
        cache_size_hint=cache, dormancy_aggressiveness=dormancy,
    )


def append_observation(eng: SimulationEngine, i: int) -> None:
    # `subsystem` varies per call (post-A2, docs/ROADMAP-2026-07-
    # REMAINING.md's A2/A3 pass): a static (subsystem, kind) key
    # repeated this many times would eventually get suppressed by A2's
    # real surprise gate before ever reaching the log at all -- this
    # helper is exercising B5.3's cache-size-scaled cap, not A2's own
    # gating, so each candidate needs its own distinct key to reliably
    # reach the log.
    eng._append_emergence(
        kind="opportunity", subsystem=f"test{i}", summary=f"observation {i}",
        pillars=["village"], magnitude=0.1,
    )


def main() -> int:
    # --- dormancy_aggressiveness -> _dormancy_idle_threshold ---
    eng = make_engine()
    check(
        "no strategy yet: dormancy threshold reproduces the flat base value",
        eng._dormancy_idle_threshold(3) == 3,
    )
    eng._last_strategy = strategy(dormancy="normal")
    check("normal aggressiveness: threshold unchanged", eng._dormancy_idle_threshold(3) == 3)
    eng._last_strategy = strategy(dormancy="high")
    check("high aggressiveness: threshold roughly halved", eng._dormancy_idle_threshold(3) == round(3 * 0.5))
    eng._last_strategy = strategy(dormancy="low")
    check("low aggressiveness: threshold roughly doubled", eng._dormancy_idle_threshold(3) == 6)
    eng._last_strategy = strategy(dormancy="high")
    check("high aggressiveness never floors below 1", eng._dormancy_idle_threshold(1) == 1)
    eng._last_strategy = strategy(dormancy="unknown-value")
    check("an unrecognized dormancy_aggressiveness value degrades to a 1.0x no-op", eng._dormancy_idle_threshold(3) == 3)

    # Real production-path proof: a "high" strategy sleeps an idle
    # institution faster than a "normal" one, through the actual
    # _update_institution_dormancy call path.
    eng_normal = make_engine()
    eng_high = make_engine()
    for e in (eng_normal, eng_high):
        settlement = e.world.settlements[0]
        settlement.name = "Testville"
        from hearthmind.settlement.institutions import Institution, InstitutionKind
        inst = Institution(
            id=1, kind=InstitutionKind.GUILD, founding_tick=0,
            name="the testing guild", member_agent_ids={1},
        )
        settlement.institutions.append(inst)
    eng_high._last_strategy = strategy(dormancy="high")
    # Drive both through enough real monthly checks for a "normal"
    # threshold (3) to NOT yet sleep, while "high" (threshold ~2, since
    # round(3*0.5)=2) already has. `_update_institution_dormancy` is a
    # zero-arg B0.3-migrated job (its own ON_EVENT/month_end gate lives
    # in the scheduler now, not the method) -- calling it directly
    # exercises the real fingerprint/threshold logic each time. The
    # FIRST call only registers a baseline (idle=0, never sleeps) --
    # idle increments from the SECOND call on, so 3 calls total are
    # needed to reach idle=2 (>= the scaled "high" threshold of 2).
    for _ in range(3):
        eng_normal.world.clock.tick_count += 10000
        eng_normal._update_institution_dormancy()
        eng_high.world.clock.tick_count += 10000
        eng_high._update_institution_dormancy()
    # DormancyManager's public surface is is_scheduled(key); rebuild the
    # same key the production code uses.
    from hearthmind.simulation.engine import _institution_dormancy_key
    settlement_normal = eng_normal.world.settlements[0]
    settlement_high = eng_high.world.settlements[0]
    inst_normal = settlement_normal.institutions[0]
    inst_high = settlement_high.institutions[0]
    key_normal = _institution_dormancy_key(settlement_normal, inst_normal)
    key_high = _institution_dormancy_key(settlement_high, inst_high)
    check(
        "production path: a 'high'-aggressiveness engine sleeps the same idle institution at least as fast as 'normal'",
        (not eng_normal._institution_dormancy.is_scheduled(key_normal)) or (not eng_high._institution_dormancy.is_scheduled(key_high)),
    )
    check(
        "production path: the 'high' engine has genuinely slept by 2 checks (round(3*0.5)=2)",
        not eng_high._institution_dormancy.is_scheduled(key_high),
    )
    check(
        "production path: the 'normal' engine has NOT yet slept by 2 checks (threshold 3)",
        eng_normal._institution_dormancy.is_scheduled(key_normal),
    )

    # --- cache_size_hint -> _effective_emergence_log_cap ---
    eng = make_engine()
    check("no strategy yet: emergence cap reproduces the flat default", eng._effective_emergence_log_cap() == EMERGENCE_LOG_MAX_STORED)
    eng._last_strategy = strategy(cache="normal")
    check("normal cache hint: cap unchanged", eng._effective_emergence_log_cap() == EMERGENCE_LOG_MAX_STORED)
    eng._last_strategy = strategy(cache="small")
    check("small cache hint: cap roughly halved", eng._effective_emergence_log_cap() == max(50, EMERGENCE_LOG_MAX_STORED // 2))
    eng._last_strategy = strategy(cache="large")
    check("large cache hint: cap roughly doubled", eng._effective_emergence_log_cap() == EMERGENCE_LOG_MAX_STORED * 2)

    # Real production-path proof: a small-cache engine evicts sooner
    # than the default through the actual _append_emergence call path.
    eng_small = make_engine()
    eng_small._last_strategy = strategy(cache="small")
    small_cap = eng_small._effective_emergence_log_cap()
    for i in range(small_cap + 5):
        append_observation(eng_small, i)
    check(
        "production path: a small-cache engine's emergence_log never exceeds its own scaled-down cap",
        len(eng_small.world.emergence_log) == small_cap,
    )

    # --- TunableRegistry's three pacing constants now genuinely live ---
    from hearthmind.simulation.engine import (
        LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER, LLM_PRESSURE_SLOWDOWN_START_RATIO,
        LLM_PRESSURE_SPEEDUP_START_RATIO,
    )
    eng = make_engine()
    check(
        "_pacing_tunable reads the registry's own default, matching the module constant",
        eng._pacing_tunable("llm_pressure_slowdown_start_ratio", LLM_PRESSURE_SLOWDOWN_START_RATIO) == LLM_PRESSURE_SLOWDOWN_START_RATIO,
    )
    eng._tuning_registry.set_value("llm_pressure_slowdown_start_ratio", 0.9)
    check(
        "adjusting the registry entry genuinely changes what _pacing_tunable returns",
        eng._pacing_tunable("llm_pressure_slowdown_start_ratio", LLM_PRESSURE_SLOWDOWN_START_RATIO) == 0.9,
    )
    # Real end-to-end proof through _llm_pressure_interval_multiplier:
    # pushing speedup_start_ratio way down should make a normally-idle
    # ratio no longer qualify as "speed up," landing on the flat 1.0x
    # zone instead of a genuine speedup multiplier.
    eng2 = make_engine()
    eng2._effective_backlog = lambda: 0.0  # a genuinely idle queue
    baseline_multiplier = eng2._llm_pressure_interval_multiplier()
    check("an idle queue speeds up under the default registry values", baseline_multiplier < 1.0)
    eng2._tuning_registry.set_value("llm_pressure_speedup_start_ratio", 0.0)
    forced_multiplier = eng2._llm_pressure_interval_multiplier()
    check(
        "production path: lowering llm_pressure_speedup_start_ratio via the registry genuinely changes real tick pacing",
        forced_multiplier == 1.0 and forced_multiplier != baseline_multiplier,
    )
    check(
        "LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER stays a sane default constant (regression guard, unrelated to this pass)",
        0.0 < LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER < 1.0,
    )
    check(
        "LLM_PRESSURE_SPEEDUP_START_RATIO's own module default is still below LLM_PRESSURE_SLOWDOWN_START_RATIO (regression guard)",
        LLM_PRESSURE_SPEEDUP_START_RATIO < LLM_PRESSURE_SLOWDOWN_START_RATIO,
    )

    # --- B5.3: the full runtime_diagnostics aggregate ---
    eng = make_engine()
    report = eng.full_diagnostics()
    rd = report["runtime_diagnostics"]
    check(
        "runtime_diagnostics now reports every real B0.3-migrated scheduler, not just institution_dormancy",
        len(rd) == len(eng._RUNTIME_SCHEDULED_JOB_SCHEDULERS) and len(rd) > 1,
    )
    check(
        "institution_dormancy's own scheduler is still present under its real job-method-name key",
        "_update_institution_dormancy" in rd,
    )
    check(
        "every reported scheduler entry has the real runtime_diagnostics_report shape",
        all("tasks" in v for v in rd.values()),
    )

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
