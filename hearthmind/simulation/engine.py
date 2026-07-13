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
import logging
import os
import random
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
    SKILL_CONSTRUCTION,
    SKILL_FARMING,
    SKILL_INVENTION_BONUS_WEIGHT,
    TRIGGERED_COGNITION_COOLDOWN_TICKS,
    AgentGoal,
)
from hearthmind.config import Config
from hearthmind.llm import (
    beliefs, caravan, chronicle, culture, dialogue, documentary, festival, invention, naming, omens, town_brain,
)
from hearthmind.llm.client import OllamaClient
from hearthmind.llm.cognition import SYSTEM_PROMPT, build_prompt, fallback_goal, parse_goal
from hearthmind.llm.jobs import CognitionRunner
from hearthmind.persistence.snapshot import (
    history_events, load_latest_snapshot, log_event, log_metrics, recent_events, save_snapshot,
)
from hearthmind.settlement.buildings import (
    CULTURE_LIST_MAX_STORED,
    CURRENCY_CAPACITY,
    ERA_DESCRIPTIONS,
    FESTIVAL_CHANCE_PER_MONTH,
    FESTIVAL_HUNGER_GATE,
    INVENTION_CHANCE_PER_SEASON,
    INVENTION_CURRENCY_THRESHOLD,
    INVENTION_MATERIALS_FRACTION,
    MATERIALS_CAPACITY,
    SHRINE_OMEN_CHANCE_MULTIPLIER,
    TEMPERAMENT_INVENTION_INFLUENCE,
    BuildingKind,
    BuildingStage,
    education_invention_bonus,
    era_for_tech_level,
    tick_player_standing,
    tick_temperament,
)
from hearthmind.world.state import TERRAIN_CHANGING_CATEGORIES, World
from hearthmind.world.terrain import biome_counts


def _namespaced_roll(seed: int, tick: int, namespace: str) -> float:
    """A single deterministic float in [0, 1) from (seed, tick, namespace)
    — the same discipline as Population's namespaced RNG, for the rare
    engine-level rolls (e.g. invention) that don't need a full
    random.Random instance."""
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _namespaced_rng(seed: int, tick: int, namespace: str) -> random.Random:
    """Same discipline as `_namespaced_roll`, for the rare engine-level
    calls (e.g. temperament) that do need a full `random.Random`
    instance rather than a single float."""
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))

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

PAUSED_POLL_SECONDS = 0.25
"""How often `run_forever`'s loop wakes up to re-check pause/stop state
while paused, instead of sleeping for a full (possibly very long, at a
low speed multiplier) tick interval — see interface/api.py's
WorldBroadcaster pause/speed fields and `_apply_intervention`'s note on
why pause/speed bypass the usual queued-intervention seam."""

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
            client = OllamaClient(
                host=config.llm_host, model=config.llm_model, timeout_seconds=config.llm_timeout_seconds,
                num_ctx=config.llm_num_ctx, num_predict=config.llm_num_predict,
                keep_alive=config.llm_keep_alive, use_mmap=config.llm_use_mmap, num_gpu=config.llm_num_gpu,
            )
        self._cognition_runner = CognitionRunner(client=client, max_concurrent=config.llm_max_concurrent)
        self._backpressure_limit = config.llm_max_concurrent * BACKPRESSURE_BACKLOG_PER_SLOT
        self._pending_goal_results: dict[int, tuple[int, dict]] = {}
        """agent_id -> (tick the job was scheduled on, result) — the tick
        lets `_apply_pending_cognition_results` drop results that went
        stale in a saturated queue (STALE_GOAL_RESULT_TICKS)."""
        self._inflight_cognition_agent_ids: set[int] = set()
        self._pending_dialogue_results: list[tuple[int, int, int, dict]] = []
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
        self._naming_scheduled = False
        """Guards `_maybe_schedule_naming` from firing more than once —
        naming is a one-time-per-world event, and the deterministic
        placeholder name (set inside World.tick the instant a building
        first stands) already satisfies every other system's
        `if not settlement.name: return` gate, so there's no retry
        logic here — either the LLM job runs once and (maybe) renames
        the settlement, or it doesn't and the placeholder stands
        forever, same as any other LLM-fallback outcome."""

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
        if self._naming_scheduled:
            return
        if not any(cat == "settlement_named" for cat, _ in self.world.last_life_events):
            return
        self._naming_scheduled = True
        if not self._cognition_runner.enabled:
            # The deterministic placeholder already *is* the fallback
            # outcome here — unlike other jobs, running a second,
            # differently-seeded fallback draw would just rename the
            # settlement to another random name for no reason when
            # there's no real LLM contribution happening.
            return
        settlement = self.world.settlement
        counts = biome_counts(self.world.terrain)
        top_biome = max(counts, key=lambda b: counts[b]).replace("_", " ") if counts else ""
        prompt = naming.build_prompt(settlement.founding_scenario, top_biome, settlement.era)
        fallback = naming.fallback_name(self.world.config.seed)

        def apply(result: dict, used_fallback: bool) -> None:
            new_name = naming.parse_name(result, fallback)
            if new_name and new_name != self.world.settlement.name:
                self.world.settlement.name = new_name
                self._log("settlement_named", f"The village came to be known as {new_name}.")

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
                if not paused:
                    self._tick_once()
                speed = self._broadcaster.get_speed_multiplier() if self._broadcaster is not None else 1.0
                # While paused, poll at a short fixed interval rather than
                # the (possibly very long, at a low speed multiplier) tick
                # interval, so a resume/stop request is picked up promptly.
                interval = PAUSED_POLL_SECONDS if paused else max(0.05, self.config.tick_seconds / speed)
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

    def _tick_once(self) -> None:
        tick_start = time.perf_counter()
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
        if events:
            logger.info(
                "Tick %s: %s | %s | %s",
                self.world.clock.tick_count, self.world.clock.date_string(),
                self.world.clock.clock_string(), self.world.weather.describe(),
            )

        self._maybe_schedule_naming()
        self._maybe_schedule_chronicle(events, previous_season)
        self._maybe_schedule_documentary(events)
        self._maybe_schedule_tradition(events)
        self._maybe_schedule_invention(events)
        self._maybe_schedule_festival(events)
        self._maybe_schedule_caravan(events)
        self._maybe_schedule_town_brain(events)
        self._maybe_schedule_beliefs(events)
        self._maybe_schedule_personal_belief(events)
        self._maybe_tick_temperament(events)
        self._maybe_schedule_omen(events)
        self._schedule_due_cognition()
        self._schedule_due_dialogue()
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
        backlog = self._cognition_runner.backlog
        population = self.world.population
        for agent in due:
            if agent.id in self._inflight_cognition_agent_ids:
                continue
            # Backpressure (see BACKPRESSURE_BACKLOG_PER_SLOT): routine
            # daily reevaluations are skipped while the queue is
            # saturated — the agent keeps its current goal and gets the
            # next staggered slot; triggered emergencies get twice the
            # headroom before they too are rationed.
            limit = self._backpressure_limit * (2 if agent.id in triggered_ids else 1)
            if backlog >= limit:
                self._cognition_runner.calls_dropped_backpressure += 1
                continue
            backlog += 1  # count this tick's own scheduling against the gate
            self._inflight_cognition_agent_ids.add(agent.id)
            latest_tradition = self.world.settlement.traditions[-1] if self.world.settlement.traditions else ""
            colocated_names = [
                other.name for other in population.agents
                if other.id != agent.id and (other.x, other.y) == (agent.x, agent.y)
            ][:4]
            food_steps = population.nearest_food_steps(
                agent, self.world.farms, self.world.settlement, self.world.resources, self.world.wildlife,
            )
            beliefs_about = beliefs.beliefs_about_agent(agent.id, self.world.settlement.beliefs)
            own_belief = max(agent.beliefs, key=lambda b: b["confidence"])["belief"] if agent.beliefs else ""
            prompt = build_prompt(
                agent, self.world.clock.season, self.world.weather.describe(),
                settlement_name=self.world.settlement.name, latest_tradition=latest_tradition,
                colocated_names=colocated_names, nearest_food_steps=food_steps,
                beliefs_about=beliefs_about, own_belief=own_belief,
            )
            hunger_snapshot, energy_snapshot = agent.hunger, agent.energy
            task = asyncio.create_task(self._run_cognition(agent.id, prompt, hunger_snapshot, energy_snapshot))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_cognition(self, agent_id: int, prompt: str, hunger: float, energy: float) -> None:
        scheduled_tick = self.world.clock.tick_count
        try:
            result, used_fallback = await self._cognition_runner.run(
                prompt, SYSTEM_PROMPT, fallback=lambda: fallback_goal(hunger, energy, agent_id),
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
        for scheduled_tick, agent_a_id, agent_b_id, parsed in self._pending_dialogue_results:
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
            # exchange is still logged (so /events and the dev console see
            # the full transcript), but only a `surfaced` one — a rumor,
            # or crossing into a close bond/rivalry — uses the distinct
            # `dialogue_surfaced` category the main UI's event feed keys
            # off of; routine background chatter stays under the quieter
            # `dialogue` category. See docs/DECISIONS.md.
            category = "dialogue_surfaced" if surfaced else "dialogue"
            self._log(
                category, f'{agent_a.name}: "{parsed["line_a"]}" — {agent_b.name}: "{parsed["line_b"]}"',
            )
            self.world.dialogue_total += 1
            if parsed["rumor"]:
                self._log("rumor", f"{agent_a.name} and {agent_b.name}: {parsed['rumor']}")
                self.world.rumor_total += 1
        self._pending_dialogue_results.clear()

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
                weather.precipitation = max(0.0, min(1.0, float(item["precipitation"])))
            if "wind" in item:
                weather.wind = max(0.0, min(1.0, float(item["wind"])))
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

    def _schedule_due_dialogue(self) -> None:
        """Fire-and-forget an LLM-authored dialogue job for each colocated
        pair due this tick (see Population.due_for_dialogue for selection
        and cooldown rules). Scheduled unconditionally, same as cognition
        — CognitionRunner resolves to the deterministic fallback when the
        LLM is disabled/unreachable. See docs/DECISIONS.md, E2."""
        # Dialogue is the most expendable LLM job — under backpressure it
        # is skipped before anything else (the pair simply stays eligible
        # for a later tick once its cooldown allows).
        if self._cognition_runner.backlog >= self._backpressure_limit:
            self._cognition_runner.calls_dropped_backpressure += 1
            return
        pairs = self.world.population.due_for_dialogue(
            self.world.config.seed, self.world.clock.tick_count, DIALOGUE_COOLDOWN_TICKS,
        )
        if not pairs:
            return
        latest_tradition = self.world.settlement.traditions[-1] if self.world.settlement.traditions else ""
        for agent_a, agent_b in pairs:
            affinity = agent_a.relationships.get(agent_b.id, 0.0)
            beliefs_about = beliefs.beliefs_about_agent(
                agent_a.id, self.world.settlement.beliefs
            ) + beliefs.beliefs_about_agent(agent_b.id, self.world.settlement.beliefs)
            prompt = dialogue.build_prompt(
                agent_a, agent_b, affinity, self.world.settlement.name, latest_tradition,
                self.world.clock.season, self.world.weather.describe(), beliefs_about=beliefs_about,
            )
            fallback = dialogue.fallback_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
            task = asyncio.create_task(self._run_dialogue(agent_a.id, agent_b.id, prompt, fallback))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_dialogue(self, agent_a_id: int, agent_b_id: int, prompt: str, fallback: dict) -> None:
        scheduled_tick = self.world.clock.tick_count
        result, used_fallback = await self._cognition_runner.run(
            prompt, dialogue.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        parsed = dialogue.parse_dialogue(result, fallback)
        self._pending_dialogue_results.append((scheduled_tick, agent_a_id, agent_b_id, parsed))
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
        if "month_end" not in events:
            return
        recent = recent_events(self.conn, limit=50)
        population_summary = self.world.population.summary()
        year = self.world.clock.year
        prompt = chronicle.build_prompt(
            recent, population_summary, previous_season, year,
            settlement_name=self.world.settlement.name,
            # Only the newest few traditions reach the prompt — the full
            # list grows unbounded over a multi-year world, and feeding
            # it whole would swell every monthly call's tokens forever
            # (July 2026 review, §3.7). The list itself still persists.
            traditions=self.world.settlement.traditions[-PROMPT_CULTURE_LIST_MAX:],
            beliefs=list(self.world.settlement.beliefs),
        )
        fallback = chronicle.fallback_summary(recent, population_summary, previous_season, year)

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
        milestones = history_events(self.conn, limit=40)
        population_summary = self.world.population.summary()
        prompt = documentary.build_prompt(
            self.world.settlement.name, self.world.settlement.era, self.world.clock.year,
            milestones, population_summary, self.world.settlement.temperament,
        )
        fallback = documentary.fallback_narration(
            self.world.settlement.name, self.world.clock.year, milestones, population_summary,
        )

        def apply(result: dict, used_fallback: bool) -> None:
            self._log("documentary", documentary.parse_narration(result, fallback))

        self._schedule_llm_job("documentary", prompt, documentary.SYSTEM_PROMPT, fallback, apply)

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
        if "season_end" not in events or not self.world.settlement.name:
            return
        recent = recent_events(self.conn, limit=50)
        traditions = self.world.settlement.traditions
        prompt = culture.build_prompt(
            self.world.settlement.name, recent, traditions[-PROMPT_CULTURE_LIST_MAX:], self.world.clock.year,
        )
        # `traditions_established` (a persistent, never-decremented
        # counter) rather than len(traditions) — the stored list is
        # capped at CULTURE_LIST_MAX_STORED, so list length alone would
        # eventually corrupt "Tradition the Nth"-style fallback naming.
        fallback = culture.fallback_tradition(
            self.world.settlement.name, self.world.clock.year, self.world.settlement.traditions_established,
        )

        def apply(result: dict, used_fallback: bool) -> None:
            name, description, influence = culture.parse_tradition(result, fallback)
            entry = f"{name}: {description}"
            settlement = self.world.settlement
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
            self._log("tradition", f"The village established a new tradition — {entry}")

        self._schedule_llm_job("tradition", prompt, culture.SYSTEM_PROMPT, fallback, apply)

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
        if "season_end" not in events or not self.world.settlement.name:
            return
        settlement = self.world.settlement
        prosperous = (
            settlement.currency >= INVENTION_CURRENCY_THRESHOLD
            or settlement.materials >= MATERIALS_CAPACITY * INVENTION_MATERIALS_FRACTION
        )
        if not prosperous:
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
                a.skills.get(SKILL_FARMING, 0.0) + a.skills.get(SKILL_CONSTRUCTION, 0.0) for a in agents
            ) / (2 * len(agents))
            chance = min(1.0, chance * (1.0 + avg_skill * SKILL_INVENTION_BONUS_WEIGHT))
        chance = max(0.0, chance * (1.0 + settlement.temperament * TEMPERAMENT_INVENTION_INFLUENCE))
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "invention_roll") >= chance:
            return
        recent = recent_events(self.conn, limit=50)
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

        def apply(result: dict, used_fallback: bool) -> None:
            name, description = invention.parse_invention(result, fallback)
            entry = f"{name}: {description}"
            settlement = self.world.settlement
            settlement.inventions.append(entry)
            if len(settlement.inventions) > CULTURE_LIST_MAX_STORED:
                settlement.inventions = settlement.inventions[-CULTURE_LIST_MAX_STORED:]
            settlement.tech_level += 1
            self._log("invention", f"The village invented {entry}")
            self._maybe_advance_era()

        self._schedule_llm_job("invention", prompt, invention.SYSTEM_PROMPT, fallback, apply)

    def _maybe_advance_era(self) -> None:
        """A settlement starts in the industrial era (see
        `Settlement.era`) and moves forward as inventions accumulate —
        each new era is a mechanically real unlock (see
        `buildings.era_for_tech_level`, the FACTORY building kind), not
        just a label. See docs/DECISIONS.md, real-calendar/genesis-seed
        follow-up."""
        settlement = self.world.settlement
        new_era = era_for_tech_level(settlement.tech_level)
        if new_era == settlement.era:
            return
        settlement.era = new_era
        self._log(
            "era_advance",
            f"The village has entered the {new_era} era — {ERA_DESCRIPTIONS[new_era]}.",
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
        if "month_end" not in events or not self.world.settlement.name:
            return
        if self.world.population.avg_hunger() > FESTIVAL_HUNGER_GATE:
            return
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "festival_roll") >= FESTIVAL_CHANCE_PER_MONTH:
            return
        recent = recent_events(self.conn, limit=50)
        festivals = self.world.settlement.festivals
        prompt = festival.build_prompt(
            self.world.settlement.name, recent, self.world.clock.season,
            beliefs=list(self.world.settlement.beliefs),
        )
        # festivals_held (persistent, never-decremented) rather than
        # len(festivals) — same CULTURE_LIST_MAX_STORED-cap rationale as
        # tradition/invention naming above.
        fallback = festival.fallback_festival(self.world.settlement.name, self.world.settlement.festivals_held)

        def apply(result: dict, used_fallback: bool) -> None:
            name, description = festival.parse_festival(result, fallback)
            entry = f"{name}: {description}"
            settlement = self.world.settlement
            settlement.festivals.append(entry)
            settlement.festivals_held += 1
            if len(settlement.festivals) > CULTURE_LIST_MAX_STORED:
                settlement.festivals = settlement.festivals[-CULTURE_LIST_MAX_STORED:]
            affected = self.world.population.hold_festival(settlement)
            self._log("festival", f"The village held {entry} ({affected} bonds strengthened)")

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
        if "month_end" not in events or not self.world.settlement.name:
            return
        if _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "caravan_roll",
        ) >= caravan.CARAVAN_CHANCE_PER_MONTH:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "caravan")
        settlement = self.world.settlement
        currency_delta = rng.uniform(*caravan.CARAVAN_CURRENCY_DELTA_RANGE)
        # Correlated, not independent: a caravan that pays the village in
        # currency takes materials in return, and vice versa — a real
        # barter rather than two unrelated windfalls. See
        # CARAVAN_MATERIALS_DELTA_RANGE's docstring.
        lo, hi = caravan.CARAVAN_MATERIALS_DELTA_RANGE
        currency_lo, currency_hi = caravan.CARAVAN_CURRENCY_DELTA_RANGE
        currency_fraction = (currency_delta - currency_lo) / (currency_hi - currency_lo)
        materials_delta = hi - currency_fraction * (hi - lo)
        settlement.currency = max(0.0, min(CURRENCY_CAPACITY, settlement.currency + currency_delta))
        settlement.materials = max(0.0, min(MATERIALS_CAPACITY, settlement.materials + materials_delta))

        recent = recent_events(self.conn, limit=20)
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
        if "month_end" not in events or not self.world.settlement.name:
            return
        settlement = self.world.settlement
        recent = recent_events(self.conn, limit=50)
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

        def apply(result: dict, used_fallback: bool) -> None:
            if whispers_sent and not used_fallback:
                # A whisper only counts as heard when the LLM actually
                # read the prompt containing it. On timeout/fallback it
                # stays queued for next month's decision instead of
                # vanishing silently — previously the queue was cleared
                # at schedule time, so a whisper submitted during a
                # flaky LLM stretch was consumed by nobody (July 2026
                # architecture review, §0.2).
                remaining = [w for w in self.world.settlement.player_influence if w not in whispers_sent]
                self.world.settlement.player_influence = remaining[-3:]
            priority, rationale = town_brain.parse_priority(result, fallback)
            self.world.settlement.current_priority = priority
            self.world.settlement.priority_rationale = rationale
            self.world.settlement.record_priority(self.world.clock.tick_count, priority, rationale)
            self._log("town_brain", f"The village's priority is now {priority} — {rationale}")

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
        if "month_end" not in events or not self.world.settlement.name:
            return
        settlement = self.world.settlement
        recent = recent_events(self.conn, limit=30)
        population_summary = self.world.population.summary()
        settlement_summary = settlement.summary()
        prompt = beliefs.build_prompt(
            settlement.name, recent, list(settlement.beliefs), population_summary, settlement_summary,
        )
        fallback = beliefs.fallback_belief(recent, list(settlement.beliefs), settlement_summary)
        existing_count = len(settlement.beliefs)

        def apply(result: dict, used_fallback: bool) -> None:
            parsed = beliefs.parse_belief(result, fallback, existing_count)
            settlement = self.world.settlement
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

        self._schedule_llm_job("beliefs", prompt, beliefs.SYSTEM_PROMPT, fallback, apply)

    def _maybe_schedule_personal_belief(self, events: list[str]) -> None:
        """H2 extension (docs/ROADMAP.md "Phase H" stage 2): once a
        month, one living agent (chosen deterministically by the
        namespaced-RNG pattern, weighted toward whoever has the most
        recent memories to reflect on) forms or revises a private
        belief about their own life, mirroring `_maybe_schedule_
        beliefs` at agent scale rather than settlement scale. Same
        monthly cadence as the settlement's own beliefs job; only one
        agent per month (not all of them) — this is real interpretive
        content, not a routine per-agent stat, and 400 agents each
        getting an LLM call every month would be a genuinely large
        scheduling load for a reflective mechanic that's meant to
        surface occasional, notable personal theories, not a monthly
        diary entry for everyone."""
        if "month_end" not in events:
            return
        candidates = [a for a in self.world.population.agents if a.memories]
        if not candidates:
            return
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "personal_belief")
        agent = rng.choice(candidates)
        agent_id = agent.id
        recent = agent.memories[-3:]
        existing = list(agent.beliefs)
        prompt = beliefs.build_personal_prompt(agent.name, recent, existing)
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

        self._schedule_llm_job("personal_belief", prompt, beliefs.PERSONAL_SYSTEM_PROMPT, fallback, apply)

    # --- Phase G v1: temperament and omens (deliberately subtle) ---------------

    def _maybe_tick_temperament(self, events: list[str]) -> None:
        """Once a month, nudge `Settlement.temperament` and `Settlement.
        player_standing` — both real, deterministic values (see
        `tick_temperament`/`tick_player_standing`), not an LLM decision.
        The LLM's only role in this system is narrating ambiguous omens
        on top of temperament (`_maybe_schedule_omen`) and folding
        player_standing into the town-brain prompt as one more subtle
        input, never computing either value itself. See
        docs/DECISIONS.md, "World-G follow-up" and "town's opinion of
        the player" pass."""
        if "month_end" not in events:
            return
        recent = recent_events(self.conn, limit=50)
        rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "temperament")
        self.world.settlement.temperament = tick_temperament(
            self.world.settlement.temperament, recent, rng, intensity=self.world.config.phase_g_intensity,
        )
        standing_rng = _namespaced_rng(self.world.config.seed, self.world.clock.tick_count, "player_standing")
        self.world.settlement.player_standing = tick_player_standing(
            self.world.settlement.player_standing, recent, standing_rng,
        )

    def _maybe_schedule_omen(self, events: list[str]) -> None:
        """Rare, ambiguous flavor event — see llm/omens.py's module
        docstring for why this deliberately never confirms anything
        supernatural. Chance scales with |temperament|'s magnitude, so
        a run of strongly good or ill fortune is somewhat more likely
        to produce one, without it ever becoming frequent. Also scales
        with Config.phase_g_intensity (0.0 disables omens outright,
        matching tick_temperament's own intensity=0.0 behavior)."""
        if "month_end" not in events or not self.world.settlement.name:
            return
        intensity = self.world.config.phase_g_intensity
        if intensity <= 0.0:
            return
        temperament = self.world.settlement.temperament
        chance = (omens.OMEN_CHANCE_BASE + abs(temperament) * omens.OMEN_CHANCE_TEMPERAMENT_SCALE) * intensity
        has_shrine = any(
            b.kind is BuildingKind.SHRINE and b.stage is BuildingStage.STANDING
            for b in self.world.settlement.buildings
        )
        if has_shrine:
            chance *= SHRINE_OMEN_CHANCE_MULTIPLIER
        chance = min(1.0, chance)
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "omen_roll") >= chance:
            return
        recent = recent_events(self.conn, limit=10)
        # Deepened narrative payoff (roadmap follow-up): about half the
        # time, if a belief already resolves to a still-living agent,
        # the omen centers on them instead of the settlement in the
        # abstract — noticing something *about a specific person*, still
        # never confirming anything, just less anonymous. See
        # docs/DECISIONS.md, "Phase G intensity + omen subjects" pass.
        subject_name = ""
        subject_candidates: list[str] = [
            self.world.population.get(b["subject_agent_id"]).name
            for b in self.world.settlement.beliefs
            if b.get("subject_agent_id") is not None
            and self.world.population.get(b["subject_agent_id"]) is not None
        ]
        # Integration milestone: a council with its own accumulated
        # civic beliefs (see llm/beliefs.sync_council_beliefs) is one
        # more candidate subject alongside individual agents — an omen
        # noticed about "the council of elders" rather than a settlement
        # in the abstract, same permanent ambiguity rule, just extended
        # from person-depth to institution-depth.
        council = self.world.settlement.council()
        if council is not None and council.beliefs:
            subject_candidates.append("the council of elders")
        if subject_candidates and _namespaced_roll(
            self.world.config.seed, self.world.clock.tick_count, "omen_subject_roll",
        ) < 0.5:
            pick_roll = _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "omen_subject_pick")
            subject_name = subject_candidates[min(len(subject_candidates) - 1, int(pick_roll * len(subject_candidates)))]
        past_omens = [entry["omen"] for entry in self.world.settlement.omen_history]
        prompt = omens.build_prompt(
            self.world.settlement.name, temperament, recent, subject_name=subject_name, past_omens=past_omens,
        )
        fallback = omens.fallback_omen(temperament, self.world.clock.tick_count, subject_name=subject_name)

        def apply(result: dict, used_fallback: bool) -> None:
            omen = omens.parse_omen(result, fallback)
            self._log("omen", omen)
            self.world.settlement.record_omen(self.world.clock.tick_count, omen, subject_name)

        self._schedule_llm_job("omen", prompt, omens.SYSTEM_PROMPT, fallback, apply)

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
                b.stored_food for b in settlement.buildings
                if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
            ), 3),
            "materials": round(settlement.materials, 3),
            "currency": round(settlement.currency, 3),
            "buildings_standing": sum(1 for b in settlement.buildings if b.stage is BuildingStage.STANDING),
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
        life_events = [
            {"category": category, "description": description}
            for category, description in self.world.last_life_events
        ]
        life_events.extend(self._pending_broadcast_events)
        self._pending_broadcast_events = []
        payload = {
            "summary": self.world.summary(),
            "life_events": life_events,
            "agents": [a.to_dict() for a in self.world.population.agents],
            "buildings": [b.to_dict() for b in self.world.settlement.buildings],
            "vehicles": [v.to_dict() for v in self.world.settlement.vehicles],
            "farms": [p.to_dict() for p in self.world.farms.plots.values()],
            "resources": [n.to_dict() for n in self.world.resources.nodes.values()],
            "wildlife": [h.to_dict() for h in self.world.wildlife.herds.values()],
            "roads": self.world.roads.to_dict()["wear"],
            "diagnostics": self._diagnostics_snapshot(),
            "infrastructure": self.world.settlement.infrastructure_report(),
        }
        task = asyncio.create_task(self._broadcaster.broadcast(payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _diagnostics_snapshot(self) -> dict:
        """Cheap, per-tick diagnostics — safe to compute every tick (no
        disk I/O, no DB queries). See `full_diagnostics` for the heavier,
        on-demand report behind `GET /diagnostics`."""
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
        return {
            **self._diagnostics_snapshot(),
            "peak_memory_rss_mb": peak_rss_mb,
            "db_size_mb": db_size_mb,
            "uptime_ticks": self.world.clock.tick_count,
            "population_total": pop_total,
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
