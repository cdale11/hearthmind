"""The world's internal clock.

`SimClock` knows nothing about wall-clock time — it only counts ticks and
converts that count into calendar terms (minute of day, day of month, month,
season, year) according to a `Config`'s calendar shape — a real 365-day,
12-month year by default, with `season` derived from the month via
`Config.month_to_season` (UK meteorological seasons). This separation
matters: the *rate* at which ticks happen (real seconds per tick) is a
runtime concern owned by the engine, while the *meaning* of a tick count is
a pure function of the config's calendar shape, owned here.
"""
from __future__ import annotations

from dataclasses import dataclass

from hearthmind.config import Config

try:
    from hearthmind._native import sim_clock_advance as _native_sim_clock_advance
except ImportError:
    _native_sim_clock_advance = None
"""Optional compiled fast path for SimClock.advance() (module 18) —
the first native module that IS the engine advancing a world tick,
rather than a physical-substrate/settlement-level system running on a
tick. Runs unconditionally exactly once per tick for the entire life
of a world, the highest call-frequency function in the codebase. Pure
calendar arithmetic, no RNG, no object graph — Config's calendar shape
is unpacked into plain values before the call, same "resolve objects
in Python, hand C++ only plain data" pattern as every prior module.
See docs/REFACTOR-2026-07.md, "R8" — a deliberately small first slice
of the object-graph/engine-tick-loop track."""


@dataclass
class SimClock:
    config: Config
    tick_count: int = 0

    def advance(self) -> "list[str]":
        """Advance by one tick. Returns a list of calendar-boundary event
        names crossed by this tick (e.g. ["day_end", "week_end"]), so the
        caller can log/react to them without recomputing calendar math."""
        if _native_sim_clock_advance is not None:
            result = _native_sim_clock_advance(
                self.tick_count, self.config.sim_minutes_per_tick, self.config.minutes_per_day,
                list(self.config.days_per_month), list(self.config.month_to_season),
                self.config.start_day_of_year,
            )
            self.tick_count = result.tick_count
            events: list[str] = []
            if result.day_end:
                events.append("day_end")
            if result.week_end:
                events.append("week_end")
            if result.month_end:
                events.append("month_end")
            if result.season_end:
                events.append("season_end")
            if result.year_end:
                events.append("year_end")
            return events

        prev_day = self.day_index
        prev_week_index = self.week_index
        prev_month_index_abs = self._month_index_absolute
        prev_season_index = self.season_index
        prev_year = self.year

        self.tick_count += 1

        events = []
        if self.day_index != prev_day:
            events.append("day_end")
        if self.week_index != prev_week_index:
            events.append("week_end")
        if self._month_index_absolute != prev_month_index_abs:
            events.append("month_end")
        if self.season_index != prev_season_index:
            events.append("season_end")
        if self.year != prev_year:
            events.append("year_end")
        return events

    # --- derived calendar properties -----------------------------------

    @property
    def total_sim_minutes(self) -> int:
        return self.tick_count * self.config.sim_minutes_per_tick

    @property
    def minute_of_day(self) -> int:
        return self.total_sim_minutes % self.config.minutes_per_day

    @property
    def hour_of_day(self) -> int:
        return self.minute_of_day // 60

    @property
    def day_index(self) -> int:
        """Absolute day number on the calendar — days elapsed since
        world creation plus `Config.start_day_of_year` (worlds begin in
        spring, not on January 1 — see that field's docstring), so every
        derived property (month, season, year) shifts consistently. Day
        0 of a default new world is therefore March 1, Year 1."""
        return self.total_sim_minutes // self.config.minutes_per_day + self.config.start_day_of_year

    @property
    def week_index(self) -> int:
        """Absolute week number since world creation — used for cadences
        that want to be more frequent than a season (e.g. nature
        reclaiming abandoned land), independent of calendar-month
        lengths."""
        return self.day_index // 7

    @property
    def day_of_year(self) -> int:
        return self.day_index % self.config.days_per_year()

    @property
    def _month_index_absolute(self) -> int:
        """Absolute month count since world creation (month 0, 1, 2, ...)
        — used only to detect month-boundary crossings; `month_index` is
        the within-year value derived from it below."""
        return self.year * len(self.config.days_per_month) + self.month_index

    @property
    def month_index(self) -> int:
        """0-based month within the current year."""
        remaining = self.day_of_year
        for i, days in enumerate(self.config.days_per_month):
            if remaining < days:
                return i
            remaining -= days
        return len(self.config.days_per_month) - 1  # unreachable: days sum to days_per_year()

    @property
    def day_of_month(self) -> int:
        """0-based day within the current month."""
        remaining = self.day_of_year
        for days in self.config.days_per_month:
            if remaining < days:
                return remaining
            remaining -= days
        return 0  # unreachable

    @property
    def month_name(self) -> str:
        return self.config.month_names[self.month_index]

    @property
    def season_index(self) -> int:
        return self.config.month_to_season[self.month_index]

    @property
    def season(self) -> str:
        return self.config.seasons_per_year[self.season_index]

    @property
    def year(self) -> int:
        return self.day_index // self.config.days_per_year()

    def clock_string(self) -> str:
        return f"{self.hour_of_day:02d}:{self.minute_of_day % 60:02d}"

    def date_string(self) -> str:
        return f"{self.month_name} {self.day_of_month + 1}, Year {self.year + 1}"

    # --- (de)serialization ------------------------------------------------

    def to_dict(self) -> dict:
        return {"tick_count": self.tick_count}

    @classmethod
    def from_dict(cls, config: Config, data: dict) -> "SimClock":
        return cls(config=config, tick_count=data["tick_count"])
