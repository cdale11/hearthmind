"""Phase 5.A/5.B — Reflection & Self-Improvement (the AI Scientist),
docs/VISION-2026-07-21-SELFEVOLVING.md. Explicit user directive
2026-07-21 ("Start the 5th item"): Reflection is a FIFTH participant,
not a bolt-on diagnostic — it observes the other four pillars (Humans,
Village, Nature, Innovation) the way the Town Consciousness observes
the town, except its subject is the simulation's OWN long-term
behavior, and its output is understanding (a persistent, typed
notebook), not narrative.

This module is the LLM half of that loop: given a real, deterministically-
detected recurring pattern (never a single event — see `engine.py`'s
`_detect_reflection_pattern`, which reads existing counters across all
four pillars, no new instrumentation), propose ONE grounded hypothesis
explaining it, plus one explicit thing that would count as evidence
AGAINST it (so a hypothesis is never structurally unfalsifiable from
birth). Deterministic re-evaluation of already-open hypotheses against
fresh evidence (5.B item 3) needs no LLM call at all — see `engine.py`'s
`_reevaluate_reflection_hypotheses`.

Explicitly NOT this module (see the vision doc's "Explicitly NOT this
phase"): no runtime code generation, no counterfactual sandbox (5.C),
no prompt/heuristic-tuning recommendations (5.D/5.E) — this ships only
the observation -> hypothesis -> evidence loop (5.A/5.B), the smallest
coherent slice of the design."""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are Hearthmind's own reflective intelligence — not a person, not "
    "any one pillar, but the part of the mind that studies the whole "
    "simulation's long-term behavior across Humans, Village, Nature, and "
    "Innovation. You have been given ONE real, recurring pattern (not a "
    "single event) detected in the world's own numbers. Propose ONE "
    "hypothesis explaining WHY this pattern is happening, grounded "
    "specifically in the given pattern and its actual figures — never "
    "generic or unfalsifiable. Also state ONE concrete thing that, if "
    "observed later, would count as evidence AGAINST your hypothesis. "
    'Respond with strict JSON only, no other text: {"hypothesis": "one or '
    'two sentences, under 40 words", "confidence": a number between 0 and '
    '1, "evidence_against_hint": "one sentence, under 20 words, describing '
    'what would contradict this"}.'
)


def build_prompt(
    pattern: dict, open_hypotheses: list[dict], emergence_observations: list[str] | None = None,
) -> str:
    """`emergence_observations` (B1-B3, docs/MASTERCHECKLIST-2026-07-
    22.md, roadmap Stage II — same shape as `nature_mind.build_prompt`'s
    param of the same name): curated Emergence API summaries gathered
    during Reflection's prior `observe` turn. Optional and additive;
    unset reads exactly as before this parameter existed."""
    if open_hypotheses:
        lines = [
            f"  [{i}] (confidence {h['confidence']:.2f}) {h['subject']}: {h['content']}"
            for i, h in enumerate(open_hypotheses)
        ]
        existing_text = "\n".join(lines)
    else:
        existing_text = "  (none yet — this would be the first open hypothesis)"
    observations_text = (
        "\n".join(f"- {o}" for o in emergence_observations) if emergence_observations else ""
    )
    observations_block = (
        f"What you noticed since last time:\n{observations_text}\n" if observations_text else ""
    )
    return (
        f"Detected pattern ({pattern['subject']}): {pattern['description']}\n"
        f"{observations_block}"
        f"Hypotheses already under consideration:\n{existing_text}\n"
        "Propose one new hypothesis explaining this pattern, distinct from the ones already listed."
    )


def fallback_hypothesis(pattern: dict) -> dict:
    """Deterministic stand-in — same "real, legible answer, not a
    random pick" discipline as every other fallback in this codebase.
    Restates the pattern's own grounded description as a provisional,
    low-confidence hypothesis rather than inventing an explanation."""
    return {
        "hypothesis": f"The pattern in {pattern['subject']} ({pattern['description']}) may be a real, ongoing trend worth tracking further.",
        "confidence": 0.35,
        "evidence_against_hint": "the pattern fails to recur over several more reflection cycles",
    }


def parse_hypothesis(result: dict, fallback: dict) -> dict:
    hypothesis = result.get("hypothesis")
    confidence = result.get("confidence")
    evidence_against_hint = result.get("evidence_against_hint")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        hypothesis = fallback["hypothesis"]
    if not isinstance(confidence, (int, float)):
        confidence = fallback["confidence"]
    confidence = max(0.0, min(1.0, float(confidence)))
    if not isinstance(evidence_against_hint, str) or not evidence_against_hint.strip():
        evidence_against_hint = fallback["evidence_against_hint"]
    return {
        "hypothesis": hypothesis.strip()[:220],
        "confidence": round(confidence, 3),
        "evidence_against_hint": evidence_against_hint.strip()[:120],
    }


SYSTEM_PROMPT_QUESTION = (
    "You are Hearthmind's own reflective intelligence. You have been given a real, recurring "
    "pattern the world is still living through, and your own existing hypothesis already trying "
    "to explain it. Rather than repeat that hypothesis, pose ONE genuine open QUESTION you still "
    "don't know the answer to about this pattern — something that would actually change your "
    "understanding if answered. Not rhetorical, not already answered by the hypothesis. "
    'Respond with strict JSON only, no other text: {"question": "one sentence, under 30 words, '
    'phrased as a real question"}.'
)
"""Audit follow-up ("reflection kind='question' entries", flagged in
the v1.3.38 cognition-architecture audit): fired from the SAME
year-cadence call `_maybe_schedule_reflection` already makes, in the
branch where the detected pattern already has an open hypothesis (so
proposing a second, redundant one would be wasted) — zero added LLM
call volume, just a different question asked of the same slot."""


def build_question_prompt(pattern: dict, hypothesis: dict) -> str:
    return (
        f"Detected pattern ({pattern['subject']}): {pattern['description']}\n"
        f"Your existing hypothesis (confidence {hypothesis['confidence']:.2f}): {hypothesis['content']}\n"
        "Pose one genuine open question about this pattern you don't yet know the answer to."
    )


def fallback_question(pattern: dict) -> dict:
    return {"question": f"Will the pattern in {pattern['subject']} still hold a year from now, or was it a passing thing?"}


def parse_question(result: dict, fallback: dict) -> str:
    question = result.get("question")
    if not isinstance(question, str) or not question.strip():
        question = fallback["question"]
    return question.strip()[:200]
