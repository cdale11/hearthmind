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
    "Given a hardship the village has genuinely lived through more than once, "
    "decide honestly whether the village would actually codify a response to "
    "it — a law with real consequence, a binding custom, or a taboo — or "
    "whether it's still too soon, too minor, or too disputed to settle into "
    "one shared rule. Most of the time it is NOT yet settled, and that is the "
    "correct answer; only say yes when a genuinely coherent, enforceable norm "
    "follows from what's given. Never invent something ungrounded in the "
    "pattern described. "
    'Respond with strict JSON only, no other text: {"forms": true or false, '
    '"text": "the norm itself, stated plainly, under 20 words", '
    '"kind": "law", "custom", or "taboo"}. If forms is false, text and kind '
    "may be empty."
)


def build_prompt(settlement_name: str, pattern: str, occurrences: int, existing_laws: list[dict]) -> str:
    laws_text = "; ".join(law.get("text", "") for law in existing_laws) or "None yet."
    return (
        f"The village of {settlement_name} has lived through this same hardship "
        f"{occurrences} separate times: {pattern}\n"
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
