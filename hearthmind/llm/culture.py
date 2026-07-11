"""Village culture: LLM-authored traditions invented periodically, once a
settlement is named — Phase E's first slice, an extension of B3's
chronicle rather than a new subsystem. Triggered on `year_end`
(generational cadence, slower than the chronicle's seasonal one) and fed
back into both future chronicle prompts and per-agent cognition prompts
(hearthmind/llm/cognition.py), closing the "chronicle isn't read back
into prompts" gap flagged since B3. See docs/DECISIONS.md, E1.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the culture-keeper of a small simulated village. Given its "
    "name, recent history, and any traditions already established, "
    "invent ONE new named tradition, festival, or custom the village now "
    "observes. Keep it grounded in what has actually happened, not "
    "generic fantasy flavor. "
    'Respond with strict JSON only, no other text: {"tradition": '
    '"a short name, under 8 words", "description": "one sentence, under 25 words"}.'
)

_FALLBACK_POOL: tuple[tuple[str, str], ...] = (
    ("The First Harvest", "Every year the village shares its first ripened crop together."),
    ("Hearthlight", "Villagers keep a fire burning through the longest night of winter."),
    ("The Gathering Walk", "Once a year, the village walks its boundary together."),
    ("Founders' Rest", "A day of rest is kept in memory of those who built the first structure."),
    ("The Quiet Meal", "Once a year the village eats together in silence, remembering the dead."),
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], existing_traditions: list[str], year: int
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    traditions_text = "; ".join(existing_traditions) if existing_traditions else "None yet."
    return (
        f"The village of {settlement_name} has completed year {year}. "
        f"Recent history:\n{events_text}\n"
        f"Traditions already established: {traditions_text}\n"
        "Invent one new tradition this village now keeps."
    )


def fallback_tradition(settlement_name: str, year: int, established_count: int) -> dict:
    """Deterministic stand-in — cycles through a small fixed pool by how
    many traditions already exist, so a fallback-only run still
    accumulates distinct culture over years rather than repeating one."""
    name, description = _FALLBACK_POOL[established_count % len(_FALLBACK_POOL)]
    return {"tradition": name, "description": description}


def parse_tradition(result: dict, fallback: dict) -> tuple[str, str]:
    name = result.get("tradition")
    description = result.get("description")
    if not isinstance(name, str) or not name.strip():
        name = fallback["tradition"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    return name.strip()[:80], description.strip()[:200]
