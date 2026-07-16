"""The world chronicle: periodic LLM summarization of recent events into
persistent history.

Triggered on `season_end`. Deliberately reuses the existing `events` table
(category="chronicle") rather than introducing a new one — the table
already stores arbitrary tick/category/description rows, and a chronicle
entry is just a longer description with a distinct category. See
docs/DECISIONS.md, B3.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the chronicler of a small simulated world. Given a list of "
    "recent events, write ONE short paragraph (2-4 sentences) about this "
    "season, in a plain, slightly wry historical tone. Interpret, don't "
    "just summarize: a good chronicler reaches for meaning in what "
    "happened — 'the winter the forest seemed to close in again', not a "
    "flat list of who did what. If the village's own folklore offers a "
    "lens that fits, let it color the telling; if not, find your own. "
    'Respond with strict JSON only, no other text: {"summary": "..."}.'
)


def build_prompt(
    recent_events: list[dict], population_summary: dict, season: str, year: int,
    settlement_name: str = "", traditions: list[str] | None = None, beliefs: list[dict] | None = None,
    place_names: dict | None = None, folklore: list[dict] | None = None, narrative_theme: str = "",
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened."
    culture = ""
    if settlement_name:
        culture = f"This is the village of {settlement_name}. "
        if traditions:
            culture += f"Its traditions: {'; '.join(traditions)}. "
        if beliefs:
            culture += (
                "Its own accumulated theories about itself: "
                + "; ".join(f"{b['subject']} ({b['belief']})" for b in beliefs) + ". "
            )
        if place_names:
            # Named geography (v0.64.0): the chronicle refers to the
            # village's own named waters, not "the river" in the abstract.
            culture += f"Its named places: {'; '.join(place_names.values())}. "
        if folklore:
            # Phase K "Historian v2": the tales the village already
            # tells itself are available as an interpretive lens, not
            # required content — the system prompt above only invites
            # using them "if it fits."
            culture += f"Tales the village tells: {'; '.join(f['tale'] for f in folklore[-3:])}. "
        if narrative_theme:
            # Phase M "Narrative Direction": ambient interpretive lens,
            # same "if it fits" treatment as folklore above.
            culture += f"The recent theme of its life has been {narrative_theme}. "
    return (
        f"{culture}The season just ended: {season}, year {year}. "
        f"Current population: {population_summary['total']} inhabitants "
        f"({population_summary['awake']} awake, {population_summary['resting']} resting). "
        f"Recent events:\n{events_text}\n"
        "Summarize this season."
    )


_FALLBACK_TEMPLATES = (
    "{season} of year {year} ended with {total} inhabitants remaining ({births} born, {deaths} died this season).",
    "As {season}, year {year}, drew to a close, the village counted {total} souls — {births} born, {deaths} lost.",
    "The books were closed on {season}, year {year}: {total} inhabitants, {births} new arrivals, {deaths} deaths.",
)
""""Continue expanding, round three" (docs/DECISIONS.md): chronicle's
own fallback is arguably the most frequently-fired narrative fallback
in the whole project (it stands in for the season-end summary on any
world running without live Ollama), yet was still a single hardcoded
line with zero variation — every other narrative fallback (dialogue,
culture, festival, invention, omens, disaster narration, world_genesis)
already cycles a small pool by this point. Same shape as disasters.py's
`_pick_template`: a small, fixed pool selected by seed, no LLM call
added — the counts-based content stays identical, only the phrasing
varies."""


def fallback_summary(
    recent_events: list[dict], population_summary: dict, season: str, year: int, seed_hint: int = 0,
) -> dict:
    """Deterministic templated stand-in used when the LLM is unavailable —
    counts-based rather than prose, but still a real, useful record."""
    import random
    births = sum(1 for event in recent_events if event["category"] == "birth")
    deaths = sum(1 for event in recent_events if event["category"] == "death")
    template = random.Random(seed_hint).choice(_FALLBACK_TEMPLATES)
    return {
        "summary": template.format(
            season=season.capitalize(), year=year, total=population_summary["total"], births=births, deaths=deaths,
        )
    }


def parse_summary(result: dict, fallback: dict) -> str:
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return fallback["summary"]
    return summary.strip()[:1000]
