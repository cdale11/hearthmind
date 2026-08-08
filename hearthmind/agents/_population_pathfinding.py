"""R1 (docs/REFACTOR-2026-07.md, roadmap Phase 8): the first extracted
slice of `agents/population.py`'s planned mixin-based decomposition --
walkability/movement/target-search, "safest to move first, almost
entirely pure" per the doc's own proposed layout (every method here was
already a `@staticmethod` -- no `self`/`cls`-dependent state, zero
coupling beyond explicit parameters). `Population` picks up `Pathfinding
Mixin` as a base class (`class Population(PathfindingMixin, ...)`), so
every internal `self._x`/`cls._x` call site in `population.py` resolves
unchanged via the MRO; the four free functions below (`_is_walkable`/
`_bridge_tiles_from_settlements`/`_walkable_tiles`/`_find_bridge_span`)
and the constants they need are imported back into `population.py`'s own
namespace by name, so every bare-name reference there (and every
external `from hearthmind.agents.population import ...`, since
`population.py` re-exports transparently by definition) is untouched
too. Zero call-site changes anywhere in the codebase; this is a pure
move, verified byte-identical against a full-state soak (`scripts/
verify_native_soak.py`).

Deliberately NOT a `hearthmind/agents/population/` package this pass
(the doc's own eventual target) -- `population.py` stays a single
importable module at its current path, sidestepping the far larger
re-export-surface risk a package conversion would carry today (dozens
of underscore-prefixed module-level names, several read by bare
attribute access from outside, e.g. `scripts/verify_native_soak.py`'s
native-toggle list) for a first slice whose whole point is proving the
extraction pattern is safe. A package conversion, if it ever happens,
can follow once several such slices exist to move at once.
"""
from __future__ import annotations

import random
from collections import deque

from hearthmind.agents.agent import Agent, MOVE_CHANCE
from hearthmind.settlement.buildings import BuildingKind, BuildingStage, Settlement
from hearthmind.world.roads import (
    ROAD_PAVED_SPEED_MULTIPLIER,
    ROAD_SPEED_MULTIPLIER,
    RoadNetwork,
    road_condition_multiplier,
)
from hearthmind.world.terrain import Biome, Tile
from hearthmind.world.weather import WeatherState

WALKABLE_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST, Biome.HILLS, Biome.BEACH, Biome.QUARRY})
"""QUARRY (M2/M8, world/terrain_evolution.py's `maybe_form_quarries`)
stays walkable/re-workable -- a real quarry is worked ground, not an
impassable pit, same as HILLS was before conversion."""
MOUNTAIN_WALKABLE_BIOMES = WALKABLE_BIOMES | frozenset({Biome.MOUNTAIN})
WATER_CROSSABLE_BIOMES = frozenset({Biome.SHALLOW_WATER, Biome.DEEP_WATER, Biome.RIVER})
"""Every open-water biome a BOAT-mounted agent can cross (v0.87.42) --
see `_is_walkable`'s `water_capable` parameter."""
"""Once a settlement's era reaches ERA_UNLOCKS_MOUNTAIN_BUILDING, its
own pathing (_dispatch_movement's travel/goal steps, and build-site
staking) treats MOUNTAIN as walkable too -- SNOWCAP stays a hard barrier
at every era, mountains only become passable, not the snowline above
them. See _is_walkable's mountain_unlocked parameter."""

_NEIGHBOR_OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))

_WATER_BIOMES = frozenset({Biome.DEEP_WATER, Biome.SHALLOW_WATER})

BRIDGE_MAX_SPAN = 6
"""Longest run of water tiles a single bridge can cover, found by
`_find_bridge_span`'s BFS from a shore tile -- bounds both the search
cost and how implausibly wide a "bridge" is allowed to be; a channel
wider than this stays uncrossable until the map's own geography (or a
future bridge from a different shore point) offers a narrower gap."""


class PathfindingMixin:
    """The five walkability/movement/target-search staticmethods
    `Population` composes as a base class. Every method here was
    already a `@staticmethod` in the original monolith, so this move
    changes nothing about how any of them execute -- only where they
    live."""

    @staticmethod
    def _choose_explore_target(
        agent: Agent, terrain: list[list[Tile]], explored_tiles: set, rng: random.Random,
        attempts: int = 40, mountain_unlocked: bool = False,
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(), water_capable: bool = False,
    ) -> tuple[int, int] | None:
        """v0.87.45: bounded random sampling for the nearest not-yet-
        explored walkable tile -- deliberately NOT a full-map flood fill
        (`_reachable_tiles` has no node cap and would recompute the
        entire connected component every tick a surveyor needs a new
        target). `attempts` random in-bounds samples, keep the closest
        unexplored walkable hit; returns None once nothing new turns up
        (map effectively fully explored, or an unlucky sampling run --
        the caller just retries next tick).

        `mountain_unlocked`/`bridge_tiles`/`water_capable` (fix, live
        report: "why aren't npcs exploring other islands?") -- this
        target-picker previously called `_is_walkable(terrain, x, y)`
        with every extra capability defaulted off, so even a SURVEYOR
        genuinely mounted on a ready BOAT (`water_capable=True` at
        every real `_step_toward` call in the caller) was never
        actually OFFERED a tile across open water as an explore
        target -- the movement math supported the crossing, nothing
        ever asked for it. Threading the caller's own already-computed
        capability flags through here closes that gap without
        widening what a landlocked surveyor can reach."""
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for _ in range(attempts):
            x, y = rng.randrange(width), rng.randrange(height)
            if (x, y) in explored_tiles or not _is_walkable(
                terrain, x, y, mountain_unlocked, bridge_tiles, water_capable,
            ):
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _step_toward(
        agent: Agent, target: tuple[int, int], terrain: list[list[Tile]],
        predator_tiles: set[tuple[int, int]] = frozenset(), mountain_unlocked: bool = False,
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(), water_capable: bool = False,
    ) -> bool:
        """Take one greedy step toward `target`. Returns False (and leaves
        `agent` unmoved) if already there or if both preferred directions
        are blocked, so the caller can fall back to wandering.

        Avoids stepping onto a live predator's tile when an alternative
        exists -- an agent still walks into danger if that's the only way
        forward (e.g. the target itself is past a predator), it just
        doesn't prefer to. See docs/DECISIONS.md, danger pass.

        `water_capable` (v0.87.42): True for an agent currently mounted
        on a READY BOAT -- see `_is_walkable`'s matching parameter."""
        tx, ty = target
        if (tx, ty) == (agent.x, agent.y):
            return False
        dx, dy = tx - agent.x, ty - agent.y
        steps = []
        if dx != 0:
            steps.append((1 if dx > 0 else -1, 0))
        if dy != 0:
            steps.append((0, 1 if dy > 0 else -1))

        height = len(terrain)
        width = len(terrain[0]) if height else 0
        fallback: tuple[int, int] | None = None
        for cdx, cdy in steps:
            nx, ny = agent.x + cdx, agent.y + cdy
            if not (
                0 <= nx < width and 0 <= ny < height
                and _is_walkable(terrain, nx, ny, mountain_unlocked, bridge_tiles, water_capable)
            ):
                continue
            if (nx, ny) in predator_tiles:
                fallback = fallback or (nx, ny)
                continue
            agent.x, agent.y = nx, ny
            return True
        if fallback is not None:
            agent.x, agent.y = fallback
            return True
        return False

    @staticmethod
    def _bfs_step(
        terrain: list[list[Tile]], start: tuple[int, int], target: tuple[int, int],
        node_cap: int = 4096, mountain_unlocked: bool = False,
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(),
    ) -> tuple[int, int] | None:
        """First step of a real shortest path from `start` toward
        `target` over walkable tiles. Two callers: a travel_target
        journey's greedy step being blocked (fires immediately -- a
        concave water/mountain pocket makes greedy stepping oscillate
        forever, and a fission party must actually arrive), and routine
        goal-directed movement (FORAGE/SOCIALIZE/GATHER/WANDER) once it's
        been greedy-blocked for MOVEMENT_STUCK_TICKS_THRESHOLD consecutive
        ticks (fires rarely, with a smaller node_cap -- see
        MOVEMENT_STUCK_BFS_NODE_CAP -- so an ordinary tick's population-wide
        cost stays near zero; most agents never trip it). Returns None
        when target is unreachable within `node_cap` expansions (an
        island) -- a journey is then abandoned; a stuck routine target
        just falls back to the random walk for that tick instead."""
        if start == target:
            return None
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        first_step: dict[tuple[int, int], tuple[int, int]] = {}
        queue = deque([start])
        seen = {start}
        expanded = 0
        while queue and expanded < node_cap:
            cx, cy = queue.popleft()
            expanded += 1
            for dx, dy in _NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                    continue
                if not _is_walkable(terrain, nx, ny, mountain_unlocked, bridge_tiles):
                    continue
                seen.add((nx, ny))
                first_step[(nx, ny)] = first_step.get((cx, cy), (nx, ny))
                if (nx, ny) == target:
                    return first_step[(nx, ny)]
                queue.append((nx, ny))
        return None

    @staticmethod
    def _reachable_tiles(
        terrain: list[list[Tile]], origin: tuple[int, int],
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(),
    ) -> set[tuple[int, int]]:
        """The walkable connected component containing `origin` -- one
        flood fill, used by the engine's fission-site chooser so a
        founding party is never pointed at land it cannot walk to (the
        map's rivers/lakes genuinely disconnect some regions), and by
        `_find_bridge_span` to avoid bridging back to already-reachable
        land."""
        seen = {origin}
        queue = deque([origin])
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in _NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if (
                    0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                    and _is_walkable(terrain, nx, ny, bridge_tiles=bridge_tiles)
                ):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        return seen

    @staticmethod
    def _maybe_move(
        agent: Agent, terrain: list[list[Tile]], rng: random.Random, roads: RoadNetwork,
        predator_tiles: set[tuple[int, int]] = frozenset(), speed_multiplier: float = 1.0,
        weather: WeatherState | None = None,
    ) -> None:
        move_chance = MOVE_CHANCE
        if roads.is_road(agent.x, agent.y):
            # Weather affects infrastructure, not just people: an
            # established road's bonus shrinks (mud) or can even go
            # negative (snow/ice) depending on current conditions. See
            # world/roads.py's road_condition_multiplier, docs/DECISIONS.md,
            # "LLM-as-brain batch." `paved` (v0.87.43): a genuinely paved
            # tile reads a better weather-band multiplier throughout.
            paved = roads.is_paved(agent.x, agent.y)
            road_multiplier = (
                road_condition_multiplier(weather, paved) if weather is not None
                else (ROAD_PAVED_SPEED_MULTIPLIER if paved else ROAD_SPEED_MULTIPLIER)
            )
            move_chance = min(1.0, move_chance * road_multiplier)
        if speed_multiplier != 1.0:
            move_chance = min(1.0, move_chance * speed_multiplier)
        if rng.random() >= move_chance:
            return
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        candidates = []
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = agent.x + dx, agent.y + dy
            if 0 <= nx < width and 0 <= ny < height and _is_walkable(terrain, nx, ny):
                candidates.append((nx, ny))
        # Prefer avoiding a predator's tile, but don't strand an agent
        # surrounded by them -- fall back to the unfiltered set if that's
        # all that's walkable.
        safe_candidates = [c for c in candidates if c not in predator_tiles]
        if safe_candidates:
            candidates = safe_candidates
        # Live report: idle wandering visibly paces back and forth
        # ("goes up-down one tile or left-right one tile") -- with only
        # 4 candidate directions (_NEIGHBOR_OFFSETS has no diagonals), a
        # uniform random walk reverses its own last step 1-in-4 times,
        # which reads as pacing in place rather than actually going
        # anywhere. Deprioritize stepping straight back the way the
        # agent just came, falling back to it only if it's the sole
        # walkable option (a dead-end corridor). See Agent.last_move_dx/
        # dy's docstring.
        if agent.last_move_dx or agent.last_move_dy:
            reverse = (agent.x - agent.last_move_dx, agent.y - agent.last_move_dy)
            non_reverse = [c for c in candidates if c != reverse]
            if non_reverse:
                candidates = non_reverse
        if candidates:
            nx, ny = rng.choice(candidates)
            agent.last_move_dx, agent.last_move_dy = nx - agent.x, ny - agent.y
            agent.x, agent.y = nx, ny


def _is_walkable(
    terrain: list[list[Tile]], x: int, y: int, mountain_unlocked: bool = False,
    bridge_tiles: frozenset[tuple[int, int]] = frozenset(), water_capable: bool = False,
) -> bool:
    biomes = MOUNTAIN_WALKABLE_BIOMES if mountain_unlocked else WALKABLE_BIOMES
    if terrain[y][x].biome in biomes:
        return True
    # A boat-mounted agent (v0.87.42, VehicleKind.BOAT) can cross open
    # water anywhere, not just a deliberately-built BRIDGE span -- the
    # real transport gap RAFT's own docstring flagged as deferred.
    # Checked before the bridge-span check since it's the cheaper/more
    # common water-crossing path once any boats exist.
    if water_capable and terrain[y][x].biome in WATER_CROSSABLE_BIOMES:
        return True
    # A STANDING bridge's spanned water tiles are the one deliberate
    # exception to "biome determines passability" -- see BuildingKind.
    # BRIDGE's docstring. Checked second (the common case never reaches
    # here) and only ever true for the handful of tiles an actual
    # bridge covers, so this is cheap even though it's a set membership
    # test on every walkability check.
    return bool(bridge_tiles) and (x, y) in bridge_tiles


def _bridge_tiles_from_settlements(settlements: list[Settlement]) -> frozenset[tuple[int, int]]:
    """Every STANDING BRIDGE's spanned water tiles, pooled across every
    settlement into one set -- bridges are physical infrastructure on
    the shared map, not settlement-private (same "anyone can use it"
    shape roads already have), so this is computed once per tick and
    passed uniformly to every agent's movement, not looked up per
    settlement. Cheap: bridges are rare and each span is short
    (bounded by BRIDGE_MAX_SPAN)."""
    tiles: set[tuple[int, int]] = set()
    for settlement in settlements:
        for building in settlement.buildings_of_kind(BuildingKind.BRIDGE):
            if building.stage is BuildingStage.STANDING:
                tiles.update(building.bridge_span)
    return frozenset(tiles)


def _walkable_tiles(terrain: list[list[Tile]]) -> list[tuple[int, int]]:
    tiles = [
        (tile.x, tile.y)
        for row in terrain
        for tile in row
        if tile.biome in WALKABLE_BIOMES
    ]
    if tiles:
        return tiles
    # Degenerate case (e.g. a tiny all-water test map): fall back to every
    # tile rather than failing to spawn anyone.
    return [(tile.x, tile.y) for row in terrain for tile in row]


def _find_bridge_span(
    terrain: list[list[Tile]], origin: tuple[int, int], mountain_unlocked: bool = False,
) -> tuple[tuple[int, int], ...] | None:
    """From a walkable shore tile `origin`, a bounded (BRIDGE_MAX_SPAN)
    multi-step BFS through water tiles only, looking for the nearest
    opposite shore NOT already reachable from `origin` by land (no
    point bridging a peninsula back to itself). Returns the ordered
    water-tile path from `origin`'s first water neighbor to the last
    water tile before the far shore, or None if no crossing exists
    within the span limit. Uniform-cost BFS naturally finds the
    shortest (cheapest) crossing first. Deliberately only called from
    a colocation-gated, probability-rolled founding check (`_maybe_
    start_bridge`) -- this is not cheap enough to run every tick for
    every agent, but founding a bridge is itself a rare event."""
    if not _is_walkable(terrain, *origin, mountain_unlocked):
        return None
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    # Land already reachable without a bridge -- bridging to any tile in
    # here would connect two points already connected, so it's not a
    # real crossing.
    home_component = PathfindingMixin._reachable_tiles(terrain, origin)

    prev: dict[tuple[int, int], tuple[int, int]] = {}
    seen: set[tuple[int, int]] = set()
    ox, oy = origin
    queue: deque[tuple[int, int, int]] = deque()
    for dx, dy in _NEIGHBOR_OFFSETS:
        nx, ny = ox + dx, oy + dy
        if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
            continue
        if terrain[ny][nx].biome not in _WATER_BIOMES:
            continue
        seen.add((nx, ny))
        prev[(nx, ny)] = origin
        queue.append((nx, ny, 1))

    while queue:
        cx, cy, depth = queue.popleft()
        if depth > BRIDGE_MAX_SPAN:
            continue
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                continue
            tile = terrain[ny][nx]
            if tile.biome in _WATER_BIOMES:
                seen.add((nx, ny))
                prev[(nx, ny)] = (cx, cy)
                queue.append((nx, ny, depth + 1))
            elif _is_walkable(terrain, nx, ny, mountain_unlocked) and (nx, ny) not in home_component:
                span: list[tuple[int, int]] = []
                node = (cx, cy)
                while node != origin:
                    span.append(node)
                    node = prev[node]
                span.reverse()
                return tuple(span)
    return None
