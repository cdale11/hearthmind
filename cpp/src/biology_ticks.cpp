// Native port of five of A14 "Layered organism biology"'s per-agent,
// per-tick scalar drift passes (agents/population.py):
// Population._tick_sleep_debt / _tick_immune_strength / _tick_stress /
// _tick_injury_recovery / _tick_development — the same "runs for
// every agent, every tick, unconditionally, pure scalar arithmetic"
// shape module 6 (needs.cpp) and module 19 (emotion_decay.cpp)
// established, and (per docs/REFACTOR-2026-07.md's R6 section) exactly
// the category of function this opportunistic-port queue exists for.
// These five were flagged in that same doc's own "still Python: the
// agent tick logic" note as real, un-ported per-tick per-agent
// candidates once the queue's original items (weather/soil/mining/
// road/relationship) were all closed.
//
// One shared BiologyConstants struct (same "build once per tick, pass
// to every agent's call" pattern NeedsConstants established) rather
// than five separate small structs, since Population.tick() calls all
// five in a fixed sequence over the same agent list every tick and the
// constants themselves never change mid-tick.
//
// Each function takes only already-resolved scalars/booleans — no
// dict/object access. `_tick_stress`'s `fear`/`grief` are the two
// specific `agent.emotions` values it reads (0.0 for a missing key,
// matching `.get(key, 0.0)`) and `has_feud` is the boolean result of
// `any(flag == "feud" for flag in agent.relationship_flags.values())`
// — both dict scans stay in Python, exactly like `_update_needs`' own
// split (object/dict resolution in Python, arithmetic in C++).
//
// `_tick_injury_recovery`/`_tick_development` each have a real early-
// out in the Python original (`if agent.injury <= 0.0: continue` /
// `if agent.development >= 1.0: continue`) — mirrored here as a
// same-value no-op return so Python can call unconditionally for
// every agent without re-implementing the branch, simplifying the
// call site to the same uniform shape as the other three.
#include <pybind11/pybind11.h>

#include <algorithm>

namespace py = pybind11;

struct BiologyConstants {
    double sleep_debt_adapt_rate;
    double immune_hunger_weight;
    double immune_energy_weight;
    double sleep_debt_immune_weight;
    double immune_baseline;
    double immune_adapt_rate;
    double sickness_immune_drain_per_tick;
    double immune_strength_floor;
    double stress_fear_weight;
    double stress_grief_weight;
    double critical_hunger_threshold;
    double stress_hunger_crisis_pull;
    double stress_sickness_pull;
    double stress_feud_pull;
    double stress_adapt_rate;
    double injury_recovery_rate;
    double injury_recovery_hunger_weight;
    double injury_recovery_energy_weight;
    double development_growth_per_tick;
    double development_nutrition_weight;
    double development_nutrition_min_factor;
    double development_nutrition_max_factor;
};

namespace {

double clamp01(double v) { return std::min(1.0, std::max(0.0, v)); }

double tick_sleep_debt(const BiologyConstants &c, double energy, double sleep_debt) {
    double target = clamp01(1.0 - energy);
    double next = sleep_debt + (target - sleep_debt) * c.sleep_debt_adapt_rate;
    return clamp01(next);
}

double tick_immune_strength(
    const BiologyConstants &c, double hunger, double energy, double sleep_debt,
    double immune_strength, bool sick
) {
    double nutrition_pull = (0.5 - hunger) * 2.0 * c.immune_hunger_weight;
    double rest_pull = (energy - 0.5) * 2.0 * c.immune_energy_weight;
    double sleep_drag = sleep_debt * c.sleep_debt_immune_weight;
    double target = clamp01(c.immune_baseline + nutrition_pull + rest_pull - sleep_drag);
    double next = immune_strength + (target - immune_strength) * c.immune_adapt_rate;
    if (sick) next -= c.sickness_immune_drain_per_tick;
    return std::min(1.0, std::max(c.immune_strength_floor, next));
}

double tick_stress(
    const BiologyConstants &c, double fear, double grief, double hunger,
    bool sick, bool has_feud, double stress
) {
    double target = fear * c.stress_fear_weight + grief * c.stress_grief_weight;
    if (hunger >= c.critical_hunger_threshold) target += c.stress_hunger_crisis_pull;
    if (sick) target += c.stress_sickness_pull;
    if (has_feud) target += c.stress_feud_pull;
    target = clamp01(target);
    double next = stress + (target - stress) * c.stress_adapt_rate;
    return clamp01(next);
}

double tick_injury_recovery(const BiologyConstants &c, double hunger, double energy, double injury) {
    if (injury <= 0.0) return injury;
    double nutrition_factor = 1.0 + (0.5 - hunger) * 2.0 * c.injury_recovery_hunger_weight;
    double rest_factor = 1.0 + (energy - 0.5) * 2.0 * c.injury_recovery_energy_weight;
    double rate = c.injury_recovery_rate * (nutrition_factor + rest_factor) / 2.0;
    return clamp01(injury - rate);
}

double tick_development(const BiologyConstants &c, double hunger, double development) {
    if (development >= 1.0) return development;
    double nutrition_factor = std::min(
        c.development_nutrition_max_factor,
        std::max(c.development_nutrition_min_factor,
                  1.0 + (0.5 - hunger) * 2.0 * c.development_nutrition_weight));
    return clamp01(development + c.development_growth_per_tick * nutrition_factor);
}

}  // namespace

void register_biology_ticks(py::module_ &m) {
    py::class_<BiologyConstants>(m, "BiologyConstants")
        .def(py::init<>())
        .def_readwrite("sleep_debt_adapt_rate", &BiologyConstants::sleep_debt_adapt_rate)
        .def_readwrite("immune_hunger_weight", &BiologyConstants::immune_hunger_weight)
        .def_readwrite("immune_energy_weight", &BiologyConstants::immune_energy_weight)
        .def_readwrite("sleep_debt_immune_weight", &BiologyConstants::sleep_debt_immune_weight)
        .def_readwrite("immune_baseline", &BiologyConstants::immune_baseline)
        .def_readwrite("immune_adapt_rate", &BiologyConstants::immune_adapt_rate)
        .def_readwrite("sickness_immune_drain_per_tick", &BiologyConstants::sickness_immune_drain_per_tick)
        .def_readwrite("immune_strength_floor", &BiologyConstants::immune_strength_floor)
        .def_readwrite("stress_fear_weight", &BiologyConstants::stress_fear_weight)
        .def_readwrite("stress_grief_weight", &BiologyConstants::stress_grief_weight)
        .def_readwrite("critical_hunger_threshold", &BiologyConstants::critical_hunger_threshold)
        .def_readwrite("stress_hunger_crisis_pull", &BiologyConstants::stress_hunger_crisis_pull)
        .def_readwrite("stress_sickness_pull", &BiologyConstants::stress_sickness_pull)
        .def_readwrite("stress_feud_pull", &BiologyConstants::stress_feud_pull)
        .def_readwrite("stress_adapt_rate", &BiologyConstants::stress_adapt_rate)
        .def_readwrite("injury_recovery_rate", &BiologyConstants::injury_recovery_rate)
        .def_readwrite("injury_recovery_hunger_weight", &BiologyConstants::injury_recovery_hunger_weight)
        .def_readwrite("injury_recovery_energy_weight", &BiologyConstants::injury_recovery_energy_weight)
        .def_readwrite("development_growth_per_tick", &BiologyConstants::development_growth_per_tick)
        .def_readwrite("development_nutrition_weight", &BiologyConstants::development_nutrition_weight)
        .def_readwrite("development_nutrition_min_factor", &BiologyConstants::development_nutrition_min_factor)
        .def_readwrite("development_nutrition_max_factor", &BiologyConstants::development_nutrition_max_factor);

    m.def("tick_sleep_debt", &tick_sleep_debt, py::arg("constants"), py::arg("energy"), py::arg("sleep_debt"),
          "Mirrors Population._tick_sleep_debt's per-agent update exactly.");
    m.def("tick_immune_strength", &tick_immune_strength,
          py::arg("constants"), py::arg("hunger"), py::arg("energy"), py::arg("sleep_debt"),
          py::arg("immune_strength"), py::arg("sick"),
          "Mirrors Population._tick_immune_strength's per-agent update exactly.");
    m.def("tick_stress", &tick_stress,
          py::arg("constants"), py::arg("fear"), py::arg("grief"), py::arg("hunger"),
          py::arg("sick"), py::arg("has_feud"), py::arg("stress"),
          "Mirrors Population._tick_stress's per-agent update exactly.");
    m.def("tick_injury_recovery", &tick_injury_recovery,
          py::arg("constants"), py::arg("hunger"), py::arg("energy"), py::arg("injury"),
          "Mirrors Population._tick_injury_recovery's per-agent update exactly, "
          "including the injury<=0 no-op.");
    m.def("tick_development", &tick_development,
          py::arg("constants"), py::arg("hunger"), py::arg("development"),
          "Mirrors Population._tick_development's per-agent update exactly, "
          "including the development>=1.0 no-op.");
}
