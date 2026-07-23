"""A17 (docs/MASTERCHECKLIST-2026-07-22.md, roadmap step 24), first
slice: "Information as a deterministic ecosystem — unify knowledge/
rumor/tradition/belief/song/custom/technique into one propagation
model on the social graph... each unit spreads... by the same rules."

Scoped down hard, per this project's standing "first slice, not the
full spec" discipline. The full vision is a single decay/mutate/
compete/merge pipeline shared by every one of those seven content
types — that's a large, genuinely risky rewrite of several independent
mature mechanisms (rumor distortion, invention_knowledge's teach/lose/
rediscover, ontology lineage) and is NOT attempted here.

What ships: the one piece every future propagation mechanism actually
needs and none of today's have — a shared, reusable "who catches this
next" weighting that traces the real relationship graph (`Agent.
relationships`/`.trust`, the Ledger from Phase 0) instead of picking a
next carrier uniformly at random. Real production proof: `world/
ontology.py`'s concept adoption spread (previously `rng.choice` over
every eligible core-cast member with zero regard for who was already
an adopter) now spreads preferentially to people close to an existing
adopter — a friend of an adopter is measurably more likely to pick up
a new custom/technology next than a stranger is, closing a real gap
("propagation on the social graph" was previously just uniform
sampling with a social-graph-shaped docstring).

Deliberately NOT attempted this pass (flagged, matching the doc's own
still-open list): folding rumor/tradition/belief/song/technique onto
this same function, a shared mutate/decay/compete step, or "false
beliefs propagate if fit" (no fitness-vs-truth axis exists yet for
rumors). This module is the propagation-weight primitive the full
unification would need next, not the unification itself.
"""

from __future__ import annotations

import random

PROPAGATION_FONDNESS_WEIGHT = 0.7
PROPAGATION_TRUST_WEIGHT = 0.3
"""How strongly a candidate's fondness-for/trust-in an existing
carrier pulls them toward being the next one. Fondness weighted higher
than trust — "I like this person and want to be like them" is a
stronger real-world spread vector than "I trust their judgment"."""

PROPAGATION_BASELINE_WEIGHT = 0.15
"""A candidate with no measured tie to any carrier — or when there are
no carriers yet at all (a brand-new idea's very first spread) — still
keeps a real, non-zero chance: word travels beyond direct friendship,
and gating spread entirely on an existing edge would make an idea with
zero starting adopters unable to ever begin spreading."""


def carrier_tie_strength(carrier, candidate) -> float:
    """One carrier's pull on one candidate, from the CARRIER's own
    ledger view (directional, matching `LedgerEdge`'s own directional
    semantics) — how fond of / trusting toward the candidate the
    carrier already is. Floored at 0: an existing carrier who dislikes
    a candidate exerts no pull, never a negative one (a rumor that
    reaches an enemy doesn't recruit them, it just doesn't help)."""
    fondness = carrier.relationships.get(candidate.id, 0.0)
    trust = carrier.trust.get(candidate.id, 0.0)
    raw = fondness * PROPAGATION_FONDNESS_WEIGHT + trust * PROPAGATION_TRUST_WEIGHT
    return max(0.0, raw)


def propagation_weight(candidate, carriers: list) -> float:
    """A candidate's total pull toward becoming the next carrier —
    the strongest single tie among all current carriers (the closest
    friend already carrying the idea matters more than the average of
    everyone who has it), plus the baseline floor above."""
    if not carriers:
        return PROPAGATION_BASELINE_WEIGHT
    tie = max(carrier_tie_strength(carrier, candidate) for carrier in carriers)
    return PROPAGATION_BASELINE_WEIGHT + tie


def weighted_spread_target(candidates: list, carriers: list, rng: random.Random):
    """Pick the next carrier from `candidates`, weighted by real
    social-graph closeness to `carriers` (existing carriers may be
    empty — e.g. a concept's very first adopter — which degrades to
    uniform selection via the baseline weight). Returns `None` for an
    empty candidate list."""
    if not candidates:
        return None
    weights = [propagation_weight(candidate, carriers) for candidate in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]
