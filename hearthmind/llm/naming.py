"""Settlement naming: a one-time LLM decision, not just a random
prefix+suffix draw.

The instant a settlement's first building stands, `World.tick()` still
gives it an immediate deterministic placeholder name (see
`settlement.naming.generate_settlement_name`) — other systems (town_brain,
chronicle, festivals, beliefs, vehicles) all gate on `settlement.name`
being non-empty, so naming can't wait on a 5-30 second LLM round trip
without stalling everything else that already assumes a name exists the
same tick a settlement is born. Instead, `SimulationEngine` schedules this
job once, in the background, right after that placeholder is set; when it
resolves, the placeholder is replaced with the LLM's more evocative,
context-aware choice (informed by the founding scenario and terrain, not
a bare random draw) — the deterministic name is a bridge, not the final
answer. See docs/DECISIONS.md, "naming mechanism follow-up."
"""
from __future__ import annotations

from hearthmind.settlement.naming import generate_settlement_name

SYSTEM_PROMPT = (
    "You are naming a small village in a simulated world, at the moment "
    "its first building has just been completed. Give it a plausible "
    "English-style place name (one or two words, no modern branding, no "
    "punctuation beyond a space) that fits the land it was founded on. "
    'Respond with strict JSON only, no other text: {"name": "the '
    'village\'s name"}.'
)


def build_prompt(founding_scenario: str, biome_summary: str, era: str) -> str:
    scenario_text = f" It was founded on this land: {founding_scenario}" if founding_scenario else ""
    biome_text = f" The surrounding country is mostly {biome_summary}." if biome_summary else ""
    return (
        f"A village's first building has just been completed, at the dawn of its {era} era."
        f"{scenario_text}{biome_text} Name the village."
    )


def fallback_name(seed_hint: int) -> dict:
    import random
    return {"name": generate_settlement_name(random.Random(seed_hint))}


def parse_name(result: dict, fallback: dict) -> str:
    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        return fallback["name"]
    cleaned = " ".join(name.strip().split())[:40]
    return cleaned if cleaned else fallback["name"]
