"""HearthBench A6.3 — score both constrained and unconstrained decoding
modes when supported, report the delta.

Runs ONE case through the adapter TWICE — once schema-constrained
(A6.1's `resolve_schema` against `TestCase.schema_ref`), once
unconstrained (`schema=None`, the runner's own pre-A6.1 default) — and
scores each independently, so a caller can see exactly what grammar
constraint bought or cost on this specific case, not just assume it
helped. Genuinely opt-in, distinct from the fast default single-call
path `run_case_against_adapter`/`run_cases_with_resume` still use for
an ordinary full-suite run — issuing two real calls per case is real
extra cost a caller should choose, not something every run pays.

Import isolation (A1.2): `hearthbench.*` only.
"""
from __future__ import annotations

from hearthbench.runner.run import render_case_prompt
from hearthbench.scoring.types import CaseResult
from hearthbench.validation.schema_resolver import resolve_schema


def run_case_dual_mode(
    case, adapter, registry, fixtures_by_id: "dict | None" = None, context: "dict | None" = None,
    max_tokens: "int | None" = 300, temperature: "float | None" = 0.0,
) -> "dict | None":
    """Returns `None` (an honest skip, matching `run_case_against_
    adapter`'s own contract) when the case has no renderable prompt.
    Otherwise returns `{"constrained_supported", "unconstrained",
    "constrained", "delta"}` — `constrained_supported` is `False` (never
    a fabricated comparison) whenever the case names no `schema_ref` or
    the adapter's own `capabilities().json_schema` says it can't do
    constrained decoding at all; `constrained`/`delta` are then real
    `None`s, and only `unconstrained` (the one call every adapter can
    always make) is populated. `delta[scorer_id]` is `constrained_
    score - unconstrained_score`, computed only where BOTH modes
    produced a real numeric `ScoreDetail.value` for that scorer —
    `None` otherwise, never a guessed number."""
    prompt, system_prompt, structured_input = render_case_prompt(case, fixtures_by_id)
    if prompt is None:
        return None

    schema = resolve_schema(getattr(case, "schema_ref", None))
    caps = adapter.capabilities()
    supported = schema is not None and bool(getattr(caps, "json_schema", False))
    task = case.task if hasattr(case, "task") else case.category
    scorers = registry.resolve(case.scorers)

    def _run_and_score(use_schema: bool) -> dict:
        result = adapter.generate(
            prompt, system=system_prompt, schema=(schema if use_schema else None),
            max_tokens=max_tokens, temperature=temperature,
        )
        case_result = CaseResult.from_adapter_result(task, structured_input, result)
        scored = {scorer.id: scorer.score(case, case_result, context) for scorer in scorers}
        return {"case_result": case_result, "scores": scored}

    unconstrained = _run_and_score(False)
    if not supported:
        return {"constrained_supported": False, "unconstrained": unconstrained, "constrained": None, "delta": None}

    constrained = _run_and_score(True)
    delta: dict = {}
    for scorer_id, unconstrained_detail in unconstrained["scores"].items():
        constrained_detail = constrained["scores"].get(scorer_id)
        u_val = unconstrained_detail.value
        c_val = constrained_detail.value if constrained_detail is not None else None
        delta[scorer_id] = (c_val - u_val) if (u_val is not None and c_val is not None) else None
    return {"constrained_supported": True, "unconstrained": unconstrained, "constrained": constrained, "delta": delta}
