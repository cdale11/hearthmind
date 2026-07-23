"""A2 "Interacting local-rule systems: CA / diffusion / reaction-
diffusion" (docs/MASTERCHECKLIST-2026-07-22.md, Stage IV step 16): a
small library of generic field operators, composed each tick over any
2D grid — not tied to one subsystem. det_sys.md's own worked example
is forest succession (grass -> bush -> young -> old forest, gated by
sunlight/grazing/fire/soil/moisture); this module ships the three
named primitives (`diffuse`/`reaction_diffuse`/`cellular_step`) plus
`terrain_evolution.py`'s real first consumer — see that module's
`compute_succession_pressure`.

Every operator here is a PURE function: it reads a grid (or grids) and
returns a NEW grid, never mutating its input — composing several
operators in a per-tick pipeline (this module's own stated shape) only
works cleanly if each stage's output is independent of iteration order
and safe to feed straight into the next stage."""
from __future__ import annotations

from typing import Callable

Grid = list[list[float]]

_ADJACENT_4 = ((0, -1), (0, 1), (-1, 0), (1, 0))


def diffuse(grid: Grid, rate: float) -> Grid:
    """Each cell moves `rate` (0..1) of the way toward the average of
    its 4-neighbors — the generic "spread toward equilibrium" operator
    (heat, moisture, scent, or here: a smoothed neighborhood-density
    reading over a 0/1 indicator grid). `rate=0` returns the grid
    unchanged; `rate=1` snaps every cell straight to its neighbor
    average in one step. Edge cells diffuse against however many
    in-bounds neighbors they actually have, not a padded/wrapped
    edge — a real map boundary, not an artifact of the algorithm."""
    height = len(grid)
    width = len(grid[0]) if height else 0
    if width == 0 or height == 0 or rate <= 0.0:
        return [row[:] for row in grid]
    result: Grid = [[0.0] * width for _ in range(height)]
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


def reaction_diffuse(a: Grid, b: Grid, rate_a_to_b: float, rate_b_to_a: float) -> tuple[Grid, Grid]:
    """Two coupled fields exchange value each tick, proportional to
    their own local concentration — `a` converts into `b` at
    `rate_a_to_b`, `b` converts back at `rate_b_to_a`. A genuine
    reaction step (mass conserved between the pair at each cell); callers
    that also want spatial spread compose this with `diffuse` on each
    output field separately, per this module's own "small library of
    operators, composed each tick" design. Same pure/new-grid-per-call
    shape as `diffuse` — safe against a fixed input snapshot."""
    height = len(a)
    width = len(a[0]) if height else 0
    new_a: Grid = [[0.0] * width for _ in range(height)]
    new_b: Grid = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            av, bv = a[y][x], b[y][x]
            transferred_to_b = av * rate_a_to_b
            transferred_to_a = bv * rate_b_to_a
            new_a[y][x] = max(0.0, av - transferred_to_b + transferred_to_a)
            new_b[y][x] = max(0.0, bv - transferred_to_a + transferred_to_b)
    return new_a, new_b


def cellular_step(grid: Grid, rule: Callable[[float, list[float]], float]) -> Grid:
    """The generic Conway-style step: `rule(own_value, neighbor_values)
    -> new_value`, applied to every cell against a fixed snapshot of
    the input grid (so no cell's new value depends on another cell
    already having been updated this same step). `neighbor_values` is
    whatever subset of the 4 orthogonal neighbors are actually
    in-bounds — a real map edge, never padded/wrapped."""
    height = len(grid)
    width = len(grid[0]) if height else 0
    result: Grid = [[0.0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            neighbors = [
                grid[y + dy][x + dx]
                for dx, dy in _ADJACENT_4
                if 0 <= x + dx < width and 0 <= y + dy < height
            ]
            result[y][x] = rule(grid[y][x], neighbors)
    return result
