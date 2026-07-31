"""A19's "battles" axis (docs/ROADMAP-2026-07-REMAINING.md, "Known
scope trims") had no data source because no combat mechanic existed
anywhere in this codebase. This is that mechanic: explicit user
decision ("full combat subsystem") over the smaller relationship-
rupture-only shape A18's "raid" example already covers.

Scoped to CROSS-settlement war, not intra-settlement FACTION civil
war — plunder (materials/currency changing hands) only makes sense
between two real, separately-resourced communities, and A19's own
worked example ("battles") reads as settlement-vs-settlement conflict.
Genuinely deterministic (Body layer, per CLAUDE.md's priority order —
objective physical outcomes are never LLM-authored): two real war
parties (a fraction of each settlement's own living, mature, healthy
population) are drawn, a real numeric strength reading decides the
winner probabilistically, both sides take real bounded casualties
(never a wipeout), the winner plunders a real fraction of the loser's
stockpile, and the fight leaves a real, decaying `battle_scars` mark
at the defending settlement's own site — the first real feed for
A19's previously-permanently-empty axis.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

BATTLE_TRIGGER_THRESHOLD = -0.75
"""A cross-settlement relation this deep past `buildings.
DIPLOMATIC_HOSTILITY_THRESHOLD` (-0.5) before real war becomes
possible — sustained, severe hostility, not merely "cold." A real
diplomatic crisis can exist for a long time before it turns into an
actual battle; this is the second, stricter gate on top of the
already-real diplomatic_hostility signal."""

BATTLE_CHANCE_PER_TICK = 0.0015
"""Checked only once a pair already clears `BATTLE_TRIGGER_THRESHOLD`
(rare on its own) — small so a real war stays a genuine, infrequent
event even for two settlements locked in bitter hostility for a long
stretch, not a near-certainty the moment the threshold is crossed."""

BATTLE_ROSTER_FRACTION = 0.3
"""Fraction of a settlement's own living, mature, healthy population
drawn into its war party — a real settlement never sends everyone; the
rest keep the town running. Deliberately smaller than the founding-
construction eligibility bar's own typical yield, since going to war is
a much larger commitment than laying one building's foundation."""

BATTLE_MIN_ROSTER_SIZE = 2
"""Below this many eligible people, a settlement can't field a real war
party at all — the battle is skipped this tick (checked again on a
future roll), never fabricated from nothing."""

BATTLE_CASUALTY_BASE_FRACTION = 0.08
BATTLE_CASUALTY_STRENGTH_DIFF_WEIGHT = 0.35
BATTLE_CASUALTY_MAX_FRACTION = 0.4
"""A real battle always costs the loser real casualties (base fraction,
never zero) that scale up the more lopsided the fight was — but never
past this ceiling. A battle is a genuine, remembered tragedy, never an
extinction event for either side's roster."""

BATTLE_WINNER_CASUALTY_MULTIPLIER = 0.35
"""The winning side also takes real losses, just proportionally fewer
than the loser's own casualty fraction — a battle is never bloodless
for the victor either."""

BATTLE_PLUNDER_FRACTION = 0.2
"""Fraction of the LOSING settlement's materials and currency the
winner carries home — real economic consequence, not just casualties."""

BATTLE_RELATION_PENALTY = 0.3
"""How much a real battle further worsens both settlements' mutual
relation reading afterward — war deepens hostility, it doesn't resolve
it. Bounded by `Settlement.relations`' own [-1, 1] clamp."""


def roster_strength(agents: list, trait_ambition: str, trait_resilience: str) -> float:
    """A war party's real fighting strength — its size, scaled by its
    own average of two already-real psychology traits (H6): ambition
    (willingness to press an advantage) and resilience (holding under
    pressure). Deliberately reuses existing traits rather than inventing
    a sixth "combat skill" axis with no other consumer."""
    if not agents:
        return 0.0
    avg = sum(
        (a.traits.get(trait_ambition, 0.0) + a.traits.get(trait_resilience, 0.0)) / 2.0 for a in agents
    ) / len(agents)
    return len(agents) * (1.0 + max(0.0, avg))


@dataclass
class BattleResult:
    winner: str
    """"attacker" or "defender" — never a tie; `resolve_battle`'s own
    probabilistic roll always picks one side, matching how a real
    engagement always has some outcome even when forces are close."""
    attacker_casualty_ids: set = field(default_factory=set)
    defender_casualty_ids: set = field(default_factory=set)
    attacker_strength: float = 0.0
    defender_strength: float = 0.0


def resolve_battle(
    attacker_roster: list, defender_roster: list, rng: random.Random,
    trait_ambition: str, trait_resilience: str,
) -> BattleResult:
    """The real, deterministic (given `rng`) resolution of one battle.
    Both rosters must be non-empty (callers gate on `BATTLE_MIN_
    ROSTER_SIZE`); winner is chosen probabilistically, weighted by
    each side's real `roster_strength`, then casualties are drawn —
    losing side scaled by how lopsided the fight was (capped), winning
    side at a smaller fixed fraction of that same rate."""
    a_strength = roster_strength(attacker_roster, trait_ambition, trait_resilience)
    d_strength = roster_strength(defender_roster, trait_ambition, trait_resilience)
    total = a_strength + d_strength
    a_win_prob = (a_strength / total) if total > 0 else 0.5
    winner = "attacker" if rng.random() < a_win_prob else "defender"
    winner_roster = attacker_roster if winner == "attacker" else defender_roster
    loser_roster = defender_roster if winner == "attacker" else attacker_roster
    strength_diff_ratio = (abs(a_strength - d_strength) / total) if total > 0 else 0.0
    loser_fraction = min(
        BATTLE_CASUALTY_MAX_FRACTION,
        BATTLE_CASUALTY_BASE_FRACTION + strength_diff_ratio * BATTLE_CASUALTY_STRENGTH_DIFF_WEIGHT,
    )
    winner_fraction = loser_fraction * BATTLE_WINNER_CASUALTY_MULTIPLIER
    loser_casualties = set(
        a.id for a in rng.sample(loser_roster, k=min(len(loser_roster), max(1, round(len(loser_roster) * loser_fraction))))
    )
    winner_casualty_count = round(len(winner_roster) * winner_fraction)
    winner_casualties = set(
        a.id for a in rng.sample(winner_roster, k=min(len(winner_roster), winner_casualty_count))
    ) if winner_casualty_count > 0 else set()
    attacker_casualties = winner_casualties if winner == "attacker" else loser_casualties
    defender_casualties = loser_casualties if winner == "attacker" else winner_casualties
    return BattleResult(
        winner=winner, attacker_casualty_ids=attacker_casualties, defender_casualty_ids=defender_casualties,
        attacker_strength=a_strength, defender_strength=d_strength,
    )
