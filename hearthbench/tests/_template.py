"""HearthBench A5.10 — category extension TEMPLATE. Not a real
category (not registered in `hearthbench.tests.CATEGORY_REGISTRY`,
not imported by `hearthbench/tests/__init__.py`) — copy this file,
rename it, and follow `docs/HEARTHBENCH-CATEGORY-GUIDE.md` alongside
it. Every real shipped category (`grounding.py`, `structured_
outputs.py`, `performance.py`) follows this exact three-part shape.
"""
from __future__ import annotations

from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer
from hearthbench.tests.category import Category

# 1. Declare the category. `weight` should match A10.1's default
#    composite table if this category maps onto one of its named
#    slots; otherwise pick a number relative to the others (a category
#    A10 doesn't know about yet is simply not folded into the
#    composite until it's added there — this file alone never breaks
#    anything).
TEMPLATE_CATEGORY = Category(
    id="template", name="Template Category", weight=0.0,
    scorer_ids=("schema_validity",),  # reuse an existing hearthbench.scoring scorer id wherever one already fits
    description="Replace with a one-sentence description of what this category measures.",
)


# 2. (Optional) A category-specific scorer, ONLY if nothing in
#    `hearthbench.scoring.DETERMINISTIC_SCORERS` already covers what
#    this category needs — most categories can reuse existing Tier 1
#    scorers wholesale (see `structured_outputs.py`, which adds none).
def _score_template(case, result: CaseResult, context: dict) -> ScoreDetail:
    return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None, detail={})


TEMPLATE_SCORER = Scorer(
    id="template_scorer", version="1", fn=_score_template, tier=1, category="template",
    description="Replace with what this scorer actually checks.",
)


# 3. Build real TestCase objects. Two real sources exist today:
#    (a) test_case_from_fixture(fixture, category=...) over a real
#        FixtureExample (hearthbench.prompts.fixtures/perturbation) —
#        the right choice when real recorded/synthesized examples
#        already exist for the underlying task.
#    (b) hand-authored TestCase(..., turns=[Turn(index=0, content=...)])
#        — the right choice for an adversarial/designed prompt with no
#        natural archive source (see grounding.py's bait cases).
def build_template_cases() -> list:
    return []
