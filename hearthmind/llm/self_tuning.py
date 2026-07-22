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

TUNABLE_GOVERNORS = {"wildfire frequency": "wildfire_chance"}
"""Closed vocabulary: reflection hypothesis subject -> governor key
consumed by `World.governor_tuning`. Only one governor is wired to a
real mechanical effect so far (`tick_wildfire`'s `chance_multiplier`)
— the vision doc's own worked example. Extending this dict is how a
future governor joins self-tuning; the interpreter itself stays fixed."""

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


def build_prompt(governor_label: str, hypothesis_text: str, current_multiplier: float) -> str:
    return (
        f"Governor under consideration: {governor_label}\n"
        f"Your supported hypothesis about it: {hypothesis_text}\n"
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
    magnitude = max(0.0, min(1.0, float(magnitude)))
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
    return max(1.0 - band, min(1.0 + band, 1.0 + signed))
