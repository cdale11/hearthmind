"""A1 "Continuous environmental fields" (docs/MASTERCHECKLIST-2026-07-
22.md, Part A, Stage I step 2): a `FieldGrid` abstraction — named
scalar fields over the map, each updated per tick by a local rule.

Deliberately coarse to start, per the roadmap's own scoping: reuses
`WEATHER_REGION_GRID` (3x3, `world/state.py`) rather than a new
per-tile resolution — "the interface (named fields, per-tick update,
cross-field coupling) matters more than resolution day one." Raising
resolution later (once the C++ dense-column store lands, R7) means
swapping this module's storage, not its callers — `get_at`/`step` stay
the same shape at any resolution.

R7 deviation, flagged (same precedent as spatial weather/mining scars/
minerals — CLAUDE.md's R7 section): this is Python, not C++, despite
being new physical-substrate code. A 3x3 grid is 9 cells per field;
even a dozen fields is under 200 floats total, several orders below
the density where a native port would pay for itself. Revisit once
resolution actually rises.

Ships one concrete field, `population_density` (agents per region,
normalized against the region with the most), to prove the shape
against a real per-tick consumer rather than shipping bare
infrastructure: `SimulationEngine._maybe_favor_uncrowded_fission_site`
reads it to bias new-settlement site search away from crowded regions
— a genuine "settlement siting" consumer, per A1's own "Feeds"
line. Diffusion/reaction-diffusion operators (A2) and the other eleven
named fields det_sys.md lists (moisture, fertility, disease-pressure,
...) are explicitly NOT built here — this is the substrate/interface,
not the full field roster; each future field is its own follow-up step
that plugs into the same `FieldGrid`."""
from __future__ import annotations

from dataclasses import dataclass, field

FIELD_GRID_SIZE = 3
"""Matches `world.state.WEATHER_REGION_GRID` — the same coarse 3x3
region split spatial weather already uses, so a `FieldGrid` field and
a weather region always line up 1:1 without a second coordinate
mapping to maintain."""


@dataclass
class FieldGrid:
    """`fields: {name: [[value_per_cell...] * SIZE] * SIZE}` — a dict of
    named `FIELD_GRID_SIZE` x `FIELD_GRID_SIZE` dense grids. Values are
    unbounded floats; individual fields document their own natural
    range in the producer that writes them (`population_density` here
    is 0..1 by construction)."""

    fields: dict[str, list[list[float]]] = field(default_factory=dict)

    def ensure_field(self, name: str) -> list[list[float]]:
        """Returns the named field's grid, creating it zero-filled on
        first use — callers never need a separate "does this field
        exist yet" branch."""
        grid = self.fields.get(name)
        if grid is None:
            grid = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
            self.fields[name] = grid
        return grid

    def region_of(self, pos: tuple[int, int] | None, width: int, height: int) -> tuple[int, int]:
        """Same bucketing math as `World.weather_at`'s region lookup —
        kept in lockstep deliberately (a field reading and the weather
        reading for the same position should always agree on which
        region they're in)."""
        if pos is None or width <= 0 or height <= 0:
            return (0, 0)
        rx = min(FIELD_GRID_SIZE - 1, max(0, pos[0] * FIELD_GRID_SIZE // width))
        ry = min(FIELD_GRID_SIZE - 1, max(0, pos[1] * FIELD_GRID_SIZE // height))
        return (rx, ry)

    def get_at(self, name: str, pos: tuple[int, int] | None, width: int, height: int) -> float:
        rx, ry = self.region_of(pos, width, height)
        return self.ensure_field(name)[ry][rx]

    def set_region(self, name: str, rx: int, ry: int, value: float) -> None:
        self.ensure_field(name)[ry][rx] = value

    def step_population_density(self, agent_positions: list[tuple[int, int]], width: int, height: int) -> None:
        """The one concrete field this pass ships: recomputes
        `population_density` from scratch each call (cheap — O(agents),
        no decay/diffusion needed since it's a live census, not an
        accumulating quantity) and normalizes 0..1 against whichever
        region currently holds the most agents. An empty world (no
        agents yet) leaves every cell at 0.0."""
        counts = [[0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in agent_positions:
            rx, ry = self.region_of(pos, width, height)
            counts[ry][rx] += 1
        peak = max((c for row in counts for c in row), default=0)
        for ry in range(FIELD_GRID_SIZE):
            for rx in range(FIELD_GRID_SIZE):
                self.set_region(
                    "population_density", rx, ry,
                    (counts[ry][rx] / peak) if peak > 0 else 0.0,
                )

    def to_dict(self) -> dict:
        return {name: [list(row) for row in grid] for name, grid in self.fields.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "FieldGrid":
        return cls(fields={name: [list(row) for row in grid] for name, grid in data.items()})
