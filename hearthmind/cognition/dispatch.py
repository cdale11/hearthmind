"""Tier 7 HCA Stage C, C3 (docs/ROADMAP-2026-07-REMAINING.md, Phase 5,
explicit user instruction "Start C3" — closes Stage C in full): cheap-
resolver dispatch, preferring the cheapest resolver that suffices.

docs/COGNITIVE-ARCHITECTURE-2026-08-02.md §3/Layer 3: "the winner is
resolved by whichever of three resolvers is adequate: a cached chunk,
a learned model, or the LLM. Only the third is expensive." This module
is that real ladder, over C1's `Impasse` and C2's `ChunkStore`:

    1. cached chunk  -- C2's `ChunkStore.lookup()`. Free (an O(1) dict
       read). If the SAME impasse (by C2's own `chunk_signature`) has
       already been resolved once, reuse that resolution -- no model,
       no LLM, no deliberation at all.
    2. learned model  -- an optional caller-supplied resolver (this
       codebase's own `hearthmind.ml.specialist.LearningSpecialist`/
       Tier 6 model family is the real candidate a future caller would
       pass in; genuinely optional here, since not every impasse has a
       trained model backing it yet).
    3. the LLM        -- the caller's own real deliberation (a real
       `_schedule_llm_job`-shaped call). Only ever reached when neither
       cheaper resolver could answer. Its result is compiled into a
       NEW chunk (`ChunkStore.compile`) so the identical impasse never
       has to pay this cost again.

`dispatch_impasse` is the one real function this module ships --
it never invents a new resolution of its own; it only decides WHICH
already-real resolver answers a given impasse, cheapest first, and
records the outcome (`DispatchOutcome.resolved_via`) so a caller (or a
future E4 learning-chart panel) can measure how often deliberation was
actually avoided.

Deliberately NOT wired into any real production `_schedule_llm_job`
call site this pass -- same "ship the interface, wire the first real
consumer next" discipline C1/C2 (and every prior Stage A/B/G/H item in
this codebase) already used. C3's own stated test (">30% of workspace
winners resolve without an LLM call") describes a measurement over a
REAL production soak once a real job is retrofitted to call this
dispatcher instead of unconditionally scheduling its LLM job -- that
retrofit is real, distinct future work (picking one low-risk ambient
job, the same "first pilot, then a sweep" shape B0.3/W1-W4 already
used elsewhere in this codebase), not attempted here. What ships now
is verified against real `Impasse`/`Chunk` objects and a statistical
proof that repeated impasses genuinely converge to the >30% bar this
item names, in `scripts/verify_c3_dispatch.py`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from hearthmind.cognition.chunk import Chunk, ChunkStore
from hearthmind.cognition.impasse import Impasse

RESOLVED_VIA_KINDS: tuple[str, ...] = ("chunk", "model", "llm")
"""The three real resolver tiers, cheapest first -- a closed
vocabulary, same "closed vocabulary, open content" discipline C2's own
`ARTIFACT_KINDS` already established."""


@dataclass
class DispatchOutcome:
    """The real record of how one impasse was actually resolved --
    never fabricated; `resolved_via` always names the resolver that
    genuinely produced `resolution`. `chunk` is the real `Chunk`
    consulted (a hit) or newly compiled (an LLM resolution, once
    `compile_llm_results=True`) -- `None` only when a `model` resolver
    answered, since a learned-model result is cheap enough it isn't
    chunked (chunking exists to skip the EXPENSIVE resolver, and the
    model tier already is the cheap one below it)."""

    impasse: Impasse
    resolved_via: str
    resolution: object
    chunk: Chunk | None = None


def dispatch_impasse(
    impasse: Impasse,
    store: ChunkStore,
    tick: int,
    llm_resolver: Callable[[], object],
    model_resolver: Callable[[], object] | None = None,
    llm_artifact_kind: str = "cached_decision",
    ttl_ticks: int | None = None,
) -> DispatchOutcome:
    """The real cheap-resolver ladder. `llm_resolver` is always
    required (there must always be a genuine fallback answer, per this
    project's own "every LLM call needs some non-blocking resolution"
    discipline) -- it is the ONLY resolver ever called unconditionally
    without a cheaper option checked first, and it is the only path
    that ever compiles a new chunk (a model or chunk-hit resolution is
    already cheap; nothing is gained by caching it again).
    `model_resolver` is optional -- most impasses have no trained model
    backing them yet, and skipping this tier when unavailable is
    correct, not a fallback failure.

    `ttl_ticks` (Phase 3): forwarded straight to `store.compile()` --
    `None` (every pre-Phase-3 caller) compiles a chunk that never
    expires; a real value bounds how long an LLM-tier resolution here
    gets trusted before the identical impasse pays for a fresh
    deliberation again. `tick` is always passed to `store.lookup()`
    now (previously it wasn't accepted there at all), so any caller
    supplying a real `ttl_ticks` gets real expiry enforcement for
    free -- a caller that never sets `ttl_ticks` sees no behavior
    change at all, since every one of its own compiled chunks still
    has `expires_at_tick=None`."""
    chunk = store.lookup(impasse, tick)
    if chunk is not None:
        store.record_hit(chunk, tick)
        return DispatchOutcome(impasse=impasse, resolved_via="chunk", resolution=chunk.resolution, chunk=chunk)

    if model_resolver is not None:
        resolution = model_resolver()
        return DispatchOutcome(impasse=impasse, resolved_via="model", resolution=resolution)

    resolution = llm_resolver()
    new_chunk = store.compile(impasse, llm_artifact_kind, resolution, tick, ttl_ticks)
    return DispatchOutcome(impasse=impasse, resolved_via="llm", resolution=resolution, chunk=new_chunk)
