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
import sqlite3
from typing import TYPE_CHECKING

from hearthmind.config import Config
from hearthmind.llm import chronicle, culture
from hearthmind.llm.client import OllamaClient
from hearthmind.llm.cognition import SYSTEM_PROMPT, build_prompt, fallback_goal, parse_goal
from hearthmind.llm.jobs import CognitionRunner
from hearthmind.persistence.snapshot import load_latest_snapshot, log_event, recent_events, save_snapshot
from hearthmind.world.state import World

if TYPE_CHECKING:
    # Only imported for type hints — importing hearthmind.simulation.engine
    # must not require the `websockets` package unless the API is actually
    # enabled (see interface/api.py, server.py). See docs/DECISIONS.md, F1.
    from hearthmind.interface.api import WorldBroadcaster

logger = logging.getLogger("hearthmind.engine")

_CALENDAR_EVENT_DESCRIPTIONS = {
    "day_end": "A new day begins.",
    "season_end": "The season turns.",
    "year_end": "A new year begins.",
}

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

        client = None
        if config.llm_enabled:
            client = OllamaClient(
                host=config.llm_host, model=config.llm_model, timeout_seconds=config.llm_timeout_seconds,
            )
        self._cognition_runner = CognitionRunner(client=client, max_concurrent=config.llm_max_concurrent)
        self._pending_goal_results: dict[int, dict] = {}
        self._inflight_cognition_agent_ids: set[int] = set()
        self._background_tasks: set[asyncio.Task] = set()

    @property
    def stop_event(self) -> asyncio.Event:
        """Exposed so a co-running loop (e.g. the WebSocket API server,
        see interface/api.py) can shut down in lockstep on Ctrl+C/SIGTERM
        rather than each needing its own signal wiring."""
        return self._stop_event

    @classmethod
    def load_or_create(
        cls, conn: sqlite3.Connection, config: Config, broadcaster: "WorldBroadcaster | None" = None,
    ) -> "SimulationEngine":
        world = load_latest_snapshot(conn, runtime_config=config)
        if world is None:
            logger.info("No existing snapshot found — creating a new world (seed=%s).", config.seed)
            world = World.create_new(config)
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

    async def run_forever(self) -> None:
        logger.info(
            "Engine starting: %.2fs/tick, %s sim-minutes/tick, snapshot every %s ticks, LLM %s.",
            self.config.tick_seconds, self.world.config.sim_minutes_per_tick, self.config.snapshot_every_ticks,
            "enabled" if self._cognition_runner.enabled else "disabled (deterministic fallback only)",
        )
        try:
            while not self._stop_event.is_set():
                self._tick_once()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.tick_seconds)
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

    def _tick_once(self) -> None:
        self._apply_pending_cognition_results()

        previous_season = self.world.clock.season
        events = self.world.tick()
        for event in events:
            log_event(
                self.conn,
                tick=self.world.clock.tick_count,
                category=event,
                description=_CALENDAR_EVENT_DESCRIPTIONS.get(event, event),
            )
        for category, description in self.world.last_life_events:
            log_event(
                self.conn, tick=self.world.clock.tick_count,
                category=category, description=description,
            )
        if events:
            logger.info(
                "Tick %s: %s | %s | %s",
                self.world.clock.tick_count, self.world.clock.date_string(),
                self.world.clock.clock_string(), self.world.weather.describe(),
            )

        self._maybe_schedule_chronicle(events, previous_season)
        self._maybe_schedule_tradition(events)
        self._schedule_due_cognition()
        self._maybe_broadcast()

        self._ticks_since_snapshot += 1
        if self._ticks_since_snapshot >= self.config.snapshot_every_ticks:
            save_snapshot(self.conn, self.world)
            self._ticks_since_snapshot = 0
            logger.debug("Snapshot saved at tick %s.", self.world.clock.tick_count)

    # --- Phase B: per-agent cognition (goals) -------------------------------

    def _apply_pending_cognition_results(self) -> None:
        """Apply goal decisions completed by background tasks since the
        last tick. Runs synchronously at the top of _tick_once, never
        inline with the LLM call itself."""
        if not self._pending_goal_results:
            return
        for agent_id, result in self._pending_goal_results.items():
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
        for agent in due:
            if agent.id in self._inflight_cognition_agent_ids:
                continue
            self._inflight_cognition_agent_ids.add(agent.id)
            latest_tradition = self.world.settlement.traditions[-1] if self.world.settlement.traditions else ""
            prompt = build_prompt(
                agent, self.world.clock.season, self.world.weather.describe(),
                settlement_name=self.world.settlement.name, latest_tradition=latest_tradition,
            )
            hunger_snapshot, energy_snapshot = agent.hunger, agent.energy
            task = asyncio.create_task(self._run_cognition(agent.id, prompt, hunger_snapshot, energy_snapshot))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_cognition(self, agent_id: int, prompt: str, hunger: float, energy: float) -> None:
        try:
            result, used_fallback = await self._cognition_runner.run(
                prompt, SYSTEM_PROMPT, fallback=lambda: fallback_goal(hunger, energy, agent_id),
            )
            self._pending_goal_results[agent_id] = result
            self._record_llm_call(used_fallback)
        finally:
            self._inflight_cognition_agent_ids.discard(agent_id)

    # --- Phase B: world chronicle --------------------------------------------

    def _maybe_schedule_chronicle(self, events: list[str], previous_season: str) -> None:
        if "season_end" not in events:
            return
        recent = recent_events(self.conn, limit=50)
        population_summary = self.world.population.summary()
        year = self.world.clock.year
        prompt = chronicle.build_prompt(
            recent, population_summary, previous_season, year,
            settlement_name=self.world.settlement.name, traditions=self.world.settlement.traditions,
        )
        fallback = chronicle.fallback_summary(recent, population_summary, previous_season, year)
        task = asyncio.create_task(self._run_chronicle(prompt, fallback))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_chronicle(self, prompt: str, fallback: dict) -> None:
        result, used_fallback = await self._cognition_runner.run(
            prompt, chronicle.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        summary = chronicle.parse_summary(result, fallback)
        log_event(self.conn, tick=self.world.clock.tick_count, category="chronicle", description=summary)
        self._record_llm_call(used_fallback)

    # --- Phase E: village culture (traditions) --------------------------------

    def _maybe_schedule_tradition(self, events: list[str]) -> None:
        """A named settlement invents a new tradition once per year — a
        slower, generational cadence than the chronicle's seasonal one.
        Unnamed settlements (no standing building yet) have no culture to
        speak of, so nothing is scheduled. See docs/DECISIONS.md, E1."""
        if "year_end" not in events or not self.world.settlement.name:
            return
        recent = recent_events(self.conn, limit=50)
        traditions = self.world.settlement.traditions
        prompt = culture.build_prompt(self.world.settlement.name, recent, traditions, self.world.clock.year)
        fallback = culture.fallback_tradition(self.world.settlement.name, self.world.clock.year, len(traditions))
        task = asyncio.create_task(self._run_tradition(prompt, fallback))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_tradition(self, prompt: str, fallback: dict) -> None:
        result, used_fallback = await self._cognition_runner.run(
            prompt, culture.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        name, description = culture.parse_tradition(result, fallback)
        entry = f"{name}: {description}"
        self.world.settlement.traditions.append(entry)
        log_event(
            self.conn, tick=self.world.clock.tick_count, category="tradition",
            description=f"The village established a new tradition — {entry}",
        )
        self._record_llm_call(used_fallback)

    def _record_llm_call(self, used_fallback: bool) -> None:
        """Cumulative counters persisted on `World`, for diagnosing LLM
        flakiness (timeouts, unreachable server) from a saved snapshot
        alone — see docs/DECISIONS.md, D5."""
        self.world.llm_calls_total += 1
        if used_fallback:
            self.world.llm_fallback_total += 1

    # --- Phase F: read-only WebSocket broadcast --------------------------------

    def _maybe_broadcast(self) -> None:
        """Fire-and-forget, same pattern as LLM background jobs — a slow
        or absent client must never be able to delay a tick. No-op when
        the API isn't enabled (`self._broadcaster is None`). See
        docs/DECISIONS.md, F1."""
        if self._broadcaster is None:
            return
        payload = {
            "summary": self.world.summary(),
            "life_events": [
                {"category": category, "description": description}
                for category, description in self.world.last_life_events
            ],
        }
        task = asyncio.create_task(self._broadcaster.broadcast(payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
