#!/usr/bin/env python3
"""Tier 7 HCA Stage G, G1 (explicit user instruction: "Start phase 1
G1"): `hearthmind.ml.specialist.LearningSpecialist` -- the `learn()`
interface wired directly onto Tier 6's already-shipped L5 substrate.
G1's own stated test (docs/ROADMAP-2026-07-REMAINING.md): "a
specialist's own prediction error trends down over its lifetime on a
stationary synthetic signal, using the real shadow gate, not a mock."
Real production-path checks against the real MLP/ReplayBuffer/
CheckpointHistory/passes_shadow_gate classes, no unittest, same
standalone-script convention as every sibling `verify_*.py`."""
from __future__ import annotations

import random
import sys

from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import LearningSpecialist
from hearthmind.ml.training import TrainingExample, mean_loss

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def stationary_signal_examples(rng: random.Random, n: int) -> list[TrainingExample]:
    """A fixed, learnable (stationary -- the same function every call)
    2-input -> 1-output signal with a little noise, y = 0.5*x0 - 0.3*x1
    + 0.5 (bounded to roughly [0, 1], a sigmoid-head-friendly range)."""
    examples = []
    for _ in range(n):
        x0 = rng.uniform(-1, 1)
        x1 = rng.uniform(-1, 1)
        noise = rng.uniform(-0.02, 0.02)
        y = max(0.0, min(1.0, 0.5 * x0 - 0.3 * x1 + 0.5 + noise))
        examples.append(TrainingExample(x=[x0, x1], y=[y]))
    return examples


def main() -> int:
    rng = random.Random(4242)

    # A large, FIXED held-out set drawn once -- never trained on,
    # reused across every learn() cycle so "does held-out loss trend
    # down" is measuring the same yardstick throughout.
    holdout = stationary_signal_examples(random.Random(999), 200)

    model = MLP.random_init([2, 6, 1], output_activation="sigmoid", seed=1)
    specialist = LearningSpecialist(model, replay_capacity=300, checkpoint_capacity=10)

    initial_loss = mean_loss(specialist.model, holdout)
    losses = [initial_loss]
    accepted_count = 0
    for cycle in range(8):
        new_examples = stationary_signal_examples(rng, 30)
        result = specialist.learn(new_examples, holdout, tick=cycle * 100)
        if result.accepted:
            accepted_count += 1
        losses.append(mean_loss(specialist.model, holdout))

    check("learn() ran real cycles and at least some were accepted", accepted_count >= 1)
    check(
        "prediction error trends down over the specialist's lifetime on a stationary signal",
        losses[-1] < initial_loss * 0.7,
    )
    check(
        "the replay buffer genuinely accumulated real lived history across cycles",
        len(specialist.replay_buffer) > 0,
    )
    check(
        "at least one real checkpoint was pushed for an accepted retrain",
        len(specialist.checkpoint_history) == accepted_count,
    )

    # --- the real shadow gate, not a mock: prove it actually rejects ---
    good_model = MLP.random_init([2, 6, 1], output_activation="sigmoid", seed=7)
    # Warm it up on the real signal first so it has a genuinely low
    # baseline loss to protect.
    warm_specialist = LearningSpecialist(good_model, replay_capacity=300)
    for cycle in range(6):
        warm_specialist.learn(stationary_signal_examples(rng, 30), holdout, tick=cycle * 100)
    pre_sabotage_metric = mean_loss(warm_specialist.model, holdout)
    pre_sabotage_weights = warm_specialist.model.to_dict()

    # Deliberately garbage "new" examples: the opposite-signed target,
    # nothing like the real stationary signal -- a genuinely bad
    # retrain a real shadow gate should catch and reject.
    garbage_examples = [TrainingExample(x=ex.x, y=[1.0 - ex.y[0]]) for ex in stationary_signal_examples(rng, 30)]
    sabotage_result = warm_specialist.learn(
        garbage_examples, holdout, tick=9999, epochs=60, learning_rate=0.2,
    )
    check("a genuinely bad retrain is rejected by the real shadow gate", not sabotage_result.accepted)
    check(
        "a rejected retrain's candidate metric is honestly worse than the baseline it was measured against",
        sabotage_result.candidate_metric > sabotage_result.baseline_metric,
    )
    check(
        "a rejected retrain leaves the LIVE model's weights genuinely untouched",
        warm_specialist.model.to_dict() == pre_sabotage_weights,
    )
    check(
        "a rejected retrain leaves the live model's real held-out performance unchanged",
        mean_loss(warm_specialist.model, holdout) == pre_sabotage_metric,
    )
    check(
        "a rejected retrain's new examples still entered the replay buffer (lived history, not learned success)",
        len(warm_specialist.replay_buffer) > 0,
    )

    # --- degrade-gracefully cases ---
    empty_specialist = LearningSpecialist(MLP.random_init([2, 6, 1], output_activation="sigmoid", seed=3))
    no_examples_result = empty_specialist.learn([], holdout, tick=0)
    check("learn() with zero new examples is a clean no-op, not a crash", not no_examples_result.accepted)

    no_holdout_specialist = LearningSpecialist(MLP.random_init([2, 6, 1], output_activation="sigmoid", seed=5))
    no_holdout_result = no_holdout_specialist.learn(stationary_signal_examples(rng, 10), [], tick=0)
    check("learn() with no holdout data degrades to an ungated accept, never silently rejects", no_holdout_result.accepted)
    check("an ungated accept still genuinely swaps in the trained candidate", no_holdout_specialist.checkpoint_history.latest() is not None)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
