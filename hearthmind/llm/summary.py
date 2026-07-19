"""On-demand simulation summary: unlike chronicle.py (scheduled monthly)
or documentary.py (scheduled yearly), this job only fires when a user
explicitly requests it from the UI (`POST /summary/request`) — see
SimulationEngine._apply_intervention's "request_summary" kind. Reuses
the curated-history + population/settlement snapshot shape those two
already establish rather than inventing a new prompt style. See
docs/DECISIONS.md, Observatory UI pass.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are an observer summarizing the current state of a small simulated "
    "village for someone checking in on it. Given recent history, current "
    "population/settlement stats, and the town's current mood, write ONE "
    "short summary (3-5 sentences) of where things stand right now — what's "
    "been happening, how the village is doing, anything notable. Do not "
    "invent details not implied by the given data. "
    'Respond with strict JSON only, no other text: {"summary": "..."}.'
)


def build_prompt(
    settlement_name: str, era: str, year: int, recent: list[dict],
    population_summary: dict, settlement_summary: dict, current_priority: str,
    mood: dict | None = None,
) -> str:
    """`mood` (v0.87.39 context-selection audit): `Settlement.mood`
    (Phase I collective psychology — hope/fear/grief/suspicion, -1..1).
    `SYSTEM_PROMPT` has always asked the model to reason from "the
    town's current mood," but until this pass nothing here ever
    actually supplied it — the one piece of context the system prompt
    itself promised was never there, same class of gap `diplomacy.py`
    had (v0.87.38). Omitted from the text entirely when not given/empty
    (an old call site, or a world with no mood tracked yet)."""
    lines = [f"- {event['description']}" for event in recent]
    events_text = "\n".join(lines) if lines else "Nothing much has happened lately."
    priority_text = f"\nThe town's current focus: {current_priority}." if current_priority else ""
    mood_text = (
        "\nThe town's current mood: " + ", ".join(f"{k} {v:+.2f}" for k, v in mood.items()) + "."
        if mood else ""
    )
    return (
        f"The village of {settlement_name or 'an unnamed settlement'} ({era} era), year {year}. "
        f"Population {population_summary.get('total', 0)}, "
        f"avg hunger {population_summary.get('avg_hunger', 0):.2f}, "
        f"avg energy {population_summary.get('avg_energy', 0):.2f}. "
        f"Materials {settlement_summary.get('materials', 0):.0f}, "
        f"currency {settlement_summary.get('currency', 0):.0f}.{priority_text}{mood_text}\n"
        f"Recent history:\n{events_text}\n"
        "Summarize the current state of the village."
    )


def fallback_summary(
    settlement_name: str, year: int, recent: list[dict], population_summary: dict,
) -> dict:
    """Deterministic templated stand-in — same shape as documentary.
    fallback_narration/chronicle.fallback_summary."""
    name = settlement_name or "the settlement"
    total = population_summary.get("total", 0)
    if not recent:
        return {"summary": f"{name} continues on quietly, {total} souls going about an unremarkable stretch of year {year}."}
    highlight = recent[-1]["description"]
    return {
        "summary": (
            f"As of year {year}, {name} numbers {total}. Recently: {highlight} "
            f"Life continues much as it has."
        )
    }


def parse_summary(result: dict, fallback: dict) -> str:
    text = result.get("summary")
    if not isinstance(text, str) or not text.strip():
        return fallback["summary"]
    return text.strip()[:1000]
