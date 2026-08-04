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
import hashlib
import itertools
import json
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
    composite_reaction_propose,
    faction, fission, beliefs, caravan, chronicle, chronicler, composite_entity, consciousness, culture,
    culture_digest, dialogue,
    digest, dispute, documentary, dream, era_branch, festival, folklore, founding, geography, invention,
    legend,
    memory_drift, migration, mind, musing,
    naming, narrative_direction, omens, pillar_chat, religion, rumor_interpret, skill_mastery, species_variant, summary,
    town_brain,
    diplomacy, laws, letters, noncore_nudge, institution_culture, nature_causal_reasoning, nature_mind,
    reflection, rule_propose,
)
from hearthmind.llm import ontology as ontology_llm
from hearthmind.llm import self_tuning
from hearthmind.world.affordances import discover_combinations
from hearthmind.world.chemistry import discover_reactions
from hearthmind.world.materials import (
    BUILDING_MATERIALS, building_affordances, building_instance_affordances, effective_material_name,
)
from hearthmind.world.sigils import generate_sigil_svg
from hearthmind.world import memetics
from hearthmind.world import ontology
from hearthmind.world import reactions
from hearthmind.world.architecture_grammar import building_descriptor
from hearthmind.world.layout_grammar import drift_layout_style
from hearthmind.world.dialect_grammar import drift_term
from hearthmind.world import emergence
from hearthmind.world import graph_algorithms
from hearthmind.world import legends
from hearthmind.world import spatial_memory
from hearthmind.world import culture_aggregate
from hearthmind.cognition import attention
from hearthmind.cognition.pillar import make_message
from hearthmind.cognition.surprise import SurpriseSpecialist
from hearthmind.world.disasters import FLOOD_PRESSURE_THRESHOLD, GOVERNOR_TUNING_BAND, HEATWAVE_PRESSURE_THRESHOLD, WILDFIRE_CHANCE_PER_WEEK
from hearthmind.world.terrain_evolution import REFOREST_MIN_FALLOW_WEEKS
from hearthmind.world.wildlife import (
    HARDINESS_VARIANT_BUMP, MAX_SPECIES_VARIANTS_STORED, SpeciesVariant, WILDLIFE_SEARCH_RADIUS,
)
from hearthmind.simulation.sandbox import evaluate_concept_dual_fork, run_counterfactual
from hearthmind.simulation.dormancy import DormancyManager
from hearthmind.simulation.history_compression import CompressionLadder, CompressionStage, StageThreshold
from hearthmind.ml.social_features import compute_social_features
from hearthmind.simulation.task_graph import PriorityClass, Task, TaskRegistry, TriggerKind
from hearthmind.simulation.scheduler import Scheduler, SubsystemBudget
from hearthmind.simulation.tuning import BangBangController, SafetyClass, TunableRegistry, register_llm_pacing_tunables
from hearthmind.simulation.runtime_diagnostics import runtime_diagnostics_report
from hearthmind.simulation.hardware_profile import GoodCitizenPolicy, HostProbe, MachineProfile, host_fingerprint, select_strategy
from hearthmind.simulation.forecasting import (
    ForecastAccuracyTracker, WorkloadForecaster, is_quiet_window, make_training_example,
)
from hearthmind.ml.specialist import LearningSpecialist
from hearthmind.simulation.persistence_scheduling import SnapshotPolicy, SnapshotScheduler
from hearthmind.simulation.escalation import CognitionBudget, EscalationLadder, Rung
from hearthmind.llm.client import build_llm_client, fetch_llama_server_metrics
from hearthmind.llm.review_diagnostics import context_reflects_any
from hearthmind.llm.json_schemas import schema_for_task
from hearthmind.llm.cognition import (
    RECENT_MEMORIES_IN_PROMPT, SURVIVAL_ENERGY_THRESHOLD, SURVIVAL_HUNGER_THRESHOLD, SYSTEM_PROMPT, build_prompt,
    fallback_goal, parse_goal,
)
from hearthmind.llm.jobs import CognitionRunner, _ResizableSemaphore
from hearthmind.llm.recorder import TrainingRecorder
from hearthmind.simulation.optimization_hypothesis import AdaptationHistory, AdaptationRecord, HypothesisLoop
from hearthmind.persistence.snapshot import (
    consciousness_log_count, events_by_category, events_since_tick, history_events,
    load_latest_snapshot, log_agent_memory_entry, log_consciousness_entry, log_event, log_metrics,
    recent_events, recent_events_diverse, recent_metrics, save_snapshot,
)
from hearthmind.agents.population import (
    DISPUTE_COOLDOWN_TICKS,
    FACTION_RIVALRY_MIN_MEMBERS,
    FACTION_RIVALRY_THRESHOLD,
    FISSION_MATERIALS_SHARE,
    FISSION_MIN_DISTANCE,
    GUILD_SKILL_MASTERY_THRESHOLD,
    MAX_SETTLEMENTS,
    MIGRATION_BOND_THRESHOLD,
    MIGRATION_CHANCE_PER_TICK,
    MIGRATION_HOUSING_PRESSURE_THRESHOLD,
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
    ALL_OCCUPATIONS,
    OCCUPATION_MAYOR,
    OCCUPATION_SHOPKEEPER,
    OCCUPATION_SURVEYOR,
    SHOPKEEPER_CARAVAN_YIELD_BONUS,
)
from hearthmind.settlement.buildings import (
    CULTURE_LIST_MAX_STORED,
    CURRENCY_CAPACITY,
    CURRENCY_SHORTAGE_THRESHOLD,
    DIPLOMATIC_HOSTILITY_THRESHOLD,
    cheapest_founding_cost,
    ERA_DESCRIPTIONS,
    FAMILY_FEUD_FESTIVAL_PENALTY,
    FESTIVAL_CHANCE_PER_MONTH,
    FESTIVAL_HUNGER_GATE,
    FOLKLORE_LEGEND_PERSISTENCE_THRESHOLD,
    FOLKLORE_MAX_STORED,
    LEGENDS_MAX_STORED,
    GRANARY_CAPACITY,
    INNOVATION_HYPOTHESIS_CONFIDENCE_THRESHOLD,
    INNOVATION_HYPOTHESIS_INVENTION_BONUS_WEIGHT,
    INVENTION_CHANCE_PER_SEASON,
    INVENTION_CURRENCY_THRESHOLD,
    INVENTION_KNOWLEDGE_MAX_TRACKED,
    INVENTION_MATERIALS_FRACTION,
    INVENTION_SPECIALIZATION_CAP,
    INVENTION_SPECIALIZATION_STEP,
    LAWS_MAX_STORED,
    LAW_SIGNAL_THRESHOLD,
    VILLAGE_PATTERN_CONVICTION_LAW_THRESHOLD,
    VILLAGE_DOMESTICATE_CONVICTION_THRESHOLD,
    DOMESTICATE_MIN_HERD_SIZE,
    DOMESTICATE_HERD_FLOOR,
    DOMESTICATE_CAPTURE_SIZE,
    DOMESTICATE_FOOD_PER_ANIMAL,
    PASTURE_CAPACITY,
    PROSPERITY_CURRENCY_FRACTION,
    PROSPERITY_FESTIVAL_BONUS,
    PROSPERITY_MATERIALS_FRACTION,
    LEXICON_MAX_AGE_TICKS,
    LEXICON_MAX_STORED,
    LEXICON_MEANING_MERGE_OVERLAP,
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

INSTITUTION_BELIEF_TARGET_LEAN_WEIGHT = 0.4
"""Tier 0's fifth mirror-write -> pillar-authored conversion (docs/
ROADMAP-2026-07-REMAINING.md) — see `SimulationEngine._maybe_schedule_
institution_belief`'s docstring. Bounds how much `village_pillar.
subject_confidence(institution.name)` can multiply an institution's
base weight of 1.0 in the monthly target draw; kept modest so every
eligible institution still keeps a real, substantial chance."""

HUMANS_PERSONAL_TARGET_LEAN_WEIGHT = 0.4
"""Tier 0's sixth/seventh mirror-write -> pillar-authored conversions
(docs/ROADMAP-2026-07-REMAINING.md) — see `SimulationEngine._maybe_
schedule_memory_drift`/`_maybe_schedule_noncore_nudge`'s docstrings.
Bounds how much `humans_pillar.subject_confidence(agent.name)` can
multiply an agent's base weight of 1.0 in each job's monthly target
draw; kept modest so every eligible agent still keeps a real,
substantial chance. Same value as `INSTITUTION_BELIEF_TARGET_LEAN_
WEIGHT` — no reason for the two pillars' analogous mechanisms to tune
differently without a live-diagnostic reason to."""

INVENTOR_HUMANS_LEAN_WEIGHT = 0.4
"""Tier 0's eighth/ninth mirror-write -> pillar-authored conversions
(docs/ROADMAP-2026-07-REMAINING.md) — the two `_maybe_schedule_
invention`/`_maybe_schedule_ontology_proposal` sites that pick WHICH
candidate agent gets credited as an invention's inventor/first knower.
Same value and "never narrow the pool, only weight it" discipline as
`HUMANS_PERSONAL_TARGET_LEAN_WEIGHT`/`INSTITUTION_BELIEF_TARGET_LEAN_
WEIGHT` — no reason to tune this site differently without a live-
diagnostic reason to."""

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

RULE_PROPOSE_NUM_PREDICT_MULT = 2.0
"""Tier 0.5 item D5 (docs/ROADMAP-2026-07-REMAINING.md, live-diagnostic
report: "rule-generation occasionally produces malformed JSON"). The
original D5 framing proposed a `json_schema` grammar fix, the same
shape FT.0 gave every other high-volume task — but `rule_propose`
(`llm/rule_propose.py`) has run with `deep_reasoning=True` since
v1.3.37 ("the game learning/improving itself... deserves genuine
reasoning"), and `_schedule_llm_job`'s own structural rule (`reasoning
= deep_reasoning and task_schema is None`) means adding a schema here
would silently and permanently suppress that reasoning trace — exactly
the tradeoff `beliefs`/`personal_belief` deliberately avoided by having
their schemas REMOVED in the same v1.3.37 pass (see json_schemas.py's
module docstring). Investigating instead: `rule_propose` asks for a
10-field JSON contract (name/description/trigger/hook_type/hook_target/
magnitude, plus a full second trigger-and-effect set), close to
`personal_belief`'s own diagnosed shape (a large free-form answer
sharing one flat reasoning-trace token budget with every simple 2-4
field reasoning job) — the same failure class `PERSONAL_BELIEF_NUM_
PREDICT_MULT` fixed above, not something a schema would fix without
also silencing the reasoning `_schedule_llm_job` was deliberately
switched on for. Applied the identical fix shape instead: extra token
headroom via `num_predict_mult`, no schema. Sized lower than
`personal_belief`'s 3.0x (10 fields vs. 14, and most of `rule_propose`'s
fields are short closed-vocabulary tokens, not free prose) — a
reasoned starting point, re-tune from a live `/diagnostics` reading of
`last_llm_calls.rule_propose.fallback_reason` the same way every other
constant here is tuned."""

LARGE_SCHEMA_REASONING_NUM_PREDICT_MULT = 1.75
"""Tier 7 preflight P1 (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md): a
live 64,453-tick soak showed `ontology_proposal` failing its one and
only real call with `raw_model_output: ""` — the exact same failure
class `PERSONAL_BELIEF_NUM_PREDICT_MULT` fixed above (a `deep_
reasoning=True` job with no `json_schema`, per v1.3.37's "reasoning and
schema-constraint don't compose" rule, sharing the flat 1.5x `DEEP_
REASONING_NUM_PREDICT_MULT` budget with every simple 2-4-field job),
just never generalised past `personal_belief`/`rule_propose` to every
job in the class. `ontology_proposal` (name/description/hypothesis/
category/hook_type/hook_target/magnitude, 7 fields plus by far the
longest prompt of any reasoning task recorded — avg 743 tokens),
`beliefs`/`institution_belief` (subject/belief/confidence/revises/
digest-or-objective_reason, 5 fields each) and `narrative_direction`
(summary/coined_term/coined_meaning, 3 fields, not observed failing in
that soak but sharing the identical structural shape) all get this one
shared headroom multiplier rather than four separately-tuned ones —
same "reasoned starting point, not a live measurement" discipline as
`RULE_PROPOSE_NUM_PREDICT_MULT`; re-tune per-task from a live `/
diagnostics` reading of `last_llm_calls.<task>.fallback_reason` if any
of the four still falls back."""

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

REFLECTION_PILLAR_CONVICTION_EXPERIMENT_THRESHOLD = 0.8
"""C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-2026-07-
22.md's Part C, Tier 3, "propose experiment"): the bar `reflection_
pillar`'s own mirrored confidence in a still-OPEN hypothesis must clear
for `_maybe_schedule_self_tuning` to genuinely INITIATE testing it
early — the sandboxed self-tuning/advisory path (item 1.3's "test the
hypothesis in a jar") normally only ever considers a hypothesis once
`REFLECTION_SUPPORTED_THRESHOLD` is crossed through the slower, multi-
cycle evidence-accumulation loop in `_reevaluate_reflection_
hypotheses`. `reflection_pillar.world_model`'s mirrored confidence is a
genuinely distinct signal from `reflection_notebook`'s own evolving
`confidence` field — it's a one-time snapshot taken at proposal time
that never re-syncs with the notebook's own reevaluation, so this
captures "Reflection's own persisted conviction was already strong,
independent of how the evidence has drifted since" rather than
duplicating the notebook's own promotion math. Deliberately higher
than `VILLAGE_PATTERN_CONVICTION_LAW_THRESHOLD` (0.75) — bypassing the
Body-authoritative promotion process entirely, not just re-opening a
reset counter, warrants a stricter bar. Still requires the notebook's
own `confidence` to be above `REFLECTION_REJECTED_THRESHOLD` (evidence
stays authoritative: an idea already trending toward rejection can
never be force-tested purely on stale initial conviction)."""

VILLAGE_CUSTOM_CONVICTION_THRESHOLD = 0.85
"""C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-2026-07-
22.md's Part C, Tier 3, "set custom"): the bar `village_pillar`'s own
confidence about one of `_LAW_PATTERN_TEXT`'s hardship subjects must
clear before `_maybe_schedule_ontology_proposal` genuinely FORCES the
proposal's category to `"custom"` — overriding whatever category the
LLM itself would otherwise freely pick among `VILLAGE_PROPOSE_
CATEGORIES`'s six options. Reuses `laws.py`'s own closed pattern
vocabulary rather than inventing a second one: a custom is the
informal, not-yet-codified sibling of a law — the same lived hardship
that can (independently) cross `_maybe_schedule_laws`'s own bar for a
formal rule can also, on its own persisted conviction, make Village
originate an informal custom about it. Deliberately the same bar as
`VILLAGE_LAND_USE_CONVICTION_THRESHOLD`/`REFLECTION_PILLAR_CONVICTION_
EXPERIMENT_THRESHOLD` — every C2 slice that overrides an already-
decided outcome (not merely initiates a call) holds to this stricter
bar than the two that only initiate (`VILLAGE_PATTERN_CONVICTION_LAW_
THRESHOLD`=0.75). Only ever supplies a MISSING `pressure_signal` (see
`_maybe_schedule_ontology_proposal`'s existing Body-driven derivation)
— a real, fresh, threshold-crossing occurrence count is never
overridden by conviction, only the "no specific problem" fallback is."""

VILLAGE_INSTITUTION_REORGANIZE_CONVICTION_THRESHOLD = 0.85
"""C2 "Intention channel" (Mind -> Body, Tier 3, "reorganize
institution"): the bar `village_pillar`'s confidence about a SPECIFIC
declining guild (keyed by that guild's own `Institution.name`, the
skill it formed around) must clear before `_detect_guild_decline`
genuinely RENAMES the guild to a different skill its own living
members have actually mastered — a real restructuring around a new
purpose, not a fresh institution. No dissolution mechanism exists
anywhere in this codebase (institutions persist until pruned by
`INSTITUTION_LIST_MAX_STORED`), so reorganizing in place — preserving
membership/beliefs/history — is the safe, mechanically real shape this
intention can take without inventing a second, riskier mechanism.
Same bar as every other override-class C2 slice (`VILLAGE_LAND_USE_
CONVICTION_THRESHOLD`/`VILLAGE_CUSTOM_CONVICTION_THRESHOLD`). Body
stays authoritative: a rename only ever fires when the guild is
ALREADY genuinely declining (per `_detect_guild_decline`'s own
same-tick check) AND at least one of its own living members already
holds real mastery in the candidate skill AND that skill has no guild
of its own yet in the settlement — conviction alone, with no real
alternate-skill master among the guild's own membership, can never
manufacture a reorganization."""

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

SCENT_FISSION_AVOID_THRESHOLD = 0.6
"""A1 FieldGrid `scent` field's real consumer: a candidate fission site
in a region at or above this reading (real predator-pack presence,
`FieldGrid.step_scent`) is avoided when a less dangerous alternative
exists — same "never a hard block" shape `POPULATION_DENSITY_FISSION_
AVOID_THRESHOLD` established. Applied AFTER the density filter, so a
founding party first avoids crowding, then (among what's left) avoids
visibly dangerous ground."""

FERTILITY_FISSION_PREFER_THRESHOLD = 0.4
"""A1 FieldGrid `fertility` field's real consumer: a candidate fission
site in a region at or above this reading (`FieldGrid.step_fertility`,
regional average of `FarmGrid.soil_fertility`) is PREFERRED over one in
a less fertile region, when at least one qualifying candidate exists —
the one POSITIVE preference among `_choose_fission_site`'s three
region-field filters (density/scent both only ever avoid); "a founding
party seeks good farmland when it exists," never a hard block — an
unfarmed map (every region reads 0.0, the honest "nothing planted
anywhere yet" default) falls through to the unfiltered candidate list
exactly like every other filter here. Applied LAST, after density/
scent, so it only narrows what survives those two."""

HAZARD_FISSION_AVOID_THRESHOLD = 0.5
"""A1 FieldGrid `hazard` field's real consumer (`FieldGrid.step_
hazard`, regional average of `World.disaster_scars` — part of
migrating mining/disaster scars/the climate grid onto `FieldGrid`,
docs/ROADMAP-2026-07-REMAINING.md): a candidate fission site in a
region at or above this reading is avoided when a less disaster-prone
alternative exists — same "never a hard block" shape `SCENT_FISSION_
AVOID_THRESHOLD` established. Applied after density/scent/fertility,
so it only narrows what survives all three."""

REFLECTION_COHERENCE_MIN_TOTAL = 10
REFLECTION_COHERENCE_ABANDONED_RATIO = 0.5
"""Vision doc item 5.3 ("Coherence/drift detection... the immune system
for long-run open-ended growth"): a genuine incoherence signal — most
of what the village has ever imagined never caught on. Requires at
least `_MIN_TOTAL` concepts ever registered (a small sample reads as
noise, same "enough real data" gate every other Reflection branch
uses) before the abandoned fraction is trusted as a real pattern, not
early-game normal churn."""

OCCUPATION_SHORTAGE_POPULATION_THRESHOLD = 15
"""Tier 0, new producer: `_detect_occupation_shortage` only flags a
settlement whose living population is at or above this bar — with
`ALL_OCCUPATIONS` (~13 entries, MAYOR capped separately) assigned to
whoever's fewest-represented, a small/young settlement will trivially
have several occupations at zero simply because it hasn't grown into
needing them yet. Past this size a persistent zero reads as a real
gap, not early-game normal."""

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

NATURE_SUCCESSION_STALL_WEEKS_MULTIPLIER = 4
"""Tier 0's Nature causal-reasoning job, third trigger (docs/ROADMAP-
2026-07-REMAINING.md's design note, "forest succession stalling well
past REFOREST_MIN_FALLOW_WEEKS"): a fallow tile whose `World.fallow_
ticks` count has reached `REFOREST_MIN_FALLOW_WEEKS * this` — 12 weeks
at the default 3 — has been eligible to reclaim for a long stretch and
just keeps losing its `REFOREST_CHANCE_PER_WEEK` roll; genuinely
unlucky, not stalled by a bad structural reason, but a real anomaly a
land-intelligence might wonder about."""

NATURE_SUCCESSION_STALL_MOISTURE_MIN = 0.45
"""The "despite favorable moisture" half of the same trigger — only a
stalled tile whose local `HydrologyField.at(x, y)` reading is at or
above this counts as the genuinely puzzling case (a stall on genuinely
DRY ground has an obvious mundane explanation and isn't worth asking
about); a tile stalled with poor moisture is skipped, not flagged, so
a future tick can still react once either a wetter tile crosses the
week threshold or this same tile's own moisture later improves."""

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

TRADITION_KEEPING_SPREAD_CHANCE_PER_TICK = 0.02
"""A17 follow-up (docs/ROADMAP-2026-07-REMAINING.md, "Information
ecosystem unification"): per-tick, per-named-settlement roll driving
`_maybe_spread_tradition_keeping` — same order of magnitude and same
"gradual uptake, not an instant flip" reasoning as `CONCEPT_SPREAD_
CHANCE_PER_TICK` above, deliberately unchanged from it rather than
independently tuned (no live signal yet to justify a different rate)."""

TRADITION_PILLAR_LEAN_WEIGHT = 0.4
"""Tier 0 conversion (docs/ROADMAP-2026-07-REMAINING.md): `_maybe_
spread_tradition_keeping`'s WHICH-tradition-to-spread-this-tick pick
was flat `rng.choice(settlement.traditions)` — now a weighted draw
folding in `village_pillar.subject_confidence(tradition)`, same shape
`HUMANS_PERSONAL_TARGET_LEAN_WEIGHT` already uses at its own sibling
site. `weight=None`/all-zero-confidence reproduces a uniform draw
(verified statistically); the underlying RNG-consumption pattern
itself is NOT byte-identical to `rng.choice` (same acknowledged,
documented class of change as v1.34.109's `_maybe_schedule_personal_
belief` conversion — determinism/reproducibility isn't a project
requirement, only the distribution needs to hold)."""

KEPT_TRADITIONS_CAP = 5
"""Cap on `Agent.kept_traditions` — a person can meaningfully hold onto
a handful of traditions as their own, not the whole settlement list;
oldest-kept is evicted FIFO past this, same small-personal-cap shape as
`MAX_CORE_MEMORIES`/`Agent.secrets`, not `ontology.MAX_ADOPTERS_
STORED`'s much larger settlement-wide-registry scale."""

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

REACTIVE_TRIGGER_BACKPRESSURE_RETRY_TICKS = 50
"""Live-diagnostic finding: `_maybe_schedule_nature_causal_reasoning`'s
three triggers (predator/grazer extinction, succession stall) are
checked UNCONDITIONALLY every tick while their own anomaly persists and
their edge-trigger flag stays unset — unlike every cadence-gated
settlement job (month/season/year boundary, or a bounded retry window),
there is no natural pacing between attempts. A real 40k-tick run showed
`nature_causal_reasoning` succeeding only 6 times total while `calls_
dropped_backpressure` reached 10022 — cross-referencing the anomaly
windows in that run's own `nature_pillar.world_model` timestamps against
its `llm_backpressure_limit_effective` (3, from a `llm_max_concurrent=1`
deployment) makes clear the bulk of those drops were the SAME still-
unresolved anomaly's backpressure check re-firing every single tick for
thousands of consecutive ticks, not thousands of genuinely distinct
scheduling attempts. `_reactive_pillar_backpressured` backs a rejected
trigger off for this many ticks before checking again — the anomaly
itself is still noticed the instant it starts (the cheap non-LLM state
read stays unconditional every tick), only the expensive/counted
backpressure re-check is throttled. 50 ticks is a small fraction of the
thousands-of-ticks anomaly durations observed, so it costs at most a
negligible delay before the eventual successful call; it just stops
counting the same still-saturated queue thousands of times over."""

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

VOICE_NARRATIVE_HUMANS_LEAN_MAX = 2000.0
"""Tier 0's thirteenth conversion (docs/ROADMAP-2026-07-REMAINING.md):
the ceiling `humans_pillar.subject_confidence(agent.name)` (0..1) can
add to `_voice_narrative_extra_scores`'s per-agent bonus dict — same
magnitude family as the inventor/council bonuses above, deliberately
kept below both so a standing Humans theory nudges the weekly
protagonist pick without ever outweighing a genuinely dramatic recent
event."""

GUILD_FOUNDER_HUMANS_LEAN_MAX = 0.2
"""Tier 0's sixteenth conversion (docs/ROADMAP-2026-07-REMAINING.md):
the ceiling `humans_pillar.subject_confidence(agent.name)` (0..1) can
add to a candidate master's `TRAIT_AMBITION` reading in `Population.
deliberate_guild_candidate`'s founder pick. Traits live in [-1, 1]
(`GENOME_FOUNDER_ALLELE_STDDEV=0.35`) — a max 0.2 lean can plausibly
edge out a close rival but can't manufacture a founder from a
genuinely unambitious master, since the eligibility floor (`DELIBERATE_
GUILD_FOUNDER_AMBITION`) is checked against the real trait afterward,
never the lean-boosted score. Reused unchanged (same trait scale, same
"no reason to tune differently" discipline) by Tier 0's seventeenth
conversion, `Population.fission_candidate`'s leader pick."""

NATURE_OMEN_SUBJECT_LEAN_MAX = 0.4
"""Tier 0's twentieth conversion (docs/ROADMAP-2026-07-REMAINING.md),
explicit user decision extending v1.34.9's one-time Phase G carve-out:
the ceiling `nature_pillar.subject_confidence(candidate_name)` (0..1)
can add to an omen subject candidate's `rng.choices` weight (base
1.0), same magnitude family as the other Tier 0 lean weights. Honestly
often a no-op in practice — Nature's own `world_model` content is
ecological, not usually agent- or institution-named — but real when a
genuine overlap exists."""

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

ADAPTIVE_CONCURRENCY_TARGET_MS = ADAPTIVE_LATENCY_ELEVATED_MS
ADAPTIVE_CONCURRENCY_HYSTERESIS_MS = 15_000
"""Tier 5 B6 adaptive tuning's real control point (`_maybe_tune_llm_
concurrency`): the `BangBangController` steering `Config.llm_max_
concurrent`'s live value targets the SAME `ADAPTIVE_LATENCY_ELEVATED_
MS` reading `_current_backpressure_limit` already treats as "healthy
ceiling" — one shared definition of "comfortable" latency, not two
independently-tuned numbers that could drift apart. Hysteresis 15s
wide gives a no-op dead zone of roughly [30s, 60s] around the 45s
target, so a single noisy reading can't flip the verdict — matches
`BangBangController`'s own stated anti-chatter purpose."""

ADAPTIVE_CONCURRENCY_MIN_EVIDENCE = 20
"""`_maybe_tune_llm_concurrency` skips its daily check entirely below
this many total attempted calls — a p95 reading over a handful of
calls is noise, not evidence; this mirrors the same "don't act on a
near-empty sample" discipline `ForecastAccuracyTracker`'s cold-start
default (simulation/forecasting.py) already uses elsewhere in Tier 5."""

ADAPTIVE_TUNING_LOG_MAX = 200
"""Bounded ring-buffer size for `SimulationEngine._adaptive_tuning_
log` — same cap-and-append discipline as every other unbounded-growth-
prone list in this codebase (traditions/inventions/events/etc.)."""

WORKLOAD_REPLAY_CAPACITY = 300
"""Tier 7 HCA G2: the `LearningSpecialist` wrapping B8.1/L3.2's
`WorkloadForecaster` rehearses this many past real (features, observed
call volume) examples alongside each new batch — same reservoir-sample
sizing order of magnitude as every other `ReplayBuffer` this codebase
constructs."""

WORKLOAD_CHECKPOINT_CAPACITY = 10
"""Bounded `CheckpointHistory` size for the workload forecaster's
`LearningSpecialist` — small since a rollback target rarely needs to
reach further back than a few accepted retrains."""

WORKLOAD_SAMPLE_HORIZON_DAYS = 1
"""How long after sampling a real feature snapshot before it's paired
with the REAL observed call-volume delta since then — one day, matching
this forecaster's own "near-term" framing (B8.1's docstring)."""

WORKLOAD_PENDING_SAMPLES_MAX = 40
"""Bound on in-flight (sampled, not yet resolved) feature snapshots —
generously above `WORKLOAD_SAMPLE_HORIZON_DAYS` days' worth of daily
samples, never meant to actually fill up in normal operation."""

WORKLOAD_TRAINING_EXAMPLES_MAX = 200
"""Bound on accumulated-since-last-retrain training examples — oldest
evicted first, same cap-and-append discipline as every other unbounded-
growth-prone list in this codebase."""

WORKLOAD_MIN_EXAMPLES_TO_RETRAIN = 20
"""A monthly retrain attempt is skipped entirely below this many
accumulated real examples — real month-boundary evidence, never a
guess extrapolated from a handful of samples."""

WORKLOAD_HOLDOUT_FRACTION = 0.3
"""Fraction of this cycle's accumulated examples held out (never
trained on) to genuinely shadow-gate the retrained candidate against —
see `LearningSpecialist.learn`."""

WORKLOAD_LEARN_LOG_MAX = 24
"""Bounded, newest-first-readable log of every real workload-forecaster
retrain attempt (`SimulationEngine._workload_learn_log`) — dev-console/
diagnostics visibility, same shape as `_adaptive_tuning_log`."""

MACHINE_PROFILE_FILENAME = "machine_profile.json"
"""Tier 5 B7.2's real control point (explicit user directive: "B8 and
MachineProfile persistence... flagged for later" — closing that flag).
Stored as a sibling file next to `Config.db_path` so it travels with a
world's own data directory rather than a hardcoded absolute path; a
`:memory:` `db_path` (every verify script, `experiment.py`) keeps the
profile in-RAM only for that process's lifetime — see `_machine_
profile_path_for`."""

RECENT_LLM_BACKLOG_SAMPLES_MAX = 30
"""Tier 5 B8.4's real control point: `_maybe_tune_llm_concurrency`
(daily) appends one `CognitionRunner.backlog` reading here regardless
of whether it goes on to skip its own tuning check — roughly a
month's worth of daily samples, enough for `is_quiet_window` to judge
"has load stayed low for a good while," never a single lucky reading."""

ESCALATION_COGNITION_BASE_BUDGET = 1_000_000
"""Tier 5 B15.4's `CognitionBudget` at every rung except `REDUCE_
COGNITION_BREADTH` (rung 5) — a number no real tick's `_schedule_due_
cognition` per-tick due-list could ever reach (staggered daily slots
already bound it far below population size), so rungs 1-4 leave real
per-tick LLM cognition scheduling completely untouched, matching the
doc's own framing that only rung 5 does real, visible work."""

ESCALATION_COGNITION_REDUCED_BUDGET = 3
"""Tier 5 B15.4's `CognitionBudget` at rung 5 (`REDUCE_COGNITION_
BREADTH`) — a real cap on how many core-cast agents may spend an LLM
cognition call in one tick once sustained pressure has exhausted rungs
1-4. A reasoned floor, not a live measurement: high enough that a
triggered emergency (grief, hunger) can still usually get through, low
enough to be a genuine reduction from the effectively-unbounded normal
budget above. WHICH agents fill this budget stays entirely `due_for_
cognition`'s own staggered-slot/significance ordering — B15.4's own
"never a selection" guarantee."""

CONCURRENCY_PROBE_TASKS = 12
"""Tier 5 B13's real active-probe measurement (`_probe_concurrency_
wait_ms`): how many synthetic asyncio tasks compete for the throwaway
semaphore each probe call. High enough that a small concurrency limit
(1-2) produces real, measurable queueing against a larger one (6-8)
within a few probe calls; low enough that a probe run costs well under
a second even at the smallest concurrency setting."""

CONCURRENCY_PROBE_HOLD_SECONDS = 0.02
"""Tier 5 B13's real active-probe hold duration per synthetic task —
short enough that `CONCURRENCY_PROBE_TASKS` probes complete quickly,
long enough that real `asyncio` scheduling overhead doesn't dominate
the measured signal."""

CONCURRENCY_EQUIVALENCE_CHECK_TICKS = 30
"""Tier 5 B13.2's real semantic-safety gate for `llm_max_concurrent`
(`_concurrency_equivalence_check`): how many ticks each forked world
runs before comparing state hashes. Short — `llm_max_concurrent` only
ever gates async LLM-call scheduling, never anything `World.tick()`
itself reads, so a genuine divergence (if the tunable's meaning ever
changed) would show up on the very first tick; this is a real,
reasoned floor, not a live-measured value, same "not tuned against
production data" honesty every other Tier 5 constant docstring in this
file already states where true."""

LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS = 14
"""Explicit user directive ("keep building adaptive runtime to what I
originally wanted"): the automatic cadence for `HypothesisLoop` over
`llm_max_concurrent` (`_maybe_auto_llm_concurrency_hypothesis`),
without letting it fight `_maybe_tune_llm_concurrency`'s own live
`BangBangController` over the SAME tunable — the exact correctness
risk `self._llm_concurrency_hypothesis_loop`'s own docstring named as
the reason this control point was originally left manual-only.
Resolved by gating strictly on QUIESCENCE: the automatic check only
ever fires once the reactive latency controller has made no real
change (`self._adaptive_tuning_log`) for this many real days — by
which point the reactive controller has settled on whatever value
current LLM latency alone justifies, so a hypothesis test proposing a
DIFFERENT, hardware-derived value (`select_strategy`'s own `llm_max_
concurrent_hint`, already computed daily but previously only consulted
as a downward-only cap) genuinely tests a distinct hypothesis rather
than racing an active adjustment. 14 days is a real, reasoned choice
(long enough that a transient latency blip's own reactive response has
long since settled; short enough that a genuinely stale value doesn't
sit untested for months), not tuned against production data — the
same honesty every other Tier 5 constant in this file states where
true."""

BROADCAST_SUBSYSTEM_BUDGET_SECONDS = 0.015
"""Tier 5 B2's real control point: `_maybe_broadcast` (the per-tick
WebSocket payload build — agents/buildings/summary/etc., explicitly
cosmetic and safe to lag a few ticks under load, unlike every one of
B0.3's CRITICAL migrations, which all deliberately reproduce "always
runs, budget or not") now runs through its own dedicated B1/B2
`TaskRegistry`/`Scheduler` pair as a real `PriorityClass.DEFERRABLE`
task with a real wall-clock budget, instead of an unconditional direct
call.

Sized from a direct measurement in this environment, not guessed: a
60-population, 64x64-tile world's real non-idle `_maybe_broadcast()`
call (client_count forced >0 to skip the idle-world fast path) showed
p50 ~9.5ms, max ~40ms over 30 calls. 15ms sits a little above the
measured p50.

**Verified, not assumed, what this actually exercises**: a direct test
(`scripts/verify_b2_broadcast_budget.py`) proved that under this
dedicated-single-task-registry-called-once-per-real-tick pattern —
the same shape every B0.3 migration uses — `Scheduler.run_tick()`
resets `SubsystemBudget.consumed_this_tick` to 0 at the END of every
call, so `remaining()` is always full again by the time the NEXT
call's due-check runs; a solo task therefore always executes (`ran`,
never `deferred`) regardless of priority class, since there is no
sibling task in the same registry+tick to have already spent the
budget before this one's check. DEFERRABLE is still the semantically
honest declaration (this job genuinely is safe to lag), but the
promotion/deferral-bound machinery (`DEFAULT_MAX_DEFERRALS`) has no
real chance to fire from this wiring alone — a real regression test
proves this directly rather than silently assuming it. What IS real
and newly exercised: `SubsystemBudget.debt_seconds` — an overrunning
broadcast genuinely and permanently accrues real overrun debt every
tick it runs over budget, surfaced via `all_budgets()`/diagnostics,
the first live signal of its kind for this job. Making deferral
itself fire for a real per-tick job would need either a second task
sharing this subsystem's budget within the same `run_tick()` call, or
a genuinely different (larger-scope, not attempted here) redesign
where budget state persists across calls instead of resetting each
one — flagged as real future work, not silently glossed over."""

LLM_PRESSURE_SLOWDOWN_START_RATIO = 0.5
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
(0.5 as of v1.34.83, was 0.75) is too eager (would strip reasoning from
routine minor load); just under `LLM_PRESSURE_PAUSE_RATIO` (2.0) is
too late (the queue is
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
Below `LLM_PRESSURE_SLOWDOWN_START_RATIO` (0.5, i.e. comfortably under
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
saturation, never normal operation.

**Lowered 0.75 -> 0.5 in v1.34.83**, explicit user directive ("I am
okay with occasional slow world progression") following a live-
diagnostic backpressure-drop investigation (v1.34.80-.82, same
deployment: `llm_max_concurrent=1`, `BACKPRESSURE_BACKLOG_PER_SLOT=3`
giving a static limit of 3). At integer concurrency this low, `llm_
pressure_ratio()` only ever takes values `k/3` (0, 0.33, 0.67, 1.0,
...) — 0.75 sits strictly BETWEEN 0.67 and 1.0, so a backlog of 2
(already effectively saturated for a single-slot server — one call
executing, one queued) read as ratio 0.67 and never engaged slowdown
at all; only a backlog of 3 (already at the point new attempts get
dropped) crossed 0.75. By the time v1.34.81/.82's fixes closed the
two structural bugs that had been re-counting the SAME still-
saturated queue as a fresh drop every tick, this reachability gap
became the dominant remaining source of drops: genuinely distinct
scheduling attempts landing on a backlog of 2, engaging no pacing,
and immediately queuing into a backlog of 3 where they're now the
one that gets dropped. 0.5 makes a backlog of 2 (ratio 0.67 > 0.5)
engage a real, if modest, slowdown BEFORE the queue is completely
full, giving in-flight calls more real time to drain before the next
wave of scheduling attempts arrives — trading some world-progression
speed for fewer wasted attempts, the explicit tradeoff requested.
Still comfortably above `LLM_PRESSURE_SPEEDUP_START_RATIO` (0.15), so
the speedup band and a real "just right" zone (0.15-0.5) both survive
unchanged; a healthy multi-slot deployment (e.g. `llm_max_concurrent
=2`, limit 6) is affected the same directional way but less sharply,
since its ratio granularity (`k/6`) resolves 0.5 exactly rather than
straddling it. Between START_RATIO and `LLM_
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
`LLM_PRESSURE_SLOWDOWN_START_RATIO`'s own floor (0.5 as of v1.34.83,
was 0.75), so the two bands never overlap and there's a real "just
right" zone at ratio 0.15-0.5 that stays at exactly 1.0x, matching a
normal healthy-but-not-idle run), the multiplier scales linearly DOWN
to `LLM_PRESSURE_MIN_
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


def _machine_profile_path_for(db_path: str) -> str | None:
    """Tier 5 B7.2's real control point: a `MachineProfile` persists as
    a sibling file next to the world's own `db_path` so it travels with
    that world's data directory. `None` for `db_path == ":memory:"`
    (every verify script, `experiment.py`'s ephemeral runs) — no real
    directory to place it next to, so the profile stays in-RAM only for
    that process's lifetime rather than writing somewhere surprising."""
    if db_path == ":memory:":
        return None
    directory = os.path.dirname(os.path.abspath(db_path))
    return os.path.join(directory, MACHINE_PROFILE_FILENAME)


def _load_or_create_machine_profile(path: str | None) -> MachineProfile:
    """Loads a persisted `MachineProfile` if one exists and is readable;
    falls back to a fresh profile for this host on ANY failure (missing
    file, corrupted JSON, an unsupported `schema_version`) — a bad
    profile file must never be able to crash startup, same "a probe
    must never crash its caller" discipline `HostProbe.sample()` itself
    holds to."""
    if path is None:
        return MachineProfile(host_fingerprint=host_fingerprint())
    try:
        return MachineProfile.load_or_create(path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return MachineProfile(host_fingerprint=host_fingerprint())


INSTITUTION_DORMANCY_IDLE_CHECKS_THRESHOLD = 3
"""Tier 5 B4.2 pilot ("idle institutions"): consecutive monthly
`_update_institution_dormancy` checks with an unchanged fingerprint
before an institution goes DORMANT. 3 checks (roughly a quarter, same
cadence as `institution_culture`'s own `season_end` gate) — a
reasoned starting point mirroring every other "how patient before
acting" constant in this file (e.g. `MONTHLY_JOB_RETRY_WINDOW_DAYS`),
not a live measurement; re-tune from a live `/diagnostics` reading of
how many institutions sit dormant if the round-robin ever narrows to
too few awake candidates."""


def _institution_dormancy_key(settlement: "Settlement", institution: "Institution") -> str:
    """`DormancyManager` entity id for one (settlement, institution)
    pair — a plain string since the manager is generic and knows
    nothing about real Hearthmind types."""
    return f"{settlement.id}:{institution.id}"


def _institution_fingerprint(institution: "Institution") -> tuple:
    """A cheap, cheap-to-compute proxy for "has this institution's own
    state actually moved since we last looked" — membership count, feud
    count, belief count, and its current objective text. Deliberately
    NOT `culture_digest` itself (that's the very field this dormancy
    decision gates the narration OF, so using it as the change signal
    would be circular) and deliberately NOT a deep content diff (this
    only needs to answer "idle or not," not "what changed")."""
    return (
        len(institution.member_agent_ids), len(institution.feuds),
        len(institution.beliefs), institution.objective,
    )


IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD = 3
"""Tier 5 B4.2, second candidate ("unused ideas"): same shape and same
threshold as `INSTITUTION_DORMANCY_IDLE_CHECKS_THRESHOLD` above — an
`InventedConcept` still in `proposed`/`spreading` status that gains no
new adopter across 3 consecutive monthly checks is dormant. Exactly
like the institutions pilot, this only narrows Mind-layer LLM/roll
ATTENTION (`_maybe_spread_concepts`'s per-tick roll list) — it never
skips a Body-affecting per-tick effect, so it stays compliant with
B15's `TWO_PART_GUARANTEE` the same way the institutions pilot is."""


def _idea_fingerprint(concept: "ontology.InventedConcept") -> tuple:
    """Cheap idle-vs-active proxy for a growing concept: status plus
    adopter count. A concept that keeps gaining adopters (or changes
    status) is active; one that sits with the same adopter count and
    status tick after tick is the "forgotten idea" this pilot targets."""
    return (concept.status, len(concept.adopter_ids))


TRADITION_DORMANCY_IDLE_CHECKS_THRESHOLD = 3
"""Tier 5 B4.2, third candidate ("forgotten traditions"): same shape
and same threshold as the institutions/ideas pilots above — a
(settlement, tradition) pair whose keeper count hasn't grown across 3
consecutive monthly checks is dormant."""


def _tradition_dormancy_key(settlement: "Settlement", tradition: str) -> str:
    """`DormancyManager` entity id for one (settlement, tradition) pair
    — namespaced by settlement id since the same tradition text could
    theoretically recur across settlements (independent coinage, not
    shared state)."""
    return f"{settlement.id}:{tradition}"


def _tradition_fingerprint(settlement: "Settlement", tradition: str, agents: list) -> int:
    """Cheap idle-vs-active proxy for one tradition: how many of this
    settlement's own agents (already pre-filtered to the settlement by
    the caller) currently keep it. A tradition that keeps gaining
    personal keepers is active; one whose keeper count sits flat tick
    after tick is the "forgotten tradition" this pilot targets.
    Deliberately NOT gated on the settlement's own population total — a
    shrinking settlement's flat keeper count is still real idleness,
    not noise to filter out."""
    return sum(1 for a in agents if tradition in a.kept_traditions)


SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD = 3
"""Tier 5 B4.2, fourth candidate ("inactive settlements"): same shape
and same threshold as the institutions/ideas/traditions pilots above.
Unlike the two candidates this pilot's own prior entries flagged as
needing a genuinely lossless elapsed-tick reconstruction (this one and
"distant wildlife"), "inactive settlements" turns out to have the
identical safe shape as the other three once scoped correctly: it
gates `_job_target()`'s existing month-indexed round-robin over WHICH
settlement gets this month's settlement-scoped LLM jobs (town_brain,
beliefs, chronicle, ...) — never `Population.tick()`/`WildlifeGrid.
tick()` for that settlement, which keep running every tick for every
settlement regardless. A settlement with nothing coarse-grained
changing about it for 3 consecutive monthly checks is dormant in the
Mind-layer-attention sense only; any real change wakes it immediately."""


def _settlement_fingerprint(settlement: "Settlement", population_count: int) -> tuple:
    """Cheap idle-vs-active proxy for one settlement: living population,
    era, standing building count, tech level — coarse, cheap-to-compute
    structural facts, deliberately NOT materials/currency (which drift
    every tick from ordinary economic activity and would make a
    settlement "active" forever, defeating the whole point). A
    settlement where none of these four shift for several consecutive
    monthly checks is genuinely quiet; a birth/death, era advance, new
    building, or invention wakes it immediately."""
    return (population_count, settlement.era, len(settlement.buildings), settlement.tech_level)


EMERGENCE_COMPRESSION_RAW_THRESHOLD = StageThreshold(max_count=EMERGENCE_LOG_MAX_STORED // 5, max_age_ticks=1_000_000)
"""B12's first real consumer: `World.emergence_log`'s own eviction
(`_append_emergence`, `EMERGENCE_LOG_MAX_STORED`) used to be plain
truncation — the oldest entries past the cap were simply discarded,
permanently and without a trace, once the cap was first reached. Now
an evicted batch is routed through a real `CompressionLadder` instead
(`SimulationEngine._emergence_compression`) — this threshold decides
how many evicted RAW entries accumulate before they're actually
condensed into one archived digest, deliberately smaller than the
full log cap (a fifth of it) so a real digest forms well before the
ladder's own in-flight RAW bucket could itself grow unbounded.
`max_age_ticks` is set high enough to never be the real trigger in
practice — volume is the intended real signal for this stream, same
as B12.1's own text allows ("either condition alone is sufficient")."""

EMERGENCE_COMPRESSION_ARCHIVE_MAX = 200
"""B12.2's real hard ceiling for the emergence-log archive specifically
— once the ladder's own condensed-digest archive exceeds this many
entries, the oldest digests are genuinely deleted (`prune_to_
capacity`), never allowed to grow without bound. At `EMERGENCE_
COMPRESSION_RAW_THRESHOLD` (100) raw entries per digest, 200 archived
digests represent roughly 20,000 raw observations' worth of condensed
history — a real, much longer memory than the live log's own 500-entry
window, at a bounded, fixed storage cost."""

EMERGENCE_SURPRISE_THRESHOLD = 0.3
"""Tier 7 HCA Stage A, A2 ("gate `world/emergence.py` on surprise, not
occurrence" -- docs/COGNITIVE-ARCHITECTURE-2026-08-02.md §1.3/§2.3):
the real fix for the soak-measured problem A1's own module docstring
names -- 93% of a 64k-tick soak's emergence log was `unexplained_
shift`, almost all of it "content agent decided to socialize," the
single most predictable event the simulation can produce. `_append_
emergence` now scores every candidate observation through `A1`'s
`SurpriseSpecialist` (`SimulationEngine._emergence_surprise`, keyed by
`f"{subsystem}:{kind}"`) BEFORE deciding whether to log it -- a
candidate whose precision-weighted surprise doesn't clear this
threshold is silently suppressed, never reaching `World.emergence_
log` at all. The specialist's running model is updated for EVERY
candidate regardless of whether it's logged (`SurpriseSpecialist.
score()` always calls `observe()`), so a routine signal's own surprise
genuinely falls the more it repeats, and a candidate that later
becomes routine after initially being novel correctly stops clearing
the gate on its own -- this is precision-weighted learning, not a flat
occurrence-count cap. A reasoned starting point (not a live
measurement -- this offline environment has no live archive to tune
it against), chosen low enough that a moderately novel signal (roughly
2-3x its own channel's typical deviation) still clears it, matching
A1's own test that a first-occurrence rare/severe signal scores well
above 2.0."""

EMERGENCE_SURPRISE_NEUTRAL_MAGNITUDE = 0.4
"""The value fed to `SurpriseSpecialist.score()` for a candidate
observation whose `magnitude` is `None` -- most `_append_emergence`
call sites don't set one (`make_observation`'s own docstring: `None`
means "a producer has no natural scale for it," not "zero severity").
A fixed neutral proxy rather than a fabricated per-call number, same
"reasoned starting point" discipline as `attention.py`'s own
`DEFAULT_SALIENCE=0.3` -- a channel that always reports this same
neutral value naturally converges to near-zero surprise once its
running model has seen enough repeats (the exact "content agent
socializes" flooding this item exists to suppress), while a channel
that DOES set a real `magnitude` is scored against its own genuine
severity reading instead."""


def _condense_emergence_entries(items: list) -> dict:
    """The real semantic half B12.1/B12.2 explicitly leave to the
    caller: turns a batch of evicted `world.emergence.Observation`
    dicts into one condensed digest — tick range, a count, a per-kind
    tally (which categories of emergence dominated this stretch), and
    a short representative sample (the single highest-`magnitude`
    entry's own summary text, the same "what mattered most" signal
    Tier 6's L2.1 value model targets) rather than concatenating every
    raw summary verbatim, which would defeat the point of compressing
    at all."""
    ticks = [item.get("tick", 0) for item in items]
    kind_counts: dict = {}
    for item in items:
        kind = item.get("kind", "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    most_notable = max(items, key=lambda item: item.get("magnitude") or 0.0)
    return {
        "tick_start": min(ticks) if ticks else 0,
        "tick_end": max(ticks) if ticks else 0,
        "count": len(items),
        "kind_counts": kind_counts,
        "notable_summary": most_notable.get("summary", ""),
    }


class SimulationEngine:
    def __init__(
        self, conn: sqlite3.Connection, config: Config, world: World,
        broadcaster: "WorldBroadcaster | None" = None,
    ):
        self.conn = conn
        self.config = config
        self.world = world
        self._stop_event = asyncio.Event()
        # Tier 5 B14.1's real control point (explicit user instruction:
        # "continue B and try closing it this turn"): a real
        # `SnapshotScheduler` replaces the old flat `_ticks_since_
        # snapshot >= snapshot_every_ticks` check. `max_interval_ticks`
        # is kept at the exact configured `snapshot_every_ticks` — the
        # existing worst-case durability guarantee (a snapshot always
        # happens by this point, regardless of load) is UNCHANGED.
        # `min_interval_ticks` is set to half that, so a genuinely
        # LLM-quiet stretch (the same real `is_quiet_window` signal
        # B8.4/B7.2 already wired) can opportunistically snapshot more
        # often — real, low-risk added durability, never less frequent
        # than before. Snapshot cadence has no bearing on deterministic
        # `World.tick()` state, so this can't affect `verify_replay_
        # hash.py`. B14.2 (`plan()`'s FULL/INCREMENTAL kind) is
        # deliberately NOT called here — `save_snapshot` has no real
        # diff/incremental-write mechanism to hand a planned kind to,
        # so consulting it would be decorative, not real; stays flagged
        # future work per persistence_scheduling.py's own module note.
        self._snapshot_scheduler = SnapshotScheduler(SnapshotPolicy(
            min_interval_ticks=max(1, config.snapshot_every_ticks // 2),
            max_interval_ticks=config.snapshot_every_ticks,
        ))
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

        # Tier 5 B6 adaptive tuning, wired to its real control point:
        # a real TunableRegistry + BangBangController pair (simulation/
        # tuning.py), seeded from the live `config.llm_max_concurrent`
        # (not the module's own hardcoded default of 2) so a CLI
        # override is respected as the controller's real starting
        # point. `_maybe_tune_llm_concurrency` (called daily) is what
        # actually steps this and applies a real change via `Cognition
        # Runner.resize_concurrency`. See tuning.py's own module
        # docstring for the full design.
        self._tuning_registry = TunableRegistry()
        register_llm_pacing_tunables(self._tuning_registry)
        self._tuning_registry.set_value("llm_max_concurrent", config.llm_max_concurrent)
        self._llm_concurrency_controller = BangBangController(
            tunable_name="llm_max_concurrent",
            target=ADAPTIVE_CONCURRENCY_TARGET_MS,
            hysteresis=ADAPTIVE_CONCURRENCY_HYSTERESIS_MS,
            increases_measurement=True,
        )
        self._hypothesis_history = AdaptationHistory()
        self._llm_concurrency_hypothesis_loop = HypothesisLoop(
            registry=self._tuning_registry,
            owned_tunable_names=frozenset({"llm_max_concurrent"}),
            history=self._hypothesis_history,
        )
        """Tier 5 B13's real first consumer (explicit user directive:
        "reverse the never-big-bang policy... build whatever is
        required for blocked items"). Deliberately a MANUALLY-invoked
        control point (`_run_llm_concurrency_hypothesis`, below) —
        never scheduled automatically into `_TICK_JOBS` — so it can
        never fight B6/B7's own already-live `BangBangController` over
        this SAME tunable. Two independent automatic controllers
        adjusting one value would be a genuine correctness risk this
        pass declines to introduce; a human-invoked what-if check
        alongside the live automatic controller is not."""
        self._llm_concurrency_hypothesis_running = False
        self._last_llm_concurrency_hypothesis: dict | None = None
        """Real dev-console/API surface for the manual B13 control point
        above — `/intervene/llm-concurrency-hypothesis` enqueues a
        request, `_apply_intervention`'s `llm_concurrency_hypothesis`
        branch spawns the real async probe+loop as a background task
        (same `_background_tasks` shutdown-drain discipline as every
        other fire-and-forget LLM/sandbox task in this file), and this
        field holds the most recent real `AdaptationRecord` as a plain
        dict for `full_diagnostics()` to surface. `_running` prevents a
        second request from starting a fresh probe while one is already
        in flight — one at a time, never queued/stacked."""
        # Tier 5 B7's real control point (explicit user directive: "B7"):
        # `GoodCitizenPolicy.should_back_off` is B7.4's own named input
        # signal for "a real scheduler would consult this" — B6's daily
        # concurrency controller (just above) is exactly that scheduler,
        # now that it's real. BALANCED, not configurable per-run yet
        # (a future CLI flag is real follow-up, not attempted here —
        # every prior B7 module was a pure function with zero call
        # sites, so even one fixed aggressiveness is new real wiring).
        self._hardware_citizen_policy = GoodCitizenPolicy()
        self._last_host_probe: HostProbe | None = None
        self._last_host_probe_back_off: bool = False
        self._last_host_probe_tick: int | None = None
        self._adaptive_tuning_log: deque[dict] = deque(maxlen=ADAPTIVE_TUNING_LOG_MAX)
        """Bounded, append-only record of every real `_maybe_tune_llm_
        concurrency` change (never a no-op check — those aren't
        logged, same "only what actually happened" discipline as
        `World.self_tuning_actions`) — dev-console-visible via `full_
        diagnostics()`'s `adaptive_tuning_log_recent`."""

        # Tier 7 HCA G2 (explicit user instruction: "Build G2"): B8.1/
        # L3.2's WorkloadForecaster gets the real continual-retrain
        # cadence its own docstring named as still open, via G1's
        # LearningSpecialist. `_workload_forecaster.model` and `_
        # workload_specialist.model` are kept in sync explicitly after
        # every `learn()` call (see `_maybe_tick_workload_forecaster`)
        # rather than sharing one mutable object, since `learn()` may
        # swap `self.model` to a whole new MLP instance on acceptance.
        self._workload_forecaster = WorkloadForecaster.new(seed=config.seed)
        self._workload_specialist = LearningSpecialist(
            self._workload_forecaster.model,
            replay_capacity=WORKLOAD_REPLAY_CAPACITY, checkpoint_capacity=WORKLOAD_CHECKPOINT_CAPACITY,
        )
        self._workload_accuracy_tracker = ForecastAccuracyTracker()
        self._cognition_calls_today = 0
        """Real per-day count of genuine LLM cognition calls (the
        `_run_cognition` dispatch point, not the deterministic-fallback
        path) — one of `WORKLOAD_FORECAST_SCHEMA`'s own named input
        features, reset daily by `_maybe_tick_workload_forecaster`."""
        self._dialogue_calls_today = 0
        """Same real per-day counting as `_cognition_calls_today`, for
        `_run_dialogue`/`_run_voice_dialogue`'s dispatch points."""
        self._workload_pending_samples: list = []
        """In-flight (sampled, not yet resolved) `(tick, features,
        predicted, calls_attempted_snapshot)` tuples — resolved into a
        real training example once `WORKLOAD_SAMPLE_HORIZON_DAYS` has
        genuinely elapsed, bounded at `WORKLOAD_PENDING_SAMPLES_MAX`."""
        self._workload_training_examples: list = []
        """Real `(features, observed_call_volume)` examples accumulated
        since the last retrain attempt, bounded at `WORKLOAD_TRAINING_
        EXAMPLES_MAX` (oldest evicted)."""
        self._workload_learn_log: deque[dict] = deque(maxlen=WORKLOAD_LEARN_LOG_MAX)
        """Bounded, append-only record of every real monthly retrain
        attempt (accepted or rejected) — dev-console-visible via `full_
        diagnostics()`."""

        # Tier 5 B7.2 + B8's real control points (explicit user
        # directive: "B8 and MachineProfile persistence and select_
        # strategy's output still have no real call site — flagged for
        # later"), same batch since B8's own docstring already names
        # them as naturally paired. `self._machine_profile` is loaded
        # once here (a real, host-fingerprinted, versioned JSON file
        # that survives a restart — B7.2's "gradually evolves... not
        # resets each time") and consulted by `_maybe_tune_llm_
        # concurrency` (below) via `select_strategy`; refined and saved
        # back to disk by `_maybe_refresh_machine_profile` (monthly).
        self._machine_profile_path = _machine_profile_path_for(config.db_path)
        self._machine_profile = _load_or_create_machine_profile(self._machine_profile_path)
        self._machine_profile.record_session()
        self._last_strategy = None
        # B8.4's real control point: a bounded history of daily
        # `CognitionRunner.backlog` readings, sampled unconditionally in
        # `_maybe_tune_llm_concurrency` regardless of whether that
        # method goes on to skip its own tuning check — the one real
        # signal `is_quiet_window` needs to judge whether now is a good
        # time for `_maybe_refresh_machine_profile`'s own real disk I/O
        # (the storage micro-benchmark) rather than running it blindly
        # every month regardless of load.
        self._recent_llm_backlog_samples: deque[float] = deque(maxlen=RECENT_LLM_BACKLOG_SAMPLES_MAX)

        # Tier 5 B15.3/B15.4's real control point (explicit user
        # instruction: "continue B and try closing it this turn"):
        # `EscalationLadder` observes the SAME `llm_pressure_ratio()`
        # reading `run_forever`'s own real-time pacing already acts on
        # (LLM_PRESSURE_SLOWDOWN_START_RATIO is the threshold both this
        # and that mechanism now agree "pressure" begins at) — but this
        # wiring never touches real-time tick pacing itself (CLAUDE.md's
        # "Preserve absolutely" names that mechanism explicitly). It
        # only feeds `cognition_budget_for_rung` into `_schedule_due_
        # cognition`'s own per-tick LLM-call gate (see there) — a
        # genuinely additive, narrower control point. `reference_mode`
        # stays False (a live deployment, not a HearthBench reference
        # run) — B15.5's pin is real future work once HearthBench's own
        # runner exists to request one.
        self._escalation_ladder = EscalationLadder()
        self._cognition_budget = CognitionBudget(count=ESCALATION_COGNITION_BASE_BUDGET)

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
        self._occupation_shortage_flagged: "set[tuple[int, str]]" = set()
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Design a new producer"): (settlement_id,
        occupation) pairs currently flagged short — edge-triggered,
        same shape as `_materials_critical_flagged`. Backs `_detect_
        occupation_shortage`, Village pillar's fourth category-keyed
        `world_model` producer (after dispute_feud/theft/materials_
        bottleneck), this one keyed by a literal `occupations.py`
        occupation string rather than a fixed pattern-signal label.
        Never persisted — same re-baseline-on-restart reasoning as
        every other edge-trigger flag here."""
        self._housing_shortage_flagged: "set[int]" = set()
        """Tier 0, new producer: settlement ids currently flagged
        overcrowded — edge-triggered, same shape as `_occupation_
        shortage_flagged`. Backs `_detect_housing_shortage`, Village
        pillar's fifth category-keyed `world_model` subject (literal
        `"housing_shortage"`), reusing `Population._housing_pressure`
        (already computed for `_maybe_migrate`'s disaster-refugee push
        signal, §2 "refugees after disasters") rather than duplicating
        the capacity/population math. Never persisted — same re-
        baseline-on-restart reasoning as every other edge-trigger flag
        here."""
        self._food_shortage_flagged: "set[int]" = set()
        """Tier 0, new producer: settlement ids currently flagged food-
        short — edge-triggered, same shape as `_housing_shortage_
        flagged`. Backs `_detect_food_shortage`, Village pillar's
        sixth category-keyed `world_model` subject (literal `"food_
        shortage"`), reusing `Population._granary_fill_ratio` (already
        computed for `_maybe_migrate`'s hunger-driven pull signal) and
        `world.reactions.FOOD_SHORTAGE_FILL_THRESHOLD` (already the
        exact threshold `_maybe_tick_composite_reactions`' inline
        `food_shortage_now` check uses) rather than duplicating either.
        Never persisted — same re-baseline-on-restart reasoning as
        every other edge-trigger flag here."""
        self._currency_shortage_flagged: "set[int]" = set()
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Currency shortage producer"). Village
        pillar's eighth category-keyed `world_model` subject, same
        shape as `_detect_food_shortage` — backs `_detect_currency_
        shortage`, comparing `Settlement.currency` against `buildings.
        CURRENCY_SHORTAGE_THRESHOLD` (half of the existing `INVENTION_
        CURRENCY_THRESHOLD` "prosperous enough to invent" bar). Never
        persisted — same re-baseline-on-restart reasoning as every
        other edge-trigger flag here."""
        self._prosperity_flagged: "set[int]" = set()
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Settlement prosperity/surplus producer").
        Village pillar's ninth category-keyed `world_model` subject —
        the first POSITIVE category in this cluster (every prior one
        names a hardship). Backs `_detect_prosperity`: both `Settlement.
        materials`/`.currency` sustained past `buildings.PROSPERITY_
        MATERIALS_FRACTION`/`PROSPERITY_CURRENCY_FRACTION` at once.
        Never persisted — same re-baseline-on-restart reasoning as
        every other edge-trigger flag here."""
        self._council_gridlock_flagged: "set[int]" = set()
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "COUNCIL gridlock producer"). Village
        pillar's eleventh category-keyed `world_model` subject. Backs
        `_detect_council_gridlock`: a settlement's COUNCIL has living
        members, at least one belongs to a real `FACTION`, yet
        `Population.council_faction_majority` still reads `None` — a
        genuinely split, politically-contested council, not just an
        apolitical one (a council with no factional membership at all
        is NOT gridlock, it simply has no politics yet). Never
        persisted — same re-baseline-on-restart reasoning as every
        other edge-trigger flag here."""
        self._guild_decline_flagged: "set[int]" = set()
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "GUILD-level signal"). Village pillar's
        twelfth category-keyed `world_model` subject, a second
        institution-scoped one alongside `_detect_council_gridlock`.
        Backs `_detect_guild_decline`: a settlement's GUILD — whose
        `Institution.name` IS the skill it was founded around (see
        `Population._maybe_form_guild`) — has no living member left
        who still holds `GUILD_SKILL_MASTERY_THRESHOLD` in that same
        skill, i.e. the craft the guild was built around has genuinely
        died out among its own membership. Never persisted — same
        re-baseline-on-restart reasoning as every other edge-trigger
        flag here."""
        self._family_extinction_counted: "set[int]" = set()
        """Tier 0, new producer (explicit user decision: "FAMILY-level
        signal"). Village pillar's thirteenth category-keyed `world_
        model` subject, a THIRD institution-scoped one. Unlike its
        gridlock/decline siblings (level-based, can recover), a
        family dying out is a one-shot event with no "recovery" —
        this tracks FAMILY institution ids already counted extinct so
        `_detect_family_extinction` counts each line's death exactly
        once. Bounded, not a leak: intersected against every currently
        -present FAMILY institution id on each check, so an id falls
        out the moment `_prune_extinct_families` evicts that family,
        same cap `Settlement.institutions` itself already holds
        (`INSTITUTION_LIST_MAX_STORED`)."""
        self._diplomatic_hostility_flagged: "set[int]" = set()
        """Tier 0, new producer: Village pillar's fourteenth category-
        keyed `world_model` subject, back to a level-based/recoverable
        shape (like `prosperity`/`currency_shortage`), reusing the
        already-real `Settlement.relations` cross-settlement affinity
        state — no new tracked data. Backs `_detect_diplomatic_
        hostility`: any recorded relation with a sister settlement
        drops below `buildings.DIPLOMATIC_HOSTILITY_THRESHOLD`. Never
        persisted — same re-baseline-on-restart reasoning as every
        other edge-trigger flag here."""
        self._faction_rivalry_flagged: "set[int]" = set()
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Design a FACTION rivalry signal") — this
        session's first genuinely-new-mechanism producer, not a
        rewiring of already-existing state. Village pillar's fifteenth
        category-keyed `world_model` subject, a FOURTH institution-
        scoped one. Backs `_detect_faction_rivalry`: two FACTION
        institutions in the same settlement, each with at least
        `Population.FACTION_RIVALRY_MIN_MEMBERS` living members, whose
        average cross-membership relationship reads below `Population.
        FACTION_RIVALRY_THRESHOLD` — real sustained inter-faction
        hostility, not one soured pair (already covered by ordinary
        dispute detection). Never persisted — same re-baseline-on-
        restart reasoning as every other edge-trigger flag here."""
        self._grazer_abundance_flagged: "set[int]" = set()
        """C2 "Intention channel" (Mind -> Body, Tier 3), "domesticate"
        — Village pillar's sixteenth category-keyed `world_model`
        subject. Backs `_detect_grazer_abundance`: a settlement with a
        standing PASTURE that has a real wild GRAZER herd within
        `WILDLIFE_SEARCH_RADIUS` holding at least `DOMESTICATE_MIN_
        HERD_SIZE` animals — a genuine domestication candidate, Body-
        supplied. Never persisted — same re-baseline-on-restart
        reasoning as every other edge-trigger flag here."""
        self._hydrology_drought_flagged: bool = False
        """A11 (roadmap Stage IV step 15): edge-trigger flag for
        `_detect_hydrology_drought`, same "one observation on the
        falling edge, silent recovery on the rising edge" shape as
        `_materials_critical_flagged`. World-scoped (not per-
        settlement) since the moisture field is map-wide, not tied to
        settlement boundaries. Never persisted — same re-baseline-on-
        restart reasoning as every other edge-trigger flag here."""
        self._nature_predator_extinction_flagged: bool = False
        """Tier 0's scoped-then-shipped Nature causal-reasoning job
        (`_maybe_schedule_nature_causal_reasoning`): edge-trigger flag,
        same shape as `_hydrology_drought_flagged` — `predator_packs`
        crossing from >0 to 0 fires the reactive LLM job once on the
        falling edge; the rising edge (recolonization, `world.wildlife.
        maybe_recolonize`) silently clears the flag with no LLM call.
        World-scoped (one shared wildlife grid, not per-settlement).
        Never persisted — re-baselines from the first post-restart
        reading, same as every other edge-trigger flag here."""
        self._nature_grazer_extinction_flagged: bool = False
        """Second Nature causal-reasoning trigger: same shape as
        `_nature_predator_extinction_flagged`, applied to `world.
        wildlife.summary()["grazer_herds"]` crossing from >0 to 0
        instead of predator packs."""
        self._nature_succession_stall_flagged: bool = False
        """Third Nature causal-reasoning trigger: True once a currently-
        stalled, favorable-moisture fallow tile has already been
        reasoned about (see `NATURE_SUCCESSION_STALL_WEEKS_MULTIPLIER`/
        `_MOISTURE_MIN`); clears once no such tile remains (reclaimed,
        dropped from `World.fallow_ticks`, or its moisture/weeks no
        longer qualify). Never persisted, same reasoning as every other
        edge-trigger flag here."""
        self._reactive_trigger_next_retry_tick: dict[str, int] = {}
        """Backoff state for `_reactive_pillar_backpressured` — see its
        docstring. Keyed by a short trigger name (e.g. `"predator_
        extinction"`), never persisted (re-baselines to "eligible right
        now" on restart, same as every edge-trigger flag above; at worst
        this costs one redundant backpressure check on the first tick
        after a resume, not a correctness issue)."""
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
        self._institution_dormancy = DormancyManager()
        self._institution_fingerprint: dict[tuple[int, int], tuple] = {}
        self._institution_idle_checks: dict[tuple[int, int], int] = {}
        """Tier 5 B4.2 pilot ("idle institutions" — the one candidate
        picked via explicit `AskUserQuestion` from the item's own five
        named options). Real B4/`DormancyManager` migration, not a new
        parallel mechanism — `_update_institution_dormancy` (monthly)
        watches each (settlement_id, institution_id)'s own cheap
        fingerprint (member count, feud count, belief count, objective
        text); a fingerprint unchanged across `INSTITUTION_DORMANCY_
        IDLE_CHECKS_THRESHOLD` consecutive monthly checks puts it to
        sleep, any real change wakes it immediately. `_institution_job_
        target`'s existing round-robin then skips sleeping institutions,
        concentrating the quarterly `institution_culture` LLM call on
        institutions something has actually happened to.

        This is a genuine behavior change (which institution gets
        picked, and when) but a Constitution-compliant one: `docs/
        HEARTHBENCH-RUNTIME-2026-07-23.md`'s B15 `TWO_PART_GUARANTEE`
        requires the deterministic Body stay replay-identical regardless
        of any runtime/dormancy decision, while explicitly permitting
        cognition BREADTH to vary ("adaptive: cognition breadth may
        scale... never a degraded world"). `Institution.culture_digest`
        is pure Mind-layer narrative content, never read by anything
        Body-deterministic — dormancy here never touches simulated
        physics/economy/population, only which institution's own
        digest gets the next quarterly narration pass. All three dicts
        are runtime scheduling state, never persisted — same "derived,
        re-baselines cleanly on restart" discipline as `_prev_
        population_total`/`_materials_critical_flagged` above; losing
        idle-tracking progress on a restart just means a few institutions
        take a little longer to be recognized as idle again, never a
        correctness issue."""
        self._idea_dormancy = DormancyManager()
        self._idea_fingerprint: dict[int, tuple] = {}
        self._idea_idle_checks: dict[int, int] = {}
        """Tier 5 B4.2, second candidate ("unused ideas") — same real
        `DormancyManager` migration as `_idea_dormancy`'s institution
        sibling above, over `World.invented_concepts` instead. See
        `_update_idea_dormancy`/`_idea_fingerprint` (module-level
        helper) for the mechanism; `_maybe_spread_concepts`'s per-tick
        roll list excludes sleeping ideas the same way `_institution_
        job_target`'s round-robin excludes sleeping institutions —
        Mind-layer attention only, B15 `TWO_PART_GUARANTEE`-compliant
        for the identical reason the institutions pilot is."""
        self._tradition_dormancy = DormancyManager()
        self._tradition_fingerprint: dict[str, tuple] = {}
        self._tradition_idle_checks: dict[str, int] = {}
        """Tier 5 B4.2, third candidate ("forgotten traditions") — the
        same real `DormancyManager` shape as the institutions/ideas
        pilots above, over `(settlement, tradition)` pairs instead. See
        `_update_tradition_dormancy`/`_tradition_fingerprint` (module-
        level helper) for the mechanism; `_maybe_spread_tradition_
        keeping`'s per-settlement weighted tradition pick excludes a
        sleeping tradition the same way the two siblings above exclude
        their own sleeping entities. Compliant with B15's `TWO_PART_
        GUARANTEE` for the identical reason: a tradition existing (or
        not) is Body-deterministic `Settlement.traditions` state,
        UNTOUCHED by this dormancy — only which tradition gets the next
        personal-keeper-spread ROLL (pure Mind-layer attention) is
        gated. All three dicts are runtime scheduling state, never
        persisted — same restart-safe discipline as the two siblings."""
        self._settlement_dormancy = DormancyManager()
        self._settlement_fingerprint: dict[int, tuple] = {}
        self._settlement_idle_checks: dict[int, int] = {}
        """Tier 5 B4.2, fourth candidate ("inactive settlements") — same
        real `DormancyManager` shape as the three siblings above, over
        named `World.settlements` instead. See `_update_settlement_
        dormancy`/`_settlement_fingerprint` (module-level helper) for
        the mechanism; `_job_target`'s existing month-indexed round-
        robin excludes sleeping settlements the same way `_institution_
        job_target`/`_maybe_spread_concepts`/`_maybe_spread_tradition_
        keeping` exclude their own sleeping entities. Compliant with
        B15's `TWO_PART_GUARANTEE` for the identical reason: a
        settlement's own Body-deterministic ticking (`Population.
        tick()`, `WildlifeGrid.tick()`) is completely untouched by this
        dormancy — only which settlement gets this month's Mind-layer
        narrative attention is gated. Runtime scheduling state, never
        persisted — same restart-safe discipline as the three
        siblings."""
        self._emergence_compression = CompressionLadder()
        """Tier 5 B12's first real consumer: routes `World.emergence_
        log`'s own evicted-past-cap entries through a real
        `CompressionLadder` (see `_append_emergence`) instead of plain
        truncation — a batch of evicted raw observations condenses into
        one archived digest (`_condense_emergence_entries`) once
        `EMERGENCE_COMPRESSION_RAW_THRESHOLD` accumulates, bounded
        overall by `EMERGENCE_COMPRESSION_ARCHIVE_MAX`. Deliberately
        runtime-only, never persisted — same "derived, re-baselines on
        restart" discipline as the four `DormancyManager` instances
        above; a restarted world simply starts accumulating a fresh
        archive rather than losing anything the live `emergence_log`
        window itself still holds (the archive is compressed HISTORY
        beyond that window, not a substitute for it)."""
        self._emergence_surprise = SurpriseSpecialist()
        """Tier 7 HCA Stage A, A2: the real gate `_append_emergence`
        scores every candidate observation through before deciding
        whether it reaches `World.emergence_log` at all — see
        `EMERGENCE_SURPRISE_THRESHOLD`'s own docstring for the full
        rationale. Runtime-only, never persisted, same "derived,
        re-baselines on restart" discipline as `_emergence_compression`
        above — a restarted world simply starts re-learning what's
        routine from scratch rather than needing durable per-key
        statistics across restarts."""
        self._emergence_surprise_attempted_total = 0
        self._emergence_surprise_suppressed_total = 0
        """A2's own dev-console-visible proof the gate is real, not just
        present — every `_append_emergence` call increments `attempted`;
        one suppressed by `EMERGENCE_SURPRISE_THRESHOLD` also increments
        `suppressed`, surfaced via `full_diagnostics()['emergence_
        surprise']`. Runtime-only counters, same depth as `_last_llm_
        calls`/`_rumor_retellings_recent` below — not persisted."""
        self._rumor_retellings_recent: list[dict] = []
        """A17's fitness-vs-truth axis (`world.memetics.rumor_fitness`/
        `rumor_truth_score`) — a small capped, transient (not persisted,
        same treatment `_last_llm_calls` gets) diagnostic ring so the
        mechanism is observable: each entry is `{reteller, subject,
        fitness, truth_score, tick}`. Dev-console/`full_diagnostics()`
        depth only — not Phase G's ambiguity discipline (this is an
        internal propagation mechanic, not a supernatural reading), just
        the same internal-numeric-diagnostic depth `self_tuning_actions_
        recent` gets."""
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

        # B0.3's first real migration (Tier 5 Part B): `_maybe_schedule_
        # naming` runs through a genuine B1 TaskRegistry + B2 Scheduler
        # instead of a direct method call — the actual "gameplay
        # declares WHAT, the runtime decides WHEN/HOW" invariant (B0)
        # applied to one real schedule point rather than left as
        # infrastructure nothing consumes. Chosen as the first pilot
        # because it's small, self-contained (no cross-job read/write
        # coupling to get wrong), and already unconditional every tick
        # — CRITICAL priority + PERIODIC trigger reproduces that exact
        # "always runs" behavior through the scheduler rather than
        # risking a real behavior change (a lower priority class could
        # let budget pressure defer it, which the original code never
        # did). `reads`/`writes` are declared honestly for when a
        # second migrated task might one day need to conflict-check
        # against this one — irrelevant to correctness with only one
        # task registered, but the point of doing it now rather than
        # `Task.legacy(...)` is proving the real declaration shape
        # works, not just the shim. See `_tick_once`'s own call site
        # for how a `_TICK_JOBS` entry can now be runtime-scheduled
        # instead of directly invoked while keeping its exact ordering
        # slot in the table.
        # Each migrated job gets its OWN registry+scheduler pair rather
        # than sharing one — deliberately, not an oversight. A shared
        # registry's `topological_order()` picks a single, fixed
        # relative order between ALL of its tasks (lexicographic
        # tiebreak, since these two share no real read/write overlap),
        # and `_tick_once`'s loop would call `run_tick()` once per
        # `_RUNTIME_SCHEDULED_JOB_NAMES` slot it hits in `_TICK_JOBS` —
        # with one shared registry, EVERY task in it would run again at
        # EACH slot, silently double-executing every migrated job the
        # moment a second one exists. Per-job registries make each
        # `_TICK_JOBS` slot's `run_tick()` call run exactly the one task
        # that belongs there, preserving the table's own declared order
        # exactly, with zero cross-job coupling to reason about as more
        # jobs migrate.
        self._runtime_registry = TaskRegistry()
        self._runtime_registry.register(Task(
            id="naming",
            subsystem="naming",
            fn=self._maybe_schedule_naming,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.newly_named_settlement_ids"}),
            writes=frozenset({"engine.naming_scheduled_ids"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler = Scheduler(self._runtime_registry)

        # Second B0.3 migration: `_maybe_retry_mind_authoring` — same
        # pilot criteria as naming (small, self-contained, already
        # unconditional every tick). Also CRITICAL+PERIODIC: the
        # original direct call always ran every tick regardless of
        # budget (its own internal backpressure/queue gate is a
        # DIFFERENT mechanism from the scheduler's budget system), so
        # anything less than CRITICAL priority could let the scheduler
        # defer a tick the direct call never would have.
        self._runtime_registry_mind_authoring = TaskRegistry()
        self._runtime_registry_mind_authoring.register(Task(
            id="retry_mind_authoring",
            subsystem="mind_authoring",
            fn=self._maybe_retry_mind_authoring,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"engine.pending_mind_agent_ids", "world.population.core_agent_ids"}),
            writes=frozenset({"engine.pending_mind_agent_ids"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_mind_authoring = Scheduler(self._runtime_registry_mind_authoring)

        # Third B0.3 migration: `_maybe_tick_trigger_state_edges` — same
        # pilot criteria (small, self-contained, already unconditional
        # every tick, CRITICAL+PERIODIC so the scheduler can't defer a
        # tick the direct call never would have). Real writes go
        # through unchanged: `_apply_trigger_rules_for` still mutates
        # real World/settlement state exactly as before, this only
        # changes HOW the method itself gets invoked each tick.
        self._runtime_registry_trigger_edges = TaskRegistry()
        self._runtime_registry_trigger_edges.register(Task(
            id="trigger_state_edges",
            subsystem="trigger_state_edges",
            fn=self._maybe_tick_trigger_state_edges,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({
                "world.trigger_rules", "world.disasters.heat_pressure", "world.settlements",
            }),
            writes=frozenset({"engine.prev_drought_state", "engine.prev_surplus_state"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_trigger_edges = Scheduler(self._runtime_registry_trigger_edges)

        # Explicit user directive: stop migrating one job at a time —
        # do as many real _JOB_NO_ARGS schedule points as possible in
        # one batch, asking only when genuinely stuck. Every remaining
        # `_TICK_JOBS` entry whose method takes zero arguments (the
        # `_JOB_EVENTS`/`_JOB_EVENTS_SEASON` jobs need `events`/
        # `previous_season` passed in fresh each tick, which `Task.fn`'s
        # zero-arg declared-once shape can't express without a design
        # change — out of scope for this batch, flagged below) gets its
        # own dedicated registry+scheduler pair, same CRITICAL+PERIODIC
        # shape as the first three migrations.
        self._runtime_registry_spread_concepts = TaskRegistry()
        self._runtime_registry_spread_concepts.register(Task(
            id="spread_concepts",
            subsystem="spread_concepts",
            fn=self._maybe_spread_concepts,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.invented_concepts", "world.population.core_agent_ids"}),
            writes=frozenset({"world.invented_concepts"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_spread_concepts = Scheduler(self._runtime_registry_spread_concepts)

        self._runtime_registry_spread_tradition_keeping = TaskRegistry()
        self._runtime_registry_spread_tradition_keeping.register(Task(
            id="spread_tradition_keeping",
            subsystem="spread_tradition_keeping",
            fn=self._maybe_spread_tradition_keeping,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements.traditions", "world.village_pillar"}),
            writes=frozenset({"agent.kept_traditions"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_spread_tradition_keeping = Scheduler(
            self._runtime_registry_spread_tradition_keeping,
        )

        self._runtime_registry_trigger_rules_life_events = TaskRegistry()
        self._runtime_registry_trigger_rules_life_events.register(Task(
            id="trigger_rules_life_events",
            subsystem="trigger_rules_life_events",
            fn=self._apply_trigger_rules_from_life_events,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.trigger_rules", "world.last_life_events"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_trigger_rules_life_events = Scheduler(
            self._runtime_registry_trigger_rules_life_events,
        )

        self._runtime_registry_composite_reactions = TaskRegistry()
        self._runtime_registry_composite_reactions.register(Task(
            id="composite_reactions",
            subsystem="composite_reactions",
            fn=self._maybe_tick_composite_reactions,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements", "world.disasters.heat_pressure"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_composite_reactions = Scheduler(self._runtime_registry_composite_reactions)

        self._runtime_registry_record = TaskRegistry()
        self._runtime_registry_record.register(Task(
            id="record",
            subsystem="record",
            fn=self._maybe_schedule_record,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.population.last_written_records"}),
            writes=frozenset({"world.settlements.records"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_record = Scheduler(self._runtime_registry_record)

        self._runtime_registry_dispute = TaskRegistry()
        self._runtime_registry_dispute.register(Task(
            id="dispute",
            subsystem="dispute",
            fn=self._maybe_schedule_dispute,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.population.agents", "world.humans_pillar"}),
            writes=frozenset({"agent.relationships"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_dispute = Scheduler(self._runtime_registry_dispute)

        self._runtime_registry_migration_decision = TaskRegistry()
        self._runtime_registry_migration_decision.register(Task(
            id="migration_decision",
            subsystem="migration_decision",
            fn=self._maybe_schedule_migration_decision,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.population.core_agent_ids", "world.humans_pillar"}),
            writes=frozenset({"world.population.agents"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_migration_decision = Scheduler(self._runtime_registry_migration_decision)

        self._runtime_registry_due_cognition = TaskRegistry()
        self._runtime_registry_due_cognition.register(Task(
            id="due_cognition",
            subsystem="due_cognition",
            fn=self._schedule_due_cognition,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.population.agents"}),
            writes=frozenset({"engine.pending_cognition_results"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_due_cognition = Scheduler(self._runtime_registry_due_cognition)

        self._runtime_registry_due_dialogue = TaskRegistry()
        self._runtime_registry_due_dialogue.register(Task(
            id="due_dialogue",
            subsystem="due_dialogue",
            fn=self._schedule_due_dialogue,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.population.agents"}),
            writes=frozenset({"engine.pending_dialogue_results"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_due_dialogue = Scheduler(self._runtime_registry_due_dialogue)

        self._runtime_registry_voice_dialogue = TaskRegistry()
        self._runtime_registry_voice_dialogue.register(Task(
            id="voice_dialogue",
            subsystem="voice_dialogue",
            fn=self._schedule_voice_dialogue,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.population.voice_pair_ids"}),
            writes=frozenset({"engine.pending_dialogue_results"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_voice_dialogue = Scheduler(self._runtime_registry_voice_dialogue)

        # Tier 5 B2's real control point (explicit user directive: "wire
        # B2 to a real control point" — see `BROADCAST_SUBSYSTEM_BUDGET_
        # SECONDS`'s own docstring for the full design writeup, including
        # what this wiring does and does NOT actually exercise, verified
        # not assumed). Deliberately NOT a `_TICK_JOBS` entry/`_RUNTIME_
        # SCHEDULED_JOB_SCHEDULERS` member — `_maybe_broadcast` has a
        # SECOND call site (the real-time `run_forever` llama-server-
        # restart-edge polling loop, outside `_tick_once` entirely) that
        # must stay a direct call, so this gets its own explicit call
        # site below rather than going through the generic per-tick
        # dispatch table built for `_TICK_JOBS` alone. DEFERRABLE (not
        # CRITICAL, unlike every B0.3 migration) — a lagged broadcast is
        # genuinely harmless, the client just gets the next available
        # frame; nothing here touches deterministic `World` state.
        self._runtime_registry_broadcast = TaskRegistry()
        self._runtime_registry_broadcast.register(Task(
            id="broadcast",
            subsystem="broadcast",
            fn=self._maybe_broadcast,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.summary", "world.population.agents", "world.settlements.buildings"}),
            writes=frozenset({"engine.broadcaster.last_payload"}),
            timescale="tick",
            priority_class=PriorityClass.DEFERRABLE,
        ))
        self._runtime_scheduler_broadcast = Scheduler(
            self._runtime_registry_broadcast,
            budgets={"broadcast": SubsystemBudget(
                subsystem="broadcast", seconds_per_tick=BROADCAST_SUBSYSTEM_BUDGET_SECONDS,
            )},
        )

        # Explicit user directive, same batch: the "blocker" flagged
        # after the first batch (`_JOB_EVENTS`/`_JOB_EVENTS_SEASON`
        # jobs need `events`/`previous_season` passed in fresh each
        # tick) turned out not to be real — `Scheduler.run_tick(*args,
        # **kwargs)` already forwards positional args straight to
        # `task.fn(*args, **kwargs)`, and since each migrated job gets
        # its own dedicated single-task registry, calling `run_tick
        # (events)`/`run_tick(events, previous_season)` at the real
        # `_tick_once` call site (below) reproduces the exact prior
        # `method(events)`/`method(events, previous_season)` call
        # shape with no `Task`/`Scheduler` change needed at all. Every
        # remaining `_TICK_JOBS` entry migrated in this same batch.
        # `reads`/`writes` are declared coarsely (`world.settlements`)
        # for all of these — real documentation, but not load-bearing:
        # each job holds its own isolated single-task registry, so no
        # actual conflict/reordering decision depends on precision
        # here, unlike a registry holding multiple tasks.
        self._runtime_registry_chronicle = TaskRegistry()
        self._runtime_registry_chronicle.register(Task(
            id="chronicle",
            subsystem="chronicle",
            fn=self._maybe_schedule_chronicle,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_chronicle = Scheduler(self._runtime_registry_chronicle)

        self._runtime_registry_documentary = TaskRegistry()
        self._runtime_registry_documentary.register(Task(
            id="documentary",
            subsystem="documentary",
            fn=self._maybe_schedule_documentary,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_documentary = Scheduler(self._runtime_registry_documentary)

        self._runtime_registry_tradition = TaskRegistry()
        self._runtime_registry_tradition.register(Task(
            id="tradition",
            subsystem="tradition",
            fn=self._maybe_schedule_tradition,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_tradition = Scheduler(self._runtime_registry_tradition)

        self._runtime_registry_folklore = TaskRegistry()
        self._runtime_registry_folklore.register(Task(
            id="folklore",
            subsystem="folklore",
            fn=self._maybe_schedule_folklore,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_folklore = Scheduler(self._runtime_registry_folklore)

        self._runtime_registry_legend_detection = TaskRegistry()
        self._runtime_registry_legend_detection.register(Task(
            id="legend_detection",
            subsystem="legend_detection",
            fn=self._maybe_schedule_legend_detection,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_legend_detection = Scheduler(self._runtime_registry_legend_detection)

        self._runtime_registry_invention = TaskRegistry()
        self._runtime_registry_invention.register(Task(
            id="invention",
            subsystem="invention",
            fn=self._maybe_schedule_invention,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_invention = Scheduler(self._runtime_registry_invention)

        self._runtime_registry_ontology_proposal = TaskRegistry()
        self._runtime_registry_ontology_proposal.register(Task(
            id="ontology_proposal",
            subsystem="ontology_proposal",
            fn=self._maybe_schedule_ontology_proposal,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_ontology_proposal = Scheduler(self._runtime_registry_ontology_proposal)

        self._runtime_registry_ontology_evolution = TaskRegistry()
        self._runtime_registry_ontology_evolution.register(Task(
            id="ontology_evolution",
            subsystem="ontology_evolution",
            fn=self._maybe_schedule_ontology_evolution,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_ontology_evolution = Scheduler(self._runtime_registry_ontology_evolution)

        self._runtime_registry_composite_entity = TaskRegistry()
        self._runtime_registry_composite_entity.register(Task(
            id="composite_entity",
            subsystem="composite_entity",
            fn=self._maybe_schedule_composite_entity,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_composite_entity = Scheduler(self._runtime_registry_composite_entity)

        self._runtime_registry_nature_mind = TaskRegistry()
        self._runtime_registry_nature_mind.register(Task(
            id="nature_mind",
            subsystem="nature_mind",
            fn=self._maybe_schedule_nature_mind,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_nature_mind = Scheduler(self._runtime_registry_nature_mind)

        self._runtime_registry_species_variant = TaskRegistry()
        self._runtime_registry_species_variant.register(Task(
            id="species_variant",
            subsystem="species_variant",
            fn=self._maybe_schedule_species_variant,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_species_variant = Scheduler(self._runtime_registry_species_variant)

        self._runtime_registry_rule_proposal = TaskRegistry()
        self._runtime_registry_rule_proposal.register(Task(
            id="rule_proposal",
            subsystem="rule_proposal",
            fn=self._maybe_schedule_rule_proposal,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_rule_proposal = Scheduler(self._runtime_registry_rule_proposal)

        self._runtime_registry_composite_reaction_propose = TaskRegistry()
        self._runtime_registry_composite_reaction_propose.register(Task(
            id="composite_reaction_propose",
            subsystem="composite_reaction_propose",
            fn=self._maybe_schedule_composite_reaction_propose,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_composite_reaction_propose = Scheduler(self._runtime_registry_composite_reaction_propose)

        self._runtime_registry_festival = TaskRegistry()
        self._runtime_registry_festival.register(Task(
            id="festival",
            subsystem="festival",
            fn=self._maybe_schedule_festival,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_festival = Scheduler(self._runtime_registry_festival)

        self._runtime_registry_religion = TaskRegistry()
        self._runtime_registry_religion.register(Task(
            id="religion",
            subsystem="religion",
            fn=self._maybe_schedule_religion,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_religion = Scheduler(self._runtime_registry_religion)

        self._runtime_registry_narrative_direction = TaskRegistry()
        self._runtime_registry_narrative_direction.register(Task(
            id="narrative_direction",
            subsystem="narrative_direction",
            fn=self._maybe_schedule_narrative_direction,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_narrative_direction = Scheduler(self._runtime_registry_narrative_direction)

        self._runtime_registry_culture_digest = TaskRegistry()
        self._runtime_registry_culture_digest.register(Task(
            id="culture_digest",
            subsystem="culture_digest",
            fn=self._maybe_schedule_culture_digest,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_culture_digest = Scheduler(self._runtime_registry_culture_digest)

        self._runtime_registry_consciousness = TaskRegistry()
        self._runtime_registry_consciousness.register(Task(
            id="consciousness",
            subsystem="consciousness",
            fn=self._maybe_schedule_consciousness,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_consciousness = Scheduler(self._runtime_registry_consciousness)

        self._runtime_registry_reflection = TaskRegistry()
        self._runtime_registry_reflection.register(Task(
            id="reflection",
            subsystem="reflection",
            fn=self._maybe_schedule_reflection,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_reflection = Scheduler(self._runtime_registry_reflection)

        self._runtime_registry_self_tuning = TaskRegistry()
        self._runtime_registry_self_tuning.register(Task(
            id="self_tuning",
            subsystem="self_tuning",
            fn=self._maybe_schedule_self_tuning,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_self_tuning = Scheduler(self._runtime_registry_self_tuning)

        self._runtime_registry_musing = TaskRegistry()
        self._runtime_registry_musing.register(Task(
            id="musing",
            subsystem="musing",
            fn=self._maybe_schedule_musing,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_musing = Scheduler(self._runtime_registry_musing)

        self._runtime_registry_caravan = TaskRegistry()
        self._runtime_registry_caravan.register(Task(
            id="caravan",
            subsystem="caravan",
            fn=self._maybe_schedule_caravan,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_caravan = Scheduler(self._runtime_registry_caravan)

        self._runtime_registry_town_brain = TaskRegistry()
        self._runtime_registry_town_brain.register(Task(
            id="town_brain",
            subsystem="town_brain",
            fn=self._maybe_schedule_town_brain,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_town_brain = Scheduler(self._runtime_registry_town_brain)

        self._runtime_registry_beliefs = TaskRegistry()
        self._runtime_registry_beliefs.register(Task(
            id="beliefs",
            subsystem="beliefs",
            fn=self._maybe_schedule_beliefs,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_beliefs = Scheduler(self._runtime_registry_beliefs)

        self._runtime_registry_personal_belief = TaskRegistry()
        self._runtime_registry_personal_belief.register(Task(
            id="personal_belief",
            subsystem="personal_belief",
            fn=self._maybe_schedule_personal_belief,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_personal_belief = Scheduler(self._runtime_registry_personal_belief)

        self._runtime_registry_dream = TaskRegistry()
        self._runtime_registry_dream.register(Task(
            id="dream",
            subsystem="dream",
            fn=self._maybe_schedule_dream,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_dream = Scheduler(self._runtime_registry_dream)

        self._runtime_registry_memory_drift = TaskRegistry()
        self._runtime_registry_memory_drift.register(Task(
            id="memory_drift",
            subsystem="memory_drift",
            fn=self._maybe_schedule_memory_drift,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_memory_drift = Scheduler(self._runtime_registry_memory_drift)

        self._runtime_registry_temperament = TaskRegistry()
        self._runtime_registry_temperament.register(Task(
            id="temperament",
            subsystem="temperament",
            fn=self._maybe_tick_temperament,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_temperament = Scheduler(self._runtime_registry_temperament)

        self._runtime_registry_omen = TaskRegistry()
        self._runtime_registry_omen.register(Task(
            id="omen",
            subsystem="omen",
            fn=self._maybe_schedule_omen,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_omen = Scheduler(self._runtime_registry_omen)

        self._runtime_registry_market_prices = TaskRegistry()
        self._runtime_registry_market_prices.register(Task(
            id="market_prices",
            subsystem="market_prices",
            fn=self._maybe_tick_market_prices,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_market_prices = Scheduler(self._runtime_registry_market_prices)

        self._runtime_registry_settlement_trade = TaskRegistry()
        self._runtime_registry_settlement_trade.register(Task(
            id="settlement_trade",
            subsystem="settlement_trade",
            fn=self._maybe_tick_settlement_trade,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_settlement_trade = Scheduler(self._runtime_registry_settlement_trade)

        self._runtime_registry_pillar_initiates_contact = TaskRegistry()
        self._runtime_registry_pillar_initiates_contact.register(Task(
            id="pillar_initiates_contact",
            subsystem="pillar_initiates_contact",
            fn=self._maybe_pillar_initiates_contact,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_pillar_initiates_contact = Scheduler(self._runtime_registry_pillar_initiates_contact)

        self._runtime_registry_guild_founding = TaskRegistry()
        self._runtime_registry_guild_founding.register(Task(
            id="guild_founding",
            subsystem="guild_founding",
            fn=self._maybe_schedule_guild_founding,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_guild_founding = Scheduler(self._runtime_registry_guild_founding)

        self._runtime_registry_faction = TaskRegistry()
        self._runtime_registry_faction.register(Task(
            id="faction",
            subsystem="faction",
            fn=self._maybe_schedule_faction,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_faction = Scheduler(self._runtime_registry_faction)

        self._runtime_registry_institution_belief = TaskRegistry()
        self._runtime_registry_institution_belief.register(Task(
            id="institution_belief",
            subsystem="institution_belief",
            fn=self._maybe_schedule_institution_belief,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_institution_belief = Scheduler(self._runtime_registry_institution_belief)

        self._runtime_registry_geography = TaskRegistry()
        self._runtime_registry_geography.register(Task(
            id="geography",
            subsystem="geography",
            fn=self._maybe_schedule_geography,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_geography = Scheduler(self._runtime_registry_geography)

        self._runtime_registry_fission = TaskRegistry()
        self._runtime_registry_fission.register(Task(
            id="fission",
            subsystem="fission",
            fn=self._maybe_schedule_fission,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_fission = Scheduler(self._runtime_registry_fission)

        self._runtime_registry_diplomacy = TaskRegistry()
        self._runtime_registry_diplomacy.register(Task(
            id="diplomacy",
            subsystem="diplomacy",
            fn=self._maybe_schedule_diplomacy,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_diplomacy = Scheduler(self._runtime_registry_diplomacy)

        self._runtime_registry_laws = TaskRegistry()
        self._runtime_registry_laws.register(Task(
            id="laws",
            subsystem="laws",
            fn=self._maybe_schedule_laws,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_laws = Scheduler(self._runtime_registry_laws)

        self._runtime_registry_noncore_nudge = TaskRegistry()
        self._runtime_registry_noncore_nudge.register(Task(
            id="noncore_nudge",
            subsystem="noncore_nudge",
            fn=self._maybe_schedule_noncore_nudge,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_noncore_nudge = Scheduler(self._runtime_registry_noncore_nudge)

        self._runtime_registry_letter = TaskRegistry()
        self._runtime_registry_letter.register(Task(
            id="letter",
            subsystem="letter",
            fn=self._maybe_schedule_letter,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_letter = Scheduler(self._runtime_registry_letter)

        # Tier 5 B3's real control point (explicit user directive: "B3").
        # `_update_institution_dormancy`'s own pre-migration body was
        # ALREADY a pure `if "month_end" not in events: return` guard
        # with no other logic ahead of it — exactly B3.2's own named
        # shape (a discrete "did this happen" signal, not an ongoing
        # state needing edge detection like B3's trigger-edges job).
        # Declaring it `ON_EVENT` instead of `PERIODIC` moves that guard
        # OUT of the function body and INTO the scheduler's own B3.1/
        # B3.2 due-check (`_due_and_reason`) — the real, structural
        # "skipped_clean, never touches budget/deferral machinery"
        # CPU win B3.1's own text names, rather than the function still
        # being called every tick only to immediately return. `events`
        # no longer needs to be threaded into the function itself (the
        # scheduler's own `EventBus.pending()` is now the source of
        # truth for whether this tick is a real month_end) — see the
        # real per-tick publish call in `_tick_once`, right after
        # `events` is computed.
        self._runtime_registry_institution_dormancy = TaskRegistry()
        self._runtime_registry_institution_dormancy.register(Task(
            id="institution_dormancy",
            subsystem="institution_dormancy",
            fn=self._update_institution_dormancy,
            trigger=TriggerKind.ON_EVENT,
            event_types=frozenset({"month_end"}),
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_institution_dormancy = Scheduler(self._runtime_registry_institution_dormancy)

        # Tier 5 B4.2, second dormancy candidate ("unused ideas") — same
        # real ON_EVENT/month_end shape as institution_dormancy directly
        # above, over `World.invented_concepts` instead of institutions.
        self._runtime_registry_idea_dormancy = TaskRegistry()
        self._runtime_registry_idea_dormancy.register(Task(
            id="idea_dormancy",
            subsystem="idea_dormancy",
            fn=self._update_idea_dormancy,
            trigger=TriggerKind.ON_EVENT,
            event_types=frozenset({"month_end"}),
            reads=frozenset({"world.invented_concepts"}),
            writes=frozenset({"world.invented_concepts"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_idea_dormancy = Scheduler(self._runtime_registry_idea_dormancy)

        # Tier 5 B4.2, third dormancy candidate ("forgotten traditions")
        # — same real ON_EVENT/month_end shape as the two siblings
        # above, over (settlement, tradition) pairs instead.
        self._runtime_registry_tradition_dormancy = TaskRegistry()
        self._runtime_registry_tradition_dormancy.register(Task(
            id="tradition_dormancy",
            subsystem="tradition_dormancy",
            fn=self._update_tradition_dormancy,
            trigger=TriggerKind.ON_EVENT,
            event_types=frozenset({"month_end"}),
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_tradition_dormancy = Scheduler(self._runtime_registry_tradition_dormancy)

        # Tier 5 B4.2, fourth dormancy candidate ("inactive settlements")
        # — same real ON_EVENT/month_end shape as the three siblings
        # above, over named `World.settlements` themselves instead.
        self._runtime_registry_settlement_dormancy = TaskRegistry()
        self._runtime_registry_settlement_dormancy.register(Task(
            id="settlement_dormancy",
            subsystem="settlement_dormancy",
            fn=self._update_settlement_dormancy,
            trigger=TriggerKind.ON_EVENT,
            event_types=frozenset({"month_end"}),
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_settlement_dormancy = Scheduler(self._runtime_registry_settlement_dormancy)

        self._runtime_registry_institution_culture = TaskRegistry()
        self._runtime_registry_institution_culture.register(Task(
            id="institution_culture",
            subsystem="institution_culture",
            fn=self._maybe_schedule_institution_culture,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset({"world.settlements"}),
            writes=frozenset({"world.settlements"}),
            timescale="tick",
            priority_class=PriorityClass.CRITICAL,
        ))
        self._runtime_scheduler_institution_culture = Scheduler(self._runtime_registry_institution_culture)


        if self._broadcaster is not None:
            # Terrain never changes after creation — set once, not part
            # of the per-tick payload. See docs/DECISIONS.md, F2.
            self._broadcaster.set_terrain(
                world.terrain, world.config.width, world.config.height,
                mining_scars=world.mining_scars, disaster_scars=world.disaster_scars,
                ritual_activity=world.ritual_activity, ruin_scars=world.ruin_scars,
                moisture=world.hydrology_field.moisture, soil_fertility=world.farms.soil_fertility,
                population_density=world.fields.ensure_field("population_density"),
                disease_pressure=world.fields.ensure_field("disease_pressure"),
                pollution=world.fields.ensure_field("pollution"),
                traffic=world.fields.ensure_field("traffic"),
                scarcity=world.fields.ensure_field("scarcity"),
                ownership=world.fields.ensure_field("ownership"),
                noise=world.fields.ensure_field("noise"),
                heat=world.fields.ensure_field("heat"),
                nutrients=world.fields.ensure_field("nutrients"),
                scent=world.fields.ensure_field("scent"),
                wildlife=world.fields.ensure_field("wildlife"),
                cultural_influence=world.fields.ensure_field("cultural_influence"),
                fertility=world.fields.ensure_field("fertility"),
                beauty=world.fields.ensure_field("beauty"),
                hazard=world.fields.ensure_field("hazard"),
                storminess=world.fields.ensure_field("storminess"),
                road_scars=world.road_scars,
                migration_trails=world.migration_trails,
                dry_lakebed_scars=world.dry_lakebed_scars,
                carcass_decomposition=world.carcass_decomposition,
                battle_scars=world.battle_scars,
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

    def _backpressure_pressure_band(self) -> str:
        """"healthy"/"elevated"/"severe" — the WHY behind `llm_
        backpressure_limit_effective`'s number, not just the number
        itself. A live diagnostic showed `llm_backpressure_limit_
        effective: 1` (== `llm_max_concurrent`, the adaptive floor)
        alongside `calls_dropped_backpressure` far exceeding `calls_
        attempted`; confirming that was `_current_backpressure_limit()`
        correctly tightening under severe measured p95 latency (not a
        scheduling bug) required cross-referencing `latency_ms_p95`
        against `ADAPTIVE_LATENCY_SEVERE_MS` by hand. Surfacing the band
        directly means a saturated-and-adaptively-throttled deployment
        reads as "severe" at a glance instead of requiring that lookup
        every time."""
        p95 = self._cognition_runner.stats()["latency_ms_p95"]
        if p95 >= ADAPTIVE_LATENCY_SEVERE_MS:
            return "severe"
        if p95 >= ADAPTIVE_LATENCY_ELEVATED_MS:
            return "elevated"
        return "healthy"

    def _maybe_tune_llm_concurrency(self) -> None:
        """Tier 5 B6 "adaptive tuning," wired to a real control point
        (explicit user directive, choosing this among several flagged
        Part B "not wired into any real control point" items): once a
        day, nudges the ACTUAL live LLM concurrency gate toward a
        target latency band, using the real `TunableRegistry`/
        `BangBangController` machinery (`simulation/tuning.py`) instead
        of a parallel ad-hoc formula.

        This replaces (for the day-to-day case) the "re-tune `llm_max_
        concurrent` by hand from a live `/diagnostics` reading" cycle
        CLAUDE.md's own long documented history shows this exact
        constant went through (4 -> 2 -> 1 -> 2 -> 1 -> 2 across many
        real deployments) — same real signal (measured p95 latency)
        driving a bounded, hysteresis-damped step instead of a person
        reading a dashboard and picking a new number. A human retune
        (CLI flag, live intervention) still always wins going forward —
        this only ever nudges from whatever the current live value is.

        Skipped entirely while the LLM is disabled (nothing to
        measure) or while the rolling latency window is too sparse to
        trust (`ADAPTIVE_CONCURRENCY_MIN_EVIDENCE`) — a controller
        that acts on 2 data points is worse than one that waits.
        `BangBangController.step`'s own hysteresis dead-zone is the
        rest of the anti-chatter discipline; combined with this
        method's own daily cadence and the registered `Tunable`'s
        bounded ±1 step, `llm_max_concurrent` can move by at most one
        notch per real day, never more.

        A genuine change resizes the REAL semaphore in-flight LLM
        calls run through (`CognitionRunner.resize_concurrency` ->
        `llm/jobs.py`'s `_ResizableSemaphore` — never yanks a permit
        already held by a running call) and keeps `_backpressure_
        limit` in step so admission math stays consistent with the
        live value, not the frozen startup one. Every real change is
        appended to `self._adaptive_tuning_log` — a no-op check is
        never logged, only what actually happened.

        Also Tier 5 B7's real control point: `self._hardware_citizen_
        policy.should_back_off` (a real `HostProbe.sample()` reading)
        is consulted every call this method doesn't skip, as a
        downward-only veto on top of the latency-driven decision above
        — real memory pressure/swap/load/thermal state can force a
        step down that latency alone wouldn't have taken, logged with
        `host_pressure_veto: True`.

        Also Tier 5 B7.3/B8.4's real control points (explicit user
        directive: "B8 and MachineProfile persistence and select_
        strategy's output still have no real call site — flagged for
        later"): `self._recent_llm_backlog_samples` gets one real
        `CognitionRunner.backlog` reading EVERY call, unconditionally
        (before either early-return below) — `is_quiet_window` (B8.4)
        needs this history regardless of whether tuning itself is
        skipped this call, and skipping the sample along with the
        tuning check would starve it exactly when the LLM is disabled
        or under-evidenced, the two cases where "load has stayed low"
        is most likely to be true and most useful to know. `select_
        strategy(probe, self._machine_profile)` (B7.3) supplies a
        SECOND downward-only cap on top of the host-pressure veto —
        this machine's own broad hardware category (cores/RAM) sets a
        ceiling B6's latency-driven step and B7.4's live-pressure veto
        can each still pull below, but neither can push above, logged
        with `strategy_cap_applied: True`."""
        self._recent_llm_backlog_samples.append(float(self._cognition_runner.backlog))
        if not self._cognition_runner.enabled:
            return
        stats = self._cognition_runner.stats()
        if stats["calls_attempted"] < ADAPTIVE_CONCURRENCY_MIN_EVIDENCE:
            return
        before = self._tuning_registry.get("llm_max_concurrent").value
        after = self._llm_concurrency_controller.step(self._tuning_registry, stats["latency_ms_p95"])
        # Tier 5 B7's real control point (explicit user directive: "B7"):
        # `GoodCitizenPolicy.should_back_off` is B7.4's own named input
        # signal, consulted here for the first time by a real scheduler
        # — B6's own daily concurrency controller, exactly the "real
        # scheduler" B7.4's docstring says this signal was always meant
        # to feed. Host pressure is a DOWNWARD-ONLY veto: it can force
        # a step down that latency alone wouldn't have taken, but it
        # never blocks or reverses a latency-driven step already
        # decided above — a struggling host and a struggling LLM are
        # two independent reasons to ease off, not one overriding the
        # other. Storage micro-benchmark skipped (`run_storage_bench=
        # False`) — irrelevant to `should_back_off` and needless disk
        # I/O on a check that already runs at most once a day.
        #
        # Sampled unconditionally (not only when a veto might apply) so
        # `full_diagnostics()['host_probe']` always has a fresh real
        # reading rather than a stale one from whichever day a veto last
        # fired — cheap "next tier intel," same batch: cost is a few
        # /proc reads and syscalls at most once a day, not a new
        # per-tick burden.
        probe = HostProbe.sample(run_storage_bench=False)
        back_off = self._hardware_citizen_policy.should_back_off(probe)
        self._last_host_probe = probe
        self._last_host_probe_back_off = back_off
        self._last_host_probe_tick = self.world.clock.tick_count
        host_pressure_veto = False
        if after >= before and back_off:
            vetoed = self._tuning_registry.adjust(
                "llm_max_concurrent", -self._tuning_registry.get("llm_max_concurrent").step,
            )
            if vetoed != after:
                after = vetoed
                host_pressure_veto = True
        # Tier 5 B7.3's real control point (explicit user directive:
        # "B8 and MachineProfile persistence and select_strategy's
        # output still have no real call site — flagged for later"):
        # `select_strategy` reads this SAME probe (never a second
        # sample) plus the persisted `MachineProfile` — a genuinely
        # different signal from `should_back_off`'s live pressure
        # reading, since it's a broad hardware-category ceiling
        # (cores/RAM), not a moment-to-moment one. Gated the same way
        # as the host-pressure veto just above (`after > before`, i.e.
        # only when a real INCREASE is already in progress): this
        # never forces down an already-stable value sitting above the
        # hint (a human retune or CLI override still always wins going
        # forward, per this method's own opening docstring — the same
        # promise the host-pressure veto already keeps), it only
        # prevents a fresh latency-driven climb from pushing PAST what
        # this machine's own broad hardware category supports.
        strategy = select_strategy(probe, self._machine_profile)
        self._last_strategy = strategy
        strategy_cap_applied = False
        if after > before and after > strategy.llm_max_concurrent_hint:
            capped = self._tuning_registry.set_value("llm_max_concurrent", strategy.llm_max_concurrent_hint)
            if capped != after:
                after = capped
                strategy_cap_applied = True
        if after == before:
            return
        new_limit = int(after)
        self._cognition_runner.resize_concurrency(new_limit)
        self._backpressure_limit = new_limit * BACKPRESSURE_BACKLOG_PER_SLOT
        self._adaptive_tuning_log.append({
            "tick": self.world.clock.tick_count,
            "tunable": "llm_max_concurrent",
            "before": before,
            "after": after,
            "measured_p95_ms": stats["latency_ms_p95"],
            "target_ms": ADAPTIVE_CONCURRENCY_TARGET_MS,
            "host_pressure_veto": host_pressure_veto,
            "strategy_cap_applied": strategy_cap_applied,
        })

    async def _probe_concurrency_wait_ms(
        self, concurrency: int, n_tasks: int = CONCURRENCY_PROBE_TASKS,
        hold_seconds: float = CONCURRENCY_PROBE_HOLD_SECONDS,
    ) -> float:
        """Tier 5 B13's real active-probe `measure_fn` primitive. Not a
        synthetic stand-in reading a fabricated number: builds a fresh,
        throwaway `_ResizableSemaphore(concurrency)` (the SAME class
        `CognitionRunner` itself uses to gate real LLM calls) and times
        how long `n_tasks` real asyncio tasks each holding it for
        `hold_seconds` genuinely take to all complete — a lower
        concurrency limit forces more serialization and measurably
        raises this real wall-clock number, a higher one lowers it.
        Deliberately drives its OWN throwaway semaphore instance rather
        than the live `self._cognition_runner`'s one — a hypothesis
        probe must never contend with real in-flight LLM calls for the
        real gate."""
        sem = _ResizableSemaphore(max(1, concurrency))

        async def _hold_once() -> None:
            async with sem:
                await asyncio.sleep(hold_seconds)

        start = time.perf_counter()
        await asyncio.gather(*(_hold_once() for _ in range(n_tasks)))
        return (time.perf_counter() - start) * 1000.0

    async def _run_llm_concurrency_hypothesis(
        self, proposed_value: int, hypothesis: str,
    ) -> AdaptationRecord:
        """Tier 5 B13's real first wiring for `llm_max_concurrent`
        (explicit user directive: "reverse the never-big-bang policy
        ... build whatever is required for blocked items"). Manually
        invoked only (see `self._llm_concurrency_hypothesis_loop`'s own
        docstring for why this is deliberately never scheduled
        automatically) — a caller (dev console / a future diagnostics
        action) supplies a candidate value and a free-text hypothesis;
        this runs the real B13.1 loop end to end.

        `HypothesisLoop.apply_and_measure`'s own `measure_fn` contract
        is synchronous (called twice, back-to-back, with no real time
        elapsing between the calls) — genuinely unable to host an
        AWAITED probe itself. Real measurements are taken here, BEFORE
        calling into the synchronous loop: `_probe_concurrency_wait_ms`
        is awaited once under the CURRENT value and once under the
        PROPOSED one, and `apply_and_measure` is handed a plain
        two-element lookup as its `measure_fn` — real work happens in
        this method, the B13.1 loop still owns the actual keep/rollback
        accounting and `AdaptationHistory` record, unmodified from its
        own already-verified (`verify_optimization_hypothesis.py`)
        synchronous API.

        `improved`/the SENSITIVE-gate decision are computed here too
        (duplicating `apply_and_measure`'s own internal `better_fn`
        check) so the expensive real equivalence probe below only ever
        runs when it would actually matter — B13.2's own "only after a
        genuine measured improvement" rule, honored a level up since
        the real check can't itself be awaited inside the synchronous
        loop."""
        before_value = int(self._tuning_registry.get("llm_max_concurrent").value)
        measured_before = await self._probe_concurrency_wait_ms(before_value)
        measured_after = await self._probe_concurrency_wait_ms(int(proposed_value))
        results = [measured_before, measured_after]
        call_index = {"i": 0}

        def measure_fn() -> float:
            i = call_index["i"]
            call_index["i"] = min(i + 1, 1)
            return results[i]

        def better_fn(before: float, after: float) -> bool:
            return after < before  # lower real queueing wait is better

        improved = better_fn(measured_before, measured_after)
        tunable = self._tuning_registry.get("llm_max_concurrent")
        equivalence_result: bool | None = None
        if improved and tunable.safety_class is SafetyClass.SENSITIVE:
            equivalence_result = await self._concurrency_equivalence_check(
                before_value, int(proposed_value),
            )

        def equivalence_check_fn() -> bool:
            return bool(equivalence_result)

        return self._llm_concurrency_hypothesis_loop.apply_and_measure(
            tunable_name="llm_max_concurrent", proposed_value=float(proposed_value),
            hypothesis=hypothesis, measure_fn=measure_fn, better_fn=better_fn,
            equivalence_check_fn=equivalence_check_fn,
        )

    async def _concurrency_equivalence_check(self, before_value: int, after_value: int) -> bool:
        """B13.2's real semantic-safety gate for `llm_max_concurrent`,
        reusing `simulation/sandbox.py`'s own real fork-and-tick
        technique (`World.from_dict(world.to_dict(), config)` + a real
        throwaway `SimulationEngine`, never `copy.deepcopy` — the
        established precedent for safely forking a live `World` without
        dragging along any native-extension-backed object graph) and
        B15.1's own hashing shape (`scripts/verify_replay_hash.py`'s
        `_state_hash`). Two independent forks, one config carrying
        `before_value` and one carrying `after_value` (both LLM
        disabled), each ticked `CONCURRENCY_EQUIVALENCE_CHECK_TICKS`
        times with the same real background-task cleanup `run_
        counterfactual` uses. Byte-identical `to_dict()` output
        confirms `llm_max_concurrent` genuinely cannot affect Body-
        deterministic state — never assumed, always checked."""
        import dataclasses

        from hearthmind.persistence.database import connect

        def _hash(world: World) -> str:
            payload = json.dumps(world.to_dict(), sort_keys=True, default=str)
            return hashlib.sha256(payload.encode()).hexdigest()

        base_snapshot = self.world.to_dict()
        hashes: dict[int, str] = {}
        for value in (before_value, after_value):
            fork_config = dataclasses.replace(self.world.config, llm_enabled=False, llm_max_concurrent=value)
            forked_world = World.from_dict(base_snapshot, fork_config)
            conn = connect(":memory:")
            fork_engine = SimulationEngine(conn, fork_config, forked_world)
            try:
                for _ in range(CONCURRENCY_EQUIVALENCE_CHECK_TICKS):
                    fork_engine._tick_once()
                    await asyncio.sleep(0)
            finally:
                if fork_engine._background_tasks:
                    for task in fork_engine._background_tasks:
                        task.cancel()
                    await asyncio.gather(*fork_engine._background_tasks, return_exceptions=True)
                conn.close()
            hashes[value] = _hash(forked_world)
        return hashes[before_value] == hashes[after_value]

    def _maybe_refresh_machine_profile(self, events: list[str]) -> None:
        """Tier 5 B7.2's real control point (explicit user directive:
        "B8 and MachineProfile persistence... still have no real call
        site — flagged for later" — closing that flag). Monthly, not
        daily like `_maybe_tune_llm_concurrency` — this is the one
        place that runs `HostProbe.sample(run_storage_bench=True)`, a
        real (small, ~4 MiB) disk write+read+fsync the daily check
        deliberately skips as "needless disk I/O on a check that
        already runs at most once a day."

        Tier 5 B8.4's real control point, same batch: that benchmark
        only runs when `is_quiet_window` reads the real `self._recent_
        llm_backlog_samples` history (sampled daily by `_maybe_tune_
        llm_concurrency`, regardless of whether that method goes on to
        skip its own tuning check) as genuinely quiet — "schedule
        expensive maintenance... into predicted-quiet periods," B8.4's
        own stated purpose, applied to this exact kind of work for the
        first time. A month with no evidence yet (a fresh world, or an
        LLM-disabled run whose backlog never moves) reads as NOT quiet
        by `is_quiet_window`'s own conservative default — the benchmark
        simply waits for real evidence rather than guessing either way.

        `MachineProfile.record_storage_benchmark` folds the real
        reading into the profile's EMA (B7.2's "gradually evolves...
        not resets each time") and the profile is saved back to
        `self._machine_profile_path` so it survives a restart. A
        `:memory:` `db_path` (`self._machine_profile_path is None`)
        keeps the profile in-RAM only for this run — never crashes,
        just doesn't persist; a real write failure (disk full, a
        permissions change mid-run) is likewise swallowed rather than
        taking down the tick loop over what is, at most, a missed
        refinement."""
        if "month_end" not in events:
            return
        if not is_quiet_window(list(self._recent_llm_backlog_samples), float(self._backpressure_limit)):
            return
        probe = HostProbe.sample(run_storage_bench=True)
        self._machine_profile.record_storage_benchmark(probe)
        if self._machine_profile_path is not None:
            try:
                self._machine_profile.save(self._machine_profile_path)
            except OSError:
                pass

    def _maybe_tick_workload_forecaster(self, events: list[str]) -> None:
        """Tier 7 HCA G2 (explicit user instruction: "Build G2"): gives
        B8.1/L3.2's `WorkloadForecaster` the real continual-retrain
        cadence its own docstring named as still open, using G1's
        `LearningSpecialist`. Closes three previously-separate flagged
        gaps at once (Part B's B8.1-B8.3, Tier 6's L3.2, HCA's own G2
        test) — all three name the identical unwired model.

        Two real-state-driven daily steps, then a monthly retrain:

        1. Sample the forecaster's own real feature vector (current
           backlog, real per-day dialogue/cognition call counts, a
           real disaster-pressure flag reusing `FLOOD_PRESSURE_
           THRESHOLD`/`HEATWAVE_PRESSURE_THRESHOLD`, a real recent-
           festival flag from `last_life_events`, real season) plus a
           snapshot of the real cumulative `calls_attempted` counter —
           remembered until `WORKLOAD_SAMPLE_HORIZON_DAYS` later.
        2. Resolve any sample whose horizon has passed into a real
           `(features, observed_call_volume)` training example —
           `observed_call_volume` is the REAL delta in `calls_
           attempted` over that exact window, never a guess — and score
           it against the real `ForecastAccuracyTracker`.

        Retraining itself (monthly, once `WORKLOAD_MIN_EXAMPLES_TO_
        RETRAIN` real examples have accumulated) goes entirely through
        `LearningSpecialist.learn` — G1's real shadow-gated loop, not a
        second training path. `_workload_forecaster.model` is kept in
        sync with `_workload_specialist.model` explicitly after every
        attempt, since `learn()` may swap in a whole new `MLP` object
        on acceptance rather than mutating the old one."""
        if "day_end" not in events:
            return
        runner = self._cognition_runner
        tick = self.world.clock.tick_count
        disasters = self.world.disasters
        features = {
            "current_backlog": float(self._effective_backlog()),
            "recent_dialogue_rate": float(self._dialogue_calls_today),
            "recent_cognition_rate": float(self._cognition_calls_today),
            "active_disaster": 1.0 if (
                disasters.flood_pressure >= FLOOD_PRESSURE_THRESHOLD
                or disasters.heat_pressure >= HEATWAVE_PRESSURE_THRESHOLD
            ) else 0.0,
            "festival_scheduled": 1.0 if any(
                category == "festival" for category, _ in self.world.last_life_events
            ) else 0.0,
            "season": self.world.clock.season,
        }
        predicted = self._workload_forecaster.predict(features)
        self._workload_pending_samples.append((tick, features, predicted, runner.calls_attempted))
        if len(self._workload_pending_samples) > WORKLOAD_PENDING_SAMPLES_MAX:
            self._workload_pending_samples = self._workload_pending_samples[-WORKLOAD_PENDING_SAMPLES_MAX:]
        self._dialogue_calls_today = 0
        self._cognition_calls_today = 0

        ticks_per_day = self.world.config.minutes_per_day // self.world.config.sim_minutes_per_tick
        horizon_ticks = WORKLOAD_SAMPLE_HORIZON_DAYS * ticks_per_day
        still_pending = []
        for sample_tick, sample_features, sample_predicted, sample_calls in self._workload_pending_samples:
            if tick - sample_tick < horizon_ticks:
                still_pending.append((sample_tick, sample_features, sample_predicted, sample_calls))
                continue
            observed = float(runner.calls_attempted - sample_calls)
            self._workload_accuracy_tracker.record(sample_predicted, observed)
            self._workload_training_examples.append(make_training_example(sample_features, observed))
        self._workload_pending_samples = still_pending
        if len(self._workload_training_examples) > WORKLOAD_TRAINING_EXAMPLES_MAX:
            self._workload_training_examples = self._workload_training_examples[-WORKLOAD_TRAINING_EXAMPLES_MAX:]

        if "month_end" not in events:
            return
        if len(self._workload_training_examples) < WORKLOAD_MIN_EXAMPLES_TO_RETRAIN:
            return
        examples = list(self._workload_training_examples)
        n_holdout = max(1, int(len(examples) * WORKLOAD_HOLDOUT_FRACTION))
        holdout, new_examples = examples[-n_holdout:], examples[:-n_holdout]
        if not new_examples:
            return
        result = self._workload_specialist.learn(new_examples, holdout, tick)
        self._workload_forecaster.model = self._workload_specialist.model
        self._workload_learn_log.append({
            "tick": tick, "accepted": result.accepted,
            "candidate_metric": result.candidate_metric, "baseline_metric": result.baseline_metric,
            "reason": result.reason, "examples_used": len(new_examples), "holdout_size": len(holdout),
        })
        self._workload_training_examples = []

    def _maybe_advance_escalation_ladder(self, events: list[str]) -> None:
        """Tier 5 B15.3/B15.4's real control point (explicit user
        instruction: "continue B and try closing it this turn").
        Daily, same cadence as `_maybe_tune_llm_concurrency`/`_maybe_
        refresh_machine_profile`. `pressured` reuses `LLM_PRESSURE_
        SLOWDOWN_START_RATIO` — the exact threshold `run_forever`'s own
        real-time tick pacing already treats as "pressure begins here"
        — so this ladder and that untouched, preserved mechanism agree
        on what counts as pressure, without this ever driving pacing
        itself.

        `EscalationLadder.observe` moves at most one rung per call, per
        its own contract; `cognition_budget_for_rung` is recomputed
        every call (cheap, a bare dataclass) and cached in `self.
        _cognition_budget` for `_schedule_due_cognition`'s per-tick
        consumption — a real change is only ever visible once rung 5
        (`REDUCE_COGNITION_BREADTH`) is actually reached, per B15.4's
        own "only rung 5 does real, visible work" framing."""
        if "day_end" not in events:
            return
        pressured = self.llm_pressure_ratio() >= self._pacing_tunable(
            "llm_pressure_slowdown_start_ratio", LLM_PRESSURE_SLOWDOWN_START_RATIO,
        )
        self._escalation_ladder.observe(self.world.clock.tick_count, pressured)
        self._cognition_budget = self._escalation_ladder.cognition_budget_for_rung(
            ESCALATION_COGNITION_BASE_BUDGET, ESCALATION_COGNITION_REDUCED_BUDGET,
        )

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
        the two thresholds (0.15-0.5 by default): exactly 1.0, the
        normal healthy-load rate."""
        ratio = self.llm_pressure_ratio()
        slowdown_start = self._pacing_tunable(
            "llm_pressure_slowdown_start_ratio", LLM_PRESSURE_SLOWDOWN_START_RATIO,
        )
        speedup_start = self._pacing_tunable(
            "llm_pressure_speedup_start_ratio", LLM_PRESSURE_SPEEDUP_START_RATIO,
        )
        min_speedup = self._pacing_tunable(
            "llm_pressure_min_speedup_multiplier", LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER,
        )
        if ratio > slowdown_start:
            span = LLM_PRESSURE_PAUSE_RATIO - slowdown_start
            if span <= 0:
                return 1.0
            progress = min(1.0, (ratio - slowdown_start) / span)
            return 1.0 + progress * (LLM_PRESSURE_MAX_SLOWDOWN - 1.0)
        if ratio < speedup_start:
            if speedup_start <= 0:
                return 1.0
            progress = min(1.0, 1.0 - ratio / speedup_start)
            return 1.0 - progress * (1.0 - min_speedup)
        return 1.0

    def _pacing_tunable(self, name: str, default: float) -> float:
        """Tier 5 B6.3 closed this gap, v1.34.214: `TunableRegistry`
        held these three pacing constants as real, adjustable `Tunable`
        entries since v1.34.168, but `_maybe_advance_escalation_ladder`/
        `_llm_pressure_interval_multiplier` read the flat module
        constants directly, so adjusting the registry entry (manually,
        or from a future controller) was a genuine no-op. Every call
        site above now reads through here instead. `default` (the
        module constant) is the fallback only if the tunable is somehow
        unregistered -- `register_llm_pacing_tunables` always registers
        it in `__init__`, so this should never trigger in practice."""
        try:
            return float(self._tuning_registry.get(name).value)
        except KeyError:
            return default

    _DORMANCY_AGGRESSIVENESS_MULTIPLIER = {"low": 2.0, "normal": 1.0, "high": 0.5}

    def _dormancy_idle_threshold(self, base_threshold: int) -> int:
        """Tier 5 B7.3 closed this gap, v1.34.214: `select_strategy`'s
        `dormancy_aggressiveness` hint ("low"/"normal"/"high") has been
        computed every `MachineProfile` refresh since v1.34.173 but was
        surfaced only in diagnostics, consumed nowhere. Every real B4.2
        dormancy candidate's own idle-checks threshold (institutions/
        ideas/traditions/settlements — all currently a flat 3) now
        scales through here: "high" (memory pressure, swap, thermal
        throttling, or genuinely modest hardware) sleeps an idle entity
        roughly twice as fast, "low" (plenty of headroom) waits roughly
        twice as long before narrowing Mind-layer attention, "normal"
        (or no strategy read yet) reproduces the exact original flat
        value. Never below 1 -- a threshold of 0 would sleep on the
        very first idle check, which is a qualitatively different
        (and untested) behavior from "faster," not just "more
        aggressive." Real dormancy semantics (the ACTIVE/DROWSY/
        DORMANT/ARCHIVED state machine, the lossless elapsed-tick
        wake contract) are completely untouched -- this only scales
        how quickly something is considered idle enough to narrow
        attention on, never whether that's safe to do."""
        if self._last_strategy is None:
            return base_threshold
        multiplier = self._DORMANCY_AGGRESSIVENESS_MULTIPLIER.get(
            self._last_strategy.dormancy_aggressiveness, 1.0,
        )
        return max(1, round(base_threshold * multiplier))

    def _effective_emergence_log_cap(self) -> int:
        """Tier 5 B7.3 closed this gap, v1.34.214: `select_strategy`'s
        `cache_size_hint` ("small"/"normal"/"large") has been computed
        every `MachineProfile` refresh since v1.34.173 but was
        surfaced only in diagnostics, consumed nowhere. Scales `World.
        emergence_log`'s own eviction cap (`EMERGENCE_LOG_MAX_STORED`,
        flat 500) -- a genuinely memory-scaled knob: modest hardware
        (or one under measured memory/swap/thermal pressure, which
        `select_strategy` already folds into a smaller cache_size_hint)
        keeps less raw emergence-log history resident before B12's
        `_emergence_compression` condenses the overflow, a well-
        provisioned host keeps more. "normal" (or no strategy read
        yet) reproduces the exact original flat cap. Never below 50 --
        the ladder's own RAW-stage threshold is `EMERGENCE_LOG_MAX_
        STORED // 5`, so a cap much smaller than that would make
        B12's own batching math degenerate."""
        if self._last_strategy is None:
            return EMERGENCE_LOG_MAX_STORED
        cache = self._last_strategy.cache_size_hint
        if cache == "small":
            return max(50, EMERGENCE_LOG_MAX_STORED // 2)
        if cache == "large":
            return EMERGENCE_LOG_MAX_STORED * 2
        return EMERGENCE_LOG_MAX_STORED

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
        `boundary_event` is crossed; True on `"day_end"` ticks within
        that window (once per day, not every tick — see below) until
        `_mark_season_year_resolved` records this ordinal as done.

        Live-diagnostic finding (the same class `_reactive_pillar_
        backpressured` closes for the three per-tick reactive Nature
        triggers): this window used to have no `"day_end"` restriction
        at all, unlike `_monthly_gate`'s already-correct once-per-day
        shape — so a backpressured job in `SEASON_YEAR_JOBS_WITH_RETRY`
        re-attempted (and, on failure, re-incremented `calls_dropped_
        backpressure`) on literally every tick of its `SEASON_YEAR_JOB_
        RETRY_WINDOW_DAYS`-day window instead of once a day, needlessly
        inflating the drop counter for no scheduling benefit (the
        window's OPENING tick always coincides with a real `day_end`
        anyway — a season/year boundary is itself a day boundary — so
        this costs nothing on the tick that matters)."""
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
        if "day_end" not in events:
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
        this is exactly the old behavior.

        Tier 5 B4.2's fourth dormancy candidate ("inactive settlements",
        `_update_settlement_dormancy`) narrows the rotation pool to
        settlements something has actually happened to, falling back to
        the full list if every named settlement happens to be asleep at
        once — same fallback shape `_maybe_spread_concepts`/`_maybe_
        spread_tradition_keeping` use for their own sleeping entities.
        With one settlement (or before any settlement has accumulated
        enough idle checks to sleep) this is still exactly the old
        behavior — a real no-op for the common case."""
        named = [s for s in self.world.settlements if s.name]
        if not named:
            return self.world.settlement
        awake = [s for s in named if self._settlement_dormancy.is_scheduled(str(s.id))]
        pool = awake if awake else named
        clock = self.world.clock
        month_ordinal = clock.year * len(self.world.config.days_per_month) + clock.month_index
        return pool[month_ordinal % len(pool)]

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
                    # Tier 0 batch (docs/ROADMAP-2026-07-REMAINING.md):
                    # naming joins Village pillar's wired jobs — a
                    # settlement's own name is a real settled fact.
                    self.world.village_pillar.upsert_world_model(
                        self.world.clock.tick_count, "the settlement's name", new_name,
                        1.0, status="observation", source="naming",
                    )
                    self._append_emergence(
                        "opportunity", "settlement", f"{noun} came to be known as {new_name}.",
                        ("village",),
                    )

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
        ("_maybe_spread_tradition_keeping", _JOB_NO_ARGS),
        ("_apply_trigger_rules_from_life_events", _JOB_NO_ARGS),
        ("_maybe_tick_trigger_state_edges", _JOB_NO_ARGS),
        ("_maybe_tick_composite_reactions", _JOB_NO_ARGS),
        ("_maybe_schedule_rule_proposal", _JOB_EVENTS),
        ("_maybe_schedule_composite_reaction_propose", _JOB_EVENTS),
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
        ("_maybe_tick_settlement_trade", _JOB_EVENTS),
        ("_maybe_pillar_initiates_contact", _JOB_EVENTS),
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
        ("_update_institution_dormancy", _JOB_NO_ARGS),
        ("_update_idea_dormancy", _JOB_NO_ARGS),
        ("_update_tradition_dormancy", _JOB_NO_ARGS),
        ("_update_settlement_dormancy", _JOB_NO_ARGS),
        ("_maybe_schedule_institution_culture", _JOB_EVENTS),
        ("_schedule_due_cognition", _JOB_NO_ARGS),
        ("_schedule_due_dialogue", _JOB_NO_ARGS),
        ("_schedule_voice_dialogue", _JOB_NO_ARGS),
        ("_maybe_refresh_machine_profile", _JOB_EVENTS),
        ("_maybe_advance_escalation_ladder", _JOB_EVENTS),
        ("_maybe_auto_llm_concurrency_hypothesis", _JOB_EVENTS),
        ("_maybe_tick_workload_forecaster", _JOB_EVENTS),
    )

    # B0.3's real migrations: `_TICK_JOBS` entries named here are NOT
    # called directly in `_tick_once`'s loop below — they run through
    # their own dedicated `Scheduler` instance (a real B1 TaskRegistry +
    # B2 Scheduler pair, built in `__init__`; see its own comment for
    # why each migrated job gets its OWN pair rather than sharing one)
    # instead. Maps method name -> the instance attribute name of that
    # job's scheduler. Kept as a separate, explicit mapping rather than
    # inferred from the registries so the table above stays the single
    # readable source of ordering, and adding a job here is a one-line,
    # deliberate opt-in.
    _RUNTIME_SCHEDULED_JOB_SCHEDULERS: dict[str, str] = {
        "_maybe_schedule_naming": "_runtime_scheduler",
        "_maybe_retry_mind_authoring": "_runtime_scheduler_mind_authoring",
        "_maybe_tick_trigger_state_edges": "_runtime_scheduler_trigger_edges",
        "_maybe_spread_concepts": "_runtime_scheduler_spread_concepts",
        "_maybe_spread_tradition_keeping": "_runtime_scheduler_spread_tradition_keeping",
        "_apply_trigger_rules_from_life_events": "_runtime_scheduler_trigger_rules_life_events",
        "_maybe_tick_composite_reactions": "_runtime_scheduler_composite_reactions",
        "_maybe_schedule_record": "_runtime_scheduler_record",
        "_maybe_schedule_dispute": "_runtime_scheduler_dispute",
        "_maybe_schedule_migration_decision": "_runtime_scheduler_migration_decision",
        "_schedule_due_cognition": "_runtime_scheduler_due_cognition",
        "_schedule_due_dialogue": "_runtime_scheduler_due_dialogue",
        "_schedule_voice_dialogue": "_runtime_scheduler_voice_dialogue",
        "_maybe_schedule_chronicle": "_runtime_scheduler_chronicle",
        "_maybe_schedule_documentary": "_runtime_scheduler_documentary",
        "_maybe_schedule_tradition": "_runtime_scheduler_tradition",
        "_maybe_schedule_folklore": "_runtime_scheduler_folklore",
        "_maybe_schedule_legend_detection": "_runtime_scheduler_legend_detection",
        "_maybe_schedule_invention": "_runtime_scheduler_invention",
        "_maybe_schedule_ontology_proposal": "_runtime_scheduler_ontology_proposal",
        "_maybe_schedule_ontology_evolution": "_runtime_scheduler_ontology_evolution",
        "_maybe_schedule_composite_entity": "_runtime_scheduler_composite_entity",
        "_maybe_schedule_nature_mind": "_runtime_scheduler_nature_mind",
        "_maybe_schedule_species_variant": "_runtime_scheduler_species_variant",
        "_maybe_schedule_rule_proposal": "_runtime_scheduler_rule_proposal",
        "_maybe_schedule_composite_reaction_propose": "_runtime_scheduler_composite_reaction_propose",
        "_maybe_schedule_festival": "_runtime_scheduler_festival",
        "_maybe_schedule_religion": "_runtime_scheduler_religion",
        "_maybe_schedule_narrative_direction": "_runtime_scheduler_narrative_direction",
        "_maybe_schedule_culture_digest": "_runtime_scheduler_culture_digest",
        "_maybe_schedule_consciousness": "_runtime_scheduler_consciousness",
        "_maybe_schedule_reflection": "_runtime_scheduler_reflection",
        "_maybe_schedule_self_tuning": "_runtime_scheduler_self_tuning",
        "_maybe_schedule_musing": "_runtime_scheduler_musing",
        "_maybe_schedule_caravan": "_runtime_scheduler_caravan",
        "_maybe_schedule_town_brain": "_runtime_scheduler_town_brain",
        "_maybe_schedule_beliefs": "_runtime_scheduler_beliefs",
        "_maybe_schedule_personal_belief": "_runtime_scheduler_personal_belief",
        "_maybe_schedule_dream": "_runtime_scheduler_dream",
        "_maybe_schedule_memory_drift": "_runtime_scheduler_memory_drift",
        "_maybe_tick_temperament": "_runtime_scheduler_temperament",
        "_maybe_schedule_omen": "_runtime_scheduler_omen",
        "_maybe_tick_market_prices": "_runtime_scheduler_market_prices",
        "_maybe_tick_settlement_trade": "_runtime_scheduler_settlement_trade",
        "_maybe_pillar_initiates_contact": "_runtime_scheduler_pillar_initiates_contact",
        "_maybe_schedule_guild_founding": "_runtime_scheduler_guild_founding",
        "_maybe_schedule_faction": "_runtime_scheduler_faction",
        "_maybe_schedule_institution_belief": "_runtime_scheduler_institution_belief",
        "_maybe_schedule_geography": "_runtime_scheduler_geography",
        "_maybe_schedule_fission": "_runtime_scheduler_fission",
        "_maybe_schedule_diplomacy": "_runtime_scheduler_diplomacy",
        "_maybe_schedule_laws": "_runtime_scheduler_laws",
        "_maybe_schedule_noncore_nudge": "_runtime_scheduler_noncore_nudge",
        "_maybe_schedule_letter": "_runtime_scheduler_letter",
        "_update_institution_dormancy": "_runtime_scheduler_institution_dormancy",
        "_update_idea_dormancy": "_runtime_scheduler_idea_dormancy",
        "_update_tradition_dormancy": "_runtime_scheduler_tradition_dormancy",
        "_update_settlement_dormancy": "_runtime_scheduler_settlement_dormancy",
        "_maybe_schedule_institution_culture": "_runtime_scheduler_institution_culture",
    }

    def _tick_once(self) -> None:
        tick_start = time.perf_counter()
        self._reserved_this_tick = 0  # see its docstring: fresh reservation count each tick
        self._apply_pending_cognition_results()
        self._apply_pending_dialogue_results()
        self._apply_pending_interventions()

        previous_season = self.world.clock.season
        events = self.world.tick()
        # Tier 5 B3's real control point: `_update_institution_dormancy`'s
        # Task is declared `ON_EVENT`/`event_types={"month_end"}` — the
        # scheduler's own B3.2 EventBus needs the real per-tick calendar
        # event published into it before that job's dispatch slot runs,
        # same source (`events`) its old internal `if "month_end" not
        # in events: return` guard used to read directly.
        if "month_end" in events:
            self._runtime_scheduler_institution_dormancy.event_bus.publish("month_end")
            self._runtime_scheduler_idea_dormancy.event_bus.publish("month_end")
            self._runtime_scheduler_tradition_dormancy.event_bus.publish("month_end")
            self._runtime_scheduler_settlement_dormancy.event_bus.publish("month_end")
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
        theft_count_this_tick = 0
        built_kinds_this_tick: list[str] = []
        for category, description in self.world.last_life_events:
            log_event(
                self.conn, tick=self.world.clock.tick_count,
                category=category, description=description,
                commit=False,
            )
            if category == "theft":
                theft_count_this_tick += 1
            elif category == "construction_started":
                # Tier 0 (29th site's producer half): `Population.
                # _maybe_start_construction`'s description always starts
                # "{Kind} construction ..." (both its own branches share
                # this exact template) — the one place engine.py can
                # recover WHICH kind was chosen without threading a new
                # structured field through `last_life_events`. Feeds
                # `choose_building_kind`'s `pillar_lean` (computed once
                # per tick in `World.tick`) — real cultural momentum,
                # "the village keeps building what it's been building."
                built_kinds_this_tick.append(description.split(" construction", 1)[0].lower())
        for kind_value in built_kinds_this_tick:
            existing_kind_signal = self.world.village_pillar.find_world_model_entry(kind_value)
            prior_kind_confidence = existing_kind_signal["confidence"] if existing_kind_signal else 0.3
            self.world.village_pillar.upsert_world_model(
                self.world.clock.tick_count, kind_value,
                f"the village keeps returning to {kind_value.replace('_', ' ')} construction.",
                min(1.0, prior_kind_confidence + 0.05), status="observation", source="construction",
                revises_id=existing_kind_signal["id"] if existing_kind_signal else None,
            )
        if theft_count_this_tick:
            # Tier 0 (25th site, new producer's second half): the
            # `Population.law_signal_counts["theft"]` increment happens
            # in population.py, decoupled from pillar access by design
            # — `World.last_life_events` (already read every tick right
            # above) is the one place engine.py sees a theft occur.
            # Same category-keyed subject shape as the dispute_feud
            # mirror; real consumer: `_maybe_schedule_laws`.
            existing_theft_signal = self.world.village_pillar.find_world_model_entry("theft")
            prior_theft_confidence = existing_theft_signal["confidence"] if existing_theft_signal else 0.3
            self.world.village_pillar.upsert_world_model(
                self.world.clock.tick_count, "theft",
                "The village has been seeing theft among its own people.",
                min(1.0, prior_theft_confidence + theft_count_this_tick * 0.05),
                status="observation", source="theft",
                revises_id=existing_theft_signal["id"] if existing_theft_signal else None,
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
        self._maybe_schedule_nature_causal_reasoning()
        if "season_end" in events:
            self._detect_social_hub()
            self._detect_social_bridge()
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
            self._tick_districts()
            # Tier 5 B6 adaptive tuning: same daily cadence as every
            # other day_end check above, zero LLM cost (reads already-
            # tracked stats, never issues a call of its own).
            self._maybe_tune_llm_concurrency()
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
            scheduler_attr = self._RUNTIME_SCHEDULED_JOB_SCHEDULERS.get(method_name)
            if scheduler_attr is not None:
                # B0.3's real migrations: this job's entry stays in its
                # exact ordering slot in the table above (order is
                # load-bearing), but instead of a direct call it now
                # runs through its own dedicated B1/B2 TaskRegistry+
                # Scheduler pair — see `__init__`'s registration for why
                # each migrated job gets its own pair and why CRITICAL+
                # PERIODIC reproduces "always runs, every tick" exactly.
                # `Scheduler.run_tick(*args, **kwargs)` forwards straight
                # to `task.fn(*args, **kwargs)`, so an `_JOB_EVENTS`/
                # `_JOB_EVENTS_SEASON` job's real per-tick arguments pass
                # through exactly as the pre-migration direct call did.
                if arg_kind == _JOB_NO_ARGS:
                    report = getattr(self, scheduler_attr).run_tick()
                elif arg_kind == _JOB_EVENTS:
                    report = getattr(self, scheduler_attr).run_tick(events)
                else:  # _JOB_EVENTS_SEASON
                    report = getattr(self, scheduler_attr).run_tick(events, previous_season)
                if report.errors:
                    # Scheduler.run_tick() catches broadly and records a
                    # repr rather than letting an exception propagate
                    # (so one budgeted task's failure can't take down a
                    # sibling task's run) — re-raising here preserves
                    # this job's own pre-migration behavior (an
                    # uncaught exception stops the tick) instead of
                    # silently swallowing it.
                    raise RuntimeError(f"runtime-scheduled task(s) errored: {report.errors}")
                continue
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
        # Tier 5 B2's real control point (see `BROADCAST_SUBSYSTEM_
        # BUDGET_SECONDS`'s docstring) — routed through its own dedicated
        # DEFERRABLE-priority scheduler instead of a direct call. Same
        # exception-propagation preservation as every B0.3 migration:
        # `Scheduler.run_tick()` catches broadly and records a repr
        # rather than letting an exception propagate, so a broadcast
        # failure is re-raised here to keep matching the pre-migration
        # behavior (an uncaught exception here stopped the tick before,
        # and still does).
        broadcast_report = self._runtime_scheduler_broadcast.run_tick()
        if broadcast_report.errors:
            raise RuntimeError(f"runtime-scheduled task(s) errored: {broadcast_report.errors}")

        if self._snapshot_scheduler.due(
            self.world.clock.tick_count, list(self._recent_llm_backlog_samples), float(self._backpressure_limit),
        ):
            # B14.2's real wiring: WHICH kind (full vs. incremental) is
            # the scheduler's own decision (`SnapshotScheduler.plan()`,
            # already real since B14.1/B14.2 shipped) — this periodic
            # call site is the only place that should ever request an
            # incremental save. The other two `save_snapshot(...)` call
            # sites (world creation/first-load, final-save-on-stop) stay
            # on the default `kind="full"` deliberately: a fresh world
            # has no snapshot to diff against anyway, and a clean
            # shutdown should always leave a real, standalone recovery
            # anchor rather than one more link in a chain that a
            # future incremental save might extend.
            kind = self._snapshot_scheduler.plan().value
            save_snapshot(self.conn, self.world, kind=kind)
            self._snapshots_saved += 1
            logger.debug("Snapshot saved at tick %s (kind=%s).", self.world.clock.tick_count, kind)

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
            previous_goal = agent.goal if agent is not None else None
            if agent is not None:
                if agent.hunger > SURVIVAL_HUNGER_THRESHOLD:
                    goal = AgentGoal.FORAGE
                elif agent.energy < SURVIVAL_ENERGY_THRESHOLD:
                    goal = AgentGoal.REST
            self.world.population.apply_goal(agent_id, goal, reason, seek_candidate_id)
            # D11 (Tier 3 item 30, docs/ROADMAP-2026-07-REMAINING.md):
            # per-agent cognition's volume-safe mirror into Humans'
            # pillar — option (a) of the doc's three named candidates.
            # Every entry reaching this loop is already a genuine
            # LLM-authored result (a fallback never queues into
            # `_pending_goal_results` — see `_run_cognition`'s
            # `used_fallback` branch, which defers instead), so the one
            # remaining volume gate is "did the goal actually CHANGE" —
            # same shape dialogue's own `is_llm`/`surfaced` flags gave
            # dialogue for free. A core-cast member reconsiders their
            # goal on most due cognition calls but doesn't always ACT on
            # it, so this fires far less than once/agent/day, unlike a
            # blind per-call mirror which would flood Humans' bounded
            # `memory`/`working_memory` FIFO (the reason this was left
            # unmirrored through every earlier Tier 0 pass).
            if agent is not None and previous_goal is not None and goal != previous_goal and reason.strip():
                self.world.humans_pillar.remember(f"{agent.name} decided to {goal.value}: {reason}")
                self._append_emergence(
                    "unexplained_shift", "cognition", f"{agent.name} decided to {goal.value}: {reason}",
                    ("humans",),
                )
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
        # Tier 5 B15.4's real control point: `self._cognition_budget`
        # (`EscalationLadder.cognition_budget_for_rung`, refreshed daily
        # by `_maybe_advance_escalation_ladder`) caps how many agents
        # THIS TICK may go on to spend a real LLM call below — see the
        # `use_llm` gate. At every rung except sustained rung-5 pressure
        # this cap is effectively unreachable (`ESCALATION_COGNITION_
        # BASE_BUDGET`), a genuine no-op; WHICH agents fill whatever
        # budget remains stays entirely `due`'s own staggered-slot/
        # significance ordering, per B15.4's own "never a selection"
        # guarantee — this counter only ever says how many, never who.
        llm_cognition_calls_this_tick = 0
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
                and llm_cognition_calls_this_tick < self._cognition_budget.count
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
            llm_cognition_calls_this_tick += 1  # ...and against B15.4's cognition_budget_for_rung cap
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
            self._cognition_calls_today += 1  # Tier 7 G2's real workload-forecaster feature
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
                # Tier 0: the voice pair is the ONE dialogue thread that
                # ever reaches here (`is_llm` can only be them since
                # v1.4.0's redesign — see this block's own docstring
                # above), so mirroring it into Humans' memory is
                # naturally volume-bounded, unlike mirroring dialogue in
                # general would be.
                self.world.humans_pillar.remember(
                    f'{agent_a.name}: "{parsed["line_a"]}" — {agent_b.name}: "{parsed["line_b"]}"'
                )
                self._append_emergence(
                    "opportunity", "dialogue", f'{agent_a.name}: "{parsed["line_a"]}" — {agent_b.name}: "{parsed["line_b"]}"',
                    ('humans',),
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
                self.world.humans_pillar.remember(f"{target.name} retold a rumor in their own way: {retelling}")
                self._append_emergence(
                    "unexplained_shift", "rumor", f"{target.name} retold a rumor in their own way: {retelling}",
                    ('humans',),
                )
                # A17 "false beliefs propagate if fit, not suppressed
                # for being false" — fitness and truth_score are
                # computed independently (see memetics.rumor_fitness/
                # rumor_truth_score's docstrings); only fitness feeds
                # the real mechanical consequence below, truth_score is
                # tracked for dev-console observability only.
                fitness = memetics.rumor_fitness(retelling)
                truth_score = memetics.rumor_truth_score(rumor, retelling)
                subject_name = self.world.population._apply_rumor_retelling_fitness(target, retelling, fitness)
                self._rumor_retellings_recent.append({
                    "reteller": target.name, "subject": subject_name,
                    "fitness": round(fitness, 3), "truth_score": round(truth_score, 3),
                    "tick": self.world.clock.tick_count,
                })
                if len(self._rumor_retellings_recent) > 20:
                    del self._rumor_retellings_recent[:-20]

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
        elif kind == "llm_concurrency_hypothesis":
            self._maybe_start_llm_concurrency_hypothesis(item)

    def _maybe_start_llm_concurrency_hypothesis(self, item: dict) -> None:
        """Tier 5 B13's real dev-console/API trigger for `_run_llm_
        concurrency_hypothesis` — enqueued via `POST /intervene/llm-
        concurrency-hypothesis`, applied here on the next real tick
        (same seam every other `/intervene/*` request uses). One in
        flight at a time — a second request while one is already
        running is silently dropped rather than queued or stacked,
        since only the MOST RECENT result is ever surfaced anyway."""
        try:
            proposed_value = int(item["proposed_value"])
        except (KeyError, TypeError, ValueError):
            return
        hypothesis = str(item.get("hypothesis", "")).strip()[:200] or "manually requested via the dev console"
        self._spawn_llm_concurrency_hypothesis(proposed_value, hypothesis, source="manual")

    def _spawn_llm_concurrency_hypothesis(self, proposed_value: int, hypothesis: str, source: str) -> None:
        """The real background-task spawn shared by both the manual
        dev-console/API trigger above and the automatic monthly one
        below (`_maybe_auto_llm_concurrency_hypothesis`) — the probe/
        equivalence-check both need several real ticks/awaits, too
        long to run synchronously from either caller. One in flight at
        a time regardless of which caller asked — a request arriving
        while one is already running is silently dropped, never queued
        or stacked, since only the MOST RECENT result is ever surfaced.
        `source` ("manual"/"auto") is threaded into the recorded result
        purely for `full_diagnostics()`'s benefit — which kind of
        request produced this reading is real, useful context, never
        consulted by any decision logic itself."""
        if self._llm_concurrency_hypothesis_running:
            return
        self._llm_concurrency_hypothesis_running = True

        async def _runner() -> None:
            try:
                record = await self._run_llm_concurrency_hypothesis(proposed_value, hypothesis)
                self._last_llm_concurrency_hypothesis = {
                    "source": source,
                    "hypothesis": record.hypothesis,
                    "tunable_name": record.tunable_name,
                    "before_value": record.before_value,
                    "after_value": record.after_value,
                    "measured_before_ms": record.measured_before,
                    "measured_after_ms": record.measured_after,
                    "gate_applied": record.gate_applied,
                    "gate_passed": record.gate_passed,
                    "decision": record.decision,
                    "reason": record.reason,
                }
            except Exception:
                logger.exception("llm_concurrency_hypothesis run failed")
                self._last_llm_concurrency_hypothesis = {
                    "source": source, "decision": "error",
                    "reason": "the hypothesis run raised an exception; see server logs",
                }
            finally:
                self._llm_concurrency_hypothesis_running = False

        task = asyncio.create_task(_runner())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _maybe_auto_llm_concurrency_hypothesis(self, events: list[str]) -> None:
        """Explicit user directive ("keep building adaptive runtime to
        what I originally wanted... automatically tune hearthmind for
        specific hardware"): the real automatic cadence for Tier 5
        B13's `HypothesisLoop`, previously manual-only by deliberate
        design (see `self._llm_concurrency_hypothesis_loop`'s own
        docstring). Monthly, same cadence as `_maybe_refresh_machine_
        profile` — real hardware-adaptive maintenance, not a per-tick
        cost.

        Strictly gated so it can never fight `_maybe_tune_llm_
        concurrency`'s own live, daily `BangBangController` over the
        SAME `llm_max_concurrent` tunable — see `LLM_CONCURRENCY_AUTO_
        HYPOTHESIS_QUIET_DAYS`'s own docstring for the full reasoning.
        Skips outright if the LLM is disabled (nothing to measure), if
        a hypothesis run is already in flight, if no real `select_
        strategy` reading has ever been taken yet (`self._last_
        strategy`, refreshed daily by `_maybe_tune_llm_concurrency`),
        if the reactive controller has made a real change within the
        quiet window (checked directly against `self._adaptive_tuning_
        log`'s own real `tick` field — no separate cadence tracker
        needed), or if the hardware-derived hint already matches the
        current live value (nothing to genuinely test). The proposed
        value is always `select_strategy`'s own `llm_max_concurrent_
        hint` — a real signal (this machine's own measured core count/
        RAM/storage/LLM-throughput profile), never an arbitrary probe
        value — so this closes the loop `_maybe_tune_llm_concurrency`'s
        own docstring named as still open: the hint no longer only
        CAPS a fresh reactive increase, it's now periodically tested as
        a real candidate value in its own right."""
        if "month_end" not in events:
            return
        if not self._cognition_runner.enabled:
            return
        if self._llm_concurrency_hypothesis_running:
            return
        if self._last_strategy is None:
            return
        ticks_per_day = self.world.config.minutes_per_day // self.world.config.sim_minutes_per_tick
        quiet_ticks = LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS * ticks_per_day
        current_tick = self.world.clock.tick_count
        if self._adaptive_tuning_log and current_tick - self._adaptive_tuning_log[-1]["tick"] < quiet_ticks:
            return
        proposed_value = int(self._last_strategy.llm_max_concurrent_hint)
        current_value = int(self._tuning_registry.get("llm_max_concurrent").value)
        if proposed_value == current_value:
            return
        hypothesis = (
            f"automatic {LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS}-day quiet-period check: "
            f"does this host's own measured hardware profile (select_strategy's llm_max_concurrent_hint) "
            f"support a different concurrency than the latency controller last settled on?"
        )
        self._spawn_llm_concurrency_hypothesis(proposed_value, hypothesis, source="auto")

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
        favorite doesn't permanently lock out a fresher one.

        Tier 0 (23rd site, explicit user decision via `AskUserQuestion`
        — extends v1.34.9/v1.34.114's Phase G carve-out for this exact
        target-selection role): a genuine tie in view count breaks
        toward whichever tied agent `humans_pillar` already has a
        standing theory about — never changes WHETHER an intervention
        happens or what it says, only which equally-viewed agent it
        targets. Real view count stays the sole determinant otherwise."""
        attention = self.world.observer_attention
        counts = attention.get("agent_view_counts", {}) if attention else {}
        if not counts:
            return None
        core_ids = self.world.population.core_agent_ids
        by_id = {a.id: a for a in self.world.population.agents}
        ranked = sorted(
            counts,
            key=lambda aid: (counts[aid], self.world.humans_pillar.subject_confidence(
                by_id[aid].name) if aid in by_id else 0.0),
            reverse=True,
        )
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
        # Tier 0's thirteenth conversion (docs/ROADMAP-2026-07-
        # REMAINING.md): a third "who's the story about right now"
        # signal, reusing Humans pillar's already-proven per-agent-
        # name-keyed content (the same `subject_confidence(agent.name)`
        # match that `memory_drift`/`noncore_nudge`/`invention`/
        # `ontology_proposal`/`dream` already rely on) rather than
        # inventing anything new. Scoped to the core cast only, same
        # candidate pool `select_voice_pair` itself filters to — a
        # cheap, bounded scan, not O(population). Additive alongside
        # (never replacing) the inventor/council bonuses above; an
        # agent with no standing Humans theory contributes 0.0, a true
        # no-op for the common case.
        for agent_id in self.world.population.core_agent_ids:
            if agent_id not in alive_ids:
                continue
            agent = self.world.population.get(agent_id)
            if agent is None:
                continue
            lean = self.world.humans_pillar.subject_confidence(agent.name) * VOICE_NARRATIVE_HUMANS_LEAN_MAX
            if lean > 0.0:
                scores[agent_id] = scores.get(agent_id, 0.0) + lean
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
        self._dialogue_calls_today += 1  # Tier 7 G2's real workload-forecaster feature
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
        self._dialogue_calls_today += 1  # Tier 7 G2's real workload-forecaster feature
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
        if self._pillar_interpret_backpressured("village"):
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
            legends=list(settlement.legends),
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
            self._append_emergence(
                "opportunity", "narrative", f"The chronicle recorded: {summary}",
                ('village',),
            )

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
        if self._pillar_interpret_backpressured("village"):
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
            self._append_emergence(
                "opportunity", "narrative", f"The year in review: {narration}",
                ('village',),
            )

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
            self.world.village_pillar.remember(f"Asked \"{question}\" — {self.world.chronicler_answer}")
            self._append_emergence(
                "opportunity", "narrative", f"Asked \"{question}\" — {self.world.chronicler_answer}",
                ('village',),
            )

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

    PILLAR_INITIATE_CONFIDENCE_THRESHOLD = 0.75
    """C3 "pillars may initiate contact" (docs/ROADMAP-2026-07-
    REMAINING.md) — the one half of the player<->pillar chat feature
    v1.8.0 explicitly flagged as not attempted (only the player-
    initiated `/ask/{pillar}` direction shipped). Only a genuinely
    confident belief is worth a pillar volunteering unprompted — a
    fresh `hypothesis`-status entry stays private until it's actually
    been reasoned about enough to earn real confidence, same bar this
    codebase already uses elsewhere for "confident enough to act on"
    (e.g. `TRUST_SKEPTICISM_THRESHOLD`'s sibling reasoning)."""

    PILLAR_INITIATE_CHANCE_PER_MONTH = 0.3
    """Once a pillar has a qualifying belief, it doesn't announce it the
    very first month it crosses the confidence bar — a real independent
    roll each month keeps the timing from reading as a mechanical
    trigger, same "meaningful, never a certainty" shape `CARAVAN_
    CHANCE_PER_MONTH`/`FESTIVAL_CHANCE_PER_MONTH` already use."""

    def _maybe_pillar_initiates_contact(self, events: list[str]) -> None:
        """C3's other half: monthly, zero NEW LLM cost by construction
        — this only ever surfaces a belief a pillar's own real cognition
        has ALREADY formed (`Pillar.world_model`'s newest entry), never
        generates fresh text. The mechanism is entirely deterministic:
        WHETHER/WHEN a pillar volunteers a thought it already holds
        unprompted, not what it says. Deduped by `world_model_entry_id`
        (`Pillar.push_initiated_message`'s own docstring) so the same
        belief is never announced twice, even across many months of it
        staying the pillar's newest/most-confident entry."""
        if "month_end" not in events:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "pillar_initiate")
        for name in emergence.PILLARS:
            pillar = getattr(self.world, f"{name}_pillar")
            if not pillar.world_model:
                continue
            entry = pillar.world_model[-1]
            if entry.get("confidence", 0.0) < self.PILLAR_INITIATE_CONFIDENCE_THRESHOLD:
                continue
            if any(m.get("world_model_entry_id") == entry["id"] for m in pillar.initiated_messages):
                continue
            if rng.random() >= self.PILLAR_INITIATE_CHANCE_PER_MONTH:
                continue
            pillar.push_initiated_message(entry["subject"], entry["belief"], self.world.clock.tick_count, entry["id"])
            self._log("pillar_initiated", f"{name.capitalize()} wanted to tell you something: \"{entry['belief']}\"")

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
            self.world.village_pillar.remember(f"Looking back: {self.world.away_digest_text}")
            self._append_emergence(
                "opportunity", "narrative", f"Looking back: {self.world.away_digest_text}",
                ('village',),
            )

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
        if self._pillar_interpret_backpressured("village"):
            return
        self._mark_season_year_resolved("tradition")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        traditions = target.traditions
        prompt = culture.build_prompt(
            target.name, recent, traditions[-PROMPT_CULTURE_LIST_MAX:], self.world.clock.year,
            legends=list(target.legends),
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
            self.world.village_pillar.remember(f"Established a new tradition — {entry}")
            # Bug fix (v1.34.131): `_maybe_spread_tradition_keeping`'s
            # pillar-leaned pick (Tier 0's 35th site) reads `village_
            # pillar.subject_confidence(t)` for each FULL "{name}:
            # {description}" tradition string, but this apply() only
            # ever called `remember()` (memory-only) — `subject_
            # confidence` scans `world_model`, never `memory`, so the
            # lean had no real content to ever match against. A
            # `world_model` entry keyed by the bare tradition NAME
            # (a prefix of the full stored string, so the consumer's
            # substring check matches it) closes the gap — revised in
            # place if this exact tradition name is ever re-coined.
            existing_tradition_signal = self.world.village_pillar.find_world_model_entry(name)
            self.world.village_pillar.upsert_world_model(
                self.world.clock.tick_count, name, f"{settlement.name or 'the village'} holds to {name.lower()}.",
                0.5, status="observation", source="tradition",
                revises_id=existing_tradition_signal["id"] if existing_tradition_signal else None,
            )
            self._append_emergence(
                "novel_combination", "culture", f"Established a new tradition — {entry}",
                ('village',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a fourth Village->Humans arrow: a new tradition
            # is a real cultural fact shaping specific living people's
            # behavior, worth Humans' pillar knowing directly.
            self._send_pillar_message(
                "village", "humans", "observation", f"established a new tradition — {entry}",
            )

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
            # A21 third slice, "unify folklore/legend pipeline": a
            # month with literally nothing new to draw on is still a
            # month the village's current tale endured unchallenged —
            # see `_note_folklore_persistence`'s own docstring.
            self._note_folklore_persistence(target)
            return
        if self._pillar_interpret_backpressured("village"):
            return
        self._mark_monthly_resolved("folklore")
        existing_folklore = list(target.folklore)
        prompt = folklore.build_prompt(target.name, rumor_events, existing_folklore, legends=list(target.legends))
        fallback = folklore.fallback_folklore(target.name, rumor_events)
        target_id = target.id

        def apply(result: dict, used_fallback: bool) -> None:
            settlement = self._settlement_by_id(target_id)
            prior_tales = [e["tale"] for e in settlement.folklore]
            entry = folklore.parse_folklore(result, fallback, existing_tales=prior_tales)
            if entry is None:
                # Nothing worth telling this month, or a near-
                # restatement of an existing tale — the current
                # dominant tale endures another month unchallenged.
                self._note_folklore_persistence(settlement)
                return
            entry["tick"] = self.world.clock.tick_count
            settlement.folklore.append(entry)
            if len(settlement.folklore) > FOLKLORE_MAX_STORED:
                settlement.folklore = settlement.folklore[-FOLKLORE_MAX_STORED:]
            # A genuinely new tale supersedes whatever was enduring
            # before it — reset the persistence clock.
            settlement.folklore_persistence_count = 0
            settlement.folklore_persistence_promoted = False
            self._log("folklore", f"{settlement.name or 'The village'} now tells a new tale — {entry['tale']}")
            self.world.village_pillar.remember(f"A new tale is told — {entry['tale']}")
            self._append_emergence(
                "novel_combination", "culture", f"A new tale is told — {entry['tale']}",
                ('village',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a fifth Village->Humans arrow: a new tale
            # entering folklore is real cultural content about
            # specific events/people, worth Humans' pillar knowing
            # directly.
            self._send_pillar_message(
                "village", "humans", "observation", f"a new tale is told — {entry['tale']}",
            )

        self._schedule_llm_job(
            "folklore", prompt, folklore.SYSTEM_PROMPT, fallback, apply, settlement=target.name,
        )

    def _note_folklore_persistence(self, settlement: "Settlement") -> None:
        """A21 third slice (explicit user instruction, "unify folklore/
        legend pipeline"): folklore's rumor-condensation chain and
        `legends`' Emergence-API chain were two totally parallel
        mechanisms that never fed each other, despite this roadmap
        item's own spec literally naming their unification as the
        target. The real fold: a folk tale that keeps being retold
        (or, more precisely, that keeps NOT being superseded by
        something newer) across many months without new material is
        exactly what "temporal compression" describes — repetition
        without change is how a tale becomes a legend. Deterministic,
        zero LLM cost, called only from `_maybe_schedule_folklore`'s
        own two "nothing new this month" paths."""
        if not settlement.folklore:
            return  # nothing to endure yet
        settlement.folklore_persistence_count += 1
        if (
            settlement.folklore_persistence_count >= FOLKLORE_LEGEND_PERSISTENCE_THRESHOLD
            and not settlement.folklore_persistence_promoted
        ):
            self._promote_folklore_to_legend(settlement)

    def _promote_folklore_to_legend(self, settlement: "Settlement") -> None:
        """The deterministic promotion itself — no LLM call, since the
        tale's own wording is already settled; graduating it to
        `Settlement.legends` is a status change, not a new narration.
        Tagged `subsystem="folklore"` (distinct from any real Emergence
        API subsystem name) so `_maybe_schedule_legend_detection`'s own
        `already_legendary` set naturally leaves this lane alone."""
        tale_entry = settlement.folklore[-1]
        legend_entry = {
            "legend": tale_entry["tale"], "subsystem": "folklore",
            "tick": self.world.clock.tick_count,
        }
        settlement.legends.append(legend_entry)
        if len(settlement.legends) > LEGENDS_MAX_STORED:
            settlement.legends = settlement.legends[-LEGENDS_MAX_STORED:]
        settlement.folklore_persistence_promoted = True
        # Same pressure-gate feedback v1.34.54 wired for Emergence-
        # sourced legends — a folklore-sourced legend biases Innovation's
        # next proposal toward its own theme too, no separate mechanism.
        settlement.pattern_signal_counts["legend_folklore"] = PATTERN_SIGNAL_BELIEF_THRESHOLD
        detail = f"{settlement.name or 'The village'}'s own tale has endured long enough to become legend — {tale_entry['tale']}"
        self._log("legend_formed", detail)
        self.world.village_pillar.remember(detail)
        self._append_emergence("novel_combination", "culture", detail, ('village',))
        self._send_pillar_message("village", "humans", "observation", detail)

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
        if self._pillar_interpret_backpressured("village"):
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
            # A21 "Temporal compression": legend -> tradition/religion/
            # institution feedback. A legend forming is itself strong
            # evidence its theme is genuinely significant to the
            # village — reuses the EXISTING pattern-signal pressure gate
            # (`pattern_signal_counts`, already read by `_maybe_
            # schedule_ontology_proposal`'s "pressured" check and its
            # `pressure_signal` naming) rather than a new mechanism, so
            # a crystallized legend measurably biases what the village
            # invents/proposes next toward its own myth's own theme.
            # Namespaced `legend_` so it never collides with an
            # unrelated signal that happens to share the raw subsystem
            # name.
            settlement.pattern_signal_counts[f"legend_{subsystem}"] = PATTERN_SIGNAL_BELIEF_THRESHOLD
            self._log(
                "legend",
                f"{settlement.name or 'The village'} now speaks of a legend — {entry['legend']}",
            )
            self.world.village_pillar.remember(f"A legend has taken hold — {entry['legend']}")
            self._append_emergence(
                "novel_combination", "culture", f"A legend has taken hold — {entry['legend']}",
                ('village',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a new Village->Reflection arrow: a legend
            # crystallizing from a repeated same-subsystem pattern IS
            # literally what Reflection's own pattern detection cares
            # about — a naturally-occurring instance of the same kind
            # of signal, worth handing over directly.
            self._send_pillar_message(
                "village", "reflection", "observation", f"a legend has taken hold — {entry['legend']}",
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
        if self._pillar_interpret_backpressured("innovation"):
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
        # C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-
        # 2026-07-22.md's Part C, Tier 3): Innovation's own leading
        # open hypothesis, when it's genuinely confident (not every
        # half-formed hunch), measurably raises invention odds — the
        # first genuinely-new-mechanism C2 slice, distinct from every
        # Tier 0 lean (which only ever broke a tie, never changed
        # WHETHER a Body-affecting event happens at all). Applied
        # AFTER the prosperity gate above, never in place of it.
        leading_hypothesis = max(
            (e for e in self.world.innovation_pillar.world_model if e.get("status") == "hypothesis"),
            key=lambda e: e.get("confidence", 0.0), default=None,
        )
        hunch_used = None
        if (
            leading_hypothesis is not None
            and leading_hypothesis.get("confidence", 0.0) >= INNOVATION_HYPOTHESIS_CONFIDENCE_THRESHOLD
        ):
            chance = min(
                1.0, chance * (1.0 + leading_hypothesis["confidence"] * INNOVATION_HYPOTHESIS_INVENTION_BONUS_WEIGHT),
            )
            hunch_used = leading_hypothesis
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "invention_roll") >= chance:
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        inventions = settlement.inventions
        prompt = invention.build_prompt(
            settlement.name, recent, inventions[-PROMPT_CULTURE_LIST_MAX:], settlement.tech_level,
            beliefs=settlement.beliefs[-PROMPT_BELIEFS_MAX:],
            hunch=hunch_used["belief"] if hunch_used else None,
        )
        hunch_id_used = hunch_used["id"] if hunch_used else None
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
                # Tier 0 mirror-write -> pillar-authored conversion
                # (docs/ROADMAP-2026-07-REMAINING.md): who becomes
                # credited as the inventor is a real WHICH-candidate
                # pick, the same shape `institution_belief`/`memory_
                # drift`/`noncore_nudge` already convert — "the person
                # already notable in the community's own accumulated
                # sense of them" is a genuine, distinct lean toward
                # recognizing a real invention. An agent Humans pillar
                # has no standing theory about reads a flat 1.0.
                weights = [
                    1.0 + self.world.humans_pillar.subject_confidence(a.name) * INVENTOR_HUMANS_LEAN_WEIGHT
                    for a in candidates
                ]
                inventor = rng.choices(candidates, weights=weights, k=1)[0]
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
                origin_pillar="innovation",
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
            # C2 "Intention channel": if this attempt was genuinely
            # seeded by Innovation's own leading hypothesis (see the
            # scheduling site above), that hunch is now resolved — a
            # real invention followed from it, so it graduates from
            # `status="hypothesis"` to a confirmed observation in
            # place, closing the hypothesis -> action -> confirmation
            # loop rather than leaving the hunch to fade unresolved.
            if hunch_id_used is not None:
                resolved = next(
                    (e for e in self.world.innovation_pillar.world_model if e["id"] == hunch_id_used), None,
                )
                if resolved is not None and resolved.get("status") == "hypothesis":
                    self.world.innovation_pillar.upsert_world_model(
                        self.world.clock.tick_count, resolved["subject"],
                        f"{resolved['belief']} This hunch led to a real invention: {name}.",
                        1.0, status="observation", source="invention_hunch_confirmed",
                        revises_id=hunch_id_used,
                    )
            self.world.innovation_pillar.remember(f"Invented {name}: {description}")
            self._append_emergence(
                "novel_combination", "innovation", f"Invented {name}: {description}",
                ('innovation',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a new Innovation->Reflection arrow: a genuine
            # invention is real material for Reflection's own pattern
            # detection over Innovation's Body state, not just a
            # world_model entry it has to notice on its own.
            self._send_pillar_message(
                "innovation", "reflection", "discovery", f"invented {name}: {description}",
            )

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
        # abandon_stale immediately above. `run_selection`'s retirement
        # is correlational (adopter reputation vs. settlement average)
        # and stays immediate/synchronous, unchanged — see
        # `_confirm_concept_retirement` for the slower causal SECOND
        # opinion (the dual-fork check) that can reverse a retirement
        # this call makes, without altering this call itself.
        retired_before = {
            c.id for c in self.world.invented_concepts.values() if c.status == "retired"
        }
        ontology.run_selection(self.world, self.world.clock.tick_count)
        newly_retired = [
            c.id for c in self.world.invented_concepts.values()
            if c.status == "retired" and c.id not in retired_before
        ]
        for concept_id in newly_retired:
            self._confirm_concept_retirement(concept_id)
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
            # Tier 0 conversion (docs/ROADMAP-2026-07-REMAINING.md):
            # `max`'s tiebreak among equally-pressured signal categories
            # (a real, not rare, case — several counters commonly cross
            # the threshold the same month) previously fell to dict-
            # iteration order. Bug fix (v1.34.131): the first cut of
            # this conversion read `innovation_pillar`, but every real
            # producer of these exact keys (`dispute_feud`/`materials_
            # bottleneck`, see their own mirror sites) writes into
            # `village_pillar`, keyed by the LITERAL underscored
            # category string, not a space-separated label — reading
            # the wrong pillar with a `.replace()`'d subject meant this
            # tiebreak was a silent permanent no-op in production
            # despite passing a self-seeded unit test. Fixed to read
            # `village_pillar.subject_confidence(kv[0])` directly. The
            # real occurrence count is still the sole primary key and
            # is never overridden by it.
            top_signal, top_value = max(
                settlement.pattern_signal_counts.items(),
                key=lambda kv: (kv[1], self.world.village_pillar.subject_confidence(kv[0])),
            )
            if top_value >= PATTERN_SIGNAL_BELIEF_THRESHOLD:
                pressure_signal = top_signal
        # C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-
        # 2026-07-22.md's Part C, Tier 3, "set custom"): when the Body-
        # driven check above found no FRESH pressure this cycle,
        # village_pillar's own persisted conviction about one of laws.
        # py's hardship subjects can still genuinely FORCE this proposal
        # into being a "custom" — the informal, not-yet-codified sibling
        # of a law about the same lived hardship. Never overrides a
        # real, fresh occurrence count (only fills the gap when
        # `pressure_signal` is still `None`) — Body stays authoritative.
        custom_conviction_subject = None
        if pressure_signal is None:
            candidate_subject = max(
                self._LAW_PATTERN_TEXT,
                key=lambda s: self.world.village_pillar.subject_confidence(s), default=None,
            )
            if (
                candidate_subject is not None
                and self.world.village_pillar.subject_confidence(candidate_subject)
                >= VILLAGE_CUSTOM_CONVICTION_THRESHOLD
            ):
                pressure_signal = candidate_subject
                custom_conviction_subject = candidate_subject
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
        standing = [b for b in settlement.buildings if b.stage is BuildingStage.STANDING]
        # A13's second slice (the real automatic reactor) means an
        # individual building's material can now genuinely differ from
        # its kind's default — reading per-INSTANCE affordances/
        # material (`building_instance_affordances`/`effective_
        # material_name`) rather than always the per-kind default keeps
        # this query honest about a converted building (e.g. a fired
        # ceramic SHRINE), not just its original clay state.
        present_tags: set[str] = set()
        for b in standing:
            present_tags |= building_instance_affordances(b)
        discoverable = discover_combinations(present_tags)
        # A13 "Chemistry / reaction system" (roadmap Stage IV step 20):
        # what a genuinely available material would produce under a
        # genuinely available condition — real materials from A12's
        # `BUILDING_MATERIALS`, real conditions derived from the same
        # affordance layer step 18/19 already computed above.
        present_materials = {
            name for b in standing if (name := effective_material_name(b)) is not None
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
            # A6's validate-step half (Tier 3 item 17): re-verify a
            # claimed invention_specialization_category against the
            # SAME present_tags already computed above for the
            # generate-step's grounding — a closure capture, not a
            # second query.
            parsed = ontology_llm.parse_propose(result, fallback, present_tags=present_tags)
            # C2 "Intention channel": village_pillar's own conviction
            # (see the scheduling site above) FORCES this proposal into
            # a "custom" — overriding whatever category the LLM itself
            # picked, the real intention rather than a mere hint via the
            # prompt's grounding text.
            if custom_conviction_subject is not None:
                parsed["category"] = "custom"
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
                # Tier 0's inventor-selection conversion, second real
                # instance (same shape as `invention`'s own site above —
                # C4's "give a pattern a second instance" precedent).
                weights = [
                    1.0 + self.world.humans_pillar.subject_confidence(a.name) * INVENTOR_HUMANS_LEAN_WEIGHT
                    for a in candidates
                ]
                inventor_id = rng.choices(candidates, weights=weights, k=1)[0].id
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
            # Humans-vs-Village ontology origination split (explicit
            # user delegation, 2026-07-31 — see `ontology_llm.origin_
            # pillar_for_category`'s docstring for the full rationale):
            # a genuine per-concept attribution, not just prompt
            # wording. Innovation's own mirror above is untouched
            # either way (Innovation still authors/discovers every
            # concept through this job's machinery) — this is a SECOND,
            # additional real signal for whichever pillar is actually
            # credited with caring about the idea.
            origin_pillar = ontology_llm.origin_pillar_for_category(parsed["category"])
            concept = ontology.register_concept(
                self.world, name=parsed["name"], description=parsed["description"], category=parsed["category"],
                origin_settlement_id=settlement_id, tick=self.world.clock.tick_count,
                inventor_agent_id=inventor_id, mechanical_hook=parsed["hook"],
                hypothesis=parsed["hypothesis"], world_model_entry_id=entry["id"],
                origin_pillar=origin_pillar,
            )
            if origin_pillar == "humans":
                self.world.humans_pillar.upsert_world_model(
                    self.world.clock.tick_count, parsed["name"], parsed["description"], 0.4,
                    source="ontology_proposal_humans_origin",
                )
                self.world.humans_pillar.remember(f"The people themselves gave rise to {concept.name}: {concept.description}")
            self._log("ontology", f"{target.name or 'The village'} originated {concept.name}: {concept.description}")
            # C2 "Intention channel": if this custom was genuinely
            # FORCED by village_pillar's own conviction, that conviction
            # is now confirmed — a real custom followed from it, so its
            # own mirror entry is reinforced to full confidence in
            # place, closing the conviction -> action -> confirmation
            # loop the same way every other C2 slice does.
            if custom_conviction_subject is not None:
                conviction_entry = self.world.village_pillar.find_world_model_entry(custom_conviction_subject)
                if conviction_entry is not None:
                    self.world.village_pillar.upsert_world_model(
                        self.world.clock.tick_count, custom_conviction_subject, conviction_entry["belief"], 1.0,
                        status="observation", source="custom_conviction_confirmed",
                        revises_id=conviction_entry["id"],
                    )
            self.world.innovation_pillar.remember(f"Originated {concept.name}: {concept.description}")
            self._append_emergence(
                "novel_combination", "innovation", f"Originated {concept.name}: {concept.description}",
                ('innovation',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), the Innovation->Village arrow: a newly
            # registered concept is real news for the village that
            # will go on to adopt (or ignore) it. Tier 3 item 23
            # ("reverse-direction disagreement classification"): the
            # Nature->Village arrow has always checked whether the
            # RECEIVER already holds a confident opposing theory about
            # the recognizably same subject; the four Innovation-
            # >Village discovery arrows never did, defaulting to a flat
            # "discovery" tag even when Village already believes
            # something that contradicts the new concept. Same
            # mechanical `disagrees_with` check, applied here for the
            # first time.
            message_kind = "disagreement" if self.world.village_pillar.disagrees_with(concept.name) else "discovery"
            self._send_pillar_message(
                "innovation", "village", message_kind,
                f"the village now has {concept.name}: {concept.description}",
            )
            self._pillar_close_cycle("innovation")

        self._schedule_llm_job(
            "ontology_proposal", prompt, ontology_llm.SYSTEM_PROMPT_PROPOSE, fallback, apply,
            deep_reasoning=True, num_predict_mult=LARGE_SCHEMA_REASONING_NUM_PREDICT_MULT,
        )

    def _confirm_concept_retirement(self, concept_id: int) -> None:
        """A8's comparative dual-fork (roadmap Stage IV step 21,
        explicit user instruction "Take dual fork of A8" following the
        v1.34.84 audit that found a naive sandbox-as-acceptance-gate
        approach would be vacuous — `InventedConcept.mechanical_hook`
        is never consumed as a numeric effect). `run_selection`'s own
        retirement (correlational: adopter reputation vs. settlement
        average) fires synchronously and is left completely unchanged
        by this — this schedules a slower, genuinely causal SECOND
        opinion (`simulation.sandbox.evaluate_concept_dual_fork`,
        with-vs-without-this-concept's-adopters, same shared-RNG-fork
        reasoning that makes the delta meaningful rather than noise —
        see that function's own docstring) that can reverse the
        retirement after the fact if it disagrees.

        Fire-and-forget background task, same `_background_tasks`
        lifecycle every other sandboxed proposal (`rule_propose`,
        `composite_reaction_propose`) already uses. A positive delta
        (the settlement is genuinely worse off, population-wise,
        without this concept's real adopters) reinstates; zero or
        negative doesn't — `run_selection`'s correlational verdict
        stands unless the causal check actively contradicts it."""
        async def _dual_fork_and_maybe_reinstate() -> None:
            delta = await evaluate_concept_dual_fork(self.world, self.world.config, concept_id)
            if delta is None or delta <= 0:
                return
            concept = ontology.reinstate_concept(self.world, concept_id, self.world.clock.tick_count)
            if concept is None:
                return
            self._log(
                "ontology_reinstated",
                f"{concept.name} was retired but a causal dual-fork check found the settlement measurably "
                f"worse off without its adopters (population delta {delta:+.0f}) — reinstated.",
            )
            self.world.innovation_pillar.remember(
                f"{concept.name} was retired, then reinstated once a deeper causal check "
                "showed real harm from losing it."
            )
            self._append_emergence(
                "opportunity", "innovation",
                f"{concept.name} was reinstated after a causal dual-fork check found real harm in its loss",
                ('innovation',),
            )

        task = asyncio.create_task(_dual_fork_and_maybe_reinstate())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
        if self._pillar_interpret_backpressured("innovation"):
            return
        self._mark_season_year_resolved("ontology_evolution")
        # A8 "Evolutionary Innovation" (roadmap Stage IV step 21)'s
        # *select* step: draw from the fitness-weighted pool, not a
        # flat uniform choice among every established concept — a
        # concept with a real positive fitness reading is genuinely
        # more likely to become a parent (see `ontology.concept_
        # fitness_weight`'s docstring for why an un-evaluated or
        # mildly-below-average concept still gets a real, non-zero
        # chance). Tier 0's fourth mirror-write -> pillar-authored
        # conversion (docs/ROADMAP-2026-07-REMAINING.md): each
        # candidate's weight also folds in `innovation_pillar.subject_
        # confidence(c.name)` as a bounded multiplier on top of
        # fitness — see `ontology.INNOVATION_EVOLUTION_LEAN_WEIGHT`'s
        # docstring for why this is a real, distinct signal from
        # fitness, not a duplicate of it.
        established = ontology.fit_established_concepts(self.world)
        if not established:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "ontology_evolution_pick")
        do_merge = len(established) >= 2 and rng.random() < 0.5

        def weighted_pick(count: int) -> list:
            pool = list(established)
            picked = []
            for _ in range(min(count, len(pool))):
                weights = [
                    ontology.concept_fitness_weight(
                        c, pillar_lean=self.world.innovation_pillar.subject_confidence(c.name),
                    )
                    for c in pool
                ]
                choice = rng.choices(pool, weights=weights, k=1)[0]
                picked.append(choice)
                pool.remove(choice)
            return picked

        settlement = self._settlement_by_id(established[0].origin_settlement_id) or self._job_target()
        if do_merge:
            a, b = weighted_pick(2)
            # A16 "tech-as-DAG" (docs/ROADMAP-2026-07-REMAINING.md): a real
            # traversal over the lineage DAG, not just its single-hop parent
            # pointers — reject a merge pair that's already kin (one an
            # ancestor of the other, or a shared common ancestor), the
            # degenerate "the idea absorbs itself" case that was previously
            # entirely unguarded. Retried a bounded few times against the
            # weighted pool before giving up and merging the original pair
            # anyway (a real, if unlikely, small settlement may have no
            # unrelated established concept at all).
            attempts = 0
            while graph_algorithms.shares_lineage(self.world, a.id, b.id) and attempts < 4:
                a, b = weighted_pick(2)
                attempts += 1
            prompt = ontology_llm.build_merge_prompt(a.name, a.description, b.name, b.description, settlement.name or "The village")
            fallback = ontology_llm.fallback_merge(a.name, b.name)
            system_prompt = ontology_llm.SYSTEM_PROMPT_MERGE
            parent_ids = [a.id, b.id]
            category, hook, origin_settlement_id = a.category, a.mechanical_hook, a.origin_settlement_id
            child_generation = max(a.generation, b.generation) + 1

            def apply(result: dict, used_fallback: bool) -> None:
                name, description, hypothesis = ontology_llm.parse_merge(result, fallback)
                if ontology.is_near_duplicate(self.world, name, description):
                    return
                # B5 "Innovation as conscious scientist" follow-up (Tier 2
                # item 15): extends the hypothesize -> observe -> revise
                # loop `ontology_proposal` already closes to `merge` too
                # — same shape as that job's own mirror-then-register
                # order, so `world.ontology._record_hypothesis_outcome`
                # can later revise this SAME entry once the merged
                # concept's own real adoption fate (established/
                # abandoned/retired) confirms or refutes it. An empty
                # `hypothesis` ("just a natural pairing," the common
                # case) is a legitimate answer that no-ops the later
                # revision via that function's own guard.
                entry = self.world.innovation_pillar.upsert_world_model(
                    self.world.clock.tick_count, name, description, 0.4, source="ontology_evolution",
                )
                concept = ontology.register_concept(
                    self.world, name=name, description=description, category=category,
                    origin_settlement_id=origin_settlement_id, tick=self.world.clock.tick_count,
                    mechanical_hook=hook, lineage={"merged_from": parent_ids}, generation=child_generation,
                    hypothesis=hypothesis, world_model_entry_id=entry["id"],
                )
                self._log("ontology", f"Two ideas combined into {concept.name}: {concept.description}")
                self.world.innovation_pillar.remember(f"Combined two ideas into {name}: {description}")
                self._append_emergence(
                    "novel_combination", "innovation", f"Combined two ideas into {name}: {description}",
                    ('innovation',),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage
                # III step 11), a fourth Innovation->Village arrow: a
                # genuinely new merged concept is real discovery
                # material, same treatment ontology_proposal's existing
                # Innovation->Village arrow already gets — including,
                # as of Tier 3 item 23, the same reverse-direction
                # disagreement check.
                message_kind = "disagreement" if self.world.village_pillar.disagrees_with(name) else "discovery"
                self._send_pillar_message(
                    "innovation", "village", message_kind, f"combined two ideas into {name}: {description}",
                )
        else:
            parent = weighted_pick(1)[0]
            prompt = ontology_llm.build_evolve_prompt(parent.name, parent.description, settlement.name or "The village", [])
            fallback = ontology_llm.fallback_evolve(parent.name)
            system_prompt = ontology_llm.SYSTEM_PROMPT_EVOLVE
            parent_id = parent.id
            category, hook, origin_settlement_id = parent.category, parent.mechanical_hook, parent.origin_settlement_id
            child_generation = parent.generation + 1

            def apply(result: dict, used_fallback: bool) -> None:
                name, description, hypothesis = ontology_llm.parse_evolve(result, fallback)
                if ontology.is_near_duplicate(self.world, name, description):
                    return
                # B5 follow-up (Tier 2 item 15) — see the merge branch's
                # matching comment above for the full rationale; same
                # mirror-then-register order and empty-hypothesis
                # discipline, applied to `evolve` instead of `merge`.
                entry = self.world.innovation_pillar.upsert_world_model(
                    self.world.clock.tick_count, name, description, 0.4, source="ontology_evolution",
                )
                concept = ontology.register_concept(
                    self.world, name=name, description=description, category=category,
                    origin_settlement_id=origin_settlement_id, tick=self.world.clock.tick_count,
                    mechanical_hook=hook, lineage={"evolved_from": parent_id}, generation=child_generation,
                    hypothesis=hypothesis, world_model_entry_id=entry["id"],
                )
                self._log("ontology", f"An old idea evolved into {concept.name}: {concept.description}")
                self.world.innovation_pillar.remember(f"An old idea evolved into {name}: {description}")
                self._append_emergence(
                    "novel_combination", "innovation", f"An old idea evolved into {name}: {description}",
                    ('innovation',),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage
                # III step 11), a fifth Innovation->Village arrow: a
                # genuinely evolved concept is real discovery material,
                # same treatment ontology_proposal's existing arrow
                # already gets — including Tier 3 item 23's reverse-
                # direction disagreement check.
                message_kind = "disagreement" if self.world.village_pillar.disagrees_with(name) else "discovery"
                self._send_pillar_message(
                    "innovation", "village", message_kind, f"an old idea evolved into {name}: {description}",
                )

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
        if self._pillar_interpret_backpressured("innovation"):
            return
        self._mark_season_year_resolved("composite_entity")
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        event_description = recent[0]["description"] if recent else "The village has simply endured, season after season."
        existing_names = [e.name for e in self.world.composite_entities.values()]
        # Closing A19 ("places as actors"): ground the origin story in
        # what this SPECIFIC tile itself remembers, not just the
        # settlement-wide latest event — the first real consumer of
        # `location_character` beyond bare build-site scoring.
        location_history = spatial_memory.location_character_text(
            spatial_memory.location_character(self.world, building.x, building.y)
        )
        prompt = composite_entity.build_prompt(
            settlement.name, building.kind.value, event_description, existing_names,
            location_history=location_history,
        )
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
            # Observe/interpret cycling, first slice: also feeds the
            # Emergence API so Innovation's own observe turn can notice
            # this on its own next cycle, not just have it written
            # directly into world_model.
            self._append_emergence(
                "novel_combination", "innovation",
                f"{target.name or 'The village'} named {parsed['name']} — {parsed['origin_story']}",
                ("innovation",),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a sixth Innovation->Village arrow: a named
            # composite entity is a real civic landmark backed by a
            # genuinely new concept — worth Village's pillar knowing
            # directly.
            self._send_pillar_message(
                "innovation", "village", "discovery",
                f"{target.name or 'the village'} now knows this place as {parsed['name']} — {parsed['origin_story']}",
            )

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

    def _reactive_pillar_backpressured(self, pillar_name: str, trigger_key: str) -> bool:
        """Same check as `_pillar_interpret_backpressured`, wrapped with
        a short cooldown for triggers that are (unlike every cadence-
        gated settlement job) polled UNCONDITIONALLY every tick while
        their own anomaly persists — see `REACTIVE_TRIGGER_
        BACKPRESSURE_RETRY_TICKS`'s docstring for the live-diagnostic
        evidence this closes. While backed off, returns True WITHOUT
        touching `calls_dropped_backpressure` — the counter should
        reflect genuinely distinct attempts, not the same still-
        saturated queue re-observed every tick. `trigger_key` is a
        short, stable string identifying the caller (e.g. `"predator_
        extinction"`) — must be unique per reactive trigger, shared
        across a pillar's several triggers only if they should share
        one backoff clock (none currently do)."""
        tick = self.world.clock.tick_count
        if tick < self._reactive_trigger_next_retry_tick.get(trigger_key, 0):
            return True
        if self._pillar_interpret_backpressured(pillar_name):
            self._reactive_trigger_next_retry_tick[trigger_key] = tick + REACTIVE_TRIGGER_BACKPRESSURE_RETRY_TICKS
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
                self._append_emergence(
                    "opportunity", "ecology", f"Came to sense {entry['subject']}: {entry['belief']}",
                    ('nature',),
                )
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
                # Tier 0, new producer: the mirror above is real, but
                # it's keyed by Nature's own free-text belief subject
                # (e.g. "the vanished predator packs") inside `nature_
                # pillar` — `_maybe_schedule_ontology_proposal`'s
                # tiebreak reads `village_pillar.subject_confidence
                # ("nature_adaptation")` (the literal counter key), a
                # different pillar AND a different subject, so it never
                # matched. A second, literal-key mirror into `village_
                # pillar` (this counter's own real home) closes it,
                # same shape `_bump_village_pattern_signal` already
                # established for starvation_death/disease_outbreak/
                # wildlife_recolonization.
                self._bump_village_pattern_signal(
                    "nature_adaptation", f"{origin_settlement.name or 'the village'} keeps seeing the land itself change.",
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
                    origin_pillar="nature",
                )
                self._log("ontology", f"The land itself gave rise to {concept.name}: {concept.description}")
            # Tier 0's species-keyed theory producer (docs/ROADMAP-
            # 2026-07-REMAINING.md, v1.34.107, explicit user-approved
            # design): Nature's real `world_model` content is otherwise
            # free text ("the hunting grounds", "the abandoned fields")
            # that never reliably matches a WHICH-candidate site's own
            # subject vocabulary — the same fragile-dead-end shape
            # Humans hit before v1.34.98's real per-agent producer.
            # This mirrors a SECOND, deterministic entry (computed from
            # `wildlife_summary`, already read above — never the LLM's
            # own free-text answer) keyed by the literal species word
            # whenever that species is under genuine real pressure,
            # revised in place across repeated firings via `find_
            # world_model_entry` rather than piling up near-duplicates.
            # Real consumer: `_maybe_schedule_species_variant`'s herd-
            # candidate ordering, below.
            if wildlife_summary.get("prey_scarce"):
                existing = self.world.nature_pillar.find_world_model_entry("grazer")
                self.world.nature_pillar.upsert_world_model(
                    tick, "grazer", "The grazing herds are under real, lately-measured pressure.",
                    0.6, status="observation", source="nature_mind",
                    revises_id=existing["id"] if existing else None,
                )
            if wildlife_summary.get("predator_pressure_ratio", 0.0) > 0.25:
                existing = self.world.nature_pillar.find_world_model_entry("predator")
                self.world.nature_pillar.upsert_world_model(
                    tick, "predator", "The predator packs are pressing harder than usual right now.",
                    0.6, status="observation", source="nature_mind",
                    revises_id=existing["id"] if existing else None,
                )
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
        pass, see `wildlife.SPECIES_VARIANT_TRAITS`'s docstring.

        Tier 0's twelfth conversion (docs/ROADMAP-2026-07-REMAINING.md,
        v1.34.107), Nature pillar's first-ever site: the herd pick
        below used to be flatly deterministic (always the lowest id) —
        now sorted by `nature_pillar.subject_confidence(herd.species.
        value)` first (descending), lowest id as the tiebreak. Nature's
        `world_model` only carries a species-keyed entry
        (`"grazer"`/`"predator"`) when `_maybe_schedule_nature_mind`'s
        own deterministic mirror wrote one — see that method's apply()
        — so with no lean anywhere (the common case) every candidate
        reads confidence 0.0 and this reproduces the exact prior
        lowest-id pick byte-for-byte."""
        if not self._season_year_gate(events, "species_variant", "year_end"):
            return
        named_herd_ids = {v.herd_id for v in self.world.species_variants.values()}
        candidates = [h for h in self.world.wildlife.herds.values() if h.id not in named_herd_ids]
        if not candidates:
            return
        herd = min(
            candidates,
            key=lambda h: (-self.world.nature_pillar.subject_confidence(h.species.value), h.id),
        )
        if self._pillar_interpret_backpressured("nature"):
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
            # A15: bridges this LLM-authored trait to the real numeric
            # gene it names — the specific gap SPECIES_VARIANT_TRAITS'
            # own docstring used to flag. Only "hardier" has a matching
            # real gene today; the other four traits stay descriptive.
            if parsed["trait"] == "hardier":
                herd = self.world.wildlife.herds.get(herd_id)
                if herd is not None:
                    herd.hardiness = min(1.0, herd.hardiness + HARDINESS_VARIANT_BUMP)
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
            # Observe/interpret cycling, first slice: also feeds the
            # Emergence API so Nature's own observe turn can notice
            # this on its own next cycle.
            self._append_emergence(
                "novel_combination", "ecology", f"The land gave rise to {variant.name} — {variant.description}",
                ("nature",),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a new Nature->Innovation arrow: a genuinely new
            # natural variant is real grounding material for what
            # Innovation might notice/build on next.
            self._send_pillar_message(
                "nature", "innovation", "observation",
                f"the land gave rise to {variant.name}: {variant.description}",
            )

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
        # Tier 5 B4.2 second pilot: a "forgotten idea" (see `_update_
        # idea_dormancy`) is excluded from the per-tick roll list —
        # falls back to the full list if every growing concept happens
        # to be asleep at once (dormancy narrows attention, it never
        # silently disables the job, same fallback shape `_institution_
        # job_target` uses).
        awake = [c for c in growing if self._idea_dormancy.is_scheduled(str(c.id))]
        if awake:
            growing = awake
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

    def _maybe_spread_tradition_keeping(self) -> None:
        """A17 follow-up (docs/ROADMAP-2026-07-REMAINING.md, "Information
        ecosystem unification") — `world/memetics.py`'s SECOND real
        production consumer, following the same "candidates weighted by
        social-graph closeness to existing carriers" shape `_maybe_
        spread_concepts` established, over a genuinely new content type:
        a `Settlement.traditions` entry existing is not the same thing as
        anyone actually LIVING by it — `Agent.kept_traditions` is that
        missing personal layer. Zero LLM cost, deliberately rare (see
        `TRADITION_KEEPING_SPREAD_CHANCE_PER_TICK`)."""
        named_with_traditions = [s for s in self.world.settlements if s.name and s.traditions]
        if not named_with_traditions:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "tradition_keeping_spread")
        for settlement in named_with_traditions:
            if rng.random() >= TRADITION_KEEPING_SPREAD_CHANCE_PER_TICK:
                continue
            # Tier 5 B4.2 third pilot: a "forgotten tradition" (see
            # `_update_tradition_dormancy`) is excluded from this
            # settlement's own weighted candidate pool — falls back to
            # the full list if every one of this settlement's own
            # traditions happens to be asleep at once (dormancy narrows
            # attention, it never silently disables the job, same
            # fallback shape `_maybe_spread_concepts` uses).
            candidate_traditions = [
                t for t in settlement.traditions
                if self._tradition_dormancy.is_scheduled(_tradition_dormancy_key(settlement, t))
            ]
            if not candidate_traditions:
                candidate_traditions = settlement.traditions
            weights = [
                1.0 + self.world.village_pillar.subject_confidence(t) * TRADITION_PILLAR_LEAN_WEIGHT
                for t in candidate_traditions
            ]
            tradition = rng.choices(candidate_traditions, weights=weights, k=1)[0]
            candidates = [
                a for a in self.world.population.agents
                if a.settlement_id == settlement.id and tradition not in a.kept_traditions
            ]
            if not candidates:
                continue
            # Carriers already keeping this SPECIFIC tradition — a
            # candidate close to an existing keeper is more likely to
            # take it up next. Empty carriers (this tradition's very
            # first personal keeper) degrades to uniform via memetics'
            # own baseline weight.
            carriers = [
                a for a in self.world.population.agents
                if a.settlement_id == settlement.id and tradition in a.kept_traditions
            ]
            chosen = memetics.weighted_spread_target(candidates, carriers, rng)
            chosen.kept_traditions.append(tradition)
            if len(chosen.kept_traditions) > KEPT_TRADITIONS_CAP:
                del chosen.kept_traditions[0]

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
            feuding_pairs = [
                (fam_a, fam_b)
                for fam_a in families for fam_b in families
                if fam_a.id < fam_b.id and Population.families_feuding(fam_a, fam_b)
            ]
            if not feuding_pairs:
                feuding_pair = None
            elif len(feuding_pairs) == 1:
                feuding_pair = feuding_pairs[0]
            else:
                # Tier 0 (26th site): more than one settlement-wide
                # feuding family pair is rare, but when it happens,
                # village_pillar's own attention (never a real priority
                # signal here — there isn't one — so this is a genuine
                # first-max-wins pick, same shape as several earlier
                # sites) decides which pair the composite reaction's
                # relationship_rupture effect actually lands on. The
                # pillar lookup only ever runs against this small,
                # already-computed candidate set, never every tick's
                # common single-or-zero-pair case.
                feuding_pair = max(
                    feuding_pairs,
                    key=lambda p: (
                        self.world.village_pillar.subject_confidence(p[0].name)
                        + self.world.village_pillar.subject_confidence(p[1].name)
                    ),
                )
            active: set[str] = set()
            if drought_now:
                active.add("drought")
            if food_shortage_now:
                active.add("food_shortage")
            if feuding_pair is not None:
                active.add("feud")
            for reaction in reactions.matching_reactions(active, self.world.composite_reactions.values()):
                key = (settlement.id, reaction.name)
                last_fired = self._composite_reaction_last_fired.get(key)
                if last_fired is not None and now - last_fired < reactions.COMPOSITE_REACTION_COOLDOWN_TICKS:
                    continue
                self._composite_reaction_last_fired[key] = now
                reaction.fire_count += 1
                reaction.last_fired_tick = now
                self._apply_composite_reaction(reaction, settlement, feuding_pair)

    def _apply_composite_reaction(self, reaction, settlement, feuding_pair) -> None:
        """The real consequence: `"relationship_rupture"` (the original
        hand-authored "Desperate Times" reaction's own bespoke effect —
        escalates the feuding pair's relationship, a bounded, immediate
        step, not a new combat/raid mechanic, see `world/reactions.py`'s
        module docstring) needs `feuding_pair` non-None; every OTHER
        `hook_type` (A18's second slice — village-proposed reactions,
        `world.ontology.MECHANICAL_HOOK_TYPES`) goes through the SAME
        general consumer `TriggerRule` already uses, `_apply_trigger_
        rule_hook`, rather than a second bespoke effect system."""
        detail = f"{settlement.name or 'The village'}: {reaction.description}"
        self._log("composite_reaction", detail)
        self._append_highlight("composite_reaction", detail)
        self._append_emergence(
            "unexplained_shift", "village", detail,
            pillars=("village", "humans"), settlement=settlement.name,
            data={"reaction": reaction.name, "conditions": sorted(reaction.conditions)},
        )
        if reaction.hook_type == "relationship_rupture":
            if feuding_pair is None:
                return
            fam_a, fam_b = feuding_pair
            members_a = [a for a in self.world.population.agents if a.id in fam_a.member_agent_ids]
            members_b = [a for a in self.world.population.agents if a.id in fam_b.member_agent_ids]
            for a in members_a:
                for b in members_b:
                    a.relationships[b.id] = clamp(
                        a.relationships.get(b.id, 0.0) - reaction.magnitude, -1.0, 1.0,
                    )
                    b.relationships[a.id] = clamp(
                        b.relationships.get(a.id, 0.0) - reaction.magnitude, -1.0, 1.0,
                    )
        elif reaction.hook_type:
            self._apply_trigger_rule_hook(reaction.hook_type, reaction.magnitude, settlement)

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
        if self._pillar_interpret_backpressured("village"):
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
        # Tier 0 (21st site): a tie in objective_ticks_unmet breaks
        # toward whichever institution village_pillar already has a
        # standing theory about — never overrides the real primary
        # signal, only a tiebreak among equally-stuck institutions.
        stuck_institution = max(
            (i for i in settlement.institutions if i.objective_ticks_unmet >= institutions.INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD),
            key=lambda i: (i.objective_ticks_unmet, self.world.village_pillar.subject_confidence(i.name)),
            default=None,
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
                self._append_emergence(
                    "opportunity", "institution", f"Adopted a new rule: {rule.name} — {rule.description}",
                    ('village',),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage III
                # step 11), a new Village->Reflection arrow: a rule that
                # survived the counterfactual sandbox and went live is
                # exactly the kind of real self-modification event
                # Reflection's meta-cognition should observe directly,
                # not just notice secondhand via the Emergence stream.
                self._send_pillar_message(
                    "village", "reflection", "observation",
                    f"adopted a new rule: {rule.name} — {rule.description}",
                )

            task = asyncio.create_task(_sandbox_and_register())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # The game learning/improving itself: a self-modifying trigger
        # rule is exactly the kind of proposal that should be reasoned
        # through, not narrated (v1.3.37).
        self._schedule_llm_job(
            "rule_propose", prompt, rule_propose.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True,
            num_predict_mult=RULE_PROPOSE_NUM_PREDICT_MULT,
        )

    def _maybe_schedule_composite_reaction_propose(self, events: list[str]) -> None:
        """A18's second slice (docs/ROADMAP-2026-07-REMAINING.md,
        explicit user instruction "Start A18"): the real authoring
        system a village needs to propose its OWN `CompositeReaction`
        combinations, mirroring `_maybe_schedule_rule_proposal` almost
        exactly — same season cadence, same village-pillar backpressure
        gate, same counterfactual-sandbox-before-registration safety
        gate, same deep-reasoning genuine self-modification treatment.
        `critical=False`: ambient village imagination, same tier as
        `rule_propose` itself — the sandbox is the real safety gate."""
        if not self._season_year_gate(events, "composite_reaction_propose", "season_end"):
            return
        if self._pillar_interpret_backpressured("village"):
            return
        self._mark_season_year_resolved("composite_reaction_propose")
        # C4's runtime acceptance auditor (Tier 2 item 16): same "run it
        # on this job's own gated cadence" precedent as rule_propose's
        # own ontology.retire_stale_rules call.
        reactions.retire_stale_composite_reactions(self.world, self.world.clock.tick_count)
        settlement = self._job_target()
        if not settlement.name:
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        existing_condition_sets = [
            ", ".join(sorted(r.conditions)) for r in self.world.composite_reactions.values()
        ]
        prompt = composite_reaction_propose.build_prompt(settlement.name, recent, existing_condition_sets)
        fallback = composite_reaction_propose.fallback_propose(len(self.world.composite_reactions))
        origin_settlement_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = composite_reaction_propose.parse_propose(result, fallback)
            target = self._settlement_by_id(origin_settlement_id)
            if target is None:
                return
            if not reactions.validate_conditions(set(parsed["conditions"])):
                return

            async def _sandbox_and_register() -> None:
                # Same discipline as rule_propose's item 1.3: never let
                # a proposed reaction go live without first proving it
                # doesn't crash the population on a disposable fork.
                verdict = await run_counterfactual(self.world, self.world.config)
                if not verdict["safe"]:
                    self._log(
                        "composite_reaction_rejected",
                        f"A proposed composite reaction ({parsed['name']}) was discarded by the "
                        f"counterfactual sandbox: {verdict['reason']}.",
                    )
                    return
                reaction = reactions.register_composite_reaction(
                    self.world, name=parsed["name"], conditions=frozenset(parsed["conditions"]),
                    description=parsed["description"], hook_type=parsed["hook_type"],
                    hook_target=parsed["hook_target"], magnitude=parsed["magnitude"],
                    origin_settlement_id=origin_settlement_id, tick=self.world.clock.tick_count,
                )
                condition_text = " + ".join(sorted(reaction.conditions))
                message = (
                    f"{target.name or 'The village'} imagined a new composite reaction: "
                    f"{reaction.name} (when {condition_text} coincide) — {reaction.description}"
                )
                self._log("composite_reaction_originated", message)
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, reaction.name, reaction.description, 1.0,
                    status="observation", source="composite_reaction_propose",
                )
                self.world.village_pillar.remember(
                    f"Imagined a new composite reaction: {reaction.name} — {reaction.description}"
                )
                self._append_emergence(
                    "opportunity", "village", message, ("village", "reflection"),
                    settlement=target.name, data={"reaction": reaction.name, "conditions": condition_text},
                )
                # B4 arrow, same Village->Reflection precedent rule_
                # propose's own registration established: a reaction
                # that survived the sandbox and went live is a real
                # self-modification event worth Reflection's attention.
                self._send_pillar_message(
                    "village", "reflection", "observation",
                    f"imagined a new composite reaction: {reaction.name} — {reaction.description}",
                )

            task = asyncio.create_task(_sandbox_and_register())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        self._schedule_llm_job(
            "composite_reaction_propose", prompt, composite_reaction_propose.SYSTEM_PROMPT, fallback, apply,
            deep_reasoning=True,
        )

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
        pillar_leans = {
            b: self.world.innovation_pillar.subject_confidence(b) for b in era_branch.ERA_BRANCH_KIND_WEIGHTS
        }
        branch, scores = era_branch.compute_branch(settlement, rng, pillar_leans)
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
            # Tier 0 new-producer conversion (docs/ROADMAP-2026-07-
            # REMAINING.md): this job's OWN `pillar_lean` read at the
            # scheduling site above (`compute_branch`'s tiebreak, see
            # `_maybe_schedule_era_branch`) keys off the literal branch
            # name ("industrious"/"scholarly"/"devout"/"mercantile"/
            # "agrarian") — but the mirror above only ever wrote a
            # per-SETTLEMENT subject ("{name}'s tech-path lean"), so
            # that read was a permanent no-op across every settlement
            # that ever reached a real branch tie. A second entry, keyed
            # by the literal branch name and revised in place across
            # every settlement that leans that way, closes it — a
            # branch other settlements have also leaned into is now a
            # real signal the next tied settlement can read.
            branch_existing = self.world.innovation_pillar.find_world_model_entry(branch)
            self.world.innovation_pillar.upsert_world_model(
                self.world.clock.tick_count, branch, f"A recurring lean toward {branch} — {reason}",
                1.0, status="observation", source="era_branch",
                revises_id=branch_existing["id"] if branch_existing is not None else None,
            )
            self.world.innovation_pillar.remember(f"{target.name or 'The village'} is leaning {branch}: {reason}")
            self._append_emergence(
                "opportunity", "innovation", f"{target.name or 'The village'} is leaning {branch}: {reason}",
                ('innovation',),
            )

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
        # Tier 0, new producer: the positive counterpart to the feud
        # dampening above — see `_detect_prosperity`'s mirror.
        if festival_target.id in self._prosperity_flagged:
            festival_chance *= 1.0 + PROSPERITY_FESTIVAL_BONUS
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "festival_roll") >= festival_chance:
            return
        if self._pillar_interpret_backpressured("village"):
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
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
            self._append_emergence(
                "opportunity", "culture", f"Held a festival — {entry}",
                ('village',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a sixth Village->Humans arrow: a festival is a
            # real communal event with specific bonds strengthened —
            # worth Humans' pillar knowing directly.
            self._send_pillar_message(
                "village", "humans", "observation", f"held a festival — {entry}",
            )

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
                self._bump_village_pattern_signal(
                    "starvation_death", f"{stl.name} has lost people to hunger before.",
                )
            if had_new_outbreak:
                counts = stl.pattern_signal_counts
                counts["disease_outbreak"] = counts.get("disease_outbreak", 0) + 1
                self._bump_village_pattern_signal(
                    "disease_outbreak", f"{stl.name} keeps seeing sickness take hold.",
                )
            if had_wildlife_recolonization:
                counts = stl.pattern_signal_counts
                counts["wildlife_recolonization"] = counts.get("wildlife_recolonization", 0) + 1
                self._bump_village_pattern_signal(
                    "wildlife_recolonization", f"Wildlife keeps pressing back into land near {stl.name}.",
                )
            self._maybe_promote_ritual(stl)

    def _bump_village_pattern_signal(self, subject: str, text: str) -> None:
        """Tier 0, new producer (explicit user instruction: "continue
        tier 0"): `starvation_death`/`disease_outbreak`/`wildlife_
        recolonization` were already real `pattern_signal_counts` keys
        with a real `PRESSURE_SIGNAL_LABELS` entry (see `llm/
        ontology.py`) — `_maybe_schedule_ontology_proposal`'s pressure-
        signal tiebreak (v1.34.129/131) already scans ALL of a
        settlement's `pattern_signal_counts` and already reads `village_
        pillar.subject_confidence(kv[0])` for whichever key wins, but
        these three specific keys had no matching `world_model` mirror
        anywhere — their real occurrence counts could still win the
        primary pick outright (never blocked), but a genuine tie
        involving one of them could never lean toward it. Same
        revise-in-place shape `dispute_feud`/`materials_bottleneck`
        already established, factored into one shared helper since this
        is the third site to need it (not retrofitted onto the earlier
        two, which already work and don't need touching)."""
        existing = self.world.village_pillar.find_world_model_entry(subject)
        prior_confidence = existing["confidence"] if existing else 0.3
        self.world.village_pillar.upsert_world_model(
            self.world.clock.tick_count, subject, text,
            min(1.0, prior_confidence + 0.1), status="observation", source=subject,
            revises_id=existing["id"] if existing else None,
        )

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
        if self._pillar_interpret_backpressured("village"):
            return
        self._mark_season_year_resolved("religion")
        omen_history = list(target.omen_history)
        folklore_entries = list(target.folklore)
        prompt = religion.build_prompt(
            target.name, target.rituals, omen_history, folklore_entries, legends=list(target.legends),
        )
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
            self._append_emergence(
                "opportunity", "culture", f"Came to share a faith called {parsed['name']}.",
                ('village', 'humans'),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a third Village->Humans arrow: a crystallized
            # faith is a real belief-shaping fact about specific living
            # people, worth Humans' pillar knowing directly.
            self._send_pillar_message(
                "village", "humans", "observation",
                f"the village came to share a faith called {parsed['name']}: "
                f"{'; '.join(parsed['tenets'])}",
            )

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
            self._append_emergence(
                "unexplained_shift", "population", f"The village's mood read as: {', '.join(themes)}.",
                ('humans',),
            )
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
                    # A17's shared "compete" step, second consumer: a
                    # near-duplicate MEANING (not just an exact-term
                    # repeat) is also silently dropped — see LEXICON_
                    # MEANING_MERGE_OVERLAP's docstring.
                    is_meaning_duplicate = memetics.find_near_duplicate(
                        meaning, [e["meaning"] for e in stl.lexicon], LEXICON_MEANING_MERGE_OVERLAP,
                    ) is not None
                    if narrative_direction.validate_coined_term(term, stl.lexicon) and not is_meaning_duplicate:
                        # A17's shared "decay" step: age out anything
                        # nobody has coined a related term for in a very
                        # long while, before appending the new one.
                        stl.lexicon = memetics.prune_aged_entries(
                            stl.lexicon, lambda e: e["formed_tick"], self.world.clock.tick_count, LEXICON_MAX_AGE_TICKS,
                        )
                        stl.lexicon.append({"term": term, "meaning": meaning, "formed_tick": self.world.clock.tick_count})
                        if len(stl.lexicon) > LEXICON_MAX_STORED:
                            stl.lexicon = stl.lexicon[-LEXICON_MAX_STORED:]
                        self._log("dialect_coined", f"{stl.name} has started calling it \"{term}\" — {meaning}")
            self._pillar_close_cycle("humans")

        # Cultural evolution: naming the emergent theme is interpretation
        # over a real computed mood signal (v1.3.37).
        self._schedule_llm_job(
            "narrative_direction", prompt, narrative_direction.SYSTEM_PROMPT, fallback, apply,
            deep_reasoning=True, num_predict_mult=LARGE_SCHEMA_REASONING_NUM_PREDICT_MULT,
        )

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
        if self._pillar_interpret_backpressured("village"):
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
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, f"{stl.name or 'the village'}'s culture", digest,
                    0.8, status="observation", source="culture_digest",
                )

        # Cultural evolution (v1.3.37).
        self._schedule_llm_job("culture_digest", prompt, culture_digest.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

    def _update_institution_dormancy(self) -> None:
        """Tier 5 B4.2 pilot — the real sleep/wake criterion for "idle
        institutions," one monthly pass over every real (settlement,
        institution) pair. Cheap by construction: `_institution_
        fingerprint` reads already-computed institution fields, no new
        per-tick tracked state and no scan beyond what `_institution_
        job_target` already does every month regardless.

        A fresh institution is registered ACTIVE (never starts asleep).
        A fingerprint change (a new member, a fresh feud, a new belief,
        a revised objective — the institution's own real activity) both
        resets the idle-check counter AND wakes it if it was dormant,
        via `DormancyManager.wake` — B4.3's real elapsed-tick gap is
        read but deliberately not "caught up" against anything (this
        pilot's dormancy never skips any Body-affecting per-tick work,
        only Mind-layer LLM-scheduling attention — see this module's
        own docstring for the Constitution B15 `TWO_PART_GUARANTEE`
        reasoning). An unchanged fingerprint for `INSTITUTION_DORMANCY_
        IDLE_CHECKS_THRESHOLD` consecutive monthly checks puts it to
        sleep.

        Tier 5 B3's real control point: this used to be a plain `if
        "month_end" not in events: return` guard, called every tick
        just to immediately no-op on all but one. That guard is now the
        scheduler's own job (`ON_EVENT`/`event_types={"month_end"}` on
        this task's declaration, `_tick_once` publishes "month_end"
        into this scheduler's real `EventBus` right after `events` is
        computed) — the function itself is only ever invoked on a real
        month_end tick now, `skipped_clean` (never touching budget/
        deferral machinery) every other tick."""
        seen: set[tuple[int, int]] = set()
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            for institution in settlement.institutions:
                if not institution.member_agent_ids:
                    continue
                key = _institution_dormancy_key(settlement, institution)
                dict_key = (settlement.id, institution.id)
                seen.add(dict_key)
                fingerprint = _institution_fingerprint(institution)
                if dict_key not in self._institution_fingerprint:
                    self._institution_dormancy.register(key, self.world.clock.tick_count)
                    self._institution_fingerprint[dict_key] = fingerprint
                    self._institution_idle_checks[dict_key] = 0
                    continue
                if fingerprint != self._institution_fingerprint[dict_key]:
                    self._institution_fingerprint[dict_key] = fingerprint
                    self._institution_idle_checks[dict_key] = 0
                    self._institution_dormancy.wake(key, self.world.clock.tick_count)
                    continue
                idle = self._institution_idle_checks.get(dict_key, 0) + 1
                self._institution_idle_checks[dict_key] = idle
                if idle >= self._dormancy_idle_threshold(INSTITUTION_DORMANCY_IDLE_CHECKS_THRESHOLD):
                    self._institution_dormancy.sleep(key, self.world.clock.tick_count)
        # An institution that's gone (settlement/institution pruned)
        # leaves no trace to clean up beyond its own small dict entries
        # — bounded by the same INSTITUTION_LIST_MAX_STORED cap
        # `Settlement.institutions` itself already holds, never
        # unbounded growth.
        stale = set(self._institution_fingerprint) - seen
        for dict_key in stale:
            del self._institution_fingerprint[dict_key]
            del self._institution_idle_checks[dict_key]

    def _update_idea_dormancy(self) -> None:
        """Tier 5 B4.2, second dormancy candidate ("unused ideas") —
        the same real `DormancyManager` sleep/wake shape as `_update_
        institution_dormancy` directly above, applied to `World.
        invented_concepts` still in `proposed`/`spreading` status (an
        `established`/`abandoned`/`retired` concept is no longer
        "growing" at all — `_maybe_spread_concepts` already excludes
        it via its own `growing` filter, so dormancy tracking for it
        would be meaningless).

        A concept that keeps gaining adopters (or changes status)
        resets its idle-check counter and wakes immediately via
        `DormancyManager.wake`; one that sits with the same fingerprint
        for `IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD` consecutive monthly
        checks goes to sleep. `_maybe_spread_concepts`'s per-tick roll
        list then skips sleeping ideas — same Mind-layer-only,
        B15-`TWO_PART_GUARANTEE`-compliant reasoning as the institutions
        pilot (an idea's own per-tick adoption ROLL is what's gated,
        never any Body-deterministic per-tick effect elsewhere)."""
        seen: set[int] = set()
        for concept in self.world.invented_concepts.values():
            if concept.status not in ("proposed", "spreading"):
                continue
            seen.add(concept.id)
            fingerprint = _idea_fingerprint(concept)
            key = str(concept.id)
            if concept.id not in self._idea_fingerprint:
                self._idea_dormancy.register(key, self.world.clock.tick_count)
                self._idea_fingerprint[concept.id] = fingerprint
                self._idea_idle_checks[concept.id] = 0
                continue
            if fingerprint != self._idea_fingerprint[concept.id]:
                self._idea_fingerprint[concept.id] = fingerprint
                self._idea_idle_checks[concept.id] = 0
                self._idea_dormancy.wake(key, self.world.clock.tick_count)
                continue
            idle = self._idea_idle_checks.get(concept.id, 0) + 1
            self._idea_idle_checks[concept.id] = idle
            if idle >= self._dormancy_idle_threshold(IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD):
                self._idea_dormancy.sleep(key, self.world.clock.tick_count)
        # A concept that left `proposed`/`spreading` (established,
        # abandoned, retired) is no longer tracked — bounded by the same
        # MAX_CONCEPTS_STORED cap `World.invented_concepts` itself holds.
        stale = set(self._idea_fingerprint) - seen
        for concept_id in stale:
            del self._idea_fingerprint[concept_id]
            del self._idea_idle_checks[concept_id]

    def _update_tradition_dormancy(self) -> None:
        """Tier 5 B4.2, third dormancy candidate ("forgotten
        traditions") — the same real `DormancyManager` sleep/wake shape
        as `_update_institution_dormancy`/`_update_idea_dormancy`
        directly above, applied to every named settlement's own
        `Settlement.traditions` entries.

        A tradition that keeps gaining personal keepers resets its
        idle-check counter and wakes immediately via `DormancyManager.
        wake`; one whose keeper count sits flat for `TRADITION_
        DORMANCY_IDLE_CHECKS_THRESHOLD` consecutive monthly checks goes
        to sleep. `_maybe_spread_tradition_keeping`'s per-settlement
        weighted pick then excludes sleeping traditions — same Mind-
        layer-only, B15-`TWO_PART_GUARANTEE`-compliant reasoning as
        both siblings above (a tradition's own per-tick personal-
        keeper-spread ROLL is what's gated, never `Settlement.
        traditions` itself or any Body-deterministic effect)."""
        seen: set[str] = set()
        for settlement in self.world.settlements:
            if not settlement.name or not settlement.traditions:
                continue
            agents = [a for a in self.world.population.agents if a.settlement_id == settlement.id]
            for tradition in settlement.traditions:
                key = _tradition_dormancy_key(settlement, tradition)
                seen.add(key)
                fingerprint = _tradition_fingerprint(settlement, tradition, agents)
                if key not in self._tradition_fingerprint:
                    self._tradition_dormancy.register(key, self.world.clock.tick_count)
                    self._tradition_fingerprint[key] = fingerprint
                    self._tradition_idle_checks[key] = 0
                    continue
                if fingerprint != self._tradition_fingerprint[key]:
                    self._tradition_fingerprint[key] = fingerprint
                    self._tradition_idle_checks[key] = 0
                    self._tradition_dormancy.wake(key, self.world.clock.tick_count)
                    continue
                idle = self._tradition_idle_checks.get(key, 0) + 1
                self._tradition_idle_checks[key] = idle
                if idle >= self._dormancy_idle_threshold(TRADITION_DORMANCY_IDLE_CHECKS_THRESHOLD):
                    self._tradition_dormancy.sleep(key, self.world.clock.tick_count)
        # A tradition whose settlement was renamed/unfounded, or that no
        # longer appears in `Settlement.traditions` at all, drops out —
        # bounded by whatever cap `Settlement.traditions` itself holds.
        stale = set(self._tradition_fingerprint) - seen
        for key in stale:
            del self._tradition_fingerprint[key]
            del self._tradition_idle_checks[key]

    def _update_settlement_dormancy(self) -> None:
        """Tier 5 B4.2, fourth dormancy candidate ("inactive
        settlements") — the same real `DormancyManager` sleep/wake
        shape as the three siblings above, applied to every NAMED
        `World.settlement` instead. Reframed from the shape the item's
        own prior entries flagged as needing a genuinely lossless
        elapsed-tick reconstruction (the harder problem `_update_
        institution_dormancy`'s own docstring names for wildlife/
        settlement per-tick ticking): this pilot gates `_job_target()`'s
        existing month-indexed round-robin (WHICH settlement gets this
        month's town_brain/beliefs/chronicle/... LLM narration) rather
        than Body-deterministic ticking itself — the identical Mind-
        layer-attention-only shape as institutions/ideas/traditions,
        not the harder problem.

        A settlement whose coarse fingerprint (living population, era,
        building count, tech level — see `_settlement_fingerprint`)
        keeps shifting resets its idle-check counter and wakes
        immediately via `DormancyManager.wake`; one that sits flat for
        `SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD` consecutive monthly
        checks goes to sleep. `_job_target`'s round-robin then excludes
        sleeping settlements — same Mind-layer-only, B15 `TWO_PART_
        GUARANTEE`-compliant reasoning as all three siblings (a
        settlement's own Body-deterministic per-tick ticking is
        completely untouched; only which settlement's turn it is for a
        narrative LLM job this month is gated)."""
        seen: set[int] = set()
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            seen.add(settlement.id)
            population_count = sum(
                1 for a in self.world.population.agents if a.settlement_id == settlement.id
            )
            fingerprint = _settlement_fingerprint(settlement, population_count)
            key = str(settlement.id)
            if settlement.id not in self._settlement_fingerprint:
                self._settlement_dormancy.register(key, self.world.clock.tick_count)
                self._settlement_fingerprint[settlement.id] = fingerprint
                self._settlement_idle_checks[settlement.id] = 0
                continue
            if fingerprint != self._settlement_fingerprint[settlement.id]:
                self._settlement_fingerprint[settlement.id] = fingerprint
                self._settlement_idle_checks[settlement.id] = 0
                self._settlement_dormancy.wake(key, self.world.clock.tick_count)
                continue
            idle = self._settlement_idle_checks.get(settlement.id, 0) + 1
            self._settlement_idle_checks[settlement.id] = idle
            if idle >= self._dormancy_idle_threshold(SETTLEMENT_DORMANCY_IDLE_CHECKS_THRESHOLD):
                self._settlement_dormancy.sleep(key, self.world.clock.tick_count)
        # A settlement that lost its name (shouldn't happen in practice,
        # settlements are never unnamed once named) drops out — bounded
        # by `Config.max_settlements` regardless.
        stale = set(self._settlement_fingerprint) - seen
        for settlement_id in stale:
            del self._settlement_fingerprint[settlement_id]
            del self._settlement_idle_checks[settlement_id]

    def _institution_job_target(self) -> "tuple[Settlement, object] | None":
        """§9 "institutions get their own persistent memory" (docs/IDEAS-
        2026-07-EMERGENCE.md): a month-indexed round-robin over every
        (settlement, institution) pair with at least one living member
        — same "flat call volume regardless of count" shape `_job_
        target`/`_diplomacy_pair_target` already give settlement-scoped
        jobs, generalized one level deeper since institutions can
        genuinely outnumber settlements. `None` once no settlement has
        any institution yet (a fresh/small world).

        Tier 5 B4.2 pilot: sleeping institutions (see `_update_
        institution_dormancy`) are excluded from the rotation, so the
        quarterly `institution_culture` call concentrates on
        institutions something has actually happened to lately — real
        cognition-breadth adaptation (permitted by B15's `TWO_PART_
        GUARANTEE`), never a Body-affecting change. Falls back to the
        FULL pair list if every institution happens to be asleep at
        once (a small/quiet world) — dormancy narrows attention, it
        never silently disables the job."""
        pairs = [
            (s, i) for s in self.world.settlements if s.name
            for i in s.institutions if i.member_agent_ids
        ]
        if not pairs:
            return None
        awake = [
            pair for pair in pairs
            if self._institution_dormancy.is_scheduled(_institution_dormancy_key(*pair))
        ]
        if awake:
            pairs = awake
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
        if self._pillar_interpret_backpressured("village"):
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
                self.world.village_pillar.remember(f"The {inst.name or inst.kind.value} came to see itself as: {digest}")
                self._append_emergence(
                    "novel_combination", "institution", f"The {inst.name or inst.kind.value} came to see itself as: {digest}",
                    ('village',),
                )

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
        if self._pillar_interpret_backpressured("reflection"):
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
        civilization_aggregate = culture_aggregate.compute_civilization_culture(
            self.world.settlements, agents=self.world.population.agents,
        )
        prompt = consciousness.build_prompt(
            target.name, self.world.consciousness_personality, self.world.consciousness_memory,
            self.world.consciousness_objectives, self.world.consciousness_player_model,
            dict(target.mood), target.temperament, self._narrative_theme_bias(target),
            target.player_standing, recent, self.world.consciousness_intervention_log,
            self._player_intervention_trend(),
            observer_favorite_name=favorite.name if favorite is not None else "",
            grudge_text=grudge_text,
            civilization_culture_text=culture_aggregate.civilization_culture_text(civilization_aggregate),
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
                # Tier 0, explicit user decision via AskUserQuestion:
                # mirror into Reflection, hypothesis-only — same narrow
                # exception shape `omen` got for Phase G. Real content
                # (kind/detail) is fine here because Reflection's
                # world_model/memory, like `consciousness_intervention_
                # log` itself, is dev-console-depth state, never
                # surfaced in the main UI — the public `_log` line
                # above stays exactly as vague as before this change.
                subject = f"a change in {target.name}"
                existing = self.world.reflection_pillar.find_world_model_entry(subject)
                self.world.reflection_pillar.upsert_world_model(
                    tick, subject, f"{kind}: {detail}",
                    0.4, status="hypothesis", source="consciousness",
                    revises_id=existing["id"] if existing is not None else None,
                )
                self.world.reflection_pillar.remember(f"Something shifted in {target.name}: {kind} — {detail}")

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
                # Tier 0 (24th site, explicit user decision via
                # `AskUserQuestion` — a third extension of the omen/
                # observer Phase G carve-out): real bond strength stays
                # the sole determinant; humans_pillar only breaks a
                # genuine tie, which relationship floats rarely produce
                # in practice — kept for consistency with the other
                # carve-out sites, not because ties are common here.
                by_id_local = {a.id: a for a in self.world.population.agents}
                partner_id = max(
                    primary.relationships,
                    key=lambda aid: (
                        primary.relationships[aid],
                        self.world.humans_pillar.subject_confidence(by_id_local[aid].name)
                        if aid in by_id_local else 0.0,
                    ),
                )
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
        notable to say" most cycles, which is correct, not a gap.

        Tier 0 mirror-write -> pillar-authored conversion (docs/
        ROADMAP-2026-07-REMAINING.md), Reflection's first real site:
        when more than one named settlement independently crosses its
        pattern threshold the SAME cycle, the settlement loop below
        used to pick whichever came first in `World.settlements`' own
        list order — an accident of insertion history, not a
        meaningful tiebreak. Reflection's own existing subjects are
        already settlement-name-keyed (`f"{label} in {settlement.
        name}"`, see the loop body) — no new content needed, unlike
        the earlier Humans dead-end. Settlements are now checked in
        order of `reflection_pillar.subject_confidence(settlement.
        name)` (descending) first: "the settlement Reflection already
        has a standing theory about" is examined first, a real
        "attention returns to what's already on your mind" tiebreak.
        `list.sort` is stable, so with no lean anywhere (the common
        case) this reproduces the exact prior list-order behavior."""
        settlements = self.world.settlements
        if len(settlements) > 1:
            settlements = sorted(
                settlements, key=lambda s: self.world.reflection_pillar.subject_confidence(s.name), reverse=True,
            )
        for settlement in settlements:
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
            self._append_emergence(
                "opportunity", "reflection", f"Still wondering about {pattern['subject']}: {question_text}",
                ('reflection',),
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
            self.world.reflection_pillar.upsert_world_model(
                self.world.clock.tick_count, hypothesis_subject, parsed["advice"],
                0.5, status="hypothesis", source="self_tuning_advisory",
            )
            self.world.reflection_pillar.remember(f"Gave advice about {hypothesis_subject}: {parsed['advice']}")
            # Observe/interpret cycling, first slice: also feeds the
            # Emergence API so Reflection's own observe turn can notice
            # this on its own next cycle.
            self._append_emergence(
                "opportunity", "reflection", f"Advice about {hypothesis_subject}: {parsed['advice']}",
                ("reflection", "village"),
            )
            # Inbox/outbox participation, first slice (docs/ROADMAP-
            # 2026-07-REMAINING.md): Reflection's own free-standing
            # advice — something it noticed but has no tunable governor
            # for — is exactly the kind of thing worth handing to
            # Village directly, not just leaving in the shared
            # Emergence stream. A `theory` (Reflection's own genuinely
            # uncertain read, not a settled fact) competes for Village's
            # bounded attention on its next observe turn like any other
            # inbox message.
            self._send_pillar_message(
                "reflection", "village", "theory",
                f"I've been wondering about {hypothesis_subject}: {parsed['advice']}",
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
        if self._pillar_interpret_backpressured("reflection"):
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
        initiated_by_conviction = False
        conviction_entry_id = None
        if candidate is None and advisory_candidate is None:
            # C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-
            # 2026-07-22.md's Part C, Tier 3, "propose experiment"):
            # before giving up, check whether reflection_pillar's own
            # persisted conviction about a still-OPEN hypothesis is
            # strong enough to genuinely INITIATE testing it early,
            # ahead of the normal multi-cycle promotion to "supported".
            # This is the real intention — not a tiebreak among already-
            # eligible candidates (every prior Tier 0 site only ever
            # broke a tie), it changes WHETHER an experiment gets tested
            # at all this cycle. Evidence still stays authoritative: an
            # open hypothesis already trending toward rejection can
            # never be force-tested purely on stale initial conviction.
            convicted = [
                e for e in self.world.reflection_notebook
                if e.get("kind") == "hypothesis" and e.get("status") == "open"
                and e.get("id") not in acted_hypothesis_ids
                and e.get("confidence", 0.0) > REFLECTION_REJECTED_THRESHOLD
                and self.world.reflection_pillar.subject_confidence(e.get("subject", ""))
                >= REFLECTION_PILLAR_CONVICTION_EXPERIMENT_THRESHOLD
            ]
            # Scoped to the governor-mapped path only, not advisory —
            # the sandboxed nudge is where "test the hypothesis in a
            # jar" (item 1.3) actually applies; the advisory path has
            # no sandboxed confirmation to close the loop against.
            governor_convicted = [
                e for e in convicted if self._governor_key_for_subject(e.get("subject", "")) is not None
            ]
            if governor_convicted:
                entry = max(
                    governor_convicted,
                    key=lambda e: self.world.reflection_pillar.subject_confidence(e.get("subject", "")),
                )
                conviction_entry = self.world.reflection_pillar.find_world_model_entry(entry.get("subject", ""))
                conviction_entry_id = conviction_entry["id"] if conviction_entry else None
                initiated_by_conviction = True
                candidate = entry
                governor_key = self._governor_key_for_subject(entry.get("subject", ""))
        if candidate is None:
            if advisory_candidate is None:
                return
            self._schedule_advisory(advisory_candidate)
            return
        current_multiplier = self.world.governor_tuning.get(governor_key, 1.0)
        prompt = self_tuning.build_prompt(
            candidate["subject"], candidate["content"], current_multiplier, via_conviction=initiated_by_conviction,
        )
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
                # C2 "Intention channel": if this experiment was
                # genuinely INITIATED by reflection_pillar's own
                # standing conviction (see the scheduling site above),
                # that conviction is now confirmed — a real, sandbox-
                # validated adjustment followed from it, so its own
                # mirror entry is reinforced to full confidence in
                # place, closing the conviction -> experiment ->
                # confirmation loop the same way invention's hypothesis
                # and laws' conviction do.
                if initiated_by_conviction and conviction_entry_id is not None:
                    conviction_entry = next(
                        (e for e in self.world.reflection_pillar.world_model if e["id"] == conviction_entry_id),
                        None,
                    )
                    if conviction_entry is not None:
                        self.world.reflection_pillar.upsert_world_model(
                            self.world.clock.tick_count, conviction_entry["subject"], conviction_entry["belief"],
                            1.0, status="observation", source="self_tuning_conviction_confirmed",
                            revises_id=conviction_entry_id,
                        )
                self.world.reflection_pillar.remember(
                    f"Acted on my own hypothesis about {hypothesis_subject}: {parsed['rationale']}"
                )
                self._append_emergence(
                    "opportunity", "reflection", f"Acted on my own hypothesis about {hypothesis_subject}: {parsed['rationale']}",
                    ('reflection', 'village'),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage III
                # step 11), a second Reflection->Village arrow: a real
                # applied self-tuning nudge (sandbox-validated, not
                # just proposed) is a settled fact about how Hearthmind
                # adjusted itself — worth Village knowing directly,
                # same treatment self_tuning_advisory's theory arrow
                # already gets.
                self._send_pillar_message(
                    "reflection", "village", "observation",
                    f"adjusted {hypothesis_subject} on its own judgment: {parsed['rationale']}",
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
        if self._pillar_interpret_backpressured("reflection"):
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
            self._append_emergence(
                "opportunity", "reflection", f"Mused: {text}",
                ('reflection',),
            )

        self._schedule_llm_job("musing", prompt, musing.SYSTEM_PROMPT, fallback, apply)

    # --- caravans: a first, scoped step toward "external settlements and trade" ---

    TRAFFIC_CARAVAN_CHANCE_WEIGHT = 0.5
    """A1's `traffic` field (Tier 1, docs/ROADMAP-2026-07-REMAINING.md):
    the maximum boost a fully-trafficked region gives `_maybe_schedule_
    caravan`'s monthly visit chance (a region with `traffic == 1.0`
    draws 1.5x as often as one with none) — real but bounded, same
    "meaningful, never dominant" scale `caravan_relation_factor`/
    `MARKET_CARAVAN_CHANCE_MULTIPLIER` already apply to this value."""

    STORMINESS_CARAVAN_CHANCE_DAMPENING = 0.4
    """A1's `storminess` field (part of migrating the 3x3 climate grid
    onto `FieldGrid`, docs/ROADMAP-2026-07-REMAINING.md): the maximum
    dampening a fully-stormy region applies to `_maybe_schedule_
    caravan`'s monthly visit chance — "traders avoid storms," the real
    negative counterpart to `TRAFFIC_CARAVAN_CHANCE_WEIGHT`'s positive
    pull on the same `chance` value."""

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
        # A1's fourth field, `traffic` (Tier 1, docs/ROADMAP-2026-07-
        # REMAINING.md): a settlement sitting in a well-traveled region
        # (real road wear nearby, not just its own tile) draws more
        # outside trade — "trade follows roads" as a mechanical fact,
        # the same kind of real multiplier `has_market()`/`caravan_
        # relation_factor` already apply to this exact `chance` value.
        if settlement.center_x >= 0 and settlement.center_y >= 0:
            traffic = self.world.fields.get_at(
                "traffic", (settlement.center_x, settlement.center_y),
                self.world.config.width, self.world.config.height,
            )
            chance = min(1.0, chance * (1.0 + traffic * self.TRAFFIC_CARAVAN_CHANCE_WEIGHT))
            # A1's `storminess` field, part of migrating the 3x3
            # climate grid onto FieldGrid — the real negative
            # counterpart to traffic's own positive pull above.
            storminess = self.world.fields.get_at(
                "storminess", (settlement.center_x, settlement.center_y),
                self.world.config.width, self.world.config.height,
            )
            chance = max(0.0, chance * (1.0 - storminess * self.STORMINESS_CARAVAN_CHANCE_DAMPENING))
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
        if self._pillar_interpret_backpressured("village"):
            return
        recent = recent_events_diverse(self.conn, limit=caravan.CARAVAN_RECENT_EVENTS)
        prompt = caravan.build_prompt(settlement.name, recent)
        fallback = caravan.fallback_caravan(self.world.clock.tick_count)

        def apply(result: dict, used_fallback: bool) -> None:
            description, rumor = caravan.parse_caravan(result, fallback)
            self._log("caravan", description)
            self.world.village_pillar.remember(f"A caravan came through — {description}")
            self._append_emergence(
                "opportunity", "economy", f"A caravan came through — {description}",
                ('village',),
            )
            if rumor and _namespaced_roll(
                self.world.config.seed, self.world.clock.tick_count, "caravan_rumor_roll",
            ) < caravan.CARAVAN_RUMOR_CHANCE:
                listener_rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "caravan_rumor")
                self.world.population.spread_rumor(
                    rumor, caravan.CARAVAN_RUMOR_LISTENER_COUNT, listener_rng,
                    humans_lean=lambda a: self.world.humans_pillar.subject_confidence(a.name),
                )

        self._schedule_llm_job(
            "caravan", prompt, caravan.SYSTEM_PROMPT, fallback, apply, settlement=settlement.name,
        )

    # --- the "town brain": monthly civic-priority LLM decision -----------------

    def _village_priority_lean(self) -> float:
        """Precomputes `town_brain.compute_priority`'s optional pillar-
        authored tiebreak input (Tier 0's mirror-write -> pillar-
        authored conversion, docs/ROADMAP-2026-07-REMAINING.md, item
        0's closing note) — the max confidence the Village pillar holds
        about ANY growth-leaning subject, minus the max confidence it
        holds about ANY safety-leaning one (`Pillar.subject_
        confidence`). Several keyword candidates per side since a real
        LLM-authored `world_model` subject label is free text, never
        guaranteed to literally say "growth"/"defense" — this stays a
        best-effort, zero-LLM-cost read of whatever the pillar has
        actually accumulated, correctly returning 0.0 (a genuine no-op
        at the caller's tiebreak) for a settlement whose Village pillar
        hasn't yet formed anything matching either side."""
        pillar = self.world.village_pillar
        growth = max(pillar.subject_confidence(k) for k in ("growth", "expansion", "prosperity"))
        caution = max(pillar.subject_confidence(k) for k in ("defense", "safety", "security", "caution"))
        return growth - caution

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
        # Attention-budget arbitration, first slice (docs/ROADMAP-
        # 2026-07-REMAINING.md): town_brain is Village's single most
        # significant civic decision, so it earns the same priority-
        # scaled backpressure tolerance the pillar's own `interpret`
        # turn gets (B3, `_pillar_interpret_backpressured`) instead of
        # the flat threshold every other settlement job shares — a
        # quiet, fresh Village pillar defers this earlier under
        # pressure; a salient or long-overdue one tolerates more
        # backlog before deferring. Never a full bypass.
        if self._pillar_interpret_backpressured("village"):
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
        decision = town_brain.compute_priority(
            population_summary, settlement_summary, council_disposition,
            village_pillar_lean=self._village_priority_lean(),
        )
        priority = decision["priority"]
        settlement.current_priority = priority
        settlement.priority_rationale = decision["rationale"]
        settlement.record_priority(self.world.clock.tick_count, priority, decision["rationale"])
        self._log("town_brain", f"{settlement.name or 'The village'}'s priority is now {priority} — {decision['rationale']}")
        # Tier 0 batch: town_brain joins Village pillar's wired jobs —
        # the priority itself is already decided deterministically
        # above, so this mirrors immediately rather than waiting on
        # the narration-only LLM call below.
        self.world.village_pillar.upsert_world_model(
            self.world.clock.tick_count, f"{settlement.name or 'the village'}'s civic priority", priority,
            1.0, status="observation", source="town_brain",
        )
        self._append_emergence(
            "opportunity", "settlement",
            f"{settlement.name or 'The village'}'s priority is now {priority} — {decision['rationale']}",
            ("village",),
        )
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
                self._append_emergence(
                    "opportunity", "belief", f"Came to believe {entry['subject']}: {entry['belief']}",
                    ('village',),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage III
                # step 11), the Village->Innovation arrow: a genuinely
                # new, reasonably-confident settlement theory is real
                # grounding material for what the village might
                # originate next — tell Innovation about it. Tier 3
                # item 23: the same reverse-direction disagreement
                # check the Nature->Village arrow has always done —
                # Innovation may already hold a confident theory about
                # the recognizably same subject (e.g. a concept whose
                # hypothesis this belief now contradicts), which is
                # real tension worth flagging as `disagreement` rather
                # than a flat `theory` tag.
                if entry["confidence"] >= 0.5:
                    message_kind = (
                        "disagreement" if self.world.innovation_pillar.disagrees_with(entry["subject"])
                        else "theory"
                    )
                    self._send_pillar_message(
                        "village", "innovation", message_kind,
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
            num_predict_mult=LARGE_SCHEMA_REASONING_NUM_PREDICT_MULT,
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
        if self._pillar_interpret_backpressured("humans"):
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
        # Tier 0's fourteenth conversion (docs/ROADMAP-2026-07-
        # REMAINING.md): a self-referential site, same shape as
        # `ontology_evolution`'s Innovation self-lean — this job WRITES
        # `humans_pillar.world_model` (via `_run_personal_belief`'s
        # apply(), v1.34.98) and now also READS it to help pick who
        # gets this month's picks, weighted (never narrowed) toward
        # whoever Humans' own accumulated attention already returns to.
        # `rng.sample`'s uniform-without-replacement draw becomes a
        # sequential weighted draw without replacement — the same
        # `HUMANS_PERSONAL_TARGET_LEAN_WEIGHT` every sibling Humans-
        # lean site already uses, no reason to tune this one
        # differently.
        pool = list(candidates)
        picks = []
        for _ in range(min(PERSONAL_BELIEF_PICKS_PER_MONTH, len(pool))):
            weights = [
                1.0 + self.world.humans_pillar.subject_confidence(a.name) * HUMANS_PERSONAL_TARGET_LEAN_WEIGHT
                for a in pool
            ]
            chosen = rng.choices(pool, weights=weights, k=1)[0]
            picks.append(chosen)
            pool.remove(chosen)
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
                self.world.humans_pillar.remember(f"{target.name} came to believe: {parsed['belief']}")
                # Tier 0's first per-agent-keyed Humans world_model
                # producer (docs/ROADMAP-2026-07-REMAINING.md,
                # explicit user request: "try humans pillar per-agent
                # producer") — every other Humans mirror before this
                # only ever appended to `.memory` (episodic), never
                # `.world_model` (revisable theory); the pillar had no
                # accumulated per-agent-keyed content at all, a real
                # gap found and left correctly unshipped-around at
                # v1.34.97. Subject is deliberately `target.name`
                # itself (not `parsed["subject"]`, which is whatever
                # specific topic this reflection happened to be
                # about) — this is Humans' own standing theory ABOUT
                # this specific person, revised in place across
                # repeated Reflect() calls via `find_world_model_
                # entry`, same shape `_reactive_pillar_backpressured`'s
                # callers already use for a recurring subject.
                existing_pillar_entry = self.world.humans_pillar.find_world_model_entry(target.name)
                self.world.humans_pillar.upsert_world_model(
                    tick, target.name, parsed["belief"], parsed["confidence"], source="personal_belief",
                    revises_id=existing_pillar_entry["id"] if existing_pillar_entry else None,
                )
                self._append_emergence(
                    "opportunity", "belief", f"{target.name} came to believe: {parsed['belief']}",
                    ('humans',),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage
                # III step 11), a new Humans->Reflection arrow: an
                # individual's own private belief revision is real
                # psychological material for Reflection's pattern
                # detection over Humans' Body state.
                self._send_pillar_message(
                    "humans", "reflection", "observation",
                    f"{target.name} came to believe: {parsed['belief']}",
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
        if self._pillar_interpret_backpressured("humans"):
            return
        self._mark_monthly_resolved("dream")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "dream")
        # Tier 0 mirror-write -> pillar-authored conversion (docs/
        # ROADMAP-2026-07-REMAINING.md): same WHICH-candidate shape as
        # `memory_drift`/`noncore_nudge`/the inventor-selection sites —
        # "the person Humans' own accumulated attention already returns
        # to" is measurably (never certainly) more likely to be this
        # month's dreamer. An agent with no standing Humans theory
        # reads a flat 1.0, same never-narrow-the-pool discipline.
        weights = [
            1.0 + self.world.humans_pillar.subject_confidence(a.name) * HUMANS_PERSONAL_TARGET_LEAN_WEIGHT
            for a in candidates
        ]
        agent = rng.choices(candidates, weights=weights, k=1)[0]
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
            self._append_emergence(
                "anomaly", "psychology", f"{target.name} dreamed: {dream_text}",
                ('humans',),
            )
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
        means no drift this month, same as every other ambient job.

        Tier 0's sixth mirror-write -> pillar-authored conversion
        (docs/ROADMAP-2026-07-REMAINING.md): unblocked by `personal_
        belief`'s new `humans_pillar.world_model` mirror (the pillar's
        first per-agent-keyed producer) — target selection now weighs
        `humans_pillar.subject_confidence(agent.name)`, same "the
        collective mind's attention returns to who it already has a
        standing theory about" framing `institution_belief`'s own
        conversion uses. Never narrows the candidate pool; every
        eligible agent keeps a real chance (`HUMANS_PERSONAL_TARGET_
        LEAN_WEIGHT`)."""
        if not self._monthly_gate(events, "memory_drift"):
            return
        core_ids = list(self.world.population.core_agent_ids)
        candidates = [a for a in self.world.population.agents if a.id in core_ids and len(a.memories) >= 2]
        if not candidates:
            return
        if self._pillar_interpret_backpressured("humans"):
            return
        self._mark_monthly_resolved("memory_drift")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "memory_drift")
        if rng.random() >= self.MEMORY_DRIFT_CHANCE:
            return
        weights = [
            1.0 + self.world.humans_pillar.subject_confidence(c.name) * HUMANS_PERSONAL_TARGET_LEAN_WEIGHT
            for c in candidates
        ]
        agent = rng.choices(candidates, weights=weights, k=1)[0]
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
            self._append_emergence(
                "unexplained_shift", "psychology", f"{target.name}'s memory shifted: {drifted_text}",
                ('humans',),
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
                self._append_emergence(
                    "opportunity", "skill", f"{target.name} reflected on mastering {skill}: {reflection}",
                    ('humans',),
                )

            self._schedule_llm_job(
                "skill_mastery", prompt, skill_mastery.SYSTEM_PROMPT, fallback, apply, critical=False,
            )

    def _maybe_schedule_nature_causal_reasoning(self) -> None:
        """Tier 0's scoped-then-shipped Nature causal-reasoning job
        (docs/ROADMAP-2026-07-REMAINING.md) — a genuinely NEW cognition
        point, not a mirror of an existing job's output. Reactive, not
        cadence-gated (same shape `_maybe_schedule_skill_mastery`
        already established): fires on one of three already-detected
        Body-state anomalies (the design note's own three named
        candidates, all now shipped) — a predator-pack local
        extinction, a grazer-herd local extinction, or a forest tile
        stalled well past its own effective fallow requirement despite
        favorable moisture. World-scoped — none of these is any one
        settlement's event. At most ONE of the three schedules per
        tick (checked in this fixed order, first hit wins) — Nature's
        own LLM budget stays a single reactive call per tick even if
        more than one anomaly happens to be live simultaneously.

        Every trigger grounds ONLY in the specific anomaly plus real,
        already-computed Nature Body state — never settlement
        prosperity or era, same discipline `nature_mind` already holds.
        Output always `status="hypothesis"` (a wordless land has no
        ground truth to confirm) written to BOTH `nature_pillar.
        world_model` (so it's reachable the same way every other Nature
        belief is) AND a new `world.ontology.CausalThread`
        (`settlement_id=None` — this is a Nature-authored cause, not
        the existing dispute-authored shape, but the same record type
        so it's legible via the existing "🔗 causal threads" UI panel
        without a new one). `critical=True`: a failed/budget-exhausted
        call defers rather than fabricating a cause (Constitution
        §3/§7)."""
        if self._maybe_react_to_predator_extinction():
            return
        if self._maybe_react_to_grazer_extinction():
            return
        self._maybe_react_to_succession_stall()

    def _maybe_react_to_predator_extinction(self) -> bool:
        """First Nature causal-reasoning trigger: `world.wildlife.
        summary()["predator_packs"]` crossing from >0 to 0. Returns
        True if a reasoning call was actually scheduled this tick (so
        the dispatcher above doesn't also check the other two
        triggers)."""
        packs_now = self.world.wildlife.summary()["predator_packs"]
        if packs_now > 0:
            self._nature_predator_extinction_flagged = False
            return False
        if self._nature_predator_extinction_flagged:
            return False  # already scheduled/reasoned about this same extinction
        if self._reactive_pillar_backpressured("nature", "predator_extinction"):
            # Backpressured this tick — flag stays False, so this same
            # still-zero-packs anomaly gets re-checked (and a real
            # chance at scheduling) on a later tick instead of being
            # silently lost the one time it happened to land on a busy
            # tick — same "no data loss on a backpressured attempt"
            # spirit as the monthly-job retry windows elsewhere in this
            # file, done per-tick here since this trigger has no fixed
            # cadence to retry within.
            return False
        self._nature_predator_extinction_flagged = True
        wildlife_summary = self.world.wildlife.summary()
        anomaly_text = "The predator packs that once roamed this land have vanished entirely."
        context_bits = [
            f"predator pressure ratio before this was {wildlife_summary['predator_pressure_ratio']}",
            f"prey scarcity: {'yes' if wildlife_summary['prey_scarce'] else 'no'}",
            f"grazer herds remaining: {wildlife_summary['grazer_herds']}",
            f"disaster scars on the land: {len(self.world.disaster_scars)}",
            f"season: {self.world.clock.season}",
        ]
        existing_beliefs = list(self.world.nature_beliefs)
        prompt = nature_causal_reasoning.build_prompt(anomaly_text, context_bits, existing_beliefs)
        fallback = nature_causal_reasoning.fallback_cause()
        tick = self.world.clock.tick_count

        def apply(result: dict, used_fallback: bool) -> None:
            cause = nature_causal_reasoning.parse_cause(result)
            if not cause:
                return
            subject = "the vanished predator packs"
            existing = self.world.nature_pillar.find_world_model_entry(subject)
            entry = self.world.nature_pillar.upsert_world_model(
                tick, subject, cause, 0.4, status="hypothesis", source="nature_causal_reasoning",
                revises_id=existing["id"] if existing is not None else None,
            )
            self.world.nature_pillar.remember(f"Wondered why the predator packs vanished: {cause}")
            ontology.register_causal_thread(
                self.world, subject=subject, chain=context_bits + [cause], tick=tick, settlement_id=None,
            )
            self._append_emergence(
                "anomaly", "ecology", f"The land wonders why its predators vanished: {cause}",
                ('nature',), data={"pillar_entry_id": entry["id"]},
            )
            # Deliberately does NOT call `_pillar_close_cycle("nature")`
            # — unlike `nature_mind`, this job doesn't own Nature's own
            # observe/interpret cycle_stage (it's a separate reactive
            # trigger, not that cycle's `interpret` turn); force-closing
            # the cycle here could stomp a concurrently in-flight
            # nature_mind call's own stage transition.

        self._schedule_llm_job(
            "nature_causal_reasoning", prompt, nature_causal_reasoning.SYSTEM_PROMPT, fallback, apply,
            critical=True,
        )
        return True

    def _maybe_react_to_grazer_extinction(self) -> bool:
        """Second Nature causal-reasoning trigger, the design note's
        second named candidate: `world.wildlife.summary()
        ["grazer_herds"]` crossing from >0 to 0 — same reactive shape
        as `_maybe_react_to_predator_extinction`, just the other
        trophic level, and worth a real cause of its own (a grazer
        collapse plausibly starves out the very predators the first
        trigger reasons about, a real ecological chain the two
        triggers can each independently notice)."""
        grazers_now = self.world.wildlife.summary()["grazer_herds"]
        if grazers_now > 0:
            self._nature_grazer_extinction_flagged = False
            return False
        if self._nature_grazer_extinction_flagged:
            return False
        if self._reactive_pillar_backpressured("nature", "grazer_extinction"):
            return False
        self._nature_grazer_extinction_flagged = True
        wildlife_summary = self.world.wildlife.summary()
        anomaly_text = "The grazing herds that once roamed this land have vanished entirely."
        context_bits = [
            f"predator packs remaining: {wildlife_summary['predator_packs']}",
            f"prey scarcity was already flagged: {'yes' if wildlife_summary['prey_scarce'] else 'no'}",
            f"disaster scars on the land: {len(self.world.disaster_scars)}",
            f"season: {self.world.clock.season}",
        ]
        existing_beliefs = list(self.world.nature_beliefs)
        prompt = nature_causal_reasoning.build_prompt(anomaly_text, context_bits, existing_beliefs)
        fallback = nature_causal_reasoning.fallback_cause()
        tick = self.world.clock.tick_count

        def apply(result: dict, used_fallback: bool) -> None:
            cause = nature_causal_reasoning.parse_cause(result)
            if not cause:
                return
            subject = "the vanished grazing herds"
            existing = self.world.nature_pillar.find_world_model_entry(subject)
            entry = self.world.nature_pillar.upsert_world_model(
                tick, subject, cause, 0.4, status="hypothesis", source="nature_causal_reasoning",
                revises_id=existing["id"] if existing is not None else None,
            )
            self.world.nature_pillar.remember(f"Wondered why the grazing herds vanished: {cause}")
            ontology.register_causal_thread(
                self.world, subject=subject, chain=context_bits + [cause], tick=tick, settlement_id=None,
            )
            self._append_emergence(
                "anomaly", "ecology", f"The land wonders why its grazing herds vanished: {cause}",
                ('nature',), data={"pillar_entry_id": entry["id"]},
            )
            # Same reasoning as the predator trigger's apply(): doesn't
            # own Nature's observe/interpret cycle_stage, so it never
            # calls _pillar_close_cycle("nature").

        self._schedule_llm_job(
            "nature_causal_reasoning", prompt, nature_causal_reasoning.SYSTEM_PROMPT, fallback, apply,
            critical=True,
        )
        return True

    def _maybe_react_to_succession_stall(self) -> bool:
        """Third Nature causal-reasoning trigger, the design note's
        third named candidate: a fallow grassland tile that's stayed
        eligible-to-reclaim for well past its own effective fallow
        requirement (`NATURE_SUCCESSION_STALL_WEEKS_MULTIPLIER *
        REFOREST_MIN_FALLOW_WEEKS`) despite locally favorable moisture
        (`NATURE_SUCCESSION_STALL_MOISTURE_MIN`) — genuinely puzzling
        bad luck on `REFOREST_CHANCE_PER_WEEK`'s own weekly roll, not
        an obvious dry-ground explanation. Picks the single
        worst-stalled QUALIFYING tile (favorable moisture, past
        threshold) each check; a tile stalled on genuinely dry ground
        is skipped entirely (not flagged), so a later tick can still
        react once either a wetter qualifying tile appears or this
        same tile's own moisture improves."""
        threshold = REFOREST_MIN_FALLOW_WEEKS * NATURE_SUCCESSION_STALL_WEEKS_MULTIPLIER
        candidates = [
            (pos, weeks) for pos, weeks in self.world.fallow_ticks.items()
            if weeks >= threshold and self.world.hydrology_field.at(*pos) >= NATURE_SUCCESSION_STALL_MOISTURE_MIN
        ]
        if not candidates:
            self._nature_succession_stall_flagged = False
            return False
        if self._nature_succession_stall_flagged:
            return False
        if self._reactive_pillar_backpressured("nature", "succession_stall"):
            return False
        self._nature_succession_stall_flagged = True
        (x, y), weeks = max(candidates, key=lambda item: item[1])
        moisture = self.world.hydrology_field.at(x, y)
        anomaly_text = (
            f"A stretch of open grassland at ({x}, {y}) has stood ready to become forest again for "
            f"{weeks} weeks now, surrounded by trees and soaked with rain, yet nothing has taken root there."
        )
        context_bits = [
            f"local soil moisture there: {round(moisture, 2)}",
            f"weeks stalled: {weeks}",
            f"season: {self.world.clock.season}",
        ]
        existing_beliefs = list(self.world.nature_beliefs)
        prompt = nature_causal_reasoning.build_prompt(anomaly_text, context_bits, existing_beliefs)
        fallback = nature_causal_reasoning.fallback_cause()
        tick = self.world.clock.tick_count

        def apply(result: dict, used_fallback: bool) -> None:
            cause = nature_causal_reasoning.parse_cause(result)
            if not cause:
                return
            subject = f"the stalled clearing at ({x}, {y})"
            existing = self.world.nature_pillar.find_world_model_entry(subject)
            entry = self.world.nature_pillar.upsert_world_model(
                tick, subject, cause, 0.4, status="hypothesis", source="nature_causal_reasoning",
                revises_id=existing["id"] if existing is not None else None,
            )
            self.world.nature_pillar.remember(f"Wondered why the clearing at ({x}, {y}) hasn't regrown: {cause}")
            ontology.register_causal_thread(
                self.world, subject=subject, chain=context_bits + [cause], tick=tick, settlement_id=None,
            )
            self._append_emergence(
                "anomaly", "ecology", f"The land wonders why a clearing at ({x}, {y}) won't regrow: {cause}",
                ('nature',), data={"pillar_entry_id": entry["id"]},
            )
            # Same reasoning as the other two triggers' apply(): no
            # _pillar_close_cycle("nature") call here either.

        self._schedule_llm_job(
            "nature_causal_reasoning", prompt, nature_causal_reasoning.SYSTEM_PROMPT, fallback, apply,
            critical=True,
        )
        return True

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
        swap = self.world.population._maybe_rotate_core_cast(
            rotation_rng, humans_lean=lambda a: self.world.humans_pillar.subject_confidence(a.name),
        )
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
        if self._pillar_interpret_backpressured("nature"):
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
            # Tier 0's twentieth conversion (docs/ROADMAP-2026-07-
            # REMAINING.md), explicit user decision extending v1.34.9's
            # one-time Phase G carve-out (that pass scoped it to
            # omen's own world_model mirror only): the WHICH-subject
            # pick among candidates now also leans toward whichever
            # subject `nature_pillar` already has a standing theory
            # about, via the same `subject_confidence` primitive every
            # other Tier 0 site uses — never a certainty (uniform
            # weight 1.0 floor), and honestly often a true no-op since
            # Nature's own content is ecological, not usually agent-
            # or-institution-named. Phase G's own ambiguity discipline
            # is otherwise completely unchanged — this only shifts
            # WHICH already-eligible candidate an omen might center on,
            # never whether one is confirmed as real.
            rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "omen_subject_pick")
            weights = [
                1.0 + self.world.nature_pillar.subject_confidence(name) * NATURE_OMEN_SUBJECT_LEAN_MAX
                for name in subject_candidates
            ]
            subject_name = rng.choices(subject_candidates, weights=weights, k=1)[0]
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
            self._append_emergence(
                "anomaly", "ecology", f"The land offered an omen: {omen}",
                ('nature',),
            )
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

    SETTLEMENT_TRADE_SURPLUS_THRESHOLD = 0.7
    """A16 "trade-as-network-flow": a named settlement above this
    fraction of `MATERIALS_CAPACITY` is a real trade SOURCE this
    month. Deliberately the mirror of `INVENTION_MATERIALS_FRACTION`-
    style thresholds elsewhere in this file — genuinely well-off, not
    merely non-critical."""

    SETTLEMENT_TRADE_DEFICIT_THRESHOLD = 0.3
    """The mirror threshold below which a named settlement is a real
    trade SINK — the same 0.3 fraction `Population._maybe_repair`'s
    materials-critical check (agents/population.py) already uses for
    "genuinely struggling," reused rather than inventing a second
    scarcity line."""

    SETTLEMENT_TRADE_CAPACITY_SCALE = 0.3
    """Scales a `Settlement.relations` edge (0..1, already clamped
    non-negative by `build_settlement_trade_graph`) into a real
    materials-flow capacity for that edge, in `MATERIALS_CAPACITY`
    units: a fully warm (1.0) direct relation can carry up to 30% of
    one settlement's full capacity per month; a cold or absent
    relation carries none. Deliberately small — trade is real help,
    never enough on its own to instantly erase either settlement's
    surplus or deficit in one month."""

    def _maybe_tick_settlement_trade(self, events: list[str]) -> None:
        """A16 "trade-as-network-flow" (docs/ROADMAP-2026-07-
        REMAINING.md), closing A16 entirely. Monthly, deterministic
        (objective economic reality, same domain as `_maybe_tick_
        market_prices`/caravan's own unconditional exchange — never
        gated behind the LLM). `Settlement.relations` was already a
        real weighted inter-settlement graph (seeded at fission, nudged
        by cross-settlement dialogue), but every prior consumer
        (`market_relation_factor`/`caravan_relation_factor`) only ever
        read a flat AVERAGE across it. This is the first genuine PER-
        PAIR routing question: the settlement in the deepest materials
        surplus supplies the one in the deepest deficit, routed through
        `graph_algorithms.max_flow` over the real relations graph — a
        cold DIRECT relation between them doesn't necessarily block
        trade if a third settlement they're both warm toward can carry
        it, the genuinely distinct thing a flow algorithm proves that a
        flat pairwise multiplier structurally cannot express."""
        if "month_end" not in events:
            return
        named = [s for s in self.world.settlements if s.name]
        if len(named) < 2:
            return
        surplus_threshold = MATERIALS_CAPACITY * self.SETTLEMENT_TRADE_SURPLUS_THRESHOLD
        deficit_threshold = MATERIALS_CAPACITY * self.SETTLEMENT_TRADE_DEFICIT_THRESHOLD
        source = max(named, key=lambda s: s.materials - surplus_threshold)
        sink = min(named, key=lambda s: s.materials - deficit_threshold)
        if source.id == sink.id or source.materials <= surplus_threshold or sink.materials >= deficit_threshold:
            return
        graph = graph_algorithms.build_settlement_trade_graph(named)
        capacity_scale = MATERIALS_CAPACITY * self.SETTLEMENT_TRADE_CAPACITY_SCALE
        scaled_graph = {
            node: {other: weight * capacity_scale for other, weight in edges.items()}
            for node, edges in graph.items()
        }
        flow_capacity = graph_algorithms.max_flow(scaled_graph, source.id, sink.id)
        if flow_capacity <= 0.0:
            return  # no route with any real relations warmth connects them, even indirectly
        transfer = min(flow_capacity, source.materials - surplus_threshold, deficit_threshold - sink.materials)
        if transfer <= 0.0:
            return
        source.materials -= transfer
        sink.materials = min(MATERIALS_CAPACITY, sink.materials + transfer)
        self._log("caravan", f"{source.name} sent aid to {sink.name} — {transfer:.0f} materials, along the trade routes between them.")
        self._append_emergence(
            "opportunity", "economy", f"{source.name} sent materials aid to {sink.name}.", ("village",),
        )

    def _maybe_schedule_record(self) -> None:
        """Written artifacts: `Population._apply_deaths` decided this
        tick that a departing villager leaves a record (an objective
        fact); the LLM (or fallback, assembled from the same memories)
        authors its text in the background. See llm/artifacts.py."""
        for candidate in self.world.population.last_written_records:
            if self._pillar_interpret_backpressured("humans"):
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
        self.world.humans_pillar.remember(f"{author} left a written record behind: \"{text}\"")
        self._append_emergence(
            "opportunity", "narrative", f"{author} left a written record behind: \"{text}\"",
            ('humans',),
        )

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
            if self._pillar_interpret_backpressured("humans"):
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
            if not used_fallback:
                self.world.humans_pillar.remember(f"{target.name} came into their own sense of self: {target.mind}")
                self._append_emergence(
                    "opportunity", "psychology", f"{target.name} came into their own sense of self: {target.mind}",
                    ('humans',),
                )
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
            if self._pillar_interpret_backpressured("humans"):
                return
            self._pending_mind_agent_ids.pop(0)
            self._author_one_mind(agent)
            return  # one retry per tick — let it compete fairly with every other job

    def _maybe_schedule_dispute(self) -> None:
        """LLM-mediated dispute resolution — see llm/dispute.py and
        Population.due_for_dispute/apply_dispute. Backpressure is
        checked *before* selection so a saturated queue doesn't burn a
        pair's cooldown on a job that never got scheduled.

        Tier 0's nineteenth conversion (docs/ROADMAP-2026-07-
        REMAINING.md), explicit user decision: `due_for_dispute` now
        collects every eligible festering pair each tick instead of
        stopping at the first, then leans the pick toward whichever
        pair Humans' own attention already returns to. The pillar
        lookup itself is passed as a lazy callable so it only ever
        runs against the candidates `due_for_dispute` actually finds
        (typically zero or a handful), never the whole population."""
        if self._effective_backlog() >= self._current_backpressure_limit():
            return
        pair = self.world.population.due_for_dispute(
            self.world.clock.tick_count, DISPUTE_COOLDOWN_TICKS,
            humans_lean=lambda a: self.world.humans_pillar.subject_confidence(a.name),
        )
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
                    # Tier 0 (25th site, new producer): a category-keyed
                    # (not agent/institution-keyed) Village belief, same
                    # shape as Nature's species-keyed producer (v1.34.
                    # 106/107) — the literal word "dispute_feud" is the
                    # subject, revised in place across repeated firings.
                    # Real consumer: `_maybe_schedule_laws`'s pattern_
                    # key pick.
                    existing_signal = self.world.village_pillar.find_world_model_entry("dispute_feud")
                    self.world.village_pillar.upsert_world_model(
                        self.world.clock.tick_count, "dispute_feud",
                        f"{dispute_settlement.name or 'the village'} keeps seeing disputes harden into feuds.",
                        min(1.0, 0.3 + counts["dispute_feud"] * 0.1), status="observation", source="dispute",
                        revises_id=existing_signal["id"] if existing_signal else None,
                    )
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
        humans_lean = {
            a.id: self.world.humans_pillar.subject_confidence(a.name) for a in members
        }
        candidate = self.world.population._detect_faction_candidate(
            faction_target, members, humans_lean=humans_lean,
        )
        if candidate is None:
            return
        if self._pillar_interpret_backpressured("village"):
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
            self._append_emergence(
                "unexplained_shift", "population", f"A faction calling itself {name} has formed: {framing}",
                ('village', 'humans'),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a second Village->Humans arrow: a newly-named
            # faction is a real social fact about specific living
            # people — worth handing directly to Humans' pillar, not
            # just left in the shared Emergence stream.
            self._send_pillar_message(
                "village", "humans", "observation",
                f"a faction calling itself {name} has formed: {framing}",
            )

        # Cultural evolution: naming a real detected faction (v1.3.37).
        self._schedule_llm_job("faction", prompt, faction.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

    def _maybe_schedule_guild_founding(self, events: list[str]) -> None:
        """Deliberate institution founding — see llm/founding.py and
        Population.deliberate_guild_candidate/found_guild. Monthly roll
        cadence: an ambitious master mulling this over is a rare,
        deliberate act, not a per-tick scan.

        Tier 0's sixteenth conversion (docs/ROADMAP-2026-07-REMAINING.
        md): the founder pick among tied-eligible masters now also
        weighs `humans_pillar.subject_confidence(agent.name)` —
        computed here (not in `population.py`, which deliberately
        doesn't reference pillar state) and passed as `humans_lean`,
        same "compute at the call site" shape `_voice_narrative_extra_
        scores` already established."""
        guild_target = self._job_target()
        if not self._monthly_gate(events, "guild_founding") or not guild_target.name:
            return
        members = [a for a in self.world.population.agents if a.settlement_id == guild_target.id]
        humans_lean = {
            a.id: self.world.humans_pillar.subject_confidence(a.name) * GUILD_FOUNDER_HUMANS_LEAN_MAX
            for a in members
        }
        # Tier 0 (28th site): reuses this job's own existing mirror
        # ("the {skill} guild", written below in apply() since v0.64.0-
        # era work) — no new producer needed, `subject_confidence`'s
        # substring match already catches a bare skill name against
        # that subject.
        skill_lean = {
            skill: self.world.village_pillar.subject_confidence(skill)
            for skill in (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE)
        }
        candidate = self.world.population.deliberate_guild_candidate(
            guild_target, members, humans_lean=humans_lean, skill_lean=skill_lean,
        )
        if candidate is None:
            return
        if self._pillar_interpret_backpressured("village"):
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
                # Observe/interpret cycling, first slice (docs/ROADMAP-
                # 2026-07-REMAINING.md): a Tier 0 mirror write now also
                # feeds the Emergence API (A22), so it can reach
                # Village's own observe/interpret cycle
                # (`_pillar_observe_turn`/`_maybe_schedule_beliefs`) as
                # a real perceived signal, not just a direct world_
                # model write that bypasses the pillar's perception
                # channel entirely.
                self._append_emergence(
                    "novel_combination", "institution", f"A {skill} guild was founded — \"{reason}\"",
                    ("village",),
                )
                # B4 "Inter-pillar consciousness bus" (roadmap Stage
                # III step 11), a new Village->Innovation arrow: a
                # deliberately founded guild is itself an institution
                # organized around a skill — real grounding material
                # for what Innovation might notice/build on next, same
                # reasoning as Nature->Innovation's species_variant
                # arrow.
                self._send_pillar_message(
                    "village", "innovation", "discovery", f"a {skill} guild was founded — \"{reason}\"",
                )

        # Major life decision: deliberately founding a guild (v1.3.37).
        self._schedule_llm_job("guild_founding", prompt, founding.SYSTEM_PROMPT, fallback, apply, deep_reasoning=True)

    def _maybe_schedule_institution_belief(self, events: list[str]) -> None:
        """Institutions Stage 3: once a month, ONE institution with
        living members forms/revises a theory of its own — no longer
        only mirrored copies of settlement beliefs. See
        beliefs.INSTITUTION_SYSTEM_PROMPT for the design note.

        Tier 0's fifth mirror-write -> pillar-authored conversion
        (docs/ROADMAP-2026-07-REMAINING.md): unlike the first four
        sites (which bias WHAT a decision concludes), this one biases
        WHICH institution gets examined this month — the village's own
        accumulated attention (institutions it already holds a
        confident recent theory about, via `village_pillar.subject_
        confidence(institution.name)`) makes that institution somewhat
        more likely to be picked again, layered as a weighted draw over
        the same uniform candidate pool rather than narrowing it. Never
        a hard filter — every eligible institution keeps a real, non-
        zero chance (`INSTITUTION_BELIEF_TARGET_LEAN_WEIGHT` bounds how
        much a lean can multiply the base weight of 1.0). A candidate
        with an empty `name` (COUNCIL has none) or no matching recent
        world_model entry reads as a flat 1.0 — every-candidate-tied
        weights, so `rng.choices` draws uniformly, the same real
        distribution `rng.choice` gave before (determinism/RNG-
        consumption-order parity is explicitly not a project
        requirement, per CLAUDE.md; only the resulting behavior needs
        to match, and it does)."""
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
        if self._pillar_interpret_backpressured("village"):
            return
        self._mark_monthly_resolved("institution_belief")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "institution_belief")
        weights = [
            1.0 + self.world.village_pillar.subject_confidence(c.name) * INSTITUTION_BELIEF_TARGET_LEAN_WEIGHT
            for c in candidates
        ]
        institution = rng.choices(candidates, weights=weights, k=1)[0]
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
        objective = institutions.compute_objective(
            institution, inst_target.summary(), council_disposition,
            village_pillar_lean=self._village_priority_lean(),
        )
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
            self._append_emergence(
                "opportunity", "institution", f"The {label} came to believe of {parsed['subject']}: {parsed['belief']}",
                ("village",),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a seventh Village->Humans arrow: an
            # institution's own theory is a real belief held by its
            # specific living members — worth Humans' pillar knowing
            # directly.
            self._send_pillar_message(
                "village", "humans", "observation",
                f"the {label} came to believe of {parsed['subject']}: {parsed['belief']}",
            )

        # Council deliberation (and FAMILY/GUILD's own equivalent):
        # institutional belief formation is genuine collective judgment
        # (v1.3.37).
        self._schedule_llm_job(
            "institution_belief", prompt, beliefs.INSTITUTION_SYSTEM_PROMPT, fallback, apply,
            deep_reasoning=True, num_predict_mult=LARGE_SCHEMA_REASONING_NUM_PREDICT_MULT,
        )

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
        if self._pillar_interpret_backpressured("village"):
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
            self.world.village_pillar.remember(f"Between {stl_a.name} and {stl_b.name}: {narration}")
            self._append_emergence(
                "unexplained_shift", "settlement", f"Between {stl_a.name} and {stl_b.name}: {narration}",
                ('village',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), an eighth Village->Humans arrow: a named
            # diplomatic moment shifts a real relationship between
            # settlements' populations — worth Humans' pillar knowing
            # directly.
            self._send_pillar_message(
                "village", "humans", "observation",
                f"between {stl_a.name} and {stl_b.name}: {narration}",
            )

        self._schedule_llm_job(
            "diplomacy", prompt, diplomacy.SYSTEM_PROMPT, fallback, apply,
            settlement=a.name, structured_input={"relation": relation, "other_settlement": b.name},
        )

    # --- item 8c / §7 item 7: laws, customs, taboos -----------------------------

    _LAW_PATTERN_TEXT = {
        "theft": "repeated theft among its own people",
        "dispute_feud": "repeated bitter disputes boiling into feuds",
        "materials_bottleneck": "running short on materials again and again",
        "housing_shortage": "too many people packed into too few homes",
        "food_shortage": "the granaries running dangerously low",
        "disease_outbreak": "sickness taking hold again and again",
        "currency_shortage": "the coffers running dangerously bare",
        "starvation_death": "hunger claiming lives again and again",
        "wildlife_recolonization": "wildlife pressing back into the land again and again",
        "council_gridlock": "the council splitting into rival camps, unable to agree",
        "guild_decline": "a guild's craft dying out for want of a master",
        "family_extinction": "family lines dying out, one after another",
        "diplomatic_hostility": "hostility with a neighboring settlement, again and again",
        "faction_rivalry": "two factions turning on each other, again and again",
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
            # Tier 0 (27th site, new producer): materials_bottleneck is
            # a genuine THIRD option here, not just a tiebreak input —
            # see `_detect_settlement_bottlenecks`'s mirror for the
            # producer half.
            "materials_bottleneck": target.pattern_signal_counts.get("materials_bottleneck", 0),
            # Tier 0, new producer: a genuine FOURTH option, same shape
            # — see `_detect_housing_shortage`'s mirror for the
            # producer half.
            "housing_shortage": target.pattern_signal_counts.get("housing_shortage", 0),
            # Tier 0, new producer: a genuine FIFTH option, same shape
            # — see `_detect_food_shortage`'s mirror for the producer
            # half.
            "food_shortage": target.pattern_signal_counts.get("food_shortage", 0),
            # Tier 0: a genuine SIXTH option needing no new producer —
            # `disease_outbreak` already has a real `pattern_signal_
            # counts` counter and a real `village_pillar` mirror (see
            # `_bump_village_pattern_signal`'s call site in `_maybe_
            # promote_ritual`'s sibling loop), previously consumed only
            # by the ontology-proposal pressure-signal tiebreak. A
            # settlement repeatedly seeing sickness take hold can now
            # produce a real public-health law, not just influence what
            # Innovation invents.
            "disease_outbreak": target.pattern_signal_counts.get("disease_outbreak", 0),
            # Tier 0, new producer (explicit user decision: "Currency
            # shortage producer"): a genuine SEVENTH option, same
            # shape — see `_detect_currency_shortage`'s mirror for the
            # producer half.
            "currency_shortage": target.pattern_signal_counts.get("currency_shortage", 0),
            # Tier 0: a genuine EIGHTH option needing no new producer,
            # same shape as `disease_outbreak`'s conversion —
            # `starvation_death` already has a real `pattern_signal_
            # counts` counter and a real `village_pillar` mirror (same
            # `_bump_village_pattern_signal` call site), previously
            # consumed only by the ontology-proposal pressure-signal
            # tiebreak. A settlement repeatedly losing people to hunger
            # can now produce a real famine-relief/rationing law.
            "starvation_death": target.pattern_signal_counts.get("starvation_death", 0),
            # Tier 0, explicit user decision via `AskUserQuestion`: a
            # genuine NINTH option needing no new producer, same
            # pattern as `disease_outbreak`/`starvation_death`'s
            # conversions — `wildlife_recolonization` already has a
            # real `pattern_signal_counts` counter and a real
            # `village_pillar` mirror (same `_bump_village_pattern_
            # signal` call site), previously consumed only by the
            # ontology-proposal pressure-signal tiebreak. A settlement
            # repeatedly seeing wildlife press back into its farmland
            # can now produce a real hunting-rights/land-use law.
            "wildlife_recolonization": target.pattern_signal_counts.get("wildlife_recolonization", 0),
            # Tier 0, explicit user decision via `AskUserQuestion`: a
            # genuine TENTH option — see `_detect_council_gridlock`'s
            # mirror for the producer half. A council that keeps
            # failing to agree can produce a real reform/succession
            # law.
            "council_gridlock": target.pattern_signal_counts.get("council_gridlock", 0),
            # Tier 0, explicit user decision via `AskUserQuestion`: a
            # genuine ELEVENTH option — see `_detect_guild_decline`'s
            # mirror for the producer half. A dying craft can produce a
            # real apprenticeship/guild-support law.
            "guild_decline": target.pattern_signal_counts.get("guild_decline", 0),
            # Tier 0, explicit user decision: a genuine TWELFTH option
            # — see `_detect_family_extinction`'s mirror for the
            # producer half. Vanishing family lines can produce a real
            # inheritance/succession law.
            "family_extinction": target.pattern_signal_counts.get("family_extinction", 0),
            # Tier 0, new producer: a genuine THIRTEENTH option — see
            # `_detect_diplomatic_hostility`'s mirror for the producer
            # half. Sustained hostility with a neighbor can produce a
            # real border-defense/militia law.
            "diplomatic_hostility": target.pattern_signal_counts.get("diplomatic_hostility", 0),
            # Tier 0, explicit user decision via `AskUserQuestion`: a
            # genuine FOURTEENTH option — see `_detect_faction_
            # rivalry`'s mirror for the producer half. Sustained
            # factional strife can produce a real reconciliation law.
            "faction_rivalry": target.pattern_signal_counts.get("faction_rivalry", 0),
        }
        # Tier 0 (25th site): a genuine tie in real occurrence count
        # breaks toward whichever category village_pillar's new
        # category-keyed producer (see the dispute_feud/theft/
        # materials_bottleneck mirrors above) already has a standing
        # theory about — real occurrences stay the sole determinant
        # except in a tie.
        pattern_key = max(
            candidates, key=lambda k: (candidates[k], self.world.village_pillar.subject_confidence(k)),
        )
        occurrences = candidates[pattern_key]
        initiated_by_conviction = False
        if occurrences < LAW_SIGNAL_THRESHOLD:
            # C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-
            # 2026-07-22.md's Part C, Tier 3, "change law"): before
            # giving up, check whether Village's own standing conviction
            # about a category with at least SOME real recent recurrence
            # is confident enough to genuinely INITIATE a law proposal on
            # its own, ahead of fresh occurrences re-crossing the full
            # threshold. This is the real intention, not a tiebreak —
            # `subject_confidence` can stay high from BEFORE a prior
            # enactment reset the raw counter (see apply()'s reset
            # below), so this captures the village genuinely acting on
            # unresolved conviction, not just fresh hardship. Still
            # requires occurrences >= 1 everywhere below — Body stays
            # authoritative, conviction only bypasses the FULL threshold.
            convicted = [
                k for k, count in candidates.items()
                if count >= 1
                and self.world.village_pillar.subject_confidence(k) >= VILLAGE_PATTERN_CONVICTION_LAW_THRESHOLD
            ]
            if not convicted:
                return
            pattern_key = max(convicted, key=lambda k: self.world.village_pillar.subject_confidence(k))
            occurrences = candidates[pattern_key]
            initiated_by_conviction = True
        if self._pillar_interpret_backpressured("village"):
            return
        self._mark_monthly_resolved("laws")
        pattern_text = self._LAW_PATTERN_TEXT.get(pattern_key, pattern_key)
        prompt = laws.build_prompt(target.name, pattern_text, occurrences, target.laws, remembered=initiated_by_conviction)
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
            # Generalized to 3+ candidates (Tier 0's 27th site added
            # materials_bottleneck) — theft lives in a separate dict
            # from every other pattern-signal-sourced candidate.
            if pattern_key == "theft":
                stl.law_signal_counts["theft"] = 0
            else:
                stl.pattern_signal_counts[pattern_key] = 0
            # C2 "Intention channel": if this proposal was genuinely
            # INITIATED by village_pillar's own standing conviction (see
            # the scheduling site above), that conviction is now
            # confirmed — a real law followed from it, so its own mirror
            # entry is reinforced to full confidence in place, closing
            # the conviction -> action -> confirmation loop rather than
            # leaving it to just sit there unacted-on.
            if initiated_by_conviction:
                conviction_entry = self.world.village_pillar.find_world_model_entry(pattern_key)
                if conviction_entry is not None:
                    self.world.village_pillar.upsert_world_model(
                        tick, pattern_key, conviction_entry["belief"], 1.0,
                        status="observation", source="laws_conviction_confirmed",
                        revises_id=conviction_entry["id"],
                    )
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
            self._append_emergence(
                "opportunity", "institution", f"Came to hold a {parsed['kind']}: {parsed['text']}",
                ('village',),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a second Village->Reflection arrow: a newly-
            # enacted law/custom/taboo (like a trigger rule) is a real
            # normative self-modification of the settlement's own
            # behavior, worth Reflection's meta-cognition seeing
            # directly.
            self._send_pillar_message(
                "village", "reflection", "observation",
                f"came to hold a {parsed['kind']}: {parsed['text']}",
            )

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
        same discipline as memory_drift.

        Tier 0's seventh mirror-write -> pillar-authored conversion
        (docs/ROADMAP-2026-07-REMAINING.md): same `humans_pillar.
        subject_confidence(agent.name)` weighting `_maybe_schedule_
        memory_drift` gained — `_maybe_schedule_personal_belief`'s own
        candidate pool falls back to ANY agent with memories (not only
        core cast) once no core-cast agent is having a significant
        moment, so a non-core agent can genuinely already carry a
        `humans_pillar.world_model` entry of their own; when they do,
        they're somewhat more likely to be this month's nudge target
        too. Never narrows the pool."""
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
        if self._pillar_interpret_backpressured("humans"):
            return
        self._mark_monthly_resolved("noncore_nudge")
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "noncore_nudge")
        weights = [
            1.0 + self.world.humans_pillar.subject_confidence(c.name) * HUMANS_PERSONAL_TARGET_LEAN_WEIGHT
            for c in candidates
        ]
        agent = rng.choices(candidates, weights=weights, k=1)[0]
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
                self._append_emergence(
                    "unexplained_shift", "psychology", f"{target_agent.name} had a quiet realization: {reflection}",
                    ('humans',),
                )
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
        # Tier 0's fifteenth conversion (docs/ROADMAP-2026-07-
        # REMAINING.md): previously the FIRST eligible core-cast sender
        # in `population.agents` iteration order won outright (an
        # accident of storage order, not a meaningful choice) — now
        # every eligible sender in the target settlement is collected
        # (still each sender's own first qualifying recipient, same as
        # before), then `humans_pillar.subject_confidence(sender.name)`
        # picks among them: the sender Humans' own attention already
        # returns to is somewhat more likely to be this month's letter-
        # writer. `max`'s first-max-wins tiebreak means with no lean
        # anywhere (the common case) this reproduces the exact prior
        # first-found pick byte-for-byte.
        candidates: list[tuple] = []
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
                    candidates.append((agent, other))
                    break
        if candidates:
            sender, recipient = max(
                candidates, key=lambda pair: self.world.humans_pillar.subject_confidence(pair[0].name),
            )
        else:
            sender, recipient = None, None
        if sender is None:
            return
        if self._pillar_interpret_backpressured("humans"):
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
            self._append_emergence(
                "opportunity", "relationship", f"{sender_name} wrote to {recipient_name}: {text}",
                ('humans',),
            )

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
                        humans_lean=lambda a: self.world.humans_pillar.subject_confidence(a.name),
                    )
            stl.pending_letters = remaining

    def _tick_districts(self) -> None:
        """D6 "social scaling" (docs/ROADMAP-2026-07-REMAINING.md,
        explicit user directive): daily (day_end) cadence for the
        District mechanism — see `hearthmind.settlement.district`'s
        module docstring for the full design. First collectivizes any
        settlement's excess individually-simulated population past
        `district.DISTRICT_INDIVIDUAL_CAP`, then ticks every existing
        district's own demography/economy one day. Zero LLM cost —
        same "cheap deterministic aggregate" treatment as FarmGrid/
        WildlifeGrid, not a cognition job. Deliberate scope trim,
        recorded here rather than left implicit: `carrying_capacity()`
        is NOT adjusted for collectivized population this pass — a
        district's residents are tracked as a separate, additive
        population figure so existing individually-simulated population
        balance/tuning isn't disturbed without the ability to live-test
        the impact; folding districts into carrying capacity is
        flagged future work, not an oversight."""
        newly_founded = self.world.population._maybe_collectivize_excess_population(
            self.world.settlements, self.world.clock.tick_count,
            humans_lean=lambda a: self.world.humans_pillar.subject_confidence(a.name),
        )
        for settlement, district_name in newly_founded:
            self._log(
                "district_founded",
                f"{settlement.name} has grown too large for every face to be known — "
                f"a new quarter takes shape: {district_name}.",
            )
            self._append_highlight(
                "district_founded",
                f"{settlement.name} grows a new quarter, {district_name}, as its population "
                "outgrows what any one person can know.",
            )
            self.world.village_pillar.remember(
                f"{settlement.name} grew a new district, {district_name} — the settlement is "
                "now too large for every resident to be known individually.",
            )
            self._append_emergence(
                "opportunity", "settlement", f"{settlement.name} founded a new district: {district_name}",
                ("village",), settlement=settlement.name,
            )
        dissolved = self.world.population.tick_districts(self.world.settlements)
        for settlement, district_name in dissolved:
            self._log(
                "district_dissolved",
                f"{district_name} in {settlement.name} has emptied out entirely.",
            )
            self._append_emergence(
                "unexplained_shift", "settlement", f"{district_name} in {settlement.name} dissolved — its population is gone",
                ("village",), settlement=settlement.name,
            )

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
            # A1 FieldGrid: prefer a region the live `scent` field
            # doesn't already read as dangerous, when an alternative
            # exists — never a hard block.
            safe = [
                pos for pos in spots
                if self.world.fields.get_at(
                    "scent", pos, self.world.config.width, self.world.config.height,
                ) < SCENT_FISSION_AVOID_THRESHOLD
            ]
            if safe:
                spots = safe
            # A1 FieldGrid: prefer a region the live `fertility` field
            # already reads as good farmland, when one exists — never a
            # hard block, and the one POSITIVE region-field preference
            # here (density/scent both only ever avoid).
            fertile = [
                pos for pos in spots
                if self.world.fields.get_at(
                    "fertility", pos, self.world.config.width, self.world.config.height,
                ) >= FERTILITY_FISSION_PREFER_THRESHOLD
            ]
            if fertile:
                spots = fertile
            # A1 FieldGrid: avoid a region the live `hazard` field
            # already reads as heavily disaster-scarred, when a safer
            # alternative exists — never a hard block.
            unscarred = [
                pos for pos in spots
                if self.world.fields.get_at(
                    "hazard", pos, self.world.config.width, self.world.config.height,
                ) < HAZARD_FISSION_AVOID_THRESHOLD
            ]
            if unscarred:
                spots = unscarred
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
        uses. Declining is a real outcome.

        Tier 0's seventeenth conversion (docs/ROADMAP-2026-07-
        REMAINING.md): the leader pick among already-eligible would-be
        leaders now also weighs `humans_pillar.subject_confidence(
        agent.name)`, same shape as `_maybe_schedule_guild_founding`'s
        `humans_lean`."""
        if not self._monthly_gate(events, "fission"):
            return
        humans_lean = {
            a.id: self.world.humans_pillar.subject_confidence(a.name) * GUILD_FOUNDER_HUMANS_LEAN_MAX
            for a in self.world.population.agents
        }
        candidate = self.world.population.fission_candidate(
            self.world.settlements, self.world.clock.tick_count, humans_lean=humans_lean,
        )
        if candidate is None:
            return
        if self._pillar_interpret_backpressured("humans"):
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
            # lexicon. Tier 3 item 18 follow-up: `lineage_depth` makes
            # this a genuine recursive rewrite chain — a granddaughter
            # settlement (depth 2) drifts its inherited terms TWO
            # compounding rounds, not the same single mutation no matter
            # how many fissions removed from the original coinage.
            new_settlement.lineage_depth = home.lineage_depth + 1
            # A7 (roadmap Tier 3), layout domain: closes the item's own
            # "layout stays a single-application scoring bias with zero
            # lineage awareness" critique — a fission daughter's layout
            # style genuinely descends from its parent's (usually
            # unchanged, occasionally a real production-rule rewrite to
            # the next style in the fixed cycle), not an independent
            # `settlement_id % 3` hash uncorrelated with lineage.
            new_settlement.layout_style = drift_layout_style(
                home.effective_layout_style, seed=f"{new_id}:layout",
            )
            for entry in home.lexicon[-LEXICON_FISSION_DRIFT_COUNT:]:
                drifted = drift_term(entry["term"], steps=new_settlement.lineage_depth)
                if narrative_direction.validate_coined_term(drifted, new_settlement.lexicon):
                    new_settlement.lexicon.append({
                        "term": drifted, "meaning": entry["meaning"],
                        "formed_tick": self.world.clock.tick_count,
                    })
            self.world.settlements.append(new_settlement)
            population.depart_for_fission(
                party, new_settlement, site, self.world.clock.tick_count, home.name,
            )
            self.world.humans_pillar.remember(
                f"{leader.name} led {len(party)} settlers out of {home.name} — \"{reason}\""
            )
            self._append_emergence(
                "unexplained_shift", "settlement", f"{leader.name} led {len(party)} settlers out of {home.name} — \"{reason}\"",
                ('humans', 'village'),
            )
            self._log(
                "settlement_founded",
                f"{leader.name} led {len(party)} settlers out of {home.name}"
                f" toward a new home in the distance — \"{reason}\"",
            )
            # Observe/interpret cycling, first slice: also feeds the
            # Emergence API so both Humans and Village can perceive it
            # on their own next observe turn, not just record it.
            self._append_emergence(
                "unexplained_shift", "settlement",
                f"{leader.name} led {len(party)} settlers out of {home.name} — \"{reason}\"",
                ("humans", "village"),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a fourth Humans->Village arrow: a departing
            # party is a real settlement-shaping fact — worth Village
            # knowing directly, not just perceiving via the shared
            # Emergence stream.
            self._send_pillar_message(
                "humans", "village", "observation",
                f"{leader.name} led {len(party)} settlers out of {home.name} — \"{reason}\"",
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
        entirely unchanged.

        Tier 0's eighteenth conversion (docs/ROADMAP-2026-07-
        REMAINING.md): the "first found" pick below now goes through
        `humans_pillar.subject_confidence(agent.name)` via `max` —
        the candidate Humans' own attention already returns to is
        somewhat more likely to be this tick's considered candidate.
        `max`'s first-max-wins tiebreak reproduces the exact prior
        first-found pick when no lean exists anywhere."""
        candidates = self.world.population.core_migration_candidates(self.world.settlements)
        if not candidates:
            return
        if self._pillar_interpret_backpressured("humans"):
            return
        if _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "migration_decision_roll",
        ) >= MIGRATION_CHANCE_PER_TICK:
            return
        agent, target, push_reason = max(
            candidates, key=lambda c: self.world.humans_pillar.subject_confidence(c[0].name),
        )
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
            self._append_emergence(
                "unexplained_shift", "population", f"{target_agent.name} chose to leave: {reason}",
                ('humans', 'village'),
            )
            # B4 "Inter-pillar consciousness bus" (roadmap Stage III
            # step 11), a fifth Humans->Village arrow: an individual's
            # weighed decision to leave is a real fact shaping the
            # settlement's own population — worth Village knowing
            # directly.
            self._send_pillar_message(
                "humans", "village", "observation", f"{target_agent.name} chose to leave: {reason}",
            )

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
        against real signals before anything depends on it.

        Tier 5 B12's first real consumer (see `_emergence_compression`):
        an evicted entry is no longer simply discarded — it's ingested
        into a real `CompressionLadder`, which condenses it into an
        archived digest once enough have accumulated, rather than
        losing the stretch's content outright.

        Tier 7 HCA Stage A, A2: gated on SURPRISE, not occurrence (see
        `EMERGENCE_SURPRISE_THRESHOLD`'s own docstring) — a candidate is
        always scored through `self._emergence_surprise` (keyed by
        `f"{subsystem}:{kind}"`, so the specialist's running model
        updates for every candidate regardless of outcome), and only
        actually appended once its precision-weighted surprise clears
        the threshold. A routine, near-identical candidate genuinely
        stops reaching `emergence_log` once the specialist has learned
        to expect it — the direct fix for a soak-measured 93%
        `unexplained_shift` share dominated by 'content agent decided
        to socialize'."""
        surprise_key = f"{subsystem}:{kind}"
        surprise_value = magnitude if magnitude is not None else EMERGENCE_SURPRISE_NEUTRAL_MAGNITUDE
        surprise = self._emergence_surprise.score(surprise_key, surprise_value)
        self._emergence_surprise_attempted_total += 1
        if surprise < EMERGENCE_SURPRISE_THRESHOLD:
            self._emergence_surprise_suppressed_total += 1
            return
        observation = emergence.make_observation(
            self.world.next_emergence_id, self.world.clock.tick_count, kind, subsystem, summary,
            pillars, magnitude=magnitude, settlement=settlement, data=data,
        )
        self.world.next_emergence_id += 1
        self.world.emergence_log.append(observation)
        cap = self._effective_emergence_log_cap()
        if len(self.world.emergence_log) > cap:
            evicted = self.world.emergence_log[:-cap]
            self.world.emergence_log = self.world.emergence_log[-cap:]
            tick = self.world.clock.tick_count
            for entry in evicted:
                self._emergence_compression.ingest(entry, tick)
            self._emergence_compression.maybe_compress(
                CompressionStage.RAW, tick, EMERGENCE_COMPRESSION_RAW_THRESHOLD, _condense_emergence_entries,
            )
            self._emergence_compression.prune_to_capacity(EMERGENCE_COMPRESSION_ARCHIVE_MAX)

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
        self._detect_occupation_shortage()
        self._detect_housing_shortage()
        self._detect_food_shortage()
        self._detect_currency_shortage()
        self._detect_prosperity()
        self._detect_council_gridlock()
        self._detect_guild_decline()
        self._detect_grazer_abundance()
        self._detect_family_extinction()
        self._detect_diplomatic_hostility()
        self._detect_faction_rivalry()

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
                # Tier 0 (27th site, new producer): Village pillar's
                # THIRD category-keyed subject, same shape as the
                # dispute_feud/theft mirrors — revised in place across
                # repeated crossings. Real new consumer: `_maybe_
                # schedule_laws`'s candidates dict, a genuine third
                # option (not just a tiebreak) that can now win the
                # pattern_key pick outright and produce a real law.
                existing_bottleneck_signal = self.world.village_pillar.find_world_model_entry("materials_bottleneck")
                prior_bottleneck_confidence = (
                    existing_bottleneck_signal["confidence"] if existing_bottleneck_signal else 0.3
                )
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "materials_bottleneck",
                    f"{settlement.name or 'the village'} keeps running short on materials.",
                    min(1.0, prior_bottleneck_confidence + 0.1), status="observation", source="bottleneck",
                    revises_id=existing_bottleneck_signal["id"] if existing_bottleneck_signal else None,
                )
            elif not critical and was_flagged:
                self._materials_critical_flagged.discard(settlement.id)

    def _detect_occupation_shortage(self) -> None:
        """Tier 0, new producer (docs/ROADMAP-2026-07-REMAINING.md,
        explicit user decision via `AskUserQuestion`: "Design a new
        producer"). Village pillar's fourth category-keyed `world_
        model` subject (after dispute_feud/theft/materials_
        bottleneck), this one keyed by a literal `occupations.py`
        occupation string rather than a fixed pattern-signal label.

        Real signal: a settlement with a real, established labor force
        (living population at or above `OCCUPATION_SHORTAGE_
        POPULATION_THRESHOLD`) has zero living holders of some
        occupation — MAYOR excluded (its cap of one living holder
        makes "zero" the expected steady state half the time, not a
        real shortage). Same edge-triggered discipline as `_detect_
        settlement_bottlenecks`/`_detect_hydrology_drought`: one
        `bottleneck` observation the tick a (settlement, occupation)
        pair first crosses into shortage, silence while it stays
        there, silent recovery once anyone takes up the trade. Riding
        the same daily-metrics cadence, no new polling loop."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            living = [a for a in self.world.population.agents if a.settlement_id == settlement.id]
            if len(living) < OCCUPATION_SHORTAGE_POPULATION_THRESHOLD:
                continue
            held = {a.occupation for a in living if a.occupation}
            for occ in ALL_OCCUPATIONS:
                if occ == OCCUPATION_MAYOR:
                    continue
                key = (settlement.id, occ)
                shortage = occ not in held
                was_flagged = key in self._occupation_shortage_flagged
                if shortage and not was_flagged:
                    self._occupation_shortage_flagged.add(key)
                    self._append_emergence(
                        "bottleneck", "settlement",
                        f"{settlement.name} has no {occ} to speak of, despite its size.",
                        pillars=("village",), magnitude=0.6, settlement=settlement.name,
                        data={"occupation": occ, "population": len(living)},
                    )
                    existing = self.world.village_pillar.find_world_model_entry(occ)
                    prior_confidence = existing["confidence"] if existing else 0.3
                    self.world.village_pillar.upsert_world_model(
                        self.world.clock.tick_count, occ,
                        f"{settlement.name} could use a {occ} — nobody has taken up the trade.",
                        min(1.0, prior_confidence + 0.1), status="observation", source="occupation_shortage",
                        revises_id=existing["id"] if existing else None,
                    )
                elif not shortage and was_flagged:
                    self._occupation_shortage_flagged.discard(key)

    def _detect_housing_shortage(self) -> None:
        """Tier 0, new producer (explicit user instruction: "build new
        sites"). Village pillar's fifth category-keyed `world_model`
        subject, same shape as `_detect_occupation_shortage` — reuses
        `Population._housing_pressure` (population / hut capacity,
        already computed for `_maybe_migrate`'s disaster-refugee push
        signal) rather than duplicating the capacity math. Same edge-
        triggered discipline: one `bottleneck` observation the tick a
        settlement first crosses into genuine overcrowding, silence
        while it stays there, silent recovery once it eases. Riding the
        same daily-metrics cadence as its siblings, no new polling
        loop.

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine FOURTH option (not just a tiebreak input) —
        `"housing_shortage"` can now win the `pattern_key` pick outright
        and produce a real law, same shape `materials_bottleneck`
        already established there."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            pressure = self.world.population._housing_pressure(settlement)
            overcrowded = pressure >= MIGRATION_HOUSING_PRESSURE_THRESHOLD
            was_flagged = settlement.id in self._housing_shortage_flagged
            if overcrowded and not was_flagged:
                self._housing_shortage_flagged.add(settlement.id)
                settlement.pattern_signal_counts["housing_shortage"] = (
                    settlement.pattern_signal_counts.get("housing_shortage", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name} is bursting at the seams — too many people, too few homes.",
                    pillars=("village",), magnitude=0.6, settlement=settlement.name,
                    data={"housing_pressure": round(pressure, 3)},
                )
                existing = self.world.village_pillar.find_world_model_entry("housing_shortage")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "housing_shortage",
                    f"{settlement.name} keeps running short on homes for its people.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="housing_shortage",
                    revises_id=existing["id"] if existing else None,
                )
            elif not overcrowded and was_flagged:
                self._housing_shortage_flagged.discard(settlement.id)

    def _detect_food_shortage(self) -> None:
        """Tier 0, new producer (explicit user instruction: "continue
        tier 0"). Village pillar's sixth category-keyed `world_model`
        subject, same shape as `_detect_housing_shortage` — reuses
        `Population._granary_fill_ratio` (population's hunger-driven
        migration pull signal) and `world.reactions.FOOD_SHORTAGE_FILL_
        THRESHOLD` (the exact threshold `_maybe_tick_composite_
        reactions`'s own inline `food_shortage_now` check already uses
        for the "Desperate Times" combination) rather than duplicating
        either. Same edge-triggered discipline: one `bottleneck`
        observation the tick a settlement first crosses into a real
        granary shortfall, silence while it stays there, silent
        recovery once it eases. Riding the same daily-metrics cadence
        as its siblings, no new polling loop.

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine FIFTH option (not just a tiebreak input) —
        `"food_shortage"` can now win the `pattern_key` pick outright
        and produce a real law, same shape `housing_shortage` already
        established there. Also automatically strengthens `_maybe_
        schedule_ontology_proposal`'s pressure-signal scan, which reads
        every `pattern_signal_counts` key, no separate wiring needed."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            fill = self.world.population._granary_fill_ratio(settlement)
            shortage = fill < reactions.FOOD_SHORTAGE_FILL_THRESHOLD
            was_flagged = settlement.id in self._food_shortage_flagged
            if shortage and not was_flagged:
                self._food_shortage_flagged.add(settlement.id)
                settlement.pattern_signal_counts["food_shortage"] = (
                    settlement.pattern_signal_counts.get("food_shortage", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name}'s granaries are running dangerously low.",
                    pillars=("village",), magnitude=0.6, settlement=settlement.name,
                    data={"granary_fill": round(fill, 3)},
                )
                existing = self.world.village_pillar.find_world_model_entry("food_shortage")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "food_shortage",
                    f"{settlement.name} keeps running short on food.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="food_shortage",
                    revises_id=existing["id"] if existing else None,
                )
            elif not shortage and was_flagged:
                self._food_shortage_flagged.discard(settlement.id)

    def _detect_currency_shortage(self) -> None:
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Currency shortage producer"). Village
        pillar's eighth category-keyed `world_model` subject, same
        shape as `_detect_food_shortage`/`_detect_housing_shortage` —
        a settlement's coffers dropping below `buildings.CURRENCY_
        SHORTAGE_THRESHOLD` (half of `INVENTION_CURRENCY_THRESHOLD`,
        the existing "prosperous enough to invent" bar) is a real,
        already-tracked economic fact, not invented state. Same
        edge-triggered discipline: one `bottleneck` observation the
        tick a settlement first crosses into genuine poverty, silence
        while it stays there, silent recovery once it eases. Riding
        the same daily-metrics cadence as its siblings.

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine SEVENTH option — `"currency_shortage"` can now
        win the `pattern_key` pick outright and produce a real
        taxation/currency law, same shape `food_shortage` already
        established. Also automatically strengthens `_maybe_schedule_
        ontology_proposal`'s pressure-signal scan, no separate wiring
        needed."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            shortage = settlement.currency < CURRENCY_SHORTAGE_THRESHOLD
            was_flagged = settlement.id in self._currency_shortage_flagged
            if shortage and not was_flagged:
                self._currency_shortage_flagged.add(settlement.id)
                settlement.pattern_signal_counts["currency_shortage"] = (
                    settlement.pattern_signal_counts.get("currency_shortage", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name}'s coffers are running dangerously bare.",
                    pillars=("village",), magnitude=0.6, settlement=settlement.name,
                    data={"currency": round(settlement.currency, 3)},
                )
                existing = self.world.village_pillar.find_world_model_entry("currency_shortage")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "currency_shortage",
                    f"{settlement.name} keeps running short on currency.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="currency_shortage",
                    revises_id=existing["id"] if existing else None,
                )
            elif not shortage and was_flagged:
                self._currency_shortage_flagged.discard(settlement.id)

    def _detect_prosperity(self) -> None:
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Settlement prosperity/surplus producer").
        Village pillar's ninth category-keyed `world_model` subject —
        deliberately the first POSITIVE one in this cluster; every
        prior producer (`housing_shortage`/`food_shortage`/`currency_
        shortage`/etc.) names a hardship. Requires BOTH `Settlement.
        materials` past `buildings.PROSPERITY_MATERIALS_FRACTION` of
        `MATERIALS_CAPACITY` AND `.currency` past `PROSPERITY_
        CURRENCY_FRACTION` of `CURRENCY_CAPACITY` at once — real
        broad-based prosperity, not one resource's momentary spike.
        Same edge-triggered discipline as every sibling detector: one
        `bottleneck`-category observation (reused as the closest
        existing Emergence API kind — a positive turning point is
        still a turning point) the tick a settlement first crosses
        into genuine comfort, silence while it holds, silent "ease"
        once it recedes.

        Real new consumer: `_maybe_schedule_festival`'s `festival_
        chance` gains `buildings.PROSPERITY_FESTIVAL_BONUS` as a
        multiplicative boost while flagged — the positive counterpart
        to the existing `FAMILY_FEUD_FESTIVAL_PENALTY` dampening a
        few lines below it. Deliberately NOT wired into `_maybe_
        schedule_laws`: that system's own prompt is explicitly framed
        around "a hardship the village has genuinely lived through" —
        folding a positive signal into a hardship-shaped pipeline
        would produce an incoherent prompt, not a real site."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            prosperous = (
                settlement.materials >= PROSPERITY_MATERIALS_FRACTION * MATERIALS_CAPACITY
                and settlement.currency >= PROSPERITY_CURRENCY_FRACTION * CURRENCY_CAPACITY
            )
            was_flagged = settlement.id in self._prosperity_flagged
            if prosperous and not was_flagged:
                self._prosperity_flagged.add(settlement.id)
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name} is thriving — full coffers and well-stocked stores.",
                    pillars=("village",), magnitude=0.5, settlement=settlement.name,
                    data={"materials": round(settlement.materials, 3), "currency": round(settlement.currency, 3)},
                )
                existing = self.world.village_pillar.find_world_model_entry("prosperity")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "prosperity",
                    f"{settlement.name} has known real prosperity.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="prosperity",
                    revises_id=existing["id"] if existing else None,
                )
            elif not prosperous and was_flagged:
                self._prosperity_flagged.discard(settlement.id)

    def _detect_council_gridlock(self) -> None:
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "COUNCIL gridlock producer"). Village
        pillar's eleventh category-keyed `world_model` subject. A
        settlement's COUNCIL genuinely deadlocked — living members
        drawn from more than one real `FACTION`, yet `Population.
        council_faction_majority` still reads `None` (no faction
        commands a strict majority of living seats) — is a distinct
        political fact from an apolitical council (no faction
        membership at all, which reads `None` too but isn't gridlock,
        just no politics yet); the two are told apart here by checking
        real faction presence directly rather than trusting `None`
        alone. Same edge-triggered discipline as every sibling
        detector. Riding the same daily-metrics cadence.

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine TENTH option — a council that keeps failing to
        agree can now produce a real reform/succession-rule law, same
        shape every prior category-keyed producer established."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            council = next(
                (i for i in settlement.institutions if i.kind is InstitutionKind.COUNCIL), None,
            )
            gridlocked = False
            if council is not None:
                living_members = [
                    a for a in self.world.population.agents if a.id in council.member_agent_ids
                ]
                factions_present = any(
                    self.world.population.faction_of(m.id, settlement) is not None
                    for m in living_members
                )
                gridlocked = (
                    bool(living_members) and factions_present
                    and self.world.population.council_faction_majority(settlement) is None
                )
            was_flagged = settlement.id in self._council_gridlock_flagged
            if gridlocked and not was_flagged:
                self._council_gridlock_flagged.add(settlement.id)
                settlement.pattern_signal_counts["council_gridlock"] = (
                    settlement.pattern_signal_counts.get("council_gridlock", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name}'s council is split, unable to agree on anything.",
                    pillars=("village",), magnitude=0.5, settlement=settlement.name,
                )
                existing = self.world.village_pillar.find_world_model_entry("council_gridlock")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "council_gridlock",
                    f"{settlement.name}'s council keeps failing to reach agreement.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="council_gridlock",
                    revises_id=existing["id"] if existing else None,
                )
            elif not gridlocked and was_flagged:
                self._council_gridlock_flagged.discard(settlement.id)

    def _detect_guild_decline(self) -> None:
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "GUILD-level signal"). Village pillar's
        twelfth category-keyed `world_model` subject — a second
        institution-scoped one alongside `_detect_council_gridlock`.
        A GUILD's `Institution.name` IS the skill it formed around
        (`Population._maybe_form_guild`/`_maybe_deliberately_found_
        guild` both name it that way); this fires once NO living
        member still holds `GUILD_SKILL_MASTERY_THRESHOLD` in that
        exact skill — the craft itself has genuinely died out among
        the guild's own membership (whether every member has died, or
        every survivor's skill has simply lapsed below mastery). A
        freshly-founded guild always starts with real living masters
        (guild formation itself requires it), so this can never
        trivially fire the instant a guild forms. Settlement-scoped
        (not per-guild) — same "flagged: set of settlement ids" shape
        as every sibling detector; a settlement with MULTIPLE guilds
        flags if ANY of them has declined. Riding the same
        daily-metrics cadence.

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine ELEVENTH option — a dying craft can now
        produce a real apprenticeship/guild-support law, same shape
        every prior category-keyed producer established.

        C2 "reorganize institution" (Tier 3): once `village_pillar`
        holds strong conviction about a SPECIFIC declining guild's own
        name (`VILLAGE_INSTITUTION_REORGANIZE_CONVICTION_THRESHOLD`),
        that guild is renamed in place to a different skill one of its
        own living members has actually mastered — see
        `_maybe_reorganize_guild`."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            declining = False
            for guild in settlement.institutions:
                if guild.kind is not InstitutionKind.GUILD or not guild.name:
                    continue
                living_members = [
                    a for a in self.world.population.agents if a.id in guild.member_agent_ids
                ]
                has_master = any(
                    a.skills.get(guild.name, 0.0) >= GUILD_SKILL_MASTERY_THRESHOLD for a in living_members
                )
                if not has_master:
                    if self._maybe_reorganize_guild(settlement, guild, living_members):
                        continue  # reorganized in place — no longer declining
                    declining = True
                    break
            was_flagged = settlement.id in self._guild_decline_flagged
            if declining and not was_flagged:
                self._guild_decline_flagged.add(settlement.id)
                settlement.pattern_signal_counts["guild_decline"] = (
                    settlement.pattern_signal_counts.get("guild_decline", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name}'s guild has no living master left to carry the craft on.",
                    pillars=("village",), magnitude=0.5, settlement=settlement.name,
                )
                existing = self.world.village_pillar.find_world_model_entry("guild_decline")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "guild_decline",
                    f"{settlement.name} keeps seeing its guilds lose their masters.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="guild_decline",
                    revises_id=existing["id"] if existing else None,
                )
            elif not declining and was_flagged:
                self._guild_decline_flagged.discard(settlement.id)

    def _maybe_reorganize_guild(self, settlement, guild, living_members: list) -> bool:
        """C2 "Intention channel" (Mind -> Body, Tier 3), "reorganize
        institution" — the sixth C2 slice. Called from `_detect_guild_
        decline`'s own per-guild loop the moment a guild is found to
        have no living master left in its own named skill. Returns
        True if the guild was genuinely renamed in place (and should
        therefore no longer count as declining this tick), False if
        Body doesn't support a reorganization (conviction too low, or
        no real alternate-skill master exists among the guild's own
        living membership).

        `village_pillar`'s conviction is read against the guild's OWN
        name (`subject_confidence(guild.name)`) — this fuzzy-matches
        `_maybe_schedule_guild_founding`'s existing `"the {skill}
        guild"` mirror (the guild's own founding belief), so a guild
        the village has held strong, lasting conviction about since it
        was founded is the one that gets a real second chance rather
        than quietly dissolving. Body stays authoritative throughout:
        conviction alone can never invent a master that doesn't exist,
        and a skill already claimed by another guild in the same
        settlement is never a valid target — this only ever
        redirects an already-real capability the guild's own surviving
        members hold toward a purpose that still has demand for it."""
        conviction = self.world.village_pillar.subject_confidence(guild.name)
        if conviction < VILLAGE_INSTITUTION_REORGANIZE_CONVICTION_THRESHOLD:
            return False
        claimed_skills = {
            inst.name for inst in settlement.institutions
            if inst.kind is InstitutionKind.GUILD and inst.id != guild.id
        }
        candidate_skill = None
        for skill in (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE):
            if skill == guild.name or skill in claimed_skills:
                continue
            if any(a.skills.get(skill, 0.0) >= GUILD_SKILL_MASTERY_THRESHOLD for a in living_members):
                candidate_skill = skill
                break
        if candidate_skill is None:
            return False
        old_name = guild.name
        guild.name = candidate_skill
        self._log(
            "institution_reorganized",
            f"{settlement.name}'s {old_name} guild reorganized around {candidate_skill} — "
            "the craft carried on by new hands, in a new direction.",
        )
        existing = self.world.village_pillar.find_world_model_entry(f"the {old_name} guild")
        if existing is not None:
            self.world.village_pillar.upsert_world_model(
                self.world.clock.tick_count, existing["subject"], existing["belief"], 1.0,
                status="observation", source="institution_reorganize_confirmed",
                revises_id=existing["id"],
            )
        return True

    def _detect_grazer_abundance(self) -> None:
        """C2 "Intention channel" (Mind -> Body, Tier 3), "domesticate"
        — the seventh and final C2 slice, the one genuinely NEW
        mechanism among the eight named intentions: no wild-herd-to-
        tame-stock conversion existed anywhere in this codebase before
        this. Village pillar's sixteenth category-keyed `world_model`
        subject, same edge-triggered settlement-scoped shape as
        `_detect_guild_decline`: a settlement with a standing PASTURE
        that has a real wild GRAZER herd within `WILDLIFE_SEARCH_
        RADIUS` holding at least `DOMESTICATE_MIN_HERD_SIZE` animals is
        genuinely positioned to domesticate it — Body supplies the real
        precondition, this only ever mirrors that a candidate exists.

        Once `village_pillar` holds strong conviction about it
        (`VILLAGE_DOMESTICATE_CONVICTION_THRESHOLD`), `_maybe_
        domesticate_grazers` genuinely INITIATES capturing some of the
        herd into the pasture's own stock. Deliberately decoupled from
        the mirror's own `DOMESTICATE_MIN_HERD_SIZE` gate (which only
        governs whether this settlement's abundance gets MIRRORED/
        reinforced as belief) — once conviction is already strong, the
        action itself runs against any real nearby herd, so a sustained
        conviction keeps producing real domestication events over many
        days as the herd is skimmed down toward `DOMESTICATE_HERD_
        FLOOR` and the pasture's stock is consumed and refilled,
        instead of stalling the moment one capture drops the herd back
        below the higher "genuinely abundant" bar."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            pastures = [
                b for b in settlement.buildings
                if b.kind is BuildingKind.PASTURE and b.stage is BuildingStage.STANDING
            ]
            abundant = any(
                (herd := self.world.wildlife.nearest_grazer_herd(p.x, p.y, WILDLIFE_SEARCH_RADIUS)) is not None
                and herd.count >= DOMESTICATE_MIN_HERD_SIZE
                for p in pastures
            )
            was_flagged = settlement.id in self._grazer_abundance_flagged
            if abundant and not was_flagged:
                self._grazer_abundance_flagged.add(settlement.id)
                existing = self.world.village_pillar.find_world_model_entry("grazer_abundance")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "grazer_abundance",
                    f"{settlement.name} keeps seeing wild grazers thrive near its pasture.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="grazer_abundance",
                    revises_id=existing["id"] if existing else None,
                )
            elif not abundant and was_flagged:
                self._grazer_abundance_flagged.discard(settlement.id)
            for pasture in pastures:
                herd = self.world.wildlife.nearest_grazer_herd(pasture.x, pasture.y, WILDLIFE_SEARCH_RADIUS)
                if herd is not None:
                    self._maybe_domesticate_grazers(settlement, pasture, herd)

    def _maybe_domesticate_grazers(self, settlement, pasture, herd) -> bool:
        """See `_detect_grazer_abundance`. Body stays authoritative:
        the pasture must have real capacity headroom, the herd must
        stay above `DOMESTICATE_HERD_FLOOR` after capture (this skims a
        genuine surplus, never extirpates the wild population), and the
        captured count is taken via `WildlifeGrid.hunt` — the same
        native-index-safe removal primitive a predator kill already
        uses, so this carries zero additional native-parity risk.
        Returns True if a real capture happened."""
        conviction = self.world.village_pillar.subject_confidence("grazer_abundance")
        if conviction < VILLAGE_DOMESTICATE_CONVICTION_THRESHOLD:
            return False
        if pasture.stored_food >= PASTURE_CAPACITY:
            return False
        capture_size = min(DOMESTICATE_CAPTURE_SIZE, herd.count - DOMESTICATE_HERD_FLOOR)
        if capture_size <= 0:
            return False
        captured = self.world.wildlife.hunt(herd.id, capture_size)
        if captured <= 0:
            return False
        pasture.stored_food = min(PASTURE_CAPACITY, pasture.stored_food + captured * DOMESTICATE_FOOD_PER_ANIMAL)
        self._log(
            "grazers_domesticated",
            f"{settlement.name}'s pasture took in {captured} wild grazer"
            f"{'s' if captured != 1 else ''} from a nearby herd.",
        )
        existing = self.world.village_pillar.find_world_model_entry("grazer_abundance")
        if existing is not None:
            self.world.village_pillar.upsert_world_model(
                self.world.clock.tick_count, existing["subject"], existing["belief"], 1.0,
                status="observation", source="domesticate_confirmed",
                revises_id=existing["id"],
            )
        return True

    def _detect_family_extinction(self) -> None:
        """Tier 0, new producer (explicit user decision: "FAMILY-level
        signal"). Village pillar's thirteenth category-keyed `world_
        model` subject, a THIRD institution-scoped one alongside
        `council_gridlock`/`guild_decline`. Unlike those two (level-
        based, can recover), a family line dying out is a genuine
        one-shot event — no living member left in a FAMILY institution
        that once had real membership. `_family_extinction_counted`
        tracks which FAMILY ids have already been counted so the same
        line's death is never double-counted, intersected against
        every currently-present FAMILY id each check so an evicted
        family's id is dropped rather than lingering forever (bounded
        by `INSTITUTION_LIST_MAX_STORED`, same as `Settlement.
        institutions` itself).

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine TWELFTH option — a settlement that keeps
        watching family lines vanish can now produce a real
        inheritance/succession law, same shape every prior category-
        keyed producer established."""
        present_family_ids: set[int] = set()
        for settlement in self.world.settlements:
            for family in settlement.institutions:
                if family.kind is InstitutionKind.FAMILY:
                    present_family_ids.add(family.id)
        self._family_extinction_counted &= present_family_ids
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            for family in settlement.institutions:
                if (
                    family.kind is not InstitutionKind.FAMILY
                    or not family.member_agent_ids
                    or family.id in self._family_extinction_counted
                ):
                    continue
                living_members = [
                    a for a in self.world.population.agents if a.id in family.member_agent_ids
                ]
                if living_members:
                    continue
                self._family_extinction_counted.add(family.id)
                settlement.pattern_signal_counts["family_extinction"] = (
                    settlement.pattern_signal_counts.get("family_extinction", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"A family line in {settlement.name} has died out entirely.",
                    pillars=("village",), magnitude=0.5, settlement=settlement.name,
                )
                existing = self.world.village_pillar.find_world_model_entry("family_extinction")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "family_extinction",
                    f"{settlement.name} has watched family lines vanish before.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="family_extinction",
                    revises_id=existing["id"] if existing else None,
                )

    def _detect_diplomatic_hostility(self) -> None:
        """Tier 0, new producer. Village pillar's fourteenth category-
        keyed `world_model` subject — back to the level-based/
        recoverable shape (`prosperity`/`currency_shortage`), and the
        first to reuse already-real `Settlement.relations` (no new
        tracked data): a settlement's own affinity reading for at
        least one sister settlement has dropped below `buildings.
        DIPLOMATIC_HOSTILITY_THRESHOLD` — deeper than `llm/
        diplomacy.py`'s own "cold" narration tone (-0.3), a genuine
        crisis. Same edge-triggered discipline as every sibling
        detector. Riding the same daily-metrics cadence. Only ever
        fires in a multi-settlement world (a settlement with no
        recorded relations has an empty dict, never crosses the
        threshold).

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine THIRTEENTH option — sustained hostility with a
        neighbor can now produce a real border-defense/militia law."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            hostile = any(v < DIPLOMATIC_HOSTILITY_THRESHOLD for v in settlement.relations.values())
            was_flagged = settlement.id in self._diplomatic_hostility_flagged
            if hostile and not was_flagged:
                self._diplomatic_hostility_flagged.add(settlement.id)
                settlement.pattern_signal_counts["diplomatic_hostility"] = (
                    settlement.pattern_signal_counts.get("diplomatic_hostility", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"{settlement.name}'s standing with a neighbor has turned genuinely hostile.",
                    pillars=("village",), magnitude=0.5, settlement=settlement.name,
                )
                existing = self.world.village_pillar.find_world_model_entry("diplomatic_hostility")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "diplomatic_hostility",
                    f"{settlement.name} keeps falling into hostility with its neighbors.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="diplomatic_hostility",
                    revises_id=existing["id"] if existing else None,
                )
            elif not hostile and was_flagged:
                self._diplomatic_hostility_flagged.discard(settlement.id)

    def _detect_faction_rivalry(self) -> None:
        """Tier 0, new producer (explicit user decision via
        `AskUserQuestion`: "Design a FACTION rivalry signal") — this
        session's first genuinely-new-mechanism producer. Village
        pillar's fifteenth category-keyed `world_model` subject, a
        FOURTH institution-scoped one alongside `council_gridlock`/
        `guild_decline`/`family_extinction`. Two FACTION institutions
        in the same settlement, each with `Population.FACTION_
        RIVALRY_MIN_MEMBERS`+ living members, whose average cross-
        membership relationship (every living member of A's real
        `Agent.relationships` reading toward every living member of B,
        both directions) drops below `Population.FACTION_RIVALRY_
        THRESHOLD` — real sustained hostility between whole factions,
        not a single soured pair (already covered by ordinary dispute
        detection). Same edge-triggered discipline as every sibling
        detector. Riding the same daily-metrics cadence; O(members_a *
        members_b) per pair, cheap since factions stay small by
        construction (`FACTION_MAX_STORED`).

        Real new consumer: `_maybe_schedule_laws`'s `candidates` dict
        gains a genuine FOURTEENTH option — sustained factional strife
        can now produce a real reconciliation/strife-management law."""
        for settlement in self.world.settlements:
            if not settlement.name:
                continue
            factions = [i for i in settlement.institutions if i.kind is InstitutionKind.FACTION]
            rival = False
            for idx, fac_a in enumerate(factions):
                members_a = [
                    a for a in self.world.population.agents if a.id in fac_a.member_agent_ids
                ]
                if len(members_a) < FACTION_RIVALRY_MIN_MEMBERS:
                    continue
                for fac_b in factions[idx + 1:]:
                    members_b = [
                        a for a in self.world.population.agents if a.id in fac_b.member_agent_ids
                    ]
                    if len(members_b) < FACTION_RIVALRY_MIN_MEMBERS:
                        continue
                    readings = [
                        a.relationships.get(b.id, 0.0)
                        for a in members_a for b in members_b
                    ] + [
                        b.relationships.get(a.id, 0.0)
                        for a in members_a for b in members_b
                    ]
                    if readings and (sum(readings) / len(readings)) < FACTION_RIVALRY_THRESHOLD:
                        rival = True
                        break
                if rival:
                    break
            was_flagged = settlement.id in self._faction_rivalry_flagged
            if rival and not was_flagged:
                self._faction_rivalry_flagged.add(settlement.id)
                settlement.pattern_signal_counts["faction_rivalry"] = (
                    settlement.pattern_signal_counts.get("faction_rivalry", 0) + 1
                )
                self._append_emergence(
                    "bottleneck", "settlement",
                    f"Two factions in {settlement.name} have grown genuinely hostile toward each other.",
                    pillars=("village",), magnitude=0.5, settlement=settlement.name,
                )
                existing = self.world.village_pillar.find_world_model_entry("faction_rivalry")
                prior_confidence = existing["confidence"] if existing else 0.3
                self.world.village_pillar.upsert_world_model(
                    self.world.clock.tick_count, "faction_rivalry",
                    f"{settlement.name} keeps seeing its factions turn on each other.",
                    min(1.0, prior_confidence + 0.1), status="observation", source="faction_rivalry",
                    revises_id=existing["id"] if existing else None,
                )
            elif not rival and was_flagged:
                self._faction_rivalry_flagged.discard(settlement.id)

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

    def _detect_social_bridge(self) -> None:
        """Tier 6 L1.2 (docs/ML-ARCHITECTURE-2026-08-01.md): the real
        first gameplay consumer of `hearthmind/ml/social_features.py`'s
        `bridge_score` — same shape as `_detect_social_hub` (season
        cadence, zero LLM cost, a deterministic structural fact never
        an LLM judgment) but for the structural-holes axis instead of
        centrality: the living agent whose own contacts mostly don't
        know each other, i.e. who genuinely bridges otherwise-separate
        parts of this settlement's social graph. Edge-triggered on
        `Settlement.social_bridge_agent_id` actually changing to a new
        agent with a real positive bridge score — a settlement with no
        genuine bridge (fully clustered, or too few relationships to
        measure one) stays silent rather than naming an arbitrary
        agent whose score is exactly 0.0."""
        for settlement in self.world.settlements:
            members = [a for a in self.world.population.agents if a.settlement_id == settlement.id]
            if not members:
                continue
            features = compute_social_features(members)
            if not features:
                continue
            best_id, best = max(features.items(), key=lambda kv: kv[1]["bridge_score"])
            if best["bridge_score"] <= 0.0:
                continue
            if best_id != settlement.social_bridge_agent_id:
                settlement.social_bridge_agent_id = best_id
                bridge_agent = next((a for a in members if a.id == best_id), None)
                if bridge_agent is not None:
                    self._append_emergence(
                        "unexplained_shift", "social_graph",
                        f"{bridge_agent.name} has become the one connecting otherwise-separate "
                        f"parts of {settlement.name or 'the village'}'s social circles.",
                        pillars=("humans", "village"), settlement=settlement.name,
                        data={"agent_id": bridge_agent.id, "bridge_score": round(best["bridge_score"], 3)},
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
                disease_pressure=self.world.fields.ensure_field("disease_pressure"),
                pollution=self.world.fields.ensure_field("pollution"),
                traffic=self.world.fields.ensure_field("traffic"),
                scarcity=self.world.fields.ensure_field("scarcity"),
                ownership=self.world.fields.ensure_field("ownership"),
                noise=self.world.fields.ensure_field("noise"),
                heat=self.world.fields.ensure_field("heat"),
                nutrients=self.world.fields.ensure_field("nutrients"),
                scent=self.world.fields.ensure_field("scent"),
                wildlife=self.world.fields.ensure_field("wildlife"),
                cultural_influence=self.world.fields.ensure_field("cultural_influence"),
                fertility=self.world.fields.ensure_field("fertility"),
                beauty=self.world.fields.ensure_field("beauty"),
                hazard=self.world.fields.ensure_field("hazard"),
                storminess=self.world.fields.ensure_field("storminess"),
                road_scars=self.world.road_scars,
                migration_trails=self.world.migration_trails,
                dry_lakebed_scars=self.world.dry_lakebed_scars,
                carcass_decomposition=self.world.carcass_decomposition,
                battle_scars=self.world.battle_scars,
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
                        b.id, b.kind.value, effective_material_name(b) or "wood",
                        s.effective_layout_style,
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
            # B6 adaptive tuning (v1.34.198): the LIVE value, which can
            # now differ from `config.llm_max_concurrent` (the frozen
            # startup default a fresh process boots from) once `_maybe_
            # tune_llm_concurrency` has made a real adaptive change —
            # see `llm_max_concurrent_static_default` for the original.
            "llm_max_concurrent": self._cognition_runner.max_concurrent,
            "llm_max_concurrent_static_default": self.config.llm_max_concurrent,
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
            # Humans-vs-Village ontology origination split (explicit
            # user delegation, 2026-07-31): same dev-console depth as
            # invented_concepts_by_category above — the live signal
            # that the split is actually distributing attribution
            # across pillars, not silently defaulting everything to
            # village.
            "invented_concepts_by_origin_pillar": {
                pillar: sum(1 for c in self.world.invented_concepts.values() if c.origin_pillar == pillar)
                for pillar in ontology.ONTOLOGY_ORIGIN_PILLARS
                if any(c.origin_pillar == pillar for c in self.world.invented_concepts.values())
            },
            # A19 "battles" axis (world/combat.py): real, cheap, in-
            # memory counters — no disk I/O, safe every tick. A live
            # run showing 0 for a long stretch is expected (the
            # trigger threshold is deliberately severe); a nonzero
            # count with battle_scars_active_sites staying near 0 would
            # point at the scar-decay rate outrunning the battle rate,
            # worth knowing on an overnight soak.
            "battle_deaths_total": self.world.population.deaths_battle,
            "battle_scars_active_sites": len(self.world.battle_scars),
            # A13 "Chemistry / reaction system": how many SMELTER
            # buildings actually stand right now — the live signal that
            # the ore-reachable reactor has real fuel, distinct from
            # `discoverable_reactions` above (which only shows what's
            # currently reachable, not standing-instance counts).
            "smelters_standing": sum(
                1 for stl in self.world.settlements for b in stl.buildings
                if b.kind is BuildingKind.SMELTER and b.stage is BuildingStage.STANDING
            ),
            # Vision doc item 1.2 — same dev-console depth as the
            # ontology fields above.
            "trigger_rules_total": len(self.world.trigger_rules),
            "trigger_rules_by_status": {
                status: sum(1 for r in self.world.trigger_rules.values() if r.status == status)
                for status in ("active", "retired")
                if any(r.status == status for r in self.world.trigger_rules.values())
            },
            # C4 "The acceptance gate as law" (Tier 2 item 16): same
            # dev-console depth as trigger_rules_* above — a `retired`
            # count rising over time is the live signal that `retire_
            # stale_composite_reactions` is actually doing its job.
            "composite_reactions_total": len(self.world.composite_reactions),
            "composite_reactions_by_status": {
                status: sum(1 for r in self.world.composite_reactions.values() if r.status == status)
                for status in ("active", "retired")
                if any(r.status == status for r in self.world.composite_reactions.values())
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
            # Tier 7 HCA Stage A, A2: the real gate above suppresses a
            # candidate whose surprise never clears `EMERGENCE_SURPRISE_
            # THRESHOLD` before it ever reaches `emergence_log` — this
            # is the direct proof the gate is genuinely active, not just
            # present, on a live deployment.
            "emergence_surprise": {
                "attempted_total": self._emergence_surprise_attempted_total,
                "suppressed_total": self._emergence_surprise_suppressed_total,
                "suppressed_fraction": (
                    round(self._emergence_surprise_suppressed_total / self._emergence_surprise_attempted_total, 4)
                    if self._emergence_surprise_attempted_total else 0.0
                ),
            },
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
            # Tier 5 B6 adaptive tuning (distinct from the vision-doc
            # "B6" governor tuning above — this is the Adaptive Runtime
            # spec's item): every real llm_max_concurrent change
            # `_maybe_tune_llm_concurrency` has made, never a no-op.
            "adaptive_tuning_log_recent": list(self._adaptive_tuning_log)[-10:],
            # Tier 7 HCA G2: B8.1/L3.2's WorkloadForecaster's real
            # continual-retrain state — accuracy against the naive
            # "predict the mean" baseline, how many real examples are
            # banked toward the next retrain, and every real learn()
            # attempt's outcome (accepted/rejected, never a no-op).
            "workload_forecaster": {
                "mean_absolute_error": self._workload_accuracy_tracker.mean_absolute_error(),
                "naive_baseline_mae": self._workload_accuracy_tracker.naive_baseline_mae(),
                "reliability_weight": round(self._workload_accuracy_tracker.reliability_weight(), 4),
                "pending_samples": len(self._workload_pending_samples),
                "training_examples_banked": len(self._workload_training_examples),
                "learn_log_recent": list(self._workload_learn_log)[-10:],
            },
            # Tier 5 B2's real control point (see `BROADCAST_SUBSYSTEM_
            # BUDGET_SECONDS`'s docstring): real, never-silently-reset
            # overrun debt for the one job B2 actually schedules today —
            # a growing `debt_seconds` here is a genuine "broadcasts are
            # now costing more than their budget, worth investigating"
            # signal, surfaced rather than only computed internally.
            "broadcast_scheduler": {
                "budget_debt_seconds": round(
                    self._runtime_scheduler_broadcast.budget_for("broadcast").debt_seconds, 6,
                ),
                "metrics": {
                    task_id: {
                        "ticks_observed": m.ticks_observed,
                        "call_count": m.call_count,
                        "error_count": m.error_count,
                        "deferred_count": m.deferred_count,
                        "promoted_count": m.promoted_count,
                    }
                    for task_id, m in self._runtime_scheduler_broadcast.all_metrics().items()
                },
            },
            "llm_stats": self._cognition_runner.stats(),
            "llm_backlog_effective": self._effective_backlog(),
            "llm_backlog_reserved_this_tick": self._reserved_this_tick,
            "llm_backpressure_limit": self._backpressure_limit,
            "llm_backpressure_limit_effective": self._current_backpressure_limit(),
            "llm_backpressure_pressure_band": self._backpressure_pressure_band(),
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
        # Tier 6 L1.2 (docs/ML-ARCHITECTURE-2026-08-01.md): a live,
        # on-demand `compute_social_features()` reading over the
        # current population, reduced to just the two extremes an
        # operator would actually want at a glance rather than a full
        # per-agent dump. `agent_id` in the max-key results is a real
        # int (Agent.id), not a string, despite Settlement.social_hub_
        # agent_id/social_bridge_agent_id's own `str | None` type hint
        # (a pre-existing inaccuracy in that hint, unrelated to this).
        def _social_feature_extreme(features: dict, key: str) -> dict | None:
            if not features:
                return None
            agent_id, values = max(features.items(), key=lambda kv: kv[1][key])
            return {"agent_id": agent_id, **values}

        _social_features_live = compute_social_features(agents)
        _social_features_live_sample = {
            "agents_measured": len(_social_features_live),
            "top_bridge": _social_feature_extreme(_social_features_live, "bridge_score"),
            "top_centrality": _social_feature_extreme(_social_features_live, "weighted_centrality"),
        }
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
            # Tier 5 B5.3's real first wiring: `runtime_diagnostics_
            # report` (built v1.34.183, never given a real HTTP route/
            # dev-console surface since "there's no real engine
            # subsystem running through Scheduler yet to expose" — no
            # longer true after B0.3/B2/B3). Reads ONLY the real
            # institution_dormancy scheduler's already-real B5.1/B2.1/
            # B5.4 state (TaskMetrics/SubsystemBudget/TickTrace) — the
            # first genuinely B3-reactive (ON_EVENT) job, so its
            # `skipped_clean_count` here is a real, live proof this
            # pass's B3 wiring is doing what it claims (skipped_clean
            # on every non-month_end tick, `ran` only on month_end).
            # On-demand only (full_diagnostics, not the per-tick
            # snapshot) — cheap, but no reason to compute it every tick.
            # Tier 5 B5.3 closed this gap, v1.34.214: this used to
            # expose only `institution_dormancy` (the one scheduler
            # that existed when the panel first shipped), with the
            # method's own docstring flagging every other real
            # scheduler as unexposed. `_RUNTIME_SCHEDULED_JOB_
            # SCHEDULERS` already names all of them (one dedicated
            # `Scheduler` per B0.3-migrated job, per that migration's
            # own no-shared-registry design) — this now reports every
            # one, keyed by job method name, each a real, cheap,
            # read-only `runtime_diagnostics_report` call (no new
            # instrumentation, same already-tracked TaskMetrics/
            # SubsystemBudget/TickTrace state every call reads).
            "runtime_diagnostics": {
                job_name: runtime_diagnostics_report(getattr(self, scheduler_attr))
                for job_name, scheduler_attr in sorted(self._RUNTIME_SCHEDULED_JOB_SCHEDULERS.items())
            },
            # Tier 5 B7's real control point, cheap "next tier intel"
            # bonus (same batch): the real `HostProbe` reading
            # `_maybe_tune_llm_concurrency` samples at most once a day,
            # cached rather than re-sampled here (an on-demand full_
            # diagnostics() call is not the place for a fresh syscall
            # burst) — `None` fields are honest ("not yet sampled this
            # process" / genuinely unreadable on this platform), never
            # fabricated.
            "host_probe": (
                {
                    "logical_cores": self._last_host_probe.logical_cores,
                    "usable_cores": self._last_host_probe.usable_cores,
                    "mem_total_mb": self._last_host_probe.mem_total_mb,
                    "mem_available_mb": self._last_host_probe.mem_available_mb,
                    "swap_used_mb": self._last_host_probe.swap_used_mb,
                    "load_avg_1m": self._last_host_probe.load_avg_1m,
                    "thermal_state": self._last_host_probe.thermal_state,
                    "should_back_off": self._last_host_probe_back_off,
                    "sampled_at_tick": self._last_host_probe_tick,
                }
                if self._last_host_probe is not None else None
            ),
            # Tier 5 B7.2/B7.3/B8.4's real control points (explicit
            # user directive: "B8 and MachineProfile persistence and
            # select_strategy's output still have no real call site —
            # flagged for later"): the persisted profile itself, the
            # most recent `select_strategy` verdict it fed into `_maybe_
            # tune_llm_concurrency`'s cap (`None` before the first real
            # call), and whether `is_quiet_window` currently reads the
            # LLM as quiet enough for `_maybe_refresh_machine_profile`'s
            # own storage benchmark to run this month.
            "machine_profile": {
                "host_fingerprint": self._machine_profile.host_fingerprint,
                "sessions_recorded": self._machine_profile.sessions_recorded,
                "measured_llm_throughput_tokens_per_s": self._machine_profile.measured_llm_throughput_tokens_per_s,
                "storage_write_mb_s": self._machine_profile.storage_write_mb_s,
                "storage_read_mb_s": self._machine_profile.storage_read_mb_s,
                "persisted": self._machine_profile_path is not None,
                "last_strategy": (
                    {
                        "llm_max_concurrent_hint": self._last_strategy.llm_max_concurrent_hint,
                        "worker_count_hint": self._last_strategy.worker_count_hint,
                        "cache_size_hint": self._last_strategy.cache_size_hint,
                        "dormancy_aggressiveness": self._last_strategy.dormancy_aggressiveness,
                    }
                    if self._last_strategy is not None else None
                ),
                "recent_llm_backlog_is_quiet_window": is_quiet_window(
                    list(self._recent_llm_backlog_samples), float(self._backpressure_limit),
                ),
            },
            # Tier 5 B15.3/B15.4's real control point: the ladder's real
            # current rung, its own logged transition history (bounded,
            # newest-last), and the cognition budget it's currently
            # producing for `_schedule_due_cognition` — `is_reduced`
            # names the one rung (5) where that budget genuinely differs
            # from the effectively-unbounded normal case.
            "escalation_ladder": {
                "current_rung": self._escalation_ladder.current_rung.name,
                "streak_at_current_rung": self._escalation_ladder.streak_at_current_rung,
                "cognition_budget": self._cognition_budget.count,
                "is_reduced": self._escalation_ladder.current_rung is Rung.REDUCE_COGNITION_BREADTH,
                "history_recent": [
                    {
                        "tick": event.tick,
                        "from_rung": event.from_rung.name,
                        "to_rung": event.to_rung.name,
                        "reason": event.reason,
                    }
                    for event in self._escalation_ladder.history[-10:]
                ],
            },
            # Tier 5 B12's real first consumer — the emergence-log
            # compression ladder's own live state, dev-console/raw-JSON
            # only (same depth as `host_probe`/`adaptive_tuning_log`):
            # how many evicted raw entries are still awaiting their next
            # digest, how many digests have been archived so far, how
            # many raw entries have been condensed in total, and the
            # single newest digest itself (if any) — a real, cheap
            # window into whether compression is actually happening on
            # a live run, not just present in the code.
            "emergence_compression": {
                "raw_pending": self._emergence_compression.stage_size(CompressionStage.RAW),
                "total_archived": self._emergence_compression.total_archived(),
                "total_raw_discarded": self._emergence_compression.total_raw_discarded,
                "newest_digest": (
                    self._emergence_compression.archive_store[
                        max(self._emergence_compression.archive_store, key=lambda k: int(k.split("#")[1]))
                    ]
                    if self._emergence_compression.archive_store else None
                ),
            },
            # Tier 6 L1.2's real first consumer — `_detect_social_hub`/
            # `_detect_social_bridge`'s own persisted per-settlement
            # verdicts (already computed each season, not recomputed
            # here), plus a live, on-demand full `compute_social_
            # features()` reading over the current living population —
            # cheap (a single-pass graph computation, no LLM, no
            # training) and genuinely live: this reflects the real
            # relationship graph AT THE MOMENT `/diagnostics` is
            # polled, not a cached snapshot.
            "social_features": {
                "settlements": [
                    {
                        "name": settlement.name or f"settlement-{settlement.id}",
                        "social_hub_agent_id": settlement.social_hub_agent_id,
                        "social_bridge_agent_id": settlement.social_bridge_agent_id,
                    }
                    for settlement in self.world.settlements
                ],
                "live_sample": _social_features_live_sample,
            },
            # Tier 5 B13's real dev-console/API control point — the
            # most recent manually-requested `HypothesisLoop` attempt
            # over `llm_max_concurrent` (see `_maybe_start_llm_
            # concurrency_hypothesis`/`POST /intervene/llm-concurrency-
            # hypothesis`), `None` until one has ever been requested.
            "llm_concurrency_hypothesis": {
                "running": self._llm_concurrency_hypothesis_running,
                "last_result": self._last_llm_concurrency_hypothesis,
                "history_recent": [
                    {
                        "hypothesis": r.hypothesis, "before_value": r.before_value,
                        "after_value": r.after_value, "decision": r.decision, "reason": r.reason,
                    }
                    for r in self._hypothesis_history.all()[-10:]
                ],
            },
            "peak_memory_rss_mb": peak_rss_mb,
            "system_memory": system_memory_report(),
            "db_size_mb": db_size_mb,
            "uptime_ticks": self.world.clock.tick_count,
            "population_total": pop_total,
            "agents_movement_stuck": agents_movement_stuck,
            "oldest_pending_goal_ticks": oldest_pending_goal_ticks,
            "oldest_pending_dialogue_ticks": oldest_pending_dialogue_ticks,
            "last_llm_calls": self._last_llm_calls,
            "rumor_retellings_recent": list(self._rumor_retellings_recent),
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
