// Native port of the pure-math tail of Population._maybe_predator_attack
// (agents/population.py) — module 7 of the R6 "full engine rewrite"
// track (docs/REFACTOR-2026-07.md). Only the kill-chance *computation*
// moves to C++; the two `rng.random()` rolls (attack-happens, then
// kill-vs-survive) stay in Python exactly where they were, in the same
// order, so the namespaced-RNG stream this project depends on for
// determinism-where-natural is untouched by this port — a native
// function must never introduce a second, uncoordinated source of
// randomness.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

double predator_kill_chance(
    double base_kill_chance, bool has_hospital, double hospital_reduction,
    double temperament, double temperament_influence,
    double resilience, double resilience_influence
) {
    double kill_chance = base_kill_chance;
    if (has_hospital) {
        kill_chance *= (1.0 - hospital_reduction);
    }
    kill_chance = std::max(0.0, kill_chance * (1.0 - temperament * temperament_influence));
    kill_chance = std::max(0.0, kill_chance * (1.0 - resilience * resilience_influence));
    return kill_chance;
}

}  // namespace

void register_predator_kill_chance(py::module_ &m) {
    m.def("predator_kill_chance", &predator_kill_chance,
          py::arg("base_kill_chance"), py::arg("has_hospital"), py::arg("hospital_reduction"),
          py::arg("temperament"), py::arg("temperament_influence"),
          py::arg("resilience"), py::arg("resilience_influence"),
          "Mirrors the kill-chance computation inside agents/population.py "
          "Population._maybe_predator_attack exactly. Pure math, no RNG — "
          "the caller still does its own rng.random() < kill_chance roll.");
}
