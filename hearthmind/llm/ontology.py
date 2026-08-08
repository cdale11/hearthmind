"""The Innovation Layer's LLM pipeline (Phase 1.A, docs/VISION-2026-07-
21-SELFEVOLVING.md) — propose a new concept, or evolve/merge existing
established ones, then validate deterministically before anything is
persisted (`world/ontology.py`).

Why bounded, not a fully open schema: `BuildingKind`/`AgentGoal`/
`InstitutionKind`/`SkillId` etc. are Python enums, several mirrored
into the C++ native store's integer code tables — a literal "the LLM
adds a new enum member at runtime" is close to structurally impossible
without a native-store schema migration mid-run. Instead: the
CATEGORY and MECHANICAL HOOK TYPE the model picks from are closed
lists (`world.ontology.ONTOLOGY_CATEGORIES`/`MECHANICAL_HOOK_TYPES`);
the NAME, DESCRIPTION, and (for `evolve`/`merge`) how a new concept
relates to its parent(s) are genuinely open-ended free text. This is
the same "bounded expansion slots hosting open-ended content" pattern
`llm/era_branch.py`/`llm/invention.py` already established, generalized
into the load-bearing mechanism instead of one narrow job.

`validate_hook` is deliberately NOT an LLM self-check — every proposed
mechanical effect is re-verified against real game state (real skill
names, a real magnitude cap) before it can move a single number,
exactly like every other closed-choice-on-open-creativity job in this
codebase."""

from __future__ import annotations

from hearthmind.agents.agent import SKILL_CONSTRUCTION, SKILL_FARMING, SKILL_MEDICINE
from hearthmind.util import clamp
from hearthmind.world.ontology import MAX_HOOK_MAGNITUDE, MECHANICAL_HOOK_TYPES, ONTOLOGY_CATEGORIES

VILLAGE_PROPOSE_CATEGORIES = tuple(c for c in ONTOLOGY_CATEGORIES if c != "ecological")
"""Body/Mind correction (CLAUDE.md "Design priorities", explicit user
direction 2026-07-21): `category="ecological"` used to be offered here
alongside everything else, gated on settlement prosperity — an
accidental collapse of Nature's own ontology-origination into a
Village-flavored mechanism. `ecological` concepts are now exclusively
`llm/nature_mind.py`'s territory, grounded in Nature's own Body state
(wildlife/disaster/succession/climate signals), not village prosperity.
Every other category stays here — this job is genuinely "the village's
collective imagination," and a custom/law/ritual/saying/profession/
institution-flavor idea IS naturally village-grounded.

Still true at the PROMPT/scheduling level: one job, one settlement-
grounded prompt, proposing across all seven of these categories. What
changed (explicit user delegation, 2026-07-31 — "you decide this one"
on the Humans-vs-Village origination split flagged in CLAUDE.md) is
ATTRIBUTION, not scheduling: `HUMANS_PROPOSE_CATEGORIES` below names
which of these seven the result should be credited to Humans rather
than Village once it's actually registered — see `origin_pillar_for_
category`. A second, fully independent Humans-grounded scheduling job
(its own prompt/budget/backpressure gate) was deliberately NOT built —
that's a materially larger lift than the actual gap CLAUDE.md named
(today NOTHING distinguishes a Humans-flavor concept from a Village-
flavor one at the data level), so this stays a bounded, real
attribution fix rather than a second Innovation-sized subsystem."""

HUMANS_PROPOSE_CATEGORIES = frozenset({"custom", "saying", "profession"})
"""CLAUDE.md's own standing correction: "Humans originate customs/
professions/social roles/myths/traditions... Village originates
institutions/laws/festivals/political structures." Mapped onto
`ONTOLOGY_CATEGORIES`' actual seven non-ecological entries: `custom`
(a lived social practice), `saying` (folk wisdom/myth-adjacent), and
`profession` (a social role) are genuinely person-and-culture-scale,
Humans' natural territory. `law`/`ritual`/`institution_flavor` stay
Village-attributed (collective/institutional in character) — see
`origin_pillar_for_category`."""


def origin_pillar_for_category(category: str) -> str:
    """`world.ontology.InventedConcept.origin_pillar`'s real source of
    truth for `_maybe_schedule_ontology_proposal`'s registered
    concepts — `"humans"` for `HUMANS_PROPOSE_CATEGORIES`, `"village"`
    for everything else this job can produce (technology/ecological
    never reach this function; their own call sites pass `origin_
    pillar` explicitly)."""
    return "humans" if category in HUMANS_PROPOSE_CATEGORIES else "village"

_VALID_SKILL_TARGETS = (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE)
_VALID_GOAL_TARGETS = ("forage", "gather", "socialize", "wander", "rest")
"""Free-text-but-validated goal names a `goal_flavor_bias` hook may
target — deliberately the small set of GOAL VERBS cognition/dialogue
prompts already reference in prose (not the full `AgentGoal` enum,
several of which — e.g. EXPLORE, the surveyor-only goal — wouldn't
make sense as a village-wide cultural bias)."""

SPECIALIZATION_AFFORDANCE_HINTS: dict[str, frozenset[str]] = {
    "agricultural": frozenset({"can_store_food", "can_carry_water", "can_redirect_water", "can_fertilize"}),
    "structural": frozenset({"can_support_weight", "can_shelter", "can_sharpen", "can_conduct_heat", "can_burn"}),
}
"""A6's validate-step half (roadmap Tier 3 item 17, docs/ROADMAP-2026-
07-REMAINING.md — the generate-step grounding shipped v1.16.0/v1.18.0;
this closes the "deterministic re-verification" half the doc's own
entry flagged as not attempted). Only `agricultural`/`structural` get a
real physical-affordance check: `mercantile`/`general` have no
meaningful mapping onto `world.affordances.AFFORDANCE_TAGS` (trade/
currency isn't a physical affordance, and MARKET/BANK-shaped buildings
correctly carry no affordance tag at all per that module's own
docstring — treating their absence as a validation failure would be a
category error, not a real check) and so always pass unchecked, same
as before this pass. Deliberately a *hint* set, not an exhaustive
mapping: a settlement claiming an agricultural/structural specialization
needs SOME real physical grounding among its standing buildings, not a
specific exact combination — see `validate_hook`'s `present_tags`
param."""

# --- propose --------------------------------------------------------------

SYSTEM_PROMPT_PROPOSE = (
    "You are the collective imagination of a small simulated village. "
    "Given its name, recent history, current technological/cultural "
    "level, and ideas it already has, invent ONE new concept this "
    "village might genuinely originate — a technology, a custom, a law, "
    "a ritual, a saying, a profession, or a flavor of an existing "
    "institution. Ground it in what has "
    "actually happened to these people, not generic fantasy flavor. "
    "If you were told the village is straining under something, treat "
    "your idea as a genuine hypothesis for helping with it — a real "
    "guess that might be wrong, not a guaranteed fix. If nothing "
    "specific was named, your idea can simply be culture for its own "
    "sake. Classify it as one of: " + ", ".join(VILLAGE_PROPOSE_CATEGORIES) + ". "
    "If the idea has a real mechanical effect, name it as one of: "
    + ", ".join(MECHANICAL_HOOK_TYPES) + " (use 'custom_text_only' if it's "
    "meaningful but shouldn't move any number). If the hook is "
    "'skill_yield_bonus' the target must be one of: farming, "
    "construction, medicine. If it's 'goal_flavor_bias' the target must "
    "be one of: forage, gather, socialize, wander, rest. If it's "
    "'invention_specialization_category' the target must be one of: "
    "agricultural, structural, mercantile, general. Otherwise leave "
    "target empty. "
    'Respond with strict JSON only, no other text: {"name": "a short '
    'name, under 8 words", "description": "one sentence, under 25 '
    'words", "hypothesis": "one short sentence naming the real problem '
    'or need this addresses, or the exact words \'no specific problem\' '
    'if it is just culture for its own sake", "category": "one of the '
    'exact listed words", "hook_type": "one of the exact listed words '
    'or custom_text_only", "hook_target": "a valid target or empty '
    'string", "magnitude": a number between 0 and 1}.'
)

_FALLBACK_PROPOSALS: tuple[tuple[str, str, str, str, str], ...] = (
    ("The Boundary Stones", "Marked stones now settle where one family's land ends and another's begins.", "custom", "custom_text_only", ""),
    ("The Gathering Bell", "A rung bell calls the village together for shared news.", "custom", "custom_text_only", ""),
    ("Elders Speak First", "In any dispute, the eldest present is heard before anyone else.", "law", "custom_text_only", ""),
    ("The Harvest Toast", "A short shared toast now opens every harvest.", "ritual", "custom_text_only", ""),
    ("Waste Not the Bone", "A saying reminding the village that nothing gathered goes unused.", "saying", "goal_flavor_bias", "gather"),
    ("The Path-Keeper", "A recognized role for whoever keeps the village paths clear and safe.", "profession", "custom_text_only", ""),
    ("Rest Before Ruin", "A saying urging the tired to rest before they collapse.", "saying", "goal_flavor_bias", "rest"),
)

PRESSURE_SIGNAL_LABELS: dict[str, str] = {
    "materials_bottleneck": "a shortage of building materials",
    "dispute_feud": "a run of bitter disputes and feuding",
    "starvation_death": "hunger and starvation",
    "disease_outbreak": "sickness spreading through the village",
    "wildlife_recolonization": "wildlife pressing back into the land",
    "nature_adaptation": "the land itself changing under them",
    "housing_shortage": "too many people packed into too few homes",
    "food_shortage": "the granaries running dangerously low",
    "currency_shortage": "the coffers running dangerously bare",
    "council_gridlock": "the council splitting into rival camps, unable to agree",
    "guild_decline": "a guild's craft dying out for want of a master",
    "family_extinction": "family lines dying out, one after another",
    "diplomatic_hostility": "hostility with a neighboring settlement, again and again",
    "faction_rivalry": "two factions turning on each other, again and again",
}
"""B5 "Innovation as conscious scientist" (roadmap Stage III step 12):
plain-language phrasing for `Settlement.pattern_signal_counts`' keys
(see `simulation/engine.py`'s own writers of that dict) — the same
closed-vocabulary-hosting-open-content discipline as everything else
here, just for READING a signal name back out as prose instead of
choosing one. An unmapped key (a future signal added without updating
this table) falls back to its raw name with underscores replaced by
spaces, never a crash."""


def _pressure_label(pressure_signal: str) -> str:
    return PRESSURE_SIGNAL_LABELS.get(pressure_signal, pressure_signal.replace("_", " "))


def build_propose_prompt(
    settlement_name: str, recent_events: list[dict], existing_concept_names: list[str],
    era: str, tech_level: int, emergence_observations: list[str] | None = None,
    pressure_signal: str | None = None, discoverable_combinations: list[str] | None = None,
    discoverable_reactions: list[str] | None = None,
) -> str:
    """`emergence_observations` (B1-B3, docs/MASTERCHECKLIST-2026-07-
    22.md, roadmap Stage II — same shape as `nature_mind.build_prompt`'s
    param of the same name): curated Emergence API summaries gathered
    during the Innovation pillar's prior `observe` turn. Optional and
    additive; unset reads exactly as before this parameter existed.

    `pressure_signal` (B5, roadmap Stage III step 12): the name of the
    real `Settlement.pattern_signal_counts` key that's currently
    crossing its promotion threshold, if any — the concrete "genuine
    problem to hypothesize about" this job was previously missing even
    when its own prosperity/pressure gate had already fired on one.
    `None`/absent (village is prosperous, not specifically pressured,
    or has no dominant signal) reads exactly as before this parameter
    existed — free invention, no named problem to answer.

    `discoverable_combinations` (A5/A6, roadmap Stage IV step 18): names
    from `world.affordances.discover_combinations`, genuinely achievable
    from what's actually standing in the settlement right now (e.g.
    `["kiln_process", "tempered_tools"]`). Grounds the generate-step in
    real physical affordances instead of pure free invention — Innovation
    querying "what could we combine into something new?" over the world's
    own capability layer. Optional/additive; empty/`None` reads exactly
    as before this parameter existed.

    `discoverable_reactions` (A13, roadmap Stage IV step 20): product
    names from `world.chemistry.discover_reactions` — a real material
    genuinely present, transformed under a real condition genuinely
    available (e.g. `["ceramic"]` once clay and heat are both present).
    Same additive/optional shape as `discoverable_combinations`."""
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    concepts_text = "; ".join(existing_concept_names) if existing_concept_names else "None yet."
    observations_text = (
        "\n".join(f"- {o}" for o in emergence_observations) if emergence_observations else ""
    )
    observations_block = (
        f"What you noticed since last time:\n{observations_text}\n" if observations_text else ""
    )
    pressure_block = (
        f"The village has been quietly straining under: {_pressure_label(pressure_signal)}.\n"
        if pressure_signal else ""
    )
    discoverable_text = (
        ", ".join(c.replace("_", " ") for c in discoverable_combinations)
        if discoverable_combinations else ""
    )
    discoverable_block = (
        f"What could physically be combined here right now: {discoverable_text}. "
        "You don't have to use one of these, but a real technology idea "
        "grounded in one is especially credible.\n" if discoverable_text else ""
    )
    reactions_text = (
        ", ".join(r.replace("_", " ") for r in discoverable_reactions)
        if discoverable_reactions else ""
    )
    reactions_block = (
        f"What could be produced here right now by working a material under the right "
        f"conditions: {reactions_text}. Again, optional but especially credible if used.\n"
        if reactions_text else ""
    )
    return (
        f"The village of {settlement_name} (era: {era}, tech tier {tech_level}). "
        f"Recent history:\n{events_text}\n"
        f"{observations_block}"
        f"{pressure_block}"
        f"{discoverable_block}"
        f"{reactions_block}"
        f"Ideas the village already has: {concepts_text}\n"
        "Originate one new concept this village might genuinely have."
    )


def fallback_propose(established_count: int, pressure_signal: str | None = None) -> dict:
    name, description, category, hook_type, hook_target = _FALLBACK_PROPOSALS[
        established_count % len(_FALLBACK_PROPOSALS)
    ]
    hypothesis = f"a response to {_pressure_label(pressure_signal)}" if pressure_signal else "no specific problem"
    return {
        "name": name, "description": description, "hypothesis": hypothesis, "category": category,
        "hook_type": hook_type, "hook_target": hook_target, "magnitude": 0.5,
    }


def validate_hook(
    hook_type: str, hook_target: str, magnitude: float, category: str,
    present_tags: "frozenset[str] | set[str] | None" = None,
) -> dict | None:
    """Deterministic — never trusts the LLM's own claim that a target
    is valid. Returns `None` for `custom_text_only` (pure flavor, a
    legitimate real outcome, see `world.ontology.MECHANICAL_HOOK_
    TYPES`'s docstring) or an unrecognized/invalid combination — a
    concept that fails validation still persists (see `parse_propose`),
    it just carries no mechanical effect rather than a fabricated one.

    `present_tags` (A6's validate-step half, Tier 3 item 17): the
    settlement's own currently-standing affordance tags (`world.
    affordances.affordances_present`/`building_instance_affordances`),
    same live query already used to GROUND `invention_specialization_
    category` proposals in `build_propose_prompt`. `None` (the default,
    and every call site that predates this param) skips the check
    entirely — unchanged behavior. When provided, an `agricultural`/
    `structural` specialization claim with zero overlap against
    `SPECIALIZATION_AFFORDANCE_HINTS` is rejected (degrades to no
    mechanical effect, same as any other invalid hook) — a village with
    nothing agricultural/structural actually standing can't claim a
    mechanical bonus in that domain. `mercantile`/`general` have no
    real affordance mapping (see that dict's own docstring) and always
    pass, same as before this param existed."""
    if hook_type not in MECHANICAL_HOOK_TYPES or hook_type == "custom_text_only":
        return None
    magnitude = clamp(magnitude, 0.0, 1.0) if isinstance(magnitude, (int, float)) else 0.5
    if hook_type == "skill_yield_bonus":
        if hook_target not in _VALID_SKILL_TARGETS:
            return None
        return {"type": hook_type, "target": hook_target, "magnitude": magnitude * MAX_HOOK_MAGNITUDE}
    if hook_type == "goal_flavor_bias":
        if hook_target not in _VALID_GOAL_TARGETS:
            return None
        return {"type": hook_type, "target": hook_target, "magnitude": magnitude * MAX_HOOK_MAGNITUDE}
    if hook_type == "belief_confidence_bonus":
        return {"type": hook_type, "target": "", "magnitude": magnitude * MAX_HOOK_MAGNITUDE}
    if hook_type == "invention_specialization_category":
        from hearthmind.settlement.buildings import INVENTION_CATEGORIES
        if hook_target not in INVENTION_CATEGORIES:
            return None
        hints = SPECIALIZATION_AFFORDANCE_HINTS.get(hook_target)
        if present_tags is not None and hints is not None and not (hints & present_tags):
            return None
        return {"type": hook_type, "target": hook_target, "magnitude": magnitude}
    return None


def parse_propose(
    result: dict, fallback: dict, present_tags: "frozenset[str] | set[str] | None" = None,
) -> dict:
    name = result.get("name")
    description = result.get("description")
    hypothesis = result.get("hypothesis")
    category = result.get("category")
    hook_type = result.get("hook_type")
    hook_target = result.get("hook_target")
    magnitude = result.get("magnitude")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        hypothesis = fallback.get("hypothesis", "no specific problem")
    if hypothesis.strip().lower() == "no specific problem":
        hypothesis = ""
    if not isinstance(category, str) or category not in VILLAGE_PROPOSE_CATEGORIES:
        category = fallback["category"]
    if not isinstance(hook_type, str) or hook_type not in MECHANICAL_HOOK_TYPES:
        hook_type = fallback["hook_type"]
    hook_target = hook_target.strip() if isinstance(hook_target, str) else fallback["hook_target"]
    if not isinstance(magnitude, (int, float)):
        magnitude = fallback["magnitude"]
    return {
        "name": name.strip()[:80],
        "description": description.strip()[:200],
        "hypothesis": hypothesis.strip()[:150],
        "category": category,
        "hook": validate_hook(hook_type, hook_target, float(magnitude), category, present_tags=present_tags),
    }


# --- evolve -----------------------------------------------------------

SYSTEM_PROMPT_EVOLVE = (
    "You are the collective imagination of a small simulated village, "
    "revisiting one of its own established ideas. Given the idea and "
    "the village's recent history, propose a genuine EVOLUTION of it — "
    "a refinement, a new use, or a way it has changed as the village "
    "changed — not a restatement of the original. "
    'Respond with strict JSON only, no other text: {"name": "a short '
    'name, under 8 words", "description": "one sentence, under 25 '
    'words, describing how it has evolved", "hypothesis": "one short '
    'sentence naming why the village genuinely believes this change '
    "will help, or the exact words 'no specific reason' if it's just "
    'natural drift"}.'
)


def build_evolve_prompt(parent_name: str, parent_description: str, settlement_name: str, recent_events: list[dict]) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    return (
        f"{settlement_name} already has this idea: {parent_name} — {parent_description}\n"
        f"Recent history:\n{events_text}\n"
        "Propose how this idea has genuinely evolved."
    )


def fallback_evolve(parent_name: str) -> dict:
    return {
        "name": f"{parent_name}, Refined",
        "description": "Long practice has quietly improved on the original idea.",
        "hypothesis": "no specific reason",
    }


def parse_evolve(result: dict, fallback: dict) -> tuple[str, str, str]:
    """Returns `(name, description, hypothesis)` — B5 "Innovation as
    conscious scientist" (roadmap Stage III step 12, Tier 2 item 15's
    follow-up): the same hypothesize -> observe -> revise loop `propose`
    already closes, extended to evolve/merge. `hypothesis` empty string
    (from the 'no specific reason' sentinel, same convention as
    `parse_propose`) is a legitimate common answer — most evolutions/
    merges are natural drift, not a claimed fix for anything — and
    correctly no-ops `world.ontology._record_hypothesis_outcome`'s later
    confirm/refute revision via its existing empty-hypothesis guard."""
    name = result.get("name")
    description = result.get("description")
    hypothesis = result.get("hypothesis")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        hypothesis = fallback.get("hypothesis", "no specific reason")
    if hypothesis.strip().lower() == "no specific reason":
        hypothesis = ""
    return name.strip()[:80], description.strip()[:200], hypothesis.strip()[:150]


# --- merge --------------------------------------------------------------

SYSTEM_PROMPT_MERGE = (
    "You are the collective imagination of a small simulated village. "
    "Given two ideas the village already has, propose ONE new idea that "
    "genuinely COMBINES them — a real synthesis, not just both ideas "
    "restated together. "
    'Respond with strict JSON only, no other text: {"name": "a short '
    'name, under 8 words", "description": "one sentence, under 25 '
    'words, describing the combined idea", "hypothesis": "one short '
    'sentence naming why the village genuinely believes this combination '
    "will help, or the exact words 'no specific reason' if it's just "
    'a natural pairing"}.'
)


def build_merge_prompt(
    a_name: str, a_description: str, b_name: str, b_description: str, settlement_name: str,
    candidate_hint: str = "",
) -> str:
    """`candidate_hint` (Tier 7 HCA F1, `hearthmind/cognition/
    semantic_pointers.py`) is an optional grounding line naming the
    words nearest to the algebraically-selected combination vector
    (`generate_candidates`/`select_best_candidate`'s real output,
    formatted by a caller as a short comma-joined string) — steers the
    LLM's synthesis toward the winning candidate's own real semantic
    neighborhood instead of a blind combination. Empty string (the
    default, and the only path any real call site uses today — no
    engine call passes a real hint yet) reproduces the exact prior
    prompt text byte-for-byte."""
    hint_line = (
        f"A blend of these two ideas leans toward: {candidate_hint}.\n" if candidate_hint else ""
    )
    return (
        f"{settlement_name} has two separate ideas:\n"
        f"1. {a_name} — {a_description}\n"
        f"2. {b_name} — {b_description}\n"
        f"{hint_line}"
        "Propose one new idea that genuinely combines them."
    )


def fallback_merge(a_name: str, b_name: str) -> dict:
    return {
        "name": f"{a_name} and {b_name}, Combined",
        "description": "Two old ideas, practiced together, have become one.",
        "hypothesis": "no specific reason",
    }


def parse_merge(result: dict, fallback: dict) -> tuple[str, str, str]:
    return parse_evolve(result, fallback)
