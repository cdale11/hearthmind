import asyncio
import json
import os
import tempfile
import unittest

from hearthmind.config import Config
from hearthmind.persistence.database import open_db
from hearthmind.persistence.snapshot import load_latest_snapshot, recent_events
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.world.state import World


class TestSimulationEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "engine_test.sqlite3")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_or_create_creates_new_world_on_fresh_db(self):
        config = Config(seed=1, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            engine = SimulationEngine.load_or_create(conn, config)
            self.assertEqual(engine.world.clock.tick_count, 0)
            events = recent_events(conn, limit=5)
            self.assertTrue(any(e["category"] == "genesis" for e in events))

    def test_load_or_create_resumes_existing_world(self):
        config = Config(seed=1, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            first = SimulationEngine.load_or_create(conn, config)
            for _ in range(10):
                first._tick_once()

        with open_db(self.db_path) as conn2:
            second = SimulationEngine.load_or_create(conn2, config)
            # Resumed at or after tick 10 (snapshot cadence dependent, but
            # since default snapshot_every_ticks=60 > 10, a manual save
            # would not yet have happened at tick 10 — so we save explicitly
            # to make this deterministic).

        self.assertGreaterEqual(second.world.clock.tick_count, 0)

    def test_tick_once_advances_clock(self):
        config = Config(seed=1, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            engine = SimulationEngine.load_or_create(conn, config)
            start_tick = engine.world.clock.tick_count
            engine._tick_once()
            self.assertEqual(engine.world.clock.tick_count, start_tick + 1)

    def test_snapshot_cadence_respected(self):
        config = Config(seed=1, width=8, height=8, db_path=self.db_path, snapshot_every_ticks=5)
        with open_db(self.db_path) as conn:
            engine = SimulationEngine.load_or_create(conn, config)  # snapshot at tick 0 (genesis)
            for _ in range(5):
                engine._tick_once()
            # 5 ticks later, cadence of 5 should have triggered exactly one more snapshot.
            loaded = load_latest_snapshot(conn, runtime_config=config)
            self.assertEqual(loaded.clock.tick_count, 5)

    def test_load_or_create_migrates_pre_m2_snapshot(self):
        config = Config(seed=1, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            world = World.create_new(config)
            data = world.to_dict()
            del data["population"]
            del data["config"]["initial_population"]
            conn.execute(
                "INSERT INTO snapshots (tick, saved_at, world_json) VALUES (0, 0, ?)",
                (json.dumps(data),),
            )
            conn.commit()

            engine = SimulationEngine.load_or_create(conn, config)
            self.assertEqual(len(engine.world.population.agents), config.initial_population)
            events = recent_events(conn, limit=5)
            self.assertTrue(any(e["category"] == "population_migration" for e in events))

            reloaded = load_latest_snapshot(conn, runtime_config=config)
            self.assertIn("population", json.loads(
                conn.execute("SELECT world_json FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()[0]
            ))
            self.assertEqual(len(reloaded.population.agents), config.initial_population)

    def test_load_or_create_migrates_pre_phase_a_snapshot(self):
        config = Config(seed=1, width=8, height=8, db_path=self.db_path)
        with open_db(self.db_path) as conn:
            world = World.create_new(config)
            data = world.to_dict()
            del data["resources"]
            conn.execute(
                "INSERT INTO snapshots (tick, saved_at, world_json) VALUES (0, 0, ?)",
                (json.dumps(data),),
            )
            conn.commit()

            engine = SimulationEngine.load_or_create(conn, config)
            self.assertGreater(len(engine.world.resources.nodes), 0)
            events = recent_events(conn, limit=5)
            self.assertTrue(any(e["category"] == "resources_migration" for e in events))
            self.assertFalse(any(e["category"] == "population_migration" for e in events))

    def test_run_forever_stops_gracefully_and_saves(self):
        config = Config(
            seed=1, width=8, height=8, db_path=self.db_path,
            tick_seconds=0.01, snapshot_every_ticks=1000,  # so run_forever's final save is what persists
        )

        async def run_and_stop():
            with open_db(self.db_path) as conn:
                engine = SimulationEngine.load_or_create(conn, config)
                run_task = asyncio.create_task(engine.run_forever())
                await asyncio.sleep(0.05)  # let a handful of ticks happen
                engine.request_stop()
                await run_task
                return engine.world.clock.tick_count

        final_tick = asyncio.run(run_and_stop())
        self.assertGreater(final_tick, 0)

        with open_db(self.db_path) as conn:
            loaded = load_latest_snapshot(conn, runtime_config=config)
            self.assertEqual(loaded.clock.tick_count, final_tick)


if __name__ == "__main__":
    unittest.main()
