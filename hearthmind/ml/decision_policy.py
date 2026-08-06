"""Tier 6, Phase 1's last named item: "five more `fallback_goal`-shaped
LLM/deterministic sites... none yet promoted to an L-layer slot"
(docs/ROADMAP-2026-07-REMAINING.md) -- `llm/dispute.py`'s `fallback_
dispute`, `llm/fission.py`/`llm/migration.py`'s `fallback_decision`,
and `llm/founding.py`'s `fallback_founding` are all, structurally, the
exact same shape `hearthmind.ml.goal_policy.GoalPolicy` already solved
for `llm/cognition.py`'s `fallback_goal`: a closed-class decision made
today by a hand-written if-ladder, reached whenever a real LLM call is
skipped/backpressured/fails, with a real recorded-outcome history a
live deployment's own `llm/recorder.py` archive already accumulates.

Rather than four near-duplicate copies of `GoalPolicy`'s own class,
this module generalizes it once: `DecisionPolicy(classes, schema)` is
the exact same softmax-MLP/entropy-floor/allowed-classes-masking/
shadow-gated-continual-learning machinery, parameterized instead of
hard-coded to `AgentGoal`'s 7 values. `hearthmind/ml/goal_policy.py`
itself is left exactly as it was (a real, working, already-shipped
production consumer) -- NOT retrofitted onto this generalization, to
avoid disturbing anything already verified and wired.

Four concrete configs below (`DISPUTE_POLICY_CONFIG`/`FISSION_POLICY_
CONFIG`/`MIGRATION_POLICY_CONFIG`/`FOUNDING_POLICY_CONFIG`), each a
`(classes, schema)` pair mirroring that site's own real `fallback_*`
function's real inputs -- never inventing a feature the deterministic
fallback doesn't already read. `llm/laws.py`'s "which hardship becomes
a law" is deliberately NOT included: it chooses among a DYNAMIC,
per-call candidate set (whichever hardship categories are currently
pressured), not a fixed closed class the way the other five are --
that's a genuinely different (ranking/scoring) problem shape this
module's fixed-class design doesn't fit, flagged as real, distinct
future work rather than forced through.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import LearnResult, LearningSpecialist
from hearthmind.ml.training import TrainingExample

DECISION_POLICY_SCHEMA_VERSION = 1

ENTROPY_FLOOR_DEFAULT = 0.05
"""Same "never argmax" mandate as `GoalPolicy`'s identical constant --
kept as its own copy rather than a shared import, since a future site
may reasonably want a different floor without touching every other
site's tuning."""

OUTCOME_OVERSAMPLE_SCALE = 10
"""Same Phase-2 deterministic-oversampling scale as `GoalPolicy`'s
identical constant -- see that module's docstring for the full
reasoning. Kept as its own copy for the same tuning-independence
reason as the entropy floor above."""


def _apply_entropy_floor(probs: list, floor: float) -> list:
    k = len(probs)
    if k == 0:
        return probs
    reserved = min(floor * k, 1.0)
    scale = 1.0 - reserved
    return [scale * p + floor for p in probs]


@dataclass
class DecisionPrediction:
    distribution: dict = field(default_factory=dict)
    raw_distribution: dict = field(default_factory=dict)

    def argmax(self) -> str:
        return max(self.raw_distribution, key=self.raw_distribution.get)


@dataclass
class DecisionPolicyConfig:
    """One site's real, closed decision shape -- `name` doubles as the
    `kind` tag `to_dict`/`from_dict` reject a mismatched file against,
    so a dispute-trained weights file can never be silently loaded as
    a fission policy or vice versa."""

    name: str
    classes: list
    schema: FeatureSchema


class DecisionPolicy:
    """The generalized `GoalPolicy` -- see this module's own docstring
    for why. `predict`/`sample_class` are the real inference path;
    `learn` is the shared Phase 1/2 training entry point, identical in
    shape to `GoalPolicy.learn`."""

    def __init__(
        self, config: DecisionPolicyConfig, specialist: "LearningSpecialist | None" = None,
        entropy_floor: float = ENTROPY_FLOOR_DEFAULT, seed: int = 0,
    ) -> None:
        self.config = config
        if specialist is None:
            dim = config.schema.dim()
            model = MLP.random_init([dim, max(4, dim), len(config.classes)], output_activation="softmax", seed=seed)
            specialist = LearningSpecialist(model)
        self.specialist = specialist
        self.entropy_floor = entropy_floor

    def _encode(self, state: dict) -> list:
        return FeatureEncoder(self.config.schema).encode(state)

    def predict(self, state: dict, allowed_classes: "set[str] | None" = None) -> DecisionPrediction:
        """Same `allowed_classes` masking contract as `GoalPolicy.
        predict`'s `allowed_goals` -- restricts to a caller-chosen
        subset before the entropy floor, renormalized over just that
        subset, degrading to a uniform draw over the allowed set on a
        genuinely-zero-mass subset rather than crashing. `None` is the
        full unmasked distribution."""
        raw = self.specialist.predict(self._encode(state))
        raw_distribution = dict(zip(self.config.classes, raw))
        if allowed_classes is not None:
            masked = {c: p for c, p in raw_distribution.items() if c in allowed_classes}
            total = sum(masked.values())
            if total > 0:
                raw_distribution = {c: p / total for c, p in masked.items()}
            else:
                raw_distribution = {c: 1.0 / len(masked) for c in masked} if masked else {}
        floored = _apply_entropy_floor(list(raw_distribution.values()), self.entropy_floor)
        return DecisionPrediction(
            distribution=dict(zip(raw_distribution.keys(), floored)),
            raw_distribution=raw_distribution,
        )

    def sample_class(self, state: dict, rng: random.Random, allowed_classes: "set[str] | None" = None) -> str:
        pred = self.predict(state, allowed_classes=allowed_classes)
        classes = list(pred.distribution.keys())
        weights = list(pred.distribution.values())
        return rng.choices(classes, weights=weights, k=1)[0]

    def learn(self, examples: list, holdout_examples: list, tick: int, **kwargs) -> LearnResult:
        kwargs.pop("loss", None)
        return self.specialist.learn(examples, holdout_examples, tick, loss="cross_entropy", **kwargs)

    def to_dict(self) -> dict:
        return {
            "schema_version": DECISION_POLICY_SCHEMA_VERSION,
            "kind": self.config.name,
            "classes": list(self.config.classes),
            "numeric_fields": list(self.config.schema.numeric_fields),
            "categorical_fields": {k: list(v) for k, v in self.config.schema.categorical_fields.items()},
            "model": self.specialist.model.to_dict(),
            "entropy_floor": self.entropy_floor,
        }

    @classmethod
    def from_dict(cls, d: dict, config: DecisionPolicyConfig) -> "DecisionPolicy":
        """`config` must be supplied by the caller (the site-specific
        module below) -- this classmethod only verifies the loaded
        blob genuinely matches it (`kind`/`classes`/schema fields all
        cross-checked), rather than trusting the file to redefine its
        own shape. A mismatch on ANY of these is rejected, not
        silently coerced."""
        if d.get("schema_version") != DECISION_POLICY_SCHEMA_VERSION:
            raise ValueError(f"unsupported decision_policy schema_version={d.get('schema_version')!r}")
        if d.get("kind") != config.name:
            raise ValueError(f"weights file is for {d.get('kind')!r}, not {config.name!r}")
        if list(d.get("classes", [])) != list(config.classes):
            raise ValueError(f"weights file classes {d.get('classes')!r} do not match {config.name!r}'s {config.classes!r}")
        if list(d.get("numeric_fields", [])) != list(config.schema.numeric_fields):
            raise ValueError(f"weights file schema does not match {config.name!r}'s current schema")
        model = MLP.from_dict(d["model"])
        return cls(config, specialist=LearningSpecialist(model), entropy_floor=d.get("entropy_floor", ENTROPY_FLOOR_DEFAULT))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str, config: DecisionPolicyConfig) -> "DecisionPolicy":
        with open(path) as f:
            return cls.from_dict(json.load(f), config)


def build_distillation_examples(config: DecisionPolicyConfig, structured_inputs: list, classes: list) -> list:
    """Phase 1: one `TrainingExample` per real recorded `(structured_
    input, class)` pair, one-hot over `config.classes`. Same "skip a
    value outside the closed set, never coerce it" discipline as
    `goal_policy.build_distillation_examples`."""
    encoder = FeatureEncoder(config.schema)
    examples = []
    for state, cls_value in zip(structured_inputs, classes):
        if cls_value not in config.classes:
            continue
        x = encoder.encode(state)
        y = [1.0 if c == cls_value else 0.0 for c in config.classes]
        examples.append(TrainingExample(x=x, y=y))
    return examples


def reweight_by_outcome(examples: list, outcome_weights: list) -> list:
    """Identical mechanism to `goal_policy.reweight_by_outcome` -- see
    that module's docstring."""
    reweighted = []
    for ex, w in zip(examples, outcome_weights):
        w = max(0.0, min(1.0, w))
        count = max(1, round(w * OUTCOME_OVERSAMPLE_SCALE))
        reweighted.extend([ex] * count)
    return reweighted


# --- Four real site configs -------------------------------------------------
# Each schema mirrors exactly what that site's own real `fallback_*`
# function already reads (see the docstring above for why `laws.py`
# is excluded). Feature names are deliberately generic (`trait_
# ambition`, not `leader_ambition`) so `llm/*.py`'s call sites don't
# need to rename anything they already compute to build a state dict.

DISPUTE_POLICY_CONFIG = DecisionPolicyConfig(
    name="dispute_policy",
    classes=["reconcile", "feud", "council_ruling", "ostracism"],
    schema=FeatureSchema(numeric_fields=[
        "trait_sociability_a", "trait_sociability_b",
        "reputation_a", "reputation_b",
        "rival_factions", "rival_families",
        "debt_a_owes_b", "debt_b_owes_a",
        "council_favors_a", "council_favors_b",
        "has_law_against_feuding", "has_council",
    ]),
)
"""`llm/dispute.py`'s `fallback_dispute` real inputs. `has_council` is
part of the STATE (the network may learn it correlates with `council_
ruling`), but the real structural guarantee that `council_ruling`
never fires when a settlement genuinely has no council comes from
`allowed_classes` masking at the call site (`{"reconcile", "feud",
"ostracism"}` when `has_council` is `False`), exactly the same
"real constraint enforced by masking, not hoped for from training"
discipline `GoalPolicy`'s own `explore` exclusion already established."""

FISSION_POLICY_CONFIG = DecisionPolicyConfig(
    name="fission_policy",
    classes=["stay", "depart"],
    schema=FeatureSchema(numeric_fields=["trait_ambition", "trait_openness", "crowding_ratio"]),
)
"""`llm/fission.py`'s `fallback_decision` real inputs -- ambition/
openness plus a derived `crowding_ratio = members / housing_capacity`
(the real pressure signal the deterministic fallback doesn't read
today but the LLM prompt already surfaces, `members`/`housing_
capacity` -- a policy CAN learn from it even though the hand-written
fallback never did)."""

MIGRATION_POLICY_CONFIG = DecisionPolicyConfig(
    name="migration_policy",
    classes=["stay", "depart"],
    schema=FeatureSchema(numeric_fields=["trait_resilience", "trait_openness", "standing_penalty"]),
)
"""`llm/migration.py`'s `fallback_decision` real inputs."""

FOUNDING_POLICY_CONFIG = DecisionPolicyConfig(
    name="founding_policy",
    classes=["decline", "found"],
    schema=FeatureSchema(numeric_fields=["trait_ambition", "master_count"]),
)
"""`llm/founding.py`'s `fallback_founding` real inputs."""
