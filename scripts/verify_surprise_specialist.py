#!/usr/bin/env python3
"""Tier 7 HCA Stage A, A1 (explicit user instruction: "Phase 2 A1"):
`predict()`/`error()` on specialists, precision-weighted surprise
scoring (`hearthmind/cognition/surprise.py`).

A1's own stated test (docs/ROADMAP-2026-07-REMAINING.md): "on the
soak's own event stream, 'content agent socialises' scores < 0.1 and
family-extinction-during-prosperity scores > 2.0." No live archive
exists in this offline environment to replay a real soak's event
stream against, so this script reproduces the two named scenarios
synthetically, same "prove the mechanism, not a specific live archive"
discipline `verify_ml_g3_regime_change.py` used for G3's own stated
test.

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import random
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.cognition.surprise import SURPRISE_VARIANCE_EPSILON, SurpriseSpecialist

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    rng = random.Random(20260804)

    specialist = SurpriseSpecialist()

    # --- predict()/stdev() on a never-observed key ----------------------
    check("predict() on a never-observed key returns the neutral 0.0 prior", specialist.predict("nothing_yet") == 0.0)
    check("stdev() on a never-observed key returns 0.0", specialist.stdev("nothing_yet") == 0.0)
    check("stdev() on a single-observation key returns 0.0 (no variance evidence yet)",
          (specialist.observe("one_obs", 0.5), specialist.stdev("one_obs"))[1] == 0.0)

    # --- the routine, near-identical signal: "content agent socializes",
    #     magnitude clustered tightly around 0.12 (every occurrence of
    #     this exact soak-observed summary reads near-identically) ------
    routine = SurpriseSpecialist()
    routine_key = "cognition:agent_decided_to_socialize"
    for _ in range(200):
        value = max(0.0, min(1.0, rng.gauss(0.12, 0.01)))
        routine.score(routine_key, value)
    # score the NEXT typical occurrence -- error() BEFORE observe(), the
    # real "how surprising is this new instance of a well-established
    # pattern" question a live L1 caller would ask.
    routine_error = routine.error(routine_key, 0.12)
    check(
        f"a routine, near-identical repeated signal scores near-zero surprise "
        f"(error={routine_error:.4f}, A1's own stated bound: < 0.1)",
        routine_error < 0.1,
    )

    # --- the rare, extreme signal: a family-extinction observation on a
    #     fresh key, scored on its very first (and only) occurrence ----
    extinction = SurpriseSpecialist()
    extinction_key = "population:family_extinction_during_prosperity"
    extinction_error = extinction.error(extinction_key, 0.95)
    check(
        f"a rare, severe, first-occurrence signal scores high surprise "
        f"(error={extinction_error:.4f}, A1's own stated bound: > 2.0)",
        extinction_error > 2.0,
    )
    manual = abs(0.95 - 0.0) / (0.0 + SURPRISE_VARIANCE_EPSILON)
    check(
        "the formula matches the doc's own |actual-predicted|/(sigma+eps) by hand",
        abs(extinction_error - manual) < 1e-9,
    )

    # --- precision-weighting: a genuinely NOISY signal (real, wide
    #     variance) should NOT hijack attention for a typical deviation
    #     the way a tightly-clustered signal would for the same raw gap --
    noisy = SurpriseSpecialist()
    noisy_key = "weather:temperature_swing"
    for _ in range(100):
        noisy.observe(noisy_key, rng.uniform(0.0, 1.0))  # wide, genuinely noisy channel
    tight = SurpriseSpecialist()
    tight_key = "cognition:agent_decided_to_socialize"
    for _ in range(100):
        tight.observe(tight_key, max(0.0, min(1.0, rng.gauss(0.5, 0.02))))
    # same raw deviation (0.15) from each channel's own mean (~0.5) —
    # the noisy channel's own history should make this read as far LESS
    # surprising than the tightly-clustered channel's identical gap.
    noisy_score = noisy.error(noisy_key, 0.65)
    tight_score = tight.error(tight_key, 0.65)
    check(
        f"precision-weighting: the same raw deviation scores lower surprise on a "
        f"chronically noisy channel than on a tightly-clustered one "
        f"(noisy={noisy_score:.3f} < tight={tight_score:.3f})",
        noisy_score < tight_score,
    )

    # --- a recurring extreme signal stops surprising you once it's no
    #     longer novel -- the direct proof this is genuine adaptation,
    #     not just "rare things always score high forever" ------------
    recurring = SurpriseSpecialist()
    recurring_key = "population:family_extinction_during_prosperity"
    first_score = recurring.score(recurring_key, 0.95)
    for _ in range(30):
        recurring.score(recurring_key, max(0.0, min(1.0, rng.gauss(0.95, 0.02))))
    later_error = recurring.error(recurring_key, 0.95)
    check(
        f"a recurring severe signal's surprise falls once the specialist has "
        f"genuinely learned it (first={first_score:.3f} -> later={later_error:.3f})",
        later_error < first_score,
    )

    # --- score() is atomic: error-then-observe in one call, matching
    #     two separate calls done in the correct order ------------------
    a = SurpriseSpecialist()
    b = SurpriseSpecialist()
    for value in (0.2, 0.3, 0.25, 0.4, 0.35):
        e = a.error("k", value)
        a.observe("k", value)
        b_score = b.score("k", value)
        check(f"score() atomically reproduces error()-then-observe() for value={value}", abs(e - b_score) < 1e-12)

    # --- method-ordering matters: error() computed AFTER observe() for
    #     the same value silently reads near-zero, the exact bug class
    #     the docstring warns against -- demonstrated, not just asserted
    wrong_order = SurpriseSpecialist()
    wrong_order.observe("k", 0.9)  # observe first (wrong order)
    wrong_order_error = wrong_order.error("k", 0.9)  # scores against a prediction that already includes 0.9
    check(
        "calling observe() before error() for the same value silently understates surprise "
        f"(wrong-order error={wrong_order_error:.4f}, near zero, demonstrating why ordering is load-bearing)",
        wrong_order_error < 0.01,
    )

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
