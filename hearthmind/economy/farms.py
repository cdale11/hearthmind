"""Cultivated farmland: planted and grown automatically, harvested by
agent presence — a substantially more reliable food source than wild
foraging.

Direct response to the Phase C finding (docs/DECISIONS.md, C5): in long
soak tests, populations collapsed from starvation before reaching
maturity, and system-wide wild-forage supply looked adequate on paper
while agents still starved — pointing at *access*, not raw scarcity, as
the bottleneck. Farms don't fix access to wild nodes; they add a second,
much higher-yield food source that, once planted, doesn't require an
agent to get lucky finding it repeatedly — it grows in place and the
whole population can return to a known location. See docs/DECISIONS.md,
D1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hearthmind.world.resources import is_adjacent_to_water
from hearthmind.world.terrain import Biome, Tile

try:
    from hearthmind._native import farm_grid_tick as _native_farm_grid_tick
except ImportError:
    _native_farm_grid_tick = None
"""Optional compiled fast path for `FarmGrid.tick` (module 8, R7's first
module — see cpp/src/farm_grid.cpp, docs/DECISIONS.md "Native extension
port"). `None` when the extension wasn't built — falls back to the
equivalent pure-Python per-plot loop in that case."""

try:
    from hearthmind._native import (
        soil_fertility_deplete_step as _native_soil_fertility_deplete_step,
        soil_fertility_recover_step as _native_soil_fertility_recover_step,
    )
except ImportError:
    _native_soil_fertility_deplete_step = None
    _native_soil_fertility_recover_step = None
"""Optional compiled fast path for `FarmGrid._tick_soil_fertility` (v1
audit fix — see cpp/src/soil_fertility.cpp; this was a genuine per-tick
hot loop sitting unported next to its native sibling farm_grid_tick
above, with no R7-deviation justification). Same "dict iteration stays
Python, only the scalar step moves to C++" shape as road_wear.py's
native pair. `None` when the extension wasn't built — falls back to the
equivalent pure-Python arithmetic in that case."""

FARMABLE_BIOMES = frozenset({Biome.GRASSLAND})
"""Deliberately narrower than WALKABLE_BIOMES/FORAGEABLE_BIOMES — open
grassland only, not forest/hills, matching the "cleared field" image."""

PLANT_CHANCE_PER_TICK = 0.01
"""Rolled once per unclaimed farmable tile with at least one awake agent
present (not once per agent — a crowded tile is no likelier to get
planted than a lone agent's) — no maturity/health/colocation requirement,
unlike construction (A3-style pairing) or founding a building (C1):
farming is meant to be an easy, low-commitment individual act, not a
milestone."""

GROWTH_PER_TICK = 0.004
"""~250 ticks (about 2.6 sim-days at default pacing) from planting to
harvest-ready — deliberately much faster than a resource node's ~500-tick
regrowth (world/resources.py), since cultivation is the whole point."""

MAX_FARM_YIELD = 3.0
"""A ready plot's total food pool — larger than a wild ResourceNode's 1.0
max, reflecting a tended plot feeding more than an opportunistic forage."""

HARVEST_AMOUNT = 0.3
"""Units consumed from a ready plot per successful harvest."""

HARVEST_HUNGER_RELIEF = 0.5
"""Hunger relief for a full harvest — noticeably better than a wild
forage's 0.3, the deliberate incentive to prefer farms once available."""

FARM_TOOL_MATERIALS_COST = 2.0
"""Materials consumed from the settlement stockpile (D8) to plant a
"tooled" plot instead of a plain one — see Population._maybe_plant, D9."""

FARM_TOOL_YIELD_MULTIPLIER = 1.5
"""A tooled plot's max yield is MAX_FARM_YIELD * this — the payoff for
spending materials on farming instead of construction, closing the D8
production chain's other end. See D9."""

FARM_ROT_TICKS = 1500
"""Ticks a READY plot stands unharvested before the crop rots and the
plot reverts to unclaimed farmland (~15.6 sim-days at default pacing —
a real harvest window, not a pantry). Added by the July 2026
architecture review's carrying-capacity rework: previously a READY
plot persisted until eaten, so the map accumulated ~1,000
simultaneously-ready plots for 200 people and food became permanently
post-scarce. Rot makes standing food a flow (must be harvested while
good) rather than an ever-growing stock — the constraint that used to
disappear after year one now persists for the life of the world."""

SEASON_GROWTH_MULTIPLIER = {"winter": 0.35, "autumn": 0.8, "spring": 1.15, "summer": 1.0}
"""Farm growth multiplier by season name — winter genuinely slows
cultivation, not just a cosmetic weather label ("seasons affect
farming"). A season name absent from this table (a custom Config's
`seasons_per_year` need not use these four names) defaults to 1.0 via
`.get(season, 1.0)` in `FarmGrid.tick`. See docs/DECISIONS.md, scarcity
pass."""

SOIL_FERTILITY_MIN = 0.4
"""§6 "Soil fertility as a real field" (docs/IDEAS-2026-07-EMERGENCE.md):
floor on `FarmGrid.soil_fertility` — exhausted land still yields
something (a floor, not a dead end you can never farm again), just
noticeably less than fresh/rested land. Never reaches 0."""

FARM_MOISTURE_YIELD_MIN_FACTOR = 0.5
"""A11 "Continuous hydrology," first slice (roadmap Stage IV step 15):
floor on the moisture-scaled yield multiplier in `FarmGrid.plant()` —
same "a floor, not a dead end" shape as `SOIL_FERTILITY_MIN` above. A
tile at zero measured surface moisture still yields half of what a
fully-watered one would (real soil always retains some water even in
a dry reading); this is the actual mechanical lever that makes
`world/hydrology_field.py`'s moisture field matter to a planting
decision, not just a number nothing reads."""

SOIL_FERTILITY_DEPLETION_PER_TICK = 0.00015
"""Fertility lost per tick a tile has an active plot (GROWING or READY)
on it — continuous cultivation without rest exhausts the soil. At this
rate a plot worked continuously for ~4000 ticks (about the time several
GROWTH_PER_TICK cycles take) drops from 1.0 fertility to the floor,
rewarding rotation (letting a tile sit fallow between plantings) over
permanently re-planting the same spot the instant it's harvested."""

SOIL_FERTILITY_RECOVERY_PER_TICK = 0.0003
"""Fertility regained per tick a previously-farmed tile has NO active
plot (fallow) — twice the depletion rate, so a tile that's rested for
a while recovers meaningfully faster than it was worn down, matching
real crop-rotation practice (a season fallow undoes much more than a
season of continuous cropping cost)."""


IRRIGATION_GROWTH_MULTIPLIER = 1.35
"""Integration milestone ("infrastructure networks"): a plot adjacent
to water (`world/resources.is_adjacent_to_water` — the same helper H-
era fishing already uses for node placement) grows this much faster —
a real irrigation effect, not flavor text, reusing an existing terrain
signal rather than inventing a new water-network data structure.
Deliberately still weaker than a bad season is harsh (`SEASON_GROWTH_
MULTIPLIER["winter"]` = 0.35, more than a 2x swing) — irrigation helps,
it doesn't override the calendar. Stacks multiplicatively with the
season multiplier and the existing tool/no-tool yield distinction
(which affects `max_yield`, not growth *rate* — irrigation and tooling
are deliberately independent levers: how fast a plot grows vs. how
much it eventually yields)."""


class FarmStage(str, Enum):
    GROWING = "growing"
    READY = "ready"
    # No EMPTY stage: an unclaimed tile is simply absent from
    # FarmGrid.plots (see harvest()) rather than present with a stage —
    # "not farmed" and "depleted, waiting to be replanted" are the same
    # state, so there's nothing an EMPTY member would distinguish.


def _is_farmable(terrain: list[list[Tile]], x: int, y: int) -> bool:
    return terrain[y][x].biome in FARMABLE_BIOMES


@dataclass
class FarmPlot:
    x: int
    y: int
    stage: FarmStage = FarmStage.GROWING
    """A freshly-planted plot starts GROWING (see FarmGrid.plant); there is
    no "empty" stage — see the FarmStage docstring."""
    growth: float = 0.0
    """0..1, meaningful while GROWING."""
    amount: float = 0.0
    """0..max_yield, meaningful while READY."""
    max_yield: float = MAX_FARM_YIELD
    """Set at planting time (see FarmGrid.plant) — MAX_FARM_YIELD for a
    plain plot, or MAX_FARM_YIELD * FARM_TOOL_YIELD_MULTIPLIER for a
    tooled one (D9)."""
    ready_ticks: int = 0
    """Ticks spent READY so far — the crop rots (plot removed) at
    FARM_ROT_TICKS. Defaults to 0 for plots from older snapshots."""

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "stage": self.stage.value,
            "growth": round(self.growth, 4),
            "amount": round(self.amount, 4),
            "max_yield": round(self.max_yield, 4),
            "ready_ticks": self.ready_ticks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FarmPlot":
        return cls(
            x=data["x"],
            y=data["y"],
            stage=FarmStage(data["stage"]),
            growth=data["growth"],
            amount=data["amount"],
            max_yield=data.get("max_yield", MAX_FARM_YIELD),
            ready_ticks=data.get("ready_ticks", 0),
        )


@dataclass
class FarmGrid:
    plots: dict[tuple[int, int], FarmPlot] = field(default_factory=dict)
    soil_fertility: dict[tuple[int, int], float] = field(default_factory=dict)
    """§6 "Soil fertility as a real field": per-tile 0..1 multiplier,
    only tracked for tiles that have EVER been planted (bounded by
    distinct farmed-tile count, not the whole map — self-limiting the
    same way `World.terrain_activity` is) — absent means "never farmed,
    full fertility" (1.0). Depletes while a tile has an active plot,
    recovers while fallow (present in this dict but not in `plots`).
    Read (not consumed) at `plant()` time to scale the new plot's
    `max_yield` — repeatedly re-planting the same worn-out spot the
    instant it's harvested yields less than resting it between
    plantings, making crop rotation and "the old fields" (an
    exhausted-then-abandoned patch) real emergent behavior rather than
    implicit in biome/farm state."""

    # --- queries -------------------------------------------------------------

    def get(self, x: int, y: int) -> FarmPlot | None:
        return self.plots.get((x, y))

    def fertility_at(self, x: int, y: int) -> float:
        return self.soil_fertility.get((x, y), 1.0)

    @staticmethod
    def is_farmable(terrain: list[list[Tile]], x: int, y: int) -> bool:
        return _is_farmable(terrain, x, y)

    # --- planting ------------------------------------------------------------

    def plant(self, x: int, y: int, tooled: bool = False, moisture: float = 1.0) -> FarmPlot:
        """`moisture` (A11, roadmap Stage IV step 15): the real per-tile
        surface-moisture reading from `World.hydrology_field` at plant
        time, 0..1. Scaled into a bounded `FARM_MOISTURE_YIELD_MIN_
        FACTOR..1.0` multiplier — a bone-dry tile still yields
        something (there's always SOME residual soil water), a
        well-watered one yields at full potential. Defaults to `1.0`
        (best case) so every existing call site/test that doesn't pass
        a real reading keeps its old behavior exactly."""
        base_max_yield = MAX_FARM_YIELD * FARM_TOOL_YIELD_MULTIPLIER if tooled else MAX_FARM_YIELD
        fertility = self.fertility_at(x, y)
        moisture_factor = FARM_MOISTURE_YIELD_MIN_FACTOR + max(0.0, min(1.0, moisture)) * (
            1.0 - FARM_MOISTURE_YIELD_MIN_FACTOR
        )
        plot = FarmPlot(x=x, y=y, max_yield=base_max_yield * fertility * moisture_factor)
        self.plots[(x, y)] = plot
        self.soil_fertility.setdefault((x, y), fertility)
        return plot

    def _tick_soil_fertility(self) -> None:
        """Deplete every tile with an active plot, recover every
        tracked-but-currently-fallow tile — a plain Python loop bounded
        by `len(soil_fertility)` (distinct ever-farmed tiles), run
        alongside (not inside) the native fast path below since it's an
        orthogonal per-tile float, not part of `FarmPlot`'s own state.
        The scalar step itself (not the dict iteration) has an optional
        native fast path — see cpp/src/soil_fertility.cpp."""
        if _native_soil_fertility_deplete_step is not None:
            for pos in self.plots:
                self.soil_fertility[pos] = _native_soil_fertility_deplete_step(
                    self.fertility_at(*pos), SOIL_FERTILITY_DEPLETION_PER_TICK, SOIL_FERTILITY_MIN,
                )
            for pos in list(self.soil_fertility):
                if pos in self.plots:
                    continue
                self.soil_fertility[pos] = _native_soil_fertility_recover_step(
                    self.fertility_at(*pos), SOIL_FERTILITY_RECOVERY_PER_TICK,
                )
            return
        for pos in self.plots:
            self.soil_fertility[pos] = max(
                SOIL_FERTILITY_MIN, self.fertility_at(*pos) - SOIL_FERTILITY_DEPLETION_PER_TICK,
            )
        for pos in list(self.soil_fertility):
            if pos in self.plots:
                continue
            self.soil_fertility[pos] = min(
                1.0, self.fertility_at(*pos) + SOIL_FERTILITY_RECOVERY_PER_TICK,
            )

    def harvest(self, x: int, y: int, amount: float) -> float:
        """Consume up to `amount` from the ready plot at (x, y), removing
        it once depleted (see the FarmStage note above — it must be
        replanted, not "reset"). Returns the amount actually consumed
        (0.0 if no ready plot is there)."""
        plot = self.plots.get((x, y))
        if plot is None or plot.stage is not FarmStage.READY:
            return 0.0
        consumed = min(plot.amount, amount)
        plot.amount -= consumed
        if plot.amount <= 0.0:
            del self.plots[(x, y)]  # depleted plot reverts to unclaimed farmland
        return consumed

    # --- tick ------------------------------------------------------------------

    def tick(self, season: str = "summer", terrain: list[list[Tile]] | None = None) -> None:
        base_growth_rate = GROWTH_PER_TICK * SEASON_GROWTH_MULTIPLIER.get(season, 1.0)
        self._tick_soil_fertility()

        if _native_farm_grid_tick is not None:
            # Native fast path (module 8): irrigation adjacency is a
            # terrain lookup over `Tile` objects, so it's resolved here
            # in Python exactly as before; the native call only does the
            # per-plot growth/rot arithmetic.
            stage_by_enum = {FarmStage.GROWING: 0, FarmStage.READY: 1}
            stage_by_int = {0: FarmStage.GROWING, 1: FarmStage.READY}
            plots_in = [
                (
                    x, y, stage_by_enum[plot.stage], plot.growth, plot.amount,
                    plot.max_yield, plot.ready_ticks,
                    terrain is not None and is_adjacent_to_water(terrain, x, y),
                )
                for (x, y), plot in self.plots.items()
            ]
            updated, rotted = _native_farm_grid_tick(
                plots_in, base_growth_rate, IRRIGATION_GROWTH_MULTIPLIER, FARM_ROT_TICKS,
            )
            for x, y, stage, growth, amount, max_yield, ready_ticks in updated:
                plot = self.plots[(x, y)]
                plot.stage = stage_by_int[stage]
                plot.growth = growth
                plot.amount = amount
                plot.ready_ticks = ready_ticks
            for pos in rotted:
                del self.plots[tuple(pos)]
            return

        rotted: list[tuple[int, int]] = []
        for (x, y), plot in self.plots.items():
            if plot.stage is FarmStage.GROWING:
                # Irrigation (integration milestone): a water-adjacent
                # plot grows faster — see IRRIGATION_GROWTH_MULTIPLIER.
                # `terrain` is optional so callers that only care about
                # depletion/season behavior (older call sites, tests)
                # aren't forced to thread it through.
                growth_rate = base_growth_rate
                if terrain is not None and is_adjacent_to_water(terrain, x, y):
                    growth_rate *= IRRIGATION_GROWTH_MULTIPLIER
                plot.growth = min(1.0, plot.growth + growth_rate)
                if plot.growth >= 1.0:
                    plot.stage = FarmStage.READY
                    plot.amount = plot.max_yield
            elif plot.stage is FarmStage.READY:
                plot.ready_ticks += 1
                if plot.ready_ticks >= FARM_ROT_TICKS:
                    rotted.append((x, y))  # crop spoiled unharvested — see FARM_ROT_TICKS
        for pos in rotted:
            del self.plots[pos]

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        growing = sum(1 for p in self.plots.values() if p.stage is FarmStage.GROWING)
        ready = sum(1 for p in self.plots.values() if p.stage is FarmStage.READY)
        avg_fertility = (
            round(sum(self.soil_fertility.values()) / len(self.soil_fertility), 3)
            if self.soil_fertility else 1.0
        )
        return {"total": len(self.plots), "growing": growing, "ready": ready, "avg_soil_fertility": avg_fertility}

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "plots": [p.to_dict() for p in self.plots.values()],
            "soil_fertility": {f"{x}:{y}": v for (x, y), v in self.soil_fertility.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FarmGrid":
        plots: dict[tuple[int, int], FarmPlot] = {}
        for plot_data in data["plots"]:
            plot = FarmPlot.from_dict(plot_data)
            plots[(plot.x, plot.y)] = plot
        soil_fertility: dict[tuple[int, int], float] = {}
        for key, value in data.get("soil_fertility", {}).items():
            x_str, y_str = key.split(":")
            soil_fertility[(int(x_str), int(y_str))] = value
        return cls(plots=plots, soil_fertility=soil_fertility)
