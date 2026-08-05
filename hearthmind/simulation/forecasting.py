"""B8 -- Predictive scheduling (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, Hard Rule 8). Standalone infrastructure, same "never big-bang"
discipline as every other Tier 5 Runtime module -- not wired into
`simulation/engine.py` or the live tick loop yet.

B8.1 `WorkloadForecaster`: a small MLP (`hearthmind.ml.primitives`)
     predicting near-term LLM call volume from simulation-state
     features (season, recent event pressure, backlog). Its training
     harness can pool examples across every past archived run found on
     disk (`hearthmind.ml.cross_run`), per the explicit "AI/ML models
     should learn from all previous runs if possible" instruction --
     this forecaster describes THIS MACHINE's runtime behaviour, not
     any one world's cognition, so unlike a per-world Mind model
     (`docs/ML-ARCHITECTURE-2026-08-01.md`'s guardrail #3) it has no
     reason to start over every session.
B8.2 `plan_reservation`: a deterministic policy turning a forecast +
     its own reliability into how much capacity to hold, without
     idling it (the reservation is a HINT for background work to fill,
     never a hard block).
B8.3 `ForecastAccuracyTracker`: scores every prediction against its
     later-observed outcome and derives a `reliability_weight()` a
     consistently-wrong predictor is automatically down-weighted by --
     "prediction that is never scored becomes superstition," per the
     item's own text.
B8.4 `is_quiet_window`: a deterministic read of recent load history,
     for scheduling maintenance work into predicted-quiet periods.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from hearthmind.cognition.workspace import Domain
from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP

SPECIALIST_DOMAIN = Domain.MACHINE
"""Tier 7 HCA Stage H, H2: `WorkloadForecaster`/`ForecastAccuracyTracker`
are the Adaptive Runtime specialist family's real `predict()`/`error()`
(see `hearthmind.cognition.runtime_specialist`'s own module docstring
for the full family mapping) -- this file already imports nothing from
`hearthmind.world`/`.agents`/`.settlement`/`.economy`, so the marker
alone makes `scripts/verify_runtime_invariant.py`'s write-scope check
real against this real production module."""
from hearthmind.ml.training import TrainingExample, mean_loss, train_mlp_sgd

# B8.1's feature schema: the item's own three named trigger examples
# (storm -> dialogue/cognition spike, harvest season -> economy surge,
# a scheduled festival -> event burst) map onto a small, generic
# vector -- any future trigger just adds a numeric/categorical field,
# never a new pipeline (same "adding a model is adding a head"
# discipline L0's encoder was built for).
WORKLOAD_FORECAST_SCHEMA = FeatureSchema(
    numeric_fields=[
        "current_backlog",
        "recent_dialogue_rate",
        "recent_cognition_rate",
        "active_disaster",
        "festival_scheduled",
    ],
    categorical_fields={"season": ["spring", "summer", "autumn", "winter"]},
)


@dataclass
class WorkloadForecaster:
    """B8.1. Wraps a small regression MLP over `WORKLOAD_FORECAST_
    SCHEMA` predicting near-term LLM call volume. Training is a thin
    wrapper over `hearthmind.ml.training` -- this class owns the
    feature encoding and the model, not a second training
    implementation."""

    model: MLP
    schema: FeatureSchema = field(default_factory=lambda: WORKLOAD_FORECAST_SCHEMA)

    @classmethod
    def new(cls, seed: int = 0) -> "WorkloadForecaster":
        dim = WORKLOAD_FORECAST_SCHEMA.dim()
        return cls(model=MLP.random_init([dim, max(4, dim), 1], output_activation="linear", seed=seed))

    def predict(self, features: dict) -> float:
        encoder = FeatureEncoder(self.schema)
        return self.model.forward(encoder.encode(features))[0]

    def train(self, examples: list, epochs: int = 60, learning_rate: float = 0.02, seed: int = 0) -> None:
        train_mlp_sgd(self.model, examples, epochs=epochs, learning_rate=learning_rate, seed=seed)

    def evaluate(self, examples: list) -> float:
        return mean_loss(self.model, examples)


def make_training_example(features: dict, observed_call_volume: float) -> TrainingExample:
    """Encodes one (situation, what actually happened) pair into the
    shape `WorkloadForecaster.train` consumes -- the one place feature
    encoding for this model happens, so a cross-run pooling loader and
    a live-session recorder both produce identical vectors."""
    encoder = FeatureEncoder(WORKLOAD_FORECAST_SCHEMA)
    return TrainingExample(x=encoder.encode(features), y=[observed_call_volume])


@dataclass
class ForecastAccuracyTracker:
    """B8.3. Bounded history of (predicted, actual) pairs; derives a
    reliability weight so a consistently-wrong forecaster is
    automatically down-weighted rather than trusted forever on the
    strength of its own unchecked predictions."""

    history_size: int = 200
    _pairs: deque = field(default_factory=lambda: deque(maxlen=200))

    def __post_init__(self):
        if self._pairs.maxlen != self.history_size:
            self._pairs = deque(self._pairs, maxlen=self.history_size)

    def record(self, predicted: float, actual: float) -> None:
        self._pairs.append((predicted, actual))

    def mean_absolute_error(self) -> float | None:
        if not self._pairs:
            return None
        return sum(abs(p - a) for p, a in self._pairs) / len(self._pairs)

    def naive_baseline_mae(self) -> float | None:
        """MAE of "always predict the historical mean actual value" --
        the floor a real forecaster has to beat to be worth trusting
        at all."""
        if not self._pairs:
            return None
        actuals = [a for _, a in self._pairs]
        mean_actual = sum(actuals) / len(actuals)
        return sum(abs(mean_actual - a) for a in actuals) / len(actuals)

    def reliability_weight(self) -> float:
        """1.0 = trust the forecaster fully, 0.0 = ignore it entirely
        (fall back to whatever a non-predictive scheduler would do).
        Scaled against the naive-baseline floor: a forecaster doing no
        better than "predict the mean" scores 0.0; one with zero error
        scores 1.0. Needs at least a few observations to say anything
        (a fresh tracker defaults to full trust rather than false
        distrust, since there's no evidence yet either way)."""
        if len(self._pairs) < 5:
            return 1.0
        mae = self.mean_absolute_error()
        baseline = self.naive_baseline_mae()
        if not baseline:
            return 1.0
        return max(0.0, min(1.0, 1.0 - (mae / baseline)))


def plan_reservation(predicted_load: float, current_capacity: int, reliability_weight: float) -> int:
    """B8.2. A deterministic, capacity-bounded reservation hint --
    NEVER a hard block; the reserved slots are meant to be filled with
    cheap-to-preempt background work until the predicted need actually
    arrives. Scaled by `reliability_weight` so an untrustworthy
    forecaster reserves less, converging to reserving nothing at
    `reliability_weight=0`."""
    if predicted_load <= 0 or current_capacity <= 0:
        return 0
    raw = predicted_load * reliability_weight
    return max(0, min(current_capacity, round(raw)))


def is_quiet_window(recent_loads: list, capacity: float, threshold_fraction: float = 0.3) -> bool:
    """B8.4. True when recent load history has stayed consistently
    below `threshold_fraction` of `capacity` -- a real signal to
    schedule expensive maintenance (compression, persistence, archive
    migration, index rebuilds) into, rather than a guess."""
    if not recent_loads or capacity <= 0:
        return False
    return all(load <= capacity * threshold_fraction for load in recent_loads)
