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

SYSTEM_PROMPT = (
    "You are the keeper of a small simulated village's oral history. Given "
    "rumors that have been circulating and any old tales the village already "
    "tells, condense them into ONE short folk tale — the kind of story that "
    "outlives the people it started with, softened and simplified in the "
    "retelling, not a precise record. It's fine, even expected, for it to "
    "drift from exactly what happened. If nothing here is worth remembering "
    "yet, say so honestly rather than inventing something ungrounded. "
    'Respond with strict JSON only, no other text: {"worth_telling": true '
    'or false, "tale": "one or two sentences, under 35 words, told as a '
    'village legend, third person"}.'
)


def build_prompt(settlement_name: str, rumor_events: list[dict], existing_folklore: list[dict]) -> str:
    lines = [f"- {event['description']}" for event in rumor_events]
    rumors_text = "\n".join(lines) if lines else "No rumors have been circulating lately."
    if existing_folklore:
        tales_text = "; ".join(entry["tale"] for entry in existing_folklore[-5:])
    else:
        tales_text = "None yet."
    return (
        f"The village of {settlement_name}. Rumors heard lately:\n{rumors_text}\n"
        f"Old tales already told: {tales_text}\n"
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


def parse_folklore(result: dict, fallback: dict) -> dict | None:
    """Returns a `{"tale": str}` entry, or None if nothing was worth
    telling (a genuine, expected outcome — folklore shouldn't form
    every single month just because the job ran)."""
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
    return {"tale": tale.strip()[:220]}
