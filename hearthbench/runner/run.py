"""HearthBench A11 (partial) — the minimal real slice A13 needs.

A11's own checklist (quick/full/custom run modes, resume, strict-
repro) is NOT built here — this ships only the one mechanism every
later A11 mode would share: given a `TestCase`, resolve what to
actually SEND to an adapter, call it, and score the result against a
`ScorerRegistry`. A13 (the CI regression guard) genuinely needs this
today; the fuller run-mode abstraction around it (progress tracking,
resume-by-skipping-completed-ids, category subsetting) stays real,
distinct, unstarted future work — see `hearthbench/runner/__init__.py`.

`render_case_prompt` is honest about what it can and can't do: a
`turns`-carrying case (A3.3's shape) sends only its LAST turn's
`content` as a single-shot prompt — real multi-turn conversation state
(injecting `render_turn_sequence`'s own accumulated `context` into a
chat history) is real future work, not attempted; a `fixture_ref`-
carrying case resolves against a caller-supplied `fixtures_by_id` map
(A3.1's own fixture packs); a case with neither (e.g. `structured_
outputs.py`'s placeholder cases, which intentionally carry no prompt
text of their own — see that module's own docstring) has nothing to
send and is skipped, never crashed on or silently faked.

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring` only — no `hearthmind.simulation`/`.agents`/`.world`.
"""
from __future__ import annotations

from hearthbench.prompts.schema import render_turn_sequence
from hearthbench.scoring.types import CaseResult


def render_case_prompt(case, fixtures_by_id: dict | None = None) -> tuple:
    """`(prompt, system_prompt, structured_input)` — any element may be
    `None`/`{}` when unresolvable. `prompt is None` is the caller's
    signal to skip this case rather than run it."""
    if case.turns:
        rendered = render_turn_sequence(case)
        if not rendered:
            return None, case.system_prompt, {}
        return rendered[-1]["content"], case.system_prompt, {}
    if case.fixture_ref and fixtures_by_id:
        fixture = fixtures_by_id.get(case.fixture_ref)
        if fixture is not None:
            return fixture.prompt, fixture.system_prompt, dict(fixture.structured_input)
    return None, case.system_prompt, {}


def run_case_against_adapter(
    case, adapter, registry, fixtures_by_id: dict | None = None, context: dict | None = None,
    max_tokens: int | None = 300, temperature: float | None = 0.0,
) -> dict | None:
    """One case, one real `adapter.generate()` call (A2's `ModelAdapter`
    Protocol — duck-typed, no import of `hearthbench.adapters`), scored
    against every scorer `registry.resolve(case.scorers)` finds.
    Returns `None` (skip, not a fabricated empty result) when the case
    has no renderable prompt. Never raises: an adapter error still
    produces a real `CaseResult` (`AdapterResult.error` is threaded
    through), and each scorer's own `Scorer.score()` already degrades
    to an error `ScoreDetail` rather than propagating an exception."""
    prompt, system_prompt, structured_input = render_case_prompt(case, fixtures_by_id)
    if prompt is None:
        return None
    schema = None
    result = adapter.generate(prompt, system=system_prompt, schema=schema, max_tokens=max_tokens, temperature=temperature)
    case_result = CaseResult.from_adapter_result(case.task if hasattr(case, "task") else case.category, structured_input, result)
    scorers = registry.resolve(case.scorers)
    return {scorer.id: scorer.score(case, case_result, context) for scorer in scorers}


def run_cases_against_adapter(
    cases: list, adapter, registry, fixtures_by_id: dict | None = None, context: dict | None = None,
) -> dict:
    """`{case_id: {scorer_id: ScoreDetail} | None}` — a case mapped to
    `None` means it was skipped (no renderable prompt), preserved in
    the output rather than silently dropped so a caller can report
    real coverage gaps."""
    results = {}
    for case in cases:
        results[case.id] = run_case_against_adapter(case, adapter, registry, fixtures_by_id, context)
    return results


def aggregate_scores(case_results: dict, cases_by_id: dict) -> dict:
    """Groups every real `ScoreDetail` by `(category, scorer_id)` —
    matches the checklist's own "per category" framing at the finer
    per-scorer grain a category's several scorers each need (a
    category is rarely backed by exactly one scorer, see `grounding.
    py`'s four). Returns `{category_id: {scorer_id: CategoryScore
    Summary}}`, built via `hearthbench.tests.category.summarize_
    scores` — the shared A5 aggregation infra, not a second one."""
    from hearthbench.tests.category import summarize_scores

    grouped: dict = {}
    for case_id, scorer_results in case_results.items():
        if not scorer_results:
            continue
        case = cases_by_id.get(case_id)
        if case is None:
            continue
        for scorer_id, detail in scorer_results.items():
            grouped.setdefault(case.category, {}).setdefault(scorer_id, []).append(detail)

    summaries: dict = {}
    for category_id, by_scorer in grouped.items():
        summaries[category_id] = {
            scorer_id: summarize_scores(category_id, details) for scorer_id, details in by_scorer.items()
        }
    return summaries


def summaries_to_metrics_dict(summaries: dict) -> dict:
    """Flattens `{category: {scorer: CategoryScoreSummary}}` into the
    plain nested-dict-of-numbers shape `hearthmind.llm.eval_harness.
    check_regressions` already knows how to walk via dotted paths
    (e.g. `"grounding.leak_freedom.pass_rate"`) — real reuse of A0.2's
    existing threshold checker (A13.3's own stated instruction),
    rather than a second regression-comparison mechanism."""
    metrics: dict = {}
    for category_id, by_scorer in summaries.items():
        metrics[category_id] = {}
        for scorer_id, summary in by_scorer.items():
            metrics[category_id][scorer_id] = {
                "mean": summary.mean, "pass_rate": summary.pass_rate,
                "n_scored": summary.n_scored, "n_total": summary.n_total,
            }
    return metrics
