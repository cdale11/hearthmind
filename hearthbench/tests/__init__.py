"""HearthBench A5 — Benchmark categories.

Objective categories (fully lifted onto A4's real scorers, needing no
judge model): `grounding` (A5.7, weighted highest per A10.1),
`structured_outputs` (A5.8), `performance` (A5.9).

The six subjective categories — `dialogue` (A5.1), `personality`
(A5.2), `memory` (A5.3), `beliefs` (A5.4), `planning` (A5.5),
`village_cognition` (A5.6) — are now real too: each gets a genuinely
distinct judge rubric via A4.2's now-generalized `JudgeScorer`
(`hearthbench.scoring.judge`, which defaults to Dialogue's own
original rubric unchanged), plus real hand-authored `TestCase`s.
Memory/Beliefs are the two categories A3.3's multi-turn `Turn.
injected_fact`/`expects_recall_of`/`offers_contradiction` machinery
was built for — see each module's own docstring for how the two
categories deliberately test opposite behaviors on the same mechanism
(Memory: hold to an established truth against a false contradiction;
Beliefs: revise a theory when genuinely new evidence arrives).

A5.11 (the world-level emergence run) is explicitly gated on B15.5
(reference mode) and is the checklist's own last item to build — still
open, not attempted here.

`CATEGORY_REGISTRY` is the one place a future A9/A10/A11 would look up
"every category this benchmark knows about" — see A5.10's own guide
(`docs/HEARTHBENCH-CATEGORY-GUIDE.md`) for how to add a new one.
"""
from __future__ import annotations

from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.tests.beliefs import BELIEFS_CATEGORY, build_beliefs_cases, build_beliefs_judge_scorer
from hearthbench.tests.category import Category, CategoryScoreSummary, percentile, summarize_scores
from hearthbench.tests.dialogue import (
    DIALOGUE_CATEGORY,
    NO_AMBIENT_FILLER_SCORER,
    build_dialogue_cases,
    build_dialogue_judge_scorer,
)
from hearthbench.tests.grounding import (
    GROUNDING_CATEGORY,
    NO_UNSUPPORTED_SPECIFICS_SCORER,
    build_grounding_bait_cases,
)
from hearthbench.tests.memory import MEMORY_CATEGORY, build_memory_cases, build_memory_judge_scorer
from hearthbench.tests.performance import PERFORMANCE_CATEGORY, summarize_latency
from hearthbench.tests.personality import (
    PERSONALITY_CATEGORY,
    build_personality_cases,
    build_personality_judge_scorer,
)
from hearthbench.tests.planning import PLANNING_CATEGORY, build_planning_cases, build_planning_judge_scorer
from hearthbench.tests.structured_outputs import (
    STRUCTURED_OUTPUTS_CATEGORY,
    build_structured_output_cases,
    score_structured_output_delta,
)
from hearthbench.tests.village_cognition import (
    VILLAGE_COGNITION_CATEGORY,
    build_village_cognition_cases,
    build_village_cognition_judge_scorer,
)

CATEGORY_REGISTRY = {
    GROUNDING_CATEGORY.id: GROUNDING_CATEGORY,
    STRUCTURED_OUTPUTS_CATEGORY.id: STRUCTURED_OUTPUTS_CATEGORY,
    PERFORMANCE_CATEGORY.id: PERFORMANCE_CATEGORY,
    DIALOGUE_CATEGORY.id: DIALOGUE_CATEGORY,
    PERSONALITY_CATEGORY.id: PERSONALITY_CATEGORY,
    MEMORY_CATEGORY.id: MEMORY_CATEGORY,
    BELIEFS_CATEGORY.id: BELIEFS_CATEGORY,
    PLANNING_CATEGORY.id: PLANNING_CATEGORY,
    VILLAGE_COGNITION_CATEGORY.id: VILLAGE_COGNITION_CATEGORY,
}

# A5.10's own guide (step 4) says a new Tier 1 scorer should be
# registered into `hearthbench.scoring.DEFAULT_REGISTRY` so a real
# runner's `registry.resolve(case.scorers)` can find it by id — a
# category module can't do this itself (it would make `hearthbench.
# scoring` import from `hearthbench.tests`, a real circular import;
# this package already imports FROM `hearthbench.scoring`, so
# extending the shared registry HERE, one-directionally, is the
# correct place). `no_unsupported_specifics` (A5.7) and `no_ambient_
# filler` (A5.1) are each a category's own category-specific Tier 1
# scorer — registering them here is what makes `run_case_against_
# adapter`/`run_cases_against_adapter` (`hearthbench.runner.run`, A11's
# own real slice) actually score a case's full declared scorer set
# instead of silently dropping an id `DEFAULT_REGISTRY` didn't know
# about.
DEFAULT_REGISTRY.register(NO_UNSUPPORTED_SPECIFICS_SCORER)
DEFAULT_REGISTRY.register(NO_AMBIENT_FILLER_SCORER)
# Every judge_* scorer is deliberately NOT auto-registered here — per
# `hearthbench.scoring`'s own module docstring, Tier 2/3 scorers are
# per-run constructions (they close over a live judge adapter), so
# each needs `build_*_judge_scorer(adapter)` called with a real
# adapter at run time, not a module-import-time registration.

__all__ = [
    "Category", "CategoryScoreSummary", "percentile", "summarize_scores",
    "CATEGORY_REGISTRY",
    "GROUNDING_CATEGORY", "NO_UNSUPPORTED_SPECIFICS_SCORER", "build_grounding_bait_cases",
    "STRUCTURED_OUTPUTS_CATEGORY", "build_structured_output_cases", "score_structured_output_delta",
    "PERFORMANCE_CATEGORY", "summarize_latency",
    "DIALOGUE_CATEGORY", "NO_AMBIENT_FILLER_SCORER", "build_dialogue_cases", "build_dialogue_judge_scorer",
    "PERSONALITY_CATEGORY", "build_personality_cases", "build_personality_judge_scorer",
    "MEMORY_CATEGORY", "build_memory_cases", "build_memory_judge_scorer",
    "BELIEFS_CATEGORY", "build_beliefs_cases", "build_beliefs_judge_scorer",
    "PLANNING_CATEGORY", "build_planning_cases", "build_planning_judge_scorer",
    "VILLAGE_COGNITION_CATEGORY", "build_village_cognition_cases", "build_village_cognition_judge_scorer",
]
