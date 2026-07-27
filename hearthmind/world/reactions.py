"""A18 (docs/MASTERCHECKLIST-2026-07-22.md, roadmap step 25): "Events
as composable reactions — an event is a *reaction* fired when a
COMBINATION of field/social/economic conditions crosses a threshold,
not a scripted incident... a drought-field + a feud-edge + a
food-shortage compose into [something] nobody hand-authored."

Deliberately distinct from `world/ontology.py`'s `TriggerRule` (a
SINGLE named trigger, LLM-authored per rule, village-originated) —
this module is the doc's own "small condition->consequence rule
engine," where the novel part is real deterministic conditions
crossing their OWN independent thresholds *simultaneously*, composing
into a consequence no single condition would have caused alone.

**First slice (v1.23.0)**: one hand-authored `CompositeReaction`
("Desperate Times") proved the AND-combination mechanism itself works
— `_maybe_tick_composite_reactions` in the engine is the general,
reusable combinator, same "the engine is fixed and general, the rules
are the open-ended part" shape `TriggerRule` already established.

**Second slice (v1.34.45, explicit user instruction: "Start A18")**:
the real authoring system this item's own doc entry flagged as
missing — a village can now propose ITS OWN `CompositeReaction`
combinations the same way `TriggerRule` is LLM-authored
(`SimulationEngine._maybe_schedule_composite_reaction_propose`),
sandbox-validated (`simulation/sandbox.py`) before going live, never
an LLM self-check. `CompositeReaction` now carries the same real-
consequence shape `TriggerRule` does (`hook_type`/`hook_target`/
`magnitude`, drawn from `world.ontology.MECHANICAL_HOOK_TYPES` — the
SAME closed vocabulary, applied through the SAME general consumer,
`SimulationEngine._apply_trigger_rule_hook`, rather than inventing a
second effect system). The original "Desperate Times" keeps its own
bespoke `hook_type="relationship_rupture"` consequence unchanged
(the doc's own "raid" example, scoped to a real relationship-rupture
effect) — new LLM-authored reactions get real mechanical hooks
instead; a general combat/raid mechanic remains out of scope."""

from __future__ import annotations

from dataclasses import dataclass

CONDITION_KEYS: tuple[str, ...] = ("drought", "feud", "food_shortage")
"""The closed set of boolean condition primitives a `CompositeReaction`
may combine — each backed by a real, already-tracked (or cheaply
computed) Body signal in `SimulationEngine`: `drought`/`food_shortage`
are edge-detected the same way `TriggerRule`'s `on_drought`/`on_
surplus` already are (heat_pressure / granary fill, just the LOW-fill
side for `food_shortage`), `feud` reads `Institution.feuds` directly.
Closed, same "closed vocabulary hosting open-ended combinations"
discipline as `ONTOLOGY_CATEGORIES`/`TRIGGER_TYPES`."""

MIN_REACTION_CONDITIONS = 2
"""A `CompositeReaction` must combine at least this many conditions —
one condition alone is just `TriggerRule`'s job (a single trigger),
not a genuine composite. With only 3 keys in `CONDITION_KEYS`, this
means every reaction combines 2 or all 3."""

FOOD_SHORTAGE_FILL_THRESHOLD = 0.15
"""A settlement's granary fill fraction below this reads as a real
shortage — deliberately far below `TRIGGER_SURPLUS_FILL_THRESHOLD`
(0.85), the opposite edge of the same granary-fill reading `world.
ontology`'s `on_surplus` trigger already uses."""

COMPOSITE_REACTION_RELATIONSHIP_PENALTY = 0.25
"""Bounded, immediate hit to relationships between the two feuding
families' living members when "Desperate Times" fires — smaller than
a single dispute's own worst-case swing (disputes are LLM-mediated and
can go further); this is a real but conservative escalation, not a
replacement for the dispute-resolution pipeline. The one reaction that
still uses this bespoke consequence (`hook_type="relationship_
rupture"`) rather than a `MECHANICAL_HOOK_TYPES` entry."""

COMPOSITE_REACTION_COOLDOWN_TICKS = 1500
"""A real AND of independently-rare conditions is already unlikely to
sit true for long, but the granary/drought edges can oscillate near
their thresholds — this cooldown (longer than `TRIGGER_RULE_COOLDOWN_
TICKS`'s 500, since a composite firing is a stronger event than a
single trigger) prevents a re-fire on every tick a still-true
combination happens to re-cross an edge."""

COMPOSITE_REACTION_STALE_TICKS = 40_000
"""C4 "The acceptance gate as law" (docs/ROADMAP-2026-07-REMAINING.md,
Part C, Tier 2 item 16): the runtime half of the acceptance gate —
"reject state no system observes" — only existed for `TriggerRule`
(`world.ontology.retire_stale_rules`); this is the same discipline
applied to `CompositeReaction`, its structural sibling (same `status`/
`fire_count`/`last_fired_tick` shape, authored the same LLM-plus-
sandbox way). Same value as `ontology.TRIGGER_RULE_STALE_TICKS` — no
live signal yet to justify tuning them independently, and a composite
reaction's own combinations are at least as rare as a single trigger's
(see `MAX_COMPOSITE_REACTIONS_STORED`'s docstring on how small the
whole condition-set space is)."""

MAX_COMPOSITE_REACTIONS_STORED = 30
"""Cap on `World.composite_reactions` — smaller than `MAX_TRIGGER_
RULES_STORED` (60): with only 3 condition keys and a `MIN_REACTION_
CONDITIONS` floor of 2, the entire combination space is 4 possible
condition-sets (`{drought,feud}`, `{drought,food_shortage}`,
`{feud,food_shortage}`, `{drought,feud,food_shortage}`) — a real
authoring system here can meaningfully vary NAME/description/hook,
not the condition-set itself, so there's no reason to store many more
than a small multiple of that combination count. A `retired` reaction
is pruned first (oldest first), matching `TriggerRule`'s own
discipline; "Desperate Times" (`origin_settlement_id=None`) is never
pruned."""


@dataclass
class CompositeReaction:
    """`conditions` must ALL be true simultaneously (a real AND, not
    an OR of independent triggers like `TriggerRule.secondary_
    trigger`) for this reaction to fire. `name` doubles as the
    per-settlement edge-tracking key.

    `hook_type`/`hook_target`/`magnitude` mirror `TriggerRule`'s own
    real-consequence shape — `"relationship_rupture"` is the one
    bespoke value (see `_apply_composite_reaction`'s docstring),
    everything else is a `world.ontology.MECHANICAL_HOOK_TYPES` entry
    applied through the same general consumer `TriggerRule` uses."""

    id: int
    name: str
    conditions: frozenset[str]
    description: str
    hook_type: str = "relationship_rupture"
    hook_target: str = ""
    magnitude: float = COMPOSITE_REACTION_RELATIONSHIP_PENALTY
    origin_settlement_id: "int | None" = None
    """`None` for the original hand-authored "Desperate Times" (a
    world-original, not village-proposed); a real settlement id for
    every LLM-authored reaction, same "who imagined this" provenance
    `TriggerRule.origin_settlement_id` already carries."""
    tick_created: int = 0
    status: str = "active"
    fire_count: int = 0
    last_fired_tick: int = -1

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "conditions": sorted(self.conditions),
            "description": self.description, "hook_type": self.hook_type,
            "hook_target": self.hook_target, "magnitude": self.magnitude,
            "origin_settlement_id": self.origin_settlement_id, "tick_created": self.tick_created,
            "status": self.status, "fire_count": self.fire_count, "last_fired_tick": self.last_fired_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompositeReaction":
        return cls(
            id=data["id"], name=data["name"], conditions=frozenset(data.get("conditions", ())),
            description=data.get("description", ""), hook_type=data.get("hook_type", "relationship_rupture"),
            hook_target=data.get("hook_target", ""), magnitude=data.get("magnitude", COMPOSITE_REACTION_RELATIONSHIP_PENALTY),
            origin_settlement_id=data.get("origin_settlement_id"), tick_created=data.get("tick_created", 0),
            status=data.get("status", "active"), fire_count=data.get("fire_count", 0),
            last_fired_tick=data.get("last_fired_tick", -1),
        )


def default_composite_reactions() -> dict[int, CompositeReaction]:
    """Seeds a brand-new world (and backfills a legacy snapshot missing
    this field entirely) with the one hand-authored "Desperate Times"
    reaction — never absent, never re-imagined, `origin_settlement_id
    =None` marks it as world-original rather than village-proposed."""
    return {
        0: CompositeReaction(
            id=0, name="Desperate Times",
            conditions=frozenset({"drought", "feud", "food_shortage"}),
            description=(
                "the dry heat and empty granary have driven an old feud past its "
                "breaking point"
            ),
            hook_type="relationship_rupture", magnitude=COMPOSITE_REACTION_RELATIONSHIP_PENALTY,
        ),
    }


def validate_conditions(conditions: "frozenset[str] | set[str]") -> bool:
    """Deterministic re-verification, never an LLM self-check — same
    discipline as `ontology.validate_hook`. A proposed condition-set
    must be a non-empty subset of `CONDITION_KEYS` with at least
    `MIN_REACTION_CONDITIONS` members."""
    if len(conditions) < MIN_REACTION_CONDITIONS:
        return False
    return all(c in CONDITION_KEYS for c in conditions)


def register_composite_reaction(
    world, name: str, conditions: "frozenset[str] | set[str]", description: str,
    hook_type: str, hook_target: str, magnitude: float, origin_settlement_id: int, tick: int,
) -> CompositeReaction:
    """Registers a real village-proposed `CompositeReaction` — the
    authoring half of A18's second slice, mirroring `ontology.
    register_trigger_rule`'s own shape closely (id counter, cap-and-
    prune oldest-retired-first, never mutates an existing entry)."""
    reaction = CompositeReaction(
        id=world.next_composite_reaction_id, name=name, conditions=frozenset(conditions),
        description=description, hook_type=hook_type, hook_target=hook_target, magnitude=magnitude,
        origin_settlement_id=origin_settlement_id, tick_created=tick,
    )
    world.composite_reactions[reaction.id] = reaction
    world.next_composite_reaction_id += 1
    if len(world.composite_reactions) > MAX_COMPOSITE_REACTIONS_STORED:
        prunable = [r for r in world.composite_reactions.values() if r.origin_settlement_id is not None]
        if prunable:
            retired_first = sorted(prunable, key=lambda r: (r.status != "retired", r.tick_created))
            del world.composite_reactions[retired_first[0].id]
    return reaction


def retire_stale_composite_reactions(world, tick: int) -> None:
    """C4's runtime auditor, applied to `CompositeReaction` — see
    `COMPOSITE_REACTION_STALE_TICKS`'s docstring. An `active` reaction
    whose condition-set has never once matched (`fire_count == 0`) for
    longer than the stale window is genuine isolated state: proposed,
    sandbox-validated, stored, but never once consumed by `_maybe_tick_
    composite_reactions`. Retired, never deleted — same "preserve as
    historical record" discipline as `ontology.retire_stale_rules`;
    `register_composite_reaction`'s own prune step is the only thing
    that ever actually removes a retired reaction, and only once the
    registry is over its storage cap. "Desperate Times" (`origin_
    settlement_id=None`, the one hand-authored reaction) is exempt —
    it's a deliberate always-available mechanism proof, not a village
    proposal that failed to catch on."""
    for reaction in world.composite_reactions.values():
        if reaction.origin_settlement_id is None:
            continue
        if (
            reaction.status == "active" and reaction.fire_count == 0
            and tick - reaction.tick_created > COMPOSITE_REACTION_STALE_TICKS
        ):
            reaction.status = "retired"


def matching_reactions(active_conditions: set[str], reactions) -> list[CompositeReaction]:
    """Every ACTIVE `CompositeReaction` whose full condition set is a
    subset of what's currently true — deterministic, no randomness,
    the combinator itself is exhaustive over the (small) registry.
    `reactions` is any iterable of `CompositeReaction` (`World.
    composite_reactions.values()` in production, a plain list in
    tests)."""
    return [
        reaction for reaction in reactions
        if reaction.status == "active" and reaction.conditions <= active_conditions
    ]
