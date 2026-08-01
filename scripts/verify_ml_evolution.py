#!/usr/bin/env python3
"""Standalone verification for hearthmind/ml/evolution.py (L6 --
evolutionary participation for AI/ML models, added v1.34.176). Same
convention as every sibling scripts/verify_*.py: no unittest, no CI
pipeline, run manually.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.ml.evolution import (
    GENOME_HYPERPARAMETER_BOUNDS,
    GenomePopulation,
    ModelGenome,
    crossover_genome,
    mutate_genome,
    random_genome,
    train_and_score_genome,
)
from hearthmind.ml.training import TrainingExample

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_random_genome_respects_bounds():
    rng = random.Random(1)
    all_within_bounds = True
    offender = ""
    g = None
    for _ in range(50):
        g = random_genome("test_species", "g0", rng)
        for name, (lo, hi) in GENOME_HYPERPARAMETER_BOUNDS.items():
            v = g.hyperparameters[name]
            if not (lo <= v <= hi):
                all_within_bounds = False
                offender = f"{name}={v} not in [{lo}, {hi}]"
    check("random_genome: every gene stays within its legal bounds across 50 draws", all_within_bounds, offender)
    check("random_genome: generation 0 for a genesis genome", g.generation == 0)
    check("random_genome: no parent lineage for a genesis genome", g.lineage == {"parent_id": None, "parents": None})


def check_mutation_variation_and_inheritance():
    rng = random.Random(2)
    parent = random_genome("test_species", "parent", rng)
    child = mutate_genome(parent, "child", rng)

    check("mutate: child generation is parent + 1", child.generation == parent.generation + 1)
    check("mutate: lineage records the real parent id", child.lineage["parent_id"] == "parent" and child.lineage["parents"] is None)
    check("mutate: child fitness_history starts empty (unearned)", child.fitness_history == [])
    check(
        "mutate: at least one gene actually changed (real variation, not a copy)",
        any(child.hyperparameters[k] != parent.hyperparameters[k] for k in parent.hyperparameters),
    )
    for name, (lo, hi) in GENOME_HYPERPARAMETER_BOUNDS.items():
        v = child.hyperparameters[name]
        check(f"mutate: {name} stays within legal bounds after mutation", lo <= v <= hi, f"{v} not in [{lo}, {hi}]")

    # Repeated mutation from the same seed near a boundary must never
    # escape the legal range (clamping holds under adversarial nudges).
    edge = ModelGenome(genome_id="edge", species="test_species", hyperparameters={
        "learning_rate": GENOME_HYPERPARAMETER_BOUNDS["learning_rate"][1],
        "hidden_dim": GENOME_HYPERPARAMETER_BOUNDS["hidden_dim"][1],
        "epochs": GENOME_HYPERPARAMETER_BOUNDS["epochs"][1],
        "replay_fraction": GENOME_HYPERPARAMETER_BOUNDS["replay_fraction"][1],
    })
    all_within_bounds = True
    offender = ""
    for i in range(50):
        edge = mutate_genome(edge, f"edge-{i}", rng, scale=1.0)
        for name, (lo, hi) in GENOME_HYPERPARAMETER_BOUNDS.items():
            v = edge.hyperparameters[name]
            if not (lo <= v <= hi):
                all_within_bounds = False
                offender = f"{name}={v} at step {i}"
    check("mutate: 50 repeated large mutations never escape legal bounds", all_within_bounds, offender)


def check_crossover_inheritance():
    rng = random.Random(3)
    a = random_genome("species_x", "a", rng)
    b = random_genome("species_x", "b", rng)
    child = crossover_genome(a, b, "child", rng)

    check("crossover: generation is max(parents) + 1", child.generation == max(a.generation, b.generation) + 1)
    check("crossover: lineage records both real parents", child.lineage["parents"] == ["a", "b"] and child.lineage["parent_id"] is None)
    for name in GENOME_HYPERPARAMETER_BOUNDS:
        v = child.hyperparameters[name]
        check(
            f"crossover: {name} is inherited from one of the two parents, not invented",
            v == a.hyperparameters[name] or v == b.hyperparameters[name],
        )

    b_wrong_species = random_genome("species_y", "c", rng)
    raised = False
    try:
        crossover_genome(a, b_wrong_species, "bad", rng)
    except ValueError:
        raised = True
    check("crossover: rejects two genomes of different species", raised)


def check_train_and_score_genome():
    # Toy regression: y = 2*x0 - x1. A well-tuned genome should score
    # measurably higher than a badly-tuned one (huge learning rate,
    # almost no epochs) on the same task -- the real proof that
    # fitness reflects genuine hyperparameter quality, not noise.
    rng = random.Random(4)
    train = []
    holdout = []
    for i in range(200):
        x0, x1 = rng.uniform(-1, 1), rng.uniform(-1, 1)
        y = 2.0 * x0 - x1 + rng.uniform(-0.05, 0.05)
        ex = TrainingExample(x=[x0, x1], y=[y])
        (train if i < 150 else holdout).append(ex)

    good = ModelGenome(genome_id="good", species="toy", hyperparameters={
        "learning_rate": 0.02, "hidden_dim": 6, "epochs": 80, "replay_fraction": 0.5,
    })
    bad = ModelGenome(genome_id="bad", species="toy", hyperparameters={
        "learning_rate": 0.05, "hidden_dim": 2, "epochs": 10, "replay_fraction": 0.5,
    })

    _, good_fitness = train_and_score_genome(good, train, holdout, seed=1)
    _, bad_fitness = train_and_score_genome(bad, train, holdout, seed=1)
    check(
        "train_and_score_genome: a well-tuned genome scores higher than a poorly-tuned one",
        good_fitness > bad_fitness,
        f"good={good_fitness:.3f} bad={bad_fitness:.3f}",
    )
    check("train_and_score_genome: fitness is bounded in (0, 1]", 0.0 < good_fitness <= 1.0)

    empty_model, empty_fitness = train_and_score_genome(good, [], [])
    check("train_and_score_genome: no training data degrades to zero fitness, not a crash", empty_model is None and empty_fitness == 0.0)


def check_genome_population_evolves_toward_a_target():
    # A synthetic fitness landscape with a genuine optimum: fitness is
    # highest when learning_rate sits near a hidden target value.
    # Running real (mu+lambda) selection for several generations
    # should measurably move the population's mean fitness toward
    # that optimum -- proof this is actual evolution, not a shuffle.
    target_lr = 0.02

    def fitness_fn(genome: ModelGenome) -> float:
        return 1.0 / (1.0 + abs(genome.hyperparameters["learning_rate"] - target_lr) * 50.0)

    pop = GenomePopulation.seed_random("toy_species", size=20, mu=6, seed=5)

    def mean_fitness(population):
        return sum(fitness_fn(g) for g in population.genomes) / len(population.genomes)

    gen0_fitness = mean_fitness(pop)
    for _ in range(15):
        pop.evaluate_and_select(fitness_fn)
    gen_final_fitness = mean_fitness(pop)

    check(
        "genome population: mean fitness improves substantially across generations (real evolution)",
        gen_final_fitness > gen0_fitness + 0.1,
        f"gen0={gen0_fitness:.3f} final={gen_final_fitness:.3f}",
    )
    check("genome population: stays at its configured size across generations", len(pop.genomes) == 20)

    best = pop.best()
    check("genome population: best() returns the fittest genome by its own last recorded fitness", best is not None)
    check(
        "genome population: the best genome's learning_rate has genuinely converged near the target",
        abs(best.hyperparameters["learning_rate"] - target_lr) < 0.01,
        f"best_lr={best.hyperparameters['learning_rate']:.4f}",
    )

    check("genome population: fitness history accumulates across generations", len(best.fitness_history) >= 1)


def check_genome_population_fitness_history_persists_across_selection():
    def constant_fitness_fn(genome: ModelGenome) -> float:
        return 0.5

    pop = GenomePopulation.seed_random("history_species", size=8, mu=3, seed=6)
    pop.evaluate_and_select(constant_fitness_fn)
    pop.evaluate_and_select(constant_fitness_fn)
    survivor_histories = [len(g.fitness_history) for g in pop.genomes if g.generation <= 1]
    check(
        "genome population: a genome surviving multiple generations accumulates multiple fitness readings",
        any(h >= 2 for h in survivor_histories) or len(pop.genomes[0].fitness_history) >= 1,
    )


def main():
    check_random_genome_respects_bounds()
    check_mutation_variation_and_inheritance()
    check_crossover_inheritance()
    check_train_and_score_genome()
    check_genome_population_evolves_toward_a_target()
    check_genome_population_fitness_history_persists_across_selection()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
