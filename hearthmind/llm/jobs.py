"""Bounded-concurrency async runner for LLM jobs.

Two responsibilities:
1. Never let the LLM stall anything — every call goes through a timeout
   and a caller-supplied deterministic fallback, so a slow/unreachable
   Ollama server degrades the simulation's *quality* (agents fall back to
   rule-based goals) rather than its *liveness* (the tick loop keeps
   going regardless).
2. Bound how many requests are in flight at once (`max_concurrent`) —
   this is the lever for idle-CPU utilization described in the project
   brief: Ollama's own thread pool does the actual inference, and keeping
   several requests in flight (rather than one at a time) is what lets it
   use more of the available cores. See docs/DECISIONS.md, B1.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Callable

from hearthmind.llm.client import LLMAdapter, LLMTimeout, LLMUnavailable, _extract_json_object

logger = logging.getLogger("hearthmind.llm")

_LATENCY_WINDOW = 200
"""How many recent successful call latencies to retain for percentile
stats (see `stats()`) — a rolling window, not a full history, so this
stays bounded on a long soak run."""

NEAR_TIMEOUT_FRACTION = 0.85
"""A succeeded reasoning call within this fraction of its own timeout
ceiling counts toward `CognitionRunner.reasoning_calls_near_timeout` —
see that field's docstring for the live-diagnostic motivation."""


def _diag(
    fallback_reason: str | None, raw_model_output: str | None = None,
    parsed_json: dict | None = None, validation_errors: list[str] | None = None,
) -> dict:
    """One shared shape for every fallback-diagnosis dict this module
    produces — explicit user request: "expose raw_model_output,
    parsed_json, validation_errors, fallback_reason, fallback_result...
    whenever a fallback occurs for any LLM call." `fallback_reason=None`
    marks a genuine success (no fallback). `parsed_json`/`validation_
    errors` are best-effort: on a raw-text-available failure, this
    module re-attempts the same parse the client already tried (cheap,
    stdlib-only) purely so the dev console can show WHAT the model said
    and WHY it didn't parse, not just that it failed."""
    return {
        "fallback_reason": fallback_reason, "raw_model_output": raw_model_output,
        "parsed_json": parsed_json, "validation_errors": validation_errors or [],
    }


def _diagnose_raw_output(raw: str | None) -> tuple[dict | None, list[str]]:
    """Best-effort re-parse of a failed call's raw completion text, for
    diagnostic display only (the real parse already happened, and
    failed, inside the client) — returns `(parsed_or_None, errors)`."""
    if not raw:
        return None, ["no raw completion text was captured (call failed before generating any output)"]
    try:
        return json.loads(raw), []
    except json.JSONDecodeError as exc:
        extracted = _extract_json_object(raw)
        if extracted != raw:
            try:
                return json.loads(extracted), [f"required extracting JSON substring; original text was not bare JSON ({exc})"]
            except json.JSONDecodeError as exc2:
                return None, [f"raw completion is not valid JSON even after extraction: {exc2}"]
        return None, [f"raw completion is not valid JSON: {exc}"]


class CognitionRunner:
    def __init__(self, client: LLMAdapter | None, max_concurrent: int):
        self.client = client
        self.max_concurrent = max(1, max_concurrent)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self.backlog = 0
        """Jobs currently inside `run()` — in flight *or* waiting on the
        semaphore. The engine reads this to apply backpressure: on the
        target hardware one call takes ~17-20s while the engine can
        schedule several jobs per 1s tick, so without a gate the queue
        of waiting tasks grows without bound and results arrive
        sim-days stale (July 2026 architecture review, §3.6). Always
        ~0 when the LLM is disabled (fallbacks resolve instantly), so
        deterministic runs are unaffected."""
        self.calls_dropped_backpressure = 0
        """How many would-be jobs the engine chose not to schedule
        because `backlog` was over its limit — surfaced in `stats()` so
        a saturated live run is diagnosable as 'rationing' rather than
        silently degraded."""
        self.calls_deferred_critical = 0
        """How many *critical* cognition jobs (individual-mind goals,
        belief revision, the town brain, dreams, the consciousness) the
        engine chose to DEFER rather than resolve via a fabricated
        deterministic substitute, when the real LLM call couldn't happen
        (daily budget spent) or failed (timeout/error). This is the
        Engineering Constitution's §3/§7 rule made observable: crucial
        cognition is never faked to keep throughput up — the state is
        simply left unchanged and re-attempted on its natural cadence
        (and the sim already slows/pauses under live backlog pressure to
        give inference time to catch up). Written by the engine, same as
        `calls_dropped_backpressure`. A rising count against a low
        `calls_succeeded` means the LLM can't keep up and the world is
        correctly waiting for it rather than degrading into rule-based
        behavior."""
        self.calls_attempted = 0
        self.calls_succeeded = 0
        self.calls_timed_out = 0
        self.calls_errored = 0
        """Attempted/succeeded/timed-out/errored broken out separately
        (not just a single fallback counter) — added for overnight-soak
        diagnosability: "LLM is degraded" and "LLM is unreachable" and
        "LLM is slow" each point at a different fix, and used_fallback
        alone can't distinguish them. See docs/DECISIONS.md,
        diagnostics pass."""
        self.reasoning_calls_attempted = 0
        self.reasoning_calls_succeeded = 0
        self.reasoning_calls_timed_out = 0
        self.reasoning_calls_errored = 0
        """v1.4.4, explicit user request: "expose the diagnostics of deep
        reasoning calls... so we can trace the errors properly in
        future" — a `reasoning=True` call (see `_schedule_llm_job`'s
        `deep_reasoning`/`REASONING_LOAD_SHED_RATIO`) is structurally
        slower and unconstrained (never combined with `json_schema`), so
        it fails differently than a routine call and deserves its own
        counters rather than being invisible inside the aggregate totals
        above. `_reasoning_latencies_ms` is the reasoning-only latency
        percentile counterpart to `_latencies_ms`."""
        self.reasoning_calls_near_timeout = 0
        """A live diagnostic (42,013-tick run) showed reasoning p50/p95/
        max latency (87.9s/171.1s/192.2s) sitting right against this
        deployment's own scaled timeout ceilings (`DEEP_REASONING_
        TIMEOUT_MULT`/`num_predict_mult`-derived) — but `latency_ms_p50/
        p95/max` only ever reflect calls that SUCCEEDED, a survivorship
        gap: a deployment where most reasoning calls are timing out
        would show the same "healthy-looking" percentiles from just the
        few that happened to finish in time, with the timeout-out
        majority invisible except as a rising `reasoning.calls_timed_
        out` count elsewhere in the same payload. This counts a
        SUCCEEDED reasoning call as "near timeout" once its own latency
        crossed `NEAR_TIMEOUT_FRACTION` of the exact ceiling `_run_gated`
        used for that call (not a flat guess) — a rising share of
        near-miss successes is the leading indicator that the timeout
        (or the model/hardware) needs headroom, visible before the
        first real timeout ever fires."""
        self._latencies_ms: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self._reasoning_latencies_ms: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self._queue_wait_ms: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        """§7 "llama-server-side diagnostics," the one remaining piece
        (docs/IDEAS-2026-07-EMERGENCE.md — `/slots`/`/metrics` polling
        and retrieval-hit stats shipped earlier): how long each job
        actually waited for a concurrency-semaphore slot to open, as
        opposed to `latency_ms` (time the LLM itself took once running).
        A rising queue-wait alongside flat `latency_ms` means the
        bottleneck is `Config.llm_max_concurrent` being too low for the
        current call volume, not the model/server being slow — a
        distinction `backlog`/`calls_dropped_backpressure` alone
        couldn't make."""

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def stats(self) -> dict:
        """Snapshot of call outcomes and latency percentiles for the
        browser dev console / `/diagnostics` — see interface/app.py."""
        latencies = sorted(self._latencies_ms)

        def percentile(p: float) -> float:
            if not latencies:
                return 0.0
            idx = min(len(latencies) - 1, int(len(latencies) * p))
            return round(latencies[idx], 1)

        return {
            "calls_attempted": self.calls_attempted,
            "calls_succeeded": self.calls_succeeded,
            "calls_timed_out": self.calls_timed_out,
            "calls_errored": self.calls_errored,
            "backlog": self.backlog,
            "calls_dropped_backpressure": self.calls_dropped_backpressure,
            "calls_deferred_critical": self.calls_deferred_critical,
            "latency_ms_p50": percentile(0.5),
            "latency_ms_p95": percentile(0.95),
            "latency_ms_max": round(latencies[-1], 1) if latencies else 0.0,
            "queue_wait_ms_p50": self._percentile(self._queue_wait_ms, 0.5),
            "queue_wait_ms_p95": self._percentile(self._queue_wait_ms, 0.95),
            "reasoning": {
                "calls_attempted": self.reasoning_calls_attempted,
                "calls_succeeded": self.reasoning_calls_succeeded,
                "calls_timed_out": self.reasoning_calls_timed_out,
                "calls_errored": self.reasoning_calls_errored,
                "calls_near_timeout": self.reasoning_calls_near_timeout,
                "latency_ms_p50": self._percentile(self._reasoning_latencies_ms, 0.5),
                "latency_ms_p95": self._percentile(self._reasoning_latencies_ms, 0.95),
                "latency_ms_max": round(max(self._reasoning_latencies_ms), 1) if self._reasoning_latencies_ms else 0.0,
            },
        }

    @staticmethod
    def _percentile(values: "deque[float]", p: float) -> float:
        sorted_values = sorted(values)
        if not sorted_values:
            return 0.0
        idx = min(len(sorted_values) - 1, int(len(sorted_values) * p))
        return round(sorted_values[idx], 1)

    async def run(
        self, prompt: str, system: str | None, fallback: Callable[[], dict],
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
        reasoning: bool = False, timeout_override: float | None = None,
    ) -> tuple[dict, bool, str | None, dict]:
        """Return `(result, used_fallback, raw_completion, diag)`: a
        parsed JSON dict from the LLM with `used_fallback=False` and the
        exact raw completion text, or `(fallback(), True, None, diag)` if
        the LLM is disabled, unreachable, times out, or misbehaves. Never
        raises — this is the boundary where LLM failures get absorbed.
        The `used_fallback` flag lets the caller track a fallback rate
        for diagnosis (see docs/DECISIONS.md, D5) — it's otherwise
        invisible from a saved snapshot. `raw_completion` (added for the
        training recorder, llm/recorder.py — Layer 3) is the model's
        exact text before JSON parsing; `None` on any fallback path since
        no real completion exists to record.

        `diag` (explicit user request — "expose raw_model_output,
        parsed_json, validation_errors, fallback_reason, fallback_result
        ... whenever a fallback occurs for any LLM call"): a `_diag()`-
        shaped dict. On success, `fallback_reason` is `None` and
        `parsed_json` is the same dict as `result`. On any fallback path,
        `fallback_reason` names WHY (llm disabled, outer/socket timeout,
        the client's own error message, or an unexpected exception) and
        `raw_model_output`/`parsed_json`/`validation_errors` are a best-
        effort re-diagnosis of whatever raw text WAS captured before the
        failure (`capture["raw"]` is set by the client before it even
        attempts its own JSON parse — see `client.py`'s docstrings — so
        it usually survives a parse failure even though the call still
        raises). The caller (`_schedule_llm_job`) is the one place that
        knows the fallback RESULT dict itself (`fallback()`'s return
        value), so `fallback_result` is added there, not here.

        `json_schema` (optional, FT.0 — see `llm/json_schemas.py`):
        forwarded to the client's own `generate_json` to constrain
        decoding to a specific shape rather than bare JSON. `None`
        (the default, and every call site's behavior before FT.0)
        leaves generation unconstrained beyond "valid JSON."

        `num_predict_override`/`temperature_override` (Phase 3.A
        "reserved deeper reasoning" — see `client.py`'s `generate_json`
        docstring): forwarded unchanged to the client. `None` (every
        call site before this phase) leaves the client's own configured
        defaults in effect.

        `reasoning` (see `client.py`'s `_REASONING_ON_PROMPT`): forwarded
        unchanged. Callers must never pass `True` together with a
        `json_schema` — grammar-constrained decoding and a preceding
        `<think>` block are incompatible; `_schedule_llm_job` enforces
        this at the call site.

        `timeout_override` (v1.4.4): forwarded to the client's request-
        level timeout AND used (plus a 5s grace) as this method's own
        `asyncio.wait_for` ceiling — `None` keeps `self.client.timeout_
        seconds` for both, same as before this param existed."""
        if self.client is None:
            return fallback(), True, None, _diag("llm_disabled")

        self.backlog += 1
        try:
            return await self._run_gated(
                prompt, system, fallback, json_schema, num_predict_override, temperature_override,
                reasoning, timeout_override,
            )
        finally:
            self.backlog -= 1

    async def _run_gated(
        self, prompt: str, system: str | None, fallback: Callable[[], dict],
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
        reasoning: bool = False, timeout_override: float | None = None,
    ) -> tuple[dict, bool, str | None, dict]:
        queue_entered = time.perf_counter()
        effective_timeout = timeout_override if timeout_override is not None else self.client.timeout_seconds
        async with self._semaphore:
            self._queue_wait_ms.append((time.perf_counter() - queue_entered) * 1000)
            self.calls_attempted += 1
            if reasoning:
                self.reasoning_calls_attempted += 1
            start = time.perf_counter()
            capture: dict = {}
            try:
                # `generate_json` is a blocking network call; run it off
                # the event loop so it can't stall other ticks/tasks, and
                # wrap it in a hard wait_for as defense in depth beyond
                # the client's own socket timeout. The 5s grace is meant
                # to let the client's own (smaller-or-equal) socket
                # timeout fire first and raise a properly classified
                # `LLMTimeout` — see that class's docstring for why this
                # ordering matters for `calls_timed_out` accuracy.
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.client.generate_json, prompt, system, capture, json_schema,
                        num_predict_override, temperature_override, reasoning, timeout_override,
                    ),
                    timeout=effective_timeout + 5.0,
                )
                elapsed_ms = (time.perf_counter() - start) * 1000
                self._latencies_ms.append(elapsed_ms)
                self.calls_succeeded += 1
                if reasoning:
                    self._reasoning_latencies_ms.append(elapsed_ms)
                    self.reasoning_calls_succeeded += 1
                    if elapsed_ms >= NEAR_TIMEOUT_FRACTION * effective_timeout * 1000:
                        self.reasoning_calls_near_timeout += 1
                raw = capture.get("raw")
                return result, False, raw, _diag(None, raw, result, [])
            except asyncio.TimeoutError as exc:
                self.calls_timed_out += 1
                if reasoning:
                    self.reasoning_calls_timed_out += 1
                logger.warning("LLM call timed out (outer wait_for), using deterministic fallback: %s", exc)
                raw = capture.get("raw")
                parsed, errors = _diagnose_raw_output(raw)
                reason = f"outer wait_for timed out after {effective_timeout + 5.0:.0f}s: {exc}"
                return fallback(), True, None, _diag(reason, raw, parsed, errors)
            except LLMTimeout as exc:
                # The client's own request-level socket timeout — see
                # that class's docstring. Checked before the broader
                # `LLMUnavailable` below (it's a subclass) so a real
                # timeout is never misclassified as a generic error.
                self.calls_timed_out += 1
                if reasoning:
                    self.reasoning_calls_timed_out += 1
                logger.warning("LLM call timed out, using deterministic fallback: %s", exc)
                raw = capture.get("raw")
                parsed, errors = _diagnose_raw_output(raw)
                return fallback(), True, None, _diag(f"request timed out: {exc}", raw, parsed, errors)
            except LLMUnavailable as exc:
                self.calls_errored += 1
                if reasoning:
                    self.reasoning_calls_errored += 1
                logger.warning("LLM call failed, using deterministic fallback: %s", exc)
                raw = capture.get("raw")
                parsed, errors = _diagnose_raw_output(raw)
                return fallback(), True, None, _diag(str(exc), raw, parsed, errors)
            except Exception as exc:  # defense in depth: LLM failure must never propagate
                self.calls_errored += 1
                if reasoning:
                    self.reasoning_calls_errored += 1
                logger.warning("Unexpected LLM error, using deterministic fallback: %s", exc)
                raw = capture.get("raw")
                parsed, errors = _diagnose_raw_output(raw)
                return fallback(), True, None, _diag(f"unexpected error: {exc}", raw, parsed, errors)
