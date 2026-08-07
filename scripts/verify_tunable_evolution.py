#!/usr/bin/env python3
"""Standalone verification for B13.5 (Optional evolutionary search
over multi-dimensional tunable sets, docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B). Same convention as every sibling scripts/
verify_*.py: no unittest, no CI pipeline, run manually.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.tunable_evolution import (
    DISQUALIFIED_FITNESS,
    TunableGenomePopulation,
    crossover_tunable_genome,
    evaluate_tunable_genome_fitness,
    mutate_tunable_genome,
    random_tunable_genome,
)
from hearthmind.simulation.tuning import SafetyClass, Tunable, TunableRegistry

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def _fresh_registry():
    registry = TunableRegistry()
    registry.register(Tunable(name="safe_a", value=5.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    registry.register(Tunable(name="safe_b", value=5.0, min_value=0.0, max_value=10.0, step=1.0, safety_class=SafetyClass.SAFE))
    registry.register(Tunable(
        name="sensitive_c", value=2.0, min_value=1.0, max_value=8.0, step=1.0,
        safety_class=SafetyClass.SENSITIVE, description="synthetic sensitive tunable for this verify script's own fixture.",
    ))
    return registry


def check_random_genome_respects_bounds():
    registry = _fresh_registry()
    rng = random.Random(1)
    for _ in range(50):
        genome = random_tunable_genome(registry, ["safe_a", "safe_b"], "g", rng)
        for name, value in genome.values.items():
            t = registry.get(name)
            check(f"random_tunable_genome: {name} within [{t.min_value},{t.max_value}]", t.min_value <= value <= t.max_value)


def check_mutation_always_clamped():
    registry = _fresh_registry()
    rng = random.Random(2)
    parent = random_tunable_genome(registry, ["safe_a"], "p", rng)
    parent.values["safe_a"] = 9.9  # near the ceiling, so a large mutation would overshoot without clamping
    for i in range(50):
        child = mutate_tunable_genome(parent, registry, f"c{i}", rng, scale=1.0)  # deliberately large scale
        t = registry.get("safe_a")
        check("mutate_tunable_genome: child gene stays within legal bounds even with a large mutation scale", t.min_value <= child.values["safe_a"] <= t.max_value)
    check("mutate_tunable_genome: lineage records the real parent", child.lineage["parent_id"] == "p" and child.generation == parent.generation + 1)


def check_crossover_mismatched_tunable_sets_rejected():
    registry = _fresh_registry()
    rng = random.Random(3)
    a = random_tunable_genome(registry, ["safe_a", "safe_b"], "a", rng)
    b = random_tunable_genome(registry, ["safe_a"], "b", rng)
    raised = False
    try:
        crossover_tunable_genome(a, b, "child", rng)
    except ValueError:
        raised = True
    check("crossover: rejects two genomes covering different tunable sets", raised)


def check_crossover_gene_by_gene_from_one_parent():
    registry = _fresh_registry()
    rng = random.Random(4)
    a = random_tunable_genome(registry, ["safe_a", "safe_b"], "a", rng)
    b = random_tunable_genome(registry, ["safe_a", "safe_b"], "b", rng)
    child = crossover_tunable_genome(a, b, "child", rng)
    check(
        "crossover: every gene is inherited from exactly one of the two named parents",
        all(child.values[n] in (a.values[n], b.values[n]) for n in child.values),
    )
    check("crossover: lineage records both real parents, generation advances", child.lineage["parents"] == ["a", "b"] and child.generation == max(a.generation, b.generation) + 1)


def check_evaluate_safe_only_genome_skips_gate_entirely():
    registry = _fresh_registry()
    genome = random_tunable_genome(registry, ["safe_a", "safe_b"], "g", random.Random(5))
    fitness = evaluate_tunable_genome_fitness(genome, registry, measure_fn=lambda: 42.0)  # no equivalence_check_fn at all
    check("evaluate: a SAFE-only genome's fitness is the raw measurement, no gate needed", fitness == 42.0)


def check_evaluate_sensitive_genome_disqualified_without_check():
    registry = _fresh_registry()
    genome = random_tunable_genome(registry, ["sensitive_c"], "g", random.Random(6))
    fitness = evaluate_tunable_genome_fitness(genome, registry, measure_fn=lambda: 100.0)  # great raw throughput, no equivalence check
    check("evaluate: a SENSITIVE-touching genome with NO equivalence_check_fn is disqualified regardless of raw fitness", fitness == DISQUALIFIED_FITNESS)


def check_evaluate_sensitive_genome_disqualified_on_failed_check():
    registry = _fresh_registry()
    genome = random_tunable_genome(registry, ["sensitive_c"], "g", random.Random(7))
    fitness = evaluate_tunable_genome_fitness(genome, registry, measure_fn=lambda: 100.0, equivalence_check_fn=lambda: False)
    check("evaluate: 'fitness = throughput under the semantic-safety constraint' -- a failed check disqualifies a genuinely fast genome", fitness == DISQUALIFIED_FITNESS)


def check_evaluate_sensitive_genome_kept_on_passed_check():
    registry = _fresh_registry()
    genome = random_tunable_genome(registry, ["sensitive_c"], "g", random.Random(8))
    fitness = evaluate_tunable_genome_fitness(genome, registry, measure_fn=lambda: 100.0, equivalence_check_fn=lambda: True)
    check("evaluate: a SENSITIVE-touching genome that passes equivalence keeps its real measured fitness", fitness == 100.0)


def check_population_mean_fitness_climbs_toward_a_target():
    """The load-bearing check, same shape as L6's own -- a real
    synthetic optimum the population should converge toward across
    several generations, proving evolution actually happens, not just
    that the mechanics run without crashing."""
    registry = _fresh_registry()
    target = 7.0

    def fitness_fn(genome):
        # Peaked fitness landscape: closer to target = higher fitness. SAFE tunable only, no gate needed.
        return -abs(genome.values["safe_a"] - target)

    pop = TunableGenomePopulation.seed_random(registry, ["safe_a"], size=12, mu=4, seed=42)
    initial_best = max(g.values["safe_a"] for g in pop.genomes)
    initial_mean_dist = sum(abs(g.values["safe_a"] - target) for g in pop.genomes) / len(pop.genomes)

    for _ in range(15):
        pop.evaluate_and_select(fitness_fn)

    final_mean_dist = sum(abs(g.values["safe_a"] - target) for g in pop.genomes) / len(pop.genomes)
    best = pop.best()
    check(
        "evolution: population mean distance to the synthetic target shrinks substantially over generations",
        final_mean_dist < initial_mean_dist * 0.5,
        f"initial={initial_mean_dist:.3f} final={final_mean_dist:.3f}",
    )
    check("evolution: best() returns the genuinely fittest genome (closest to target)", best is not None and abs(best.values["safe_a"] - target) == min(abs(g.values["safe_a"] - target) for g in pop.genomes if g.fitness_history))
    check("evolution: fitness history persists across survivors (more than one reading for at least one genome)", any(len(g.fitness_history) > 1 for g in pop.genomes))
    _ = initial_best  # referenced only for the printed diagnostic context above


def check_disqualified_genomes_never_survive_over_a_qualifying_alternative():
    registry = _fresh_registry()
    rng = random.Random(9)
    good = random_tunable_genome(registry, ["sensitive_c"], "good", rng)
    bad = random_tunable_genome(registry, ["sensitive_c"], "bad", rng)
    pop = TunableGenomePopulation(registry=registry, tunable_names=frozenset({"sensitive_c"}), genomes=[good, bad], mu=1, seed=1)

    def fitness_fn(genome):
        # "good" always passes equivalence; "bad" never does, regardless of measured value.
        passes = genome.genome_id == "good"
        return evaluate_tunable_genome_fitness(genome, registry, measure_fn=lambda: 50.0, equivalence_check_fn=(lambda: True) if passes else (lambda: False))

    pop.evaluate_and_select(fitness_fn)
    check(
        "evolution: the disqualified genome is never kept as the sole survivor when a qualifying one exists",
        any(g.lineage.get("parent_id") == "good" or g.genome_id == "good" for g in pop.genomes),
    )


def main():
    check_random_genome_respects_bounds()
    check_mutation_always_clamped()
    check_crossover_mismatched_tunable_sets_rejected()
    check_crossover_gene_by_gene_from_one_parent()
    check_evaluate_safe_only_genome_skips_gate_entirely()
    check_evaluate_sensitive_genome_disqualified_without_check()
    check_evaluate_sensitive_genome_disqualified_on_failed_check()
    check_evaluate_sensitive_genome_kept_on_passed_check()
    check_population_mean_fitness_climbs_toward_a_target()
    check_disqualified_genomes_never_survive_over_a_qualifying_alternative()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
