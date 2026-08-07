#!/usr/bin/env python3
"""HearthBench A7.1/A8/A11.4 — real run record, recomputable metrics,
and resume. Real production-path checks, no unittest, same standalone-
script convention as every sibling `verify_*.py`.

Exercises the real end-to-end path: a real local stdlib HTTP server
(same `_CapturingHandler` technique `verify_a2_model_adapters.py`/
`verify_a4_scoring.py`/`verify_a13_ci_guard.py` established) standing
in for a live model, through the REAL `OpenAICompatAdapter`, driving
real grounding bait cases through `hearthbench.runner.run.run_cases_
with_resume` and the real `hearthbench.diagnostics`/`hearthbench.
metrics` modules — never mocked.
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
from hearthbench.diagnostics import (
    BlobStore,
    CaseRecord,
    RunRecordReader,
    RunRecordWriter,
    build_environment_snapshot,
    prune_run,
)
from hearthbench.metrics import recompute_run_metrics
from hearthbench.runner.run import run_cases_with_resume
from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.tests import build_grounding_bait_cases

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
    return OpenAICompatAdapter(
        endpoint=f"http://{server.server_address[0]}:{server.server_address[1]}/v1",
        model="fake-diagnostics-model", quantization="q4_k_m", context=4096,
    )


def main() -> int:
    # --- A8.3: BlobStore ---------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        store = BlobStore(os.path.join(tmp, "blobs"))
        digest = store.put("hello world")
        check("BlobStore.put: returns a real sha256 hex digest", len(digest) == 64 and all(c in "0123456789abcdef" for c in digest))
        check("BlobStore.get: round-trips the exact stored text", store.get(digest) == "hello world")
        check("BlobStore.get: an unknown digest returns None, not a crash", store.get("0" * 64) is None)
        check("BlobStore.get: None digest returns None", store.get(None) is None)

        digest2 = store.put("hello world")
        check("BlobStore.put: an identical blob dedupes to the same digest", digest == digest2)

        second_call_content = store.get(digest)
        store.put("hello world")
        check("BlobStore.put: re-storing an existing blob never corrupts the file", store.get(digest) == second_call_content == "hello world")

    # --- A8.1: CaseRecord round-trip ----------------------------------------
    record = CaseRecord(
        case_id="c1", category="grounding", prompt_hash="a" * 64, completion_hash="b" * 64,
        parsed_json={"reason": "It has not been counted."}, structured_input={"x": 1},
        fallback_used=False, parse_repaired=False, retries=0, latency_ms=12.5, ttft_ms=None,
        prompt_tokens=10, completion_tokens=8, error=None,
        scores={"leak_freedom": {"scorer_id": "leak_freedom", "scorer_version": "1", "value": 1.0, "passed": True, "detail": {}, "error": None}},
    )
    round_tripped = CaseRecord.from_dict(record.to_dict())
    check("CaseRecord: to_dict/from_dict round-trips byte-for-byte", round_tripped.to_dict() == record.to_dict())

    # --- A8.2: environment snapshot -----------------------------------------
    fake_server = _start_fake_server(canned_content="{}")
    try:
        adapter = _adapter_for(fake_server)
        env = build_environment_snapshot(adapter, run_id="run-1")
        check("build_environment_snapshot: real adapter.describe() model captured", env["adapter_describe"].get("model") == "fake-diagnostics-model")
        check("build_environment_snapshot: real adapter.capabilities() captured", env["adapter_capabilities"].get("json_schema") in (True, False))
        check("build_environment_snapshot: real run_id preserved", env["run_id"] == "run-1")

        class _NoDescribeAdapter:
            pass

        honest_empty = build_environment_snapshot(_NoDescribeAdapter(), run_id="run-2")
        check("build_environment_snapshot: an adapter with neither method degrades honestly, never crashes",
              honest_empty["adapter_describe"] == {} and honest_empty["adapter_capabilities"] == {})
    finally:
        fake_server.shutdown()

    # --- A8.1: RunRecordWriter/RunRecordReader ------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = os.path.join(tmp, "run-a")
        writer = RunRecordWriter(run_dir, environment={"run_id": "run-a", "note": "first"})
        check("RunRecordWriter: creates the real run directory", os.path.isdir(run_dir))
        check("RunRecordWriter: writes a real manifest.json", os.path.exists(os.path.join(run_dir, "manifest.json")))

        # A manifest is never silently overwritten by a second writer construction.
        RunRecordWriter(run_dir, environment={"run_id": "run-a", "note": "SHOULD NOT APPEAR"})
        reader = RunRecordReader(run_dir)
        check("RunRecordWriter: manifest is write-once, a later construction never overwrites it",
              reader.manifest().get("note") == "first")

        writer.commit_case(CaseRecord(case_id="x1", category="grounding"))
        writer.commit_case(CaseRecord(case_id="x2", category="grounding"))
        cases_path = os.path.join(run_dir, "cases.jsonl")
        check("RunRecordWriter.commit_case: writes a real JSONL line per commit", sum(1 for _ in open(cases_path)) == 2)

        all_records = list(reader.iter_case_records())
        check("RunRecordReader.iter_case_records: reads back real CaseRecords", len(all_records) == 2 and all_records[0].case_id == "x1")
        check("RunRecordReader.completed_case_ids: real set of committed ids", reader.completed_case_ids() == {"x1", "x2"})

        empty_reader = RunRecordReader(os.path.join(tmp, "never-created"))
        check("RunRecordReader: a nonexistent run directory degrades to empty, not a crash",
              empty_reader.completed_case_ids() == set() and empty_reader.manifest() == {})

    # --- A8.4: prune_run -----------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = os.path.join(tmp, "run-b")
        RunRecordWriter(run_dir).commit_case(CaseRecord(case_id="y1", category="grounding"))
        check("prune_run: the run directory genuinely exists before pruning", os.path.isdir(run_dir))
        prune_run(run_dir)
        check("prune_run: a real explicit prune actually deletes the run directory", not os.path.exists(run_dir))
        prune_run(run_dir)  # must not raise
        check("prune_run: pruning an already-gone directory is a safe no-op", not os.path.exists(run_dir))

    # --- A11.4: run_cases_with_resume, real end-to-end ------------------------
    grounding_cases = build_grounding_bait_cases()
    check("build_grounding_bait_cases: reuses the real 4 grounding bait cases", len(grounding_cases) == 4)

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = os.path.join(tmp, "resumable-run")

        clean_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}))
        try:
            adapter = _adapter_for(clean_server)
            env = build_environment_snapshot(adapter, run_id="resumable-run")

            # First "session": only the first 2 cases have run so far (simulates an interruption).
            first_results = run_cases_with_resume(grounding_cases[:2], adapter, DEFAULT_REGISTRY, run_dir, environment=env)
            check("run_cases_with_resume: first partial call runs exactly 2 real cases", len(first_results) == 2)
            check("run_cases_with_resume: first partial call makes exactly 2 real HTTP requests", clean_server.request_count == 2)

            reader = RunRecordReader(run_dir)
            check("run_cases_with_resume: 2 cases genuinely committed to disk after the first call", reader.completed_case_ids() == {c.id for c in grounding_cases[:2]})

            # Second "session": the SAME run_dir, the FULL case list — must skip the 2 already done.
            second_results = run_cases_with_resume(grounding_cases, adapter, DEFAULT_REGISTRY, run_dir, environment=env)
            check("run_cases_with_resume: resume only runs the 2 remaining real cases, never re-running the first 2",
                  len(second_results) == 2 and set(second_results.keys()) == {c.id for c in grounding_cases[2:]})
            check("run_cases_with_resume: resume made exactly 2 NEW HTTP requests (2 + 2 = 4 total, never 6)",
                  clean_server.request_count == 4)

            final_reader = RunRecordReader(run_dir)
            check("run_cases_with_resume: all 4 cases are committed to disk after resume completes",
                  final_reader.completed_case_ids() == {c.id for c in grounding_cases})

            # A third call with the full list again should run NOTHING new.
            third_results = run_cases_with_resume(grounding_cases, adapter, DEFAULT_REGISTRY, run_dir, environment=env)
            check("run_cases_with_resume: a fully-completed run resumes to a real no-op", third_results == {} and clean_server.request_count == 4)

            # The manifest was written once, from the FIRST call's real environment, never overwritten.
            check("run_cases_with_resume: manifest captured the real environment on first write",
                  final_reader.manifest().get("run_id") == "resumable-run")

            # Prompt/completion blobs are real and retrievable.
            one_record = next(final_reader.iter_case_records())
            check("run_cases_with_resume: a committed record's prompt_hash resolves to real stored text via BlobStore",
                  one_record.prompt_hash is not None and final_reader.blobs.get(one_record.prompt_hash) is not None)
            check("run_cases_with_resume: a committed record carries real per-scorer scores with scorer_version",
                  "leak_freedom" in one_record.scores and one_record.scores["leak_freedom"].get("scorer_version"))
        finally:
            clean_server.shutdown()

        # --- A7.1: recompute_run_metrics -----------------------------------
        recomputed = recompute_run_metrics(run_dir)
        check("recompute_run_metrics: real grounding category present after reading the run back from disk", "grounding" in recomputed)
        check("recompute_run_metrics: no_unsupported_specifics scorer present (proves the A5.7 registry fix reaches here too)",
              "no_unsupported_specifics" in recomputed["grounding"])
        check("recompute_run_metrics: n_total across all 4 real committed cases", recomputed["grounding"]["leak_freedom"].n_total == 4)
        check("recompute_run_metrics: a clean/hedging model scores a perfect pass rate, recomputed from disk alone",
              recomputed["grounding"]["no_unsupported_specifics"].pass_rate == 1.0)

        empty_metrics = recompute_run_metrics(os.path.join(tmp, "never-run"))
        check("recompute_run_metrics: a run directory with no committed cases returns {}, not an error", empty_metrics == {})

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
