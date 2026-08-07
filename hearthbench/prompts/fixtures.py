"""HearthBench A3.1 — frozen prompt fixtures exported from the real
simulation.

**[DECIDED: frozen export, as specced.]** A fixture pack is a
versioned, checked-in snapshot: `hearthbench export` reads a real
`hearthmind.llm.recorder` archive (via `hearthmind.llm.review_pack.
iter_examples` — real reuse, that module already does exactly this
walk, don't rebuild it) and writes one JSON file per task under
`fixtures/v<version>/<task>.json` plus a `manifest.json` naming every
task's example count and the pack's own content hash — a benchmark
run replays these frozen examples, never the live archive, so a run
from six months ago stays exactly reproducible even after the archive
that originally produced it has grown, rotated, or been pruned.

Import isolation (A1.2): `hearthmind.llm.review_pack`/`.recorder` are
under `hearthmind.llm`, not `hearthmind.simulation`/`.agents`/`.world`
— reusing them stays inside the firewall.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hearthmind.llm.review_pack import iter_examples

FIXTURE_PACK_MANIFEST_FILENAME = "manifest.json"


def _content_hash(task: str, structured_input: dict, prompt: str, system_prompt: str | None) -> str:
    """A stable, order-independent identity for one fixture's real
    content — `sort_keys=True` so two logically-identical examples
    always hash the same regardless of dict insertion order (the
    archive's own JSON round-trip can reorder keys)."""
    payload = json.dumps(
        {"task": task, "structured_input": structured_input, "prompt": prompt, "system_prompt": system_prompt},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class FixtureExample:
    """One frozen fixture — the real `layer1_structured_input` +
    rendered prompt a recorder archive line already carries (see A0.3),
    trimmed to only what a benchmark case needs (no latency/queue/
    recorder-operational metadata — that's this project's own live-
    deployment diagnostics, not a reproducible test input)."""

    fixture_id: str
    task: str
    structured_input: dict
    prompt: str
    system_prompt: str | None
    content_hash: str
    source_example_id: str | None = None
    """The archive's own `example_id` this fixture was frozen from, or
    `None` for a synthetic fixture (A3.4) never recorded from a real
    run — the one field that distinguishes organic from synthesized
    fixtures in a pack."""
    synthetic: bool = False
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FixtureExample":
        return cls(
            fixture_id=data["fixture_id"], task=data["task"],
            structured_input=data.get("structured_input") or {}, prompt=data.get("prompt") or "",
            system_prompt=data.get("system_prompt"), content_hash=data["content_hash"],
            source_example_id=data.get("source_example_id"), synthetic=bool(data.get("synthetic", False)),
            tags=list(data.get("tags") or []),
        )


def fixture_from_archive_example(example: dict, fixture_id: str) -> FixtureExample | None:
    """Builds one `FixtureExample` from a real archive line (the exact
    dict shape `review_pack.iter_examples` yields). Returns `None` for
    a line with no usable content — an archive line whose `layer2_
    prompt` is empty (a task the recorder never populated `structured_
    input`/prompt for — same "some tasks lack layer 1" limitation A0.3
    already documents) isn't a real fixture."""
    prompt = example.get("layer2_prompt")
    if not prompt:
        return None
    task = example.get("task") or "unknown"
    structured_input = example.get("layer1_structured_input") or {}
    system_prompt = example.get("layer2_system_prompt")
    return FixtureExample(
        fixture_id=fixture_id, task=task, structured_input=structured_input, prompt=prompt,
        system_prompt=system_prompt, content_hash=_content_hash(task, structured_input, prompt, system_prompt),
        source_example_id=example.get("example_id"),
    )


def select_fixtures_per_task(
    examples: list[FixtureExample], max_per_task: int, seed: int = 0,
) -> dict[str, list[FixtureExample]]:
    """Groups by `task`, dedupes by `content_hash` (a re-recorded
    near-identical situation should count once, not crowd out real
    variety), then takes a deterministic seeded sample up to `max_per_
    task` per task — deterministic so re-running the export against
    the SAME archive reproduces the SAME pack byte-for-byte (the
    spec's own "frozen, checked-in, hash-identified" requirement would
    be meaningless if re-exporting silently picked different
    examples)."""
    by_task: dict[str, dict[str, FixtureExample]] = {}
    for ex in examples:
        by_task.setdefault(ex.task, {})[ex.content_hash] = ex  # last-write-wins de-dup, order doesn't matter here

    selected: dict[str, list[FixtureExample]] = {}
    for task, by_hash in by_task.items():
        unique = sorted(by_hash.values(), key=lambda e: e.content_hash)  # deterministic pre-shuffle order
        rng = random.Random(f"{seed}:{task}")
        rng.shuffle(unique)
        selected[task] = unique[:max_per_task]
    return selected


def export_fixture_pack(
    archive_dir: str | Path, output_dir: str | Path, version: str,
    max_per_task: int = 20, seed: int = 0,
) -> dict:
    """The real `hearthbench export` mechanism. Reads every real
    archive line via `iter_examples`, converts each into a candidate
    `FixtureExample`, selects a deterministic per-task subset, and
    writes `<output_dir>/<version>/<task>.json` + a manifest. Returns
    the manifest dict (also written to disk) so a caller (the CLI, or
    a verify script) doesn't have to re-read it."""
    candidates: list[FixtureExample] = []
    counter = 0
    for raw in iter_examples(archive_dir):
        fixture = fixture_from_archive_example(raw, fixture_id=f"archive-{counter:06d}")
        if fixture is not None:
            candidates.append(fixture)
            counter += 1

    selected = select_fixtures_per_task(candidates, max_per_task=max_per_task, seed=seed)

    pack_dir = Path(output_dir) / version
    pack_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"version": version, "seed": seed, "max_per_task": max_per_task, "tasks": {}}
    for task, fixtures in sorted(selected.items()):
        task_path = pack_dir / f"{task}.json"
        with open(task_path, "w", encoding="utf-8") as fh:
            json.dump([f.to_dict() for f in fixtures], fh, indent=2, sort_keys=True)
        manifest["tasks"][task] = len(fixtures)
    manifest["total"] = sum(manifest["tasks"].values())
    manifest["pack_hash"] = hashlib.sha256(
        json.dumps(manifest["tasks"], sort_keys=True).encode("utf-8")
        + b"".join(sorted(f.content_hash.encode("utf-8") for fixtures in selected.values() for f in fixtures))
    ).hexdigest()

    with open(pack_dir / FIXTURE_PACK_MANIFEST_FILENAME, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return manifest


def load_fixture_pack(output_dir: str | Path, version: str, task: str | None = None) -> list[FixtureExample]:
    """Reads a previously-exported pack back — the read half of A3.1,
    what A3.2's `test_case_from_fixture` and a future A11 runner both
    need. `task=None` loads every task's fixtures; a specific task
    loads only that one file (never scans the whole pack directory for
    a single-task read)."""
    pack_dir = Path(output_dir) / version
    if not pack_dir.exists():
        return []
    task_files = [pack_dir / f"{task}.json"] if task else sorted(pack_dir.glob("*.json"))
    fixtures: list[FixtureExample] = []
    for path in task_files:
        if path.name == FIXTURE_PACK_MANIFEST_FILENAME or not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as fh:
            raw_list = json.load(fh)
        fixtures.extend(FixtureExample.from_dict(d) for d in raw_list)
    return fixtures
