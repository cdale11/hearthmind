#!/usr/bin/env python3
"""HearthBench A1.3 — process isolation for the bench run itself. Real
production-path checks, no unittest, same standalone-script convention
as every sibling `verify_*.py`.

Exercises the real end-to-end path: a real local stdlib HTTP server
standing in for a live model, a REAL `python -m hearthbench.runner.
cli run` subprocess (`subprocess.Popen`, not mocked, not just called
in-process) driven by a real `hearthbench.runner.process.
BenchRunProcess`, its real progress observed purely through the real
run directory on disk (A8) — no IPC beyond the filesystem both
processes already share."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.diagnostics import RunRecordReader
from hearthbench.runner.cli import _cases_for_category, build_arg_parser, main as cli_main
from hearthbench.runner.process import BenchRunProcess, build_bench_run_command
from hearthbench.tests import build_grounding_bait_cases

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


class _CapturingHandler(BaseHTTPRequestHandler):
    def _handle(self):
        if self.server.delay_seconds:
            time.sleep(self.server.delay_seconds)
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length) if length else b""
        self.server.request_count += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        content = self.server.canned_content
        self.wfile.write(json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8"))

    def do_POST(self):
        self._handle()

    def log_message(self, *args):  # noqa: D401 - silence stdlib access logging
        pass


def _start_fake_server(canned_content: str = "", delay_seconds: float = 0.0) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_content = canned_content
    server.delay_seconds = delay_seconds
    server.request_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> int:
    grounding_cases = build_grounding_bait_cases()

    # --- pure-function coverage: cli.py -----------------------------------
    check("_cases_for_category: grounding resolves to the real 4 bait cases", len(_cases_for_category("grounding")) == 4)
    try:
        _cases_for_category("does-not-exist")
        check("_cases_for_category: an unsupported category raises", False)
    except ValueError as exc:
        check("_cases_for_category: an unsupported category raises a real, clear ValueError", "does-not-exist" in str(exc))

    parser = build_arg_parser()
    parsed = parser.parse_args(["run", "--run-dir", "/tmp/x", "--adapter-endpoint", "http://x", "--adapter-model", "m"])
    check("build_arg_parser: --category defaults to grounding", parsed.category == "grounding")
    check("build_arg_parser: required args are real and present", parsed.run_dir == "/tmp/x" and parsed.adapter_model == "m")

    # --- build_bench_run_command, pure function -----------------------------
    cmd = build_bench_run_command("/tmp/rd", "http://h:1/v1", "m1", category="grounding")
    check("build_bench_run_command: a real argv naming the real CLI module", "hearthbench.runner.cli" in cmd and "run" in cmd)
    check("build_bench_run_command: real endpoint/model/run-dir threaded through", "/tmp/rd" in cmd and "http://h:1/v1" in cmd and "m1" in cmd)
    cmd_with_extras = build_bench_run_command("/tmp/rd", "http://h:1/v1", "m1", adapter_api_key="k", adapter_quantization="q4", adapter_context=4096)
    check("build_bench_run_command: optional adapter args only appear when given", "--adapter-api-key" in cmd_with_extras and "--adapter-context" in cmd_with_extras)
    check("build_bench_run_command: optional args are omitted, not empty-stringed, when not given", "--adapter-api-key" not in cmd)

    # --- main(argv) exercised directly (fast, in-process) -------------------
    fast_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "inprocess-run")
            code = cli_main([
                "run", "--category", "grounding", "--run-dir", run_dir,
                "--adapter-endpoint", f"http://{fast_server.server_address[0]}:{fast_server.server_address[1]}/v1",
                "--adapter-model", "fake-inprocess-model",
            ])
            check("cli.main: a real in-process run exits 0", code == 0)
            reader = RunRecordReader(run_dir)
            check("cli.main: all 4 real grounding cases genuinely committed to disk", reader.completed_case_ids() == {c.id for c in grounding_cases})
            check("cli.main: the real environment snapshot names the real adapter model", reader.manifest().get("adapter_describe", {}).get("model") == "fake-inprocess-model")
    finally:
        fast_server.shutdown()

    # --- BenchRunProcess: a REAL subprocess, real progress polling ----------
    slow_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}), delay_seconds=0.2)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "subprocess-run")
            command = build_bench_run_command(
                run_dir, f"http://{slow_server.server_address[0]}:{slow_server.server_address[1]}/v1", "fake-subprocess-model",
            )
            proc = BenchRunProcess(run_dir, command)
            record = proc.start()
            check("BenchRunProcess.start: a real OS process was launched with a real pid", isinstance(record.pid, int) and record.pid > 0)

            try:
                proc.start()
                check("BenchRunProcess.start: starting a second time while running raises", False)
            except RuntimeError:
                check("BenchRunProcess.start: starting a second time while running raises RuntimeError", True)

            # Real mid-run progress: the slow server guarantees the 4 real
            # requests can't all finish before this poll, so a genuine
            # partial-but-real state should be observable at least once.
            deadline = time.monotonic() + 5.0
            saw_partial_progress = False
            while time.monotonic() < deadline:
                progress = proc.poll_progress(expected_case_ids={c.id for c in grounding_cases})
                if 0 < progress["n_completed"] < 4:
                    saw_partial_progress = True
                    break
                if not progress["is_running"]:
                    break
                time.sleep(0.05)
            check("BenchRunProcess.poll_progress: real partial progress observed mid-run via the filesystem alone", saw_partial_progress)

            exit_code = proc.wait(timeout=30.0)
            check("BenchRunProcess.wait: the real subprocess exits cleanly", exit_code == 0)
            check("BenchRunProcess.is_running: false once the real process has exited", proc.is_running() is False)
            check("BenchRunProcess: record.exit_code/stopped_at populated after exit", proc.record.exit_code == 0 and proc.record.stopped_at is not None)

            final_progress = proc.poll_progress(expected_case_ids={c.id for c in grounding_cases})
            check("BenchRunProcess.poll_progress: all 4 real cases completed", final_progress["n_completed"] == 4)
            check("BenchRunProcess.poll_progress: a cleanly-finished run is never flagged crashed", final_progress["crashed"] is False)

            reader = RunRecordReader(run_dir)
            check("BenchRunProcess: the real run directory holds all 4 real committed cases", reader.completed_case_ids() == {c.id for c in grounding_cases})
    finally:
        slow_server.shutdown()

    # --- BenchRunProcess: a real crash, genuinely detected -------------------
    with tempfile.TemporaryDirectory() as tmp:
        broken_run_dir = os.path.join(tmp, "broken-run-dir")
        with open(broken_run_dir, "w", encoding="utf-8") as fh:
            fh.write("not a directory")  # forces a real, uncaught exception inside the child process
        command = build_bench_run_command(broken_run_dir, "http://127.0.0.1:1/v1", "fake-crash-model")
        crash_proc = BenchRunProcess(broken_run_dir, command)
        crash_proc.start()
        crash_code = crash_proc.wait(timeout=15.0)
        check("BenchRunProcess: a real uncaught exception in the child produces a real nonzero exit", crash_code not in (None, 0), str(crash_code))
        crash_progress = crash_proc.poll_progress(expected_case_ids={c.id for c in grounding_cases})
        check("BenchRunProcess.poll_progress: a genuine crash with incomplete work is flagged crashed", crash_progress["crashed"] is True)
        check("BenchRunProcess.poll_progress: a broken run_dir never crashes the READER, degrades to zero completed", crash_progress["n_completed"] == 0)

    # --- BenchRunProcess: a real stop() actually terminates a long-running process ---
    hang_server = _start_fake_server(canned_content=json.dumps({"reason": "It has not been counted yet."}), delay_seconds=30.0)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "hang-run")
            command = build_bench_run_command(run_dir, f"http://{hang_server.server_address[0]}:{hang_server.server_address[1]}/v1", "fake-hang-model")
            hang_proc = BenchRunProcess(run_dir, command)
            hang_proc.start()
            time.sleep(0.3)  # let it genuinely start a real (slow) request
            check("BenchRunProcess: a real long-running process is genuinely still running before stop()", hang_proc.is_running() is True)
            stopped_record = hang_proc.stop(timeout=5.0)
            check("BenchRunProcess.stop: the real process is genuinely no longer running after stop()", hang_proc.is_running() is False)
            check("BenchRunProcess.stop: a real exit_code was recorded", stopped_record.exit_code is not None)
    finally:
        hang_server.shutdown()

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
