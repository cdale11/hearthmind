"""Tier 6 Phase 1's last named item, continued: `llm/laws.py`'s "which
hardship becomes a law" (docs/ROADMAP-2026-07-REMAINING.md) -- flagged
and deliberately excluded from `hearthmind.ml.decision_policy`'s four
sites, since it "chooses among a DYNAMIC, per-call candidate set
(whichever hardship categories are currently pressured), not a fixed
closed class... a genuinely different (ranking/scoring) problem
shape."

This module is that different shape -- the same L2.3 `RetrievalScorer`
pattern (`hearthmind/ml/retrieval_scorer.py`: a single scalar sigmoid
score over GENERIC features, never a softmax over named classes),
applied here to "how likely is THIS specific pressured hardship, right
now, to actually crystallize into a law/custom/taboo if the LLM is
asked about it." Because the score never sees the candidate's own NAME
as a feature -- only the generic occurrence/confidence signals every
one of `_maybe_schedule_laws`'s candidates already carries -- it
applies unmodified to any of today's 14 named `pattern_key`s, and to
any future one Tier 0 adds tomorrow, with no schema change and no
retrain-from-scratch. That genericity is exactly what a fixed-class
`DecisionPolicy` structurally cannot offer here.

**What this does NOT do, deliberately.** `llm/laws.py`'s own module
docstring is explicit: "Nothing predefined and nothing guaranteed: the
fallback is a genuine no-op, never an invented norm." A law/custom/
taboo's actual TEXT is free prose only the LLM may author -- no
learned model anywhere in this module ever proposes, gates, or
fabricates one, and `llm.laws.fallback_laws()` stays untouched (still
the same honest "not yet" no-op on every skipped/backpressured/failed
call). This module's score never touches `forms`/`kind`/`text` at
all -- its only real job is informing WHICH already-eligible candidate
(Body-gated by real `occurrences >= LAW_SIGNAL_THRESHOLD`, or a real
standing `village_pillar` conviction -- both unchanged) gets spent on
this month's real LLM call. A genuine third-level tiebreak after the
real occurrence count (primary, always dominant -- Body stays
authoritative) and `village_pillar.subject_confidence` (secondary,
unchanged) -- same "a lean only breaks a genuine tie, the real signal
is never overridden" discipline every Tier 0 site already holds.

Label: the real recorded `forms` outcome (True/False) for a `laws`
task example's own `layer1_structured_input`/`layer4_parsed_output`
pair -- a genuine, non-fabricated supervised signal (did asking about
a candidate shaped like THIS actually result in a law forming),
filtered to `fallback_used=False` exactly like every other Tier 6
trainer. Not available in this offline environment -- same "ship the
substrate, wire it once a real archive exists" discipline every prior
Tier 6 item has shipped under; see `scripts/train_law_scorer_from_
archive.py`.
"""
from __future__ import annotations

import json

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import LearnResult, LearningSpecialist
from hearthmind.ml.training import TrainingExample

LAW_SCORER_SCHEMA_VERSION = 1

LAW_OCCURRENCE_SCALE = 20.0
"""Same un-normalized-large-count divergence class already fixed once
for `simulation/forecasting.py`'s `WorkloadForecaster` (`WORKLOAD_
FEATURE_SCALE`, v1.34.257) -- a real settlement's own `occurrences`
count for a long-unaddressed hardship can run into the hundreds (HCA's
own worked example: "family lines dying out, 590 occurrences, no
rule"), and `MLP.random_init`'s near-unit-scale weight init needs its
inputs scaled down to roughly match, not fed raw."""

LAW_OCCURRENCE_CAP = 5.0
"""A further hard cap on top of the scale above -- a genuinely
100+-occurrence hardship should read as "very pressured," not as a
number ten-plus times larger than a 20-occurrence one; capping keeps
the network's real input range bounded regardless of how extreme a
real settlement's history gets."""

LAW_SCORER_SCHEMA = FeatureSchema(
    numeric_fields=["occurrences_scaled", "pillar_confidence", "initiated_by_conviction"],
)
"""Deliberately generic -- no candidate NAME (no `pattern_key` one-hot)
anywhere in this schema, which is the whole point of this module: the
same trained scorer applies to a `pattern_key` it has never seen
before, as long as that candidate's own occurrence count and `village_
pillar.subject_confidence` are supplied the same way every other
candidate's already are at the real call site."""


def encode_candidate(occurrences: int, pillar_confidence: float, initiated_by_conviction: bool = False) -> list:
    occurrences_scaled = min(occurrences / LAW_OCCURRENCE_SCALE, LAW_OCCURRENCE_CAP)
    values = {
        "occurrences_scaled": occurrences_scaled,
        "pillar_confidence": pillar_confidence,
        "initiated_by_conviction": 1.0 if initiated_by_conviction else 0.0,
    }
    return FeatureEncoder(LAW_SCORER_SCHEMA).encode(values)


def build_law_scorer_model(hidden_dims: tuple = (6,), seed: int = 0) -> MLP:
    dims = [LAW_SCORER_SCHEMA.dim()] + list(hidden_dims) + [1]
    return MLP.random_init(dims, output_activation="sigmoid", seed=seed)


class LawCandidateScorer:
    """Wraps a `LearningSpecialist` over the scalar sigmoid model above.
    `score()`/`rank()` are the real inference path; `learn()` is a
    one-phase training entry point (same shape as `RetrievalScorer`'s
    own -- L2.3-style, no two-phase distillation/reweight curriculum,
    since a real recorded `forms` outcome is already a genuine 0/1
    label, not a noisy teacher choice needing `GoalPolicy`-style
    outcome-reweighting)."""

    def __init__(self, specialist: "LearningSpecialist | None" = None, seed: int = 0) -> None:
        self.specialist = specialist or LearningSpecialist(build_law_scorer_model(seed=seed))

    def score(self, occurrences: int, pillar_confidence: float, initiated_by_conviction: bool = False) -> float:
        x = encode_candidate(occurrences, pillar_confidence, initiated_by_conviction)
        return self.specialist.predict(x)[0]

    def rank(self, candidates: list) -> list:
        """`candidates` is a list of `(pattern_key, occurrences,
        pillar_confidence, initiated_by_conviction)` tuples -- returns
        just the `pattern_key`s, highest-scored first (ties broken by
        the tuple's own original order, `sort`'s stability). Never
        called with anything Body hasn't already deemed eligible --
        `_maybe_schedule_laws` filters to real occurrence-gated
        candidates before this is ever consulted, so this only orders
        among the already-eligible, never manufactures eligibility."""
        scored = list(enumerate(
            self.score(occ, conf, conv) for _, occ, conf, conv in candidates
        ))
        keys = [key for key, _, _, _ in candidates]
        scored.sort(key=lambda t: (-t[1], t[0]))
        return [keys[i] for i, _ in scored]

    def learn(self, examples: list, holdout_examples: list, tick: int, **kwargs) -> LearnResult:
        return self.specialist.learn(examples, holdout_examples, tick, **kwargs)

    def to_dict(self) -> dict:
        return {
            "schema_version": LAW_SCORER_SCHEMA_VERSION,
            "kind": "law_scorer",
            "model": self.specialist.model.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LawCandidateScorer":
        if d.get("schema_version") != LAW_SCORER_SCHEMA_VERSION:
            raise ValueError(f"unsupported law_scorer schema_version={d.get('schema_version')!r}")
        if d.get("kind") != "law_scorer":
            raise ValueError(f"weights file is for {d.get('kind')!r}, not 'law_scorer'")
        model = MLP.from_dict(d["model"])
        return cls(specialist=LearningSpecialist(model))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "LawCandidateScorer":
        with open(path) as f:
            return cls.from_dict(json.load(f))


def build_training_examples(candidate_features: list, forms_labels: list) -> list:
    """One `TrainingExample` per real recorded `(occurrences, pillar_
    confidence, initiated_by_conviction)` state and its real `forms`
    outcome -- `forms_labels` is the REAL recorded result from a
    `laws` task's own `layer4_parsed_output["forms"]`, never
    fabricated and never this scorer's own prior output fed back in
    (the same anti-self-reinforcement guard every Tier 6 trainer
    already holds)."""
    examples = []
    for (occ, conf, conv), label in zip(candidate_features, forms_labels):
        x = encode_candidate(occ, conf, conv)
        examples.append(TrainingExample(x=x, y=[1.0 if label else 0.0]))
    return examples
