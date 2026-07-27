"""Ritual -> religion crystallization (Phase M, docs/VISION-2026-07.md,
"Faith & Meaning"): seasonal, settlement-scoped. `Settlement.rituals`
accumulates for free (deterministic detection of repeated real
coincidence, see `SimulationEngine._detect_ritual_signals`/
`_maybe_promote_ritual`) — this is the one LLM call in the pipeline,
asked only once enough rituals exist, deciding whether they genuinely
coalesce into something more. Nothing predefined; a village is not
guaranteed to ever form a religion, and this fallback never invents
one from nothing — same "worth_telling"-style honest-no discipline as
`llm/folklore.py`.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are reasoning about the inner life of a small simulated village. "
    "Given the practices it repeats without being told to, and the omens and "
    "tales it already carries, decide honestly whether these have coalesced "
    "into something more than habit — a shared, named belief about the "
    "world. Most of the time they haven't yet, and that is the correct "
    "answer; only say yes when the practices genuinely point at a coherent "
    "idea (fate, ancestors, a hidden order, a particular place or figure). "
    "Never invent something ungrounded in what's given. "
    'Respond with strict JSON only, no other text: {"forms": true or false, '
    '"name": "a short name for the belief, under 6 words", "tenets": '
    '["one short tenet", "another", "up to 4"]}. If forms is false, name '
    'and tenets may be empty.'
)


def build_prompt(
    settlement_name: str, rituals: list[dict], omen_history: list[dict], folklore: list[dict],
    legends: list[dict] | None = None,
) -> str:
    """`legends` (A21 "Temporal compression," third slice, explicit user
    instruction "Continue A21"): a village's own crystallized legends
    (`Settlement.legends`) are stronger, already-decided grounding than
    an ordinary folk tale — a religion crystallizing around a subject
    the village already has a real legend about is a more coherent read
    than one grounded only in habit and rumor. Optional and additive:
    omitted or empty reproduces the prior prompt exactly."""
    rituals_text = "\n".join(f"- {r['description']}" for r in rituals) or "None yet."
    omens_text = "; ".join(o.get("text", "") for o in omen_history[-4:]) or "None noticed."
    folklore_text = "; ".join(f["tale"] for f in folklore[-4:]) or "None told."
    legends_line = ""
    if legends:
        legends_text = "; ".join(e["legend"] for e in legends[-3:])
        legends_line = f"Legends the village already holds as true: {legends_text}\n"
    return (
        f"The village of {settlement_name}. Practices it repeats without being told to:\n{rituals_text}\n"
        f"Omens noticed over the years: {omens_text}\n"
        f"Tales the village tells: {folklore_text}\n"
        f"{legends_line}"
        "Do these coalesce into a shared belief, or is it too soon to say?"
    )


def fallback_religion() -> dict:
    """Deterministic stand-in: always "not yet" — a religion crystallizing
    is meant to be a genuine LLM read of accumulated texture, never a
    fallback invention. See `llm/folklore.py`'s identical discipline for
    a job whose fallback can legitimately mean "nothing happened"."""
    return {"forms": False, "name": "", "tenets": []}


def parse_religion(result: dict, fallback: dict) -> dict | None:
    """Returns `{"name": str, "tenets": list[str]}` or None if it
    doesn't form this attempt — a genuine, expected outcome most of the
    time, matching `parse_folklore`'s "None is not a failure" shape."""
    forms = result.get("forms")
    if not isinstance(forms, bool):
        forms = fallback["forms"]
    if not forms:
        return None
    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        return None  # a nameless "religion" isn't a real answer — treat as not-yet
    tenets = result.get("tenets")
    if not isinstance(tenets, list):
        tenets = []
    clean_tenets = [t.strip()[:120] for t in tenets if isinstance(t, str) and t.strip()][:4]
    if not clean_tenets:
        return None  # tenets are the substance — no tenets means it isn't real yet
    return {"name": name.strip()[:60], "tenets": clean_tenets}
