"""HearthBench A11 (partial) — the minimal real slice A13 needed, plus
A11.4 (resume), built directly on A8's real run record.

A11's fuller run-mode abstraction (quick/full/custom, strict-repro) is
still NOT built here — this ships the one mechanism every later A11
mode would share: given a `TestCase`, resolve what to actually SEND to
an adapter, call it, and score the result against a `ScorerRegistry`
— plus, this pass, `run_cases_with_resume`, which threads that same
mechanism through A8's `RunRecordWriter`/`RunRecordReader` so a run
interrupted mid-way can be re-invoked against the same `run_dir` and
pick up exactly where it left off, per the checklist's own literal
words ("every completed case commits immediately; resume = skip
completed IDs"). Progress tracking/category subsetting/strict-repro
stay real, distinct, unstarted future work — see `hearthbench/
runner/__init__.py`.

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
scoring`/`hearthbench.diagnostics` only — no `hearthmind.simulation`/
`.agents`/`.world`.
"""
from __future__ import annotations

from hearthbench.diagnostics.run_record import CaseRecord, RunRecordReader, RunRecordWriter
from hearthbench.prompts.schema import render_turn_sequence
from hearthbench.scoring.types import CaseResult
from hearthbench.validation.schema_resolver import resolve_schema


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


def _execute_case(
    case, adapter, registry, fixtures_by_id: dict | None, context: dict | None,
    max_tokens: int | None, temperature: float | None,
) -> "tuple | None":
    """The one real render→call→score sequence, shared by `run_case_
    against_adapter` and `run_cases_with_resume` (A11.4) so there is a
    single source of truth for "what does running one case actually
    do" — returns `None` (an honest skip) or `(prompt, adapter_result,
    case_result, structured_input, scored)`, where `scored` is
    `{scorer_id: ScoreDetail}`. Never raises for the same reasons `run_
    case_against_adapter`'s own docstring already gives (an adapter
    error still produces a real `CaseResult`; a scorer bug degrades to
    an error `ScoreDetail`)."""
    prompt, system_prompt, structured_input = render_case_prompt(case, fixtures_by_id)
    if prompt is None:
        return None
    # A6.1: a case naming a real hearthmind.llm.json_schemas task via
    # `schema_ref` now actually REQUESTS schema-constrained decoding,
    # not just gets scored afterward against that same schema (A4.1's
    # `schema_validity` already did the latter) -- `resolve_schema`
    # returns None for an unset/unrecognized ref, reproducing the
    # exact prior unconstrained call byte-for-byte.
    schema = resolve_schema(getattr(case, "schema_ref", None))
    result = adapter.generate(prompt, system=system_prompt, schema=schema, max_tokens=max_tokens, temperature=temperature)
    case_result = CaseResult.from_adapter_result(case.task if hasattr(case, "task") else case.category, structured_input, result)
    scorers = registry.resolve(case.scorers)
    scored = {scorer.id: scorer.score(case, case_result, context) for scorer in scorers}
    return prompt, result, case_result, structured_input, scored


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
    executed = _execute_case(case, adapter, registry, fixtures_by_id, context, max_tokens, temperature)
    if executed is None:
        return None
    _prompt, _result, _case_result, _structured_input, scored = executed
    return scored


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


def run_cases_with_resume(
    cases: list, adapter, registry, run_dir: str, fixtures_by_id: dict | None = None,
    context: dict | None = None, environment: dict | None = None,
    max_tokens: int | None = 300, temperature: float | None = 0.0,
) -> dict:
    """A11.4: resume, built directly on A8's real run record — "every
    completed case commits immediately; resume = skip completed IDs,"
    the checklist's own literal words. `run_dir` is a real directory: a
    first call creates it (and writes `environment`'s snapshot into
    `manifest.json`, once, if supplied); a SECOND call against the
    SAME `run_dir` — after a crash, a Ctrl-C, or just picking a paused
    benchmark back up — reads `RunRecordReader.completed_case_ids()`
    fresh off disk and skips every case already committed there,
    running only what's left. Each newly-run case's `CaseRecord` is
    committed to disk the instant it completes (never batched until
    the end), so a second interruption loses at most the one case that
    was in flight, never the whole call. Returns `{case_id: {scorer_id:
    ScoreDetail}}` for only the cases THIS call actually ran — a
    caller wanting the full run's results (including ones skipped as
    already-done) reads them back via `hearthbench.metrics.aggregate.
    recompute_run_metrics(run_dir)` or `RunRecordReader(run_dir).
    iter_case_records()` directly."""
    writer = RunRecordWriter(run_dir, environment=environment)
    already_done = RunRecordReader(run_dir).completed_case_ids()

    results: dict = {}
    for case in cases:
        if case.id in already_done:
            continue
        executed = _execute_case(case, adapter, registry, fixtures_by_id, context, max_tokens, temperature)
        if executed is None:
            continue
        prompt, result, case_result, structured_input, scored = executed
        results[case.id] = scored

        record = CaseRecord(
            case_id=case.id, category=case.category,
            prompt_hash=writer.blobs.put(prompt) if prompt else None,
            completion_hash=writer.blobs.put(result.text) if getattr(result, "text", None) else None,
            parsed_json=case_result.output or None,
            structured_input=structured_input,
            fallback_used=case_result.fallback_used, parse_repaired=case_result.parse_repaired,
            repair_rung=case_result.repair_rung, repair_reason=case_result.repair_reason,
            retries=case_result.retries, latency_ms=case_result.latency_ms, ttft_ms=case_result.ttft_ms,
            prompt_tokens=getattr(result, "prompt_tokens", None),
            completion_tokens=getattr(result, "completion_tokens", None),
            error=case_result.error,
            scores={scorer_id: detail.to_dict() for scorer_id, detail in scored.items()},
        )
        writer.commit_case(record)
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
