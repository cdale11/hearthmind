"""Deterministic terrain generation.

Uses midpoint displacement (the "diamond-square" algorithm) to produce a
plausible, seed-reproducible elevation field with no external dependencies.
Diamond-square wants a grid of size (2^k + 1), so we generate at the
smallest such size that covers the requested width/height and crop the
result. This keeps the public interface (`generate_terrain`) agnostic to
that implementation detail, so it can be swapped for multi-octave noise
with real hydrology later (see docs/DECISIONS.md, M1-3) without callers
changing.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Biome(str, Enum):
    DEEP_WATER = "deep_water"
    SHALLOW_WATER = "shallow_water"
    BEACH = "beach"
    GRASSLAND = "grassland"
    FOREST = "forest"
    HILLS = "hills"
    MOUNTAIN = "mountain"
    SNOWCAP = "snowcap"


@dataclass(frozen=True)
class Tile:
    x: int
    y: int
    elevation: float  # normalized 0.0 (lowest) .. 1.0 (highest)
    biome: Biome

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "elevation": self.elevation, "biome": self.biome.value}

    @classmethod
    def from_dict(cls, data: dict) -> "Tile":
        return cls(x=data["x"], y=data["y"], elevation=data["elevation"], biome=Biome(data["biome"]))


BIOME_ORDER: tuple[Biome, ...] = (
    Biome.DEEP_WATER, Biome.SHALLOW_WATER, Biome.BEACH, Biome.GRASSLAND,
    Biome.FOREST, Biome.HILLS, Biome.MOUNTAIN, Biome.SNOWCAP,
)
"""Low-elevation to high-elevation biome ordering — used by
world/terrain_evolution.py to nudge a tile one biome-step at a time
under climate drift, rather than jumping straight to a possibly
distant target biome."""

_CLIMATE_WATER_SHIFT = 0.05
_CLIMATE_LAND_SHIFT = 0.05
_CLIMATE_COLD_SHIFT = 0.05
"""Max elevation-threshold displacement at climate bias = +-1 — modest
relative to the 0..1 elevation range split across 8 biome bands, so
even a fully-drifted climate reshapes boundaries rather than erasing
whole biomes. See docs/DECISIONS.md, terrain-evolution pass."""


def classify_with_bias(elevation: float, warming: float = 0.0, drying: float = 0.0) -> Biome:
    """Elevation -> biome, with the boundary thresholds nudged by a
    climate bias. `warming` (-1..1) raises the mountain/snowcap
    thresholds (those cold biomes need more elevation, so they shrink
    under a warming trend). `drying` (-1..1) lowers the water
    thresholds (water recedes) and raises grassland/forest's lower
    edge (forest needs more elevation, so grassland expands at its
    expense). Both default to 0.0, reproducing the original static
    thresholds exactly — see `generate_terrain`."""
    thresholds: list[tuple[float, Biome]] = [
        (0.30 - drying * _CLIMATE_WATER_SHIFT, Biome.DEEP_WATER),
        (0.38 - drying * _CLIMATE_WATER_SHIFT, Biome.SHALLOW_WATER),
        (0.42 - drying * _CLIMATE_WATER_SHIFT, Biome.BEACH),
        (0.62 + drying * _CLIMATE_LAND_SHIFT, Biome.GRASSLAND),
        (0.75 + drying * _CLIMATE_LAND_SHIFT, Biome.FOREST),
        (0.87 + warming * _CLIMATE_COLD_SHIFT, Biome.HILLS),
        (0.95 + warming * _CLIMATE_COLD_SHIFT, Biome.MOUNTAIN),
        (1.01 + warming * _CLIMATE_COLD_SHIFT, Biome.SNOWCAP),  # 1.01 so elevation == 1.0 still matches
    ]
    for threshold, biome in thresholds:
        if elevation < threshold:
            return biome
    return Biome.SNOWCAP


def _classify(elevation: float) -> Biome:
    return classify_with_bias(elevation)


def _next_diamond_square_size(minimum: int) -> int:
    """Smallest N = 2^k + 1 that is >= minimum."""
    size = 2
    while size + 1 < minimum:
        size *= 2
    return size + 1


def _diamond_square(size: int, seed: int, roughness: float = 0.55) -> list[list[float]]:
    """Classic diamond-square midpoint displacement.

    Returns an unnormalized size x size grid of floats (indexed [y][x]).
    """
    rng = random.Random(seed)
    grid = [[0.0] * size for _ in range(size)]

    # Seed the four corners.
    grid[0][0] = rng.uniform(0.0, 1.0)
    grid[0][size - 1] = rng.uniform(0.0, 1.0)
    grid[size - 1][0] = rng.uniform(0.0, 1.0)
    grid[size - 1][size - 1] = rng.uniform(0.0, 1.0)

    step = size - 1
    scale = 1.0

    while step > 1:
        half = step // 2

        # Diamond step: midpoint of each square = avg of 4 corners + jitter.
        for y in range(0, size - 1, step):
            for x in range(0, size - 1, step):
                avg = (
                    grid[y][x]
                    + grid[y][x + step]
                    + grid[y + step][x]
                    + grid[y + step][x + step]
                ) / 4.0
                grid[y + half][x + half] = avg + rng.uniform(-scale, scale)

        # Square step: midpoint of each diamond edge = avg of 4 neighbors + jitter.
        for y in range(0, size, half):
            x_start = half if (y // half) % 2 == 0 else 0
            for x in range(x_start, size, step):
                total = 0.0
                count = 0
                for dy, dx in ((-half, 0), (half, 0), (0, -half), (0, half)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < size and 0 <= nx < size:
                        total += grid[ny][nx]
                        count += 1
                grid[y][x] = total / count + rng.uniform(-scale, scale)

        step = half
        scale *= roughness

    return grid


def _normalize(grid: list[list[float]]) -> list[list[float]]:
    flat = [v for row in grid for v in row]
    lo, hi = min(flat), max(flat)
    span = (hi - lo) or 1.0
    return [[(v - lo) / span for v in row] for row in grid]


def generate_terrain(seed: int, width: int, height: int) -> list[list[Tile]]:
    """Generate a deterministic width x height grid of Tiles.

    Same (seed, width, height) always produces the same terrain.
    """
    raw_size = _next_diamond_square_size(max(width, height))
    raw = _diamond_square(raw_size, seed=seed)
    normalized = _normalize(raw)

    tiles: list[list[Tile]] = []
    for y in range(height):
        row: list[Tile] = []
        for x in range(width):
            elevation = normalized[y][x]
            row.append(Tile(x=x, y=y, elevation=elevation, biome=_classify(elevation)))
        tiles.append(row)
    return tiles


def biome_counts(tiles: list[list[Tile]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in tiles:
        for tile in row:
            counts[tile.biome.value] = counts.get(tile.biome.value, 0) + 1
    return counts
