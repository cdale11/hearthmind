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
institution-flavor idea IS naturally village-grounded."""

_VALID_SKILL_TARGETS = (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE)
_VALID_GOAL_TARGETS = ("forage", "gather", "socialize", "wander", "rest")
"""Free-text-but-validated goal names a `goal_flavor_bias` hook may
target — deliberately the small set of GOAL VERBS cognition/dialogue
prompts already reference in prose (not the full `AgentGoal` enum,
several of which — e.g. EXPLORE, the surveyor-only goal — wouldn't
make sense as a village-wide cultural bias)."""

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
    as before this parameter existed."""
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
    return (
        f"The village of {settlement_name} (era: {era}, tech tier {tech_level}). "
        f"Recent history:\n{events_text}\n"
        f"{observations_block}"
        f"{pressure_block}"
        f"{discoverable_block}"
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


def validate_hook(hook_type: str, hook_target: str, magnitude: float, category: str) -> dict | None:
    """Deterministic — never trusts the LLM's own claim that a target
    is valid. Returns `None` for `custom_text_only` (pure flavor, a
    legitimate real outcome, see `world.ontology.MECHANICAL_HOOK_
    TYPES`'s docstring) or an unrecognized/invalid combination — a
    concept that fails validation still persists (see `parse_propose`),
    it just carries no mechanical effect rather than a fabricated one."""
    if hook_type not in MECHANICAL_HOOK_TYPES or hook_type == "custom_text_only":
        return None
    magnitude = max(0.0, min(1.0, magnitude)) if isinstance(magnitude, (int, float)) else 0.5
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
        return {"type": hook_type, "target": hook_target, "magnitude": magnitude}
    return None


def parse_propose(result: dict, fallback: dict) -> dict:
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
        "hook": validate_hook(hook_type, hook_target, float(magnitude), category),
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
    'words, describing how it has evolved"}.'
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
    return {"name": f"{parent_name}, Refined", "description": "Long practice has quietly improved on the original idea."}


def parse_evolve(result: dict, fallback: dict) -> tuple[str, str]:
    name = result.get("name")
    description = result.get("description")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    return name.strip()[:80], description.strip()[:200]


# --- merge --------------------------------------------------------------

SYSTEM_PROMPT_MERGE = (
    "You are the collective imagination of a small simulated village. "
    "Given two ideas the village already has, propose ONE new idea that "
    "genuinely COMBINES them — a real synthesis, not just both ideas "
    "restated together. "
    'Respond with strict JSON only, no other text: {"name": "a short '
    'name, under 8 words", "description": "one sentence, under 25 '
    'words, describing the combined idea"}.'
)


def build_merge_prompt(a_name: str, a_description: str, b_name: str, b_description: str, settlement_name: str) -> str:
    return (
        f"{settlement_name} has two separate ideas:\n"
        f"1. {a_name} — {a_description}\n"
        f"2. {b_name} — {b_description}\n"
        "Propose one new idea that genuinely combines them."
    )


def fallback_merge(a_name: str, b_name: str) -> dict:
    return {"name": f"{a_name} and {b_name}, Combined", "description": "Two old ideas, practiced together, have become one."}


def parse_merge(result: dict, fallback: dict) -> tuple[str, str]:
    return parse_evolve(result, fallback)
