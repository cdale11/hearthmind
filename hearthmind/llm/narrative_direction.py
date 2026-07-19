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
    "given; don't invent drama that isn't there. Separately — and only when "
    "one event has genuinely dominated this stretch enough that villagers "
    "would actually have started calling it something ('the white month' "
    "for a brutal winter, 'the long hunger') — coin ONE short local term "
    "for it and say briefly what it means; most of the time nothing has "
    "been dominant enough for this, and that is the correct answer. "
    'Respond with strict JSON only, no other text: {"themes": ["one or two '
    'short theme words or phrases"], "coined_term": "a short local term, or '
    'empty if nothing dominant enough happened", "coined_meaning": "what it '
    'refers to, under 15 words, or empty"}.'
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], folklore: list[dict],
    mood: dict, previous_themes: list[dict], lexicon: list[dict] | None = None,
) -> str:
    events_text = "\n".join(f"- {e['description']}" for e in recent_events) or "A quiet stretch."
    folklore_text = "; ".join(f["tale"] for f in folklore[-3:]) or "None told."
    mood_text = ", ".join(f"{k} {v:+.2f}" for k, v in mood.items()) or "unremarkable"
    prev_text = ", ".join(previous_themes[-1]["themes"]) if previous_themes else "none yet"
    lexicon_text = (
        "; ".join(f"\"{e['term']}\" ({e['meaning']})" for e in (lexicon or [])) or "none coined yet"
    )
    return (
        f"The village of {settlement_name}. What's happened lately:\n{events_text}\n"
        f"Its tales: {folklore_text}\n"
        f"Its current mood: {mood_text}\n"
        f"The last theme noticed: {prev_text}\n"
        f"Local terms it already uses: {lexicon_text}\n"
        "What theme (or two) runs through this stretch of its life right now? "
        "Has anything happened that's dominant enough to deserve its own local term?"
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


def parse_coined_term(result: dict) -> tuple[str, str] | None:
    """§2 "dialect drift": returns `(term, meaning)` or None most calls
    — a genuine, expected outcome; this rides narrative_direction's
    existing quarterly call for zero added LLM volume, so there's no
    fallback to fall back to (a missed call simply coins nothing that
    quarter, same as any other rider field)."""
    term = result.get("coined_term")
    meaning = result.get("coined_meaning")
    if not isinstance(term, str) or not term.strip():
        return None
    if not isinstance(meaning, str) or not meaning.strip():
        return None
    return term.strip()[:30], meaning.strip()[:100]
