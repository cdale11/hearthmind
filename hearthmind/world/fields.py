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

First slice ships one concrete field, `population_density` (agents per
region, normalized against the region with the most): `SimulationEngine.
_maybe_favor_uncrowded_fission_site` reads it to bias new-settlement
site search away from crowded regions — a genuine "settlement siting"
consumer, per A1's own "Feeds" line.

Second slice (A1/A2 together, docs/ROADMAP-2026-07-REMAINING.md Tier 1
items 3-4) ships `disease_pressure` — the second of the eleven other
named fields, chosen because contagion is the single most natural
`diffuse()` consumer in the whole codebase: real sickness IS a
diffusion process, not a metaphorical one. `step_disease_pressure`
recomputes a raw regional sick-fraction census each tick (same "live
census, not an accumulating quantity" shape `population_density`
already established), then spreads it with `world.ca_operators.
diffuse` — contagion risk doesn't respect the coarse region boundary
any more than population density needing a real neighbor-averaging
pass would, and this is A2's stated ask ("the doc calls for a small
general operator library other systems can reuse... today only
succession uses it") getting its second real consumer. `Population.
_maybe_outbreak` weights its index-case draw by the sick agent's own
region's `disease_pressure` instead of a flat uniform choice —
genuinely wet-adjacent regions of the map (regions bordering an
already-sick one) become measurably more likely to seed the NEXT
spontaneous case, not just the literally-already-sick region itself.

The other ten named fields (fertility, nutrients, pollution, scent,
traffic, heat, cultural-influence, ownership, beauty, noise) and
migrating `mining_scars`/`disaster_scars`/the climate grid onto
`FieldGrid` proper remain explicitly NOT built here — each is its own
follow-up step against the same `FieldGrid`/`ca_operators` shape now
proven against two real fields, not one."""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.world.ca_operators import diffuse

FIELD_GRID_SIZE = 3
"""Matches `world.state.WEATHER_REGION_GRID` — the same coarse 3x3
region split spatial weather already uses, so a `FieldGrid` field and
a weather region always line up 1:1 without a second coordinate
mapping to maintain."""

DISEASE_PRESSURE_DIFFUSE_RATE = 0.35
"""How strongly `disease_pressure` spreads into a region's neighbors
each tick via `ca_operators.diffuse` — high enough that a region
bordering a real outbreak reads measurably elevated within a handful
of ticks (contagion risk is a regional property, not confined to the
exact region sick agents currently stand in), low enough that pressure
still visibly concentrates near its real source rather than smearing
flat across the whole map."""


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

    def step_disease_pressure(self, sick_positions: list[tuple[int, int]], total_agents: int, width: int, height: int) -> None:
        """Second concrete field. Recomputes a raw regional sick-fraction
        census each call (same "live census, not accumulating" shape as
        `step_population_density`), then spreads it into neighboring
        regions via `ca_operators.diffuse` — a region with no sick
        agents of its own but adjacent to one that does reads real,
        elevated pressure, the actual point of using a diffusion
        operator here rather than a bare census. An empty world (no
        agents yet) leaves every cell at 0.0."""
        counts = [[0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in sick_positions:
            rx, ry = self.region_of(pos, width, height)
            counts[ry][rx] += 1
        raw = [
            [(counts[ry][rx] / total_agents) if total_agents > 0 else 0.0 for rx in range(FIELD_GRID_SIZE)]
            for ry in range(FIELD_GRID_SIZE)
        ]
        self.fields["disease_pressure"] = diffuse(raw, DISEASE_PRESSURE_DIFFUSE_RATE)

    def to_dict(self) -> dict:
        return {name: [list(row) for row in grid] for name, grid in self.fields.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "FieldGrid":
        return cls(fields={name: [list(row) for row in grid] for name, grid in data.items()})
