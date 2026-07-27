"""Folklore condensation (Phase K, docs/VISION-2026-07.md, "Knowledge &
Story"): monthly, settlement-scoped — the village's own recent rumors
gradually settle into a handful of enduring tales, the way real oral
history compresses many retellings into one remembered story. Scoped
down to reuse the existing "rumor" event-log category (see `Settlement.
folklore`/`FOLKLORE_MAX_STORED`) rather than the vision's fuller
per-rumor hops/mutation tracking, which doesn't exist in this codebase
yet — this piece only closes the "condensation" half of Phase K's
rumor->folklore->myth pipeline. Same call-volume shape as tradition/
invention/festival: one bounded settlement job in the existing monthly
rotation, not a new per-agent gate.
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = (
    "You are the keeper of a small simulated village's oral history. Given "
    "rumors that have been circulating and any old tales the village already "
    "tells, condense them into ONE short folk tale — the kind of story that "
    "outlives the people it started with, softened and simplified in the "
    "retelling, not a precise record. It's fine, even expected, for it to "
    "drift from exactly what happened. If the rumors circulating now are "
    "really just the same old story being retold, say there's nothing new "
    "worth telling rather than restating an old tale in slightly different "
    "words — a real oral tradition only mints a NEW legend when it has "
    "genuinely new material to work with. If nothing here is worth "
    "remembering yet, say so honestly rather than inventing something "
    "ungrounded. "
    'Respond with strict JSON only, no other text: {"worth_telling": true '
    'or false, "tale": "one or two sentences, under 35 words, told as a '
    'village legend, third person"}.'
)


def build_prompt(
    settlement_name: str, rumor_events: list[dict], existing_folklore: list[dict],
    legends: list[dict] | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in rumor_events]
    rumors_text = "\n".join(lines) if lines else "No rumors have been circulating lately."
    if existing_folklore:
        tales_text = "; ".join(entry["tale"] for entry in existing_folklore[-5:])
    else:
        tales_text = "None yet."
    legends_line = ""
    if legends:
        # A21 "Temporal compression": a crystallized legend (`world/
        # legends.py`) is a step ABOVE an ordinary folk tale — telling
        # folklore about it too would just re-mint the same story one
        # rung down, the exact "same old story being retold" case the
        # system prompt above already asks the model to decline. Named
        # explicitly so the model can tell the difference between "no
        # new material" and "this is already a full legend, not folk
        # tale material."
        legends_text = "; ".join(e["legend"] for e in legends[-2:])
        legends_line = f"Already a full legend, not just a tale: {legends_text}\n"
    return (
        f"The village of {settlement_name}. Rumors heard lately:\n{rumors_text}\n"
        f"Old tales already told: {tales_text}\n"
        f"{legends_line}"
        "Condense this into one new folk tale, or say there's nothing worth telling yet."
    )


def fallback_folklore(settlement_name: str, rumor_events: list[dict]) -> dict:
    """Deterministic stand-in: only proposes a tale when there's real
    rumor material to draw from (a fallback shouldn't invent folklore
    from nothing) — reads the oldest rumor in the window as the
    "original" the tale grew from, matching the "condensation" framing."""
    if not rumor_events:
        return {"worth_telling": False, "tale": ""}
    seed = rumor_events[-1]["description"]
    return {
        "worth_telling": True,
        "tale": f"They still tell it in {settlement_name}: {seed}",
    }


_TALE_WORD_RE = re.compile(r"[a-z']+")
FOLKLORE_DUPLICATE_OVERLAP = 0.6
"""Live-review-pack finding: a small model shown its own last 5 tales as
"old tales already told" context (see `build_prompt`) tends to just
re-condense the same dominant rumor theme into a near-restatement each
month rather than a genuinely new legend — the same feedback-loop shape
`Settlement.top_topics()` had for dialogue (fixed v0.87.35), just for
folklore's own small context window instead of settlement-wide
weighting. SYSTEM_PROMPT now asks the model to self-recognize this and
say "nothing new" instead; this Jaccard word-overlap check (stdlib
only, same class of heuristic as `review_diagnostics`' keyword overlap)
is the deterministic backstop for when a small model doesn't comply —
a proposed tale sharing >=60% of its distinct words with any of the
last `FOLKLORE_MAX_STORED` tales is treated as "nothing new," not
stored as a duplicate entry."""


def _is_near_duplicate(tale: str, existing_tales: list[str]) -> bool:
    words = set(_TALE_WORD_RE.findall(tale.lower()))
    if not words:
        return False
    for existing in existing_tales:
        existing_words = set(_TALE_WORD_RE.findall(existing.lower()))
        if not existing_words:
            continue
        overlap = len(words & existing_words) / len(words | existing_words)
        if overlap >= FOLKLORE_DUPLICATE_OVERLAP:
            return True
    return False


def parse_folklore(result: dict, fallback: dict, existing_tales: list[str] | None = None) -> dict | None:
    """Returns a `{"tale": str}` entry, or None if nothing was worth
    telling (a genuine, expected outcome — folklore shouldn't form
    every single month just because the job ran). `existing_tales`
    (optional, backward compatible) rejects a near-restatement of an
    already-told tale — see `FOLKLORE_DUPLICATE_OVERLAP`'s docstring."""
    worth_telling = result.get("worth_telling")
    if not isinstance(worth_telling, bool):
        worth_telling = fallback["worth_telling"]
    if not worth_telling:
        return None
    tale = result.get("tale")
    if not isinstance(tale, str) or not tale.strip():
        tale = fallback["tale"]
        if not tale:
            return None
    tale = tale.strip()[:220]
    if existing_tales and _is_near_duplicate(tale, existing_tales):
        return None
    return {"tale": tale}
