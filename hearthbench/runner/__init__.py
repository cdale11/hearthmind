"""Bench run orchestration (A11): quick/full/custom run modes, resume
from a partial run, per-case scheduling against a `ModelAdapter` (A2).

`run.py` ships the one real execution-core slice A13 (the CI
regression guard) needed: resolve a `TestCase` to a real prompt, call
a real adapter, score the result — plus, this pass, A11.4 (`run_
cases_with_resume`, built on `hearthbench.diagnostics`'s real A8 run
record: every completed case commits immediately, a second call
against the same `run_dir` skips whatever's already committed). Quick/
full/custom mode selection and `--strict-repro` remain a later, fuller
A11 pass — see `run.py`'s own docstring for exactly what's covered.
"""
from __future__ import annotations

from hearthbench.runner.run import (
    aggregate_scores,
    render_case_prompt,
    run_case_against_adapter,
    run_cases_against_adapter,
    run_cases_with_resume,
    summaries_to_metrics_dict,
)

__all__ = [
    "render_case_prompt", "run_case_against_adapter", "run_cases_against_adapter",
    "run_cases_with_resume", "aggregate_scores", "summaries_to_metrics_dict",
]
