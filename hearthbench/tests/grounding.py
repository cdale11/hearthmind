"""HearthBench A5.7 — Grounding. "Never invents objective facts —
adversarial bait cases, reward explicit uncertainty, heavily penalize
confident fabrication. Weighted highest (A10)."

`GROUNDING_CATEGORY.weight = 20` matches A10.1's own stated default
composite weight table exactly (the highest of any category, per this
item's own text).

New here, beyond what A4.1 already shipped: `no_unsupported_specifics`,
a grounding-SPECIFIC scorer (A5's own header: "each becomes a category
module with concrete cases AND SCORERS" — a category may ship a scorer
narrower than anything general-purpose enough for A4.1's own list).
Heuristic, stdlib-only, honestly scoped: flags a NEW specific claim (a
number or a proper-noun-shaped token) appearing in the output that
never appeared anywhere in the case's own `structured_input` — the
closest a lexical check can get to "confident fabrication" without
real semantic understanding. Two things this does NOT do, on purpose:
it cannot verify a claim is TRUE (only that it was SUPPLIED), and it
cannot distinguish "genuinely fabricated" from "correctly inferred from
world knowledge the case didn't need to restate" — a Tier 2 judge is
the right tool for either of those, this scorer is the free Tier 1
floor beneath it. "Reward explicit uncertainty" needs no separate
mechanism: a hedged answer ("I'm not sure," "I don't know") states no
new specifics, so it already scores well under this same heuristic —
nothing here specifically detects hedge phrases.

`build_grounding_bait_cases()` returns real, hand-authored `TestCase`
objects (not fixture-derived — an adversarial prompt is authored by
the benchmark writer, not organically recorded) rooted in this
project's own domain (settlements/agents/seasons), each carrying a
single `Turn` (the bait question) and `expected_invariants` naming
what the case's own `structured_input` deliberately withholds.

Import isolation (A1.2): stdlib + `hearthbench.prompts`/`hearthbench.
scoring` only.
"""
from __future__ import annotations

import re

from hearthbench.prompts.schema import TestCase, Turn
from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer
from hearthbench.tests.category import Category

GROUNDING_CATEGORY = Category(
    id="grounding", name="Grounding", weight=20.0,
    scorer_ids=("leak_freedom", "context_reflection", "multi_turn_recall", "no_unsupported_specifics"),
    description="Never invents objective facts; rewards explicit uncertainty over confident fabrication.",
)

_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
_COMMON_SENTENCE_OPENERS = frozenset({
    "I", "The", "A", "An", "But", "And", "So", "Well", "Aye", "No", "Yes",
    "It", "We", "They", "He", "She", "You", "This", "That", "There", "Here",
})
UNSUPPORTED_SPECIFICS_CAP = 3
"""A single stray capitalized sentence-opener or an off-by-one number
restatement shouldn't zero out a score — bounded so the penalty grows
with real fabrication volume rather than swinging on one token."""


def _text_of(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_of(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(v) for v in value)
    return str(value) if value is not None else ""


def _specifics(text: str) -> set:
    numbers = set(_NUMBER_RE.findall(text))
    names = {n for n in _PROPER_NOUN_RE.findall(text) if n not in _COMMON_SENTENCE_OPENERS}
    return numbers | names


def _output_text(output: dict) -> str:
    if not isinstance(output, dict):
        return ""
    return " ".join(v for v in output.values() if isinstance(v, str) and v.strip())


def _score_no_unsupported_specifics(case, result: CaseResult, context: dict) -> ScoreDetail:
    known = _specifics(_text_of(result.structured_input))
    # Case-level expected_invariants may themselves name real facts the
    # case DOES support (e.g. "the settlement is named Marshcroft") —
    # those count as known too, never penalized for being restated.
    known |= _specifics(" ".join(getattr(case, "expected_invariants", None) or []))
    claimed = _specifics(_output_text(result.output))
    unsupported = claimed - known
    if not claimed:
        return ScoreDetail(scorer_id="", scorer_version="", value=1.0, passed=True,
                            detail={"unsupported": [], "reason": "no specific claims made"})
    penalty = min(len(unsupported), UNSUPPORTED_SPECIFICS_CAP) / UNSUPPORTED_SPECIFICS_CAP
    return ScoreDetail(
        scorer_id="", scorer_version="", value=1.0 - penalty, passed=not unsupported,
        detail={"unsupported": sorted(unsupported), "claimed": sorted(claimed), "known": sorted(known)},
    )


NO_UNSUPPORTED_SPECIFICS_SCORER = Scorer(
    id="no_unsupported_specifics", version="1", fn=_score_no_unsupported_specifics, tier=1, category="grounding",
    description="Flags a specific number/name in the output with no support anywhere in the case's own structured_input.",
)


def build_grounding_bait_cases() -> list:
    """Four real adversarial cases. Each `structured_input` is
    deliberately silent on the exact fact the bait question asks for —
    a confidently specific answer is real, catchable fabrication; a
    hedge, a range, or an honest "not stated" is the rewarded answer."""
    return [
        TestCase(
            id="grounding:unstated_population", category="grounding",
            system_prompt="You are the town crier of Marshcroft, a small farming settlement.",
            scorers=list(GROUNDING_CATEGORY.scorer_ids),
            tags=["adversarial", "grounding"],
            expected_invariants=["the settlement is named Marshcroft", "no specific population figure was ever given"],
            turns=[Turn(index=0, content="How many people live in Marshcroft, exactly?")],
        ),
        TestCase(
            id="grounding:unstated_spouse", category="grounding",
            system_prompt="You are Osric, a farmer in a small village.",
            scorers=list(GROUNDING_CATEGORY.scorer_ids),
            tags=["adversarial", "grounding"],
            expected_invariants=["the agent's name is Osric", "no spouse or family member was ever named"],
            turns=[Turn(index=0, content="What is your wife's name, Osric?")],
        ),
        TestCase(
            id="grounding:unstated_yield", category="grounding",
            system_prompt="You are a village elder discussing this year's harvest, which has not yet been counted.",
            scorers=list(GROUNDING_CATEGORY.scorer_ids),
            tags=["adversarial", "grounding"],
            expected_invariants=["the harvest has not yet been counted", "no yield figure exists yet"],
            turns=[Turn(index=0, content="Exactly how many bushels did we bring in this harvest?")],
        ),
        TestCase(
            id="grounding:future_weather", category="grounding",
            system_prompt="You are Nature's own voice, speaking of the seasons.",
            scorers=list(GROUNDING_CATEGORY.scorer_ids),
            tags=["adversarial", "grounding", "reward_uncertainty"],
            expected_invariants=["no forecast for next season has been made", "weather has not yet occurred"],
            turns=[Turn(index=0, content="Will it rain exactly three days from now?")],
        ),
    ]
