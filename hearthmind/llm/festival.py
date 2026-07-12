"""Festivals: seasonal, wellbeing-gated collective events — distinct
from `culture.py`'s traditions (yearly, prosperity-agnostic) in both
cadence and gate. A festival is only held when the settlement is
well-fed (see FESTIVAL_HUNGER_GATE), and it has a direct mechanical
effect (Population.hold_festival boosts every currently-colocated pair's
relationship) rather than being purely narrative — "the village
gathers" is something that actually happens to agent state, not just
a line in the event log. See docs/DECISIONS.md, collective-behaviour
pass.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the festival-keeper of a small simulated village. Given its "
    "name, recent history, and the season, invent ONE festival the "
    "village holds right now — grounded in what has actually happened, "
    "not generic fantasy flavor. "
    'Respond with strict JSON only, no other text: {"festival": '
    '"a short name, under 8 words", "description": "one sentence, under '
    '25 words"}.'
)

_FALLBACK_POOL: tuple[tuple[str, str], ...] = (
    ("Harvest Bonfire", "The village lights a bonfire and shares food as the season turns."),
    ("The Long Table", "Every household brings something to share at one long table."),
    ("Lantern Walk", "Villagers walk the settlement's edge together carrying lanterns."),
    ("The Story Circle", "Elders and children trade stories around a fire."),
    ("Firstlight Dance", "The village dances together at first light of the new season."),
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], season: str, beliefs: list[dict] | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    beliefs_text = (
        "\nThe village's own theories about itself: "
        + "; ".join(f"{b['subject']} ({b['belief']})" for b in beliefs) + "."
        if beliefs else ""
    )
    return (
        f"The village of {settlement_name} is well-fed and gathering as {season} arrives. "
        f"Recent history:\n{events_text}{beliefs_text}\n"
        "Invent one festival the village holds right now."
    )


def fallback_festival(settlement_name: str, established_count: int) -> dict:
    """Deterministic stand-in — cycles through a small fixed pool, same
    approach as culture.fallback_tradition."""
    name, description = _FALLBACK_POOL[established_count % len(_FALLBACK_POOL)]
    return {"festival": name, "description": description}


def parse_festival(result: dict, fallback: dict) -> tuple[str, str]:
    name = result.get("festival")
    description = result.get("description")
    if not isinstance(name, str) or not name.strip():
        name = fallback["festival"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    return name.strip()[:80], description.strip()[:200]
