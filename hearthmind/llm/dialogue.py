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
    latest_tradition: str, season: str, weather: str, beliefs_about: list[str] | None = None,
) -> str:
    is_parent_child = (
        (agent_a.parents is not None and agent_b.id in agent_a.parents)
        or (agent_b.parents is not None and agent_a.id in agent_b.parents)
    )
    if is_parent_child:
        # Family ties override the affinity-band read — a parent and
        # child talk like family even on a tick their numeric affinity
        # happens to read distant, and a fresh LLM prompt should know
        # this is not two strangers. See docs/DECISIONS.md,
        # family-memory pass.
        tie = "parent and child"
    elif affinity >= 0.6:
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
    beliefs_text = (
        f" What the village has come to believe about them: {'; '.join(beliefs_about)}."
        if beliefs_about else ""
    )
    return (
        f"{agent_a.name} (hunger {agent_a.hunger:.2f}, energy {agent_a.energy:.2f}) "
        f"meets {agent_b.name} (hunger {agent_b.hunger:.2f}, energy {agent_b.energy:.2f}). "
        f"They are {tie}. It is {season}, weather: {weather}.{culture}{beliefs_text} "
        "Write their brief exchange."
    )


_TENSE_POOL: tuple[tuple[str, str], ...] = (
    ("I have nothing to say to you, {b}.", "Nor I to you."),
    ("Still avoiding me, {b}?", "Can you blame me?"),
    ("We should talk. Eventually.", "Eventually."),
    ("Out of my way.", "Gladly."),
)
_WARM_POOL: tuple[tuple[str, str], ...] = (
    ("Good to see you, {b}.", "And you, always."),
    ("I was hoping to run into you.", "Likewise, {a}."),
    ("You look well today.", "Feeling well, thanks to you."),
    ("Walk with me a while?", "Always."),
)
_NEUTRAL_POOL: tuple[tuple[str, str], ...] = (
    ("Quiet day.", "Quiet enough."),
    ("Cold one, isn't it.", "That it is."),
    ("Anything new?", "Not much, no."),
    ("Long day.", "Isn't it always."),
)
"""Small pools rather than one fixed line per band, cycled
deterministically by (agent ids, tick) — a fallback-only run (Ollama
disabled or unreachable) previously repeated the exact same 3 lines for
every pair forever, which read as an obvious, boring bug. See
docs/DECISIONS.md, "NPCs repeating dialogue" fix."""


def fallback_dialogue(agent_a: Agent, agent_b: Agent, affinity: float, tick: int = 0) -> dict:
    """Deterministic stand-in, varying by relationship band and cycled
    by tick so the same pair doesn't get the identical line every time —
    mirrors cognition.fallback_goal's approach, extended for variety."""
    if affinity <= RIVALRY_THRESHOLD:
        pool, sentiment = _TENSE_POOL, "tense"
    elif affinity >= 0.6:
        pool, sentiment = _WARM_POOL, "warm"
    else:
        pool, sentiment = _NEUTRAL_POOL, "neutral"
    line_a, line_b = pool[(agent_a.id + agent_b.id + tick) % len(pool)]
    return {
        "line_a": line_a.format(a=agent_a.name, b=agent_b.name),
        "line_b": line_b.format(a=agent_a.name, b=agent_b.name),
        "sentiment": sentiment, "rumor": "",
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
