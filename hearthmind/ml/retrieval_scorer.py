"""L2.3 -- semantic retrieval scorer (docs/ML-ARCHITECTURE-2026-08-01.md,
gated on L1.1). Replaces `cognition/activation.py`'s hand-tuned
`ACTIVATION_SALIENCE_GAIN`/`ACTIVATION_RELEVANCE_GAIN`/`ACTIVATION_
CAUSAL_GAIN` spreading-activation weights with one learned scorer over
the SAME four real inputs (base-level recency+frequency, salience,
relevance, causal-tag presence) -- merging the architecture doc's
"M3-consumer + M4" into one model rather than two.

**Correction, recorded in docs/ROADMAP-2026-07-REMAINING.md**: the
architecture doc's own text cites `agents/agent.py:472-474`'s hand-set
weights as what this replaces -- those no longer exist there (Tier 7
HCA's D1 superseded them with the real ACT-R equation in `cognition/
activation.py` before this item was ever scoped). This module targets
`activation.py`'s real gains, the correct current site.

Label: "did the retrieved memory demonstrably influence the resulting
output?" -- a real supervised signal, available only from a live
recorder archive correlating a `retrieve_relevant_memories` call's
candidate set against whether the eventual LLM output actually
referenced/was shaped by a given memory (same class of signal L2.2
needs from `layer1_structured_input`/`layer4_parsed_output` pairs).
Not available in this offline environment -- same "ship the
substrate, wire it once a real archive exists" discipline every prior
Tier 6 L-layer piece has shipped under.

`retrieve_relevant_memories`'s own k-slot prompt BUDGET is untouched
by this module -- it only proposes a different per-memory score to
rank by, never a different k.
"""
from __future__ import annotations

from hearthmind.cognition.activation import base_level_activation
from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import LearningSpecialist, LearnResult
from hearthmind.ml.training import TrainingExample

RETRIEVAL_SCHEMA = FeatureSchema(
    numeric_fields=["base_level_activation", "salience", "relevance", "causal_present"],
)
"""The SAME four real inputs `cognition/activation.py`'s hand-tuned
formula already combines -- this module doesn't invent a fifth
signal, it learns a better combination of the four that already
exist. `base_level_activation` is pre-computed by the caller (via
`hearthmind.cognition.activation.base_level_activation`) rather than
re-derived here, so this module never needs `presentation_ticks`/
`current_tick` in its own schema."""


def build_retrieval_model(hidden_dims: tuple = (8,), seed: int = 0) -> MLP:
    dims = [RETRIEVAL_SCHEMA.dim()] + list(hidden_dims) + [1]
    return MLP.random_init(dims, output_activation="sigmoid", seed=seed)


def encode_candidate(
    presentation_ticks: list, current_tick: int, salience: float,
    relevance: float, causal_present: bool,
) -> list:
    """The one real place a raw memory-retrieval candidate becomes a
    feature vector -- reuses `activation.py`'s own base-level term
    directly rather than re-deriving recency math a second time."""
    values = {
        "base_level_activation": base_level_activation(presentation_ticks, current_tick),
        "salience": salience,
        "relevance": relevance,
        "causal_present": 1.0 if causal_present else 0.0,
    }
    return FeatureEncoder(RETRIEVAL_SCHEMA).encode(values)


class RetrievalScorer:
    """Wraps a `LearningSpecialist` over the real four-input sigmoid
    model. `score()` is the real inference path; `learn()` is Phase 1's
    (and only phase's -- L2.3 has no stated two-phase curriculum,
    unlike L2.2) training entry point."""

    def __init__(self, specialist: LearningSpecialist | None = None, seed: int = 0) -> None:
        self.specialist = specialist or LearningSpecialist(build_retrieval_model(seed=seed))

    def score(
        self, presentation_ticks: list, current_tick: int, salience: float,
        relevance: float, causal_present: bool,
    ) -> float:
        x = encode_candidate(presentation_ticks, current_tick, salience, relevance, causal_present)
        return self.specialist.predict(x)[0]

    def rank(self, candidates: list, k: int) -> list:
        """`candidates` is a list of `(presentation_ticks, current_tick,
        salience, relevance, causal_present, original_index)` tuples --
        returns the top-`k` `original_index` values, highest score
        first. The one real function that would replace `cognition/
        activation.py`'s combined sort key at `retrieve_relevant_
        memories`'s call site once this model is trained and wired."""
        scored = [
            (self.score(pt, ct, sal, rel, cp), idx)
            for pt, ct, sal, rel, cp, idx in candidates
        ]
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [idx for _, idx in scored[:k]]

    def learn(self, examples: list, holdout_examples: list, tick: int, **kwargs) -> LearnResult:
        return self.specialist.learn(examples, holdout_examples, tick, **kwargs)


def build_training_examples(candidate_features: list, influenced_labels: list) -> list:
    """One `TrainingExample` per real `(candidate, label)` pair.
    `candidate_features` is the same tuple shape `RetrievalScorer.
    rank`'s `candidates` uses (minus `original_index`); `influenced_
    labels` is the real, externally-measured "did this memory
    demonstrably influence the output" signal in `[0, 1]` -- never
    fabricated, never this scorer's own prior output fed back in."""
    examples = []
    for (pt, ct, sal, rel, cp), label in zip(candidate_features, influenced_labels):
        x = encode_candidate(pt, ct, sal, rel, cp)
        examples.append(TrainingExample(x=x, y=[float(label)]))
    return examples
