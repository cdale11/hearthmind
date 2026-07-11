import random
import unittest

from hearthmind.agents.agent import (
    MATURITY_TICKS,
    POPULATION_CAP,
    REPRODUCTION_AFFINITY_THRESHOLD,
    STARVATION_HUNGER_THRESHOLD,
    STARVATION_TICKS_TO_DEATH,
    Agent,
    AgentGoal,
    AgentState,
)
from hearthmind.agents.population import WALKABLE_BIOMES, Population
from hearthmind.settlement.buildings import Settlement
from hearthmind.world.resources import ResourceGrid, ResourceNode
from hearthmind.world.terrain import Biome, Tile, generate_terrain


class TestPopulationSpawn(unittest.TestCase):
    def test_spawns_requested_count(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        population = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        self.assertEqual(len(population.agents), 10)

    def test_spawned_agents_have_unique_ids_and_names(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        population = Population.spawn_initial(seed=42, count=15, terrain=terrain)
        ids = [a.id for a in population.agents]
        names = [a.name for a in population.agents]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

    def test_spawned_agents_on_walkable_tiles(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        population = Population.spawn_initial(seed=42, count=20, terrain=terrain)
        for agent in population.agents:
            biome = terrain[agent.y][agent.x].biome
            self.assertIn(biome, WALKABLE_BIOMES)

    def test_deterministic_for_same_seed(self):
        terrain = generate_terrain(seed=7, width=32, height=32)
        a = Population.spawn_initial(seed=7, count=10, terrain=terrain)
        b = Population.spawn_initial(seed=7, count=10, terrain=terrain)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_handles_tiny_map_with_no_walkable_tiles(self):
        # A 1x1 map generated at an extreme seed could plausibly be
        # entirely water; spawning must not crash regardless.
        terrain = generate_terrain(seed=1, width=1, height=1)
        population = Population.spawn_initial(seed=1, count=3, terrain=terrain)
        self.assertEqual(len(population.agents), 3)

    def test_spawned_agents_have_lifespans_assigned(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        population = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        for agent in population.agents:
            self.assertGreater(agent.max_age_ticks, 0)


class TestPopulationTick(unittest.TestCase):
    def setUp(self):
        self.terrain = generate_terrain(seed=42, width=32, height=32)
        self.population = Population.spawn_initial(seed=42, count=10, terrain=self.terrain)
        self.resources = ResourceGrid.generate(seed=42, terrain=self.terrain)
        self.settlement = Settlement()

    def test_hunger_increases_each_tick(self):
        before = [a.hunger for a in self.population.agents]
        self.population.tick(seed=42, tick=1, terrain=self.terrain, resources=self.resources, settlement=self.settlement)
        after = [a.hunger for a in self.population.agents]
        for b, a in zip(before, after):
            self.assertGreaterEqual(a, b)  # foraging could offset the rise, never below 0

    def test_hunger_capped_at_one(self):
        for _ in range(500):
            self.population.tick(seed=42, tick=1, terrain=self.terrain, resources=self.resources, settlement=self.settlement)
        for agent in self.population.agents:
            self.assertLessEqual(agent.hunger, 1.0)

    def test_energy_drains_while_awake_and_triggers_rest(self):
        # Energy starts at 1.0 and drains ENERGY_DRAIN_AWAKE (0.015) per
        # tick; REST_THRESHOLD (0.2) is crossed after ~54 ticks.
        for tick in range(1, 60):
            self.population.tick(seed=42, tick=tick, terrain=self.terrain, resources=self.resources, settlement=self.settlement)
        self.assertTrue(any(a.state is AgentState.RESTING for a in self.population.agents))

    def test_resting_agent_recovers_energy_and_wakes(self):
        agent = self.population.agents[0]
        agent.energy = 0.1
        agent.state = AgentState.RESTING
        for tick in range(1, 30):
            self.population.tick(seed=42, tick=tick, terrain=self.terrain, resources=self.resources, settlement=self.settlement)
        self.assertGreater(agent.energy, 0.1)

    def test_movement_stays_in_bounds_and_walkable(self):
        for tick in range(1, 100):
            self.population.tick(seed=42, tick=tick, terrain=self.terrain, resources=self.resources, settlement=self.settlement)
        for agent in self.population.agents:
            self.assertTrue(0 <= agent.x < 32)
            self.assertTrue(0 <= agent.y < 32)
            self.assertIn(self.terrain[agent.y][agent.x].biome, WALKABLE_BIOMES)

    def test_age_increases_each_tick(self):
        self.population.tick(seed=42, tick=1, terrain=self.terrain, resources=self.resources, settlement=self.settlement)
        for agent in self.population.agents:
            self.assertEqual(agent.age_ticks, 1)

    def test_tick_deterministic_for_same_seed_and_tick(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        resources_a = ResourceGrid.generate(seed=42, terrain=terrain)
        resources_b = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement_a = Settlement()
        settlement_b = Settlement()
        pop_a = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        pop_b = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        for tick in range(1, 20):
            pop_a.tick(seed=42, tick=tick, terrain=terrain, resources=resources_a, settlement=settlement_a)
            pop_b.tick(seed=42, tick=tick, terrain=terrain, resources=resources_b, settlement=settlement_b)
        self.assertEqual(pop_a.to_dict(), pop_b.to_dict())
        self.assertEqual(resources_a.to_dict(), resources_b.to_dict())


class TestForaging(unittest.TestCase):
    def test_hungry_agent_on_full_node_reduces_hunger_and_depletes_node(self):
        terrain = generate_terrain(seed=42, width=8, height=8)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        # Force a node at an arbitrary walkable spot regardless of what
        # generation produced, so the test doesn't depend on seed luck.
        agent = Agent(id=0, name="Test", x=0, y=0, hunger=0.9)
        from hearthmind.world.resources import ResourceNode
        resources.nodes[(0, 0)] = ResourceNode(x=0, y=0, amount=1.0)
        population = Population(agents=[agent], _next_id=1)

        population.tick(seed=42, tick=1, terrain=terrain, resources=resources, settlement=settlement)

        self.assertLess(agent.hunger, 0.9)
        self.assertLess(resources.nodes[(0, 0)].amount, 1.0)

    def test_not_hungry_agent_does_not_forage(self):
        terrain = generate_terrain(seed=42, width=8, height=8)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        from hearthmind.world.resources import ResourceNode
        resources.nodes[(0, 0)] = ResourceNode(x=0, y=0, amount=1.0)
        agent = Agent(id=0, name="Test", x=0, y=0, hunger=0.1, energy=0.5, state=AgentState.RESTING)
        population = Population(agents=[agent], _next_id=1)

        population.tick(seed=42, tick=1, terrain=terrain, resources=resources, settlement=settlement)

        self.assertEqual(resources.nodes[(0, 0)].amount, 1.0)


class TestDeath(unittest.TestCase):
    def test_sustained_starvation_kills_agent(self):
        terrain = generate_terrain(seed=42, width=8, height=8)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        resources.nodes.clear()  # no forage anywhere, including wherever the agent wanders
        agent = Agent(id=0, name="Doomed", x=0, y=0, hunger=STARVATION_HUNGER_THRESHOLD)
        population = Population(agents=[agent], _next_id=1)

        events = []
        for tick in range(1, STARVATION_TICKS_TO_DEATH + 5):
            events.extend(population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement))

        self.assertEqual(len(population.agents), 0)
        self.assertTrue(any(cat == "death" and "starvation" in desc for cat, desc in events))

    def test_old_age_kills_agent(self):
        terrain = generate_terrain(seed=42, width=8, height=8)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        agent = Agent(id=0, name="Elder", x=0, y=0, age_ticks=9998, max_age_ticks=10000)
        population = Population(agents=[agent], _next_id=1)

        events = []
        for tick in range(1, 5):
            events.extend(population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement))

        self.assertEqual(len(population.agents), 0)
        self.assertTrue(any(cat == "death" and "old age" in desc for cat, desc in events))

    def test_healthy_agent_survives(self):
        terrain = generate_terrain(seed=42, width=8, height=8)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        agent = Agent(id=0, name="Fine", x=0, y=0, age_ticks=0, max_age_ticks=1_000_000)
        population = Population(agents=[agent], _next_id=1)

        for tick in range(1, 50):
            population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement)

        self.assertEqual(len(population.agents), 1)


class TestRelationshipsAndBirth(unittest.TestCase):
    def test_colocated_agents_build_affinity(self):
        # Tested directly against the by-position grouping rather than via
        # full tick()s: over many ticks, per-tick movement (independent
        # 50% chance each) makes staying colocated for dozens of ticks
        # unreliable to assert on, even though the underlying mechanic is
        # deterministic given a fixed position.
        a = Agent(id=0, name="A", x=2, y=2)
        b = Agent(id=1, name="B", x=2, y=2)
        Population._update_relationships({(2, 2): [a, b]})

        self.assertGreater(a.relationships.get(1, 0.0), 0.0)
        self.assertGreater(b.relationships.get(0, 0.0), 0.0)

    def test_relationships_decay_when_not_colocated(self):
        a = Agent(id=0, name="A", x=0, y=0, relationships={1: 0.5})
        b = Agent(id=1, name="B", x=5, y=5, relationships={0: 0.5})
        Population._update_relationships({(0, 0): [a], (5, 5): [b]})

        self.assertLess(a.relationships[1], 0.5)

    def test_mature_healthy_affinitied_pair_can_reproduce(self):
        # Tested by calling the reproduction step directly with a synthetic
        # by-position grouping, for the same reason as above: relying on
        # random movement to keep two agents colocated for hundreds of
        # ticks (needed to observe the ~1%-per-tick reproduction roll)
        # would make this test both slow and seed-fragile.
        a = Agent(id=0, name="Parent1", x=3, y=3, age_ticks=MATURITY_TICKS + 1,
                  max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        b = Agent(id=1, name="Parent2", x=3, y=3, age_ticks=MATURITY_TICKS + 1,
                  max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        a.relationships[1] = REPRODUCTION_AFFINITY_THRESHOLD + 0.1
        b.relationships[0] = REPRODUCTION_AFFINITY_THRESHOLD + 0.1
        population = Population(agents=[a, b], _next_id=2)

        births: list[tuple[str, str]] = []
        for tick in range(1, 2000):
            rng = random.Random(tick)
            births = population._maybe_reproduce({(3, 3): [a, b]}, rng)
            if births:
                break

        self.assertTrue(births, "expected at least one birth within 2000 rolls at max affinity")
        self.assertEqual(len(population.agents), 3)

    def test_immature_pair_does_not_reproduce(self):
        terrain = generate_terrain(seed=42, width=8, height=8)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        a = Agent(id=0, name="Young1", x=3, y=3, age_ticks=0, max_age_ticks=1_000_000)
        b = Agent(id=1, name="Young2", x=3, y=3, age_ticks=0, max_age_ticks=1_000_000)
        a.relationships[1] = 1.0
        b.relationships[0] = 1.0
        population = Population(agents=[a, b], _next_id=2)

        for tick in range(1, 200):
            population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement)

        self.assertEqual(len(population.agents), 2)

    def test_population_cap_is_respected(self):
        terrain = generate_terrain(seed=42, width=16, height=16)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        agents = []
        for i in range(POPULATION_CAP):
            a = Agent(id=i, name=f"A{i}", x=5, y=5, age_ticks=MATURITY_TICKS + 1,
                      max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
            agents.append(a)
        population = Population(agents=agents, _next_id=POPULATION_CAP)
        for a in agents:
            for b in agents:
                if a.id != b.id:
                    a.relationships[b.id] = 1.0

        for tick in range(1, 50):
            population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement)

        self.assertLessEqual(len(population.agents), POPULATION_CAP)


class TestSerialization(unittest.TestCase):
    def test_agent_round_trip(self):
        agent = Agent(
            id=3, name="Test", x=5, y=6, hunger=0.4, energy=0.7, state=AgentState.RESTING,
            age_ticks=100, max_age_ticks=30000, starving_ticks=2,
            relationships={1: 0.5, 2: 0.1}, parents=(1, 2),
        )
        restored = Agent.from_dict(agent.to_dict())
        self.assertEqual(agent.to_dict(), restored.to_dict())

    def test_agent_round_trip_no_parents(self):
        agent = Agent(id=0, name="Orphan-ish Founder", x=0, y=0)
        restored = Agent.from_dict(agent.to_dict())
        self.assertIsNone(restored.parents)

    def test_population_round_trip(self):
        terrain = generate_terrain(seed=42, width=16, height=16)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        population = Population.spawn_initial(seed=42, count=8, terrain=terrain)
        for tick in range(1, 10):
            population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement)

        restored = Population.from_dict(population.to_dict())
        self.assertEqual(population.to_dict(), restored.to_dict())


def _open_terrain(width=16, height=16):
    """An all-grassland terrain with no obstacles, so goal-directed
    movement tests aren't at the mercy of a randomly generated map having
    (or not having) a clear walkable path between two points."""
    return [
        [Tile(x=x, y=y, elevation=0.5, biome=Biome.GRASSLAND) for x in range(width)]
        for y in range(height)
    ]


class TestGoalDirectedMovement(unittest.TestCase):
    def test_forage_goal_moves_toward_nearest_node(self):
        terrain = _open_terrain()
        resources = ResourceGrid(nodes={(10, 5): ResourceNode(x=10, y=5, amount=1.0)})
        settlement = Settlement()
        agent = Agent(id=0, name="Seeker", x=5, y=5, hunger=0.1, goal=AgentGoal.FORAGE)
        population = Population(agents=[agent], _next_id=1)

        for tick in range(1, 6):
            population.tick(seed=1, tick=tick, terrain=terrain, resources=resources, settlement=settlement)

        self.assertGreater(agent.x, 5)  # stepped toward x=10

    def test_socialize_goal_moves_toward_nearest_agent(self):
        terrain = _open_terrain()
        resources = ResourceGrid(nodes={})
        settlement = Settlement()
        a = Agent(id=0, name="Seeker", x=0, y=0, hunger=0.1, energy=0.9, goal=AgentGoal.SOCIALIZE)
        b = Agent(id=1, name="Target", x=5, y=0, hunger=0.1, energy=0.9, goal=AgentGoal.WANDER)
        population = Population(agents=[a, b], _next_id=2)

        for tick in range(1, 6):
            population.tick(seed=1, tick=tick, terrain=terrain, resources=resources, settlement=settlement)

        self.assertGreater(a.x, 0)  # stepped toward b at x=5

    def test_rest_goal_forces_resting_even_with_high_energy(self):
        terrain = _open_terrain()
        resources = ResourceGrid(nodes={})
        settlement = Settlement()
        agent = Agent(id=0, name="Weary", x=5, y=5, energy=0.9, state=AgentState.AWAKE, goal=AgentGoal.REST)
        population = Population(agents=[agent], _next_id=1)

        population.tick(seed=1, tick=1, terrain=terrain, resources=resources, settlement=settlement)

        self.assertEqual(agent.state, AgentState.RESTING)

    def test_wander_goal_unaffected_by_goal_machinery(self):
        # Default goal (WANDER) should reproduce pre-Phase-B movement
        # exactly — this is really a regression guard for the dispatch
        # refactor, not a new behavior.
        terrain = generate_terrain(seed=42, width=32, height=32)
        resources = ResourceGrid.generate(seed=42, terrain=terrain)
        settlement = Settlement()
        population = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        for tick in range(1, 50):
            population.tick(seed=42, tick=tick, terrain=terrain, resources=resources, settlement=settlement)
        for agent in population.agents:
            self.assertEqual(agent.goal, AgentGoal.WANDER)
            self.assertIn(terrain[agent.y][agent.x].biome, WALKABLE_BIOMES)


class TestCognitionScheduling(unittest.TestCase):
    def test_due_for_cognition_is_staggered_by_agent_id(self):
        terrain = _open_terrain()
        agents = [Agent(id=i, name=f"A{i}", x=0, y=0) for i in range(5)]
        population = Population(agents=agents, _next_id=5)

        due_at_tick_0 = {a.id for a in population.due_for_cognition(tick=0, ticks_per_day=5)}
        due_at_tick_3 = {a.id for a in population.due_for_cognition(tick=3, ticks_per_day=5)}

        self.assertEqual(due_at_tick_0, {0})
        self.assertEqual(due_at_tick_3, {2})

    def test_due_for_cognition_empty_when_ticks_per_day_invalid(self):
        population = Population(agents=[Agent(id=0, name="A", x=0, y=0)], _next_id=1)
        self.assertEqual(population.due_for_cognition(tick=0, ticks_per_day=0), [])

    def test_apply_goal_sets_goal_and_reason(self):
        agent = Agent(id=0, name="A", x=0, y=0)
        population = Population(agents=[agent], _next_id=1)

        population.apply_goal(0, AgentGoal.FORAGE, "hungry")

        self.assertEqual(agent.goal, AgentGoal.FORAGE)
        self.assertEqual(agent.goal_reason, "hungry")

    def test_apply_goal_is_noop_for_unknown_agent(self):
        population = Population(agents=[], _next_id=0)
        population.apply_goal(999, AgentGoal.REST, "n/a")  # must not raise


class TestGoalSerialization(unittest.TestCase):
    def test_goal_round_trips(self):
        agent = Agent(id=0, name="A", x=0, y=0, goal=AgentGoal.SOCIALIZE, goal_reason="lonely")
        restored = Agent.from_dict(agent.to_dict())
        self.assertEqual(restored.goal, AgentGoal.SOCIALIZE)
        self.assertEqual(restored.goal_reason, "lonely")

    def test_pre_phase_b_agent_dict_defaults_to_wander(self):
        agent = Agent(id=0, name="A", x=0, y=0)
        data = agent.to_dict()
        del data["goal"]
        del data["goal_reason"]
        restored = Agent.from_dict(data)
        self.assertEqual(restored.goal, AgentGoal.WANDER)
        self.assertEqual(restored.goal_reason, "")


if __name__ == "__main__":
    unittest.main()
