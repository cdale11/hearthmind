"""The World aggregate.

`World` is the single object that fully describes the simulation's state at
a point in time. It owns nothing that can't be serialized to a plain dict,
which is what makes snapshotting trivial (see persistence/snapshot.py).
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from hearthmind.agents.population import Population
from hearthmind.config import Config
from hearthmind.economy.farms import FarmGrid
from hearthmind.settlement.buildings import BuildingStage, Settlement
from hearthmind.settlement.naming import generate_settlement_name
from hearthmind.time_system import SimClock
from hearthmind.world.resources import ResourceGrid
from hearthmind.world.roads import RoadNetwork
from hearthmind.world.terrain import Tile, biome_counts, generate_terrain
from hearthmind.world.weather import WeatherState, compute_weather
from hearthmind.world.wildlife import WildlifeGrid


def _namespaced_rng(seed: int, tick: int, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


@dataclass
class World:
    config: Config
    clock: SimClock
    terrain: list[list[Tile]]
    weather: WeatherState
    population: Population
    resources: ResourceGrid
    settlement: Settlement
    farms: FarmGrid
    wildlife: WildlifeGrid
    roads: RoadNetwork
    llm_calls_total: int = 0
    llm_fallback_total: int = 0
    """Cumulative counts of every LLM-backed decision (cognition +
    chronicle) since world creation, and how many of those fell back to
    deterministic behavior — visible via `inspect_world` to diagnose a
    flaky/overloaded Ollama instance without reading server logs. See
    docs/DECISIONS.md, D5."""
    dialogue_total: int = 0
    rumor_total: int = 0
    """Cumulative counts of NPC dialogue exchanges and the rumors they've
    seeded since world creation — the same "make emergence visible in
    diagnostics" rationale as llm_calls_total, for a system (E2) that has
    no other cumulative counter. See docs/DECISIONS.md, E2/UI pass."""
    last_calendar_events: list[str] = field(default_factory=list)
    last_life_events: list[tuple[str, str]] = field(default_factory=list, compare=False)
    """(category, description) pairs from this tick's births/deaths, for the
    caller to log. Never serialized — recomputed fresh every tick."""
    migrated_subsystems: list[str] = field(default_factory=list, compare=False)
    """Names of subsystems that were missing from a loaded snapshot and got
    freshly backfilled (e.g. ["population", "resources"]) — lets the caller
    (SimulationEngine) log a one-off migration event per subsystem and
    persist the change. Never itself serialized; see docs/DECISIONS.md,
    M2-3 and A4."""

    # --- construction ----------------------------------------------------

    @classmethod
    def create_new(cls, config: Config) -> "World":
        clock = SimClock(config=config, tick_count=0)
        terrain = generate_terrain(seed=config.seed, width=config.width, height=config.height)
        weather = compute_weather(seed=config.seed, tick=0, season=clock.season, previous=None)
        population = Population.spawn_initial(
            seed=config.seed, count=config.initial_population, terrain=terrain,
        )
        resources = ResourceGrid.generate(seed=config.seed, terrain=terrain)
        settlement = Settlement()  # settlements emerge from population behavior, not pre-placed
        farms = FarmGrid()  # likewise: no farms exist until agents plant them
        wildlife = WildlifeGrid.generate(seed=config.seed, terrain=terrain)
        roads = RoadNetwork()  # paths emerge from foot traffic, not pre-placed
        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            population=population, resources=resources, settlement=settlement, farms=farms,
            wildlife=wildlife, roads=roads,
        )

    # --- tick --------------------------------------------------------------

    def tick(self) -> list[str]:
        """Advance the world by one tick. Returns calendar-boundary events
        crossed (e.g. ["day_end"]), for the caller to log. Births/deaths/
        construction/farming events from this tick are left on
        `last_life_events` for the caller."""
        events = self.clock.advance()
        self.weather = compute_weather(
            seed=self.config.seed,
            tick=self.clock.tick_count,
            season=self.clock.season,
            previous=self.weather,
        )
        self.resources.tick(season=self.clock.season)
        self.farms.tick(season=self.clock.season)
        self.wildlife.tick(seed=self.config.seed, tick=self.clock.tick_count, terrain=self.terrain)
        settlement_events = self.settlement.tick(weather=self.weather)
        if not self.settlement.name and any(
            b.stage is BuildingStage.STANDING for b in self.settlement.buildings
        ):
            rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "settlement_naming")
            self.settlement.name = generate_settlement_name(rng)
            settlement_events.append(("settlement_named", f"The village was named {self.settlement.name}."))
        population_events = self.population.tick(
            seed=self.config.seed, tick=self.clock.tick_count,
            terrain=self.terrain, resources=self.resources,
            settlement=self.settlement, farms=self.farms, wildlife=self.wildlife, roads=self.roads,
            weather=self.weather,
        )
        self.last_life_events = settlement_events + population_events
        self.last_calendar_events = events
        return events

    # --- summary for humans / the future interface ------------------------

    def summary(self) -> dict:
        return {
            "tick": self.clock.tick_count,
            "date": self.clock.date_string(),
            "clock": self.clock.clock_string(),
            "season": self.clock.season,
            "year": self.clock.year,
            "weather": self.weather.describe(),
            "weather_detail": self.weather.to_dict(),
            "biome_counts": biome_counts(self.terrain),
            "world_size": f"{self.config.width}x{self.config.height}",
            "population": self.population.summary(),
            "resources": self.resources.summary(),
            "settlement": self.settlement.summary(),
            "farms": self.farms.summary(),
            "wildlife": self.wildlife.summary(),
            "roads": self.roads.summary(),
            "llm": {
                "calls_total": self.llm_calls_total,
                "fallback_total": self.llm_fallback_total,
                "fallback_rate": (
                    round(self.llm_fallback_total / self.llm_calls_total, 3)
                    if self.llm_calls_total else 0.0
                ),
                "dialogue_total": self.dialogue_total,
                "rumor_total": self.rumor_total,
            },
        }

    # --- (de)serialization --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "config": {
                "seed": self.config.seed,
                "width": self.config.width,
                "height": self.config.height,
                "sim_minutes_per_tick": self.config.sim_minutes_per_tick,
                "minutes_per_day": self.config.minutes_per_day,
                "days_per_season": self.config.days_per_season,
                "seasons_per_year": list(self.config.seasons_per_year),
                "initial_population": self.config.initial_population,
            },
            "clock": self.clock.to_dict(),
            "terrain": [[tile.to_dict() for tile in row] for row in self.terrain],
            "weather": self.weather.to_dict(),
            "population": self.population.to_dict(),
            "resources": self.resources.to_dict(),
            "settlement": self.settlement.to_dict(),
            "farms": self.farms.to_dict(),
            "wildlife": self.wildlife.to_dict(),
            "roads": self.roads.to_dict(),
            "llm_calls_total": self.llm_calls_total,
            "llm_fallback_total": self.llm_fallback_total,
            "dialogue_total": self.dialogue_total,
            "rumor_total": self.rumor_total,
        }

    @classmethod
    def from_dict(cls, data: dict, runtime_config: Config) -> "World":
        """Reconstruct a World from a snapshot dict. Creation-only fields
        (seed/width/height/calendar shape, including sim_minutes_per_tick)
        come from the snapshot itself, not from `runtime_config` — those
        were fixed when the world was created and affect calendar math.
        Runtime fields (tick_seconds, snapshot_every_ticks, db_path) come
        from `runtime_config`, since those only control pacing/storage and
        are safe to change between runs.

        Snapshots may be missing subsystems added by later releases (e.g.
        "population" pre-Milestone-2, "resources" pre-Phase-A, "settlement"
        pre-Phase-C, "farms" pre-Phase-D). Any missing subsystem is freshly
        backfilled and its name recorded in `migrated_subsystems` so the
        caller can log/persist the change once (see M2-3, generalized in
        A4)."""
        saved = data["config"]
        config = Config(
            seed=saved["seed"],
            width=saved["width"],
            height=saved["height"],
            sim_minutes_per_tick=saved["sim_minutes_per_tick"],
            minutes_per_day=saved["minutes_per_day"],
            days_per_season=saved["days_per_season"],
            seasons_per_year=tuple(saved["seasons_per_year"]),
            initial_population=saved.get("initial_population", Config.initial_population),
            tick_seconds=runtime_config.tick_seconds,
            snapshot_every_ticks=runtime_config.snapshot_every_ticks,
            db_path=runtime_config.db_path,
        )
        clock = SimClock.from_dict(config, data["clock"])
        terrain = [[Tile.from_dict(t) for t in row] for row in data["terrain"]]
        weather = WeatherState.from_dict(data["weather"])

        migrated_subsystems: list[str] = []

        if "population" in data:
            population = Population.from_dict(data["population"])
        else:
            population = Population.spawn_initial(
                seed=config.seed, count=config.initial_population, terrain=terrain,
            )
            migrated_subsystems.append("population")

        if "resources" in data:
            resources = ResourceGrid.from_dict(data["resources"])
        else:
            resources = ResourceGrid.generate(seed=config.seed, terrain=terrain)
            migrated_subsystems.append("resources")

        if "settlement" in data:
            settlement = Settlement.from_dict(data["settlement"])
        else:
            settlement = Settlement()  # no retroactive guessing at pre-existing structures
            migrated_subsystems.append("settlement")

        if "farms" in data:
            farms = FarmGrid.from_dict(data["farms"])
        else:
            farms = FarmGrid()  # no retroactive guessing at pre-existing farmland
            migrated_subsystems.append("farms")

        if "wildlife" in data:
            wildlife = WildlifeGrid.from_dict(data["wildlife"])
        else:
            wildlife = WildlifeGrid.generate(seed=config.seed, terrain=terrain)
            migrated_subsystems.append("wildlife")

        if "roads" in data:
            roads = RoadNetwork.from_dict(data["roads"])
        else:
            roads = RoadNetwork()  # no retroactive guessing at pre-existing paths
            migrated_subsystems.append("roads")

        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            population=population, resources=resources, settlement=settlement, farms=farms,
            wildlife=wildlife, roads=roads,
            llm_calls_total=data.get("llm_calls_total", 0),
            llm_fallback_total=data.get("llm_fallback_total", 0),
            dialogue_total=data.get("dialogue_total", 0),
            rumor_total=data.get("rumor_total", 0),
            migrated_subsystems=migrated_subsystems,
        )
