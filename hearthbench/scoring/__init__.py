"""HearthBench A4 — Scoring & the judge problem.

**[DECIDED: build both paths]** (docs/HEARTHBENCH-RUNTIME-2026-07-23.md):
deterministic-only scoring is a first-class run mode, used by CI (A13)
and quick screening; the judge tier is an additive layer for
subjective categories. This package ships all three tiers as real,
independently-testable primitives:

- **Tier 1 (A4.1)** — `deterministic.py`: nine free, always-on scorers,
  five lifted directly from `hearthmind.llm.quality_labels`/
  `.review_diagnostics`, four genuinely new (fallback-rate, latency-
  as-measurement, lexical diversity, multi-turn recall).
- **Tier 2 (A4.2)** — `judge.py`: `JudgeScorer` wraps any A2
  `ModelAdapter` behind a fixed, versioned rubric with few-shot
  anchors; `measure_self_consistency` re-scores a sample to report a
  judge's own reliability.
- **Tier 3 (A4.3)** — `human.py`: the blind-pairwise data model +
  `judge_human_agreement` — the report the checklist names; the
  rating PAGE itself is A12.9's job, not built here.
- **A4.4** — `types.py`/`registry.py`: `Scorer(id, version, fn(case,
  result, context) -> ScoreDetail)`, `ScorerRegistry`. `DEFAULT_
  REGISTRY` below is pre-populated with every Tier 1 scorer (always
  safe, always free) — Tier 2/3 scorers are per-run constructions
  (they close over a live judge adapter / a rating file), registered
  by a caller via `registry.register(judge.as_scorer())`, not
  auto-registered here.

Both run paths the checklist requires produce a valid report using
only this package: `registry.resolve(["schema_validity", "leak_
freedom", ...])` for `--no-judge`, or the same list plus a
`JudgeScorer.as_scorer()` id for the full run.
"""
from __future__ import annotations

from hearthbench.scoring.deterministic import DETERMINISTIC_SCORERS, register_deterministic_scorers
from hearthbench.scoring.human import (
    HumanRating,
    HumanRatingTask,
    append_rating,
    judge_human_agreement,
    judge_implied_choice,
    load_ratings,
)
from hearthbench.scoring.judge import JudgeScorer, build_judge_prompt, measure_self_consistency
from hearthbench.scoring.registry import DuplicateScorerError, ScorerRegistry
from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer

DEFAULT_REGISTRY = ScorerRegistry()
register_deterministic_scorers(DEFAULT_REGISTRY)

__all__ = [
    "CaseResult", "ScoreDetail", "Scorer",
    "ScorerRegistry", "DuplicateScorerError", "DEFAULT_REGISTRY",
    "DETERMINISTIC_SCORERS", "register_deterministic_scorers",
    "JudgeScorer", "build_judge_prompt", "measure_self_consistency",
    "HumanRatingTask", "HumanRating", "append_rating", "load_ratings",
    "judge_implied_choice", "judge_human_agreement",
]
