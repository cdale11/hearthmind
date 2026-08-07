"""HearthBench A2.1 — the `ModelAdapter` Protocol.

One interface every backend adapter implements, per docs/HEARTHBENCH-
RUNTIME-2026-07-23.md's own literal spec:

    generate(prompt, system, schema|None, max_tokens, temperature, seed)
        -> AdapterResult(text, parsed, prompt_tokens, completion_tokens,
                         latency_ms, ttft_ms, raw_response, retries)
    capabilities() -> {json_schema, grammar, seed, logprobs,
                       metrics_endpoint}
    describe() -> {model, quantization, context, backend, build_id, ...}
    health() -> ok | error

A `typing.Protocol`, not an ABC — HearthBench never needs to *subclass*
this to get shared behavior (unlike `hearthmind.llm.client.LLMAdapter`,
whose ABC-ness backs a real inheritance hierarchy of two live production
classes); it only needs a structural type every adapter satisfies, so a
future adapter written entirely outside this package (a hosted API a
user wires in themselves) still type-checks without importing anything
from `hearthbench`.

Import isolation (A1.2): this module imports nothing from `hearthmind.
simulation`/`.agents`/`.world` — only stdlib. It is deliberately NOT
`hearthmind.llm.client.LLMAdapter` (a different contract for a
different consumer — the live sim's fire-and-forget async jobs vs. a
benchmark run's need for token counts/TTFT/retry accounting per call)
though the two are intentionally shaped alike so wrapping one inside
the other (see `llamacpp.py`/`ollama.py`) stays a thin, obvious mapping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AdapterResult:
    """One call's full outcome — everything A7 (metrics)/A8
    (diagnostics) need to score and archive a case without a second
    round-trip to the backend. `parsed` is `None` when `text` could not
    be parsed as JSON at all (a genuine result, not an exception —
    HearthBench scores parse failures as data, per A4.1's "parse/retry/
    fallback rate" deterministic scorer, rather than treating them as
    run-aborting errors the way `hearthmind.llm.client.LLMUnavailable`
    does for the live simulation)."""

    text: str
    """The raw completion text, post `<think>`-stripping, pre-parse —
    the exact string an A6 structured-output validator re-checks."""
    parsed: dict | None
    """The parsed JSON object, or `None` if `text` was not valid JSON
    even after best-effort recovery."""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float = 0.0
    """Wall-clock time for this one call, start of request to end of
    response body — always measured, regardless of what the backend
    itself reports (not every backend returns tokens/TTFT)."""
    ttft_ms: float | None = None
    """Time to first token, when the backend/transport can report it
    (streaming responses only — every adapter here uses `stream:
    false` for simplicity, matching `hearthmind.llm.client`'s own
    clients, so this is `None` for all three A2.2 adapters today; a
    real value needs a future streaming-capable adapter)."""
    raw_response: Any = None
    """The backend's own full response body (already-decoded JSON),
    kept for A8's content-addressed storage — never re-fetched later."""
    retries: int = 0
    """How many times this call was internally retried before
    `generate()` returned (e.g. a malformed-JSON recovery re-ask) — 0
    for every adapter shipped this pass, since none retries internally
    yet; a real field for a future adapter that does."""
    error: str | None = None
    """Non-`None` only when the call failed outright (network error,
    timeout, backend error response) — `text`/`parsed` are then both
    empty/`None`. A result object is returned even on failure (never
    an exception) so a benchmark run can score/record a failed case
    the same uniform way as a successful one."""


@dataclass(frozen=True)
class AdapterCapabilities:
    """What a specific adapter+backend combination can actually do —
    lets a test degrade gracefully (A2.1's own stated purpose: "a
    backend without schema support gets scored on raw-JSON validity
    instead of being disqualified") rather than assuming every backend
    supports every feature."""

    json_schema: bool = False
    """Can constrain decoding to a JSON Schema (a GBNF grammar or
    equivalent), not just request "valid JSON in general"."""
    grammar: bool = False
    """Can accept an arbitrary formal grammar beyond JSON Schema (e.g.
    a raw GBNF string) — distinct from `json_schema`, which is the
    narrower, more common case every A2.2 adapter here supports."""
    seed: bool = False
    """Can pin a specific sampling seed per request."""
    logprobs: bool = False
    """Can return per-token log-probabilities."""
    metrics_endpoint: bool = False
    """Has a live, pollable server-side metrics endpoint (e.g.
    llama-server's `/metrics`) beyond what this one call's own
    `AdapterResult` reports."""


@dataclass(frozen=True)
class AdapterDescribe:
    """Static identity of what's actually being benchmarked — recorded
    once per run (A8.2's "environment capture") so a stored result is
    reproducible from the record alone, independent of live process
    state. Every field is `str | None` (not a fixed enum) since a
    backend may not report all of them, and this project has no
    standing opinion on any specific model/backend's naming scheme."""

    model: str | None = None
    quantization: str | None = None
    context: int | None = None
    backend: str | None = None
    build_id: str | None = None
    extra: dict = field(default_factory=dict)
    """Anything backend-specific worth recording that doesn't fit the
    four named fields above (e.g. llama.cpp's own build number, an
    Ollama digest) — additive, never required by any consumer."""


@dataclass(frozen=True)
class HealthStatus:
    """The outcome of `health()` — `ok`/`error` per A2.1's literal
    spec, plus an optional human-readable `detail` for the failure
    case (never required for the healthy case)."""

    ok: bool
    detail: str | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    """A2.1's Protocol. Every method is synchronous/blocking (same
    "no async work inside the adapter" discipline as `hearthmind.llm.
    client.LLMAdapter` — a benchmark runner, not this protocol, owns
    any threading/async wrapping) so a conformance check (A2.3) can
    call these directly with no event loop required."""

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> AdapterResult:
        """Issue one request and return the full result — never raises
        on an ordinary backend failure (network error, timeout,
        malformed response); those land in `AdapterResult.error`
        instead, so a benchmark run can keep scoring the rest of a
        suite. A genuine programming error (a bad argument type) may
        still raise normally."""
        ...

    def capabilities(self) -> AdapterCapabilities:
        """What this adapter+backend combination can do — see
        `AdapterCapabilities`'s own docstring."""
        ...

    def describe(self) -> AdapterDescribe:
        """Static identity of what's being benchmarked — see
        `AdapterDescribe`'s own docstring."""
        ...

    def health(self) -> HealthStatus:
        """A cheap reachability check (never a full `generate()` call)
        — used before a run starts to fail fast with a clear reason
        rather than burning an entire suite against an unreachable
        backend."""
        ...
