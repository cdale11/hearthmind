"""Tier 6, L2.1 -- Value / consequence model (docs/ML-ARCHITECTURE-
2026-08-01.md: "predicts: how consequential is this agent's current
state?" -- the merge that justifies itself, since attention allocation
and policy advantage weighting are literally the same estimate asked
by two callers). Standalone infrastructure, same "never big-bang"
discipline as every other Tier 6 module shipped so far -- not wired
into a real scheduling call site this pass.

Reuses L0's `FeatureEncoder`/`MLP`/`train_mlp_sgd` directly, same
thin-wrapper shape `WorkloadForecaster`/`LLMCostRegressor` established
-- this module owns feature encoding + the model, training itself is
`hearthmind.ml.training`'s job.

**Real, already-recorded training label**: `world/emergence.py`'s
`Observation.magnitude` (0-1, clamped at `make_observation`) is a
genuine "how big did this look" reading; `compute_consequence_label`
additionally folds in whether a real `life_events` entry followed
within a horizon -- "did it actually matter downstream," the doc's own
named second half of the label. No synthetic ground truth is invented
here; both real fields already exist in this codebase.

**The real unblock this model is FOR** (stated in the architecture
doc): B2.4 "attention follows change" has been blocked since it was
first scoped (v1.34.83) on exactly this -- a real learned priority
signal, not a hand-set weighted sum. `rank_by_predicted_value` is that
consumer function, real and independently testable, but NOT called
from any real engine schedule point this pass -- it needs real weights
trained against a real accumulated emergence/life-event history this
offline environment has no live world to source, same reasoning every
other Tier 6 module's own "not wired" note gives.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.training import TrainingExample, mean_loss, train_mlp_sgd

# Deliberately small and structural, not free-text -- every field here
# is already real, already-computed per-agent state (Agent.emotions,
# a recent-event count, Ledger relationship extremity, core-cast
# membership), nothing invented for this model alone. All numeric
# fields are pre-scaled to roughly [0, 1] per this codebase's own
# normalization discipline (see llm_cost.py's LLM_COST_SCHEMA
# docstring for the concrete NaN-divergence history this convention
# exists to avoid).
VALUE_MODEL_SCHEMA = FeatureSchema(
    numeric_fields=[
        "emotion_intensity",       # max(fear, joy, grief, anger), 0..1
        "recent_event_count_k",    # events touching this agent in a recent window, count/10
        "relationship_extremity",  # mean(abs(relationship)) across this agent's ties, 0..1
        "is_core_cast",            # 1.0 / 0.0
    ],
)


def compute_consequence_label(magnitude: float, life_event_followed: bool, life_event_bonus: float = 0.3) -> float:
    """The real training target: `magnitude` (already clamped 0..1 by
    `emergence.make_observation`) as the base "how big did this look"
    reading, additively bumped -- then re-clamped to 1.0, never
    multiplied -- when a genuine `life_events` entry followed within
    the recorder's own horizon. Additive rather than multiplicative on
    purpose: a magnitude=0 observation that a real life event followed
    should still register as somewhat consequential, not stay pinned
    at zero the way a multiplicative bonus would leave it."""
    base = max(0.0, min(1.0, magnitude))
    if life_event_followed:
        base = max(0.0, min(1.0, base + life_event_bonus))
    return base


@dataclass
class ValueConsequenceModel:
    """Wraps a small regression MLP over `VALUE_MODEL_SCHEMA` predicting
    one agent's current consequence score in [0, 1]. Sigmoid output
    head, not linear (unlike `LLMCostRegressor`) -- the target here is
    a genuine bounded probability-like score, not an unbounded physical
    quantity, so the model's own output range should match it exactly
    rather than needing a separate scale constant."""

    model: MLP
    schema: FeatureSchema = field(default_factory=lambda: VALUE_MODEL_SCHEMA)

    @classmethod
    def new(cls, seed: int = 0) -> "ValueConsequenceModel":
        dim = VALUE_MODEL_SCHEMA.dim()
        return cls(model=MLP.random_init([dim, max(4, dim), 1], output_activation="sigmoid", seed=seed))

    def predict(self, features: dict) -> float:
        encoder = FeatureEncoder(self.schema)
        return self.model.forward(encoder.encode(features))[0]

    def train(self, examples: list, epochs: int = 80, learning_rate: float = 0.05, seed: int = 0) -> None:
        train_mlp_sgd(self.model, examples, epochs=epochs, learning_rate=learning_rate, seed=seed)

    def evaluate(self, examples: list) -> float:
        """Mean squared error in the model's own [0, 1]-scaled units --
        no separate scale constant needed since the sigmoid output head
        and the label are already the same range."""
        return mean_loss(self.model, examples)


def make_training_example(features: dict, magnitude: float, life_event_followed: bool) -> TrainingExample:
    """Encodes one (agent-state features, real observed outcome) pair
    into the shape `ValueConsequenceModel.train` consumes -- the one
    place feature encoding for this model happens, so a real emergence-
    log/life-events archive loader and a live-session trainer would
    produce identical vectors."""
    label = compute_consequence_label(magnitude, life_event_followed)
    encoder = FeatureEncoder(VALUE_MODEL_SCHEMA)
    return TrainingExample(x=encoder.encode(features), y=[label])


def rank_by_predicted_value(model: ValueConsequenceModel, candidates: list[dict]) -> list[dict]:
    """The real B2.4 consumer function, stated as a pure function so
    it's independently testable before any real call site consults it:
    sorts a set of candidate agents' own feature dicts by predicted
    consequence, descending -- "spend the scarce cognition call on the
    agent whose state is most consequential," B2.4's own framing and
    L2.1's stated unblock for it. Ties broken by input order (Python's
    `sorted` is stable), never randomly -- same "no RNG in arbitration"
    discipline the HCA attention-redesign section of CLAUDE.md
    establishes for a related, later-scoped mechanism. Not called from
    any real engine schedule point this pass."""
    return sorted(candidates, key=lambda c: model.predict(c), reverse=True)
