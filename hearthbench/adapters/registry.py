"""HearthBench A2.2 — the adapter registry.

Mirrors `hearthmind.llm.client.ADAPTER_REGISTRY`/`build_llm_client`'s
own shape (a plain name -> class dict + one factory function) for a
distinct reason: bench adapters are constructed from explicit CLI/
config arguments a run specifies (host, model, endpoint, ...), never
from a live `hearthmind.Config` object the way the sim-side factory
is — there is no `hearthmind.Config` a benchmark run should depend on
(that would reach toward `hearthmind.simulation`, tripping A1.2's
firewall). Adding a fourth backend needs exactly one class + one
registry line here, same "adding a new LLM requires implementing only
a single adapter class" contract as the sim-side registry.
"""
from __future__ import annotations

from .llamacpp import LlamaCppAdapter
from .ollama import OllamaAdapter
from .openai_compat import OpenAICompatAdapter
from .protocol import ModelAdapter

ADAPTER_REGISTRY: dict[str, type] = {
    "llamacpp": LlamaCppAdapter,
    "ollama": OllamaAdapter,
    "openai_compat": OpenAICompatAdapter,
}
"""backend name -> adapter class. `build_adapter` below is the only
consumer expected to read this directly; a caller who already holds a
constructed adapter instance never needs to touch it."""


def build_adapter(backend: str, **kwargs) -> ModelAdapter:
    """Construct an adapter by backend name. `**kwargs` are forwarded
    verbatim to the chosen class's `__init__` — each adapter's own
    constructor signature is the real, single source of truth for what
    it needs (host/model/timeout_seconds for `llamacpp`/`ollama`;
    endpoint/model/api_key/supports_json_schema for `openai_compat`),
    so this function itself carries no per-backend field list to drift
    out of sync."""
    try:
        adapter_cls = ADAPTER_REGISTRY[backend]
    except KeyError:
        raise ValueError(
            f"Unknown adapter backend {backend!r} — must be one of {sorted(ADAPTER_REGISTRY)} "
            "(or register a new adapter in hearthbench.adapters.registry.ADAPTER_REGISTRY)"
        ) from None
    return adapter_cls(**kwargs)
