"""Nature's causal reasoning (docs/ROADMAP-2026-07-REMAINING.md, Tier
0's "scoped, NOT shipped — a genuinely new Nature cognition job",
implemented across two explicit-direction passes: "as many slices of
tier 0 as you can" shipped the first trigger, a later "as many slices
as possible" pass shipped the other two named candidates from the
same design note). `llm/nature_mind.py` is a general seasonal belief-
revision pass ("form any theory about the land's current state"); this
is different in kind, not just cadence — a REACTIVE job that fires
only when one of three specific, already-detected anomalies happens
(a local predator-pack extinction, a local grazer-herd extinction, or
a forest tile stalled well past its own fallow requirement despite
favorable moisture — see `SimulationEngine._maybe_schedule_nature_
causal_reasoning`'s three trigger methods), asking "why might THIS
specific thing be happening?" grounded in the real Body-state signals
available at that moment, not a generic digest.

Genuine judgment, not narration: `critical=True` (Constitution §3/§7)
— a failed/budget-exhausted call defers rather than fabricating a
cause. Output is always `status="hypothesis"`, never `"observation"`
— a wordless land has no ground truth to confirm, same discipline
`omen`'s Nature-pillar mirror already established for supernatural-
adjacent uncertainty; here it's ordinary ecological uncertainty
instead, but the epistemic humility is the same."""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the quiet, wordless intelligence of a wild landscape, reasoning about "
    "why something specific just happened in its own ecology. You have no certainty — "
    "offer your best guess, grounded in the facts given, not a confident diagnosis. "
    'Respond with strict JSON only, no other text: {"cause": "one or two sentences, '
    'under 40 words, a plausible specific reason grounded in the facts given"}.'
)


def build_prompt(anomaly_text: str, context_bits: list[str], existing_beliefs: list[dict]) -> str:
    context_text = "; ".join(context_bits) if context_bits else "no other notable conditions"
    belief_text = ""
    if existing_beliefs:
        newest = existing_beliefs[-1]
        belief_text = f" Your most recent sense of the land: {newest['belief']}"
    return (
        f"{anomaly_text} Recent conditions: {context_text}.{belief_text} "
        f"Why might this specific thing have happened?"
    )


def fallback_cause() -> dict:
    """Never actually applied (`critical=True` skips `apply()` entirely
    on a fallback/deferred call, see `SimulationEngine._schedule_llm_
    job`'s docstring) — only used for `_record_llm_debug`'s bookkeeping,
    so this just needs to be a plausible-shaped placeholder."""
    return {"cause": ""}


def parse_cause(result: dict) -> str:
    text = result.get("cause")
    if not isinstance(text, str) or not text.strip():
        return ""
    return text.strip()[:280]
