"""Faction naming (Phase L, docs/VISION-2026-07.md "Society & Power"):
`Population._detect_faction_candidate` finds a cohesive trust-graph
cluster deterministically, with no LLM call — this module only names
and frames what already, mechanically, exists. Same "detect cheaply,
spend the call only to name it" split as deliberate guild founding
(llm/founding.py). Rare by construction: a faction only forms once per
cluster, ever (membership is fixed at formation, see InstitutionKind.
FACTION's docstring), so this call is nowhere near the daily budget."""
from __future__ import annotations

from hearthmind.agents.agent import Agent, describe_traits

SYSTEM_PROMPT = (
    "A cluster of villagers in a small simulated world has grown closer "
    "to each other than to anyone else — a faction, bound by loyalty "
    "rather than blood or trade. Give it a short, plausible name a "
    "village might actually use, and one line on what draws this group "
    "together. "
    'Respond with strict JSON only, no other text: {"name": "two or '
    'three words, no quotes", "framing": "one sentence, under 20 words, '
    'what binds them"}.'
)


def build_prompt(members: list[Agent], settlement_name: str) -> str:
    names = ", ".join(a.name for a in members)
    personality_bits = []
    for agent in members[:4]:  # keep the prompt bounded on a large cluster
        traits = describe_traits(agent.traits)
        if traits:
            personality_bits.append(f"{agent.name} is {traits}")
    personality = f" {'; '.join(personality_bits)}." if personality_bits else ""
    place = f" in {settlement_name}" if settlement_name else ""
    return (
        f"These villagers{place} have grown into a tight faction: {names}."
        f"{personality} What is this faction called, and what binds them?"
    )


def fallback_faction(members: list[Agent]) -> dict:
    """Deterministic stand-in: named for whoever's been alive longest in
    the cluster — village factions often end up known by their most
    established member, an unglamorous but legible rule."""
    anchor = max(members, key=lambda a: a.age_ticks)
    return {
        "name": f"{anchor.name}'s circle",
        "framing": f"A group that has come to trust {anchor.name} and each other.",
    }


def parse_faction(result: dict, fallback: dict) -> tuple[str, str]:
    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        name = fallback["name"]
    framing = result.get("framing")
    if not isinstance(framing, str) or not framing.strip():
        framing = fallback["framing"]
    return name.strip()[:40], framing.strip()[:150]
