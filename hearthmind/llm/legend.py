"""A21 "Temporal compression," first slice — the LLM-narration step of
the pipeline `world/legends.py`'s deterministic detector feeds. Distinct
from `llm/folklore.py`: folklore condenses raw rumor text every month;
this narrates a genuinely RECURRING pattern (the same subsystem
producing several noteworthy Emergence API observations) into one
legend sentence, only once that pattern crosses `LEGEND_SUBSYSTEM_
THRESHOLD` — a much rarer, more selective call."""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the keeper of a small simulated village's deep memory — the "
    "handful of legends that outlast ordinary gossip. You will be given a "
    "settlement name and a short list of real things that have repeatedly "
    "happened there, all of the same underlying kind. Weave them into ONE "
    "legend: a single sentence, under 30 words, that captures the PATTERN, "
    "not a list of the individual events. Speak as if this has become a "
    "known saying or belief about the place — \"they say...\", \"it's told "
    "that...\", or similar. Ground it in what's actually given; don't invent "
    "new specifics. "
    'Respond with strict JSON only, no other text: {"legend": "one sentence, '
    'under 30 words"}.'
)


def build_prompt(settlement_name: str, subsystem: str, summaries: list[str]) -> str:
    lines = "\n".join(f"- {s}" for s in summaries)
    subsystem_label = subsystem.replace("_", " ")
    return (
        f"The village of {settlement_name}. A recurring pattern in "
        f"\"{subsystem_label}\" has shown itself again and again:\n{lines}\n"
        "Weave this pattern into one legend."
    )


def fallback_legend(settlement_name: str, subsystem: str, summaries: list[str]) -> dict:
    """Deterministic stand-in: names the pattern plainly rather than
    inventing folkloric phrasing a small model would normally supply —
    still grounded in real material (the most recent qualifying
    observation), never fabricated."""
    subsystem_label = subsystem.replace("_", " ")
    seed = summaries[-1] if summaries else subsystem_label
    return {
        "legend": f"It's said in {settlement_name} that {subsystem_label} always comes back to this: {seed}",
    }


def parse_legend(result: dict, fallback: dict) -> dict:
    """Always returns a legend entry — unlike folklore's `worth_telling`
    gate, `world/legends.py`'s detector has already decided this pattern
    IS worth naming (that's the deterministic gate); this step only
    narrates it, it doesn't get a second veto."""
    legend = result.get("legend")
    if not isinstance(legend, str) or not legend.strip():
        legend = fallback["legend"]
    return {"legend": legend.strip()[:220]}
