#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B4 (explicit user instruction: "Start B4"):
coalition formation -- `form_coalitions`/`Coalition`/`merged_coalition_
score` in `hearthmind/cognition/workspace.py`. Bids naming the same
subject merge, superadditively but sublinearly, counting only
genuinely independent bidders.

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.cognition.workspace import Bid, form_coalitions, merged_coalition_score

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # --- the roadmap's own two stated tests, both thresholds computed
    #     and confirmed by hand before writing this assertion: five
    #     independent mild (0.35) corroborating bids on one subject
    #     genuinely beat one strong (0.85) isolated bid on another. ---
    MILD, STRONG = 0.35, 0.85
    bids = [Bid(specialist_id=f"mild{i}", subject="family_lines_thinning", score=MILD) for i in range(5)]
    bids.append(Bid(specialist_id="solo", subject="a_single_strong_reading", score=STRONG))
    coalitions = {c.subject: c for c in form_coalitions(bids)}
    check(
        "five independent mild (0.35) corroborating bids beat one strong isolated (0.85) bid",
        coalitions["family_lines_thinning"].merged_score > coalitions["a_single_strong_reading"].merged_score,
    )

    # --- ten weak (0.1) corroborating bids still lose to one genuine
    #     crisis reading (0.95) -- the ceiling half of the same test. ---
    WEAK, CRISIS = 0.1, 0.95
    bids2 = [Bid(specialist_id=f"weak{i}", subject="minor_grumbling", score=WEAK) for i in range(10)]
    bids2.append(Bid(specialist_id="alarm", subject="genuine_crisis", score=CRISIS))
    coalitions2 = {c.subject: c for c in form_coalitions(bids2)}
    check(
        "ten weak (0.1) corroborating bids still lose to one genuine crisis (0.95) reading",
        coalitions2["genuine_crisis"].merged_score > coalitions2["minor_grumbling"].merged_score,
    )

    # --- exact formula match by hand: 1 - (1-s)^n, no surprises ---
    check("merged score matches the noisy-OR formula exactly by hand computation",
          abs(coalitions["family_lines_thinning"].merged_score - (1 - (1 - MILD) ** 5)) < 1e-12
          and abs(coalitions2["minor_grumbling"].merged_score - (1 - (1 - WEAK) ** 10)) < 1e-12)

    # --- a lone bid's coalition reproduces its own raw score exactly
    #     (B1's own documented "single-bidder cycle" guarantee held) ---
    solo_score = merged_coalition_score((Bid(specialist_id="x", subject="s", score=0.42),))
    check("a coalition of one reproduces that bid's own raw score exactly", abs(solo_score - 0.42) < 1e-12)

    # --- independence: two bids sharing an evidence_source count as
    #     ONE bidder -- the merged score should equal the higher of
    #     the two, NOT the noisy-OR boost two genuinely independent
    #     bids at the same scores would produce. ---
    duplicate_bids = (
        Bid(specialist_id="wrapper_a", subject="s", score=0.4, evidence_source="raw_signal_x"),
        Bid(specialist_id="wrapper_b", subject="s", score=0.6, evidence_source="raw_signal_x"),
    )
    dup_score = merged_coalition_score(duplicate_bids)
    check("two bids sharing an evidence_source collapse to the higher raw score, not a noisy-OR boost",
          abs(dup_score - 0.6) < 1e-12)
    independent_equivalent = merged_coalition_score((
        Bid(specialist_id="a", subject="s", score=0.4),
        Bid(specialist_id="b", subject="s", score=0.6),
    ))
    check(
        "the SAME two raw scores, WITHOUT a shared evidence_source, genuinely score higher "
        "than the deduped case -- proof the independence check is load-bearing, not a no-op",
        independent_equivalent > dup_score,
    )

    # --- form_coalitions itself surfaces the dedup correctly ---
    c = form_coalitions(list(duplicate_bids))[0]
    check("Coalition.members keeps every raw bid, including the deduped-out one",
          len(c.members) == 2)
    check("Coalition.independent_members keeps only the higher-scoring bid from a shared source",
          len(c.independent_members) == 1 and c.independent_members[0].specialist_id == "wrapper_b")

    # --- same specialist_id bidding twice on the same subject (no
    #     evidence_source set) also collapses via the specialist_id
    #     fallback -- accidental duplicate submission isn't double-
    #     counted either. ---
    same_specialist = (
        Bid(specialist_id="nature", subject="drought", score=0.3),
        Bid(specialist_id="nature", subject="drought", score=0.5),
    )
    check("two bids from the same specialist_id (no evidence_source) also collapse to one",
          len(_independent := form_coalitions(list(same_specialist))[0].independent_members) == 1
          and _independent[0].score == 0.5)

    # --- mixed-subject grouping: bids across several subjects form
    #     separate, correctly-membered coalitions ---
    mixed = [
        Bid(specialist_id="a", subject="alpha", score=0.5),
        Bid(specialist_id="b", subject="beta", score=0.6),
        Bid(specialist_id="c", subject="alpha", score=0.4),
    ]
    mixed_coalitions = {c.subject: c for c in form_coalitions(mixed)}
    check("mixed-subject bids form the correct number of separate coalitions", len(mixed_coalitions) == 2)
    check("each coalition holds exactly the members naming its own subject",
          {b.specialist_id for b in mixed_coalitions["alpha"].members} == {"a", "c"}
          and {b.specialist_id for b in mixed_coalitions["beta"].members} == {"b"})

    # --- empty input never crashes ---
    check("an empty bid list produces an empty coalition list, no crash", form_coalitions([]) == [])
    check("merged_coalition_score of an empty tuple is 0.0, not a crash", merged_coalition_score(()) == 0.0)

    # --- bounds: the merged score never exceeds 1.0 regardless of how
    #     much independent evidence piles in -- the real "sublinear/
    #     saturating" proof, not just the two-subject comparison
    #     above. ---
    many = tuple(Bid(specialist_id=f"s{i}", subject="s", score=0.9) for i in range(8))
    many_score = merged_coalition_score(many)
    check("a coalition score never exceeds 1.0 even with many strong independent bids",
          many_score <= 1.0)
    check("the bound is genuinely approached (superadditive proof), not just clamped low",
          many_score > 0.99)

    # --- deterministic ordering: no RNG anywhere in this module ---
    check("form_coalitions returns subjects in first-appearance order, not re-sorted",
          [c.subject for c in form_coalitions(mixed)] == ["alpha", "beta"])

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
