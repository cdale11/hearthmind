"""Vision doc item 4.1, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("Composite entities from existing primitives"). A new "entity" isn't
new code — it's a named, persistent COMPOSITE of things that already
exist: one real standing building, given a name and an origin story
tied to something that actually happened, plus a new `InventedConcept`
(closed category/hook vocabulary, same bounded-open-content shape
`llm/ontology.py`/`llm/rule_propose.py` already use) that concept
embodies. "The Sorrow-Hall" is mechanically still just a building of
its existing kind — the entity is the sum, never a new mechanism."""
from __future__ import annotations

from hearthmind.llm.ontology import validate_hook
from hearthmind.world.ontology import MECHANICAL_HOOK_TYPES, ONTOLOGY_CATEGORIES

SYSTEM_PROMPT = (
    "You are the collective imagination of a small simulated village. You are given one real "
    "standing building and something significant that actually happened here. Give this SPECIFIC "
    "building a memorable name and a short origin story tying it to that event — the way a real "
    "village names 'the old mill' after the miller who died there, or 'the Sorrow-Hall' after a "
    "plague. Also invent the idea this name embodies: a category and, if it's meaningful, a bounded "
    "mechanical effect. The category must be one of: " + ", ".join(ONTOLOGY_CATEGORIES) + ". The "
    "effect must be one of: " + ", ".join(MECHANICAL_HOOK_TYPES) + " (use 'custom_text_only' if it's "
    "meaningful but shouldn't move any number). If the hook is 'skill_yield_bonus' the target must be "
    "one of: farming, construction, medicine. If it's 'goal_flavor_bias' the target must be one of: "
    "forage, gather, socialize, wander, rest. Otherwise leave target empty. "
    'Respond with strict JSON only, no other text: {"name": "a short, memorable place-name, under 6 '
    'words", "origin_story": "one or two sentences, under 40 words, grounded in the given event", '
    '"category": "one of the exact listed categories", "hook_type": "one of the exact listed effect '
    'words", "hook_target": "a valid target or empty string", "magnitude": a number between 0 and 1}.'
)

_FALLBACK_NAMES: tuple[tuple[str, str], ...] = (
    ("the Quiet House", "It stood through a hard season, and people started calling it that."),
    ("the Long Watch", "Someone kept vigil here once, and the name stayed."),
    ("the Bright Hearth", "It was warm on a cold night when warmth mattered most."),
    ("the Old Ground", "Something was buried in its memory here, even if no one says what."),
)


def build_prompt(
    settlement_name: str, building_kind: str, event_description: str, existing_names: list[str],
    location_history: str = "",
) -> str:
    """`location_history` (closing A19, `world.spatial_memory.
    location_character_text`): what this SPECIFIC tile itself
    remembers (old mining activity, a past disaster, a wildlife
    migration crossing...), distinct from `event_description`'s
    single most recent settlement-wide event — grounds the origin
    story in the site's own accumulated character when it has one,
    same "places as actors" the module exists for. Empty for a tile
    with no notable history, the common case, in which case the
    prompt reads exactly as it did before this parameter existed."""
    kind_spaced = building_kind.replace("_", " ")
    names_text = "; ".join(existing_names) if existing_names else "None yet."
    history_text = f"\nThis particular spot has also seen {location_history}.\n" if location_history else ""
    return (
        f"The village of {settlement_name}. A standing {kind_spaced} stands here, unnamed.\n"
        f"Something that actually happened: {event_description}\n"
        f"{history_text}"
        f"Places already named: {names_text}\n"
        "Give this building a name and origin story, distinct from the ones already named."
    )


def fallback_entity(existing_count: int) -> dict:
    name, story = _FALLBACK_NAMES[existing_count % len(_FALLBACK_NAMES)]
    return {
        "name": name, "origin_story": story, "category": "institution_flavor",
        "hook_type": "custom_text_only", "hook_target": "", "magnitude": 0.3,
    }


def parse_entity(result: dict, fallback: dict) -> dict:
    name = result.get("name")
    origin_story = result.get("origin_story")
    category = result.get("category")
    hook_type = result.get("hook_type")
    hook_target = result.get("hook_target")
    magnitude = result.get("magnitude")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(origin_story, str) or not origin_story.strip():
        origin_story = fallback["origin_story"]
    if not isinstance(category, str) or category not in ONTOLOGY_CATEGORIES:
        category = fallback["category"]
    if not isinstance(hook_type, str) or hook_type not in MECHANICAL_HOOK_TYPES:
        hook_type = fallback["hook_type"]
    hook_target = hook_target.strip() if isinstance(hook_target, str) else fallback["hook_target"]
    if not isinstance(magnitude, (int, float)):
        magnitude = fallback["magnitude"]
    return {
        "name": name.strip()[:60],
        "origin_story": origin_story.strip()[:220],
        "category": category,
        "hook": validate_hook(hook_type, hook_target, float(magnitude), category),
    }
