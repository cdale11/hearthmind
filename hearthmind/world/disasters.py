"""Deterministic natural disasters — rare, consequential physical events
layered on top of routine weathering (settlement/buildings.py's
DECAY_PER_TICK_BASE/SEASON_DECAY_MULTIPLIER). The engine only models the
physical event itself (what floods, what burns, what breaks); any
narration/interpretation of *why* or *what it means* is left to the
chronicle/omens LLM jobs, which already see life_events and can pick a
disaster up if they want to remark on it — no new LLM call is added
here. See docs/DECISIONS.md, "natural disasters" pass.

Five kinds, each with its own trigger and a real, mechanical
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
- **Heatwave**: sustained hot, dry weather (UK's own climate scale runs
  cooler than the official 25-28C policy threshold, so this is scaled
  to the same baselines as `weather.py`) builds "heat pressure" the same
  way flood pressure builds from rain; once triggered it persists for a
  while, wilting/spoiling farm plots and raising wildfire ignition odds
  — a real UK pattern (2018, 2022 heatwaves both came with drought and a
  spike in wildfires).
- **Frost/cold snap**: the mirror image — a sustained hard freeze (well
  below the existing snow threshold) damages exposed farm plots, echoing
  events like the UK's 2018 "Beast from the East".
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.economy.farms import FarmGrid, FarmStage
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

HEATWAVE_BUILD_TEMP = 18.5
HEATWAVE_DRY_PRECIPITATION = 0.22
HEATWAVE_PRESSURE_GAIN = 0.05
HEATWAVE_PRESSURE_DECAY = 0.015
HEATWAVE_PRESSURE_THRESHOLD = 0.9
HEATWAVE_CHANCE_PER_TICK = 0.01
HEATWAVE_DRY_CHANCE_MULTIPLIER = 2.5
HEATWAVE_DURATION_TICKS = 60
HEATWAVE_FARM_WILT_CHANCE = 0.01
HEATWAVE_FARM_LOSS_FRACTION = 0.15
"""Sustained heat (temperature above HEATWAVE_BUILD_TEMP, the same
pressure-buildup shape as flood — dryness isn't required to build
pressure, only to make the trigger roll more likely once pressure clears
threshold, since requiring both simultaneously nearly never fires
against `compute_weather`'s actual smoothed output) can trigger a
heatwave that persists HEATWAVE_DURATION_TICKS. While active, every farm
plot has a
small per-tick chance of losing HEATWAVE_FARM_LOSS_FRACTION of its
growth/yield to heat stress — growing crops wilt, ready crops spoil on
the vine (a ready plot fully consumed this way is removed, same as a
harvested-out plot). Consumed by population.py's weather_harsh check
(via `DisasterState.heatwave_active`) so agents also feel it, and nudges
wildfire ignition odds in tick_wildfire — real UK heatwaves (2018, 2022)
came with drought and a spike in wildfires, not just heat alone."""
HEATWAVE_WILDFIRE_CHANCE_MULTIPLIER = 2.0
"""Applied on top of WILDFIRE_CHANCE_PER_WEEK's temperament nudge when a
heatwave is active — dry heat is a much stronger fire driver than ill
fortune alone. HEATWAVE_BUILD_TEMP/HEATWAVE_DRY_PRECIPITATION were both
tuned against `compute_weather`'s actual smoothed summer output (which
tops out around 21C, not the raw uniform-jitter range) — see
SNOW_TEMPERATURE_THRESHOLD_C's docstring in weather.py for the same
"threshold the model can actually reach" fix applied there."""

FROST_TEMP_THRESHOLD = 2.0
FROST_DURATION_MIN_TICKS = 6
FROST_CHANCE_PER_TICK = 0.05
FROST_FARM_LOSS_FRACTION = 0.25
"""A hard freeze at or below FROST_TEMP_THRESHOLD (colder than
weather.py's SNOW_TEMPERATURE_THRESHOLD_C=2.0 — a below-snow "cold
snap", not routine winter cold) sustained for FROST_DURATION_MIN_TICKS
has a small per-tick chance of a frost event that damages every farm
plot in one hit (FROST_FARM_LOSS_FRACTION off growth/yield) — real UK
events like the 2018 "Beast from the East" killed crops and livestock
outright, a sharper, rarer hit than winter's routine growth slowdown
(economy/farms.py's SEASON_GROWTH_MULTIPLIER). Threshold tuned against
`compute_weather`'s actual smoothed output range, same fix as
SNOW_TEMPERATURE_THRESHOLD_C — an unreached threshold is dead code, not
a rarer event."""

_ADJACENT = ((0, -1), (0, 1), (-1, 0), (1, 0))


@dataclass
class DisasterState:
    flood_pressure: float = 0.0
    flooded_tiles: dict[tuple[int, int], tuple[str, int]] = field(default_factory=dict)
    """Tile -> (original Biome value, ticks remaining before it recedes)
    — tiles that flood at different times recede independently."""
    active_wildfire_tiles: set[tuple[int, int]] = field(default_factory=set)
    wildfire_ticks_remaining: int = 0
    heat_pressure: float = 0.0
    heatwave_active: bool = False
    heatwave_ticks_remaining: int = 0
    frost_ticks: int = 0
    """Consecutive ticks the temperature has held below FROST_TEMP_
    THRESHOLD — resets to 0 the moment it warms back up, same shape as
    flood/heat pressure but a plain counter since frost is a single
    instantaneous hit rather than a lingering state like flood/heatwave."""

    def to_dict(self) -> dict:
        return {
            "flood_pressure": round(self.flood_pressure, 4),
            "flooded_tiles": {
                f"{x}:{y}": [biome, ticks] for (x, y), (biome, ticks) in self.flooded_tiles.items()
            },
            "active_wildfire_tiles": [[x, y] for x, y in sorted(self.active_wildfire_tiles)],
            "wildfire_ticks_remaining": self.wildfire_ticks_remaining,
            "heat_pressure": round(self.heat_pressure, 4),
            "heatwave_active": self.heatwave_active,
            "heatwave_ticks_remaining": self.heatwave_ticks_remaining,
            "frost_ticks": self.frost_ticks,
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
            heat_pressure=data.get("heat_pressure", 0.0),
            heatwave_active=data.get("heatwave_active", False),
            heatwave_ticks_remaining=data.get("heatwave_ticks_remaining", 0),
            frost_ticks=data.get("frost_ticks", 0),
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
    heatwave_active: bool = False,
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
    if heatwave_active:
        chance *= HEATWAVE_WILDFIRE_CHANCE_MULTIPLIER
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


def _wilt_farms(farms: FarmGrid, loss_fraction: float, chance: float, rng: random.Random) -> int:
    """Shared by heatwave/frost: roll each plot independently, knocking
    `loss_fraction` of growth (GROWING) or amount (READY) off any plot
    that rolls under `chance`. A plot reduced to nothing is removed, same
    as a fully-harvested one. Returns how many plots were hit."""
    hit = 0
    for pos, plot in list(farms.plots.items()):
        if rng.random() >= chance:
            continue
        hit += 1
        if plot.stage is FarmStage.GROWING:
            plot.growth = max(0.0, plot.growth - loss_fraction)
        else:
            plot.amount = max(0.0, plot.amount - loss_fraction * plot.max_yield)
            if plot.amount <= 0.0:
                del farms.plots[pos]
    return hit


def tick_heatwave(
    state: DisasterState, weather: WeatherState, farms: FarmGrid, rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick. Builds/decays heat pressure from sustained hot,
    dry weather exactly like tick_flood builds pressure from rain; once a
    heatwave is triggered it persists for HEATWAVE_DURATION_TICKS,
    wilting/spoiling farm plots each tick before breaking. Callers should
    also feed `state.heatwave_active` into population.py's weather_harsh
    check and tick_wildfire's `heatwave_active` param — see the module
    docstring."""
    events: list[tuple[str, str]] = []

    if state.heatwave_active:
        state.heatwave_ticks_remaining -= 1
        hit = _wilt_farms(farms, HEATWAVE_FARM_LOSS_FRACTION, HEATWAVE_FARM_WILT_CHANCE, rng)
        if hit:
            events.append(("disaster_heatwave", f"The heatwave wilted crops on {hit} plot{'s' if hit != 1 else ''}."))
        if state.heatwave_ticks_remaining <= 0:
            state.heatwave_active = False
            state.heat_pressure = 0.0
            events.append(("disaster_heatwave", "The heatwave finally broke."))
        return events

    if weather.temperature_c > HEATWAVE_BUILD_TEMP:
        state.heat_pressure = min(2.0, state.heat_pressure + HEATWAVE_PRESSURE_GAIN)
    else:
        state.heat_pressure = max(0.0, state.heat_pressure - HEATWAVE_PRESSURE_DECAY)

    if state.heat_pressure < HEATWAVE_PRESSURE_THRESHOLD:
        return events
    chance = HEATWAVE_CHANCE_PER_TICK
    if weather.precipitation < HEATWAVE_DRY_PRECIPITATION:
        chance *= HEATWAVE_DRY_CHANCE_MULTIPLIER  # a sustained hot spell is likelier to break as a heatwave once it's also dry
    if rng.random() < chance:
        state.heatwave_active = True
        state.heatwave_ticks_remaining = HEATWAVE_DURATION_TICKS
        events.append(("disaster_heatwave", "A heatwave settled over the land, the air thick and dry."))
    return events


def tick_frost(
    state: DisasterState, weather: WeatherState, farms: FarmGrid, rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick. Tracks consecutive ticks below FROST_TEMP_
    THRESHOLD; once that streak is long enough, rolls a small per-tick
    chance of a single hard-frost event damaging every farm plot at
    once (unlike heatwave's per-tick wilt, a frost is one sharp hit, not
    a lingering state — see module docstring)."""
    if weather.temperature_c > FROST_TEMP_THRESHOLD:
        state.frost_ticks = 0
        return []
    state.frost_ticks += 1
    if state.frost_ticks < FROST_DURATION_MIN_TICKS or rng.random() >= FROST_CHANCE_PER_TICK:
        return []
    state.frost_ticks = 0
    hit = _wilt_farms(farms, FROST_FARM_LOSS_FRACTION, 1.0, rng)
    if hit == 0:
        return []
    return [("disaster_frost", f"A hard frost struck, damaging {hit} farm plot{'s' if hit != 1 else ''}.")]
