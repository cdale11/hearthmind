"""HearthBench A7 — Metrics collector.

A7.1 ("aggregates can be recomputed without re-running"), made real
and tested rather than merely claimed: `recompute_run_metrics` reads a
run's raw per-case records straight off disk (A8's `RunRecordReader`)
and re-derives per-category/per-scorer statistics via A5's own
`summarize_scores` — the SAME function `hearthbench.runner.run.
aggregate_scores` calls for a live in-memory run, just fed from a
stored `CaseRecord`'s already-scored `scores` dict instead of a fresh
scoring pass. No adapter is ever constructed here, no case is ever
re-sent — this function's own existence is the proof A7.1's claim
holds, not an assumption.

A7.2 (a background system-sampling thread — RSS/swap/CPU%, llama-
server's `/metrics` endpoint, aligned to case boundaries) is real,
distinct, unstarted future work: it needs a live long-running benchmark
process to sample against, which this offline environment has no real
run long enough to exercise meaningfully; flagged, not attempted.

A7.3 (N/mean/median/p95/stdev/confidence interval per category)
already shipped as `hearthbench.tests.category.summarize_scores`/
`CategoryScoreSummary` (A5, v1.34.279) — reused here directly, not
reimplemented a second time.

Import isolation (A1.2): stdlib + `hearthbench.diagnostics`/
`hearthbench.scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.diagnostics.run_record import RunRecordReader
from hearthbench.scoring.types import ScoreDetail
from hearthbench.tests.category import summarize_scores


def recompute_run_metrics(run_dir: "str") -> dict:
    """Walks every `CaseRecord` a run directory actually committed,
    regroups its already-stored `ScoreDetail`s by `(category,
    scorer_id)`, and calls `summarize_scores` fresh — returns
    `{category_id: {scorer_id: CategoryScoreSummary}}`, the identical
    shape `hearthbench.runner.run.aggregate_scores` returns for a live
    run, so a caller (a future A9 report, A13's own CI guard re-run
    against an archived run) can treat "freshly scored" and "recomputed
    from disk" results uniformly. A run directory with no committed
    cases yet returns `{}`, not an error."""
    reader = RunRecordReader(run_dir)
    grouped: dict = {}
    for record in reader.iter_case_records():
        for scorer_id, raw_detail in (record.scores or {}).items():
            detail = ScoreDetail.from_dict(raw_detail)
            grouped.setdefault(record.category, {}).setdefault(scorer_id, []).append(detail)

    summaries: dict = {}
    for category_id, by_scorer in grouped.items():
        summaries[category_id] = {
            scorer_id: summarize_scores(category_id, details) for scorer_id, details in by_scorer.items()
        }
    return summaries
