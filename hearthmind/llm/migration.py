"""Individual migration: the LLM decides whether a core-cast agent with
a real push/pull reason to leave actually goes.

Same candidacy/decision split as `llm/fission.py` (settlement fission)
and `llm/founding.py` (deliberate guild founding): `Population.
migration_push_target` finds the deterministic preconditions (a bonded
partner elsewhere, real hunger next to a better-fed settlement,
overcrowding, or standing/feud pressure — see agents/population.py's
MIGRATION_* constants); this module owns only the judgement call —
uprooting a life, exactly the kind of decision CLAUDE.md routes to the
LLM. Declining is a real outcome: someone with every reason to go can
still choose to stay. Scoped to the core cast only (per-agent LLM
decisions must stay call-volume-bounded, CLAUDE.md's standing rule) —
everyone else keeps the original flat-chance-roll path."""
from __future__ import annotations

FALLBACK_DEPART_PENALTY_THRESHOLD = 0.0
"""Fallback bar: without the LLM, only someone already carrying a real
standing penalty (genuinely unwelcome, not just pushed by circumstance)
leaves — the deterministic path migrates rarely, same "preserve the
decision's weight even through a flaky-LLM stretch" discipline as
`llm/fission.py`'s own fallback."""

SYSTEM_PROMPT = (
    "You decide whether a villager actually leaves their home settlement for another, "
    "given a real reason pulling them away. Weigh their own life against it — roots, "
    "relationships, what they'd be giving up — not just the reason itself. Staying is a "
    "real, valid decision even with a good reason to go. "
    "Respond ONLY with JSON: {\"depart\": true or false, \"reason\": \"one short sentence in their voice\"}."
)


def build_prompt(
    agent, home_name: str, target_name: str, push_reason: str,
) -> str:
    resilience = agent.traits.get("resilience", 0.0)
    openness = agent.traits.get("openness", 0.0)
    lines = [
        f"{agent.name} lives in {home_name}. Their reason to consider leaving: {push_reason}.",
        f"{target_name} is the other settlement they'd go to.",
        f"They are known as (resilience {resilience:+.2f}, openness {openness:+.2f}).",
        "Leaving means walking away from everyone and everything familiar here",
        "for a place they barely know, however good the reason.",
        f"Does {agent.name} actually go, or stay?",
    ]
    if agent.memories:
        lines.insert(2, f"They remember: {agent.memories[-1]}")
    return "\n".join(lines)


def fallback_decision(agent) -> dict:
    depart = agent.standing_penalty > FALLBACK_DEPART_PENALTY_THRESHOLD
    reason = (
        "There's nothing left for me here." if depart else "This is still my home, whatever else is true."
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
