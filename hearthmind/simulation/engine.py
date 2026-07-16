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
    RIVALRY_THRESHOLD,
    SKILL_CONSTRUCTION,
    SKILL_FARMING,
    SKILL_INVENTION_BONUS_WEIGHT,
    SKILL_MEDICINE,
    TRIGGERED_COGNITION_COOLDOWN_TICKS,
    AgentGoal,
    describe_emotion,
    dominant_emotion,
    push_secret,
)
from hearthmind.config import Config
from hearthmind.util import clamp, namespaced_rng, namespaced_roll
from hearthmind.llm import (
    artifacts,
    faction, fission, beliefs, caravan, chronicle, culture, dialogue, dispute, documentary, dream, festival,
    folklore, founding, geography, invention, mind, naming, omens, rumor_interpret, summary, town_brain,
)
from hearthmind.llm.client import build_llm_client
from hearthmind.llm.cognition import SYSTEM_PROMPT, build_prompt, fallback_goal, parse_goal
from hearthmind.llm.jobs import CognitionRunner
from hearthmind.persistence.snapshot import (
    events_by_category, history_events, load_latest_snapshot, log_event, log_metrics,
    recent_events, recent_events_diverse, save_snapshot,
)
from hearthmind.agents.population import (
    DISPUTE_COOLDOWN_TICKS,
    FISSION_MATERIALS_SHARE,
    FISSION_MIN_DISTANCE,
    MAX_SETTLEMENTS,
    Population,
    _bridge_tiles_from_settlements,
    _remember,
    _walkable_tiles,
)
from hearthmind.settlement.buildings import (
    CULTURE_LIST_MAX_STORED,
    CURRENCY_CAPACITY,
    ERA_DESCRIPTIONS,
    FESTIVAL_CHANCE_PER_MONTH,
    FESTIVAL_HUNGER_GATE,
    FOLKLORE_MAX_STORED,
    INVENTION_CHANCE_PER_SEASON,
    INVENTION_CURRENCY_THRESHOLD,
    INVENTION_MATERIALS_FRACTION,
    MARKET_CARAVAN_CHANCE_MULTIPLIER,
    MARKET_CARAVAN_YIELD_MULTIPLIER,
    MATERIALS_CAPACITY,
    CAMP_TOLERANCE,
    HUT_CAPACITY,
    SHRINE_OMEN_CHANCE_MULTIPLIER,
    TEMPERAMENT_INVENTION_INFLUENCE,
    BuildingKind,
    BuildingStage,
    Settlement,
    education_invention_bonus,
    era_for_tech_level,
    RELATION_DIALOGUE_NUDGE_SCALE,
    seed_relation,
    tick_market_prices,
    tick_mood,
    tick_player_standing,
    tick_relation,
    tick_temperament,
)
from hearthmind.settlement.institutions import InstitutionKind
from hearthmind.world.state import TERRAIN_CHANGING_CATEGORIES, World
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

INTERPRET_RUMOR_MAX_PER_DAY = 3
"""Phase K's InterpretRumor() (docs/VISION-2026-07.md, "Knowledge &
Story") fires per listening event, not once a month like every other
settlement job — deliberately small, since this is real *added* call
volume on top of the existing daily budget, not a reuse of an existing
job slot. See `SimulationEngine._interpret_rumor_today` and
`_apply_pending_dialogue_results`."""

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
    "chronicle": 1, "festival": 4, "caravan": 7, "fission": 8, "town_brain": 10,
    "beliefs": 13, "personal_belief": 16, "guild_founding": 19,
    "institution_belief": 22, "geography": 25, "folklore": 20, "dream": 23, "omen": 27, "faction": 26,
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
    "geography",
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

PAUSED_POLL_SECONDS = 0.25
"""How often `run_forever`'s loop wakes up to re-check pause/stop state
while paused, instead of sleeping for a full (possibly very long, at a
low speed multiplier) tick interval — see interface/api.py's
WorldBroadcaster pause/speed fields and `_apply_intervention`'s note on
why pause/speed bypass the usual queued-intervention seam."""

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
        self._monthly_job_scheduled_month: dict[str, int] = {}
        """job name -> absolute month ordinal (year * months_per_year +
        month_index) it last got past its own backpressure check — lets
        `_monthly_gate` retry on the next couple of days if a job's first
        scheduled day was backpressured, instead of silently waiting a
        full month. See MONTHLY_JOB_RETRY_WINDOW_DAYS and `_mark_monthly_
        resolved`."""
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
        self._pending_goal_results: dict[int, tuple[int, dict]] = {}
        """agent_id -> (tick the job was scheduled on, result) — the tick
        lets `_apply_pending_cognition_results` drop results that went
        stale in a saturated queue (STALE_GOAL_RESULT_TICKS)."""
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
            self._broadcaster.set_terrain(world.terrain, world.config.width, world.config.height)
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

    def _schedule_llm_job(self, name: str, prompt: str, system: str, fallback: dict, apply) -> None:
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
        doesn't need."""
        # Daily-ceiling gate (v0.70.0): once the day's Ollama budget is
        # spent, this settlement job resolves via its deterministic
        # fallback inline rather than scheduling a real call. The job's
        # in-fiction effect still happens; only the model authorship is
        # skipped — same degradation as any other fallback.
        if not self._consume_llm_budget():
            try:
                apply(fallback, True)
            except Exception:
                logger.exception("Failed to apply %s fallback job result", name)
            self._record_llm_debug(name, prompt, fallback, True)
            return

        async def _runner() -> None:
            result, used_fallback = await self._cognition_runner.run(
                prompt, system, fallback=lambda: fallback
            )
            try:
                apply(result, used_fallback)
            except Exception:
                logger.exception("Failed to apply %s LLM job result", name)
            self._record_llm_debug(name, prompt, result, used_fallback)
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

            self._schedule_llm_job("naming", prompt, naming.SYSTEM_PROMPT, fallback, apply)

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
                if not paused and not llm_paused:
                    self._tick_once()
                speed = self._broadcaster.get_speed_multiplier() if self._broadcaster is not None else 1.0
                # While paused (user-requested or LLM-pressure-triggered),
                # poll at a short fixed interval rather than the (possibly
                # very long, at a low speed multiplier) tick interval, so a
                # resume/stop request — or backlog draining back down — is
                # picked up promptly.
                if paused or llm_paused:
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
        ("_maybe_schedule_caravan", _JOB_EVENTS),
        ("_maybe_schedule_town_brain", _JOB_EVENTS),
        ("_maybe_schedule_beliefs", _JOB_EVENTS),
        ("_maybe_schedule_personal_belief", _JOB_EVENTS),
        ("_maybe_schedule_dream", _JOB_EVENTS),
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
        if "day_end" in events:
            self._log_daily_metrics()
            self._llm_calls_today = 0  # reset the daily Ollama-call ceiling (v0.70.0)
            self._interpret_rumor_today = 0  # reset InterpretRumor()'s own daily ceiling (Phase K)
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
        for agent_id, (scheduled_tick, result) in self._pending_goal_results.items():
            if now - scheduled_tick > STALE_GOAL_RESULT_TICKS:
                continue  # reasoned from a days-old snapshot — see STALE_GOAL_RESULT_TICKS
            goal, reason = parse_goal(result)
            self.world.population.apply_goal(agent_id, goal, reason)
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
                self._pending_goal_results[agent.id] = (
                    self.world.clock.tick_count,
                    fallback_goal(agent.hunger, agent.energy, agent.id, dict(agent.traits), dict(agent.emotions)),
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
                # (another job spent the last slot): fall back inline.
                self._pending_goal_results[agent.id] = (
                    self.world.clock.tick_count,
                    fallback_goal(agent.hunger, agent.energy, agent.id, dict(agent.traits), dict(agent.emotions)),
                )
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
            prompt = build_prompt(
                agent, self.world.clock.season, self.world.weather.describe(),
                settlement_name=home.name, latest_tradition=latest_tradition,
                colocated_names=colocated_names, nearest_food_steps=food_steps,
                beliefs_about=beliefs_about, own_belief=own_belief,
                semantic_memory=semantic_memory, mind_text=agent.mind,
            )
            hunger_snapshot, energy_snapshot = agent.hunger, agent.energy
            traits_snapshot = dict(agent.traits)
            emotions_snapshot = dict(agent.emotions)
            task = asyncio.create_task(
                self._run_cognition(
                    agent.id, prompt, hunger_snapshot, energy_snapshot, traits_snapshot, emotions_snapshot,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_cognition(
        self, agent_id: int, prompt: str, hunger: float, energy: float, traits: dict, emotions: dict,
    ) -> None:
        scheduled_tick = self.world.clock.tick_count
        try:
            result, used_fallback = await self._cognition_runner.run(
                prompt, SYSTEM_PROMPT,
                fallback=lambda: fallback_goal(hunger, energy, agent_id, traits, emotions),
            )
            self._pending_goal_results[agent_id] = (scheduled_tick, result)
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
            result, used_fallback = await self._cognition_runner.run(
                prompt, rumor_interpret.SYSTEM_PROMPT, fallback=lambda: fallback,
            )
            target = self.world.population.get(listener_id)
            if target is not None:
                retelling = rumor_interpret.parse_interpretation(result, fallback)
                _remember(target, retelling)
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
        elif kind == "settlement_resources":
            settlement = self.world.settlement
            materials_delta = float(item.get("materials", 0.0))
            currency_delta = float(item.get("currency", 0.0))
            settlement.materials = max(0.0, min(MATERIALS_CAPACITY, settlement.materials + materials_delta))
            settlement.currency = max(0.0, min(CURRENCY_CAPACITY, settlement.currency + currency_delta))
            self._log(
                "intervention",
                f"An outside hand adjusted the settlement's stores "
                f"(materials {materials_delta:+.1f}, currency {currency_delta:+.1f}).",
            )
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
        elif kind == "town_influence":
            text = str(item.get("text", "")).strip()[:200]
            if text:
                self.world.settlement.player_influence.append(text)
                self.world.settlement.player_influence = self.world.settlement.player_influence[-3:]
                self._log("intervention", f"A whisper reached the village's ear: \"{text}\"")
        elif kind == "request_summary":
            self._schedule_summary()

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
            prompt = dialogue.build_prompt(
                agent_a, agent_b, affinity, local.name, latest_tradition,
                self.world.clock.season, self.world.weather.describe(), beliefs_about=beliefs_about,
                other_settlement_name=other_settlement_name, cross_settlement_relation=cross_relation,
            )
            fallback = dialogue.fallback_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
            self._reserved_this_tick += 1
            task = asyncio.create_task(self._run_dialogue(agent_a.id, agent_b.id, prompt, fallback))
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

    async def _run_dialogue(self, agent_a_id: int, agent_b_id: int, prompt: str, fallback: dict) -> None:
        scheduled_tick = self.world.clock.tick_count
        result, used_fallback = await self._cognition_runner.run(
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
        self._record_llm_debug("dialogue", prompt, result, used_fallback)
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
            beliefs=list(settlement.beliefs),
            place_names=dict(settlement.place_names),
            folklore=list(settlement.folklore),
        )
        fallback = chronicle.fallback_summary(
            recent, population_summary, previous_season, year,
            seed_hint=self.world.clock.tick_count,
        )

        def apply(result: dict, used_fallback: bool) -> None:
            self._log("chronicle", chronicle.parse_summary(result, fallback))

        self._schedule_llm_job("chronicle", prompt, chronicle.SYSTEM_PROMPT, fallback, apply)

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
        if "year_end" not in events or not self.world.settlement.name:
            return
        if self._settlement_job_backpressured():
            return
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
        )
        fallback = summary.fallback_summary(settlement.name, year, recent, population_summary)
        self.world.sim_summary_pending = True

        def apply(result: dict, used_fallback: bool) -> None:
            self.world.sim_summary_text = summary.parse_summary(result, fallback)
            self.world.sim_summary_tick = self.world.clock.tick_count
            self.world.sim_summary_pending = False
            self._log("sim_summary", self.world.sim_summary_text)

        self._schedule_llm_job("sim_summary", prompt, summary.SYSTEM_PROMPT, fallback, apply)

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
        if "season_end" not in events or not target.name:
            return
        if self._settlement_job_backpressured():
            return
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
        a new legend. See llm/folklore.py."""
        target = self._job_target()
        if not self._monthly_gate(events, "folklore") or not target.name:
            return
        if self._settlement_job_backpressured():
            return
        self._mark_monthly_resolved("folklore")
        rumor_events = events_by_category(self.conn, "rumor", limit=20)
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

        self._schedule_llm_job("folklore", prompt, folklore.SYSTEM_PROMPT, fallback, apply)

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
        if "season_end" not in events or not settlement.name:
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
            beliefs=list(settlement.beliefs),
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
            self._log("invention", f"{settlement.name or 'The village'} invented {entry}")
            self._maybe_advance_era(settlement)

        self._schedule_llm_job("invention", prompt, invention.SYSTEM_PROMPT, fallback, apply)

    def _maybe_advance_era(self, settlement=None) -> None:
        """A settlement starts in the industrial era (see
        `Settlement.era`) and moves forward as inventions accumulate —
        each new era is a mechanically real unlock (see
        `buildings.era_for_tech_level`, the FACTORY building kind), not
        just a label. See docs/DECISIONS.md, real-calendar/genesis-seed
        follow-up."""
        settlement = settlement if settlement is not None else self.world.settlement
        new_era = era_for_tech_level(settlement.tech_level)
        if new_era == settlement.era:
            return
        settlement.era = new_era
        self._log(
            "era_advance",
            f"{settlement.name or 'The village'} has entered the {new_era} era — {ERA_DESCRIPTIONS[new_era]}.",
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
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "festival_roll") >= FESTIVAL_CHANCE_PER_MONTH:
            return
        if self._settlement_job_backpressured():
            return
        recent = recent_events_diverse(self.conn, limit=PROMPT_RECENT_EVENTS)
        festivals = festival_target.festivals
        prompt = festival.build_prompt(
            festival_target.name, recent, self.world.clock.season,
            beliefs=list(festival_target.beliefs),
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
        # — the direct payoff for having built one.
        if settlement.has_market():
            currency_delta *= MARKET_CARAVAN_YIELD_MULTIPLIER
            materials_delta *= MARKET_CARAVAN_YIELD_MULTIPLIER
        settlement.currency = max(0.0, min(CURRENCY_CAPACITY, settlement.currency + currency_delta))
        settlement.materials = max(0.0, min(MATERIALS_CAPACITY, settlement.materials + materials_delta))

        # The trade itself (above) is objective reality and always
        # applies; only the LLM/fallback narration is subject to
        # backpressure — a dropped narration still leaves the currency/
        # materials exchange in effect, just undescribed this month.
        if self._settlement_job_backpressured():
            return
        recent = recent_events_diverse(self.conn, limit=20)
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

        self._schedule_llm_job("caravan", prompt, caravan.SYSTEM_PROMPT, fallback, apply)

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
        prompt = town_brain.build_prompt(
            settlement.name, recent, population_summary, settlement_summary, whispers_sent,
            beliefs=list(settlement.beliefs),
            council_beliefs=list(council.beliefs) if council else None,
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

        self._schedule_llm_job("town_brain", prompt, town_brain.SYSTEM_PROMPT, fallback, apply)

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
        prompt = beliefs.build_prompt(
            settlement.name, recent, list(settlement.beliefs), population_summary, settlement_summary,
        )
        fallback = beliefs.fallback_belief(recent, list(settlement.beliefs), settlement_summary)
        existing_count = len(settlement.beliefs)
        beliefs_target_id = settlement.id

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = beliefs.parse_belief(result, fallback, existing_count)
            settlement = self._settlement_by_id(beliefs_target_id)
            tick = self.world.clock.tick_count
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
                # if the village already holds a theory about this exact
                # subject, treat the answer as a revision of it rather
                # than piling up duplicate theories. See
                # beliefs.find_belief_index_by_subject.
                revises = beliefs.find_belief_index_by_subject(parsed["subject"], settlement.beliefs)
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

        self._schedule_llm_job("beliefs", prompt, beliefs.SYSTEM_PROMPT, fallback, apply)

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
        recent = agent.memories[-3:]
        existing = list(agent.beliefs)
        emotion_text = describe_emotion(agent.emotions)
        semantic = list(agent.semantic_memories)
        prompt = beliefs.build_personal_prompt(agent.name, recent, existing, emotion_text, semantic)
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
                revises = beliefs.find_belief_index_by_subject(parsed["subject"], target.beliefs)
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
            semantic_text = beliefs.parse_semantic_memory(result, fallback)
            beliefs.push_semantic_memory(target, semantic_text)
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

        self._schedule_llm_job("personal_belief", prompt, beliefs.PERSONAL_SYSTEM_PROMPT, fallback, apply)

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
        prompt = dream.build_prompt(agent.name, dict(agent.emotions), agent.goal_reason, latest_folklore)
        fallback = dream.fallback_dream(agent.name, dict(agent.emotions))

        def apply(result: dict, used_fallback: bool) -> None:
            target = self.world.population.get(agent_id)
            if target is None:
                return  # died between scheduling and resolution
            dream_text = dream.parse_dream(result, fallback)
            _remember(target, f"Dreamed: {dream_text}")

        self._schedule_llm_job("dream", prompt, dream.SYSTEM_PROMPT, fallback, apply)

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
            stl.temperament = tick_temperament(
                stl.temperament, recent, rng, intensity=self.world.config.phase_g_intensity,
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
        prompt = omens.build_prompt(
            omen_target.name, temperament, recent, subject_name=subject_name, past_omens=past_omens,
            folklore=list(omen_target.folklore),
        )
        fallback = omens.fallback_omen(temperament, self.world.clock.tick_count, subject_name=subject_name)
        omen_target_id = omen_target.id

        def apply(result: dict, used_fallback: bool) -> None:
            omen = omens.parse_omen(result, fallback)
            self._log("omen", omen)
            self._settlement_by_id(omen_target_id).record_omen(self.world.clock.tick_count, omen, subject_name)

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
            if self._settlement_job_backpressured():
                continue
            agent_id = agent.id
            prompt = mind.build_prompt(agent)

            def apply(result: dict, used_fallback: bool, agent_id=agent_id, fallback=fallback) -> None:
                target = self.world.population.get(agent_id)
                if target is None:
                    return  # died before the answer arrived
                target.mind = mind.parse_mind(result, fallback)

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
        debt_a_owes_b = agent_a.debts.get(agent_b.id, 0.0)
        debt_b_owes_a = agent_b.debts.get(agent_a.id, 0.0)
        prompt = dispute.build_prompt(
            agent_a, agent_b, relationship, dispute_home.name, has_council,
            reputation_a, reputation_b, rival_factions, debt_a_owes_b, debt_b_owes_a,
        )
        fallback = dispute.fallback_dispute(
            agent_a, agent_b, has_council, reputation_a, reputation_b, rival_factions,
            debt_a_owes_b, debt_b_owes_a,
        )
        a_id, b_id = agent_a.id, agent_b.id
        dispute_home_id = dispute_home.id

        def apply(result: dict, used_fallback: bool) -> None:
            outcome, narration = dispute.parse_dispute(
                result, fallback, self._settlement_by_id(dispute_home_id).council() is not None,
            )
            applied = self.world.population.apply_dispute(a_id, b_id, outcome)
            if applied is None:
                return  # one of them died while the decision was in flight
            self._log("dispute", narration)
            # Phase J "Secrets & lies" (v0.78.3): a hardened feud plants
            # a private secret on each core-cast party — deterministic,
            # not a new LLM output field (zero added call volume/schema
            # risk). Non-core agents don't get one: MAX_SECRETS is meant
            # to stay a small, load-bearing set (docs/agents/agent.py).
            if outcome == "feud":
                core = self.world.population.core_agent_ids
                a, b = applied[0], applied[1]
                if a.id in core:
                    push_secret(a, f"I still resent {b.name} for what happened between us.")
                if b.id in core:
                    push_secret(b, f"I still resent {a.name} for what happened between us.")

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
            self._log(
                "institution_belief",
                f"The {label} {'revised its view' if verb == 'revised' else 'came to believe something'}"
                f" of {parsed['subject']}: {parsed['belief']}",
            )

        self._schedule_llm_job("institution_belief", prompt, beliefs.INSTITUTION_SYSTEM_PROMPT, fallback, apply)

    def _choose_fission_site(self, origin: tuple[int, int] | None = None) -> tuple[int, int] | None:
        """The best walkable tile at least FISSION_MIN_DISTANCE from
        every existing settlement's center, scored by nearby wild-food
        supply — the same criterion the original founders' spawn used
        (Population._best_founding_site), because a founding party faces
        the same first problem: eating before infrastructure exists.
        None when the map has no qualifying tile (fission then lapses
        this month)."""
        centers = [c for c in (s.center() for s in self.world.settlements) if c is not None]
        spots = [
            (x, y) for (x, y) in _walkable_tiles(self.world.terrain)
            if all(max(abs(x - cx), abs(y - cy)) >= FISSION_MIN_DISTANCE for cx, cy in centers)
        ]
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
        prompt = fission.build_prompt(leader, home.name, members, housing, self.world.clock.season)
        fallback = fission.fallback_decision(leader)
        leader_id, home_id = leader.id, home.id

        def apply(result: dict, used_fallback: bool) -> None:
            depart, reason = fission.parse_decision(result, fallback)
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
            site = self._choose_fission_site(origin=(leader.x, leader.y))
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

    def _record_llm_call(self, used_fallback: bool) -> None:
        """Cumulative counters persisted on `World`, for diagnosing LLM
        flakiness (timeouts, unreachable server) from a saved snapshot
        alone — see docs/DECISIONS.md, D5."""
        self.world.llm_calls_total += 1
        if used_fallback:
            self.world.llm_fallback_total += 1

    def _record_llm_debug(self, name: str, prompt: str, result: dict, used_fallback: bool) -> None:
        """Records the most recent prompt/result for one named LLM job
        — see `self._last_llm_calls`'s docstring."""
        self._last_llm_calls[name] = {
            "tick": self.world.clock.tick_count, "prompt": prompt,
            "result": result, "used_fallback": used_fallback,
        }

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
            self._broadcaster.set_terrain(self.world.terrain, self.world.config.width, self.world.config.height)
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
                {**a.to_dict(), "is_core": self.world.population.is_core(a.id)}
                for a in self.world.population.agents
            ],
            # Physical layers merge across every settlement — the map
            # shows the world, not one community's slice of it.
            "buildings": [b.to_dict() for s in settlements for b in s.buildings],
            "vehicles": [v.to_dict() for s in settlements for v in s.vehicles],
            "farms": [p.to_dict() for p in self.world.farms.plots.values()],
            "resources": [n.to_dict() for n in self.world.resources.nodes.values()],
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
                    **s.summary(),
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
            (now - t for t, _ in self._pending_goal_results.values()), default=0,
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
            "pending_player_whispers": list(self.world.settlement.player_influence),
            "temperament": round(self.world.settlement.temperament, 3),
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
