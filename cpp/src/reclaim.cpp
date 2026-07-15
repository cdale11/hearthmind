// Native port of maybe_reclaim (world/terrain_evolution.py) — module
// 17, the first module using a callback-into-Python-RNG design rather
// than pre-drawing. maybe_reclaim has a genuine same-pass dependency
// (documented as blocking a native port since v0.72.11): converting an
// earlier grassland tile to FOREST in the same pass can change a
// later tile's forest-neighbor count, so the roll count/positions
// can't be determined up front and batched like every other module
// here. Preserving exact behavior requires the C++ loop to call back
// into Python for each conditional roll, in the same order the
// pure-Python loop would draw them — slower per-call than a batched
// native function, but the neighbor-counting/branching (the actual
// per-tile cost) still moves to C++, and RNG draw order/count is
// unaffected either way (this project's standing rule: reproducing
// CPython's Mersenne Twister isn't required, only native-vs-Python
// parity for the same call sequence).
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include <cstdint>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace {
constexpr int BIOME_OTHER = 0;
constexpr int BIOME_GRASSLAND = 1;
constexpr int BIOME_FOREST = 2;
}  // namespace

// `biome` is a flat, row-major width*height array of BIOME_OTHER/
// GRASSLAND/FOREST codes, mutated in place as tiles reclaim (so a
// later tile in the same pass sees an earlier tile's conversion, same
// as the pure-Python original mutating `terrain` directly). `developed`
// is a flat, row-major bool array — Python precomputes `_is_developed`
// OR `(x, y) in heat` once before calling, since neither changes during
// this function's own loop. `roll` is `rng.random` bound as a Python
// callable, invoked only when a tile's forest-neighbor count clears
// the threshold (matching the original's exact conditional-roll
// count). Returns reclaimed (x, y) positions in the order they
// occurred, for the caller to build event text.
std::vector<std::pair<int, int>> maybe_reclaim_tick(
    int width, int height, std::vector<int> &biome, const std::vector<uint8_t> &developed,
    int min_forest_neighbors, double chance_per_week, py::function roll
) {
    std::vector<std::pair<int, int>> reclaimed;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            int idx = y * width + x;
            if (biome[idx] != BIOME_GRASSLAND) continue;
            if (developed[idx]) continue;
            int forest_neighbors = 0;
            if (y > 0 && biome[(y - 1) * width + x] == BIOME_FOREST) forest_neighbors += 1;
            if (y < height - 1 && biome[(y + 1) * width + x] == BIOME_FOREST) forest_neighbors += 1;
            if (x > 0 && biome[y * width + (x - 1)] == BIOME_FOREST) forest_neighbors += 1;
            if (x < width - 1 && biome[y * width + (x + 1)] == BIOME_FOREST) forest_neighbors += 1;
            if (forest_neighbors < min_forest_neighbors) continue;
            double roll_value = roll().cast<double>();
            if (roll_value >= chance_per_week) continue;
            biome[idx] = BIOME_FOREST;
            reclaimed.emplace_back(x, y);
        }
    }
    return reclaimed;
}

void register_reclaim(py::module_ &m) {
    m.def("maybe_reclaim_tick", &maybe_reclaim_tick,
          py::arg("width"), py::arg("height"), py::arg("biome"), py::arg("developed"),
          py::arg("min_forest_neighbors"), py::arg("chance_per_week"), py::arg("roll"),
          "Mirrors world/terrain_evolution.py maybe_reclaim's scan/roll "
          "loop exactly, calling back into `roll` (rng.random bound) for "
          "each conditional roll to preserve the genuine same-pass "
          "dependency (an earlier reclaim changes later neighbor counts "
          "in the same pass).");
}
