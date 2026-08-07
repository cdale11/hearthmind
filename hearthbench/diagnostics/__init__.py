"""Run diagnostics (A8): one directory per run (JSONL + manifest),
environment capture, content-addressed prompt/completion storage,
retention policy.

A8.1/A8.2/A8.3/A8.4 shipped this pass (`run_record.py`): `RunRecordWriter`/
`RunRecordReader` (a real run directory, one JSONL line per case,
committed immediately, never batched), `build_environment_snapshot`
(A2's `AdapterDescribe`/`AdapterCapabilities` reused directly), `BlobStore`
(sha256-keyed, deduplicated prompt/completion storage), `prune_run`
(the one explicit-only deletion path — nothing here auto-deletes).
This is the real mechanism behind A11.4 (resume, `hearthbench.runner.
run.run_cases_with_resume`) and A7.1 (recomputable aggregates,
`hearthbench.metrics.aggregate.recompute_run_metrics`).
"""
from __future__ import annotations

from hearthbench.diagnostics.run_record import (
    BlobStore,
    CaseRecord,
    RunRecordReader,
    RunRecordWriter,
    build_environment_snapshot,
    prune_run,
)

__all__ = [
    "BlobStore", "CaseRecord", "RunRecordReader", "RunRecordWriter",
    "build_environment_snapshot", "prune_run",
]
