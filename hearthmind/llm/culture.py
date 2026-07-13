"""Village culture: LLM-authored traditions invented periodically, once a
settlement is named — Phase E's first slice, an extension of B3's
chronicle rather than a new subsystem. Triggered on `year_end`
(generational cadence, slower than the chronicle's seasonal one) and fed
back into both future chronicle prompts and per-agent cognition prompts
(hearthmind/llm/cognition.py), closing the "chronicle isn't read back
into prompts" gap flagged since B3. See docs/DECISIONS.md, E1.
"""
from __future__ import annotations

TRADITION_INFLUENCES = ("festivity", "harvest", "resilience", "knowledge")
"""The fixed menu of mechanical riders a new tradition can carry —
culture with teeth (July 2026 architecture review's second-highest
emergence lever): the LLM freely authors *what* the tradition is, and
additionally classifies *which lever of village life it strengthens*.
Each accumulates a small bounded settlement-wide effect (see
buildings.culture_effect_multiplier and its consumers: festival bond
strength, farm-harvest relief, grief energy cost, and — 'knowledge',
integration milestone — skill-teaching chance in `Population._maybe_
teach_skills`, a guild-tradition-shaped rider ("apprenticeship is
valued here") rather than a bespoke new mechanic. A fixed menu — not
free-form effects — keeps a 2B model's answer safe to apply directly,
the same enum-not-prose discipline as cognition's goals."""

SYSTEM_PROMPT = (
    "You are the culture-keeper of a small simulated village. Given its "
    "name, recent history, and any traditions already established, "
    "invent ONE new named tradition, festival, or custom the village now "
    "observes. Keep it grounded in what has actually happened, not "
    "generic fantasy flavor. Also classify which part of village life it "
    "strengthens: 'festivity' (gatherings and bonds), 'harvest' (food and "
    "fieldwork), 'resilience' (mourning, endurance, hard seasons), "
    "'knowledge' (teaching, apprenticeship, craft), or 'none'. "
    'Respond with strict JSON only, no other text: {"tradition": '
    '"a short name, under 8 words", "description": "one sentence, under '
    '25 words", "influence": "festivity" | "harvest" | "resilience" | '
    '"knowledge" | "none"}.'
)

_FALLBACK_POOL: tuple[tuple[str, str, str], ...] = (
    ("The First Harvest", "Every year the village shares its first ripened crop together.", "harvest"),
    ("Hearthlight", "Villagers keep a fire burning through the longest night of winter.", "resilience"),
    ("The Gathering Walk", "Once a year, the village walks its boundary together.", "festivity"),
    ("Founders' Rest", "A day of rest is kept in memory of those who built the first structure.", "resilience"),
    ("The Apprentice's Vow", "Elders take a turn each season teaching whoever wants to learn a craft.", "knowledge"),
    ("The Quiet Meal", "Once a year the village eats together in silence, remembering the dead.", "none"),
    ("The Naming Stone", "A newborn's name is carved into the village's naming stone.", "festivity"),
    ("Winter's Debt", "Households settle small debts to each other before the first frost.", "resilience"),
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
    accumulates distinct culture (and distinct influences) over years
    rather than repeating one."""
    name, description, influence = _FALLBACK_POOL[established_count % len(_FALLBACK_POOL)]
    return {"tradition": name, "description": description, "influence": influence}


def parse_tradition(result: dict, fallback: dict) -> tuple[str, str, str]:
    name = result.get("tradition")
    description = result.get("description")
    influence = result.get("influence")
    if not isinstance(name, str) or not name.strip():
        name = fallback["tradition"]
    if not isinstance(description, str) or not description.strip():
        description = fallback["description"]
    if not isinstance(influence, str) or influence.strip().lower() not in TRADITION_INFLUENCES:
        # "none", anything unrecognized, or a missing field all mean "no
        # mechanical rider" — a purely narrative tradition stays valid.
        influence = ""
    else:
        influence = influence.strip().lower()
    return name.strip()[:80], description.strip()[:200], influence
