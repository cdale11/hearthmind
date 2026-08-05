"""L2.2 -- the goal policy (docs/ML-ARCHITECTURE-2026-08-01.md, "the
flagship, and the biggest design change"). A closed-class softmax
classifier over `AgentGoal`'s 7 values, meant to replace `llm/
cognition.py`'s `fallback_goal` hand-written if-ladder -- the path
that today handles the MAJORITY of goal decisions in a real run, since
only the core cast ever reaches a live LLM cognition call.

Two-phase training curriculum, per the architecture doc:
- **Phase 1 (`build_distillation_examples`)** -- teacher->student
  distillation from the recorder's existing `(structured_input ->
  goal)` pairs. Bootstraps a policy that reproduces the LLM's/existing
  fallback's judgment across the whole state space, no cold start.
- **Phase 2 (`reweight_by_outcome`)** -- outcome-weighted refinement.
  Pure imitation caps the student at the teacher and inherits its
  mistakes; reweighting examples by REALIZED outcome (did hunger
  actually fall, did the agent survive, did a consequential event
  follow -- L2.1's own job) lets the student diverge from and exceed
  the teacher where the world says it was wrong. This module never
  trains on the policy's own unweighted output -- only externally
  measured outcomes -- per this project's standing guard against
  self-reinforcing training loops.

Homogenization guardrails (mandatory, per the architecture doc):
personality/emotion/plan features are part of the input schema, so one
shared network produces different behaviour per agent state rather
than one flattened population-wide habit; `sample_goal`'s entropy
floor keeps every call genuinely stochastic (never `argmax`); survival
overrides (critical hunger/energy) are explicitly OUT of this module's
scope and must keep being checked BEFORE consulting the policy, same
as `fallback_goal` already does today -- this module never touches
that precedence.

Built on G1's already-shipped `LearningSpecialist` (shadow-gated
continual learning) rather than a new training loop; `training.py`
gained real `softmax`+cross-entropy backprop support for this module
(previously forward-pass-only, no matching trainer existed).

Not wired into `cognition.py`/`Population` this pass -- same "ship the
substrate, wire it once a real consumer/archive exists" discipline
every prior Tier 6 L-layer piece has shipped under. Phase 1 needs a
real recorder archive (`layer1_structured_input -> layer4_parsed_
output` pairs) this offline environment has no live run to source.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import LearnResult, LearningSpecialist
from hearthmind.ml.training import TrainingExample

# The closed AgentGoal set (agents/agent.py) -- kept as a plain string
# list, not an import, so hearthmind/ml/ stays decoupled from World/
# Agent state, same discipline every sibling L-module already holds
# (`cross_run.py`'s `example_loader` callback, `embedding.py`'s
# corpus-agnostic design). This module's softmax class index i <->
# GOAL_VALUES[i] is the one place that mapping lives.
GOAL_VALUES = [
    "wander", "forage", "socialize", "rest", "gather", "seek_person", "explore",
]

GOAL_POLICY_SCHEMA = FeatureSchema(
    numeric_fields=[
        "hunger", "energy",
        "trait_resilience", "trait_sociability", "trait_ambition", "trait_openness",
        "emotion_fear", "emotion_grief", "emotion_joy", "emotion_anger",
        "materials_critical", "has_plan",
    ],
)
"""Deliberately scoped to real, already-available scalar per-agent
state -- the homogenization-guarding conditioning inputs the
architecture doc names (traits/emotions), plus the two forced-
override signals (`materials_critical`/`has_plan`) `fallback_goal`
already reads. `Agent.plan`'s own free TEXT (the doc's "absorbs
planning... as an L1.1-embedded input feature") is deliberately NOT
folded in here yet -- `FeatureSchema` encodes only flat numeric/
categorical slots today, no vector-valued field; concatenating a real
L1.1 `text_vector` needs a small schema extension, flagged as real,
distinct follow-up work once L1.1 has a real corpus wired (see
`docs/ROADMAP-2026-07-REMAINING.md`)."""

ENTROPY_FLOOR_DEFAULT = 0.05
"""Minimum probability mass reserved per class after mixing the
network's raw softmax output with a uniform distribution -- the
architecture doc's own "never argmax" mandate, made a real, checkable
lower bound rather than a hope about temperature/sampling. At 7
classes this reserves 35% of total mass to the floor, 65% to the
learned distribution -- confident but never certain."""

OUTCOME_OVERSAMPLE_SCALE = 10
"""Phase 2's outcome-reweighting mechanism: `train_mlp_sgd` (and the
`LearningSpecialist`/`continual_train_mlp` loop wrapping it) take
uniformly-weighted examples, so a real per-example outcome weight is
applied via deterministic integer oversampling -- a weight near 1.0
keeps an example at roughly its original frequency, a weight near 0
keeps it at a bare minimum (never fully erased -- the student refines
away from a bad teacher call, it doesn't have that state deleted from
its experience). Chosen over adding a weighted-loss code path to the
L0 trainer, which would need touching every existing MSE/sigmoid
caller for one new consumer's benefit."""


def encode_agent_state(values: dict) -> list:
    return FeatureEncoder(GOAL_POLICY_SCHEMA).encode(values)


def build_policy_model(hidden_dims: tuple = (16,), seed: int = 0) -> MLP:
    dims = [GOAL_POLICY_SCHEMA.dim()] + list(hidden_dims) + [len(GOAL_VALUES)]
    return MLP.random_init(dims, output_activation="softmax", seed=seed)


def _apply_entropy_floor(probs: list, floor: float) -> list:
    """`p_i' = (1 - floor*k)*p_i + floor` -- exact normalization (sums
    to 1 by construction, no renormalization pass needed) and a real
    guaranteed per-class minimum, not an approximation."""
    k = len(probs)
    if k == 0:
        return probs
    reserved = min(floor * k, 1.0)
    scale = 1.0 - reserved
    return [scale * p + floor for p in probs]


@dataclass
class GoalPrediction:
    distribution: dict = field(default_factory=dict)
    """goal -> probability, AFTER the entropy floor -- what `sample_
    goal` actually draws from."""
    raw_distribution: dict = field(default_factory=dict)
    """goal -> probability, the network's own unmodified softmax
    output -- useful for diagnostics/confidence reporting, never used
    for sampling directly."""

    def argmax(self) -> str:
        """The single most-likely goal -- diagnostic/logging use only.
        `sample_goal` must be used for the real decision; this exists
        so a caller can show "the policy leaned toward X" without
        conflating that with what was actually chosen."""
        return max(self.raw_distribution, key=self.raw_distribution.get)


class GoalPolicy:
    """Wraps a `LearningSpecialist` over the closed-class goal MLP.
    `predict`/`sample_goal` are the real inference path; `learn` is
    Phase 1/2's shared entry point (both phases just differ in how
    their `examples` were built -- see module-level functions)."""

    def __init__(
        self, specialist: LearningSpecialist | None = None,
        entropy_floor: float = ENTROPY_FLOOR_DEFAULT, seed: int = 0,
    ) -> None:
        self.specialist = specialist or LearningSpecialist(build_policy_model(seed=seed))
        self.entropy_floor = entropy_floor

    def predict(self, agent_state: dict) -> GoalPrediction:
        raw = self.specialist.predict(encode_agent_state(agent_state))
        floored = _apply_entropy_floor(raw, self.entropy_floor)
        return GoalPrediction(
            distribution=dict(zip(GOAL_VALUES, floored)),
            raw_distribution=dict(zip(GOAL_VALUES, raw)),
        )

    def sample_goal(self, agent_state: dict, rng: random.Random) -> str:
        """The real per-agent decision -- entropy-floored, genuinely
        stochastic, never `argmax`. Personality/emotion state entering
        via `agent_state` is what makes two differently-tempered
        agents in the identical situation draw different distributions
        from the SAME shared network."""
        pred = self.predict(agent_state)
        goals = list(pred.distribution.keys())
        weights = list(pred.distribution.values())
        return rng.choices(goals, weights=weights, k=1)[0]

    def learn(
        self, examples: list, holdout_examples: list, tick: int, **kwargs,
    ) -> LearnResult:
        """Thin pass-through to the wrapped `LearningSpecialist`,
        fixed to `loss="cross_entropy"` -- the correct, only-supported
        loss for this module's `softmax` head (see `training.py`)."""
        kwargs.pop("loss", None)
        return self.specialist.learn(examples, holdout_examples, tick, loss="cross_entropy", **kwargs)


def build_distillation_examples(structured_inputs: list, goals: list) -> list:
    """Phase 1: one `TrainingExample` per real recorded `(structured_
    input, goal)` pair, one-hot over `GOAL_VALUES`. A goal value
    outside the closed set is skipped, never coerced to a fabricated
    class -- a genuinely malformed/legacy recorder row shouldn't teach
    the policy a class that doesn't exist."""
    examples = []
    for state, goal in zip(structured_inputs, goals):
        if goal not in GOAL_VALUES:
            continue
        x = encode_agent_state(state)
        y = [1.0 if g == goal else 0.0 for g in GOAL_VALUES]
        examples.append(TrainingExample(x=x, y=y))
    return examples


def reweight_by_outcome(examples: list, outcome_weights: list) -> list:
    """Phase 2: deterministic integer oversampling by a real,
    externally-measured outcome weight in `[0, 1]` per example (did
    hunger fall, did the agent survive, did a consequential event
    follow -- L2.1's job, never this policy's own prediction fed back
    in). `len(outcome_weights) != len(examples)` is a caller error
    handled by `zip`'s own truncation, not silently padded with a
    fabricated weight."""
    reweighted = []
    for ex, w in zip(examples, outcome_weights):
        w = max(0.0, min(1.0, w))
        count = max(1, round(w * OUTCOME_OVERSAMPLE_SCALE))
        reweighted.extend([ex] * count)
    return reweighted
