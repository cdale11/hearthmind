// Native port of Settlement.tick's building and vehicle decay/ruin/
// reclaim passes (settlement/buildings.py) — module 9 (buildings) and
// module 10 (vehicles) of the incremental C++ port, continuing R7's
// cellular-automata physical substrate track. Same shape as
// farm_grid_tick (module 8): a fixed collection of independent cells
// (buildings/vehicles), each updated purely from its own prior state
// plus tick-level scalar inputs (decay rate, ruin-removal threshold).
//
// Event text ("A structure at (x, y) fell into ruin.") stays in
// Python — it needs the building's x/y and this function only receives
// the fields relevant to the decay math itself, following the same
// "object-graph resolution stays Python" principle as every module
// since 6. This function returns per-cell result flags (`just_ruined`/
// `removed`/`just_broke`) so the caller knows exactly when to log an
// event and with which building/vehicle, without duplicating the
// decay logic in Python as well.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <tuple>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int BSTAGE_UNDER_CONSTRUCTION = 0;
constexpr int BSTAGE_STANDING = 1;
constexpr int BSTAGE_RUINED = 2;

}  // namespace

// Input per building: (stage, condition, is_hut, ruined_ticks,
// material_decay_factor). `material_decay_factor` is A5/A6's
// per-instance material-driven multiplier (world/materials.py's
// `material_decay_factor`, computed by the caller since resolving a
// building's effective material lives in world/materials.py, which
// itself imports BuildingKind from settlement/buildings.py — computing
// it here would be circular) — 1.0 reproduces the pre-A5/A6 flat rate
// exactly, a real per-instance value scales it (stone/ore/ceramic
// decay slower, wood/fiber faster, matching material_repair_factor's
// own real-world-intuition direction).
// Output per building, same order/length as input:
// (stage, condition, ruined_ticks, removed, just_ruined).
// A `removed` building's other fields are meaningless (dropped from
// `Settlement.buildings` entirely) — mirrors the pure-Python version's
// `continue` (never appended to `survivors`).
std::vector<std::tuple<int, double, int, bool, bool>> building_decay_tick(
    const std::vector<std::tuple<int, double, bool, int, double>> &buildings,
    double hut_decay, double civic_decay, int ruin_removal_ticks
) {
    std::vector<std::tuple<int, double, int, bool, bool>> results;
    results.reserve(buildings.size());

    for (const auto &b : buildings) {
        int stage = std::get<0>(b);
        double condition = std::get<1>(b);
        bool is_hut = std::get<2>(b);
        int ruined_ticks = std::get<3>(b);
        double material_decay_factor = std::get<4>(b);
        bool removed = false;
        bool just_ruined = false;

        if (stage == BSTAGE_STANDING) {
            double decay = (is_hut ? hut_decay : civic_decay) * material_decay_factor;
            condition = std::max(0.0, condition - decay);
            if (condition <= 0.0) {
                stage = BSTAGE_RUINED;
                just_ruined = true;
            }
        } else if (stage == BSTAGE_RUINED) {
            ruined_ticks += 1;
            if (ruined_ticks >= ruin_removal_ticks) {
                removed = true;
            }
        }
        // BSTAGE_UNDER_CONSTRUCTION: pass through unchanged, matching
        // the pure-Python version (neither branch touches it).
        results.emplace_back(stage, condition, ruined_ticks, removed, just_ruined);
    }
    return results;
}

// Input: condition per READY vehicle only (caller filters — non-READY
// vehicles are untouched by Settlement.tick and never passed in).
// Output: (new_condition, just_broke), same order/length as input.
std::vector<std::pair<double, bool>> vehicle_decay_tick(
    const std::vector<double> &conditions, double vehicle_decay
) {
    std::vector<std::pair<double, bool>> results;
    results.reserve(conditions.size());
    for (double condition : conditions) {
        double new_condition = std::max(0.0, condition - vehicle_decay);
        results.emplace_back(new_condition, new_condition <= 0.0);
    }
    return results;
}

void register_settlement_decay(py::module_ &m) {
    m.def("building_decay_tick", &building_decay_tick,
          py::arg("buildings"), py::arg("hut_decay"), py::arg("civic_decay"),
          py::arg("ruin_removal_ticks"),
          "Mirrors the building decay/ruin/reclaim loop inside "
          "settlement/buildings.py Settlement.tick exactly.");
    m.def("vehicle_decay_tick", &vehicle_decay_tick,
          py::arg("conditions"), py::arg("vehicle_decay"),
          "Mirrors the READY-vehicle decay loop inside "
          "settlement/buildings.py Settlement.tick exactly.");
}
