"""HearthBench A5.2 — Personality. "Stability across many
conversations, long-term consistency, individual-voice
distinguishability."

Honest scope trim, stated up front rather than glossed over: a single
judge call reads one case's output against a stated personality
profile (`system_prompt`) and scores whether the answer PLAUSIBLY
matches that profile — a real, testable single-case proxy for
"consistency," not literal cross-conversation aggregation (which needs
several real outputs from the SAME character compared to each other,
a future A11 runner's job once it can accumulate results across cases
for one subject — the same "ship the primitive, wire the aggregation
later" discipline this package has already used for `repetition_
self_similarity`'s own `context["prior_outputs"]` design).
"Individual-voice distinguishability" is judged the same way, one
case at a time, by asking whether the line could plausibly have been
said by a DIFFERENT stated personality — never by literally comparing
two agents' outputs against each other in this pass.

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.judge import JudgeScorer
from hearthbench.scoring.types import Scorer
from hearthbench.tests.category import Category

PERSONALITY_CATEGORY = Category(
    id="personality", name="Personality", weight=10.0,
    scorer_ids=("judge_personality_quality", "leak_freedom"),
    description="Stability across conversations, long-term consistency, individual-voice distinguishability.",
)

PERSONALITY_RUBRIC_VERSION = "1"

PERSONALITY_RUBRIC_PROMPT = """You are scoring one line of in-character dialogue from a life \
simulation game for how well it holds to a STATED personality profile. \
Judge ONLY what is asked; do not reward length or flowery language.

Rubric (score the OUTPUT on each axis, 1=worst, 5=best):
1. Voice consistency: does the line's tone/word choice plausibly match \
the stated personality profile, rather than reading as a generic
narrator voice?
2. Distinctiveness: would this line read as OUT OF CHARACTER if a \
person with a clearly different stated personality said it instead?
3. Trait plausibility: does the line express the stated traits through \
what is said and how, rather than by naming the trait outright \
("I am blunt and impatient" is a score-1 answer on this axis; a line \
that simply IS blunt and impatient is a score-5 answer)?

Anchors:
- Score 1 voice-consistency example: a stated profile of "blunt,
impatient" paired with an output that hedges at length and never gets
to the point.
- Score 5 voice-consistency example: a stated profile of "blunt,
impatient" paired with a short, direct answer with no hedging.
- Score 1 trait-plausibility example: "I am known for being gentle and
patient with everyone I meet." (states the trait, doesn't perform it)
- Score 5 trait-plausibility example: a visibly patient, gentle
response to someone's frustration, with the trait never named outright.

Stated personality profile (from the case's own system prompt):
{context}

Output being judged:
{output_text}

Respond with ONLY a JSON object of this exact shape, no other text:
{{"voice_consistency": <1-5 int>, "distinctiveness": <1-5 int>, "trait_plausibility": <1-5 int>, "reason": "<one short sentence>"}}
"""

_PERSONALITY_AXES = ("voice_consistency", "distinctiveness", "trait_plausibility")


def build_personality_judge_scorer(adapter) -> Scorer:
    """`adapter` is any A2-shaped `ModelAdapter` (duck-typed)."""
    judge = JudgeScorer(
        adapter, rubric_prompt=PERSONALITY_RUBRIC_PROMPT, axes=_PERSONALITY_AXES,
        rubric_version=PERSONALITY_RUBRIC_VERSION,
    )
    return judge.as_scorer(
        scorer_id="judge_personality_quality", category="personality",
        description="LLM-judge rating of voice consistency/distinctiveness/trait plausibility against a stated personality profile.",
    )


def build_personality_cases() -> list:
    """Two real cases with deliberately opposite stated profiles — not
    a cross-comparison mechanism (see the module docstring's scope
    trim), but real, distinct grounding for the judge to hold each
    output against on its own."""
    return [
        TestCase(
            id="personality:blunt_impatient", category="personality",
            system_prompt=(
                "You are Mira, a blacksmith known throughout the village for being blunt, "
                "impatient, and fiercely loyal to her own family — she has openly criticized "
                "the council to their faces before and does not soften her words for anyone."
            ),
            scorers=list(PERSONALITY_CATEGORY.scorer_ids),
            tags=["personality", "voice_consistency"],
            turns=[Turn(index=0, content="Mira, what do you think of the council's new grain tax?")],
        ),
        TestCase(
            id="personality:gentle_patient", category="personality",
            system_prompt=(
                "You are Aldric, the village's eldest healer — soft-spoken, endlessly patient, "
                "and known for taking his time with anyone who comes to him afraid or in pain."
            ),
            scorers=list(PERSONALITY_CATEGORY.scorer_ids),
            tags=["personality", "voice_consistency"],
            turns=[Turn(index=0, content="Aldric, a child in the square is terrified of the wound on her arm.")],
        ),
    ]


__all__ = [
    "PERSONALITY_CATEGORY", "PERSONALITY_RUBRIC_PROMPT", "PERSONALITY_RUBRIC_VERSION",
    "build_personality_judge_scorer", "build_personality_cases",
]
