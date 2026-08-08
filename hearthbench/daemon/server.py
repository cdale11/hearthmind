"""HearthBench A12 — the bench daemon.

A real, standalone FastAPI app the UI page (A12.1) talks to, per A1.3's
own framing: "The UI page talks to a bench daemon, not the sim
engine." Deliberately separate from `hearthmind.interface.app` (the
live sim's own web server) — this module imports nothing from
`hearthmind.simulation`/`.agents`/`.world` (A1.2's firewall), runs on
its own port, and every real benchmark it launches is a genuine,
process-isolated `BenchRunProcess` subprocess (A1.3) — a benchmark can
never contend with, pause, or corrupt a live sim, structurally, not by
convention.

**Scope this pass**: A12.1 (a real page, served BY this daemon,
clearly marked "not part of the sim" — `page.py`), A12.2 (start a
run), A12.3 (live progress via polling — the page's own `setInterval`
refresh; a real push/WebSocket log stream is real, distinct, unstarted
future work, flagged honestly rather than faked with a fake stream),
A12.4 (cancel — only for a run this daemon PROCESS itself launched;
canceling a run some OTHER process/daemon launched needs a real PID
file or lock mechanism, not attempted), A12.5 (browse EVERY real run
under `runs_root`, whether or not this daemon process launched it —
each one's state is always re-derived from its own real `manifest.
json`/`cases.jsonl` on disk, A8, never from an in-memory registry that
a daemon restart would lose). **A12.6** (compare runs — `GET /api/
runs/compare?run_ids=a,b,c`, real reuse of `hearthbench.reporting.
report.compare_runs`, the FIRST id given is the baseline). **A12.7**
(drill into a case — `GET /api/runs/{id}/cases` lists every real
committed `CaseRecord`; `GET /api/runs/{id}/cases/{case_id}` resolves
the case's actual prompt/completion text through A8's own `BlobStore`
plus its full real `scores`/timing/structured-input detail). **A12.8**
(download — `GET /api/runs/{id}/export.json`/`export.csv`, real reuse
of `export_json`/`export_csv`, written to a real temp file then
streamed back with a `Content-Disposition` header). **A12.9** (the
human-rating page, A4.3) remains open — real, distinct, unstarted
future work within this same item, not attempted here.

Only `OpenAICompatAdapter` (A2.2) is exposed through this daemon's
`StartRunRequest` — matching `hearthbench.runner.cli`'s own current
scope exactly (that CLI has no `--backend` flag either); wiring
`LlamaCppAdapter`/`OllamaAdapter` through needs the CLI itself extended
first, a real, separate, symmetric piece of future work on BOTH sides,
not a daemon-only gap.

Import isolation (A1.2): `hearthbench.*` + `fastapi`/`pydantic` (a
real, separate `bench` extra dependency — see `pyproject.toml`, never
pulled in by the live sim's own `api` extra or default install).
"""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from hearthbench.daemon.page import INDEX_HTML
from hearthbench.diagnostics import RunRecordReader
from hearthbench.metrics.aggregate import recompute_run_metrics
from hearthbench.reporting.report import compare_runs, export_csv, export_json, render_html_report
from hearthbench.reporting.score import compute_score
from hearthbench.runner.process import BenchRunProcess, build_bench_run_command

RUN_ID_PREFIX = "run_"


def _new_run_id() -> str:
    return RUN_ID_PREFIX + uuid.uuid4().hex[:12]


class StartRunRequest(BaseModel):
    category: str = "grounding"
    adapter_endpoint: str
    adapter_model: str
    adapter_api_key: "str | None" = None
    adapter_quantization: "str | None" = None
    adapter_context: "int | None" = None


@dataclass
class TrackedRun:
    """A real `BenchRunProcess` this daemon PROCESS itself launched —
    never the source of truth for a run's own state (that's always the
    real run_dir on disk, A8); purely what lets `cancel`/a live
    `poll_progress` reach an actual running subprocess. Lost on daemon
    restart, same as any in-flight subprocess handle would be — a
    restarted daemon can still browse the same run (A12.5) via its
    real `manifest.json`/`cases.jsonl`, it just can no longer `cancel`
    it or distinguish "still running elsewhere" from "crashed.\""""

    process: BenchRunProcess
    category: str
    adapter_model: str


class RunRegistry:
    """In-memory registry of `TrackedRun`s, keyed by `run_id`."""

    def __init__(self) -> None:
        self._tracked: dict = {}

    def add(self, run_id: str, tracked: TrackedRun) -> None:
        self._tracked[run_id] = tracked

    def get(self, run_id: str) -> "TrackedRun | None":
        return self._tracked.get(run_id)


def create_app(runs_root: str) -> FastAPI:
    """A real factory, not a module-level singleton — lets a verify
    script (or a future multi-tenant deployment) build several
    independent apps against different `runs_root`s in one process,
    same discipline `hearthbench.runner.process.build_bench_run_
    command` already established for testability."""
    os.makedirs(runs_root, exist_ok=True)
    registry = RunRegistry()
    app = FastAPI(title="HearthBench Daemon")

    def _run_dir(run_id: str) -> str:
        return os.path.join(runs_root, run_id)

    def _discover_run_ids() -> list:
        # Every subdirectory of runs_root holding a real manifest.json is a
        # real run (A8.2) — whether or not THIS daemon process is the one
        # that launched it. No registry file to keep in sync (A12.5).
        if not os.path.isdir(runs_root):
            return []
        found = []
        for name in sorted(os.listdir(runs_root)):
            if os.path.isfile(os.path.join(runs_root, name, "manifest.json")):
                found.append(name)
        return found

    def _run_summary(run_id: str) -> dict:
        run_dir = _run_dir(run_id)
        reader = RunRecordReader(run_dir)
        manifest = reader.manifest()
        extra = manifest.get("extra") or {}
        expected_case_ids = extra.get("expected_case_ids") or []
        completed = reader.completed_case_ids()
        tracked = registry.get(run_id)
        is_running = False
        crashed = False
        if tracked is not None:
            progress = tracked.process.poll_progress(
                expected_case_ids=set(expected_case_ids) if expected_case_ids else None
            )
            is_running = progress["is_running"]
            crashed = progress["crashed"]
        return {
            "run_id": run_id,
            "category": extra.get("category"),
            "model": (manifest.get("adapter_describe") or {}).get("model"),
            "created_at": manifest.get("created_at"),
            "n_completed": len(completed),
            "n_expected": len(expected_case_ids) if expected_case_ids else None,
            "is_running": is_running,
            "crashed": crashed,
            "tracked_by_this_daemon": tracked is not None,
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/runs")
    def list_runs() -> dict:
        return {"runs": [_run_summary(rid) for rid in _discover_run_ids()]}

    @app.post("/api/runs")
    def start_run(req: StartRunRequest) -> dict:
        run_id = _new_run_id()
        run_dir = _run_dir(run_id)
        command = build_bench_run_command(
            run_dir, req.adapter_endpoint, req.adapter_model, category=req.category,
            adapter_api_key=req.adapter_api_key, adapter_quantization=req.adapter_quantization,
            adapter_context=req.adapter_context,
        )
        process = BenchRunProcess(run_dir, command)
        process.start()
        registry.add(run_id, TrackedRun(process=process, category=req.category, adapter_model=req.adapter_model))
        return {"run_id": run_id, "run_dir": run_dir}

    @app.get("/api/runs/{run_id}/progress")
    def get_progress(run_id: str) -> dict:
        if not os.path.isdir(_run_dir(run_id)):
            raise HTTPException(status_code=404, detail="unknown run_id")
        return _run_summary(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict:
        tracked = registry.get(run_id)
        if tracked is None:
            raise HTTPException(
                status_code=404,
                detail="run is not tracked by this daemon process (already finished, or launched elsewhere)",
            )
        record = tracked.process.stop()
        return {"run_id": run_id, "stopped": True, "exit_code": record.exit_code if record else None}

    @app.get("/api/runs/{run_id}/report", response_class=HTMLResponse)
    def get_report(run_id: str) -> str:
        run_dir = _run_dir(run_id)
        if not os.path.isdir(run_dir):
            raise HTTPException(status_code=404, detail="unknown run_id")
        category_summaries = recompute_run_metrics(run_dir)
        score = compute_score(category_summaries)
        manifest = RunRecordReader(run_dir).manifest()
        model_label = (manifest.get("adapter_describe") or {}).get("model") or run_id
        return render_html_report(score, run_dir=run_dir, model_label=model_label)

    def _score_for(run_id: str):
        run_dir = _run_dir(run_id)
        if not os.path.isdir(run_dir):
            raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
        return compute_score(recompute_run_metrics(run_dir))

    @app.get("/api/runs/compare")
    def compare(run_ids: str) -> dict:
        # A12.6: real reuse of A9.3's `compare_runs` -- this route only
        # resolves ids -> real HearthBenchScores and reshapes the
        # dataclass result into JSON, no new comparison logic.
        ids = [rid.strip() for rid in run_ids.split(",") if rid.strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="run_ids query param required, comma-separated")
        labeled_scores = [(rid, _score_for(rid)) for rid in ids]
        report = compare_runs(labeled_scores)
        return {
            "labels": report.labels,
            "totals": report.totals,
            "categories": {
                cid: {
                    "scores": comp.scores,
                    "delta_from_baseline": comp.delta_from_baseline,
                    "significant_change": comp.significant_change,
                }
                for cid, comp in report.categories.items()
            },
        }

    @app.get("/api/runs/{run_id}/cases")
    def list_cases(run_id: str) -> dict:
        # A12.7 (list half): every real committed CaseRecord for this
        # run, summary fields only -- the full prompt/completion/scores
        # detail is the single-case route below.
        run_dir = _run_dir(run_id)
        if not os.path.isdir(run_dir):
            raise HTTPException(status_code=404, detail="unknown run_id")
        reader = RunRecordReader(run_dir)
        cases = [
            {
                "case_id": r.case_id, "category": r.category,
                "fallback_used": r.fallback_used, "error": r.error,
                "latency_ms": r.latency_ms,
            }
            for r in reader.iter_case_records()
        ]
        return {"run_id": run_id, "cases": cases}

    @app.get("/api/runs/{run_id}/cases/{case_id:path}")
    def get_case(run_id: str, case_id: str) -> dict:
        # A12.7 (drill-in half): the case's real prompt/completion text
        # resolved through A8's BlobStore, plus its full committed
        # CaseRecord -- exactly "prompt/completion/parsed output/scores
        # with justifications/timing," the item's own literal text.
        run_dir = _run_dir(run_id)
        if not os.path.isdir(run_dir):
            raise HTTPException(status_code=404, detail="unknown run_id")
        reader = RunRecordReader(run_dir)
        for r in reader.iter_case_records():
            if r.case_id != case_id:
                continue
            return {
                "case_id": r.case_id, "category": r.category,
                "prompt": reader.blobs.get(r.prompt_hash) or "",
                "completion": reader.blobs.get(r.completion_hash) or "",
                "parsed_json": r.parsed_json, "structured_input": r.structured_input,
                "fallback_used": r.fallback_used, "parse_repaired": r.parse_repaired,
                "retries": r.retries, "latency_ms": r.latency_ms, "ttft_ms": r.ttft_ms,
                "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                "error": r.error, "scores": r.scores, "recorded_at": r.recorded_at,
            }
        raise HTTPException(status_code=404, detail="unknown case_id in this run")

    @app.get("/api/runs/{run_id}/export.json")
    def export_run_json(run_id: str) -> Response:
        # A12.8: real reuse of export_json -- written to a real temp
        # file (its own real (score, path) contract), then streamed
        # back rather than left on disk, since a daemon route has no
        # business leaving download artifacts scattered in runs_root.
        score = _score_for(run_id)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, f"{run_id}.json")
            export_json(score, path)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
        return Response(
            content=content, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.json"'},
        )

    @app.get("/api/runs/{run_id}/export.csv")
    def export_run_csv(run_id: str) -> Response:
        score = _score_for(run_id)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, f"{run_id}.csv")
            export_csv(score, path)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
        return Response(
            content=content, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'},
        )

    return app
