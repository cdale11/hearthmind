"""The population: the collection of agents living on a World's terrain.

Follows the same determinism discipline as terrain/weather (see
docs/DECISIONS.md, M1-2/M1-3): both initial placement and per-tick behavior
are derived from `(world_seed, tick)` via a namespaced RNG, never from
unseeded `random` calls, so a given seed always produces the same
population history.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from hearthmind.agents.agent import (
    ENERGY_DRAIN_AWAKE,
    ENERGY_RECOVERY_RESTING,
    HUNGER_RATE,
    MOVE_CHANCE,
    REST_THRESHOLD,
    WAKE_THRESHOLD,
    Agent,
    AgentState,
)
from hearthmind.agents.names import generate_names
from hearthmind.world.terrain import Biome, Tile

WALKABLE_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST, Biome.HILLS, Biome.BEACH})

_NEIGHBOR_OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))


def _namespaced_rng(seed: int, tick: int, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _is_walkable(terrain: list[list[Tile]], x: int, y: int) -> bool:
    return terrain[y][x].biome in WALKABLE_BIOMES


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


@dataclass
class Population:
    agents: list[Agent] = field(default_factory=list)
    _next_id: int = 0

    # --- construction ------------------------------------------------------

    @classmethod
    def spawn_initial(cls, seed: int, count: int, terrain: list[list[Tile]]) -> "Population":
        rng = _namespaced_rng(seed, tick=0, namespace="population_init")
        spots = _walkable_tiles(terrain)
        names = generate_names(count, rng)

        agents: list[Agent] = []
        for i in range(count):
            x, y = rng.choice(spots)
            agents.append(Agent(id=i, name=names[i], x=x, y=y))
        return cls(agents=agents, _next_id=count)

    # --- tick ----------------------------------------------------------------

    def tick(self, seed: int, tick: int, terrain: list[list[Tile]]) -> None:
        rng = _namespaced_rng(seed, tick=tick, namespace="population_tick")
        for agent in self.agents:
            self._update_needs(agent)
            if agent.state is AgentState.AWAKE:
                self._maybe_move(agent, terrain, rng)

    @staticmethod
    def _update_needs(agent: Agent) -> None:
        agent.hunger = min(1.0, agent.hunger + HUNGER_RATE)
        if agent.state is AgentState.RESTING:
            agent.energy = min(1.0, agent.energy + ENERGY_RECOVERY_RESTING)
            if agent.energy >= WAKE_THRESHOLD:
                agent.state = AgentState.AWAKE
        else:
            agent.energy = max(0.0, agent.energy - ENERGY_DRAIN_AWAKE)
            if agent.energy <= REST_THRESHOLD:
                agent.state = AgentState.RESTING

    @staticmethod
    def _maybe_move(agent: Agent, terrain: list[list[Tile]], rng: random.Random) -> None:
        if rng.random() >= MOVE_CHANCE:
            return
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        candidates = []
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = agent.x + dx, agent.y + dy
            if 0 <= nx < width and 0 <= ny < height and _is_walkable(terrain, nx, ny):
                candidates.append((nx, ny))
        if candidates:
            agent.x, agent.y = rng.choice(candidates)

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        total = len(self.agents)
        resting = sum(1 for a in self.agents if a.state is AgentState.RESTING)
        avg_hunger = sum(a.hunger for a in self.agents) / total if total else 0.0
        avg_energy = sum(a.energy for a in self.agents) / total if total else 0.0
        return {
            "total": total,
            "awake": total - resting,
            "resting": resting,
            "avg_hunger": round(avg_hunger, 3),
            "avg_energy": round(avg_energy, 3),
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "agents": [a.to_dict() for a in self.agents],
            "next_id": self._next_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Population":
        agents = [Agent.from_dict(a) for a in data["agents"]]
        return cls(agents=agents, _next_id=data["next_id"])
