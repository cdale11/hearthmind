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

    # --- queries -------------------------------------------------------------

    def get(self, x: int, y: int) -> FarmPlot | None:
        return self.plots.get((x, y))

    @staticmethod
    def is_farmable(terrain: list[list[Tile]], x: int, y: int) -> bool:
        return _is_farmable(terrain, x, y)

    # --- planting ------------------------------------------------------------

    def plant(self, x: int, y: int, tooled: bool = False) -> FarmPlot:
        max_yield = MAX_FARM_YIELD * FARM_TOOL_YIELD_MULTIPLIER if tooled else MAX_FARM_YIELD
        plot = FarmPlot(x=x, y=y, max_yield=max_yield)
        self.plots[(x, y)] = plot
        return plot

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
        return {"total": len(self.plots), "growing": growing, "ready": ready}

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {"plots": [p.to_dict() for p in self.plots.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> "FarmGrid":
        plots: dict[tuple[int, int], FarmPlot] = {}
        for plot_data in data["plots"]:
            plot = FarmPlot.from_dict(plot_data)
            plots[(plot.x, plot.y)] = plot
        return cls(plots=plots)
