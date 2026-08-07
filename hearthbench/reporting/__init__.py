"""Reports (A9) & the HearthBench Score (A10): self-contained HTML
report, JSON/CSV exports, N-run comparison, weighted composite score
with disqualifying floors. Not yet implemented.

`ci_guard.py` ships real, distinct A13 content (the prompt-regression
CI guard) — a specialized comparison report against a stored baseline,
closer in shape to A9's own future work than to any other reserved
module — see that file's own docstring. A9/A10 themselves remain
unbuilt.
"""
from __future__ import annotations

from hearthbench.reporting.ci_guard import (
    DEFAULT_CI_THRESHOLDS,
    CIGuardResult,
    build_default_ci_cases,
    is_relevant_change,
    load_baseline,
    run_ci_guard,
    save_baseline,
)

__all__ = [
    "DEFAULT_CI_THRESHOLDS", "CIGuardResult", "build_default_ci_cases",
    "is_relevant_change", "load_baseline", "run_ci_guard", "save_baseline",
]
