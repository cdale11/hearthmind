"""Rivers and lakes — geographical features beyond the base elevation-
classified biome grid (terrain.py already gives mountains/hills/
snowcap for free from the elevation field; this adds the two features
that elevation classification alone can't produce).

Rivers are carved once at world creation by steepest-descent from a
handful of high-elevation sources down to existing water (or the map
edge, or a max length) — see `generate_rivers`. They're static after
that (their tiles are just `Biome.RIVER` in the terrain grid, so they
persist automatically through terrain's own (de)serialization); the
"evolves over time" ask for rivers is answered by world/disasters.py's
flood mechanic, which temporarily expands water onto riverbank land
during sustained heavy rain.

Lakes are identified once at world creation (`identify_lakes`) by
flood-filling connected water components that never touch the map
border — a heuristic for "inland water" vs. the ocean, which does touch
the border on this generator's typical output. Each lake then gets its
own slowly-changing `level` (a bounded random walk biased by the
map-wide climate drying trend, same shape as ClimateState), nudged
monthly by `tick_lakes`, whose shoreline visibly grows or shrinks by one
ring of tiles when the level crosses a threshold — this is the "evolves
over time" answer for lakes specifically.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from hearthmind.util import clamp
from hearthmind.world.terrain import Biome, Tile, classify_with_bias
from hearthmind.world.terrain_evolution import _is_developed, apply_dry_lakebed_scar

try:
    from hearthmind._native import bounded_random_walk_step as _native_bounded_random_walk_step
except ImportError:
    _native_bounded_random_walk_step = None
"""Optional compiled fast path for the lake-level bounded-random-walk
step (module 12, see cpp/src/bounded_random_walk.cpp, docs/DECISIONS.md
"Native extension port"). Shared with world/terrain_evolution.py's
tick_climate and settlement/buildings.py's tick_temperament/tick_
player_standing/tick_relation. The RNG draw stays in Python."""

RIVER_SOURCE_TILES_PER_1000 = 1.2
"""How many river sources to carve per 1000 map tiles — scales river
count with map size instead of a fixed count."""

RIVER_MAX_LENGTH = 60
"""Steepest-descent walk gives up after this many steps even if it never
reaches water (e.g. a landlocked depression) — avoids a runaway walk
across a very flat map."""

_WATER_BIOMES = frozenset({Biome.DEEP_WATER, Biome.SHALLOW_WATER})
_RIVER_SOURCE_BIOMES = frozenset({Biome.MOUNTAIN, Biome.SNOWCAP, Biome.HILLS})
_RIVER_CARVABLE_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST, Biome.HILLS, Biome.BEACH})
"""Biomes a river is allowed to carve through — never re-carves
mountain/snowcap (too high to be a riverbed) or tiles that are already
water."""

_ADJACENT_8 = ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))
_ADJACENT_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))


def _hydro_rng(seed: int, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def river_sources_used(seed: int, terrain: list[list[Tile]]) -> list[tuple[int, int]]:
    """The exact source positions `generate_rivers` carves from, given
    the same `(seed, terrain)` — a pure, deterministic function of the
    map's genesis-time biome layout. Called once at world creation and
    the result persisted (`World.river_sources`), because A3's re-
    carving mechanism (`recarve_rivers`, below) needs to re-walk from
    the SAME starting points every time, regardless of what elevation/
    biome at those exact positions has since become under erosion — a
    source tile that erodes from MOUNTAIN into HILLS is still where the
    river originates, it just may carve a different course from there
    now."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return []
    rng = _hydro_rng(seed, "rivers")
    sources = [(t.x, t.y) for row in terrain for t in row if t.biome in _RIVER_SOURCE_BIOMES]
    rng.shuffle(sources)
    num_rivers = max(1, int(width * height * RIVER_SOURCE_TILES_PER_1000 / 1000))
    return sources[:num_rivers]


def generate_rivers(seed: int, terrain: list[list[Tile]]) -> set[tuple[int, int]]:
    """Carves rivers by steepest-descent from randomly chosen high-
    elevation sources. Mutates `terrain` in place, replacing carved
    tiles' biome with Biome.RIVER. Returns the set of carved positions.

    A3 (docs/ROADMAP-2026-07-REMAINING.md, "rivers re-carving their
    course"): the actual SOURCE positions chosen this call are also
    recoverable via `river_sources_used`, called with the same
    `(seed, terrain)` right after this — see that function's docstring
    for why sources need to be captured once, at genesis, rather than
    re-derived later from a terrain that erosion has since reshaped."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return set()

    sources = river_sources_used(seed, terrain)
    river_tiles: set[tuple[int, int]] = set()

    for x, y in sources:
        pos = (x, y)
        visited: set[tuple[int, int]] = set()
        for _ in range(RIVER_MAX_LENGTH):
            visited.add(pos)
            px, py = pos
            tile = terrain[py][px]
            if tile.biome in _WATER_BIOMES:
                break
            if tile.biome in _RIVER_CARVABLE_BIOMES and pos not in river_tiles:
                terrain[py][px] = Tile(x=px, y=py, elevation=tile.elevation, biome=Biome.RIVER)
                river_tiles.add(pos)
            candidates = [
                (terrain[py + dy][px + dx].elevation, px + dx, py + dy)
                for dx, dy in _ADJACENT_8
                if 0 <= px + dx < width and 0 <= py + dy < height and (px + dx, py + dy) not in visited
            ]
            if not candidates:
                break
            candidates.sort(key=lambda c: c[0])
            lowest_elevation, nx, ny = candidates[0]
            if lowest_elevation > tile.elevation:
                break  # nowhere lower to go — local basin, stop carving
            pos = (nx, ny)
    return river_tiles


def recarve_rivers(
    sources: list[tuple[int, int]], terrain: list[list[Tile]], river_tiles_before: set[tuple[int, int]],
    settlements, farms, excluded: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """A3 "rivers re-carving their course" (docs/ROADMAP-2026-07-
    REMAINING.md): re-walks each of the world's genesis-time river
    sources by the exact same steepest-descent rule `generate_rivers`
    used, but against CURRENT elevation — `world/hydrology_field.py`'s
    `tick_erosion` genuinely reshapes the land over time now, so a
    river's actual course should genuinely reshape with it, the same
    way real rivers migrate as sediment builds up and banks erode.

    A tile that was river before but the new walk no longer visits
    reverts to whatever biome its CURRENT elevation actually classifies
    as (`classify_with_bias`) — a river that has genuinely moved on
    leaves dry former riverbed behind, not lingering phantom water. A
    newly-visited tile becomes `Biome.RIVER`. Never touches a developed
    tile (standing building, vehicle, or farm) in EITHER direction —
    same `_is_developed` discipline `apply_climate_drift` already
    applies, and the reason a developed tile that would otherwise
    revert instead just stays classified as river: a farm or building
    can't spontaneously be un-founded because the river moved away
    from under it (no mechanic exists for that), so it keeps whatever
    it already is rather than the map silently disagreeing with itself.

    Deliberately does NOT call `_hydro_rng`/re-derive `sources` itself
    — `sources` must be `World.river_sources`, captured once at genesis
    via `river_sources_used`, so re-carving always starts from the same
    origin points regardless of how much erosion has since changed
    the biome AT those exact positions."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return set(river_tiles_before)

    new_river_tiles: set[tuple[int, int]] = set()
    for x, y in sources:
        if not (0 <= x < width and 0 <= y < height):
            continue
        pos = (x, y)
        visited: set[tuple[int, int]] = set()
        for _ in range(RIVER_MAX_LENGTH):
            visited.add(pos)
            px, py = pos
            tile = terrain[py][px]
            if tile.biome in _WATER_BIOMES:
                break
            already_carvable = tile.biome in _RIVER_CARVABLE_BIOMES or tile.biome is Biome.RIVER
            if already_carvable and pos not in new_river_tiles and not _is_developed(px, py, settlements, farms, excluded):
                new_river_tiles.add(pos)
            candidates = [
                (terrain[py + dy][px + dx].elevation, px + dx, py + dy)
                for dx, dy in _ADJACENT_8
                if 0 <= px + dx < width and 0 <= py + dy < height and (px + dx, py + dy) not in visited
            ]
            if not candidates:
                break
            candidates.sort(key=lambda c: c[0])
            lowest_elevation, nx, ny = candidates[0]
            if lowest_elevation > tile.elevation:
                break  # nowhere lower to go — local basin, stop carving
            pos = (nx, ny)

    for px, py in new_river_tiles - river_tiles_before:
        tile = terrain[py][px]
        terrain[py][px] = Tile(x=px, y=py, elevation=tile.elevation, biome=Biome.RIVER)
    for px, py in river_tiles_before - new_river_tiles:
        if _is_developed(px, py, settlements, farms, excluded):
            new_river_tiles.add((px, py))
            continue
        tile = terrain[py][px]
        terrain[py][px] = Tile(x=px, y=py, elevation=tile.elevation, biome=classify_with_bias(tile.elevation))
    return new_river_tiles


WETLAND_FORM_MOISTURE_THRESHOLD = 0.75
WETLAND_FORM_GROUNDWATER_THRESHOLD = 0.7
"""M4 "The Living Map" (docs/VISION-2026-07-24-LIVINGMAP.md, docs/
ROADMAP-2026-07-REMAINING.md's Tier 1.5): "wetlands expand/shrink with
hydrology" — the real gap this closes is that moisture/groundwater
drove FarmGrid yield but never a distinct biome. A GRASSLAND tile
needs BOTH surface moisture and groundwater sustained above these
(near-saturated) levels — a genuinely soggy tile, not just a rainy
week — before it's even a candidate."""

WETLAND_FORM_MONTHS_REQUIRED = 6
"""How many CONSECUTIVE qualifying months (see `wetland_progress`)
before a candidate tile actually converts — half a year of sustained
saturation, so a wetland reads as a real slow landscape change, not a
biome that flickers with the weather."""

WETLAND_DRY_MOISTURE_THRESHOLD = 0.4
"""An existing WETLAND tile reverts once surface moisture drops below
this — deliberately far below `WETLAND_FORM_MOISTURE_THRESHOLD`
(hysteresis) so a wetland doesn't form and dry out again within the
same season's normal moisture swings."""


def tick_wetlands(
    terrain: list[list[Tile]], moisture: list[list[float]], groundwater: list[list[float]],
    wetland_progress: dict[tuple[int, int], int], settlements, farms, excluded: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Monthly (`World._tick_terrain`'s `month_end` block, alongside
    climate drift/river re-carving). Two independent passes:

    Formation: every GRASSLAND tile whose current `moisture`/
    `groundwater` both clear the FORM thresholds this month has its
    `wetland_progress` counter bumped; any tile that doesn't qualify
    has its counter reset to 0 (removed from the dict — same "absence
    means zero" convention as `fallow_ticks`) rather than merely
    paused, so a genuine wetland needs SUSTAINED wet conditions, not
    just `WETLAND_FORM_MONTHS_REQUIRED` wet months spread across a
    drought-interrupted decade. A tile that reaches the requirement
    converts to `Biome.WETLAND` and drops out of the progress dict —
    once formed, wetness is tracked implicitly by staying WETLAND.

    Reversion: every WETLAND tile whose moisture has fallen below the
    (lower, hysteresis) DRY threshold reverts to GRASSLAND.

    Never touches a developed tile (standing building, vehicle, or
    farm) in either direction — same `_is_developed` discipline
    `recarve_rivers`/`apply_climate_drift` already apply; `WETLAND` is
    in neither `FARMABLE_BIOMES` nor `WALKABLE_BIOMES` (see agents/
    population.py, economy/farms.py), so a formed wetland is a real,
    immediate constraint on farm siting and routine agent movement
    through existing biome-gated systems — no bespoke consumer needed.
    Returns the list of positions whose biome changed this call, for
    the caller's own event/cache-invalidation bookkeeping."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return []

    changed: list[tuple[int, int]] = []

    for y in range(height):
        for x in range(width):
            tile = terrain[y][x]
            if tile.biome is not Biome.GRASSLAND:
                continue
            pos = (x, y)
            if _is_developed(x, y, settlements, farms, excluded):
                continue
            qualifies = (
                moisture[y][x] >= WETLAND_FORM_MOISTURE_THRESHOLD
                and groundwater[y][x] >= WETLAND_FORM_GROUNDWATER_THRESHOLD
            )
            if not qualifies:
                wetland_progress.pop(pos, None)
                continue
            progress = wetland_progress.get(pos, 0) + 1
            if progress >= WETLAND_FORM_MONTHS_REQUIRED:
                terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.WETLAND)
                wetland_progress.pop(pos, None)
                changed.append(pos)
            else:
                wetland_progress[pos] = progress

    for y in range(height):
        for x in range(width):
            tile = terrain[y][x]
            if tile.biome is not Biome.WETLAND:
                continue
            if moisture[y][x] >= WETLAND_DRY_MOISTURE_THRESHOLD:
                continue
            pos = (x, y)
            if _is_developed(x, y, settlements, farms, excluded):
                continue
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
            changed.append(pos)

    return changed


@dataclass
class LakeState:
    id: int
    tiles: set[tuple[int, int]] = field(default_factory=set)
    level: float = 0.0
    """-1 (receding) .. 1 (rising) — a bounded random walk nudged
    monthly, biased toward the map-wide climate drying trend. Crossing
    LAKE_GROW_THRESHOLD/LAKE_SHRINK_THRESHOLD converts one boundary tile,
    so the shoreline visibly moves over years — the lake equivalent of
    terrain_evolution.py's climate drift."""

    def to_dict(self) -> dict:
        return {"id": self.id, "tiles": [[x, y] for x, y in sorted(self.tiles)], "level": round(self.level, 4)}

    @classmethod
    def from_dict(cls, data: dict) -> "LakeState":
        return cls(
            id=data["id"],
            tiles={(x, y) for x, y in data.get("tiles", [])},
            level=data.get("level", 0.0),
        )


LAKE_STEP_MAX = 0.06
LAKE_MEAN_REVERSION = 0.95
LAKE_DRYING_WEIGHT = 0.4
"""Same bounded-random-walk shape as ClimateState.warming/drying, but
per-lake and biased toward the map-wide drying trend rather than fully
independent — a lake's level broadly tracks a drying/wetting climate,
with its own noise on top."""

LAKE_GROW_THRESHOLD = 0.5
LAKE_SHRINK_THRESHOLD = -0.5
LAKE_MIN_TILES = 3
"""A lake never shrinks below this many tiles — a long dry spell nudges
it, but doesn't erase it outright, which would leave nothing for the
level to describe going forward."""


def identify_lakes(terrain: list[list[Tile]]) -> list[LakeState]:
    """Flood-fills connected DEEP_WATER/SHALLOW_WATER components; a
    component that never touches the map border is classified as an
    inland lake (as opposed to ocean, which does touch the border on
    this generator's typical output). Heuristic, not guaranteed correct
    on every possible map, but matches how the diamond-square generator
    actually places water in practice."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    seen: set[tuple[int, int]] = set()
    lakes: list[LakeState] = []
    next_id = 0
    for row in terrain:
        for tile in row:
            pos = (tile.x, tile.y)
            if pos in seen or tile.biome not in _WATER_BIOMES:
                continue
            component: set[tuple[int, int]] = set()
            touches_border = False
            stack = [pos]
            seen.add(pos)
            while stack:
                cx, cy = stack.pop()
                component.add((cx, cy))
                if cx == 0 or cy == 0 or cx == width - 1 or cy == height - 1:
                    touches_border = True
                for dx, dy in _ADJACENT_4:
                    nx, ny = cx + dx, cy + dy
                    if (
                        0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                        and terrain[ny][nx].biome in _WATER_BIOMES
                    ):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if not touches_border:
                lakes.append(LakeState(id=next_id, tiles=component))
                next_id += 1
    return lakes


def tick_lakes(
    lakes: list[LakeState], terrain: list[list[Tile]], drying: float,
    rng: random.Random, excluded: set[tuple[int, int]],
    dry_lakebed_scars: dict[tuple[int, int], float] | None = None,
) -> list[tuple[str, str]]:
    """Called once per month. Nudges each lake's level, and grows/shrinks
    its shoreline by one ring tile if the level crossed a threshold.
    Mutates `terrain`/`lakes` in place. `dry_lakebed_scars` (M1/M9,
    optional — `None` reproduces the exact pre-M1/M9 behavior for any
    caller without one in scope, same "additive, zero-risk-to-existing-
    callers" precedent `WildlifeGrid.tick`'s own `migration_trails`
    param set) marks a vacated shoreline tile so its history survives
    even after the water returns and the biome flips back to land."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    events: list[tuple[str, str]] = []
    for lake in lakes:
        level_jitter = rng.uniform(-LAKE_STEP_MAX, LAKE_STEP_MAX)
        extra = -drying * LAKE_DRYING_WEIGHT * LAKE_STEP_MAX
        if _native_bounded_random_walk_step is not None:
            lake.level = _native_bounded_random_walk_step(
                lake.level, LAKE_MEAN_REVERSION, level_jitter, extra, -1.0, 1.0,
            )
        else:
            lake.level = clamp((
                lake.level * LAKE_MEAN_REVERSION + level_jitter + extra
            ), -1.0, 1.0)
        if lake.level >= LAKE_GROW_THRESHOLD:
            neighbors: set[tuple[int, int]] = set()
            for (x, y) in lake.tiles:
                for dx, dy in _ADJACENT_4:
                    nx, ny = x + dx, y + dy
                    pos = (nx, ny)
                    if (
                        0 <= nx < width and 0 <= ny < height and pos not in lake.tiles
                        and pos not in excluded and terrain[ny][nx].biome in (Biome.BEACH, Biome.GRASSLAND)
                    ):
                        neighbors.add(pos)
            if neighbors:
                nx, ny = min(neighbors, key=lambda p: terrain[p[1]][p[0]].elevation)
                tile = terrain[ny][nx]
                terrain[ny][nx] = Tile(x=nx, y=ny, elevation=tile.elevation, biome=Biome.SHALLOW_WATER)
                lake.tiles.add((nx, ny))
                events.append(("lake_rose", f"Rising water swallowed the shore near ({nx}, {ny})."))
        elif lake.level <= LAKE_SHRINK_THRESHOLD and len(lake.tiles) > LAKE_MIN_TILES:
            shallow = [p for p in lake.tiles if terrain[p[1]][p[0]].biome is Biome.SHALLOW_WATER]
            candidates = [p for p in shallow if p not in excluded] or shallow
            if candidates:
                x, y = max(candidates, key=lambda p: terrain[p[1]][p[0]].elevation)
                tile = terrain[y][x]
                terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.BEACH)
                lake.tiles.discard((x, y))
                if dry_lakebed_scars is not None:
                    apply_dry_lakebed_scar((x, y), dry_lakebed_scars)
                events.append(("lake_receded", f"The lake receded, leaving bare ground at ({x}, {y})."))
    return events
