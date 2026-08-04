#!/usr/bin/env python3
"""C++ porting backlog (docs/ROADMAP-2026-07-REMAINING.md's parallel
track): randomized native-vs-Python-fallback equivalence test for
`cpp/src/hydrology_tick.cpp`'s `hydrology_moisture_tick`/`hydrology_
groundwater_tick` -- the full-grid scalar passes behind `world/
hydrology_field.py`'s `tick_hydrology`/`tick_groundwater`, ported per
that module's own docstring's explicit invitation ("port to C++ once
the shape is confirmed live, following soil_fertility.cpp's
precedent"). Standalone script, no unittest, same convention as every
sibling `verify_*.py` -- and the same randomized-equivalence technique
this project's own history already used for every prior numeric port
(50,000-trial-class checks against a plain-Python reference
reimplementation) before committing to `scripts/verify_native_soak.py`
for the full-state soak.
"""
from __future__ import annotations

import random
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind._native import hydrology_groundwater_tick, hydrology_moisture_tick

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


MOISTURE_PRECIPITATION_GAIN = 0.30
MOISTURE_FLOW_FRACTION = 0.20
MOISTURE_MIN = 0.0
MOISTURE_MAX = 1.0
_ADJACENT_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))

GROUNDWATER_MIN = 0.0
GROUNDWATER_MAX = 1.0
GROUNDWATER_INFILTRATION_THRESHOLD = 0.6
GROUNDWATER_INFILTRATION_FRACTION = 0.08
GROUNDWATER_SEEP_THRESHOLD = 0.3
GROUNDWATER_SEEP_FRACTION = 0.05
GROUNDWATER_PERCOLATION_LOSS = 0.01


def reference_moisture_tick(moisture, elevation, is_water, precipitation, evaporation):
    """Direct reimplementation of tick_hydrology's pre-native Python
    body -- the exact algorithm the native function must match."""
    height = len(moisture)
    width = len(moisture[0]) if height else 0
    grid = [row[:] for row in moisture]
    for y in range(height):
        for x in range(width):
            if is_water[y][x]:
                grid[y][x] = MOISTURE_MAX
                continue
            value = grid[y][x] + MOISTURE_PRECIPITATION_GAIN * precipitation - evaporation
            grid[y][x] = max(MOISTURE_MIN, min(MOISTURE_MAX, value))
    before = [row[:] for row in grid]
    deltas = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if is_water[y][x]:
                continue
            lowest_pos = None
            lowest_elevation = elevation[y][x]
            for dx, dy in _ADJACENT_4:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and elevation[ny][nx] < lowest_elevation:
                    lowest_elevation = elevation[ny][nx]
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
            if is_water[y][x]:
                continue
            grid[y][x] = max(MOISTURE_MIN, min(MOISTURE_MAX, grid[y][x] + deltas[y][x]))
    return grid


def reference_groundwater_tick(moisture, groundwater):
    height = len(moisture)
    width = len(moisture[0]) if height else 0
    m_grid = [row[:] for row in moisture]
    g_grid = [row[:] for row in groundwater]
    for y in range(height):
        for x in range(width):
            m = m_grid[y][x]
            g = g_grid[y][x]
            if m >= GROUNDWATER_INFILTRATION_THRESHOLD:
                infiltrated = (m - GROUNDWATER_INFILTRATION_THRESHOLD) * GROUNDWATER_INFILTRATION_FRACTION
                g += infiltrated
                m = max(MOISTURE_MIN, m - infiltrated)
            elif m < GROUNDWATER_SEEP_THRESHOLD and g > GROUNDWATER_MIN:
                seep = min(g, (GROUNDWATER_SEEP_THRESHOLD - m)) * GROUNDWATER_SEEP_FRACTION
                g -= seep
                m = min(MOISTURE_MAX, m + seep)
            g_grid[y][x] = max(GROUNDWATER_MIN, min(GROUNDWATER_MAX, g - GROUNDWATER_PERCOLATION_LOSS))
            m_grid[y][x] = m
    return m_grid, g_grid


def approx_equal_grids(a, b, tol=1e-9) -> bool:
    return all(abs(av - bv) <= tol for ra, rb in zip(a, b) for av, bv in zip(ra, rb))


def main() -> int:
    rng = random.Random(20260804)

    trials_ok = True
    for trial in range(2000):
        height = rng.randint(1, 12)
        width = rng.randint(1, 12)
        moisture = [[rng.random() for _ in range(width)] for _ in range(height)]
        elevation = [[rng.random() for _ in range(width)] for _ in range(height)]
        is_water = [[1 if rng.random() < 0.2 else 0 for _ in range(width)] for _ in range(height)]
        precipitation = rng.random()
        evaporation = rng.uniform(0.0, 0.15)

        expected = reference_moisture_tick(moisture, elevation, is_water, precipitation, evaporation)
        actual = hydrology_moisture_tick(moisture, elevation, is_water, precipitation, evaporation)
        if not approx_equal_grids(expected, actual):
            trials_ok = False
            print(f"  moisture mismatch on trial {trial}: expected={expected} actual={actual}")
            break
    check("hydrology_moisture_tick matches the Python reference over 2000 randomized trials", trials_ok)

    trials_ok = True
    for trial in range(2000):
        height = rng.randint(1, 12)
        width = rng.randint(1, 12)
        moisture = [[rng.random() for _ in range(width)] for _ in range(height)]
        groundwater = [[rng.random() for _ in range(width)] for _ in range(height)]

        expected_m, expected_g = reference_groundwater_tick(moisture, groundwater)
        actual_m, actual_g = hydrology_groundwater_tick(moisture, groundwater)
        if not (approx_equal_grids(expected_m, actual_m) and approx_equal_grids(expected_g, actual_g)):
            trials_ok = False
            print(f"  groundwater mismatch on trial {trial}")
            break
    check("hydrology_groundwater_tick matches the Python reference over 2000 randomized trials", trials_ok)

    # Edge cases: empty grid, all-water grid, single tile.
    check("empty grid returns empty (moisture)", hydrology_moisture_tick([], [], [], 0.5, 0.06) == [])
    check(
        "all-water grid stays pinned to MOISTURE_MAX",
        hydrology_moisture_tick([[0.2, 0.3]], [[0.5, 0.4]], [[1, 1]], 1.0, 0.06) == [[1.0, 1.0]],
    )
    single_m, single_g = hydrology_groundwater_tick([[0.5]], [[0.5]])
    check("single-tile groundwater tick runs without error", isinstance(single_m[0][0], float))

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
