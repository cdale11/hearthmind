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
import logging
import time
from collections import deque
from typing import Callable

from hearthmind.llm.client import OllamaClient, OllamaUnavailable

logger = logging.getLogger("hearthmind.llm")

_LATENCY_WINDOW = 200
"""How many recent successful call latencies to retain for percentile
stats (see `stats()`) — a rolling window, not a full history, so this
stays bounded on a long soak run."""


class CognitionRunner:
    def __init__(self, client: OllamaClient | None, max_concurrent: int):
        self.client = client
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))
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
        self._latencies_ms: deque[float] = deque(maxlen=_LATENCY_WINDOW)

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
            "latency_ms_p50": percentile(0.5),
            "latency_ms_p95": percentile(0.95),
            "latency_ms_max": round(latencies[-1], 1) if latencies else 0.0,
        }

    async def run(
        self, prompt: str, system: str | None, fallback: Callable[[], dict]
    ) -> tuple[dict, bool]:
        """Return `(result, used_fallback)`: a parsed JSON dict from the
        LLM with `used_fallback=False`, or `(fallback(), True)` if the LLM
        is disabled, unreachable, times out, or misbehaves. Never raises —
        this is the boundary where LLM failures get absorbed. The
        `used_fallback` flag lets the caller track a fallback rate for
        diagnosis (see docs/DECISIONS.md, D5) — it's otherwise invisible
        from a saved snapshot."""
        if self.client is None:
            return fallback(), True

        async with self._semaphore:
            self.calls_attempted += 1
            start = time.perf_counter()
            try:
                # `generate_json` is a blocking network call; run it off
                # the event loop so it can't stall other ticks/tasks, and
                # wrap it in a hard wait_for as defense in depth beyond
                # the client's own socket timeout.
                result = await asyncio.wait_for(
                    asyncio.to_thread(self.client.generate_json, prompt, system),
                    timeout=self.client.timeout_seconds + 5.0,
                )
                self._latencies_ms.append((time.perf_counter() - start) * 1000)
                self.calls_succeeded += 1
                return result, False
            except asyncio.TimeoutError as exc:
                self.calls_timed_out += 1
                logger.warning("LLM call timed out, using deterministic fallback: %s", exc)
                return fallback(), True
            except OllamaUnavailable as exc:
                self.calls_errored += 1
                logger.warning("LLM call failed, using deterministic fallback: %s", exc)
                return fallback(), True
            except Exception as exc:  # defense in depth: LLM failure must never propagate
                self.calls_errored += 1
                logger.warning("Unexpected LLM error, using deterministic fallback: %s", exc)
                return fallback(), True
