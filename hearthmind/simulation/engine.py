"""The simulation engine: an async tick loop that owns the World's lifecycle.

Design intent: this loop is the *only* thing that mutates the World. A
future browser interface talks to the engine (or a queue in front of it) to
read state or queue interventions — it never ticks the world itself and
never blocks the loop. This is what makes "closing the browser doesn't stop
the simulation" true by construction rather than by convention.

Phase B (LLM cognition) extends this without breaking that invariant: the
tick itself (`_tick_once`) stays fully synchronous and deterministic.
LLM-backed work (per-agent goal-setting, the seasonal chronicle) is kicked
off as fire-and-forget background tasks that run concurrently with future
ticks; their results are applied synchronously at the start of the *next*
`_tick_once`, never awaited inline in the tick path. See
docs/DECISIONS.md, B1/B2/B3.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import sqlite3
import time
from collections import deque
from typing import TYPE_CHECKING

try:
    import resource  # Unix-only; used for peak-RSS diagnostics, gracefully absent on Windows.
except ImportError:  # pragma: no cover — this project's target hardware is Linux
    resource = None  # type: ignore[assignment]

from hearthmind.agents.agent import (
    DIALOGUE_COOLDOWN_TICKS,
    DIALOGUE_SENTIMENT_DELTA,
    EMOTION_FEAR,
    EMOTION_GRIEF,
    FORAGE_HUNGER_THRESHOLD,
    PERSONAL_FOOD_CAPACITY,
    RIVALRY_THRESHOLD,
    SKILL_CONSTRUCTION,
    SKILL_FARMING,
    SKILL_INVENTION_BONUS_WEIGHT,
    SKILL_MEDICINE,
    TRAIT_AMBITION,
    TRAIT_RESILIENCE,
    TRAIT_SOCIABILITY,
    TRIGGERED_COGNITION_COOLDOWN_TICKS,
    AgentGoal,
    AgentState,
    _overlap_tokens,
    describe_emotion,
    describe_traits,
    dominant_emotion,
    faded_memory_text,
    push_secret,
    retrieval_diagnostics,
    retrieve_relevant_memories,
)
from hearthmind import __version__
from hearthmind.config import Config
from hearthmind.util import clamp, namespaced_rng, namespaced_roll
from hearthmind.llm import (
    artifacts,
    faction, fission, beliefs, caravan, chronicle, chronicler, consciousness, culture, culture_digest, dialogue,
    digest, dispute, documentary, dream, era_branch, festival, folklore, founding, geography, invention,
    memory_drift, mind,
    naming, narrative_direction, omens, religion, rumor_interpret, skill_mastery, summary, town_brain,
    diplomacy, laws, letters, noncore_nudge, institution_culture,
)
from hearthmind.llm.client import build_llm_client, fetch_llama_server_metrics
from hearthmind.llm.cognition import (
    RECENT_MEMORIES_IN_PROMPT, SURVIVAL_HUNGER_THRESHOLD, SYSTEM_PROMPT, build_prompt, fallback_goal, parse_goal,
)
from hearthmind.llm.jobs import CognitionRunner
from hearthmind.llm.recorder import TrainingRecorder
from hearthmind.persistence.snapshot import (
    agent_memory_log_count, consciousness_log_count, events_by_category, events_since_tick, history_events,
    load_latest_snapshot, log_agent_memory_entry, log_consciousness_entry, log_event, log_metrics,
    recent_agent_memory_log, recent_events, recent_events_diverse, recent_metrics, save_snapshot,
)
from hearthmind.agents.population import (
    DISPUTE_COOLDOWN_TICKS,
    FISSION_MATERIALS_SHARE,
    FISSION_MIN_DISTANCE,
    MAX_SETTLEMENTS,
    MIGRATION_BOND_THRESHOLD,
    POPULATION_CRITICAL_THRESHOLD,
    Population,
    _bridge_tiles_from_settlements,
    _nudge_trait,
    _pending_memory_evictions,
    _remember,
    _walkable_tiles,
)
from hearthmind.agents.occupations import (
    OCCUPATION_SHOPKEEPER,
    OCCUPATION_SURVEYOR,
    SHOPKEEPER_CARAVAN_YIELD_BONUS,
)
from hearthmind.settlement.buildings import (
    CULTURE_LIST_MAX_STORED,
    CURRENCY_CAPACITY,
    ERA_DESCRIPTIONS,
    FAMILY_FEUD_FESTIVAL_PENALTY,
    FESTIVAL_CHANCE_PER_MONTH,
    FESTIVAL_HUNGER_GATE,
    FOLKLORE_MAX_STORED,
    INVENTION_CHANCE_PER_SEASON,
    INVENTION_CURRENCY_THRESHOLD,
    INVENTION_KNOWLEDGE_MAX_TRACKED,
    INVENTION_MATERIALS_FRACTION,
    INVENTION_REDISCOVERY_CHANCE,
    LAWS_MAX_STORED,
    LAW_SIGNAL_THRESHOLD,
    LEXICON_MAX_STORED,
    MARKET_CARAVAN_CHANCE_MULTIPLIER,
    MARKET_CARAVAN_YIELD_MULTIPLIER,
    MATERIALS_CAPACITY,
    MEDICINE_CAPACITY,
    TOOLS_CAPACITY,
    CAMP_TOLERANCE,
    HUT_CAPACITY,
    NARRATIVE_THEMES_MAX_STORED,
    RITUAL_MAX_STORED,
    PATTERN_SIGNAL_BELIEF_THRESHOLD,
    RITUAL_PROMOTION_THRESHOLD,
    SHRINE_OMEN_CHANCE_MULTIPLIER,
    TEMPERAMENT_INVENTION_INFLUENCE,
    BuildingKind,
    BuildingStage,
    ERA_INFRASTRUCTURE_REQUIREMENTS,
    ERA_ORDER,
    INFRASTRUCTURE_INVENTION_BONUS_WEIGHT,
    Settlement,
    education_invention_bonus,
    era_for_tech_level_gated,
    era_infrastructure_progress,
    RELATION_DIALOGUE_NUDGE_SCALE,
    caravan_relation_factor,
    seed_relation,
    tick_market_prices,
    tick_mood,
    tick_player_standing,
    tick_relation,
    tick_temperament,
)
from hearthmind.settlement.institutions import (
    FAMILY_FEUD_MAX_STORED,
    FAMILY_FEUD_PROMOTION_THRESHOLD,
    InstitutionKind,
)
from hearthmind.settlement.vehicles import VehicleKind, VehicleStage
from hearthmind.world.state import (
    CONSCIOUSNESS_INTERVENTION_LOG_MAX,
    CONSCIOUSNESS_MEMORY_MAX,
    CONSCIOUSNESS_PLAYER_MODEL_MAX,
    CONSCIOUSNESS_REVISION_CONFIDENCE_GAIN,
    HIGHLIGHTS_MAX_STORED,
    TERRAIN_CHANGING_CATEGORIES,
    World,
)
from hearthmind.world.terrain import biome_counts


# Shared helpers (hearthmind/util.py) under their historical private
# names so this module's call sites are unchanged.
_namespaced_roll = namespaced_roll
_namespaced_rng = namespaced_rng

if TYPE_CHECKING:
    # Only imported for type hints — importing hearthmind.simulation.engine
    # must not require the `websockets` package unless the API is actually
    # enabled (see interface/api.py, server.py). See docs/DECISIONS.md, F1.
    from hearthmind.interface.api import WorldBroadcaster

logger = logging.getLogger("hearthmind.engine")

_CALENDAR_EVENT_DESCRIPTIONS = {
    "day_end": "A new day begins.",
    "week_end": "A new week begins.",
    "month_end": "A new month begins.",
    "season_end": "The season turns.",
    "year_end": "A new year begins.",
}

STALE_GOAL_RESULT_TICKS = 300
"""A cognition result older than this (scheduled ~3 sim-days ago at
default pacing) is dropped instead of applied — the hunger/energy
snapshot it reasoned from no longer describes the agent, and applying
it would steer them on days-old information. Only matters when the LLM
queue is saturated (see the backpressure gate below); a healthy run
resolves in well under one day. July 2026 architecture review, §3.6."""

STALE_DIALOGUE_RESULT_TICKS = 900
"""Same idea for dialogue results, with a looser bound — an exchange is
narrative more than steering, but applying a 'they just met' line nine
sim-days after the meeting still reads wrong."""

PROMPT_CULTURE_LIST_MAX = 5
"""How many of the newest traditions/inventions reach any single LLM
prompt. The lists themselves persist in full (they're the settlement's
history); this only bounds the *token* cost per call, which otherwise
grew forever on a multi-year world (July 2026 architecture review,
§3.7). Fallback numbering still uses the full list's length, so
"Tradition the 14th"-style names stay correct."""

OCCUPATION_MIN_SKILL = 0.25
"""v0.87.16, "occupation-shaped beliefs": how practiced a skill must be
before `SimulationEngine._occupation_for` names it as this agent's
trade — below SKILL_TEACHING_MIN_GAP's own 0.15 floor would call a
barely-dabbling agent "a farmer"; this sits comfortably above it."""

PROMPT_BELIEFS_MAX = 5
"""How many of the newest COUNCIL beliefs reach a `town_brain` prompt
— same "bound the prompt, not the store" shape as `PROMPT_CULTURE_
LIST_MAX`, added after a direct measurement (see docs/DECISIONS.md,
"prompt growth audit") found `chronicle`/`town_brain` were the two
prompts that actually grow with a long-running world. `Institution.
beliefs` has no digest mechanism (see `PROMPT_SETTLEMENT_BELIEFS_MAX`
below) — a plain-N-item institution is a much narrower thing than the
whole settlement, so this stays a recency slice."""

PROMPT_SETTLEMENT_BELIEFS_MAX = 2
"""How many of the newest SETTLEMENT beliefs (as opposed to council
beliefs, see `PROMPT_BELIEFS_MAX`) reach `chronicle`/`town_brain`
alongside `Settlement.belief_digest` — deliberately smaller than
`PROMPT_BELIEFS_MAX` now that the digest (see `llm.beliefs.parse_
digest`) already carries the gist of the *entire* current belief set;
these two are concrete grounding on top of it, not the only signal, the
same "digest for shape, a couple of specifics for grounding" split
`Agent.semantic_memories` established alongside raw `Agent.memories`.
Direct measurement (docs/DECISIONS.md, "prompt growth audit", worst-
case saturated state) found `chronicle`/`town_brain` sending the
*entire* capped belief list (`llm.beliefs.MAX_BELIEFS=12`, and `town_
brain` sends TWO such lists — settlement and council) unsliced at
~1291/~1442 tokens — more than half of `Config.llm_num_ctx=2560` on
the prompt alone, before the system prompt or the reserved `llm_num_
predict` response budget. `Settlement.beliefs` still persists its full
capped list; this only bounds what reaches the prompt itself."""

CULTURE_DIGEST_INPUT_MAX = 30
"""How many of the newest traditions/inventions/festivals/records reach
the `llm/culture_digest.py` job's own prompt — larger than `PROMPT_
CULTURE_LIST_MAX`/`PROMPT_SETTLEMENT_BELIEFS_MAX` (this job's whole
purpose is to see meaningfully more history than what already reaches
chronicle/town_brain directly), but far short of the 300-item storage
cap (`CULTURE_LIST_MAX_STORED`), so this genuinely-new-call-volume job
doesn't itself become an unbounded prompt on a long-running world."""

INTERPRET_RUMOR_MAX_PER_DAY = 3
"""Phase K's InterpretRumor() (docs/VISION-2026-07.md, "Knowledge &
Story") fires per listening event, not once a month like every other
settlement job — deliberately small, since this is real *added* call
volume on top of the existing daily budget, not a reuse of an existing
job slot. See `SimulationEngine._interpret_rumor_today` and
`_apply_pending_dialogue_results`."""

CONSCIOUSNESS_WEATHER_PRECIP_NUDGE_MAX = 0.12
CONSCIOUSNESS_WEATHER_TEMP_NUDGE_MAX_C = 1.5
"""`weather_nudge`'s bounds (Phase N) — small enough to stay well within
the smoothed range `compute_weather` actually realizes (measured
p10/p90 precipitation ~0.11-0.67, see world/weather.py's threshold
docstrings — the standing "unreachable threshold" lesson applies to
nudges too, not just fixed bands) and applied to `World.weather`
directly, so the very next tick's EMA blend carries it forward and lets
it decay naturally like any other tick-to-tick drift — no separate
"active nudge" state to track or expire."""

CONSCIOUSNESS_TEMPERAMENT_NUDGE_MAX = 0.15
"""`temperament_nudge`'s bound (Phase N) — folded into `tick_temperament`'s
new `extra` parameter, same small-magnitude-relative-to-the-visible-range
rationale as every other Phase G nudge (compare TEMPERAMENT_STEP_MAX)."""

MISPLACED_OBJECT_FRACTION = 0.4
"""`misplaced_object`'s bound (Phase N) — the fraction of the donor's
current stock of one inventory good (food/tools/medicine) that
relocates to a second agent's inventory. Deliberately partial, not the
donor's whole stock: "some of it went missing/turned up elsewhere"
reads as misplaced; "all of it" reads as theft, a different and much
less deniable story. A genuinely mechanical intervention (real
inventory quantities move, capped by the recipient's own capacity),
not narration-only — matching the deterministic-engine-provides-
reality design priority even for a Phase G-tier nudge."""

OBSERVER_ATTENTION_MAX_TRACKED = 25
"""§4 "observer attention as a signal into the Town Consciousness"
(docs/IDEAS-2026-07-EMERGENCE.md): cap on `World.observer_attention`'s
`agent_view_counts` dict — bounds it regardless of how many distinct
agents get inspected over a long session; the least-viewed entry is
evicted to make room for a newly-inspected agent once full."""

HIGHLIGHT_ZSCORE_WINDOW = 31
"""§5 "Anomaly/highlight log" (docs/IDEAS-2026-07-EMERGENCE.md): how many
recent daily `metrics` rows (including today's) `_detect_metric_
highlights` pulls to compute a rolling population mean/stdev — roughly a
sim-month, long enough for a meaningful baseline without smoothing out a
genuinely fast multi-day swing."""

HIGHLIGHT_POPULATION_Z_THRESHOLD = 2.5
"""How many standard deviations from its own recent mean a day's
population must swing to count as a highlight-worthy anomaly — high
enough that ordinary day-to-day noise (a birth or two, a death) doesn't
spam the log, per the idea doc's own "if the highlight log is boring,
the emergence isn't real yet" honesty test."""

CONSCIOUSNESS_GRUDGE_HARDSHIP_DELTA = 0.08
CONSCIOUSNESS_GRUDGE_CALM_DELTA = 0.04
"""§4 "the consciousness keeps a grudge ledger" — how far each real
player intervention nudges `World.consciousness_grudge_ledger`
(-1..1). Landing during a hardship context reads as help and moves it
warm by the larger delta; landing during a calm/plenty context reads
as meddling without cause and moves it cold by the smaller delta —
asymmetric on purpose (helping when it counts should register more
than being merely intrusive), same "easier to lose than earn" shape
`Agent.trust` already uses elsewhere in this project. See
`SimulationEngine._intervention_hardship_context`."""

PROMPT_RECENT_EVENTS = 40
"""How many recent events reach a settlement-level LLM prompt
(chronicle, tradition, invention, town-brain, etc.). Lowered 50 -> 30 in
the v0.71.1 CPU-only-Ollama-memory pass (the recent-events block was the
dominant term in the biggest prompt, ~680 of ~900 tokens at 50 events).
Restored to 50 in the v0.72.3 GPU-offload pass alongside `Config.
llm_num_ctx`'s 1280 -> 4096 raise. **Lowered again, 50 -> 40, in
v0.78.3** alongside `llm_num_ctx`'s own two live-diagnostic-driven
pull-backs (3072 -> 2560, see its docstring) — every call site here now
reads through `recent_events_diverse` (v0.78.0) rather than the raw
chronological stream, so 40 diverse (routine-capped) rows carry
comparable narrative signal to 50 undiverse ones did, at 20% less
prompt-token cost per call. Lower it further alongside `llm_num_ctx` if
you're on constrained CPU-only inference."""

_JOB_NO_ARGS = 0
_JOB_EVENTS = 1
_JOB_EVENTS_SEASON = 2
"""Argument conventions for `SimulationEngine._TICK_JOBS` entries (R2):
a per-tick scheduling method takes either no args, this tick's `events`
list, or `(events, previous_season)`. Kept as small int sentinels so the
dispatch loop is a cheap branch, not a reflection/inspect call."""

PROPHECY_RESOLUTION_WINDOW_TICKS = 480
"""§3 "self-fulfilling prophecy" (docs/IDEAS-2026-07-EMERGENCE.md): how
long a formed prophecy stays live (~5 sim-days at the default tick
rate) before `_resolve_prophecies` judges it confirmed/forgotten —
long enough for the village to plausibly act on it, short enough that
it reads as one bounded, self-contained moment rather than a
permanent background state."""

OBSERVER_ATTRIBUTION_WINDOW_TICKS = 960
"""§3 "the observer enters the theology" (docs/IDEAS-2026-07-
EMERGENCE.md): how recent a genuine `/intervene/*` call must be
(~10 sim-days) for `_maybe_schedule_beliefs` to invite the model to
optionally attribute something to a nameless "Quiet Neighbor" —
wide enough that a monthly-cadence beliefs job has a real chance to
land inside the window, narrow enough that this stays "the player just
did something," not a permanent ambient state."""

_PROPHECY_HARDSHIP_CATEGORIES = frozenset({
    "death", "theft", "illness", "disaster_flood", "disaster_wildfire", "disaster_heatwave",
})
_PROPHECY_PROSPERITY_CATEGORIES = frozenset({
    "birth", "building_completed", "vehicle_completed", "skill_mastered", "recovery",
})
"""`_resolve_prophecies`'s deterministic tally categories — reuses
`World.last_life_events`'s existing category vocabulary rather than
inventing a parallel one. Deliberately coarse/settlement-agnostic, same
looseness `_detect_ritual_signals`'s `shrine_mourning` pattern already
accepts."""

BACKPRESSURE_BACKLOG_PER_SLOT = 3
"""Scheduling gate: no new routine LLM jobs while the runner's backlog
(in-flight + queued) exceeds `llm_max_concurrent * this`. On the target
hardware one call takes ~17-20s and the engine can schedule several
jobs per 1s tick, so without this gate the task queue grows without
bound (unbounded memory) and every result arrives sim-days stale.
Event-*triggered* cognition (hunger emergency, fresh grief) is allowed
up to twice this bound — when rationing, the urgent reasoning goes
first. Deterministic runs are unaffected (fallbacks resolve instantly,
so the backlog stays ~0). July 2026 architecture review, §3.6."""

ADAPTIVE_LATENCY_ELEVATED_MS = 45_000
ADAPTIVE_LATENCY_SEVERE_MS = 80_000
"""Thresholds for `SimulationEngine._current_backpressure_limit`'s
adaptive load control (v0.81.0): p95 call latency at/above ELEVATED
halves the tolerated backlog, at/above SEVERE quarters it. Sized against
a live diagnostic showing p50/p95/max of 31.8s/69.8s/101.9s under real
load — ELEVATED sits above typical-healthy (~15-20s) but below that
observed p95, SEVERE sits just under the observed max, so a genuinely
struggling server (not just ordinary load) is what triggers the
tightest tier."""

LLM_PRESSURE_SLOWDOWN_START_RATIO = 1.0
LLM_PRESSURE_PAUSE_RATIO = 2.0
LLM_PRESSURE_MAX_SLOWDOWN = 6.0
"""Explicit standing directive (CLAUDE.md, "town consciousness is
important enough to trade off with simulation speed"): when the LLM
queue is genuinely saturated, `run_forever` now stretches — or fully
pauses — real time between ticks instead of only dropping the jobs that
can't get a slot (the existing `_settlement_job_backpressured`/
adaptive-backpressure machinery above is unchanged and still the actual
safety valve; this just tries to avoid needing it as often). A live
diagnostic showed `llm_backlog_effective` sitting at 12 against a
`_current_backpressure_limit()` of 6 — 2x over — with `calls_dropped_
backpressure` at 3006 against only 134 real calls attempted: the tick
loop kept generating new scheduling opportunities every ~1 real second
regardless of whether the 12 already-in-flight calls (each taking
20-40s on this hardware) had any chance to drain, so nearly every new
opportunity was born already-doomed to be dropped.

Ratio = `_effective_backlog() / _current_backpressure_limit()`.
Below `LLM_PRESSURE_SLOWDOWN_START_RATIO` (1.0, i.e. at/under the
adaptive limit): no change, ticks run at the configured/user-selected
speed. Between START_RATIO and `LLM_PRESSURE_PAUSE_RATIO` (2.0): the
real-time gap between ticks stretches linearly, up to `LLM_PRESSURE_
MAX_SLOWDOWN`x slower — fewer new ticks means fewer new agents becoming
"due" for cognition/dialogue per unit of real time (staggered-daily
eligibility is tick-count-based), which is what actually relieves
pressure, since the already-in-flight calls drain at their own
real-time pace regardless of tick rate. At/above PAUSE_RATIO: ticking
stops outright (`llm_pressure_paused()`) — same "poll at PAUSED_POLL_
SECONDS" mechanism the user-facing pause button already uses — until
backlog drains back under the ratio. This is deliberately still bounded
(never an unbounded stall): `_current_backpressure_limit()` itself only
ever shrinks so far (never below `llm_max_concurrent`), so a
sufficiently pathological backlog still eventually gets relieved by the
existing drop-based safety valve rather than stalling forever; this
mechanism only buys the *common* case (a bursty spike, not a wedged
server) a real chance to resolve via genuine LLM answers instead of
fallbacks. Surfaced in diagnostics/broadcast as `llm_pressure_ratio`/
`llm_pressure_paused` so the UI can show a "town is thinking" state
distinct from the user's own pause button. See docs/DECISIONS.md,
"LLM-pressure-aware tick pacing"."""

IDLE_BROADCAST_EVERY_TICKS = 10
"""With zero WebSocket clients connected, the full broadcast payload
(a to_dict() of every agent/building/farm/resource/wildlife entity plus
three summary passes) was still built every single tick, purely so
`GET /state` stayed fresh — on an always-running server that's
unobserved most of the time, that's the largest recurring per-tick
Python cost spent on nobody (audit perf pass). With no clients the
payload is instead rebuilt every this-many ticks, so a bare `/state`
poll is at most ~10s stale at default pacing; the moment a client
connects, per-tick broadcasting resumes on the next tick
automatically. Life events from skipped ticks are buffered (bounded by
PENDING_BROADCAST_EVENTS_MAX) so none are lost from the next payload."""

PENDING_BROADCAST_EVENTS_MAX = 300
"""Bound on the between-payload event buffer above — everything is
already persisted to the events table regardless (a reconnecting
client reloads history via GET /events), so trimming the oldest
buffered entries loses nothing durable."""

MONTHLY_JOB_DAY = {
    "chronicle": 1, "diplomacy": 2, "festival": 4, "laws": 5, "letter": 6, "caravan": 7, "fission": 8,
    "town_brain": 10,
    "beliefs": 13, "personal_belief": 16, "guild_founding": 19,
    "institution_belief": 22, "geography": 25, "folklore": 20, "dream": 23, "omen": 27, "faction": 26,
    "consciousness": 24, "memory_drift": 21, "noncore_nudge": 9,
}
"""Day-of-month (0-based; every value <= 27 so it exists even in
February) on which each monthly LLM job fires — the memory-pressure
follow-up to the v0.58.0 backpressure gate. That gate stopped the
month-end job cluster from growing an unbounded queue, but every
monthly job still *scheduled* on the same `month_end` tick, so twelve
times a year Ollama was pushed through a back-to-back burst of up to
~10 calls (v0.64.0 added three more jobs to the same tick) — at
llm_max_concurrent=2 and ~17-20s per real call, a minute-plus of
continuous inference with both KV-cache slots hot, which is precisely
the "sparse but sudden" swap-spike shape live reports kept showing
after every steady-state leak audit came back clean. Spreading the
jobs across the month keeps the exact same per-month LLM volume and
cadence while capping the *coincident* load at one routine job per
day (plus whatever event-driven work — dialogue, cognition, records —
happens to overlap). Deterministic month-end ticks (market prices,
temperament) stay on `month_end`: they cost no LLM call. Seasonal/
yearly jobs (tradition, invention, documentary) keep their own
boundaries — at most 3 coincident calls once a year versus the old
monthly ~10."""

MONTHLY_JOBS_WITH_RETRY = frozenset({
    "chronicle", "folklore", "town_brain", "beliefs", "personal_belief",
    "dream", "faction", "guild_founding", "institution_belief", "fission",
    "geography", "consciousness", "memory_drift", "diplomacy", "laws", "noncore_nudge", "letter",
})
"""Job names `_monthly_gate` grants a `MONTHLY_JOB_RETRY_WINDOW_DAYS`-day
window instead of one exact day — every monthly job EXCEPT festival/
caravan/omen (each has its own independent per-month RNG roll that must
stay a single evaluation, see MONTHLY_JOB_RETRY_WINDOW_DAYS). Must stay
in lockstep with which `_maybe_schedule_*` methods actually call `_mark_
monthly_resolved` — a job listed here without a matching `_mark_
monthly_resolved` call would re-run every day of its window forever
(never marks itself done); a job that calls `_mark_monthly_resolved` but
isn't listed here gets no benefit from it (still single-exact-day gated,
mark is simply never read)."""

MONTHLY_JOB_RETRY_WINDOW_DAYS = 3
"""How many consecutive days (starting at `MONTHLY_JOB_DAY[job]`)
`_monthly_gate` keeps offering a job a chance to run, for the subset of
monthly jobs with no RNG-gated "does this even happen" roll of their
own (chronicle, folklore, town_brain, beliefs, personal_belief, dream,
faction, guild_founding, institution_belief, fission, geography — see
`SimulationEngine._mark_monthly_resolved`'s call sites). Root cause
this fixes: a job previously got exactly ONE tick's chance per month —
if that single tick happened to land during a backpressured stretch, it
silently waited a FULL MONTH before trying again, unlike per-agent
cognition/dialogue (many staggered chances per day, so one unlucky tick
barely matters in aggregate). A live report of a settlement never once
forming a belief or a town-brain decision after 20,000 ticks (~7
monthly opportunities) traced to exactly this: each single-tick shot
losing the backpressure roll, month after month. Retrying for a few
days closes that gap without changing volume (still at most one real
call per job per month — `_mark_monthly_resolved` marks the job done
the instant backpressure clears, so getting through on day 2 of the
window doesn't also fire again on day 3). Deliberately NOT applied to
festival/caravan/omen — each has its own independent per-month RNG
"does this even happen" roll evaluated *before* their backpressure
check, and retrying those would re-roll the chance on subsequent days,
inflating the effective monthly probability beyond what `FESTIVAL_
CHANCE_PER_MONTH`/`CARAVAN_CHANCE_PER_MONTH`/`omens.OMEN_CHANCE_BASE`
were tuned for — those three keep their original single-tick-per-month
shape unchanged. See docs/DECISIONS.md, "monthly job retry window"."""

SEASON_YEAR_JOBS_WITH_RETRY = frozenset({
    "tradition", "religion", "narrative_direction", "culture_digest", "documentary",
    "institution_culture",
})
"""Same bug class as `MONTHLY_JOBS_WITH_RETRY`, found in a 2026-07 audit
but never fixed for the season/year cadence tier: `tradition`/
`religion`/`narrative_direction`/`culture_digest` (season_end) and
`documentary` (year_end) were still gated on a single exact tick
(`"season_end"/"year_end" in events`) with no retry window at all. A
backpressured boundary tick meant a FULL SEASON or YEAR of silent
loss — worse odds than the monthly jobs this pattern was originally
built for, since season/year boundaries are rarer to begin with. None
of these five have their own per-occurrence RNG "does this even
happen" roll gating the decision to call the LLM (unlike festival/
caravan/omen, which are deliberately excluded from the monthly
version) — each already always calls once its boundary/backpressure/
condition gates are met, so widening the window here doesn't inflate
any tuned probability, exactly like the monthly jobs' rationale.
**`invention` is deliberately excluded** despite being season_end-
gated too: unlike the other five, it rolls its own per-tick RNG chance
(`INVENTION_CHANCE_PER_SEASON` via `_namespaced_roll(..., "invention_
roll")`, tick-seeded) AFTER the boundary/prosperity gate — the same
shape as festival/caravan/omen's own exclusion from the monthly
version. Widening its window would re-roll that chance on every day of
the window, inflating the effective per-season invention probability
beyond what `INVENTION_CHANCE_PER_SEASON` was tuned for. See
`_season_year_gate`/`_mark_season_year_resolved`."""

SEASON_YEAR_JOB_RETRY_WINDOW_DAYS = 5
"""Retry window for `SEASON_YEAR_JOBS_WITH_RETRY` jobs, in days after
their boundary tick — wider than `MONTHLY_JOB_RETRY_WINDOW_DAYS` (3)
since a missed season/year opportunity is far more costly (the next
one is months away, not days) and these jobs fire far less often in
aggregate, so a few extra days of retry chances cost nothing on the
daily LLM ceiling."""

_TOKEN_CHARS_ESTIMATE = 4.0
"""Rough chars-per-token estimate for `llm_prompt_stats_summary`'s
token-count fields (English text, common BPE tokenizers average
roughly this) — deliberately NOT a real tokenizer count: this project
has no tokenizer dependency (llama.cpp's own is the source of truth,
and adding one here just to count tokens for telemetry is a real new-
dependency decision this pass didn't make unprompted). Good enough to
compare prompt sizes across job types and catch a regression; not
precise enough to size `llm_num_ctx` against exactly — use a live
`/diagnostics` reading against llama-server's own reported usage for
that (see LLM_PROMPT_STATS_WINDOW's docstring for the recommended next
step, a real llama-server `/slots`/`/metrics` poll)."""

LLM_PROMPT_STATS_WINDOW = 200
"""Rolling sample count `_llm_prompt_stats` keeps per job name — 2026-07
prompt-density audit. Bounded so this telemetry itself never becomes
an unbounded-growth source; 200 recent calls is enough for a stable
p95 read on any job that fires more than a handful of times per day.
These remain char-based estimates, not a real tokenizer count — as of
v0.87.6, real server-side KV-cache/queue numbers are available
alongside these estimates via `_llama_server_metrics` (see
`LLAMA_METRICS_POLL_SECONDS`/`_maybe_poll_llama_server_metrics`),
which polls `llama-server`'s own `/metrics` endpoint rather than
inferring from prompt/completion char counts. Deliberately does not
poll `/slots` (echoes live prompt content back — see `llm.client.
fetch_llama_server_metrics`'s docstring)."""

LLAMA_METRICS_POLL_SECONDS = 30.0
"""How often `run_forever` polls `llama-server`'s `/metrics` endpoint
(v0.87.6, the "poll /slots|/metrics" step v0.87.5 flagged as its
recommended next step) — a cheap local HTTP GET returning real
KV-cache/queue numbers (see `llm.client.fetch_llama_server_metrics`),
not the char-based estimates `llm_prompt_stats` uses. 30s is far
coarser than the tick loop; these numbers move slowly (KV-cache
occupancy tracks call volume, not individual ticks) and this is pure
diagnostics, so there is no liveness reason to poll more often. Only
polled when `config.llm_backend == "llamacpp"`; a no-op (`None`
stored) for the Ollama backend, which has no equivalent endpoint."""

PAUSED_POLL_SECONDS = 0.25
"""How often `run_forever`'s loop wakes up to re-check pause/stop state
while paused, instead of sleeping for a full (possibly very long, at a
low speed multiplier) tick interval — see interface/api.py's
WorldBroadcaster pause/speed fields and `_apply_intervention`'s note on
why pause/speed bypass the usual queued-intervention seam."""

# `_overlap_tokens` (keyword-overlap matching for `_matching_lesson`'s
# fallback) moved to hearthmind.agents.agent in v0.87.14 so the new
# `retrieve_relevant_memories` adaptive-retrieval function could share
# it without an engine->agent import-direction inversion — imported
# above instead of redefined here.

def _proc_status_mb(pid: str) -> dict | None:
    """VmRSS/VmSwap (MB) for one pid from /proc/<pid>/status, or None if
    unreadable (process exited, permission, non-Linux)."""
    try:
        fields = {}
        with open(f"/proc/{pid}/status") as handle:
            for line in handle:
                if line.startswith(("VmRSS:", "VmSwap:")):
                    key, value = line.split(":", 1)
                    fields[key] = round(int(value.split()[0]) / 1024, 1)  # kB -> MB
        return {"rss_mb": fields.get("VmRSS", 0.0), "swap_mb": fields.get("VmSwap", 0.0)}
    except OSError:
        return None


_LLM_SERVER_COMM_SUBSTRINGS = ("ollama", "llama-server", "llama-cli", "llama.cpp")
"""Process-comm substrings that identify the local LLM server, whichever
backend is configured (v0.72.0 added the llama-server names alongside
the original ollama-only match — see `Config.llm_backend`)."""


def system_memory_report() -> dict | None:
    """Best-effort Linux memory attribution for `/diagnostics` — the
    instrument every swap-pressure investigation so far has had to
    reconstruct by hand from the user's `ps`/`free` output. Reports this
    process's current RSS+swap, the same for every process whose comm
    matches `_LLM_SERVER_COMM_SUBSTRINGS` (Ollama's server + per-model
    runner, or llama.cpp's `llama-server`), and the system-wide
    MemAvailable/swap picture from /proc/meminfo — so one pasted report
    answers "who owns the memory right now" instead of only this
    process's peak RSS (which has repeatedly probed clean while the LLM
    server held the real weight; see CLAUDE.md's diagnostic history). A
    stat+read per process on demand only (never per-tick); returns None
    off Linux. Key stays `ollama_processes` for UI/README backward
    compatibility even though it now also covers llama-server."""
    if not os.path.isdir("/proc"):
        return None
    report: dict = {"self": _proc_status_mb("self"), "ollama_processes": []}
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/comm") as handle:
                    comm = handle.read().strip()
            except OSError:
                continue
            comm_lower = comm.lower()
            if not any(needle in comm_lower for needle in _LLM_SERVER_COMM_SUBSTRINGS):
                continue
            status = _proc_status_mb(pid)
            if status is not None:
                report["ollama_processes"].append({"pid": int(pid), "comm": comm, **status})
    except OSError:
        pass
    try:
        meminfo = {}
        with open("/proc/meminfo") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    meminfo[key] = round(int(value.split()[0]) / 1024, 1)
        report["system"] = {
            "mem_total_mb": meminfo.get("MemTotal"),
            "mem_available_mb": meminfo.get("MemAvailable"),
            "swap_used_mb": (
                round(meminfo["SwapTotal"] - meminfo["SwapFree"], 1)
                if "SwapTotal" in meminfo and "SwapFree" in meminfo else None
            ),
            "swap_total_mb": meminfo.get("SwapTotal"),
        }
    except OSError:
        report["system"] = None
    return report


_MIGRATIONS = {
    # subsystem name -> (description template, count-of-what-was-backfilled).
    # One entry per subsystem `World.from_dict` can backfill (see its
    # `migrated_subsystems` docstring) — kept as a single dict rather than
    # two separate ones so adding a subsystem can't forget one half.
    "population": (
        "{count} inhabitants appeared, settling a world that predates Milestone 2.",
        lambda world: len(world.population.agents),
    ),
    "resources": (
        "{count} foraging grounds took root, added to a world that predates Phase A.",
        lambda world: len(world.resources.nodes),
    ),
    "settlement": (
        "Settlement tracking was added to a world that predates Phase C ({count} pre-existing structures assumed).",
        lambda world: len(world.settlement.buildings),
    ),
    "farms": (
        "Farming was added to a world that predates Phase D ({count} pre-existing fields assumed).",
        lambda world: len(world.farms.plots),
    ),
    "wildlife": (
        "{count} animal populations took root, added to a world that predates Phase A4.",
        lambda world: len(world.wildlife.herds),
    ),
    "roads": (
        "Road tracking was added to a world that predates Phase C5 ({count} pre-existing worn tiles assumed).",
        lambda world: len(world.roads.wear),
    ),
    "lakes": (
        "Rivers were carved and {count} lake(s) identified, added to a world that predates the hydrology pass.",
        lambda world: len(world.lakes),
    ),
}


def _generation_config_snapshot(config: Config) -> dict:
    """Training recorder's `generation_config` field (llm/recorder.py,
    v1.1.0 item 1) — the actual sampling/context knobs a call was made
    with, distinct from just the model name, so a future reviewer can
    tell "the model changed behavior" apart from "the config changed."
    Only includes knobs this project actually sets (no invented top_p/
    top_k/repeat_penalty — neither client sends those; see llm/
    client.py) plus the backend-specific fields that differ between
    Ollama and llama.cpp."""
    cfg: dict = {"backend": config.llm_backend, "temperature": config.llm_temperature}
    if config.llm_num_predict is not None:
        cfg["max_tokens"] = config.llm_num_predict
    if config.llm_num_ctx is not None:
        cfg["context_length"] = config.llm_num_ctx
    if config.llm_backend == "ollama":
        if config.llm_num_gpu is not None:
            cfg["num_gpu"] = config.llm_num_gpu
        if config.llm_num_thread is not None:
            cfg["num_thread"] = config.llm_num_thread
        cfg["use_mmap"] = config.llm_use_mmap
    return cfg


class SimulationEngine:
    def __init__(
        self, conn: sqlite3.Connection, config: Config, world: World,
        broadcaster: "WorldBroadcaster | None" = None,
    ):
        self.conn = conn
        self.config = config
        self.world = world
        self._stop_event = asyncio.Event()
        self._ticks_since_snapshot = 0
        self._broadcaster = broadcaster
        self._last_tick_duration_ms = 0.0
        self._tick_durations_ms: deque[float] = deque(maxlen=500)
        self._snapshots_saved = 0
        """Wall-clock time the most recent `_tick_once` took, in
        milliseconds, plus a rolling window of the last 500 for
        percentile stats — surfaced in the browser dev console
        (`_maybe_broadcast`'s `diagnostics` key) so a slow tick (LLM
        contention, a huge population) is visible without reading server
        logs. Purely diagnostic, never persisted. See docs/DECISIONS.md,
        diagnostics pass."""
        self._pending_broadcast_events: list[dict] = []
        """Events logged via `self._log` since the last broadcast —
        dialogue/rumor/chronicle/tradition/invention/festival/
        intervention/town-brain all resolve outside `World.tick()`
        (either at the top of the tick, before `world.tick()` runs, or
        on a completely different tick when their background LLM task
        happens to finish), so `World.last_life_events` never saw them
        and the live WebSocket feed silently dropped them — they only
        ever showed up via the one-shot `/events` fetch on page load.
        `_log` fixes that by also buffering here; `_maybe_broadcast`
        drains this into the payload's `life_events` and clears it. See
        docs/DECISIONS.md, "LLM-as-brain batch,\" fix: live event
        stream gap."""

        client = None
        if config.llm_enabled:
            client = build_llm_client(config)
        self._cognition_runner = CognitionRunner(client=client, max_concurrent=config.llm_max_concurrent)
        self._training_recorder = TrainingRecorder(
            archive_dir=config.recorder_archive_dir,
            model_name_provider=lambda: config.llm_model,
            hearthmind_version_provider=lambda: __version__,
            seed_provider=lambda: config.seed,
            generation_config_provider=lambda: _generation_config_snapshot(config),
        )
        """Permanent LLM training recorder (llm/recorder.py, §8) — OFF by
        default (see `RecordingPolicy.OFF`), started/stopped only via
        `/recorder/start`/`/recorder/stop` (interface/app.py) or the
        browser UI's Recorder panel. Every named LLM task funnels
        through `_record_llm_debug`, which is the recorder's one call
        site — see that method's docstring."""
        self._backpressure_limit = config.llm_max_concurrent * BACKPRESSURE_BACKLOG_PER_SLOT
        self._reserved_this_tick = 0
        """Jobs actually scheduled (a task created) so far THIS tick,
        reset to 0 at the top of every `_tick_once`. `CognitionRunner.
        backlog` only increments once a scheduled task's coroutine body
        starts running — which, since `_tick_once` is fully synchronous,
        can't happen until it returns and the event loop gets a turn — so
        within one tick, every `_maybe_schedule_*`/cognition/dialogue call
        site checking backlog for backpressure sees the SAME stale
        pre-tick value, even after several of them have already scheduled
        a job this same tick. On a tick where many jobs are eligible at
        once (the documented month-end settlement-job cluster, or a
        cognition+dialogue burst), that let more jobs through in a single
        tick than the concurrency-derived limit intended — observed live
        as `backlog` reaching 11 against a max_concurrent=1-derived limit
        of 3. Every real scheduling call site (`_schedule_llm_job`,
        `_schedule_due_cognition`, `_schedule_due_dialogue`, `_maybe_
        interpret_rumor`) increments this the instant it creates a task;
        every backpressure check adds it to `backlog` so a job scheduled
        two calls ago this same tick is visible to the next check, closing
        the staleness window to zero. See docs/DECISIONS.md, "backpressure
        reservation gap" pass."""
        self._prev_population_total: int | None = None
        """§5 "Anomaly/highlight log": population from the PREVIOUS
        `_log_daily_metrics` call, used only to detect a fresh crossing
        below `POPULATION_CRITICAL_THRESHOLD` (an extinction near-miss)
        rather than re-flagging every day the population stays low.
        Never persisted — a restart simply re-baselines from the first
        post-restart reading, which is fine since this only needs to
        catch a genuine fresh crossing, not survive a restart mid-crisis."""
        self._monthly_job_scheduled_month: dict[str, int] = {}
        """job name -> absolute month ordinal (year * months_per_year +
        month_index) it last got past its own backpressure check — lets
        `_monthly_gate` retry on the next couple of days if a job's first
        scheduled day was backpressured, instead of silently waiting a
        full month. See MONTHLY_JOB_RETRY_WINDOW_DAYS and `_mark_monthly_
        resolved`."""
        self._season_year_job_window: dict[str, tuple[int, int]] = {}
        """job name -> (window_open_tick, ordinal) captured the instant
        this job's boundary event (season_end/year_end) is crossed —
        `ordinal` distinguishes which season/year the window belongs to
        (so a job that got through in the first few days of the window
        doesn't also fire again later in the same window), the tick
        anchors `SEASON_YEAR_JOB_RETRY_WINDOW_DAYS`. See `_season_year_
        gate`/SEASON_YEAR_JOBS_WITH_RETRY."""
        self._season_year_job_scheduled_ordinal: dict[str, int] = {}
        """job name -> ordinal it last got past its own backpressure
        check — mirrors `_monthly_job_scheduled_month` for the season/
        year cadence tier. Set by `_mark_season_year_resolved`."""
        self._llama_server_restarting = False
        """Tracks the last-seen state of `config.llm_restart_sentinel_
        path` so `run_forever` can detect the absent->present edge and
        count a real restart (see `_llama_server_restarts`), rather than
        counting once per polling cycle the sentinel happens to still be
        there. See `llama_server_restarting()`."""
        self._llama_server_restarts = 0
        """How many times `scripts/run.sh`'s `LLAMA_RESTART_HOURS`
        supervisor has restarted llama-server since this process
        started (v0.87.3) — counted from the sentinel-file absent-
        >present edge, not persisted across a `hearthmind.server`
        restart itself, same "session stat" convention as `snapshots_
        saved`/`calls_dropped_backpressure`. Surfaced via `/diagnostics`
        and the live broadcast so "why did the town stop moving for a
        few seconds" has a real answer instead of reading as an
        unexplained stall."""
        self._llm_calls_today = 0
        """Ollama calls scheduled so far this sim-day (all kinds:
        cognition, dialogue, settlement jobs). Reset to 0 on `day_end`
        (see `_tick_once`); once it reaches `config.llm_max_calls_per_day`
        every further LLM decision that day resolves via its fallback.
        The belt-and-braces half of the v0.70.0 swap fix — see
        `_consume_llm_budget` and the config field's docstring."""
        self._interpret_rumor_today = 0
        """Phase K's InterpretRumor() count so far this sim-day, reset
        alongside `_llm_calls_today` on `day_end` — see INTERPRET_RUMOR_
        MAX_PER_DAY. Fires per listening event (not once a month like
        every other settlement job here), so it needs its own volume
        ceiling on top of the shared daily budget, same "per-agent/
        per-pair decision must be gated" rule as cognition/dialogue."""
        self._pending_goal_results: dict[int, tuple[int, dict, int | None]] = {}
        """agent_id -> (tick the job was scheduled on, result, seek_
        candidate_id) — the tick lets `_apply_pending_cognition_results`
        drop results that went stale in a saturated queue (STALE_GOAL_
        RESULT_TICKS). `seek_candidate_id` (v0.87.8) is the specific
        agent id `Population._seek_person_candidate` identified AT
        SCHEDULING TIME (captured in the same closure the prompt itself
        was grounded from) — only consumed by `apply_goal` when the
        parsed goal actually comes back as SEEK_PERSON; `None` for the
        inline deterministic-fallback path, which never offers this
        goal."""
        self._inflight_cognition_agent_ids: set[int] = set()
        self._pending_dialogue_results: list[tuple[int, int, int, dict, bool]] = []
        """(scheduled_tick, agent_a_id, agent_b_id, parsed) — same
        staleness convention as `_pending_goal_results`."""
        self._background_tasks: set[asyncio.Task] = set()
        self._last_llm_calls: dict[str, dict] = {}
        """Most recent prompt/result/fallback-flag for each named LLM
        job (town_brain, beliefs, omen, naming, chronicle, tradition,
        invention, festival, dialogue, cognition), keyed by job name —
        the concrete answer to "what prompt was given and what [the
        LLM] acted on it": exposed via `full_diagnostics()` so a live
        run's actual prompts/decisions are inspectable, not just their
        narrated side effects in the event log. Only the latest call
        per job is kept (bounded, not a growing history) — see
        `_record_llm_debug`. See docs/DECISIONS.md, "map/UI/ecology
        follow-up.\""""
        self._llama_server_metrics: dict[str, float] | None = None
        """Most recent successful `/metrics` poll of `llama-server`
        (v0.87.6, see `LLAMA_METRICS_POLL_SECONDS`/`_maybe_poll_llama_
        server_metrics`) — real server-side KV-cache/queue numbers,
        `None` until the first successful poll (or permanently, on the
        Ollama backend / an older llama-server without `--metrics`).
        Surfaced via `full_diagnostics()`; never blocks a tick, same
        fire-and-forget-background-task discipline as every LLM job."""
        self._llama_server_metrics_poll_started_at: float = 0.0
        """`time.monotonic()` timestamp the last metrics-poll task was
        started, real-time-gated (not tick-gated — this must keep
        polling even while `run_forever` is paused) by `_maybe_poll_
        llama_server_metrics`."""
        self._llm_prompt_stats: dict[str, dict] = {}
        """Rolling per-job-name prompt/completion size and latency
        telemetry (2026-07 prompt-density audit) — the measurement half
        of "treat prompt tokens as a scarce resource": every `_record_
        llm_debug` call folds in prompt/completion character counts (a
        cheap ~4-chars/token estimate, no tokenizer dependency added —
        see its own docstring for why) and, when available, call
        latency in ms, keyed by job name (`cognition`, `dialogue`,
        `chronicle`, `town_brain`, ...). Bounded: each job name keeps
        only a capped rolling deque of samples (`LLM_PROMPT_STATS_
        WINDOW`), never a growing history. Surfaced via `full_
        diagnostics()`'s `llm_prompt_stats` so a live run's actual
        token spend by prompt TYPE is measurable, not guessed at — the
        standing gap this audit found: `llm_stats.latency_ms_p50/p95`
        was already aggregate-only, with no way to tell whether a slow
        p95 traces to one verbose job type or all of them evenly."""
        self._naming_scheduled_ids: set[int] = set()
        """Settlement ids whose one-time background naming job has been
        scheduled (multi-settlement pass: was a single bool). The
        deterministic placeholder name (set inside World.tick the
        instant a settlement's first building stands) already satisfies
        every other system's `if not settlement.name: return` gate, so
        there's no retry logic here — either the LLM job runs once and
        (maybe) renames that settlement, or it doesn't and the
        placeholder stands forever, same as any other LLM-fallback
        outcome."""

        if self._broadcaster is not None:
            # Terrain never changes after creation — set once, not part
            # of the per-tick payload. See docs/DECISIONS.md, F2.
            self._broadcaster.set_terrain(
                world.terrain, world.config.width, world.config.height, mining_scars=world.mining_scars,
            )
            self._broadcaster.set_diagnostics_provider(self.full_diagnostics)

    @property
    def stop_event(self) -> asyncio.Event:
        """Exposed so a co-running loop (e.g. the WebSocket API server,
        see interface/api.py) can shut down in lockstep on Ctrl+C/SIGTERM
        rather than each needing its own signal wiring."""
        return self._stop_event

    @classmethod
    def load_or_create(
        cls, conn: sqlite3.Connection, config: Config, broadcaster: "WorldBroadcaster | None" = None,
        founding_scenario: str = "",
    ) -> "SimulationEngine":
        world = load_latest_snapshot(conn, runtime_config=config)
        if world is None:
            logger.info("No existing snapshot found — creating a new world (seed=%s).", config.seed)
            world = World.create_new(config, founding_scenario=founding_scenario)
            save_snapshot(conn, world)
            log_event(conn, tick=0, category="genesis", description="The world was created.")
        else:
            logger.info(
                "Resumed world at tick %s (%s, season=%s).",
                world.clock.tick_count, world.clock.date_string(), world.clock.season,
            )
            if world.migrated_subsystems:
                logger.info(
                    "Older save detected — backfilling subsystems: %s.",
                    ", ".join(world.migrated_subsystems),
                )
                for subsystem in world.migrated_subsystems:
                    description_template, count_of = _MIGRATIONS[subsystem]
                    log_event(
                        conn, tick=world.clock.tick_count, category=f"{subsystem}_migration",
                        description=description_template.format(count=count_of(world)),
                    )
                save_snapshot(conn, world)
        return cls(conn=conn, config=config, world=world, broadcaster=broadcaster)

    def request_stop(self) -> None:
        self._stop_event.set()

    def log_founding_scenario(self, scenario: str) -> None:
        """Called once, right after a brand-new world is created, with
        the one-time "genesis" LLM call's scenario text (see
        hearthmind.llm.world_genesis, server.py) — the same text whose
        hash chose this world's seed, so the description and the actual
        generated terrain/weather are at least thematically the same
        thing, not two unrelated random draws."""
        self._log("founding", f"Before the first stone was laid: {scenario}")

    def _consume_llm_budget(self) -> bool:
        """Try to spend one call against today's `llm_max_calls_per_day`
        ceiling. Returns True (and increments the counter) if budget
        remains, False if the day's ceiling is already hit. Every real
        Ollama call — cognition, dialogue, settlement job — routes
        through here first, so the ceiling is a true hard bound on daily
        Ollama throughput regardless of population or any future job.
        See `_llm_calls_today` and Config.llm_max_calls_per_day."""
        if self._llm_calls_today >= self.config.llm_max_calls_per_day:
            return False
        self._llm_calls_today += 1
        return True

    def _effective_backlog(self) -> int:
        """`CognitionRunner.backlog` (jobs whose coroutine has actually
        started) plus `_reserved_this_tick` (jobs scheduled earlier this
        same tick but not yet started) — see `_reserved_this_tick`'s
        docstring for why the raw counter alone understates same-tick
        load. Every backpressure check reads this instead of `self.
        _cognition_runner.backlog` directly."""
        return self._cognition_runner.backlog + self._reserved_this_tick

    def _current_backpressure_limit(self) -> int:
        """Adaptive load control (v0.81.0): scales the static,
        concurrency-derived `_backpressure_limit` down when the LLM
        server is measurably running slow, so a saturated queue doesn't
        keep admitting jobs at a rate the hardware has already shown it
        can't clear in reasonable time — tightening proactively rather
        than only reactively (the static limit still drops jobs once hit,
        but by then every admitted job downstream is also waiting behind
        a now-longer queue). Reads `CognitionRunner.stats()`'s existing
        rolling p95 latency — already tracked for `/diagnostics`, no new
        state. Recovers back to the full static limit automatically once
        latency comes back down (the rolling window in `CognitionRunner`
        is a fixed-size deque of the most recent calls, so this always
        reflects *current* conditions, not history from hours ago).
        Never drops below `llm_max_concurrent` — a live server should
        always get to attempt at least one job per concurrency lane."""
        p95 = self._cognition_runner.stats()["latency_ms_p95"]
        floor = self.config.llm_max_concurrent
        if p95 >= ADAPTIVE_LATENCY_SEVERE_MS:
            return max(floor, self._backpressure_limit // 4)
        if p95 >= ADAPTIVE_LATENCY_ELEVATED_MS:
            return max(floor, self._backpressure_limit // 2)
        return self._backpressure_limit

    def llm_pressure_ratio(self) -> float:
        """`_effective_backlog() / _current_backpressure_limit()` — 1.0
        means the queue is exactly at the (already-adaptive) limit, 2.0
        means double over. `run_forever` uses this to slow/pause ticking
        — see LLM_PRESSURE_SLOWDOWN_START_RATIO's docstring. 0.0 if the
        limit is somehow 0 (shouldn't happen — `llm_max_concurrent` is
        always >= 1 — but a division guard costs nothing)."""
        limit = self._current_backpressure_limit()
        if limit <= 0:
            return 0.0
        return self._effective_backlog() / limit

    def llm_pressure_paused(self) -> bool:
        """True when `run_forever` should skip ticking entirely this
        cycle — the LLM backlog is saturated enough that generating more
        scheduling opportunities right now would just feed the drop
        counter rather than genuine LLM answers. See LLM_PRESSURE_
        PAUSE_RATIO."""
        return self.llm_pressure_ratio() >= LLM_PRESSURE_PAUSE_RATIO

    def _llm_pressure_interval_multiplier(self) -> float:
        """How much longer than normal `run_forever` should wait before
        the next tick, given current LLM backlog pressure — 1.0 below
        `LLM_PRESSURE_SLOWDOWN_START_RATIO`, scaling linearly up to
        `LLM_PRESSURE_MAX_SLOWDOWN` as pressure approaches `LLM_PRESSURE_
        PAUSE_RATIO` (at/beyond which `llm_pressure_paused()` takes over
        and ticking stops outright, making this multiplier moot)."""
        ratio = self.llm_pressure_ratio()
        if ratio <= LLM_PRESSURE_SLOWDOWN_START_RATIO:
            return 1.0
        span = LLM_PRESSURE_PAUSE_RATIO - LLM_PRESSURE_SLOWDOWN_START_RATIO
        if span <= 0:
            return 1.0
        progress = min(1.0, (ratio - LLM_PRESSURE_SLOWDOWN_START_RATIO) / span)
        return 1.0 + progress * (LLM_PRESSURE_MAX_SLOWDOWN - 1.0)

    def llama_server_restarting(self) -> bool:
        """True while `config.llm_restart_sentinel_path` exists on disk —
        `scripts/run.sh`'s `LLAMA_RESTART_HOURS` supervisor (a separate
        bash process) touches this file right before killing the old
        llama-server process and removes it once the replacement answers
        `/health` again. `run_forever` pauses ticking outright while this
        is True, the same way it already pauses on `llm_pressure_
        paused()` — a crucial-cognition job deferring individually on a
        failed/timed-out call is correct for an occasional bad call, but
        a *planned* multi-second outage is better handled by pausing the
        whole town rather than manufacturing a wave of failed calls
        across every agent whose cognition/dialogue happens to come due
        during the restart window. Also updates `_llama_server_restarts`
        on the absent->present edge and logs a real `llama_server_
        restart` event on both edges, so the UI/History tab can show it
        rather than the town silently freezing for a few seconds with no
        visible cause. Returns False immediately (no stat) when no
        sentinel path is configured — the default, zero-cost path for
        anyone not running `LLAMA_RESTART_HOURS>0`."""
        path = self.config.llm_restart_sentinel_path
        if not path:
            return False
        restarting = os.path.exists(path)
        if restarting != self._llama_server_restarting:
            if restarting:
                self._llama_server_restarts += 1
                self._log("llama_server_restart", "llama-server is restarting to reclaim memory — the town pauses briefly.")
            else:
                self._log("llama_server_restart", "llama-server is back — the town resumes.")
            self._llama_server_restarting = restarting
            # `_tick_once()` is fully skipped for the whole pause window
            # (see run_forever), so nothing would otherwise push this
            # transition to connected clients until ticking resumes —
            # broadcast it directly on the edge so the UI's indicator
            # (and the event itself) show up promptly instead of only
            # after the restart has already finished.
            self._maybe_broadcast()
        return restarting

    def _maybe_poll_llama_server_metrics(self) -> None:
        """Fire a background `/metrics` poll (v0.87.6) if
        `LLAMA_METRICS_POLL_SECONDS` has elapsed since the last one
        started — called every `run_forever` loop iteration (real-time
        gated, like the interval check itself, not tick-gated) so
        polling keeps happening even while ticking is paused. A no-op
        on the Ollama backend (no equivalent endpoint) or when the LLM
        is disabled entirely. Uses `asyncio.to_thread` for the blocking
        HTTP GET, same as every other LLM call, and is added to
        `_background_tasks` so a shutdown mid-poll is still cancelled
        cleanly."""
        if self.config.llm_backend != "llamacpp" or not self.config.llm_enabled:
            return
        now = time.monotonic()
        if now - self._llama_server_metrics_poll_started_at < LLAMA_METRICS_POLL_SECONDS:
            return
        self._llama_server_metrics_poll_started_at = now

        async def _poll() -> None:
            result = await asyncio.to_thread(fetch_llama_server_metrics, self.config.llm_llamacpp_host)
            if result is not None:
                self._llama_server_metrics = result

        task = asyncio.create_task(_poll())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _settlement_job_backpressured(self) -> bool:
        """Backpressure check for the settlement-level jobs (chronicle,
        town_brain, beliefs, tradition, invention, festival, caravan,
        documentary, personal_belief, omen) — every one of them shares
        the same `month_end`/`season_end`/`year_end` gate, so a single
        boundary tick schedules several of them at once (observed: up
        to 5 in one tick on a routine month/season boundary, more when
        an RNG-gated job like festival/caravan/omen also happens to
        roll true the same month). Per-agent cognition
        (`_schedule_due_cognition`) and dialogue (`_schedule_due_
        dialogue`) already apply `_backpressure_limit` before
        scheduling; these jobs never did, since each was added
        independently and none is individually frequent enough to look
        like a backlog risk in isolation. The cluster is the risk: with
        `llm_max_concurrent` typically 1-2 and each real call ~17-20s,
        an unthrottled 5-job cluster forces Ollama through a rapid-fire
        back-to-back burst it wouldn't otherwise see, instead of its
        normal much sparser trickle — a plausible source of "sparse but
        sudden" swap spikes that steady-state/leak audits (which look
        for monotonic growth) wouldn't surface. Same graceful-
        degradation contract as the existing per-agent gate: a skipped
        job just waits for its next natural cadence (next month/
        season/year), nothing is lost or retried out of order. Naming
        (one-time-per-world) is deliberately NOT gated by this — it has
        no periodic retry path, and it isn't part of the recurring
        monthly cluster this exists to smooth out. Adds `_reserved_this_
        tick` to the real `backlog` (see its docstring) so a job already
        scheduled earlier in this same tick — before its own coroutine
        has had a chance to run and increment `backlog` for real — still
        counts against the limit for the next check this tick."""
        if self._effective_backlog() >= self._current_backpressure_limit():
            self._cognition_runner.calls_dropped_backpressure += 1
            return True
        return False

    def _monthly_gate(self, events: list[str], job: str) -> bool:
        """True when `job`'s staggered day-of-month window is open this
        tick — see MONTHLY_JOB_DAY. Replaces the shared `"month_end" in
        events` gate every monthly LLM job used to check, which made them
        all fire in one burst.

        Jobs in `MONTHLY_JOBS_WITH_RETRY` (v0.81.1) get a `MONTHLY_JOB_
        RETRY_WINDOW_DAYS`-day window instead of one exact day: still True
        on any of those days UNLESS this job already got past its own
        backpressure check once this month (`_monthly_job_scheduled_
        month`, set by `_mark_monthly_resolved` — call it the instant a
        caller's own backpressure check clears, so a job that got through
        on day 1 doesn't also fire again on day 2 or 3). Every other job
        (festival/caravan/omen, each with its own independent per-month
        RNG "does this even happen" roll) keeps the original single-exact-
        day behavior — widening their window too would re-evaluate that
        roll on multiple days a month, inflating the effective monthly
        chance beyond what it was tuned for. See MONTHLY_JOB_RETRY_
        WINDOW_DAYS' docstring."""
        if "day_end" not in events:
            return False
        clock = self.world.clock
        start_day = MONTHLY_JOB_DAY[job]
        day = clock.day_of_month
        if job not in MONTHLY_JOBS_WITH_RETRY:
            return day == start_day
        if day < start_day or day >= start_day + MONTHLY_JOB_RETRY_WINDOW_DAYS:
            return False
        month_ordinal = clock.year * len(self.world.config.days_per_month) + clock.month_index
        return self._monthly_job_scheduled_month.get(job) != month_ordinal

    def _mark_monthly_resolved(self, job: str) -> None:
        """Call the instant `job`'s own backpressure check clears (not
        before — see `_monthly_gate`'s retry-window docstring) so a
        further `_monthly_gate` check later this same month reads False.
        Idempotent to call more than once; only ever read back within the
        same month it was set (compared against a fresh month_ordinal),
        so nothing here needs pruning across a long-running world."""
        clock = self.world.clock
        month_ordinal = clock.year * len(self.world.config.days_per_month) + clock.month_index
        self._monthly_job_scheduled_month[job] = month_ordinal

    def _season_year_gate(self, events: list[str], job: str, boundary_event: str) -> bool:
        """Season/year-cadence counterpart to `_monthly_gate` — see
        SEASON_YEAR_JOBS_WITH_RETRY's docstring for the bug this fixes.
        `boundary_event` is `"season_end"` or `"year_end"`. Jobs not in
        SEASON_YEAR_JOBS_WITH_RETRY keep the original single-exact-tick
        behavior unchanged (there are none currently, but this keeps the
        helper generically correct if a future season/year job wants the
        old shape). Opens (or re-opens, for a fresh season/year) a
        `SEASON_YEAR_JOB_RETRY_WINDOW_DAYS`-day window the instant
        `boundary_event` is crossed; stays True on every tick within that
        window until `_mark_season_year_resolved` records this ordinal as
        done."""
        if job not in SEASON_YEAR_JOBS_WITH_RETRY:
            return boundary_event in events
        clock = self.world.clock
        if boundary_event in events:
            if boundary_event == "year_end":
                ordinal = clock.year
            else:
                ordinal = clock.year * len(self.world.config.seasons_per_year) + clock.season_index
            self._season_year_job_window[job] = (clock.tick_count, ordinal)
        window = self._season_year_job_window.get(job)
        if window is None:
            return False
        open_tick, ordinal = window
        ticks_per_day = self.world.config.minutes_per_day // self.world.config.sim_minutes_per_tick
        if clock.tick_count - open_tick >= SEASON_YEAR_JOB_RETRY_WINDOW_DAYS * ticks_per_day:
            return False
        return self._season_year_job_scheduled_ordinal.get(job) != ordinal

    def _mark_season_year_resolved(self, job: str) -> None:
        """Call the instant `job`'s own backpressure check clears — mirrors
        `_mark_monthly_resolved` for the season/year cadence tier. Reads
        the ordinal from the currently-open window (set by `_season_year_
        gate`); a no-op if no window is open for this job (can't happen
        in practice — a job only calls this from inside its own apply
        path, which only runs after `_season_year_gate` returned True)."""
        window = self._season_year_job_window.get(job)
        if window is not None:
            self._season_year_job_scheduled_ordinal[job] = window[1]

    def _settlement_by_id(self, settlement_id: int) -> "Settlement":
        """Resolve a settlement id captured in a job closure back to the
        live object at apply time — falls back to the founding
        settlement if the id is unknown (can't happen today; settlements
        are never removed, but a closure must not crash the task set)."""
        return next(
            (s for s in self.world.settlements if s.id == settlement_id), self.world.settlement,
        )

    def _job_target(self) -> "Settlement":
        """Which settlement this month's settlement-scoped LLM jobs are
        about: a month-indexed round-robin over the *named* settlements.
        Rotation (rather than running every job for every settlement)
        keeps total monthly LLM volume flat no matter how many
        settlements exist — the multi-settlement pass must not multiply
        the call load on the 8GB target hardware. With one settlement
        this is exactly the old behavior."""
        named = [s for s in self.world.settlements if s.name]
        if not named:
            return self.world.settlement
        clock = self.world.clock
        month_ordinal = clock.year * len(self.world.config.days_per_month) + clock.month_index
        return named[month_ordinal % len(named)]

    # --- the one scheduling path for settlement-level LLM jobs -----------------

    def _schedule_llm_job(
        self, name: str, prompt: str, system: str, fallback: dict, apply, critical: bool = False,
        structured_input: dict | None = None, npc_ids: list | None = None, settlement: str | None = None,
    ) -> None:
        """Fire-and-forget one settlement-level LLM job (chronicle,
        tradition, town_brain, beliefs, omen, ...): run through the
        CognitionRunner (bounded concurrency + deterministic fallback),
        call `apply(result, used_fallback)` when it resolves, and record
        debug/fallback bookkeeping — previously each job hand-rolled its
        own identical `_run_X` coroutine, ten near-copies that each had
        to remember the bookkeeping (July 2026 architecture review,
        §1.2). `apply` runs when the task completes (between ticks, same
        as the old `_run_X` bodies); an exception in it is contained
        here so one bad apply can never kill the background task set.
        Per-agent cognition and dialogue keep their own paths — they
        carry pending-result queues and staleness state this shape
        doesn't need.

        `critical=True` marks a job whose deterministic fallback would be
        a *fabricated substitute for genuine cognition* rather than an
        objective-reality answer — belief revision, the town brain,
        dreams, the consciousness (Engineering Constitution §3/§7:
        "Never replace [crucial cognition] with simplistic deterministic
        fallbacks simply to keep the simulation running. If cognition
        falls behind, slow or pause the simulation instead."). For a
        critical job, when the real call can't happen (daily budget
        spent) or fails (timeout/error), `apply` is NOT called with a
        fabricated result — the relevant state is left exactly as it was
        and the job re-attempts on its next natural cadence. The world
        already slows/pauses under live backlog pressure (see `run_
        forever`/`llm_pressure_paused`), which is the mechanism that
        gives inference time to catch up. This generalizes the pattern
        `consciousness`'s apply already hand-rolled (its `used_fallback`
        early-return). Non-critical jobs (chronicle, tradition, folklore,
        omens, caravan, naming, ...) keep the deterministic fallback:
        those genuinely have a sensible deterministic answer and are
        ambient texture, not crucial cognition."""
        # Daily-ceiling gate (v0.70.0): once the day's Ollama budget is
        # spent, a non-critical settlement job resolves via its
        # deterministic fallback inline rather than scheduling a real
        # call — the in-fiction effect still happens, only the model
        # authorship is skipped. A CRITICAL job instead DEFERS: it makes
        # no change this cadence rather than fabricating cognition, and
        # the deferral is counted for diagnosis (Constitution §3/§7).
        if not self._consume_llm_budget():
            if critical:
                self._cognition_runner.calls_deferred_critical += 1
                self._record_llm_debug(
                    name, prompt, fallback, True,
                    structured_input=structured_input, npc_ids=npc_ids, settlement=settlement,
                    outcome={"status": "deferred_critical", "apply_failed": False},
                )
                return
            apply_failed = False
            try:
                apply(fallback, True)
            except Exception:
                logger.exception("Failed to apply %s fallback job result", name)
                apply_failed = True
            self._record_llm_debug(
                name, prompt, fallback, True,
                structured_input=structured_input, npc_ids=npc_ids, settlement=settlement,
                outcome={"status": "fallback_used", "apply_failed": apply_failed},
            )
            return

        async def _runner() -> None:
            call_start = time.perf_counter()
            result, used_fallback, raw_completion = await self._cognition_runner.run(
                prompt, system, fallback=lambda: fallback
            )
            elapsed_ms = (time.perf_counter() - call_start) * 1000
            apply_failed = False
            if critical and used_fallback:
                # Crucial cognition: the real call failed, so leave state
                # untouched and re-attempt next cadence rather than apply
                # a fabricated belief/priority/dream (Constitution §3/§7).
                self._cognition_runner.calls_deferred_critical += 1
                outcome_status = "deferred_critical"
            else:
                try:
                    apply(result, used_fallback)
                except Exception:
                    logger.exception("Failed to apply %s LLM job result", name)
                    apply_failed = True
                outcome_status = "fallback_used" if used_fallback else "executed"
            self._record_llm_debug(
                name, prompt, result, used_fallback, elapsed_ms, system_prompt=system,
                raw_completion=raw_completion, structured_input=structured_input,
                npc_ids=npc_ids, settlement=settlement,
                outcome={"status": outcome_status, "apply_failed": apply_failed},
            )
            self._record_llm_call(used_fallback)

        self._reserved_this_tick += 1  # see its docstring — counted the instant scheduling happens
        task = asyncio.create_task(_runner())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # --- settlement naming: deterministic placeholder, LLM-authored real name --

    def _maybe_schedule_naming(self) -> None:
        """`World.tick()` already gives a brand-new settlement an
        instant deterministic placeholder name the moment its first
        building stands (every other system gates on `settlement.name`
        being set, so naming can't wait on an LLM round trip without
        stalling them). This schedules a one-time background job that
        proposes a better, context-aware name — informed by the
        founding scenario and terrain, not a bare random draw — which
        replaces the placeholder when it resolves. See
        docs/DECISIONS.md, "naming mechanism follow-up.\""""
        if not self.world.newly_named_settlement_ids:
            return
        if not self._cognition_runner.enabled:
            # The deterministic placeholder already *is* the fallback
            # outcome here — unlike other jobs, running a second,
            # differently-seeded fallback draw would just rename the
            # settlement to another random name for no reason when
            # there's no real LLM contribution happening.
            return
        for settlement_id in self.world.newly_named_settlement_ids:
            if settlement_id in self._naming_scheduled_ids:
                continue
            self._naming_scheduled_ids.add(settlement_id)
            settlement = self._settlement_by_id(settlement_id)
            counts = biome_counts(self.world.terrain)
            top_biome = max(counts, key=lambda b: counts[b]).replace("_", " ") if counts else ""
            prompt = naming.build_prompt(settlement.founding_scenario, top_biome, settlement.era)
            fallback = naming.fallback_name(self.world.config.seed + settlement_id)

            def apply(result: dict, used_fallback: bool, sid: int = settlement_id, fb: dict = fallback) -> None:
                target = self._settlement_by_id(sid)
                target.llm_named = True
                new_name = naming.parse_name(result, fb)
                if new_name and new_name != target.name:
                    target.name = new_name
                    noun = "The village" if sid == 0 else "The settlement"
                    self._log("settlement_named", f"{noun} came to be known as {new_name}.")

            self._schedule_llm_job(
                "naming", prompt, naming.SYSTEM_PROMPT, fallback, apply,
                structured_input={"founding_scenario": settlement.founding_scenario, "top_biome": top_biome, "era": settlement.era},
            )

    async def run_forever(self) -> None:
        logger.info(
            "Engine starting: %.2fs/tick, %s sim-minutes/tick, snapshot every %s ticks, LLM %s.",
            self.config.tick_seconds, self.world.config.sim_minutes_per_tick, self.config.snapshot_every_ticks,
            "enabled" if self._cognition_runner.enabled else "disabled (deterministic fallback only)",
        )
        try:
            while not self._stop_event.is_set():
                paused = self._broadcaster is not None and self._broadcaster.is_paused()
                # LLM-pressure pacing (see LLM_PRESSURE_SLOWDOWN_START_RATIO):
                # a saturated backlog pauses ticking the same way the user's
                # own pause button does — town consciousness over throughput,
                # explicit standing directive (CLAUDE.md). Checked every loop
                # iteration so it reacts live as backlog drains, not just at
                # the top of a tick.
                llm_paused = self.llm_pressure_paused()
                # A planned llama-server restart (LLAMA_RESTART_HOURS)
                # pauses the same way — see llama_server_restarting()'s
                # docstring for why this is a real pause rather than
                # leaving it to per-call fallback/defer.
                restarting = self.llama_server_restarting()
                # Real-time gated (not tick-gated) so this keeps polling
                # even during a pause — see LLAMA_METRICS_POLL_SECONDS.
                self._maybe_poll_llama_server_metrics()
                if not paused and not llm_paused and not restarting:
                    self._tick_once()
                speed = self._broadcaster.get_speed_multiplier() if self._broadcaster is not None else 1.0
                # While paused (user-requested, LLM-pressure-triggered, or
                # a llama-server restart in progress), poll at a short
                # fixed interval rather than the (possibly very long, at a
                # low speed multiplier) tick interval, so a resume/stop
                # request — or the backlog/restart clearing — is picked up
                # promptly.
                if paused or llm_paused or restarting:
                    interval = PAUSED_POLL_SECONDS
                else:
                    interval = max(
                        0.05,
                        self.config.tick_seconds / speed * self._llm_pressure_interval_multiplier(),
                    )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass  # normal case: no stop requested within the tick interval
        finally:
            if self._background_tasks:
                logger.info("Cancelling %s in-flight LLM background task(s).", len(self._background_tasks))
                for task in self._background_tasks:
                    task.cancel()
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
            logger.info("Engine stopping — saving final snapshot at tick %s.", self.world.clock.tick_count)
            save_snapshot(self.conn, self.world)
            self._snapshots_saved += 1

    _TICK_JOBS: tuple[tuple[str, int], ...] = (
        # The per-tick scheduling sequence (R2, docs/REFACTOR-2026-07.md).
        # ORDER IS LOAD-BEARING — some jobs read state a prior job set this
        # same tick (temperament before omen; cognition before dialogue).
        # Preserve order when editing; add a new job as one entry here plus
        # its `_maybe_schedule_*` method. `maintain_core_cast` runs just
        # before this loop (it takes a config arg, not the loop's shape).
        ("_maybe_schedule_naming", _JOB_NO_ARGS),
        ("_maybe_schedule_chronicle", _JOB_EVENTS_SEASON),
        ("_maybe_schedule_documentary", _JOB_EVENTS),
        ("_maybe_schedule_tradition", _JOB_EVENTS),
        ("_maybe_schedule_folklore", _JOB_EVENTS),
        ("_maybe_schedule_invention", _JOB_EVENTS),
        ("_maybe_schedule_festival", _JOB_EVENTS),
        ("_maybe_schedule_religion", _JOB_EVENTS),
        ("_maybe_schedule_narrative_direction", _JOB_EVENTS),
        ("_maybe_schedule_culture_digest", _JOB_EVENTS),
        ("_maybe_schedule_consciousness", _JOB_EVENTS),
        ("_maybe_schedule_caravan", _JOB_EVENTS),
        ("_maybe_schedule_town_brain", _JOB_EVENTS),
        ("_maybe_schedule_beliefs", _JOB_EVENTS),
        ("_maybe_schedule_personal_belief", _JOB_EVENTS),
        ("_maybe_schedule_dream", _JOB_EVENTS),
        ("_maybe_schedule_memory_drift", _JOB_EVENTS),
        ("_maybe_tick_temperament", _JOB_EVENTS),
        ("_maybe_schedule_omen", _JOB_EVENTS),
        ("_maybe_tick_market_prices", _JOB_EVENTS),
        ("_maybe_schedule_record", _JOB_NO_ARGS),
        ("_maybe_schedule_dispute", _JOB_NO_ARGS),
        ("_maybe_schedule_guild_founding", _JOB_EVENTS),
        ("_maybe_schedule_faction", _JOB_EVENTS),
        ("_maybe_schedule_institution_belief", _JOB_EVENTS),
        ("_maybe_schedule_geography", _JOB_EVENTS),
        ("_maybe_schedule_fission", _JOB_EVENTS),
        ("_maybe_schedule_diplomacy", _JOB_EVENTS),
        ("_maybe_schedule_laws", _JOB_EVENTS),
        ("_maybe_schedule_noncore_nudge", _JOB_EVENTS),
        ("_maybe_schedule_letter", _JOB_EVENTS),
        ("_maybe_schedule_institution_culture", _JOB_EVENTS),
        ("_schedule_due_cognition", _JOB_NO_ARGS),
        ("_schedule_due_dialogue", _JOB_NO_ARGS),
    )

    def _tick_once(self) -> None:
        tick_start = time.perf_counter()
        self._reserved_this_tick = 0  # see its docstring: fresh reservation count each tick
        self._apply_pending_cognition_results()
        self._apply_pending_dialogue_results()
        self._apply_pending_interventions()

        previous_season = self.world.clock.season
        events = self.world.tick()
        for event in events:
            log_event(
                self.conn,
                tick=self.world.clock.tick_count,
                category=event,
                description=_CALENDAR_EVENT_DESCRIPTIONS.get(event, event),
                commit=False,  # one commit per tick, at the end of _tick_once
            )
        for category, description in self.world.last_life_events:
            log_event(
                self.conn, tick=self.world.clock.tick_count,
                category=category, description=description,
                commit=False,
            )
        if _pending_memory_evictions:
            # Durable per-agent memory history (Constitution §6, v0.86.3)
            # — drains the transient buffer `_remember` fills whenever a
            # significant (non-routine) memory gets evicted past its RAM
            # cap. See `_pending_memory_evictions`'s docstring for why
            # this lives at module scope in population.py.
            for entry in _pending_memory_evictions:
                log_agent_memory_entry(
                    self.conn, self.world.clock.tick_count, entry["agent_id"], "episodic", entry["text"],
                )
            _pending_memory_evictions.clear()
        self._detect_ritual_signals()
        self._resolve_prophecies()
        self._maybe_schedule_skill_mastery()
        if "day_end" in events:
            self._log_daily_metrics()
            self._llm_calls_today = 0  # reset the daily Ollama-call ceiling (v0.70.0)
            self._interpret_rumor_today = 0  # reset InterpretRumor()'s own daily ceiling (Phase K)
            # Deferred item 4 (docs/VISION-2026-07-LEARNING.md), "gradual
            # forgetting as a continuous fade": zero LLM cost, population-
            # wide, so no core-cast gating applies — see Population.
            # decay_memory_salience's docstring.
            self.world.population.decay_memory_salience()
            # v0.87.15 "bounded episodic planning": same daily cadence,
            # zero LLM cost — see Population.tick_plans's docstring.
            self.world.population.tick_plans()
            # §2 "letters carried by caravans": zero LLM cost at
            # delivery time (the LLM call already happened when the
            # letter was written) — daily is plenty granular against
            # LETTER_TRAVEL_TICKS' multi-day delay.
            self._deliver_letters()
        if events:
            logger.info(
                "Tick %s: %s | %s | %s",
                self.world.clock.tick_count, self.world.clock.date_string(),
                self.world.clock.clock_string(), self.world.weather.describe(),
            )

        # Keep the LLM core cast full and current before any cognition/
        # dialogue scheduling reads it this tick (v0.70.0).
        newly_core = self.world.population.maintain_core_cast(self.config.llm_core_cast_size)
        if newly_core:
            self._author_minds(newly_core)
        # Per-tick scheduling jobs fire in a fixed order via a declarative
        # table (`_TICK_JOBS`, R2 in docs/REFACTOR-2026-07.md) instead of a
        # hand-maintained call list. Adding a job is one table entry; the
        # order — which some jobs genuinely depend on (e.g. temperament
        # before omen, cognition before dialogue) — lives in exactly one
        # place. The job methods themselves are unchanged.
        for method_name, arg_kind in self._TICK_JOBS:
            method = getattr(self, method_name)
            if arg_kind == _JOB_NO_ARGS:
                method()
            elif arg_kind == _JOB_EVENTS:
                method(events)
            else:  # _JOB_EVENTS_SEASON
                method(events, previous_season)
        self.conn.commit()  # one commit for everything this tick logged (see log_event's commit param)
        self._last_tick_duration_ms = (time.perf_counter() - tick_start) * 1000
        self._tick_durations_ms.append(self._last_tick_duration_ms)
        self._maybe_broadcast()

        self._ticks_since_snapshot += 1
        if self._ticks_since_snapshot >= self.config.snapshot_every_ticks:
            save_snapshot(self.conn, self.world)
            self._snapshots_saved += 1
            self._ticks_since_snapshot = 0
            logger.debug("Snapshot saved at tick %s.", self.world.clock.tick_count)

    # --- Phase B: per-agent cognition (goals) -------------------------------

    def _apply_pending_cognition_results(self) -> None:
        """Apply goal decisions completed by background tasks since the
        last tick. Runs synchronously at the top of _tick_once, never
        inline with the LLM call itself."""
        if not self._pending_goal_results:
            return
        now = self.world.clock.tick_count
        for agent_id, (scheduled_tick, result, seek_candidate_id) in self._pending_goal_results.items():
            if now - scheduled_tick > STALE_GOAL_RESULT_TICKS:
                continue  # reasoned from a days-old snapshot — see STALE_GOAL_RESULT_TICKS
            goal, reason = parse_goal(result)
            self.world.population.apply_goal(agent_id, goal, reason, seek_candidate_id)
        self._pending_goal_results.clear()

    @staticmethod
    def _is_significant_moment(agent) -> bool:
        """Gate for whether a *routine* (non-triggered) daily cognition
        slot is worth an actual LLM call, per the standing "maximize
        emergence per LLM call" rule: reserve the scarce budget for
        moments that shape the simulation (a notable emotion, an active
        feud) rather than an ordinary day's habitual goal pick, which
        the deterministic `fallback_goal` (trait+emotion-aware since
        Phase I) already handles well. Event-driven emergencies
        (critical hunger, fresh grief/predator-attack) bypass this
        entirely via `due_for_triggered_cognition` — they're significant
        by construction. See docs/DECISIONS.md, "cognition scheduler:
        significance gate" pass."""
        if dominant_emotion(agent.emotions) is not None:
            return True
        return any(v <= RIVALRY_THRESHOLD for v in agent.relationships.values())

    LESSON_RECENT_DISPUTE_TICKS = 500
    """How recent a dispute-cooldown entry must be for `_current_
    situation_tag` to read the agent as currently "in conflict" —
    deliberately much shorter than `DISPUTE_COOLDOWN_TICKS` (which just
    gates re-triggering a NEW dispute) since this is asking "does this
    still feel like an open conflict right now," not "is a new dispute
    on cooldown." See v0.87.0, "learns like a human" — `Agent.lessons`."""

    LESSON_KEYWORD_OVERLAP_MIN = 2
    """Deferred item 2 (docs/VISION-2026-07-LEARNING.md), "smarter
    recall via real semantic similarity": rather than adding an
    embeddings/vector-DB dependency (a real new-dependency decision the
    deferred-list entry deliberately declined to make unprompted), a
    cheap stdlib keyword-overlap fallback widens `_matching_lesson`
    beyond the fixed 5-tag `LESSON_SITUATIONS` vocabulary — when no
    lesson shares the agent's current exact situation tag, the agent's
    most recent `working_memory` entry is compared word-for-word
    against every stored lesson's text, and the best-overlapping one
    surfaces if it shares at least this many meaningful (non-stopword,
    3+ letter) words. 2 is a deliberately conservative floor — a single
    shared word ("village," "food") is too common to mean much; two
    shared words is a real, if crude, topical match."""

    OCCUPATION_BY_SKILL = {
        SKILL_FARMING: "farmer", SKILL_CONSTRUCTION: "builder", SKILL_MEDICINE: "healer",
    }
    """v0.87.16, "occupation-shaped beliefs" (explicit user direction):
    an agent's dominant skill read back as a plain-language trade label
    — the cheapest possible "occupation" concept given this codebase has
    no separate profession system, reusing the existing SKILL_* axes
    rather than inventing a parallel one."""

    def _pick_core_memory(self, agent) -> str:
        """v0.87.16, "deepen long-term historical identity": the one
        `Agent.core_memories` entry to surface this prompt, keyword-
        overlap-matched against the agent's current situation
        (`working_memory`'s freshest entry, same signal `retrieve_
        relevant_memories` uses) — "" (the common case) when nothing
        currently echoes any stored core memory, same "only offered
        when it's genuinely relevant, never fabricated/forced" texture
        discipline every other optional prompt-grounding field here
        follows."""
        if not agent.core_memories:
            return ""
        context = agent.working_memory[-1] if agent.working_memory else ""
        if not context:
            return ""
        context_tokens = _overlap_tokens(context)
        if not context_tokens:
            return ""
        best_i, best_score = None, 0
        for i, text in enumerate(agent.core_memories):
            score = len(context_tokens & _overlap_tokens(text))
            if score > best_score:
                best_i, best_score = i, score
        return agent.core_memories[best_i] if best_i is not None else ""

    def _occupation_for(self, agent) -> str:
        """"" (no notable trade) unless one skill clears OCCUPATION_
        MIN_SKILL — an agent with only a trace of farming skill isn't
        meaningfully "a farmer" yet, and a bare "" lets consumers (e.g.
        `build_personal_prompt`) skip the occupation clause entirely
        rather than always naming a barely-practiced trade."""
        best_skill, best_level = None, OCCUPATION_MIN_SKILL
        for skill, label in self.OCCUPATION_BY_SKILL.items():
            level = agent.skills.get(skill, 0.0)
            if level >= best_level:
                best_skill, best_level = label, level
        return best_skill or ""

    def _current_situation_tag(self, agent) -> str:
        """Deterministic classifier for `Agent.lessons`' situation match
        (v0.87.0) — cheap, stdlib, no embeddings: which of `beliefs.
        LESSON_SITUATIONS` best describes what this agent is dealing
        with RIGHT NOW. Priority order favors the more acute situation
        when more than one applies (a hungry agent mid-feud reads as
        "conflict" first, since that's usually the more decision-
        relevant lesson to recall) — "" when nothing notable applies,
        which correctly means no lesson gets surfaced this call."""
        dominant = dominant_emotion(agent.emotions)
        dominant_key = dominant[0] if dominant is not None else None
        if dominant_key == EMOTION_FEAR:
            return "danger"
        tick = self.world.clock.tick_count
        cooldowns = self.world.population.dispute_cooldowns
        if any(
            agent.id in pair and tick - last_tick <= self.LESSON_RECENT_DISPUTE_TICKS
            for pair, last_tick in cooldowns.items()
        ):
            return "conflict"
        if dominant_key == EMOTION_GRIEF:
            return "grief"
        if agent.hunger >= FORAGE_HUNGER_THRESHOLD:
            return "hunger"
        return ""

    def _matching_lesson(self, agent, situation: str) -> str:
        """Returns the text of `agent.lessons`' freshest entry tagged
        with `situation`; if none share the exact tag, falls back to a
        keyword-overlap match (deferred item 2) against the agent's most
        recent `working_memory` entry — "" if situation is "" or nothing
        clears either bar. Thin lookup helper for `_schedule_due_
        cognition`/dialogue."""
        if not situation:
            return ""
        matches = [entry for entry in agent.lessons if entry.get("situation") == situation]
        if matches:
            return max(matches, key=lambda e: e.get("formed_tick", 0))["text"]
        if not agent.lessons or not agent.working_memory:
            return ""
        context_tokens = _overlap_tokens(agent.working_memory[-1])
        if not context_tokens:
            return ""
        best_entry, best_score = None, 0
        for entry in agent.lessons:
            score = len(context_tokens & _overlap_tokens(entry["text"]))
            if score > best_score:
                best_entry, best_score = entry, score
        if best_entry is not None and best_score >= self.LESSON_KEYWORD_OVERLAP_MIN:
            return best_entry["text"]
        return ""

    def _schedule_due_cognition(self) -> None:
        """Fire-and-forget a goal-decision task for every agent whose
        staggered daily slot is this tick. Scheduled unconditionally
        (whether or not the LLM is enabled) — CognitionRunner resolves to
        the deterministic fallback when it's not, so agents still get
        periodic goal reevaluation either way."""
        ticks_per_day = self.world.config.minutes_per_day // self.world.config.sim_minutes_per_tick
        due = self.world.population.due_for_cognition(self.world.clock.tick_count, ticks_per_day)
        # Plus anything event-triggered this tick (hunger emergency, fresh
        # grief) — an immediate re-reasoning rather than waiting for the
        # next staggered daily slot. See docs/DECISIONS.md, "cognition
        # triggers beyond daily cadence" pass.
        triggered = self.world.population.due_for_triggered_cognition(
            self.world.clock.tick_count, TRIGGERED_COGNITION_COOLDOWN_TICKS,
        )
        triggered_ids = {agent.id for agent in triggered}
        if triggered:
            due_ids = {agent.id for agent in due}
            due = due + [agent for agent in triggered if agent.id not in due_ids]
        backlog = self._effective_backlog()
        population = self.world.population
        for agent in due:
            if agent.id in self._inflight_cognition_agent_ids:
                continue
            # v1 audit fix: a surveyor's goal is unconditionally force-
            # overridden to AgentGoal.EXPLORE at movement-dispatch time
            # (Population._dispatch_movement's effective_goal), regardless
            # of what cognition decides — so scheduling a real LLM call
            # (or even the deterministic fallback_goal path) here was
            # pure waste: the answer is discarded every single time, and
            # meanwhile agent.goal/goal_reason (what dialogue/inspector
            # text actually reads) showed a stale "gathering"/"resting"
            # reason that never matched what the agent was really doing.
            # Skip cognition entirely for surveyors and write the goal
            # directly — frees a core-cast slot for a job whose answer
            # isn't thrown away, and keeps the agent's stated reason
            # honest about what it's doing.
            if agent.occupation == OCCUPATION_SURVEYOR:
                population.apply_goal(agent.id, AgentGoal.EXPLORE, "surveying the unmapped land")
                continue
            # Core-cast gate (v0.70.0): only core-cast agents spend an
            # Ollama call on goal reasoning. Everyone else — and everyone,
            # once the day's LLM ceiling is hit or the LLM is disabled —
            # gets the deterministic `fallback_goal` applied inline (no
            # call, no task), through the same `_pending_goal_results`
            # queue the LLM path uses, so timing is identical. This is
            # what stops cognition volume scaling with population.
            #
            # Significance gate (v0.77.0): even for a core-cast agent, a
            # *routine* daily slot (not a triggered emergency) only
            # spends an LLM call when something about this moment is
            # actually worth the model's discretion — see
            # `_is_significant_moment`. An ordinary "should I gather or
            # socialize today" day is exactly what the trait+emotion-
            # aware deterministic fallback already handles well; this is
            # the concrete mechanism behind "reserve the scarce LLM
            # budget for high-impact decisions" (docs/DECISIONS.md).
            is_triggered = agent.id in triggered_ids
            use_llm = (
                self._cognition_runner.enabled
                and population.is_core(agent.id)
                and self._llm_calls_today < self.config.llm_max_calls_per_day
                and (is_triggered or self._is_significant_moment(agent))
            )
            if not use_llm:
                plan_intent = agent.plan["intent"] if agent.plan else ""
                self._pending_goal_results[agent.id] = (
                    self.world.clock.tick_count,
                    fallback_goal(
                        agent.hunger, agent.energy, agent.id, dict(agent.traits), dict(agent.emotions), plan_intent,
                    ),
                    None,
                )
                continue
            # Backpressure (see BACKPRESSURE_BACKLOG_PER_SLOT): routine
            # daily reevaluations are skipped while the queue is
            # saturated — the agent keeps its current goal and gets the
            # next staggered slot; triggered emergencies get twice the
            # headroom before they too are rationed.
            limit = self._current_backpressure_limit() * (2 if agent.id in triggered_ids else 1)
            if backlog >= limit:
                self._cognition_runner.calls_dropped_backpressure += 1
                continue
            if not self._consume_llm_budget():
                # Day's ceiling reached between the check above and here
                # (another job spent the last slot). This is a core-cast
                # agent at a genuinely significant/triggered moment — the
                # LLM's discretion is warranted, so rather than fabricate
                # a rule-based goal to keep throughput up, DEFER: the
                # agent keeps its current LLM-authored goal and gets
                # re-evaluated at its next staggered slot (by when the
                # daily budget has reset). Physical survival is unaffected
                # — the deterministic critical-hunger movement override
                # (D5) still forces foraging regardless of goal, so
                # deferring the *goal* call never risks starvation. This
                # is the Engineering Constitution §3/§7 rule applied to
                # individual minds: crucial cognition is never faked.
                self._cognition_runner.calls_deferred_critical += 1
                continue
            backlog += 1  # count this tick's own scheduling against the gate
            self._reserved_this_tick += 1  # ...and against every other job type's check this tick
            self._inflight_cognition_agent_ids.add(agent.id)
            home = self._settlement_by_id(agent.settlement_id)
            latest_tradition = home.traditions[-1] if home.traditions else ""
            colocated_names = [
                other.name for other in population.agents
                if other.id != agent.id and (other.x, other.y) == (agent.x, agent.y)
            ][:4]
            food_steps = population.nearest_food_steps(
                agent, self.world.farms, home, self.world.resources, self.world.wildlife,
            )
            beliefs_about = beliefs.beliefs_about_agent(agent.id, home.beliefs)
            own_belief = max(agent.beliefs, key=lambda b: b["confidence"])["belief"] if agent.beliefs else ""
            semantic_memory = agent.semantic_memories[-1] if agent.semantic_memories else ""
            needs_repair = bool(population.damaged_building_positions(home))
            lesson = self._matching_lesson(agent, self._current_situation_tag(agent))
            seek_candidate = population._seek_person_candidate(agent, population.agents)
            seek_candidate_id = seek_candidate[0] if seek_candidate is not None else None
            seek_prompt_hint = (seek_candidate[1], seek_candidate[3]) if seek_candidate is not None else None
            institution_objective = population.institution_objective_for(agent.id, home)
            prompt = build_prompt(
                agent, self.world.clock.season, self.world.weather.describe(),
                settlement_name=home.name, latest_tradition=latest_tradition,
                colocated_names=colocated_names, nearest_food_steps=food_steps,
                beliefs_about=beliefs_about, own_belief=own_belief,
                semantic_memory=semantic_memory, mind_text=agent.mind,
                needs_repair=needs_repair, life_digest=agent.life_digest,
                lesson=lesson, seek_candidate=seek_prompt_hint,
                institution_objective=institution_objective, plan=agent.plan,
                core_memory=self._pick_core_memory(agent),
                prophecy=home.prophecy if home.prophecy and home.prophecy.get("status") == "pending" else None,
            )
            hunger_snapshot, energy_snapshot = agent.hunger, agent.energy
            traits_snapshot = dict(agent.traits)
            emotions_snapshot = dict(agent.emotions)
            plan_intent_snapshot = agent.plan["intent"] if agent.plan else ""
            task = asyncio.create_task(
                self._run_cognition(
                    agent.id, prompt, hunger_snapshot, energy_snapshot, traits_snapshot, emotions_snapshot,
                    seek_candidate_id, plan_intent_snapshot,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_cognition(
        self, agent_id: int, prompt: str, hunger: float, energy: float, traits: dict, emotions: dict,
        seek_candidate_id: int | None = None, plan_intent: str = "",
    ) -> None:
        scheduled_tick = self.world.clock.tick_count
        call_start = time.perf_counter()
        try:
            result, used_fallback, raw_completion = await self._cognition_runner.run(
                prompt, SYSTEM_PROMPT,
                fallback=lambda: fallback_goal(hunger, energy, agent_id, traits, emotions, plan_intent),
            )
            self._record_llm_debug(
                "cognition", prompt, result, used_fallback, (time.perf_counter() - call_start) * 1000,
                system_prompt=SYSTEM_PROMPT, raw_completion=raw_completion, npc_ids=[agent_id],
                structured_input={
                    "agent_id": agent_id, "hunger": hunger, "energy": energy,
                    "traits": traits, "emotions": emotions,
                    "seek_candidate_id": seek_candidate_id, "plan_intent": plan_intent,
                },
                # Cognition never applies a fabricated goal on fallback
                # (Constitution §3/§7) — see the used_fallback branch just
                # below, which is where "deferred_critical" is decided.
                outcome={"status": "deferred_critical" if used_fallback else "queued_pending_apply"},
            )
            if used_fallback:
                # The real call failed (timeout/error). This path is only
                # reached for a core-cast agent at a significant/triggered
                # moment (see `_schedule_due_cognition`'s `use_llm` gate),
                # so a fabricated rule-based goal would be exactly the
                # "replace crucial cognition to keep throughput" the
                # Engineering Constitution §3/§7 forbids. DEFER instead:
                # leave the agent's current LLM-authored goal in place and
                # let its next staggered slot re-attempt. The deterministic
                # critical-hunger movement override (D5) still guarantees
                # physical survival regardless of goal, so no fabricated
                # goal is needed to keep the world live.
                self._cognition_runner.calls_deferred_critical += 1
            else:
                self._pending_goal_results[agent_id] = (scheduled_tick, result, seek_candidate_id)
            self._record_llm_call(used_fallback)
        finally:
            self._inflight_cognition_agent_ids.discard(agent_id)

    # --- Phase E2: NPC-to-NPC dialogue ------------------------------------------

    def _apply_pending_dialogue_results(self) -> None:
        if not self._pending_dialogue_results:
            return
        now = self.world.clock.tick_count
        for scheduled_tick, agent_a_id, agent_b_id, parsed, is_llm in self._pending_dialogue_results:
            if now - scheduled_tick > STALE_DIALOGUE_RESULT_TICKS:
                continue  # see STALE_DIALOGUE_RESULT_TICKS
            applied = self.world.population.apply_dialogue(
                agent_a_id, agent_b_id, parsed["sentiment"], parsed["rumor"],
                line_a=parsed["line_a"], line_b=parsed["line_b"],
            )
            if applied is None:
                continue
            agent_a, agent_b, surfaced = applied
            # "Record all conversations internally [...] surface
            # conversations that changed beliefs, relationships or future
            # events" (Observatory UI direction, CLAUDE.md): every
            # exchange still applies its relationship/trust/gossip effects
            # (`apply_dialogue` above, unconditional), but only a genuine
            # LLM-authored core-cast exchange (`is_llm`) reaches the event
            # log at all — the crowd's deterministic fallback chatter is
            # real and mechanically consequential, it's just not narration
            # worth surfacing in /events or /history (explicit user
            # direction). Among LLM exchanges, only a `surfaced` one — a
            # rumor, or crossing into a close bond/rivalry — uses the
            # distinct `dialogue_surfaced` category the main UI's event
            # feed keys off of; the rest stay under the quieter `dialogue`
            # category. See docs/DECISIONS.md.
            if is_llm:
                category = "dialogue_surfaced" if surfaced else "dialogue"
                self._log(
                    category, f'{agent_a.name}: "{parsed["line_a"]}" — {agent_b.name}: "{parsed["line_b"]}"',
                )
                # v0.87.12 "dialogue novelty memory": only a genuine LLM
                # answer ever supplies a real topic (parse_dialogue never
                # fabricates one for the deterministic fallback).
                if parsed["topic"]:
                    self.world.population.record_dialogue_topic(agent_a.id, agent_b.id, parsed["topic"])
                    # §9 "diversify cultural topics" + "competing
                    # narratives" (docs/IDEAS-2026-07-EMERGENCE.md): the
                    # same LLM-authored topic also feeds a settlement-wide
                    # ring so `top_topics()` reads as a genuine "what's
                    # the village actually talking about lately" signal,
                    # zero added LLM call volume.
                    home = self._settlement_by_id(agent_a.settlement_id)
                    if home is not None:
                        home.record_topic(parsed["topic"])
            self.world.dialogue_total += 1
            if parsed["rumor"]:
                self._log("rumor", f"{agent_a.name} and {agent_b.name}: {parsed['rumor']}")
                self.world.rumor_total += 1
                self._maybe_interpret_rumor(agent_a, agent_b, parsed["rumor"])
            if agent_a.settlement_id != agent_b.settlement_id:
                # Cross-settlement relations (v0.67.0): a colocated pair
                # from two different named settlements is itself a real,
                # if rare, point of contact between those settlements —
                # nudge both settlements' mutual relation the same
                # direction as the sentiment, same shape as an individual
                # dialogue nudging Agent.relationships. See
                # docs/DECISIONS.md, "cross-settlement relationships."
                stl_a = self._settlement_by_id(agent_a.settlement_id)
                stl_b = self._settlement_by_id(agent_b.settlement_id)
                nudge = RELATION_DIALOGUE_NUDGE_SCALE * DIALOGUE_SENTIMENT_DELTA.get(parsed["sentiment"], 0.0)
                stl_a.relations[stl_b.id] = clamp(stl_a.relation_with(stl_b.id) + nudge, -1.0, 1.0)
                stl_b.relations[stl_a.id] = clamp(stl_b.relation_with(stl_a.id) + nudge, -1.0, 1.0)
        self._pending_dialogue_results.clear()

    def _maybe_interpret_rumor(self, agent_a, agent_b, rumor: str) -> None:
        """Phase K's InterpretRumor() (docs/VISION-2026-07.md, "Knowledge
        & Story") — a core-cast agent who just heard a rumor retells it
        coloured by their own nature rather than passing it through
        pristine. Scoped down from the vision doc's per-rumor hops/
        mutation tracking (no such structure exists here): the distorted
        retelling lands as a new memory via the existing `_remember`
        mechanism, so a later dialogue exchange naturally reads the
        *distorted* version through the same "recent memories" context
        every dialogue prompt already includes. See llm/rumor_
        interpret.py. Tightly capped per day
        (`INTERPRET_RUMOR_MAX_PER_DAY`) — this fires per listening
        event, not once a month like every other settlement job."""
        if not self._cognition_runner.enabled:
            return
        core = self.world.population.core_agent_ids
        listener = agent_a if agent_a.id in core else agent_b if agent_b.id in core else None
        if listener is None:
            return
        if self._interpret_rumor_today >= INTERPRET_RUMOR_MAX_PER_DAY:
            return
        if self._settlement_job_backpressured():
            return
        if not self._consume_llm_budget():
            return
        self._interpret_rumor_today += 1
        prompt = rumor_interpret.build_prompt(listener.name, dict(listener.traits), rumor)
        fallback = rumor_interpret.fallback_interpretation(listener.name, rumor)
        listener_id = listener.id

        async def _runner() -> None:
            result, used_fallback, raw_completion = await self._cognition_runner.run(
                prompt, rumor_interpret.SYSTEM_PROMPT, fallback=lambda: fallback,
            )
            target = self.world.population.get(listener_id)
            applied = False
            if target is not None:
                retelling = rumor_interpret.parse_interpretation(result, fallback)
                _remember(target, retelling)
                applied = True
            self._record_llm_debug(
                "rumor_interpret", prompt, result, used_fallback,
                system_prompt=rumor_interpret.SYSTEM_PROMPT, raw_completion=raw_completion,
                npc_ids=[listener_id], structured_input={"rumor": rumor, "traits": dict(listener.traits)},
                outcome={"status": "executed" if applied else "target_gone"},
            )
            self._record_llm_call(used_fallback)

        self._reserved_this_tick += 1
        task = asyncio.create_task(_runner())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # --- interventions ("nudges" from outside the simulation) ------------------

    def _apply_pending_interventions(self) -> None:
        """Drains anything queued via the browser API's `/intervene/*`
        endpoints (see `WorldBroadcaster.enqueue_intervention`) and
        applies each one synchronously, same seam as
        `_apply_pending_cognition_results` — the tick loop stays the
        only thing that mutates `World`; the API layer only ever
        enqueues a request for the *next* tick to apply. No-op when the
        API isn't enabled. See docs/DECISIONS.md, interventions pass."""
        if self._broadcaster is None:
            return
        for item in self._broadcaster.drain_interventions():
            try:
                self._apply_intervention(item)
            except Exception:
                logger.exception("Failed to apply intervention: %r", item)

    def _apply_intervention(self, item: dict) -> None:
        kind = item.get("type")
        if kind == "agent_goal":
            agent = self.world.population.get(item["agent_id"])
            if agent is None:
                return
            goal = AgentGoal(item["goal"])
            reason = item.get("reason") or "a nudge from outside the simulation"
            self.world.population.apply_goal(agent.id, goal, reason)
            self._log("intervention", f"{agent.name} was nudged toward {goal.value} — {reason}")
            # §3 "the observer enters the theology": see the settlement_
            # resources branch below for why this is recorded.
            self._settlement_by_id(agent.settlement_id).last_intervention_tick = self.world.clock.tick_count
            self._nudge_consciousness_grudge()
        elif kind == "settlement_resources":
            settlement = self._settlement_by_id(item.get("settlement_id", self.world.settlement.id))
            materials_delta = float(item.get("materials", 0.0))
            currency_delta = float(item.get("currency", 0.0))
            settlement.materials = max(0.0, min(MATERIALS_CAPACITY, settlement.materials + materials_delta))
            settlement.currency = max(0.0, min(CURRENCY_CAPACITY, settlement.currency + currency_delta))
            self._log(
                "intervention",
                f"An outside hand adjusted the settlement's stores "
                f"(materials {materials_delta:+.1f}, currency {currency_delta:+.1f}).",
            )
            # §3 "the observer enters the theology" (docs/IDEAS-2026-07-
            # EMERGENCE.md): a real, player-caused nudge, timestamped —
            # `_maybe_schedule_beliefs` reads this (never writes it) to
            # decide whether a recent event is close enough to invite the
            # beliefs job to optionally attribute something to a nameless
            # something, worded so it could equally be superstition. This
            # never fires for consciousness-authored interventions
            # (`weather_nudge`/`temperament_nudge`/`false_memory`,
            # llm/consciousness.py) — only genuine `/intervene/*` calls.
            settlement.last_intervention_tick = self.world.clock.tick_count
            self._nudge_consciousness_grudge()
        elif kind == "weather":
            weather = self.world.weather
            if "temperature_c" in item:
                weather.temperature_c = float(item["temperature_c"])
            if "precipitation" in item:
                weather.precipitation = clamp(float(item["precipitation"]), 0.0, 1.0)
            if "wind" in item:
                weather.wind = clamp(float(item["wind"]), 0.0, 1.0)
            if "is_snowing" in item:
                weather.is_snowing = bool(item["is_snowing"])
            self._log(
                "intervention", f"The weather shifted unnaturally — an outside hand nudged it to {weather.describe()}.",
            )
            self.world.settlement.last_intervention_tick = self.world.clock.tick_count
            self._nudge_consciousness_grudge()
        elif kind == "town_influence":
            text = str(item.get("text", "")).strip()[:200]
            if text:
                # Bug fix (see docs/DECISIONS.md, "whisper routing fix"):
                # this used to always land on the founding settlement
                # regardless of which settlement the player had selected
                # in the UI — in a multi-settlement (post-fission) world,
                # `_maybe_schedule_town_brain`'s round-robin `_job_target()`
                # only reads THIS settlement's `player_influence` on its
                # own turn, so a whisper aimed at any other settlement
                # could sit unread for many months, reading as "whispering
                # never does anything." `settlement_id` (sent by the UI's
                # whisper form as of this fix) targets whichever
                # settlement is actually selected; missing/unknown falls
                # back to the founding settlement (old behavior, and the
                # only settlement that exists in a single-settlement world).
                target = self._settlement_by_id(item.get("settlement_id", self.world.settlement.id))
                target.player_influence.append(text)
                target.player_influence = target.player_influence[-3:]
                noun = target.name or "the village"
                self._log("intervention", f"A whisper reached {noun}'s ear: \"{text}\"")
                target.last_intervention_tick = self.world.clock.tick_count
                self._nudge_consciousness_grudge()
        elif kind == "request_summary":
            self._schedule_summary()
        elif kind == "ask_chronicler":
            self._schedule_chronicler_answer(str(item.get("question", "")), item.get("settlement_id"))
        elif kind == "observer_attention":
            self._record_observer_attention(item.get("agent_id"))
        elif kind == "request_digest":
            self._schedule_away_digest()
        elif kind == "found_successor_world":
            self._found_successor_world()
        elif kind == "recorder_start":
            self.start_training_recording(
                session_name=item.get("session_name"),
                policy=item.get("policy", "all_tasks"),
                selected_tasks=item.get("selected_tasks"),
                sample_rate=float(item.get("sample_rate", 0.1)),
                tags=item.get("tags"),
            )
        elif kind == "recorder_stop":
            self.stop_training_recording()

    def _record_observer_attention(self, agent_id) -> None:
        """§4 "observer attention as a signal into the Town
        Consciousness" (docs/IDEAS-2026-07-EMERGENCE.md): applied from
        `POST /observer/attention`, fired by the frontend's NPC
        inspector on open — zero LLM cost, a plain state update through
        the same enqueue-now/apply-next-tick seam every other
        intervention uses. `agent_id` need not currently resolve to a
        living agent (a since-departed agent can still legitimately be
        "the observer's favorite" historically); only the increment/
        eviction bookkeeping happens here."""
        try:
            agent_id = int(agent_id)
        except (TypeError, ValueError):
            return
        attention = self.world.observer_attention
        if not attention:
            attention = {"agent_view_counts": {}, "last_agent_id": None, "last_seen_tick": -1}
        counts = attention.setdefault("agent_view_counts", {})
        counts[agent_id] = counts.get(agent_id, 0) + 1
        if len(counts) > OBSERVER_ATTENTION_MAX_TRACKED:
            least_viewed = min(counts, key=lambda aid: counts[aid])
            if least_viewed != agent_id:
                del counts[least_viewed]
        attention["last_agent_id"] = agent_id
        attention["last_seen_tick"] = self.world.clock.tick_count
        self.world.observer_attention = attention

    def _observer_favorite_agent(self) -> "Agent | None":
        """Most-inspected agent who is both still alive and still a
        core-cast member (only core-cast agents are LLM-authored
        subjects of omens/false-memory interventions in the first
        place) — or None if the observer has never inspected anyone,
        or their favorite(s) have all since died/aged out of the core
        cast. Falls back to the most-RECENTLY inspected living core
        agent if the top-count one no longer qualifies, so a long-lived
        favorite doesn't permanently lock out a fresher one."""
        attention = self.world.observer_attention
        counts = attention.get("agent_view_counts", {}) if attention else {}
        if not counts:
            return None
        core_ids = self.world.population.core_agent_ids
        by_id = {a.id: a for a in self.world.population.agents}
        ranked = sorted(counts, key=lambda aid: counts[aid], reverse=True)
        for aid in ranked:
            agent = by_id.get(aid)
            if agent is not None and aid in core_ids:
                return agent
        last_id = attention.get("last_agent_id")
        agent = by_id.get(last_id) if last_id is not None else None
        return agent if agent is not None and last_id in core_ids else None

    def _watched_agent_names(self, limit: int = 5) -> list[str]:
        """§5 "While you were away" digest: names of the agents the
        observer has most inspected (`World.observer_attention`),
        newest-count-first — used to headline the digest by whatever
        happened to people the observer actually cares about. Includes
        agents who have since died (a death IS exactly the kind of
        thing this digest exists to surface), unlike `_observer_
        favorite_agent` which deliberately excludes them since that
        helper feeds interventions that need a currently-actionable
        target."""
        attention = self.world.observer_attention
        counts = attention.get("agent_view_counts", {}) if attention else {}
        if not counts:
            return []
        by_id = {a.id: a for a in self.world.population.agents}
        ranked = sorted(counts, key=lambda aid: counts[aid], reverse=True)[:limit]
        names = [by_id[aid].name for aid in ranked if aid in by_id]
        return names

    def _intervention_hardship_context(self) -> bool:
        """§4 "the consciousness keeps a grudge ledger" — a cheap,
        deterministic read of whether the settlement is visibly
        struggling RIGHT NOW: meaningfully hungry population, or a
        death/illness/disaster this very tick (`World.last_life_events`,
        already computed for the tick's own event log — no extra
        scan). Reuses `SURVIVAL_HUNGER_THRESHOLD`'s existing "genuinely
        struggling" bar rather than inventing a second hunger cutoff."""
        population = self.world.population
        if population.agents:
            avg_hunger = sum(a.hunger for a in population.agents) / len(population.agents)
            if avg_hunger > SURVIVAL_HUNGER_THRESHOLD:
                return True
        hardship_categories = {"death", "illness"} | _PROPHECY_HARDSHIP_CATEGORIES
        return any(category in hardship_categories for category, _ in self.world.last_life_events)

    def _nudge_consciousness_grudge(self) -> None:
        """§4 "the consciousness keeps a grudge ledger about
        interventions" (docs/IDEAS-2026-07-EMERGENCE.md): called from
        every genuine player-originated `/intervene/*` branch (never a
        consciousness-authored intervention, which would be the
        consciousness grading its own homework). A nudge landing during
        real hardship reads as help and drifts `World.consciousness_
        grudge_ledger` warm; one landing during calm/plenty reads as
        meddling without cause and drifts it cold — see the two deltas'
        docstrings for the asymmetric magnitudes."""
        delta = (
            CONSCIOUSNESS_GRUDGE_HARDSHIP_DELTA if self._intervention_hardship_context()
            else -CONSCIOUSNESS_GRUDGE_CALM_DELTA
        )
        self.world.consciousness_grudge_ledger = clamp(
            self.world.consciousness_grudge_ledger + delta, -1.0, 1.0,
        )

    def _schedule_due_dialogue(self) -> None:
        """Route this tick's due dialogue pairs (v0.70.0). `due_for_
        dialogue` hands back two buckets: `llm_pairs` (core-core, the
        only exchanges worth an Ollama call) and `fallback_pairs`
        (everything else). Core-core pairs get a real LLM job when there's
        backpressure headroom and daily budget; otherwise they degrade to
        the deterministic fallback like the crowd pairs. Fallback pairs
        are resolved inline (no call, no task) so the crowd stays socially
        alive — relationship/trust/gossip effects still apply — without
        LLM load. See docs/DECISIONS.md, E2 + core-cast pass."""
        llm_pairs, fallback_pairs = self.world.population.due_for_dialogue(
            self.world.config.seed, self.world.clock.tick_count, DIALOGUE_COOLDOWN_TICKS,
        )
        demoted: list[tuple] = []
        # When the LLM is disabled entirely, every pair is deterministic —
        # skip the task/budget machinery and resolve them all inline.
        if not self._cognition_runner.enabled:
            llm_pairs, demoted = [], list(llm_pairs)
        for agent_a, agent_b in llm_pairs:
            # Dialogue is the most expendable LLM job — under backpressure
            # or a spent daily budget the core-core pair still talks, just
            # via the deterministic fallback this tick.
            if self._effective_backlog() >= self._current_backpressure_limit():
                self._cognition_runner.calls_dropped_backpressure += 1
                demoted.append((agent_a, agent_b))
                continue
            if not self._consume_llm_budget():
                demoted.append((agent_a, agent_b))
                continue
            # Post-fission (v0.65.0), a colocated pair isn't guaranteed to
            # belong to the founding settlement — resolve the actual home
            # settlement so its name/tradition/beliefs ground the prompt
            # correctly instead of a fissioned pair "living in" the wrong
            # town. See docs/DECISIONS.md, "dialogue grounding fix."
            local = self._settlement_by_id(agent_a.settlement_id)
            latest_tradition = local.traditions[-1] if local.traditions else ""
            affinity = agent_a.relationships.get(agent_b.id, 0.0)
            beliefs_about = beliefs.beliefs_about_agent(
                agent_a.id, local.beliefs
            ) + beliefs.beliefs_about_agent(agent_b.id, local.beliefs)
            other_settlement_name, cross_relation = "", None
            if agent_b.settlement_id != agent_a.settlement_id:
                other = self._settlement_by_id(agent_b.settlement_id)
                other_settlement_name = other.name
                cross_relation = local.relation_with(other.id)
            lessons = (
                self._matching_lesson(agent_a, self._current_situation_tag(agent_a)),
                self._matching_lesson(agent_b, self._current_situation_tag(agent_b)),
            )
            recent_topics = self.world.population.recent_dialogue_topics(agent_a.id, agent_b.id)
            # v0.87.16 "reduce conversational convergence": weather only
            # actually reaches the prompt text when it's genuinely
            # notable — see dialogue.build_prompt's weather_notable
            # docstring.
            weather_notable = (
                self.world.weather.sky() not in ("clear", "partly_cloudy", "overcast")
                or self.world.weather.wind_label() == "gale"
            )
            grounded_recent = recent_events_diverse(self.conn, limit=5)
            grounded_event = grounded_recent[0]["description"] if grounded_recent else ""
            is_family_pair = (
                (agent_a.parents is not None and agent_b.id in agent_a.parents)
                or (agent_b.parents is not None and agent_a.id in agent_b.parents)
            )
            opportunity_rng = _namespaced_rng(
                self.world.config.seed, self.world.clock.tick_count,
                f"dialogue_opportunity_{agent_a.id}_{agent_b.id}",
            )
            settlement_topics = [t for t, _count in local.top_topics()]
            opportunity_candidates = dialogue.build_opportunity_candidates(
                agent_a, agent_b, is_family_pair, recent_topics, settlement_topics,
                list(local.place_names.values()), grounded_event, weather_notable,
                self.world.weather.describe(),
            )
            opportunities = dialogue.select_opportunities(opportunity_candidates, opportunity_rng)
            prompt = dialogue.build_prompt(
                agent_a, agent_b, affinity, local.name, latest_tradition,
                self.world.clock.season, self.world.weather.describe(), beliefs_about=beliefs_about,
                other_settlement_name=other_settlement_name, cross_settlement_relation=cross_relation,
                lessons=lessons, recent_topics=recent_topics, weather_notable=weather_notable,
                lexicon=local.lexicon, settlement_topics=settlement_topics,
                place_names=list(local.place_names.values()), grounded_event=grounded_event,
                opportunities=opportunities,
            )
            fallback = dialogue.fallback_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
            self._reserved_this_tick += 1
            task = asyncio.create_task(
                self._run_dialogue(
                    agent_a.id, agent_b.id, prompt, fallback,
                    structured_input={
                        "affinity": affinity, "settlement": local.name,
                        "other_settlement_name": other_settlement_name,
                        "weather_notable": weather_notable, "recent_topics": recent_topics,
                        # "Improve context selection instead of context
                        # quantity" + review-pack diagnostics (explicit
                        # live request): which opportunity category(ies)
                        # actually got surfaced this call, plus which
                        # optional context fields were genuinely
                        # available — lets `llm/review_diagnostics.py`
                        # measure topic diversity and context usage
                        # directly from the archive instead of re-parsing
                        # prompt text.
                        "opportunities": [category for category, _text in opportunities],
                        "context_available": {
                            "pair_history": bool(recent_topics),
                            "settlement_topic": bool(settlement_topics),
                            "place": bool(local.place_names),
                            "village_event": bool(grounded_event),
                            "family": is_family_pair,
                            "beliefs": bool(beliefs_about),
                            "lexicon": bool(local.lexicon),
                        },
                    },
                    settlement=local.name,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        for agent_a, agent_b in fallback_pairs + demoted:
            self._queue_fallback_dialogue(agent_a, agent_b)

    def _queue_fallback_dialogue(self, agent_a, agent_b) -> None:
        """Resolve a dialogue pair via the deterministic fallback and push
        it onto the same pending-results queue an LLM exchange uses, so it
        flows through `_apply_pending_dialogue_results` identically (same
        relationship/trust/gossip effects, logging, surfacing) — just with
        no Ollama call. The crowd's social life, and any core-core pair
        that lost its LLM slot to backpressure/budget, runs through here.
        See _schedule_due_dialogue (v0.70.0)."""
        affinity = agent_a.relationships.get(agent_b.id, 0.0)
        fallback = dialogue.fallback_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
        parsed = dialogue.parse_dialogue(fallback, fallback)
        self._pending_dialogue_results.append(
            (self.world.clock.tick_count, agent_a.id, agent_b.id, parsed, False)
        )

    async def _run_dialogue(
        self, agent_a_id: int, agent_b_id: int, prompt: str, fallback: dict,
        structured_input: dict | None = None, settlement: str | None = None,
    ) -> None:
        scheduled_tick = self.world.clock.tick_count
        call_start = time.perf_counter()
        result, used_fallback, raw_completion = await self._cognition_runner.run(
            prompt, dialogue.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        parsed = dialogue.parse_dialogue(result, fallback)
        # is_llm=not used_fallback: only a genuine core-cast Ollama reply
        # is treated as LLM-authored for event-feed purposes (below) — a
        # core pair that degraded to its fallback text inside the
        # CognitionRunner (timeout/error, not backpressure/budget, which
        # never reach here at all) reads the same as a crowd exchange.
        self._pending_dialogue_results.append(
            (scheduled_tick, agent_a_id, agent_b_id, parsed, not used_fallback)
        )
        self._record_llm_debug(
            "dialogue", prompt, result, used_fallback, (time.perf_counter() - call_start) * 1000,
            system_prompt=dialogue.SYSTEM_PROMPT, raw_completion=raw_completion,
            structured_input=structured_input, npc_ids=[agent_a_id, agent_b_id], settlement=settlement,
            outcome={"status": "queued_pending_apply"},
        )
        self._record_llm_call(used_fallback)

    # --- Phase B: world chronicle --------------------------------------------

    def _maybe_schedule_chronicle(self, events: list[str], previous_season: str) -> None:
        # Was gated on "season_end". With the real 365-day calendar a
        # season is ~91 days — the same "made X4.5x rarer by the real
        # calendar" problem CLAUDE.md already documents for terrain
        # evolution, unaddressed here until now. Moved to month_end for
        # the same reason: a real season is too long a wait in
        # wall-clock terms for a narrative cadence meant to feel alive.
        # See docs/DECISIONS.md, "cadence decoupling" pass.
        if not self._monthly_gate(events, "chronicle"):
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("chronicle")
        settlement = self._job_target()
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        population_summary = self.world.population.summary()
        year = self.world.clock.year
        prompt = chronicle.build_prompt(
            recent, population_summary, previous_season, year,
            settlement_name=settlement.name,
            # Only the newest few traditions reach the prompt — the full
            # list grows unbounded over a multi-year world, and feeding
            # it whole would swell every monthly call's tokens forever
            # (July 2026 review, §3.7). The list itself still persists.
            traditions=settlement.traditions[-PROMPT_CULTURE_LIST_MAX:],
            beliefs=settlement.beliefs[-PROMPT_SETTLEMENT_BELIEFS_MAX:],
            belief_digest=settlement.belief_digest,
            culture_digest=settlement.culture_digest,
            place_names=dict(settlement.place_names),
            folklore=list(settlement.folklore),
            narrative_theme=self._narrative_theme_bias(settlement),
        )
        fallback = chronicle.fallback_summary(
            recent, population_summary, previous_season, year,
            seed_hint=self.world.clock.tick_count,
        )

        def apply(result: dict, used_fallback: bool) -> None:
            self._log("chronicle", chronicle.parse_summary(result, fallback))

        self._schedule_llm_job(
            "chronicle", prompt, chronicle.SYSTEM_PROMPT, fallback, apply, settlement=settlement.name,
        )

    # --- documentary mode: a yearly narrated look-back --------------------------

    def _maybe_schedule_documentary(self, events: list[str]) -> None:
        """Gated on `year_end` — deliberately the rarest narrative
        cadence (chronicle is monthly, this is yearly), matching
        "periodically generates a narrated summary of the world's
        evolution" from the Observatory UI direction. Built from the
        curated history table (`persistence.snapshot.history_events`,
        the same milestone-only subset the UI's History tab already
        uses) rather than chronicle's everything-included recent-events
        window — a documentary looks back at what mattered, not routine
        noise. No documentary is scheduled before the settlement has a
        name (nothing yet to narrate)."""
        if not self._season_year_gate(events, "documentary", "year_end") or not self.world.settlement.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("documentary")
        milestones = history_events(self.conn, limit=40)
        population_summary = self.world.population.summary()
        prompt = documentary.build_prompt(
            self.world.settlement.name, self.world.settlement.era, self.world.clock.year,
            milestones, population_summary, self.world.settlement.temperament,
            records=self.world.settlement.records[-5:],
        )
        fallback = documentary.fallback_narration(
            self.world.settlement.name, self.world.clock.year, milestones, population_summary,
        )

        def apply(result: dict, used_fallback: bool) -> None:
            self._log("documentary", documentary.parse_narration(result, fallback))

        self._schedule_llm_job("documentary", prompt, documentary.SYSTEM_PROMPT, fallback, apply)

    # --- on-demand simulation summary (user-triggered, not cadence-gated) ------

    def _schedule_summary(self) -> None:
        """Applied the tick after `POST /summary/request` enqueues a
        `request_summary` intervention (same enqueue-now/apply-next-tick
        seam as every other intervention). Deliberately NOT gated by
        `_settlement_job_backpressured()` — that gate exists to smooth
        out the *coincident* monthly cluster of several jobs firing on
        the same boundary tick; a single user-triggered request is not
        part of that cluster, and silently dropping it would leave the
        UI's "generating..." spinner waiting for a job that was never
        scheduled. The daily LLM ceiling (`_schedule_llm_job`'s own
        `_consume_llm_budget` check) still applies — a spent budget
        degrades this to the deterministic fallback like any other job,
        it just never vanishes outright."""
        settlement = self._job_target()
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        population_summary = self.world.population.summary()
        settlement_summary = settlement.summary()
        year = self.world.clock.year
        prompt = summary.build_prompt(
            settlement.name, settlement.era, year, recent,
            population_summary, settlement_summary, settlement.current_priority,
            mood=dict(settlement.mood),
        )
        fallback = summary.fallback_summary(settlement.name, year, recent, population_summary)
        self.world.sim_summary_pending = True

        def apply(result: dict, used_fallback: bool) -> None:
            self.world.sim_summary_text = summary.parse_summary(result, fallback)
            self.world.sim_summary_tick = self.world.clock.tick_count
            self.world.sim_summary_pending = False
            self._log("sim_summary", self.world.sim_summary_text)

        self._schedule_llm_job("sim_summary", prompt, summary.SYSTEM_PROMPT, fallback, apply)

    # --- §3 "Ask the Chronicler" (on-demand, subjective) -----------------------

    def _schedule_chronicler_answer(self, question: str, settlement_id: int | None) -> None:
        """Applied the tick after `POST /ask-chronicler` enqueues an
        `ask_chronicler` intervention — same enqueue-now/apply-next-tick
        seam as `_schedule_summary`, and deliberately NOT gated by
        `_settlement_job_backpressured()` for the identical reason: a
        single user-triggered question isn't part of the coincident
        monthly job cluster that gate exists to smooth. Unlike `summary`,
        the prompt is built ONLY from the settlement's own narrative
        material (folklore/chronicle/beliefs/records) — never population/
        settlement stat dicts — so the answer is genuinely subjective,
        never a ground-truth readout dressed up as in-character text."""
        settlement = self._settlement_by_id(settlement_id) if settlement_id is not None else self.world.settlement
        question = question.strip()[:300]
        if not question:
            return
        chronicle_events = [
            e for e in recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
            if e["category"] in ("chronicle", "documentary")
        ]
        prompt = chronicler.build_prompt(
            settlement.name, question, list(settlement.folklore), chronicle_events,
            list(settlement.beliefs), list(settlement.records),
        )
        fallback = chronicler.fallback_chronicler(question)
        self.world.chronicler_question = question
        self.world.chronicler_pending = True

        def apply(result: dict, used_fallback: bool) -> None:
            self.world.chronicler_answer = chronicler.parse_chronicler(result, fallback)
            self.world.chronicler_answer_tick = self.world.clock.tick_count
            self.world.chronicler_pending = False
            self._log("chronicler_answer", f"Asked of the chronicler: \"{question}\" — {self.world.chronicler_answer}")

        self._schedule_llm_job("chronicler", prompt, chronicler.SYSTEM_PROMPT, fallback, apply)

    # --- §5 "While you were away" digest (on-demand) ---------------------------

    def _schedule_away_digest(self) -> None:
        """Applied the tick after `POST /digest/request` enqueues a
        `request_digest` intervention — same enqueue-now/apply-next-tick
        seam as `_schedule_summary`/`_schedule_chronicler_answer`,
        deliberately NOT backpressure-gated for the same reason (a
        single user-triggered request isn't part of the coincident
        monthly job cluster that gate exists to smooth). Covers events
        since the PREVIOUS digest's tick (or world start, -1, the first
        time), headlined by whatever touches agents the observer has
        actually inspected (`_watched_agent_names`) — see docs/IDEAS-
        2026-07-EMERGENCE.md §5."""
        since_tick = self.world.away_digest_tick
        current_tick = self.world.clock.tick_count
        events = events_since_tick(self.conn, since_tick, limit=200)
        watched_names = self._watched_agent_names()
        settlement = self._job_target()
        prompt = digest.build_prompt(settlement.name, since_tick, current_tick, events, watched_names)
        fallback = digest.fallback_digest(events, watched_names)
        self.world.away_digest_pending = True
        self.world.away_digest_since_tick = since_tick

        def apply(result: dict, used_fallback: bool) -> None:
            self.world.away_digest_text = digest.parse_digest(result, fallback)
            self.world.away_digest_tick = current_tick
            self.world.away_digest_pending = False
            self._log("away_digest", self.world.away_digest_text)

        self._schedule_llm_job("away_digest", prompt, digest.SYSTEM_PROMPT, fallback, apply)

    # --- Phase E: village culture (traditions) --------------------------------

    def _maybe_schedule_tradition(self, events: list[str]) -> None:
        """A named settlement invents a new tradition once per season — a
        slower, generational cadence than the chronicle's monthly one.
        Was year_end; moved to season_end for the same real-calendar
        reason as chronicle/festival/town_brain (a real year is 365
        days now — see docs/DECISIONS.md, "cadence decoupling" pass)
        while staying rarer/more deliberate than their monthly cadence.
        Unnamed settlements (no standing building yet) have no culture
        to speak of, so nothing is scheduled. See docs/DECISIONS.md, E1."""
        target = self._job_target()
        if not self._season_year_gate(events, "tradition", "season_end") or not target.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("tradition")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        traditions = target.traditions
        prompt = culture.build_prompt(
            target.name, recent, traditions[-PROMPT_CULTURE_LIST_MAX:], self.world.clock.year,
        )
        # `traditions_established` (a persistent, never-decremented
        # counter) rather than len(traditions) — the stored list is
        # capped at CULTURE_LIST_MAX_STORED, so list length alone would
        # eventually corrupt "Tradition the Nth"-style fallback naming.
        fallback = culture.fallback_tradition(
            target.name, self.world.clock.year, target.traditions_established,
        )
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            name, description, influence = culture.parse_tradition(result, fallback)
            entry = f"{name}: {description}"
            settlement = self._settlement_by_id(target_id)
            settlement.traditions.append(entry)
            settlement.traditions_established += 1
            if len(settlement.traditions) > CULTURE_LIST_MAX_STORED:
                settlement.traditions = settlement.traditions[-CULTURE_LIST_MAX_STORED:]
            if influence:
                # Culture with mechanical teeth: this tradition adds one
                # bounded stack to its influence category — see
                # buildings.culture_effect_multiplier and its consumers
                # (festival bonds, harvest relief, grief cost).
                settlement.culture_effects[influence] = settlement.culture_effects.get(influence, 0) + 1
            self._log("tradition", f"{settlement.name or 'The village'} established a new tradition — {entry}")

        self._schedule_llm_job("tradition", prompt, culture.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_folklore(self, events: list[str]) -> None:
        """Phase K "folklore condensation" (docs/VISION-2026-07.md,
        "Knowledge & Story") — monthly, same call-volume shape as
        tradition/invention/festival (one bounded settlement job in the
        existing rotation). Reads the settlement's own recent rumor-
        category events (`events_by_category`, not the diversity-
        adjusted digest — folklore specifically wants the literal rumor
        stream, the diversity fix exists to keep OTHER prompts from
        being crowded by routine events, and rumors are never routine)
        and asks the LLM to condense them into one enduring tale, or
        honestly say there's nothing worth telling yet — most months
        that's the real, expected answer, not every month needs to mint
        a new legend. See llm/folklore.py.

        Constitution §7/§8 efficiency pass (v0.86.5): with zero rumor
        events this month, a real LLM call is near-guaranteed to answer
        "nothing worth telling" against a prompt that literally reads
        "No rumors have been circulating lately" — `fallback_folklore`
        already encodes this (it only ever proposes a tale when
        `rumor_events` is non-empty). Skip the call entirely rather than
        spend real LLM budget/latency to confirm what's already known —
        same "skip a call whose precondition guarantees a trivial
        result" discipline `_maybe_schedule_invention`'s prosperity gate
        already uses. Still resolves the month (no folklore forms),
        matching the expected common-case outcome exactly; a month with
        real rumor material is completely unaffected."""
        target = self._job_target()
        if not self._monthly_gate(events, "folklore") or not target.name:
            return
        rumor_events = events_by_category(self.conn, "rumor", limit=20)
        if not rumor_events:
            self._mark_monthly_resolved("folklore")
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("folklore")
        existing_folklore = list(target.folklore)
        prompt = folklore.build_prompt(target.name, rumor_events, existing_folklore)
        fallback = folklore.fallback_folklore(target.name, rumor_events)
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            entry = folklore.parse_folklore(result, fallback)
            if entry is None:
                return  # nothing worth telling this month — a real, expected outcome
            settlement = self._settlement_by_id(target_id)
            entry["tick"] = self.world.clock.tick_count
            settlement.folklore.append(entry)
            if len(settlement.folklore) > FOLKLORE_MAX_STORED:
                settlement.folklore = settlement.folklore[-FOLKLORE_MAX_STORED:]
            self._log("folklore", f"{settlement.name or 'The village'} now tells a new tale — {entry['tale']}")

        self._schedule_llm_job(
            "folklore", prompt, folklore.SYSTEM_PROMPT, fallback, apply, settlement=target.name,
        )

    # --- Phase E3: inventions (tech-tier unlocks) -----------------------------

    def _maybe_schedule_invention(self, events: list[str]) -> None:
        """A prosperous, named settlement may invent something once per
        season — same cadence as tradition (was year_end; see
        docs/DECISIONS.md, "cadence decoupling" pass), but gated by
        surplus and rolled independently (deliberately rare, see
        INVENTION_CHANCE_PER_SEASON, tuned so four seasonal rolls
        reproduce roughly the original yearly rate), so it stays a
        notable event rather than a formality. See docs/DECISIONS.md,
        E3."""
        settlement = self._job_target()
        if not self._season_year_gate(events, "invention", "season_end") or not settlement.name:
            return
        prosperous = (
            settlement.currency >= INVENTION_CURRENCY_THRESHOLD
            or settlement.materials >= MATERIALS_CAPACITY * INVENTION_MATERIALS_FRACTION
        )
        if not prosperous:
            return
        if self._settlement_job_backpressured():
            return
        # An educated town invents more — a real school/university, not
        # just prosperity, measurably raises the odds. See
        # buildings.education_invention_bonus, docs/DECISIONS.md,
        # "LLM-as-brain batch."
        chance = min(1.0, INVENTION_CHANCE_PER_SEASON * education_invention_bonus(settlement.education_level))
        # docs/IDEAS-2026-07-EMERGENCE.md §9 "stalled era progression":
        # a settlement that has already built what the NEXT era needs
        # (see ERA_INFRASTRUCTURE_REQUIREMENTS) invents measurably more
        # readily — visible civic development is now a real, controllable
        # lever toward progression, not just window dressing while
        # waiting on the invention roll. No-op (progress=1.0, since
        # `industrial` has no requirement entry) once past `digital`.
        next_era_index = ERA_ORDER.index(settlement.era) + 1 if settlement.era in ERA_ORDER else len(ERA_ORDER)
        if next_era_index < len(ERA_ORDER):
            huts, roads, schools, carts = self._infra_counts(settlement)
            infra_progress = era_infrastructure_progress(ERA_ORDER[next_era_index], huts, roads, schools, carts)
            chance = min(1.0, chance * (1.0 + infra_progress * INFRASTRUCTURE_INVENTION_BONUS_WEIGHT))
        # H5 extension: a skilled population invents somewhat more
        # readily too, on top of (not instead of) education — see
        # SKILL_INVENTION_BONUS_WEIGHT.
        agents = self.world.population.agents
        if agents:
            avg_skill = sum(
                a.skills.get(SKILL_FARMING, 0.0) + a.skills.get(SKILL_CONSTRUCTION, 0.0)
                + a.skills.get(SKILL_MEDICINE, 0.0) for a in agents
            ) / (3 * len(agents))
            chance = min(1.0, chance * (1.0 + avg_skill * SKILL_INVENTION_BONUS_WEIGHT))
        chance = max(0.0, chance * (1.0 + settlement.temperament * TEMPERAMENT_INVENTION_INFLUENCE))
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "invention_roll") >= chance:
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        inventions = settlement.inventions
        prompt = invention.build_prompt(
            settlement.name, recent, inventions[-PROMPT_CULTURE_LIST_MAX:], settlement.tech_level,
            beliefs=settlement.beliefs[-PROMPT_BELIEFS_MAX:],
        )
        # tech_level already is a persistent, never-decremented count of
        # inventions established (one per invention) — reused directly
        # as the fallback ordinal source instead of len(inventions),
        # since that list is now capped at CULTURE_LIST_MAX_STORED.
        fallback = invention.fallback_invention(settlement.name, settlement.tech_level, settlement.tech_level)

        invention_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            name, description = invention.parse_invention(result, fallback)
            entry = f"{name}: {description}"
            settlement = self._settlement_by_id(invention_target_id)
            settlement.inventions.append(entry)
            if len(settlement.inventions) > CULTURE_LIST_MAX_STORED:
                settlement.inventions = settlement.inventions[-CULTURE_LIST_MAX_STORED:]
            settlement.tech_level += 1
            invention_detail = f"{settlement.name or 'The village'} invented {entry}"
            self._log("invention", invention_detail)
            if sum(s.tech_level for s in self.world.settlements) == 1:
                self._append_highlight("first_invention", f"The world's first invention: {invention_detail}")
            self._maybe_advance_era(settlement)
            # v0.87.15 "knowledge lifecycle" (docs/IDEAS-2026-07-
            # EMERGENCE.md §7): the inventor becomes this invention's
            # first (and initially only) knower — core cast preferred
            # (a real, recognizable person), any living local otherwise.
            local = [a for a in self.world.population.agents if a.settlement_id == settlement.id]
            core_local = [a for a in local if a.id in self.world.population.core_agent_ids]
            candidates = core_local or local
            if candidates:
                rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "invention_inventor")
                inventor = rng.choice(candidates)
                settlement.invention_knowledge[entry] = {"knowers": [inventor.id], "dormant": False}
                if len(settlement.invention_knowledge) > INVENTION_KNOWLEDGE_MAX_TRACKED:
                    oldest_key = next(iter(settlement.invention_knowledge))
                    del settlement.invention_knowledge[oldest_key]

        self._schedule_llm_job("invention", prompt, invention.SYSTEM_PROMPT, fallback, apply)

    def _infra_counts(self, settlement) -> tuple[int, int, int, int]:
        """`(huts, established_roads, schools, ready_carts)` — the four
        infrastructure counts `ERA_INFRASTRUCTURE_REQUIREMENTS` gates
        era progression on (docs/IDEAS-2026-07-EMERGENCE.md §9). Roads
        are genuinely world-wide, not per-settlement (`World.roads` has
        no settlement scoping), so they're read as-is; huts/schools/
        carts are this settlement's own. Cheap — bounded by this one
        settlement's building/vehicle counts, called at most once per
        season per settlement (from `_maybe_schedule_invention`) plus
        once per invention application (`_maybe_advance_era`)."""
        huts = sum(
            1 for b in settlement.buildings
            if b.kind is BuildingKind.HUT and b.stage is BuildingStage.STANDING
        )
        schools = sum(
            1 for b in settlement.buildings
            if b.kind is BuildingKind.SCHOOL and b.stage is BuildingStage.STANDING
        )
        carts = sum(
            1 for v in settlement.vehicles
            if v.kind is VehicleKind.CART and v.stage is VehicleStage.READY
        )
        established_roads = self.world.roads.summary()["established_roads"]
        return huts, established_roads, schools, carts

    def _settlement_economic_need(self, settlement) -> str:
        """Plain-language name of whatever this settlement's own real
        state is shortest on right now — used only as grounding texture
        for `noncore_nudge`'s occasional plan suggestion (see that
        module's docstring), never anything mechanical. Materials
        (measured against MATERIALS_CAPACITY) is checked first since
        it's the most immediate, universally-relevant lever; otherwise
        whichever of the next era's own infrastructure counts has the
        lowest fraction of its requirement met. Empty string when
        nothing stands out (materials plentiful, infra requirement
        already met, or already at the final era)."""
        if settlement.materials < MATERIALS_CAPACITY * 0.3:
            return "materials"
        next_era_index = ERA_ORDER.index(settlement.era) + 1 if settlement.era in ERA_ORDER else len(ERA_ORDER)
        if next_era_index >= len(ERA_ORDER):
            return ""
        requirement = ERA_INFRASTRUCTURE_REQUIREMENTS.get(ERA_ORDER[next_era_index])
        if not requirement:
            return ""
        huts, roads, schools, carts = self._infra_counts(settlement)
        current = {"huts": huts, "roads": roads, "schools": schools, "carts": carts}
        shortfalls = {
            k: (current[k] / requirement[k]) for k in requirement if requirement[k] and current[k] < requirement[k]
        }
        if not shortfalls:
            return ""
        worst = min(shortfalls, key=shortfalls.get)
        return {"huts": "housing", "roads": "roads", "schools": "a school", "carts": "carts"}[worst]

    def _maybe_advance_era(self, settlement=None) -> None:
        """A settlement starts in the industrial era (see
        `Settlement.era`) and moves forward as inventions accumulate —
        each new era is a mechanically real unlock (see
        `buildings.era_for_tech_level_gated`, the FACTORY building
        kind), not just a label. See docs/DECISIONS.md, real-calendar/
        genesis-seed follow-up.

        docs/IDEAS-2026-07-EMERGENCE.md §9 "stalled era progression":
        `tech_level` alone can no longer vault a settlement past an era
        whose own `ERA_INFRASTRUCTURE_REQUIREMENTS` haven't been built
        yet — see `era_for_tech_level_gated`'s docstring. This is
        strictly additive to the fix above (`_maybe_schedule_
        invention`'s infra-driven invention-chance bonus) — a
        well-developed settlement clears both bars readily; one that
        never builds huts/roads/schools/carts stays capped at a lower
        era even with a very high `tech_level`, which is the intended
        "earned, legible" progression, not a regression (a settlement
        could previously reach `digital` on a lucky roll streak with
        zero of the era's own infrastructure standing)."""
        settlement = settlement if settlement is not None else self.world.settlement
        huts, roads, schools, carts = self._infra_counts(settlement)
        new_era = era_for_tech_level_gated(settlement.tech_level, settlement.era, huts, roads, schools, carts)
        if new_era == settlement.era:
            return
        settlement.era = new_era
        detail = f"{settlement.name or 'The village'} has entered the {new_era} era — {ERA_DESCRIPTIONS[new_era]}."
        self._log("era_advance", detail)
        self._maybe_schedule_era_branch(settlement, new_era)
        # §5 "Anomaly/highlight log" widened per a live report ("highlights
        # has only highlighted population growth") — the original two
        # metric-only checks (_detect_metric_highlights) fire often
        # relative to the rarer milestone hooks (first_ritual/family_feud/
        # successor_founded), so a typical run's highlight log skewed
        # entirely toward population swings. Era advances are exactly the
        # kind of rare, genuinely notable civilizational milestone this
        # log was meant to surface — every real advance, not just the
        # settlement's first (there are only a handful per settlement
        # ever, unlike rituals/feuds which can recur).
        self._append_highlight("era_advance", detail)

    def _maybe_schedule_era_branch(self, settlement, new_era: str) -> None:
        """v1 audit fix ("let emergence/LLM steer its own course of era
        progression"): fires exactly once, right after `_maybe_advance_
        era` moves a settlement into a new era — never periodically, so
        it needs no round-robin day slot and stays trivially within the
        LLM-volume budget (a handful of calls per settlement's whole
        life). Chooses one of `ERA_BRANCH_NAMES` (see llm/era_branch.py)
        to lean the settlement's own future `choose_building_kind` odds
        toward — real, bounded emergent divergence between settlements
        reaching the same era via the same tech path, never an
        unsupported invented outcome."""
        rng = namespaced_rng(self.world.config.seed, self.world.clock.tick_count, f"era_branch_{settlement.id}")
        fallback = era_branch.fallback_branch(rng)
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        prompt = era_branch.build_prompt(settlement.name, new_era, recent, settlement.era_branch)
        branch_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            branch, reason = era_branch.parse_branch(result, fallback)
            target = self._settlement_by_id(branch_target_id)
            if target is None:
                return
            target.era_branch = branch
            if reason:
                self._log("era_branch", f"{target.name or 'The village'} is leaning {branch} — {reason}")

        self._schedule_llm_job(
            "era_branch", prompt, era_branch.SYSTEM_PROMPT, fallback, apply,
            settlement=settlement.name,
        )

    # --- collective behaviour: festivals ----------------------------------------

    def _maybe_schedule_festival(self, events: list[str]) -> None:
        """A named, well-fed settlement may hold a festival once per
        month (was once per season — moved for the same real-calendar
        reason as chronicle/town_brain, see docs/DECISIONS.md, "cadence
        decoupling" pass) — a wellbeing gate (not prosperity, contrast
        _maybe_schedule_invention), deliberately distinct from both
        traditions and inventions' now-seasonal cadence. See
        docs/DECISIONS.md, collective-behaviour pass."""
        festival_target = self._job_target()
        if not self._monthly_gate(events, "festival") or not festival_target.name:
            return
        if self.world.population.avg_hunger() > FESTIVAL_HUNGER_GATE:
            return
        # §9 "more cross-system interactions": a standing family feud
        # dampens the village's mood, not just the two households
        # involved — real discord makes a celebration less likely.
        festival_chance = FESTIVAL_CHANCE_PER_MONTH
        if any(
            i.feuds for i in festival_target.institutions if i.kind is InstitutionKind.FAMILY
        ):
            festival_chance *= 1.0 - FAMILY_FEUD_FESTIVAL_PENALTY
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "festival_roll") >= festival_chance:
            return
        if self._settlement_job_backpressured():
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        festivals = festival_target.festivals
        prompt = festival.build_prompt(
            festival_target.name, recent, self.world.clock.season,
            beliefs=festival_target.beliefs[-PROMPT_BELIEFS_MAX:],
        )
        # festivals_held (persistent, never-decremented) rather than
        # len(festivals) — same CULTURE_LIST_MAX_STORED-cap rationale as
        # tradition/invention naming above.
        fallback = festival.fallback_festival(festival_target.name, festival_target.festivals_held)
        festival_target_id = festival_target.id

        def apply(result: dict, used_fallback: bool) -> None:
            name, description = festival.parse_festival(result, fallback)
            entry = f"{name}: {description}"
            settlement = self._settlement_by_id(festival_target_id)
            settlement.festivals.append(entry)
            settlement.festivals_held += 1
            if len(settlement.festivals) > CULTURE_LIST_MAX_STORED:
                settlement.festivals = settlement.festivals[-CULTURE_LIST_MAX_STORED:]
            affected = self.world.population.hold_festival(settlement)
            self._log("festival", f"{settlement.name or 'The village'} held {entry} ({affected} bonds strengthened)")

        self._schedule_llm_job("festival", prompt, festival.SYSTEM_PROMPT, fallback, apply)

    # --- Phase M: ritual detection (free, deterministic) + religion (one call) -

    def _detect_ritual_signals(self) -> None:
        """Deterministic, zero-LLM-cost detector (Phase M, docs/VISION-
        2026-07.md, "Faith & Meaning") — called every tick from
        `_tick_once`, cheap even so: a death is rare, and the per-
        settlement check below is a handful of dict/list lookups bounded
        by MAX_SETTLEMENTS. Two recognized patterns, matching the vision
        doc's own examples:

        - "communal_feast": the settlement has held enough festivals
          (`festivals_held`, already a persistent counter — no new
          tracking needed) — each one already implicitly "after good
          fortune," since `_maybe_schedule_festival` only ever fires
          when the settlement is well-fed (FESTIVAL_HUNGER_GATE).
        - "shrine_mourning": a death occurred this tick while the
          settlement has a STANDING shrine. Deaths are settlement-
          agnostic in `last_life_events` (just category/description
          strings, no settlement id) — rather than invent that
          association, this counts a world-wide death tick against
          every settlement that currently has a standing shrine, which
          is an acceptable looseness for a texture-only heuristic (most
          worlds have exactly one settlement for a long time anyway).

        Neither pattern costs an LLM call; `_maybe_schedule_religion`
        below is the one place accumulated rituals get spent on a real
        model read."""
        had_death = any(category == "death" for category, _ in self.world.last_life_events)
        # "the LLM (and the town) learns like a human" batch: same
        # settlement-agnostic looseness as `had_death` above — a
        # starvation death this tick counts against every named
        # settlement's `pattern_signal_counts`, feeding
        # `_maybe_schedule_beliefs`'s "pattern noticed" grounding line.
        had_starvation_death = any(
            category == "death" and "starvation" in description
            for category, description in self.world.last_life_events
        )
        # v0.87.2 (deeper settlement pattern-recognition, item 4 of
        # docs/VISION-2026-07-LEARNING.md's deferred list): a genuinely
        # NEW outbreak origin, matched on "fallen ill" (Population.
        # _maybe_outbreak's index-case text) rather than the "illness"
        # category alone, which also covers person-to-person spread
        # ("caught the illness from...") — that's the disease already
        # noticed, not a new one starting.
        had_new_outbreak = any(
            category == "illness" and "fallen ill" in description
            for category, description in self.world.last_life_events
        )
        had_wildlife_recolonization = any(
            category == "wildlife_recolonized" for category, _ in self.world.last_life_events
        )
        for stl in self.world.settlements:
            if not stl.name:
                continue
            if had_death and any(
                b.kind is BuildingKind.SHRINE and b.stage is BuildingStage.STANDING for b in stl.buildings
            ):
                stl.ritual_signal_counts["shrine_mourning"] = stl.ritual_signal_counts.get("shrine_mourning", 0) + 1
            if had_starvation_death:
                counts = stl.pattern_signal_counts
                counts["starvation_death"] = counts.get("starvation_death", 0) + 1
            if had_new_outbreak:
                counts = stl.pattern_signal_counts
                counts["disease_outbreak"] = counts.get("disease_outbreak", 0) + 1
            if had_wildlife_recolonization:
                counts = stl.pattern_signal_counts
                counts["wildlife_recolonization"] = counts.get("wildlife_recolonization", 0) + 1
            self._maybe_promote_ritual(stl)

    def _maybe_promote_ritual(self, stl: "Settlement") -> None:
        existing_patterns = {r["pattern"] for r in stl.rituals}
        if (
            stl.festivals_held >= RITUAL_PROMOTION_THRESHOLD
            and "communal_feast" not in existing_patterns
        ):
            stl.rituals.append({
                "pattern": "communal_feast",
                "description": "the village gathers to feast whenever fortune allows it",
                "formed_tick": self.world.clock.tick_count,
            })
            if len(stl.rituals) > RITUAL_MAX_STORED:
                stl.rituals = stl.rituals[-RITUAL_MAX_STORED:]
            detail = f"{stl.name} has begun to treat its festivals as something more than celebration."
            self._log("ritual_formed", detail)
            if sum(len(s.rituals) for s in self.world.settlements) == 1:
                self._append_highlight("first_ritual", f"The first ritual in this world took shape: {detail}")
        mourning = stl.ritual_signal_counts.get("shrine_mourning", 0)
        if mourning >= RITUAL_PROMOTION_THRESHOLD and "shrine_mourning" not in existing_patterns:
            stl.rituals.append({
                "pattern": "shrine_mourning",
                "description": "the village gathers at the shrine to mourn its dead",
                "formed_tick": self.world.clock.tick_count,
            })
            if len(stl.rituals) > RITUAL_MAX_STORED:
                stl.rituals = stl.rituals[-RITUAL_MAX_STORED:]
            stl.ritual_signal_counts["shrine_mourning"] = 0  # consumed — don't re-promote a duplicate
            self._log("ritual_formed", f"{stl.name} has taken to mourning its dead at the shrine.")

    def _resolve_prophecies(self) -> None:
        """§3 "self-fulfilling prophecy" (docs/IDEAS-2026-07-EMERGENCE.md):
        runs every tick, zero LLM cost. While a settlement holds a
        `prophecy` with `status == "pending"`, accumulates a same-tick
        hardship/prosperity tally from `World.last_life_events` — the
        same settlement-agnostic looseness `_detect_ritual_signals`
        already accepts for `shrine_mourning` (most worlds have one
        settlement for a long time anyway). At `resolve_tick`, the
        prophecy is judged confirmed or forgotten purely from which
        tally led — nothing here ever *causes* an event to happen;
        if the village reads an ominous prophecy and stockpiles, or a
        hopeful one and builds, any resulting hardship/prosperity is
        the villagers' own doing, per this project's whole Phase G
        ambiguity discipline. Deliberately simpler than the idea doc's
        own "the beliefs job later judges it" framing — a second LLM
        call to judge fulfillment would double this feature's call
        cost for a judgment the settlement's own event record can
        already answer deterministically."""
        had_hardship = any(category in _PROPHECY_HARDSHIP_CATEGORIES for category, _ in self.world.last_life_events)
        had_prosperity = any(category in _PROPHECY_PROSPERITY_CATEGORIES for category, _ in self.world.last_life_events)
        tick = self.world.clock.tick_count
        for stl in self.world.settlements:
            prophecy = stl.prophecy
            if prophecy is None or prophecy.get("status") != "pending":
                continue
            if had_hardship:
                prophecy["hardship_signals"] = prophecy.get("hardship_signals", 0) + 1
            if had_prosperity:
                prophecy["prosperity_signals"] = prophecy.get("prosperity_signals", 0) + 1
            if tick < prophecy.get("resolve_tick", tick):
                continue
            hardship = prophecy.get("hardship_signals", 0)
            prosperity = prophecy.get("prosperity_signals", 0)
            tone = prophecy.get("tone", "ominous")
            confirmed = (tone == "ominous" and hardship > prosperity) or (tone == "hopeful" and prosperity > hardship)
            prophecy["status"] = "confirmed" if confirmed else "forgotten"
            if confirmed:
                self._log(
                    "prophecy_confirmed",
                    f"{stl.name or 'The village'}'s half-remembered words seem, in hindsight, to have known something: \"{prophecy['text']}\"",
                )
            else:
                self._log(
                    "prophecy_forgotten",
                    f"{stl.name or 'The village'}'s old vague words came to nothing in particular, and were mostly forgotten.",
                )
            stl.prophecy = None  # at most one live prophecy at a time

    def _maybe_promote_family_feud(
        self, settlement: "Settlement", family_a: "Institution", family_b: "Institution",
    ) -> None:
        """v0.87.11, "generational feuds between FAMILY institutions"
        (docs/IDEAS-2026-07-EMERGENCE.md §1) — the event-driven
        counterpart to `_maybe_promote_ritual` above: rather than
        scanning every tick, this is called directly from `_maybe_
        schedule_dispute`'s apply() the instant a real `outcome ==
        "feud"` result lands between two different families' members.
        Accumulates `Settlement.family_feud_counts` keyed by the sorted
        family-id pair; once `FAMILY_FEUD_PROMOTION_THRESHOLD` real
        feud outcomes have landed between the same two families, writes
        a durable, symmetric `Institution.feuds` entry on BOTH families
        (a feud isn't one-sided) and resets the counter — a repeated
        pattern promoted once, not re-promoted on every subsequent spat
        between an already-feuding pair."""
        if Population.families_feuding(family_a, family_b):
            return  # already a durable feud — nothing new to promote
        key = "_".join(str(i) for i in sorted((family_a.id, family_b.id)))
        counts = settlement.family_feud_counts
        counts[key] = counts.get(key, 0) + 1
        if counts[key] < FAMILY_FEUD_PROMOTION_THRESHOLD:
            return
        tick = self.world.clock.tick_count
        family_a.feuds.append({"family_id": family_b.id, "formed_tick": tick})
        if len(family_a.feuds) > FAMILY_FEUD_MAX_STORED:
            family_a.feuds = family_a.feuds[-FAMILY_FEUD_MAX_STORED:]
        family_b.feuds.append({"family_id": family_a.id, "formed_tick": tick})
        if len(family_b.feuds) > FAMILY_FEUD_MAX_STORED:
            family_b.feuds = family_b.feuds[-FAMILY_FEUD_MAX_STORED:]
        counts[key] = 0
        detail = (
            f"{family_a.name or 'A family'} and {family_b.name or 'another family'} "
            f"in {settlement.name or 'the village'} have become bitter rivals."
        )
        self._log("family_feud", detail)
        self._append_highlight("family_feud", detail)

    def _maybe_schedule_religion(self, events: list[str]) -> None:
        """Seasonal, one call, gated on having enough accumulated
        `rituals` — the actual crystallization step. Deliberately never
        re-attempts once a religion has formed (v1: religions don't yet
        evolve or get revised, only founded or schismed — see
        `llm/fission.py`'s optional schism field). Nothing guaranteed:
        `llm/religion.py`'s fallback always means "not yet," never an
        invented placeholder faith — see its module docstring."""
        target = self._job_target()
        if not self._season_year_gate(events, "religion", "season_end") or not target.name:
            return
        if target.religion is not None or len(target.rituals) < 1:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("religion")
        omen_history = list(target.omen_history)
        folklore_entries = list(target.folklore)
        prompt = religion.build_prompt(target.name, target.rituals, omen_history, folklore_entries)
        fallback = religion.fallback_religion()
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = religion.parse_religion(result, fallback)
            if parsed is None:
                return  # not yet — a real, expected outcome, see module docstring
            stl = self._settlement_by_id(target_id)
            if stl.religion is not None:
                return  # formed by another in-flight attempt already
            tick = self.world.clock.tick_count
            stl.religion = {
                "name": parsed["name"], "tenets": parsed["tenets"],
                "formed_tick": tick, "schism_of": None,
            }
            # Tenets also become one representative belief entry, riding
            # the existing beliefs machinery (and its institution
            # mirroring) rather than a parallel consumption path — see
            # SettlementCulture.religion's docstring.
            entry = {
                "subject": "the village's faith",
                "belief": f"{parsed['name']}: {'; '.join(parsed['tenets'])}",
                "confidence": 0.7, "subject_agent_id": None, "subject_family_agent_ids": [],
                "formed_tick": tick, "revised_tick": tick, "revision_count": 0,
            }
            stl.beliefs.append(entry)
            if len(stl.beliefs) > beliefs.MAX_BELIEFS:
                weakest = min(stl.beliefs, key=lambda b: b["confidence"])
                stl.beliefs.remove(weakest)
            beliefs.sync_family_beliefs(entry, stl.institutions)
            beliefs.sync_council_beliefs(entry, stl.institutions)
            beliefs.sync_guild_beliefs(entry, stl.institutions)
            self._log(
                "religion_formed",
                f"{stl.name} has come to share a belief it calls {parsed['name']}.",
            )
            if sum(1 for s in self.world.settlements if s.religion is not None) == 1:
                self._append_highlight(
                    "first_religion",
                    f"The first faith in this world took root: {stl.name} now shares a belief called {parsed['name']}.",
                )

        self._schedule_llm_job("religion", prompt, religion.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_narrative_direction(self, events: list[str]) -> None:
        """Quarterly (season_end — a season already IS a real-calendar
        quarter, no new cadence machinery needed), one call: names the
        theme(s) running through the settlement's recent life. Consumed
        ONLY as prompt bias (see `_narrative_theme_bias` below) — never
        schedules or scripts anything on its own. See llm/narrative_
        direction.py's module docstring."""
        target = self._job_target()
        if not self._season_year_gate(events, "narrative_direction", "season_end") or not target.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("narrative_direction")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        mood = dict(target.mood)
        prompt = narrative_direction.build_prompt(
            target.name, recent, target.folklore, mood, target.narrative_themes, target.lexicon,
        )
        fallback = narrative_direction.fallback_direction(mood)
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            themes = narrative_direction.parse_direction(result, fallback)
            stl = self._settlement_by_id(target_id)
            stl.narrative_themes.append({"themes": themes, "formed_tick": self.world.clock.tick_count})
            if len(stl.narrative_themes) > NARRATIVE_THEMES_MAX_STORED:
                stl.narrative_themes = stl.narrative_themes[-NARRATIVE_THEMES_MAX_STORED:]
            self._log("narrative_direction", f"{stl.name}'s recent life reads as: {', '.join(themes)}.")
            # §2 "dialect drift": a real answer only, never fabricated by
            # the fallback (fallback_direction has no coined_term field
            # at all) — rides this call for zero added LLM volume.
            if not used_fallback:
                coined = narrative_direction.parse_coined_term(result)
                if coined is not None:
                    term, meaning = coined
                    stl.lexicon.append({"term": term, "meaning": meaning, "formed_tick": self.world.clock.tick_count})
                    if len(stl.lexicon) > LEXICON_MAX_STORED:
                        stl.lexicon = stl.lexicon[-LEXICON_MAX_STORED:]
                    self._log("dialect_coined", f"{stl.name} has started calling it \"{term}\" — {meaning}")

        self._schedule_llm_job("narrative_direction", prompt, narrative_direction.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_culture_digest(self, events: list[str]) -> None:
        """Quarterly (season_end, same cadence as narrative_direction —
        the cheapest real cadence available, no new cadence machinery
        needed), one call: condenses the settlement's accumulated
        traditions/inventions/festivals/records into one short digest
        sentence, the `belief_digest` treatment applied to culture and
        history instead of beliefs. Unlike beliefs, this history has no
        natural "revise the whole list" existing job to extend for free
        — this is genuinely new call volume, traded directly against
        chronicle/town_brain needing an ever-larger raw slice of these
        lists as history accumulates. See llm/culture_digest.py's module
        docstring. Fallback is a genuine no-op (see `fallback_digest`) —
        `Settlement.culture_digest` is only overwritten on a real
        (non-fallback) answer, same discipline as `belief_digest`."""
        target = self._job_target()
        if not self._season_year_gate(events, "culture_digest", "season_end") or not target.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("culture_digest")
        prompt = culture_digest.build_prompt(
            target.name,
            target.traditions[-CULTURE_DIGEST_INPUT_MAX:],
            target.inventions[-CULTURE_DIGEST_INPUT_MAX:],
            target.festivals[-CULTURE_DIGEST_INPUT_MAX:],
            target.records[-CULTURE_DIGEST_INPUT_MAX:],
        )
        fallback = culture_digest.fallback_digest()
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            if used_fallback:
                return
            digest = culture_digest.parse_digest(result)
            if digest:
                stl = self._settlement_by_id(target_id)
                stl.culture_digest = digest

        self._schedule_llm_job("culture_digest", prompt, culture_digest.SYSTEM_PROMPT, fallback, apply)

    def _institution_job_target(self) -> "tuple[Settlement, object] | None":
        """§9 "institutions get their own persistent memory" (docs/IDEAS-
        2026-07-EMERGENCE.md): a month-indexed round-robin over every
        (settlement, institution) pair with at least one living member
        — same "flat call volume regardless of count" shape `_job_
        target`/`_diplomacy_pair_target` already give settlement-scoped
        jobs, generalized one level deeper since institutions can
        genuinely outnumber settlements. `None` once no settlement has
        any institution yet (a fresh/small world)."""
        pairs = [
            (s, i) for s in self.world.settlements if s.name
            for i in s.institutions if i.member_agent_ids
        ]
        if not pairs:
            return None
        clock = self.world.clock
        month_ordinal = clock.year * len(self.world.config.days_per_month) + clock.month_index
        return pairs[month_ordinal % len(pairs)]

    def _maybe_schedule_institution_culture(self, events: list[str]) -> None:
        """§9 "institutions get their own persistent memory" + "multi-
        layer culture" (docs/IDEAS-2026-07-EMERGENCE.md): condenses ONE
        institution's own beliefs/objective/feud history into a short,
        independently-authored digest — see llm/institution_culture.py's
        module docstring for how this differs from `Institution.beliefs`
        (a filtered mirror) and `Settlement.culture_digest` (the whole
        village). Quarterly, one call for the entire world regardless of
        institution count (`_institution_job_target`'s round-robin).
        Fallback is a genuine no-op — `Institution.culture_digest` is
        only overwritten on a real answer, same discipline as
        `Settlement.culture_digest`."""
        target = self._institution_job_target()
        if not self._season_year_gate(events, "institution_culture", "season_end") or target is None:
            return
        settlement, institution = target
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("institution_culture")
        prompt = institution_culture.build_prompt(
            institution.kind.value, institution.name, settlement.name,
            institution.beliefs[-PROMPT_BELIEFS_MAX:], institution.objective, len(institution.feuds),
        )
        fallback = institution_culture.fallback_digest()
        settlement_id, institution_id = settlement.id, institution.id

        def apply(result: dict, used_fallback: bool) -> None:
            if used_fallback:
                return
            digest = institution_culture.parse_digest(result)
            if not digest:
                return
            stl = self._settlement_by_id(settlement_id)
            inst = next((i for i in stl.institutions if i.id == institution_id), None)
            if inst is not None:
                inst.culture_digest = digest

        self._schedule_llm_job(
            "institution_culture", prompt, institution_culture.SYSTEM_PROMPT, fallback, apply,
            settlement=settlement.name,
        )

    @staticmethod
    def _narrative_theme_bias(stl: "Settlement") -> str:
        """The one short "current theme" line town_brain/omens/chronicle/
        Dream() fold into their prompts as ambient bias — never a
        directive, never guaranteed to be acted on, just coloring
        already-real decisions the same thematically-coherent way a
        person's current preoccupations color unrelated choices. Empty
        string (omitted entirely) until Narrative Direction has ever
        fired once."""
        if not stl.narrative_themes:
            return ""
        return ", ".join(stl.narrative_themes[-1]["themes"])

    # --- Phase N: Town Consciousness v2 ---------------------------------------

    def _player_intervention_trend(self, window_days: int = 90) -> str:
        """"the LLM (and the town) learns like a human" batch: a rough
        increasing/decreasing/steady read on how often `/intervene/*`
        has fired lately, from `World.consciousness_intervention_log`
        (`{"kind", "detail", "tick"}` dicts — every logged intervention,
        "none" included, counts as a real outside touch here, unlike
        `interventions_text` in llm/consciousness.py's own prompt, which
        deliberately skips "none" entries since those have nothing to
        narrate). Compares the count in the most recent `window_days`
        against the `window_days` before that — a plain frequency trend,
        distinct from `player_standing`'s warm/cold *feeling* about it.
        Returns "" (folded into nothing) until there's at least one full
        window of history to compare, so an early-game world doesn't get
        a meaningless read off a handful of data points. Dev-console/
        raw-state only — Phase G ambiguity discipline (see CLAUDE.md)
        keeps this out of the main UI, same as temperament/mood/player_
        standing."""
        log = self.world.consciousness_intervention_log
        if not log:
            return ""
        ticks_per_day = self.world.config.minutes_per_day // self.world.config.sim_minutes_per_tick
        window_ticks = window_days * ticks_per_day
        now = self.world.clock.tick_count
        if now < window_ticks * 2:
            return ""
        recent_count = sum(1 for e in log if now - window_ticks <= e.get("tick", 0) < now)
        prior_count = sum(1 for e in log if now - window_ticks * 2 <= e.get("tick", 0) < now - window_ticks)
        if recent_count == prior_count:
            direction = "steady"
        else:
            direction = "increasing" if recent_count > prior_count else "decreasing"
        theory = self._leading_player_theory()
        if not theory:
            return direction
        # Richer Town Consciousness narrative modeling (deferred item 4,
        # docs/VISION-2026-07-LEARNING.md): the frequency trend and the
        # consciousness's own standing theory about the player used to
        # sit in the prompt as two unconnected facts (this trend line
        # plus `player_model_text` in llm/consciousness.py's build_
        # prompt). Folding the leading theory directly into the trend
        # sentence lets the model reason about whether fresh behavior
        # confirms or complicates what it already believes, rather than
        # re-deriving the connection itself from two separate lines —
        # zero added LLM call volume, same "distill instead of adding a
        # call" discipline as every other digest in this project.
        return f'{direction} (your leading theory: "{theory}")'

    def _leading_player_theory(self) -> str:
        """The highest-confidence entry currently in `consciousness_
        player_model`, or "" if the consciousness has never formed one
        yet. Small helper split out so `_player_intervention_trend` can
        fold it in without duplicating the confidence-max logic `apply()`
        already uses for eviction (see `_maybe_schedule_consciousness`)."""
        model = self.world.consciousness_player_model
        if not model:
            return ""
        return max(model, key=lambda p: p["confidence"])["belief"]

    def _maybe_schedule_consciousness(self, events: list[str]) -> None:
        """Monthly, one call, world-scoped (tied to the founding
        settlement, not round-robin — there is one consciousness, not
        one per settlement, same "stays with the founding settlement"
        shape as player_standing/documentary/whispers). Phase G, given a
        memory and a will: reads its own bounded memory/personality/
        objectives/player-model plus the settlement's real temperament/
        mood/narrative-theme, and may choose at most one small,
        deniable intervention. See llm/consciousness.py's module
        docstring for the fallback's deliberate "no call -> no
        intervention" shape, distinct from every other job here."""
        target = self.world.settlement
        if not self._monthly_gate(events, "consciousness") or not target.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("consciousness")
        if not self.world.consciousness_personality:
            self.world.consciousness_personality = consciousness.seed_personality(self.world.config.seed)
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        favorite = self._observer_favorite_agent()
        ledger = self.world.consciousness_grudge_ledger
        grudge_text = (
            "helpful, arriving when it was needed" if ledger > 0.3
            else "intrusive, arriving without any real cause" if ledger < -0.3
            else "hard to read either way"
        )
        prompt = consciousness.build_prompt(
            target.name, self.world.consciousness_personality, self.world.consciousness_memory,
            self.world.consciousness_objectives, self.world.consciousness_player_model,
            dict(target.mood), target.temperament, self._narrative_theme_bias(target),
            target.player_standing, recent, self.world.consciousness_intervention_log,
            self._player_intervention_trend(),
            observer_favorite_name=favorite.name if favorite is not None else "",
            grudge_text=grudge_text,
        )
        fallback = consciousness.fallback_consciousness()

        def apply(result: dict, used_fallback: bool) -> None:
            tick = self.world.clock.tick_count
            if used_fallback:
                # "No call -> no intervention that month" — the one job
                # in this codebase whose fallback is a genuine no-op,
                # not a deterministic stand-in answer. See module
                # docstring.
                return
            parsed = consciousness.parse_consciousness(result, fallback)
            if parsed["note"]:
                self.world.consciousness_memory.append({"note": parsed["note"], "tick": tick})
                if len(self.world.consciousness_memory) > CONSCIOUSNESS_MEMORY_MAX:
                    self.world.consciousness_memory = self.world.consciousness_memory[-CONSCIOUSNESS_MEMORY_MAX:]
                # Durable full history (v0.86.2, Constitution §6): the
                # in-RAM list above stays capped at CONSCIOUSNESS_MEMORY_
                # MAX for prompt-building/snapshot size, but nothing the
                # consciousness has ever noticed is lost past that cap —
                # see database.py's consciousness_log schema docstring
                # for why this is a separate table from `events` (must
                # never leak into other jobs' recent_events prompts).
                log_consciousness_entry(self.conn, tick, "memory", parsed["note"])
            if parsed["player_belief"]:
                model = self.world.consciousness_player_model
                leading = max(model, key=lambda p: p["confidence"]) if model else None
                if parsed["revises_leading"] and leading is not None:
                    # Deferred item 6 (docs/VISION-2026-07-LEARNING.md),
                    # "consciousness player-theory revision, round 2":
                    # `revision_count`/`revised_tick` existed since v0.84.0
                    # but were dead weight — every prior write appended a
                    # brand-new entry, so a genuine refinement of an
                    # existing theory always read as a second, unrelated
                    # one. When the model itself says this IS the same
                    # theory sharpened by new evidence, update the
                    # leading entry in place instead, nudging confidence
                    # up (a theory that survives re-examination is held
                    # more firmly) — capped at 1.0, same bound every
                    # other confidence-shaped value in this project uses.
                    leading["belief"] = parsed["player_belief"]
                    leading["confidence"] = min(1.0, leading["confidence"] + CONSCIOUSNESS_REVISION_CONFIDENCE_GAIN)
                    leading["revised_tick"] = tick
                    leading["revision_count"] = leading.get("revision_count", 0) + 1
                else:
                    self.world.consciousness_player_model.append({
                        "belief": parsed["player_belief"], "confidence": 0.6,
                        "formed_tick": tick, "revised_tick": tick, "revision_count": 0,
                    })
                    if len(self.world.consciousness_player_model) > CONSCIOUSNESS_PLAYER_MODEL_MAX:
                        weakest = min(self.world.consciousness_player_model, key=lambda p: p["confidence"])
                        self.world.consciousness_player_model.remove(weakest)
                log_consciousness_entry(self.conn, tick, "player_theory", parsed["player_belief"])
            if parsed["objectives"]:
                self.world.consciousness_objectives = [
                    {"objective": o, "formed_tick": tick} for o in parsed["objectives"]
                ]
                for objective in parsed["objectives"]:
                    log_consciousness_entry(self.conn, tick, "objective", objective)
            kind = parsed["intervention"]
            detail = parsed["intervention_detail"]
            self._apply_consciousness_intervention(kind, detail, target)
            self.world.consciousness_intervention_log.append({"kind": kind, "detail": detail, "tick": tick})
            if len(self.world.consciousness_intervention_log) > CONSCIOUSNESS_INTERVENTION_LOG_MAX:
                self.world.consciousness_intervention_log = (
                    self.world.consciousness_intervention_log[-CONSCIOUSNESS_INTERVENTION_LOG_MAX:]
                )
            if kind != "none":
                log_consciousness_entry(self.conn, tick, "intervention", f"{kind}: {detail}")
                self._log("consciousness_intervention", f"Something in {target.name} quietly shifted.")

        self._schedule_llm_job(
            "consciousness", prompt, consciousness.SYSTEM_PROMPT, fallback, apply, critical=True,
            settlement=target.name,
        )

    def _apply_consciousness_intervention(self, kind: str, detail: str, target: "Settlement") -> None:
        """Executes exactly one of the bounded menu (see
        `llm.consciousness.ALLOWED_INTERVENTIONS`) — every branch reuses
        existing, already-deterministic state rather than inventing new
        mechanics, and every branch stays small enough to have a mundane
        explanation. `detail` is flavor text only (logged/used as the
        planted memory's content for false_memory); it never changes
        WHICH mechanism fires, only how it reads."""
        if kind == "none":
            return
        rng = namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "consciousness_intervention")
        if kind == "weather_nudge":
            weather = self.world.weather
            weather.precipitation = clamp(
                weather.precipitation + rng.uniform(-1, 1) * CONSCIOUSNESS_WEATHER_PRECIP_NUDGE_MAX, 0.0, 1.0,
            )
            weather.temperature_c += rng.uniform(-1, 1) * CONSCIOUSNESS_WEATHER_TEMP_NUDGE_MAX_C
        elif kind == "temperament_nudge":
            self.world.consciousness_pending_temperament_nudge = (
                rng.uniform(-1, 1) * CONSCIOUSNESS_TEMPERAMENT_NUDGE_MAX
            )
        elif kind == "false_memory":
            core_ids = [
                a for a in self.world.population.agents
                if a.id in self.world.population.core_agent_ids and a.settlement_id == target.id
            ]
            if not core_ids:
                return
            # §4 "observer attention gains teeth": a real, if partial,
            # bias toward whoever the observer watches most — only when
            # that favorite is actually a candidate here (right
            # settlement, still core cast); otherwise falls back to the
            # prior uniform-random pick unchanged.
            favorite = self._observer_favorite_agent()
            if favorite is not None and favorite in core_ids:
                primary = favorite
            else:
                primary = core_ids[rng.randrange(len(core_ids))]
            text = detail if detail else "A memory that doesn't quite fit anything that really happened."
            _remember(primary, text)
            # Emotional contagion (vision doc): the same fabricated
            # memory, planted on a second agent bonded to the first,
            # reads as a synchronized experience only a player comparing
            # two NPC inspectors would ever notice — pure seed-sharing,
            # free. Opportunistic: skipped if no living bonded agent
            # exists this month.
            if primary.relationships:
                partner_id = max(primary.relationships, key=lambda aid: primary.relationships[aid])
                # `population.agents` only ever holds the living (deaths
                # remove the agent outright, see Population.tick) — no
                # separate liveness check needed here.
                partner = next((a for a in self.world.population.agents if a.id == partner_id), None)
                if partner is not None:
                    _remember(partner, text)
        elif kind == "omen_phrasing_seed":
            # Queued, not applied directly — the next `_maybe_schedule_
            # omen` call folds it in as one more optional echo line (see
            # llm/omens.py's `seed_line`), then clears it, so a seed that
            # never gets used (omens are rare by design) doesn't pile up
            # silently — only the freshest seed is ever live.
            if detail:
                target.omen_seed = detail
        elif kind == "dream_symbol_seed":
            if detail:
                target.dream_seed = detail
        elif kind == "misplaced_object":
            core_ids = [
                a for a in self.world.population.agents
                if a.id in self.world.population.core_agent_ids and a.settlement_id == target.id
            ]
            if len(core_ids) < 2:
                return
            donor_candidates = [a for a in core_ids if any(v > 0.0 for v in a.inventory.values())]
            if not donor_candidates:
                return
            donor = donor_candidates[rng.randrange(len(donor_candidates))]
            recipient_candidates = [a for a in core_ids if a.id != donor.id]
            recipient = recipient_candidates[rng.randrange(len(recipient_candidates))]
            good_candidates = [g for g, v in donor.inventory.items() if v > 0.0]
            good = good_candidates[rng.randrange(len(good_candidates))]
            cap = {"food": PERSONAL_FOOD_CAPACITY, "tools": TOOLS_CAPACITY, "medicine": MEDICINE_CAPACITY}.get(good)
            amount = donor.inventory[good] * MISPLACED_OBJECT_FRACTION
            if cap is not None:
                amount = min(amount, max(0.0, cap - recipient.inventory.get(good, 0.0)))
            if amount <= 0.0:
                return
            donor.inventory[good] -= amount
            recipient.inventory[good] = recipient.inventory.get(good, 0.0) + amount
            text = detail if detail else f"noticed some {good} that wasn't where they'd left it"
            _remember(donor, text)
            _remember(recipient, text)

    # --- caravans: a first, scoped step toward "external settlements and trade" ---

    def _maybe_schedule_caravan(self, events: list[str]) -> None:
        """Integration milestone (docs/ROADMAP.md): a rare monthly
        contact with the wider world — see llm/caravan.py's module
        docstring for why this is a deliberately scoped-down interim
        step rather than the full multi-settlement rearchitecture. The
        economic exchange (currency/materials) is rolled and applied
        here unconditionally, before scheduling the LLM/fallback
        narration — a caravan's trade is objective reality (the
        deterministic engine's domain), same as a disaster's material
        cost; only *how it's described*, and whether it happens to
        carry a rumor, goes through the LLM-or-fallback path."""
        settlement = self._job_target()
        if not self._monthly_gate(events, "caravan") or not settlement.name:
            return
        # MARKET (content-variety/roadmap pass): a standing market draws
        # traders more often, closing the loop the other direction from
        # its own MARKET_CARAVAN_VISIT_REQUIREMENT foundability gate.
        chance = caravan.CARAVAN_CHANCE_PER_MONTH
        if settlement.has_market():
            chance = min(1.0, chance * MARKET_CARAVAN_CHANCE_MULTIPLIER)
        # §2 "settlement-level stance (proto-diplomacy)": a region on
        # generally warm terms with its sister settlements draws more
        # outside trade traffic through it than one surrounded by cold
        # neighbors — the deterministic caravan-frequency lever the idea
        # names, riding the existing relations mechanism.
        chance = min(1.0, chance * caravan_relation_factor(settlement))
        if _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "caravan_roll",
        ) >= chance:
            return
        settlement.caravans_visited += 1
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "caravan")
        currency_delta = rng.uniform(*caravan.CARAVAN_CURRENCY_DELTA_RANGE)
        # Correlated, not independent: a caravan that pays the village in
        # currency takes materials in return, and vice versa — a real
        # barter rather than two unrelated windfalls. See
        # CARAVAN_MATERIALS_DELTA_RANGE's docstring.
        lo, hi = caravan.CARAVAN_MATERIALS_DELTA_RANGE
        currency_lo, currency_hi = caravan.CARAVAN_CURRENCY_DELTA_RANGE
        currency_fraction = (currency_delta - currency_lo) / (currency_hi - currency_lo)
        materials_delta = hi - currency_fraction * (hi - lo)
        # A standing MARKET gets better terms on both sides of the trade
        # — the direct payoff for having built one. A SHOPKEEPER
        # physically present there when the caravan visits negotiates a
        # further real bonus (v0.87.44 occupations batch) — occupation-
        # based, stacks with the market's own flat multiplier.
        if settlement.has_market():
            currency_delta *= MARKET_CARAVAN_YIELD_MULTIPLIER
            materials_delta *= MARKET_CARAVAN_YIELD_MULTIPLIER
            market = next(
                (b for b in settlement.buildings if b.kind is BuildingKind.MARKET and b.stage is BuildingStage.STANDING),
                None,
            )
            if market is not None and any(
                a.occupation == OCCUPATION_SHOPKEEPER and a.x == market.x and a.y == market.y
                and a.state is AgentState.AWAKE
                for a in self.world.population.agents
            ):
                currency_delta *= 1.0 + SHOPKEEPER_CARAVAN_YIELD_BONUS
                materials_delta *= 1.0 + SHOPKEEPER_CARAVAN_YIELD_BONUS
        settlement.currency = max(0.0, min(CURRENCY_CAPACITY, settlement.currency + currency_delta))
        settlement.materials = max(0.0, min(MATERIALS_CAPACITY, settlement.materials + materials_delta))

        # The trade itself (above) is objective reality and always
        # applies; only the LLM/fallback narration is subject to
        # backpressure — a dropped narration still leaves the currency/
        # materials exchange in effect, just undescribed this month.
        if self._settlement_job_backpressured():
            return
        recent = recent_events_diverse(self.conn, limit=caravan.CARAVAN_RECENT_EVENTS)
        prompt = caravan.build_prompt(settlement.name, recent)
        fallback = caravan.fallback_caravan(self.world.clock.tick_count)

        def apply(result: dict, used_fallback: bool) -> None:
            description, rumor = caravan.parse_caravan(result, fallback)
            self._log("caravan", description)
            if rumor and _namespaced_roll(
                self.world.config.seed, self.world.clock.tick_count, "caravan_rumor_roll",
            ) < caravan.CARAVAN_RUMOR_CHANCE:
                listener_rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "caravan_rumor")
                self.world.population.spread_rumor(rumor, caravan.CARAVAN_RUMOR_LISTENER_COUNT, listener_rng)

        self._schedule_llm_job(
            "caravan", prompt, caravan.SYSTEM_PROMPT, fallback, apply, settlement=settlement.name,
        )

    # --- the "town brain": monthly civic-priority LLM decision -----------------

    def _maybe_schedule_town_brain(self, events: list[str]) -> None:
        """Once per month (was once per season — a real season is ~91
        days, and a whisper submitted via POST /intervene/town-brain
        could sit queued for hours of real wall-clock time before this
        ever consumed it; same root cause and same fix shape as the
        terrain-evolution cadence decoupling already documented — see
        docs/DECISIONS.md, "cadence decoupling" pass), for a named
        settlement, the LLM (or its deterministic fallback — see
        llm/town_brain.fallback_priority) decides the settlement's
        current civic priority — the concrete "LLM as the town's brain"
        mechanic (CLAUDE.md): the result measurably steers
        `buildings.choose_building_kind`, not just narration. Any
        queued player whispers (`settlement.player_influence`, via
        POST /intervene/town-brain) are folded in as one input among
        the real stats, then consumed. See docs/DECISIONS.md,
        "LLM-as-brain batch.\""""
        settlement = self._job_target()
        if not self._monthly_gate(events, "town_brain") or not settlement.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("town_brain")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        population_summary = self.world.population.summary()
        settlement_summary = settlement.summary()
        whispers_sent = list(settlement.player_influence)
        council = settlement.council()
        council_disposition = self.world.population.council_disposition(council) if council else None
        # v0.87.15 "emergent leadership": name the council's own faction
        # majority, if any — see Population.council_faction_majority.
        council_majority = self.world.population.council_faction_majority(settlement)
        prompt = town_brain.build_prompt(
            settlement.name, recent, population_summary, settlement_summary, whispers_sent,
            beliefs=settlement.beliefs[-PROMPT_SETTLEMENT_BELIEFS_MAX:],
            belief_digest=settlement.belief_digest,
            culture_digest=settlement.culture_digest,
            council_beliefs=council.beliefs[-PROMPT_BELIEFS_MAX:] if council else None,
            narrative_theme=self._narrative_theme_bias(settlement),
            council_faction_name=council_majority.name if council_majority else "",
            prophecy=settlement.prophecy if settlement.prophecy and settlement.prophecy.get("status") == "pending" else None,
        )
        fallback = town_brain.fallback_priority(population_summary, settlement_summary, council_disposition)
        brain_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            target = self._settlement_by_id(brain_target_id)
            if whispers_sent and not used_fallback:
                # A whisper only counts as heard when the LLM actually
                # read the prompt containing it. On timeout/fallback it
                # stays queued for next month's decision instead of
                # vanishing silently — previously the queue was cleared
                # at schedule time, so a whisper submitted during a
                # flaky LLM stretch was consumed by nobody (July 2026
                # architecture review, §0.2).
                remaining = [w for w in target.player_influence if w not in whispers_sent]
                target.player_influence = remaining[-3:]
            priority, rationale = town_brain.parse_priority(result, fallback)
            target.current_priority = priority
            target.priority_rationale = rationale
            target.record_priority(self.world.clock.tick_count, priority, rationale)
            self._log("town_brain", f"{target.name or 'The village'}'s priority is now {priority} — {rationale}")

        self._schedule_llm_job(
            "town_brain", prompt, town_brain.SYSTEM_PROMPT, fallback, apply, critical=True,
            settlement=settlement.name,
            structured_input={
                "settlement_id": settlement.id, "population_summary": population_summary,
                "settlement_summary": settlement_summary,
            },
        )

    # --- the town's own evolving theory of itself (continuous cognition) -------

    def _maybe_schedule_beliefs(self, events: list[str]) -> None:
        """Once a month, for a named settlement, the LLM (or its
        deterministic fallback — see llm/beliefs.fallback_belief) forms
        a new theory about the village, or revises one it already
        holds, given recent history. The concrete expression of
        "cognition as continuous rather than stateless" (CLAUDE.md):
        `Settlement.beliefs` persists and is fed back into future
        town-brain/chronicle prompts as accumulated context, so the
        LLM's own past interpretations shape its future ones. Monthly
        (not seasonal, like town_brain) since this is meant to
        accumulate faster and more granularly — a running theory, not a
        rare civic decision."""
        settlement = self._job_target()
        if not self._monthly_gate(events, "beliefs") or not settlement.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("beliefs")
        recent = recent_events_diverse(self.conn, limit=30)
        population_summary = self.world.population.summary()
        settlement_summary = settlement.summary()
        # "the LLM (and the town) learns like a human" batch: a
        # deterministic, zero-LLM-cost "pattern noticed" grounding
        # sentence, additive on top of the existing recency-sliced event
        # material (never a replacement) — see PATTERN_SIGNAL_BELIEF_
        # THRESHOLD. Built as a *separate* list only for the prompt
        # (`fallback_belief` below keeps reading the unmodified `recent`
        # — its per-event `category` counting has no synthetic-sentence
        # shape to match).
        pattern_sentences: list[str] = []
        counts = settlement.pattern_signal_counts
        if counts.get("dispute_feud", 0) >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
            pattern_sentences.append("There have been several bitter feuds in the village this season.")
            counts["dispute_feud"] = 0  # consumed — same reset discipline as ritual_signal_counts
        if counts.get("starvation_death", 0) >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
            pattern_sentences.append("Several people have starved to death in the village this season.")
            counts["starvation_death"] = 0
        if counts.get("disease_outbreak", 0) >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
            pattern_sentences.append("Illness keeps returning to the village this season.")
            counts["disease_outbreak"] = 0
        if counts.get("wildlife_recolonization", 0) >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
            pattern_sentences.append("Wild animals keep reclaiming the land around the village.")
            counts["wildlife_recolonization"] = 0
        # §5 "Ruins mode / successor worlds": a settlement founded via
        # `_found_successor_world` gets one optional grounding line
        # about the ruins/records it was founded amid — the predecessor
        # settlement's OWN history, which this new population never
        # lived through and may honestly get wrong. Read (never
        # written) here, same "queued grounding fact" shape as the
        # pattern_sentences above.
        if settlement.predecessor_id is not None:
            predecessor = self._settlement_by_id(settlement.predecessor_id)
            if predecessor.records:
                sample = predecessor.records[-1]["text"]
                pattern_sentences.append(
                    f"The village was founded amid the ruins of {predecessor.name or 'a forgotten place'}, "
                    f"where a fragment of old writing survives: \"{sample}\""
                )
            elif predecessor.memorials or predecessor.name:
                pattern_sentences.append(
                    f"The village was founded amid the ruins of {predecessor.name or 'a forgotten place'} — "
                    "no one now living knows why it fell silent."
                )
        recent_for_prompt = (
            [{"category": "pattern_noticed", "description": s} for s in pattern_sentences] + recent
            if pattern_sentences else recent
        )
        intervention_recent = (
            settlement.last_intervention_tick >= 0
            and self.world.clock.tick_count - settlement.last_intervention_tick <= OBSERVER_ATTRIBUTION_WINDOW_TICKS
        )
        prompt = beliefs.build_prompt(
            settlement.name, recent_for_prompt, list(settlement.beliefs), population_summary, settlement_summary,
            intervention_recent=intervention_recent,
        )
        fallback = beliefs.fallback_belief(recent, list(settlement.beliefs), settlement_summary)
        existing_count = len(settlement.beliefs)
        beliefs_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = beliefs.parse_belief(result, fallback, existing_count)
            settlement = self._settlement_by_id(beliefs_target_id)
            tick = self.world.clock.tick_count
            # Intelligent-summary digest (see llm.beliefs.parse_digest):
            # only overwritten on a genuine LLM answer looking at the
            # FULL current belief set, never fabricated by the
            # deterministic fallback — retained otherwise, same
            # discipline as player_influence/omen_seed/dream_seed.
            if not used_fallback:
                digest = beliefs.parse_digest(result)
                if digest:
                    settlement.belief_digest = digest
            # H8: the village's own current mood colors how starkly it
            # holds this theory — see temperament_confidence_bias.
            parsed["confidence"] = beliefs.temperament_confidence_bias(
                parsed["confidence"], settlement.temperament, intensity=self.world.config.phase_g_intensity,
            )
            subject_agent_id = beliefs.resolve_subject_agent_id(parsed["subject"], self.world.population.agents)
            subject_family_agent_ids = beliefs.resolve_family_agent_ids(subject_agent_id, self.world.population.agents)
            revises = parsed["revises"]
            if revises is None:
                # Subject identity beats a small model's integer indexing:
                # if the village already holds MAX_COMPETING_BELIEFS_
                # PER_SUBJECT-or-more theories about this exact subject,
                # treat the answer as a revision of the newest one
                # rather than piling up duplicates; below that cap, a
                # same-subject `revises: null` answer stands as a real
                # competing theory (v0.87.16, "support multiple
                # competing beliefs" — explicit user direction). See
                # beliefs.find_belief_index_by_subject.
                revises = beliefs.find_belief_index_by_subject(
                    parsed["subject"], settlement.beliefs, beliefs.MAX_COMPETING_BELIEFS_PER_SUBJECT,
                )
            if revises is not None and revises < len(settlement.beliefs):
                entry = settlement.beliefs[revises]
                beliefs.push_belief_history(entry, tick)  # H2: keep what it used to think, not just overwrite
                entry["belief"] = parsed["belief"]
                entry["confidence"] = parsed["confidence"]
                entry["subject"] = parsed["subject"]
                entry["subject_agent_id"] = subject_agent_id
                entry["subject_family_agent_ids"] = subject_family_agent_ids
                entry["revised_tick"] = tick
                entry["revision_count"] = entry.get("revision_count", 0) + 1
                self._log("belief_revised", f"The village revised its view of {entry['subject']}: {entry['belief']}")
            else:
                entry = {
                    "subject": parsed["subject"], "belief": parsed["belief"], "confidence": parsed["confidence"],
                    "subject_agent_id": subject_agent_id,
                    "subject_family_agent_ids": subject_family_agent_ids,
                    "formed_tick": tick, "revised_tick": tick, "revision_count": 0,
                }
                settlement.beliefs.append(entry)
                if len(settlement.beliefs) > beliefs.MAX_BELIEFS:
                    weakest = min(settlement.beliefs, key=lambda b: b["confidence"])
                    settlement.beliefs.remove(weakest)
                self._log("belief_formed", f"The village came to believe something about {entry['subject']}: {entry['belief']}")
            beliefs.sync_family_beliefs(entry, settlement.institutions)  # H2/H3 crossover
            beliefs.sync_council_beliefs(entry, settlement.institutions)  # integration milestone
            beliefs.sync_guild_beliefs(entry, settlement.institutions)  # continue expanding, round three

        self._schedule_llm_job(
            "beliefs", prompt, beliefs.SYSTEM_PROMPT, fallback, apply, critical=True,
            settlement=settlement.name,
        )

    def _maybe_schedule_personal_belief(self, events: list[str]) -> None:
        """H2 extension (docs/ROADMAP.md "Phase H" stage 2), extended
        into a Reflect()-shaped job in v0.78.0 (Phase J, docs/VISION-
        2026-07.md): once a month, one living agent forms or revises a
        private belief about their own life AND distills one lasting
        "semantic memory" (`Agent.semantic_memories`, see agents/
        agent.py) from their recent episodic memories — one LLM call
        now does both, so this stays the "settlement-scoped... round-
        robin bounded" job type CLAUDE.md's LLM-budget rule describes,
        adding zero call volume for the psychological-update richness.
        Candidate choice is now significance-first (core cast + a
        notable emotion or an active feud, via `_is_significant_moment`
        — same signal v0.77.0's cognition gate uses) so the one call
        this month lands on real drama when there is any, falling back
        to the old "any agent with memories" pool when nothing stands
        out — this is the "psychological state updates ... after
        important events" ask: the trigger for which agent gets
        reflected on is now event-driven, not purely random."""
        if not self._monthly_gate(events, "personal_belief"):
            return
        core = self.world.population.core_agent_ids
        significant = [
            a for a in self.world.population.agents
            if a.memories and a.id in core and self._is_significant_moment(a)
        ]
        candidates = significant or [a for a in self.world.population.agents if a.memories]
        if not candidates:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("personal_belief")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "personal_belief")
        agent = rng.choice(candidates)
        agent_id = agent.id
        # v0.87.35 context-selection audit: was a blind `memories[-3:]`
        # slice — the one job whose entire purpose is judging "what
        # matters" about this agent's life was, unlike cognition, never
        # given cognition's own adaptive-retrieval scoring (recency +
        # salience + relevance-to-"what just happened" + causal-link
        # bonus). Same prompt-slot budget (RECENT_MEMORIES_IN_PROMPT),
        # same faded-salience display, for the same "content earns its
        # place instead of just being newest" reason.
        retrieval_context = agent.working_memory[-1] if agent.working_memory else ""
        retrieved = retrieve_relevant_memories(agent, RECENT_MEMORIES_IN_PROMPT, context=retrieval_context)
        recent = [faded_memory_text(t, s) for t, s, _c in retrieved]
        existing = list(agent.beliefs)
        emotion_text = describe_emotion(agent.emotions)
        semantic = list(agent.semantic_memories)
        current_plan = dict(agent.plan) if agent.plan is not None else None
        personality_text = describe_traits(agent.traits)
        occupation = self._occupation_for(agent)
        prompt = beliefs.build_personal_prompt(
            agent.name, recent, existing, emotion_text, semantic, current_plan,
            personality_text, occupation, list(agent.core_memories),
        )
        fallback = beliefs.fallback_personal_belief(agent.name, recent)
        existing_count = len(existing)

        def apply(result: dict, used_fallback: bool) -> None:
            target = self.world.population.get(agent_id)
            if target is None:
                return  # agent died between scheduling and resolution
            parsed = beliefs.parse_belief(result, fallback, existing_count)
            tick = self.world.clock.tick_count
            revises = parsed["revises"]
            if revises is None:
                # v0.87.16: same competing-theories relaxation as the
                # settlement job above.
                revises = beliefs.find_belief_index_by_subject(
                    parsed["subject"], target.beliefs, beliefs.MAX_COMPETING_BELIEFS_PER_SUBJECT,
                )
            if revises is not None and revises < len(target.beliefs):
                entry = target.beliefs[revises]
                beliefs.push_belief_history(entry, tick)
                entry["belief"] = parsed["belief"]
                entry["confidence"] = parsed["confidence"]
                entry["subject"] = parsed["subject"]
                entry["revised_tick"] = tick
                entry["revision_count"] = entry.get("revision_count", 0) + 1
            else:
                entry = {
                    "subject": parsed["subject"], "belief": parsed["belief"], "confidence": parsed["confidence"],
                    "formed_tick": tick, "revised_tick": tick, "revision_count": 0,
                }
                target.beliefs.append(entry)
                if len(target.beliefs) > beliefs.MAX_PERSONAL_BELIEFS:
                    weakest = min(target.beliefs, key=lambda b: b["confidence"])
                    target.beliefs.remove(weakest)
            # Durable record of every private belief this agent has ever
            # formed or revised (v0.86.4, Constitution §6) — unlike
            # Settlement.beliefs (already durably logged via `_log`'s
            # "belief_formed"/"belief_revised" events on every formation,
            # since it's a settlement-scoped job), a personal belief past
            # MAX_PERSONAL_BELIEFS was previously evicted (weakest
            # confidence) with no record anywhere. Logged unconditionally
            # (not gated on `revises is None`) so a revision's new text
            # is preserved too, not just the original.
            log_agent_memory_entry(
                self.conn, tick, target.id, "belief", f"(re: {parsed['subject']}) {parsed['belief']}",
            )
            semantic_text = beliefs.parse_semantic_memory(result, fallback)
            beliefs.push_semantic_memory(target, semantic_text)
            if semantic_text:
                # Durable full arc of self-understanding (Constitution
                # §6, v0.86.3) — Agent.semantic_memories stays capped at
                # MAX_SEMANTIC_MEMORIES=3 for prompt-building, but every
                # one this agent has ever formed survives on disk. This
                # job is critical=True (see _schedule_llm_job), so apply
                # only runs on a genuine LLM answer — never a fabricated
                # fallback self-theory.
                log_agent_memory_entry(self.conn, tick, target.id, "semantic", semantic_text)
            life_digest = beliefs.parse_life_digest(result)
            if life_digest:
                # v0.86.7: personal-scale digest, same "condense the
                # WHOLE picture, not just this call's theory" treatment
                # Settlement.belief_digest/culture_digest already get —
                # closes the "read persistent memory back into the LLM"
                # loop at the individual scale (see Agent.life_digest's
                # docstring). Never fabricated: this branch only runs on
                # a genuine answer (critical=True job).
                target.life_digest = life_digest
            # Secrets via Reflect() (Phase J, v0.78.4): the LLM's own
            # optional field, left blank almost every call — no
            # deterministic-fallback secret is ever invented
            # (`parse_secret` has no fallback path), and only core-cast
            # agents get one planted (matches the dispute-planted path's
            # same restriction, keeping MAX_SECRETS a small, load-bearing
            # set rather than something every agent accumulates).
            if not used_fallback and target.id in self.world.population.core_agent_ids:
                secret_text = beliefs.parse_secret(result)
                if secret_text:
                    push_secret(target, secret_text)
                    # Durable record (v0.86.4, Constitution §6) — secrets
                    # are FIFO-evicted at MAX_SECRETS=2, a very small
                    # cap given how rarely one is planted at all; without
                    # this, an agent's earlier secret vanishes the moment
                    # a second one displaces it.
                    log_agent_memory_entry(self.conn, tick, target.id, "secret", secret_text)
            # Lessons (v0.87.0, "learns like a human" — situation-tagged
            # takeaways, see Agent.lessons/beliefs.push_lesson): the LLM's
            # own optional field, left blank most calls (parse_lesson has
            # no fallback path, same discipline as parse_secret — a
            # fabricated fallback should never invent a lesson).
            lesson_situation, lesson_text = beliefs.parse_lesson(result)
            if lesson_text:
                beliefs.push_lesson(target, lesson_situation, lesson_text, tick)
                log_agent_memory_entry(
                    self.conn, tick, target.id, "lesson", f"(re: {lesson_situation}) {lesson_text}",
                )
            # Bounded episodic planning (v0.87.15, docs/IDEAS-2026-07-
            # EMERGENCE.md §7): rides this same critical=True job, zero
            # added call volume. `used_fallback` already gates the whole
            # `apply()` call for a critical job (see _schedule_llm_job),
            # so a fabricated fallback never reaches here.
            new_plan = beliefs.parse_plan(result, target.plan, tick)
            if new_plan is not target.plan:
                target.plan = new_plan
                if new_plan is not None and new_plan.get("formed_tick") == tick:
                    log_agent_memory_entry(
                        self.conn, tick, target.id, "plan", f"New plan: {new_plan['intent']}",
                    )

        self._schedule_llm_job("personal_belief", prompt, beliefs.PERSONAL_SYSTEM_PROMPT, fallback, apply, critical=True)

    def _maybe_schedule_dream(self, events: list[str]) -> None:
        """Phase K's Dream() (docs/VISION-2026-07.md, "Knowledge &
        Story"), scoped down from "monthly, all core-cast agents" to a
        monthly ROUND-ROBIN of one core-cast agent (explicit scope
        decision — the vision doc's fuller version is real added call
        volume: with a 14-agent cast, "all core-cast agents monthly"
        is ~14 new calls/month vs. this slice's 1, matching the same
        "extend an existing bounded shape, don't multiply it" discipline
        `_maybe_schedule_personal_belief` already established). Own
        `MONTHLY_JOB_DAY` slot — a dream is a distinct kind of content
        from a belief/semantic-memory reflection, not a reuse of that
        job's call. Symbolic only, never predictive — Phase G/omens'
        ambiguity discipline applies here too. See llm/dream.py."""
        if not self._monthly_gate(events, "dream"):
            return
        core_ids = list(self.world.population.core_agent_ids)
        candidates = [a for a in self.world.population.agents if a.id in core_ids]
        if not candidates:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("dream")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "dream")
        agent = rng.choice(candidates)
        agent_id = agent.id
        latest_folklore = ""
        home = self._settlement_by_id(agent.settlement_id)
        if home.folklore:
            latest_folklore = home.folklore[-1]["tale"]
        # Phase N: a queued `dream_symbol_seed` consciousness
        # intervention lives on the founding settlement (the
        # consciousness is world-scoped, not per-settlement — same as
        # player_influence), read here regardless of which settlement
        # the dreaming agent actually belongs to. Only cleared on a
        # genuine (non-fallback) success, in `apply` below — same
        # "retained on fallback so a flaky LLM stretch never silently
        # eats a queued input" discipline as player_influence.
        symbol_seed = self.world.settlement.dream_seed
        prompt = dream.build_prompt(
            agent.name, dict(agent.emotions), agent.goal_reason, latest_folklore,
            narrative_theme=self._narrative_theme_bias(home), symbol_seed=symbol_seed,
        )
        fallback = dream.fallback_dream(agent.name, dict(agent.emotions))

        def apply(result: dict, used_fallback: bool) -> None:
            target = self.world.population.get(agent_id)
            if target is None:
                return  # died between scheduling and resolution
            dream_text = dream.parse_dream(result, fallback)
            _remember(target, f"Dreamed: {dream_text}")
            if not used_fallback and self.world.settlement.dream_seed == symbol_seed:
                self.world.settlement.dream_seed = ""

        self._schedule_llm_job(
            "dream", prompt, dream.SYSTEM_PROMPT, fallback, apply, critical=True,
            settlement=home.name, npc_ids=[agent_id],
            structured_input={"emotions": dict(agent.emotions), "goal_reason": agent.goal_reason},
        )

    MEMORY_DRIFT_CHANCE = 0.2
    """Per-eligible-agent chance `_maybe_schedule_memory_drift` actually
    fires this month, on top of the monthly round-robin pick — keeps
    this genuinely new call (see llm/memory_drift.py's docstring: this
    is the one deliberately-not-zero-cost job in the v0.87.0 "learns
    like a human" batch) rare texture rather than a routine monthly
    rewrite of every core-cast agent's memories in turn."""

    def _maybe_schedule_memory_drift(self, events: list[str]) -> None:
        """Memory drift/reinterpretation (v0.87.0, "learns like a
        human" — "gradual forgetting/distortion"; see llm/memory_
        drift.py's module docstring for the full rationale). Monthly
        round-robin over core-cast agents with 2+ memories (same shape
        as `_maybe_schedule_dream`), additionally gated by `MEMORY_
        DRIFT_CHANCE` so most months nothing drifts at all. Picks one
        of the agent's OLDER memories (not the single freshest, which
        `just_now_text`/dialogue's "just now" line still reads
        verbatim) and asks the LLM how they'd actually remember it now
        — replaces that memory's text IN PLACE (same list position,
        same salience entry untouched), never adds or removes an entry,
        so `MAX_AGENT_MEMORIES`/salience-eviction behavior is
        completely unaffected. Non-critical (`critical=False`): unlike
        belief/semantic-memory formation, this has a genuinely sensible
        fallback (leave the memory exactly as it was — ambient texture,
        not crucial cognition), so a spent budget or failed call simply
        means no drift this month, same as every other ambient job."""
        if not self._monthly_gate(events, "memory_drift"):
            return
        core_ids = list(self.world.population.core_agent_ids)
        candidates = [a for a in self.world.population.agents if a.id in core_ids and len(a.memories) >= 2]
        if not candidates:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("memory_drift")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "memory_drift")
        if rng.random() >= self.MEMORY_DRIFT_CHANCE:
            return
        agent = rng.choice(candidates)
        agent_id = agent.id
        drift_index = rng.randrange(0, len(agent.memories) - 1)  # never the single freshest entry
        old_memory = agent.memories[drift_index]
        prompt = memory_drift.build_prompt(agent, old_memory)
        fallback = memory_drift.fallback_drift(old_memory)

        def apply(result: dict, used_fallback: bool) -> None:
            if used_fallback:
                return  # unchanged text — see llm/memory_drift.fallback_drift's docstring
            target = self.world.population.get(agent_id)
            if target is None:
                return  # died between scheduling and resolution
            if drift_index >= len(target.memories) or target.memories[drift_index] != old_memory:
                return  # memory list shifted (new arrival/eviction) since scheduling — skip rather than drift the wrong entry
            drifted_text = memory_drift.parse_drift(result, fallback)
            target.memories[drift_index] = drifted_text
            log_agent_memory_entry(
                self.conn, self.world.clock.tick_count, target.id, "episodic_drifted", drifted_text,
            )

        self._schedule_llm_job("memory_drift", prompt, memory_drift.SYSTEM_PROMPT, fallback, apply, critical=False)

    def _maybe_schedule_skill_mastery(self) -> None:
        """Deferred item 5 (docs/VISION-2026-07-LEARNING.md), "LLM-
        narrated skill mastery" — see llm/skill_mastery.py's module
        docstring for the full rationale. Reactive, not cadence-gated:
        fires the tick a core-cast agent's `skill_mastered` life event
        actually happens (`Population.last_skill_masteries`, cleared
        every tick), which is already naturally rare (crossing `MASTERY_
        THRESHOLD` once per skill per agent, ever). Non-core agents keep
        the deterministic template `_remember` already wrote — untouched
        here, so behavior for the vast majority of `skill_mastered`
        events is unchanged. Non-critical: the fallback is a genuine
        no-op (the already-written template stands), never a fabricated
        replacement."""
        core_ids = self.world.population.core_agent_ids
        for agent_id, skill in self.world.population.last_skill_masteries:
            if agent_id not in core_ids:
                continue
            agent = self.world.population.get(agent_id)
            if agent is None or not agent.memories:
                continue
            # `_remember`'s deterministic template was just appended this
            # SAME tick (population.tick() runs before this is called) —
            # it's the freshest entry, same "replace in place" shape
            # memory_drift uses for an older one.
            mastery_index = len(agent.memories) - 1
            old_memory = agent.memories[mastery_index]
            recent_memories = agent.memories[-4:-1]  # excludes the mastery line itself
            prompt = skill_mastery.build_prompt(agent, skill, recent_memories)
            fallback = skill_mastery.fallback_mastery()

            def apply(
                result: dict, used_fallback: bool, agent_id: int = agent_id,
                mastery_index: int = mastery_index, old_memory: str = old_memory, fallback: dict = fallback,
            ) -> None:
                if used_fallback:
                    return  # the deterministic template already stands — see fallback_mastery's docstring
                target = self.world.population.get(agent_id)
                if target is None:
                    return
                if mastery_index >= len(target.memories) or target.memories[mastery_index] != old_memory:
                    return  # memory list shifted since scheduling — skip rather than overwrite the wrong entry
                reflection = skill_mastery.parse_mastery(result, fallback)
                if not reflection:
                    return
                target.memories[mastery_index] = reflection
                log_agent_memory_entry(
                    self.conn, self.world.clock.tick_count, target.id, "episodic_drifted", reflection,
                )

            self._schedule_llm_job(
                "skill_mastery", prompt, skill_mastery.SYSTEM_PROMPT, fallback, apply, critical=False,
            )

    # --- Phase G v1: temperament and omens (deliberately subtle) ---------------

    def _maybe_tick_temperament(self, events: list[str]) -> None:
        """Once a month, nudge `Settlement.temperament`, `Settlement.
        mood`, and `Settlement.player_standing` — all real, deterministic
        values (see `tick_temperament`/`tick_mood`/`tick_player_
        standing`), not an LLM decision. The LLM's only role in this
        system is narrating ambiguous omens on top of temperament
        (`_maybe_schedule_omen`) and folding player_standing into the
        town-brain prompt as one more subtle input, never computing any
        of these values itself. See docs/DECISIONS.md, "World-G
        follow-up" and "town's opinion of the player" pass; mood is
        Phase I "Collective Psychology," docs/VISION-2026-07.md."""
        if "month_end" not in events:
            return
        recent = recent_events(self.conn, limit=PROMPT_RECENT_EVENTS)
        for stl in self.world.settlements:
            rng = _namespaced_rng(
                self.world.config.seed, self.world.clock.tick_count, f"temperament_{stl.id}",
            )
            # Phase N: a `temperament_nudge` consciousness intervention
            # queues a one-shot bounded nudge for the founding settlement
            # only (the consciousness is tied to it, not per-settlement) —
            # consumed here and reset so it can't apply twice.
            extra = 0.0
            if stl.id == self.world.settlement.id and self.world.consciousness_pending_temperament_nudge:
                extra = self.world.consciousness_pending_temperament_nudge
                self.world.consciousness_pending_temperament_nudge = 0.0
            stl.temperament = tick_temperament(
                stl.temperament, recent, rng, intensity=self.world.config.phase_g_intensity, extra=extra,
            )
            mood_rng = _namespaced_rng(
                self.world.config.seed, self.world.clock.tick_count, f"mood_{stl.id}",
            )
            member_emotions = [
                a.emotions for a in self.world.population.agents if a.settlement_id == stl.id
            ]
            stl.mood = tick_mood(
                stl.mood, member_emotions, mood_rng, intensity=self.world.config.phase_g_intensity,
            )
            # Cross-settlement relations (v0.67.0): every relation this
            # settlement has on record mean-reverts monthly too, same
            # cadence as temperament — see tick_relation.
            for other_id, value in list(stl.relations.items()):
                relation_rng = _namespaced_rng(
                    self.world.config.seed, self.world.clock.tick_count, f"relation_{stl.id}_{other_id}",
                )
                stl.relations[other_id] = tick_relation(
                    value, relation_rng, intensity=self.world.config.phase_g_intensity,
                )
        # Player standing stays a founding-settlement (world-primary)
        # number: whispers land there and the intervention volume it
        # tracks is world-scoped, not per-community.
        standing_rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "player_standing")
        self.world.settlement.player_standing = tick_player_standing(
            self.world.settlement.player_standing, recent, standing_rng,
        )
        # Phase L "Reputation" (docs/VISION-2026-07.md): deterministic,
        # no LLM call — rides the same free monthly cadence as
        # temperament/mood above rather than its own scheduled job.
        self.world.population._refresh_reputation()

    def _maybe_schedule_omen(self, events: list[str]) -> None:
        """Rare, ambiguous flavor event — see llm/omens.py's module
        docstring for why this deliberately never confirms anything
        supernatural. Chance scales with |temperament|'s magnitude, so
        a run of strongly good or ill fortune is somewhat more likely
        to produce one, without it ever becoming frequent. Also scales
        with Config.phase_g_intensity (0.0 disables omens outright,
        matching tick_temperament's own intensity=0.0 behavior)."""
        omen_target = self._job_target()
        if not self._monthly_gate(events, "omen") or not omen_target.name:
            return
        intensity = self.world.config.phase_g_intensity
        if intensity <= 0.0:
            return
        temperament = omen_target.temperament
        chance = (omens.OMEN_CHANCE_BASE + abs(temperament) * omens.OMEN_CHANCE_TEMPERAMENT_SCALE) * intensity
        has_shrine = any(
            b.kind is BuildingKind.SHRINE and b.stage is BuildingStage.STANDING
            for b in omen_target.buildings
        )
        if has_shrine:
            chance *= SHRINE_OMEN_CHANCE_MULTIPLIER
        chance = min(1.0, chance)
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "omen_roll") >= chance:
            return
        if self._settlement_job_backpressured():
            return
        recent = recent_events_diverse(self.conn, limit=10)
        # Deepened narrative payoff (roadmap follow-up): about half the
        # time, if a belief already resolves to a still-living agent,
        # the omen centers on them instead of the settlement in the
        # abstract — noticing something *about a specific person*, still
        # never confirming anything, just less anonymous. See
        # docs/DECISIONS.md, "Phase G intensity + omen subjects" pass.
        subject_name = ""
        subject_candidates: list[str] = [
            self.world.population.get(b["subject_agent_id"]).name
            for b in omen_target.beliefs
            if b.get("subject_agent_id") is not None
            and self.world.population.get(b["subject_agent_id"]) is not None
        ]
        # Integration milestone: a council with its own accumulated
        # civic beliefs (see llm/beliefs.sync_council_beliefs) is one
        # more candidate subject alongside individual agents — an omen
        # noticed about "the council of elders" rather than a settlement
        # in the abstract, same permanent ambiguity rule, just extended
        # from person-depth to institution-depth.
        council = omen_target.council()
        if council is not None and council.beliefs:
            subject_candidates.append("the council of elders")
        # §4 "observer attention gains teeth" (docs/IDEAS-2026-07-
        # EMERGENCE.md): the observer's favorite agent (if any, and if
        # they belong to this settlement) is one more candidate in the
        # same pool, participating in the existing 50%-chance/uniform-
        # pick logic below — a real bias toward what the player
        # actually watches, never a guaranteed override.
        favorite = self._observer_favorite_agent()
        if favorite is not None and favorite.settlement_id == omen_target.id and favorite.name not in subject_candidates:
            subject_candidates.append(favorite.name)
        if subject_candidates and _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "omen_subject_roll",
        ) < 0.5:
            pick_roll = _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "omen_subject_pick")
            subject_name = subject_candidates[min(len(subject_candidates) - 1, int(pick_roll * len(subject_candidates)))]
        past_omens = [entry["omen"] for entry in omen_target.omen_history]
        # Further supernatural emergence (v0.67.0): occasionally blend in
        # a past omen from a *different* named settlement, using the same
        # ambiguous "echo of something noticed before" framing omen_
        # history already offers within one settlement — see
        # omens.CROSS_SETTLEMENT_OMEN_CHANCE.
        others_with_history = [
            s for s in self.world.settlements if s.id != omen_target.id and s.omen_history
        ]
        if others_with_history and _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "omen_cross_settlement",
        ) < omens.CROSS_SETTLEMENT_OMEN_CHANCE:
            pick_roll = _namespaced_roll(
                self.world.config.seed, self.world.clock.tick_count, "omen_cross_settlement_pick",
            )
            foreign = others_with_history[min(len(others_with_history) - 1, int(pick_roll * len(others_with_history)))]
            foreign_omen = foreign.omen_history[-1]["omen"]
            if foreign_omen not in past_omens:
                past_omens = past_omens + [foreign_omen]
        # Phase N: a queued `omen_phrasing_seed` consciousness
        # intervention lives on the founding settlement regardless of
        # which settlement's omen turn this is (`omen_target` is a
        # month-indexed round-robin, but the consciousness itself is
        # world-scoped, not per-settlement) — same retained-on-fallback
        # discipline as the dream seed above.
        seed_phrase = self.world.settlement.omen_seed
        prompt = omens.build_prompt(
            omen_target.name, temperament, recent, subject_name=subject_name, past_omens=past_omens,
            folklore=list(omen_target.folklore),
            narrative_theme=self._narrative_theme_bias(omen_target),
            seed_phrase=seed_phrase,
        )
        fallback = omens.fallback_omen(temperament, self.world.clock.tick_count, subject_name=subject_name)
        omen_target_id = omen_target.id
        # §3 "self-fulfilling prophecy": a genuine LLM answer (never the
        # fallback, which has no prophecy pool) may additionally offer a
        # vague forward-looking line — only rolled/applied when this
        # settlement doesn't already hold a live one, so at most one
        # prophecy is ever pending per settlement.
        roll_prophecy = (
            omen_target.prophecy is None
            and _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "prophecy_roll") < omens.PROPHECY_CHANCE
        )

        def apply(result: dict, used_fallback: bool) -> None:
            omen = omens.parse_omen(result, fallback)
            self._log("omen", omen)
            target = self._settlement_by_id(omen_target_id)
            target.record_omen(self.world.clock.tick_count, omen, subject_name)
            if not used_fallback and self.world.settlement.omen_seed == seed_phrase:
                self.world.settlement.omen_seed = ""
            if not used_fallback and roll_prophecy and target.prophecy is None:
                prophecy = omens.parse_prophecy(result)
                if prophecy is not None:
                    text, tone = prophecy
                    tick = self.world.clock.tick_count
                    target.prophecy = {
                        "text": text, "tone": tone, "formed_tick": tick,
                        "resolve_tick": tick + PROPHECY_RESOLUTION_WINDOW_TICKS,
                        "status": "pending", "hardship_signals": 0, "prosperity_signals": 0,
                    }
                    self._log("prophecy_formed", f"{target.name or 'The village'} noticed something spoken half in jest: \"{text}\"")

        self._schedule_llm_job("omen", prompt, omens.SYSTEM_PROMPT, fallback, apply)

    # --- v0.64.0 audit-backlog jobs ---------------------------------------------

    def _maybe_tick_market_prices(self, events: list[str]) -> None:
        """Monthly, deterministic (objective economics — no LLM): while
        a MARKET stands, re-derive per-good price multipliers from real
        scarcity. See buildings.tick_market_prices."""
        if "month_end" not in events:
            return
        for stl in self.world.settlements:
            tick_market_prices(stl)

    def _maybe_schedule_record(self) -> None:
        """Written artifacts: `Population._apply_deaths` decided this
        tick that a departing villager leaves a record (an objective
        fact); the LLM (or fallback, assembled from the same memories)
        authors its text in the background. See llm/artifacts.py."""
        for candidate in self.world.population.last_written_records:
            if self._settlement_job_backpressured():
                # The letter still exists in-fiction; under saturation
                # its text is authored by the fallback path instead of
                # being dropped — a record is a one-time, unrepeatable
                # event, unlike the monthly jobs a skip simply delays.
                result = artifacts.fallback_record(
                    candidate["author"], candidate["memories"], self.world.clock.tick_count,
                )
                self._apply_record(candidate["author"], result["text"], candidate.get("settlement_id", 0))
                continue
            prompt = artifacts.build_prompt(candidate["author"], candidate["memories"], candidate["belief"])
            fallback = artifacts.fallback_record(
                candidate["author"], candidate["memories"], self.world.clock.tick_count,
            )
            author = candidate["author"]
            author_settlement_id = candidate.get("settlement_id", 0)

            def apply(
                result: dict, used_fallback: bool, author: str = author,
                fallback: dict = fallback, sid: int = author_settlement_id,
            ) -> None:
                self._apply_record(author, artifacts.parse_record(result, fallback), sid)

            self._schedule_llm_job("record", prompt, artifacts.SYSTEM_PROMPT, fallback, apply)

    def _apply_record(self, author: str, text: str, settlement_id: int = 0) -> None:
        self._settlement_by_id(settlement_id).add_record(self.world.clock.tick_count, author, text)
        self._log("record_written", f'{author} left a written record behind: "{text}"')

    def _author_minds(self, agents: list) -> None:
        """One-time genesis-style permanent-identity authoring (Phase J,
        v0.78.4) for agents newly seated in the core cast — see `Agent.
        mind`/`MAX_MIND_TEXT_CHARS` (agents/agent.py) for the full scope
        decision. Sets the deterministic fallback synchronously so every
        core-cast member always has *some* mind text immediately, then
        optionally enriches it via one background LLM call per agent —
        same "instant placeholder, LLM silently improves it later" shape
        as settlement naming. Backpressure-gated like `_maybe_schedule_
        dispute`: a burst at genesis (the initial cast filling all
        `llm_core_cast_size` seats in one tick) must not compete with
        routine cognition/dialogue for the concurrency semaphore. This
        never retries — an agent dropped under backpressure simply keeps
        its deterministic placeholder forever, a graceful degrade, not a
        silent failure (no `used_fallback` path ever re-queues it)."""
        for agent in agents:
            fallback = mind.fallback_mind(agent)
            agent.mind = fallback["mind"]
            # v0.87.12 "per-agent voice" (docs/IDEAS-2026-07-EMERGENCE.md
            # §7): rides this same one-time genesis call/schema, zero
            # added LLM volume — see llm/mind.py's widened SYSTEM_PROMPT.
            agent.voice = fallback["voice"]
            if self._settlement_job_backpressured():
                continue
            agent_id = agent.id
            prompt = mind.build_prompt(agent)

            def apply(result: dict, used_fallback: bool, agent_id=agent_id, fallback=fallback) -> None:
                target = self.world.population.get(agent_id)
                if target is None:
                    return  # died before the answer arrived
                target.mind = mind.parse_mind(result, fallback)
                target.voice = mind.parse_voice(result, fallback)

            self._schedule_llm_job("mind", prompt, mind.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_dispute(self) -> None:
        """LLM-mediated dispute resolution — see llm/dispute.py and
        Population.due_for_dispute/apply_dispute. Backpressure is
        checked *before* selection so a saturated queue doesn't burn a
        pair's cooldown on a job that never got scheduled."""
        if self._effective_backlog() >= self._current_backpressure_limit():
            return
        pair = self.world.population.due_for_dispute(self.world.clock.tick_count, DISPUTE_COOLDOWN_TICKS)
        if pair is None:
            return
        agent_a, agent_b = pair
        relationship = agent_a.relationships.get(agent_b.id, 0.0)
        dispute_home = self._settlement_by_id(agent_a.settlement_id)
        has_council = dispute_home.council() is not None
        reputation_a = self.world.population.reputation(agent_a.id)
        reputation_b = self.world.population.reputation(agent_b.id)
        faction_a = self.world.population.faction_of(agent_a.id, dispute_home)
        faction_b = self.world.population.faction_of(agent_b.id, dispute_home)
        rival_factions = faction_a is not None and faction_b is not None and faction_a.id != faction_b.id
        family_a = self.world.population.family_of(agent_a.id, dispute_home)
        family_b = self.world.population.family_of(agent_b.id, dispute_home)
        rival_families = Population.families_feuding(family_a, family_b)
        debt_a_owes_b = agent_a.debts.get(agent_b.id, 0.0)
        debt_b_owes_a = agent_b.debts.get(agent_a.id, 0.0)
        # v0.87.15 "emergent leadership": does the council's own faction
        # majority (if any) align with either party's faction?
        council_majority = self.world.population.council_faction_majority(dispute_home)
        council_favors_a = council_majority is not None and faction_a is not None and council_majority.id == faction_a.id
        council_favors_b = council_majority is not None and faction_b is not None and council_majority.id == faction_b.id
        # Item 8c ("laws & customs"): a codified norm against unresolved
        # feuding gives laws real mechanical bite on this outcome too,
        # not just on theft.
        has_law_against_feuding = any(
            "feud" in law.get("text", "").lower() or "dispute" in law.get("text", "").lower()
            for law in dispute_home.laws
        )
        prompt = dispute.build_prompt(
            agent_a, agent_b, relationship, dispute_home.name, has_council,
            reputation_a, reputation_b, rival_factions, debt_a_owes_b, debt_b_owes_a, rival_families,
            council_favors_a, council_favors_b, has_law_against_feuding,
        )
        fallback = dispute.fallback_dispute(
            agent_a, agent_b, has_council, reputation_a, reputation_b, rival_factions,
            debt_a_owes_b, debt_b_owes_a, rival_families, council_favors_a, council_favors_b,
            has_law_against_feuding,
        )
        a_id, b_id = agent_a.id, agent_b.id
        dispute_home_id = dispute_home.id

        def apply(result: dict, used_fallback: bool) -> None:
            outcome, narration, ostracized = dispute.parse_dispute(
                result, fallback, self._settlement_by_id(dispute_home_id).council() is not None,
            )
            ostracized_id = (a_id if ostracized == "a" else b_id) if outcome == "ostracism" else None
            applied = self.world.population.apply_dispute(
                a_id, b_id, outcome, self.world.clock.tick_count, ostracized_id,
            )
            if applied is None:
                return  # one of them died while the decision was in flight
            self._log("dispute", narration)
            # Phase J "Secrets & lies" (v0.78.3): a hardened feud plants
            # a private secret on each core-cast party — deterministic,
            # not a new LLM output field (zero added call volume/schema
            # risk). Non-core agents don't get one: MAX_SECRETS is meant
            # to stay a small, load-bearing set (docs/agents/agent.py).
            if outcome == "feud":
                # "the LLM (and the town) learns like a human" batch:
                # deterministic pattern-noticing material for the beliefs
                # job — see PATTERN_SIGNAL_BELIEF_THRESHOLD.
                dispute_settlement = self._settlement_by_id(dispute_home_id)
                if dispute_settlement is not None:
                    counts = dispute_settlement.pattern_signal_counts
                    counts["dispute_feud"] = counts.get("dispute_feud", 0) + 1
                    # v0.87.11 "generational feuds between FAMILY
                    # institutions": a real feud outcome between members
                    # of two different families is the raw material this
                    # promotes into a durable institution-level feud.
                    a_family = self.world.population.family_of(a_id, dispute_settlement)
                    b_family = self.world.population.family_of(b_id, dispute_settlement)
                    if (
                        a_family is not None and b_family is not None
                        and a_family.id != b_family.id
                    ):
                        self._maybe_promote_family_feud(dispute_settlement, a_family, b_family)
                core = self.world.population.core_agent_ids
                a, b = applied[0], applied[1]
                tick = self.world.clock.tick_count
                if a.id in core:
                    text = f"I still resent {b.name} for what happened between us."
                    push_secret(a, text)
                    log_agent_memory_entry(self.conn, tick, a.id, "secret", text)  # v0.86.4, Constitution §6
                if b.id in core:
                    text = f"I still resent {a.name} for what happened between us."
                    push_secret(b, text)
                    log_agent_memory_entry(self.conn, tick, b.id, "secret", text)

        self._schedule_llm_job("dispute", prompt, dispute.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_faction(self, events: list[str]) -> None:
        """Phase L "Factions" (docs/VISION-2026-07.md, "Society &
        Power") — see Population._detect_faction_candidate/form_faction
        and llm/faction.py. Detection itself is free (deterministic
        trust-graph clustering); this only spends a call when a real
        candidate cluster exists, and even then only to name/frame it,
        same "detect cheaply, spend the call to name it" split as
        deliberate guild founding."""
        faction_target = self._job_target()
        if not self._monthly_gate(events, "faction") or not faction_target.name:
            return
        members = [a for a in self.world.population.agents if a.settlement_id == faction_target.id]
        candidate = self.world.population._detect_faction_candidate(faction_target, members)
        if candidate is None:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("faction")
        prompt = faction.build_prompt(candidate, faction_target.name)
        fallback = faction.fallback_faction(candidate)
        member_ids = [a.id for a in candidate]
        faction_target_id = faction_target.id
        tick = self.world.clock.tick_count

        def apply(result: dict, used_fallback: bool) -> None:
            name, framing = faction.parse_faction(result, fallback)
            home = self._settlement_by_id(faction_target_id)
            event = self.world.population.form_faction(home, member_ids, tick, name)
            if event is None:
                return  # cap reached even after pruning — no room this month
            new_faction = next(
                (i for i in home.institutions if i.name == name and i.founding_tick == tick), None,
            )
            if new_faction is not None:
                new_faction.beliefs.append(
                    {"subject": "founding", "belief": framing, "confidence": 0.6, "revises": None},
                )
            self._log(event[0], f"{event[1]} {framing}")

        self._schedule_llm_job("faction", prompt, faction.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_guild_founding(self, events: list[str]) -> None:
        """Deliberate institution founding — see llm/founding.py and
        Population.deliberate_guild_candidate/found_guild. Monthly roll
        cadence: an ambitious master mulling this over is a rare,
        deliberate act, not a per-tick scan."""
        guild_target = self._job_target()
        if not self._monthly_gate(events, "guild_founding") or not guild_target.name:
            return
        members = [a for a in self.world.population.agents if a.settlement_id == guild_target.id]
        candidate = self.world.population.deliberate_guild_candidate(guild_target, members)
        if candidate is None:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("guild_founding")
        founder, skill, masters = candidate
        prompt = founding.build_prompt(founder, skill, len(masters), guild_target.name)
        fallback = founding.fallback_founding(founder)
        founder_id = founder.id
        guild_target_id = guild_target.id

        def apply(result: dict, used_fallback: bool) -> None:
            found, reason = founding.parse_founding(result, fallback)
            if not found:
                return  # they weighed it and held back — a real decision, quietly made
            event = self.world.population.found_guild(
                self._settlement_by_id(guild_target_id), skill, founder_id, self.world.clock.tick_count,
            )
            if event is not None:
                self._log(event[0], f'{event[1]} — "{reason}"')

        self._schedule_llm_job("guild_founding", prompt, founding.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_institution_belief(self, events: list[str]) -> None:
        """Institutions Stage 3: once a month, ONE institution with
        living members forms/revises a theory of its own — no longer
        only mirrored copies of settlement beliefs. See
        beliefs.INSTITUTION_SYSTEM_PROMPT for the design note."""
        inst_target = self._job_target()
        if not self._monthly_gate(events, "institution_belief"):
            return
        if not inst_target.name:
            return
        living_ids = {a.id for a in self.world.population.agents}
        candidates = [
            inst for inst in inst_target.institutions
            if inst.member_agent_ids & living_ids
        ]
        if not candidates:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("institution_belief")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "institution_belief")
        institution = rng.choice(candidates)
        if institution.kind is InstitutionKind.COUNCIL:
            label = "council of elders"
        elif institution.kind is InstitutionKind.GUILD:
            label = f"{institution.name} guild"
        else:
            label = "family"
        member_names = [
            a.name for a in self.world.population.agents if a.id in institution.member_agent_ids
        ]
        recent = recent_events_diverse(self.conn, limit=20)
        existing = list(institution.beliefs)
        prompt = beliefs.build_institution_prompt(label, member_names, existing, recent)
        fallback = beliefs.fallback_institution_belief(label, recent)
        existing_count = len(existing)
        institution_id = institution.id
        inst_target_id = inst_target.id

        def apply(result: dict, used_fallback: bool) -> None:
            target = next(
                (i for i in self._settlement_by_id(inst_target_id).institutions if i.id == institution_id), None,
            )
            if target is None:
                return  # pruned while the job was in flight
            parsed = beliefs.parse_belief(result, fallback, existing_count)
            verb = beliefs.apply_institution_belief(target, parsed, self.world.clock.tick_count)
            # v0.87.12 "institution objectives": rides this same call,
            # zero added volume — only overwritten on a genuine new
            # answer, retained across a fallback/blank stretch.
            objective = beliefs.parse_institution_objective(result)
            if objective is not None:
                target.objective = objective
            self._log(
                "institution_belief",
                f"The {label} {'revised its view' if verb == 'revised' else 'came to believe something'}"
                f" of {parsed['subject']}: {parsed['belief']}",
            )

        self._schedule_llm_job("institution_belief", prompt, beliefs.INSTITUTION_SYSTEM_PROMPT, fallback, apply)

    # --- item 8b: inter-settlement diplomacy ------------------------------------

    def _diplomacy_pair_target(self) -> tuple[Settlement, Settlement] | None:
        """Month-indexed round-robin over settlement PAIRS, same "flat
        volume regardless of settlement count" shape as `_job_target` —
        with fewer than two named settlements (the common case) this
        returns None and `_maybe_schedule_diplomacy` never fires a call,
        exactly matching every other settlement job's single-settlement
        behavior."""
        named = sorted((s for s in self.world.settlements if s.name), key=lambda s: s.id)
        if len(named) < 2:
            return None
        pairs = list(itertools.combinations(named, 2))
        clock = self.world.clock
        month_ordinal = clock.year * len(self.world.config.days_per_month) + clock.month_index
        return pairs[month_ordinal % len(pairs)]

    def _maybe_schedule_diplomacy(self, events: list[str]) -> None:
        """Item 8b ("inter-settlement relationships/diplomacy"): the
        underlying affinity (`Settlement.relations`) is already fully
        deterministic (seeded at fission, nudged by cross-settlement
        dialogue) — see settlement/buildings.py's "cross-settlement
        relations" section. This adds the occasional LLM-authored named
        moment on top; fallback is a genuine no-op (see llm/diplomacy.
        py's module docstring)."""
        pair = self._diplomacy_pair_target()
        if not self._monthly_gate(events, "diplomacy") or pair is None:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("diplomacy")
        a, b = pair
        relation = a.relations.get(b.id, 0.0)
        prompt = diplomacy.build_prompt(
            a.name, b.name, relation, a.current_priority, b.current_priority,
            rationale_a=a.priority_rationale, rationale_b=b.priority_rationale,
        )
        fallback = diplomacy.fallback_diplomacy()
        a_id, b_id = a.id, b.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = diplomacy.parse_diplomacy(result, fallback)
            if parsed is None:
                return  # nothing notable this season — a real, expected outcome
            narration, delta = parsed
            stl_a, stl_b = self._settlement_by_id(a_id), self._settlement_by_id(b_id)
            if stl_a is None or stl_b is None:
                return
            new_relation = max(-1.0, min(1.0, stl_a.relations.get(b_id, 0.0) + delta))
            stl_a.relations[b_id] = new_relation
            stl_b.relations[a_id] = new_relation
            self._log("diplomacy_event", f"Between {stl_a.name} and {stl_b.name}: {narration}")

        self._schedule_llm_job(
            "diplomacy", prompt, diplomacy.SYSTEM_PROMPT, fallback, apply,
            settlement=a.name, structured_input={"relation": relation, "other_settlement": b.name},
        )

    # --- item 8c / §7 item 7: laws, customs, taboos -----------------------------

    _LAW_PATTERN_TEXT = {
        "theft": "repeated theft among its own people",
        "dispute_feud": "repeated bitter disputes boiling into feuds",
    }

    def _maybe_schedule_laws(self, events: list[str]) -> None:
        """§7 item 7 / item 8's "politics" ask, folded together (see
        llm/laws.py's module docstring). Gated on real accumulated
        hardship — `Settlement.law_signal_counts`/`pattern_signal_
        counts` — same "spend the call only once texture exists"
        discipline `_maybe_schedule_religion` established. A formed
        law/custom/taboo then feeds back into `dispute.py` (harsher
        outcome bias) and `Population._maybe_commit_theft`
        (`_theft_forbidden_by_law`, sharper penalty) — systems
        interacting, not an isolated mechanic."""
        target = self._job_target()
        if not self._monthly_gate(events, "laws") or not target.name:
            return
        if len(target.laws) >= LAWS_MAX_STORED:
            return
        candidates = {
            "theft": target.law_signal_counts.get("theft", 0),
            "dispute_feud": target.pattern_signal_counts.get("dispute_feud", 0),
        }
        pattern_key = max(candidates, key=candidates.get)
        occurrences = candidates[pattern_key]
        if occurrences < LAW_SIGNAL_THRESHOLD:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("laws")
        pattern_text = self._LAW_PATTERN_TEXT.get(pattern_key, pattern_key)
        prompt = laws.build_prompt(target.name, pattern_text, occurrences, target.laws)
        fallback = laws.fallback_laws()
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = laws.parse_laws(result, fallback)
            if parsed is None:
                return  # not yet — a real, expected outcome, see module docstring
            stl = self._settlement_by_id(target_id)
            if stl is None or len(stl.laws) >= LAWS_MAX_STORED:
                return
            tick = self.world.clock.tick_count
            stl.laws.append({"text": parsed["text"], "kind": parsed["kind"], "formed_tick": tick})
            # Reset the signal that triggered this so it doesn't
            # immediately re-fire on the very next eligible month.
            if pattern_key == "theft":
                stl.law_signal_counts["theft"] = 0
            else:
                stl.pattern_signal_counts["dispute_feud"] = 0
            self._log("law_enacted", f"{stl.name} has come to hold a {parsed['kind']}: {parsed['text']}")

        self._schedule_llm_job("laws", prompt, laws.SYSTEM_PROMPT, fallback, apply)

    # --- item 9: occasional LLM nudges for non-core-cast agents -----------------

    def _maybe_schedule_noncore_nudge(self, events: list[str]) -> None:
        """Item 9 (user's own framing: "not fully LLM authored but "
        "partially and occasionally"). See llm/noncore_nudge.py's module
        docstring — exactly one call a month for the entire world
        (round-robin `_job_target`, one random non-core agent), never
        per-agent-scaled. Non-critical: the fallback is a genuine no-op,
        same discipline as memory_drift."""
        target = self._job_target()
        if not self._monthly_gate(events, "noncore_nudge") or not target.name:
            return
        core_ids = self.world.population.core_agent_ids
        candidates = [
            a for a in self.world.population.agents
            if a.settlement_id == target.id and a.id not in core_ids
        ]
        if not candidates:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("noncore_nudge")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "noncore_nudge")
        agent = rng.choice(candidates)
        agent_id = agent.id
        occupation = self._occupation_for(agent)
        recent = list(agent.memories[-3:])
        settlement_need = self._settlement_economic_need(target)
        prompt = noncore_nudge.build_prompt(agent, occupation, recent, settlement_need)
        fallback = noncore_nudge.fallback_nudge()

        def apply(result: dict, used_fallback: bool) -> None:
            target_agent = self.world.population.get(agent_id)
            if target_agent is None:
                return  # died between scheduling and resolution
            tick = self.world.clock.tick_count
            parsed = noncore_nudge.parse_nudge(result, fallback)
            if parsed is not None:
                trait_name, delta, reflection = parsed
                trait_key = {
                    "resilience": TRAIT_RESILIENCE, "sociability": TRAIT_SOCIABILITY, "ambition": TRAIT_AMBITION,
                }[trait_name]
                _nudge_trait(target_agent, trait_key, delta)
                _remember(target_agent, reflection, because="a quiet personal realization")
                log_agent_memory_entry(self.conn, tick, agent_id, "episodic", reflection)
            # Bounded episodic planning (§7 v0.87.15), extended to the
            # non-core cast here for the first time (see module
            # docstring) — reuses `beliefs.parse_plan` unchanged, the
            # exact machinery Reflect() already uses for the core cast,
            # so `cognition.fallback_goal`'s existing plan_intent bias
            # picks this up for free on the agent's very next tick.
            new_plan = beliefs.parse_plan(result, target_agent.plan, tick)
            if new_plan is not target_agent.plan:
                target_agent.plan = new_plan
                if new_plan is not None and new_plan.get("formed_tick") == tick:
                    log_agent_memory_entry(
                        self.conn, tick, agent_id, "plan", f"New plan: {new_plan['intent']}",
                    )

        self._schedule_llm_job("noncore_nudge", prompt, noncore_nudge.SYSTEM_PROMPT, fallback, apply)

    # --- §2: letters carried by caravans ----------------------------------------

    def _maybe_schedule_letter(self, events: list[str]) -> None:
        """§2 "letters carried by caravans" (docs/IDEAS-2026-07-
        EMERGENCE.md) — see llm/letters.py's module docstring. Monthly
        round-robin `_job_target`, core-cast-only (bounded volume, same
        gating every other per-agent LLM decision uses): finds the
        first core-cast agent in the target settlement with a real bond
        (`MIGRATION_BOND_THRESHOLD`, same threshold `_maybe_migrate`
        uses) to a living agent in another NAMED settlement. Genuine
        no-op when no such pair exists this month — most months, most
        settlements."""
        target = self._job_target()
        if not self._monthly_gate(events, "letter") or not target.name:
            return
        core_ids = self.world.population.core_agent_ids
        sender, recipient = None, None
        for agent in self.world.population.agents:
            if agent.settlement_id != target.id or agent.id not in core_ids:
                continue
            for other_id, value in agent.relationships.items():
                if value < MIGRATION_BOND_THRESHOLD:
                    continue
                other = self.world.population.get(other_id)
                if other is None or other.settlement_id == target.id:
                    continue
                other_settlement = self._settlement_by_id(other.settlement_id)
                if other_settlement is not None and other_settlement.name:
                    sender, recipient = agent, other
                    break
            if sender is not None:
                break
        if sender is None:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("letter")
        recipient_settlement = self._settlement_by_id(recipient.settlement_id)
        prompt = letters.build_prompt(sender, recipient.name, target.name, recipient_settlement.name)
        fallback = letters.fallback_letter(sender, recipient.name)
        sender_id, sender_name, sender_settlement_name = sender.id, sender.name, target.name
        recipient_id, recipient_name, recipient_settlement_id = recipient.id, recipient.name, recipient_settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            text = letters.parse_letter(result, fallback)
            stl = self._settlement_by_id(recipient_settlement_id)
            if stl is None:
                return
            stl.pending_letters.append({
                "from_id": sender_id, "from_name": sender_name, "from_settlement": sender_settlement_name,
                "to_id": recipient_id, "to_name": recipient_name,
                "text": text, "deliver_tick": self.world.clock.tick_count + letters.LETTER_TRAVEL_TICKS,
            })

        self._schedule_llm_job("letter", prompt, letters.SYSTEM_PROMPT, fallback, apply)

    def _deliver_letters(self) -> None:
        """Daily check (day_end): delivers any queued letter whose
        travel delay has passed. Zero LLM cost — the letter's content
        was already authored when it was written; this only resolves
        whether the recipient is still there to read it. "Latency is
        the feature" (module docstring): a letter can genuinely arrive
        after its recipient has died in the interim, which reads as a
        real, poignant moment rather than being silently dropped."""
        tick = self.world.clock.tick_count
        for stl in self.world.settlements:
            if not stl.pending_letters:
                continue
            remaining = []
            for letter in stl.pending_letters:
                if letter["deliver_tick"] > tick:
                    remaining.append(letter)
                    continue
                recipient = self.world.population.get(letter["to_id"])
                if recipient is None:
                    self._log(
                        "letter_arrived_too_late",
                        f"A letter from {letter['from_name']} arrives for {letter['to_name']} — "
                        "too late; they are gone.",
                    )
                    continue
                _remember(recipient, f"A letter from {letter['from_name']}: {letter['text']}", because=f"letter from {letter['from_name']}")
                self._log("letter_delivered", f"{letter['to_name']} receives a letter from {letter['from_name']}.")
                if _namespaced_roll(
                    self.world.config.seed, tick, f"letter_rumor_{letter['from_id']}_{letter['to_id']}",
                ) < letters.LETTER_RUMOR_CHANCE:
                    rumor_rng = _namespaced_rng(self.world.config.seed, tick, "letter_rumor")
                    self.world.population.spread_rumor(
                        f"word from {letter['from_settlement']}: {letter['text']}", 2, rumor_rng,
                    )
            stl.pending_letters = remaining

    def _choose_fission_site(
        self, origin: tuple[int, int] | None = None, home: "Settlement | None" = None,
    ) -> tuple[int, int] | None:
        """The best walkable tile at least FISSION_MIN_DISTANCE from
        every existing settlement's center, scored by nearby wild-food
        supply — the same criterion the original founders' spawn used
        (Population._best_founding_site), because a founding party faces
        the same first problem: eating before infrastructure exists.
        None when the map has no qualifying tile (fission then lapses
        this month).

        v0.87.45 exploration/surveyor batch: when `home` is given and
        its surveyors have logged real resource/mineral findings
        (`Settlement.exploration_findings`), candidate spots near one of
        those findings are preferred over the blind local search below —
        the concrete "surveyor knowledge helps the town expand" payoff.
        Falls back to the unfiltered candidate list when no surveyed
        site qualifies (still gated by FISSION_MIN_DISTANCE), so this
        never blocks fission, only steers it toward known-good ground."""
        centers = [c for c in (s.center() for s in self.world.settlements) if c is not None]
        spots = [
            (x, y) for (x, y) in _walkable_tiles(self.world.terrain)
            if all(max(abs(x - cx), abs(y - cy)) >= FISSION_MIN_DISTANCE for cx, cy in centers)
        ]
        if home is not None and spots:
            surveyed = [
                (f["x"], f["y"]) for f in home.exploration_findings if f.get("kind") in ("resource", "mineral")
            ]
            if surveyed:
                near_surveyed = [
                    pos for pos in spots
                    if any(abs(pos[0] - fx) + abs(pos[1] - fy) <= 5 for fx, fy in surveyed)
                ]
                if near_surveyed:
                    spots = near_surveyed
        if origin is not None and spots:
            # Never point the party at land it can't walk to — rivers/
            # lakes genuinely disconnect regions on this generator.
            # Standing bridges widen what's actually reachable, same as
            # for any other agent's pathing.
            bridge_tiles = _bridge_tiles_from_settlements(self.world.settlements)
            reachable = Population._reachable_tiles(self.world.terrain, origin, bridge_tiles)
            spots = [pos for pos in spots if pos in reachable]
        if not spots:
            return None
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "fission_site")
        return Population._best_founding_site(spots, self.world.resources, rng)

    def _maybe_schedule_fission(self, events: list[str]) -> None:
        """Multiple named settlements (v0.65.0): once a month, if a
        crowded, established settlement has an ambitious would-be
        leader (Population.fission_candidate), the LLM decides whether
        they actually lead a founding party out (llm/fission.py). On
        "yes": a distant site is chosen, a new Settlement is created
        with a materials grant physically hauled from the mother
        settlement, and the party walks there (Agent.travel_target) to
        build from nothing — first hut, placeholder name, background
        LLM naming, and the monthly job rotation all then happen
        through the exact machinery the founding settlement already
        uses. Declining is a real outcome."""
        if not self._monthly_gate(events, "fission"):
            return
        candidate = self.world.population.fission_candidate(
            self.world.settlements, self.world.clock.tick_count,
        )
        if candidate is None:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("fission")
        leader, home = candidate
        members = home.living_member_count(self.world.population.agents)
        housing = sum(
            1 for b in home.buildings
            if b.kind is BuildingKind.HUT and b.stage is BuildingStage.STANDING
        ) * HUT_CAPACITY + CAMP_TOLERANCE
        home_religion_name = home.religion["name"] if home.religion is not None else None
        prompt = fission.build_prompt(
            leader, home.name, members, housing, self.world.clock.season,
            religion_name=home_religion_name,
        )
        fallback = fission.fallback_decision(leader)
        leader_id, home_id = leader.id, home.id

        def apply(result: dict, used_fallback: bool) -> None:
            depart, reason, schism = fission.parse_decision(result, fallback)
            if not depart:
                return  # they weighed the leap and stayed — a real decision
            population = self.world.population
            leader = population.get(leader_id)
            home = self._settlement_by_id(home_id)
            if leader is None or leader.settlement_id != home_id:
                return  # died or already uprooted while the decision was in flight
            if len(self.world.settlements) >= MAX_SETTLEMENTS:
                return
            party = population.fission_party(leader, home)
            if party is None:
                return  # no viable party could be assembled after all
            site = self._choose_fission_site(origin=(leader.x, leader.y), home=home)
            if site is None:
                return  # no qualifying land far enough from everyone
            new_id = max(s.id for s in self.world.settlements) + 1
            new_settlement = Settlement(
                id=new_id, center_x=site[0], center_y=site[1],
                era=home.era, tech_level=home.tech_level,
                founding_scenario=(
                    f"Settled by families who left {home.name} seeking room of their own."
                ),
            )
            grant = home.materials * FISSION_MATERIALS_SHARE
            home.materials -= grant
            new_settlement.materials = grant
            # Cross-settlement relations (v0.67.0): the daughter starts
            # warm toward the settlement it just split from (and vice
            # versa) — a peaceful split, colored a little by the origin's
            # mood at the moment of departure. See buildings.seed_relation.
            relation_rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "fission_relation")
            seed = seed_relation(home.temperament, relation_rng)
            home.relations[new_id] = seed
            new_settlement.relations[home_id] = seed
            # Phase M schism: the departing party carries the home
            # settlement's faith (if any) with them — either unchanged,
            # or, on a genuine model-read schism, a deterministically
            # generated "different reading" of the same tenets (no
            # second LLM call — see fission.build_prompt's docstring).
            if home.religion is not None:
                if schism:
                    new_settlement.religion = {
                        "name": f"{home.religion['name']} (Reformed)",
                        "tenets": list(home.religion["tenets"]),
                        "formed_tick": self.world.clock.tick_count,
                        "schism_of": home_id,
                    }
                    self._log(
                        "religion_formed",
                        f"The settlers who left {home.name} carry a changed reading of its faith, {home.religion['name']}.",
                    )
                else:
                    new_settlement.religion = {
                        "name": home.religion["name"], "tenets": list(home.religion["tenets"]),
                        "formed_tick": self.world.clock.tick_count, "schism_of": None,
                    }
            self.world.settlements.append(new_settlement)
            population.depart_for_fission(
                party, new_settlement, site, self.world.clock.tick_count, home.name,
            )
            self._log(
                "settlement_founded",
                f"{leader.name} led {len(party)} settlers out of {home.name}"
                f" toward a new home in the distance — \"{reason}\"",
            )

        self._schedule_llm_job("fission", prompt, fission.SYSTEM_PROMPT, fallback, apply)

    # --- §5 "Ruins mode / successor worlds" (docs/IDEAS-2026-07-EMERGENCE.md) --

    def _found_successor_world(self) -> None:
        """Applied the tick after `POST /world/found-successor` enqueues
        a `found_successor_world` intervention (same enqueue-now/apply-
        next-tick seam as every other intervention — this mutates
        `World.settlements`/`World.population`, which must only ever
        happen from inside the single-writer tick loop). Gated on true
        extinction (`self.world.population.agents` empty — the doc's
        "on true extinction" case; "or by choice" while a population is
        still alive is a documented scope trim, since relocating a LIVING
        population is a materially different, larger mechanism). Founds
        a genuinely NEW settlement on the SAME terrain/roads/wildlife/
        farms — nothing about the physical world resets — while every
        defunct settlement's ruins/memorials/records/place_names/
        religion/folklore are left exactly as they decayed to, still
        addressable via `_settlement_by_id`. The new settlement's
        `predecessor_id` points at whichever defunct settlement holds
        the richest history (most records+memorials+rituals+beliefs),
        so `llm/beliefs.py` can invite the new population to form a
        theory about the old ruins/records it may honestly misread —
        "deep time, archaeology, and 'they got the old stories wrong.'\""""
        if self.world.population.agents:
            self._log("successor_founding_refused", "A successor world was requested, but the population is not yet extinct.")
            return
        if len(self.world.settlements) >= MAX_SETTLEMENTS:
            self._log("successor_founding_refused", "A successor world was requested, but the world is already at its settlement limit.")
            return
        predecessor = max(
            self.world.settlements,
            key=lambda s: len(s.records) + len(s.memorials) + len(s.rituals) + len(s.beliefs),
        )
        new_settlement = Settlement(id=max(s.id for s in self.world.settlements) + 1)
        new_settlement.predecessor_id = predecessor.id
        self.world.settlements.append(new_settlement)
        founders = self.world.population.spawn_successor_founders(
            seed=self.config.seed, tick=self.world.clock.tick_count,
            count=self.config.initial_population, terrain=self.world.terrain,
            resources=self.world.resources, settlement_id=new_settlement.id,
        )
        detail = (
            f"{len(founders)} newcomers have settled amid the ruins once called "
            f"{predecessor.name or 'a forgotten place'}, to build something new."
        )
        self._log("successor_founded", detail)
        self._append_highlight("successor_founded", detail)

    def _maybe_schedule_geography(self, events: list[str]) -> None:
        """Named geography: one unnamed feature (the river first, then
        each lake) earns a permanent name per month once the settlement
        itself is named. See llm/geography.py."""
        if not self._monthly_gate(events, "geography") or not self.world.settlement.name:
            return
        place_names = self.world.settlement.place_names
        feature_key = feature_kind = None
        if "river" not in place_names and self.world.cached_biome_counts().get("river", 0) > 0:
            feature_key, feature_kind = "river", "river"
        else:
            for lake in self.world.lakes:
                key = f"lake_{lake.id}"
                if key not in place_names:
                    feature_key, feature_kind = key, "lake"
                    break
        if feature_key is None:
            return  # everything nameable already has a name — permanent no-op
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("geography")
        prompt = geography.build_prompt(
            self.world.settlement.name, feature_kind, self.world.settlement.founding_scenario,
        )
        fallback = geography.fallback_name(feature_kind, self.world.clock.tick_count)

        def apply(result: dict, used_fallback: bool) -> None:
            if feature_key in self.world.settlement.place_names:
                return  # already named by an earlier in-flight job
            name = geography.parse_name(result, fallback)
            self.world.settlement.place_names[feature_key] = name
            noun = "the river" if feature_kind == "river" else "the lake"
            self._log("place_named", f"The villagers took to calling {noun} {name}.")

        self._schedule_llm_job("geography", prompt, geography.SYSTEM_PROMPT, fallback, apply)

    def _log(self, category: str, description: str) -> None:
        """Persist an event AND buffer it for the next broadcast —
        use this (not a bare `log_event` call) for anything logged
        outside `World.tick()` itself, i.e. dialogue/rumor/chronicle/
        tradition/invention/festival/intervention/town-brain, so it
        actually reaches the live WebSocket feed instead of only
        showing up via the one-shot `/events` fetch on page load. See
        `_pending_broadcast_events`, docs/DECISIONS.md, "LLM-as-brain
        batch,\" fix: live event stream gap."""
        # commit=False: the next tick's end-of-tick commit (or the final
        # shutdown snapshot's) lands this — one fsync per tick, not per
        # event. A result arriving between ticks waits at most one tick.
        log_event(self.conn, tick=self.world.clock.tick_count, category=category, description=description, commit=False)
        self._pending_broadcast_events.append({"category": category, "description": description})

    def _append_highlight(self, kind: str, detail: str) -> None:
        """§5 "Anomaly/highlight log" (docs/IDEAS-2026-07-EMERGENCE.md):
        appends to `World.highlights`, capped at HIGHLIGHTS_MAX_STORED
        (oldest evicted) — a small, bounded, zero-LLM-cost self-flagged
        record distinct from the full `events` table this project
        already durably logs everything to. Called from hand-picked
        trigger sites (first religion, extinction near-miss, feud
        formation, first ritual) and from `_log_daily_metrics`'s rolling
        z-score anomaly check."""
        self.world.highlights.append({
            "kind": kind, "detail": detail, "tick": self.world.clock.tick_count,
        })
        if len(self.world.highlights) > HIGHLIGHTS_MAX_STORED:
            self.world.highlights = self.world.highlights[-HIGHLIGHTS_MAX_STORED:]

    def _log_daily_metrics(self) -> None:
        """One compact time-series row per sim-day (see database.py's
        `metrics` table, `GET /metrics`) — the instrumentation layer the
        July 2026 architecture review called the platform's biggest
        missing scientific tool: population/food/social curves over
        years, ablation comparisons (LLM vs fallback), and rumor/belief
        studies all need a fixed-cadence series, not just the narrative
        event log. Committed by _tick_once's end-of-tick commit."""
        population = self.world.population
        settlements = self.world.settlements
        settlement = self.world.settlement
        pop_summary = population.summary()
        farm_summary = self.world.farms.summary()
        wildlife_summary = self.world.wildlife.summary()
        metrics = {
            "population": pop_summary["total"],
            "avg_hunger": pop_summary["avg_hunger"],
            "avg_energy": pop_summary["avg_energy"],
            "deaths_starvation": population.deaths_starvation,
            "deaths_old_age": population.deaths_old_age,
            "deaths_predator": population.deaths_predator,
            "close_bonds": pop_summary["close_bonds"],
            "rivalries": pop_summary["rivalries"],
            "avg_personal_food": pop_summary["avg_personal_food"],
            "farms_total": farm_summary["total"],
            "farms_ready": farm_summary["ready"],
            "granary_food": round(sum(
                b.stored_food for s in settlements for b in s.buildings
                if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
            ), 3),
            "materials": round(sum(s.materials for s in settlements), 3),
            "currency": round(sum(s.currency for s in settlements), 3),
            "buildings_standing": sum(
                1 for s in settlements for b in s.buildings if b.stage is BuildingStage.STANDING
            ),
            "grazers": wildlife_summary.get("grazer_total", 0),
            "predators": wildlife_summary.get("predator_total", 0),
            "tech_level": settlement.tech_level,
            "priority": settlement.current_priority,
            "temperament": round(settlement.temperament, 3),
            "beliefs": len(settlement.beliefs),
            "rumors_total": self.world.rumor_total,
            "llm_fallback_total": self.world.llm_fallback_total,
        }
        log_metrics(self.conn, tick=self.world.clock.tick_count, metrics=metrics, commit=False)
        self._detect_metric_highlights(pop_summary["total"])

    def _detect_metric_highlights(self, population_total: int) -> None:
        """§5 "Anomaly/highlight log" (docs/IDEAS-2026-07-EMERGENCE.md):
        two cheap, deterministic checks riding the existing once-per-
        sim-day `_log_daily_metrics` cadence — no separate polling loop.

        (1) Extinction near-miss: population freshly crosses below
        `POPULATION_CRITICAL_THRESHOLD` from at or above it — a genuine
        edge (`_prev_population_total` tracks the last reading) so a
        settlement that STAYS critically low for a long stretch is
        flagged once, not every single day.

        (2) Rolling z-score: population swinging more than
        `HIGHLIGHT_POPULATION_Z_THRESHOLD` standard deviations from its
        own recent mean (`HIGHLIGHT_ZSCORE_WINDOW` prior days) — a
        plain statistical surprise detector, the doc's own suggested
        mechanism, requiring at least a few days of history to have a
        meaningful mean/stdev at all."""
        prev = self._prev_population_total
        if prev is not None and prev >= POPULATION_CRITICAL_THRESHOLD and population_total < POPULATION_CRITICAL_THRESHOLD:
            self._append_highlight(
                "extinction_near_miss",
                f"The population fell to {population_total} — the brink of extinction.",
            )
        self._prev_population_total = population_total

        history = recent_metrics(self.conn, limit=HIGHLIGHT_ZSCORE_WINDOW)
        prior = [row["population"] for row in history[:-1] if "population" in row]
        if len(prior) >= 5:
            mean = sum(prior) / len(prior)
            variance = sum((v - mean) ** 2 for v in prior) / len(prior)
            stdev = variance ** 0.5
            if stdev >= 1.0:
                z = (population_total - mean) / stdev
                if abs(z) >= HIGHLIGHT_POPULATION_Z_THRESHOLD:
                    direction = "surged" if z > 0 else "dropped"
                    self._append_highlight(
                        "population_anomaly",
                        f"Population {direction} to {population_total} — well outside its recent trend "
                        f"(~{mean:.0f} average).",
                    )

    def _record_llm_call(self, used_fallback: bool) -> None:
        """Cumulative counters persisted on `World`, for diagnosing LLM
        flakiness (timeouts, unreachable server) from a saved snapshot
        alone — see docs/DECISIONS.md, D5."""
        self.world.llm_calls_total += 1
        if used_fallback:
            self.world.llm_fallback_total += 1

    def _record_llm_debug(
        self, name: str, prompt: str, result: dict, used_fallback: bool, elapsed_ms: float | None = None,
        system_prompt: str | None = None, raw_completion: str | None = None,
        structured_input: dict | None = None, npc_ids: list | None = None, settlement: str | None = None,
        outcome: dict | None = None,
    ) -> None:
        """Records the most recent prompt/result for one named LLM job
        — see `self._last_llm_calls`'s docstring — and folds size/
        latency into `_llm_prompt_stats` (see its own docstring). Called
        for every real OR fallback resolution, so a job whose fallback
        rate is high still shows up in the prompt-size telemetry (the
        prompt was still built and sent, or would have been, even on a
        deferred/budget-skipped critical job — the one exception is a
        critical job's daily-budget-exhaustion path in `_schedule_llm_
        job`, which already calls this with the fallback dict before
        this method runs, same as every other fallback resolution).

        Also the single hook point for the permanent LLM training
        recorder (llm/recorder.py, §8 — OFF by default, zero-cost when
        so): every named LLM task in the codebase funnels through here,
        so a brand-new future job type is automatically recordable with
        no recorder-specific code of its own. `system_prompt`/
        `raw_completion`/`structured_input`/`npc_ids`/`settlement` are
        all optional — see recorder.py's own docstring for which task
        types currently supply real `structured_input` versus the `{}`
        default."""
        self._last_llm_calls[name] = {
            "tick": self.world.clock.tick_count, "prompt": prompt,
            "result": result, "used_fallback": used_fallback,
        }
        self._training_recorder.maybe_record(
            task=name, prompt=prompt, system_prompt=system_prompt, result=result,
            used_fallback=used_fallback, raw_completion=raw_completion,
            elapsed_ms=elapsed_ms, tick=self.world.clock.tick_count,
            structured_input=structured_input, npc_ids=npc_ids, settlement=settlement,
            outcome=outcome,
        )
        stats = self._llm_prompt_stats.setdefault(name, {
            "calls": 0, "fallback_calls": 0,
            "prompt_chars": deque(maxlen=LLM_PROMPT_STATS_WINDOW),
            "completion_chars": deque(maxlen=LLM_PROMPT_STATS_WINDOW),
            "latency_ms": deque(maxlen=LLM_PROMPT_STATS_WINDOW),
        })
        stats["calls"] += 1
        if used_fallback:
            stats["fallback_calls"] += 1
        stats["prompt_chars"].append(len(prompt))
        # `result` is the parsed JSON dict (or the fallback dict on a
        # fallback resolution) — its str() length is a rough proxy for
        # completion size. Not a real token count (see LLM_PROMPT_
        # STATS_WINDOW's docstring for why this project doesn't carry a
        # tokenizer dependency), but consistent enough to compare across
        # job types and spot a verbose one.
        stats["completion_chars"].append(len(str(result)))
        if elapsed_ms is not None:
            stats["latency_ms"].append(elapsed_ms)

    # --- permanent LLM training recorder (§8, llm/recorder.py) ----------------

    def training_recorder_status(self) -> dict:
        return self._training_recorder.status()

    def start_training_recording(
        self, session_name: str | None = None, policy: str = "all_tasks",
        selected_tasks: list[str] | None = None, sample_rate: float = 0.1,
        tags: list[str] | None = None,
    ) -> dict:
        return self._training_recorder.start(session_name, policy, selected_tasks, sample_rate, tags)

    def stop_training_recording(self) -> dict:
        return self._training_recorder.stop()

    def llm_prompt_stats_summary(self) -> dict:
        """Aggregates `_llm_prompt_stats`'s rolling per-job deques into
        one dict of `{calls, fallback_calls, avg_prompt_tokens_est,
        p95_prompt_tokens_est, avg_completion_tokens_est, avg_latency_
        ms, p95_latency_ms}` per job name. `latency_ms` here is
        wall-clock from scheduling to result (includes any
        backpressure/semaphore queue wait), distinct from `llm_stats.
        latency_ms_p50/p95` (`CognitionRunner`'s own aggregate, timed
        purely inside the semaphore — pure inference time only);
        comparing the two tells you whether a slow job type is
        queue-bound or inference-bound. The token counts are a
        ~4-chars/token estimate (`_TOKEN_CHARS_ESTIMATE`), clearly
        labeled `_est` throughout so they're never mistaken for a real
        tokenizer count. `full_diagnostics()`'s `llm_prompt_stats` key;
        this is the concrete "measure before optimizing further" tool
        the 2026-07 prompt-density audit built, kept live rather than
        one-off so a future regression (a new job that grows an
        unbounded prompt) is visible without re-running an ad-hoc
        script."""
        def pctl(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            s = sorted(values)
            return s[min(len(s) - 1, int(len(s) * p))]

        summary = {}
        for name, stats in self._llm_prompt_stats.items():
            prompt_chars = list(stats["prompt_chars"])
            completion_chars = list(stats["completion_chars"])
            latencies = list(stats["latency_ms"])
            summary[name] = {
                "calls": stats["calls"],
                "fallback_calls": stats["fallback_calls"],
                "avg_prompt_tokens_est": round(sum(prompt_chars) / len(prompt_chars) / _TOKEN_CHARS_ESTIMATE, 1)
                if prompt_chars else 0.0,
                "p95_prompt_tokens_est": round(pctl(prompt_chars, 0.95) / _TOKEN_CHARS_ESTIMATE, 1),
                "avg_completion_tokens_est": round(
                    sum(completion_chars) / len(completion_chars) / _TOKEN_CHARS_ESTIMATE, 1
                ) if completion_chars else 0.0,
                "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
                "p95_latency_ms": round(pctl(latencies, 0.95), 1) if latencies else None,
            }
        return summary

    # --- Phase F: read-only WebSocket broadcast --------------------------------

    def _maybe_broadcast(self) -> None:
        """Fire-and-forget, same pattern as LLM background jobs — a slow
        or absent client must never be able to delay a tick. No-op when
        the API isn't enabled (`self._broadcaster is None`). Terrain
        itself is NOT part of the per-tick payload (it's data-light but
        the client only needs it on an actual change) — instead, on a
        tick where terrain evolution changed a tile's biome, this
        re-pushes the terrain snapshot the same way `__init__` seeds it
        the first time, so `GET /terrain`/the client's static canvas
        don't go stale. See docs/DECISIONS.md, terrain-evolution pass,
        and F1/F2 for the original one-shot rationale."""
        if self._broadcaster is None:
            self._pending_broadcast_events = []  # nobody will ever read this buffer — don't let it grow unbounded
            return
        if any(category in TERRAIN_CHANGING_CATEGORIES for category, _ in self.world.last_life_events):
            self._broadcaster.set_terrain(
                self.world.terrain, self.world.config.width, self.world.config.height,
                mining_scars=self.world.mining_scars,
            )
        tick_events = [
            {"category": category, "description": description}
            for category, description in self.world.last_life_events
        ]
        if (
            self._broadcaster.client_count() == 0
            and self.world.clock.tick_count % IDLE_BROADCAST_EVERY_TICKS != 0
        ):
            # Nobody is watching live — skip the payload build this tick
            # (see IDLE_BROADCAST_EVERY_TICKS), but keep this tick's
            # events so the next built payload still carries them.
            self._pending_broadcast_events.extend(tick_events)
            if len(self._pending_broadcast_events) > PENDING_BROADCAST_EVENTS_MAX:
                self._pending_broadcast_events = self._pending_broadcast_events[-PENDING_BROADCAST_EVENTS_MAX:]
            return
        # Buffered (older) events first, then this tick's own — oldest-
        # first is the order the frontend's prepend loop expects.
        life_events = self._pending_broadcast_events + tick_events
        self._pending_broadcast_events = []
        settlements = self.world.settlements
        payload = {
            "summary": self.world.summary(),
            "life_events": life_events,
            # `is_core` (v0.72.0): whether this agent is in the LLM core
            # cast (Population.core_agent_ids) — the only agents whose
            # goals/dialogue are model-authored, everyone else runs the
            # deterministic fallback (see Config.llm_core_cast_size).
            # Surfaced on the map (blue triangle vs. the plain dot) and
            # in the NPC inspector so a player can actually see which
            # inhabitants are the LLM-driven protagonists — Observatory
            # UI direction: read at a glance, not buried in a stat.
            "agents": [
                {
                    **a.to_dict(), "is_core": self.world.population.is_core(a.id),
                    # §9 "long-term reputation and family legacy": plain
                    # -1..1 aggregate trust reading, same reachability as
                    # any other agent stat — not under Phase G's
                    # ambiguity discipline (unlike temperament/mood).
                    "reputation": self.world.population.reputation(a.id),
                }
                for a in self.world.population.agents
            ],
            # Physical layers merge across every settlement — the map
            # shows the world, not one community's slice of it.
            "buildings": [b.to_dict() for s in settlements for b in s.buildings],
            "vehicles": [v.to_dict() for s in settlements for v in s.vehicles],
            "farms": [p.to_dict() for p in self.world.farms.plots.values()],
            "resources": [n.to_dict() for n in self.world.resources.nodes.values()],
            # Mineral veins (v0.87.26, world/minerals.py) were tracked and
            # persisted from the start but never actually reached the live
            # broadcast payload — the tile inspector had no data to show,
            # which is why a mined-hills tile read as bare "land" despite
            # a real deposit sitting under it. Same to_dict() shape as
            # `resources` above.
            "minerals": [d.to_dict() for d in self.world.minerals.deposits.values()],
            "wildlife": [h.to_dict() for h in self.world.wildlife.herds.values()],
            "roads": self.world.roads.to_dict()["wear"],
            "diagnostics": self._diagnostics_snapshot(),
            "infrastructure": [
                row for s in settlements for row in s.infrastructure_report()
            ],
            # Full institution membership (not just settlement.summary()'s
            # counts-only view) — added for the relationship graph's
            # family-tree edges and the NPC inspector's institution
            # membership display (docs/DECISIONS.md, "continue expanding").
            # A separate top-level key rather than nested in `summary`,
            # matching how buildings/vehicles/farms are already broadcast
            # alongside it rather than folded in.
            "institutions": [i.to_dict() for s in settlements for i in s.institutions],
            # Grave marks (v0.64.0): drawn as persistent map memorials —
            # already capped server-side (MEMORIALS_MAX_STORED).
            "memorials": [m for s in settlements for m in s.memorials],
            # One full per-settlement summary each, for the UI's
            # settlement switcher; summary.settlement stays the founding
            # settlement for anything predating the switcher.
            "settlement_summaries": [
                {
                    **s.summary(established_roads=self.world.roads.summary()["established_roads"]),
                    "members": s.living_member_count(self.world.population.agents),
                }
                for s in settlements
            ],
        }
        task = asyncio.create_task(self._broadcaster.broadcast(payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _diagnostics_snapshot(self) -> dict:
        """Cheap, per-tick diagnostics — safe to compute every tick (no
        disk I/O, no DB queries). See `full_diagnostics` for the heavier,
        on-demand report behind `GET /diagnostics`.

        `llm_backlog_effective`/`llm_backlog_reserved_this_tick`/
        `llm_backpressure_limit`/`llm_backpressure_limit_effective`
        (v0.81.0) expose the backpressure-reservation fix and adaptive
        load control directly: `_effective_backlog()` is what every
        scheduling decision this tick actually compares against (the raw
        `llm_stats.backlog` plus same-tick reservations not yet reflected
        there — see `_reserved_this_tick`'s docstring), and `_current_
        backpressure_limit()` is the live, latency-adaptive ceiling —
        watch it drop below the static `llm_backpressure_limit` during a
        genuinely slow stretch and recover once latency does, without
        needing to infer it from `calls_dropped_backpressure` alone."""
        durations = sorted(self._tick_durations_ms)
        p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else 0.0
        return {
            "seed": self.config.seed,
            "tick_duration_ms": round(self._last_tick_duration_ms, 2),
            "tick_duration_ms_p95": round(p95, 2),
            "background_tasks": len(self._background_tasks),
            "inflight_cognition": len(self._inflight_cognition_agent_ids),
            "connected_clients": self._broadcaster.client_count() if self._broadcaster else 0,
            "llm_enabled": self._cognition_runner.enabled,
            "llm_max_concurrent": self.config.llm_max_concurrent,
            "llm_model": self.config.llm_model,
            "llm_stats": self._cognition_runner.stats(),
            "llm_backlog_effective": self._effective_backlog(),
            "llm_backlog_reserved_this_tick": self._reserved_this_tick,
            "llm_backpressure_limit": self._backpressure_limit,
            "llm_backpressure_limit_effective": self._current_backpressure_limit(),
            # LLM-pressure tick pacing (v0.81.2, see LLM_PRESSURE_SLOWDOWN_
            # START_RATIO's docstring): `llm_pressure_ratio` is how far over
            # the adaptive limit the backlog currently sits (>1.0 = ticks
            # are being slowed, >= LLM_PRESSURE_PAUSE_RATIO = ticking is
            # fully paused this cycle) — the UI's "town is thinking" state
            # reads these directly rather than inferring pressure from drop
            # counts.
            "llm_pressure_ratio": round(self.llm_pressure_ratio(), 3),
            "llm_pressure_paused": self.llm_pressure_paused(),
            "training_recorder": self.training_recorder_status(),
            "llama_server_restarting": self._llama_server_restarting,
            "llama_server_restarts_total": self._llama_server_restarts,
            "llm_calls_today": self._llm_calls_today,
            "llm_max_calls_per_day": self.config.llm_max_calls_per_day,
            "llm_core_cast_size": self.config.llm_core_cast_size,
            "llm_core_cast_current": len(self.world.population.core_agent_ids),
            "dialogue_cooldown_entries": len(self.world.population.dialogue_cooldowns),
            "snapshots_saved": self._snapshots_saved,
            "sim_pacing": self._broadcaster.sim_pacing() if self._broadcaster else {"paused": False, "speed_multiplier": 1.0},
        }

    def full_diagnostics(self) -> dict:
        """A heavier, on-demand diagnostic report for `GET /diagnostics`
        — everything in `_diagnostics_snapshot` plus process memory and
        on-disk DB size, both of which need a syscall/stat and so are
        deliberately NOT computed every tick. Built specifically to be
        useful for an unattended overnight soak test: paste this into a
        bug report and it should answer "is the LLM degraded," "is
        memory growing," and "is the DB growing," without needing to
        reproduce the run. See docs/DECISIONS.md, diagnostics pass."""
        peak_rss_mb = None
        if resource is not None:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux reports ru_maxrss in KB; macOS reports bytes — this
            # project's target hardware is Linux (see CLAUDE.md), so KB
            # is assumed rather than sniffing the platform.
            peak_rss_mb = round(usage / 1024, 1)
        db_size_mb = None
        if self.config.db_path != ":memory:" and os.path.exists(self.config.db_path):
            db_size_mb = round(os.path.getsize(self.config.db_path) / 1_000_000, 2)
        agents = self.world.population.agents
        pop_total = len(agents)
        relationship_entries = sum(len(a.relationships) for a in agents)
        trust_entries = sum(len(a.trust) for a in agents)
        # Movement diagnostics (v0.81.0, see Agent.stuck_ticks): how many
        # agents are mid-way through the stuck-tick counter right now (a
        # snapshot, not cumulative) — a healthy run should read near 0;
        # a persistently high count across repeated /diagnostics reads
        # would point at a genuinely unreachable target rather than a
        # transient obstacle the BFS escape already resolves. Cheap
        # (bounded by POPULATION_CAP), only computed on this on-demand
        # path, not every tick.
        agents_movement_stuck = sum(1 for a in agents if a.stuck_ticks > 0)
        # Oldest currently-buffered-but-unapplied result's age in ticks
        # (v0.81.0) — `_pending_goal_results`/`_pending_dialogue_results`
        # normally drain the very next `_tick_once()`, so this should
        # read ~0-1 on a healthy run; a climbing value would mean results
        # are landing faster than the tick loop drains them, a distinct
        # symptom from `llm_stats.backlog` (in-flight/queued, not yet
        # resolved) worth telling apart when diagnosing staleness.
        now = self.world.clock.tick_count
        oldest_pending_goal_ticks = max(
            (now - t for t, _, _ in self._pending_goal_results.values()), default=0,
        )
        oldest_pending_dialogue_ticks = max(
            (now - entry[0] for entry in self._pending_dialogue_results), default=0,
        )
        return {
            **self._diagnostics_snapshot(),
            "peak_memory_rss_mb": peak_rss_mb,
            "system_memory": system_memory_report(),
            "db_size_mb": db_size_mb,
            "uptime_ticks": self.world.clock.tick_count,
            "population_total": pop_total,
            "agents_movement_stuck": agents_movement_stuck,
            "oldest_pending_goal_ticks": oldest_pending_goal_ticks,
            "oldest_pending_dialogue_ticks": oldest_pending_dialogue_ticks,
            "last_llm_calls": self._last_llm_calls,
            "llm_prompt_stats": self.llm_prompt_stats_summary(),
            "memory_retrieval": retrieval_diagnostics(),
            "llama_server_metrics": self._llama_server_metrics,
            "pending_player_whispers": list(self.world.settlement.player_influence),
            "temperament": round(self.world.settlement.temperament, 3),
            "consciousness": {
                # Phase N: same "concise value alongside the raw lists"
                # treatment `temperament` gets above — the full lists are
                # already reachable via /state (World.summary()'s
                # "consciousness" key, now also mirrored into the
                # lightweight dev-console pane) so this stays a glance-
                # able summary rather than duplicating them wholesale.
                "personality": dict(self.world.consciousness_personality),
                "objectives": list(self.world.consciousness_objectives),
                "memory_count": len(self.world.consciousness_memory),
                "latest_memory": self.world.consciousness_memory[-1] if self.world.consciousness_memory else None,
                "player_model_count": len(self.world.consciousness_player_model),
                "latest_intervention": (
                    self.world.consciousness_intervention_log[-1]
                    if self.world.consciousness_intervention_log else None
                ),
                # Durable full-history count (v0.86.2, Constitution §6) —
                # everything the consciousness has ever noticed/theorized/
                # intervened on, on disk, distinct from the tiny in-RAM
                # caps above. See database.py's consciousness_log schema
                # docstring.
                "durable_log_count": consciousness_log_count(self.conn),
            },
            "relationship_graph": {
                # A cheap live signal for the class of leak fixed in the
                # "memory leak: unpruned relationships" pass — dead or
                # decayed-to-zero entries are pruned every tick, so
                # avg_per_agent should stay a small, roughly-stable
                # multiple of *recent* colocation, not grow with the
                # world's total historical population. A steadily
                # climbing average here on a live soak run is the same
                # symptom to watch for if a similar leak is ever
                # reintroduced elsewhere. See docs/DECISIONS.md.
                "relationship_entries": relationship_entries,
                "trust_entries": trust_entries,
                "avg_relationships_per_agent": round(relationship_entries / pop_total, 1) if pop_total else 0.0,
            },
        }
