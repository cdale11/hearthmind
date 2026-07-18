"""LLM-narrated skill mastery (deferred item 5, docs/VISION-2026-07-
LEARNING.md): v0.87.0 kept mastery narration zero-cost/deterministic
("Became a master of X after years of practice.") for every agent. For
the core cast specifically, this reads back the agent's own recent
memories and traits to narrate mastery grounded in their actual lived
experience ("got better at healing after losing a patient," the
deferred item's own framing) instead of the fixed template.

Genuinely a new, small LLM call (approved call-volume budget for this
batch) — but deliberately narrow: it only ever REPLACES one already-
written memory (`SimulationEngine._maybe_schedule_skill_mastery`
mutates `agent.memories[-1]` in place, the exact same "old_memory
identity check before mutating" guard `memory_drift.py` established),
never the settlement-wide event log, which stays the deterministic
"true master" line for every agent regardless of core-cast status —
this is personal narration, not public record. Fallback is a genuine
no-op (the deterministic template `_remember` already wrote stands
unchanged), same discipline as `memory_drift.fallback_drift`.
"""
from __future__ import annotations

from hearthmind.agents.agent import Agent, describe_traits

SYSTEM_PROMPT = (
    "You are one villager in a small simulated world, reflecting on finally "
    "mastering a skill after years of practice. Ground it in what's actually "
    "happened to you if anything relevant is given (a hardship, a memorable "
    "moment) rather than generic pride — real skill is often won through a "
    "specific struggle, not just repetition. "
    'Respond with strict JSON only, no other text: {"reflection": "one sentence, '
    'under 25 words, first-person, how you think back on finally mastering it"}.'
)


def build_prompt(agent: Agent, skill: str, recent_memories: list[str]) -> str:
    personality = describe_traits(agent.traits)
    personality_text = f" You are {personality}." if personality else ""
    memory_text = (
        f" Recently: {' | '.join(recent_memories)}." if recent_memories else ""
    )
    return (
        f"You are {agent.name}.{personality_text} You have just truly mastered {skill}, "
        f"after years of practice.{memory_text} Looking back, how do you think of "
        f"finally reaching mastery?"
    )


def fallback_mastery() -> dict:
    """Genuine no-op: `remember_mastery`'s already-written deterministic
    template memory is left completely unchanged — there is nothing
    grounded to fall back to that isn't already what's stored."""
    return {"reflection": ""}


def parse_mastery(result: dict, fallback: dict) -> str:
    text = result.get("reflection")
    if not isinstance(text, str) or not text.strip():
        text = fallback["reflection"]
    return text.strip()[:150]
