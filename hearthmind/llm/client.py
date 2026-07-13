"""A minimal, dependency-free client for a local Ollama server.

Uses `urllib.request` (stdlib) rather than adding `requests`/`httpx` as a
dependency — Ollama itself is the first real external dependency this
project takes on (see README), but talking HTTP to it doesn't need a new
pip package. See docs/DECISIONS.md, B1.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
"""Hybrid "thinking" models (e.g. Qwen3) can wrap chain-of-thought in
these tags even when a strict JSON response is requested — stripped
defensively so a stray reasoning block never breaks `json.loads`. Cheap
and a no-op for models that never emit them."""


class OllamaUnavailable(Exception):
    """Raised when the LLM could not be reached, timed out, or returned
    something we can't parse as JSON. Callers MUST catch this and fall
    back to deterministic behavior — the LLM must never be able to stall
    the simulation. See docs/DECISIONS.md, B1."""


@dataclass
class OllamaClient:
    host: str
    model: str
    timeout_seconds: float
    num_ctx: int | None = None
    num_predict: int | None = None
    """Explicit per-call bounds on Ollama's context window and generated
    token count (v0.43.0, see Config.llm_num_ctx/llm_num_predict) — sent
    as `options` so a live run's memory footprint doesn't depend on
    whatever default the Ollama server happens to ship with. `None`
    leaves the corresponding option out of the request entirely (server
    default), kept for callers/tests that don't care to pin it."""
    keep_alive: str | None = None
    """How long Ollama keeps this model loaded after the call (v0.43.1,
    see Config.llm_keep_alive) — sent as the request's top-level
    `keep_alive` field. `None` omits it (server default)."""

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        """Blocking call — issue one generate request and parse the
        response as JSON. Callers running inside the event loop must wrap
        this in `asyncio.to_thread` (see hearthmind/llm/jobs.py); this
        method itself does no async work."""
        options = {}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "think": False,
        }
        if options:
            payload["options"] = options
        if system:
            payload["system"] = system
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        request = urllib.request.Request(
            f"{self.host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc

        raw_response = _THINK_BLOCK_RE.sub("", body.get("response", "")).strip()
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise OllamaUnavailable(f"Ollama returned non-JSON response: {raw_response!r}") from exc
