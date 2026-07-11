import unittest

from hearthmind.config import Config
from hearthmind.time_system import SimClock


class TestSimClock(unittest.TestCase):
    def make_config(self, **overrides) -> Config:
        defaults = dict(
            sim_minutes_per_tick=15,
            minutes_per_day=24 * 60,  # 96 ticks/day
            days_per_season=4,         # small for fast tests
            seasons_per_year=("spring", "summer", "autumn", "winter"),
        )
        defaults.update(overrides)
        return Config(**defaults)

    def test_starts_at_zero(self):
        clock = SimClock(config=self.make_config())
        self.assertEqual(clock.day_index, 0)
        self.assertEqual(clock.season, "spring")
        self.assertEqual(clock.year, 0)

    def test_advance_increments_tick_count(self):
        clock = SimClock(config=self.make_config())
        clock.advance()
        self.assertEqual(clock.tick_count, 1)

    def test_day_rollover(self):
        config = self.make_config()
        clock = SimClock(config=config)
        ticks_per_day = config.minutes_per_day // config.sim_minutes_per_tick  # 96
        events = []
        for _ in range(ticks_per_day):
            events = clock.advance()
        self.assertEqual(clock.day_index, 1)
        self.assertIn("day_end", events)

    def test_season_rollover(self):
        config = self.make_config()
        clock = SimClock(config=config)
        ticks_per_day = config.minutes_per_day // config.sim_minutes_per_tick
        ticks_per_season = ticks_per_day * config.days_per_season
        events = []
        for _ in range(ticks_per_season):
            events = clock.advance()
        self.assertEqual(clock.season, "summer")
        self.assertIn("season_end", events)
        self.assertIn("day_end", events)  # season boundary is also a day boundary

    def test_year_rollover(self):
        config = self.make_config()
        clock = SimClock(config=config)
        ticks_per_day = config.minutes_per_day // config.sim_minutes_per_tick
        ticks_per_year = ticks_per_day * config.days_per_year()
        events = []
        for _ in range(ticks_per_year):
            events = clock.advance()
        self.assertEqual(clock.year, 1)
        self.assertEqual(clock.season, "spring")
        self.assertIn("year_end", events)

    def test_no_boundary_events_mid_day(self):
        clock = SimClock(config=self.make_config())
        events = clock.advance()  # first tick of the world, still day 0
        self.assertEqual(events, [])

    def test_serialization_round_trip(self):
        config = self.make_config()
        clock = SimClock(config=config)
        for _ in range(50):
            clock.advance()
        data = clock.to_dict()
        restored = SimClock.from_dict(config, data)
        self.assertEqual(restored.tick_count, clock.tick_count)
        self.assertEqual(restored.date_string(), clock.date_string())


if __name__ == "__main__":
    unittest.main()
