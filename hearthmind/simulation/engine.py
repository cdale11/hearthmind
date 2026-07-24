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
import math
import os
import re
import sqlite3
import time
from collections import deque
from typing import TYPE_CHECKING

try:
    import resource  # Unix-only; used for peak-RSS diagnostics, gracefully absent on Windows.
except ImportError:  # pragma: no cover — this project's target hardware is Linux
    resource = None  # type: ignore[assignment]

from hearthmind.agents.agent import (
    DEBT_SIGNIFICANT_THRESHOLD,
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
    faction, fission, beliefs, caravan, chronicle, chronicler, composite_entity, consciousness, culture,
    culture_digest, dialogue,
    digest, dispute, documentary, dream, era_branch, festival, folklore, founding, geography, invention,
    legend,
    memory_drift, migration, mind, musing,
    naming, narrative_direction, omens, pillar_chat, religion, rumor_interpret, skill_mastery, species_variant, summary,
    town_brain,
    diplomacy, laws, letters, noncore_nudge, institution_culture, nature_mind, reflection, rule_propose,
)
from hearthmind.llm import ontology as ontology_llm
from hearthmind.llm import self_tuning
from hearthmind.world.affordances import discover_combinations
from hearthmind.world.chemistry import discover_reactions
from hearthmind.world.materials import BUILDING_MATERIALS, building_affordances
from hearthmind.world.sigils import generate_sigil_svg
from hearthmind.world import memetics
from hearthmind.world import ontology
from hearthmind.world import reactions
from hearthmind.world.architecture_grammar import building_descriptor
from hearthmind.world.layout_grammar import settlement_layout_style
from hearthmind.world.dialect_grammar import drift_term
from hearthmind.world import emergence
from hearthmind.world import graph_algorithms
from hearthmind.world import legends
from hearthmind.cognition import attention
from hearthmind.cognition.pillar import make_message
from hearthmind.world.disasters import GOVERNOR_TUNING_BAND, WILDFIRE_CHANCE_PER_WEEK
from hearthmind.world.wildlife import MAX_SPECIES_VARIANTS_STORED, SpeciesVariant
from hearthmind.simulation.sandbox import run_counterfactual
from hearthmind.llm.client import build_llm_client, fetch_llama_server_metrics
from hearthmind.llm.review_diagnostics import context_reflects_any
from hearthmind.llm.json_schemas import schema_for_task
from hearthmind.llm.cognition import (
    RECENT_MEMORIES_IN_PROMPT, SURVIVAL_ENERGY_THRESHOLD, SURVIVAL_HUNGER_THRESHOLD, SYSTEM_PROMPT, build_prompt,
    fallback_goal, parse_goal,
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
    MIGRATION_CHANCE_PER_TICK,
    POPULATION_CRITICAL_THRESHOLD,
    VOICE_CONVERSATION_HISTORY_TURNS,
    VOICE_DIALOGUE_COOLDOWN_TICKS,
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
    cheapest_founding_cost,
    ERA_DESCRIPTIONS,
    FAMILY_FEUD_FESTIVAL_PENALTY,
    FESTIVAL_CHANCE_PER_MONTH,
    FESTIVAL_HUNGER_GATE,
    FOLKLORE_MAX_STORED,
    LEGENDS_MAX_STORED,
    GRANARY_CAPACITY,
    INVENTION_CHANCE_PER_SEASON,
    INVENTION_CURRENCY_THRESHOLD,
    INVENTION_KNOWLEDGE_MAX_TRACKED,
    INVENTION_MATERIALS_FRACTION,
    INVENTION_REDISCOVERY_CHANCE,
    INVENTION_SPECIALIZATION_CAP,
    INVENTION_SPECIALIZATION_STEP,
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
from hearthmind.settlement import institutions
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
    EMERGENCE_LOG_MAX_STORED,
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


def _resolve_llm_model_label(config: Config) -> str:
    """`Config.llm_model` is a hand-set label that has drifted from the
    actually-deployed model before (v1.3.15's own docstring records a
    live incident: an env-only model switch left `/diagnostics` reading
    the stale default). `scripts/run.sh`'s `MODEL_PATH` env var is what
    the llama-server process was ACTUALLY launched with — when set, it
    is ground truth and takes priority; `Config.llm_model` stays the
    fallback (Ollama backend, or `MODEL_PATH` unset in this process)."""
    model_path = os.environ.get("MODEL_PATH")
    if model_path:
        return os.path.splitext(os.path.basename(model_path))[0]
    return config.llm_model

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

PERSONAL_BELIEF_PICKS_PER_MONTH = 2
"""How many distinct agents Reflect() (`_maybe_schedule_personal_belief`)
picks per month — raised from a hardcoded 1 (live review-pack finding,
"improve context influence"). Still a fixed, population-independent
count, so this stays a settlement-scoped job under CLAUDE.md's LLM-
budget rule, not a per-agent-gated one; it just makes each core-cast
member's own_belief/semantic_memory/plan/lesson catch up meaningfully
faster than one pick a month ever could across an 18-member cast."""

RUMOR_NOVELTY_MIN_COUNT = 3
"""Live audit finding (P0.2b/c): before a dialogue's rumor is spread
and (if a core-cast listener heard it) retold via InterpretRumor(), it's
checked against `Settlement.top_topics(1)` — the rumor's OWN topic
label recorded a moment earlier is included in that ranking, so this
requires the leading topic to have already recurred at least this many
times before treating it as "the dominant, saturating topic" worth
damping; otherwise a settlement's very first-ever topic (trivially rank
1 of a near-empty ring) would get suppressed before it ever had a
chance to recur."""

GROUNDED_EVENT_PICK_WEIGHTS = (0.40, 0.25, 0.15, 0.12, 0.08)
"""Live audit finding (P1.1): dialogue's `grounded_event` used to be
`recent_events_diverse(...)[0]` unconditionally — the single most
recent diverse event, deterministically ignoring the other 4 fetched.
Still favors recency (weights sum to 1.0, strictly decreasing) but
gives every candidate in the top-5 a real chance."""

_EVENT_COORDINATE_RE = re.compile(r"\s*at \(\d+,\s*\d+\)")
"""Strips a literal "at (x, y)" from an event description before it
reaches a SPEAKING prompt (dialogue's `grounded_event`) — live audit
finding (P1.1): NPCs were reciting raw tile coordinates verbatim
("Remember the field at sixty, forty-five?"). Not applied to narrator-
voice prompts (chronicle/town_brain/beliefs), which read `recent_
events_diverse` directly and aren't first-person character speech."""

INTERPRET_RUMOR_MAX_PER_DAY = 3
"""Phase K's InterpretRumor() (docs/VISION-2026-07.md, "Knowledge &
Story") fires per listening event, not once a month like every other
settlement job — deliberately small, since this is real *added* call
volume on top of the existing daily budget, not a reuse of an existing
job slot. See `SimulationEngine._interpret_rumor_today` and
`_apply_pending_dialogue_results`."""

CORE_CAST_POPULATION_FRACTION = 0.4
"""docs/AUDIT-2026-07-20.md, P1.6: the fixed `Config.llm_core_cast_size`
(18) is an *input* pretending to be a *limit* — at a large population it
correctly caps LLM load, but at a small one (a live report cited pop
24) it means 75%+ of everyone is core-cast, and the queue saturates
anyway because real load is `cast x jobs-per-agent / latency`, not cast
alone. `_tick_once` now caps the seat count actually passed to
`Population.maintain_core_cast` at `min(configured_size, ceil(
population * this))`, so a small founding party gets a proportionally
small cast (and a genuine non-core crowd — "the crowd is what makes the
core cast legible") while a large settlement is unaffected once it
clears `configured_size / this` members. Scoped down from the audit's
full ask: this ships the fraction cap only, not throughput-derived
sizing or the Tier 1/2/3 + rotating-spotlight scheme — both flagged as
still-open follow-ups in the audit doc. `maintain_core_cast`'s own
no-eviction contract is unchanged: a shrinking cap only slows how fast
new seats fill, it never demotes an existing living member."""

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

DEEP_REASONING_NUM_PREDICT_MULT = 1.5
DEEP_REASONING_TEMPERATURE = 0.5
DEEP_REASONING_TIMEOUT_MULT = 1.5
"""v1.4.4, explicit user follow-up ("see if timeout is playing a role
here"): a real reasoning trace plus its answer is a proportionally
longer generation than a routine call — a live diagnostic showed
`personal_belief` (a `deep_reasoning=True` task) at p95 latency 146.7s
against an un-scaled 125s timeout (`Config.llm_timeout_seconds` (120) +
`jobs.py`'s 5s grace), meaning the socket timeout was cutting off calls
that were genuinely still generating, not stuck — misclassified as
`calls_errored` rather than `calls_timed_out` on top of that (see
`client.py`'s `LLMTimeout` docstring for the classification bug fixed
alongside this). Mirrors `DEEP_REASONING_NUM_PREDICT_MULT`'s own 1.5x
rather than inventing a second ratio — the timeout should grow in step
with the token budget it's meant to cover, not by an unrelated amount."""
"""Phase 3.A "reserved deeper reasoning" (docs/VISION-2026-07-21-
SELFEVOLVING.md), broadened v1.3.37 (explicit user directive: "move the
LLM from describing the world to thinking within the world," enable
reasoning for genuine judgment/planning/belief-revision tasks, leave
narration/routine-cognition tasks fast). `_schedule_llm_job(...,
deep_reasoning=True)` gets 1.5x `Config.llm_num_predict`'s configured
token budget and a lower, more deliberate temperature than `Config.
llm_temperature`'s routine-dialogue default, AND — new in v1.3.37 — a
real Nemotron 3 "detailed thinking on" reasoning trace (`reasoning =
deep_reasoning and task_schema is None` in `_runner()` below; never
combined with a schema, see `client.py`'s `_REASONING_ON_PROMPT`
docstring). Originally scoped to just the Innovation Layer's propose/
evolve/merge calls; now every task that is a genuine subjective
judgment call (personal/settlement belief revision, major life
decisions — migration/fission/founding/dispute, institutional/council
belief formation, town consciousness, cultural evolution — tradition/
religion/narrative direction/culture digest/institution culture/
faction naming/laws/self-modifying-rule proposals, invention/ontology
origination, and the Reflection/self-tuning system that lets the game
itself learn and improve) carries this flag — see each call site's own
comment for why. Routine/high-volume/narration tasks (dialogue,
rumor_interpret, dream, moment-to-moment cognition/goal decisions,
chronicle, documentary, naming, festival, caravan, town_brain's
one-sentence rationale, ...) deliberately stay off this path — they
either have a sensible deterministic answer already computed (town_
brain, era_branch, geography — v1.3.35) or genuinely don't benefit from
a reasoning trace (one-line narration, a single goal word). Every job
NOT passing `deep_reasoning=True` is completely unaffected by this
constant."""

PERSONAL_BELIEF_NUM_PREDICT_MULT = 3.0
"""Fallback-diagnosis follow-up (explicit user request: "see why the
reasoning-based personal_belief LLM calls are still falling back"):
`personal_belief` (`llm/beliefs.py`'s `PERSONAL_SYSTEM_PROMPT`) asks for
by far the largest JSON contract of any `deep_reasoning=True` job in
this codebase — 14 fields (subject/belief/confidence/revises/semantic_
memory/secret/life_digest/lesson_situation/lesson/plan_intent/plan_
horizon_days/plan_progress_note/long_term_goal, several with their own
multi-clause instructions), versus 2-4 fields for every other reasoning
job (dispute, tradition, invention, laws, ...). It ALSO can't use a
`json_schema` grammar (deliberately — see `PERSONAL_SYSTEM_PROMPT`'s own
"deliberately reasons rather than schema-constrains" note, v1.3.37),
so its `<think>` trace and its unusually large free-form answer share
the same flat `DEEP_REASONING_NUM_PREDICT_MULT` (1.5x) token budget
every simple 2-field reasoning job also gets. On a small model, a
genuine Nemotron 3 reasoning trace over this much required output can
plausibly consume the whole budget before the JSON answer is ever
written — `_UNCLOSED_THINK_RE` (client.py) then strips the entire
dangling `<think>` block, leaving nothing for `json.loads`, a `calls_
errored` fallback with no obvious cause in the aggregate counters alone
(this is exactly what the new per-fallback `raw_model_output`/
`fallback_reason` diagnostics above exist to make visible on a live
run). `_schedule_llm_job`'s new `num_predict_mult` param lets a job ask
for more headroom than the flat default without changing every other
reasoning task's budget; `personal_belief`'s own call site passes this
constant. Re-tune from a live `/diagnostics` reading of `last_llm_calls
.personal_belief.fallback_reason` the same way every other constant in
this file is tuned — this is a reasoned starting point (2x the fields
of a typical reasoning job, rounded up with margin for the trace
itself), not a live measurement."""

_PILLAR_MESSAGE_MAGNITUDE = {
    "disagreement": 0.9, "warning": 0.8, "discovery": 0.6, "theory": 0.55,
    "hypothesis": 0.5, "observation": 0.45, "question": 0.5, "request": 0.5,
}
"""B4 "Inter-pillar consciousness bus" (roadmap Stage III step 11): the
synthetic salience `_pillar_observe_turn` assigns an inbox message by
its `kind` (`cognition.pillar.MESSAGE_KINDS`), since a message has no
natural `magnitude` scalar the way an Emergence API observation does.
`disagreement`/`warning` outrank routine traffic so a genuinely
contentious or urgent message reliably wins a bounded `working_memory`
slot over an ordinary `observation`; every kind still competes fairly
against real Emergence observations of comparable magnitude, rather
than an unconditional bypass."""

MUSING_HISTORY_MAX = 60
"""Vision item 3.4: `World.musings` is daily-cadence texture (unlike
`reflection_notebook`, which is never pruned) — 60 entries is roughly
two months of daily lines, plenty for a UI scrollback, capped so a
years-long world doesn't accumulate thousands of short strings for no
consumer that reads more than the last handful."""

REFLECTION_ONTOLOGY_IMBALANCE_MIN_TOTAL = 6
REFLECTION_ONTOLOGY_IMBALANCE_RATIO = 3.0
"""Phase 5.B pattern-detection (docs/VISION-2026-07-21-SELFEVOLVING.md,
"Start the 5th item"): one of Reflection's deterministic cross-pillar
signals — if established `invented_concepts` total at least this many
(enough to be a real sample, not noise) and one category has at least
this many times more established concepts than the least-represented
category with at least one, that's a genuine imbalance across the four
pillars' ontology-origination worth a hypothesis (e.g. "the village
keeps inventing customs but the land almost never gives rise to
anything")."""

REFLECTION_CONFIDENCE_STEP = 0.08
REFLECTION_SUPPORTED_THRESHOLD = 0.85
REFLECTION_REJECTED_THRESHOLD = 0.15
"""5.B item 3, "existing OPEN hypotheses are re-evaluated against fresh
evidence every firing" — a small bounded nudge (same `bounded_random_
walk_step`-adjacent shape temperament/mood already use), never a fresh
LLM call. An open hypothesis whose pattern recurs this cycle gains
confidence; one whose pattern no longer clears its own threshold loses
some. Crossing `_SUPPORTED_THRESHOLD`/`_REJECTED_THRESHOLD` transitions
status — supported/rejected hypotheses stop being re-evaluated (the
notebook itself is never pruned, only status-transitioned)."""

GOVERNOR_DRIFT_MIN_SAMPLES = 5
GOVERNOR_DRIFT_RATIO = 2.0
"""Vision doc item 1.4's own worked example ("wildfires feel too rare
to matter"): `_detect_reflection_pattern`'s governor-drift branch reads
`World.wildfire_ignition_ticks` (needs at least `_MIN_SAMPLES` real
ignitions to say anything — a small sample is noise, not drift) and
compares the REALIZED mean tick-gap between consecutive ignitions
against the THEORETICAL mean gap `disasters.WILDFIRE_CHANCE_PER_WEEK`
implies. A ratio (realized/theoretical, or its inverse) clearing
`_DRIFT_RATIO` is treated as a genuine, sustained drift worth a
hypothesis — not RNG noise around the configured rate."""

_HIGHLIGHT_EMERGENCE_MAP: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # highlight kind -> (emergence.OBSERVATION_KINDS member, subsystem, pillars)
    "first_invention": ("opportunity", "innovation", ("innovation",)),
    "era_advance": ("opportunity", "settlement", ("village", "innovation")),
    "first_ritual": ("opportunity", "culture", ("village", "humans")),
    "first_religion": ("opportunity", "culture", ("village", "humans")),
    "family_feud": ("unexplained_shift", "population", ("humans", "village")),
    "successor_founded": ("unexplained_shift", "settlement", ("village",)),
    "extinction_near_miss": ("anomaly", "population", ("humans", "nature")),
    "population_anomaly": ("anomaly", "population", ("humans", "village")),
}
"""A22 Emergence API: every existing `_append_highlight` trigger site is
already a real, edge-triggered "something notable happened" detector —
this maps each highlight `kind` string onto an emergence observation's
`(kind, subsystem, pillars)` so `_append_highlight` can mirror into
`_append_emergence` for free instead of a parallel detection pass. Keys
must exactly match every `kind` string passed to `_append_highlight`
across the codebase; a highlight kind not listed here just doesn't get
an emergence mirror (see `_append_highlight`'s own docstring)."""

POPULATION_DENSITY_FISSION_AVOID_THRESHOLD = 0.75
"""A1 FieldGrid (docs/MASTERCHECKLIST-2026-07-22.md, roadmap Stage I
step 2): a candidate fission site in a region at or above this
`population_density` field reading is avoided when a less-crowded
alternative exists — the field's own "Feeds: settlement siting" line,
made real. Never a hard block (see `_choose_fission_site`'s fallback):
a map where every walkable region is this crowded still lets fission
proceed, just without the density preference."""

REFLECTION_COHERENCE_MIN_TOTAL = 10
REFLECTION_COHERENCE_ABANDONED_RATIO = 0.5
"""Vision doc item 5.3 ("Coherence/drift detection... the immune system
for long-run open-ended growth"): a genuine incoherence signal — most
of what the village has ever imagined never caught on. Requires at
least `_MIN_TOTAL` concepts ever registered (a small sample reads as
noise, same "enough real data" gate every other Reflection branch
uses) before the abandoned fraction is trusted as a real pattern, not
early-game normal churn."""

HYDROLOGY_DROUGHT_THRESHOLD = 0.15
"""A11 (roadmap Stage IV step 15): a tile below this `HydrologyField.
moisture` reading counts as "parched" for `_detect_hydrology_drought`.
Below `hydrology_field.MOISTURE_DEFAULT` (0.35) — a tile has to be
genuinely dried out, not just at its ordinary starting level."""

HYDROLOGY_DROUGHT_LAND_FRACTION = 0.5
"""A11: `_detect_hydrology_drought` only fires once at least this
fraction of ALL tiles (water tiles included in the denominator, but
they're always pinned above the threshold so they never count as
parched) read below `HYDROLOGY_DROUGHT_THRESHOLD` — a genuinely
widespread drought, not a dry patch in one corner of the map."""

SELF_TUNING_MIN_MAGNITUDE = 0.05
"""Vision doc items 1.4/2.4: a proposed nudge below this magnitude is
treated as "no real adjustment warranted" — recorded in `World.self_
tuning_actions` (so the same supported hypothesis isn't re-asked about
every year-cadence firing) but never sandbox-validated or applied,
since there is nothing to validate."""

TRIGGER_DROUGHT_HEAT_PRESSURE_THRESHOLD = 0.9
"""Vision doc item 1.2's `on_drought` edge-detection threshold — reused
from `world.disasters.HEATWAVE_PRESSURE_THRESHOLD` verbatim rather than
inventing a second number: disasters.py's own docstring already
documents heat_pressure crossing this point as the real UK drought-
comes-with-heatwave pattern (2018/2022), so "drought" riding the same
signal a real heatwave already uses is the honest choice, not a new
heuristic."""

TRIGGER_SURPLUS_FILL_THRESHOLD = 0.85
"""Vision doc item 1.2's `on_surplus` edge-detection threshold — a
settlement's granary fill fraction (`stored_food / capacity`) crossing
this reads as "the granary is genuinely close to overflowing," the
concrete condition the vision doc's own worked example ("when the
granary overflows, hold a feast") describes."""

PILLAR_COLD_START_BOUNDARIES = 2
"""How many season/year boundaries Nature/Reflection's B2 observe-then-
interpret cycle needs before its FIRST real belief/hypothesis can ever
form (one observe turn, one interpret turn) — see `Pillar.turns_
processed`'s docstring and `_pillar_cognition_status`. A live-report
follow-up ("not forming any hypothesis even after 13k ticks") found
this cold-start latency was previously invisible; this constant is the
same 2 the code already implicitly required, just now named."""

LEXICON_FISSION_DRIFT_COUNT = 2
"""A7 (roadmap Stage IV step 27), dialect domain: how many of the home
settlement's most recently coined terms a fissioning daughter
settlement inherits (each independently drift-mutated via `world.
dialect_grammar.drift_term`) — small and recent, not the whole
lexicon, so drift stays a a few distinguishing words, not a wholesale
re-derivation."""

CONCEPT_SPREAD_CHANCE_PER_TICK = 0.02
"""Per-tick, per-growing-concept roll driving `_maybe_spread_concepts`
— zero LLM cost, deliberately small (a concept's origin settlement
will see roughly one new adopter every ~50 ticks a candidate is
available) so adoption reads as gradual uptake, not an instant flip."""

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

MATERIALS_FLOW_WINDOW_TICKS = 200
"""Window size for `SimulationEngine._materials_level_history` (P3.4)
— a couple hundred ticks is short enough to read as "current trend,"
not a whole-run average, matching the audit's ask for a live materials
inflow/outflow signal rather than a historical chart."""

VOICE_NARRATIVE_INVENTOR_BONUS = 4000.0
"""`_voice_narrative_extra_scores`'s bonus for an agent who authored a
concept within `VOICE_NARRATIVE_INVENTOR_RECENT_TICKS` — the explicit
"an inventor" example — same magnitude family as `Population`'s
NARRATIVE_*_BONUS constants (computed here rather than in population.py
since it reads `World.invented_concepts`, which Population deliberately
doesn't reference)."""

VOICE_NARRATIVE_INVENTOR_RECENT_TICKS = 2000
"""How recently `InventedConcept.tick_invented` must fall for the
inventor bonus above to apply — roughly a season, so an invention from
years ago doesn't keep pulling its author into the spotlight forever."""

VOICE_NARRATIVE_COUNCIL_BONUS = 3500.0
"""`_voice_narrative_extra_scores`'s bonus for a living COUNCIL member —
the explicit "a council elder" example."""

DIALOGUE_BACKPRESSURE_FRACTION = 0.6
RUMOR_INTERPRET_BACKPRESSURE_FRACTION = 0.35
"""docs/AUDIT-2026-07-20.md, P1.2(ii): dialogue and rumor_interpret were
each commented as "the most expendable LLM job" but mechanically used
the identical bare `_current_backpressure_limit()` threshold as routine
cognition — no real rank existed at the consume stage, only the
priority-order suggested by comments. A live session measured cognition
(the only job that changes behavior) at 110 successful calls against
dialogue+rumor_interpret at 353+149 = 78% of the session's LLM spend.
These fractions make dialogue/rumor_interpret shed load *before*
cognition does as backlog climbs toward the shared limit — cognition's
own gate (`_schedule_due_cognition`) is left at the full, unscaled
limit so it's rationed last, not to a stricter threshold of its own.
Ordered rumor_interpret < dialogue < cognition, matching the audit's
stated priority (cognition > dialogue > rumor_interpret); P0.2(b)/(c)'s
novelty gating already trims rumor_interpret's raw call volume
separately — this fraction only changes which job yields first when
the queue is genuinely saturated.

Lowered further from 0.75/0.5 in v1.3.37 (explicit user directive:
"allocate more freed-up LLM budget to tasks that require sentience and
intelligence"): that pass gave roughly twenty settlement/institution/
agent judgment tasks a real reasoning trace (`deep_reasoning=True`,
1.5x token budget each), so pure narration — dialogue lines,
distorted-retelling — should yield its queue slot even earlier under
real pressure, leaving more of the shared backlog limit for jobs that
actually think rather than describe."""

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

LLM_PRESSURE_SLOWDOWN_START_RATIO = 0.75
LLM_PRESSURE_PAUSE_RATIO = 2.0

REASONING_LOAD_SHED_RATIO = 0.9
"""v1.4.3, explicit user directive: reasoning ("detailed thinking on",
a real `<think>` trace) genuinely costs several times a routine call's
latency — worth it for a `deep_reasoning=True` job's own judgment
quality, not worth it while the LLM queue is already struggling to
keep up. A `deep_reasoning` job whose `llm_pressure_ratio()` is at/
above this ratio silently runs WITHOUT a reasoning trace this one call
(same fast direct-answer path as every routine task) rather than
deferring or dropping — the decision still gets made, just without the
extra trace, shedding load exactly where it's most expensive. Sized
just under `LLM_PRESSURE_SLOWDOWN_START_RATIO`'s own pacing kicking in
(0.75) is too eager (would strip reasoning from routine minor load);
just under `LLM_PRESSURE_PAUSE_RATIO` (2.0) is too late (the queue is
already stalling by then) — 0.9 sheds the single most expensive job
class right as the queue starts genuinely backing up, before pacing/
pause even engage."""
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
Below `LLM_PRESSURE_SLOWDOWN_START_RATIO` (0.75, i.e. comfortably under
the adaptive limit): no change, ticks run at the configured/user-
selected speed. **Lowered 1.0 -> 0.75 in v1.3.14** after a live
diagnostic on a much slower model (gemma-4-e4b, ~2.6 tok/s, per-call
p50/p95 latency 47s/77s) exposed a blind spot in the original 1.0
start: under *sustained* (not bursty) saturation the backlog sits
pinned right at the adaptive limit — `llm_pressure_ratio` reads
exactly 1.0, `llm_pressure_paused` false — because excess jobs are
cleanly *dropped* at the gate rather than queued past the limit, so the
ratio structurally can't climb above ~1.0 to trip a start of 1.0. That
run showed the symptom precisely: ratio 1.0, not paused, yet 11,891
backpressure drops against 760 attempted calls — the sim sprinting at
~4.5 ticks/s while each cognition call took 47-100s, so nearly every
scheduling opportunity was born doomed (exactly the failure the pacing
mechanism exists to prevent, just at a saturation shape the 1.0 start
didn't catch). A 0.75 start means a backlog pinned at the limit now
reads as ~1.0/0.75 into the slowdown band and stretches the tick gap
~2x, halving how fast agents become cognition-due per real second —
draining the wasteful churn and letting more calls land on fresh state.
Still well clear of a healthy fast-model run (backlog ~2 against limit
6 = ratio 0.33, no slowdown), so this only engages under real
saturation, never normal operation. Between START_RATIO and `LLM_
PRESSURE_PAUSE_RATIO` (2.0): the
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

LLM_PRESSURE_SPEEDUP_START_RATIO = 0.15
LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER = 0.4
"""Explicit user directive: "the adaptive slowing of the simulation
should also adaptively speed up the simulation when LLM load is low and
system is sitting idle." Everything above only ever stretches the
real-time gap between ticks (multiplier >= 1.0) — a genuinely idle
queue (a fresh world, a quiet stretch with few core-cast agents due, or
`llm_enabled=False` entirely) always ran at exactly the user's
configured/selected speed, leaving real spare LLM/CPU capacity unused
even though nothing was competing for it. `_llm_pressure_interval_
multiplier()` now mirrors the slowdown shape on the low side too:
below `LLM_PRESSURE_SPEEDUP_START_RATIO` (0.15 — comfortably under
`LLM_PRESSURE_SLOWDOWN_START_RATIO`'s own 0.75 floor, so the two bands
never overlap and there's a real "just right" zone at ratio 0.15-0.75
that stays at exactly 1.0x, matching a normal healthy-but-not-idle
run), the multiplier scales linearly DOWN to `LLM_PRESSURE_MIN_
SPEEDUP_MULTIPLIER` (0.4, i.e. up to 2.5x faster ticks) as the ratio
approaches 0. Faster ticks mean agents become cognition/dialogue-due
sooner in real time (staggered-daily eligibility is tick-count-based,
same mechanism the slowdown side already leans on in reverse) — this
is what actually converts idle LLM capacity into more calls per real
second, not just a cosmetic faster clock. Bounded the same way the
slowdown side is: `run_forever`'s own `max(0.05, ...)` floor on the
final interval is the hard backstop regardless of how this multiplier
or the user's own speed slider compose; a sufficiently pathological
combination (e.g. 8x user speed already selected) still can't produce
an unsafe interval. 0.4 (not lower) is deliberately conservative — a
tick's own compute cost is negligible (~1ms, see the "C/C++ port"
evaluation in this file's audit history) so the real bound on how much
faster is safe is untested territory; 2.5x is a real, noticeable
speedup without assuming the whole pacing model generalizes further
than it's been verified to. Purely a function of `llm_pressure_ratio()`
— no separate "is the system idle" signal needed, since a genuinely
idle LLM queue (including `llm_enabled=False`, where `llm_pressure_
ratio()` is always exactly 0.0) already reads as ratio 0 by
construction."""

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
    "consciousness": 24, "memory_drift": 21, "noncore_nudge": 9, "legend_detection": 18,
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
    "chronicle", "folklore", "legend_detection", "town_brain", "beliefs", "personal_belief",
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
    "institution_culture", "invention", "ontology_proposal", "ontology_evolution",
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

**`invention` was excluded for a while too**, for a documented but
ultimately wrong reason: it rolls its own per-occurrence RNG chance
(`INVENTION_CHANCE_PER_SEASON` via `_namespaced_roll(..., "invention_
roll")`) AFTER the boundary/prosperity gate, and widening the window
naively would re-roll that chance on every day of the window,
inflating the effective per-season probability. Fixed by having
`_maybe_schedule_invention` call `_mark_season_year_resolved` the
instant its OWN backpressure check clears — same spot every other job
in this set already marks resolved — which means the roll still only
ever happens once per season (a later day in the window sees the
season already marked resolved and never re-enters), so retry-safety
came for free once the mark moved before the roll instead of after a
successful schedule. A live 400-population world with heavy
backpressure (598 dropped calls) went an entire multi-season run with
zero inventions — `invention`'s single-exact-tick gate meant its ONE
seasonal roll per settlement was disproportionately likely to fall on
a backpressured tick, especially since season_end is also when five
OTHER settlement jobs fire and compete for the same backpressure slot.
See `_season_year_gate`/`_mark_season_year_resolved`."""

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
            model_name_provider=lambda: _resolve_llm_model_label(config),
            hearthmind_version_provider=lambda: __version__,
            seed_provider=lambda: config.seed,
            generation_config_provider=lambda: _generation_config_snapshot(config),
            adapter_name_provider=lambda: config.llm_adapter_name,
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
        self._materials_critical_flagged: set[int] = set()
        """A22 Emergence API: settlement ids currently below `cheapest_
        founding_cost()` — edge-triggered, same shape as `_prev_
        population_total`, so `_detect_settlement_bottlenecks` emits one
        `bottleneck` observation on the falling edge and one implicit
        recovery (silent — no "opportunity" spam) on the rising edge,
        not a fresh observation every single day a settlement stays
        materials-poor. Never persisted — a restart re-baselines from
        the first post-restart reading, same reasoning as `_prev_
        population_total`."""
        self._hydrology_drought_flagged: bool = False
        """A11 (roadmap Stage IV step 15): edge-trigger flag for
        `_detect_hydrology_drought`, same "one observation on the
        falling edge, silent recovery on the rising edge" shape as
        `_materials_critical_flagged`. World-scoped (not per-
        settlement) since the moisture field is map-wide, not tied to
        settlement boundaries. Never persisted — same re-baseline-on-
        restart reasoning as every other edge-trigger flag here."""
        self._monthly_job_scheduled_month: dict[str, int] = {}
        """job name -> absolute month ordinal (year * months_per_year +
        month_index) it last got past its own backpressure check — lets
        `_monthly_gate` retry on the next couple of days if a job's first
        scheduled day was backpressured, instead of silently waiting a
        full month. See MONTHLY_JOB_RETRY_WINDOW_DAYS and `_mark_monthly_
        resolved`."""
        self._pending_mind_agent_ids: list[int] = []
        """FIFO queue of core-cast agent ids whose one-time `_author_
        minds` LLM call lost the backpressure roll — retried by `_maybe_
        retry_mind_authoring`, see its docstring. Never persisted
        (snapshot round-trip just re-derives the fallback text was never
        replaced, same as any other in-flight-job queue in this class);
        a world resumed mid-backlog simply leaves those agents on the
        fallback template until the next live retry, no worse than
        before this fix existed."""
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
        self._recent_line_tails: deque[tuple[str, str]] = deque(maxlen=dialogue.TIC_SPREAD_WINDOW)
        """(tail_fingerprint, speaker_name) history feeding P3.2's
        spreading-tic detector — see `dialogue.is_spreading_tic`'s
        docstring."""
        self._prev_drought_state: dict[int, bool] = {}
        self._prev_surplus_state: dict[int, bool] = {}
        """settlement_id -> previous-tick boolean, feeding vision doc
        item 1.2's `on_drought`/`on_surplus` edge detection (see
        `_maybe_tick_trigger_state_edges`) — transient, non-persisted
        (same precedent as `_recent_line_tails`); re-derived cleanly on
        restart since the worst case is one missed/extra edge, not a
        correctness issue."""
        self._composite_reaction_last_fired: dict[tuple[int, str], int] = {}
        """(settlement_id, reaction_name) -> last-fired tick, A18's own
        cooldown tracker (`_maybe_tick_composite_reactions`) — same
        transient, re-derivable-on-restart shape as `_prev_drought_
        state` above, just keyed on a composite instead of a single
        edge."""
        self._materials_level_history: deque[tuple[int, float]] = deque(maxlen=MATERIALS_FLOW_WINDOW_TICKS)
        """(tick, total materials across all settlements) sampled once
        per tick — P3.4 (docs/AUDIT-2026-07-20.md): "materials inflow/
        outflow" was one of four numbers the audit had to compute by
        hand from raw events; this is the cheap live equivalent (a
        simple level delta over a bounded window), same deque-sampling
        shape `_tick_durations_ms` already uses. See `materials_flow_
        per_tick` in `_diagnostics_snapshot`."""
        self._cognition_context_stats = {"scored": 0, "any_reflected": 0}
        """Incremental (not archive-rescanning) counters feeding P3.4's
        live "per-thread context-reflection rate" — updated inline in
        `_record_llm_debug` for the `cognition` task only (the one task
        `llm/review_diagnostics.py`'s own Context Influence section
        scores), same "maintain a running count, never re-scan"
        discipline the training recorder's own v1.1.0 stats pass
        established. Deliberately a coarser any-vs-none live signal,
        not the export's full per-field breakdown — that stays an
        archive-analysis job, this is just the dev-console's canary."""
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
                world.terrain, world.config.width, world.config.height,
                mining_scars=world.mining_scars, disaster_scars=world.disaster_scars,
                ritual_activity=world.ritual_activity, ruin_scars=world.ruin_scars,
                moisture=world.hydrology_field.moisture, soil_fertility=world.farms.soil_fertility,
                population_density=world.fields.ensure_field("population_density"),
            )
            self._broadcaster.set_diagnostics_provider(self.full_diagnostics)
            self._broadcaster.set_knowledge_tree_provider(self.world.knowledge_tree)
            self._broadcaster.set_causal_threads_provider(self.world.causal_threads_list)
            self._broadcaster.set_emergence_log_provider(self.world.emergence_log_recent)

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
        """How much longer (or shorter) than normal `run_forever` should
        wait before the next tick, given current LLM backlog pressure —
        symmetric around a flat 1.0x "just right" zone. Above `LLM_
        PRESSURE_SLOWDOWN_START_RATIO`: scales linearly up to `LLM_
        PRESSURE_MAX_SLOWDOWN` as pressure approaches `LLM_PRESSURE_
        PAUSE_RATIO` (at/beyond which `llm_pressure_paused()` takes over
        and ticking stops outright, making this multiplier moot). Below
        `LLM_PRESSURE_SPEEDUP_START_RATIO`: scales linearly DOWN to
        `LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER` as pressure approaches 0
        (a genuinely idle queue) — see that constant's docstring. Between
        the two thresholds (0.15-0.75 by default): exactly 1.0, the
        normal healthy-load rate."""
        ratio = self.llm_pressure_ratio()
        if ratio > LLM_PRESSURE_SLOWDOWN_START_RATIO:
            span = LLM_PRESSURE_PAUSE_RATIO - LLM_PRESSURE_SLOWDOWN_START_RATIO
            if span <= 0:
                return 1.0
            progress = min(1.0, (ratio - LLM_PRESSURE_SLOWDOWN_START_RATIO) / span)
            return 1.0 + progress * (LLM_PRESSURE_MAX_SLOWDOWN - 1.0)
        if ratio < LLM_PRESSURE_SPEEDUP_START_RATIO:
            if LLM_PRESSURE_SPEEDUP_START_RATIO <= 0:
                return 1.0
            progress = min(1.0, 1.0 - ratio / LLM_PRESSURE_SPEEDUP_START_RATIO)
            return 1.0 - progress * (1.0 - LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER)
        return 1.0

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
        deep_reasoning: bool = False, num_predict_mult: float | None = None,
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
        ambient texture, not crucial cognition.

        `deep_reasoning=True` (Phase 3.A, "reserved deeper reasoning" —
        docs/VISION-2026-07-21-SELFEVOLVING.md): reserved for a job that
        genuinely warrants more tokens/lower randomness than routine
        dialogue/cognition — currently only the Innovation Layer's
        propose/evolve/merge calls. Applies `DEEP_REASONING_NUM_
        PREDICT_MULT`/`DEEP_REASONING_TEMPERATURE` on top of `Config`'s
        normal `llm_num_predict`/`llm_temperature`, per-call only —
        every other job's generation config is unaffected."""
        # Daily-ceiling gate (v0.70.0): once the day's Ollama budget is
        # spent, a non-critical settlement job resolves via its
        # deterministic fallback inline rather than scheduling a real
        # call — the in-fiction effect still happens, only the model
        # authorship is skipped. A CRITICAL job instead DEFERS: it makes
        # no change this cadence rather than fabricating cognition, and
        # the deferral is counted for diagnosis (Constitution §3/§7).
        if not self._consume_llm_budget():
            budget_diag = {
                "fallback_reason": "daily_llm_budget_exhausted", "raw_model_output": None,
                "parsed_json": None, "validation_errors": [],
            }
            if critical:
                self._cognition_runner.calls_deferred_critical += 1
                self._record_llm_debug(
                    name, prompt, fallback, True,
                    structured_input=structured_input, npc_ids=npc_ids, settlement=settlement,
                    outcome={"status": "deferred_critical", "apply_failed": False}, diag=budget_diag,
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
                outcome={"status": "fallback_used", "apply_failed": apply_failed}, diag=budget_diag,
            )
            return

        async def _runner() -> None:
            call_start = time.perf_counter()
            num_predict_override, temperature_override = None, None
            task_schema = schema_for_task(name)
            effective_mult = num_predict_mult if num_predict_mult is not None else DEEP_REASONING_NUM_PREDICT_MULT
            if deep_reasoning:
                base_num_predict = self.world.config.llm_num_predict
                if base_num_predict is not None:
                    num_predict_override = int(base_num_predict * effective_mult)
                temperature_override = DEEP_REASONING_TEMPERATURE
            # Nemotron 3 "detailed thinking on": reserved for the same
            # deep_reasoning jobs that already get extra tokens/lower
            # temperature — never combined with a schema-constrained
            # call (see client.py's _REASONING_ON_PROMPT docstring for
            # why a grammar and a preceding <think> block conflict).
            # Also shed under queue pressure (REASONING_LOAD_SHED_RATIO,
            # v1.4.3, explicit user directive) — reasoning is the single
            # most expensive thing a call can ask for, so it's the first
            # thing given up once the backlog is genuinely struggling;
            # the job still runs and still decides, just without a trace
            # this one call, same as every routine task.
            reasoning = (
                deep_reasoning and task_schema is None
                and self.llm_pressure_ratio() < REASONING_LOAD_SHED_RATIO
            )
            # v1.4.4: a reasoning call legitimately generates more tokens
            # (a <think> trace plus the answer) and so legitimately takes
            # longer — scale the request-level timeout the same way
            # num_predict was already scaled, so the socket timeout
            # doesn't cut off a call that's genuinely still working. A
            # live diagnostic showed reasoning-task p95 latency (146.7s)
            # exceeding the un-scaled timeout (125s) outright. Scaled by
            # `effective_mult` (not the flat `DEEP_REASONING_TIMEOUT_
            # MULT`) so a job like `personal_belief` that requested extra
            # token headroom via `num_predict_mult` also gets a
            # proportionally longer socket timeout to actually use it —
            # see `PERSONAL_BELIEF_NUM_PREDICT_MULT`'s docstring.
            timeout_override = None
            if reasoning:
                base_timeout = self.world.config.llm_timeout_seconds
                if base_timeout is not None:
                    timeout_override = base_timeout * DEEP_REASONING_TIMEOUT_MULT * (effective_mult / DEEP_REASONING_NUM_PREDICT_MULT)
            result, used_fallback, raw_completion, diag = await self._cognition_runner.run(
                prompt, system, fallback=lambda: fallback, json_schema=task_schema,
                num_predict_override=num_predict_override, temperature_override=temperature_override,
                reasoning=reasoning, timeout_override=timeout_override,
            )
            if used_fallback:
                diag = dict(diag, fallback_result=fallback)
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
                reasoning=reasoning, diag=diag,
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
        ("_maybe_retry_mind_authoring", _JOB_NO_ARGS),
        ("_maybe_schedule_naming", _JOB_NO_ARGS),
        ("_maybe_schedule_chronicle", _JOB_EVENTS_SEASON),
        ("_maybe_schedule_documentary", _JOB_EVENTS),
        ("_maybe_schedule_tradition", _JOB_EVENTS),
        ("_maybe_schedule_folklore", _JOB_EVENTS),
        ("_maybe_schedule_legend_detection", _JOB_EVENTS),
        ("_maybe_schedule_invention", _JOB_EVENTS),
        ("_maybe_schedule_ontology_proposal", _JOB_EVENTS),
        ("_maybe_schedule_ontology_evolution", _JOB_EVENTS),
        ("_maybe_schedule_composite_entity", _JOB_EVENTS),
        ("_maybe_schedule_nature_mind", _JOB_EVENTS),
        ("_maybe_schedule_species_variant", _JOB_EVENTS),
        ("_maybe_spread_concepts", _JOB_NO_ARGS),
        ("_apply_trigger_rules_from_life_events", _JOB_NO_ARGS),
        ("_maybe_tick_trigger_state_edges", _JOB_NO_ARGS),
        ("_maybe_tick_composite_reactions", _JOB_NO_ARGS),
        ("_maybe_schedule_rule_proposal", _JOB_EVENTS),
        ("_maybe_schedule_festival", _JOB_EVENTS),
        ("_maybe_schedule_religion", _JOB_EVENTS),
        ("_maybe_schedule_narrative_direction", _JOB_EVENTS),
        ("_maybe_schedule_culture_digest", _JOB_EVENTS),
        ("_maybe_schedule_consciousness", _JOB_EVENTS),
        ("_maybe_schedule_reflection", _JOB_EVENTS),
        ("_maybe_schedule_self_tuning", _JOB_EVENTS),
        ("_maybe_schedule_musing", _JOB_EVENTS),
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
        ("_maybe_schedule_migration_decision", _JOB_NO_ARGS),
        ("_maybe_schedule_diplomacy", _JOB_EVENTS),
        ("_maybe_schedule_laws", _JOB_EVENTS),
        ("_maybe_schedule_noncore_nudge", _JOB_EVENTS),
        ("_maybe_schedule_letter", _JOB_EVENTS),
        ("_maybe_schedule_institution_culture", _JOB_EVENTS),
        ("_schedule_due_cognition", _JOB_NO_ARGS),
        ("_schedule_due_dialogue", _JOB_NO_ARGS),
        ("_schedule_voice_dialogue", _JOB_NO_ARGS),
    )

    def _tick_once(self) -> None:
        tick_start = time.perf_counter()
        self._reserved_this_tick = 0  # see its docstring: fresh reservation count each tick
        self._apply_pending_cognition_results()
        self._apply_pending_dialogue_results()
        self._apply_pending_interventions()

        previous_season = self.world.clock.season
        events = self.world.tick()
        total_materials = sum(s.materials for s in self.world.settlements)
        self._materials_level_history.append((self.world.clock.tick_count, total_materials))
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
        if "season_end" in events:
            self._detect_social_hub()
        if "week_end" in events:
            # A11 (roadmap Stage IV step 15): riding the same week_end
            # boundary World.tick's own _tick_disasters just updated
            # hydrology_field on, so this always reads this week's
            # fresh moisture reading, never a stale one.
            self._detect_hydrology_drought()
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
        # dialogue scheduling reads it this tick (v0.70.0). P1.6: cap the
        # configured cast size by a population fraction so a small
        # village doesn't drive 75%+ of everyone through LLM cognition —
        # see CORE_CAST_POPULATION_FRACTION's docstring.
        target_cast_size = min(
            self.config.llm_core_cast_size,
            math.ceil(len(self.world.population.agents) * CORE_CAST_POPULATION_FRACTION),
        )
        newly_core = self.world.population.maintain_core_cast(target_cast_size)
        if newly_core:
            self._author_minds(newly_core)
        # Explicit user directive: exactly one fixed core-cast pair
        # carries all LLM dialogue; every other pair (including former
        # core-core ones) is now deterministic-only. Cheap every-tick
        # check (a no-op unless the pair actually changed) — see
        # Population.maintain_voice_pair's docstring for the rotation
        # rule on death. "Shifting protagonists rather than permanent
        # stars" (explicit follow-up directive): also force a fresh
        # narrative-significance reselection on a real in-game week
        # boundary, not just on death.
        new_voice_pair = self.world.population.maintain_voice_pair(
            self.world.clock.tick_count, week_rotation="week_end" in events,
            extra_scores=self._voice_narrative_extra_scores(),
        )
        if new_voice_pair is not None:
            a = self.world.population.get(new_voice_pair[0])
            b = self.world.population.get(new_voice_pair[1])
            if a is not None and b is not None:
                self._log("voice_pair_change", f"{a.name} and {b.name} now carry the village's voice.")
                # B7 "Humans collective consciousness + coordinator"
                # (roadmap Stage III step 14): the voice-pair machinery
                # (dramatically-salient individuals, narrative-
                # significance-selected) previously ran entirely
                # separate from the collective mind that's supposed to
                # be aware of them — this was the real "fold in the
                # voice-pair machinery" gap, not a missing mechanism.
                # `self_model` is Humans' own persistent record of who
                # it currently is; an Emergence API observation also
                # makes the rotation reach its next real `observe` turn
                # as salient perceived context, same channel every
                # other pillar's genuine news already uses.
                self.world.humans_pillar.self_model["current_protagonists"] = [a.name, b.name]
                self._append_emergence(
                    "opportunity", "humans",
                    f"{a.name} and {b.name} now carry the village's voice.",
                    pillars=("humans",), magnitude=0.6,
                    data={"agent_ids": [a.id, b.id]},
                )
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
        # Root-cause fix for a live diagnostics finding: `_reserved_this_
        # tick` was only ever cleared at the TOP of the next `_tick_once`
        # (see its docstring — designed purely to close a same-tick
        # staleness window for scheduling calls within ONE synchronous
        # tick). LLM-pressure pacing (v0.82.0) can pause ticking entirely
        # for extended real time while backlog drains; while paused,
        # `_tick_once` never runs, so this tick's reservation count never
        # clears — but by the time the NEXT `llm_pressure_paused()` check
        # runs (after `run_forever` has yielded to the event loop at least
        # once), every job reserved this tick has already had the chance
        # to actually start and is now ALSO counted by `CognitionRunner.
        # backlog`. The result: `_effective_backlog()` double-counted the
        # same in-flight batch (backlog + a stale reservation of the same
        # jobs) for the entire pause window, inflating `llm_pressure_
        # ratio()` roughly 2x and keeping the sim paused well past the
        # point its real backlog had already drained enough to resume —
        # confirmed live: `llm_backlog_effective` 20 = `background_tasks`
        # 10 + `llm_backlog_reserved_this_tick` 10, the same 10 jobs
        # counted twice. Clearing it here (once this tick's own scheduling
        # work is done, not just at the next tick's top) removes the
        # double-count without reopening the original same-tick gap the
        # v0.81.0 fix closed.
        self._reserved_this_tick = 0
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
            # Root-cause fix for a live review-pack audit finding: past
            # SURVIVAL_HUNGER_THRESHOLD/SURVIVAL_ENERGY_THRESHOLD the
            # prompt already tells the model "there's no real choice
            # about it" and asks it to echo that forced priority back as
            # 'goal' — but SYSTEM_PROMPT never actually defines what
            # 'forage' means (only 'gather'/'wander'/'seek_person' are
            # defined), so a small model reliably narrates hunger in
            # 'reason' while still returning 'gather' for 'goal' (a
            # review pack showed this on 328/328 sampled hunger>0.6
            # examples). Below CRITICAL_HUNGER_THRESHOLD the movement
            # layer's critically_hungry override doesn't kick in, so
            # this genuinely steered agents toward materials instead of
            # food while starving. Same "objective survival decisions
            # aren't a real LLM choice" reasoning as v0.87.15 — enforce
            # it server-side instead of trusting the model to self-report
            # correctly; 'reason' (the model's real contribution) is
            # kept untouched either way.
            agent = self.world.population.get(agent_id)
            if agent is not None:
                if agent.hunger > SURVIVAL_HUNGER_THRESHOLD:
                    goal = AgentGoal.FORAGE
                elif agent.energy < SURVIVAL_ENERGY_THRESHOLD:
                    goal = AgentGoal.REST
            self.world.population.apply_goal(agent_id, goal, reason, seek_candidate_id)
            # Phase 1.C "self-evolving world" (docs/VISION-2026-07-21-
            # SELFEVOLVING.md): tally every REAL per-agent goal
            # decision — the single choke point every LLM-decided or
            # forced-survival goal passes through — so town_brain can
            # cite actual NPC behavior, not just settlement-level
            # numbers. Deliberately not incremented for the player-
            # intervention or forced-surveyor-EXPLORE call sites (see
            # Settlement.recent_goal_counts' docstring) — neither is a
            # real NPC decision.
            if agent is not None:
                home = self._settlement_by_id(agent.settlement_id)
                if home is not None:
                    counts = home.recent_goal_counts
                    counts[goal.value] = counts.get(goal.value, 0) + 1
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
            # Live audit finding (P0.3): a settlement whose stockpile
            # can't even afford its cheapest building kind gets real
            # GATHER urgency here (both the fallback path most agents
            # take and the live-LLM prompt's grounding line below) —
            # see `fallback_goal`'s/`build_prompt`'s `materials_critical`
            # docstrings for the full root-cause writeup.
            agent_home = self._settlement_by_id(agent.settlement_id)
            materials_critical = agent_home is not None and agent_home.materials < cheapest_founding_cost()
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
            # P1.3 (docs/AUDIT-2026-07-20.md, explicit user direction to
            # implement it): past SURVIVAL_HUNGER_THRESHOLD/SURVIVAL_
            # ENERGY_THRESHOLD the goal isn't a real choice — cognition.
            # build_prompt's own "closing" text already says so verbatim
            # ("there's no real choice about it") — so a full LLM call
            # in this state buys only in-character flavor text on a
            # foregone decision. Reverses the v1.3.7 flag: that earlier
            # note preserved crisis reasoning specifically because a
            # hunger emergency "deserves the LLM's actual reasoning";
            # this pass's explicit user instruction supersedes it.
            # `fallback_goal` below is unchanged in what GOAL it picks
            # here (it already enforces the identical thresholds) — the
            # only change is skipping the LLM call for the reason text,
            # which now comes from FORCED_HUNGER_REASON_POOL/FORCED_
            # ENERGY_REASON_POOL instead. Real open decisions (is_
            # triggered by grief, or `_is_significant_moment`) are
            # unaffected.
            forced = agent.hunger > SURVIVAL_HUNGER_THRESHOLD or agent.energy < SURVIVAL_ENERGY_THRESHOLD
            use_llm = (
                self._cognition_runner.enabled
                and population.is_core(agent.id)
                and self._llm_calls_today < self.config.llm_max_calls_per_day
                and not forced
                and (is_triggered or self._is_significant_moment(agent))
            )
            if not use_llm:
                plan_intent = agent.plan["intent"] if agent.plan else ""
                self._pending_goal_results[agent.id] = (
                    self.world.clock.tick_count,
                    fallback_goal(
                        agent.hunger, agent.energy, agent.id, dict(agent.traits), dict(agent.emotions), plan_intent,
                        materials_critical,
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
            core_memory_text = self._pick_core_memory(agent)
            prophecy_obj = home.prophecy if home.prophecy and home.prophecy.get("status") == "pending" else None
            prompt = build_prompt(
                agent, self.world.clock.season, self.world.weather.describe(),
                settlement_name=home.name, latest_tradition=latest_tradition,
                colocated_names=colocated_names, nearest_food_steps=food_steps,
                beliefs_about=beliefs_about, own_belief=own_belief,
                semantic_memory=semantic_memory, mind_text=agent.mind,
                needs_repair=needs_repair, life_digest=agent.life_digest,
                materials_critical=materials_critical,
                lesson=lesson, seek_candidate=seek_prompt_hint,
                institution_objective=institution_objective, plan=agent.plan,
                core_memory=core_memory_text, prophecy=prophecy_obj,
                long_term_goal=agent.long_term_goal,
            )
            hunger_snapshot, energy_snapshot = agent.hunger, agent.energy
            traits_snapshot = dict(agent.traits)
            emotions_snapshot = dict(agent.emotions)
            plan_intent_snapshot = agent.plan["intent"] if agent.plan else ""
            # "Context Influence" diagnostics (llm/review_diagnostics.py):
            # the actual TEXT of every optional context thread offered in
            # this prompt, not just whether it was present — lets a later
            # diagnostics pass check whether the model's own `reason`
            # shares vocabulary with more than one of these, i.e. actually
            # synthesized what it was given rather than reacting to a
            # single obvious cue. Retrieved-memory text itself is computed
            # inside `build_prompt` and isn't duplicated here (would cost
            # a second retrieval pass) — a known scope trim, not an
            # oversight.
            context_snapshot = {
                "beliefs_about": list(beliefs_about) if beliefs_about else [],
                "own_belief": own_belief,
                "semantic_memory": semantic_memory,
                "life_digest": agent.life_digest,
                "mind_text": agent.mind,
                "lesson": lesson,
                "seek_reason": seek_prompt_hint[1] if seek_prompt_hint else "",
                "institution_objective": institution_objective,
                "plan_intent": plan_intent_snapshot,
                "core_memory": core_memory_text,
                "prophecy_text": prophecy_obj["text"] if prophecy_obj else "",
                "latest_tradition": latest_tradition,
            }
            task = asyncio.create_task(
                self._run_cognition(
                    agent.id, prompt, hunger_snapshot, energy_snapshot, traits_snapshot, emotions_snapshot,
                    seek_candidate_id, plan_intent_snapshot, context_snapshot, materials_critical,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_cognition(
        self, agent_id: int, prompt: str, hunger: float, energy: float, traits: dict, emotions: dict,
        seek_candidate_id: int | None = None, plan_intent: str = "",
        context_snapshot: dict | None = None, materials_critical: bool = False,
    ) -> None:
        scheduled_tick = self.world.clock.tick_count
        call_start = time.perf_counter()
        try:
            fallback_dict = fallback_goal(
                hunger, energy, agent_id, traits, emotions, plan_intent, materials_critical,
            )
            result, used_fallback, raw_completion, diag = await self._cognition_runner.run(
                prompt, SYSTEM_PROMPT, fallback=lambda: fallback_dict,
                json_schema=schema_for_task("cognition"),
            )
            if used_fallback:
                diag = dict(diag, fallback_result=fallback_dict)
            self._record_llm_debug(
                "cognition", prompt, result, used_fallback, (time.perf_counter() - call_start) * 1000,
                system_prompt=SYSTEM_PROMPT, raw_completion=raw_completion, npc_ids=[agent_id],
                structured_input={
                    "agent_id": agent_id, "hunger": hunger, "energy": energy,
                    "traits": traits, "emotions": emotions,
                    "seek_candidate_id": seek_candidate_id, "plan_intent": plan_intent,
                    **(context_snapshot or {}),
                },
                # Cognition never applies a fabricated goal on fallback
                # (Constitution §3/§7) — see the used_fallback branch just
                # below, which is where "deferred_critical" is decided.
                outcome={"status": "deferred_critical" if used_fallback else "queued_pending_apply"},
                diag=diag,
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
                promise=parsed.get("promise", ""), debt_delta=parsed.get("debt_delta", 0.0),
                secret_revealed=parsed.get("secret_revealed", False),
                misunderstanding=parsed.get("misunderstanding", False),
                goal_change=parsed.get("goal_change", False),
            )
            if applied is None:
                continue
            agent_a, agent_b, surfaced = applied
            # "Record all conversations internally [...] surface
            # conversations that changed beliefs, relationships or future
            # events" (Observatory UI direction, CLAUDE.md): every
            # exchange still applies its relationship/trust/gossip effects
            # (`apply_dialogue` above, unconditional), but only a genuine
            # LLM-authored exchange (`is_llm`) reaches the event log at
            # all — the crowd's deterministic fallback chatter is real
            # and mechanically consequential, it's just not narration
            # worth surfacing in /events or /history (explicit user
            # direction).
            #
            # v1.4.4 fix: since v1.4.0's voice-pair redesign, `is_llm`
            # here can ONLY ever be the one dedicated voice pair (every
            # other pair resolves through `_queue_fallback_dialogue`,
            # always `is_llm=False`) — but the OLD category split below
            # still gated visibility on `surfaced` (a rumor/relationship-
            # threshold flag), and plain `dialogue` is `skip: true` in
            # the frontend (a holdover from when many core-cast pairs
            # produced real LLM chatter and most of it needed hiding).
            # The result: the voice pair's actual conversation — the
            # entire point of the feature — was invisible in the main UI
            # feed unless a line happened to also cross that threshold,
            # a live-diagnosed "I don't see any dialogue at all" bug.
            # `surfaced` still marks the stronger `dialogue_surfaced`
            # category; every OTHER voice-pair line now gets its own
            # visible `voice_dialogue` category instead of the hidden
            # `dialogue` one — see docs/DECISIONS.md.
            if is_llm:
                category = "dialogue_surfaced" if surfaced else "voice_dialogue"
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
                # Root-cause fix for a live audit finding (P0.2b/c): the
                # rumor->memory->dialogue->folklore loop had no damping —
                # 71% of LLM dialogues emitted a rumor, and once a topic
                # became dominant every exchange about it minted ANOTHER
                # rumor object, feeding right back into the same loop
                # (measured: 853 rumor events, one settlement spending an
                # entire in-world year on one topic). An exchange about
                # the settlement's own already-dominant topic still
                # happens and still shows up in the event log/history —
                # it just doesn't mint a new rumor object or spend an
                # InterpretRumor() call retelling something the village
                # is already thoroughly talking about.
                home_for_rumor = self._settlement_by_id(agent_a.settlement_id)
                dominant = home_for_rumor.top_topics(1) if home_for_rumor is not None else []
                # Requires the dominant topic to have already recurred a
                # few times (not just "is currently rank 1 of a nearly-
                # empty ring," which every settlement's very first topic
                # would trivially satisfy) — RUMOR_NOVELTY_MIN_COUNT.
                is_dominant_topic = bool(
                    parsed["topic"] and dominant and dominant[0][1] >= RUMOR_NOVELTY_MIN_COUNT
                    and parsed["topic"].strip().lower() == dominant[0][0].strip().lower()
                )
                if not is_dominant_topic:
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
        event, not once a month like every other settlement job.

        Routed through `_schedule_llm_job` (LLM-integration audit,
        v1.3.29) rather than a hand-rolled `_runner()` coroutine — it
        used to duplicate the budget-consume/debug-record/call-record
        bookkeeping `_schedule_llm_job` already centralizes, the one
        settlement/world-scoped job that hadn't been folded in. One
        real behavior change from this move: on a day whose LLM budget
        is already spent, this used to skip the retelling entirely
        (silent no-op, nothing recorded); now, like every other non-
        critical job, it applies the deterministic fallback retelling
        via `apply` — consistent with rumor_interpret's own ambient/
        narrative classification (`critical=False`, a real deterministic
        fallback already existed) rather than the outlier of silently
        dropping it. Its own tighter-than-`_settlement_job_
        backpressured()` fraction check (P1.2(ii) — rumor_interpret
        ranks below both cognition and dialogue at the consume stage)
        stays as an explicit pre-check, same pattern every settlement
        job's own `_settlement_job_backpressured()` pre-check already
        uses before calling into the shared helper."""
        if not self._cognition_runner.enabled:
            return
        core = self.world.population.core_agent_ids
        listener = agent_a if agent_a.id in core else agent_b if agent_b.id in core else None
        if listener is None:
            return
        if self._interpret_rumor_today >= INTERPRET_RUMOR_MAX_PER_DAY:
            return
        # P1.2(ii): rumor_interpret ranks below both cognition and
        # dialogue at the consume stage — its own tighter fraction of
        # the shared limit, not `_settlement_job_backpressured()`'s
        # bare threshold (that one is shared by chronicle/town_brain/
        # beliefs/etc., which aren't part of this ranking).
        if self._effective_backlog() >= self._current_backpressure_limit() * RUMOR_INTERPRET_BACKPRESSURE_FRACTION:
            self._cognition_runner.calls_dropped_backpressure += 1
            return
        self._interpret_rumor_today += 1
        prompt = rumor_interpret.build_prompt(listener.name, dict(listener.traits), rumor)
        fallback = rumor_interpret.fallback_interpretation(listener.name, rumor)
        listener_id = listener.id

        def apply(result: dict, used_fallback: bool) -> None:
            target = self.world.population.get(listener_id)
            if target is not None:
                retelling = rumor_interpret.parse_interpretation(result, fallback)
                _remember(target, retelling)

        self._schedule_llm_job(
            "rumor_interpret", prompt, rumor_interpret.SYSTEM_PROMPT, fallback, apply,
            structured_input={"rumor": rumor, "traits": dict(listener.traits)}, npc_ids=[listener_id],
        )

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
        elif kind == "ask_pillar":
            self._schedule_pillar_answer(str(item.get("pillar", "")), str(item.get("question", "")))
        elif kind == "review_advisory":
            self._review_advisory(item.get("advisory_id"), str(item.get("status", "")))
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

    @staticmethod
    def _dialogue_objective(speaker, other) -> str:
        """Phase 2 "dialogue as a simulation event": what `speaker`
        privately wants out of an exchange with `other`, in priority
        order — a real ledger-recorded debt they owe outranks a vague
        long-term ambition, since it's concrete and about THIS other
        person specifically. Returns "" (most calls) when neither
        source yields anything — dialogue.build_prompt already treats
        an empty objective as "no grounding, write ordinary chatter."
        """
        owed = speaker.debts.get(other.id, 0.0)
        if owed >= DEBT_SIGNIFICANT_THRESHOLD:
            return f"settle what I owe {other.name}, or at least explain myself"
        grievance = speaker.grievances.get(other.id)
        if grievance:
            return f"air a grievance I hold about {other.name}: {grievance[-1]}"
        if speaker.long_term_goal:
            return speaker.long_term_goal.get("goal", "")
        return ""

    def _voice_narrative_extra_scores(self) -> dict[int, float]:
        """The two "who's the story about right now" signals that live
        outside `Population` — a recent invention and active COUNCIL
        membership — computed here (not in `population.py`, which
        deliberately doesn't reference `World`/`Settlement`) and fed
        into `Population.select_voice_pair`'s `extra_scores`. Cheap: at
        most a handful of recent concepts and a few council seats per
        settlement, not an O(population) scan."""
        scores: dict[int, float] = {}
        now = self.world.clock.tick_count
        for concept in self.world.invented_concepts.values():
            if (
                concept.inventor_agent_id is not None
                and now - concept.tick_invented <= VOICE_NARRATIVE_INVENTOR_RECENT_TICKS
            ):
                scores[concept.inventor_agent_id] = max(
                    scores.get(concept.inventor_agent_id, 0.0), VOICE_NARRATIVE_INVENTOR_BONUS,
                )
        alive_ids = {a.id for a in self.world.population.agents}
        for settlement in self.world.settlements:
            council = settlement.council()
            if council is None:
                continue
            for member_id in council.member_agent_ids:
                if member_id in alive_ids:
                    scores[member_id] = max(scores.get(member_id, 0.0), VOICE_NARRATIVE_COUNCIL_BONUS)
        return scores

    def _schedule_due_dialogue(self) -> None:
        """Route this tick's due (non-voice-pair) dialogue pairs. Every
        one of these resolves via the deterministic fallback — no Ollama
        call, LLM dialogue is reserved entirely for the fixed voice pair
        (see `_schedule_voice_dialogue`). Still real: relationship/trust/
        gossip effects apply, the crowd stays socially alive, it just
        never reaches the event log (`is_llm=False`). See docs/
        DECISIONS.md, E2 + core-cast pass; explicit user directive for
        the voice-pair split."""
        for agent_a, agent_b in self.world.population.due_for_dialogue(
            self.world.config.seed, self.world.clock.tick_count, DIALOGUE_COOLDOWN_TICKS,
        ):
            self._queue_fallback_dialogue(agent_a, agent_b)

    def _queue_fallback_dialogue(self, agent_a, agent_b) -> None:
        """Resolve a dialogue pair via the deterministic fallback and push
        it onto the same pending-results queue an LLM exchange uses, so it
        flows through `_apply_pending_dialogue_results` identically (same
        relationship/trust/gossip effects, logging, surfacing) — just with
        no Ollama call. See _schedule_due_dialogue."""
        affinity = agent_a.relationships.get(agent_b.id, 0.0)
        fallback = dialogue.fallback_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
        parsed = dialogue.parse_dialogue(fallback, fallback)
        self._pending_dialogue_results.append(
            (self.world.clock.tick_count, agent_a.id, agent_b.id, parsed, False)
        )

    def _schedule_voice_dialogue(self) -> None:
        """Explicit user directive: the town's ONE LLM-dialogue pair
        (`Population.voice_pair_ids`, maintained by `maintain_voice_pair`
        every tick). Backpressure/budget-exhausted ticks degrade to the
        deterministic fallback, same discipline as every other LLM job —
        the pair still "talks," it just isn't the deep model-authored
        exchange that tick."""
        due = self.world.population.due_for_voice_dialogue(
            self.world.clock.tick_count, VOICE_DIALOGUE_COOLDOWN_TICKS,
        )
        if due is None:
            return
        agent_a, agent_b = due
        affinity = agent_a.relationships.get(agent_b.id, 0.0)
        fallback = dialogue.fallback_voice_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
        if (
            not self._cognition_runner.enabled
            or self._effective_backlog() >= self._current_backpressure_limit() * DIALOGUE_BACKPRESSURE_FRACTION
            or not self._consume_llm_budget()
        ):
            parsed = dialogue.parse_voice_dialogue(fallback, fallback)
            self._pending_dialogue_results.append(
                (self.world.clock.tick_count, agent_a.id, agent_b.id, parsed, False)
            )
            return
        local = self._settlement_by_id(agent_a.settlement_id)
        # Explicit user directive: "a very concise summary of the town
        # and happenings" — deliberately NOT the full grounding
        # apparatus `_schedule_due_dialogue`'s old LLM path used
        # (opportunities/beliefs/lexicon/etc.) — one condensed sentence,
        # reusing the town-brain decision already computed this month
        # rather than a fresh read of raw stats.
        town_bits = []
        if local is not None:
            if local.current_priority:
                town_bits.append(f"the village's current focus is {local.current_priority}")
            pop = self.world.population.summary()
            town_bits.append(f"population {pop['total']}, {self.world.clock.season}")
        town_digest = "; ".join(town_bits)

        def _internal_state(agent) -> str:
            bits = [f"hunger {agent.hunger:.2f}, energy {agent.energy:.2f}, currently {agent.goal.value}"]
            emotion = describe_emotion(agent.emotions)
            if emotion:
                bits.append(f"feeling {emotion}")
            return ", ".join(bits)

        conversation_so_far = [
            {
                "speaker": agent_a.name if turn["speaker_id"] == agent_a.id else agent_b.name,
                "text": turn["text"],
            }
            for turn in self.world.population.voice_conversation[-VOICE_CONVERSATION_HISTORY_TURNS:]
        ]
        prompt = dialogue.build_voice_prompt(
            agent_a, agent_b, affinity, local.name if local else "",
            town_digest=town_digest, internal_state_a=_internal_state(agent_a),
            internal_state_b=_internal_state(agent_b), conversation_so_far=conversation_so_far,
        )
        self._reserved_this_tick += 1
        task = asyncio.create_task(
            self._run_voice_dialogue(
                agent_a.id, agent_b.id, prompt, fallback,
                structured_input={"affinity": affinity, "settlement": local.name if local else ""},
                settlement=local.name if local else None,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_voice_dialogue(
        self, agent_a_id: int, agent_b_id: int, prompt: str, fallback: dict,
        structured_input: dict | None = None, settlement: str | None = None,
    ) -> None:
        """Voice pair counterpart to `_run_dialogue` — separate parse
        path (`parse_voice_dialogue`, wider length ceiling, no tic-
        spread check since this is one dedicated pair, not many
        rotating speakers) but the SAME pending-results queue, so
        `_apply_pending_dialogue_results` applies/surfaces it exactly
        like an ordinary LLM exchange. Also records both lines into
        `voice_conversation` for the NEXT call's continuity, regardless
        of whether this result is later found stale for `apply_
        dialogue` purposes — the thread itself should still remember
        what was said."""
        scheduled_tick = self.world.clock.tick_count
        call_start = time.perf_counter()
        result, used_fallback, raw_completion, diag = await self._cognition_runner.run(
            prompt, dialogue.VOICE_SYSTEM_PROMPT, fallback=lambda: fallback,
            json_schema=schema_for_task("voice_dialogue"),
        )
        if used_fallback:
            diag = dict(diag, fallback_result=fallback)
        # v1.4.5: self-name stripping + per-speaker repetition backstop
        # (see parse_voice_dialogue's docstring and VOICE_LINE_DUPLICATE_
        # OVERLAP) — `recent_lines_*` reads the FULL stored `voice_
        # conversation` ring (not just the ~6 turns fed into the prompt
        # itself), since a live report showed exact-line repeats well
        # outside that shorter prompt window.
        agent_a = self.world.population.get(agent_a_id)
        agent_b = self.world.population.get(agent_b_id)
        recent_lines_a = [
            turn["text"] for turn in self.world.population.voice_conversation
            if turn["speaker_id"] == agent_a_id
        ]
        recent_lines_b = [
            turn["text"] for turn in self.world.population.voice_conversation
            if turn["speaker_id"] == agent_b_id
        ]
        parsed = dialogue.parse_voice_dialogue(
            result, fallback,
            speaker_a_name=agent_a.name if agent_a is not None else "",
            speaker_b_name=agent_b.name if agent_b is not None else "",
            recent_lines_a=recent_lines_a, recent_lines_b=recent_lines_b,
        )
        self.world.population.record_voice_line(agent_a_id, parsed["line_a"], scheduled_tick)
        self.world.population.record_voice_line(agent_b_id, parsed["line_b"], scheduled_tick)
        self._pending_dialogue_results.append(
            (scheduled_tick, agent_a_id, agent_b_id, parsed, not used_fallback)
        )
        self._record_llm_debug(
            "voice_dialogue", prompt, result, used_fallback, (time.perf_counter() - call_start) * 1000,
            system_prompt=dialogue.VOICE_SYSTEM_PROMPT, raw_completion=raw_completion,
            structured_input=structured_input, npc_ids=[agent_a_id, agent_b_id], settlement=settlement,
            outcome={"status": "queued_pending_apply"}, diag=diag,
        )
        self._record_llm_call(used_fallback)

    async def _run_dialogue(
        self, agent_a_id: int, agent_b_id: int, prompt: str, fallback: dict,
        structured_input: dict | None = None, settlement: str | None = None,
    ) -> None:
        scheduled_tick = self.world.clock.tick_count
        call_start = time.perf_counter()
        result, used_fallback, raw_completion, diag = await self._cognition_runner.run(
            prompt, dialogue.SYSTEM_PROMPT, fallback=lambda: fallback,
            json_schema=schema_for_task("dialogue"),
        )
        if used_fallback:
            diag = dict(diag, fallback_result=fallback)
        parsed = dialogue.parse_dialogue(result, fallback)
        # P3.2: a genuinely LLM-authored line whose tail matches a tic
        # already spreading across other speakers degrades to the
        # deterministic fallback, same "suspicious -> fallback"
        # treatment garbled/leaked text already gets inside parse_
        # dialogue itself. Only checked (and only recorded into the
        # tracker) for real LLM lines — the deterministic fallback pool
        # legitimately reuses phrasing across agents, which isn't a tic.
        if not used_fallback:
            agent_a = self.world.population.get(agent_a_id)
            agent_b = self.world.population.get(agent_b_id)
            name_a = agent_a.name if agent_a is not None else str(agent_a_id)
            name_b = agent_b.name if agent_b is not None else str(agent_b_id)
            tails = list(self._recent_line_tails)
            if (
                dialogue.is_spreading_tic(parsed["line_a"], name_a, tails)
                or dialogue.is_spreading_tic(parsed["line_b"], name_b, tails)
            ):
                parsed = dict(parsed)
                parsed["line_a"], parsed["line_b"] = fallback["line_a"], fallback["line_b"]
            else:
                self._recent_line_tails.append((dialogue.line_tail_fingerprint(parsed["line_a"]), name_a))
                self._recent_line_tails.append((dialogue.line_tail_fingerprint(parsed["line_b"]), name_b))
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
            outcome={"status": "queued_pending_apply"}, diag=diag,
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
            summary = chronicle.parse_summary(result, fallback)
            self._log("chronicle", summary)
            # Tier 0 eleventh slice (docs/ROADMAP-2026-07-REMAINING.md):
            # chronicle becomes Village pillar's sixth real wired job —
            # memory-only, the monthly narrative itself isn't a single
            # standing fact the way a law/religion/faction is.
            self.world.village_pillar.remember(f"The chronicle recorded: {summary}")

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
            narration = documentary.parse_narration(result, fallback)
            self._log("documentary", narration)
            # Tier 0 twelfth slice: documentary becomes Village
            # pillar's seventh real wired job — memory-only, same
            # reasoning as chronicle (a yearly look-back, not a single
            # standing fact).
            self.world.village_pillar.remember(f"The year in review: {narration}")

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

    # --- C3 "Player <-> Pillar chat" (roadmap Stage III step 10) ---------------

    def _schedule_pillar_answer(self, pillar_name: str, question: str) -> None:
        """Applied the tick after `POST /ask/{pillar}` enqueues an
        `ask_pillar` intervention — same enqueue-now/apply-next-tick
        seam as `_schedule_chronicler_answer`, generalized from one
        settlement-scoped narrative voice to any of the five cognitive
        pillars. Deliberately NOT gated by `_settlement_job_
        backpressured()`/the attention scheduler, same reasoning as the
        chronicler: a single user-triggered question is not part of the
        coincident-job cluster those gates exist to smooth. Answers ONLY
        from the pillar's own real `description`/`self_model`/
        `objectives`/`world_model`/`memory` (see `llm/pillar_chat.py`'s
        module docstring) — never raw World/Settlement stats."""
        question = question.strip()[:300]
        if pillar_name not in emergence.PILLARS or not question:
            return
        pillar = getattr(self.world, f"{pillar_name}_pillar")
        voice_hint = pillar.self_model.get("voice", "") if isinstance(pillar.self_model, dict) else ""
        system_prompt = pillar_chat.build_system_prompt(pillar.description, voice_hint)
        prompt = pillar_chat.build_prompt(
            pillar_name, question, list(pillar.objectives), list(pillar.world_model),
            list(pillar.memory), list(pillar.conversation_log),
        )
        fallback = pillar_chat.fallback_answer(pillar_name)
        pillar.last_question = question
        pillar.pending = True

        def apply(result: dict, used_fallback: bool) -> None:
            answer = pillar_chat.parse_answer(result, fallback)
            tick = self.world.clock.tick_count
            pillar.record_conversation(question, answer, tick)
            pillar.pending = False
            self._log("pillar_answer", f"Asked of {pillar_name}: \"{question}\" — {answer}")
            # "Nudges enter cognition as weighable inputs, never
            # commands" (C3's own phrasing): `note_observation` puts
            # this exchange into `working_memory` — the SAME list every
            # representative job's real `interpret` call already reads
            # via `emergence_observations=list(world.<pillar>_pillar.
            # working_memory)` (see `_pillar_observe_turn`). A recent
            # question genuinely reaches this pillar's next real
            # cognition call as one more thing it noticed, exactly like
            # a salient Emergence API observation would — never a
            # direct belief write or a bypassed decision.
            pillar.note_observation(f"A visitor asked: \"{question}\" — I answered: {answer}")

        self._schedule_llm_job(f"pillar_chat_{pillar_name}", prompt, system_prompt, fallback, apply)

    def _review_advisory(self, advisory_id, status: str) -> None:
        """B6 "Reflection as meta-scientist" (roadmap Stage III step
        13): applies `POST /advisory/{id}/review` — the ONLY way an
        `advisory_proposals` entry's `status` ever changes. Deliberately
        synchronous (no LLM call, no queue-then-apply-next-tick seam
        needed) — a human marking their own review decision is not
        cognition to defer or fake. `advisory_id` may arrive as a JSON
        int or a stringified one depending on the request body; both
        are accepted. An unknown id or a status outside the two real
        review outcomes is a silent no-op, matching every other
        intervention's tolerance of a stale/malformed queued item."""
        if status not in ("accepted", "rejected"):
            return
        try:
            advisory_id = int(advisory_id)
        except (TypeError, ValueError):
            return
        for entry in self.world.advisory_proposals:
            if entry["id"] == advisory_id:
                entry["status"] = status
                self._log("advisory_reviewed", f"Advisory #{advisory_id} marked {status}.")
                return

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
        2026-07-EMERGENCE.md §5.

        Vision doc item 3.1, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
        ("the morning paper"): alongside the existing prose recap,
        `away_digest_highlights` is the structured "front page" section
        — every `World.knowledge_tree()` entry originated strictly
        after `since_tick`, i.e. what the world originated for itself
        during the away window. Pure read over already-computed state,
        zero added LLM cost; computed in `apply` (not before scheduling)
        so it reflects the window at APPLY time, matching when `_tick`
        is captured."""
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
            self.world.away_digest_highlights = [
                entry for entry in self.world.knowledge_tree(limit=400) if entry["tick"] > since_tick
            ]
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

        # Cultural evolution: a tradition is a genuine interpretive claim
        # about what the settlement's lived history means, worth a real
        # reasoning trace (v1.3.37).
        self._schedule_llm_job("tradition", prompt, culture.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
            settlement = self._settlement_by_id(target_id)
            prior_tales = [e["tale"] for e in settlement.folklore]
            entry = folklore.parse_folklore(result, fallback, existing_tales=prior_tales)
            if entry is None:
                return  # nothing worth telling this month, or a near-restatement of an existing tale
            entry["tick"] = self.world.clock.tick_count
            settlement.folklore.append(entry)
            if len(settlement.folklore) > FOLKLORE_MAX_STORED:
                settlement.folklore = settlement.folklore[-FOLKLORE_MAX_STORED:]
            self._log("folklore", f"{settlement.name or 'The village'} now tells a new tale — {entry['tale']}")

        self._schedule_llm_job(
            "folklore", prompt, folklore.SYSTEM_PROMPT, fallback, apply, settlement=target.name,
        )

    def _maybe_schedule_legend_detection(self, events: list[str]) -> None:
        """A21 "Temporal compression" (roadmap Stage IV step 30, docs/
        MASTERCHECKLIST-2026-07-22.md), first slice. Same monthly
        rotation shape as folklore, but a SEPARATE, more selective
        mechanism — see `world/legends.py`'s module docstring for why
        this reuses the Emergence API stream instead of folklore's raw
        rumor text.

        Deterministic-first, same "skip the call when the precondition
        guarantees nothing" discipline `_maybe_schedule_folklore` and
        `_maybe_schedule_invention` already use: `legends.detect_
        legend_candidate` runs for free (no LLM call) every month: most
        months no subsystem has crossed the threshold yet, and the job
        resolves with zero cost, same as folklore's own common case."""
        target = self._job_target()
        if not self._monthly_gate(events, "legend_detection") or not target.name:
            return
        already_legendary = {entry["subsystem"] for entry in target.legends}
        candidate = legends.detect_legend_candidate(
            self.world.emergence_log, target.name, already_legendary,
        )
        if candidate is None:
            self._mark_monthly_resolved("legend_detection")
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("legend_detection")
        subsystem = candidate["subsystem"]
        summaries = candidate["summaries"]
        prompt = legend.build_prompt(target.name, subsystem, summaries)
        fallback = legend.fallback_legend(target.name, subsystem, summaries)
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            settlement = self._settlement_by_id(target_id)
            entry = legend.parse_legend(result, fallback)
            entry["subsystem"] = subsystem
            entry["tick"] = self.world.clock.tick_count
            settlement.legends.append(entry)
            if len(settlement.legends) > LEGENDS_MAX_STORED:
                settlement.legends = settlement.legends[-LEGENDS_MAX_STORED:]
            self._log(
                "legend",
                f"{settlement.name or 'The village'} now speaks of a legend — {entry['legend']}",
            )

        self._schedule_llm_job(
            "legend", prompt, legend.SYSTEM_PROMPT, fallback, apply, settlement=target.name,
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
        self._mark_season_year_resolved("invention")
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
            name, description, category = invention.parse_invention(result, fallback)
            entry = f"{name}: {description}"
            settlement = self._settlement_by_id(invention_target_id)
            settlement.inventions.append(entry)
            if len(settlement.inventions) > CULTURE_LIST_MAX_STORED:
                settlement.inventions = settlement.inventions[-CULTURE_LIST_MAX_STORED:]
            settlement.tech_level += 1
            if category != "general":
                current = settlement.invention_specializations.get(category, 0.0)
                settlement.invention_specializations[category] = min(
                    INVENTION_SPECIALIZATION_CAP, current + INVENTION_SPECIALIZATION_STEP,
                )
            invention_detail = f"{settlement.name or 'The village'} invented {entry}"
            self._log("invention", invention_detail)
            # Vision doc item 1.2: a real invention forming is the
            # concrete `on_invention` detection point for trigger rules.
            self._apply_trigger_rules_for("on_invention", settlement)
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
            inventor_id = None
            if candidates:
                rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "invention_inventor")
                inventor = rng.choice(candidates)
                inventor_id = inventor.id
                settlement.invention_knowledge[entry] = {"knowers": [inventor.id], "dormant": False}
                if len(settlement.invention_knowledge) > INVENTION_KNOWLEDGE_MAX_TRACKED:
                    oldest_key = next(iter(settlement.invention_knowledge))
                    del settlement.invention_knowledge[oldest_key]
            # Phase 1.A "self-evolving world" (docs/VISION-2026-07-21-
            # SELFEVOLVING.md): every invention is ALSO registered as a
            # first-class InventedConcept — the bridge that keeps this
            # pre-existing job from becoming a disconnected duplicate
            # of the new Innovation Layer registry, per the explicit
            # user direction that invented concepts must be real,
            # referenceable building blocks, not inert flavor. Reuses
            # the mechanical effect this job already computed above
            # (the v1.2.0 specialization bump) rather than inventing a
            # second one.
            ontology.register_concept(
                self.world, name=name, description=description, category="technology",
                origin_settlement_id=settlement.id, tick=self.world.clock.tick_count,
                inventor_agent_id=inventor_id,
                mechanical_hook=(
                    {"type": "invention_specialization_category", "target": category, "magnitude": INVENTION_SPECIALIZATION_STEP}
                    if category != "general" else None
                ),
            )
            # Tier 0 first slice (docs/ROADMAP-2026-07-REMAINING.md):
            # invention becomes Innovation pillar's SECOND real wired
            # job, alongside ontology_proposal — same mirror-into-
            # world_model shape nature_mind established for Nature.
            # An established invention is a settled fact, not a
            # revisable theory, hence status="observation" (confidence
            # 1.0) rather than "hypothesis".
            self.world.innovation_pillar.upsert_world_model(
                self.world.clock.tick_count, name, description, 1.0,
                status="observation", source="invention",
            )
            self.world.innovation_pillar.remember(f"Invented {name}: {description}")

        # Innovation & discovery: naming/scoping a genuinely new idea
        # warrants a real reasoning trace, same treatment as ontology
        # propose/evolve below (v1.3.37).
        self._schedule_llm_job("invention", prompt, invention.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

    # --- Phase 1.A "self-evolving world" — the Innovation Layer -----------

    def _maybe_schedule_ontology_proposal(self, events: list[str]) -> None:
        """Same seasonal cadence/prosperity gate as `_maybe_schedule_
        invention`, but for the six ontology categories `invention.py`
        doesn't cover (custom/law/ritual/saying/profession/institution_
        flavor) — see docs/VISION-2026-07-21-SELFEVOLVING.md, Phase 1.A.
        Deliberately excludes "technology" (`invention.py`'s own job,
        bridged into the same registry, not duplicated — see
        `_maybe_schedule_invention`'s apply()) AND "ecological" (Body/
        Mind correction: that's `_maybe_schedule_nature_mind`'s
        territory now, grounded in Nature's own Body state rather than
        settlement prosperity — see `ontology_llm.VILLAGE_PROPOSE_
        CATEGORIES`)."""
        settlement = self._job_target()
        if not self._season_year_gate(events, "ontology_proposal", "season_end") or not settlement.name:
            return
        if self._pillar_observe_turn("innovation"):
            self._mark_season_year_resolved("ontology_proposal")
            return
        if self._pillar_interpret_backpressured("innovation"):
            return
        prosperous = (
            settlement.currency >= INVENTION_CURRENCY_THRESHOLD
            or settlement.materials >= MATERIALS_CAPACITY * INVENTION_MATERIALS_FRACTION
        )
        pressured = any(v >= PATTERN_SIGNAL_BELIEF_THRESHOLD for v in settlement.pattern_signal_counts.values())
        if not (prosperous or pressured):
            self._mark_season_year_resolved("ontology_proposal")
            self._pillar_close_cycle("innovation")
            return
        self._mark_season_year_resolved("ontology_proposal")
        ontology.abandon_stale(self.world, self.world.clock.tick_count)
        # A8 "Evolutionary Innovation" (roadmap Stage IV step 21): the
        # real *evaluate* step, same monthly cadence/call site as
        # abandon_stale immediately above.
        ontology.run_selection(self.world, self.world.clock.tick_count)
        chance = min(1.0, INVENTION_CHANCE_PER_SEASON * education_invention_bonus(settlement.education_level))
        # Vision item 5.3: self-tuning's bounded nudge on ontology
        # coherence, if any has ever been applied.
        chance = max(0.0, min(1.0, chance * self.world.governor_tuning.get("ontology_proposal_chance", 1.0)))
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "ontology_proposal_roll") >= chance:
            self._pillar_close_cycle("innovation")
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        existing_names = [c.name for c in self.world.invented_concepts.values()][-PROMPT_CULTURE_LIST_MAX:]
        # B5 "Innovation as conscious scientist" (roadmap Stage III step
        # 12): name the real problem, if any, this proposal should be
        # treated as a hypothesis about — the dominant pattern-signal
        # crossing its own promotion threshold, or None if the job only
        # fired on prosperity (nothing specifically pressured).
        pressure_signal = None
        if settlement.pattern_signal_counts:
            top_signal, top_value = max(settlement.pattern_signal_counts.items(), key=lambda kv: kv[1])
            if top_value >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
                pressure_signal = top_signal
        # A5/A6 "Affordances + discovery query layer" (roadmap Stage IV
        # step 18): a real query into what's physically standing right
        # now, not just prosperity/pressure — Innovation's generate-step
        # asking the affordance layer "what combination of affordances
        # would achieve Y?" per the spec. A12 (step 19) widens this
        # further: `materials.building_affordances` unions each kind's
        # hand-tagged set with what its assigned material's properties
        # derive, so a genuinely material-driven combination (e.g. a
        # metal FORGE's `can_conduct_heat` from conductivity, not just
        # its hand tag) is reachable too.
        standing_kinds = {
            b.kind for b in settlement.buildings if b.stage is BuildingStage.STANDING
        }
        present_tags: set[str] = set()
        for kind in standing_kinds:
            present_tags |= building_affordances(kind)
        discoverable = discover_combinations(present_tags)
        # A13 "Chemistry / reaction system" (roadmap Stage IV step 20):
        # what a genuinely available material would produce under a
        # genuinely available condition — real materials from A12's
        # `BUILDING_MATERIALS`, real conditions derived from the same
        # affordance layer step 18/19 already computed above.
        present_materials = {
            BUILDING_MATERIALS[kind] for kind in standing_kinds if kind in BUILDING_MATERIALS
        }
        discoverable_reactions = discover_reactions(present_materials, present_tags)
        prompt = ontology_llm.build_propose_prompt(
            settlement.name, recent, existing_names, settlement.era, settlement.tech_level,
            emergence_observations=list(self.world.innovation_pillar.working_memory),
            pressure_signal=pressure_signal,
            discoverable_combinations=discoverable,
            discoverable_reactions=discoverable_reactions,
        )
        established_count = sum(1 for c in self.world.invented_concepts.values() if c.status == "established")
        fallback = ontology_llm.fallback_propose(established_count, pressure_signal=pressure_signal)
        settlement_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = ontology_llm.parse_propose(result, fallback)
            if ontology.is_near_duplicate(self.world, parsed["name"], parsed["description"]):
                self._pillar_close_cycle("innovation")
                return  # "nothing new" — same discipline as folklore's duplicate-tale guard
            target = self._settlement_by_id(settlement_id)
            local = [a for a in self.world.population.agents if a.settlement_id == settlement_id]
            core_local = [a for a in local if a.id in self.world.population.core_agent_ids]
            candidates = core_local or local
            inventor_id = None
            if candidates:
                rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "ontology_inventor")
                inventor_id = rng.choice(candidates).id
            # B1 Pillar abstraction, generalized: always-additive
            # mirror into Innovation's own world_model (no revision
            # path exists for concepts — name/description -> subject/
            # belief; 0.4 confidence for a freshly "proposed" concept,
            # matching its real adoption-lifecycle starting point).
            # B5: `entry["id"]` is threaded onto the concept itself so
            # `world.ontology.add_adopter`/`abandon_stale` can revise
            # this SAME belief in place once the concept's real fate
            # (established/abandoned) confirms or refutes it.
            entry = self.world.innovation_pillar.upsert_world_model(
                self.world.clock.tick_count, parsed["name"], parsed["description"], 0.4, source="ontology_proposal",
            )
            concept = ontology.register_concept(
                self.world, name=parsed["name"], description=parsed["description"], category=parsed["category"],
                origin_settlement_id=settlement_id, tick=self.world.clock.tick_count,
                inventor_agent_id=inventor_id, mechanical_hook=parsed["hook"],
                hypothesis=parsed["hypothesis"], world_model_entry_id=entry["id"],
            )
            self._log("ontology", f"{target.name or 'The village'} originated {concept.name}: {concept.description}")
            self.world.innovation_pillar.remember(f"Originated {concept.name}: {concept.description}")
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), the Innovation->Village arrow: a newly
            # registered concept is real news for the village that
            # will go on to adopt (or ignore) it.
            self._send_pillar_message(
                "innovation", "village", "discovery",
                f"the village now has {concept.name}: {concept.description}",
            )
            self._pillar_close_cycle("innovation")

        self._schedule_llm_job(
            "ontology_proposal", prompt, ontology_llm.SYSTEM_PROMPT_PROPOSE, fallback, apply,
            deep_reasoning=True,
        )

    def _maybe_schedule_ontology_evolution(self, events: list[str]) -> None:
        """Rare (year_end), world-scoped (not per-settlement — an idea
        being reinterpreted/combined isn't bound to where it started):
        picks one `established` concept and either evolves it (mutation,
        `lineage.evolved_from`) or, if at least two exist, combines two
        of them (`lineage.merged_from`) — the concrete "combine, mutate,
        build upon indefinitely" mechanism. Parents are never removed
        or altered; the new concept just references them, so the DAG
        stays fully walkable."""
        if not self._season_year_gate(events, "ontology_evolution", "year_end"):
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("ontology_evolution")
        # A8 "Evolutionary Innovation" (roadmap Stage IV step 21)'s
        # *select* step: draw from the fitness-weighted pool, not a
        # flat uniform choice among every established concept — a
        # concept with a real positive fitness reading is genuinely
        # more likely to become a parent (see `ontology.concept_
        # fitness_weight`'s docstring for why an un-evaluated or
        # mildly-below-average concept still gets a real, non-zero
        # chance).
        established = ontology.fit_established_concepts(self.world)
        if not established:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "ontology_evolution_pick")
        do_merge = len(established) >= 2 and rng.random() < 0.5

        def weighted_pick(count: int) -> list:
            pool = list(established)
            picked = []
            for _ in range(min(count, len(pool))):
                weights = [ontology.concept_fitness_weight(c) for c in pool]
                choice = rng.choices(pool, weights=weights, k=1)[0]
                picked.append(choice)
                pool.remove(choice)
            return picked

        settlement = self._settlement_by_id(established[0].origin_settlement_id) or self._job_target()
        if do_merge:
            a, b = weighted_pick(2)
            prompt = ontology_llm.build_merge_prompt(a.name, a.description, b.name, b.description, settlement.name or "The village")
            fallback = ontology_llm.fallback_merge(a.name, b.name)
            system_prompt = ontology_llm.SYSTEM_PROMPT_MERGE
            parent_ids = [a.id, b.id]
            category, hook, origin_settlement_id = a.category, a.mechanical_hook, a.origin_settlement_id
            child_generation = max(a.generation, b.generation) + 1

            def apply(result: dict, used_fallback: bool) -> None:
                name, description = ontology_llm.parse_merge(result, fallback)
                if ontology.is_near_duplicate(self.world, name, description):
                    return
                concept = ontology.register_concept(
                    self.world, name=name, description=description, category=category,
                    origin_settlement_id=origin_settlement_id, tick=self.world.clock.tick_count,
                    mechanical_hook=hook, lineage={"merged_from": parent_ids}, generation=child_generation,
                )
                self._log("ontology", f"Two ideas combined into {concept.name}: {concept.description}")
                # Tier 0 second slice (docs/ROADMAP-2026-07-REMAINING.md):
                # ontology_evolution becomes Innovation pillar's THIRD
                # real wired job, alongside ontology_proposal/invention.
                self.world.innovation_pillar.upsert_world_model(
                    self.world.clock.tick_count, name, description, 1.0,
                    status="observation", source="ontology_evolution",
                )
                self.world.innovation_pillar.remember(f"Combined two ideas into {name}: {description}")
        else:
            parent = weighted_pick(1)[0]
            prompt = ontology_llm.build_evolve_prompt(parent.name, parent.description, settlement.name or "The village", [])
            fallback = ontology_llm.fallback_evolve(parent.name)
            system_prompt = ontology_llm.SYSTEM_PROMPT_EVOLVE
            parent_id = parent.id
            category, hook, origin_settlement_id = parent.category, parent.mechanical_hook, parent.origin_settlement_id
            child_generation = parent.generation + 1

            def apply(result: dict, used_fallback: bool) -> None:
                name, description = ontology_llm.parse_evolve(result, fallback)
                if ontology.is_near_duplicate(self.world, name, description):
                    return
                concept = ontology.register_concept(
                    self.world, name=name, description=description, category=category,
                    origin_settlement_id=origin_settlement_id, tick=self.world.clock.tick_count,
                    mechanical_hook=hook, lineage={"evolved_from": parent_id}, generation=child_generation,
                )
                self._log("ontology", f"An old idea evolved into {concept.name}: {concept.description}")
                # Tier 0 second slice (docs/ROADMAP-2026-07-REMAINING.md):
                # ontology_evolution becomes Innovation pillar's THIRD
                # real wired job, alongside ontology_proposal/invention.
                self.world.innovation_pillar.upsert_world_model(
                    self.world.clock.tick_count, name, description, 1.0,
                    status="observation", source="ontology_evolution",
                )
                self.world.innovation_pillar.remember(f"An old idea evolved into {name}: {description}")

        self._schedule_llm_job(
            "ontology_evolution", prompt, system_prompt, fallback, apply, deep_reasoning=True,
        )

    def _composite_entity_candidate_building(self, settlement) -> "Building | None":
        """Vision item 4.1: a real standing building in `settlement`
        that no `CompositeEntity` has named yet — the deterministic
        eligibility check. Prefers the oldest-standing (most likely to
        have real history behind it) among unnamed candidates, a small
        deterministic tiebreak rather than random, so a settlement's
        first-ever named place tends to be a genuinely established one,
        not whichever hut finished construction most recently."""
        named_building_ids = {e.building_id for e in self.world.composite_entities.values()}
        candidates = [
            b for b in settlement.buildings
            if b.stage == BuildingStage.STANDING and b.id not in named_building_ids
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda b: b.id)

    def _maybe_schedule_composite_entity(self, events: list[str]) -> None:
        """Vision doc item 4.1, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
        ("Composite entities from existing primitives"): a new "entity"
        that's structurally just composition — a real standing building
        (unchanged kind/mechanics), given a name and an origin story
        grounded in something that actually happened, plus a genuine
        new `InventedConcept` that name embodies. Same seasonal,
        round-robin-settlement cadence as `_maybe_schedule_institution_
        culture`; `critical=False` — this is ambient world-building
        texture with a real deterministic fallback name, not crucial
        cognition."""
        settlement = self._job_target()
        if not self._season_year_gate(events, "composite_entity", "season_end") or not settlement.name:
            return
        building = self._composite_entity_candidate_building(settlement)
        if building is None:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("composite_entity")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        event_description = recent[0]["description"] if recent else "The village has simply endured, season after season."
        existing_names = [e.name for e in self.world.composite_entities.values()]
        prompt = composite_entity.build_prompt(settlement.name, building.kind.value, event_description, existing_names)
        fallback = composite_entity.fallback_entity(len(existing_names))
        settlement_id, building_id, building_kind = settlement.id, building.id, building.kind.value

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = composite_entity.parse_entity(result, fallback)
            if ontology.is_near_duplicate(self.world, parsed["name"], parsed["origin_story"]):
                return  # "nothing new" — same discipline as folklore/ontology's duplicate guard
            target = self._settlement_by_id(settlement_id)
            live_building = next(
                (b for b in target.buildings if b.id == building_id and b.stage == BuildingStage.STANDING), None,
            ) if target else None
            if live_building is None:
                return  # ruined/gone while the call was in flight
            concept = ontology.register_concept(
                self.world, name=parsed["name"], description=parsed["origin_story"], category=parsed["category"],
                origin_settlement_id=settlement_id, tick=self.world.clock.tick_count,
                mechanical_hook=parsed["hook"],
            )
            sigil = generate_sigil_svg(parsed["name"], parsed["category"])
            ontology.register_composite_entity(
                self.world, name=parsed["name"], base_kind=building_kind, building_id=building_id,
                concept_id=concept.id, origin_settlement_id=settlement_id,
                origin_story=parsed["origin_story"], tick=self.world.clock.tick_count, sigil_svg=sigil,
            )
            self._log(
                "composite_entity_named",
                f"{target.name or 'The village'} now knows this place as {parsed['name']} — {parsed['origin_story']}",
            )
            # Tier 0 fifth slice (docs/ROADMAP-2026-07-REMAINING.md):
            # composite_entity becomes Innovation pillar's FOURTH real
            # wired job, alongside ontology_proposal/invention/
            # ontology_evolution — a named place backed by a genuinely
            # new registered `InventedConcept` is a settled fact, same
            # "observation" treatment as those three.
            self.world.innovation_pillar.upsert_world_model(
                self.world.clock.tick_count, parsed["name"], parsed["origin_story"], 1.0,
                status="observation", source="composite_entity",
            )
            self.world.innovation_pillar.remember(f"{target.name or 'The village'} named {parsed['name']}: {parsed['origin_story']}")

        self._schedule_llm_job("composite_entity", prompt, composite_entity.SYSTEM_PROMPT, fallback, apply)

    def _pillar_observe_turn(self, pillar_name: str) -> bool:
        """B2 "The continuous cognitive cycle," shared across every
        pillar job (roadmap Stage II): if `world.<pillar_name>_pillar`
        is on an `observe` turn, read the Emergence API (A22) into its
        bounded `working_memory` — zero LLM cost — advance to
        `interpret`, and return True (the caller should stop here,
        having done this turn's whole job). Returns False on an
        `interpret` turn (the caller should proceed to its real LLM
        call). Extracted from `_maybe_schedule_nature_mind`'s original
        inline logic once a second pillar needed the identical shape.

        C1 "The perception channel" (docs/MASTERCHECKLIST-2026-07-22.md,
        Part C, roadmap Stage II step 9) asks for this feed to be
        "bounded, salience-ranked, pillar-tagged" — bounded and pillar-
        tagged already held; salience-ranked did not. This used to feed
        `note_observation` every pillar-tagged candidate in the 40-entry
        window in plain recency order, letting `WORKING_MEMORY_MAX`'s
        FIFO eviction silently discard a genuinely high-`magnitude`
        observation in favor of a later but less salient one purely
        because it happened to log first. Now sorts the pillar-tagged
        candidates by `magnitude` (highest first, unranked observations
        — `magnitude=None` — sorting last) and only notes the top
        `WORKING_MEMORY_MAX`, so a pillar's bounded attention is
        deliberately spent on what actually matters most this turn, not
        whatever happened to be freshest.

        B4 "Inter-pillar consciousness bus" (roadmap Stage III step 11):
        undelivered `inbox` messages now compete for the same bounded
        attention alongside Emergence API observations, using a
        per-kind synthetic magnitude (`_PILLAR_MESSAGE_MAGNITUDE`) so a
        `disagreement`/`warning` from another pillar reliably outranks
        routine `observation`/`discovery` traffic. Only the messages
        that actually made it into `working_memory` this turn are
        removed from `inbox` — anything bumped by higher-priority
        traffic stays queued for a future observe turn (this is the
        mechanism that makes "disagreement persists" literally true,
        not just a design intention)."""
        pillar = getattr(self.world, f"{pillar_name}_pillar")
        if pillar.cycle_stage != "observe":
            return False
        candidates: list[dict] = [
            {"summary": obs["summary"], "magnitude": obs.get("magnitude"), "message_id": None}
            for obs in self.world.emergence_log_recent(limit=40)
            if pillar_name in obs.get("pillars", ())
        ]
        for msg in pillar.inbox:
            candidates.append({
                "summary": f"{msg['from_pillar'].capitalize()} ({msg['kind']}): {msg['summary']}",
                "magnitude": _PILLAR_MESSAGE_MAGNITUDE.get(msg["kind"], 0.5),
                "message_id": msg["id"],
            })
        candidates.sort(key=lambda c: c["magnitude"] if c["magnitude"] is not None else -1.0, reverse=True)
        delivered_message_ids = set()
        for c in candidates[: pillar.WORKING_MEMORY_MAX]:
            pillar.note_observation(c["summary"])
            if c["message_id"] is not None:
                delivered_message_ids.add(c["message_id"])
        if delivered_message_ids:
            pillar.inbox = [m for m in pillar.inbox if m["id"] not in delivered_message_ids]
        pillar.set_cycle_stage("interpret")
        pillar.last_turn_tick = self.world.clock.tick_count
        return True

    def _pillar_interpret_backpressured(self, pillar_name: str) -> bool:
        """B3 "The Attention Scheduler," shared across every pillar job:
        a priority-scaled backpressure check for a pillar's `interpret`
        turn — salience of what it noticed since its last turn plus how
        stale that turn is, mapped to a 0.5..1.0 fraction of the shared
        backpressure limit this turn tolerates before deferring. Never
        a full bypass. On deferral, increments the same `calls_dropped_
        backpressure` counter `_settlement_job_backpressured()` does,
        for diagnostic parity."""
        pillar = getattr(self.world, f"{pillar_name}_pillar")
        tick = self.world.clock.tick_count
        priority = attention.compute_priority(
            attention.pillar_salience(self.world.emergence_log, pillar_name, pillar.last_turn_tick),
            tick - pillar.last_turn_tick, message_count=len(pillar.inbox),
        )
        if self._effective_backlog() >= self._current_backpressure_limit() * attention.backpressure_fraction(priority):
            self._cognition_runner.calls_dropped_backpressure += 1
            return True
        return False

    def _pillar_close_cycle(self, pillar_name: str) -> None:
        """Closes a pillar's `interpret` turn, freeing `working_memory`
        and returning `cycle_stage` to `observe` for the next season/
        year this job's own gate opens again. Also runs B8 "Living
        memory & consolidation" (roadmap Stage II step 8) once per
        closed cycle — `Pillar.consolidate()` is cheap and a no-op below
        its threshold, so calling it unconditionally here (rather than
        only on cycles that actually wrote new memory) is simplest and
        correct; a pillar that hasn't accumulated enough raw notes yet
        just returns False and does nothing."""
        pillar = getattr(self.world, f"{pillar_name}_pillar")
        pillar.consolidate()
        pillar.clear_working_memory()
        pillar.set_cycle_stage("observe")
        pillar.last_turn_tick = self.world.clock.tick_count

    def _send_pillar_message(
        self, from_name: str, to_name: str, kind: str, summary: str, data: dict | None = None,
    ) -> None:
        """B4 "Inter-pillar consciousness bus" (roadmap Stage III step
        11): the one call site that actually sends a message — builds
        it via `cognition.pillar.make_message` (validates `kind` against
        the closed `MESSAGE_KINDS` vocabulary), records it on the
        sender's `outbox`, and delivers it into the recipient's `inbox`
        (`Pillar.send_message`/`receive_message`). The message is NOT
        immediately visible to the recipient's cognition — it sits in
        `inbox` until that pillar's own next `observe` turn delivers it
        into `working_memory` via `_pillar_observe_turn`, competing for
        that bounded attention by salience like anything else."""
        from_pillar = getattr(self.world, f"{from_name}_pillar")
        to_pillar = getattr(self.world, f"{to_name}_pillar")
        tick = self.world.clock.tick_count
        message = make_message(from_pillar.next_message_id, tick, from_name, to_name, kind, summary, data)
        from_pillar.next_message_id += 1
        from_pillar.send_message(dict(message))
        to_pillar.receive_message(message)

    def _maybe_schedule_nature_mind(self, events: list[str]) -> None:
        """Nature's Mind (Body/Mind framing, CLAUDE.md "Design
        priorities" — explicit user direction 2026-07-21): world-scoped
        (the land isn't any one settlement's), season_end cadence, same
        shape as `_maybe_schedule_beliefs` but grounded ONLY in Nature's
        own Body state — wildlife trophic ratios, disaster/mining scars,
        succession progress, climate drift, season — never settlement
        prosperity, era, or tech level. Forms/revises one belief about
        the land (critical — genuine cognition, deferred rather than
        faked on a spent budget/failed call, same as settlement
        beliefs) and may originate one `category="ecological"` concept
        into the SHARED ontology registry — the "every pillar expands
        the ontology from its own Body state" correction; this is the
        one job allowed to originate that category now (see
        `_maybe_schedule_ontology_proposal`'s narrowed category list).

        B2 "The continuous cognitive cycle" (roadmap Stage II step 5):
        this method is now Nature's whole turn, branching on `world.
        nature_pillar.cycle_stage`. An `observe` season reads the
        Emergence API (A22) into bounded `working_memory` — cheap, zero
        LLM cost — and advances to `interpret`; the NEXT season is the
        one that actually fires the LLM call below, grounded in both
        the raw event window (unchanged) and what was noticed during
        the prior observe turn, then returns to `observe` once resolved.
        Total LLM call volume for this job is now halved (one real call
        every other season instead of every season) — a real trade of
        volume for a genuinely resumable, perception-grounded cycle,
        not a free lunch.

        B3 "The Attention Scheduler" (roadmap Stage II step 6): the
        `interpret` turn's backpressure tolerance now scales with a
        computed priority (`cognition.attention.compute_priority`) —
        salience of what's been noticed since the pillar's last turn,
        how stale that turn is, inbox message count (0 today, no
        second pillar exists to message from yet) — instead of the
        flat threshold every other settlement job shares. A quiet,
        fresh turn defers earlier under pressure; a salient or
        long-overdue one tolerates more backlog before deferring.
        Never a full bypass — the tolerance is always a fraction (0.5
        to 1.0) of the same shared limit."""
        if not self._season_year_gate(events, "nature_mind", "season_end"):
            return
        pillar = self.world.nature_pillar
        if self._pillar_observe_turn("nature"):
            self._mark_season_year_resolved("nature_mind")
            pillar.turns_processed += 1
            return
        if self._pillar_interpret_backpressured("nature"):
            return
        self._mark_season_year_resolved("nature_mind")
        pillar.turns_processed += 1
        recent = recent_events_diverse(self.conn, limit=30)
        nature_events = [e for e in recent if e["category"] in nature_mind.NATURE_EVENT_CATEGORIES]
        wildlife_summary = self.world.wildlife.summary()
        disaster_scar_count = len(self.world.disaster_scars)
        fallow_count = len(self.world.fallow_ticks)
        climate_summary = self.world.climate.to_dict()
        season = self.world.clock.season
        existing_beliefs = list(self.world.nature_beliefs)
        prompt = nature_mind.build_prompt(
            nature_events, existing_beliefs, wildlife_summary, disaster_scar_count, fallow_count,
            climate_summary, season, emergence_observations=list(pillar.working_memory),
        )
        fallback = nature_mind.fallback_belief(nature_events, wildlife_summary, fallow_count)
        existing_count = len(existing_beliefs)
        # A concept, if any, needs an origin_settlement_id — the shared
        # ontology schema ties every concept to a settlement even when
        # its true origin is the land itself; the round-robin job
        # target is the pragmatic attribution, same as any other
        # world-scoped job that still needs a settlement id to write
        # through (`_maybe_schedule_ontology_evolution` above does the
        # same thing).
        origin_settlement = self._job_target()
        origin_settlement_id = origin_settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            # critical=True below means this apply only ever runs on a
            # genuine LLM answer — see _schedule_llm_job's docstring.
            parsed = nature_mind.parse_nature_belief(result, fallback, existing_count)
            tick = self.world.clock.tick_count
            revises = parsed["revises"]
            if revises is not None and revises < len(self.world.nature_beliefs):
                entry = self.world.nature_beliefs[revises]
                if nature_mind.is_noop_nature_revision(parsed["belief"], parsed["confidence"], entry):
                    # B2: a no-op interpretation is still a completed
                    # interpret turn (the LLM genuinely answered, it
                    # just found nothing worth changing) — the cycle
                    # still closes, or the pillar would retry the same
                    # interpret turn forever whenever the model tends
                    # to no-op.
                    self._pillar_close_cycle("nature")
                    return
                entry["belief"] = parsed["belief"]
                entry["confidence"] = parsed["confidence"]
                entry["subject"] = parsed["subject"]
                entry["revised_tick"] = tick
                entry["revision_count"] = entry.get("revision_count", 0) + 1
                self._log("nature_belief_revised", f"The land's own sense of {entry['subject']} shifted: {entry['belief']}")
                # B1 Pillar abstraction (roadmap Stage II step 4): mirror
                # the same revision into Nature's own world_model —
                # `nature_beliefs` stays the field every existing reader
                # uses, this is additive proof of the pillar shape.
                self.world.nature_pillar.upsert_world_model(
                    tick, entry["subject"], entry["belief"], entry["confidence"],
                    source="nature_mind", revises_id=entry.get("pillar_entry_id"),
                )
            else:
                entry = {
                    "subject": parsed["subject"], "belief": parsed["belief"], "confidence": parsed["confidence"],
                    "formed_tick": tick, "revised_tick": tick, "revision_count": 0,
                }
                self.world.nature_beliefs.append(entry)
                if len(self.world.nature_beliefs) > beliefs.MAX_BELIEFS:
                    weakest = min(self.world.nature_beliefs, key=lambda b: b["confidence"])
                    self.world.nature_beliefs.remove(weakest)
                self._log("nature_belief_formed", f"The land came to hold a sense of {entry['subject']}: {entry['belief']}")
                pillar_entry = self.world.nature_pillar.upsert_world_model(
                    tick, entry["subject"], entry["belief"], entry["confidence"], source="nature_mind",
                )
                entry["pillar_entry_id"] = pillar_entry["id"]
                self.world.nature_pillar.remember(f"Came to sense {entry['subject']}: {entry['belief']}")
                # Vision doc item 2.3 ("Nature and Village can surprise
                # each other"): a genuinely NEW belief (not a revision
                # of an existing one) is real fresh insight the land
                # has formed — bump the origin settlement's existing
                # pattern-signal counter so it can, on its own pressure
                # threshold, feed straight into an ontology/rule
                # proposal the Village pillar didn't originate itself.
                origin_settlement.pattern_signal_counts["nature_adaptation"] = (
                    origin_settlement.pattern_signal_counts.get("nature_adaptation", 0) + 1
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage III
                # step 11), the Nature->Village arrow: the same genuine
                # fresh insight that bumps the pattern-signal counter
                # above is real enough to actually tell Village about.
                # `disagrees_with` gives "disagreement persists" a
                # mechanical trigger — Village already holding a
                # confident theory about the recognizably same subject
                # is real tension worth flagging as `disagreement`
                # rather than a routine `warning`/`observation`.
                message_kind = (
                    "disagreement" if self.world.village_pillar.disagrees_with(entry["subject"])
                    else ("warning" if entry["confidence"] >= 0.6 else "observation")
                )
                self._send_pillar_message(
                    "nature", "village", message_kind,
                    f"the land senses {entry['subject']}: {entry['belief']}",
                )
            concept_data = nature_mind.parse_concept(result)
            if concept_data is not None and not ontology.is_near_duplicate(
                self.world, concept_data["name"], concept_data["description"],
            ):
                concept = ontology.register_concept(
                    self.world, name=concept_data["name"], description=concept_data["description"],
                    category="ecological", origin_settlement_id=origin_settlement_id, tick=tick,
                )
                self._log("ontology", f"The land itself gave rise to {concept.name}: {concept.description}")
            # B2: interpret/remember/plan/act/reflect all completed
            # synchronously above — close the cycle, freeing the
            # working memory this turn consumed.
            self._pillar_close_cycle("nature")

        # Nature's Mind is a pillar-cognition/ontology-origination task
        # (v1.3.37).
        self._schedule_llm_job(
            "nature_mind", prompt, nature_mind.SYSTEM_PROMPT, fallback, apply, critical=True,
            deep_reasoning=True,
        )

    def _maybe_schedule_species_variant(self, events: list[str]) -> None:
        """Vision doc item 4.2 ("Emergent species/variants via
        parameter-space"): Nature naming a real existing wildlife herd
        — an existing `Species` given an LLM-authored identity and a
        closed-vocabulary trait, grounded in the land's own real recent
        condition. World-scoped, year_end cadence (rarer than `nature_
        mind` — a named variant is a bigger event than an ordinary
        belief revision), `critical=False` — ambient world-building
        texture with a real deterministic fallback name, same tier as
        `_maybe_schedule_composite_entity`. Never touches `AnimalHerd`'s
        own mechanics/native-index parity (R7) — identity only this
        pass, see `wildlife.SPECIES_VARIANT_TRAITS`'s docstring."""
        if not self._season_year_gate(events, "species_variant", "year_end"):
            return
        named_herd_ids = {v.herd_id for v in self.world.species_variants.values()}
        candidates = [h for h in self.world.wildlife.herds.values() if h.id not in named_herd_ids]
        if not candidates:
            return
        herd = min(candidates, key=lambda h: h.id)
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("species_variant")
        wildlife_summary = self.world.wildlife.summary()
        condition_bits = [f"{k.replace('_', ' ')}: {v}" for k, v in wildlife_summary.items()]
        condition_text = "; ".join(condition_bits) if condition_bits else "The land is quiet."
        existing_names = [v.name for v in self.world.species_variants.values()]
        prompt = species_variant.build_prompt(herd.species.value, condition_text, existing_names)
        fallback = species_variant.fallback_variant(len(existing_names))
        herd_id, species_value = herd.id, herd.species.value
        tick = self.world.clock.tick_count

        def apply(result: dict, used_fallback: bool) -> None:
            if herd_id not in self.world.wildlife.herds:
                return  # the herd died out while the call was in flight
            parsed = species_variant.parse_variant(result, fallback)
            variant_id = self.world.next_species_variant_id
            self.world.next_species_variant_id += 1
            variant = SpeciesVariant(
                id=variant_id, name=parsed["name"], species=species_value, herd_id=herd_id,
                trait=parsed["trait"], description=parsed["description"], tick_named=tick,
            )
            self.world.species_variants[variant_id] = variant
            if len(self.world.species_variants) > MAX_SPECIES_VARIANTS_STORED:
                oldest_id = min(self.world.species_variants, key=lambda i: self.world.species_variants[i].tick_named)
                del self.world.species_variants[oldest_id]
            self._log("species_variant_named", f"The land gave rise to {variant.name} — {variant.description}")
            # Tier 0 second slice (docs/ROADMAP-2026-07-REMAINING.md):
            # species_variant becomes Nature pillar's SECOND real wired
            # job, alongside nature_mind — a named variant is a settled
            # fact about the land, hence "observation".
            self.world.nature_pillar.upsert_world_model(
                tick, variant.name, variant.description, 1.0,
                status="observation", source="species_variant",
            )
            self.world.nature_pillar.remember(f"The land gave rise to {variant.name}: {variant.description}")

        self._schedule_llm_job("species_variant", prompt, species_variant.SYSTEM_PROMPT, fallback, apply)

    def _maybe_spread_concepts(self) -> None:
        """Zero-LLM-cost, every-tick, rare-roll adoption growth for
        `proposed`/`spreading` concepts — the minimal spread mechanism
        Phase 1.A ships with (a documented simplification: full reuse
        of `invention_knowledge`'s teach/lose/rediscover lifecycle for
        every ontology category is flagged as a follow-up, not
        attempted this pass — see docs/VISION-2026-07-21-SELFEVOLVING.
        md). A random core-cast member of the concept's origin
        settlement who isn't already an adopter has a small chance to
        become one each tick a growing concept exists."""
        growing = [c for c in self.world.invented_concepts.values() if c.status in ("proposed", "spreading")]
        if not growing:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "ontology_spread")
        for concept in growing:
            if rng.random() >= CONCEPT_SPREAD_CHANCE_PER_TICK:
                continue
            candidates = [
                a for a in self.world.population.agents
                if a.settlement_id == concept.origin_settlement_id
                and a.id in self.world.population.core_agent_ids
                and a.id not in concept.adopter_ids
            ]
            if not candidates:
                continue
            # A17 first slice: spread traces the real relationship graph
            # (memetics.weighted_spread_target) instead of a uniform pick
            # — a candidate close to an existing adopter is more likely
            # to be next. Empty `carriers` (a concept's first-ever
            # adopter) degrades to uniform via the baseline weight.
            carriers = [a for a in self.world.population.agents if a.id in concept.adopter_ids]
            chosen = memetics.weighted_spread_target(candidates, carriers, rng)
            status_before = concept.status
            ontology.add_adopter(self.world, concept.id, chosen.id, self.world.clock.tick_count)
            if status_before != "established" and concept.status == "established":
                # A22 Emergence API: a concept crossing into "established"
                # is the one genuinely novel-combination moment in its
                # whole lifecycle (proposed/spreading are just growth
                # toward this) — see `world/ontology.py`'s `maybe_
                # promote_status`.
                origin = self._settlement_by_id(concept.origin_settlement_id)
                self._append_emergence(
                    "novel_combination", "ontology",
                    f"'{concept.name}' ({concept.category}) has become an established part of "
                    f"{origin.name if origin else 'the village'}'s life.",
                    pillars=("innovation", "village"), settlement=origin.name if origin else None,
                    data={"concept_id": concept.id, "category": concept.category},
                )

    # --- vision doc item 1.2: trigger→effect rules as data ---------------------

    def _apply_trigger_rules_for(self, trigger: str, settlement) -> None:
        """Fires every ACTIVE `TriggerRule` bound to `trigger` and
        originated by `settlement` — a rule is settlement-scoped, same
        as an `InventedConcept`'s mechanical hook. Cooldown-gated
        (`TRIGGER_RULE_COOLDOWN_TICKS`) so a burst of matching events
        in quick succession can't turn one village custom into
        runaway repeated narration. Called from each trigger's real
        detection point (dispute/invention application callbacks, or
        `_apply_trigger_rules_from_life_events`/`_maybe_tick_trigger_
        state_edges` below) — never on a schedule of its own."""
        now = self.world.clock.tick_count
        for rule in self.world.trigger_rules.values():
            if rule.status != "active" or rule.origin_settlement_id != settlement.id:
                continue
            # Vision item 1.1 (composable hooks): a rule's primary and
            # secondary side are independent triggers with independent
            # effects and independent cooldowns — either can fire this
            # call, neither is required to fire alongside the other.
            if rule.trigger == trigger:
                if rule.last_fired_tick < 0 or now - rule.last_fired_tick >= ontology.TRIGGER_RULE_COOLDOWN_TICKS:
                    rule.fire_count += 1
                    rule.last_fired_tick = now
                    self._log("trigger_rule", f"{rule.name}: {rule.description}")
                    self._apply_trigger_rule_hook(rule.hook_type, rule.magnitude, settlement)
            if rule.secondary_trigger and rule.secondary_trigger == trigger:
                if (
                    rule.secondary_last_fired_tick < 0
                    or now - rule.secondary_last_fired_tick >= ontology.TRIGGER_RULE_COOLDOWN_TICKS
                ):
                    rule.secondary_last_fired_tick = now
                    self._log("trigger_rule", f"{rule.name} (secondary): {rule.description}")
                    self._apply_trigger_rule_hook(rule.secondary_hook_type, rule.secondary_magnitude, settlement)

    def _apply_trigger_rule_hook(self, hook_type: str, magnitude: float, settlement) -> None:
        """Only `belief_confidence_bonus` is actually consumed as a
        real numeric effect this pass — see `llm/rule_propose.py`'s
        module docstring for why the other hook types (skill_yield_
        bonus, goal_flavor_bias) stay narrative-only for now, same
        flagged-not-silently-dropped honesty as InventedConcept's own
        not-yet-consumed hooks. Shared by a rule's primary and
        secondary side (item 1.1) so both go through one real
        consumer, not two copies."""
        if hook_type == "belief_confidence_bonus" and settlement.beliefs:
            target = max(settlement.beliefs, key=lambda b: b["confidence"])
            target["confidence"] = clamp(target["confidence"] + magnitude, 0.0, 1.0)

    def _apply_trigger_rules_from_life_events(self) -> None:
        """`on_death`/`on_birth` detection — reads `World.last_life_
        events` (already computed by `World.tick()` this same tick),
        the same shared vocabulary many other jobs already key off of.
        Applied settlement-wide (every settlement checks every fired
        category) since life events aren't settlement-tagged in the
        tuple; `_apply_trigger_rules_for`'s own settlement-id filter
        means each settlement only ever fires its OWN rules."""
        if not self.world.trigger_rules:
            return
        categories = {category for category, _ in self.world.last_life_events}
        trigger_map = {"death": "on_death", "birth": "on_birth"}
        fired = {trigger_map[c] for c in categories if c in trigger_map}
        if not fired:
            return
        for settlement in self.world.settlements:
            for trigger in fired:
                self._apply_trigger_rules_for(trigger, settlement)

    def _maybe_tick_trigger_state_edges(self) -> None:
        """`on_drought`/`on_surplus` detection — these two triggers
        aren't discrete events, they're a low->high crossing of an
        ongoing state (`World.disasters.heat_pressure`, a settlement's
        granary fill fraction), so a naive "check every tick" would
        fire every tick the state stays above threshold. Tracks each
        settlement's previous-tick boolean state in a transient
        (non-persisted) dict — same precedent as `_recent_line_tails`
        — and only fires on the false->true edge. A rule can still
        re-fire on a later edge once its own cooldown clears."""
        if not self.world.trigger_rules:
            return
        drought_now = self.world.disasters.heat_pressure > TRIGGER_DROUGHT_HEAT_PRESSURE_THRESHOLD
        for settlement in self.world.settlements:
            if drought_now and not self._prev_drought_state.get(settlement.id, False):
                self._apply_trigger_rules_for("on_drought", settlement)
            self._prev_drought_state[settlement.id] = drought_now

            # Cheap direct count, NOT settlement.summary() — summary()
            # also computes vehicle/era-infrastructure stats irrelevant
            # here and is expensive enough that calling it every tick
            # for every settlement measurably slowed the tick loop
            # (caught live during this feature's own soak verification).
            granaries = [
                b for b in settlement.buildings
                if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
            ]
            capacity = len(granaries) * GRANARY_CAPACITY
            fill = (sum(b.stored_food for b in granaries) / capacity) if capacity else 0.0
            surplus_now = fill > TRIGGER_SURPLUS_FILL_THRESHOLD
            if surplus_now and not self._prev_surplus_state.get(settlement.id, False):
                self._apply_trigger_rules_for("on_surplus", settlement)
            self._prev_surplus_state[settlement.id] = surplus_now

    def _maybe_tick_composite_reactions(self) -> None:
        """A18 first slice (roadmap Stage IV step 25, docs/MASTERCHECKLIST
        -2026-07-22.md): the general AND-combination reaction check —
        `world/reactions.py`'s registry is the open-ended part, this is
        the fixed engine, same "engine is general, content is data"
        split `_apply_trigger_rules_for` established for `TriggerRule`.
        Deliberately independent of `_maybe_tick_trigger_state_edges`
        (which early-returns with no `TriggerRule`s stored) — a
        composite reaction has nothing to do with village-authored
        trigger rules and must keep working with none stored."""
        if not self.world.settlements:
            return
        drought_now = self.world.disasters.heat_pressure > TRIGGER_DROUGHT_HEAT_PRESSURE_THRESHOLD
        now = self.world.clock.tick_count
        for settlement in self.world.settlements:
            granaries = [
                b for b in settlement.buildings
                if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
            ]
            capacity = len(granaries) * GRANARY_CAPACITY
            fill = (sum(b.stored_food for b in granaries) / capacity) if capacity else 0.0
            food_shortage_now = fill < reactions.FOOD_SHORTAGE_FILL_THRESHOLD
            families = [i for i in settlement.institutions if i.kind is InstitutionKind.FAMILY]
            feuding_pair = next(
                (
                    (fam_a, fam_b)
                    for fam_a in families for fam_b in families
                    if fam_a.id < fam_b.id and Population.families_feuding(fam_a, fam_b)
                ),
                None,
            )
            active: set[str] = set()
            if drought_now:
                active.add("drought")
            if food_shortage_now:
                active.add("food_shortage")
            if feuding_pair is not None:
                active.add("feud")
            for reaction in reactions.matching_reactions(active):
                key = (settlement.id, reaction.name)
                last_fired = self._composite_reaction_last_fired.get(key)
                if last_fired is not None and now - last_fired < reactions.COMPOSITE_REACTION_COOLDOWN_TICKS:
                    continue
                self._composite_reaction_last_fired[key] = now
                self._apply_composite_reaction(reaction, settlement, feuding_pair)

    def _apply_composite_reaction(self, reaction, settlement, feuding_pair) -> None:
        """The one real consequence this slice ships: escalates the
        feuding pair's relationship rupture — a bounded, immediate
        step, not a new combat/raid mechanic (see `world/reactions.py`'s
        module docstring for why). `feuding_pair` is guaranteed non-None
        whenever a reaction naming `"feud"` in its conditions matches
        (the only reaction this pass ships does)."""
        detail = f"{settlement.name or 'The village'}: {reaction.description}"
        self._log("composite_reaction", detail)
        self._append_highlight("composite_reaction", detail)
        self._append_emergence(
            "unexplained_shift", "village", detail,
            pillars=("village", "humans"), settlement=settlement.name,
            data={"reaction": reaction.name, "conditions": sorted(reaction.conditions)},
        )
        if feuding_pair is None:
            return
        fam_a, fam_b = feuding_pair
        members_a = [a for a in self.world.population.agents if a.id in fam_a.member_agent_ids]
        members_b = [a for a in self.world.population.agents if a.id in fam_b.member_agent_ids]
        for a in members_a:
            for b in members_b:
                a.relationships[b.id] = clamp(
                    a.relationships.get(b.id, 0.0) - reactions.COMPOSITE_REACTION_RELATIONSHIP_PENALTY, -1.0, 1.0,
                )
                b.relationships[a.id] = clamp(
                    b.relationships.get(a.id, 0.0) - reactions.COMPOSITE_REACTION_RELATIONSHIP_PENALTY, -1.0, 1.0,
                )

    def _maybe_schedule_rule_proposal(self, events: list[str]) -> None:
        """Vision doc item 1.2's origination half — one new trigger-
        rule proposal per season at most, world-scoped (`_job_target`
        round-robins settlements like `_maybe_schedule_ontology_
        proposal`). `critical=False`: this is ambient village
        imagination, same tier as the ontology/culture jobs it sits
        beside — the real safety gate is item 1.3's sandbox in `apply`,
        not the fallback/critical distinction (a fallback-authored rule
        still goes through the same sandbox check as an LLM one)."""
        if not self._season_year_gate(events, "rule_propose", "season_end"):
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("rule_propose")
        # Item 5.1's runtime acceptance auditor: same "run it on this
        # job's own gated cadence" precedent as ontology.abandon_stale.
        ontology.retire_stale_rules(self.world, self.world.clock.tick_count)
        settlement = self._job_target()
        if not settlement.name:
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        existing_names = [
            r.name for r in self.world.trigger_rules.values()
            if r.origin_settlement_id == settlement.id and r.status == "active"
        ]
        # Vision item 2.2: ground the proposal in whichever institution
        # has wanted the same thing longest, if any has stuck around
        # long enough to count as real (not fresh-noise) frustration.
        stuck_institution = max(
            (i for i in settlement.institutions if i.objective_ticks_unmet >= institutions.INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD),
            key=lambda i: i.objective_ticks_unmet, default=None,
        )
        institution_grounding = ""
        stuck_label = ""
        if stuck_institution is not None:
            stuck_label = (
                "council of elders" if stuck_institution.kind is InstitutionKind.COUNCIL
                else f"{stuck_institution.name} guild" if stuck_institution.kind is InstitutionKind.GUILD
                else "a family"
            )
            institution_grounding = (
                f"The {stuck_label} has wanted to {stuck_institution.objective} for a long "
                "stretch now, without it happening."
            )
        prompt = rule_propose.build_prompt(settlement.name, recent, existing_names, institution_grounding)
        fallback = rule_propose.fallback_propose(len(existing_names))
        origin_settlement_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = rule_propose.parse_propose(result, fallback)
            target = self._settlement_by_id(origin_settlement_id)
            if target is None:
                return

            async def _sandbox_and_register() -> None:
                # Item 1.3: never let a proposed rule go live without
                # first proving it doesn't crash the population on a
                # disposable fork — see simulation/sandbox.py.
                verdict = await run_counterfactual(self.world, self.world.config)
                if not verdict["safe"]:
                    self._log(
                        "trigger_rule_rejected",
                        f"A proposed rule ({parsed['name']}) was discarded by the counterfactual "
                        f"sandbox: {verdict['reason']}.",
                    )
                    return
                rule = ontology.register_trigger_rule(
                    self.world, name=parsed["name"], description=parsed["description"],
                    trigger=parsed["trigger"], hook_type=parsed["hook_type"], hook_target=parsed["hook_target"],
                    magnitude=parsed["magnitude"], origin_settlement_id=origin_settlement_id,
                    tick=self.world.clock.tick_count,
                    secondary_trigger=parsed["secondary_trigger"], secondary_hook_type=parsed["secondary_hook_type"],
                    secondary_hook_target=parsed["secondary_hook_target"],
                    secondary_magnitude=parsed["secondary_magnitude"],
                )
                message = f"{target.name or 'The village'} adopted a new rule: {rule.name} — {rule.description}"
                if stuck_label:
                    message += f" (long-standing want of the {stuck_label})"
                if rule.secondary_trigger:
                    message += f" — also bound to {rule.secondary_trigger.replace('_', ' ')}"
                self._log("rule_originated", message)
                # Tier 0 third slice (docs/ROADMAP-2026-07-REMAINING.
                # md): rule_propose becomes Village pillar's FOURTH
                # real wired job, alongside beliefs/institution_belief/
                # dispute — a rule that survived the counterfactual
                # sandbox and went live is a real settled civic fact,
                # hence "observation" rather than "hypothesis".
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, rule.name, rule.description, 1.0,
                    status="observation", source="rule_propose",
                )
                self.world.village_pillar.remember(f"Adopted a new rule: {rule.name} — {rule.description}")

            task = asyncio.create_task(_sandbox_and_register())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # The game learning/improving itself: a self-modifying trigger
        # rule is exactly the kind of proposal that should be reasoned
        # through, not narrated (v1.3.37).
        self._schedule_llm_job("rule_propose", prompt, rule_propose.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
        life). The branch itself (see llm/era_branch.py) is computed
        deterministically from the settlement's own real standing-
        building mix and applied immediately — real, bounded emergent
        divergence between settlements reaching the same era via the
        same tech path, never an LLM impression of it. The one LLM call
        this still schedules is narration-only: one sentence explaining
        the already-computed lean, never a second vote on what it is."""
        rng = namespaced_rng(self.world.config.seed, self.world.clock.tick_count, f"era_branch_{settlement.id}")
        branch, scores = era_branch.compute_branch(settlement, rng)
        settlement.era_branch = branch
        fallback = era_branch.fallback_reason()
        prompt = era_branch.build_prompt(settlement.name, new_era, branch, scores)
        branch_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            reason = era_branch.parse_reason(result, fallback)
            target = self._settlement_by_id(branch_target_id)
            if target is None or not reason:
                return
            self._log("era_branch", f"{target.name or 'The village'} is leaning {branch} — {reason}")
            # Tier 0 ninth slice (docs/ROADMAP-2026-07-REMAINING.md):
            # era_branch becomes Innovation pillar's FIFTH real wired
            # job — the branch itself is a real, already-settled
            # decision (computed deterministically above), so this is
            # an observation, not a hypothesis, same treatment
            # composite_entity gets.
            self.world.innovation_pillar.upsert_world_model(
                self.world.clock.tick_count, f"{target.name or 'the village'}'s tech-path lean",
                f"Leaning {branch} — {reason}", 1.0, status="observation", source="era_branch",
            )
            self.world.innovation_pillar.remember(f"{target.name or 'The village'} is leaning {branch}: {reason}")

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
            affected = self.world.population.hold_festival(settlement, ritual_activity=self.world.ritual_activity)
            self._log("festival", f"{settlement.name or 'The village'} held {entry} ({affected} bonds strengthened)")
            # Tier 0 thirteenth slice: festival becomes Village
            # pillar's eighth real wired job — memory-only, an
            # occurrence rather than a standing fact.
            self.world.village_pillar.remember(f"Held a festival — {entry}")

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
            # Tier 0 fourteenth slice: religion becomes Village
            # pillar's ninth real wired job — a crystallized faith is a
            # real, high-confidence settled fact, same treatment
            # rule_propose/laws already get.
            self.world.village_pillar.upsert_world_model(
                tick, f"{stl.name or 'the village'}'s faith", f"{parsed['name']}: {'; '.join(parsed['tenets'])}",
                1.0, status="observation", source="religion",
            )
            self.world.village_pillar.remember(f"Came to share a faith called {parsed['name']}.")

        # Cultural evolution: crystallizing a religion from a repeated
        # ritual is a real interpretive act (v1.3.37).
        self._schedule_llm_job("religion", prompt, religion.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

    def _maybe_schedule_narrative_direction(self, events: list[str]) -> None:
        """Quarterly (season_end — a season already IS a real-calendar
        quarter, no new cadence machinery needed), one call: names the
        theme running through the settlement's recent life. Consumed
        ONLY as prompt bias (see `_narrative_theme_bias` below) — never
        schedules or scripts anything on its own. See llm/narrative_
        direction.py's module docstring.

        The theme itself is computed deterministically (explicit user
        directive) from `Settlement.mood`'s own real axes — applied
        immediately, before any LLM call. The LLM's remaining job is a
        grounded one-sentence summary, plus its genuinely creative side
        task of coining a local term for a dominant event.

        B1-B3 (roadmap Stage II, generalized from Nature): `World.
        humans_pillar` mirrors this job's theme-naming into world_model
        — B7's "collective consciousness (mood/values/direction)" read
        literally, since `Settlement.mood` is itself the aggregate of
        living agents' `Agent.emotions`. A quarterly `observe` turn
        reads the Emergence API into bounded `working_memory`; the
        FOLLOWING quarter is the real `interpret` call, grounded in
        what was observed."""
        target = self._job_target()
        if not self._season_year_gate(events, "narrative_direction", "season_end") or not target.name:
            return
        if self._pillar_observe_turn("humans"):
            self._mark_season_year_resolved("narrative_direction")
            return
        if self._pillar_interpret_backpressured("humans"):
            return
        self._mark_season_year_resolved("narrative_direction")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        mood = dict(target.mood)
        themes = narrative_direction.compute_themes(mood)
        target.narrative_themes.append({"themes": themes, "formed_tick": self.world.clock.tick_count})
        if len(target.narrative_themes) > NARRATIVE_THEMES_MAX_STORED:
            target.narrative_themes = target.narrative_themes[-NARRATIVE_THEMES_MAX_STORED:]
        prompt = narrative_direction.build_prompt(
            target.name, themes, recent, target.folklore, mood, target.lexicon,
            emergence_observations=list(self.world.humans_pillar.working_memory),
        )
        fallback = narrative_direction.fallback_summary()
        target_id = target.id
        # B1 Pillar abstraction, generalized: no natural per-subject
        # `revises` scheme exists here (`narrative_themes` is a plain
        # append-only log, not a revisable belief list) — each turn's
        # mirror is always a fresh world_model entry. Confidence has no
        # native source either; the strongest mood axis's magnitude is
        # the closest real signal for "how pronounced is this theme."
        mood_confidence = max((abs(v) for v in mood.values()), default=0.5)

        def apply(result: dict, used_fallback: bool) -> None:
            stl = self._settlement_by_id(target_id)
            if stl is None:
                self._pillar_close_cycle("humans")
                return
            summary = narrative_direction.parse_summary(result, fallback)
            self._log(
                "narrative_direction",
                f"{stl.name}'s recent life reads as: {', '.join(themes)}." + (f" {summary}" if summary else ""),
            )
            self.world.humans_pillar.upsert_world_model(
                self.world.clock.tick_count, ", ".join(themes) or "the village's mood",
                summary or f"{stl.name}'s recent life reads as: {', '.join(themes)}.",
                mood_confidence, source="narrative_direction",
            )
            self.world.humans_pillar.remember(f"The village's mood read as: {', '.join(themes)}.")
            # §2 "dialect drift": a real answer only, never fabricated by
            # the fallback (fallback_summary has no coined_term field at
            # all) — rides this call for zero added LLM volume.
            if not used_fallback:
                coined = narrative_direction.parse_coined_term(result)
                if coined is not None:
                    term, meaning = coined
                    # C2 "The intention channel": the Body validates
                    # this real state-creating proposal before executing
                    # it — see validate_coined_term's docstring. An
                    # exact duplicate coinage is silently dropped, same
                    # "not every call produces visible output" discipline
                    # as a rejected/near-duplicate ontology proposal.
                    if narrative_direction.validate_coined_term(term, stl.lexicon):
                        stl.lexicon.append({"term": term, "meaning": meaning, "formed_tick": self.world.clock.tick_count})
                        if len(stl.lexicon) > LEXICON_MAX_STORED:
                            stl.lexicon = stl.lexicon[-LEXICON_MAX_STORED:]
                        self._log("dialect_coined", f"{stl.name} has started calling it \"{term}\" — {meaning}")
            self._pillar_close_cycle("humans")

        # Cultural evolution: naming the emergent theme is interpretation
        # over a real computed mood signal (v1.3.37).
        self._schedule_llm_job("narrative_direction", prompt, narrative_direction.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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

        # Cultural evolution (v1.3.37).
        self._schedule_llm_job("culture_digest", prompt, culture_digest.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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

        # Cultural evolution: an institution's own independent character
        # (v1.3.37).
        self._schedule_llm_job(
            "institution_culture", prompt, institution_culture.SYSTEM_PROMPT, fallback, apply,
            settlement=settlement.name, deep_reasoning=True,
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

        # Town consciousness: choosing at most one deniable intervention
        # is exactly the kind of long-horizon judgment reasoning helps
        # with (v1.3.37).
        self._schedule_llm_job(
            "consciousness", prompt, consciousness.SYSTEM_PROMPT, fallback, apply, critical=True,
            settlement=target.name, deep_reasoning=True,
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

    # --- Phase 5.A/5.B "self-evolving world" — Reflection, the fifth participant ---

    def _detect_reflection_pattern(self) -> dict | None:
        """Deterministic pattern-detection pass across all four
        pillars' Body state and existing signal counters — no new
        instrumentation (docs/VISION-2026-07-21-SELFEVOLVING.md, Phase
        5.B item 1). Checked in a fixed priority order; returns the
        first pattern that clears a real threshold, or `None` if
        nothing does this cycle — reflection genuinely has "nothing
        notable to say" most cycles, which is correct, not a gap."""
        for settlement in self.world.settlements:
            counts = settlement.pattern_signal_counts
            for category, count in counts.items():
                if count >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
                    label = category.replace("_", " ")
                    return {
                        "subject": f"{label} in {settlement.name or 'the village'}",
                        "description": f"{count} {label} occurrences recently in {settlement.name or 'the village'}.",
                    }
        wildlife_summary = self.world.wildlife.summary()
        if wildlife_summary.get("prey_scarce"):
            return {
                "subject": "prey scarcity",
                "description": (
                    f"{wildlife_summary['grazer_herds']} grazer herds against "
                    f"{wildlife_summary['predator_packs']} predator packs — prey is scarce."
                ),
            }
        if wildlife_summary.get("predator_pressure_ratio", 0.0) > 0.25:
            return {
                "subject": "predator pressure",
                "description": f"predator pressure ratio {wildlife_summary['predator_pressure_ratio']:.2f} against grazer population.",
            }
        established = [c for c in self.world.invented_concepts.values() if c.status == "established"]
        if len(established) >= REFLECTION_ONTOLOGY_IMBALANCE_MIN_TOTAL:
            counts_by_cat: dict[str, int] = {}
            for c in established:
                counts_by_cat[c.category] = counts_by_cat.get(c.category, 0) + 1
            if len(counts_by_cat) >= 2:
                top_cat = max(counts_by_cat, key=lambda k: counts_by_cat[k])
                bottom_cat = min(counts_by_cat, key=lambda k: counts_by_cat[k])
                top_n, bottom_n = counts_by_cat[top_cat], counts_by_cat[bottom_cat]
                if bottom_n > 0 and top_n >= bottom_n * REFLECTION_ONTOLOGY_IMBALANCE_RATIO:
                    return {
                        "subject": "ontology imbalance",
                        "description": (
                            f"{top_n} established '{top_cat}' concepts against only {bottom_n} "
                            f"'{bottom_cat}' concepts, out of {len(established)} established total."
                        ),
                    }
        # Vision doc item 5.3 ("coherence/drift detection"): the
        # ontology's own immune-system signal — a village that's
        # inventing constantly but nothing is actually catching on is
        # incoherent growth, not healthy emergence. Checked before the
        # imbalance branch above since a bloated-but-abandoned registry
        # is the more urgent read.
        total_concepts = len(self.world.invented_concepts)
        if total_concepts >= REFLECTION_COHERENCE_MIN_TOTAL:
            abandoned = sum(1 for c in self.world.invented_concepts.values() if c.status == "abandoned")
            abandoned_fraction = abandoned / total_concepts
            if abandoned_fraction >= REFLECTION_COHERENCE_ABANDONED_RATIO:
                return {
                    "subject": "ontology coherence",
                    "description": (
                        f"{abandoned} of {total_concepts} invented concepts were abandoned "
                        f"(never caught on) — the village may be imagining faster than it can absorb."
                    ),
                }
        # Vision doc item 1.4's own worked example — a genuine governor
        # drift, grounded only in Body state (WILDFIRE_CHANCE_PER_WEEK's
        # theoretical rate vs. the realized gap between ignitions),
        # never a free-text hunch.
        ticks = self.world.wildfire_ignition_ticks
        if len(ticks) >= GOVERNOR_DRIFT_MIN_SAMPLES:
            realized_gap = (ticks[-1] - ticks[0]) / (len(ticks) - 1)
            ticks_per_week = 7 * self.world.config.minutes_per_day / self.world.config.sim_minutes_per_tick
            theoretical_gap = ticks_per_week / WILDFIRE_CHANCE_PER_WEEK
            if theoretical_gap > 0 and realized_gap > 0:
                ratio = max(realized_gap / theoretical_gap, theoretical_gap / realized_gap)
                if ratio >= GOVERNOR_DRIFT_RATIO:
                    direction = "far rarer" if realized_gap > theoretical_gap else "far more frequent"
                    return {
                        "subject": "wildfire frequency",
                        "description": (
                            f"wildfires are firing {direction} than the configured rate implies — "
                            f"realized ~{realized_gap:.0f} ticks between ignitions against a theoretical "
                            f"~{theoretical_gap:.0f}."
                        ),
                    }
        return None

    def _reevaluate_reflection_hypotheses(self, current_pattern: dict | None) -> None:
        """5.B item 3: existing OPEN hypotheses re-evaluated against
        fresh evidence every firing — deterministic, no LLM call. A
        hypothesis whose own subject matches this cycle's detected
        pattern gains confidence (the pattern recurred); one that
        doesn't match loses a little (its supporting evidence didn't
        renew this cycle). Crossing the supported/rejected threshold
        transitions status; the entry itself is never deleted."""
        tick = self.world.clock.tick_count
        for entry in self.world.reflection_notebook:
            if entry.get("status") != "open" or entry.get("kind") != "hypothesis":
                continue
            recurred = current_pattern is not None and entry.get("subject") == current_pattern["subject"]
            step = REFLECTION_CONFIDENCE_STEP if recurred else -REFLECTION_CONFIDENCE_STEP
            entry["confidence"] = round(max(0.0, min(1.0, entry["confidence"] + step)), 3)
            if recurred:
                entry.setdefault("evidence_for", []).append(current_pattern["description"])
            if entry["confidence"] >= REFLECTION_SUPPORTED_THRESHOLD:
                entry["status"] = "supported"
                self._append_reflection_conclusion(entry, tick, confirmed=True)
            elif entry["confidence"] <= REFLECTION_REJECTED_THRESHOLD:
                entry["status"] = "rejected"
                entry.setdefault("evidence_against", []).append(
                    f"confidence fell below threshold at tick {tick} without recurring evidence"
                )
                self._append_reflection_conclusion(entry, tick, confirmed=False)

    def _append_reflection_conclusion(self, hypothesis: dict, tick: int, confirmed: bool) -> None:
        """Audit follow-up ("reflection kind='question'/'conclusion'
        entries", flagged in the v1.3.38 cognition-architecture audit):
        the deterministic counterpart to the LLM-authored hypothesis —
        zero new LLM call, fires exactly once at the moment
        `_reevaluate_reflection_hypotheses` above transitions a
        hypothesis out of `open`. Never deleted, same append-only
        discipline as everything else in this notebook; `supersedes`
        points back at the hypothesis it concludes, keeping the DAG
        walkable the way `InventedConcept.lineage` already is.

        A22 Emergence API: a confirmed hypothesis is a genuine
        `opportunity` (the world learned something real about itself);
        a refuted one is an `unexplained_shift` (the pattern that
        prompted it didn't hold up — worth noting, not worth acting
        on). Both tagged `reflection` only — inferring which OTHER
        pillar a bare `subject` string belongs to would need fragile
        string matching; left for Stage II's pillar refactor, which
        will have real per-pillar context to draw on instead."""
        emergence_kind = "opportunity" if confirmed else "unexplained_shift"
        self._append_emergence(
            emergence_kind, "reflection",
            f"The hypothesis about {hypothesis['subject']} was "
            f"{'confirmed' if confirmed else 'refuted'} "
            f"(confidence settled at {hypothesis['confidence']:.2f}).",
            pillars=("reflection",), magnitude=hypothesis["confidence"],
        )
        entry_id = self.world.next_reflection_entry_id
        self.world.next_reflection_entry_id += 1
        verb = "confirmed" if confirmed else "refuted"
        content = (
            f"The hypothesis about {hypothesis['subject']} was {verb} "
            f"(confidence settled at {hypothesis['confidence']:.2f})."
        )
        self.world.reflection_notebook.append({
            "id": entry_id, "created_tick": tick, "kind": "conclusion",
            "subject": hypothesis["subject"], "content": content, "confidence": hypothesis["confidence"],
            "evidence_for": [], "evidence_against": [], "evidence_against_hint": "",
            "status": "confirmed" if confirmed else "refuted", "supersedes": hypothesis["id"],
        })
        self._log("reflection_conclusion", content)

    def _maybe_schedule_reflection_question(self, pattern: dict, hypothesis: dict) -> None:
        """Audit follow-up ("reflection kind='question' entries"): a
        genuine standing question about a pattern that already has an
        open hypothesis — same call slot `_maybe_schedule_reflection`
        would otherwise waste re-proposing a redundant hypothesis for.
        Skips if an open question already covers this exact hypothesis
        (asked once, not re-asked every year the hypothesis stays
        open)."""
        if any(
            e.get("kind") == "question" and e.get("status") == "open" and e.get("supersedes") == hypothesis["id"]
            for e in self.world.reflection_notebook
        ):
            return
        prompt = reflection.build_question_prompt(pattern, hypothesis)
        fallback = reflection.fallback_question(pattern)
        hypothesis_id = hypothesis["id"]

        def apply(result: dict, used_fallback: bool) -> None:
            question_text = reflection.parse_question(result, fallback)
            entry_id = self.world.next_reflection_entry_id
            self.world.next_reflection_entry_id += 1
            self.world.reflection_notebook.append({
                "id": entry_id, "created_tick": self.world.clock.tick_count, "kind": "question",
                "subject": pattern["subject"], "content": question_text, "confidence": None,
                "evidence_for": [], "evidence_against": [], "evidence_against_hint": "",
                "status": "open", "supersedes": hypothesis_id,
            })
            self._log("reflection_question", f"Hearthmind is still wondering: {question_text}")
            # Tier 0 third slice (docs/ROADMAP-2026-07-REMAINING.md):
            # reflection_question becomes Reflection pillar's THIRD
            # real wired job, alongside reflection/self_tuning — a
            # genuinely distinct call site (own job name, own prompt/
            # apply), not the same job as `reflection` reused. Memory-
            # only: an open question is explicitly not a settled
            # belief (status="open", confidence=None on the notebook
            # entry itself), so no world_model entry.
            self.world.reflection_pillar.remember(
                f"Still wondering about {pattern['subject']}: {question_text}"
            )

        self._schedule_llm_job(
            "reflection_question", prompt, reflection.SYSTEM_PROMPT_QUESTION, fallback, apply, deep_reasoning=True,
        )

    def _maybe_schedule_reflection(self, events: list[str]) -> None:
        """Phase 5.A/5.B (docs/VISION-2026-07-21-SELFEVOLVING.md,
        explicit user directive "Start the 5th item"): Reflection is a
        FIFTH participant observing the other four pillars' long-term
        behavior, not their objective state directly. Year-cadence
        (deliberately slower than any per-pillar Mind job — "decades
        and generations," not "every tick"), `critical=False`
        (ambient self-improvement, real deterministic "skip this cycle"
        fallback like every other narrative job — reflection never
        blocks or defers crucial per-pillar cognition).

        B1-B3 (roadmap Stage II, generalized from Nature): `World.
        reflection_pillar` mirrors this job's hypothesis formation the
        same way `nature_pillar` mirrors `nature_mind`. World-scoped
        (no settlement round-robin, matching this job's own shape) —
        a year-cadence `observe` turn reads the Emergence API into
        bounded `working_memory`; the FOLLOWING year is the real
        `interpret` turn (deterministic pattern detection/reevaluation
        always runs there, an LLM call only fires if a genuinely new
        pattern with no open hypothesis exists), closing back to
        `observe` once this year's turn is fully resolved either way."""
        if not self._season_year_gate(events, "reflection", "year_end"):
            return
        if self._pillar_observe_turn("reflection"):
            self._mark_season_year_resolved("reflection")
            self.world.reflection_pillar.turns_processed += 1
            return
        if self._pillar_interpret_backpressured("reflection"):
            return
        self._mark_season_year_resolved("reflection")
        self.world.reflection_pillar.turns_processed += 1
        pattern = self._detect_reflection_pattern()
        self._reevaluate_reflection_hypotheses(pattern)
        if pattern is None:
            self._pillar_close_cycle("reflection")
            return
        open_hypotheses = [
            e for e in self.world.reflection_notebook
            if e.get("status") == "open" and e.get("kind") == "hypothesis"
        ]
        # Don't spend a call re-proposing a hypothesis this exact
        # pattern already has an open explanation for — the fresh
        # evidence already fed it via _reevaluate_reflection_hypotheses
        # above. Ask a genuine open QUESTION about it instead (audit
        # follow-up, kind="question") rather than doing nothing this
        # cycle — same call slot, not extra volume.
        existing = next((e for e in open_hypotheses if e.get("subject") == pattern["subject"]), None)
        if existing is not None:
            self._maybe_schedule_reflection_question(pattern, existing)
            self._pillar_close_cycle("reflection")
            return
        prompt = reflection.build_prompt(
            pattern, open_hypotheses, emergence_observations=list(self.world.reflection_pillar.working_memory),
        )
        fallback = reflection.fallback_hypothesis(pattern)

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = reflection.parse_hypothesis(result, fallback)
            entry_id = self.world.next_reflection_entry_id
            self.world.next_reflection_entry_id += 1
            tick = self.world.clock.tick_count
            entry = {
                "id": entry_id, "created_tick": tick, "kind": "hypothesis",
                "subject": pattern["subject"], "content": parsed["hypothesis"],
                "confidence": parsed["confidence"],
                "evidence_for": [pattern["description"]],
                "evidence_against": [],
                "evidence_against_hint": parsed["evidence_against_hint"],
                "status": "open", "supersedes": None,
            }
            self.world.reflection_notebook.append(entry)
            self._log("reflection", f"Hearthmind formed a hypothesis about {pattern['subject']}: {parsed['hypothesis']}")
            self._append_emergence(
                "anomaly", "reflection",
                f"Hearthmind formed a hypothesis about {pattern['subject']}: {parsed['hypothesis']}",
                pillars=("reflection",), magnitude=parsed["confidence"],
            )
            # B1 Pillar abstraction, generalized: always-additive
            # mirror into Reflection's own world_model (content ->
            # belief; a fresh hypothesis is always new, no revision
            # path — resolution/confidence changes happen via
            # `_append_reflection_conclusion`, a separate deterministic
            # write, not this LLM call).
            self.world.reflection_pillar.upsert_world_model(
                tick, pattern["subject"], parsed["hypothesis"], parsed["confidence"],
                status="hypothesis", source="reflection",
            )
            self.world.reflection_pillar.remember(f"Hypothesized about {pattern['subject']}: {parsed['hypothesis']}")
            self._pillar_close_cycle("reflection")

        # The game learning/improving itself: Reflection proposes a
        # grounded hypothesis from real cross-pillar pattern signals —
        # the flagship "self-improvement" reasoning task (v1.3.37).
        self._schedule_llm_job(
            "reflection", prompt, reflection.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True,
        )

    @staticmethod
    def _governor_key_for_subject(subject: str) -> str | None:
        """B6 "Reflection as meta-scientist" (roadmap Stage III step
        13): `self_tuning.TUNABLE_GOVERNORS`'s global subjects
        ("wildfire frequency", "ontology coherence") match a hypothesis
        subject exactly; `_detect_reflection_pattern`'s SETTLEMENT-
        scoped subjects are `f"{label} in {settlement_name}"` (varies
        per settlement, so they can never appear verbatim in a fixed
        dict) — matched by PREFIX instead, so any settlement-scoped
        pattern reaches self-tuning once its own label is wired to a
        governor, without special-casing every settlement name."""
        for label, governor_key in self_tuning.TUNABLE_GOVERNORS.items():
            if subject == label or subject.startswith(label):
                return governor_key
        return None

    def _schedule_advisory(self, hypothesis: dict) -> None:
        """B6 "Reflection as meta-scientist" (roadmap Stage III step
        13): the "changes beyond governors" half — a supported
        hypothesis that names no tunable governor still gets a real
        response, just not a numeric nudge. `critical=True`, same
        reasoning as `_maybe_schedule_self_tuning` itself (a genuine
        judgment, not narrative texture); deferred rather than faked on
        a spent budget or failed call."""
        prompt = self_tuning.build_advisory_prompt(hypothesis["subject"], hypothesis["content"])
        fallback = self_tuning.fallback_advisory()
        hypothesis_id = hypothesis["id"]
        hypothesis_subject = hypothesis["subject"]

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = self_tuning.parse_advisory(result, fallback)
            advisory_id = self.world.next_advisory_id
            self.world.next_advisory_id += 1
            self.world.advisory_proposals.append({
                "id": advisory_id, "tick": self.world.clock.tick_count,
                "hypothesis_id": hypothesis_id, "subject": hypothesis_subject,
                "advice": parsed["advice"], "status": "pending",
            })
            self._log(
                "advisory",
                f"Hearthmind's own advice about {hypothesis_subject}: {parsed['advice']}",
            )

        self._schedule_llm_job(
            "self_tuning_advisory", prompt, self_tuning.SYSTEM_PROMPT_ADVISORY, fallback, apply,
            critical=True, deep_reasoning=True,
        )

    def _maybe_schedule_self_tuning(self, events: list[str]) -> None:
        """Vision doc items 1.4 + 2.4, docs/VISION-2026-07-22-
        LIVINGTERRARIUM.md: "self-tuning as bounded proposals" and "a
        Reflection that acts." World-scoped, year-cadence (deliberately
        the same "long period" as `_maybe_schedule_reflection` itself,
        never more often). Only fires when a `supported` hypothesis
        (survived `_reevaluate_reflection_hypotheses`'s deterministic
        evidence-nudging across multiple cycles, not a single-cycle
        guess) exists that hasn't been acted on yet; `critical=True` —
        a genuine, real judgment about the world's own balance,
        deferred rather than faked on a spent budget or failed call.

        B6 (roadmap Stage III step 13): a supported hypothesis whose
        subject names one of `self_tuning.TUNABLE_GOVERNORS` (by
        prefix, see `_governor_key_for_subject`) still takes the
        original bounded-nudge path, validated on a disposable forked
        copy of the world (item 1.3's sandbox) BEFORE ever touching
        real state — see `apply`'s `_validate_and_tune`. A supported
        hypothesis that names NO governor is no longer silently
        skipped: it takes the new advisory path instead — Reflection
        writes one short piece of free-text advice into `World.
        advisory_proposals` for a human to read and mark `accepted`/
        `rejected` via `POST /advisory/{id}/review`. Never auto-applied
        — this is the "changes beyond governors" half of the roadmap
        item, kept strictly out-of-band from the sandboxed numeric
        path."""
        if not self._season_year_gate(events, "self_tuning", "year_end"):
            return
        if self._settlement_job_backpressured():
            return
        self._mark_season_year_resolved("self_tuning")
        acted_hypothesis_ids = {a.get("hypothesis_id") for a in self.world.self_tuning_actions}
        acted_hypothesis_ids |= {a.get("hypothesis_id") for a in self.world.advisory_proposals}
        candidate = None
        governor_key = None
        advisory_candidate = None
        for entry in self.world.reflection_notebook:
            if (
                entry.get("kind") != "hypothesis" or entry.get("status") != "supported"
                or entry.get("id") in acted_hypothesis_ids
            ):
                continue
            key = self._governor_key_for_subject(entry.get("subject", ""))
            if key is not None:
                candidate, governor_key = entry, key
                break
            if advisory_candidate is None:
                advisory_candidate = entry
        if candidate is None:
            if advisory_candidate is None:
                return
            self._schedule_advisory(advisory_candidate)
            return
        current_multiplier = self.world.governor_tuning.get(governor_key, 1.0)
        prompt = self_tuning.build_prompt(candidate["subject"], candidate["content"], current_multiplier)
        fallback = self_tuning.fallback_self_tuning()
        hypothesis_id = candidate["id"]
        hypothesis_subject = candidate["subject"]

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = self_tuning.parse_self_tuning(result, fallback)

            def _record(status: str, new_multiplier: float | None) -> None:
                self.world.self_tuning_actions.append({
                    "id": len(self.world.self_tuning_actions) + 1, "tick": self.world.clock.tick_count,
                    "governor": governor_key, "hypothesis_id": hypothesis_id, "status": status,
                    "direction": parsed["direction"], "magnitude": parsed["magnitude"],
                    "new_multiplier": new_multiplier, "rationale": parsed["rationale"],
                })

            if parsed["magnitude"] < SELF_TUNING_MIN_MAGNITUDE:
                _record("no_adjustment", None)
                return

            async def _validate_and_tune() -> None:
                new_multiplier = self_tuning.apply_bounded_nudge(
                    parsed["magnitude"], parsed["direction"], GOVERNOR_TUNING_BAND,
                )
                # Build the proposed state on a disposable copy FIRST —
                # real World.governor_tuning is never touched until the
                # sandbox confirms it's safe (item 1.3's whole point).
                test_dict = self.world.to_dict()
                test_dict.setdefault("governor_tuning", {})[governor_key] = new_multiplier
                test_world = World.from_dict(test_dict, self.world.config)
                verdict = await run_counterfactual(test_world, self.world.config)
                if not verdict["safe"]:
                    self._log(
                        "self_tuning_rejected",
                        f"A proposed adjustment to {hypothesis_subject} was discarded by the "
                        f"counterfactual sandbox: {verdict['reason']}.",
                    )
                    _record("rejected", new_multiplier)
                    return
                self.world.governor_tuning[governor_key] = new_multiplier
                _record("applied", new_multiplier)
                self._log(
                    "self_tuning",
                    f"Hearthmind adjusted {hypothesis_subject} on its own judgment: {parsed['rationale']} "
                    f"(multiplier {current_multiplier:.2f} -> {new_multiplier:.2f}).",
                )
                # Tier 0 first slice (docs/ROADMAP-2026-07-REMAINING.md):
                # self_tuning becomes Reflection pillar's SECOND real
                # wired job, alongside reflection itself — a genuinely
                # APPLIED nudge (sandbox-validated, not just proposed)
                # is a real fact about what Reflection did, not a
                # revisable theory, hence "observation".
                self.world.reflection_pillar.upsert_world_model(
                    self.world.clock.tick_count, hypothesis_subject, parsed["rationale"], 0.8,
                    status="observation", source="self_tuning",
                )
                self.world.reflection_pillar.remember(
                    f"Acted on my own hypothesis about {hypothesis_subject}: {parsed['rationale']}"
                )

            task = asyncio.create_task(_validate_and_tune())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # The game learning/improving itself: proposing a bounded
        # governor-tuning nudge (v1.3.37).
        self._schedule_llm_job(
            "self_tuning", prompt, self_tuning.SYSTEM_PROMPT, fallback, apply, critical=True,
            deep_reasoning=True,
        )

    def _musing_subject(self) -> dict | None:
        """Vision item 3.4's grounding: prefer the newest OPEN
        `reflection_notebook` hypothesis (something genuinely still
        being tested) over the newest `knowledge_tree()` entry (a
        recent settled fact) — musing about an open question reads more
        like "wondering" than musing about a closed one. `None` when
        the world hasn't learned or hypothesized anything yet (a fresh
        world) — the caller skips the call entirely rather than
        fabricating a subject."""
        # Bug fix, found while verifying Tier 0's reflection_question
        # mirroring (docs/ROADMAP-2026-07-REMAINING.md): a "question"
        # entry (kind="question", status="open", confidence=None by
        # design — see `_maybe_schedule_reflection_question`) used to
        # slip through this filter and crash `musing.build_prompt`'s
        # `{subject['confidence']:.2f}` on `None`. Musing is explicitly
        # about HYPOTHESES per this method's own docstring — a genuine
        # pre-existing bug, not introduced by this pass, just surfaced
        # by it.
        open_hyps = [
            e for e in self.world.reflection_notebook
            if e.get("status") == "open" and e.get("kind") == "hypothesis"
        ]
        if open_hyps:
            latest = max(open_hyps, key=lambda e: e.get("created_tick", 0))
            return {
                "kind": "hypothesis", "text": latest.get("content", ""),
                "confidence": latest.get("confidence", 0.3),
            }
        tree = self.world.knowledge_tree(limit=1)
        if tree:
            return {"kind": "knowledge", "text": tree[0].get("text", "")}
        return None

    def _maybe_schedule_musing(self, events: list[str]) -> None:
        """Vision doc item 3.4, "The world talks to you"
        (docs/VISION-2026-07-22-LIVINGTERRARIUM.md): a once-a-day line
        in Reflection's own voice, not a stat. `critical=False` — this
        is texture, not cognition, and has a genuine deterministic
        fallback (a plain restatement of the subject); a day with
        nothing to muse about (`_musing_subject` returns `None`) skips
        the call entirely rather than fabricating one, same discipline
        as every other "no material, no call" ambient job here."""
        if "day_end" not in events:
            return
        subject = self._musing_subject()
        if subject is None:
            return
        if self._settlement_job_backpressured():
            return
        prompt = musing.build_prompt(subject)
        fallback = musing.fallback_musing(subject)
        tick = self.world.clock.tick_count

        def apply(result: dict, used_fallback: bool) -> None:
            text = musing.parse_musing(result, fallback)
            if not text:
                return
            self.world.musings.append({"tick": tick, "text": text})
            if len(self.world.musings) > MUSING_HISTORY_MAX:
                self.world.musings = self.world.musings[-MUSING_HISTORY_MAX:]
            self._log("musing", text)
            # Tier 0 tenth slice (docs/ROADMAP-2026-07-REMAINING.md):
            # musing becomes Reflection pillar's FOURTH real wired job
            # — memory-only, same reasoning as dream/skill_mastery:
            # a musing is Reflection's own passing voice, not a
            # collective theory (the theory itself, if any, already
            # lives in reflection_notebook via _maybe_schedule_
            # reflection/_reflection_question).
            self.world.reflection_pillar.remember(f"Mused: {text}")

        self._schedule_llm_job("musing", prompt, musing.SYSTEM_PROMPT, fallback, apply)

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
        settlement, `town_brain.compute_priority` (deterministic, see
        its own docstring) decides the settlement's current civic
        priority — the concrete "LLM as the town's brain" mechanic
        (CLAUDE.md): the result measurably steers `buildings.
        choose_building_kind`, not just narration. The LLM's remaining
        role is to write one grounded sentence explaining that already-
        decided priority. Any queued player whispers (`settlement.
        player_influence`, via POST /intervene/town-brain) are folded
        in as one input among the real stats, then consumed. See
        docs/DECISIONS.md,
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
        known_concepts = [
            f"{c.name}: {c.description}"
            for c in ontology.established_concepts(self.world, settlement.id)[-PROMPT_CULTURE_LIST_MAX:]
        ]
        # Phase 1.C: read, then reset — a since-last-check window, same
        # shape `away_digest_since_tick` already uses, so this stays a
        # genuinely "recent" NPC-behavior signal rather than an
        # all-time tally.
        recent_goal_counts = dict(settlement.recent_goal_counts)
        settlement.recent_goal_counts = {}
        # THE decision: computed, not asked for — see town_brain.
        # compute_priority's docstring. Applied immediately, before any
        # LLM call, so the mechanical effect (choose_building_kind's
        # weighting) never waits on or depends on inference.
        decision = town_brain.compute_priority(population_summary, settlement_summary, council_disposition)
        priority = decision["priority"]
        settlement.current_priority = priority
        settlement.priority_rationale = decision["rationale"]
        settlement.record_priority(self.world.clock.tick_count, priority, decision["rationale"])
        self._log("town_brain", f"{settlement.name or 'The village'}'s priority is now {priority} — {decision['rationale']}")
        prompt = town_brain.build_prompt(
            settlement.name, priority, recent, population_summary, settlement_summary, whispers_sent,
            beliefs=settlement.beliefs[-PROMPT_SETTLEMENT_BELIEFS_MAX:],
            belief_digest=settlement.belief_digest,
            culture_digest=settlement.culture_digest,
            council_beliefs=council.beliefs[-PROMPT_BELIEFS_MAX:] if council else None,
            narrative_theme=self._narrative_theme_bias(settlement),
            council_faction_name=council_majority.name if council_majority else "",
            prophecy=settlement.prophecy if settlement.prophecy and settlement.prophecy.get("status") == "pending" else None,
            known_concepts=known_concepts, recent_goal_counts=recent_goal_counts,
        )
        fallback = {"rationale": decision["rationale"]}
        brain_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            target = self._settlement_by_id(brain_target_id)
            if target is None:
                return
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
            if used_fallback:
                return  # the deterministic rationale was already applied/logged above
            rationale = town_brain.parse_rationale(result, fallback)
            target.priority_rationale = rationale
            if target.priority_history:
                target.priority_history[-1]["rationale"] = rationale
            self._log("town_brain", f"{target.name or 'The village'}'s priority is {priority} — {rationale}")

        self._schedule_llm_job(
            "town_brain", prompt, town_brain.SYSTEM_PROMPT, fallback, apply,
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
        rare civic decision.

        B1-B3 (roadmap Stage II, generalized from Nature): `World.
        village_pillar` mirrors this job's real output the same way
        `nature_pillar` mirrors `nature_mind` — a monthly `observe` slot
        reads the Emergence API (A22) into bounded `working_memory`
        (zero LLM cost), the FOLLOWING month is the real `interpret`
        call (grounded in what was observed, via `beliefs.build_prompt`'s
        `emergence_observations` param), and its priority-scaled
        backpressure tolerance replaces the flat gate. Halves this job's
        LLM call volume, same trade `nature_mind` made."""
        settlement = self._job_target()
        if not self._monthly_gate(events, "beliefs") or not settlement.name:
            return
        if self._pillar_observe_turn("village"):
            self._mark_monthly_resolved("beliefs")
            return
        if self._pillar_interpret_backpressured("village"):
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
            intervention_recent=intervention_recent, emergence_observations=list(self.world.village_pillar.working_memory),
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
                if beliefs.is_noop_belief_revision(parsed["belief"], parsed["confidence"], entry):
                    # Live review-pack finding: the model sometimes points
                    # `revises` at an entry and just restates it verbatim
                    # (same text, same confidence) instead of genuinely
                    # sharpening it — not a real revision, so don't log one
                    # or churn `push_belief_history`/`revision_count` for
                    # nothing. Same discipline as folklore's own-output
                    # dedup guard (v1.3.2).
                    self._pillar_close_cycle("village")
                    return
                beliefs.push_belief_history(entry, tick)  # H2: keep what it used to think, not just overwrite
                entry["belief"] = parsed["belief"]
                entry["confidence"] = parsed["confidence"]
                entry["subject"] = parsed["subject"]
                entry["subject_agent_id"] = subject_agent_id
                entry["subject_family_agent_ids"] = subject_family_agent_ids
                entry["revised_tick"] = tick
                entry["revision_count"] = entry.get("revision_count", 0) + 1
                self._log("belief_revised", f"The village revised its view of {entry['subject']}: {entry['belief']}")
                # B1 Pillar abstraction, generalized: mirror the
                # revision into Village's own world_model.
                self.world.village_pillar.upsert_world_model(
                    tick, entry["subject"], entry["belief"], entry["confidence"],
                    source="beliefs", revises_id=entry.get("pillar_entry_id"),
                )
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
                pillar_entry = self.world.village_pillar.upsert_world_model(
                    tick, entry["subject"], entry["belief"], entry["confidence"], source="beliefs",
                )
                entry["pillar_entry_id"] = pillar_entry["id"]
                self.world.village_pillar.remember(f"Came to believe {entry['subject']}: {entry['belief']}")
                # B4 "Inter-pillar consciousness bus" (roadmap Stage III
                # step 11), the Village->Innovation arrow: a genuinely
                # new, reasonably-confident settlement theory is real
                # grounding material for what the village might
                # originate next — tell Innovation about it.
                if entry["confidence"] >= 0.5:
                    self._send_pillar_message(
                        "village", "innovation", "theory",
                        f"the village believes {entry['subject']}: {entry['belief']}",
                    )
            beliefs.sync_family_beliefs(entry, settlement.institutions)  # H2/H3 crossover
            beliefs.sync_council_beliefs(entry, settlement.institutions)  # integration milestone
            beliefs.sync_guild_beliefs(entry, settlement.institutions)  # continue expanding, round three
            self._pillar_close_cycle("village")

        # Settlement-wide belief revision: genuine subjective judgment,
        # same reasoning-over-schema tradeoff as personal_belief
        # (v1.3.37, see json_schemas.py's docstring).
        self._schedule_llm_job(
            "beliefs", prompt, beliefs.SYSTEM_PROMPT, fallback, apply, critical=True,
            settlement=settlement.name, deep_reasoning=True,
        )

    def _maybe_schedule_personal_belief(self, events: list[str]) -> None:
        """H2 extension (docs/ROADMAP.md "Phase H" stage 2), extended
        into a Reflect()-shaped job in v0.78.0 (Phase J, docs/VISION-
        2026-07.md): once a month, `PERSONAL_BELIEF_PICKS_PER_MONTH`
        distinct living agents each form or revise a private belief
        about their own life AND distill one lasting
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
        # Widened from a single pick to PERSONAL_BELIEF_PICKS_PER_MONTH
        # (live review-pack finding, "improve context influence"): with
        # an 18-member core cast and one Reflect() a month, most agents
        # went many real months between ever forming an own_belief/
        # semantic_memory/plan/lesson — the exact fields cognition's
        # prompt offers as personalized context, so most cognition calls
        # simply had nothing but `mind_text` to draw on. Still flat,
        # population-independent volume per month (a fixed small N, not
        # "one per agent") — stays within the "settlement-scoped jobs...
        # give those to the LLM freely" allowance (CLAUDE.md), not the
        # per-agent-gated category.
        picks = rng.sample(candidates, k=min(PERSONAL_BELIEF_PICKS_PER_MONTH, len(candidates)))
        for agent in picks:
            self._run_personal_belief(agent)

    def _run_personal_belief(self, agent) -> None:
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
        current_long_term_goal = dict(agent.long_term_goal) if agent.long_term_goal is not None else None
        life_event_occurred = agent.life_event_since_goal
        prompt = beliefs.build_personal_prompt(
            agent.name, recent, existing, emotion_text, semantic, current_plan,
            personality_text, occupation, list(agent.core_memories),
            current_long_term_goal=current_long_term_goal, life_event_occurred=life_event_occurred,
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
            noop_revision = False
            if revises is not None and revises < len(target.beliefs):
                entry = target.beliefs[revises]
                if beliefs.is_noop_belief_revision(parsed["belief"], parsed["confidence"], entry):
                    # Same live review-pack finding as the settlement job
                    # above: a verbatim restatement isn't a real revision —
                    # skip the mutation/counter/durable-log entry for it.
                    noop_revision = True
                else:
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
            # is preserved too, not just the original — but not for a
            # no-op revision, which changed nothing worth recording.
            if not noop_revision:
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
            # Phase 1.B "self-evolving world" (docs/VISION-2026-07-21-
            # SELFEVOLVING.md): the server-enforced gate — a parsed
            # long_term_goal is only ever applied when a real life
            # event was confirmed for THIS call (see `life_event_
            # since_goal`'s docstring); a model that answers anyway on
            # an ordinary reflection is simply ignored here, not
            # trusted. The flag is consumed (cleared) either way once
            # Reflect() has actually run for this agent.
            if target.life_event_since_goal:
                new_goal = beliefs.parse_long_term_goal(result, target.long_term_goal, tick)
                if new_goal is not target.long_term_goal:
                    target.long_term_goal = new_goal
                    log_agent_memory_entry(
                        self.conn, tick, target.id, "long_term_goal", f"New ambition: {new_goal['goal']}",
                    )
                target.life_event_since_goal = False

        # Personal belief revision: genuine subjective judgment,
        # deliberately reasons rather than schema-constrains (v1.3.37,
        # see json_schemas.py's docstring).
        self._schedule_llm_job(
            "personal_belief", prompt, beliefs.PERSONAL_SYSTEM_PROMPT, fallback, apply, critical=True,
            deep_reasoning=True, num_predict_mult=PERSONAL_BELIEF_NUM_PREDICT_MULT,
        )

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
            # Tier 0 first slice (docs/ROADMAP-2026-07-REMAINING.md):
            # dream becomes Humans pillar's SECOND real wired job,
            # alongside narrative_direction — a memory note only, never
            # a world_model belief (a dream is symbolic content, not a
            # theory the collective holds — Phase G's ambiguity
            # discipline stays intact).
            self.world.humans_pillar.remember(f"{target.name} dreamed: {dream_text}")
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
            # Tier 0 fourth slice (docs/ROADMAP-2026-07-REMAINING.md):
            # memory_drift becomes Humans pillar's FOURTH real wired
            # job, alongside narrative_direction/dream/migration_
            # decision — memory-only, same reasoning as dream: an
            # individual's own reinterpreted memory, not a collective
            # theory.
            self.world.humans_pillar.remember(f"{target.name}'s memory shifted: {drifted_text}")

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
                skill: str = skill,
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
                # Tier 0 eighth slice (docs/ROADMAP-2026-07-REMAINING.
                # md): skill_mastery becomes Humans pillar's FIFTH real
                # wired job, alongside narrative_direction/dream/
                # migration_decision/memory_drift — memory-only, same
                # reasoning as those: one individual's own achievement,
                # not a collective theory.
                self.world.humans_pillar.remember(f"{target.name} reflected on mastering {skill}: {reflection}")

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
        # Post-v1 convergence-audit follow-up: same free monthly cadence,
        # deterministic (no LLM call, no added volume) — see CORE_CAST_
        # ROTATION_MARGIN's docstring for why this exists.
        rotation_rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "core_cast_rotation")
        swap = self.world.population._maybe_rotate_core_cast(rotation_rng)
        if swap is not None:
            outgoing, incoming = swap
            detail = f"{outgoing.name} has stepped back from prominence in the town's story; {incoming.name} has come to the fore."
            self._log("core_cast_rotation", detail)

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
            # Tier 0 sixth slice (docs/ROADMAP-2026-07-REMAINING.md):
            # omen becomes Nature pillar's THIRD real wired job,
            # alongside nature_mind/species_variant. Explicit user
            # decision (2026-07-24, in response to a direct question):
            # Phase G's standing "never confirm anything supernatural"
            # discipline is deliberately set aside for this one site —
            # every OTHER omen consumer (the settlement stat tile, dev
            # console, narration) stays exactly as ambiguous as before;
            # only this new pillar mirror treats the omen as a real
            # sensed impression. `status="hypothesis"` (never
            # "observation") since an omen is explicitly never a
            # confirmed fact even by this relaxed treatment.
            omen_subject = f"an omen about {subject_name}" if subject_name else "an omen the land offered"
            self.world.nature_pillar.upsert_world_model(
                self.world.clock.tick_count, omen_subject, omen, 0.3,
                status="hypothesis", source="omen",
            )
            self.world.nature_pillar.remember(f"The land offered an omen: {omen}")
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

        self._schedule_llm_job("omen", prompt, omens.SYSTEM_PROMPT, fallback, apply)  # ambient texture, stays fast

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
        routine cognition/dialogue for the concurrency semaphore. A
        backpressure-dropped agent is queued in `_pending_mind_agent_ids`
        for `_maybe_retry_mind_authoring` rather than permanently stuck
        (see that method's docstring — root-cause fix for a live
        review-pack finding: `mind_text` dominated cognition's only
        reliably-present context thread, but most of it was this generic
        fallback template, not the distinctive LLM-authored paragraph,
        because a genesis burst regularly loses the backpressure roll on
        this hardware)."""
        for agent in agents:
            fallback = mind.fallback_mind(agent)
            agent.mind = fallback["mind"]
            # v0.87.12 "per-agent voice" (docs/IDEAS-2026-07-EMERGENCE.md
            # §7): rides this same one-time genesis call/schema, zero
            # added LLM volume — see llm/mind.py's widened SYSTEM_PROMPT.
            agent.voice = fallback["voice"]
            if self._settlement_job_backpressured():
                if agent.id not in self._pending_mind_agent_ids:
                    self._pending_mind_agent_ids.append(agent.id)
                continue
            self._author_one_mind(agent)

    def _author_one_mind(self, agent) -> None:
        agent_id = agent.id
        fallback = {"mind": agent.mind, "voice": agent.voice}
        prompt = mind.build_prompt(agent)

        def apply(result: dict, used_fallback: bool, agent_id=agent_id, fallback=fallback) -> None:
            target = self.world.population.get(agent_id)
            if target is None:
                return  # died before the answer arrived
            target.mind = mind.parse_mind(result, fallback)
            target.voice = mind.parse_voice(result, fallback)
            if target.long_term_goal is None and not used_fallback:
                initial_goal = mind.parse_initial_goal(result)
                if initial_goal:
                    target.long_term_goal = {"goal": initial_goal, "formed_tick": self.world.clock.tick_count}

        self._schedule_llm_job("mind", prompt, mind.SYSTEM_PROMPT, fallback, apply)

    def _maybe_retry_mind_authoring(self) -> None:
        """Backpressure at genesis is common (a fresh core-cast seat, or
        several at once after a `core_cast_rotation`) — `_author_minds`
        used to give up permanently on a dropped agent, so any tick that
        lost the backpressure roll left that agent's `Agent.mind` stuck
        on the generic fallback template for the rest of its life. Same
        "one unlucky tick shouldn't mean permanent silence" bug class as
        the monthly-job retry-window fix (v0.81.0/.87.0-era, see CLAUDE.
        md's diagnostic history) — here the job has no natural monthly
        cadence to fall back on, so it just keeps retrying, one agent per
        tick, until it succeeds (bounded by the existing backpressure/
        budget gates like any other job, so this never adds unbounded
        call volume — a persistently-saturated queue just means this
        keeps losing its slot to higher-priority jobs, same as today).
        Only spends a retry on an agent still worth it: alive and
        currently core cast (a rotated-out or deceased agent is quietly
        dropped from the queue rather than wasting a call on it)."""
        core_ids = self.world.population.core_agent_ids
        while self._pending_mind_agent_ids:
            agent_id = self._pending_mind_agent_ids[0]
            agent = self.world.population.get(agent_id)
            if agent is None or agent_id not in core_ids:
                self._pending_mind_agent_ids.pop(0)
                continue
            if self._settlement_job_backpressured():
                return
            self._pending_mind_agent_ids.pop(0)
            self._author_one_mind(agent)
            return  # one retry per tick — let it compete fairly with every other job

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
        # Tier 2.2 (2026-07-21): due_for_dispute now also fires on
        # one-sided souring, so the two directions can genuinely
        # differ — show whichever side has actually festered worse
        # rather than always reading a's view of b, which could
        # otherwise show a mild/neutral number while b's real
        # grievance (the reason this fired at all) goes unmentioned.
        relationship = min(
            agent_a.relationships.get(agent_b.id, 0.0), agent_b.relationships.get(agent_a.id, 0.0),
        )
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
            # Tier 0 second slice (docs/ROADMAP-2026-07-REMAINING.md):
            # dispute becomes Village pillar's THIRD real wired job,
            # alongside beliefs/institution_belief — a memory note
            # (not a world_model entry: a specific dispute between two
            # people isn't a settlement-wide theory) every time, not
            # just lasting ruptures — ordinary civic life either way.
            self.world.village_pillar.remember(
                f"{agent_a.name} and {agent_b.name}'s dispute ended in {outcome.replace('_', ' ')}: {narration}"
            )
            # Vision doc item 3.3 ("Legible causal threads"): capture the
            # SAME grounding facts already computed above for the prompt
            # as a structured chain, for any outcome that represents a
            # real, lasting rupture (not a plain reconcile, which has no
            # "how this came to be" worth tracing).
            if outcome in ("feud", "ostracism", "council_ruling"):
                chain = [f"{agent_a.name} and {agent_b.name}'s relationship soured (level {relationship:.2f})."]
                if debt_a_owes_b >= 1.0 or debt_b_owes_a >= 1.0:
                    debtor, creditor = (agent_a, agent_b) if debt_a_owes_b >= debt_b_owes_a else (agent_b, agent_a)
                    chain.append(f"{debtor.name} owed {creditor.name} an unpaid debt.")
                if rival_factions:
                    chain.append(f"{agent_a.name} and {agent_b.name} belong to rival factions.")
                if rival_families:
                    chain.append(f"{agent_a.name} and {agent_b.name}'s families were already feuding.")
                if abs(reputation_a - reputation_b) >= 0.3:
                    better, worse = (agent_a, agent_b) if reputation_a > reputation_b else (agent_b, agent_a)
                    chain.append(f"{better.name} was generally better regarded in the village than {worse.name}.")
                if has_law_against_feuding:
                    chain.append("The village has a law against unresolved feuding.")
                chain.append(narration)
                subject = f"{agent_a.name} & {agent_b.name}'s {outcome.replace('_', ' ')}"
                ontology.register_causal_thread(self.world, subject, chain, self.world.clock.tick_count, dispute_home_id)
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
                    # Vision doc item 1.2: a feud is the real, concrete
                    # `on_feud` detection point for trigger rules.
                    self._apply_trigger_rules_for("on_feud", dispute_settlement)
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

        # Major life decision: a dispute outcome reshapes two lives and
        # settlement history (v1.3.37).
        self._schedule_llm_job("dispute", prompt, dispute.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
            # Tier 0 fifteenth slice: faction becomes Village pillar's
            # tenth real wired job — a detected, named faction is a
            # real settled social fact.
            self.world.village_pillar.upsert_world_model(
                tick, f"the {name} faction", framing, 0.8, status="observation", source="faction",
            )
            self.world.village_pillar.remember(f"A faction calling itself {name} has formed: {framing}")

        # Cultural evolution: naming a real detected faction (v1.3.37).
        self._schedule_llm_job("faction", prompt, faction.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
            tick = self.world.clock.tick_count
            event = self.world.population.found_guild(
                self._settlement_by_id(guild_target_id), skill, founder_id, tick,
            )
            if event is not None:
                self._log(event[0], f'{event[1]} — "{reason}"')
                # Tier 0 sixteenth slice: guild_founding becomes
                # Village pillar's eleventh real wired job — a
                # deliberately founded guild is a real settled
                # institutional fact.
                self.world.village_pillar.upsert_world_model(
                    tick, f"the {skill} guild", reason, 0.8, status="observation", source="guild_founding",
                )
                self.world.village_pillar.remember(f"A {skill} guild was founded — \"{reason}\"")

        # Major life decision: deliberately founding a guild (v1.3.37).
        self._schedule_llm_job("guild_founding", prompt, founding.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
        # v0.87.12 "institution objectives," made deterministic
        # (explicit user directive): the WANT itself is computed, not
        # asked for — applied immediately, before any LLM call. Only
        # the LLM's explanation of it (`objective_reason`) waits on
        # inference.
        council_disposition = (
            self.world.population.council_disposition(institution)
            if institution.kind is InstitutionKind.COUNCIL else None
        )
        objective = institutions.compute_objective(institution, inst_target.summary(), council_disposition)
        # Vision item 2.2: track how long this institution has wanted
        # the SAME thing — a real, persistent frustration, not a fresh
        # one each check.
        if objective and objective == institution.objective:
            institution.objective_ticks_unmet += 1
        else:
            institution.objective_ticks_unmet = 0
        institution.objective = objective
        prompt = beliefs.build_institution_prompt(label, member_names, existing, recent, objective=objective)
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
            objective_reason = beliefs.parse_institution_objective_reason(result)
            if objective_reason:
                self._log("institution_objective", f"The {label} wants to {objective} — {objective_reason}")
            if verb == "unchanged":
                return  # a verbatim restatement of an existing theory — nothing to log
            self._log(
                "institution_belief",
                f"The {label} {'revised its view' if verb == 'revised' else 'came to believe something'}"
                f" of {parsed['subject']}: {parsed['belief']}",
            )
            # Tier 0 first slice (docs/ROADMAP-2026-07-REMAINING.md):
            # institution_belief becomes Village pillar's SECOND real
            # wired job, alongside beliefs — an institution's own
            # theory genuinely is Village-domain civic life, mirrored
            # the same way settlement-wide belief revision already is.
            self.world.village_pillar.upsert_world_model(
                self.world.clock.tick_count, parsed["subject"], parsed["belief"], parsed["confidence"],
                source=f"institution_belief:{label}",
            )
            self.world.village_pillar.remember(f"The {label} came to believe of {parsed['subject']}: {parsed['belief']}")

        # Council deliberation (and FAMILY/GUILD's own equivalent):
        # institutional belief formation is genuine collective judgment
        # (v1.3.37).
        self._schedule_llm_job("institution_belief", prompt, beliefs.INSTITUTION_SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
            # Tier 0 seventh slice (docs/ROADMAP-2026-07-REMAINING.md):
            # laws becomes Village pillar's FIFTH real wired job,
            # alongside beliefs/institution_belief/dispute/rule_
            # propose — a newly-enacted law/custom/taboo is a real
            # settled civic fact, same "observation" treatment
            # rule_propose already gets.
            self.world.village_pillar.upsert_world_model(
                tick, f"the {parsed['kind']} on {pattern_text}", parsed["text"], 1.0,
                status="observation", source="laws",
            )
            self.world.village_pillar.remember(f"Came to hold a {parsed['kind']}: {parsed['text']}")

        # Cultural evolution: a law/custom/taboo is a real normative
        # judgment about the settlement (v1.3.37).
        self._schedule_llm_job("laws", prompt, laws.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

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
                # Tier 0 eighteenth slice: noncore_nudge becomes Humans
                # pillar's seventh real wired job — memory-only, one
                # ordinary villager's own quiet moment, same reasoning
                # as letter/skill_mastery.
                self.world.humans_pillar.remember(f"{target_agent.name} had a quiet realization: {reflection}")
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
            # Tier 0 seventeenth slice: letter becomes Humans pillar's
            # sixth real wired job — memory-only, one individual's own
            # written words, not a collective theory.
            self.world.humans_pillar.remember(f"{sender_name} wrote to {recipient_name}: {text}")

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
        if spots:
            # A1 FieldGrid (roadmap Stage I step 2): prefer a region the
            # live population_density field doesn't already read as
            # crowded, when an alternative exists — never a hard block.
            uncrowded = [
                pos for pos in spots
                if self.world.fields.get_at(
                    "population_density", pos, self.world.config.width, self.world.config.height,
                ) < POPULATION_DENSITY_FISSION_AVOID_THRESHOLD
            ]
            if uncrowded:
                spots = uncrowded
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
            # A7 (roadmap Stage IV step 27), dialect domain: the
            # daughter settlement inherits a few of its origin's coined
            # terms, each independently drift-mutated (zero LLM cost) —
            # a real "two related villages now say things slightly
            # differently" outcome, not a copy-paste of the parent's
            # lexicon.
            for entry in home.lexicon[-LEXICON_FISSION_DRIFT_COUNT:]:
                drifted = drift_term(entry["term"])
                if narrative_direction.validate_coined_term(drifted, new_settlement.lexicon):
                    new_settlement.lexicon.append({
                        "term": drifted, "meaning": entry["meaning"],
                        "formed_tick": self.world.clock.tick_count,
                    })
            self.world.settlements.append(new_settlement)
            population.depart_for_fission(
                party, new_settlement, site, self.world.clock.tick_count, home.name,
            )
            self._log(
                "settlement_founded",
                f"{leader.name} led {len(party)} settlers out of {home.name}"
                f" toward a new home in the distance — \"{reason}\"",
            )

        # Major life decision: whether to leave and found a new
        # settlement (v1.3.37).
        self._schedule_llm_job("fission", prompt, fission.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

    def _maybe_schedule_migration_decision(self) -> None:
        """Individual migration's core-cast half (explicit user
        directive, "expand genuine decision points" audit): mirrors
        `_maybe_schedule_fission`'s candidacy/decision split exactly,
        one level down — `Population.core_migration_candidates` finds
        the deterministic preconditions (push/pull facts already
        tracked elsewhere), this schedules the LLM's actual "do they
        go" judgment (`llm/migration.py`). At most one candidate
        considered per tick (the first found — candidate order is
        stable, not adversarially gamed), gated by the same `MIGRATION_
        CHANCE_PER_TICK` roll the non-core path already uses, so this
        adds no new call-volume ceiling beyond what individual
        migration already cost before this pass — it only changes WHO
        decides for the core cast specifically. Non-core agents keep
        the original flat-roll path in `Population._maybe_migrate`
        entirely unchanged."""
        candidates = self.world.population.core_migration_candidates(self.world.settlements)
        if not candidates:
            return
        if self._settlement_job_backpressured():
            return
        if _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "migration_decision_roll",
        ) >= MIGRATION_CHANCE_PER_TICK:
            return
        agent, target, push_reason = candidates[0]
        home = self._settlement_by_id(agent.settlement_id)
        if home is None:
            return
        prompt = migration.build_prompt(agent, home.name, target.name, push_reason)
        fallback = migration.fallback_decision(agent)
        agent_id, home_id, target_id = agent.id, home.id, target.id

        def apply(result: dict, used_fallback: bool) -> None:
            depart, reason = migration.parse_decision(result, fallback)
            if not depart:
                return  # they weighed the reason to go and stayed — a real decision
            population = self.world.population
            target_agent = population.get(agent_id)
            target_home = self._settlement_by_id(home_id)
            target_settlement = self._settlement_by_id(target_id)
            if (
                target_agent is None or target_home is None or target_settlement is None
                or target_agent.settlement_id != home_id or target_agent.travel_target is not None
            ):
                return  # died, already moved, or already mid-journey while the decision was in flight
            description = population.depart_for_migration(target_agent, target_home, target_settlement)
            self._log("migrant_departed", f"{description} — \"{reason}\"")
            # Tier 0 second slice (docs/ROADMAP-2026-07-REMAINING.md):
            # migration_decision becomes Humans pillar's THIRD real
            # wired job, alongside narrative_direction/dream — a real
            # weighed life decision, memory-only (an individual's
            # choice, not a collective theory).
            self.world.humans_pillar.remember(f"{target_agent.name} chose to leave: {reason}")

        # Major life decision: weighing a real reason to leave against
        # roots/relationships (v1.3.37).
        self._schedule_llm_job(
            "migration_decision", prompt, migration.SYSTEM_PROMPT, fallback, apply, settlement=home.name,
            deep_reasoning=True,
        )

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
        itself is named. Fully procedural (explicit user directive) —
        a plain weathered place name carries no interpretation the LLM
        would meaningfully add, so this is a direct, zero-LLM-call
        assignment, not a scheduled job. See llm/geography.py."""
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
        self._mark_monthly_resolved("geography")
        existing_names = list(place_names.values())
        name = geography.name_feature(feature_kind, self.world.clock.tick_count, existing_names=existing_names)
        place_names[feature_key] = name
        noun = "the river" if feature_kind == "river" else "the lake"
        self._log("place_named", f"The villagers took to calling {noun} {name}.")

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
        z-score anomaly check.

        Also mirrors into `_append_emergence` (A22) via `_HIGHLIGHT_
        EMERGENCE_MAP` — every highlight trigger site is already a real,
        edge-triggered "something notable happened" detector, so this
        reuses all of them for free rather than building a parallel
        detection pass. A `kind` with no map entry (should never happen
        — every call site above is mapped) silently skips the mirror
        rather than raising, so a future highlight trigger added without
        updating the map degrades to "just a highlight," not a crash."""
        self.world.highlights.append({
            "kind": kind, "detail": detail, "tick": self.world.clock.tick_count,
        })
        if len(self.world.highlights) > HIGHLIGHTS_MAX_STORED:
            self.world.highlights = self.world.highlights[-HIGHLIGHTS_MAX_STORED:]
        mapped = _HIGHLIGHT_EMERGENCE_MAP.get(kind)
        if mapped is not None:
            emergence_kind, subsystem, pillars = mapped
            self._append_emergence(emergence_kind, subsystem, detail, pillars)

    def _append_emergence(
        self, kind: str, subsystem: str, summary: str, pillars: list[str] | tuple[str, ...],
        magnitude: float | None = None, settlement: str | None = None, data: dict | None = None,
    ) -> None:
        """A22 "The Emergence API" (docs/MASTERCHECKLIST-2026-07-22.md):
        appends one curated, typed, pillar-tagged observation to `World.
        emergence_log`, capped at EMERGENCE_LOG_MAX_STORED (oldest
        evicted) — see `world/emergence.py`'s `make_observation` for the
        shape contract this validates against. No pillar reads this
        stream yet (Stage II of the roadmap); this is the producer side
        only, exercised by the detectors below so the shape is proven
        against real signals before anything depends on it."""
        observation = emergence.make_observation(
            self.world.next_emergence_id, self.world.clock.tick_count, kind, subsystem, summary,
            pillars, magnitude=magnitude, settlement=settlement, data=data,
        )
        self.world.next_emergence_id += 1
        self.world.emergence_log.append(observation)
        if len(self.world.emergence_log) > EMERGENCE_LOG_MAX_STORED:
            self.world.emergence_log = self.world.emergence_log[-EMERGENCE_LOG_MAX_STORED:]

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
        self._detect_settlement_bottlenecks()

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

    def _detect_settlement_bottlenecks(self) -> None:
        """A22 Emergence API: a genuine, already-computed bottleneck
        signal — `cheapest_founding_cost()` is the same bar `cognition.
        py`'s `materials_critical` flag uses per-agent every tick to
        force a GATHER decision, but that's too fine-grained (per
        agent, per tick) for a settlement-level "is this bottleneck
        actually binding" observation. Checked once per sim-day
        (riding `_log_daily_metrics`'s existing cadence, no new
        polling loop) and edge-triggered via `_materials_critical_
        flagged` — one `bottleneck` observation when a settlement
        first crosses below the threshold, silence while it stays
        there or once it recovers, same discipline as `_detect_metric_
        highlights`' extinction-near-miss check."""
        cheapest = cheapest_founding_cost()
        for settlement in self.world.settlements:
            critical = settlement.materials < cheapest
            was_flagged = settlement.id in self._materials_critical_flagged
            if critical and not was_flagged:
                self._materials_critical_flagged.add(settlement.id)
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name or 'The village'}'s material stockpile "
                    f"({settlement.materials:.1f}) has run dry — nothing new can be built.",
                    pillars=("village", "humans"), magnitude=1.0, settlement=settlement.name,
                    data={"materials": round(settlement.materials, 2), "threshold": round(cheapest, 2)},
                )
                # A9 feedback-loop audit, second pass (docs/ROADMAP-
                # 2026-07-REMAINING.md): `llm/ontology.py`'s
                # PRESSURE_SIGNAL_LABELS has always named this key, but
                # nothing anywhere incremented `pattern_signal_counts[
                # "materials_bottleneck"]` — a real pressure signal that
                # could never actually fire. This edge-trigger (a
                # settlement genuinely crossing INTO a materials
                # shortage, not merely staying in one) is the natural
                # producer, same shape as `dispute_feud`/`nature_
                # adaptation` elsewhere in this file.
                settlement.pattern_signal_counts["materials_bottleneck"] = (
                    settlement.pattern_signal_counts.get("materials_bottleneck", 0) + 1
                )
            elif not critical and was_flagged:
                self._materials_critical_flagged.discard(settlement.id)

    def _detect_hydrology_drought(self) -> None:
        """A22 Emergence API, A11's real consumer beyond farm yield
        (roadmap Stage IV step 15): a genuinely widespread drought —
        most land tiles reading well below `HYDROLOGY_DROUGHT_
        THRESHOLD` — is a real Nature-domain fact, not narrative
        texture. Riding the weekly hydrology-tick cadence (no separate
        polling loop); edge-triggered via `_hydrology_drought_flagged`,
        same "one observation on the falling edge, silent recovery on
        the rising edge" discipline as `_detect_settlement_
        bottlenecks`."""
        moisture = self.world.hydrology_field.moisture
        flat = [v for row in moisture for v in row]
        if not flat:
            return
        dry_fraction = sum(1 for v in flat if v < HYDROLOGY_DROUGHT_THRESHOLD) / len(flat)
        drought = dry_fraction >= HYDROLOGY_DROUGHT_LAND_FRACTION
        if drought and not self._hydrology_drought_flagged:
            self._hydrology_drought_flagged = True
            self._append_emergence(
                "bottleneck", "hydrology",
                f"The land itself is drying — {dry_fraction:.0%} of the ground reads parched.",
                pillars=("nature", "village"), magnitude=1.0,
                data={"dry_fraction": round(dry_fraction, 3)},
            )
        elif not drought and self._hydrology_drought_flagged:
            self._hydrology_drought_flagged = False

    def _detect_social_hub(self) -> None:
        """A16 "Graph algorithms" (docs/MASTERCHECKLIST-2026-07-22.md,
        roadmap Stage I step 3): a real graph-theoretic algorithm
        (weighted-degree centrality, `world.graph_algorithms`) run over
        the existing pairwise relationship ledger — a structural fact
        ("who does this village's social network actually center on"),
        computed deterministically, never an LLM judgment. Season
        cadence per settlement (cheap — O(agents), no LLM call, so
        every settlement gets it every season rather than round-
        robining like the LLM-gated settlement jobs). Edge-triggered on
        `Settlement.social_hub_agent_id` actually changing to a new,
        non-None agent — a settlement whose hub stays the same, or
        drops to no hub at all (an emptied settlement), stays silent."""
        for settlement in self.world.settlements:
            members = [a for a in self.world.population.agents if a.settlement_id == settlement.id]
            if not members:
                continue
            graph = graph_algorithms.build_relationship_graph(members)
            new_hub = graph_algorithms.most_central_agent(graph)
            if new_hub is not None and new_hub != settlement.social_hub_agent_id:
                settlement.social_hub_agent_id = new_hub
                hub_agent = next((a for a in members if a.id == new_hub), None)
                if hub_agent is not None:
                    self._append_emergence(
                        "unexplained_shift", "social_graph",
                        f"{hub_agent.name} has become the center of {settlement.name or 'the village'}'s "
                        f"social network.",
                        pillars=("humans", "village"), settlement=settlement.name,
                        data={"agent_id": hub_agent.id},
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
        outcome: dict | None = None, reasoning: bool = False, diag: dict | None = None,
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
        default.

        `diag` (explicit user request — expose raw_model_output/
        parsed_json/validation_errors/fallback_reason/fallback_result
        whenever a fallback occurs for any LLM call): the `_diag()`-
        shaped dict `CognitionRunner.run` returns (plus `fallback_
        result`, added by the caller — see `_schedule_llm_job`'s
        `_runner`). Folded into `_last_llm_calls[name]` below only when
        `used_fallback` is true — a successful call has nothing to
        diagnose, and `result` already IS the parsed answer in that
        case."""
        self._last_llm_calls[name] = {
            "tick": self.world.clock.tick_count, "prompt": prompt,
            "result": result, "used_fallback": used_fallback, "reasoning": reasoning,
        }
        if used_fallback and diag is not None:
            self._last_llm_calls[name].update({
                "fallback_reason": diag.get("fallback_reason"),
                "raw_model_output": diag.get("raw_model_output"),
                "parsed_json": diag.get("parsed_json"),
                "validation_errors": diag.get("validation_errors") or [],
                "fallback_result": diag.get("fallback_result", result),
            })
        self._training_recorder.maybe_record(
            task=name, prompt=prompt, system_prompt=system_prompt, result=result,
            used_fallback=used_fallback, raw_completion=raw_completion,
            elapsed_ms=elapsed_ms, tick=self.world.clock.tick_count,
            structured_input=structured_input, npc_ids=npc_ids, settlement=settlement,
            outcome=outcome,
        )
        stats = self._llm_prompt_stats.setdefault(name, {
            "calls": 0, "fallback_calls": 0, "reasoning_calls": 0,
            "prompt_chars": deque(maxlen=LLM_PROMPT_STATS_WINDOW),
            "completion_chars": deque(maxlen=LLM_PROMPT_STATS_WINDOW),
            "latency_ms": deque(maxlen=LLM_PROMPT_STATS_WINDOW),
        })
        stats["calls"] += 1
        if used_fallback:
            stats["fallback_calls"] += 1
        if reasoning:
            stats["reasoning_calls"] += 1
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
        # P3.4: live counterpart to review_diagnostics.py's export-time
        # Context Influence section — see `context_reflects_any`'s and
        # `self._cognition_context_stats`'s docstrings.
        if name == "cognition" and structured_input is not None:
            reflected = context_reflects_any(structured_input, result.get("reason") if isinstance(result, dict) else None)
            if reflected is not None:
                self._cognition_context_stats["scored"] += 1
                if reflected:
                    self._cognition_context_stats["any_reflected"] += 1

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
                "reasoning_calls": stats.get("reasoning_calls", 0),
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
        if (
            any(category in TERRAIN_CHANGING_CATEGORIES for category, _ in self.world.last_life_events)
            or "week_end" in self.world.last_calendar_events
        ):
            # `week_end` resyncs even when nothing changed a tile's biome —
            # moisture/soil_fertility/population_density (below) have no
            # TERRAIN_CHANGING_CATEGORIES event of their own (they're
            # continuous fields, not discrete scarring), so without this
            # they'd only ever refresh as a side effect of an unrelated
            # terrain-changing event. Weekly matches hydrology's own real
            # tick cadence — no point resyncing more often than the
            # underlying field actually changes.
            self._broadcaster.set_terrain(
                self.world.terrain, self.world.config.width, self.world.config.height,
                mining_scars=self.world.mining_scars, disaster_scars=self.world.disaster_scars,
                ritual_activity=self.world.ritual_activity, ruin_scars=self.world.ruin_scars,
                moisture=self.world.hydrology_field.moisture, soil_fertility=self.world.farms.soil_fertility,
                population_density=self.world.fields.ensure_field("population_density"),
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
            # `settlement_id` (Phase 3.C, docs/VISION-2026-07-21-
            # SELFEVOLVING.md "architecture visibly changing on the
            # map") is computed here, not persisted on `Building`
            # itself — the frontend needs it only to look up
            # `architecture_styles` below and tint accordingly.
            "buildings": [
                {
                    **b.to_dict(), "settlement_id": s.id,
                    # A7 (roadmap Stage IV step 27), architecture domain:
                    # a deterministic per-instance structural descriptor,
                    # distinct from materials.py's per-KIND "Built of"
                    # line (which reads identically for every HUT).
                    "descriptor": building_descriptor(
                        b.id, b.kind.value, BUILDING_MATERIALS.get(b.kind, "wood"),
                        settlement_layout_style(s.id),
                    ),
                }
                for s in settlements for b in s.buildings
            ],
            "architecture_styles": {
                str(s.id): {"name": concept.name, "category": concept.category, "concept_id": concept.id}
                for s in settlements
                for concept in [ontology.dominant_architecture_concept(self.world, s.id)]
                if concept is not None
            },
            # Vision item 4.1: named composite entities, keyed by the
            # real building they're bound to — the building inspector
            # looks one up by building_id when a clicked building has
            # been named.
            "composite_entities": [e.to_dict() for e in self.world.composite_entities.values()],
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

    def _pillar_cognition_status(self) -> dict:
        """Explicit live-report follow-up: "Nature and especially
        Reflection still feel disconnected from the actual simulation
        state. They are not forming any hypothesis even after 13k
        ticks." Both jobs halve their own already-slow season/year
        cadence via the B2 observe-then-interpret cycle (see `_maybe_
        schedule_nature_mind`/`_maybe_schedule_reflection`) — their
        FIRST real output needs two boundary crossings, not one. This
        was previously invisible; makes that cold-start latency a
        directly readable status instead."""
        nature_pillar = self.world.nature_pillar
        nature_stage = "Observation" if nature_pillar.cycle_stage == "observe" else "Interpretation"
        belief_formed = len(self.world.nature_beliefs) > 0
        reflection_pillar = self.world.reflection_pillar
        reflection_stage = (
            "Historical accumulation" if reflection_pillar.cycle_stage == "observe" else "Pattern analysis"
        )
        pattern_eligible = self._detect_reflection_pattern() is not None
        hypothesis_formed = any(
            e.get("kind") == "hypothesis" for e in self.world.reflection_notebook
        )
        return {
            "nature": {
                "stage": nature_stage,
                "boundaries_observed": nature_pillar.turns_processed,
                "boundaries_needed_for_first_belief": PILLAR_COLD_START_BOUNDARIES,
                "belief_formation": "Formed" if belief_formed else "Pending",
            },
            "reflection": {
                "stage": reflection_stage,
                "years_observed": reflection_pillar.turns_processed,
                "years_needed_for_first_hypothesis": PILLAR_COLD_START_BOUNDARIES,
                "pattern_detector": "Eligible" if pattern_eligible else "Not yet eligible",
                "hypothesis": "Formed" if hypothesis_formed else "Deferred",
            },
        }

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
            "llm_model": _resolve_llm_model_label(self.config),
            "llm_adapter_name": self.config.llm_adapter_name,
            # Phase 1.A "self-evolving world" (docs/VISION-2026-07-21-
            # SELFEVOLVING.md): the Innovation Layer's own registry
            # size/health, dev-console reachable — a full main-UI
            # panel (per-settlement "Ideas & Innovations" stat tile,
            # NPC-inspector adopter view) is flagged as a fast-follow
            # UI pass, not shipped this batch (backend/mechanism is the
            # priority for this slice; every field here is already
            # real, mechanically-consumed state, not placeholder).
            "invented_concepts_total": len(self.world.invented_concepts),
            "invented_concepts_established": sum(
                1 for c in self.world.invented_concepts.values() if c.status == "established"
            ),
            "invented_concepts_by_category": {
                cat: sum(1 for c in self.world.invented_concepts.values() if c.category == cat)
                for cat in ontology.ONTOLOGY_CATEGORIES
                if any(c.category == cat for c in self.world.invented_concepts.values())
            },
            # Vision doc item 1.2 — same dev-console depth as the
            # ontology fields above.
            "trigger_rules_total": len(self.world.trigger_rules),
            "trigger_rules_by_status": {
                status: sum(1 for r in self.world.trigger_rules.values() if r.status == status)
                for status in ("active", "retired")
                if any(r.status == status for r in self.world.trigger_rules.values())
            },
            # Vision doc item 4.1 — same dev-console depth as trigger
            # rules above; the main-UI surfacing is the building click
            # inspector (a composite entity is meant to be discovered
            # by clicking its building, not read as a raw count).
            "composite_entities_total": len(self.world.composite_entities),
            # A5/A6 "Affordances + discovery query layer" (roadmap Stage
            # IV step 18, widened by A12/step 19's material-derived
            # union — see `materials.building_affordances`): what's
            # genuinely discoverable right now per settlement, from
            # what's actually standing — live-computed (not persisted
            # state, so no snapshot field), dev-console depth same as
            # `invented_concepts_by_category` above; a settlement with
            # nothing standing that clears a known pair is simply absent
            # from this dict.
            "discoverable_affordance_combinations": {
                stl.name or f"settlement_{stl.id}": combos
                for stl in self.world.settlements
                for combos in [discover_combinations({
                    tag
                    for b in stl.buildings if b.stage is BuildingStage.STANDING
                    for tag in building_affordances(b.kind)
                })]
                if combos
            },
            # A13 "Chemistry / reaction system" (roadmap Stage IV step
            # 20): same dev-console depth/shape as the affordance
            # combinations field directly above.
            "discoverable_reactions": {
                stl.name or f"settlement_{stl.id}": products
                for stl in self.world.settlements
                for standing in [{
                    b.kind for b in stl.buildings if b.stage is BuildingStage.STANDING
                }]
                for products in [discover_reactions(
                    {BUILDING_MATERIALS[k] for k in standing if k in BUILDING_MATERIALS},
                    {tag for k in standing for tag in building_affordances(k)},
                )]
                if products
            },
            # Vision doc item 1.4/2.4's own signal — how close the
            # governor-drift detector is to having enough samples, and
            # the same recent-window numbers `_detect_reflection_
            # pattern` itself computes.
            "wildfire_ignition_ticks_recorded": len(self.world.wildfire_ignition_ticks),
            # Phase 5.A/5.B (docs/VISION-2026-07-21-SELFEVOLVING.md,
            # "Start the 5th item"): dev-console reachability for
            # Reflection's notebook, same "diagnostics-depth content,
            # not main-UI" treatment as every other Phase N/§4-§6
            # internals-only feature.
            "reflection_notebook_total": len(self.world.reflection_notebook),
            "reflection_notebook_by_status": {
                status: sum(1 for e in self.world.reflection_notebook if e.get("status") == status)
                for status in ("open", "supported", "rejected")
                if any(e.get("status") == status for e in self.world.reflection_notebook)
            },
            "reflection_notebook_recent": [
                {"subject": e["subject"], "content": e["content"], "confidence": e["confidence"], "status": e["status"]}
                for e in self.world.reflection_notebook[-10:]
            ],
            # A22 "The Emergence API" (docs/MASTERCHECKLIST-2026-07-22.
            # md, Stage I step 1): same dev-console-reachability
            # treatment as reflection_notebook above — full stream via
            # GET /emergence (on-demand provider), this is just the
            # at-a-glance summary the diagnostics payload already
            # carries for everything else.
            "emergence_log_total": len(self.world.emergence_log),
            "emergence_log_by_kind": {
                kind: sum(1 for o in self.world.emergence_log if o.get("kind") == kind)
                for kind in emergence.OBSERVATION_KINDS
                if any(o.get("kind") == kind for o in self.world.emergence_log)
            },
            "emergence_log_recent": [
                {"kind": o["kind"], "subsystem": o["subsystem"], "summary": o["summary"], "pillars": o["pillars"]}
                for o in self.world.emergence_log[-10:]
            ],
            # B1 Pillar abstraction (roadmap Stage II step 4): same dev-
            # console-only reachability as reflection_notebook/emergence
            # above — Nature's persistent self-model/world-model/memory
            # aren't main-UI-worthy yet (nothing player-facing reads
            # them), but the shape should be inspectable while it's
            # being proven out.
            "nature_pillar": self.world.nature_pillar.to_dict(),
            # B1, generalized to all five pillars (roadmap Stage II):
            # same dev-console-only depth as nature_pillar above — none
            # of these four are main-UI-worthy yet either.
            "village_pillar": self.world.village_pillar.to_dict(),
            "humans_pillar": self.world.humans_pillar.to_dict(),
            "innovation_pillar": self.world.innovation_pillar.to_dict(),
            "reflection_pillar": self.world.reflection_pillar.to_dict(),
            # Vision doc items 1.4/2.4: same dev-console depth as
            # reflection_notebook above — governor_tuning is the live
            # effective state, self_tuning_actions is the append-only
            # decision log (applied/rejected/no_adjustment) behind it.
            "governor_tuning": dict(self.world.governor_tuning),
            "self_tuning_actions_recent": list(self.world.self_tuning_actions[-10:]),
            # B6 (roadmap Stage III step 13): the human-reviewed
            # counterpart to self_tuning_actions_recent above — advice
            # for a supported hypothesis that named no governor.
            "advisory_proposals_recent": list(self.world.advisory_proposals[-10:]),
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
            # Explicit user directive: adaptive slowdown should have a
            # symmetric speedup counterpart when the LLM queue is idle
            # (see LLM_PRESSURE_SPEEDUP_START_RATIO's docstring) — this
            # is the actual live multiplier `run_forever` is applying to
            # the tick interval right now: <1.0 sped up, 1.0 normal,
            # >1.0 slowed down.
            "llm_pressure_interval_multiplier": round(self._llm_pressure_interval_multiplier(), 3),
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
            # P3.4 (docs/AUDIT-2026-07-20.md): topic-share, mood axes,
            # materials flow, and context-reflection rate were four
            # numbers the audit had to compute by hand from raw events/
            # the archive — each already exists server-side; this
            # surfaces them directly in the same cheap per-tick snapshot
            # the dev console already polls, rather than a one-off
            # export.
            "dialogue_topic_share": self._dominant_topic_share(),
            "mood": dict(self.world.settlement.mood),
            "materials_flow_per_tick": self._materials_flow_per_tick(),
            "cognition_context_reflection_rate": self._cognition_context_reflection_rate(),
        }

    def _dominant_topic_share(self) -> dict | None:
        """P3.4: `Settlement.top_topics(1)` already ranks the founding
        settlement's recent dialogue topics — this just also computes
        its share of the tracked window, the number the audit actually
        wanted (a live regression signal for the "spring rhythm keeps
        coming up" monoculture class of bug, see v0.87.35)."""
        topics = self.world.settlement.recent_topics
        if not topics:
            return None
        top = self.world.settlement.top_topics(1)
        if not top:
            return None
        topic, count = top[0]
        return {"topic": topic, "share": round(count / len(topics), 3)}

    def _materials_flow_per_tick(self) -> float | None:
        """P3.4: net materials change per tick over `_materials_level_
        history`'s window — positive means the settlement(s) are
        accumulating materials faster than they're spending them,
        negative means the reverse (a live "is construction starving"
        signal, see P0.3/materials_critical)."""
        if len(self._materials_level_history) < 2:
            return None
        first_tick, first_level = self._materials_level_history[0]
        last_tick, last_level = self._materials_level_history[-1]
        tick_span = last_tick - first_tick
        if tick_span <= 0:
            return None
        return round((last_level - first_level) / tick_span, 4)

    def _cognition_context_reflection_rate(self) -> dict:
        """P3.4: incremental live counterpart to review_diagnostics.py's
        export-time Context Influence section — see `self._cognition_
        context_stats`'s docstring for why this is a coarser any-vs-
        none signal rather than the export's full per-field breakdown."""
        scored = self._cognition_context_stats["scored"]
        return {
            "examples_scored": scored,
            "any_context_reflected_rate": (
                round(self._cognition_context_stats["any_reflected"] / scored, 3) if scored else None
            ),
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
            # Explicit live-report follow-up ("Nature and especially
            # Reflection still feel disconnected... not forming any
            # hypothesis even after 13k ticks"): on-demand only, not
            # per-tick — `_detect_reflection_pattern` scans every
            # settlement's signal counts plus up to MAX_CONCEPTS_STORED
            # invented concepts, the same "don't compute every tick"
            # reasoning peak_memory_rss_mb/system_memory below follow.
            "pillar_cognition_status": self._pillar_cognition_status(),
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
