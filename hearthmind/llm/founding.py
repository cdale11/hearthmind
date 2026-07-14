"""Deliberate institution founding (v0.64.0 audit-backlog item): the
first institution-formation path that runs through an agent's own
decision rather than a census threshold. When an ambitious master
qualifies (`Population.deliberate_guild_candidate` — at least
DELIBERATE_GUILD_MIN_MASTERS but fewer than the automatic
GUILD_FORMATION_MASTER_COUNT), the LLM decides *whether this specific
person actually does it* — founding early is an act of individual
drive, and the model is free to decide they hold back. The fallback is
the founder's own ambition, so a deterministic run still gets early
foundings from its most driven masters."""
from __future__ import annotations

from hearthmind.agents.agent import TRAIT_AMBITION, Agent, describe_traits

FALLBACK_FOUND_AMBITION = 0.4
"""Fallback bar: without an LLM, a candidate founds the guild only when
their ambition clears this — higher than the candidacy bar
(DELIBERATE_GUILD_FOUNDER_AMBITION, 0.3), so the fallback founds
sometimes, not always."""

SYSTEM_PROMPT = (
    "You are the inner voice of an accomplished villager in a small "
    "simulated world weighing whether to formally organize their trade "
    "into a guild now, with only a couple of masters in the village, or "
    "wait for the craft to grow on its own. Either answer is reasonable "
    "— decide what this specific person would do. "
    'Respond with strict JSON only, no other text: {"found": true | '
    'false, "reason": "a short first-person reason, under 15 words"}.'
)


def build_prompt(founder: Agent, skill: str, master_count: int, settlement_name: str) -> str:
    personality = describe_traits(founder.traits)
    personality_text = f" You are {personality}." if personality else ""
    place = f" of {settlement_name}" if settlement_name else ""
    return (
        f"You are {founder.name}, one of only {master_count} true masters of {skill} in the "
        f"village{place}. There is no {skill} guild yet.{personality_text} "
        "Do you gather the others and found one now?"
    )


def fallback_founding(founder: Agent) -> dict:
    ambitious = founder.traits.get(TRAIT_AMBITION, 0.0) >= FALLBACK_FOUND_AMBITION
    return {
        "found": ambitious,
        "reason": "the craft deserves a proper guild" if ambitious else "it can wait a while yet",
    }


def parse_founding(result: dict, fallback: dict) -> tuple[bool, str]:
    found = result.get("found")
    if not isinstance(found, bool):
        found = bool(fallback["found"])
    reason = result.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = fallback["reason"]
    return found, reason.strip()[:120]
