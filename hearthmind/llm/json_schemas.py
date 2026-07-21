"""Per-task JSON Schemas for grammar-constrained decoding (FT.0, docs/
AUDIT-2026-07-20.md's fine-tuning roadmap). llama-server enforces these
at the sampler level via `response_format: {"type": "json_schema", ...}`
(it converts the schema to a GBNF grammar internally) — this is strictly
stronger than the `response_format: {"type": "json_object"}` every call
already sent: that only guarantees syntactically valid JSON, this also
guarantees the *shape* (required keys present, enums honored, types
correct). Ships alongside the audit's warning that today's archive
can't be trained on as-is — eliminating the whole parse/repair failure
class here means future-collected examples spend zero completion budget
on JSON syntax and *never* need `parse_*`'s defensive coercion for
structural reasons (a missing/mistyped field), only for semantic
judgment calls (e.g. `revises` pointing at a real prior belief).

Deliberately scoped to the eleven task names the training recorder
actually observes in a real live run (see any `review_pack.json`
manifest's `task_distribution` — dialogue/cognition/rumor_interpret/
mind/personal_belief/chronicle/beliefs/dream/folklore/naming/
town_brain cover 100% of a real archive). Every other `llm/*.py` job
(caravan, dispute, diplomacy, invention, ...) still works exactly as
before via the unconstrained `json_object` mode — `schema_for_task`
returns `None` for anything not listed here, and every call site
already treats `None` as "no schema, fall back to the old behavior."
Extend this dict opportunistically when a new task earns a real archive
presence; it is not required to stay in lockstep with every `llm/`
module.

Each schema intentionally omits any field `parse_*` treats as "optional,
never fabricate" (secrets, plan fields split across `parse_plan`,
semantic_memory/life_digest/lesson) from `required` — the model is
still allowed to include them (or not); only the fields every fallback
already guarantees a value for are mandatory. `additionalProperties:
False` keeps a chatty model from padding the completion with commentary
fields that would just be dead tokens under `llm_num_predict`.
"""
from __future__ import annotations

_COGNITION_GOALS = ["wander", "forage", "socialize", "rest", "gather", "seek_person", "explore"]
"""Mirrors `agents.agent.AgentGoal`'s values — kept as a plain list here
rather than importing the enum to avoid a llm/ -> agents/ import for
what's otherwise a pure-data module; a new goal added there needs this
list updated too (same manual-sync tradeoff `_VALID_PRIORITIES`/
`_VALID_SENTIMENTS` already accept in their own modules)."""

_TOWN_BRAIN_PRIORITIES = ["growth", "food", "commerce", "education", "health", "defense"]
"""Mirrors `town_brain._VALID_PRIORITIES`."""

_DIALOGUE_SENTIMENTS = ["warm", "tense", "neutral"]
"""Mirrors `dialogue._VALID_SENTIMENTS`."""

TASK_SCHEMAS: dict[str, dict] = {
    "cognition": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "enum": _COGNITION_GOALS},
            "reason": {"type": "string", "maxLength": 200},
        },
        "required": ["goal", "reason"],
        "additionalProperties": False,
    },
    "dialogue": {
        "type": "object",
        "properties": {
            "line_a": {"type": "string", "maxLength": 160},
            "line_b": {"type": "string", "maxLength": 160},
            "sentiment": {"type": "string", "enum": _DIALOGUE_SENTIMENTS},
            "rumor": {"type": "string", "maxLength": 180},
            "topic": {"type": "string", "maxLength": 50},
            "promise": {"type": "string", "maxLength": 120},
            "debt_delta": {"type": "number"},
            "secret_revealed": {"type": "boolean"},
            "misunderstanding": {"type": "boolean"},
            "goal_change": {"type": "boolean"},
        },
        "required": ["line_a", "line_b", "sentiment"],
        "additionalProperties": False,
    },
    "rumor_interpret": {
        "type": "object",
        "properties": {"retelling": {"type": "string", "maxLength": 250}},
        "required": ["retelling"],
        "additionalProperties": False,
    },
    "mind": {
        "type": "object",
        "properties": {
            "mind": {"type": "string", "maxLength": 400},
            "voice": {"type": "string", "maxLength": 200},
        },
        "required": ["mind", "voice"],
        "additionalProperties": False,
    },
    "chronicle": {
        "type": "object",
        "properties": {"summary": {"type": "string", "maxLength": 400}},
        "required": ["summary"],
        "additionalProperties": False,
    },
    "dream": {
        "type": "object",
        "properties": {"dream": {"type": "string", "maxLength": 400}},
        "required": ["dream"],
        "additionalProperties": False,
    },
    "folklore": {
        "type": "object",
        "properties": {
            "worth_telling": {"type": "boolean"},
            "tale": {"type": "string", "maxLength": 240},
        },
        "required": ["worth_telling"],
        "additionalProperties": False,
    },
    "naming": {
        "type": "object",
        "properties": {"name": {"type": "string", "maxLength": 40}},
        "required": ["name"],
        "additionalProperties": False,
    },
    "town_brain": {
        "type": "object",
        "properties": {
            "priority": {"type": "string", "enum": _TOWN_BRAIN_PRIORITIES},
            "rationale": {"type": "string", "maxLength": 220},
        },
        "required": ["priority", "rationale"],
        "additionalProperties": False,
    },
    "beliefs": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "maxLength": 70},
            "belief": {"type": "string", "maxLength": 220},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "revises": {"type": ["integer", "null"]},
        },
        "required": ["subject", "belief", "confidence"],
        "additionalProperties": False,
    },
    "personal_belief": {
        # A strict superset of "beliefs" — `_run_personal_belief` (engine.py)
        # reads several more optional fields off the same one call
        # (semantic_memory, life_digest, lesson, plan) that the settlement
        # job never asks for. None of them go in `required`: each has its
        # own "leave blank most calls, never fabricate" contract in
        # `beliefs.parse_*`.
        "type": "object",
        "properties": {
            "subject": {"type": "string", "maxLength": 70},
            "belief": {"type": "string", "maxLength": 220},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "revises": {"type": ["integer", "null"]},
            "semantic_memory": {"type": "string", "maxLength": 200},
            "life_digest": {"type": "string", "maxLength": 300},
            "lesson_situation": {"type": "string", "maxLength": 100},
            "lesson": {"type": "string", "maxLength": 150},
            "plan_intent": {"type": "string", "maxLength": 120},
            "plan_horizon_days": {"type": "integer", "minimum": 3, "maximum": 30},
            "plan_progress_note": {"type": "string", "maxLength": 150},
        },
        "required": ["subject", "belief", "confidence"],
        "additionalProperties": False,
    },
}


def schema_for_task(name: str) -> dict | None:
    """`None` means "no constrained schema for this task" — every call
    site treats that as a request to fall back to the previous
    unconstrained `json_object` behavior, so adding/removing an entry
    here is always backward compatible."""
    return TASK_SCHEMAS.get(name)
