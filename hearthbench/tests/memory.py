"""HearthBench A5.3 — Memory. "Recall, appropriate forgetting,
contradiction resistance, long-term integration."

Real multi-turn cases using `hearthbench.prompts.schema.Turn`'s own
`injected_fact`/`expects_recall_of`/`offers_contradiction` fields —
built for exactly this category's needs. Two distinct shapes:
`memory:recall_after_gap` (a fact stated early, recalled several turns
later — the checklist's own worked example) and `memory:contradiction_
resistance` (a fact stated early, a LATER turn states something
inconsistent with it, and a final turn checks the model still holds
the original truth rather than flipping to the contradiction — this is
the "contradiction resistance" bullet specifically; see `beliefs.py`
for the deliberately opposite case, where NEW evidence SHOULD change
the answer).

`multi_turn_recall` (A4.1) is the deterministic scorer these cases are
built to feed directly; `judge_memory_quality` adds the qualitative
half the checklist also asks for ("appropriate forgetting, long-term
integration" — neither is a pure recall/no-recall signal a lexical
check can score).

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.judge import JudgeScorer
from hearthbench.scoring.types import Scorer
from hearthbench.tests.category import Category

MEMORY_CATEGORY = Category(
    id="memory", name="Memory", weight=12.0,
    scorer_ids=("judge_memory_quality", "multi_turn_recall", "context_reflection", "leak_freedom"),
    description="Recall, appropriate forgetting, contradiction resistance, long-term integration.",
)

MEMORY_RUBRIC_VERSION = "1"

MEMORY_RUBRIC_PROMPT = """You are scoring one line of in-character dialogue from a life \
simulation game for how well it handles the character's own memory of \
past events. Judge ONLY what is asked; do not reward length.

Rubric (score the OUTPUT on each axis, 1=worst, 5=best):
1. Recall accuracy: if the character should remember a specific fact \
given the conversation so far, does the output correctly reflect it \
(not merely mention it, but get it RIGHT)?
2. Appropriate forgetting: does the output avoid confidently stating \
specific detail the character was never actually given (a vague or \
uncertain answer about something ungrounded is CORRECT here, a \
confidently invented detail is not)?
3. Contradiction resistance: when a later statement in the \
conversation conflicts with something established earlier, does the \
character hold to the ESTABLISHED fact rather than silently accepting \
the contradiction?

Anchors:
- Score 1 recall example: the conversation established the character's \
brother died two winters ago, and the output describes him as still \
alive.
- Score 5 recall example: the output correctly and naturally \
references the established fact.
- Score 1 contradiction-resistance example: someone falsely claims the \
harvest was poor after it was established as excellent, and the \
character simply agrees.
- Score 5 contradiction-resistance example: the character politely but \
clearly holds to what actually happened.

Conversation context so far (established facts):
{context}

Output being judged:
{output_text}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"recall_accuracy": <1-5 int>, "appropriate_forgetting": <1-5 int>, "contradiction_resistance": <1-5 int>, "reason": "<one short sentence>"}}
"""

_MEMORY_AXES = ("recall_accuracy", "appropriate_forgetting", "contradiction_resistance")


def build_memory_judge_scorer(adapter) -> Scorer:
    """`adapter` is any A2-shaped `ModelAdapter` (duck-typed)."""
    judge = JudgeScorer(
        adapter, rubric_prompt=MEMORY_RUBRIC_PROMPT, axes=_MEMORY_AXES,
        rubric_version=MEMORY_RUBRIC_VERSION,
    )
    return judge.as_scorer(
        scorer_id="judge_memory_quality", category="memory",
        description="LLM-judge rating of recall accuracy/appropriate forgetting/contradiction resistance across a conversation.",
    )


def build_memory_cases() -> list:
    """Two real multi-turn cases, both grounded in this project's own
    domain. Each names the exact fact string in both `injected_fact`
    and `expects_recall_of`/the contradiction turn, so the deterministic
    `multi_turn_recall` scorer (a word-overlap check against that exact
    string) has something concrete to check."""
    return [
        TestCase(
            id="memory:recall_after_gap", category="memory",
            system_prompt="You are Tobin, a fisherman in a small lakeside village.",
            scorers=list(MEMORY_CATEGORY.scorer_ids),
            tags=["memory", "recall"],
            turns=[
                Turn(index=0, content="Tobin, I heard your boat's mast finally gave out last week.",
                     injected_fact="Tobin's boat mast broke last week"),
                Turn(index=1, content="Any word on when you'll get that boat sorted, Tobin?"),
                Turn(index=2, content="It's been a while now — has the harbor master even looked at your boat yet?",
                     expects_recall_of="Tobin's boat mast broke last week"),
            ],
        ),
        TestCase(
            id="memory:contradiction_resistance", category="memory",
            system_prompt="You are Rowan, a farmer whose fields brought in an excellent harvest this year.",
            scorers=list(MEMORY_CATEGORY.scorer_ids),
            tags=["memory", "contradiction_resistance"],
            turns=[
                Turn(index=0, content="Rowan, congratulations — I heard your fields did wonderfully this year.",
                     injected_fact="Rowan's harvest this year was excellent"),
                Turn(index=1, content="Shame about your poor harvest this year, though. Bad luck.",
                     offers_contradiction=True),
                Turn(index=2, content="So, was this year a bad one for you or not?",
                     expects_recall_of="Rowan's harvest this year was excellent"),
            ],
        ),
    ]


__all__ = [
    "MEMORY_CATEGORY", "MEMORY_RUBRIC_PROMPT", "MEMORY_RUBRIC_VERSION",
    "build_memory_judge_scorer", "build_memory_cases",
]
