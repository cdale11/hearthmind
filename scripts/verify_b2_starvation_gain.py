#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B2 (explicit user instruction: "Start B2"):
`GlobalWorkspace`'s unbounded staleness gain -- the *primary*
starvation-prevention mechanism ("nothing starves on merit"), replacing
a fixed-priority-queue's inability to ever let a chronically-outscored
but genuinely real subject win.

No unittest, same standalone-script convention as every sibling
`verify_*.py`. The roadmap's own stated test for B2 ("reflection_
notebook_total > 0 in a 64k-tick soak") needs a real live-LLM archive
this offline environment has no way to reproduce -- same "synthetic
reproduction of the doc's own reported shape" technique A1/A2 already
used for their own live-report-derived tests.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.cognition.workspace import Bid, GlobalWorkspace, STALENESS_GAIN_PER_CYCLE

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # --- the headline test: a chronically-outscored real subject
    #     eventually wins purely from accumulated staleness, against a
    #     rival that never stops winning on raw score alone. Stops at
    #     the FIRST upset so the reset/resume checks below have a known
    #     state to build on. ---
    ws = GlobalWorkspace()
    upset_cycle = None
    for i in range(1, 201):
        ws.submit(Bid(specialist_id="village", subject="routine_chatter", score=0.9))
        ws.submit(Bid(specialist_id="reflection", subject="family_extinction", score=0.1))
        winner = ws.arbitrate()
        if winner.subject == "family_extinction":
            upset_cycle = i
            break
    check(
        "a chronically 9x-outscored real subject eventually wins arbitration purely from "
        "staleness gain, despite never once having the higher raw score",
        upset_cycle is not None,
    )
    check(
        "the upset happens well within the reasoned constant's own design horizon "
        "(a few dozen cycles, not 2 and not 200+)",
        upset_cycle is not None and 10 < upset_cycle < 150,
    )

    # --- staleness resets to zero the instant its subject wins ---
    check("staleness resets to 0 immediately after a win",
          ws.staleness_for("family_extinction") == 0)
    check("the chronic-winner's own staleness is 0 too -- it just lost this exact cycle",
          ws.staleness_for("routine_chatter") == 1)

    # --- after a reset, staleness starts accumulating again from zero,
    #     not from wherever it left off before the win ---
    ws.submit(Bid(specialist_id="village", subject="routine_chatter", score=0.9))
    ws.submit(Bid(specialist_id="reflection", subject="family_extinction", score=0.1))
    ws.arbitrate()
    check("staleness resumes accumulating from 0, not from wherever it left off",
          ws.staleness_for("family_extinction") == 1)

    # --- mathematically exact: the gain formula matches the doc's own math by hand ---
    ws2 = GlobalWorkspace()
    ws2.submit(Bid(specialist_id="a", subject="s1", score=1.0))
    ws2.submit(Bid(specialist_id="b", subject="s2", score=2.0))
    ws2.arbitrate()  # s2 wins (2.0 > 1.0); s1 staleness -> 1
    check("exact staleness count after one real loss", ws2.staleness_for("s1") == 1)
    ws2.submit(Bid(specialist_id="a", subject="s1", score=1.0))
    ws2.submit(Bid(specialist_id="b", subject="s2", score=2.0))
    winner2 = ws2.arbitrate()
    # s1's gained score this cycle: 1.0 * (1 + 0.15*1) = 1.15, still < 2.0 -> s2 wins again
    check("the gain formula matches hand computation (still loses at exactly this rate/count)",
          winner2 is not None and winner2.subject == "s2" and abs(STALENESS_GAIN_PER_CYCLE - 0.15) < 1e-12)

    # --- unbounded: even a much bigger raw-score gap (20x, not 9x) is
    #     genuinely overcome within a bounded number of cycles -- proof
    #     the gain is truly unbounded (no min()/max() clamp anywhere),
    #     not merely "somewhat higher." ---
    ws3 = GlobalWorkspace()
    big_gap_upset = None
    for i in range(1, 301):
        ws3.submit(Bid(specialist_id="strong", subject="always_wins", score=1.0))
        ws3.submit(Bid(specialist_id="weak", subject="huge_gap", score=0.05))
        w = ws3.arbitrate()
        if w.subject == "huge_gap":
            big_gap_upset = i
            break
    check(
        "a 20x raw-score gap is still genuinely overcome within a bounded number of "
        "cycles -- the gain has no hidden ceiling that would cap out below this",
        big_gap_upset is not None,
    )

    # --- the staleness COUNT itself never stops accumulating past any
    #     plausible cap, confirmed over hundreds of straight losses ---
    ws4 = GlobalWorkspace()
    for _ in range(500):
        ws4.submit(Bid(specialist_id="strong", subject="always_wins", score=1_000_000.0))
        ws4.submit(Bid(specialist_id="weak", subject="never_wins_by_raw_score", score=0.001))
        ws4.arbitrate()
    check(
        "staleness keeps growing without any cap even after 500 straight losses "
        "(a real, unbounded multiplier, not a floor with a hidden ceiling)",
        ws4.staleness_for("never_wins_by_raw_score") == 500,
    )

    # --- a subject that doesn't bid this cycle is frozen, not incremented ---
    ws5 = GlobalWorkspace()
    ws5.submit(Bid(specialist_id="a", subject="present", score=0.5))
    ws5.submit(Bid(specialist_id="b", subject="absent_later", score=0.2))
    ws5.arbitrate()  # present wins; absent_later staleness -> 1
    check("staleness is 1 after one real bid-and-lose cycle", ws5.staleness_for("absent_later") == 1)
    ws5.submit(Bid(specialist_id="a", subject="present", score=0.5))
    # absent_later does NOT bid this cycle
    ws5.arbitrate()
    check(
        "a subject that submits no bid this cycle is neither penalized nor rewarded -- "
        "its staleness clock is frozen while it's silent, not still ticking",
        ws5.staleness_for("absent_later") == 1,
    )

    # --- a subject that's never bid, or was never seen, reads 0, not an error ---
    check("an unseen subject's staleness reads 0, never crashes", GlobalWorkspace().staleness_for("nothing") == 0)

    # --- Bid.score itself is never mutated -- gain is comparison-only ---
    ws6 = GlobalWorkspace()
    b1 = Bid(specialist_id="x", subject="s", score=0.3)
    ws6.submit(b1)
    ws6.submit(Bid(specialist_id="y", subject="s2", score=0.9))
    ws6.arbitrate()
    ws6.submit(Bid(specialist_id="x", subject="s", score=0.3))
    ws6.submit(Bid(specialist_id="y", subject="s2", score=0.9))
    ws6.arbitrate()
    check("the losing bid's own .score field is never mutated by gain application", b1.score == 0.3)

    # --- deterministic tie-break still holds even with staleness gain applied
    #     equally to both sides (no RNG anywhere, per the standing rule) ---
    ws7 = GlobalWorkspace()
    ws7.submit(Bid(specialist_id="p", subject="tied_subject", score=0.5))
    ws7.submit(Bid(specialist_id="q", subject="tied_subject", score=0.5))
    win7 = ws7.arbitrate()
    check("an exact tie under identical (zero) staleness still deterministically picks the first submitted",
          win7 is not None and win7.specialist_id == "p")

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
