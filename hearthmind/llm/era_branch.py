"""One-time-per-era-advance LLM job: chooses which of a small, fixed
set of named "branches" (settlement/buildings.py's ERA_BRANCH_NAMES)
best fits this settlement's own recent history — v1 audit fix,
"let emergence/LLM steer its own course of era progression." Fires
only right after `SimulationEngine._maybe_advance_era` moves a
settlement into a new era (a handful of times per settlement's whole
life), never periodically, so it needs no round-robin day slot.

Deliberately a CLOSED choice among ERA_BRANCH_NAMES, not free text —
the branch nudges real building-selection odds (`choose_building_kind`'s
`branch` param), so the LLM must land on a mechanically-supported
option rather than inventing an unsupported one. This is the "bounded
branch space" the branching-influence design explicitly requires: the
LLM decides WHICH of the existing paths a settlement leans into, never
invents a wholly new one outside what the engine can act on.
"""
from __future__ import annotations

from hearthmind.settlement.buildings import ERA_BRANCH_NAMES

SYSTEM_PROMPT = (
    "You are choosing the emerging character of a small simulated village as it enters a "
    "new era of its history. Given what the village has recently lived through, choose "
    "which ONE of the following paths it is leaning toward: "
    f"{', '.join(ERA_BRANCH_NAMES)}. "
    'Respond with strict JSON only, no other text: {"branch": "one of the exact listed '
    'words", "reason": "one short sentence, under 20 words, explaining why"}.'
)


def build_prompt(settlement_name: str, era: str, recent_events: list[dict], current_branch: str) -> str:
    lines = [f"- {event['description']}" for event in recent_events[-6:]]
    events_text = "\n".join(lines) if lines else "Nothing especially notable yet."
    previous = f" It had been leaning {current_branch} before this." if current_branch else ""
    return (
        f"The village of {settlement_name} has just entered the {era} era.{previous}\n"
        f"What it has recently lived through:\n{events_text}\n"
        "Which path does it lean toward now?"
    )


def fallback_branch(rng) -> dict:
    """Deterministic stand-in: a real pick, not a no-op — unlike a
    quarterly digest job (where "nothing changed" is a fine outcome),
    a settlement needs SOME branch as soon as it enters a new era so
    `choose_building_kind` has something to read; an empty answer would
    silently degrade to "no lean at all," not a genuine texture-only
    absence. See llm.institution_culture.fallback_digest for the
    contrasting genuine-no-op shape used elsewhere."""
    return {"branch": rng.choice(ERA_BRANCH_NAMES), "reason": ""}


def parse_branch(result: dict, fallback: dict) -> tuple[str, str]:
    branch = result.get("branch")
    if not isinstance(branch, str) or branch not in ERA_BRANCH_NAMES:
        branch = fallback["branch"]
    reason = result.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return branch, reason.strip()[:160]
