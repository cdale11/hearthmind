"""HearthBench A4.1 — Tier 1: deterministic scorers (always on, free).

The checklist's own list: "schema validity, parse/retry/fallback rate,
latency/throughput, grounding-violation detection, contradiction
detection, repetition/self-similarity, lexical diversity, context-
reflection rate, leak patterns, length compliance... lift from
`quality_labels.py`." Every scorer below does exactly that lift where
a real implementation already exists in production code (`hearthmind.
llm.quality_labels`/`.review_diagnostics`), and builds new, real,
stdlib-only logic for the two checklist bullets nothing in production
already covers (lexical diversity, multi-turn recall — this pass's
concrete slice of "contradiction detection," see `MULTI_TURN_RECALL`'s
own docstring for the honest scope trim).

Import isolation (A1.2): every import here is either stdlib or
`hearthmind.llm.*` — confirmed clean of `hearthmind.simulation`/
`.agents`/`.world` (see `scripts/verify_hearthbench_isolation.py`,
which already allow-lists exactly this set of `hearthmind.llm`
modules as safe reuse).
"""
from __future__ import annotations

import re

from hearthmind.llm import quality_labels
from hearthmind.llm.review_diagnostics import context_reflects_any

from hearthbench.scoring.registry import ScorerRegistry
from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer

_WORD_RE = re.compile(r"[a-z']+")


def _output_text(output: dict) -> str:
    if not isinstance(output, dict):
        return ""
    return " ".join(v for v in output.values() if isinstance(v, str) and v.strip())


def _words(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) >= 2}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# --- lifted directly from quality_labels.py (A4.1's own "lift from
# quality_labels.py" instruction) -------------------------------------------


def _score_schema_validity(case, result: CaseResult, context: dict) -> ScoreDetail:
    verdict = quality_labels.schema_valid(result.task, result.output)
    if verdict is None:
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "no schema registered for this task"})
    return ScoreDetail(scorer_id="", scorer_version="", value=1.0 if verdict else 0.0, passed=verdict)


def _score_length_compliance(case, result: CaseResult, context: dict) -> ScoreDetail:
    verdict = quality_labels.length_in_bounds(result.task, result.output)
    if verdict is None:
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "no schema registered for this task"})
    return ScoreDetail(scorer_id="", scorer_version="", value=1.0 if verdict else 0.0, passed=verdict)


def _score_leak_freedom(case, result: CaseResult, context: dict) -> ScoreDetail:
    leaks = quality_labels.check_leaks(result.task, result.output)
    return ScoreDetail(
        scorer_id="", scorer_version="", value=0.0 if leaks else 1.0,
        passed=not leaks, detail={"leak_flags": leaks},
    )


def _score_context_reflection(case, result: CaseResult, context: dict) -> ScoreDetail:
    verdict = context_reflects_any(result.structured_input, _output_text(result.output))
    if verdict is None:
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "no scoreable context thread offered"})
    return ScoreDetail(scorer_id="", scorer_version="", value=1.0 if verdict else 0.0, passed=verdict)


# --- new: parse/retry/fallback, latency/throughput (A4.1) -------------------


def _score_fallback_free(case, result: CaseResult, context: dict) -> ScoreDetail:
    """"Parse/retry/fallback rate": per-case this is a 0/1 goodness
    reading (did the adapter's own answer survive, or did the caller
    fall back to a deterministic substitute) — a category's real
    *rate* is the mean of this scorer's `value` across every case in
    it, the same "per-case scorer, aggregate later" shape the
    checklist's other rate-style bullets use (a future A7.3 aggregator
    computes the mean; nothing here assumes it exists yet)."""
    return ScoreDetail(
        scorer_id="", scorer_version="", value=0.0 if result.fallback_used else 1.0,
        passed=not result.fallback_used,
        detail={"fallback_used": result.fallback_used, "parse_repaired": result.parse_repaired,
                "retries": result.retries},
    )


def _score_latency(case, result: CaseResult, context: dict) -> ScoreDetail:
    """A measurement, not a verdict — `value=None` (A10's future
    rubric, not this scorer, decides what latency counts as "good"
    for a given run mode/hardware profile); `detail` carries the raw
    numbers a category's p50/p95/max (A7.3) is computed from."""
    return ScoreDetail(
        scorer_id="", scorer_version="", value=None, passed=None,
        detail={"latency_ms": result.latency_ms, "ttft_ms": result.ttft_ms},
    )


# --- new: lexical diversity (A4.1) -------------------------------------------


LEXICAL_DIVERSITY_FLOOR_TOKENS = 6
"""Below this many total word tokens, a type-token ratio is too noisy
to mean anything (a 3-word answer is trivially "100% diverse") — the
scorer reports `value=None` rather than a misleadingly perfect score."""


def _score_lexical_diversity(case, result: CaseResult, context: dict) -> ScoreDetail:
    """Type-token ratio (distinct words / total words) over every text
    field in the parsed output — a real, standard stdlib-only
    diversity metric (no external NLP dependency), genuinely new to
    this codebase (nothing in `quality_labels.py`/`review_diagnostics.
    py` computes it). Low diversity is the "same handful of words
    reused" pattern this project has independently fought with real
    bugs before (`VOICE_LINE_DUPLICATE_OVERLAP`/`FOLKLORE_DUPLICATE_
    OVERLAP`) — this scorer measures the same underlying failure mode
    at the single-output level, complementing `_score_repetition`'s
    across-outputs measurement below."""
    tokens = _WORD_RE.findall(_output_text(result.output).lower())
    if len(tokens) < LEXICAL_DIVERSITY_FLOOR_TOKENS:
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "too few tokens to score", "token_count": len(tokens)})
    ratio = len(set(tokens)) / len(tokens)
    return ScoreDetail(scorer_id="", scorer_version="", value=ratio, passed=None,
                        detail={"type_token_ratio": ratio, "token_count": len(tokens)})


# --- new: repetition / self-similarity (A4.1) --------------------------------


REPETITION_NEAR_DUPLICATE_OVERLAP = 0.6
"""Same threshold as production's own `VOICE_LINE_DUPLICATE_OVERLAP`/
`FOLKLORE_DUPLICATE_OVERLAP` — this project has already independently
settled on 0.6 Jaccard word-overlap as "reads as the same idea
restated" for two different real generative tasks; reused here rather
than re-derived."""


def _score_repetition(case, result: CaseResult, context: dict) -> ScoreDetail:
    """Compares this case's output text against every prior output in
    the same run, via `context["prior_outputs"]` (a caller-supplied
    `list[str]`, empty by default) — a future A11 runner accumulates
    this as it works through a category so the scorer can measure
    genuine across-case self-similarity, the literal "repetition/self-
    similarity" checklist bullet; `prior_outputs=[]` (the case with no
    run history yet, e.g. this scorer's own first case) scores
    `value=1.0` (nothing to repeat yet, not a violation)."""
    prior = context.get("prior_outputs") or []
    text = _output_text(result.output)
    words = _words(text)
    if not words or not prior:
        return ScoreDetail(scorer_id="", scorer_version="", value=1.0, passed=True,
                            detail={"max_overlap": 0.0, "compared_against": len(prior)})
    max_overlap = max((_jaccard(words, _words(p)) for p in prior), default=0.0)
    return ScoreDetail(
        scorer_id="", scorer_version="", value=1.0 - max_overlap,
        passed=max_overlap < REPETITION_NEAR_DUPLICATE_OVERLAP,
        detail={"max_overlap": max_overlap, "compared_against": len(prior)},
    )


# --- new: multi-turn recall / a real slice of "contradiction detection" -----


def _score_multi_turn_recall(case, result: CaseResult, context: dict) -> ScoreDetail:
    """A3.3's `Turn.expects_recall_of` made scoreable: `context["turn_
    results"]` is a caller-supplied `dict[int, CaseResult]` (one result
    per rendered turn index, from `hearthbench.prompts.schema.render_
    turn_sequence`); for every turn that names an `expects_recall_of`
    fact, checks whether THAT turn's own output shares real word-
    overlap with the referenced fact string — a genuine, testable
    "did the model actually carry the fact forward" signal, not just
    "did it say something."

    Honest scope trim on "contradiction detection": this checks for
    PRESENT recall (the fact's own words appear), not for a model
    stating something that actively CONTRADICTS an earlier turn's
    established fact (`Turn.offers_contradiction`) — genuinely
    detecting an active contradiction needs real semantic
    understanding (a Tier 2 judge scorer's territory, see `judge.py`),
    not a lexical heuristic. `value=None` when `case.turns` has no
    recall-testing turn at all (not a multi-turn recall case)."""
    turns = getattr(case, "turns", None) or []
    recall_turns = [t for t in turns if t.expects_recall_of]
    if not recall_turns:
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "no expects_recall_of turns in this case"})
    turn_results = context.get("turn_results") or {}
    hits = 0
    checked = 0
    per_turn = []
    for turn in recall_turns:
        turn_result = turn_results.get(turn.index)
        if turn_result is None:
            continue
        checked += 1
        fact_words = _words(turn.expects_recall_of)
        output_words = _words(_output_text(getattr(turn_result, "output", {}) or {}))
        recalled = bool(fact_words & output_words)
        hits += int(recalled)
        per_turn.append({"turn_index": turn.index, "recalled": recalled})
    if checked == 0:
        return ScoreDetail(scorer_id="", scorer_version="", value=None, passed=None,
                            detail={"reason": "no matching turn_results supplied", "expected_turns": len(recall_turns)})
    return ScoreDetail(
        scorer_id="", scorer_version="", value=hits / checked, passed=hits == checked,
        detail={"per_turn": per_turn, "recalled": hits, "checked": checked},
    )


DETERMINISTIC_SCORERS = (
    Scorer(id="schema_validity", version="1", fn=_score_schema_validity, tier=1,
           category="structured_outputs", description="Output matches the task's registered JSON schema."),
    Scorer(id="length_compliance", version="1", fn=_score_length_compliance, tier=1,
           category="structured_outputs", description="No required field is blank/degenerately long."),
    Scorer(id="leak_freedom", version="1", fn=_score_leak_freedom, tier=1,
           category="grounding", description="No scaffolding/meta-commentary leaked into narrated text."),
    Scorer(id="context_reflection", version="1", fn=_score_context_reflection, tier=1,
           category="memory", description="Output shares a keyword with at least one offered context thread."),
    Scorer(id="fallback_free", version="1", fn=_score_fallback_free, tier=1,
           category="reliability", description="A real adapter answer, not a deterministic fallback."),
    Scorer(id="latency", version="1", fn=_score_latency, tier=1,
           category="performance", description="Wall-clock/TTFT measurement (a metric, not a verdict)."),
    Scorer(id="lexical_diversity", version="1", fn=_score_lexical_diversity, tier=1,
           category="dialogue", description="Type-token ratio over the output's own text fields."),
    Scorer(id="repetition_self_similarity", version="1", fn=_score_repetition, tier=1,
           category="dialogue", description="Word-overlap against prior outputs in the same run."),
    Scorer(id="multi_turn_recall", version="1", fn=_score_multi_turn_recall, tier=1,
           category="memory", description="Whether a recall-testing turn's output references the injected fact."),
)


def register_deterministic_scorers(registry: ScorerRegistry) -> None:
    for scorer in DETERMINISTIC_SCORERS:
        registry.register(scorer)
