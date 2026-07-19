"""Terrain evolution: local activity-driven biome change, and slow
map-wide climate/biome drift.

Two independent mechanisms, both requested together ("both 1 and 2" —
local activity-driven change AND longer-term climate/biome drift):

1. **Local, activity-driven change** — checked every tick. Sustained
   heavy GATHER presence on a forest tile thins it to grassland
   (deforestation); an abandoned grassland tile next to existing forest
   can slowly revert to forest (nature reclaiming), checked once per
   week (`World._tick_terrain`) since it's rare and cheap to defer that
   far without making it invisible over a normal viewing session.
2. **Climate/biome drift** — a slow, bounded random walk in a
   `warming`/`drying` bias, nudged once per month, gradually shifting a
   small sample of tiles' biomes map-wide (e.g. snowcap/mountain shrink
   under a warming trend, water recedes under a drying one).

Cadence is tied to fixed week/month boundaries rather than season/year
ones deliberately — see `World._tick_terrain`'s docstring for why.

Both skip tiles with a building/farm/vehicle on them, or an agent
currently standing there — developed or occupied land doesn't
spontaneously change biome underfoot. See docs/DECISIONS.md,
terrain-evolution pass.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from hearthmind.util import clamp
from hearthmind.world.terrain import BIOME_ORDER, Biome, Tile, classify_with_bias

try:
    from hearthmind._native import climate_drift_batch as _native_climate_drift_batch
except ImportError:
    _native_climate_drift_batch = None

try:
    from hearthmind._native import maybe_reclaim_tick as _native_maybe_reclaim_tick
except ImportError:
    _native_maybe_reclaim_tick = None
"""Optional compiled fast path for maybe_reclaim (module 17) — the
first native module using a callback-into-Python-RNG design instead of
pre-drawing, because maybe_reclaim has a genuine same-pass dependency
(an earlier reclaim in the same pass changes a later tile's forest-
neighbor count, so the roll count/order can't be determined before the
loop runs, unlike every other ported module here). The C++ loop calls
back into `rng.random` for each conditional roll, in the same order
the pure-Python loop would — preserves the dependency exactly while
still moving the neighbor-scan/branching into C++."""
"""Optional compiled fast path for apply_climate_drift's biome-step
mutation (module 16) — the first native module where a Biome enum
value crosses the boundary, done as a plain int index into BIOME_ORDER
(Python converts both ways) rather than exposing the enum itself. RNG
draws (rng.randrange for tile sampling) stay in Python; this batch call
only replaces the pure classify_with_bias + one-step-toward-target
arithmetic for tiles Python has already filtered as eligible."""

try:
    from hearthmind._native import bounded_random_walk_step as _native_bounded_random_walk_step
except ImportError:
    _native_bounded_random_walk_step = None
"""Optional compiled fast path for the bounded-random-walk step (module
12, see cpp/src/bounded_random_walk.cpp, docs/DECISIONS.md "Native
extension port"). Shared with settlement/buildings.py's tick_temperament/
tick_player_standing/tick_relation and world/hydrology.py's tick_lakes.
The RNG draw producing the jitter stays in Python. `None` when the
extension wasn't built — falls back to the equivalent pure-Python
arithmetic."""

try:
    from hearthmind._native import roll_passes_tick as _native_roll_passes_tick
except ImportError:
    _native_roll_passes_tick = None
"""Optional compiled fast path for `apply_local_activity`'s
deforestation roll (module 15, see cpp/src/roll_batch.cpp,
docs/DECISIONS.md "Native extension port"). Each candidate tile's
eligibility depends only on state that exists before the loop runs
(current heat value + biome), never on another candidate's outcome
within the same pass — unlike `maybe_reclaim` below, which does have
that cross-iteration dependency and stays pure Python. `None` when the
extension wasn't built — falls back to the equivalent pure-Python
loop in that case."""

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

MINING_SCAR_GAIN_PER_TICK = 0.006
"""Scar intensity (0..1) added to a HILLS tile per tick a GATHER-goal
agent works an ORE/mineral node there — v0.87.27, docs/IDEAS-2026-07-
EMERGENCE.md §8 ("mining should visibly pit/scar hills over time, not
just deplete an invisible ResourceNode.amount"). Deliberately visual/
cosmetic state, not a biome change: unlike deforestation, mining a
hill doesn't turn it into a different terrain type in this project's
model — it stays HILLS, walkable and re-minable, just visibly worked.
~165 ticks of continuous single-agent mining to reach full (1.0) scar."""

MINING_SCAR_DECAY_PER_WEEK = 0.05
"""Scar intensity lost per week-boundary tick a tile isn't actively
being mined — a worked-out, abandoned quarry slowly weathers/overgrows
rather than staying a permanent eyesore forever, same "nature recovers
if left alone" shape `maybe_reclaim` already gives deforestation."""

MINING_SCAR_VISIBLE_THRESHOLD = 0.35
"""Intensity at which a scar is judged worth a client-visible terrain
resync (see `apply_mining_scars`'s returned events / `TERRAIN_CHANGING_
CATEGORIES`) — below this a tile is "recently worked," not yet a real
visible scar; fired once per tile, not on every threshold-crossing
tick, so a single settlement's sustained mining doesn't spam events."""


def apply_mining_scars(
    active_mining_tiles: set[tuple[int, int]], scars: dict[tuple[int, int], float],
) -> list[tuple[str, str]]:
    """Called every tick alongside `apply_local_activity`. Mutates
    `scars` in place; returns a life event the first time a tile's scar
    crosses MINING_SCAR_VISIBLE_THRESHOLD (never fired again for that
    tile while it stays scarred — see `_scarred_announced` handling by
    the caller). No terrain/biome mutation — see MINING_SCAR_GAIN_PER_
    TICK's docstring for why this is deliberately cosmetic-only state."""
    events: list[tuple[str, str]] = []
    for pos in active_mining_tiles:
        before = scars.get(pos, 0.0)
        after = min(1.0, before + MINING_SCAR_GAIN_PER_TICK)
        scars[pos] = after
        if before < MINING_SCAR_VISIBLE_THRESHOLD <= after:
            events.append(("mining_scarred", f"A hillside at {pos} bears the visible marks of sustained mining."))
    return events


def decay_mining_scars(scars: dict[tuple[int, int], float]) -> None:
    """Called once per week (`World._tick_terrain`'s existing week_end
    gate). A tile fully weathered back to 0 is dropped from the dict —
    same "don't track what's no longer true" discipline `terrain_
    activity`'s own heat-decay-to-removal already uses."""
    for pos in list(scars.keys()):
        scars[pos] -= MINING_SCAR_DECAY_PER_WEEK
        if scars[pos] <= 0.0:
            del scars[pos]

DEFOREST_CHANCE_PER_TICK = 0.02
"""Rolled only once a tile's heat clears the threshold — deforestation
isn't instant even under sustained pressure."""

REFOREST_MIN_FOREST_NEIGHBORS = 2
REFOREST_CHANCE_PER_WEEK = 0.05
"""An abandoned grassland tile (no farm/building/vehicle/agent, no
recent activity heat) touching at least this many forest neighbors has
this chance, rolled once per week, to revert to forest — "nature
reclaims abandoned areas.\""""

CLIMATE_STEP_MAX = 0.05
CLIMATE_MEAN_REVERSION = 0.95
"""Each year, `warming`/`drying` take a small random step and decay
slightly toward 0 — a slow bounded random walk, not a runaway trend, so
a long-running world doesn't reliably freeze or flood solid."""

CLIMATE_DRIFT_SAMPLE_FRACTION = 0.03
"""Fraction of all tiles re-evaluated against the current climate bias
each month — gradual, map-wide drift rather than an instant reflow.
Slightly higher than the original per-year rate (0.02) since this now
rolls monthly rather than yearly and should still read as a visible,
if slow, change over a normal viewing session."""

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
    """Nudge the climate bias one month's worth. Mutates in place."""
    warming_jitter = rng.uniform(-CLIMATE_STEP_MAX, CLIMATE_STEP_MAX)
    drying_jitter = rng.uniform(-CLIMATE_STEP_MAX, CLIMATE_STEP_MAX)
    if _native_bounded_random_walk_step is not None:
        climate.warming = _native_bounded_random_walk_step(
            climate.warming, CLIMATE_MEAN_REVERSION, warming_jitter, 0.0, -1.0, 1.0,
        )
        climate.drying = _native_bounded_random_walk_step(
            climate.drying, CLIMATE_MEAN_REVERSION, drying_jitter, 0.0, -1.0, 1.0,
        )
        return
    climate.warming = clamp((
        climate.warming * CLIMATE_MEAN_REVERSION + warming_jitter
    ), -1.0, 1.0)
    climate.drying = clamp((
        climate.drying * CLIMATE_MEAN_REVERSION + drying_jitter
    ), -1.0, 1.0)


def _is_developed(x: int, y: int, settlements, farms, excluded: set[tuple[int, int]]) -> bool:
    """A tile agents live/work on, or are standing on right now, doesn't
    spontaneously change biome underfoot. Checks every settlement's
    structures — multi-settlement pass, v0.65.0."""
    if (x, y) in excluded:
        return True
    for settlement in settlements:
        if settlement.at(x, y) is not None or settlement.vehicle_at(x, y) is not None:
            return True
    if farms.get(x, y) is not None:
        return True
    return False


def _skip_climate_drift(tile: Tile) -> bool:
    """Biome.RIVER is carved post-generation, not elevation-classified,
    so it has no entry in BIOME_ORDER — climate drift must never sample
    it (BIOME_ORDER.index() would raise). See world/hydrology.py."""
    return tile.biome is Biome.RIVER


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

    candidates: list[tuple[int, int]] = []
    for (x, y), value in list(heat.items()):
        if value < DEFOREST_HEAT_THRESHOLD:
            continue
        tile = terrain[y][x]
        if tile.biome is not Biome.FOREST:
            del heat[(x, y)]  # already changed some other way — stop tracking
            continue
        candidates.append((x, y))

    if _native_roll_passes_tick is not None:
        # Native fast path (module 15): each candidate's eligibility
        # was already fully determined above from pre-loop state, so
        # the rolls can be pre-drawn here (same order the pure-Python
        # loop would draw them) and handed to the native comparison.
        rolls = [rng.random() for _ in candidates]
        passed = _native_roll_passes_tick(rolls, DEFOREST_CHANCE_PER_TICK)
        for (x, y), did_pass in zip(candidates, passed):
            if not did_pass:
                continue
            tile = terrain[y][x]
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
            del heat[(x, y)]
            events.append((
                "terrain_thinned",
                f"Heavy use thinned the forest at ({x}, {y}) to open grassland.",
            ))
        return events

    for (x, y) in candidates:
        if rng.random() >= DEFOREST_CHANCE_PER_TICK:
            continue
        tile = terrain[y][x]
        terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.GRASSLAND)
        del heat[(x, y)]
        events.append((
            "terrain_thinned",
            f"Heavy use thinned the forest at ({x}, {y}) to open grassland.",
        ))
    return events


def maybe_reclaim(
    terrain: list[list[Tile]], heat: dict[tuple[int, int], float],
    settlements, farms, excluded: set[tuple[int, int]], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called once per week. An abandoned grassland tile bordered by
    enough forest can revert to forest — nature reclaiming unused land,
    the inverse of `apply_local_activity`'s deforestation."""
    events: list[tuple[str, str]] = []
    height = len(terrain)
    width = len(terrain[0]) if height else 0

    if _native_maybe_reclaim_tick is not None:
        biome_codes = [
            1 if terrain[y][x].biome is Biome.GRASSLAND
            else (2 if terrain[y][x].biome is Biome.FOREST else 0)
            for y in range(height) for x in range(width)
        ]
        developed = [
            (x, y) in heat or _is_developed(x, y, settlements, farms, excluded)
            for y in range(height) for x in range(width)
        ]
        reclaimed = _native_maybe_reclaim_tick(
            width, height, biome_codes, developed,
            REFOREST_MIN_FOREST_NEIGHBORS, REFOREST_CHANCE_PER_WEEK, rng.random,
        )
        for (x, y) in reclaimed:
            tile = terrain[y][x]
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.FOREST)
            events.append((
                "terrain_reclaimed",
                f"Nature reclaimed abandoned ground at ({x}, {y}) — forest crept back in.",
            ))
        return events

    for y in range(height):
        for x in range(width):
            tile = terrain[y][x]
            if tile.biome is not Biome.GRASSLAND:
                continue
            if (x, y) in heat or _is_developed(x, y, settlements, farms, excluded):
                continue
            forest_neighbors = 0
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and terrain[ny][nx].biome is Biome.FOREST:
                    forest_neighbors += 1
            if forest_neighbors < REFOREST_MIN_FOREST_NEIGHBORS:
                continue
            if rng.random() >= REFOREST_CHANCE_PER_WEEK:
                continue
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.FOREST)
            events.append((
                "terrain_reclaimed",
                f"Nature reclaimed abandoned ground at ({x}, {y}) — forest crept back in.",
            ))
    return events


def apply_climate_drift(
    terrain: list[list[Tile]], climate: ClimateState,
    settlements, farms, excluded: set[tuple[int, int]], rng: random.Random,
) -> list[tuple[str, str]]:
    """Called once per month. Re-evaluates a small random sample of tiles
    against the current climate bias and nudges each one biome-step
    (not a full jump) toward whatever biome its elevation now maps to,
    so the map-wide drift reads as gradual over many years."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    total = width * height
    if total == 0:
        return []
    sample_size = max(1, int(total * CLIMATE_DRIFT_SAMPLE_FRACTION))
    # sample_size is fixed before the loop starts (doesn't depend on any
    # in-loop outcome), so the rng.randrange draws stay a plain, safe
    # Python pass regardless of which tiles end up eligible.
    sampled: list[tuple[int, int]] = []
    for _ in range(sample_size):
        x, y = rng.randrange(width), rng.randrange(height)
        if _is_developed(x, y, settlements, farms, excluded):
            continue
        tile = terrain[y][x]
        if _skip_climate_drift(tile):
            continue
        sampled.append((x, y))

    changed = 0
    if _native_climate_drift_batch is not None:
        # Genuine same-pass dependency, caught by A/B verification (not
        # assumed up front): `sampled` can contain the same (x, y) twice
        # — rng.randrange draws with replacement, so a tile can be
        # sampled more than once in one call. The pure-Python original
        # mutates `terrain` in place as it goes, so a duplicate's second
        # occurrence reads the tile's *already-stepped* biome from the
        # first — one native call per sample (not one batched call over
        # `sampled` as a whole) preserves that by always reading current
        # terrain state each iteration. Still zero RNG in the native
        # call itself; this is purely about read-your-own-writes order.
        for (x, y) in sampled:
            tile = terrain[y][x]
            entry = [(tile.elevation, BIOME_ORDER.index(tile.biome))]
            result = _native_climate_drift_batch(entry, climate.warming, climate.drying)[0]
            if not result.changed:
                continue
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=BIOME_ORDER[result.new_biome_idx])
            changed += 1
    else:
        for (x, y) in sampled:
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
