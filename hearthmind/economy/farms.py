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

from hearthmind.world.terrain import Biome, Tile

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
    """0..MAX_FARM_YIELD, meaningful while READY."""

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "stage": self.stage.value,
            "growth": round(self.growth, 4),
            "amount": round(self.amount, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FarmPlot":
        return cls(
            x=data["x"],
            y=data["y"],
            stage=FarmStage(data["stage"]),
            growth=data["growth"],
            amount=data["amount"],
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

    def plant(self, x: int, y: int) -> FarmPlot:
        plot = FarmPlot(x=x, y=y)
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

    def tick(self) -> None:
        for plot in self.plots.values():
            if plot.stage is FarmStage.GROWING:
                plot.growth = min(1.0, plot.growth + GROWTH_PER_TICK)
                if plot.growth >= 1.0:
                    plot.stage = FarmStage.READY
                    plot.amount = MAX_FARM_YIELD

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
