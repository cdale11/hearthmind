"""Permanent LLM Training Recorder & Dataset Pipeline (§8, docs/IDEAS-
2026-07-EMERGENCE.md — "fine-tuning the local model (LoRA/QLoRA) on
Hearthmind's own generated prompt/completion data with human-supervised
top-5%/worst-5%/random-1% curation before any training batch").

This module implements the *data-collection* half of that idea (a
LoRA/QLoRA training run itself is out of scope here and stays a future,
separately-scoped increment) per the user-supplied "Hearthmind Permanent
LLM Training Recorder & Dataset Pipeline Specification": a permanent,
production-grade recorder that accumulates a corpus of every real LLM
task's four-layer record (structured input, rendered prompt, raw
completion, parsed output) for future SFT/DPO/eval/regression/prompt-
research use.

Design mirrors the spec's own architecture: `TrainingRecorder.
maybe_record(...)` is called synchronously from the engine's existing
`_record_llm_debug` hook (see simulation/engine.py) but does no I/O
itself — it builds one JSON-able dict and pushes it onto a bounded
`queue.Queue`, then returns immediately. A single background OS thread
(`_writer_loop`) drains the queue and appends one JSON line per example
to a per-task, date-rotated JSONL file, fsync'd after every write for
crash-safety. Deliberately a plain thread + `queue.Queue`, not asyncio —
recording must never touch the simulation's own event loop or block a
tick waiting on disk I/O ("gameplay must never wait for disk I/O," the
spec's own architecture diagram).

OFF by default (`RecordingPolicy.OFF`) — nothing is recorded, and
`maybe_record`'s first check is the policy no-op, so the steady-state
cost when disabled is one enum comparison per LLM call. Recording is
started/stopped only via an explicit `/recorder/start`/`/recorder/stop`
API call (see interface/app.py) or the browser UI's Recorder panel.

Layer 1 (structured input) is populated by the caller and defaults to
`{}` when not supplied — full population at every one of the ~35
`_schedule_llm_job` call sites in engine.py was scoped out of this pass
(see CHANGELOG.md for the exact list of which tasks DO carry real
structured input this pass: cognition, dialogue, and the settlement/
world-scoped jobs explicitly named in the spec's own "Scope" section).
Layers 2-4 (prompt, raw completion, parsed output) plus every metadata
field ARE captured for every real LLM task automatically, since every
task already funnels through the one `_record_llm_debug` hook — a
brand-new future job type needs zero recorder-specific code to start
being recorded.
"""
from __future__ import annotations

import json
import logging
import queue
import random
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger("hearthmind.recorder")

SCHEMA_VERSION = 1
"""Bumped whenever `TrainingExample`'s field set changes shape — lets a
future dataset-pipeline consumer detect and handle older archive lines
without guessing. Never bumped for a value-only change (new task name,
larger structured_input), only a field added/removed/retyped."""

RECORDER_VERSION = "1.0.0"
"""This module's own version, independent of `hearthmind.__version__` —
distinguishes "the simulation changed" from "the recorder's own record
shape changed," since either could explain a dataset discontinuity."""

ARCHIVE_ROTATE_MAX_BYTES = 100 * 1024 * 1024
"""Spec: "Rotate daily or at approximately 100 MB." A task's archive
file rolls to the next ordinal suffix once it crosses this size, in
addition to the always-on daily rotation by filename date."""

QUEUE_MAX = 5000
"""Bounded so a stalled/slow disk can never grow unbounded memory —
"zero gameplay impact" extends to the recorder itself never becoming a
new leak source. Past this, `maybe_record` drops the newest example and
counts it in `dropped` (same "shed the least-costly thing" shape as
`WorldBroadcaster.enqueue_intervention`'s own bounded queue) rather than
blocking the caller, which would violate "gameplay continues" (spec,
Core Principles)."""


class RecordingPolicy(str, Enum):
    OFF = "off"
    ALL_TASKS = "all_tasks"
    SELECTED_TASKS = "selected_tasks"
    SAMPLED = "sampled"
    DEBUG = "debug"
    """DEBUG behaves identically to ALL_TASKS for recording purposes
    (records everything) — reserved as its own value per the spec's
    explicit policy list so a future consumer can distinguish "recording
    for the permanent corpus" from "recording because someone is
    actively debugging a prompt," without this module needing to know
    what that distinction should mechanically do yet."""


@dataclass
class TrainingExample:
    """One four-layer record. `to_dict()` is the exact JSONL line shape
    — see docs/TRAINING_RECORDER.md for the full schema reference."""

    example_id: str
    schema_version: int
    recorder_version: str
    hearthmind_version: str
    session_id: str
    session_name: str
    task: str
    timestamp: float
    simulation_tick: int
    settlement: str | None
    npc_ids: list
    model_name: str
    latency_ms: float | None
    estimated_prompt_tokens: int
    estimated_completion_tokens: int
    parse_repaired: bool
    fallback_used: bool
    deterministic_seed: int | None
    structured_input: dict
    prompt: str
    system_prompt: str | None
    raw_completion: str | None
    parsed_output: dict

    def to_dict(self) -> dict:
        return {
            "example_id": self.example_id,
            "schema_version": self.schema_version,
            "recorder_version": self.recorder_version,
            "hearthmind_version": self.hearthmind_version,
            "session_id": self.session_id,
            "session_name": self.session_name,
            "task": self.task,
            "timestamp": self.timestamp,
            "simulation_tick": self.simulation_tick,
            "settlement": self.settlement,
            "npc_ids": self.npc_ids,
            "model_name": self.model_name,
            "latency_ms": self.latency_ms,
            "estimated_prompt_tokens": self.estimated_prompt_tokens,
            "estimated_completion_tokens": self.estimated_completion_tokens,
            "parse_repaired": self.parse_repaired,
            "fallback_used": self.fallback_used,
            "deterministic_seed": self.deterministic_seed,
            "layer1_structured_input": self.structured_input,
            "layer2_prompt": self.prompt,
            "layer2_system_prompt": self.system_prompt,
            "layer3_raw_completion": self.raw_completion,
            "layer4_parsed_output": self.parsed_output,
        }


def _estimate_tokens(text: str) -> int:
    """~4 chars/token estimate, same convention `SimulationEngine.
    llm_prompt_stats_summary` already uses — deliberately not a real
    tokenizer dependency (see that method's docstring)."""
    return max(0, len(text) // 4)


class TrainingRecorder:
    def __init__(
        self,
        archive_dir: str | Path,
        model_name_provider,
        hearthmind_version_provider,
        seed_provider=None,
    ) -> None:
        self._archive_dir = Path(archive_dir)
        self._policy = RecordingPolicy.OFF
        self._selected_tasks: set[str] = set()
        self._sample_rate = 0.1
        self._session_id: str | None = None
        self._session_name: str | None = None
        self._examples_this_session = 0
        self._queue: "queue.Queue[dict | None]" = queue.Queue(maxsize=QUEUE_MAX)
        self._writer_thread: threading.Thread | None = None
        self._dropped = 0
        self._write_errors = 0
        self._model_name_provider = model_name_provider
        self._hearthmind_version_provider = hearthmind_version_provider
        self._seed_provider = seed_provider
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._policy != RecordingPolicy.OFF

    # --- control -------------------------------------------------------------

    def start(
        self,
        session_name: str | None = None,
        policy: str = "all_tasks",
        selected_tasks: list[str] | None = None,
        sample_rate: float = 0.1,
    ) -> dict:
        try:
            policy_enum = RecordingPolicy(policy)
        except ValueError:
            policy_enum = RecordingPolicy.ALL_TASKS
        if policy_enum == RecordingPolicy.OFF:
            policy_enum = RecordingPolicy.ALL_TASKS
        with self._lock:
            self._policy = policy_enum
            self._selected_tasks = set(selected_tasks or [])
            self._sample_rate = max(0.0, min(1.0, sample_rate))
            self._session_id = uuid.uuid4().hex[:12]
            self._session_name = session_name or f"session-{self._session_id}"
            self._examples_this_session = 0
            self._dropped = 0
            self._write_errors = 0
            if self._writer_thread is None or not self._writer_thread.is_alive():
                self._writer_thread = threading.Thread(
                    target=self._writer_loop, daemon=True, name="training-recorder-writer",
                )
                self._writer_thread.start()
        logger.info(
            "Training recorder started: session=%s (%s) policy=%s",
            self._session_id, self._session_name, policy_enum.value,
        )
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._policy = RecordingPolicy.OFF
        logger.info(
            "Training recorder stopped: session=%s, %d examples collected.",
            self._session_id, self._examples_this_session,
        )
        return self.status()

    def status(self) -> dict:
        return {
            "policy": self._policy.value,
            "recording": self.enabled,
            "session_id": self._session_id,
            "session_name": self._session_name,
            "examples_collected": self._examples_this_session,
            "archive_size_bytes": self._archive_size_bytes(),
            "queue_depth": self._queue.qsize(),
            "dropped": self._dropped,
            "write_errors": self._write_errors,
            "selected_tasks": sorted(self._selected_tasks),
            "sample_rate": self._sample_rate,
            "archive_dir": str(self._archive_dir),
        }

    # --- recording (called from the tick loop's own thread) -------------------

    def _should_record(self, task: str) -> bool:
        policy = self._policy  # single attribute read, no lock needed for a bool-ish check
        if policy == RecordingPolicy.OFF:
            return False
        if policy == RecordingPolicy.SELECTED_TASKS:
            return task in self._selected_tasks
        if policy == RecordingPolicy.SAMPLED:
            return random.random() < self._sample_rate
        return True  # ALL_TASKS, DEBUG

    def maybe_record(
        self,
        *,
        task: str,
        prompt: str,
        system_prompt: str | None,
        result: dict,
        used_fallback: bool,
        raw_completion: str | None = None,
        elapsed_ms: float | None = None,
        tick: int = 0,
        structured_input: dict | None = None,
        npc_ids: list | None = None,
        settlement: str | None = None,
        parse_repaired: bool = False,
    ) -> None:
        """Called from `SimulationEngine._record_llm_debug` for EVERY
        resolved LLM task (real or fallback) — the policy check above is
        the only cost paid when recording is off. Never raises: a
        malformed example must never surface as a simulation error (spec:
        "if recording fails: gameplay continues, log failures, never
        block simulation")."""
        if not self._should_record(task):
            return
        try:
            example = TrainingExample(
                example_id=str(uuid.uuid4()),
                schema_version=SCHEMA_VERSION,
                recorder_version=RECORDER_VERSION,
                hearthmind_version=self._hearthmind_version_provider(),
                session_id=self._session_id or "unknown",
                session_name=self._session_name or "unknown",
                task=task,
                timestamp=time.time(),
                simulation_tick=tick,
                settlement=settlement,
                npc_ids=list(npc_ids or []),
                model_name=self._model_name_provider(),
                latency_ms=elapsed_ms,
                estimated_prompt_tokens=_estimate_tokens(prompt),
                estimated_completion_tokens=_estimate_tokens(str(result)),
                parse_repaired=parse_repaired,
                fallback_used=used_fallback,
                deterministic_seed=self._seed_provider() if self._seed_provider else None,
                structured_input=structured_input or {},
                prompt=prompt,
                system_prompt=system_prompt,
                raw_completion=raw_completion,
                parsed_output=result,
            )
            payload = example.to_dict()
        except Exception:
            logger.exception("Failed to build training example for task %s", task)
            return
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped += 1
            return
        self._examples_this_session += 1

    # --- background writer -----------------------------------------------------

    def _writer_loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                return
            self._write_one(item)

    def _write_one(self, item: dict) -> None:
        task = item.get("task", "unknown")
        try:
            path = self._archive_path_for(task)
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(item, ensure_ascii=False)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                try:
                    import os
                    os.fsync(fh.fileno())
                except OSError:
                    pass  # best-effort durability; never fatal
        except Exception:
            self._write_errors += 1
            logger.exception("Failed to write training example to archive (task=%s)", task)

    def _archive_path_for(self, task: str) -> Path:
        """`<archive_dir>/<task>/<date>.jsonl`, rolling to `<date>_2.jsonl`
        etc. once the current file crosses `ARCHIVE_ROTATE_MAX_BYTES` —
        satisfies "rotate daily or at approximately 100 MB" without ever
        needing to open/close a file across the day boundary mid-write."""
        date_str = time.strftime("%Y-%m-%d", time.gmtime())
        task_dir = self._archive_dir / _safe_task_name(task)
        base = task_dir / f"{date_str}.jsonl"
        if not base.exists() or base.stat().st_size < ARCHIVE_ROTATE_MAX_BYTES:
            return base
        ordinal = 2
        while True:
            candidate = task_dir / f"{date_str}_{ordinal}.jsonl"
            if not candidate.exists() or candidate.stat().st_size < ARCHIVE_ROTATE_MAX_BYTES:
                return candidate
            ordinal += 1

    def _archive_size_bytes(self) -> int:
        total = 0
        if self._archive_dir.exists():
            for p in self._archive_dir.rglob("*.jsonl"):
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
        return total


def _safe_task_name(task: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in task) or "unknown"
