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

    def tick(self, seed: int, tick: int, terrain: list[list[Tile]]) -> list[tuple[str, str]]:
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
                if herd.count < MAX_HERD_SIZE and rng.random() < GRAZER_REPRODUCE_CHANCE:
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
