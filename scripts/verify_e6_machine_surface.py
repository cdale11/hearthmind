#!/usr/bin/env python3
"""Tier 7 HCA Stage E, E6 (docs/ROADMAP-2026-07-REMAINING.md, Phase 7,
explicit user instruction "Start E6") -- **this closes Stage E**: the
Cognitive Observatory's Machine surface, a rendering pass combining
three already-real `full_diagnostics()` fields (H2's `machine_domain`,
H4's `player_model_domain`, B15's `escalation_ladder`) into one legible
panel -- "the Runtime's own bids, wins and escalations shown beside
the world's." No new backend mechanism; this script's job is to prove
all three fields carry real, populated production data once the
Runtime and Player Model actually do something, which is exactly what
the new dev-console panel (`renderMachineSurface`, `app.js`) renders.

Same "force real pressure, call the real production method" technique
`verify_h2_h3_runtime_domain.py` already established for the
escalation ladder; `_record_observer_attention` is the real production
call site for the Player Model (H4)."""
from __future__ import annotations

import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    d = tempfile.mkdtemp()
    conn = connect(f"{d}/e6.db")
    cfg = Config(db_path=f"{d}/e6.db", llm_enabled=False, seed=17, initial_population=4, width=16, height=16)
    eng = SimulationEngine.load_or_create(conn, cfg)

    # --- before any real Runtime/Player-Model activity, the three
    #     fields are present but honestly show a fresh/no-op state ---
    report_before = eng.full_diagnostics()
    for key in ("escalation_ladder", "machine_domain", "player_model_domain"):
        check(f"full_diagnostics() surfaces '{key}' before any activity",
              key in report_before)
    check("a fresh ladder starts at REORDER_BATCH with no real transitions logged",
          report_before["escalation_ladder"]["current_rung"] == "REORDER_BATCH"
          and report_before["escalation_ladder"]["history_recent"] == [])
    check("a fresh player model reports an honest 'no observations yet' (hit_rate None)",
          report_before["player_model_domain"]["hit_rate"] is None)

    # --- force real sustained pressure so a real rung transition (a
    #     real escalation) lands in the ladder's own history, and a
    #     real MACHINE-domain workspace cycle records a real winner ---
    eng._current_backpressure_limit = lambda: 1  # type: ignore[method-assign]
    eng._effective_backlog = lambda: 999  # type: ignore[method-assign]
    before_cycles = eng._machine_workspace._cycle
    eng._maybe_advance_escalation_ladder(["day_end"])
    report_pressured = eng.full_diagnostics()
    check("a real forced-pressure day_end call produces a real logged rung transition",
          len(report_pressured["escalation_ladder"]["history_recent"]) == 1
          and report_pressured["escalation_ladder"]["current_rung"] != "REORDER_BATCH")
    check("the same call advances the real MACHINE-domain workspace's own cycle counter",
          report_pressured["machine_domain"]["cycles"] == before_cycles + 1)
    check("the MACHINE-domain workspace's real winner names the escalation_ladder specialist",
          report_pressured["machine_domain"]["history_recent"][-1]["winner"]["specialist_id"] == "adaptive_runtime")

    # --- drive a real Player Model observation through its real
    #     production call site, twice (a genuine hit then a genuine
    #     miss is guaranteed by observing two DIFFERENT agents, since
    #     the very first observation has nothing to predict from) ---
    agent_ids = [a.id for a in eng.world.population.agents][:2]
    for aid in agent_ids:
        eng._record_observer_attention(aid)
    report_after = eng.full_diagnostics()
    check("a real observer-attention call populates the player model's real history",
          len(report_after["player_model_domain"]["history_recent"]) == len(agent_ids))
    check("the player model's hit_rate is now a real measured float, not None",
          isinstance(report_after["player_model_domain"]["hit_rate"], float))

    # --- the panel's own data contract: every field the JS render
    #     function reads must actually be present on a real record ---
    ladder_event = report_after["escalation_ladder"]["history_recent"][-1]
    for field in ("tick", "from_rung", "to_rung", "reason"):
        check(f"a real escalation event carries the field '{field}' the panel reads",
              field in ladder_event)
    machine_cycle = report_after["machine_domain"]["history_recent"][-1]
    check("a real machine-domain cycle carries 'cycle'/'winner'/'losers' the panel reads",
          "cycle" in machine_cycle and "winner" in machine_cycle and "losers" in machine_cycle)
    player_event = report_after["player_model_domain"]["history_recent"][-1]
    for field in ("tick", "predicted_agent_id", "actual_agent_id", "hit"):
        check(f"a real player-model observation carries the field '{field}' the panel reads",
              field in player_event)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
