import unittest

from hearthmind.world.resources import FORAGEABLE_BIOMES, MAX_NODE_AMOUNT, ResourceGrid
from hearthmind.world.terrain import generate_terrain


class TestResourceGeneration(unittest.TestCase):
    def test_nodes_only_on_forageable_biomes(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        grid = ResourceGrid.generate(seed=42, terrain=terrain)
        for (x, y) in grid.nodes:
            self.assertIn(terrain[y][x].biome, FORAGEABLE_BIOMES)

    def test_deterministic_for_same_seed(self):
        terrain = generate_terrain(seed=7, width=32, height=32)
        a = ResourceGrid.generate(seed=7, terrain=terrain)
        b = ResourceGrid.generate(seed=7, terrain=terrain)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_nodes_start_full(self):
        terrain = generate_terrain(seed=42, width=32, height=32)
        grid = ResourceGrid.generate(seed=42, terrain=terrain)
        self.assertGreater(len(grid.nodes), 0)
        for node in grid.nodes.values():
            self.assertEqual(node.amount, MAX_NODE_AMOUNT)

    def test_handles_terrain_with_no_forageable_tiles(self):
        terrain = generate_terrain(seed=1, width=1, height=1)
        grid = ResourceGrid.generate(seed=1, terrain=terrain)
        self.assertIsInstance(grid.nodes, dict)


class TestResourceTick(unittest.TestCase):
    def setUp(self):
        self.terrain = generate_terrain(seed=42, width=32, height=32)
        self.grid = ResourceGrid.generate(seed=42, terrain=self.terrain)

    def test_depleted_node_regenerates_over_time(self):
        node = next(iter(self.grid.nodes.values()))
        node.amount = 0.0
        for _ in range(1000):
            self.grid.tick()
        self.assertGreater(node.amount, 0.0)

    def test_amount_never_exceeds_max(self):
        for _ in range(10000):
            self.grid.tick()
        for node in self.grid.nodes.values():
            self.assertLessEqual(node.amount, MAX_NODE_AMOUNT)

    def test_get_returns_none_for_empty_tile(self):
        self.assertIsNone(self.grid.get(-1, -1))


class TestResourceSerialization(unittest.TestCase):
    def test_round_trip(self):
        terrain = generate_terrain(seed=42, width=16, height=16)
        grid = ResourceGrid.generate(seed=42, terrain=terrain)
        for node in list(grid.nodes.values())[:3]:
            node.amount = 0.5

        restored = ResourceGrid.from_dict(grid.to_dict())
        self.assertEqual(grid.to_dict(), restored.to_dict())


if __name__ == "__main__":
    unittest.main()
