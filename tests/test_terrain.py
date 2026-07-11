import unittest

from hearthmind.world.terrain import biome_counts, generate_terrain


class TestTerrain(unittest.TestCase):
    def test_deterministic_for_same_seed(self):
        a = generate_terrain(seed=42, width=16, height=16)
        b = generate_terrain(seed=42, width=16, height=16)
        self.assertEqual(
            [[t.to_dict() for t in row] for row in a],
            [[t.to_dict() for t in row] for row in b],
        )

    def test_different_seeds_differ(self):
        a = generate_terrain(seed=1, width=16, height=16)
        b = generate_terrain(seed=2, width=16, height=16)
        self.assertNotEqual(
            [[t.elevation for t in row] for row in a],
            [[t.elevation for t in row] for row in b],
        )

    def test_correct_dimensions(self):
        tiles = generate_terrain(seed=42, width=13, height=27)
        self.assertEqual(len(tiles), 27)
        self.assertEqual(len(tiles[0]), 13)

    def test_non_power_of_two_dimensions(self):
        # width/height need not be 2^k+1 even though the internal algorithm
        # generates at that size and crops.
        tiles = generate_terrain(seed=7, width=10, height=10)
        self.assertEqual(len(tiles), 10)
        self.assertEqual(len(tiles[0]), 10)

    def test_elevations_within_bounds(self):
        tiles = generate_terrain(seed=99, width=20, height=20)
        for row in tiles:
            for tile in row:
                self.assertGreaterEqual(tile.elevation, 0.0)
                self.assertLessEqual(tile.elevation, 1.0)

    def test_biome_counts_sum_to_total_tiles(self):
        tiles = generate_terrain(seed=5, width=16, height=16)
        counts = biome_counts(tiles)
        self.assertEqual(sum(counts.values()), 16 * 16)

    def test_produces_variety_of_biomes(self):
        # Not a strict guarantee for all seeds, but this seed/size should
        # produce more than one biome — a fully flat world would suggest a
        # bug in normalization.
        tiles = generate_terrain(seed=42, width=64, height=64)
        counts = biome_counts(tiles)
        self.assertGreater(len(counts), 1)


if __name__ == "__main__":
    unittest.main()
