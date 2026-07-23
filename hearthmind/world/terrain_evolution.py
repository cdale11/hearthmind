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
from hearthmind.world.ca_operators import diffuse
from hearthmind.world.terrain import BIOME_ORDER, Biome, Tile, classify_with_bias

try:
    from hearthmind._native import climate_drift_batch as _native_climate_drift_batch
except ImportError:
    _native_climate_drift_batch = None

try:
    from hearthmind._native import (
        mining_scar_decay_step as _native_mining_scar_decay_step,
        mining_scar_gain_step as _native_mining_scar_gain_step,
    )
except ImportError:
    _native_mining_scar_gain_step = None
    _native_mining_scar_decay_step = None
"""Optional compiled fast path for apply_mining_scars/decay_mining_scars'
per-tile scalar step — v1 audit fix, see cpp/src/mining_scars.cpp. Same
"dict iteration + event bookkeeping stays Python, only the scalar step
moves to C++" shape as road_wear.py/farms.py's native pairs. `None`
when the extension wasn't built — falls back to equivalent pure-Python
arithmetic in that case."""

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
        after = (
            _native_mining_scar_gain_step(before, MINING_SCAR_GAIN_PER_TICK)
            if _native_mining_scar_gain_step is not None
            else min(1.0, before + MINING_SCAR_GAIN_PER_TICK)
        )
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
        scars[pos] = (
            _native_mining_scar_decay_step(scars[pos], MINING_SCAR_DECAY_PER_WEEK)
            if _native_mining_scar_decay_step is not None
            else scars[pos] - MINING_SCAR_DECAY_PER_WEEK
        )
        if scars[pos] <= 0.0:
            del scars[pos]


DISASTER_SCAR_GAIN_PER_HIT = 0.2
"""Phase 3.D "permanent landscape scars from disasters" (docs/VISION-
2026-07-21-SELFEVOLVING.md), direct physical extension of 1.D's
psychology-side scarring: a tile actively flooded or actively burning
THIS tick gains scar intensity — a single disaster leaves a visible but
minor mark, ~5 repeated hits (the same tile struck across several
separate disaster events, not necessarily consecutive ticks — flood/
wildfire already only persist a handful of ticks each) reaches full
(1.0) scarring. Deliberately per-DISASTER-TICK, not per-hit-event, same
"sustained pressure, not a single roll" shape MINING_SCAR_GAIN_PER_TICK
already uses."""

DISASTER_SCAR_DECAY_PER_WEEK = 0.04
"""Slightly slower recovery than a worked-out mine (MINING_SCAR_DECAY_
PER_WEEK) — scorched/flood-scoured ground plausibly takes a little
longer to visibly recover than an abandoned quarry."""

DISASTER_SCAR_VISIBLE_THRESHOLD = 0.35
"""Same role as MINING_SCAR_VISIBLE_THRESHOLD — fired once per tile
crossing this, not on every threshold-crossing tick."""

NATURE_ADAPTATION_DECAY_BONUS_MAX = 0.5
"""Vision doc item 2.1, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("Nature acts on its Mind, not just narrates it") — the max fractional
speed-up `decay_disaster_scars` grants once Nature's Mind holds a
confident belief about repeated fire/flood damage: "a forest learning
to reclaim burned land differently after repeated fires," bounded
adaptation DIRECTED BY Nature's own accumulated experience (the
belief `llm/nature_mind.py` forms, grounded only in Nature's Body
state) rather than a raw random walk. Deliberately modest — this
nudges an existing rate, it doesn't rewrite ecology; not natively
ported (see `apply_disaster_scars`'s own R7-deviation note), so this
stays pure Python with no native-parity risk."""

_NATURE_ADAPTATION_SUBJECT_KEYWORDS = ("fire", "flood", "disaster", "scar", "burn")


def nature_adaptation_bias(nature_beliefs: list[dict]) -> float:
    """The confidence (0..1) of Nature's single strongest held belief
    whose subject concerns repeated disaster damage, or 0.0 if it
    holds none — see `NATURE_ADAPTATION_DECAY_BONUS_MAX`. The belief
    TEXT is LLM-authored (`nature_mind.py`); reading it here to bias a
    real deterministic rate is not — same "closed-vocabulary-hosting-
    open-content" discipline as everywhere else the LLM's output feeds
    a real number in this codebase."""
    best = 0.0
    for belief in nature_beliefs:
        subject = str(belief.get("subject", "")).lower()
        if any(kw in subject for kw in _NATURE_ADAPTATION_SUBJECT_KEYWORDS):
            best = max(best, float(belief.get("confidence", 0.0)))
    return best


def apply_disaster_scars(
    flooded_tiles: dict, active_wildfire_tiles: set, scars: dict[tuple[int, int], float],
) -> list[tuple[str, str]]:
    """Called every tick from `World._tick_terrain`, alongside `apply_
    mining_scars` — same shape, same R7 deviation rationale (Python not
    C++: a low-density tile-scalar-step lookup, not yet worth a native
    port; see MINING_SCAR's own docstring for the precedent). No
    terrain/biome mutation — cosmetic-only, same as mining scars; a
    scarred tile stays its normal biome, walkable, re-scarrable."""
    events: list[tuple[str, str]] = []
    hit_tiles = set(flooded_tiles) | active_wildfire_tiles
    for pos in hit_tiles:
        before = scars.get(pos, 0.0)
        after = min(1.0, before + DISASTER_SCAR_GAIN_PER_HIT)
        scars[pos] = after
        if before < DISASTER_SCAR_VISIBLE_THRESHOLD <= after:
            events.append((
                "disaster_scarred", f"The land at {pos} bears lasting scars from repeated disasters.",
            ))
    return events


def decay_disaster_scars(scars: dict[tuple[int, int], float], adaptation_bias: float = 0.0) -> None:
    """Called once per week, same cadence as `decay_mining_scars`.
    `adaptation_bias` (0..1, see `nature_adaptation_bias`) speeds up
    decay up to `NATURE_ADAPTATION_DECAY_BONUS_MAX` extra fraction —
    Nature's own accumulated belief about repeated disaster damage
    directing how fast the land recovers, vision doc item 2.1."""
    rate = DISASTER_SCAR_DECAY_PER_WEEK * (1.0 + adaptation_bias * NATURE_ADAPTATION_DECAY_BONUS_MAX)
    for pos in list(scars.keys()):
        scars[pos] -= rate
        if scars[pos] <= 0.0:
            del scars[pos]


RITUAL_ACTIVITY_GAIN_PER_FESTIVAL = 0.15
"""A19 "Persistent spatial memory," first slice (roadmap Stage IV step
26, docs/MASTERCHECKLIST-2026-07-22.md): intensity (0..1) a tile gains
each time a shrine-boosted festival gathering happens there
(`Population.hold_festival`) — a handful of festivals at the same
shrine builds real accumulated significance, same order of magnitude
as `DISASTER_SCAR_GAIN_PER_HIT`."""

RITUAL_ACTIVITY_DECAY_PER_WEEK = 0.01
"""Slower than `MINING_SCAR_DECAY_PER_WEEK`/`DISASTER_SCAR_DECAY_PER_
WEEK` — a site's sacred standing plausibly outlasts a worked-out
quarry or a scorched field; still bounded, not permanent."""

RITUAL_ACTIVITY_BOOST_SCALE = 0.5
"""`Population.hold_festival`'s worked example of A19's spec ("a
ritual site draws ritual"): a tile at full accumulated activity
(1.0) makes its own festival boost up to this fraction stronger —
scoped to a magnitude effect (the doc's literal "draws ritual" read
as attracting movement is out of scope; see `world/reactions.py`'s
similarly-scoped A18 slice for the same discipline)."""


def apply_ritual_activity(pos: tuple[int, int], activity: dict[tuple[int, int], float]) -> None:
    """Called from `Population.hold_festival` the instant a shrine-
    boosted gathering happens at `pos` — mutates `activity` in place,
    same shape as `apply_mining_scars`/`apply_disaster_scars`."""
    activity[pos] = min(1.0, activity.get(pos, 0.0) + RITUAL_ACTIVITY_GAIN_PER_FESTIVAL)


def decay_ritual_activity(activity: dict[tuple[int, int], float]) -> None:
    """Called once per week, same cadence as `decay_mining_scars`/
    `decay_disaster_scars`."""
    for pos in list(activity.keys()):
        activity[pos] -= RITUAL_ACTIVITY_DECAY_PER_WEEK
        if activity[pos] <= 0.0:
            del activity[pos]


DEFOREST_CHANCE_PER_TICK = 0.02
"""Rolled only once a tile's heat clears the threshold — deforestation
isn't instant even under sustained pressure."""

REFOREST_MIN_FOREST_NEIGHBORS = 2
REFOREST_CHANCE_PER_WEEK = 0.05
"""An abandoned grassland tile (no farm/building/vehicle/agent, no
recent activity heat) touching at least this many forest neighbors has
this chance, rolled once per week, to revert to forest — "nature
reclaims abandoned areas.\""""

REFOREST_MIN_FALLOW_WEEKS = 3
"""Phase 3.D "succession — real intermediate stages, not an instant
biome flip" (docs/VISION-2026-07-21-SELFEVOLVING.md). Previously a
qualifying tile could revert to forest the very first week it became
eligible; now it must qualify (undeveloped, enough forest neighbors)
for this many CONSECUTIVE weeks before the reforest roll is even
attempted — a visible fallow period reads as gradual regrowth rather
than land snapping to forest the week the farmer walks away. Tracked
in `World.fallow_ticks`, the same additive Python-dict-overlay shape
as `mining_scars`/`disaster_scars` (R7 deviation: a low-density weekly
tile scan, not yet worth a native port) — a tile that stops qualifying
resets to 0 rather than merely pausing, so an interrupted fallow period
doesn't bank progress."""

SUCCESSION_FOREST_DIFFUSE_RATE = 0.6
"""A2 "CA / diffusion / reaction-diffusion operators" (roadmap Stage IV
step 16), forest succession as the worked first consumer: how strongly
`compute_succession_pressure` smooths the raw 0/1 forest-tile indicator
grid via `ca_operators.diffuse` before reading it — a genuine "how
forested is my neighborhood" reading (not just a 4-neighbor count),
composed as one operator call per week."""

SUCCESSION_WEEKS_MIN = 1
SUCCESSION_WEEKS_MAX_MULTIPLIER = 2.0
SUCCESSION_WEEKS_MIN_MULTIPLIER = 0.34
"""A2: bounds on how much `compute_succession_pressure` can modulate
`REFOREST_MIN_FALLOW_WEEKS` per tile — a tile with a dense, moist
forest neighborhood can reclaim in as few as `SUCCESSION_WEEKS_MIN`
weeks; a poor one (sparse forest, dry) can take up to `REFOREST_MIN_
FALLOW_WEEKS * SUCCESSION_WEEKS_MAX_MULTIPLIER`. Real, bounded
modulation of the existing tuned rate — not a wholesale replacement —
so overall reforest pacing stays in the same order of magnitude while
now genuinely responding to local conditions (det_sys.md's "gated by
... moisture")."""

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


def compute_succession_pressure(
    terrain: list[list[Tile]], moisture: list[list[float]] | None,
) -> list[list[float]] | None:
    """A2 "CA / diffusion / reaction-diffusion operators" (roadmap
    Stage IV step 16): forest succession as the worked first consumer.
    Builds a 0/1 forest-indicator grid and runs it through `ca_
    operators.diffuse` — the result is a genuine smoothed "how forested
    is my neighborhood" field, not just a 4-neighbor count — then
    averages it against the (also real, per-tile) `moisture` field from
    `world/hydrology_field.py` (A11). Returns `None` when no moisture
    field is available (a caller with legacy/absent hydrology data) so
    `_tick_fallow` can cleanly fall back to the flat, unmodulated rate."""
    if moisture is None:
        return None
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width == 0 or height == 0:
        return None
    forest_indicator = [
        [1.0 if terrain[y][x].biome is Biome.FOREST else 0.0 for x in range(width)]
        for y in range(height)
    ]
    forest_density = diffuse(forest_indicator, SUCCESSION_FOREST_DIFFUSE_RATE)
    return [
        [
            clamp((forest_density[y][x] + moisture[y][x]) / 2.0, 0.0, 1.0)
            for x in range(width)
        ]
        for y in range(height)
    ]


def _tick_fallow(
    terrain: list[list[Tile]], heat: dict[tuple[int, int], float],
    settlements, farms, excluded: set[tuple[int, int]],
    fallow_ticks: dict[tuple[int, int], int],
    succession_pressure: list[list[float]] | None = None,
) -> set[tuple[int, int]]:
    """Advances `fallow_ticks` one week and returns the set of tiles
    that have now cleared their own effective fallow requirement — the
    only tiles `maybe_reclaim` is allowed to roll for this week. A tile
    that no longer qualifies (developed, or fell below the forest-
    neighbor count) is dropped from the dict entirely rather than
    paused.

    `succession_pressure` (A2, optional): when given, a tile's
    effective threshold is `REFOREST_MIN_FALLOW_WEEKS` scaled DOWN as
    pressure rises toward 1 (a well-forested, moist neighborhood) and
    UP as it falls toward 0, bounded to [`SUCCESSION_WEEKS_MIN`,
    `REFOREST_MIN_FALLOW_WEEKS * SUCCESSION_WEEKS_MAX_MULTIPLIER`].
    `None` (or an out-of-bounds tile) keeps the original flat rate —
    existing callers/tests that don't pass this see unchanged
    behavior."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    eligible: set[tuple[int, int]] = set()
    seen: set[tuple[int, int]] = set()
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
            seen.add((x, y))
            weeks = fallow_ticks.get((x, y), 0) + 1
            fallow_ticks[(x, y)] = weeks
            required_weeks = REFOREST_MIN_FALLOW_WEEKS
            if succession_pressure is not None and 0 <= y < len(succession_pressure) and 0 <= x < len(succession_pressure[y]):
                pressure = succession_pressure[y][x]
                scale = SUCCESSION_WEEKS_MAX_MULTIPLIER - pressure * (
                    SUCCESSION_WEEKS_MAX_MULTIPLIER - SUCCESSION_WEEKS_MIN_MULTIPLIER
                )
                required_weeks = max(SUCCESSION_WEEKS_MIN, round(REFOREST_MIN_FALLOW_WEEKS * scale))
            if weeks >= required_weeks:
                eligible.add((x, y))
    for pos in list(fallow_ticks.keys()):
        if pos not in seen:
            del fallow_ticks[pos]
    return eligible


def maybe_reclaim(
    terrain: list[list[Tile]], heat: dict[tuple[int, int], float],
    settlements, farms, excluded: set[tuple[int, int]], rng: random.Random,
    fallow_ticks: dict[tuple[int, int], int],
    moisture: list[list[float]] | None = None,
) -> list[tuple[str, str]]:
    """Called once per week. An abandoned grassland tile bordered by
    enough forest, and fallow for its own effective fallow requirement
    (A2: modulated by local succession pressure when `moisture` is
    given), can revert to forest — nature reclaiming unused land, the
    inverse of `apply_local_activity`'s deforestation."""
    events: list[tuple[str, str]] = []
    height = len(terrain)
    width = len(terrain[0]) if height else 0

    succession_pressure = compute_succession_pressure(terrain, moisture)
    eligible = _tick_fallow(terrain, heat, settlements, farms, excluded, fallow_ticks, succession_pressure)
    if not eligible:
        return events

    if _native_maybe_reclaim_tick is not None:
        biome_codes = [
            1 if terrain[y][x].biome is Biome.GRASSLAND
            else (2 if terrain[y][x].biome is Biome.FOREST else 0)
            for y in range(height) for x in range(width)
        ]
        developed = [
            (x, y) not in eligible
            for y in range(height) for x in range(width)
        ]
        reclaimed = _native_maybe_reclaim_tick(
            width, height, biome_codes, developed,
            REFOREST_MIN_FOREST_NEIGHBORS, REFOREST_CHANCE_PER_WEEK, rng.random,
        )
        for (x, y) in reclaimed:
            tile = terrain[y][x]
            terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.FOREST)
            fallow_ticks.pop((x, y), None)
        events.extend(_reclaim_events(reclaimed))
        return events

    reclaimed: list[tuple[int, int]] = []
    for (x, y) in sorted(eligible, key=lambda pos: (pos[1], pos[0])):
        if rng.random() >= REFOREST_CHANCE_PER_WEEK:
            continue
        tile = terrain[y][x]
        terrain[y][x] = Tile(x=x, y=y, elevation=tile.elevation, biome=Biome.FOREST)
        fallow_ticks.pop((x, y), None)
        reclaimed.append((x, y))
    events.extend(_reclaim_events(reclaimed))
    return events


def _reclaim_events(reclaimed: list[tuple[int, int]]) -> list[tuple[str, str]]:
    """P2.3 (docs/AUDIT-2026-07-20.md): `terrain_reclaimed` was 281/16k
    events in a live run (16%) — one event per tile per week flooded
    the History tab even after P0.2(d) capped its prompt-side crowding.
    One combined line per call instead of one per tile, same UI-noise
    fix the audit describes ("batch reclaim into one ... line with a
    count") applied at the weekly cadence this function actually runs
    on rather than forcing a month-boundary rewrite."""
    if not reclaimed:
        return []
    if len(reclaimed) == 1:
        x, y = reclaimed[0]
        return [(
            "terrain_reclaimed",
            f"Nature reclaimed abandoned ground at ({x}, {y}) — forest crept back in.",
        )]
    return [(
        "terrain_reclaimed",
        f"Nature reclaimed abandoned ground at {len(reclaimed)} sites — forest crept back in.",
    )]


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
