"""Memory drift/reinterpretation (v0.87.0, "learns like a human" —
"gradual forgetting/distortion"): a person's old memories don't stay
pristine in storage the way `Agent.memories` otherwise implies — they
fade, blur, and get quietly reinterpreted with time and hindsight,
never simply vanishing at a hard cap with no trace of having changed.
This is the same distortion idea `InterpretRumor()` (`rumor_interpret.
py`) already applies to a rumor at the moment it's HEARD, applied
instead to an agent's own memory some time AFTER it was formed — same
"the distortion lands as a new entry via the existing mechanism, no new
persistent object model" scoping (see that module's docstring), same
discipline "keep the core of what happened recognizable; don't invent
an entirely different event."

Deliberately a genuinely NEW, infrequent LLM call (not a zero-cost
extension of an existing job, per explicit user direction that a small
new call-volume budget is acceptable for this batch) — scheduled
core-cast-only, monthly-round-robin (one settlement's turn per month,
same shape as `_maybe_schedule_dream`), and additionally gated to a low
per-eligible-agent probability so it stays rare texture, not a routine
monthly rewrite of everyone's memories.
"""
from __future__ import annotations

from hearthmind.agents.agent import Agent, describe_traits

SYSTEM_PROMPT = (
    "You are one villager in a small simulated world, looking back on something "
    "that happened to you a while ago. With time and hindsight, memory isn't "
    "perfect — retell this old memory the way you'd actually remember it now: "
    "maybe softened, maybe sharpened, a detail blurred or exaggerated, colored by "
    "who you are and what's happened since. Keep the core of what happened "
    "recognizable; don't invent an entirely different event, and don't erase what "
    "actually happened. "
    'Respond with strict JSON only, no other text: {"remembered_now": "one '
    'sentence, under 25 words, first-person, how you\'d actually remember it '
    'today"}.'
)


def build_prompt(agent: Agent, old_memory: str) -> str:
    personality = describe_traits(agent.traits)
    personality_text = f" You are {personality}." if personality else ""
    return (
        f"You are {agent.name}.{personality_text} A while ago, this happened: "
        f"\"{old_memory}\" Looking back on it now, how do you actually remember it?"
    )


def fallback_drift(old_memory: str) -> dict:
    """Deterministic stand-in: passes the memory through unchanged — a
    fallback shouldn't invent distortion it can't ground in anything,
    same discipline as `rumor_interpret.fallback_interpretation`. Since
    this leaves the text identical, `SimulationEngine._maybe_schedule_
    memory_drift`'s apply() skips the write entirely on a fallback
    result (see its docstring) rather than performing a no-op replace."""
    return {"remembered_now": old_memory}


def parse_drift(result: dict, fallback: dict) -> str:
    text = result.get("remembered_now")
    if not isinstance(text, str) or not text.strip():
        text = fallback["remembered_now"]
    return text.strip()[:150]
