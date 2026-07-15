// Native port of FarmGrid.tick (economy/farms.py) — module 8 of the
// incremental C++ port, and the first R7 "cellular-automata physical
// substrate" module: a plain per-cell/per-tick local-rule pass over
// every farm plot (GROWING -> accumulate growth, flip to READY at 1.0;
// READY -> accumulate ready_ticks, rot past FARM_ROT_TICKS) — the same
// shape as resource_grid_tick (module 1), just a second grid.
//
// Irrigation (`is_adjacent_to_water`) is resolved in Python before the
// call — it's a terrain-adjacency lookup over `Tile` objects, not
// per-cell farm state, so it stays with the rest of the object-graph
// resolution this project's native ports keep in Python (same
// principle as needs.cpp's `sheltered`/`hospital` booleans).
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <tuple>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int STAGE_GROWING = 0;
constexpr int STAGE_READY = 1;

}  // namespace

// Input: (x, y, stage, growth, amount, max_yield, ready_ticks, irrigated).
// Output: (updated plots in the same shape/order, positions that rotted
// this tick — the caller deletes those from FarmGrid.plots, mirroring
// the pure-Python `del self.plots[pos]` loop).
std::pair<
    std::vector<std::tuple<int, int, int, double, double, double, int>>,
    std::vector<std::pair<int, int>>
> farm_grid_tick(
    const std::vector<std::tuple<int, int, int, double, double, double, int, bool>> &plots,
    double base_growth_rate, double irrigation_multiplier, int farm_rot_ticks
) {
    std::vector<std::tuple<int, int, int, double, double, double, int>> updated;
    std::vector<std::pair<int, int>> rotted;
    updated.reserve(plots.size());

    for (const auto &p : plots) {
        int x = std::get<0>(p);
        int y = std::get<1>(p);
        int stage = std::get<2>(p);
        double growth = std::get<3>(p);
        double amount = std::get<4>(p);
        double max_yield = std::get<5>(p);
        int ready_ticks = std::get<6>(p);
        bool irrigated = std::get<7>(p);

        if (stage == STAGE_GROWING) {
            double growth_rate = base_growth_rate;
            if (irrigated) growth_rate *= irrigation_multiplier;
            growth = std::min(1.0, growth + growth_rate);
            if (growth >= 1.0) {
                stage = STAGE_READY;
                amount = max_yield;
            }
        } else if (stage == STAGE_READY) {
            ready_ticks += 1;
            if (ready_ticks >= farm_rot_ticks) {
                rotted.emplace_back(x, y);
                continue;  // rotted plots are removed, not carried into `updated`
            }
        }
        updated.emplace_back(x, y, stage, growth, amount, max_yield, ready_ticks);
    }
    return {updated, rotted};
}

void register_farm_grid(py::module_ &m) {
    m.def("farm_grid_tick", &farm_grid_tick,
          py::arg("plots"), py::arg("base_growth_rate"), py::arg("irrigation_multiplier"),
          py::arg("farm_rot_ticks"),
          "Mirrors economy/farms.py FarmGrid.tick exactly, given "
          "already-resolved irrigation booleans. Returns (updated_plots, "
          "rotted_positions).");
}
