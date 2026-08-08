"""HearthBench A6.1 — reuse `hearthmind.llm.json_schemas` directly so
bench validation is identical to production validation, per the
checklist's own literal text ("via the shared contract package").

The shared `hearthmind.cognition_contract` package the checklist
envisions doesn't exist yet (see `docs/HEARTHBENCH-RUNTIME-2026-07-
23.md`'s A0's own still-open "Rule" item) — this module ships the real
achievable slice today: `hearthmind.llm.json_schemas` is NOT one of
A1.2's three banned modules (`hearthmind.simulation`/`.agents`/
`.world`), so importing it directly is legal, real reuse of
production's own per-task schemas, not a duplicate copy that could
drift out of sync. Migrating this single import onto a future shared
package, once one exists, needs no change here beyond the import line.

Import isolation (A1.2): `hearthmind.llm.json_schemas` only — a pure,
dependency-free data module (see that module's own docstring), no
`hearthmind.simulation`/`.agents`/`.world` reached transitively.
"""
from __future__ import annotations

from hearthmind.llm.json_schemas import schema_for_task


def resolve_schema(schema_ref: "str | None") -> "dict | None":
    """`TestCase.schema_ref` -> a real JSON Schema, or `None` when the
    ref is empty/falsy or names a task with no schema entry (`schema_
    for_task` itself already returns `None` for the latter — this
    wrapper exists to give A6 its own named, testable entry point
    rather than every caller reaching into `hearthmind.llm.json_
    schemas` directly, and to be the one place a future migration onto
    a shared `cognition_contract` package would change)."""
    if not schema_ref:
        return None
    return schema_for_task(schema_ref)
