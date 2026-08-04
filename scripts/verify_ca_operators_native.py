#!/usr/bin/env python3
"""C++ porting backlog (docs/ROADMAP-2026-07-REMAINING.md's parallel
track): randomized equivalence test for `cpp/src/ca_operators.cpp`'s
`ca_diffuse`/`ca_reaction_diffuse` against the pure-Python reference
implementations in `hearthmind/world/ca_operators.py`.

Same standalone-script convention as every sibling `verify_*_native.py`
(no unittest): a plain reimplementation of each function's pre-native
body, a randomized-trial equivalence sweep, plus deliberate edge cases
(empty grid, zero/negative rate, single tile, non-square grid).
"""
from __future__ import annotations

import random
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind._native import ca_diffuse as native_diffuse
from hearthmind._native import ca_reaction_diffuse as native_reaction_diffuse

FAILURES: list[str] = []

_ADJACENT_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def ref_diffuse(grid, rate):
    height = len(grid)
    width = len(grid[0]) if height else 0
    if width == 0 or height == 0 or rate <= 0.0:
        return [row[:] for row in grid]
    result = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            total = 0.0
            count = 0
            for dx, dy in _ADJACENT_4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    total += grid[ny][nx]
                    count += 1
            neighbor_avg = total / count if count else grid[y][x]
            result[y][x] = grid[y][x] + rate * (neighbor_avg - grid[y][x])
    return result


def ref_reaction_diffuse(a, b, rate_a_to_b, rate_b_to_a):
    height = len(a)
    width = len(a[0]) if height else 0
    new_a = [[0.0] * width for _ in range(height)]
    new_b = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            av, bv = a[y][x], b[y][x]
            transferred_to_b = av * rate_a_to_b
            transferred_to_a = bv * rate_b_to_a
            new_a[y][x] = max(0.0, av - transferred_to_b + transferred_to_a)
            new_b[y][x] = max(0.0, bv - transferred_to_a + transferred_to_b)
    return new_a, new_b


def random_grid(rng, height, width, lo=0.0, hi=1.0):
    return [[rng.uniform(lo, hi) for _ in range(width)] for _ in range(height)]


def grids_close(a, b, tol=1e-9) -> bool:
    if len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if len(ra) != len(rb):
            return False
        for va, vb in zip(ra, rb):
            if abs(va - vb) > tol:
                return False
    return True


def main() -> int:
    rng = random.Random(20260804)

    # --- randomized equivalence, diffuse -------------------------------
    mismatches = 0
    for _ in range(2000):
        height = rng.randint(1, 8)
        width = rng.randint(1, 8)
        grid = random_grid(rng, height, width, -5.0, 5.0)
        rate = rng.uniform(-0.5, 1.5)
        if ref_diffuse(grid, rate) != native_diffuse(grid, rate):
            if not grids_close(ref_diffuse(grid, rate), native_diffuse(grid, rate)):
                mismatches += 1
    check(f"ca_diffuse: 2000 randomized trials, {mismatches} mismatches", mismatches == 0)

    # --- randomized equivalence, reaction_diffuse -----------------------
    mismatches = 0
    for _ in range(2000):
        height = rng.randint(1, 8)
        width = rng.randint(1, 8)
        a = random_grid(rng, height, width, 0.0, 3.0)
        b = random_grid(rng, height, width, 0.0, 3.0)
        rate_a_to_b = rng.uniform(-0.3, 0.8)
        rate_b_to_a = rng.uniform(-0.3, 0.8)
        ref_na, ref_nb = ref_reaction_diffuse(a, b, rate_a_to_b, rate_b_to_a)
        nat_na, nat_nb = native_reaction_diffuse(a, b, rate_a_to_b, rate_b_to_a)
        if not (grids_close(ref_na, nat_na) and grids_close(ref_nb, nat_nb)):
            mismatches += 1
    check(f"ca_reaction_diffuse: 2000 randomized trials, {mismatches} mismatches", mismatches == 0)

    # --- edge cases ------------------------------------------------------
    check("diffuse: empty grid returns empty", native_diffuse([], 0.5) == [])
    check(
        "diffuse: zero rate returns an unchanged copy",
        native_diffuse([[1.0, 2.0], [3.0, 4.0]], 0.0) == [[1.0, 2.0], [3.0, 4.0]],
    )
    check(
        "diffuse: negative rate returns an unchanged copy (matches Python's rate<=0.0 early-out)",
        native_diffuse([[1.0, 2.0], [3.0, 4.0]], -0.1) == [[1.0, 2.0], [3.0, 4.0]],
    )
    check(
        "diffuse: single tile stays itself (no in-bounds neighbors, neighbor_avg falls back to own value)",
        native_diffuse([[7.5]], 1.0) == [[7.5]],
    )
    non_square = [[1.0, 2.0, 3.0]]
    check(
        "diffuse: non-square (1x3) grid matches reference",
        grids_close(ref_diffuse(non_square, 0.5), native_diffuse(non_square, 0.5)),
    )
    check(
        "reaction_diffuse: mass-conserving transfer floored at 0.0 on both sides",
        native_reaction_diffuse([[0.0]], [[0.0]], 0.5, 0.5) == ([[0.0]], [[0.0]]),
    )
    a1 = [[1.0]]
    b1 = [[0.0]]
    na, nb = native_reaction_diffuse(a1, b1, 1.0, 0.0)
    check(
        "reaction_diffuse: full transfer a->b at rate_a_to_b=1.0 conserves total mass",
        grids_close(na, [[0.0]]) and grids_close(nb, [[1.0]]),
    )

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
