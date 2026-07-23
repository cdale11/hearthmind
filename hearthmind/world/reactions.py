"""A18 (docs/MASTERCHECKLIST-2026-07-22.md, roadmap step 25), first
slice: "Events as composable reactions — an event is a *reaction*
fired when a COMBINATION of field/social/economic conditions crosses a
threshold, not a scripted incident... a drought-field + a feud-edge +
a food-shortage compose into [something] nobody hand-authored."

Deliberately distinct from `world/ontology.py`'s `TriggerRule` (a
SINGLE named trigger, LLM-authored per rule, village-originated) —
this module is the doc's own "small condition->consequence rule
engine," where the novel part is real deterministic conditions
crossing their OWN independent thresholds *simultaneously*, composing
into a consequence no single condition would have caused alone.

Scoped down hard, per this project's standing "first slice, not the
full spec" discipline: one hand-authored `CompositeReaction` ships
this pass (`_maybe_tick_composite_reactions` in the engine is the
general, reusable combinator — same "the engine is fixed and general,
the rules are the open-ended part" shape `TriggerRule` already
established), proving the AND-combination mechanism itself works. A
real registry of many composable reactions, and folding this onto the
Innovation Layer so villages can propose their OWN combinations (the
way `TriggerRule` is LLM-authored), remain open, flagged — see
docs/MASTERCHECKLIST-2026-07-22.md's A18 section.

The doc's own worked example ("a raid nobody hand-authored") is scoped
down to a buildable, already-real consequence: three independently
tracked Body signals (drought, an active family feud, a food shortage)
crossing their thresholds together escalate that feud into open
conflict — a real, bounded, immediate cooldown on relationships between
the two families' members — rather than a new combat/raid mechanic,
which is out of scope for this slice."""

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
replacement for the dispute-resolution pipeline."""


@dataclass(frozen=True)
class CompositeReaction:
    """`conditions` must ALL be true simultaneously (a real AND, not
    an OR of independent triggers like `TriggerRule.secondary_
    trigger`) for this reaction to fire. `name` doubles as the
    per-settlement edge-tracking key."""

    name: str
    conditions: frozenset[str]
    description: str


COMPOSITE_REACTIONS: tuple[CompositeReaction, ...] = (
    CompositeReaction(
        name="Desperate Times",
        conditions=frozenset({"drought", "feud", "food_shortage"}),
        description=(
            "the dry heat and empty granary have driven an old feud past its "
            "breaking point"
        ),
    ),
)
"""The one worked composite this pass ships — see this module's own
docstring for why the count stays at one rather than a general
authoring system."""

COMPOSITE_REACTION_COOLDOWN_TICKS = 1500
"""A real AND of three independently-rare conditions is already
unlikely to sit true for long, but the granary/drought edges can
oscillate near their thresholds — this cooldown (longer than
`TRIGGER_RULE_COOLDOWN_TICKS`'s 500, since a composite firing is a
stronger event than a single trigger) prevents a re-fire on every
tick a still-true combination happens to re-cross an edge."""


def matching_reactions(active_conditions: set[str]) -> list[CompositeReaction]:
    """Every `CompositeReaction` whose full condition set is a subset
    of what's currently true — deterministic, no randomness, the
    combinator itself is exhaustive over the (small, closed)
    registry."""
    return [reaction for reaction in COMPOSITE_REACTIONS if reaction.conditions <= active_conditions]
