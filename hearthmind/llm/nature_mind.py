"""Nature's Mind (Body/Mind framing, CLAUDE.md "Design priorities" /
docs/VISION-2026-07-21-SELFEVOLVING.md "v1.2 revision note", explicit
user direction 2026-07-21): Nature's Body (weather, wildlife, disasters,
terrain evolution — all deterministic) has always been authoritative,
but Nature previously had no subjective interpretation layer at all —
every other pillar (Village via town_brain/beliefs, Innovation via
propose/evolve/merge) had a real Mind, Nature didn't.

This module gives Nature two things a Mind is supposed to have,
grounded ONLY in Nature's own Body state (never settlement prosperity,
which is what the pre-existing generic `llm/ontology.py` propose job
used to gate its "ecological" category on — an accidental collapse of
Nature's ontology-origination into a Village-flavored mechanism, fixed
alongside this module — see `engine.py`'s `_maybe_schedule_ontology_
proposal` and `ONTOLOGY_CATEGORIES` in this file's sibling):

1. **Belief formation** — a running, revisable subjective theory about
   the land itself (`World.nature_beliefs`, same shape/discipline as
   `Settlement.beliefs`: subject/belief/confidence, revisable, allowed
   to be wrong). Reuses `llm.beliefs.parse_belief`/`is_noop_belief_
   revision` rather than re-inventing belief mechanics — same
   "extend existing systems" discipline as every other cross-pillar
   crossover in this codebase.
2. **Concept invention** — Nature may (not must) originate one new
   `category="ecological"` entry in the SHARED ontology registry
   (`world.ontology.register_concept`) in the same call: a migration
   route, a symbiosis, a habitat, a climate phenomenon, a landscape
   identity. Every non-`ecological` category stays the Village-
   imagination job's territory (see `ONTOLOGY_CATEGORIES` there) —
   this is the "each pillar expands the shared ontology from its own
   Body state" correction, not a second Innovation Layer.

Both outputs land in ONE LLM call (the "maximize emergence per LLM
call" rule, docs/VISION-2026-07-21.md) — belief formation always
happens; the concept is optional and only registered if the model
actually proposed one and it clears the same deterministic dedup/
validation gates every other ontology-origination path uses."""
from __future__ import annotations

from hearthmind.llm.beliefs import is_noop_belief_revision, parse_belief

NATURE_EVENT_CATEGORIES = frozenset({
    "wildlife_hunt", "wildlife_extinct", "wildlife_recolonized", "wildlife_migrated",
    "disaster_flood", "disaster_wildfire", "disaster_storm", "disaster_heatwave", "disaster_frost",
    "terrain_reclaimed", "terrain_thinned", "mining_scarred", "disaster_scarred",
})
"""Nature's own slice of the event stream — the same filter-a-diverse-
window-by-category-set shape `folklore.py` uses for its rumor slice,
applied here so Nature's Mind is grounded in what actually happened to
the land, not the village's social events."""

SYSTEM_PROMPT = (
    "You are the wordless, watching intelligence of the land itself — not a "
    "person, not the village, but the accumulated sense the wilderness has "
    "of its own state. Given what has actually happened to the land, the "
    "animals, and the weather lately, form or revise ONE belief about the "
    "land — a real, sometimes-wrong theory of its own condition. You may "
    "ALSO originate one new thing the land itself gives rise to — a "
    "migration route, a symbiosis between two creatures, a new habitat, a "
    "climate phenomenon, or a landscape identity a place has taken on — "
    "but ONLY if what you've been told genuinely suggests one; otherwise "
    "leave it out. Ground everything in the given signals, not generic "
    "fantasy nature-flavor. "
    'Respond with strict JSON only, no other text: {"subject": "a short '
    'name for what the belief is about, under 8 words", "belief": "one '
    'sentence, under 25 words", "confidence": a number between 0 and 1, '
    '"revises": an integer index into the existing beliefs list or null, '
    '"concept_name": "a short name, under 8 words, or empty string if none", '
    '"concept_description": "one sentence, under 25 words, or empty string"}.'
)


def build_prompt(
    nature_events: list[dict], existing_beliefs: list[dict], wildlife_summary: dict,
    disaster_scar_count: int, fallow_count: int, climate_summary: dict, season: str,
) -> str:
    lines = [f"- {event['description']}" for event in nature_events]
    events_text = "\n".join(lines) if lines else "Nothing notable has happened to the land lately."
    if existing_beliefs:
        belief_lines = [
            f"  [{i}] (confidence {b['confidence']:.2f}) {b['subject']}: {b['belief']}"
            for i, b in enumerate(existing_beliefs)
        ]
        beliefs_text = "\n".join(belief_lines)
    else:
        beliefs_text = "  (none yet — this would be the land's first theory about itself)"
    signals = (
        f"Season: {season}. "
        f"Wildlife: {wildlife_summary.get('grazer_total', 0)} grazers "
        f"({wildlife_summary.get('grazer_herds', 0)} herds), "
        f"{wildlife_summary.get('predator_total', 0)} predators "
        f"({wildlife_summary.get('predator_packs', 0)} packs)"
        + (", prey is scarce" if wildlife_summary.get("prey_scarce") else "")
        + (
            ", heavy predation pressure" if wildlife_summary.get("predator_pressure_ratio", 0.0) > 0.25 else ""
        )
        + f". {disaster_scar_count} places still bear a scar from disaster. "
        f"{fallow_count} places are slowly turning back to forest. "
        f"Climate trend: {'warming' if climate_summary.get('warming', 0.0) > 0.05 else 'cooling' if climate_summary.get('warming', 0.0) < -0.05 else 'stable'}, "
        f"{'drying' if climate_summary.get('drying', 0.0) > 0.05 else 'wettening' if climate_summary.get('drying', 0.0) < -0.05 else 'stable'}."
    )
    return (
        f"What has happened to the land lately:\n{events_text}\n"
        f"Current conditions: {signals}\n"
        f"Theories the land already holds about itself:\n{beliefs_text}\n"
        "Form or revise one theory. Originate a new thing only if it's genuinely suggested."
    )


def fallback_belief(nature_events: list[dict], wildlife_summary: dict, fallow_count: int) -> dict:
    """Deterministic stand-in — same "real, legible answer, not a
    random pick" discipline as `beliefs.fallback_belief`. Picks the
    single loudest Body-state signal rather than counting event
    categories (Nature's own aggregate ratios are more informative than
    its sparse event stream)."""
    if wildlife_summary.get("prey_scarce"):
        return {
            "subject": "the hunting grounds", "belief": "Prey has grown scarce; the hunters go hungrier.",
            "confidence": 0.5, "revises": None,
        }
    if wildlife_summary.get("predator_pressure_ratio", 0.0) > 0.25:
        return {
            "subject": "the herds", "belief": "The herds move cautiously now, wary of what stalks them.",
            "confidence": 0.5, "revises": None,
        }
    if fallow_count > 0:
        return {
            "subject": "the abandoned fields", "belief": "Untended ground is slowly returning to forest.",
            "confidence": 0.4, "revises": None,
        }
    if nature_events:
        top_category = max(
            {e["category"] for e in nature_events}, key=lambda c: sum(1 for e in nature_events if e["category"] == c),
        )
        subject = top_category.replace("_", " ")
        return {"subject": subject, "belief": f"The land has seen a run of {subject}.", "confidence": 0.4, "revises": None}
    return {
        "subject": "the quiet season", "belief": "Little has stirred; the land rests.",
        "confidence": 0.3, "revises": None,
    }


def parse_nature_belief(result: dict, fallback: dict, existing_count: int) -> dict:
    return parse_belief(result, fallback, existing_count)


def is_noop_nature_revision(new_belief: str, new_confidence: float, existing_entry: dict) -> bool:
    return is_noop_belief_revision(new_belief, new_confidence, existing_entry)


def parse_concept(result: dict) -> dict | None:
    """`None` when the model left the concept fields empty (the common,
    correct case most calls — Nature doesn't invent something new every
    time it forms a belief). Deliberately no `hook_type`/`hook_target`/
    `magnitude` fields on this path: unlike the Village-imagination job,
    Nature's concepts are ecological texture (a migration route, a
    landscape identity) — real mechanical hooks stay possible via a
    later `ontology_evolution` pass over this same concept, not
    fabricated here just because the schema allows it."""
    name = result.get("concept_name")
    description = result.get("concept_description")
    if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
        return None
    return {"name": name.strip()[:60], "description": description.strip()[:200]}
