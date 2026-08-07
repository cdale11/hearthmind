"""HearthBench A2.2 — `OllamaAdapter`.

Wraps `hearthmind.llm.client.OllamaClient` — same "reuse, don't
rebuild" reasoning as `llamacpp.py`. Import isolation (A1.2) holds for
the identical reason: `hearthmind.llm.client` has no dependency on
`hearthmind.simulation`/`.agents`/`.world`.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from hearthmind.llm.client import LLMUnavailable, OllamaClient

from .protocol import AdapterCapabilities, AdapterDescribe, AdapterResult, HealthStatus


class OllamaAdapter:
    """Structurally satisfies `hearthbench.adapters.protocol.
    ModelAdapter`."""

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
        self._client = OllamaClient(host=host, model=model, timeout_seconds=timeout_seconds)

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
            json_schema=True, grammar=False, seed=True, logprobs=False, metrics_endpoint=False,
        )

    def describe(self) -> AdapterDescribe:
        return AdapterDescribe(
            model=self.model, quantization=self.quantization, context=self.context, backend="ollama",
        )

    def health(self) -> HealthStatus:
        """Ollama's own root `/` endpoint answers "Ollama is running"
        for a live daemon with no model load required — cheaper than
        `/api/show` (which would need `model` to already exist)."""
        request = urllib.request.Request(f"{self.host.rstrip('/')}/", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                if response.status == 200:
                    return HealthStatus(ok=True)
                return HealthStatus(ok=False, detail=f"HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return HealthStatus(ok=False, detail=str(exc))

    def list_models(self) -> list[str] | None:
        """Best-effort `GET /api/tags` — not part of the `ModelAdapter`
        Protocol (Ollama-specific), a convenience for a future A2.4
        server-lifecycle check ("is this model already pulled?")."""
        request = urllib.request.Request(f"{self.host.rstrip('/')}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return None
        models = body.get("models") if isinstance(body, dict) else None
        if not isinstance(models, list):
            return None
        return [m.get("name") for m in models if isinstance(m, dict) and m.get("name")]
