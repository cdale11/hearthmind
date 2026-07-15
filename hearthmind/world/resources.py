"""Discrete, depletable resource nodes scattered across terrain.

Emergence lever: resource nodes are finite and regenerate slowly, so local
overforaging genuinely matters — a population that grows faster than its
foraging grounds regenerate should feel real scarcity, not draw from an
infinite pantry. See docs/DECISIONS.md, A1.

Three kinds as of the fishing pass: FOOD ("bush" — wild forage,
grassland/forest/hills, fast regen), ORE ("mine" — GATHER-goal
material source, hills only, regenerates far slower than food), and
FISH ("fishing spot" — any walkable tile bordering water, richer yield
and faster regen than a bush since a fish stock replenishes by
migration/spawning rather than static regrowth). Forest wood is
deliberately NOT a discrete/depletable resource here — see
Population._maybe_gather for why. See docs/DECISIONS.md, resource-variety
pass and "fishing" pass.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from enum import Enum

from hearthmind.world.terrain import Biome, Tile

try:
    from hearthmind._native import ResourceIndex as _NativeResourceIndex
    from hearthmind._native import resource_grid_tick as _native_tick
except ImportError:
    _NativeResourceIndex = None
    _native_tick = None
"""Optional compiled fast path for `ResourceGrid.tick` (see cpp/src/
resource_grid.cpp, docs/DECISIONS.md "Native extension port"). `None`
when the extension wasn't built (missing compiler, `pip install -e .`
run without pybind11, unsupported platform, ...) — `tick` below falls
back to the equivalent pure-Python loop in that case. Never a hard
dependency; behavior is identical either way."""


class ResourceKind(str, Enum):
    FOOD = "food"
    ORE = "ore"
    FISH = "fish"


FOOD_BIOMES = frozenset({Biome.FOREST, Biome.GRASSLAND, Biome.HILLS})
ORE_BIOMES = frozenset({Biome.HILLS})
"""Ore only on hills (not mountain — mountain isn't a walkable biome, see
agents/population.py's WALKABLE_BIOMES, so an unreachable ore vein there
would be pointless)."""

WATER_ADJACENT_BIOMES = frozenset({Biome.DEEP_WATER, Biome.SHALLOW_WATER, Biome.RIVER})
"""A fishing spot needs a walkable tile bordering one of these — not
"is beach" specifically, since a grassland/forest tile hugging a river
is just as fishable as a beach hugging the sea. See `is_adjacent_to_water`."""

NODE_DENSITY = 0.12
"""Fraction of FOOD_BIOMES tiles that get a food node at world creation."""

ORE_NODE_DENSITY = 0.06
"""Fraction of hills tiles that get an ore node instead of a food node —
rolled before the food roll on hills specifically (see `generate`), so a
hills tile is one or the other, never both."""

FISH_NODE_DENSITY = 0.35
"""Fraction of walkable water-adjacent tiles that get a fishing spot —
much denser than NODE_DENSITY: a shoreline is a genuinely reliable food
source in reality, and this is deliberately the richer, faster-
replenishing alternative to wild foraging the "add fishing" ask wants,
not a rare extra. Rolled independently of (and after) the food/ore rolls,
so a water-adjacent grassland/forest/hills/beach tile can carry a fish
node even if it already missed (or won given FOOD_BIOMES/ORE_BIOMES
overlap) the other rolls — see `generate`."""

MAX_NODE_AMOUNT = 1.0
MAX_ORE_AMOUNT = 2.0
"""A mineral vein holds more than a berry bush, but see ORE_REGEN_PER_TICK
— it takes far longer to refill."""

MAX_FISH_AMOUNT = 1.5
"""A fishing spot holds more than a bush (a school of fish is a richer
catch than wild forage) but less than a full ore vein."""

REGEN_PER_TICK = 0.002
"""~500 ticks (about 5 sim-days at default pacing) to fully regrow from empty."""

ORE_REGEN_PER_TICK = REGEN_PER_TICK / 12
"""~12x slower than food (and from double the max amount) — a depleted
vein takes on the order of 60 sim-days to fully recover, not 5. "Mines
recover over longer time" is the concrete ask this constant answers."""

FISH_REGEN_PER_TICK = REGEN_PER_TICK * 1.5
"""Faster than food, not slower — a fish stock replenishes by migration/
spawning from the wider body of water, not by static local regrowth
like a bush, so overfishing one spot recovers faster than overforaging
a patch of land."""

FISH_HUNGER_RELIEF_MULTIPLIER = 1.2
"""A catch is a richer meal than wild forage — applied to
FORAGE_HUNGER_RELIEF in Population._maybe_forage's fish branch."""

SEASON_REGEN_MULTIPLIER = {"winter": 0.3, "autumn": 0.75, "spring": 1.1, "summer": 1.0}
"""Regeneration multiplier by season name, applied to both kinds —
winter genuinely slows regrowth (frozen ground is harder to forage *and*
harder to mine). Same rationale/pattern as
economy.farms.SEASON_GROWTH_MULTIPLIER; a season absent from this table
defaults to 1.0. See docs/DECISIONS.md, scarcity pass."""


def _resource_rng(seed: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:resources_init".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


_ADJACENT = ((0, -1), (0, 1), (-1, 0), (1, 0))


def is_adjacent_to_water(terrain: list[list[Tile]], x: int, y: int) -> bool:
    height, width = len(terrain), len(terrain[0]) if terrain else 0
    for dx, dy in _ADJACENT:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height and terrain[ny][nx].biome in WATER_ADJACENT_BIOMES:
            return True
    return False


@dataclass
class ResourceNode:
    x: int
    y: int
    kind: ResourceKind = ResourceKind.FOOD
    amount: float = MAX_NODE_AMOUNT

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "kind": self.kind.value, "amount": round(self.amount, 4)}

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceNode":
        return cls(
            x=data["x"], y=data["y"],
            kind=ResourceKind(data.get("kind", ResourceKind.FOOD.value)),
            amount=data["amount"],
        )


@dataclass
class ResourceGrid:
    nodes: dict[tuple[int, int], ResourceNode]
    _regenerating: "set[tuple[int, int]] | None" = field(default=None, compare=False, repr=False)
    """Positions of nodes currently below their cap — the working set
    `tick` actually iterates (v0.71.x perf pass, R4). Most nodes sit at
    cap most of the time (regen outpaces harvest), so the old
    "scan every node every tick" pass did mostly no-op work; iterating
    only below-cap nodes is a real, measured win with no behavior change
    (a node at cap is a no-op under `min(cap, amount+regen)` anyway).
    Not persisted, not part of equality — lazily seeded to every node on
    the first `tick` and thereafter kept in sync: a node leaves the set
    when it reaches cap, and re-enters via `mark_regenerating` whenever
    something depletes it (forage/gather/grazing). `None` means "not yet
    seeded"; harvests before the first tick are safely covered because
    that first tick seeds the whole grid regardless."""
    _native_index: "object | None" = field(default=None, compare=False, repr=False)
    """Compiled `hearthmind._native.ResourceIndex` snapshot backing
    `nearest_food_or_fish` (v0.72.2, second native-port module — see
    cpp/src/resource_grid.cpp `ResourceIndex`). Rebuilt once per `tick`
    (not per query) from the current FOOD/FISH node amounts — cheap
    (O(total nodes), same class of one-per-tick cost the working-set
    rebuild already pays) because the real win is amortizing it across
    every forage-seeking agent's query that tick, the same "compute once
    per tick, share across every agent" shape `Population.tick`'s
    `food_positions`/`granary_positions` precompute already uses one
    call site up. `None` when the extension isn't built (pure-Python
    fallback stays in `Population._nearest_resource`) or before the
    first `tick`."""

    # --- construction ------------------------------------------------------

    @classmethod
    def generate(cls, seed: int, terrain: list[list[Tile]]) -> "ResourceGrid":
        rng = _resource_rng(seed)
        nodes: dict[tuple[int, int], ResourceNode] = {}
        for row in terrain:
            for tile in row:
                if tile.biome in ORE_BIOMES and rng.random() < ORE_NODE_DENSITY:
                    nodes[(tile.x, tile.y)] = ResourceNode(
                        x=tile.x, y=tile.y, kind=ResourceKind.ORE, amount=MAX_ORE_AMOUNT,
                    )
                elif tile.biome in FOOD_BIOMES and rng.random() < NODE_DENSITY:
                    nodes[(tile.x, tile.y)] = ResourceNode(x=tile.x, y=tile.y, kind=ResourceKind.FOOD)
        # Fishing spots are a separate pass keyed on water-adjacency, not
        # biome membership. `nodes` holds one node per tile, so a fish
        # roll on a tile that already got a food/ore node above replaces
        # it — a deliberate tradeoff (this pass runs after the food/ore
        # pass), not an accident: it's what keeps FISH_NODE_DENSITY
        # meaningful without a second per-tile resource slot. See
        # WATER_ADJACENT_BIOMES/FISH_NODE_DENSITY.
        for row in terrain:
            for tile in row:
                if tile.biome in WATER_ADJACENT_BIOMES:
                    continue
                if is_adjacent_to_water(terrain, tile.x, tile.y) and rng.random() < FISH_NODE_DENSITY:
                    nodes[(tile.x, tile.y)] = ResourceNode(
                        x=tile.x, y=tile.y, kind=ResourceKind.FISH, amount=MAX_FISH_AMOUNT,
                    )
        return cls(nodes=nodes)

    # --- queries -------------------------------------------------------------

    def get(self, x: int, y: int) -> ResourceNode | None:
        return self.nodes.get((x, y))

    def nearest_food_or_fish(self, ax: int, ay: int, radius: int) -> tuple[int, int] | None:
        """Native-backed lookup for `Population._nearest_resource`'s
        bounded-box scan (v0.72.2) — `None` when `_native_index` isn't
        built yet (extension unavailable, or before the first `tick`),
        in which case the caller runs its own pure-Python bounded-box
        scan unchanged. See `_native_index`'s docstring for the
        once-per-tick amortization rationale."""
        if self._native_index is None:
            return None
        return self._native_index.nearest(ax, ay, radius)

    def _refresh_native_index(self) -> None:
        if _NativeResourceIndex is None:
            return
        entries = [
            (n.x, n.y, 1 if n.kind is ResourceKind.FISH else 0, n.amount)
            for n in self.nodes.values()
            if n.kind is not ResourceKind.ORE
        ]
        self._native_index = _NativeResourceIndex(entries)

    # --- tick ------------------------------------------------------------------

    def mark_regenerating(self, x: int, y: int) -> None:
        """Register a node as below-cap so the next `tick` regenerates it.
        Call after depleting a node (forage/gather/grazing). A no-op
        before the working set is seeded (the first `tick` seeds every
        node anyway), so callers never need to care about ordering. See
        `_regenerating`. Also live-patches `_native_index` when built
        (v0.72.2) — required for exact equivalence with the pure-Python
        `_nearest_resource` scan: without this, a second agent foraging
        later in the *same* tick would see a stale (pre-depletion)
        native index instead of the just-updated `self.nodes` amount the
        Python path always reads live. See `_native_index`'s docstring."""
        if self._regenerating is not None:
            self._regenerating.add((x, y))
        if self._native_index is not None:
            node = self.nodes.get((x, y))
            if node is not None and node.kind is not ResourceKind.ORE:
                self._native_index.update(x, y, 1 if node.kind is ResourceKind.FISH else 0, node.amount)

    def tick(self, season: str = "summer") -> None:
        if self._regenerating is None:
            # First tick: seed the working set with every node. Full nodes
            # are pruned below on this same pass, so from tick 2 on only
            # genuinely-regenerating nodes are visited.
            self._regenerating = set(self.nodes.keys())
        if _native_tick is not None:
            self._tick_native(season)
        else:
            self._tick_python(season)
        self._refresh_native_index()

    def _tick_native(self, season: str) -> None:
        """Compiled fast path — see cpp/src/resource_grid.cpp. Amounts are
        mutated in a plain dict handed to C++ (not the ResourceNode objects
        themselves; pybind11 doesn't know about our dataclass), then
        written back. Identical arithmetic/branch order to `_tick_python`,
        proven via the SHA-256 resource-state hash harness."""
        positions = list(self._regenerating)
        # C++ side keys amounts/kinds by the same (x << 32) ^ y encoding
        # used internally in resource_grid.cpp — must match exactly.
        def _key(pos: tuple[int, int]) -> int:
            return (pos[0] << 32) ^ (pos[1] & 0xFFFFFFFF)

        amounts = {_key(pos): self.nodes[pos].amount for pos in positions if pos in self.nodes}
        kinds = {_key(pos): self.nodes[pos].kind.value for pos in positions if pos in self.nodes}
        updated, still_regenerating = _native_tick(positions, amounts, kinds, season)
        for pos in positions:
            key = _key(pos)
            if key in updated and pos in self.nodes:
                self.nodes[pos].amount = updated[key]
        self._regenerating = set(still_regenerating)

    def _tick_python(self, season: str) -> None:
        """Pure-Python fallback, used when hearthmind._native isn't built
        (see the import at the top of this module). Kept byte-for-byte
        equivalent to `_tick_native`'s arithmetic — this was the only
        implementation prior to the v0.72.0 native port."""
        multiplier = SEASON_REGEN_MULTIPLIER.get(season, 1.0)
        for pos in list(self._regenerating):
            node = self.nodes.get(pos)
            if node is None:
                self._regenerating.discard(pos)  # node vanished (shouldn't happen, defensive)
                continue
            if node.kind is ResourceKind.ORE:
                cap, regen = MAX_ORE_AMOUNT, ORE_REGEN_PER_TICK * multiplier
            elif node.kind is ResourceKind.FISH:
                cap, regen = MAX_FISH_AMOUNT, FISH_REGEN_PER_TICK * multiplier
            else:
                cap, regen = MAX_NODE_AMOUNT, REGEN_PER_TICK * multiplier
            if node.amount < cap:
                node.amount = min(cap, node.amount + regen)
            if node.amount >= cap:
                self._regenerating.discard(pos)  # topped up — stop visiting until next depletion

    # --- summary -----------------------------------------------------------------

    def summary(self) -> dict:
        food = [n for n in self.nodes.values() if n.kind is ResourceKind.FOOD]
        ore = [n for n in self.nodes.values() if n.kind is ResourceKind.ORE]
        fish = [n for n in self.nodes.values() if n.kind is ResourceKind.FISH]
        return {
            "total_nodes": len(self.nodes),
            "depleted": sum(1 for n in self.nodes.values() if n.amount <= 0.01),
            "avg_amount": round(sum(n.amount for n in self.nodes.values()) / len(self.nodes), 3) if self.nodes else 0.0,
            "food_nodes": len(food),
            "ore_nodes": len(ore),
            "ore_avg_amount": round(sum(n.amount for n in ore) / len(ore), 3) if ore else 0.0,
            "fish_nodes": len(fish),
            "fish_avg_amount": round(sum(n.amount for n in fish) / len(fish), 3) if fish else 0.0,
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {"nodes": [n.to_dict() for n in self.nodes.values()]}

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceGrid":
        nodes: dict[tuple[int, int], ResourceNode] = {}
        for node_data in data["nodes"]:
            node = ResourceNode.from_dict(node_data)
            nodes[(node.x, node.y)] = node
        return cls(nodes=nodes)
