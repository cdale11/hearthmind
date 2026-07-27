"""A18 second slice (docs/ROADMAP-2026-07-REMAINING.md, "Composable
event reactions" — a general authoring system, the piece the item's
own doc entry flagged as missing). Given the village's recent history
and the closed condition/hook vocabularies (`world.reactions.
CONDITION_KEYS`/`world.ontology.MECHANICAL_HOOK_TYPES`), propose ONE
new `CompositeReaction`: a combination of 2 or 3 conditions that,
happening TOGETHER, produce a consequence no single condition would
have caused alone — "when the land is dry, food runs short, AND an
old feud is already open, the elders quietly ration what's left"
combines `drought`+`food_shortage`+`feud` into a `custom_text_only`
(or real mechanical) effect. Same closed-vocabulary-hosting-open-
content shape `llm/rule_propose.py` already established; reuses
`MECHANICAL_HOOK_TYPES` verbatim rather than inventing a second effect
vocabulary — a composite reaction's hook is exactly as real/bounded as
a trigger rule's."""
from __future__ import annotations

from hearthmind.world.ontology import MECHANICAL_HOOK_TYPES
from hearthmind.world.reactions import CONDITION_KEYS

SYSTEM_PROMPT = (
    "You are the collective imagination of a small simulated village, proposing a genuine "
    "COMPOSITE reaction — something that only happens when SEVERAL real conditions are true "
    "at the SAME time, not a response to any one of them alone. The conditions available are: "
    + ", ".join(CONDITION_KEYS) + ". Choose 2 or 3 of them (never just 1 — that would be an "
    "ordinary single-trigger rule, not a composite). The effect must be one of: "
    + ", ".join(MECHANICAL_HOOK_TYPES) + " (use 'custom_text_only' if it's meaningful but "
    "shouldn't move any number). If the hook is 'skill_yield_bonus' the target must be one of: "
    "farming, construction, medicine. If it's 'goal_flavor_bias' the target must be one of: "
    "forage, gather, socialize, wander, rest. Otherwise leave target empty. Ground it in what "
    "has actually happened to these people. "
    'Respond with strict JSON only, no other text: {"name": "a short name, under 8 words", '
    '"description": "one sentence, under 25 words, describing what happens when these '
    'conditions combine", "conditions": ["two or three of the exact listed condition words"], '
    '"hook_type": "one of the exact listed effect words", "hook_target": "a valid target or '
    'empty string", "magnitude": a number between 0 and 1}.'
)

_FALLBACK_REACTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Lean Times Together",
        "When the land turns dry and food runs short, the village quietly pools what's left.",
        ("drought", "food_shortage"),
    ),
    (
        "Old Wounds Reopened",
        "When the harvest fails while an old feud still smolders, tempers flare faster than usual.",
        ("food_shortage", "feud"),
    ),
    (
        "Scorched Grudges",
        "When the heat won't break and a feud is already open, both sides blame the other for their luck.",
        ("drought", "feud"),
    ),
)


def build_prompt(settlement_name: str, recent_events: list[dict], existing_condition_sets: list[str]) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    existing_text = "; ".join(existing_condition_sets) if existing_condition_sets else "None yet."
    return (
        f"The village of {settlement_name}. Recent history:\n{events_text}\n"
        f"Composite reactions the village already has (by their condition combinations): "
        f"{existing_text}\n"
        "Originate one new composite reaction — a combination of 2 or 3 conditions that, "
        "happening together, produce something neither would alone."
    )


def fallback_propose(existing_count: int) -> dict:
    name, description, conditions = _FALLBACK_REACTIONS[existing_count % len(_FALLBACK_REACTIONS)]
    return {
        "name": name, "description": description, "conditions": list(conditions),
        "hook_type": "custom_text_only", "hook_target": "", "magnitude": 0.5,
    }


def parse_propose(result: dict, fallback: dict) -> dict:
    name = result.get("name")
    description = result.get("description")
    conditions = result.get("conditions")
    hook_type = result.get("hook_type")
    hook_target = result.get("hook_target")
    magnitude = result.get("magnitude")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    if (
        not isinstance(conditions, list)
        or len(set(conditions)) < 2
        or not all(isinstance(c, str) and c in CONDITION_KEYS for c in conditions)
    ):
        conditions = fallback["conditions"]
    if not isinstance(hook_type, str) or hook_type not in MECHANICAL_HOOK_TYPES:
        hook_type = fallback["hook_type"]
    hook_target = hook_target.strip() if isinstance(hook_target, str) else fallback["hook_target"]
    if not isinstance(magnitude, (int, float)):
        magnitude = fallback["magnitude"]
    return {
        "name": name.strip()[:80],
        "description": description.strip()[:200],
        "conditions": sorted(set(conditions)),
        "hook_type": hook_type,
        "hook_target": hook_target,
        "magnitude": float(magnitude),
    }
