"""Metrics collector (A7): per-case/per-category/per-run aggregates,
a system-sampling thread (RSS, swap, CPU%), statistical hygiene (N,
mean, median, p95).

A7.1 shipped this pass (`aggregate.py`'s `recompute_run_metrics`): real
proof that per-category statistics are recomputable from a stored run
directory (A8) with zero adapter calls — reuses `hearthbench.tests.
category.summarize_scores` (A7.3, already shipped) rather than a
second aggregation mechanism. A7.2 (the system-sampling thread) stays
real, distinct, unstarted future work — needs a live long-running
benchmark process to sample against.
"""
from __future__ import annotations

from hearthbench.metrics.aggregate import recompute_run_metrics

__all__ = ["recompute_run_metrics"]
