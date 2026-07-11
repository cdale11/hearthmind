import os
import tempfile
import unittest

from hearthmind.config import Config
from hearthmind.persistence.database import is_fresh, open_db, write_world_meta
from hearthmind.persistence.snapshot import load_latest_snapshot, log_event, recent_events, save_snapshot
from hearthmind.world.state import World


class TestWorldSerialization(unittest.TestCase):
    def test_to_dict_from_dict_round_trip(self):
        config = Config(seed=42, width=8, height=8)
        world = World.create_new(config)
        for _ in range(10):
            world.tick()

        data = world.to_dict()
        restored = World.from_dict(data, runtime_config=config)

        self.assertEqual(restored.clock.tick_count, world.clock.tick_count)
        self.assertEqual(restored.weather.to_dict(), world.weather.to_dict())
        self.assertEqual(
            [[t.to_dict() for t in row] for row in restored.terrain],
            [[t.to_dict() for t in row] for row in world.terrain],
        )

    def test_loading_pre_m2_snapshot_migrates_population(self):
        config = Config(seed=42, width=8, height=8)
        world = World.create_new(config)
        data = world.to_dict()
        del data["population"]  # simulate a snapshot saved before Milestone 2
        del data["config"]["initial_population"]

        restored = World.from_dict(data, runtime_config=config)

        self.assertIn("population", restored.migrated_subsystems)
        self.assertEqual(len(restored.population.agents), config.initial_population)

    def test_loading_pre_phase_a_snapshot_migrates_resources(self):
        config = Config(seed=42, width=8, height=8)
        world = World.create_new(config)
        data = world.to_dict()
        del data["resources"]  # simulate a snapshot saved before Phase A

        restored = World.from_dict(data, runtime_config=config)

        self.assertIn("resources", restored.migrated_subsystems)
        self.assertNotIn("population", restored.migrated_subsystems)

    def test_loading_pre_phase_c_snapshot_migrates_settlement(self):
        config = Config(seed=42, width=8, height=8)
        world = World.create_new(config)
        data = world.to_dict()
        del data["settlement"]  # simulate a snapshot saved before Phase C

        restored = World.from_dict(data, runtime_config=config)

        self.assertIn("settlement", restored.migrated_subsystems)
        self.assertEqual(len(restored.settlement.buildings), 0)

    def test_loading_pre_phase_d_snapshot_migrates_farms(self):
        config = Config(seed=42, width=8, height=8)
        world = World.create_new(config)
        data = world.to_dict()
        del data["farms"]  # simulate a snapshot saved before Phase D

        restored = World.from_dict(data, runtime_config=config)

        self.assertIn("farms", restored.migrated_subsystems)
        self.assertEqual(len(restored.farms.plots), 0)

    def test_loading_current_snapshot_does_not_migrate(self):
        config = Config(seed=42, width=8, height=8)
        world = World.create_new(config)
        data = world.to_dict()

        restored = World.from_dict(data, runtime_config=config)

        self.assertEqual(restored.migrated_subsystems, [])
        self.assertEqual(
            [a.to_dict() for a in restored.population.agents],
            [a.to_dict() for a in world.population.agents],
        )

    def test_runtime_config_overrides_on_resume(self):
        original = Config(seed=42, width=8, height=8, tick_seconds=1.0)
        world = World.create_new(original)
        data = world.to_dict()

        different_runtime = Config(tick_seconds=99.0, snapshot_every_ticks=5)
        restored = World.from_dict(data, runtime_config=different_runtime)

        # Creation-only fields preserved from the snapshot:
        self.assertEqual(restored.config.seed, 42)
        self.assertEqual(restored.config.width, 8)
        # Runtime fields taken from the new runtime config:
        self.assertEqual(restored.config.tick_seconds, 99.0)
        self.assertEqual(restored.config.snapshot_every_ticks, 5)


class TestDatabasePersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_world.sqlite3")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_fresh_database_has_no_snapshot(self):
        with open_db(self.db_path) as conn:
            self.assertTrue(is_fresh(conn))
            world = load_latest_snapshot(conn, runtime_config=Config())
            self.assertIsNone(world)

    def test_save_and_load_snapshot(self):
        config = Config(seed=7, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            world = World.create_new(config)
            for _ in range(5):
                world.tick()
            save_snapshot(conn, world)

            loaded = load_latest_snapshot(conn, runtime_config=config)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.clock.tick_count, 5)

    def test_load_latest_returns_most_recent_snapshot(self):
        config = Config(seed=7, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            world = World.create_new(config)
            save_snapshot(conn, world)  # tick 0
            for _ in range(3):
                world.tick()
            save_snapshot(conn, world)  # tick 3

            loaded = load_latest_snapshot(conn, runtime_config=config)
            self.assertEqual(loaded.clock.tick_count, 3)

    def test_world_meta_written_once(self):
        with open_db(self.db_path) as conn:
            self.assertTrue(is_fresh(conn))
            write_world_meta(conn, seed=1, width=8, height=8)
            self.assertFalse(is_fresh(conn))

    def test_events_logged_and_retrieved_in_order(self):
        with open_db(self.db_path) as conn:
            log_event(conn, tick=1, category="genesis", description="first")
            log_event(conn, tick=2, category="day_end", description="second")
            log_event(conn, tick=3, category="day_end", description="third")

            events = recent_events(conn, limit=2)
            self.assertEqual(len(events), 2)
            # Most recent first.
            self.assertEqual(events[0]["description"], "third")
            self.assertEqual(events[1]["description"], "second")

    def test_resume_across_separate_connections(self):
        """Simulates a server restart: open a connection, tick and save,
        close it, then open a fresh connection and confirm state resumed."""
        config = Config(seed=99, width=8, height=8, db_path=self.db_path)

        with open_db(self.db_path) as conn:
            world = World.create_new(config)
            for _ in range(20):
                world.tick()
            save_snapshot(conn, world)
            original_tick = world.clock.tick_count
            original_terrain = [[t.to_dict() for t in row] for row in world.terrain]

        # Simulate the process restarting entirely.
        with open_db(self.db_path) as conn2:
            resumed = load_latest_snapshot(conn2, runtime_config=config)
            self.assertEqual(resumed.clock.tick_count, original_tick)
            self.assertEqual(
                [[t.to_dict() for t in row] for row in resumed.terrain],
                original_terrain,
            )


if __name__ == "__main__":
    unittest.main()
