// Native port of Population's Phase I emotion-decay pass
// (agents/agent.py's decay_emotions, called from agents/population.py's
// Population.tick right after _update_needs) — same "runs every tick,
// for every agent, unconditionally" shape as module 6 (needs.cpp), the
// highest-value native-port category per that module's own precedent.
//
// Agent.emotions is a sparse Python dict (0-4 of the fear/joy/grief/
// anger keys, missing = 0.0) rather than a fixed-slot struct, so this
// takes all four as plain doubles (0.0 for an absent key) and returns
// all four updated — Python re-derives which keys to keep vs. drop from
// the EMOTION_NOTABLE_FLOOR check, exactly mirroring decay_emotions'
// own per-key < 0.005 prune. A missing key (0.0 in) decays to 0.0 out,
// a correct no-op, so this needs no separate "which keys are present"
// signal.
#include <pybind11/pybind11.h>

namespace py = pybind11;

struct EmotionState {
    double fear;
    double joy;
    double grief;
    double anger;
};

namespace {

EmotionState decay_emotions(const EmotionState &e, double decay_rate) {
    double factor = 1.0 - decay_rate;
    return {e.fear * factor, e.joy * factor, e.grief * factor, e.anger * factor};
}

}  // namespace

void register_emotion_decay(py::module_ &m) {
    py::class_<EmotionState>(m, "EmotionState")
        .def(py::init<>())
        .def(py::init<double, double, double, double>(),
             py::arg("fear") = 0.0, py::arg("joy") = 0.0, py::arg("grief") = 0.0, py::arg("anger") = 0.0)
        .def_readwrite("fear", &EmotionState::fear)
        .def_readwrite("joy", &EmotionState::joy)
        .def_readwrite("grief", &EmotionState::grief)
        .def_readwrite("anger", &EmotionState::anger);

    m.def("decay_emotions", &decay_emotions, py::arg("emotions"), py::arg("decay_rate"),
          "value * (1 - decay_rate) for all four axes. Mirrors "
          "agents/agent.py decay_emotions' per-key arithmetic exactly "
          "(the < 0.005 prune-vs-keep decision stays in Python).");
}
