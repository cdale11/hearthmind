"""The world's internal clock.

`SimClock` knows nothing about wall-clock time — it only counts ticks and
converts that count into calendar terms (minute of day, day of season,
season, year) according to a `Config`'s calendar shape. This separation
matters: the *rate* at which ticks happen (real seconds per tick) is a
runtime concern owned by the engine, while the *meaning* of a tick count is
a pure function of the config's calendar shape, owned here.
"""
from __future__ import annotations

from dataclasses import dataclass

from hearthmind.config import Config


@dataclass
class SimClock:
    config: Config
    tick_count: int = 0

    def advance(self) -> "list[str]":
        """Advance by one tick. Returns a list of calendar-boundary event
        names crossed by this tick (e.g. ["day_end", "season_end"]), so the
        caller can log/react to them without recomputing calendar math."""
        prev_day = self.day_index
        prev_season_index = self.season_index
        prev_year = self.year

        self.tick_count += 1

        events: list[str] = []
        if self.day_index != prev_day:
            events.append("day_end")
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
        """Absolute day number since world creation (day 0, 1, 2, ...)."""
        return self.total_sim_minutes // self.config.minutes_per_day

    @property
    def day_of_season(self) -> int:
        return self.day_index % self.config.days_per_season

    @property
    def season_index(self) -> int:
        days_per_year = self.config.days_per_year()
        day_in_year = self.day_index % days_per_year
        return day_in_year // self.config.days_per_season

    @property
    def season(self) -> str:
        return self.config.seasons_per_year[self.season_index]

    @property
    def year(self) -> int:
        return self.day_index // self.config.days_per_year()

    def clock_string(self) -> str:
        return f"{self.hour_of_day:02d}:{self.minute_of_day % 60:02d}"

    def date_string(self) -> str:
        return (
            f"Year {self.year}, {self.season.capitalize()} "
            f"day {self.day_of_season + 1}/{self.config.days_per_season}"
        )

    # --- (de)serialization ------------------------------------------------

    def to_dict(self) -> dict:
        return {"tick_count": self.tick_count}

    @classmethod
    def from_dict(cls, config: Config, data: dict) -> "SimClock":
        return cls(config=config, tick_count=data["tick_count"])
