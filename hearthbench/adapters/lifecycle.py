"""HearthBench A2.4 — server lifecycle management.

"Optionally launch/stop the backend itself (llama-server with given
flags), recording exact command line, so a run is reproducible from
the stored record alone." Two pieces, deliberately separable:
`build_llama_server_command` is pure (no process touched, fully
testable without a real `llama-server` binary present); `ServerLifecycle`
is the generic subprocess wrapper — it doesn't know or care that the
command happens to be `llama-server`, so its own start/stop/health-poll
mechanics are exercised against ANY real subprocess in a verify script,
not a llama-server-specific fake.

Deliberately scoped narrower than `scripts/run.sh`: this records enough
of the confirmed-working GPU-offload recipe (ctx-size/parallel/n-gpu-
layers/threads/port/model) to make a bench run's exact invocation
reproducible from its own stored record, not a full re-implementation
of every one of `run.sh`'s ~20 tuning env vars — a run wanting the
fuller launch-flag surface can always pass `extra_args`.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass


def build_llama_server_command(
    model_path: str,
    host: str = "127.0.0.1",
    port: int = 8080,
    ctx_size: int = 3072,
    parallel: int = 1,
    n_gpu_layers: str | int = "999",
    threads: int | None = None,
    binary: str = "llama-server",
    extra_args: list[str] | None = None,
) -> list[str]:
    """Pure function: model path + tuning knobs -> the exact argv a
    reproducible bench run would launch. Mirrors `scripts/run.sh`'s own
    confirmed-working defaults (see that script's own docstring for the
    live-diagnostic history behind each one) without depending on the
    shell script itself — a benchmark run records this list verbatim
    (A8.2's "environment capture") so a stored result names the precise
    command that produced it, not just a model file path."""
    command = [
        binary,
        "--model", model_path,
        "--host", host,
        "--port", str(port),
        "--ctx-size", str(ctx_size),
        "--parallel", str(parallel),
        "--n-gpu-layers", str(n_gpu_layers),
    ]
    if threads is not None:
        command += ["--threads", str(threads)]
    if extra_args:
        command += list(extra_args)
    return command


@dataclass
class LaunchRecord:
    """A2.4's own "recording exact command line" — the reproducibility
    artifact, kept independent of the live `subprocess.Popen` object so
    it can be archived (A8) after the process itself has long since
    exited."""

    command: list[str]
    started_at: float
    pid: int | None = None
    stopped_at: float | None = None
    exit_code: int | None = None


class ServerLifecycle:
    """Generic subprocess launch/stop wrapper — knows nothing about
    llama-server specifically (that knowledge lives entirely in
    `build_llama_server_command`, which produces the `command` this
    class is handed). A2.1's "adapters are the only place model-
    specific logic may live" discipline applies here too: this class
    stays a plain process manager, never branching on what `command[0]`
    happens to be."""

    def __init__(self, command: list[str]) -> None:
        self.command = list(command)
        self._process: subprocess.Popen | None = None
        self.record: LaunchRecord | None = None

    def start(self) -> LaunchRecord:
        """Launches the process, detached from this Python process's
        own stdin (so a bench run started headless never blocks
        waiting on it) but with stdout/stderr left connected for now —
        real log capture is A8's own job, not this pass's. Raises
        `RuntimeError` if already running (never silently launches a
        second copy)."""
        if self.is_running():
            raise RuntimeError("ServerLifecycle.start() called while a process is already running")
        self._process = subprocess.Popen(self.command, stdin=subprocess.DEVNULL)
        self.record = LaunchRecord(command=list(self.command), started_at=time.time(), pid=self._process.pid)
        return self.record

    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def stop(self, timeout: float = 10.0) -> LaunchRecord | None:
        """A clean SIGTERM, escalating to SIGKILL only if the process
        hasn't exited within `timeout` — never a bare `kill()` first,
        so a well-behaved backend gets a real chance to flush/exit
        cleanly (matching this project's own standing "never destructive
        by default" discipline, applied here to a benchmark's own
        managed subprocess rather than the live simulation)."""
        if self._process is None or self.record is None:
            return self.record
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=timeout)
        self.record.stopped_at = time.time()
        self.record.exit_code = self._process.returncode
        return self.record

    def wait_for_health(self, health_check_fn, timeout: float = 30.0, interval: float = 0.5) -> bool:
        """Polls `health_check_fn()` (e.g. a `ModelAdapter.health`
        bound method) until it reports `ok=True` or `timeout` elapses.
        Bails out immediately (returns `False`) if the managed process
        has already exited — no point polling a health endpoint a dead
        process will never answer."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                return False
            status = health_check_fn()
            if getattr(status, "ok", False):
                return True
            time.sleep(interval)
        return False
