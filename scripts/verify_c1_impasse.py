#!/usr/bin/env python3
"""Tier 7 HCA Stage C, C1 (docs/ROADMAP-2026-07-REMAINING.md, Phase 5,
explicit user instruction "Start C1"): the four typed impasses as the
deliberation trigger.

Verifies `hearthmind/cognition/impasse.py`'s four classifiers, each
against REAL production data structures/signals this codebase already
maintains, not synthetic stand-ins invented for this test alone: a
real `CompetitionRecord` produced by a real `GlobalWorkspace.
arbitrate()` cycle (tie); a real `Institution.objective_ticks_unmet`
counter (no_change); a real `Pillar.disagrees_with()` call against a
real seeded `world_model` entry (conflict); and a real `Simulation
Engine._emergence_surprise` (A1's own `SurpriseSpecialist`) scored
against the real production `EMERGENCE_SURPRISE_THRESHOLD` (novelty).
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    from hearthmind.cognition.impasse import (
        Impasse, ImpasseKind, TIE_SCORE_TOLERANCE,
        detect_conflict, detect_no_change, detect_novelty, detect_tie_from_competition,
    )
    from hearthmind.cognition.workspace import Bid, GlobalWorkspace

    # --- tie, against a real CompetitionRecord from a real workspace ---
    ws = GlobalWorkspace()
    ws.submit(Bid(specialist_id="a", subject="site_choice", score=0.601))
    ws.submit(Bid(specialist_id="b", subject="site_choice", score=0.599))
    ws.arbitrate()
    tie_record = ws.history[-1]
    tie = detect_tie_from_competition(tie_record)
    check("a real near-equal competition (within tolerance) IS classified as a tie",
          tie is not None and tie.kind is ImpasseKind.TIE and tie.subject == "site_choice")

    ws2 = GlobalWorkspace()
    ws2.submit(Bid(specialist_id="a", subject="site_choice", score=0.9))
    ws2.submit(Bid(specialist_id="b", subject="site_choice", score=0.1))
    ws2.arbitrate()
    decisive_record = ws2.history[-1]
    check("a real decisively-won competition is correctly NOT a tie",
          detect_tie_from_competition(decisive_record) is None)

    ws3 = GlobalWorkspace()
    ws3.submit(Bid(specialist_id="a", subject="site_choice", score=0.9))
    ws3.arbitrate()
    solo_record = ws3.history[-1]
    check("a real coalition-of-one (no losers) is correctly NOT a tie",
          detect_tie_from_competition(solo_record) is None)

    empty_ws = GlobalWorkspace()
    empty_ws.arbitrate()
    empty_record = empty_ws.history[-1]
    check("a real genuinely empty cycle (winner=None) is correctly NOT a tie",
          detect_tie_from_competition(empty_record) is None)

    ws_boundary = GlobalWorkspace()
    ws_boundary.submit(Bid(specialist_id="a", subject="x", score=0.5 + TIE_SCORE_TOLERANCE * 0.5))
    ws_boundary.submit(Bid(specialist_id="b", subject="x", score=0.5))
    ws_boundary.arbitrate()
    check("a gap well inside the tolerance IS a tie",
          detect_tie_from_competition(ws_boundary.history[-1]) is not None)

    ws_just_outside = GlobalWorkspace()
    ws_just_outside.submit(Bid(specialist_id="a", subject="x", score=0.5 + TIE_SCORE_TOLERANCE * 3))
    ws_just_outside.submit(Bid(specialist_id="b", subject="x", score=0.5))
    ws_just_outside.arbitrate()
    check("a gap well outside the tolerance is NOT a tie",
          detect_tie_from_competition(ws_just_outside.history[-1]) is None)

    # --- no_change, against a real Institution.objective_ticks_unmet ---
    from hearthmind.settlement.institutions import (
        INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD, Institution, InstitutionKind,
    )

    institution = Institution(id=1, kind=InstitutionKind.COUNCIL, founding_tick=0)
    institution.objective_ticks_unmet = INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD - 1
    check("a real institution just below the real persistence threshold is NOT a no-change impasse",
          detect_no_change(institution.name or "council", institution.objective_ticks_unmet,
                            INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD) is None)

    institution.objective_ticks_unmet = INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD
    no_change = detect_no_change("council", institution.objective_ticks_unmet,
                                  INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
    check("a real institution at/past the real persistence threshold IS a no-change impasse",
          no_change is not None and no_change.kind is ImpasseKind.NO_CHANGE)

    # --- conflict, against a real Pillar.disagrees_with() ---
    from hearthmind.cognition.pillar import default_village_pillar

    pillar = default_village_pillar()
    check("a fresh real pillar with no theories yet never reports conflict",
          detect_conflict("drought", pillar.disagrees_with("drought")) is None)

    pillar.upsert_world_model(tick=10, subject="drought", belief="the drought will pass soon", confidence=0.8)
    conflict = detect_conflict("drought", pillar.disagrees_with("drought"))
    check("a real confident pillar theory about the SAME subject IS a conflict impasse",
          conflict is not None and conflict.kind is ImpasseKind.CONFLICT)
    check("an unrelated real subject is correctly NOT a conflict",
          detect_conflict("famine", pillar.disagrees_with("famine")) is None)

    # --- novelty, against a real SimulationEngine._emergence_surprise ---
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import EMERGENCE_SURPRISE_THRESHOLD, SimulationEngine
    from hearthmind.world.state import World

    config = Config(db_path=":memory:", llm_enabled=False, seed=606)
    world = World.create_new(config)
    conn = connect(":memory:")
    engine = SimulationEngine(conn, config, world)

    # a signal repeated identically many times converges to near-zero surprise
    key = "nature:predator_pack_extinction"
    for _ in range(20):
        engine._emergence_surprise.observe(key, 0.5)
    routine_surprise = engine._emergence_surprise.error(key, 0.5)
    check("a real, repeatedly-confirmed signal scores low real surprise",
          detect_novelty(key, routine_surprise, EMERGENCE_SURPRISE_THRESHOLD) is None)

    # a genuinely novel deviation on the same real specialist
    novel_surprise = engine._emergence_surprise.error(key, 5.0)
    novelty = detect_novelty(key, novel_surprise, EMERGENCE_SURPRISE_THRESHOLD)
    check("a real sharp deviation on the same real specialist IS a novelty impasse "
          "(using the real production EMERGENCE_SURPRISE_THRESHOLD)",
          novelty is not None and novelty.kind is ImpasseKind.NOVELTY)

    # --- Impasse itself is a plain, frozen, real record ---
    sample = Impasse(kind=ImpasseKind.TIE, subject="x", detail="y")
    check("Impasse is a real frozen dataclass (immutable, hashable-shaped)",
          sample.kind is ImpasseKind.TIE and sample.subject == "x" and sample.detail == "y")
    try:
        sample.subject = "z"  # type: ignore[misc]
        frozen_ok = False
    except Exception:
        frozen_ok = True
    check("an Impasse cannot be mutated after construction", frozen_ok)

    check("TIE_SCORE_TOLERANCE is a real positive constant", TIE_SCORE_TOLERANCE > 0.0)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
