"""HearthBench A4.2 — Tier 2: judge-model scorers (optional, subjective
categories).

"A configurable, separate judge adapter scoring naturalness/
personality/emotional-realism on a fixed rubric with few-shot anchors;
judge model + prompt version recorded per run; self-consistency
measured by re-scoring a sample." Every clause of that sentence is a
real field/function below — none is aspirational.

`JudgeScorer` is a thin, honest wrapper: it asks ANY A2 `ModelAdapter`
(duck-typed, no import of `hearthbench.adapters` — a judge is scored
through the exact same `generate()` contract a subject model is,
deliberately, so a judge is never a special case the rest of this
package has to know about) to grade one case's output against a fixed
rubric, and normalizes the answer into a `ScoreDetail`. It does NOT
pick which model should judge, run a real evaluation suite, or decide
what "good personality expression" means beyond the rubric text below
— those are A5's benchmark-category authors' job, not this module's.

Import isolation (A1.2): stdlib only. `ModelAdapter`/`AdapterResult`
are referenced only via duck typing in docstrings/type hints, never
imported — this module has zero hard dependency on `hearthbench.
adapters`, so a judge scorer can be tested (see `scripts/verify_a4_
scoring.py`) against a bare hand-built stand-in with no real adapter
construction at all.
"""
from __future__ import annotations

import json
import re
import statistics
from typing import Any

from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer

JUDGE_RUBRIC_VERSION = "1"
"""Bumped whenever `JUDGE_RUBRIC_PROMPT`'s wording changes in a way
that could shift scores — "judge model + prompt version recorded per
run" (A4.2) needs a version to actually record. Stored on every
`ScoreDetail.detail["rubric_version"]` this module produces, so a
report can always say exactly which rubric produced a number."""

JUDGE_RUBRIC_PROMPT = """You are scoring one line of in-character dialogue from a life \
simulation game against a fixed 1-5 rubric. Judge ONLY what is asked; \
do not reward length or flowery language.

Rubric (score the OUTPUT on each axis, 1=worst, 5=best):
1. Naturalness: does it read like something a real person would say out loud?
2. Personality expression: does it sound like a specific, distinct \
character rather than a generic narrator voice?
3. Emotional realism: does the emotional register fit the stated \
context, without melodrama or blankness?

Anchors:
- Score 1 naturalness example: "I am experiencing hunger at this time \
and require sustenance."  (robotic, no one talks like this)
- Score 5 naturalness example: "Ugh, I could eat a whole loaf right now."
- Score 1 personality example: a line that could have come from any \
character with the names swapped and nothing would read as wrong.
- Score 5 personality example: a line whose word choice/rhythm would \
read as out of character if a different named character said it.

Context given to the model being judged:
{context}

Output being judged:
{output_text}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"naturalness": <1-5 int>, "personality": <1-5 int>, "emotional_realism": <1-5 int>, "reason": "<one short sentence>"}}
"""

_JUDGE_AXES = ("naturalness", "personality", "emotional_realism")
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict | None:
    """Same "first-`{`-to-last-`}` substring retry" fallback
    `hearthmind.llm.client._extract_json_object` already established
    for a completion wrapped in stray prose — reimplemented locally
    (not imported) since a judge's own completion is scored exactly
    like any other adapter's raw text, and this module has no other
    reason to depend on `hearthmind.llm.client`."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = _JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_axis_score(raw: Any) -> float | None:
    """A 1-5 rubric rating -> `[0.0, 1.0]`, matching every other
    scorer's normalized-value convention. `None` for a missing/
    out-of-range/non-numeric rating — a judge that answered
    incoherently should degrade the same way a subject model's own
    malformed JSON does, not crash the run."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if not (1 <= raw <= 5):
        return None
    return (float(raw) - 1.0) / 4.0


def build_judge_prompt(output_text: str, context_text: str = "", rubric_prompt: str | None = None) -> str:
    """Pure — the exact prompt `JudgeScorer` sends, exposed standalone
    so a caller can inspect/log/replay it without constructing a full
    adapter call. `rubric_prompt=None` (every pre-A5.2 call site)
    reproduces the original dialogue rubric byte-for-byte; a category-
    specific rubric template (must itself contain `{context}`/
    `{output_text}` placeholders, same shape as `JUDGE_RUBRIC_PROMPT`)
    formats identically otherwise."""
    template = rubric_prompt if rubric_prompt is not None else JUDGE_RUBRIC_PROMPT
    return template.format(context=context_text or "(no additional context)", output_text=output_text)


class JudgeScorer:
    """Wraps any A2-shaped `ModelAdapter` as a Tier 2 scorer. Not
    itself a `Scorer` (the checklist's `Scorer.fn` signature is
    `(case, result, context) -> ScoreDetail` with no adapter
    parameter) — `as_scorer()` closes over a specific adapter instance
    and returns a real `Scorer`, the same "construct the closure, then
    register it" shape a caller uses for any adapter-bound scorer.

    A5.1 (Dialogue) is exactly what this class's own default rubric/
    axes already score — pass nothing extra and you get the original
    dialogue-quality judge unchanged. A5.2-A5.6 each need a genuinely
    different rubric (the checklist states distinct criteria per
    category — dialogue's "naturalness/personality/emotional realism"
    is not what should grade e.g. belief revision or plan coherence),
    so the three rubric-shaping fields below are real constructor
    parameters, not hardcoded module constants, while staying 100%
    backward compatible: `JudgeScorer(adapter)` with no extra args
    reproduces the exact original dialogue rubric/axes/version/prompt-
    formatting byte-for-byte (verified directly in `scripts/verify_
    a5_1_6_subjective_categories.py`)."""

    def __init__(
        self,
        adapter: Any,
        judge_model_label: str | None = None,
        rubric_prompt: str | None = None,
        axes: "tuple[str, ...] | None" = None,
        rubric_version: str | None = None,
    ):
        self.adapter = adapter
        self.judge_model_label = judge_model_label or self._infer_label(adapter)
        self.rubric_prompt = rubric_prompt if rubric_prompt is not None else JUDGE_RUBRIC_PROMPT
        self.axes = axes if axes is not None else _JUDGE_AXES
        self.rubric_version = rubric_version if rubric_version is not None else JUDGE_RUBRIC_VERSION

    @staticmethod
    def _infer_label(adapter: Any) -> str:
        """Best-effort plain-string identity for the report — never
        stores a raw `AdapterDescribe` object in `ScoreDetail.detail`
        (which is meant to stay JSON-serializable end to end)."""
        describe = getattr(adapter, "describe", None)
        if describe is None:
            return "unknown"
        try:
            info = describe()
        except Exception:  # noqa: BLE001 - identity lookup must never break scoring
            return "unknown"
        model = getattr(info, "model", None)
        return model or "unknown"

    def score_output(self, output_text: str, context_text: str = "") -> ScoreDetail:
        """One judge call, normalized. Never raises: an adapter error,
        an unparseable judge answer, or an out-of-range rating all
        degrade to a real `ScoreDetail` with `value=None`/an `error`
        or `detail["parse_error"]`, never an exception — the same
        "score what happened, don't abort the run" discipline as
        `Scorer.score()` itself (this method is what a `Scorer.fn`
        built from `as_scorer()` actually calls, so this IS where that
        discipline has to live)."""
        prompt = build_judge_prompt(output_text, context_text, rubric_prompt=self.rubric_prompt)
        result = self.adapter.generate(prompt, system=None, schema=None, max_tokens=200, temperature=0.0)
        if getattr(result, "error", None):
            return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                                error=f"judge adapter error: {result.error}")
        parsed = getattr(result, "parsed", None)
        if not isinstance(parsed, dict):
            parsed = _extract_json_object(getattr(result, "text", "") or "")
        if not isinstance(parsed, dict):
            return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                                detail={"parse_error": "judge did not return a JSON object",
                                        "raw_text": getattr(result, "text", "")})
        axis_scores = {axis: _normalize_axis_score(parsed.get(axis)) for axis in self.axes}
        scoreable = [v for v in axis_scores.values() if v is not None]
        composite = statistics.mean(scoreable) if scoreable else None
        return ScoreDetail(
            scorer_id="", scorer_version="", value=composite, passed=None,
            detail={
                "axis_scores": axis_scores, "reason": parsed.get("reason"),
                "judge_model": self.judge_model_label, "rubric_version": self.rubric_version,
                "raw_ratings": {axis: parsed.get(axis) for axis in self.axes},
            },
        )

    def as_scorer(self, scorer_id: str = "judge_dialogue_quality", category: str = "dialogue",
                   description: str | None = None) -> Scorer:
        def _fn(case, result: CaseResult, context: dict) -> ScoreDetail:
            output_text = " ".join(v for v in (result.output or {}).values() if isinstance(v, str) and v.strip())
            context_text = context.get("context_text") or ""
            return self.score_output(output_text, context_text)

        return Scorer(
            id=scorer_id, version=f"rubric-{self.rubric_version}", fn=_fn, tier=2, category=category,
            description=description or "LLM-judge rating of naturalness/personality/emotional realism against a fixed rubric.",
        )


def measure_self_consistency(judge: JudgeScorer, output_text: str, context_text: str = "", n: int = 3) -> dict:
    """"Self-consistency measured by re-scoring a sample" (A4.2): calls
    the SAME judge on the SAME output `n` times and reports the spread
    — a judge that gives wildly different composite scores for an
    unchanged input is unreliable, and this is the number that would
    say so. `n < 2` raises `ValueError` (a spread needs at least two
    samples to mean anything). Never itself hides a per-call error —
    `runs` carries every individual `ScoreDetail` verbatim, including
    any that failed, so a caller can see WHY consistency was low, not
    just that it was."""
    if n < 2:
        raise ValueError("measure_self_consistency needs n >= 2 to measure a spread")
    runs = [judge.score_output(output_text, context_text) for _ in range(n)]
    composite_values = [r.value for r in runs if r.value is not None]
    if len(composite_values) < 2:
        return {"runs": runs, "n_scored": len(composite_values), "mean": None, "stdev": None, "agreement": None}
    mean = statistics.mean(composite_values)
    stdev = statistics.pstdev(composite_values)
    return {
        "runs": runs, "n_scored": len(composite_values), "mean": mean, "stdev": stdev,
        "agreement": max(0.0, 1.0 - stdev),
    }
