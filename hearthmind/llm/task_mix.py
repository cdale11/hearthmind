"""FT.4 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap): "Balance the
task mix; augment the rare tasks." A naive training mix over a real
archive (dialogue/rumor_interpret dominate by 1-2 orders of magnitude
over the hardest structured tasks — consciousness/town_brain/beliefs
sit at single digits) fine-tunes a model that's good at chit-chat and
mediocre at everything that actually runs the world. This module is
the "per-task sampling weights" half of FT.4 — a pure function over
task counts, no live LLM/archive I/O, so it composes cleanly with
`review_pack.label_archive()`'s per-task counts and `llm/prompt_
synthesis.py`'s augmentation output. See `prompt_synthesis.py` for the
"synthesize prompts for rare tasks" half.
"""
from __future__ import annotations

DEFAULT_MAX_SHARE = 0.35
"""Cap on any single task's share of a sampled training batch — FT.4
names "~30-40%" for dialogue specifically; 0.35 sits in the middle of
that range and applies uniformly (a cap only matters for whichever
task actually dominates the raw counts, dialogue in every archive this
project has measured so far)."""

DEFAULT_MIN_WEIGHT_FLOOR = 0.02
"""A rare task (1-6 raw examples) would round to ~0 sampling weight
under plain inverse-frequency weighting, effectively dropping it from
training entirely — the opposite of what "upweight rare tasks" asks
for. This floor guarantees every task with at least one real example
gets a non-trivial floor share before the cap/renormalization pass."""


def compute_sampling_weights(
    task_counts: dict[str, int],
    max_share: float = DEFAULT_MAX_SHARE,
    min_weight_floor: float = DEFAULT_MIN_WEIGHT_FLOOR,
) -> dict[str, float]:
    """Turns raw per-task example counts (e.g. `review_pack.label_
    archive()['per_task'][task]['count']`, or any task->count dict)
    into normalized sampling weights (sum to 1.0) suitable for a
    weighted-without-replacement draw when assembling a training batch.

    Three passes, in order:
    1. Inverse-frequency base weight (`1 / count`) so rare tasks start
       ahead of common ones on a per-weight basis, then normalize.
    2. Apply `min_weight_floor` to any task that rounds below it.
    3. Cap any task's share at `max_share`, redistributing the excess
       proportionally across every other task (iterative — capping one
       task can push another over the cap too, most visibly on an
       archive with only 2-3 tasks total).

    Tasks with `count <= 0` are dropped entirely (nothing to sample).
    Returns `{}` for empty input — the caller decides what an empty
    mix means (skip training, fall back to raw counts, etc.)."""
    counts = {task: c for task, c in task_counts.items() if c > 0}
    if not counts:
        return {}

    inverse = {task: 1.0 / c for task, c in counts.items()}
    total_inverse = sum(inverse.values())
    weights = {task: w / total_inverse for task, w in inverse.items()}

    for task in weights:
        if weights[task] < min_weight_floor:
            weights[task] = min_weight_floor
    total = sum(weights.values())
    weights = {task: w / total for task, w in weights.items()}

    # Iteratively clamp shares above max_share and redistribute the
    # excess across the remaining (not-yet-clamped) tasks — bounded to
    # len(weights) passes so a pathological input (every task capped)
    # can never loop forever; each pass clamps at least one more task
    # or the loop is already at a fixed point and exits early.
    clamped: set[str] = set()
    for _ in range(len(weights)):
        over = {t: w for t, w in weights.items() if t not in clamped and w > max_share}
        if not over:
            break
        excess = sum(w - max_share for w in over.values())
        for t in over:
            weights[t] = max_share
        clamped |= set(over)
        free = {t: w for t, w in weights.items() if t not in clamped}
        free_total = sum(free.values())
        if free_total <= 0:
            break
        for t in free:
            weights[t] += excess * (free[t] / free_total)

    total = sum(weights.values())
    return {task: round(w / total, 6) for task, w in weights.items()}


def weighted_task_targets(task_counts: dict[str, int], batch_size: int, **kwargs) -> dict[str, int]:
    """Convenience wrapper: `compute_sampling_weights` scaled to a
    concrete `batch_size`, rounded to whole examples-per-task (largest-
    remainder rounding so the totals sum exactly to `batch_size`, not
    off by a few from independent per-task rounding). This is the
    number a training-set builder actually consumes — "draw N_task
    examples of this task" — the weights themselves are the
    intermediate, reusable artifact."""
    weights = compute_sampling_weights(task_counts, **kwargs)
    if not weights or batch_size <= 0:
        return {task: 0 for task in weights}
    raw = {task: w * batch_size for task, w in weights.items()}
    floored = {task: int(r) for task, r in raw.items()}
    remainder = batch_size - sum(floored.values())
    # Largest-remainder method: hand out the leftover slots to whichever
    # tasks' fractional part was closest to rounding up, in order.
    remainders = sorted(raw, key=lambda t: raw[t] - floored[t], reverse=True)
    for task in remainders[:remainder]:
        floored[task] += 1
    return floored
