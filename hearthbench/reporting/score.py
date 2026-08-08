"""HearthBench A10 — The HearthBench Score.

A10.1 (weighted composite, explained): `CATEGORY_REGISTRY[id].weight`
already IS the checklist's own stated default weight table — all nine
named categories (Grounding 20, Dialogue 15, Beliefs 12, Memory 12,
Village cognition 10, Personality 10, Planning 8, Reliability/
structured-output 8, Performance 5) are now real `Category` objects
(A5.1-A5.6 shipped their judge rubric + content; `MISSING_SUBJECTIVE_
CATEGORY_WEIGHTS` is kept only as a real, empty extension point — a
future genuinely-new category with no `Category` yet can still be
recorded there for honest "missing" reporting before it ships, the
same role it played for A5.1-A5.6 themselves). `compute_score`
renormalizes weight over ONLY the categories that actually have real
scored data this run — a category with zero real cases contributes
neither a fabricated zero (which would be a made-up penalty) nor
silent full credit (which would overstate confidence); it is named in
`categories_missing` instead, and the report (A9) must say so plainly
(A9.4).

A10.2 (disqualifying floors): `DEFAULT_DISQUALIFYING_FLOORS` — the
checklist's own worked example (grounding < 50 caps the total at 60)
is the one entry shipped; a caller may pass a different floor table.
A category's floor is only ever checked when that category actually
has a real score this run (a missing category can't disqualify
anything it was never measured on).

A10.3 (normalization discipline): every category score is `[0, 100]`,
via one explicit rubric per category kind, `SCORE_RUBRIC_VERSION`
stamped on every `HearthBenchScore` — never a curve against other
runs' results (no cross-run comparison logic lives in this module at
all; that's A9.3's own job, over TWO already-computed `HearthBench
Score`s). Grounding/structured-outputs/(future subjective) categories
score from `CategoryScoreSummary.pass_rate` (preferred, a real
boolean-gate rate) or `.mean` (fallback, a real graded average) *
100, averaged across a category's own several scorers when it has
more than one — never fabricated from `.value=None` measurement-only
scorers. Performance has no boolean/graded scorer at all (`latency`'s
own `ScoreDetail.value` is `None` by design, per that scorer's own
docstring — "A10's future rubric, not this scorer, decides") — this
IS that future rubric: `score_from_latency_stats` maps a run's real
measured p50 latency onto `[0, 100]` via `LATENCY_SCORE_BANDS_MS`, a
loosely-reasoned starting point (not validated against a real
archive, same "starting points, not validated targets" framing
`hearthmind.llm.eval_harness.DEFAULT_THRESHOLDS`'s own docstring
already carries for this project) rather than a permanently unscoreable
category.

A10.4 (confidence): `HearthBenchScore.category_confidence_margin` (a
real 95% CI half-width, scaled to the same `[0, 100]` axis, per scored
category — reusing `CategoryScoreSummary.confidence_interval_95`
directly, no second interval computed) lets `overall_confidence_
margin` report the WIDEST (least confident) margin among the
categories that actually contributed to the total — "a composite is
only as confident as its shakiest measured input," never an
average that could hide one badly-undersampled category behind
several well-sampled ones.

Import isolation (A1.2): stdlib + `hearthbench.tests.category`/
`hearthbench.tests` only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthbench.tests import CATEGORY_REGISTRY

SCORE_RUBRIC_VERSION = "1"

MISSING_SUBJECTIVE_CATEGORY_WEIGHTS: dict = {}
"""Empty as of A5.1-A5.6 shipping — every category the checklist's own
A10.1 weight table names now has a real `Category` in `hearthbench.
tests.CATEGORY_REGISTRY`. Kept (not deleted) as the real extension
point it always was: a future genuinely-new category can be recorded
here — `{category_id: weight}` — the moment its weight is DECIDED but
before its `Category`/content/scorer ship, so `compute_score` can
report it as honestly "missing" from day one rather than silently
absent from `categories_missing` until the code catches up."""

DEFAULT_DISQUALIFYING_FLOORS = {
    "grounding": (50.0, 60.0, "a model that fails grounding cannot be recommended regardless of other scores"),
}
"""A10.2's own worked example, `{category_id: (floor, cap, reason)}` —
a category score below `floor` caps the WHOLE composite at `cap`, only
ever checked for a category that was actually scored this run."""

LATENCY_SCORE_BANDS_MS = (
    (2000.0, 100.0), (5000.0, 85.0), (10000.0, 65.0), (20000.0, 40.0), (40000.0, 15.0),
)
"""A10.3's real Performance-category rubric: `(p50_ceiling_ms, score)`
pairs, checked in order — a run's real measured p50 latency at or
below a band's ceiling earns that band's score; above every band
scores the floor (`LATENCY_SCORE_FLOOR`). Loosely reasoned against
this project's own documented local-LLM latency range (CLAUDE.md
records live p50/p95 in the tens of seconds on real 8GB/iGPU
hardware, so `10000ms` deliberately sits mid-band rather than
treating ordinary local-model latency as an automatic failure) — a
starting point, not a validated target; a maintainer tunes these
against a real measured archive the same way `DEFAULT_CI_THRESHOLDS`
is meant to be tuned."""
LATENCY_SCORE_FLOOR = 5.0


@dataclass
class HearthBenchScore:
    total: "float | None"
    """`None` only when literally nothing was scored this run — the
    honest zero-data case, never conflated with a genuine low score."""
    category_scores: dict = field(default_factory=dict)
    """`{category_id: score_0_to_100}` — every category that
    contributed to `total`."""
    category_confidence_margin: dict = field(default_factory=dict)
    """`{category_id: margin_0_to_100 | None}` — `None` when that
    category's own CI couldn't be computed (fewer than 2 samples)."""
    categories_used: list = field(default_factory=list)
    categories_missing: list = field(default_factory=list)
    """Every category in `CATEGORY_REGISTRY` plus `MISSING_SUBJECTIVE_
    CATEGORY_WEIGHTS` that contributed nothing to `total` this run."""
    weights_used: dict = field(default_factory=dict)
    """The REAL, renormalized weight each used category was scored at
    (sums to 1.0 across `categories_used`) — distinct from each
    `Category.weight`'s own raw, un-renormalized value."""
    disqualifications: list = field(default_factory=list)
    """`[{category, floor, cap, reason, actual}]` — every A10.2 floor
    that actually fired this run."""
    overall_confidence_margin: "float | None" = None
    """The single widest per-category margin among `categories_used` —
    A10.4's "only as confident as the shakiest measured input.\""""
    n_cases_total: int = 0
    rubric_version: str = SCORE_RUBRIC_VERSION


def _category_score_and_margin(scorer_summaries: dict) -> "tuple[float | None, float | None, int]":
    """Averages every scorer's own `pass_rate` (preferred) or `mean`
    (fallback, for a scorer with no boolean gate) across a category's
    real summaries, each mapped to `[0, 100]`; a measurement-only
    scorer with neither (e.g. `latency`, `n_scored == 0` and `pass_
    rate is None`) is skipped, not treated as a zero. Returns `(score,
    widest_margin, n_cases)`; `score` is `None` when every scorer in
    the category had nothing to contribute."""
    per_scorer_scores = []
    widest_margin = None
    n_cases = 0
    for summary in scorer_summaries.values():
        n_cases = max(n_cases, summary.n_total)
        basis = summary.pass_rate if summary.pass_rate is not None else summary.mean
        if basis is None:
            continue
        per_scorer_scores.append(basis * 100.0)
        if summary.confidence_interval_95 is not None:
            lo, hi = summary.confidence_interval_95
            margin = ((hi - lo) / 2.0) * 100.0
            if widest_margin is None or margin > widest_margin:
                widest_margin = margin
    if not per_scorer_scores:
        return None, None, n_cases
    return sum(per_scorer_scores) / len(per_scorer_scores), widest_margin, n_cases


def score_from_latency_stats(latency_stats: "dict | None") -> "float | None":
    """A10.3's real Performance rubric, applied to `hearthbench.tests.
    performance.summarize_latency`'s own `latency_ms` sub-dict — `None`
    when no real p50 was measured (an empty/missing input), never a
    fabricated 0."""
    if not latency_stats:
        return None
    p50 = (latency_stats.get("latency_ms") or {}).get("p50")
    if p50 is None:
        return None
    for ceiling, score in LATENCY_SCORE_BANDS_MS:
        if p50 <= ceiling:
            return score
    return LATENCY_SCORE_FLOOR


def compute_score(
    category_summaries: dict, latency_stats: "dict | None" = None,
    floors: "dict | None" = None,
) -> HearthBenchScore:
    """`category_summaries` is `{category_id: {scorer_id: CategoryScore
    Summary}}` — the exact shape both `hearthbench.runner.run.
    aggregate_scores` (a live run) and `hearthbench.metrics.aggregate.
    recompute_run_metrics` (a stored run, read back from disk) already
    return, so this composes with either with zero adaptation.
    `latency_stats` is `hearthbench.tests.performance.summarize_
    latency`'s own return shape, over the performance category's raw
    `ScoreDetail`s (not derivable from `category_summaries` alone,
    since `latency`'s own summary always carries `n_scored=0` — see
    this module's own docstring)."""
    floors = floors if floors is not None else DEFAULT_DISQUALIFYING_FLOORS

    raw_scores: dict = {}
    margins: dict = {}
    n_cases_total = 0
    for category_id, category in CATEGORY_REGISTRY.items():
        if category_id == "performance":
            score = score_from_latency_stats(latency_stats)
            margin = None
            n_cases = (latency_stats or {}).get("n_total", 0)
        else:
            score, margin, n_cases = _category_score_and_margin(category_summaries.get(category_id, {}))
        if score is None:
            continue
        raw_scores[category_id] = score
        margins[category_id] = margin
        n_cases_total += n_cases

    categories_used = sorted(raw_scores.keys())
    all_weighted_ids = set(CATEGORY_REGISTRY.keys()) | set(MISSING_SUBJECTIVE_CATEGORY_WEIGHTS.keys())
    categories_missing = sorted(all_weighted_ids - set(categories_used))

    if not categories_used:
        return HearthBenchScore(
            total=None, categories_missing=categories_missing, rubric_version=SCORE_RUBRIC_VERSION,
        )

    raw_weight_total = sum(CATEGORY_REGISTRY[cid].weight for cid in categories_used)
    weights_used = {cid: CATEGORY_REGISTRY[cid].weight / raw_weight_total for cid in categories_used}
    total = sum(raw_scores[cid] * weights_used[cid] for cid in categories_used)

    disqualifications = []
    for category_id, (floor, cap, reason) in floors.items():
        if category_id in raw_scores and raw_scores[category_id] < floor:
            if total > cap:
                total = cap
            disqualifications.append({
                "category": category_id, "floor": floor, "cap": cap, "reason": reason, "actual": raw_scores[category_id],
            })

    real_margins = [m for m in margins.values() if m is not None]
    overall_margin = max(real_margins) if real_margins else None

    return HearthBenchScore(
        total=total, category_scores=raw_scores, category_confidence_margin=margins,
        categories_used=categories_used, categories_missing=categories_missing,
        weights_used=weights_used, disqualifications=disqualifications,
        overall_confidence_margin=overall_margin, n_cases_total=n_cases_total,
        rubric_version=SCORE_RUBRIC_VERSION,
    )
