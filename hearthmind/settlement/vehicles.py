"""Vehicles: hauling carts and personal-travel mounts.

Built from settlement materials at a colocated worksite the same way
buildings are (see buildings.py), and weather/repair the same way too —
carts speed the settlement's material hauling (a multiplier on gathered
yield), mounts speed one rider's own movement. Both wear down with use on
top of ordinary weathering and stop contributing once broken, until
repaired. See docs/DECISIONS.md, vehicles pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VehicleKind(str, Enum):
    CART = "cart"
    """Settlement-wide: each ready cart speeds hauling of gathered
    materials back to the stockpile — a multiplier on
    Population._maybe_gather's yield, stacking up to CART_BONUS_CAP."""
    MOUNT = "mount"
    """Personal: an awake agent colocated with a ready, unclaimed mount
    claims it and moves faster (like a personal road) for as long as
    they keep it in good repair."""


class VehicleStage(str, Enum):
    BUILDING = "building"
    READY = "ready"
    BROKEN = "broken"
    """Condition hit zero — inert (no haul bonus, no speed bonus, a mount
    immediately unassigns its rider) until repaired back above
    VEHICLE_REPAIR_THRESHOLD, unlike a ruined building it isn't lost."""


CART_MATERIALS_COST = 4.0
MOUNT_MATERIALS_COST = 6.0
"""Costlier than a hut (HUT_MATERIALS_COST=3.0 in buildings.py): a mount
is a bigger investment than shelter, matching its bigger per-agent payoff."""

VEHICLE_CONSTRUCTION_WORK_PER_TICK = 0.05
VEHICLE_MAX_WORKERS = 3
"""Same cadence as CONSTRUCTION_WORK_PER_TICK/MAX_WORKERS in
buildings.py — vehicles are built the same way buildings are."""

VEHICLE_CHANCE_PER_TICK = 0.004
"""Rolled only once a settlement is named (a vehicle presupposes an
existing community) for a colocated, mature, healthy pair — rarer than
SETTLE_CHANCE_PER_TICK (0.01): buildings stay the priority, vehicles a
later refinement."""

VEHICLE_REPAIR_THRESHOLD = 0.5
VEHICLE_REPAIR_WORK_PER_TICK = 0.03

VEHICLE_DECAY_PER_TICK_BASE = 0.0003
VEHICLE_DECAY_WEATHER_MULTIPLIER = 2.0
"""Milder than a building's DECAY_WEATHER_MULTIPLIER (3.0) — a vehicle
isn't a fixed structure exposed to the elements the same way."""

MOUNT_USE_DECAY = 0.002
"""Extra condition lost on a tick a mount actually carries its rider an
extra step — wear from use, on top of passive weather decay."""

CART_USE_DECAY = 0.0015
"""Extra condition lost, spread across all currently-ready carts, on any
tick at least one cart's haul bonus was actually applied."""

CART_HAUL_BONUS_PER_CART = 0.25
CART_BONUS_CAP = 3
"""Each ready cart adds 25% to gathered-material yield, up to 3 carts
(+75%) — a hard ceiling since, unlike inventions, carts are buildable at
will and shouldn't compound without limit."""

MOUNT_SPEED_MULTIPLIER = 1.6
"""Slightly better than ROAD_SPEED_MULTIPLIER (1.4, world/roads.py) and
stacks with it — a mounted agent on a road is faster still."""


@dataclass
class Vehicle:
    id: int
    x: int
    y: int
    kind: VehicleKind = VehicleKind.CART
    stage: VehicleStage = VehicleStage.BUILDING
    progress: float = 0.0
    """0..1, meaningful while BUILDING."""
    condition: float = 1.0
    """0..1, meaningful while READY (and while decaying toward BROKEN)."""
    assigned_agent_id: int | None = None
    """Meaningful only for MOUNT — the agent currently riding it."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "kind": self.kind.value,
            "stage": self.stage.value,
            "progress": round(self.progress, 4),
            "condition": round(self.condition, 4),
            "assigned_agent_id": self.assigned_agent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Vehicle":
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            kind=VehicleKind(data.get("kind", VehicleKind.CART.value)),
            stage=VehicleStage(data.get("stage", VehicleStage.BUILDING.value)),
            progress=data.get("progress", 0.0),
            condition=data.get("condition", 1.0),
            assigned_agent_id=data.get("assigned_agent_id"),
        )
