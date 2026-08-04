// Native port of world/terrain_evolution.py's `_tick_fallow` inner
// forest-neighbor count -- C++ porting backlog, continued
// (docs/ROADMAP-2026-07-REMAINING.md's parallel track). Same "resolve
// enums/objects in Python, hand C++ only plain data" discipline every
// prior module in this queue follows: `_tick_fallow` runs weekly over
// the FULL terrain grid (checking every GRASSLAND tile's 4 orthogonal
// neighbors for FOREST, the reclaim-eligibility gate), but the
// neighbor loop itself never needs a `Tile`/`Biome` object -- only a
// plain forest/not-forest boolean per tile, precomputed once in Python
// before calling in. Same 4-neighbor bounds-checked shape
// `ca_operators.cpp`'s `ca_diffuse` already established, just counting
// booleans instead of averaging floats.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <vector>

namespace py = pybind11;

namespace {

constexpr int DX[4] = {0, 0, -1, 1};
constexpr int DY[4] = {-1, 1, 0, 0};

}  // namespace

// Mirrors world/terrain_evolution.py's `_tick_fallow` forest-neighbor
// loop exactly: for every tile, counts how many of its in-bounds
// 4 orthogonal neighbors are forested.
std::vector<std::vector<int>> forest_neighbor_counts(const std::vector<std::vector<bool>> &is_forest) {
    int height = static_cast<int>(is_forest.size());
    if (height == 0) return {};
    int width = static_cast<int>(is_forest[0].size());
    if (width == 0) return std::vector<std::vector<int>>(height);

    std::vector<std::vector<int>> result(height, std::vector<int>(width, 0));
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            int count = 0;
            for (int i = 0; i < 4; ++i) {
                int nx = x + DX[i], ny = y + DY[i];
                if (nx >= 0 && nx < width && ny >= 0 && ny < height && is_forest[ny][nx]) {
                    ++count;
                }
            }
            result[y][x] = count;
        }
    }
    return result;
}

void register_terrain_neighbor_count(py::module_ &m) {
    m.def("forest_neighbor_counts", &forest_neighbor_counts, py::arg("is_forest"),
          "For every tile, count how many of its in-bounds 4 orthogonal "
          "neighbors are forested. Mirrors world/terrain_evolution.py's "
          "_tick_fallow forest-neighbor loop exactly.");
}
