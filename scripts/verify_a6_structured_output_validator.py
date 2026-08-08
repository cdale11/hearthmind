#!/usr/bin/env python3
"""HearthBench A6 — the structured output validator (A6.1 schema reuse,
A6.2 repair ladder, A6.3 dual-mode delta). Real production-path checks,
no unittest, same standalone-script convention as every sibling
`verify_*.py` — a real local HTTP server standing in for a model
backend, talked to exclusively through the real `OpenAICompatAdapter`
and the real `hearthbench.runner.run`/`hearthbench.validation.*`
call paths, never mocks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.adapters.openai_compat import OpenAICompatAdapter
from hearthbench.diagnostics.run_record import CaseRecord, RunRecordReader
from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.runner.run import run_case_against_adapter, run_cases_with_resume
from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.scoring.types import CaseResult
from hearthbench.validation.dual_mode import run_case_dual_mode
from hearthbench.validation.repair_ladder import classify_repair
from hearthbench.validation.schema_resolver import resolve_schema
from hearthmind.llm.json_schemas import TASK_SCHEMAS

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


class _RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        self.server.received_requests.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"choices": [{"message": {"content": self.server.canned_content}}]}).encode("utf-8")
        )

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def _start_fake_backend(canned_content: str) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.canned_content = canned_content
    server.received_requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _adapter_for(server: HTTPServer, supports_json_schema: bool) -> OpenAICompatAdapter:
    endpoint = f"http://{server.server_address[0]}:{server.server_address[1]}/v1"
    return OpenAICompatAdapter(endpoint, model="fake-model", supports_json_schema=supports_json_schema)


def main() -> int:
    # --- pure-function checks: resolve_schema (A6.1) -----------------------
    check("resolve_schema(None) is None", resolve_schema(None) is None)
    check(
        "resolve_schema('cognition') matches the real production schema exactly",
        resolve_schema("cognition") == TASK_SCHEMAS["cognition"],
    )
    check("resolve_schema of an unrecognized task is None", resolve_schema("not-a-real-task") is None)

    # --- pure-function checks: classify_repair (A6.2) -----------------------
    raw = classify_repair('{"a": 1}', {"a": 1}, None)
    check("classify_repair: clean first-try parse is rung 'raw'", raw["rung"] == "raw" and raw["parse_repaired"] is False, str(raw))

    repaired = classify_repair('Sure! {"a": 1} hope that helps.', {"a": 1}, None)
    check(
        "classify_repair: JSON wrapped in prose is rung 'repaired'",
        repaired["rung"] == "repaired" and repaired["parse_repaired"] is True, str(repaired),
    )

    failed_no_error = classify_repair("not json at all", None, None)
    check("classify_repair: no recoverable JSON, no backend error -> rung 'failed'", failed_no_error["rung"] == "failed")
    check("classify_repair: failed reason names 'no valid JSON'", "no valid JSON" in failed_no_error["reason"])

    failed_error = classify_repair("", None, "connection refused")
    check("classify_repair: a real backend error -> rung 'failed'", failed_error["rung"] == "failed")
    check("classify_repair: failed-with-error reason names the real error", "connection refused" in failed_error["reason"])

    # --- CaseResult.from_adapter_result wiring (A6.2) -----------------------
    class _FakeResult:
        def __init__(self, text, parsed, error=None):
            self.text, self.parsed, self.error = text, parsed, error
            self.retries, self.latency_ms, self.ttft_ms = 0, 12.5, None

    cr_raw = CaseResult.from_adapter_result("cognition", {}, _FakeResult('{"goal": "wander"}', {"goal": "wander"}))
    check("CaseResult: a clean parse sets repair_rung='raw'", cr_raw.repair_rung == "raw" and cr_raw.parse_repaired is False)

    cr_repaired = CaseResult.from_adapter_result(
        "cognition", {}, _FakeResult('blah {"goal": "wander"} blah', {"goal": "wander"})
    )
    check("CaseResult: a repaired parse sets repair_rung='repaired'", cr_repaired.repair_rung == "repaired" and cr_repaired.parse_repaired is True)

    cr_failed = CaseResult.from_adapter_result("cognition", {}, _FakeResult("", None, "timeout"))
    check("CaseResult: a backend error sets repair_rung='failed'", cr_failed.repair_rung == "failed")
    check("CaseResult: fallback_used is True when parsed is None", cr_failed.fallback_used is True)

    # --- CaseRecord round-trip incl. backward compatibility -----------------
    record = CaseRecord(case_id="x", category="cognition", repair_rung="repaired", repair_reason="needed recovery")
    round_tripped = CaseRecord.from_dict(record.to_dict())
    check(
        "CaseRecord: repair_rung/repair_reason round-trip through to_dict/from_dict",
        round_tripped.repair_rung == "repaired" and round_tripped.repair_reason == "needed recovery",
    )
    legacy = CaseRecord.from_dict({"case_id": "y", "category": "cognition"})
    check("CaseRecord: a pre-A6.2 record with no repair fields degrades to None, not a crash", legacy.repair_rung is None and legacy.repair_reason is None)

    # --- A6.1 end-to-end: schema_ref genuinely changes the real HTTP request ---
    a_turn = [Turn(index=0, content="An NPC in Marshcroft is idle. What should they do next?")]
    case_with_schema = TestCase(
        id="cognition-probe", category="cognition", system_prompt="You decide an NPC's next action.",
        schema_ref="cognition", scorers=["schema_validity"], turns=a_turn,
    )

    server_a = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
    try:
        adapter_constrained = _adapter_for(server_a, supports_json_schema=True)
        scored = run_case_against_adapter(case_with_schema, adapter_constrained, DEFAULT_REGISTRY)
        check("A6.1: run_case_against_adapter produced a real score", scored is not None and "schema_validity" in scored, str(scored))
        sent = server_a.received_requests[-1]
        rf = sent.get("response_format", {})
        check(
            "A6.1: a schema_ref case against a schema-capable adapter requests real json_schema decoding",
            rf.get("type") == "json_schema" and rf.get("json_schema", {}).get("schema") == TASK_SCHEMAS["cognition"],
            str(rf),
        )
    finally:
        server_a.shutdown()

    server_b = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
    try:
        adapter_unconstrained = _adapter_for(server_b, supports_json_schema=False)
        run_case_against_adapter(case_with_schema, adapter_unconstrained, DEFAULT_REGISTRY)
        sent = server_b.received_requests[-1]
        rf = sent.get("response_format", {})
        check(
            "A6.1: the SAME schema_ref case against a non-schema-capable adapter degrades to json_object (A2.1's own documented fallback)",
            rf.get("type") == "json_object", str(rf),
        )
    finally:
        server_b.shutdown()

    case_without_schema = TestCase(
        id="no-schema-probe", category="cognition", system_prompt="You decide an NPC's next action.",
        scorers=["schema_validity"], turns=a_turn,
    )
    server_c = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
    try:
        adapter_c = _adapter_for(server_c, supports_json_schema=True)
        run_case_against_adapter(case_without_schema, adapter_c, DEFAULT_REGISTRY)
        sent = server_c.received_requests[-1]
        check(
            "A6.1: a case naming NO schema_ref reproduces the exact prior unconstrained call (no response_format key at all)",
            "response_format" not in sent, str(sent),
        )
    finally:
        server_c.shutdown()

    # --- A6.2 end-to-end: the real repair ladder lands in a real committed
    #     CaseRecord, read back purely from disk ------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = os.path.join(tmp, "run_clean")
        server_clean = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
        try:
            adapter = _adapter_for(server_clean, supports_json_schema=True)
            run_cases_with_resume([case_with_schema], adapter, DEFAULT_REGISTRY, run_dir)
        finally:
            server_clean.shutdown()
        rec = next(iter(RunRecordReader(run_dir).iter_case_records()))
        check("A6.2 end-to-end: a clean single-shot response commits repair_rung='raw'", rec.repair_rung == "raw" and rec.parse_repaired is False, str(rec.to_dict()))

        run_dir2 = os.path.join(tmp, "run_prose")
        server_prose = _start_fake_backend('Sure thing! {"goal": "wander", "reason": "nothing urgent"} Hope that helps!')
        try:
            adapter = _adapter_for(server_prose, supports_json_schema=True)
            run_cases_with_resume([case_with_schema], adapter, DEFAULT_REGISTRY, run_dir2)
        finally:
            server_prose.shutdown()
        rec2 = next(iter(RunRecordReader(run_dir2).iter_case_records()))
        check("A6.2 end-to-end: JSON wrapped in prose commits repair_rung='repaired'", rec2.repair_rung == "repaired" and rec2.parse_repaired is True, str(rec2.to_dict()))

        run_dir3 = os.path.join(tmp, "run_garbage")
        server_garbage = _start_fake_backend("this is not json at all, sorry")
        try:
            adapter = _adapter_for(server_garbage, supports_json_schema=True)
            run_cases_with_resume([case_with_schema], adapter, DEFAULT_REGISTRY, run_dir3)
        finally:
            server_garbage.shutdown()
        rec3 = next(iter(RunRecordReader(run_dir3).iter_case_records()))
        check("A6.2 end-to-end: unrecoverable text commits repair_rung='failed'", rec3.repair_rung == "failed" and rec3.fallback_used is True, str(rec3.to_dict()))

    # --- A6.3: dual-mode scoring + delta -------------------------------------
    server_dual = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
    try:
        adapter = _adapter_for(server_dual, supports_json_schema=True)
        result = run_case_dual_mode(case_with_schema, adapter, DEFAULT_REGISTRY)
        check("A6.3: constrained_supported=True when schema_ref set and adapter supports it", result["constrained_supported"] is True, str(result))
        check("A6.3: both real modes scored", "schema_validity" in result["unconstrained"]["scores"] and "schema_validity" in result["constrained"]["scores"])
        check("A6.3: a real delta dict is present", "schema_validity" in result["delta"])
        check("A6.3: exactly 2 real HTTP requests made (one per mode)", len(server_dual.received_requests) == 2, str(len(server_dual.received_requests)))
    finally:
        server_dual.shutdown()

    server_no_ref = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
    try:
        adapter = _adapter_for(server_no_ref, supports_json_schema=True)
        result = run_case_dual_mode(case_without_schema, adapter, DEFAULT_REGISTRY)
        check("A6.3: no schema_ref -> constrained_supported=False, real skip", result["constrained_supported"] is False and result["constrained"] is None and result["delta"] is None)
        check("A6.3: no schema_ref -> unconstrained is still populated", result["unconstrained"] is not None)
        check("A6.3: no schema_ref -> only 1 real HTTP request made (never a wasted second call)", len(server_no_ref.received_requests) == 1, str(len(server_no_ref.received_requests)))
    finally:
        server_no_ref.shutdown()

    server_unsupported = _start_fake_backend(json.dumps({"goal": "wander", "reason": "nothing urgent"}))
    try:
        adapter = _adapter_for(server_unsupported, supports_json_schema=False)
        result = run_case_dual_mode(case_with_schema, adapter, DEFAULT_REGISTRY)
        check(
            "A6.3: schema_ref set but adapter can't do it -> constrained_supported=False",
            result["constrained_supported"] is False,
        )
        check("A6.3: an unsupported adapter never wastes a second call", len(server_unsupported.received_requests) == 1, str(len(server_unsupported.received_requests)))
    finally:
        server_unsupported.shutdown()

    unrenderable_case = TestCase(id="empty-case", category="structured_outputs", scorers=["schema_validity"])
    server_empty = _start_fake_backend("{}")
    try:
        adapter = _adapter_for(server_empty, supports_json_schema=True)
        result = run_case_dual_mode(unrenderable_case, adapter, DEFAULT_REGISTRY)
        check("A6.3: a case with no renderable prompt returns a real honest skip (None)", result is None)
        check("A6.3: a real skip makes zero HTTP requests", len(server_empty.received_requests) == 0)
    finally:
        server_empty.shutdown()

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
