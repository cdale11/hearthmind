"""Real UK (London-latitude) sunrise/sunset by month, and the resulting
day/night factor — mirrors the client's `UK_DAYLIGHT_HOURS`/`nightFactor`
in interface/static/app.js (kept in sync by hand; there's no shared
runtime between Python and JS here) so the server-side behavioral effect
and the client-side lighting tint agree on when "night" is. Previously
daylight only drove the map's visual darkening; this is the mechanical
half — see docs/DECISIONS.md, "daylight affects agent behavior."
"""
from __future__ import annotations

UK_DAYLIGHT_HOURS: dict[str, tuple[float, float]] = {
    "January": (8.08, 16.00), "February": (7.67, 17.00), "March": (6.50, 18.17),
    "April": (6.50, 20.00), "May": (5.33, 20.83), "June": (4.75, 21.33),
    "July": (5.00, 21.25), "August": (5.75, 20.50), "September": (6.58, 19.33),
    "October": (7.42, 18.17), "November": (7.25, 16.25), "December": (8.00, 15.92),
}

DAWN_DUSK_TRANSITION_HOURS = 1.0
"""Hours either side of sunrise/sunset over which night_factor ramps
linearly rather than flipping instantly — same value as the client."""


def night_factor(hour_of_day: float, month_name: str) -> float:
    """0.0 (full daylight) .. 1.0 (full night), ramping linearly through
    a 1-hour dawn/dusk transition window either side of sunrise/sunset."""
    sunrise, sunset = UK_DAYLIGHT_HOURS.get(month_name, (6.0, 18.0))
    if hour_of_day <= sunrise - DAWN_DUSK_TRANSITION_HOURS or hour_of_day >= sunset + DAWN_DUSK_TRANSITION_HOURS:
        return 1.0
    if sunrise <= hour_of_day <= sunset:
        return 0.0
    if hour_of_day < sunrise:
        return (sunrise - hour_of_day) / DAWN_DUSK_TRANSITION_HOURS
    return (hour_of_day - sunset) / DAWN_DUSK_TRANSITION_HOURS
