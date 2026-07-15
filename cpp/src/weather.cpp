// Native port of compute_weather's blend/threshold math (world/weather.py)
// — module 11, continuing R7's cellular-automata physical substrate
// track. Unlike modules 1-10, `compute_weather` draws from a seeded
// `random.Random` stream (`_tick_rng`) rather than accepting one from
// the caller — reproducing CPython's Mersenne Twister seeding/output
// bit-for-bit in C++ would be a real undertaking of its own and buys
// nothing here (this project's determinism discipline is "same code
// path, native vs Python, must match," not "match across RNG
// implementations" — see CLAUDE.md, "Determinism/reproducibility is
// NOT a requirement"). So the three `rng.uniform(...)` jitter draws
// stay in Python exactly as before; only the pure arithmetic that
// follows (baseline + jitter, clamp, EMA blend toward the previous
// tick, snow threshold check) crosses into C++.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

inline double clamp01(double value, double low, double high) {
    return std::max(low, std::min(high, value));
}

}  // namespace

struct WeatherResult {
    double temperature_c;
    double precipitation;
    double wind;
    bool is_snowing;
};

namespace {

WeatherResult compute_weather_blend(
    double base_temp, double base_precip, double base_wind,
    double jitter_temp, double jitter_precip, double jitter_wind,
    bool has_previous, double prev_temp, double prev_precip, double prev_wind,
    double smoothing, double snow_precipitation_threshold, double snow_temperature_threshold_c
) {
    double target_temp = base_temp + jitter_temp;
    double target_precip = clamp01(base_precip + jitter_precip, 0.0, 1.0);
    double target_wind = clamp01(base_wind + jitter_wind, 0.0, 1.0);

    double temperature_c, precipitation, wind;
    if (!has_previous) {
        temperature_c = target_temp;
        precipitation = target_precip;
        wind = target_wind;
    } else {
        temperature_c = prev_temp * smoothing + target_temp * (1.0 - smoothing);
        precipitation = prev_precip * smoothing + target_precip * (1.0 - smoothing);
        wind = prev_wind * smoothing + target_wind * (1.0 - smoothing);
    }

    bool is_snowing = precipitation > snow_precipitation_threshold
        && temperature_c <= snow_temperature_threshold_c;

    return {temperature_c, precipitation, wind, is_snowing};
}

}  // namespace

void register_weather(py::module_ &m) {
    py::class_<WeatherResult>(m, "WeatherResult")
        .def_readonly("temperature_c", &WeatherResult::temperature_c)
        .def_readonly("precipitation", &WeatherResult::precipitation)
        .def_readonly("wind", &WeatherResult::wind)
        .def_readonly("is_snowing", &WeatherResult::is_snowing);

    m.def("compute_weather_blend", &compute_weather_blend,
          py::arg("base_temp"), py::arg("base_precip"), py::arg("base_wind"),
          py::arg("jitter_temp"), py::arg("jitter_precip"), py::arg("jitter_wind"),
          py::arg("has_previous"), py::arg("prev_temp"), py::arg("prev_precip"), py::arg("prev_wind"),
          py::arg("smoothing"), py::arg("snow_precipitation_threshold"), py::arg("snow_temperature_threshold_c"),
          "Mirrors world/weather.py compute_weather's blend/threshold math "
          "exactly, given already-drawn RNG jitter values. The RNG draws "
          "themselves stay in Python — see this file's header comment.");
}
