"""The World aggregate.

`World` is the single object that fully describes the simulation's state at
a point in time. It owns nothing that can't be serialized to a plain dict,
which is what makes snapshotting trivial (see persistence/snapshot.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.agents.population import Population
from hearthmind.config import Config
from hearthmind.settlement.buildings import Settlement
from hearthmind.time_system import SimClock
from hearthmind.world.resources import ResourceGrid
from hearthmind.world.terrain import Tile, biome_counts, generate_terrain
from hearthmind.world.weather import WeatherState, compute_weather


@dataclass
class World:
    config: Config
    clock: SimClock
    terrain: list[list[Tile]]
    weather: WeatherState
    population: Population
    resources: ResourceGrid
    settlement: Settlement
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
        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            population=population, resources=resources, settlement=settlement,
        )

    # --- tick --------------------------------------------------------------

    def tick(self) -> list[str]:
        """Advance the world by one tick. Returns calendar-boundary events
        crossed (e.g. ["day_end"]), for the caller to log. Births/deaths/
        construction events from this tick are left on `last_life_events`
        for the caller."""
        events = self.clock.advance()
        self.weather = compute_weather(
            seed=self.config.seed,
            tick=self.clock.tick_count,
            season=self.clock.season,
            previous=self.weather,
        )
        self.resources.tick()
        settlement_events = self.settlement.tick(weather=self.weather)
        population_events = self.population.tick(
            seed=self.config.seed, tick=self.clock.tick_count,
            terrain=self.terrain, resources=self.resources, settlement=self.settlement,
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
            "biome_counts": biome_counts(self.terrain),
            "world_size": f"{self.config.width}x{self.config.height}",
            "population": self.population.summary(),
            "resources": self.resources.summary(),
            "settlement": self.settlement.summary(),
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
        pre-Phase-C). Any missing subsystem is freshly backfilled and its
        name recorded in `migrated_subsystems` so the caller can log/persist
        the change once (see M2-3, generalized in A4)."""
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

        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            population=population, resources=resources, settlement=settlement,
            migrated_subsystems=migrated_subsystems,
        )
