"""Reports (A9) & the HearthBench Score (A10): self-contained HTML
report, JSON/CSV exports, N-run comparison, weighted composite score
with disqualifying floors.

`ci_guard.py` (A13) shipped first — a specialized comparison report
against a stored baseline, closer in shape to A9's own work than to
any other reserved module. `score.py` (A10) and `report.py` (A9)
shipped next: `compute_score` (the real weighted composite, honest
about missing categories, A10.2's disqualifying floors, A10.4's
confidence margin); `render_html_report`/`export_json`/`export_csv`/
`recommendation_text`/`compare_runs` (A9.1-A9.4). A9.1's latency/memory
GRAPHS are explicitly not attempted — no charting dependency exists in
this repo; the real numbers are printed as a plain table instead.

`passport.py` (C5) ships the model-passport half of Part C: `build_
passport`/`save_passport`/`load_passport` emit a small, portable
`passport.json` from a real `HearthBenchScore`; the OTHER half —
`hearthmind.simulation.hardware_profile.seed_machine_profile_from_
passport`, the runtime actually reading one at startup — deliberately
lives on the `hearthmind` side, not here, per A1.2's own two-directional
import firewall (see `passport.py`'s own docstring).
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
from hearthbench.reporting.passport import (
    PASSPORT_SCHEMA_VERSION,
    STRENGTH_THRESHOLD,
    WEAKNESS_THRESHOLD,
    ModelPassport,
    build_passport,
    load_passport,
    produced_by_host,
    save_passport,
)
from hearthbench.reporting.report import (
    LOW_CONFIDENCE_MARGIN_THRESHOLD,
    CategoryComparison,
    ComparisonReport,
    compare_runs,
    export_csv,
    export_json,
    recommendation_text,
    render_html_report,
)
from hearthbench.reporting.score import (
    DEFAULT_DISQUALIFYING_FLOORS,
    LATENCY_SCORE_BANDS_MS,
    MISSING_SUBJECTIVE_CATEGORY_WEIGHTS,
    SCORE_RUBRIC_VERSION,
    HearthBenchScore,
    compute_score,
    score_from_latency_stats,
)

__all__ = [
    "DEFAULT_CI_THRESHOLDS", "CIGuardResult", "build_default_ci_cases",
    "is_relevant_change", "load_baseline", "run_ci_guard", "save_baseline",
    "PASSPORT_SCHEMA_VERSION", "STRENGTH_THRESHOLD", "WEAKNESS_THRESHOLD", "ModelPassport",
    "build_passport", "load_passport", "produced_by_host", "save_passport",
    "LOW_CONFIDENCE_MARGIN_THRESHOLD", "CategoryComparison", "ComparisonReport",
    "compare_runs", "export_csv", "export_json", "recommendation_text", "render_html_report",
    "DEFAULT_DISQUALIFYING_FLOORS", "LATENCY_SCORE_BANDS_MS", "MISSING_SUBJECTIVE_CATEGORY_WEIGHTS",
    "SCORE_RUBRIC_VERSION", "HearthBenchScore", "compute_score", "score_from_latency_stats",
]
