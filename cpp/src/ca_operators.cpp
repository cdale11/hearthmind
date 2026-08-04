// Native port of world/ca_operators.py's `diffuse`/`reaction_diffuse`
// -- C++ porting backlog, continued (docs/ROADMAP-2026-07-REMAINING.md's
// parallel track). Unlike every prior port in this queue, these two
// functions take NO domain objects at all (no Tile/Biome, no enum
// crossing, no dict iteration) -- a plain grid of doubles in, a plain
// grid of doubles out, the simplest possible port shape in this
// codebase. Picked up because `diffuse` is called from `world/fields.py`
// roughly a dozen times every real tick (once per FieldGrid field) and
// `reaction_diffuse` backs `hydrology_field.py`'s `tick_snowpack` --
// porting these also removes the one thing that kept `tick_snowpack`
// itself flagged un-ported after `hydrology_tick.cpp` shipped.
// `cellular_step` (this module's third operator) is NOT ported here --
// it takes a Python callable `rule` as its actual per-cell logic, which
// can't cross the pybind11 boundary without specializing per consumer;
// left in Python, same "resolve callables/objects in Python" discipline
// every other module in this queue already follows.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <utility>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int DX[4] = {0, 0, -1, 1};
constexpr int DY[4] = {-1, 1, 0, 0};

}  // namespace

// Mirrors world/ca_operators.py's `diffuse` exactly: each cell moves
// `rate` of the way toward the average of its in-bounds 4-neighbors.
// `rate <= 0.0` returns an unchanged copy, matching the Python
// early-out (never a division-by-zero on an edge cell with count=0,
// since that cell's neighbor_avg falls back to its own value).
std::vector<std::vector<double>> ca_diffuse(const std::vector<std::vector<double>> &grid, double rate) {
    int height = static_cast<int>(grid.size());
    if (height == 0) return grid;
    int width = static_cast<int>(grid[0].size());
    if (width == 0 || rate <= 0.0) return grid;

    std::vector<std::vector<double>> result(height, std::vector<double>(width, 0.0));
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            double total = 0.0;
            int count = 0;
            for (int i = 0; i < 4; ++i) {
                int nx = x + DX[i], ny = y + DY[i];
                if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                    total += grid[ny][nx];
                    ++count;
                }
            }
            double neighbor_avg = count ? total / count : grid[y][x];
            result[y][x] = grid[y][x] + rate * (neighbor_avg - grid[y][x]);
        }
    }
    return result;
}

// Mirrors world/ca_operators.py's `reaction_diffuse` exactly: two
// coupled fields exchange value each cell, mass-conserving, floored
// at 0.0 (never negative -- matches the Python's own max(0.0, ...)).
std::pair<std::vector<std::vector<double>>, std::vector<std::vector<double>>> ca_reaction_diffuse(
    const std::vector<std::vector<double>> &a, const std::vector<std::vector<double>> &b,
    double rate_a_to_b, double rate_b_to_a
) {
    int height = static_cast<int>(a.size());
    int width = height ? static_cast<int>(a[0].size()) : 0;
    std::vector<std::vector<double>> new_a(height, std::vector<double>(width, 0.0));
    std::vector<std::vector<double>> new_b(height, std::vector<double>(width, 0.0));
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            double av = a[y][x], bv = b[y][x];
            double transferred_to_b = av * rate_a_to_b;
            double transferred_to_a = bv * rate_b_to_a;
            double na = av - transferred_to_b + transferred_to_a;
            double nb = bv - transferred_to_a + transferred_to_b;
            new_a[y][x] = na > 0.0 ? na : 0.0;
            new_b[y][x] = nb > 0.0 ? nb : 0.0;
        }
    }
    return {new_a, new_b};
}

void register_ca_operators(py::module_ &m) {
    m.def("ca_diffuse", &ca_diffuse, py::arg("grid"), py::arg("rate"),
          "Each cell moves `rate` of the way toward the average of its "
          "in-bounds 4-neighbors. Mirrors world/ca_operators.py's "
          "diffuse exactly.");
    m.def("ca_reaction_diffuse", &ca_reaction_diffuse,
          py::arg("a"), py::arg("b"), py::arg("rate_a_to_b"), py::arg("rate_b_to_a"),
          "Two coupled fields exchange value each cell, mass-conserving. "
          "Mirrors world/ca_operators.py's reaction_diffuse exactly.");
}
