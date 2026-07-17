// Native port of the two scalar operations behind Population.
// _update_relationships (agents/population.py) — the per-tick pass that
// decays every held relationship/trust value toward 0 and bumps
// colocated pairs toward affinity. Continues the R6 "opportunistic
// pure-math port" queue (docs/REFACTOR-2026-07.md) with the same shape
// as module 12 (bounded_random_walk.cpp): the dict iteration,
// itertools.combinations pairing, and prune-on-reach-zero bookkeeping
// all stay in Python (variable-size per-agent dicts, not a fit for a
// flat-array port per the R8 scoping pass) — only the per-value
// arithmetic moves to C++.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

// Pulls `value` toward 0.0 by `decay_rate`, from whichever side it's
// on, without crossing 0.0 — mirrors _update_relationships' decay
// branch exactly (relationship/trust values range -1..1 since E2's
// rivalry addition, so a plain one-sided clamp no longer applies).
double relationship_decay_step(double value, double decay_rate) {
    if (value > 0.0) {
        return std::max(0.0, value - decay_rate);
    }
    if (value < 0.0) {
        return std::min(0.0, value + decay_rate);
    }
    return 0.0;
}

// min(cap, value + gain) — the colocation-gain bump applied to both
// sides of a colocated pair.
double relationship_gain_step(double value, double gain, double cap) {
    return std::min(cap, value + gain);
}

}  // namespace

void register_relationship_step(py::module_ &m) {
    m.def("relationship_decay_step", &relationship_decay_step,
          py::arg("value"), py::arg("decay_rate"),
          "Pulls value toward 0.0 by decay_rate without crossing it. "
          "Mirrors Population._update_relationships' decay branch.");
    m.def("relationship_gain_step", &relationship_gain_step,
          py::arg("value"), py::arg("gain"), py::arg("cap"),
          "min(cap, value + gain) — the colocation-gain bump.");
}
