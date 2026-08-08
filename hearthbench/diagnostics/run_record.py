"""HearthBench A8 — Run diagnostics: lose nothing.

A8.1 (run record): one directory per run holding a JSONL file (one
`CaseRecord` per completed case, written and fsync'd IMMEDIATELY on
completion — never batched, never held in memory only) plus a
`manifest.json` (A8.2's environment capture + run identity). This is
the mechanism that makes A11.4 (resume, `hearthbench.runner.run.
run_cases_with_resume`) real rather than aspirational: `RunRecord
Reader.completed_case_ids()` is a real read of what a run directory
already has on disk, not a guess held in a caller's own memory that a
crashed process would lose.

A8.2 (environment capture): `build_environment_snapshot` reuses A2's
own `AdapterDescribe`/`AdapterCapabilities` (already exactly what this
item asks for: backend/model/quantization/context, capability flags)
duck-typed off whatever `adapter.describe()`/`.capabilities()` return
— no second identity-capture mechanism invented.

A8.3 (content-addressed storage): `BlobStore` — sha256-keyed files
under `<run_dir>/blobs/`, deduplicated (an identical prompt/completion
recurring across many cases, or across two runs sharing a `blobs/`
directory, is stored once); a `CaseRecord` references prompt/
completion text by hash rather than inlining the full string on every
line, matching the item's own stated intent.

A8.4 (retention policy): permanent by default — nothing in this module
ever deletes a run directory on its own. `prune_run` is the ONE,
explicit-only deletion path, never called by `RunRecordWriter`/
anything in a normal run — the same "explicit refresh/delete only"
discipline A13.4's `save_baseline` already established for this
package.

A7.1 ("all raw values retained... so aggregates can be recomputed
without re-running") is what this module's `CaseRecord`/`RunRecord
Reader` actually make possible — see `hearthbench.metrics.aggregate.
recompute_run_metrics`, which reads a run back through this module and
re-derives category statistics with zero adapter calls.

Import isolation (A1.2): stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BlobStore:
    """A8.3: content-addressed storage for prompt/completion text.

    Deliberately lazy about directory creation: `__init__` touches no
    filesystem state at all (a `BlobStore` behind a real-only-on-write
    `RunRecordReader` must never turn a read into a write) — only
    `put()` ever creates a directory, and only the one it's about to
    write into. `get()` degrades to `None` on a missing/broken path
    (including a `root` that isn't even a real directory) rather than
    raising, the same "never crash a reader on a caller's own bad
    input" discipline this whole package already holds."""

    def __init__(self, root: "str | Path"):
        self.root = Path(root)

    def _path_for(self, digest: str) -> Path:
        return self.root / digest[:2] / f"{digest}.txt"

    def put(self, text: str) -> str:
        """Stores `text`, returns its sha256 hex digest. Writing an
        already-stored blob is a real no-op (the file is left
        untouched, never rewritten) — genuine deduplication, not just
        a content-derived naming scheme."""
        digest = _sha256_hex(text)
        path = self._path_for(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return digest

    def get(self, digest: "str | None") -> "str | None":
        if not digest:
            return None
        try:
            path = self._path_for(digest)
            if not path.exists():
                return None
            return path.read_text(encoding="utf-8")
        except OSError:
            return None


@dataclass
class CaseRecord:
    """A8.1's per-case line — everything about one case's real
    execution, raw. `prompt_hash`/`completion_hash` reference A8.3's
    blob store rather than inlining the text; every other field is
    small enough to store directly. `scores` is `{scorer_id: ScoreDetail.
    to_dict()}` — carries `scorer_version` on each entry, A7.1's own
    "with scorer version" requirement, satisfied via `ScoreDetail`'s
    already-real field rather than a second version-stamping scheme."""

    case_id: str
    category: str
    prompt_hash: "str | None" = None
    completion_hash: "str | None" = None
    parsed_json: "dict | None" = None
    structured_input: dict = field(default_factory=dict)
    fallback_used: bool = False
    parse_repaired: bool = False
    repair_rung: "str | None" = None
    """A6.2's real ladder rung (`"raw"`/`"repaired"`/`"failed"`) — see
    `hearthbench.validation.repair_ladder.classify_repair`."""
    repair_reason: "str | None" = None
    retries: int = 0
    latency_ms: "float | None" = None
    ttft_ms: "float | None" = None
    prompt_tokens: "int | None" = None
    completion_tokens: "int | None" = None
    error: "str | None" = None
    scores: dict = field(default_factory=dict)
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CaseRecord":
        return cls(
            case_id=data["case_id"], category=data.get("category", ""),
            prompt_hash=data.get("prompt_hash"), completion_hash=data.get("completion_hash"),
            parsed_json=data.get("parsed_json"), structured_input=dict(data.get("structured_input") or {}),
            fallback_used=bool(data.get("fallback_used", False)), parse_repaired=bool(data.get("parse_repaired", False)),
            repair_rung=data.get("repair_rung"), repair_reason=data.get("repair_reason"),
            retries=int(data.get("retries", 0) or 0),
            latency_ms=data.get("latency_ms"), ttft_ms=data.get("ttft_ms"),
            prompt_tokens=data.get("prompt_tokens"), completion_tokens=data.get("completion_tokens"),
            error=data.get("error"), scores=dict(data.get("scores") or {}),
            recorded_at=float(data.get("recorded_at") or 0.0),
        )


def build_environment_snapshot(adapter, run_id: str, extra: "dict | None" = None) -> dict:
    """A8.2: capture what's actually being benchmarked. `adapter` is
    duck-typed (anything with `.describe()`/`.capabilities()`, per A2's
    real `ModelAdapter` Protocol) — a caller whose adapter lacks either
    method still gets a real, honest, partially-empty snapshot instead
    of a crash, matching this whole package's "degrade gracefully,
    never fabricate" discipline."""
    describe: dict = {}
    caps: dict = {}
    if hasattr(adapter, "describe"):
        try:
            d = adapter.describe()
            describe = asdict(d) if hasattr(d, "__dataclass_fields__") else dict(d or {})
        except Exception:  # noqa: BLE001 - a broken describe() must never abort a run
            describe = {}
    if hasattr(adapter, "capabilities"):
        try:
            c = adapter.capabilities()
            caps = asdict(c) if hasattr(c, "__dataclass_fields__") else dict(c or {})
        except Exception:  # noqa: BLE001
            caps = {}
    return {
        "run_id": run_id,
        "created_at": time.time(),
        "adapter_describe": describe,
        "adapter_capabilities": caps,
        "extra": dict(extra or {}),
    }


class RunRecordWriter:
    """A8.1: one directory per run. `commit_case` writes immediately —
    open in append mode, write one JSONL line, flush, `os.fsync`,
    close — never batched in memory, which is the real mechanism
    behind A11.4's "every completed case commits immediately.\""""

    def __init__(self, run_dir: "str | Path", environment: "dict | None" = None):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.blobs = BlobStore(self.run_dir / "blobs")
        self._cases_path = self.run_dir / "cases.jsonl"
        if environment is not None:
            self._write_manifest(environment)

    def _write_manifest(self, environment: dict) -> None:
        manifest_path = self.run_dir / "manifest.json"
        if manifest_path.exists():
            # A run's own recorded identity is fixed at creation, never
            # silently overwritten by a later resume call passing a
            # (possibly stale) environment snapshot again.
            return
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(environment, fh, indent=2, sort_keys=True, default=str)

    def commit_case(self, record: CaseRecord) -> None:
        line = json.dumps(record.to_dict(), sort_keys=True, default=str)
        with self._cases_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())


class RunRecordReader:
    """Reads back a real run directory — the real consumer behind
    A11.4 (resume) and A7.1 ("aggregates can be recomputed without
    re-running")."""

    def __init__(self, run_dir: "str | Path"):
        self.run_dir = Path(run_dir)
        self.blobs = BlobStore(self.run_dir / "blobs")

    def manifest(self) -> dict:
        path = self.run_dir / "manifest.json"
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def iter_case_records(self):
        path = self.run_dir / "cases.jsonl"
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield CaseRecord.from_dict(json.loads(line))

    def completed_case_ids(self) -> set:
        """A11.4's real resume signal — every `case_id` with at least
        one committed record on disk, read fresh each call (never
        cached), so a caller always sees the true state of the run
        directory rather than a snapshot that could go stale mid-run."""
        return {r.case_id for r in self.iter_case_records()}


def prune_run(run_dir: "str | Path") -> None:
    """A8.4's ONE deletion path — explicit only, never invoked by
    `RunRecordWriter` or anywhere in a normal run/resume call. Pruning
    a run directory that doesn't exist is a safe no-op."""
    path = Path(run_dir)
    if path.exists():
        shutil.rmtree(path)
