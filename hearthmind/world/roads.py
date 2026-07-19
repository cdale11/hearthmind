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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hearthmind.world.weather import WeatherState

try:
    from hearthmind._native import road_wear_gain_step as _native_road_wear_gain_step
    from hearthmind._native import road_wear_decay_step as _native_road_wear_decay_step
except ImportError:
    _native_road_wear_gain_step = None
    _native_road_wear_decay_step = None
"""Optional compiled fast path for RoadNetwork.tick's per-tile scalar
wear math (see cpp/src/road_wear.cpp). The sparse tile->wear dict
iteration and prune-on-fade-to-zero deletion stay in Python; only the
per-tile gain/decay arithmetic moves. `None` when the extension wasn't
built."""

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
"""Random-walk move-chance multiplier for an agent on an established
road tile in clear/dry weather — worn paths are faster to cross than
open terrain. See `road_condition_multiplier` for how weather changes
this. Applied in Population._maybe_move."""

ROAD_MUDDY_MULTIPLIER = 1.1
"""Heavy rain turns an established road to mud — still better than open
ground, much less of a bonus than dry-weather ROAD_SPEED_MULTIPLIER."""

ROAD_SNOWY_MULTIPLIER = 0.9
"""Snow cover on a road actually costs a little speed versus open
terrain (drifts, poor footing) — below 1.0, unlike mud."""

ROAD_ICY_MULTIPLIER = 0.75
"""Freezing weather (snowing at or below this module's ice threshold)
makes an established road the most hazardous surface to be moving on —
the lowest multiplier of the four conditions."""

ROAD_ICE_TEMPERATURE_C = -3.0
"""Snowing at or below this temperature counts as icy rather than just
snowy — see `road_condition_multiplier`."""

ROAD_PAVED_WEAR = 0.85
"""v0.87.43 era-scaled-infrastructure batch (live report: "improve
building/road/infrastructure types with era"): a second, higher wear
threshold above ROAD_ESTABLISHED_WEAR (0.5) — a well-worn path that
sees SUSTAINED heavy traffic (not just enough to count as "established")
can pave into a real road, gated by `paving_unlocked` (see
`RoadNetwork.tick`). Roads are shared physical infrastructure, not
settlement-private (same "anyone can use it" shape BRIDGE already has),
so paving is a world-wide capability, not per-settlement."""

ROAD_PAVED_SPEED_MULTIPLIER = 1.7
"""Better than ROAD_SPEED_MULTIPLIER's dry-weather 1.4 — a genuinely
paved surface, the concrete payoff for era progression this batch adds
(mirrors AUTOMOBILE_SPEED_MULTIPLIER > MOUNT_SPEED_MULTIPLIER's shape:
era-appropriate infrastructure measurably beats the earlier tier, not
just reads as a label change)."""

ROAD_PAVED_MUDDY_MULTIPLIER = 1.5
ROAD_PAVED_SNOWY_MULTIPLIER = 1.1
ROAD_PAVED_ICY_MULTIPLIER = 0.9
"""Paved-road weather bands, each better than its dirt-road counterpart
by the same proportional margin ROAD_PAVED_SPEED_MULTIPLIER has over
ROAD_SPEED_MULTIPLIER in dry weather — a paved surface is more weather-
resistant, not immune to it."""


def road_condition_multiplier(weather: "WeatherState", paved: bool = False) -> float:
    """Weather affects infrastructure, not just people/crops: an
    established road's speed bonus depends on current conditions rather
    than being a flat constant. See docs/DECISIONS.md, "LLM-as-brain
    batch." `paved` (v0.87.43): a tile at/above ROAD_PAVED_WEAR while
    paving is world-unlocked reads the paved band instead."""
    if weather.is_snowing:
        if weather.temperature_c <= ROAD_ICE_TEMPERATURE_C:
            return ROAD_PAVED_ICY_MULTIPLIER if paved else ROAD_ICY_MULTIPLIER
        return ROAD_PAVED_SNOWY_MULTIPLIER if paved else ROAD_SNOWY_MULTIPLIER
    if weather.precipitation > 0.4:
        return ROAD_PAVED_MUDDY_MULTIPLIER if paved else ROAD_MUDDY_MULTIPLIER
    return ROAD_PAVED_SPEED_MULTIPLIER if paved else ROAD_SPEED_MULTIPLIER


@dataclass
class RoadNetwork:
    wear: dict[tuple[int, int], float] = field(default_factory=dict)
    paving_unlocked: bool = False
    """v0.87.43: True once any settlement in the world has reached era
    `modern` or `digital` — set each tick by `tick()`'s new parameter,
    not persisted-meaningful on its own (recomputed from live settlement
    state every tick the same way `mountain_unlocked` is, so a stale
    value on load is immediately overwritten before it's ever read)."""

    # --- queries -------------------------------------------------------------

    def wear_at(self, x: int, y: int) -> float:
        return self.wear.get((x, y), 0.0)

    def is_road(self, x: int, y: int) -> bool:
        return self.wear_at(x, y) >= ROAD_ESTABLISHED_WEAR

    def is_paved(self, x: int, y: int) -> bool:
        """v0.87.43: a genuinely paved road tile — ROAD_PAVED_WEAR of
        sustained traffic AND the world has unlocked paving (any
        settlement at `modern`+). See `road_condition_multiplier`."""
        return self.paving_unlocked and self.wear_at(x, y) >= ROAD_PAVED_WEAR

    # --- tick ------------------------------------------------------------------

    def tick(self, occupied_tiles: set[tuple[int, int]], paving_unlocked: bool = False) -> None:
        """`occupied_tiles` are walkable, building-free, farm-free tiles
        with at least one awake agent present this tick — see
        Population.tick for the filtering. `paving_unlocked` (v0.87.43):
        whether any settlement has reached the era that unlocks the
        paved road tier — see `Population._update_roads`."""
        self.paving_unlocked = paving_unlocked
        if _native_road_wear_gain_step is not None:
            for pos in occupied_tiles:
                self.wear[pos] = _native_road_wear_gain_step(self.wear.get(pos, 0.0), ROAD_WEAR_PER_TICK)
            for pos in list(self.wear):
                if pos in occupied_tiles:
                    continue
                remaining = _native_road_wear_decay_step(self.wear[pos], ROAD_DECAY_PER_TICK)
                if remaining <= 0:
                    del self.wear[pos]
                else:
                    self.wear[pos] = remaining
            return
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

    def summary(self, weather: "WeatherState | None" = None) -> dict:
        established = sum(1 for w in self.wear.values() if w >= ROAD_ESTABLISHED_WEAR)
        paved = sum(1 for w in self.wear.values() if w >= ROAD_PAVED_WEAR) if self.paving_unlocked else 0
        result = {
            "worn_tiles": len(self.wear), "established_roads": established,
            "paved_roads": paved, "paving_unlocked": self.paving_unlocked,
        }
        if weather is not None:
            multiplier = road_condition_multiplier(weather)
            if multiplier >= ROAD_SPEED_MULTIPLIER:
                condition = "dry"
            elif multiplier >= ROAD_MUDDY_MULTIPLIER:
                condition = "muddy"
            elif multiplier >= ROAD_SNOWY_MULTIPLIER:
                condition = "snowy"
            else:
                condition = "icy"
            result["condition"] = condition
            result["speed_multiplier"] = round(multiplier, 2)
        return result

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {"wear": [[x, y, round(w, 4)] for (x, y), w in self.wear.items()]}

    @classmethod
    def from_dict(cls, data: dict) -> "RoadNetwork":
        wear = {(x, y): w for x, y, w in data.get("wear", [])}
        return cls(wear=wear)
