"""Narrative Direction (Phase M, docs/VISION-2026-07.md, "Faith &
Meaning"): quarterly (season_end-gated — a season already IS a quarter
of the real 365-day calendar, no new cadence needed), settlement-scoped,
one call. Names 1-2 active themes (grief, hope, decay, renewal...) and
folds them into `_narrative_theme_bias` as prompt bias for town_brain/
omens/chronicle/Dream() — it never schedules or scripts an event on its
own; it makes whatever those mechanisms already do thematically
coherent instead of arbitrary from call to call.

Made deterministic (explicit user directive): "I don't think an LLM
should decide Theme: Grief, Renewal. That can emerge statistically from
events. The LLM can write a summary." `compute_themes` reads
`Settlement.mood`'s own real axes (hope/fear/grief/suspicion, each
already a statistical aggregate of lived events — Phase I) and picks
the strongest one past a real threshold — the same signal the old
`fallback_direction` already used as its non-LLM path, now promoted to
THE decision. The LLM's remaining job is a one-sentence summary
explaining the computed theme, plus its one genuinely creative-
authorship side task (coining a local term for a dominant event, kept
as-is — naming an unprecedented thing, not choosing among a closed set
of moods)."""
from __future__ import annotations

_MOOD_THEME_THRESHOLD = 0.15
"""Same magnitude as the prior `fallback_direction`'s threshold —
below this, no mood axis reads as a genuine active theme."""

_LABEL_BY_AXIS = {"hope": "quiet hope", "fear": "unease", "grief": "mourning", "suspicion": "wariness"}

SYSTEM_PROMPT = (
    "You are summarizing the emotional throughline of a small simulated "
    "village's recent history. You have been told the theme that has ALREADY "
    "been computed for this stretch of its life, from its own real mood — "
    "your only job is to write one short sentence grounded in what's given, "
    "never to name a different theme. Separately — and only when one event "
    "has genuinely dominated this stretch enough that villagers would "
    "actually have started calling it something ('the white month' for a "
    "brutal winter, 'the long hunger') — coin ONE short local term for it "
    "and say briefly what it means; most of the time nothing has been "
    "dominant enough for this, and that is the correct answer. "
    'Respond with strict JSON only, no other text: {"summary": "one short '
    'sentence, under 20 words, grounded in the given theme", "coined_term": '
    '"a short local term, or empty if nothing dominant enough happened", '
    '"coined_meaning": "what it refers to, under 15 words, or empty"}.'
)


def compute_themes(mood: dict) -> list[str]:
    """THE decision — not a fallback. Reads the settlement's own real,
    already-tracked mood axes; a theme only counts once its axis clears
    `_MOOD_THEME_THRESHOLD`, so most quarters correctly read as "an
    ordinary season" rather than manufacturing drama from noise."""
    if not mood:
        return ["an ordinary season"]
    strongest = max(mood, key=lambda k: abs(mood.get(k, 0.0)))
    if abs(mood.get(strongest, 0.0)) < _MOOD_THEME_THRESHOLD:
        return ["an ordinary season"]
    return [_LABEL_BY_AXIS.get(strongest, strongest)]


def build_prompt(
    settlement_name: str, themes: list[str], recent_events: list[dict], folklore: list[dict],
    mood: dict, lexicon: list[dict] | None = None, emergence_observations: list[str] | None = None,
) -> str:
    """`emergence_observations` (B1-B3, docs/MASTERCHECKLIST-2026-07-
    22.md, roadmap Stage II — same shape as `nature_mind.build_prompt`'s
    param of the same name): curated Emergence API summaries gathered
    during the Humans pillar's prior `observe` turn. Optional and
    additive; unset reads exactly as before this parameter existed."""
    events_text = "\n".join(f"- {e['description']}" for e in recent_events) or "A quiet stretch."
    folklore_text = "; ".join(f["tale"] for f in folklore[-3:]) or "None told."
    mood_text = ", ".join(f"{k} {v:+.2f}" for k, v in mood.items()) or "unremarkable"
    lexicon_text = (
        "; ".join(f"\"{e['term']}\" ({e['meaning']})" for e in (lexicon or [])) or "none coined yet"
    )
    observations_text = (
        "\n".join(f"- {o}" for o in emergence_observations) if emergence_observations else ""
    )
    observations_block = (
        f"What you noticed since last time:\n{observations_text}\n" if observations_text else ""
    )
    return (
        f"The village of {settlement_name}. What's happened lately:\n{events_text}\n"
        f"{observations_block}"
        f"Its tales: {folklore_text}\n"
        f"Its current mood: {mood_text}\n"
        f"The theme already computed for this stretch of its life: {', '.join(themes)}.\n"
        f"Local terms it already uses: {lexicon_text}\n"
        "Write one sentence grounded in the computed theme. "
        "Has anything happened that's dominant enough to deserve its own local term?"
    )


def fallback_summary() -> dict:
    return {"summary": ""}


def parse_summary(result: dict, fallback: dict) -> str:
    summary = result.get("summary")
    if not isinstance(summary, str):
        summary = fallback["summary"]
    return summary.strip()[:160]


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


def validate_coined_term(term: str, existing_lexicon: list[dict]) -> bool:
    """C2 "The intention channel" (docs/MASTERCHECKLIST-2026-07-22.md,
    Part C — "every pillar acts only by emitting intentions the Body
    validates and executes"): a dialect-drift coinage is a real
    persistent-state-creating intention (a new `Settlement.lexicon`
    entry) the Body must check before executing, the same "never trust
    the LLM's own claim unconditionally" discipline `ontology.validate_
    hook` already enforces for Innovation's concept proposals — this
    call site previously had no such check at all beyond `parse_coined_
    term`'s own non-blank validation. Rejects an exact case-insensitive
    duplicate of an already-coined term (the one concrete failure mode
    this join site could actually produce — the model re-coining "the
    white month" a second time, redundant with an existing entry);
    returns True (the intention is valid, safe to execute) otherwise."""
    term_lower = term.strip().lower()
    return not any(entry.get("term", "").strip().lower() == term_lower for entry in existing_lexicon)
