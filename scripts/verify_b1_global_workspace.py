#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B1 (explicit user instruction: "Start phase 3
B1"): the base coalition-bidding/arbitration engine --
`hearthmind/cognition/workspace.py`'s `Bid`/`GlobalWorkspace`.

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.cognition.surprise import SurpriseSpecialist
from hearthmind.cognition.workspace import Bid, COMPETITION_LOG_MAX, GlobalWorkspace

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # --- basic arbitration: highest score wins, others become losers ---
    ws = GlobalWorkspace()
    ws.submit(Bid(specialist_id="village", subject="food_shortage", score=0.4))
    ws.submit(Bid(specialist_id="nature", subject="predator_extinction", score=0.9))
    ws.submit(Bid(specialist_id="humans", subject="mira_grief", score=0.2))
    winner = ws.arbitrate()
    check("the highest-score bid wins arbitration", winner is not None and winner.specialist_id == "nature")
    check("the pending queue is empty after arbitrate()", ws.pending_count() == 0)
    check("a genuinely empty cycle after arbitration returns None on the next call",
          ws.arbitrate() is None)

    # --- the full competition is logged: winner + every real loser ---
    record = ws.history[-2]  # the winning cycle, not the empty one just logged
    check("the competition record names the real winner", record.winner is not None and record.winner.specialist_id == "nature")
    check("the competition record names both real losers", {b.specialist_id for b in record.losers} == {"village", "humans"})
    check("an empty cycle is itself a real, recorded outcome (not skipped)",
          ws.history[-1].winner is None and ws.history[-1].losers == ())

    # --- deterministic tie-break: no RNG anywhere, first-submitted wins ---
    ws2 = GlobalWorkspace()
    ws2.submit(Bid(specialist_id="a", subject="s", score=0.5))
    ws2.submit(Bid(specialist_id="b", subject="s", score=0.5))
    ws2.submit(Bid(specialist_id="c", subject="s", score=0.5))
    tie_winner = ws2.arbitrate()
    check("an exact three-way tie deterministically picks the FIRST submitted bid",
          tie_winner is not None and tie_winner.specialist_id == "a")
    # Repeat the identical scenario several times -- a real proof of
    # determinism, not an assumption from reading the code once.
    all_same = True
    for _ in range(20):
        ws_repeat = GlobalWorkspace()
        ws_repeat.submit(Bid(specialist_id="a", subject="s", score=0.5))
        ws_repeat.submit(Bid(specialist_id="b", subject="s", score=0.5))
        ws_repeat.submit(Bid(specialist_id="c", subject="s", score=0.5))
        if ws_repeat.arbitrate().specialist_id != "a":
            all_same = False
            break
    check("the tie-break is genuinely deterministic across 20 repeated identical cycles", all_same)

    # --- cycle counter advances correctly across multiple real cycles ---
    ws3 = GlobalWorkspace()
    ws3.submit(Bid(specialist_id="x", subject="s", score=0.1))
    ws3.arbitrate()
    ws3.submit(Bid(specialist_id="y", subject="s", score=0.1))
    ws3.arbitrate()
    check("the cycle counter genuinely advances one per arbitrate() call",
          ws3.history[0].cycle == 1 and ws3.history[1].cycle == 2)

    # --- broadcast: every real subscriber is called exactly once, with the winner ---
    ws4 = GlobalWorkspace()
    win_bid = Bid(specialist_id="nature", subject="drought", score=0.8)
    ws4.submit(win_bid)
    won = ws4.arbitrate()
    received: list[Bid] = []
    subscribers = [lambda b: received.append(("humans", b)), lambda b: received.append(("village", b))]
    ws4.broadcast(won, subscribers)
    check("every real subscriber receives the exact winning bid",
          len(received) == 2 and all(b is won for _, b in received))

    # --- resolvers are never invoked by workspace code itself (execution-agnostic) ---
    resolver_calls = {"count": 0}

    def real_resolver():
        resolver_calls["count"] += 1
        return "resolved"

    ws5 = GlobalWorkspace()
    ws5.submit(Bid(specialist_id="innovation", subject="new_tech", score=1.0, resolver=real_resolver))
    ws5_winner = ws5.arbitrate()
    ws5.broadcast(ws5_winner, [lambda b: None])
    check(
        "arbitrate()/broadcast() never invoke a winning bid's own resolver "
        "(deliberately execution-agnostic, per the module's own design)",
        resolver_calls["count"] == 0,
    )
    check("the winning bid's resolver is still reachable for the real caller to invoke",
          ws5_winner.resolver is real_resolver and ws5_winner.resolver() == "resolved")

    # --- bounded history: never grows past COMPETITION_LOG_MAX ---
    ws6 = GlobalWorkspace()
    for i in range(COMPETITION_LOG_MAX + 25):
        ws6.submit(Bid(specialist_id=f"s{i}", subject="s", score=float(i)))
        ws6.arbitrate()
    check("the competition history never exceeds its real bound",
          len(ws6.history) == COMPETITION_LOG_MAX)
    check("the bounded history kept the NEWEST cycles, not the oldest",
          ws6.history[-1].winner.specialist_id == f"s{COMPETITION_LOG_MAX + 24}")

    # --- a bare submit() with no arbitrate() never mutates anything else ---
    ws7 = GlobalWorkspace()
    ws7.submit(Bid(specialist_id="a", subject="s", score=0.1))
    check("a pending, un-arbitrated bid produces no history entry yet", ws7.history == [])
    check("a pending, un-arbitrated bid IS counted", ws7.pending_count() == 1)

    # --- real cross-primitive integration: A1's SurpriseSpecialist
    #     feeding real bids into B1's workspace, proving this is a
    #     genuinely usable base for the eventual real migration, not a
    #     mock-only exercise. Three specialists observe the same kind
    #     of routine signal repeatedly (surprise decays toward zero);
    #     a fourth specialist reports a genuinely novel, rare signal
    #     for the first time -- it should win arbitration even though
    #     every OTHER specialist has been "active" every single cycle.
    surprise = SurpriseSpecialist()
    for _ in range(30):
        surprise.score("village:food_shortage", 0.1)
        surprise.score("humans:socialize", 0.1)
        surprise.score("nature:seasonal_migration", 0.1)
    ws8 = GlobalWorkspace()
    ws8.submit(Bid(specialist_id="village", subject="food_shortage",
                    score=surprise.score("village:food_shortage", 0.1)))
    ws8.submit(Bid(specialist_id="humans", subject="socialize",
                    score=surprise.score("humans:socialize", 0.1)))
    ws8.submit(Bid(specialist_id="nature", subject="seasonal_migration",
                    score=surprise.score("nature:seasonal_migration", 0.1)))
    ws8.submit(Bid(specialist_id="reflection", subject="family_extinction",
                    score=surprise.score("reflection:family_extinction", 2.0)))
    real_winner = ws8.arbitrate()
    check(
        "a genuinely novel, rare signal (A1's real SurpriseSpecialist) wins "
        "arbitration over three chronically-routine specialists, even though "
        "every specialist bid this cycle -- the real cross-primitive proof "
        "B1's arbitration is a usable base for a future real migration",
        real_winner is not None and real_winner.specialist_id == "reflection",
    )

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
