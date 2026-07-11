"""Weather derived deterministically from (world seed, tick, season).

Rather than storing a running RNG stream, each tick's weather is a pure
function of `(seed, tick)`, smoothed by blending with the previous tick's
values so weather drifts rather than jumping randomly (see docs/DECISIONS.md,
M1-2). This means weather never needs its own persistence beyond the tick
count already stored on `SimClock` — it's always recomputable.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

# Rough seasonal baselines: (temperature_c, precipitation_chance, wind_avg)
_SEASON_BASELINES: dict[str, tuple[float, float, float]] = {
    "spring": (12.0, 0.40, 0.35),
    "summer": (24.0, 0.20, 0.20),
    "autumn": (10.0, 0.35, 0.40),
    "winter": (-2.0, 0.30, 0.50),
}


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
        elif self.precipitation > 0.6:
            sky = "heavy rain"
        elif self.precipitation > 0.25:
            sky = "light rain"
        elif self.precipitation > 0.08:
            sky = "overcast"
        else:
            sky = "clear"
        return f"{sky}, {self.temperature_c:.1f}\u00b0C, {self.wind_label()} wind"

    def wind_label(self) -> str:
        if self.wind < 0.15:
            return "calm"
        if self.wind < 0.35:
            return "breezy"
        if self.wind < 0.6:
            return "windy"
        return "gale"


def _tick_rng(seed: int, tick: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:weather:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def compute_weather(seed: int, tick: int, season: str, previous: "WeatherState | None") -> WeatherState:
    """Compute this tick's weather. Blends toward the seasonal baseline with
    tick-local jitter, and toward the previous tick's values for smoothness,
    so weather drifts instead of teleporting between extremes."""
    rng = _tick_rng(seed, tick)
    base_temp, base_precip, base_wind = _SEASON_BASELINES[season]

    target_temp = base_temp + rng.uniform(-6.0, 6.0)
    target_precip = max(0.0, min(1.0, base_precip + rng.uniform(-0.25, 0.25)))
    target_wind = max(0.0, min(1.0, base_wind + rng.uniform(-0.25, 0.25)))

    if previous is None:
        temperature_c, precipitation, wind = target_temp, target_precip, target_wind
    else:
        smoothing = 0.7  # weight kept from previous tick
        temperature_c = previous.temperature_c * smoothing + target_temp * (1 - smoothing)
        precipitation = previous.precipitation * smoothing + target_precip * (1 - smoothing)
        wind = previous.wind * smoothing + target_wind * (1 - smoothing)

    is_snowing = precipitation > 0.2 and temperature_c <= 0.0

    return WeatherState(
        temperature_c=temperature_c,
        precipitation=precipitation,
        wind=wind,
        is_snowing=is_snowing,
    )
