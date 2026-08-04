#!/usr/bin/env python3
"""C++ porting backlog (docs/ROADMAP-2026-07-REMAINING.md's parallel
track): randomized equivalence test for `cpp/src/terrain_neighbor_
count.cpp`'s `forest_neighbor_counts` against a plain-Python
reimplementation of `world/terrain_evolution.py`'s `_tick_fallow`
forest-neighbor loop.

Same standalone-script convention as every sibling `verify_*_native.py`
(no unittest): a reference reimplementation, a randomized-trial
equivalence sweep, plus deliberate edge cases (empty grid, single
tile, all-forest, no-forest, non-square grid).
"""
from __future__ import annotations

import random
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind._native import forest_neighbor_counts as native_counts

FAILURES: list[str] = []

_ADJACENT_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def ref_forest_neighbor_counts(is_forest):
    height = len(is_forest)
    width = len(is_forest[0]) if height else 0
    result = [[0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            count = 0
            for dx, dy in _ADJACENT_4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and is_forest[ny][nx]:
                    count += 1
            result[y][x] = count
    return result


def random_bool_grid(rng, height, width, p_forest=0.5):
    return [[rng.random() < p_forest for _ in range(width)] for _ in range(height)]


def main() -> int:
    rng = random.Random(20260804)

    mismatches = 0
    for _ in range(2000):
        height = rng.randint(1, 10)
        width = rng.randint(1, 10)
        grid = random_bool_grid(rng, height, width, rng.uniform(0.1, 0.9))
        if ref_forest_neighbor_counts(grid) != native_counts(grid):
            mismatches += 1
    check(f"forest_neighbor_counts: 2000 randomized trials, {mismatches} mismatches", mismatches == 0)

    check("empty grid returns empty", native_counts([]) == [])
    check("single tile (no neighbors) counts 0", native_counts([[True]]) == [[0]])
    check("single tile, not forest, still counts 0", native_counts([[False]]) == [[0]])

    all_forest = [[True] * 5 for _ in range(5)]
    check(
        "an all-forest 5x5 grid matches the reference exactly (corners=2, edges=3, interior=4)",
        native_counts(all_forest) == ref_forest_neighbor_counts(all_forest),
    )

    no_forest = [[False] * 4 for _ in range(4)]
    check("an all-non-forest grid counts 0 everywhere", native_counts(no_forest) == [[0] * 4 for _ in range(4)])

    non_square = [[True, False, True, True]]
    check(
        "non-square (1x4) grid matches the reference",
        native_counts(non_square) == ref_forest_neighbor_counts(non_square),
    )

    tall = [[True], [False], [True]]
    check(
        "non-square (3x1) grid matches the reference",
        native_counts(tall) == ref_forest_neighbor_counts(tall),
    )

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
