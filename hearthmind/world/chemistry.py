"""A13 "Chemistry / reaction system" (roadmap Stage IV step 20, docs/
MASTERCHECKLIST-2026-07-22.md): general reaction rules over A12's
material registry — `A + condition -> C` as a small closed rule table,
not per-recipe code. Together with A12, this is the doc's own "invent
metallurgy without hardcoding metallurgy" engine: Innovation queries
"what does X produce under condition Y?" instead of a fixed recipe list
ever being consulted directly.

Scoped to the doc's own three worked examples (clay + fire -> ceramic;
ore + heat -> metal; plant + water + time -> fermentation), reinterpreted
against `world.materials.MATERIALS`' actual registry: `clay` + `heat` ->
`ceramic`, `ore` + `heat` -> `metal`, `fiber` + `water_and_time` ->
`cured_fiber` (fiber tanning/curing — the real-world "plant + water +
time" process). All three products are themselves real, fully-propertied
`Material` entries in `world.materials.MATERIALS` (not a special
second-class output type), so a discovered reaction product is
immediately `derive_affordances`-capable like any hand-tagged material.

Deliberately NOT a general `ReactionRule(reactants, conditions,
products, rate)` engine that fires automatically on the tick loop and
mutates world state (the spec's literal "a deterministic reactor that
fires rules when conditions meet") — that's real, larger follow-up
work needing its own design pass (what would a "condition being met"
even change about a standing building's material after the fact?).
This slice ships the QUERY half only: given what's genuinely available
in a settlement (materials from `world.materials.BUILDING_MATERIALS`
on its standing buildings, conditions derived from A5/A6's affordance
layer), `discover_reactions` returns which reaction products are
genuinely reachable right now — real, deterministic, and (like A5/A6's
`discover_combinations`) wired as grounding text into Innovation's
ontology-proposal generate-step, not merely inert data."""
from __future__ import annotations

from dataclasses import dataclass

CONDITIONS: tuple[str, ...] = ("heat", "water_and_time")
"""Closed vocabulary of reaction conditions — same discipline as
`world.affordances.AFFORDANCE_TAGS`. `heat` is available wherever
`can_conduct_heat` or `can_burn` is present (A5/A6's affordance
layer); `water_and_time` wherever `can_carry_water` is present (a
settlement with sustained water access implicitly has "time" — this
system doesn't model a separate elapsed-time axis)."""

_HEAT_AFFORDANCES = frozenset({"can_conduct_heat", "can_burn"})
_WATER_AND_TIME_AFFORDANCES = frozenset({"can_carry_water"})


@dataclass(frozen=True)
class ReactionRule:
    reactant: str
    condition: str
    product: str


REACTION_RULES: tuple[ReactionRule, ...] = (
    ReactionRule(reactant="clay", condition="heat", product="ceramic"),
    ReactionRule(reactant="ore", condition="heat", product="metal"),
    ReactionRule(reactant="fiber", condition="water_and_time", product="cured_fiber"),
)
"""Small and closed by design (same as `world.affordances.KNOWN_
COMBINATIONS`) — each entry only exists once its product material is
itself real, propertied, grounded state in `world.materials.MATERIALS`,
never a bare string with no backing data."""


def available_conditions(present_affordances: set[str]) -> set[str]:
    """A6-style query, generalized to conditions: which of the closed
    `CONDITIONS` are implied by a settlement's currently-present
    affordance tags (see `world.materials.building_affordances`)."""
    conditions: set[str] = set()
    if present_affordances & _HEAT_AFFORDANCES:
        conditions.add("heat")
    if present_affordances & _WATER_AND_TIME_AFFORDANCES:
        conditions.add("water_and_time")
    return conditions


def discover_reactions(available_materials: set[str], present_affordances: set[str]) -> list[str]:
    """Every `REACTION_RULES` product genuinely reachable right now:
    its reactant material is actually present (see `world.materials.
    BUILDING_MATERIALS` over a settlement's standing buildings) AND its
    condition is implied by what's actually standing. Sorted for
    deterministic prompt text, same as `world.affordances.discover_
    combinations`."""
    conditions = available_conditions(present_affordances)
    return sorted(
        rule.product for rule in REACTION_RULES
        if rule.reactant in available_materials and rule.condition in conditions
    )
