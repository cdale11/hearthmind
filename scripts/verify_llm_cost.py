#!/usr/bin/env python3
"""Standalone verification for Tier 6's L3.1, the LLM cost regressor
(hearthmind/ml/llm_cost.py). Same convention as every sibling
scripts/verify_*.py: no unittest, no CI pipeline, run manually.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.ml.llm_cost import (
    LLM_COST_SCHEMA,
    LLM_COST_TASKS,
    CostPredictionAccuracyTracker,
    LLMCostRegressor,
    make_training_example,
    should_preflight_defer,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_schema():
    check("schema has a real numeric dimension", LLM_COST_SCHEMA.dim() > len(LLM_COST_SCHEMA.numeric_fields))
    check("task vocabulary is non-empty and closed", len(LLM_COST_TASKS) >= 5)
    check("cognition/dialogue are covered (highest real call volume)",
          "cognition" in LLM_COST_TASKS and "dialogue" in LLM_COST_TASKS)


def check_encoder_degrades_gracefully():
    ex = make_training_example(
        {"task": "not_a_real_task", "prompt_chars_k": 0.1, "context_chars_k": 0.05,
         "current_backlog_fraction": 0.5, "concurrency_limit": 2, "deep_reasoning": 0.0},
        observed_latency_ms=1200.0,
    )
    check("unrecognized task never raises, produces a real vector",
          len(ex.x) == LLM_COST_SCHEMA.dim())
    check("training example y carries the real observed latency, LATENCY_SCALE_MS-scaled",
          ex.y == [1.2])


def synthetic_dataset(rng, n):
    """A real, learnable synthetic relationship: latency scales with
    prompt/context size and backlog, is much higher for deep_reasoning
    calls, and varies by task -- close to the real world's own shape
    (a large deep_reasoning call under backlog pressure genuinely does
    take longer) without needing a real archive. Feature/target scales
    deliberately mirror the small-magnitude convention `LLM_COST_
    SCHEMA`/`LATENCY_SCALE_MS` document -- an earlier draft of this
    dataset used raw char counts and millisecond targets directly and
    reliably diverged the SGD trainer to NaN (the same bug class
    CLAUDE.md's v1.34.174 entry already documents), fixed by scaling
    here rather than by further lowering the learning rate alone."""
    examples = []
    for _ in range(n):
        task = rng.choice(LLM_COST_TASKS)
        prompt_chars_k = rng.uniform(0.2, 3.0)
        context_chars_k = rng.uniform(0.0, 2.0)
        backlog = rng.uniform(0.0, 1.0)
        concurrency = rng.choice([1, 2, 4])
        deep_reasoning = 1.0 if rng.random() < 0.2 else 0.0
        base = 0.8 + (prompt_chars_k + context_chars_k) * 0.15 + backlog * 4.0
        base += deep_reasoning * 15.0
        base -= (concurrency - 1) * 0.3
        noise = rng.uniform(-0.2, 0.2)
        latency_ms = max(50.0, (base + noise) * 1000.0)
        features = {
            "task": task, "prompt_chars_k": prompt_chars_k, "context_chars_k": context_chars_k,
            "current_backlog_fraction": backlog, "concurrency_limit": float(concurrency),
            "deep_reasoning": deep_reasoning,
        }
        examples.append((features, latency_ms))
    return examples


def check_training_reduces_loss():
    rng = random.Random(42)
    raw = synthetic_dataset(rng, 300)
    train_raw, holdout_raw = raw[:240], raw[240:]
    train_examples = [make_training_example(f, y) for f, y in train_raw]
    holdout_examples = [make_training_example(f, y) for f, y in holdout_raw]

    model = LLMCostRegressor.new(seed=1)
    loss_before = model.evaluate(holdout_examples)
    model.train(train_examples, epochs=120, learning_rate=0.001, seed=1)
    loss_after = model.evaluate(holdout_examples)
    check("training measurably cuts held-out loss on synthetic data",
          loss_after < loss_before * 0.5,
          f"before={loss_before:.1f} after={loss_after:.1f}")


def check_prediction_direction():
    """The load-bearing check: a trained model should predict a HIGHER
    latency for a large deep_reasoning call under heavy backlog than
    for a small ordinary call under an empty queue -- not byte-exact
    parity with the synthetic generator, just the right direction."""
    rng = random.Random(7)
    raw = synthetic_dataset(rng, 400)
    train_examples = [make_training_example(f, y) for f, y in raw]
    model = LLMCostRegressor.new(seed=2)
    model.train(train_examples, epochs=150, learning_rate=0.001, seed=2)

    heavy = model.predict({
        "task": "beliefs", "prompt_chars_k": 2.8, "context_chars_k": 1.8,
        "current_backlog_fraction": 0.95, "concurrency_limit": 1.0, "deep_reasoning": 1.0,
    })
    light = model.predict({
        "task": "naming", "prompt_chars_k": 0.25, "context_chars_k": 0.0,
        "current_backlog_fraction": 0.05, "concurrency_limit": 4.0, "deep_reasoning": 0.0,
    })
    check("a heavy deep_reasoning call under backlog predicts higher latency than a light one",
          heavy > light, f"heavy={heavy:.1f} light={light:.1f}")


def check_accuracy_tracker():
    tracker = CostPredictionAccuracyTracker()
    check("fresh tracker defaults to full trust (no evidence either way)",
          tracker.reliability_weight() == 1.0)

    good = CostPredictionAccuracyTracker()
    for i in range(30):
        actual = 1000.0 + i * 10
        good.record(predicted_ms=actual + 5.0, actual_ms=actual)
    check("a consistently-accurate tracker scores near-full reliability",
          good.reliability_weight() > 0.9)

    bad = CostPredictionAccuracyTracker()
    rng = random.Random(3)
    for i in range(30):
        actual = 1000.0 + i * 10
        bad.record(predicted_ms=actual + rng.uniform(-2000, 2000), actual_ms=actual)
    check("a noisy/unreliable tracker scores measurably lower than the accurate one",
          bad.reliability_weight() < good.reliability_weight())

    always_mean = CostPredictionAccuracyTracker()
    actuals = [1000.0 + i * 37 % 500 for i in range(20)]
    mean_actual = sum(actuals) / len(actuals)
    for a in actuals:
        always_mean.record(predicted_ms=mean_actual, actual_ms=a)
    check("'always predict the mean' scores ~0 reliability (it IS the baseline)",
          abs(always_mean.reliability_weight()) < 0.05,
          f"got {always_mean.reliability_weight()}")


def check_should_preflight_defer():
    check("never defers with zero reliability regardless of prediction",
          not should_preflight_defer(50000.0, 0.99, 0.0, elevated_latency_ms=5000.0))
    check("never defers a fast-predicted call even under heavy backlog",
          not should_preflight_defer(1000.0, 0.99, 1.0, elevated_latency_ms=5000.0))
    check("never defers a slow-predicted call on an idle queue",
          not should_preflight_defer(50000.0, 0.1, 1.0, elevated_latency_ms=5000.0))
    check("defers a genuinely slow, reliable prediction under real backlog pressure",
          should_preflight_defer(50000.0, 0.95, 1.0, elevated_latency_ms=5000.0))
    check("a low-reliability prediction is scaled down and may no longer clear the bar",
          not should_preflight_defer(6000.0, 0.95, 0.1, elevated_latency_ms=5000.0))


def main():
    check_schema()
    check_encoder_degrades_gracefully()
    check_training_reduces_loss()
    check_prediction_direction()
    check_accuracy_tracker()
    check_should_preflight_defer()

    total = len(FAILURES)
    print()
    if total:
        print(f"{total} check(s) FAILED: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
