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
    "doing, the weather, their relationship, and especially anything "
    "listed as something one of them recently remembers or believes) — "
    "prefer talking about that over generic small talk, never invent "
    "unrelated topics, and never mention that this is a game, a "
    "simulation, or that you are an AI. Optionally "
    "the exchange plants a short rumor that might spread through the "
    "village — leave it blank most of the time. Output ONLY the JSON "
    "object below, nothing before or after it, no explanation.\n"
    "Examples of the exact shape expected:\n"
    '{"line_a": "You look worn out, friend.", "line_b": "Long day in the '
    'fields.", "sentiment": "warm", "rumor": ""}\n'
    '{"line_a": "Still nothing to say to me?", "line_b": "Not today.", '
    '"sentiment": "tense", "rumor": ""}\n'
    '{"line_a": "Cold one, isn\'t it.", "line_b": "Heard the miller\'s '
    'roof is leaking.", "sentiment": "neutral", "rumor": "The miller\'s '
    'roof is leaking."}\n'
    'Now respond with strict JSON only, in that exact shape: {"line_a": '
    '"under 10 words, said by the first villager", "line_b": "under 10 '
    'words, said by the second", "sentiment": "warm" | "tense" | '
    '"neutral", "rumor": "" or a short rumor under 15 words}.'
)


DIALOGUE_MEMORY_IN_PROMPT = 1
"""How many of each speaker's most recent memories reach the dialogue
prompt — same reasoning as cognition.RECENT_MEMORIES_IN_PROMPT, kept to
1 here (vs. cognition's 3) since a conversational line only has room to
land one concrete thing per speaker anyway. Previously 0: dialogue was
the one LLM-authored prompt in the project that never read from
`agent.memories` at all, despite cognition (goal-setting) already doing
so — a colocated pair had no way to talk about anything that actually
happened to either of them (a death, a bond, a rumor heard), only their
current stats/weather/relationship, which reads as generic small talk
regardless of model quality. See docs/DECISIONS.md, "dialogue grounding
fix.\""""


def build_prompt(
    agent_a: Agent, agent_b: Agent, affinity: float, settlement_name: str,
    latest_tradition: str, season: str, weather: str, beliefs_about: list[str] | None = None,
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
    return (
        f"{agent_a.name} (hunger {agent_a.hunger:.2f}, energy {agent_a.energy:.2f}, "
        f"currently {agent_a.goal.value}) meets {agent_b.name} (hunger "
        f"{agent_b.hunger:.2f}, energy {agent_b.energy:.2f}, currently {agent_b.goal.value}). "
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
)
_WARM_POOL: tuple[tuple[str, str], ...] = (
    ("Good to see you, {b}.", "And you, always."),
    ("I was hoping to run into you.", "Likewise, {a}."),
    ("You look well today.", "Feeling well, thanks to you."),
    ("Walk with me a while?", "Always."),
    ("Save me a seat next time?", "Already do."),
)
_NEUTRAL_POOL: tuple[tuple[str, str], ...] = (
    ("Quiet day.", "Quiet enough."),
    ("Cold one, isn't it.", "That it is."),
    ("Anything new?", "Not much, no."),
    ("Long day.", "Isn't it always."),
    ("Busy morning?", "Busy enough."),
)
"""Small pools rather than one fixed line per band, cycled
deterministically by (agent ids, tick) — a fallback-only run (Ollama
disabled or unreachable) previously repeated the exact same 3 lines for
every pair forever, which read as an obvious, boring bug. See
docs/DECISIONS.md, "NPCs repeating dialogue" fix."""


def fallback_dialogue(agent_a: Agent, agent_b: Agent, affinity: float, tick: int = 0) -> dict:
    """Deterministic stand-in, varying by relationship band and cycled
    by tick so the same pair doesn't get the identical line every time —
    mirrors cognition.fallback_goal's approach, extended for variety."""
    if affinity <= RIVALRY_THRESHOLD:
        pool, sentiment = _TENSE_POOL, "tense"
    elif affinity >= 0.6:
        pool, sentiment = _WARM_POOL, "warm"
    else:
        pool, sentiment = _NEUTRAL_POOL, "neutral"
    line_a, line_b = pool[(agent_a.id + agent_b.id + tick) % len(pool)]
    return {
        "line_a": line_a.format(a=agent_a.name, b=agent_b.name),
        "line_b": line_b.format(a=agent_a.name, b=agent_b.name),
        "sentiment": sentiment, "rumor": "",
    }


_VALID_SENTIMENTS = {"warm", "tense", "neutral"}

_MAX_LINE_WORDS = 22
"""A line requested as "under 10 words" that comes back several times
longer is a sign a small/weak model rambled past the instruction rather
than writing a real line — see `_is_sane_line`."""

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
