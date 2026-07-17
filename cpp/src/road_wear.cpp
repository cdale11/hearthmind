// Native port of the two scalar operations behind RoadNetwork.tick
// (world/roads.py) — the per-tick pass that wears in a path under
// foot traffic and lets an abandoned one fade back to bare ground.
// Continues the R6 "opportunistic pure-math port" queue
// (docs/REFACTOR-2026-07.md) with the same shape as module 20
// (relationship_step.cpp): the dict iteration/prune-on-fade-to-zero
// bookkeeping stays in Python (a variable-size, sparse tile->wear
// dict, not a fit for a flat-array port per the R8 scoping pass) —
// only the per-tile scalar arithmetic moves to C++.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

// min(1.0, wear + gain_rate) — a tile gains wear while occupied.
double road_wear_gain_step(double wear, double gain_rate) {
    return std::min(1.0, wear + gain_rate);
}

// wear - decay_rate, unclamped below 0 — mirrors RoadNetwork.tick's
// decay branch exactly: the caller deletes the entry once the result
// drops to/below 0.0 rather than clamping here, so this stays a pure
// scalar step with no dict-mutation policy baked in.
double road_wear_decay_step(double wear, double decay_rate) {
    return wear - decay_rate;
}

}  // namespace

void register_road_wear(py::module_ &m) {
    m.def("road_wear_gain_step", &road_wear_gain_step,
          py::arg("wear"), py::arg("gain_rate"),
          "min(1.0, wear + gain_rate) — the foot-traffic wear-in bump.");
    m.def("road_wear_decay_step", &road_wear_decay_step,
          py::arg("wear"), py::arg("decay_rate"),
          "wear - decay_rate, unclamped — mirrors RoadNetwork.tick's fade branch.");
}
