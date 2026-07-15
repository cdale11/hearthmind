// Native port of SimClock.advance()'s calendar-boundary-crossing
// detection (time_system.py) — module 18, the first module that is
// literally "the engine advancing a world tick": SimClock.advance()
// runs unconditionally exactly once per tick, every tick, for the
// entire life of a world — the highest call-frequency function in the
// codebase. Pure integer/calendar arithmetic, no RNG, no object graph
// (Config's calendar shape is passed in as plain values, not the
// dataclass itself) — same "resolve objects in Python, hand C++ only
// plain data" pattern as every prior module. Deliberately does NOT
// take over SimClock itself (the dataclass, its properties, to_dict/
// from_dict) — this is a first small slice of the "engine running
// world ticks" object-graph track (R8), scoped tightly per the R8
// design doc's own recommendation to start with the least-entangled
// piece and prove the pattern before anything larger moves.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <vector>

namespace py = pybind11;

namespace {

struct ClockAdvanceResult {
    int tick_count;
    bool day_end;
    bool week_end;
    bool month_end;
    bool season_end;
    bool year_end;
};

// Mirrors SimClock's day_index/week_index/_month_index_absolute/
// season_index/year properties exactly, given plain calendar-shape
// inputs instead of a Config object.
struct CalendarPoint {
    int day_index;
    int week_index;
    int month_index_absolute;
    int season_index;
    int year;
};

CalendarPoint calendar_point(
    int tick_count, int sim_minutes_per_tick, int minutes_per_day,
    const std::vector<int> &days_per_month, const std::vector<int> &month_to_season,
    int start_day_of_year
) {
    long long total_sim_minutes = static_cast<long long>(tick_count) * sim_minutes_per_tick;
    int day_index = static_cast<int>(total_sim_minutes / minutes_per_day) + start_day_of_year;

    int days_per_year = 0;
    for (int d : days_per_month) days_per_year += d;

    // day_of_year = day_index % days_per_year, with Python's floor-mod
    // semantics (day_index is never negative here, so plain % matches).
    int day_of_year = day_index % days_per_year;
    int year = day_index / days_per_year;

    int remaining = day_of_year;
    int month_index = static_cast<int>(days_per_month.size()) - 1;
    for (size_t i = 0; i < days_per_month.size(); ++i) {
        if (remaining < days_per_month[i]) {
            month_index = static_cast<int>(i);
            break;
        }
        remaining -= days_per_month[i];
    }

    int month_index_absolute = year * static_cast<int>(days_per_month.size()) + month_index;
    int season_index = month_to_season[month_index];
    int week_index = day_index / 7;

    return {day_index, week_index, month_index_absolute, season_index, year};
}

}  // namespace

// Advances tick_count by one and reports which calendar boundaries
// were crossed — mirrors SimClock.advance() exactly.
ClockAdvanceResult sim_clock_advance(
    int tick_count, int sim_minutes_per_tick, int minutes_per_day,
    const std::vector<int> &days_per_month, const std::vector<int> &month_to_season,
    int start_day_of_year
) {
    CalendarPoint before = calendar_point(
        tick_count, sim_minutes_per_tick, minutes_per_day, days_per_month, month_to_season, start_day_of_year
    );
    int new_tick_count = tick_count + 1;
    CalendarPoint after = calendar_point(
        new_tick_count, sim_minutes_per_tick, minutes_per_day, days_per_month, month_to_season, start_day_of_year
    );

    return {
        new_tick_count,
        after.day_index != before.day_index,
        after.week_index != before.week_index,
        after.month_index_absolute != before.month_index_absolute,
        after.season_index != before.season_index,
        after.year != before.year,
    };
}

void register_sim_clock(py::module_ &m) {
    py::class_<ClockAdvanceResult>(m, "ClockAdvanceResult")
        .def_readonly("tick_count", &ClockAdvanceResult::tick_count)
        .def_readonly("day_end", &ClockAdvanceResult::day_end)
        .def_readonly("week_end", &ClockAdvanceResult::week_end)
        .def_readonly("month_end", &ClockAdvanceResult::month_end)
        .def_readonly("season_end", &ClockAdvanceResult::season_end)
        .def_readonly("year_end", &ClockAdvanceResult::year_end);

    m.def("sim_clock_advance", &sim_clock_advance,
          py::arg("tick_count"), py::arg("sim_minutes_per_tick"), py::arg("minutes_per_day"),
          py::arg("days_per_month"), py::arg("month_to_season"), py::arg("start_day_of_year"),
          "Mirrors time_system.py SimClock.advance() exactly, given "
          "plain calendar-shape values instead of a Config object. "
          "Returns the new tick_count plus which boundaries were "
          "crossed.");
}
