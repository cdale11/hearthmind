#!/usr/bin/env python3
"""HearthBench A13 — prompt-regression CI guard (plus its A11 runner
dependency). Real production-path checks, no unittest, same
standalone-script convention as every sibling `verify_*.py`.

Exercises the real end-to-end path: a real local stdlib HTTP server
(same `_CapturingHandler` technique `verify_a2_model_adapters.py`/
`verify_a4_scoring.py` established) standing in for a live model,
through the REAL `OpenAICompatAdapter`, driving REAL grounding bait
cases through the REAL runner (`hearthbench.runner.run`) and REAL
threshold checking (`hearthbench.reporting.ci_guard`, built on A0.2's
already-real `eval_harness.check_regressions`).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.adapters import OpenAICompatAdapter
from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.reporting.ci_guard import (
    DEFAULT_CI_THRESHOLDS,
    build_default_ci_cases,
    is_relevant_change,
    load_baseline,
    run_ci_guard,
    save_baseline,
)
from hearthbench.runner.run import (
    aggregate_scores,
    render_case_prompt,
    run_case_against_adapter,
    run_cases_against_adapter,
    summaries_to_metrics_dict,
)
from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.tests import GROUNDING_CATEGORY

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


class _CapturingHandler(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            self.server.last_request_json = json.loads(body) if body else None
        except json.JSONDecodeError:
            self.server.last_request_json = None
        self.server.request_count += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        content = self.server.answer_fn(self.server.last_request_json) if self.server.answer_fn else self.server.canned_content
        self.wfile.write(json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8"))

    def do_POST(self):
        self._handle()

    def log_message(self, *args):  # noqa: D401 - silence stdlib access logging
        pass


def _start_fake_server(canned_content: str = "", answer_fn=None) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_content = canned_content
    server.answer_fn = answer_fn
    server.request_count = 0
    server.last_request_json = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _adapter_for(server: HTTPServer) -> OpenAICompatAdapter:
    return OpenAICompatAdapter(endpoint=f"http://{server.server_address[0]}:{server.server_address[1]}/v1", model="fake-ci-model")


def main() -> int:
    # --- A13.1: trigger --------------------------------------------------------
    check("is_relevant_change: a change under hearthmind/llm/ triggers", is_relevant_change(["hearthmind/llm/cognition.py"]))
    check("is_relevant_change: a change under hearthbench/prompts/ triggers", is_relevant_change(["hearthbench/prompts/schema.py"]))
    check("is_relevant_change: a change under hearthbench/scoring/ triggers", is_relevant_change(["hearthbench/scoring/deterministic.py"]))
    check("is_relevant_change: an unrelated change does not trigger", not is_relevant_change(["README.md", "hearthmind/world/farms.py"]))
    check("is_relevant_change: no changes at all does not trigger", not is_relevant_change([]))
    check("is_relevant_change: a mix with one relevant file still triggers", is_relevant_change(["README.md", "hearthmind/llm/dialogue.py"]))

    # --- A11 runner slice: render_case_prompt -----------------------------------
    turn_case = TestCase(id="x", category="grounding", turns=[Turn(index=0, content="first"), Turn(index=1, content="last one")])
    prompt, system_prompt, structured_input = render_case_prompt(turn_case)
    check("render_case_prompt: a turns-carrying case sends its LAST turn's content", prompt == "last one")
    check("render_case_prompt: no fixture involved means empty structured_input", structured_input == {})

    class _FakeFixture:
        prompt = "fixture prompt text"
        system_prompt = "fixture system"
        structured_input = {"real": "data"}

    fixture_case = TestCase(id="y", category="structured_outputs", fixture_ref="fx-1")
    fx_prompt, fx_system, fx_input = render_case_prompt(fixture_case, fixtures_by_id={"fx-1": _FakeFixture()})
    check("render_case_prompt: a fixture_ref-carrying case resolves through fixtures_by_id", fx_prompt == "fixture prompt text")
    check("render_case_prompt: fixture's own structured_input is threaded through", fx_input == {"real": "data"})

    empty_case = TestCase(id="z", category="structured_outputs", schema_ref="cognition")
    empty_prompt, _, _ = render_case_prompt(empty_case)
    check("render_case_prompt: a case with neither turns nor a resolvable fixture returns None, never fabricates a prompt",
          empty_prompt is None)

    # --- A11 runner: run_case_against_adapter / run_cases_against_adapter -------
    grounding_cases = build_default_ci_cases()
    check("build_default_ci_cases: reuses the real 4 grounding bait cases", len(grounding_cases) == 4)

    clean_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}))
    try:
        adapter = _adapter_for(clean_server)
        scored = run_case_against_adapter(grounding_cases[0], adapter, DEFAULT_REGISTRY)
        check("run_case_against_adapter: a real case run against a real server produces real ScoreDetails",
              scored is not None and "leak_freedom" in scored)
        check("run_case_against_adapter: a real HTTP request actually reached the fake server", clean_server.request_count == 1)
        check("run_case_against_adapter: an honest hedge answer passes no_unsupported_specifics",
              scored["no_unsupported_specifics"].passed is True)

        skip_case = TestCase(id="no-prompt", category="structured_outputs", schema_ref="cognition")
        skip_result = run_case_against_adapter(skip_case, adapter, DEFAULT_REGISTRY)
        check("run_case_against_adapter: an unrenderable case is skipped (None), not a crash or a fabricated result",
              skip_result is None)
        check("skipping a case makes no real HTTP call", clean_server.request_count == 1)

        all_results = run_cases_against_adapter(grounding_cases, adapter, DEFAULT_REGISTRY)
        check("run_cases_against_adapter: all 4 real cases produce real results", len(all_results) == 4 and all(v is not None for v in all_results.values()))
        check("run_cases_against_adapter: real request count matches (1 already spent + 4 new)", clean_server.request_count == 5)
    finally:
        clean_server.shutdown()

    # --- aggregate_scores / summaries_to_metrics_dict ----------------------------
    cases_by_id = {c.id: c for c in grounding_cases}
    summaries = aggregate_scores(all_results, cases_by_id)
    check("aggregate_scores: real grounding scorers grouped under the real category id", "grounding" in summaries)
    check("aggregate_scores: no_unsupported_specifics is one of the real grouped scorers", "no_unsupported_specifics" in summaries["grounding"])
    check("aggregate_scores: a real CategoryScoreSummary has a real n_total matching the case count",
          summaries["grounding"]["no_unsupported_specifics"].n_total == 4)

    metrics = summaries_to_metrics_dict(summaries)
    check("summaries_to_metrics_dict: real nested dotted-path-ready dict shape", metrics["grounding"]["no_unsupported_specifics"]["pass_rate"] is not None)
    check("a real clean-answer run yields a perfect pass rate (all 4 hedge cleanly)",
          metrics["grounding"]["no_unsupported_specifics"]["pass_rate"] == 1.0, str(metrics["grounding"]["no_unsupported_specifics"]))

    # --- A13.3: check_regressions reuse (via run_ci_guard) -----------------------
    with tempfile.TemporaryDirectory() as tmp:
        baseline_path = os.path.join(tmp, "baseline.json")

        # No relevant change -> the guard genuinely does nothing (no adapter call at all).
        no_change_server = _start_fake_server(canned_content="{}")
        try:
            noop_result = run_ci_guard(["README.md"], _adapter_for(no_change_server), DEFAULT_REGISTRY, baseline_path)
            check("run_ci_guard: an irrelevant change is a real no-op", noop_result.ran is False and no_change_server.request_count == 0)
        finally:
            no_change_server.shutdown()

        # A relevant change with a real clean model -> passes.
        clean_result_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}))
        try:
            clean_result = run_ci_guard(["hearthmind/llm/cognition.py"], _adapter_for(clean_result_server), DEFAULT_REGISTRY, baseline_path)
            check("run_ci_guard: a relevant change genuinely runs the real cases", clean_result.ran is True and clean_result.n_cases_run == 4)
            check("run_ci_guard: a clean model passes every default threshold", clean_result.passed is True, str(clean_result.violations))
        finally:
            clean_result_server.shutdown()

        # A relevant change with a real fabricating model -> a real violation is caught.
        fabricating_server = _start_fake_server(canned_content=json.dumps(
            {"reason": "Exactly 92 people, led by Bartholomew, in a town called Ravenhollow, since 1743."}
        ))
        try:
            bad_result = run_ci_guard(["hearthmind/llm/cognition.py"], _adapter_for(fabricating_server), DEFAULT_REGISTRY, baseline_path)
            check("run_ci_guard: a real confidently-fabricating model FAILS the guard", bad_result.passed is False)
            check("run_ci_guard: the real violation names the real gated metric",
                  any("no_unsupported_specifics" in v for v in bad_result.violations), str(bad_result.violations))
        finally:
            fabricating_server.shutdown()

        # --- A13.4: baseline save/load ---------------------------------------
        check("load_baseline: a missing baseline file degrades to {} rather than raising", load_baseline(baseline_path) == {})
        save_baseline(clean_result.metrics, baseline_path)
        loaded = load_baseline(baseline_path)
        check("save_baseline/load_baseline: a real baseline round-trips byte-for-byte in structure",
              loaded == clean_result.metrics)

        # A custom threshold dict (as a caller might derive from a loaded baseline) is honored, not ignored.
        custom_thresholds = {"grounding.no_unsupported_specifics.pass_rate": {"min": 0.99}}
        marginal_server = _start_fake_server(canned_content=json.dumps({"reason": "About 300, give or take."}))
        try:
            marginal_result = run_ci_guard(
                ["hearthmind/llm/dialogue.py"], _adapter_for(marginal_server), DEFAULT_REGISTRY, baseline_path,
                thresholds=custom_thresholds,
            )
            check("run_ci_guard: a caller-supplied threshold dict is genuinely used, not the default", marginal_result.passed is False)
        finally:
            marginal_server.shutdown()

    check("DEFAULT_CI_THRESHOLDS names only objective (grounding/structured_outputs) metrics, per A13.2",
          all(k.startswith("grounding.") or k.startswith("structured_outputs.") for k in DEFAULT_CI_THRESHOLDS))
    check("GROUNDING_CATEGORY is the real category the default CI cases belong to",
          all(c.category == GROUNDING_CATEGORY.id for c in grounding_cases))

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
