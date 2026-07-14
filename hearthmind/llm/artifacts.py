"""Written artifacts: the letter/record a notable villager leaves behind
at death (v0.64.0 audit-backlog item — "agents leave letters/records
that outlive them").

The *existence* of a record is objective and decided synchronously at
death (`Population._apply_deaths` -> `last_written_records`, gated on
RECORD_MIN_MEMORIES); only its *text* is interpretive, so it's authored
here by the LLM (or the deterministic fallback, which assembles from the
same memories). The finished record lands in `Settlement.records`
(capped at RECORDS_MAX_STORED) where it outlives its author: it feeds
the yearly documentary prompt, and the first grieving relative keeps a
memory of the letter itself — the "memory beyond the 8-entry cap"
mechanism the roadmap asked for.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are writing the short letter or record a villager in a small "
    "simulated world left behind at their death — their own words, first "
    "person, grounded ONLY in the specific memories and belief given. "
    "Plain, human, a little unfinished, never grand or supernatural. "
    'Respond with strict JSON only, no other text: {"text": "the record, '
    'one to two sentences, under 40 words, first person"}.'
)


def build_prompt(author: str, memories: list[str], belief: str) -> str:
    memories_text = " | ".join(memories) if memories else "A quiet life."
    belief_text = f"\nA belief they privately held: {belief}" if belief else ""
    return (
        f"{author} has died. What they remembered of their life: {memories_text}{belief_text}\n"
        "Write the short record they left behind."
    )


def fallback_record(author: str, memories: list[str], seed_hint: int = 0) -> dict:
    """Deterministic stand-in assembled from the same memories the LLM
    would see — a real record, not filler."""
    if memories:
        kept = memories[seed_hint % len(memories)]
        text = f"If anyone reads this after me: {kept}"
    else:
        text = "Little to set down. The days were quiet, and that was enough."
    return {"text": text}


def parse_record(result: dict, fallback: dict) -> str:
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        text = fallback["text"]
    return text.strip()[:240]
