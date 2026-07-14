"""LLM-mediated dispute resolution (v0.64.0 audit-backlog item): when a
pair's mutual relationship has festered past DISPUTE_RELATIONSHIP_
THRESHOLD, a rare job lets the LLM decide how the feud breaks —
reconciliation, a hardened feud, or (only if a council exists) a council
ruling forcing a truce. Every outcome has real mechanical effects
(`Population.apply_dispute`): relationships/trust move, memories are
left, traits nudge. The deterministic fallback reads the pair's own
sociability and the council's existence — a legible rule, not a coin
flip."""
from __future__ import annotations

from hearthmind.agents.agent import TRAIT_SOCIABILITY, Agent, describe_traits

_VALID_OUTCOMES = ("reconcile", "feud", "council_ruling")

SYSTEM_PROMPT = (
    "Two villagers in a small simulated world have a long, genuinely "
    "soured feud, and it has come to a head. Given who they are, decide "
    "how it breaks: they reconcile, the feud hardens for good, or — only "
    "if the village has a council of elders — the council imposes a "
    "ruling that forces a cold truce. There is no correct answer; choose "
    "what these two specific people would plausibly do. "
    'Respond with strict JSON only, no other text: {"outcome": '
    '"reconcile" | "feud" | "council_ruling", "narration": "one sentence, '
    'under 25 words, describing how it played out"}.'
)


def build_prompt(
    agent_a: Agent, agent_b: Agent, relationship: float, settlement_name: str, has_council: bool,
) -> str:
    personality_bits = []
    for agent in (agent_a, agent_b):
        traits = describe_traits(agent.traits)
        if traits:
            personality_bits.append(f"{agent.name} is {traits}")
    personality = f" {'; '.join(personality_bits)}." if personality_bits else ""
    council = (
        " The village has a council of elders that could impose a ruling."
        if has_council else " There is no council to appeal to."
    )
    place = f" in {settlement_name}" if settlement_name else ""
    return (
        f"{agent_a.name} and {agent_b.name}{place} have festered into open enmity "
        f"(their regard for each other stands at {relationship:.2f} on a -1..1 scale)."
        f"{personality}{council} How does it break?"
    )


def fallback_dispute(agent_a: Agent, agent_b: Agent, has_council: bool) -> dict:
    """Deterministic stand-in: a sociable pair finds its own way back; an
    unsociable one hardens; a council steps in for the in-between case."""
    avg_sociability = (
        agent_a.traits.get(TRAIT_SOCIABILITY, 0.0) + agent_b.traits.get(TRAIT_SOCIABILITY, 0.0)
    ) / 2.0
    if avg_sociability > 0.2:
        outcome = "reconcile"
        narration = f"{agent_a.name} and {agent_b.name} talked it through at last and set the feud down."
    elif has_council:
        outcome = "council_ruling"
        narration = f"The council of elders ruled on the feud between {agent_a.name} and {agent_b.name}."
    else:
        outcome = "feud"
        narration = f"Nothing softened between {agent_a.name} and {agent_b.name}; the feud hardened."
    return {"outcome": outcome, "narration": narration}


def parse_dispute(result: dict, fallback: dict, has_council: bool) -> tuple[str, str]:
    outcome = result.get("outcome")
    if not isinstance(outcome, str) or outcome.strip().lower() not in _VALID_OUTCOMES:
        outcome = fallback["outcome"]
    else:
        outcome = outcome.strip().lower()
    if outcome == "council_ruling" and not has_council:
        outcome = "feud"  # no council exists to rule — the model imagined one
    narration = result.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        narration = fallback["narration"]
    return outcome, narration.strip()[:200]
