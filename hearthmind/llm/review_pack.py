"""Review-pack export + archive validation for the permanent LLM
training recorder (llm/recorder.py, §8 — see its module docstring).

Kept separate from `recorder.py` itself: this module is a pure read-only
consumer of the on-disk JSONL archive (never touches the live
`TrainingRecorder`/queue), used both by `interface/app.py`'s
`/recorder/export-review-pack` endpoint and `scripts/recorder_tools.py`
(the spec's own "validation utility"). Nothing here runs on the
simulation's hot path.
"""
from __future__ import annotations

import json
import random
import time
import zipfile
from pathlib import Path
from typing import Iterator

from hearthmind.llm import review_diagnostics

# Fields carried into a review-pack example — spec: "structured input,
# prompt, raw completion, parsed output, stable example ID, essential
# metadata... exclude unrelated diagnostics." Deliberately narrower than
# the full archive record (drops queue-wait/latency-adjacent fields that
# belong to this project's own operational diagnostics, not a training
# example). `.get(...)` on every field below (see `_to_review_example`)
# means an OLDER archive line that predates the v1.1.0 recorder-
# enhancement fields simply yields `None` for those keys — no error, no
# special-casing needed to stay backward compatible.
REVIEW_PACK_FIELDS = (
    "example_id", "task", "timestamp", "simulation_tick", "settlement", "npc_ids",
    "model_name", "fallback_used", "parse_repaired",
    "layer1_structured_input", "layer2_prompt", "layer2_system_prompt",
    "layer3_raw_completion", "layer4_parsed_output",
    # v1.1.0 "Recorder Enhancement Pass" additions — all optional/`None`
    # on older archive lines, never required.
    "generation_config", "prompt_metadata", "prompt_hash", "structured_input_hash",
    "session", "outcome", "dataset",
)


def iter_examples(
    archive_dir: str | Path, task: str | None = None,
    date_from: str | None = None, date_to: str | None = None,
) -> Iterator[dict]:
    """Yields every valid JSON example under `archive_dir`, optionally
    scoped to one task subdirectory and/or an inclusive `YYYY-MM-DD`
    date range (matched against the archive filename's own date stamp,
    not a per-line timestamp parse — cheap and exact, since
    `TrainingRecorder._archive_path_for` names files by UTC date).
    Corrupt lines are silently skipped (`validate_archive` below is
    where corruption gets reported, not here)."""
    root = Path(archive_dir)
    if not root.exists():
        return
    task_dirs = [root / task] if task else sorted(p for p in root.iterdir() if p.is_dir())
    for task_dir in task_dirs:
        if not task_dir.is_dir():
            continue
        for jsonl_path in sorted(task_dir.glob("*.jsonl")):
            file_date = jsonl_path.stem.split("_")[0]  # "2026-07-19" or "2026-07-19_2" -> "2026-07-19"
            if date_from and file_date < date_from:
                continue
            if date_to and file_date > date_to:
                continue
            with open(jsonl_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


def _to_review_example(example: dict) -> dict:
    return {k: example.get(k) for k in REVIEW_PACK_FIELDS}


def _dataset_manifest_summary(raw_examples: list[dict]) -> dict:
    """§8 recorder-enhancement item 8 "Review Pack Metadata": lets a
    reviewing LLM understand the pack's shape before reading every
    example. Computed from the already-collected raw example dicts —
    no extra archive scan. Every field here is derived from what's
    already present on each example (`.get(...)`-safe), so a pack built
    from a mix of pre- and post-v1.1.0 archive lines degrades
    gracefully (missing `generation_config`/`session` just don't
    contribute to `models`/`recording_sessions`)."""
    task_distribution: dict[str, int] = {}
    models: set[str] = set()
    prompt_versions: set[str] = set()
    sessions: dict[str, dict] = {}
    timestamps: list[float] = []
    for ex in raw_examples:
        task = ex.get("task")
        if task:
            task_distribution[task] = task_distribution.get(task, 0) + 1
        model = ex.get("model_name")
        if model:
            models.add(model)
        version = (ex.get("prompt_metadata") or {}).get("system_prompt_version")
        if version:
            prompt_versions.add(version)
        session = ex.get("session")
        session_id = ex.get("session_id")
        if session_id and session_id not in sessions:
            sessions[session_id] = {
                "session_id": session_id,
                "name": (session or {}).get("name") or ex.get("session_name"),
                "tags": (session or {}).get("tags", []),
            }
        ts = ex.get("timestamp")
        if isinstance(ts, (int, float)):
            timestamps.append(ts)
    return {
        "task_distribution": task_distribution,
        "model": sorted(models),
        "prompt_versions": sorted(prompt_versions),
        "recording_session": list(sessions.values()),
        "date_range": {"from": min(timestamps), "to": max(timestamps)} if timestamps else None,
    }


def _write_zip(
    examples: list[dict], manifest: dict, out_dir: Path, markdown: bool,
    diagnostics: dict | None = None,
) -> Path:
    """Explicit live request: "Every exported review pack should include
    an automatic diagnostics report (diagnostics.json + diagnostics.md)
    ... to objectively identify simulator regressions and improvements
    before manual review." `diagnostics` is always written when supplied
    (both `export_review_pack`/`export_random_subset` below always
    supply one — `diagnostics=None` only exists for callers that
    deliberately want a bare pack, none currently do)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    zip_path = out_dir / f"review_pack_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("review_pack.json", json.dumps(examples, ensure_ascii=False, indent=2))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if markdown:
            zf.writestr("review_pack.md", _to_markdown(examples))
        if diagnostics is not None:
            zf.writestr("diagnostics.json", json.dumps(diagnostics, ensure_ascii=False, indent=2))
            zf.writestr("diagnostics.md", review_diagnostics.diagnostics_to_markdown(diagnostics))
    return zip_path


def _to_markdown(examples: list[dict]) -> str:
    lines = ["# Hearthmind LLM Review Pack", ""]
    for ex in examples:
        lines.append(f"## {ex.get('example_id')} — {ex.get('task')}")
        lines.append(f"- tick: {ex.get('simulation_tick')}  settlement: {ex.get('settlement')}")
        lines.append(f"- model: {ex.get('model_name')}  fallback_used: {ex.get('fallback_used')}")
        session = ex.get("session") or {}
        if session.get("tags"):
            lines.append(f"- session: {session.get('name')}  tags: {', '.join(session['tags'])}")
        if ex.get("outcome"):
            lines.append(f"- outcome: {ex['outcome']}")
        lines.append("")
        lines.append("**Structured input**")
        lines.append("```json")
        lines.append(json.dumps(ex.get("layer1_structured_input", {}), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("**Prompt**")
        lines.append("```")
        lines.append(str(ex.get("layer2_prompt", "")))
        lines.append("```")
        lines.append("**Raw completion**")
        lines.append("```")
        lines.append(str(ex.get("layer3_raw_completion") or "(fallback — no real completion)"))
        lines.append("```")
        lines.append("**Parsed output**")
        lines.append("```json")
        lines.append(json.dumps(ex.get("layer4_parsed_output", {}), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def export_review_pack(
    archive_dir: str | Path, task: str | None = None,
    date_from: str | None = None, date_to: str | None = None,
    limit: int = 500, markdown: bool = False, out_dir: str | Path | None = None,
) -> Path:
    """Builds `review_pack.json` + `manifest.json` (and optionally
    `review_pack.md`) into a ZIP under `<archive_dir>/exports/` — each
    example is self-contained per the spec ("Each example must be
    self-contained")."""
    root = Path(archive_dir)
    raw_examples = []
    for example in iter_examples(root, task=task, date_from=date_from, date_to=date_to):
        raw_examples.append(example)
        if len(raw_examples) >= limit:
            break
    examples = [_to_review_example(e) for e in raw_examples]
    manifest = {
        "generated_at": time.time(),
        "filters": {"task": task, "date_from": date_from, "date_to": date_to, "limit": limit},
        "example_count": len(examples),
        **_dataset_manifest_summary(raw_examples),
    }
    diagnostics = review_diagnostics.compute_diagnostics(raw_examples)
    return _write_zip(
        examples, manifest, Path(out_dir) if out_dir else root / "exports", markdown,
        diagnostics=diagnostics,
    )


def export_random_subset(
    archive_dir: str | Path, count: int = 50, task: str | None = None, seed: int | None = None,
    out_dir: str | Path | None = None, markdown: bool = False,
) -> Path:
    root = Path(archive_dir)
    all_raw = list(iter_examples(root, task=task))
    rng = random.Random(seed)
    raw_sample = all_raw if len(all_raw) <= count else rng.sample(all_raw, count)
    sample = [_to_review_example(e) for e in raw_sample]
    manifest = {
        "generated_at": time.time(), "kind": "random_subset",
        "filters": {"task": task, "count": count, "seed": seed},
        "example_count": len(sample), "population_count": len(all_raw),
        **_dataset_manifest_summary(raw_sample),
    }
    diagnostics = review_diagnostics.compute_diagnostics(raw_sample)
    return _write_zip(
        sample, manifest, Path(out_dir) if out_dir else root / "exports", markdown,
        diagnostics=diagnostics,
    )


def archive_stats(archive_dir: str | Path) -> dict:
    """Spec: "count records, ... report statistics." Per-task counts,
    fallback rate, and total on-disk size — cheap enough to run over a
    real archive (single sequential pass, no JSON re-serialization)."""
    root = Path(archive_dir)
    per_task: dict[str, dict] = {}
    total = 0
    total_bytes = 0
    if root.exists():
        for task_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if task_dir.name == "exports":
                continue
            stats = per_task.setdefault(task_dir.name, {"count": 0, "fallback_count": 0, "bytes": 0})
            for jsonl_path in task_dir.glob("*.jsonl"):
                stats["bytes"] += jsonl_path.stat().st_size
                total_bytes += jsonl_path.stat().st_size
                with open(jsonl_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        stats["count"] += 1
                        total += 1
                        try:
                            if json.loads(line).get("fallback_used"):
                                stats["fallback_count"] += 1
                        except json.JSONDecodeError:
                            continue
    return {"total_examples": total, "total_bytes": total_bytes, "per_task": per_task}


def validate_archive(archive_dir: str | Path) -> dict:
    """Spec: "validate JSON, validate schema, ... detect corruption."
    Walks every `.jsonl` file line by line; a line that fails to parse
    as JSON, or parses but is missing a required top-level field, is
    reported (file + line number), never silently dropped the way
    `iter_examples` does for normal reads."""
    required_fields = {
        "example_id", "schema_version", "task", "layer2_prompt", "layer4_parsed_output",
    }
    root = Path(archive_dir)
    errors: list[dict] = []
    valid_count = 0
    if root.exists():
        for task_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if task_dir.name == "exports":
                continue
            for jsonl_path in task_dir.glob("*.jsonl"):
                with open(jsonl_path, "r", encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                        except json.JSONDecodeError as exc:
                            errors.append({"file": str(jsonl_path), "line": lineno, "error": f"invalid JSON: {exc}"})
                            continue
                        missing = required_fields - parsed.keys()
                        if missing:
                            errors.append({
                                "file": str(jsonl_path), "line": lineno,
                                "error": f"missing required fields: {sorted(missing)}",
                            })
                            continue
                        valid_count += 1
    return {"valid_count": valid_count, "error_count": len(errors), "errors": errors[:200]}
