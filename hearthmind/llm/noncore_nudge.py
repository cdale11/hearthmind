"""Occasional LLM nudges for non-core-cast agents (item 9, the user's
own framing: "not fully LLM authored but partially and occasionally").
Every other LLM-authored personal cognition (goals, beliefs, dialogue,
mind/voice) is deliberately scoped to `Population.core_agent_ids` to
keep call volume from scaling with population (v0.70.0's swap-after-
hours fix). Item 9 asks for a narrow exception: the rest of the town
should not be permanently LLM-silent — just far rarer than the core
cast, and never per-agent-scaled.

`SimulationEngine._maybe_schedule_noncore_nudge` picks exactly ONE
non-core agent, once a month, round-robin across settlements (the same
flat-regardless-of-population-size shape `_job_target` already gives
every other settlement job) — this is a single call a month for the
*entire world*, not per agent. A genuine LLM answer nudges one trait by
a small bounded amount and plants one short reflective memory; the
fallback is a real no-op (the agent's personality holds exactly as it
was) — an "occasional" nudge that never happens is correct, not a
failure, same discipline `memory_drift.py` established for its own
rare/gated call.
"""
from __future__ import annotations

from hearthmind.agents.agent import Agent, describe_traits

SYSTEM_PROMPT = (
    "You are quietly reflecting on one ordinary villager in a small simulated "
    "world — someone whose life mostly goes unnoticed. Given what little is "
    "known about them, decide whether anything in their recent life would "
    "genuinely, if slightly, reshape who they are — and if so, which single "
    "trait shifts and in which direction. Most of the time nothing rises to "
    "that level, and that is the correct answer. Keep any shift small. "
    'Respond with strict JSON only, no other text: {"shifts": true or false, '
    '"trait": "resilience", "sociability", or "ambition", "direction": '
    '"up" or "down", "reflection": "one short first-person sentence, under 20 '
    'words"}. If shifts is false, trait/direction/reflection may be empty.'
)


def build_prompt(agent: Agent, occupation: str, recent_memories: list[str]) -> str:
    personality = describe_traits(agent.traits)
    personality_text = f" You are {personality}." if personality else ""
    occupation_text = f" You work as a {occupation}." if occupation else ""
    memory_text = f" Recently: {' | '.join(recent_memories)}." if recent_memories else " Nothing notable has happened to you lately."
    return f"You are {agent.name}, an ordinary villager.{occupation_text}{personality_text}{memory_text} Has anything changed in you?"


def fallback_nudge() -> dict:
    """Genuine no-op — see module docstring."""
    return {"shifts": False, "trait": "", "direction": "", "reflection": ""}


NUDGE_TRAIT_STEP = 0.12
"""Bounded shift magnitude — small next to the -1..1 trait range, same
"never dominant" shape as every other trait nudge in this project
(TRAIT_SUSTAINED_HUNGER_NUDGE, TRAIT_VIOLENCE_NUDGE, ...)."""

VALID_TRAITS = frozenset({"resilience", "sociability", "ambition"})


def parse_nudge(result: dict, fallback: dict) -> tuple[str, float, str] | None:
    """Returns `(trait, signed_delta, reflection)` or None if nothing
    shifts this attempt — the common, expected case."""
    shifts = result.get("shifts")
    if not isinstance(shifts, bool):
        shifts = fallback["shifts"]
    if not shifts:
        return None
    trait = result.get("trait")
    if not isinstance(trait, str) or trait.strip().lower() not in VALID_TRAITS:
        return None
    direction = result.get("direction")
    if direction not in ("up", "down"):
        return None
    reflection = result.get("reflection")
    if not isinstance(reflection, str) or not reflection.strip():
        return None
    delta = NUDGE_TRAIT_STEP if direction == "up" else -NUDGE_TRAIT_STEP
    return trait.strip().lower(), delta, reflection.strip()[:140]
