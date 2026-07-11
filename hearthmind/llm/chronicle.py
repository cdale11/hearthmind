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
    "recent events, write ONE short paragraph (2-4 sentences) summarizing "
    "what happened this season, in a plain, slightly wry historical tone. "
    'Respond with strict JSON only, no other text: {"summary": "..."}.'
)


def build_prompt(
    recent_events: list[dict], population_summary: dict, season: str, year: int,
    settlement_name: str = "", traditions: list[str] | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened."
    culture = ""
    if settlement_name:
        culture = f"This is the village of {settlement_name}. "
        if traditions:
            culture += f"Its traditions: {'; '.join(traditions)}. "
    return (
        f"{culture}The season just ended: {season}, year {year}. "
        f"Current population: {population_summary['total']} inhabitants "
        f"({population_summary['awake']} awake, {population_summary['resting']} resting). "
        f"Recent events:\n{events_text}\n"
        "Summarize this season."
    )


def fallback_summary(recent_events: list[dict], population_summary: dict, season: str, year: int) -> dict:
    """Deterministic templated stand-in used when the LLM is unavailable —
    counts-based rather than prose, but still a real, useful record."""
    births = sum(1 for event in recent_events if event["category"] == "birth")
    deaths = sum(1 for event in recent_events if event["category"] == "death")
    return {
        "summary": (
            f"{season.capitalize()} of year {year} ended with "
            f"{population_summary['total']} inhabitants remaining "
            f"({births} born, {deaths} died this season)."
        )
    }


def parse_summary(result: dict, fallback: dict) -> str:
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return fallback["summary"]
    return summary.strip()[:1000]
