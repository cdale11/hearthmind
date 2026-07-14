"""Weather derived deterministically from (world seed, tick, month).

Rather than storing a running RNG stream, each tick's weather is a pure
function of `(seed, tick)`, smoothed by blending with the previous tick's
values so weather drifts rather than jumping randomly (see docs/DECISIONS.md,
M1-2). This means weather never needs its own persistence beyond the tick
count already stored on `SimClock` — it's always recomputable.

Baselines model a temperate UK-style maritime climate (roughly Met Office
30-year averages: mild, wet winters, cool damp summers, rain spread fairly
evenly across the year with a wetter autumn/winter and windier winter) at
monthly granularity rather than 4 broad seasonal buckets, since the real
365-day calendar (see time_system.py) makes that resolution meaningful.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from hearthmind.util import clamp

# UK-climate-style monthly baselines: (temperature_c, precipitation_chance, wind_avg).
_MONTH_BASELINES: dict[str, tuple[float, float, float]] = {
    "january": (5.0, 0.48, 0.48),
    "february": (5.0, 0.42, 0.46),
    "march": (7.0, 0.38, 0.42),
    "april": (9.0, 0.35, 0.38),
    "may": (12.0, 0.32, 0.32),
    "june": (15.0, 0.30, 0.28),
    "july": (17.0, 0.30, 0.25),
    "august": (17.0, 0.32, 0.27),
    "september": (14.0, 0.35, 0.32),
    "october": (11.0, 0.42, 0.40),
    "november": (7.0, 0.46, 0.45),
    "december": (5.0, 0.48, 0.48),
}


CLEAR_PRECIPITATION_THRESHOLD = 0.27
OVERCAST_PRECIPITATION_THRESHOLD = 0.38
HEAVY_RAIN_PRECIPITATION_THRESHOLD = 0.50
"""`describe()`'s sky-band cutoffs, retuned against measured realized
output (v0.43.0) — the same class of bug already diagnosed for
`SNOW_TEMPERATURE_THRESHOLD_C` below: the old cutoffs (clear <=0.08,
overcast <=0.25, heavy >0.6) were chosen against the raw per-tick
`uniform(-0.25, 0.25)` jitter, but `compute_weather`'s smoothing=0.7 EMA
damps that into a much narrower realized band. A 200k-tick measurement
across all twelve months found realized precipitation essentially never
below ~0.11 or above ~0.67, with a p10/p50/p90 of 0.27/0.38/0.50 — so
"clear" was live code that could never fire (0th percentile), and "heavy
rain" only reachable in the tail of winter months, meaning a live run
saw rain almost every tick regardless of season (a user-reported
"I only see rain" symptom, confirmed by measurement, not "just weather
variance"). Retuned to the actual measured percentiles so each band
gets a real, roughly-even share of ticks instead of one dominating."""

CALM_WIND_THRESHOLD = 0.24
BREEZY_WIND_THRESHOLD = 0.38
WINDY_WIND_THRESHOLD = 0.51
"""`wind_label()`'s bands, retuned against measured realized output —
the same "threshold the model can actually reach" bug already fixed for
precipitation/temperature above, this time for wind. The old cutoffs
(calm <0.15, breezy <0.35, windy <0.6) were plausible-looking against
the raw uniform(-0.25, 0.25) jitter, but a 17,520-tick measurement
across all twelve months found realized wind essentially confined to
0.08-0.66 with p10/p50/p90 of 0.24/0.38/0.51 — "calm" fired on <1% of
ticks and the label read as "always windy" (live user report). Retuned
to the measured percentiles so each band gets a roughly even share."""

SNOW_PRECIPITATION_THRESHOLD = 0.2
SNOW_TEMPERATURE_THRESHOLD_C = 2.0
"""Real UK snow overwhelmingly falls in the 0-2C band, not exactly at or
below freezing — precipitation phase depends on the whole air column,
not just screen-height temperature. Previously gated at exactly <= 0.0C,
which combined with `compute_weather`'s smoothing (see `smoothing=0.7`
below — an EMA that damps single-tick jitter into a much narrower
realized range than the raw uniform(-6, 6) draw) meant winter
temperature essentially never actually reached 0 or below in practice
(verified: 0 snow ticks across a simulated December at the default
seed) — `is_snowing` was live code that could never fire. Raising the
threshold to 2.0C is the fix, not a cosmetic tweak: it's within the
smoothed range winter baselines actually reach, and still matches real
UK meteorology."""


@dataclass
class WeatherState:
    temperature_c: float
    precipitation: float  # 0.0 (clear) .. 1.0 (torrential)
    wind: float  # 0.0 (still) .. 1.0 (gale)
    is_snowing: bool

    def to_dict(self) -> dict:
        return {
            "temperature_c": round(self.temperature_c, 2),
            "precipitation": round(self.precipitation, 3),
            "wind": round(self.wind, 3),
            "is_snowing": self.is_snowing,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WeatherState":
        return cls(
            temperature_c=data["temperature_c"],
            precipitation=data["precipitation"],
            wind=data["wind"],
            is_snowing=data["is_snowing"],
        )

    def describe(self) -> str:
        if self.is_snowing:
            sky = "snowing"
        elif self.precipitation > HEAVY_RAIN_PRECIPITATION_THRESHOLD:
            sky = "heavy rain"
        elif self.precipitation > OVERCAST_PRECIPITATION_THRESHOLD:
            sky = "light rain"
        elif self.precipitation > CLEAR_PRECIPITATION_THRESHOLD:
            sky = "overcast"
        else:
            sky = "clear"
        return f"{sky}, {self.temperature_c:.1f}\u00b0C, {self.wind_label()} wind"

    def wind_label(self) -> str:
        if self.wind < CALM_WIND_THRESHOLD:
            return "calm"
        if self.wind < BREEZY_WIND_THRESHOLD:
            return "breezy"
        if self.wind < WINDY_WIND_THRESHOLD:
            return "windy"
        return "gale"


def _tick_rng(seed: int, tick: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:weather:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def compute_weather(seed: int, tick: int, month: str, previous: "WeatherState | None") -> WeatherState:
    """Compute this tick's weather. Blends toward the current month's UK-
    climate baseline with tick-local jitter, and toward the previous tick's
    values for smoothness, so weather drifts instead of teleporting between
    extremes. `month` is a lowercase month name (see SimClock.month_name)."""
    rng = _tick_rng(seed, tick)
    base_temp, base_precip, base_wind = _MONTH_BASELINES[month]

    target_temp = base_temp + rng.uniform(-6.0, 6.0)
    target_precip = clamp(base_precip + rng.uniform(-0.25, 0.25), 0.0, 1.0)
    target_wind = clamp(base_wind + rng.uniform(-0.25, 0.25), 0.0, 1.0)

    if previous is None:
        temperature_c, precipitation, wind = target_temp, target_precip, target_wind
    else:
        smoothing = 0.7  # weight kept from previous tick
        temperature_c = previous.temperature_c * smoothing + target_temp * (1 - smoothing)
        precipitation = previous.precipitation * smoothing + target_precip * (1 - smoothing)
        wind = previous.wind * smoothing + target_wind * (1 - smoothing)

    is_snowing = precipitation > SNOW_PRECIPITATION_THRESHOLD and temperature_c <= SNOW_TEMPERATURE_THRESHOLD_C

    return WeatherState(
        temperature_c=temperature_c,
        precipitation=precipitation,
        wind=wind,
        is_snowing=is_snowing,
    )
