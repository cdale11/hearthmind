"""HearthBench A5 — Benchmark categories.

Objective categories shipped this pass (fully lifted onto A4's real
scorers, needing no judge model): `grounding` (A5.7, weighted highest
per A10.1), `structured_outputs` (A5.8), `performance` (A5.9). The
subjective categories (A5.1-A5.6 — dialogue/personality/memory/
beliefs/planning/village cognition) need A4.2's judge tier and real
content authoring; per the checklist's own SEQUENCE ("A4.2 judge +
remaining subjective categories" is a later step than "A4.1
deterministic scorers + A5.7/A5.8"), they're deliberately left for a
future pass, not attempted here. A5.11 (the world-level emergence run)
is explicitly gated on B15.5 (reference mode) and is the checklist's
own last item to build.

`CATEGORY_REGISTRY` is the one place a future A9/A10/A11 would look up
"every category this benchmark knows about" — see A5.10's own guide
(`docs/HEARTHBENCH-CATEGORY-GUIDE.md`) for how to add a new one.
"""
from __future__ import annotations

from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.tests.category import Category, CategoryScoreSummary, percentile, summarize_scores
from hearthbench.tests.grounding import (
    GROUNDING_CATEGORY,
    NO_UNSUPPORTED_SPECIFICS_SCORER,
    build_grounding_bait_cases,
)
from hearthbench.tests.performance import PERFORMANCE_CATEGORY, summarize_latency
from hearthbench.tests.structured_outputs import (
    STRUCTURED_OUTPUTS_CATEGORY,
    build_structured_output_cases,
    score_structured_output_delta,
)

CATEGORY_REGISTRY = {
    GROUNDING_CATEGORY.id: GROUNDING_CATEGORY,
    STRUCTURED_OUTPUTS_CATEGORY.id: STRUCTURED_OUTPUTS_CATEGORY,
    PERFORMANCE_CATEGORY.id: PERFORMANCE_CATEGORY,
}

# A5.10's own guide (step 4) says a new Tier 1 scorer should be
# registered into `hearthbench.scoring.DEFAULT_REGISTRY` so a real
# runner's `registry.resolve(case.scorers)` can find it by id — a
# category module can't do this itself (it would make `hearthbench.
# scoring` import from `hearthbench.tests`, a real circular import;
# this package already imports FROM `hearthbench.scoring`, so
# extending the shared registry HERE, one-directionally, is the
# correct place). `no_unsupported_specifics` is grounding's own
# category-specific Tier 1 scorer (A5.7) — registering it here is what
# makes `run_case_against_adapter`/`run_cases_against_adapter`
# (`hearthbench.runner.run`, A11's own real slice) actually score a
# grounding case's full declared scorer set instead of silently
# dropping the one id `DEFAULT_REGISTRY` didn't know about.
DEFAULT_REGISTRY.register(NO_UNSUPPORTED_SPECIFICS_SCORER)

__all__ = [
    "Category", "CategoryScoreSummary", "percentile", "summarize_scores",
    "CATEGORY_REGISTRY",
    "GROUNDING_CATEGORY", "NO_UNSUPPORTED_SPECIFICS_SCORER", "build_grounding_bait_cases",
    "STRUCTURED_OUTPUTS_CATEGORY", "build_structured_output_cases", "score_structured_output_delta",
    "PERFORMANCE_CATEGORY", "summarize_latency",
]
