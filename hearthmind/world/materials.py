"""A12 "Material science / physical properties" (roadmap Stage IV step
19, docs/MASTERCHECKLIST-2026-07-22.md): a real material-property
registry, and the first real bridge from A5/A6's hand-tagged affordances
toward properties-DERIVED ones — "new tools emerge from combining
properties," not just from a programmer hand-tagging what a building
kind can do.

Scoped down from the full spec: this pass covers the registry itself
(`Material`, `MATERIALS`) and one real consumer — deriving affordance
tags from a material's properties (`derive_affordances`) and unioning
that into what `world/affordances.py` already reports for a
`BuildingKind` (`BUILDING_MATERIALS` assigns each tagged kind its
primary material). Full per-instance material assignment (`Entity.
material: Material`, every tool/vehicle/agent-crafted good carrying its
own material rather than one closed per-kind lookup), and A13's
chemistry/reaction rules consuming these properties, remain open —
real, larger follow-ups, flagged rather than attempted here.

`MATERIALS` is a small closed registry (same discipline as `world.
affordances.AFFORDANCE_TAGS`/`world.ontology.MECHANICAL_HOOK_TYPES`):
five materials genuinely grounded in what a `BuildingKind` is already
described as being built from in its own docstrings (wood huts/docks,
stone forges/bridges, clay-adjacent shrines, worked metal at a forge/
factory, woven fiber at a pasture/hatchery fence). Every property is
0..1; thresholds in `derive_affordances` are deliberately conservative
(a material must clear a threshold, not just be nonzero) so derivation
stays a genuine signal, not "everything can do everything a little.\""""
from __future__ import annotations

from dataclasses import dataclass

from hearthmind.settlement.buildings import BuildingKind
from hearthmind.world.affordances import AFFORDANCE_TAGS, BUILDING_AFFORDANCES


@dataclass(frozen=True)
class Material:
    hardness: float
    density: float
    conductivity: float
    elasticity: float
    durability: float
    decay_rate: float
    flammability: float
    toxicity: float
    thermal_capacity: float
    workability: float


MATERIALS: dict[str, Material] = {
    "wood": Material(
        hardness=0.35, density=0.3, conductivity=0.15, elasticity=0.4,
        durability=0.4, decay_rate=0.5, flammability=0.85, toxicity=0.05,
        thermal_capacity=0.2, workability=0.8,
    ),
    "stone": Material(
        hardness=0.85, density=0.9, conductivity=0.2, elasticity=0.05,
        durability=0.9, decay_rate=0.05, flammability=0.0, toxicity=0.0,
        thermal_capacity=0.5, workability=0.25,
    ),
    "clay": Material(
        hardness=0.3, density=0.55, conductivity=0.1, elasticity=0.15,
        durability=0.45, decay_rate=0.3, flammability=0.0, toxicity=0.05,
        thermal_capacity=0.55, workability=0.75,
    ),
    "metal": Material(
        hardness=0.95, density=0.85, conductivity=0.9, elasticity=0.3,
        durability=0.85, decay_rate=0.1, flammability=0.05, toxicity=0.15,
        thermal_capacity=0.75, workability=0.5,
    ),
    "fiber": Material(
        hardness=0.1, density=0.15, conductivity=0.05, elasticity=0.6,
        durability=0.25, decay_rate=0.7, flammability=0.6, toxicity=0.0,
        thermal_capacity=0.1, workability=0.9,
    ),
}
"""Property values are hand-authored, not measured — same "grounded
estimate, not simulated physics" discipline as `world.affordances.
BUILDING_AFFORDANCES`'s hand-tagging. Real-world-plausible relative
ordering (stone harder/denser/less flammable than wood, metal most
conductive, fiber most flammable-and-workable-but-least-durable) is
what makes `derive_affordances` produce sensible output, not literal
material-science accuracy."""

BUILDING_MATERIALS: dict[BuildingKind, str] = {
    BuildingKind.HUT: "wood",
    BuildingKind.GRANARY: "wood",
    BuildingKind.WORKSHOP: "wood",
    BuildingKind.HOSPITAL: "stone",
    BuildingKind.FACTORY: "metal",
    BuildingKind.SHRINE: "clay",
    BuildingKind.POWER_PLANT: "metal",
    BuildingKind.PASTURE: "fiber",
    BuildingKind.HATCHERY: "fiber",
    BuildingKind.DOCK: "wood",
    BuildingKind.OIL_RIG: "metal",
    BuildingKind.BRIDGE: "stone",
    BuildingKind.FORGE: "stone",
}
"""Deliberately the same tagged-kind set `world.affordances.BUILDING_
AFFORDANCES` covers — SCHOOL/UNIVERSITY/MARKET/LIBRARY carry no
physical affordance tag there either, for the same "informational/
economic identity, not a physical capability" reasoning; extending
one without the other would be a real inconsistency, not a smaller
scope."""

HARDNESS_SHARPEN_THRESHOLD = 0.6
WORKABILITY_SHARPEN_THRESHOLD = 0.4
FLAMMABILITY_BURN_THRESHOLD = 0.4
CONDUCT_HEAT_THRESHOLD = 0.45
"""A material conducts heat well if EITHER its conductivity or its
thermal capacity clears this — two distinct real routes to the same
affordance (a metal conducts; a dense stone retains and radiates)."""
SUPPORT_WEIGHT_HARDNESS_THRESHOLD = 0.6
SUPPORT_WEIGHT_DENSITY_THRESHOLD = 0.5


def derive_affordances(material: Material) -> set[str]:
    """The A12 "properties → affordances" bridge: a real, deterministic
    function of the four material-science axes that plausibly imply a
    physical capability among `AFFORDANCE_TAGS`. Deliberately partial —
    `can_store_food`/`can_carry_water`/`can_redirect_water`/
    `can_fertilize`/`can_poison` are function-of-shape, not function-
    of-raw-material, properties (a wooden granary stores food because
    of its FORM, not because wood is inherently food-storing) — this
    function only ever derives the subset that genuinely follows from
    material properties alone, unioned (never replacing) with `world.
    affordances.BUILDING_AFFORDANCES`'s existing hand-tagged set."""
    tags: set[str] = set()
    if material.hardness >= HARDNESS_SHARPEN_THRESHOLD and material.workability >= WORKABILITY_SHARPEN_THRESHOLD:
        tags.add("can_sharpen")
    if material.flammability >= FLAMMABILITY_BURN_THRESHOLD:
        tags.add("can_burn")
    if material.conductivity >= CONDUCT_HEAT_THRESHOLD or material.thermal_capacity >= CONDUCT_HEAT_THRESHOLD:
        tags.add("can_conduct_heat")
    if material.hardness >= SUPPORT_WEIGHT_HARDNESS_THRESHOLD and material.density >= SUPPORT_WEIGHT_DENSITY_THRESHOLD:
        tags.add("can_support_weight")
    if material.toxicity >= 0.5:
        tags.add("can_poison")
    assert tags.issubset(AFFORDANCE_TAGS)
    return tags


def material_for_building(kind: BuildingKind) -> Material | None:
    name = BUILDING_MATERIALS.get(kind)
    return MATERIALS.get(name) if name else None


def building_affordances(kind: BuildingKind) -> frozenset[str]:
    """The real union point: `world.affordances.BUILDING_AFFORDANCES`'s
    existing hand-tagged set for this kind, PLUS whatever `derive_
    affordances` adds from its assigned material's properties. A hand-
    tagged affordance never disappears (union, not replacement) — this
    is "affordances start ALSO deriving from properties," not "stop
    being hand-tagged." A kind with no assigned material (SCHOOL/
    UNIVERSITY/MARKET/LIBRARY) reads exactly as `BUILDING_AFFORDANCES`
    alone did before this module existed."""
    tags = set(BUILDING_AFFORDANCES.get(kind, frozenset()))
    material = material_for_building(kind)
    if material is not None:
        tags |= derive_affordances(material)
    return frozenset(tags)
