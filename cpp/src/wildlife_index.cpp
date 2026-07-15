// Native port of WildlifeGrid.nearest_grazer_herd (world/wildlife.py) —
// module 5 of the incremental C++ port (docs/REFACTOR-2026-07.md, R5).
// Same live-patch shape as ResourceIndex (cpp/src/resource_grid.cpp):
// herd positions only change in WildlifeGrid.tick() (migration), which
// always runs before Population.tick() each engine tick (see world/
// state.py's World.tick ordering) — but herd *counts* can drop to 0
// mid-Population.tick() via Population._maybe_forage's hunt() call, so
// a plain once-per-tick rebuild alone would drift from the live
// pure-Python scan (which re-reads `herd.count` fresh on every call).
// `update()` mirrors ResourceIndex's live-patch pattern for exactly
// this reason.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdlib>
#include <optional>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

namespace py = pybind11;

class GrazerHerdIndex {
public:
    explicit GrazerHerdIndex(const std::vector<std::tuple<long long, int, int, int>> &herds) {
        // Insertion-order vector, not an unordered_map, is load-bearing
        // here: the pure-Python scan iterates `self.herds.values()` in
        // dict insertion order, and ties in Manhattan distance resolve
        // to "first encountered wins" — an unordered_map's iteration
        // order doesn't match that, so a tied-distance query could
        // silently pick a different (but equally valid) herd than the
        // Python path. Caught via a 20,000-query randomized equivalence
        // check before this fix (see docs/DECISIONS.md).
        entries_.reserve(herds.size());
        for (const auto &h : herds) {
            id_to_index_[std::get<0>(h)] = entries_.size();
            entries_.push_back(h);
        }
    }

    // Nearest live (count > 0) herd within `radius` (Chebyshev bounds
    // check, Manhattan tie-break — mirrors nearest_grazer_herd exactly,
    // including first-encountered-wins tie-break order).
    std::optional<std::pair<int, int>> nearest(int ax, int ay, int radius) const {
        std::optional<std::pair<int, int>> best;
        int best_dist = -1;
        for (const auto &entry : entries_) {
            int x = std::get<1>(entry);
            int y = std::get<2>(entry);
            int count = std::get<3>(entry);
            if (count <= 0) continue;
            int dx = std::abs(x - ax);
            int dy = std::abs(y - ay);
            if (std::max(dx, dy) > radius) continue;
            int dist = dx + dy;
            if (best_dist < 0 || dist < best_dist) {
                best = std::make_pair(x, y);
                best_dist = dist;
            }
        }
        return best;
    }

    // Live-patch one herd's count (and position, in case a future
    // caller ever moves a herd mid-tick) after a hunt. Updates in place
    // so `entries_`'s order — and therefore tie-break behavior — never
    // changes from a patch, only from a full rebuild.
    void update(long long herd_id, int x, int y, int count) {
        auto it = id_to_index_.find(herd_id);
        if (it == id_to_index_.end()) {
            id_to_index_[herd_id] = entries_.size();
            entries_.push_back({herd_id, x, y, count});
            return;
        }
        entries_[it->second] = {herd_id, x, y, count};
    }

private:
    std::vector<std::tuple<long long, int, int, int>> entries_;
    std::unordered_map<long long, size_t> id_to_index_;
};

void register_wildlife_index(py::module_ &m) {
    py::class_<GrazerHerdIndex>(m, "GrazerHerdIndex")
        .def(py::init<const std::vector<std::tuple<long long, int, int, int>> &>(), py::arg("herds"))
        .def("nearest", &GrazerHerdIndex::nearest, py::arg("ax"), py::arg("ay"), py::arg("radius"),
             "Nearest live grazer herd's (x, y) in range, else None. "
             "Mirrors world/wildlife.py WildlifeGrid.nearest_grazer_herd exactly.")
        .def("update", &GrazerHerdIndex::update, py::arg("herd_id"), py::arg("x"), py::arg("y"), py::arg("count"),
             "Live-patch one herd's position/count — keeps the index consistent "
             "with WildlifeGrid.herds between full rebuilds. See WildlifeGrid.hunt.");
}
