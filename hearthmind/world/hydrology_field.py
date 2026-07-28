"""A11 "Continuous hydrology" (docs/MASTERCHECKLIST-2026-07-22.md,
Stage IV step 15 — the roadmap's own "highest-leverage single item:
touches agriculture, siting, disasters, ecology at once").

The existing `world/hydrology.py` only answers "is this tile a river
or a lake" — a one-time-carved, mostly-static classification. What A11
actually asks for is water as a CONTINUOUS field every tile carries,
with real flow and feedback. This ships:

  precipitation -> single-pass downhill redistribution -> evaporation

as a real per-tile `moisture` field (`HydrologyField`), consumed by a
real mechanic (farm planting yield, see `economy/farms.py`'s new
`moisture` param on `plant()`).

**Groundwater** (second slice, docs/ROADMAP-2026-07-REMAINING.md's A11
entry): a per-tile `groundwater` reservoir, distinct from surface
`moisture`. Land tiles above `GROUNDWATER_INFILTRATION_THRESHOLD`
infiltrate a fraction of their surface moisture into groundwater each
week (real rain "sinking in," not just running off/evaporating);
tiles below `GROUNDWATER_SEEP_THRESHOLD` draw a small amount back OUT
of groundwater into surface moisture — a spring/base-flow effect that
gives dry stretches real resilience a surface-only model couldn't:
land that was wet recently stays measurably less parched than land
that never was. `GROUNDWATER_PERCOLATION_LOSS` is a small constant
weekly drain (representing water sinking below the reachable zone
entirely), so groundwater doesn't just ratchet upward forever.

**Erosion** (second slice): `Tile.elevation` has been storage-layer
mutable since v0.74.1 on both the native `TerrainGrid` and the plain-
Python fallback (`TerrainGrid._set_tile`/`TerrainRow.__setitem__`
already accept and store any elevation value — see `world/terrain.py`)
— nothing here changed at that layer; this module is simply the first
real WRITER of a new elevation value. `tick_erosion` reuses `tick_
hydrology`'s own steepest-descent neighbor-finding (a tile whose
surface moisture is above `EROSION_MOISTURE_THRESHOLD` — i.e.
genuinely wet enough to be carrying flow, not just damp) moves a small,
capped fraction of the elevation gap to its lowest orthogonal
neighbor, mass-conserving (what erodes from the source tile deposits
at the target), skipping any tile whose lowest neighbor is a pinned
water/RIVER biome (siltation into standing water is real-world true
but adds a second, harder-to-bound feedback loop — deliberately out of
scope this pass, flagged). Whenever a tile's elevation genuinely
crosses a biome threshold, its biome is re-derived via `classify_with_
bias` in the SAME write — the one real coherence hazard here (nothing
else in the codebase reads raw `.elevation`; every consumer keys off
`.biome`, so biome drifting out of sync with elevation would be a
silent, hard-to-notice bug, not a loud one). Capped to a small
per-tile-per-week magnitude by design — this reshapes the map over
real years of play, the same "history becomes physically visible over
the long run" pace every other scar-shaped mechanism in this codebase
already uses, not an instant rewrite.

R7 deviation, flagged (docs/CONSTITUTION.md's "new physical-substrate
code is C++-first" rule): this ships in pure Python, not yet natively
ported, unlike this codebase's usual practice for new per-tile Body
systems. Justification: this is a genuinely NEW field-based mechanism
(not a reimplementation of an existing pattern the way e.g.
mining_scars/soil_fertility were) — the exact shape of the flow-
accumulation algorithm needs to prove itself against real gameplay
before being locked into a compiled interface that's expensive to
iterate on further. Computed on a WEEKLY cadence (not per-tick) to keep
the real-time cost of an un-ported full-grid pass bounded in the
meantime — see `World._tick_disasters`. Port to C++ once the shape is
confirmed live, following `cpp/src/soil_fertility.cpp`'s precedent
exactly (same "prove Python correctness first, then mirror the exact
math into C++" discipline already used elsewhere in this codebase for
a from-scratch mechanism). Erosion's own elevation-write call goes
through the exact same `TerrainGrid`/`TerrainRow` storage API every
other terrain mutator (`terrain_evolution.py`, `hydrology.py`,
`disasters.py`) already uses — no new native-vs-fallback equivalence
risk beyond what those modules already carry, since the storage layer
itself was proven at v0.74.1, not by this pass."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.world.ca_operators import reaction_diffuse
from hearthmind.world.terrain import Biome, Tile, classify_with_bias

MOISTURE_MIN = 0.0
MOISTURE_MAX = 1.0
MOISTURE_DEFAULT = 0.35
"""A never-farmed, non-water tile's starting moisture — moderate, not
saturated or parched, so the field has real room to move in either
direction as precipitation/flow/evaporation act on it."""

MOISTURE_PRECIPITATION_GAIN = 0.30
"""Per weekly tick, scaled by `WeatherState.precipitation` (0..1) —
land tiles gain up to this much moisture on a fully saturated-rain
week."""

MOISTURE_FLOW_FRACTION = 0.20
"""Fraction of a tile's ABOVE-NEIGHBOR moisture excess pushed to its
single lowest-elevation orthogonal neighbor each weekly tick — a
simple single-step steepest-descent transfer, not a full iterative
shallow-water solve. Over many weeks this still produces a real
"water moves downhill and pools in low ground" pattern; it just
doesn't converge to a physically exact flow field in one step."""

MOISTURE_EVAPORATION_BASE = 0.06
MOISTURE_EVAPORATION_HEAT_BONUS = 0.05
"""Added on top of the base evaporation rate during `"summer"` —
warmer weeks dry the land faster, same "climate/weather is a real
catalyst" discipline `terrain_evolution.py`'s decay math already
established for building wear."""

_ADJACENT_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))
_WATER_BIOMES = frozenset({Biome.DEEP_WATER, Biome.SHALLOW_WATER, Biome.RIVER})

GROUNDWATER_MIN = 0.0
GROUNDWATER_MAX = 1.0
GROUNDWATER_DEFAULT = 0.3
"""A never-farmed, non-water tile's starting groundwater — moderate,
not empty or full, matching `MOISTURE_DEFAULT`'s own "real room to move
either way" reasoning."""

GROUNDWATER_INFILTRATION_THRESHOLD = 0.6
GROUNDWATER_INFILTRATION_FRACTION = 0.08
"""A land tile whose surface `moisture` (post-`tick_hydrology`) is
above this threshold infiltrates this fraction of the excess into
groundwater each week — real rain "sinking in" once the surface is
already wet enough for it, not siphoning off a dry tile's own scant
moisture."""

GROUNDWATER_SEEP_THRESHOLD = 0.3
GROUNDWATER_SEEP_FRACTION = 0.05
"""A land tile whose surface `moisture` is below this threshold draws
this fraction of the CURRENT groundwater deficit-to-threshold back out
of groundwater into surface moisture each week — the base-flow/spring
effect: a tile with a full groundwater reserve resists drying out as
fast as one with none, even though both show the same surface
moisture reading right now."""

GROUNDWATER_PERCOLATION_LOSS = 0.01
"""Small constant weekly drain applied to every land tile's groundwater
regardless of infiltration/seep — water sinking below the reachable
zone entirely. Without this, groundwater would only ever ratchet
upward under any positive infiltration, never settling to a real
equilibrium."""

EROSION_MOISTURE_THRESHOLD = 0.55
"""A tile's surface `moisture` (post-`tick_hydrology`) must be at or
above this to erode at all this week — erosion needs genuine flow, not
just ambient dampness. Land well below this threshold never erodes,
regardless of slope."""

EROSION_RATE = 0.05
"""Fraction of the elevation excess to a tile's lowest orthogonal
neighbor moved per week, for a tile that clears `EROSION_MOISTURE_
THRESHOLD` — same "fraction of the excess, not the excess itself"
shape as `MOISTURE_FLOW_FRACTION`."""

EROSION_MAX_DELTA_PER_TILE_PER_WEEK = 0.01
"""Hard cap on how much a single tile's elevation can change in one
week, regardless of how large the computed excess/rate would otherwise
allow — keeps erosion a "the map visibly reshapes over real years of
play" mechanism, not an overnight rewrite. Elevation spans 0..1 across
eight biome bands (`classify_with_bias`), so this caps roughly one
biome-band crossing to several real years of sustained erosive
conditions at one tile, not less."""


SNOWPACK_MIN = 0.0
SNOWPACK_MAX = 1.0
SNOWPACK_DEFAULT = 0.0
"""Unlike `MOISTURE_DEFAULT`/`GROUNDWATER_DEFAULT`'s "real room to move
either way" starting point, a fresh world starts with zero snowpack —
worlds always begin in spring (see CLAUDE.md's calendar section), so
"no accumulated snow yet" is the honest default, not a neutral
midpoint."""

SNOWPACK_FREEZE_TEMP_C = 0.0
"""At or below this regional temperature, a tick's exchange runs in
the freezing direction (moisture -> snowpack); above it, thawing
(snowpack -> moisture)."""

SNOWPACK_FREEZE_RATE = 0.12
"""A2 "CA / diffusion / reaction-diffusion operators" (docs/ROADMAP-
2026-07-REMAINING.md, Tier 1): `ca_operators.reaction_diffuse`'s first
real consumer — `moisture`/`snowpack` are a genuine mass-conserving
pair (literally the same water in two states), the textbook shape that
operator's own docstring calls for, unlike every `FieldGrid` field
(independent quantities, never meant to trade mass with each other).
Fraction of a freezing tile's surface moisture converted to snowpack
per week."""

SNOWPACK_MELT_RATE = 0.25
"""Fraction of a thawing tile's snowpack converted back to surface
moisture per week — melts faster than it accumulates, matching the
real seasonal asymmetry: snow builds slowly over a whole winter, melts
within a much shorter spring window."""


@dataclass
class HydrologyField:
    """Per-tile surface-moisture (`moisture`), subsurface-reservoir
    (`groundwater`), and accumulated-snow (`snowpack`) values for every
    tile on the map. Water-biome tiles are always pinned to `MOISTURE_
    MAX` (they ARE the water, not land holding moisture) — everything
    else is a real, continuously-updated quantity. `groundwater` is not
    pinned for water tiles — a lake/river bed still has a real
    subsurface reservoir underneath it, distinct from the surface water
    itself. `snowpack` IS pinned to 0 for water tiles (open water
    doesn't accumulate snow cover the way land does)."""

    moisture: list[list[float]] = field(default_factory=list)
    groundwater: list[list[float]] = field(default_factory=list)
    snowpack: list[list[float]] = field(default_factory=list)

    def at(self, x: int, y: int) -> float:
        if 0 <= y < len(self.moisture) and 0 <= x < len(self.moisture[y]):
            return self.moisture[y][x]
        return MOISTURE_DEFAULT

    def groundwater_at(self, x: int, y: int) -> float:
        if 0 <= y < len(self.groundwater) and 0 <= x < len(self.groundwater[y]):
            return self.groundwater[y][x]
        return GROUNDWATER_DEFAULT

    def snowpack_at(self, x: int, y: int) -> float:
        if 0 <= y < len(self.snowpack) and 0 <= x < len(self.snowpack[y]):
            return self.snowpack[y][x]
        return SNOWPACK_DEFAULT

    def average(self) -> float:
        flat = [v for row in self.moisture for v in row]
        return sum(flat) / len(flat) if flat else MOISTURE_DEFAULT

    def average_groundwater(self) -> float:
        flat = [v for row in self.groundwater for v in row]
        return sum(flat) / len(flat) if flat else GROUNDWATER_DEFAULT

    def average_snowpack(self) -> float:
        flat = [v for row in self.snowpack for v in row]
        return sum(flat) / len(flat) if flat else SNOWPACK_DEFAULT

    def to_dict(self) -> dict:
        return {
            "moisture": [list(row) for row in self.moisture],
            "groundwater": [list(row) for row in self.groundwater],
            "snowpack": [list(row) for row in self.snowpack],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HydrologyField":
        moisture = [list(row) for row in data.get("moisture", [])]
        groundwater = [list(row) for row in data.get("groundwater", [])]
        if not groundwater and moisture:
            # Legacy pre-groundwater snapshot: backfill at the default,
            # same "derived state gets rebuilt on load" treatment
            # `create_hydrology_field` already gives a brand-new world.
            groundwater = [[GROUNDWATER_DEFAULT] * len(row) for row in moisture]
        snowpack = [list(row) for row in data.get("snowpack", [])]
        if not snowpack and moisture:
            # Legacy pre-snowpack snapshot: backfill at zero, same
            # "derived state gets rebuilt on load" treatment above —
            # SNOWPACK_DEFAULT is 0, not a neutral midpoint, so this is
            # the same value a brand-new world would start with anyway.
            snowpack = [[SNOWPACK_DEFAULT] * len(row) for row in moisture]
        return cls(moisture=moisture, groundwater=groundwater, snowpack=snowpack)


def create_hydrology_field(terrain: list[list[Tile]]) -> HydrologyField:
    """Seeds the field at world-creation time (or silently backfilled
    on loading a pre-A11 snapshot, same "derived state gets rebuilt on
    load" treatment as `_biome_counts_cache`) — water tiles start
    saturated, everything else at `MOISTURE_DEFAULT`/`GROUNDWATER_
    DEFAULT`."""
    moisture = [
        [MOISTURE_MAX if tile.biome in _WATER_BIOMES else MOISTURE_DEFAULT for tile in row]
        for row in terrain
    ]
    groundwater = [[GROUNDWATER_DEFAULT for _ in row] for row in terrain]
    snowpack = [[SNOWPACK_DEFAULT for _ in row] for row in terrain]
    return HydrologyField(moisture=moisture, groundwater=groundwater, snowpack=snowpack)


def tick_hydrology(
    field: HydrologyField, terrain: list[list[Tile]], precipitation: float, season: str, rng: random.Random,
) -> None:
    """One weekly step: precipitation gain -> single-pass downhill
    redistribution -> evaporation. Mutates `field.moisture` in place.
    `rng` is accepted for interface symmetry with every other tick_*
    function in this domain (deliberately unused today — the
    algorithm is fully deterministic; a future erosion/groundwater
    extension may need real randomness for e.g. spring placement)."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return

    grid = field.moisture
    # Pass 1: precipitation gain + evaporation, land tiles only.
    evaporation = MOISTURE_EVAPORATION_BASE + (MOISTURE_EVAPORATION_HEAT_BONUS if season == "summer" else 0.0)
    for y in range(height):
        for x in range(width):
            if terrain[y][x].biome in _WATER_BIOMES:
                grid[y][x] = MOISTURE_MAX
                continue
            value = grid[y][x] + MOISTURE_PRECIPITATION_GAIN * precipitation - evaporation
            grid[y][x] = max(MOISTURE_MIN, min(MOISTURE_MAX, value))

    # Pass 2: single-step downhill transfer, computed against a
    # snapshot of pass 1's result (not in-place) so no tile's transfer
    # this week depends on iteration order.
    before = [row[:] for row in grid]
    deltas = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if terrain[y][x].biome in _WATER_BIOMES:
                continue
            lowest_pos = None
            lowest_elevation = terrain[y][x].elevation
            for dx, dy in _ADJACENT_4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and terrain[ny][nx].elevation < lowest_elevation:
                    lowest_elevation = terrain[ny][nx].elevation
                    lowest_pos = (nx, ny)
            if lowest_pos is None:
                continue
            nx, ny = lowest_pos
            excess = before[y][x] - before[ny][nx]
            if excess <= 0:
                continue
            transfer = excess * MOISTURE_FLOW_FRACTION
            deltas[y][x] -= transfer
            deltas[ny][nx] += transfer
    for y in range(height):
        for x in range(width):
            if terrain[y][x].biome in _WATER_BIOMES:
                continue
            grid[y][x] = max(MOISTURE_MIN, min(MOISTURE_MAX, grid[y][x] + deltas[y][x]))


def tick_groundwater(field: HydrologyField, terrain: list[list[Tile]]) -> None:
    """One weekly step, called immediately after `tick_hydrology` (reads
    its already-updated `field.moisture`): infiltration on wet land ->
    seep-back (base flow) on dry land -> constant percolation loss.
    Mutates `field.groundwater` in place. Land only — water-biome tiles
    still carry a real subsurface reservoir underneath them (not pinned
    the way surface `moisture` is), so this runs over every tile."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return
    moisture = field.moisture
    ground = field.groundwater
    for y in range(height):
        for x in range(width):
            m = moisture[y][x]
            g = ground[y][x]
            if m >= GROUNDWATER_INFILTRATION_THRESHOLD:
                infiltrated = (m - GROUNDWATER_INFILTRATION_THRESHOLD) * GROUNDWATER_INFILTRATION_FRACTION
                g += infiltrated
                moisture[y][x] = max(MOISTURE_MIN, m - infiltrated)
            elif m < GROUNDWATER_SEEP_THRESHOLD and g > GROUNDWATER_MIN:
                seep = min(g, (GROUNDWATER_SEEP_THRESHOLD - m)) * GROUNDWATER_SEEP_FRACTION
                g -= seep
                moisture[y][x] = min(MOISTURE_MAX, m + seep)
            ground[y][x] = max(GROUNDWATER_MIN, min(GROUNDWATER_MAX, g - GROUNDWATER_PERCOLATION_LOSS))


def tick_snowpack(field: HydrologyField, terrain: list[list[Tile]], temperature_c: float) -> None:
    """One weekly step, called immediately after `tick_groundwater`
    (reads/writes `field.moisture` together with the new `field.
    snowpack`, same weekly cadence as every other hydrology tick). A2's
    real `ca_operators.reaction_diffuse` consumer: below `SNOWPACK_
    FREEZE_TEMP_C`, surface moisture freezes into snowpack; at or above
    it, snowpack thaws back into moisture — genuinely mass-conserving
    (whatever a tile's snowpack gains, its moisture loses that same
    tick, and vice versa), the textbook case that operator was built
    for and unlike every `FieldGrid` field (independent quantities,
    never meant to trade mass). Water-biome tiles are excluded from the
    exchange and re-pinned afterward (moisture stays `MOISTURE_MAX`,
    snowpack stays `SNOWPACK_MIN`) — open water doesn't accumulate a
    snow cover the way land does."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return
    if temperature_c <= SNOWPACK_FREEZE_TEMP_C:
        rate_a_to_b, rate_b_to_a = SNOWPACK_FREEZE_RATE, 0.0
    else:
        rate_a_to_b, rate_b_to_a = 0.0, SNOWPACK_MELT_RATE
    new_moisture, new_snowpack = reaction_diffuse(field.moisture, field.snowpack, rate_a_to_b, rate_b_to_a)
    for y in range(height):
        for x in range(width):
            if terrain[y][x].biome in _WATER_BIOMES:
                new_moisture[y][x] = MOISTURE_MAX
                new_snowpack[y][x] = SNOWPACK_MIN
    field.moisture = new_moisture
    field.snowpack = new_snowpack


def tick_erosion(
    field: HydrologyField, terrain: list[list[Tile]], rng: random.Random,
) -> list[tuple[int, int]]:
    """One weekly step, called immediately after `tick_hydrology` (reads
    its already-updated `field.moisture` to decide which tiles are
    genuinely carrying flow this week). Reuses `tick_hydrology`'s own
    steepest-descent neighbor-finding: a wet-enough land tile moves a
    small, capped, mass-conserving fraction of its elevation excess to
    its lowest orthogonal neighbor, skipping any tile whose lowest
    neighbor is pinned water/RIVER (siltation into standing water is
    out of scope, see module docstring). Mutates `terrain` in place via
    the normal `Tile`-replacement pattern every other terrain mutator
    in this codebase already uses, re-deriving biome via `classify_
    with_bias` whenever elevation crosses a real threshold. Returns the
    list of `(x, y)` positions whose BIOME changed as a result (for
    narration/UI — most weeks this is empty; erosion is gradual by
    design). `rng` is accepted for interface symmetry with the rest of
    this domain (unused today — deterministic given `field`/`terrain`,
    same as `tick_hydrology`)."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return []

    moisture = field.moisture
    deltas = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if terrain[y][x].biome in _WATER_BIOMES or moisture[y][x] < EROSION_MOISTURE_THRESHOLD:
                continue
            lowest_pos = None
            lowest_elevation = terrain[y][x].elevation
            for dx, dy in _ADJACENT_4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and terrain[ny][nx].elevation < lowest_elevation:
                    lowest_elevation = terrain[ny][nx].elevation
                    lowest_pos = (nx, ny)
            if lowest_pos is None:
                continue
            nx, ny = lowest_pos
            if terrain[ny][nx].biome in _WATER_BIOMES:
                continue
            excess = terrain[y][x].elevation - terrain[ny][nx].elevation
            if excess <= 0:
                continue
            transfer = min(excess * EROSION_RATE, EROSION_MAX_DELTA_PER_TILE_PER_WEEK)
            deltas[y][x] -= transfer
            deltas[ny][nx] += transfer

    changed: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            delta = deltas[y][x]
            if delta == 0.0:
                continue
            tile = terrain[y][x]
            new_elevation = max(0.0, min(1.0, tile.elevation + delta))
            new_biome = classify_with_bias(new_elevation)
            if new_biome in _WATER_BIOMES or tile.biome in _WATER_BIOMES or tile.biome is Biome.QUARRY:
                # Erosion never drowns a land tile into a water biome or
                # dries out water outright — that's hydrology.py's
                # river/lake carving's job, not this gradual mechanism's.
                # QUARRY is likewise sticky (M2/M8, world/terrain_
                # evolution.py's `maybe_form_quarries`) — a real
                # excavated quarry doesn't silently reclassify back to
                # HILLS just because gradual erosion nudged its
                # elevation across a classify_with_bias band.
                new_biome = tile.biome
            terrain[y][x] = Tile(x=x, y=y, elevation=new_elevation, biome=new_biome)
            if new_biome != tile.biome:
                changed.append((x, y))
    return changed
