"""Per-agent goal-setting: prompt construction, response parsing, and the
deterministic fallback used when the LLM is disabled/unreachable.

Deliberately narrow in scope for this slice: the LLM chooses one of four
fixed goals (see AgentGoal) rather than free text, which keeps the output
structured, cheap to validate, and directly executable by the deterministic
movement logic in Population — "decision-first, not dialogue-first," per
the project roadmap. See docs/DECISIONS.md, B2.
"""
from __future__ import annotations

from hearthmind.agents.agent import Agent, AgentGoal

SYSTEM_PROMPT = (
    "You are the inner voice of a villager in a small simulated world. "
    "Given their current state, choose what they should focus on right now. "
    'Respond with strict JSON only, no other text: '
    '{"goal": "forage" | "rest" | "socialize" | "wander", "reason": "a short first-person reason, under 15 words"}.'
)


def build_prompt(agent: Agent, season: str, weather: str) -> str:
    return (
        f"You are {agent.name}. Hunger: {agent.hunger:.2f} (0=full, 1=starving). "
        f"Energy: {agent.energy:.2f} (0=exhausted, 1=fully rested). "
        f"Currently {agent.state.value}. It is {season}, weather: {weather}. "
        "What should you focus on right now?"
    )


def fallback_goal(hunger: float, energy: float, agent_id: int = 0) -> dict:
    """Deterministic rule-based stand-in for the LLM's choice, used when
    Ollama is disabled, unreachable, or misbehaves. Mirrors the kind of
    reasoning the prompt asks for, just without an actual model behind it.

    Content agents (not hungry, not tired) split deterministically by
    `agent_id` parity between SOCIALIZE and WANDER, rather than always
    wandering — without this, the fallback path could never produce
    clustering at all (SOCIALIZE was previously unreachable without a live
    LLM choosing it), which was a real contributor to the social-dispersion
    finding in docs/DECISIONS.md, D2/D4."""
    if hunger > 0.6:
        return {"goal": AgentGoal.FORAGE.value, "reason": "hungry"}
    if energy < 0.3:
        return {"goal": AgentGoal.REST.value, "reason": "tired"}
    if agent_id % 2 == 0:
        return {"goal": AgentGoal.SOCIALIZE.value, "reason": "content, seeking company"}
    return {"goal": AgentGoal.WANDER.value, "reason": "content"}


def parse_goal(result: dict) -> tuple[AgentGoal, str]:
    """Validate an LLM (or fallback) response into a safe (goal, reason)
    pair. Any malformed/unexpected content degrades to WANDER rather than
    raising — a bad LLM response should never crash a tick."""
    raw_goal = result.get("goal", AgentGoal.WANDER.value)
    try:
        goal = AgentGoal(raw_goal)
    except ValueError:
        goal = AgentGoal.WANDER
    reason = str(result.get("reason", ""))[:200]
    return goal, reason
