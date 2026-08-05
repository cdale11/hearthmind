#!/usr/bin/env python3
"""Standalone verification for L2.2 (hearthmind/ml/goal_policy.py) --
the goal policy -- plus the softmax+cross-entropy training support it
needed from hearthmind/ml/training.py. No unittest, per this project's
standing "verification is live diagnostics + ad-hoc scripts" rule.
Run: python3 scripts/verify_ml_l2_2_goal_policy.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.ml.goal_policy import (  # noqa: E402
    GOAL_VALUES,
    GoalPolicy,
    build_distillation_examples,
    build_policy_model,
    reweight_by_outcome,
)
from hearthmind.ml.primitives import MLP  # noqa: E402
from hearthmind.ml.specialist import LearningSpecialist  # noqa: E402
from hearthmind.ml.training import (  # noqa: E402
    TrainingExample,
    cross_entropy_loss,
    mean_loss,
    train_mlp_sgd,
)

CHECKS = []


def check(name, condition):
    CHECKS.append((name, bool(condition)))
    print(f"[{'OK' if condition else 'FAIL'}] {name}")


def main():
    # 1. cross_entropy_loss: hand-computed.
    loss = cross_entropy_loss([0.7, 0.2, 0.1], [1.0, 0.0, 0.0])
    check(
        "cross_entropy_loss matches -log(p_true) by hand",
        abs(loss - (-__import__("math").log(0.7))) < 1e-9,
    )
    check(
        "cross_entropy_loss never raises on a zero-probability true class",
        cross_entropy_loss([1.0, 0.0], [0.0, 1.0]) > 20.0,  # clamped, huge but finite
    )

    # 2. train_mlp_sgd rejects cross_entropy on a non-softmax head.
    bad_model = MLP.random_init([3, 2], output_activation="sigmoid")
    rejected = False
    try:
        train_mlp_sgd(bad_model, [TrainingExample(x=[0, 0, 0], y=[1, 0])], loss="cross_entropy", epochs=1)
    except ValueError:
        rejected = True
    check("train_mlp_sgd rejects loss='cross_entropy' on a non-softmax head", rejected)

    # 3. A real softmax classifier trained with cross-entropy separates
    #    two linearly-separable classes -- proves the new backward pass
    #    is actually correct, not just accepted without error.
    rng = random.Random(0)
    examples = []
    for _ in range(200):
        if rng.random() < 0.5:
            x = [rng.uniform(0.8, 1.0), rng.uniform(0.0, 0.2)]
            y = [1.0, 0.0]
        else:
            x = [rng.uniform(0.0, 0.2), rng.uniform(0.8, 1.0)]
            y = [0.0, 1.0]
        examples.append(TrainingExample(x=x, y=y))
    clf = MLP.random_init([2, 6, 2], output_activation="softmax", seed=1)
    before = mean_loss(clf, examples, loss="cross_entropy")
    train_mlp_sgd(clf, examples, epochs=80, learning_rate=0.2, loss="cross_entropy", seed=1)
    after = mean_loss(clf, examples, loss="cross_entropy")
    check(
        f"cross-entropy SGD cuts loss on a separable toy problem ({before:.3f} -> {after:.3f})",
        after < before * 0.3,
    )
    correct = sum(
        1 for ex in examples
        if (clf.forward(ex.x).index(max(clf.forward(ex.x)))) == ex.y.index(max(ex.y))
    )
    check(
        f"trained softmax classifier gets >90% accuracy on its own training set ({correct}/{len(examples)})",
        correct / len(examples) > 0.9,
    )

    # 4. build_policy_model / encode_agent_state shapes.
    model = build_policy_model(hidden_dims=(8,), seed=0)
    check("build_policy_model output dim matches len(GOAL_VALUES)", model.layers[-1].out_dim == len(GOAL_VALUES))
    x = model.forward([0.0] * model.layers[0].in_dim)
    check("a fresh policy model's forward pass sums to ~1.0 (softmax)", abs(sum(x) - 1.0) < 1e-9)

    # 5. Entropy floor: every class stays above the floor, always.
    policy = GoalPolicy(specialist=LearningSpecialist(build_policy_model(seed=2)), entropy_floor=0.05)
    state = {"hunger": 0.1, "energy": 0.9, "trait_ambition": 0.9}
    pred = policy.predict(state)
    check(
        "entropy floor: every goal's floored probability >= the configured floor",
        all(p >= 0.05 - 1e-9 for p in pred.distribution.values()),
    )
    check(
        "entropy floor: floored distribution still sums to 1.0",
        abs(sum(pred.distribution.values()) - 1.0) < 1e-9,
    )

    # Sampling never collapses to a single goal across many draws even
    # against an artificially over-confident raw distribution.
    overconfident = GoalPolicy(entropy_floor=0.1)
    # Force near-certainty by hand-crafting weights that saturate one class.
    for layer in overconfident.specialist.model.layers[-1:]:
        for row in layer.weights:
            for i in range(len(row)):
                row[i] = 0.0
        layer.bias[0] = 50.0  # class 0 (WANDER) saturates softmax
        for i in range(1, len(layer.bias)):
            layer.bias[i] = 0.0
    seen = set()
    r = random.Random(3)
    for _ in range(500):
        seen.add(overconfident.sample_goal(state, r))
    check(
        f"entropy floor: repeated sampling against a saturated policy still visits >1 goal ({sorted(seen)})",
        len(seen) > 1,
    )

    # 6. Personality conditioning: train on trait-correlated synthetic
    #    data, confirm two different trait vectors predict differently.
    training_examples = []
    for _ in range(300):
        ambition = rng.uniform(0.6, 1.0) if rng.random() < 0.5 else rng.uniform(-1.0, -0.2)
        state_i = {"hunger": 0.1, "energy": 0.9, "trait_ambition": ambition}
        goal = "gather" if ambition > 0 else "socialize"
        training_examples.append((state_i, goal))
    dist_examples = build_distillation_examples(
        [s for s, _ in training_examples], [g for _, g in training_examples],
    )
    check(
        "build_distillation_examples produces one example per real (state, goal) pair",
        len(dist_examples) == len(training_examples),
    )
    trained_policy = GoalPolicy(specialist=LearningSpecialist(build_policy_model(seed=4)), entropy_floor=0.0)
    result = trained_policy.learn(dist_examples, holdout_examples=[], tick=100)
    check("phase-1 distillation learn() reports accepted", result.accepted)

    ambitious_pred = trained_policy.predict({"hunger": 0.1, "energy": 0.9, "trait_ambition": 0.9})
    sociable_pred = trained_policy.predict({"hunger": 0.1, "energy": 0.9, "trait_ambition": -0.9})
    check(
        "personality conditioning: high-ambition state predicts 'gather' most",
        ambitious_pred.argmax() == "gather",
    )
    check(
        "personality conditioning: high-sociability(-ambition) state predicts 'socialize' most",
        sociable_pred.argmax() == "socialize",
    )
    check(
        "the SAME shared network gives genuinely different distributions per personality",
        ambitious_pred.raw_distribution != sociable_pred.raw_distribution,
    )

    # 7. Unrecognized goal values are skipped, not fabricated as a class.
    skip_examples = build_distillation_examples(
        [{"hunger": 0.0}, {"hunger": 0.0}], ["wander", "not_a_real_goal"],
    )
    check("build_distillation_examples skips an unrecognized goal value", len(skip_examples) == 1)

    # 8. Phase 2 outcome reweighting: a good-outcome example is
    #    oversampled far more than a bad-outcome one, deterministically.
    base = [TrainingExample(x=[1.0], y=[1.0, 0.0]), TrainingExample(x=[2.0], y=[0.0, 1.0])]
    reweighted = reweight_by_outcome(base, [1.0, 0.0])
    good_count = sum(1 for ex in reweighted if ex.x == [1.0])
    bad_count = sum(1 for ex in reweighted if ex.x == [2.0])
    check(
        f"outcome reweighting oversamples the good-outcome example ({good_count} vs {bad_count})",
        good_count > bad_count,
    )
    check("outcome reweighting never fully erases a bad-outcome example", bad_count >= 1)
    check(
        "outcome reweighting is deterministic (same weights -> same counts)",
        reweight_by_outcome(base, [1.0, 0.0]) == reweighted,
    )

    # 9. Headline test -- phase 2 lets the student diverge from and
    #    exceed a systematically-wrong teacher. Build a dataset where
    #    the "teacher" (recorded goal) is WRONG half the time for a
    #    specific state, but the realized outcome tells us which half
    #    was actually right -- confirm outcome-reweighted training
    #    shifts the policy toward the outcome-preferred answer, away
    #    from blind imitation of the noisy teacher label.
    wrong_teacher_examples = []
    outcome_weights = []
    r2 = random.Random(5)
    for _ in range(100):
        state_i = {"hunger": 0.2, "energy": 0.8}
        # Teacher alternates between two labels for the identical state
        # (a genuinely noisy/sometimes-wrong recorded judgment).
        if r2.random() < 0.5:
            goal = "gather"
            outcome = 0.9  # this call led to a good realized outcome
        else:
            goal = "wander"
            outcome = 0.1  # this call led to a poor realized outcome
        wrong_teacher_examples.append((state_i, goal))
        outcome_weights.append(outcome)

    imitation_only = build_distillation_examples(
        [s for s, _ in wrong_teacher_examples], [g for _, g in wrong_teacher_examples],
    )
    pure_imitation_policy = GoalPolicy(specialist=LearningSpecialist(build_policy_model(seed=9)), entropy_floor=0.0)
    pure_imitation_policy.learn(imitation_only, holdout_examples=[], tick=1)
    imitation_pred = pure_imitation_policy.predict({"hunger": 0.2, "energy": 0.8})

    refined_examples = reweight_by_outcome(imitation_only, outcome_weights)
    refined_policy = GoalPolicy(specialist=LearningSpecialist(build_policy_model(seed=9)), entropy_floor=0.0)
    refined_policy.learn(refined_examples, holdout_examples=[], tick=1)
    refined_pred = refined_policy.predict({"hunger": 0.2, "energy": 0.8})

    check(
        f"headline: outcome-refined P(gather)={refined_pred.raw_distribution['gather']:.3f} "
        f"exceeds pure-imitation P(gather)={imitation_pred.raw_distribution['gather']:.3f} "
        "(the student learns to prefer the outcome that actually worked)",
        refined_pred.raw_distribution["gather"] > imitation_pred.raw_distribution["gather"],
    )

    print()
    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
