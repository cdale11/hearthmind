"""Buildings: constructed, decaying, repairable structures on the terrain.

Emergence lever, paralleling resources.py: buildings are finite, local,
and require sustained agent presence to build or maintain. Left untended,
weather erodes them; abandoned ruins are eventually reclaimed by nature.
Placement is deterministic in this slice — colocated, mature, healthy
agents may found a building, the same shape as A3's reproduction — not
yet an LLM/goal decision. See docs/DECISIONS.md, C1-C4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hearthmind.world.weather import WeatherState


class BuildingStage(str, Enum):
    UNDER_CONSTRUCTION = "under_construction"
    STANDING = "standing"
    RUINED = "ruined"


class BuildingKind(str, Enum):
    HUT = "hut"
    GRANARY = "granary"
    """Communal food storage — see docs/DECISIONS.md, D7. Once standing,
    well-fed agents present passively stock it, and hungry agents can draw
    from it (Population._maybe_forage/_nearest_food_target) — a buffer
    against a bad patch of wild-forage/farm luck rather than a
    per-agent inventory system, which doesn't exist in this project."""


CONSTRUCTION_WORK_PER_TICK = 0.05
"""Progress added per tick, per present worker (capped at MAX_WORKERS
counted workers) — a hut takes ~20 ticks of one agent's continuous
presence, faster with more hands."""

REPAIR_WORK_PER_TICK = 0.03
"""Condition restored per tick, per present worker, for a standing
building below REPAIR_THRESHOLD."""

MAX_WORKERS = 3
"""Extra agents beyond this at one site don't speed construction/repair
further — a crude stand-in for "there's only so much useful room to work.\""""

REPAIR_THRESHOLD = 0.5
"""Standing buildings below this condition attract repair work from any
awake agents present, in addition to whatever else those agents are doing."""

DECAY_PER_TICK_BASE = 0.0004
"""Baseline condition lost per tick for a standing building — roughly a
full decay from perfect condition over ~2500 ticks (~26 sim-days at
default pacing) with no weather effect and no repair."""

DECAY_WEATHER_MULTIPLIER = 3.0
"""Multiplier applied to decay during precipitation or high wind — storms
wear structures down faster than fair weather."""

SETTLE_CHANCE_PER_TICK = 0.01
"""Rolled only for mature, healthy, colocated (2+) agents standing on a
tile with no existing building — see Population._maybe_start_construction.
Raised from 0.003 (D6): with D4/D5/D6's survival fixes, qualifying pairs
are no longer rare, so the original rate left construction lagging behind
demand. Matches PLANT_CHANCE_PER_TICK's cadence."""

MATURE_WORKER_ONLY = False
"""Whether construction/repair work requires workers to be "mature"
(see agents.agent.MATURITY_TICKS). False: any awake agent present helps —
only *founding* a new building requires maturity (see C1)."""

RUIN_REMOVAL_TICKS = 3000
"""Ticks a ruined building persists (still inspectable) before nature
finishes reclaiming it and it's removed from the world entirely."""

GRANARY_KIND_CHANCE = 0.3
"""Fraction of newly-started buildings that are GRANARY rather than HUT —
rolled once at founding (Population._maybe_start_construction), not a
player/agent choice yet."""

GRANARY_CAPACITY = 15.0
"""Max food a standing granary can hold — several farm harvests' worth
(MAX_FARM_YIELD is 3.0), enough to matter as a buffer without trivializing
scarcity."""

GRANARY_WELLFED_HUNGER_THRESHOLD = 0.3
"""An awake agent at or below this hunger, present at a standing granary,
contributes surplus each tick — presence-driven like every other
mechanic here (foraging, construction), not a hauling/inventory system."""

GRANARY_DEPOSIT_PER_TICK = 0.02
"""Food added per well-fed agent present, per tick, up to GRANARY_CAPACITY."""

GRANARY_WITHDRAW_AMOUNT = 0.25
"""Food consumed from a granary per successful withdrawal (see
Population._maybe_forage) — between a wild forage (FORAGE_AMOUNT 0.2) and
a farm harvest (HARVEST_AMOUNT 0.3): better than scrounging, worse than a
fresh crop."""

GRANARY_HUNGER_RELIEF = 0.4
"""Hunger relief for a full granary withdrawal — between
FORAGE_HUNGER_RELIEF (0.3) and HARVEST_HUNGER_RELIEF (0.5)."""

MATERIALS_CAPACITY = 30.0
"""Max wood/stone a settlement's shared stockpile can hold — see D8."""

MATERIALS_GATHER_PER_TICK = 0.03
"""Materials added per GATHER-goal agent present on forest/hills, per
tick, up to MATERIALS_CAPACITY — see Population._maybe_gather."""

MATERIALS_PER_CONSTRUCTION_TICK = 0.1
"""Materials consumed per tick a construction site draws on the
stockpile, in exchange for CONSTRUCTION_MATERIALS_MULTIPLIER — see
Population._advance_construction."""

CONSTRUCTION_MATERIALS_MULTIPLIER = 2.0
"""Construction progress multiplier while materials are available and
being consumed — the actual payoff of the D8 production chain (gather ->
stockpile -> faster building) over presence alone."""

CURRENCY_CAPACITY = 50.0
"""Max settlement currency — see D10."""

CURRENCY_PER_OVERFLOW_UNIT = 1.0
"""Currency generated per unit of food/materials that would otherwise be
wasted once a granary/the materials stockpile is already at capacity —
"trade" here means selling surplus to an abstract outside economy, not
literal per-agent barter, since no per-agent inventory exists in this
project (see docs/DECISIONS.md, D10 for the full rationale)."""

CURRENCY_EMERGENCY_RATION_COST = 2.0
"""Currency spent per emergency-ration purchase — see
Population._maybe_forage, D10."""

CURRENCY_EMERGENCY_HUNGER_RELIEF = 0.4
"""Hunger relief per emergency-ration purchase — matches
GRANARY_HUNGER_RELIEF: bought food is as good as stored food, just costs
currency instead of being free."""


@dataclass
class Building:
    id: int
    x: int
    y: int
    kind: BuildingKind = BuildingKind.HUT
    stage: BuildingStage = BuildingStage.UNDER_CONSTRUCTION
    progress: float = 0.0
    """0..1, meaningful while UNDER_CONSTRUCTION."""
    condition: float = 1.0
    """0..1, meaningful while STANDING (and while decaying toward RUINED)."""
    ruined_ticks: int = 0
    """Ticks spent as a ruin so far — see RUIN_REMOVAL_TICKS."""
    stored_food: float = 0.0
    """0..GRANARY_CAPACITY, meaningful only for a STANDING GRANARY."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "kind": self.kind.value,
            "stage": self.stage.value,
            "progress": round(self.progress, 4),
            "condition": round(self.condition, 4),
            "ruined_ticks": self.ruined_ticks,
            "stored_food": round(self.stored_food, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Building":
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            kind=BuildingKind(data.get("kind", BuildingKind.HUT.value)),
            stage=BuildingStage(data["stage"]),
            progress=data["progress"],
            condition=data["condition"],
            ruined_ticks=data.get("ruined_ticks", 0),
            stored_food=data.get("stored_food", 0.0),
        )


@dataclass
class Settlement:
    """All buildings in the world. Named distinctly from any per-agent
    concept to leave room for a future named-settlement/culture layer
    (Phase E) grouping buildings without a confusing rename here."""

    buildings: list[Building] = field(default_factory=list)
    _next_id: int = 0
    materials: float = 0.0
    """Shared wood/stone stockpile, 0..MATERIALS_CAPACITY — see D8. Global
    to the settlement rather than per-building/per-tile: unlike food
    (which must be consumed near where it's stored), materials are
    fungible and this project has no hauling/transport system to move
    them tile-by-tile."""
    currency: float = 0.0
    """Settlement-wide wealth, 0..CURRENCY_CAPACITY — see D10. Generated
    from food/materials surplus that would otherwise be wasted at
    capacity; spent on emergency food when a granary's own stock runs
    out. Settlement-wide for the same reason as `materials`: no
    per-agent wallet/inventory system exists."""

    # --- queries -------------------------------------------------------------

    def at(self, x: int, y: int) -> Building | None:
        for building in self.buildings:
            if building.x == x and building.y == y:
                return building
        return None

    # --- construction ------------------------------------------------------

    def start_construction(self, x: int, y: int, kind: BuildingKind = BuildingKind.HUT) -> Building:
        building = Building(id=self._next_id, x=x, y=y, kind=kind)
        self._next_id += 1
        self.buildings.append(building)
        return building

    # --- tick: weathering, ruin, reclamation ----------------------------------

    def tick(self, weather: WeatherState) -> list[tuple[str, str]]:
        """Weather-driven decay of standing buildings into ruins, and
        eventual removal of long-abandoned ruins. Returns life-cycle
        events as (category, description) pairs. Construction/repair
        progress (which needs agent presence) is handled separately by
        Population.tick, since Settlement has no agent awareness."""
        events: list[tuple[str, str]] = []
        survivors: list[Building] = []

        weather_harsh = weather.precipitation > 0.4 or weather.wind > 0.5 or weather.is_snowing
        decay = DECAY_PER_TICK_BASE * (DECAY_WEATHER_MULTIPLIER if weather_harsh else 1.0)

        for building in self.buildings:
            if building.stage is BuildingStage.STANDING:
                building.condition = max(0.0, building.condition - decay)
                if building.condition <= 0.0:
                    building.stage = BuildingStage.RUINED
                    events.append(("building_ruined", f"A structure at ({building.x}, {building.y}) fell into ruin."))
            elif building.stage is BuildingStage.RUINED:
                building.ruined_ticks += 1
                if building.ruined_ticks >= RUIN_REMOVAL_TICKS:
                    events.append(
                        ("building_reclaimed", f"Nature reclaimed the ruins at ({building.x}, {building.y}).")
                    )
                    continue  # dropped from survivors — removed from the world

            survivors.append(building)

        self.buildings = survivors
        return events

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        under_construction = sum(1 for b in self.buildings if b.stage is BuildingStage.UNDER_CONSTRUCTION)
        standing = [b for b in self.buildings if b.stage is BuildingStage.STANDING]
        ruined = sum(1 for b in self.buildings if b.stage is BuildingStage.RUINED)
        avg_condition = sum(b.condition for b in standing) / len(standing) if standing else 0.0
        granaries = [b for b in standing if b.kind is BuildingKind.GRANARY]
        return {
            "total": len(self.buildings),
            "under_construction": under_construction,
            "standing": len(standing),
            "ruined": ruined,
            "avg_condition": round(avg_condition, 3),
            "granaries": len(granaries),
            "granary_food": round(sum(b.stored_food for b in granaries), 3),
            "materials": round(self.materials, 3),
            "currency": round(self.currency, 3),
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "buildings": [b.to_dict() for b in self.buildings],
            "next_id": self._next_id,
            "materials": round(self.materials, 4),
            "currency": round(self.currency, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Settlement":
        buildings = [Building.from_dict(b) for b in data["buildings"]]
        return cls(
            buildings=buildings, _next_id=data["next_id"],
            materials=data.get("materials", 0.0), currency=data.get("currency", 0.0),
        )
