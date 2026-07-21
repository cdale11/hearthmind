"""Phase 1 of the "self-evolving world" architecture
(docs/VISION-2026-07-21-SELFEVOLVING.md): the Innovation Layer's
persistent registry. Explicit user follow-up (2026-07-21): invented
concepts must not just exist — they are first-class simulation
objects any system can discover, reference, reinterpret, combine,
mutate, and build upon indefinitely, not inert flavor text.

`InventedConcept` is the object; `World.invented_concepts` (keyed by a
stable integer id, never reused) is the shared registry every system
reads/writes through — genuinely shared across settlements (an idea
can spread or be referenced beyond where it was born, same "ideas
aren't settlement-private" reasoning `roads`' paving tier already
established). Lineage (`evolved_from`/`merged_from`) makes this a real
DAG: a concept's parents are never destroyed when a child is created
("build upon indefinitely" means the history stays walkable, not that
old concepts get replaced), so a chain of reinterpretation/combination
is itself part of the world's history.

Deliberately bounded, not a fully open schema — see `llm/ontology.py`'s
module docstring for why (closed category/hook-type vocabulary hosting
open-ended name/description/lineage)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

ONTOLOGY_CATEGORIES: tuple[str, ...] = (
    "technology", "custom", "law", "ritual", "saying", "profession",
    "institution_flavor", "ecological",
)
"""The closed set of "what kind of thing is this" categories — see
`llm/ontology.py`'s SYSTEM_PROMPT_PROPOSE. `technology` is the one
category the pre-existing `llm/invention.py` job already produces
(bridged into this registry by `SimulationEngine._maybe_schedule_
invention`, not duplicated — see its docstring); the other seven are
new, produced by `SimulationEngine._maybe_schedule_ontology_proposal`."""

MECHANICAL_HOOK_TYPES: tuple[str, ...] = (
    "invention_specialization_category", "skill_yield_bonus", "goal_flavor_bias",
    "belief_confidence_bonus", "custom_text_only",
)
"""The closed set of mechanical effects a proposed concept may attach
to — see `llm/ontology.py`'s `validate_hook`. `custom_text_only` (no
numeric effect) is a legitimate, common choice: most sayings/customs/
rituals are real (persistent, spreadable, referenceable) without
needing a fabricated numeric effect — same tier as folklore/omens."""

MAX_HOOK_MAGNITUDE = 0.12
"""Shared cap on any non-`invention_specialization_category` hook's
`magnitude` — deliberately smaller than `INVENTION_SPECIALIZATION_CAP`
(a mature, single-purpose mechanism); a same-tier-but-newer mechanism
gets a same-tier-but-slightly-more-conservative ceiling until it has a
comparable amount of live tuning behind it."""

MAX_CONCEPTS_STORED = 400
"""Cap on `World.invented_concepts` — same "prune the least-load-
bearing entries first" discipline as `INSTITUTION_LIST_MAX_STORED`/
`CULTURE_LIST_MAX_STORED`: `abandoned` concepts are dropped first
(oldest first), then (only if still over cap) the oldest `proposed`
ones — `spreading`/`established` concepts and anything with a lineage
child pointing at it are never pruned, since deleting a referenced
parent would corrupt the DAG other concepts' `lineage` fields point
into."""

MAX_ADOPTERS_STORED = 40
"""Cap on `InventedConcept.adopter_ids` — enough to comfortably clear
the `established` threshold below with headroom, not a full population
census."""

CONCEPT_SPREADING_ADOPTERS = 2
CONCEPT_ESTABLISHED_ADOPTERS = 5
"""Floors for `maybe_promote_status`'s thresholds — the Phase 1.A
minimum, still in force for a small/new core cast so an early-game
settlement doesn't get an impossibly slow first promotion."""

CONCEPT_SPREADING_FRACTION = 0.2
CONCEPT_ESTABLISHED_FRACTION = 0.5
"""Phase 3.A "population-scaled (not flat) adoption thresholds"
(docs/VISION-2026-07-21-SELFEVOLVING.md): only core-cast members of the
concept's origin settlement can ever become tracked adopters (see
`_maybe_spread_concepts`'s candidate filter in engine.py) — the
relevant "population" to scale against is that settlement's actual
core-cast headcount, not the settlement's total population, which the
adoption mechanism structurally can't reach. `maybe_promote_status`
takes the max of these fractions and the flat floors above, so a large
core cast needs proportionally more real adopters to promote a concept
(not just 5 out of an 80-strong cast) while a small/new cast still
promotes at the original flat pace."""

CONCEPT_STALE_TICKS = 20_000
"""A `proposed` concept that never gains a second adopter within this
many ticks (~a season and a half at default pacing) ages to
`abandoned` — a real "this idea didn't catch on" outcome, not a
permanent zombie entry competing for the `MAX_CONCEPTS_STORED` cap
forever. `spreading`/`established` concepts never go stale this way —
adoption momentum, once real, isn't punished for slowing down."""

DUPLICATE_NAME_OVERLAP = 0.6
"""Jaccard word-overlap threshold for `is_near_duplicate` — same value
and reasoning as `folklore.FOLKLORE_DUPLICATE_OVERLAP`: a near-
restatement of an existing concept's name+description is "nothing
new," not a fresh entry."""


def _overlap_tokens(text: str) -> set[str]:
    return {w for w in text.lower().split() if len(w) > 3}


@dataclass
class InventedConcept:
    """One first-class, persistent invented concept — see this
    module's docstring. `status` is the adoption lifecycle
    (`proposed -> spreading -> established`, or `-> abandoned` if it
    never catches on); a concept is never deleted for having been
    superseded — `lineage` lets later concepts point back at it
    instead, so old ideas stay part of the walkable history even once
    a village has moved past them."""

    id: int
    name: str
    description: str
    category: str
    origin_settlement_id: int
    tick_invented: int
    inventor_agent_id: int | None
    status: str = "proposed"
    mechanical_hook: dict | None = None
    adopter_ids: set[int] = field(default_factory=set)
    lineage: dict = field(default_factory=dict)
    """`{"evolved_from": id|None, "merged_from": [id, id]|None}` — at
    most one of the two keys is ever populated (a concept is either a
    mutation of one parent or a combination of two, never both)."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "origin_settlement_id": self.origin_settlement_id,
            "tick_invented": self.tick_invented,
            "inventor_agent_id": self.inventor_agent_id,
            "status": self.status,
            "mechanical_hook": dict(self.mechanical_hook) if self.mechanical_hook else None,
            "adopter_ids": sorted(self.adopter_ids),
            "lineage": dict(self.lineage),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InventedConcept":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            category=data["category"],
            origin_settlement_id=data.get("origin_settlement_id", 0),
            tick_invented=data.get("tick_invented", 0),
            inventor_agent_id=data.get("inventor_agent_id"),
            status=data.get("status", "proposed"),
            mechanical_hook=dict(data["mechanical_hook"]) if data.get("mechanical_hook") else None,
            adopter_ids=set(data.get("adopter_ids", [])),
            lineage=dict(data.get("lineage", {})),
        )


TRIGGER_TYPES: tuple[str, ...] = ("on_death", "on_birth", "on_feud", "on_invention", "on_drought", "on_surplus")
"""Vision doc item 1.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md ("A
conditional/trigger vocabulary as data"): the closed set of conditions
a `TriggerRule` may bind to. Each name corresponds to a real, already-
existing detection point `SimulationEngine._apply_trigger_rules_for`
is called from — `on_death`/`on_birth` off `World.last_life_events`,
`on_feud` off `llm.dispute`'s feud outcome, `on_invention` off a
genuine (non-fallback) invention, `on_drought`/`on_surplus` off a
low->high edge in `World.disasters.heat_pressure`/a settlement's
granary food fraction. Not every trigger a real village might imagine
is here — this is deliberately the small set with a real, already-
built detection point, same "closed vocabulary hosting open-ended
content" discipline as `ONTOLOGY_CATEGORIES`/`MECHANICAL_HOOK_TYPES`."""

MAX_TRIGGER_RULES_STORED = 60
"""Cap on `World.trigger_rules` — smaller than `MAX_CONCEPTS_STORED`
since rules are rarer (one proposal per season at most, see
`SimulationEngine._maybe_schedule_rule_proposal`) and a `retired` rule
is pruned first (oldest first), same discipline as concepts."""

TRIGGER_RULE_COOLDOWN_TICKS = 500
"""A rule that already fired within this many ticks is skipped on a
fresh trigger — without this, a burst of same-tick deaths (a disaster)
or a state that stays past its `on_drought`/`on_surplus` threshold for
many ticks would fire the same rule over and over, turning one
"village custom" into runaway repeated narration/effect. ~1-2 weeks at
default pacing — long enough that a rule reads as "this happens when X
happens," not "this happens constantly.\""""

TRIGGER_RULE_STALE_TICKS = 40_000
"""Vision doc item 5.1, docs/VISION-2026-07-22-LIVINGTERRARIUM.md ("the
acceptance gate as a runtime invariant... anything the Innovation Layer
creates that no system reads within N days is auto-flagged and
retired"). A `TriggerRule` is "read" by the rule engine every time its
trigger condition actually matches (`fire_count` increments) — a rule
whose trigger genuinely never occurs is exactly the "isolated mechanic"
the acceptance gate exists to catch. Twice `CONCEPT_STALE_TICKS`
(rarer conditions — on_feud/on_invention/on_drought/on_surplus don't
recur as often as a concept simply gaining a second adopter) — see
`retire_stale_rules`."""


@dataclass
class TriggerRule:
    """Vision doc item 1.2: a village-originated rule binding a real
    `trigger` (from `TRIGGER_TYPES`) to a real mechanical `hook_type`
    (from `MECHANICAL_HOOK_TYPES`, same closed vocabulary/validation as
    `InventedConcept`) — "when the granary overflows, hold a feast that
    raises everyone's fondness" is `trigger="on_surplus"`,
    `hook_type="belief_confidence_bonus"` (or `custom_text_only` for a
    purely narrative rule). The rule engine (`_apply_trigger_rules_for`)
    is fixed and general; the rules themselves are LLM-authored and
    open-ended within that closed shape. Never deleted on retirement —
    `status="retired"` (Reflection's counterfactual sandbox judged it
    unsafe, or a human/future mechanism retires it) keeps it as
    historical record, same as a rejected Reflection hypothesis."""

    id: int
    name: str
    description: str
    trigger: str
    hook_type: str
    hook_target: str
    magnitude: float
    origin_settlement_id: int
    tick_created: int
    status: str = "active"
    fire_count: int = 0
    last_fired_tick: int = -1

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "trigger": self.trigger, "hook_type": self.hook_type, "hook_target": self.hook_target,
            "magnitude": self.magnitude, "origin_settlement_id": self.origin_settlement_id,
            "tick_created": self.tick_created, "status": self.status,
            "fire_count": self.fire_count, "last_fired_tick": self.last_fired_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TriggerRule":
        return cls(
            id=data["id"], name=data["name"], description=data["description"],
            trigger=data["trigger"], hook_type=data["hook_type"], hook_target=data.get("hook_target", ""),
            magnitude=data.get("magnitude", 0.0), origin_settlement_id=data.get("origin_settlement_id", 0),
            tick_created=data.get("tick_created", 0), status=data.get("status", "active"),
            fire_count=data.get("fire_count", 0), last_fired_tick=data.get("last_fired_tick", -1),
        )


def register_concept(
    world, name: str, description: str, category: str, origin_settlement_id: int,
    tick: int, inventor_agent_id: int | None = None, mechanical_hook: dict | None = None,
    lineage: dict | None = None,
) -> InventedConcept:
    """Mints a new `InventedConcept` with the next id, seeds the
    inventor as its first adopter (if any), and prunes the registry if
    it's now over cap. The one mutator that creates new concepts —
    every other write goes through `add_adopter`/`maybe_promote_
    status`/`abandon_stale` below."""
    concept_id = world.next_concept_id
    world.next_concept_id += 1
    concept = InventedConcept(
        id=concept_id, name=name, description=description, category=category,
        origin_settlement_id=origin_settlement_id, tick_invented=tick,
        inventor_agent_id=inventor_agent_id, mechanical_hook=mechanical_hook,
        lineage=lineage or {},
    )
    if inventor_agent_id is not None:
        concept.adopter_ids.add(inventor_agent_id)
    world.invented_concepts[concept_id] = concept
    prune_concepts(world)
    return concept


def is_near_duplicate(world, name: str, description: str) -> bool:
    tokens = _overlap_tokens(f"{name} {description}")
    if not tokens:
        return False
    for concept in world.invented_concepts.values():
        existing_tokens = _overlap_tokens(f"{concept.name} {concept.description}")
        if not existing_tokens:
            continue
        overlap = len(tokens & existing_tokens) / max(1, len(tokens | existing_tokens))
        if overlap >= DUPLICATE_NAME_OVERLAP:
            return True
    return False


def add_adopter(world, concept_id: int, agent_id: int, tick: int) -> None:
    concept = world.invented_concepts.get(concept_id)
    if concept is None or concept.status == "abandoned":
        return
    if len(concept.adopter_ids) >= MAX_ADOPTERS_STORED:
        return
    concept.adopter_ids.add(agent_id)
    core_cast_size = sum(
        1 for a in world.population.agents
        if a.settlement_id == concept.origin_settlement_id and a.id in world.population.core_agent_ids
    )
    maybe_promote_status(concept, core_cast_size)


def maybe_promote_status(concept: InventedConcept, core_cast_size: int = 0) -> None:
    """`core_cast_size` (Phase 3.A): the origin settlement's current
    core-cast headcount — see CONCEPT_SPREADING_FRACTION's docstring
    for why that, not total population, is the right scale. Defaults to
    0 (falls back to the flat floors unchanged) for any caller that
    doesn't have a settlement context to compute it from."""
    count = len(concept.adopter_ids)
    spreading_threshold = max(CONCEPT_SPREADING_ADOPTERS, math.ceil(core_cast_size * CONCEPT_SPREADING_FRACTION))
    established_threshold = max(
        CONCEPT_ESTABLISHED_ADOPTERS, math.ceil(core_cast_size * CONCEPT_ESTABLISHED_FRACTION)
    )
    if concept.status == "proposed" and count >= spreading_threshold:
        concept.status = "spreading"
    if concept.status in ("proposed", "spreading") and count >= established_threshold:
        concept.status = "established"


def abandon_stale(world, tick: int) -> None:
    """Monthly-cadence sweep (see `SimulationEngine._maybe_schedule_
    ontology_proposal`'s call site): a `proposed` concept that's been
    sitting with fewer than `CONCEPT_SPREADING_ADOPTERS` adopters for
    longer than `CONCEPT_STALE_TICKS` genuinely didn't catch on."""
    for concept in world.invented_concepts.values():
        if concept.status == "proposed" and tick - concept.tick_invented > CONCEPT_STALE_TICKS:
            concept.status = "abandoned"


def _referenced_ids(world) -> set[int]:
    referenced: set[int] = set()
    for concept in world.invented_concepts.values():
        evolved_from = concept.lineage.get("evolved_from")
        if evolved_from is not None:
            referenced.add(evolved_from)
        for parent_id in concept.lineage.get("merged_from") or ():
            referenced.add(parent_id)
    return referenced


def prune_concepts(world) -> None:
    if len(world.invented_concepts) <= MAX_CONCEPTS_STORED:
        return
    referenced = _referenced_ids(world)

    def prunable(concept: InventedConcept) -> bool:
        return concept.id not in referenced

    abandoned = sorted(
        (c for c in world.invented_concepts.values() if c.status == "abandoned" and prunable(c)),
        key=lambda c: c.tick_invented,
    )
    for concept in abandoned:
        if len(world.invented_concepts) <= MAX_CONCEPTS_STORED:
            return
        del world.invented_concepts[concept.id]
    proposed = sorted(
        (c for c in world.invented_concepts.values() if c.status == "proposed" and prunable(c)),
        key=lambda c: c.tick_invented,
    )
    for concept in proposed:
        if len(world.invented_concepts) <= MAX_CONCEPTS_STORED:
            return
        del world.invented_concepts[concept.id]


def established_concepts(world, settlement_id: int | None = None) -> list[InventedConcept]:
    """Reference material for prompt-grounding call sites — see
    `SimulationEngine._maybe_schedule_town_brain`'s new grounding line.
    `settlement_id=None` returns every established concept world-wide
    (an idea already established elsewhere is real, referenceable
    history even for a settlement that never adopted it itself)."""
    return [
        c for c in world.invented_concepts.values()
        if c.status == "established"
        and (settlement_id is None or c.origin_settlement_id == settlement_id)
    ]


ARCHITECTURE_RELEVANT_CATEGORIES = ("technology", "institution_flavor")
"""Phase 3.C "architecture visibly changing on the map per established
Innovation concept" (docs/VISION-2026-07-21-SELFEVOLVING.md): of the
eight categories, only these two plausibly reshape what a settlement
BUILDS, not just what it believes/says/does — a `custom`, `law`,
`ritual`, `saying`, or `profession` doesn't have an obvious physical
form. Deliberately narrow rather than letting every established
concept compete for the one visual slot below."""


def dominant_architecture_concept(world, settlement_id: int) -> InventedConcept | None:
    """The settlement's own most-recently-established concept in an
    architecture-relevant category, or `None` if it has none yet — the
    real, contained hook `SimulationEngine._maybe_broadcast` reads to
    tint that settlement's buildings on the map (see app.js
    `paintArchitectureStyle`). "Most recent" (by `tick_invented`, the
    only ordering field a concept carries) means a settlement's visible
    style can genuinely shift again later if a newer concept overtakes
    an older one — not a one-time permanent lock-in."""
    candidates = [
        c for c in world.invented_concepts.values()
        if c.origin_settlement_id == settlement_id
        and c.status == "established"
        and c.category in ARCHITECTURE_RELEVANT_CATEGORIES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.tick_invented)


def register_trigger_rule(
    world, name: str, description: str, trigger: str, hook_type: str, hook_target: str,
    magnitude: float, origin_settlement_id: int, tick: int,
) -> "TriggerRule":
    """Mints a new `TriggerRule` with the next id — the trigger-rule
    counterpart to `register_concept`. Never validates `trigger`/
    `hook_type` itself (that's `llm/rule_propose.py`'s job, same
    deterministic-re-verification discipline as `validate_hook`) —
    this is the pure mutator."""
    rule_id = world.next_trigger_rule_id
    world.next_trigger_rule_id += 1
    rule = TriggerRule(
        id=rule_id, name=name, description=description, trigger=trigger,
        hook_type=hook_type, hook_target=hook_target, magnitude=magnitude,
        origin_settlement_id=origin_settlement_id, tick_created=tick,
    )
    world.trigger_rules[rule_id] = rule
    prune_trigger_rules(world)
    return rule


def prune_trigger_rules(world) -> None:
    """Same over-cap discipline as `prune_concepts`: `retired` rules
    are dropped first (oldest first), never `active` ones."""
    if len(world.trigger_rules) <= MAX_TRIGGER_RULES_STORED:
        return
    retired = sorted(
        (r for r in world.trigger_rules.values() if r.status == "retired"),
        key=lambda r: r.tick_created,
    )
    for rule in retired:
        if len(world.trigger_rules) <= MAX_TRIGGER_RULES_STORED:
            return
        del world.trigger_rules[rule.id]


def retire_stale_rules(world, tick: int) -> None:
    """Vision doc item 5.1's runtime acceptance auditor, applied to
    `TriggerRule` — see `TRIGGER_RULE_STALE_TICKS`'s docstring. An
    `active` rule whose trigger condition has never once matched
    (`fire_count == 0`) for longer than the stale window is genuinely
    an isolated mechanic: proposed, validated, stored, but never once
    consumed by the rule engine. Retired, never deleted — same
    "preserve as historical record" discipline as `abandon_stale`'s
    concepts and Reflection's rejected hypotheses; `prune_trigger_
    rules` is the only thing that ever actually removes a retired
    rule, and only once the registry is over its storage cap."""
    for rule in world.trigger_rules.values():
        if rule.status == "active" and rule.fire_count == 0 and tick - rule.tick_created > TRIGGER_RULE_STALE_TICKS:
            rule.status = "retired"
