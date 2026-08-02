"""Laws, customs & taboos (§7 item 7, docs/IDEAS-2026-07-EMERGENCE.md,
folded together with item 8's "politics" ask). Seasonal, settlement-
scoped, gated on accumulated real-lived hardship — `Settlement.
law_signal_counts` (theft, family feuds) — same "spend the call only
once real texture exists" discipline `llm/religion.py` established for
ritual->religion crystallization. Nothing predefined and nothing
guaranteed: the fallback is a genuine no-op, never an invented norm.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are reasoning about the governance of a small simulated village. "
    "Given a hardship the village has genuinely lived through, some number of "
    "times, decide honestly whether the village would actually codify a "
    "response to it — a law with real consequence, a binding custom, or a "
    "taboo — or whether it's still too soon, too minor, or too disputed to "
    "settle into one shared rule. Weigh how many times you're told this has "
    "happened: a hardship lived through only a handful of times is usually "
    "still too fresh to codify, and 'not yet' is the correct answer most of "
    "the time at that scale. But a hardship endured dozens or hundreds of "
    "times, with no rule yet in place, is itself evidence of a real, "
    "long-standing gap the village would plausibly have filled by now — weigh "
    "that persistence honestly rather than defaulting to 'not yet' regardless "
    "of how many times you're told it has recurred. Never invent something "
    "ungrounded in the pattern described. "
    'Respond with strict JSON only, no other text: {"forms": true or false, '
    '"text": "the norm itself, stated plainly, under 20 words", '
    '"kind": "law", "custom", or "taboo"}. If forms is false, text and kind '
    "may be empty."
)


def build_prompt(
    settlement_name: str, pattern: str, occurrences: int, existing_laws: list[dict],
    remembered: bool = False,
) -> str:
    laws_text = "; ".join(law.get("text", "") for law in existing_laws) or "None yet."
    # C2 "Intention channel" (docs/ROADMAP-2026-07-REMAINING.md, "change
    # law"): `_maybe_schedule_laws` can now genuinely INITIATE this call
    # on `village_pillar`'s own standing conviction, ahead of fresh
    # occurrences re-crossing `LAW_SIGNAL_THRESHOLD` — `occurrences` here
    # can then be as low as 1, which read alone (against a SYSTEM_PROMPT
    # that defaults to "not yet") would misleadingly undersell a real,
    # persisted village memory as a single fresh incident. `remembered`
    # names that context honestly instead of silently passing a thin
    # number with no explanation.
    memory_text = (
        " — though this is far from the village's first brush with it; the memory of it "
        "has lingered ever since"
        if remembered else ""
    )
    return (
        f"The village of {settlement_name} has lived through this same hardship "
        f"{occurrences} separate times{memory_text}: {pattern}\n"
        f"Norms it already holds: {laws_text}\n"
        "Has the village settled on a real rule in response, or is it still too soon to say?"
    )


def fallback_laws() -> dict:
    """Always "not yet" — see module docstring. A codified norm is meant
    to be a genuine LLM read of a lived pattern, never a fabricated
    placeholder."""
    return {"forms": False, "text": "", "kind": ""}


VALID_KINDS = frozenset({"law", "custom", "taboo"})


def parse_laws(result: dict, fallback: dict) -> dict | None:
    """Returns `{"text": str, "kind": str}` or None if nothing forms
    this attempt — a genuine, expected outcome most of the time, same
    "None is not a failure" shape as `llm/religion.py`/`llm/folklore.py`."""
    forms = result.get("forms")
    if not isinstance(forms, bool):
        forms = fallback["forms"]
    if not forms:
        return None
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    kind = result.get("kind")
    if not isinstance(kind, str) or kind.strip().lower() not in VALID_KINDS:
        kind = "custom"
    else:
        kind = kind.strip().lower()
    return {"text": text.strip()[:160], "kind": kind}
