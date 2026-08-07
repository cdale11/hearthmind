#!/usr/bin/env python3
"""HearthBench A5 — Benchmark categories (the objective slice: A5.7
Grounding, A5.8 Structured Outputs, A5.9 Performance, plus the shared
A5-scoped category-aggregation infra and A5.10's guide/template).
Real production-path checks, no unittest, same standalone-script
convention as every sibling `verify_*.py`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.prompts.schema import TestCase, render_turn_sequence
from hearthbench.scoring.types import CaseResult, ScoreDetail
from hearthbench.tests import (
    CATEGORY_REGISTRY,
    GROUNDING_CATEGORY,
    NO_UNSUPPORTED_SPECIFICS_SCORER,
    PERFORMANCE_CATEGORY,
    STRUCTURED_OUTPUTS_CATEGORY,
    build_grounding_bait_cases,
    build_structured_output_cases,
    score_structured_output_delta,
    percentile,
    summarize_latency,
    summarize_scores,
)
from hearthbench.tests.category import CategoryScoreSummary
from hearthmind.llm.json_schemas import TASK_SCHEMAS

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def main() -> int:
    # --- CATEGORY_REGISTRY ---------------------------------------------------
    check("CATEGORY_REGISTRY has exactly the 3 objective categories shipped this pass",
          set(CATEGORY_REGISTRY) == {"grounding", "structured_outputs", "performance"}, str(sorted(CATEGORY_REGISTRY)))
    check("grounding is weighted highest, matching A10.1's own stated default table",
          GROUNDING_CATEGORY.weight == max(c.weight for c in CATEGORY_REGISTRY.values()))
    check("performance is weighted lowest, matching A10.1's own stated default table",
          PERFORMANCE_CATEGORY.weight == min(c.weight for c in CATEGORY_REGISTRY.values()))

    # --- percentile / summarize_scores (shared A5 infra) ----------------------
    check("percentile: median of an odd-length sorted list", percentile([1, 2, 3, 4, 5], 0.5) == 3)
    check("percentile: min at p0", percentile([1, 2, 3], 0.0) == 1)
    check("percentile: max at p1", percentile([1, 2, 3], 1.0) == 3)
    check("percentile: single-element list returns that element", percentile([7], 0.95) == 7)
    percentile_raised = False
    try:
        percentile([], 0.5)
    except ValueError:
        percentile_raised = True
    check("percentile: empty list raises rather than fabricating a value", percentile_raised)

    empty_summary = summarize_scores("grounding", [])
    check("summarize_scores: empty input degrades to all-None stats, not a crash",
          empty_summary.n_total == 0 and empty_summary.mean is None and empty_summary.p95 is None)

    all_none_details = [ScoreDetail(scorer_id="latency", scorer_version="1", value=None, detail={"latency_ms": 100})]
    all_none_summary = summarize_scores("performance", all_none_details)
    check("summarize_scores: a measurement-only scorer (value=None) contributes to n_total but not n_scored",
          all_none_summary.n_total == 1 and all_none_summary.n_scored == 0)

    real_details = [
        ScoreDetail(scorer_id="x", scorer_version="1", value=v, passed=(v >= 0.5))
        for v in [0.2, 0.4, 0.6, 0.8, 1.0]
    ]
    real_summary = summarize_scores("grounding", real_details)
    check("summarize_scores: real mean matches hand computation", abs(real_summary.mean - 0.6) < 1e-9, str(real_summary.mean))
    check("summarize_scores: real median matches hand computation", real_summary.median == 0.6)
    check("summarize_scores: n_passed/n_failed/pass_rate computed from real passed flags",
          real_summary.n_passed == 3 and real_summary.n_failed == 2 and abs(real_summary.pass_rate - 0.6) < 1e-9)
    check("summarize_scores: stdev is a real nonzero spread for varied inputs", real_summary.stdev > 0)
    check("summarize_scores: 95% CI is a real (lower, upper) bracketing the mean",
          real_summary.confidence_interval_95 is not None
          and real_summary.confidence_interval_95[0] < real_summary.mean < real_summary.confidence_interval_95[1])
    single_summary = summarize_scores("grounding", real_details[:1])
    check("summarize_scores: a single sample has no CI (needs 2+ to estimate spread)",
          single_summary.confidence_interval_95 is None and single_summary.stdev == 0.0)

    # --- A5.7 Grounding --------------------------------------------------------
    bait_cases = build_grounding_bait_cases()
    check("build_grounding_bait_cases: 4 real hand-authored adversarial cases", len(bait_cases) == 4)
    check("every bait case carries a real single Turn (the bait question)",
          all(len(c.turns) == 1 for c in bait_cases))
    check("every bait case is tagged adversarial", all("adversarial" in c.tags for c in bait_cases))
    check("every bait case names what its own context withholds via expected_invariants",
          all(c.expected_invariants for c in bait_cases))
    rendered = render_turn_sequence(bait_cases[0])
    check("a bait case's rendered turn sequence carries the real bait question",
          len(rendered) == 1 and "marshcroft" in rendered[0]["content"].lower())

    clean_result = CaseResult(task="cognition", output={"reason": "It has not been counted yet."},
                               structured_input={"settlement": "Marshcroft"})
    hedge_detail = NO_UNSUPPORTED_SPECIFICS_SCORER.score(bait_cases[0], clean_result)
    check("no_unsupported_specifics: an honest hedge with no invented specifics passes",
          hedge_detail.passed is True and hedge_detail.value == 1.0)

    fabricated_result = CaseResult(task="cognition", output={"reason": "There are exactly Ninety-two people living here."},
                                    structured_input={"settlement": "Marshcroft"})
    fab_detail = NO_UNSUPPORTED_SPECIFICS_SCORER.score(bait_cases[0], fabricated_result)
    check("no_unsupported_specifics: a confidently fabricated new name is caught",
          fab_detail.passed is False and "Ninety" in fab_detail.detail["unsupported"])

    number_result = CaseResult(task="cognition", output={"reason": "About 300, give or take."},
                                structured_input={"settlement": "Marshcroft"})
    num_detail = NO_UNSUPPORTED_SPECIFICS_SCORER.score(bait_cases[0], number_result)
    check("no_unsupported_specifics: a fabricated specific number is caught",
          num_detail.passed is False and "300" in num_detail.detail["unsupported"])

    supported_result = CaseResult(task="cognition", output={"reason": "As always, Marshcroft carries on."},
                                   structured_input={"settlement": "Marshcroft"})
    supported_detail = NO_UNSUPPORTED_SPECIFICS_SCORER.score(bait_cases[0], supported_result)
    check("no_unsupported_specifics: restating a name genuinely present in structured_input is not penalized",
          supported_detail.passed is True, str(supported_detail.detail))

    heavy_fab_result = CaseResult(
        task="cognition",
        output={"reason": "Exactly 92 people, led by Bartholomew, in a town called Ravenhollow, since 1743."},
        structured_input={"settlement": "Marshcroft"},
    )
    heavy_detail = NO_UNSUPPORTED_SPECIFICS_SCORER.score(bait_cases[0], heavy_fab_result)
    check("no_unsupported_specifics: heavy fabrication is capped, not an unbounded free-fall to a huge negative",
          heavy_detail.value == 0.0 and len(heavy_detail.detail["unsupported"]) >= 3)

    empty_output_detail = NO_UNSUPPORTED_SPECIFICS_SCORER.score(bait_cases[0], CaseResult(task="cognition", output={}, structured_input={}))
    check("no_unsupported_specifics: a genuinely empty output makes no claims -> clean pass",
          empty_output_detail.value == 1.0 and empty_output_detail.passed is True)

    # --- A5.8 Structured Outputs -------------------------------------------
    so_cases = build_structured_output_cases()
    check("build_structured_output_cases: 2 variants (grammar/no_grammar) per real registered task schema",
          len(so_cases) == 2 * len(TASK_SCHEMAS), f"{len(so_cases)} vs {2 * len(TASK_SCHEMAS)}")
    check("every structured-output case's schema_ref names a real registered task",
          all(c.schema_ref in TASK_SCHEMAS for c in so_cases))
    check("every case's scorers match STRUCTURED_OUTPUTS_CATEGORY's own declared scorer_ids",
          all(c.scorers == list(STRUCTURED_OUTPUTS_CATEGORY.scorer_ids) for c in so_cases))
    check("CATEGORY_REGISTRY['structured_outputs'] is the real same object the module exports",
          CATEGORY_REGISTRY["structured_outputs"] is STRUCTURED_OUTPUTS_CATEGORY)
    grammar_cases = [c for c in so_cases if "grammar" in c.tags and "no_grammar" not in c.tags]
    no_grammar_cases = [c for c in so_cases if "no_grammar" in c.tags]
    check("exactly half the cases are grammar-tagged, half no_grammar-tagged",
          len(grammar_cases) == len(no_grammar_cases) == len(TASK_SCHEMAS))
    check("adding a task to TASK_SCHEMAS grows the case set automatically (no hardcoded task list here)",
          "cognition" in {c.schema_ref for c in so_cases} and "dialogue" in {c.schema_ref for c in so_cases})

    with_grammar_summary = CategoryScoreSummary(category_id="structured_outputs", n_total=10, n_scored=10, n_passed=9, n_failed=1, pass_rate=0.9)
    without_grammar_summary = CategoryScoreSummary(category_id="structured_outputs", n_total=10, n_scored=10, n_passed=6, n_failed=4, pass_rate=0.6)
    delta = score_structured_output_delta(with_grammar_summary, without_grammar_summary)
    check("score_structured_output_delta: a real 0.3 pass-rate gap computed correctly", abs(delta["pass_rate_delta"] - 0.3) < 1e-9)
    check("score_structured_output_delta: grammar_helps is True when it genuinely does", delta["grammar_helps"] is True)

    reversed_delta = score_structured_output_delta(without_grammar_summary, with_grammar_summary)
    check("score_structured_output_delta: grammar_helps is False the other direction",
          reversed_delta["grammar_helps"] is False and reversed_delta["pass_rate_delta"] < 0)

    no_data_summary = CategoryScoreSummary(category_id="structured_outputs", n_total=0, n_scored=0)
    no_data_delta = score_structured_output_delta(no_data_summary, with_grammar_summary)
    check("score_structured_output_delta: missing pass-rate data degrades to None, not a fabricated 0", no_data_delta["pass_rate_delta"] is None)

    # --- A5.9 Performance --------------------------------------------------
    latency_details = [
        ScoreDetail(scorer_id="latency", scorer_version="1", value=None,
                    detail={"latency_ms": ms, "ttft_ms": ms * 0.3, "completion_tokens": 40})
        for ms in [100.0, 200.0, 300.0, 400.0, 5000.0]
    ]
    perf = summarize_latency(latency_details)
    check("summarize_latency: real p50 matches hand computation", perf["latency_ms"]["p50"] == 300.0, str(perf["latency_ms"]))
    check("summarize_latency: real max captures the real outlier", perf["latency_ms"]["max"] == 5000.0)
    check("summarize_latency: n reflects every real sample with a latency reading", perf["latency_ms"]["n"] == 5)
    check("summarize_latency: TTFT stats computed independently from the same real details", perf["ttft_ms"]["n"] == 5 and perf["ttft_ms"]["max"] == 1500.0)
    check("summarize_latency: real completion tok/s computed from latency_ms + completion_tokens",
          perf["completion_tokens_per_sec"]["n"] == 5 and perf["completion_tokens_per_sec"]["mean"] > 0)

    empty_perf = summarize_latency([])
    check("summarize_latency: empty input degrades to real None stats, not a crash",
          empty_perf["latency_ms"]["p50"] is None and empty_perf["n_total"] == 0)

    no_token_details = [ScoreDetail(scorer_id="latency", scorer_version="1", value=None, detail={"latency_ms": 50.0})]
    no_token_perf = summarize_latency(no_token_details)
    check("summarize_latency: latency present but no token counts -> tok/s stays honestly empty, not a fabricated rate",
          no_token_perf["completion_tokens_per_sec"]["n"] == 0 and no_token_perf["latency_ms"]["n"] == 1)

    # --- A5.10: template/guide exist and the template is a real, importable, unregistered module ---
    import importlib
    template = importlib.import_module("hearthbench.tests._template")
    check("A5.10 template module imports cleanly", hasattr(template, "TEMPLATE_CATEGORY") and hasattr(template, "build_template_cases"))
    check("A5.10 template category is deliberately NOT in the real CATEGORY_REGISTRY",
          template.TEMPLATE_CATEGORY.id not in CATEGORY_REGISTRY)
    guide_path = os.path.join(os.path.dirname(__file__), "..", "docs", "HEARTHBENCH-CATEGORY-GUIDE.md")
    check("A5.10 guide doc exists on disk", os.path.isfile(guide_path))

    # A single-shot TestCase with no turns still renders cleanly (structured_outputs.py's own shape).
    single_shot = TestCase(id="x", category="structured_outputs", schema_ref="cognition", scorers=["schema_validity"])
    check("a fixture-less, turn-less TestCase (structured_outputs.py's real shape) renders to an empty turn sequence",
          render_turn_sequence(single_shot) == [])

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
