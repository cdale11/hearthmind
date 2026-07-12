"""Deterministic natural disasters — rare, consequential physical events
layered on top of routine weathering (settlement/buildings.py's
DECAY_PER_TICK_BASE/SEASON_DECAY_MULTIPLIER). The engine only models the
physical event itself (what floods, what burns, what breaks); any
narration/interpretation of *why* or *what it means* is left to the
chronicle/omens LLM jobs, which already see life_events and can pick a
disaster up if they want to remark on it — no new LLM call is added
here. See docs/DECISIONS.md, "natural disasters" pass.

Three kinds, each with its own trigger and a real, mechanical
consequence:

- **Flood**: sustained heavy rain builds "flood pressure"; once past
  threshold, a small per-tick chance submerges low ground near existing
  water (river/lake tiles) for a while, damaging anything caught in it,
  then recedes.
- **Wildfire**: dry summer forest can ignite (rare weekly roll, nudged
  by ill-fortune temperament — the same lever Phase G already uses for
  invention/predator rolls), then spreads tile-to-tile for a few ticks
  before burning out.
- **Storm**: extreme wind (well past the existing "harsh weather"
  threshold) has a small per-tick chance of directly damaging standing
  buildings/ready vehicles, independent of routine decay.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.economy.farms import FarmGrid
from hearthmind.settlement.buildings import BuildingStage, Settlement
from hearthmind.world.terrain import Biome, Tile
from hearthmind.world.weather import WeatherState

FLOOD_PRESSURE_GAIN = 0.05
FLOOD_PRESSURE_DECAY = 0.02
FLOOD_PRESSURE_THRESHOLD = 1.0
FLOOD_CHANCE_PER_TICK = 0.015
FLOOD_DURATION_TICKS = 40
FLOOD_DAMAGE = 0.35
FLOOD_HEAVY_RAIN_PRECIPITATION = 0.4
"""Sustained heavy rain (precipitation above the existing "harsh
weather" threshold — see population.py's WEATHER_HARSH_PRECIPITATION)
builds flood pressure each tick it persists, decaying otherwise. Once
pressure clears the threshold, each tick rolls a small chance to submerge
low ground bordering an existing river/lake tile for FLOOD_DURATION_TICKS,
knocking FLOOD_DAMAGE off any building/vehicle caught in it and
destroying any farm plot there — real damage, not narration."""

WILDFIRE_CHANCE_PER_WEEK = 0.015
WILDFIRE_TEMPERAMENT_INFLUENCE = 0.5
WILDFIRE_SPREAD_CHANCE = 0.35
WILDFIRE_MAX_TILES = 14
WILDFIRE_BUILDING_DAMAGE = 0.5
WILDFIRE_DRY_PRECIPITATION = 0.1
"""A dry summer forest tile can ignite (rare weekly roll, chance nudged
by ill-fortune temperament the same way TEMPERAMENT_KILL_CHANCE_INFLUENCE
nudges predator lethality — see settlement/buildings.py), then spreads to
neighboring forest tiles for a few ticks before burning out, turning
FOREST to GRASSLAND (ash) and damaging any building caught in its path."""

STORM_WIND_THRESHOLD = 0.75
STORM_CHANCE_PER_TICK = 0.01
STORM_DAMAGE = 0.25
"""Extreme wind (well above population.py's WEATHER_HARSH_WIND=0.5) has
a small per-tick chance of a storm event directly damaging standing
buildings/ready vehicles map-wide, independent of routine weather
decay."""

_ADJACENT = ((0, -1), (0, 1), (-1, 0), (1, 0))


@dataclass
class DisasterState:
    flood_pressure: float = 0.0
    flooded_tiles: dict[tuple[int, int], tuple[str, int]] = field(default_factory=dict)
    """Tile -> (original Biome value, ticks remaining before it recedes)
    — tiles that flood at different times recede independently."""
    active_wildfire_tiles: set[tuple[int, int]] = field(default_factory=set)
    wildfire_ticks_remaining: int = 0

    def to_dict(self) -> dict:
        return {
            "flood_pressure": round(self.flood_pressure, 4),
            "flooded_tiles": {
                f"{x}:{y}": [biome, ticks] for (x, y), (biome, ticks) in self.flooded_tiles.items()
            },
            "active_wildfire_tiles": [[x, y] for x, y in sorted(self.active_wildfire_tiles)],
            "wildfire_ticks_remaining": self.wildfire_ticks_remaining,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DisasterState":
        flooded: dict[tuple[int, int], tuple[str, int]] = {}
        for key, value in data.get("flooded_tiles", {}).items():
            x_str, y_str = key.split(":")
            flooded[(int(x_str), int(y_str))] = (value[0], value[1])
        return cls(
            flood_pressure=data.get("flood_pressure", 0.0),
            flooded_tiles=flooded,
            active_wildfire_tiles={(x, y) for x, y in data.get("active_wildfire_tiles", [])},
            wildfire_ticks_remaining=data.get("wildfire_ticks_remaining", 0),
        )


def _damage_at(settlement: Settlement, farms: FarmGrid, x: int, y: int, amount: float) -> None:
    building = settlement.at(x, y)
    if building is not None and building.stage is BuildingStage.STANDING:
        building.condition = max(0.0, building.condition - amount)
    vehicle = settlement.vehicle_at(x, y)
    if vehicle is not None:
        vehicle.condition = max(0.0, vehicle.condition - amount)
    if (x, y) in farms.plots:
        del farms.plots[(x, y)]


def tick_flood(
    state: DisasterState, terrain: list[list[Tile]], weather: WeatherState,
    settlement: Settlement, farms: FarmGrid, water_tiles: set[tuple[int, int]], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick. Builds/decays flood pressure from sustained
    rain, occasionally triggers a new flood along a random water-adjacent
    low tile, and recedes any already-flooded tile whose duration expired
    (restoring its original biome)."""
    events: list[tuple[str, str]] = []
    height = len(terrain)
    width = len(terrain[0]) if height else 0

    if weather.precipitation > FLOOD_HEAVY_RAIN_PRECIPITATION:
        state.flood_pressure = min(2.0, state.flood_pressure + FLOOD_PRESSURE_GAIN)
    else:
        state.flood_pressure = max(0.0, state.flood_pressure - FLOOD_PRESSURE_DECAY)

    if (
        state.flood_pressure >= FLOOD_PRESSURE_THRESHOLD and water_tiles
        and rng.random() < FLOOD_CHANCE_PER_TICK
    ):
        candidates: list[tuple[int, int]] = []
        for (wx, wy) in water_tiles:
            for dx, dy in _ADJACENT:
                nx, ny = wx + dx, wy + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                pos = (nx, ny)
                if pos in state.flooded_tiles or pos in water_tiles:
                    continue
                tile = terrain[ny][nx]
                if tile.biome in (Biome.BEACH, Biome.GRASSLAND, Biome.FOREST):
                    candidates.append(pos)
        if candidates:
            x, y = candidates[rng.randrange(len(candidates))]
            original = terrain[y][x].biome.value
            state.flooded_tiles[(x, y)] = (original, FLOOD_DURATION_TICKS)
            _damage_at(settlement, farms, x, y, FLOOD_DAMAGE)
            events.append(("disaster_flood", f"Floodwater swallowed the ground near ({x}, {y})."))
            state.flood_pressure *= 0.5  # one flood relieves some of the built-up pressure

    for pos in list(state.flooded_tiles.keys()):
        original, ticks_left = state.flooded_tiles[pos]
        ticks_left -= 1
        if ticks_left <= 0:
            x, y = pos
            elevation = terrain[y][x].elevation
            terrain[y][x] = Tile(x=x, y=y, elevation=elevation, biome=Biome(original))
            del state.flooded_tiles[pos]
            events.append(("disaster_flood", f"The floodwater at ({x}, {y}) receded."))
        else:
            state.flooded_tiles[pos] = (original, ticks_left)
    return events


def tick_wildfire(
    state: DisasterState, terrain: list[list[Tile]], weather: WeatherState, season: str,
    temperament: float, settlement: Settlement, is_week_end: bool, rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick — ignition is only rolled on week boundaries
    (rare by design), but an already-burning fire spreads/dies down every
    tick it's active."""
    events: list[tuple[str, str]] = []
    height = len(terrain)
    width = len(terrain[0]) if height else 0

    if state.active_wildfire_tiles:
        state.wildfire_ticks_remaining -= 1
        if state.wildfire_ticks_remaining <= 0:
            for (x, y) in state.active_wildfire_tiles:
                tile = terrain[y][x]
                if tile.biome is Biome.FOREST:
                    terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
            state.active_wildfire_tiles = set()
            events.append(("disaster_wildfire", "The wildfire burned itself out."))
            return events
        frontier = set()
        for (x, y) in list(state.active_wildfire_tiles):
            tile = terrain[y][x]
            if tile.biome is Biome.FOREST:
                terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
                _damage_at(settlement, FarmGrid(), x, y, WILDFIRE_BUILDING_DAMAGE)
            if len(state.active_wildfire_tiles) >= WILDFIRE_MAX_TILES:
                continue
            for dx, dy in _ADJACENT:
                nx, ny = x + dx, y + dy
                if (
                    0 <= nx < width and 0 <= ny < height and (nx, ny) not in state.active_wildfire_tiles
                    and terrain[ny][nx].biome is Biome.FOREST and rng.random() < WILDFIRE_SPREAD_CHANCE
                ):
                    frontier.add((nx, ny))
        state.active_wildfire_tiles |= frontier
        return events

    if not is_week_end or season != "summer" or weather.precipitation >= WILDFIRE_DRY_PRECIPITATION:
        return events
    chance = WILDFIRE_CHANCE_PER_WEEK * (1.0 + max(0.0, -temperament) * WILDFIRE_TEMPERAMENT_INFLUENCE)
    if rng.random() >= chance:
        return events
    forest_tiles = [(t.x, t.y) for row in terrain for t in row if t.biome is Biome.FOREST]
    if not forest_tiles:
        return events
    x, y = forest_tiles[rng.randrange(len(forest_tiles))]
    tile = terrain[y][x]
    terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
    state.active_wildfire_tiles = {(x, y)}
    state.wildfire_ticks_remaining = 6
    events.append(("disaster_wildfire", f"A wildfire broke out in the forest near ({x}, {y})."))
    return events


def tick_storm(
    weather: WeatherState, settlement: Settlement, rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick. Extreme wind occasionally batters standing
    structures and ready vehicles directly — a sharper, rarer hit than
    the routine weather-harsh decay multiplier already applied in
    Settlement.tick."""
    if weather.wind < STORM_WIND_THRESHOLD or rng.random() >= STORM_CHANCE_PER_TICK:
        return []
    hit = 0
    for building in settlement.buildings:
        if building.stage is BuildingStage.STANDING:
            building.condition = max(0.0, building.condition - STORM_DAMAGE)
            hit += 1
    for vehicle in settlement.vehicles:
        vehicle.condition = max(0.0, vehicle.condition - STORM_DAMAGE)
        hit += 1
    if hit == 0:
        return []
    return [("disaster_storm", f"A violent storm tore through, damaging {hit} structure{'s' if hit != 1 else ''}.")]
