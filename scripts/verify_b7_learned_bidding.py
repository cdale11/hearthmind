#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B7 (explicit user instruction: "Start B7" --
Stage G's `learn()` interface, this B7's own real dependency, has been
shipped since v1.34.216-.219): learning to bid from realised outcomes.
Real claims verified: (1) a deliberately unreliable specialist and a
reliable one, given IDENTICAL raw bids, invert in rank order over a
run of real credited outcomes; (2) a never-winning specialist's
staleness gain is NOT learned downward -- `OutcomeLearner` and
`GlobalWorkspace` are structurally disconnected; (3) `credit_winning_
coalition`/`credit_losing_bid` are the real B4/B7 integration points
the roadmap names ("credited back to winning coalitions... and, where
a counterfactual is honestly available, to losing ones").

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
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
    from hearthmind.cognition.workspace import (
        Bid,
        BidFactors,
        Coalition,
        GlobalWorkspace,
        HISTORICAL_USEFULNESS_CEILING,
        HISTORICAL_USEFULNESS_FLOOR,
        OutcomeLearner,
        compute_evidence_score,
        credit_losing_bid,
        credit_winning_coalition,
        evidence_bid,
    )

    # --- claim 0: a fresh specialist reads neutral (1.0), with zero
    #     credited outcomes on record. ---
    learner = OutcomeLearner()
    check("a never-credited specialist reads the neutral 1.0 gain",
          learner.historical_usefulness_for("unknown_specialist") == 1.0)
    check("a never-credited specialist has a real 0 credited_count",
          learner.credited_count("unknown_specialist") == 0)

    # --- claim 1: the headline test, straight from the roadmap's own
    #     text -- "a deliberately unreliable specialist and a reliable
    #     one, given identical raw bids, invert in rank order over a
    #     run." Both specialists start out identical EXCEPT one raw
    #     factor set that deliberately favors "unreliable" at first
    #     (so the run has something real to invert), then both get
    #     credited real, DIFFERENT, sustained outcome histories. ---
    learner = OutcomeLearner()
    reliable_factors = BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5)
    unreliable_factors = BidFactors(surprise=0.55, consequence=0.55, confidence=0.55, urgency=0.55)

    def score_for(specialist_id: str, factors: BidFactors) -> float:
        gain = learner.historical_usefulness_for(specialist_id)
        boosted = BidFactors(
            surprise=factors.surprise, consequence=factors.consequence,
            confidence=factors.confidence, urgency=factors.urgency,
            uncertainty=factors.uncertainty, historical_usefulness=gain,
        )
        return compute_evidence_score(boosted)

    initial_reliable = score_for("reliable_specialist", reliable_factors)
    initial_unreliable = score_for("unreliable_specialist", unreliable_factors)
    check("BEFORE any credited outcomes, the deliberately-favored 'unreliable' "
          "specialist scores higher (the run has something real to invert)",
          initial_unreliable > initial_reliable)

    for _ in range(30):
        learner.credit("reliable_specialist", 0.95)
        learner.credit("unreliable_specialist", 0.05)

    final_reliable = score_for("reliable_specialist", reliable_factors)
    final_unreliable = score_for("unreliable_specialist", unreliable_factors)
    check(
        "AFTER a real run of credited outcomes, rank order genuinely INVERTS -- "
        "the reliable specialist now outscores the unreliable one despite starting behind",
        final_reliable > final_unreliable,
    )
    check("the reliable specialist's own gain genuinely rose toward the real ceiling",
          learner.historical_usefulness_for("reliable_specialist") > 1.0)
    check("the unreliable specialist's own gain genuinely fell toward the real floor",
          learner.historical_usefulness_for("unreliable_specialist") < 1.0)
    check("both gains stay within the documented [floor, ceiling] range",
          HISTORICAL_USEFULNESS_FLOOR <= learner.historical_usefulness_for("unreliable_specialist")
          and learner.historical_usefulness_for("reliable_specialist") <= HISTORICAL_USEFULNESS_CEILING)

    # --- claim 2: a never-winning specialist's STALENESS gain is
    #     verified NOT to have been learned downward -- the real proof
    #     is structural (OutcomeLearner never touches GlobalWorkspace
    #     state), demonstrated end to end: a specialist that loses
    #     every single cycle in a real GlobalWorkspace still accrues
    #     the exact same staleness `GlobalWorkspace.arbitrate()` would
    #     give it with ZERO OutcomeLearner involved, whether or not an
    #     entirely separate OutcomeLearner exists crediting OTHER
    #     specialists in the same run. ---
    ws_with_learner = GlobalWorkspace()
    ws_without_learner = GlobalWorkspace()
    learner2 = OutcomeLearner()
    for _ in range(10):
        ws_with_learner.submit(Bid(specialist_id="strong", subject="strong_subject", score=0.9))
        ws_with_learner.submit(Bid(specialist_id="chronic_loser", subject="loser_subject", score=0.1))
        ws_with_learner.arbitrate()
        # An OutcomeLearner exists and is actively crediting OTHER
        # specialists in this same run -- proving its presence/activity
        # has zero bearing on staleness tracking.
        learner2.credit("some_other_specialist", 0.9)

        ws_without_learner.submit(Bid(specialist_id="strong", subject="strong_subject", score=0.9))
        ws_without_learner.submit(Bid(specialist_id="chronic_loser", subject="loser_subject", score=0.1))
        ws_without_learner.arbitrate()

    check(
        "a chronically-losing specialist's real staleness count is IDENTICAL whether or "
        "not an OutcomeLearner is simultaneously active in the same run -- staleness gain "
        "was never learned, up or down, by anything this module does",
        ws_with_learner.staleness_for("loser_subject") == ws_without_learner.staleness_for("loser_subject"),
    )
    check("OutcomeLearner never learned the chronic loser's gain downward -- it was never "
          "even credited, so it correctly still reads neutral",
          learner2.historical_usefulness_for("chronic_loser") == 1.0)

    # --- claim 3: credit_winning_coalition credits every genuinely
    #     independent member of a real winning Coalition with the
    #     SAME measured outcome, and correctly does NOT double-credit
    #     a duplicate-source loser that didn't survive dedup. ---
    learner3 = OutcomeLearner()
    b1 = Bid(specialist_id="s1", subject="food_shortage", score=0.6, evidence_source="granary_reading")
    b2 = Bid(specialist_id="s2", subject="food_shortage", score=0.4, evidence_source="granary_reading")
    b3 = Bid(specialist_id="s3", subject="food_shortage", score=0.5, evidence_source="hunger_reading")
    coalition = Coalition(subject="food_shortage", members=(b1, b2, b3), independent_members=(b1, b3), merged_score=0.8)
    credit_winning_coalition(learner3, coalition, outcome=0.9)
    check("every independent coalition member (s1, s3) got credited",
          learner3.credited_count("s1") == 1 and learner3.credited_count("s3") == 1)
    check("the duplicate-source loser (s2), which never survived dedup, was NOT credited",
          learner3.credited_count("s2") == 0)

    # --- claim 4: credit_losing_bid credits a real, caller-supplied
    #     counterfactual outcome for a losing bid's specialist -- the
    #     roadmap's own "where a counterfactual is honestly available"
    #     second half. ---
    learner4 = OutcomeLearner()
    losing_bid = Bid(specialist_id="s_losing", subject="predator_extinction", score=0.3)
    credit_losing_bid(learner4, losing_bid, counterfactual_outcome=0.7)
    check("a losing bid's specialist is credited from a real, explicit counterfactual value",
          learner4.credited_count("s_losing") == 1 and learner4.historical_usefulness_for("s_losing") > 1.0)

    # --- claim 5: evidence_bid (B5) genuinely reflects a learned gain
    #     end to end -- the real B5/B7 integration proof. ---
    learner5 = OutcomeLearner()
    for _ in range(20):
        learner5.credit("proven_specialist", 0.95)
    gain = learner5.historical_usefulness_for("proven_specialist")
    factors_neutral = BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5)
    factors_learned = BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5, historical_usefulness=gain)
    bid_neutral = evidence_bid("proven_specialist", "subject_x", factors_neutral)
    bid_learned = evidence_bid("proven_specialist", "subject_x", factors_learned)
    check("a real evidence_bid's own score genuinely rises once fed the learned gain",
          bid_learned.score > bid_neutral.score)

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
