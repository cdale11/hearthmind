"""Documentary mode: a yearly LLM-narrated summary of the world's
evolution, built from curated history (persistence.snapshot's
HISTORY_CATEGORIES) rather than the raw everything-included event feed
`chronicle.py` uses — a documentary looks back over milestones (a
settlement named, an era advanced, a belief formed, a disaster
weathered), not routine day-to-day noise. Same "reuse the events table,
new category" shape as chronicle.py: no new persistence, just a longer
narrated `documentary` row logged once a year. See docs/DECISIONS.md,
Observatory UI pass.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a documentary narrator looking back on a year in the life of a "
    "small simulated village, in the style of a nature/history documentary "
    "voiceover — measured, a little wistful, grounded only in what actually "
    "happened. Given a list of the year's curated historical milestones, "
    "write ONE short narrated passage (3-5 sentences) covering the arc of "
    "the year. Do not invent details not implied by the given events. "
    'Respond with strict JSON only, no other text: {"narration": "..."}.'
)


def build_prompt(
    settlement_name: str, era: str, year: int, milestones: list[dict],
    population_summary: dict, temperament: float, records: list[dict] | None = None,
) -> str:
    lines = [f"- {event['description']}" for event in milestones]
    events_text = "\n".join(lines) if lines else "A quiet year — nothing rose to the level of history."
    records_text = ""
    if records:
        # Written artifacts (v0.64.0): the dead speak in their own words
        # — a documentary quoting the letters people left behind is
        # exactly the "memory that outlives its author" payoff.
        records_text = "\nWords the departed left behind:\n" + "\n".join(
            f'- {r["author"]} wrote: "{r["text"]}"' for r in records
        )
    return (
        f"The village of {settlement_name or 'an unnamed settlement'} ({era} era), "
        f"year {year}. Population now {population_summary.get('total', 0)}.\n"
        f"This year's milestones:\n{events_text}{records_text}\n"
        "Narrate this year for a documentary."
    )


def fallback_narration(
    settlement_name: str, year: int, milestones: list[dict], population_summary: dict,
) -> dict:
    """Deterministic templated stand-in — a plain factual recap rather
    than prose, same shape as chronicle.fallback_summary."""
    name = settlement_name or "the settlement"
    if not milestones:
        return {"narration": f"Year {year} passed quietly in {name}, with {population_summary.get('total', 0)} souls living out an unremarkable stretch of history."}
    highlight = milestones[-1]["description"]
    return {
        "narration": (
            f"Year {year} in {name}: {len(milestones)} moment{'s' if len(milestones) != 1 else ''} "
            f"worth remembering, among them — {highlight} The village now numbers "
            f"{population_summary.get('total', 0)}."
        )
    }


def parse_narration(result: dict, fallback: dict) -> str:
    narration = result.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        return fallback["narration"]
    return narration.strip()[:1000]
