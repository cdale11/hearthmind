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
`CULTURE_LIST_MAX_STORED`: `abandoned`/`retired` concepts are dropped
first (oldest first), then (only if still over cap) the oldest
`proposed` ones — `spreading`/`established` concepts and anything with
a lineage child pointing at it are never pruned, since deleting a
referenced parent would corrupt the DAG other concepts' `lineage`
fields point into."""

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

FITNESS_HISTORY_MAX = 8
"""Cap on `InventedConcept.fitness_history` — a rolling window, not a
full lifetime ledger (same bounded-list discipline as every other
per-entity history in this codebase); recent evaluations matter more
than a concept's fitness from months ago."""

FITNESS_EVALUATION_MIN_READINGS = 3
"""A8 "Evolutionary Innovation" (roadmap Stage IV step 21): `run_
selection` won't retire a concept off a single bad reading — noise in
any one monthly reputation snapshot shouldn't end a concept's run.
Only once at least this many real readings have accumulated does the
selection pass judge sustained unfitness."""

FITNESS_UNFIT_THRESHOLD = -0.05
"""A concept whose adopters' mean recent reputation trails the origin
settlement's own living-population mean reputation by at least this
much, sustained across `FITNESS_EVALUATION_MIN_READINGS` readings, is
judged genuinely unfit ("did adopters prosper?" — no) and retired.
Deliberately a small negative margin, not zero — reputation is a noisy
signal even averaged, and a concept merely tracking the settlement
average shouldn't be punished."""


def _overlap_tokens(text: str) -> set[str]:
    return {w for w in text.lower().split() if len(w) > 3}


@dataclass
class InventedConcept:
    """One first-class, persistent invented concept — see this
    module's docstring. `status` is the adoption lifecycle
    (`proposed -> spreading -> established`, or `-> abandoned` if it
    never catches on, or `-> retired` if A8's selection pass judges it
    genuinely unfit after real adoption — see `run_selection`); a
    concept is never deleted for having been superseded — `lineage`
    lets later concepts point back at it instead, so old ideas stay
    part of the walkable history even once a village has moved past
    them."""

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
    hypothesis: str = ""
    """B5 "Innovation as conscious scientist" (roadmap Stage III step
    12): the real problem/need this concept was proposed to address —
    empty string means "no specific problem, just culture for its own
    sake," a legitimate answer, not a missing one. Set once at
    proposal time (`llm/ontology.py`'s new `hypothesis` JSON field),
    never revised afterward — the concept's `status` lifecycle is
    itself the record of whether the hypothesis held up."""
    world_model_entry_id: int | None = None
    """The id of this concept's mirrored entry in `World.innovation_
    pillar.world_model` (set by `SimulationEngine._maybe_schedule_
    ontology_proposal`'s apply()) — lets `add_adopter`/`abandon_stale`
    below revise that SAME entry in place when the concept's real-world
    fate (established vs. abandoned) confirms or refutes the original
    hypothesis, instead of leaving Innovation's own belief frozen at
    its initial 0.4 "just proposed" confidence forever."""
    fitness_history: list[float] = field(default_factory=list)
    """A8 "Evolutionary Innovation" (roadmap Stage IV step 21): recent
    `evaluate_fitness` readings, oldest first, capped at `FITNESS_
    HISTORY_MAX` — the real "did adopters prosper?" evaluate step,
    distinct from `status`'s adoption-COUNT-only promotion logic above.
    Empty for a concept never yet evaluated (no living adopters at any
    monthly sweep so far)."""
    generation: int = 0
    """0 for an originally-proposed concept; `max(parent.generation) +
    1` for one created via `evolve`/`merge` (`register_concept`'s new
    `generation` param) — a real, walkable "how many rounds of
    selection produced this idea" counter alongside the existing
    `lineage` DAG."""

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
            "hypothesis": self.hypothesis,
            "world_model_entry_id": self.world_model_entry_id,
            "fitness_history": list(self.fitness_history),
            "generation": self.generation,
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
            hypothesis=data.get("hypothesis", ""),
            world_model_entry_id=data.get("world_model_entry_id"),
            fitness_history=list(data.get("fitness_history", [])),
            generation=data.get("generation", 0),
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
    secondary_trigger: str = ""
    """Vision doc item 1.1 ("composable hooks, not just parameterized
    ones"): a rule may bind a SECOND, different trigger to its own
    independent effect — "a ritual that raises farming yield after a
    death, AND lowers it during a feud" is one `TriggerRule` with
    `trigger="on_death"`/`hook_type="skill_yield_bonus"` and
    `secondary_trigger="on_feud"`/`secondary_hook_type=...`. The two
    closed primitives (`TRIGGER_TYPES`/`MECHANICAL_HOOK_TYPES`) stay
    fixed; letting one rule chain two of them is the combination that's
    genuinely open-ended. Empty string means single-effect (the
    original v1.3.31 shape) — every existing rule round-trips
    unchanged. `_apply_trigger_rules_for` fires whichever trigger
    (primary or secondary) matches, cooldown-gated independently per
    side so a rule with two frequently-matching triggers can't runaway
    either half."""
    secondary_hook_type: str = ""
    secondary_hook_target: str = ""
    secondary_magnitude: float = 0.0
    secondary_last_fired_tick: int = -1

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "trigger": self.trigger, "hook_type": self.hook_type, "hook_target": self.hook_target,
            "magnitude": self.magnitude, "origin_settlement_id": self.origin_settlement_id,
            "tick_created": self.tick_created, "status": self.status,
            "fire_count": self.fire_count, "last_fired_tick": self.last_fired_tick,
            "secondary_trigger": self.secondary_trigger, "secondary_hook_type": self.secondary_hook_type,
            "secondary_hook_target": self.secondary_hook_target, "secondary_magnitude": self.secondary_magnitude,
            "secondary_last_fired_tick": self.secondary_last_fired_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TriggerRule":
        return cls(
            id=data["id"], name=data["name"], description=data["description"],
            trigger=data["trigger"], hook_type=data["hook_type"], hook_target=data.get("hook_target", ""),
            magnitude=data.get("magnitude", 0.0), origin_settlement_id=data.get("origin_settlement_id", 0),
            tick_created=data.get("tick_created", 0), status=data.get("status", "active"),
            fire_count=data.get("fire_count", 0), last_fired_tick=data.get("last_fired_tick", -1),
            secondary_trigger=data.get("secondary_trigger", ""),
            secondary_hook_type=data.get("secondary_hook_type", ""),
            secondary_hook_target=data.get("secondary_hook_target", ""),
            secondary_magnitude=data.get("secondary_magnitude", 0.0),
            secondary_last_fired_tick=data.get("secondary_last_fired_tick", -1),
        )


MAX_COMPOSITE_ENTITIES_STORED = 100
"""Cap on `World.composite_entities` — rarer than concepts/rules (one
proposal per season at most per settlement, same cadence as `_maybe_
schedule_institution_culture`), so a smaller ceiling than `MAX_
CONCEPTS_STORED` suffices. Never pruned by eviction in practice at
that volume; kept as a genuine ceiling, oldest dropped first, matching
every other capped registry here."""


@dataclass
class CompositeEntity:
    """Vision doc item 4.1, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
    ("Composite entities from existing primitives"): a new "entity"
    that isn't new code — a named, persistent COMPOSITE of things that
    already exist. Mechanically this is nothing more than: one real
    standing `Building` (`building_id`, unchanged kind/stats — a
    composite entity never adds a new `BuildingKind`), bound to one
    real `InventedConcept` (`concept_id`, carrying whatever mechanical
    hook that concept already has, if any) via a name and an origin
    story grounded in something that actually happened. "The
    Sorrow-Hall" is mechanically still just a MEMORIAL-shaped building
    and an `institution_flavor` concept — the entity is the SUM,
    structurally just composition, never a new mechanism. `sigil_svg`
    (item 4.3) is a small deterministic parameterized SVG icon
    generated at creation time — see `world/sigils.py` — never an LLM
    call of its own."""

    id: int
    name: str
    base_kind: str
    building_id: int
    concept_id: int
    origin_settlement_id: int
    origin_story: str
    tick_created: int
    sigil_svg: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "base_kind": self.base_kind,
            "building_id": self.building_id, "concept_id": self.concept_id,
            "origin_settlement_id": self.origin_settlement_id,
            "origin_story": self.origin_story, "tick_created": self.tick_created,
            "sigil_svg": self.sigil_svg,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CompositeEntity":
        return cls(
            id=data["id"], name=data["name"], base_kind=data.get("base_kind", ""),
            building_id=data["building_id"], concept_id=data["concept_id"],
            origin_settlement_id=data.get("origin_settlement_id", 0),
            origin_story=data.get("origin_story", ""), tick_created=data.get("tick_created", 0),
            sigil_svg=data.get("sigil_svg", ""),
        )


MAX_CAUSAL_THREADS_STORED = 60
"""Cap on `World.causal_threads` — one entry per dispute-family-feud-
style outcome, roughly the same rarity class as composite entities."""


@dataclass
class CausalThread:
    """Vision doc item 3.3, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
    ("Legible causal threads"): "click a feud, see the chain that made
    it." A full generic event-graph (every event linked to its cause)
    would need every event-emission site in the codebase threaded with
    stable ids — out of scope for one batch. Scoped instead to the
    concrete grounding facts ALREADY computed at the one call site that
    decides a dispute/feud outcome (`SimulationEngine._maybe_schedule_
    dispute`) — the debt/rival-faction/rival-family/reputation-gap/law
    lines that already go into the LLM prompt are exactly the causal
    chain a human would point to, just captured as a structured record
    instead of being spent once on a single prompt and discarded."""

    id: int
    subject: str
    chain: list[str]
    tick: int
    settlement_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "subject": self.subject, "chain": list(self.chain),
            "tick": self.tick, "settlement_id": self.settlement_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CausalThread":
        return cls(
            id=data["id"], subject=data.get("subject", ""), chain=list(data.get("chain", [])),
            tick=data.get("tick", 0), settlement_id=data.get("settlement_id"),
        )


def register_causal_thread(world, subject: str, chain: list[str], tick: int, settlement_id: int | None = None) -> CausalThread:
    """Mints a new `CausalThread`, prunes the registry past MAX_CAUSAL_
    THREADS_STORED (oldest dropped first, same discipline as every
    other capped registry here)."""
    thread_id = world.next_causal_thread_id
    world.next_causal_thread_id += 1
    thread = CausalThread(id=thread_id, subject=subject, chain=list(chain), tick=tick, settlement_id=settlement_id)
    world.causal_threads[thread_id] = thread
    if len(world.causal_threads) > MAX_CAUSAL_THREADS_STORED:
        oldest_id = min(world.causal_threads, key=lambda i: world.causal_threads[i].tick)
        del world.causal_threads[oldest_id]
    return thread


def register_concept(
    world, name: str, description: str, category: str, origin_settlement_id: int,
    tick: int, inventor_agent_id: int | None = None, mechanical_hook: dict | None = None,
    lineage: dict | None = None, hypothesis: str = "", world_model_entry_id: int | None = None,
    generation: int = 0,
) -> InventedConcept:
    """Mints a new `InventedConcept` with the next id, seeds the
    inventor as its first adopter (if any), and prunes the registry if
    it's now over cap. The one mutator that creates new concepts —
    every other write goes through `add_adopter`/`maybe_promote_
    status`/`abandon_stale` below.

    `generation` (A8, roadmap Stage IV step 21): 0 for an original
    proposal (the default — every existing call site keeps reading as
    before); `_maybe_schedule_ontology_evolution` passes `parent.
    generation + 1` (evolve) or `max(a.generation, b.generation) + 1`
    (merge)."""
    concept_id = world.next_concept_id
    world.next_concept_id += 1
    concept = InventedConcept(
        id=concept_id, name=name, description=description, category=category,
        origin_settlement_id=origin_settlement_id, tick_invented=tick,
        inventor_agent_id=inventor_agent_id, mechanical_hook=mechanical_hook,
        lineage=lineage or {}, hypothesis=hypothesis, world_model_entry_id=world_model_entry_id,
        generation=generation,
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


def _record_hypothesis_outcome(world, concept: InventedConcept, tick: int, confirmed: bool) -> None:
    """B5 "Innovation as conscious scientist" (roadmap Stage III step
    12): closes the hypothesize -> observe -> revise loop. A concept
    proposed as an answer to a real, named problem (`hypothesis`, set
    once at proposal time) eventually either catches on
    (`established`, `confirmed=True`) or doesn't (`abandoned`,
    `confirmed=False`) — that real-world outcome is fed straight back
    into Innovation's own `world_model` belief about it, in place
    (`revises_id`), rather than leaving the belief frozen at its
    initial 0.4 "just proposed" confidence forever. Zero LLM cost —
    the outcome is read off state that already exists (`status`,
    `adopter_ids`), not asked of the model a second time. A concept
    with no `hypothesis` (pure culture, not a claimed fix for
    anything) and/or no mirrored `world_model_entry_id` is a no-op —
    nothing to confirm or refute."""
    if not concept.hypothesis or concept.world_model_entry_id is None:
        return
    pillar = getattr(world, "innovation_pillar", None)
    if pillar is None:
        return
    if confirmed:
        belief = f"{concept.hypothesis} — {concept.name} caught on and confirmed it."
        confidence = 0.85
        status = "observation"
    else:
        belief = f"{concept.hypothesis} — {concept.name} never caught on; this idea did not hold up."
        confidence = 0.1
        status = "hypothesis"
    pillar.upsert_world_model(
        tick, concept.name, belief, confidence, status=status,
        source="ontology_outcome", revises_id=concept.world_model_entry_id,
    )


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
    was_established = concept.status == "established"
    maybe_promote_status(concept, core_cast_size)
    if concept.status == "established" and not was_established:
        _record_hypothesis_outcome(world, concept, tick, confirmed=True)


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
            _record_hypothesis_outcome(world, concept, tick, confirmed=False)


def evaluate_fitness(world, concept: InventedConcept) -> float | None:
    """A8 "Evolutionary Innovation" (roadmap Stage IV step 21)'s real
    *evaluate* step: "did adopters prosper?" — the mean `Population.
    reputation` of a concept's still-LIVING adopters, relative to the
    mean reputation of its origin settlement's current living
    population. Positive means adopters are doing measurably better
    than their neighbors on average; negative means worse. `None` (not
    evaluable this cycle, not "neutral 0.0") when the concept has no
    living adopters or its origin settlement currently has nobody
    living in it — a real "nothing to measure," never faked as a
    reading."""
    living_adopters = [a for a in world.population.agents if a.id in concept.adopter_ids]
    if not living_adopters:
        return None
    settlement_members = [
        a for a in world.population.agents if a.settlement_id == concept.origin_settlement_id
    ]
    if not settlement_members:
        return None
    adopter_avg = sum(world.population.reputation(a.id) for a in living_adopters) / len(living_adopters)
    settlement_avg = sum(world.population.reputation(a.id) for a in settlement_members) / len(settlement_members)
    return adopter_avg - settlement_avg


def run_selection(world, tick: int) -> None:
    """A8's *select* step, paired at the same monthly cadence as
    `abandon_stale` (see `SimulationEngine._maybe_schedule_ontology_
    proposal`'s call site): every `spreading`/`established` concept
    gets one fresh `evaluate_fitness` reading appended to its bounded
    `fitness_history` (skipped, not zero-padded, when unevaluable this
    cycle — see that function's docstring). Only once at least `FITNESS_
    EVALUATION_MIN_READINGS` real readings have accumulated does
    sustained mean unfitness below `FITNESS_UNFIT_THRESHOLD` retire the
    concept (`status = "retired"`, distinct from `abandoned` — this
    concept DID catch on for a while, unlike a stale `proposed` one)
    and revise Innovation's own mirrored belief about its hypothesis.
    `proposed`/`abandoned`/`retired` concepts are never evaluated —
    there is nothing meaningful to select among until real adoption has
    actually happened."""
    for concept in world.invented_concepts.values():
        if concept.status not in ("spreading", "established"):
            continue
        fitness = evaluate_fitness(world, concept)
        if fitness is None:
            continue
        concept.fitness_history.append(fitness)
        if len(concept.fitness_history) > FITNESS_HISTORY_MAX:
            concept.fitness_history.pop(0)
        if len(concept.fitness_history) < FITNESS_EVALUATION_MIN_READINGS:
            continue
        recent = concept.fitness_history[-FITNESS_EVALUATION_MIN_READINGS:]
        if sum(recent) / len(recent) < FITNESS_UNFIT_THRESHOLD:
            concept.status = "retired"
            _record_hypothesis_outcome(world, concept, tick, confirmed=False)


def reinstate_concept(world, concept_id: int, tick: int) -> InventedConcept | None:
    """A8's dual-fork confirmation step (`SimulationEngine._confirm_
    concept_retirement`, `simulation.sandbox.evaluate_concept_dual_
    fork`): `run_selection`'s correlational retirement (adopter
    reputation vs. settlement average, immediate/synchronous) stays
    exactly as it was — this is a SECOND, slower, causal opinion that
    can reverse it after the fact, not a replacement. Reinstating only
    makes sense against a concept this exact function's caller just
    retired and that hasn't since been re-evaluated into some other
    status by a later `run_selection` sweep (rare — the async dual-
    fork check resolves well within one monthly cadence — but checked
    explicitly rather than assumed); returns `None` and does nothing
    in that case, or if the concept no longer exists at all.

    Resets `fitness_history` to empty on reinstatement — the readings
    that triggered the retirement `run_selection` is judging are now
    known (by this stronger causal check) to have been misleading, so
    letting them count toward a second future retirement would be
    trusting the same discredited signal twice. Re-runs `_record_
    hypothesis_outcome(..., confirmed=True)`, which revises the SAME
    mirrored Innovation world_model entry `_record_hypothesis_
    outcome(..., confirmed=False)` wrote at retirement time (both key
    off the concept's own persistent `world_model_entry_id`), so the
    belief ends up reading as confirmed, not stuck on its own earlier
    refutation."""
    concept = world.invented_concepts.get(concept_id)
    if concept is None or concept.status != "retired":
        return None
    concept.status = "established"
    concept.fitness_history = []
    _record_hypothesis_outcome(world, concept, tick, confirmed=True)
    return concept


def fit_established_concepts(world) -> list[InventedConcept]:
    """A8's *select* step, second half: the pool `_maybe_schedule_
    ontology_evolution`'s evolve/merge should draw parents from —
    every `established` concept, but weighted so ones with a real
    positive mean fitness reading are more likely to be chosen (fit
    concepts becoming parents, per the spec) without categorically
    excluding an `established` concept that has no fitness reading yet
    (freshly promoted, hasn't hit a monthly sweep) or a mildly-below-
    average one that hasn't crossed the `run_selection` retirement bar.
    Returns concepts in a stable id order; the caller does the actual
    weighted pick."""
    return sorted(
        (c for c in world.invented_concepts.values() if c.status == "established"),
        key=lambda c: c.id,
    )


INNOVATION_EVOLUTION_LEAN_WEIGHT = 0.3
"""Tier 0's mirror-write -> pillar-authored conversion, fourth site
(docs/ROADMAP-2026-07-REMAINING.md; explicit user `AskUserQuestion`
answer: "yes, as an additional multiplier alongside fitness"). Unlike
the first three sites (each a final catchall tiebreak that never
touches a harder-computed branch above it), this one multiplies
directly into `concept_fitness_weight`'s own PRIMARY selection signal
— deliberately kept low so real fitness (the "did adopters prosper"
measurement) stays dominant; a pillar lean can only ever ADD up to
this fraction on top, never subtract or override it. `pillar_
lean=0.0` (the default, and every call site that doesn't pass one)
reproduces `concept_fitness_weight`'s exact prior output."""


def concept_fitness_weight(concept: InventedConcept, pillar_lean: float = 0.0) -> float:
    """Selection weight for `fit_established_concepts`' pool — a
    concept with no fitness reading yet reads as perfectly neutral
    (weight 1.0, the same as if `evaluate_fitness` returned exactly
    0.0), so it's neither favored nor penalized before it's had a
    chance to be measured. Floored well above 0 so an unlucky/unfit
    concept can still occasionally become a parent (real evolutionary
    diversity, not a hard cutoff duplicating `run_selection`'s own
    retirement threshold).

    `pillar_lean` (0..1, typically `innovation_pillar.subject_
    confidence(concept.name)` — see `INNOVATION_EVOLUTION_LEAN_
    WEIGHT`'s docstring): how confident Innovation's own accumulated
    `world_model` currently reads about THIS SPECIFIC concept, whether
    that's a fresh proposal's initial 0.4 confidence or a later
    confirmed/refuted revision from `_record_hypothesis_outcome` — a
    real signal distinct from `fitness_history` (adoption-measured
    prosperity): a concept can be freshly proposed with zero fitness
    history yet already carry a pillar lean, and an old concept with a
    settled fitness reading can have long since scrolled out of the
    pillar's own bounded recent-attention window (reads 0.0 there,
    same "absence means neutral" discipline as everywhere else)."""
    if not concept.fitness_history:
        base = 1.0
    else:
        mean_fitness = sum(concept.fitness_history) / len(concept.fitness_history)
        base = max(0.1, 1.0 + mean_fitness)
    return base * (1.0 + pillar_lean * INNOVATION_EVOLUTION_LEAN_WEIGHT)


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
        (c for c in world.invented_concepts.values() if c.status in ("abandoned", "retired") and prunable(c)),
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
    secondary_trigger: str = "", secondary_hook_type: str = "", secondary_hook_target: str = "",
    secondary_magnitude: float = 0.0,
) -> "TriggerRule":
    """Mints a new `TriggerRule` with the next id — the trigger-rule
    counterpart to `register_concept`. Never validates `trigger`/
    `hook_type` itself (that's `llm/rule_propose.py`'s job, same
    deterministic-re-verification discipline as `validate_hook`) —
    this is the pure mutator. `secondary_*` (item 1.1, composable
    hooks) defaults to empty/single-effect."""
    rule_id = world.next_trigger_rule_id
    world.next_trigger_rule_id += 1
    rule = TriggerRule(
        id=rule_id, name=name, description=description, trigger=trigger,
        hook_type=hook_type, hook_target=hook_target, magnitude=magnitude,
        origin_settlement_id=origin_settlement_id, tick_created=tick,
        secondary_trigger=secondary_trigger, secondary_hook_type=secondary_hook_type,
        secondary_hook_target=secondary_hook_target, secondary_magnitude=secondary_magnitude,
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


def register_composite_entity(
    world, name: str, base_kind: str, building_id: int, concept_id: int,
    origin_settlement_id: int, origin_story: str, tick: int, sigil_svg: str = "",
) -> "CompositeEntity":
    """Mints a new `CompositeEntity` — the item 4.1 counterpart to
    `register_concept`/`register_trigger_rule`. Pure mutator; the
    caller (`SimulationEngine._maybe_schedule_composite_entity`)
    already validated that `building_id` is a real standing building
    without an entity yet and `concept_id` a real registered concept."""
    entity_id = world.next_composite_entity_id
    world.next_composite_entity_id += 1
    entity = CompositeEntity(
        id=entity_id, name=name, base_kind=base_kind, building_id=building_id,
        concept_id=concept_id, origin_settlement_id=origin_settlement_id,
        origin_story=origin_story, tick_created=tick, sigil_svg=sigil_svg,
    )
    world.composite_entities[entity_id] = entity
    if len(world.composite_entities) > MAX_COMPOSITE_ENTITIES_STORED:
        oldest_id = min(world.composite_entities, key=lambda i: world.composite_entities[i].tick_created)
        del world.composite_entities[oldest_id]
    return entity


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
        # Item 1.1: a composed rule only counts as "never consumed" if
        # NEITHER side has ever fired — a rule whose secondary trigger
        # is doing real work shouldn't be retired just because
        # `fire_count` (primary-only) reads 0.
        ever_fired = rule.fire_count > 0 or rule.secondary_last_fired_tick >= 0
        if rule.status == "active" and not ever_fired and tick - rule.tick_created > TRIGGER_RULE_STALE_TICKS:
            rule.status = "retired"
