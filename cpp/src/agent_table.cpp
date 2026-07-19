// Native structure-of-arrays storage for Agent's dense scalar fields —
// R8 slice 3, the first attempt at the object-graph track's harder
// half. Explicitly staged per the v0.74.2 scoping pass: Agent has ~700
// scalar-field touch sites across the codebase (vs. terrain's ~60
// clean indexing sites), almost all interleaved with the six variable-
// size per-agent dict/list fields (relationships, trust, inventory,
// memories, skills, traits) that stay Python-side regardless. This
// module ships and verifies the storage PRIMITIVE ONLY — a compiled
// AgentTable, proven byte-identical against a parallel Python
// reference implementation via randomized append/remove/get/set fuzz
// testing, the same discipline as every other module here. It is
// NOT yet wired into the live `Population.agents` list; that requires
// a full call-site verification pass (the ~700-site risk surface) as
// its own follow-up, not bundled into the same change as the storage
// primitive itself. See docs/REFACTOR-2026-07.md, "R8 slice 3."
//
// Scalar fields stored (12, matching Agent's non-container fields):
// id (int64), x/y (int32), hunger/energy (double), state (int32 enum
// code: 0=AWAKE, 1=RESTING), age_ticks/max_age_ticks/starving_ticks/
// sick_ticks/immune_ticks (int64), goal (int32 enum code: 0=WANDER,
// 1=FORAGE, 2=SOCIALIZE, 3=REST, 4=GATHER, 5=SEEK_PERSON, 6=EXPLORE),
// settlement_id (int32).
// True parallel-array layout (one vector per field, not one vector of
// structs) — genuine SoA, not just "a C++ class holding the data."
//
// Removal uses swap-with-last (tombstone-free): removing slot i moves
// the last slot's data into slot i and shrinks by one. This keeps
// storage dense (no wasted slots to skip over) at the cost of
// reassigning whichever id occupied the last slot to a new index —
// the caller (Python, which owns the id->slot map) is told which id
// moved and to which slot, so it can update its own map. Fine at this
// project's population scale (POPULATION_CAP=400, confirmed via the
// v0.74.2 scoping pass) — a moved slot's caller-side bookkeeping cost
// is O(1) per removal, not a concern at any realistic population.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdint>
#include <stdexcept>
#include <vector>

namespace py = pybind11;

namespace {

struct RemoveResult {
    bool moved;             // true if a slot other than the removed one now holds different data
    int64_t moved_agent_id;  // the id that now occupies `slot` (the removed slot's old index), if moved
};

class NativeAgentTable {
public:
    int size() const { return static_cast<int>(id_.size()); }

    // Appends a new agent's scalar fields, returns its slot index.
    int append(
        int64_t id, int x, int y, double hunger, double energy, int state,
        int64_t age_ticks, int64_t max_age_ticks, int64_t starving_ticks,
        int64_t sick_ticks, int64_t immune_ticks, int goal, int settlement_id
    ) {
        id_.push_back(id);
        x_.push_back(x);
        y_.push_back(y);
        hunger_.push_back(hunger);
        energy_.push_back(energy);
        state_.push_back(state);
        age_ticks_.push_back(age_ticks);
        max_age_ticks_.push_back(max_age_ticks);
        starving_ticks_.push_back(starving_ticks);
        sick_ticks_.push_back(sick_ticks);
        immune_ticks_.push_back(immune_ticks);
        goal_.push_back(goal);
        settlement_id_.push_back(settlement_id);
        return size() - 1;
    }

    // Swap-with-last removal. Returns whether a different slot's data
    // moved into `slot`, and if so, which agent id now lives there.
    RemoveResult remove(int slot) {
        check_bounds(slot);
        int last = size() - 1;
        if (slot == last) {
            pop_back();
            return {false, 0};
        }
        move_slot(last, slot);
        int64_t moved_id = id_[slot];
        pop_back();
        return {true, moved_id};
    }

    int64_t get_id(int slot) const { check_bounds(slot); return id_[slot]; }
    int get_x(int slot) const { check_bounds(slot); return x_[slot]; }
    int get_y(int slot) const { check_bounds(slot); return y_[slot]; }
    double get_hunger(int slot) const { check_bounds(slot); return hunger_[slot]; }
    double get_energy(int slot) const { check_bounds(slot); return energy_[slot]; }
    int get_state(int slot) const { check_bounds(slot); return state_[slot]; }
    int64_t get_age_ticks(int slot) const { check_bounds(slot); return age_ticks_[slot]; }
    int64_t get_max_age_ticks(int slot) const { check_bounds(slot); return max_age_ticks_[slot]; }
    int64_t get_starving_ticks(int slot) const { check_bounds(slot); return starving_ticks_[slot]; }
    int64_t get_sick_ticks(int slot) const { check_bounds(slot); return sick_ticks_[slot]; }
    int64_t get_immune_ticks(int slot) const { check_bounds(slot); return immune_ticks_[slot]; }
    int get_goal(int slot) const { check_bounds(slot); return goal_[slot]; }
    int get_settlement_id(int slot) const { check_bounds(slot); return settlement_id_[slot]; }

    void set_x(int slot, int v) { check_bounds(slot); x_[slot] = v; }
    void set_y(int slot, int v) { check_bounds(slot); y_[slot] = v; }
    void set_hunger(int slot, double v) { check_bounds(slot); hunger_[slot] = v; }
    void set_energy(int slot, double v) { check_bounds(slot); energy_[slot] = v; }
    void set_state(int slot, int v) { check_bounds(slot); state_[slot] = v; }
    void set_age_ticks(int slot, int64_t v) { check_bounds(slot); age_ticks_[slot] = v; }
    void set_max_age_ticks(int slot, int64_t v) { check_bounds(slot); max_age_ticks_[slot] = v; }
    void set_starving_ticks(int slot, int64_t v) { check_bounds(slot); starving_ticks_[slot] = v; }
    void set_sick_ticks(int slot, int64_t v) { check_bounds(slot); sick_ticks_[slot] = v; }
    void set_immune_ticks(int slot, int64_t v) { check_bounds(slot); immune_ticks_[slot] = v; }
    void set_goal(int slot, int v) { check_bounds(slot); goal_[slot] = v; }
    void set_settlement_id(int slot, int v) { check_bounds(slot); settlement_id_[slot] = v; }

private:
    void check_bounds(int slot) const {
        if (slot < 0 || slot >= size()) throw std::out_of_range("AgentTable slot out of range");
    }

    void move_slot(int from, int to) {
        id_[to] = id_[from];
        x_[to] = x_[from];
        y_[to] = y_[from];
        hunger_[to] = hunger_[from];
        energy_[to] = energy_[from];
        state_[to] = state_[from];
        age_ticks_[to] = age_ticks_[from];
        max_age_ticks_[to] = max_age_ticks_[from];
        starving_ticks_[to] = starving_ticks_[from];
        sick_ticks_[to] = sick_ticks_[from];
        immune_ticks_[to] = immune_ticks_[from];
        goal_[to] = goal_[from];
        settlement_id_[to] = settlement_id_[from];
    }

    void pop_back() {
        id_.pop_back(); x_.pop_back(); y_.pop_back();
        hunger_.pop_back(); energy_.pop_back(); state_.pop_back();
        age_ticks_.pop_back(); max_age_ticks_.pop_back(); starving_ticks_.pop_back();
        sick_ticks_.pop_back(); immune_ticks_.pop_back();
        goal_.pop_back(); settlement_id_.pop_back();
    }

    std::vector<int64_t> id_;
    std::vector<int> x_, y_;
    std::vector<double> hunger_, energy_;
    std::vector<int> state_;
    std::vector<int64_t> age_ticks_, max_age_ticks_, starving_ticks_, sick_ticks_, immune_ticks_;
    std::vector<int> goal_, settlement_id_;
};

}  // namespace

void register_agent_table(py::module_ &m) {
    py::class_<RemoveResult>(m, "AgentTableRemoveResult")
        .def_readonly("moved", &RemoveResult::moved)
        .def_readonly("moved_agent_id", &RemoveResult::moved_agent_id);

    py::class_<NativeAgentTable>(m, "AgentTable")
        .def(py::init<>())
        .def("size", &NativeAgentTable::size)
        .def("append", &NativeAgentTable::append,
             py::arg("id"), py::arg("x"), py::arg("y"), py::arg("hunger"), py::arg("energy"),
             py::arg("state"), py::arg("age_ticks"), py::arg("max_age_ticks"),
             py::arg("starving_ticks"), py::arg("sick_ticks"), py::arg("immune_ticks"),
             py::arg("goal"), py::arg("settlement_id"))
        .def("remove", &NativeAgentTable::remove, py::arg("slot"),
             "Swap-with-last removal. Returns (moved, moved_agent_id) — "
             "if moved, the caller's id->slot map must be updated to "
             "point moved_agent_id at `slot`.")
        .def("get_id", &NativeAgentTable::get_id, py::arg("slot"))
        .def("get_x", &NativeAgentTable::get_x, py::arg("slot"))
        .def("get_y", &NativeAgentTable::get_y, py::arg("slot"))
        .def("get_hunger", &NativeAgentTable::get_hunger, py::arg("slot"))
        .def("get_energy", &NativeAgentTable::get_energy, py::arg("slot"))
        .def("get_state", &NativeAgentTable::get_state, py::arg("slot"))
        .def("get_age_ticks", &NativeAgentTable::get_age_ticks, py::arg("slot"))
        .def("get_max_age_ticks", &NativeAgentTable::get_max_age_ticks, py::arg("slot"))
        .def("get_starving_ticks", &NativeAgentTable::get_starving_ticks, py::arg("slot"))
        .def("get_sick_ticks", &NativeAgentTable::get_sick_ticks, py::arg("slot"))
        .def("get_immune_ticks", &NativeAgentTable::get_immune_ticks, py::arg("slot"))
        .def("get_goal", &NativeAgentTable::get_goal, py::arg("slot"))
        .def("get_settlement_id", &NativeAgentTable::get_settlement_id, py::arg("slot"))
        .def("set_x", &NativeAgentTable::set_x, py::arg("slot"), py::arg("value"))
        .def("set_y", &NativeAgentTable::set_y, py::arg("slot"), py::arg("value"))
        .def("set_hunger", &NativeAgentTable::set_hunger, py::arg("slot"), py::arg("value"))
        .def("set_energy", &NativeAgentTable::set_energy, py::arg("slot"), py::arg("value"))
        .def("set_state", &NativeAgentTable::set_state, py::arg("slot"), py::arg("value"))
        .def("set_age_ticks", &NativeAgentTable::set_age_ticks, py::arg("slot"), py::arg("value"))
        .def("set_max_age_ticks", &NativeAgentTable::set_max_age_ticks, py::arg("slot"), py::arg("value"))
        .def("set_starving_ticks", &NativeAgentTable::set_starving_ticks, py::arg("slot"), py::arg("value"))
        .def("set_sick_ticks", &NativeAgentTable::set_sick_ticks, py::arg("slot"), py::arg("value"))
        .def("set_immune_ticks", &NativeAgentTable::set_immune_ticks, py::arg("slot"), py::arg("value"))
        .def("set_goal", &NativeAgentTable::set_goal, py::arg("slot"), py::arg("value"))
        .def("set_settlement_id", &NativeAgentTable::set_settlement_id, py::arg("slot"), py::arg("value"));
}
