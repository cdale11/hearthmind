#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B5 (explicit user instruction: "start B5"):
evidence-based scoring -- `BidFactors`/`compute_evidence_score`/
`evidence_bid` in `hearthmind/cognition/workspace.py`. Six of the
roadmap's own seven named factors as a real, auditable formula
(staleness, the seventh, stays `GlobalWorkspace`'s own tracked state).

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import math
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.cognition.workspace import (
    BidFactors, EVIDENCE_UNCERTAINTY_BETA, GlobalWorkspace,
    compute_evidence_score, evidence_bid,
)

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # --- the roadmap's own stated test: with expected value (the base
    #     factor combination) held equal, the higher-uncertainty
    #     coalition wins -- the direct proof exploration is real and
    #     deterministic, not randomness. Numbers hand-computed before
    #     writing the assertion. ---
    base_factors = dict(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5)
    low_uncertainty = BidFactors(**base_factors, uncertainty=0.1, historical_usefulness=1.0)
    high_uncertainty = BidFactors(**base_factors, uncertainty=0.9, historical_usefulness=1.0)
    score_low = compute_evidence_score(low_uncertainty)
    score_high = compute_evidence_score(high_uncertainty)
    check(
        "with expected value (base factors) held exactly equal, the higher-uncertainty "
        "coalition scores higher -- exploration is real, not randomness",
        score_high > score_low,
    )
    check("both scores share the identical base (0.5) before the uncertainty bonus diverges them",
          abs((score_low - EVIDENCE_UNCERTAINTY_BETA * math.sqrt(0.1))
              - (score_high - EVIDENCE_UNCERTAINTY_BETA * math.sqrt(0.9))) < 1e-9)

    # --- exact formula match by hand ---
    f = BidFactors(surprise=0.8, consequence=0.6, confidence=0.4, urgency=0.2,
                    uncertainty=0.25, historical_usefulness=1.5)
    expected_base = (0.8 + 0.6 + 0.4 + 0.2) / 4.0
    expected = expected_base * 1.5 + EVIDENCE_UNCERTAINTY_BETA * math.sqrt(0.25)
    check("compute_evidence_score matches the formula exactly by hand computation",
          abs(compute_evidence_score(f) - expected) < 1e-12)

    # --- historical_usefulness is a genuine multiplicative gain, not
    #     an additive offset: halving it should roughly halve the
    #     gained portion (with uncertainty=0, exactly halve the whole
    #     score). ---
    neutral = BidFactors(surprise=0.6, consequence=0.6, confidence=0.6, urgency=0.6,
                          uncertainty=0.0, historical_usefulness=1.0)
    halved = BidFactors(surprise=0.6, consequence=0.6, confidence=0.6, urgency=0.6,
                         uncertainty=0.0, historical_usefulness=0.5)
    check("historical_usefulness is genuinely multiplicative -- halving it exactly halves "
          "the score (uncertainty=0 isolates the gain term)",
          abs(compute_evidence_score(halved) - compute_evidence_score(neutral) / 2.0) < 1e-12)

    # --- a proven-reliable source (gain > 1.0) amplifies; a chronically
    #     unreliable one (gain < 1.0) attenuates -- both directions real ---
    amplified = BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5,
                            historical_usefulness=2.0)
    attenuated = BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5,
                             historical_usefulness=0.2)
    check("a reliability gain above 1.0 amplifies the base score above the neutral case",
          compute_evidence_score(amplified) > compute_evidence_score(
              BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5)))
    check("a reliability gain below 1.0 attenuates the base score below the neutral case",
          compute_evidence_score(attenuated) < compute_evidence_score(
              BidFactors(surprise=0.5, consequence=0.5, confidence=0.5, urgency=0.5)))

    # --- clamping: out-of-range factors never crash or produce a
    #     garbage (e.g. negative or wildly inflated) score ---
    out_of_range = BidFactors(surprise=1.5, consequence=-0.5, confidence=2.0, urgency=-1.0,
                               uncertainty=5.0, historical_usefulness=-3.0)
    oor_score = compute_evidence_score(out_of_range)
    check("out-of-range factor values never crash and produce a real, finite score",
          isinstance(oor_score, float) and oor_score == oor_score)  # NaN check via self-inequality
    check("a negative historical_usefulness clamps to 0.0 (a gain can never flip a bid's sign)",
          abs(oor_score - EVIDENCE_UNCERTAINTY_BETA * math.sqrt(1.0)) < 1e-9)

    # --- provenance is a real, preserved field, not decorative ---
    prov = BidFactors(surprise=0.3, consequence=0.3, confidence=0.3, urgency=0.3,
                       provenance={"surprise": "SurpriseSpecialist reading 2.1 sigma above mean"})
    check("provenance is preserved on BidFactors, reachable for a future Observatory panel",
          prov.provenance.get("surprise") == "SurpriseSpecialist reading 2.1 sigma above mean")

    # --- evidence_bid builds a real Bid with every OTHER field passed
    #     straight through untouched ---
    resolver_called = {"n": 0}
    b = evidence_bid(
        specialist_id="nature", subject="predator_extinction",
        factors=BidFactors(surprise=0.9, consequence=0.8, confidence=0.7, urgency=0.6),
        resolver=lambda: resolver_called.__setitem__("n", resolver_called["n"] + 1),
        reason="predator packs vanished region-wide", evidence_source="wildlife_census",
    )
    check("evidence_bid's score matches compute_evidence_score for the same factors",
          abs(b.score - compute_evidence_score(BidFactors(surprise=0.9, consequence=0.8,
                                                             confidence=0.7, urgency=0.6))) < 1e-12)
    check("evidence_bid passes specialist_id/subject/reason/evidence_source through untouched",
          b.specialist_id == "nature" and b.subject == "predator_extinction"
          and b.reason == "predator packs vanished region-wide" and b.evidence_source == "wildlife_census")
    check("evidence_bid's resolver is the real caller-supplied callable, never invoked by construction",
          resolver_called["n"] == 0 and b.resolver is not None)

    # --- real integration: two evidence_bids fed into a real
    #     GlobalWorkspace arbitrate correctly by their computed scores,
    #     composing with B1/B2's own untouched arbitration/staleness ---
    ws = GlobalWorkspace()
    ws.submit(evidence_bid("village", "routine_matter",
                            BidFactors(surprise=0.1, consequence=0.1, confidence=0.5, urgency=0.1)))
    ws.submit(evidence_bid("nature", "genuine_crisis",
                            BidFactors(surprise=0.95, consequence=0.9, confidence=0.85, urgency=0.9)))
    winner = ws.arbitrate()
    check("a genuinely stronger evidence-scored bid wins real arbitration through the unmodified workspace",
          winner is not None and winner.specialist_id == "nature")

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
