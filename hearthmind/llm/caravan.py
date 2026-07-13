"""Caravans: a scoped-down first step toward "external settlements and
trade" (docs/ROADMAP.md, integration milestone). The full ask — multiple
addressable `Settlement` objects trading with each other — remains its
own dedicated session (see docs/DECISIONS.md, "Multiple named
settlements": it touches population/engine/every LLM prompt/the
interface layer/snapshot schema in the same pass, the same reasoning
that's kept it deferred through every H-phase batch). A caravan is the
smallest coherent milestone that still makes "the village is not alone
in the world" mechanically real rather than purely narrative: a rare
monthly event that nudges the settlement's currency/materials (a real
economic exchange with someone outside it) and has a chance to leave
behind a rumor from the wider world — folded into a few colocated
agents' own memories, so it spreads through the *existing* gossip/
teaching contagion machinery rather than a bespoke new one. No new map
entity, no pathfinding, no second Settlement — this is deliberately an
abstract, settlement-wide event, the same shape weather/disasters
already use for something that isn't agent-colocated.
"""
from __future__ import annotations

CARAVAN_CHANCE_PER_MONTH = 0.15
"""Rare — roughly one caravan every ~7 months on average, deliberately
uncommon enough that a visit reads as a genuine event, not routine
trade. Independent of the settlement's own prosperity (a caravan can
visit any settlement, rich or lean) — SETTLE_CHANCE_PER_TICK-style
prosperity gating belongs to *internal* growth, not an external actor's
decision to travel through."""

CARAVAN_CURRENCY_DELTA_RANGE = (-8.0, 15.0)
"""A caravan visit's currency effect — biased positive (selling surplus
to a caravan is more common than buying from one, mirroring a small
village's usual trade position) but can go negative (the village buys
something it needs). Clamped to the settlement's existing currency
capacity/floor by the caller, same as every other currency mutation."""

CARAVAN_MATERIALS_DELTA_RANGE = (-10.0, 6.0)
"""Materials effect, inversely correlated with the currency roll by the
caller (a caravan that pays the village in currency takes materials in
return, and vice versa) — a real barter, not two independent windfalls."""

CARAVAN_RUMOR_CHANCE = 0.5
"""Chance a visiting caravan also leaves behind a rumor from the wider
world — folded into up to CARAVAN_RUMOR_LISTENER_COUNT colocated
agents' own memories (Population._remember), the same mechanism
ordinary in-village gossip already uses, so it can propagate through
existing dialogue/trust contagion rather than a new one."""

CARAVAN_RUMOR_LISTENER_COUNT = 3
"""How many living agents (chosen deterministically, not necessarily
colocated with each other) hear a caravan's rumor firsthand — a small
seed, not an instant settlement-wide broadcast; if it spreads further,
that's the existing gossip system doing the spreading, not this one."""

SYSTEM_PROMPT = (
    "You are narrating a rare traveling caravan's visit to a small simulated "
    "village — traders from beyond it, passing through. Given the village's "
    "name and recent history, describe ONE brief, grounded exchange (what "
    "they traded, in plain terms) and, if it fits, one short piece of news "
    "or rumor they brought from outside the village — something that "
    "happened elsewhere, not about anyone in this village. Keep both "
    "grounded and mundane, not fantastical. "
    'Respond with strict JSON only, no other text: {"description": "one '
    'sentence, under 25 words, describing the exchange", "rumor": "one '
    'sentence, under 25 words, news from outside the village, or empty '
    'string if the caravan brought none"}.'
)

_FALLBACK_POOL: tuple[tuple[str, str], ...] = (
    ("A caravan passed through, trading dyed cloth and salt for the village's spare grain.", ""),
    (
        "Traders stopped at the village edge, exchanging tools for surplus materials.",
        "They mentioned a larger settlement two rivers over had a hard winter.",
    ),
    ("A lone trader's cart rolled through, swapping tea and spices for coin.", ""),
    (
        "A small caravan camped a night, trading glassware for stored goods.",
        "They spoke of a road being cleared somewhere to the east.",
    ),
    ("Traders came through briefly, buying up whatever surplus the village could spare.", ""),
    (
        "A caravan of leatherworkers passed through, trading tanned hides for tools.",
        "They warned of wolves growing bolder along the northern trade route.",
    ),
    ("A weary-looking trader swapped a cask of preserved fruit for a bundle of firewood.", ""),
    (
        "A small train of pack mules stopped to trade woven baskets for stored grain.",
        "They spoke of a festival held in a distant town to celebrate a good harvest.",
    ),
)


def build_prompt(settlement_name: str, recent_events: list[dict]) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    return (
        f"A caravan has arrived at the village of {settlement_name}.\n"
        f"Recent history:\n{events_text}\n"
        "Describe the exchange, and any news from outside the village they brought."
    )


def fallback_caravan(seed_hint: int) -> dict:
    import random
    description, rumor = _FALLBACK_POOL[seed_hint % len(_FALLBACK_POOL)]
    return {"description": description, "rumor": rumor}


def parse_caravan(result: dict, fallback: dict) -> tuple[str, str]:
    description = result.get("description")
    rumor = result.get("rumor")
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    if not isinstance(rumor, str):
        rumor = fallback["rumor"]
    return description.strip()[:200], rumor.strip()[:200]
