// Native port of Population._nearest_other_agent (agents/population.py,
// D4) — module 4 of the incremental C++ port (docs/REFACTOR-2026-07.md,
// R5). Unlike the terrain/resource ports, this one is a genuine O(N^2)
// per-tick cost: SOCIALIZE-goal agents scan the *entire* population's
// position snapshot with no distance cap (see _nearest_other_agent's
// docstring, D4 — an agent seeking company is assumed to roughly know
// where everyone else is), so this is O(population) per query and
// O(population^2) worst case across a tick, growing directly with the
// LLM core cast's town size rather than a fixed map-shaped cost.
//
// No index structure is needed (nothing to bucket by — the search has
// no radius), just a fast linear scan. Built once per Population.tick()
// from the same `position_snapshot` list the pure-Python path already
// builds, in the same order, so tie-breaking (first-strictly-closer-
// wins, in list order) is identical to the Python scan.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdlib>
#include <optional>
#include <tuple>
#include <utility>
#include <vector>

namespace py = pybind11;

class AgentPositionIndex {
public:
    explicit AgentPositionIndex(const std::vector<std::tuple<long long, int, int>> &positions)
        : positions_(positions) {}

    std::optional<std::pair<int, int>> nearest(long long agent_id, int ax, int ay) const {
        std::optional<std::pair<int, int>> best;
        int best_dist = -1;
        for (const auto &entry : positions_) {
            long long other_id = std::get<0>(entry);
            if (other_id == agent_id) continue;
            int x = std::get<1>(entry);
            int y = std::get<2>(entry);
            int dist = std::abs(x - ax) + std::abs(y - ay);
            if (best_dist < 0 || dist < best_dist) {
                best = std::make_pair(x, y);
                best_dist = dist;
            }
        }
        return best;
    }

private:
    std::vector<std::tuple<long long, int, int>> positions_;
};

void register_agent_position_index(py::module_ &m) {
    py::class_<AgentPositionIndex>(m, "AgentPositionIndex")
        .def(py::init<const std::vector<std::tuple<long long, int, int>> &>(), py::arg("positions"))
        .def("nearest", &AgentPositionIndex::nearest, py::arg("agent_id"), py::arg("ax"), py::arg("ay"),
             "Nearest other agent's (x, y) by Manhattan distance, no radius cap, else None. "
             "Mirrors agents/population.py Population._nearest_other_agent exactly.");
}
