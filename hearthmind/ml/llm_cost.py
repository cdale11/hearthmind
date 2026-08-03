"""Tier 6, L3.1 -- LLM cost regressor (docs/ML-ARCHITECTURE-2026-08-01.md,
docs/ROADMAP-2026-07-REMAINING.md's Tier 6 section: "predict latency_ms
before issuing a call; attacks calls_dropped_backpressure at its
root"). Standalone infrastructure, same "never big-bang" discipline as
every other Tier 6/Tier 5 module shipped so far -- not wired into
`llm/jobs.py`/`simulation/engine.py`'s real scheduling path this pass.

Distinct from L3.2 (`simulation/forecasting.py`'s `WorkloadForecaster`):
that model predicts AGGREGATE near-term call VOLUME for the whole
engine from simulation-state features (season, disaster, festival).
This one predicts the LATENCY of one SPECIFIC about-to-be-issued call
from that call's own shape (which task, how large a prompt/context,
whether it's a `deep_reasoning` call, how loaded the queue already is)
-- a genuinely different question with a genuinely different real
consumer: `_schedule_llm_job` could, in principle, defer or skip a
call predicted to take unusually long while the backlog is already
elevated, attacking `calls_dropped_backpressure` before the call is
even issued rather than reacting to it after the fact. That wiring is
explicitly NOT done here -- it needs real weights trained against a
real `llm/recorder.py` archive (`prompt_metadata`/`generation_config`/
per-example latency, all real fields since v1.34.29 gained the review-
diagnostics context work), which this offline environment has no live
archive to source, same reasoning L0's own filing gave for shipping
the substrate before any real consumer.

Reuses L0's `FeatureEncoder`/`MLP`/`train_mlp_sgd` directly -- this
module owns feature encoding + the model, not a second training
implementation, same discipline `WorkloadForecaster` established.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.training import TrainingExample, mean_loss, train_mlp_sgd

# A closed, deliberately small task vocabulary -- the highest-volume
# real `_schedule_llm_job` tasks (see llm/json_schemas.py's own
# TASK_SCHEMAS keys plus the two highest-volume unconstrained tasks,
# beliefs/personal_belief) rather than every one of the ~55 scattered
# LLM jobs. An unrecognized task degrades to FeatureEncoder's own
# "unknown category -> all-zero one-hot" behavior (see encoder.py),
# never raises -- widening this list later is additive, not breaking.
LLM_COST_TASKS = [
    "cognition", "dialogue", "voice_dialogue", "town_brain", "chronicle",
    "folklore", "dream", "naming", "rumor_interpret", "mind",
    "beliefs", "personal_belief",
]

# Numeric fields are deliberately pre-scaled to roughly [0, few] rather
# than raw units -- `prompt_chars_k`/`context_chars_k` are character
# counts in THOUSANDS (a ~2500-char prompt encodes as 2.5), matching
# `WORKLOAD_FORECAST_SCHEMA`'s own convention of small fractional/rate
# values rather than raw counts. This isn't cosmetic: plain SGD over
# unnormalized large-magnitude inputs has already bitten this codebase
# once (CLAUDE.md's own v1.34.174 entry -- un-normalized 0-10-range
# synthetic features reliably diverged to NaN even at a learning rate
# every other check safely used) and a real caller building this dict
# from `prompt_metadata`'s character counts needs to divide by 1000
# before handing it to `make_training_example`/`predict`, not after.
LLM_COST_SCHEMA = FeatureSchema(
    numeric_fields=[
        "prompt_chars_k",
        "context_chars_k",
        "current_backlog_fraction",
        "concurrency_limit",
        "deep_reasoning",
    ],
    categorical_fields={"task": LLM_COST_TASKS},
)

# The other half of the same normalization discipline: a real call's
# latency spans roughly 200ms-60000ms, another large-magnitude target
# a linear regression head trained by plain SGD can't absorb safely at
# a workable learning rate. `make_training_example`/`LLMCostRegressor.
# predict` divide/multiply by this scale at the model boundary only --
# every OTHER public surface (the class's own docstrings, a real future
# caller) still deals exclusively in real milliseconds.
LATENCY_SCALE_MS = 1000.0


@dataclass
class LLMCostRegressor:
    """Wraps a small regression MLP over `LLM_COST_SCHEMA` predicting
    one call's `latency_ms` before it's issued. Same thin-wrapper shape
    as `WorkloadForecaster` -- this class owns feature encoding + the
    model, training itself is `hearthmind.ml.training`'s job. The
    model's own internal units are `LATENCY_SCALE_MS`-scaled (see that
    constant's docstring); `predict()` always returns real milliseconds
    regardless."""

    model: MLP
    schema: FeatureSchema = field(default_factory=lambda: LLM_COST_SCHEMA)

    @classmethod
    def new(cls, seed: int = 0) -> "LLMCostRegressor":
        dim = LLM_COST_SCHEMA.dim()
        return cls(model=MLP.random_init([dim, max(4, dim), 1], output_activation="linear", seed=seed))

    def predict(self, features: dict) -> float:
        encoder = FeatureEncoder(self.schema)
        return self.model.forward(encoder.encode(features))[0] * LATENCY_SCALE_MS

    def train(self, examples: list, epochs: int = 60, learning_rate: float = 0.001, seed: int = 0) -> None:
        """`learning_rate=0.001` default, not this codebase's more
        common `0.01`-`0.05`: even after the `LATENCY_SCALE_MS`
        normalization above, `deep_reasoning`'s own target contribution
        (a real call genuinely can take ~15x longer) keeps `y`'s range
        wide enough that 0.005 and above measurably diverged to NaN
        during this module's own verification
        (`scripts/verify_llm_cost.py`) -- found and fixed here, not
        left for a caller to rediscover."""
        train_mlp_sgd(self.model, examples, epochs=epochs, learning_rate=learning_rate, seed=seed)

    def evaluate(self, examples: list) -> float:
        """Mean squared error in `LATENCY_SCALE_MS`-scaled units (the
        same units `examples` were built in via `make_training_
        example`) -- comparable across calls, not a real-ms figure
        itself; use `predict()` against a held-out example's own
        features and compare to its real observed latency directly for
        a real-ms error reading."""
        return mean_loss(self.model, examples)


def make_training_example(features: dict, observed_latency_ms: float) -> TrainingExample:
    """Encodes one (call shape, real observed latency) pair into the
    shape `LLMCostRegressor.train` consumes -- the one place feature
    encoding for this model happens, so a real `llm/recorder.py`
    archive loader and a live-session recorder would produce identical
    vectors. `observed_latency_ms` is the real per-call figure
    `CognitionRunner.stats()`'s `latency_ms_*` percentiles are already
    derived from -- this model would eventually train on the same raw
    per-call latencies, not a second measurement. Internally scaled by
    `LATENCY_SCALE_MS`; see that constant's docstring."""
    encoder = FeatureEncoder(LLM_COST_SCHEMA)
    return TrainingExample(x=encoder.encode(features), y=[observed_latency_ms / LATENCY_SCALE_MS])


@dataclass
class CostPredictionAccuracyTracker:
    """Deliberately parallel to (but not importing) `simulation.
    forecasting.ForecastAccuracyTracker` -- that class lives in the
    Tier 5 Runtime layer, and a Tier 6 `hearthmind/ml/` module has no
    reason to depend downward into it (the substrate should stay reused
    UPWARD by Runtime/gameplay code, never the reverse). Same math,
    same "prediction that is never scored becomes superstition"
    discipline: a consistently-wrong predictor is automatically
    down-weighted rather than trusted forever on its own say-so."""

    history_size: int = 200
    _pairs: deque = field(default_factory=lambda: deque(maxlen=200))

    def __post_init__(self):
        if self._pairs.maxlen != self.history_size:
            self._pairs = deque(self._pairs, maxlen=self.history_size)

    def record(self, predicted_ms: float, actual_ms: float) -> None:
        self._pairs.append((predicted_ms, actual_ms))

    def mean_absolute_error(self) -> float | None:
        if not self._pairs:
            return None
        return sum(abs(p - a) for p, a in self._pairs) / len(self._pairs)

    def naive_baseline_mae(self) -> float | None:
        """MAE of "always predict the historical mean actual latency" --
        the floor a real regressor has to beat to be worth consulting
        at all."""
        if not self._pairs:
            return None
        actuals = [a for _, a in self._pairs]
        mean_actual = sum(actuals) / len(actuals)
        return sum(abs(mean_actual - a) for a in actuals) / len(actuals)

    def reliability_weight(self) -> float:
        """1.0 = trust the regressor fully, 0.0 = ignore it entirely.
        A fresh tracker with fewer than 5 observations defaults to full
        trust rather than false distrust, since there's no evidence yet
        either way -- same convention `ForecastAccuracyTracker` uses."""
        if len(self._pairs) < 5:
            return 1.0
        mae = self.mean_absolute_error()
        baseline = self.naive_baseline_mae()
        if not baseline:
            return 1.0
        return max(0.0, min(1.0, 1.0 - (mae / baseline)))


def should_preflight_defer(
    predicted_latency_ms: float, current_backlog_fraction: float, reliability_weight: float,
    elevated_latency_ms: float, elevated_backlog_fraction: float = 0.8,
) -> bool:
    """The real decision this model would inform, stated as a pure
    function so it's independently testable before any real call site
    ever consults it: defer a call ONLY when both a genuinely
    trustworthy prediction (`reliability_weight` scaled in, same
    "an untrustworthy model recommends nothing" discipline as B8.2's
    `plan_reservation`) says this SPECIFIC call would be unusually
    slow AND the queue is already meaningfully loaded -- a slow-but-
    predicted call on an otherwise idle queue should still run; a
    fast-predicted call never defers regardless of backlog. Never a
    hard block by itself -- same "hint, not gate" framing as B8.2;
    the actual call site (real future work, not built this pass) would
    still own whether to honor it."""
    if reliability_weight <= 0.0:
        return False
    if current_backlog_fraction < elevated_backlog_fraction:
        return False
    weighted_prediction = predicted_latency_ms * reliability_weight
    return weighted_prediction >= elevated_latency_ms
