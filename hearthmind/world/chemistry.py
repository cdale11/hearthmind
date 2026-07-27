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

First slice (query-only) resolved this at settlement-wide, per-KIND
granularity: `discover_reactions` reads `world.materials.BUILDING_
MATERIALS[kind]`, not any specific building's own material. The
second slice (explicit user instruction, "Start A13") ships the real
automatic reactor the doc's own spec literally asks for —
`ReactionRule` now carries a `rate` (consecutive ticks required), and
`tick_building_reactions` fires it: a standing building whose
EFFECTIVE material (`world.materials.effective_material_name`,
`Building.material` if ever converted, else the per-kind default)
matches a rule's reactant, held under that rule's condition for
`rate` consecutive ticks uninterrupted, genuinely converts —
`Building.material` is overwritten with the product, a real, lasting
change to that specific instance, not settlement-wide. Only clay
(SHRINE) and fiber (PASTURE/HATCHERY) can ever fire this way today —
no `BuildingKind` defaults to `ore`, so the ore->metal rule stays
reachable only through `discover_reactions`' query half (a settlement
would need to genuinely stockpile ore as a building's material, which
nothing in this codebase does yet — an honest, flagged gap, not
silently worked around). Real consequences, both zero native-parity
risk (this function runs OUTSIDE the native-ported building-decay
tick, never inside it): the building's `condition` gets a one-time
`REACTION_CONDITION_BOOST` ("freshly hardened"), and every future
affordance query for that instance (`world.materials.building_
instance_affordances`, threaded into Innovation's discovery prompt)
reflects the NEW material's real derived capabilities, not the old
one's."""
from __future__ import annotations

from dataclasses import dataclass

from hearthmind.settlement.buildings import BuildingStage
from hearthmind.world.materials import BUILDING_AFFORDANCES, MATERIALS, derive_affordances, effective_material_name

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
    rate: int = 500
    """Consecutive ticks a standing building's effective material must
    sit under `condition`, uninterrupted, before `tick_building_
    reactions` converts it — the spec's own literal `rate` field.
    Comparable order of magnitude to `terrain_evolution.MINING_SCAR_
    QUARRY_TICKS` (400): a real, sustained transformation, not a
    same-tick coin flip."""


REACTION_RULES: tuple[ReactionRule, ...] = (
    ReactionRule(reactant="clay", condition="heat", product="ceramic"),
    ReactionRule(reactant="ore", condition="heat", product="metal"),
    ReactionRule(reactant="fiber", condition="water_and_time", product="cured_fiber"),
)
"""Small and closed by design (same as `world.affordances.KNOWN_
COMBINATIONS`) — each entry only exists once its product material is
itself real, propertied, grounded state in `world.materials.MATERIALS`,
never a bare string with no backing data."""

REACTION_CONDITION_BOOST = 0.1
"""A converted building's one-time `condition` bump on firing — "the
kiln-fired shrine came out sturdier than before it was fired." Capped
at 1.0 like every other `condition` write; small and one-time (not a
new decay-rate mechanic), since this function runs entirely outside
the native-ported building-decay tick and must not entangle with it."""


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


def tick_building_reactions(settlement) -> list[tuple[str, str]]:
    """The real automatic reactor: called once per settlement per tick
    (`SimulationEngine._tick_chemistry_reactions`). Condition presence
    is settlement-wide (same affordance-union model `discover_
    reactions` already uses — a kiln/forge anywhere in the settlement
    provides heat for the whole community, not just its own tile), but
    the reactant match and the sustained-progress counter are per-
    BUILDING, since `Building.material` is now a genuine per-instance
    value. A building whose material/condition match breaks (kind
    changed underneath it — can't happen — or the settlement's
    standing buildings shift enough that the condition disappears)
    has its `reaction_progress` reset to 0, not paused, matching every
    other sustained-condition mechanism in this codebase (`terrain_
    evolution.maybe_form_quarries`, `hydrology.tick_wetlands`)."""
    standing = [b for b in settlement.buildings if b.stage is BuildingStage.STANDING]
    present_tags: set[str] = set()
    for b in standing:
        present_tags |= BUILDING_AFFORDANCES.get(b.kind, frozenset())
        name = effective_material_name(b)
        material = MATERIALS.get(name) if name else None
        if material is not None:
            present_tags |= derive_affordances(material)
    conditions = available_conditions(present_tags)

    events: list[tuple[str, str]] = []
    for building in standing:
        current = effective_material_name(building)
        rule = next(
            (r for r in REACTION_RULES if r.reactant == current and r.condition in conditions), None,
        )
        if rule is None:
            building.reaction_progress = 0
            continue
        building.reaction_progress += 1
        if building.reaction_progress < rule.rate:
            continue
        building.material = rule.product
        building.reaction_progress = 0
        building.condition = min(1.0, building.condition + REACTION_CONDITION_BOOST)
        events.append((
            "material_converted",
            f"The {building.kind.value} at ({building.x}, {building.y}) has genuinely become {rule.product} "
            f"under sustained {rule.condition.replace('_', ' ')}.",
        ))
    return events
