"""FT.5 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap): "Freeze an
eval harness before the first training run." The measuring stick
already exists (`llm/review_diagnostics.py`'s metrics) — this module is
the "formalize it" half FT.5 actually asks for: a hash-based (never
random) held-out split so a duplicate prompt can't leak train into
eval, a stratified golden-prompt sampler that guarantees every task is
represented, and a regression-threshold checker any candidate adapter
run can be checked against automatically.

Deliberately does NOT itself run a "world-level A/B... same seed, base
vs. tuned adapter, over 30k ticks" — FT.5's second half. That requires
an actual trained adapter to compare against a base run, which is
outside this module's (and this environment's) scope; the mechanism
this module DOES provide (frozen split + thresholds) is the
prerequisite that A/B needs anyway (you can't compare "regression or
not" without a frozen baseline to regress against).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hearthmind.llm.review_diagnostics import compute_diagnostics

HOLDOUT_FRACTION = 0.1
"""FT.5: "a frozen held-out prompt set (deduped by structured_input_
hash against train — the 0.14 duplicate rate means dedupe matters;
split by hash, never randomly)." 10% is a conventional default large
enough to be statistically meaningful on a real multi-thousand-example
archive without starving the training set."""

GOLDEN_SET_MIN_SIZE = 50
"""FT.5: "~50 hand-picked golden prompts covering every task including
the weird cases." This module can't automate the "hand-picked"
judgment call, but it CAN guarantee structural coverage (every task
present, not just whichever tasks happen to dominate a random draw) —
see `build_golden_set`."""


def _hash_bucket(structured_input_hash: str) -> int:
    """Deterministic 0-99 bucket from a hex hash string — stable across
    runs (same hash always lands in the same bucket), so re-running the
    split later never reshuffles which examples are held out, and a
    duplicate `structured_input_hash` always lands in the same bucket
    as every other copy of itself (the actual point: split by hash, not
    randomly, so a near-duplicate prompt can't straddle train/holdout)."""
    digest = hashlib.sha256(structured_input_hash.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def split_holdout(
    examples: list[dict], holdout_fraction: float = HOLDOUT_FRACTION,
) -> tuple[list[dict], list[dict]]:
    """Splits archive examples (the `to_dict()` shape `review_pack.
    iter_examples` yields — needs a real `structured_input_hash` field,
    v1.1.0+ recorder output) into `(train, holdout)` by hashing each
    example's own `structured_input_hash` into a stable 0-99 bucket.
    Examples missing that field (pre-v1.1.0 archive lines) are placed
    into `train` — a hash-less example can't be deduped against
    anything, so it's safer to leave it out of the frozen eval set
    entirely than to risk it silently overlapping something else."""
    threshold = int(holdout_fraction * 100)
    train, holdout = [], []
    for ex in examples:
        h = ex.get("structured_input_hash")
        if not h or _hash_bucket(h) >= threshold:
            train.append(ex)
        else:
            holdout.append(ex)
    return train, holdout


def build_golden_set(examples: list[dict], min_size: int = GOLDEN_SET_MIN_SIZE) -> list[dict]:
    """Stratified sample guaranteeing every task present in `examples`
    contributes at least one example (a plain random draw of ~50 from
    an archive that's 60%+ dialogue would silently starve every rare
    task FT.5 specifically wants covered) — remaining slots filled
    round-robin across tasks until `min_size` is reached or the pool is
    exhausted. Within each task, prefers examples flagged `outcome.
    status == "executed"` (a genuine, non-fallback LLM call) when that
    field is present, since a golden prompt whose own reference
    behavior was a deterministic fallback isn't testing the model at
    all. Deterministic (input order preserved, no RNG) — this is meant
    to be reviewed and hand-edited by a human afterward (FT.5's own
    "hand-picked"), not regenerated fresh each time."""
    by_task: dict[str, list[dict]] = {}
    for ex in examples:
        task = ex.get("task") or "unknown"
        by_task.setdefault(task, []).append(ex)
    for task_examples in by_task.values():
        task_examples.sort(key=lambda e: (e.get("outcome") or {}).get("status") != "executed")

    golden: list[dict] = []
    seen_ids: set[str] = set()
    round_robin = list(by_task.values())
    idx = 0
    while len(golden) < min_size and any(round_robin):
        pool = round_robin[idx % len(round_robin)]
        idx += 1
        if pool:
            ex = pool.pop(0)
            example_id = ex.get("example_id")
            if example_id not in seen_ids:
                golden.append(ex)
                if example_id is not None:
                    seen_ids.add(example_id)
        if all(not p for p in round_robin):
            break
    return golden


DEFAULT_THRESHOLDS = {
    "fallback_rate.overall": {"max": 0.10},
    "parse_repaired_rate.overall": {"max": 0.02},
    "duplicate_rates.structured_input_duplicate_rate": {"max": 0.20},
    "topic_diversity.dialogue.dominant_topic_share": {"max": 0.40},
    "opportunity_diversity.dialogue.category_share.settlement_topic": {"max": 0.50},
}
"""One flat `"dotted.path.to.metric": {"min": x} | {"max": x}` per
regression gate — deliberately a plain dict (not a class/schema) so a
project maintainer can copy, tune, and version this alongside a real
training run without touching this module's code, per FT.5's own
"target thresholds per metric... tunable and versioned." Sized
loosely around what a healthy pre-fine-tuning archive already measures
(fallback near 0%, parse-repair near 0% since FT.0's schema-constrained
decoding, `dialogue_topic_share` well under P0.2's monoculture-era
55%+ readings) — these are starting points, not validated targets;
tighten them once a real baseline pack's own numbers are in hand."""


def _get_path(d: dict, dotted_path: str):
    node = d
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def check_regressions(
    candidate_diagnostics: dict, thresholds: dict | None = None,
) -> list[str]:
    """Compares one `review_diagnostics.compute_diagnostics(...)` output
    against `thresholds` (defaults to `DEFAULT_THRESHOLDS`); returns a
    list of human-readable violation strings, empty if every gated
    metric is within bounds. A metric missing from the candidate
    diagnostics (e.g. no dialogue examples in this particular run) is
    silently skipped, not counted as a violation — an empty category
    isn't a regression, it's a coverage gap the golden set should
    catch separately."""
    thresholds = thresholds if thresholds is not None else DEFAULT_THRESHOLDS
    violations = []
    for path, bounds in thresholds.items():
        value = _get_path(candidate_diagnostics, path)
        if value is None:
            continue
        if "max" in bounds and value > bounds["max"]:
            violations.append(f"{path} = {value:.4f} exceeds max {bounds['max']}")
        if "min" in bounds and value < bounds["min"]:
            violations.append(f"{path} = {value:.4f} below min {bounds['min']}")
    return violations


def freeze_eval_set(
    archive_examples: list[dict], out_dir: str | Path,
    holdout_fraction: float = HOLDOUT_FRACTION, golden_min_size: int = GOLDEN_SET_MIN_SIZE,
) -> dict:
    """One-shot: splits `archive_examples` into train/holdout, builds
    the golden set from the holdout portion (never train — a golden
    prompt is meaningless as an eval target if it was also available
    for training), computes baseline diagnostics over the holdout, and
    writes all three (`holdout.jsonl`, `golden_set.jsonl`,
    `baseline_diagnostics.json`) to `out_dir`. Returns the same three
    pieces in memory too, for a caller (e.g. `scripts/recorder_tools.py
    freeze-eval-set`) that wants to report a summary without
    re-reading its own output back off disk."""
    train, holdout = split_holdout(archive_examples, holdout_fraction)
    golden = build_golden_set(holdout, golden_min_size)
    baseline = compute_diagnostics(holdout)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "holdout.jsonl", "w", encoding="utf-8") as fh:
        for ex in holdout:
            fh.write(json.dumps(ex, ensure_ascii=False, default=str) + "\n")
    with open(out_dir / "golden_set.jsonl", "w", encoding="utf-8") as fh:
        for ex in golden:
            fh.write(json.dumps(ex, ensure_ascii=False, default=str) + "\n")
    with open(out_dir / "baseline_diagnostics.json", "w", encoding="utf-8") as fh:
        json.dump(baseline, fh, ensure_ascii=False, indent=2, default=str)

    return {
        "train_count": len(train), "holdout_count": len(holdout), "golden_count": len(golden),
        "baseline_diagnostics": baseline,
    }


MIN_SFT_EXAMPLES_PER_TASK = 200
"""§8 LoRA fine-tuning, kept data-collection-only per explicit user
decision ("keep data-collection-only, extend the tooling instead" — no
new ML dependency like torch/peft/transformers, this environment can't
run a real training job anyway). A conventional order-of-magnitude
floor for a per-task LoRA slice (widely-cited community guidance for a
narrow single-task adapter, not a number measured against a real
Hearthmind training run in this environment — flagged honestly, not
presented as tuned). Below this, a task's SFT-eligible pool is
probably too thin to fine-tune on usefully; above it, readiness is
gated by quality (schema/leak rates), not volume."""

MAX_ACCEPTABLE_LEAK_RATE = 0.05
MAX_ACCEPTABLE_FALLBACK_RATE = 0.5
"""§8: a task whose recorded examples are mostly fallback output (never
a real LLM answer) has nothing worth imitating; a task with meaningful
scaffolding-leak contamination (`quality_labels.check_leaks`) needs a
prompt fix before its archive is trustworthy training material, not a
bigger archive."""


def training_readiness_report(archive_dir: "str | Path") -> dict:
    """§8's real "extend the tooling instead" deliverable: a single
    read-only report answering "is there enough GOOD data to attempt a
    first LoRA pass on task X yet?" — combining `review_pack.label_
    archive`'s per-task quality rates (FT.2) with a volume floor
    (`MIN_SFT_EXAMPLES_PER_TASK`) and the two quality floors above.
    Deliberately does NOT run or configure any actual training job —
    per the explicit "no new ML dependency" scope, this module stays
    stdlib-only; a `ready` task here is a real, actionable target for
    an external training pipeline (see docs/TRAINING_RECORDER.md),
    never training run itself. `archive_dir` is passed straight to
    `review_pack.label_archive`, so no separate example list needs
    loading here."""
    from hearthmind.llm.review_pack import label_archive  # local import: avoids a review_pack<->eval_harness cycle

    labeled = label_archive(archive_dir)
    per_task_verdicts: dict[str, dict] = {}
    ready_tasks: list[str] = []
    not_ready_tasks: list[str] = []
    for task, stats in labeled["per_task"].items():
        count = stats["count"]
        fallback_rate = round(stats["fallback_used"] / count, 3) if count else 0.0
        reasons = []
        if count < MIN_SFT_EXAMPLES_PER_TASK:
            reasons.append(f"only {count} examples, below the {MIN_SFT_EXAMPLES_PER_TASK}-example floor")
        if stats["leak_rate"] > MAX_ACCEPTABLE_LEAK_RATE:
            reasons.append(f"leak rate {stats['leak_rate']:.1%} exceeds {MAX_ACCEPTABLE_LEAK_RATE:.0%}")
        if fallback_rate > MAX_ACCEPTABLE_FALLBACK_RATE:
            reasons.append(f"fallback rate {fallback_rate:.1%} exceeds {MAX_ACCEPTABLE_FALLBACK_RATE:.0%}")
        ready = not reasons
        per_task_verdicts[task] = {
            "count": count,
            "sft_eligible_rate": stats["sft_eligible_rate"],
            "leak_rate": stats["leak_rate"],
            "fallback_rate": fallback_rate,
            "ready": ready,
            "reasons": reasons,
        }
        (ready_tasks if ready else not_ready_tasks).append(task)
    return {
        "total_examples": labeled["total_examples"],
        "tasks_ready": sorted(ready_tasks),
        "tasks_not_ready": sorted(not_ready_tasks),
        "per_task": per_task_verdicts,
        "verdict": (
            f"{len(ready_tasks)}/{len(labeled['per_task'])} task(s) have enough good data for a first "
            "LoRA slice; no training run was attempted — this environment has no training infrastructure "
            "and none was added (explicit scope)."
            if labeled["per_task"] else
            "no recorded examples found — nothing to assess yet."
        ),
    }
