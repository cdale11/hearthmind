#!/usr/bin/env python3
"""Verifies roadmap Phase 2's L6: the real yearly evolutionary cadence
for the workload forecaster's own hyperparameters
(`SimulationEngine._maybe_evolve_workload_genomes`, wired onto
`hearthmind.ml.evolution`'s already-shipped `GenomePopulation`/G4
`train_and_score_genome_via_specialist`). No unittest, same
`@check`-decorator standalone convention as every sibling
`verify_*.py`. Run:

    python3 scripts/verify_l6_workload_genome_evolution.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, ".")

from hearthmind.config import Config
from hearthmind.ml.evolution import ModelGenome
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    WORKLOAD_FORECASTER_HIDDEN_DIM, WORKLOAD_GENOME_MIN_EXAMPLES, WORKLOAD_GENOME_MU,
    WORKLOAD_GENOME_POPULATION_SIZE, WORKLOAD_LEARNING_RATE, SimulationEngine,
)
from hearthmind.simulation.forecasting import make_training_example
from hearthmind.world.state import World

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


def _make_engine(seed: int = 3, sim_minutes_per_tick: int | None = None) -> SimulationEngine:
    d = tempfile.mkdtemp()
    db_path = f"{d}/world.sqlite3"
    kwargs = {}
    if sim_minutes_per_tick is not None:
        kwargs["sim_minutes_per_tick"] = sim_minutes_per_tick
    cfg = Config(db_path=db_path, width=20, height=20, seed=seed, llm_enabled=False, **kwargs)
    conn = connect(db_path)
    world = World.create_new(cfg)
    return SimulationEngine(conn, cfg, world)


def _synthetic_examples(n: int, backlog: float = 0.1, call_volume: float = 5.0) -> list:
    return [
        make_training_example(
            {
                "current_backlog": backlog, "recent_dialogue_rate": 0.1, "recent_cognition_rate": 0.1,
                "active_disaster": 0.0, "festival_scheduled": 0.0, "season": "spring",
            },
            call_volume,
        )
        for _ in range(n)
    ]


@check("__init__: a real GenomePopulation is seeded with the configured size/species")
def check_population_seeded():
    eng = _make_engine()
    pop = eng._workload_genome_population
    return (
        pop.species == "workload_forecaster"
        and len(pop.genomes) == WORKLOAD_GENOME_POPULATION_SIZE
        and pop.mu == WORKLOAD_GENOME_MU
    )


@check("__init__: overrides start at the exact pre-L6 constants (byte-identical default behavior)")
def check_overrides_default_to_original_constants():
    eng = _make_engine()
    return eng._workload_learning_rate_override == WORKLOAD_LEARNING_RATE and eng._workload_epochs_override == 20


@check("_maybe_evolve_workload_genomes: no-op on a non-year_end event, even with enough examples")
def check_noop_non_year_end():
    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 5)
    eng._maybe_evolve_workload_genomes(["month_end"])
    return len(eng._workload_genome_evolve_log) == 0


@check("_maybe_evolve_workload_genomes: no-op below WORKLOAD_GENOME_MIN_EXAMPLES")
def check_noop_below_min_examples():
    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES - 1)
    eng._maybe_evolve_workload_genomes(["year_end"])
    return len(eng._workload_genome_evolve_log) == 0


@check("_maybe_evolve_workload_genomes: a real generation fires and logs exactly one entry")
def check_real_generation_fires():
    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 10)
    eng._maybe_evolve_workload_genomes(["year_end"])
    if len(eng._workload_genome_evolve_log) != 1:
        return False
    entry = eng._workload_genome_evolve_log[0]
    return set(entry.keys()) == {
        "tick", "adopted", "best_genome_id", "best_fitness", "live_fitness",
        "learning_rate", "epochs", "population_size",
    }


@check("this job does NOT clear _workload_training_examples (only the monthly retrain owns that)")
def check_does_not_clear_training_examples():
    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 10)
    before = len(eng._workload_training_examples)
    eng._maybe_evolve_workload_genomes(["year_end"])
    return len(eng._workload_training_examples) == before


@check("population size never changes across multiple real generations")
def check_population_size_stable_across_generations():
    eng = _make_engine()
    for _ in range(4):
        eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 10)
        eng._maybe_evolve_workload_genomes(["year_end"])
    return len(eng._workload_genome_population.genomes) == WORKLOAD_GENOME_POPULATION_SIZE


@check("a genuinely fitter evolved genome IS adopted over a deliberately-worse live baseline")
def check_fitter_genome_is_adopted():
    """Isolates the ADOPTION LOGIC from real training-dynamics noise by
    monkeypatching `train_and_score_genome_via_specialist` (imported
    directly into `simulation.engine`'s namespace) with a fixed,
    genome-id-keyed fitness table -- the same technique this codebase's
    own sibling scripts already use to test comparison/gating logic
    deterministically rather than hoping real SGD produces a big enough
    gap on trivial synthetic data."""
    import hearthmind.simulation.engine as engine_mod

    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 10)
    eng._workload_learning_rate_override = 0.05
    eng._workload_epochs_override = 5
    good = ModelGenome(
        genome_id="known-good", species="workload_forecaster",
        hyperparameters={
            "learning_rate": 0.01, "hidden_dim": WORKLOAD_FORECASTER_HIDDEN_DIM,
            "epochs": 40, "replay_fraction": 0.5,
        },
    )
    eng._workload_genome_population.genomes = [good]
    eng._workload_genome_population.mu = 1

    def fake_score(genome, train_examples, holdout, seed=0):
        fitness = 0.9 if genome.genome_id == "known-good" else 0.1
        return None, fitness

    real_fn = engine_mod.train_and_score_genome_via_specialist
    engine_mod.train_and_score_genome_via_specialist = fake_score
    try:
        eng._maybe_evolve_workload_genomes(["year_end"])
    finally:
        engine_mod.train_and_score_genome_via_specialist = real_fn
    entry = eng._workload_genome_evolve_log[-1]
    return (
        entry["adopted"] is True
        and eng._workload_learning_rate_override == 0.01
        and eng._workload_epochs_override == 40
    )


@check("a genuinely worse candidate population is correctly NOT adopted")
def check_worse_genome_not_adopted():
    import hearthmind.simulation.engine as engine_mod

    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 10)
    eng._workload_learning_rate_override = WORKLOAD_LEARNING_RATE
    eng._workload_epochs_override = 20
    bad = ModelGenome(
        genome_id="known-bad", species="workload_forecaster",
        hyperparameters={
            "learning_rate": 0.05, "hidden_dim": WORKLOAD_FORECASTER_HIDDEN_DIM,
            "epochs": 3, "replay_fraction": 0.5,
        },
    )
    eng._workload_genome_population.genomes = [bad]
    eng._workload_genome_population.mu = 1

    def fake_score(genome, train_examples, holdout, seed=0):
        fitness = 0.1 if genome.genome_id == "known-bad" else 0.9
        return None, fitness

    real_fn = engine_mod.train_and_score_genome_via_specialist
    engine_mod.train_and_score_genome_via_specialist = fake_score
    try:
        eng._maybe_evolve_workload_genomes(["year_end"])
    finally:
        engine_mod.train_and_score_genome_via_specialist = real_fn
    entry = eng._workload_genome_evolve_log[-1]
    return (
        entry["adopted"] is False
        and eng._workload_learning_rate_override == WORKLOAD_LEARNING_RATE
        and eng._workload_epochs_override == 20
    )


@check("_maybe_tick_workload_forecaster's monthly retrain reads the live overrides, not the flat constant")
def check_monthly_retrain_reads_override():
    eng = _make_engine()
    eng._workload_learning_rate_override = 0.005
    eng._workload_epochs_override = 7
    eng._workload_training_examples = _synthetic_examples(30)
    # Directly exercise the retrain half (the daily-sampling half needs
    # a real day_end tick; this isolates the retrain call itself).
    captured = {}
    real_learn = eng._workload_specialist.learn

    def spy_learn(new_examples, holdout, tick, **kwargs):
        captured.update(kwargs)
        return real_learn(new_examples, holdout, tick, **kwargs)

    eng._workload_specialist.learn = spy_learn
    # The daily-sampling step (which the monthly retrain is gated
    # behind) is itself gated on "day_end" -- a real month_end tick
    # always also carries day_end (SimClock.advance crosses every
    # smaller boundary too), so both must be present here.
    eng._maybe_tick_workload_forecaster(["day_end", "month_end"])
    return captured.get("learning_rate") == 0.005 and captured.get("epochs") == 7


@check("_TICK_JOBS registers _maybe_evolve_workload_genomes BEFORE _maybe_tick_workload_forecaster")
def check_tick_jobs_ordering():
    names = [name for name, _ in SimulationEngine._TICK_JOBS]
    return (
        "_maybe_evolve_workload_genomes" in names
        and "_maybe_tick_workload_forecaster" in names
        and names.index("_maybe_evolve_workload_genomes") < names.index("_maybe_tick_workload_forecaster")
    )


@check("full_diagnostics()['workload_forecaster']['genome_population'] surfaces real live state")
def check_diagnostics_shape():
    eng = _make_engine()
    eng._workload_training_examples = _synthetic_examples(WORKLOAD_GENOME_MIN_EXAMPLES + 10)
    eng._maybe_evolve_workload_genomes(["year_end"])
    report = eng.full_diagnostics()
    gp = report["workload_forecaster"]["genome_population"]
    return (
        gp["size"] == WORKLOAD_GENOME_POPULATION_SIZE
        and gp["learning_rate"] == eng._workload_learning_rate_override
        and gp["epochs"] == eng._workload_epochs_override
        and len(gp["evolve_log_recent"]) == 1
    )


@check("no-op baseline: a real soak with too little accumulated data never evolves/adopts anything")
def check_short_soak_never_evolves():
    eng = _make_engine(seed=9)

    async def drive():
        for _ in range(500):
            eng._tick_once()
            await asyncio.sleep(0)

    asyncio.run(drive())
    return len(eng._workload_genome_evolve_log) == 0


@check("live end-to-end proof: a real multi-year soak produces at least one real evolutionary generation")
def check_live_soak_produces_evolution():
    # A coarser sim_minutes_per_tick (120 vs. the default 15) buys
    # nothing but real wall-clock cost here — this check's own claim
    # is "a real year_end boundary genuinely fires
    # _maybe_evolve_workload_genomes end-to-end," which depends only
    # on how many CALENDAR units have elapsed (SimClock derives day/
    # month/season/year boundaries purely from minutes-per-tick vs.
    # each unit's own fixed real-minute length, per time_system.py),
    # never on tick-to-simulated-time fidelity. At 120 this is 12
    # ticks/day instead of 96 -- an 8x fewer real `_tick_once()` calls
    # to cross the same 370 simulated days, confirmed directly against
    # a real timing probe (~21s vs. 10+ minutes at the default).
    eng = _make_engine(seed=17, sim_minutes_per_tick=120)
    ticks_per_day = eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick
    # A little over one real year -- day_end/month_end/season_end/
    # year_end all fire naturally, letting _maybe_tick_workload_
    # forecaster's own daily sampling accumulate real training
    # examples (call-volume observations, even LLM-disabled, since
    # the observed delta is a real 0-call reading, not a fabricated
    # one) before this job's own year_end check runs.
    total_ticks = ticks_per_day * 370

    async def drive():
        for _ in range(total_ticks):
            eng._tick_once()
            if eng.world.clock.tick_count % 500 == 0:
                await asyncio.sleep(0)

    asyncio.run(drive())
    return len(eng._workload_genome_evolve_log) >= 1


def main() -> int:
    failures = []
    for name, fn in CHECKS:
        try:
            ok = fn()
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[FAIL] {name} -- raised {exc!r}")
            failures.append(name)
            continue
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(name)
    print()
    if failures:
        print(f"{len(failures)}/{len(CHECKS)} check(s) FAILED: {failures}")
        return 1
    print(f"{len(CHECKS)}/{len(CHECKS)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
