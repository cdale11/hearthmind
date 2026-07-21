"""A single inhabitant: position, needs, lifecycle, and relationships.

Milestone 2 scope: agents have needs that decay and a resting/awake state
that responds to them, and they wander the walkable terrain (slice 1).
Phase A closes the loop M2-2 left open: agents now forage
(hearthmind/world/resources.py), age, can die of starvation or old age,
and can build affinity with nearby agents that leads to reproduction (see
docs/DECISIONS.md, A1-A3).
"""
from __future__ import annotations

import re
from enum import Enum

from hearthmind.agents.ledger import Ledger
from hearthmind.util import clamp

try:
    from hearthmind._native import EmotionState as _NativeEmotionState
    from hearthmind._native import decay_emotions as _native_decay_emotions
except ImportError:
    _NativeEmotionState = None
    _native_decay_emotions = None
"""Optional compiled fast path for `decay_emotions` below (Phase I,
see cpp/src/emotion_decay.cpp) — same "runs every tick, for every
agent, unconditionally" shape as module 6's `_update_needs`. `None`
when the extension wasn't built — falls back to the equivalent
pure-Python per-key multiply in that case."""


class AgentState(str, Enum):
    AWAKE = "awake"
    RESTING = "resting"


class AgentGoal(str, Enum):
    """A high-level intention set periodically (Phase B: once per sim-day,
    by the LLM cognition layer or its deterministic fallback) and executed
    deterministically every tick until re-evaluated. WANDER is both the
    default and the pre-Phase-B behavior, so agents with no goal set yet
    (or loaded from a pre-Phase-B save) behave exactly as before — see
    docs/DECISIONS.md, B2."""

    WANDER = "wander"
    FORAGE = "forage"
    SOCIALIZE = "socialize"
    REST = "rest"
    GATHER = "gather"
    """Added D8: collect building materials from forest/hills into the
    settlement's shared stockpile — see Population._maybe_gather."""
    SEEK_PERSON = "seek_person"
    """v0.87.8, "directed intent" (docs/IDEAS-2026-07-EMERGENCE.md §1) —
    unlike SOCIALIZE (nearest agent, no particular reason), this
    pathfinds to a SPECIFIC other agent (`Agent.seek_target_id`) for a
    stored reason (confront/console/confide, see `Population.
    _seek_person_candidate`) drawn from existing trust/secrets/emotion
    state. Core-cast-only in practice — only reachable via LLM
    cognition (`SimulationEngine._schedule_due_cognition`), never the
    deterministic fallback, so it's automatically bounded by `Config.
    llm_core_cast_size` the same way every other core-cast-gated
    decision is. On arrival (same tile as the target), the EXISTING
    colocated-dialogue mechanism (`Population.due_for_dialogue`) picks
    the pair up exactly like a SOCIALIZE-driven meeting — the intent
    reaches the dialogue prompt for free via `Agent.goal_reason`
    (`dialogue.py`'s `_activity` already surfaces it), so this needs no
    new dialogue-scheduling logic at all."""
    EXPLORE = "explore"
    """v0.87.45 exploration/surveyor batch: forced (like FORAGE for
    critical hunger) for any agent whose `occupation` is SURVEYOR,
    regardless of their assigned goal — see `Population._dispatch_
    movement`. Paths toward the nearest tile outside `Settlement.
    explored_tiles`, marking tiles explored (and recording notable
    findings) as the agent moves, whether walking this specific goal or
    not — see `Population._mark_explored`."""


# --- enum <-> int code maps for the native AgentStore (v0.75.0) -------------
# The native AgentTable stores `state`/`goal` as small ints; these are the
# single authoritative bijection between the enums and those codes. Kept
# here, next to the enums they encode, so agents/agent_store.py stays
# enum-free. cpp/src/agent_table.cpp's header documents the same codes —
# keep the three in sync (append new members at the end; never renumber an
# existing code, or a resumed native world would misread saved scalars).
STATE_TO_CODE: dict["AgentState", int] = {AgentState.AWAKE: 0, AgentState.RESTING: 1}
CODE_TO_STATE: dict[int, "AgentState"] = {v: k for k, v in STATE_TO_CODE.items()}

GOAL_TO_CODE: dict["AgentGoal", int] = {
    AgentGoal.WANDER: 0,
    AgentGoal.FORAGE: 1,
    AgentGoal.SOCIALIZE: 2,
    AgentGoal.REST: 3,
    AgentGoal.GATHER: 4,
    AgentGoal.SEEK_PERSON: 5,
    AgentGoal.EXPLORE: 6,
}
CODE_TO_GOAL: dict[int, "AgentGoal"] = {v: k for k, v in GOAL_TO_CODE.items()}


# Needs tuning. Kept as module constants rather than Config fields for now —
# these are behavioral parameters of the agent model itself, not world-shape
# parameters a deployer chooses at creation time. Revisit if that stops
# being true (e.g. once difficulty/pacing knobs are wanted).
HUNGER_RATE = 0.008
"""Hunger gained per tick, always (no food source yet to offset it).
Lowered from 0.01 (v0.87.24 starvation-collapse fix) — a live-diagnostic-
style soak showed population booming during a good stretch then
crashing hard (29 -> 2) once a food shortfall hit, largely because the
reactive food-seeking chain (FORAGE_HUNGER_THRESHOLD 0.4 for passive
tile-checking, SURVIVAL_HUNGER_THRESHOLD 0.6 for the deterministic
forced-FORAGE goal override, CRITICAL_HUNGER_THRESHOLD 0.9 for the
emergency wake) has little real-time margin at 0.01/tick — the gap
between "starting to worry" and "starving" is under 60 ticks. The 20%
slowdown widens every one of those reaction windows proportionally
without changing any threshold's meaning, giving the settlement-level
throttles (see CARRYING_CAPACITY_HUNGER_WEIGHT, REPRODUCTION_SETTLEMENT_
HUNGER_CEILING) and the granary buffer (GRANARY_CAPACITY) more real time
to actually engage before a bad patch compounds into a crash."""

ENERGY_DRAIN_AWAKE = 0.015
"""Energy lost per tick while awake (whether moving or not)."""

ENERGY_RECOVERY_RESTING = 0.06
"""Energy gained per tick while resting."""

REST_THRESHOLD = 0.2
"""Energy at or below which an awake agent falls asleep."""

WAKE_THRESHOLD = 0.85
"""Energy at or above which a resting agent wakes up."""

MOVE_CHANCE = 0.5
"""Per-tick probability an awake agent wanders to an adjacent tile."""

# --- Phase A: foraging, lifecycle, relationships ---------------------------

FORAGE_HUNGER_THRESHOLD = 0.4
"""Hunger at or above which an agent will forage if food is available —
regardless of awake/resting state, see docs/DECISIONS.md, D3."""

CRITICAL_HUNGER_THRESHOLD = 0.9
"""Hunger at or above which a resting agent wakes immediately, and a goal
of REST is overridden for the tick, so a starving agent isn't trapped
asleep while unable to reach food. Deliberately below
STARVATION_HUNGER_THRESHOLD (0.95) so the emergency wake fires before the
starvation-death countdown even begins. See docs/DECISIONS.md, D3."""

FORAGE_AMOUNT = 0.2
"""Units consumed from a resource node per successful forage attempt."""

FORAGE_HUNGER_RELIEF = 0.3
"""Hunger relief for a full (FORAGE_AMOUNT-sized) successful forage; scales
down proportionally if the node had less than FORAGE_AMOUNT remaining."""

MIN_LIFESPAN_TICKS = 20_000
MAX_LIFESPAN_TICKS = 40_000
"""Per-agent lifespan, assigned at spawn. An abstraction of "vitality"
rather than literal years — tunable, see docs/DECISIONS.md, A2."""

STARVATION_HUNGER_THRESHOLD = 0.95
STARVATION_TICKS_TO_DEATH = 280
"""Consecutive ticks at/above STARVATION_HUNGER_THRESHOLD before death.
Raised from 200 (v0.87.24 starvation-collapse fix, alongside HUNGER_
RATE's slowdown above) — more grace period for a genuinely desperate
agent to reach a food source (or for a settlement-wide famine to
resolve) before death becomes irreversible, without weakening
starvation as a real consequence: a resilient agent (TRAIT_RESILIENCE_
STARVATION_TOLERANCE_INFLUENCE) can already stretch this further, this
just raises the base everyone gets."""

MATURITY_TICKS = 4_000
"""Age at which an agent becomes eligible to reproduce."""

RELATIONSHIP_GAIN_PER_TICK_COLOCATED = 0.02
RELATIONSHIP_DECAY_PER_TICK = 0.0005
"""Pulls a relationship value toward 0 (neither affinity nor rivalry)
from whichever side it's on — see Population._update_relationships.
Relationship values range -1..1 as of E2 (previously 0..1): a dialogue
exchange (see hearthmind/llm/dialogue.py) can now push a pair into
rivalry, not just toward friendship."""
REPRODUCTION_AFFINITY_THRESHOLD = 0.6
REPRODUCTION_CHANCE_PER_TICK = 0.01
"""Rolled only for mature, healthy, colocated pairs above the affinity
threshold — see Population._maybe_reproduce."""

REPRODUCTION_WELLFED_HUNGER = 0.35
"""The surplus gate's fallback arm: a pair with no personal food saved
can still have a child if both are clearly well-fed (hunger at or
below this — much stricter than _is_healthy's 0.7 ceiling). See
Population._maybe_reproduce and the July 2026 architecture review's
carrying-capacity rework: children follow surplus, so demography is
coupled to the food economy instead of only to a hard population cap.
Kept as an OR with the personal-food arm so a brand-new world (nobody
has saved food yet — the inventory skim needs farms/granaries to
exist first) can still grow off a good foraging stretch."""

REPRODUCTION_SETTLEMENT_HUNGER_CEILING = 0.45
"""Hard birth-rate backstop (v0.87.24 starvation-collapse fix): no
reproduction at all while the settlement's own average member hunger
is at/above this, regardless of the reproducing pair's own state. The
pre-existing surplus gate above only reads the two parents — a couple
that happened to just eat could still add a mouth to feed to a
settlement that is, in aggregate, already visibly starving. Set above
REPRODUCTION_WELLFED_HUNGER (0.35, a per-couple bar) since this is a
community-wide crisis threshold, not an individual one — see
Population.carrying_capacity's CARRYING_CAPACITY_HUNGER_WEIGHT for the
softer, continuous throttle this backstops. Tightened from an initial
0.55 (measurably too loose — see that constant's docstring) to 0.45."""

RIVALRY_THRESHOLD = -0.4
"""Relationship value at or below which a pair is considered rivals for
prompt-context/diagnostic purposes — see hearthmind/llm/dialogue.py."""

DIALOGUE_COOLDOWN_TICKS = 300
"""Minimum ticks between two agents having another LLM-authored dialogue
exchange — keeps a stable pair that's colocated for a long stretch from
generating a new exchange (and LLM call) every tick. See
docs/DECISIONS.md, E2."""

DIALOGUE_TOPICS_RING_MAX = 3
"""Cap on `Population.dialogue_topics`'s per-pair ring — v0.87.12
"dialogue novelty memory" (docs/IDEAS-2026-07-EMERGENCE.md §7). Small
on purpose: this is "what did we just talk about," not a transcript."""

TRIGGERED_COGNITION_COOLDOWN_TICKS = 200
"""Minimum ticks between two event-triggered (not staggered-daily)
cognition calls for the same agent — a hunger emergency or fresh grief
gets one immediate LLM re-reasoning, not one every tick for as long as
the condition persists. Shorter than DIALOGUE_COOLDOWN_TICKS since these
are individually rarer events, not a routine per-pair interaction. See
Population.due_for_triggered_cognition, docs/DECISIONS.md, "cognition
triggers beyond daily cadence" pass."""

DIALOGUE_SENTIMENT_DELTA = {"warm": 0.05, "tense": -0.05, "neutral": 0.0}
"""Relationship nudge applied when a dialogue exchange resolves, on top
of the passive per-tick colocation gain — the LLM's read on how the
exchange went, distinct from mere proximity. See
Population.apply_dialogue, docs/DECISIONS.md, E2."""

TRUST_DELTA = {"warm": 0.03, "tense": -0.04, "neutral": 0.0}
"""Agent.trust nudge applied alongside DIALOGUE_SENTIMENT_DELTA — smaller
magnitude and asymmetric (tense conversations cost more trust than warm
ones earn) since credibility is easier to lose than build, same
real-world asymmetry as reputation. Distinct axis from `relationships`:
see Agent.trust's docstring."""

TRUST_SKEPTICISM_THRESHOLD = -0.15
"""Below this, a rumor from that source is remembered with visible
skepticism instead of at face value — see Population.apply_dialogue."""

DIALOGUE_MISUNDERSTANDING_TRUST_PENALTY = 0.06
"""Phase 2 ("dialogue as a simulation event"): applied to BOTH
directions of trust when an exchange's `misunderstanding` outcome
fires — on top of, not instead of, the ordinary TRUST_DELTA sentiment
nudge (a misunderstanding can happen within an otherwise warm
exchange). Deliberately smaller than TRUST_DELTA's tense penalty —
being confused about something is a lighter hit to credibility than an
openly tense exchange."""

PERSONAL_FOOD_CAPACITY = 0.6
"""Max `Agent.inventory["food"]` — a small personal reserve, deliberately
far below granary/farm scale (GRANARY_CAPACITY 15.0), since this is one
person's pocket, not a storehouse. First slice of the "per-agent
inventory" gap CLAUDE.md flags as a real, genuinely large not-yet-built
item — scoped here to a single good (food) and direct agent-to-agent
transfer, not a full multi-good economy/market. See
docs/DECISIONS.md, "per-agent inventory and trade" pass."""

FORAGE_INVENTORY_SKIM = 0.05
"""Food stashed into `Agent.inventory["food"]` (capped at
PERSONAL_FOOD_CAPACITY) alongside a successful farm-harvest or
granary-withdrawal forage — deliberately not from wild foraging or an
emergency currency purchase, both of which are scarcity-driven with
nothing spare to set aside. See Population._maybe_forage."""

TRADE_FOOD_AMOUNT = 0.2
"""Personal food transferred in one barter exchange — matches
FORAGE_AMOUNT's scale. See Population._maybe_trade_food."""

TRADE_HUNGER_RELIEF = 0.25
"""Hunger relief for the receiving agent in a full trade — between a
wild forage (FORAGE_HUNGER_RELIEF 0.3) and a granary withdrawal
(GRANARY_HUNGER_RELIEF 0.4), since this is one neighbor's spare food,
not a communal store."""

TRADE_RELATIONSHIP_BOOST = 0.03
"""Relationship nudge for both parties when a trade completes — smaller
than DIALOGUE_SENTIMENT_DELTA's warm nudge (0.05): a material kindness,
not a conversation, but still a real bond-building act."""

TRADE_MIN_RELATIONSHIP = -0.2
"""An agent won't share personal food with someone at or below this
relationship value — rivals don't get fed first, though this is well
above RIVALRY_THRESHOLD (-0.4) so mere strangers (relationship 0) still
trade freely."""

TRAIT_SOCIABILITY_TRADE_THRESHOLD_SHIFT = 0.15
"""Integration milestone: a giver's own sociability shifts the
TRADE_MIN_RELATIONSHIP bar they personally apply, in
`Population._trade_relationship_threshold` (consumed by all three
barter functions — food/tools/medicine). A sociable giver shares with
even a mildly-disliked neighbor; an unsociable one holds out for a
closer bond than the settlement-wide default. Closes TRAIT_SOCIABILITY's
write-only loop the same way TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE
does for teaching, just as a threshold shift rather than a chance
multiplier since trade here is deterministic-on-colocation, not a
per-tick roll."""

TRADE_TOOLS_AMOUNT = 1.0
"""H4: personal tools transferred in one barter exchange — see
Population._maybe_trade_tools. Chunkier than TRADE_FOOD_AMOUNT since
tools are a durable, lower-frequency good, not consumed on use."""

TRADE_MEDICINE_AMOUNT = 0.5
"""H4 extension: personal medicine transferred in one barter exchange —
see Population._maybe_trade_medicine. Between TRADE_FOOD_AMOUNT and
TRADE_TOOLS_AMOUNT in scale: medicine is consumed over a bout of
illness (not durable like tools), but a single dose is still a
meaningful share of MEDICINE_CAPACITY."""

GATHER_TOOLS_YIELD_BONUS = 0.4
"""H4: a GATHER-goal agent's own tools stretch what they bring back —
up to +40% materials per gather at a full personal tools stash
(TOOLS_CAPACITY), scaled linearly. Higher than SKILL_FARMING_YIELD_
BONUS (25%) since a physical tool is a more direct force-multiplier on
raw extraction than accumulated technique alone — the two are
deliberately distinct levers (skill from practice/teaching, tools from
the crafting supply chain) that could eventually stack for the same
goal. See Population._maybe_gather."""

ELDER_AGE_FRACTION = 0.8
ELDER_RECOVERY_MULTIPLIER = 0.7
"""Past ELDER_AGE_FRACTION of their own max_age_ticks, an agent's
resting energy recovery is multiplied by ELDER_RECOVERY_MULTIPLIER —
age-graded frailty, so an elder rests longer and does visibly less in
their final season instead of being indistinguishable from an adult
until the tick they die (death was a pure cliff at max_age_ticks; the
July 2026 architecture review flagged the missing decline). Recovery
rather than drain so a sheltered, cared-for elder still gets by —
they're slower, not doomed. See Population._update_needs."""

MAX_CORE_MEMORIES = 5
"""v0.87.16, "deepen long-term historical identity" (explicit user
direction): a small, separate tier a memory graduates INTO when it's
evicted from the churning `memories` list but was genuinely major (see
`Population._remember`'s eviction branch) — a flood, a famine, an old
leader, a settlement split, a death — instead of just vanishing into
the durable disk-only log nothing ever reads back. Distinct from
`semantic_memories` (an LLM-DISTILLED lasting theory, "I don't trust
the river since the flood") — this is the concrete EVENT text itself,
still first-person and specific, meant to resurface verbatim years
later ("the flood of that spring") the way `agent_memory_log` already
preserves durably but never fed back into a prompt until now. Kept
small — this is "a handful of things that mattered," not a second
memory store to manage."""

MAX_AGENT_MEMORIES = 8
"""Cap on Agent.memories — a short-term personal log (bond formed, rumor
heard, a bonded partner's death), not a full diary. See docs/
DECISIONS.md, relationship-memory pass. Eviction policy: see
MEMORY_SALIENCE_BASELINE below (Phase I, v0.76.3) — no longer strict
FIFO."""

MEMORY_SALIENCE_BASELINE = 0.2
MEMORY_SALIENCE_EMOTION_WEIGHT = 0.7
"""Phase I "layered memory v1" (docs/VISION-2026-07.md): each memory
gets a salience score, computed once at write time from the agent's
`emotions` in that moment (`salience = clamp(BASELINE + sum(emotions.
values()) * EMOTION_WEIGHT, BASELINE, 1.0)`) and stored alongside it in
`Agent.memory_salience` (index-aligned with `Agent.memories`, maintained
solely by `agents/population.py`'s `_remember` — the only place that
ever mutates `memories`). Eviction at `MAX_AGENT_MEMORIES` now drops the
LOWEST-salience entry (ties toward the oldest index) instead of always
the oldest — a routine "quiet day" memory formed with no notable
emotion (salience 0.2) is forgotten before a memory formed during real
fear/grief/joy/anger (up to salience 1.0) is, even if the mundane one
is more recent. This is the actual "layered" mechanism: memorable
experiences genuinely outlast unremarkable ones, not just a FIFO queue
with a fancier name."""

MEMORY_REPETITION_DAMPING = 0.6
MEMORY_REPETITION_OVERLAP_THRESHOLD = 3
"""v0.87.16, "improve memory weighting" (explicit user direction): a
newly-formed memory whose text shares at least `MEMORY_REPETITION_
OVERLAP_THRESHOLD` meaningful (`_overlap_tokens`) words with ANY of
the agent's current `memories` is treated as a repeat of something
already lived through, not a fresh experience — its computed salience
is multiplied by `MEMORY_REPETITION_DAMPING` before storage. This is
the concrete "novelty/repetition" half of the ask: a routine event
that keeps recurring in near-identical phrasing (the same kind of
weather-flavored small talk, the same trade-thanks line) now fades
faster than something that happened once and stands out. Checked
against the FULL current `memories` list (not just the newest few) so
a repeated pattern spread across the whole 8-slot window still gets
caught, not only back-to-back repeats."""

MEMORY_FADE_DECAY_PER_DAY = 0.985
"""Deferred item 4 of docs/VISION-2026-07-LEARNING.md, "gradual
forgetting as a genuinely continuous fade": once/sim-day (`day_end`,
`Population.decay_memory_salience`), every entry in `Agent.memory_
salience` is multiplied by this factor (floored at `MEMORY_FADE_
FLOOR`). Distinct from the existing salience-ranked hard eviction at
`MAX_AGENT_MEMORIES` and the occasional LLM-authored `memory_drift`
(v0.87.0) — this is a third, purely deterministic mechanism: even a
memory that never gets evicted or drifted still slowly reads as less
sharp the longer it sits unrefreshed, the same way a real memory a
person never actively revisits fades before one they keep retelling.
0.985/day compounds to ~0.20 (an unremarkable salience-0.2 memory
reaches `MEMORY_FADE_FLOOR`) after about 90 days and ~0.20 of a vivid
salience-1.0 memory after roughly a year — slow enough that a genuinely
distinctive memory stays vivid for a long time, fast enough that a
routine memory that somehow survives eviction still visibly fades
within a season. Chosen by feel (no live diagnostic drives this one,
unlike most constants in this project) since there's no "correct"
real-world forgetting curve to measure against; retune if a live run
shows fading feels too fast/slow."""

MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD = 0.75
MEMORY_MAJOR_EVENT_DECAY_PER_DAY = 0.999
"""v0.87.16, "improve memory weighting — major life events should
remain influential for years" (explicit user direction): a memory
already at or above `MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD` when a
day's decay applies uses this much slower rate instead of the
ordinary `MEMORY_FADE_DECAY_PER_DAY` — 0.999/day compounds to ~0.69
after a full year (365 days) vs. ~0.004 for an ordinary vivid memory
at the standard rate, a genuinely multi-year difference rather than
everything converging to the same few-month fade. A memory decays
using WHICHEVER rate its CURRENT salience qualifies for each day
(checked fresh every call, not locked in at formation) — so a memory
that started merely vivid but never dropped below the threshold keeps
the slow rate, while one that fades below it partway through switches
to the ordinary rate for its remaining life, same "graceful
degradation" shape the rest of this system uses."""

MEMORY_FADE_FLOOR = 0.05
"""Floor `decay_memory_salience` never decays a memory's salience below
— a memory that's still occupying a `memories` slot (hasn't been
evicted) is still a real memory, just a hazy one; it should never read
as literally zero-confidence."""

MEMORY_FADE_DISPLAY_THRESHOLD = 0.25
"""Below this salience, `faded_memory_text` wraps a memory's text with
a hazier phrasing when it's read back into an LLM prompt (cognition/
dialogue's "You remember: ..." line) — the fade is meant to be felt by
the LLM (and therefore visible in NPC behavior/dialogue), not just a
number nobody reads. Set below `MEMORY_SALIENCE_BASELINE` (0.2 is the
starting salience for an emotionless "quiet day" memory) so a fresh
mundane memory doesn't immediately read as faded; a memory needs
several days of decay (or started already-low) to cross it."""


_OVERLAP_STOPWORDS = frozenset({
    "the", "a", "an", "i", "my", "me", "and", "to", "of", "in", "on", "at", "it",
    "was", "is", "were", "for", "with", "that", "this", "after", "when", "we",
    "us", "our", "they", "them", "their", "not", "but", "so", "as", "be", "been",
})
"""Tiny hardcoded stopword list for `_overlap_tokens` — not meant to be
linguistically complete, just enough to keep filler words from
counting as a topical match. Originally lived in simulation/engine.py
(deferred item 2, `_matching_lesson`'s keyword-overlap fallback);
moved here in v0.87.14 so `retrieve_relevant_memories` below can share
the same tokenizer without an engine->agent import inversion."""


def _overlap_tokens(text: str) -> set[str]:
    """Lowercased, stopword-filtered, 3+ letter word set for a cheap
    keyword-overlap comparison — deliberately not real NLP (no stemming/
    lemmatization), matching this project's stdlib-first, no-new-
    dependency posture."""
    return {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 2 and w not in _OVERLAP_STOPWORDS}


MEMORY_RETRIEVAL_RECENCY_WEIGHT = 0.5
MEMORY_RETRIEVAL_SALIENCE_WEIGHT = 0.3
MEMORY_RETRIEVAL_RELEVANCE_WEIGHT = 0.5
MEMORY_RETRIEVAL_CAUSAL_BONUS = 0.15
"""v0.87.14 "adaptive retrieval layer" (docs/IDEAS-2026-07-EMERGENCE.md
§7): weights for `retrieve_relevant_memories`'s scoring — recency and
relevance are roughly equal top priorities (a fixed recency-only slice
was the whole problem this item names: "the three most recent
memories reach cognition even when a ten-year-old high-salience
memory is the relevant one"), salience a real but smaller signal
(already used for eviction, not meant to double-count too heavily
here), and a modest bonus for a memory carrying a known causal tag
(v0.87.14 "causal memory links," see `Agent.memory_causes`) — a memory
that's part of a known cause-and-effect chain is a little more worth
surfacing than an equally-scored isolated one. Deliberately no
embeddings/new dependency — relevance is cheap keyword overlap via
`_overlap_tokens`, same posture as `_matching_lesson`'s existing
fallback."""


def retrieve_relevant_memories(
    agent: "Agent", k: int, context: str = "",
) -> list[tuple[str, float, str]]:
    """Adaptive retrieval (v0.87.14, docs/IDEAS-2026-07-EMERGENCE.md §7
    "Adaptive retrieval layer"): scores every stored memory by recency,
    salience, keyword-overlap relevance to `context` (typically the
    agent's own freshest `working_memory` entry — "what just
    happened"), and a small bonus for a known causal link, returning
    the top `k` — same prompt-slot BUDGET as the old fixed `memories[
    -k:]` slice (bounded prompt size is preserved), but the content now
    earns its place instead of just being newest. Falls back to
    returning everything (still capped at k by the `n <= k` early
    return) when there are k or fewer memories, or scores purely on
    recency+salience+causal-bonus when `context` is blank (no text to
    compare relevance against) — never worse than the old behavior in
    the degenerate case. Result order is restored to chronological
    (oldest-of-the-selected first) for readability, matching what the
    old slice already read like."""
    n = len(agent.memories)
    causes = agent.memory_causes
    if n <= k:
        return [
            (agent.memories[i], agent.memory_salience[i] if i < len(agent.memory_salience) else 0.0,
             causes[i] if i < len(causes) else "")
            for i in range(n)
        ]
    context_tokens = _overlap_tokens(context) if context else set()
    scored: list[tuple[float, int]] = []
    for i in range(n):
        text = agent.memories[i]
        salience = agent.memory_salience[i] if i < len(agent.memory_salience) else 0.0
        because = causes[i] if i < len(causes) else ""
        recency = i / (n - 1)
        relevance = 0.0
        if context_tokens:
            overlap = len(context_tokens & _overlap_tokens(text))
            relevance = min(1.0, overlap / 2.0)
        score = (
            MEMORY_RETRIEVAL_RECENCY_WEIGHT * recency
            + MEMORY_RETRIEVAL_SALIENCE_WEIGHT * salience
            + MEMORY_RETRIEVAL_RELEVANCE_WEIGHT * relevance
            + (MEMORY_RETRIEVAL_CAUSAL_BONUS if because else 0.0)
        )
        scored.append((score, i))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    top_indices = sorted(i for _, i in scored[:k])
    _retrieval_stats["calls"] += 1
    naive_indices = set(range(n - k, n))
    if set(top_indices) != naive_indices:
        _retrieval_stats["diverged_from_recency"] += 1
    return [
        (agent.memories[i], agent.memory_salience[i] if i < len(agent.memory_salience) else 0.0,
         causes[i] if i < len(causes) else "")
        for i in top_indices
    ]


_retrieval_stats = {"calls": 0, "diverged_from_recency": 0}
"""v0.87.14 retrieval-hit diagnostic (docs/IDEAS-2026-07-EMERGENCE.md
§7 explicitly asked for this: "does retrieval beat recency? — measured,
not assumed"). `diverged_from_recency` counts calls where the scored
top-k picked at least one memory a plain `memories[-k:]` slice would
NOT have — the only observable signal available without ground truth
on which memory was "actually" more relevant. Read via
`retrieval_diagnostics()`, surfaced at `/diagnostics`."""


def retrieval_diagnostics() -> dict:
    """Snapshot of `_retrieval_stats` plus the derived hit rate — 0 calls
    reads as 0.0 rate, not a divide-by-zero."""
    calls = _retrieval_stats["calls"]
    diverged = _retrieval_stats["diverged_from_recency"]
    return {
        "calls": calls,
        "diverged_from_recency": diverged,
        "divergence_rate": round(diverged / calls, 4) if calls else 0.0,
    }


def faded_memory_text(text: str, salience: float) -> str:
    """Wraps `text` with a hazier framing once its salience has decayed
    below `MEMORY_FADE_DISPLAY_THRESHOLD` — a clear memory reads as
    itself, a faded one is marked as hazy, changing how the memory
    reads to the LLM without altering the underlying stored text (the
    original stays exact in `Agent.memories` for `memory_drift`/UI
    history — only the prompt-facing copy is reworded). Deliberately
    not itself an LLM call (deferred item 4 explicitly scopes this as
    the deterministic half of "gradual forgetting"; item 5's
    LLM-authored skill-mastery narration is the batch's one new call).

    Live audit finding (P1.1): the original "I only vaguely recall: X"
    framing read as literal first-person speech, so a small model
    routinely quoted it verbatim in dialogue ("Yeah, I only vaguely
    recall Bartholomew was born to us") and even laundered it into
    rumor text — a narrator's note about vividness leaking into the
    fiction as something a villager would actually say. The
    parenthetical `(a hazy memory)` framing reads as an aside about the
    memory, not a sentence to repeat."""
    if salience >= MEMORY_FADE_DISPLAY_THRESHOLD:
        return text
    lowered = text[0].lower() + text[1:] if text else text
    return f"(a hazy memory) {lowered}"


ROUTINE_MEMORY_SALIENCE_MULT = 0.5
"""Multiplier `_remember(..., routine=True)` applies to a memory's
computed salience — used for high-frequency, low-narrative-interest
events (today: `_maybe_trade_food`/`_maybe_trade_tools`/`_maybe_trade_
medicine`'s "X shared food/tools/medicine with me", which can recur
every hunger cycle for an agent leaning on neighbors, far more often
than any other memory kind) so it's evicted from the salience-ranked
`MAX_AGENT_MEMORIES` cap before a rarer, more distinctive memory is,
and — the bigger effect — never occupies the strictly-FIFO `working_
memory` slot at all (see WORKING_MEMORY_MAX below), so dialogue/
cognition's "just now" line isn't dominated by routine barter instead
of whatever's actually distinctive. Fixes a live report that NPC
dialogue kept gravitating to food-sharing regardless of what else was
happening: `just_now_text` always reads the single freshest working_
memory entry, and food-sharing was frequent enough to usually BE that
entry. A routine memory is still recorded (nothing is hidden), just
deprioritized."""

WORKING_MEMORY_MAX = 2
"""Cap on `Agent.working_memory` — a second, much smaller buffer written
alongside `memories` at every `_remember` call, but strictly FIFO
(never salience-weighted). This is the vision's "fast, working" layer
distinct from "episodic": once salience-weighted eviction can drop a
recent-but-mundane memory in favor of an older-but-memorable one (see
MEMORY_SALIENCE_BASELINE above), `agent.memories[-1]` is no longer
guaranteed to be "the literal last thing that happened" — working_
memory is. Consumed by `llm/cognition.py`/`llm/dialogue.py` as a "just
now" grounding line, shown only when it isn't already present in the
episodic slice being read (avoids a duplicated sentence in the common
case where the most recent event was memorable enough to survive
eviction too)."""

MAX_SEMANTIC_MEMORIES = 3
"""Cap on `Agent.semantic_memories` — Phase J's third memory layer
(docs/VISION-2026-07.md, "Deeper Minds": "Reflect()... writes 1 semantic
memory ('I have come to think…')"). Unlike `memories` (a short log of
individual events) or `working_memory` (the single freshest event), a
semantic memory is a *condensed* lasting belief-about-self distilled
from several episodic memories at once — "I don't trust the water since
the flood" rather than a list of separate flood/drought/harvest entries.
Written only by `SimulationEngine._maybe_schedule_personal_belief`
(v0.78.0: extended into a full Reflect() alongside its existing personal
belief output — one LLM call now produces both, no added call volume),
strictly FIFO (oldest evicted first — a stale abstraction is superseded
by forming a new one, there is no salience contest between them). Small
and capped deliberately: this is meant to be a handful of load-bearing
self-theories a prompt can always afford to include in full, not a
second episodic log."""

MAX_SECRETS = 2
"""Cap on `Agent.secrets` — Phase J's "Secrets & lies" piece
(docs/VISION-2026-07.md, "Deeper Minds": "planted by Reflect()/
disputes; dialogue prompt may reference or guard them"). Deliberately
tiny and FIFO: this is a handful of private grievances/held-back
things, not a growing diary. Planted two ways: a hardened "feud"
dispute outcome (`SimulationEngine._maybe_schedule_dispute`, v0.78.3 —
a deterministic derivation from the existing outcome/narration, zero
added call volume/schema risk), and (v0.78.4) an occasional Reflect()
answer (`SimulationEngine._maybe_schedule_personal_belief` /
`llm/beliefs.py`'s extended personal-belief job) — the LLM's own optional
`"secret"` field, left blank most calls, reusing that job's existing
monthly call slot rather than adding a new one. Both paths are core-cast
only. `dialogue.py`'s prompt may allude to a speaker's secret about
their conversation partner without stating its contents outright —
never surfaced in the main UI (a "secret" spoiled in the NPC inspector
defeats the point); reachable via the dev console/raw `/state` JSON
like every other under-the-hood mechanism."""

DEATHBED_SECRET_HEIR_CHANCE = 0.3
"""v0.87.6, "deathbed release of secrets" (docs/IDEAS-2026-07-
EMERGENCE.md §1): a kept secret currently just dies with its holder.
On death, `Population._apply_inheritance` (the same heir-resolution
H7 already does for goods/skill/bias) may pass the deceased's freshest
secret to their chosen heir, attributed to the deathbed rather than
the original confidant — the heir learns it was said, not who (if
anyone) already knew. Not guaranteed: secrets are meant to stay mostly
private, so this is a real chance, not every death. Zero LLM cost."""

DEATHBED_SECRET_RUMOR_CHANCE = 0.4
"""Given a deathbed secret already released to an heir (see
DEATHBED_SECRET_HEIR_CHANCE), the further chance it also slips out as
a vague rumor via the existing `Population.spread_rumor` machinery
(no LLM call) — "on their deathbed, X spoke of something long kept
quiet," never the secret's actual contents, so eavesdroppers gain
intrigue without the secret itself becoming common knowledge. Secrets
then have a real lifecycle: planted (Reflect()/disputes) -> guarded in
dialogue -> leaked at death -> distorted by InterpretRumor() -> maybe
condensed into folklore a generation later."""

DEATHBED_SECRET_RUMOR_LISTENER_COUNT = 2
"""How many nearby agents hear the vague deathbed rumor (see
DEATHBED_SECRET_RUMOR_CHANCE) — deliberately small, matching the scale
of an intimate deathbed moment rather than a settlement-wide
announcement (contrast `caravan.CARAVAN_RUMOR_LISTENER_COUNT`, a
public arrival)."""

MAX_LESSONS = 4
"""Cap on `Agent.lessons` — v0.87.0, "learns like a human." A lesson is
`{"situation": str, "text": str, "formed_tick": int}`: a short, tagged
takeaway the agent draws from a specific kind of lived experience
("hunger", "conflict", "grief", "danger", "social"), distinct from
`semantic_memories` (a general self-theory) and `beliefs` (a theory
about someone/something else) — a lesson is specifically indexed by
*when it applies*, so cognition/dialogue can surface the one lesson
that matches the agent's CURRENT situation instead of only ever
reading the newest memory regardless of relevance ("smarter recall,
not just storage"). Written by extending the existing Reflect() job
(`SimulationEngine._maybe_schedule_personal_belief`) — zero added LLM
call volume, same discipline `semantic_memories`/`life_digest` already
established. Small and capped: evicts the oldest entry sharing the
*same* situation tag first (a fresher lesson about hunger supersedes an
older one about hunger), falling back to the globally oldest only if no
same-situation entry exists — so the cap doesn't let one situation
crowd out all the others."""

MAX_MIND_TEXT_CHARS = 220
"""Length cap on `Agent.mind` — Phase J's "persistent mind schema"
(docs/VISION-2026-07.md, "Deeper Minds"), scoped down to its
**permanent** tier only (v0.78.4, explicit user direction): a short,
one-time-authored paragraph of durable identity — values, fears,
ambitions, worldview — distinct from both the bounded numeric `traits`
vector and any single episodic/semantic memory. Authored exactly once,
when an agent enters the core cast (`Population.maintain_core_cast`),
never revised afterward — this is who they fundamentally are, not a
running theory. Set synchronously to a deterministic template
(`describe_mind_fallback`) the instant they join, then optionally
overwritten by a one-time background LLM call
(`SimulationEngine._maybe_author_mind`) if one succeeds — the same
"instant placeholder, LLM silently improves it later" pattern
`World.tick()`'s settlement-naming job already uses. Non-core agents
never get one (empty string) — a deliberate scope cut vs. the vision
doc's "non-core agents get a cheap deterministic template from traits"
line: `describe_traits` already serves that purpose inline wherever
needed, so no second templated string is stored per non-core agent.
The vision's "slow" (ideology) and "fast" (current preoccupation) tiers
are **not** separate new fields this round — explicit scope decision:
`traits`' slow bounded-random-walk drift already is the slow layer,
and `goal_reason`/`working_memory` already are the fast layer: building
distinct parallel state for those would duplicate existing mechanisms
and, for "slow," imply a new *recurring* LLM job — real added call
volume this project is explicitly trying to hold flat. Revisit only on
a fresh, explicit ask."""

MAX_VOICE_TEXT_CHARS = 100
"""Length cap on `Agent.voice` — v0.87.12 "per-agent voice" (docs/
IDEAS-2026-07-EMERGENCE.md §7). Much shorter than `MAX_MIND_TEXT_CHARS`
on purpose: this is a single manner-of-speaking tag (cadence, a
favorite figure of speech, a verbal habit), not a paragraph. Authored
once, at the same genesis moment as `mind` (`llm/mind.py`'s widened
schema), never revised — same one-time-permanent shape as `mind`."""

GRIEF_ENERGY_PENALTY = 0.2
"""Energy lost when a close bond (affinity >= REPRODUCTION_AFFINITY_THRESHOLD)
dies — grief has a real cost, not just a memory entry. See
Population._apply_deaths."""

INHERITANCE_SKILL_TRANSFER_FRACTION = 0.5
"""H7 (docs/ROADMAP.md "Phase H"): on death, an heir's skill closes half
the gap toward the deceased's — "a last lesson," not a full transfer
(skill is procedural; it can't simply be copied the way a possession
can, only accelerated by whatever notes/technique are left behind). A
no-op if the heir was already equally or more skilled. See
Population._apply_inheritance."""

INHERITANCE_BIAS_THRESHOLD = -0.3
INHERITANCE_BIAS_TRANSFER_FRACTION = 0.4
"""H7: a deceased agent's strong distrust of someone still living
(trust <= INHERITANCE_BIAS_THRESHOLD) partially carries over to their
heir — the heir's own trust in that person steps 40% of the way toward
the deceased's, a real "inherited grudge/bias" rather than pure
narration. Deliberately one-directional (only carries negative bias,
not positive trust) — a family's caution about someone is the more
mechanically interesting inheritance to model first; warm trust
already has its own accrual path through the heir's own dialogue."""

INHERITANCE_LESSON_CHANCE = 0.5
"""Deferred item 3 (docs/VISION-2026-07-LEARNING.md), "cross-
generational lesson inheritance": chance the deceased's freshest
`Agent.lessons` entry passes to their heir on death (`Population.
_apply_inheritance`), attributed ("X used to say: ...") rather than
claimed as the heir's own. Deliberately not guaranteed — same "a lesson
is exactly the kind of thing that can get lost between generations"
imperfection this deferred item asked for, distinct from the
unconditional home/goods transfer above it. A no-op when the deceased
had no lessons to pass on (the common case for a non-core-cast agent,
since `lessons` are currently only LLM-authored for the core cast plus
the two deterministic template triggers from item 1)."""

POPULATION_CAP = 400
"""Fallback safety valve when map area isn't available to `carrying_
capacity()` (e.g. a caller that doesn't pass `map_tiles` — see
`dynamic_population_cap`). A pure safety valve, not the binding
constraint: the July 2026 architecture review measured every run
pinning at the old 200 indefinitely (food was post-scarce, so nothing
else ever pushed back). With the carrying-capacity rework — goal-gated
planting, crop rot (FARM_ROT_TICKS), and surplus-gated reproduction
(REPRODUCTION_WELLFED_HUNGER) — population is meant to be limited by
the food economy; this cap only guards against a pathological runaway.
Raised rather than removed so a tuning mistake in the new food loop
can't take the process down. See docs/DECISIONS.md, A2 and the
architecture-review implementation pass."""

POPULATION_DENSITY_PER_TILE = 0.1
"""Live report finding: a flat `POPULATION_CAP=400` regardless of map
size meant a settlement that filled a large map with housing (1590
standing structures observed live) hit the SAME hard ceiling a tiny
map would — the safety valve had quietly become the binding constraint
again, just at a higher number, exactly the bug class `POPULATION_CAP`
itself was raised to fix in the first place. `dynamic_population_cap`
scales the ceiling with map area instead: ~1 person per 10 tiles,
chosen so the default 64x64 map (4096 tiles) yields ~410 — close to
the old flat default, so existing tuning/expectations at default map
size carry over almost exactly, while a larger map gets real headroom
to support what it can actually build."""

POPULATION_CAP_FLOOR = 100
"""`dynamic_population_cap`'s floor — even a small map keeps a
minimum-viable-colony ceiling rather than being squeezed by density
scaling alone."""

POPULATION_CAP_CEILING = 3000
"""`dynamic_population_cap`'s ceiling — still a genuine safety valve
against a pathological runaway on a very large map; at the measured
~85ms/tick p50 for a 400-population world against a 1000ms tick
budget, there's real headroom above the old flat 400, but this stays a
real bound, not "whatever the map allows.\""""


def dynamic_population_cap(map_tiles: int | None) -> float:
    """Map-area-scaled population ceiling — see `POPULATION_DENSITY_
    PER_TILE`'s docstring for the live-reported bug this closes.
    `map_tiles` is `Config.width * Config.height`; `None` (a caller
    that hasn't been updated to pass map area) falls back to the flat
    `POPULATION_CAP`, unchanged from before this existed."""
    if not map_tiles:
        return float(POPULATION_CAP)
    return clamp(map_tiles * POPULATION_DENSITY_PER_TILE, POPULATION_CAP_FLOOR, POPULATION_CAP_CEILING)

OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK = 1e-7
"""Background per-agent-tick chance of a single spontaneous illness case
appearing (Population._maybe_outbreak rolls this once per tick, scaled by
current population and doubled by OUTBREAK_CROWDING_MULTIPLIER while the
settlement is crowded). At ~35,040 ticks/year (see time_system.py), this
is roughly 1 spontaneous case/year at population 200 uncrowded, versus
roughly 8/year at population 400 crowded — deliberately rare at low/mid
population and a real, felt pressure specifically where growth is
already straining housing. v0.44.0, "population control: disease" pass
— see docs/DECISIONS.md. The deterministic engine models the physical
fact of a pathogen taking hold; nothing here is LLM-judged, consistent
with disease being objective reality, not interpretation."""

OUTBREAK_MIN_CHANCE_PER_TICK = 2e-5
"""Floor applied to the population-scaled outbreak chance (see
`Population._maybe_outbreak`) — at a small founding population (~12),
`OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK * len(agents)` alone gives an
expected first case around tick ~830,000 (~24 sim-years), which reads
as "disease doesn't exist" for the entire early game even though the
system (and its UI: sick/immune rings, `/state` counters) is fully
real and live-report-confirmed invisible for that reason (v0.68.0).
This floor puts a small settlement's first case within roughly a
sim-year or two instead, while leaving the population-scaled term (and
therefore the "rare at low/mid population, real pressure once crowded"
design intent) untouched for any settlement large enough that the
scaled term already exceeds this floor on its own."""

OUTBREAK_FLOOR_SICK_FRACTION_CAP = 0.15
"""P2.2 (docs/AUDIT-2026-07-20.md): a live report at pop ~25 found
illness prevalence sitting near 40% — the floor above is population-
INDEPENDENT (a flat per-tick chance), so below roughly population 200
(where the scaled term overtakes it) it fires at the same absolute
rate regardless of settlement size, disadvantaging small villages
proportionally. Worse, nothing stopped it from firing again and again
while a settlement was already mid-outbreak — its job ("guarantee a
small settlement doesn't go a whole early game with zero visible
disease") is done the moment a first case has occurred; repeatedly
reseeding fresh index cases on top of an already-sick population is
what turned a real, felt pressure into a near-permanent state.
`_maybe_outbreak` now skips the floor (falls back to the honest
population-scaled chance alone) once the sick fraction already exceeds
this cap — small villages still get their guaranteed early case, but
the floor stops actively working against recovery once an outbreak is
already under way."""

OUTBREAK_CROWDING_MULTIPLIER = 6.0
"""Applied to OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK while the
settlement is crowded (same flag CROWDING_ENERGY_MULTIPLIER already
reads — population exceeding housing capacity) — real epidemiology:
crowd diseases originate and spread more readily in dense, under-housed
populations. Deliberately reuses the existing housing-pressure signal
rather than a second, disconnected density metric."""

OUTBREAK_ROAD_CONTACT_MULTIPLIER = 1.5
"""Integration milestone: scales OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK
by `1.0 + (fraction of the population on an established road tile) *
this` — infrastructure that connects people for trade/teaching also
connects them for contagion. Deliberately smaller-magnitude than
OUTBREAK_CROWDING_MULTIPLIER (crowding is the dominant, well-tuned
driver; roads are a real but secondary contact-rate signal on top of
it, same "never dominant" discipline every cross-system nudge in this
project follows) — a settlement with 100% of its people on roads
this tick sees at most a 2.5x multiplier, versus crowding's flat 6x."""

SICKNESS_TRANSMISSION_CHANCE_PER_TICK = 0.01
"""Chance a sick agent infects a colocated healthy agent, per tick they
share a tile. Compounds with how often agents actually end up colocated
(constant colocation over a full SICKNESS_DURATION_TICKS bout would make
infection near-certain; real movement makes realized spread textured
rather than an instant sweep) — see Population._tick_disease."""

SICKNESS_DURATION_TICKS = 800
"""Ticks a bout of sickness lasts before natural recovery, absent death
— roughly 8 sim-days at the default pacing."""

SICKNESS_DEATH_CHANCE_PER_TICK = 0.0001
"""Per-tick chance of dying while sick, without a hospital — chosen so
the case-fatality rate over a full SICKNESS_DURATION_TICKS bout is
roughly 8% (0.0001 x 800 ticks), reduced by SICKNESS_HOSPITAL_KILL_
CHANCE_REDUCTION with a standing hospital and nudged by temperament
(TEMPERAMENT_KILL_CHANCE_INFLUENCE), same shape as predator-attack
lethality. A real, felt population check without being a devastating
plague — see docs/DECISIONS.md."""

SICKNESS_HOSPITAL_KILL_CHANCE_REDUCTION = 0.3
"""Fractional reduction to SICKNESS_DEATH_CHANCE_PER_TICK, settlement-
wide, once at least one hospital is standing — same magnitude and
rationale as HOSPITAL_KILL_CHANCE_REDUCTION for predator attacks: care
exists and measurably improves survival odds. Gives the town brain's
"health" priority (already mapped to HOSPITAL, see settlement/
buildings.py's _PRIORITY_TO_KIND) a mechanical reason to matter beyond
the rare no-hospital-yet-and-someone-died-to-a-predator fallback arm."""

SICKNESS_ENERGY_DRAIN_MULTIPLIER = 1.3
SICKNESS_HUNGER_RATE_MULTIPLIER = 1.2
"""A sick agent feels it mechanically, not just narratively — faster
energy loss and hunger accrual while unwell. Same "small nudge, real
consequence" magnitude as CROWDING_ENERGY_MULTIPLIER. See
Population._update_needs."""

IMMUNITY_DURATION_TICKS = 400
"""Disease v2 (docs/DECISIONS.md): ticks a just-recovered agent stays
resistant to reinfection — deliberately half of SICKNESS_DURATION_TICKS
(~4 sim-days), a real but temporary window rather than lifelong
immunity, matching how most real endemic illnesses work. Set on
Agent.immune_ticks at recovery; see Population._tick_disease for the
decay and Population._maybe_outbreak for the index-case exclusion."""

GOSSIP_OPINION_CONTAGION = 0.15
GOSSIP_OPINION_MAX_STEP = 0.05
"""When a rumor names a specific third villager, each listener's
opinion of that person relaxes toward the *speaker's* opinion by this
fraction (capped at MAX_STEP per rumor, and skipped entirely when the
listener doesn't trust the speaker — see TRUST_SKEPTICISM_THRESHOLD).
This is the mechanism that makes gossip a real social force: opinions
now propagate through the conversation graph instead of only through
direct contact, so a well-connected critic can sour a village on
someone they've barely met — and a skeptical village can't be swayed.
See Population.apply_dialogue, docs/DECISIONS.md, architecture-review
implementation pass (gossip contagion)."""

SKILL_FARMING = "farming"
"""The only named skill in H5 v1 — see `Agent.skills`. A single
dimension deliberately, not a skill tree: this is the smallest slice
that makes "knowledge spreads through teaching/observation/
apprenticeship" mechanically real (practiced yield bonus + colocated
teaching) without redesigning every profession-shaped goal at once."""

SKILL_PRACTICE_GAIN = 0.01
"""Proficiency gained per successful farm harvest by the harvester
themself — "observation"/learning-by-doing. Small: ~100 harvests to go
from 0 to full mastery, a genuine multi-season apprenticeship, not an
instant unlock."""

SKILL_TEACHING_CHANCE_PER_TICK = 0.02
SKILL_TEACHING_GAIN = 0.015
SKILL_TEACHING_MIN_GAP = 0.15
"""A colocated pair where one agent's farming proficiency is at least
SKILL_TEACHING_MIN_GAP above the other's has a small per-tick chance of
the more skilled one teaching — the learner's proficiency steps toward
the teacher's by SKILL_TEACHING_GAIN, same "small nudge, real
consequence, colocation-driven" shape as relationship gain and gossip
contagion above. Faster than solo practice (SKILL_PRACTICE_GAIN),
consistent with teaching being a genuinely faster way to learn than
trial and error alone."""

INSTITUTION_TEACHING_BONUS_MULTIPLIER = 1.4
"""Integration milestone: `Population._maybe_teach_skills`'s roll
chance is multiplied by this when teacher and learner share a living
FAMILY or COUNCIL institution — learning from your own household or
elders is more effective than a passing lesson from a stranger.
Deliberately smaller than the trait/culture multipliers can combine to
(a modest, legible bonus, not a dominant one), and stacks with both
rather than replacing either."""

SKILL_FARMING_YIELD_BONUS = 0.25
"""At full mastery (proficiency 1.0), a farming-skilled harvester gets
up to +25% hunger relief per harvest — see Population._maybe_forage.
Same order of magnitude as TECH_BONUS_PER_LEVEL's per-invention harvest
bonus (15%), deliberately a bit higher since this is a per-person
ceiling requiring real practice/apprenticeship time, not a one-off
settlement-wide unlock."""

SKILL_CONSTRUCTION = "construction"
"""H5 extension (docs/ROADMAP.md "Phase H"): the second skill, gained
by practice (`Population._advance_construction`) and colocated teaching
(`_maybe_teach_skills`, already skill-name-agnostic — see H5 v1's own
docstring). Boosts that worker's own contribution to a construction/
repair site's progress, the same "practiced yield bonus" shape
`SKILL_FARMING` already established, just at a different mechanic."""

SKILL_CONSTRUCTION_SPEED_BONUS = 0.25
"""Same magnitude as SKILL_FARMING_YIELD_BONUS — a fully-skilled crew
(average construction proficiency 1.0) builds/repairs up to 25% faster
than an unskilled one, on top of (not instead of) the existing
materials-multiplier and tech-level bonuses."""

SKILL_MEDICINE = "medicine"
"""Third skill axis (docs/DECISIONS.md, "continue expanding, round
three"): gained by a hospital worker's own practice while crafting the
`"medicine"` good (`Population._maybe_craft_medicine`), taught the same
skill-name-agnostic way as farming/construction. Distinct from the
crafted good of the same name — the good is a personal stockpile that
gets consumed treating illness; the skill is the crafter's own growing
proficiency at making it."""

SKILL_MEDICINE_PRACTICE_GAIN = 0.012
"""Per successful medicine-crafting tick — close to SKILL_PRACTICE_GAIN
(farming's solo-practice rate), since both are "learning by doing" at a
fixed workplace rather than a rarer event-triggered gain."""

SKILL_MEDICINE_YIELD_BONUS = 0.3
"""At full mastery, a medicine-skilled hospital worker crafts up to +30%
more medicine per tick (`HOSPITAL_CRAFT_MEDICINE_PER_TICK` base) — same
"practiced yield bonus" shape as SKILL_FARMING_YIELD_BONUS/
SKILL_CONSTRUCTION_SPEED_BONUS, slightly higher since medicine has no
tech-level bonus of its own to stack with the way farming/construction
do."""

SKILL_INVENTION_BONUS_WEIGHT = 0.3
"""H5 extension: the settlement-wide average skill level (farming +
construction, now also medicine) gives a small additive nudge to
invention chance
(`SimulationEngine._maybe_schedule_invention`), mirroring `education_
invention_bonus`'s shape (1.0 + something). This is the roadmap's own
suggested H5 evolution point ("tech_level becomes the settlement-
aggregate signal... rather than an independently-rolled scalar") taken
as an *additive nudge* rather than a full replacement of the existing
roll — the roll, prosperity gate, and education bonus are all
untouched; a skilled population invents somewhat more readily on top of
them, not instead of them. Deliberately smaller than education's
uncapped 1.0-per-education-level scale (this maxes out at +30% at full
average mastery across the whole population, a much narrower ceiling)
since two narrow skills are a much thinner signal of general
inventiveness than accumulated formal education."""

# --- H6: psychology — a compact, bounded personality vector ----------------

TRAIT_RESILIENCE = "resilience"
TRAIT_SOCIABILITY = "sociability"
"""The two v1 axes `Agent.traits` holds — deliberately not a big-five
system. Resilience: how well an agent copes with hardship/loss (low =
more fragile/shaken by trauma, high = hardy). Sociability: draw toward
social contact vs. solitude. Both -1..1, 0.0 = neutral/unformed."""

TRAIT_AMBITION = "ambition"
"""H6 extension (docs/ROADMAP.md "Phase H"): a third axis, drawn from
the roadmap's own "identity, values, ambition" list — how much an agent
is driven to build/achieve/master something vs. content with routine.
Same -1..1/0.0-neutral convention as the other two. Nudged up by
tangible achievement (founding a building, first reaching mastery in a
skill — see TRAIT_AMBITION_FOUNDING_NUDGE/TRAIT_AMBITION_MASTERY_NUDGE)
rather than by hardship/social contact like resilience/sociability —
ambition is earned, not suffered or given."""

TRAIT_INHERITANCE_MUTATION_STDDEV = 0.15
"""How far a newborn's inherited trait axis (see `Population._maybe_
reproduce`'s call to `_inherited_traits`) is allowed to drift from the
exact average of its two parents' values — v0.87.6, "heritable
temperament with mutation" (docs/IDEAS-2026-07-EMERGENCE.md §1).
Sampled via `rng.gauss(0.0, TRAIT_INHERITANCE_MUTATION_STDDEV)` per
axis, then clamped back into -1..1 alongside the parent-average. Small
enough that a family's character is a real, recognizable statistical
tendency across generations (the beliefs/folklore layer can notice and
name "the stubborn Aldertons") rather than pure noise, but not so small
that lineages become deterministic clones of their founders — every
prior founder started at a neutral 0.0 on all four axes (traits are
never rolled at spawn, only earned via lifetime event nudges — see
TRAIT_RESILIENCE/TRAIT_SOCIABILITY below), so this is the first source
of inherited (rather than purely lived) trait variance in the
simulation."""

TRAIT_OPENNESS = "openness"
"""H6 v4 (docs/DECISIONS.md "continue expanding" pass): a fourth axis,
closing the "identity/values remain open" note the roadmap has carried
since ambition (the third axis) shipped. -1 = rooted/set in the
village's own ways, +1 = drawn to the unfamiliar. Same -1..1/0.0-
neutral convention as the other three. Nudged up by direct outside
contact (hearing a caravan's news from beyond the village — see
TRAIT_OPENNESS_CARAVAN_NUDGE); unlike ambition (earned through
achievement) or resilience (worn by hardship), openness is shaped by
exposure — the one thing a small, mostly-isolated village rarely
gets."""

TRAIT_STEP_MAX = 0.02
TRAIT_MEAN_REVERSION = 0.99
"""Monthly bounded-random-walk parameters — same shape as `Settlement.
temperament`'s `TEMPERAMENT_STEP_MAX`/`TEMPERAMENT_MEAN_REVERSION`,
reused at agent scale. Slower mean reversion than temperament's 0.97
(a person's underlying disposition should drift less readily than a
whole settlement's mood) and a smaller step, since 400 agents each
walking is a lot more individual variance to keep bounded and legible
than one settlement-wide number. See Population._tick_traits."""

TRAIT_GRIEF_NUDGE = -0.03
TRAIT_VIOLENCE_NUDGE = -0.05
TRAIT_SUSTAINED_HUNGER_NUDGE = -0.01
"""Event-driven resilience nudges — "nudged slowly by lived experience
(grief, violence witnessed, sustained hunger)," per docs/ROADMAP.md's
H6 evolution point verbatim. Violence (surviving/witnessing a predator
attack) hits harder than grief; sustained hunger is the mildest and
only applied while an agent is already critically hungry, mirroring
how starvation itself escalates gradually rather than snapping the
first tick. All three only ever push resilience down — recovery comes
from the monthly mean-reverting walk, the same way temperament recovers
from a bad season without a matching "good event" for every bad one."""

TRAIT_SOCIAL_CONTACT_NUDGE = 0.015
"""Sociability nudge on a positive social exchange (a completed trade —
food or tools) — small and positive, the mirror of the resilience
nudges above but the only trait axis with a routine upward pull, since
ordinary friendly contact is common and grief/violence are not."""

TRAIT_RECONCILE_NUDGE = 0.02
"""Sociability nudge on a successful dispute reconciliation
(`Population.apply_dispute`, `outcome == "reconcile"`) — trusting
someone again and being right about it teaches you to keep trusting.
Slightly larger than the routine TRAIT_SOCIAL_CONTACT_NUDGE since
reconciling after a real feud is a rarer, more deliberate event than an
ordinary trade, same "rarer -> bigger per-event nudge" discipline
TRAIT_AMBITION's event nudges already use."""

TRAIT_RECOVERY_RESILIENCE_NUDGE = 0.01
"""Resilience nudge on recovering from illness (`Population._tick_
disease`, the `"recovery"` life event) — surviving hardship makes you
tougher. The missing positive counterpart to TRAIT_SUSTAINED_HUNGER_
NUDGE, which only ever pushes resilience down at the onset of a hunger
crisis; same small magnitude, mirrored in sign."""

MASTERY_THRESHOLD = 0.95
"""A skill counts as "mastered" at or above this proficiency — the
trigger for TRAIT_AMBITION_MASTERY_NUDGE (see Population._maybe_forage/
_advance_construction, both of which check the practice-gain crossed
this threshold rather than firing every tick a mastered agent happens
to practice again)."""

TRAIT_AMBITION_FOUNDING_NUDGE = 0.04
TRAIT_AMBITION_MASTERY_NUDGE = 0.06
"""Ambition nudges on tangible achievement — founding a building
(`Population._maybe_start_construction`) or a skill first crossing
MASTERY_THRESHOLD through practice. Both larger than the resilience/
sociability event nudges: these are rarer, more deliberate
accomplishments, not routine lived experience, so they should register
more per occurrence even though they fire less often."""

TRAIT_NOTABLE_THRESHOLD = 0.3
"""A trait is only mentioned in cognition/dialogue prompts once its
magnitude clears this bar — same "only mentioned once notably warm/
cold" treatment `player_standing` already gets, so a freshly-neutral
agent's prompt isn't cluttered with "not particularly resilient or
fragile" noise."""

# --- integration milestone: traits become mechanically consumed, not write-only ---

TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE = 0.25
"""How far personal `TRAIT_RESILIENCE` (-1..1) can push an agent's own
disease/predator death-chance roll away from the settlement-wide
baseline (`Population._tick_disease`/`_maybe_predator_attack`) — a
fully resilient agent's chance is scaled toward `1 - this`, a fully
fragile one toward `1 + this`. Previously traits were nudged by these
exact events (grief, violence, sustained hunger) but never read back by
any deterministic mechanic — this closes that loop: living through a
brush with danger measurably makes the next one a little more
survivable, or not, depending on how it went. Same small, symmetric,
never-dominant magnitude as TEMPERAMENT_KILL_CHANCE_INFLUENCE."""

TRAIT_RESILIENCE_STARVATION_TOLERANCE_INFLUENCE = 0.2
"""Fractional stretch/shrink on `STARVATION_TICKS_TO_DEATH` from
personal resilience (`Population._apply_deaths`) — a resilient agent
holds on somewhat longer into a hunger crisis, a fragile one somewhat
less. Same magnitude class as the death-chance influence above."""

TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE = 0.3
"""Fractional nudge on personal trade-initiation and skill-teaching
roll chances from `TRAIT_SOCIABILITY` (-1..1) — a sociable agent reaches
out more readily, an unsociable one less. Consumed in
`Population._maybe_trade_food/_maybe_trade_tools/_maybe_trade_medicine`
and `_maybe_teach_skills`. Larger than the death-chance influence above
since these are routine, low-stakes rolls rather than life-or-death
ones — a bigger swing here is still never dominant (contact still
requires colocation + the base roll to begin with)."""

TRAIT_AMBITION_FOUNDER_SELECTION_WEIGHT = 0.4
"""How strongly `TRAIT_AMBITION` (-1..1) weights which eligible,
colocated agent personally owns a newly-founded HUT
(`Population._maybe_start_construction`), when more than one candidate
qualifies — an ambitious agent is more likely to be the one who steps
up and claims it, not guaranteed to be (still an RNG-weighted pick, not
a hard rule). Deliberately scoped to HUT ownership only, not council
seating — COUNCIL stays a clean, single-purpose "elders by age" rule
(`_maybe_form_council`/`_maybe_refresh_council`); mixing ambition into
that selection would blur what "a council of elders" means. Read side
of the same trait `TRAIT_AMBITION_FOUNDING_NUDGE` already writes to on
the event itself, closing that loop the same way resilience/
sociability close theirs."""

TRAIT_OPENNESS_CARAVAN_NUDGE = 0.05
"""Openness nudge applied to each listener a caravan's outside rumor
reaches (`Population.spread_rumor`) — larger than the routine
sociability contact nudge (0.015) since direct contact with news from
beyond the village is rare (see CARAVAN_CHANCE_PER_MONTH) and should
register accordingly per occurrence, same "rarer, more deliberate ->
bigger per-event nudge" discipline TRAIT_AMBITION's event nudges
already use."""

TRAIT_FEUD_SOCIABILITY_NUDGE = -0.02
TRAIT_OSTRACISM_SOCIABILITY_NUDGE = -0.04
TRAIT_THEFT_VICTIM_SOCIABILITY_NUDGE = -0.02
"""v1 audit fix: sociability, ambition, and openness previously had
*zero* negative event-nudge sources anywhere in the codebase — only
TRAIT_RESILIENCE was genuinely bidirectional (grief/violence/hunger
nudges down, recovery nudges up). Meanwhile TRAIT_SOCIAL_CONTACT_NUDGE
(+0.015) fires on every routine food/tools/medicine trade, a frequent
event in a populous settlement, with no matching downward force —
plausible long-run homogenization toward "everyone eventually becomes
sociable," working against the psychological-realism/per-agent-
diversity priority. These three close the gap with real negative
triggers, same "rarer/harsher event -> bigger magnitude" discipline as
their positive counterparts: a feud hardening for good
(`Population.apply_dispute`, outcome=="feud") makes both parties
somewhat more withdrawn; being ostracized is a harsher, more isolating
blow than an ordinary feud; being the victim of theft (a colocated
agent, not a stranger) sours routine trust in others generally, not
just in the thief. All three land on `TRAIT_SOCIABILITY`, mirroring
the existing positive nudges' own axis."""

TRAIT_MEAN_REVERSION_AMBITION = 0.965
TRAIT_MEAN_REVERSION_OPENNESS = 0.965
"""v1 audit fix, companion to the sociability nudges above: ambition
and openness genuinely lack a natural, frequent negative-trigger event
in this simulation the way sociability now has (feud/ostracism/theft)
and resilience always had (grief/violence/hunger) — a plausible
in-fiction negative ambition event (a failed venture, a stalled
career) or negative openness event (a bad encounter with an outsider)
isn't backed by any existing mechanic worth bending out of shape just
to manufacture a trigger. Rather than force one, these two axes get a
faster monthly mean-reversion pull back toward neutral (0.965 vs. the
shared TRAIT_MEAN_REVERSION=0.99) so their existing rare positive
nudges (mastery/founding for ambition, caravan contact for openness)
don't accumulate into a population-wide upward drift the way the old
uniform 0.99 allowed — same fix direction the audit itself flagged as
an acceptable alternative to a fabricated negative trigger. See
Population._tick_traits."""

TRAIT_OPENNESS_MIGRANT_WELCOME_INFLUENCE = 0.3
"""Fractional nudge on `_maybe_welcome_migrant`'s roll chance from the
surviving population's average `TRAIT_OPENNESS` — a village whose
handful of survivors lean toward the unfamiliar welcomes a stranger
somewhat more readily than one that leans rooted. Same magnitude class
as TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE (a routine, non-life-
critical roll, so a bigger swing is still never dominant) — closes
openness's own write-only loop the same way the integration milestone
closed resilience/sociability/ambition's."""


# --- Phase I: per-agent emotions — fast-changing, deterministic, decaying ---
# See docs/VISION-2026-07.md, Phase I. Distinct from `traits` (slow,
# near-permanent disposition): emotions are the "rapidly changing" layer
# the vision's cognition pipeline calls for — bumped by specific lived
# events, decaying back toward 0 every tick otherwise. Same dict-with-
# missing-key-reads-0.0 convention as `traits`.

EMOTION_FEAR = "fear"
EMOTION_JOY = "joy"
EMOTION_GRIEF = "grief"
EMOTION_ANGER = "anger"
"""The four v1 axes `Agent.emotions` holds, each 0..1 (0 = not feeling
it, 1 = overwhelmed) — unlike `traits`' -1..1 bipolar convention,
emotions are intensities, not a spectrum between two opposites (fear
and joy are not opposites of the same axis). Deliberately not a bigger
affect model — four legible, event-groundable feelings, matching the
vision's "fast-changing" layer without turning cognition prompts into a
psychology thesis."""

EMOTION_DECAY_RATE = 0.01
"""Fraction of the distance back to 0 an emotion recovers per tick
(`value *= (1 - EMOTION_DECAY_RATE)`), applied in `Population.tick`
right after `_update_needs`. At the default tick cadence a strong (1.0)
fear fades to ~0.5 in about 70 ticks and is negligible within a couple
of sim-days — fast enough that emotions read as "how I feel right now,"
not a second belief system; events that should leave a longer mark
already do, via `memories`/`traits`/`beliefs`."""

EMOTION_PREDATOR_FEAR_BUMP = 0.5
EMOTION_STARVATION_FEAR_BUMP = 0.3
EMOTION_ILLNESS_FEAR_BUMP = 0.2
EMOTION_BIRTH_JOY_BUMP = 0.4
EMOTION_FESTIVAL_JOY_BUMP = 0.3
EMOTION_RECONCILE_JOY_BUMP = 0.3
EMOTION_DEATH_GRIEF_BUMP = 0.6
EMOTION_DISPUTE_ANGER_BUMP = 0.4
"""Per-event bump magnitudes (added, then clamped to 1.0 — repeated
events within the decay window compound toward the ceiling rather than
resetting). Sized so a single sharp event (survived a predator attack,
a death in the family) reads as a real spike against the 0..1 range,
not a rounding error; see the call sites in `agents/population.py` for
exactly which event fires which bump."""

EMOTION_DISASTER_FEAR_BUMP = 0.7
"""Largest fear bump of the set — surviving a flood/wildfire on your own
tile is a direct brush with the disaster itself, not a secondhand scare.
Paired in `Population.tick` with a `_remember(..., because=...)` call, so
when the memory eventually falls out of the regular capped memory list
it graduates into permanent `core_memories` instead of disappearing —
see EMOTION_DECAY_RATE's docstring above: a spike this sharp is exactly
the "should leave a longer mark" case, even though the emotion value
itself still decays like any other."""

EMOTION_STORM_FEAR_BUMP = 0.4
"""Storm has no per-tile tracking (`tick_storm` damages every settlement
uniformly the instant it fires, unlike flood/wildfire's persistent
per-tile state) — every AWAKE agent gets this smaller, settlement-wide
fear bump instead of EMOTION_DISASTER_FEAR_BUMP's tile-scoped, more
direct spike."""

MOURNING_DURATION_TICKS = 96
"""v0.87.9, "ceremonies agents attend: funerals" (docs/IDEAS-2026-07-
EMERGENCE.md §1). How long a bereaved kin/bonded survivor's movement is
biased toward the deceased's grave (the memorial `Population._apply_
deaths` already creates at the death tile) — "for a day," matching a
default-config day's tick count (`minutes_per_day // sim_minutes_per_
tick` = 1440//15 = 96) rather than a config-derived value, since this
is a behavioral constant of the mourning model itself (see MIN_
LIFESPAN_TICKS/MATURITY_TICKS above for the same "tuned constant, not
a config field" convention)."""

MOURNING_GRIEF_EASE = 0.15
"""Grief reduction applied once mourning completes (MOURNING_DURATION_
TICKS elapsed) — "attending the funeral helped process it," a real,
modest easing (never full relief) distinct from ordinary passive
emotion decay. Deliberately smaller than EMOTION_DEATH_GRIEF_BUMP
(0.6) — the funeral softens grief, it doesn't erase the loss."""

WEDDING_DURATION_TICKS = 48
"""v0.87.10, "ceremonies agents attend: weddings" (docs/IDEAS-2026-07-
EMERGENCE.md §1, the companion to funerals/MOURNING_DURATION_TICKS —
"A wedding = the same shape on a reproduction-pair formation"). Half
the mourning duration ("half a day," not "a day") — a wedding is a
gathering to mark a joyful occasion already underway, not a grief
process to work through; there's no equivalent reason for it to hold
guests as long."""

WEDDING_JOY_BUMP = 0.25
"""Joy bump applied to every guest once the gathering concludes
(WEDDING_DURATION_TICKS elapsed) — "the celebration lifted the whole
gathering's spirits," on top of (not instead of) the couple's own
existing EMOTION_BIRTH_JOY_BUMP from the triggering birth. Smaller than
EMOTION_BIRTH_JOY_BUMP (0.4, the parents' own bump) since this is the
secondhand lift onlookers get from attending, not the couple's own."""

EMOTION_NOTABLE_THRESHOLD = 0.35
"""Floor above which an emotion is worth mentioning in a prompt or
letting bias a deterministic fallback — mirrors `TRAIT_NOTABLE_
THRESHOLD`'s role for traits. Below this, decay has already made the
feeling background noise."""


def bump_emotion(agent: "Agent", key: str, amount: float) -> None:
    """Raise one of `agent.emotions`' four axes by `amount`, clamped to
    1.0. The single call site every event-driven emotion nudge in
    `agents/population.py` goes through, so the clamp/creation logic
    lives in one place."""
    agent.emotions[key] = min(1.0, agent.emotions.get(key, 0.0) + amount)


def push_secret(agent: "Agent", text: str) -> None:
    """Appends one private secret to `agent.secrets`, FIFO-evicted at
    `MAX_SECRETS`. Thin mutator (same shape as `llm.beliefs.push_
    semantic_memory`) so callers don't hand-roll the eviction logic."""
    if not text:
        return
    agent.secrets.append(text)
    if len(agent.secrets) > MAX_SECRETS:
        del agent.secrets[0]


MAX_GRIEVANCE_TAGS_PER_SOURCE = 3
"""Cap on each `Agent.grievances[source_id]` list — "a handful of
concrete wrongs remembered about this one person," not a growing
diary. See `Agent.grievances`'s docstring for why this is a separate,
protected store rather than relying on the churning `memories` log."""


def add_grievance(agent: "Agent", source_id: int, text: str) -> None:
    """Appends one tagged grievance against `source_id`, FIFO-evicted at
    MAX_GRIEVANCE_TAGS_PER_SOURCE. Never auto-cleared by time — only
    `clear_grievance` (an explicit reconciliation) removes an entry.
    Goes through `agent.ledger` directly rather than `agent.grievances
    .setdefault(...)` — see `_GrievanceView`'s docstring in
    agents/ledger.py for why the dict-proxy's `setdefault` isn't safe
    for a mutable-list field backed by shared ledger storage."""
    agent.ledger.add_grievance(source_id, text, MAX_GRIEVANCE_TAGS_PER_SOURCE)


def clear_grievance(agent: "Agent", source_id: int) -> None:
    """Explicit reconciliation: drops every grievance tag against
    `source_id`. Distinct from decay — grievances never fade on their
    own, see `Agent.grievances`'s docstring."""
    agent.ledger.clear_grievance(source_id)


def decay_emotions(agent: "Agent") -> None:
    """Tick every held emotion back toward 0 by `EMOTION_DECAY_RATE`,
    dropping entries that have decayed to (near enough) nothing so a
    long-lived agent's `emotions` dict doesn't accumulate stale
    near-zero keys forever — same "prune, don't just leak toward zero"
    discipline as the relationship/trust dicts (v0.42.0).

    Native fast path (see cpp/src/emotion_decay.cpp): the multiply
    itself moves to C++, one call per agent per tick (module 6's own
    "runs unconditionally every tick" shape) — the < 0.005 prune
    decision and the sparse-dict bookkeeping (a missing key never
    entered the call, decays to a no-op 0.0 either way) stay in Python,
    exactly like `_update_needs`' native split."""
    if not agent.emotions:
        return
    if _native_decay_emotions is not None:
        state = _NativeEmotionState(
            agent.emotions.get(EMOTION_FEAR, 0.0), agent.emotions.get(EMOTION_JOY, 0.0),
            agent.emotions.get(EMOTION_GRIEF, 0.0), agent.emotions.get(EMOTION_ANGER, 0.0),
        )
        result = _native_decay_emotions(state, EMOTION_DECAY_RATE)
        for key, value in (
            (EMOTION_FEAR, result.fear), (EMOTION_JOY, result.joy),
            (EMOTION_GRIEF, result.grief), (EMOTION_ANGER, result.anger),
        ):
            if key not in agent.emotions:
                continue
            if value < 0.005:
                del agent.emotions[key]
            else:
                agent.emotions[key] = value
        return
    for key in list(agent.emotions.keys()):
        value = agent.emotions[key] * (1.0 - EMOTION_DECAY_RATE)
        if value < 0.005:
            del agent.emotions[key]
        else:
            agent.emotions[key] = value


DEBT_DECAY_RATE = 0.0005
"""Per-tick fractional decay on `Agent.debts` (Phase L "Economy depth",
docs/VISION-2026-07.md) — much slower than EMOTION_DECAY_RATE: a debt
is a lasting social fact, not a passing feeling, so it should take
genuine time (thousands of ticks) to fade to forgiven rather than
washing out within a season. Written only by `_record_debt` (agents/
population.py); this function only ever shrinks it."""

DEBT_PRUNE_THRESHOLD = 0.02
"""Below this, a decayed debt is dropped from the dict entirely — same
"prune small entries, don't let them linger forever" discipline as
`decay_emotions`/the relationship/trust dicts."""

DEBT_SIGNIFICANT_THRESHOLD = 2.0
""""Definitive checklist" Tier 0.1 (2026-07-21, "significant
interpersonal state stops decaying to zero — persists for years,
resolves only explicitly"): a debt at or above this amount (roughly 4x
one trade's DEBT_PER_TRADE_FRACTION increment — several real
exchanges, not one) is a genuine standing obligation a village would
actually remember and expect repaid, not small change that's fine to
quietly forget. `decay_debts` now leaves it flat once it crosses this
line; only an explicit repayment/forgiveness action (or the debtor's
death) resolves it. Smaller, ordinary debts keep the original ambient
fade unchanged — this distinguishes "history" (permanent, load-
bearing) from "weather" (ambient, meant to fade), applied to the one
axis that previously decayed unconditionally to zero regardless of
size."""


def decay_debts(agent: "Agent") -> None:
    """Tick every owed debt back toward 0, pruning what's decayed near
    enough to nothing — except a debt at/above DEBT_SIGNIFICANT_
    THRESHOLD, which stays flat (see its docstring) rather than fading
    on its own. Pure Python, no native fast path: unlike emotions
    (a fixed 4-key vector scanned every tick for every agent regardless
    of activity), `debts` is sparse and only ever has entries for
    agents who've actually traded — nowhere near the same hot-path
    cost, so this doesn't clear the native-port bar (CLAUDE.md's
    "escalate only with a measured need")."""
    if not agent.debts:
        return
    for key in list(agent.debts.keys()):
        current = agent.debts[key]
        if current >= DEBT_SIGNIFICANT_THRESHOLD:
            continue
        value = current * (1.0 - DEBT_DECAY_RATE)
        if value < DEBT_PRUNE_THRESHOLD:
            del agent.debts[key]
        else:
            agent.debts[key] = value


def dominant_emotion(emotions: dict) -> tuple[str, float] | None:
    """The single strongest emotion clearing `EMOTION_NOTABLE_THRESHOLD`,
    or None — the one-feeling summary prompts and fallbacks consume
    rather than reasoning over all four axes individually."""
    if not emotions:
        return None
    key, value = max(emotions.items(), key=lambda item: item[1])
    if value < EMOTION_NOTABLE_THRESHOLD:
        return None
    return key, value


_EMOTION_PHRASES = {
    EMOTION_FEAR: "afraid",
    EMOTION_JOY: "joyful",
    EMOTION_GRIEF: "grieving",
    EMOTION_ANGER: "angry",
}


def describe_emotion(emotions: dict) -> str:
    """Shared by llm/cognition.py and llm/dialogue.py: a short natural-
    language fragment naming the dominant notable emotion, or "" if none
    clears the threshold — same one-function-so-prompts-don't-drift
    reasoning as `describe_traits`."""
    dominant = dominant_emotion(emotions)
    if dominant is None:
        return ""
    return _EMOTION_PHRASES[dominant[0]]


def just_now_text(working_memory: list[str], recent_episodic: list[str]) -> str:
    """Shared by llm/cognition.py and llm/dialogue.py: the freshest
    `working_memory` entry (bare text, caller formats it), or "" when
    there isn't one or it's already present in the episodic slice the
    prompt is separately showing — avoids a duplicated sentence in the
    common case where the most recent event was memorable enough to
    survive salience-weighted eviction too (see WORKING_MEMORY_MAX's
    docstring for why the two can diverge)."""
    if not working_memory:
        return ""
    latest = working_memory[-1]
    return "" if latest in recent_episodic else latest


def describe_traits(traits: dict) -> str:
    """Shared by llm/cognition.py and llm/dialogue.py: a short natural-
    language fragment for whichever traits currently clear
    TRAIT_NOTABLE_THRESHOLD, or "" if none do. One function so both
    prompts describe personality the same way rather than drifting."""
    bits = []
    resilience = traits.get(TRAIT_RESILIENCE, 0.0)
    if resilience >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("resilient, taking hardship in stride")
    elif resilience <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("shaken easily by hardship")
    sociability = traits.get(TRAIT_SOCIABILITY, 0.0)
    if sociability >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("drawn to company")
    elif sociability <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("keeps to themself")
    ambition = traits.get(TRAIT_AMBITION, 0.0)
    if ambition >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("driven to build and achieve")
    elif ambition <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("content with routine")
    openness = traits.get(TRAIT_OPENNESS, 0.0)
    if openness >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("drawn to the unfamiliar")
    elif openness <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("set in the village's own ways")
    return ", ".join(bits)


def describe_mind_fallback(name: str, traits: dict) -> str:
    """Deterministic stand-in for `Agent.mind`'s one-time LLM-authored
    paragraph (see `MAX_MIND_TEXT_CHARS`) — set synchronously the
    instant an agent enters the core cast, before any background LLM
    call has a chance to run or in case one never succeeds. Built from
    the same trait descriptions `describe_traits` already produces, just
    framed as a standing self-description rather than a momentary
    prompt fragment, so a fallback-only run still gives every core-cast
    member *some* durable identity text."""
    traits_text = describe_traits(traits)
    if traits_text:
        return f"{name} thinks of themself as someone who is {traits_text}."
    return f"{name} has never put much thought into who they are — they just live."


_VOICE_FALLBACK_TEMPLATES = (
    "speaks in short, plain sentences",
    "trails off mid-thought and rarely finishes a sentence",
    "answers most things with another question",
    "leans on old sayings and proverbs when they talk",
    "talks fast and often interrupts themself",
    "chooses words carefully and speaks slowly",
    "has a habit of repeating the last thing they said, for emphasis",
    "rarely speaks unless spoken to first",
)


def describe_voice_fallback(name: str, agent_id: int) -> str:
    """Deterministic stand-in for `Agent.voice` — same "instant
    placeholder, LLM silently improves it later" shape as `describe_
    mind_fallback`, just a shorter manner-of-speaking tag instead of a
    full identity paragraph. Keyed by `agent_id` (not traits, unlike
    `describe_mind_fallback`) purely to give every fallback-only agent
    a genuinely different-sounding tag rather than clustering on
    whichever trait combination happens to be common."""
    return _VOICE_FALLBACK_TEMPLATES[agent_id % len(_VOICE_FALLBACK_TEMPLATES)]


_VOICE_LEADING_PRONOUN_RE = re.compile(r"^(they|he|she|it)\s+", re.IGNORECASE)


def normalize_voice_phrase(text: str) -> str:
    """`Agent.voice` is meant to read as a bare predicate phrase — the
    fallback templates above are already shaped this way ("speaks in
    short, plain sentences," no subject, no trailing period), so
    `llm/dialogue.py` can safely write `f"{agent.name} {agent.voice}"`
    and get one grammatical sentence. A live audit found the LLM-
    authored path routinely violates this despite SYSTEM_PROMPT asking
    for "third person" (meant to distinguish it from a stage direction
    like "I always..."), producing "Ysolde Always speaks..." (a
    sentence-initial capital that reads as two sentences smashed
    together once concatenated) or "Godfrey He always speaks..." (a
    redundant explicit subject pronoun duplicating the name dialogue.py
    already prepends). Applied both at write time (`llm/mind.py`'s
    `parse_voice`, for anything authored from here on) and at read time
    here (retroactively fixes every already-persisted voice with zero
    snapshot migration needed) — strip a leading subject pronoun, strip
    trailing punctuation, lowercase the new leading letter so it reads
    as a continuation of the name that precedes it."""
    text = text.strip()
    text = _VOICE_LEADING_PRONOUN_RE.sub("", text)
    text = text.rstrip(". ").strip()
    if text:
        text = text[0].lower() + text[1:]
    return text


class Agent:
    """A single inhabitant.

    Storage (v0.75.0, R8 slice 3 wire-in): the 12 dense scalar fields —
    `x`, `y`, `hunger`, `energy`, `state`, `age_ticks`, `max_age_ticks`,
    `starving_ticks`, `sick_ticks`, `immune_ticks`, `goal`,
    `settlement_id` — are `@property` accessors backed by a native
    `AgentStore` (structure-of-arrays over cpp/src/agent_table.cpp) once
    `Population` adopts the agent via `_attach`. Until adopted — and
    permanently when the native extension isn't built — those scalars
    live in plain `_x`/`_hunger`/... instance attributes, byte-identical
    to the former dataclass. The store is a pure change of *where* the
    numbers sit, never of behaviour (verified native-on vs native-off
    every tick by scripts/verify_native_soak.py). The variable-size
    fields (relationships/trust/inventory/memories/skills/traits/beliefs
    /parents/travel_target) stay ordinary Python attributes regardless.

    Was a `@dataclass` before v0.75.0; converted to a hand-written class
    so the scalar fields can be properties. The `__init__` keyword
    signature and `to_dict`/`from_dict` are preserved exactly, so every
    construction site is unchanged. Per-field rationale that used to live
    in dataclass field docstrings is retained inline below.
    """

    def __init__(
        self,
        id: int,
        name: str,
        x: int,
        y: int,
        hunger: float = 0.0,
        energy: float = 1.0,
        state: AgentState = AgentState.AWAKE,
        age_ticks: int = 0,
        max_age_ticks: int = MAX_LIFESPAN_TICKS,
        starving_ticks: int = 0,
        sick_ticks: int = 0,
        immune_ticks: int = 0,
        relationships: dict[int, float] | None = None,
        trust: dict[int, float] | None = None,
        inventory: dict[str, float] | None = None,
        parents: tuple[int, int] | None = None,
        goal: AgentGoal = AgentGoal.WANDER,
        goal_reason: str = "",
        memories: list[str] | None = None,
        skills: dict[str, float] | None = None,
        traits: dict[str, float] | None = None,
        settlement_id: int = 0,
        travel_target: tuple[int, int] | None = None,
        beliefs: list[dict] | None = None,
        emotions: dict[str, float] | None = None,
        memory_salience: list[float] | None = None,
        memory_causes: list[str] | None = None,
        working_memory: list[str] | None = None,
        semantic_memories: list[str] | None = None,
        secrets: list[str] | None = None,
        life_digest: str = "",
        mind: str = "",
        voice: str = "",
        debts: dict[int, float] | None = None,
        stuck_ticks: int = 0,
        last_move_dx: int = 0,
        last_move_dy: int = 0,
        lessons: list[dict] | None = None,
        seek_target_id: int | None = None,
        mourning_ticks_remaining: int = 0,
        mourning_target: tuple[int, int] | None = None,
        wedding_ticks_remaining: int = 0,
        wedding_target: tuple[int, int] | None = None,
        plan: dict | None = None,
        core_memories: list[str] | None = None,
        core_memory_salience: list[float] | None = None,
        standing_penalty: float = 0.0,
        occupation: str = "",
        relationship_flags: dict[int, str] | None = None,
        grievances: dict[int, list[str]] | None = None,
        long_term_goal: dict | None = None,
        life_event_since_goal: bool = False,
        hardened_traits: "set[str] | None" = None,
        extreme_event_count: int = 0,
    ) -> None:
        self.id = id
        self.name = name
        # Native store, set by Population._attach when the extension is
        # built; None means "scalars live in the _x/... locals below",
        # which is the permanent state in the pure-Python fallback.
        self._store: "object | None" = None
        # --- the 12 store-backed scalars (source of truth while detached) ---
        self._x = x
        self._y = y
        self._hunger = hunger
        self._energy = energy
        self._state = state
        self._age_ticks = age_ticks
        self._max_age_ticks = max_age_ticks
        self._starving_ticks = starving_ticks
        # sick_ticks: 0 = healthy; >0 = ticks into the current bout of
        # illness (recovery via SICKNESS_DURATION_TICKS, reset on
        # recovery/death). See Population._maybe_outbreak/_tick_disease.
        self._sick_ticks = sick_ticks
        # immune_ticks: set to IMMUNITY_DURATION_TICKS on recovery,
        # decremented every tick; while >0 the agent can neither be an
        # outbreak index case nor catch illness from a carrier —
        # temporary, fading resistance, not a permanent vaccine.
        self._immune_ticks = immune_ticks
        self._goal = goal
        # settlement_id: which settlement this agent calls home
        # (multi-settlement, v0.65.0) — 0 until a fission party departs.
        # Scopes which granaries/stockpiles/institutions are "theirs";
        # physical interaction stays spatial across settlements.
        self._settlement_id = settlement_id
        self.goal_reason = goal_reason
        # --- variable-size fields — always plain Python attributes ----------
        # relationships/trust/debts/relationship_flags/grievances: all
        # five now back onto one shared `Ledger` (Phase 0 of "the
        # self-evolving world," docs/VISION-2026-07-21-SELFEVOLVING.md
        # — agents/ledger.py) instead of five independent dicts. Each
        # attribute below is still a real dict-like object with the
        # exact same sparsity/behavior as before (see `ledger.py`'s
        # `_FieldView`/`_GrievanceView`) — assigned further down, once
        # all five constructor args are in scope, so this is a forward
        # reference; see `self.ledger = Ledger()` below.
        #
        # trust: -1..1 per source id — credibility, a distinct axis from
        # `relationships` (fondness); the two can diverge. Low trust makes
        # a rumor land with visible skepticism. See apply_dialogue.
        #
        # inventory: personal possessions, today just {"food": 0..
        # PERSONAL_FOOD_CAPACITY} — the one thing unambiguously this
        # agent's own, vs. communal Settlement.materials/granary food.
        self.inventory: dict[str, float] = {} if inventory is None else inventory
        self.parents = parents
        # memories: short personal log capped at MAX_AGENT_MEMORIES, fed
        # back into this agent's own cognition prompt.
        self.memories: list[str] = [] if memories is None else memories
        # memory_salience: index-aligned with `memories` (Phase I, see
        # MEMORY_SALIENCE_BASELINE above) — maintained solely by
        # agents/population.py's `_remember`, the only mutator of
        # `memories`. A legacy/mismatched-length list is defensively
        # padded with the baseline in `from_dict` rather than trusted
        # raw, so an old snapshot never desyncs the two lists.
        self.memory_salience: list[float] = [] if memory_salience is None else memory_salience
        # memory_causes: v0.87.14 "causal memory links" (docs/IDEAS-
        # 2026-07-EMERGENCE.md §7) — index-aligned with `memories`
        # exactly like `memory_salience`, "" meaning "no known cause."
        # Written only at `_remember` call sites where the engine
        # objectively knows the cause (a death, a dispute outcome, an
        # inheritance) — never fabricated for an ordinary memory.
        # Consumed by `retrieve_relevant_memories` (small scoring bonus)
        # and surfaced in cognition prompts as "(because: ...)" — see
        # llm/cognition.py's build_prompt.
        self.memory_causes: list[str] = [] if memory_causes is None else memory_causes
        # working_memory: small, strictly-FIFO "what just happened"
        # buffer — see WORKING_MEMORY_MAX above.
        self.working_memory: list[str] = [] if working_memory is None else working_memory
        # semantic_memories: condensed lasting self-theories distilled
        # from episodic memory, strictly FIFO, cap MAX_SEMANTIC_MEMORIES
        # (Phase J, see above) — written only by the Reflect() job.
        self.semantic_memories: list[str] = [] if semantic_memories is None else semantic_memories
        # secrets: private things this agent holds back, strictly FIFO,
        # cap MAX_SECRETS (see above) — planted by dispute outcomes.
        self.secrets: list[str] = [] if secrets is None else secrets
        # life_digest: one LLM-authored sentence condensing this agent's
        # ENTIRE accumulated self-understanding (their private beliefs +
        # semantic memories together, not just the newest one) — same
        # "digest, not just a recency slice" treatment `Settlement.
        # belief_digest`/`culture_digest` already get (v0.85.4/.5),
        # applied at the individual level (v0.86.7, Constitution: "the
        # LLM should learn about the simulation... through persistent,
        # summarized context"). Written by extending the existing
        # monthly Reflect() job (`SimulationEngine._maybe_schedule_
        # personal_belief`) — zero added LLM call volume. Only
        # overwritten on a genuine LLM answer (that job is `critical=
        # True`), retained across a fallback stretch, same discipline as
        # every other digest field. Fed back into this agent's own
        # cognition/dialogue prompts as one more grounding line — this
        # is the concrete "read persistent memory back into the LLM"
        # loop closing at the personal scale.
        self.life_digest: str = life_digest
        # lessons: situation-tagged takeaways from lived experience, cap
        # MAX_LESSONS (see above) — written by Reflect(), consumed by
        # cognition/dialogue when the current situation matches.
        self.lessons: list[dict] = [] if lessons is None else lessons
        # mind: one-time-authored permanent identity paragraph, core
        # cast only, "" until they join — see MAX_MIND_TEXT_CHARS above.
        self.mind: str = mind
        # voice: v0.87.12, "per-agent voice" (docs/IDEAS-2026-07-
        # EMERGENCE.md §7) — one short line of manner-of-speaking
        # (cadence, a favorite figure of speech, a verbal habit),
        # authored at the same one-time genesis call as `mind` (zero
        # added LLM volume — see llm/mind.py's widened schema). Garnish
        # for dialogue/letters, never mechanically consumed — the point
        # is a reader recognizing who's talking before the name.
        self.voice: str = voice
        # occupation: v0.87.44 jobs/economy batch — a real profession
        # (baker/builder/banker/teacher/priest/mayor/fisherman/farmer/
        # shopkeeper/businessman, see agents/occupations.py) that gates
        # actual mechanical bonuses at the matching building, not a
        # cosmetic label. "" until deterministically assigned (see
        # Population._maybe_assign_occupation) — a newborn/migrant is
        # occupationless until old enough and a settlement need exists.
        self.occupation: str = occupation
        # skills: procedural teachable know-how, name -> proficiency 0..1
        # (SKILL_FARMING/CONSTRUCTION/MEDICINE) — distinct from beliefs.
        self.skills: dict[str, float] = {} if skills is None else skills
        # traits: compact bounded (-1..1) personality vector (resilience/
        # sociability/ambition/openness); absent keys read 0.0.
        self.traits: dict[str, float] = {} if traits is None else traits
        # travel_target: long-range destination that overrides goal-
        # directed movement until reached (fission journeys); a
        # critically hungry traveler still detours for food first.
        self.travel_target = travel_target
        # beliefs: this agent's own evolving theories, same entry shape as
        # Settlement.beliefs, capped at llm/beliefs.MAX_PERSONAL_BELIEFS.
        self.beliefs: list[dict] = [] if beliefs is None else beliefs
        # emotions: fast-changing 0..1 affect vector (Phase I, see
        # bump_emotion/decay_emotions above) — missing keys read 0.0,
        # same convention as traits. Decayed every tick, bumped at
        # specific lived events; never persisted at a size beyond 4 keys
        # (bounded by EMOTION_* constants themselves, no separate cap
        # needed the way memories/beliefs need MAX_*).
        self.emotions: dict[str, float] = {} if emotions is None else emotions
        # ledger: the shared substrate for relationships/trust/debts/
        # relationship_flags/grievances (Phase 0, agents/ledger.py) —
        # seeded from whichever of the five constructor args were
        # passed (from_dict reconstruction, or a legacy direct-
        # construction call site), then each of the five attributes
        # below is a live dict-like view over it. debts: Phase L
        # "Economy depth" — id -> abstract amount THIS agent owes that
        # source, written only by `_record_debt` (agents/population.py).
        # Decays slowly every tick EXCEPT past `DEBT_SIGNIFICANT_
        # THRESHOLD` (see decay_debts) so an old, small debt reads as
        # forgiven while a real standing obligation doesn't. relation
        # ship_flags: "Definitive checklist" Tier 0.1 — id -> "feud"
        # (the only flag written so far). A flagged pair is exempted
        # from `Population._update_relationships`'s ambient decay
        # entirely: a hardened feud holds at whatever depth it
        # deepened to until an explicit reconcile/council_ruling clears
        # it. grievances: Tier 0.2 — id -> a small (MAX_GRIEVANCE_
        # TAGS_PER_SOURCE), FIFO-capped list of concrete wrongs
        # suffered from that source, distinct from the numeric scalars
        # (HOW MUCH vs. WHAT) and from the churning 8-slot `memories`
        # log — a protected store untouched by MAX_AGENT_MEMORIES
        # eviction, cleared only by explicit reconciliation.
        self.ledger = Ledger()
        for other_id, value in (relationships or {}).items():
            self.ledger.get_or_create(other_id).fondness = value
        for other_id, value in (trust or {}).items():
            self.ledger.get_or_create(other_id).trust = value
        for other_id, value in (debts or {}).items():
            self.ledger.get_or_create(other_id).debt = value
        for other_id, value in (relationship_flags or {}).items():
            self.ledger.get_or_create(other_id).flag = value
        for other_id, value in (grievances or {}).items():
            self.ledger.get_or_create(other_id).grievances = list(value)
        self.relationships = self.ledger.fondness_view
        self.trust = self.ledger.trust_view
        self.debts = self.ledger.debt_view
        self.relationship_flags = self.ledger.flag_view
        self.grievances = self.ledger.grievance_view
        # standing_penalty: §1 "deviance loop" (docs/IDEAS-2026-07-
        # EMERGENCE.md) — a bounded 0..1 civic penalty applied by an
        # "ostracism" dispute outcome (`Population.apply_dispute`),
        # deterministically targeted at whichever party the town's own
        # existing reputation() read already regards worse. Gates
        # SOCIALIZE targeting (`_nearest_other_agent`) and council
        # candidacy while it stands; decays monthly like a trait
        # (`Population._tick_traits`), never reset abruptly.
        self.standing_penalty: float = standing_penalty
        # stuck_ticks: consecutive ticks a goal-directed target has existed
        # but the greedy step in Population._dispatch_movement/_step_toward
        # failed to move the agent toward it (blocked by a concave water/
        # mountain pocket, not merely "already there") — once this crosses
        # MOVEMENT_STUCK_TICKS_THRESHOLD, movement escalates to one bounded
        # BFS step (_bfs_step) instead of leaving the agent to random-walk
        # near a target it can see but can't greedily reach. Reset to 0 on
        # any successful greedy step or when there's no target. See
        # docs/DECISIONS.md, "movement: stuck-agent BFS escape" pass.
        self.stuck_ticks: int = stuck_ticks
        # last_move_dx/dy: the (dx, dy) of this agent's most recent
        # random-walk step (Population._maybe_move only — goal-directed
        # greedy/BFS steps don't touch this). Live report: undirected
        # wandering visibly paces back and forth ("goes up-down one tile
        # or left-right one tile") because _NEIGHBOR_OFFSETS only has 4
        # cardinal directions, so a uniform-random walk reverses its own
        # last step 1-in-4 times — noticeable specifically because there
        # are only 4 choices, not 8. _maybe_move deprioritizes stepping
        # straight back the way it came (falls back to it only if no
        # other walkable candidate exists), which is enough to make
        # idle wandering read as actually going somewhere instead of
        # oscillating in place. (0, 0) means "no recent random-walk step
        # yet" (fresh agent, or its last move was goal-directed)."""
        self.last_move_dx: int = last_move_dx
        self.last_move_dy: int = last_move_dy
        # seek_target_id: the specific agent id a SEEK_PERSON goal is
        # currently walking toward (v0.87.8) — None for every other
        # goal. Cleared by Population._dispatch_movement on arrival
        # (same tile as the target) or if the target no longer exists
        # (death/settlement change), same "target becomes unreachable ->
        # goal quietly lapses" shape `Agent.travel_target` already has.
        self.seek_target_id: int | None = seek_target_id
        # mourning_ticks_remaining/mourning_target: v0.87.9, "ceremonies
        # agents attend: funerals" — set on a kin/bonded survivor by
        # Population._apply_deaths (mourning_target = the deceased's
        # grave position, same tile `add_memorial` records), counted
        # down by Population._tick_mourning until it reaches 0, at
        # which point grief eases (MOURNING_GRIEF_EASE) and both fields
        # reset. While nonzero, Population._dispatch_movement biases
        # this agent's movement toward the grave instead of their
        # normal goal — same override-priority shape as `travel_target`
        # but persists at the destination (a gathering, not a one-shot
        # errand) rather than clearing itself the instant it arrives.
        self.mourning_ticks_remaining: int = mourning_ticks_remaining
        self.mourning_target: tuple[int, int] | None = mourning_target
        # wedding_ticks_remaining/wedding_target: v0.87.10, the companion
        # "ceremony" to mourning above — set on a newly-bonded couple
        # plus their gathered kin/bonded well-wishers by Population.
        # _maybe_reproduce (wedding_target = the position where the
        # couple's first child was born, the same tile the new FAMILY
        # institution forms at), counted down by Population._tick_
        # weddings until it reaches 0, at which point every guest gets a
        # joy bump (WEDDING_JOY_BUMP) and both fields reset. Same
        # override-priority/gathering shape as mourning, just shorter
        # (WEDDING_DURATION_TICKS) and joyful rather than grieving.
        self.wedding_ticks_remaining: int = wedding_ticks_remaining
        self.wedding_target: tuple[int, int] | None = wedding_target
        # plan: v0.87.15, "bounded episodic planning — ambitions get
        # teeth" (docs/IDEAS-2026-07-EMERGENCE.md §7). `None` until the
        # Reflect() job (`SimulationEngine._maybe_schedule_personal_
        # belief`) decides a situation warrants one; a dict of {"intent":
        # str, "horizon_days": int, "days_remaining": int, "progress_
        # note": str, "formed_tick": int} while active. Consumed as one
        # cognition-prompt line (llm/cognition.build_prompt) and a small
        # deterministic goal-bias in the fallback path (`fallback_goal`'s
        # `plan_intent` param) — a multi-week arc that outlives any
        # single day's goal reevaluation, unlike `goal`/`goal_reason`
        # which reset every cognition cycle. Ticked down daily by
        # `Population.tick_plans`, cleared (reverts to None) once
        # `days_remaining` reaches 0 — "expiring," not "failing"; Reflect
        # () may form a fresh one afterward if warranted.
        self.plan: dict | None = plan
        # long_term_goal: Phase 1.B "self-evolving world" (docs/VISION-
        # 2026-07-21-SELFEVOLVING.md) — `None` until a real life event
        # (a hardened dispute outcome, a bonded partner/family death, a
        # child born) makes this agent eligible for Reflect() to name
        # one; a dict of {"goal": str, "formed_tick": int} while active.
        # Deliberately NOT time-limited like `plan` — an ambition
        # doesn't expire on a schedule, only when life genuinely moves
        # past it (the LLM may revise or drop it on a later eligible
        # Reflect() call). `plan` is the near-term STEP toward this;
        # this is the standing WHY. Core cast only in practice (Reflect
        # ()'s candidate pool). See `life_event_since_goal` below and
        # `SimulationEngine._run_personal_belief`.
        self.long_term_goal: dict | None = long_term_goal
        # life_event_since_goal: server-enforced eligibility gate — set
        # True at the handful of call sites that are genuinely "a life
        # event" (apply_dispute's outcomes, bonded/family death grief,
        # a child born), consumed (reset False) the next time Reflect()
        # actually runs for this agent. `_run_personal_belief` only
        # applies a parsed `long_term_goal` when this is True — the
        # model's own prompt asks it to only rarely offer one, but this
        # is the real guarantee, same "closed-choice enforced server-
        # side, never just a prompt instruction" discipline as every
        # other constrained field in this codebase.
        self.life_event_since_goal: bool = life_event_since_goal
        # hardened_traits/extreme_event_count (Phase 3.B, "identity,
        # irreversible change" — docs/VISION-2026-07-21-SELFEVOLVING.md):
        # a trait name in `hardened_traits` is exempt from `Population.
        # _tick_traits`'s monthly mean-reversion — a real, permanent
        # personality shift, not another bounded nudge. `extreme_event_
        # count` is the server-side counter driving it (see
        # `Population._maybe_harden_trait`); a small number of genuinely
        # extreme events (a survived disaster, a hardened feud, a
        # bonded-partner death) crosses a threshold and locks TRAIT_
        # RESILIENCE in place — same "closed-choice enforced server-
        # side" discipline as `life_event_since_goal` above.
        self.hardened_traits: set[str] = set() if hardened_traits is None else hardened_traits
        self.extreme_event_count: int = extreme_event_count
        # core_memories/core_memory_salience: v0.87.16, "deepen long-
        # term historical identity" — see MAX_CORE_MEMORIES's docstring.
        # Index-aligned pair, same discipline as memories/memory_
        # salience; written only by Population._remember's eviction
        # branch, never truncated except by its own small cap.
        self.core_memories: list[str] = [] if core_memories is None else core_memories
        self.core_memory_salience: list[float] = (
            [] if core_memory_salience is None else core_memory_salience
        )

    # --- native-store attach + scalar properties ---------------------------

    def _attach(self, store: "object | None") -> None:
        """Adopt this agent's scalars into a native `AgentStore` (owned by
        `Population`). No-op when `store` is None — the pure-Python
        fallback, where scalars stay in the `_x`/... locals. After a
        successful attach the store is the source of truth; the locals
        are left as harmless shadows and the properties below never read
        them again (they dispatch on `self._store`)."""
        if store is None:
            return
        store.add(
            self.id, self._x, self._y, self._hunger, self._energy,
            STATE_TO_CODE[self._state], self._age_ticks, self._max_age_ticks,
            self._starving_ticks, self._sick_ticks, self._immune_ticks,
            GOAL_TO_CODE[self._goal], self._settlement_id,
        )
        self._store = store

    @property
    def x(self) -> int:
        s = self._store
        return self._x if s is None else s.get_x(self.id)

    @x.setter
    def x(self, v: int) -> None:
        s = self._store
        if s is None:
            self._x = v
        else:
            s.set_x(self.id, v)

    @property
    def y(self) -> int:
        s = self._store
        return self._y if s is None else s.get_y(self.id)

    @y.setter
    def y(self, v: int) -> None:
        s = self._store
        if s is None:
            self._y = v
        else:
            s.set_y(self.id, v)

    @property
    def hunger(self) -> float:
        s = self._store
        return self._hunger if s is None else s.get_hunger(self.id)

    @hunger.setter
    def hunger(self, v: float) -> None:
        s = self._store
        if s is None:
            self._hunger = v
        else:
            s.set_hunger(self.id, v)

    @property
    def energy(self) -> float:
        s = self._store
        return self._energy if s is None else s.get_energy(self.id)

    @energy.setter
    def energy(self, v: float) -> None:
        s = self._store
        if s is None:
            self._energy = v
        else:
            s.set_energy(self.id, v)

    @property
    def state(self) -> AgentState:
        s = self._store
        return self._state if s is None else CODE_TO_STATE[s.get_state(self.id)]

    @state.setter
    def state(self, v: AgentState) -> None:
        s = self._store
        if s is None:
            self._state = v
        else:
            s.set_state(self.id, STATE_TO_CODE[v])

    @property
    def age_ticks(self) -> int:
        s = self._store
        return self._age_ticks if s is None else s.get_age_ticks(self.id)

    @age_ticks.setter
    def age_ticks(self, v: int) -> None:
        s = self._store
        if s is None:
            self._age_ticks = v
        else:
            s.set_age_ticks(self.id, v)

    @property
    def max_age_ticks(self) -> int:
        s = self._store
        return self._max_age_ticks if s is None else s.get_max_age_ticks(self.id)

    @max_age_ticks.setter
    def max_age_ticks(self, v: int) -> None:
        s = self._store
        if s is None:
            self._max_age_ticks = v
        else:
            s.set_max_age_ticks(self.id, v)

    @property
    def starving_ticks(self) -> int:
        s = self._store
        return self._starving_ticks if s is None else s.get_starving_ticks(self.id)

    @starving_ticks.setter
    def starving_ticks(self, v: int) -> None:
        s = self._store
        if s is None:
            self._starving_ticks = v
        else:
            s.set_starving_ticks(self.id, v)

    @property
    def sick_ticks(self) -> int:
        s = self._store
        return self._sick_ticks if s is None else s.get_sick_ticks(self.id)

    @sick_ticks.setter
    def sick_ticks(self, v: int) -> None:
        s = self._store
        if s is None:
            self._sick_ticks = v
        else:
            s.set_sick_ticks(self.id, v)

    @property
    def immune_ticks(self) -> int:
        s = self._store
        return self._immune_ticks if s is None else s.get_immune_ticks(self.id)

    @immune_ticks.setter
    def immune_ticks(self, v: int) -> None:
        s = self._store
        if s is None:
            self._immune_ticks = v
        else:
            s.set_immune_ticks(self.id, v)

    @property
    def goal(self) -> AgentGoal:
        s = self._store
        return self._goal if s is None else CODE_TO_GOAL[s.get_goal(self.id)]

    @goal.setter
    def goal(self, v: AgentGoal) -> None:
        s = self._store
        if s is None:
            self._goal = v
        else:
            s.set_goal(self.id, GOAL_TO_CODE[v])

    @property
    def settlement_id(self) -> int:
        s = self._store
        return self._settlement_id if s is None else s.get_settlement_id(self.id)

    @settlement_id.setter
    def settlement_id(self, v: int) -> None:
        s = self._store
        if s is None:
            self._settlement_id = v
        else:
            s.set_settlement_id(self.id, v)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "hunger": round(self.hunger, 4),
            "energy": round(self.energy, 4),
            "state": self.state.value,
            "age_ticks": self.age_ticks,
            "max_age_ticks": self.max_age_ticks,
            "starving_ticks": self.starving_ticks,
            "sick_ticks": self.sick_ticks,
            "immune_ticks": self.immune_ticks,
            "relationships": {str(k): round(v, 4) for k, v in self.relationships.items()},
            "trust": {str(k): round(v, 4) for k, v in self.trust.items()},
            "inventory": {k: round(v, 4) for k, v in self.inventory.items()},
            "parents": list(self.parents) if self.parents is not None else None,
            "goal": self.goal.value,
            "goal_reason": self.goal_reason,
            "memories": list(self.memories),
            "memory_salience": [round(v, 4) for v in self.memory_salience],
            "memory_causes": list(self.memory_causes),
            "working_memory": list(self.working_memory),
            "semantic_memories": list(self.semantic_memories),
            "secrets": list(self.secrets),
            "life_digest": self.life_digest,
            "lessons": list(self.lessons),
            "mind": self.mind,
            "voice": self.voice,
            "occupation": self.occupation,
            "skills": {k: round(v, 4) for k, v in self.skills.items()},
            "traits": {k: round(v, 4) for k, v in self.traits.items()},
            "beliefs": list(self.beliefs),
            "settlement_id": self.settlement_id,
            "travel_target": list(self.travel_target) if self.travel_target is not None else None,
            "emotions": {k: round(v, 4) for k, v in self.emotions.items()},
            "debts": {str(k): round(v, 4) for k, v in self.debts.items()},
            "relationship_flags": {str(k): v for k, v in self.relationship_flags.items()},
            "grievances": {str(k): list(v) for k, v in self.grievances.items()},
            # ledger_extra: the two Phase 0 additions with no legacy
            # dict of their own — promises (Phase 2) / history_tags —
            # only entries that actually have one or the other, keyed
            # separately from the five legacy keys above so their
            # shape stays exactly what it always was.
            "ledger_extra": {
                str(other_id): {"promises": list(edge.promises), "history_tags": sorted(edge.history_tags)}
                for other_id, edge in self.ledger.edges.items()
                if edge.promises or edge.history_tags
            },
            "stuck_ticks": self.stuck_ticks,
            "last_move_dx": self.last_move_dx,
            "last_move_dy": self.last_move_dy,
            "seek_target_id": self.seek_target_id,
            "mourning_ticks_remaining": self.mourning_ticks_remaining,
            "mourning_target": list(self.mourning_target) if self.mourning_target is not None else None,
            "wedding_ticks_remaining": self.wedding_ticks_remaining,
            "wedding_target": list(self.wedding_target) if self.wedding_target is not None else None,
            "plan": dict(self.plan) if self.plan is not None else None,
            "long_term_goal": dict(self.long_term_goal) if self.long_term_goal is not None else None,
            "life_event_since_goal": self.life_event_since_goal,
            "hardened_traits": sorted(self.hardened_traits),
            "extreme_event_count": self.extreme_event_count,
            "core_memories": list(self.core_memories),
            "core_memory_salience": [round(v, 4) for v in self.core_memory_salience],
            "standing_penalty": round(self.standing_penalty, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        parents = data.get("parents")
        memories = list(data.get("memories", []))
        # memory_salience must stay index-aligned with memories — a
        # legacy snapshot (predating v0.76.3) or any length mismatch is
        # defensively padded/truncated with the baseline rather than
        # trusted raw, so a resumed world never desyncs the two lists.
        memory_salience = list(data.get("memory_salience", []))
        if len(memory_salience) < len(memories):
            memory_salience += [MEMORY_SALIENCE_BASELINE] * (len(memories) - len(memory_salience))
        elif len(memory_salience) > len(memories):
            memory_salience = memory_salience[:len(memories)]
        # memory_causes: same index-alignment discipline as memory_
        # salience above — "" (no known cause) is the safe pad value.
        memory_causes = list(data.get("memory_causes", []))
        if len(memory_causes) < len(memories):
            memory_causes += [""] * (len(memories) - len(memory_causes))
        elif len(memory_causes) > len(memories):
            memory_causes = memory_causes[:len(memories)]
        _agent = cls(
            id=data["id"],
            name=data["name"],
            x=data["x"],
            y=data["y"],
            hunger=data["hunger"],
            energy=data["energy"],
            state=AgentState(data["state"]),
            age_ticks=data.get("age_ticks", 0),
            max_age_ticks=data.get("max_age_ticks", MAX_LIFESPAN_TICKS),
            starving_ticks=data.get("starving_ticks", 0),
            sick_ticks=data.get("sick_ticks", 0),
            immune_ticks=data.get("immune_ticks", 0),
            relationships={int(k): v for k, v in data.get("relationships", {}).items()},
            trust={int(k): v for k, v in data.get("trust", {}).items()},
            debts={int(k): v for k, v in data.get("debts", {}).items()},
            relationship_flags={int(k): v for k, v in data.get("relationship_flags", {}).items()},
            grievances={int(k): list(v) for k, v in data.get("grievances", {}).items()},
            inventory=dict(data.get("inventory", {})),
            parents=tuple(parents) if parents is not None else None,
            goal=AgentGoal(data.get("goal", AgentGoal.WANDER.value)),
            goal_reason=data.get("goal_reason", ""),
            memories=memories,
            memory_salience=memory_salience,
            memory_causes=memory_causes,
            working_memory=list(data.get("working_memory", [])),
            semantic_memories=list(data.get("semantic_memories", [])),
            secrets=list(data.get("secrets", [])),
            life_digest=data.get("life_digest", ""),
            lessons=list(data.get("lessons", [])),
            mind=data.get("mind", ""),
            voice=data.get("voice", ""),
            occupation=data.get("occupation", ""),
            skills=dict(data.get("skills", {})),
            traits=dict(data.get("traits", {})),
            beliefs=list(data.get("beliefs", [])),
            settlement_id=data.get("settlement_id", 0),
            travel_target=(
                tuple(data["travel_target"]) if data.get("travel_target") is not None else None
            ),
            emotions=dict(data.get("emotions", {})),
            stuck_ticks=data.get("stuck_ticks", 0),
            last_move_dx=data.get("last_move_dx", 0),
            last_move_dy=data.get("last_move_dy", 0),
            seek_target_id=data.get("seek_target_id"),
            mourning_ticks_remaining=data.get("mourning_ticks_remaining", 0),
            mourning_target=(
                tuple(data["mourning_target"]) if data.get("mourning_target") is not None else None
            ),
            wedding_ticks_remaining=data.get("wedding_ticks_remaining", 0),
            wedding_target=(
                tuple(data["wedding_target"]) if data.get("wedding_target") is not None else None
            ),
            plan=data.get("plan"),
            long_term_goal=data.get("long_term_goal"),
            life_event_since_goal=data.get("life_event_since_goal", False),
            hardened_traits=set(data.get("hardened_traits", [])),
            extreme_event_count=data.get("extreme_event_count", 0),
            core_memories=list(data.get("core_memories", [])),
            core_memory_salience=list(data.get("core_memory_salience", [])),
            standing_penalty=data.get("standing_penalty", 0.0),
        )
        for other_id_str, extra in data.get("ledger_extra", {}).items():
            edge = _agent.ledger.get_or_create(int(other_id_str))
            edge.promises = [dict(p) for p in extra.get("promises", [])]
            edge.history_tags = set(extra.get("history_tags", []))
        return _agent
