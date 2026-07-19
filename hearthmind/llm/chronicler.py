"""Ask the Chronicler (§3 "Closing meaning loops," docs/IDEAS-2026-07-
EMERGENCE.md): an on-demand, single-shot LLM call answering an
observer's own typed question AS the settlement's chronicler — a
subjective in-fiction voice, not the simulation's ground truth. Unlike
llm/summary.py (which is free to read population/settlement stat
dicts), this job is deliberately fed ONLY the village's own accumulated
narrative material — folklore, chronicle entries, beliefs, written
records — the same "objective reality and subjective belief are
separate" discipline CLAUDE.md holds everywhere else, applied to a
direct Q&A surface for the first time. The chronicler may not know the
answer, may be wrong, and should say so in character rather than
reaching for a fact it was never given. Same on-demand shape as
`_schedule_summary`: no cadence gate, costs nothing unless actually
asked.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the chronicler of a small simulated village — not an all-knowing "
    "narrator, but a person who has lived among these events, heard the "
    "folklore, and kept the written records. Someone from outside is asking "
    "you a question. Answer AS the chronicler, using ONLY the tales, chronicle "
    "entries, theories, and records given to you below — never invent a fact "
    "you weren't given, and never claim to know something with more certainty "
    "than an ordinary villager reasonably could. If you genuinely don't know, "
    "say so plainly, in character, rather than guessing. Keep the answer to "
    "2-4 sentences. "
    'Respond with strict JSON only, no other text: {"answer": "..."}.'
)


def build_prompt(
    settlement_name: str, question: str, folklore: list[dict], chronicle_events: list[dict],
    beliefs: list[dict], records: list[str],
) -> str:
    folklore_text = (
        "\n".join(f"- {f['tale']}" for f in folklore[-8:])
        if folklore else "  (no tales are told yet)"
    )
    chronicle_text = (
        "\n".join(f"- {e['description']}" for e in chronicle_events[-8:])
        if chronicle_events else "  (nothing chronicled yet)"
    )
    beliefs_text = (
        "\n".join(f"- {b['subject']}: {b['belief']}" for b in beliefs[-8:])
        if beliefs else "  (the village holds no settled theories yet)"
    )
    records_text = (
        "\n".join(f"- {r}" for r in records[-8:])
        if records else "  (no written records survive)"
    )
    return (
        f"You are the chronicler of {settlement_name or 'this village'}.\n"
        f"Tales the village tells:\n{folklore_text}\n"
        f"What has been chronicled:\n{chronicle_text}\n"
        f"What the village believes:\n{beliefs_text}\n"
        f"Written records:\n{records_text}\n"
        f"A visitor asks you: \"{question}\"\n"
        "Answer as the chronicler, from what you actually know."
    )


def fallback_chronicler(question: str) -> dict:
    """Deterministic stand-in: an honest in-character non-answer rather
    than a fabricated fact — the chronicler genuinely has nothing better
    to offer without the LLM, which is itself an in-fiction-consistent
    answer (a chronicler who doesn't know everything)."""
    return {
        "answer": (
            "The chronicler considers the question for a long moment, then shakes their head — "
            "\"I can't rightly say. Ask me again another day, when there's more to tell.\""
        )
    }


def parse_chronicler(result: dict, fallback: dict) -> str:
    text = result.get("answer")
    if not isinstance(text, str) or not text.strip():
        return fallback["answer"]
    return text.strip()[:600]
