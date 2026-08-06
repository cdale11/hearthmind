#!/usr/bin/env python3
"""Roadmap Phase 3, H1 "per-domain budgets" (docs/ROADMAP-2026-07-
REMAINING.md, explicit user instruction "continue with phase 3's
remaining items" -> "H1 per-domain budgets (Recommended)"): a real
SECOND MACHINE-domain bidder, closing the exact gap H1's own entry
named ("write-scope enforcement is real; real per-domain budget
contention needs a second real bidder in the MACHINE or OBSERVER
domain, which doesn't exist yet").

`hearthmind.cognition.runtime_specialist.propose_machine_profile_
refresh_bid` gives B7.2's monthly `MachineProfile` disk refresh a real
`Bid`, submitted to the SAME `SimulationEngine._machine_workspace` the
escalation ladder's own `propose_escalation_bid` already uses.
`_maybe_advance_escalation_ladder`/`_maybe_refresh_machine_profile` now
only SUBMIT; the actual `arbitrate()` call moved to a new shared
`_maybe_resolve_machine_domain`, run once per real day_end AFTER both
have had a chance to submit -- the real structural change that makes
multi-bid contention possible at all (a submit-then-immediately-
arbitrate site, same shape every W1-W4 site already used, is
structurally a coalition of one).

This script proves what none of the four pre-existing H1/H2/H3/B8/E6
scripts test (all pre-date this pass and were re-run unmodified,
adjusted only to drive the new two-step submit/resolve shape where they
already exercised `_maybe_advance_escalation_ladder`/`_maybe_refresh_
machine_profile` directly): the real score ordering that makes
contention MEANINGFUL, not a coin flip; a real `GlobalWorkspace` with
both bids pending resolving to whichever one the real `pressured`
reading favors, in BOTH directions; and a full real production proof
through `SimulationEngine` -- on a genuinely calm day where both real
gates clear, the profile refresh wins and the escalation ladder's own
resolver does NOT run (the ladder's rung/streak state is untouched);
on a genuinely pressured day, the reverse."""
from __future__ import annotations

import sys
import tempfile
from unittest import mock

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, db_name: str):
    """Each engine gets its OWN subdirectory, not just its own db
    filename within a shared `tmpdir` -- `_machine_profile_path_for`
    derives the real persisted profile's path from `os.path.dirname
    (db_path)` alone (a fixed `machine_profile.json` filename, per
    B7.2), so two engines sharing a directory would silently load each
    OTHER'S real saved profile instead of starting genuinely fresh --
    exactly the class of test-harness bug this project's own history
    repeatedly documents, caught here before shipping."""
    import os

    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    subdir = os.path.join(tmpdir, db_name.replace(".db", ""))
    os.makedirs(subdir, exist_ok=True)
    db_path = os.path.join(subdir, db_name)
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=7, initial_population=4, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


def main() -> int:
    from hearthmind.cognition import runtime_specialist
    from hearthmind.cognition.runtime_specialist import (
        ESCALATION_BID_CALM_SCORE, ESCALATION_BID_PRESSURED_SCORE, MACHINE_PROFILE_REFRESH_BID_SCORE,
    )
    from hearthmind.cognition.workspace import GlobalWorkspace
    from hearthmind.simulation.hardware_profile import HostProbe

    # --- the real score ordering that makes contention meaningful,
    #     not accidental submission-order luck ---
    check("a pressured escalation bid outscores the profile-refresh bid",
          ESCALATION_BID_PRESSURED_SCORE > MACHINE_PROFILE_REFRESH_BID_SCORE)
    check("a calm escalation bid is outscored by the profile-refresh bid",
          ESCALATION_BID_CALM_SCORE < MACHINE_PROFILE_REFRESH_BID_SCORE)

    # --- propose_escalation_bid's score genuinely depends on pressured ---
    bid_pressured = runtime_specialist.propose_escalation_bid(1, lambda: None, pressured=True)
    bid_calm = runtime_specialist.propose_escalation_bid(1, lambda: None, pressured=False)
    check("propose_escalation_bid(pressured=True) scores ESCALATION_BID_PRESSURED_SCORE",
          bid_pressured.score == ESCALATION_BID_PRESSURED_SCORE)
    check("propose_escalation_bid(pressured=False) scores ESCALATION_BID_CALM_SCORE",
          bid_calm.score == ESCALATION_BID_CALM_SCORE)
    check("both escalation bids still name the real subject", bid_pressured.subject == bid_calm.subject == "escalation_ladder")

    # --- propose_machine_profile_refresh_bid: a real, distinct subject ---
    refresh_bid = runtime_specialist.propose_machine_profile_refresh_bid(lambda: None)
    check("propose_machine_profile_refresh_bid names its own distinct subject",
          refresh_bid.subject == "machine_profile_refresh")
    check("propose_machine_profile_refresh_bid scores MACHINE_PROFILE_REFRESH_BID_SCORE",
          refresh_bid.score == MACHINE_PROFILE_REFRESH_BID_SCORE)
    check("propose_machine_profile_refresh_bid is a real MACHINE-domain bid",
          refresh_bid.domain is runtime_specialist.SPECIALIST_DOMAIN)

    # --- real multi-bid contention, both directions, over a real
    #     GlobalWorkspace (the domain's own real one-winner-per-cycle
    #     mechanism, not a hand-simulated stand-in) ---
    ws = GlobalWorkspace()
    escalation_ran, refresh_ran = [], []
    ws.submit(runtime_specialist.propose_escalation_bid(10, lambda: escalation_ran.append(1), pressured=True))
    ws.submit(runtime_specialist.propose_machine_profile_refresh_bid(lambda: refresh_ran.append(1)))
    winner = ws.arbitrate()
    if winner is not None:
        winner.resolver()
    check("a pressured cycle with both real bids pending: the escalation ladder wins",
          winner is not None and winner.subject == "escalation_ladder"
          and escalation_ran == [1] and refresh_ran == [])
    check("the losing profile-refresh bid is recorded as a real loser, not silently dropped",
          len(ws.history[-1].losers) == 1 and ws.history[-1].losers[0].subject == "machine_profile_refresh")

    ws2 = GlobalWorkspace()
    escalation_ran2, refresh_ran2 = [], []
    ws2.submit(runtime_specialist.propose_escalation_bid(20, lambda: escalation_ran2.append(1), pressured=False))
    ws2.submit(runtime_specialist.propose_machine_profile_refresh_bid(lambda: refresh_ran2.append(1)))
    winner2 = ws2.arbitrate()
    if winner2 is not None:
        winner2.resolver()
    check("a CALM cycle with both real bids pending: the profile refresh wins instead",
          winner2 is not None and winner2.subject == "machine_profile_refresh"
          and refresh_ran2 == [1] and escalation_ran2 == [])
    check("the losing escalation bid is recorded as a real loser this cycle",
          len(ws2.history[-1].losers) == 1 and ws2.history[-1].losers[0].subject == "escalation_ladder")

    # --- real end-to-end production wiring: a full SimulationEngine,
    #     both real gates cleared the same real day_end+month_end tick ---
    BENCHMARK_PROBE = HostProbe(
        logical_cores=8, usable_cores=8, mem_total_mb=16000, mem_available_mb=8000,
        swap_used_mb=0, swap_total_mb=0, load_avg_1m=1.0, storage_write_mb_s=250.0,
        storage_read_mb_s=500.0, gpu_present=False, thermal_state="nominal", timestamp=0.0,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        # CALM cycle: the profile refresh wins the domain's one real
        # action; the escalation ladder's own resolver never runs.
        eng_calm = make_engine(tmpdir, "calm.db")
        for _ in range(40):
            eng_calm._recent_llm_backlog_samples.append(0.0)  # a genuinely quiet history
        rung_before = eng_calm._escalation_ladder.current_rung
        streak_before = eng_calm._escalation_ladder.streak_at_current_rung
        with mock.patch.object(HostProbe, "sample", return_value=BENCHMARK_PROBE), \
             mock.patch.object(type(eng_calm), "llm_pressure_ratio", return_value=0.0):
            eng_calm._maybe_refresh_machine_profile(["month_end", "day_end"])
            eng_calm._maybe_advance_escalation_ladder(["month_end", "day_end"])
            eng_calm._maybe_resolve_machine_domain(["month_end", "day_end"])
        check("a real calm cycle: the machine profile's storage benchmark genuinely refreshed",
              eng_calm._machine_profile.storage_write_mb_s == BENCHMARK_PROBE.storage_write_mb_s)
        check("a real calm cycle: the escalation ladder's own resolver did NOT run (rung/streak untouched)",
              eng_calm._escalation_ladder.current_rung == rung_before
              and eng_calm._escalation_ladder.streak_at_current_rung == streak_before)
        check("a real calm cycle: the machine workspace recorded a real winner+loser this cycle",
              eng_calm._machine_workspace.history[-1].winner.subject == "machine_profile_refresh"
              and len(eng_calm._machine_workspace.history[-1].losers) == 1
              and eng_calm._machine_workspace.history[-1].losers[0].subject == "escalation_ladder")

        # PRESSURED cycle: the escalation ladder wins instead; the
        # profile refresh's own real disk work never runs, even though
        # its own gate cleared this same cycle.
        eng_pressured = make_engine(tmpdir, "pressured.db")
        for _ in range(40):
            eng_pressured._recent_llm_backlog_samples.append(0.0)  # profile refresh's own gate still clears
        with mock.patch.object(HostProbe, "sample", return_value=BENCHMARK_PROBE), \
             mock.patch.object(type(eng_pressured), "llm_pressure_ratio", return_value=2.0):
            eng_pressured._maybe_refresh_machine_profile(["month_end", "day_end"])
            eng_pressured._maybe_advance_escalation_ladder(["month_end", "day_end"])
            eng_pressured._maybe_resolve_machine_domain(["month_end", "day_end"])
        check("a real pressured cycle: the machine profile's storage benchmark did NOT run",
              eng_pressured._machine_profile.storage_write_mb_s is None)
        check("a real pressured cycle: the escalation ladder's own resolver DID run (a real rung/streak change)",
              eng_pressured._escalation_ladder.current_rung.name != "REORDER_BATCH"
              or eng_pressured._escalation_ladder.streak_at_current_rung >= 1)
        check("a real pressured cycle: the machine workspace recorded the reverse winner+loser",
              eng_pressured._machine_workspace.history[-1].winner.subject == "escalation_ladder"
              and eng_pressured._machine_workspace.history[-1].losers[0].subject == "machine_profile_refresh")

        # --- the common case is unchanged: on an ordinary day (no
        #     month_end), only the escalation ladder ever bids, and it
        #     wins its own coalition of one exactly as before this pass ---
        eng_ordinary = make_engine(tmpdir, "ordinary.db")
        rung0 = eng_ordinary._escalation_ladder.current_rung
        with mock.patch.object(type(eng_ordinary), "llm_pressure_ratio", return_value=2.0):
            eng_ordinary._maybe_refresh_machine_profile(["day_end"])  # no month_end -> never submits
            eng_ordinary._maybe_advance_escalation_ladder(["day_end"])
            eng_ordinary._maybe_resolve_machine_domain(["day_end"])
        check("an ordinary pressured day_end (no month_end): still a real coalition of one, the ladder still moves",
              eng_ordinary._escalation_ladder.current_rung.name != rung0.name
              or eng_ordinary._escalation_ladder.streak_at_current_rung >= 1)
        check("an ordinary day never even builds a profile-refresh bid",
              len(eng_ordinary._machine_workspace.history[-1].losers) == 0)

        # --- _maybe_resolve_machine_domain's own gate: never arbitrates
        #     off a non-day_end tick, even with a real bid pending ---
        eng_gate = make_engine(tmpdir, "gate.db")
        eng_gate._machine_workspace.submit(
            runtime_specialist.propose_machine_profile_refresh_bid(lambda: None),
        )
        pending_before = eng_gate._machine_workspace.pending_count()
        eng_gate._maybe_resolve_machine_domain(["month_end"])  # no day_end
        check("_maybe_resolve_machine_domain is a genuine no-op off day_end, even with a real bid pending",
              eng_gate._machine_workspace.pending_count() == pending_before)

    # --- _TICK_JOBS ordering: both real submitters must run before the
    #     shared resolver in the same real tick ---
    job_names = [name for name, _ in eng_ordinary._TICK_JOBS]
    idx_profile = job_names.index("_maybe_refresh_machine_profile")
    idx_ladder = job_names.index("_maybe_advance_escalation_ladder")
    idx_resolve = job_names.index("_maybe_resolve_machine_domain")
    check("_maybe_refresh_machine_profile runs before _maybe_resolve_machine_domain in _TICK_JOBS",
          idx_profile < idx_resolve)
    check("_maybe_advance_escalation_ladder runs before _maybe_resolve_machine_domain in _TICK_JOBS",
          idx_ladder < idx_resolve)

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
