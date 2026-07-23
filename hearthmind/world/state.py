"""The World aggregate.

`World` is the single object that fully describes the simulation's state at
a point in time. It owns nothing that can't be serialized to a plain dict,
which is what makes snapshotting trivial (see persistence/snapshot.py).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from hearthmind.agents.agent import AgentGoal, AgentState
from hearthmind.agents.population import Population
from hearthmind.config import Config
from hearthmind.economy.farms import FarmGrid
from hearthmind.settlement.buildings import BuildingStage, Settlement
from hearthmind.settlement.naming import generate_settlement_name
from hearthmind.time_system import SimClock
from hearthmind.world.resources import ResourceGrid
from hearthmind.world.roads import RoadNetwork
from hearthmind.world.terrain import Biome, TerrainGrid, Tile, biome_counts, generate_terrain
from hearthmind.world.terrain_evolution import (
    ClimateState,
    apply_climate_drift,
    apply_local_activity,
    apply_disaster_scars,
    apply_mining_scars,
    decay_disaster_scars,
    decay_mining_scars,
    maybe_reclaim,
    nature_adaptation_bias,
    tick_climate,
)
from hearthmind.world.daylight import night_factor as compute_night_factor
from hearthmind.world.fields import FieldGrid
from hearthmind.world import emergence
from hearthmind.cognition.pillar import (
    Pillar, default_nature_pillar, default_village_pillar, default_humans_pillar,
    default_innovation_pillar, default_reflection_pillar,
)
from hearthmind.world.disasters import (
    DisasterState,
    WILDFIRE_IGNITION_HISTORY_MAX,
    tick_flood,
    tick_frost,
    tick_heatwave,
    tick_storm,
    tick_wildfire,
)
from hearthmind.world.hydrology import LakeState, generate_rivers, identify_lakes, tick_lakes
from hearthmind.world.hydrology_field import HydrologyField, create_hydrology_field, tick_hydrology
from hearthmind.world.minerals import MineralGrid
from hearthmind.world.ontology import CausalThread, CompositeEntity, InventedConcept, TriggerRule
from hearthmind.world.weather import WeatherState, compute_weather
from hearthmind.world.wildlife import SpeciesVariant, WildlifeGrid
from hearthmind.util import namespaced_rng

# Shared helper (hearthmind/util.py) under its historical private name so
# this module's call sites are unchanged.
_namespaced_rng = namespaced_rng


CONSCIOUSNESS_MEMORY_MAX = 16
"""Cap on `World.consciousness_memory` — Phase N, see its docstring."""

CONSCIOUSNESS_PLAYER_MODEL_MAX = 6
"""Cap on `World.consciousness_player_model` — small deliberately: this
is a private running theory, not a growing dossier."""

CONSCIOUSNESS_INTERVENTION_LOG_MAX = 12
"""Cap on `World.consciousness_intervention_log`."""

WEATHER_REGION_GRID = 3
"""§6 "Spatial weather" (docs/IDEAS-2026-07-EMERGENCE.md): the map is
divided into a `WEATHER_REGION_GRID` x `WEATHER_REGION_GRID` coarse
grid (9 regions by default) rather than one uniform reading — "even a
coarse 2-4 cell gradient gives geography consequences." Deliberately
NOT a per-tile field (that's a genuinely larger R7/C++-first
undertaking the doc itself flags) — this is the smallest real step
that gives two settlements on the same map a chance to experience
different weather at the same tick. Each region's `WeatherState` is
computed by the same `compute_weather` function as the global
reading, seeded with its own region id so regions drift independently
rather than all mirroring `World.weather`. Currently consumed only by
`Settlement.tick`'s building-decay catalyst (via `World.weather_at`)
— farms/wildlife/disasters stay on the single global `World.weather`
reading, a documented scope trim, not an oversight."""

HIGHLIGHTS_MAX_STORED = 30
"""Cap on `World.highlights` — a small, bounded log of self-flagged
emergent moments, not a growing archive (the full narrative record
already lives durably in the `events` table)."""

EMERGENCE_LOG_MAX_STORED = 500
"""Cap on `World.emergence_log` (see its own docstring) — bigger than
`HIGHLIGHTS_MAX_STORED` on purpose: highlights are a small hand-curated
human-facing log, the emergence stream is meant to be the pillars' full
sensory feed once Stage II consumers exist, so it needs headroom for a
busier signal without still growing unbounded. Small dicts, oldest
evicted — same discipline as every other capped ring in this codebase."""

CONSCIOUSNESS_REVISION_CONFIDENCE_GAIN = 0.1
"""Deferred item 6 (docs/VISION-2026-07-LEARNING.md), "consciousness
player-theory revision, round 2": how much a `consciousness_player_
model` entry's confidence rises each time the monthly job revises it
in place (`parsed["revises_leading"]`, `llm/consciousness.py`) rather
than appending an independent new theory — a theory that keeps holding
up under fresh evidence is held more firmly, capped at 1.0 the same
way every other confidence-shaped value in this project is."""

TERRAIN_CHANGING_CATEGORIES = frozenset({
    "terrain_thinned", "terrain_reclaimed", "climate_drift",
    "disaster_flood", "disaster_wildfire", "lake_rose", "lake_receded",
    "mining_scarred", "disaster_scarred",
})
"""Life-event categories that mean at least one tile's biome changed
this tick. Canonical home for this set (it used to live only in
simulation/engine.py for broadcast invalidation) — now also used by
`World._tick_disasters`' water-tile cache, so the two consumers can't
drift apart. Part of the July 2026 review's stringly-typed-events
cleanup."""


@dataclass
class World:
    config: Config
    clock: SimClock
    terrain: "list[list[Tile]] | TerrainGrid"
    """A `TerrainGrid` (R8 slice 2) behaving exactly like `list[list[
    Tile]]` for every existing access pattern — the type hint stays
    permissive since a few standalone scripts/tests still construct
    genuine nested lists directly and pass them through unchanged."""
    weather: WeatherState
    population: Population
    resources: ResourceGrid
    settlements: list[Settlement]
    """Every settlement in the world, founding settlement (id 0) first
    — the multi-settlement pass (v0.65.0). New settlements appear only
    through fission (SimulationEngine._maybe_schedule_fission); the
    list never shrinks (an emptied settlement's ruins decay away on
    their own, and its entry simply stops mattering — same
    "extinction is a legitimate ending" stance as population)."""
    farms: FarmGrid
    wildlife: WildlifeGrid
    roads: RoadNetwork
    climate: ClimateState = field(default_factory=ClimateState)
    lakes: list[LakeState] = field(default_factory=list)
    """Inland water bodies identified at world creation (world/hydrology.py)
    — distinct from the map-edge ocean, each with its own slowly-changing
    water level. Rivers don't need an equivalent list: they're carved once
    into `terrain` as Biome.RIVER tiles and persist through terrain's own
    (de)serialization with no extra state to track."""
    disasters: DisasterState = field(default_factory=DisasterState)
    """Flood pressure/active-flood tiles and any in-progress wildfire —
    see world/disasters.py."""
    hydrology_field: "HydrologyField" = field(default_factory=lambda: HydrologyField(moisture=[]))
    """A11 "Continuous hydrology," first slice (docs/MASTERCHECKLIST-
    2026-07-22.md, Stage IV step 15): a real per-tile surface-moisture
    field — precipitation, single-pass downhill redistribution, and
    evaporation, ticked weekly by `SimulationEngine._maybe_tick_
    hydrology`. Distinct from `lakes`/rivers above (which only answer
    "is this tile water") — every tile, not just water tiles, carries a
    real continuous quantity. See `world/hydrology_field.py`'s module
    docstring for the full scope (and what's deliberately deferred:
    groundwater, erosion into mutable elevation) and the flagged R7
    deviation (pure Python this pass, not yet natively ported)."""
    minerals: MineralGrid = field(default_factory=MineralGrid)
    """§8 expanded mineral economy (v0.87.25, docs/IDEAS-2026-07-
    EMERGENCE.md — explicit user directive): distinct iron/gold veins
    on hills terrain, generated once at world creation (empty grid on a
    legacy snapshot missing this key — a resumed old world simply has
    no mineral deposits, same "creation-only" stance the calendar shape
    already takes). See world/minerals.py."""
    terrain_activity: dict[tuple[int, int], float] = field(default_factory=dict)
    """Per-tile deforestation pressure (forest tiles only) — see
    world/terrain_evolution.py. Small and self-pruning (entries are
    deleted once heat decays to 0 or the tile changes biome), so it's
    fine to keep in memory/snapshot alongside everything else."""
    mining_scars: dict[tuple[int, int], float] = field(default_factory=dict)
    """§8 "NPC activity reshapes geography" (v0.87.27, docs/IDEAS-2026-
    07-EMERGENCE.md): per-tile visible pit/scar intensity (0..1) on
    hills tiles worked by GATHER-goal mining, distinct from
    `terrain_activity` (which drives an actual biome change) — mining
    stays cosmetic-only state, HILLS never stops being HILLS. Small and
    self-pruning like `terrain_activity`. See world/terrain_evolution.py
    `apply_mining_scars`/`decay_mining_scars`, `World._tick_terrain`."""
    disaster_scars: dict[tuple[int, int], float] = field(default_factory=dict)
    """Phase 3.D "permanent landscape scars from disasters" (docs/
    VISION-2026-07-21-SELFEVOLVING.md), same shape as `mining_scars`
    (cosmetic-only intensity, same R7-deviation rationale) — a tile
    repeatedly caught in a flood/wildfire accumulates a visible scar
    instead of always fully healing. See world/terrain_evolution.py
    `apply_disaster_scars`/`decay_disaster_scars`."""
    fallow_ticks: dict[tuple[int, int], int] = field(default_factory=dict)
    """Phase 3.D "succession — real intermediate stages, not an instant
    biome flip" — consecutive weeks a tile has qualified for reforesting
    (undeveloped grassland with enough forest neighbors); reset to 0 the
    moment it stops qualifying. See world/terrain_evolution.py
    `maybe_reclaim`/`_tick_fallow`, `REFOREST_MIN_FALLOW_WEEKS`."""
    llm_calls_total: int = 0
    llm_fallback_total: int = 0
    """Cumulative counts of every LLM-backed decision (cognition +
    chronicle) since world creation, and how many of those fell back to
    deterministic behavior — visible via `inspect_world` to diagnose a
    flaky/overloaded Ollama instance without reading server logs. See
    docs/DECISIONS.md, D5."""
    dialogue_total: int = 0
    rumor_total: int = 0
    """Cumulative counts of NPC dialogue exchanges and the rumors they've
    seeded since world creation — the same "make emergence visible in
    diagnostics" rationale as llm_calls_total, for a system (E2) that has
    no other cumulative counter. See docs/DECISIONS.md, E2/UI pass."""
    sim_summary_text: str = ""
    sim_summary_tick: int = -1
    sim_summary_pending: bool = False
    """On-demand LLM-authored simulation summary (the "summarize the
    sim, whenever asked" tab): `sim_summary_text` holds the most recent
    result, `sim_summary_tick` the tick it was generated on (-1 = never
    generated), `sim_summary_pending` true from the moment a
    `request_summary` intervention is applied until its `_schedule_
    llm_job` callback resolves — the UI polls `/summary` and shows a
    "generating..." state in between. Persisted (unlike last_life_events)
    so a page refresh or resumed world still shows the last summary
    rather than reading empty."""
    chronicler_question: str = ""
    chronicler_answer: str = ""
    chronicler_answer_tick: int = -1
    chronicler_pending: bool = False
    """§3 "Ask the Chronicler" (docs/IDEAS-2026-07-EMERGENCE.md): an
    on-demand, single-shot LLM call mirroring `sim_summary_*` above
    exactly — `chronicler_question` the observer's own typed question,
    `chronicler_answer` the settlement chronicler's most recent reply
    (answered strictly from folklore/chronicle/beliefs/records, never
    ground truth — see llm/chronicler.py), `chronicler_answer_tick` when
    it was generated (-1 = never asked), `chronicler_pending` true from
    the moment a `ask_chronicler` intervention is applied until its
    `_schedule_llm_job` callback resolves. Persisted like sim_summary_*
    so a page refresh still shows the last answer."""
    away_digest_text: str = ""
    away_digest_tick: int = -1
    away_digest_since_tick: int = -1
    away_digest_pending: bool = False
    away_digest_highlights: list[dict] = field(default_factory=list)
    """§5 "While you were away" digest (docs/IDEAS-2026-07-EMERGENCE.md):
    on-demand, mirrors `sim_summary_*`/`chronicler_*` exactly.
    `away_digest_since_tick` is the tick the PREVIOUS digest was
    generated at (or -1, meaning "since world start") — each new digest
    request covers events after that tick, then `away_digest_tick`
    becomes the new boundary for the NEXT request, so repeated requests
    never re-cover the same ground. Persisted like sim_summary_* so a
    page refresh still shows the last digest and the boundary survives
    a restart.

    `away_digest_highlights` (vision doc item 3.1, docs/VISION-2026-07-
    22-LIVINGTERRARIUM.md, "the morning paper"): the structured "front
    page" half — every `knowledge_tree()` entry originated strictly
    after `away_digest_since_tick`, i.e. what the world originated for
    itself during the away window (a new custom, a law the council
    passed, a Reflection hypothesis, a Nature belief), computed
    alongside the existing prose `away_digest_text` at zero extra LLM
    cost (`World.knowledge_tree` is a pure read). The prose headline
    stays the primary read; this is the "since you last looked, here's
    what got originated" section beneath it — not a replacement."""
    weather_regions: dict[tuple[int, int], WeatherState] = field(default_factory=dict)
    """§6 "Spatial weather": `(region_x, region_y) -> WeatherState`, one
    entry per cell of the `WEATHER_REGION_GRID` x `WEATHER_REGION_GRID`
    coarse grid — see `WEATHER_REGION_GRID`'s docstring and `World.
    weather_at`. Recomputed every tick in `World.tick()` alongside the
    global `weather` reading; empty only before the first tick (never
    persisted across that gap, same as `weather` itself needing at
    least one tick to exist meaningfully)."""
    highlights: list[dict] = field(default_factory=list)
    """§5 "Anomaly/highlight log" (docs/IDEAS-2026-07-EMERGENCE.md): the
    simulation's own bounded record of moments it judged notable
    (`{"kind": str, "detail": str, "tick": int}`), capped at
    HIGHLIGHTS_MAX_STORED (oldest evicted). Populated by
    `SimulationEngine._append_highlight` — some entries from hand-picked
    triggers at existing event-logging call sites (first religion,
    extinction near-miss, feud formation, first ritual/schism), others
    from a cheap rolling z-score over `metrics` rows (population/hunger
    swings) computed in `_log_daily_metrics`. Zero LLM cost by design —
    the doc's own framing: "if the highlight log is boring, the
    emergence isn't real yet.\""""
    emergence_log: list[dict] = field(default_factory=list)
    """A22 "The Emergence API" (docs/MASTERCHECKLIST-2026-07-22.md, Part
    A, Stage I step 1): the deterministic Body's structured sense-stream
    — curated observations tagged by *kind* (`world.emergence.
    OBSERVATION_KINDS`: anomaly/novel_combination/bottleneck/
    unexplained_shift/opportunity) and by which future cognitive
    pillar(s) (`world.emergence.PILLARS`: humans/village/nature/
    innovation/reflection) would care, not raw state. This is the
    Body↔Mind interface item the master checklist calls "the single
    most important... without it, cognition drowns in raw data or eats
    hand-picked slices" — no pillar refactor consumes it yet (that's
    Stage II), so today this is a real, populated, but not-yet-read
    sensory stream, same "build the organ before the consumer" shape
    `Population.voice_conversation` had before the voice-pair feature
    read it. Each entry: `{id, tick, kind, subsystem, summary, pillars,
    magnitude, settlement, data}` — see `world/emergence.py`'s `make_
    observation` for the exact contract. Capped at `EMERGENCE_LOG_MAX_
    STORED` (oldest evicted) — unlike `reflection_notebook` (never
    pruned, low natural volume), this is meant to be a genuinely busy
    stream once more Stage IV detectors feed it, so it needs a real cap
    from day one. Populated by `SimulationEngine._append_emergence`."""
    next_emergence_id: int = 1
    """Monotonic id counter for `emergence_log` — never reused, same
    discipline as `next_reflection_entry_id` and every other id counter
    in this codebase."""
    fields: FieldGrid = field(default_factory=FieldGrid)
    """A1 "Continuous environmental fields" (docs/MASTERCHECKLIST-2026-
    07-22.md, Part A, Stage I step 2): named scalar fields over the map
    (`world.fields.FieldGrid`), coarse (the existing 3x3 weather-region
    resolution) to start. Stepped once per tick (`World.tick`, right
    after `population.tick` so agent positions are current) via each
    field's own `step_*` method — today just `population_density`, the
    one field this pass ships as a real consumer proof; more fields are
    additive follow-ups onto the same grid. See `world/fields.py`."""
    nature_pillar: Pillar = field(default_factory=default_nature_pillar)
    """B1 "The Pillar abstraction" (docs/MASTERCHECKLIST-2026-07-22.md,
    Part B, Stage II step 4 — the keystone): Nature's persistent
    conscious-entity structure (identity, self-model, world-model,
    memory, objectives, inbox/outbox — `cognition/pillar.py`), proving
    the shape against the existing `_maybe_schedule_nature_mind` job
    before it's replicated to the other four future pillars (Humans,
    Village, Innovation, Reflection). Mirrors `World.nature_beliefs`
    into `nature_pillar.world_model` alongside it — `nature_beliefs`
    stays the source every existing consumer reads unchanged; this is
    additive, not a migration."""
    village_pillar: Pillar = field(default_factory=default_village_pillar)
    """B1, generalized (roadmap Stage II): Village's persistent
    conscious-entity structure, mirroring `_maybe_schedule_beliefs`
    (settlement-wide `Settlement.beliefs`, round-robin across named
    settlements) — same additive-mirror discipline as `nature_pillar`."""
    humans_pillar: Pillar = field(default_factory=default_humans_pillar)
    """B1/B7, generalized: Humans' persistent conscious-entity
    structure — the collective-mood/narrative-theme reading
    (`_maybe_schedule_narrative_direction`, itself derived from
    `Settlement.mood`, the aggregate of living agents' `Agent.
    emotions`), mirrored into `world_model`."""
    innovation_pillar: Pillar = field(default_factory=default_innovation_pillar)
    """B1/B5, generalized: Innovation's persistent conscious-entity
    structure, mirroring `_maybe_schedule_ontology_proposal`'s newly
    registered `InventedConcept`s (`World.invented_concepts`) into
    `world_model` — always additive (no revision path exists for
    concepts the way beliefs support `revises`)."""
    reflection_pillar: Pillar = field(default_factory=default_reflection_pillar)
    """B1/B6, generalized: Reflection's persistent conscious-entity
    structure, mirroring `_maybe_schedule_reflection`'s hypothesis
    formation (`World.reflection_notebook`) into `world_model` —
    Reflection is the one pillar that's world-scoped with no settlement
    round-robin, matching its existing job's shape."""
    consciousness_memory: list[dict] = field(default_factory=list)
    """Phase N "Town Consciousness v2" (docs/VISION-2026-07.md, "The Town
    Awake"): bounded log of what the town's persistent inner awareness
    has noticed (`{"note": str, "tick": int}`), capped at
    CONSCIOUSNESS_MEMORY_MAX. World-scoped (not per-settlement) — the
    consciousness is one hidden intelligence tied to the founding
    settlement, same "stays with the founding settlement" shape as
    player_standing/documentary/whispers, not something that multiplies
    with fission."""
    consciousness_personality: dict = field(default_factory=dict)
    """`{"curiosity": float, "patience": float, "possessiveness": float}`,
    each 0..1, genesis-seeded once (`llm.consciousness.seed_personality`
    — deterministic from `config.seed`, zero LLM cost) the first time
    `SimulationEngine._maybe_schedule_consciousness` runs. Empty `{}`
    until then. Deliberately static afterward — a settled temperament
    the monthly job reasons FROM, not a fourth Phase G random walk."""
    consciousness_objectives: list[dict] = field(default_factory=list)
    """At most 2 standing preoccupations (`{"objective": str,
    "formed_tick": int}`), revised only when the monthly consciousness
    call actually supplies new ones — otherwise held unchanged, per the
    vision doc's "LLM-revised rarely.\""""
    consciousness_player_model: list[dict] = field(default_factory=list)
    """The consciousness's own private, possibly-wrong theory about the
    player — same belief shape as `Settlement.beliefs` entries
    (`{"belief": str, "confidence": float, "formed_tick": int,
    "revised_tick": int, "revision_count": int}`) but never institution-
    mirrored (there's no institution this belongs to) and never shown to
    NPCs — this is the consciousness's model of the OUTSIDE hand, not a
    village belief about anything in-world. Capped at
    CONSCIOUSNESS_PLAYER_MODEL_MAX."""
    observer_attention: dict = field(default_factory=dict)
    """§4 "Observer attention as a signal into the Town Consciousness"
    (docs/IDEAS-2026-07-EMERGENCE.md): `{"agent_view_counts":
    {agent_id: count}, "last_agent_id": int|None, "last_seen_tick":
    int}` — a small, bounded record of which agents the observer has
    actually inspected in the UI (`POST /observer/attention`, fired
    from the NPC inspector on open), never anything about the observer
    themselves. `agent_view_counts` is capped at `OBSERVER_ATTENTION_
    MAX_TRACKED` entries (least-viewed evicted) so this can never grow
    with session length. Read (never written) by the monthly
    consciousness job as one more grounding fact, and by the omen/
    false-memory intervention mechanisms as a bias toward the
    observer's own favorite/most-recently-inspected agent — the
    existing intervention menu gaining a genuinely observer-aware
    target, still always with a mundane explanation available.
    Privacy note: entirely local, stored only in this world's own save
    file, never transmitted anywhere else."""
    consciousness_grudge_ledger: float = 0.0
    """§4 "The consciousness keeps a grudge ledger about interventions"
    (docs/IDEAS-2026-07-EMERGENCE.md): -1..1, nudged (never randomly
    walked — driven entirely by real intervention timing) each time a
    genuine player `/intervene/*` call lands, based on whether the
    settlement was visibly struggling at that moment (`_apply_
    intervention`'s `_intervention_hardship_context` check) — a nudge
    landing during real hardship reads as help and drifts this warm;
    one landing during calm/plenty reads as meddling without cause and
    drifts it cold. Distinct from `Settlement.player_standing` (Phase
    G's own separate bounded random walk, a settlement-level "feeling
    nudged" signal) — this is the CONSCIOUSNESS's own private ledger,
    world-scoped, folded into its monthly prompt as one more grounding
    fact so its own intervention choices may organically drift warmer
    or colder toward the player across months, legible only through
    pattern, never stated outright."""
    consciousness_intervention_log: list[dict] = field(default_factory=list)
    """Rolling log of what the monthly job has actually done
    (`{"kind": str, "detail": str, "tick": int}`, "none" entries included
    so a quiet month is visible too), capped at
    CONSCIOUSNESS_INTERVENTION_LOG_MAX — the dev-console surface, and
    also fed back into the next prompt so the consciousness doesn't
    repeat itself unknowingly."""
    consciousness_pending_temperament_nudge: float = 0.0
    """One-shot bounded nudge queued by a `temperament_nudge`
    intervention, consumed (and reset to 0.0) by the very next
    `_maybe_tick_temperament` call for the founding settlement — see
    `tick_temperament`'s `extra` parameter. Never itself serialized
    (a nudge left pending across a save/restart would apply twice, once
    from each process) — see `to_dict`'s comment on `sim_summary_
    pending` for the identical shape of this concern."""
    last_calendar_events: list[str] = field(default_factory=list)
    last_life_events: list[tuple[str, str]] = field(default_factory=list, compare=False)
    """(category, description) pairs from this tick's births/deaths, for the
    caller to log. Never serialized — recomputed fresh every tick."""
    migrated_subsystems: list[str] = field(default_factory=list, compare=False)
    """Names of subsystems that were missing from a loaded snapshot and got
    freshly backfilled (e.g. ["population", "resources"]) — lets the caller
    (SimulationEngine) log a one-off migration event per subsystem and
    persist the change. Never itself serialized; see docs/DECISIONS.md,
    M2-3 and A4."""
    invented_concepts: dict[int, InventedConcept] = field(default_factory=dict)
    """The Innovation Layer's persistent registry (Phase 1, docs/
    VISION-2026-07-21-SELFEVOLVING.md) — see world/ontology.py. World-
    scoped, not per-settlement: an invented concept is a first-class
    object any settlement/system can reference, same "shared, not
    settlement-private" reasoning `roads`' paving tier already
    established."""
    next_concept_id: int = 1
    """Monotonic id counter for `invented_concepts` — never reused,
    same discipline as every other id counter in this codebase (e.g.
    `Population`'s own agent-id counter)."""
    trigger_rules: dict[int, TriggerRule] = field(default_factory=dict)
    """Vision doc item 1.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
    ("A conditional/trigger vocabulary as data") — village-originated
    trigger→effect rules, world-scoped like `invented_concepts` (same
    "shared, not settlement-private" reasoning), see world/ontology.py.
    `SimulationEngine._apply_trigger_rules_for` fires these when a
    matching real event occurs; `_maybe_schedule_rule_proposal`
    originates new ones, gated through the counterfactual sandbox
    (item 1.3, `simulation/sandbox.py`) before going live."""
    next_trigger_rule_id: int = 1
    composite_entities: dict[int, CompositeEntity] = field(default_factory=dict)
    """Vision doc item 4.1 (docs/VISION-2026-07-22-LIVINGTERRARIUM.md,
    "Composite entities from existing primitives") — world-scoped like
    `invented_concepts`/`trigger_rules`, see world/ontology.py.
    `SimulationEngine._maybe_schedule_composite_entity` originates new
    ones, binding a real standing building to a real `InventedConcept`
    via a name and an origin story."""
    next_composite_entity_id: int = 1
    species_variants: dict[int, SpeciesVariant] = field(default_factory=dict)
    """Vision doc item 4.2 ("Emergent species/variants via parameter-
    space") — world-scoped like `composite_entities`. `SimulationEngine.
    _maybe_schedule_species_variant` originates new ones, naming a real
    existing wildlife herd via `llm/species_variant.py`."""
    next_species_variant_id: int = 1
    causal_threads: dict[int, CausalThread] = field(default_factory=dict)
    """Vision doc item 3.3 ("Legible causal threads") — world-scoped
    like `composite_entities`. `SimulationEngine._maybe_schedule_
    dispute` captures the concrete grounding facts already computed for
    a feud/ostracism/council_ruling outcome into a `CausalThread`, see
    world/ontology.py's docstring for the scoping rationale."""
    next_causal_thread_id: int = 1
    nature_beliefs: list[dict] = field(default_factory=list)
    """Nature's Mind (Body/Mind framing, CLAUDE.md "Design priorities" —
    explicit user direction 2026-07-21): the land's own running,
    revisable theories about its condition — same shape/discipline as
    `Settlement.beliefs` (subject/belief/confidence/formed_tick/
    revised_tick/revision_count), world-scoped rather than per-
    settlement (the land isn't any one village's). Capped at
    `llm.beliefs.MAX_BELIEFS`, weakest-confidence eviction, same as
    settlement beliefs. See `llm/nature_mind.py`, `SimulationEngine.
    _maybe_schedule_nature_mind`."""
    reflection_notebook: list[dict] = field(default_factory=list)
    """Phase 5.A (docs/VISION-2026-07-21-SELFEVOLVING.md, "Start the
    5th item"): the persistent research notebook of Hearthmind's own
    reflective intelligence — a FIFTH participant observing the other
    four pillars' long-term behavior, never their objective state
    directly. Each entry: `{id, created_tick, kind: hypothesis|
    observation, subject, content, confidence, evidence_for,
    evidence_against, status: open|supported|rejected, supersedes}`.
    Deliberately NEVER pruned (unlike every other capped log in this
    codebase) — "preserve rejected hypotheses as historical knowledge"
    is structural, not aspirational; low natural volume (one entry per
    reflection cycle at most, year-cadence) keeps this safe without an
    artificial cap. See `llm/reflection.py`, `SimulationEngine.
    _maybe_schedule_reflection`."""
    next_reflection_entry_id: int = 1
    """Monotonic id counter for `reflection_notebook` — never reused,
    same discipline as every other id counter in this codebase."""
    wildfire_ignition_ticks: list[int] = field(default_factory=list)
    """Rolling window (capped at `WILDFIRE_IGNITION_HISTORY_MAX`) of the
    tick each real wildfire ignition fired — the deterministic signal
    `SimulationEngine._detect_reflection_pattern`'s governor-drift
    branch compares against `disasters.WILDFIRE_CHANCE_PER_WEEK`'s own
    theoretical rate to notice a real, sustained drift (vision doc item
    1.4's own example: "wildfires feel too rare to matter")."""
    governor_tuning: dict[str, float] = field(default_factory=dict)
    """Vision doc items 1.4/2.4: governor name -> effective multiplier,
    bounded to `disasters.GOVERNOR_TUNING_BAND` around 1.0. Missing key
    means untouched (multiplier 1.0). Consumers: `tick_wildfire`'s
    `chance_multiplier` (key `"wildfire_chance"`), `_maybe_schedule_
    ontology_proposal`'s invention-chance scale (key `"ontology_
    proposal_chance"`), `Population._maybe_outbreak`'s `chance_
    multiplier` (key `"disease_outbreak_chance"`, B6, roadmap Stage III
    step 13) — see `SimulationEngine._maybe_schedule_self_tuning`, the
    only writer."""
    musings: list[dict] = field(default_factory=list)
    """Vision doc item 3.4, "The world talks to you"
    (docs/VISION-2026-07-22-LIVINGTERRARIUM.md): a once-a-day line in
    Reflection's own voice — not a stat, a musing — `{tick, text}`,
    capped at MUSING_HISTORY_MAX (this is texture for the daily-peek
    experience, not a persistent-knowledge structure like `reflection_
    notebook`, so it prunes unlike that list). Grounded in a real open
    `reflection_notebook` hypothesis or a recent `knowledge_tree()`
    entry when one exists; a genuine "nothing notable to muse on yet"
    fallback otherwise — never fabricated. See `llm/musing.py`,
    `SimulationEngine._maybe_schedule_musing`."""
    self_tuning_actions: list[dict] = field(default_factory=list)
    """Vision doc item 2.4 ("Reflection may enact ONE validated
    self-tuning proposal per long period, logged verbosely as the
    world's own decision"): append-only record of every enacted
    tuning — `{id, tick, governor, hypothesis_id, direction, magnitude,
    new_multiplier, rationale}`. Never pruned (low natural volume, at
    most one per year-cadence reflection cycle, same discipline as
    `reflection_notebook`) — this IS the terrarium's own decision log,
    read by `_maybe_schedule_self_tuning` to avoid re-acting on a
    hypothesis it already tuned for."""
    advisory_proposals: list[dict] = field(default_factory=list)
    """B6 "Reflection as meta-scientist" (roadmap Stage III step 13):
    the human-reviewed counterpart to `self_tuning_actions` above, for
    a supported hypothesis whose subject names no `self_tuning.
    TUNABLE_GOVERNORS` entry — Reflection still has something worth
    saying, it just isn't a bounded numeric nudge the sandbox can
    validate on its own. `{id, tick, hypothesis_id, subject, advice,
    status}` — `status` starts `"pending"` and is the ONLY field a
    human can change (`POST /advisory/{id}/review`, queued through the
    same `_apply_intervention` seam as every other player action) to
    `"accepted"`/`"rejected"` — never auto-applied, never auto-scored;
    this is advice logged for a person to act on outside the
    simulation, not a second self-tuning channel. Never pruned, same
    append-only discipline as `self_tuning_actions`/`reflection_
    notebook` (identical low natural volume — at most one per year-
    cadence reflection cycle)."""
    next_advisory_id: int = 1
    """Monotonic id counter for `advisory_proposals` — never reused,
    same discipline as every other id counter in this codebase."""
    _water_tiles: set = field(default=None, compare=False, repr=False)  # type: ignore[assignment]
    """Cached set of water-biome tile coords for `_tick_disasters` —
    previously rebuilt with a full terrain scan every tick even though
    water only changes on the rare TERRAIN_CHANGING_CATEGORIES events.
    Never serialized; None means "recompute". July 2026 review, §6.3."""
    newly_named_settlement_ids: list = field(default_factory=list, compare=False, repr=False)
    """Ids of settlements whose deterministic placeholder name was
    assigned THIS tick — consumed by SimulationEngine's per-settlement
    background-naming scheduler the same tick, never serialized (same
    transient shape as last_life_events)."""
    _biome_counts_cache: dict = field(default=None, compare=False, repr=False)  # type: ignore[assignment]
    """Same caching pattern as `_water_tiles`, for `summary()`'s
    biome_counts (audit perf pass): `summary()` runs every tick for the
    broadcast payload, and a bare `biome_counts()` call scans every tile
    — 16,384 of them on a 128x128 world — for numbers that only change
    on the same rare TERRAIN_CHANGING_CATEGORIES events the water cache
    already keys off. Invalidated at the end of `tick()` whenever one of
    those events fired; never serialized."""

    @property
    def settlement(self) -> Settlement:
        """The founding settlement — kept as a property so the very
        large number of single-settlement-era call sites (and the
        primary-settlement semantics of whispers, documentaries, and
        world-level geography names) read naturally."""
        return self.settlements[0]

    def weather_at(self, pos: tuple[int, int] | None) -> WeatherState:
        """§6 "Spatial weather": the regional `WeatherState` covering
        `pos` (a settlement's `center()`), falling back to the single
        global `weather` reading when `pos` is None (a brand-new
        settlement with no buildings yet to infer a center from) or
        before the first tick has populated `weather_regions`."""
        if pos is None or not self.weather_regions:
            return self.weather
        width = max(1, self.config.width)
        height = max(1, self.config.height)
        rx = min(WEATHER_REGION_GRID - 1, pos[0] * WEATHER_REGION_GRID // width)
        ry = min(WEATHER_REGION_GRID - 1, pos[1] * WEATHER_REGION_GRID // height)
        return self.weather_regions.get((rx, ry), self.weather)

    # --- construction ----------------------------------------------------

    @classmethod
    def create_new(cls, config: Config, founding_scenario: str = "") -> "World":
        clock = SimClock(config=config, tick_count=0)
        # R8 slice 2: terrain is stored via TerrainGrid (native-backed
        # flat-array storage when hearthmind._native is built) instead
        # of a plain list[list[Tile]] — every existing terrain[y][x]/
        # len(terrain)/for-row-in-terrain call site works unchanged
        # since TerrainGrid implements the same protocol. generate_
        # terrain itself still returns a plain nested list (its diamond-
        # square algorithm is easiest to write against one); wrapped
        # here so every subsequent mutation (generate_rivers, and every
        # per-tick terrain-evolution/disaster/hydrology call for the
        # rest of the world's life) goes through the wrapper. See
        # world/terrain.py, docs/DECISIONS.md "terrain grid port."
        terrain = TerrainGrid.from_nested(
            generate_terrain(seed=config.seed, width=config.width, height=config.height)
        )
        generate_rivers(seed=config.seed, terrain=terrain)
        lakes = identify_lakes(terrain)
        hydrology_field = create_hydrology_field(terrain)
        weather = compute_weather(seed=config.seed, tick=0, month=clock.month_name.lower(), previous=None)
        resources = ResourceGrid.generate(seed=config.seed, terrain=terrain)
        minerals = MineralGrid.generate(seed=config.seed, terrain=terrain)
        # Resources before population: founders spawn clustered around
        # the best local food supply (see Population.spawn_initial).
        population = Population.spawn_initial(
            seed=config.seed, count=config.initial_population, terrain=terrain, resources=resources,
        )
        settlements = [Settlement(founding_scenario=founding_scenario)]  # settlements emerge from population behavior, not pre-placed
        farms = FarmGrid()  # likewise: no farms exist until agents plant them
        wildlife = WildlifeGrid.generate(seed=config.seed, terrain=terrain)
        roads = RoadNetwork()  # paths emerge from foot traffic, not pre-placed
        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            population=population, resources=resources, settlements=settlements, farms=farms,
            wildlife=wildlife, roads=roads, lakes=lakes, minerals=minerals,
            hydrology_field=hydrology_field,
        )

    # --- tick --------------------------------------------------------------

    def tick(self) -> list[str]:
        """Advance the world by one tick. Returns calendar-boundary events
        crossed (e.g. ["day_end"]), for the caller to log. Births/deaths/
        construction/farming events from this tick are left on
        `last_life_events` for the caller."""
        events = self.clock.advance()
        self.weather = compute_weather(
            seed=self.config.seed,
            tick=self.clock.tick_count,
            month=self.clock.month_name.lower(),
            previous=self.weather,
        )
        month_name = self.clock.month_name.lower()
        new_regions: dict[tuple[int, int], WeatherState] = {}
        for rx in range(WEATHER_REGION_GRID):
            for ry in range(WEATHER_REGION_GRID):
                # A cheap deterministic per-region seed offset (not a
                # full namespaced_rng draw — this runs every tick, and
                # all `compute_weather` needs is a distinct seed per
                # region so they drift independently rather than
                # mirroring the global reading tick-for-tick).
                region_seed = self.config.seed + rx * 1009 + ry * 31
                new_regions[(rx, ry)] = compute_weather(
                    seed=region_seed,
                    tick=self.clock.tick_count,
                    month=month_name,
                    previous=self.weather_regions.get((rx, ry)),
                )
        self.weather_regions = new_regions
        self.resources.tick(season=self.clock.season)
        self.minerals.tick(season=self.clock.season)
        self.farms.tick(season=self.clock.season, terrain=self.terrain)
        wildlife_events = self.wildlife.tick(
            seed=self.config.seed, tick=self.clock.tick_count, terrain=self.terrain, resources=self.resources,
            temperament=self.settlement.temperament, season=self.clock.season,
        )
        settlement_events: list[tuple[str, str]] = []
        self.newly_named_settlement_ids = []
        for stl in self.settlements:
            settlement_events += stl.tick(weather=self.weather_at(stl.center()), season=self.clock.season)
            has_standing_building = any(b.stage is BuildingStage.STANDING for b in stl.buildings)
            if not stl.name and has_standing_building:
                rng = _namespaced_rng(
                    self.config.seed, self.clock.tick_count, f"settlement_naming_{stl.id}",
                )
                stl.name = generate_settlement_name(rng)
                noun = "The village" if stl.id == 0 else "The new settlement"
                settlement_events.append(("settlement_named", f"{noun} was named {stl.name}."))
            # Queue the background LLM naming job whenever a settlement
            # has a placeholder it hasn't gotten a real name for yet —
            # not just the one tick the placeholder is first assigned.
            # A resumed world already has `stl.name` truthy (the
            # placeholder was persisted), so gating this solely on
            # "name just got set" left it permanently un-renameable
            # after any restart (v0.68.0 fix, see `llm_named`).
            if stl.name and not stl.llm_named and has_standing_building:
                self.newly_named_settlement_ids.append(stl.id)
        night = compute_night_factor(
            hour_of_day=self.clock.minute_of_day / 60.0, month_name=self.clock.month_name,
        )
        disaster_events = self._tick_disasters(events)
        storm_struck = any(category == "disaster_storm" for category, _ in disaster_events)
        population_events = self.population.tick(
            seed=self.config.seed, tick=self.clock.tick_count,
            terrain=self.terrain, resources=self.resources, minerals=self.minerals,
            settlements=self.settlements, farms=self.farms, wildlife=self.wildlife, roads=self.roads,
            weather=self.weather, night_factor=night, heatwave_active=self.disasters.heatwave_active,
            month_end="month_end" in events, core_cast_target=self.config.llm_core_cast_size,
            map_tiles=self.config.width * self.config.height,
            flooded_tiles=self.disasters.flooded_tiles,
            active_wildfire_tiles=self.disasters.active_wildfire_tiles,
            storm_struck=storm_struck,
            outbreak_chance_multiplier=self.governor_tuning.get("disease_outbreak_chance", 1.0),
            hydrology_moisture=self.hydrology_field.moisture,
        )
        self.fields.step_population_density(
            [(a.x, a.y) for a in self.population.agents], self.config.width, self.config.height,
        )
        terrain_events = self._tick_terrain(events)
        self.last_life_events = (
            wildlife_events + settlement_events + population_events + terrain_events + disaster_events
        )
        self.last_calendar_events = events
        if self._biome_counts_cache is not None and any(
            category in TERRAIN_CHANGING_CATEGORIES for category, _ in self.last_life_events
        ):
            self._biome_counts_cache = None  # a tile's biome changed this tick — see the field's docstring
        return events

    def _tick_disasters(self, calendar_events: list[str]) -> list[tuple[str, str]]:
        """Flood/heatwave/wildfire/storm/frost — see world/disasters.py.
        Called before population.tick so a heatwave/frost triggered this
        tick is already visible to agents/farms in the same tick. Flood,
        heatwave, storm, and frost all roll every tick (each rare-per-tick
        by construction); wildfire ignition only rolls on a week boundary,
        though an already-burning fire still spreads/dies down every
        tick."""
        if self._water_tiles is None or any(
            category in TERRAIN_CHANGING_CATEGORIES for category, _ in self.last_life_events
        ):
            # `last_life_events` still holds the *previous* tick's events
            # here (this runs before population/terrain ticks refresh it),
            # which is exactly the signal needed: recompute only after a
            # tick that actually changed some tile's biome.
            self._water_tiles = {
                (t.x, t.y) for row in self.terrain for t in row
                if t.biome in (Biome.DEEP_WATER, Biome.SHALLOW_WATER, Biome.RIVER)
            }
        water_tiles = self._water_tiles
        flood_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_flood")
        events = tick_flood(
            self.disasters, self.terrain, self.weather, self.settlements, self.farms, water_tiles, flood_rng,
        )
        heat_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_heatwave")
        events += tick_heatwave(self.disasters, self.weather, self.farms, heat_rng)
        fire_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_wildfire")
        wildfire_events = tick_wildfire(
            self.disasters, self.terrain, self.weather, self.clock.season, self.settlement.temperament,
            self.settlements, "week_end" in calendar_events, fire_rng,
            heatwave_active=self.disasters.heatwave_active, farms=self.farms,
            chance_multiplier=self.governor_tuning.get("wildfire_chance", 1.0),
        )
        if any(desc != "The wildfire burned itself out." for cat, desc in wildfire_events if cat == "disaster_wildfire"):
            self.wildfire_ignition_ticks.append(self.clock.tick_count)
            if len(self.wildfire_ignition_ticks) > WILDFIRE_IGNITION_HISTORY_MAX:
                self.wildfire_ignition_ticks.pop(0)
        events += wildfire_events
        storm_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_storm")
        events += tick_storm(self.weather, self.settlements, storm_rng)
        frost_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_frost")
        events += tick_frost(self.disasters, self.weather, self.farms, frost_rng)
        if "month_end" in calendar_events and self.lakes:
            occupied_tiles = {(a.x, a.y) for a in self.population.agents}
            lake_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "lakes")
            events += tick_lakes(self.lakes, self.terrain, self.climate.drying, lake_rng, occupied_tiles)
        if "week_end" in calendar_events:
            # A11 "Continuous hydrology," first slice (Stage IV step
            # 15): weekly cadence, not per-tick — see hydrology_field.
            # py's own R7-deviation docstring for why.
            hydro_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "hydrology")
            tick_hydrology(
                self.hydrology_field, self.terrain, self.weather.precipitation, self.clock.season, hydro_rng,
            )
        return events

    def _tick_terrain(self, calendar_events: list[str]) -> list[tuple[str, str]]:
        """Local activity-driven terrain change (every tick), plus the
        rarer reclaim (weekly) and climate drift (monthly) passes — see
        world/terrain_evolution.py. Decoupled from season/year boundaries
        (previously: reclaim per season, drift per year) so the real
        365-day calendar doesn't stretch out how often the map visibly
        changes — a full year is now 365 days instead of 80, so tying
        these to season/year boundaries the old way would have made
        terrain evolution ~4.5x rarer in wall-clock terms, not just
        differently-timed."""
        occupied_tiles = {(a.x, a.y) for a in self.population.agents}
        active_forest_tiles = {
            (a.x, a.y) for a in self.population.agents
            if a.state is AgentState.AWAKE and a.goal is AgentGoal.GATHER
            and self.terrain[a.y][a.x].biome is Biome.FOREST
        }
        active_mining_tiles = {
            (a.x, a.y) for a in self.population.agents
            if a.state is AgentState.AWAKE and a.goal is AgentGoal.GATHER
            and self.terrain[a.y][a.x].biome is Biome.HILLS
        }
        rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "terrain_activity")
        events = apply_local_activity(self.terrain, active_forest_tiles, self.terrain_activity, rng)
        events += apply_mining_scars(active_mining_tiles, self.mining_scars)
        # Phase 3.D: `self.disasters.flooded_tiles`/`active_wildfire_
        # tiles` are already updated for THIS tick by `_tick_disasters`,
        # which runs before `_tick_terrain` in `tick()` — no staleness.
        events += apply_disaster_scars(
            self.disasters.flooded_tiles, self.disasters.active_wildfire_tiles, self.disaster_scars,
        )

        if "week_end" in calendar_events:
            reclaim_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "terrain_reclaim")
            events += maybe_reclaim(
                self.terrain, self.terrain_activity, self.settlements, self.farms, occupied_tiles, reclaim_rng,
                self.fallow_ticks, moisture=self.hydrology_field.moisture,
            )
            decay_mining_scars(self.mining_scars)
            decay_disaster_scars(self.disaster_scars, nature_adaptation_bias(self.nature_beliefs))

        if "month_end" in calendar_events:
            climate_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "climate_drift")
            tick_climate(self.climate, climate_rng)
            events += apply_climate_drift(
                self.terrain, self.climate, self.settlements, self.farms, occupied_tiles, climate_rng,
            )

        return events

    # --- summary for humans / the future interface ------------------------

    def cached_biome_counts(self) -> dict:
        """Biome tally with the terrain-change-invalidated cache — see
        `_biome_counts_cache`. Shared by `summary()` and the engine's
        named-geography job (which needs to know whether a river
        exists without a full scan)."""
        if self._biome_counts_cache is None:
            self._biome_counts_cache = biome_counts(self.terrain)
        return self._biome_counts_cache

    def summary(self) -> dict:
        place_names = self.settlement.place_names
        return {
            "tick": self.clock.tick_count,
            "date": self.clock.date_string(),
            "clock": self.clock.clock_string(),
            "month": self.clock.month_name,
            "season": self.clock.season,
            "year": self.clock.year,
            "weather": self.weather.describe(),
            "weather_detail": self.weather.to_dict(),
            "biome_counts": dict(self.cached_biome_counts()),
            "climate": self.climate.to_dict(),
            "night_factor": round(compute_night_factor(
                hour_of_day=self.clock.minute_of_day / 60.0, month_name=self.clock.month_name,
            ), 3),
            "lakes": [
                {
                    "id": lake.id, "tiles": len(lake.tiles), "level": round(lake.level, 3),
                    "name": place_names.get(f"lake_{lake.id}", ""),
                }
                for lake in self.lakes
            ],
            "river_name": place_names.get("river", ""),
            "disasters": {
                "flood_pressure": round(self.disasters.flood_pressure, 3),
                "active_flood_tiles": len(self.disasters.flooded_tiles),
                "active_wildfire_tiles": len(self.disasters.active_wildfire_tiles),
                "heat_pressure": round(self.disasters.heat_pressure, 3),
                "heatwave_active": self.disasters.heatwave_active,
                "frost_ticks": self.disasters.frost_ticks,
            },
            "world_size": f"{self.config.width}x{self.config.height}",
            "population": self.population.summary(),
            "resources": self.resources.summary(),
            "minerals": self.minerals.summary(),
            "mining_scars": {
                "scarred_tiles": len(self.mining_scars),
                "avg_intensity": (
                    round(sum(self.mining_scars.values()) / len(self.mining_scars), 3)
                    if self.mining_scars else 0.0
                ),
            },
            "disaster_scars": {
                "scarred_tiles": len(self.disaster_scars),
                "avg_intensity": (
                    round(sum(self.disaster_scars.values()) / len(self.disaster_scars), 3)
                    if self.disaster_scars else 0.0
                ),
            },
            "hydrology": {"avg_moisture": round(self.hydrology_field.average(), 3)},
            "nature_beliefs": [
                {"subject": b["subject"], "belief": b["belief"], "confidence": b["confidence"]}
                for b in self.nature_beliefs
            ],
            "settlement": self.settlement.summary(established_roads=self.roads.summary()["established_roads"]),
            "settlements": [
                {
                    "id": stl.id,
                    "name": stl.name,
                    "center": stl.center(),
                    "members": stl.living_member_count(self.population.agents),
                    "standing": sum(1 for b in stl.buildings if b.stage is BuildingStage.STANDING),
                    "era": stl.era,
                    # §6 "Spatial weather" (docs/IDEAS-2026-07-EMERGENCE.md):
                    # this settlement's own regional reading, which can
                    # genuinely differ from the global `weather` key above
                    # once settlements are far enough apart to land in
                    # different WEATHER_REGION_GRID cells.
                    "local_weather": self.weather_at(stl.center()).describe(),
                }
                for stl in self.settlements
            ],
            "farms": self.farms.summary(),
            "wildlife": self.wildlife.summary(),
            "roads": self.roads.summary(self.weather),
            "llm": {
                "calls_total": self.llm_calls_total,
                "fallback_total": self.llm_fallback_total,
                "fallback_rate": (
                    round(self.llm_fallback_total / self.llm_calls_total, 3)
                    if self.llm_calls_total else 0.0
                ),
                "dialogue_total": self.dialogue_total,
                "rumor_total": self.rumor_total,
            },
            "sim_summary": {
                "text": self.sim_summary_text,
                "tick": self.sim_summary_tick,
                "pending": self.sim_summary_pending,
            },
            "chronicler": {
                "question": self.chronicler_question,
                "answer": self.chronicler_answer,
                "tick": self.chronicler_answer_tick,
                "pending": self.chronicler_pending,
            },
            # C3 "Player <-> Pillar chat" (roadmap Stage III step 10):
            # same {question, answer, tick, pending} shape as
            # "chronicler" above, one entry per cognitive pillar, so the
            # UI/`/ask/{pillar}` polling logic can reuse the exact same
            # pattern it already has for the chronicler.
            "pillars": {
                name: {
                    "question": getattr(self, f"{name}_pillar").last_question,
                    "answer": getattr(self, f"{name}_pillar").last_answer,
                    "tick": getattr(self, f"{name}_pillar").last_answer_tick,
                    "pending": getattr(self, f"{name}_pillar").pending,
                }
                for name in emergence.PILLARS
            },
            "away_digest": {
                "text": self.away_digest_text,
                "tick": self.away_digest_tick,
                "since_tick": self.away_digest_since_tick,
                "pending": self.away_digest_pending,
                "highlights": list(self.away_digest_highlights),
            },
            "latest_musing": self.musings[-1] if self.musings else None,
            "consciousness": {
                "personality": dict(self.consciousness_personality),
                "memory": list(self.consciousness_memory),
                "objectives": list(self.consciousness_objectives),
                "player_model": list(self.consciousness_player_model),
                "interventions": list(self.consciousness_intervention_log),
                "grudge_ledger": round(self.consciousness_grudge_ledger, 3),
            },
            "observer_attention": {
                "tracked_agents": len(self.observer_attention.get("agent_view_counts", {})),
                "last_agent_id": self.observer_attention.get("last_agent_id"),
                "last_seen_tick": self.observer_attention.get("last_seen_tick", -1),
            },
            "highlights": list(self.highlights),
        }

    def knowledge_tree(self, limit: int = 200) -> list[dict]:
        """Vision doc item 3.2, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
        ("What the world learned" ledger — CERTAIN, mostly-existing-
        data): a single, browsable, newest-first aggregation of every
        LLM-originated persistent entity in the world, across all four
        pillars plus Reflection, with lineage where it exists. Reads
        only — no new state, no new LLM call. Sources: `invented_
        concepts` (Innovation + every pillar's ontology origination,
        `lineage`'s `evolved_from`/`merged_from` preserved), each
        settlement's `laws` (Village — law/custom/taboo), `reflection_
        notebook` hypotheses (Reflection — status/confidence), and
        `nature_beliefs` (Nature). Capped at `limit` (default 200,
        matching `ontology.MAX_CONCEPTS_STORED`'s order of magnitude)
        so the endpoint payload stays bounded even on a world that's
        run for months — the underlying stores are each already capped
        independently; this cap is just a display ceiling on top."""
        def _agent_name(agent_id: int | None) -> str | None:
            if agent_id is None:
                return None
            agent = self.population.get(agent_id)
            return agent.name if agent is not None else "someone no longer living"

        entries: list[dict] = []
        for concept in self.invented_concepts.values():
            text = concept.description
            if concept.hypothesis:
                # B5 "Innovation as conscious scientist" (roadmap Stage
                # III step 12): the hypothesis this concept was meant
                # to test is real, player-legible context for "why does
                # this idea exist," not dev-console-only detail.
                text = f"{text} (a hopeful answer to: {concept.hypothesis})"
            entries.append({
                "type": "concept", "id": f"concept_{concept.id}", "kind": concept.category,
                "name": concept.name, "text": text, "status": concept.status,
                "tick": concept.tick_invented, "settlement": concept.origin_settlement_id,
                "lineage": dict(concept.lineage) if concept.lineage else None,
                "who": _agent_name(concept.inventor_agent_id) or "the village",
            })
        for settlement in self.settlements:
            for i, law in enumerate(settlement.laws):
                entries.append({
                    "type": "law", "id": f"law_{settlement.id}_{i}", "kind": law.get("kind", "law"),
                    "name": law.get("text", "")[:40], "text": law.get("text", ""), "status": "active",
                    "tick": law.get("formed_tick", 0), "settlement": settlement.name, "lineage": None,
                    "who": settlement.name or "the village",
                })
        for entry in self.reflection_notebook:
            if entry.get("kind") not in ("hypothesis", "conclusion", "question"):
                continue
            entries.append({
                "type": entry["kind"], "id": f"reflection_{entry['id']}", "kind": entry.get("subject", ""),
                "name": entry.get("subject", ""), "text": entry.get("content", ""),
                "status": entry.get("status", "open"), "tick": entry.get("created_tick", 0),
                "confidence": entry.get("confidence"),
                "settlement": None, "lineage": {"supersedes": entry["supersedes"]} if entry.get("supersedes") else None,
                "who": "Hearthmind's own reflection",
            })
        for i, belief in enumerate(self.nature_beliefs):
            entries.append({
                "type": "nature_belief", "id": f"nature_{i}", "kind": belief.get("subject", ""),
                "name": belief.get("subject", ""), "text": belief.get("belief", ""), "status": "held",
                "tick": belief.get("formed_tick", 0), "confidence": belief.get("confidence"),
                "settlement": None, "lineage": None, "who": "the land itself",
            })
        for rule in self.trigger_rules.values():
            # Item 1.5 ("a visible law of nature ontology"): fire_count
            # (and the secondary side's own last-fired tick) is what
            # tells the observer whether this "law" has ever actually
            # been validated by a real occurrence, or is still an
            # untested proposal — "some true, some superstition the sim
            # never validated."
            entries.append({
                "type": "rule", "id": f"rule_{rule.id}", "kind": rule.trigger,
                "name": rule.name, "text": rule.description, "status": rule.status,
                "tick": rule.tick_created, "settlement": rule.origin_settlement_id, "lineage": None,
                "who": "the village",
                "hook_type": rule.hook_type, "fire_count": rule.fire_count,
                "secondary_trigger": rule.secondary_trigger or None,
                "validated": rule.fire_count > 0 or rule.secondary_last_fired_tick >= 0,
            })
        for entity in self.composite_entities.values():
            entries.append({
                "type": "composite_entity", "id": f"composite_{entity.id}", "kind": entity.base_kind,
                "name": entity.name, "text": entity.origin_story, "status": "named",
                "tick": entity.tick_created, "settlement": entity.origin_settlement_id,
                "lineage": {"concept_id": entity.concept_id, "building_id": entity.building_id},
                "who": "the village",
            })
        for variant in self.species_variants.values():
            entries.append({
                "type": "species_variant", "id": f"variant_{variant.id}", "kind": variant.trait,
                "name": variant.name, "text": variant.description, "status": "named",
                "tick": variant.tick_named, "settlement": None, "lineage": {"herd_id": variant.herd_id},
                "who": "the land itself",
            })
        for action in self.self_tuning_actions:
            if action.get("status") != "applied":
                continue
            entries.append({
                "type": "self_tuning", "id": f"self_tuning_{action['id']}", "kind": action["governor"],
                "name": action["governor"], "text": action["rationale"], "status": action["status"],
                "tick": action["tick"], "settlement": None, "lineage": None,
                "who": "Hearthmind itself",
            })
        entries.sort(key=lambda e: e["tick"], reverse=True)
        return entries[:limit]

    def emergence_log_recent(self, limit: int = 200) -> list[dict]:
        """A22 "The Emergence API" (docs/MASTERCHECKLIST-2026-07-22.md):
        newest-first view over `World.emergence_log`, same on-demand-
        endpoint shape as `knowledge_tree()`/`causal_threads_list()` —
        `GET /emergence` (interface/app.py) calls this via the
        broadcaster's provider hook. `emergence_log` itself stays
        append-order (oldest-first) internally, same as every other
        capped list in this codebase; only the read-side view reverses
        it for "what just happened" display convenience."""
        return list(reversed(self.emergence_log[-limit:]))

    def causal_threads_list(self, limit: int = 60) -> list[dict]:
        """Vision doc item 3.3 ("Legible causal threads") — newest-first
        view over `World.causal_threads`, the same on-demand-endpoint
        shape as `knowledge_tree()`. Each entry's `chain` is the
        ordered list of concrete grounding facts that led to the
        outcome named in `subject` — "click a feud, see the chain.\""""
        threads = sorted(self.causal_threads.values(), key=lambda t: t.tick, reverse=True)
        return [
            {"id": t.id, "subject": t.subject, "chain": list(t.chain), "tick": t.tick, "settlement_id": t.settlement_id}
            for t in threads[:limit]
        ]

    # --- (de)serialization --------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "config": {
                "seed": self.config.seed,
                "width": self.config.width,
                "height": self.config.height,
                "sim_minutes_per_tick": self.config.sim_minutes_per_tick,
                "minutes_per_day": self.config.minutes_per_day,
                "days_per_month": list(self.config.days_per_month),
                "month_names": list(self.config.month_names),
                "seasons_per_year": list(self.config.seasons_per_year),
                "month_to_season": list(self.config.month_to_season),
                "start_day_of_year": self.config.start_day_of_year,
                "initial_population": self.config.initial_population,
            },
            "clock": self.clock.to_dict(),
            "terrain": [[tile.to_dict() for tile in row] for row in self.terrain],
            "weather": self.weather.to_dict(),
            "weather_regions": {
                f"{rx}:{ry}": ws.to_dict() for (rx, ry), ws in self.weather_regions.items()
            },
            "population": self.population.to_dict(),
            "resources": self.resources.to_dict(),
            "minerals": self.minerals.to_dict(),
            "settlements": [stl.to_dict() for stl in self.settlements],
            "farms": self.farms.to_dict(),
            "wildlife": self.wildlife.to_dict(),
            "roads": self.roads.to_dict(),
            "climate": self.climate.to_dict(),
            "lakes": [lake.to_dict() for lake in self.lakes],
            "hydrology_field": self.hydrology_field.to_dict(),
            "disasters": self.disasters.to_dict(),
            "terrain_activity": {f"{x}:{y}": v for (x, y), v in self.terrain_activity.items()},
            "mining_scars": {f"{x}:{y}": round(v, 4) for (x, y), v in self.mining_scars.items()},
            "disaster_scars": {f"{x}:{y}": round(v, 4) for (x, y), v in self.disaster_scars.items()},
            "fallow_ticks": {f"{x}:{y}": v for (x, y), v in self.fallow_ticks.items()},
            "llm_calls_total": self.llm_calls_total,
            "llm_fallback_total": self.llm_fallback_total,
            "dialogue_total": self.dialogue_total,
            "rumor_total": self.rumor_total,
            "sim_summary_text": self.sim_summary_text,
            "sim_summary_tick": self.sim_summary_tick,
            # sim_summary_pending is deliberately NOT persisted — a
            # generation left in flight at shutdown never resolves after
            # restart, so it must load back as False, not stuck "true"
            # forever with no job to clear it.
            "chronicler_question": self.chronicler_question,
            "chronicler_answer": self.chronicler_answer,
            "chronicler_answer_tick": self.chronicler_answer_tick,
            # chronicler_pending: same not-persisted reasoning as
            # sim_summary_pending above.
            "away_digest_text": self.away_digest_text,
            "away_digest_tick": self.away_digest_tick,
            "away_digest_since_tick": self.away_digest_since_tick,
            "away_digest_highlights": list(self.away_digest_highlights),
            # away_digest_pending: same not-persisted reasoning as
            # sim_summary_pending above.
            "highlights": list(self.highlights),
            "emergence_log": list(self.emergence_log),
            "next_emergence_id": self.next_emergence_id,
            "fields": self.fields.to_dict(),
            "nature_pillar": self.nature_pillar.to_dict(),
            "village_pillar": self.village_pillar.to_dict(),
            "humans_pillar": self.humans_pillar.to_dict(),
            "innovation_pillar": self.innovation_pillar.to_dict(),
            "reflection_pillar": self.reflection_pillar.to_dict(),
            "observer_attention": {
                "agent_view_counts": {str(k): v for k, v in self.observer_attention.get("agent_view_counts", {}).items()},
                "last_agent_id": self.observer_attention.get("last_agent_id"),
                "last_seen_tick": self.observer_attention.get("last_seen_tick", -1),
            },
            "consciousness_grudge_ledger": self.consciousness_grudge_ledger,
            "invented_concepts": {str(k): v.to_dict() for k, v in self.invented_concepts.items()},
            "next_concept_id": self.next_concept_id,
            "trigger_rules": {str(k): v.to_dict() for k, v in self.trigger_rules.items()},
            "next_trigger_rule_id": self.next_trigger_rule_id,
            "composite_entities": {str(k): v.to_dict() for k, v in self.composite_entities.items()},
            "next_composite_entity_id": self.next_composite_entity_id,
            "species_variants": {str(k): v.to_dict() for k, v in self.species_variants.items()},
            "next_species_variant_id": self.next_species_variant_id,
            "causal_threads": {str(k): v.to_dict() for k, v in self.causal_threads.items()},
            "next_causal_thread_id": self.next_causal_thread_id,
            "nature_beliefs": list(self.nature_beliefs),
            "reflection_notebook": list(self.reflection_notebook),
            "musings": list(self.musings),
            "next_reflection_entry_id": self.next_reflection_entry_id,
            "wildfire_ignition_ticks": list(self.wildfire_ignition_ticks),
            "governor_tuning": dict(self.governor_tuning),
            "self_tuning_actions": list(self.self_tuning_actions),
            "advisory_proposals": list(self.advisory_proposals),
            "next_advisory_id": self.next_advisory_id,
            "consciousness_memory": list(self.consciousness_memory),
            "consciousness_personality": dict(self.consciousness_personality),
            "consciousness_objectives": list(self.consciousness_objectives),
            "consciousness_player_model": list(self.consciousness_player_model),
            "consciousness_intervention_log": list(self.consciousness_intervention_log),
            # consciousness_pending_temperament_nudge is deliberately NOT
            # persisted — same "in-flight, one-shot, must not double-apply
            # across a restart" reasoning as sim_summary_pending above.
        }

    @classmethod
    def from_dict(cls, data: dict, runtime_config: Config) -> "World":
        """Reconstruct a World from a snapshot dict. Creation-only fields
        (seed/width/height/calendar shape, including sim_minutes_per_tick)
        come from the snapshot itself, not from `runtime_config` — those
        were fixed when the world was created and affect calendar math.
        Runtime fields (tick_seconds, snapshot_every_ticks, db_path) come
        from `runtime_config`, since those only control pacing/storage and
        are safe to change between runs.

        Snapshots may be missing subsystems added by later releases (e.g.
        "population" pre-Milestone-2, "resources" pre-Phase-A, "settlement"
        pre-Phase-C, "farms" pre-Phase-D). Any missing subsystem is freshly
        backfilled and its name recorded in `migrated_subsystems` so the
        caller can log/persist the change once (see M2-3, generalized in
        A4)."""
        saved = data["config"]
        # Start from `runtime_config` and overlay only the creation-only
        # fields from the snapshot — previously this was built the other
        # way around (a fresh Config with a hand-picked list of runtime
        # fields copied over), which silently reset every runtime field
        # NOT on that list to its dataclass default on resume. The one
        # that actually bit: `phase_g_intensity` is read via
        # `world.config` by the engine's temperament/omen/belief jobs, so
        # the documented Phase G off-switch (0.0) only ever worked on a
        # brand-new world, never a resumed one. Replacing wholesale also
        # means a future runtime field can't reintroduce the same bug.
        config = dataclasses.replace(
            runtime_config,
            seed=saved["seed"],
            width=saved["width"],
            height=saved["height"],
            sim_minutes_per_tick=saved["sim_minutes_per_tick"],
            minutes_per_day=saved["minutes_per_day"],
            days_per_month=tuple(saved["days_per_month"]),
            month_names=tuple(saved["month_names"]),
            seasons_per_year=tuple(saved["seasons_per_year"]),
            month_to_season=tuple(saved["month_to_season"]),
            # Older snapshots predate the spring-start change and were
            # created with a January 1 tick 0 — default 0 so their
            # calendar history doesn't shift underfoot on load.
            start_day_of_year=saved.get("start_day_of_year", 0),
            initial_population=saved.get("initial_population", Config.initial_population),
        )
        clock = SimClock.from_dict(config, data["clock"])
        terrain = TerrainGrid.from_nested(
            [[Tile.from_dict(t) for t in row] for row in data["terrain"]]
        )
        weather = WeatherState.from_dict(data["weather"])
        weather_regions: dict[tuple[int, int], WeatherState] = {}
        for key, ws_data in data.get("weather_regions", {}).items():
            rx_str, ry_str = key.split(":")
            weather_regions[(int(rx_str), int(ry_str))] = WeatherState.from_dict(ws_data)

        migrated_subsystems: list[str] = []

        if "population" in data:
            population = Population.from_dict(data["population"])
        else:
            population = Population.spawn_initial(
                seed=config.seed, count=config.initial_population, terrain=terrain,
            )
            migrated_subsystems.append("population")

        if "resources" in data:
            resources = ResourceGrid.from_dict(data["resources"])
        else:
            resources = ResourceGrid.generate(seed=config.seed, terrain=terrain)
            migrated_subsystems.append("resources")

        if "minerals" in data:
            minerals = MineralGrid.from_dict(data["minerals"])
        else:
            # Legacy pre-§8 snapshot: no mineral deposits, same
            # creation-only stance the calendar shape already takes —
            # not regenerated retroactively onto an existing map.
            minerals = MineralGrid()
            migrated_subsystems.append("minerals")

        if "settlements" in data:
            settlements = [Settlement.from_dict(entry) for entry in data["settlements"]]
        elif "settlement" in data:
            # Pre-multi-settlement snapshot: the one settlement becomes
            # the founding entry (id 0 is Settlement.from_dict's default
            # for data without an "id" key).
            settlements = [Settlement.from_dict(data["settlement"])]
        else:
            settlements = [Settlement()]  # no retroactive guessing at pre-existing structures
            migrated_subsystems.append("settlement")

        if "farms" in data:
            farms = FarmGrid.from_dict(data["farms"])
        else:
            farms = FarmGrid()  # no retroactive guessing at pre-existing farmland
            migrated_subsystems.append("farms")

        if "wildlife" in data:
            wildlife = WildlifeGrid.from_dict(data["wildlife"])
        else:
            wildlife = WildlifeGrid.generate(seed=config.seed, terrain=terrain)
            migrated_subsystems.append("wildlife")

        if "roads" in data:
            roads = RoadNetwork.from_dict(data["roads"])
        else:
            roads = RoadNetwork()  # no retroactive guessing at pre-existing paths
            migrated_subsystems.append("roads")

        climate = ClimateState.from_dict(data["climate"]) if "climate" in data else ClimateState()

        if "lakes" in data:
            lakes = [LakeState.from_dict(entry) for entry in data["lakes"]]
        else:
            # Pre-hydrology-pass snapshot: carve rivers into the existing
            # terrain and identify lakes now, same one-time-backfill shape
            # as every other subsystem here — real geography added to a
            # world already in progress, not guessed at retroactively.
            generate_rivers(seed=config.seed, terrain=terrain)
            lakes = identify_lakes(terrain)
            migrated_subsystems.append("lakes")

        if "hydrology_field" in data:
            hydrology_field = HydrologyField.from_dict(data["hydrology_field"])
        else:
            # A11 (Stage IV step 15): silent backfill, not a narrated
            # migrated_subsystems entry — this is derived background
            # state (same treatment as _biome_counts_cache), not a
            # one-time genesis event a player would notice like rivers/
            # lakes being carved.
            hydrology_field = create_hydrology_field(terrain)

        disasters = DisasterState.from_dict(data["disasters"]) if "disasters" in data else DisasterState()

        terrain_activity: dict[tuple[int, int], float] = {}
        for key, value in data.get("terrain_activity", {}).items():
            x_str, y_str = key.split(":")
            terrain_activity[(int(x_str), int(y_str))] = value

        mining_scars: dict[tuple[int, int], float] = {}
        for key, value in data.get("mining_scars", {}).items():
            x_str, y_str = key.split(":")
            mining_scars[(int(x_str), int(y_str))] = value

        disaster_scars: dict[tuple[int, int], float] = {}
        for key, value in data.get("disaster_scars", {}).items():
            x_str, y_str = key.split(":")
            disaster_scars[(int(x_str), int(y_str))] = value

        fallow_ticks: dict[tuple[int, int], int] = {}
        for key, value in data.get("fallow_ticks", {}).items():
            x_str, y_str = key.split(":")
            fallow_ticks[(int(x_str), int(y_str))] = value

        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            weather_regions=weather_regions,
            population=population, resources=resources, settlements=settlements, farms=farms,
            wildlife=wildlife, roads=roads, climate=climate, lakes=lakes, disasters=disasters,
            minerals=minerals, hydrology_field=hydrology_field,
            terrain_activity=terrain_activity,
            mining_scars=mining_scars,
            disaster_scars=disaster_scars,
            fallow_ticks=fallow_ticks,
            llm_calls_total=data.get("llm_calls_total", 0),
            llm_fallback_total=data.get("llm_fallback_total", 0),
            dialogue_total=data.get("dialogue_total", 0),
            rumor_total=data.get("rumor_total", 0),
            sim_summary_text=data.get("sim_summary_text", ""),
            sim_summary_tick=data.get("sim_summary_tick", -1),
            chronicler_question=data.get("chronicler_question", ""),
            chronicler_answer=data.get("chronicler_answer", ""),
            chronicler_answer_tick=data.get("chronicler_answer_tick", -1),
            away_digest_text=data.get("away_digest_text", ""),
            away_digest_tick=data.get("away_digest_tick", -1),
            away_digest_since_tick=data.get("away_digest_since_tick", -1),
            away_digest_highlights=list(data.get("away_digest_highlights", [])),
            highlights=list(data.get("highlights", [])),
            emergence_log=list(data.get("emergence_log", [])),
            next_emergence_id=data.get("next_emergence_id", 1),
            fields=FieldGrid.from_dict(data.get("fields", {})),
            nature_pillar=(
                Pillar.from_dict(data["nature_pillar"]) if data.get("nature_pillar") else default_nature_pillar()
            ),
            village_pillar=(
                Pillar.from_dict(data["village_pillar"]) if data.get("village_pillar") else default_village_pillar()
            ),
            humans_pillar=(
                Pillar.from_dict(data["humans_pillar"]) if data.get("humans_pillar") else default_humans_pillar()
            ),
            innovation_pillar=(
                Pillar.from_dict(data["innovation_pillar"]) if data.get("innovation_pillar")
                else default_innovation_pillar()
            ),
            reflection_pillar=(
                Pillar.from_dict(data["reflection_pillar"]) if data.get("reflection_pillar")
                else default_reflection_pillar()
            ),
            observer_attention=(
                {
                    "agent_view_counts": {int(k): v for k, v in data["observer_attention"].get("agent_view_counts", {}).items()},
                    "last_agent_id": data["observer_attention"].get("last_agent_id"),
                    "last_seen_tick": data["observer_attention"].get("last_seen_tick", -1),
                }
                if data.get("observer_attention") else {}
            ),
            consciousness_grudge_ledger=data.get("consciousness_grudge_ledger", 0.0),
            consciousness_memory=list(data.get("consciousness_memory", [])),
            consciousness_personality=dict(data.get("consciousness_personality", {})),
            consciousness_objectives=list(data.get("consciousness_objectives", [])),
            consciousness_player_model=list(data.get("consciousness_player_model", [])),
            consciousness_intervention_log=list(data.get("consciousness_intervention_log", [])),
            invented_concepts={
                int(k): InventedConcept.from_dict(v) for k, v in data.get("invented_concepts", {}).items()
            },
            next_concept_id=data.get("next_concept_id", 1),
            trigger_rules={
                int(k): TriggerRule.from_dict(v) for k, v in data.get("trigger_rules", {}).items()
            },
            next_trigger_rule_id=data.get("next_trigger_rule_id", 1),
            composite_entities={
                int(k): CompositeEntity.from_dict(v) for k, v in data.get("composite_entities", {}).items()
            },
            next_composite_entity_id=data.get("next_composite_entity_id", 1),
            species_variants={
                int(k): SpeciesVariant.from_dict(v) for k, v in data.get("species_variants", {}).items()
            },
            next_species_variant_id=data.get("next_species_variant_id", 1),
            causal_threads={
                int(k): CausalThread.from_dict(v) for k, v in data.get("causal_threads", {}).items()
            },
            next_causal_thread_id=data.get("next_causal_thread_id", 1),
            nature_beliefs=list(data.get("nature_beliefs", [])),
            reflection_notebook=list(data.get("reflection_notebook", [])),
            musings=list(data.get("musings", [])),
            next_reflection_entry_id=data.get("next_reflection_entry_id", 1),
            wildfire_ignition_ticks=list(data.get("wildfire_ignition_ticks", [])),
            governor_tuning=dict(data.get("governor_tuning", {})),
            self_tuning_actions=list(data.get("self_tuning_actions", [])),
            advisory_proposals=list(data.get("advisory_proposals", [])),
            next_advisory_id=data.get("next_advisory_id", 1),
            migrated_subsystems=migrated_subsystems,
        )
