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

_VALID_OUTCOMES = ("reconcile", "feud", "council_ruling", "ostracism")

OSTRACISM_REPUTATION_GAP = 0.6
"""How lopsided the two parties' village standing (`reputation()`) must
be before the deterministic fallback will impose ostracism on its own —
deliberately steep so this stays the rare, severe-case outcome the
prompt itself asks for, not a routine substitute for feud/council_
ruling."""

SYSTEM_PROMPT = (
    "Two villagers in a small simulated world have a long, genuinely "
    "soured feud, and it has come to a head. Given who they are, decide "
    "how it breaks: they reconcile, the feud hardens for good, the council "
    "imposes a ruling that forces a cold truce (only if the village has a "
    "council of elders), or — only for a genuinely severe case, one clearly "
    "in the wrong (theft, betrayal, a wrong the village itself would "
    "recognize) — the village ostracizes that one party for a time. "
    "There is no correct answer; choose what these two specific people "
    "would plausibly do; ostracism should be rare, reserved for real "
    "wrongdoing, not an ordinary personal grudge. "
    'Respond with strict JSON only, no other text: {"outcome": '
    '"reconcile" | "feud" | "council_ruling" | "ostracism", "ostracized": '
    '"a" | "b" (only meaningful if outcome is "ostracism" — which of the '
    'two, by their position below, is shunned), "narration": "one sentence, '
    'under 25 words, describing how it played out"}.'
)


def build_prompt(
    agent_a: Agent, agent_b: Agent, relationship: float, settlement_name: str, has_council: bool,
    reputation_a: float = 0.0, reputation_b: float = 0.0, rival_factions: bool = False,
    debt_a_owes_b: float = 0.0, debt_b_owes_a: float = 0.0, rival_families: bool = False,
    council_favors_a: bool = False, council_favors_b: bool = False,
    has_law_against_feuding: bool = False,
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
    # v0.87.15 "emergent leadership" (docs/IDEAS-2026-07-EMERGENCE.md §7):
    # the council is no longer a neutral appeal — if one faction holds a
    # majority of its living seats, the OTHER party has real reason to
    # doubt an impartial ruling, same "let a faction majority... bias
    # dispute rulings" the idea doc names.
    council_leaning_line = ""
    if has_council and council_favors_a and not council_favors_b:
        council_leaning_line = f" The council is dominated by {agent_a.name}'s own faction — {agent_b.name} may not trust it to rule fairly."
    elif has_council and council_favors_b and not council_favors_a:
        council_leaning_line = f" The council is dominated by {agent_b.name}'s own faction — {agent_a.name} may not trust it to rule fairly."
    # Item 8c ("laws & customs"): a codified norm against feuding gives
    # the village a real stake in HOW this breaks, not just the two
    # people involved.
    law_line = (
        " The village holds a norm against letting feuds fester unresolved."
        if has_law_against_feuding else ""
    )
    return (
        f"(\"a\" = {agent_a.name}, \"b\" = {agent_b.name}, for the ostracized field.) "
        f"{agent_a.name} and {agent_b.name}{place} have festered into open enmity "
        f"(their regard for each other stands at {relationship:.2f} on a -1..1 scale)."
        f"{personality}{council}{council_leaning_line}{reputation_line}{faction_line}{debt_line}{family_line}{law_line} How does it break?"
    )


def fallback_dispute(
    agent_a: Agent, agent_b: Agent, has_council: bool, reputation_a: float = 0.0, reputation_b: float = 0.0,
    rival_factions: bool = False, debt_a_owes_b: float = 0.0, debt_b_owes_a: float = 0.0,
    rival_families: bool = False, council_favors_a: bool = False, council_favors_b: bool = False,
    has_law_against_feuding: bool = False,
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
    # v0.87.15 "emergent leadership": a party who doesn't trust the
    # council to be impartial won't accept a clean ruling — pushes away
    # from the easy middle outcome, same direction as a rival faction.
    if has_council and (council_favors_a != council_favors_b):
        avg_sociability -= 0.15
    # Item 8c: a village that has codified a norm against unresolved
    # feuds exerts real social pressure toward settling this one, one
    # way or another — pushes away from an indefinite stalemate.
    if has_law_against_feuding:
        avg_sociability += 0.15
    # §1 "deviance loop": ostracism is deliberately rare and reserved for
    # a genuinely lopsided case (one party's village standing is far
    # worse than the other's) with a council present to impose it —
    # never the default outcome for an ordinary mutual grudge.
    if has_council and abs(reputation_a - reputation_b) >= OSTRACISM_REPUTATION_GAP:
        ostracized = "a" if reputation_a < reputation_b else "b"
        shunned = agent_a if ostracized == "a" else agent_b
        return {
            "outcome": "ostracism", "ostracized": ostracized,
            "narration": f"The village turned its back on {shunned.name} for what happened with {agent_a.name if shunned is agent_b else agent_b.name}.",
        }
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


def parse_dispute(result: dict, fallback: dict, has_council: bool) -> tuple[str, str, str]:
    """Returns `(outcome, narration, ostracized)` — `ostracized` is
    `"a"`/`"b"` (meaningful only when `outcome == "ostracism"`) or `""`
    otherwise."""
    outcome = result.get("outcome")
    if not isinstance(outcome, str) or outcome.strip().lower() not in _VALID_OUTCOMES:
        outcome = fallback["outcome"]
    else:
        outcome = outcome.strip().lower()
    if outcome in ("council_ruling", "ostracism") and not has_council:
        outcome = "feud"  # no council exists to rule/ostracize — the model imagined one
    narration = result.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        narration = fallback["narration"]
    ostracized = ""
    if outcome == "ostracism":
        raw = result.get("ostracized")
        if isinstance(raw, str) and raw.strip().lower() in ("a", "b"):
            ostracized = raw.strip().lower()
        else:
            ostracized = fallback.get("ostracized", "a")
    return outcome, narration.strip()[:200], ostracized
