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
this same function. This module is the propagation-weight primitive
the full unification would need next, not the unification itself.

**Two more slices shipped on explicit user instruction ("A17 — build
both remaining pieces"), each scoped to sidestep the risk that had
kept it flagged rather than ignoring the flag:**

`rumor_fitness`/`rumor_truth_score` ("false beliefs propagate if fit,
not suppressed for being false"): the prior audit's concern was that a
fitness-vs-truth axis needs a ground-truth value per rumor, which
would cut against Phase G's standing principle that belief never has
to reconcile with objective reality. Sidestepped by never measuring
against objective reality at all — `rumor_truth_score` measures
textual fidelity to what was ORIGINALLY SAID (the rumor as first
heard, via `SimulationEngine._maybe_interpret_rumor`'s InterpretRumor()
retelling), never against the state of the world. `rumor_fitness` is a
closed-vocabulary "how dramatic does this retelling read" heuristic,
computed independently of truth_score. Real consumer:
`Population._apply_rumor_retelling_fitness` polarizes the reteller's
OWN opinion of whoever their retelling names, scaled by fitness alone
— truth_score is tracked (`World.rumor_retellings_recent`, dev-console
only) but deliberately plays no role in the nudge, so a dramatic-but-
distorted retelling entrenches opinion exactly as readily as a
faithful-but-dull one would.

`find_near_duplicate`/`prune_aged_entries` (the shared decay/compete
step): the prior audit found two candidate sites, `Settlement.
lexicon` and `recent_topics`/`top_topics()`, and flagged BOTH —
lexicon because its only reader was confirmed dead code (nothing to
prove the mechanism against), `top_topics()` because touching it
risked destabilizing v0.87.35's live-tuned topic-diversity mechanism
without a fresh live-diagnostic read (unavailable in this
environment). Resolved by wiring the safe direction only:
`find_near_duplicate` is now a real "compete" step in `record_topic`
itself — a near-restatement of a recently-seen topic collapses to the
EXISTING phrasing instead of being tallied as a second, separately-
counted entry. This doesn't touch any of v0.87.35's actual tuned
constants (novelty thresholds, category weights, pick counts) — if
anything it makes the existing exact-string dominant-topic gate in
`_apply_pending_dialogue_results` MORE accurate (a topic phrased two
ways no longer silently evades it), a plausible improvement, not a
destabilization, reasoned through without needing a live read.
`Settlement.lexicon` gets both: `find_near_duplicate` on a coinage's
MEANING (a near-synonymous idea competes with, rather than duplicates,
an already-coined term) and `prune_aged_entries` as a genuine age-
based decay (distinct from the existing flat `LEXICON_MAX_STORED`
count cap) — both riding the lexicon's own existing append call sites,
zero new cadence.
"""

from __future__ import annotations

import random

from hearthmind.cognition.pillar import word_overlap

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


def find_near_duplicate(text: str, existing: list[str], threshold: float) -> str | None:
    """A17's shared "compete" step: a near-restatement of something
    already tracked (Jaccard word overlap >= `threshold`) collapses to
    the EXISTING phrasing rather than being tracked as a genuinely
    separate second entry — the established phrasing "wins" a
    near-duplicate contest. Returns `None` if `text` is genuinely
    novel against everything in `existing`. Generic over any
    string-keyed tracker; see the module docstring for the two real
    consumers (`SettlementCulture.record_topic`, `Settlement.lexicon`
    coinage)."""
    for candidate in existing:
        if candidate and word_overlap(text, candidate) >= threshold:
            return candidate
    return None


def prune_aged_entries(entries: list, tick_of, current_tick: int, max_age_ticks: int) -> list:
    """A17's shared "decay" step over any tick-stamped tracker — drops
    an entry once it's older than `max_age_ticks`, distinct from a
    flat count-based cap (a tracker can decay AND still be well under
    its max-stored count). `tick_of` reads an entry's own recorded
    tick (e.g. `lambda e: e["formed_tick"]`)."""
    return [e for e in entries if current_tick - tick_of(e) <= max_age_ticks]


RUMOR_FITNESS_KEYWORDS = frozenset({
    "death", "died", "dying", "dead", "secret", "betray", "betrayed",
    "betrayal", "affair", "curse", "cursed", "scandal", "forbidden",
    "stolen", "theft", "feud", "vanished", "disappeared", "haunt",
    "haunted", "omen", "grudge", "revenge", "murder", "conspiracy",
    "shameful", "disgrace",
})
RUMOR_FITNESS_KEYWORD_WEIGHT = 0.15
RUMOR_FITNESS_BASE = 0.25
"""A17's "false beliefs propagate if fit" axis. `rumor_fitness`: a
small closed vocabulary of dramatic/scandalous words, each present
word bumping the score — deliberately crude (this is "how gossip-worthy
does this READ," not a claim about anything real) and, crucially,
computed with zero reference to `rumor_truth_score` below — the two
are independent by construction, which is the entire point of the
axis. Base + per-keyword weight, capped at 1.0."""


def rumor_fitness(text: str) -> float:
    """How "spreadable" a retold rumor reads on its face, independent
    of whether it stayed faithful to what was actually said."""
    words = {w.strip(".,!?;:'\"") for w in text.lower().split()}
    hits = len(words & RUMOR_FITNESS_KEYWORDS)
    return min(1.0, RUMOR_FITNESS_BASE + hits * RUMOR_FITNESS_KEYWORD_WEIGHT)


def rumor_truth_score(original: str, retelling: str) -> float:
    """How faithfully a retelling stuck to the rumor as originally
    heard — deliberately NOT a claim about objective reality. Phase
    G's "belief never has to reconcile with objective reality"
    principle is untouched by this: it measures textual fidelity to
    what was actually SAID, never to the state of the world, and nothing
    downstream is allowed to use this score to correct anyone's belief
    (see `rumor_fitness`'s docstring — the two never interact)."""
    return word_overlap(original, retelling)
