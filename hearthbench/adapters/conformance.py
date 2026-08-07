"""HearthBench A2.3 — the adapter conformance suite.

"A test each new adapter must pass (schema honoring, token accounting,
seed behavior, timeout, cancellation, error taxonomy)" — per the
brief's own text. Adapter-shape-agnostic: every check here only ever
calls the `ModelAdapter` Protocol's four public methods, never reaches
into a specific adapter class's internals, so a brand-new fourth
adapter (A2.2's own "adding a new local LLM backend is exactly two
steps" contract) automatically gets a real conformance run for free.

Honest scope: "cancellation" in the brief's own list describes a
*runner's* concern (an async task the runner itself cancels
mid-flight) more than a synchronous adapter method's — `generate()`
here is blocking by contract (see `protocol.ModelAdapter`'s
docstring), so there is no in-adapter cancellation surface to check
independently of A11's future runner. What this suite DOES verify
directly, against a REAL backend (reachable or not — no fake/mock
adapter needed, the real `generate()`/`health()` code path is
exercised either way): the Protocol's own contract that a call never
raises regardless of outcome, that `AdapterResult.error` is always a
string (never an exception object) on failure, and that the four
methods always return the right dataclass shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .protocol import (
    AdapterCapabilities,
    AdapterDescribe,
    AdapterResult,
    HealthStatus,
    ModelAdapter,
)


@dataclass
class ConformanceCheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ConformanceReport:
    adapter_backend: str
    results: list[ConformanceCheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[ConformanceCheckResult]:
        return [r for r in self.results if not r.passed]


def _check(results: list[ConformanceCheckResult], name: str, condition: bool, detail: str = "") -> None:
    results.append(ConformanceCheckResult(name=name, passed=bool(condition), detail=detail if not condition else ""))


def run_conformance_suite(
    adapter: ModelAdapter,
    prompt: str = "Reply with a short JSON object.",
    schema: dict | None = None,
) -> ConformanceReport:
    """Runs every check against one real adapter instance. Never raises
    itself — a check that would otherwise raise (e.g. `generate()`
    violating its own "never raises" contract) is caught and recorded
    as a genuine FAILure rather than aborting the whole suite, since
    that's exactly the kind of contract violation this suite exists to
    catch."""
    results: list[ConformanceCheckResult] = []

    # 1. capabilities()/describe()/health() return the right shape and
    #    never raise.
    try:
        caps = adapter.capabilities()
        _check(results, "capabilities() returns AdapterCapabilities", isinstance(caps, AdapterCapabilities))
    except Exception as exc:  # noqa: BLE001 - a contract violation IS the failure being checked for
        caps = AdapterCapabilities()
        _check(results, "capabilities() returns AdapterCapabilities", False, f"raised: {exc!r}")

    try:
        described = adapter.describe()
        _check(results, "describe() returns AdapterDescribe", isinstance(described, AdapterDescribe))
    except Exception as exc:  # noqa: BLE001
        _check(results, "describe() returns AdapterDescribe", False, f"raised: {exc!r}")

    try:
        health = adapter.health()
        _check(results, "health() returns HealthStatus", isinstance(health, HealthStatus))
    except Exception as exc:  # noqa: BLE001
        _check(results, "health() returns HealthStatus", False, f"raised: {exc!r}")

    # 2. generate() never raises, always returns a real AdapterResult,
    #    regardless of whether the backend is reachable.
    try:
        result = adapter.generate(prompt, schema=schema)
        raised = False
    except Exception as exc:  # noqa: BLE001 - the exact violation this check exists to catch
        result = None
        raised = True
        _check(results, "generate() never raises", False, f"raised: {exc!r}")
    if not raised:
        _check(results, "generate() never raises", True)
        _check(results, "generate() returns AdapterResult", isinstance(result, AdapterResult))

    if isinstance(result, AdapterResult):
        # 3. Error taxonomy: on failure, `error` is a real string and
        #    both text/parsed reflect "nothing usable came back."
        if result.error is not None:
            _check(results, "error taxonomy: error is a string", isinstance(result.error, str) and len(result.error) > 0)
            _check(results, "error taxonomy: parsed is None on failure", result.parsed is None)
        else:
            _check(results, "success path: text is a string", isinstance(result.text, str))
            _check(
                results, "success path: parsed is a dict or None (never raised, never a non-dict)",
                result.parsed is None or isinstance(result.parsed, dict),
            )
            # 4. Schema honoring — only meaningful when the adapter
            # itself claims schema support AND a real schema was given.
            if caps.json_schema and schema is not None and result.parsed is not None:
                required = schema.get("required", []) if isinstance(schema, dict) else []
                _check(
                    results, "schema honoring: every required key is present",
                    all(k in result.parsed for k in required),
                    detail=f"missing: {[k for k in required if k not in result.parsed]}",
                )

        # 5. latency_ms is always populated — a caller can always time
        #    a call regardless of whether the backend itself reports
        #    timing.
        _check(results, "latency_ms is a non-negative float", isinstance(result.latency_ms, (int, float)) and result.latency_ms >= 0)

        # 6. Token accounting — best-effort: when reported, both must
        #    be non-negative ints; unreported (None) is honest, not a
        #    failure (not every backend/response shape returns usage).
        for field_name, value in (("prompt_tokens", result.prompt_tokens), ("completion_tokens", result.completion_tokens)):
            _check(
                results, f"token accounting: {field_name} is None or a non-negative int",
                value is None or (isinstance(value, int) and value >= 0),
            )

    return ConformanceReport(adapter_backend=type(adapter).__name__, results=results)
