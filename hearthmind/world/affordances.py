"""A5/A6 "Capabilities/affordances over object classes" + "Exposed
affordances for discovery" (roadmap Stage IV step 18, docs/
MASTERCHECKLIST-2026-07-22.md): a thing is defined by *what it can do*,
not just its closed enum class — and a real deterministic query layer
over that so Innovation can discover unprogrammed combinations instead
of only ever naming within its existing closed hook vocabulary.

Deliberately the "wrap, don't replace" path the spec itself names:
`BuildingKind` stays exactly as it is (its own closed enum, mirrored
into the C++ native store's integer code tables — genuinely unsafe to
touch mid-run) — this module attaches an ADDITIONAL, purely-Python,
purely-additive affordance tag-set as data alongside it. Nothing here
changes what a building mechanically does; it only makes what it
*could plausibly do* queryable.

Scoped down from the full A5/A6 spec: `Entity.affordances`/`Entity.
properties` as genuine per-instance fields (A5's literal data model) and
A12's material-property registry are NOT built this pass — that's a
real generalization (any entity, not just buildings) that needs A12's
groundwork to be worth doing well, flagged as a follow-up. This slice
hand-tags `BuildingKind` (the one entity class with an existing
foundable/standing lifecycle Innovation can already ground a proposal
in) with a fixed affordance set, and ships the query/discovery layer
over that — real, working, just narrower in scope than "every entity."

`AFFORDANCE_TAGS` is the closed vocabulary named directly in det_sys.md's
own A5 worked example. `BUILDING_AFFORDANCES` is hand-tagged (not
LLM-authored, not derived from properties — that's A12's job) but
genuinely grounded: each tag reflects something that building kind's
existing mechanics or plain-language identity already implies (a
GRANARY already `can_store_food` per its own docstring; a FORGE's
description already invokes heat and tools).

`KNOWN_COMBINATIONS` is A6's "what combination of affordances would
achieve Y" — a small, closed, deterministic registry mapping a
required affordance PAIR to a named discoverable capability. This is
NOT itself a mechanical effect (no numeric hook fires here) — it's
grounding text handed to Innovation's generate-step (`llm/ontology.py`'s
`build_propose_prompt`, new optional `discoverable_combinations` param)
so a proposal can be "physically coherent" (respond to something
actually buildable from what's standing) rather than pure unconstrained
invention. A6's other named half — the validate-step re-checking a
proposal against this layer — shipped later (Tier 3 item 17, docs/
ROADMAP-2026-07-REMAINING.md): `llm/ontology.py`'s `validate_hook`
gained an optional `present_tags` param that rejects an `agricultural`/
`structural` `invention_specialization_category` claim with zero real
affordance overlap (see that module's `SPECIALIZATION_AFFORDANCE_
HINTS`) — `mercantile`/`general` have no meaningful affordance mapping
and stay unchecked, same reasoning as MARKET/BANK correctly carrying no
tag in `BUILDING_AFFORDANCES` above."""
from __future__ import annotations

from hearthmind.settlement.buildings import BuildingKind

AFFORDANCE_TAGS: tuple[str, ...] = (
    "can_burn", "can_shelter", "can_carry_water", "can_sharpen",
    "can_store_food", "can_redirect_water", "can_fertilize", "can_poison",
    "can_support_weight", "can_conduct_heat",
)
"""The closed affordance vocabulary named in det_sys.md's A5 example —
kept closed for the same reason `ONTOLOGY_CATEGORIES`/`MECHANICAL_
HOOK_TYPES` are: this feeds LLM-facing grounding text and a
deterministic combination registry, both of which need a fixed set to
stay reliably matchable."""

BUILDING_AFFORDANCES: dict[BuildingKind, frozenset[str]] = {
    BuildingKind.HUT: frozenset({"can_shelter", "can_support_weight"}),
    BuildingKind.GRANARY: frozenset({"can_store_food"}),
    BuildingKind.WORKSHOP: frozenset({"can_conduct_heat", "can_sharpen"}),
    BuildingKind.HOSPITAL: frozenset({"can_shelter"}),
    BuildingKind.FACTORY: frozenset({"can_conduct_heat", "can_sharpen"}),
    BuildingKind.SHRINE: frozenset({"can_support_weight"}),
    BuildingKind.POWER_PLANT: frozenset({"can_conduct_heat"}),
    BuildingKind.PASTURE: frozenset({"can_fertilize", "can_shelter"}),
    BuildingKind.HATCHERY: frozenset({"can_carry_water"}),
    BuildingKind.DOCK: frozenset({"can_carry_water", "can_redirect_water"}),
    BuildingKind.OIL_RIG: frozenset({"can_burn", "can_conduct_heat"}),
    BuildingKind.BRIDGE: frozenset({"can_support_weight"}),
    BuildingKind.FORGE: frozenset({"can_conduct_heat", "can_sharpen", "can_burn"}),
    BuildingKind.SMELTER: frozenset({"can_conduct_heat", "can_burn"}),
}
"""Kinds absent from this dict (SCHOOL/UNIVERSITY/MARKET/LIBRARY) carry
no physical affordance tag — their real identity is informational/
economic, not a physical capability this vocabulary describes; that's
a legitimate empty result, not a gap to fill."""

KNOWN_COMBINATIONS: dict[frozenset[str], str] = {
    frozenset({"can_carry_water", "can_store_food"}): "irrigation_store",
    frozenset({"can_conduct_heat", "can_sharpen"}): "tempered_tools",
    frozenset({"can_redirect_water", "can_fertilize"}): "irrigated_field",
    frozenset({"can_burn", "can_conduct_heat"}): "kiln_process",
    frozenset({"can_support_weight", "can_shelter"}): "reinforced_dwelling",
}
"""A6's "what combination of affordances would achieve Y" registry —
each entry names a plausible, physically coherent discovery a village
with BOTH tags present nearby could plausibly stumble onto. Closed and
small by design (same discipline as `MECHANICAL_HOOK_TYPES`): this is
grounding vocabulary for an LLM prompt, not a mechanism that fires
mechanical effects on its own."""


def affordances_present(standing_kinds) -> set[str]:
    """A6's "what here can_X?" query. `standing_kinds` is any iterable
    of `BuildingKind` (production call sites pass the STANDING
    buildings actually present in a settlement, e.g. `{b.kind for b in
    settlement.buildings if b.stage is BuildingStage.STANDING}` — this
    function itself stays building-state-agnostic so it's trivially
    testable against a bare list of kinds)."""
    present: set[str] = set()
    for kind in standing_kinds:
        present |= BUILDING_AFFORDANCES.get(kind, frozenset())
    return present


def discover_combinations(present_tags: set[str]) -> list[str]:
    """A6's "what combination of affordances would achieve Y" query —
    every `KNOWN_COMBINATIONS` entry whose full tag-pair is a subset of
    `present_tags`, i.e. genuinely achievable from what's actually
    standing right now. Sorted for deterministic prompt text (no RNG
    dependency on dict iteration order)."""
    return sorted(
        capability for tags, capability in KNOWN_COMBINATIONS.items()
        if tags.issubset(present_tags)
    )
