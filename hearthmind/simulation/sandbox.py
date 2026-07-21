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
