"""Ambient NPC-to-NPC dialogue: colocated agents periodically exchange a
short LLM-authored line each. The exchange nudges their relationship
(warmer, tenser, or unchanged) and may seed a rumor, which is logged as a
normal event and so gets read back into the chronicle/culture prompts
like anything else that happens in the world. This is the concrete
mechanism behind "NPCs talk to and influence each other" — see
docs/DECISIONS.md, E2.
"""
from __future__ import annotations

from hearthmind.agents.agent import RIVALRY_THRESHOLD, Agent

SYSTEM_PROMPT = (
    "You are writing a brief, natural exchange between two villagers who "
    "just crossed paths in a simulated world. Keep it grounded in their "
    "current state and relationship, not generic small talk. Optionally "
    "the exchange plants a short rumor that might spread through the "
    "village — leave it blank most of the time. "
    'Respond with strict JSON only, no other text: {"line_a": "under 10 '
    'words, said by the first villager", "line_b": "under 10 words, said '
    'by the second", "sentiment": "warm" | "tense" | "neutral", "rumor": '
    '"" or a short rumor under 15 words}.'
)


def build_prompt(
    agent_a: Agent, agent_b: Agent, affinity: float, settlement_name: str,
    latest_tradition: str, season: str, weather: str,
) -> str:
    if affinity >= 0.6:
        tie = "close friends"
    elif affinity <= RIVALRY_THRESHOLD:
        tie = "at odds with each other"
    elif affinity <= 0.0:
        tie = "strangers, or barely acquainted"
    else:
        tie = "friendly acquaintances"
    culture = f" They live in {settlement_name}." if settlement_name else ""
    if settlement_name and latest_tradition:
        culture += f" The village keeps this tradition: {latest_tradition}."
    return (
        f"{agent_a.name} (hunger {agent_a.hunger:.2f}, energy {agent_a.energy:.2f}) "
        f"meets {agent_b.name} (hunger {agent_b.hunger:.2f}, energy {agent_b.energy:.2f}). "
        f"They are {tie}. It is {season}, weather: {weather}.{culture} "
        "Write their brief exchange."
    )


def fallback_dialogue(agent_a: Agent, agent_b: Agent, affinity: float) -> dict:
    """Deterministic stand-in, varying by relationship band so a
    fallback-only run still produces some texture instead of one repeated
    line — mirrors cognition.fallback_goal's approach."""
    if affinity <= RIVALRY_THRESHOLD:
        return {
            "line_a": f"I have nothing to say to you, {agent_b.name}.",
            "line_b": "Nor I to you.",
            "sentiment": "tense", "rumor": "",
        }
    if affinity >= 0.6:
        return {
            "line_a": f"Good to see you, {agent_b.name}.",
            "line_b": "And you, always.",
            "sentiment": "warm", "rumor": "",
        }
    return {
        "line_a": "Quiet day.", "line_b": "Quiet enough.",
        "sentiment": "neutral", "rumor": "",
    }


_VALID_SENTIMENTS = {"warm", "tense", "neutral"}


def parse_dialogue(result: dict, fallback: dict) -> dict:
    """Validate an LLM (or fallback) response into a safe dict. Any
    malformed content degrades to the fallback field-by-field rather than
    raising — a bad LLM response should never crash a tick."""
    sentiment = result.get("sentiment")
    if sentiment not in _VALID_SENTIMENTS:
        sentiment = fallback["sentiment"]
    line_a = result.get("line_a")
    line_b = result.get("line_b")
    if not isinstance(line_a, str) or not line_a.strip():
        line_a = fallback["line_a"]
    if not isinstance(line_b, str) or not line_b.strip():
        line_b = fallback["line_b"]
    rumor = result.get("rumor")
    if not isinstance(rumor, str):
        rumor = ""
    return {
        "line_a": line_a.strip()[:120],
        "line_b": line_b.strip()[:120],
        "sentiment": sentiment,
        "rumor": rumor.strip()[:150],
    }
