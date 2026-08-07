"""Bench run orchestration (A11): quick/full/custom run modes, resume
from a partial run, per-case scheduling against a `ModelAdapter` (A2).

`run.py` ships the one real slice A13 (the CI regression guard) needs
today: resolve a `TestCase` to a real prompt, call a real adapter,
score the result — see that module's own docstring for exactly what's
covered and what's deliberately left to a later, fuller A11 pass
(quick/full/custom mode selection, resume-by-skipping-completed-ids,
`--strict-repro`, progress/ETA reporting).
"""
from __future__ import annotations

from hearthbench.runner.run import (
    aggregate_scores,
    render_case_prompt,
    run_case_against_adapter,
    run_cases_against_adapter,
    summaries_to_metrics_dict,
)

__all__ = [
    "render_case_prompt", "run_case_against_adapter", "run_cases_against_adapter",
    "aggregate_scores", "summaries_to_metrics_dict",
]
