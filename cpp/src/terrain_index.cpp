// Native port of Population._nearest_material_tile's bounded-box scan
// (agents/population.py, D8) — module 3 of the incremental C++ port
// (docs/REFACTOR-2026-07.md, R5). Unlike ResourceGrid.tick/ResourceIndex,
// MATERIAL_BIOMES tiles (FOREST/HILLS) never deplete — GATHER harvests
// wood/stone abstractly without changing the tile's biome — so this
// index needs no live-patch/mark-regenerating equivalent: a plain
// once-per-`Population.tick()` rebuild (see world/state.py wiring) is
// exactly equivalent to the pure-Python scan, no incremental-sync logic
// required the way ResourceIndex needed for depletion.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdlib>
#include <optional>
#include <unordered_set>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace {

inline long long encode_key(int x, int y) {
    // Same encoding as resource_grid.cpp's `encode_key` — kept
    // independently here (no shared header yet) since this is a
    // separate, self-contained translation unit.
    return (static_cast<long long>(x) << 32) ^ static_cast<unsigned int>(y);
}

}  // namespace

class TerrainMaterialIndex {
public:
    explicit TerrainMaterialIndex(const std::vector<std::pair<int, int>> &positions) {
        data_.reserve(positions.size());
        for (const auto &pos : positions) {
            data_.insert(encode_key(pos.first, pos.second));
        }
    }

    // Only positions that are valid MATERIAL_BIOMES tiles are ever in
    // `data_` (built from terrain, which is already bounds-correct), so
    // an out-of-map (x, y) is simply absent — no separate width/height
    // bounds check needed, unlike the pure-Python version's explicit
    // `0 <= x < width` (which exists only to avoid an index error on a
    // list, not because out-of-bounds tiles are otherwise valid).
    std::optional<std::pair<int, int>> nearest(int ax, int ay, int radius) const {
        std::optional<std::pair<int, int>> best;
        int best_dist = -1;
        for (int dy = -radius; dy <= radius; ++dy) {
            int y = ay + dy;
            for (int dx = -radius; dx <= radius; ++dx) {
                int x = ax + dx;
                if (data_.find(encode_key(x, y)) == data_.end()) continue;
                int dist = std::abs(dx) + std::abs(dy);
                if (best_dist < 0 || dist < best_dist) {
                    best = std::make_pair(x, y);
                    best_dist = dist;
                }
            }
        }
        return best;
    }

private:
    std::unordered_set<long long> data_;
};

void register_terrain_index(py::module_ &m) {
    py::class_<TerrainMaterialIndex>(m, "TerrainMaterialIndex")
        .def(py::init<const std::vector<std::pair<int, int>> &>(), py::arg("positions"))
        .def("nearest", &TerrainMaterialIndex::nearest, py::arg("ax"), py::arg("ay"), py::arg("radius"),
             "Nearest MATERIAL_BIOMES (FOREST/HILLS) tile in range, else None. "
             "Mirrors agents/population.py Population._nearest_material_tile exactly.");
}
