"""The population: the collection of agents living on a World's terrain.

Follows the same determinism discipline as terrain/weather (see
docs/DECISIONS.md, M1-2/M1-3): both initial placement and per-tick behavior
are derived from `(world_seed, tick)` via a namespaced RNG, never from
unseeded `random` calls, so a given seed always produces the same
population history.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from dataclasses import dataclass, field

from hearthmind.agents.agent import (
    CRITICAL_HUNGER_THRESHOLD,
    DIALOGUE_SENTIMENT_DELTA,
    ENERGY_DRAIN_AWAKE,
    ENERGY_RECOVERY_RESTING,
    FORAGE_AMOUNT,
    FORAGE_HUNGER_RELIEF,
    FORAGE_HUNGER_THRESHOLD,
    HUNGER_RATE,
    MATURITY_TICKS,
    MAX_LIFESPAN_TICKS,
    MIN_LIFESPAN_TICKS,
    MOVE_CHANCE,
    POPULATION_CAP,
    REPRODUCTION_AFFINITY_THRESHOLD,
    REPRODUCTION_CHANCE_PER_TICK,
    RELATIONSHIP_DECAY_PER_TICK,
    RELATIONSHIP_GAIN_PER_TICK_COLOCATED,
    REST_THRESHOLD,
    STARVATION_HUNGER_THRESHOLD,
    STARVATION_TICKS_TO_DEATH,
    WAKE_THRESHOLD,
    Agent,
    AgentGoal,
    AgentState,
)
from hearthmind.agents.names import generate_names
from hearthmind.economy.farms import (
    FARM_TOOL_MATERIALS_COST,
    HARVEST_AMOUNT,
    HARVEST_HUNGER_RELIEF,
    PLANT_CHANCE_PER_TICK,
    FarmGrid,
    FarmStage,
)
from hearthmind.settlement.buildings import (
    CONSTRUCTION_MATERIALS_MULTIPLIER,
    CONSTRUCTION_WORK_PER_TICK,
    CURRENCY_CAPACITY,
    CURRENCY_EMERGENCY_HUNGER_RELIEF,
    CURRENCY_EMERGENCY_RATION_COST,
    CURRENCY_PER_OVERFLOW_UNIT,
    GRANARY_CAPACITY,
    GRANARY_DEPOSIT_PER_TICK,
    GRANARY_KIND_CHANCE,
    GRANARY_HUNGER_RELIEF,
    GRANARY_WELLFED_HUNGER_THRESHOLD,
    GRANARY_WITHDRAW_AMOUNT,
    MATERIALS_CAPACITY,
    MATERIALS_GATHER_PER_TICK,
    MATERIALS_PER_CONSTRUCTION_TICK,
    MAX_WORKERS,
    REPAIR_THRESHOLD,
    REPAIR_WORK_PER_TICK,
    SETTLE_CHANCE_PER_TICK,
    TECH_BONUS_PER_LEVEL,
    BuildingKind,
    BuildingStage,
    Settlement,
)
from hearthmind.world.resources import ResourceGrid
from hearthmind.world.terrain import Biome, Tile
from hearthmind.world.wildlife import HUNT_YIELD_PER_ANIMAL, WILDLIFE_SEARCH_RADIUS, Species, WildlifeGrid

WALKABLE_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST, Biome.HILLS, Biome.BEACH})
MATERIAL_BIOMES = frozenset({Biome.FOREST, Biome.HILLS})
"""Where GATHER-goal agents can collect wood/stone — see D8."""

_NEIGHBOR_OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))

FORAGE_SEARCH_RADIUS = 6
"""How far a FORAGE-goal agent can "see" a resource node to move toward,
in Chebyshev distance — beyond this, they fall back to the default wander
behavior. Deliberately local: wild food awareness is plausible only
nearby. SOCIALIZE has no equivalent cap — see docs/DECISIONS.md, D4."""

GATHER_SEARCH_RADIUS = 6
"""Same rationale as FORAGE_SEARCH_RADIUS — local, plausible awareness of
nearby forest/hills, not map-wide. See D8."""

MAX_DIALOGUES_PER_TICK = 3
"""Caps how many LLM-authored dialogue exchanges are scheduled in a
single tick regardless of how many colocated pairs qualify — keeps LLM
load bounded as population/clustering grows, same rationale as
`llm_max_concurrent`. See Population.due_for_dialogue, docs/DECISIONS.md,
E2."""


def _namespaced_rng(seed: int, tick: int, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _tech_factor(settlement: Settlement) -> float:
    """Multiplicative bonus from established inventions — see
    TECH_BONUS_PER_LEVEL, docs/DECISIONS.md, E3."""
    return 1.0 + TECH_BONUS_PER_LEVEL * settlement.tech_level


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
    deaths_starvation: int = 0
    deaths_old_age: int = 0
    """Cumulative counts since world creation, for diagnosis — the
    inhabitant listing only shows who's alive *now*, so without these a
    population crash (many deaths between two snapshots) is invisible in
    `inspect_world` unless you happened to be watching the event log at
    the time. See docs/DECISIONS.md, D5."""
    dialogue_cooldowns: dict[tuple[int, int], int] = field(default_factory=dict)
    """(agent_id, agent_id) sorted pair -> tick of their last dialogue
    exchange, so a stable colocated pair doesn't re-trigger the LLM every
    tick — see due_for_dialogue, docs/DECISIONS.md, E2."""

    # --- construction ------------------------------------------------------

    @classmethod
    def spawn_initial(cls, seed: int, count: int, terrain: list[list[Tile]]) -> "Population":
        rng = _namespaced_rng(seed, tick=0, namespace="population_init")
        spots = _walkable_tiles(terrain)
        names = generate_names(count, rng)

        agents: list[Agent] = []
        for i in range(count):
            x, y = rng.choice(spots)
            max_age = rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS)
            agents.append(Agent(id=i, name=names[i], x=x, y=y, max_age_ticks=max_age))
        return cls(agents=agents, _next_id=count)

    # --- tick ----------------------------------------------------------------

    def tick(
        self, seed: int, tick: int, terrain: list[list[Tile]],
        resources: ResourceGrid, settlement: Settlement, farms: FarmGrid, wildlife: WildlifeGrid,
    ) -> list[tuple[str, str]]:
        """Advance every agent by one tick: needs, foraging, movement,
        relationships, construction/repair, farming, birth, and death.
        Returns life events as (category, description) pairs for the
        caller to log."""
        rng = _namespaced_rng(seed, tick=tick, namespace="population_tick")
        # Snapshot positions before anyone moves this tick, so goal-directed
        # search (SOCIALIZE) sees a consistent picture rather than a mix of
        # this-tick-already-moved and not-yet-moved agents.
        position_snapshot = [(a.id, a.x, a.y) for a in self.agents]

        by_position: dict[tuple[int, int], list[Agent]] = {}
        for agent in self.agents:
            agent.age_ticks += 1
            self._update_needs(agent)
            critically_hungry = agent.hunger >= CRITICAL_HUNGER_THRESHOLD
            if critically_hungry and agent.state is AgentState.RESTING:
                agent.state = AgentState.AWAKE  # emergency wake: starving beats sleeping
            self._maybe_forage(agent, resources, farms, settlement, wildlife)  # can eat while resting, not just awake
            self._maybe_gather(agent, terrain, settlement)
            if agent.hunger >= STARVATION_HUNGER_THRESHOLD:
                agent.starving_ticks += 1
            else:
                agent.starving_ticks = 0
            if (
                agent.state is AgentState.AWAKE and agent.goal is AgentGoal.REST
                and agent.energy < 0.95 and not critically_hungry
            ):
                agent.state = AgentState.RESTING  # proactive rest: a chosen goal, not just necessity
            if agent.state is AgentState.AWAKE:
                self._dispatch_movement(
                    agent, terrain, rng, resources, farms, settlement, wildlife, position_snapshot, critically_hungry
                )
            by_position.setdefault((agent.x, agent.y), []).append(agent)

        self._update_relationships(by_position)
        life_events: list[tuple[str, str]] = []
        life_events.extend(self._advance_construction(by_position, settlement))
        life_events.extend(self._maybe_repair(by_position, settlement))
        self._maybe_stock_granaries(by_position, settlement)
        life_events.extend(self._maybe_start_construction(by_position, settlement, farms, rng))
        life_events.extend(self._maybe_plant(by_position, farms, settlement, terrain, rng))
        life_events.extend(self._maybe_reproduce(by_position, rng))
        life_events.extend(self._apply_deaths())
        return life_events

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
    def _maybe_forage(
        agent: Agent, resources: ResourceGrid, farms: FarmGrid, settlement: Settlement, wildlife: WildlifeGrid,
    ) -> None:
        if agent.hunger < FORAGE_HUNGER_THRESHOLD:
            return

        # A ready farm plot is preferred over wild foraging — better yield,
        # and it's the deliberate incentive for cultivating one at all.
        plot = farms.get(agent.x, agent.y)
        if plot is not None and plot.stage is FarmStage.READY:
            consumed = farms.harvest(agent.x, agent.y, HARVEST_AMOUNT)
            if consumed > 0:
                relief = HARVEST_HUNGER_RELIEF * (consumed / HARVEST_AMOUNT) * _tech_factor(settlement)
                agent.hunger = max(0.0, agent.hunger - relief)
                return

        # A stocked granary is preferred over wild foraging too — a
        # deliberate community buffer, second only to a fresh farm.
        granary = settlement.at(agent.x, agent.y)
        if (
            granary is not None and granary.kind is BuildingKind.GRANARY
            and granary.stage is BuildingStage.STANDING and granary.stored_food > 0
        ):
            consumed = min(granary.stored_food, GRANARY_WITHDRAW_AMOUNT)
            granary.stored_food -= consumed
            relief = GRANARY_HUNGER_RELIEF * (consumed / GRANARY_WITHDRAW_AMOUNT) * _tech_factor(settlement)
            agent.hunger = max(0.0, agent.hunger - relief)
            return

        # A colocated grazer herd can be hunted for a richer yield than
        # wild foraging — a finite, huntable resource like a resource
        # node, but mobile and shared with predators. See docs/DECISIONS.md, A4.
        for herd in wildlife.at(agent.x, agent.y):
            if herd.species is Species.GRAZER and herd.count > 0:
                killed = wildlife.hunt(herd.id, amount=1)
                if killed > 0:
                    agent.hunger = max(0.0, agent.hunger - HUNT_YIELD_PER_ANIMAL * killed)
                    return
                break

        node = resources.get(agent.x, agent.y)
        if node is not None and node.amount > 0:
            consumed = min(node.amount, FORAGE_AMOUNT)
            node.amount -= consumed
            relief = FORAGE_HUNGER_RELIEF * (consumed / FORAGE_AMOUNT)
            agent.hunger = max(0.0, agent.hunger - relief)
            return

        # Last resort: buy emergency rations with settlement currency at a
        # standing granary (the village's trade post) — only reachable
        # once nothing free is available. See D10.
        if (
            granary is not None and granary.kind is BuildingKind.GRANARY
            and granary.stage is BuildingStage.STANDING
            and settlement.currency >= CURRENCY_EMERGENCY_RATION_COST
        ):
            settlement.currency -= CURRENCY_EMERGENCY_RATION_COST
            agent.hunger = max(0.0, agent.hunger - CURRENCY_EMERGENCY_HUNGER_RELIEF)

    @staticmethod
    def _maybe_gather(agent: Agent, terrain: list[list[Tile]], settlement: Settlement) -> None:
        """GATHER-goal agents on forest/hills feed the settlement's shared
        materials stockpile — awake-only (unlike foraging, this isn't a
        survival mechanic, so no resting-interrupt applies). See D8."""
        if agent.goal is not AgentGoal.GATHER or agent.state is not AgentState.AWAKE:
            return
        if terrain[agent.y][agent.x].biome not in MATERIAL_BIOMES:
            return
        # A full stockpile doesn't waste the surplus — it sells to an
        # abstract outside economy instead (D10).
        if settlement.materials >= MATERIALS_CAPACITY:
            settlement.currency = min(
                CURRENCY_CAPACITY, settlement.currency + MATERIALS_GATHER_PER_TICK * CURRENCY_PER_OVERFLOW_UNIT
            )
            return
        settlement.materials = min(MATERIALS_CAPACITY, settlement.materials + MATERIALS_GATHER_PER_TICK)

    @staticmethod
    def _maybe_plant(
        by_position: dict[tuple[int, int], list[Agent]], farms: FarmGrid, settlement: Settlement,
        terrain: list[list[Tile]], rng: random.Random,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        for (x, y), group in by_position.items():
            if farms.get(x, y) is not None or settlement.at(x, y) is not None:
                continue
            if not FarmGrid.is_farmable(terrain, x, y):
                continue
            if not any(a.state is AgentState.AWAKE for a in group):
                continue
            if rng.random() >= PLANT_CHANCE_PER_TICK:
                continue
            tooled = settlement.materials >= FARM_TOOL_MATERIALS_COST
            if tooled:
                settlement.materials -= FARM_TOOL_MATERIALS_COST
            farms.plant(x, y, tooled=tooled)
            note = "tooled field" if tooled else "field"
            life_events.append(("farm_planted", f"A {note} was planted at ({x}, {y})."))
        return life_events

    @classmethod
    def _dispatch_movement(
        cls, agent: Agent, terrain: list[list[Tile]], rng: random.Random,
        resources: ResourceGrid, farms: FarmGrid, settlement: Settlement, wildlife: WildlifeGrid,
        position_snapshot: list[tuple[int, int, int]], critically_hungry: bool = False,
    ) -> None:
        """Goal-directed agents (FORAGE/SOCIALIZE) take a deliberate step
        toward a visible target when one exists; otherwise (including
        WANDER, the default/pre-Phase-B behavior) fall back to the
        original probabilistic random walk.

        `critically_hungry` overrides whatever goal is assigned and forces
        FORAGE-seeking instead: goals are only reevaluated once per
        sim-day (see `due_for_cognition`), so an agent assigned e.g.
        SOCIALIZE while well-fed can otherwise drift toward starvation
        with nothing making it deliberately look for food until its next
        daily reevaluation — the D3 emergency-wake only got a resting
        agent back onto its feet, it never redirected where an *awake*
        agent walks. See docs/DECISIONS.md, D5."""
        effective_goal = AgentGoal.FORAGE if critically_hungry else agent.goal
        target = None
        if effective_goal is AgentGoal.FORAGE:
            target = (
                cls._nearest_ready_farm(agent, farms)
                or cls._nearest_stocked_granary(agent, settlement)
                or cls._nearest_grazer_herd(agent, wildlife)
                or cls._nearest_resource(agent, resources)
            )
        elif effective_goal is AgentGoal.SOCIALIZE:
            target = cls._nearest_other_agent(agent, position_snapshot)
        elif effective_goal is AgentGoal.GATHER:
            target = cls._nearest_material_tile(agent, terrain)

        if target is not None and cls._step_toward(agent, target, terrain):
            return
        cls._maybe_move(agent, terrain, rng)

    @staticmethod
    def _nearest_ready_farm(agent: Agent, farms: FarmGrid) -> tuple[int, int] | None:
        """No distance cap, unlike `_nearest_resource`: found root cause of
        the D6 starvation cascade — FORAGE previously only ever targeted
        wild nodes, so a hungry agent standing next to dozens of
        harvest-ready farms (planted by the same population) would starve
        rather than walk to one, because nothing pointed it there.
        Cultivated land is known to its community the same way SOCIALIZE
        treats other agents as known (D4) — see docs/DECISIONS.md, D6."""
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for (x, y), plot in farms.plots.items():
            if plot.stage is not FarmStage.READY:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _nearest_stocked_granary(agent: Agent, settlement: Settlement) -> tuple[int, int] | None:
        """No distance cap, same rationale as `_nearest_ready_farm` — a
        built granary is a known community landmark. See docs/DECISIONS.md,
        D7. Also a target when empty of stored food but the settlement has
        currency for emergency rations (D10) — either way, worth the walk."""
        can_buy_rations = settlement.currency >= CURRENCY_EMERGENCY_RATION_COST
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for building in settlement.buildings:
            if building.kind is not BuildingKind.GRANARY or building.stage is not BuildingStage.STANDING:
                continue
            if building.stored_food <= 0 and not can_buy_rations:
                continue
            dist = abs(building.x - agent.x) + abs(building.y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (building.x, building.y), dist
        return best

    @staticmethod
    def _nearest_grazer_herd(agent: Agent, wildlife: WildlifeGrid) -> tuple[int, int] | None:
        herd = wildlife.nearest_grazer_herd(agent.x, agent.y, WILDLIFE_SEARCH_RADIUS)
        return (herd.x, herd.y) if herd is not None else None

    @staticmethod
    def _nearest_resource(agent: Agent, resources: ResourceGrid) -> tuple[int, int] | None:
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for (x, y), node in resources.nodes.items():
            if node.amount <= 0:
                continue
            if max(abs(x - agent.x), abs(y - agent.y)) > FORAGE_SEARCH_RADIUS:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _nearest_material_tile(agent: Agent, terrain: list[list[Tile]]) -> tuple[int, int] | None:
        """Scans a bounded box (no discrete registry like resources/farms
        exist for terrain biomes) within GATHER_SEARCH_RADIUS. See D8."""
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for dy in range(-GATHER_SEARCH_RADIUS, GATHER_SEARCH_RADIUS + 1):
            y = agent.y + dy
            if not (0 <= y < height):
                continue
            for dx in range(-GATHER_SEARCH_RADIUS, GATHER_SEARCH_RADIUS + 1):
                x = agent.x + dx
                if not (0 <= x < width):
                    continue
                if terrain[y][x].biome not in MATERIAL_BIOMES:
                    continue
                dist = abs(dx) + abs(dy)
                if best_dist is None or dist < best_dist:
                    best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _nearest_other_agent(
        agent: Agent, position_snapshot: list[tuple[int, int, int]]
    ) -> tuple[int, int] | None:
        """No distance cap, unlike _nearest_resource: an agent actively
        seeking company is assumed to know roughly where the (small)
        population's other members are, not just what's locally visible —
        see docs/DECISIONS.md, D4."""
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for other_id, x, y in position_snapshot:
            if other_id == agent.id:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _step_toward(agent: Agent, target: tuple[int, int], terrain: list[list[Tile]]) -> bool:
        """Take one greedy step toward `target`. Returns False (and leaves
        `agent` unmoved) if already there or if both preferred directions
        are blocked, so the caller can fall back to wandering."""
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
        for cdx, cdy in steps:
            nx, ny = agent.x + cdx, agent.y + cdy
            if 0 <= nx < width and 0 <= ny < height and _is_walkable(terrain, nx, ny):
                agent.x, agent.y = nx, ny
                return True
        return False

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

    @staticmethod
    def _update_relationships(by_position: dict[tuple[int, int], list[Agent]]) -> None:
        agents_by_id = {a.id: a for group in by_position.values() for a in group}
        for agent in agents_by_id.values():
            for other_id in list(agent.relationships):
                # Pulls toward 0 from whichever side it's on — relationship
                # values range -1..1 as of E2 (rivalry as well as affinity),
                # so decay can no longer just clamp at a 0.0 floor.
                value = agent.relationships[other_id]
                if value > 0.0:
                    agent.relationships[other_id] = max(0.0, value - RELATIONSHIP_DECAY_PER_TICK)
                elif value < 0.0:
                    agent.relationships[other_id] = min(0.0, value + RELATIONSHIP_DECAY_PER_TICK)
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                a.relationships[b.id] = min(
                    1.0, a.relationships.get(b.id, 0.0) + RELATIONSHIP_GAIN_PER_TICK_COLOCATED
                )
                b.relationships[a.id] = min(
                    1.0, b.relationships.get(a.id, 0.0) + RELATIONSHIP_GAIN_PER_TICK_COLOCATED
                )

    def _maybe_reproduce(
        self, by_position: dict[tuple[int, int], list[Agent]], rng: random.Random
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        if len(self.agents) >= POPULATION_CAP:
            return life_events

        newborns: list[Agent] = []
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                if len(self.agents) + len(newborns) >= POPULATION_CAP:
                    break
                if not (self._is_mature(a) and self._is_mature(b)):
                    continue
                if not (self._is_healthy(a) and self._is_healthy(b)):
                    continue
                if a.relationships.get(b.id, 0.0) < REPRODUCTION_AFFINITY_THRESHOLD:
                    continue
                if rng.random() >= REPRODUCTION_CHANCE_PER_TICK:
                    continue

                child_name = generate_names(1, rng)[0]
                child = Agent(
                    id=self._next_id,
                    name=child_name,
                    x=a.x,
                    y=a.y,
                    max_age_ticks=rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS),
                    parents=(a.id, b.id),
                )
                self._next_id += 1
                newborns.append(child)
                life_events.append(("birth", f"{child.name} was born to {a.name} and {b.name}."))

        self.agents.extend(newborns)
        return life_events

    @staticmethod
    def _is_mature(agent: Agent) -> bool:
        return agent.age_ticks >= MATURITY_TICKS

    @staticmethod
    def _is_healthy(agent: Agent) -> bool:
        return agent.hunger <= 0.7 and agent.energy >= 0.3

    # --- settlement: construction & repair (Phase C) --------------------------

    @staticmethod
    def _advance_construction(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        for building in settlement.buildings:
            if building.stage is not BuildingStage.UNDER_CONSTRUCTION:
                continue
            workers = sum(
                1 for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE
            )
            if workers == 0:
                continue
            work = CONSTRUCTION_WORK_PER_TICK * min(workers, MAX_WORKERS) * _tech_factor(settlement)
            if settlement.materials >= MATERIALS_PER_CONSTRUCTION_TICK:
                settlement.materials -= MATERIALS_PER_CONSTRUCTION_TICK
                work *= CONSTRUCTION_MATERIALS_MULTIPLIER
            building.progress = min(1.0, building.progress + work)
            if building.progress >= 1.0:
                building.stage = BuildingStage.STANDING
                building.condition = 1.0
                life_events.append(("building_completed", f"A structure was completed at ({building.x}, {building.y})."))
        return life_events

    @staticmethod
    def _maybe_repair(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> list[tuple[str, str]]:
        for building in settlement.buildings:
            if building.stage is not BuildingStage.STANDING or building.condition >= REPAIR_THRESHOLD:
                continue
            workers = sum(
                1 for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE
            )
            if workers == 0:
                continue
            repair = REPAIR_WORK_PER_TICK * min(workers, MAX_WORKERS) * _tech_factor(settlement)
            building.condition = min(1.0, building.condition + repair)
        return []  # repair progress isn't eventful enough on its own to log per-tick

    @classmethod
    def _maybe_start_construction(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement,
        farms: FarmGrid, rng: random.Random,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        for (x, y), group in by_position.items():
            if len(group) < 2 or settlement.at(x, y) is not None or farms.get(x, y) is not None:
                continue
            eligible = [a for a in group if cls._is_mature(a) and cls._is_healthy(a)]
            if len(eligible) < 2:
                continue
            if rng.random() >= SETTLE_CHANCE_PER_TICK:
                continue
            kind = BuildingKind.GRANARY if rng.random() < GRANARY_KIND_CHANCE else BuildingKind.HUT
            settlement.start_construction(x, y, kind=kind)
            life_events.append(("construction_started", f"{kind.value.capitalize()} construction began at ({x}, {y})."))
        return life_events

    @staticmethod
    def _maybe_stock_granaries(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> None:
        """Well-fed awake agents present at a standing granary passively
        contribute surplus each tick — presence-driven like every other
        mechanic here, not a hauling/inventory system. See
        docs/DECISIONS.md, D7. A full granary sells the surplus instead of
        wasting it (D10)."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.GRANARY or building.stage is not BuildingStage.STANDING:
                continue
            contributors = sum(
                1 for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if contributors == 0:
                continue
            deposit = GRANARY_DEPOSIT_PER_TICK * contributors * _tech_factor(settlement)
            if building.stored_food >= GRANARY_CAPACITY:
                settlement.currency = min(
                    CURRENCY_CAPACITY, settlement.currency + deposit * CURRENCY_PER_OVERFLOW_UNIT
                )
                continue
            building.stored_food = min(GRANARY_CAPACITY, building.stored_food + deposit)

    def _apply_deaths(self) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        survivors: list[Agent] = []
        for agent in self.agents:
            if agent.starving_ticks >= STARVATION_TICKS_TO_DEATH:
                life_events.append(("death", f"{agent.name} died of starvation."))
                self.deaths_starvation += 1
                continue
            if agent.age_ticks >= agent.max_age_ticks:
                life_events.append(("death", f"{agent.name} died of old age."))
                self.deaths_old_age += 1
                continue
            survivors.append(agent)
        self.agents = survivors
        return life_events

    # --- cognition (Phase B) --------------------------------------------------

    def due_for_cognition(self, tick: int, ticks_per_day: int) -> list[Agent]:
        """Agents whose once-per-sim-day goal reevaluation falls on this
        tick. Staggered by agent id (rather than all agents re-deciding on
        the same tick) so a full day's worth of LLM calls spreads evenly
        across the day instead of arriving in one burst — see
        docs/DECISIONS.md, B2."""
        if ticks_per_day <= 0:
            return []
        return [agent for agent in self.agents if (tick + agent.id) % ticks_per_day == 0]

    def apply_goal(self, agent_id: int, goal: AgentGoal, reason: str) -> None:
        """Apply a resolved goal to an agent by id. A no-op if the agent
        has since died — cognition results can arrive on a later tick than
        they were requested on (see SimulationEngine)."""
        for agent in self.agents:
            if agent.id == agent_id:
                agent.goal = goal
                agent.goal_reason = reason
                return

    def get(self, agent_id: int) -> Agent | None:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    # --- dialogue (Phase E2) ---------------------------------------------------

    def due_for_dialogue(self, seed: int, tick: int, cooldown_ticks: int) -> list[tuple[Agent, Agent]]:
        """Colocated, awake pairs whose cooldown has expired, capped at
        MAX_DIALOGUES_PER_TICK and chosen deterministically (namespaced
        RNG shuffle, not scan order) so which pairs talk first is
        reproducible for a given seed. Marks the selected pairs' cooldown
        immediately (not when the LLM result arrives) — the cooldown
        itself prevents re-selecting a pair while its exchange is still
        in flight, so no separate inflight-tracking set is needed. See
        docs/DECISIONS.md, E2."""
        by_position: dict[tuple[int, int], list[Agent]] = {}
        for agent in self.agents:
            if agent.state is AgentState.AWAKE:
                by_position.setdefault((agent.x, agent.y), []).append(agent)

        candidates: list[tuple[Agent, Agent]] = []
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                last = self.dialogue_cooldowns.get((a.id, b.id), -cooldown_ticks)
                if tick - last < cooldown_ticks:
                    continue
                candidates.append((a, b))
        if not candidates:
            return []

        rng = _namespaced_rng(seed, tick, "dialogue_select")
        rng.shuffle(candidates)
        selected = candidates[:MAX_DIALOGUES_PER_TICK]
        for a, b in selected:
            self.dialogue_cooldowns[(a.id, b.id)] = tick
        return selected

    def apply_dialogue(self, a_id: int, b_id: int, sentiment: str) -> tuple[Agent, Agent] | None:
        """Apply a resolved dialogue's sentiment as a relationship nudge,
        on top of the passive per-tick colocation gain. Returns None (a
        no-op) if either agent has since died — dialogue results can
        arrive on a later tick than requested, same as cognition."""
        agent_a, agent_b = self.get(a_id), self.get(b_id)
        if agent_a is None or agent_b is None:
            return None
        delta = DIALOGUE_SENTIMENT_DELTA.get(sentiment, 0.0)
        if delta:
            agent_a.relationships[b_id] = max(-1.0, min(1.0, agent_a.relationships.get(b_id, 0.0) + delta))
            agent_b.relationships[a_id] = max(-1.0, min(1.0, agent_b.relationships.get(a_id, 0.0) + delta))
        return agent_a, agent_b

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        total = len(self.agents)
        resting = sum(1 for a in self.agents if a.state is AgentState.RESTING)
        avg_hunger = sum(a.hunger for a in self.agents) / total if total else 0.0
        avg_energy = sum(a.energy for a in self.agents) / total if total else 0.0
        avg_age = sum(a.age_ticks for a in self.agents) / total if total else 0.0
        return {
            "total": total,
            "awake": total - resting,
            "resting": resting,
            "avg_hunger": round(avg_hunger, 3),
            "avg_energy": round(avg_energy, 3),
            "avg_age_ticks": round(avg_age, 1),
            "deaths_starvation": self.deaths_starvation,
            "deaths_old_age": self.deaths_old_age,
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "agents": [a.to_dict() for a in self.agents],
            "next_id": self._next_id,
            "deaths_starvation": self.deaths_starvation,
            "deaths_old_age": self.deaths_old_age,
            "dialogue_cooldowns": {
                f"{a_id}:{b_id}": tick for (a_id, b_id), tick in self.dialogue_cooldowns.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Population":
        agents = [Agent.from_dict(a) for a in data["agents"]]
        dialogue_cooldowns = {}
        for key, tick in data.get("dialogue_cooldowns", {}).items():
            a_id, b_id = key.split(":")
            dialogue_cooldowns[(int(a_id), int(b_id))] = tick
        return cls(
            agents=agents,
            _next_id=data["next_id"],
            deaths_starvation=data.get("deaths_starvation", 0),
            deaths_old_age=data.get("deaths_old_age", 0),
            dialogue_cooldowns=dialogue_cooldowns,
        )
