"""Terrain evolution: local activity-driven biome change, and slow
map-wide climate/biome drift.

Two independent mechanisms, both requested together ("both 1 and 2" —
local activity-driven change AND longer-term climate/biome drift):

1. **Local, activity-driven change** — checked every tick. Sustained
   heavy GATHER presence on a forest tile thins it to grassland
   (deforestation); an abandoned grassland tile next to existing forest
   can slowly revert to forest (nature reclaiming), checked once per
   season since it's rare and cheap to defer that far.
2. **Climate/biome drift** — a slow, bounded random walk in a
   `warming`/`drying` bias, nudged once per year, gradually shifting a
   small sample of tiles' biomes map-wide (e.g. snowcap/mountain shrink
   under a warming trend, water recedes under a drying one).

Both skip tiles with a building/farm/vehicle on them, or an agent
currently standing there — developed or occupied land doesn't
spontaneously change biome underfoot. See docs/DECISIONS.md,
terrain-evolution pass.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from hearthmind.world.terrain import BIOME_ORDER, Biome, Tile, classify_with_bias

DEFOREST_HEAT_GAIN = 0.01
"""Activity heat added to a forest tile per tick a GATHER-goal agent is
present on it."""

DEFOREST_HEAT_DECAY = 0.003
"""Heat lost per tick a tracked tile has nobody gathering on it — heat
is a sustained-pressure signal, not a single-tick trigger, so a tile
visited only occasionally recovers rather than accumulating forever."""

DEFOREST_HEAT_THRESHOLD = 1.0
"""Heat level at which a forest tile becomes eligible to thin —
roughly 100 ticks of continuous single-agent gathering at the gain rate
above, longer if intermittent (decay eats into it between visits)."""

DEFOREST_CHANCE_PER_TICK = 0.02
"""Rolled only once a tile's heat clears the threshold — deforestation
isn't instant even under sustained pressure."""

REFOREST_MIN_FOREST_NEIGHBORS = 2
REFOREST_CHANCE_PER_SEASON = 0.05
"""An abandoned grassland tile (no farm/building/vehicle/agent, no
recent activity heat) touching at least this many forest neighbors has
this chance, rolled once per season, to revert to forest — "nature
reclaims abandoned areas.\""""

CLIMATE_STEP_MAX = 0.05
CLIMATE_MEAN_REVERSION = 0.95
"""Each year, `warming`/`drying` take a small random step and decay
slightly toward 0 — a slow bounded random walk, not a runaway trend, so
a long-running world doesn't reliably freeze or flood solid."""

CLIMATE_DRIFT_SAMPLE_FRACTION = 0.02
"""Fraction of all tiles re-evaluated against the current climate bias
each year — gradual, map-wide drift rather than an instant reflow."""

CLIMATE_TREND_REPORT_THRESHOLD = 0.05
"""|warming| below this reports as "shifting" rather than a directional
trend — avoids describing meaningless noise near zero as a real trend."""


@dataclass
class ClimateState:
    warming: float = 0.0
    """-1 (cooling trend) .. 1 (warming trend) — shrinks/expands the
    cold biomes (mountain/snowcap) via `classify_with_bias`."""
    drying: float = 0.0
    """-1 (wetting trend) .. 1 (drying trend) — shrinks/expands the
    water biomes and forest's lower edge."""

    def to_dict(self) -> dict:
        return {"warming": round(self.warming, 4), "drying": round(self.drying, 4)}

    @classmethod
    def from_dict(cls, data: dict) -> "ClimateState":
        return cls(warming=data.get("warming", 0.0), drying=data.get("drying", 0.0))


def tick_climate(climate: ClimateState, rng: random.Random) -> None:
    """Nudge the climate bias one year's worth. Mutates in place."""
    climate.warming = max(-1.0, min(1.0, (
        climate.warming * CLIMATE_MEAN_REVERSION + rng.uniform(-CLIMATE_STEP_MAX, CLIMATE_STEP_MAX)
    )))
    climate.drying = max(-1.0, min(1.0, (
        climate.drying * CLIMATE_MEAN_REVERSION + rng.uniform(-CLIMATE_STEP_MAX, CLIMATE_STEP_MAX)
    )))


def _is_developed(x: int, y: int, settlement, farms, excluded: set[tuple[int, int]]) -> bool:
    """A tile agents live/work on, or are standing on right now, doesn't
    spontaneously change biome underfoot."""
    if (x, y) in excluded:
        return True
    if settlement.at(x, y) is not None or settlement.vehicle_at(x, y) is not None:
        return True
    if farms.get(x, y) is not None:
        return True
    return False


def apply_local_activity(
    terrain: list[list[Tile]], active_forest_tiles: set[tuple[int, int]],
    heat: dict[tuple[int, int], float], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called every tick. Decays heat everywhere it's tracked, adds heat
    at `active_forest_tiles`, and rolls deforestation for any tile whose
    heat clears the threshold. Mutates `terrain`/`heat` in place."""
    events: list[tuple[str, str]] = []

    for pos in active_forest_tiles:
        heat[pos] = min(DEFOREST_HEAT_THRESHOLD * 2, heat.get(pos, 0.0) + DEFOREST_HEAT_GAIN)
    for pos in list(heat.keys()):
        if pos in active_forest_tiles:
            continue
        heat[pos] -= DEFOREST_HEAT_DECAY
        if heat[pos] <= 0.0:
            del heat[pos]

    for (x, y), value in list(heat.items()):
        if value < DEFOREST_HEAT_THRESHOLD:
            continue
        tile = terrain[y][x]
        if tile.biome is not Biome.FOREST:
            del heat[(x, y)]  # already changed some other way — stop tracking
            continue
        if rng.random() >= DEFOREST_CHANCE_PER_TICK:
            continue
        terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
        del heat[(x, y)]
        events.append((
            "terrain_thinned",
            f"Heavy use thinned the forest at ({x}, {y}) to open grassland.",
        ))
    return events


def maybe_reclaim(
    terrain: list[list[Tile]], heat: dict[tuple[int, int], float],
    settlement, farms, excluded: set[tuple[int, int]], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called once per season. An abandoned grassland tile bordered by
    enough forest can revert to forest — nature reclaiming unused land,
    the inverse of `apply_local_activity`'s deforestation."""
    events: list[tuple[str, str]] = []
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    for y in range(height):
        for x in range(width):
            tile = terrain[y][x]
            if tile.biome is not Biome.GRASSLAND:
                continue
            if (x, y) in heat or _is_developed(x, y, settlement, farms, excluded):
                continue
            forest_neighbors = 0
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and terrain[ny][nx].biome is Biome.FOREST:
                    forest_neighbors += 1
            if forest_neighbors < REFOREST_MIN_FOREST_NEIGHBORS:
                continue
            if rng.random() >= REFOREST_CHANCE_PER_SEASON:
                continue
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.FOREST)
            events.append((
                "terrain_reclaimed",
                f"Nature reclaimed abandoned ground at ({x}, {y}) — forest crept back in.",
            ))
    return events


def apply_climate_drift(
    terrain: list[list[Tile]], climate: ClimateState,
    settlement, farms, excluded: set[tuple[int, int]], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called once per year. Re-evaluates a small random sample of tiles
    against the current climate bias and nudges each one biome-step
    (not a full jump) toward whatever biome its elevation now maps to,
    so the map-wide drift reads as gradual over many years."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    total = width * height
    if total == 0:
        return []
    sample_size = max(1, int(total * CLIMATE_DRIFT_SAMPLE_FRACTION))
    changed = 0
    for _ in range(sample_size):
        x, y = rng.randrange(width), rng.randrange(height)
        if _is_developed(x, y, settlement, farms, excluded):
            continue
        tile = terrain[y][x]
        target = classify_with_bias(tile.elevation, climate.warming, climate.drying)
        if target is tile.biome:
            continue
        cur_idx = BIOME_ORDER.index(tile.biome)
        tgt_idx = BIOME_ORDER.index(target)
        step = 1 if tgt_idx > cur_idx else -1
        new_biome = BIOME_ORDER[cur_idx + step]
        terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=new_biome)
        changed += 1
    if changed == 0:
        return []
    if climate.warming > CLIMATE_TREND_REPORT_THRESHOLD:
        trend = "warming"
    elif climate.warming < -CLIMATE_TREND_REPORT_THRESHOLD:
        trend = "cooling"
    else:
        trend = "shifting"
    return [(
        "climate_drift",
        f"The climate is gradually {trend} — {changed} tile{'s' if changed != 1 else ''} "
        f"shifted biome this year.",
    )]
