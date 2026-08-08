"""Ambient NPC-to-NPC dialogue: colocated agents periodically exchange a
short LLM-authored line each. The exchange nudges their relationship
(warmer, tenser, or unchanged) and may seed a rumor, which is logged as a
normal event and so gets read back into the chronicle/culture prompts
like anything else that happens in the world. This is the concrete
mechanism behind "NPCs talk to and influence each other" — see
docs/DECISIONS.md, E2.
"""
from __future__ import annotations

import random
import re

from hearthmind.agents.agent import (
    RIVALRY_THRESHOLD,
    Agent,
    describe_emotion,
    describe_traits,
    faded_memory_text,
    just_now_text as _just_now_text,
    normalize_voice_phrase,
)
from hearthmind.agents.occupations import OCCUPATION_DIALOGUE_REGISTER
from hearthmind.util import clamp

SYSTEM_PROMPT = (
    "You are writing a brief, natural exchange between two villagers who "
    "just crossed paths in a simulated world. Ground it in the specific "
    "facts you're given (their hunger/energy, what each is currently "
    "doing and WHY if a reason is given, their relationship, and "
    "especially anything listed as something one of them recently "
    "remembers or believes) — prefer talking about that over generic "
    "small talk. Real village conversation is mostly about people and "
    "life, not the sky: family, a guild or trade, an ambition, a birth "
    "or death, a debt or trade, a coming festival, an animal, a building "
    "going up, or something one of them is working toward. Weather is "
    "only worth mentioning when it's actually notable (you'll be told "
    "when it is) — never bring it up as generic filler on an ordinary "
    "day. If the village has local terms of its own listed below, feel "
    "free to use one where it naturally fits — never forced. Anything "
    "written in parentheses, like '(a hazy memory)', is a narrator's "
    "note about how clearly the villager remembers something — never "
    "quote it or a phrase like it out loud, just let it color HOW "
    "confidently they say the thing itself. Never invent unrelated "
    "topics, and never mention that "
    "this is a game, a simulation, or that you are an AI. Write like two "
    "real people, not a script: it is fine for a line to be a half-"
    "finished thought, a single word, a grunt of agreement, or a joke, "
    "and the two villagers don't have to fully agree with each other — "
    "someone can deflect, tease, disagree, or answer a different "
    "question than the one asked, the way real conversations drift. "
    "Treat this as one real, connected back-and-forth, not two separate "
    "statements: line_b must be a genuine reaction to line_a — an actual "
    "answer, a rebuttal, a joke back, a change of subject that still "
    "acknowledges what was said — never a line that could just as well "
    "have opened the conversation. Specifically: line_b should respond to "
    "the actual thing line_a just said, not swap in a different memory, "
    "rumor, or topic from the speaker's own background that has nothing "
    "to do with it — if unsure what to say, a short direct reaction to "
    "line_a's words beats an unrelated aside. If a speaker is noted as privately "
    "holding something back about the other, that tension may surface as "
    "a deflection, a pointed silence, or a half-said thing — never have "
    "them simply state the secret outright, that defeats the point of it "
    "being one. Optionally the exchange plants a "
    "short rumor that might spread through the village — leave it blank "
    "most of the time. This is a real conversation between two people "
    "with their own wants, not just talk for its own sake — when you're "
    "given each speaker's own objective for this exchange (grounded in "
    "what they want, what they owe, or a grievance between them), let it "
    "actually shape the exchange rather than being decoration; the two "
    "objectives may conflict, and it's fine for the exchange to leave "
    "that tension unresolved rather than reaching tidy agreement. Most "
    "exchanges are still just talk and change nothing beyond the mood — "
    "only mark a promise/debt/secret/misunderstanding/goal_change when "
    "something in THIS exchange genuinely caused it, never as a matter "
    "of course. Output ONLY the JSON object below, nothing before "
    "or after it, no explanation.\n"
    "Examples of the exact shape expected:\n"
    '{"line_a": "You look worn out, friend.", "line_b": "Long day in the '
    'fields.", "sentiment": "warm", "rumor": "", "topic": "work"}\n'
    '{"line_a": "Still nothing to say to me?", "line_b": "Not today.", '
    '"sentiment": "tense", "rumor": "", "topic": "silence"}\n'
    '{"line_a": "How\'s the little one settling in?", "line_b": "Barely '
    'sleeps, honestly.", "sentiment": "warm", "rumor": "", "topic": '
    '"the new baby"}\n'
    '{"line_a": "You still sore about the fence?", "line_b": "Wasn\'t '
    'talking about the fence.", "sentiment": "tense", "rumor": "", '
    '"topic": "the fence"}\n'
    '{"line_a": "Hungry work today.", "line_b": "Isn\'t it always with '
    'you.", "sentiment": "warm", "rumor": "", "topic": "hunger"}\n'
    '{"line_a": "I still owe you for the seed grain.", "line_b": '
    '"I\'ll bring the rest by market day, I swear it.", "sentiment": '
    '"neutral", "rumor": "", "topic": "debt", "promise": "bring the '
    'rest of what is owed by market day"}\n'
    'Now respond with strict JSON only, in that exact shape: {"line_a": '
    '"under 14 words, said by the first villager", "line_b": "under 14 '
    'words, said by the second", "sentiment": "warm" | "tense" | '
    '"neutral", "rumor": "" or a short rumor under 15 words, "topic": '
    '"1-3 words naming what this exchange was actually about", '
    '"promise": "" or a short concrete promise under 15 words made by '
    'either speaker, "debt_delta": 0 or a small number (positive if '
    'the first speaker now owes the second, negative the other way — '
    'only for a real exchange of goods/favor/coin just now), '
    '"secret_revealed": true only if a speaker just let slip something '
    'they were privately holding back, otherwise false, '
    '"misunderstanding": true only if the exchange genuinely left one '
    'or both speakers with a wrong idea, otherwise false, "goal_change": '
    'true only if this exchange plausibly shifted a speaker\'s deeper '
    'ambition, otherwise false}.'
)


OPPORTUNITY_MAX_PICKS = 2
"""Live request ("diversify conversation opportunities... prevent
conversations from repeatedly revolving around dominant village-wide
narratives... give greater weight to each NPC's immediate
circumstances"): the prompt used to unconditionally concatenate EVERY
available steering line (this pair's own topic history, the whole
village's top topic, named places, a grounded recent event) every
single call. That's not "diverse," it's "maximal" — and it actively
reinforces whatever settlement-wide topic is already dominant, since
`Settlement.top_topics()` naming it as "what the village has been
talking about" is itself an invitation to talk about it more, which
then keeps it dominant (the mechanism designed for the OPPOSITE effect
in v0.87.31 backfired without an actual selection step). This constant
caps how many of the candidate "opportunities" below actually reach
the prompt each call — usually 1, sometimes 2 (see `_select_
opportunities`), weighted-random rather than exhaustive."""

_OPPORTUNITY_SECOND_PICK_CHANCE = 0.4
"""Chance `select_opportunities` takes a second candidate on top of
its first — most exchanges read as more natural steered toward ONE
concrete thing, not a checklist of everything available."""


def select_opportunities(
    candidates: list[tuple[str, float, str]], rng: "random.Random",
) -> list[tuple[str, str]]:
    """Weighted-random selection WITHOUT replacement, up to
    `OPPORTUNITY_MAX_PICKS`. `candidates` is `(category, weight, text)`
    — weight is relative likelihood, not a hard priority order, so a
    low-weight category (the settlement-wide topic) can still surface
    sometimes, just less often than a personal one. Returns `(category,
    text)` pairs in the order picked. Public (not `_`-prefixed): the
    engine calls this directly, once, so it can log which categories
    were actually chosen (`structured_input["opportunities"]`, feeds
    the review-pack diagnostics' context/topic-diversity report) without
    re-deriving the selection a second time or double-consuming the
    RNG."""
    pool = list(candidates)
    picks: list[tuple[str, str]] = []
    while pool and len(picks) < OPPORTUNITY_MAX_PICKS:
        if picks and rng.random() >= _OPPORTUNITY_SECOND_PICK_CHANCE:
            break
        weights = [w for _, w, _ in pool]
        idx = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        category, _weight, text = pool.pop(idx)
        picks.append((category, text))
    return picks


def build_opportunity_candidates(
    agent_a: Agent, agent_b: Agent, is_family: bool, recent_topics: list[str] | None,
    settlement_topics: list[str] | None, place_names: list[str] | None, grounded_event: str,
    weather_notable: bool, weather: str,
) -> list[tuple[str, float, str]]:
    """§9 follow-up, "diversify conversation opportunities" (explicit
    live request): candidate steering lines this specific exchange could
    draw on, each tagged with a relative weight. Personal-scope signals
    (this pair's own history, either speaker's own near-term plan,
    family) weigh more than village-scope ones (a named place, a
    grounded event) which in turn weigh more than the settlement-wide
    dominant topic — deliberately the LOWEST weight and reframed as
    "common knowledge, no need to repeat" rather than an invitation, so
    it can still surface sometimes without becoming the thing every
    exchange gravitates toward. See `select_opportunities`/
    `OPPORTUNITY_MAX_PICKS`."""
    candidates: list[tuple[str, float, str]] = []
    if recent_topics:
        candidates.append((
            "pair_history", 3.0,
            f"You two have lately talked about: {', '.join(recent_topics)} — find something new or go deeper.",
        ))
    if is_family:
        candidates.append((
            "family", 2.5,
            "They are family — a sibling, a parent, a child, a chore at home, are natural things to bring up.",
        ))
    for agent, label in ((agent_a, agent_a.name), (agent_b, agent_b.name)):
        plan = agent.plan
        if plan and plan.get("intent"):
            candidates.append((
                "future_plan", 2.5, f"{label} has quietly resolved to: {plan['intent']}.",
            ))
    if grounded_event:
        candidates.append((
            "village_event", 1.8, f"Something that actually happened recently: {grounded_event}.",
        ))
    if place_names:
        candidates.append((
            "place", 1.5,
            f"The village knows this place by name: {', '.join(place_names[-2:])}.",
        ))
    if weather_notable:
        candidates.append((
            "weather", 1.3, f"It's currently {weather} — worth mentioning if it fits.",
        ))
    if settlement_topics:
        candidates.append((
            "settlement_topic", 0.8,
            f"Lately the whole village has been talking about: {', '.join(settlement_topics)} — "
            "common knowledge, no need to bring it up yourself unless it genuinely fits.",
        ))
    return candidates


DIALOGUE_MEMORY_IN_PROMPT = 2
"""How many of each speaker's most recent memories reach the dialogue
prompt. Raised 1 -> 2 in the v0.72.3 GPU-offload pass: 1 was deliberately
tight against the CPU-only-Ollama token budget (see `Config.llm_num_ctx`'s
docstring for the hardware context that no longer applies the same way);
with real headroom back, two recent memories per speaker gives the model
an actual choice of what to bring up instead of always the single most
recent thing, without yet approaching cognition's 3 (a conversational
line still only has room to land one or two concrete things per speaker,
even with a bigger context budget — this is a content judgment, not just
a token-budget one). Previously 0: dialogue was the one LLM-authored
prompt in the project that never read from `agent.memories` at all,
despite cognition (goal-setting) already doing so — a colocated pair had
no way to talk about anything that actually happened to either of them
(a death, a bond, a rumor heard), only their current stats/weather/
relationship, which reads as generic small talk regardless of model
quality. See docs/DECISIONS.md, "dialogue grounding
fix.\""""


def build_prompt(
    agent_a: Agent, agent_b: Agent, affinity: float, settlement_name: str,
    latest_tradition: str, season: str, weather: str, beliefs_about: list[str] | None = None,
    other_settlement_name: str = "", cross_settlement_relation: float | None = None,
    lessons: tuple[str, str] = ("", ""), recent_topics: list[str] | None = None,
    weather_notable: bool = False, lexicon: list[dict] | None = None,
    settlement_topics: list[str] | None = None, place_names: list[str] | None = None,
    grounded_event: str = "", opportunity_rng: "random.Random | None" = None,
    opportunities: list[tuple[str, str]] | None = None,
    objectives: tuple[str, str] = ("", ""), open_thread: str = "",
) -> str:
    """`objectives`/`open_thread` (Phase 2, "dialogue as a simulation
    event", docs/VISION-2026-07-21-SELFEVOLVING.md): `objectives` is
    `(agent_a's want for THIS exchange, agent_b's)`, computed at the
    call site from the ledger (Phase 0 — an open debt/grievance/promise
    toward the other speaker) and `Agent.long_term_goal` (Phase 1.B) —
    "" when neither yields anything concrete, which is most exchanges.
    `open_thread` is one still-open promise between this exact pair
    (`Ledger.open_promises`), offered as something either speaker might
    follow up on — empty when there is none. Both are optional grounding,
    never a requirement that the exchange resolve anything.

    `lessons` (v0.87.0): `(agent_a's matching lesson, agent_b's
    matching lesson)`, each "" when no stored lesson matches that
    speaker's current situation — computed at the call site via
    `SimulationEngine._current_situation_tag`/`_matching_lesson`, the
    same helpers `cognition.build_prompt` already uses.

    `recent_topics` (v0.87.12, "dialogue novelty memory" — docs/IDEAS-
    2026-07-EMERGENCE.md §7): this pair's small stored ring of topics
    their last few LLM-authored exchanges actually covered
    (`Population.recent_dialogue_topics`) — empty most of the time (a
    pair's first exchange, or one whose past exchanges never supplied a
    parseable topic). Only offered as a steering line when non-empty;
    never fabricated.

    `weather_notable` (v0.87.16, "reduce conversational convergence" —
    explicit user direction): `weather` is only actually STATED in the
    prompt when this is true (a real storm/heavy rain/snow, computed at
    the call site from `WeatherState.sky()`/`wind_label()`) — an
    ordinary clear/partly-cloudy/overcast day contributes nothing here
    at all, closing the gap where weather was previously named as an
    unconditional grounding fact in literally every exchange regardless
    of whether anything about it was actually noteworthy.

    `settlement_topics` (§9 "diversify cultural topics" + "competing
    narratives", docs/IDEAS-2026-07-EMERGENCE.md): the whole village's
    most-talked-about subjects right now (`Settlement.top_topics()`),
    distinct from `recent_topics` above (this PAIR's own small history)
    — offered as one more optional steering line naming what's
    currently a live storyline in the village at large, never a
    requirement to follow it.

    `place_names` (§9 "geography as culture"): a couple of the
    settlement's own named landmarks (`Settlement.place_names`), so a
    villager can occasionally ground small talk in an actual place
    ("out past the {landmark}") instead of only abstract subjects.

    `grounded_event` (§9 "conversation grounded in simulation events"):
    one short, recent, non-routine thing that genuinely happened in the
    settlement (a filtered `recent_events_diverse` slice, same source
    `town_brain`/`chronicle` already read), offered as something either
    speaker might plausibly bring up — empty most of the time when
    nothing notable happened lately.

    `opportunity_rng`/`opportunities` ("diversify conversation
    opportunities", explicit live request): `recent_topics`/
    `settlement_topics`/`place_names`/`grounded_event`/notable-weather
    no longer ALL reach the prompt together every call —
    `build_opportunity_candidates`/`select_opportunities` weigh each one
    (personal signals over village-wide ones, the dominant settlement
    topic weighted lowest of all so naming it doesn't keep reinforcing
    it) and pick 1-2 per exchange. Pass a pre-computed `opportunities`
    list (the engine's own call site does this, so it can log which
    categories were chosen without re-deriving them) to skip the
    internal selection entirely; otherwise `opportunity_rng` (a seeded
    `random.Random` for reproducible tests, defaulting to a fresh one —
    this project's determinism-not-required convention) drives a fresh
    selection here."""
    is_parent_child = (
        (agent_a.parents is not None and agent_b.id in agent_a.parents)
        or (agent_b.parents is not None and agent_a.id in agent_b.parents)
    )
    if is_parent_child:
        # Family ties override the affinity-band read — a parent and
        # child talk like family even on a tick their numeric affinity
        # happens to read distant, and a fresh LLM prompt should know
        # this is not two strangers. See docs/DECISIONS.md,
        # family-memory pass.
        tie = "parent and child"
    elif affinity >= 0.6:
        tie = "close friends"
    elif affinity <= RIVALRY_THRESHOLD:
        tie = "at odds with each other"
    elif affinity <= 0.0:
        tie = "strangers, or barely acquainted"
    else:
        tie = "friendly acquaintances"
    culture = f" They live in {settlement_name}." if settlement_name else ""
    if settlement_name and latest_tradition:
        culture += f" The village keeps this tradition: {latest_tradition}."
    # §2 "dialect drift": a settlement's own coined terms, offered as a
    # light steering line — feel free to use them, never a requirement.
    if lexicon:
        terms = ", ".join(f"\"{e['term']}\" ({e['meaning']})" for e in lexicon[-3:])
        culture += f" Locally, people sometimes say: {terms}."
    if other_settlement_name and other_settlement_name != settlement_name:
        # Cross-settlement relationships (v0.67.0): a colocated pair from
        # two different named settlements — rare, since each settlement's
        # own population mostly stays near its own home, but the shared
        # physical map means it can happen. `cross_settlement_relation`
        # is that settlement pair's own recorded affinity (Settlement.
        # relations, seeded at fission, nudged by exactly this kind of
        # encounter) — colors the exchange the same way personal
        # affinity colors `tie`, one level up. See docs/DECISIONS.md.
        culture += f" {agent_b.name} is from {other_settlement_name}, not {settlement_name}."
        if cross_settlement_relation is not None:
            if cross_settlement_relation >= 0.4:
                culture += f" {settlement_name} and {other_settlement_name} are on warm terms."
            elif cross_settlement_relation <= -0.4:
                culture += f" {settlement_name} and {other_settlement_name} are on cold terms."
    beliefs_text = (
        f" What the village has come to believe about them: {'; '.join(beliefs_about)}."
        if beliefs_about else ""
    )
    personality_bits = []
    for agent, label in ((agent_a, agent_a.name), (agent_b, agent_b.name)):
        personality = describe_traits(agent.traits)
        if personality:
            personality_bits.append(f"{label} is {personality}")
    personality_text = f" {'; '.join(personality_bits)}." if personality_bits else ""
    # Phase 3.B "occupation -> identity/status/dialogue register"
    # (docs/VISION-2026-07-21-SELFEVOLVING.md): "a priest speaks to
    # belief, a banker to debt" — a light manner-of-speaking hint, same
    # "garnish, never forced" treatment `voice_bits` below already gets.
    # Only the occupations in OCCUPATION_DIALOGUE_REGISTER carry one;
    # everyone else contributes nothing here.
    register_bits = []
    for agent, label in ((agent_a, agent_a.name), (agent_b, agent_b.name)):
        register = OCCUPATION_DIALOGUE_REGISTER.get(agent.occupation)
        if register:
            register_bits.append(f"{label}, as {agent.occupation}, {register}")
    register_text = f" {'. '.join(register_bits)}." if register_bits else ""
    emotion_bits = []
    for agent, label in ((agent_a, agent_a.name), (agent_b, agent_b.name)):
        emotion = describe_emotion(agent.emotions)
        if emotion:
            emotion_bits.append(f"{label} is currently feeling {emotion}")
    emotion_text = f" {'; '.join(emotion_bits)}." if emotion_bits else ""
    memory_bits = []
    just_now_bits = []
    semantic_bits = []
    secret_bits = []
    mind_bits = []
    voice_bits = []
    lesson_bits = []
    for agent, label, other, lesson in (
        (agent_a, agent_a.name, agent_b, lessons[0]), (agent_b, agent_b.name, agent_a, lessons[1]),
    ):
        recent = agent.memories[-DIALOGUE_MEMORY_IN_PROMPT:]
        recent_salience = agent.memory_salience[-DIALOGUE_MEMORY_IN_PROMPT:]
        recent_display = [faded_memory_text(t, s) for t, s in zip(recent, recent_salience)]
        if recent_display:
            memory_bits.append(f"{label} recently: {'; '.join(recent_display)}")
        just_now = _just_now_text(agent.working_memory, recent)
        if just_now:
            just_now_bits.append(f"{label} just now: {just_now}")
        if agent.semantic_memories:
            semantic_bits.append(f"{label} has come to feel: {agent.semantic_memories[-1]}")
        # Secrets (Phase J, v0.78.3): only surfaced when the secret is
        # actually about the OTHER speaker in this exchange (matched by
        # name, same lightweight text-matching convention `beliefs_
        # about_agent`'s callers already use elsewhere) — a secret about
        # someone not present has no business shaping this conversation.
        own_secret = next((s for s in agent.secrets if other.name in s), None)
        if own_secret:
            secret_bits.append(f"{label} is privately holding something back about {other.name}: {own_secret}")
        # Permanent mind (Phase J, v0.78.4): core cast only (empty "" for
        # everyone else, so this is a no-op for a non-core exchange).
        if agent.mind:
            mind_bits.append(f"{label}, at their core: {agent.mind}")
        # Per-agent voice (v0.87.12, docs/IDEAS-2026-07-EMERGENCE.md
        # §7): a manner-of-speaking garnish, same core-cast-only scope
        # as `mind` (empty "" for everyone else — no-op here).
        if agent.voice:
            # Retroactively sanitizes any already-persisted voice text
            # too (see `normalize_voice_phrase`'s docstring) — no
            # snapshot migration needed, this runs on every read.
            voice_bits.append(f"{label} {normalize_voice_phrase(agent.voice)}")
        # Lessons (v0.87.0, "learns like a human"): the one stored lesson
        # (if any) matching THIS speaker's current situation — see
        # Agent.lessons/SimulationEngine._current_situation_tag. Same
        # "smarter recall" treatment cognition.build_prompt already gets;
        # dialogue previously never read this layer at all.
        if lesson:
            lesson_bits.append(f"{label} has learned: {lesson}")
    memory_text = f" {'. '.join(memory_bits)}." if memory_bits else ""
    just_now_text = f" {'. '.join(just_now_bits)}." if just_now_bits else ""
    semantic_text = f" {'. '.join(semantic_bits)}." if semantic_bits else ""
    secret_text = f" {'. '.join(secret_bits)}." if secret_bits else ""
    mind_text = f" {'. '.join(mind_bits)}." if mind_bits else ""
    voice_text = f" {'. '.join(voice_bits)}." if voice_bits else ""
    lesson_text = f" {'. '.join(lesson_bits)}." if lesson_bits else ""

    # "Diversify conversation opportunities" (explicit live request):
    # weighted-select 1-2 of the available steering candidates instead
    # of unconditionally naming all of them — see
    # `build_opportunity_candidates`/`select_opportunities`. Use the
    # caller's pre-computed picks when given (the engine's call site
    # does this so it can log the chosen categories); otherwise select
    # fresh here.
    if opportunities is None:
        opportunity_candidates = build_opportunity_candidates(
            agent_a, agent_b, is_parent_child, recent_topics, settlement_topics,
            place_names, grounded_event, weather_notable, weather,
        )
        opportunities = select_opportunities(opportunity_candidates, opportunity_rng or random.Random())
    opportunity_text = "".join(f" {text}" for _category, text in opportunities)

    objective_bits = []
    for label, objective in ((agent_a.name, objectives[0]), (agent_b.name, objectives[1])):
        if objective:
            objective_bits.append(f"{label} privately wants, from this exchange: {objective}")
    objective_text = f" {'. '.join(objective_bits)}." if objective_bits else ""
    open_thread_text = f" Still unresolved between them: {open_thread}." if open_thread else ""

    def _activity(agent: Agent) -> str:
        # Grounds "currently X" in *why* when cognition set a reason
        # (LLM-authored goal or the trait-aware fallback_goal both
        # populate this) — previously the prompt only named the goal
        # ("currently forage"), never the motivation behind it, so a
        # villager talking about their own activity had nothing more
        # specific to say than the deterministic fallback would. See
        # docs/DECISIONS.md, "dialogue quality" pass (v0.72.0).
        if agent.goal_reason:
            return f'{agent.goal.value} ("{agent.goal_reason.strip()[:80]}")'
        return agent.goal.value

    return (
        f"{agent_a.name} (hunger {agent_a.hunger:.2f}, energy {agent_a.energy:.2f}, "
        f"currently {_activity(agent_a)}) meets {agent_b.name} (hunger "
        f"{agent_b.hunger:.2f}, energy {agent_b.energy:.2f}, currently {_activity(agent_b)}). "
        f"They are {tie}. It is {season}."
        f"{culture}{beliefs_text}{personality_text}{register_text}{emotion_text}{memory_text}{just_now_text}"
        f"{semantic_text}{secret_text}{mind_text}{voice_text}{lesson_text}{opportunity_text}"
        f"{objective_text}{open_thread_text} "
        "Write their brief exchange."
    )


_TENSE_POOL: tuple[tuple[str, str], ...] = (
    ("I have nothing to say to you, {b}.", "Nor I to you."),
    ("Still avoiding me, {b}?", "Can you blame me?"),
    ("We should talk. Eventually.", "Eventually."),
    ("Out of my way.", "Gladly."),
    ("Don't start, {b}.", "I wasn't going to."),
    ("You've got a lot of nerve, {b}.", "So I've been told."),
    ("Say what you mean, {a}, or don't say it at all.", "Fine. Not now."),
    ("Funny running into you.", "Isn't it just."),
)
_WARM_POOL: tuple[tuple[str, str], ...] = (
    ("Good to see you, {b}.", "And you, always."),
    ("I was hoping to run into you.", "Likewise, {a}."),
    ("You look well today.", "Feeling well, thanks to you."),
    ("Walk with me a while?", "Always."),
    ("Save me a seat next time?", "Already do."),
    ("You're a sight for tired eyes, {b}.", "Comes with practice."),
    ("Been meaning to thank you for the other day.", "Don't mention it, {a}."),
    ("How's the family?", "Loud. Same as ever."),
)
_NEUTRAL_POOL: tuple[tuple[str, str], ...] = (
    ("Quiet day.", "Quiet enough."),
    ("Cold one, isn't it.", "That it is."),
    ("Anything new?", "Not much, no."),
    ("Long day.", "Isn't it always."),
    ("Busy morning?", "Busy enough."),
    ("Where are you headed?", "Wherever this takes me."),
    ("You look deep in thought.", "Just thinking out loud, mostly."),
    ("Fine weather for it, at least.", "Small mercies."),
)
"""Small pools rather than one fixed line per band, cycled
deterministically by (agent ids, tick) — a fallback-only run (Ollama
disabled or unreachable) previously repeated the exact same 3 lines for
every pair forever, which read as an obvious, boring bug. See
docs/DECISIONS.md, "NPCs repeating dialogue" fix. Widened 5 -> 8 entries
per band in v0.72.0's dialogue-quality pass — still finite, but a longer
cycle before a fallback-only run notices the repeat."""

_MEMORY_REACTIONS: tuple[str, ...] = (
    "Is that so.", "Hadn't heard that.", "Hm. Good to know.",
    "Word travels fast.", "That's something, alright.", "First I'm hearing of it.",
)
"""Short, neutral reactions used opposite a memory-grounded opening line
(see `fallback_dialogue`) — deliberately generic since they only need to
acknowledge the other speaker, not carry content of their own."""


def fallback_dialogue(agent_a: Agent, agent_b: Agent, affinity: float, tick: int = 0) -> dict:
    """Deterministic stand-in, varying by relationship band and cycled
    by tick so the same pair doesn't get the identical line every time —
    mirrors cognition.fallback_goal's approach, extended for variety.

    v0.72.0: roughly one exchange in three (when the band isn't tense —
    trading a genuine memory doesn't fit an "at odds" exchange the same
    way) splices in whichever speaker has a recent memory instead of a
    pool line, the same "ground it in what actually happened" fix the
    LLM prompt already has (see `build_prompt`'s `memory_bits`) — a
    fallback-only run (LLM disabled/unreachable) previously had zero
    connection to the world's actual events, reading as pure canned
    chit-chat regardless of what was happening in the village. Selection
    is deterministic (agent ids + tick), not random, matching the
    project's namespaced-but-reproducible-per-site RNG convention."""
    if affinity <= RIVALRY_THRESHOLD:
        pool, sentiment = _TENSE_POOL, "tense"
    elif affinity >= 0.6:
        pool, sentiment = _WARM_POOL, "warm"
    else:
        pool, sentiment = _NEUTRAL_POOL, "neutral"

    if sentiment != "tense" and (agent_a.id + agent_b.id + tick) % 3 == 0:
        speaker, other = (agent_a, agent_b) if (agent_a.id + tick) % 2 == 0 else (agent_b, agent_a)
        memory = speaker.memories[-1] if speaker.memories else (other.memories[-1] if other.memories else None)
        speaker = speaker if speaker.memories else other
        if memory:
            trimmed = memory.strip()
            if len(trimmed) > 90:
                trimmed = trimmed[:90].rsplit(" ", 1)[0] + "..."
            opener = f"Did you hear? {trimmed}"
            reaction = _MEMORY_REACTIONS[(agent_a.id + agent_b.id + tick) % len(_MEMORY_REACTIONS)]
            line_a, line_b = (opener, reaction) if speaker is agent_a else (reaction, opener)
            return {"line_a": line_a, "line_b": line_b, "sentiment": sentiment, "rumor": ""}

    line_a, line_b = pool[(agent_a.id + agent_b.id + tick) % len(pool)]
    return {
        "line_a": line_a.format(a=agent_a.name, b=agent_b.name),
        "line_b": line_b.format(a=agent_a.name, b=agent_b.name),
        "sentiment": sentiment, "rumor": "",
    }


_VALID_SENTIMENTS = {"warm", "tense", "neutral"}

DIALOGUE_DEBT_DELTA_MAX = 1.0
"""Phase 2: caps how much a single exchange's `debt_delta` can move
either agent's ledger debt — small next to `_record_debt`'s per-trade
DEBT_PER_TRADE_FRACTION-scaled amounts (a real barter, not a
conversational aside about one), and well below `DEBT_SIGNIFICANT_
THRESHOLD=2.0`'s decay-lock floor, so a single chatty exchange alone
can never lock a debt against decay — only several would."""

_MAX_LINE_WORDS = 26
"""A line requested as "under 14 words" that comes back several times
longer is a sign a small/weak model rambled past the instruction rather
than writing a real line — see `_is_sane_line`. Both the prompt's word
budget (10 -> 14, v0.72.3) and this sanity ceiling (22 -> 26, kept
proportional) were raised for dialogue-quality reasons, not a memory
one: 10-under words often reads as a clipped fragment rather than
natural speech, and the extra few tokens this costs per line are
negligible against `Config.llm_num_ctx`'s now-larger budget (see its
docstring) — there was no real reason to keep the tighter number once
that budget stopped being razor-thin."""

_LEAKAGE_MARKERS = (
    "json", "system prompt", "you are writing", "villager who",
    "respond with", "as an ai", "language model", "i cannot", "i'm an ai",
    "line_a", "line_b", "sentiment", '"rumor"', "as a villager",
    "here is", "here's a", "sure,", "output:", "```",
)
"""Substrings that show up when a weak model leaks its instructions,
field names, or meta-commentary into the output instead of writing an
actual line — degrading to the fallback in that case reads as an
ordinary canned line instead of visibly broken text. Widened in v0.75.2
(field-name/markdown/preamble leakage: `line_a`, ```` ``` ````, "here
is", "output:") after a live report of garbled dialogue on the small
default model. See docs/DECISIONS.md, "dialogue quality follow-up"."""


def _looks_garbled(line: str) -> bool:
    """True if a line is mostly non-letters or a single token spammed —
    both small-model degeneration modes (mojibake / repetition loops)
    that read as obviously broken text rather than dialogue. Kept
    separate from the leakage-marker list since it's a shape check, not
    a substring match. A short interjection ('Hm.', 'Aye.') is fine — the
    letter-ratio gate only applies once there's enough text to judge."""
    stripped = line.strip()
    letters = sum(c.isalpha() or c.isspace() for c in stripped)
    if len(stripped) >= 8 and letters / len(stripped) < 0.6:
        return True
    tokens = [t for t in stripped.lower().split() if t.isalpha()]
    if len(tokens) >= 4 and len(set(tokens)) <= max(1, len(tokens) // 3):
        # e.g. "no no no no no" — one word repeated to fill the line.
        return True
    return False


def _is_sane_line(line: str, other_line: str, max_words: int = _MAX_LINE_WORDS) -> bool:
    """Reject a line that's almost certainly a small-model failure mode
    rather than a real line of dialogue: instruction/meta/field-name
    leakage, garbled (mostly-symbol or repetition-loop) text, wildly over
    length, or an exact duplicate of the other speaker's line (all "make
    no sense" symptoms actually observed in live small-model
    diagnostics). `max_words` is overridable — the voice pair's own
    longer-form exchanges (see `VOICE_MAX_LINE_WORDS`) need a higher
    ceiling than ordinary crowd small talk."""
    lowered = line.lower()
    if any(marker in lowered for marker in _LEAKAGE_MARKERS):
        return False
    if len(line.split()) > max_words:
        return False
    if line.strip().lower() == other_line.strip().lower():
        return False
    if "{" in line or "}" in line:
        return False
    if _looks_garbled(line):
        return False
    return True


TIC_SPREAD_DISTINCT_SPEAKER_THRESHOLD = 3
TIC_SPREAD_WINDOW = 60
TIC_TAIL_MIN_LINE_LENGTH = 10
TIC_TAIL_MAX_WORDS = 4
"""P3.2 (docs/AUDIT-2026-07-20.md): a live session showed the same
trailing phrase ("…, and so.") appearing in multiple different agents'
lines — the model imitating a verbal tic it saw in one agent's
pair-history text and letting it bleed into everyone else's, which
defeats the whole point of `mind.py`'s per-agent voice feature.
`SimulationEngine` tracks the last `TIC_SPREAD_WINDOW` (tail
fingerprint, speaker name) pairs across all dialogue calls; a line
whose tail fingerprint has already been used by
`TIC_SPREAD_DISTINCT_SPEAKER_THRESHOLD` or more OTHER speakers within
that window degrades to the deterministic fallback, same "suspicious
content -> fallback" treatment `_is_sane_line` already gives garbled/
leaked text. The fingerprint is the text after the line's last comma
(the observed tic sat right after one), capped at `TIC_TAIL_MAX_WORDS`
words — falls back to the last `TIC_TAIL_MAX_WORDS` words when there's
no comma. Deliberately a literal-string match, not stemmed/semantic —
the observed failure mode is a repeated tail string, not a paraphrase.
Lines shorter than `TIC_TAIL_MIN_LINE_LENGTH` are exempt (a short
interjection sharing a tail with another short interjection is
normal, not a spreading tic)."""


def line_tail_fingerprint(line: str) -> str:
    """Fingerprint of a line's trailing clause — see TIC_TAIL_MAX_
    WORDS's docstring for why this is intentionally a literal-string
    match, not semantic."""
    stripped = line.strip().lower()
    tail = stripped.rsplit(",", 1)[-1].strip()
    words = tail.split()
    if not words:
        words = stripped.split()
    return " ".join(words[-TIC_TAIL_MAX_WORDS:])


def is_spreading_tic(
    line: str, speaker: str, recent_tails: list[tuple[str, str]],
    threshold: int = TIC_SPREAD_DISTINCT_SPEAKER_THRESHOLD,
) -> bool:
    """True if `line`'s tail fingerprint has already been used by at
    least `threshold` speakers OTHER than `speaker` within
    `recent_tails` (a bounded (fingerprint, speaker) history the
    caller maintains — see TIC_SPREAD_WINDOW's docstring)."""
    if len(line.strip()) < TIC_TAIL_MIN_LINE_LENGTH:
        return False
    fingerprint = line_tail_fingerprint(line)
    other_speakers = {s for fp, s in recent_tails if fp == fingerprint and s != speaker}
    return len(other_speakers) >= threshold


def parse_dialogue(result: dict, fallback: dict) -> dict:
    """Validate an LLM (or fallback) response into a safe dict. Any
    malformed OR merely-suspicious content (see `_is_sane_line`)
    degrades to the fallback field-by-field rather than raising or
    surfacing garbled text — a bad LLM response should never crash a
    tick or read as obviously broken."""
    sentiment = result.get("sentiment")
    if sentiment not in _VALID_SENTIMENTS:
        sentiment = fallback["sentiment"]
    line_a = result.get("line_a")
    line_b = result.get("line_b")
    if not isinstance(line_a, str) or not line_a.strip():
        line_a = fallback["line_a"]
    if not isinstance(line_b, str) or not line_b.strip():
        line_b = fallback["line_b"]
    if not _is_sane_line(line_a, line_b) or not _is_sane_line(line_b, line_a):
        line_a, line_b = fallback["line_a"], fallback["line_b"]
    rumor = result.get("rumor")
    if not isinstance(rumor, str):
        rumor = ""
    # v0.87.12 "dialogue novelty memory" (docs/IDEAS-2026-07-EMERGENCE.md
    # §7): unlike every other field here, a missing/blank topic degrades
    # to "" rather than the fallback's — the fallback dict has no
    # "topic" key at all, and a fabricated topic for deterministic
    # chatter would be noise in `Population.dialogue_topics`, which only
    # wants genuine LLM-observed subjects.
    topic = result.get("topic")
    if not isinstance(topic, str):
        topic = ""
    # Phase 2 "dialogue as a simulation event" structured-outcome fields
    # (docs/VISION-2026-07-21-SELFEVOLVING.md) — same "missing/invalid
    # degrades to the inert default, never fabricated" treatment as
    # topic/rumor above. Never present on `fallback` (deterministic
    # chatter has no mechanical outcome), so no fallback lookup needed.
    promise = result.get("promise")
    if not isinstance(promise, str):
        promise = ""
    debt_delta = result.get("debt_delta")
    if not isinstance(debt_delta, (int, float)) or isinstance(debt_delta, bool):
        debt_delta = 0.0
    debt_delta = clamp(float(debt_delta), -DIALOGUE_DEBT_DELTA_MAX, DIALOGUE_DEBT_DELTA_MAX)
    return {
        "line_a": line_a.strip()[:120],
        "line_b": line_b.strip()[:120],
        "sentiment": sentiment,
        "rumor": rumor.strip()[:150],
        "topic": topic.strip()[:40],
        "promise": promise.strip()[:120],
        "debt_delta": debt_delta,
        "secret_revealed": bool(result.get("secret_revealed")),
        "misunderstanding": bool(result.get("misunderstanding")),
        "goal_change": bool(result.get("goal_change")),
    }


# --- Voice pair: the town's two LLM-dialogue speakers ----------------------
# Explicit user directive: LLM dialogue is disabled for every pair except one
# fixed core-cast pair (Population.voice_pair_ids) — freeing the budget that
# used to spread thin across several core-core pairs into ONE real, deep,
# continuing conversation between two people who know each other, with an
# actual memory of what was just said. Deliberately a separate prompt/parse
# path from build_prompt/parse_dialogue above rather than a mode flag on
# them — the ordinary crowd-dialogue machinery (opportunity weighting,
# novelty-topic rings, weather/place/settlement-topic steering) is tuned for
# brief small talk between people who may barely know each other; the voice
# pair wants something structurally simpler (concise town state + internal
# state + the actual conversation so far) pushed much harder on depth and
# continuity instead.

VOICE_MAX_LINE_WORDS = 40
"""Each voice-pair line may run up to this many words — real conversation
between two people who know each other well runs longer than a passing
"just crossed paths" exchange (`_MAX_LINE_WORDS`=26 there). Enforced both
in the prompt's own instruction and as `_is_sane_line`'s ceiling via
`parse_voice_dialogue`."""

VOICE_MAX_LINE_CHARS = 320
"""Character truncation ceiling for a voice-pair line — proportionally
wider than the ordinary 120-char cap, matching VOICE_MAX_LINE_WORDS."""

VOICE_SYSTEM_PROMPT = (
    "You are writing the next moment in an ONGOING, real conversation between "
    "two people who know each other well in a small simulated world — not two "
    "strangers making small talk, an established relationship continuing "
    "naturally from what was just said. If 'the conversation so far' is given "
    "below, treat it as real and continue it: line_a must pick up from the "
    "last thing said, not restart the topic or open with a fresh greeting. "
    "Ground what you write in the concrete facts given — the town's current "
    "situation, what each person is feeling and doing right now, their "
    "relationship, and anything either privately wants or is holding back. "
    "Real conversation between two people who know each other can run longer "
    "and go deeper than passing small talk — lines may run up to about 40 "
    "words when there's something real being said, but don't pad or ramble; "
    "a short reaction is still fine when that's honest, and it's fine for a "
    "line to be a half-finished thought or a single word. Write like two "
    "real people: it's fine to disagree, deflect, joke, trail off, or leave "
    "something unresolved — they don't have to agree or resolve anything. "
    "line_b must be a genuine reaction to line_a — an actual answer, a "
    "rebuttal, a joke back, a change of subject that still acknowledges what "
    "was said — never a line that could just as well have opened the "
    "conversation on its own. Never invent unrelated topics, and never "
    "mention that this is a game, a simulation, or that you are an AI. "
    "A real person doesn't repeat the same image, metaphor, or complaint "
    "every time they talk — if 'the conversation so far' sounds similar to "
    "something already said, find an actually different angle, memory, or "
    "concern rather than reusing the same phrase or idea again. "
    "Each speaker may address the OTHER person by name, but must NEVER say "
    "their own name — a person doesn't call themself by name when they talk. "
    "Output ONLY the JSON object below, nothing before or after it, no "
    "explanation.\n"
    'Respond with strict JSON only, in this exact shape: {"line_a": "up to '
    '40 words, said by the first speaker, continuing the conversation", '
    '"line_b": "up to 40 words, a genuine reply from the second speaker to '
    'what line_a just said", "sentiment": "warm" | "tense" | "neutral", '
    '"topic": "1-3 words naming what this exchange was actually about"}.'
)


def build_voice_prompt(
    agent_a: Agent, agent_b: Agent, affinity: float, settlement_name: str,
    town_digest: str = "", internal_state_a: str = "", internal_state_b: str = "",
    conversation_so_far: list[dict] | None = None,
) -> str:
    """`town_digest`: one concise sentence of what's happening in the
    town right now (the call site's own condensed read, NOT the full
    grounding apparatus `build_prompt` uses — explicit user directive
    for "a very concise summary of the town and happenings"). `internal_
    state_a`/`internal_state_b`: a short line per speaker covering their
    own hunger/energy/emotion/current activity — "their internal
    states," per the same directive. `conversation_so_far`: the voice
    pair's own recent lines (`Population.voice_conversation`, newest
    last, each `{"speaker", "text"}` with `speaker` already resolved to
    a display name at the call site) — when given, the prompt frames
    this as a continuation, not an opener."""
    if affinity >= 0.6:
        tie = "close friends"
    elif affinity <= RIVALRY_THRESHOLD:
        tie = "at odds with each other"
    elif affinity <= 0.0:
        tie = "strangers, or barely acquainted"
    else:
        tie = "friendly acquaintances"
    lines = [
        f"{agent_a.name} and {agent_b.name} are {tie}"
        + (f" in {settlement_name}." if settlement_name else "."),
    ]
    if town_digest:
        lines.append(f"The town right now: {town_digest}")
    if internal_state_a:
        lines.append(f"{agent_a.name} right now: {internal_state_a}")
    if internal_state_b:
        lines.append(f"{agent_b.name} right now: {internal_state_b}")
    if conversation_so_far:
        convo = "\n".join(f"  {turn['speaker']}: {turn['text']}" for turn in conversation_so_far)
        lines.append(f"The conversation so far:\n{convo}")
        lines.append("Continue this conversation naturally from here.")
    else:
        lines.append("This is the start of a new conversation between them.")
    return "\n".join(lines)


def fallback_voice_dialogue(agent_a: Agent, agent_b: Agent, affinity: float, tick: int) -> dict:
    """Same shape/pool as `fallback_dialogue` — the voice pair still
    needs a real answer on a backpressured/budget-exhausted tick, this
    is just the identical deterministic mechanism reused rather than a
    parallel pool."""
    return fallback_dialogue(agent_a, agent_b, affinity, tick)


_VOICE_WORD_RE = re.compile(r"[a-z']+")
VOICE_LINE_DUPLICATE_OVERLAP = 0.6
"""Live-reported finding: the voice pair's own frequent cadence
(`VOICE_DIALOGUE_COOLDOWN_TICKS=5`) plus a small model repeatedly seeing
similar internal-state/town-digest input converges onto a handful of
images ("cold bread," "stir the soup," "ash still smells like home")
and recites them near-verbatim many exchanges apart — the exact same
"small model shown similar context re-condenses the same idea instead
of writing something new" shape `FOLKLORE_DUPLICATE_OVERLAP` already
fixed for monthly tale-telling, just for the voice pair's much more
frequent cadence instead. The prompt itself now also asks the model not
to repeat an image/complaint it's already used (see `VOICE_SYSTEM_
PROMPT`) — this Jaccard word-overlap check is the deterministic
backstop for when a weak model doesn't comply, same class of stdlib-
only heuristic as `review_diagnostics`' keyword overlap."""


def _is_near_duplicate_line(line: str, recent_lines: list[str]) -> bool:
    words = set(_VOICE_WORD_RE.findall(line.lower()))
    if not words:
        return False
    for existing in recent_lines:
        existing_words = set(_VOICE_WORD_RE.findall(existing.lower()))
        if not existing_words:
            continue
        overlap = len(words & existing_words) / len(words | existing_words)
        if overlap >= VOICE_LINE_DUPLICATE_OVERLAP:
            return True
    return False


_SELF_NAME_VOCATIVE_RES_CACHE: dict[str, tuple] = {}


def _self_name_vocative_patterns(own_name: str) -> tuple:
    cached = _SELF_NAME_VOCATIVE_RES_CACHE.get(own_name)
    if cached is not None:
        return cached
    escaped = re.escape(own_name)
    patterns = (
        re.compile(rf",\s*{escaped}\s*([.!?]?)\s*$", re.IGNORECASE),  # "..., Osric." (trailing)
        re.compile(rf"^{escaped}\s*,\s*", re.IGNORECASE),  # "Osric, ..." (leading)
        re.compile(rf",\s*{escaped}\s*,", re.IGNORECASE),  # "..., Osric, ..." (mid-sentence)
    )
    _SELF_NAME_VOCATIVE_RES_CACHE[own_name] = patterns
    return patterns


def _strip_self_address(line: str, own_name: str) -> str:
    """Removes a vocative use of the SPEAKER'S OWN name from their own
    line — e.g. "...we were, Osric." spoken by Osric himself, a real
    live-reported failure mode (a real person doesn't call themself by
    name mid-sentence; `VOICE_SYSTEM_PROMPT` now says so explicitly,
    this is the deterministic backstop). Only strips a clear vocative
    position (immediately after/before a comma, trailing punctuation
    preserved) rather than any substring occurrence, so a name that
    happens to appear as part of a longer clause is left alone. A no-op
    when `own_name` is empty (agent/name unavailable at the call site)
    or doesn't appear as a vocative."""
    if not own_name or not line:
        return line
    trailing_re, leading_re, mid_re = _self_name_vocative_patterns(own_name)
    stripped = trailing_re.sub(r"\1", line)
    stripped = leading_re.sub("", stripped)
    stripped = mid_re.sub(",", stripped)
    return stripped.strip() or line


def parse_voice_dialogue(
    result: dict, fallback: dict,
    speaker_a_name: str = "", speaker_b_name: str = "",
    recent_lines_a: list[str] | None = None, recent_lines_b: list[str] | None = None,
) -> dict:
    """Same validation shape as `parse_dialogue`, with the voice pair's
    wider length ceiling (`VOICE_MAX_LINE_WORDS`/`_CHARS`). The model
    itself is never asked for the Phase-2 structured-outcome fields
    (promise/debt/secret/misunderstanding/goal_change) — the voice
    pair's exchanges are narration-grade conversation, not a scripted
    scene — but the returned dict still carries them at inert defaults
    so it's a drop-in for `Population.apply_dialogue`/`SimulationEngine.
    _apply_pending_dialogue_results`, the same shared apply pipeline
    ordinary dialogue already uses (is_llm-gated event surfacing, topic-
    ring recording, cross-settlement relation nudge — all reused
    unchanged rather than duplicated for the voice pair).

    `speaker_a_name`/`speaker_b_name` (optional, backward compatible):
    when given, strips a self-address vocative from that speaker's own
    line — see `_strip_self_address`. `recent_lines_a`/`recent_lines_b`
    (optional): that speaker's own prior voice-pair lines — a near-
    duplicate (see `VOICE_LINE_DUPLICATE_OVERLAP`) degrades just that
    one side to the deterministic fallback rather than losing the whole
    exchange, since the other side is very likely still a genuine, non-
    repeated line worth keeping."""
    sentiment = result.get("sentiment")
    if sentiment not in _VALID_SENTIMENTS:
        sentiment = fallback["sentiment"]
    line_a = result.get("line_a")
    line_b = result.get("line_b")
    if not isinstance(line_a, str) or not line_a.strip():
        line_a = fallback["line_a"]
    if not isinstance(line_b, str) or not line_b.strip():
        line_b = fallback["line_b"]
    if (
        not _is_sane_line(line_a, line_b, max_words=VOICE_MAX_LINE_WORDS)
        or not _is_sane_line(line_b, line_a, max_words=VOICE_MAX_LINE_WORDS)
    ):
        line_a, line_b = fallback["line_a"], fallback["line_b"]
    else:
        line_a = _strip_self_address(line_a, speaker_a_name)
        line_b = _strip_self_address(line_b, speaker_b_name)
        if recent_lines_a and _is_near_duplicate_line(line_a, recent_lines_a):
            line_a = fallback["line_a"]
        if recent_lines_b and _is_near_duplicate_line(line_b, recent_lines_b):
            line_b = fallback["line_b"]
    topic = result.get("topic")
    if not isinstance(topic, str):
        topic = ""
    return {
        "line_a": line_a.strip()[:VOICE_MAX_LINE_CHARS],
        "line_b": line_b.strip()[:VOICE_MAX_LINE_CHARS],
        "sentiment": sentiment,
        "topic": topic.strip()[:40],
        "rumor": "",
        "promise": "",
        "debt_delta": 0.0,
        "secret_revealed": False,
        "misunderstanding": False,
        "goal_change": False,
    }
