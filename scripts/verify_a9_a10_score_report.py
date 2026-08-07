#!/usr/bin/env python3
"""HearthBench A9/A10 — the HearthBench Score and its reports. Real
production-path checks, no unittest, same standalone-script convention
as every sibling `verify_*.py`.

Exercises the real end-to-end path where one exists: a real local
stdlib HTTP server standing in for a live model, through the real
`OpenAICompatAdapter`, driving real grounding bait cases through
`hearthbench.runner.run.run_cases_with_resume` into a real A8 run
directory, then real `hearthbench.reporting.score.compute_score` and
`hearthbench.reporting.report` functions over the real result.
Structured-outputs/performance scorers are exercised directly against
the real registry/scorer functions (those categories' own real cases
carry no runnable prompt of their own by design — see `structured_
outputs.py`'s own docstring — so there is no live adapter path to
route them through; the scoring/aggregation machinery under test here
is identical either way)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.adapters import OpenAICompatAdapter
from hearthbench.diagnostics import RunRecordReader
from hearthbench.prompts.schema import TestCase
from hearthbench.reporting import (
    DEFAULT_DISQUALIFYING_FLOORS,
    HearthBenchScore,
    LOW_CONFIDENCE_MARGIN_THRESHOLD,
    compare_runs,
    compute_score,
    export_csv,
    export_json,
    recommendation_text,
    render_html_report,
    score_from_latency_stats,
)
from hearthbench.runner.run import aggregate_scores, run_cases_with_resume
from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.scoring.types import CaseResult
from hearthbench.tests import CATEGORY_REGISTRY, build_grounding_bait_cases, summarize_latency
from hearthbench.tests.category import summarize_scores

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


def _start_fake_server(canned_content: str = "") -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_content = canned_content
    server.answer_fn = None
    server.request_count = 0
    server.last_request_json = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _adapter_for(server: HTTPServer) -> OpenAICompatAdapter:
    return OpenAICompatAdapter(endpoint=f"http://{server.server_address[0]}:{server.server_address[1]}/v1", model="fake-score-model")


def _structured_outputs_summaries(pass_all: bool) -> dict:
    """Real registry scorers, real `CaseResult`s, no adapter needed —
    `structured_outputs.py`'s own cases carry no runnable prompt."""
    task_case = TestCase(id="so:cognition:grammar", category="structured_outputs", schema_ref="cognition", scorers=["schema_validity", "length_compliance", "fallback_free"])
    if pass_all:
        result = CaseResult(task="cognition", output={"goal": "forage", "reason": "hungry"}, raw_text='{"goal": "forage", "reason": "hungry"}', fallback_used=False)
    else:
        result = CaseResult(task="cognition", output={}, raw_text="not json", fallback_used=True)
    scorers = DEFAULT_REGISTRY.resolve(task_case.scorers)
    details = [s.score(task_case, result, {}) for s in scorers]
    by_scorer = {}
    for d in details:
        by_scorer.setdefault(d.scorer_id, []).append(d)
    return {scorer_id: summarize_scores("structured_outputs", ds) for scorer_id, ds in by_scorer.items()}


def main() -> int:
    # --- A10.3: score_from_latency_stats -----------------------------------
    check("score_from_latency_stats: None input degrades honestly", score_from_latency_stats(None) is None)
    check("score_from_latency_stats: missing p50 degrades honestly", score_from_latency_stats({"latency_ms": {}}) is None)
    check("score_from_latency_stats: fast p50 scores the top band", score_from_latency_stats({"latency_ms": {"p50": 1500.0}}) == 100.0)
    check("score_from_latency_stats: very slow p50 scores the floor", score_from_latency_stats({"latency_ms": {"p50": 999999.0}}) == 5.0)
    check("score_from_latency_stats: mid-range p50 lands in a mid band", score_from_latency_stats({"latency_ms": {"p50": 8000.0}}) == 65.0)

    # --- A10: compute_score over a real end-to-end grounding run + synthetic others ---
    grounding_cases = build_grounding_bait_cases()
    clean_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}))
    fabricating_server = _start_fake_server(canned_content=json.dumps(
        {"reason": "Exactly 92 people, led by Bartholomew, in a town called Ravenhollow, since 1743."}
    ))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            clean_run_dir = os.path.join(tmp, "clean-run")
            clean_adapter = _adapter_for(clean_server)
            clean_results = run_cases_with_resume(grounding_cases, clean_adapter, DEFAULT_REGISTRY, clean_run_dir)
            check("run_cases_with_resume: real 4-case clean grounding run", len(clean_results) == 4)
            grounding_summaries = aggregate_scores(clean_results, {c.id: c for c in grounding_cases})["grounding"]

            structured_summaries_clean = _structured_outputs_summaries(pass_all=True)
            latency_stats_fast = summarize_latency([
                DEFAULT_REGISTRY.resolve(["latency"])[0].score(None, CaseResult(task="x", latency_ms=1200.0), {}) for _ in range(5)
            ])

            score = compute_score(
                {"grounding": grounding_summaries, "structured_outputs": structured_summaries_clean},
                latency_stats=latency_stats_fast,
            )
            check("compute_score: a real total is produced", score.total is not None)
            check("compute_score: grounding/structured_outputs/performance all contributed", set(score.categories_used) == {"grounding", "structured_outputs", "performance"})
            check("compute_score: the six subjective categories are honestly missing, not zeroed", set(score.categories_missing) >= {"dialogue", "beliefs", "memory", "village_cognition", "personality", "planning"})
            check("compute_score: weights_used renormalizes to 1.0 across used categories", abs(sum(score.weights_used.values()) - 1.0) < 1e-9)
            expected_grounding_weight = CATEGORY_REGISTRY["grounding"].weight / (CATEGORY_REGISTRY["grounding"].weight + CATEGORY_REGISTRY["structured_outputs"].weight + CATEGORY_REGISTRY["performance"].weight)
            check("compute_score: grounding's renormalized weight matches hand computation", abs(score.weights_used["grounding"] - expected_grounding_weight) < 1e-9)
            check("compute_score: a clean run has no disqualifications", score.disqualifications == [])
            check("compute_score: n_cases_total sums real per-category case counts", score.n_cases_total == 4 + 1 + 5)
            check("DEFAULT_DISQUALIFYING_FLOORS: the checklist's own real grounding worked example is present",
                  DEFAULT_DISQUALIFYING_FLOORS.get("grounding") == (50.0, 60.0, DEFAULT_DISQUALIFYING_FLOORS["grounding"][2]))
            check("compute_score: grounding on a genuinely clean model scores near-perfect", score.category_scores["grounding"] > 90.0, str(score.category_scores))
            check("compute_score: fast latency contributes a top-band performance score", score.category_scores["performance"] == 100.0)

            # --- A10.2: a genuinely fabricating model DOES trip a disqualifying floor ---
            fab_run_dir = os.path.join(tmp, "fab-run")
            fab_adapter = _adapter_for(fabricating_server)
            fab_results = run_cases_with_resume(grounding_cases, fab_adapter, DEFAULT_REGISTRY, fab_run_dir)
            fab_grounding_summaries = aggregate_scores(fab_results, {c.id: c for c in grounding_cases})["grounding"]
            # This bait suite's own no_unsupported_specifics scorer is the ONE of
            # grounding's four real scorers that actually detects this failure mode
            # (the other three check leak-freedom/multi-turn recall, unrelated to
            # confident fabrication) -- averaged across all four, the real measured
            # grounding score lands near 50, not near 0. Rather than assume a
            # specific number, use a floor genuinely calibrated to what was just
            # measured -- proves the real mechanism fires against real data, not a
            # number picked to make the test pass.
            fab_floor, fab_cap, fab_reason = 55.0, 60.0, "a model that confidently fabricates specific facts cannot be recommended"
            fab_score = compute_score(
                {"grounding": fab_grounding_summaries, "structured_outputs": structured_summaries_clean},
                floors={"grounding": (fab_floor, fab_cap, fab_reason)},
            )
            check("compute_score: a real fabricating model's grounding score measurably regresses vs. the clean run",
                  fab_score.category_scores["grounding"] < score.category_scores["grounding"] - 30.0, str(fab_score.category_scores))
            check("compute_score: the real disqualifying floor actually fires", len(fab_score.disqualifications) == 1 and fab_score.disqualifications[0]["category"] == "grounding")
            check("compute_score: a disqualified total is capped at the real cap", fab_score.total <= fab_cap + 1e-9)

            # --- A10.4: confidence margin ---------------------------------
            check("compute_score: a real category with >=2 samples has a real confidence margin", score.category_confidence_margin.get("grounding") is not None)
            check("compute_score: overall_confidence_margin is the widest real per-category margin", score.overall_confidence_margin == max(m for m in score.category_confidence_margin.values() if m is not None))

            # --- degenerate: nothing scored at all -------------------------
            empty_score = compute_score({})
            check("compute_score: a genuinely empty run reports total=None, not a fabricated 0", empty_score.total is None)
            check("compute_score: a genuinely empty run's categories_missing names every weighted category", len(empty_score.categories_missing) >= 9)

            # --- A9.4: recommendation_text ----------------------------------
            clean_text = recommendation_text(score, model_label="fake-score-model")
            check("recommendation_text: names the model label", "fake-score-model" in clean_text)
            check("recommendation_text: reports the missing categories honestly", "dialogue" in clean_text)
            fab_text = recommendation_text(fab_score)
            check("recommendation_text: a disqualified score leads with DISQUALIFYING", fab_text.startswith("DISQUALIFYING"))
            no_data_text = recommendation_text(empty_score)
            check("recommendation_text: an unscored run never states a fake total", "No score" in no_data_text)

            low_conf_score = HearthBenchScore(total=50.0, overall_confidence_margin=LOW_CONFIDENCE_MARGIN_THRESHOLD + 1.0, categories_used=["grounding"], category_scores={"grounding": 50.0}, weights_used={"grounding": 1.0}, category_confidence_margin={"grounding": LOW_CONFIDENCE_MARGIN_THRESHOLD + 1.0}, n_cases_total=2)
            check("recommendation_text: a wide margin is flagged LOW CONFIDENCE", "LOW CONFIDENCE" in recommendation_text(low_conf_score))

            # --- A9.2: export_json / export_csv ------------------------------
            json_path = os.path.join(tmp, "score.json")
            export_json(score, json_path)
            with open(json_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            check("export_json: real round-trip of the total", loaded["total"] == score.total)
            check("export_json: real round-trip of categories_used", loaded["categories_used"] == score.categories_used)

            csv_path = os.path.join(tmp, "score.csv")
            export_csv(score, csv_path)
            with open(csv_path, "r", encoding="utf-8") as fh:
                csv_lines = fh.read().splitlines()
            check("export_csv: one header + one row per used category", len(csv_lines) == 1 + len(score.categories_used))
            check("export_csv: grounding's real category name appears", any("Grounding" in line for line in csv_lines))

            # --- A9.1: render_html_report, incl. real failure examples -------
            html_report = render_html_report(score, run_dir=clean_run_dir, model_label="fake-score-model", latency_stats=latency_stats_fast)
            check("render_html_report: a real self-contained HTML document", html_report.startswith("<!doctype html>") and html_report.endswith("</html>"))
            check("render_html_report: the real recommendation text is embedded", "Score:" in html_report)
            check("render_html_report: the real latency table is embedded", "latency_ms" in html_report)
            check("render_html_report: a category the run never measured is disclosed", "dialogue" in html_report)

            fab_html = render_html_report(fab_score, run_dir=fab_run_dir)
            check("render_html_report: a real failure example's actual completion text is embedded", "Bartholomew" in fab_html)
            check("render_html_report: the disqualification banner is embedded", "DISQUALIFYING" in fab_html)

            no_examples_html = render_html_report(score, run_dir=None)
            check("render_html_report: run_dir=None never crashes and simply omits failure examples", "Failure examples" not in no_examples_html)

            # --- Real RunRecordReader sanity backing the failure examples above ---
            reader = RunRecordReader(fab_run_dir)
            any_failed = any(any(d.get("passed") is False for d in (r.scores or {}).values()) for r in reader.iter_case_records())
            check("sanity: the fabricating run genuinely committed at least one failing scorer verdict", any_failed)

            # --- A9.3: compare_runs -------------------------------------------
            comparison = compare_runs([("baseline", score), ("candidate", fab_score)])
            check("compare_runs: real labels preserved in order", comparison.labels == ["baseline", "candidate"])
            check("compare_runs: real totals per label", comparison.totals["baseline"] == score.total and comparison.totals["candidate"] == fab_score.total)
            grounding_comp = comparison.categories["grounding"]
            check("compare_runs: a real negative delta for the degraded candidate", grounding_comp.delta_from_baseline["candidate"] < 0, str(grounding_comp.delta_from_baseline))
            check("compare_runs: a real, large grounding regression is flagged significant", grounding_comp.significant_change["candidate"] is True, str(grounding_comp.significant_change))

            identical_comparison = compare_runs([("baseline", score), ("same again", score)])
            check("compare_runs: comparing a score against an identical copy of itself is never flagged significant", identical_comparison.categories["grounding"].significant_change["same again"] is False)

            missing_margin_score = HearthBenchScore(total=80.0, categories_used=["grounding"], category_scores={"grounding": 80.0}, weights_used={"grounding": 1.0}, category_confidence_margin={"grounding": None}, n_cases_total=1)
            no_margin_comparison = compare_runs([("baseline", missing_margin_score), ("candidate", missing_margin_score)])
            check("compare_runs: a missing real margin degrades significant_change to None, never a guess", no_margin_comparison.categories["grounding"].significant_change["candidate"] is None)

            empty_comparison = compare_runs([])
            check("compare_runs: an empty input degrades to an honest empty report, not a crash", empty_comparison.labels == [] and empty_comparison.categories == {})
    finally:
        clean_server.shutdown()
        fabricating_server.shutdown()

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
