"""Roads: foot-traffic-driven path wear between frequently-visited tiles.

Presence-driven and decaying, mirroring `settlement/buildings.py`'s
construction/decay mechanic: a walkable, unoccupied (no building, no
farm) tile that sees regular agent traffic slowly wears into an
established path, which agents then move across faster; an abandoned
path fades back to untouched terrain. Closes the "infrastructure" gap in
the original feature list, and gives future systems (culture, trade,
wildlife-avoidance) something spatial to react to besides raw tile
biome. See docs/DECISIONS.md, C5.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ROAD_WEAR_PER_TICK = 0.01
"""Wear gained by a qualifying tile each tick at least one awake agent
stands on it — ~50 ticks of regular traffic to reach
ROAD_ESTABLISHED_WEAR from bare ground."""

ROAD_DECAY_PER_TICK = 0.0008
"""Wear lost per tick a previously-worn tile sees no agent presence —
deliberately slower than the gain rate (a path needs sustained
abandonment, not a momentarily empty tick, to fade) and slower than
DECAY_PER_TICK_BASE for buildings: a dirt path outlasts a neglected
structure."""

ROAD_ESTABLISHED_WEAR = 0.5
"""Wear at or above which a tile counts as an established road — see
ROAD_SPEED_MULTIPLIER."""

ROAD_SPEED_MULTIPLIER = 1.4
"""Random-walk move-chance multiplier for an agent currently standing on
an established road tile — worn paths are faster to cross than open
terrain. Applied in Population._maybe_move."""


@dataclass
class RoadNetwork:
    wear: dict[tuple[int, int], float] = field(default_factory=dict)

    # --- queries -------------------------------------------------------------

    def wear_at(self, x: int, y: int) -> float:
        return self.wear.get((x, y), 0.0)

    def is_road(self, x: int, y: int) -> bool:
        return self.wear_at(x, y) >= ROAD_ESTABLISHED_WEAR

    # --- tick ------------------------------------------------------------------

    def tick(self, occupied_tiles: set[tuple[int, int]]) -> None:
        """`occupied_tiles` are walkable, building-free, farm-free tiles
        with at least one awake agent present this tick — see
        Population.tick for the filtering."""
        for pos in occupied_tiles:
            self.wear[pos] = min(1.0, self.wear.get(pos, 0.0) + ROAD_WEAR_PER_TICK)
        for pos in list(self.wear):
            if pos in occupied_tiles:
                continue
            remaining = self.wear[pos] - ROAD_DECAY_PER_TICK
            if remaining <= 0:
                del self.wear[pos]
            else:
                self.wear[pos] = remaining

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        established = sum(1 for w in self.wear.values() if w >= ROAD_ESTABLISHED_WEAR)
        return {"worn_tiles": len(self.wear), "established_roads": established}

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {"wear": [[x, y, round(w, 4)] for (x, y), w in self.wear.items()]}

    @classmethod
    def from_dict(cls, data: dict) -> "RoadNetwork":
        wear = {(x, y): w for x, y, w in data.get("wear", [])}
        return cls(wear=wear)
