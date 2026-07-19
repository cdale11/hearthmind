// Native port of the two scalar operations behind
// FarmGrid._tick_soil_fertility (economy/farms.py) — v1 audit fix: this
// was a genuine per-tick, farmed-tile-count-scaled hot loop sitting
// unported right next to its already-native sibling (farm_grid_tick,
// module 8) with no R7-deviation justification. Same shape as
// road_wear.cpp (module 21): the dict iteration (bounded by distinct
// ever-farmed tiles, not the whole map) stays in Python — only the
// per-tile scalar arithmetic moves to C++.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

// max(floor, fertility - depletion_rate) — a tile loses fertility while
// actively farmed. Mirrors FarmGrid._tick_soil_fertility's depletion
// branch exactly.
double soil_fertility_deplete_step(double fertility, double depletion_rate, double floor) {
    return std::max(floor, fertility - depletion_rate);
}

// min(1.0, fertility + recovery_rate) — a fallow tile recovers fertility.
// Mirrors FarmGrid._tick_soil_fertility's recovery branch exactly.
double soil_fertility_recover_step(double fertility, double recovery_rate) {
    return std::min(1.0, fertility + recovery_rate);
}

}  // namespace

void register_soil_fertility(py::module_ &m) {
    m.def("soil_fertility_deplete_step", &soil_fertility_deplete_step,
          py::arg("fertility"), py::arg("depletion_rate"), py::arg("floor"),
          "max(floor, fertility - depletion_rate) — the active-plot depletion step.");
    m.def("soil_fertility_recover_step", &soil_fertility_recover_step,
          py::arg("fertility"), py::arg("recovery_rate"),
          "min(1.0, fertility + recovery_rate) — the fallow-tile recovery step.");
}
