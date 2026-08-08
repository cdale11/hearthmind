"""Vision doc items 1.4/2.4, docs/VISION-2026-07-22-LIVINGTERRARIUM.md:
"Self-tuning as bounded proposals (Reflection 5.D/5.E)" and "The
world-Mind: a Reflection that acts." Reflection may propose a bounded
nudge to one of a small, closed set of TUNABLE governors — never a raw
value, only a direction + magnitude within `disasters.
GOVERNOR_TUNING_BAND` of the governor's own base constant — grounded in
one of its own SUPPORTED hypotheses (a pattern that has recurred enough
to survive `_reevaluate_reflection_hypotheses`'s deterministic
evidence-nudging, not a single-cycle guess). The proposal is only ever
enacted after `simulation.sandbox.run_counterfactual` validates it on a
disposable forked world — see `SimulationEngine._maybe_schedule_self_
tuning`. This is critical cognition (a genuine, real judgment about the
world's own balance, not narrative texture) — deferred, never faked, on
a spent budget or failed call, same as `nature_mind`/`beliefs`."""
from __future__ import annotations

from hearthmind.util import clamp

TUNABLE_GOVERNORS = {
    "wildfire frequency": "wildfire_chance",
    "ontology coherence": "ontology_proposal_chance",
    "disease outbreak": "disease_outbreak_chance",
}
"""Closed vocabulary: reflection hypothesis subject -> governor key
consumed by `World.governor_tuning`. `wildfire_chance` is the vision
doc's own worked example (`tick_wildfire`'s `chance_multiplier`).
`ontology_proposal_chance` (vision item 5.3, "coherence/drift
detection") is the immune-system counterpart — when Reflection's
ontology-coherence hypothesis (a high abandoned-concept fraction) is
supported, self-tuning may nudge this multiplier within the usual
`disasters.GOVERNOR_TUNING_BAND`, same bounded direction+magnitude
shape as every other governor (the model isn't forced to lower it, but
a hypothesis grounded in "too much abandoned churn" gives it real
reason to) — see `_maybe_schedule_ontology_proposal`'s consumption of
`World.governor_tuning.get("ontology_proposal_chance", 1.0)`.
`disease_outbreak_chance` (B6, roadmap Stage III step 13, "extend
TUNABLE_GOVERNORS to the major levers") is the worked example for
`_detect_reflection_pattern`'s SETTLEMENT-scoped signals — those
subjects are `f"{label} in {settlement_name}"` (varies per
settlement), so `SimulationEngine._maybe_schedule_self_tuning`
matches a hypothesis subject against this dict by PREFIX
(`subject.startswith(key)`), not exact equality; every settlement-
scoped pattern is now governable this way, `disease_outbreak_chance`
(consumed by `Population._maybe_outbreak`'s `chance_multiplier`) is
just the first one actually wired to a real multiplier. Extending this
dict (plus wiring the matching consumer) is how a future governor
joins self-tuning; the interpreter itself stays fixed."""

SYSTEM_PROMPT = (
    "You are Hearthmind's own reflective intelligence, now considering whether to "
    "adjust one of the simulation's own tunable balance knobs. You have been given a "
    "hypothesis you already believe, grounded in the world's real numbers, about one "
    "named governor drifting away from its intended rate. Propose a SMALL, bounded "
    "nudge: a direction (raise or lower the rate) and a magnitude between 0 and 1 "
    "representing how much of the allowed adjustment band to use (1.0 is the maximum "
    "allowed nudge, not an unbounded change). Also give one short rationale citing the "
    'actual figures. Respond with strict JSON only, no other text: {"direction": '
    '"raise" or "lower", "magnitude": a number between 0 and 1, "rationale": "one '
    'sentence, under 30 words, citing the numbers from the hypothesis"}.'
)


def build_prompt(
    governor_label: str, hypothesis_text: str, current_multiplier: float, via_conviction: bool = False,
) -> str:
    # C2 "Intention channel" (docs/ROADMAP-2026-07-REMAINING.md, "propose
    # experiment"): `_maybe_schedule_self_tuning` can now genuinely
    # initiate testing a hypothesis EARLY, on `reflection_pillar`'s own
    # standing conviction, before it's crossed `REFLECTION_SUPPORTED_
    # THRESHOLD` through the normal evidence-accumulation loop — the
    # prompt must say so honestly (`via_conviction`) rather than
    # unconditionally claiming "supported," which would misrepresent an
    # open, not-yet-proven hypothesis's real epistemic status to the
    # model and undermine the "evidence stays authoritative" discipline
    # this whole mechanism depends on.
    hypothesis_label = (
        "A hunch you feel strongly about, though the evidence hasn't fully settled it yet"
        if via_conviction else "Your supported hypothesis about it"
    )
    return (
        f"Governor under consideration: {governor_label}\n"
        f"{hypothesis_label}: {hypothesis_text}\n"
        f"Its current effective multiplier: {current_multiplier:.2f} (1.0 = base rate, "
        "unmodified).\n"
        "Propose a bounded nudge, or a very small magnitude if you believe no real "
        "adjustment is warranted."
    )


def fallback_self_tuning() -> dict:
    """Deterministic stand-in — used only for `_record_llm_debug`
    bookkeeping (critical jobs never apply a fallback result, see
    `_schedule_llm_job`'s docstring); a genuine no-op nudge."""
    return {"direction": "raise", "magnitude": 0.0, "rationale": "no adjustment proposed"}


def parse_self_tuning(result: dict, fallback: dict) -> dict:
    direction = result.get("direction")
    magnitude = result.get("magnitude")
    rationale = result.get("rationale")
    if direction not in ("raise", "lower"):
        direction = fallback["direction"]
    if not isinstance(magnitude, (int, float)):
        magnitude = fallback["magnitude"]
    magnitude = clamp(float(magnitude), 0.0, 1.0)
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = fallback["rationale"]
    return {
        "direction": direction, "magnitude": round(magnitude, 3), "rationale": rationale.strip()[:160],
    }


def apply_bounded_nudge(magnitude: float, direction: str, band: float) -> float:
    """The interpreter itself: converts a parsed (direction, magnitude)
    into a real effective multiplier bounded to
    [1-band, 1+band] — the homeostatic band is enforced HERE,
    structurally, regardless of what the LLM asked for."""
    signed = magnitude * band * (1.0 if direction == "raise" else -1.0)
    return clamp(1.0 + signed, 1.0 - band, 1.0 + band)


# --- advisory (B6 "Reflection as meta-scientist," roadmap Stage III step 13) ---

SYSTEM_PROMPT_ADVISORY = (
    "You are Hearthmind's own reflective intelligence. You hold a hypothesis you "
    "already believe, grounded in the world's real numbers, but it does not name any "
    "of the simulation's small set of tunable balance knobs — there is nothing you can "
    "directly nudge. Instead, write ONE short piece of advice for the person who built "
    "this world: what might genuinely help, or what is worth watching for. This is "
    "advice for a human to consider, not an action you are taking yourself. "
    'Respond with strict JSON only, no other text: {"advice": "one or two sentences, '
    'under 40 words, concrete and grounded in the hypothesis given"}.'
)


def build_advisory_prompt(hypothesis_subject: str, hypothesis_text: str) -> str:
    return (
        f"Your supported hypothesis: {hypothesis_subject} — {hypothesis_text}\n"
        "This does not match any governor you can directly tune. Offer your advice "
        "about it to whoever built this world."
    )


def fallback_advisory() -> dict:
    """Deterministic stand-in — used only for `_record_llm_debug`
    bookkeeping (critical jobs never apply a fallback result, see
    `_schedule_llm_job`'s docstring)."""
    return {"advice": "no specific advice — this pattern is worth watching, not yet acting on."}


def parse_advisory(result: dict, fallback: dict) -> dict:
    advice = result.get("advice")
    if not isinstance(advice, str) or not advice.strip():
        advice = fallback["advice"]
    return {"advice": advice.strip()[:220]}
