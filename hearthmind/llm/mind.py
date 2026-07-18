"""One-time permanent-identity authoring for a newly-seated core-cast
member (Phase J, docs/VISION-2026-07.md, "Deeper Minds" — permanent
tier only, see `agents/agent.py`'s `MAX_MIND_TEXT_CHARS` for the full
scope decision). Genesis-style: fired once per agent's entire life, the
same "instant deterministic placeholder, LLM silently improves it in
the background" shape `World.tick()`'s settlement-naming job already
uses — never revised afterward, unlike beliefs/semantic memories.
"""
from __future__ import annotations

from hearthmind.agents.agent import MAX_VOICE_TEXT_CHARS, Agent, describe_traits

SYSTEM_PROMPT = (
    "You are naming the permanent, unchanging core of one villager in a small "
    "simulated world — not a passing mood or a recent event, but who they "
    "fundamentally are: what they value, what they fear, what they want out of "
    "life, how they see their place in the world. This is written once and "
    "never revisited, so write it as a lasting truth about them, not a "
    "reaction to anything happening right now. Also give them a distinct "
    "manner of speaking — a cadence, a favorite figure of speech, a verbal "
    "habit — so a reader could recognize their voice without seeing their name. "
    'Respond with strict JSON only, no other text: {"mind": "one to two '
    'sentences, under 35 words, third person, this villager\'s permanent '
    'inner character", "voice": "under 12 words, third person, one concrete '
    'habit of speech"}.'
)


def build_prompt(agent: Agent) -> str:
    traits_text = describe_traits(agent.traits)
    personality = f" They are {traits_text}." if traits_text else ""
    return f"{agent.name} has just come of age in this village.{personality} Who are they, at their core?"


def fallback_mind(agent: Agent) -> dict:
    from hearthmind.agents.agent import describe_mind_fallback, describe_voice_fallback
    return {
        "mind": describe_mind_fallback(agent.name, agent.traits),
        "voice": describe_voice_fallback(agent.name, agent.id),
    }


def parse_mind(result: dict, fallback: dict) -> str:
    text = result.get("mind")
    if not isinstance(text, str) or not text.strip():
        text = fallback["mind"]
    return text.strip()[:220]


def parse_voice(result: dict, fallback: dict) -> str:
    text = result.get("voice")
    if not isinstance(text, str) or not text.strip():
        text = fallback["voice"]
    return text.strip()[:MAX_VOICE_TEXT_CHARS]
