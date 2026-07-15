// Native port of the flat-damage sweep inside tick_storm
// (world/disasters.py) — module 14, continuing R7's cellular-automata
// physical substrate track. Once a storm is determined to have
// triggered (a single, already-Python-side RNG check — see the header
// comment in disasters.py's tick_storm wiring), every standing
// building and every vehicle (regardless of stage — the pure-Python
// original applies this unconditionally to vehicles, unlike
// Settlement.tick's routine decay) takes a flat, unconditional
// condition hit with no further randomness involved. This is the
// simplest possible per-cell local rule: max(0, condition - damage)
// applied uniformly, no branching, no RNG.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <vector>

namespace py = pybind11;

namespace {

std::vector<double> flat_damage_tick(const std::vector<double> &conditions, double damage) {
    std::vector<double> results;
    results.reserve(conditions.size());
    for (double condition : conditions) {
        results.push_back(std::max(0.0, condition - damage));
    }
    return results;
}

}  // namespace

void register_flat_damage(py::module_ &m) {
    m.def("flat_damage_tick", &flat_damage_tick,
          py::arg("conditions"), py::arg("damage"),
          "max(0, condition - damage) applied to every entry. Mirrors "
          "the flat-damage sweep inside world/disasters.py tick_storm.");
}
