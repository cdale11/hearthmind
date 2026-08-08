"""HearthBench A1.3 — process isolation for the bench run itself.

"Bench runs execute in a subprocess with their own model server
config, so a benchmark can never contend with, pause, or corrupt a
live sim." Two independent isolation layers now exist: A2.4's
`ServerLifecycle` (`hearthbench.adapters.lifecycle`) isolates the
MODEL SERVER (llama-server) in its own process; `BenchRunProcess`
here isolates the BENCH RUN ITSELF — the code that actually calls
`generate()`, scores results, and writes to disk — in a SECOND,
separate process, so neither a hung/crashed model server NOR a bug in
scoring/aggregation code can ever touch the caller's own process (a
live sim's interpreter, or a future A12 bench-daemon's own request
loop).

`BenchRunProcess` wraps a real `python -m hearthbench.runner.cli run`
invocation (`hearthbench.runner.cli`, this pass's own new real entry
point) as a `subprocess.Popen`, mirroring `ServerLifecycle`'s own
start/is_running/stop shape — generic process-management mechanics,
not benchmark-specific logic (the "adapters/CLI are the only place
model-specific knowledge lives" discipline applied one level up).

`poll_progress` is the real, dependency-free live-progress mechanism:
it reads the run's own `completed_case_ids()` straight off disk via
A8's `RunRecordReader` — the SAME run directory both the parent and
the child process already share — so a caller can watch a bench run's
real progress, and detect a real crash (the process exited with a
non-zero/None-vs-expected code while cases remain uncompleted),
without any socket/pipe/shared-memory IPC at all.

Import isolation (A1.2): stdlib + `hearthbench.*` only.
"""
from __future__ import annotations

import subprocess
import sys
import time

from hearthbench.adapters.lifecycle import LaunchRecord
from hearthbench.diagnostics import RunRecordReader


def build_bench_run_command(
    run_dir: str, adapter_endpoint: str, adapter_model: str, category: str = "grounding",
    adapter_api_key: "str | None" = None, adapter_quantization: "str | None" = None,
    adapter_context: "int | None" = None, python_executable: "str | None" = None,
) -> list:
    """Pure function: the exact argv a bench run subprocess would
    launch (mirrors `build_llama_server_command`'s own pure-function
    shape) — testable, and reproducibly recordable (A8.2), without
    needing a real process to exist yet."""
    command = [
        python_executable or sys.executable, "-m", "hearthbench.runner.cli", "run",
        "--category", category, "--run-dir", run_dir,
        "--adapter-endpoint", adapter_endpoint, "--adapter-model", adapter_model,
    ]
    if adapter_api_key:
        command += ["--adapter-api-key", adapter_api_key]
    if adapter_quantization:
        command += ["--adapter-quantization", adapter_quantization]
    if adapter_context is not None:
        command += ["--adapter-context", str(adapter_context)]
    return command


class BenchRunProcess:
    """Generic subprocess wrapper around one `hearthbench.runner.cli
    run` invocation — knows nothing about scoring/adapters/cases
    itself (that knowledge lives entirely in `cli.py`, which produces
    the real results this class only ever observes indirectly through
    `run_dir`)."""

    def __init__(self, run_dir: str, command: list) -> None:
        self.run_dir = run_dir
        self.command = list(command)
        self._process: "subprocess.Popen | None" = None
        self.record: "LaunchRecord | None" = None

    def start(self) -> LaunchRecord:
        """Raises `RuntimeError` if already running (never silently
        launches a second copy against the same run directory)."""
        if self.is_running():
            raise RuntimeError("BenchRunProcess.start() called while a process is already running")
        self._process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL)
        self.record = LaunchRecord(command=list(self.command), started_at=time.time(), pid=self._process.pid)
        return self.record

    def is_running(self) -> bool:
        """Lazily finalizes `self.record`'s `stopped_at`/`exit_code`
        the moment the child is observed to have exited — so a caller
        polling only `is_running()`/`poll_progress()` (never calling
        `wait()`) still gets an accurate, non-blocking crash reading."""
        if self._process is None:
            return False
        code = self._process.poll()
        if code is not None and self.record is not None and self.record.exit_code is None:
            self.record.stopped_at = time.time()
            self.record.exit_code = code
        return code is None

    def wait(self, timeout: "float | None" = None) -> "int | None":
        """Blocks up to `timeout` seconds (or forever if `None`) for
        the child to exit; returns `None` on a real timeout rather
        than raising, so a caller can retry without exception
        handling for the common "still running" case."""
        if self._process is None:
            return None
        try:
            code = self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        if self.record is not None and self.record.exit_code is None:
            self.record.stopped_at = time.time()
            self.record.exit_code = code
        return code

    def stop(self, timeout: float = 10.0) -> "LaunchRecord | None":
        """A clean SIGTERM, escalating to SIGKILL only past `timeout`
        — same "never a bare kill() first" discipline as `ServerLifecycle.
        stop`, applied to a bench run's own managed subprocess."""
        if self._process is None or self.record is None:
            return self.record
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=timeout)
        if self.record.exit_code is None:
            self.record.stopped_at = time.time()
            self.record.exit_code = self._process.returncode
        return self.record

    def poll_progress(self, expected_case_ids: "set | None" = None) -> dict:
        """The real, filesystem-only live-progress signal: reads
        `RunRecordReader(self.run_dir).completed_case_ids()` fresh —
        never cached — every call. `crashed` is `True` only once the
        process has genuinely exited with a real non-zero (or
        unexpectedly `None`) code while real work remained
        incomplete — never guessed from `is_running()` alone, since a
        cleanly-finished run also stops running."""
        completed = RunRecordReader(self.run_dir).completed_case_ids()
        running = self.is_running()
        exit_code = self.record.exit_code if self.record is not None else None
        incomplete = expected_case_ids is not None and not (expected_case_ids <= completed)
        crashed = (not running) and exit_code not in (None, 0) and incomplete
        return {
            "completed_case_ids": completed,
            "n_completed": len(completed),
            "n_expected": None if expected_case_ids is None else len(expected_case_ids),
            "is_running": running,
            "exit_code": exit_code,
            "crashed": crashed,
        }
