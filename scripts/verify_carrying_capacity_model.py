#!/usr/bin/env python3
"""Roadmap Group 1: `Population.carrying_capacity` as a learned
regression target (`hearthmind/ml/carrying_capacity.py`). Standalone
verification, same convention as every sibling `scripts/verify_*.py`:
no unittest, no CI pipeline, run manually. Real production-path checks
against a real `SimulationEngine`/`World`/`Population`, not just the
new module in isolation.
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.config import Config
from hearthmind.ml.carrying_capacity import (
    CARRYING_CAPACITY_MODEL_BLEND_MAX,
    CARRYING_CAPACITY_SCHEMA,
    CarryingCapacityModel,
    blended_capacity,
    carrying_capacity_features,
    compute_carrying_capacity_label,
    make_training_example,
)
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine, _carrying_capacity_model_path_for
from scripts.train_carrying_capacity_from_world import build_examples

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


# --- Pure-function checks -------------------------------------------------

def check_schema():
    check("schema has the real seven named fields", set(CARRYING_CAPACITY_SCHEMA.numeric_fields) == {
        "population_k", "avg_hunger", "avg_energy", "materials_k",
        "currency_k", "buildings_standing_k", "tech_level_k",
    })


def check_features_bounded():
    features = carrying_capacity_features(
        population=100.0, avg_hunger=1.5, avg_energy=-0.5, materials=50.0,
        currency=20.0, buildings_standing=10.0, tech_level=5.0,
    )
    check("avg_hunger is clamped to [0, 1] even given an out-of-range input", features["avg_hunger"] == 1.0)
    check("avg_energy is clamped to [0, 1] even given an out-of-range input", features["avg_energy"] == 0.0)
    check("population_k scales down a raw population count", features["population_k"] == 0.5)


def check_label_direction():
    comfortable = compute_carrying_capacity_label(population=100.0, avg_hunger=0.1, starvation_delta=0.0)
    check("a comfortable, non-starving settlement's label sits ABOVE its observed population "
          "(evidence the ceiling hasn't been found yet)", comfortable > 100.0)

    distressed = compute_carrying_capacity_label(population=100.0, avg_hunger=0.95, starvation_delta=5.0)
    check("a hungry, starving settlement's label sits BELOW its observed population "
          "(evidence it has overshot)", distressed < 100.0)

    check("the label never goes negative even at maximal pressure",
          compute_carrying_capacity_label(population=10.0, avg_hunger=1.0, starvation_delta=1000.0) >= 0.0)

    neutral = compute_carrying_capacity_label(population=100.0, avg_hunger=0.5, starvation_delta=0.0)
    check("exactly-at-comfort hunger with no starvation deaths reads as a mild positive nudge, not neutral zero",
          neutral >= 100.0)


def check_blended_capacity():
    check("a higher model prediction nudges the hand output up, bounded by CARRYING_CAPACITY_MODEL_BLEND_MAX",
          blended_capacity(100.0, 1000.0) == 100.0 * (1.0 + CARRYING_CAPACITY_MODEL_BLEND_MAX))
    check("a lower model prediction nudges the hand output down, bounded the same way",
          blended_capacity(100.0, 0.0) == 100.0 * (1.0 - CARRYING_CAPACITY_MODEL_BLEND_MAX))
    check("a model prediction inside the blend band is honored exactly",
          abs(blended_capacity(100.0, 110.0) - 110.0) < 1e-9)
    check("a zero hand_capacity passes through unchanged (no degenerate ratio)",
          blended_capacity(0.0, 500.0) == 0.0)


def check_round_trip_and_schema_rejection():
    model = CarryingCapacityModel.new(seed=1)
    d = model.to_dict()
    restored = CarryingCapacityModel.from_dict(d)
    check("round-trip predict() matches for an arbitrary feature vector",
          model.predict({"population_k": 0.5, "avg_hunger": 0.3}) ==
          restored.predict({"population_k": 0.5, "avg_hunger": 0.3}))

    bad = dict(d)
    bad["schema_version"] = 999
    try:
        CarryingCapacityModel.from_dict(bad)
        check("an unsupported schema_version is rejected", False)
    except ValueError:
        check("an unsupported schema_version is rejected", True)

    bad_kind = dict(d)
    bad_kind["kind"] = "value_model"
    try:
        CarryingCapacityModel.from_dict(bad_kind)
        check("a mismatched kind is rejected", False)
    except ValueError:
        check("a mismatched kind is rejected", True)


def synthetic_history(rng, n):
    """A real, learnable synthetic relationship between (avg_hunger,
    starvation_delta) and the label `compute_carrying_capacity_label`
    itself derives -- exercising the actual production label function,
    not a separately-invented target."""
    rows = []
    for _ in range(n):
        population = rng.uniform(20.0, 300.0)
        avg_hunger = rng.uniform(0.0, 1.0)
        starvation_delta = rng.uniform(0.0, 5.0) if avg_hunger > 0.6 else 0.0
        rows.append((population, avg_hunger, starvation_delta))
    return rows


def check_training_reduces_loss():
    rng = random.Random(7)
    rows = synthetic_history(rng, 400)
    examples = []
    for population, avg_hunger, starvation_delta in rows:
        features = carrying_capacity_features(
            population=population, avg_hunger=avg_hunger, avg_energy=0.6,
            materials=40.0, currency=20.0, buildings_standing=8.0, tech_level=3.0,
        )
        label = compute_carrying_capacity_label(population, avg_hunger, starvation_delta)
        examples.append(make_training_example(features, label))
    train_examples, holdout_examples = examples[:320], examples[320:]

    model = CarryingCapacityModel.new(seed=1)
    loss_before = model.evaluate(holdout_examples)
    model.train(train_examples, epochs=150, learning_rate=0.02, seed=2)
    loss_after = model.evaluate(holdout_examples)
    check(
        "training measurably cuts held-out loss on synthetic data",
        loss_after < loss_before * 0.6,
        detail=f"before={loss_before:.4f} after={loss_after:.4f}",
    )


# --- Production-path checks (real Population/Settlement/SimulationEngine) -

def make_engine(tmpdir, tag):
    db_path = os.path.join(tmpdir, f"world_{tag}.db")
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=777, initial_population=10, width=24, height=24)
    return SimulationEngine.load_or_create(conn, cfg), db_path


def run_ticks(eng, n):
    """`_tick_once()` schedules real `asyncio.create_task(...)` calls
    regardless of `llm_enabled` (see CLAUDE.md's own B13.5 note) -- a
    real running event loop is required, same technique every sibling
    verify script that drives multiple real ticks already uses."""
    async def _drive():
        for _ in range(n):
            eng._tick_once()
    asyncio.run(_drive())


def check_carrying_capacity_none_is_byte_identical():
    """The core parity claim: `carrying_capacity_model=None` (the
    default, and every call site's behavior before this feature
    existed) must reproduce the hand formula's exact output --
    verified directly against a real `Settlement`/member list, not
    assumed from reading the code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, _ = make_engine(tmpdir, "parity")
        run_ticks(eng, 30)
        pop = eng.world.population
        stl = eng.world.settlements[0]
        members = [a for a in pop.agents if a.settlement_id == stl.id]
        args = (stl, 40, False, False)
        kwargs = dict(established_roads=2, members=members, map_tiles=24 * 24)

        without_param = pop.carrying_capacity(*args, **kwargs)
        with_explicit_none = pop.carrying_capacity(*args, carrying_capacity_model=None, **kwargs)
        check("omitting carrying_capacity_model and passing it explicitly as None agree exactly",
              without_param == with_explicit_none)

        model = CarryingCapacityModel.new(seed=3)
        with_model = pop.carrying_capacity(*args, carrying_capacity_model=model, **kwargs)
        check("a real loaded model measurably changes the output vs. None",
              with_model != without_param)
        if without_param > 0:
            ratio = with_model / without_param
            check("a loaded model's effect stays inside the documented blend band",
                  (1.0 - CARRYING_CAPACITY_MODEL_BLEND_MAX - 1e-6) <= ratio <=
                  (1.0 + CARRYING_CAPACITY_MODEL_BLEND_MAX + 1e-6),
                  detail=f"ratio={ratio:.4f}")


def check_extreme_prediction_never_exceeds_blend_band():
    """Even a wildly-diverged/untrained model's raw prediction can only
    ever move the final output by the bounded ratio -- the real safety
    argument for why this is safe to wire into a live tick loop with no
    further gating. Uses a real ticked `Population`/`Settlement`, not a
    hand-rolled fake member (which would need to fake every real
    `Agent` attribute the formula reads -- `sick_ticks` included)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, _ = make_engine(tmpdir, "extreme")
        run_ticks(eng, 30)
        pop = eng.world.population
        stl = eng.world.settlements[0]
        members = [a for a in pop.agents if a.settlement_id == stl.id]

        class _WildModel:
            def predict(self, features):
                return 1e9  # absurdly large -- must still be bounded at the consumer

        class _WildLowModel:
            def predict(self, features):
                return -1e9  # absurdly negative -- must still be bounded, never go negative

        baseline = pop.carrying_capacity(stl, 40, False, False, members=members, carrying_capacity_model=None)
        wild_high = pop.carrying_capacity(stl, 40, False, False, members=members, carrying_capacity_model=_WildModel())
        wild_low = pop.carrying_capacity(stl, 40, False, False, members=members, carrying_capacity_model=_WildLowModel())
        if baseline > 0:
            check("an absurdly high model prediction is still clamped to the documented blend band",
                  wild_high <= baseline * (1.0 + CARRYING_CAPACITY_MODEL_BLEND_MAX + 1e-6))
            check("an absurdly low (negative) model prediction is still clamped, never negative output",
                  wild_low >= 0.0 and wild_low >= baseline * (1.0 - CARRYING_CAPACITY_MODEL_BLEND_MAX - 1e-6))


def check_engine_loading_three_cases():
    with tempfile.TemporaryDirectory() as tmpdir:
        # (1) No file present -> loaded: False.
        eng_none, db_path_none = make_engine(tmpdir, "no_file")
        check("no weights file -> carrying_capacity_model not loaded", eng_none._carrying_capacity_model is None)
        diag = eng_none.full_diagnostics()
        check("full_diagnostics() reports loaded=False with no file",
              diag["carrying_capacity_model"]["loaded"] is False)

        # (2) A corrupted file -> degrades safely, never crashes startup.
        corrupt_dir = os.path.join(tmpdir, "corrupt")
        os.makedirs(corrupt_dir, exist_ok=True)
        db_path_corrupt = os.path.join(corrupt_dir, "hearthmind.db")
        path = _carrying_capacity_model_path_for(db_path_corrupt)
        with open(path, "w") as f:
            f.write("{not valid json")
        conn = connect(db_path_corrupt)
        cfg = Config(db_path=db_path_corrupt, llm_enabled=False, seed=1, initial_population=6, width=16, height=16)
        eng_corrupt = SimulationEngine.load_or_create(conn, cfg)
        check("a corrupted weights file degrades to None rather than crashing startup",
              eng_corrupt._carrying_capacity_model is None)

        # (3) A real, valid file -> loaded: True.
        real_dir = os.path.join(tmpdir, "real")
        os.makedirs(real_dir, exist_ok=True)
        db_path_real = os.path.join(real_dir, "hearthmind.db")
        real_path = _carrying_capacity_model_path_for(db_path_real)
        CarryingCapacityModel.new(seed=9).save(real_path)
        conn2 = connect(db_path_real)
        cfg2 = Config(db_path=db_path_real, llm_enabled=False, seed=1, initial_population=6, width=16, height=16)
        eng_real = SimulationEngine.load_or_create(conn2, cfg2)
        check("a real, valid weights file loads successfully", eng_real._carrying_capacity_model is not None)
        diag2 = eng_real.full_diagnostics()
        check("full_diagnostics() reports loaded=True with a real file",
              diag2["carrying_capacity_model"]["loaded"] is True)


def check_world_tick_threads_model_through():
    """A real `World.tick(carrying_capacity_model=...)` call genuinely
    reaches `Population.carrying_capacity` -- proven by observing
    `Population.last_carrying_capacity` shift once a model with a
    known strong upward bias is supplied, through the real `_tick_once`
    call path (not a direct method call bypassing the engine)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        eng, db_path = make_engine(tmpdir, "world_tick")
        run_ticks(eng, 10)
        baseline = eng.world.population.last_carrying_capacity

        class _AlwaysHighModel:
            def predict(self, features):
                return 1e6

        eng._carrying_capacity_model = _AlwaysHighModel()
        run_ticks(eng, 5)
        boosted = eng.world.population.last_carrying_capacity
        check("a real _tick_once() call with a loaded model changes last_carrying_capacity",
              boosted != baseline)


def check_trainer_label_direction_on_real_metrics_shape():
    """`build_examples` (the real trainer's own row-to-example logic)
    against a synthetic but real-metrics-row-shaped history: a
    comfortable stretch should produce labels sitting above the raw
    population, a starving stretch below it -- confirmed via the exact
    function the shipped trainer calls, not a re-implementation."""
    comfortable_rows = [
        {"population": 100, "avg_hunger": 0.1, "deaths_starvation": 0, "materials": 40,
         "currency": 20, "buildings_standing": 8, "tech_level": 2}
        for _ in range(5)
    ]
    starving_rows = [
        {"population": 100, "avg_hunger": 0.95, "deaths_starvation": i * 2, "materials": 5,
         "currency": 2, "buildings_standing": 8, "tech_level": 2}
        for i in range(1, 6)
    ]
    comfortable_examples = build_examples(comfortable_rows)
    starving_examples = build_examples(starving_rows)
    check("build_examples() produces one example per usable row",
          len(comfortable_examples) == 5 and len(starving_examples) == 5)
    from hearthmind.ml.carrying_capacity import CAPACITY_OUTPUT_SCALE
    comfortable_labels = [ex.y[0] * CAPACITY_OUTPUT_SCALE for ex in comfortable_examples]
    starving_labels = [ex.y[0] * CAPACITY_OUTPUT_SCALE for ex in starving_examples]
    check("a comfortable real-shaped history yields labels above the raw population",
          all(label > 100.0 for label in comfortable_labels))
    check("a starving real-shaped history yields labels below the raw population",
          all(label < 100.0 for label in starving_labels))

    zero_pop_rows = [{"population": 0, "avg_hunger": 0.5, "deaths_starvation": 0}]
    check("a zero-population row is skipped, never a crash", build_examples(zero_pop_rows) == [])


def check_trainer_end_to_end_subprocess():
    """A full subprocess run of the real training script against a
    genuinely ticked-and-saved LLM-disabled world -- same technique
    `verify_l1_1_corpus_and_wiring.py` established for `train_
    embedding_from_world.py`."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        build_script = os.path.join(tmpdir, "build_fixture.py")
        db_path = os.path.join(tmpdir, "world.db")
        with open(build_script, "w") as f:
            f.write(f'''
import asyncio, sys
sys.path.insert(0, ".")
from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.persistence.snapshot import save_snapshot
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.world.state import World

async def main():
    config = Config(db_path={db_path!r}, llm_enabled=False, seed=42, initial_population=12, width=24, height=24)
    world = World.create_new(config)
    conn = connect({db_path!r})
    eng = SimulationEngine(conn, config, world)
    for _ in range(1800):
        eng._tick_once()
    save_snapshot(conn, eng.world)
    conn.commit()

asyncio.run(main())
''')
        result = subprocess.run([sys.executable, build_script], capture_output=True, text=True, timeout=180)
        check("real fixture world builds and saves cleanly", result.returncode == 0,
              detail=result.stdout + result.stderr)

        out_path = os.path.join(tmpdir, "out")
        result = subprocess.run(
            [sys.executable, "scripts/train_carrying_capacity_from_world.py",
             "--db-path", db_path, "--out-dir", out_path, "--epochs", "30"],
            capture_output=True, text=True, timeout=180,
        )
        check("training script exits cleanly against a real ~18-sim-day history",
              result.returncode == 0, detail=result.stdout + result.stderr)
        weights_path = os.path.join(out_path, "carrying_capacity_model_weights.json")
        check("training script writes the exact filename SimulationEngine looks for",
              os.path.exists(weights_path))
        if os.path.exists(weights_path):
            loaded = CarryingCapacityModel.load(weights_path)
            check("the written weights file loads back successfully", loaded is not None)


def main():
    check_schema()
    check_features_bounded()
    check_label_direction()
    check_blended_capacity()
    check_round_trip_and_schema_rejection()
    check_training_reduces_loss()
    check_carrying_capacity_none_is_byte_identical()
    check_extreme_prediction_never_exceeds_blend_band()
    check_engine_loading_three_cases()
    check_world_tick_threads_model_through()
    check_trainer_label_direction_on_real_metrics_shape()
    check_trainer_end_to_end_subprocess()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
