// Native port of Population._update_needs (agents/population.py) —
// module 6 of the incremental C++ port, and the first module from the
// "full engine rewrite" track (docs/REFACTOR-2026-07.md, R6): unlike
// modules 1-5 (bounded-box/index lookups gated behind a goal), this
// runs for every agent, every tick, unconditionally — the actual
// per-tick needs/aging math at the core of the simulation.
//
// Deliberately takes every tunable constant as a parameter (via
// `NeedsConstants`) rather than duplicating literal values here: those
// constants live in agents/agent.py, agents/population.py, and
// settlement/buildings.py (three different files, no single home), and
// hardcoding a second copy risks silent drift if any of them is ever
// retuned without updating this file. Population.py builds one
// `NeedsConstants` per tick (values don't change mid-tick) and passes
// it to every agent's `update_needs` call. All object-shaped
// resolution (which building an agent stands in, whether it's a
// standing hospital, elder-age comparison) stays in Python — this
// function only takes the already-resolved booleans/floats and does
// the arithmetic.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

struct NeedsConstants {
    double hunger_rate;
    double energy_drain_awake;
    double sickness_hunger_mult;
    double sickness_energy_mult;
    double weather_hunger_mult;
    double weather_energy_mult;
    double crowding_energy_mult;
    double night_energy_extra;
    double rest_threshold;
    double night_rest_threshold_boost;
    double energy_recovery_resting;
    double night_rest_recovery_bonus;
    double elder_recovery_mult;
    double hospital_rest_recovery_mult;
    double wake_threshold;
};

struct NeedsResult {
    double hunger;
    double energy;
    bool resting;
};

namespace {

NeedsResult update_needs(
    const NeedsConstants &c,
    double hunger, double energy, bool resting,
    bool sick, bool weather_harsh, bool sheltered_from_weather,
    bool crowded, double night_factor, bool elder, bool hospital_rest
) {
    bool awake = !resting;
    double hunger_rate = c.hunger_rate;
    double energy_drain = c.energy_drain_awake;
    if (sick) {
        hunger_rate *= c.sickness_hunger_mult;
        energy_drain *= c.sickness_energy_mult;
    }
    if (weather_harsh && awake && !sheltered_from_weather) {
        hunger_rate *= c.weather_hunger_mult;
        energy_drain *= c.weather_energy_mult;
    }
    if (crowded && awake) {
        energy_drain *= c.crowding_energy_mult;
    }
    if (awake) {
        energy_drain *= 1.0 + night_factor * c.night_energy_extra;
    }

    double new_hunger = std::min(1.0, hunger + hunger_rate);
    double rest_threshold = c.rest_threshold + night_factor * c.night_rest_threshold_boost;

    double new_energy;
    bool new_resting = resting;
    if (resting) {
        double recovery = c.energy_recovery_resting * (1.0 + night_factor * c.night_rest_recovery_bonus);
        if (elder) recovery *= c.elder_recovery_mult;
        if (hospital_rest) recovery *= c.hospital_rest_recovery_mult;
        new_energy = std::min(1.0, energy + recovery);
        if (new_energy >= c.wake_threshold) new_resting = false;
    } else {
        new_energy = std::max(0.0, energy - energy_drain);
        if (new_energy <= rest_threshold) new_resting = true;
    }
    return {new_hunger, new_energy, new_resting};
}

}  // namespace

void register_needs(py::module_ &m) {
    py::class_<NeedsConstants>(m, "NeedsConstants")
        .def(py::init<>())
        .def_readwrite("hunger_rate", &NeedsConstants::hunger_rate)
        .def_readwrite("energy_drain_awake", &NeedsConstants::energy_drain_awake)
        .def_readwrite("sickness_hunger_mult", &NeedsConstants::sickness_hunger_mult)
        .def_readwrite("sickness_energy_mult", &NeedsConstants::sickness_energy_mult)
        .def_readwrite("weather_hunger_mult", &NeedsConstants::weather_hunger_mult)
        .def_readwrite("weather_energy_mult", &NeedsConstants::weather_energy_mult)
        .def_readwrite("crowding_energy_mult", &NeedsConstants::crowding_energy_mult)
        .def_readwrite("night_energy_extra", &NeedsConstants::night_energy_extra)
        .def_readwrite("rest_threshold", &NeedsConstants::rest_threshold)
        .def_readwrite("night_rest_threshold_boost", &NeedsConstants::night_rest_threshold_boost)
        .def_readwrite("energy_recovery_resting", &NeedsConstants::energy_recovery_resting)
        .def_readwrite("night_rest_recovery_bonus", &NeedsConstants::night_rest_recovery_bonus)
        .def_readwrite("elder_recovery_mult", &NeedsConstants::elder_recovery_mult)
        .def_readwrite("hospital_rest_recovery_mult", &NeedsConstants::hospital_rest_recovery_mult)
        .def_readwrite("wake_threshold", &NeedsConstants::wake_threshold);

    py::class_<NeedsResult>(m, "NeedsResult")
        .def_readonly("hunger", &NeedsResult::hunger)
        .def_readonly("energy", &NeedsResult::energy)
        .def_readonly("resting", &NeedsResult::resting);

    m.def("update_needs", &update_needs,
          py::arg("constants"), py::arg("hunger"), py::arg("energy"), py::arg("resting"),
          py::arg("sick"), py::arg("weather_harsh"), py::arg("sheltered_from_weather"),
          py::arg("crowded"), py::arg("night_factor"), py::arg("elder"), py::arg("hospital_rest"),
          "Mirrors agents/population.py Population._update_needs exactly, "
          "given already-resolved booleans (building lookup stays in Python).");
}
