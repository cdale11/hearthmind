"""Cross-run training data pooling -- added per explicit user
instruction: "the AI/ML models should learn from all previous runs if
possible."

This complements L5's continual-learning loop (`hearthmind/ml/
lifelong.py`), which keeps ONE world's models learning across ITS OWN
lifetime, with the orthogonal axis: pooling training signal across
MULTIPLE past runs/worlds, when more than one archived run exists on
disk, so a model that isn't per-world "Mind" state at all -- like
B8's workload forecaster, which describes THIS MACHINE's runtime
behaviour, not any one world's cognition -- doesn't have to start
learning from nothing every session. (Per-world Mind models, per
`docs/ML-ARCHITECTURE-2026-08-01.md`'s guardrail #3, stay per-world by
design -- pooling across runs is for the runtime-scoped models this
principle doesn't apply to, or for a deliberate warm-start seed before
per-world specialization diverges.)

Directory layout assumed: `runs_root/<run_id>/...` -- each `<run_id>`
subdirectory is one past run's own archive (matching `llm/recorder.
py`'s own `<archive_dir>/<task>/<date>.jsonl` shape one level down,
or any other per-run export). This module never assumes a particular
schema inside a run directory -- callers supply an `example_loader`
function per run and this stays agnostic to what's actually being
learned.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field


@dataclass
class CrossRunDatasetStats:
    runs_found: int
    runs_used: int
    runs_failed: int
    examples_total: int
    examples_per_run: dict = field(default_factory=dict)
    failed_run_ids: list = field(default_factory=list)


def discover_runs(runs_root: str) -> list:
    """Every immediate subdirectory of `runs_root`, sorted for a
    deterministic pooling order. Returns an empty list (never raises)
    if `runs_root` doesn't exist -- the common case for a brand-new
    installation with no prior runs archived yet."""
    if not os.path.isdir(runs_root):
        return []
    return sorted(
        name for name in os.listdir(runs_root)
        if os.path.isdir(os.path.join(runs_root, name))
    )


def pool_examples_across_runs(
    runs_root: str,
    example_loader,
    max_per_run: int | None = None,
    max_total: int | None = None,
    seed: int = 0,
):
    """Loads examples from every run under `runs_root` via `example_
    loader(run_dir) -> list[example]`, pools them, and returns
    `(examples, stats)`.

    A run whose loader raises is skipped, not fatal -- one corrupted
    or partially-written past archive must never block training on
    every other one. Each run is capped at `max_per_run` (a uniform
    random sample of ITS OWN examples, so no single unusually large
    run can dominate the pool and effectively erase every other run's
    voice); the combined pool is then capped at `max_total` the same
    way if it's still too large."""
    rng = random.Random(seed)
    run_ids = discover_runs(runs_root)
    pooled = []
    stats = CrossRunDatasetStats(runs_found=len(run_ids), runs_used=0, runs_failed=0, examples_total=0)

    for run_id in run_ids:
        run_dir = os.path.join(runs_root, run_id)
        try:
            examples = list(example_loader(run_dir))
        except Exception:
            stats.runs_failed += 1
            stats.failed_run_ids.append(run_id)
            continue
        if not examples:
            continue
        if max_per_run is not None and len(examples) > max_per_run:
            examples = rng.sample(examples, max_per_run)
        stats.examples_per_run[run_id] = len(examples)
        stats.runs_used += 1
        pooled.extend(examples)

    if max_total is not None and len(pooled) > max_total:
        pooled = rng.sample(pooled, max_total)

    stats.examples_total = len(pooled)
    return pooled, stats
