"""One-time permanent-identity authoring for a newly-seated core-cast
member (Phase J, docs/VISION-2026-07.md, "Deeper Minds" — permanent
tier only, see `agents/agent.py`'s `MAX_MIND_TEXT_CHARS` for the full
scope decision). Genesis-style: fired once per agent's entire life, the
same "instant deterministic placeholder, LLM silently improves it in
the background" shape `World.tick()`'s settlement-naming job already
uses — never revised afterward, unlike beliefs/semantic memories.
"""
from __future__ import annotations

from hearthmind.agents.agent import MAX_VOICE_TEXT_CHARS, Agent, describe_traits, normalize_voice_phrase

SYSTEM_PROMPT = (
    "You are naming the permanent, unchanging core of one villager in a small "
    "simulated world — not a passing mood or a recent event, but who they "
    "fundamentally are: what they value, what they fear, what they want out of "
    "life, how they see their place in the world. This is written once and "
    "never revisited, so write it as a lasting truth about them, not a "
    "reaction to anything happening right now. Also give them a distinct "
    "manner of speaking — a cadence, a favorite figure of speech, a verbal "
    "habit — so a reader could recognize their voice without seeing their name. "
    "Also name ONE long-term ambition this character will carry for years — "
    "something concrete they want out of their life here, grounded in who "
    "they are, not a passing want. "
    'Respond with strict JSON only, no other text: {"mind": "one to two '
    'sentences, under 35 words, third person, this villager\'s permanent '
    'inner character", "voice": "under 12 words: a bare predicate phrase '
    'with NO subject and no leading pronoun, as if continuing the sentence '
    '\'<Name> ...\' — e.g. \'speaks in short, plain sentences\' or \'trails '
    'off mid-thought,\' never \'They speak...\' or \'Always speaks...\' with '
    'a capital letter, and no trailing period", "initial_goal": "under 20 '
    'words, third person, what they want out of their life here"}.'
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
    return normalize_voice_phrase(text)[:MAX_VOICE_TEXT_CHARS]


def parse_initial_goal(result: dict) -> str | None:
    """Audit follow-up (v1.3.38: "seeding Agent.long_term_goal at
    genesis"). Optional — unlike mind/voice there is no fallback text;
    a missing/empty answer just means no goal is seeded yet, and the
    existing monthly life-event-gated job (llm/beliefs.py's
    parse_long_term_goal) will form one naturally later. Never
    fabricate a standing ambition from a deterministic template."""
    text = result.get("initial_goal")
    if not isinstance(text, str) or not text.strip():
        return None
    return text.strip()[:150]
