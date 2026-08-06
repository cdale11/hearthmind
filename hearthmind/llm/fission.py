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

import random

FALLBACK_DEPART_AMBITION = 0.55
"""Fallback bar: without the LLM, only a strikingly driven leader
(well above FISSION_LEADER_AMBITION's 0.35 candidacy floor) takes the
leap — the deterministic path founds settlements rarely, preserving
"a once-an-era event" even through a long Ollama outage."""

SYSTEM_PROMPT = (
    "You decide whether a villager leads a group away to found a new settlement. "
    "If told the village shares a specific belief, also decide whether the departing group "
    "carries it with them faithfully or breaks from it in a quiet schism — a different reading "
    "of the same belief, not necessarily a hostile one. Ignore the schism question entirely if "
    "no belief is mentioned. "
    "Respond ONLY with JSON: {\"depart\": true or false, \"reason\": \"one short sentence in their voice\", "
    "\"schism\": true or false}."
)


def build_prompt(
    leader, settlement_name: str, members: int, housing_capacity: int, season: str,
    religion_name: str | None = None,
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
    # Phase M schism hook: only mentioned when the home settlement
    # actually holds a named belief — this reuses fission's existing
    # one call rather than adding a second, per the "zero added call
    # volume" discipline every optional-field extension in this
    # codebase follows (see Agent.secrets/mind's docstrings for the
    # precedent).
    if religion_name:
        lines.append(
            f"{settlement_name} shares a belief called {religion_name}. If {leader.name} departs, "
            "do the people who leave carry it unchanged, or does the departure mark a quiet schism?"
        )
    return "\n".join(lines)


def fallback_decision(
    leader, members: "int | None" = None, housing_capacity: "int | None" = None,
    policy=None, rng: "random.Random | None" = None,
) -> dict:
    """`policy` (Tier 6, `hearthmind.ml.decision_policy.DecisionPolicy`
    built from `FISSION_POLICY_CONFIG`) is optional and defaults to
    `None`, reproducing this function's exact original ambition-
    threshold output byte-for-byte -- `members`/`housing_capacity`
    are likewise optional and unused on that path, present only so a
    real caller passing them doesn't need a separate signature.
    `schism` stays hard-coded `False` on the policy path too, same
    "the fallback never invents a schism" discipline the pure-
    threshold path already documents below."""
    if policy is not None:
        crowding_ratio = (members / housing_capacity) if members and housing_capacity else 0.0
        state = {
            "trait_ambition": leader.traits.get("ambition", 0.0),
            "trait_openness": leader.traits.get("openness", 0.0),
            "crowding_ratio": crowding_ratio,
        }
        outcome = policy.sample_class(state, rng or random.Random())
        depart = outcome == "depart"
        reason = (
            "There is no room left here for what I mean to build."
            if depart else "Not yet — my roots still hold me here."
        )
        return {"depart": depart, "reason": reason, "schism": False}

    depart = leader.traits.get("ambition", 0.0) >= FALLBACK_DEPART_AMBITION
    reason = (
        "There is no room left here for what I mean to build."
        if depart else "Not yet — my roots still hold me here."
    )
    # Deterministic fallback always keeps the faith unchanged — a schism
    # is meant to be a genuine model read of the leader's own bent, never
    # invented by the fallback path (same discipline as llm/religion.py's
    # "fallback never forms a religion").
    return {"depart": depart, "reason": reason, "schism": False}


def parse_decision(result: dict, fallback: dict) -> tuple[bool, str, bool]:
    depart = result.get("depart", fallback["depart"])
    if not isinstance(depart, bool):
        depart = str(depart).strip().lower() in ("true", "yes", "1")
    reason = str(result.get("reason", "") or fallback["reason"]).strip()
    if len(reason) > 200:
        reason = reason[:197] + "..."
    schism = result.get("schism", fallback["schism"])
    if not isinstance(schism, bool):
        schism = str(schism).strip().lower() in ("true", "yes", "1")
    return depart, reason, schism
