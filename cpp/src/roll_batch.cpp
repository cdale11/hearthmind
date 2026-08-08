// Native port of "roll < chance" batch decisions — module 15. Several
// R7 physical-substrate loops (starting with apply_local_activity's
// deforestation roll, world/terrain_evolution.py) resolve a set of
// independent RNG-gated yes/no decisions per tick, where each
// candidate's eligibility depends only on state that existed *before*
// the loop started (not on other candidates' outcomes within the same
// pass) — see docs/DECISIONS.md for the distinction from
// `maybe_reclaim`, which doesn't have this property and stays pure
// Python. For loops with that property, Python can determine the
// candidate set and pre-draw one `rng.random()` per candidate (in the
// same order the pure-Python loop would), then hand the whole batch
// here. The comparison itself is trivial; the value is in having one
// shared, tested building block for "which of these candidates rolled
// under their threshold" rather than re-deriving it per call site.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <vector>

namespace py = pybind11;

namespace {

std::vector<bool> roll_passes_tick(const std::vector<double> &rolls, double chance) {
    std::vector<bool> results;
    results.reserve(rolls.size());
    for (double roll : rolls) {
        results.push_back(roll < chance);
    }
    return results;
}

// A2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 8): `roll_passes_tick`'s
// per-candidate sibling for when eligibility isn't a single flat
// probability — each candidate gets its OWN pre-computed chance (e.g.
// wildfire spread weighted by `ca_operators.cellular_step`-derived
// forest contiguity, world/disasters.py), rather than a single scalar
// shared by the whole batch. Same "compare pre-drawn roll against a
// threshold" triviality, same shared-tested-building-block reasoning —
// `rolls`/`chances` must be the same length (the Python call site
// builds both from the same candidate list, in the same order).
std::vector<bool> roll_passes_weighted(const std::vector<double> &rolls, const std::vector<double> &chances) {
    std::vector<bool> results;
    results.reserve(rolls.size());
    for (size_t i = 0; i < rolls.size(); ++i) {
        results.push_back(rolls[i] < chances[i]);
    }
    return results;
}

}  // namespace

void register_roll_batch(py::module_ &m) {
    m.def("roll_passes_tick", &roll_passes_tick,
          py::arg("rolls"), py::arg("chance"),
          "For each pre-drawn roll, whether roll < chance. Shared batch "
          "building block for RNG-gated per-candidate decisions whose "
          "eligibility doesn't depend on other candidates' outcomes "
          "within the same pass — see apply_local_activity's "
          "deforestation roll (world/terrain_evolution.py).");
    m.def("roll_passes_weighted", &roll_passes_weighted,
          py::arg("rolls"), py::arg("chances"),
          "Per-candidate sibling of roll_passes_tick: for each pre-drawn "
          "roll, whether roll < chances[i] (a distinct threshold per "
          "candidate, not one shared value) — see wildfire spread's "
          "contiguity-weighted chance (world/disasters.py).");
}
