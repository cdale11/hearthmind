"""A20 "Multi-scale simulation" (docs/MASTERCHECKLIST-2026-07-22.md,
Part A #20), closing the item's second named example: "'culture'
aggregates settlements' information-ecosystems." `population_density`
(A1's `world/fields.py`) already proved the pattern once — a region is
a computed summary of its tiles' own state, not separately simulated —
but nothing did the same one level up: a world with several settlements
had no computed reading of what they collectively add up to, only N
independent per-settlement culture objects.

Deliberately NOT a new simulation: every field this module reads
already exists (`Settlement.culture_effects`, `.religion`, `.legends`,
`.traditions_established`) — this is a pure aggregation function over
already-real state, the same "compute, don't simulate" shape
`step_population_density` established for tiles.

A17 follow-up (docs/ROADMAP-2026-07-REMAINING.md, "Information
ecosystem unification"): the optional `agents` param folds in
`Agent.kept_traditions` (`SimulationEngine._maybe_spread_tradition_
keeping`, `world/memetics.py`'s second real production consumer) —
how many people actually personally keep a tradition, distinct from
`total_traditions_established`'s bare count of how many exist on
paper. A settlement can have traditions nobody really lives by; this
is the reading that tells the two apart.
"""
from __future__ import annotations

TRADITION_ENGAGEMENT_COHESION_WEIGHT = 0.15
"""How much personal tradition-keeping can raise `cultural_cohesion`
above what the settlement-level dominant-influence agreement alone
gives it — real but deliberately modest: a civilization where everyone
personally lives by their local traditions reads as somewhat MORE
unified than the bare settlement-level category-agreement number
alone would say, but this should never be the dominant signal (a
single, tiny founding party where everyone happens to keep the same
one tradition shouldn't read as a fully cohesive civilization on its
own)."""


def compute_civilization_culture(settlements: list, agents: list | None = None) -> dict:
    """One world-scale reading of the collective culture every named
    settlement has independently accumulated. Unnamed settlements (no
    standing building yet, no culture to speak of) are excluded, same
    "nothing to report" discipline every per-settlement culture job
    already uses for an unfounded settlement.

    `dominant_influence`: the `culture.TRADITION_INFLUENCES` category
    most settlements lean toward (by summed `culture_effects` stacks,
    "none" excluded) — "" if no settlement has a leaning tradition yet.
    `cultural_cohesion`: 0..1, the fraction of named settlements that
    share that SAME dominant category — a genuine aggregate measure of
    how unified (vs. locally divergent) the wider civilization's
    culture is, not a per-settlement number.
    `religions_formed`/`total_legends`/`total_traditions_established`:
    straightforward world-wide sums/counts over already-real per-
    settlement state — the "coherent world-scale story from local
    rules" the spec's own Feeds line asks for.
    `tradition_keeping_rate`: 0..1, the fraction of living agents in a
    named settlement who personally keep at least one tradition
    (`Agent.kept_traditions`, only computed when `agents` is passed) —
    0.0 (not "no data") when `agents` is omitted, same "absence reads
    as neutral" discipline every other optional axis in this codebase
    holds. Nudges `cultural_cohesion` up by at most `TRADITION_
    ENGAGEMENT_COHESION_WEIGHT`, never replacing the settlement-level
    agreement signal."""
    named = [s for s in settlements if s.name]
    if not named:
        return {
            "settlements_considered": 0, "dominant_influence": "", "cultural_cohesion": 0.0,
            "religions_formed": 0, "total_legends": 0, "total_traditions_established": 0,
            "tradition_keeping_rate": 0.0,
        }

    world_influence_totals: dict[str, int] = {}
    settlement_dominant: dict[int, str] = {}
    for s in named:
        effects = {k: v for k, v in s.culture_effects.items() if k != "none" and v > 0}
        for influence, stacks in effects.items():
            world_influence_totals[influence] = world_influence_totals.get(influence, 0) + stacks
        if effects:
            settlement_dominant[s.id] = max(effects.items(), key=lambda kv: kv[1])[0]

    dominant_influence = ""
    cultural_cohesion = 0.0
    if world_influence_totals:
        dominant_influence = max(world_influence_totals.items(), key=lambda kv: kv[1])[0]
        sharing = sum(1 for v in settlement_dominant.values() if v == dominant_influence)
        cultural_cohesion = round(sharing / len(named), 3)

    named_ids = {s.id for s in named}
    tradition_keeping_rate = 0.0
    if agents:
        counted = [a for a in agents if a.settlement_id in named_ids]
        if counted:
            keepers = sum(1 for a in counted if a.kept_traditions)
            tradition_keeping_rate = round(keepers / len(counted), 3)
    if tradition_keeping_rate > 0.0:
        cultural_cohesion = min(
            1.0, round(cultural_cohesion + TRADITION_ENGAGEMENT_COHESION_WEIGHT * tradition_keeping_rate, 3),
        )

    return {
        "settlements_considered": len(named),
        "dominant_influence": dominant_influence,
        "cultural_cohesion": cultural_cohesion,
        "religions_formed": sum(1 for s in named if s.religion is not None),
        "total_legends": sum(len(s.legends) for s in named),
        "total_traditions_established": sum(s.traditions_established for s in named),
        "tradition_keeping_rate": tradition_keeping_rate,
    }


CIVILIZATION_INFLUENCE_LABELS: dict[str, str] = {
    "festivity": "shared festivity", "harvest": "shared harvest custom",
    "resilience": "shared endurance", "knowledge": "shared craft and teaching",
}
"""Plain-language rendering of `compute_civilization_culture`'s
`dominant_influence`, for prompts/UI that want a sentence, not a raw
category key — same convention as `world/spatial_memory.py`'s
`LOCATION_CHARACTER_LABELS`."""


def civilization_culture_text(aggregate: dict) -> str:
    """A short plain-English clause describing the civilization's
    collective culture, or `""` if there's nothing to report yet (no
    named settlement, or none has leaned toward any tradition
    category). Meant to drop straight into a prompt or a UI line."""
    if not aggregate.get("dominant_influence"):
        return ""
    label = CIVILIZATION_INFLUENCE_LABELS.get(
        aggregate["dominant_influence"], aggregate["dominant_influence"],
    )
    cohesion = aggregate.get("cultural_cohesion", 0.0)
    if cohesion >= 0.75:
        return f"the wider civilization is bound by {label}"
    if cohesion >= 0.4:
        return f"much of the civilization leans toward {label}"
    return f"the civilization's culture is divided, though {label} runs strongest"
