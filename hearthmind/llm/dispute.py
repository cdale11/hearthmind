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
    reputation_a: float = 0.0, reputation_b: float = 0.0, rival_factions: bool = False,
    debt_a_owes_b: float = 0.0, debt_b_owes_a: float = 0.0, rival_families: bool = False,
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
    # Phase L "Reputation" (docs/VISION-2026-07.md): only mentioned when
    # it's actually lopsided — a village's general opinion of the two
    # parties is ambient context for how a feud plausibly breaks, not
    # something worth stating when both are equally regarded (or
    # unknown, REPUTATION_MIN_SOURCES-thin).
    reputation_line = ""
    if abs(reputation_a - reputation_b) >= 0.3:
        better, worse = (agent_a, agent_b) if reputation_a > reputation_b else (agent_b, agent_a)
        reputation_line = f" {better.name} is generally better regarded in the village than {worse.name}."
    # Phase L "Factions": a rivalry between two different factions raises
    # the stakes past an ordinary personal grudge.
    faction_line = (
        f" {agent_a.name} and {agent_b.name} belong to rival factions in the village."
        if rival_factions else ""
    )
    # Phase L "Economy depth": an unpaid debt is a classic, concrete
    # dispute source — only worth naming when it's actually sizeable
    # (DEBT_DISPUTE_CONTEXT_THRESHOLD), not a rounding-error IOU.
    debt_line = ""
    if debt_a_owes_b >= 1.0 or debt_b_owes_a >= 1.0:
        debtor, creditor = (agent_a, agent_b) if debt_a_owes_b >= debt_b_owes_a else (agent_b, agent_a)
        debt_line = f" {debtor.name} still owes {creditor.name} for past help never repaid."
    # v0.87.11 "generational feuds": their own two households are
    # already at odds — a fresh spat between members of two rival
    # families is generational, not personal, and is that much harder
    # to simply talk through.
    family_line = (
        f" Worse, {agent_a.name}'s and {agent_b.name}'s families have been feuding for generations."
        if rival_families else ""
    )
    return (
        f"{agent_a.name} and {agent_b.name}{place} have festered into open enmity "
        f"(their regard for each other stands at {relationship:.2f} on a -1..1 scale)."
        f"{personality}{council}{reputation_line}{faction_line}{debt_line}{family_line} How does it break?"
    )


def fallback_dispute(
    agent_a: Agent, agent_b: Agent, has_council: bool, reputation_a: float = 0.0, reputation_b: float = 0.0,
    rival_factions: bool = False, debt_a_owes_b: float = 0.0, debt_b_owes_a: float = 0.0,
    rival_families: bool = False,
) -> dict:
    """Deterministic stand-in: a sociable pair finds its own way back; an
    unsociable one hardens; a council steps in for the in-between case.
    Phase L: a pair whose combined village standing runs notably warm
    nudges the same way sociability does (reconciliation is easier when
    others already think well of you both) — reputation only pushes the
    threshold, it never overrides the sociability read outright. Rival
    faction membership pushes the other way — a personal feud between
    two people whose factions are already opposed is harder to set
    down. An unrepaid debt on either side pushes the same way — being
    owed (or owing) something concrete is friction reconciliation has
    to overcome. v0.87.11: a durable inter-family feud pushes the same
    direction as rival factions — harder still, since it's generational
    rather than personal."""
    avg_sociability = (
        agent_a.traits.get(TRAIT_SOCIABILITY, 0.0) + agent_b.traits.get(TRAIT_SOCIABILITY, 0.0)
    ) / 2.0
    avg_reputation = (reputation_a + reputation_b) / 2.0
    if avg_reputation >= 0.3:
        avg_sociability += 0.15
    elif avg_reputation <= -0.3:
        avg_sociability -= 0.15
    if rival_factions:
        avg_sociability -= 0.2
    if rival_families:
        avg_sociability -= 0.2
    if max(debt_a_owes_b, debt_b_owes_a) >= 1.0:
        avg_sociability -= 0.1
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
