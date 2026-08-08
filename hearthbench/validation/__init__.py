"""Structured output validator (A6) — SHIPPED, v1.34.289.

`schema_resolver.resolve_schema` (A6.1): reuses `hearthmind.llm.
json_schemas` directly, wired into `hearthbench.runner.run._execute_
case` so `TestCase.schema_ref` now genuinely requests schema-
constrained decoding, not just gets scored against a schema
afterward (A4.1's `schema_validity` already did the latter).

`repair_ladder.classify_repair` (A6.2): the real raw -> parse ->
repair -> fallback classification per call, computed off an already-
real `AdapterResult`'s own `text`/`parsed`/`error` — wired into
`hearthbench.scoring.types.CaseResult.from_adapter_result` (replacing
a hardcoded `parse_repaired=False` stub) and threaded through to
`hearthbench.diagnostics.run_record.CaseRecord`'s new `repair_rung`/
`repair_reason` fields, so a run's own committed record carries the
real reason at each rung, not just a bare boolean.

`dual_mode.run_case_dual_mode` (A6.3): scores a case in BOTH
constrained and unconstrained modes when the adapter supports it,
reporting a real per-scorer delta — genuinely opt-in (two real calls
per case), distinct from the fast single-call default every ordinary
run still uses.

Not left as a module reserved by the A1 package skeleton anymore.
"""
