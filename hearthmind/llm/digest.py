""""While you were away" digest (§5 "Making deep time legible",
docs/IDEAS-2026-07-EMERGENCE.md): an on-demand LLM job answering "what
happened since I last looked," written as the chronicler-style summary
llm/summary.py already establishes, but scoped to events SINCE a given
tick rather than a fixed recent-window, and headlined by anything
touching agents the observer has actually inspected (`World.
observer_attention`). Same on-demand shape as summary/chronicler: no
cadence gate, costs nothing unless actually requested.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are an observer writing a short 'while you were away' recap for "
    "someone returning to check on a small simulated village after a gap. "
    "Given the events that happened since they last looked, and which "
    "people (if any) they especially care about, write ONE short recap "
    "(3-6 sentences) headlined by whatever involves those people, then "
    "covering the rest of what's notable. If nothing much happened, say so "
    "plainly. Do not invent details not implied by the given data. "
    'Respond with strict JSON only, no other text: {"digest": "..."}.'
)


def build_prompt(
    settlement_name: str, since_tick: int, current_tick: int,
    events: list[dict], watched_names: list[str],
) -> str:
    lines = [f"- {event['description']}" for event in events]
    events_text = "\n".join(lines) if lines else "Nothing much happened."
    span = max(0, current_tick - since_tick)
    watched_text = (
        f"The observer especially cares about: {', '.join(watched_names)}.\n"
        if watched_names else ""
    )
    return (
        f"The village of {settlement_name or 'an unnamed settlement'}. "
        f"The observer has been away for {span} ticks.\n"
        f"{watched_text}"
        f"What happened while they were gone:\n{events_text}\n"
        "Write the 'while you were away' recap."
    )


def fallback_digest(events: list[dict], watched_names: list[str]) -> dict:
    """Deterministic templated stand-in — same shape as summary.
    fallback_summary. Headlines the newest event mentioning a watched
    name if one exists, otherwise just the newest event."""
    if not events:
        return {"digest": "Nothing much happened while you were away."}
    headline = None
    if watched_names:
        for event in events:  # newest-first
            if any(name and name in event["description"] for name in watched_names):
                headline = event["description"]
                break
    if headline is None:
        headline = events[0]["description"]
    rest = len(events) - 1
    tail = f" ({rest} other thing{'s' if rest != 1 else ''} happened too.)" if rest > 0 else ""
    return {"digest": f"While you were away: {headline}{tail}"}


def parse_digest(result: dict, fallback: dict) -> str:
    text = result.get("digest")
    if not isinstance(text, str) or not text.strip():
        return fallback["digest"]
    return text.strip()[:1200]
