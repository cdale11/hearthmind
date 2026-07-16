"""Narrative Direction (Phase M, docs/VISION-2026-07.md, "Faith &
Meaning"): quarterly (season_end-gated — a season already IS a quarter
of the real 365-day calendar, no new cadence needed), settlement-scoped,
one call. Reads the chronicle/folklore/mood trajectory and names 1-2
active themes (grief, hope, decay, renewal...). Consumed ONLY as prompt
bias for town_brain/omens/chronicle/Dream() — it never schedules or
scripts an event on its own; it makes whatever those mechanisms already
do thematically coherent instead of arbitrary from call to call.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are noticing the emotional throughline of a small simulated "
    "village's recent history. Given what has happened lately and its "
    "general mood, name the theme or two that actually run through it right "
    "now — not a plot, not a prediction, just what this stretch of the "
    "village's life has been ABOUT (grief, renewal, suspicion, quiet "
    "prosperity, decline, whatever genuinely fits). Stay grounded in what's "
    "given; don't invent drama that isn't there. "
    'Respond with strict JSON only, no other text: {"themes": ["one or two '
    'short theme words or phrases"]}.'
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], folklore: list[dict],
    mood: dict, previous_themes: list[dict],
) -> str:
    events_text = "\n".join(f"- {e['description']}" for e in recent_events) or "A quiet stretch."
    folklore_text = "; ".join(f["tale"] for f in folklore[-3:]) or "None told."
    mood_text = ", ".join(f"{k} {v:+.2f}" for k, v in mood.items()) or "unremarkable"
    prev_text = ", ".join(previous_themes[-1]["themes"]) if previous_themes else "none yet"
    return (
        f"The village of {settlement_name}. What's happened lately:\n{events_text}\n"
        f"Its tales: {folklore_text}\n"
        f"Its current mood: {mood_text}\n"
        f"The last theme noticed: {prev_text}\n"
        "What theme (or two) runs through this stretch of its life right now?"
    )


def fallback_direction(mood: dict) -> dict:
    """Deterministic stand-in: reads the single strongest mood axis
    rather than inventing a theme from nothing — a real signal already
    on the settlement, just not model-interpreted."""
    label_by_axis = {
        "hope": "quiet hope", "fear": "unease", "grief": "mourning", "suspicion": "wariness",
    }
    if not mood:
        return {"themes": ["an ordinary season"]}
    strongest = max(mood, key=lambda k: abs(mood.get(k, 0.0)))
    if abs(mood.get(strongest, 0.0)) < 0.15:
        return {"themes": ["an ordinary season"]}
    return {"themes": [label_by_axis.get(strongest, strongest)]}


def parse_direction(result: dict, fallback: dict) -> list[str]:
    themes = result.get("themes")
    if not isinstance(themes, list):
        themes = fallback["themes"]
    clean = [t.strip()[:40] for t in themes if isinstance(t, str) and t.strip()][:2]
    return clean or fallback["themes"]
