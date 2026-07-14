"""Settlement fission: the LLM decides whether a crowded settlement's
most driven inhabitant actually leads a founding party out.

Same candidacy/decision split as deliberate guild founding
(llm/founding.py): `Population.fission_candidate` finds the
deterministic preconditions (a crowded, established settlement and an
ambitious, healthy leader — see the FISSION_* constants in
agents/population.py); this module owns only the judgement call — a
one-way, community-splitting decision with more than one believable
future, exactly the kind CLAUDE.md routes to the LLM. Declining is a
real outcome: an ambitious villager can weigh the risk and stay.
"""
from __future__ import annotations

FALLBACK_DEPART_AMBITION = 0.55
"""Fallback bar: without the LLM, only a strikingly driven leader
(well above FISSION_LEADER_AMBITION's 0.35 candidacy floor) takes the
leap — the deterministic path founds settlements rarely, preserving
"a once-an-era event" even through a long Ollama outage."""

SYSTEM_PROMPT = (
    "You decide whether a villager leads a group away to found a new settlement. "
    "Respond ONLY with JSON: {\"depart\": true or false, \"reason\": \"one short sentence in their voice\"}."
)


def build_prompt(
    leader, settlement_name: str, members: int, housing_capacity: int, season: str,
) -> str:
    ambition = leader.traits.get("ambition", 0.0)
    openness = leader.traits.get("openness", 0.0)
    lines = [
        f"{settlement_name} holds {members} people but shelter for only about {housing_capacity}.",
        f"{leader.name} is spoken of as driven (ambition {ambition:+.2f}, openness {openness:+.2f}).",
        f"It is {season}. Founding a new settlement means leading friends and family",
        "to raw land a long walk away: no granary, no walls, a hard first year —",
        "but room to grow and a place bearing their own mark.",
        f"Does {leader.name} lead a founding party out, or stay?",
    ]
    if leader.memories:
        lines.insert(2, f"They remember: {leader.memories[-1]}")
    return "\n".join(lines)


def fallback_decision(leader) -> dict:
    depart = leader.traits.get("ambition", 0.0) >= FALLBACK_DEPART_AMBITION
    reason = (
        "There is no room left here for what I mean to build."
        if depart else "Not yet — my roots still hold me here."
    )
    return {"depart": depart, "reason": reason}


def parse_decision(result: dict, fallback: dict) -> tuple[bool, str]:
    depart = result.get("depart", fallback["depart"])
    if not isinstance(depart, bool):
        depart = str(depart).strip().lower() in ("true", "yes", "1")
    reason = str(result.get("reason", "") or fallback["reason"]).strip()
    if len(reason) > 200:
        reason = reason[:197] + "..."
    return depart, reason
