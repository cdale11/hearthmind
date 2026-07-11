"""Discrete, depletable forageable resource nodes scattered across terrain.

Emergence lever: resource nodes are finite and regenerate slowly, so local
overforaging genuinely matters — a population that grows faster than its
foraging grounds regenerate should feel real scarcity, not draw from an
infinite pantry. See docs/DECISIONS.md, A1.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from hearthmind.world.terrain import Biome, Tile

FORAGEABLE_BIOMES = frozenset({Biome.FOREST, Biome.GRASSLAND, Biome.HILLS})

NODE_DENSITY = 0.12
"""Fraction of forageable-biome tiles that get a resource node at world creation."""

MAX_NODE_AMOUNT = 1.0

REGEN_PER_TICK = 0.002
"""~500 ticks (about 5 sim-days at default pacing) to fully regrow from empty."""

SEASON_REGEN_MULTIPLIER = {"winter": 0.3, "autumn": 0.75, "spring": 1.1, "summer": 1.0}
"""Wild-resource regeneration multiplier by season name — winter
genuinely slows regrowth. Same rationale/pattern as
economy.farms.SEASON_GROWTH_MULTIPLIER; a season absent from this table
defaults to 1.0. See docs/DECISIONS.md, scarcity pass."""


def _resource_rng(seed: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:resources_init".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


@dataclass
class ResourceNode:
    x: int
    y: int
    amount: float = MAX_NODE_AMOUNT

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "amount": round(self.amount, 4)}

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceNode":
        return cls(x=data["x"], y=data["y"], amount=data["amount"])


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
                if tile.biome in FORAGEABLE_BIOMES and rng.random() < NODE_DENSITY:
                    nodes[(tile.x, tile.y)] = ResourceNode(x=tile.x, y=tile.y)
        return cls(nodes=nodes)

    # --- queries -------------------------------------------------------------

    def get(self, x: int, y: int) -> ResourceNode | None:
        return self.nodes.get((x, y))

    # --- tick ------------------------------------------------------------------

    def tick(self, season: str = "summer") -> None:
        regen = REGEN_PER_TICK * SEASON_REGEN_MULTIPLIER.get(season, 1.0)
        for node in self.nodes.values():
            if node.amount < MAX_NODE_AMOUNT:
                node.amount = min(MAX_NODE_AMOUNT, node.amount + regen)

    # --- summary -----------------------------------------------------------------

    def summary(self) -> dict:
        total = len(self.nodes)
        depleted = sum(1 for n in self.nodes.values() if n.amount <= 0.01)
        avg_amount = sum(n.amount for n in self.nodes.values()) / total if total else 0.0
        return {"total_nodes": total, "depleted": depleted, "avg_amount": round(avg_amount, 3)}

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
