"""HearthBench A6.2 — record the full repair ladder per call, with a
reason at each rung.

Works purely off an already-real `AdapterResult`'s own `text`/`parsed`/
`error` fields, uniformly across every A2.2 adapter (LlamaCpp/Ollama/
OpenAICompat) — no per-adapter instrumentation needed, since each
adapter's own internal recovery step (Ollama/LlamaCpp: `hearthmind.
llm.client.generate_json`'s repair chain; OpenAICompat: its own
self-contained `_best_effort_json`) is opaque from here by design (see
`hearthbench/adapters/openai_compat.py`'s own docstring on why
OpenAICompat doesn't import `hearthmind.llm.client`'s private helpers).
Rather than reverse-engineer which specific internal mechanism ran, this
module answers the one question every adapter's `AdapterResult` can
always honestly answer: did a bare `json.loads` of the raw completion
text land on the exact object `AdapterResult.parsed` already holds? If
so, no repair happened. If `parsed` is a real dict/list but the bare
parse didn't produce it, SOME recovery step ran upstream, whatever it
was. If `parsed` is `None`, nothing was ever recoverable.

Import isolation (A1.2): stdlib only.
"""
from __future__ import annotations

import json

REPAIR_RUNGS = ("raw", "repaired", "failed")
"""The three rungs this module can classify a call as landing on. Not
`"schema"`/`"fallback"` as separate rungs — per A2.1's own contract,
`AdapterResult` never fabricates a fallback value (that's the live
sim's own `llm/client.py` concern, out of scope for a benchmark call);
schema *conformance* is a separate, later question (A4.1's `schema_
validity` scorer already answers it) from whether the text parsed as
JSON at all, which is what this ladder is about."""


def classify_repair(text: str, parsed: "dict | list | None", error: "str | None" = None) -> dict:
    """Returns `{"rung", "reason", "parse_repaired"}`. `parse_repaired`
    mirrors `CaseResult`'s own pre-existing bool field exactly (`True`
    iff `rung == "repaired"`) so a caller needing just the boolean
    doesn't have to compare strings — this function is the real
    computation that field always should have had (it was previously
    hardcoded `False` in `CaseResult.from_adapter_result`, a stub A6.2
    closes)."""
    if error:
        return {"rung": "failed", "reason": f"backend error: {error}", "parse_repaired": False}
    if parsed is None:
        return {
            "rung": "failed",
            "reason": "no valid JSON was recoverable from the completion text",
            "parse_repaired": False,
        }
    try:
        bare = json.loads((text or "").strip())
    except (json.JSONDecodeError, ValueError):
        bare = None
    if bare == parsed:
        return {
            "rung": "raw",
            "reason": "a bare json.loads of the completion text parsed on the first try",
            "parse_repaired": False,
        }
    return {
        "rung": "repaired",
        "reason": "the completion text needed recovery (e.g. wrapped in stray prose, or a "
        "differently-formed JSON object) before it matched the parsed result",
        "parse_repaired": True,
    }
