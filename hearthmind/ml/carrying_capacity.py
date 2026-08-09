"""Tier 6 -- learned regression target for `Population.carrying_
capacity` (docs/ROADMAP-2026-07-REMAINING.md's Group 1, explicit user
product decision closing the item CLAUDE.md's v1.34.299 entry left
flagged: "genuinely ambiguous whether it crosses docs/CONSTITUTION.
md's Body/Mind line"). The decision, made explicitly rather than
guessed at unilaterally: yes -- a learned correction, bounded and
never allowed to override the hand formula's own safety clamps, is
now wired.

Reuses L0's `FeatureEncoder`/`MLP`/`train_mlp_sgd` directly, same
thin-wrapper shape `ValueConsequenceModel`/`LLMCostRegressor`
established -- this module owns feature encoding + the model, not a
second training implementation.

**Real, already-persisted training signal -- not hand-labeled.**
`SimulationEngine._log_daily_metrics` has written one real time-series
row per sim-day to the `metrics` table (`persistence/database.py`,
`Config.metrics_log_retention`) since well before this module existed
-- `population`, `avg_hunger`, `deaths_starvation` (cumulative),
`materials`, `currency`, `buildings_standing`, `tech_level` are all
real, already-tracked, already-persisted fields. No new tracked state
was added to build this trainer.

**Honest limitation, stated plainly (same discipline as `train_value_
model_from_archive.py`'s own "one snapshot-in-time per agent" note):**
`metrics` rows are WORLD-scoped, not per-settlement -- `population`/
`materials`/`currency` are summed across every named settlement a
multi-settlement world has (see `_log_daily_metrics`'s own `pop_
summary`/`sum(s.materials for s in settlements)`). A single-settlement
world (still the overwhelmingly common shape this project's own worlds
take) trains cleanly against its own real history; a multi-settlement
world's history trains against the WORLD aggregate, which is only an
approximation of any one settlement's own real capacity ceiling. No
per-settlement metrics time series exists to train against instead --
building one is real, distinct future work, not attempted here.

**No true population-growth time series exists either** -- `metrics`
rows ARE that time series (one population reading per sim-day), so
this module reads it directly rather than reconstructing one; what
does NOT exist is a labeled "this is the true carrying capacity"
ground truth for any row. `compute_carrying_capacity_label` is the
self-supervised proxy: real hunger + real starvation-death pressure
(both already logged) push the implied capacity below the observed
population when a settlement is visibly overshooting it, and pull it
above the observed population when hunger stays comfortable and no one
is starving (evidence the settlement hasn't found its ceiling yet).
This is a proxy, not a measurement -- a settlement that has simply
never gotten crowded enough to test its own ceiling will train toward
"capacity is a bit above whatever I've seen," which is honest (that IS
the best available evidence) but not the same as having watched a real
stall happen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.training import TrainingExample, mean_loss, train_mlp_sgd
from hearthmind.util import clamp

CARRYING_CAPACITY_SCHEMA_VERSION = 1

# Every field here is deliberately restricted to something both (a)
# already logged, per sim-day, in the real `metrics` table (so a
# trainer can build historical examples with zero new instrumentation)
# and (b) cheaply computable inline from live `Settlement`/`Population`
# state at the one real inference call site (`Population.carrying_
# capacity`) -- the same vector shape trains and predicts, never two
# slightly-different encodings of "the same" state.
CARRYING_CAPACITY_SCHEMA = FeatureSchema(
    numeric_fields=[
        "population_k",         # current population / POPULATION_FEATURE_SCALE
        "avg_hunger",            # 0..1 already
        "avg_energy",             # 0..1 already
        "materials_k",            # settlement materials / RESOURCE_FEATURE_SCALE
        "currency_k",              # settlement currency / RESOURCE_FEATURE_SCALE
        "buildings_standing_k",    # standing buildings / BUILDINGS_FEATURE_SCALE
        "tech_level_k",             # settlement.tech_level / TECH_LEVEL_FEATURE_SCALE
    ],
)

POPULATION_FEATURE_SCALE = 200.0
"""Rough middle of this project's own documented equilibrium range
(CLAUDE.md's own "Diagnostic history index": abundant maps reach the
flat `POPULATION_CAP=400` safety valve; typical settled populations
sit well below that) -- keeps the dominant feature near unit scale for
plain-SGD stability, same normalization discipline `LLM_COST_SCHEMA`'s
own docstring documents the NaN-divergence history behind."""

RESOURCE_FEATURE_SCALE = 100.0
"""`GRANARY_CAPACITY`/`CURRENCY_CAPACITY`-adjacent order of magnitude
(settlement.py's own per-building capacity constants) -- materials/
currency readings cluster in the tens-to-low-hundreds in a real
settlement, so this keeps both near unit scale."""

BUILDINGS_FEATURE_SCALE = 30.0
"""A settlement with 30 standing buildings is already a substantial
town by this project's own era-infrastructure ladder (`ERA_
INFRASTRUCTURE_REQUIREMENTS`'s own `digital`-era bar tops out around
15 huts + supporting infra) -- keeps the feature near unit scale
without needing to track a settlement-size-dependent ceiling."""

TECH_LEVEL_FEATURE_SCALE = 20.0
"""`tech_level` is an unbounded invention counter, not itself capped
at the ten-era `ERA_ORDER` ladder's length -- 20 is a reasoned
"comfortably past `digital`" ceiling for feature-scale purposes only;
a tech_level well past this still encodes as a value modestly above
1.0 rather than exploding, since nothing here clamps the encoded
value itself (see `encoder.FeatureEncoder`'s own "absence means
neutral, never crashes" contract -- an out-of-range numeric value is
likewise never rejected, just fed through)."""

CAPACITY_OUTPUT_SCALE = 400.0
"""Same `POPULATION_CAP=400` reference point `POPULATION_FEATURE_
SCALE` uses -- the model's internal linear-head units are `y / CAPACITY_
OUTPUT_SCALE`; `predict()` always returns a real population-count
figure regardless, same boundary-only-scaling discipline
`LATENCY_SCALE_MS`/`LLMCostRegressor.predict` already establish."""

HUNGER_COMFORT_FOR_LABEL = 0.5
"""Deliberately NOT imported from `agents.population.CARRYING_
CAPACITY_HUNGER_COMFORT` -- per this project's own standing dependency
discipline ("the substrate should stay reused UPWARD by Runtime/
gameplay code, never the reverse," `LLMCostRegressor`'s own docstring
for the identical reasoning), an `hearthmind/ml/` module never imports
from `agents/`/`settlement/`/`world/`. Same value, kept independently
so this module has zero coupling to that one."""

STARVATION_PRESSURE_PER_CAPITA_SCALE = 20.0
"""One real starvation death per this many living people, within one
sim-day's delta, is treated as maximal pressure on its own (saturates
the starvation half of `compute_carrying_capacity_label`'s pressure
term) -- a reasoned "even a single fresh death in a modest settlement
is a real, sharp signal" starting point; no live-diagnostic history
exists yet to tune this further."""

CAPACITY_LABEL_ADJUST_MAX = 0.35
"""How far the self-supervised label is allowed to sit above/below the
literal observed population for a maximally-comfortable/maximally-
pressured reading -- bounded so a single noisy day never implies an
absurd capacity swing; a real, sustained pattern across many training
rows is what actually pulls the trained model's prediction, not any
one row's own label."""

CARRYING_CAPACITY_MODEL_BLEND_MAX = 0.25
"""The real consumption bound at `Population.carrying_capacity`'s one
call site: a loaded model's prediction is applied as a RATIO on top of
the hand formula's own output, clamped to `[1 - 0.25, 1 + 0.25]` --
the learned correction can meaningfully move the ceiling once trained
(+/-25% is a real, felt difference against a typical few-hundred-
person settlement) but can never override the hand formula's own
tuned weights/clamps/`dynamic_population_cap` safety valve by more
than a modest fraction. `carrying_capacity_model=None` (every world
until an operator trains one) skips this blend entirely -- see
`blended_capacity`'s own docstring for the exact byte-for-byte-parity
argument."""


def carrying_capacity_features(
    population: float, avg_hunger: float, avg_energy: float,
    materials: float, currency: float, buildings_standing: float, tech_level: float,
) -> dict:
    """The one place this model's feature encoding happens -- shared by
    the live inference call site (`Population.carrying_capacity`) and
    the offline trainer (`scripts/train_carrying_capacity_from_world.
    py`, building rows straight from the real `metrics` table), so both
    produce identical vectors for identical state."""
    return {
        "population_k": population / POPULATION_FEATURE_SCALE,
        "avg_hunger": clamp(avg_hunger, 0.0, 1.0),
        "avg_energy": clamp(avg_energy, 0.0, 1.0),
        "materials_k": materials / RESOURCE_FEATURE_SCALE,
        "currency_k": currency / RESOURCE_FEATURE_SCALE,
        "buildings_standing_k": buildings_standing / BUILDINGS_FEATURE_SCALE,
        "tech_level_k": tech_level / TECH_LEVEL_FEATURE_SCALE,
    }


def compute_carrying_capacity_label(
    population: float, avg_hunger: float, starvation_delta: float,
    hunger_comfort: float = HUNGER_COMFORT_FOR_LABEL,
) -> float:
    """The self-supervised training target -- see the module docstring
    for the honest limitation this is a proxy, not a measurement.

    `hunger_pressure`: 0 once `avg_hunger` is at/below `hunger_comfort`,
    rising to 1 at `avg_hunger=1.0`. `starvation_pressure`: real
    starvation deaths that occurred since the PRIOR sample (a per-day
    delta against the same cumulative `deaths_starvation` counter
    `_log_daily_metrics` already logs), scaled per living capita so a
    death in a small settlement counts for more than the same single
    death in a huge one. Both combine (never multiply -- either signal
    alone is real evidence of overshoot) into one bounded `pressure`
    term that shifts the observed population up or down by at most
    `CAPACITY_LABEL_ADJUST_MAX`:

    - `pressure=0` (comfortable, nobody starving): the settlement
      hasn't found its ceiling yet -- label sits ABOVE current
      population, the honest "capacity is at least this much" proxy.
    - `pressure=1` (miserable, people dying of hunger): the settlement
      has visibly overshot -- label sits BELOW current population, the
      honest "the real sustainable level is somewhat less than this"
      proxy."""
    hunger_pressure = clamp(
        (avg_hunger - hunger_comfort) / max(1e-6, 1.0 - hunger_comfort), 0.0, 1.0,
    )
    starvation_pressure = clamp(
        max(0.0, starvation_delta) / max(1.0, population) * STARVATION_PRESSURE_PER_CAPITA_SCALE, 0.0, 1.0,
    )
    pressure = clamp(hunger_pressure + starvation_pressure, 0.0, 1.0)
    factor = 1.0 + CAPACITY_LABEL_ADJUST_MAX * (1.0 - 2.0 * pressure)
    return max(0.0, population * factor)


def make_training_example(features: dict, label: float) -> TrainingExample:
    """Encodes one (state features, self-supervised label) pair into
    the shape `CarryingCapacityModel.train` consumes. Internally
    `CAPACITY_OUTPUT_SCALE`-scaled; see that constant's docstring."""
    encoder = FeatureEncoder(CARRYING_CAPACITY_SCHEMA)
    return TrainingExample(x=encoder.encode(features), y=[label / CAPACITY_OUTPUT_SCALE])


@dataclass
class CarryingCapacityModel:
    """Wraps a small regression MLP over `CARRYING_CAPACITY_SCHEMA`
    predicting one settlement's own real population ceiling. Linear
    output head (like `LLMCostRegressor`, unlike `ValueConsequence
    Model`'s sigmoid) -- the target is an unbounded, real-world-scale
    population count, not a [0, 1] probability-like score."""

    model: MLP
    schema: FeatureSchema = field(default_factory=lambda: CARRYING_CAPACITY_SCHEMA)

    @classmethod
    def new(cls, seed: int = 0) -> "CarryingCapacityModel":
        dim = CARRYING_CAPACITY_SCHEMA.dim()
        return cls(model=MLP.random_init([dim, max(4, dim), 1], output_activation="linear", seed=seed))

    def predict(self, features: dict) -> float:
        encoder = FeatureEncoder(self.schema)
        return max(0.0, self.model.forward(encoder.encode(features))[0] * CAPACITY_OUTPUT_SCALE)

    def train(self, examples: list, epochs: int = 80, learning_rate: float = 0.01, seed: int = 0) -> None:
        train_mlp_sgd(self.model, examples, epochs=epochs, learning_rate=learning_rate, seed=seed)

    def evaluate(self, examples: list) -> float:
        """Mean squared error in `CAPACITY_OUTPUT_SCALE`-scaled units --
        comparable across calls, not a real-population-count figure
        itself; use `predict()` against a held-out example's own
        features and compare to its real label directly for that."""
        return mean_loss(self.model, examples)

    def to_dict(self) -> dict:
        return {
            "schema_version": CARRYING_CAPACITY_SCHEMA_VERSION,
            "kind": "carrying_capacity_model",
            "model": self.model.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CarryingCapacityModel":
        if d.get("schema_version") != CARRYING_CAPACITY_SCHEMA_VERSION:
            raise ValueError(f"unsupported carrying_capacity_model schema_version={d.get('schema_version')!r}")
        if d.get("kind") != "carrying_capacity_model":
            raise ValueError(f"weights file is for {d.get('kind')!r}, not 'carrying_capacity_model'")
        return cls(model=MLP.from_dict(d["model"]))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "CarryingCapacityModel":
        with open(path) as f:
            return cls.from_dict(json.load(f))


def blended_capacity(hand_capacity: float, predicted_capacity: float, blend_max: float = CARRYING_CAPACITY_MODEL_BLEND_MAX) -> float:
    """The real consumption function at `Population.carrying_capacity`'s
    one call site -- a pure function so it's independently testable
    before any real caller consults it.

    `hand_capacity` (the tuned formula's own output, already clamped
    against `CARRYING_CAPACITY_MIN/MAX_MULTIPLIER` and `housing_
    capacity`) stays structurally dominant: the model's prediction can
    only ever nudge it by a bounded ratio (`CARRYING_CAPACITY_MODEL_
    BLEND_MAX`), never replace it outright. A `hand_capacity` of 0.0
    (a settlement with no housing at all) is returned unchanged -- a
    ratio has no meaningful effect on zero, and this avoids a
    division-by-something-degenerate edge case."""
    if hand_capacity <= 0.0:
        return hand_capacity
    ratio = clamp(predicted_capacity / hand_capacity, 1.0 - blend_max, 1.0 + blend_max)
    return hand_capacity * ratio
