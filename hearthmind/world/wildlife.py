"""Wildlife: mobile grazer and predator populations occupying terrain,
independent of the settlement. Grazer herds slowly migrate across
grassland/forest and reproduce when not overhunted; predator packs
independently roam forest/hills and cull grazer herds when they meet —
a second trophic level, so the ecosystem has its own internal dynamic
agents can disturb (overhunt a valley, watch it recover slower because
predators are thinning it too) rather than a static backdrop. Hungry
agents can hunt a colocated grazer herd for a richer food yield than
wild foraging — see Population._maybe_forage. See docs/DECISIONS.md, A4.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from enum import Enum

from hearthmind.world.resources import ResourceGrid, ResourceKind
from hearthmind.world.terrain import Biome, Tile

_NEIGHBOR_OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))


class Species(str, Enum):
    GRAZER = "grazer"
    PREDATOR = "predator"


GRAZER_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST})
PREDATOR_BIOMES = frozenset({Biome.FOREST, Biome.HILLS})

HERD_DENSITY = 0.02
"""Fraction of grazer-eligible tiles that start with a herd at world
creation — sparser than ResourceGrid's NODE_DENSITY (0.12): herds are
mobile groups, not fixed points, so far fewer are needed to populate a
map."""

INITIAL_HERD_SIZE = 4
MAX_HERD_SIZE = 12
"""A herd stops reproducing at this size — reproduction resumes once
hunting/predation brings it back below the cap."""

MIN_PREDATOR_PACK = 2
MAX_PREDATOR_PACK = 6
GRAZER_TO_PREDATOR_RATIO = 6
"""Roughly one predator pack per this many grazer herds, at creation —
keeps predators a real but not overwhelming pressure."""

MOVE_CHANCE = 0.3
"""Per-tick probability a herd/pack takes one step — slower than agent
wandering (MOVE_CHANCE 0.5), so migration reads as drift, not chaos."""

GRAZE_CONSUMPTION_PER_TICK = 0.015
GRAZE_REPRODUCE_MIN_FOOD = 0.1
"""A grazer herd colocated with a wild FOOD `ResourceNode` (world/
resources.py) eats a small amount of it each tick — real competition
with agents for the same wild forage, not just a backdrop animal.
Reproduction (GRAZER_REPRODUCE_CHANCE) is skipped outright on an
overgrazed tile (node amount below GRAZE_REPRODUCE_MIN_FOOD) — a herd
can survive on thin pasture but doesn't grow on it. A herd not
colocated with any FOOD node (open grassland with no node rolled there)
is unaffected — grazing pressure only exists where the two food sources
actually overlap. See docs/DECISIONS.md, "vegetation depletion" pass."""

GRAZER_REPRODUCE_CHANCE = 0.01
PREDATOR_HUNT_CHANCE = 0.05
"""Rolled when a predator pack is colocated with a live grazer herd —
predation isn't guaranteed just from proximity."""
PREDATOR_KILL_SIZE = 1
PREDATOR_STARVE_GRACE_TICKS = 400
PREDATOR_STARVE_CHANCE = 0.002
"""Beyond the grace period without a successful hunt, a predator pack
risks losing a member each tick — packs that can't find prey shrink and
eventually vanish, not persist forever on nothing."""

HUNT_YIELD_PER_ANIMAL = 0.6
"""Hunger relief per grazer killed by a hunting agent — richer than a
wild forage (FORAGE_HUNGER_RELIEF 0.3) or even a farm harvest (0.5): the
payoff for successfully hunting instead of just foraging or farming."""

WILDLIFE_SEARCH_RADIUS = 6
"""How far a FORAGE-goal agent can "see" a grazer herd, matching
FORAGE_SEARCH_RADIUS's rationale — wild animals are locally visible, not
map-wide knowledge like a farm or granary."""

PREDATOR_ATTACK_CHANCE = 0.015
"""Rolled once per tick for each awake agent colocated with a live
predator pack — a real but not overwhelming risk: sustained exposure
(camping on a predator's tile) is what makes it dangerous, not a single
tick of bad luck. See Population._maybe_predator_attack, docs/DECISIONS.md,
danger pass."""

PREDATOR_ATTACK_ENERGY_DRAIN = 0.25
PREDATOR_ATTACK_HUNGER_INCREASE = 0.15
"""An attack that doesn't kill still costs the agent — injury, not a
clean miss. See PREDATOR_KILL_CHANCE_ON_ATTACK for the rarer lethal case."""

PREDATOR_KILL_CHANCE_ON_ATTACK = 0.12
"""Fraction of attacks (not per-tick — per attack, so PREDATOR_ATTACK_CHANCE
* this is the true per-tick death odds, ~0.18%) that are lethal rather
than just an injury."""

GRAZER_FLEE_RADIUS = 1
"""A grazer herd prefers a move candidate that isn't adjacent to a live
predator pack, within this Chebyshev radius — animal-vs-animal
awareness, not just a passive victim of whatever tile a predator
wanders onto. Mirrors Population._maybe_move's agent-vs-predator
avoidance. See docs/DECISIONS.md, "LLM-as-brain batch.\""""

WILDLIFE_RECOLONIZE_CHECK_CHANCE = 0.002
WILDLIFE_TEMPERAMENT_INFLUENCE = 0.2
"""Fractional nudge to WILDLIFE_RECOLONIZE_CHECK_CHANCE from `Settlement.
temperament` — the same land the village's fortune is read from seems
to recover somewhat more readily during a warm spell, same small-
magnitude, warm-only treatment as population.py's MIGRANT_TEMPERAMENT_
INFLUENCE (a cold spell doesn't actively suppress recolonization, since
this is already the sole path back from local extinction)."""
"""Rolled once per tick; on success, checks whether a new grazer herd
or predator pack should spawn (migration in from beyond the map's
edge). Without this, a species that hits exactly 0 (e.g. every predator
pack starving out, especially now that GRAZER_FLEE_RADIUS makes
hunting harder) was gone from the world forever — `WildlifeGrid.generate`
only ever runs once, at world creation. A real, user-reported bug (a
live run showed "0 predators (0 packs)"), not a hypothetical. See
docs/DECISIONS.md, "map/UI/ecology follow-up.\""""

GRAZER_RECOLONIZE_TARGET_HERDS_FRACTION = 0.5
"""A new grazer herd is more likely to spawn the further the current
herd count is below (this fraction of what world-creation density would
have produced for the map's size) — see `_maybe_recolonize`."""

SEASON_GRAZER_REPRODUCE_MULTIPLIER = {"winter": 0.3, "autumn": 0.7, "spring": 1.3, "summer": 1.0}
"""Seasonal migration pressure (v0.64.0 audit-backlog item): grazer
reproduction follows the calendar the way farm growth and resource
regen already do — lean winters, a spring flush. Objective ecology, so
deterministic, matching SEASON_GROWTH_MULTIPLIER/SEASON_REGEN_
MULTIPLIER's shape; absent season names default to 1.0."""

SEASON_MIGRATE_AWAY_CHANCE = {"autumn": 0.0005, "winter": 0.0008}
"""Per-herd per-tick chance a grazer herd leaves the map entirely
during the cold half of the year (an event, not a silent vanish) —
the "pressure" half of seasonal migration: herds genuinely thin out
over autumn/winter rather than only breeding slower. Balanced by
SEASON_RECOLONIZE_MULTIPLIER's spring surge below, so the yearly cycle
reads as departure-and-return, not slow extinction. Seasons absent
from this table never migrate away."""

SEASON_RECOLONIZE_MULTIPLIER = {"spring": 3.0, "summer": 1.5}
"""Applied to WILDLIFE_RECOLONIZE_CHECK_CHANCE — the return half of
the migration cycle: herds that drifted off over winter come back with
the spring flush. Stacks with the existing warm-temperament nudge."""


def _wildlife_init_rng(seed: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:wildlife_init".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _wildlife_tick_rng(seed: int, tick: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:wildlife_tick:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


@dataclass
class AnimalHerd:
    id: int
    species: Species
    x: int
    y: int
    count: int
    ticks_since_meal: int = 0
    """Predator-only: ticks since the pack's last successful hunt — see
    PREDATOR_STARVE_CHANCE."""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "species": self.species.value, "x": self.x, "y": self.y,
            "count": self.count, "ticks_since_meal": self.ticks_since_meal,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnimalHerd":
        return cls(
            id=data["id"], species=Species(data["species"]), x=data["x"], y=data["y"],
            count=data["count"], ticks_since_meal=data.get("ticks_since_meal", 0),
        )


@dataclass
class WildlifeGrid:
    herds: dict[int, AnimalHerd] = field(default_factory=dict)
    _next_id: int = 0

    # --- construction ------------------------------------------------------

    @classmethod
    def generate(cls, seed: int, terrain: list[list[Tile]]) -> "WildlifeGrid":
        rng = _wildlife_init_rng(seed)
        herds: dict[int, AnimalHerd] = {}
        next_id = 0

        for row in terrain:
            for tile in row:
                if tile.biome in GRAZER_BIOMES and rng.random() < HERD_DENSITY:
                    herds[next_id] = AnimalHerd(
                        id=next_id, species=Species.GRAZER, x=tile.x, y=tile.y, count=INITIAL_HERD_SIZE,
                    )
                    next_id += 1

        grazer_count = len(herds)
        predator_spots = [(t.x, t.y) for row in terrain for t in row if t.biome in PREDATOR_BIOMES]
        n_predators = grazer_count // GRAZER_TO_PREDATOR_RATIO
        for _ in range(n_predators):
            if not predator_spots:
                break
            x, y = rng.choice(predator_spots)
            herds[next_id] = AnimalHerd(
                id=next_id, species=Species.PREDATOR, x=x, y=y,
                count=rng.randint(MIN_PREDATOR_PACK, MAX_PREDATOR_PACK),
            )
            next_id += 1

        return cls(herds=herds, _next_id=next_id)

    # --- queries -------------------------------------------------------------

    def at(self, x: int, y: int) -> list[AnimalHerd]:
        return [h for h in self.herds.values() if h.x == x and h.y == y]

    def predator_tiles(self) -> set[tuple[int, int]]:
        """Tiles currently occupied by a live predator pack — used for
        agent movement avoidance (Population._maybe_move/_step_toward)."""
        return {(h.x, h.y) for h in self.herds.values() if h.species is Species.PREDATOR and h.count > 0}

    def nearest_grazer_herd(self, x: int, y: int, radius: int) -> AnimalHerd | None:
        best: AnimalHerd | None = None
        best_dist: int | None = None
        for herd in self.herds.values():
            if herd.species is not Species.GRAZER or herd.count <= 0:
                continue
            if max(abs(herd.x - x), abs(herd.y - y)) > radius:
                continue
            dist = abs(herd.x - x) + abs(herd.y - y)
            if best_dist is None or dist < best_dist:
                best, best_dist = herd, dist
        return best

    def hunt(self, herd_id: int, amount: int = 1) -> int:
        """Kill up to `amount` animals from a herd, returning how many
        were actually taken (0 if the herd is already gone)."""
        herd = self.herds.get(herd_id)
        if herd is None or herd.count <= 0:
            return 0
        killed = min(amount, herd.count)
        herd.count -= killed
        return killed

    # --- tick ------------------------------------------------------------------

    def tick(
        self, seed: int, tick: int, terrain: list[list[Tile]], resources: ResourceGrid | None = None,
        temperament: float = 0.0, season: str = "summer",
    ) -> list[tuple[str, str]]:
        """Advance every herd/pack by one tick. Returns (category,
        description) events for a successful hunt or a pack/herd going
        fully extinct — animal-vs-animal interaction visible in the
        event log, not just silent numbers. See docs/DECISIONS.md,
        "LLM-as-brain batch.\""""
        rng = _wildlife_tick_rng(seed, tick)
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        events: list[tuple[str, str]] = []
        predator_tiles = self.predator_tiles()

        for herd in self.herds.values():
            if herd.count <= 0:
                continue
            biomes = GRAZER_BIOMES if herd.species is Species.GRAZER else PREDATOR_BIOMES
            if rng.random() < MOVE_CHANCE:
                candidates = []
                for dx, dy in _NEIGHBOR_OFFSETS:
                    nx, ny = herd.x + dx, herd.y + dy
                    if 0 <= nx < width and 0 <= ny < height and terrain[ny][nx].biome in biomes:
                        candidates.append((nx, ny))
                if herd.species is Species.GRAZER and candidates:
                    # Prefer a candidate that isn't adjacent to a live
                    # predator — flee rather than wander blindly into
                    # danger. Falls back to the unfiltered set if every
                    # candidate is threatened, same "don't strand it"
                    # shape as agent predator-avoidance.
                    safe = [
                        c for c in candidates
                        if not any(
                            max(abs(c[0] - px), abs(c[1] - py)) <= GRAZER_FLEE_RADIUS
                            for px, py in predator_tiles
                        )
                    ]
                    if safe:
                        candidates = safe
                if candidates:
                    herd.x, herd.y = rng.choice(candidates)

            if herd.species is Species.GRAZER:
                # Seasonal migration pressure: a cold-season herd may
                # simply leave for beyond the map (see SEASON_MIGRATE_
                # AWAY_CHANCE) — the spring recolonize surge below is
                # the return leg of the same cycle.
                if rng.random() < SEASON_MIGRATE_AWAY_CHANCE.get(season, 0.0):
                    herd.count = 0
                    events.append((
                        "wildlife_migrated",
                        f"A grazer herd near ({herd.x}, {herd.y}) drifted away with the turning season.",
                    ))
                    continue
                node = resources.get(herd.x, herd.y) if resources is not None else None
                grazing_food = node is not None and node.kind is ResourceKind.FOOD
                if grazing_food:
                    node.amount = max(0.0, node.amount - GRAZE_CONSUMPTION_PER_TICK)
                overgrazed = grazing_food and node.amount < GRAZE_REPRODUCE_MIN_FOOD
                reproduce_chance = GRAZER_REPRODUCE_CHANCE * SEASON_GRAZER_REPRODUCE_MULTIPLIER.get(season, 1.0)
                if herd.count < MAX_HERD_SIZE and not overgrazed and rng.random() < reproduce_chance:
                    herd.count += 1
                continue

            herd.ticks_since_meal += 1
            prey = next(
                (h for h in self.herds.values() if h.species is Species.GRAZER and h.count > 0
                 and h.x == herd.x and h.y == herd.y),
                None,
            )
            if prey is not None and rng.random() < PREDATOR_HUNT_CHANCE:
                prey.count -= min(PREDATOR_KILL_SIZE, prey.count)
                herd.ticks_since_meal = 0
                if herd.count < MAX_PREDATOR_PACK and rng.random() < GRAZER_REPRODUCE_CHANCE:
                    herd.count += 1
                if prey.count <= 0:
                    events.append((
                        "wildlife_extinct",
                        f"A grazer herd near ({prey.x}, {prey.y}) was hunted to nothing by predators.",
                    ))
                else:
                    events.append((
                        "wildlife_hunt",
                        f"A predator pack culled a grazer herd near ({herd.x}, {herd.y}).",
                    ))
            elif herd.ticks_since_meal > PREDATOR_STARVE_GRACE_TICKS and rng.random() < PREDATOR_STARVE_CHANCE:
                herd.count -= 1
                if herd.count <= 0:
                    events.append((
                        "wildlife_extinct",
                        f"A predator pack near ({herd.x}, {herd.y}) starved and scattered.",
                    ))

        self.herds = {herd_id: h for herd_id, h in self.herds.items() if h.count > 0}

        recolonize_chance = (
            WILDLIFE_RECOLONIZE_CHECK_CHANCE
            * (1.0 + max(0.0, temperament) * WILDLIFE_TEMPERAMENT_INFLUENCE)
            * SEASON_RECOLONIZE_MULTIPLIER.get(season, 1.0)
        )
        if rng.random() < recolonize_chance:
            events += self._maybe_recolonize(rng, terrain)

        return events

    def _maybe_recolonize(self, rng: random.Random, terrain: list[list[Tile]]) -> list[tuple[str, str]]:
        """A locally-extinct (or thin) species can be recolonized from
        beyond the map's edge — without this, a species that ever hits
        exactly 0 herds/packs stays extinct forever, since
        `WildlifeGrid.generate` only runs once at world creation. See
        WILDLIFE_RECOLONIZE_CHECK_CHANCE."""
        events: list[tuple[str, str]] = []
        grazer_herds = [h for h in self.herds.values() if h.species is Species.GRAZER]
        predator_packs = [h for h in self.herds.values() if h.species is Species.PREDATOR]

        grazer_spots = [(t.x, t.y) for row in terrain for t in row if t.biome in GRAZER_BIOMES]
        target_herds = max(1, int(len(grazer_spots) * HERD_DENSITY * GRAZER_RECOLONIZE_TARGET_HERDS_FRACTION))
        if len(grazer_herds) < target_herds and grazer_spots:
            x, y = rng.choice(grazer_spots)
            self.herds[self._next_id] = AnimalHerd(
                id=self._next_id, species=Species.GRAZER, x=x, y=y, count=INITIAL_HERD_SIZE,
            )
            self._next_id += 1
            events.append(("wildlife_recolonized", f"A new grazer herd was seen near ({x}, {y})."))

        if not predator_packs and grazer_herds:
            # Only recolonize predators if there's already prey to
            # sustain them — a predator pack with nothing to hunt would
            # just starve out again immediately.
            predator_spots = [(t.x, t.y) for row in terrain for t in row if t.biome in PREDATOR_BIOMES]
            if predator_spots:
                x, y = rng.choice(predator_spots)
                self.herds[self._next_id] = AnimalHerd(
                    id=self._next_id, species=Species.PREDATOR, x=x, y=y,
                    count=rng.randint(MIN_PREDATOR_PACK, MAX_PREDATOR_PACK),
                )
                self._next_id += 1
                events.append(("wildlife_recolonized", f"A predator pack has moved into the area near ({x}, {y})."))

        return events

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        grazers = [h for h in self.herds.values() if h.species is Species.GRAZER]
        predators = [h for h in self.herds.values() if h.species is Species.PREDATOR]
        return {
            "grazer_herds": len(grazers),
            "grazer_total": sum(h.count for h in grazers),
            "predator_packs": len(predators),
            "predator_total": sum(h.count for h in predators),
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {"herds": [h.to_dict() for h in self.herds.values()], "next_id": self._next_id}

    @classmethod
    def from_dict(cls, data: dict) -> "WildlifeGrid":
        herds = {h["id"]: AnimalHerd.from_dict(h) for h in data["herds"]}
        next_id = data.get("next_id", (max(herds) + 1) if herds else 0)
        return cls(herds=herds, _next_id=next_id)
