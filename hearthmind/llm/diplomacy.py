"""Inter-settlement diplomacy (item 8b, docs/IDEAS-2026-07-EMERGENCE.md
item 8's "inter-settlement relationships" ask). The underlying affinity
mechanism already exists and is deterministic (`Settlement.relations`,
`settlement/buildings.py`'s "cross-settlement relations" section — seeded
at fission, nudged by cross-settlement dialogue, felt in market prices).
This module is the LLM-authored layer on top: an occasional, named
diplomatic moment (an envoy, a trade pact, a border dispute) between two
named settlements sharing the same map, reasoning from their existing
relation score rather than replacing it. Ambient texture, not crucial
cognition — the fallback is a genuine no-op (a between-settlement
relationship the model never actually reasoned about that month just
holds, exactly as if no contact happened), never a fabricated event.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are reasoning about relations between two neighboring settlements in "
    "a small simulated world. Given their current mutual standing and what "
    "each has recently lived through, decide whether anything notable passes "
    "between them this season — an envoy, a trade agreement, a border dispute, "
    "a shared festival, or simply nothing worth naming (the common case). "
    "Keep any change to the relationship small and grounded in what's given. "
    'Respond with strict JSON only, no other text: {"happens": true or false, '
    '"narration": "one short sentence, under 25 words", '
    '"relation_delta": a number between -0.15 and 0.15}. If happens is '
    "false, narration may be empty and relation_delta should be 0."
)


def build_prompt(name_a: str, name_b: str, relation: float, priority_a: str, priority_b: str) -> str:
    tone = "warm" if relation > 0.3 else "cold" if relation < -0.3 else "neutral"
    return (
        f"{name_a} and {name_b} are two settlements sharing the same land. "
        f"Their current standing is {tone} ({relation:+.2f} on a -1..1 scale). "
        f"{name_a}'s current priority: {priority_a or 'unclear'}. "
        f"{name_b}'s current priority: {priority_b or 'unclear'}. "
        "Does anything notable pass between them this season?"
    )


def fallback_diplomacy() -> dict:
    """Genuine no-op — see module docstring. The deterministic monthly
    `tick_relation` mean-reversion/jitter (settlement/buildings.py)
    keeps handling ordinary drift regardless; this fallback simply
    contributes nothing extra that month."""
    return {"happens": False, "narration": "", "relation_delta": 0.0}


DIPLOMACY_DELTA_MAX = 0.15
"""Bound on a single diplomacy event's relation swing — small next to
the full -1..1 range, same "never dominant" shape as every other Phase G
nudge; the deterministic `tick_relation` walk still does most of the
work over time."""


def parse_diplomacy(result: dict, fallback: dict) -> tuple[str, float] | None:
    """Returns `(narration, relation_delta)` or None if nothing happens
    this attempt — a genuine, expected outcome most months."""
    happens = result.get("happens")
    if not isinstance(happens, bool):
        happens = fallback["happens"]
    if not happens:
        return None
    narration = result.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        return None
    delta = result.get("relation_delta")
    if not isinstance(delta, (int, float)):
        delta = 0.0
    delta = max(-DIPLOMACY_DELTA_MAX, min(DIPLOMACY_DELTA_MAX, float(delta)))
    return narration.strip()[:200], delta
