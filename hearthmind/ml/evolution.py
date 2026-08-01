"""L6 -- evolutionary participation for AI/ML models (added v1.34.176,
explicit user instruction: "Every AI/ML subsystem should itself
participate in Hearthmind's evolutionary architecture... accumulate
experience, periodically retrain from the world's history, support
variation, inheritance and adaptation... become part of the
simulation's long-term emergent ecosystem rather than remaining a
static optimization layer.")

L5 (`lifelong.py`) already gives a model ONTOGENY -- one lineage
continually learning across its own lifetime via warm-start + replay.
This module gives a model POPULATION real PHYLOGENY -- variation,
inheritance, and selection across many candidate configurations, the
same mechanism `world/ontology.py`'s `InventedConcept` already uses
for cultural concepts (a `lineage` dict of `evolved_from`/`merged_
from`, a bounded `fitness_history`, a `generation` counter) and
`agents/population.py`'s diploid `Agent.genome` already uses for
psychology traits (draw-from-a-parent-allele + mutation chance). This
is deliberately the SAME shape, not a new one -- consistent with the
project's own standing "extend existing mechanics before inventing
new ones" discipline.

  - `ModelGenome`: a model's own tunable hyperparameters (learning
    rate, hidden width, epoch count, replay fraction) as a real,
    heritable, mutable genome -- lineage/fitness_history/generation
    fields mirror `InventedConcept` exactly.
  - `mutate_genome`/`crossover_genome`: variation and inheritance --
    a child genome descends from one parent (mutation) or two
    (crossover, gene-by-gene, same "draw from one parent's allele"
    shape `agents/population.py`'s genetic inheritance already uses).
  - `GenomePopulation`: a bounded population of genome variants per
    model "species" (e.g. "workload_forecaster"); `evaluate_and_
    select` is a real (mu + lambda) evolutionary step -- score every
    genome, keep the fittest survivors, refill the rest via mutation/
    crossover of survivors. This is the adaptation mechanism the
    instruction asks for, distinct from L5's single-lineage continual
    retrain.
  - `train_and_score_genome`: the one place a genome's hyperparameters
    actually become a trained `primitives.MLP` and get scored --
    shared by every consumer so genome semantics stay consistent.

Still standalone substrate, same "never big-bang" discipline as every
other Tier 5/6 module -- nothing here is wired into a real simulated-
time-triggered evolutionary cadence or `simulation/engine.py` yet.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hearthmind.ml.primitives import MLP
from hearthmind.ml.training import mean_loss, train_mlp_sgd

FITNESS_HISTORY_MAX = 20
"""Same bound and same rationale as `world/ontology.py`'s own
`FITNESS_HISTORY_MAX` -- a rolling window, not an unbounded log."""

GENOME_HYPERPARAMETER_BOUNDS = {
    "learning_rate": (0.001, 0.05),
    "hidden_dim": (2, 16),
    "epochs": (10, 150),
    "replay_fraction": (0.0, 1.0),
}
"""The heritable genes every genome carries. Adding a new tunable
hyperparameter to a model consumer is adding one entry here, not a new
mechanism -- same "adding a field, not a pipeline" discipline L0's
`FeatureSchema` already established."""

GENOME_MUTATION_SCALE = 0.25
"""Fraction of a gene's own legal range a mutation may move it by --
bounded so mutation explores, never teleports a genome to a random
corner of the search space in one step (mirrors `agents/population.
py`'s own small-perturbation trait mutation, not a full reroll)."""


def _clamp(value: float, bounds: tuple) -> float:
    lo, hi = bounds
    return max(lo, min(hi, value))


@dataclass
class ModelGenome:
    """A model's own heritable hyperparameter set. Field shape
    deliberately mirrors `world.ontology.InventedConcept`: `lineage`
    (`{"parent_id": id|None, "parents": [id, id]|None}` for a mutation
    vs. a crossover), `fitness_history` (bounded, most-recent-last),
    `generation` (0 for an originally-seeded genome; `parent.
    generation + 1` for mutation, `max(a, b).generation + 1` for
    crossover)."""

    genome_id: str
    species: str
    hyperparameters: dict
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


_INTEGER_GENES = ("hidden_dim", "epochs")


def _draw_gene(name: str, bounds: tuple, rng: random.Random):
    lo, hi = bounds
    if name in _INTEGER_GENES:
        return rng.randint(int(lo), int(hi))
    return rng.uniform(lo, hi)


def random_genome(species: str, genome_id: str, rng: random.Random) -> ModelGenome:
    """Seeds a genesis genome (generation 0, no parents) with a
    uniformly-random legal value per gene -- the same role `agents/
    population.py`'s genesis founder trait seeding plays for the
    diploid trait genome."""
    genes = {name: _draw_gene(name, bounds, rng) for name, bounds in GENOME_HYPERPARAMETER_BOUNDS.items()}
    return ModelGenome(genome_id=genome_id, species=species, hyperparameters=genes)


def mutate_genome(parent: ModelGenome, genome_id: str, rng: random.Random, scale: float = GENOME_MUTATION_SCALE) -> ModelGenome:
    """Variation + inheritance (asexual): a child's genes are the
    parent's own genes, each independently nudged by up to `scale` of
    its legal range. Real evidence (`fitness_history`) never carries
    over -- a child's fitness is unearned, it has to prove itself."""
    child_genes = {}
    for name, value in parent.hyperparameters.items():
        lo, hi = GENOME_HYPERPARAMETER_BOUNDS[name]
        span = hi - lo
        delta = rng.uniform(-scale, scale) * span
        new_value = _clamp(value + delta, (lo, hi))
        child_genes[name] = int(round(new_value)) if name in _INTEGER_GENES else new_value
    return ModelGenome(
        genome_id=genome_id,
        species=parent.species,
        hyperparameters=child_genes,
        lineage={"parent_id": parent.genome_id, "parents": None},
        generation=parent.generation + 1,
    )


def crossover_genome(a: ModelGenome, b: ModelGenome, genome_id: str, rng: random.Random) -> ModelGenome:
    """Variation + inheritance (sexual): each gene is independently
    drawn from ONE of the two parents (uniform crossover) -- the same
    "draw from a randomly-chosen parent allele" shape `agents/
    population.py`'s diploid genetic inheritance already uses for
    psychology traits, applied here to hyperparameters instead of
    trait alleles."""
    if a.species != b.species:
        raise ValueError(f"crossover requires two genomes of the same species: {a.species!r} vs {b.species!r}")
    child_genes = {name: (a.hyperparameters[name] if rng.random() < 0.5 else b.hyperparameters[name]) for name in a.hyperparameters}
    return ModelGenome(
        genome_id=genome_id,
        species=a.species,
        hyperparameters=child_genes,
        lineage={"parent_id": None, "parents": [a.genome_id, b.genome_id]},
        generation=max(a.generation, b.generation) + 1,
    )


def genome_to_mlp(genome: ModelGenome, input_dim: int, output_dim: int = 1, output_activation: str = "linear", seed: int = 0) -> MLP:
    """The one place a genome's `hidden_dim` gene becomes a real
    network shape -- kept in one function so every genome consumer
    interprets the gene identically."""
    hidden = max(2, int(genome.hyperparameters["hidden_dim"]))
    return MLP.random_init([input_dim, hidden, output_dim], output_activation=output_activation, seed=seed)


def train_and_score_genome(genome: ModelGenome, train_examples: list, holdout_examples: list, seed: int = 0):
    """Trains a fresh model shaped by `genome` on `train_examples` and
    scores it on `holdout_examples`. Returns `(model, fitness)` where
    fitness is `1 / (1 + holdout_loss)` -- bounded (0, 1], higher is
    better, and well-defined even when loss diverges to a large value
    (never divides by zero, never inverts sign)."""
    if not train_examples:
        return None, 0.0
    input_dim = len(train_examples[0].x)
    output_dim = len(train_examples[0].y)
    model = genome_to_mlp(genome, input_dim, output_dim=output_dim, seed=seed)
    train_mlp_sgd(
        model, train_examples,
        epochs=int(genome.hyperparameters["epochs"]),
        learning_rate=genome.hyperparameters["learning_rate"],
        seed=seed,
    )
    eval_set = holdout_examples or train_examples
    loss = mean_loss(model, eval_set)
    if loss != loss:  # NaN check without importing math -- a diverged genome scores as unfit, not a crash
        return model, 0.0
    fitness = 1.0 / (1.0 + max(0.0, loss))
    return model, fitness


@dataclass
class GenomePopulation:
    """A bounded population of genome variants for one model species --
    the real adaptation mechanism: `evaluate_and_select` is a (mu +
    lambda) evolutionary step. `mu` genomes survive each generation by
    fitness; `lambda` new genomes are bred from them (mutation +
    crossover) to refill the population back to its original size."""

    species: str
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
        return f"{self.species}-g{self._next_id}"

    @classmethod
    def seed_random(cls, species: str, size: int, mu: int, seed: int = 0) -> "GenomePopulation":
        rng = random.Random(seed)
        pop = cls(species=species, genomes=[], mu=mu, seed=seed)
        pop.genomes = [random_genome(species, pop._fresh_id(), rng) for _ in range(size)]
        return pop

    def evaluate_and_select(self, fitness_fn) -> None:
        """`fitness_fn(genome) -> float`. Scores every genome, records
        the reading into each genome's own `fitness_history` (so a
        genome's evolutionary track record persists across
        generations even if it's later bred from again), keeps the
        `mu` fittest as survivors, and refills the population back to
        its original size by breeding new genomes from the survivors
        -- half by mutation, half by crossover between two distinct
        survivors when there are at least two."""
        size = len(self.genomes)
        for genome in self.genomes:
            genome.record_fitness(fitness_fn(genome))

        ranked = sorted(self.genomes, key=lambda g: g.fitness_history[-1], reverse=True)
        survivors = ranked[: min(self.mu, len(ranked))]

        offspring = []
        while len(survivors) + len(offspring) < size:
            if len(survivors) >= 2 and self._rng.random() < 0.5:
                a, b = self._rng.sample(survivors, 2)
                offspring.append(crossover_genome(a, b, self._fresh_id(), self._rng))
            else:
                parent = self._rng.choice(survivors)
                offspring.append(mutate_genome(parent, self._fresh_id(), self._rng))

        self.genomes = survivors + offspring

    def best(self):
        scored = [g for g in self.genomes if g.fitness_history]
        if not scored:
            return None
        return max(scored, key=lambda g: g.fitness_history[-1])
