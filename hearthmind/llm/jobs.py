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
from typing import Callable

from hearthmind.llm.client import OllamaClient, OllamaUnavailable

logger = logging.getLogger("hearthmind.llm")


class CognitionRunner:
    def __init__(self, client: OllamaClient | None, max_concurrent: int):
        self.client = client
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))

    @property
    def enabled(self) -> bool:
        return self.client is not None

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
            try:
                # `generate_json` is a blocking network call; run it off
                # the event loop so it can't stall other ticks/tasks, and
                # wrap it in a hard wait_for as defense in depth beyond
                # the client's own socket timeout.
                result = await asyncio.wait_for(
                    asyncio.to_thread(self.client.generate_json, prompt, system),
                    timeout=self.client.timeout_seconds + 5.0,
                )
                return result, False
            except (OllamaUnavailable, asyncio.TimeoutError) as exc:
                logger.warning("LLM call failed, using deterministic fallback: %s", exc)
                return fallback(), True
            except Exception as exc:  # defense in depth: LLM failure must never propagate
                logger.warning("Unexpected LLM error, using deterministic fallback: %s", exc)
                return fallback(), True
