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

Third slice (Tier 1, docs/ROADMAP-2026-07-REMAINING.md) ships
`pollution` — sourced from two already-real Body-state producers
(standing FACTORY/POWER_PLANT/OIL_RIG buildings, `World.mining_scars`)
rather than anything new, then spread via `ca_operators.diffuse` the
same way `disease_pressure` is (industrial fumes/runoff don't respect
the coarse region boundary either). Real consumer: `economy.farms.
FarmGrid.plant()` gained a `pollution` yield-penalty factor, same
bounded-floor shape `moisture` already has — "industry chokes the
fields nearby" is now a mechanical fact, not just a name on a list.

Fourth slice (Tier 1, docs/ROADMAP-2026-07-REMAINING.md) ships
`traffic` — sourced from `World.roads.wear` (already-real per-tile
road-usage state, same shape `mining_scars` gave `pollution`), spread
via `ca_operators.diffuse`. Real consumer: `SimulationEngine._maybe_
schedule_caravan`'s monthly visit chance now scales up with the
target settlement's own region traffic reading — "trade follows
roads" as a mechanical fact, the same kind of real multiplier
`has_market()`/`caravan_relation_factor` already apply to that same
`chance` value.

The remaining eight named fields (fertility, nutrients, scent, heat,
cultural-influence, ownership, beauty, noise) and migrating `disaster_
scars`/the climate grid onto `FieldGrid` proper remain explicitly NOT
built here — each is its own follow-up step against the same
`FieldGrid`/`ca_operators` shape now proven against four real
fields."""
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

POLLUTION_BUILDING_WEIGHT = 1.0
"""Each standing FACTORY/POWER_PLANT/OIL_RIG contributes this much to
its region's raw pollution reading before normalization — the
dominant source; industry is the point-source, mining scars (below)
are the secondary, more diffuse one."""

POLLUTION_MINING_SCAR_WEIGHT = 0.3
"""Each unit of `World.mining_scars` intensity in a region contributes
this fraction as much as one standing industrial building — real but
secondary; a heavily-scarred hillside alone shouldn't read as
polluted as an actual standing factory."""

POLLUTION_DIFFUSE_RATE = 0.3
"""Same role as `DISEASE_PRESSURE_DIFFUSE_RATE` — fumes/runoff from an
industrial region measurably affect its neighbors, not just the exact
region the source sits in, while still concentrating near the real
source rather than smearing flat."""

TRAFFIC_DIFFUSE_RATE = 0.3
"""Same role as `POLLUTION_DIFFUSE_RATE` — a busy road corridor's
traffic naturally reads as elevated in the regions it passes through
and touches, not just the exact tiles carrying the heaviest wear."""


def _normalize_peak(raw: list[list[float]]) -> list[list[float]]:
    """Scales a raw non-negative grid to 0..1 against its own peak cell
    — same "normalize against whichever region currently holds the
    most" shape `step_population_density` already established. An
    all-zero grid stays all-zero (no source anywhere yet)."""
    peak = max((v for row in raw for v in row), default=0.0)
    if peak <= 0.0:
        return [[0.0 for _ in row] for row in raw]
    return [[v / peak for v in row] for row in raw]


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

    def step_pollution(
        self, industrial_positions: list[tuple[int, int]],
        mining_scar_items: list[tuple[tuple[int, int], float]], width: int, height: int,
    ) -> None:
        """Third concrete field. Unlike `population_density`/`disease_
        pressure` (both live per-tick censuses), pollution's two
        sources are already slow-changing state elsewhere (standing
        buildings, `World.mining_scars`) — this just re-reads them each
        call (still cheap, same O(buildings + scarred tiles) either
        way) rather than accumulating its own separate history, keeping
        the same "recompute fresh, never drift" discipline every other
        field here follows. Normalizes against the region with the
        most raw pollution, then spreads via `ca_operators.diffuse` —
        real industrial impact isn't confined to the exact region a
        factory's tile falls in."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in industrial_positions:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += POLLUTION_BUILDING_WEIGHT
        for pos, intensity in mining_scar_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += intensity * POLLUTION_MINING_SCAR_WEIGHT
        self.fields["pollution"] = diffuse(_normalize_peak(raw), POLLUTION_DIFFUSE_RATE)

    def step_traffic(self, road_wear_items: list[tuple[tuple[int, int], float]], width: int, height: int) -> None:
        """Fourth concrete field. Same "re-read already-real slow-
        changing state" shape `step_pollution` established: `World.
        roads.wear` (per-tile, already accumulated by `RoadNetwork.
        tick`) is summed per region, normalized against the region
        with the most, then spread via `ca_operators.diffuse` — a
        region just off a busy road corridor reads real, elevated
        traffic too, not just the exact tiles carrying wear."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, wear in road_wear_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += wear
        self.fields["traffic"] = diffuse(_normalize_peak(raw), TRAFFIC_DIFFUSE_RATE)

    def to_dict(self) -> dict:
        return {name: [list(row) for row in grid] for name, grid in self.fields.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "FieldGrid":
        return cls(fields={name: [list(row) for row in grid] for name, grid in data.items()})
