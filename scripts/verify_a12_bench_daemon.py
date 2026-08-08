#!/usr/bin/env python3
"""HearthBench A12 — the bench daemon (A12.1-A12.5). Real production-
path checks, no unittest, same standalone-script convention as every
sibling `verify_*.py`.

Runs the REAL daemon app under a real `uvicorn.Server` in a background
thread, a real fake model-backend HTTP server standing in for a live
model, and talks to the daemon exclusively via real `urllib.request`
HTTP calls (never `TestClient`/mocks — this project's own established
technique throughout every HearthBench verify script this session)."""
from __future__ import annotations

import ast
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn

from hearthbench.daemon.server import create_app
from hearthbench.diagnostics import RunRecordReader
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
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"choices": [{"message": {"content": self.server.canned_content}}]}).encode("utf-8"))

    def do_POST(self):
        self._handle()

    def log_message(self, *args):
        pass


def _start_fake_backend(canned_content: str = "", delay_seconds: float = 0.0) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    server.canned_content = canned_content
    server.delay_seconds = delay_seconds
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _DaemonHandle:
    def __init__(self, runs_root: str):
        self.port = _free_port()
        app = create_app(runs_root)
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not getattr(self.server, "started", False):
            time.sleep(0.05)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str, expect_status: "int | None" = 200):
        try:
            with urllib.request.urlopen(self.url(path), timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), {}

    def post(self, path: str, body: "dict | None" = None):
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self.url(path), data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def shutdown(self):
        self.server.should_exit = True
        self.thread.join(timeout=10.0)


def main() -> int:
    # --- A1.2 firewall, checked directly over the whole daemon package -----
    daemon_dir = os.path.join(os.path.dirname(__file__), "..", "hearthbench", "daemon")
    banned = []
    for name in os.listdir(daemon_dir):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(daemon_dir, name)).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
                ("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")
            ):
                banned.append(f"{name}: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")):
                        banned.append(f"{name}: {alias.name}")
    check("A1.2 firewall: hearthbench/daemon/ imports nothing banned", not banned, str(banned))

    grounding_cases = build_grounding_bait_cases()
    fast_backend = _start_fake_backend(canned_content=json.dumps({"reason": "It has not been counted yet."}))

    with tempfile.TemporaryDirectory() as tmp:
        daemon = _DaemonHandle(tmp)
        try:
            check("daemon started (uvicorn server.started flag set)", getattr(daemon.server, "started", False))

            # --- A12.1: the page itself, clearly marked --------------------
            status, body, headers = daemon.get("/")
            check("GET /: real 200", status == 200)
            check("GET /: clearly marked NOT part of the sim (A12.1)", "NOT the live town simulation" in body)
            check("GET /: content-type is real HTML", "text/html" in headers.get("content-type", ""))

            # --- empty state ------------------------------------------------
            status, body, _ = daemon.get("/api/runs")
            check("GET /api/runs: empty list before any run exists", status == 200 and json.loads(body)["runs"] == [])

            status, body = daemon.post(
                "/api/runs/nonexistent-run-id/cancel",
            )
            check("POST cancel on an unknown/untracked run: real 404", status == 404)

            status, body, _ = daemon.get("/api/runs/nonexistent-run-id/progress")
            check("GET progress on an unknown run: real 404", status == 404)

            # --- A12.2: start a real run against the real fake backend -----
            status, body = daemon.post("/api/runs", {
                "category": "grounding",
                "adapter_endpoint": f"http://{fast_backend.server_address[0]}:{fast_backend.server_address[1]}/v1",
                "adapter_model": "fake-daemon-model",
            })
            check("POST /api/runs: real 200 launching a real subprocess", status == 200)
            run_id = json.loads(body)["run_id"]
            check("POST /api/runs: a real run_id assigned", bool(run_id))

            # --- A12.3: live progress via polling ----------------------------
            deadline = time.monotonic() + 20.0
            final_progress = None
            while time.monotonic() < deadline:
                status, body, _ = daemon.get(f"/api/runs/{run_id}/progress")
                if status != 200:
                    # a genuine, real race at the very start: the child
                    # subprocess hasn't created its own run_dir/manifest.json
                    # yet (RunRecordWriter.__init__), so the daemon honestly
                    # 404s rather than fabricating a summary -- keep polling.
                    time.sleep(0.1)
                    continue
                progress = json.loads(body)
                if progress["n_completed"] >= 4 and not progress["is_running"]:
                    final_progress = progress
                    break
                time.sleep(0.2)
            check("real run completed all 4 real grounding cases", final_progress is not None and final_progress["n_completed"] == 4, str(final_progress))
            check("progress: category/model surfaced correctly", final_progress and final_progress["category"] == "grounding" and final_progress["model"] == "fake-daemon-model")
            check("progress: never flagged crashed on a clean finish", final_progress and final_progress["crashed"] is False)

            # --- A12.5: browse via the list endpoint too --------------------
            status, body, _ = daemon.get("/api/runs")
            runs = json.loads(body)["runs"]
            check("GET /api/runs: the real completed run is listed", any(r["run_id"] == run_id and r["n_completed"] == 4 for r in runs))

            # --- report rendering (real A9 HTML report) ----------------------
            status, body, headers = daemon.get(f"/api/runs/{run_id}/report")
            check("GET report: real 200", status == 200)
            check("GET report: real HTML content", "<html" in body.lower())
            check("GET report: real 404 for a nonexistent run", daemon.get("/api/runs/does-not-exist/report")[0] == 404)

            # --- A12.7: drill into a case's real prompt/completion/scores ---
            status, body, _ = daemon.get(f"/api/runs/{run_id}/cases")
            cases_list = json.loads(body)
            check("GET cases: real 200 listing every real committed case", status == 200 and len(cases_list["cases"]) == 4, str(cases_list))
            check("GET cases: every case names the real grounding category", all(c["category"] == "grounding" for c in cases_list["cases"]))
            check("GET cases: real 404 for a nonexistent run", daemon.get("/api/runs/does-not-exist/cases")[0] == 404)

            first_case_id = cases_list["cases"][0]["case_id"]
            status, body, _ = daemon.get(f"/api/runs/{run_id}/cases/{first_case_id}")
            case_detail = json.loads(body)
            check("GET case detail: real 200", status == 200)
            check("GET case detail: the real prompt text was resolved through BlobStore", "marshcroft" in case_detail["prompt"].lower())
            check("GET case detail: the real completion text was resolved through BlobStore", "not been counted" in case_detail["completion"].lower())
            check("GET case detail: real per-scorer scores present", len(case_detail["scores"]) > 0)
            check("GET case detail: real 404 for an unknown case_id", daemon.get(f"/api/runs/{run_id}/cases/does-not-exist")[0] == 404)
            check("GET case detail: real 404 for an unknown run_id", daemon.get(f"/api/runs/does-not-exist/cases/{first_case_id}")[0] == 404)

            # --- A12.8: download JSON/CSV, real reuse of export_json/export_csv ---
            status, body, headers = daemon.get(f"/api/runs/{run_id}/export.json")
            check("GET export.json: real 200", status == 200)
            check("GET export.json: real JSON content-type", "application/json" in headers.get("content-type", ""))
            check("GET export.json: real Content-Disposition attachment header", "attachment" in headers.get("content-disposition", ""))
            exported = json.loads(body)
            check("GET export.json: a real total score present", exported["total"] is not None, str(exported))
            check("GET export.json: real 404 for a nonexistent run", daemon.get("/api/runs/does-not-exist/export.json")[0] == 404)

            status, body, headers = daemon.get(f"/api/runs/{run_id}/export.csv")
            check("GET export.csv: real 200", status == 200)
            check("GET export.csv: real CSV content-type", "text/csv" in headers.get("content-type", ""))
            csv_lines = body.strip().split("\n")
            check("GET export.csv: one header + at least one real category row", len(csv_lines) >= 2, body)
            check("GET export.csv: real 404 for a nonexistent run", daemon.get("/api/runs/does-not-exist/export.csv")[0] == 404)

            # --- A12.6: compare runs -- a SECOND real run against a fabricating
            #     backend, so the comparison has a genuine, measurable score gap.
            fabricating_backend = _start_fake_backend(canned_content=json.dumps(
                {"reason": "Exactly 92 people, led by Bartholomew, in a town called Ravenhollow, since 1743."}
            ))
            try:
                status, body = daemon.post("/api/runs", {
                    "category": "grounding",
                    "adapter_endpoint": f"http://{fabricating_backend.server_address[0]}:{fabricating_backend.server_address[1]}/v1",
                    "adapter_model": "fake-fabricating-model",
                })
                fab_run_id = json.loads(body)["run_id"]
                deadline = time.monotonic() + 20.0
                while time.monotonic() < deadline:
                    status, body, _ = daemon.get(f"/api/runs/{fab_run_id}/progress")
                    if status == 200 and json.loads(body).get("n_completed") == 4:
                        break
                    time.sleep(0.2)
                check("A12.6 setup: a real second run (fabricating backend) completed", json.loads(body).get("n_completed") == 4)

                status, body, _ = daemon.get(f"/api/runs/compare?run_ids={run_id},{fab_run_id}")
                check("GET compare: real 200", status == 200)
                compare_data = json.loads(body)
                check("GET compare: real labels, baseline first", compare_data["labels"] == [run_id, fab_run_id])
                check("GET compare: real totals for both runs", compare_data["totals"][run_id] is not None and compare_data["totals"][fab_run_id] is not None)
                grounding_comp = compare_data["categories"]["grounding"]
                check("GET compare: the real clean baseline's own grounding score is present",
                      grounding_comp["scores"][run_id] is not None, str(grounding_comp))
                check("GET compare: the clean baseline measurably outscores the fabricating run on grounding",
                      grounding_comp["scores"][run_id] > grounding_comp["scores"][fab_run_id], str(grounding_comp))
                check("GET compare: a real, negative delta for the fabricating run vs. the clean baseline",
                      grounding_comp["delta_from_baseline"][fab_run_id] is not None
                      and grounding_comp["delta_from_baseline"][fab_run_id] < 0, str(grounding_comp))

                status, body, _ = daemon.get("/api/runs/compare?run_ids=does-not-exist")
                check("GET compare: real 404 for an unknown run_id", status == 404)
                status, body, _ = daemon.get("/api/runs/compare?run_ids=")
                check("GET compare: real 400 for no run_ids given", status == 400)
            finally:
                fabricating_backend.shutdown()

            # --- A12.9: human rating over the same two real runs -----------
            status, body, _ = daemon.get(f"/api/rating/tasks?run_a={run_id}&run_b={fab_run_id}")
            check("GET rating tasks: real 200", status == 200)
            tasks_data = json.loads(body)
            check("GET rating tasks: real 4-task queue, one per shared case_id", tasks_data["n_total"] == 4 and tasks_data["n_pending"] == 4, str(tasks_data))
            first_task = tasks_data["tasks"][0]
            check(
                "GET rating tasks: blind -- no adapter identity or judge score leaked over the wire",
                "candidate_a_source" not in first_task and "candidate_b_source" not in first_task
                and "judge_score_a" not in first_task and "judge_score_b" not in first_task,
                str(first_task),
            )
            check("GET rating tasks: real prompt/candidate text present", bool(first_task["prompt_text"]) and bool(first_task["candidate_a_text"]) and bool(first_task["candidate_b_text"]))
            check("GET rating tasks: real 404 for an unknown run_id", daemon.get(f"/api/rating/tasks?run_a={run_id}&run_b=does-not-exist")[0] == 404)

            status, body = daemon.post("/api/rating/submit", {"task_id": first_task["task_id"], "rater_id": "verify-script", "choice": "a"})
            check("POST rating submit: real 200", status == 200 and json.loads(body)["ok"] is True)

            status, body = daemon.post("/api/rating/submit", {"task_id": first_task["task_id"], "rater_id": "verify-script", "choice": "not-a-real-choice"})
            check("POST rating submit: real 400 for an invalid choice", status == 400)

            status, body = daemon.post("/api/rating/submit", {"task_id": tasks_data["tasks"][1]["task_id"], "rater_id": "", "choice": "b"})
            check("POST rating submit: real 400 for a missing rater_id", status == 400)

            status, body, _ = daemon.get(f"/api/rating/tasks?run_a={run_id}&run_b={fab_run_id}")
            tasks_after = json.loads(body)
            check("GET rating tasks: the rated task no longer appears in the pending queue", tasks_after["n_pending"] == 3 and all(t["task_id"] != first_task["task_id"] for t in tasks_after["tasks"]), str(tasks_after))

            status, body, _ = daemon.get(f"/api/rating/agreement?run_a={run_id}&run_b={fab_run_id}")
            check("GET rating agreement: real 200", status == 200)
            agreement = json.loads(body)
            check(
                "GET rating agreement: the one real recorded rating counted, honestly against no judge score (neither run carries a Tier 2 judge scorer)",
                agreement["n_compared"] == 0 and agreement["agreement_rate"] is None and agreement["n_no_judge_score"] == 1,
                str(agreement),
            )

            # --- cancel on an already-finished (but still tracked) run -----
            status, body = daemon.post(f"/api/runs/{run_id}/cancel")
            check("POST cancel on an already-finished tracked run: safe, real 200", status == 200 and json.loads(body)["stopped"] is True)

            # --- A12.5's real claim: a SECOND daemon (fresh registry, same runs_root)
            #     still finds the SAME real run purely from disk (A8), no in-memory
            #     registry to rebuild -- the direct proof this isn't just reading its
            #     own launcher's memory.
            daemon2 = _DaemonHandle(tmp)
            try:
                status, body, _ = daemon2.get("/api/runs")
                runs2 = json.loads(body)["runs"]
                matching = [r for r in runs2 if r["run_id"] == run_id]
                check("a fresh daemon (no launch memory) still discovers the real run from disk", len(matching) == 1 and matching[0]["n_completed"] == 4)
                check("a fresh daemon correctly reports tracked_by_this_daemon=False for a run it never launched", matching[0]["tracked_by_this_daemon"] is False)
                status, body = daemon2.post(f"/api/runs/{run_id}/cancel")
                check("cancel on a run this SECOND daemon never tracked: real 404, never a false success", status == 404)
            finally:
                daemon2.shutdown()

            # --- real end-to-end proof: the actual run_dir on disk matches -----
            reader = RunRecordReader(os.path.join(tmp, run_id))
            check("the real run_dir on disk holds all 4 real committed cases", reader.completed_case_ids() == {c.id for c in grounding_cases})
        finally:
            daemon.shutdown()

        # --- a real cancel-while-running proof, separate run, slow backend ---
        slow_backend = _start_fake_backend(canned_content=json.dumps({"reason": "It has not been counted yet."}), delay_seconds=30.0)
        daemon3 = _DaemonHandle(tmp)
        try:
            status, body = daemon3.post("/api/runs", {
                "category": "grounding",
                "adapter_endpoint": f"http://{slow_backend.server_address[0]}:{slow_backend.server_address[1]}/v1",
                "adapter_model": "fake-slow-model",
            })
            run_id2 = json.loads(body)["run_id"]
            time.sleep(0.5)  # let it genuinely start a real (slow) request
            status, body, _ = daemon3.get(f"/api/runs/{run_id2}/progress")
            check("A12.3: a real slow run is genuinely observed running", json.loads(body)["is_running"] is True)

            status, body = daemon3.post(f"/api/runs/{run_id2}/cancel")
            check("A12.4: cancel on a real running, tracked run: real 200", status == 200)

            deadline = time.monotonic() + 10.0
            stopped = False
            while time.monotonic() < deadline:
                status, body, _ = daemon3.get(f"/api/runs/{run_id2}/progress")
                if json.loads(body)["is_running"] is False:
                    stopped = True
                    break
                time.sleep(0.1)
            check("A12.4: cancel genuinely terminates the real subprocess", stopped)
        finally:
            daemon3.shutdown()
            slow_backend.shutdown()

    fast_backend.shutdown()

    print(f"\n{len(FAILURES)} failure(s)." if FAILURES else "\nAll checks passed.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
