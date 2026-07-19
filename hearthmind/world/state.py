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
    maybe_reclaim,
    tick_climate,
)
from hearthmind.world.daylight import night_factor as compute_night_factor
from hearthmind.world.disasters import (
    DisasterState,
    tick_flood,
    tick_frost,
    tick_heatwave,
    tick_storm,
    tick_wildfire,
)
from hearthmind.world.hydrology import LakeState, generate_rivers, identify_lakes, tick_lakes
from hearthmind.world.weather import WeatherState, compute_weather
from hearthmind.world.wildlife import WildlifeGrid
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

HIGHLIGHTS_MAX_STORED = 30
"""Cap on `World.highlights` — a small, bounded log of self-flagged
emergent moments, not a growing archive (the full narrative record
already lives durably in the `events` table)."""

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
    terrain_activity: dict[tuple[int, int], float] = field(default_factory=dict)
    """Per-tile deforestation pressure (forest tiles only) — see
    world/terrain_evolution.py. Small and self-pruning (entries are
    deleted once heat decays to 0 or the tile changes biome), so it's
    fine to keep in memory/snapshot alongside everything else."""
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
    """§5 "While you were away" digest (docs/IDEAS-2026-07-EMERGENCE.md):
    on-demand, mirrors `sim_summary_*`/`chronicler_*` exactly.
    `away_digest_since_tick` is the tick the PREVIOUS digest was
    generated at (or -1, meaning "since world start") — each new digest
    request covers events after that tick, then `away_digest_tick`
    becomes the new boundary for the NEXT request, so repeated requests
    never re-cover the same ground. Persisted like sim_summary_* so a
    page refresh still shows the last digest and the boundary survives
    a restart."""
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
        weather = compute_weather(seed=config.seed, tick=0, month=clock.month_name.lower(), previous=None)
        resources = ResourceGrid.generate(seed=config.seed, terrain=terrain)
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
            wildlife=wildlife, roads=roads, lakes=lakes,
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
        self.resources.tick(season=self.clock.season)
        self.farms.tick(season=self.clock.season, terrain=self.terrain)
        wildlife_events = self.wildlife.tick(
            seed=self.config.seed, tick=self.clock.tick_count, terrain=self.terrain, resources=self.resources,
            temperament=self.settlement.temperament, season=self.clock.season,
        )
        settlement_events: list[tuple[str, str]] = []
        self.newly_named_settlement_ids = []
        for stl in self.settlements:
            settlement_events += stl.tick(weather=self.weather, season=self.clock.season)
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
        population_events = self.population.tick(
            seed=self.config.seed, tick=self.clock.tick_count,
            terrain=self.terrain, resources=self.resources,
            settlements=self.settlements, farms=self.farms, wildlife=self.wildlife, roads=self.roads,
            weather=self.weather, night_factor=night, heatwave_active=self.disasters.heatwave_active,
            month_end="month_end" in events, core_cast_target=self.config.llm_core_cast_size,
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
        events += tick_wildfire(
            self.disasters, self.terrain, self.weather, self.clock.season, self.settlement.temperament,
            self.settlements, "week_end" in calendar_events, fire_rng,
            heatwave_active=self.disasters.heatwave_active, farms=self.farms,
        )
        storm_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_storm")
        events += tick_storm(self.weather, self.settlements, storm_rng)
        frost_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "disaster_frost")
        events += tick_frost(self.disasters, self.weather, self.farms, frost_rng)
        if "month_end" in calendar_events and self.lakes:
            occupied_tiles = {(a.x, a.y) for a in self.population.agents}
            lake_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "lakes")
            events += tick_lakes(self.lakes, self.terrain, self.climate.drying, lake_rng, occupied_tiles)
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
        rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "terrain_activity")
        events = apply_local_activity(self.terrain, active_forest_tiles, self.terrain_activity, rng)

        if "week_end" in calendar_events:
            reclaim_rng = _namespaced_rng(self.config.seed, self.clock.tick_count, "terrain_reclaim")
            events += maybe_reclaim(
                self.terrain, self.terrain_activity, self.settlements, self.farms, occupied_tiles, reclaim_rng,
            )

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
            "settlement": self.settlement.summary(),
            "settlements": [
                {
                    "id": stl.id,
                    "name": stl.name,
                    "center": stl.center(),
                    "members": stl.living_member_count(self.population.agents),
                    "standing": sum(1 for b in stl.buildings if b.stage is BuildingStage.STANDING),
                    "era": stl.era,
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
            "away_digest": {
                "text": self.away_digest_text,
                "tick": self.away_digest_tick,
                "since_tick": self.away_digest_since_tick,
                "pending": self.away_digest_pending,
            },
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
            "population": self.population.to_dict(),
            "resources": self.resources.to_dict(),
            "settlements": [stl.to_dict() for stl in self.settlements],
            "farms": self.farms.to_dict(),
            "wildlife": self.wildlife.to_dict(),
            "roads": self.roads.to_dict(),
            "climate": self.climate.to_dict(),
            "lakes": [lake.to_dict() for lake in self.lakes],
            "disasters": self.disasters.to_dict(),
            "terrain_activity": {f"{x}:{y}": v for (x, y), v in self.terrain_activity.items()},
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
            # away_digest_pending: same not-persisted reasoning as
            # sim_summary_pending above.
            "highlights": list(self.highlights),
            "observer_attention": {
                "agent_view_counts": {str(k): v for k, v in self.observer_attention.get("agent_view_counts", {}).items()},
                "last_agent_id": self.observer_attention.get("last_agent_id"),
                "last_seen_tick": self.observer_attention.get("last_seen_tick", -1),
            },
            "consciousness_grudge_ledger": self.consciousness_grudge_ledger,
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

        disasters = DisasterState.from_dict(data["disasters"]) if "disasters" in data else DisasterState()

        terrain_activity: dict[tuple[int, int], float] = {}
        for key, value in data.get("terrain_activity", {}).items():
            x_str, y_str = key.split(":")
            terrain_activity[(int(x_str), int(y_str))] = value

        return cls(
            config=config, clock=clock, terrain=terrain, weather=weather,
            population=population, resources=resources, settlements=settlements, farms=farms,
            wildlife=wildlife, roads=roads, climate=climate, lakes=lakes, disasters=disasters,
            terrain_activity=terrain_activity,
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
            highlights=list(data.get("highlights", [])),
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
            migrated_subsystems=migrated_subsystems,
        )
