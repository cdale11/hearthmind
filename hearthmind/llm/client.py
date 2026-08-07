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
from abc import ABC, abstractmethod
from dataclasses import dataclass

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
"""Hybrid "thinking" models (e.g. Qwen3, Nemotron 3) can wrap chain-of-
thought in these tags even when a strict JSON response is requested —
stripped defensively so a stray reasoning block never breaks
`json.loads`. Cheap and a no-op for models that never emit them."""

_UNCLOSED_THINK_RE = re.compile(r"<think>.*", re.DOTALL)
"""v1.4.3: a completion that runs out of `max_tokens` mid-reasoning
never emits the closing `</think>` — invisible to `_THINK_BLOCK_RE`
above, which requires a matched pair, so the whole unfinished trace
(never valid JSON) used to reach `json.loads` and fail. Applied only
after `_THINK_BLOCK_RE` finds no *closed* pair, so a normal closed
block is never double-processed. Strips from the dangling `<think>` to
the end, same as a closed block would once it closes — leaves nothing
recoverable (there genuinely is no answer in a truncated trace), so
this still surfaces as a real `LLMUnavailable`/fallback, it just fails
fast with an accurate message instead of a confusing "non-JSON
response" dump of a half-finished reasoning trace."""

def _extract_json_object(text: str) -> str:
    """Best-effort recovery for a completion that's *almost* a bare JSON
    object but has stray text wrapped around it — a small/hybrid-
    reasoning model asked NOT to think can still occasionally prepend
    ("Sure, here's the response:") or append commentary despite the
    system prompt's explicit instruction, or leak a fragment of
    reasoning outside a well-formed `<think>...</think>` pair (so
    `_THINK_BLOCK_RE` above never matches it). Returns the substring
    from the first `{` to the last `}` when both exist and the slice is
    non-trivial; otherwise returns `text` unchanged so the caller's own
    `json.loads` raises its normal, accurately-worded error. Cheap and
    a no-op for the common case (a response that's already bare JSON —
    `start == 0` and `end == len(text) - 1`)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start : end + 1]


_SENTENCE_END_RE = re.compile(r"[.!?][\"'’”)]?(?:\s|$)")
"""v1.4.4: matches the end of a complete sentence (terminal punctuation,
optionally followed by a closing quote/paren) — used by `_trim_
truncated_string` to find the last point a maxLength-truncated
completion can be cut back to without leaving a dangling mid-word/
mid-clause fragment."""


def _trim_truncated_string(text: str) -> str:
    """A `json_schema`'s `maxLength` is enforced by the sampler at the
    character level — the grammar force-closes the JSON string (and the
    object around it) the instant the cap is hit, with no chance for the
    model to wrap up its sentence first. A live review pack showed this
    exact shape twice: `mind.voice` ("...a whisper that remains, a
    rhythm,") and `chronicle.summary` ("...ends not with fanfare but
    with") — both stop mid-clause, both land within a couple characters
    of that field's declared `maxLength`. Only called on a string whose
    length is at/near its schema cap (see `_trim_truncated_strings`), so
    a normal short answer that just happens to end without punctuation
    is never touched. Trims to the last complete sentence if one exists;
    otherwise falls back to the last complete word before an obviously
    dangling trailing comma/fragment. Never raises, never returns empty
    on non-empty input — worst case returns the input unchanged."""
    if not text:
        return text
    matches = list(_SENTENCE_END_RE.finditer(text))
    if matches:
        return text[: matches[-1].end()].rstrip()
    # No complete sentence at all (short phrase-style fields like
    # `voice`) — drop the trailing dangling word/comma fragment instead.
    trimmed = text.rstrip().rstrip(",")
    last_space = trimmed.rfind(" ")
    if last_space > 0:
        trimmed = trimmed[:last_space]
    return trimmed.rstrip().rstrip(",") or text


def _trim_truncated_strings(parsed, schema: dict | None):
    """Walks a parsed JSON-schema-constrained result's top-level string
    properties and trims any value that hit (or came within a couple
    characters of) its declared `maxLength` — see `_trim_truncated_
    string`'s docstring for why. A no-op when there's no schema (nothing
    to compare a length against — an unconstrained call can ramble but
    was never sampler-truncated mid-clause the way a maxLength cap can)
    or the parsed result isn't a dict (defensive; every task schema in
    `llm/json_schemas.py` is object-shaped, but this must never raise on
    a surprise shape)."""
    if not schema or not isinstance(parsed, dict):
        return parsed
    properties = schema.get("properties", {})
    for key, spec in properties.items():
        max_length = spec.get("maxLength") if isinstance(spec, dict) else None
        if max_length is None:
            continue
        value = parsed.get(key)
        if not isinstance(value, str) or len(value) < max_length - 2:
            continue
        parsed[key] = _trim_truncated_string(value)
    return parsed


_REASONING_OFF_PROMPT = "detailed thinking off"
_REASONING_ON_PROMPT = "detailed thinking on"
"""NVIDIA Nemotron 3's documented reasoning-mode toggle (default model
as of this pass, see `Config.llm_model`): unlike Qwen3's hybrid-
thinking mode (controlled via Ollama's own `"think"` API field, still
sent below), Nemotron 3 controls its `<think>` chain-of-thought purely
through this exact phrase appearing in the system prompt — it must be
the model's first-seen instruction, so it's prepended, never appended.
Harmless boilerplate for any other model family (ignored as ordinary
text), so this is sent on every call regardless of which model is
actually loaded — no backend/model-detection branch needed. `generate_
json`'s new `reasoning` param selects which phrase: `False` (the
default, every routine strict-JSON task) asks for a fast direct answer;
`True` is reserved for a job that has genuinely benefited from a real
reasoning trace before committing to an answer (`deep_reasoning=True`
call sites, `_schedule_llm_job`'s docstring) — never combined with a
`json_schema` grammar (see that param's own note), since a grammar
enforces the FULL output shape from the first token and would suppress
a preceding `<think>` block entirely; `_schedule_llm_job` only ever
passes `reasoning=True` when `schema_for_task` returned `None` for
that job.

**v1.4.3 fix — the prompt phrase alone is not enough.** A live review
pack (`--reasoning auto` server default since v1.3.37) showed
`reasoning=False` tasks — including plain `mind`, never a `deep_
reasoning` job — erroring out almost 100% of the time (`calls_errored`
5/5, avg latency ~114s against a measured ~11 tok/s decode rate, i.e.
~1280 tokens generated against a 512 `max_tokens` request). Root
cause: `--reasoning auto` leaves the server's own reasoning budget
open regardless of what the system prompt asks for — this model does
not reliably honor "detailed thinking off" as a hard stop, so it kept
generating a `<think>` trace that ran the completion past `max_tokens`
with no JSON ever emitted (an unclosed `<think>` block, invisible to
`_THINK_BLOCK_RE`, which only matches a *closed* pair). The prompt
phrase alone was a soft hint the model could ignore; both clients below
now also assert `reasoning=False` at the request level (`llama-server`'s
`reasoning_budget: 0`/Ollama-compatible `chat_template_kwargs.
enable_thinking: false` — mirrors the already-proven `--reasoning-budget
0` CLI flag, this is its per-request equivalent), which is enforced by
the sampler rather than merely requested of the model."""


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


class LLMTimeout(LLMUnavailable):
    """v1.4.4: a genuine socket-level timeout, raised distinctly from the
    generic `LLMUnavailable` so `CognitionRunner._run_gated` can count it
    as `calls_timed_out` instead of `calls_errored` — see that class's
    docstring for the live-diagnosed bug this fixes. Before this, EVERY
    timeout was misclassified: `urlopen(..., timeout=self.timeout_
    seconds)` always expires before the outer `asyncio.wait_for(...,
    timeout=self.client.timeout_seconds + 5.0)` in jobs.py ever gets a
    chance to fire (the inner socket timeout is strictly smaller), so a
    slow call always raised plain `LLMUnavailable` from this module and
    the `calls_timed_out` counter stayed permanently at 0 in every live
    diagnostic to date — real timeouts were invisible as a distinct
    failure mode, indistinguishable from a parse error or connection
    refusal. Still an `LLMUnavailable` subclass, so any existing `except
    LLMUnavailable` catch-all still absorbs it correctly; only jobs.py's
    now more specific `except LLMTimeout` branch (checked first) changes
    behavior."""


class LLMAdapter(ABC):
    """The ENTIRE contract between Hearthmind and any local LLM backend.

    Explicit user directive: "adding a new LLM requires implementing only
    a single adapter class. No changes should be needed anywhere else in
    the codebase." This class IS that single seam — `CognitionRunner`
    (llm/jobs.py), `_schedule_llm_job`/`_run_cognition`/`_run_dialogue`
    (simulation/engine.py), and every prompt/parse module under `llm/`
    only ever call `adapter.generate_json(...)` on whatever object
    `build_llm_client(config)` handed them. None of them import
    `OllamaClient`/`LlamaCppClient` by name, know a backend's wire
    protocol, or branch on `config.llm_backend` themselves — that
    dispatch lives ENTIRELY in `_ADAPTER_REGISTRY`/`build_llm_client`
    below. A brand-new backend (a different local server, a hosted API,
    a future in-process runtime) needs exactly three things: (1) a class
    inheriting `LLMAdapter`, (2) a real `generate_json` implementing this
    contract against that backend's actual wire format, (3) one line
    registering it in `_ADAPTER_REGISTRY`. Simulation logic, cognition
    prompts, JSON-schema validation, memory, and every game system stay
    completely unaware — they only ever see "a dict came back, or it
    didn't."

    Every adapter must:
    - Accept the exact `generate_json` signature below (positional-
      compatible with every existing call site — `CognitionRunner._run_
      gated` calls it via `asyncio.to_thread` with positional args).
    - Do its own blocking I/O (no async) — the runner is what wraps this
      in a thread; an adapter must never assume an event loop.
    - Raise `LLMUnavailable` (or `LLMTimeout`, its more specific socket-
      timeout subclass) on ANY failure — network error, malformed
      response shape, non-JSON completion. Must NEVER raise anything
      else out to the runner and must NEVER return a value that isn't a
      plain `dict` (the parsed JSON answer).
    - Fill `capture["raw"]` with the exact raw completion text, if a
      `capture` dict was given, BEFORE attempting to parse it as JSON —
      so a malformed-JSON response still leaves the raw text recoverable
      for the training recorder and the fallback-diagnostics dev-console
      panel even though the call still raises.
    - Honor `reasoning` (whatever this model's own hybrid-thinking
      toggle is, or a no-op if the model has none) and never combine a
      `True` value with a non-`None` `json_schema` (grammar-constrained
      decoding structurally suppresses a preceding `<think>` block —
      `_schedule_llm_job` already enforces this at the call site, but an
      adapter should not assume every future caller will).

    `build_from_config` is the second half of the contract — a
    classmethod that knows how to construct this adapter from the
    project's own `Config` object, so `build_llm_client` never needs a
    per-field constructor call hand-rolled for each backend."""

    @abstractmethod
    def generate_json(
        self, prompt: str, system: str | None = None, capture: dict | None = None,
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
        reasoning: bool = False, timeout_override: float | None = None,
        seed_override: int | None = None,
    ) -> dict:
        """Blocking call — issue one request to the backend and return
        the parsed JSON response as a plain dict. See the class
        docstring above for the full contract every implementation must
        honor. Callers running inside the event loop must wrap this in
        `asyncio.to_thread`; this method itself must do no async work.

        `seed_override` (v1.34.276, HearthBench A2.1): both backends'
        wire protocols already accept a per-request `seed` — added here,
        appended last so every existing positional call site (`llm/
        jobs.py`'s `asyncio.to_thread(self.client.generate_json, ...)`)
        stays byte-identical with `None` implicitly supplied. No live
        Hearthmind call site sets this yet (determinism/reproducibility
        is explicitly not a project requirement — see CLAUDE.md's
        workflow rules); it exists so `hearthbench.adapters.ModelAdapter`
        implementations wrapping these classes can honestly report
        `capabilities().seed = True` instead of a false `False` for a
        capability the backend genuinely has."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def build_from_config(cls, config) -> "LLMAdapter":
        """Construct this adapter from the project's `Config` object.
        The one place a new adapter's own config fields get read —
        `build_llm_client` below never needs to know what they are."""
        raise NotImplementedError


@dataclass
class OllamaClient(LLMAdapter):
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

    @classmethod
    def build_from_config(cls, config) -> "OllamaClient":
        """See `LLMAdapter.build_from_config` — the one place this
        adapter's own `Config` fields get read."""
        return cls(
            host=config.llm_host, model=config.llm_model, timeout_seconds=config.llm_timeout_seconds,
            num_ctx=config.llm_num_ctx, num_predict=config.llm_num_predict,
            keep_alive=config.llm_keep_alive, use_mmap=config.llm_use_mmap, num_gpu=config.llm_num_gpu,
            num_thread=config.llm_num_thread, temperature=config.llm_temperature,
        )

    def generate_json(
        self, prompt: str, system: str | None = None, capture: dict | None = None,
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
        reasoning: bool = False, timeout_override: float | None = None,
        seed_override: int | None = None,
    ) -> dict:
        """Blocking call — issue one generate request and parse the
        response as JSON. Callers running inside the event loop must wrap
        this in `asyncio.to_thread` (see hearthmind/llm/jobs.py); this
        method itself does no async work.

        `seed_override`: sent as `options["seed"]` when given — see
        `LLMAdapter.generate_json`'s docstring for why this exists.
        `None` (every live call site) omits it, server default.

        `timeout_override` (v1.4.4, companion to `num_predict_override`):
        a `reasoning=True` call legitimately generates more tokens (a
        `<think>` trace plus the answer) and so legitimately takes
        longer — `_schedule_llm_job` scales this proportionally to its
        own `num_predict_override` so the socket timeout doesn't cut off
        a call that's genuinely still working, not stuck. `None` (every
        non-reasoning call) keeps using `self.timeout_seconds`.

        `reasoning` (see `_REASONING_OFF_PROMPT`/`_REASONING_ON_PROMPT`):
        prepends Nemotron 3's system-prompt reasoning toggle AND sets
        Ollama's native `"think"` field to match — two different
        models' hybrid-thinking controls (Nemotron's is prompt-text,
        Qwen3's is this API field), sent together since each is inert
        for the other model family, so both can stay on regardless of
        which is actually loaded.

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
        if seed_override is not None:
            options["seed"] = seed_override
        reasoning_prefix = _REASONING_ON_PROMPT if reasoning else _REASONING_OFF_PROMPT
        effective_system = f"{reasoning_prefix}\n{system}" if system else reasoning_prefix
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": json_schema if json_schema is not None else "json",
            "stream": False,
            "think": reasoning,
        }
        if options:
            payload["options"] = options
        payload["system"] = effective_system
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        effective_timeout = timeout_override if timeout_override is not None else self.timeout_seconds
        request = urllib.request.Request(
            f"{self.host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise LLMTimeout(f"Ollama request timed out after {effective_timeout}s: {exc}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMTimeout(f"Ollama request timed out after {effective_timeout}s: {exc}") from exc
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"Ollama request failed: {exc}") from exc

        raw_response = body.get("response", "")
        if not _THINK_BLOCK_RE.search(raw_response):
            raw_response = _UNCLOSED_THINK_RE.sub("", raw_response)
        raw_response = _THINK_BLOCK_RE.sub("", raw_response).strip()
        if capture is not None:
            capture["raw"] = raw_response
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            parsed = None
        if parsed is None:
            try:
                parsed = json.loads(_extract_json_object(raw_response))
            except json.JSONDecodeError as exc:
                raise LLMUnavailable(f"Ollama returned non-JSON response: {raw_response!r}") from exc
        return _trim_truncated_strings(parsed, json_schema)


@dataclass
class LlamaCppClient(LLMAdapter):
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

    **This is the Nemotron 3 Nano 4B-tuned adapter** (the project default
    model as of v1.3.36, `Config.llm_model`). It is deliberately NOT a
    separate "NemotronAdapter" subclass — this class already IS the code
    path every default install runs, and Nemotron's actual requirements
    (the "detailed thinking on/off" system-prompt toggle, `reasoning_
    budget`/`enable_thinking` request fields, letting llama-server's own
    GGUF-embedded chat template handle role formatting rather than this
    project hand-rolling one) are already implemented directly below —
    adding a parallel, unused subclass would just be dead code duplicating
    the one path that actually runs. Everything model-specific about
    Nemotron 3 lives in `_REASONING_ON_PROMPT`/`_REASONING_OFF_PROMPT`
    (module-level, both clients) and this class's own `generate_json`;
    switching `Config.llm_model` to a different GGUF (or `Config.llm_
    backend` to `"ollama"`) needs no further code change — see `LLMAdapter`'s
    class docstring for the "one class, nothing else changes" contract
    this whole module exists to satisfy. (The upstream model card's own
    recommended sampling values could not be independently confirmed in
    this environment — outbound fetches to huggingface.co were blocked —
    so `temperature`/`top_p`/`min_p` below stay whatever this project's
    own live-diagnostic tuning has already measured, per CLAUDE.md's
    standing "live user reports over unverified specs" discipline, not a
    number copied from an unread page.)
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
    top_p: float | None = None
    """Optional nucleus-sampling cutoff (see `Config.llm_top_p`), sent as
    the OpenAI-compatible `top_p` field alongside `temperature`. `None`
    (the default) omits it, leaving llama-server's own default (1.0, i.e.
    off) in place — this project has no measured live-diagnostic basis
    for a specific value yet (see the class docstring above), so it's
    exposed as a real, wired lever rather than a guessed default."""
    min_p: float | None = None
    """Optional min-p sampling cutoff (see `Config.llm_min_p`) — sent as
    a top-level `min_p` field, llama-server's own extension beyond the
    bare OpenAI chat-completions schema (ignored by a server build that
    doesn't recognize it). Same "wired but unset until measured" posture
    as `top_p`."""

    @classmethod
    def build_from_config(cls, config) -> "LlamaCppClient":
        """See `LLMAdapter.build_from_config` — the one place this
        adapter's own `Config` fields get read."""
        return cls(
            host=config.llm_llamacpp_host, model=config.llm_model,
            timeout_seconds=config.llm_timeout_seconds, num_predict=config.llm_num_predict,
            temperature=config.llm_temperature, top_p=config.llm_top_p, min_p=config.llm_min_p,
        )

    def generate_json(
        self, prompt: str, system: str | None = None, capture: dict | None = None,
        json_schema: dict | None = None,
        num_predict_override: int | None = None, temperature_override: float | None = None,
        reasoning: bool = False, timeout_override: float | None = None,
        seed_override: int | None = None,
    ) -> dict:
        """Blocking call — issue one `/v1/chat/completions` request and
        parse the response as JSON. Callers running inside the event loop
        must wrap this in `asyncio.to_thread` (see hearthmind/llm/jobs.py);
        this method itself does no async work. Uses the OpenAI-compatible
        chat endpoint (not llama.cpp's raw `/completion`) so the server's
        own chat template handles system/user role formatting correctly
        per-model, matching how `OllamaClient` separates `system`/`prompt`
        without this project needing to know each model's prompt format.

        `seed_override`: sent as the top-level OpenAI-compatible `seed`
        field when given — see `LLMAdapter.generate_json`'s docstring for
        why this exists. `None` (every live call site) omits it, server
        default (a fresh seed per call).

        `timeout_override`: see `OllamaClient.generate_json`'s docstring
        — same contract (`None` keeps `self.timeout_seconds`).

        `capture`: see `OllamaClient.generate_json`'s docstring — same
        contract (fresh dict per call, filled with `capture["raw"]`).

        `reasoning`: see `OllamaClient.generate_json`'s docstring for the
        Nemotron 3 rationale — this client has no per-request analog of
        Ollama's `"think"` field (llama-server's reasoning control is a
        server-launch flag, `LLAMA_REASONING`/`--reasoning`, see the
        README), so the system-prompt phrase is the only per-call lever
        here. Never pass `reasoning=True` alongside `json_schema` — see
        `_REASONING_ON_PROMPT`'s docstring for why.

        `json_schema` (optional, FT.0 — docs/AUDIT-2026-07-20.md, see
        `llm/json_schemas.py`): when given, requests `response_format:
        {"type": "json_schema", ...}` instead of the bare `json_object`
        mode — llama-server converts the schema to a GBNF grammar and
        enforces it at the sampler level, so a call with a schema can no
        longer emit a missing required key, a wrong-typed value, or an
        out-of-enum string; it was already structurally guaranteed valid
        JSON, this narrows that guarantee to the actual expected shape.
        `None` keeps the old bare `json_object` behavior unchanged."""
        reasoning_prefix = _REASONING_ON_PROMPT if reasoning else _REASONING_OFF_PROMPT
        effective_system = f"{reasoning_prefix}\n{system}" if system else reasoning_prefix
        messages = [{"role": "system", "content": effective_system}]
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
        if not reasoning:
            # v1.4.3: hard-disable reasoning for this specific request,
            # rather than trusting the system-prompt phrase alone — see
            # `_REASONING_OFF_PROMPT`'s docstring for the live-diagnosed
            # failure this fixes. `reasoning_budget` mirrors `scripts/
            # run.sh`'s already-proven `--reasoning-budget 0` CLI flag as
            # its per-request equivalent; `chat_template_kwargs.enable_
            # thinking` covers templates (Qwen3-family included) that key
            # off that variable instead. Both are additive/ignored by a
            # server build or template that doesn't recognize them, so
            # this is safe even if one of the two levers is a no-op on a
            # given llama-server version — never sent when reasoning=True
            # (a deep_reasoning job wants the server's configured budget,
            # set once via `--reasoning`, not overridden per-call here).
            payload["reasoning_budget"] = 0
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        effective_num_predict = num_predict_override if num_predict_override is not None else self.num_predict
        if effective_num_predict is not None:
            payload["max_tokens"] = effective_num_predict
        effective_temperature = temperature_override if temperature_override is not None else self.temperature
        if effective_temperature is not None:
            payload["temperature"] = effective_temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.min_p is not None:
            payload["min_p"] = self.min_p
        if seed_override is not None:
            payload["seed"] = seed_override

        effective_timeout = timeout_override if timeout_override is not None else self.timeout_seconds
        request = urllib.request.Request(
            f"{self.host.rstrip('/')}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise LLMTimeout(f"llama.cpp request timed out after {effective_timeout}s: {exc}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMTimeout(f"llama.cpp request timed out after {effective_timeout}s: {exc}") from exc
            raise LLMUnavailable(f"llama.cpp request failed: {exc}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"llama.cpp request failed: {exc}") from exc

        try:
            raw_response = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"llama.cpp returned an unexpected response shape: {body!r}") from exc

        raw_response = raw_response or ""
        if not _THINK_BLOCK_RE.search(raw_response):
            raw_response = _UNCLOSED_THINK_RE.sub("", raw_response)
        raw_response = _THINK_BLOCK_RE.sub("", raw_response).strip()
        if capture is not None:
            capture["raw"] = raw_response
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            parsed = None
        if parsed is None:
            try:
                parsed = json.loads(_extract_json_object(raw_response))
            except json.JSONDecodeError as exc:
                raise LLMUnavailable(f"llama.cpp returned non-JSON content: {raw_response!r}") from exc
        return _trim_truncated_strings(parsed, json_schema)


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


ADAPTER_REGISTRY: dict[str, type[LLMAdapter]] = {
    "ollama": OllamaClient,
    "llamacpp": LlamaCppClient,
}
"""The single-source-of-truth mapping `Config.llm_backend` -> adapter
class — see `LLMAdapter`'s class docstring for the "one class, nothing
else changes" contract this exists to satisfy. **Adding support for a
new local LLM backend is exactly two steps**: (1) write a class
inheriting `LLMAdapter` (implementing `generate_json`/`build_from_
config`) anywhere importable, (2) add one line here:
`ADAPTER_REGISTRY["my_backend"] = MyAdapter`. Nothing in `llm/jobs.py`,
`simulation/engine.py`, or any prompt/parse module under `llm/` needs to
change — they only ever hold an `LLMAdapter` reference and call
`.generate_json(...)` on it. Set `Config.llm_backend = "my_backend"` to
select it."""


def build_llm_client(config) -> LLMAdapter:
    """Factory used by both `SimulationEngine` and `server.py` so the two
    call sites can't drift on which fields each backend actually
    consumes (see docs/DECISIONS.md, "llama.cpp default backend"). Only
    ever called when `config.llm_enabled` is true. Looks up `config.
    llm_backend` in `ADAPTER_REGISTRY` and delegates construction to that
    adapter's own `build_from_config` — this function itself has no
    per-backend branch or knowledge of any adapter's constructor fields,
    which is what makes registering a brand-new adapter a one-line
    change instead of a change here too."""
    try:
        adapter_cls = ADAPTER_REGISTRY[config.llm_backend]
    except KeyError:
        raise ValueError(
            f"Unknown llm_backend {config.llm_backend!r} — must be one of {sorted(ADAPTER_REGISTRY)} "
            "(or register a new adapter in hearthmind.llm.client.ADAPTER_REGISTRY)"
        ) from None
    return adapter_cls.build_from_config(config)
