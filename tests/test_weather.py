import unittest

from hearthmind.world.weather import compute_weather


class TestWeather(unittest.TestCase):
    def test_deterministic_for_same_inputs(self):
        a = compute_weather(seed=1, tick=100, season="summer", previous=None)
        b = compute_weather(seed=1, tick=100, season="summer", previous=None)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_different_ticks_differ(self):
        a = compute_weather(seed=1, tick=1, season="summer", previous=None)
        b = compute_weather(seed=1, tick=2, season="summer", previous=None)
        self.assertNotEqual(a.to_dict(), b.to_dict())

    def test_winter_colder_than_summer_on_average(self):
        # Not true for every single tick, but should hold over many ticks.
        summer_temps = []
        winter_temps = []
        prev_summer = None
        prev_winter = None
        for tick in range(200):
            prev_summer = compute_weather(seed=1, tick=tick, season="summer", previous=prev_summer)
            prev_winter = compute_weather(seed=1, tick=tick, season="winter", previous=prev_winter)
            summer_temps.append(prev_summer.temperature_c)
            winter_temps.append(prev_winter.temperature_c)
        avg_summer = sum(summer_temps) / len(summer_temps)
        avg_winter = sum(winter_temps) / len(winter_temps)
        self.assertGreater(avg_summer, avg_winter)

    def test_snowing_only_when_cold_and_wet(self):
        state = compute_weather(seed=1, tick=1, season="winter", previous=None)
        if state.is_snowing:
            self.assertLessEqual(state.temperature_c, 0.0)
            self.assertGreater(state.precipitation, 0.2)

    def test_smoothing_keeps_consecutive_ticks_close(self):
        prev = compute_weather(seed=1, tick=0, season="summer", previous=None)
        curr = compute_weather(seed=1, tick=1, season="summer", previous=prev)
        # With 0.7 smoothing weight, consecutive temps shouldn't swing wildly.
        self.assertLess(abs(curr.temperature_c - prev.temperature_c), 15.0)

    def test_bounded_ranges(self):
        for tick in range(50):
            state = compute_weather(seed=3, tick=tick, season="autumn", previous=None)
            self.assertGreaterEqual(state.precipitation, 0.0)
            self.assertLessEqual(state.precipitation, 1.0)
            self.assertGreaterEqual(state.wind, 0.0)
            self.assertLessEqual(state.wind, 1.0)


if __name__ == "__main__":
    unittest.main()
