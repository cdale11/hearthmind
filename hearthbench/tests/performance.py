"""HearthBench A5.9 — Performance. "Latency (p50/p95/max), TTFT,
tok/s, RAM/swap/CPU%, sampled continuously, attributed per case."

Scoped honestly: this category wraps A4.1's already-shipped `latency`
scorer (a pure per-case measurement, `value=None` by design — see that
scorer's own docstring) and adds the one thing a *category* can
compute that a single scorer can't — real p50/p95/max/mean aggregation
across many cases' `ScoreDetail.detail` readings, the "attributed per
case" half of A5.9's own text. Continuous RAM/swap/CPU% sampling
(A7.2, a system-sampling thread) is real, distinct, unstarted future
work — this module has no sampling thread and makes no claim to.

`tok/s` needs `prompt_tokens`/`completion_tokens` alongside
`latency_ms`; `AdapterResult`/`CaseResult` both already carry token
counts (A2.1's own `AdapterResult` fields), so `summarize_latency`
computes completion tok/s wherever both fields are present on a
result's own detail, `None` otherwise — never a divide-by-zero, never
a guessed denominator.

Import isolation (A1.2): stdlib + `hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.tests.category import Category, percentile

PERFORMANCE_CATEGORY = Category(
    id="performance", name="Performance", weight=5.0,
    scorer_ids=("latency",),
    description="Latency (p50/p95/max), TTFT, and completion tok/s, attributed per case.",
)


def summarize_latency(score_details: list) -> dict:
    """`score_details` is a real list of `latency` scorer
    `ScoreDetail`s (`.value` is always `None` for this scorer by
    design — every real number lives in `.detail`). Every stat
    degrades to `None` on an empty/all-missing input rather than
    raising or reporting a fabricated `0`."""
    latencies = [d.detail.get("latency_ms") for d in score_details if isinstance(d.detail.get("latency_ms"), (int, float))]
    ttfts = [d.detail.get("ttft_ms") for d in score_details if isinstance(d.detail.get("ttft_ms"), (int, float))]
    tok_per_sec = []
    for d in score_details:
        latency_ms = d.detail.get("latency_ms")
        completion_tokens = d.detail.get("completion_tokens")
        if isinstance(latency_ms, (int, float)) and latency_ms > 0 and isinstance(completion_tokens, (int, float)):
            tok_per_sec.append(completion_tokens / (latency_ms / 1000.0))

    def _stats(values: list) -> dict:
        if not values:
            return {"p50": None, "p95": None, "max": None, "mean": None, "n": 0}
        sorted_values = sorted(values)
        return {
            "p50": percentile(sorted_values, 0.50), "p95": percentile(sorted_values, 0.95),
            "max": max(values), "mean": sum(values) / len(values), "n": len(values),
        }

    return {
        "latency_ms": _stats(latencies), "ttft_ms": _stats(ttfts), "completion_tokens_per_sec": _stats(tok_per_sec),
        "n_total": len(score_details),
    }
