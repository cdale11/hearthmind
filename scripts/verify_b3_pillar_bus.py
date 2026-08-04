#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B3 (explicit user instruction: "Start B3"):
`PillarBus`, the real broadcast bus replacing `SimulationEngine._send_
pillar_message`'s ~29 hand-wired sender/receiver arrows with a genuine
pillar-generic subscription mechanism.

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.cognition.pillar import default_innovation_pillar, default_nature_pillar
from hearthmind.cognition.workspace import Bid, GlobalWorkspace, PillarBus

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def generic_mirror_handler(pillar):
    """A single handler, usable by ANY pillar for ANY sender -- no
    branch anywhere on `bid.specialist_id` naming who sent it. This is
    the literal proof B3's own test demands: the SAME function, wired
    once, works whether the winning bid came from Nature, Village,
    Humans, or anyone else the bus ever arbitrates for."""
    def _handle(bid: Bid) -> None:
        pillar.upsert_world_model(tick=0, subject=bid.subject, belief=bid.reason,
                                   confidence=0.8, status="observation", source=bid.specialist_id)
    return _handle


def decide_innovation_focus(pillar, candidates: list[str]) -> str:
    """A synthetic stand-in for a real Innovation decision, same real
    shape this codebase's own Tier 0 sites already use elsewhere
    (`max(candidates, key=pillar.subject_confidence)`, first-max-wins
    on a genuine tie) -- proves the bus content actually reaches and
    MOVES a downstream decision, not just that it landed in a dict."""
    return max(candidates, key=lambda c: pillar.subject_confidence(c))


def main() -> int:
    innovation = default_innovation_pillar()
    candidates = ["agriculture", "metallurgy", "predator_extinction_remedies"]

    # --- baseline: with nothing ever broadcast, every candidate reads
    #     zero confidence -- first-max-wins picks the first candidate,
    #     same "no lean anywhere reproduces the original pick" parity
    #     discipline every Tier 0 site already holds to. ---
    baseline_pick = decide_innovation_focus(innovation, candidates)
    check("baseline (nothing broadcast yet) picks the first candidate on an honest tie",
          baseline_pick == "agriculture")

    # --- the headline test: a real Nature belief, published through
    #     the bus's GENERIC subscription mechanism, measurably moves
    #     Innovation's decision -- with ZERO Nature-specific code
    #     anywhere in Innovation's own handler or decision function. ---
    bus = PillarBus()
    bus.subscribe("innovation", generic_mirror_handler(innovation))
    check("the bus reports exactly one real subscriber after subscribing", bus.subscriber_count() == 1)

    nature = default_nature_pillar()  # constructed but deliberately unused by the bus/handler --
    # proof that NOTHING about Nature's own identity is required anywhere in this wiring; only
    # the Bid it submits matters, and the bus doesn't care or know it came from "nature" at all.
    del nature
    bus.submit(Bid(
        specialist_id="nature", subject="predator_extinction_remedies",
        score=0.9, reason="the predator packs have vanished region-wide; livestock losses have stopped",
    ))
    winner = bus.publish_cycle()
    check("the Nature-submitted bid genuinely won this cycle's arbitration",
          winner is not None and winner.specialist_id == "nature")

    moved_pick = decide_innovation_focus(innovation, candidates)
    check(
        "Innovation's own decision genuinely changed to the subject Nature's belief named -- "
        "the real proof a Nature belief measurably moves an Innovation decision with no "
        "Nature-specific code anywhere in the path",
        moved_pick == "predator_extinction_remedies",
    )
    check("the moved decision is a genuine change from the untouched baseline",
          moved_pick != baseline_pick)

    # --- the SAME generic handler, unmodified, correctly serves a
    #     totally different sender too -- the property a hand-wired
    #     arrow could never have without a second dedicated call. ---
    bus.submit(Bid(specialist_id="village", subject="agriculture", score=0.95,
                    reason="three consecutive harvests have failed; the fields need real reform"))
    winner2 = bus.publish_cycle()
    check("a second, entirely different sender (Village, not Nature) also wins its own cycle",
          winner2 is not None and winner2.specialist_id == "village")
    moved_pick2 = decide_innovation_focus(innovation, candidates)
    check(
        "the identical unmodified handler correctly mirrors Village's content too -- no code "
        "change was needed to add a new sender, the literal point of a generic bus",
        moved_pick2 == "agriculture",
    )

    # --- multi-subscriber broadcast: every subscribed pillar hears the
    #     SAME real winner, not just one designated receiver. ---
    bus2 = PillarBus()
    reflection_received: list[Bid] = []
    humans_received: list[Bid] = []
    bus2.subscribe("reflection", lambda b: reflection_received.append(b))
    bus2.subscribe("humans", lambda b: humans_received.append(b))
    bus2.submit(Bid(specialist_id="nature", subject="drought", score=0.7, reason="a real drought"))
    win3 = bus2.publish_cycle()
    check("every subscribed pillar receives the exact same real winning bid",
          len(reflection_received) == 1 and len(humans_received) == 1
          and reflection_received[0] is win3 and humans_received[0] is win3)

    # --- unsubscribe genuinely stops future delivery ---
    bus2.unsubscribe("humans")
    bus2.submit(Bid(specialist_id="village", subject="feud", score=0.5, reason="a feud"))
    bus2.publish_cycle()
    check("unsubscribing genuinely stops future delivery to that pillar",
          len(humans_received) == 1 and len(reflection_received) == 2)

    # --- a genuinely empty cycle never calls broadcast at all (no
    #     subscriber is ever invoked with a fabricated winner) ---
    bus3 = PillarBus()
    called = {"count": 0}
    bus3.subscribe("village", lambda b: called.__setitem__("count", called["count"] + 1))
    empty_winner = bus3.publish_cycle()
    check("a genuinely empty cycle returns None and never invokes any subscriber",
          empty_winner is None and called["count"] == 0)

    # --- PillarBus can wrap an EXISTING GlobalWorkspace (composes with
    #     B1/B2 rather than reimplementing arbitration) ---
    shared_ws = GlobalWorkspace()
    bus4 = PillarBus(workspace=shared_ws)
    check("PillarBus reuses a caller-supplied GlobalWorkspace rather than always building its own",
          bus4.workspace is shared_ws)
    bus4.submit(Bid(specialist_id="x", subject="s", score=0.1))
    bus4.publish_cycle()
    check("submitting/arbitrating through the bus genuinely drives the shared workspace's own history",
          len(shared_ws.history) == 1)

    # --- re-subscribing under the same name replaces, never duplicates ---
    bus5 = PillarBus()
    calls_a: list[str] = []
    calls_b: list[str] = []
    bus5.subscribe("village", lambda b: calls_a.append("a"))
    bus5.subscribe("village", lambda b: calls_b.append("b"))  # replaces the first handler
    bus5.submit(Bid(specialist_id="x", subject="s", score=1.0))
    bus5.publish_cycle()
    check("re-subscribing the same pillar name replaces the old handler, never stacks both",
          calls_a == [] and calls_b == ["b"])

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
