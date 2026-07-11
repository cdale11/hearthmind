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


@dataclass
class Building:
    id: int
    x: int
    y: int
    stage: BuildingStage = BuildingStage.UNDER_CONSTRUCTION
    progress: float = 0.0
    """0..1, meaningful while UNDER_CONSTRUCTION."""
    condition: float = 1.0
    """0..1, meaningful while STANDING (and while decaying toward RUINED)."""
    ruined_ticks: int = 0
    """Ticks spent as a ruin so far — see RUIN_REMOVAL_TICKS."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "stage": self.stage.value,
            "progress": round(self.progress, 4),
            "condition": round(self.condition, 4),
            "ruined_ticks": self.ruined_ticks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Building":
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            stage=BuildingStage(data["stage"]),
            progress=data["progress"],
            condition=data["condition"],
            ruined_ticks=data.get("ruined_ticks", 0),
        )


@dataclass
class Settlement:
    """All buildings in the world. Named distinctly from any per-agent
    concept to leave room for a future named-settlement/culture layer
    (Phase E) grouping buildings without a confusing rename here."""

    buildings: list[Building] = field(default_factory=list)
    _next_id: int = 0

    # --- queries -------------------------------------------------------------

    def at(self, x: int, y: int) -> Building | None:
        for building in self.buildings:
            if building.x == x and building.y == y:
                return building
        return None

    # --- construction ------------------------------------------------------

    def start_construction(self, x: int, y: int) -> Building:
        building = Building(id=self._next_id, x=x, y=y)
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
        return {
            "total": len(self.buildings),
            "under_construction": under_construction,
            "standing": len(standing),
            "ruined": ruined,
            "avg_condition": round(avg_condition, 3),
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "buildings": [b.to_dict() for b in self.buildings],
            "next_id": self._next_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Settlement":
        buildings = [Building.from_dict(b) for b in data["buildings"]]
        return cls(buildings=buildings, _next_id=data["next_id"])
