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


class LLMUnavailable(Exception):
    """Raised when the LLM could not be reached, timed out, or returned
    something we can't parse as JSON. Callers MUST catch this and fall
    back to deterministic behavior — the LLM must never be able to stall
    the simulation. See docs/DECISIONS.md, B1. Renamed from
    `OllamaUnavailable` in v0.72.0 when a second backend (llama.cpp) was
    added; the old name is kept as an alias below since both clients can
    raise it and callers (`llm/jobs.py`) catch it generically."""


OllamaUnavailable = LLMUnavailable
"""Backward-compatible alias — see `LLMUnavailable`."""


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
    use_mmap: bool | None = None
    """Explicit `use_mmap` request option (v0.55.0, see Config.llm_use_
    mmap) — a live diagnostic found the Ollama server launching its
    model runner with `--no-mmap`, forcing model weights into private
    anonymous memory the kernel can only relieve via swap rather than
    the cheaper drop-and-re-read-from-disk path mmap'd (file-backed)
    pages allow. `None` omits it (server default/heuristic)."""
    num_gpu: int | None = None
    """Explicit `num_gpu` request option (see Config.llm_num_gpu) — how
    many layers Ollama offloads to a GPU it has detected. `None` (the
    default) omits it, leaving Ollama's own auto-detected split in
    place; this project has no standing opinion on GPU layer count the
    way it does on mmap/ctx/predict, since it depends entirely on
    hardware Ollama may or may not recognize."""
    temperature: float | None = None
    """Sampling temperature (see Config.llm_temperature) — sent as an
    `options` entry. `None` omits it (server default)."""
    num_thread: int | None = None
    """Explicit `num_thread` request option (see Config.llm_num_thread) —
    how many CPU threads Ollama uses for this single inference call.
    Unlike `llm_max_concurrent` (which trades memory for richness and
    is a hard floor), this is a pure "use the CPU you already have"
    lever: on CPU-only hardware, Ollama defaults to a conservative
    thread count, leaving cores idle while a call runs. Pointing it at
    the machine's full core count makes each call finish faster —
    shortening the window its KV-cache allocation holds memory,
    without adding a second concurrent call's worth of KV cache the
    way raising `llm_max_concurrent` would. `None` (the default) omits
    it, leaving Ollama's own heuristic in charge."""

    def generate_json(
        self, prompt: str, system: str | None = None, capture: dict | None = None,
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
    ) -> dict:
        """Blocking call — issue one generate request and parse the
        response as JSON. Callers running inside the event loop must wrap
        this in `asyncio.to_thread` (see hearthmind/llm/jobs.py); this
        method itself does no async work.

        `num_predict_override`/`temperature_override` (Phase 3.A,
        "reserved deeper reasoning" — docs/VISION-2026-07-21-
        SELFEVOLVING.md): per-call replacements for `self.num_predict`/
        `self.temperature`, used by a job that genuinely warrants more
        tokens/lower randomness than routine dialogue/cognition (the
        Innovation Layer's propose/evolve/merge calls) without changing
        every other call site's behavior. `None` (every prior call site)
        keeps using the instance defaults exactly as before.

        `capture` (optional): if given a dict, this call fills in
        `capture["raw"]` with the exact raw completion text (Layer 3 of
        the training recorder, see llm/recorder.py) BEFORE attempting to
        parse it as JSON — so a malformed-JSON response still leaves the
        raw text recoverable for review, even though the call still
        raises `LLMUnavailable` for the caller's own fallback path. A
        fresh dict per call (never a shared/instance attribute) — this
        method may run concurrently across threads under
        `Config.llm_max_concurrent` > 1, and a shared attribute would be
        a data race.

        `json_schema` (optional, FT.0 — docs/AUDIT-2026-07-20.md):
        a per-task JSON Schema (see `llm/json_schemas.py`) that, when
        given, replaces the bare `"format": "json"` request with the
        actual schema — Ollama (0.5+) accepts a JSON Schema object
        directly in `format`, constraining decoding to the real
        shape (required keys, enums), not just valid-JSON-in-general.
        `None` keeps the old bare `"json"` behavior unchanged."""
        options = {}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        effective_num_predict = num_predict_override if num_predict_override is not None else self.num_predict
        if effective_num_predict is not None:
            options["num_predict"] = effective_num_predict
        if self.use_mmap is not None:
            options["use_mmap"] = self.use_mmap
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        if self.num_thread is not None:
            options["num_thread"] = self.num_thread
        effective_temperature = temperature_override if temperature_override is not None else self.temperature
        if effective_temperature is not None:
            options["temperature"] = effective_temperature
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": json_schema if json_schema is not None else "json",
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
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc

        raw_response = _THINK_BLOCK_RE.sub("", body.get("response", "")).strip()
        if capture is not None:
            capture["raw"] = raw_response
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"Ollama returned non-JSON response: {raw_response!r}") from exc


@dataclass
class LlamaCppClient:
    """Client for a local `llama-server` (llama.cpp's own HTTP server,
    OpenAI-chat-compatible) — the default backend as of v0.72.0 (see
    docs/DECISIONS.md, "llama.cpp default backend"). Chosen as the
    default over `OllamaClient` for the same reason Ollama itself is a
    llama.cpp wrapper under the hood (see the earlier "llama.cpp
    migration" evaluation in docs/DECISIONS.md): talking to llama.cpp
    directly removes Ollama's model-management daemon layer entirely
    (~100-300MB baseline RSS, plus its own defaults for
    `OLLAMA_NUM_PARALLEL`/mmap/keep_alive this project has spent several
    releases fighting) and exposes context size, KV-cache quantization,
    thread count, and GPU layer offload as direct, visible `llama-server`
    launch flags — see the README's "Running the LLM (llama.cpp)"
    section. `OllamaClient` above is kept and still fully supported
    (`Config.llm_backend = "ollama"`) for anyone with an existing Ollama
    setup; nothing about it changed in this pass.

    Unlike Ollama's per-request `num_ctx`, llama.cpp's context size is a
    *server startup* flag (`--ctx-size`) — there is no per-request
    equivalent, so `Config.llm_num_ctx` is consumed by the README's
    launch-flag guidance, not sent in this client's payload. Thread count
    (`--threads`) and GPU layer offload (`--n-gpu-layers`) are likewise
    server-launch flags for the same reason — llama.cpp pins them for the
    life of the server process rather than allowing them to vary call to
    call the way Ollama's `options` do.
    """

    host: str
    model: str
    timeout_seconds: float
    num_predict: int | None = None
    """Sent as `max_tokens` (v0.72.0, see Config.llm_num_predict) — same
    role as `OllamaClient.num_predict`: bounds a rambling generation,
    which otherwise burns KV-cache memory and wall-clock time for no
    reason since every response here is a short strict-JSON answer."""
    temperature: float | None = None
    """Sampling temperature (see Config.llm_temperature) — sent as the
    OpenAI-compatible `temperature` field. `None` omits it (server
    default). Lower values curb the rambling/off-shape output small
    models emit under the JSON grammar constraint."""

    def generate_json(
        self, prompt: str, system: str | None = None, capture: dict | None = None,
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
    ) -> dict:
        """Blocking call — issue one `/v1/chat/completions` request and
        parse the response as JSON. Callers running inside the event loop
        must wrap this in `asyncio.to_thread` (see hearthmind/llm/jobs.py);
        this method itself does no async work. Uses the OpenAI-compatible
        chat endpoint (not llama.cpp's raw `/completion`) so the server's
        own chat template handles system/user role formatting correctly
        per-model, matching how `OllamaClient` separates `system`/`prompt`
        without this project needing to know each model's prompt format.

        `capture`: see `OllamaClient.generate_json`'s docstring — same
        contract (fresh dict per call, filled with `capture["raw"]`).

        `json_schema` (optional, FT.0 — docs/AUDIT-2026-07-20.md, see
        `llm/json_schemas.py`): when given, requests `response_format:
        {"type": "json_schema", ...}` instead of the bare `json_object`
        mode — llama-server converts the schema to a GBNF grammar and
        enforces it at the sampler level, so a call with a schema can no
        longer emit a missing required key, a wrong-typed value, or an
        out-of-enum string; it was already structurally guaranteed valid
        JSON, this narrows that guarantee to the actual expected shape.
        `None` keeps the old bare `json_object` behavior unchanged."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if json_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "hearthmind_task", "schema": json_schema, "strict": True},
            }
        else:
            response_format = {"type": "json_object"}
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # Grammar-constrained JSON output — llama.cpp enforces this at
            # the sampler level (not just prompted), same intent as
            # Ollama's `"format": "json"` but stronger (structurally
            # guaranteed valid JSON, not merely requested; a per-task
            # schema above narrows this further to the expected shape).
            "response_format": response_format,
        }
        effective_num_predict = num_predict_override if num_predict_override is not None else self.num_predict
        if effective_num_predict is not None:
            payload["max_tokens"] = effective_num_predict
        effective_temperature = temperature_override if temperature_override is not None else self.temperature
        if effective_temperature is not None:
            payload["temperature"] = effective_temperature

        request = urllib.request.Request(
            f"{self.host.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"llama.cpp request failed: {exc}") from exc

        try:
            raw_response = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"llama.cpp returned an unexpected response shape: {body!r}") from exc

        raw_response = _THINK_BLOCK_RE.sub("", raw_response or "").strip()
        if capture is not None:
            capture["raw"] = raw_response
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"llama.cpp returned non-JSON content: {raw_response!r}") from exc


_METRICS_LINE_RE = re.compile(r"^(llamacpp:[a-zA-Z_]+)(?:\{[^}]*\})?\s+([0-9eE.+-]+)\s*$")
"""Matches one Prometheus text-format line from llama-server's `/metrics`
endpoint, e.g. `llamacpp:kv_cache_usage_ratio 0.312` or
`llamacpp:requests_processing{...} 2` — label blocks (if any) are
discarded, this project only wants the bare gauge/counter value per
metric name. Comment lines (`# HELP`/`# TYPE`) and blank lines simply
don't match and are skipped."""


def fetch_llama_server_metrics(host: str, timeout: float = 5.0) -> dict[str, float] | None:
    """Poll `llama-server`'s own `/metrics` endpoint (Prometheus text
    format, only present when the server was launched with `--metrics`
    — see `scripts/run.sh`'s `LLAMA_METRICS_ENDPOINT`) for real
    KV-cache/queue occupancy instead of this project's char-based
    prompt-size estimates (`SimulationEngine.llm_prompt_stats_summary`).
    v0.87.5 flagged this as a recommended-but-deferred next step;
    implemented here as a small, best-effort GET — returns `None` on
    any failure (server not running `--metrics`, unreachable, wrong
    backend, malformed response) rather than raising, since this is
    pure diagnostics and must never affect the tick loop or LLM call
    path. Deliberately does NOT poll `/slots` — that endpoint echoes
    live prompt content back to the caller for prompt-cache
    inspection, which is a real (if remote) privacy exposure this
    project's own local-only diagnostics don't need to take on for a
    handful of aggregate KV-cache numbers `/metrics` already provides
    (`llamacpp:kv_cache_usage_ratio`, `llamacpp:kv_cache_tokens`,
    `llamacpp:requests_processing`, `llamacpp:requests_deferred`, and
    the running prompt/predicted token/second counters)."""
    request = urllib.request.Request(f"{host.rstrip('/')}/metrics", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    metrics: dict[str, float] = {}
    for line in body.splitlines():
        match = _METRICS_LINE_RE.match(line.strip())
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        try:
            metrics[name] = float(value)
        except ValueError:
            continue
    return metrics or None


def build_llm_client(config) -> "OllamaClient | LlamaCppClient":
    """Factory used by both `SimulationEngine` and `server.py` so the two
    call sites can't drift on which fields each backend actually
    consumes (see docs/DECISIONS.md, "llama.cpp default backend"). Only
    ever called when `config.llm_enabled` is true."""
    if config.llm_backend == "ollama":
        return OllamaClient(
            host=config.llm_host, model=config.llm_model, timeout_seconds=config.llm_timeout_seconds,
            num_ctx=config.llm_num_ctx, num_predict=config.llm_num_predict,
            keep_alive=config.llm_keep_alive, use_mmap=config.llm_use_mmap, num_gpu=config.llm_num_gpu,
            num_thread=config.llm_num_thread, temperature=config.llm_temperature,
        )
    return LlamaCppClient(
        host=config.llm_llamacpp_host, model=config.llm_model,
        timeout_seconds=config.llm_timeout_seconds, num_predict=config.llm_num_predict,
        temperature=config.llm_temperature,
    )
