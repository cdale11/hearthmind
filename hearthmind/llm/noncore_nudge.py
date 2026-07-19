"""Occasional LLM nudges for non-core-cast agents (item 9, the user's
own framing: "not fully LLM authored but partially and occasionally").
Every other LLM-authored personal cognition (goals, beliefs, dialogue,
mind/voice) is deliberately scoped to `Population.core_agent_ids` to
keep call volume from scaling with population (v0.70.0's swap-after-
hours fix). Item 9 asks for a narrow exception: the rest of the town
should not be permanently LLM-silent — just far rarer than the core
cast, and never per-agent-scaled.

`SimulationEngine._maybe_schedule_noncore_nudge` picks exactly ONE
non-core agent, once a month, round-robin across settlements (the same
flat-regardless-of-population-size shape `_job_target` already gives
every other settlement job) — this is a single call a month for the
*entire world*, not per agent. A genuine LLM answer nudges one trait by
a small bounded amount and plants one short reflective memory; the
fallback is a real no-op (the agent's personality holds exactly as it
was) — an "occasional" nudge that never happens is correct, not a
failure, same discipline `memory_drift.py` established for its own
rare/gated call.

Widened per a live user request: "improve the intelligence of non-core
NPCs and they should take up jobs that help grow the town/village
economy, infrastructure etc. Occasional LLM nudging can be made to do
that." Every other non-core-agent decision stays deliberately
deterministic (the whole point of core-cast gating, v0.70.0) — this
job's own existing "occasional" shape is the one sanctioned channel,
now doing double duty: the same call may ALSO set a short `Agent.plan`
(reusing `llm/beliefs.py`'s `parse_plan`/`PLAN_GOAL_BIAS_KEYWORDS`
machinery bounded-episodic-planning already built, §7 v0.87.15) —
zero new mechanism, zero added call volume. A plan set here is what
actually makes the nudge "take" on a non-core agent's day-to-day
behavior: `cognition.fallback_goal` (the ONLY goal source a non-core
agent ever gets, every single day, fully deterministic) already reads
`plan_intent` and biases toward GATHER/FORAGE/SOCIALIZE by keyword —
so one grounded LLM sentence here can steer several real days of an
ordinary villager's deterministic behavior toward genuinely useful
work, not just a private trait wobble nobody else ever sees. The
prompt is grounded in real settlement need (current era's infra
shortfall) so a suggested plan is a real answer to a real gap, not
generic flavor text.
"""
from __future__ import annotations

from hearthmind.agents.agent import Agent, describe_traits

SYSTEM_PROMPT = (
    "You are quietly reflecting on one ordinary villager in a small simulated "
    "world — someone whose life mostly goes unnoticed. Given what little is "
    "known about them, decide whether anything in their recent life would "
    "genuinely, if slightly, reshape who they are — and if so, which single "
    "trait shifts and in which direction. Most of the time nothing rises to "
    "that level, and that is the correct answer. Keep any shift small. "
    "Separately, if the village genuinely needs something and this villager "
    "could plausibly help, they may quietly resolve to spend the next few "
    "days on it — real, useful work (gathering materials, helping build, "
    "tending crops, learning a trade), grounded in what's actually needed, "
    "never invented busywork. Most of the time they already have enough "
    "going on and this should be left blank. "
    'Respond with strict JSON only, no other text: {"shifts": true or false, '
    '"trait": "resilience", "sociability", or "ambition", "direction": '
    '"up" or "down", "reflection": "one short first-person sentence, under 20 '
    'words", "plan_intent": "" or a short first-person resolve under 15 words, '
    '"plan_horizon_days": 0 or an integer 1-7 if plan_intent is set}. If '
    "shifts is false, trait/direction/reflection may be empty."
)


def build_prompt(
    agent: Agent, occupation: str, recent_memories: list[str], settlement_need: str = "",
) -> str:
    """`settlement_need` (economy/infrastructure nudge, see module
    docstring): one plain-language sentence naming what the settlement's
    own real state (era-infrastructure shortfall, low materials) could
    use more of — grounds a suggested `plan_intent` in an actual gap
    rather than generic flavor text. Empty when nothing stands out."""
    personality = describe_traits(agent.traits)
    personality_text = f" You are {personality}." if personality else ""
    occupation_text = f" You work as a {occupation}." if occupation else ""
    memory_text = f" Recently: {' | '.join(recent_memories)}." if recent_memories else " Nothing notable has happened to you lately."
    need_text = f" The village could use more {settlement_need}." if settlement_need else ""
    return (
        f"You are {agent.name}, an ordinary villager.{occupation_text}{personality_text}"
        f"{memory_text}{need_text} Has anything changed in you? Is there something worth turning your hands to?"
    )


def fallback_nudge() -> dict:
    """Genuine no-op — see module docstring."""
    return {
        "shifts": False, "trait": "", "direction": "", "reflection": "",
        "plan_intent": "", "plan_horizon_days": 0,
    }


NUDGE_TRAIT_STEP = 0.12
"""Bounded shift magnitude — small next to the -1..1 trait range, same
"never dominant" shape as every other trait nudge in this project
(TRAIT_SUSTAINED_HUNGER_NUDGE, TRAIT_VIOLENCE_NUDGE, ...)."""

VALID_TRAITS = frozenset({"resilience", "sociability", "ambition"})


def parse_nudge(result: dict, fallback: dict) -> tuple[str, float, str] | None:
    """Returns `(trait, signed_delta, reflection)` or None if nothing
    shifts this attempt — the common, expected case."""
    shifts = result.get("shifts")
    if not isinstance(shifts, bool):
        shifts = fallback["shifts"]
    if not shifts:
        return None
    trait = result.get("trait")
    if not isinstance(trait, str) or trait.strip().lower() not in VALID_TRAITS:
        return None
    direction = result.get("direction")
    if direction not in ("up", "down"):
        return None
    reflection = result.get("reflection")
    if not isinstance(reflection, str) or not reflection.strip():
        return None
    delta = NUDGE_TRAIT_STEP if direction == "up" else -NUDGE_TRAIT_STEP
    return trait.strip().lower(), delta, reflection.strip()[:140]
