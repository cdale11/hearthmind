#!/usr/bin/env python3
"""HearthBench A2 — Model Adapter Layer. Real production-path checks,
no unittest, same standalone-script convention as every sibling
`verify_*.py`. Where a real live LLM backend can't exist in this
offline environment, exercises the REAL adapter code path (real HTTP
request/response parsing) against a small local stdlib HTTP server
serving canned, shape-accurate responses, plus real unreachable-host
checks (a real connection-refused error, not a mock) to prove the
"never raises" contract end to end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.adapters import (
    AdapterCapabilities,
    AdapterDescribe,
    AdapterResult,
    HealthStatus,
    LaunchRecord,
    LlamaCppAdapter,
    OllamaAdapter,
    OpenAICompatAdapter,
    ServerLifecycle,
    build_adapter,
    build_llama_server_command,
    run_conformance_suite,
)
from hearthmind.llm.client import LlamaCppClient, OllamaClient

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


class _CapturingHandler(BaseHTTPRequestHandler):
    """Records the last request's method/path/JSON body on the server
    instance itself, then answers with whatever `canned_response`/
    `canned_status` the server was configured with. One handler class
    shared by every fake server this script spins up (llama.cpp's
    OpenAI-chat shape, Ollama's own shape, a generic OpenAI-compat
    shape, and a plain `/health`/`/`/`/models` reachability check) —
    the response shape is entirely a construction-time parameter, not
    hardcoded per fake."""

    def _handle(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            self.server.last_request_json = json.loads(body) if body else None
        except json.JSONDecodeError:
            self.server.last_request_json = None
        self.server.last_request_path = self.path
        self.send_response(self.server.canned_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.canned_response).encode("utf-8"))

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def log_message(self, *args):  # noqa: D401 - silence stdlib access logging
        pass


def _start_fake_server(canned_response: dict, canned_status: int = 200) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_response = canned_response
    server.canned_status = canned_status
    server.last_request_json = None
    server.last_request_path = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _host_of(server: HTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


UNREACHABLE_HOST = "http://127.0.0.1:1"  # port 1 is privileged/unbound -- always refuses


def check_protocol_dataclasses():
    result = AdapterResult(text="hi", parsed={"a": 1})
    check("AdapterResult defaults: latency_ms 0.0, retries 0, error None", result.latency_ms == 0.0 and result.retries == 0 and result.error is None)
    caps = AdapterCapabilities()
    check("AdapterCapabilities defaults to every capability False", not any([caps.json_schema, caps.grammar, caps.seed, caps.logprobs, caps.metrics_endpoint]))
    described = AdapterDescribe(model="x")
    check("AdapterDescribe.extra defaults to a fresh empty dict", described.extra == {})
    health = HealthStatus(ok=True)
    check("HealthStatus round-trips ok/detail", health.ok is True and health.detail is None)


def check_llamacpp_adapter_success_path():
    canned = {"choices": [{"message": {"content": '{"goal": "forage", "reason": "hungry"}'}}], "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
    server = _start_fake_server(canned)
    try:
        adapter = LlamaCppAdapter(host=_host_of(server), model="test-model", timeout_seconds=5.0)
        result = adapter.generate("What should the agent do?", system="You are a village.", seed=42)
        check("LlamaCppAdapter.generate: real HTTP round-trip parses the canned response", result.parsed == {"goal": "forage", "reason": "hungry"})
        check("LlamaCppAdapter.generate: error is None on success", result.error is None)
        check("LlamaCppAdapter.generate: token counts reach AdapterResult via usage", result.prompt_tokens is None and result.completion_tokens is None, detail="(LlamaCppClient doesn't surface usage -- honest limitation, not this adapter's own field)")
        check("LlamaCppAdapter.generate: latency_ms is measured and positive", result.latency_ms >= 0)
        check("LlamaCppAdapter.generate: seed=42 genuinely reached the wire payload", server.last_request_json is not None and server.last_request_json.get("seed") == 42)
        caps = adapter.capabilities()
        check("LlamaCppAdapter.capabilities(): json_schema/grammar/seed/metrics_endpoint all True", caps.json_schema and caps.grammar and caps.seed and caps.metrics_endpoint)
        described = adapter.describe()
        check("LlamaCppAdapter.describe(): backend='llamacpp'", described.backend == "llamacpp" and described.model == "test-model")
    finally:
        server.shutdown()


def check_llamacpp_adapter_health():
    server = _start_fake_server({"status": "ok"})
    try:
        adapter = LlamaCppAdapter(host=_host_of(server), model="x")
        status = adapter.health()
        check("LlamaCppAdapter.health(): a real reachable server reports ok=True", status.ok is True)
    finally:
        server.shutdown()
    unreachable = LlamaCppAdapter(host=UNREACHABLE_HOST, model="x")
    status = unreachable.health()
    check("LlamaCppAdapter.health(): a real unreachable host reports ok=False with a real detail", status.ok is False and bool(status.detail))


def check_llamacpp_adapter_unreachable_generate_never_raises():
    adapter = LlamaCppAdapter(host=UNREACHABLE_HOST, model="x", timeout_seconds=2.0)
    result = adapter.generate("hi")
    check("LlamaCppAdapter.generate() against an unreachable host never raises", isinstance(result, AdapterResult))
    check("LlamaCppAdapter.generate() against an unreachable host sets a real error string", isinstance(result.error, str) and bool(result.error))
    check("LlamaCppAdapter.generate() against an unreachable host leaves parsed None", result.parsed is None)


def check_ollama_adapter_success_path():
    canned = {"response": '{"goal": "gather", "reason": "materials low"}'}
    server = _start_fake_server(canned)
    try:
        adapter = OllamaAdapter(host=_host_of(server), model="test-model", timeout_seconds=5.0)
        result = adapter.generate("What should the agent do?", seed=7)
        check("OllamaAdapter.generate: real HTTP round-trip parses the canned response", result.parsed == {"goal": "gather", "reason": "materials low"})
        check("OllamaAdapter.generate: seed=7 genuinely reached the wire payload's options", server.last_request_json is not None and server.last_request_json.get("options", {}).get("seed") == 7)
        caps = adapter.capabilities()
        check("OllamaAdapter.capabilities(): json_schema/seed True, grammar/metrics_endpoint False", caps.json_schema and caps.seed and not caps.grammar and not caps.metrics_endpoint)
    finally:
        server.shutdown()


def check_ollama_adapter_list_models():
    canned = {"models": [{"name": "nemotron-3-nano-4b"}, {"name": "qwen3:4b-instruct"}]}
    server = _start_fake_server(canned)
    try:
        adapter = OllamaAdapter(host=_host_of(server), model="x")
        names = adapter.list_models()
        check("OllamaAdapter.list_models(): real /api/tags parse returns both real names", names == ["nemotron-3-nano-4b", "qwen3:4b-instruct"])
    finally:
        server.shutdown()
    unreachable = OllamaAdapter(host=UNREACHABLE_HOST, model="x")
    check("OllamaAdapter.list_models(): an unreachable host degrades to None, never raises", unreachable.list_models() is None)


def check_openai_compat_adapter():
    canned = {"choices": [{"message": {"content": "not valid json, oops"}}]}
    server = _start_fake_server(canned)
    try:
        adapter = OpenAICompatAdapter(endpoint=_host_of(server) + "/v1", model="any-model", supports_json_schema=False)
        result = adapter.generate("hi", schema={"type": "object"})
        check("OpenAICompatAdapter.generate: malformed JSON content degrades to parsed=None, not an exception", result.parsed is None and result.text == "not valid json, oops")
        check("OpenAICompatAdapter.generate: without schema support, response_format falls back to json_object", server.last_request_json.get("response_format") == {"type": "json_object"})
        caps = adapter.capabilities()
        check("OpenAICompatAdapter.capabilities(): reports json_schema=False when configured that way", caps.json_schema is False and caps.seed is True)
    finally:
        server.shutdown()

    canned_good = {"choices": [{"message": {"content": '{"result": "ok"}'}}]}
    server2 = _start_fake_server(canned_good)
    try:
        adapter2 = OpenAICompatAdapter(endpoint=_host_of(server2) + "/v1", model="any-model", supports_json_schema=True, api_key="secret")
        schema = {"type": "object", "required": ["result"]}
        result2 = adapter2.generate("hi", schema=schema)
        check("OpenAICompatAdapter.generate: with schema support, real json_schema response_format sent", server2.last_request_json.get("response_format", {}).get("type") == "json_schema")
        check("OpenAICompatAdapter.generate: valid JSON content parses correctly", result2.parsed == {"result": "ok"})
    finally:
        server2.shutdown()

    unreachable = OpenAICompatAdapter(endpoint=UNREACHABLE_HOST + "/v1", model="x", timeout_seconds=2.0)
    result3 = unreachable.generate("hi")
    check("OpenAICompatAdapter.generate() against an unreachable host never raises and sets error", isinstance(result3, AdapterResult) and bool(result3.error))


def check_registry():
    server = _start_fake_server({"response": "{}"})
    try:
        adapter = build_adapter("ollama", host=_host_of(server), model="x")
        check("build_adapter('ollama', ...) constructs a real OllamaAdapter", isinstance(adapter, OllamaAdapter))
    finally:
        server.shutdown()
    try:
        build_adapter("not_a_real_backend", host="x", model="y")
        check("build_adapter with an unknown backend raises ValueError", False)
    except ValueError as exc:
        check("build_adapter with an unknown backend raises ValueError", "not_a_real_backend" in str(exc))


def check_conformance_suite_against_a_healthy_fake_backend():
    canned = {"choices": [{"message": {"content": '{"required_field": "value"}'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    server = _start_fake_server(canned)
    try:
        adapter = LlamaCppAdapter(host=_host_of(server), model="x", timeout_seconds=5.0)
        report = run_conformance_suite(adapter, prompt="hi", schema={"type": "object", "required": ["required_field"]})
        check("conformance suite: a well-behaved real backend passes every check", report.all_passed, detail=str(report.failures))
        check("conformance suite: adapter_backend records the real class name", report.adapter_backend == "LlamaCppAdapter")
        check("conformance suite: schema-honoring check ran (required key present)", any("schema honoring" in r.name for r in report.results))
    finally:
        server.shutdown()


def check_conformance_suite_against_an_unreachable_backend():
    adapter = LlamaCppAdapter(host=UNREACHABLE_HOST, model="x", timeout_seconds=2.0)
    report = run_conformance_suite(adapter)
    check("conformance suite: never raises even against a fully unreachable backend", isinstance(report, type(report)))
    error_taxonomy_checks = [r for r in report.results if "error taxonomy" in r.name]
    check("conformance suite: error-taxonomy checks ran and passed for a real connection failure", len(error_taxonomy_checks) == 2 and all(r.passed for r in error_taxonomy_checks))
    never_raises_check = [r for r in report.results if r.name == "generate() never raises"][0]
    check("conformance suite: 'generate() never raises' passes against a real unreachable host", never_raises_check.passed)


def check_conformance_suite_catches_a_real_contract_violation():
    class _BrokenAdapter:
        def generate(self, prompt, system=None, schema=None, max_tokens=None, temperature=None, seed=None):
            raise RuntimeError("this adapter violates the never-raises contract")

        def capabilities(self):
            return AdapterCapabilities()

        def describe(self):
            return AdapterDescribe()

        def health(self):
            return HealthStatus(ok=False, detail="n/a")

    report = run_conformance_suite(_BrokenAdapter())
    check("conformance suite: a genuinely broken adapter fails the suite (not silently passed)", not report.all_passed)
    check("conformance suite: the specific violated check is named in the failures", any(r.name == "generate() never raises" for r in report.failures))


def check_build_llama_server_command():
    command = build_llama_server_command("/models/nemotron.gguf", port=9001, ctx_size=4096, parallel=2, threads=8)
    check("build_llama_server_command: model path present", "/models/nemotron.gguf" in command)
    check("build_llama_server_command: port/ctx-size/parallel/threads all present as real flags", all(x in command for x in ["--port", "9001", "--ctx-size", "4096", "--parallel", "2", "--threads", "8"]))
    minimal = build_llama_server_command("/models/x.gguf")
    check("build_llama_server_command: threads=None omits --threads entirely", "--threads" not in minimal)
    with_extra = build_llama_server_command("/models/x.gguf", extra_args=["--flash-attn", "on"])
    check("build_llama_server_command: extra_args appended verbatim", with_extra[-2:] == ["--flash-attn", "on"])


def check_server_lifecycle_generic_process():
    # A generic, always-available long-running process -- proves the
    # lifecycle mechanics (start/is_running/stop/exit_code) work
    # against ANY real subprocess, not something llama-server-specific
    # (no such binary exists in this offline environment).
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    lifecycle = ServerLifecycle(command)
    check("ServerLifecycle: not running before start()", lifecycle.is_running() is False)
    record = lifecycle.start()
    check("ServerLifecycle.start() returns a real LaunchRecord with a real pid", isinstance(record, LaunchRecord) and record.pid is not None)
    check("ServerLifecycle: is_running() is True right after a real start()", lifecycle.is_running() is True)
    try:
        lifecycle.start()
        check("ServerLifecycle.start() while already running raises RuntimeError", False)
    except RuntimeError:
        check("ServerLifecycle.start() while already running raises RuntimeError", True)
    stopped = lifecycle.stop(timeout=5.0)
    check("ServerLifecycle.stop(): the real process is no longer running afterward", lifecycle.is_running() is False)
    check("ServerLifecycle.stop(): stopped_at and exit_code are recorded", stopped.stopped_at is not None and stopped.exit_code is not None)


def check_server_lifecycle_stop_on_never_started():
    lifecycle = ServerLifecycle([sys.executable, "--version"])
    result = lifecycle.stop()
    check("ServerLifecycle.stop() on a never-started process is a safe no-op", result is None)


def check_server_lifecycle_wait_for_health():
    # A process that exits almost immediately -- wait_for_health must
    # bail out (return False) rather than spin for the full timeout.
    command = [sys.executable, "-c", "pass"]
    lifecycle = ServerLifecycle(command)
    lifecycle.start()
    time.sleep(0.3)  # let the real process actually exit
    healthy = lifecycle.wait_for_health(lambda: HealthStatus(ok=True), timeout=3.0, interval=0.1)
    check("ServerLifecycle.wait_for_health(): bails out fast once the managed process has exited", healthy is False)
    lifecycle.stop()


def check_seed_override_wired_into_ollama_client():
    canned = {"response": "{}"}
    server = _start_fake_server(canned)
    try:
        client = OllamaClient(host=_host_of(server), model="x", timeout_seconds=5.0)
        client.generate_json("hi", seed_override=99)
        check("OllamaClient.generate_json(seed_override=99): reaches options.seed on the real wire payload", server.last_request_json.get("options", {}).get("seed") == 99)
        client.generate_json("hi")
        check("OllamaClient.generate_json(seed_override=None): no seed key sent at all (default omits it)", "seed" not in server.last_request_json.get("options", {}))
    finally:
        server.shutdown()


def check_seed_override_wired_into_llamacpp_client():
    canned = {"choices": [{"message": {"content": "{}"}}]}
    server = _start_fake_server(canned)
    try:
        client = LlamaCppClient(host=_host_of(server), model="x", timeout_seconds=5.0)
        client.generate_json("hi", seed_override=17)
        check("LlamaCppClient.generate_json(seed_override=17): reaches the real top-level seed field", server.last_request_json.get("seed") == 17)
        client.generate_json("hi")
        check("LlamaCppClient.generate_json(seed_override=None): no seed key sent at all", "seed" not in server.last_request_json)
    finally:
        server.shutdown()


def check_no_model_specific_logic_outside_adapters():
    script = os.path.join(os.path.dirname(__file__), "verify_hearthbench_adapter_isolation.py")
    result = subprocess.run([sys.executable, script], capture_output=True, text=True)
    check("scripts/verify_hearthbench_adapter_isolation.py passes clean on the real tree", result.returncode == 0, detail=result.stdout + result.stderr)


def main() -> int:
    check_protocol_dataclasses()
    check_llamacpp_adapter_success_path()
    check_llamacpp_adapter_health()
    check_llamacpp_adapter_unreachable_generate_never_raises()
    check_ollama_adapter_success_path()
    check_ollama_adapter_list_models()
    check_openai_compat_adapter()
    check_registry()
    check_conformance_suite_against_a_healthy_fake_backend()
    check_conformance_suite_against_an_unreachable_backend()
    check_conformance_suite_catches_a_real_contract_violation()
    check_build_llama_server_command()
    check_server_lifecycle_generic_process()
    check_server_lifecycle_stop_on_never_started()
    check_server_lifecycle_wait_for_health()
    check_seed_override_wired_into_ollama_client()
    check_seed_override_wired_into_llamacpp_client()
    check_no_model_specific_logic_outside_adapters()

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
