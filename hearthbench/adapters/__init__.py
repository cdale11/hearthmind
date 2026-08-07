"""Model adapters (A2) — SHIPPED, v1.34.276.

A2.1 `ModelAdapter` Protocol (`protocol.py`, formalizing the existing
`hearthmind.llm.client.build_llm_client` factory, A0.1's own "reuse,
don't rebuild"); A2.2 three adapters at launch (`LlamaCppAdapter`,
`OllamaAdapter`, `OpenAICompatAdapter`) + `registry.build_adapter`;
A2.3 the conformance suite (`conformance.py`); A2.4 server lifecycle
management (`lifecycle.py`). See each submodule's own docstring for
full detail.
"""
from .conformance import ConformanceCheckResult, ConformanceReport, run_conformance_suite
from .lifecycle import LaunchRecord, ServerLifecycle, build_llama_server_command
from .llamacpp import LlamaCppAdapter
from .ollama import OllamaAdapter
from .openai_compat import OpenAICompatAdapter
from .protocol import (
    AdapterCapabilities,
    AdapterDescribe,
    AdapterResult,
    HealthStatus,
    ModelAdapter,
)
from .registry import ADAPTER_REGISTRY, build_adapter

__all__ = [
    "ADAPTER_REGISTRY",
    "AdapterCapabilities",
    "AdapterDescribe",
    "AdapterResult",
    "ConformanceCheckResult",
    "ConformanceReport",
    "HealthStatus",
    "LaunchRecord",
    "LlamaCppAdapter",
    "ModelAdapter",
    "OllamaAdapter",
    "OpenAICompatAdapter",
    "ServerLifecycle",
    "build_adapter",
    "build_llama_server_command",
    "run_conformance_suite",
]
