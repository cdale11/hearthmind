// Native port of the grazer-branch scalar math behind WildlifeGrid.tick
// (world/wildlife.py) — the per-tick pass that has each live grazer herd
// nibble a colocated FOOD resource node and roll to reproduce. Continues
// the R6 "opportunistic pure-math port" queue (docs/REFACTOR-2026-07.md)
// with the same shape as modules 20/21 (relationship_step.cpp/road_wear.
// cpp): herd/dict iteration, movement (terrain-dependent candidate
// search), and the predator branch's cross-herd prey lookup all stay in
// Python (object-graph work, not a fit for a pure-math port) — only the
// grazer branch's self-contained per-herd scalar arithmetic moves here.
// The RNG draw (`rng.random()` for the reproduce roll) stays in Python
// and is passed in, exactly like bounded_random_walk_step's jitter and
// roll_passes_tick's pre-drawn rolls — this file makes no RNG calls of
// its own, preserving the caller's draw order/count exactly.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

// Bundles WildlifeGrid.tick's grazer branch (node consumption + overgraze
// check + reproduce roll) into one call. Returns (new_count,
// new_node_amount, grazed) where `grazed` mirrors the original code's
// `grazing_food` flag — the caller only needs it to decide whether to
// call resources.mark_regenerating (a pure-Python-object side effect,
// so it can't move here).
py::tuple grazer_tick_step(
    int count, bool has_food_node, double node_amount, double graze_consumption,
    double reproduce_min_food, int max_herd_size, double reproduce_chance, double reproduce_roll
) {
    bool grazed = has_food_node;
    double new_amount = node_amount;
    if (grazed) {
        new_amount = std::max(0.0, node_amount - graze_consumption);
    }
    bool overgrazed = grazed && new_amount < reproduce_min_food;
    int new_count = count;
    if (count < max_herd_size && !overgrazed && reproduce_roll < reproduce_chance) {
        new_count = count + 1;
    }
    return py::make_tuple(new_count, new_amount, grazed);
}

}  // namespace

void register_wildlife_step(py::module_ &m) {
    m.def("grazer_tick_step", &grazer_tick_step,
          py::arg("count"), py::arg("has_food_node"), py::arg("node_amount"),
          py::arg("graze_consumption"), py::arg("reproduce_min_food"),
          py::arg("max_herd_size"), py::arg("reproduce_chance"), py::arg("reproduce_roll"),
          "Grazer-branch scalar step: node consumption + overgraze check + "
          "reproduce roll. Mirrors WildlifeGrid.tick's GRAZER branch exactly; "
          "the reproduce roll is drawn by the caller and passed in.");
}
