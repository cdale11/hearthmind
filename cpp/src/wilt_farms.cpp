// Native port of _wilt_farms (world/disasters.py) — module 13,
// continuing R7's cellular-automata physical substrate track. Shared
// by tick_heatwave and tick_frost: rolls exactly one `rng.random()`
// per farm plot, unconditionally, in `farms.plots.items()` order — a
// fixed, data-independent draw count per plot (unlike terrain_
// evolution.py's heat-threshold loop, where whether a tile gets rolled
// at all depends on its current heat value, making the total draw
// count itself data-dependent and much harder to pre-draw safely).
// Because the draw count here is fixed and unconditional, Python can
// pre-draw one roll per plot (preserving the exact stream order) and
// hand the whole batch to this function — same principle as module 8.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <tuple>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int STAGE_GROWING = 0;
constexpr int STAGE_READY = 1;

struct WiltEntry {
    double growth;
    double amount;
    bool hit;
    bool removed;
};

}  // namespace

// Input per plot: (stage, growth, amount, max_yield), and one
// pre-drawn roll per plot (same order). Output: (hit_count, per-plot
// results in the same order/length as input).
std::pair<int, std::vector<WiltEntry>> wilt_farms_tick(
    const std::vector<std::tuple<int, double, double, double>> &plots,
    const std::vector<double> &rolls, double chance, double loss_fraction
) {
    std::vector<WiltEntry> results;
    results.reserve(plots.size());
    int hit_count = 0;

    for (size_t i = 0; i < plots.size(); ++i) {
        int stage = std::get<0>(plots[i]);
        double growth = std::get<1>(plots[i]);
        double amount = std::get<2>(plots[i]);
        double max_yield = std::get<3>(plots[i]);
        double roll = rolls[i];

        if (roll >= chance) {
            results.push_back({growth, amount, false, false});
            continue;
        }
        hit_count += 1;
        bool removed = false;
        if (stage == STAGE_GROWING) {
            growth = std::max(0.0, growth - loss_fraction);
        } else if (stage == STAGE_READY) {
            amount = std::max(0.0, amount - loss_fraction * max_yield);
            removed = amount <= 0.0;
        }
        results.push_back({growth, amount, true, removed});
    }
    return {hit_count, results};
}

void register_wilt_farms(py::module_ &m) {
    py::class_<WiltEntry>(m, "WiltEntry")
        .def_readonly("growth", &WiltEntry::growth)
        .def_readonly("amount", &WiltEntry::amount)
        .def_readonly("hit", &WiltEntry::hit)
        .def_readonly("removed", &WiltEntry::removed);

    m.def("wilt_farms_tick", &wilt_farms_tick,
          py::arg("plots"), py::arg("rolls"), py::arg("chance"), py::arg("loss_fraction"),
          "Mirrors world/disasters.py _wilt_farms exactly, given one "
          "pre-drawn RNG roll per plot in the same order. Returns "
          "(hit_count, per-plot results).");
}
