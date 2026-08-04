#!/usr/bin/env python3
"""Tier 7 HCA Stage G, G4 (explicit user instruction: "Start G4"): L6's
population-level variation (phylogeny) wired to a real L1 consumer.

G4's own stated test (docs/ROADMAP-2026-07-REMAINING.md): "a genome
population's mean fitness climbs over generations on a real
specialist's own task, using the real `GenomePopulation.evaluate_and_
select` against a real L1 consumer (verified in isolation only so
far)." Verified here as real production-path checks against the real
`GenomePopulation`/`ModelGenome`/`LearningSpecialist` classes -- the
"workload_forecaster" species (the same real specialist family G2
wired up), a real stationary synthetic task, and the real shadow-gated
`train_and_score_genome_via_specialist` as the fitness function. No
unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import random
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.ml.evolution import (
    GENOME_HYPERPARAMETER_BOUNDS,
    GenomePopulation,
    ModelGenome,
    genome_to_mlp,
    train_and_score_genome,
    train_and_score_genome_via_specialist,
)
from hearthmind.ml.specialist import LearningSpecialist
from hearthmind.ml.training import TrainingExample

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def stationary_examples(rng: random.Random, n: int) -> list[TrainingExample]:
    """A fixed, learnable 3-input -> 1-output signal -- the same real
    specialist's-own-task shape G4's test asks for, generic enough to
    stand in for WORKLOAD_FORECAST_SCHEMA's own real dimensionality
    without needing a live SimulationEngine to source real examples
    from (same "ship the substrate, verify with a real stationary
    signal" discipline G1's own verify script already used)."""
    examples = []
    for _ in range(n):
        x0, x1, x2 = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)
        noise = rng.uniform(-0.02, 0.02)
        y = max(0.0, min(1.0, 0.4 * x0 - 0.3 * x1 + 0.2 * x2 + 0.5 + noise))
        examples.append(TrainingExample(x=[x0, x1, x2], y=[y]))
    return examples


def main() -> int:
    rng = random.Random(7734)
    train_examples = stationary_examples(rng, 120)
    holdout = stationary_examples(random.Random(9911), 60)

    # --- 1. real L1 consumer: fitness is scored through a real
    #        LearningSpecialist.learn() cycle, not a parallel path ------
    genome = ModelGenome(
        genome_id="g-test-1", species="workload_forecaster",
        hyperparameters={"learning_rate": 0.01, "hidden_dim": 6, "epochs": 40, "replay_fraction": 0.5},
    )
    model, fitness = train_and_score_genome_via_specialist(genome, train_examples, holdout, seed=1)
    check("train_and_score_genome_via_specialist returns a real trained model + fitness", model is not None and 0.0 < fitness <= 1.0)

    # Independently confirm it's a genuine specialist.learn() cycle:
    # replicate the exact call by hand and check the resulting model's
    # held-out loss lines up with what the genome scoring produced.
    hand_model = genome_to_mlp(genome, input_dim=3, output_dim=1, seed=1)
    hand_specialist = LearningSpecialist(hand_model, replay_capacity=200, checkpoint_capacity=10, replay_seed=1)
    hand_result = hand_specialist.learn(
        train_examples, holdout, tick=0, replay_fraction=0.5, epochs=40, learning_rate=0.01, seed=1,
    )
    check(
        "the genome-scoring path reproduces the identical real specialist.learn() outcome by hand",
        abs(hand_result.candidate_metric - (1.0 / fitness - 1.0)) < 1e-9,
    )

    # --- 2. a shadow-gate REJECTION leaves the live specialist model
    #        untouched, and a NaN-diverged candidate degrades the genome
    #        scorer's fitness gracefully (0.0) rather than crashing -----
    warm_model = genome_to_mlp(genome, input_dim=3, output_dim=1, seed=2)
    warm_specialist = LearningSpecialist(warm_model, replay_capacity=200, checkpoint_capacity=10, replay_seed=2)
    warm_specialist.learn(train_examples, holdout, tick=0, replay_fraction=0.5, epochs=80, learning_rate=0.02, seed=2)
    live_weights_before = warm_specialist.model.to_dict()
    # A deliberately wrong, wildly-off target -- diverges the retrain's
    # loss to NaN, a real (if extreme) rejected-candidate case.
    sabotage_examples = [TrainingExample(x=ex.x, y=[-999.0]) for ex in train_examples]
    bad_result = warm_specialist.learn(sabotage_examples, holdout, tick=1, epochs=60, learning_rate=0.05, seed=2)
    check("a deliberately-sabotaged retrain is genuinely rejected by the real shadow gate", bad_result.accepted is False)
    check(
        "the live model's weights are byte-identical after a rejected retrain",
        warm_specialist.model.to_dict() == live_weights_before,
    )
    # The genome-scoring wrapper's own NaN guard, exercised directly:
    # a genome whose training run diverges must degrade to fitness 0.0,
    # never propagate the NaN or crash the evolutionary loop around it.
    diverging_genome = ModelGenome(
        genome_id="g-diverge", species="workload_forecaster",
        hyperparameters={"learning_rate": 0.05, "hidden_dim": 6, "epochs": 60, "replay_fraction": 0.5},
    )
    diverge_model, diverge_fitness = train_and_score_genome_via_specialist(
        diverging_genome, sabotage_examples, holdout, seed=2,
    )
    check(
        "a genuinely NaN-diverged genome degrades to fitness 0.0, not a crash or a fabricated score",
        diverge_model is not None and diverge_fitness == 0.0,
    )

    # --- 3. THE headline test: a real genome population's mean fitness
    #        climbs over generations via evaluate_and_select against the
    #        real L1 consumer -----------------------------------------
    population = GenomePopulation.seed_random(species="workload_forecaster", size=10, mu=4, seed=42)

    def fitness_fn(g: ModelGenome) -> float:
        _, f = train_and_score_genome_via_specialist(g, train_examples, holdout, seed=1)
        return f

    generation_means = []
    for _ in range(8):
        population.evaluate_and_select(fitness_fn)
        readings = [g.fitness_history[-1] for g in population.genomes if g.fitness_history]
        generation_means.append(sum(readings) / len(readings))

    check(
        f"population mean fitness climbs across 8 generations ({generation_means[0]:.4f} -> {generation_means[-1]:.4f})",
        generation_means[-1] > generation_means[0],
    )
    best = population.best()
    check("GenomePopulation.best() returns a real, fitness-scored genome", best is not None and best.mean_fitness() is not None)

    # --- 4. negative control: the OLD path (train_and_score_genome,
    #        bare train_mlp_sgd, no specialist) still works unmodified,
    #        confirming this pass didn't disturb the existing consumer --
    _, old_fitness = train_and_score_genome(genome, train_examples, holdout, seed=1)
    check("the pre-existing train_and_score_genome path is unaffected", 0.0 < old_fitness <= 1.0)

    # --- 5. every heritable gene stays within GENOME_HYPERPARAMETER_
    #        BOUNDS across the whole real evolutionary run above --------
    bounds_ok = all(
        GENOME_HYPERPARAMETER_BOUNDS[name][0] <= value <= GENOME_HYPERPARAMETER_BOUNDS[name][1]
        for g in population.genomes for name, value in g.hyperparameters.items()
    )
    check("every surviving/bred genome's genes stay within their legal bounds", bounds_ok)

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
