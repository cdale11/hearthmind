// Native port of `Population.decay_memory_salience`'s per-memory step —
// the first real slice of R8 (docs/ROADMAP-2026-07-REMAINING.md's
// Phase 7: "agent tick logic still living in population.py, ported to
// C++ one function at a time, following the same randomized-
// equivalence + full-World.to_dict() hash-soak discipline as every
// other cpp/src/ module"). `Agent.memory_salience`/`memory_causes` are
// plain per-instance Python lists (index-aligned with `Agent.memories`,
// NOT part of the native `AgentStore`'s fixed scalar fields), so this
// crosses the pybind11 boundary once per (agent, memory-index) pair —
// the exact same per-scalar-call shape module 12's
// `bounded_random_walk_step` and module 20's `relationship_decay_step`/
// `relationship_gain_step` already established for a variable-count,
// per-tick-called scalar update.
//
// Called once per real sim-day (`day_end`), not every tick — a much
// lighter cadence than needs/biology_ticks (called every tick) — but
// still bounded by `population * MAX_AGENT_MEMORIES`, real work worth
// a native fast path at scale. Every branch/threshold/rate lookup this
// mirrors lives in `agents/population.py`'s `decay_memory_salience`;
// see that method's own docstring for the full rationale (a causally-
// tagged or already-vivid memory decays at the slow
// MEMORY_MAJOR_EVENT_DECAY_PER_DAY rate, permanently; everything else
// at MEMORY_FADE_DECAY_PER_DAY, floored at MEMORY_FADE_FLOOR).
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

namespace {

double memory_salience_decay_step(
    double current_salience, bool has_known_cause,
    double major_event_salience_threshold, double major_event_decay_per_day,
    double fade_decay_per_day, double floor
) {
    double rate;
    if (has_known_cause || current_salience >= major_event_salience_threshold) {
        rate = major_event_decay_per_day;
    } else {
        rate = fade_decay_per_day;
    }
    double decayed = current_salience * rate;
    return std::max(floor, decayed);
}

}  // namespace

void register_memory_salience_decay(py::module_ &m) {
    m.def("memory_salience_decay_step", &memory_salience_decay_step,
          py::arg("current_salience"), py::arg("has_known_cause"),
          py::arg("major_event_salience_threshold"), py::arg("major_event_decay_per_day"),
          py::arg("fade_decay_per_day"), py::arg("floor"),
          "One memory's daily salience decay step. A causally-tagged "
          "memory, or one already at/above `major_event_salience_"
          "threshold`, decays at `major_event_decay_per_day` "
          "(permanently — checked against the CURRENT value, matching "
          "population.py's own comment on why); everything else decays "
          "at `fade_decay_per_day`. Floored at `floor`. Mirrors "
          "Population.decay_memory_salience's inner loop exactly.");
}
