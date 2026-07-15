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

#include <optional>
#include <string>
#include <tuple>
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

namespace {

inline long long encode_key(int x, int y) {
    // Same encoding as resource_grid_tick's `key` and Python's
    // `resources.py::ResourceGrid._tick_native._key` — kept consistent
    // across every native lookup site in this module, even though each
    // currently builds it independently (no shared header yet; a small,
    // deliberate duplication rather than premature module-splitting for
    // a two-file extension).
    return (static_cast<long long>(x) << 32) ^ static_cast<unsigned int>(y);
}

}  // namespace

// Native port of Population._nearest_resource's bounded-box scan (see
// agents/population.py, v0.67.0 perf pass) — the second module in the
// incremental C++ port (docs/REFACTOR-2026-07.md, R5). Unlike
// ResourceGrid.tick (mutates nodes in place, called once per tick),
// this is a *query* called up to once per forage-seeking agent per
// tick, so the win here is amortizing the cost of building a native
// lookup structure across every agent's query that tick, not the
// per-query cost alone — mirrors the existing "compute food_positions/
// granary_positions once per tick, share across agents" pattern
// already used one call site up (`Population.tick`). Only FOOD (kind 0)
// and FISH (kind 1) nodes are indexed — ORE never participates in
// foraging, matching the pure-Python version's kind filter.
class ResourceIndex {
public:
    explicit ResourceIndex(const std::vector<std::tuple<int, int, int, double>> &nodes) {
        data_.reserve(nodes.size());
        for (const auto &entry : nodes) {
            int x = std::get<0>(entry);
            int y = std::get<1>(entry);
            int kind = std::get<2>(entry);
            double amount = std::get<3>(entry);
            if (amount <= 0.0) continue;
            data_[encode_key(x, y)] = std::make_pair(kind, std::make_pair(x, y));
        }
    }

    std::optional<std::pair<int, int>> nearest(int ax, int ay, int radius) const {
        std::optional<std::pair<int, int>> best_food, best_fish;
        int best_food_dist = -1, best_fish_dist = -1;
        for (int dy = -radius; dy <= radius; ++dy) {
            int y = ay + dy;
            for (int dx = -radius; dx <= radius; ++dx) {
                int x = ax + dx;
                auto it = data_.find(encode_key(x, y));
                if (it == data_.end()) continue;
                int kind = it->second.first;
                int dist = std::abs(dx) + std::abs(dy);
                if (kind == 1) {  // fish
                    if (best_fish_dist < 0 || dist < best_fish_dist) {
                        best_fish = it->second.second;
                        best_fish_dist = dist;
                    }
                } else {  // food
                    if (best_food_dist < 0 || dist < best_food_dist) {
                        best_food = it->second.second;
                        best_food_dist = dist;
                    }
                }
            }
        }
        return best_fish.has_value() ? best_fish : best_food;
    }

    // Live incremental patch — called from Python's `mark_regenerating`
    // (the same call site R4's `_regenerating` working set already
    // hooks) right after a forage/gather depletes a node, so this
    // index stays consistent with `ResourceGrid.nodes` for the rest of
    // the current tick without a full rebuild. Erases the entry when
    // amount drops to/below 0 (matches the constructor's amount>0
    // filter — a stale zero-amount entry would otherwise still be
    // "found" by `nearest`).
    void update(int x, int y, int kind, double amount) {
        long long key = encode_key(x, y);
        if (amount <= 0.0) {
            data_.erase(key);
        } else {
            data_[key] = std::make_pair(kind, std::make_pair(x, y));
        }
    }

private:
    std::unordered_map<long long, std::pair<int, std::pair<int, int>>> data_;
};

// Defined in terrain_index.cpp — a separate translation unit compiled
// into this same extension module (see setup.py); registered here
// since a Python extension module can only have one PYBIND11_MODULE
// entry point.
void register_terrain_index(py::module_ &m);
void register_agent_position_index(py::module_ &m);
void register_wildlife_index(py::module_ &m);
void register_needs(py::module_ &m);
void register_predator_kill_chance(py::module_ &m);
void register_farm_grid(py::module_ &m);
void register_settlement_decay(py::module_ &m);
void register_weather(py::module_ &m);
void register_bounded_random_walk(py::module_ &m);
void register_wilt_farms(py::module_ &m);
void register_flat_damage(py::module_ &m);

PYBIND11_MODULE(_native, m) {
    m.doc() = "Hearthmind native (C++) hot-path extensions. Optional — "
              "every function here has a pure-Python fallback; the sim "
              "runs correctly (just slower) if this extension isn't built.";
    m.def("resource_grid_tick", &resource_grid_tick,
          py::arg("positions"), py::arg("amounts"), py::arg("kinds"), py::arg("season"),
          "Regenerate all below-cap resource nodes in `positions`. Returns "
          "(updated_amounts_by_key, still_below_cap_positions). Mirrors "
          "world/resources.py ResourceGrid.tick exactly.");

    py::class_<ResourceIndex>(m, "ResourceIndex")
        .def(py::init<const std::vector<std::tuple<int, int, int, double>> &>(), py::arg("nodes"))
        .def("nearest", &ResourceIndex::nearest, py::arg("ax"), py::arg("ay"), py::arg("radius"),
             "Nearest FISH node in range, else nearest FOOD node, else None. "
             "Mirrors agents/population.py Population._nearest_resource exactly.")
        .def("update", &ResourceIndex::update, py::arg("x"), py::arg("y"), py::arg("kind"), py::arg("amount"),
             "Live-patch one entry (upsert, or erase if amount <= 0) — "
             "keeps the index consistent with ResourceGrid.nodes between "
             "full rebuilds. See ResourceGrid.mark_regenerating.");

    register_terrain_index(m);
    register_agent_position_index(m);
    register_wildlife_index(m);
    register_needs(m);
    register_predator_kill_chance(m);
    register_farm_grid(m);
    register_settlement_decay(m);
    register_weather(m);
    register_bounded_random_walk(m);
    register_wilt_farms(m);
    register_flat_damage(m);
}
