#!/usr/bin/env python3
"""Verify the fix for a real live-deployment crash: a long soak's
`SimulationEngine._maybe_tick_workload_forecaster` -> `LearningSpecialist.
learn` -> `mean_loss` -> `mse_loss` raised `OverflowError: (34,
'Numerical result out of range')` from `(p - t) ** 2` once the
`WorkloadForecaster`'s weights had genuinely diverged over many real
retrain cycles -- crashing the whole `uvicorn`/asyncio process, not
just failing one LLM call the way every other fallback path in this
codebase degrades.

Two independent pieces, both real production code paths:

1. `hearthmind/ml/training.py`'s `mse_loss`/`cross_entropy_loss` are
   hardened against overflow/NaN -- `mean_loss` (and therefore
   `LearningSpecialist.learn`'s shadow gate) can now never crash on a
   diverged model; it correctly reads `float("inf")`, which `passes_
   shadow_gate` already treats as strictly worse than any finite
   baseline.
2. The actual root cause -- `WORKLOAD_FORECAST_SCHEMA`'s raw,
   un-normalized real-valued counts (`current_backlog`/`recent_
   dialogue_rate`/`recent_cognition_rate`/`observed_call_volume`)
   feeding plain SGD against `MLP.random_init`'s near-unit-input-scale
   assumption, the same bug class already fixed once for `llm/
   llm_cost.py` (v1.34.174) -- is fixed at the source: `Simulation
   Engine._maybe_tick_workload_forecaster` now divides every one of
   these by `WORKLOAD_FEATURE_SCALE` before it ever reaches the
   model.

No unittest, same standalone-script convention as every sibling
`verify_*.py`. Run: python3 scripts/verify_ml_loss_overflow_guard.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from hearthmind.ml.lifelong import passes_shadow_gate
from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import LearningSpecialist
from hearthmind.ml.training import (
    TrainingExample,
    cross_entropy_loss,
    mean_loss,
    mse_loss,
    train_mlp_sgd,
)

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


@check("mse_loss: parity with the plain (p-t)**2 formula on ordinary values")
def _():
    pred, target = [0.3, 0.7, -0.2], [0.5, 0.6, 0.1]
    reference = sum((p - t) ** 2 for p, t in zip(pred, target)) / max(1, len(pred))
    assert abs(mse_loss(pred, target) - reference) < 1e-12


@check("mse_loss: the exact live-crash reproduction no longer raises, returns inf")
def _():
    # This is the literal shape that raised in production: a
    # large-but-finite prediction whose square exceeds a Python
    # float's range via `**`, but not via plain multiplication.
    try:
        (1e200 - 0.0) ** 2
        raise AssertionError("expected this environment's Python to reproduce the OverflowError")
    except OverflowError:
        pass  # confirms the bug class is real on this interpreter before testing the fix
    result = mse_loss([1e200, -1e250], [0.0, 0.0])
    assert result == float("inf"), result


@check("mse_loss: NaN prediction degrades to inf, never a propagated NaN")
def _():
    result = mse_loss([float("nan"), 0.5], [0.0, 0.5])
    assert result == float("inf"), result


@check("mse_loss: an already-inf prediction is handled without raising")
def _():
    result = mse_loss([float("inf"), 0.5], [0.0, 0.5])
    assert result == float("inf"), result


@check("cross_entropy_loss: parity with the reference formula")
def _():
    import math
    pred, target = [0.7, 0.2, 0.1], [1.0, 0.0, 0.0]
    reference = -sum(t * math.log(max(p, 1e-12)) for p, t in zip(pred, target))
    assert abs(cross_entropy_loss(pred, target) - reference) < 1e-12


@check("cross_entropy_loss: NaN input degrades to inf")
def _():
    result = cross_entropy_loss([float("nan"), 0.2, 0.1], [1.0, 0.0, 0.0])
    assert result == float("inf"), result


@check("passes_shadow_gate: an inf candidate metric is correctly rejected against any finite baseline")
def _():
    assert passes_shadow_gate(candidate_metric=float("inf"), baseline_metric=5.0) is False
    assert passes_shadow_gate(candidate_metric=0.5, baseline_metric=5.0) is True


@check("mean_loss: a genuinely diverged model produces inf, not a crash, through the real call path")
def _():
    model = MLP.random_init([2, 4, 1], output_activation="linear", seed=0)
    # Force the exact failure mode: manually diverge the weights to the
    # same order of magnitude the live incident's model reached, then
    # confirm the real mean_loss() -> mse_loss() call path (not a
    # hand-rolled stand-in) survives it.
    for layer in model.layers:
        for row in layer.weights:
            for i in range(len(row)):
                row[i] *= 1e120
    examples = [TrainingExample(x=[1.0, 1.0], y=[0.0])]
    result = mean_loss(model, examples)
    assert result == float("inf"), result


def _realistic_examples(scale: float, n: int = 20, seed: int = 0) -> list:
    """A `WORKLOAD_FORECAST_SCHEMA`-shaped synthetic dataset with real
    variety across examples (unlike a single repeated point, which
    behaves like unstochastic full-batch descent and is pathologically
    prone to diverge regardless of scale/learning rate -- not
    representative of the real accumulated `_workload_training_
    examples`, which span many different days/backlog states)."""
    import random as _random
    rng = _random.Random(seed)
    examples = []
    for _ in range(n):
        backlog = rng.uniform(0, 20)
        dialogue = rng.uniform(0, 40)
        cognition = rng.uniform(0, 40)
        y = backlog * 1.5 + dialogue * 0.8 + cognition * 0.9 + rng.uniform(-5, 5)
        examples.append(TrainingExample(
            x=[backlog / scale, dialogue / scale, cognition / scale, 0.0, 0.0, 1.0],
            y=[y / scale],
        ))
    return examples


@check("headline: un-normalized (raw scale, default lr=0.03) training genuinely diverges to overflow")
def _():
    # Reproduces the ROOT CAUSE, not just the symptom: WORKLOAD_FORECAST_
    # SCHEMA's raw counts fed directly into MLP.random_init's near-
    # unit-input-scale weight init, trained with plain SGD at
    # LearningSpecialist.learn's own SHARED default learning_rate=0.03
    # -- the exact combination that diverged in the live incident.
    model = MLP.random_init([6, 6, 1], output_activation="linear", seed=0)
    raw_examples = _realistic_examples(scale=1.0)
    train_mlp_sgd(model, raw_examples, epochs=20, learning_rate=0.03, seed=0)
    loss = mean_loss(model, raw_examples)
    assert loss == float("inf"), f"expected raw-scale/default-lr training to diverge, got {loss}"


@check("headline: the real fix (WORKLOAD_FEATURE_SCALE input normalization + WORKLOAD_LEARNING_RATE) stays stable, single cycle")
def _():
    # The real, both-pieces fix this incident needed -- scale alone
    # (still using lr=0.03) was measured NOT sufficient on its own; see
    # the next check for why lr alone isn't the whole story either.
    from hearthmind.simulation.engine import WORKLOAD_FEATURE_SCALE, WORKLOAD_LEARNING_RATE

    model = MLP.random_init([6, 6, 1], output_activation="linear", seed=0)
    scaled_examples = _realistic_examples(scale=WORKLOAD_FEATURE_SCALE)
    train_mlp_sgd(model, scaled_examples, epochs=20, learning_rate=WORKLOAD_LEARNING_RATE, seed=0)
    loss = mean_loss(model, scaled_examples)
    assert loss != float("inf") and loss == loss, f"diverged (loss={loss})"
    assert loss < 10.0, f"unexpectedly large loss ({loss}) for the real fixed configuration"


@check("headline: scale alone (still at the shared default lr=0.03) is measurably NOT sufficient -- the lowered learning rate is load-bearing")
def _():
    from hearthmind.simulation.engine import WORKLOAD_FEATURE_SCALE

    model = MLP.random_init([6, 6, 1], output_activation="linear", seed=0)
    scaled_examples = _realistic_examples(scale=WORKLOAD_FEATURE_SCALE)
    train_mlp_sgd(model, scaled_examples, epochs=20, learning_rate=0.03, seed=0)
    loss = mean_loss(model, scaled_examples)
    assert loss == float("inf"), (
        "expected scale-only (default lr=0.03) to still diverge on this dataset -- "
        f"if this now passes with a finite loss ({loss}), WORKLOAD_LEARNING_RATE's "
        "own docstring claim ('lowering LR alone did not fix it... scale alone "
        "wasn't sufficient either') needs re-checking against whatever changed"
    )


@check("headline: the real fixed configuration stays stable across many warm-started retrain cycles (a real multi-year soak's worth)")
def _():
    from hearthmind.simulation.engine import WORKLOAD_FEATURE_SCALE, WORKLOAD_LEARNING_RATE

    model = MLP.random_init([6, 6, 1], output_activation="linear", seed=0)
    for cycle in range(60):  # ~60 simulated monthly retrains, roughly 5 real years
        examples = _realistic_examples(scale=WORKLOAD_FEATURE_SCALE, seed=cycle)
        train_mlp_sgd(model, examples, epochs=20, learning_rate=WORKLOAD_LEARNING_RATE, seed=cycle)
        loss = mean_loss(model, examples)
        assert loss != float("inf") and loss == loss, f"diverged at cycle {cycle} (loss={loss})"


@check("end-to-end: LearningSpecialist.learn()'s real shadow gate rejects a sabotaged candidate that diverges to overflow, without crashing")
def _():
    # A well-behaved live model (finite baseline_metric), sabotaged with
    # wildly-wrong targets at a magnitude that genuinely drives the
    # CANDIDATE (not the baseline) to numeric divergence -- the real
    # shape of the live incident: the candidate's own holdout evaluation
    # is what crashed, not the starting model.
    model = MLP.random_init([2, 3, 1], output_activation="linear", seed=0)
    specialist = LearningSpecialist(model, replay_capacity=20, checkpoint_capacity=5)
    good_examples = [TrainingExample(x=[0.5, 0.5], y=[0.5]) for _ in range(10)]
    holdout = [TrainingExample(x=[0.5, 0.5], y=[0.5]) for _ in range(5)]
    # Establish a real, finite, reasonably-fit baseline first.
    baseline_result = specialist.learn(good_examples, holdout, tick=0, epochs=40, learning_rate=0.05)
    assert baseline_result.candidate_metric != float("inf")
    live_weights_before = specialist.model.to_dict()
    # A sabotaged retrain at a magnitude large enough to diverge the
    # candidate during its own 40-epoch training (garbage targets, high
    # learning rate) -- this is the exact "candidate overflows during
    # its own holdout evaluation" shape the live incident hit.
    sabotage_examples = [TrainingExample(x=[1.0, 1.0], y=[1e30]) for _ in range(10)]
    result = specialist.learn(sabotage_examples, holdout, tick=1, epochs=40, learning_rate=0.5)
    assert result.accepted is False, f"a diverged candidate must be rejected (candidate_metric={result.candidate_metric}, baseline_metric={result.baseline_metric})"
    assert specialist.model.to_dict() == live_weights_before, "a rejected candidate must never mutate the live model"


def main():
    failures = []
    for name, fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append((name, exc))
            print(f"[FAIL] {name}: {exc}")
    print(f"\n{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
