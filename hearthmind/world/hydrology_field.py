"""A11 "Continuous hydrology" (docs/MASTERCHECKLIST-2026-07-22.md,
Stage IV step 15 — the roadmap's own "highest-leverage single item:
touches agriculture, siting, disasters, ecology at once"). This module
is a deliberately scoped FIRST SLICE, not the full spec.

The existing `world/hydrology.py` only answers "is this tile a river
or a lake" — a one-time-carved, mostly-static classification. What A11
actually asks for is water as a CONTINUOUS field every tile carries,
with real flow and feedback. This ships:

  precipitation -> single-pass downhill redistribution -> evaporation

as a real per-tile `moisture` field (`HydrologyField`), consumed by a
real mechanic (farm planting yield, see `economy/farms.py`'s new
`moisture` param on `plant()`). Two of A11's four named pieces are
explicitly NOT attempted this pass, flagged rather than silently
dropped:

  - **Groundwater**: no subsurface reservoir/aquifer layer — moisture
    is a single surface quantity. A real second (slow-draining,
    slow-recharging) layer feeding springs/wells is legitimate future
    work once this surface layer's shape is validated live.
  - **Erosion feeding back into now-mutable elevation**: `Tile.
    elevation` stays immutable this pass. Real erosion (moisture/flow
    magnitude gradually reshaping the terrain that then reshapes flow
    right back) is the single biggest remaining piece of A11 and
    deliberately deferred rather than rushed — it touches `TerrainGrid`
    (already native-ported) and would need its own careful native-vs-
    fallback equivalence pass.

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
meantime — see `SimulationEngine._maybe_tick_hydrology`. Port to C++
once the shape is confirmed live, following `cpp/src/soil_fertility.
cpp`'s precedent exactly (same "prove Python correctness first, then
mirror the exact math into C++" discipline already used elsewhere in
this codebase for a from-scratch mechanism)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.world.terrain import Biome, Tile

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


@dataclass
class HydrologyField:
    """A single per-tile surface-moisture value for every tile on the
    map. Water-biome tiles are always pinned to `MOISTURE_MAX` (they
    ARE the water, not land holding moisture) — everything else is a
    real, continuously-updated quantity."""

    moisture: list[list[float]] = field(default_factory=list)

    def at(self, x: int, y: int) -> float:
        if 0 <= y < len(self.moisture) and 0 <= x < len(self.moisture[y]):
            return self.moisture[y][x]
        return MOISTURE_DEFAULT

    def average(self) -> float:
        flat = [v for row in self.moisture for v in row]
        return sum(flat) / len(flat) if flat else MOISTURE_DEFAULT

    def to_dict(self) -> dict:
        return {"moisture": [list(row) for row in self.moisture]}

    @classmethod
    def from_dict(cls, data: dict) -> "HydrologyField":
        return cls(moisture=[list(row) for row in data.get("moisture", [])])


def create_hydrology_field(terrain: list[list[Tile]]) -> HydrologyField:
    """Seeds the field at world-creation time (or silently backfilled
    on loading a pre-A11 snapshot, same "derived state gets rebuilt on
    load" treatment as `_biome_counts_cache`) — water tiles start
    saturated, everything else at `MOISTURE_DEFAULT`."""
    moisture = [
        [MOISTURE_MAX if tile.biome in _WATER_BIOMES else MOISTURE_DEFAULT for tile in row]
        for row in terrain
    ]
    return HydrologyField(moisture=moisture)


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
