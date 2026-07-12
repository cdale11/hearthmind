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
import sqlite3
import time
from collections import deque
from typing import TYPE_CHECKING

try:
    import resource  # Unix-only; used for peak-RSS diagnostics, gracefully absent on Windows.
except ImportError:  # pragma: no cover — this project's target hardware is Linux
    resource = None  # type: ignore[assignment]

from hearthmind.agents.agent import DIALOGUE_COOLDOWN_TICKS, AgentGoal
from hearthmind.config import Config
from hearthmind.llm import chronicle, culture, dialogue, festival, invention, town_brain
from hearthmind.llm.client import OllamaClient
from hearthmind.llm.cognition import SYSTEM_PROMPT, build_prompt, fallback_goal, parse_goal
from hearthmind.llm.jobs import CognitionRunner
from hearthmind.persistence.snapshot import load_latest_snapshot, log_event, recent_events, save_snapshot
from hearthmind.settlement.buildings import (
    CURRENCY_CAPACITY,
    FESTIVAL_CHANCE_PER_SEASON,
    FESTIVAL_HUNGER_GATE,
    INVENTION_CHANCE_PER_YEAR,
    INVENTION_CURRENCY_THRESHOLD,
    INVENTION_MATERIALS_FRACTION,
    MATERIALS_CAPACITY,
    education_invention_bonus,
)
from hearthmind.world.state import World


def _namespaced_roll(seed: int, tick: int, namespace: str) -> float:
    """A single deterministic float in [0, 1) from (seed, tick, namespace)
    — the same discipline as Population's namespaced RNG, for the rare
    engine-level rolls (e.g. invention) that don't need a full
    random.Random instance."""
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF

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

_TERRAIN_CHANGING_CATEGORIES = frozenset({"terrain_thinned", "terrain_reclaimed", "climate_drift"})
"""Life-event categories that mean at least one tile's biome changed
this tick — see `_maybe_broadcast`."""

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
            )
        self._cognition_runner = CognitionRunner(client=client, max_concurrent=config.llm_max_concurrent)
        self._pending_goal_results: dict[int, dict] = {}
        self._inflight_cognition_agent_ids: set[int] = set()
        self._pending_dialogue_results: list[tuple[int, int, dict]] = []
        self._background_tasks: set[asyncio.Task] = set()

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
        self._maybe_schedule_invention(events)
        self._maybe_schedule_festival(events)
        self._maybe_schedule_town_brain(events)
        self._schedule_due_cognition()
        self._schedule_due_dialogue()
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

    # --- Phase E2: NPC-to-NPC dialogue ------------------------------------------

    def _apply_pending_dialogue_results(self) -> None:
        if not self._pending_dialogue_results:
            return
        for agent_a_id, agent_b_id, parsed in self._pending_dialogue_results:
            applied = self.world.population.apply_dialogue(
                agent_a_id, agent_b_id, parsed["sentiment"], parsed["rumor"],
            )
            if applied is None:
                continue
            agent_a, agent_b = applied
            self._log(
                "dialogue", f'{agent_a.name}: "{parsed["line_a"]}" — {agent_b.name}: "{parsed["line_b"]}"',
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
        pairs = self.world.population.due_for_dialogue(
            self.world.config.seed, self.world.clock.tick_count, DIALOGUE_COOLDOWN_TICKS,
        )
        if not pairs:
            return
        latest_tradition = self.world.settlement.traditions[-1] if self.world.settlement.traditions else ""
        for agent_a, agent_b in pairs:
            affinity = agent_a.relationships.get(agent_b.id, 0.0)
            prompt = dialogue.build_prompt(
                agent_a, agent_b, affinity, self.world.settlement.name, latest_tradition,
                self.world.clock.season, self.world.weather.describe(),
            )
            fallback = dialogue.fallback_dialogue(agent_a, agent_b, affinity, self.world.clock.tick_count)
            task = asyncio.create_task(self._run_dialogue(agent_a.id, agent_b.id, prompt, fallback))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _run_dialogue(self, agent_a_id: int, agent_b_id: int, prompt: str, fallback: dict) -> None:
        result, used_fallback = await self._cognition_runner.run(
            prompt, dialogue.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        parsed = dialogue.parse_dialogue(result, fallback)
        self._pending_dialogue_results.append((agent_a_id, agent_b_id, parsed))
        self._record_llm_call(used_fallback)

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
        self._log("chronicle", summary)
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
        self._log("tradition", f"The village established a new tradition — {entry}")
        self._record_llm_call(used_fallback)

    # --- Phase E3: inventions (tech-tier unlocks) -----------------------------

    def _maybe_schedule_invention(self, events: list[str]) -> None:
        """A prosperous, named settlement may invent something once per
        year — same cadence as tradition, but gated by surplus and rolled
        independently (deliberately rare, see INVENTION_CHANCE_PER_YEAR),
        so it stays a notable event rather than a yearly formality. See
        docs/DECISIONS.md, E3."""
        if "year_end" not in events or not self.world.settlement.name:
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
        chance = min(1.0, INVENTION_CHANCE_PER_YEAR * education_invention_bonus(settlement.education_level))
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "invention_roll") >= chance:
            return
        recent = recent_events(self.conn, limit=50)
        inventions = settlement.inventions
        prompt = invention.build_prompt(settlement.name, recent, inventions, settlement.tech_level)
        fallback = invention.fallback_invention(settlement.name, settlement.tech_level, len(inventions))
        task = asyncio.create_task(self._run_invention(prompt, fallback))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_invention(self, prompt: str, fallback: dict) -> None:
        result, used_fallback = await self._cognition_runner.run(
            prompt, invention.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        name, description = invention.parse_invention(result, fallback)
        entry = f"{name}: {description}"
        self.world.settlement.inventions.append(entry)
        self.world.settlement.tech_level += 1
        self._log("invention", f"The village invented {entry}")
        self._record_llm_call(used_fallback)

    # --- collective behaviour: festivals ----------------------------------------

    def _maybe_schedule_festival(self, events: list[str]) -> None:
        """A named, well-fed settlement may hold a festival once per
        season — a wellbeing gate (not prosperity, contrast
        _maybe_schedule_invention) and a seasonal cadence (not yearly),
        deliberately distinct from both traditions and inventions. See
        docs/DECISIONS.md, collective-behaviour pass."""
        if "season_end" not in events or not self.world.settlement.name:
            return
        if self.world.population.avg_hunger() > FESTIVAL_HUNGER_GATE:
            return
        if _namespaced_roll(self.world.config.seed, self.world.clock.tick_count, "festival_roll") >= FESTIVAL_CHANCE_PER_SEASON:
            return
        recent = recent_events(self.conn, limit=50)
        festivals = self.world.settlement.festivals
        prompt = festival.build_prompt(self.world.settlement.name, recent, self.world.clock.season)
        fallback = festival.fallback_festival(self.world.settlement.name, len(festivals))
        task = asyncio.create_task(self._run_festival(prompt, fallback))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_festival(self, prompt: str, fallback: dict) -> None:
        result, used_fallback = await self._cognition_runner.run(
            prompt, festival.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        name, description = festival.parse_festival(result, fallback)
        entry = f"{name}: {description}"
        self.world.settlement.festivals.append(entry)
        affected = self.world.population.hold_festival()
        self._log("festival", f"The village held {entry} ({affected} bonds strengthened)")
        self._record_llm_call(used_fallback)

    # --- the "town brain": seasonal civic-priority LLM decision -----------------

    def _maybe_schedule_town_brain(self, events: list[str]) -> None:
        """Once per season, for a named settlement, the LLM (or its
        deterministic fallback — see llm/town_brain.fallback_priority)
        decides the settlement's current civic priority — the concrete
        "LLM as the town's brain" mechanic (CLAUDE.md): the result
        measurably steers `buildings.choose_building_kind`, not just
        narration. Any queued player whispers (`settlement.player_influence`,
        via POST /intervene/town-brain) are folded in as one input among
        the real stats, then consumed. See docs/DECISIONS.md,
        "LLM-as-brain batch.\""""
        if "season_end" not in events or not self.world.settlement.name:
            return
        settlement = self.world.settlement
        recent = recent_events(self.conn, limit=50)
        population_summary = self.world.population.summary()
        settlement_summary = settlement.summary()
        prompt = town_brain.build_prompt(
            settlement.name, recent, population_summary, settlement_summary, list(settlement.player_influence),
        )
        fallback = town_brain.fallback_priority(population_summary, settlement_summary)
        task = asyncio.create_task(self._run_town_brain(prompt, fallback))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        settlement.player_influence = []  # consumed by this prompt regardless of how the LLM call resolves

    async def _run_town_brain(self, prompt: str, fallback: dict) -> None:
        result, used_fallback = await self._cognition_runner.run(
            prompt, town_brain.SYSTEM_PROMPT, fallback=lambda: fallback
        )
        priority, rationale = town_brain.parse_priority(result, fallback)
        self.world.settlement.current_priority = priority
        self.world.settlement.priority_rationale = rationale
        self._log("town_brain", f"The village's priority is now {priority} — {rationale}")
        self._record_llm_call(used_fallback)

    def _log(self, category: str, description: str) -> None:
        """Persist an event AND buffer it for the next broadcast —
        use this (not a bare `log_event` call) for anything logged
        outside `World.tick()` itself, i.e. dialogue/rumor/chronicle/
        tradition/invention/festival/intervention/town-brain, so it
        actually reaches the live WebSocket feed instead of only
        showing up via the one-shot `/events` fetch on page load. See
        `_pending_broadcast_events`, docs/DECISIONS.md, "LLM-as-brain
        batch,\" fix: live event stream gap."""
        log_event(self.conn, tick=self.world.clock.tick_count, category=category, description=description)
        self._pending_broadcast_events.append({"category": category, "description": description})

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
        if any(category in _TERRAIN_CHANGING_CATEGORIES for category, _ in self.world.last_life_events):
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
        return {
            **self._diagnostics_snapshot(),
            "peak_memory_rss_mb": peak_rss_mb,
            "db_size_mb": db_size_mb,
            "uptime_ticks": self.world.clock.tick_count,
            "population_total": len(self.world.population.agents),
        }
