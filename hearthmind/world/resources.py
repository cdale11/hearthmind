"""Discrete, depletable resource nodes scattered across terrain.

Emergence lever: resource nodes are finite and regenerate slowly, so local
overforaging genuinely matters — a population that grows faster than its
foraging grounds regenerate should feel real scarcity, not draw from an
infinite pantry. See docs/DECISIONS.md, A1.

Two kinds as of the resource-variety pass: FOOD ("bush" — wild forage,
grassland/forest/hills, fast regen) and ORE ("mine" — GATHER-goal
material source, hills only, regenerates far slower than food. Forest
wood is deliberately NOT a discrete/depletable resource here — see
Population._maybe_gather for why. See docs/DECISIONS.md, resource-variety
pass.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from enum import Enum

from hearthmind.world.terrain import Biome, Tile


class ResourceKind(str, Enum):
    FOOD = "food"
    ORE = "ore"


FOOD_BIOMES = frozenset({Biome.FOREST, Biome.GRASSLAND, Biome.HILLS})
ORE_BIOMES = frozenset({Biome.HILLS})
"""Ore only on hills (not mountain — mountain isn't a walkable biome, see
agents/population.py's WALKABLE_BIOMES, so an unreachable ore vein there
would be pointless)."""

NODE_DENSITY = 0.12
"""Fraction of FOOD_BIOMES tiles that get a food node at world creation."""

ORE_NODE_DENSITY = 0.06
"""Fraction of hills tiles that get an ore node instead of a food node —
rolled before the food roll on hills specifically (see `generate`), so a
hills tile is one or the other, never both."""

MAX_NODE_AMOUNT = 1.0
MAX_ORE_AMOUNT = 2.0
"""A mineral vein holds more than a berry bush, but see ORE_REGEN_PER_TICK
— it takes far longer to refill."""

REGEN_PER_TICK = 0.002
"""~500 ticks (about 5 sim-days at default pacing) to fully regrow from empty."""

ORE_REGEN_PER_TICK = REGEN_PER_TICK / 12
"""~12x slower than food (and from double the max amount) — a depleted
vein takes on the order of 60 sim-days to fully recover, not 5. "Mines
recover over longer time" is the concrete ask this constant answers."""

SEASON_REGEN_MULTIPLIER = {"winter": 0.3, "autumn": 0.75, "spring": 1.1, "summer": 1.0}
"""Regeneration multiplier by season name, applied to both kinds —
winter genuinely slows regrowth (frozen ground is harder to forage *and*
harder to mine). Same rationale/pattern as
economy.farms.SEASON_GROWTH_MULTIPLIER; a season absent from this table
defaults to 1.0. See docs/DECISIONS.md, scarcity pass."""


def _resource_rng(seed: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:resources_init".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


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
        return cls(nodes=nodes)

    # --- queries -------------------------------------------------------------

    def get(self, x: int, y: int) -> ResourceNode | None:
        return self.nodes.get((x, y))

    # --- tick ------------------------------------------------------------------

    def tick(self, season: str = "summer") -> None:
        multiplier = SEASON_REGEN_MULTIPLIER.get(season, 1.0)
        for node in self.nodes.values():
            if node.kind is ResourceKind.ORE:
                cap, regen = MAX_ORE_AMOUNT, ORE_REGEN_PER_TICK * multiplier
            else:
                cap, regen = MAX_NODE_AMOUNT, REGEN_PER_TICK * multiplier
            if node.amount < cap:
                node.amount = min(cap, node.amount + regen)

    # --- summary -----------------------------------------------------------------

    def summary(self) -> dict:
        food = [n for n in self.nodes.values() if n.kind is ResourceKind.FOOD]
        ore = [n for n in self.nodes.values() if n.kind is ResourceKind.ORE]
        return {
            "total_nodes": len(self.nodes),
            "depleted": sum(1 for n in self.nodes.values() if n.amount <= 0.01),
            "avg_amount": round(sum(n.amount for n in self.nodes.values()) / len(self.nodes), 3) if self.nodes else 0.0,
            "food_nodes": len(food),
            "ore_nodes": len(ore),
            "ore_avg_amount": round(sum(n.amount for n in ore) / len(ore), 3) if ore else 0.0,
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
