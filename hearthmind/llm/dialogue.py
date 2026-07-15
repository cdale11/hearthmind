"""Ambient NPC-to-NPC dialogue: colocated agents periodically exchange a
short LLM-authored line each. The exchange nudges their relationship
(warmer, tenser, or unchanged) and may seed a rumor, which is logged as a
normal event and so gets read back into the chronicle/culture prompts
like anything else that happens in the world. This is the concrete
mechanism behind "NPCs talk to and influence each other" — see
docs/DECISIONS.md, E2.
"""
from __future__ import annotations

from hearthmind.agents.agent import RIVALRY_THRESHOLD, Agent, describe_traits

SYSTEM_PROMPT = (
    "You are writing a brief, natural exchange between two villagers who "
    "just crossed paths in a simulated world. Ground it in the specific "
    "facts you're given (their hunger/energy, what each is currently "
    "doing and WHY if a reason is given, the weather, their relationship, "
    "and especially anything listed as something one of them recently "
    "remembers or believes) — prefer talking about that over generic "
    "small talk, never invent unrelated topics, and never mention that "
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
    "have opened the conversation. Optionally the exchange plants a "
    "short rumor that might spread through the village — leave it blank "
    "most of the time. Output ONLY the JSON object below, nothing before "
    "or after it, no explanation.\n"
    "Examples of the exact shape expected:\n"
    '{"line_a": "You look worn out, friend.", "line_b": "Long day in the '
    'fields.", "sentiment": "warm", "rumor": ""}\n'
    '{"line_a": "Still nothing to say to me?", "line_b": "Not today.", '
    '"sentiment": "tense", "rumor": ""}\n'
    '{"line_a": "Cold one, isn\'t it.", "line_b": "Heard the miller\'s '
    'roof is leaking.", "sentiment": "neutral", "rumor": "The miller\'s '
    'roof is leaking."}\n'
    '{"line_a": "You still sore about the fence?", "line_b": "Wasn\'t '
    'talking about the fence.", "sentiment": "tense", "rumor": ""}\n'
    '{"line_a": "Hungry work today.", "line_b": "Isn\'t it always with '
    'you.", "sentiment": "warm", "rumor": ""}\n'
    'Now respond with strict JSON only, in that exact shape: {"line_a": '
    '"under 14 words, said by the first villager", "line_b": "under 14 '
    'words, said by the second", "sentiment": "warm" | "tense" | '
    '"neutral", "rumor": "" or a short rumor under 15 words}.'
)


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
) -> str:
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
    memory_bits = []
    for agent, label in ((agent_a, agent_a.name), (agent_b, agent_b.name)):
        recent = agent.memories[-DIALOGUE_MEMORY_IN_PROMPT:]
        if recent:
            memory_bits.append(f"{label} recently: {'; '.join(recent)}")
    memory_text = f" {'. '.join(memory_bits)}." if memory_bits else ""

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
        f"They are {tie}. It is {season}, weather: {weather}."
        f"{culture}{beliefs_text}{personality_text}{memory_text} "
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
)
"""Substrings that show up when a weak model leaks its instructions or
meta-commentary into the output instead of writing an actual line —
degrading to the fallback in that case reads as an ordinary canned
line instead of visibly broken text. See docs/DECISIONS.md, "dialogue
quality follow-up" (qwen3.5:2b diagnostics)."""


def _is_sane_line(line: str, other_line: str) -> bool:
    """Reject a line that's almost certainly a small-model failure mode
    rather than a real line of dialogue: instruction/meta leakage, wildly
    over length, or an exact duplicate of the other speaker's line
    (a "make no sense" symptom actually observed in live 2B-model
    diagnostics)."""
    lowered = line.lower()
    if any(marker in lowered for marker in _LEAKAGE_MARKERS):
        return False
    if len(line.split()) > _MAX_LINE_WORDS:
        return False
    if line.strip().lower() == other_line.strip().lower():
        return False
    if "{" in line or "}" in line:
        return False
    return True


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
    return {
        "line_a": line_a.strip()[:120],
        "line_b": line_b.strip()[:120],
        "sentiment": sentiment,
        "rumor": rumor.strip()[:150],
    }
