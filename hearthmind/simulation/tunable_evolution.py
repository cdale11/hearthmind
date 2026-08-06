"""B13.5 -- Optional evolutionary search over multi-dimensional
tunable sets (docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard
Rule 14]). Gated behind B13.1/B13.2 being solid first, per the item's
own text -- both shipped v1.34.180, so this closed B13 in full.

**Wired (roadmap Phase 2, "phase 2 b13.5"):** `SimulationEngine.
_maybe_evolve_pacing_genomes` runs a real yearly `TunableGenome
Population` over the three `llm_pressure_*` pacing-ratio tunables —
`evaluate_tunable_genome_fitness` below is consulted for real, not
just tested in isolation. `llm_max_concurrent` (the fourth registered
pacing tunable) is deliberately excluded from this population — it
already has its own real single-tunable B13.1 `HypothesisLoop`.

Mirrors Tier 6's L6 `ModelGenome`/`mutate_genome`/`crossover_genome`/
`GenomePopulation` shape directly (`hearthmind/ml/evolution.py`) --
the SAME evolutionary mechanism (mu+lambda selection, mutation +
crossover), a genuinely different gene space: runtime CONTROL
tunables here (B6's own `Tunable`/`TunableRegistry`), never LEARNED
MODEL hyperparameters. Reuses B13's own semantic-safety gate directly
for fitness disqualification, rather than a parallel evolutionary
mechanism AND a parallel safety gate: a genome touching a `SENSITIVE`
tunable that fails (or skips) `equivalence_check_fn` scores as unfit
(`DISQUALIFIED_FITNESS`), never allowed to win selection regardless of
its raw measured throughput -- "fitness = throughput under the
semantic-safety constraint" is enforced in code, not left as an
intention.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.simulation.tuning import SafetyClass, TunableRegistry

FITNESS_HISTORY_MAX = 20
GENOME_MUTATION_SCALE = 0.25
DISQUALIFIED_FITNESS = float("-inf")


@dataclass
class TunableGenome:
    """Field shape mirrors L6's `ModelGenome` exactly. `values` covers
    a fixed, named SUBSET of a `TunableRegistry`'s tunables -- the
    "multi-dimensional tunable set" this item's own text names."""

    genome_id: str
    tunable_names: frozenset
    values: dict
    lineage: dict = field(default_factory=lambda: {"parent_id": None, "parents": None})
    fitness_history: list = field(default_factory=list)
    generation: int = 0

    def record_fitness(self, fitness: float) -> None:
        self.fitness_history.append(fitness)
        if len(self.fitness_history) > FITNESS_HISTORY_MAX:
            self.fitness_history.pop(0)

    def mean_fitness(self):
        if not self.fitness_history:
            return None
        return sum(self.fitness_history) / len(self.fitness_history)


def random_tunable_genome(registry: TunableRegistry, tunable_names, genome_id: str, rng: random.Random) -> TunableGenome:
    """Genesis genome: a uniformly-random legal value per named
    tunable, read straight from the registry's own real bounds."""
    values = {}
    for name in tunable_names:
        t = registry.get(name)
        values[name] = rng.uniform(t.min_value, t.max_value)
    return TunableGenome(genome_id=genome_id, tunable_names=frozenset(tunable_names), values=values)


def mutate_tunable_genome(parent: TunableGenome, registry: TunableRegistry, genome_id: str, rng: random.Random, scale: float = GENOME_MUTATION_SCALE) -> TunableGenome:
    """Variation + inheritance (asexual), same shape as L6's
    `mutate_genome`: each gene nudged by up to `scale` of its OWN
    tunable's real legal range, then clamped via the registry's own
    `Tunable.clamp` -- a mutated genome can never propose an illegal
    value."""
    child_values = {}
    for name, value in parent.values.items():
        t = registry.get(name)
        span = t.max_value - t.min_value
        delta = rng.uniform(-scale, scale) * span
        child_values[name] = t.clamp(value + delta)
    return TunableGenome(
        genome_id=genome_id,
        tunable_names=parent.tunable_names,
        values=child_values,
        lineage={"parent_id": parent.genome_id, "parents": None},
        generation=parent.generation + 1,
    )


def crossover_tunable_genome(a: TunableGenome, b: TunableGenome, genome_id: str, rng: random.Random) -> TunableGenome:
    """Variation + inheritance (sexual), same shape as L6's `crossover_
    genome`: each gene independently drawn from ONE of the two parents.
    Rejects crossing two genomes that cover different tunable sets --
    the direct analogue of `crossover_genome`'s species-mismatch
    rejection."""
    if a.tunable_names != b.tunable_names:
        raise ValueError(
            f"crossover requires two genomes over the SAME tunable set: "
            f"{sorted(a.tunable_names)} vs {sorted(b.tunable_names)}"
        )
    child_values = {name: (a.values[name] if rng.random() < 0.5 else b.values[name]) for name in a.tunable_names}
    return TunableGenome(
        genome_id=genome_id,
        tunable_names=a.tunable_names,
        values=child_values,
        lineage={"parent_id": None, "parents": [a.genome_id, b.genome_id]},
        generation=max(a.generation, b.generation) + 1,
    )


def apply_tunable_genome(genome: TunableGenome, registry: TunableRegistry) -> None:
    """Writes every gene into the real registry via `set_value`
    (clamped) -- the one place a genome's values actually become the
    live tunable state a `measure_fn` would then read."""
    for name, value in genome.values.items():
        registry.set_value(name, value)


def evaluate_tunable_genome_fitness(genome: TunableGenome, registry: TunableRegistry, measure_fn, equivalence_check_fn=None) -> float:
    """B13.5's own "fitness = throughput under the semantic-safety
    constraint," enforced in code. Applies the genome, measures via
    `measure_fn()` (higher is better -- e.g. real throughput). If the
    genome touches ANY `SENSITIVE` tunable, the measured fitness only
    counts once `equivalence_check_fn` (B13.2's real replay-hash-
    equivalence machinery) reports `True` -- no check at all, or a
    failing one, disqualifies the genome outright (`DISQUALIFIED_
    FITNESS`), regardless of how good its raw measurement looked. A
    genome touching only `SAFE` tunables skips the gate entirely, same
    as B13's own `HypothesisLoop`."""
    apply_tunable_genome(genome, registry)
    raw_fitness = measure_fn()

    touches_sensitive = any(registry.get(name).safety_class is SafetyClass.SENSITIVE for name in genome.values)
    if touches_sensitive:
        passed = bool(equivalence_check_fn()) if equivalence_check_fn is not None else False
        if not passed:
            return DISQUALIFIED_FITNESS
    return raw_fitness


@dataclass
class TunableGenomePopulation:
    """A bounded population of genome variants over one fixed tunable
    set. `evaluate_and_select` is the same real (mu + lambda)
    evolutionary step L6's `GenomePopulation` already established."""

    registry: TunableRegistry
    tunable_names: frozenset
    genomes: list
    mu: int
    seed: int = 0
    _next_id: int = 0
    _rng: object = field(default=None, repr=False)

    def __post_init__(self):
        if self._rng is None:
            self._rng = random.Random(self.seed)

    def _fresh_id(self) -> str:
        self._next_id += 1
        return f"tunables-g{self._next_id}"

    @classmethod
    def seed_random(cls, registry: TunableRegistry, tunable_names, size: int, mu: int, seed: int = 0) -> "TunableGenomePopulation":
        rng = random.Random(seed)
        pop = cls(registry=registry, tunable_names=frozenset(tunable_names), genomes=[], mu=mu, seed=seed)
        pop.genomes = [random_tunable_genome(registry, tunable_names, pop._fresh_id(), rng) for _ in range(size)]
        return pop

    def evaluate_and_select(self, fitness_fn) -> None:
        """`fitness_fn(genome) -> float` (typically `evaluate_tunable_
        genome_fitness` bound to a real registry/measure_fn/equivalence_
        check_fn). Scores every genome, records the reading into its
        own `fitness_history`, keeps the `mu` fittest as survivors
        (a `DISQUALIFIED_FITNESS` genome always ranks last and is
        never kept while a qualifying alternative exists), and refills
        the population back to its original size via mutation/
        crossover of survivors."""
        size = len(self.genomes)
        for genome in self.genomes:
            genome.record_fitness(fitness_fn(genome))

        ranked = sorted(self.genomes, key=lambda g: g.fitness_history[-1], reverse=True)
        survivors = ranked[: min(self.mu, len(ranked))]

        offspring = []
        while len(survivors) + len(offspring) < size:
            if len(survivors) >= 2 and self._rng.random() < 0.5:
                a, b = self._rng.sample(survivors, 2)
                offspring.append(crossover_tunable_genome(a, b, self._fresh_id(), self._rng))
            else:
                parent = self._rng.choice(survivors)
                offspring.append(mutate_tunable_genome(parent, self.registry, self._fresh_id(), self._rng))

        self.genomes = survivors + offspring

    def best(self):
        scored = [g for g in self.genomes if g.fitness_history]
        if not scored:
            return None
        return max(scored, key=lambda g: g.fitness_history[-1])
