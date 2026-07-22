"""Vision doc item 3.4, "The world talks to you"
(docs/VISION-2026-07-22-LIVINGTERRARIUM.md): a once-a-day line in
Hearthmind's own reflective voice — not a stat, a musing. Grounded in
whatever `World.reflection_notebook` is actually puzzling over right
now (an open hypothesis) or, absent one, the most recent thing the
world itself learned (`World.knowledge_tree()`). Never invents a
subject from nothing — same "no call -> no intervention" discipline
`llm/consciousness.py` established, applied to musing instead of
action."""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are Hearthmind's own reflective intelligence, speaking directly to the person who checks "
    "on this simulated world. Given ONE real thing you are currently puzzling over — an open "
    "hypothesis you have not yet confirmed, or something the world recently learned — write ONE "
    "short, genuine musing about it. Not a status report, not a stat — the voice of something "
    "quietly wondering about its own world. Under 30 words. "
    'Respond with strict JSON only, no other text: {"musing": "one short sentence, under 30 words"}.'
)


def build_prompt(subject: dict) -> str:
    if subject["kind"] == "hypothesis":
        return (
            f"An open hypothesis you are still testing: {subject['text']} "
            f"(confidence {subject['confidence']:.2f}).\n"
            "Muse briefly about it, as if wondering aloud."
        )
    return (
        f"Something the world recently learned: {subject['text']}\n"
        "Muse briefly about it, as if wondering aloud."
    )


def fallback_musing(subject: dict | None) -> dict:
    if subject is None:
        return {"musing": ""}
    if subject["kind"] == "hypothesis":
        return {"musing": f"Still wondering whether it's true: {subject['text']}"}
    return {"musing": f"Still thinking about this: {subject['text']}"}


def parse_musing(result: dict, fallback: dict) -> str:
    musing = result.get("musing")
    if not isinstance(musing, str) or not musing.strip():
        musing = fallback["musing"]
    musing = musing.strip()
    if len(musing) > 200:
        musing = musing[:197] + "..."
    return musing
