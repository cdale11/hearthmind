"""A single inhabitant: position + a minimal needs model.

Milestone 2 scope, deliberately: agents have needs that decay and a
resting/awake state that responds to them, and they wander the walkable
terrain. There is no food source, foraging, or death yet (see
docs/DECISIONS.md, M2-2) — hunger currently only ever rises. That's an
honest gap, not an oversight: it's the next slice (agriculture/foraging)
that gives hunger something to push against.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentState(str, Enum):
    AWAKE = "awake"
    RESTING = "resting"


# Needs tuning. Kept as module constants rather than Config fields for now —
# these are behavioral parameters of the agent model itself, not world-shape
# parameters a deployer chooses at creation time. Revisit if that stops
# being true (e.g. once difficulty/pacing knobs are wanted).
HUNGER_RATE = 0.01
"""Hunger gained per tick, always (no food source yet to offset it)."""

ENERGY_DRAIN_AWAKE = 0.015
"""Energy lost per tick while awake (whether moving or not)."""

ENERGY_RECOVERY_RESTING = 0.06
"""Energy gained per tick while resting."""

REST_THRESHOLD = 0.2
"""Energy at or below which an awake agent falls asleep."""

WAKE_THRESHOLD = 0.85
"""Energy at or above which a resting agent wakes up."""

MOVE_CHANCE = 0.5
"""Per-tick probability an awake agent wanders to an adjacent tile."""


@dataclass
class Agent:
    id: int
    name: str
    x: int
    y: int
    hunger: float = 0.0
    energy: float = 1.0
    state: AgentState = AgentState.AWAKE

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "hunger": round(self.hunger, 4),
            "energy": round(self.energy, 4),
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        return cls(
            id=data["id"],
            name=data["name"],
            x=data["x"],
            y=data["y"],
            hunger=data["hunger"],
            energy=data["energy"],
            state=AgentState(data["state"]),
        )
