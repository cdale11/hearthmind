"""Shared test-only terrain builder. Not a test module itself (no test_
prefix, so `unittest discover` skips it).
"""
from __future__ import annotations

from hearthmind.world.terrain import Biome, Tile


def open_terrain(width: int = 16, height: int = 16, biome: Biome = Biome.GRASSLAND) -> list[list[Tile]]:
    """An obstacle-free terrain of a single biome, so movement/placement
    tests aren't at the mercy of a randomly generated map having (or not
    having) a clear path or the right biome mix between two points."""
    return [[Tile(x=x, y=y, elevation=0.5, biome=biome) for x in range(width)] for y in range(height)]
