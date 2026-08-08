"""HearthBench A5.1 — Dialogue. "Naturalness, coherence, personality
expression, emotional realism, incl. an 'ambient filler' penalty for
aphorism ping-pong/mutual-agreement patterns."

`DIALOGUE_CATEGORY.weight = 15` matches A10.1's own stated default
composite weight table exactly. This is the category `hearthbench.
scoring.judge.JUDGE_RUBRIC_PROMPT`'s own default rubric was ALREADY
written for — `build_dialogue_judge_scorer()` constructs a
`JudgeScorer` with NO custom rubric/axes, reusing the shipped A4.2
default byte-for-byte, per that module's own "A5.1 is exactly what
this class's own default rubric already scores" note.

New here: `no_ambient_filler`, a Tier-1 deterministic scorer for the
one checklist bullet no judge call is needed for — a closed,
hand-authored vocabulary of the exact generic-agreement/aphorism
phrases this project's own dialogue system has independently fought
before (`VOICE_LINE_DUPLICATE_OVERLAP`/`FOLKLORE_DUPLICATE_OVERLAP`
catch verbatim-repeated lines; this catches a different, related
failure — two lines that are NEVER identical but both reduce to empty
"aye, wise words"/"true enough" agreement with no actual content).
Same bounded-penalty shape as grounding's `no_unsupported_specifics`:
a single filler phrase doesn't zero out a score, repeated reliance on
the pattern does.

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring`/`hearthbench.tests.category` only.
"""
from __future__ import annotations

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.judge import JudgeScorer
from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer
from hearthbench.tests.category import Category

DIALOGUE_CATEGORY = Category(
    id="dialogue", name="Dialogue", weight=15.0,
    scorer_ids=("judge_dialogue_quality", "lexical_diversity", "repetition_self_similarity",
                "no_ambient_filler", "leak_freedom"),
    description="Naturalness, coherence, personality expression, emotional realism; penalizes ambient-filler agreement patterns.",
)

_AMBIENT_FILLER_PHRASES = frozenset({
    "wise words", "well said", "true enough", "aye, that's true", "you speak the truth",
    "can't argue with that", "so it goes", "such is life", "that's just how it goes",
    "indeed it is", "you're not wrong", "fair point", "no argument there", "that's for sure",
    "ain't that the truth", "as you say", "who's to say", "such is the way of things",
})
AMBIENT_FILLER_CAP = 2
"""A single stock phrase in an otherwise substantive line is normal
speech, not the failure mode this scorer exists to catch — the penalty
only grows once a line leans on the pattern repeatedly, same bounded-
growth shape as `grounding.UNSUPPORTED_SPECIFICS_CAP`."""


def _output_text(output: dict) -> str:
    if not isinstance(output, dict):
        return ""
    return " ".join(v for v in output.values() if isinstance(v, str) and v.strip())


def _score_no_ambient_filler(case, result: CaseResult, context: dict) -> ScoreDetail:
    text = _output_text(result.output).lower()
    if not text.strip():
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "no output text to score"})
    hits = sorted(phrase for phrase in _AMBIENT_FILLER_PHRASES if phrase in text)
    if not hits:
        return ScoreDetail(scorer_id="", scorer_version="", value=1.0, passed=True,
                            detail={"filler_phrases": []})
    penalty = min(len(hits), AMBIENT_FILLER_CAP) / AMBIENT_FILLER_CAP
    return ScoreDetail(scorer_id="", scorer_version="", value=1.0 - penalty, passed=False,
                        detail={"filler_phrases": hits})


NO_AMBIENT_FILLER_SCORER = Scorer(
    id="no_ambient_filler", version="1", fn=_score_no_ambient_filler, tier=1, category="dialogue",
    description="Flags reliance on generic aphorism/mutual-agreement filler phrases instead of substantive content.",
)

def build_dialogue_judge_scorer(adapter) -> Scorer:
    """`adapter` is any A2-shaped `ModelAdapter` (duck-typed, per
    `JudgeScorer`'s own contract). No custom rubric/axes — Dialogue
    reuses `JudgeScorer`'s shipped default exactly, so this is a thin,
    honest wiring function, not a redefinition."""
    return JudgeScorer(adapter).as_scorer(scorer_id="judge_dialogue_quality", category="dialogue")


def build_dialogue_cases() -> list:
    """Two real hand-authored single-turn cases, each grounded in this
    project's own domain, each with a system prompt establishing a
    distinct voice the judge/lexical scorers can hold the output
    against."""
    return [
        TestCase(
            id="dialogue:grief_exchange", category="dialogue",
            system_prompt=(
                "You are Elowen, a weaver in a small village. Your younger brother died of fever "
                "two winters ago. You are speaking with a neighbor who just lost a family member "
                "the same way."
            ),
            scorers=list(DIALOGUE_CATEGORY.scorer_ids),
            tags=["dialogue", "emotional_realism"],
            turns=[Turn(index=0, content="I don't know how you bore it, Elowen. The grief is unbearable.")],
        ),
        TestCase(
            id="dialogue:harvest_boast", category="dialogue",
            system_prompt=(
                "You are Corwin, a proud and boastful farmer who just brought in the best harvest "
                "of his life. You are talking to Bram, a rival farmer whose crop failed this year."
            ),
            scorers=list(DIALOGUE_CATEGORY.scorer_ids),
            tags=["dialogue", "personality_expression"],
            turns=[Turn(index=0, content="So, Bram. How did your fields fare this season?")],
        ),
    ]


__all__ = [
    "DIALOGUE_CATEGORY", "NO_AMBIENT_FILLER_SCORER", "AMBIENT_FILLER_CAP",
    "build_dialogue_judge_scorer", "build_dialogue_cases",
]
