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
from hearthmind.world.ca_operators import Grid, cellular_step
from hearthmind.world.terrain import Biome, Tile, classify_with_bias
from hearthmind.world.terrain_evolution import _is_developed
from hearthmind.world.weather import WeatherState

try:
    from hearthmind._native import wilt_farms_tick as _native_wilt_farms_tick
except ImportError:
    _native_wilt_farms_tick = None
"""Optional compiled fast path for `_wilt_farms` (module 13, see
cpp/src/wilt_farms.cpp, docs/DECISIONS.md "Native extension port").
Exactly one `rng.random()` draw per farm plot, unconditionally, so
Python pre-draws the whole batch (preserving stream order) and hands
it to the native call. `None` when the extension wasn't built — falls
back to the equivalent pure-Python loop in that case."""

try:
    from hearthmind._native import flat_damage_tick as _native_flat_damage_tick
except ImportError:
    _native_flat_damage_tick = None
"""Optional compiled fast path for the flat-damage sweep inside
tick_storm (module 14, see cpp/src/flat_damage.cpp). No RNG involved
once the single trigger roll (kept in Python) has decided a storm
happened — this only replaces the per-building/vehicle condition
subtraction loop."""

try:
    from hearthmind._native import roll_passes_tick as _native_roll_passes_tick
except ImportError:
    _native_roll_passes_tick = None
"""Optional compiled fast path for `tick_wildfire`'s spread roll
(module 15's `roll_passes_tick`, reused here — see cpp/src/roll_batch.
cpp). Each (active tile, neighbor) pair's spread eligibility depends
only on the pre-loop snapshot of `active_wildfire_tiles` and terrain
biomes, never on another pair's outcome within the same pass — own-
tile conversion draws no RNG at all, so it stays a separate, ordinary
Python pass before the roll batch. `None` when the extension wasn't
built — falls back to the equivalent pure-Python loop."""

FLOOD_PRESSURE_GAIN = 0.04
FLOOD_PRESSURE_DECAY = 0.03
FLOOD_PRESSURE_THRESHOLD = 1.0
FLOOD_CHANCE_PER_TICK = 0.015
FLOOD_DURATION_TICKS = 40
FLOOD_DAMAGE = 0.35
FLOOD_HEAVY_RAIN_PRECIPITATION = 0.50
"""Builds flood pressure each tick precipitation clears this bar,
decaying otherwise. Once pressure clears FLOOD_PRESSURE_THRESHOLD, each
tick rolls a small chance to submerge low ground bordering an existing
river/lake tile for FLOOD_DURATION_TICKS, knocking FLOOD_DAMAGE off any
building/vehicle caught in it and destroying any farm plot there — real
damage, not narration.

History — this constant has now been wrong in BOTH directions:

- Originally 0.4 with GAIN=0.05/DECAY=0.02. Real problem: at that duty
  cycle expected pressure drift was positive, so pressure ratcheted to
  its cap and STAYED there — flooding read as constant background
  weather, not the rare event this module describes.
- v0.88.0 ("v1 audit") fixed that by changing two things at once:
  raising the bar to 0.65 AND rebalancing GAIN/DECAY to 0.04/0.03. Only
  the GAIN/DECAY half was needed; the 0.65 half overshot into this
  codebase's own standing "unreachable threshold" bug class (CLAUDE.md),
  because `compute_weather`'s EMA smoothing keeps realized precipitation
  far narrower than the raw jitter suggests. Result: floods became
  structurally impossible, dead code guarding a fully-built subsystem.

Re-derived for the v1.34.64 audit against 328,500 samples (3 seeds x 3
FULL years — an earlier probe in the same pass sampled only ~90 ticks-
per-day-scaled days, i.e. spring alone, and reached a wrong answer;
threshold work here must span all twelve months). Realized precipitation
over that sample: min 0.105, p50 0.378, p99 0.580, max 0.670. Simulated
flood pressure against those same real weather sequences, with the
current GAIN/DECAY:

    bar   precip clears   pressure elevated   crossings   flood rolls
    0.65      0.01%             0.00%              0             0
    0.55      2.90%             0.00%              0             0
    0.50      9.99%             2.44%            272          ~13/yr
    0.45     22.90%            24.64%            122         ~136/yr
    0.40     40.94%            41.77%            243         ~228/yr

(The "flood rolls" column is an upper bound: the model above omits the
`flood_pressure *= 0.5` relief a real flood applies when it fires, so
live rates land lower. Confirmed against the real function: driving
`tick_flood` on a real world for a full sim year (36,500 ticks, 907
water tiles) at 0.50 gave peak pressure 1.63, **4 genuine flood
events**, and 78 ticks with a tile actually submerged.)

0.65 and 0.55 are both structurally dead (a 2.9% duty cycle never
accumulates 25 net gains in a row). 0.45 and below re-create the
original ratchet. 0.50 is the only value that produces a real,
self-clearing flood season — pressure elevated on ~2.4% of ticks, each
flood localized to low ground bordering water. Do not move this without
re-running that full-year measurement; the usable window is narrow and
one-sided."""

FLOOD_RECURRENCE_EROSION_THRESHOLD = 3
"""M2/M8 "flooding reshapes the land" (docs/ROADMAP-2026-07-REMAINING.
md, docs/VISION-2026-07-24-LIVINGMAP.md). A tile already gets a
temporary submerge/restore cycle every single flood (see the Biome.
SHALLOW_WATER conversion below) — but that always fully reverts, never
leaving a lasting mark. Once the SAME tile has flooded this many
separate times, its next recede applies a real, PERMANENT elevation
drop (FLOOD_EROSION_ELEVATION_DROP) instead of fully restoring the
pre-flood biome — repeated scouring genuinely wears the land down."""

FLOOD_EROSION_ELEVATION_DROP = 0.02
"""Permanent elevation lost on a recurrence-triggered erosion event —
small enough that one or two such events just leave a tile lower-lying
within its existing biome band (and more flood-prone next time), while
enough repeated erosion can genuinely push it down into BEACH or
SHALLOW_WATER permanently via the existing `classify_with_bias` bands
— same permanence discipline as A11's own `hydrology_field.tick_
erosion`. Deliberately smaller than `terrain_evolution.MINING_SCAR_
QUARRY_ELEVATION_DROP` — this fires far more often (every third flood
recurrence vs. one rare sustained-mining event)."""

WILDFIRE_CHANCE_PER_WEEK = 0.015
WILDFIRE_TEMPERAMENT_INFLUENCE = 0.5
WILDFIRE_SPREAD_CHANCE = 0.35
WILDFIRE_MAX_TILES = 14
WILDFIRE_BUILDING_DAMAGE = 0.5
WILDFIRE_DRY_PRECIPITATION = 0.25
"""The exact "unreachable threshold" bug class CLAUDE.md documents for
flood/snow/wind (v0.88.0/v1.34.64 et al.), found via a live diagnostic
showing `wildfire_ignition_ticks_recorded: 0` after 42,013 ticks. The
old value (0.1) sat BELOW `compute_weather`'s own realized minimum
summer precipitation — measured directly (10 seeds x 4 years, driven
with a real `SimClock`, same technique CLAUDE.md's weather lesson
prescribes): summer week-boundary precipitation never dropped below
~0.145, so `weather.precipitation >= WILDFIRE_DRY_PRECIPITATION` was
true on literally every summer week and `tick_wildfire` always
returned before ever rolling `WILDFIRE_CHANCE_PER_WEEK` — wildfires
were structurally impossible regardless of chance/temperament/
heatwave tuning. 0.25 sits at the same measurement's ~19th percentile
of summer precipitation (below 0.18: ~1%, below 0.22: ~7%, below 0.25:
~19%, below 0.3: ~49%) — a real "drier than typical" gate, reachable
on a genuine minority of summer weeks, not the unreachable floor the
old value was. Combined with `WILDFIRE_CHANCE_PER_WEEK`'s own 1.5%
weekly roll this still makes ignition a rare, multi-year event, not a
free retune of how OFTEN a fire starts once the gate opens."""

"""A dry summer forest tile can ignite (rare weekly roll, chance nudged
by ill-fortune temperament the same way TEMPERAMENT_KILL_CHANCE_INFLUENCE
nudges predator lethality — see settlement/buildings.py), then spreads to
neighboring forest tiles for a few ticks before burning out, turning
FOREST to GRASSLAND (ash) and damaging any building caught in its path."""

GOVERNOR_TUNING_BAND = 0.3
"""Vision doc items 1.4/2.4, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("self-tuning as bounded proposals... only ones expressed as bounded
nudges to existing governors, never raw values"). Reflection's
self-tuning job may only move a governor's effective multiplier within
[1-GOVERNOR_TUNING_BAND, 1+GOVERNOR_TUNING_BAND] of its base constant
— a real homeostatic band enforced at the proposal-parsing step
(`llm/self_tuning.py`'s `parse_self_tuning`), not just a suggestion.
`WILDFIRE_CHANCE_PER_WEEK` is the only governor wired to this band so
far (`tick_wildfire`'s `chance_multiplier` param) — the example the
vision doc names verbatim ("wildfires feel too rare to matter; widen
the ignition band 10%")."""

WILDFIRE_IGNITION_HISTORY_MAX = 20
"""Cap on `World.wildfire_ignition_ticks` — only the gap between
consecutive ignitions matters for drift detection, so this stays a
small bounded rolling window, not a growing history."""

WILDFIRE_CONTIGUITY_WEIGHT = 1.0
"""A2's first real `ca_operators.cellular_step` consumer. The ignition
tile among all forest tiles used to be picked by flat uniform choice —
`compute_forest_contiguity` instead scores each forest tile by how much
forest surrounds it (`_forest_contiguity_rule`, 1x for an isolated
stand up to 2x for one fully boxed in by forest neighbors at this
weight), and `tick_wildfire` draws the ignition site weighted by that
score: a real fire needs continuous fuel to catch and hold, so a dense
forest cluster is genuinely more likely to be where the next one
starts. Reweights WHICH forest tile catches first only — a non-forest
tile scores exactly 0 and stays excluded from the candidate list
up front, same as before this change; nothing here alters WHETHER or
HOW OFTEN a wildfire starts (`WILDFIRE_CHANCE_PER_WEEK` untouched)."""

STORM_WIND_THRESHOLD = 0.55
STORM_CHANCE_PER_TICK = 0.01
STORM_DAMAGE = 0.25
"""Extreme wind (above population.py's WEATHER_HARSH_WIND=0.5, and above
weather.py's own WINDY_WIND_THRESHOLD=0.51 — genuinely gale-adjacent, not
just "windy") has a small per-tick chance of a storm event directly
damaging standing buildings/ready vehicles map-wide, independent of
routine weather decay. Originally 0.75 — the same unreachable-threshold
bug already fixed for precipitation/temperature/wind-label: a 17,520-
tick measurement of `compute_weather`'s realized wind output topped out
at ~0.66 (see weather.py's CALM/BREEZY/WINDY_WIND_THRESHOLD docstring),
so storms were dead code that could never fire (live user report:
"storms are not shown"). Retuned to ~p90 of realized wind — reachable
in a genuine wind peak, still rare enough (combined with the 1%/tick
roll) to read as a real weather event, not routine."""

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


_FLOOD_ONSET_TEMPLATES = (
    "Floodwater swallowed the ground near ({x}, {y}).",
    "The river burst its banks near ({x}, {y}), water rising fast.",
    "Runoff pooled into a sudden flood near ({x}, {y}).",
)
_WILDFIRE_ONSET_TEMPLATES = (
    "A wildfire broke out in the forest near ({x}, {y}).",
    "Dry timber near ({x}, {y}) caught and flared into a wildfire.",
    "Smoke rose from the treeline near ({x}, {y}) as fire took hold.",
)
_STORM_TEMPLATES = (
    "A violent storm tore through, damaging {hit} structure{s}.",
    "Howling wind battered the settlement, damaging {hit} structure{s}.",
    "A sudden squall lashed the village, damaging {hit} structure{s}.",
)
_HEATWAVE_ONSET_TEMPLATES = (
    "A heatwave settled over the land, the air thick and dry.",
    "The heat turned oppressive, the sky pale and unrelenting.",
    "A dry, punishing heat rolled in and stayed.",
)
_FROST_TEMPLATES = (
    "A hard frost struck, damaging {hit} farm plot{s}.",
    "A killing frost settled overnight, damaging {hit} farm plot{s}.",
    "Ice crept over the fields by morning, damaging {hit} farm plot{s}.",
)
"""Content-variety pass (docs/DECISIONS.md "continue expanding"): the
module docstring's "no new LLM call is added here" decision stands —
these are small, purely deterministic template pools (same "cycle
through a fixed pool" shape the LLM fallback pools use, just without
ever touching an LLM), picked by the tick's own `rng` so the same
disaster kind doesn't log the identical sentence every single time it
fires across a long-running world."""


def _pick_template(rng: random.Random, templates: tuple[str, ...]) -> str:
    return templates[rng.randrange(len(templates))]


def _damage_at(settlements: list[Settlement], farms: FarmGrid, x: int, y: int, amount: float) -> None:
    # Physics doesn't care who owns the structure — every settlement's
    # buildings/vehicles on this tile take the hit (multi-settlement
    # pass, v0.65.0; previously only the single settlement existed).
    for settlement in settlements:
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
    settlements: list[Settlement], farms: FarmGrid, water_tiles: set[tuple[int, int]], rng: random.Random,
    recurrence: dict[tuple[int, int], int] | None = None,
) -> list[tuple[str, str]]:
    """Called every tick. Builds/decays flood pressure from sustained
    rain, occasionally triggers a new flood along a random water-adjacent
    low tile, and recedes any already-flooded tile whose duration expired
    (restoring its original biome). `recurrence` (M2/M8, optional,
    keyword-only in effect) counts how many separate times each tile has
    flooded — once a tile crosses FLOOD_RECURRENCE_EROSION_THRESHOLD, its
    next recede permanently erodes it instead of fully restoring the
    pre-flood biome, see FLOOD_RECURRENCE_EROSION_THRESHOLD's docstring.
    `None` (the default) reproduces the exact prior always-fully-restores
    behavior."""
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
            # The submerge itself (audit fix): the original biome was
            # always recorded and restored on recede, but the tile was
            # never actually converted to water at onset — the restore
            # was a no-op and "low ground submerges" only ever existed
            # as damage + a log line, invisible on the map and to every
            # water-biome consumer.
            terrain[y][x] = Tile(x=x, y=y, elevation=terrain[y][x].elevation, biome=Biome.SHALLOW_WATER)
            _damage_at(settlements, farms, x, y, FLOOD_DAMAGE)
            events.append(("disaster_flood", _pick_template(rng, _FLOOD_ONSET_TEMPLATES).format(x=x, y=y)))
            state.flood_pressure *= 0.5  # one flood relieves some of the built-up pressure
            if recurrence is not None:
                recurrence[(x, y)] = recurrence.get((x, y), 0) + 1

    for pos in list(state.flooded_tiles.keys()):
        original, ticks_left = state.flooded_tiles[pos]
        ticks_left -= 1
        if ticks_left <= 0:
            x, y = pos
            elevation = terrain[y][x].elevation
            if (
                recurrence is not None
                and recurrence.get(pos, 0) >= FLOOD_RECURRENCE_EROSION_THRESHOLD
                and not _is_developed(x, y, settlements, farms, set())
            ):
                # M2/M8 "flooding reshapes the land": a permanent mark
                # instead of the usual full restore, see FLOOD_
                # RECURRENCE_EROSION_THRESHOLD's docstring.
                new_elevation = max(0.0, elevation - FLOOD_EROSION_ELEVATION_DROP)
                terrain[y][x] = Tile(x=x, y=y, elevation=new_elevation, biome=classify_with_bias(new_elevation))
                recurrence[pos] = 0
                events.append((
                    "flood_eroded",
                    f"Repeated flooding has permanently worn down the ground at ({x}, {y}).",
                ))
            else:
                terrain[y][x] = Tile(x=x, y=y, elevation=elevation, biome=Biome(original))
                events.append(("disaster_flood", f"The floodwater at ({x}, {y}) receded."))
            del state.flooded_tiles[pos]
        else:
            state.flooded_tiles[pos] = (original, ticks_left)
    return events


def _forest_contiguity_rule(own: float, neighbors: list[float]) -> float:
    """`cellular_step`'s rule callback for `compute_forest_contiguity`.
    A non-forest tile (`own <= 0`) always scores 0, regardless of its
    neighbors — this only ever reweights among forest tiles, never adds
    a non-forest one to the ignition candidate pool."""
    if own <= 0.0:
        return 0.0
    neighbor_density = sum(neighbors) / len(neighbors) if neighbors else 0.0
    return own * (1.0 + neighbor_density * WILDFIRE_CONTIGUITY_WEIGHT)


def compute_forest_contiguity(terrain: list[list[Tile]]) -> Grid:
    """A2's first real `ca_operators.cellular_step` consumer — see
    `WILDFIRE_CONTIGUITY_WEIGHT`'s docstring. Builds a plain 0/1 forest
    indicator grid, then applies `_forest_contiguity_rule` once."""
    indicator: Grid = [[1.0 if t.biome is Biome.FOREST else 0.0 for t in row] for row in terrain]
    return cellular_step(indicator, _forest_contiguity_rule)


def tick_wildfire(
    state: DisasterState, terrain: list[list[Tile]], weather: WeatherState, season: str,
    temperament: float, settlements: list[Settlement], is_week_end: bool, rng: random.Random,
    heatwave_active: bool = False, farms: FarmGrid | None = None, chance_multiplier: float = 1.0,
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
        # Own-tile conversion draws no RNG at all, so it's a plain
        # Python pass over a fixed snapshot regardless of the native
        # extension's availability — only the spread roll below has
        # anything to hand off. `active_list` is captured once here so
        # both this pass and the spread-candidate pass below iterate
        # the exact same order (a live `state.active_wildfire_tiles`
        # membership test is used for eligibility either way, never
        # mutated until `|= frontier` at the very end).
        active_list = list(state.active_wildfire_tiles)
        for (x, y) in active_list:
            tile = terrain[y][x]
            if tile.biome is Biome.FOREST:
                terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
                # Audit fix: this used to pass a fresh empty FarmGrid(),
                # so crops caught in a spreading fire never burned —
                # `_damage_at`'s farm-destruction branch was dead code
                # on the one disaster where it matters most.
                _damage_at(settlements, farms if farms is not None else FarmGrid(), x, y, WILDFIRE_BUILDING_DAMAGE)

        frontier = set()
        at_cap = len(state.active_wildfire_tiles) >= WILDFIRE_MAX_TILES
        if not at_cap:
            # Native fast path (module 15's roll_passes_tick, reused):
            # each (active tile, neighbor) pair's spread eligibility
            # depends only on the pre-loop `active_list`/terrain
            # snapshot, never on another pair's outcome within this
            # same pass — a shared neighbor of two active tiles still
            # gets rolled twice here, exactly like the pure-Python
            # original, since `frontier` (not `active_wildfire_tiles`)
            # accumulates the result and isn't consulted for
            # eligibility mid-pass.
            candidates: list[tuple[int, int]] = []
            for (x, y) in active_list:
                for dx, dy in _ADJACENT:
                    nx, ny = x + dx, y + dy
                    if (
                        0 <= nx < width and 0 <= ny < height and (nx, ny) not in state.active_wildfire_tiles
                        and terrain[ny][nx].biome is Biome.FOREST
                    ):
                        candidates.append((nx, ny))
            if _native_roll_passes_tick is not None:
                rolls = [rng.random() for _ in candidates]
                for (nx, ny), did_pass in zip(candidates, _native_roll_passes_tick(rolls, WILDFIRE_SPREAD_CHANCE)):
                    if did_pass:
                        frontier.add((nx, ny))
            else:
                for (nx, ny) in candidates:
                    if rng.random() < WILDFIRE_SPREAD_CHANCE:
                        frontier.add((nx, ny))
        state.active_wildfire_tiles |= frontier
        return events

    if not is_week_end or season != "summer" or weather.precipitation >= WILDFIRE_DRY_PRECIPITATION:
        return events
    chance = WILDFIRE_CHANCE_PER_WEEK * (1.0 + max(0.0, -temperament) * WILDFIRE_TEMPERAMENT_INFLUENCE)
    if heatwave_active:
        chance *= HEATWAVE_WILDFIRE_CHANCE_MULTIPLIER
    chance *= chance_multiplier
    if rng.random() >= chance:
        return events
    forest_tiles = [(t.x, t.y) for row in terrain for t in row if t.biome is Biome.FOREST]
    if not forest_tiles:
        return events
    contiguity = compute_forest_contiguity(terrain)
    weights = [contiguity[ty][tx] for (tx, ty) in forest_tiles]
    if sum(weights) <= 0.0:
        x, y = forest_tiles[rng.randrange(len(forest_tiles))]
    else:
        x, y = rng.choices(forest_tiles, weights=weights, k=1)[0]
    tile = terrain[y][x]
    terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
    state.active_wildfire_tiles = {(x, y)}
    state.wildfire_ticks_remaining = 6
    events.append(("disaster_wildfire", _pick_template(rng, _WILDFIRE_ONSET_TEMPLATES).format(x=x, y=y)))
    return events


def tick_storm(
    weather: WeatherState, settlements: list[Settlement], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick. Extreme wind occasionally batters standing
    structures and ready vehicles directly — a sharper, rarer hit than
    the routine weather-harsh decay multiplier already applied in
    Settlement.tick."""
    if weather.wind < STORM_WIND_THRESHOLD or rng.random() >= STORM_CHANCE_PER_TICK:
        return []
    hit = 0
    for settlement in settlements:
        standing = [b for b in settlement.buildings if b.stage is BuildingStage.STANDING]
        if _native_flat_damage_tick is not None:
            for building, condition in zip(standing, _native_flat_damage_tick(
                [b.condition for b in standing], STORM_DAMAGE,
            )):
                building.condition = condition
            hit += len(standing)
            for vehicle, condition in zip(settlement.vehicles, _native_flat_damage_tick(
                [v.condition for v in settlement.vehicles], STORM_DAMAGE,
            )):
                vehicle.condition = condition
            hit += len(settlement.vehicles)
            continue
        for building in standing:
            building.condition = max(0.0, building.condition - STORM_DAMAGE)
            hit += 1
        for vehicle in settlement.vehicles:
            vehicle.condition = max(0.0, vehicle.condition - STORM_DAMAGE)
            hit += 1
    if hit == 0:
        return []
    return [(
        "disaster_storm",
        _pick_template(rng, _STORM_TEMPLATES).format(hit=hit, s="s" if hit != 1 else ""),
    )]


def _wilt_farms(farms: FarmGrid, loss_fraction: float, chance: float, rng: random.Random) -> int:
    """Shared by heatwave/frost: roll each plot independently, knocking
    `loss_fraction` of growth (GROWING) or amount (READY) off any plot
    that rolls under `chance`. A plot reduced to nothing is removed, same
    as a fully-harvested one. Returns how many plots were hit."""
    items = list(farms.plots.items())

    if _native_wilt_farms_tick is not None:
        # Native fast path (module 13): one RNG roll per plot, drawn
        # here in Python in the same order the pure-Python loop would,
        # so the stream stays identical either way.
        rolls = [rng.random() for _ in items]
        stage_in = {FarmStage.GROWING: 0, FarmStage.READY: 1}
        inputs = [
            (stage_in[plot.stage], plot.growth, plot.amount, plot.max_yield)
            for _, plot in items
        ]
        hit, results = _native_wilt_farms_tick(inputs, rolls, chance, loss_fraction)
        for (pos, plot), r in zip(items, results):
            if not r.hit:
                continue
            if r.removed:
                del farms.plots[pos]
                continue
            plot.growth = r.growth
            plot.amount = r.amount
        return hit

    hit = 0
    for pos, plot in items:
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
        events.append(("disaster_heatwave", _pick_template(rng, _HEATWAVE_ONSET_TEMPLATES)))
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
    return [(
        "disaster_frost",
        _pick_template(rng, _FROST_TEMPLATES).format(hit=hit, s="s" if hit != 1 else ""),
    )]
