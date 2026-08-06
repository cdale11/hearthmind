#!/usr/bin/env python3
"""Tier 7 HCA Stage G, G2 (explicit user instruction: "Build G2"):
B8.1/L3.2's `WorkloadForecaster` wired to a real, live, monthly
shadow-gated retrain cadence via G1's `LearningSpecialist` --
`SimulationEngine._maybe_tick_workload_forecaster`.

G2's own stated test (docs/ROADMAP-2026-07-REMAINING.md): "closes
three previously-separate flagged gaps at once ... wire the FIRST real
specialist to G1." Verified here as real production-path checks
against a real `SimulationEngine`/`World` -- driving the actual clock
forward through real day_end/month_end boundaries and calling the
actual registered method, not a synthetic stand-in. No unittest, same
standalone-script convention as every sibling `verify_*.py`.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.ml.specialist import LearningSpecialist
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    WORKLOAD_FEATURE_SCALE,
    WORKLOAD_MIN_EXAMPLES_TO_RETRAIN,
    WORKLOAD_PENDING_SAMPLES_MAX,
    WORKLOAD_SAMPLE_HORIZON_DAYS,
    SimulationEngine,
)
from hearthmind.simulation.forecasting import ForecastAccuracyTracker, WorkloadForecaster

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, db_name: str = "g2.db") -> SimulationEngine:
    db_path = f"{tmpdir}/{db_name}"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=1,
        initial_population=5, width=32, height=32,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def ticks_per_day(eng: SimulationEngine) -> int:
    return eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick


def advance_to_day_end(eng: SimulationEngine, calls_this_day: int = 0) -> None:
    """Drives real `_maybe_tick_workload_forecaster` calls directly
    (the real method the tick loop dispatches to), advancing the real
    clock and `_cognition_runner.calls_attempted` by a caller-chosen
    amount first -- so the resolved `observed_call_volume` is a real,
    known, checkable delta, not a guess."""
    eng.world.clock.tick_count += ticks_per_day(eng)
    eng._cognition_runner.calls_attempted += calls_this_day
    eng._maybe_tick_workload_forecaster(["day_end"])


def advance_to_month_end(eng: SimulationEngine, calls_this_day: int = 0) -> None:
    eng.world.clock.tick_count += ticks_per_day(eng)
    eng._cognition_runner.calls_attempted += calls_this_day
    eng._maybe_tick_workload_forecaster(["day_end", "month_end"])


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # --- 1. non-day_end tick is a genuine no-op -----------------
        eng = make_engine(tmpdir, "g2_noop.db")
        before_pending = len(eng._workload_pending_samples)
        eng._maybe_tick_workload_forecaster([])
        check("non-day_end tick never samples", len(eng._workload_pending_samples) == before_pending)

        # --- 2. a day_end tick samples real state --------------------
        eng = make_engine(tmpdir, "g2_sample.db")
        check("starts with zero pending samples", len(eng._workload_pending_samples) == 0)
        advance_to_day_end(eng, calls_this_day=3)
        check("one real sample recorded after day_end", len(eng._workload_pending_samples) == 1)
        check("daily counters reset after sampling", eng._cognition_calls_today == 0 and eng._dialogue_calls_today == 0)

        # --- 3. pending samples are bounded --------------------------
        eng = make_engine(tmpdir, "g2_bound.db")
        for _ in range(WORKLOAD_PENDING_SAMPLES_MAX + 10):
            advance_to_day_end(eng, calls_this_day=1)
        check(
            "pending samples never exceed WORKLOAD_PENDING_SAMPLES_MAX",
            len(eng._workload_pending_samples) <= WORKLOAD_PENDING_SAMPLES_MAX,
        )

        # --- 4. a sample resolves into a real training example once
        #        its horizon has genuinely elapsed, with the REAL
        #        observed call-volume delta -----------------------------
        eng = make_engine(tmpdir, "g2_resolve.db")
        advance_to_day_end(eng, calls_this_day=0)
        check("no training example before the horizon elapses", len(eng._workload_training_examples) == 0)
        # the real observed call-volume delta is whatever happens DURING
        # the horizon window, after the sample was taken -- not before it.
        for _ in range(WORKLOAD_SAMPLE_HORIZON_DAYS):
            advance_to_day_end(eng, calls_this_day=7)
        check("a real training example forms once the horizon elapses", len(eng._workload_training_examples) == 1)
        # the resolved example's y must equal the real observed delta,
        # normalized by WORKLOAD_FEATURE_SCALE (the divergence-hardening
        # fix, docs/DECISIONS.md -- the target is trained/compared in
        # this SAME scale as the input features, never raw call counts).
        expected_delta = (7.0 * WORKLOAD_SAMPLE_HORIZON_DAYS) / WORKLOAD_FEATURE_SCALE
        resolved_y = eng._workload_training_examples[0].y[0]
        check(f"resolved example's target matches the real scaled delta (got {resolved_y}, expected {expected_delta})", resolved_y == expected_delta)
        check("accuracy tracker recorded a real (predicted, actual) pair", eng._workload_accuracy_tracker.mean_absolute_error() is not None)

        # --- 5. real accuracy math against ForecastAccuracyTracker
        #        (a direct check the same class engine.py wires in) ----
        tracker = ForecastAccuracyTracker()
        tracker.record(predicted=5.0, actual=5.0)
        tracker.record(predicted=5.0, actual=5.0)
        tracker.record(predicted=5.0, actual=5.0)
        tracker.record(predicted=5.0, actual=5.0)
        tracker.record(predicted=5.0, actual=5.0)
        check("a perfectly accurate tracker reads zero MAE", tracker.mean_absolute_error() == 0.0)

        # --- 6. no retrain fires before month_end, even with plenty
        #        of banked examples -------------------------------------
        eng = make_engine(tmpdir, "g2_no_early_retrain.db")
        eng._workload_training_examples = list(range(WORKLOAD_MIN_EXAMPLES_TO_RETRAIN + 5))  # type: ignore[list-item]
        eng.world.clock.tick_count += ticks_per_day(eng)
        eng._maybe_tick_workload_forecaster(["day_end"])
        check("no retrain attempt logged on a non-month_end day", len(eng._workload_learn_log) == 0)

        # --- 7. no retrain fires with too few banked examples, even
        #        on a real month_end -------------------------------------
        eng = make_engine(tmpdir, "g2_too_few.db")
        eng.world.clock.tick_count += ticks_per_day(eng)
        eng._maybe_tick_workload_forecaster(["day_end", "month_end"])
        check("no retrain attempt logged with too few banked examples", len(eng._workload_learn_log) == 0)

        # --- 8. a real month_end WITH enough banked examples fires a
        #        real learn() cycle through LearningSpecialist, and the
        #        forecaster's model is kept in sync afterward -----------
        eng = make_engine(tmpdir, "g2_retrain.db")
        from hearthmind.simulation.forecasting import WORKLOAD_FORECAST_SCHEMA, make_training_example
        base_features = {
            "current_backlog": 0.0, "recent_dialogue_rate": 2.0, "recent_cognition_rate": 3.0,
            "active_disaster": 0.0, "festival_scheduled": 0.0, "season": "spring",
        }
        eng._workload_training_examples = [
            make_training_example(base_features, 5.0) for _ in range(WORKLOAD_MIN_EXAMPLES_TO_RETRAIN + 5)
        ]
        model_before = eng._workload_forecaster.model
        eng.world.clock.tick_count += ticks_per_day(eng)
        eng._maybe_tick_workload_forecaster(["day_end", "month_end"])
        check("a real learn() attempt was logged on month_end with enough examples", len(eng._workload_learn_log) == 1)
        check("training examples reset after a retrain attempt", len(eng._workload_training_examples) == 0)
        check(
            "forecaster's live model stays in sync with the specialist's model",
            eng._workload_forecaster.model is eng._workload_specialist.model,
        )
        entry = eng._workload_learn_log[0]
        check("learn log entry carries a real accepted/reason verdict", "accepted" in entry and isinstance(entry["reason"], str))
        del model_before  # not asserted on directly -- acceptance may or may not swap it in

        # --- 9. the real shadow gate provably REJECTS a retrain that
        #        would regress the live model's held-out metric --------
        specialist = LearningSpecialist(WorkloadForecaster.new(seed=7).model, replay_capacity=50, checkpoint_capacity=5)
        good_examples = [make_training_example(base_features, 5.0) for _ in range(30)]
        holdout = [make_training_example(base_features, 5.0) for _ in range(20)]
        # give the specialist a real, reasonably-fit baseline first
        specialist.learn(good_examples, holdout, tick=0, epochs=80, learning_rate=0.05)
        live_weights_before = specialist.model.to_dict()
        # a deliberately sabotaged retrain: garbage, wildly wrong targets
        sabotage_examples = [make_training_example(base_features, -999.0) for _ in range(30)]
        result = specialist.learn(sabotage_examples, holdout, tick=1, epochs=80, learning_rate=0.05)
        check("the sabotaged retrain was rejected by the real shadow gate", result.accepted is False)
        check(
            "the live model's weights are byte-identical after a rejected retrain",
            specialist.model.to_dict() == live_weights_before,
        )

        # --- 10. full_diagnostics() surfaces real forecaster state,
        #         not a placeholder ---------------------------------------
        eng = make_engine(tmpdir, "g2_diag.db")
        advance_to_day_end(eng, calls_this_day=2)
        diag = eng.full_diagnostics()
        wf = diag.get("workload_forecaster")
        check("full_diagnostics() carries a workload_forecaster section", wf is not None)
        check("diagnostics report the real pending-sample count", wf["pending_samples"] == len(eng._workload_pending_samples))
        check("diagnostics report the real banked-examples count", wf["training_examples_banked"] == len(eng._workload_training_examples))

        # --- 11. WORKLOAD_FORECAST_SCHEMA's real season field lines up
        #         with SimClock.season() -----------------------------------
        eng = make_engine(tmpdir, "g2_season.db")
        check(
            "SimClock.season() is a legal WORKLOAD_FORECAST_SCHEMA categorical value",
            eng.world.clock.season in WORKLOAD_FORECAST_SCHEMA.categorical_fields["season"],
        )

        # --- 12. a real 3000-tick production run never crashes with
        #         the new job registered in _TICK_JOBS -------------------
        eng = make_engine(tmpdir, "g2_soak.db")

        async def run_soak() -> None:
            for _ in range(3000):
                eng._tick_once()
                await asyncio.sleep(0)

        asyncio.run(run_soak())
        check("a 3000-tick production run with the new job live never crashes", True)
        check(
            "the new job actually ran during the soak (real samples/examples accumulated)",
            len(eng._workload_pending_samples) + len(eng._workload_training_examples) > 0,
        )

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
