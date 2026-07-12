"""Inventions: rare, LLM-authored tech-tier unlocks for a prosperous,
named settlement — a rarer sibling of `hearthmind/llm/culture.py`'s
traditions, gated by surplus (currency/materials) rather than a flat
yearly cadence. Each invention permanently raises `Settlement.tech_level`,
which boosts construction/repair work and cultivated-food yield (see
TECH_BONUS_PER_LEVEL). See docs/DECISIONS.md, E3.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the craft-keeper of a small simulated village. Given its "
    "name, recent history, and inventions already made, invent ONE new "
    "practical technique or tool that improves how the village builds or "
    "grows food — grounded in what has actually happened, not generic "
    "fantasy flavor. "
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
