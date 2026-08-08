// R8, third slice/batch (docs/ROADMAP-2026-07-REMAINING.md's Phase 7):
// `Population._tick_disease`'s hospital/medicine/resilience death-
// chance multiplier chain -- real per-tick work for every currently-
// sick agent (a meaningful fraction of the population during a real
// outbreak). Every object-shaped lookup (which settlement, whether it
// holds a standing hospital, how much medicine an agent carries) is
// resolved in Python first -- this function only does the already-
// resolved bool/float arithmetic, same split `_update_needs` (module
// 6) already established. The immune-modulation term
// (`immune_modulation_factor`, this same R8 batch's own second slice)
// is deliberately left OUT of this function and still applied
// separately in Python -- one shared formula, not duplicated.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

double disease_death_chance_multiplier(
    double base_chance,
    bool in_hospital_settlement, double hospital_reduction,
    bool has_medicine, double medicine_reduction,
    double resilience, double resilience_influence
) {
    double chance = base_chance;
    if (in_hospital_settlement) {
        chance *= (1.0 - hospital_reduction);
    }
    if (has_medicine) {
        chance *= (1.0 - medicine_reduction);
    }
    chance = std::max(0.0, chance * (1.0 - resilience * resilience_influence));
    return chance;
}

}  // namespace

void register_disease_death_chance(py::module_ &m) {
    m.def("disease_death_chance_multiplier", &disease_death_chance_multiplier,
          py::arg("base_chance"),
          py::arg("in_hospital_settlement"), py::arg("hospital_reduction"),
          py::arg("has_medicine"), py::arg("medicine_reduction"),
          py::arg("resilience"), py::arg("resilience_influence"),
          "Applies the hospital, medicine, and resilience reductions to "
          "a sick agent's base death chance, in that order, floored at "
          "0.0 after the resilience term (matching the original inline "
          "Python). Immune-strength modulation is applied separately "
          "by the caller via `immune_modulation_factor`. Mirrors "
          "Population._tick_disease's per-agent chain exactly.");
}
