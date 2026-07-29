"""Reflection 5.C / vision doc item 1.3, docs/VISION-2026-07-22-
LIVINGTERRARIUM.md: "test the hypothesis in a jar" — before a proposed
rule with a real mechanical effect goes live, run it forward on a
disposable, deep-copied fork of the current world for a small bounded
number of ticks (LLM forced off — this is a physical/invariant check,
not a cognition test) and verify it doesn't break an invariant
(population collapse/explosion/extinction, resource explosion). Never
mutates the real `World`; the fork and its throwaway in-memory DB
connection are both discarded when this returns.

Item 5.2 ("invariant guards around self-modification... population
can't be driven to 0, resources can't explode, no governor can be
disabled") is folded in here rather than built as a separate module —
this IS the one place a proposal's consequences get checked before
going live, so the hard floors/ceilings belong exactly where the soft
crash/explosion checks already live, not a second parallel gate.
`POPULATION_HARD_FLOOR` is unconditional (never gated on the crash
fraction — literal extinction is always rejected regardless of how
small the starting population was) and `RESOURCE_EXPLOSION_MULTIPLE`
mirrors the population-explosion check for total settlement materials.
"No governor can be disabled" is enforced structurally, not by a
runtime check here: a `TriggerRule`'s `hook_type` is drawn from the
closed `MECHANICAL_HOOK_TYPES` vocabulary (`ontology.validate_hook`),
none of which reads or writes `Config` — there is no vector through
which a proposal could reach a governor at all, so there's nothing for
this sandbox to catch on that axis. Coherence/drift detection (item
5.3) is a separate, larger vision-doc item, not attempted here."""
from __future__ import annotations

import asyncio
from dataclasses import replace

from hearthmind.persistence.database import connect
from hearthmind.world.state import World

SANDBOX_TICKS = 50
"""How far forward to simulate before judging — long enough for a
population-affecting effect to show real drift, short enough to stay
a cheap synchronous check (~50 ticks at the ~1ms/tick order of
magnitude CLAUDE.md's own architecture review measured) run inline
inside an LLM-job `apply` callback, which executes on the same event
loop the tick timer and other background LLM calls share."""

POPULATION_CRASH_FRACTION = 0.5
"""A sandboxed run that loses more than this fraction of its starting
population within SANDBOX_TICKS is judged unsafe."""

POPULATION_EXPLOSION_MULTIPLE = 3.0
"""...or grows beyond this multiple of its starting population — the
other direction of the same collapse/explosion invariant."""

POPULATION_HARD_FLOOR = 0
"""Item 5.2's unconditional invariant: population reaching exactly
this many agents is ALWAYS unsafe, independent of `POPULATION_CRASH_
FRACTION` — a world that started with only 2-3 agents could lose 100%
without ever tripping the fractional check (2 -> 0 is a 100% loss, but
so is a fractional check with a small denominator behaving oddly at
the edges); this is the literal "can't be driven to 0" floor the
vision doc names, checked first and separately."""

RESOURCE_EXPLOSION_MULTIPLE = 5.0
"""Item 5.2's resource-side invariant, the same shape as `POPULATION_
EXPLOSION_MULTIPLE` applied to total settlement materials — a real
"resources can't explode" ceiling. Looser than the population multiple
since materials legitimately swing harder tick-to-tick (a single big
harvest or caravan trade) than population ever does."""


async def run_counterfactual(world: World, config, ticks: int = SANDBOX_TICKS) -> dict:
    """Returns `{"safe": bool, "reason": str, "population_start": int,
    "population_end": int | None}`. `population_end` is `None` only if
    the fork raised an exception mid-run (also judged unsafe). `async`
    (called from inside an LLM job's `apply` callback, itself already
    running on the event loop) so any background task the sandbox's
    OWN throwaway `SimulationEngine` schedules (its `CognitionRunner`
    still runs with `llm_enabled=False`, resolving instantly via
    fallback, but still as a real `asyncio.create_task`) gets cancelled
    and awaited before the throwaway DB connection closes underneath
    it — same shutdown-drain pattern `run_forever`'s `finally` block
    uses for the real engine."""
    from hearthmind.simulation.engine import SimulationEngine  # local: avoid an import cycle at module load

    sandbox_config = replace(config, llm_enabled=False)
    forked_world = World.from_dict(world.to_dict(), sandbox_config)
    population_start = len(forked_world.population.agents)
    materials_start = sum(s.materials for s in forked_world.settlements)
    conn = connect(":memory:")
    engine = SimulationEngine(conn, sandbox_config, forked_world)
    try:
        try:
            for _ in range(ticks):
                engine._tick_once()
                # `_tick_once` is fully synchronous — with no yield point
                # in this loop, a real-world ~1.7s/150-tick sandbox run
                # (measured) would freeze the ENTIRE event loop for that
                # whole stretch: the real tick loop can't advance, no LLM
                # I/O can resolve, no broadcast can go out. One `sleep(0)`
                # per tick costs negligible overhead against a ~ms-scale
                # tick but turns a hard freeze into cooperative
                # interleaving — the real engine's own `run_forever` gets
                # a chance to run between fork ticks instead of after all
                # of them (found via live measurement, v1.34.86, after a
                # user question about A8's dual-fork cost).
                await asyncio.sleep(0)
        except Exception as exc:
            return {
                "safe": False, "reason": f"raised {type(exc).__name__}: {exc}",
                "population_start": population_start, "population_end": None,
            }
    finally:
        if engine._background_tasks:
            for task in engine._background_tasks:
                task.cancel()
            await asyncio.gather(*engine._background_tasks, return_exceptions=True)
        conn.close()
    population_end = len(forked_world.population.agents)
    materials_end = sum(s.materials for s in forked_world.settlements)
    if population_start > POPULATION_HARD_FLOOR and population_end <= POPULATION_HARD_FLOOR:
        return {
            "safe": False, "reason": f"population driven to extinction {population_start} -> {population_end}",
            "population_start": population_start, "population_end": population_end,
        }
    if population_start > 0 and population_end < population_start * (1 - POPULATION_CRASH_FRACTION):
        return {
            "safe": False, "reason": f"population crashed {population_start} -> {population_end}",
            "population_start": population_start, "population_end": population_end,
        }
    if population_start > 0 and population_end > population_start * POPULATION_EXPLOSION_MULTIPLE:
        return {
            "safe": False, "reason": f"population exploded {population_start} -> {population_end}",
            "population_start": population_start, "population_end": population_end,
        }
    if materials_start > 0 and materials_end > materials_start * RESOURCE_EXPLOSION_MULTIPLE:
        return {
            "safe": False, "reason": f"materials exploded {materials_start:.1f} -> {materials_end:.1f}",
            "population_start": population_start, "population_end": population_end,
        }
    return {
        "safe": True, "reason": "within invariants",
        "population_start": population_start, "population_end": population_end,
    }


CONCEPT_FITNESS_SANDBOX_TICKS = 150
"""A8's dual-fork causal check (`evaluate_concept_dual_fork`) runs
3x longer than `SANDBOX_TICKS` — a population-mediated effect (a
concept's adopters attracting more migrants via `FieldGrid.
cultural_influence`) needs real time to compound into a visible
headcount difference, unlike the fast crash/explosion invariant
checks `run_counterfactual` looks for. Still bounded/synchronous
enough to run inline from an LLM job's `apply` callback (this
function is only ever awaited from inside a background task, never
blocking a real tick)."""


async def evaluate_concept_dual_fork(
    world: World, config, concept_id: int, ticks: int = CONCEPT_FITNESS_SANDBOX_TICKS,
) -> float | None:
    """A8 "Evolutionary Innovation," the comparative dual-fork the
    roadmap's own audit (v1.34.84) flagged as the only way to make
    "sandbox forward-simulation as a fitness input" genuinely
    meaningful rather than a rubber stamp: `InventedConcept.
    mechanical_hook` is never consumed as a numeric effect
    (`_apply_trigger_rule_hook`'s own docstring), so a naive
    with-vs-without-the-CONCEPT fork would always diff to zero. The
    one real causal pathway concept adoption has on simulation
    dynamics instead runs through `adopter_ids`: `World.tick()` unions
    every concept's adopters into `FieldGrid.step_cultural_influence`,
    which gives `Population._maybe_welcome_migrant` a real positive
    `MIGRANT_CULTURAL_PULL` pull in the region(s) adopters stand in.

    Forks the world TWICE — once with the concept's real current
    `adopter_ids`, once with that set stripped to empty for this
    concept only — and runs both forward for `ticks` (LLM disabled,
    same disposable-fork discipline as `run_counterfactual`). Returns
    `population_with - population_without`, or `None` if the concept
    has no adopters to strip (nothing to compare) or doesn't exist.

    Why a nonzero delta is a genuine causal signal and not just two
    independent noisy runs: every RNG draw in this codebase is
    `_namespaced_rng`/`_namespaced_roll`, keyed by `(seed, tick_count,
    ...)` — never by call order or any state that differs between the
    two forks before their first divergent roll. Both forks share the
    exact same seed and start from the exact same `World.to_dict()`
    snapshot, so every roll VALUE is identical between them up until a
    roll that itself reads `cultural_influence` (a migrant-arrival
    chance check) actually straddles a threshold the two forks'
    differing field values put on opposite sides. A population
    difference is that threshold tipping, not sampling noise — the
    same "shared-RNG-stream forks make a diff meaningful" property
    `run_counterfactual`'s single-fork invariant checks don't need
    but a genuine A-vs-B comparison does.

    A raised exception in either fork is treated as "nothing learned"
    (`None`), same as an unevaluable `evaluate_fitness` reading —
    never propagated into the caller's async task."""
    concept = world.invented_concepts.get(concept_id)
    if concept is None or not concept.adopter_ids:
        return None
    from hearthmind.simulation.engine import SimulationEngine  # local: avoid an import cycle at module load

    sandbox_config = replace(config, llm_enabled=False)
    base_snapshot = world.to_dict()

    async def _run_fork(strip_adoption: bool) -> int | None:
        forked_world = World.from_dict(base_snapshot, sandbox_config)
        if strip_adoption:
            forked_concept = forked_world.invented_concepts.get(concept_id)
            if forked_concept is not None:
                forked_concept.adopter_ids = set()
        conn = connect(":memory:")
        engine = SimulationEngine(conn, sandbox_config, forked_world)
        try:
            try:
                for _ in range(ticks):
                    engine._tick_once()
                    # See `run_counterfactual`'s matching comment — this
                    # fork runs 2x `ticks` total (both `_run_fork` calls)
                    # with no yield point in the loop; measured at ~12ms/
                    # tick, an unyielded pair of 150-tick forks freezes
                    # the real event loop for several real seconds. This
                    # doesn't shrink the fork's own wall-clock cost, it
                    # just stops it from also freezing the real tick loop
                    # and any in-flight LLM I/O while it runs.
                    await asyncio.sleep(0)
            except Exception:
                return None
        finally:
            if engine._background_tasks:
                for task in engine._background_tasks:
                    task.cancel()
                await asyncio.gather(*engine._background_tasks, return_exceptions=True)
            conn.close()
        return len(forked_world.population.agents)

    population_with = await _run_fork(strip_adoption=False)
    population_without = await _run_fork(strip_adoption=True)
    if population_with is None or population_without is None:
        return None
    return float(population_with - population_without)
