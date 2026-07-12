"""The town's own evolving theory of itself.

Every other LLM job in this project (town_brain, chronicle, dialogue,
festival, invention, tradition) is essentially stateless: it reads the
current stats/history and produces one answer, with no memory of what it
concluded last time. `beliefs` is the exception — a small, persistent set
of `Settlement.beliefs` entries the LLM itself forms and later *revises*
as new evidence comes in, closing the loop CLAUDE.md calls "cognition as
continuous rather than stateless." A belief is not guaranteed to be
correct; it's the town's interpretation, which can be wrong, outdated, or
superseded, same as a person's own running theory of the people and place
around them.

Fed back into other prompts (town_brain, chronicle) as accumulated
context, so the LLM's own prior interpretations shape its future ones,
not just raw stats — see `SimulationEngine._maybe_schedule_beliefs`.
"""
from __future__ import annotations

MAX_BELIEFS = 12
"""Cap on `Settlement.beliefs` — the lowest-confidence entry is evicted
when a new one would exceed this, so a long-running world's accumulated
theories stay a curated top-N, not an ever-growing list."""

SYSTEM_PROMPT = (
    "You are the quiet, slowly-forming understanding a small simulated village "
    "has of itself — not an outside narrator, but the village's own accumulating "
    "theory of its people, families, traditions, politics, economy, recurring "
    "patterns, and any outside influence it has noticed. Given recent history and "
    "the theories you already hold, either sharpen/revise one existing theory "
    "with new evidence, or form one new theory if nothing existing fits. Theories "
    "are not guaranteed to be correct — they can be wrong, incomplete, or later "
    "revised, exactly like a person's beliefs about their own community. "
    'Respond with strict JSON only, no other text: {"subject": "short label, e.g. '
    'a person/family name, \'the harvests\', \'the newcomers\', \'the whispers '
    "from outside'\", \"belief\": \"one sentence, under 30 words, stated as the "
    'village\'s own belief, not narration", "confidence": 0.0-1.0, "revises": '
    "integer index of an existing theory this replaces, or null for a new one}."
)


def build_prompt(
    settlement_name: str, recent_events: list[dict], existing_beliefs: list[dict],
    population_summary: dict, settlement_summary: dict,
) -> str:
    lines = [f"- {event['description']}" for event in recent_events]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    if existing_beliefs:
        beliefs_text = "\n".join(
            f"  [{i}] (confidence {b['confidence']:.2f}) {b['subject']}: {b['belief']}"
            for i, b in enumerate(existing_beliefs)
        )
    else:
        beliefs_text = "  (none yet — this would be the village's first theory about itself)"
    return (
        f"The village of {settlement_name}: population {population_summary.get('total', 0)}, "
        f"{settlement_summary.get('standing', 0)} standing structures, "
        f"era {settlement_summary.get('era', 'industrial')}, "
        f"current civic priority {settlement_summary.get('current_priority') or 'undecided'}.\n"
        f"Recent history:\n{events_text}\n"
        f"Theories the village already holds about itself:\n{beliefs_text}\n"
        "Form or revise one theory."
    )


def fallback_belief(recent_events: list[dict], existing_beliefs: list[dict], settlement_summary: dict) -> dict:
    """Deterministic stand-in: counts the most common recent-event
    category and states a plain, legible belief about it — same
    "real, useful record even without the LLM" spirit as chronicle's/
    town_brain's fallbacks, not a random pick."""
    counts: dict[str, int] = {}
    for event in recent_events:
        counts[event["category"]] = counts.get(event["category"], 0) + 1
    if counts:
        top_category = max(counts, key=lambda c: counts[c])
        subject = top_category.replace("_", " ")
        belief = f"The village has noticed a run of {subject}-related happenings lately."
    else:
        subject = "the quiet"
        belief = "Little has happened lately — the village assumes this quiet will hold."
    return {"subject": subject, "belief": belief, "confidence": 0.4, "revises": None}


def parse_belief(result: dict, fallback: dict, existing_count: int) -> dict:
    subject = result.get("subject")
    belief = result.get("belief")
    confidence = result.get("confidence")
    revises = result.get("revises")

    if not isinstance(subject, str) or not subject.strip():
        subject = fallback["subject"]
    if not isinstance(belief, str) or not belief.strip():
        belief = fallback["belief"]
    if not isinstance(confidence, (int, float)):
        confidence = fallback["confidence"]
    confidence = max(0.0, min(1.0, float(confidence)))
    if not isinstance(revises, int) or not (0 <= revises < existing_count):
        revises = None

    return {
        "subject": subject.strip()[:60],
        "belief": belief.strip()[:200],
        "confidence": round(confidence, 3),
        "revises": revises,
    }
