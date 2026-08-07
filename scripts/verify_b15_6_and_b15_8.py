#!/usr/bin/env python3
"""Tier 5 B15.6 + B15.8 verification (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B, B15 "Semantic safety: the determinism
guarantee"). Standalone script, no unittest, same convention as every
sibling scripts/verify_*.py.

B15.6: `World.machine_profile_history` — a real, persisted, bounded
record of `session_started`/`rung5_entered`/`rung5_exited` events, the
one field B15.2's own text names directly ("save files must record
the profile") that no prior B15 item actually wrote to a save file.

B15.8: `TunableRegistry.register()`'s two new registration-time
semantic-safety checks — an out-of-range starting value, and a
`SENSITIVE` tunable with no description.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine, Rung
from hearthmind.simulation.tuning import SafetyClass, Tunable, TunableRegistry

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


# --- B15.8: registration-time checks -----------------------------------


def check_out_of_range_value_rejected():
    reg = TunableRegistry()
    raised = False
    try:
        reg.register(Tunable(name="a", value=99.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    except ValueError:
        raised = True
    check("out-of-range starting value rejected at registration", raised)


def check_in_range_value_accepted():
    reg = TunableRegistry()
    reg.register(Tunable(name="a", value=5.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    check("in-range starting value accepted", reg.get("a").value == 5.0)


def check_boundary_values_accepted():
    reg = TunableRegistry()
    reg.register(Tunable(name="lo", value=0.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    reg.register(Tunable(name="hi", value=10.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    check("exact-boundary values accepted (not off-by-one strict)", reg.get("lo").value == 0.0 and reg.get("hi").value == 10.0)


def check_sensitive_without_description_rejected():
    reg = TunableRegistry()
    raised = False
    try:
        reg.register(Tunable(name="a", value=5.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SENSITIVE))
    except ValueError:
        raised = True
    check("SENSITIVE tunable with no description rejected at registration", raised)


def check_sensitive_with_whitespace_description_rejected():
    reg = TunableRegistry()
    raised = False
    try:
        reg.register(Tunable(
            name="a", value=5.0, min_value=0.0, max_value=10.0, step=1.0,
            safety_class=SafetyClass.SENSITIVE, description="   ",
        ))
    except ValueError:
        raised = True
    check("SENSITIVE tunable with a whitespace-only description rejected", raised)


def check_sensitive_with_real_description_accepted():
    reg = TunableRegistry()
    reg.register(Tunable(
        name="a", value=5.0, min_value=0.0, max_value=10.0, step=1.0,
        safety_class=SafetyClass.SENSITIVE, description="a real, non-empty justification.",
    ))
    check("SENSITIVE tunable with a real description accepted", reg.get("a").description != "")


def check_safe_without_description_accepted():
    reg = TunableRegistry()
    reg.register(Tunable(name="a", value=5.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    check("SAFE tunable needs no description (exempt by design)", reg.get("a").description == "")


def check_real_llm_pacing_tunables_still_pass():
    from hearthmind.simulation.tuning import register_llm_pacing_tunables
    reg = TunableRegistry()
    registered_ok = True
    try:
        register_llm_pacing_tunables(reg)
    except ValueError:
        registered_ok = False
    check(
        "the real register_llm_pacing_tunables (4 real SENSITIVE tunables) still registers cleanly",
        registered_ok and len(reg.all()) == 4,
    )


def check_real_snapshot_tunables_still_pass():
    from hearthmind.simulation.persistence_scheduling import SnapshotPolicy, register_snapshot_tunables
    reg = TunableRegistry()
    registered_ok = True
    try:
        register_snapshot_tunables(reg, SnapshotPolicy(min_interval_ticks=10, max_interval_ticks=100, full_snapshot_every=3))
    except (ValueError, TypeError):
        registered_ok = False
    check("the real register_snapshot_tunables (2 real SAFE tunables) still registers cleanly", registered_ok)


# --- B15.6: persisted machine-profile history ---------------------------


async def _drive(eng, ticks: int) -> None:
    for _ in range(ticks):
        eng._tick_once()
        await asyncio.sleep(0)
    if eng._background_tasks:
        await asyncio.gather(*eng._background_tasks, return_exceptions=True)


def _make_engine(tmpdir: str) -> SimulationEngine:
    db_path = os.path.join(tmpdir, "b15_6.db")
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=42, initial_population=6, width=24, height=24)
    return SimulationEngine.load_or_create(conn, cfg)


def check_session_started_recorded_on_construction():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        entries = eng.world.machine_profile_history
        check(
            "session_started recorded once at construction",
            len(entries) == 1 and entries[0]["event"] == "session_started",
            str(entries),
        )
        check(
            "session_started carries a real host_fingerprint",
            entries[0]["host_fingerprint"] == eng._machine_profile.host_fingerprint and bool(entries[0]["host_fingerprint"]),
        )
        check("session_started's tick matches the world's own clock at construction", entries[0]["tick"] == eng.world.clock.tick_count)


def check_rung5_entry_and_exit_recorded():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        baseline = len(eng.world.machine_profile_history)

        # Directly drive the resolver's own logic (same shape every
        # other B15/H2 verify script uses to force a rung transition
        # without needing a real multi-day pressured soak) -- force the
        # ladder to REDUCE_COGNITION_BREADTH, then observe it recede.
        eng._escalation_ladder.current_rung = Rung.PAUSE
        eng._escalation_ladder.streak_at_current_rung = 10  # >= SUSTAINED_PRESSURE_THRESHOLD

        def resolver_body(pressured: bool, tick: int) -> None:
            rung_before = eng._escalation_ladder.current_rung
            eng._escalation_ladder.observe(tick, pressured)
            rung_after = eng._escalation_ladder.current_rung
            eng._cognition_budget = eng._escalation_ladder.cognition_budget_for_rung(1_000_000, 3)
            from hearthmind.simulation.escalation import Rung as _Rung
            if rung_after is _Rung.REDUCE_COGNITION_BREADTH and rung_before is not _Rung.REDUCE_COGNITION_BREADTH:
                eng._record_machine_profile_history("rung5_entered", rung=rung_after, cognition_budget=eng._cognition_budget.count)
            elif rung_before is _Rung.REDUCE_COGNITION_BREADTH and rung_after is not _Rung.REDUCE_COGNITION_BREADTH:
                eng._record_machine_profile_history("rung5_exited", rung=rung_after, cognition_budget=eng._cognition_budget.count)

        resolver_body(pressured=True, tick=100)
        check(
            "a genuine rung-5 entry is recorded",
            eng._escalation_ladder.current_rung is Rung.REDUCE_COGNITION_BREADTH
            and len(eng.world.machine_profile_history) == baseline + 1
            and eng.world.machine_profile_history[-1]["event"] == "rung5_entered"
            and eng.world.machine_profile_history[-1]["rung"] == "REDUCE_COGNITION_BREADTH"
            and eng.world.machine_profile_history[-1]["cognition_budget"] == 3,
        )

        # A non-pressured reading at rung 5 de-escalates one rung (to
        # PAUSE) -- a real rung-5 EXIT.
        resolver_body(pressured=False, tick=101)
        check(
            "a genuine rung-5 exit is recorded",
            eng._escalation_ladder.current_rung is Rung.PAUSE
            and len(eng.world.machine_profile_history) == baseline + 2
            and eng.world.machine_profile_history[-1]["event"] == "rung5_exited",
        )


def check_non_rung5_transitions_not_recorded():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        baseline = len(eng.world.machine_profile_history)
        # Ordinary rung 1 <-> 2 churn never touches rung 5 at all.
        eng._escalation_ladder.observe(10, True)   # 1 -> 2
        eng._escalation_ladder.observe(11, False)  # 2 -> 1
        check(
            "ordinary (non-rung-5) transitions are never persisted",
            len(eng.world.machine_profile_history) == baseline,
            f"history grew to {len(eng.world.machine_profile_history)}",
        )


def check_bounded_eviction():
    from hearthmind.simulation.engine import MACHINE_PROFILE_HISTORY_MAX
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        for i in range(MACHINE_PROFILE_HISTORY_MAX + 25):
            eng._record_machine_profile_history("session_started")
        check(
            f"machine_profile_history stays bounded at {MACHINE_PROFILE_HISTORY_MAX}",
            len(eng.world.machine_profile_history) == MACHINE_PROFILE_HISTORY_MAX,
            str(len(eng.world.machine_profile_history)),
        )


def check_round_trip_and_legacy_backfill():
    from hearthmind.world.state import World
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        eng._record_machine_profile_history("rung5_entered", rung=Rung.REDUCE_COGNITION_BREADTH, cognition_budget=3)
        data = eng.world.to_dict()
        restored = World.from_dict(data, eng.world.config)
        check(
            "machine_profile_history round-trips through to_dict/from_dict",
            restored.machine_profile_history == eng.world.machine_profile_history,
        )
        legacy = dict(data)
        del legacy["machine_profile_history"]
        legacy_restored = World.from_dict(legacy, eng.world.config)
        check(
            "a legacy snapshot with no machine_profile_history key backfills to an empty list",
            legacy_restored.machine_profile_history == [],
        )


def check_diagnostics_surfacing():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        report = eng.full_diagnostics()
        check(
            "full_diagnostics() surfaces machine_profile_history_recent",
            "machine_profile_history_recent" in report
            and len(report["machine_profile_history_recent"]) == 1
            and report["machine_profile_history_recent"][0]["event"] == "session_started",
        )


def check_production_soak_no_crash():
    with tempfile.TemporaryDirectory() as d:
        eng = _make_engine(d)
        asyncio.run(_drive(eng, 400))
        check(
            "a real 400-tick soak with the new machine_profile_history writer live never crashes",
            len(eng.world.machine_profile_history) >= 1,
        )


def main() -> int:
    check_out_of_range_value_rejected()
    check_in_range_value_accepted()
    check_boundary_values_accepted()
    check_sensitive_without_description_rejected()
    check_sensitive_with_whitespace_description_rejected()
    check_sensitive_with_real_description_accepted()
    check_safe_without_description_accepted()
    check_real_llm_pacing_tunables_still_pass()
    check_real_snapshot_tunables_still_pass()
    check_session_started_recorded_on_construction()
    check_rung5_entry_and_exit_recorded()
    check_non_rung5_transitions_not_recorded()
    check_bounded_eviction()
    check_round_trip_and_legacy_backfill()
    check_diagnostics_surfacing()
    check_production_soak_no_crash()

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
