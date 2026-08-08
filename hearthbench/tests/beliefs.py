"""HearthBench A5.4 — Beliefs. "Formation from evidence, revision when
evidence flips, theory quality, confidence calibration."

The deliberate mirror-image of `memory.py`'s `contradiction_
resistance` case: Memory tests HOLDING to an established true fact
against a false, unsupported contradiction (the character should NOT
update). Beliefs tests the opposite direction — when genuinely NEW
evidence arrives (not a bare contradictory claim, but a fact the case
itself establishes as real), a well-formed belief SHOULD revise. Both
reuse the same `Turn.offers_contradiction`/`expects_recall_of`
machinery; which behavior counts as "correct" is what differs, and
that's exactly what a judge call (not a lexical scorer) is for — this
is why `judge_beliefs_quality` carries the actual verdict here, with
`multi_turn_recall` only checking that the NEW evidence's own words
were at least referenced, not that revision itself was correct.

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.judge import JudgeScorer
from hearthbench.scoring.types import Scorer
from hearthbench.tests.category import Category

BELIEFS_CATEGORY = Category(
    id="beliefs", name="Beliefs", weight=12.0,
    scorer_ids=("judge_beliefs_quality", "multi_turn_recall", "leak_freedom"),
    description="Formation from evidence, revision when evidence flips, theory quality, confidence calibration.",
)

BELIEFS_RUBRIC_VERSION = "1"

BELIEFS_RUBRIC_PROMPT = """You are scoring one line of in-character dialogue from a life \
simulation game for how well the character forms and revises BELIEFS \
(theories about why something is happening, not simple facts). Judge \
ONLY what is asked; do not reward length.

Rubric (score the OUTPUT on each axis, 1=worst, 5=best):
1. Evidence grounding: is the stated belief/theory actually supported \
by the evidence given in the conversation, rather than asserted from \
nowhere?
2. Revision quality: when new evidence in the conversation genuinely \
conflicts with an earlier belief, does the character update their \
theory in a way that responds to the NEW evidence specifically (not \
just vaguely acknowledging confusion, and not stubbornly repeating the \
old theory unchanged)?
3. Confidence calibration: does the character's stated certainty match \
how much evidence actually supports the claim (overclaiming certainty \
from thin evidence, or hedging on something well-established, are both \
score-1 answers on this axis)?

Anchors:
- Score 1 evidence-grounding example: a confident theory about why \
something happened with no reference to any of the evidence actually \
given.
- Score 5 evidence-grounding example: a theory that visibly reasons \
from the specific evidence stated in the conversation.
- Score 1 revision-quality example: new evidence directly undermines an \
earlier theory, and the character repeats the old theory verbatim, \
unchanged.
- Score 5 revision-quality example: the character explicitly updates \
their theory in light of the new evidence.

Conversation context so far (established facts/evidence):
{context}

Output being judged:
{output_text}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"evidence_grounding": <1-5 int>, "revision_quality": <1-5 int>, "confidence_calibration": <1-5 int>, "reason": "<one short sentence>"}}
"""

_BELIEFS_AXES = ("evidence_grounding", "revision_quality", "confidence_calibration")


def build_beliefs_judge_scorer(adapter) -> Scorer:
    """`adapter` is any A2-shaped `ModelAdapter` (duck-typed)."""
    judge = JudgeScorer(
        adapter, rubric_prompt=BELIEFS_RUBRIC_PROMPT, axes=_BELIEFS_AXES,
        rubric_version=BELIEFS_RUBRIC_VERSION,
    )
    return judge.as_scorer(
        scorer_id="judge_beliefs_quality", category="beliefs",
        description="LLM-judge rating of evidence grounding/revision quality/confidence calibration for a stated theory.",
    )


def build_beliefs_cases() -> list:
    """Two real multi-turn cases: formation-from-evidence, and
    revision-when-evidence-flips (the deliberate inverse of `memory.
    build_memory_cases`'s contradiction-resistance case)."""
    return [
        TestCase(
            id="beliefs:formation_from_evidence", category="beliefs",
            system_prompt="You are Yara, the village elder, known for reasoning carefully before speaking.",
            scorers=list(BELIEFS_CATEGORY.scorer_ids),
            tags=["beliefs", "formation"],
            turns=[
                Turn(index=0, content="Yara, the well has run dry three times this month, and it never used to.",
                     injected_fact="the well has run dry three times this month"),
                Turn(index=1, content="What do you make of it, Yara? Why do you think the well keeps failing?"),
            ],
        ),
        TestCase(
            id="beliefs:revision_on_new_evidence", category="beliefs",
            system_prompt="You are Yara, the village elder, who earlier theorized the well was failing from overuse.",
            scorers=list(BELIEFS_CATEGORY.scorer_ids),
            tags=["beliefs", "revision"],
            turns=[
                Turn(index=0, content="Yara, you said before you thought the well was failing because too many households draw from it.",
                     injected_fact="Yara believed the well was failing from overuse"),
                Turn(index=1, content="The surveyor just found a crack running clean through the old well shaft, Yara — it's been leaking into the ground for months.",
                     injected_fact="the surveyor found a crack in the well shaft leaking into the ground",
                     offers_contradiction=True),
                Turn(index=2, content="Given what the surveyor found, do you still think it's overuse, Yara?",
                     expects_recall_of="the surveyor found a crack in the well shaft leaking into the ground"),
            ],
        ),
    ]


__all__ = [
    "BELIEFS_CATEGORY", "BELIEFS_RUBRIC_PROMPT", "BELIEFS_RUBRIC_VERSION",
    "build_beliefs_judge_scorer", "build_beliefs_cases",
]
