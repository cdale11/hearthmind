// Native (C++) port of hearthmind.world.resources.ResourceGrid.tick.
//
// This is the first module in the incremental C++ port (see
// docs/DECISIONS.md, "Native extension port"). It mirrors
// world/resources.py exactly — same constants, same working-set
// iteration (only below-cap nodes visited, R4), same season multiplier
// table — and is called from Python via a thin pybind11 binding
// (hearthmind/_native.*.so, see hearthmind/world/resources.py's
// `_tick_native` fallback wiring). Kept in a plain function operating on
// primitive arrays (not a stateful C++ class mirroring the dataclass) so
// the Python ResourceGrid stays the single source of truth for state;
// this function only replaces the hot inner loop.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <string>
#include <unordered_map>
#include <vector>

namespace py = pybind11;

namespace {

constexpr double MAX_NODE_AMOUNT = 1.0;
constexpr double MAX_ORE_AMOUNT = 2.0;
constexpr double MAX_FISH_AMOUNT = 1.5;
constexpr double REGEN_PER_TICK = 0.002;
constexpr double ORE_REGEN_PER_TICK = REGEN_PER_TICK / 12.0;
constexpr double FISH_REGEN_PER_TICK = REGEN_PER_TICK * 1.5;

double season_multiplier(const std::string &season) {
    if (season == "winter") return 0.3;
    if (season == "autumn") return 0.75;
    if (season == "spring") return 1.1;
    if (season == "summer") return 1.0;
    return 1.0;  // unrecognized season name defaults to 1.0, same as the Python dict.get fallback
}

}  // namespace

// positions: list of (x, y) currently in the "regenerating" working set.
// amounts: parallel dict (x,y-encoded key) -> current amount (input only —
//   pybind11's default STL casters copy Python containers rather than
//   share them, so a "mutate in place" reference parameter here would
//   silently no-op on the Python side; the updated amounts are returned
//   instead, not written back through the parameter).
// kinds: parallel dict (x,y-encoded key) -> kind string ("food"/"ore"/"fish").
// Returns (updated amounts by encoded key, positions still below cap).
std::pair<std::unordered_map<long long, double>, std::vector<std::pair<int, int>>>
resource_grid_tick(
    const std::vector<std::pair<int, int>> &positions,
    const std::unordered_map<long long, double> &amounts,
    const std::unordered_map<long long, std::string> &kinds,
    const std::string &season) {
    const double multiplier = season_multiplier(season);
    std::unordered_map<long long, double> updated = amounts;
    std::vector<std::pair<int, int>> still_regenerating;
    still_regenerating.reserve(positions.size());

    for (const auto &pos : positions) {
        const long long key = (static_cast<long long>(pos.first) << 32) ^
                               static_cast<unsigned int>(pos.second);
        auto amount_it = updated.find(key);
        if (amount_it == updated.end()) {
            continue;  // node vanished — defensive, matches Python's discard-and-continue
        }
        auto kind_it = kinds.find(key);
        const std::string &kind = kind_it != kinds.end() ? kind_it->second : "food";

        double cap, regen;
        if (kind == "ore") {
            cap = MAX_ORE_AMOUNT;
            regen = ORE_REGEN_PER_TICK * multiplier;
        } else if (kind == "fish") {
            cap = MAX_FISH_AMOUNT;
            regen = FISH_REGEN_PER_TICK * multiplier;
        } else {
            cap = MAX_NODE_AMOUNT;
            regen = REGEN_PER_TICK * multiplier;
        }

        double &amount = amount_it->second;
        if (amount < cap) {
            amount = std::min(cap, amount + regen);
        }
        if (amount < cap) {
            still_regenerating.push_back(pos);
        }
    }
    return {updated, still_regenerating};
}

PYBIND11_MODULE(_native, m) {
    m.doc() = "Hearthmind native (C++) hot-path extensions. Optional — "
              "every function here has a pure-Python fallback; the sim "
              "runs correctly (just slower) if this extension isn't built.";
    m.def("resource_grid_tick", &resource_grid_tick,
          py::arg("positions"), py::arg("amounts"), py::arg("kinds"), py::arg("season"),
          "Regenerate all below-cap resource nodes in `positions`. Returns "
          "(updated_amounts_by_key, still_below_cap_positions). Mirrors "
          "world/resources.py ResourceGrid.tick exactly.");
}
