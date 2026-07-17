"""Per-agent goal-setting: prompt construction, response parsing, and the
deterministic fallback used when the LLM is disabled/unreachable.

Deliberately narrow in scope for this slice: the LLM chooses one of four
fixed goals (see AgentGoal) rather than free text, which keeps the output
structured, cheap to validate, and directly executable by the deterministic
movement logic in Population — "decision-first, not dialogue-first," per
the project roadmap. See docs/DECISIONS.md, B2.
"""
from __future__ import annotations

from hearthmind.agents.agent import (
    EMOTION_FEAR,
    EMOTION_GRIEF,
    EMOTION_NOTABLE_THRESHOLD,
    TRAIT_AMBITION,
    TRAIT_NOTABLE_THRESHOLD,
    TRAIT_SOCIABILITY,
    Agent,
    AgentGoal,
    describe_emotion,
    describe_traits,
    just_now_text as _just_now_text,
)

SYSTEM_PROMPT = (
    "You are the inner voice of a villager in a small simulated world. "
    "Given their current state, choose what they should focus on right now. "
    "'gather' means collecting wood and stone for the village's shared "
    "building supply. 'wander' means going about ordinary business near "
    "home — if you're told a building nearby needs repair, choosing "
    "'wander' is how you'd go lend a hand with it. When nothing urgent "
    "(hunger, exhaustion) forces the choice, let personality tilt it: an "
    "ambitious or driven villager leans toward 'gather' (visible, "
    "effortful work), a sociable one leans toward 'socialize' — and if a "
    "building needs repair, that alone is worth leaning toward 'wander' "
    "for, regardless of personality. Don't override real needs for any "
    "of this, just break ties toward it. "
    'Respond with strict JSON only, no other text: '
    '{"goal": "forage" | "rest" | "socialize" | "wander" | "gather", '
    '"reason": "a short first-person reason, under 15 words"}.'
)


RECENT_MEMORIES_IN_PROMPT = 3
"""How many of the agent's most recent memories reach the cognition
prompt. Was 1 (only `memories[-1]`) — the July 2026 architecture
review's finding was that an agent's whole inner life at decision time
was a single sentence; three keeps the prompt small for a 2B model
while letting e.g. a grief memory survive one newer rumor."""


def build_prompt(
    agent: Agent, season: str, weather: str,
    settlement_name: str = "", latest_tradition: str = "",
    colocated_names: list[str] | None = None, nearest_food_steps: int | None = None,
    beliefs_about: list[str] | None = None, own_belief: str = "",
    semantic_memory: str = "", mind_text: str = "", needs_repair: bool = False,
    life_digest: str = "",
) -> str:
    """`settlement_name`/`latest_tradition` are optional culture context
    (Phase E) — empty until the settlement is named/has a tradition, so
    early-game prompts are unaffected. Closes the "chronicle isn't read
    back into prompts" gap flagged since B3 — see docs/DECISIONS.md, E1.

    `colocated_names`/`nearest_food_steps` ground the choice in what the
    agent can actually act on this decision cycle — previously the LLM
    chose between forage/socialize/etc. without being told whether food
    was reachable or anyone was nearby, so its choice couldn't be better
    than a coin flip on exactly the facts that matter (July 2026
    architecture review, LLM-cognition pass).

    `agent.memories` contributes its most recent few entries as personal
    context — bonds formed, rumors heard, a partner's death — so an
    agent's own history can shape its next goal, not just the
    settlement's. See docs/DECISIONS.md, relationship-memory pass.

    `beliefs_about` (H2 extension, docs/ROADMAP.md "Phase H"): settlement
    theories that resolve to this agent or their family (see
    llm.beliefs.beliefs_about_agent) — dialogue prompts already got this
    context; cognition's own goal-setting previously didn't, despite
    "the village believes X is reckless" being exactly the kind of thing
    that should be able to shape X's own choices, not just what others
    say to them.

    `semantic_memory` (Phase J, v0.78.0): the freshest entry in `Agent.
    semantic_memories` — a condensed lasting self-theory distilled from
    several episodic memories at once ("I don't trust the river since
    the flood"), distinct from `own_belief`'s settlement-scale-shaped
    theory and from the raw `memory` line's individual events. Small,
    high prompt priority per the vision doc; shown as one short clause,
    never the whole capped list, to keep this prompt's token cost flat
    as the layer fills up.

    `mind_text` (Phase J permanent tier, v0.78.4): `Agent.mind`'s
    one-time-authored durable identity paragraph, core cast only. Unlike
    every other field here it never changes across an agent's life —
    "at your core" framing distinguishes it from `own_belief` (a
    revisable running theory) and `semantic_memory` (distilled from
    recent experience).

    `needs_repair` (root-cause fix for a live "NPCs aren't repairing
    buildings" report): whether the agent's home settlement currently
    has a STANDING building below `REPAIR_THRESHOLD` (see `Population.
    damaged_building_positions`). The deterministic side already biases
    WANDER-goal movement toward the nearest damaged building
    (`_dispatch_movement`'s WANDER branch, `work_positions`) — repair
    was only ever incidental with a live LLM in the loop because the
    model was never told repair was a thing 'wander' could mean, so it
    had no way to rationally choose it over forage/socialize/gather.
    This closes that information gap the same way `nearest_food_steps`
    already grounds 'forage'.

    `life_digest` (v0.86.7): `Agent.life_digest`, one LLM-authored
    sentence condensing this agent's ENTIRE accumulated self-
    understanding (their private beliefs and semantic memories taken
    together), not just the single freshest entry `own_belief`/
    `semantic_memory` already show — same "digest alongside specifics"
    shape `chronicle`/`town_brain` already use for `Settlement.
    belief_digest`, applied at the individual scale. Empty until the
    Reflect() job has run at least once for this agent."""
    culture = ""
    if settlement_name:
        culture = f" You live in {settlement_name}."
        if latest_tradition:
            culture += f" The village keeps this tradition: {latest_tradition}."
    recent = agent.memories[-RECENT_MEMORIES_IN_PROMPT:]
    memory = f" You remember: {' | '.join(recent)}" if recent else ""
    just_now = _just_now_text(agent.working_memory, recent)
    just_now_text = f" Just now: {just_now}." if just_now else ""
    personality = describe_traits(agent.traits)
    personality_text = f" You are {personality}." if personality else ""
    emotion = describe_emotion(agent.emotions)
    emotion_text = f" Right now you feel {emotion}." if emotion else ""
    beliefs_text = (
        f" What the village has come to believe about you: {'; '.join(beliefs_about)}."
        if beliefs_about else ""
    )
    own_belief_text = f" Your own private theory: {own_belief}" if own_belief else ""
    semantic_text = f" You've come to feel: {semantic_memory}" if semantic_memory else ""
    mind_prompt_text = f" At your core: {mind_text}" if mind_text else ""
    life_digest_text = f" Your outlook on your own life so far: {life_digest}" if life_digest else ""
    company = (
        f" With you right now: {', '.join(colocated_names)}."
        if colocated_names else " Nobody else is here right now."
    )
    if nearest_food_steps is None:
        food = " You know of no food source nearby."
    elif nearest_food_steps == 0:
        food = " There is food where you stand."
    else:
        food = f" The nearest food you know of is about {nearest_food_steps} steps away."
    repair_text = (
        " A building nearby has fallen into disrepair and could use a hand — 'wander' "
        "would take you there." if needs_repair else ""
    )
    return (
        f"You are {agent.name}. Hunger: {agent.hunger:.2f} (0=full, 1=starving). "
        f"Energy: {agent.energy:.2f} (0=exhausted, 1=fully rested). "
        f"Currently {agent.state.value}, focused on '{agent.goal.value}'."
        f"{company}{food} It is {season}, weather: {weather}.{culture}{memory}{just_now_text}"
        f"{personality_text}{emotion_text}{beliefs_text}{own_belief_text}{semantic_text}{mind_prompt_text}"
        f"{life_digest_text}{repair_text} "
        "What should you focus on right now?"
    )


def fallback_goal(
    hunger: float, energy: float, agent_id: int = 0, traits: dict | None = None,
    emotions: dict | None = None,
) -> dict:
    """Deterministic rule-based stand-in for the LLM's choice, used when
    Ollama is disabled, unreachable, or misbehaves. Mirrors the kind of
    reasoning the prompt asks for, just without an actual model behind it.

    Content agents (not hungry, not tired) split deterministically by
    `agent_id % 3` between SOCIALIZE, WANDER, and GATHER, rather than
    always wandering — without this, a fallback-only run (no live LLM)
    could never produce clustering (D2/D4) or a materials stockpile (D8),
    since only a live LLM could ever choose those goals otherwise.

    A standout `TRAIT_AMBITION` or `TRAIT_SOCIABILITY` (see agents/
    agent.py) overrides the `agent_id % 3` split toward GATHER/SOCIALIZE
    respectively — previously this fallback (which fires on every LLM
    miss: disabled, unreachable, backpressured) ignored personality
    entirely, so a content agent's "profession" was purely an id-based
    caste with zero connection to their trait vector, even though the
    live-LLM prompt already described that same personality in words.
    Neutral-personality agents (the common case) keep the exact old
    id%3 split unchanged. See docs/DECISIONS.md, "personality steers
    profession.\""""
    if hunger > 0.6:
        return {"goal": AgentGoal.FORAGE.value, "reason": "hungry"}
    if energy < 0.3:
        return {"goal": AgentGoal.REST.value, "reason": "tired"}
    emotions = emotions or {}
    fear = emotions.get(EMOTION_FEAR, 0.0)
    grief = emotions.get(EMOTION_GRIEF, 0.0)
    if fear >= EMOTION_NOTABLE_THRESHOLD and fear >= grief:
        # A frightened agent (recent predator attack, illness, or a
        # starvation scare) seeks the safety of rest rather than the
        # id%3/trait split below — Phase I's "emotions bias small
        # deterministic behavior" rule, applied to the fallback path so
        # it's real even with the LLM disabled/unreachable.
        return {"goal": AgentGoal.REST.value, "reason": "shaken, wants to feel safe"}
    if grief >= EMOTION_NOTABLE_THRESHOLD:
        # Grief withdraws rather than seeks company — overrides the
        # sociability standout below, same "real feeling beats routine
        # tie-break" precedence fear gets above.
        return {"goal": AgentGoal.WANDER.value, "reason": "grieving, wants to be alone"}
    traits = traits or {}
    ambition = traits.get(TRAIT_AMBITION, 0.0)
    sociability = traits.get(TRAIT_SOCIABILITY, 0.0)
    if ambition >= TRAIT_NOTABLE_THRESHOLD and ambition >= sociability:
        return {"goal": AgentGoal.GATHER.value, "reason": "content, driven to make something of themself"}
    if sociability >= TRAIT_NOTABLE_THRESHOLD and sociability > ambition:
        return {"goal": AgentGoal.SOCIALIZE.value, "reason": "content, seeking company"}
    branch = agent_id % 3
    if branch == 0:
        return {"goal": AgentGoal.SOCIALIZE.value, "reason": "content, seeking company"}
    if branch == 1:
        return {"goal": AgentGoal.GATHER.value, "reason": "content, gathering materials"}
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
