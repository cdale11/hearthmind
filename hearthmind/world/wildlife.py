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
from hearthmind.world.terrain_evolution import apply_migration_trail

try:
    from hearthmind._native import GrazerHerdIndex as _NativeGrazerHerdIndex
except ImportError:
    _NativeGrazerHerdIndex = None
"""Optional compiled fast path for `nearest_grazer_herd` (module 5, see
cpp/src/wildlife_index.cpp, docs/DECISIONS.md "Native extension port").
`None` when the extension wasn't built — falls back to the equivalent
pure-Python scan in that case."""

try:
    from hearthmind._native import grazer_tick_step as _native_grazer_tick_step
except ImportError:
    _native_grazer_tick_step = None
"""Optional compiled fast path for `WildlifeGrid.tick`'s GRAZER branch
(module 22, see cpp/src/wildlife_step.cpp, docs/DECISIONS.md "Native
extension port"). Bundles node-consumption + overgraze check + reproduce
roll into one call — herd/dict iteration and movement (terrain lookups)
stay in Python either way. `None` when the extension wasn't built."""

_NEIGHBOR_OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))


def _field_region_value(grid: "list[list[float]] | None", x: int, y: int, width: int, height: int) -> float:
    """Same bucketing math as `FieldGrid.get_at`/`region_of` (`world/
    fields.py`) — kept deliberately in lockstep rather than importing
    `FieldGrid` itself, since this module has no other reason to depend
    on it. `grid=None`/an empty grid/non-positive dimensions all read
    as 0.0 (neutral, no dampening) rather than erroring."""
    if not grid or width <= 0 or height <= 0:
        return 0.0
    size = len(grid)
    rx = min(size - 1, max(0, x * size // width))
    ry = min(size - 1, max(0, y * size // height))
    return grid[ry][rx]


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

MIGRATION_TRAIL_PREFERENCE_WEIGHT = 3.0
"""M4 (docs/VISION-2026-07-24-LIVINGMAP.md, "migration creates
recognizable paths"): a GRAZER herd choosing among its move candidates
weights a tile with existing trail intensity `1.0 + trail *
MIGRATION_TRAIL_PREFERENCE_WEIGHT` — herds genuinely tend to reuse the
same crossings over time, a real feedback loop (movement creates the
trail, the trail then draws more movement) rather than a one-way
cosmetic. Scoped to GRAZER only — predators track prey, not paths."""

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

PREDATOR_PRESSURE_RATIO_THRESHOLD = 0.25
"""Phase 3.D "food webs / predator-prey feedback" (docs/VISION-2026-07-
21-SELFEVOLVING.md): total live predator animals as a fraction of total
live grazer animals. Above this ratio, predation pressure is high
enough to measurably suppress grazer reproduction map-wide — not just
the direct per-tile kills the hunt mechanic already does, but a
"landscape of fear" effect: a herd under heavy predation pressure
breeds less even where it hasn't personally been hunted yet."""
PREDATOR_PRESSURE_REPRODUCE_PENALTY = 0.5
"""Grazer `reproduce_chance` multiplier once the ratio above is
crossed — halved, not zeroed; direct kills remain the dominant
suppression mechanism, this is a secondary population-level effect."""

PREY_SCARCITY_RATIO_THRESHOLD = 0.5
"""The other half of the loop: `GRAZER_TO_PREDATOR_RATIO` grazer herds
per predator pack is the population world-gen (and recolonization)
already treats as "enough support." When the actual grazer-herd-count-
to-predator-pack-count ratio falls below this fraction of that
baseline, prey is scarce enough map-wide that predator reproduction and
survival suffer even for a pack that got lucky with a same-tile hunt
this tick — not just the existing same-tile "no prey here" case."""
PREY_SCARCITY_REPRODUCE_PENALTY = 0.5
PREY_SCARCITY_STARVE_MULTIPLIER = 2.0
"""A pack in a prey-scarce landscape is twice as likely to lose a
member on the post-grace-period starvation roll — scarcity compounds
starvation risk beyond just "this exact pack hasn't eaten in a while.\""""

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

RECOLONIZE_NOISE_DAMPENING = 0.6
"""A1's `noise` `FieldGrid` field's first real consumer: a candidate
recolonization site in a region at peak noise (`World.fields`'s
`noise`, `population_density`/`traffic` averaged) has its selection
weight cut by up to this fraction — "wildlife resettles the quiet
corners of the map first, not the busy ones," a real ecological
consequence neither source field had on its own. Never zeroes a
candidate out entirely (floored via `max(0.0, 1.0 - noise * this)`,
and the whole weighted draw falls back to a uniform `rng.choice` if
every candidate somehow lands at zero weight) — noise nudges WHICH
tile gets picked, never whether recolonization can happen at all."""

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


HARDINESS_BASELINE = 0.5
"""A15 "Genetic inheritance," wildlife slice (roadmap Tier 2 item 7):
`AnimalHerd.hardiness` is a real heritable 0..1 trait — the first
piece of real wildlife genetics (previously humans-only, `Agent.
genome`). Unlike a human's diploid two-allele genome, a herd/pack is
already a POPULATION aggregate, not an individual, so its "genome" is
one continuous number representing the population's own average
constitution — genuinely heritable (see `_maybe_recolonize`'s gene-
pool inheritance) without needing per-animal allele bookkeeping."""

HARDINESS_GENESIS_STDDEV = 0.12
"""Spread of `hardiness` across herds/packs seeded at world genesis
(`WildlifeGrid.generate`) — real starting genetic diversity, not every
founding herd identical. Small enough that `HARDINESS_REPRODUCE_MIN_
FACTOR`/`_MAX_FACTOR` below stay meaningful, not saturated."""

HARDINESS_MUTATION_STDDEV = 0.08
"""Drift applied when a NEW herd/pack inherits its `hardiness` from
the surviving local gene pool on recolonization (`_maybe_recolonize`)
— smaller than the genesis spread (an already-adapted population drifts
gradually generation to generation, it doesn't reset to random)."""

HARDINESS_REPRODUCE_MIN_FACTOR = 0.7
HARDINESS_REPRODUCE_MAX_FACTOR = 1.3
"""The real consumer: `hardiness_reproduce_factor` scales a herd's own
`reproduce_chance` between these bounds (hardiness=0 -> 0.7x, =0.5 ->
1.0x/no-op, =1 -> 1.3x) — a genuinely hardier population reproduces
measurably better under the SAME predator-pressure/prey-scarcity
penalty every herd already contends with, never a hard override of
those existing tuned rates. Applied in pure Python to the scalar
`reproduce_chance` BEFORE it reaches `_native_grazer_tick_step` (which
only ever sees the final float) — zero native/index parity risk, the
same "modulate after the fact" discipline A14's `injury` consumer
established."""

HARDINESS_VARIANT_BUMP = 0.15
"""Bridges `SpeciesVariant`'s existing descriptive-only "hardier" trait
(`SPECIES_VARIANT_TRAITS`) to this real numeric gene — the specific
gap flagged in `SPECIES_VARIANT_TRAITS`'s own docstring. When Nature
names a herd's variant as "hardier" (`SimulationEngine._maybe_
schedule_species_variant`), that herd's `hardiness` genuinely rises by
this much, clamped to 1.0 — an LLM-authored identity now has one real,
bounded mechanical consequence, not just flavor text."""


def hardiness_reproduce_factor(hardiness: float) -> float:
    """See `HARDINESS_REPRODUCE_MIN_FACTOR`/`_MAX_FACTOR`'s docstring."""
    hardiness = max(0.0, min(1.0, hardiness))
    return HARDINESS_REPRODUCE_MIN_FACTOR + hardiness * (
        HARDINESS_REPRODUCE_MAX_FACTOR - HARDINESS_REPRODUCE_MIN_FACTOR
    )


def _inherit_hardiness(rng: random.Random, gene_pool: list[float]) -> float:
    """A15's real inheritance mechanism: a recolonizing herd/pack draws
    its `hardiness` from the surviving local gene pool's own average
    (founder-effect realism — a new colony largely reflects the source
    population's genetics) plus a small mutation, rather than a flat
    reset to baseline. An empty pool (the species is genuinely, fully
    gone map-wide) has no gene pool to draw from, so a fresh founder
    population starts at the neutral baseline instead."""
    if not gene_pool:
        return HARDINESS_BASELINE
    avg = sum(gene_pool) / len(gene_pool)
    return max(0.0, min(1.0, avg + rng.gauss(0.0, HARDINESS_MUTATION_STDDEV)))


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
    hardiness: float = HARDINESS_BASELINE
    """A15: real heritable population-level trait — see its own
    docstring above."""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "species": self.species.value, "x": self.x, "y": self.y,
            "count": self.count, "ticks_since_meal": self.ticks_since_meal,
            "hardiness": round(self.hardiness, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnimalHerd":
        return cls(
            id=data["id"], species=Species(data["species"]), x=data["x"], y=data["y"],
            count=data["count"], ticks_since_meal=data.get("ticks_since_meal", 0),
            hardiness=data.get("hardiness", HARDINESS_BASELINE),
        )


SPECIES_VARIANT_TRAITS: tuple[str, ...] = ("hardier", "migratory", "timid", "aggressive", "prolific")
"""Vision doc item 4.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("Emergent species/variants via parameter-space"): closed vocabulary
of what makes a named variant distinct — same "closed primitives,
open combination" discipline as `MECHANICAL_HOOK_TYPES`. Descriptive
only for now (surfaced in the UI/knowledge tree, read by Nature's own
belief-formation prompt) — real numeric stat deltas applied inside
`WildlifeGrid.tick`'s hot loop are explicitly NOT wired this pass to
avoid an `AnimalHerd`/native-index parity risk (R7); same flagged-not-
silently-dropped honesty as `TriggerRule`'s still-narrative-only hook
types."""

MAX_SPECIES_VARIANTS_STORED = 60
"""Cap on `World.species_variants` — rare (Nature's own cadence, not
per-tick), smaller ceiling than concepts/rules is plenty."""


@dataclass
class SpeciesVariant:
    """Vision item 4.2: a named, persistent variant of an EXISTING
    wildlife species — "a new kind of thing in the world, still fully
    inside the physics," same composition discipline as item 4.1's
    `CompositeEntity` applied to Nature. Bound to one real `AnimalHerd`
    (`herd_id`) at the moment it's named; the herd's own species/
    mechanics never change — this is identity, not a new creature
    type."""

    id: int
    name: str
    species: str
    herd_id: int
    trait: str
    description: str
    tick_named: int

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "species": self.species, "herd_id": self.herd_id,
            "trait": self.trait, "description": self.description, "tick_named": self.tick_named,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SpeciesVariant":
        return cls(
            id=data["id"], name=data["name"], species=data.get("species", ""),
            herd_id=data["herd_id"], trait=data.get("trait", ""),
            description=data.get("description", ""), tick_named=data.get("tick_named", 0),
        )


@dataclass
class WildlifeGrid:
    herds: dict[int, AnimalHerd] = field(default_factory=dict)
    _next_id: int = 0
    _native_index: "object | None" = field(default=None, compare=False, repr=False)
    """Rebuilt at the end of `tick()` (herd positions only change there,
    always before Population.tick() runs — see world/state.py's
    World.tick ordering) and live-patched by `hunt()` for the same
    same-tick-multi-agent-ordering reason `ResourceIndex` needs
    `mark_regenerating`. `None` when the native extension isn't built."""

    def _refresh_native_index(self) -> None:
        if _NativeGrazerHerdIndex is None:
            return
        self._native_index = _NativeGrazerHerdIndex([
            (h.id, h.x, h.y, h.count)
            for h in self.herds.values() if h.species is Species.GRAZER
        ])

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
                        # A15: real starting genetic diversity, not every
                        # founding herd identical — see HARDINESS_
                        # GENESIS_STDDEV's docstring.
                        hardiness=max(0.0, min(1.0, rng.gauss(HARDINESS_BASELINE, HARDINESS_GENESIS_STDDEV))),
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
                hardiness=max(0.0, min(1.0, rng.gauss(HARDINESS_BASELINE, HARDINESS_GENESIS_STDDEV))),
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
        if self._native_index is not None:
            pos = self._native_index.nearest(x, y, radius)
            if pos is None:
                return None
            # Recover the actual AnimalHerd object (callers read fields
            # like `.id`/`.count` off it) — the index only tracks
            # position/count, not full herd identity, so resolve the one
            # live grazer herd at that exact tile.
            for herd in self.herds.values():
                if herd.species is Species.GRAZER and herd.count > 0 and (herd.x, herd.y) == pos:
                    return herd
            return None
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
        if self._native_index is not None and herd.species is Species.GRAZER:
            self._native_index.update(herd.id, herd.x, herd.y, herd.count)
        return killed

    # --- tick ------------------------------------------------------------------

    def tick(
        self, seed: int, tick: int, terrain: list[list[Tile]], resources: ResourceGrid | None = None,
        temperament: float = 0.0, season: str = "summer",
        migration_trails: "dict[tuple[int, int], float] | None" = None,
        noise: "list[list[float]] | None" = None,
    ) -> list[tuple[str, str]]:
        """Advance every herd/pack by one tick. Returns (category,
        description) events for a successful hunt or a pack/herd going
        fully extinct — animal-vs-animal interaction visible in the
        event log, not just silent numbers. See docs/DECISIONS.md,
        "LLM-as-brain batch."

        `migration_trails` (M4, `World.migration_trails`, optional —
        `None` reproduces the exact pre-M4 behavior): a GRAZER herd
        that actually moves this tick leaves a small mark at its new
        position (see `terrain_evolution.apply_migration_trail`) and,
        when choosing among move candidates, weights toward tiles that
        already carry trail intensity — the two halves of one real
        feedback loop, not just a one-way cosmetic overlay.

        `noise` (A1, `World.fields`'s `noise` field, optional — `None`
        reproduces the exact pre-this-feature behavior): dampens
        `_maybe_recolonize`'s site-selection weight toward quieter
        regions. Read one tick stale, same as every other `World.fields`
        consumer (`Population`'s migrant-welcome chance, etc.) — this
        tick's `fields.step_*` calls haven't run yet when `tick()` is
        called."""
        rng = _wildlife_tick_rng(seed, tick)
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        events: list[tuple[str, str]] = []
        predator_tiles = self.predator_tiles()

        # Phase 3.D trophic feedback (see PREDATOR_PRESSURE_RATIO_
        # THRESHOLD/PREY_SCARCITY_RATIO_THRESHOLD docstrings): two cheap
        # O(n) aggregate reads over the herd dict we're about to iterate
        # anyway, computed once up front rather than per-herd — R7
        # deviation (Python, not C++), same "aggregate scalar, not a new
        # per-tile hot loop" rationale as the existing scar/soil
        # deviations.
        total_grazers = sum(h.count for h in self.herds.values() if h.species is Species.GRAZER)
        total_predators = sum(h.count for h in self.herds.values() if h.species is Species.PREDATOR)
        predator_pack_count = sum(1 for h in self.herds.values() if h.species is Species.PREDATOR)
        grazer_herd_count = sum(1 for h in self.herds.values() if h.species is Species.GRAZER)
        predator_pressure_ratio = total_predators / max(1, total_grazers)
        grazer_reproduce_penalty = (
            PREDATOR_PRESSURE_REPRODUCE_PENALTY if predator_pressure_ratio > PREDATOR_PRESSURE_RATIO_THRESHOLD
            else 1.0
        )
        expected_grazer_herds = predator_pack_count * GRAZER_TO_PREDATOR_RATIO
        prey_scarce = (
            predator_pack_count > 0
            and grazer_herd_count < expected_grazer_herds * PREY_SCARCITY_RATIO_THRESHOLD
        )

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
                    if herd.species is Species.GRAZER and migration_trails:
                        # M4: reuse an established crossing over a fresh
                        # one when several are otherwise equally valid —
                        # the trail-preference half of the feedback loop
                        # (the gain half is right below).
                        weights = [
                            1.0 + migration_trails.get(c, 0.0) * MIGRATION_TRAIL_PREFERENCE_WEIGHT
                            for c in candidates
                        ]
                        herd.x, herd.y = rng.choices(candidates, weights=weights, k=1)[0]
                    else:
                        herd.x, herd.y = rng.choice(candidates)
                    if herd.species is Species.GRAZER and migration_trails is not None:
                        apply_migration_trail((herd.x, herd.y), migration_trails)

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
                reproduce_chance = (
                    GRAZER_REPRODUCE_CHANCE * SEASON_GRAZER_REPRODUCE_MULTIPLIER.get(season, 1.0)
                    * grazer_reproduce_penalty * hardiness_reproduce_factor(herd.hardiness)
                )
                reproduce_roll = rng.random()
                if _native_grazer_tick_step is not None:
                    # Native fast path (module 22): bundles the node-
                    # consumption + overgraze check + reproduce roll into
                    # one call. `node_amount` is a dummy 0.0 when there's
                    # no colocated FOOD node — `grazed` tells us whether
                    # to trust the returned amount at all.
                    new_count, new_amount, grazed = _native_grazer_tick_step(
                        herd.count, grazing_food, node.amount if grazing_food else 0.0,
                        GRAZE_CONSUMPTION_PER_TICK, GRAZE_REPRODUCE_MIN_FOOD,
                        MAX_HERD_SIZE, reproduce_chance, reproduce_roll,
                    )
                    herd.count = new_count
                    if grazed:
                        node.amount = new_amount
                        resources.mark_regenerating(herd.x, herd.y)
                    continue
                if grazing_food:
                    node.amount = max(0.0, node.amount - GRAZE_CONSUMPTION_PER_TICK)
                    resources.mark_regenerating(herd.x, herd.y)
                overgrazed = grazing_food and node.amount < GRAZE_REPRODUCE_MIN_FOOD
                if herd.count < MAX_HERD_SIZE and not overgrazed and reproduce_roll < reproduce_chance:
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
                reproduce_chance = GRAZER_REPRODUCE_CHANCE * (
                    PREY_SCARCITY_REPRODUCE_PENALTY if prey_scarce else 1.0
                ) * hardiness_reproduce_factor(herd.hardiness)
                if herd.count < MAX_PREDATOR_PACK and rng.random() < reproduce_chance:
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
            elif herd.ticks_since_meal > PREDATOR_STARVE_GRACE_TICKS and rng.random() < (
                PREDATOR_STARVE_CHANCE * (PREY_SCARCITY_STARVE_MULTIPLIER if prey_scarce else 1.0)
            ):
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
            events += self._maybe_recolonize(rng, terrain, noise, width, height)

        self._refresh_native_index()
        return events

    def _maybe_recolonize(
        self, rng: random.Random, terrain: list[list[Tile]],
        noise: "list[list[float]] | None" = None, width: int = 0, height: int = 0,
    ) -> list[tuple[str, str]]:
        """A locally-extinct (or thin) species can be recolonized from
        beyond the map's edge — without this, a species that ever hits
        exactly 0 herds/packs stays extinct forever, since
        `WildlifeGrid.generate` only runs once at world creation. See
        WILDLIFE_RECOLONIZE_CHECK_CHANCE. `noise=None` (default)
        reproduces the exact pre-A1 uniform `rng.choice` selection."""
        events: list[tuple[str, str]] = []
        grazer_herds = [h for h in self.herds.values() if h.species is Species.GRAZER]
        predator_packs = [h for h in self.herds.values() if h.species is Species.PREDATOR]

        def _choose_spot(spots: list[tuple[int, int]]) -> tuple[int, int]:
            if noise is None:
                return rng.choice(spots)
            weights = [
                max(0.0, 1.0 - _field_region_value(noise, sx, sy, width, height) * RECOLONIZE_NOISE_DAMPENING)
                for sx, sy in spots
            ]
            if sum(weights) <= 0.0:
                return rng.choice(spots)
            return rng.choices(spots, weights=weights, k=1)[0]

        grazer_spots = [(t.x, t.y) for row in terrain for t in row if t.biome in GRAZER_BIOMES]
        target_herds = max(1, int(len(grazer_spots) * HERD_DENSITY * GRAZER_RECOLONIZE_TARGET_HERDS_FRACTION))
        if len(grazer_herds) < target_herds and grazer_spots:
            x, y = _choose_spot(grazer_spots)
            # A15: the new herd inherits its hardiness from the
            # surviving (count > 0) local gene pool (founder-effect
            # realism), not a flat reset — see _inherit_hardiness's
            # docstring. `grazer_herds` itself isn't count-filtered
            # (pre-existing `target_herds` sizing behavior, unchanged
            # here) so the gene pool re-filters locally.
            hardiness = _inherit_hardiness(rng, [h.hardiness for h in grazer_herds if h.count > 0])
            self.herds[self._next_id] = AnimalHerd(
                id=self._next_id, species=Species.GRAZER, x=x, y=y, count=INITIAL_HERD_SIZE,
                hardiness=hardiness,
            )
            self._next_id += 1
            events.append(("wildlife_recolonized", f"A new grazer herd was seen near ({x}, {y})."))

        # P2.1 (docs/AUDIT-2026-07-20.md): a live 16k-tick LLM-off soak
        # measured predators collapsing 6-ish packs -> 1, with only 4
        # recolonizations against 10 extinctions — this branch only ever
        # fired once packs hit exactly 0, so a pack thinned to 1 (still
        # technically alive, easy prey for the starve-out chance next
        # tick) never got recolonization pressure the way a thin grazer
        # population already does via `target_herds`. Now uses the same
        # target-fraction shape as grazers (reusing GRAZER_TO_PREDATOR_
        # RATIO, the same ratio world-gen itself uses to size the
        # initial predator count) instead of a strict "== 0" check.
        predator_target = max(1, len(grazer_herds) // GRAZER_TO_PREDATOR_RATIO)
        if len(predator_packs) < predator_target and grazer_herds:
            # Only recolonize predators if there's already prey to
            # sustain them — a predator pack with nothing to hunt would
            # just starve out again immediately.
            predator_spots = [(t.x, t.y) for row in terrain for t in row if t.biome in PREDATOR_BIOMES]
            if predator_spots:
                x, y = _choose_spot(predator_spots)
                hardiness = _inherit_hardiness(rng, [h.hardiness for h in predator_packs if h.count > 0])
                self.herds[self._next_id] = AnimalHerd(
                    id=self._next_id, species=Species.PREDATOR, x=x, y=y,
                    count=rng.randint(MIN_PREDATOR_PACK, MAX_PREDATOR_PACK),
                    hardiness=hardiness,
                )
                self._next_id += 1
                events.append(("wildlife_recolonized", f"A predator pack has moved into the area near ({x}, {y})."))

        return events

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        grazers = [h for h in self.herds.values() if h.species is Species.GRAZER]
        predators = [h for h in self.herds.values() if h.species is Species.PREDATOR]
        grazer_total = sum(h.count for h in grazers)
        predator_total = sum(h.count for h in predators)
        # Phase 3.D trophic feedback — same formulas `tick()` uses live,
        # recomputed here (cheap) so the dev console can see the two
        # pressure signals that are currently suppressing reproduction/
        # raising starvation risk, not just the raw population counts.
        predator_pressure_ratio = predator_total / max(1, grazer_total)
        expected_grazer_herds = len(predators) * GRAZER_TO_PREDATOR_RATIO
        prey_scarce = len(predators) > 0 and len(grazers) < expected_grazer_herds * PREY_SCARCITY_RATIO_THRESHOLD
        # A15: population-genetics readout — the average heritable
        # hardiness across each trophic level's LIVING herds/packs
        # only (a dead entry can lingers in `self.herds` until GC'd
        # elsewhere; its stale hardiness shouldn't skew this reading).
        # `None` when that level is fully extinct (nothing to average).
        living_grazers = [h for h in grazers if h.count > 0]
        living_predators = [h for h in predators if h.count > 0]
        avg_grazer_hardiness = (
            round(sum(h.hardiness for h in living_grazers) / len(living_grazers), 3) if living_grazers else None
        )
        avg_predator_hardiness = (
            round(sum(h.hardiness for h in living_predators) / len(living_predators), 3)
            if living_predators else None
        )
        return {
            "grazer_herds": len(grazers),
            "grazer_total": grazer_total,
            "predator_packs": len(predators),
            "predator_total": predator_total,
            "predator_pressure_ratio": round(predator_pressure_ratio, 3),
            "prey_scarce": prey_scarce,
            "avg_grazer_hardiness": avg_grazer_hardiness,
            "avg_predator_hardiness": avg_predator_hardiness,
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {"herds": [h.to_dict() for h in self.herds.values()], "next_id": self._next_id}

    @classmethod
    def from_dict(cls, data: dict) -> "WildlifeGrid":
        herds = {h["id"]: AnimalHerd.from_dict(h) for h in data["herds"]}
        next_id = data.get("next_id", (max(herds) + 1) if herds else 0)
        return cls(herds=herds, _next_id=next_id)
