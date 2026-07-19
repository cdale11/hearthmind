// Native port of the two scalar operations behind apply_mining_scars/
// decay_mining_scars (world/terrain_evolution.py) — v1 audit fix: CLAUDE.md
// described this as "a flagged R7 deviation... low-density tile lookups
// don't justify a native port yet," but that flag never actually existed
// in the source file (only in project-memory prose) and the loop is a
// genuine per-tick, active-miner-count-scaled hot path (apply_mining_scars)
// plus a per-week full-dict pass (decay_mining_scars). Same shape as
// road_wear.cpp/soil_fertility.cpp: the dict iteration + first-crossing
// event bookkeeping stays in Python — only the per-tile scalar step moves
// to C++.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

// min(1.0, scar + gain_rate) — a mined tile's scar deepens.
double mining_scar_gain_step(double scar, double gain_rate) {
    return std::min(1.0, scar + gain_rate);
}

// scar - decay_rate, unclamped below 0 — mirrors decay_mining_scars'
// weathering branch exactly; the caller deletes the entry once the
// result drops to/below 0.0, same convention as road_wear_decay_step.
double mining_scar_decay_step(double scar, double decay_rate) {
    return scar - decay_rate;
}

}  // namespace

void register_mining_scars(py::module_ &m) {
    m.def("mining_scar_gain_step", &mining_scar_gain_step,
          py::arg("scar"), py::arg("gain_rate"),
          "min(1.0, scar + gain_rate) — the per-tick active-mining scar bump.");
    m.def("mining_scar_decay_step", &mining_scar_decay_step,
          py::arg("scar"), py::arg("decay_rate"),
          "scar - decay_rate, unclamped — mirrors decay_mining_scars' weekly fade.");
}
