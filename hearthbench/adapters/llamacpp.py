"""HearthBench A2.2 — `LlamaCppAdapter`.

Wraps `hearthmind.llm.client.LlamaCppClient` rather than reimplementing
the `/v1/chat/completions` wire protocol a second time (A0.1's own
text: "reuse, don't rebuild"). `hearthmind.llm.client` imports nothing
from `hearthmind.simulation`/`.agents`/`.world` itself, so this stays
within A1.2's isolation firewall — the module being reused here has
zero live-simulation coupling to begin with.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request

from hearthmind.llm.client import LLMUnavailable, LlamaCppClient, fetch_llama_server_metrics

from .protocol import AdapterCapabilities, AdapterDescribe, AdapterResult, HealthStatus


class LlamaCppAdapter:
    """Structurally satisfies `hearthbench.adapters.protocol.
    ModelAdapter` (a `Protocol` — no explicit base class needed)."""

    def __init__(
        self,
        host: str,
        model: str,
        timeout_seconds: float = 120.0,
        quantization: str | None = None,
        context: int | None = None,
    ) -> None:
        self.host = host
        self.model = model
        self.quantization = quantization
        self.context = context
        self._client = LlamaCppClient(host=host, model=model, timeout_seconds=timeout_seconds)

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> AdapterResult:
        start = time.perf_counter()
        capture: dict = {}
        try:
            parsed = self._client.generate_json(
                prompt, system, capture, schema,
                max_tokens, temperature, False, None, seed,
            )
        except LLMUnavailable as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            return AdapterResult(
                text=capture.get("raw", ""), parsed=None, latency_ms=latency_ms, error=str(exc),
            )
        latency_ms = (time.perf_counter() - start) * 1000
        return AdapterResult(
            text=capture.get("raw", ""), parsed=parsed, latency_ms=latency_ms, raw_response=parsed,
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            json_schema=True, grammar=True, seed=True, logprobs=False, metrics_endpoint=True,
        )

    def describe(self) -> AdapterDescribe:
        return AdapterDescribe(
            model=self.model, quantization=self.quantization, context=self.context, backend="llamacpp",
        )

    def health(self) -> HealthStatus:
        """A cheap `/health` GET — never a full `generate()` call."""
        request = urllib.request.Request(f"{self.host.rstrip('/')}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                if response.status == 200:
                    return HealthStatus(ok=True)
                return HealthStatus(ok=False, detail=f"HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return HealthStatus(ok=False, detail=str(exc))

    def poll_metrics(self) -> dict[str, float] | None:
        """A2's own real metrics-endpoint reuse — `fetch_llama_server_
        metrics` already exists in `hearthmind.llm.client` for the live
        sim's diagnostics panel; a benchmark run wants the identical
        real KV-cache/queue numbers, not a second parser. Not part of
        the `ModelAdapter` Protocol itself (only llama.cpp exposes
        this) — an A7/A9 consumer that knows it's holding a
        `LlamaCppAdapter` specifically may call this directly."""
        return fetch_llama_server_metrics(self.host)
