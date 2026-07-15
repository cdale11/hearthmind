// Native port of the biome-step mutation math inside apply_climate_
// drift (world/terrain_evolution.py) — module 16, first case of a
// Biome enum crossing the pybind11 boundary in this codebase. Python
// enums can't cross directly, so both sides speak plain `int` biome
// codes matching BIOME_ORDER's position (0=DEEP_WATER..7=SNOWCAP) —
// Python converts `Biome -> int` via `BIOME_ORDER.index(...)` before
// the call and `int -> Biome` via `BIOME_ORDER[i]` after, the same
// "resolve enums/objects in Python, hand C++ only plain data" strategy
// already used by TerrainMaterialIndex and apply_local_activity's
// Biome.FOREST filtering (no precedent for the enum itself crossing).
//
// The sampling loop's tile-selection (_is_developed/_skip_climate_
// drift, RIVER exclusion via BIOME_ORDER membership) stays entirely
// in Python, same as every other module here — this only takes over
// classify_with_bias's threshold table plus the one-step-toward-
// target arithmetic, for tiles Python has already decided are
// eligible. RNG draws (rng.randrange(width)/(height) for tile
// sampling) also stay in Python — this module draws no RNG at all.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <tuple>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int BIOME_COUNT = 8;  // DEEP_WATER..SNOWCAP, matches BIOME_ORDER

constexpr double CLIMATE_WATER_SHIFT = 0.05;
constexpr double CLIMATE_LAND_SHIFT = 0.05;
constexpr double CLIMATE_COLD_SHIFT = 0.05;

struct DriftResult {
    int new_biome_idx;
    bool changed;
};

}  // namespace

// Mirrors world/terrain.py classify_with_bias exactly, returning a
// BIOME_ORDER index (0..7) instead of a Biome enum value.
int classify_biome_index(double elevation, double warming, double drying) {
    const std::pair<double, int> thresholds[BIOME_COUNT] = {
        {0.30 - drying * CLIMATE_WATER_SHIFT, 0},  // DEEP_WATER
        {0.38 - drying * CLIMATE_WATER_SHIFT, 1},  // SHALLOW_WATER
        {0.42 - drying * CLIMATE_WATER_SHIFT, 2},  // BEACH
        {0.62 + drying * CLIMATE_LAND_SHIFT, 3},   // GRASSLAND
        {0.75 + drying * CLIMATE_LAND_SHIFT, 4},   // FOREST
        {0.87 + warming * CLIMATE_COLD_SHIFT, 5},  // HILLS
        {0.95 + warming * CLIMATE_COLD_SHIFT, 6},  // MOUNTAIN
        {1.01 + warming * CLIMATE_COLD_SHIFT, 7},  // SNOWCAP
    };
    for (const auto &entry : thresholds) {
        if (elevation < entry.first) return entry.second;
    }
    return 7;  // SNOWCAP
}

// One eligible tile: classify its elevation-implied target biome, and
// if different from its current biome, step the current index by ±1
// toward the target (never jump straight there) — mirrors apply_
// climate_drift's lines 277-284 exactly.
DriftResult climate_drift_step(double elevation, double warming, double drying, int cur_biome_idx) {
    int target_idx = classify_biome_index(elevation, warming, drying);
    if (target_idx == cur_biome_idx) return {cur_biome_idx, false};
    int step = target_idx > cur_biome_idx ? 1 : -1;
    return {cur_biome_idx + step, true};
}

// Batch form: one (elevation, cur_biome_idx) pair per already-
// eligible sampled tile (Python has already filtered out developed/
// skip/RIVER tiles) — returns the same-length, same-order result
// list. No RNG anywhere in this module.
std::vector<DriftResult> climate_drift_batch(
    const std::vector<std::tuple<double, int>> &entries, double warming, double drying
) {
    std::vector<DriftResult> results;
    results.reserve(entries.size());
    for (const auto &entry : entries) {
        results.push_back(climate_drift_step(std::get<0>(entry), warming, drying, std::get<1>(entry)));
    }
    return results;
}

void register_climate_drift(py::module_ &m) {
    py::class_<DriftResult>(m, "DriftResult")
        .def_readonly("new_biome_idx", &DriftResult::new_biome_idx)
        .def_readonly("changed", &DriftResult::changed);

    m.def("classify_biome_index", &classify_biome_index,
          py::arg("elevation"), py::arg("warming"), py::arg("drying"),
          "Mirrors world/terrain.py classify_with_bias exactly, returning "
          "a BIOME_ORDER index (0..7) instead of a Biome enum value.");

    m.def("climate_drift_batch", &climate_drift_batch,
          py::arg("entries"), py::arg("warming"), py::arg("drying"),
          "Batch form of climate_drift_step — one (elevation, "
          "cur_biome_idx) pair per already-eligible sampled tile. "
          "Mirrors apply_climate_drift's per-tile biome-step mutation "
          "exactly (world/terrain_evolution.py).");
}
