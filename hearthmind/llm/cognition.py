"""Per-agent goal-setting: prompt construction, response parsing, and the
deterministic fallback used when the LLM is disabled/unreachable.

Deliberately narrow in scope for this slice: the LLM chooses one of four
fixed goals (see AgentGoal) rather than free text, which keeps the output
structured, cheap to validate, and directly executable by the deterministic
movement logic in Population — "decision-first, not dialogue-first," per
the project roadmap. See docs/DECISIONS.md, B2.

"Improve context utilization" pass (explicit user request): this prompt
already supplies rich per-agent context (memories, relationships,
beliefs, personality, goals, traditions, weather, ...), but a small
model's own default instinct is to key off the single loudest cue
(usually hunger) and ignore the rest, even when a real person would
weigh several things at once. `SYSTEM_PROMPT`/`build_prompt`'s closing
lines now explicitly ask for that synthesis — not longer output, richer
reasoning — with a worked example calibrating what "weighing two things
in one breath" sounds like versus a step-by-step listing (which is
explicitly forbidden, so the model doesn't just enumerate context
instead of reacting to only one piece of it). The `reason` word cap
rose modestly (15 -> 28) to give that synthesis room without inviting
a verbose report. See `SimulationEngine._schedule_due_cognition`'s
`context_snapshot` and `llm/review_diagnostics.py`'s `context_
influence` diagnostic — the measurable counterpart to this change,
scoring how many distinct supplied context threads a `reason` actually
shares vocabulary with.
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
    faded_memory_text,
    just_now_text as _just_now_text,
    retrieve_relevant_memories,
)

SYSTEM_PROMPT = (
    "You are the inner voice of a villager in a small simulated world. "
    "Given their current state, choose what they should focus on right now. "
    "'forage' means going after food specifically — the nearest crop, "
    "granary, herd, or wild plant — this is the one to pick whenever "
    "hunger is what's driving the choice, never 'gather'. 'gather' means "
    "collecting wood and stone for the village's shared building supply, "
    "not food. 'rest' means resting to recover energy. 'socialize' means "
    "seeking out whoever's nearby for company. 'wander' means going about "
    "home — if you're told a building nearby needs repair, choosing "
    "'wander' is how you'd go lend a hand with it. 'seek_person' means "
    "deliberately going to find one specific person for a specific "
    "reason (only offered when there genuinely is such a reason and "
    "someone to seek) — choose it only when that reason feels pressing "
    "enough to interrupt your ordinary business for. When nothing urgent "
    "(hunger, exhaustion) forces the choice, let personality tilt it: an "
    "ambitious or driven villager leans toward 'gather' (visible, "
    "effortful work), a sociable one leans toward 'socialize' — and if a "
    "building needs repair, that alone is worth leaning toward 'wander' "
    "for, regardless of personality. Don't override real needs for any "
    "of this, just break ties toward it. Sometimes survival already "
    "decides the priority for them (they're too hungry or too "
    "exhausted to weigh anything else) — when told this is the case, "
    "there is no real choice to make: give that same priority back as "
    "'goal' and spend your one real contribution on 'reason'.\n"
    "You're given a lot about this person: how they feel, what they "
    "remember, what they believe about themselves, what others believe "
    "about them, who they're with, their village's mood and customs, a "
    "plan they're partway through, a lesson they once learned. A real "
    "person doesn't think about only one of these at a time — they feel "
    "hungry AND remember a promise AND notice who's nearby, all at once, "
    "and one of those tips the balance. Let 'reason' show that: weigh at "
    "least one thing beyond the single most obvious need whenever the "
    "prompt actually gives you more than one thing to weigh — hunger "
    "against a commitment, a memory against the weather, personality "
    "against what the village expects of them. Don't force a connection "
    "that isn't there, and don't list your reasons like a report — say "
    "it the way the person would actually think it to themselves, in "
    "one breath, never as numbered or step-by-step reasoning. Anything "
    "written in parentheses, like '(a hazy memory)', is a note about "
    "how clearly they remember something, not something they'd think "
    "in those exact words — never quote it, just let it color how sure "
    "they sound. "
    'Respond with strict JSON only, no other text: '
    '{"goal": "forage" | "rest" | "socialize" | "wander" | "gather" | "seek_person", '
    '"reason": "a short first-person reason, under 28 words, blending at '
    'least two things they\'re weighing when more than one applies"}.'
)


SURVIVAL_HUNGER_THRESHOLD = 0.6
SURVIVAL_ENERGY_THRESHOLD = 0.3
"""v0.87.15, explicit user direction: "remove objective survival
decisions from the LLM... ask something like: 'your current priority
is obtaining food, explain how you decide to pursue it' when a certain
threshold has passed." Past either threshold, `build_prompt` no longer
poses goal-setting as an open question — the physical need has already
decided it (same deterministic-reality/LLM-meaning split the critical-
hunger movement override already enforces at the movement layer, see
CLAUDE.md's tick-loop rule) — the LLM's one real contribution becomes
the in-character "reason," not the choice itself. Matches `fallback_
goal`'s own long-standing hardcoded 0.6/0.3 checks (now sourced from
these same constants instead of separate magic numbers) so the live-
LLM and deterministic paths agree on where "survival forces it" begins."""


FORCED_HUNGER_REASON_POOL = (
    "hungry",
    "stomach gnawing, hunting for anything to eat",
    "belly aching, casting around for a meal",
    "hunger pressing hard, can't think past it",
    "gut twisting with hunger, needs food now",
)
FORCED_ENERGY_REASON_POOL = (
    "tired",
    "legs heavy, desperate for rest",
    "worn thin, needs to lie down",
    "exhausted, can barely keep moving",
    "running on nothing, has to stop and rest",
)
"""docs/AUDIT-2026-07-20.md, P1.3 (explicit user direction to
implement it, overriding the earlier v1.3.7 flag): once hunger/energy
cross `SURVIVAL_HUNGER_THRESHOLD`/`SURVIVAL_ENERGY_THRESHOLD`, the goal
was never a real choice — `build_prompt`'s own closing text says so —
so `SimulationEngine._schedule_due_cognition` now skips the LLM call
entirely in this state (see its `forced` gate) rather than spending a
full call for reason-only flavor text. These pools stand in for that
flavor text, picked by `agent_id % len(pool)` for a little per-agent
variety without an RNG dependency — plain "hungry"/"tired" stays the
first entry so an existing save's fallback text doesn't shift for
agent_id % len == 0."""


RECENT_MEMORIES_IN_PROMPT = 3
"""How many memories reach the cognition prompt — the prompt-slot
BUDGET, unchanged since the July 2026 architecture review (a 2B model
needs the prompt small; three lets e.g. a grief memory survive one
newer rumor). v0.87.14 (docs/IDEAS-2026-07-EMERGENCE.md §7 "Adaptive
retrieval layer") changed WHICH three: `retrieve_relevant_memories`
scores every stored memory by recency, salience, keyword-overlap
relevance to what just happened, and a causal-link bonus, rather than
always taking the blind `memories[-3:]` slice — so a ten-year-old
high-salience memory can now outrank a mundane one from yesterday when
it's actually the relevant one, with prompt size still bounded exactly
as before."""


def build_prompt(
    agent: Agent, season: str, weather: str,
    settlement_name: str = "", latest_tradition: str = "",
    colocated_names: list[str] | None = None, nearest_food_steps: int | None = None,
    beliefs_about: list[str] | None = None, own_belief: str = "",
    semantic_memory: str = "", mind_text: str = "", needs_repair: bool = False,
    materials_critical: bool = False,
    life_digest: str = "", lesson: str = "", seek_candidate: tuple[str, str] | None = None,
    institution_objective: str = "", plan: dict | None = None, core_memory: str = "",
    prophecy: dict | None = None, long_term_goal: dict | None = None,
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

    `materials_critical` (live audit finding, P0.3): whether the
    settlement's stockpile currently sits below `buildings.cheapest_
    founding_cost()` — the point where NOTHING can be founded, not even
    a single hut, while repairs/tools/workshop crafting keep drawing
    from the same stockpile. Same information-gap shape as `needs_
    repair`: 'gather' was already an available choice, but nothing told
    the model the village's building economy was genuinely stalled, so
    it had no more reason to favor gather here than on any ordinary day.

    `life_digest` (v0.86.7): `Agent.life_digest`, one LLM-authored
    sentence condensing this agent's ENTIRE accumulated self-
    understanding (their private beliefs and semantic memories taken
    together), not just the single freshest entry `own_belief`/
    `semantic_memory` already show — same "digest alongside specifics"
    shape `chronicle`/`town_brain` already use for `Settlement.
    belief_digest`, applied at the individual scale. Empty until the
    Reflect() job has run at least once for this agent. v0.87.35
    context-selection audit: since a real `life_digest` already
    synthesizes `own_belief`/`semantic_memory`, `build_prompt` shows
    only the digest once one exists and drops the two specific fields
    it was built from — showing all three together was redundant
    "loosely related" texture, not three genuinely distinct facts.

    `lesson` (v0.87.0, "learns like a human" — see `Agent.lessons`):
    the one stored lesson, if any, whose `situation` tag matches the
    agent's CURRENT situation (computed deterministically at the call
    site, `SimulationEngine._current_situation_tag`) — "smarter recall,
    not just storage": this surfaces the most RELEVANT past takeaway
    for right now, which may be older than every other memory/belief
    already in this prompt, rather than only ever reading the newest
    entries regardless of relevance.

    `seek_candidate` (v0.87.8, "directed intent" — docs/IDEAS-2026-07-
    EMERGENCE.md §1): `(target_name, reason_text)`, computed
    deterministically at the call site (`Population.
    _seek_person_candidate`) from the agent's own trust/secrets/
    emotions state — `None` most of the time (most agents most days
    have no one specific to seek out). Only offered as a grounding
    sentence when non-`None`; the model is never asked to invent a
    target or a reason, only to decide whether the one real, existing
    reason is worth interrupting ordinary business for.

    `institution_objective` (v0.87.12, "institution objectives" —
    docs/IDEAS-2026-07-EMERGENCE.md §7): the agent's own FAMILY/GUILD/
    COUNCIL's slow-revised ambition (`Institution.objective`), if any —
    "" most of the time (an institution's objective starts blank and
    only forms once the monthly institution-belief job supplies one).
    A real group ambition genuinely shaping a member's own choices.

    `plan` (v0.87.15, "bounded episodic planning" — docs/IDEAS-2026-07-
    EMERGENCE.md §7): `Agent.plan`, if any — a multi-day intent formed
    by Reflect() that outlives any single day's goal reevaluation
    ("stockpiling before winter," "earning a council seat"). `None`
    most of the time (most agents most days have no active plan).

    `core_memory` (v0.87.16, "deepen long-term historical identity" —
    explicit user direction): the single most relevant entry from
    `Agent.core_memories`, if any — a genuinely major memory (a flood,
    a death, a settlement split) that graduated out of the ordinary
    8-slot recency window months or years ago, computed at the call
    site. "" most of the time (an agent with no core memories yet, or
    none relevant right now).

    `prophecy` (§3 "self-fulfilling prophecy", docs/IDEAS-2026-07-
    EMERGENCE.md): `Settlement.prophecy` while `status == "pending"`,
    if any — a vague forward-looking line the village half-remembers.
    An ominous one nudges toward stockpiling/caution phrasing, a
    hopeful one toward building/ambition phrasing; nothing here forces
    a specific goal, it's colored suggestion only, same "texture, never
    a required thread" treatment every other optional grounding line in
    this prompt gets. `None` most of the time — a live prophecy is
    meant to be rare."""
    culture = ""
    if settlement_name:
        culture = f" You live in {settlement_name}."
        if latest_tradition:
            culture += f" The village keeps this tradition: {latest_tradition}."
    # v0.87.14 adaptive retrieval: scored, not just the newest slice —
    # see RECENT_MEMORIES_IN_PROMPT's docstring. `context` is what just
    # happened (working_memory's freshest entry), the same signal
    # `_just_now_text` below reads for its own duplicate check.
    retrieval_context = agent.working_memory[-1] if agent.working_memory else ""
    retrieved = retrieve_relevant_memories(agent, RECENT_MEMORIES_IN_PROMPT, context=retrieval_context)
    recent = [t for t, _, _ in retrieved]
    # Deferred item 4 (docs/VISION-2026-07-LEARNING.md): a decayed
    # memory reads hazier here, not just in raw storage — see
    # Population.decay_memory_salience/faded_memory_text. `recent`
    # itself stays the exact stored text for `_just_now_text`'s
    # duplicate-detection below.
    recent_display = [
        faded_memory_text(t, s) + (f" (because {c})" if c else "")
        for t, s, c in retrieved
    ]
    memory = f" You remember: {' | '.join(recent_display)}" if recent_display else ""
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
    # `life_digest` is itself authored FROM `own_belief` + `semantic_
    # memory` taken together (see its docstring: "condensing this
    # agent's ENTIRE accumulated self-understanding... not just the
    # single freshest entry"). Showing all three at once is exactly the
    # "long list of loosely related facts" item 3 (docs/DECISIONS.md,
    # v0.87.35 context-selection audit) warns against — two of them are
    # redundant with the third. Prefer the synthesis once Reflect() has
    # produced one; fall back to the two specific pieces only while
    # `life_digest` is still empty (this agent hasn't been reflected on
    # yet, or isn't core cast).
    if life_digest:
        life_digest_text = f" Your outlook on your own life so far: {life_digest}"
        own_belief_text = ""
        semantic_text = ""
    else:
        life_digest_text = ""
        own_belief_text = f" Your own private theory: {own_belief}" if own_belief else ""
        semantic_text = f" You've come to feel: {semantic_memory}" if semantic_memory else ""
    mind_prompt_text = f" At your core: {mind_text}" if mind_text else ""
    lesson_text = f" Something you've learned: {lesson}" if lesson else ""
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
    materials_text = (
        " The village's stockpile of building materials has run dry — nothing new can be "
        "built until someone gathers more." if materials_critical else ""
    )
    seek_text = (
        f" You could go find {seek_candidate[0]} — {seek_candidate[1]}; 'seek_person' would take you to them."
        if seek_candidate else ""
    )
    objective_text = f" Your household/guild/council wants: {institution_objective}." if institution_objective else ""
    plan_text = (
        f" Your plan: {plan['intent']} ({plan.get('days_remaining', 0)} days left)."
        if plan else ""
    )
    # Phase 1.B "self-evolving world" (docs/VISION-2026-07-21-
    # SELFEVOLVING.md): the standing WHY behind `plan`'s near-term
    # step — shown alongside it, never instead of it, so a day's goal
    # choice can read as serving something larger without pretending
    # the ambition itself is today's decision.
    long_term_goal_text = f" Your deeper aim: {long_term_goal['goal']}." if long_term_goal else ""
    core_memory_text = f" You still remember well: {core_memory}" if core_memory else ""
    prophecy_text = ""
    if prophecy is not None:
        lean = "unsettled" if prophecy["tone"] == "ominous" else "hopeful"
        prophecy_text = (
            f" There's a {lean} half-remembered saying going around: \"{prophecy['text']}\" "
            "— it may be worth heeding, or it may be nothing."
        )
    # v0.87.15, explicit user direction: past a real survival threshold,
    # the goal isn't a genuine choice — don't pose it as an open
    # question (see SURVIVAL_HUNGER_THRESHOLD/SURVIVAL_ENERGY_THRESHOLD's
    # docstring). The LLM's contribution narrows to the "reason" alone.
    if agent.hunger > SURVIVAL_HUNGER_THRESHOLD:
        closing = (
            " Your current priority is obtaining food — there's no real choice about it. "
            "Explain briefly, in character, how you go about it — let it carry a trace of "
            "what else is on your mind right now, if anything genuinely is."
        )
    elif agent.energy < SURVIVAL_ENERGY_THRESHOLD:
        closing = (
            " Your current priority is resting — there's no real choice about it. "
            "Explain briefly, in character, how you go about it — let it carry a trace of "
            "what else is on your mind right now, if anything genuinely is."
        )
    else:
        closing = " What should you focus on right now — and what's actually weighing on you as you decide?"
    return (
        f"You are {agent.name}. Hunger: {agent.hunger:.2f} (0=full, 1=starving). "
        f"Energy: {agent.energy:.2f} (0=exhausted, 1=fully rested). "
        f"Currently {agent.state.value}, focused on '{agent.goal.value}'."
        f"{company}{food} It is {season}, weather: {weather}.{culture}{memory}{just_now_text}"
        f"{personality_text}{emotion_text}{beliefs_text}{own_belief_text}{semantic_text}{mind_prompt_text}"
        f"{life_digest_text}{lesson_text}{repair_text}{materials_text}{seek_text}{objective_text}{plan_text}"
        f"{long_term_goal_text}{core_memory_text}{prophecy_text}{closing}"
    )


PLAN_GOAL_BIAS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "forage": ("stockpil", "food", "winter", "harvest", "hungry", "hunger"),
    "gather": ("council", "guild", "seat", "lead", "skill", "master", "craft", "build", "materials", "prove"),
    "socialize": ("peace", "friend", "reconcile", "trust", "bond", "marry", "court"),
}
"""v0.87.15, "bounded episodic planning" (docs/IDEAS-2026-07-
EMERGENCE.md §7): a small keyword-overlap bias so `Agent.plan` shapes
the DETERMINISTIC fallback goal too, not just the live-LLM prompt —
same "real, if crude" discipline `fallback_goal`'s trait-standout bias
already applies. Checked in this fixed order (forage/gather/socialize)
so an ambiguous intent resolves consistently rather than by dict
iteration order; deliberately never overrides hunger/energy/fear/grief
above, which is why this constant is only consulted after those."""


def fallback_goal(
    hunger: float, energy: float, agent_id: int = 0, traits: dict | None = None,
    emotions: dict | None = None, plan_intent: str = "", materials_critical: bool = False,
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
    if hunger > SURVIVAL_HUNGER_THRESHOLD:
        reason = FORCED_HUNGER_REASON_POOL[agent_id % len(FORCED_HUNGER_REASON_POOL)]
        return {"goal": AgentGoal.FORAGE.value, "reason": reason}
    if energy < SURVIVAL_ENERGY_THRESHOLD:
        reason = FORCED_ENERGY_REASON_POOL[agent_id % len(FORCED_ENERGY_REASON_POOL)]
        return {"goal": AgentGoal.REST.value, "reason": reason}
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
    if materials_critical:
        # Live audit finding (P0.3): the majority of GATHER decisions
        # come from this fallback (only core-cast agents ever get a
        # live-LLM cognition call), so the `agent_id % 3`/trait-standout
        # split below gave a critically-materials-starved settlement no
        # more GATHER pressure than an ordinary well-stocked day —
        # sinks (repairs/tools/crafting) kept outpacing this trickle.
        # Overrides plan_intent/trait/id-split the same way fear/grief
        # above override them — a genuine settlement-wide need, not a
        # routine tie-break.
        return {"goal": AgentGoal.GATHER.value, "reason": "the village badly needs materials"}
    if plan_intent:
        lowered = plan_intent.lower()
        for goal_name, keywords in PLAN_GOAL_BIAS_KEYWORDS.items():
            if any(kw in lowered for kw in keywords):
                return {"goal": AgentGoal(goal_name).value, "reason": f"working toward: {plan_intent}"}
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
    reason = str(result.get("reason", ""))[:260]
    return goal, reason
