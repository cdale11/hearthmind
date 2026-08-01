#!/usr/bin/env python3
"""Standalone verification for B8 (Predictive scheduling) and the new
cross-run training-data pooling primitive
(docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B; hearthmind/ml/
cross_run.py). Same convention as every sibling scripts/verify_*.py:
no unittest, no CI pipeline, run manually.
"""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.ml.cross_run import pool_examples_across_runs, discover_runs
from hearthmind.simulation.forecasting import (
    ForecastAccuracyTracker,
    WorkloadForecaster,
    is_quiet_window,
    make_training_example,
    plan_reservation,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_discover_runs():
    with tempfile.TemporaryDirectory() as root:
        check("discover_runs: empty root returns no runs", discover_runs(root) == [])
        for name in ["run_c", "run_a", "run_b"]:
            os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, "not_a_dir.txt"), "w") as f:
            f.write("x")
        runs = discover_runs(root)
        check("discover_runs: finds every run subdirectory, sorted", runs == ["run_a", "run_b", "run_c"], str(runs))

    check("discover_runs: nonexistent root returns [] rather than raising", discover_runs("/no/such/path/at/all") == [])


def check_pool_examples_across_runs():
    with tempfile.TemporaryDirectory() as root:
        for i, name in enumerate(["run_1", "run_2", "run_3"]):
            os.makedirs(os.path.join(root, name))

        def loader(run_dir):
            run_name = os.path.basename(run_dir)
            n = {"run_1": 5, "run_2": 50, "run_3": 5}[run_name]
            return [f"{run_name}-{i}" for i in range(n)]

        pooled, stats = pool_examples_across_runs(root, loader, seed=1)
        check("pool: uses every run", stats.runs_used == 3)
        check("pool: total examples is the sum across runs", stats.examples_total == 60, str(stats.examples_total))
        check(
            "pool: examples from every run are present without a cap",
            any(x.startswith("run_1-") for x in pooled)
            and any(x.startswith("run_2-") for x in pooled)
            and any(x.startswith("run_3-") for x in pooled),
        )

        pooled_capped, stats_capped = pool_examples_across_runs(root, loader, max_per_run=5, seed=2)
        check(
            "pool: max_per_run caps a large run down to the same size as small ones",
            stats_capped.examples_per_run["run_2"] == 5,
            str(stats_capped.examples_per_run),
        )
        check("pool: total reflects per-run capping", stats_capped.examples_total == 15, str(stats_capped.examples_total))

        pooled_total_capped, stats_tc = pool_examples_across_runs(root, loader, max_total=10, seed=3)
        check("pool: max_total caps the final combined pool", len(pooled_total_capped) == 10)
        check("pool: stats.examples_total matches the actual returned pool size", stats_tc.examples_total == 10)

        def flaky_loader(run_dir):
            run_name = os.path.basename(run_dir)
            if run_name == "run_2":
                raise ValueError("corrupted archive")
            return [1, 2, 3]

        _, stats_flaky = pool_examples_across_runs(root, flaky_loader)
        check("pool: a run whose loader raises is skipped, not fatal", stats_flaky.runs_failed == 1 and "run_2" in stats_flaky.failed_run_ids)
        check("pool: the other two runs still contribute despite one failure", stats_flaky.runs_used == 2)


def _synth_workload_example(rng):
    # Synthetic ground truth: call volume rises with backlog and
    # active disasters, roughly matching B8.1's own worked examples
    # (a storm approaching predicts a dialogue/cognition spike). Every
    # numeric feature is kept on a normalized ~[0, 1] scale -- a real
    # forecaster's inputs would be fractions/rates, not raw unbounded
    # counts, and plain SGD (no batch-norm/Adam) is measurably unstable
    # once inputs and targets sit on wildly different scales than the
    # weight init assumes (verified directly: raw 0-10-scale backlog
    # against a 0-28 target diverges to NaN even at a tiny learning
    # rate; this normalized scale converges cleanly at lr=0.02).
    backlog = rng.uniform(0, 1)
    disaster = float(rng.random() < 0.3)
    volume = 2.0 * backlog + 3.0 * disaster + rng.uniform(-0.1, 0.1)
    features = {
        "current_backlog": backlog,
        "recent_dialogue_rate": rng.uniform(0, 1),
        "recent_cognition_rate": rng.uniform(0, 1),
        "active_disaster": disaster,
        "festival_scheduled": 0.0,
        "season": "autumn",
    }
    return make_training_example(features, volume)


def check_workload_forecaster_learns_from_pooled_examples():
    rng = random.Random(5)
    examples = [_synth_workload_example(rng) for _ in range(300)]
    forecaster = WorkloadForecaster.new(seed=1)
    loss_before = forecaster.evaluate(examples)
    forecaster.train(examples, epochs=80, learning_rate=0.02, seed=1)
    loss_after = forecaster.evaluate(examples)
    check(
        "workload forecaster: training substantially reduces loss on its own synthetic data",
        loss_after < loss_before * 0.2,
        f"before={loss_before:.3f} after={loss_after:.3f}",
    )

    high_disaster_pred = forecaster.predict(
        {"current_backlog": 0.5, "recent_dialogue_rate": 0.2, "recent_cognition_rate": 0.2,
         "active_disaster": 1.0, "festival_scheduled": 0.0, "season": "autumn"}
    )
    low_pred = forecaster.predict(
        {"current_backlog": 0.5, "recent_dialogue_rate": 0.2, "recent_cognition_rate": 0.2,
         "active_disaster": 0.0, "festival_scheduled": 0.0, "season": "autumn"}
    )
    check(
        "workload forecaster: correctly learned that an active disaster raises predicted load",
        high_disaster_pred > low_pred,
        f"disaster={high_disaster_pred:.2f} no_disaster={low_pred:.2f}",
    )


def check_workload_forecaster_trains_on_cross_run_pool():
    # The "learn from all previous runs" requirement, end to end: three
    # synthetic past-run directories, each with its own recorder-shaped
    # loader, pooled and trained on together.
    rng = random.Random(11)
    with tempfile.TemporaryDirectory() as root:
        for name in ["run_a", "run_b", "run_c"]:
            os.makedirs(os.path.join(root, name))

        def loader(run_dir):
            return [_synth_workload_example(rng) for _ in range(80)]

        pooled, stats = pool_examples_across_runs(root, loader, seed=4)
        check("cross-run training: pooled examples come from all three archived runs", stats.runs_used == 3)

        forecaster = WorkloadForecaster.new(seed=2)
        loss_before = forecaster.evaluate(pooled)
        forecaster.train(pooled, epochs=60, learning_rate=0.02, seed=2)
        loss_after = forecaster.evaluate(pooled)
        check(
            "cross-run training: a forecaster trained on the cross-run pool genuinely learns",
            loss_after < loss_before * 0.2,
            f"before={loss_before:.3f} after={loss_after:.3f}",
        )


def check_forecast_accuracy_tracker():
    accurate = ForecastAccuracyTracker()
    rng = random.Random(3)
    for _ in range(30):
        actual = rng.uniform(5, 15)
        accurate.record(predicted=actual + rng.uniform(-0.2, 0.2), actual=actual)
    check("accuracy tracker: an accurate forecaster gets a high reliability weight", accurate.reliability_weight() > 0.8, str(accurate.reliability_weight()))

    wrong = ForecastAccuracyTracker()
    for _ in range(30):
        actual = rng.uniform(5, 15)
        wrong.record(predicted=actual + rng.uniform(20, 30), actual=actual)
    check("accuracy tracker: a consistently-wrong forecaster gets a low reliability weight", wrong.reliability_weight() < 0.3, str(wrong.reliability_weight()))

    fresh = ForecastAccuracyTracker()
    check("accuracy tracker: a fresh tracker with no history defaults to full trust", fresh.reliability_weight() == 1.0)

    bounded = ForecastAccuracyTracker(history_size=5)
    for i in range(20):
        bounded.record(predicted=float(i), actual=float(i))
    check("accuracy tracker: history stays bounded", len(bounded._pairs) == 5)


def check_plan_reservation():
    check("plan_reservation: scales with predicted load", plan_reservation(10.0, 20, 1.0) > plan_reservation(2.0, 20, 1.0))
    check("plan_reservation: scales with reliability", plan_reservation(10.0, 20, 1.0) > plan_reservation(10.0, 20, 0.3))
    check("plan_reservation: never exceeds current capacity", plan_reservation(1000.0, 5, 1.0) == 5)
    check("plan_reservation: zero reliability reserves nothing", plan_reservation(10.0, 20, 0.0) == 0)
    check("plan_reservation: never negative", plan_reservation(-5.0, 20, 1.0) == 0)


def check_is_quiet_window():
    check("is_quiet_window: consistently low load is quiet", is_quiet_window([1, 2, 1, 2], capacity=20, threshold_fraction=0.3))
    check("is_quiet_window: a single high reading breaks quiet", not is_quiet_window([1, 2, 19, 2], capacity=20, threshold_fraction=0.3))
    check("is_quiet_window: empty history is never quiet", not is_quiet_window([], capacity=20))
    check("is_quiet_window: zero capacity is never quiet", not is_quiet_window([1, 2], capacity=0))


def main():
    check_discover_runs()
    check_pool_examples_across_runs()
    check_workload_forecaster_learns_from_pooled_examples()
    check_workload_forecaster_trains_on_cross_run_pool()
    check_forecast_accuracy_tracker()
    check_plan_reservation()
    check_is_quiet_window()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
