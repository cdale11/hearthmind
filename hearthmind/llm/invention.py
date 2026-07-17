"""Inventions: rare, LLM-authored tech-tier unlocks for a prosperous,
named settlement — a rarer sibling of `hearthmind/llm/culture.py`'s
traditions, gated by surplus (currency/materials) rather than a flat
yearly cadence. Each invention permanently raises `Settlement.tech_level`,
which boosts construction/repair work and cultivated-food yield (see
TECH_BONUS_PER_LEVEL). See docs/DECISIONS.md, E3.

`SYSTEM_PROMPT` deliberately widened (v0.86.7, explicit user direction:
"sometimes NPCs can uncover novel ways to get food, new buildings,
medical innovation, something the simulation was never built for in
the first place") beyond its original build/farm framing — the LLM is
invited toward whatever this settlement's own specific history
plausibly leads to (a husbandry technique, a genuinely new food source,
a hardship-born medical remedy, or anything else), not steered into a
fixed category list. Mechanically this is still just a flavor string —
the only guaranteed effect remains the flat `tech_level += 1` bump
(`SimulationEngine._maybe_schedule_invention`) — so a wilder answer
never risks breaking anything downstream; it only changes what gets
narrated as the reason tech_level went up.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the craft-keeper of a small simulated village. Given its "
    "name, recent history, and inventions already made, invent ONE new "
    "practical technique or tool this village now uses — grounded in "
    "what has actually happened, not generic fantasy flavor. It doesn't "
    "have to be building or farming: a clever new way to raise animals "
    "or fish, a genuinely novel food source nobody expected, a remedy or "
    "medical technique born from a real hardship the village lived "
    "through, or anything else this particular history plausibly leads "
    "to — the goal is something that feels like it grew out of these "
    "specific people's specific experience, not a generic tech-tree "
    "entry. "
    'Respond with strict JSON only, no other text: {"invention": '
    '"a short name, under 8 words", "description": "one sentence, under '
    '25 words"}.'
)

_FALLBACK_POOL: tuple[tuple[str, str], ...] = (
    ("The Iron Ploughshare", "A sturdier plough blade lets fields be worked faster."),
    ("Post-and-Beam Framing", "A stronger timber frame speeds every new structure."),
    ("The Root Cellar", "Cool storage dug below ground keeps food from spoiling."),
    ("Crop Rotation", "Fields are rested and rotated, yielding more over time."),
    ("The Grain Quern", "A hand-turned mill grinds harvests faster than before."),
    ("The Rain Cistern", "A dug cistern catches rainwater, easing the well's burden in dry spells."),
    ("Woven Fencing", "Interlaced hedging keeps livestock and wandering feet out of tended fields."),
    ("The Handcart Axle", "A stronger axle lets carts haul heavier loads without breaking."),
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], existing_inventions: list[str], tech_level: int,
    beliefs: list[dict] | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    inventions_text = "; ".join(existing_inventions) if existing_inventions else "None yet."
    beliefs_text = (
        "\nThe village's own theories about itself: "
        + "; ".join(f"{b['subject']} ({b['belief']})" for b in beliefs) + "."
        if beliefs else ""
    )
    return (
        f"The village of {settlement_name} has grown prosperous (tech tier {tech_level}). "
        f"Recent history:\n{events_text}\n"
        f"Inventions already made: {inventions_text}{beliefs_text}\n"
        "Invent one new practical technique or tool this village now uses."
    )


def fallback_invention(settlement_name: str, tech_level: int, established_count: int) -> dict:
    """Deterministic stand-in — cycles through a small fixed pool, same
    approach as culture.fallback_tradition."""
    name, description = _FALLBACK_POOL[established_count % len(_FALLBACK_POOL)]
    return {"invention": name, "description": description}


def parse_invention(result: dict, fallback: dict) -> tuple[str, str]:
    name = result.get("invention")
    description = result.get("description")
    if not isinstance(name, str) or not name.strip():
        name = fallback["invention"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    return name.strip()[:80], description.strip()[:200]
