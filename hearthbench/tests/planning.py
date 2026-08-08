"""HearthBench A5.5 — Planning. "Goal formation, multi-step coherence,
horizon realism, adaptation when blocked."

Two real cases: `planning:goal_formation` (a scenario with a real
constraint, asking the character to state a plan) and `planning:
adaptation_when_blocked` (a multi-turn case where a stated plan hits a
genuine obstacle mid-conversation, testing whether the character
adapts rather than repeating the original plan unchanged).

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.judge import JudgeScorer
from hearthbench.scoring.types import Scorer
from hearthbench.tests.category import Category

PLANNING_CATEGORY = Category(
    id="planning", name="Planning", weight=8.0,
    scorer_ids=("judge_planning_quality", "leak_freedom"),
    description="Goal formation, multi-step coherence, horizon realism, adaptation when blocked.",
)

PLANNING_RUBRIC_VERSION = "1"

PLANNING_RUBRIC_PROMPT = """You are scoring one line of in-character dialogue from a life \
simulation game for how well the character forms and adapts PLANS. \
Judge ONLY what is asked; do not reward length.

Rubric (score the OUTPUT on each axis, 1=worst, 5=best):
1. Goal coherence: does the stated plan actually address the real goal \
in the scenario, with steps that logically lead toward it (not a vague \
restatement of the goal itself, and not steps that don't connect to \
each other)?
2. Horizon realism: is the plan's scope/timeline plausible for a \
person in this situation (not wildly overambitious for one person, and \
not so trivial it ignores the real difficulty of the goal)?
3. Adaptation when blocked: if the conversation introduces a genuine \
obstacle to the original plan, does the character revise their \
approach to account for it, rather than repeating the original plan \
unchanged as if nothing happened?

Anchors:
- Score 1 goal-coherence example: asked how to gather enough materials \
for a granary before winter, the character talks only about wanting a \
granary without naming any real steps.
- Score 5 goal-coherence example: the character names concrete, \
connected steps that would actually get materials gathered in time.
- Score 1 adaptation example: told the road washed out, the character \
repeats the exact same travel plan as if the obstacle were never \
mentioned.
- Score 5 adaptation example: the character visibly changes course in \
response to the specific obstacle.

Conversation context so far:
{context}

Output being judged:
{output_text}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"goal_coherence": <1-5 int>, "horizon_realism": <1-5 int>, "adaptation_when_blocked": <1-5 int>, "reason": "<one short sentence>"}}
"""

_PLANNING_AXES = ("goal_coherence", "horizon_realism", "adaptation_when_blocked")


def build_planning_judge_scorer(adapter) -> Scorer:
    """`adapter` is any A2-shaped `ModelAdapter` (duck-typed)."""
    judge = JudgeScorer(
        adapter, rubric_prompt=PLANNING_RUBRIC_PROMPT, axes=_PLANNING_AXES,
        rubric_version=PLANNING_RUBRIC_VERSION,
    )
    return judge.as_scorer(
        scorer_id="judge_planning_quality", category="planning",
        description="LLM-judge rating of goal coherence/horizon realism/adaptation when blocked for a stated plan.",
    )


def build_planning_cases() -> list:
    return [
        TestCase(
            id="planning:goal_formation", category="planning",
            system_prompt=(
                "You are Petra, a builder in a small village. Winter is roughly two months away, "
                "and the village granary badly needs repair before the cold sets in."
            ),
            scorers=list(PLANNING_CATEGORY.scorer_ids),
            tags=["planning", "goal_formation"],
            turns=[Turn(index=0, content="Petra, how do you plan to get the granary repaired before winter?")],
        ),
        TestCase(
            id="planning:adaptation_when_blocked", category="planning",
            system_prompt=(
                "You are Petra, a builder in a small village, midway through repairing the "
                "granary before winter."
            ),
            scorers=list(PLANNING_CATEGORY.scorer_ids),
            tags=["planning", "adaptation"],
            turns=[
                Turn(index=0, content="Petra, you said you'd haul the timber in from the eastern grove this week.",
                     injected_fact="Petra planned to haul timber from the eastern grove this week"),
                Turn(index=1, content="Bad news, Petra — the bridge to the eastern grove washed out in the storm.",
                     offers_contradiction=True),
                Turn(index=2, content="So what's the plan now, with the bridge gone?"),
            ],
        ),
    ]


__all__ = [
    "PLANNING_CATEGORY", "PLANNING_RUBRIC_PROMPT", "PLANNING_RUBRIC_VERSION",
    "build_planning_judge_scorer", "build_planning_cases",
]
