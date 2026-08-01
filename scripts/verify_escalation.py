#!/usr/bin/env python3
"""Standalone verification for B15 (Semantic safety: the determinism
guarantee, docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same
convention as every sibling scripts/verify_*.py: no unittest, no CI
pipeline, run manually.
"""
import dataclasses
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.escalation import (
    SUSTAINED_PRESSURE_THRESHOLD,
    CognitionBudget,
    EscalationLadder,
    Rung,
    TWO_PART_GUARANTEE,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_two_part_guarantee_documented():
    check(
        "B15.2: the decided two-part guarantee is a real, checkable structure, not just prose",
        set(TWO_PART_GUARANTEE.keys()) == {"strict", "adaptive", "accepted_consequence"},
    )


def check_starts_at_rung_one():
    ladder = EscalationLadder()
    check("EscalationLadder: starts at REORDER_BATCH (rung 1)", ladder.current_rung is Rung.REORDER_BATCH)


def check_escalates_one_rung_at_a_time_never_skips():
    ladder = EscalationLadder()
    seen_rungs = [ladder.current_rung]
    for tick in range(1, 4):
        ladder.observe(tick, pressured=True)
        seen_rungs.append(ladder.current_rung)
    check(
        "B15.3: escalates exactly one rung per pressured reading at rungs 1-3, never skips",
        seen_rungs == [Rung.REORDER_BATCH, Rung.DEFER_WITHIN_DEADLINE, Rung.SLOW_SIM_TIME, Rung.PAUSE],
        str(seen_rungs),
    )


def check_rung_five_needs_sustained_pressure_not_a_spike():
    ladder = EscalationLadder()
    for tick in range(1, 4):
        ladder.observe(tick, pressured=True)  # -> PAUSE
    check("setup: reached PAUSE (rungs 1-4 exhausted)", ladder.current_rung is Rung.PAUSE)

    # A single further pressured reading at PAUSE is a spike, not
    # sustained -- must NOT escalate to rung 5 yet.
    ladder.observe(4, pressured=True)
    check(
        "B15.3: a lone pressured reading at PAUSE is a transient spike -- does not reach rung 5",
        ladder.current_rung is Rung.PAUSE,
    )

    for tick in range(5, 4 + SUSTAINED_PRESSURE_THRESHOLD):
        ladder.observe(tick, pressured=True)
    check(
        "B15.3: SUSTAINED pressure at PAUSE genuinely reaches rung 5",
        ladder.current_rung is Rung.REDUCE_COGNITION_BREADTH,
    )


def check_never_escalates_past_rung_five():
    ladder = EscalationLadder()
    for tick in range(1, 50):
        ladder.observe(tick, pressured=True)
    check("B15.3: rung 5 is a real ceiling -- never escalates further even under sustained extreme pressure", ladder.current_rung is Rung.REDUCE_COGNITION_BREADTH)


def check_deescalates_one_rung_at_a_time():
    ladder = EscalationLadder()
    for tick in range(1, 4):
        ladder.observe(tick, pressured=True)  # -> PAUSE
    check("setup: reached PAUSE", ladder.current_rung is Rung.PAUSE)

    seen_rungs = []
    for tick in range(10, 13):
        ladder.observe(tick, pressured=False)
        seen_rungs.append(ladder.current_rung)
    check(
        "B15.3: clearing pressure de-escalates one rung at a time, never skips",
        seen_rungs == [Rung.SLOW_SIM_TIME, Rung.DEFER_WITHIN_DEADLINE, Rung.REORDER_BATCH],
        str(seen_rungs),
    )


def check_deescalate_floor_at_rung_one():
    ladder = EscalationLadder()
    ladder.observe(1, pressured=False)
    check("B15.3: rung 1 is a real floor -- a clear reading at rung 1 stays at rung 1, no error", ladder.current_rung is Rung.REORDER_BATCH)


def check_every_transition_is_logged():
    ladder = EscalationLadder()
    for tick in range(1, 4):
        ladder.observe(tick, pressured=True)
    check("B15.3: every real transition is recorded in history", len(ladder.history) == 3)
    check("B15.3: each history entry carries a real reason string", all(e.reason for e in ladder.history))
    check("B15.3: history entries record the correct from/to rungs", ladder.history[0].from_rung is Rung.REORDER_BATCH and ladder.history[0].to_rung is Rung.DEFER_WITHIN_DEADLINE)


def check_reference_mode_is_a_hard_no_op():
    ladder = EscalationLadder(reference_mode=True, pinned_rung=Rung.SLOW_SIM_TIME)
    check("B15.5: reference mode starts pinned at the requested rung", ladder.current_rung is Rung.SLOW_SIM_TIME)
    for tick in range(1, 100):
        ladder.observe(tick, pressured=True)
    check("B15.5: reference mode NEVER escalates, no matter how much pressure is observed", ladder.current_rung is Rung.SLOW_SIM_TIME)
    for tick in range(100, 110):
        ladder.observe(tick, pressured=False)
    check("B15.5: reference mode NEVER de-escalates either -- a genuine pin, not just resistant to escalation", ladder.current_rung is Rung.SLOW_SIM_TIME)
    check("B15.5: reference mode records no history at all -- nothing real happened", len(ladder.history) == 0)


def check_cognition_budget_is_structurally_count_only():
    field_names = {f.name for f in dataclasses.fields(CognitionBudget)}
    check("B15.4: CognitionBudget has EXACTLY one field, a bare count -- structurally incapable of naming a selection", field_names == {"count"}, str(field_names))


def check_cognition_budget_only_shrinks_at_rung_five():
    ladder = EscalationLadder()
    budget_at_rung1 = ladder.cognition_budget_for_rung(base_budget=100, reduced_budget=20)
    check("B15.4: at rung 1, the budget is the simulation's own base budget, untouched", budget_at_rung1.count == 100)

    for tick in range(1, 4):
        ladder.observe(tick, pressured=True)  # -> PAUSE
    budget_at_pause = ladder.cognition_budget_for_rung(base_budget=100, reduced_budget=20)
    check("B15.4: at PAUSE (rung 4), the budget is STILL the full base budget -- only rung 5 reduces it", budget_at_pause.count == 100)

    ladder.observe(4, pressured=True)
    for tick in range(5, 4 + SUSTAINED_PRESSURE_THRESHOLD):
        ladder.observe(tick, pressured=True)
    check("setup: reached rung 5", ladder.current_rung is Rung.REDUCE_COGNITION_BREADTH)
    budget_at_rung5 = ladder.cognition_budget_for_rung(base_budget=100, reduced_budget=20)
    check("B15.4: only at rung 5 does the runtime's own budget genuinely shrink", budget_at_rung5.count == 20)


def main():
    check_two_part_guarantee_documented()
    check_starts_at_rung_one()
    check_escalates_one_rung_at_a_time_never_skips()
    check_rung_five_needs_sustained_pressure_not_a_spike()
    check_never_escalates_past_rung_five()
    check_deescalates_one_rung_at_a_time()
    check_deescalate_floor_at_rung_one()
    check_every_transition_is_logged()
    check_reference_mode_is_a_hard_no_op()
    check_cognition_budget_is_structurally_count_only()
    check_cognition_budget_only_shrinks_at_rung_five()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
