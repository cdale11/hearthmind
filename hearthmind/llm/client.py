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
        if self.use_mmap is not None:
            options["use_mmap"] = self.use_mmap
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        if self.num_thread is not None:
            options["num_thread"] = self.num_thread
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
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc

        raw_response = _THINK_BLOCK_RE.sub("", body.get("response", "")).strip()
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

    def generate_json(self, prompt: str, system: str | None = None) -> dict:
        """Blocking call — issue one `/v1/chat/completions` request and
        parse the response as JSON. Callers running inside the event loop
        must wrap this in `asyncio.to_thread` (see hearthmind/llm/jobs.py);
        this method itself does no async work. Uses the OpenAI-compatible
        chat endpoint (not llama.cpp's raw `/completion`) so the server's
        own chat template handles system/user role formatting correctly
        per-model, matching how `OllamaClient` separates `system`/`prompt`
        without this project needing to know each model's prompt format."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # Grammar-constrained JSON output — llama.cpp enforces this at
            # the sampler level (not just prompted), same intent as
            # Ollama's `"format": "json"` but stronger (structurally
            # guaranteed valid JSON, not merely requested).
            "response_format": {"type": "json_object"},
        }
        if self.num_predict is not None:
            payload["max_tokens"] = self.num_predict

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
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"llama.cpp returned non-JSON content: {raw_response!r}") from exc


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
            num_thread=config.llm_num_thread,
        )
    return LlamaCppClient(
        host=config.llm_llamacpp_host, model=config.llm_model,
        timeout_seconds=config.llm_timeout_seconds, num_predict=config.llm_num_predict,
    )
