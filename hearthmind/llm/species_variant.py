"""Vision doc item 4.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("Emergent species/variants via parameter-space"): Nature naming a
real existing wildlife herd — an existing species (grazer/predator)
given an LLM-authored identity and a trait from a small closed
vocabulary, grounded in the land's own real recent condition. Same
composition discipline as `llm/composite_entity.py` applied to Nature:
never a new creature type, just a named variant of one that already
exists."""
from __future__ import annotations

from hearthmind.world.wildlife import SPECIES_VARIANT_TRAITS

SYSTEM_PROMPT = (
    "You are the land's own sense of itself — Nature's Mind, noticing something distinct about "
    "one real pack or herd of animals living here. Given the species and the land's real recent "
    "condition, give this specific group a short, memorable name and describe what makes them "
    "distinct — pick ONE trait from a closed list that best fits. The trait must be one of: "
    + ", ".join(SPECIES_VARIANT_TRAITS) + ". "
    'Respond with strict JSON only, no other text: {"name": "a short name, under 5 words", '
    '"trait": "one of the exact listed trait words", "description": "one sentence, under 30 '
    'words, grounded in the land\'s real condition"}.'
)

_FALLBACK_VARIANTS: tuple[tuple[str, str, str], ...] = (
    ("the Long-Ranging pack", "migratory", "They range farther than most, following the seasons more closely."),
    ("the Steady herd", "hardier", "They have weathered more hard winters than most and show it."),
    ("the Watchful pack", "timid", "They keep their distance, wary in a way the others aren't."),
    ("the Bold herd", "aggressive", "They hold ground the others would flee from."),
    ("the Thriving herd", "prolific", "Their numbers grow faster than the land around them usually allows."),
)


def build_prompt(species: str, condition_text: str, existing_names: list[str]) -> str:
    names_text = "; ".join(existing_names) if existing_names else "None yet."
    return (
        f"A {species} group living in this land.\n"
        f"The land's real recent condition: {condition_text}\n"
        f"Already-named groups: {names_text}\n"
        "Give this group a distinct name and trait, different from the ones already named."
    )


def fallback_variant(existing_count: int) -> dict:
    name, trait, description = _FALLBACK_VARIANTS[existing_count % len(_FALLBACK_VARIANTS)]
    return {"name": name, "trait": trait, "description": description}


def parse_variant(result: dict, fallback: dict) -> dict:
    name = result.get("name")
    trait = result.get("trait")
    description = result.get("description")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(trait, str) or trait not in SPECIES_VARIANT_TRAITS:
        trait = fallback["trait"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    return {
        "name": name.strip()[:50],
        "trait": trait,
        "description": description.strip()[:200],
    }
