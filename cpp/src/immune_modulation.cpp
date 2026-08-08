// R8, second slice (docs/ROADMAP-2026-07-REMAINING.md's Phase 7):
// `Population._immune_modulation_factor`'s formula — "the real 'not a
// coin flip' bridge: how much an agent's current immune_strength
// should scale a base sickness rate." A pure clamp formula, called
// twice per real tick per relevant agent inside `_tick_disease` (once
// scaling a sick agent's own death chance, once scaling a healthy
// colocated agent's transmission chance) — real, if sparse (only sick/
// colocated agents), per-tick work, same "small pure scalar function,
// no object/string construction" shape module 12's `bounded_random_
// walk_step` and this R8 slice's own `memory_salience_decay_step`
// already established.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

double immune_modulation_factor(
    double immune_strength, double baseline, double sensitivity,
    double min_factor, double max_factor
) {
    double raw = 1.0 + (baseline - immune_strength) * sensitivity;
    return std::max(min_factor, std::min(max_factor, raw));
}

}  // namespace

void register_immune_modulation(py::module_ &m) {
    m.def("immune_modulation_factor", &immune_modulation_factor,
          py::arg("immune_strength"), py::arg("baseline"), py::arg("sensitivity"),
          py::arg("min_factor"), py::arg("max_factor"),
          "1.0 + (baseline - immune_strength) * sensitivity, clamped to "
          "[min_factor, max_factor]. Mirrors Population._immune_"
          "modulation_factor exactly.");
}
