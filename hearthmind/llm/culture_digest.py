"""Quarterly LLM job: condenses the settlement's accumulated culture
(traditions, inventions, festivals, notable records) into one short
digest sentence — the "intelligent summary instead of blind slicing"
companion to `llm.beliefs.parse_digest`, for the culture-history lists
that (unlike beliefs) have no natural "revise the whole list" call to
piggyback a digest onto for free. This is genuinely new call volume —
one per season, the cheapest real cadence available (a season already
IS a real-calendar quarter, no new cadence machinery needed, same
reasoning `llm/narrative_direction.py` already uses) — traded directly
against `chronicle`/`town_brain` needing an ever-larger raw slice of
these lists as a world's history accumulates. Distinct from Narrative
Direction: that job names the *theme* of recent life (grief, renewal,
unease); this job summarizes the settlement's accumulated *culture and
history itself* (what it has built, kept, and left behind).
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the settled memory a small simulated village has of its own culture and "
    "history — its traditions, its inventions, its festivals, and what its notable dead "
    "left behind in writing. Given everything the village has accumulated so far, "
    "condense it into one short sentence capturing the overall shape and character of "
    "its history and way of life — not a list, a gist, the way you'd sum up a place's "
    "character in one line to someone who had never been there. "
    'Respond with strict JSON only, no other text: {"digest": "one sentence, under 25 '
    'words"}.'
)


def build_prompt(
    settlement_name: str, traditions: list[str], inventions: list[str],
    festivals: list[str], records: list[dict],
) -> str:
    traditions_text = "; ".join(traditions) if traditions else "None yet."
    inventions_text = "; ".join(inventions) if inventions else "None yet."
    festivals_text = "; ".join(festivals) if festivals else "None yet."
    records_text = (
        "; ".join(f'{r["author"]}: "{r["text"]}"' for r in records) if records else "None yet."
    )
    return (
        f"The village of {settlement_name}.\n"
        f"Traditions kept: {traditions_text}\n"
        f"Inventions made: {inventions_text}\n"
        f"Festivals held: {festivals_text}\n"
        f"Words the dead left behind: {records_text}\n"
        "Condense this into one sentence capturing the village's overall character."
    )


def fallback_digest() -> dict:
    """Genuine no-op, same shape as `llm.beliefs.fallback_belief`'s
    digest field and `llm.consciousness.fallback_consciousness` — "no
    call -> no update this quarter," never a fabricated summary. The
    engine only overwrites `Settlement.culture_digest` when `used_
    fallback` is False."""
    return {"digest": ""}


def parse_digest(result: dict) -> str:
    text = result.get("digest")
    if not isinstance(text, str) or not text.strip():
        return ""
    return text.strip()[:180]
