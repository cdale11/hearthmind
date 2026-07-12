"""The "town brain": a seasonal LLM decision that sets the settlement's
current civic priority — the concrete expression of "the LLM is the
brain of the town" (see CLAUDE.md). Unlike traditions/festivals/
inventions, which are purely narrative-with-a-side-effect, this
decision measurably steers mechanics: `Settlement.current_priority`
feeds `buildings.choose_building_kind`'s weighting at every future
construction founding until the next seasonal decision. Player
intervention (`POST /intervene/town-brain`) is folded in as one input
among the real settlement stats/history — a deliberately subtle nudge,
not a command. See docs/DECISIONS.md, "LLM-as-brain batch."
"""
from __future__ import annotations

_VALID_PRIORITIES = ("growth", "food", "commerce", "education", "health", "defense")

SYSTEM_PROMPT = (
    "You are the quiet civic instinct of a small simulated village — not a "
    "ruler, just the sense of what the village needs most right now. Given "
    "its stats and recent history, choose ONE current priority. "
    'Respond with strict JSON only, no other text: {"priority": one of '
    '"growth", "food", "commerce", "education", "health", "defense", '
    '"rationale": "one sentence, under 20 words, grounded in the actual '
    'stats/history given"}.'
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], population_summary: dict,
    settlement_summary: dict, player_whispers: list[str], beliefs: list[dict] | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    whisper_text = (
        f"\nSome in the village have been murmuring: {'; '.join(player_whispers)}."
        if player_whispers else ""
    )
    beliefs_text = (
        "\nThe village's own theories about itself so far: "
        + "; ".join(f"{b['subject']} ({b['belief']})" for b in beliefs)
        + "."
        if beliefs else ""
    )
    return (
        f"The village of {settlement_name}: population {population_summary.get('total', 0)} "
        f"(avg hunger {population_summary.get('avg_hunger', 0):.2f}), "
        f"materials {settlement_summary.get('materials', 0):.1f}/{settlement_summary.get('materials_capacity', 0):.0f}, "
        f"currency {settlement_summary.get('currency', 0):.1f}/{settlement_summary.get('currency_capacity', 0):.0f}, "
        f"education {settlement_summary.get('education_level', 0):.2f}, "
        f"{settlement_summary.get('standing', 0)} standing structures "
        f"({settlement_summary.get('hospitals', 0)} hospitals, {settlement_summary.get('schools', 0)} schools, "
        f"{settlement_summary.get('workshops', 0)} workshops).\n"
        f"Recent history:\n{events_text}{whisper_text}{beliefs_text}\n"
        "Choose the village's current priority."
    )


def fallback_priority(population_summary: dict, settlement_summary: dict) -> dict:
    """Deterministic stand-in: a simple, legible read of the same stats
    an LLM would see, not a random pick — so a fallback run still steers
    sensibly rather than just narrating."""
    avg_hunger = population_summary.get("avg_hunger", 0.0)
    materials_frac = (
        settlement_summary.get("materials", 0.0) / settlement_summary.get("materials_capacity", 1.0)
        if settlement_summary.get("materials_capacity") else 0.0
    )
    currency_frac = (
        settlement_summary.get("currency", 0.0) / settlement_summary.get("currency_capacity", 1.0)
        if settlement_summary.get("currency_capacity") else 0.0
    )
    deaths_predator = population_summary.get("deaths_predator", 0)
    hospitals = settlement_summary.get("hospitals", 0)
    schools = settlement_summary.get("schools", 0)
    granary_food = settlement_summary.get("granary_food", 0.0)
    granary_capacity = settlement_summary.get("granary_capacity", 0.0) or 1.0

    if avg_hunger > 0.5 or (granary_capacity and granary_food / granary_capacity < 0.2):
        return {"priority": "food", "rationale": "Too many go hungry — the village needs food security."}
    if deaths_predator > 0 and hospitals == 0:
        return {"priority": "health", "rationale": "No hospital yet, and the village has already lost people to danger."}
    if currency_frac < 0.2:
        return {"priority": "commerce", "rationale": "The village's coffers are thin — commerce would help."}
    if schools == 0 and materials_frac > 0.3:
        return {"priority": "education", "rationale": "There's material to spare and no school yet."}
    if materials_frac < 0.15:
        return {"priority": "growth", "rationale": "Little on hand yet — the basics still need building."}
    return {"priority": "defense", "rationale": "The essentials are covered; time to look after the village's safety."}


def parse_priority(result: dict, fallback: dict) -> tuple[str, str]:
    priority = result.get("priority")
    rationale = result.get("rationale")
    if not isinstance(priority, str) or priority.strip().lower() not in _VALID_PRIORITIES:
        priority = fallback["priority"]
    else:
        priority = priority.strip().lower()
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = fallback["rationale"]
    return priority, rationale.strip()[:200]
