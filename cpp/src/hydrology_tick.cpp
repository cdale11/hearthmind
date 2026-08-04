// Native port of the two full-grid scalar passes behind
// world/hydrology_field.py's tick_hydrology/tick_groundwater (A11,
// "Continuous hydrology") -- picked up under the C++ porting backlog's
// standing discipline of "port to C++ once the shape is confirmed
// live," per that module's own docstring, which explicitly names this
// module (soil_fertility.cpp) as the precedent to follow. Unlike every
// prior port in this queue, these two functions run over the WHOLE
// terrain grid every real tick they fire (weekly), not a bounded
// per-agent/per-tile-dict subset -- the same full-grid shape as
// climate_drift.cpp's batch form, generalized to every tile rather
// than a sampled subset.
//
// Enum/object resolution stays in Python (same "resolve enums/objects
// in Python, hand C++ only plain data" discipline climate_drift.cpp
// established): the caller precomputes a per-tile water-biome boolean
// grid and the per-tile elevation grid before calling in, and this
// file never touches a `Tile`/`Biome` object directly. `tick_snowpack`
// (depends on the still-unported `ca_operators.reaction_diffuse`) and
// `tick_erosion` (writes new `Tile` objects with real biome
// reclassification, including the QUARRY-sticky special case) are
// deliberately NOT ported this pass -- a materially different, larger
// risk surface, flagged as separate future work.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <utility>
#include <vector>

namespace py = pybind11;

namespace {

// Mirrors world/hydrology_field.py's MOISTURE_PRECIPITATION_GAIN/
// MOISTURE_FLOW_FRACTION constants exactly -- verified by the
// randomized native-vs-fallback equivalence test, same discipline
// climate_drift.cpp's hardcoded CLIMATE_*_SHIFT constants already use.
constexpr double MOISTURE_PRECIPITATION_GAIN = 0.30;
constexpr double MOISTURE_FLOW_FRACTION = 0.20;
constexpr double MOISTURE_MIN = 0.0;
constexpr double MOISTURE_MAX = 1.0;

constexpr int DX[4] = {0, 0, -1, 1};
constexpr int DY[4] = {-1, 1, 0, 0};

}  // namespace

// One weekly tick_hydrology step: precipitation gain + evaporation
// (pass 1), then a single-step downhill transfer computed against a
// snapshot of pass 1's result (pass 2) -- mirrors tick_hydrology
// exactly, including pass 2 never depending on iteration order within
// itself. `precipitation`/`evaporation` are already-resolved scalars
// (the caller computes evaporation's season-conditional heat bonus in
// Python, a cheap string comparison not worth porting). `is_water` is
// a 0/1 grid the caller derives from each tile's real biome once per
// call, `elevation` a plain read-only copy of each tile's elevation.
std::vector<std::vector<double>> hydrology_moisture_tick(
    std::vector<std::vector<double>> moisture,
    const std::vector<std::vector<double>> &elevation,
    const std::vector<std::vector<int>> &is_water,
    double precipitation, double evaporation
) {
    int height = static_cast<int>(moisture.size());
    if (height == 0) return moisture;
    int width = static_cast<int>(moisture[0].size());
    if (width == 0) return moisture;

    // Pass 1: precipitation gain + evaporation, land tiles only.
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (is_water[y][x]) {
                moisture[y][x] = MOISTURE_MAX;
                continue;
            }
            double value = moisture[y][x] + MOISTURE_PRECIPITATION_GAIN * precipitation - evaporation;
            moisture[y][x] = std::max(MOISTURE_MIN, std::min(MOISTURE_MAX, value));
        }
    }

    // Pass 2: single-step downhill transfer against a pass-1 snapshot.
    std::vector<std::vector<double>> before = moisture;
    std::vector<std::vector<double>> deltas(height, std::vector<double>(width, 0.0));
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (is_water[y][x]) continue;
            int lx = -1, ly = -1;
            double lowest_elevation = elevation[y][x];
            for (int i = 0; i < 4; ++i) {
                int nx = x + DX[i], ny = y + DY[i];
                if (nx >= 0 && nx < width && ny >= 0 && ny < height && elevation[ny][nx] < lowest_elevation) {
                    lowest_elevation = elevation[ny][nx];
                    lx = nx;
                    ly = ny;
                }
            }
            if (lx < 0) continue;
            double excess = before[y][x] - before[ly][lx];
            if (excess <= 0.0) continue;
            double transfer = excess * MOISTURE_FLOW_FRACTION;
            deltas[y][x] -= transfer;
            deltas[ly][lx] += transfer;
        }
    }
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (is_water[y][x]) continue;
            moisture[y][x] = std::max(MOISTURE_MIN, std::min(MOISTURE_MAX, moisture[y][x] + deltas[y][x]));
        }
    }
    return moisture;
}

// One weekly tick_groundwater step: infiltration on wet land -> seep-
// back (base flow) on dry land -> constant percolation loss. Mirrors
// tick_groundwater exactly, including running over every tile (not
// just land, per that function's own docstring). Returns (new_
// moisture, new_groundwater) since the exchange mutates both grids.
std::pair<std::vector<std::vector<double>>, std::vector<std::vector<double>>> hydrology_groundwater_tick(
    std::vector<std::vector<double>> moisture,
    std::vector<std::vector<double>> groundwater
) {
    constexpr double GROUNDWATER_MIN = 0.0;
    constexpr double GROUNDWATER_MAX = 1.0;
    constexpr double GROUNDWATER_INFILTRATION_THRESHOLD = 0.6;
    constexpr double GROUNDWATER_INFILTRATION_FRACTION = 0.08;
    constexpr double GROUNDWATER_SEEP_THRESHOLD = 0.3;
    constexpr double GROUNDWATER_SEEP_FRACTION = 0.05;
    constexpr double GROUNDWATER_PERCOLATION_LOSS = 0.01;

    int height = static_cast<int>(moisture.size());
    if (height == 0) return {moisture, groundwater};
    int width = static_cast<int>(moisture[0].size());
    if (width == 0) return {moisture, groundwater};

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            double m = moisture[y][x];
            double g = groundwater[y][x];
            if (m >= GROUNDWATER_INFILTRATION_THRESHOLD) {
                double infiltrated = (m - GROUNDWATER_INFILTRATION_THRESHOLD) * GROUNDWATER_INFILTRATION_FRACTION;
                g += infiltrated;
                m = std::max(MOISTURE_MIN, m - infiltrated);
            } else if (m < GROUNDWATER_SEEP_THRESHOLD && g > GROUNDWATER_MIN) {
                double seep = std::min(g, GROUNDWATER_SEEP_THRESHOLD - m) * GROUNDWATER_SEEP_FRACTION;
                g -= seep;
                m = std::min(MOISTURE_MAX, m + seep);
            }
            g = std::max(GROUNDWATER_MIN, std::min(GROUNDWATER_MAX, g - GROUNDWATER_PERCOLATION_LOSS));
            moisture[y][x] = m;
            groundwater[y][x] = g;
        }
    }
    return {moisture, groundwater};
}

void register_hydrology_tick(py::module_ &m) {
    m.def("hydrology_moisture_tick", &hydrology_moisture_tick,
          py::arg("moisture"), py::arg("elevation"), py::arg("is_water"),
          py::arg("precipitation"), py::arg("evaporation"),
          "One weekly tick_hydrology step (precipitation gain + evaporation, "
          "then single-step downhill transfer). Mirrors world/hydrology_"
          "field.py's tick_hydrology exactly; returns the new moisture grid.");
    m.def("hydrology_groundwater_tick", &hydrology_groundwater_tick,
          py::arg("moisture"), py::arg("groundwater"),
          "One weekly tick_groundwater step (infiltration/seep/percolation). "
          "Mirrors world/hydrology_field.py's tick_groundwater exactly; "
          "returns (new_moisture, new_groundwater).");
}
