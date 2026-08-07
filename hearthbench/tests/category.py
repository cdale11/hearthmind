"""HearthBench A5 — shared category infrastructure.

Every category module in this package (`grounding.py`, `structured_
outputs.py`, `performance.py`, ...) defines two things: a `Category`
(id/name/weight/scorer ids, matching A10.1's own default-weight table
so a category module IS the source of truth A10's future composite
would read from) and a `build_*_cases()` function returning real
`hearthbench.prompts.schema.TestCase` objects — never a live score,
since A11 (the runner) doesn't exist yet.

`summarize_scores` is this pass's honest, CATEGORY-SCOPED slice of
A7.3's stated statistics ("N, mean, median, p95, stdev, and a
confidence interval per category — feeds A10"). It is NOT A7 (the
metrics collector) — no system-sampling thread, no per-run record, no
cross-category rollup. A caller with a real list of `ScoreDetail`s for
one category (from a live run, once A11 exists, or from a synthetic/
recorded sample today) gets real, tested statistics back; A7 building
the full per-run collector around this remains open, unstarted work.

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring` only.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    """One A5 benchmark category. `weight` mirrors A10.1's own stated
    default composite weights (Grounding 20, Dialogue 15, Beliefs 12,
    Memory 12, Village cognition 10, Personality 10, Planning 8,
    Reliability/structured-output 8, Performance 5) — recorded here so
    a future A10 composite reads real category metadata instead of a
    second hardcoded table that could drift from this one."""

    id: str
    name: str
    weight: float
    scorer_ids: tuple
    description: str = ""


@dataclass
class CategoryScoreSummary:
    """The A7.3-shaped statistics for one category's real scored
    cases. `n_scored` counts only `ScoreDetail`s with a non-`None`
    `value` — a measurement-only scorer (e.g. `latency`) or a not-
    applicable one contributes to `n_total` but never to the mean/
    percentiles, same "None means no data point, never a zero"
    discipline every scorer in this package already holds."""

    category_id: str
    n_total: int
    n_scored: int
    mean: float | None = None
    median: float | None = None
    p95: float | None = None
    stdev: float | None = None
    confidence_interval_95: tuple | None = None
    n_passed: int | None = None
    n_failed: int | None = None
    pass_rate: float | None = None
    detail: dict = field(default_factory=dict)


def percentile(sorted_values: list, pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list — the same
    simple, dependency-free method `hearthmind.llm.review_diagnostics`
    already uses elsewhere in this codebase for p95 reporting, reused
    here by the same reasoning (no numpy dependency for one interpolated
    number)."""
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    frac = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def _confidence_interval_95(values: list) -> tuple | None:
    """A normal-approximation 95% CI on the mean (`mean +/- 1.96 *
    stderr`) — the simplest defensible interval for "feeds A10's
    score-confidence requirement" without pulling in a stats library;
    `None` below 2 samples (no spread to estimate from)."""
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    stderr = statistics.stdev(values) / math.sqrt(len(values))
    margin = 1.96 * stderr
    return (mean - margin, mean + margin)


def summarize_scores(category: "Category | str", score_details: list) -> CategoryScoreSummary:
    """`score_details` is a real list of `hearthbench.scoring.
    ScoreDetail` (or anything duck-typed the same way) for ONE
    category's cases — never mixes categories, matching the checklist's
    own "per category" framing. Never raises on an empty list (a
    category with zero real results yet is a legitimate state, not an
    error) — every stat degrades to `None`."""
    category_id = category.id if isinstance(category, Category) else category
    n_total = len(score_details)
    scored_values = [d.value for d in score_details if d.value is not None]
    passed_values = [d.passed for d in score_details if d.passed is not None]
    n_passed = sum(1 for p in passed_values if p) if passed_values else None
    n_failed = sum(1 for p in passed_values if not p) if passed_values else None
    pass_rate = (n_passed / len(passed_values)) if passed_values else None
    if not scored_values:
        return CategoryScoreSummary(
            category_id=category_id, n_total=n_total, n_scored=0,
            n_passed=n_passed, n_failed=n_failed, pass_rate=pass_rate,
        )
    sorted_values = sorted(scored_values)
    return CategoryScoreSummary(
        category_id=category_id, n_total=n_total, n_scored=len(scored_values),
        mean=statistics.mean(scored_values), median=statistics.median(scored_values),
        p95=percentile(sorted_values, 0.95),
        stdev=statistics.stdev(scored_values) if len(scored_values) >= 2 else 0.0,
        confidence_interval_95=_confidence_interval_95(scored_values),
        n_passed=n_passed, n_failed=n_failed, pass_rate=pass_rate,
    )
