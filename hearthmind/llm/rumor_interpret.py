"""InterpretRumor() (Phase K, docs/VISION-2026-07.md, "Knowledge &
Story"): a rumor a core-cast agent hears doesn't stay pristine — they
retell it as themself, coloring it with bias, exaggeration, or a
misremembered detail. Scoped down from the vision doc's fuller `hops`/
`mutated`-field rumor-object model (no such structure exists in this
codebase; rumors are transient strings passed through dialogue/
`_remember`, not persistent tracked entities) — the distortion lands as
a new memory entry via the existing memory mechanism instead, so a
future dialogue exchange naturally propagates the *distorted* version
through the same "recent memories" prompt context every dialogue
already reads. Functionally equivalent emergence (different NPCs
remember the same rumor differently), lighter-weight plumbing.

Tightly capped per day (`INTERPRET_RUMOR_MAX_PER_DAY`,
`simulation/engine.py`) — this fires per listening event, not once a
month like every other settlement job, so it needs its own volume
ceiling on top of the shared daily LLM budget.
"""
from __future__ import annotations

from hearthmind.agents.agent import describe_traits

SYSTEM_PROMPT = (
    "You are one villager in a small simulated world, retelling a rumor you "
    "just heard the way you personally would — colored by your own nature, "
    "not a neutral repeat. You might exaggerate, soften it, get a small "
    "detail wrong, or read more into it than was said. Keep the core of "
    "what happened recognizable; don't invent an entirely different event. "
    'Respond with strict JSON only, no other text: {"retelling": "one '
    'sentence, under 25 words, first-person or as you\'d actually say it, '
    'coloured by your own take"}.'
)


def build_prompt(agent_name: str, traits: dict, rumor: str) -> str:
    personality = describe_traits(traits)
    personality_text = f" You are {personality}." if personality else ""
    return f"You are {agent_name}.{personality_text} You just heard: \"{rumor}\" How would you retell it?"


def fallback_interpretation(agent_name: str, rumor: str) -> dict:
    """Deterministic stand-in: passes the rumor through close to verbatim,
    just reframed as this agent's own retelling rather than a bare quote
    — a fallback shouldn't invent bias it can't ground in anything."""
    return {"retelling": f"I heard: {rumor}"}


def parse_interpretation(result: dict, fallback: dict) -> str:
    text = result.get("retelling")
    if not isinstance(text, str) or not text.strip():
        text = fallback["retelling"]
    return text.strip()[:150]
