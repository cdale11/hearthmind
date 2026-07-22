"""Vision doc item 1.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md ("A
conditional/trigger vocabulary as data"). Given the village's recent
history and the closed trigger/hook vocabularies (`world.ontology.
TRIGGER_TYPES`/`MECHANICAL_HOOK_TYPES`), propose ONE trigger→effect
rule the village might genuinely originate for itself — "when the
granary overflows, hold a feast" is `trigger="on_surplus"`,
`hook_type="custom_text_only"` (or a real mechanical hook). Same
closed-vocabulary-hosting-open-content shape as `llm/ontology.py`'s
concept proposal; reuses `ontology.validate_hook` verbatim for the
effect half rather than duplicating validation logic — a rule's hook
is exactly as real/bounded as a concept's."""
from __future__ import annotations

from hearthmind.world.ontology import MECHANICAL_HOOK_TYPES, TRIGGER_TYPES

SYSTEM_PROMPT = (
    "You are the collective imagination of a small simulated village, "
    "proposing a genuine RULE it might live by — a custom or law that "
    "fires in response to a specific real recurring condition, not a "
    "one-off event. Given the village's recent history and the rules "
    "it already has, invent ONE new trigger-and-effect rule: WHEN a "
    "condition happens, THEN something follows. The trigger must be "
    "one of: " + ", ".join(TRIGGER_TYPES) + ". The effect must be one "
    "of: " + ", ".join(MECHANICAL_HOOK_TYPES) + " (use 'custom_text_"
    "only' if it's meaningful but shouldn't move any number). If the "
    "hook is 'skill_yield_bonus' the target must be one of: farming, "
    "construction, medicine. If it's 'goal_flavor_bias' the target "
    "must be one of: forage, gather, socialize, wander, rest. "
    "If a specific institution's long-standing want is mentioned, "
    "prefer a rule that would actually satisfy or respond to it over "
    "an unrelated one. "
    "Otherwise leave target empty. Ground it in what has actually "
    "happened to these people. "
    'Respond with strict JSON only, no other text: {"name": "a short '
    'name, under 8 words", "description": "one sentence, under 25 '
    'words, phrased as when X then Y", "trigger": "one of the exact '
    'listed trigger words", "hook_type": "one of the exact listed '
    'effect words", "hook_target": "a valid target or empty string", '
    '"magnitude": a number between 0 and 1}.'
)

_FALLBACK_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("Mourning Bell", "When someone dies, the village rings a bell and pauses its work.", "on_death", "custom_text_only"),
    ("Welcome Fire", "When a child is born, a fire is lit outside the family's door that night.", "on_birth", "custom_text_only"),
    ("Cooling Words", "When a feud breaks out, the elders speak first before anyone else.", "on_feud", "custom_text_only"),
    ("Maker's Toast", "When someone invents something new, the village toasts them at the next meal.", "on_invention", "custom_text_only"),
    ("Dry Season Rationing", "When the land turns dry, shares are quietly rationed before anyone asks.", "on_drought", "custom_text_only"),
    ("Harvest Feast", "When the granary overflows, the village holds a shared feast.", "on_surplus", "custom_text_only"),
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], existing_rule_names: list[str],
    institution_grounding: str = "",
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    rules_text = "; ".join(existing_rule_names) if existing_rule_names else "None yet."
    parts = [
        f"The village of {settlement_name}. Recent history:\n{events_text}\n"
        f"Rules the village already lives by: {rules_text}",
    ]
    if institution_grounding:
        # Vision item 2.2: an institution stuck wanting the same thing
        # for a real stretch of time is exactly the "council remembers
        # a famine legislating against it" case — grounding the
        # proposal in that persistent want, not just recent events.
        parts.append(institution_grounding)
    parts.append("Originate one new trigger-and-effect rule this village might genuinely have.")
    return "\n".join(parts)


def fallback_propose(existing_count: int) -> dict:
    name, description, trigger, hook_type = _FALLBACK_RULES[existing_count % len(_FALLBACK_RULES)]
    return {
        "name": name, "description": description, "trigger": trigger,
        "hook_type": hook_type, "hook_target": "", "magnitude": 0.5,
    }


def parse_propose(result: dict, fallback: dict) -> dict:
    name = result.get("name")
    description = result.get("description")
    trigger = result.get("trigger")
    hook_type = result.get("hook_type")
    hook_target = result.get("hook_target")
    magnitude = result.get("magnitude")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    if not isinstance(trigger, str) or trigger not in TRIGGER_TYPES:
        trigger = fallback["trigger"]
    if not isinstance(hook_type, str) or hook_type not in MECHANICAL_HOOK_TYPES:
        hook_type = fallback["hook_type"]
    hook_target = hook_target.strip() if isinstance(hook_target, str) else fallback["hook_target"]
    if not isinstance(magnitude, (int, float)):
        magnitude = fallback["magnitude"]
    return {
        "name": name.strip()[:80],
        "description": description.strip()[:200],
        "trigger": trigger,
        "hook_type": hook_type,
        "hook_target": hook_target,
        "magnitude": float(magnitude),
    }
