"""HearthBench A2.2 — `OpenAICompatAdapter`.

Genuinely new (not a thin wrap): talks to any `/v1/chat/completions`
endpoint on its own terms — no Nemotron-specific "detailed thinking
on/off" system-prompt toggle, no Ollama-specific `think`/`options`
fields. `hearthmind.llm.client.LlamaCppClient` already speaks this
same wire shape but is deliberately tuned for one specific model
family (see that class's own docstring); this adapter is the
brief's own explicit third option, for "any" OpenAI-compatible server
(a hosted API, a different local runtime, a future backend this
project has never tuned for). Self-contained JSON-recovery/`<think>`-
stripping rather than importing `hearthmind.llm.client`'s own
underscore-prefixed helpers — those are that module's private
implementation detail, not a shared public contract, and this
adapter's needs are simpler (no reasoning-toggle awareness).

Import isolation (A1.2): stdlib only, no `hearthmind` import at all.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from .protocol import AdapterCapabilities, AdapterDescribe, AdapterResult, HealthStatus

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _best_effort_json(text: str) -> dict | None:
    """Try a bare parse first; on failure, try the substring from the
    first `{` to the last `}` (a model that wrapped its JSON in stray
    prose) before giving up. Never raises — returns `None` on total
    failure, matching every A2.2 adapter's "a result object even on
    failure" contract."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


class OpenAICompatAdapter:
    """Structurally satisfies `hearthbench.adapters.protocol.
    ModelAdapter`. `endpoint` is the full base URL up to (not
    including) `/chat/completions` — e.g. `http://localhost:8000/v1`
    for a self-hosted server, or a hosted provider's own base URL.
    `api_key` (optional) is sent as a bare `Authorization: Bearer`
    header when given; `None` omits the header entirely (a local
    server with no auth)."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        timeout_seconds: float = 120.0,
        api_key: str | None = None,
        supports_json_schema: bool = False,
        quantization: str | None = None,
        context: int | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        self.supports_json_schema = supports_json_schema
        self.quantization = quantization
        self.context = context

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> AdapterResult:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {"model": self.model, "messages": messages, "stream": False}
        if schema is not None and self.supports_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "hearthbench_case", "schema": schema, "strict": True},
            }
        elif schema is not None:
            # No schema/grammar support (capabilities().json_schema is
            # False for this instance) — fall back to the weaker
            # "some kind of JSON" request rather than silently dropping
            # the constraint request outright.
            payload["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if seed is not None:
            payload["seed"] = seed

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return AdapterResult(text="", parsed=None, latency_ms=(time.perf_counter() - start) * 1000, error=str(exc))
        latency_ms = (time.perf_counter() - start) * 1000

        try:
            raw_text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            return AdapterResult(
                text="", parsed=None, latency_ms=latency_ms, raw_response=body,
                error=f"unexpected response shape: {exc}",
            )
        raw_text = _THINK_BLOCK_RE.sub("", raw_text).strip()
        usage = body.get("usage") if isinstance(body, dict) else None
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        return AdapterResult(
            text=raw_text, parsed=_best_effort_json(raw_text),
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            latency_ms=latency_ms, raw_response=body,
        )

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            json_schema=self.supports_json_schema, grammar=False, seed=True,
            logprobs=False, metrics_endpoint=False,
        )

    def describe(self) -> AdapterDescribe:
        return AdapterDescribe(
            model=self.model, quantization=self.quantization, context=self.context,
            backend="openai_compat", extra={"endpoint": self.endpoint},
        )

    def health(self) -> HealthStatus:
        """Best-effort `GET {endpoint}/models` — the one endpoint the
        OpenAI chat-completions spec itself defines for listing
        available models, present on most compatible servers. A server
        that doesn't implement it reports unhealthy here even though
        `generate()` might still work — an honest limitation of a
        "any OpenAI-compatible server" adapter with no more specific
        health check to fall back to."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.endpoint.rstrip('/')}/models", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                if response.status == 200:
                    return HealthStatus(ok=True)
                return HealthStatus(ok=False, detail=f"HTTP {response.status}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return HealthStatus(ok=False, detail=str(exc))
