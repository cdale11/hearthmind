"""A1's `beauty` field (docs/ROADMAP-2026-07-REMAINING.md, Tier 1) —
the one `FieldGrid` field in this codebase that is NOT a live re-read
of already-real deterministic state. Explicit user decision via
`AskUserQuestion` (v1.34.74), choosing between a deterministic
composite (fertility/pollution/scars blended), skipping the field
entirely, or a genuinely new subjective mechanic: "New subjective
agent-vote signal." This module is that mechanic.

A small, cheap per-agent roll (`BEAUTY_APPRAISAL_CHANCE_PER_TICK`) lets
an agent occasionally appraise the tile they currently stand on —
water proximity, biome variety in the immediate neighborhood, and
absence of mining/disaster scarring all read as real environmental
"is this a nice place" signals, the same physical cues a person would
actually notice. The appraisal is genuinely SUBJECTIVE, not a pure
function of the tile: it's nudged by the voting agent's own
`TRAIT_OPENNESS` (`BEAUTY_OPENNESS_INFLUENCE`) — a more open-minded
person rates scenery more generously than a guarded one standing on
the identical tile, exactly the same real trait `TRAIT_OPENNESS_
MIGRANT_WELCOME_INFLUENCE` already lets shape how readily a settlement
welcomes strangers.

Individual votes are folded into `World.aesthetic_appraisal`, a
persistent 3x3 per-region exponential moving average (`BEAUTY_VOTE_
SMOOTHING`) — a REAL accumulator that remembers past votes and drifts
slowly as opinion shifts, not a value recomputed from scratch each
tick. Seeded at a neutral 0.5 everywhere (an unvoted region has no
opinion yet, not "objectively ugly" — deliberately NOT the "absence
means zero" convention every other field here uses, since this is a
running belief, not a live census).

R7 ("new physical-substrate code is C++-first") deviation, audited and
confirmed this pass (Tier 7 HCA B6 turn's parallel-track check): same
documented shape as `world/minerals.py`'s own flagged deviation — a
native port is a reasonable follow-up once/if this proves worth the
engineering cost, not attempted given the genuinely low real density.
`BEAUTY_APPRAISAL_CHANCE_PER_TICK=0.02` means the per-tick vote count
stays roughly constant (~1 vote/tick at a 50-agent settlement)
REGARDLESS of population size — this is the opposite shape from every
already-ported per-tick module in `cpp/src/` (needs/emotion/relationship
step, farm/wildlife/settlement ticks), each of which scales with
population or grid size and therefore has real throughput to gain from
a native port. A flat, population-independent low-frequency roll has
no such throughput to reclaim."""
from __future__ import annotations

import random

from hearthmind.agents.agent import TRAIT_OPENNESS
from hearthmind.world.terrain import Biome, Tile

BEAUTY_APPRAISAL_CHANCE_PER_TICK = 0.02
"""Cheap per-agent per-tick roll — at a settlement of ~50 agents this
averages roughly one vote per tick, enough for the field to visibly
respond within a season without scanning every agent's full appraisal
every tick (the cost this whole mechanic is designed to stay well
under, since it's the one FieldGrid field with genuinely new per-tick
per-agent work, unlike every sibling field's zero-added-cost re-read of
state something else already computes)."""

BEAUTY_VOTE_SMOOTHING = 0.08
"""Exponential-smoothing rate applied to `World.aesthetic_appraisal` on
each accepted vote — a single vote nudges a region's running average by
at most 8% of the gap to that vote's own score, so genuine consensus
(many similar votes) moves the reading meaningfully while one outlier
opinion barely dents it. Same "many small nudges over many ticks, no
value ever fully replaced" shape `bounded_random_walk_step` establishes
elsewhere in this codebase."""

BEAUTY_OPENNESS_INFLUENCE = 0.12
"""How much a voting agent's own `TRAIT_OPENNESS` (-1..1) shifts their
appraisal of the SAME tile relative to a neutral (0.0-openness) agent —
the subjective half of this mechanic. Small and additive, never enough
to turn an objectively poor tile into a rave review on its own."""

BEAUTY_WATER_BONUS = 0.15
"""A tile with a water biome (river/lake/coast) in its 3x3 appraisal
neighborhood reads as more scenic — the single most universal "nice
view" cue a real landscape offers."""

BEAUTY_SCENIC_BIOME_BONUS = 0.1
"""The tile itself being FOREST/HILLS/MOUNTAIN/SNOWCAP/WETLAND (a
biome with real visual character, as opposed to flat GRASSLAND/BEACH)
adds a further bump."""

BEAUTY_VARIETY_BONUS_PER_BIOME = 0.04
BEAUTY_VARIETY_BONUS_MAX = 0.2
"""Each distinct biome in the 3x3 appraisal neighborhood beyond the
first nudges the score up — a varied vista (forest edge meeting river
meeting hills) reads as more picturesque than a flat monoculture of one
biome, capped so a wildly fragmented terrain-generation edge case can't
dominate the reading."""

BEAUTY_MINING_SCAR_PENALTY = 0.3
BEAUTY_DISASTER_SCAR_PENALTY = 0.25
"""Real environmental damage at the appraised tile drags the score
down proportional to the scar's own intensity (0..1) — the same
already-real `World.mining_scars`/`disaster_scars` state every other
scar-consuming mechanic in this codebase reads, scaled by how ugly each
kind of damage plausibly reads (a mine pit is a more visible eyesore
than a healing disaster mark, hence the slightly heavier weight)."""

_WATER_BIOMES = frozenset({Biome.DEEP_WATER, Biome.SHALLOW_WATER, Biome.RIVER})
"""Kept in lockstep with `world/hydrology_field.py`'s own `_WATER_
BIOMES` rather than imported — this module has no other reason to
depend on that one, same "duplicate the small constant, don't couple
modules unnecessarily" discipline `wildlife.py`'s `_field_region_value`
already established for `FieldGrid`'s bucketing math."""

_SCENIC_BIOMES = frozenset({Biome.FOREST, Biome.HILLS, Biome.MOUNTAIN, Biome.SNOWCAP, Biome.WETLAND})


def compute_aesthetic_appraisal(
    traits: dict, terrain: list[list[Tile]], x: int, y: int,
    mining_scars: dict[tuple[int, int], float], disaster_scars: dict[tuple[int, int], float],
) -> float:
    """One agent's 0..1 subjective appraisal of the tile at (x, y).
    `traits` is the voting agent's own `Agent.traits` dict — the
    subjective half of the reading. Pure function, no RNG: the same
    agent voting on the same tile under the same scar state always
    reaches the same appraisal (the RANDOMNESS here is entirely in
    *whether* a given agent votes this tick, handled by the caller)."""
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    if width <= 0 or height <= 0 or not (0 <= x < width and 0 <= y < height):
        return 0.5
    score = 0.5
    neighbor_biomes: set[Biome] = set()
    water_adjacent = False
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height:
                biome = terrain[ny][nx].biome
                neighbor_biomes.add(biome)
                if biome in _WATER_BIOMES:
                    water_adjacent = True
    if water_adjacent:
        score += BEAUTY_WATER_BONUS
    if terrain[y][x].biome in _SCENIC_BIOMES:
        score += BEAUTY_SCENIC_BIOME_BONUS
    score += min(BEAUTY_VARIETY_BONUS_MAX, max(0, len(neighbor_biomes) - 1) * BEAUTY_VARIETY_BONUS_PER_BIOME)
    score -= mining_scars.get((x, y), 0.0) * BEAUTY_MINING_SCAR_PENALTY
    score -= disaster_scars.get((x, y), 0.0) * BEAUTY_DISASTER_SCAR_PENALTY
    score += traits.get(TRAIT_OPENNESS, 0.0) * BEAUTY_OPENNESS_INFLUENCE
    return max(0.0, min(1.0, score))


def _region_of(x: int, y: int, width: int, height: int, size: int) -> tuple[int, int]:
    """Same bucketing math as `FieldGrid.region_of` — kept in lockstep
    rather than imported, matching `wildlife.py`'s own precedent for
    this exact formula."""
    if width <= 0 or height <= 0:
        return (0, 0)
    rx = min(size - 1, max(0, x * size // width))
    ry = min(size - 1, max(0, y * size // height))
    return (rx, ry)


def tick_aesthetic_votes(
    appraisal: list[list[float]], agents: list, terrain: list[list[Tile]],
    mining_scars: dict[tuple[int, int], float], disaster_scars: dict[tuple[int, int], float],
    width: int, height: int, rng: random.Random,
) -> None:
    """Mutates `appraisal` (`World.aesthetic_appraisal`) in place. Each
    living agent independently rolls `BEAUTY_APPRAISAL_CHANCE_PER_TICK`
    this tick; an agent who votes appraises their OWN current tile and
    the vote is folded into that tile's region via exponential
    smoothing. Deliberately every-agent, not core-cast-gated — this is
    zero-LLM-cost arithmetic, not a budget-constrained cognition call,
    so the standing "per-agent decision points must be core-cast-gated"
    rule (see CLAUDE.md's LLM call-volume section) doesn't apply; the
    thing being budget-guarded here is real per-tick CPU work, via the
    roll chance itself."""
    size = len(appraisal)
    for agent in agents:
        if rng.random() >= BEAUTY_APPRAISAL_CHANCE_PER_TICK:
            continue
        score = compute_aesthetic_appraisal(agent.traits, terrain, agent.x, agent.y, mining_scars, disaster_scars)
        rx, ry = _region_of(agent.x, agent.y, width, height, size)
        appraisal[ry][rx] += (score - appraisal[ry][rx]) * BEAUTY_VOTE_SMOOTHING
