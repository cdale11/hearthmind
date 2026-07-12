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

from hearthmind.world.terrain import Biome, Tile

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


def generate_rivers(seed: int, terrain: list[list[Tile]]) -> set[tuple[int, int]]:
    """Carves rivers by steepest-descent from randomly chosen high-
    elevation sources. Mutates `terrain` in place, replacing carved
    tiles' biome with Biome.RIVER. Returns the set of carved positions."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return set()

    rng = _hydro_rng(seed, "rivers")
    sources = [(t.x, t.y) for row in terrain for t in row if t.biome in _RIVER_SOURCE_BIOMES]
    rng.shuffle(sources)
    num_rivers = max(1, int(width * height * RIVER_SOURCE_TILES_PER_1000 / 1000))
    river_tiles: set[tuple[int, int]] = set()

    for x, y in sources[:num_rivers]:
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
) -> list[tuple[str, str]]:
    """Called once per month. Nudges each lake's level, and grows/shrinks
    its shoreline by one ring tile if the level crossed a threshold.
    Mutates `terrain`/`lakes` in place."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    events: list[tuple[str, str]] = []
    for lake in lakes:
        lake.level = max(-1.0, min(1.0, (
            lake.level * LAKE_MEAN_REVERSION + rng.uniform(-LAKE_STEP_MAX, LAKE_STEP_MAX)
            - drying * LAKE_DRYING_WEIGHT * LAKE_STEP_MAX
        )))
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
                events.append(("lake_receded", f"The lake receded, leaving bare ground at ({x}, {y})."))
    return events
