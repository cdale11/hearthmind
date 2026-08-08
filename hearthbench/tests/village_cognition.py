"""HearthBench A5.6 — Village cognition. "Cultural belief formation,
institution reasoning, tradition crystallization, social reasoning."

Distinct in shape from every other subjective category: the other five
(A5.1-A5.5) score an individual agent's voice; this one scores
SETTLEMENT-scale cognition — the collective "village" voice this
project's own production code (`llm/town_brain.py`, `llm/beliefs.py`'s
settlement-scoped path, `llm/culture.py`) already speaks in. Cases are
authored from that same vantage point (a council/collective system
prompt, never a single named agent).

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.judge import JudgeScorer
from hearthbench.scoring.types import Scorer
from hearthbench.tests.category import Category

VILLAGE_COGNITION_CATEGORY = Category(
    id="village_cognition", name="Village Cognition", weight=10.0,
    scorer_ids=("judge_village_cognition_quality", "leak_freedom"),
    description="Cultural belief formation, institution reasoning, tradition crystallization, social reasoning.",
)

VILLAGE_COGNITION_RUBRIC_VERSION = "1"

VILLAGE_COGNITION_RUBRIC_PROMPT = """You are scoring one piece of settlement-level (not individual-agent) \
cognition from a life simulation game — the collective "village voice" \
reasoning about culture, institutions, or tradition. Judge ONLY what is \
asked; do not reward length.

Rubric (score the OUTPUT on each axis, 1=worst, 5=best):
1. Cultural reasoning: does the output reason from the settlement's \
own real, lived history (the events/patterns given), rather than \
inventing a generic cultural justification untethered to what's \
actually happened?
2. Institutional grounding: if the output involves an institution \
(a council, guild, family, faction), does the reasoning reflect that \
institution's real, stated role/objective rather than treating it as \
interchangeable window dressing?
3. Social plausibility: does the reasoning read as a believable \
collective judgment a real small community might actually reach, \
rather than either a hollow platitude or an implausibly unanimous \
certainty?

Anchors:
- Score 1 cultural-reasoning example: a settlement that has faced \
three seasons of hardship “decides” to hold a lavish festival for no \
stated reason connecting to that hardship.
- Score 5 cultural-reasoning example: the reasoning visibly draws on \
the settlement's own stated recent history.
- Score 1 social-plausibility example: absolute, unanimous certainty \
about a genuinely contested community question with no acknowledgment \
of disagreement.
- Score 5 social-plausibility example: a judgment that reads like a \
real community weighing real, sometimes competing, considerations.

Settlement context given (recent history/institution state):
{context}

Output being judged:
{output_text}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"cultural_reasoning": <1-5 int>, "institutional_grounding": <1-5 int>, "social_plausibility": <1-5 int>, "reason": "<one short sentence>"}}
"""

_VILLAGE_COGNITION_AXES = ("cultural_reasoning", "institutional_grounding", "social_plausibility")


def build_village_cognition_judge_scorer(adapter) -> Scorer:
    """`adapter` is any A2-shaped `ModelAdapter` (duck-typed)."""
    judge = JudgeScorer(
        adapter, rubric_prompt=VILLAGE_COGNITION_RUBRIC_PROMPT, axes=_VILLAGE_COGNITION_AXES,
        rubric_version=VILLAGE_COGNITION_RUBRIC_VERSION,
    )
    return judge.as_scorer(
        scorer_id="judge_village_cognition_quality", category="village_cognition",
        description="LLM-judge rating of cultural reasoning/institutional grounding/social plausibility for settlement-level cognition.",
    )


def build_village_cognition_cases() -> list:
    return [
        TestCase(
            id="village_cognition:tradition_crystallization", category="village_cognition",
            system_prompt=(
                "You speak as the collective voice of Marshcroft's council. For the third year "
                "running, the whole village has gathered at the mill on the first frost to share "
                "the last of the season's bread. Some elders now argue this should be formally "
                "recognized as a lasting tradition, not just something that keeps happening."
            ),
            scorers=list(VILLAGE_COGNITION_CATEGORY.scorer_ids),
            tags=["village_cognition", "tradition"],
            turns=[Turn(index=0, content="Should the first-frost bread-sharing become a formal Marshcroft tradition, and why?")],
        ),
        TestCase(
            id="village_cognition:institution_reasoning", category="village_cognition",
            system_prompt=(
                "You speak as the collective voice of Marshcroft's council. The village's only "
                "GUILD, the millers' guild, has seen its membership shrink to a single elderly "
                "member over the past two years, while grain production has actually grown."
            ),
            scorers=list(VILLAGE_COGNITION_CATEGORY.scorer_ids),
            tags=["village_cognition", "institution"],
            turns=[Turn(index=0, content="What should be done about the millers' guild, given it's down to one member?")],
        ),
    ]


__all__ = [
    "VILLAGE_COGNITION_CATEGORY", "VILLAGE_COGNITION_RUBRIC_PROMPT", "VILLAGE_COGNITION_RUBRIC_VERSION",
    "build_village_cognition_judge_scorer", "build_village_cognition_cases",
]
