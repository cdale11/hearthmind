// Native port of the bounded-random-walk step used across several
// monthly "nudge a value toward 0, with noise, clamped to [-1, 1]"
// mechanics — module 12. Same shape appears independently in
// `Settlement.tick_temperament`/`tick_player_standing`/`tick_relation`
// (settlement/buildings.py, R6 — general deterministic engine math,
// not physical substrate: temperament/player_standing are Phase G's
// literal deterministic implementation, dialogue-nudged relations are
// institution state) and `tick_climate`/`tick_lakes`'s lake-level nudge
// (world/terrain_evolution.py, world/hydrology.py — R7 physical
// substrate). One shared function rather than five near-identical
// copies, following this project's existing `util.py` precedent
// (`clamp`/`namespaced_rng` were already deduplicated the same way,
// see docs/DECISIONS.md v0.69.0).
//
// As with module 11 (weather), the RNG draw itself (`rng.uniform(-step,
// step)`) stays in Python — this function takes the already-drawn
// jitter value and does the mean-reversion/extra-term/clamp arithmetic.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

double bounded_random_walk_step(
    double value, double mean_reversion, double jitter, double extra,
    double low, double high
) {
    double stepped = value * mean_reversion + jitter + extra;
    return std::max(low, std::min(high, stepped));
}

}  // namespace

void register_bounded_random_walk(py::module_ &m) {
    m.def("bounded_random_walk_step", &bounded_random_walk_step,
          py::arg("value"), py::arg("mean_reversion"), py::arg("jitter"), py::arg("extra"),
          py::arg("low"), py::arg("high"),
          "value*mean_reversion + jitter + extra, clamped to [low, high]. "
          "Shared math behind tick_temperament/tick_player_standing/"
          "tick_relation (settlement/buildings.py), tick_climate "
          "(world/terrain_evolution.py), and the lake-level nudge inside "
          "tick_lakes (world/hydrology.py). The RNG draw producing "
          "`jitter` stays in Python — see this file's header comment.");
}
