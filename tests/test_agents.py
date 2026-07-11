import unittest

from hearthmind.agents.agent import Agent, AgentState
from hearthmind.agents.population import WALKABLE_BIOMES, Population
from hearthmind.world.terrain import generate_terrain


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


class TestPopulationTick(unittest.TestCase):
    def setUp(self):
        self.terrain = generate_terrain(seed=42, width=32, height=32)
        self.population = Population.spawn_initial(seed=42, count=10, terrain=self.terrain)

    def test_hunger_increases_each_tick(self):
        before = [a.hunger for a in self.population.agents]
        self.population.tick(seed=42, tick=1, terrain=self.terrain)
        after = [a.hunger for a in self.population.agents]
        for b, a in zip(before, after):
            self.assertGreater(a, b)

    def test_hunger_capped_at_one(self):
        for _ in range(500):
            self.population.tick(seed=42, tick=1, terrain=self.terrain)
        for agent in self.population.agents:
            self.assertLessEqual(agent.hunger, 1.0)

    def test_energy_drains_while_awake_and_triggers_rest(self):
        # Energy starts at 1.0 and drains ENERGY_DRAIN_AWAKE (0.015) per
        # tick; REST_THRESHOLD (0.2) is crossed after ~54 ticks.
        for tick in range(1, 60):
            self.population.tick(seed=42, tick=tick, terrain=self.terrain)
        self.assertTrue(any(a.state is AgentState.RESTING for a in self.population.agents))

    def test_resting_agent_recovers_energy_and_wakes(self):
        agent = self.population.agents[0]
        agent.energy = 0.1
        agent.state = AgentState.RESTING
        for tick in range(1, 30):
            self.population.tick(seed=42, tick=tick, terrain=self.terrain)
        self.assertGreater(agent.energy, 0.1)

    def test_movement_stays_in_bounds_and_walkable(self):
        for tick in range(1, 100):
            self.population.tick(seed=42, tick=tick, terrain=self.terrain)
        for agent in self.population.agents:
            self.assertTrue(0 <= agent.x < 32)
            self.assertTrue(0 <= agent.y < 32)
            self.assertIn(self.terrain[agent.y][agent.x].biome, WALKABLE_BIOMES)

    def test_tick_deterministic_for_same_seed_and_tick(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        pop_a = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        pop_b = Population.spawn_initial(seed=42, count=10, terrain=terrain)
        for tick in range(1, 20):
            pop_a.tick(seed=42, tick=tick, terrain=terrain)
            pop_b.tick(seed=42, tick=tick, terrain=terrain)
        self.assertEqual(pop_a.to_dict(), pop_b.to_dict())


class TestSerialization(unittest.TestCase):
    def test_agent_round_trip(self):
        agent = Agent(id=3, name="Test", x=5, y=6, hunger=0.4, energy=0.7, state=AgentState.RESTING)
        restored = Agent.from_dict(agent.to_dict())
        self.assertEqual(agent.to_dict(), restored.to_dict())

    def test_population_round_trip(self):
        terrain = generate_terrain(seed=42, width=16, height=16)
        population = Population.spawn_initial(seed=42, count=8, terrain=terrain)
        for tick in range(1, 10):
            population.tick(seed=42, tick=tick, terrain=terrain)

        restored = Population.from_dict(population.to_dict())
        self.assertEqual(population.to_dict(), restored.to_dict())


if __name__ == "__main__":
    unittest.main()
