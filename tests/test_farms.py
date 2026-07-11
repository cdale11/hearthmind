import random
import unittest

from hearthmind.agents.agent import Agent, AgentState
from hearthmind.agents.population import Population
from hearthmind.economy.farms import (
    FARMABLE_BIOMES,
    GROWTH_PER_TICK,
    HARVEST_AMOUNT,
    MAX_FARM_YIELD,
    FarmGrid,
    FarmPlot,
    FarmStage,
)
from hearthmind.settlement.buildings import Settlement
from hearthmind.world.resources import ResourceGrid
from hearthmind.world.terrain import Biome, Tile
from tests._terrain_helpers import open_terrain


class TestFarmGridQueries(unittest.TestCase):
    def test_get_returns_none_for_unplanted_tile(self):
        self.assertIsNone(FarmGrid().get(0, 0))

    def test_is_farmable_only_grassland(self):
        terrain = [
            [Tile(x=0, y=0, elevation=0.5, biome=Biome.GRASSLAND)],
            [Tile(x=0, y=0, elevation=0.5, biome=Biome.FOREST)],
        ]
        self.assertTrue(FarmGrid.is_farmable(terrain, 0, 0))
        self.assertFalse(FarmGrid.is_farmable(terrain, 0, 1))

    def test_farmable_biomes_is_narrower_than_walkable(self):
        self.assertEqual(FARMABLE_BIOMES, {Biome.GRASSLAND})


class TestPlantingAndGrowth(unittest.TestCase):
    def test_plant_creates_growing_plot(self):
        grid = FarmGrid()
        plot = grid.plant(3, 4)
        self.assertEqual(plot.stage, FarmStage.GROWING)
        self.assertEqual(plot.growth, 0.0)
        self.assertIs(grid.get(3, 4), plot)

    def test_growth_reaches_ready_and_gets_yield(self):
        grid = FarmGrid()
        grid.plant(0, 0)
        for _ in range(int(1 / GROWTH_PER_TICK) + 5):
            grid.tick()
        plot = grid.get(0, 0)
        self.assertEqual(plot.stage, FarmStage.READY)
        self.assertEqual(plot.amount, MAX_FARM_YIELD)

    def test_growth_does_not_exceed_one(self):
        grid = FarmGrid()
        grid.plant(0, 0)
        for _ in range(10000):
            grid.tick()
        self.assertLessEqual(grid.get(0, 0).growth, 1.0)


class TestHarvest(unittest.TestCase):
    def test_harvest_consumes_and_relieves(self):
        grid = FarmGrid()
        grid.plots[(0, 0)] = FarmPlot(x=0, y=0, stage=FarmStage.READY, growth=1.0, amount=MAX_FARM_YIELD)
        consumed = grid.harvest(0, 0, HARVEST_AMOUNT)
        self.assertEqual(consumed, HARVEST_AMOUNT)
        self.assertAlmostEqual(grid.get(0, 0).amount, MAX_FARM_YIELD - HARVEST_AMOUNT, places=4)

    def test_harvest_from_growing_plot_yields_nothing(self):
        grid = FarmGrid()
        grid.plant(0, 0)
        consumed = grid.harvest(0, 0, HARVEST_AMOUNT)
        self.assertEqual(consumed, 0.0)

    def test_harvest_from_empty_tile_yields_nothing(self):
        grid = FarmGrid()
        self.assertEqual(grid.harvest(5, 5, HARVEST_AMOUNT), 0.0)

    def test_depleted_plot_is_removed_and_replantable(self):
        grid = FarmGrid()
        grid.plots[(0, 0)] = FarmPlot(x=0, y=0, stage=FarmStage.READY, growth=1.0, amount=HARVEST_AMOUNT / 2)
        grid.harvest(0, 0, HARVEST_AMOUNT)  # takes everything left
        self.assertIsNone(grid.get(0, 0))
        # Since it's gone, planting again should work cleanly.
        grid.plant(0, 0)
        self.assertEqual(grid.get(0, 0).stage, FarmStage.GROWING)

    def test_partial_harvest_leaves_remainder(self):
        grid = FarmGrid()
        grid.plots[(0, 0)] = FarmPlot(x=0, y=0, stage=FarmStage.READY, growth=1.0, amount=MAX_FARM_YIELD)
        consumed = grid.harvest(0, 0, MAX_FARM_YIELD + 10)  # ask for more than available
        self.assertEqual(consumed, MAX_FARM_YIELD)
        self.assertIsNone(grid.get(0, 0))  # fully depleted, removed


class TestPopulationForagingPrefersFarms(unittest.TestCase):
    def test_hungry_agent_harvests_ready_farm_over_wild_node(self):
        terrain = open_terrain(8, 8)
        resources = ResourceGrid(nodes={})
        farms = FarmGrid()
        farms.plots[(0, 0)] = FarmPlot(x=0, y=0, stage=FarmStage.READY, growth=1.0, amount=MAX_FARM_YIELD)
        agent = Agent(id=0, name="Hungry", x=0, y=0, hunger=0.9)
        population = Population(agents=[agent], _next_id=1)
        settlement = Settlement()

        population.tick(seed=1, tick=1, terrain=terrain, resources=resources, settlement=settlement, farms=farms)

        self.assertLess(agent.hunger, 0.9)
        self.assertLess(farms.get(0, 0).amount, MAX_FARM_YIELD)

    def test_falls_back_to_wild_forage_when_no_farm_present(self):
        from hearthmind.world.resources import ResourceNode

        terrain = open_terrain(8, 8)
        resources = ResourceGrid(nodes={(0, 0): ResourceNode(x=0, y=0, amount=1.0)})
        farms = FarmGrid()
        agent = Agent(id=0, name="Hungry", x=0, y=0, hunger=0.9)
        population = Population(agents=[agent], _next_id=1)
        settlement = Settlement()

        population.tick(seed=1, tick=1, terrain=terrain, resources=resources, settlement=settlement, farms=farms)

        self.assertLess(agent.hunger, 0.9)
        self.assertLess(resources.get(0, 0).amount, 1.0)


class TestPlantingMechanic(unittest.TestCase):
    def test_awake_agent_can_plant_on_farmable_unclaimed_tile(self):
        terrain = open_terrain(8, 8)
        farms = FarmGrid()
        agent = Agent(id=0, name="Farmer", x=3, y=3, state=AgentState.AWAKE)
        planted = False
        for tick in range(1, 2000):
            rng = random.Random(tick)
            events = Population._maybe_plant({(3, 3): [agent]}, farms, Settlement(), terrain, rng)
            if any(cat == "farm_planted" for cat, _ in events):
                planted = True
                break
        self.assertTrue(planted, "expected planting within 2000 rolls")
        self.assertIsNotNone(farms.get(3, 3))

    def test_no_planting_on_non_farmable_biome(self):
        terrain = open_terrain(8, 8, biome=Biome.FOREST)
        farms = FarmGrid()
        agent = Agent(id=0, name="Farmer", x=3, y=3, state=AgentState.AWAKE)
        for tick in range(1, 2000):
            rng = random.Random(tick)
            Population._maybe_plant({(3, 3): [agent]}, farms, Settlement(), terrain, rng)
        self.assertIsNone(farms.get(3, 3))

    def test_no_planting_on_already_claimed_tile(self):
        terrain = open_terrain(8, 8)
        farms = FarmGrid()
        farms.plant(3, 3)
        agent = Agent(id=0, name="Farmer", x=3, y=3, state=AgentState.AWAKE)
        for tick in range(1, 200):
            rng = random.Random(tick)
            events = Population._maybe_plant({(3, 3): [agent]}, farms, Settlement(), terrain, rng)
            self.assertEqual(events, [])

    def test_resting_agent_does_not_plant(self):
        terrain = open_terrain(8, 8)
        farms = FarmGrid()
        agent = Agent(id=0, name="Sleepy", x=3, y=3, state=AgentState.RESTING)
        for tick in range(1, 2000):
            rng = random.Random(tick)
            Population._maybe_plant({(3, 3): [agent]}, farms, Settlement(), terrain, rng)
        self.assertIsNone(farms.get(3, 3))

    def test_no_planting_on_tile_with_a_building(self):
        terrain = open_terrain(8, 8)
        farms = FarmGrid()
        settlement = Settlement()
        settlement.start_construction(3, 3)
        agent = Agent(id=0, name="Farmer", x=3, y=3, state=AgentState.AWAKE)
        for tick in range(1, 2000):
            rng = random.Random(tick)
            events = Population._maybe_plant({(3, 3): [agent]}, farms, settlement, terrain, rng)
            self.assertEqual(events, [])
        self.assertIsNone(farms.get(3, 3))

    def test_no_construction_on_tile_with_a_farm(self):
        from hearthmind.agents.agent import MATURITY_TICKS

        farms = FarmGrid()
        farms.plant(5, 5)
        settlement = Settlement()
        a = Agent(id=0, name="A", x=5, y=5, age_ticks=MATURITY_TICKS + 1,
                  max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        b = Agent(id=1, name="B", x=5, y=5, age_ticks=MATURITY_TICKS + 1,
                  max_age_ticks=1_000_000, hunger=0.1, energy=0.9)
        population = Population(agents=[a, b], _next_id=2)
        for tick in range(1, 3000):
            rng = random.Random(tick)
            events = population._maybe_start_construction({(5, 5): [a, b]}, settlement, farms, rng)
            self.assertEqual(events, [])
        self.assertEqual(len(settlement.buildings), 0)


class TestSummary(unittest.TestCase):
    def test_summary_counts_by_stage(self):
        grid = FarmGrid(plots={
            (0, 0): FarmPlot(x=0, y=0, stage=FarmStage.GROWING),
            (1, 1): FarmPlot(x=1, y=1, stage=FarmStage.READY, amount=1.0),
            (2, 2): FarmPlot(x=2, y=2, stage=FarmStage.READY, amount=2.0),
        })
        summary = grid.summary()
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["growing"], 1)
        self.assertEqual(summary["ready"], 2)

    def test_summary_empty_grid(self):
        summary = FarmGrid().summary()
        self.assertEqual(summary, {"total": 0, "growing": 0, "ready": 0})


class TestSerialization(unittest.TestCase):
    def test_plot_round_trip(self):
        plot = FarmPlot(x=2, y=3, stage=FarmStage.READY, growth=1.0, amount=1.5)
        restored = FarmPlot.from_dict(plot.to_dict())
        self.assertEqual(plot.to_dict(), restored.to_dict())

    def test_grid_round_trip(self):
        grid = FarmGrid(plots={
            (0, 0): FarmPlot(x=0, y=0, stage=FarmStage.GROWING, growth=0.3),
            (5, 5): FarmPlot(x=5, y=5, stage=FarmStage.READY, growth=1.0, amount=2.0),
        })
        restored = FarmGrid.from_dict(grid.to_dict())
        self.assertEqual(grid.to_dict(), restored.to_dict())


if __name__ == "__main__":
    unittest.main()
