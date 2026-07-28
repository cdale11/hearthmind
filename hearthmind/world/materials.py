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
    "ore": Material(
        hardness=0.6, density=0.75, conductivity=0.2, elasticity=0.1,
        durability=0.5, decay_rate=0.2, flammability=0.0, toxicity=0.2,
        thermal_capacity=0.35, workability=0.15,
    ),
    "ceramic": Material(
        hardness=0.7, density=0.5, conductivity=0.05, elasticity=0.02,
        durability=0.75, decay_rate=0.08, flammability=0.0, toxicity=0.0,
        thermal_capacity=0.6, workability=0.1,
    ),
    "cured_fiber": Material(
        hardness=0.15, density=0.2, conductivity=0.05, elasticity=0.45,
        durability=0.55, decay_rate=0.25, flammability=0.5, toxicity=0.0,
        thermal_capacity=0.12, workability=0.6,
    ),
}
"""`ore`/`ceramic`/`cured_fiber` are A13's reaction PRODUCTS (`world.
chemistry.REACTION_RULES`) rather than anything `BUILDING_MATERIALS`
assigns directly — kept in this same registry (not a separate one) so
a discovered product is a real, fully-propertied, `derive_affordances`-
capable material like any other, not a special second-class kind of
value. `ore` is metal's raw, harder-to-work, less-conductive precursor;
`ceramic` is fired clay (harder, far more durable, zero flammability,
but far less workable — you shape clay, not ceramic); `cured_fiber` is
fiber tanned/cured (real "plant + water + time" processing: notably
more durable and decay-resistant than raw fiber, somewhat less
flammable, at some cost to workability). Property values are hand-
authored, not measured — same "grounded estimate, not simulated
physics" discipline as `world.affordances.BUILDING_AFFORDANCES`'s
hand-tagging. Real-world-plausible relative
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


def effective_material_name(building) -> str | None:
    """A13's per-instance resolution point: `Building.material` if the
    reactor (`world.chemistry.tick_building_reactions`) has ever
    converted this specific building, else the per-kind default from
    `BUILDING_MATERIALS`. Every other reader of "what is this building
    made of" (queries, prompts, affordance derivation) should go
    through this, not `BUILDING_MATERIALS[kind]` directly, once an
    individual instance can genuinely differ from its kind's default."""
    return building.material if building.material is not None else BUILDING_MATERIALS.get(building.kind)


MATERIAL_REPAIR_FACTOR_BASE = 0.5
MATERIAL_REPAIR_FACTOR_WORKABILITY_WEIGHT = 1.0
"""A5/A6's other named gap, closed here: `Entity.properties` as a
genuine per-instance driver of a real mechanic, distinct from
`building_instance_affordances`' boolean capability tags above. A
material's numeric `workability` (already tracked, never consumed by
anything until now) directly scales how fast `Population._maybe_
repair` restores a damaged building's `condition` — wood/fiber
(workability 0.8/0.9) repair meaningfully faster than stone/ore/
ceramic (0.25/0.15/0.1), the same real-world intuition "you can patch
a wooden hut faster than you can re-lay stonework" made mechanical.
Range with these constants: ~0.6 (ceramic) to ~1.4 (fiber), centered
near 1.0 for wood/metal so the previously-flat repair rate stays close
to its old tuned value for the two most common kinds."""


def material_repair_factor(name: str | None) -> float:
    """A kind with no assigned material (SCHOOL/UNIVERSITY/MARKET/
    LIBRARY) or an unrecognized name returns exactly 1.0 — the old
    flat-rate behavior, unchanged. `effective_material_name(building)`
    is the intended caller for a real per-instance value."""
    material = MATERIALS.get(name) if name else None
    if material is None:
        return 1.0
    return MATERIAL_REPAIR_FACTOR_BASE + material.workability * MATERIAL_REPAIR_FACTOR_WORKABILITY_WEIGHT


def building_instance_affordances(building) -> frozenset[str]:
    """`building_affordances(kind)`'s per-INSTANCE counterpart — reads
    `effective_material_name` instead of always the per-kind default,
    so a converted building (ceramic instead of clay, cured_fiber
    instead of fiber) genuinely presents different derived affordances
    to Innovation's discovery queries, not just a silent internal
    label change. Hand-tagged affordances (`BUILDING_AFFORDANCES`)
    never depend on material, so those are identical either way."""
    tags = set(BUILDING_AFFORDANCES.get(building.kind, frozenset()))
    name = effective_material_name(building)
    material = MATERIALS.get(name) if name else None
    if material is not None:
        tags |= derive_affordances(material)
    return frozenset(tags)
