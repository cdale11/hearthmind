"""The population: the collection of agents living on a World's terrain.

Follows the same determinism discipline as terrain/weather (see
docs/DECISIONS.md, M1-2/M1-3): both initial placement and per-tick behavior
are derived from `(world_seed, tick)` via a namespaced RNG, never from
unseeded `random` calls, so a given seed always produces the same
population history.
"""
from __future__ import annotations

import itertools
import random
from collections import deque
from dataclasses import dataclass, field

from hearthmind.util import clamp, namespaced_rng

try:
    from hearthmind._native import TerrainMaterialIndex as _NativeTerrainMaterialIndex
except ImportError:
    _NativeTerrainMaterialIndex = None
"""Optional compiled fast path for `_nearest_material_tile` (v0.72.3,
see cpp/src/terrain_index.cpp, docs/DECISIONS.md "Native extension
port"). `None` when the extension wasn't built — `_nearest_material_
tile` falls back to an equivalent pure-Python scan in that case."""

try:
    from hearthmind._native import AgentPositionIndex as _NativeAgentPositionIndex
except ImportError:
    _NativeAgentPositionIndex = None
"""Optional compiled fast path for `_nearest_other_agent` (module 4,
see cpp/src/agent_position_index.cpp, docs/DECISIONS.md "Native
extension port"). Unlike the terrain/resource ports, this one scales
with population squared (SOCIALIZE has no distance cap — see D4), so
it's the highest-value remaining native-port candidate. `None` when
the extension wasn't built — falls back to the equivalent pure-Python
linear scan in that case."""

try:
    from hearthmind._native import NeedsConstants as _NativeNeedsConstants
    from hearthmind._native import update_needs as _native_update_needs
except ImportError:
    _NativeNeedsConstants = None
    _native_update_needs = None

try:
    from hearthmind._native import relationship_decay_step as _native_relationship_decay_step
    from hearthmind._native import relationship_gain_step as _native_relationship_gain_step
except ImportError:
    _native_relationship_decay_step = None
    _native_relationship_gain_step = None
"""Optional compiled fast path for the two scalar operations inside
`_update_relationships` (see cpp/src/relationship_step.cpp). The dict
iteration/`itertools.combinations` pairing/prune-on-reach-zero
bookkeeping all stay in Python — only the per-value decay/gain
arithmetic moves. `None` when the extension wasn't built."""

try:
    from hearthmind._native import predator_kill_chance as _native_predator_kill_chance
except ImportError:
    _native_predator_kill_chance = None
"""Optional compiled fast path for the pure-math kill-chance computation
inside `_maybe_predator_attack` (module 7, see cpp/src/predator_kill_
chance.cpp). Only the arithmetic moves — both `rng.random()` rolls stay
in Python, in the same order, so the namespaced-RNG stream is
untouched. `None` when the extension wasn't built."""
"""Optional compiled fast path for `_update_needs` (module 6, see
cpp/src/needs.cpp, docs/DECISIONS.md "Native extension port" — the
first module from the "full engine rewrite" track: this runs
unconditionally for every agent every tick, unlike the goal-gated
lookups in modules 1-5. `None` when the extension wasn't built — falls
back to the equivalent pure-Python branching in that case."""

from hearthmind.agents import agent_store
from hearthmind.agents.agent import (
    CRITICAL_HUNGER_THRESHOLD,
    MEMORY_REPETITION_DAMPING,
    MEMORY_REPETITION_OVERLAP_THRESHOLD,
    _overlap_tokens,
    seed_founder_genome,
    DEATHBED_SECRET_HEIR_CHANCE,
    DEATHBED_SECRET_RUMOR_CHANCE,
    DEATHBED_SECRET_RUMOR_LISTENER_COUNT,
    DEBT_PRUNE_THRESHOLD,
    DEVELOPMENT_GROWTH_PER_TICK,
    DEVELOPMENT_LABOR_WEIGHT,
    DEVELOPMENT_NUTRITION_MAX_FACTOR,
    DEVELOPMENT_NUTRITION_MIN_FACTOR,
    DEVELOPMENT_NUTRITION_WEIGHT,
    DIALOGUE_MISUNDERSTANDING_TRUST_PENALTY,
    DIALOGUE_SENTIMENT_DELTA,
    DIALOGUE_TOPICS_RING_MAX,
    ELDER_AGE_FRACTION,
    FERTILITY_REPRODUCTION_WEIGHT,
    EMOTION_ANGER,
    EMOTION_BIRTH_JOY_BUMP,
    EMOTION_DEATH_GRIEF_BUMP,
    EMOTION_DISASTER_FEAR_BUMP,
    EMOTION_DISPUTE_ANGER_BUMP,
    EMOTION_FEAR,
    EMOTION_FESTIVAL_JOY_BUMP,
    EMOTION_GRIEF,
    EMOTION_ILLNESS_FEAR_BUMP,
    EMOTION_JOY,
    EMOTION_NOTABLE_THRESHOLD,
    EMOTION_PREDATOR_FEAR_BUMP,
    EMOTION_RECONCILE_JOY_BUMP,
    EMOTION_STARVATION_FEAR_BUMP,
    EMOTION_STORM_FEAR_BUMP,
    ELDER_RECOVERY_MULTIPLIER,
    ENERGY_DRAIN_AWAKE,
    ENERGY_RECOVERY_RESTING,
    FORAGE_AMOUNT,
    FORAGE_HUNGER_RELIEF,
    FORAGE_HUNGER_THRESHOLD,
    FORAGE_INVENTORY_SKIM,
    GATHER_TOOLS_YIELD_BONUS,
    GENOME_MUTATION_CHANCE,
    GENOME_MUTATION_STDDEV,
    GENOME_TRAITS,
    GOSSIP_OPINION_CONTAGION,
    RUMOR_FITNESS_POLARIZE_SCALE,
    IMMUNE_ADAPT_RATE,
    IMMUNE_BASELINE,
    IMMUNE_ENERGY_WEIGHT,
    IMMUNE_HUNGER_WEIGHT,
    IMMUNE_MODULATION_MAX_FACTOR,
    IMMUNE_MODULATION_MIN_FACTOR,
    IMMUNE_MODULATION_SENSITIVITY,
    IMMUNE_STRENGTH_FLOOR,
    SICKNESS_IMMUNE_DRAIN_PER_TICK,
    INJURY_RECOVERY_ENERGY_WEIGHT,
    INJURY_RECOVERY_HUNGER_WEIGHT,
    INJURY_RECOVERY_RATE,
    INJURY_VULNERABILITY_MAX_FACTOR,
    INJURY_VULNERABILITY_WEIGHT,
    PREDATOR_ATTACK_INJURY,
    STRESS_ADAPT_RATE,
    STRESS_FEAR_WEIGHT,
    STRESS_FEUD_PULL,
    STRESS_GRIEF_WEIGHT,
    STRESS_HUNGER_CRISIS_PULL,
    STRESS_REPRODUCTION_PENALTY_WEIGHT,
    STRESS_SICKNESS_PULL,
    GOSSIP_OPINION_MAX_STEP,
    GRIEF_ENERGY_PENALTY,
    HUNGER_RATE,
    IMMUNITY_DURATION_TICKS,
    INHERITANCE_BELIEF_CHANCE,
    INHERITANCE_BELIEF_CONFIDENCE_FRACTION,
    INHERITANCE_LESSON_CHANCE,
    INSTITUTION_TEACHING_BONUS_MULTIPLIER,
    MATURITY_TICKS,
    MAX_AGENT_MEMORIES,
    MAX_LIFESPAN_TICKS,
    MEMORY_FADE_DECAY_PER_DAY,
    MEMORY_FADE_FLOOR,
    MEMORY_MAJOR_EVENT_DECAY_PER_DAY,
    MAX_CORE_MEMORIES,
    MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD,
    MEMORY_SALIENCE_BASELINE,
    MEMORY_SALIENCE_EMOTION_WEIGHT,
    ROUTINE_MEMORY_SALIENCE_MULT,
    WORKING_MEMORY_MAX,
    MIN_LIFESPAN_TICKS,
    MOURNING_DURATION_TICKS,
    MOURNING_GRIEF_EASE,
    MOVE_CHANCE,
    OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK,
    OUTBREAK_CROWDING_MULTIPLIER,
    OUTBREAK_DISEASE_PRESSURE_WEIGHT,
    OUTBREAK_FLOOR_SICK_FRACTION_CAP,
    OUTBREAK_MIN_CHANCE_PER_TICK,
    OUTBREAK_ROAD_CONTACT_MULTIPLIER,
    PERSONAL_FOOD_CAPACITY,
    POPULATION_CAP,
    dynamic_population_cap,
    REPRODUCTION_AFFINITY_THRESHOLD,
    REPRODUCTION_CHANCE_PER_TICK,
    RELATIONSHIP_DECAY_PER_TICK,
    RELATIONSHIP_GAIN_PER_TICK_COLOCATED,
    REPRODUCTION_SETTLEMENT_HUNGER_CEILING,
    REPRODUCTION_WELLFED_HUNGER,
    REST_THRESHOLD,
    RIVALRY_THRESHOLD,
    SICKNESS_DEATH_CHANCE_PER_TICK,
    SICKNESS_DURATION_TICKS,
    SICKNESS_ENERGY_DRAIN_MULTIPLIER,
    SICKNESS_HOSPITAL_KILL_CHANCE_REDUCTION,
    SICKNESS_HUNGER_RATE_MULTIPLIER,
    SICKNESS_TRANSMISSION_CHANCE_PER_TICK,
    SKILL_CONSTRUCTION,
    SKILL_CONSTRUCTION_SPEED_BONUS,
    SKILL_FARMING,
    SKILL_FARMING_YIELD_BONUS,
    SKILL_MEDICINE,
    SKILL_MEDICINE_PRACTICE_GAIN,
    SKILL_MEDICINE_YIELD_BONUS,
    SKILL_PRACTICE_GAIN,
    SKILL_TEACHING_CHANCE_PER_TICK,
    SKILL_TEACHING_GAIN,
    SKILL_TEACHING_MIN_GAP,
    SLEEP_DEBT_ADAPT_RATE,
    SLEEP_DEBT_IMMUNE_WEIGHT,
    STARVATION_HUNGER_THRESHOLD,
    STARVATION_TICKS_TO_DEATH,
    INHERITANCE_BIAS_THRESHOLD,
    INHERITANCE_BIAS_TRANSFER_FRACTION,
    INHERITANCE_SKILL_TRANSFER_FRACTION,
    TRADE_FOOD_AMOUNT,
    TRADE_HUNGER_RELIEF,
    TRADE_MEDICINE_AMOUNT,
    TRADE_MIN_RELATIONSHIP,
    TRADE_RELATIONSHIP_BOOST,
    TRADE_TOOLS_AMOUNT,
    MASTERY_THRESHOLD,
    TRAIT_AMBITION,
    TRAIT_AMBITION_FOUNDER_SELECTION_WEIGHT,
    TRAIT_AMBITION_FOUNDING_NUDGE,
    TRAIT_AMBITION_MASTERY_NUDGE,
    TRAIT_FEUD_SOCIABILITY_NUDGE,
    TRAIT_GRIEF_NUDGE,
    TRAIT_MEAN_REVERSION_AMBITION,
    TRAIT_MEAN_REVERSION_OPENNESS,
    TRAIT_OSTRACISM_SOCIABILITY_NUDGE,
    TRAIT_RECONCILE_NUDGE,
    TRAIT_RECOVERY_RESILIENCE_NUDGE,
    TRAIT_MEAN_REVERSION,
    TRAIT_OPENNESS,
    TRAIT_OPENNESS_CARAVAN_NUDGE,
    TRAIT_OPENNESS_MIGRANT_WELCOME_INFLUENCE,
    TRAIT_RESILIENCE,
    TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE,
    TRAIT_RESILIENCE_STARVATION_TOLERANCE_INFLUENCE,
    TRAIT_SOCIABILITY,
    TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE,
    TRAIT_SOCIABILITY_TRADE_THRESHOLD_SHIFT,
    TRAIT_SOCIAL_CONTACT_NUDGE,
    TRAIT_STEP_MAX,
    TRAIT_SUSTAINED_HUNGER_NUDGE,
    TRAIT_THEFT_VICTIM_SOCIABILITY_NUDGE,
    TRAIT_VIOLENCE_NUDGE,
    TRUST_DELTA,
    TRUST_SKEPTICISM_THRESHOLD,
    WAKE_THRESHOLD,
    WEDDING_DURATION_TICKS,
    WEDDING_JOY_BUMP,
    Agent,
    AgentGoal,
    AgentState,
    add_grievance,
    bump_emotion,
    clear_grievance,
    decay_debts,
    decay_emotions,
    dominant_emotion,
    push_secret,
)
from hearthmind.agents.names import _roman, generate_names
from hearthmind.llm.beliefs import MAX_PERSONAL_BELIEFS, push_lesson
from hearthmind.economy.farms import (
    FARM_TOOL_MATERIALS_COST,
    HARVEST_AMOUNT,
    HARVEST_HUNGER_RELIEF,
    PLANT_CHANCE_PER_TICK,
    FarmGrid,
    FarmStage,
)
from hearthmind.agents.occupations import (
    ALL_OCCUPATIONS,
    BANKER_INCOME_PER_TICK,
    BUILDER_WORK_BONUS,
    EXPLORATION_FINDINGS_MAX,
    EXPLORATION_VISION_RADIUS,
    FARMER_HARVEST_BONUS,
    FISHERMAN_FORAGE_BONUS,
    MAYOR_REPUTATION_NUDGE,
    OCCUPATION_BAKER,
    OCCUPATION_BANKER,
    OCCUPATION_BLACKSMITH,
    OCCUPATION_BUILDER,
    OCCUPATION_BUSINESSMAN,
    OCCUPATION_FARMER,
    OCCUPATION_FISHERMAN,
    OCCUPATION_MAYOR,
    OCCUPATION_PRIEST,
    OCCUPATION_SCRIBE,
    OCCUPATION_STATUS_BONUS,
    OCCUPATION_SURVEYOR,
    OCCUPATION_TEACHER,
    PRIEST_RITUAL_BOOST_MULTIPLIER,
    occupation_staff_weight,
)
from hearthmind.settlement.buildings import (
    BRIDGE_CHANCE_PER_TICK,
    BRIDGE_MATERIALS_COST_PER_SPAN_TILE,
    BRIDGE_MIN_MATERIALS_COST,
    CAMP_TOLERANCE,
    CARRYING_CAPACITY_COORDINATION_WEIGHT,
    CARRYING_CAPACITY_ECONOMY_WEIGHT,
    CARRYING_CAPACITY_ENVIRONMENT_WEIGHT,
    CARRYING_CAPACITY_HUNGER_COMFORT,
    CARRYING_CAPACITY_HUNGER_WEIGHT,
    CARRYING_CAPACITY_INFRASTRUCTURE_WEIGHT,
    CARRYING_CAPACITY_KNOWLEDGE_WEIGHT,
    CARRYING_CAPACITY_POWER_PLANT_BONUS,
    CARRYING_CAPACITY_LABOR_WEIGHT,
    CARRYING_CAPACITY_MAX_MULTIPLIER,
    CARRYING_CAPACITY_MIN_MULTIPLIER,
    CARRYING_CAPACITY_ROADS_PER_CAPITA_SATURATION,
    CARRYING_CAPACITY_SECURITY_WEIGHT,
    CONSTRUCTION_MATERIALS_MULTIPLIER,
    CONSTRUCTION_WORK_PER_TICK,
    CROWDING_ENERGY_MULTIPLIER,
    CURRENCY_CAPACITY,
    CURRENCY_EMERGENCY_HUNGER_RELIEF,
    CURRENCY_EMERGENCY_RATION_COST,
    CURRENCY_PER_OVERFLOW_UNIT,
    EDUCATION_CAPACITY,
    ERA_UNLOCKS_AUTOMOBILE,
    INVENTION_REDISCOVERY_CHANCE,
    ERA_UNLOCKS_MOUNTAIN_BUILDING,
    DOCK_INCOME_PER_TICK,
    FORGE_INCOME_PER_TICK,
    OIL_RIG_INCOME_PER_TICK,
    FACTORY_INCOME_PER_TICK,
    FESTIVAL_RELATIONSHIP_BOOST,
    GRANARY_CAPACITY,
    GRANARY_DEPOSIT_PER_TICK,
    GRANARY_HUNGER_RELIEF,
    GRANARY_WELLFED_HUNGER_THRESHOLD,
    GRANARY_WITHDRAW_AMOUNT,
    HATCHERY_CAPACITY,
    HATCHERY_PASSIVE_YIELD_PER_TICK,
    HATCHERY_TENDED_YIELD_PER_TICK,
    HOSPITAL_CRAFT_MATERIALS_COST_PER_TICK,
    HOSPITAL_CRAFT_MEDICINE_PER_TICK,
    HOSPITAL_KILL_CHANCE_REDUCTION,
    HOSPITAL_REST_RECOVERY_MULTIPLIER,
    HUT_CAPACITY,
    INSTITUTION_LIST_MAX_STORED,
    IRON_TOOL_BONUS_PER_TICK,
    IRON_TOOL_COST_PER_TICK,
    MEDICINE_CAPACITY,
    MEDICINE_CONSUMPTION_PER_TICK,
    MEDICINE_DEATH_CHANCE_REDUCTION,
    MATERIALS_CAPACITY,
    MINERAL_CAPACITY,
    MINERAL_CURRENCY_VALUE,
    MINERAL_GATHER_PER_TICK,
    POWER_GRID_INDUSTRY_MULTIPLIER,
    MATERIALS_COST_BY_KIND,
    MATERIALS_GATHER_PER_TICK,
    MATERIALS_PER_CONSTRUCTION_TICK,
    MAX_WORKERS,
    PASTURE_CAPACITY,
    PASTURE_PASSIVE_YIELD_PER_TICK,
    PASTURE_TENDED_YIELD_PER_TICK,
    REPAIR_THRESHOLD,
    REPAIR_WORK_PER_TICK,
    SCHOOL_EDUCATION_PER_TICK,
    SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER,
    SETTLE_CHANCE_OFF_PRIORITY_MULTIPLIER,
    SETTLE_CHANCE_PER_TICK,
    SETTLE_CHANCE_RESOURCE_ADJACENCY_MULTIPLIER,
    SETTLE_RESOURCE_SEARCH_RADIUS,
    SHELTER_NEGATES_WEATHER,
    SHRINE_FESTIVAL_BOOST_MULTIPLIER,
    TECH_BONUS_PER_LEVEL,
    TEMPERAMENT_KILL_CHANCE_INFLUENCE,
    TOOLS_CAPACITY,
    WORKSHOP_CRAFT_MATERIALS_COST_PER_TICK,
    WORKSHOP_CRAFT_TOOLS_PER_TICK,
    UNIVERSITY_EDUCATION_MULTIPLIER,
    UNIVERSITY_MATERIALS_COST,
    UNIVERSITY_TECH_REQUIREMENT,
    URBAN_GROWTH_ROAD_ADJACENCY_MULTIPLIER,
    WORKSHOP_INCOME_PER_TICK,
    BuildingKind,
    BuildingStage,
    Settlement,
    choose_building_kind,
    culture_effect_multiplier,
    hut_capacity_multiplier,
)
from hearthmind.settlement.institutions import (
    FAMILY_FEUD_AFFINITY_PENALTY,
    Institution,
    InstitutionKind,
)
from hearthmind.settlement.district import (
    DISTRICT_INDIVIDUAL_CAP,
    DISTRICT_MATERIALS_PER_CAPITA_PER_DAY,
    DISTRICT_MAX_POPULATION,
    District,
    fallback_district_name,
    tick_district,
)
from hearthmind.settlement.vehicles import (
    AUTOMOBILE_MATERIALS_COST,
    BOAT_MATERIALS_COST,
    CART_BONUS_CAP,
    CART_HAUL_BONUS_PER_CART,
    CART_MATERIALS_COST,
    CART_USE_DECAY,
    MOUNT_MATERIALS_COST,
    PERSONAL_VEHICLE_KINDS,
    PERSONAL_VEHICLE_SPEED_MULTIPLIER,
    PERSONAL_VEHICLE_USE_DECAY,
    RAFT_BONUS_CAP,
    RAFT_FISH_BONUS_PER_RAFT,
    RAFT_MATERIALS_COST,
    RAFT_USE_DECAY,
    VEHICLE_CHANCE_PER_TICK,
    VEHICLE_CONSTRUCTION_WORK_PER_TICK,
    VEHICLE_MAX_WORKERS,
    VEHICLE_REPAIR_THRESHOLD,
    VEHICLE_REPAIR_WORK_PER_TICK,
    Vehicle,
    VehicleKind,
    VehicleStage,
)
from hearthmind.world.minerals import MineralGrid
from hearthmind.world.resources import (
    FISH_HUNGER_RELIEF_MULTIPLIER,
    ORE_BIOMES,
    ResourceGrid,
    ResourceKind,
    is_adjacent_to_water,
)
from hearthmind.world.roads import (
    ROAD_PAVED_SPEED_MULTIPLIER,
    ROAD_SPEED_MULTIPLIER,
    RoadNetwork,
    road_condition_multiplier,
)
from hearthmind.world.terrain import Biome, Tile
from hearthmind.world.terrain_evolution import (
    DISASTER_SCAR_SITE_PENALTY_SCALE,
    MINING_SCAR_SITE_PENALTY_SCALE,
    RITUAL_ACTIVITY_BOOST_SCALE,
    ROAD_SCAR_SITE_BONUS_SCALE,
    RUIN_SITE_BONUS_SCALE,
    apply_ritual_activity,
    apply_road_scar,
)
from hearthmind.world.fields import FieldGrid
from hearthmind.world.graph_algorithms import bfs_distances, build_relationship_graph
from hearthmind.world.layout_grammar import layout_site_bonus
from hearthmind.world.materials import effective_material_name, material_repair_factor
from hearthmind.world.spatial_memory import location_character_from_dicts
from hearthmind.world.weather import WeatherState
from hearthmind.world.wildlife import (
    HUNT_YIELD_PER_ANIMAL,
    PREDATOR_ATTACK_CHANCE,
    PREDATOR_ATTACK_ENERGY_DRAIN,
    PREDATOR_ATTACK_HUNGER_INCREASE,
    PREDATOR_KILL_CHANCE_ON_ATTACK,
    WILDLIFE_SEARCH_RADIUS,
    Species,
    WildlifeGrid,
)

WALKABLE_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST, Biome.HILLS, Biome.BEACH, Biome.QUARRY})
"""QUARRY (M2/M8, world/terrain_evolution.py's `maybe_form_quarries`)
stays walkable/re-workable — a real quarry is worked ground, not an
impassable pit, same as HILLS was before conversion."""
MOUNTAIN_WALKABLE_BIOMES = WALKABLE_BIOMES | frozenset({Biome.MOUNTAIN})
WATER_CROSSABLE_BIOMES = frozenset({Biome.SHALLOW_WATER, Biome.DEEP_WATER, Biome.RIVER})
"""Every open-water biome a BOAT-mounted agent can cross (v0.87.42) —
see `_is_walkable`'s `water_capable` parameter."""
"""Once a settlement's era reaches ERA_UNLOCKS_MOUNTAIN_BUILDING, its
own pathing (_dispatch_movement's travel/goal steps, and build-site
staking) treats MOUNTAIN as walkable too — SNOWCAP stays a hard barrier
at every era, mountains only become passable, not the snowline above
them. See _is_walkable's mountain_unlocked parameter."""
MATERIAL_BIOMES = frozenset({Biome.FOREST, Biome.HILLS})
"""Where GATHER-goal agents can collect wood/stone — see D8."""

_NEIGHBOR_OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))

FORAGE_SEARCH_RADIUS = 6
"""How far a FORAGE-goal agent can "see" a resource node to move toward,
in Chebyshev distance — beyond this, they fall back to the default wander
behavior. Deliberately local: wild food awareness is plausible only
nearby. SOCIALIZE has no equivalent cap — see docs/DECISIONS.md, D4."""

GATHER_SEARCH_RADIUS = 6
"""Same rationale as FORAGE_SEARCH_RADIUS — local, plausible awareness of
nearby forest/hills, not map-wide. See D8."""

RUMOR_BFS_BASELINE_WEIGHT = 0.15
"""A16 "information-propagation-as-graph-algorithm" (docs/ROADMAP-
2026-07-REMAINING.md): the floor weight `Population.spread_rumor`
gives a listener candidate with no real social path (via `graph_
algorithms.bfs_distances`) to the point of contact at all — matching
`memetics.PROPAGATION_BASELINE_WEIGHT`'s same "news travels beyond a
closed social circle" discipline, so a stranger can still occasionally
hear it, just far less often than someone genuinely socially close."""

SOCIALIZE_RELATIONSHIP_RADIUS = 12
SOCIALIZE_DISTANCE_PENALTY = 0.02
"""Audit follow-up (v1.3.38 cognition-architecture audit, "relationship-
weighted SOCIALIZE targeting" — the highest-call-volume movement
decision, previously pure nearest-neighbor). An agent seeking company
now prefers whoever they genuinely like (`Agent.relationships` > 0)
within `_RADIUS` tiles, breaking ties by distance
(`score = relationship - distance * _DISTANCE_PENALTY`); with no liked
candidate in range, behavior is unchanged — plain nearest-neighbor.
Only applied when `agent.relationships` is non-empty (most agents,
most of the time, have at least one real bond by then) — see
`_nearest_liked_agent`'s own docstring for why this bypasses the
native fast-path index (no weighting support there, same reasoning as
the pre-existing `ostracized_ids` exclusion-set case)."""

MOVEMENT_STUCK_TICKS_THRESHOLD = 4
"""Consecutive ticks `_step_toward`'s greedy 2-candidate step can fail
toward a live goal-directed target (FORAGE/SOCIALIZE/GATHER/WANDER)
before movement escalates to one bounded `_bfs_step` call. Root cause
this fixes: greedy stepping only ever tries the two cardinal directions
that reduce Manhattan distance, so a concave water/mountain pocket
between an agent and a visible-but-blocked target made it fail forever
— every tick, indefinitely, for as long as that goal held — silently
degrading to the pure random walk instead of ever arriving, even though
the target was genuinely reachable by a longer route. `travel_target`
journeys already had this BFS fallback (fires the same tick the greedy
step first fails, since journeys are rare); routine goal-directed
movement runs for every awake agent every tick, so it waits a few
tries first (an obstacle-free path usually resolves on its own via the
next tick's fresh target/position) before paying the heavier BFS cost.
See docs/DECISIONS.md, "movement: stuck-agent BFS escape" pass."""

MOVEMENT_STUCK_BFS_NODE_CAP = 600
"""Node-expansion cap for the stuck-agent BFS escape — smaller than
`_bfs_step`'s own 4096 default (used for rare travel_target journeys)
since this can fire for many ordinary agents, not just one journeying
party at a time; bounds the worst-case per-agent cost of an unreachable
target to one modest flood-fill every MOVEMENT_STUCK_TICKS_THRESHOLD
ticks rather than every tick."""

WEATHER_HARSH_PRECIPITATION = 0.4
WEATHER_HARSH_WIND = 0.5
"""Same "harsh weather" definition as settlement/buildings.py's
DECAY_WEATHER_MULTIPLIER trigger — kept as separate constants here
(rather than importing from buildings.py) since agent need-drain and
building decay are conceptually independent effects that happen to share
a threshold, not the same mechanic."""

WEATHER_HARSH_HUNGER_MULTIPLIER = 1.3
WEATHER_HARSH_ENERGY_DRAIN_MULTIPLIER = 1.4
"""Awake agents in harsh weather (heavy rain/snow/high wind) burn energy
and get hungry faster — "weather affects people," not just buildings.
Applied only to AWAKE agents: resting is treated as sheltering/sleeping,
abstracted as weather-proof. See docs/DECISIONS.md, scarcity pass."""

NIGHT_ENERGY_DRAIN_EXTRA = 0.3
"""At full night (night_factor=1.0), an AWAKE agent's energy drain is
multiplied by (1 + this) — same order of magnitude as the weather-harsh
multiplier above, so staying up all night costs about as much as working
through a storm. Scales linearly with night_factor, so dawn/dusk cost
less than deep night. See docs/DECISIONS.md, "daylight affects agent
behavior.\""""

NIGHT_REST_THRESHOLD_BOOST = 0.15
"""At full night, the energy level that triggers involuntary RESTING
(REST_THRESHOLD in agent.py) is raised by this much — agents settle in
for the night sooner rather than only collapsing from exhaustion, same
as a real day/night routine."""

NIGHT_REST_RECOVERY_BONUS = 0.15
"""At full night, RESTING energy recovery is multiplied by
(1 + this) — sleeping through the dark hours is more restful than a
daytime nap."""

FOUNDING_SITE_RADIUS = 5
FOUNDING_CLUSTER_RADIUS = 3
"""Founding-site selection (see Population.spawn_initial): the anchor
is the walkable tile with the most wild FOOD nodes within SITE_RADIUS
(Chebyshev), and all founders start within CLUSTER_RADIUS of it.
SITE_RADIUS matches FORAGE_SEARCH_RADIUS-ish local awareness;
CLUSTER_RADIUS keeps the group close enough to meet (relationships,
construction pairs) within days instead of weeks. Together with the
spring calendar start (Config.start_day_of_year) this is the fix for
the measured early starvation funnel — believable causality (founders
chose a good spot in spring), not a stat buff."""

COUNCIL_FORMATION_POPULATION_THRESHOLD = 20
"""H3 extension (docs/ROADMAP.md "Phase H"): a named settlement forms
its first COUNCIL institution the first tick its living population
reaches this size — a second, larger-scale institution kind alongside
FAMILY, still fully automatic (no agent goal/LLM decision to found
one), same "cheapest, most unambiguous moment" discipline family
formation already uses. Chosen well above `POPULATION_CRITICAL_
THRESHOLD` and comfortably reachable by a healthy settlement, so
council formation reads as "the village has grown large enough to need
one," not an arbitrary tripwire."""

COUNCIL_SIZE = 5
"""Council membership is fixed at formation — the this-many oldest
living agents at that moment (age_ticks fraction of their own
max_age_ticks, eldest first), never refreshed afterward. Matches how
FAMILY institutions already work (member_agent_ids only ever grows,
never gets swapped out) rather than introducing a different, dynamic-
membership shape for the second kind. v0.87.15 ("emergent leadership")
partly reverses "never gets swapped out": a living member's seat CAN
now be contested and displaced (see `_maybe_refresh_council`'s
displacement check) — membership still only ever grows in
`Institution.member_agent_ids` itself (an institution outlives its
members by design, unchanged), it's the council's SEAT roster read out
of that pool that can now shift."""

COUNCIL_DISPLACEMENT_MARGIN = 1.5
"""v0.87.15, "emergent leadership" (docs/IDEAS-2026-07-EMERGENCE.md
§7): a non-member challenger must out-`_prominence` the weakest sitting
member by this multiple before a seat changes hands — well above 1.0
so ordinary week-to-week prominence noise (age ticking up, a routine
trade) never triggers a displacement; this is meant to fire only for a
genuinely standout challenger (a young founder with real social/skill
standing), not to churn the roster."""

COUNCIL_DISPLACEMENT_CHECK_INTERVAL_TICKS = 2880
"""How often `_maybe_refresh_council` evaluates a possible seat
contest — roughly monthly at the default tick rate (not tied to the
calendar's actual month boundary; a cheap tick-modulo gate is enough
for "not every single tick," which is all this needs). Seat-FILLING
(an open seat from a death) stays checked every tick, since that's
already cheap and time-sensitive; only the CONTEST check (an already-
full council) is throttled, since sorting the whole non-member pool by
prominence every tick would be wasted work for a signal that moves
slowly."""

GUILD_SKILL_MASTERY_THRESHOLD = 0.6
"""A living agent counts as having "mastered" a trade (SKILL_FARMING/
SKILL_CONSTRUCTION, both 0..1) once their skill level reaches this —
well above SKILL_TEACHING_MIN_GAP (0.15), so a guild forms around
genuine expertise, not merely-competent practitioners. See
_maybe_form_guild/_maybe_refresh_guild."""

GUILD_FORMATION_MASTER_COUNT = 3
"""A GUILD institution forms for a given skill the first tick at least
this many living agents have mastered it — a real critical mass of
expertise, not a single skilled individual declaring a guild of one.
Same "cheapest, most unambiguous moment" formation discipline as
FAMILY/COUNCIL."""

GUILD_TEACHING_BONUS_MULTIPLIER = 1.6
"""_maybe_teach_skills' per-trade bonus for a teacher/learner pair who
share a living GUILD for the specific skill being taught — larger than
INSTITUTION_TEACHING_BONUS_MULTIPLIER (1.4, FAMILY/COUNCIL's
trade-agnostic bonus) since this is expertise-specific: a builders'
guild member teaches construction better than a family member who
merely happens to share a house. Stacks multiplicatively with the
trade-agnostic bonus when a pair happens to share both kinds of
institution."""

FACTION_TRUST_EDGE_THRESHOLD = 0.4
"""Two living agents count as a "faction edge" (`_detect_faction_
candidate`) only when each trusts the other at or above this on the
-1..1 scale — mutual, not one-sided; a faction is chosen loyalty, not
one agent's unreciprocated opinion of another."""

FACTION_MIN_SIZE = 4
"""A trust-graph cluster must reach this many members before it's even
a candidate — same "real critical mass, not a clique of two"
discipline as GUILD_FORMATION_MASTER_COUNT."""

FACTION_MIN_COHESION = 0.3
"""The candidate cluster's mean mutual-trust value (across its own
internal edges) must clear this before formation — a large but only
loosely-connected cluster (e.g. one long trust chain) shouldn't read as
a cohesive faction just because it's big."""

FACTION_MAX_STORED = 20
"""Cap on stored FACTION institutions per settlement (`_prune_extinct_
institutions`) — deliberately much smaller than FAMILY's 300: a
settlement realistically has a handful of live factions at once, not
hundreds, so this stays a curated, meaningful list rather than
approaching FAMILY's scale."""

DEBT_PER_TRADE_FRACTION = 0.5
"""Phase L "Economy depth" (docs/VISION-2026-07.md, "Society & Power"):
a barter recipient owes the giver this fraction of the traded amount,
in the same abstract units as the good itself (food/tools/medicine
share one debt ledger — a village doesn't keep separate books per
good, just a running sense of "I owe them"). See `_record_debt`."""

DEBT_DISPUTE_CONTEXT_THRESHOLD = 1.0
"""An outstanding one-sided debt at or above this is worth mentioning
in dispute framing (`llm/dispute.py`) — below it, the amount is too
small to plausibly be what a feud is really about."""

POPULATION_CRITICAL_THRESHOLD = 4
"""Below this many living inhabitants (but above 0 — total extinction is
a legitimate, permanent settlement-collapse outcome, see
_maybe_welcome_migrant, not a bug to route around), a population is one
incompatible or unlucky pair away from a demographic dead end even
though people remain: reproduction needs two colocated, mature, healthy
agents whose mutual affinity has crossed REPRODUCTION_AFFINITY_THRESHOLD
— with only 1-3 survivors left, there may be nobody eligible to pair
with at all."""

MIGRANT_BELOW_CORE_CAST_CHANCE_MULT = 0.25
"""Applied to `MIGRANT_CHECK_CHANCE_PER_TICK` when the population is
below the LLM core cast target (`Config.llm_core_cast_size`) but still
above `POPULATION_CRITICAL_THRESHOLD` — a gentler trickle than the
near-extinction case below, since the settlement isn't in acute danger
of a demographic dead end, just short of the roster the core-cast
cognition/dialogue system was sized for. Explicit user request: a town
whose population has fallen below its LLM-authored cast size should be
able to draw newcomers from outside to rebuild toward it, not only once
down to a handful of survivors."""

MIGRANT_CHECK_CHANCE_PER_TICK = 0.003
MIGRANT_DENSITY_DAMPENING = 0.3
"""A20 "Multi-scale aggregation," first slice (roadmap Stage IV step
29, docs/MASTERCHECKLIST-2026-07-22.md): a second real consumer of the
`World.fields` `population_density` region field (A1), beyond its
original sole consumer (`_maybe_favor_uncrowded_fission_site`) — the
same region-level computed summary now also dampens migrant draw at a
settlement sitting in an already-crowded region (up to 30% at the
region's peak density), plausible on its own terms ("word travels that
this place is already full") and a genuine second independent system
reading the same field, the gap the roadmap item's own definition
flags ("region-level state ... instead of a separately-simulated
object" — one field, one consumer, was a thin first slice)."""
MIGRANT_SCARCITY_DAMPENING = 0.3
"""A4 "Continuous systems vs. scripted events" (Tier 1, docs/ROADMAP-
2026-07-REMAINING.md): a real consumer of `World.fields`'s `scarcity`
region field — a settlement sitting in a visibly struggling region
(low granary/materials fill, `settlement.buildings.compute_resource_
fill`) draws newcomers less readily, same bounded shape and same
magnitude `MIGRANT_DENSITY_DAMPENING` already established for
population density (up to 30% dampening at maximum regional
scarcity). "Word travels that a place is struggling" is the same
plausible framing that field's own docstring uses."""
MIGRANT_OWNERSHIP_PULL = 0.3
"""A1 (Tier 1 item 3): a real consumer of `World.fields`'s new
`ownership` region field — the first POSITIVE pull among the three
region-field terms here (density/scarcity both only ever dampen).
A region with deep inheritance history (`World.ownership_history`,
A19) reads as visibly settled, not a frontier — up to 30% MORE likely
to draw a migrant at the region's peak ownership reading, the
plausible inverse framing of scarcity's "word travels that a place is
struggling": word also travels that a place has real roots. Same
magnitude as the two dampening terms, deliberately not larger — this
is a modest pull toward stability, not the dominant factor in whether
a migrant arrives at all (that's still the population-floor gate
above)."""
MIGRANT_HEAT_DAMPENING = 0.25
"""A1 (Tier 1 item 3): a real consumer of `World.fields`'s `heat`
region field — a settlement in a genuinely scorching region draws
newcomers a bit less readily (up to 25% dampening at peak heat),
same bounded "never a hard block" shape as `MIGRANT_SCARCITY_
DAMPENING`. Smaller magnitude than the other terms here — heat is a
real but secondary consideration next to whether a place is crowded,
struggling, or established."""
MIGRANT_CULTURAL_PULL = 0.25
"""A1 (Tier 1): a real consumer of `World.fields`'s `cultural_
influence` region field — a region where invented concepts have real
living adopters draws newcomers more readily (up to 25% more at peak),
a third POSITIVE region-field pull alongside `MIGRANT_OWNERSHIP_PULL`
(density/scarcity/heat all only ever dampen) — "word travels that a
place has real ideas," the same plausible-word-of-mouth framing every
other region-field migrant term here already uses."""
MIGRANT_BEAUTY_PULL = 0.2
"""A1 (Tier 1): a real consumer of `World.fields`'s `beauty` region
field — the one field sourced from genuinely NEW per-agent subjective
votes (`world/aesthetics.py`), not a re-read of already-real state. A
region the settlement's own people have rated as lovely draws newcomers
somewhat more readily (up to 20% more at peak), a fourth POSITIVE
region-field pull alongside `MIGRANT_OWNERSHIP_PULL`/`MIGRANT_
CULTURAL_PULL` — "word travels that a place is beautiful.\""""
MIGRANT_WILDLIFE_PULL = 0.2
"""A10 "Ecology / food webs," field-substrate fold-in: a real consumer
of `World.fields`'s `wildlife` region field (sourced from live GRAZER-
herd presence — see `FieldGrid.step_wildlife`) — a region with real
game draws newcomers somewhat more readily (up to 20% more at peak),
a fifth POSITIVE region-field pull alongside `MIGRANT_OWNERSHIP_PULL`/
`MIGRANT_CULTURAL_PULL`/`MIGRANT_BEAUTY_PULL` — "word travels that a
place has good hunting." The deliberate positive counterpart to
`scent`'s existing negative pull on `_choose_fission_site` (predator
danger); this is the first migrant-welcome term sourced from wildlife
at all, closing the loop the other direction from this fold-in's
first slice (wildlife itself avoiding busy `population_density`)."""
MIGRANT_TEMPERAMENT_INFLUENCE = 0.2
"""Fractional nudge to migrant-arrival chance from `Settlement.
temperament` — a village that's lately had a run of good fortune draws
a newcomer somewhat more readily (a strongly warm village up to ~1.2x
baseline), same small-magnitude treatment as TEMPERAMENT_INVENTION_
INFLUENCE/TEMPERAMENT_KILL_CHANCE_INFLUENCE. Deliberately one-sided —
only warm temperament helps; a cold spell doesn't actively repel
migrants, since MIGRANT_CHECK_CHANCE_PER_TICK is already the sole
recovery path out of a population crash and shouldn't be actively
suppressed by the same ill fortune that likely caused the crash."""
"""Same rare-per-tick-roll shape as wildlife's
WILDLIFE_RECOLONIZE_CHECK_CHANCE — a lone newcomer, drawn to a
dwindling settlement, occasionally arrives already mature (so they're
immediately reproduction-eligible rather than waiting out
MATURITY_TICKS) when the population is critically low. See
docs/DECISIONS.md, "population recovery" pass."""

RECORD_MIN_MEMORIES = 4
"""Written artifacts (v0.64.0 audit-backlog item): a dying agent leaves
a letter/record behind only when they had at least this many memories —
a life with enough in it to be worth writing down. Half the memory cap
(MAX_AGENT_MEMORIES=8), so a mid-length life qualifies but a newborn or
a barely-arrived migrant doesn't."""

DISPUTE_RELATIONSHIP_THRESHOLD = -0.6
"""A pair whose mutual relationship has soured to or below this (well
past RIVALRY_THRESHOLD's -0.4) is eligible for a rare LLM-mediated
dispute-resolution moment — see Population.due_for_dispute,
SimulationEngine._maybe_schedule_dispute. Deep enough that ordinary
tense patches never trigger it; a feud has to have genuinely festered."""

DISPUTE_COOLDOWN_TICKS = 1000
"""Minimum ticks between two dispute-resolution moments for the same
pair (~10 sim-days at default pacing) — a resolution is still a rare,
notable event, not a recurring mechanic; an outcome needs time to
settle (or fester again) before the question can reopen. Lowered from
3000 ("Definitive checklist" Tier 2.2, 2026-07-21): the audit measured
zero dispute firings across a 3685-tick run at the old value — combined
with `due_for_dispute`'s prior mutual-souring requirement (see below),
the gate was tight enough that the interpersonal system with the
richest mechanical teeth (feud/reconcile/council_ruling/ostracism,
Population.apply_dispute) almost never actually fired. Still gated by
`_maybe_schedule_dispute`'s existing backpressure check, so this can't
add unbounded LLM volume — it only widens the window a genuinely
festered pair becomes eligible in."""

DISPUTE_RECONCILE_RELATIONSHIP = 0.1
DISPUTE_TRUCE_RELATIONSHIP = -0.1
DISPUTE_FEUD_DEEPEN = -0.2

DISASTER_SURVIVOR_BOND_BUMP = 0.15
"""Phase 1.D (Nature->Human): agents caught on the same flooded/wildfire
tile this tick get a one-time relationship bump toward each other — an
honest "survived it together" proxy. Sized above RELATIONSHIP_GAIN_PER_
TICK_COLOCATED (routine, per-tick, tiny) but below a full reconciliation
— a single sharp shared-hardship moment, not a standing companionship."""

DISASTER_HELPER_RADIUS = 3
DISASTER_HELPER_BOND_BUMP = 0.08
"""Phase 1.D follow-up: the honest half of the vision doc's helper/
non-helper framing. A nearby AWAKE agent who visibly moved closer to a
disaster tile this same tick (`_mark_disaster_survivors` compares
start-of-tick vs. post-movement position — a real, observed action, not
an inferred one) counts as a helper and gets a smaller bond with the
survivors there. Deliberately still NOT implementing a grievance against
agents who were merely nearby and did nothing — the engine has no way
to know a bystander was even aware of the disaster, so "could have
helped" would be asserted, not observed; that stays a future follow-up
pending a real disaster-awareness/response mechanic."""

THEFT_HUNGER_THRESHOLD = 0.65
"""Item 8a ("crime & theft"): a colocated agent this desperate — past
`cognition.SURVIVAL_HUNGER_THRESHOLD`'s own 0.6 — with meaningfully less
personal food than a nearby settlement-mate may resort to taking it,
same "physical desperation, not malice, drives the deterministic layer"
shape as the critical-hunger movement override (D5)."""

THEFT_TRUST_THRESHOLD = 0.1
"""Theft is only physically plausible against someone the thief doesn't
already trust enough to simply ask — a close, trusted colocated pair
never triggers this regardless of hunger gap."""

THEFT_FOOD_MARGIN = 0.15
"""Minimum food-inventory gap (victim - thief) before a theft is even
considered — a starving pair with equally little food has nothing worth
stealing."""

THEFT_CHANCE_PER_TICK = 0.015
"""Per-tick roll once every other condition is met — deliberately small;
this is a rare, notable act, not routine behavior."""

THEFT_FOOD_FRACTION = 0.4
"""Fraction of the victim's current personal food stock taken in one
theft."""

THEFT_TRUST_PENALTY = -0.45
THEFT_RELATIONSHIP_PENALTY = -0.3
"""Asymmetric, victim-side-only nudges — same "distrust is easy to lose,
hard to earn" shape as dialogue's trust nudges (agent.py). The thief's
own trust/relationship toward the victim is untouched; only the victim's
read of the thief changes."""

THEFT_LAW_PENALTY_MULT = 1.6
"""When the settlement has codified a law/taboo against theft
(`Settlement.laws`), a caught theft costs the thief more — laws having a
real mechanical bite, not just flavor text. See `_theft_forbidden_by_law`."""

THEFT_SECRET_TEXT_TEMPLATE = "I stole food from {name} out of desperation."
"""§1 "deviance loop" completion: a theft now plants a real `Agent.
secrets` entry on the thief (not just a memory) — secrets planted by
theft join the same lifecycle (guarded in dialogue, released at death,
distorted by rumor) disputes already established."""

THEFT_WITNESS_RUMOR_CHANCE = 0.5
"""If a third colocated agent is present at a theft, this is the chance
they notice and the act seeds a real rumor via the existing rumor
machinery (attributed to the witness) — same "deviance -> gossip"
completion the idea doc names."""

OSTRACISM_PENALTY = 0.5
"""§1 "deviance loop": the bounded 0..1 civic penalty an "ostracism"
dispute outcome applies to `Agent.standing_penalty` — see that field's
docstring for what it gates. Deliberately not 1.0: ostracism should
meaningfully cost someone standing, not permanently erase them from
the settlement's social life."""

STANDING_PENALTY_DECAY_PER_MONTH = 0.15
"""How fast `Agent.standing_penalty` fades on its own each month
(`Population._tick_traits`) — roughly a 3-4 month full recovery from a
single ostracism, long enough to read as a real consequence, short
enough that a settlement doesn't accumulate a permanent underclass."""

MIGRATION_CHANCE_PER_TICK = 0.003
"""§1 "migration by choice": once an agent clears a push condition
(below), the per-tick roll before they actually act on it — keeps
migration a rare, deliberate-feeling event rather than an instant
snap the moment a threshold is crossed."""

MIGRATION_STARVATION_HUNGER_THRESHOLD = 0.75
"""Push condition: an agent this hungry, with a meaningfully better-fed
sister settlement available, may choose to leave rather than starve —
distinct from `THEFT_HUNGER_THRESHOLD`'s lower bar (theft is the first,
easier resort; leaving everyone you know is the harder one)."""

MIGRATION_GRANARY_ADVANTAGE = 0.3
"""How much better a target settlement's granary fill ratio must be
than the agent's own for hunger to count as a real pull, not just
"somewhere else exists.\""""

MIGRATION_BOND_THRESHOLD = 0.5
"""Push/pull condition: a bonded partner (relationship at least this
warm) already living in another named settlement is itself sufficient
reason to migrate toward them, independent of hunger/standing."""

MIGRATION_HOUSING_PRESSURE_THRESHOLD = 1.3
"""§2 "refugees after disasters": `_housing_pressure` (population /
housing capacity) must clear this before overcrowding counts as a real
migration push — genuinely over capacity, not merely at it (crowding
past 1.0 is already tolerated day-to-day via CAMP_TOLERANCE/energy
penalties elsewhere; this is the harder "actually can't house everyone
here anymore" bar)."""

RELATION_MIGRATION_NUDGE = 0.05
"""§2 "settlement-level stance (proto-diplomacy)": a successful
migration is itself a "migrant treatment" signal feeding `Settlement.
relations` — increased contact between two communities (whatever the
individual's own reason) reads as modest warming between them, the
same direction dialogue contact already nudges relations, just a
smaller per-event step since migration is far rarer than colocated
dialogue."""

DISPUTE_TRUST_DELTA = 0.1
"""Mechanical teeth for the three dispute outcomes (apply_dispute):
reconciliation resets the pair to mildly-warm and rebuilds a little
trust; a council ruling forces a cool truce without warmth (the feud is
suppressed, not resolved); a feud deepens the rivalry toward -1 and
costs trust both ways."""

DELIBERATE_GUILD_MIN_MASTERS = 2
DELIBERATE_GUILD_FOUNDER_AMBITION = 0.3
"""Deliberate institution founding (v0.64.0 audit-backlog item): an
ambitious master may push a guild into existence at only this many
living masters — below GUILD_FORMATION_MASTER_COUNT's automatic 3 —
via an LLM decision (SimulationEngine._maybe_schedule_guild_founding).
The founder must personally clear the ambition bar
(TRAIT_NOTABLE_THRESHOLD's magnitude class): founding early is an act
of individual drive, not a census threshold."""

FISSION_MIN_POPULATION = 40
"""A settlement can only fission once it holds at least this many
people — below that, splitting leaves two fragile hamlets instead of
one viable town and one viable expedition. Roughly twice
COUNCIL_FORMATION_POPULATION_THRESHOLD: fission is a later-stage event
than civic organization."""

FISSION_LEADER_AMBITION = 0.35
"""Minimum TRAIT_AMBITION for the mature, healthy member who would lead
a founding party out — comfortably above TRAIT_NOTABLE_THRESHOLD (0.3),
so the leader is someone whose drive already shows in their prompts.
The decision itself still goes to the LLM (llm/fission.py); this only
gates who could credibly propose it."""

FISSION_PARTY_MIN = 4
FISSION_PARTY_MAX = 8
"""Founding-party size bounds: fewer than 4 can't sustain construction
pace + foraging at a raw site (the measured founding-funnel lesson,
applied in reverse); more than 8 guts the mother settlement's labor
pool in one event."""

FISSION_MIN_REMAINING = 16
"""The mother settlement must keep at least this many people after the
party leaves — a fission is expansion, not collapse-by-emigration."""

FISSION_COOLDOWN_TICKS = 20_000
"""Minimum ticks between fissions world-wide (~208 sim-days) — founding
a settlement should be a once-an-era event a long-running world
remembers, not a recurring drain."""

FISSION_MATERIALS_SHARE = 0.4
"""Fraction of the mother settlement's materials stockpile the party
carries to the new site — seed capital for the first huts (HUT cost is
3.0; a healthy stockpile's 40% funds several), leaving the mother the
larger share. Physically hauled, not duplicated."""

FISSION_MIN_DISTANCE = 18
"""Minimum Chebyshev distance between a new founding site and every
existing settlement's center — far enough (on a 64x64 default map) to
be a genuinely separate community with its own hinterland, not a
suburb."""

FISSION_PARTY_RELATIONSHIP = 0.2
"""Beyond the leader's own family, only members with at least this much
affinity for the leader join the party — people follow someone they
actually like, they aren't conscripted."""

MAX_SETTLEMENTS = 3
"""Hard cap on concurrent settlements. Each named settlement joins the
monthly LLM job rotation (SimulationEngine's round-robin), so this also
bounds total LLM volume/memory on the 8GB target hardware — raise it
deliberately, not incidentally."""

BUILD_SITE_SEARCH_RADIUS = 3
"""How far (Chebyshev) founders look around their own feet for the best
tile to stake out when a construction roll passes — the close of the
long-standing "where to build, fully agent-pathed" gap. Previously the
building always went up exactly where the group happened to stand;
road/resource adjacency only nudged the *chance*. Now the group
deliberately picks the best nearby site (scored below), and builders
walk to it: an under-construction site is a WANDER-goal attractor the
same way a damaged building already is (see _dispatch_movement), so a
staked-out site a few tiles away genuinely draws labor rather than
depending on incidental colocation. Radius 3 keeps the choice local —
a decision the founders can see from where they stand, not a
map-wide optimizer."""

BUILD_SITE_ADJACENCY_SCORE = 0.5
"""Score bonus per satisfied adjacency (established road; productive
resource or open water) when ranking candidate build sites — both
bonuses can stack. Same two signals SETTLE_CHANCE_*_MULTIPLIER already
uses for the roll, reused as a ranking so the two "where does the town
grow" mechanisms can't disagree about what makes a tile good."""

BUILD_SITE_DISTANCE_PENALTY = 0.15
"""Score penalty per Chebyshev step from the founders' own tile — all
else equal they build where they stand (zero penalty), and a
road/resource-adjacent tile (+0.5 or +1.0) is worth walking up to a
few tiles for, but never the full radius for no gain."""

RECOVERY_LESSON_TEMPLATES = (
    "Illness nearly took me once; I don't take my health for granted anymore.",
    "I remember how close I came to not recovering — I rest when I need to now.",
    "Surviving that sickness taught me not to push myself past exhaustion.",
)
RECONCILE_LESSON_TEMPLATES = (
    "Making peace was harder than staying angry, but it was worth it.",
    "I learned that a feud costs more than it's worth, once I let mine go.",
    "Forgiving them taught me that grudges only ever weigh me down.",
)
"""Deferred item 1 (docs/VISION-2026-07-LEARNING.md), "non-core-cast
population-wide lessons": a genuinely non-LLM, template-based lesson-
formation path for the WHOLE population, distinct from the LLM-authored
`Agent.lessons` core-cast jobs (Reflect()/memory_drift, both still
core-cast-gated per the standing per-agent-LLM-call rule — this costs
no LLM budget at all, so the gate doesn't apply). Picked deterministically
by `agent.id % len(...)` at the two call sites below (illness recovery,
dispute reconciliation) rather than via RNG — small, fixed, and every
agent who lives through the same kind of event gets *a* lesson, not
necessarily the identical wording every time."""

MAX_DIALOGUES_PER_TICK = 6
"""Caps how many *fallback* (deterministic, no LLM call) dialogue
exchanges are selected in a single tick regardless of how many
colocated pairs qualify. Explicit user directive: LLM dialogue is now
reserved entirely for the single fixed `Population.voice_pair_ids`
pair (see `due_for_voice_dialogue`) — every other colocated pair,
including former core-core ones, resolves via the deterministic
fallback so the crowd stays socially alive without spending any LLM
budget. See Population.due_for_dialogue, docs/DECISIONS.md, E2."""

VOICE_DIALOGUE_COOLDOWN_TICKS = 5
"""Explicit user directive ("triggered often... every 5 ticks or
something like that"): the voice pair's own cooldown between
exchanges, far shorter than the ordinary `DIALOGUE_COOLDOWN_TICKS`
(300) — since this is now the ONLY pair spending LLM dialogue budget,
the freed-up call volume goes toward talking to each other far more
frequently instead of many pairs talking rarely. See due_for_voice_
dialogue."""

NARRATIVE_EMOTION_BONUS = 3000.0
"""`_narrative_significance`'s bonus for any dominant, non-grief
emotion (fear/joy/anger) — same unit family as `PROMINENCE_BOND_
WEIGHT`. A visibly emotional agent right now reads as "something is
happening to them," worth surfacing as this week's protagonist even
if they're not otherwise the settlement's most prominent figure."""

NARRATIVE_GRIEF_BONUS = 5000.0
"""`_narrative_significance`'s bonus for grief specifically — the
explicit "a grieving parent" example — weighted above the generic
emotion bonus since grief is the single most narratively load-bearing
emotion this project models (death, widowhood, loss)."""

NARRATIVE_REBEL_BONUS = 4000.0
"""`_narrative_significance`'s bonus for an active hardened feud
(`Agent.relationship_flags`, set by ostracism/feud-outcome disputes) —
the explicit "a rebel" example: someone the village has turned against
or who has turned against someone else."""

NARRATIVE_EXTREME_EVENT_WEIGHT = 1500.0
"""`_narrative_significance`'s per-point weight on `Agent.extreme_
event_count` (Phase 3.B "irreversible personality" — disaster
survival, feud/ostracism, widowhood) — a life visibly marked by
extreme events is exactly the kind of standing narrative weight that
should pull someone into the spotlight over an ordinary quiet week."""

VOICE_CONVERSATION_HISTORY_TURNS = 6
"""How many of the voice pair's own most recent lines (from
`Population.voice_conversation`) are fed back into the next prompt as
"the conversation so far" — enough for the model to pick up a genuine
thread without letting an already-long-running conversation dominate
the prompt. See llm/dialogue.py's build_voice_prompt."""

MAX_VOICE_CONVERSATION_STORED = 220
"""Cap on `Population.voice_conversation`'s ring — comfortably more
than VOICE_CONVERSATION_HISTORY_TURNS actually reads each call, so a
little history survives past what any single prompt uses, same
oldest-dropped-first discipline as every other capped ring here.

Raised 24 -> 220 in v1.4.6: this ring is also the ONLY place
`dialogue._is_near_duplicate_line`'s repetition backstop (see
VOICE_LINE_DUPLICATE_OVERLAP) looks for a speaker's own past lines,
and a live-reported repeat recurred ~650 ticks apart — at `VOICE_
DIALOGUE_COOLDOWN_TICKS=5`'s fastest cadence that's well over 100
exchanges, far outside the old 24-entry window (which had already
evicted the earlier occurrence long before the repeat happened, so the
backstop never got a chance to catch it). 220 covers a Wilhelmina/
Quill-shaped run comfortably even at the fastest cooldown; still a
bounded ring, still cheap (small dicts, no LLM cost either way — the
prompt itself still only ever reads the newest VOICE_CONVERSATION_
HISTORY_TURNS)."""

PROMINENCE_BOND_WEIGHT = 4000.0
"""Weight on an agent's bond count in `_prominence` (core-cast refill
ranking), expressed in the same units as age_ticks so one strong social
bond is worth ~4000 ticks (~42 sim-days) of age. A settlement's most
socially-central and longest-lived inhabitants are its natural
protagonists; both signals matter, neither should dominate outright."""

PROMINENCE_SKILL_WEIGHT = 2000.0
"""Weight on an agent's summed skill level in `_prominence` — a master
of a craft is a notable figure too, but ranks below raw social
centrality and longevity (a smaller multiplier than
PROMINENCE_BOND_WEIGHT)."""

PROMINENCE_BOND_THRESHOLD = 0.3
"""|relationship| at or above which a tie counts as a real 'bond' for
`_prominence` — same magnitude class as TRAIT_NOTABLE_THRESHOLD; faint
acquaintances shouldn't inflate a wallflower's prominence."""

PROMINENCE_REPUTATION_WEIGHT = 3000.0
"""Weight on `reputation()` in `_prominence` (Phase L, docs/VISION-2026-
07.md "Society & Power") — same units/scale family as PROMINENCE_BOND_
WEIGHT/PROMINENCE_SKILL_WEIGHT. reputation() is already -1..1, so this
is the full per-point swing; a widely well-regarded agent is a natural
protagonist candidate independent of how many *specific* bonds they've
formed (the existing bond term)."""

CORE_CAST_ROTATION_MARGIN = 1.5
"""Post-v1 convergence-audit follow-up: `maintain_core_cast`'s own
docstring frames the cast as deliberately sticky and "never demoted
while alive" — correct for keeping a young cast stable, but with no
counterpart at all across a long run it becomes a structural
convergence bug: the same handful of characters carry every LLM-
authored storyline for as long as they happen to live, and a vacated
seat's own refill ranking (`_prominence`, longevity-weighted) tends to
hand it straight to a founder's already-old child. `_maybe_rotate_
core_cast` closes this without touching cast size or LLM call volume —
a rare, bounded exception to "never demoted," not a repeal of it. A
non-core candidate must out-rank the WEAKEST current core member by
this multiplicative margin on `_prominence` before a swap is even
considered — the cast stays sticky against anyone merely comparable,
only a genuinely more prominent rising figure can displace a quiet
incumbent."""

CORE_CAST_ROTATION_CHANCE_PER_MONTH = 0.15
"""Even once the margin above is cleared, a swap only happens with this
probability per month-end check — keeps rotation feeling like an
organic narrative beat (a quiet elder finally stepping back as someone
else's story rises) rather than a mechanical eviction the instant a
threshold trips."""

REPUTATION_MIN_SOURCES = 2
"""Below this many living agents holding *any* trust opinion of someone,
`reputation()` reads as neutral (0.0) rather than a noisy 1-source
average — mirrors the same 'don't let a thin sample masquerade as a
real signal' discipline `_prominence` already applies via weighting."""

LEGACY_REPUTATION_DECAY = 0.03
"""§9 'long-term reputation and family legacy' (docs/IDEAS-2026-07-
EMERGENCE.md): monthly fade rate applied to `Population.
_deceased_reputation_legacy` — a dead agent's final standing doesn't
vanish the instant `_refresh_reputation`'s alive-only filter drops
them (the confirmed real gap the idea doc named), it lingers and
slowly fades, the same 'a notable villager's reputation outlives them
for a while, memory of it eventually fades too' shape `memorials`/
`decay_memory_salience` already apply to other kinds of legacy."""

LEGACY_REPUTATION_FLOOR = 0.02
"""Once a deceased agent's faded legacy reputation's magnitude drops
below this, it's pruned from `_deceased_reputation_legacy` entirely —
bounds the structure's growth across a long-running world with many
deaths, same 'decay to zero, then delete' discipline the relationship-
leak fix already established."""


# `_namespaced_rng` is the shared helper (see hearthmind/util.py) — kept
# under its historical private name here so the many call sites in this
# module are unchanged.
_namespaced_rng = namespaced_rng


def _tech_factor(settlement: Settlement) -> float:
    """Multiplicative bonus from established inventions — see
    TECH_BONUS_PER_LEVEL, docs/DECISIONS.md, E3."""
    return 1.0 + TECH_BONUS_PER_LEVEL * settlement.tech_level


def _specialization_factor(settlement: Settlement, category: str) -> float:
    """Post-v1 follow-up: multiplicative bonus from `Settlement.
    invention_specializations[category]` — the category-specific LEAN
    an invention's LLM-chosen category nudges, stacking on top of (not
    replacing) `_tech_factor`'s flat, category-agnostic bonus. 1.0 (no-
    op) for a settlement that hasn't accumulated any bonus in this
    category yet. See INVENTION_SPECIALIZATION_STEP/CAP."""
    return 1.0 + settlement.invention_specializations.get(category, 0.0)


def _haul_factor(settlement: Settlement) -> float:
    """Multiplicative bonus from ready carts on gathered-material yield —
    see CART_HAUL_BONUS_PER_CART/CART_BONUS_CAP, docs/DECISIONS.md,
    vehicles pass."""
    ready_carts = sum(1 for v in settlement.vehicles if v.kind is VehicleKind.CART and v.stage is VehicleStage.READY)
    return 1.0 + CART_HAUL_BONUS_PER_CART * min(ready_carts, CART_BONUS_CAP)


def _raft_factor(settlement: Settlement) -> float:
    """Multiplicative bonus from ready rafts on a fish catch's hunger
    relief — same shape as `_haul_factor`, see RAFT_FISH_BONUS_PER_RAFT/
    RAFT_BONUS_CAP."""
    ready_rafts = sum(1 for v in settlement.vehicles if v.kind is VehicleKind.RAFT and v.stage is VehicleStage.READY)
    return 1.0 + RAFT_FISH_BONUS_PER_RAFT * min(ready_rafts, RAFT_BONUS_CAP)


def _agent_mount(settlement: Settlement, agent_id: int) -> Vehicle | None:
    """Either personal-vehicle kind (MOUNT or the era-gated AUTOMOBILE
    upgrade) an agent currently has claimed and ready — see
    PERSONAL_VEHICLE_KINDS."""
    for vehicle in settlement.vehicles:
        if (
            vehicle.kind in PERSONAL_VEHICLE_KINDS and vehicle.stage is VehicleStage.READY
            and vehicle.assigned_agent_id == agent_id
        ):
            return vehicle
    return None


_pending_memory_evictions: list[dict] = []
"""Transient (never serialized) buffer of significant evicted agent
memories — appended by `_remember`'s eviction branch, drained and
durably logged to disk by `SimulationEngine._tick_once()` every tick
(see `snapshot.log_agent_memory_entry`, Constitution §6, v0.86.3).
Module-level rather than a `Population`/`World` field because `_remember`
receives only `agent`, with no reference back to its owning Population
or the engine's DB connection — the same constraint that shaped how
`SimulationEngine._maybe_schedule_consciousness` logs durably (see
`CLAUDE.md`, "per-agent memory durability" note in the v0.86.2 section).
Safe under this project's single-threaded-asyncio, one-World-per-process
tick loop (`CLAUDE.md`, "Preserve absolutely"): `_tick_once()` is fully
synchronous, so nothing can append to this buffer concurrently with the
engine draining and clearing it. Entries: `{"agent_id": int, "text": str}`."""


def _memory_salience(agent: Agent) -> float:
    """How memorable *right now* is, from the agent's own current
    `emotions` — see MEMORY_SALIENCE_BASELINE's docstring (Phase I,
    "layered memory v1"). A calm moment gets the baseline; a moment
    lived through real fear/grief/joy/anger scores higher, up to 1.0."""
    if not agent.emotions:
        return MEMORY_SALIENCE_BASELINE
    return clamp(
        MEMORY_SALIENCE_BASELINE + sum(agent.emotions.values()) * MEMORY_SALIENCE_EMOTION_WEIGHT,
        MEMORY_SALIENCE_BASELINE, 1.0,
    )


def _remember(agent: Agent, text: str, routine: bool = False, because: str = "") -> None:
    """Append to an agent's short personal log (`memories`, episodic)
    AND its small strictly-FIFO `working_memory` — see WORKING_MEMORY_
    MAX's docstring. `memories` is capped at MAX_AGENT_MEMORIES but no
    longer FIFO: eviction drops the LOWEST-salience entry (computed at
    write time from the agent's current emotions, ties broken toward
    the oldest index) rather than always the oldest, so a memorable
    experience genuinely outlasts a mundane one. The only place either
    `memories` or `memory_salience` is ever mutated — see their
    docstrings on Agent for the index-alignment invariant this relies
    on. See docs/DECISIONS.md, relationship-memory pass + Phase I
    "layered memory v1\" (v0.76.3).

    `routine=True` (see ROUTINE_MEMORY_SALIENCE_MULT) is for high-
    frequency, low-narrative-interest events — it discounts the
    computed salience so the memory is evicted sooner, and — the bigger
    effect — skips `working_memory` entirely, so it can never be the
    "just now" line dialogue/cognition read. Still recorded in
    `memories`, just deprioritized, never hidden.

    `because` (v0.87.14 "causal memory links," docs/IDEAS-2026-07-
    EMERGENCE.md §7): an optional short cause description, stored
    index-aligned in `agent.memory_causes` — "" (the default) means no
    known cause. Only ever passed at call sites where the engine
    OBJECTIVELY knows the cause (a death, a dispute outcome, an
    inheritance) — never fabricated for an ordinary memory. See
    `Agent.memory_causes`'s docstring."""
    salience = _memory_salience(agent)
    # v0.87.16 "improve memory weighting" (explicit user direction):
    # repetition dampening — checked against the memories ALREADY
    # stored, before this one is appended. See MEMORY_REPETITION_
    # DAMPING's docstring.
    new_tokens = _overlap_tokens(text)
    if new_tokens and any(
        len(new_tokens & _overlap_tokens(existing)) >= MEMORY_REPETITION_OVERLAP_THRESHOLD
        for existing in agent.memories
    ):
        salience *= MEMORY_REPETITION_DAMPING
    agent.memories.append(text)
    if routine:
        salience *= ROUTINE_MEMORY_SALIENCE_MULT
    agent.memory_salience.append(salience)
    agent.memory_causes.append(because)
    if len(agent.memories) > MAX_AGENT_MEMORIES:
        evict_at = min(range(len(agent.memories)), key=lambda i: (agent.memory_salience[i], i))
        evicted_text = agent.memories[evict_at]
        evicted_salience = agent.memory_salience[evict_at]
        evicted_because = agent.memory_causes[evict_at]
        del agent.memories[evict_at]
        del agent.memory_salience[evict_at]
        del agent.memory_causes[evict_at]
        # v0.87.16 "deepen long-term historical identity": a genuinely
        # major evicted memory (already causally tagged, or vivid
        # enough to clear MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD)
        # graduates into the small permanent `core_memories` tier
        # instead of just disappearing into the disk-only durable log
        # below — see MAX_CORE_MEMORIES's docstring. Bounded by its own
        # small cap: the weakest core memory yields when a new one
        # qualifies and the tier is already full.
        if evicted_because or evicted_salience >= MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD:
            agent.core_memories.append(evicted_text)
            agent.core_memory_salience.append(evicted_salience)
            if len(agent.core_memories) > MAX_CORE_MEMORIES:
                weakest = min(
                    range(len(agent.core_memories)), key=lambda i: agent.core_memory_salience[i],
                )
                del agent.core_memories[weakest]
                del agent.core_memory_salience[weakest]
        # Durable record of what would otherwise be permanently lost
        # (Constitution §6, v0.86.3) — deliberately gated on `not
        # routine` (this call's OWN significance, not the evicted
        # entry's): routine calls are frequent, low-narrative-interest
        # noise (food/tool/medicine sharing) by design, and logging
        # every one of those evictions would bloat the durable log with
        # exactly the texture this project already deprioritizes for
        # `working_memory`. A non-routine call means something
        # memorable is happening right now, which is also the moment
        # worth preserving whatever it displaced.
        if not routine:
            _pending_memory_evictions.append({"agent_id": agent.id, "text": evicted_text})
    if not routine:
        agent.working_memory.append(text)
        if len(agent.working_memory) > WORKING_MEMORY_MAX:
            agent.working_memory.pop(0)


def _trade_relationship_threshold(giver: Agent) -> float:
    """Integration milestone: the relationship bar a giver personally
    applies before sharing food/tools/medicine — see
    TRAIT_SOCIABILITY_TRADE_THRESHOLD_SHIFT."""
    sociability = giver.traits.get(TRAIT_SOCIABILITY, 0.0)
    return TRADE_MIN_RELATIONSHIP - sociability * TRAIT_SOCIABILITY_TRADE_THRESHOLD_SHIFT


def _starvation_threshold(agent: Agent) -> float:
    """Integration milestone: personal resilience stretches or shrinks
    how long an agent holds on into a starvation crisis before it's
    fatal — see TRAIT_RESILIENCE_STARVATION_TOLERANCE_INFLUENCE. Reads
    the same trait `starving_ticks == 1`'s onset already nudges
    (TRAIT_SUSTAINED_HUNGER_NUDGE), closing that write-only loop."""
    resilience = agent.traits.get(TRAIT_RESILIENCE, 0.0)
    return STARVATION_TICKS_TO_DEATH * (1.0 + resilience * TRAIT_RESILIENCE_STARVATION_TOLERANCE_INFLUENCE)


def _near_productive_resource(resources: ResourceGrid, x: int, y: int) -> bool:
    """`_maybe_start_construction`'s resource-proximity "where to
    build" check: is there a still-productive (amount > 0) foraging
    node within SETTLE_RESOURCE_SEARCH_RADIUS of this candidate tile?
    A small local scan (the search radius is tiny, and settlements are
    small relative to the map), not an indexed spatial query — fine at
    this scale, same "revisit if it ever shows up in profiling"
    tolerance as the rest of this project's O(N) scans."""
    r = SETTLE_RESOURCE_SEARCH_RADIUS
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            node = resources.get(x + dx, y + dy)
            if node is not None and node.amount > 0.0:
                return True
    return False


def _nudge_trait(agent: Agent, trait: str, delta: float) -> None:
    """H6: apply one event-driven nudge to a trait axis, clamped -1..1.
    See TRAIT_RESILIENCE/TRAIT_SOCIABILITY."""
    agent.traits[trait] = clamp(agent.traits.get(trait, 0.0) + delta, -1.0, 1.0)


EXTREME_EVENT_HARDEN_THRESHOLD = 3
EXTREME_EVENT_HARDEN_BUMP = 0.3
"""Phase 3.B, "identity, irreversible change" (docs/VISION-2026-07-21-
SELFEVOLVING.md): a small, bounded counter of genuinely extreme lived
events — surviving a disaster (1.D), a relationship hardening into a
standing feud, a bonded partner's death — where H6's usual bounded/
mean-reverting trait nudges (CLAUDE.md's own anti-homogenization fix)
are deliberately too gentle to capture "this person is not who they
were." Crossing the threshold locks TRAIT_RESILIENCE into `Agent.
hardened_traits` (exempt from `_tick_traits`'s monthly reversion from
then on) with one real, permanent bump — a genuine exception to "traits
always revert toward neutral," not a repeal of it."""


def _maybe_harden_trait(agent: Agent) -> None:
    """Call at each of the three extreme-event sites (disaster survival,
    feud hardening, bonded/family death grief). No-op once already
    hardened — the counter still increments (a durable record of how
    much this agent has lived through) but a second crossing does
    nothing further."""
    agent.extreme_event_count += 1
    if TRAIT_RESILIENCE in agent.hardened_traits:
        return
    if agent.extreme_event_count >= EXTREME_EVENT_HARDEN_THRESHOLD:
        agent.hardened_traits.add(TRAIT_RESILIENCE)
        agent.traits[TRAIT_RESILIENCE] = clamp(
            agent.traits.get(TRAIT_RESILIENCE, 0.0) + EXTREME_EVENT_HARDEN_BUMP, -1.0, 1.0,
        )


_TRAIT_MEAN_REVERSION_BY_TRAIT = {
    TRAIT_AMBITION: TRAIT_MEAN_REVERSION_AMBITION,
    TRAIT_OPENNESS: TRAIT_MEAN_REVERSION_OPENNESS,
}
"""v1 audit fix: per-trait override for `Population._tick_traits`'s
monthly reversion strength — see TRAIT_MEAN_REVERSION_AMBITION's
docstring. Resilience/sociability aren't listed here and fall back to
the shared TRAIT_MEAN_REVERSION, since both now have real, frequent
bidirectional event nudges and don't need a faster artificial pull."""


_INHERITABLE_TRAITS = GENOME_TRAITS
"""Kept as a population.py-local alias (some earlier call sites/reading
this file expect the name here) — the actual closed vocabulary now
lives once, in `agent.GENOME_TRAITS`, so the two can never drift apart."""


def _agent_allele_pair(agent: Agent, trait: str) -> tuple[float, float]:
    """A15 (roadmap Stage IV step 22): an agent's two alleles for
    `trait`, or — for an agent with no recorded genome (every pre-A15
    snapshot, or a legacy code path that still constructs an `Agent`
    without one) — both reading as its current expressed phenotype
    value, i.e. "genome unknown, assume homozygous at the observed
    trait." Keeps inheritance total: a genome-less parent still
    contributes real (if less granular) heredity, never a crash or a
    silently-skipped axis."""
    pair = agent.genome.get(trait)
    if pair is not None:
        return pair
    value = agent.traits.get(trait, 0.0)
    return (value, value)


def _inherited_genome_and_traits(
    a: Agent, b: Agent, rng: random.Random,
) -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
    """A15 "Genetic inheritance" (roadmap Stage IV step 22), replacing
    v0.87.6's flat parent-average+noise blend with real Mendelian-style
    inheritance: for each `GENOME_TRAITS` axis, the child receives ONE
    allele independently drawn from each parent's own diploid pair
    (real genetic drift — which of the two alleles gets passed on is
    random per axis per parent), each independently subject to
    `GENOME_MUTATION_CHANCE` of being replaced by a fresh mutated value
    (`GENOME_MUTATION_STDDEV`) instead of copied verbatim (real
    mutation, distinct from drift). The child's expressed `traits`
    value for each axis is the mean of its own two new alleles — same
    "-1..1, 0.0 neutral" phenotype convention every trait-consuming
    call site already expects, so nothing downstream needs to change.
    Called once per birth in `_maybe_reproduce`; zero LLM cost."""
    genome: dict[str, tuple[float, float]] = {}
    traits: dict[str, float] = {}
    for trait in GENOME_TRAITS:
        alleles = []
        for parent in (a, b):
            allele = rng.choice(_agent_allele_pair(parent, trait))
            if rng.random() < GENOME_MUTATION_CHANCE:
                allele = clamp(rng.gauss(0.0, GENOME_MUTATION_STDDEV), -1.0, 1.0)
            alleles.append(allele)
        genome[trait] = (alleles[0], alleles[1])
        traits[trait] = clamp((alleles[0] + alleles[1]) / 2.0, -1.0, 1.0)
    return genome, traits


def _prune_extinct_families(settlement: Settlement, living_ids: set[int]) -> None:
    """v0.54.0 memory-bounds fix: `Settlement.institutions` was
    discovered unbounded on a persistent world (see
    INSTITUTION_LIST_MAX_STORED's docstring — measured 191 families by
    tick 24,000 on a single settlement, still climbing regardless of
    population plateauing at the carrying-capacity cap). Only runs once
    stored FAMILY count exceeds the cap, and only ever removes families
    with zero living members (oldest-founded first) — a family with
    even one living member is never touched, so this can never orphan a
    still-living agent's `family_for` lookup."""
    _prune_extinct_institutions(settlement, living_ids, InstitutionKind.FAMILY, INSTITUTION_LIST_MAX_STORED)


def _prune_extinct_institutions(
    settlement: Settlement, living_ids: set[int], kind: InstitutionKind, cap: int,
) -> None:
    """Shared eviction rule behind `_prune_extinct_families` (v0.54.0)
    and, since Phase L (v0.80.0), FACTION — generalized rather than
    duplicated once a second one-time-authored institution kind needed
    the same "only prune once over cap, only the fully-dead, oldest
    first" discipline. GUILD/COUNCIL don't use this: COUNCIL is
    inherently small (COUNCIL_SIZE) and GUILD grows by mastery, not
    formation events, so neither has ever measured unbounded."""
    matching = [i for i in settlement.institutions if i.kind is kind]
    if len(matching) <= cap:
        return
    extinct = sorted(
        (i for i in matching if i.member_agent_ids.isdisjoint(living_ids)),
        key=lambda i: i.founding_tick,
    )
    excess = len(matching) - cap
    to_remove = {inst.id for inst in extinct[:excess]}
    if to_remove:
        settlement.institutions = [i for i in settlement.institutions if i.id not in to_remove]


def _record_debt(recipient: Agent, giver: Agent, amount: float) -> None:
    """Phase L "Economy depth": called by `_maybe_trade_food`/`_maybe_
    trade_tools`/`_maybe_trade_medicine` after a successful barter. Any
    debt the giver already owed the recipient (from a past reversed
    trade) settles first — goods flowing both ways over time nets out
    toward zero rather than both directions piling up independently —
    and only the remainder becomes a new debt on the recipient. This is
    the one mutator of `Agent.debts` besides `decay_debts`' fade."""
    delta = amount * DEBT_PER_TRADE_FRACTION
    reverse = giver.debts.get(recipient.id, 0.0)
    if reverse > 0.0:
        settled = min(reverse, delta)
        giver.debts[recipient.id] = reverse - settled
        if giver.debts[recipient.id] < DEBT_PRUNE_THRESHOLD:
            giver.debts.pop(recipient.id, None)
        delta -= settled
    if delta > 0.0:
        recipient.debts[giver.id] = recipient.debts.get(giver.id, 0.0) + delta


_WATER_BIOMES = frozenset({Biome.DEEP_WATER, Biome.SHALLOW_WATER})

BRIDGE_MAX_SPAN = 6
"""Longest run of water tiles a single bridge can cover, found by
`_find_bridge_span`'s BFS from a shore tile — bounds both the search
cost and how implausibly wide a "bridge" is allowed to be; a channel
wider than this stays uncrossable until the map's own geography (or a
future bridge from a different shore point) offers a narrower gap."""


def _is_walkable(
    terrain: list[list[Tile]], x: int, y: int, mountain_unlocked: bool = False,
    bridge_tiles: frozenset[tuple[int, int]] = frozenset(), water_capable: bool = False,
) -> bool:
    biomes = MOUNTAIN_WALKABLE_BIOMES if mountain_unlocked else WALKABLE_BIOMES
    if terrain[y][x].biome in biomes:
        return True
    # A boat-mounted agent (v0.87.42, VehicleKind.BOAT) can cross open
    # water anywhere, not just a deliberately-built BRIDGE span — the
    # real transport gap RAFT's own docstring flagged as deferred.
    # Checked before the bridge-span check since it's the cheaper/more
    # common water-crossing path once any boats exist.
    if water_capable and terrain[y][x].biome in WATER_CROSSABLE_BIOMES:
        return True
    # A STANDING bridge's spanned water tiles are the one deliberate
    # exception to "biome determines passability" — see BuildingKind.
    # BRIDGE's docstring. Checked second (the common case never reaches
    # here) and only ever true for the handful of tiles an actual
    # bridge covers, so this is cheap even though it's a set membership
    # test on every walkability check.
    return bool(bridge_tiles) and (x, y) in bridge_tiles


def _bridge_tiles_from_settlements(settlements: list[Settlement]) -> frozenset[tuple[int, int]]:
    """Every STANDING BRIDGE's spanned water tiles, pooled across every
    settlement into one set — bridges are physical infrastructure on
    the shared map, not settlement-private (same "anyone can use it"
    shape roads already have), so this is computed once per tick and
    passed uniformly to every agent's movement, not looked up per
    settlement. Cheap: bridges are rare and each span is short
    (bounded by BRIDGE_MAX_SPAN)."""
    tiles: set[tuple[int, int]] = set()
    for settlement in settlements:
        for building in settlement.buildings:
            if building.kind is BuildingKind.BRIDGE and building.stage is BuildingStage.STANDING:
                tiles.update(building.bridge_span)
    return frozenset(tiles)


def _walkable_tiles(terrain: list[list[Tile]]) -> list[tuple[int, int]]:
    tiles = [
        (tile.x, tile.y)
        for row in terrain
        for tile in row
        if tile.biome in WALKABLE_BIOMES
    ]
    if tiles:
        return tiles
    # Degenerate case (e.g. a tiny all-water test map): fall back to every
    # tile rather than failing to spawn anyone.
    return [(tile.x, tile.y) for row in terrain for tile in row]


def _find_bridge_span(
    terrain: list[list[Tile]], origin: tuple[int, int], mountain_unlocked: bool = False,
) -> tuple[tuple[int, int], ...] | None:
    """From a walkable shore tile `origin`, a bounded (BRIDGE_MAX_SPAN)
    multi-step BFS through water tiles only, looking for the nearest
    opposite shore NOT already reachable from `origin` by land (no
    point bridging a peninsula back to itself). Returns the ordered
    water-tile path from `origin`'s first water neighbor to the last
    water tile before the far shore, or None if no crossing exists
    within the span limit. Uniform-cost BFS naturally finds the
    shortest (cheapest) crossing first. Deliberately only called from
    a colocation-gated, probability-rolled founding check (`_maybe_
    start_bridge`) — this is not cheap enough to run every tick for
    every agent, but founding a bridge is itself a rare event."""
    if not _is_walkable(terrain, *origin, mountain_unlocked):
        return None
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    # Land already reachable without a bridge — bridging to any tile in
    # here would connect two points already connected, so it's not a
    # real crossing.
    home_component = Population._reachable_tiles(terrain, origin)

    prev: dict[tuple[int, int], tuple[int, int]] = {}
    seen: set[tuple[int, int]] = set()
    ox, oy = origin
    queue: deque[tuple[int, int, int]] = deque()
    for dx, dy in _NEIGHBOR_OFFSETS:
        nx, ny = ox + dx, oy + dy
        if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
            continue
        if terrain[ny][nx].biome not in _WATER_BIOMES:
            continue
        seen.add((nx, ny))
        prev[(nx, ny)] = origin
        queue.append((nx, ny, 1))

    while queue:
        cx, cy, depth = queue.popleft()
        if depth > BRIDGE_MAX_SPAN:
            continue
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                continue
            tile = terrain[ny][nx]
            if tile.biome in _WATER_BIOMES:
                seen.add((nx, ny))
                prev[(nx, ny)] = (cx, cy)
                queue.append((nx, ny, depth + 1))
            elif _is_walkable(terrain, nx, ny, mountain_unlocked) and (nx, ny) not in home_component:
                span: list[tuple[int, int]] = []
                node = (cx, cy)
                while node != origin:
                    span.append(node)
                    node = prev[node]
                span.reverse()
                return tuple(span)
    return None


@dataclass
class Population:
    agents: list[Agent] = field(default_factory=list)
    _next_id: int = 0
    deaths_starvation: int = 0
    deaths_old_age: int = 0
    deaths_predator: int = 0
    deaths_disease: int = 0
    """Cumulative counts since world creation, for diagnosis — the
    inhabitant listing only shows who's alive *now*, so without these a
    population crash (many deaths between two snapshots) is invisible in
    `inspect_world` unless you happened to be watching the event log at
    the time. See docs/DECISIONS.md, D5 (deaths_predator added in the
    danger pass)."""
    rumors_seeded_total: int = 0
    """Rumor-epidemiology instrumentation (docs/DECISIONS.md "continue
    expanding" pass): cumulative count of distinct rumors that have
    entered the world — every `spread_rumor` call (a caravan's outside
    news) plus every dialogue exchange whose LLM/fallback result
    carries a non-empty `rumor` (a villager-invented one, via
    `apply_dialogue`). Not a measure of *reach* (see the next field) —
    just how many separate pieces of gossip have ever been born."""
    rumor_listener_exposures_total: int = 0
    """Cumulative agent-exposures to rumor content — incremented by
    `len(listeners)` per `spread_rumor` call and by 2 (both dialogue
    parties) per rumor-carrying `apply_dialogue` call. This is real
    instrumentation of the *existing* gossip/trust contagion machinery
    (docs/ROADMAP.md's long-flagged "rumor-epidemiology
    instrumentation" gap), not a new propagation mechanic — this
    project's dialogue-carried rumors are each independently LLM/
    fallback-generated per exchange rather than the same rumor string
    literally hopping listener to listener, so this counts total
    exposure volume (a meaningful "how much gossip has moved through
    the village" signal against population size), not a traceable
    per-rumor transmission chain."""
    dialogue_cooldowns: dict[tuple[int, int], int] = field(default_factory=dict)
    """(agent_id, agent_id) sorted pair -> tick of their last dialogue
    exchange, so a stable colocated pair doesn't re-trigger the LLM every
    tick — see due_for_dialogue, docs/DECISIONS.md, E2."""
    cognition_trigger_cooldowns: dict[int, int] = field(default_factory=dict)
    """agent_id -> tick of their last event-triggered (not staggered-
    daily) cognition call — see due_for_triggered_cognition. Same
    per-pair-cooldown shape as dialogue_cooldowns, just keyed by a
    single agent instead of a pair."""
    core_agent_ids: set[int] = field(default_factory=set)
    """The LLM-driven "core cast" (v0.70.0, Config.llm_core_cast_size) —
    the only agents that receive LLM cognition, and the only agents whose
    pairings receive LLM-authored dialogue. Everyone else runs on the
    deterministic fallback. Maintained by `maintain_core_cast`: seeded
    from the founders, sticky (a member stays until death), and refilled
    from the most-prominent living non-member (see `_prominence`) when a
    seat opens. Persisted so the cast is stable across restarts (a
    resumed world must not reshuffle who its protagonists are). This is
    the fix for LLM call volume scaling with population — see the config
    field's docstring and docs/DECISIONS.md."""
    _reputation_cache: dict[int, float] = field(default_factory=dict)
    """Phase L (docs/VISION-2026-07.md "Society & Power"): agent id ->
    mean trust toward that agent across every living agent who holds an
    opinion of them, refreshed once a month by `_refresh_reputation`
    (see `reputation()`). Deliberately NOT persisted — a fully derived
    view over `Agent.trust`, cheap to rebuild, and (like `last_carrying_
    capacity`) would just go stale between a save and a reload if it
    were."""
    _deceased_reputation_legacy: dict[int, float] = field(default_factory=dict)
    """§9 'long-term reputation and family legacy' (docs/IDEAS-2026-07-
    EMERGENCE.md): a dead agent's final `_reputation_cache` reading,
    snapshotted the month they drop out of the alive-only cache instead
    of vanishing outright, then faded monthly by LEGACY_REPUTATION_
    DECAY and pruned once its magnitude crosses LEGACY_REPUTATION_
    FLOOR — bounded the same 'decay to zero, then delete' way the
    relationship-leak fix already established. Deliberately NOT
    persisted, same rationale as `_reputation_cache` itself (derived,
    cheap to approximate-rebuild from `Agent.trust`, and it's a slow-
    fading texture value, not durable history — `Institution.feuds`/
    `memorials`/`Settlement.records` remain the actually-persisted
    legacy mechanisms). Consumed by `reputation()` (falls back to this
    once an id is no longer alive) and `family_legacy_reputation()`."""
    last_carrying_capacity: float = float(POPULATION_CAP)
    """Recomputed every tick by `carrying_capacity()` — the dynamic ceiling
    that now actually gates reproduction/growth (H1, docs/ROADMAP.md Phase
    H), composing housing/economy/labor/security/environment into one
    number instead of the flat `POPULATION_CAP` safety valve. Stored (not
    just returned) so `summary()` can expose it without threading a
    `Settlement` through a method that otherwise doesn't need one; not
    itself persisted, since it's fully derived and recomputed on the next
    tick regardless."""
    dispute_cooldowns: dict[tuple[int, int], int] = field(default_factory=dict)
    """(agent_id, agent_id) sorted pair -> tick of their last dispute-
    resolution moment — same shape/pruning as dialogue_cooldowns. See
    due_for_dispute."""
    dialogue_topics: dict[tuple[int, int], list[str]] = field(default_factory=dict)
    """v0.87.12 "dialogue novelty memory" (docs/IDEAS-2026-07-EMERGENCE.
    md §7): (agent_id, agent_id) sorted pair -> small ring (capped
    DIALOGUE_TOPICS_RING_MAX) of the last few topics an LLM-authored
    exchange between them actually covered (`dialogue.parse_dialogue`'s
    new `topic` field). Same key space/pruning as `dialogue_cooldowns`
    (pruned alongside it in `due_for_dialogue`) — read back into the
    NEXT exchange between the same pair as one grounding line ("you two
    have lately talked about X, Y — find something new or go deeper"),
    so the live-LLM path doesn't keep converging on the same subject
    pair after pair."""
    voice_pair_ids: tuple[int, int] | None = None
    """Explicit user directive: LLM dialogue is disabled for every pair
    except this ONE fixed core-cast pair, so their exchanges can be much
    deeper (longer lines, real conversational continuity) without the
    call volume every other core-core pair used to cost. Selected by
    `select_voice_pair` (most prominent 2 core-cast members), maintained
    every tick by `maintain_voice_pair` — rotates to the survivor's
    strongest remaining bond if one dies, or picks a fresh pair if both
    do. `due_for_dialogue` excludes this exact pair from the ordinary
    (now LLM-free) dialogue pool; `due_for_voice_dialogue` is their own
    separate, shorter-cooldown scheduling path."""
    voice_conversation: list[dict] = field(default_factory=list)
    """Ring of `{"speaker_id", "text", "tick"}` — the voice pair's own
    running conversation thread (distinct from `dialogue_topics`, which
    only stores a topic WORD, not the actual line), fed back into the
    next call so a reply genuinely continues from what was just said
    rather than re-opening small talk. Capped at MAX_VOICE_CONVERSATION_
    STORED; cleared whenever the pair itself changes (a new partner has
    no business continuing the old thread)."""
    voice_dialogue_last_tick: int = -1_000_000
    """Tick of the voice pair's last exchange — a single scalar cooldown
    (not a dict, since there is only ever one active pair) gating
    `due_for_voice_dialogue`."""
    last_fission_tick: int = -1_000_000
    """Tick of the most recent settlement fission (world-wide) — gates
    FISSION_COOLDOWN_TICKS. Persisted; the far-negative default means a
    fresh or pre-multi-settlement world is immediately eligible once
    the other conditions hold."""
    last_written_records: list[dict] = field(default_factory=list, compare=False)
    """Written-artifact candidates from THIS tick's deaths (`{author,
    memories, belief}` for each dying agent with RECORD_MIN_MEMORIES+
    memories) — computed fresh every tick like last_triggered_agent_ids,
    consumed by SimulationEngine._maybe_schedule_record the same tick,
    never serialized. The record's *existence* is objective (set here,
    synchronously); its text is interpretive, so the LLM (or fallback)
    authors it in the background."""
    last_skill_masteries: list[tuple[int, str]] = field(default_factory=list, compare=False)
    """`(agent_id, skill)` pairs for every `skill_mastered` life event
    THIS tick, in the same order they're appended to `life_events` —
    deferred item 5 (docs/VISION-2026-07-LEARNING.md), "LLM-narrated
    skill mastery": `SimulationEngine`'s life-event log loop pairs each
    `skill_mastered` category entry with the next one of these (by
    position) to resolve which agent/skill it was, without changing the
    project-wide `(category, description)` event-tuple shape. Computed
    fresh every tick, never serialized, same "consumed the same tick"
    shape as `last_written_records`/`last_triggered_agent_ids`."""
    last_triggered_agent_ids: set[int] = field(default_factory=set, compare=False)
    """Agent ids whose circumstances changed sharply enough *this tick*
    to warrant an immediate goal reevaluation rather than waiting for
    their next staggered daily slot — a hunger emergency, or grief at a
    bonded partner's death. Recomputed fresh every tick inside `tick()`
    (see `_apply_deaths`'s grief loop and the critical-hunger check),
    consumed by `SimulationEngine._schedule_due_cognition` the same tick
    it's set, same "computed fresh, never serialized" shape as
    `World.last_life_events`. See docs/DECISIONS.md, "cognition
    triggers beyond daily cadence" pass."""

    def __post_init__(self) -> None:
        """Build the native AgentStore (only when the extension is built)
        and adopt every agent passed in — this covers both construction
        paths, `spawn_initial` and `from_dict`, since both hand a fully
        built `agents` list to `cls(agents=..., ...)`. When the extension
        isn't present, `_store` stays None and agents keep their scalars
        in plain locals, byte-identical to the pre-v0.75.0 dataclass.

        Not a dataclass field: derived, per-process, and must never be
        serialized (the native table can't and shouldn't round-trip
        through JSON — it's rebuilt from the loaded agents here)."""
        self._store = agent_store.AgentStore() if agent_store.native_available() else None
        if self._store is not None:
            for agent in self.agents:
                agent._attach(self._store)

    def _adopt(self, agent: Agent) -> None:
        """Register an agent created *after* construction (a newborn or a
        migrant) with the store, so its scalars live in the same backing
        as everyone else's. No-op in the pure-Python fallback."""
        if self._store is not None:
            agent._attach(self._store)

    # --- construction ------------------------------------------------------

    @classmethod
    def spawn_initial(
        cls, seed: int, count: int, terrain: list[list[Tile]], resources: "ResourceGrid | None" = None,
    ) -> "Population":
        """Founders spawn as a *group near food*, not scattered across
        the map: when `resources` is given, the anchor is the walkable
        tile with the most wild food nodes within FOUNDING_SITE_RADIUS,
        and everyone starts within FOUNDING_CLUSTER_RADIUS of it — the
        site a real founding expedition would have chosen. Scattered
        spawn (the pre-review behavior, kept for the no-resources
        backfill path) was half of the measured early-winter starvation
        funnel: strangers starving alone before ever meeting. See
        docs/DECISIONS.md, "founding funnel" pass."""
        rng = _namespaced_rng(seed, tick=0, namespace="population_init")
        spots = _walkable_tiles(terrain)
        names = generate_names(count, rng)

        if resources is not None and resources.nodes:
            anchor = cls._best_founding_site(spots, resources, rng)
            near = [
                (x, y) for (x, y) in spots
                if max(abs(x - anchor[0]), abs(y - anchor[1])) <= FOUNDING_CLUSTER_RADIUS
            ]
            if near:
                spots = near

        agents: list[Agent] = []
        for i in range(count):
            x, y = rng.choice(spots)
            max_age = rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS)
            genome = seed_founder_genome(rng)
            traits = {trait: (a + b) / 2.0 for trait, (a, b) in genome.items()}
            agents.append(Agent(
                id=i, name=names[i], x=x, y=y, max_age_ticks=max_age, genome=genome, traits=traits,
            ))
        return cls(agents=agents, _next_id=count)

    def spawn_successor_founders(
        self, seed: int, tick: int, count: int, terrain: list[list[Tile]],
        resources: "ResourceGrid | None", settlement_id: int,
    ) -> list["Agent"]:
        """§5 "Ruins mode / successor worlds" (docs/IDEAS-2026-07-
        EMERGENCE.md): `spawn_initial`'s exact site-selection logic
        (cluster near the best local food supply), but appending INTO
        this already-existing (and, at the moment this is called,
        completely extinct) `Population` rather than returning a fresh
        one — preserves cumulative history (`_next_id`, `deaths_*`
        counters, everything) instead of discarding it the way
        `spawn_initial` would. New agents get consecutive ids starting
        at `self._next_id` (so they never collide with a departed
        agent's historical id still referenced in the durable `agent_
        memory_log`/`consciousness_log` tables) and `settlement_id` set
        to the new successor settlement, not the default 0."""
        rng = _namespaced_rng(seed, tick=tick, namespace="successor_founding")
        spots = _walkable_tiles(terrain)
        names = generate_names(count, rng)
        if resources is not None and resources.nodes:
            anchor = self._best_founding_site(spots, resources, rng)
            near = [
                (x, y) for (x, y) in spots
                if max(abs(x - anchor[0]), abs(y - anchor[1])) <= FOUNDING_CLUSTER_RADIUS
            ]
            if near:
                spots = near
        founders: list[Agent] = []
        for i in range(count):
            x, y = rng.choice(spots)
            max_age = rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS)
            genome = seed_founder_genome(rng)
            traits = {trait: (a + b) / 2.0 for trait, (a, b) in genome.items()}
            agent = Agent(
                id=self._next_id, name=names[i], x=x, y=y,
                max_age_ticks=max_age, settlement_id=settlement_id,
                genome=genome, traits=traits,
            )
            self._next_id += 1
            self._adopt(agent)
            self.agents.append(agent)
            founders.append(agent)
        return founders

    @staticmethod
    def _best_founding_site(
        spots: list[tuple[int, int]], resources: "ResourceGrid", rng: random.Random,
    ) -> tuple[int, int]:
        """The walkable tile with the most FOOD-node supply within
        FOUNDING_SITE_RADIUS (ties broken by rng among the best). One-time
        O(walkable x nodes) scan at world creation only."""
        food_nodes = [
            (x, y) for (x, y), node in resources.nodes.items() if node.kind is ResourceKind.FOOD
        ]
        best_score = -1
        best: list[tuple[int, int]] = []
        for sx, sy in spots:
            score = sum(
                1 for (nx, ny) in food_nodes
                if max(abs(nx - sx), abs(ny - sy)) <= FOUNDING_SITE_RADIUS
            )
            if score > best_score:
                best_score, best = score, [(sx, sy)]
            elif score == best_score:
                best.append((sx, sy))
        return rng.choice(best)

    # --- tick ----------------------------------------------------------------

    def tick(
        self, seed: int, tick: int, terrain: list[list[Tile]],
        resources: ResourceGrid, settlements: list[Settlement], farms: FarmGrid, wildlife: WildlifeGrid,
        roads: RoadNetwork, weather: WeatherState, night_factor: float = 0.0,
        heatwave_active: bool = False, month_end: bool = False,
        core_cast_target: int = POPULATION_CRITICAL_THRESHOLD,
        minerals: "MineralGrid | None" = None,
        map_tiles: int | None = None,
        flooded_tiles: "dict | None" = None,
        active_wildfire_tiles: "set | None" = None,
        storm_struck: bool = False,
        outbreak_chance_multiplier: float = 1.0,
        hydrology_moisture: list[list[float]] | None = None,
        ruin_scars: "dict[tuple[int, int], float] | None" = None,
        mining_scars: "dict[tuple[int, int], float] | None" = None,
        disaster_scars: "dict[tuple[int, int], float] | None" = None,
        road_scars: "dict[tuple[int, int], float] | None" = None,
        fields: "FieldGrid | None" = None,
        construction_history: "dict[tuple[int, int], int] | None" = None,
        ownership_history: "dict[tuple[int, int], int] | None" = None,
    ) -> list[tuple[str, str]]:
        """Advance every agent by one tick: needs, foraging, movement,
        relationships, construction/repair, farming, birth, and death.
        Returns life events as (category, description) pairs for the
        caller to log."""
        rng = _namespaced_rng(seed, tick=tick, namespace="population_tick")
        # Snapshot positions before anyone moves this tick, so goal-directed
        # search (SOCIALIZE) sees a consistent picture rather than a mix of
        # this-tick-already-moved and not-yet-moved agents.
        position_snapshot = [(a.id, a.x, a.y) for a in self.agents]
        # Start-of-tick occupancy, keyed like `by_position` (populated
        # fresh, post-move, later in this same method) but available
        # early enough for `damaged_building_positions`' staffing filter
        # below — one tick stale, same acceptable staleness every other
        # once-per-tick attractor list here already has.
        agents_by_id = {a.id: a for a in self.agents}
        start_of_tick_by_position: dict[tuple[int, int], list[Agent]] = {}
        for agent_id, x, y in position_snapshot:
            start_of_tick_by_position.setdefault((x, y), []).append(agents_by_id[agent_id])
        # Native fast path for SOCIALIZE's _nearest_other_agent (module 4,
        # cpp/src/agent_position_index.cpp): built once from the same
        # snapshot/order the pure-Python scan uses, so tie-breaking stays
        # identical. This is the highest-value remaining native-port
        # candidate — SOCIALIZE has no distance cap, so the pure-Python
        # path is a real O(population) scan per agent, O(population^2)
        # across a tick.
        agent_position_index = None
        if _NativeAgentPositionIndex is not None:
            agent_position_index = _NativeAgentPositionIndex(position_snapshot)
        # Rival positions, computed once for the whole tick: one pass over
        # each agent's (usually short) relationships dict, instead of the
        # previous per-agent scan of the full position snapshot inside
        # _dispatch_movement — that scan was O(N^2) per tick and measured
        # at ~40% of population-tick time at 200 agents (July 2026
        # architecture review, §6.1). Most agents have no rivals at all
        # (rivalry needs repeated tense dialogue), so this is near-free
        # in the common case.
        position_by_id = {a.id: (a.x, a.y) for a in self.agents}
        rival_tiles_by_agent: dict[int, set[tuple[int, int]]] = {}
        for a in self.agents:
            if not a.relationships:
                continue
            tiles = {
                position_by_id[other_id]
                for other_id, value in a.relationships.items()
                if value <= RIVALRY_THRESHOLD and other_id in position_by_id
            }
            if tiles:
                rival_tiles_by_agent[a.id] = tiles
        predator_tiles = wildlife.predator_tiles()
        weather_harsh = (
            weather.precipitation > WEATHER_HARSH_PRECIPITATION
            or weather.wind > WEATHER_HARSH_WIND or weather.is_snowing or heatwave_active
        )

        life_events: list[tuple[str, str]] = []
        killed_by_predator: set[int] = set()
        by_position: dict[tuple[int, int], list[Agent]] = {}
        any_gather_occurred = False
        # §1 "deviance loop": computed once per tick (typically empty —
        # ostracism is rare), reused by every SOCIALIZE-goal agent's
        # movement dispatch below.
        ostracized_ids = frozenset(a.id for a in self.agents if a.standing_penalty > 0.0)
        # --- multi-settlement partition (v0.65.0) ------------------------
        # One shared physical world, N home communities: spatial systems
        # (movement, colocation, trade, dialogue, disease spread) stay
        # global — people of different settlements still meet, talk,
        # trade, teach, and infect each other when colocated. Ownership
        # systems (granaries/stockpiles, construction, institutions,
        # carrying capacity) resolve through each agent's home
        # settlement. See docs/DECISIONS.md, "multiple named
        # settlements."
        primary = settlements[0]
        settlements_by_id = {s.id: s for s in settlements}

        def home_of(a: Agent) -> Settlement:
            return settlements_by_id.get(a.settlement_id, primary)

        members_count: dict[int, int] = {s.id: 0 for s in settlements}
        for a in self.agents:
            members_count[home_of(a).id] += 1
        has_hospital_by_id = {
            s.id: any(
                b.kind is BuildingKind.HOSPITAL and b.stage is BuildingStage.STANDING
                for b in s.buildings
            )
            for s in settlements
        }
        housing_by_id = {
            s.id: CAMP_TOLERANCE + HUT_CAPACITY * hut_capacity_multiplier(s.era) * sum(
                1 for b in s.buildings
                if b.kind is BuildingKind.HUT and b.stage is BuildingStage.STANDING
            )
            for s in settlements
        }
        crowded_by_id = {s.id: members_count[s.id] > housing_by_id[s.id] for s in settlements}
        crowded = any(crowded_by_id.values())
        # Built once per tick, shared by every GATHER-seeking agent's
        # `_nearest_material_tile` call — same "compute once, amortize
        # across agents" shape as `farm_positions`/`granary_positions`
        # below, and as `ResourceGrid`'s `_native_index` (see world/
        # resources.py). Terrain biomes never change mid-tick (only
        # weekly/monthly terrain evolution touches them), so unlike
        # ResourceIndex this needs no live-patch — a fresh once-per-tick
        # rebuild is already exactly equivalent to the pure-Python scan.
        material_index = None
        if _NativeTerrainMaterialIndex is not None:
            material_index = _NativeTerrainMaterialIndex([
                (tile.x, tile.y)
                for row in terrain for tile in row
                if tile.biome in MATERIAL_BIOMES
            ])
        # Built once per tick (values never change mid-tick), shared by
        # every agent's `_update_needs` call — module 6 of the native
        # port, and the first from the "full engine rewrite" track: this
        # runs unconditionally every tick for every agent, unlike the
        # goal-gated lookups modules 1-5 ported. Passed as parameters
        # rather than duplicated as C++ literals since these constants
        # live in three different files with no single home — see
        # cpp/src/needs.cpp.
        needs_constants = None
        if _NativeNeedsConstants is not None:
            needs_constants = _NativeNeedsConstants()
            needs_constants.hunger_rate = HUNGER_RATE
            needs_constants.energy_drain_awake = ENERGY_DRAIN_AWAKE
            needs_constants.sickness_hunger_mult = SICKNESS_HUNGER_RATE_MULTIPLIER
            needs_constants.sickness_energy_mult = SICKNESS_ENERGY_DRAIN_MULTIPLIER
            needs_constants.weather_hunger_mult = WEATHER_HARSH_HUNGER_MULTIPLIER
            needs_constants.weather_energy_mult = WEATHER_HARSH_ENERGY_DRAIN_MULTIPLIER
            needs_constants.crowding_energy_mult = CROWDING_ENERGY_MULTIPLIER
            needs_constants.night_energy_extra = NIGHT_ENERGY_DRAIN_EXTRA
            needs_constants.rest_threshold = REST_THRESHOLD
            needs_constants.night_rest_threshold_boost = NIGHT_REST_THRESHOLD_BOOST
            needs_constants.energy_recovery_resting = ENERGY_RECOVERY_RESTING
            needs_constants.night_rest_recovery_bonus = NIGHT_REST_RECOVERY_BONUS
            needs_constants.elder_recovery_mult = ELDER_RECOVERY_MULTIPLIER
            needs_constants.hospital_rest_recovery_mult = HOSPITAL_REST_RECOVERY_MULTIPLIER
            needs_constants.wake_threshold = WAKE_THRESHOLD
        farm_positions = self.ready_farm_positions(farms)
        granary_positions_by_id = {s.id: self.stocked_granary_positions(s) for s in settlements}
        work_positions_by_id = {
            s.id: (
                self.damaged_building_positions(s, start_of_tick_by_position) + self.under_construction_positions(s)
                + self.husbandry_positions(s) + self.granary_positions(s)
            )
            for s in settlements
        }
        # Every STANDING bridge's spanned water tiles, pooled once per
        # tick across every settlement (bridges are shared physical
        # infrastructure, not settlement-private) — see BuildingKind.
        # BRIDGE / _bridge_tiles_from_settlements.
        bridge_tiles = _bridge_tiles_from_settlements(settlements)
        self.last_triggered_agent_ids = set()
        self.last_written_records = []
        self.last_skill_masteries = []
        for agent in self.agents:
            home = home_of(agent)
            agent.age_ticks += 1
            self._update_needs(
                agent, weather_harsh, settlements, night_factor, crowded_by_id[home.id], needs_constants,
            )
            decay_emotions(agent)
            decay_debts(agent)
            critically_hungry = agent.hunger >= CRITICAL_HUNGER_THRESHOLD
            if critically_hungry:
                # Fear of one's own starvation, distinct from the fear a
                # predator attack or someone else's death produces below —
                # see EMOTION_STARVATION_FEAR_BUMP. Bumped every tick the
                # condition holds at a fraction of the full bump (decay_
                # emotions above already ran this tick, so this doesn't get
                # immediately erased) — repeated ticks compound toward the
                # 1.0 ceiling, so a sustained crisis reads as worse than a
                # momentary one.
                bump_emotion(agent, EMOTION_FEAR, EMOTION_STARVATION_FEAR_BUMP * 0.1)
            if critically_hungry:
                # A hunger emergency deserves the LLM's actual reasoning
                # (a real goal + rationale), not just the movement-layer
                # override _dispatch_movement already forces regardless
                # of assigned goal — see due_for_triggered_cognition.
                self.last_triggered_agent_ids.add(agent.id)
            if critically_hungry and agent.state is AgentState.RESTING:
                agent.state = AgentState.AWAKE  # emergency wake: starving beats sleeping
            self._maybe_forage(
                agent, resources, farms, settlements, wildlife, life_events,
                skill_masteries=self.last_skill_masteries,
            )  # can eat while resting, not just awake
            if self._maybe_gather(agent, terrain, home, resources, minerals):
                any_gather_occurred = True
            if agent.hunger >= STARVATION_HUNGER_THRESHOLD:
                agent.starving_ticks += 1
                if agent.starving_ticks == 1:
                    # H6: the onset of a hunger crisis, not every tick
                    # spent in one — see TRAIT_SUSTAINED_HUNGER_NUDGE.
                    _nudge_trait(agent, TRAIT_RESILIENCE, TRAIT_SUSTAINED_HUNGER_NUDGE)
            else:
                agent.starving_ticks = 0
            if (
                agent.state is AgentState.AWAKE and agent.goal is AgentGoal.REST
                and agent.energy < 0.95 and not critically_hungry
            ):
                agent.state = AgentState.RESTING  # proactive rest: a chosen goal, not just necessity
            if agent.state is AgentState.AWAKE:
                attack_event = self._maybe_predator_attack(
                    agent, wildlife, rng, has_hospital_by_id[home.id], home.temperament,
                    predator_tiles=predator_tiles,
                )
                if attack_event is not None:
                    life_events.append(attack_event[0])
                    if attack_event[1]:
                        killed_by_predator.add(agent.id)
                    else:
                        _nudge_trait(agent, TRAIT_RESILIENCE, TRAIT_VIOLENCE_NUDGE)
                        bump_emotion(agent, EMOTION_FEAR, EMOTION_PREDATOR_FEAR_BUMP)
                self._dispatch_movement(
                    agent, terrain, rng, resources, farms, home, wildlife, roads,
                    predator_tiles, position_snapshot, critically_hungry, weather,
                    rival_tiles=rival_tiles_by_agent.get(agent.id),
                    food_positions=(farm_positions, granary_positions_by_id[home.id]),
                    work_positions=work_positions_by_id[home.id],
                    material_index=material_index,
                    agent_position_index=agent_position_index,
                    bridge_tiles=bridge_tiles,
                    ostracized_ids=ostracized_ids,
                )
                if agent.occupation == OCCUPATION_SURVEYOR:
                    life_events.extend(self._mark_explored(agent, home, terrain, resources, minerals, settlements, tick))
            by_position.setdefault((agent.x, agent.y), []).append(agent)

        life_events.extend(self._update_roads(by_position, settlements, farms, roads, road_scars))
        self._update_relationships(by_position)
        self._maybe_teach_skills(by_position, rng, settlements)
        self._maybe_commit_theft(by_position, rng, settlements, life_events)
        life_events.extend(self._maybe_migrate(rng, settlements))
        if month_end:
            self._tick_traits(rng)
        hospital_settlement_ids = {sid for sid, has in has_hospital_by_id.items() if has}
        # A14 "Layered organism biology," sixth and final slice: sleep
        # debt drifts from the same just-updated energy reading, BEFORE
        # immune_strength ticks below (which now reads it as a further
        # chronic drag on top of its own momentary energy pull).
        self._tick_sleep_debt(self.agents)
        # A14 "Layered organism biology," first slice (roadmap Stage IV
        # step 23): immune state drifts from real current nutrition/
        # rest before disease resolves this tick, so a just-updated
        # hunger/energy reading (from _update_needs above) is what
        # feeds it, not a stale value from last tick.
        self._tick_immune_strength(self.agents)
        # A14 "Layered organism biology," second slice: stress reads the
        # same just-updated emotions/hunger/sick_ticks state.
        self._tick_stress(self.agents)
        # A14 "Layered organism biology," third slice: injury heals
        # from the same just-updated hunger/energy state.
        self._tick_injury_recovery(self.agents)
        # A14 "Layered organism biology," fourth slice: development
        # grows from the same just-updated hunger state.
        self._tick_development(self.agents)
        disease_events, died_of_disease = self._tick_disease(
            self.agents, by_position, hospital_settlement_ids, primary.temperament, rng, tick,
        )
        life_events.extend(disease_events)
        map_size = (len(terrain[0]), len(terrain)) if terrain else None
        life_events.extend(self._maybe_outbreak(
            rng, crowded, roads, outbreak_chance_multiplier, fields=fields, map_size=map_size,
        ))
        # Building-driven subsystems run once per settlement over the
        # global colocation map: each settlement's own structures get
        # worked/stocked/crafted-at by whoever is physically present —
        # a visiting neighbor genuinely can help raise a wall or study
        # at the other village's school.
        members_by_settlement: dict[int, list[Agent]] = {s.id: [] for s in settlements}
        for a in self.agents:
            members_by_settlement.get(home_of(a).id, members_by_settlement[primary.id]).append(a)
        for stl in settlements:
            self._maybe_assign_occupations(stl, members_by_settlement[stl.id])
            life_events.extend(self._advance_construction(by_position, stl, self.last_skill_masteries))
            life_events.extend(self._maybe_repair(by_position, stl))
            self._maybe_stock_granaries(by_position, stl)
            self._maybe_run_husbandry(by_position, stl)
            self._maybe_run_workshops(by_position, stl)
            self._maybe_craft_tools(by_position, stl)
            self._maybe_craft_medicine(by_position, stl)
            self._maybe_run_factories(by_position, stl)
            self._maybe_run_docks(by_position, stl)
            self._maybe_run_oil_rigs(by_position, stl)
            self._maybe_run_forges(by_position, stl)
            self._maybe_run_market_workers(by_position, stl)
            self._maybe_run_schools(by_position, stl)
            life_events.extend(self._maybe_upgrade_university(by_position, stl, rng))
            life_events.extend(self._advance_vehicle_construction(by_position, stl))
            self._maybe_repair_vehicles(by_position, stl)
            self._maybe_assign_mounts(by_position, stl)
            if any_gather_occurred:
                self._wear_carts(stl)
            life_events.extend(self._maybe_start_vehicle(by_position, stl, farms, rng, terrain))
            life_events.extend(self._maybe_start_bridge(by_position, stl, farms, rng, terrain))
        self._maybe_trade_food(by_position, rng)
        self._maybe_trade_tools(by_position, rng)
        self._maybe_trade_medicine(by_position, rng)
        life_events.extend(
            self._maybe_start_construction(
                by_position, settlements, farms, rng, roads, resources, terrain, ruin_scars=ruin_scars,
                mining_scars=mining_scars, disaster_scars=disaster_scars, road_scars=road_scars,
                construction_history=construction_history,
            )
        )
        life_events.extend(
            self._maybe_plant(by_position, farms, settlements, terrain, rng, hydrology_moisture, fields)
        )
        established_roads = roads.summary()["established_roads"]
        capacity_by_id = {
            s.id: self.carrying_capacity(
                s, housing_by_id[s.id], weather_harsh, bool(predator_tiles),
                established_roads=established_roads,
                members=[a for a in self.agents if home_of(a).id == s.id],
                map_tiles=map_tiles,
            )
            for s in settlements
        }
        self.last_carrying_capacity = sum(capacity_by_id.values())
        life_events.extend(
            self._maybe_reproduce(by_position, rng, capacity_by_id, settlements, tick)
        )
        life_events.extend(
            self._apply_deaths(
                killed_by_predator, settlements, died_of_disease, tick=tick, rng=rng,
                ownership_history=ownership_history,
            )
        )
        self._tick_mourning()
        self._tick_weddings()
        region_density = None
        region_scarcity = None
        region_ownership = None
        region_heat = None
        region_cultural_influence = None
        region_beauty = None
        region_wildlife = None
        if fields is not None and terrain:
            region_density = fields.get_at(
                "population_density", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
            region_scarcity = fields.get_at(
                "scarcity", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
            region_ownership = fields.get_at(
                "ownership", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
            region_heat = fields.get_at(
                "heat", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
            region_cultural_influence = fields.get_at(
                "cultural_influence", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
            region_beauty = fields.get_at(
                "beauty", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
            region_wildlife = fields.get_at(
                "wildlife", (primary.center_x, primary.center_y), len(terrain[0]), len(terrain),
            )
        life_events.extend(
            self._maybe_welcome_migrant(
                rng, primary, core_cast_target, terrain,
                region_density, region_scarcity, region_ownership, region_heat, region_cultural_influence,
                region_beauty, region_wildlife,
            )
        )
        for stl in settlements:
            members = [a for a in self.agents if home_of(a).id == stl.id]
            life_events.extend(self._maybe_form_council(stl, tick, members))
            life_events.extend(self._maybe_refresh_council(stl, tick, members))
            life_events.extend(self._maybe_form_guild(stl, tick, members))
            life_events.extend(self._maybe_refresh_guild(stl, members))
        self._mark_disaster_survivors(
            start_of_tick_by_position, flooded_tiles, active_wildfire_tiles, storm_struck, position_by_id,
        )
        return life_events

    def _mark_disaster_survivors(
        self,
        start_of_tick_by_position: dict[tuple[int, int], list[Agent]],
        flooded_tiles: "dict | None",
        active_wildfire_tiles: "set | None",
        storm_struck: bool,
        start_positions_by_id: dict[int, tuple[int, int]],
    ) -> None:
        """Phase 1.D (Nature->Human): an agent standing on a flooded or
        actively-burning tile this tick gets a genuinely lasting mark —
        a causally-tagged memory (via `_remember(..., because=...)`,
        which graduates it into the small permanent `core_memories` tier
        instead of vanishing once it's eventually evicted from the
        regular memory list) and a sharp `EMOTION_FEAR` spike, plus a
        one-time bond with anyone else who survived the same tile
        alongside them (DISASTER_SURVIVOR_BOND_BUMP).

        Storm has no per-tile tracking on `DisasterState` (`tick_storm`
        damages every settlement uniformly the instant it fires) — every
        AWAKE agent gets the same, smaller mark instead of a tile-scoped
        one when `storm_struck` is True.

        A nearby AWAKE bystander who moved measurably closer to a
        flood/wildfire tile this same tick (real, observable behavior —
        `start_positions_by_id` vs. the agent's post-movement position,
        not a fabricated "could have helped" judgment) counts as a
        genuine helper: a smaller bond with the survivors there, and
        their own memory of it. This is the honest half of the vision
        doc's helper/non-helper framing; a grievance against agents who
        were merely nearby and did nothing is still NOT implemented —
        the engine has no way to know a bystander was even aware of the
        disaster, so asserting they "could have helped" would be
        fabricated, not observed."""
        disaster_tiles: dict[tuple[int, int], str] = {}
        if flooded_tiles:
            for pos in flooded_tiles:
                disaster_tiles[pos] = "flood"
        if active_wildfire_tiles:
            for pos in active_wildfire_tiles:
                disaster_tiles[pos] = "wildfire"
        all_survivor_ids: set[int] = set()
        for pos, kind in disaster_tiles.items():
            survivors = start_of_tick_by_position.get(pos)
            if not survivors:
                continue
            all_survivor_ids.update(a.id for a in survivors)
            for agent in survivors:
                bump_emotion(agent, EMOTION_FEAR, EMOTION_DISASTER_FEAR_BUMP)
                _remember(
                    agent,
                    f"Survived a {kind} that struck right where I was standing.",
                    because=f"survived a {kind}",
                )
                # Phase 3.B "identity, irreversible change": surviving a
                # disaster is one of the vision doc's three named
                # extreme-event triggers for a permanent trait shift.
                _maybe_harden_trait(agent)
            for i, a in enumerate(survivors):
                for b in survivors[i + 1:]:
                    a.relationships[b.id] = min(1.0, a.relationships.get(b.id, 0.0) + DISASTER_SURVIVOR_BOND_BUMP)
                    b.relationships[a.id] = min(1.0, b.relationships.get(a.id, 0.0) + DISASTER_SURVIVOR_BOND_BUMP)
            for bystander in self.agents:
                if bystander.id in all_survivor_ids or bystander.state is not AgentState.AWAKE:
                    continue
                start_pos = start_positions_by_id.get(bystander.id)
                if start_pos is None:
                    continue
                start_dist = max(abs(start_pos[0] - pos[0]), abs(start_pos[1] - pos[1]))
                now_dist = max(abs(bystander.x - pos[0]), abs(bystander.y - pos[1]))
                if now_dist >= start_dist or now_dist > DISASTER_HELPER_RADIUS:
                    continue
                for agent in survivors:
                    agent.relationships[bystander.id] = min(
                        1.0, agent.relationships.get(bystander.id, 0.0) + DISASTER_HELPER_BOND_BUMP
                    )
                    bystander.relationships[agent.id] = min(
                        1.0, bystander.relationships.get(agent.id, 0.0) + DISASTER_HELPER_BOND_BUMP
                    )
                _remember(bystander, f"Rushed toward the {kind} to help.", because=f"helped during a {kind}")
        if storm_struck:
            for agent in self.agents:
                if agent.state is not AgentState.AWAKE or agent.id in all_survivor_ids:
                    continue
                bump_emotion(agent, EMOTION_FEAR, EMOTION_STORM_FEAR_BUMP)
                _remember(agent, "A violent storm tore through the settlement.", because="survived a storm")

    @staticmethod
    def _update_needs(
        agent: Agent, weather_harsh: bool = False, settlements: list[Settlement] | None = None,
        night_factor: float = 0.0, crowded: bool = False, needs_constants: "object | None" = None,
    ) -> None:
        # Shelter/care are physical: standing inside ANY settlement's
        # building counts, whoever owns it — a traveler sheltering in
        # the neighboring village's granary is dry all the same.
        building = None
        if settlements:
            for stl in settlements:
                building = stl.at(agent.x, agent.y)
                if building is not None:
                    break
        standing = building is not None and building.stage is BuildingStage.STANDING

        if needs_constants is not None:
            # Native fast path (module 6, cpp/src/needs.cpp): every
            # object-shaped lookup (which building, whether it's a
            # standing hospital, elder-age comparison) is resolved here
            # in Python first — the native function only does the
            # arithmetic on the already-resolved scalars/booleans.
            result = _native_update_needs(
                needs_constants,
                agent.hunger, agent.energy, agent.state is AgentState.RESTING,
                agent.sick_ticks > 0, weather_harsh,
                SHELTER_NEGATES_WEATHER and standing,
                crowded, night_factor,
                agent.age_ticks >= agent.max_age_ticks * ELDER_AGE_FRACTION,
                standing and building.kind is BuildingKind.HOSPITAL,
            )
            agent.hunger = result.hunger
            agent.energy = result.energy
            agent.state = AgentState.RESTING if result.resting else AgentState.AWAKE
            return

        hunger_rate = HUNGER_RATE
        energy_drain = ENERGY_DRAIN_AWAKE
        if agent.sick_ticks > 0:
            # Illness has a real mechanical cost, not just a status flag —
            # see SICKNESS_ENERGY_DRAIN_MULTIPLIER/SICKNESS_HUNGER_RATE_
            # MULTIPLIER, Population._tick_disease.
            hunger_rate *= SICKNESS_HUNGER_RATE_MULTIPLIER
            energy_drain *= SICKNESS_ENERGY_DRAIN_MULTIPLIER
        if weather_harsh and agent.state is AgentState.AWAKE:
            # "Weather affects people": harsh weather (heavy rain/snow/high
            # wind/an active heatwave) costs an awake agent more — resting
            # is treated as sheltering, so it's unaffected — and as of the
            # shelter pass, so is standing on any STANDING building's tile
            # (working indoors). See SHELTER_NEGATES_WEATHER,
            # docs/DECISIONS.md, scarcity pass + review-implementation
            # follow-up.
            sheltered = SHELTER_NEGATES_WEATHER and standing
            if not sheltered:
                hunger_rate *= WEATHER_HARSH_HUNGER_MULTIPLIER
                energy_drain *= WEATHER_HARSH_ENERGY_DRAIN_MULTIPLIER
        if crowded and agent.state is AgentState.AWAKE:
            # More people than roofs: rough nights wear everyone down a
            # little — see CROWDING_ENERGY_MULTIPLIER/HUT_CAPACITY.
            energy_drain *= CROWDING_ENERGY_MULTIPLIER
        if agent.state is AgentState.AWAKE:
            # Real UK daylight hours, not just a visual tint: staying up
            # through the dark costs more energy, scaling with how deep
            # into the night it is. See NIGHT_ENERGY_DRAIN_EXTRA.
            energy_drain *= 1.0 + night_factor * NIGHT_ENERGY_DRAIN_EXTRA
        agent.hunger = min(1.0, agent.hunger + hunger_rate)
        rest_threshold = REST_THRESHOLD + night_factor * NIGHT_REST_THRESHOLD_BOOST
        if agent.state is AgentState.RESTING:
            recovery = ENERGY_RECOVERY_RESTING * (1.0 + night_factor * NIGHT_REST_RECOVERY_BONUS)
            if agent.age_ticks >= agent.max_age_ticks * ELDER_AGE_FRACTION:
                # Age-graded frailty: elders recover slower — see
                # ELDER_RECOVERY_MULTIPLIER in agents/agent.py.
                recovery *= ELDER_RECOVERY_MULTIPLIER
            if standing and building.kind is BuildingKind.HOSPITAL:
                # Care exists: resting at a standing hospital recovers
                # energy faster. See HOSPITAL_REST_RECOVERY_MULTIPLIER,
                # docs/DECISIONS.md, "LLM-as-brain batch."
                recovery *= HOSPITAL_REST_RECOVERY_MULTIPLIER
            agent.energy = min(1.0, agent.energy + recovery)
            if agent.energy >= WAKE_THRESHOLD:
                agent.state = AgentState.AWAKE
        else:
            agent.energy = max(0.0, agent.energy - energy_drain)
            if agent.energy <= rest_threshold:
                agent.state = AgentState.RESTING

    @staticmethod
    def _maybe_predator_attack(
        agent: Agent, wildlife: WildlifeGrid, rng: random.Random, has_hospital: bool = False,
        temperament: float = 0.0, predator_tiles: set[tuple[int, int]] | None = None,
    ) -> tuple[tuple[str, str], bool] | None:
        """Rolled for an awake agent colocated with a live predator pack.
        Returns ((category, description), killed) or None if no attack
        happened this tick. `has_hospital` (any standing hospital,
        settlement-wide — medical readiness, not proximity) reduces the
        lethal-outcome odds. `temperament` (Settlement.temperament,
        -1..1) applies a small, deliberately subtle further nudge — see
        TEMPERAMENT_KILL_CHANCE_INFLUENCE, docs/DECISIONS.md, "World-G
        follow-up.\" See also docs/DECISIONS.md, danger pass and
        "LLM-as-brain batch.\""""
        # Cheap early-out against the tick's precomputed predator-tile set
        # (audit perf pass): `wildlife.at()` scans every herd, and this
        # runs for every awake agent every tick — almost all of whom are
        # nowhere near a predator. The set membership test answers the
        # common case without the scan.
        if predator_tiles is not None and (agent.x, agent.y) not in predator_tiles:
            return None
        predators = [h for h in wildlife.at(agent.x, agent.y) if h.species is Species.PREDATOR and h.count > 0]
        if not predators:
            return None
        if rng.random() >= PREDATOR_ATTACK_CHANCE:
            return None
        # Integration milestone: the agent's own resilience gets a say
        # too, alongside the settlement-wide temperament nudge — see
        # TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE.
        resilience = agent.traits.get(TRAIT_RESILIENCE, 0.0)
        if _native_predator_kill_chance is not None:
            # Native fast path (module 7): pure math only — this call
            # consumes no RNG, so it can't disturb the two rng.random()
            # rolls' order in this function.
            kill_chance = _native_predator_kill_chance(
                PREDATOR_KILL_CHANCE_ON_ATTACK, has_hospital, HOSPITAL_KILL_CHANCE_REDUCTION,
                temperament, TEMPERAMENT_KILL_CHANCE_INFLUENCE,
                resilience, TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE,
            )
        else:
            kill_chance = PREDATOR_KILL_CHANCE_ON_ATTACK
            if has_hospital:
                kill_chance *= (1.0 - HOSPITAL_KILL_CHANCE_REDUCTION)
            kill_chance = max(0.0, kill_chance * (1.0 - temperament * TEMPERAMENT_KILL_CHANCE_INFLUENCE))
            kill_chance = max(0.0, kill_chance * (1.0 - resilience * TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE))
        # A14 "Layered organism biology," third slice: an already-
        # injured agent surviving a FURTHER attack is measurably more
        # likely to die from it — applied in pure Python after the
        # native-or-fallback kill_chance above, zero native/fallback
        # parity risk. See INJURY_VULNERABILITY_WEIGHT's docstring.
        if agent.injury > 0.0:
            kill_chance = min(
                1.0, kill_chance * min(
                    INJURY_VULNERABILITY_MAX_FACTOR, 1.0 + agent.injury * INJURY_VULNERABILITY_WEIGHT,
                ),
            )
        if rng.random() < kill_chance:
            return (("death", f"{agent.name} was killed by predators."), True)
        agent.energy = max(0.0, agent.energy - PREDATOR_ATTACK_ENERGY_DRAIN)
        agent.hunger = min(1.0, agent.hunger + PREDATOR_ATTACK_HUNGER_INCREASE)
        agent.injury = min(1.0, agent.injury + PREDATOR_ATTACK_INJURY)
        return (("predator_attack", f"{agent.name} was attacked by predators and barely escaped."), False)

    def _maybe_outbreak(
        self, rng: random.Random, crowded: bool, roads: RoadNetwork | None = None,
        chance_multiplier: float = 1.0,
        fields: "FieldGrid | None" = None, map_size: tuple[int, int] | None = None,
    ) -> list[tuple[str, str]]:
        """Rolled once per tick, settlement-wide: a small chance a new,
        spontaneous case of illness appears among the currently-healthy
        population — the *origin* of a bout. Scaled by population size
        and boosted under crowding (OUTBREAK_CROWDING_MULTIPLIER), same
        housing-pressure signal Population.tick already computes for
        CROWDING_ENERGY_MULTIPLIER — a settlement growing past its
        housing capacity draws real disease risk, not just tighter
        quarters. Person-to-person spread from this index case is
        handled separately by `_tick_disease`. See docs/DECISIONS.md,
        "population control: disease" pass.

        Integration milestone: also boosted by the fraction of the
        population currently standing on an established road tile —
        infrastructure that connects people is, realistically, also
        infrastructure that spreads a cold. Same double-edged framing
        roads already get in `carrying_capacity` (infrastructure helps
        overall, but this is the one place it has a real cost).

        v2: a recently-recovered agent (`immune_ticks > 0`) can't become
        a fresh index case either — same temporary-resistance window
        `_tick_disease` already exempts from person-to-person spread.

        `chance_multiplier` (B6, roadmap Stage III step 13): `World.
        governor_tuning.get("disease_outbreak_chance", 1.0)` — Reflection's
        self-tuning worked example for a settlement-scoped governor, see
        `llm/self_tuning.py`'s `TUNABLE_GOVERNORS` docstring. Applied to
        the base chance only, before the floor below — the floor exists
        to guarantee a small settlement's first case isn't invisible and
        should stay a real guarantee regardless of any governor nudge.

        A1/A2 (docs/ROADMAP-2026-07-REMAINING.md Tier 1 items 3-4): once
        `fields`/`map_size` are given, WHICH healthy agent becomes the
        index case is weighted by their own region's `disease_pressure`
        (`World.fields`, written last tick by `FieldGrid.step_disease_
        pressure` — one-tick stale, same accepted staleness `population_
        density`'s own consumer already has) instead of a flat uniform
        draw — a region bordering a real outbreak is measurably more
        likely to seed the NEXT spontaneous case than one nowhere near
        any sickness, without ever making it a certainty (every healthy
        agent keeps a real floor weight)."""
        healthy = [a for a in self.agents if a.sick_ticks == 0 and a.immune_ticks == 0]
        if not healthy:
            return []
        chance = OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK * len(self.agents) * chance_multiplier
        if crowded:
            chance *= OUTBREAK_CROWDING_MULTIPLIER
        if roads is not None and self.agents:
            on_road_fraction = sum(1 for a in self.agents if roads.is_road(a.x, a.y)) / len(self.agents)
            chance *= 1.0 + on_road_fraction * OUTBREAK_ROAD_CONTACT_MULTIPLIER
        # P2.2: the flat floor's job (guarantee a small settlement's
        # first case isn't invisible for the whole early game) is done
        # once illness has actually appeared — don't let it keep
        # reseeding fresh index cases on top of an already-sick
        # population (see OUTBREAK_FLOOR_SICK_FRACTION_CAP's docstring).
        sick_fraction = 1.0 - (len(healthy) / len(self.agents)) if self.agents else 0.0
        if sick_fraction <= OUTBREAK_FLOOR_SICK_FRACTION_CAP:
            chance = max(chance, OUTBREAK_MIN_CHANCE_PER_TICK)
        if rng.random() >= chance:
            return []
        if fields is not None and map_size is not None:
            width, height = map_size
            weights = [
                1.0 + fields.get_at("disease_pressure", (a.x, a.y), width, height) * OUTBREAK_DISEASE_PRESSURE_WEIGHT
                for a in healthy
            ]
            index_case = rng.choices(healthy, weights=weights, k=1)[0]
        else:
            index_case = rng.choice(healthy)
        index_case.sick_ticks = 1
        bump_emotion(index_case, EMOTION_FEAR, EMOTION_ILLNESS_FEAR_BUMP)
        return [("illness", f"{index_case.name} has fallen ill.")]

    @staticmethod
    def _tick_sleep_debt(agents: list[Agent]) -> None:
        """A14 "Layered organism biology," sixth and final slice
        (roadmap Tier 1 item 8): drifts every agent's continuous
        `sleep_debt` toward `1.0 - energy` via exponential smoothing at
        `SLEEP_DEBT_ADAPT_RATE` — deliberately much slower than
        `IMMUNE_ADAPT_RATE`, so this tracks a CHRONIC rest deficit
        across many ticks, not the same-tick tiredness `energy` already
        captures on its own. Pure Python, O(agents), same cost class as
        `_tick_immune_strength`."""
        for agent in agents:
            target = clamp(1.0 - agent.energy, 0.0, 1.0)
            agent.sleep_debt += (target - agent.sleep_debt) * SLEEP_DEBT_ADAPT_RATE
            agent.sleep_debt = clamp(agent.sleep_debt, 0.0, 1.0)

    @staticmethod
    def _tick_immune_strength(agents: list[Agent]) -> None:
        """A14 "Layered organism biology," first slice (roadmap Stage IV
        step 23): drifts every agent's continuous `immune_strength`
        toward a target derived from their CURRENT hunger/energy —
        the real metabolism/nutrition -> immune coupling — via
        exponential smoothing (`IMMUNE_ADAPT_RATE`), then applies a
        small extra drain if they're actively sick (the reverse
        coupling: fighting infection taxes immune reserve). Also
        drags the target down by their chronic `sleep_debt` (A14's
        sixth slice) — a distinct, slower-resolving signal from the
        momentary rest_pull below. Pure Python, reads/writes only the
        plain (non-native-store-backed) `immune_strength`/`hunger`/
        `energy`/`sick_ticks`/`sleep_debt` attributes — runs every
        tick, O(agents), same cost class as the trait/emotion decay
        passes elsewhere in this file."""
        for agent in agents:
            # hunger/energy are already 0..1 with 0.5 as their own
            # natural midpoint reading — center each around that so a
            # merely-average agent's target sits exactly at baseline.
            nutrition_pull = (0.5 - agent.hunger) * 2.0 * IMMUNE_HUNGER_WEIGHT
            rest_pull = (agent.energy - 0.5) * 2.0 * IMMUNE_ENERGY_WEIGHT
            sleep_drag = agent.sleep_debt * SLEEP_DEBT_IMMUNE_WEIGHT
            target = clamp(IMMUNE_BASELINE + nutrition_pull + rest_pull - sleep_drag, 0.0, 1.0)
            agent.immune_strength += (target - agent.immune_strength) * IMMUNE_ADAPT_RATE
            if agent.sick_ticks > 0:
                agent.immune_strength -= SICKNESS_IMMUNE_DRAIN_PER_TICK
            agent.immune_strength = clamp(agent.immune_strength, IMMUNE_STRENGTH_FLOOR, 1.0)

    @staticmethod
    def _tick_stress(agents: list[Agent]) -> None:
        """A14 "Layered organism biology," second slice (roadmap Tier 1
        item 8): drifts every agent's continuous `stress` toward a
        target built from real, already-tracked acute-threat signals —
        current fear/grief emotions, a hunger crisis
        (`CRITICAL_HUNGER_THRESHOLD`), active illness (`sick_ticks`),
        and a hardened feud (`relationship_flags`) — via exponential
        smoothing (`STRESS_ADAPT_RATE`). Pure Python, reads only plain
        (non-native-store-backed) attributes — O(agents), same cost
        class as `_tick_immune_strength`."""
        for agent in agents:
            target = (
                agent.emotions.get(EMOTION_FEAR, 0.0) * STRESS_FEAR_WEIGHT
                + agent.emotions.get(EMOTION_GRIEF, 0.0) * STRESS_GRIEF_WEIGHT
            )
            if agent.hunger >= CRITICAL_HUNGER_THRESHOLD:
                target += STRESS_HUNGER_CRISIS_PULL
            if agent.sick_ticks > 0:
                target += STRESS_SICKNESS_PULL
            if any(flag == "feud" for flag in agent.relationship_flags.values()):
                target += STRESS_FEUD_PULL
            target = clamp(target, 0.0, 1.0)
            agent.stress += (target - agent.stress) * STRESS_ADAPT_RATE
            agent.stress = clamp(agent.stress, 0.0, 1.0)

    @staticmethod
    def _tick_injury_recovery(agents: list[Agent]) -> None:
        """A14 "Layered organism biology," third slice (roadmap Tier 1
        item 8): heals every agent's continuous `injury` toward 0 each
        tick via exponential smoothing, at a rate scaled up to 1.5x by
        good nutrition/rest and down to 0.5x for a starving, exhausted
        agent (`INJURY_RECOVERY_HUNGER_WEIGHT`/`_ENERGY_WEIGHT`) — real
        convalescence, not an instant reset. Injury itself is only ever
        GAINED elsewhere (`_maybe_predator_attack`'s non-lethal
        outcome); this is the recovery half only. Pure Python,
        O(agents), same cost class as `_tick_stress`."""
        for agent in agents:
            if agent.injury <= 0.0:
                continue
            nutrition_factor = 1.0 + (0.5 - agent.hunger) * 2.0 * INJURY_RECOVERY_HUNGER_WEIGHT
            rest_factor = 1.0 + (agent.energy - 0.5) * 2.0 * INJURY_RECOVERY_ENERGY_WEIGHT
            rate = INJURY_RECOVERY_RATE * (nutrition_factor + rest_factor) / 2.0
            agent.injury = clamp(agent.injury - rate, 0.0, 1.0)

    @staticmethod
    def _tick_development(agents: list[Agent]) -> None:
        """A14 "Layered organism biology," fourth slice (roadmap Tier 1
        item 8): accumulates every agent's continuous `development`
        toward 1.0 each tick at `DEVELOPMENT_GROWTH_PER_TICK`, scaled
        up to 1.2x by good nutrition and down to 0.5x under chronic
        hunger (`DEVELOPMENT_NUTRITION_WEIGHT`) — real childhood
        stunting under sustained famine, distinct from `injury`'s
        acute-trauma coupling. Runs for every agent regardless of age
        (a fully-grown adult just stays pinned at 1.0 once reached).
        Real consumer: `carrying_capacity`'s labor term. Pure Python,
        O(agents), same cost class as `_tick_stress`."""
        for agent in agents:
            if agent.development >= 1.0:
                continue
            nutrition_factor = clamp(
                1.0 + (0.5 - agent.hunger) * 2.0 * DEVELOPMENT_NUTRITION_WEIGHT,
                DEVELOPMENT_NUTRITION_MIN_FACTOR, DEVELOPMENT_NUTRITION_MAX_FACTOR,
            )
            agent.development = clamp(
                agent.development + DEVELOPMENT_GROWTH_PER_TICK * nutrition_factor, 0.0, 1.0,
            )

    @staticmethod
    def _immune_modulation_factor(agent: Agent) -> float:
        """The real "not a coin flip" bridge: how much `agent`'s current
        `immune_strength` should scale a base sickness rate, centered so
        `IMMUNE_BASELINE` is a true no-op against every existing tuned
        constant — see `IMMUNE_MODULATION_SENSITIVITY`'s docstring."""
        return clamp(
            1.0 + (IMMUNE_BASELINE - agent.immune_strength) * IMMUNE_MODULATION_SENSITIVITY,
            IMMUNE_MODULATION_MIN_FACTOR, IMMUNE_MODULATION_MAX_FACTOR,
        )

    @staticmethod
    def _tick_disease(
        agents: list[Agent], by_position: dict[tuple[int, int], list[Agent]],
        hospital_settlement_ids: set[int], temperament: float, rng: random.Random, tick: int,
    ) -> tuple[list[tuple[str, str]], set[int]]:
        """Advances every currently-sick agent by one tick: a chance of
        death (reduced by a standing hospital, nudged by temperament —
        same shape as `_maybe_predator_attack`'s lethality, giving the
        town brain's "health" priority a real mechanical reason to
        matter), natural recovery after SICKNESS_DURATION_TICKS, and
        person-to-person transmission to any colocated healthy agent.
        v2: also decays `immune_ticks` for recently-recovered agents and
        exempts them from catching it again while immune. Returns
        (life_events, died_of_disease) — the latter is folded into
        `_apply_deaths` the same way `killed_by_predator` is."""
        life_events: list[tuple[str, str]] = []
        died_of_disease: set[int] = set()
        death_chance = max(
            0.0, SICKNESS_DEATH_CHANCE_PER_TICK * (1.0 - temperament * TEMPERAMENT_KILL_CHANCE_INFLUENCE)
        )
        for agent in agents:
            if agent.sick_ticks <= 0:
                if agent.immune_ticks > 0:
                    agent.immune_ticks -= 1
                continue
            agent.sick_ticks += 1
            agent_death_chance = death_chance
            # Care is a home-community benefit: the hospital that treats
            # you is your own settlement's (a bedridden patient isn't
            # commuting to the neighbors').
            if agent.settlement_id in hospital_settlement_ids:
                agent_death_chance *= (1.0 - SICKNESS_HOSPITAL_KILL_CHANCE_REDUCTION)
            # H4 extension: personal medicine is a second, individually-
            # earned layer of protection on top of the settlement-wide
            # hospital reduction above — see MEDICINE_DEATH_CHANCE_
            # REDUCTION. Drawn down each tick it's helping, so sustained
            # treatment through a full bout needs ongoing production.
            medicine = agent.inventory.get("medicine", 0.0)
            if medicine > 0.0:
                agent_death_chance *= (1.0 - MEDICINE_DEATH_CHANCE_REDUCTION)
                agent.inventory["medicine"] = max(0.0, medicine - MEDICINE_CONSUMPTION_PER_TICK)
            # Integration milestone: personal resilience stacks with
            # medicine/hospital, same shape as the predator-attack side
            # of TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE.
            resilience = agent.traits.get(TRAIT_RESILIENCE, 0.0)
            agent_death_chance = max(
                0.0, agent_death_chance * (1.0 - resilience * TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE)
            )
            # A14 (roadmap Stage IV step 23): the continuous immune-state
            # modulation, stacking with resilience/medicine/hospital
            # above rather than replacing any of them — see
            # `_immune_modulation_factor`'s docstring.
            agent_death_chance *= Population._immune_modulation_factor(agent)
            if rng.random() < agent_death_chance:
                died_of_disease.add(agent.id)
                continue
            if agent.sick_ticks >= SICKNESS_DURATION_TICKS:
                agent.sick_ticks = 0
                agent.immune_ticks = IMMUNITY_DURATION_TICKS
                life_events.append(("recovery", f"{agent.name} has recovered from illness."))
                # H6 extension: surviving a bout of illness is a hardship
                # weathered, not just an emotional event — the missing
                # positive counterpart to TRAIT_SUSTAINED_HUNGER_NUDGE.
                _nudge_trait(agent, TRAIT_RESILIENCE, TRAIT_RECOVERY_RESILIENCE_NUDGE)
                # Deferred item 1 (docs/VISION-2026-07-LEARNING.md):
                # deterministic, zero-LLM-cost lesson formation for the
                # WHOLE population, not just the core cast — the LLM-
                # authored `lessons`/memory-drift jobs stay core-cast-
                # gated per the standing per-agent-LLM-call rule, but a
                # fixed-template lesson costs no LLM budget at all, so
                # every survivor gets to "learn" from surviving illness,
                # not just the protagonists.
                template = RECOVERY_LESSON_TEMPLATES[agent.id % len(RECOVERY_LESSON_TEMPLATES)]
                push_lesson(agent, "danger", template, tick)
        for group in by_position.values():
            if len(group) < 2:
                continue
            sick = [a for a in group if a.sick_ticks > 0]
            if not sick:
                continue
            for target in group:
                if target.sick_ticks > 0 or target.id in died_of_disease or target.immune_ticks > 0:
                    continue
                for carrier in sick:
                    # A14: a well-fed, rested target resists infection
                    # better than a starving, exhausted one — same
                    # modulation shape as the death-chance side above.
                    transmission_chance = (
                        SICKNESS_TRANSMISSION_CHANCE_PER_TICK * Population._immune_modulation_factor(target)
                    )
                    if rng.random() < transmission_chance:
                        target.sick_ticks = 1
                        bump_emotion(target, EMOTION_FEAR, EMOTION_ILLNESS_FEAR_BUMP)
                        life_events.append(("illness", f"{target.name} caught the illness from {carrier.name}."))
                        break
        return life_events, died_of_disease

    @staticmethod
    def _maybe_forage(
        agent: Agent, resources: ResourceGrid, farms: FarmGrid, settlements: list[Settlement],
        wildlife: WildlifeGrid, life_events: "list[tuple[str, str]] | None" = None,
        skill_masteries: "list[tuple[int, str]] | None" = None,
    ) -> None:
        if agent.hunger < FORAGE_HUNGER_THRESHOLD:
            return
        # Technique/customs travel with the eater's own community; the
        # physical food comes from whichever settlement's granary the
        # agent is actually standing at (hospitality is spatial).
        home = next((s for s in settlements if s.id == agent.settlement_id), settlements[0])

        # A ready farm plot is preferred over wild foraging — better yield,
        # and it's the deliberate incentive for cultivating one at all.
        plot = farms.get(agent.x, agent.y)
        if plot is not None and plot.stage is FarmStage.READY:
            # FARMER (v0.87.44): a real occupation-based harvest bonus,
            # on top of (not instead of) SKILL_FARMING below.
            harvest_amount = (
                HARVEST_AMOUNT * (FARMER_HARVEST_BONUS if agent.occupation == OCCUPATION_FARMER else 1.0)
                * _specialization_factor(home, "agricultural")
            )
            consumed = farms.harvest(agent.x, agent.y, harvest_amount)
            if consumed > 0:
                # Harvest-minded traditions stretch what a harvest gives —
                # culture with a real lever, see culture_effect_multiplier.
                # H5: a farming-skilled harvester also stretches their own
                # catch further, on top of (not instead of) the settlement-
                # wide tech/tradition bonuses — see SKILL_FARMING_YIELD_BONUS.
                farming_skill = agent.skills.get(SKILL_FARMING, 0.0)
                relief = (
                    HARVEST_HUNGER_RELIEF * (consumed / HARVEST_AMOUNT) * _tech_factor(home)
                    * culture_effect_multiplier(home.culture_effects, "harvest")
                    * (1.0 + farming_skill * SKILL_FARMING_YIELD_BONUS)
                )
                agent.hunger = max(0.0, agent.hunger - relief)
                agent.inventory["food"] = min(
                    PERSONAL_FOOD_CAPACITY, agent.inventory.get("food", 0.0) + FORAGE_INVENTORY_SKIM
                )
                new_farming_skill = min(1.0, farming_skill + SKILL_PRACTICE_GAIN)
                agent.skills[SKILL_FARMING] = new_farming_skill
                if farming_skill < MASTERY_THRESHOLD <= new_farming_skill:
                    # H6 extension: first time this skill reaches mastery —
                    # a tangible achievement, not routine practice.
                    _nudge_trait(agent, TRAIT_AMBITION, TRAIT_AMBITION_MASTERY_NUDGE)
                    _remember(agent, "Became a master of farming after years of practice.")
                    if life_events is not None:
                        life_events.append(("skill_mastered", f"{agent.name} became a true master of farming."))
                    if skill_masteries is not None:
                        skill_masteries.append((agent.id, "farming"))
                return

        # A stocked granary, pasture, or hatchery is preferred over wild
        # foraging too — a deliberate community buffer/production
        # source, second only to a fresh farm. PASTURE/HATCHERY
        # (v0.86.7) share the exact same withdrawal shape as GRANARY —
        # all three are "cultivated food a settlement invested in
        # building," not opportunistic wild catch.
        granary, granary_owner = None, home
        for stl in settlements:
            candidate = stl.at(agent.x, agent.y)
            if candidate is not None:
                granary, granary_owner = candidate, stl
                break
        if (
            granary is not None
            and granary.kind in (BuildingKind.GRANARY, BuildingKind.PASTURE, BuildingKind.HATCHERY)
            and granary.stage is BuildingStage.STANDING and granary.stored_food > 0
        ):
            consumed = min(granary.stored_food, GRANARY_WITHDRAW_AMOUNT)
            granary.stored_food -= consumed
            relief = GRANARY_HUNGER_RELIEF * (consumed / GRANARY_WITHDRAW_AMOUNT) * _tech_factor(granary_owner)
            agent.hunger = max(0.0, agent.hunger - relief)
            agent.inventory["food"] = min(
                PERSONAL_FOOD_CAPACITY, agent.inventory.get("food", 0.0) + FORAGE_INVENTORY_SKIM
            )
            return

        # An agent's own saved reserve is drawn on before scrounging for
        # something fresh — eating what you already set aside, same as a
        # person would, before a trade with a neighbor even becomes
        # relevant (see Population._maybe_trade_food for the sharing side).
        personal_food = agent.inventory.get("food", 0.0)
        if personal_food > 0.0:
            consumed = min(personal_food, TRADE_FOOD_AMOUNT)
            agent.inventory["food"] = personal_food - consumed
            relief = TRADE_HUNGER_RELIEF * (consumed / TRADE_FOOD_AMOUNT)
            agent.hunger = max(0.0, agent.hunger - relief)
            return

        # A colocated grazer herd can be hunted for a richer yield than
        # wild foraging — a finite, huntable resource like a resource
        # node, but mobile and shared with predators. See docs/DECISIONS.md, A4.
        for herd in wildlife.at(agent.x, agent.y):
            if herd.species is Species.GRAZER and herd.count > 0:
                killed = wildlife.hunt(herd.id, amount=1)
                if killed > 0:
                    agent.hunger = max(0.0, agent.hunger - HUNT_YIELD_PER_ANIMAL * killed)
                    return
                break

        node = resources.get(agent.x, agent.y)
        if node is not None and node.kind in (ResourceKind.FOOD, ResourceKind.FISH) and node.amount > 0:
            consumed = min(node.amount, FORAGE_AMOUNT)
            node.amount -= consumed
            resources.mark_regenerating(agent.x, agent.y)
            relief = FORAGE_HUNGER_RELIEF * (consumed / FORAGE_AMOUNT)
            if node.kind is ResourceKind.FISH:
                # FISHERMAN (v0.87.44): occupation-based catch bonus, on
                # top of the settlement-wide RAFT bonus.
                fisherman_bonus = FISHERMAN_FORAGE_BONUS if agent.occupation == OCCUPATION_FISHERMAN else 1.0
                relief *= FISH_HUNGER_RELIEF_MULTIPLIER * _raft_factor(home) * fisherman_bonus
                home.fish_caught += 1
                Population._wear_rafts(home)
            agent.hunger = max(0.0, agent.hunger - relief)
            return

        # Last resort: buy emergency rations with settlement currency at a
        # standing granary (the village's trade post) — only reachable
        # once nothing free is available. See D10. Famine food costs more
        # when a MARKET has discovered a food price (tick_market_prices)
        # — scarcity now cuts both ways for the buyer, not just the
        # seller side of overflow sales.
        ration_cost = CURRENCY_EMERGENCY_RATION_COST * granary_owner.market_price("food")
        if (
            granary is not None and granary.kind is BuildingKind.GRANARY
            and granary.stage is BuildingStage.STANDING
            and granary_owner.currency >= ration_cost
        ):
            granary_owner.currency -= ration_cost
            agent.hunger = max(0.0, agent.hunger - CURRENCY_EMERGENCY_HUNGER_RELIEF)

    @staticmethod
    def _maybe_gather(
        agent: Agent, terrain: list[list[Tile]], settlement: Settlement, resources: ResourceGrid,
        minerals: "MineralGrid | None" = None,
    ) -> bool:
        """GATHER-goal agents on forest/hills feed the settlement's shared
        materials stockpile — awake-only (unlike foraging, this isn't a
        survival mechanic, so no resting-interrupt applies). See D8.

        Forest wood stays uncapped (a forest is abstracted as
        renewable/abundant, unlike a specific mineral vein) — but hills
        gathering (see docs/DECISIONS.md, resource-variety pass) now
        draws from a discrete ORE `ResourceNode` that depletes and
        regrows far slower than food (ORE_REGEN_PER_TICK), so a mined-out
        hill genuinely stops producing until it recovers. A hills tile
        with no ore node (rolled FOOD instead at generation, see
        `ResourceGrid.generate`) yields nothing to a GATHER-goal agent —
        it's a foraging spot, not a mine.

        §8 expanded mineral economy (v0.87.25): a hills tile carrying a
        `MineralDeposit` (world/minerals.py, independent of whatever
        ResourceGrid node sits there — see that module's docstring)
        takes priority when present — the agent works the specific
        iron/gold vein that tick instead of general ore/materials, same
        "one focused lot per tick" shape the rest of gathering already
        has. `minerals=None` (a caller that hasn't threaded the grid
        through, e.g. an older test) simply skips this branch — no
        behavior change from before this pass."""
        biome = terrain[agent.y][agent.x].biome
        if agent.goal is not AgentGoal.GATHER or agent.state is not AgentState.AWAKE:
            return False
        if biome not in MATERIAL_BIOMES:
            return False

        if minerals is not None:
            deposit = minerals.get(agent.x, agent.y)
            if deposit is not None and deposit.amount > 0:
                mined = minerals.harvest(agent.x, agent.y, MINERAL_GATHER_PER_TICK)
                mined *= _haul_factor(settlement)
                kind = deposit.kind.value
                stock = settlement.minerals
                current = stock.get(kind, 0.0)
                if current >= MINERAL_CAPACITY:
                    settlement.currency = min(
                        CURRENCY_CAPACITY,
                        settlement.currency + mined * MINERAL_CURRENCY_VALUE.get(kind, 1.0),
                    )
                else:
                    stock[kind] = min(MINERAL_CAPACITY, current + mined)
                return True

        gathered = MATERIALS_GATHER_PER_TICK
        if biome in ORE_BIOMES:
            node = resources.get(agent.x, agent.y)
            if node is None or node.kind is not ResourceKind.ORE or node.amount <= 0:
                return False
            gathered = min(node.amount, MATERIALS_GATHER_PER_TICK)
            node.amount -= gathered
            resources.mark_regenerating(agent.x, agent.y)

        # Ready carts speed hauling of whatever was just gathered back to
        # the stockpile — see CART_HAUL_BONUS_PER_CART, D8/vehicles pass.
        gathered *= _haul_factor(settlement)
        # H4: the gatherer's own tools stretch their own haul further —
        # a personal, ownership-driven multiplier distinct from the
        # settlement-wide cart bonus above. See GATHER_TOOLS_YIELD_BONUS.
        gathered *= 1.0 + (agent.inventory.get("tools", 0.0) / TOOLS_CAPACITY) * GATHER_TOOLS_YIELD_BONUS

        # A full stockpile doesn't waste the surplus — it sells to an
        # abstract outside economy instead (D10). With a standing MARKET
        # the sale fetches the current materials price (scarce materials
        # sell high) rather than a flat rate — see tick_market_prices.
        if settlement.materials >= MATERIALS_CAPACITY:
            settlement.currency = min(
                CURRENCY_CAPACITY,
                settlement.currency + gathered * CURRENCY_PER_OVERFLOW_UNIT * settlement.market_price("materials"),
            )
            return True
        settlement.materials = min(MATERIALS_CAPACITY, settlement.materials + gathered)
        return True

    @staticmethod
    def _maybe_plant(
        by_position: dict[tuple[int, int], list[Agent]], farms: FarmGrid,
        settlements: list[Settlement], terrain: list[list[Tile]], rng: random.Random,
        hydrology_moisture: list[list[float]] | None = None,
        fields: "FieldGrid | None" = None,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        settlements_by_id = {s.id: s for s in settlements}
        for (x, y), group in by_position.items():
            if farms.get(x, y) is not None or any(s.at(x, y) is not None for s in settlements):
                continue
            if not FarmGrid.is_farmable(terrain, x, y):
                continue
            # Planting is now a *deliberate* act, not ambient: it needs a
            # colocated awake agent who is actually food-focused — FORAGE
            # goal (LLM- or fallback-chosen) or genuinely hungry. This is
            # the negative-feedback half of the carrying-capacity rework
            # (July 2026 review): a well-fed village stops planting, its
            # standing crops rot away (FARM_ROT_TICKS), and food tightens
            # again — instead of the map monotonically carpeting itself
            # in fields. It also gives the cognition layer's goal choice
            # real mechanical teeth: FORAGE now *produces* food supply,
            # not just consumption.
            if not any(
                a.state is AgentState.AWAKE
                and (a.goal is AgentGoal.FORAGE or a.hunger >= FORAGE_HUNGER_THRESHOLD)
                for a in group
            ):
                continue
            if rng.random() >= PLANT_CHANCE_PER_TICK:
                continue
            # Farm tools come from the planters' own stockpile.
            settlement = settlements_by_id.get(group[0].settlement_id, settlements[0])
            tooled = settlement.materials >= FARM_TOOL_MATERIALS_COST
            if tooled:
                settlement.materials -= FARM_TOOL_MATERIALS_COST
            moisture = 1.0
            if hydrology_moisture is not None and 0 <= y < len(hydrology_moisture) and 0 <= x < len(hydrology_moisture[y]):
                moisture = hydrology_moisture[y][x]
            pollution = 0.0
            if fields is not None and terrain:
                pollution = fields.get_at("pollution", (x, y), len(terrain[0]), len(terrain))
            farms.plant(x, y, tooled=tooled, moisture=moisture, pollution=pollution)
            note = (
                f"A field was planted at ({x}, {y}), using tools for a richer harvest."
                if tooled else f"A field was planted at ({x}, {y})."
            )
            life_events.append(("farm_planted", note))
        return life_events

    @classmethod
    def _dispatch_movement(
        cls, agent: Agent, terrain: list[list[Tile]], rng: random.Random,
        resources: ResourceGrid, farms: FarmGrid, settlement: Settlement, wildlife: WildlifeGrid,
        roads: RoadNetwork, predator_tiles: set[tuple[int, int]],
        position_snapshot: list[tuple[int, int, int]], critically_hungry: bool = False,
        weather: WeatherState | None = None,
        rival_tiles: set[tuple[int, int]] | None = None,
        food_positions: tuple[list[tuple[int, int]], list[tuple[int, int]]] | None = None,
        work_positions: list[tuple[int, int]] | None = None,
        material_index: "object | None" = None,
        agent_position_index: "object | None" = None,
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(),
        ostracized_ids: frozenset[int] = frozenset(),
    ) -> None:
        """Goal-directed agents (FORAGE/SOCIALIZE) take a deliberate step
        toward a visible target when one exists; otherwise (including
        WANDER, the default/pre-Phase-B behavior) fall back to the
        original probabilistic random walk.

        `critically_hungry` overrides whatever goal is assigned and forces
        FORAGE-seeking instead: goals are only reevaluated once per
        sim-day (see `due_for_cognition`), so an agent assigned e.g.
        SOCIALIZE while well-fed can otherwise drift toward starvation
        with nothing making it deliberately look for food until its next
        daily reevaluation — the D3 emergency-wake only got a resting
        agent back onto its feet, it never redirected where an *awake*
        agent walks. See docs/DECISIONS.md, D5."""
        # Rivalry-driven avoidance (A5 follow-up): a rival's tile is
        # avoided the same way a predator's is — preferred against, not
        # forbidden, so an agent doesn't strand itself. `rival_tiles` is
        # precomputed once per tick by `tick()` (see the O(N^2) note
        # there) and folded into the same `predator_tiles`-shaped set
        # _step_toward/_maybe_move already know how to prefer-avoid.
        # See docs/DECISIONS.md, "rivalry avoidance" pass.
        if rival_tiles:
            predator_tiles = predator_tiles | rival_tiles

        # Mining/tunneling technology (ERA_UNLOCKS_MOUNTAIN_BUILDING)
        # opens MOUNTAIN terrain to this settlement's own pathing — see
        # docs/DECISIONS.md, "geography x tech" fix (v0.68.0). SNOWCAP
        # stays impassable at every era.
        mountain_unlocked = settlement.era in ERA_UNLOCKS_MOUNTAIN_BUILDING

        # v0.87.42: computed once, up front, so every _step_toward call
        # below (travel journeys, mourning/wedding venues, ordinary
        # goal-directed movement) consistently grants water-crossing
        # capability to a boat-mounted agent — see `_is_walkable`'s
        # `water_capable` parameter. `_bfs_step`'s stuck-pocket escape
        # path deliberately isn't extended this pass (a documented scope
        # trim, not an oversight): it's a rare fallback, not the primary
        # transport mechanism.
        early_mount = _agent_mount(settlement, agent.id)
        water_capable = early_mount is not None and early_mount.kind is VehicleKind.BOAT

        # A long-range journey (today: a fission party walking to its
        # new settlement's site) overrides goal-directed movement — but
        # never a hunger emergency: a starving traveler detours for food
        # first, the same override precedence everything else follows.
        # See Agent.travel_target.
        if agent.travel_target is not None and not critically_hungry:
            if (agent.x, agent.y) == agent.travel_target:
                agent.travel_target = None
            else:
                journey_mount = early_mount
                moved = cls._step_toward(
                    agent, agent.travel_target, terrain, predator_tiles, mountain_unlocked, bridge_tiles,
                    water_capable,
                )
                if moved and journey_mount is not None and agent.travel_target is not None:
                    if cls._step_toward(
                        agent, agent.travel_target, terrain, predator_tiles, mountain_unlocked, bridge_tiles,
                        water_capable,
                    ):
                        journey_mount.condition = max(
                            0.0, journey_mount.condition - PERSONAL_VEHICLE_USE_DECAY[journey_mount.kind]
                        )
                if agent.travel_target is not None and not moved:
                    # Greedy step blocked (concave water/mountain pocket
                    # — greedy would oscillate forever): take one step
                    # of a real BFS path instead. Unreachable target =
                    # the journey is abandoned where they stand.
                    step = cls._bfs_step(
                        terrain, (agent.x, agent.y), agent.travel_target,
                        mountain_unlocked=mountain_unlocked, bridge_tiles=bridge_tiles,
                    )
                    if step is None:
                        agent.travel_target = None
                    else:
                        agent.x, agent.y = step
                        moved = True
                if agent.travel_target is not None and (agent.x, agent.y) == agent.travel_target:
                    agent.travel_target = None
                if moved:
                    return

        # Mourning (v0.87.9, "ceremonies agents attend: funerals"):
        # biases movement toward the deceased's grave for the survivor's
        # mourning duration — lower priority than a long-range journey
        # (travel_target, above) or a hunger emergency, but overrides
        # the agent's normal goal for its duration. Unlike travel_target
        # this does NOT clear itself on arrival — a funeral is a
        # gathering, not a one-shot errand; `Population._tick_mourning`
        # is the only thing that ends it (duration expiry). Once
        # arrived, the agent simply holds still at the grave rather than
        # random-walking away — a legible "the mourners gathered and
        # stayed" cue on the map.
        if agent.mourning_ticks_remaining > 0 and not critically_hungry and agent.travel_target is None:
            grave = agent.mourning_target
            if grave is not None and (agent.x, agent.y) != grave:
                if cls._step_toward(agent, grave, terrain, predator_tiles, mountain_unlocked, bridge_tiles, water_capable):
                    agent.stuck_ticks = 0
                    return
                step = cls._bfs_step(
                    terrain, (agent.x, agent.y), grave,
                    mountain_unlocked=mountain_unlocked, bridge_tiles=bridge_tiles,
                )
                if step is not None:
                    agent.x, agent.y = step
            return

        # Weddings (v0.87.10, companion to funerals above): the same
        # gathering-and-hold shape, just shorter (WEDDING_DURATION_TICKS)
        # and joyful. Checked after mourning so a guest who is somehow
        # both mourning and celebrating (extremely rare — a death and a
        # birth landing on the same agent's overlapping windows) finishes
        # the funeral first; the wedding resumes on the very next tick
        # once mourning's own override no longer applies.
        if agent.wedding_ticks_remaining > 0 and not critically_hungry and agent.travel_target is None:
            venue = agent.wedding_target
            if venue is not None and (agent.x, agent.y) != venue:
                if cls._step_toward(agent, venue, terrain, predator_tiles, mountain_unlocked, bridge_tiles, water_capable):
                    agent.stuck_ticks = 0
                    return
                step = cls._bfs_step(
                    terrain, (agent.x, agent.y), venue,
                    mountain_unlocked=mountain_unlocked, bridge_tiles=bridge_tiles,
                )
                if step is not None:
                    agent.x, agent.y = step
            return

        effective_goal = (
            AgentGoal.FORAGE if critically_hungry
            else AgentGoal.EXPLORE if agent.occupation == OCCUPATION_SURVEYOR
            else agent.goal
        )
        target = None
        if effective_goal is AgentGoal.EXPLORE:
            # v0.87.45: a surveyor always explores, overriding whatever
            # goal cognition/the deterministic fallback last assigned —
            # same "forced regardless of assigned goal" shape critically_
            # hungry uses for FORAGE. No travel_target yet this leg?
            # Pick one via bounded random sampling (never a full-map
            # flood fill — see `_choose_explore_target`'s docstring for
            # why) and let the existing travel_target journey machinery
            # (checked at the top of this function, highest priority)
            # carry the surveyor there over the following ticks.
            if agent.travel_target is None:
                agent.travel_target = cls._choose_explore_target(agent, terrain, settlement.explored_tiles, rng)
            if agent.travel_target is None:
                pass  # fully explored (or unlucky sampling) — fall through to ordinary wander below
            else:
                return
        elif effective_goal is AgentGoal.FORAGE:
            # `food_positions` (ready farms, worth-the-walk granaries) is
            # precomputed once per tick by `tick()` and shared by every
            # food-seeking agent, instead of each agent re-walking the
            # plots dict/building list — the next constant-factor cost
            # after the rival-scan fix at large populations. Falls back
            # to computing locally when not provided (nearest_food_steps'
            # rare, engine-side use).
            farm_positions, granary_positions = (
                food_positions if food_positions is not None
                else (cls.ready_farm_positions(farms), cls.stocked_granary_positions(settlement))
            )
            target = (
                cls._nearest_position(agent, farm_positions)
                or cls._nearest_position(agent, granary_positions)
                or cls._nearest_grazer_herd(agent, wildlife)
                or cls._nearest_resource(agent, resources)
            )
        elif effective_goal is AgentGoal.SOCIALIZE:
            # §1 "deviance loop": an ostracized villager isn't sought out
            # as company (Agent.standing_penalty) — the native index has
            # no exclusion-set support, so it's only bypassed on the rare
            # ticks any ostracism is actually in effect. Audit follow-up:
            # relationship-weighted targeting (also native-index-
            # incompatible) whenever the agent has any real bond on
            # record — see _nearest_liked_agent's docstring.
            if agent.relationships:
                target = cls._nearest_liked_agent(agent, position_snapshot, ostracized_ids)
            elif ostracized_ids and agent_position_index is not None:
                target = cls._nearest_other_agent(agent, position_snapshot, None, ostracized_ids)
            else:
                target = cls._nearest_other_agent(agent, position_snapshot, agent_position_index, ostracized_ids)
        elif effective_goal is AgentGoal.SEEK_PERSON:
            # Unlike SOCIALIZE (nearest agent), this pathfinds toward a
            # SPECIFIC agent (`seek_target_id`) — re-looked-up from the
            # shared per-tick position_snapshot every call, so movement
            # correctly tracks a moving target instead of chasing a
            # stale position. Arrival (same tile) or the target no
            # longer existing (death/settlement change) both clear the
            # seek and fall through to a random walk this tick — the
            # NEXT cognition cycle picks a fresh goal; no separate
            # "arrived, now what" state is needed since the existing
            # colocated-dialogue mechanism (due_for_dialogue) already
            # picks up same-tile pairs every tick regardless of goal.
            if agent.seek_target_id is not None:
                for other_id, ox, oy in position_snapshot:
                    if other_id == agent.seek_target_id:
                        if (ox, oy) == (agent.x, agent.y):
                            agent.seek_target_id = None
                        else:
                            target = (ox, oy)
                        break
                else:
                    agent.seek_target_id = None
        elif effective_goal is AgentGoal.GATHER:
            target = cls._nearest_material_tile(agent, terrain, material_index)
            if target is None and agent.travel_target is None and terrain is not None:
                # Root-cause fix for a live report: a settlement founded
                # (or, more often, fissioned) with no FOREST/HILLS tile
                # within GATHER_SEARCH_RADIUS left every GATHER-goal agent
                # with a permanently-None target — no fallback existed the
                # way FORAGE has three fallback tiers and SOCIALIZE has no
                # cap at all — degrading to a pure random walk forever.
                # `settlement.materials` then never crosses HUT_MATERIALS_
                # COST, so the settlement can go 20,000+ ticks with zero
                # buildings, which in turn means it never gets named either
                # (naming gates on a STANDING building, see World.tick()).
                # One-time whole-map reachability scan (see
                # _nearest_material_tile_global) sets a real travel_target
                # so the existing journey/BFS machinery (already used for
                # fission travel and stuck-pocket escapes) carries them
                # there over many ticks — cheap because it only fires
                # while no nearby material exists AND no journey is
                # already under way.
                far_target = cls._nearest_material_tile_global(agent.x, agent.y, terrain, bridge_tiles)
                if far_target is not None:
                    agent.travel_target = far_target
        elif effective_goal is AgentGoal.WANDER and work_positions:
            # Root-cause fix (v0.43.2 follow-up): a WANDERing agent
            # previously had zero attraction toward a decaying building —
            # `_maybe_repair` only ever fires from *incidental* colocation,
            # so a batch of huts built in the same growth spurt (identical
            # decay trajectory, no per-building variance) could all cross
            # REPAIR_THRESHOLD together with nobody nearby to catch it,
            # collapsing housing capacity in one window. WANDER is the
            # common idle/no-pressing-need fallback goal (see
            # llm/cognition.py's fallback_goal), so biasing it toward the
            # settlement's most-damaged building gives every otherwise-
            # idle agent a chance to become repair labor, the same way
            # FORAGE already biases toward food. See docs/DECISIONS.md.
            # v0.65.0: the same attractor list now also carries staked-
            # out/under-construction sites (see under_construction_
            # positions) — the "builders walk to the chosen site" half
            # of agent-pathed construction.
            target = cls._nearest_position(agent, work_positions)

        mount = early_mount
        if target is not None:
            if cls._step_toward(agent, target, terrain, predator_tiles, mountain_unlocked, bridge_tiles, water_capable):
                agent.stuck_ticks = 0
                if mount is not None and cls._step_toward(
                    agent, target, terrain, predator_tiles, mountain_unlocked, bridge_tiles, water_capable,
                ):
                    # A ready personal vehicle (mount or the era-gated
                    # automobile upgrade) covers ground twice as fast toward
                    # a deliberate target — the goal-directed equivalent of
                    # PERSONAL_VEHICLE_SPEED_MULTIPLIER's boost to the
                    # random walk below.
                    mount.condition = max(0.0, mount.condition - PERSONAL_VEHICLE_USE_DECAY[mount.kind])
                return
            if (agent.x, agent.y) == target:
                agent.stuck_ticks = 0  # arrived, not blocked — nothing to escape
            else:
                agent.stuck_ticks += 1
                if agent.stuck_ticks >= MOVEMENT_STUCK_TICKS_THRESHOLD:
                    # See MOVEMENT_STUCK_TICKS_THRESHOLD: the greedy step has
                    # failed repeatedly, likely a concave pocket rather than
                    # true unreachability — spend one bounded BFS to escape
                    # it instead of leaving the agent to random-walk near a
                    # target it can see but can't greedily reach.
                    agent.stuck_ticks = 0
                    step = cls._bfs_step(
                        terrain, (agent.x, agent.y), target, node_cap=MOVEMENT_STUCK_BFS_NODE_CAP,
                        mountain_unlocked=mountain_unlocked, bridge_tiles=bridge_tiles,
                    )
                    if step is not None:
                        agent.x, agent.y = step
                        return
        else:
            agent.stuck_ticks = 0
        cls._maybe_move(
            agent, terrain, rng, roads, predator_tiles,
            speed_multiplier=PERSONAL_VEHICLE_SPEED_MULTIPLIER[mount.kind] if mount is not None else 1.0,
            weather=weather,
        )
        if mount is not None:
            mount.condition = max(0.0, mount.condition - PERSONAL_VEHICLE_USE_DECAY[mount.kind])

    @staticmethod
    def _choose_explore_target(
        agent: Agent, terrain: list[list[Tile]], explored_tiles: set, rng: random.Random,
        attempts: int = 40,
    ) -> tuple[int, int] | None:
        """v0.87.45: bounded random sampling for the nearest not-yet-
        explored walkable tile — deliberately NOT a full-map flood fill
        (`_reachable_tiles` has no node cap and would recompute the
        entire connected component every tick a surveyor needs a new
        target). `attempts` random in-bounds samples, keep the closest
        unexplored walkable hit; returns None once nothing new turns up
        (map effectively fully explored, or an unlucky sampling run —
        the caller just retries next tick)."""
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for _ in range(attempts):
            x, y = rng.randrange(width), rng.randrange(height)
            if (x, y) in explored_tiles or not _is_walkable(terrain, x, y):
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def ready_farm_positions(farms: FarmGrid) -> list[tuple[int, int]]:
        """READY-plot coordinates. No distance cap when targeted (see
        `_nearest_position`): found root cause of the D6 starvation
        cascade — cultivated land is known to its community the same
        way SOCIALIZE treats other agents as known (D4). See
        docs/DECISIONS.md, D6."""
        return [(x, y) for (x, y), plot in farms.plots.items() if plot.stage is FarmStage.READY]

    @staticmethod
    def stocked_granary_positions(settlement: Settlement) -> list[tuple[int, int]]:
        """Worth-the-walk stocked food buildings: a GRANARY (stocked, or
        empty but the settlement can afford emergency rations, D10), or a
        standing PASTURE/HATCHERY with real stored_food. v0.87.25
        (explicit user direction — "actively seek out ways to get food
        like husbandries, hatcheries"): PASTURE/HATCHERY already accepted
        withdrawals once an agent happened to stand there
        (`_maybe_forage`), but nothing ever pathed a hungry FORAGE-goal
        agent toward one deliberately — same D6/D7 "known community
        landmark" logic GRANARY already gets, extended to the other two
        built food sources. Empty pastures/hatcheries aren't included
        (no emergency-ration equivalent for them) — a hungry agent only
        detours there when there's actually something to eat."""
        can_buy_rations = settlement.currency >= CURRENCY_EMERGENCY_RATION_COST * settlement.market_price("food")
        return [
            (b.x, b.y) for b in settlement.buildings
            if b.stage is BuildingStage.STANDING and (
                (b.kind is BuildingKind.GRANARY and (b.stored_food > 0 or can_buy_rations))
                or (b.kind in (BuildingKind.PASTURE, BuildingKind.HATCHERY) and b.stored_food > 0)
            )
        ]

    @staticmethod
    def damaged_building_positions(
        settlement: Settlement, by_position: dict[tuple[int, int], list[Agent]] | None = None,
    ) -> list[tuple[int, int]]:
        """Standing buildings at or below REPAIR_THRESHOLD — the WANDER-
        goal repair attractor (v0.43.2 follow-up, see _dispatch_movement).
        No distance cap when targeted, same rationale as farm/granary
        positions: a settlement's own buildings are known landmarks to
        its residents, not something they have to stumble across.

        v0.87.41: excludes a damaged building already staffed to
        MAX_WORKERS awake agents when `by_position` is supplied — every
        idle agent previously targeted the single NEAREST damaged
        building independently via `_nearest_position`, so in a populous
        settlement they piled onto one site past the point of any real
        repair benefit (extra workers beyond MAX_WORKERS don't speed
        `_maybe_repair`) while every other damaged building sat untouched.
        This is the same "single-target magnetism" bug class the mining/
        food-priority feedback loops were, applied to labor allocation —
        a live report of decay outrunning repair at scale traced to this.
        Sorted worst-condition-first so the newly-freed-up idle agents
        prioritize the most urgent site among the reachable remainder."""
        candidates = sorted(
            (
                b for b in settlement.buildings
                if b.stage is BuildingStage.STANDING and b.condition < REPAIR_THRESHOLD
            ),
            key=lambda b: b.condition,
        )
        if by_position is None:
            return [(b.x, b.y) for b in candidates]
        result = []
        for b in candidates:
            workers = sum(
                1 for a in by_position.get((b.x, b.y), []) if a.state is AgentState.AWAKE
            )
            if workers < MAX_WORKERS:
                result.append((b.x, b.y))
        return result

    @staticmethod
    def husbandry_positions(settlement: Settlement) -> list[tuple[int, int]]:
        """Standing PASTURE/HATCHERY tiles not yet at capacity — a WANDER-
        goal attractor (v0.87.25, folded into `work_positions` alongside
        damaged/under-construction buildings) so a well-fed, idle agent
        is deliberately drawn to go TEND husbandry, not just eat from it
        by lucky colocation. `_maybe_run_husbandry`'s own tending bonus
        was always real; nothing before this made an agent seek out the
        chance to earn it. Below-capacity only — no reason to attract
        idle labor to a building that's already full."""
        return [
            (b.x, b.y) for b in settlement.buildings
            if b.stage is BuildingStage.STANDING
            and b.kind in (BuildingKind.PASTURE, BuildingKind.HATCHERY)
            and b.stored_food < (PASTURE_CAPACITY if b.kind is BuildingKind.PASTURE else HATCHERY_CAPACITY)
        ]

    @staticmethod
    def granary_positions(settlement: Settlement) -> list[tuple[int, int]]:
        """Standing GRANARY tiles not yet at capacity — a WANDER-goal
        attractor, the same fix `husbandry_positions` (v0.87.25) gave
        PASTURE/HATCHERY but GRANARY itself never received. v0.87.41:
        `_maybe_stock_granaries` has always been real (well-fed agents
        present deposit surplus) but nothing before this deliberately
        drew an idle, well-fed agent TOWARD a granary to do it — deposits
        only happened by lucky colocation (an agent already there for
        some other reason), the exact gap husbandry_positions closed for
        its two younger sibling buildings. This is the direct fix for
        "NPCs aren't storing food in granaries." Below-capacity only, same
        rationale as husbandry_positions."""
        return [
            (b.x, b.y) for b in settlement.buildings
            if b.stage is BuildingStage.STANDING
            and b.kind is BuildingKind.GRANARY
            and b.stored_food < GRANARY_CAPACITY
        ]

    @staticmethod
    def _nearest_position(agent: Agent, positions: list[tuple[int, int]]) -> tuple[int, int] | None:
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for x, y in positions:
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _nearest_grazer_herd(agent: Agent, wildlife: WildlifeGrid) -> tuple[int, int] | None:
        herd = wildlife.nearest_grazer_herd(agent.x, agent.y, WILDLIFE_SEARCH_RADIUS)
        return (herd.x, herd.y) if herd is not None else None

    @staticmethod
    def _nearest_resource(agent: Agent, resources: ResourceGrid) -> tuple[int, int] | None:
        """A FISH node in range is preferred over a nearer FOOD node, not
        just whichever tile wins a raw distance tie-break. FISH nodes are
        deliberately the richer, faster-regenerating catch (see world/
        resources.py's FISH_HUNGER_RELIEF_MULTIPLIER/FISH_REGEN_PER_TICK
        docstrings) but are only ~35% as dense as FOOD nodes are across a
        much smaller footprint (water-adjacent tiles only, vs. every
        forest/grassland/hills tile) — under plain nearest-wins, a FISH
        node essentially never won the tie-break, so fishing only ever
        happened by incidental colocation, never as visible in-game
        behavior. Root cause of the "NPCs never seem to fish" report.

        Scans the bounded (2*FORAGE_SEARCH_RADIUS+1)^2 box around the
        agent via direct dict lookups rather than every node on the map
        (v0.67.0 perf pass — profiling a 60-agent/64x64 run found this
        the single largest self-time hotspot: ~800 total resource nodes
        scanned per call, most of them far outside any agent's search
        radius). Fixed-cost regardless of map size/node density, so it
        stops scaling with total node count the way the old `.items()`
        scan did — CLAUDE.md's pre-approved first escalation step
        ("spatial buckets for nearest-X scans") applied to the one
        function that actually needed it.

        v0.72.2 native port: dispatches to `resources.nearest_food_or_
        fish` (a compiled `ResourceIndex` query, see cpp/src/resource_
        grid.cpp) when built, falling back to the identical pure-Python
        scan below otherwise — same "hot query, share the amortized
        setup cost across every agent's call this tick" shape as R4's
        `resources.tick` working set."""
        native_result = resources.nearest_food_or_fish(agent.x, agent.y, FORAGE_SEARCH_RADIUS)
        if native_result is not None:
            return native_result
        if resources._native_index is not None:
            return None  # native index built and searched, genuinely nothing in range

        best_food: tuple[int, int] | None = None
        best_food_dist: int | None = None
        best_fish: tuple[int, int] | None = None
        best_fish_dist: int | None = None
        nodes = resources.nodes
        ax, ay = agent.x, agent.y
        for dy in range(-FORAGE_SEARCH_RADIUS, FORAGE_SEARCH_RADIUS + 1):
            y = ay + dy
            for dx in range(-FORAGE_SEARCH_RADIUS, FORAGE_SEARCH_RADIUS + 1):
                node = nodes.get((ax + dx, y))
                if node is None or node.kind not in (ResourceKind.FOOD, ResourceKind.FISH) or node.amount <= 0:
                    continue
                dist = abs(dx) + abs(dy)
                if node.kind is ResourceKind.FISH:
                    if best_fish_dist is None or dist < best_fish_dist:
                        best_fish, best_fish_dist = (ax + dx, y), dist
                else:
                    if best_food_dist is None or dist < best_food_dist:
                        best_food, best_food_dist = (ax + dx, y), dist
        return best_fish if best_fish is not None else best_food

    @staticmethod
    def _nearest_material_tile(
        agent: Agent, terrain: list[list[Tile]], material_index: "object | None" = None,
    ) -> tuple[int, int] | None:
        """Scans a bounded box (no discrete registry like resources/farms
        exist for terrain biomes) within GATHER_SEARCH_RADIUS. See D8.

        v0.72.3 native port: dispatches to `material_index` (a compiled
        `TerrainMaterialIndex`, see cpp/src/terrain_index.cpp), built
        once per `Population.tick()` and shared across every GATHER-
        seeking agent's call this tick, when available — falls back to
        the identical pure-Python scan below otherwise (`material_index`
        is `None` when the extension isn't built)."""
        if material_index is not None:
            return material_index.nearest(agent.x, agent.y, GATHER_SEARCH_RADIUS)

        height = len(terrain)
        width = len(terrain[0]) if height else 0
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for dy in range(-GATHER_SEARCH_RADIUS, GATHER_SEARCH_RADIUS + 1):
            y = agent.y + dy
            if not (0 <= y < height):
                continue
            for dx in range(-GATHER_SEARCH_RADIUS, GATHER_SEARCH_RADIUS + 1):
                x = agent.x + dx
                if not (0 <= x < width):
                    continue
                if terrain[y][x].biome not in MATERIAL_BIOMES:
                    continue
                dist = abs(dx) + abs(dy)
                if best_dist is None or dist < best_dist:
                    best, best_dist = (x, y), dist
        return best

    @classmethod
    def _nearest_material_tile_global(
        cls, agent_x: int, agent_y: int, terrain: list[list[Tile]],
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(),
    ) -> tuple[int, int] | None:
        """Whole-map escape hatch for `_nearest_material_tile`'s bounded
        `GATHER_SEARCH_RADIUS` scan, called only once the bounded scan has
        already come back empty (see its call site in `_dispatch_movement`)
        — not a routine per-tick cost.

        Filtered by actual walkable reachability (`_reachable_tiles`, the
        same flood fill the fission site-chooser and bridge search already
        use) rather than raw Manhattan distance — an earlier version of
        this fix picked the nearest material tile by distance alone, which
        could be a real geographic island across a lake/river the agent
        can never actually walk to. That produced an infinite loop: a
        travel_target gets set toward the unreachable tile, the greedy+BFS
        journey machinery exhausts its search and abandons it (correctly
        detecting it as unreachable), travel_target goes back to None, and
        the very next tick's GATHER dispatch rediscovers and reassigns the
        *same* unreachable tile — the agent never makes progress and never
        gathers, only now spending a wasted journey attempt every cycle
        instead of a plain random walk. Returns None only if no FOREST/
        HILLS tile exists anywhere in the agent's own reachable region — a
        real, if rare, possibility (a small island with no forest/hills of
        its own)."""
        reachable = cls._reachable_tiles(terrain, (agent_x, agent_y), bridge_tiles)
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for (x, y) in reachable:
            if terrain[y][x].biome not in MATERIAL_BIOMES:
                continue
            dist = abs(x - agent_x) + abs(y - agent_y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _nearest_other_agent(
        agent: Agent, position_snapshot: list[tuple[int, int, int]],
        agent_position_index: "object | None" = None,
        ostracized_ids: frozenset[int] = frozenset(),
    ) -> tuple[int, int] | None:
        """No distance cap, unlike _nearest_resource: an agent actively
        seeking company is assumed to know roughly where the (small)
        population's other members are, not just what's locally visible —
        see docs/DECISIONS.md, D4.

        Scans the full `position_snapshot` (built once per tick, see
        Population.tick) — the highest-value native-port candidate of
        the three shipped so far, since this scan has no radius cap and
        so genuinely scales with population, not map size (module 4,
        see cpp/src/agent_position_index.cpp).

        `ostracized_ids` (§1 "deviance loop") excludes agents currently
        under an ostracism penalty from being sought out as company —
        only meaningful on the Python fallback path; the native index
        has no exclusion-set support, so a caller with a non-empty set
        passes `agent_position_index=None` to force this path (rare:
        ostracism itself is rare)."""
        if agent_position_index is not None:
            return agent_position_index.nearest(agent.id, agent.x, agent.y)
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for other_id, x, y in position_snapshot:
            if other_id == agent.id or other_id in ostracized_ids:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _nearest_liked_agent(
        agent: Agent, position_snapshot: list[tuple[int, int, int]], ostracized_ids: frozenset[int] = frozenset(),
    ) -> tuple[int, int] | None:
        """Audit follow-up: relationship-weighted counterpart to
        `_nearest_other_agent`, used for SOCIALIZE whenever the seeking
        agent has any real relationship on record. Never bypasses
        distance entirely — a beloved friend on the far side of a large
        map still loses to someone merely liked nearby, same "locally
        plausible awareness" discipline `FORAGE_SEARCH_RADIUS`/
        `GATHER_SEARCH_RADIUS` already establish elsewhere. Falls back
        to plain nearest-neighbor (unweighted) when no one liked is in
        range — same behavior as before this pass, not a regression for
        an agent with no nearby friends."""
        best: tuple[int, int] | None = None
        best_score: float | None = None
        fallback_best: tuple[int, int] | None = None
        fallback_dist: int | None = None
        for other_id, x, y in position_snapshot:
            if other_id == agent.id or other_id in ostracized_ids:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if fallback_dist is None or dist < fallback_dist:
                fallback_best, fallback_dist = (x, y), dist
            if dist > SOCIALIZE_RELATIONSHIP_RADIUS:
                continue
            relationship = agent.relationships.get(other_id, 0.0)
            if relationship <= 0:
                continue
            score = relationship - dist * SOCIALIZE_DISTANCE_PENALTY
            if best_score is None or score > best_score:
                best, best_score = (x, y), score
        return best if best is not None else fallback_best

    @staticmethod
    def _seek_person_candidate(agent: Agent, agents: list[Agent]) -> tuple[int, str, str, str] | None:
        """v0.87.8, "directed intent" (docs/IDEAS-2026-07-EMERGENCE.md
        §1) — deterministically picks at most one specific living,
        same-settlement agent `agent` has a concrete reason to seek out,
        drawn entirely from existing state (no new tracking added).
        Returns `(target_id, target_name, intent_label, reason_text)`
        or `None` when nothing qualifies (the common case — most agents
        most of the time have no one to specifically confront/console/
        confide in). Checked in a fixed priority order (most emotionally
        urgent first) and returns the FIRST match, not a survey of all
        candidates — this is meant to ground a single cognition-prompt
        suggestion, not to fully rank the settlement.

        - console: someone the agent has a real bond with
          (relationships > 0) whose EMOTION_GRIEF is currently notable —
          the most legible, sympathetic case.
        - confront: someone named in one of the agent's own kept secrets
          (the existing free-text substring convention `dialogue.py`'s
          `_activity` already uses for "a secret about them") whom the
          agent also distrusts (`trust < 0`) — the secret is presumably
          ABOUT a grievance, not a fondly-kept confidence.
        - confide: the agent's most-trusted living partner (`trust`
          strictly positive, highest value), only offered when the
          agent actually holds a secret worth confiding.

        Deliberately does NOT implement "apologize" (the IDEAS doc's
        fourth intent) — that needs real dispute-history tracking this
        codebase doesn't persist per-pair today; flagged as a natural
        follow-up once/if that state exists, not faked here."""
        living = {a.id: a for a in agents if a.settlement_id == agent.settlement_id}
        for other_id, other in living.items():
            if other_id == agent.id:
                continue
            if agent.relationships.get(other_id, 0.0) <= 0.0:
                continue
            if other.emotions.get(EMOTION_GRIEF, 0.0) >= EMOTION_NOTABLE_THRESHOLD:
                return (other_id, other.name, "console", f"{other.name} is grieving")
        if agent.secrets:
            for other_id, other in living.items():
                if other_id == agent.id:
                    continue
                if agent.trust.get(other_id, 0.0) >= 0.0:
                    continue
                if any(other.name in secret for secret in agent.secrets):
                    return (other_id, other.name, "confront", f"a secret concerning {other.name}")
            best_confidant: tuple[int, Agent] | None = None
            best_trust = 0.0
            for other_id, other in living.items():
                if other_id == agent.id:
                    continue
                trust = agent.trust.get(other_id, 0.0)
                if trust > best_trust:
                    best_trust, best_confidant = trust, (other_id, other)
            if best_confidant is not None:
                other_id, other = best_confidant
                return (other_id, other.name, "confide", f"trusts {other.name} most")
        return None

    @staticmethod
    def _step_toward(
        agent: Agent, target: tuple[int, int], terrain: list[list[Tile]],
        predator_tiles: set[tuple[int, int]] = frozenset(), mountain_unlocked: bool = False,
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(), water_capable: bool = False,
    ) -> bool:
        """Take one greedy step toward `target`. Returns False (and leaves
        `agent` unmoved) if already there or if both preferred directions
        are blocked, so the caller can fall back to wandering.

        Avoids stepping onto a live predator's tile when an alternative
        exists — an agent still walks into danger if that's the only way
        forward (e.g. the target itself is past a predator), it just
        doesn't prefer to. See docs/DECISIONS.md, danger pass.

        `water_capable` (v0.87.42): True for an agent currently mounted
        on a READY BOAT — see `_is_walkable`'s matching parameter."""
        tx, ty = target
        if (tx, ty) == (agent.x, agent.y):
            return False
        dx, dy = tx - agent.x, ty - agent.y
        steps = []
        if dx != 0:
            steps.append((1 if dx > 0 else -1, 0))
        if dy != 0:
            steps.append((0, 1 if dy > 0 else -1))

        height = len(terrain)
        width = len(terrain[0]) if height else 0
        fallback: tuple[int, int] | None = None
        for cdx, cdy in steps:
            nx, ny = agent.x + cdx, agent.y + cdy
            if not (
                0 <= nx < width and 0 <= ny < height
                and _is_walkable(terrain, nx, ny, mountain_unlocked, bridge_tiles, water_capable)
            ):
                continue
            if (nx, ny) in predator_tiles:
                fallback = fallback or (nx, ny)
                continue
            agent.x, agent.y = nx, ny
            return True
        if fallback is not None:
            agent.x, agent.y = fallback
            return True
        return False

    @staticmethod
    def _bfs_step(
        terrain: list[list[Tile]], start: tuple[int, int], target: tuple[int, int],
        node_cap: int = 4096, mountain_unlocked: bool = False,
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(),
    ) -> tuple[int, int] | None:
        """First step of a real shortest path from `start` toward
        `target` over walkable tiles. Two callers: a travel_target
        journey's greedy step being blocked (fires immediately — a
        concave water/mountain pocket makes greedy stepping oscillate
        forever, and a fission party must actually arrive), and routine
        goal-directed movement (FORAGE/SOCIALIZE/GATHER/WANDER) once it's
        been greedy-blocked for MOVEMENT_STUCK_TICKS_THRESHOLD consecutive
        ticks (fires rarely, with a smaller node_cap — see
        MOVEMENT_STUCK_BFS_NODE_CAP — so an ordinary tick's population-wide
        cost stays near zero; most agents never trip it). Returns None
        when target is unreachable within `node_cap` expansions (an
        island) — a journey is then abandoned; a stuck routine target
        just falls back to the random walk for that tick instead."""
        if start == target:
            return None
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        first_step: dict[tuple[int, int], tuple[int, int]] = {}
        queue = deque([start])
        seen = {start}
        expanded = 0
        while queue and expanded < node_cap:
            cx, cy = queue.popleft()
            expanded += 1
            for dx, dy in _NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                    continue
                if not _is_walkable(terrain, nx, ny, mountain_unlocked, bridge_tiles):
                    continue
                seen.add((nx, ny))
                first_step[(nx, ny)] = first_step.get((cx, cy), (nx, ny))
                if (nx, ny) == target:
                    return first_step[(nx, ny)]
                queue.append((nx, ny))
        return None

    @staticmethod
    def _reachable_tiles(
        terrain: list[list[Tile]], origin: tuple[int, int],
        bridge_tiles: frozenset[tuple[int, int]] = frozenset(),
    ) -> set[tuple[int, int]]:
        """The walkable connected component containing `origin` — one
        flood fill, used by the engine's fission-site chooser so a
        founding party is never pointed at land it cannot walk to (the
        map's rivers/lakes genuinely disconnect some regions), and by
        `_find_bridge_span` to avoid bridging back to already-reachable
        land."""
        seen = {origin}
        queue = deque([origin])
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in _NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if (
                    0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                    and _is_walkable(terrain, nx, ny, bridge_tiles=bridge_tiles)
                ):
                    seen.add((nx, ny))
                    queue.append((nx, ny))
        return seen

    @staticmethod
    def _maybe_move(
        agent: Agent, terrain: list[list[Tile]], rng: random.Random, roads: RoadNetwork,
        predator_tiles: set[tuple[int, int]] = frozenset(), speed_multiplier: float = 1.0,
        weather: WeatherState | None = None,
    ) -> None:
        move_chance = MOVE_CHANCE
        if roads.is_road(agent.x, agent.y):
            # Weather affects infrastructure, not just people: an
            # established road's bonus shrinks (mud) or can even go
            # negative (snow/ice) depending on current conditions. See
            # world/roads.py's road_condition_multiplier, docs/DECISIONS.md,
            # "LLM-as-brain batch." `paved` (v0.87.43): a genuinely paved
            # tile reads a better weather-band multiplier throughout.
            paved = roads.is_paved(agent.x, agent.y)
            road_multiplier = (
                road_condition_multiplier(weather, paved) if weather is not None
                else (ROAD_PAVED_SPEED_MULTIPLIER if paved else ROAD_SPEED_MULTIPLIER)
            )
            move_chance = min(1.0, move_chance * road_multiplier)
        if speed_multiplier != 1.0:
            move_chance = min(1.0, move_chance * speed_multiplier)
        if rng.random() >= move_chance:
            return
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        candidates = []
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = agent.x + dx, agent.y + dy
            if 0 <= nx < width and 0 <= ny < height and _is_walkable(terrain, nx, ny):
                candidates.append((nx, ny))
        # Prefer avoiding a predator's tile, but don't strand an agent
        # surrounded by them — fall back to the unfiltered set if that's
        # all that's walkable.
        safe_candidates = [c for c in candidates if c not in predator_tiles]
        if safe_candidates:
            candidates = safe_candidates
        # Live report: idle wandering visibly paces back and forth
        # ("goes up-down one tile or left-right one tile") — with only
        # 4 candidate directions (_NEIGHBOR_OFFSETS has no diagonals), a
        # uniform random walk reverses its own last step 1-in-4 times,
        # which reads as pacing in place rather than actually going
        # anywhere. Deprioritize stepping straight back the way the
        # agent just came, falling back to it only if it's the sole
        # walkable option (a dead-end corridor). See Agent.last_move_dx/
        # dy's docstring.
        if agent.last_move_dx or agent.last_move_dy:
            reverse = (agent.x - agent.last_move_dx, agent.y - agent.last_move_dy)
            non_reverse = [c for c in candidates if c != reverse]
            if non_reverse:
                candidates = non_reverse
        if candidates:
            nx, ny = rng.choice(candidates)
            agent.last_move_dx, agent.last_move_dy = nx - agent.x, ny - agent.y
            agent.x, agent.y = nx, ny

    @staticmethod
    def _update_roads(
        by_position: dict[tuple[int, int], list[Agent]], settlements: list[Settlement],
        farms: FarmGrid, roads: RoadNetwork,
        road_scars: dict[tuple[int, int], float] | None = None,
    ) -> list[tuple[str, str]]:
        """Tiles with at least one awake agent present, excluding
        building/farm tiles (paths form between things, not on top of
        them) — see docs/DECISIONS.md, C5.

        M1/M9 "The Living Map": `road_scars` (optional — `World.
        road_scars`, `None` reproduces the exact pre-M1/M9 behavior)
        gets a real mark (`terrain_evolution.apply_road_scar`) for
        every position `roads.tick()` reports as a just-abandoned
        ESTABLISHED road — a fully-decayed road no longer vanishes
        without a trace."""
        occupied = {
            (x, y) for (x, y), group in by_position.items()
            if any(a.state is AgentState.AWAKE for a in group)
            and all(s.at(x, y) is None for s in settlements) and farms.get(x, y) is None
        }
        # v0.87.43: paving is a world-wide capability once ANY settlement
        # has reached `modern`+ — roads are shared physical
        # infrastructure, not settlement-private (same shape BRIDGE
        # already has), so no single settlement's era alone gates it.
        paving_unlocked = any(s.era in ERA_UNLOCKS_AUTOMOBILE for s in settlements)
        abandoned = roads.tick(occupied, paving_unlocked)
        if not abandoned or road_scars is None:
            return []
        for pos in abandoned:
            apply_road_scar(pos, road_scars)
        return [(
            "road_scarred",
            f"{len(abandoned)} old road bed{'s' if len(abandoned) != 1 else ''} left behind as travel moved on.",
        )]

    @staticmethod
    def _update_relationships(by_position: dict[tuple[int, int], list[Agent]]) -> None:
        agents_by_id = {a.id: a for group in by_position.values() for a in group}
        for agent in agents_by_id.values():
            # Pulls toward 0 from whichever side it's on — relationship
            # values range -1..1 as of E2 (rivalry as well as affinity),
            # so decay can no longer just clamp at a 0.0 floor. A pair
            # that decays exactly to 0.0 (or was already there — a
            # single transient encounter that never grew past one tick's
            # gain) is pruned from the dict entirely: `.get(id, 0.0)`
            # reads it identically to an absent key either way, so this
            # changes no observable behavior, but without it every pair
            # that ever shared a tile anywhere in the world's history
            # stayed in the dict forever — measured at ~94 relationship
            # entries per agent after only 5,000 ticks at population 125
            # (near-total connectivity in a young population), the
            # dominant driver of unbounded RAM growth on a long-running,
            # high-population world. See docs/DECISIONS.md, "memory
            # leak: unpruned relationships" pass.
            for other_id in list(agent.relationships):
                if agent.relationship_flags.get(other_id) == "feud":
                    # Tier 0.1 "significant state stops decaying to
                    # zero": a hardened feud holds at whatever depth it
                    # deepened to until an explicit reconcile/council_
                    # ruling clears the flag (apply_dispute below) — see
                    # Agent.relationship_flags's docstring.
                    continue
                value = agent.relationships[other_id]
                if _native_relationship_decay_step is not None:
                    value = _native_relationship_decay_step(value, RELATIONSHIP_DECAY_PER_TICK)
                elif value > 0.0:
                    value = max(0.0, value - RELATIONSHIP_DECAY_PER_TICK)
                elif value < 0.0:
                    value = min(0.0, value + RELATIONSHIP_DECAY_PER_TICK)
                if value == 0.0:
                    del agent.relationships[other_id]
                else:
                    agent.relationships[other_id] = value
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                if a.relationship_flags.get(b.id) == "feud" or b.relationship_flags.get(a.id) == "feud":
                    # A locked feud doesn't quietly warm back up just
                    # from standing near each other, same "resolves only
                    # explicitly" rule as the decay skip above.
                    continue
                if _native_relationship_gain_step is not None:
                    a.relationships[b.id] = _native_relationship_gain_step(
                        a.relationships.get(b.id, 0.0), RELATIONSHIP_GAIN_PER_TICK_COLOCATED, 1.0,
                    )
                    b.relationships[a.id] = _native_relationship_gain_step(
                        b.relationships.get(a.id, 0.0), RELATIONSHIP_GAIN_PER_TICK_COLOCATED, 1.0,
                    )
                else:
                    a.relationships[b.id] = min(
                        1.0, a.relationships.get(b.id, 0.0) + RELATIONSHIP_GAIN_PER_TICK_COLOCATED
                    )
                    b.relationships[a.id] = min(
                        1.0, b.relationships.get(a.id, 0.0) + RELATIONSHIP_GAIN_PER_TICK_COLOCATED
                    )

    @staticmethod
    def _maybe_teach_skills(
        by_position: dict[tuple[int, int], list[Agent]], rng: random.Random,
        settlements: list[Settlement],
    ) -> None:
        """H5 (docs/ROADMAP.md "Phase H"): knowledge spreads through
        teaching, not only solo practice (see the farming-skill gain in
        `_maybe_forage`). A colocated pair with a wide enough skill gap
        has a small per-tick chance of the more skilled agent teaching
        the less skilled one — same colocation-driven contagion shape as
        `_update_relationships`'s gain loop and dialogue's gossip
        contagion. Skill-name-agnostic — H5 extension added
        SKILL_CONSTRUCTION as a second skill, and the "continue
        expanding, round three" pass added SKILL_MEDICINE as a third,
        both with no changes needed here beyond listing them below.

        Integration milestone: the base chance is no longer a flat
        constant — it's scaled by both agents' average sociability
        (TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE, closing that
        trait's write-only loop), boosted when teacher and learner
        share a living FAMILY or COUNCIL institution (learning from
        your own family or elders is more effective than a stranger's
        passing lesson), and boosted further by a 'knowledge' tradition
        (culture_effect_multiplier — a village that has come to value
        apprenticeship teaches faster, the same mechanical-rider shape
        festivals/harvests/grief already use)."""
        knowledge_by_id = {
            s.id: culture_effect_multiplier(s.culture_effects, "knowledge") for s in settlements
        }
        default_knowledge = knowledge_by_id[settlements[0].id]
        settlements_by_id = {s.id: s for s in settlements}
        # Membership index built once per tick (audit perf pass): the
        # previous per-pair `any()` over the full institutions list was
        # O(colocated pairs x stored institutions) — with the stored
        # FAMILY list allowed to reach INSTITUTION_LIST_MAX_STORED (300)
        # and crowding routinely producing 20+-agent tiles (hundreds of
        # pairs), that scan alone reached six figures of iterations per
        # tick. Same results, one pass over institutions instead.
        bonded_memberships: dict[int, set[int]] = {}  # agent id -> FAMILY/COUNCIL institution ids
        guild_members: dict[str, set[int]] = {}  # skill name -> that guild's member agent ids
        all_institutions = [inst for s in settlements for inst in s.institutions]
        for inst in all_institutions:
            if inst.kind in (InstitutionKind.FAMILY, InstitutionKind.COUNCIL):
                for member_id in inst.member_agent_ids:
                    bonded_memberships.setdefault(member_id, set()).add(inst.id)
            elif inst.kind is InstitutionKind.GUILD and inst.name:
                guild_members.setdefault(inst.name, set()).update(inst.member_agent_ids)
        no_memberships: set[int] = set()
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                shared_institution = bool(
                    bonded_memberships.get(a.id, no_memberships)
                    & bonded_memberships.get(b.id, no_memberships)
                )
                sociability = (a.traits.get(TRAIT_SOCIABILITY, 0.0) + b.traits.get(TRAIT_SOCIABILITY, 0.0)) / 2.0
                # A knowledge-minded tradition helps the lesson if EITHER
                # party's community carries it — customs travel with the
                # person, not the tile.
                knowledge_multiplier = max(
                    knowledge_by_id.get(a.settlement_id, default_knowledge),
                    knowledge_by_id.get(b.settlement_id, default_knowledge),
                )
                chance = SKILL_TEACHING_CHANCE_PER_TICK * (
                    1.0 + sociability * TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE
                ) * knowledge_multiplier
                if shared_institution:
                    chance *= INSTITUTION_TEACHING_BONUS_MULTIPLIER
                for skill in (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE):
                    a_level, b_level = a.skills.get(skill, 0.0), b.skills.get(skill, 0.0)
                    gap = a_level - b_level
                    if abs(gap) < SKILL_TEACHING_MIN_GAP:
                        continue
                    skill_chance = chance
                    # H3 v4: a shared guild for THIS trade specifically
                    # is a stronger teaching bonus than the trade-
                    # agnostic FAMILY/COUNCIL one above — expertise-
                    # sharing, not just bonding. Stacks multiplicatively.
                    members = guild_members.get(skill)
                    if members is not None and a.id in members and b.id in members:
                        skill_chance *= GUILD_TEACHING_BONUS_MULTIPLIER
                    if rng.random() >= skill_chance:
                        continue
                    teacher, learner = (a, b) if gap > 0 else (b, a)
                    learner.skills[skill] = min(
                        teacher.skills[skill], learner.skills.get(skill, 0.0) + SKILL_TEACHING_GAIN
                    )
                # v0.87.15 "knowledge lifecycle" (docs/IDEAS-2026-07-
                # EMERGENCE.md §7): a colocated pair sharing a settlement
                # may pass along a tracked, non-dormant invention exactly
                # like a skill — same chance/bonus shape, bounded to
                # INVENTION_KNOWLEDGE_MAX_TRACKED entries so this never
                # scales with the full 300-cap `inventions` history.
                # Cross-settlement diffusion (a knower migrating, a
                # caravan) is deliberately out of scope this pass.
                if a.settlement_id == b.settlement_id:
                    home = settlements_by_id.get(a.settlement_id)
                    if home is not None and home.invention_knowledge:
                        for entry, info in home.invention_knowledge.items():
                            if info.get("dormant"):
                                continue
                            knowers = info.get("knowers", [])
                            a_knows, b_knows = a.id in knowers, b.id in knowers
                            if a_knows == b_knows:
                                continue
                            if rng.random() >= chance:
                                continue
                            learner = b if a_knows else a
                            knowers.append(learner.id)

    @staticmethod
    def _theft_forbidden_by_law(settlement: "Settlement") -> bool:
        """Item 8c ("laws & customs"): does this settlement have a
        codified norm against theft? Cheap substring check over a
        LAWS_MAX_STORED-capped list — never a hot-path concern."""
        return any(
            "theft" in entry.get("text", "").lower() or "steal" in entry.get("text", "").lower()
            for entry in settlement.laws
        )

    @staticmethod
    def _maybe_commit_theft(
        by_position: dict[tuple[int, int], list[Agent]], rng: random.Random,
        settlements: list[Settlement], life_events: list,
    ) -> None:
        """Item 8a ("crime & theft", docs/IDEAS-2026-07-EMERGENCE.md
        item 8 follow-up) — entirely deterministic, zero LLM cost: this
        is a physical act (who has food, who doesn't), not an act of
        interpretation. Reuses the same colocation loop `_maybe_teach_
        skills` already walks per tick rather than a second O(agents^2)
        pass. A desperate, distrustful agent colocated with someone
        holding meaningfully more personal food may take some of it —
        the deterministic engine modeling `Population._maybe_reproduce`/
        `_maybe_trade_food`'s existing personal-food-inventory mechanic
        finally has a coercive counterpart to its voluntary one.
        Consequences land only on the victim's read of the thief
        (asymmetric distrust, same shape dialogue/dispute use), and a
        `family_feud`-style law-signal counter feeds `_maybe_schedule_
        laws` — repeated theft is the raw material a settlement can
        eventually codify a real taboo against, which then sharpens this
        very mechanic's own penalty (`_theft_forbidden_by_law`)."""
        settlements_by_id = {s.id: s for s in settlements}
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                for thief, victim in ((a, b), (b, a)):
                    if thief.hunger < THEFT_HUNGER_THRESHOLD:
                        continue
                    if thief.trust.get(victim.id, 0.0) >= THEFT_TRUST_THRESHOLD:
                        continue
                    thief_food = thief.inventory.get("food", 0.0)
                    victim_food = victim.inventory.get("food", 0.0)
                    if victim_food - thief_food < THEFT_FOOD_MARGIN:
                        continue
                    if rng.random() >= THEFT_CHANCE_PER_TICK:
                        continue
                    amount = victim_food * THEFT_FOOD_FRACTION
                    victim.inventory["food"] = victim_food - amount
                    thief.inventory["food"] = min(PERSONAL_FOOD_CAPACITY, thief_food + amount)
                    home = settlements_by_id.get(victim.settlement_id)
                    law_penalty = THEFT_LAW_PENALTY_MULT if home is not None and Population._theft_forbidden_by_law(home) else 1.0
                    victim.trust[thief.id] = max(-1.0, victim.trust.get(thief.id, 0.0) + THEFT_TRUST_PENALTY * law_penalty)
                    victim.relationships[thief.id] = max(
                        -1.0, victim.relationships.get(thief.id, 0.0) + THEFT_RELATIONSHIP_PENALTY * law_penalty
                    )
                    bump_emotion(victim, EMOTION_ANGER, EMOTION_DISPUTE_ANGER_BUMP)
                    _nudge_trait(victim, TRAIT_SOCIABILITY, TRAIT_THEFT_VICTIM_SOCIABILITY_NUDGE)
                    _remember(victim, f"{thief.name} stole food from me while I wasn't looking.", because=f"{thief.name} stole from me")
                    add_grievance(victim, thief.id, f"{thief.name} stole food from me.")
                    _remember(thief, f"I took food from {victim.name} out of desperation.", routine=True)
                    # §1 "deviance loop" completion: the act now plants a
                    # real secret on the thief (not just a routine
                    # memory) — joins the same secrets lifecycle disputes
                    # already established (guarded, released at death,
                    # distorted by rumor). If a third colocated agent
                    # witnesses it, they remember it too — the classic
                    # deviance -> gossip seed, reaching dialogue/beliefs
                    # for free through the existing memory-grounded
                    # prompts, without a bespoke broadcast.
                    push_secret(thief, THEFT_SECRET_TEXT_TEMPLATE.format(name=victim.name))
                    witnesses = [w for w in group if w.id not in (thief.id, victim.id)]
                    if witnesses and rng.random() < THEFT_WITNESS_RUMOR_CHANCE:
                        witness = witnesses[0]
                        _remember(witness, f"I saw {thief.name} steal food from {victim.name}.", because=f"witnessed {thief.name} steal")
                    if home is not None:
                        home.thefts_committed += 1
                        counts = home.law_signal_counts
                        counts["theft"] = counts.get("theft", 0) + 1
                        life_events.append(("theft", f"{thief.name} took food from {victim.name}."))
                    break  # one theft resolution per pair per tick

    @staticmethod
    def _granary_fill_ratio(settlement: Settlement) -> float:
        """0..1 how full a settlement's standing granaries run — the
        deterministic "is life better over there" signal `_maybe_
        migrate`'s hunger-driven pull reads, same underlying buildings
        `_maybe_stock_granaries`/`_maybe_welcome_migrant` already use."""
        granaries = [
            b for b in settlement.buildings
            if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
        ]
        if not granaries:
            return 0.0
        capacity = len(granaries) * GRANARY_CAPACITY
        return sum(b.stored_food for b in granaries) / capacity if capacity else 0.0

    def _housing_pressure(self, settlement: Settlement) -> float:
        """population / housing-capacity — >1.0 means the settlement is
        genuinely overcrowded for its standing huts. §2 "refugees after
        disasters" (docs/IDEAS-2026-07-EMERGENCE.md) reads this as
        `_maybe_migrate`'s disaster-driven push signal: a disaster that
        ruins huts drops capacity here directly (no separate disaster-
        detection needed), the same causal chain the idea names, just
        reached through the housing math that's already computed
        elsewhere (`tick`'s own `crowded_by_id`) rather than duplicated
        state. `float('inf')` for a settlement with no standing huts and
        a living population — maximally overcrowded, not a division
        error."""
        capacity = CAMP_TOLERANCE + HUT_CAPACITY * hut_capacity_multiplier(settlement.era) * sum(
            1 for b in settlement.buildings if b.kind is BuildingKind.HUT and b.stage is BuildingStage.STANDING
        )
        population = settlement.living_member_count(self.agents)
        return population / capacity if capacity else float("inf")

    def migration_push_target(
        self, agent: "Agent", home: Settlement, by_id: dict[int, Settlement],
    ) -> tuple[Settlement, str] | None:
        """The objective half of migration (§1 "migration by choice,
        not just fission", docs/IDEAS-2026-07-EMERGENCE.md): the real
        push/pull facts already tracked elsewhere — ostracism
        (`standing_penalty`), family feud pressure (`Institution.
        feuds`), genuine starvation next to a meaningfully better-fed
        sister settlement, real overcrowding (§2 "refugees after
        disasters" — see `_housing_pressure`), or a bonded partner
        already living elsewhere — priority-ordered exactly as before.
        Returns `(target_settlement, push_reason)` or `None`. Extracted
        from the old monolithic `_maybe_migrate` (explicit user
        directive, "expand genuine decision points" audit) so the
        WHETHER-they-actually-go half can split by agent: a core-cast
        member's own life circumstances deserve a real weighed decision
        (`SimulationEngine._maybe_schedule_migration_decision`, `llm/
        migration.py`, mirroring `llm/fission.py`'s "they weighed the
        leap and stayed" shape exactly); everyone else keeps the
        original flat-chance-roll path in `_maybe_migrate` below,
        unchanged, for call-volume reasons (CLAUDE.md's standing
        per-agent LLM-gating rule)."""
        alternatives = [s for s in by_id.values() if s.id != home.id]
        if not alternatives:
            return None
        bonded_settlement = None
        for other_id, value in agent.relationships.items():
            if value < MIGRATION_BOND_THRESHOLD:
                continue
            partner = self.get(other_id)
            if partner is not None and partner.settlement_id in by_id and partner.settlement_id != home.id:
                bonded_settlement = by_id[partner.settlement_id]
                break
        my_family = self.family_of(agent.id, home)
        feud_pressure = my_family is not None and bool(my_family.feuds)
        if bonded_settlement is not None:
            return bonded_settlement, "a bonded partner already living there"
        if agent.hunger >= MIGRATION_STARVATION_HUNGER_THRESHOLD:
            best = max(alternatives, key=self._granary_fill_ratio)
            if self._granary_fill_ratio(best) - self._granary_fill_ratio(home) >= MIGRATION_GRANARY_ADVANTAGE:
                return best, "hunger here against real food security there"
        elif self._housing_pressure(home) >= MIGRATION_HOUSING_PRESSURE_THRESHOLD:
            best = min(alternatives, key=self._housing_pressure)
            if self._housing_pressure(best) < self._housing_pressure(home):
                return best, "overcrowding here against real room there"
        elif agent.standing_penalty > 0.0 or feud_pressure:
            return max(alternatives, key=self._granary_fill_ratio), "no longer welcome here"
        return None

    def core_migration_candidates(self, settlements: list[Settlement]) -> list[tuple["Agent", Settlement, str]]:
        """The core-cast half of migration candidacy — every living
        core-cast member with a real push/pull target and no journey
        already underway. `SimulationEngine._maybe_schedule_migration_
        decision` schedules at most one LLM decision per tick from
        this list (same volume discipline as every other per-agent
        core-cast job)."""
        named = [s for s in settlements if s.name]
        if len(named) < 2:
            return []
        by_id = {s.id: s for s in named}
        candidates: list[tuple["Agent", Settlement, str]] = []
        for agent in self.agents:
            if agent.id not in self.core_agent_ids:
                continue
            home = by_id.get(agent.settlement_id)
            if home is None or agent.travel_target is not None:
                continue
            found = self.migration_push_target(agent, home, by_id)
            if found is not None:
                candidates.append((agent, found[0], found[1]))
        return candidates

    def depart_for_migration(self, agent: "Agent", home: Settlement, target: Settlement) -> str:
        """Apply a real migration decision (from either path — the
        deterministic roll below, or a genuine LLM "yes" via `llm/
        migration.py`): reassigns settlement, resets `standing_penalty`
        (a fresh settlement doesn't know what the old one held against
        someone — a genuine second chance), sets `travel_target` so the
        agent physically walks there via the existing journey
        machinery, and nudges settlement-level relations toward warmer
        (§2 "settlement-level stance": increased contact reads as
        modest symmetric warming). Returns the life-event description."""
        origin_name = home.name
        agent.settlement_id = target.id
        agent.standing_penalty = 0.0
        center = target.center()
        if center is not None:
            agent.travel_target = center
        _remember(agent, f"I left {origin_name} for {target.name}.", because=f"migrated to {target.name}")
        new_relation = min(1.0, home.relations.get(target.id, 0.0) + RELATION_MIGRATION_NUDGE)
        home.relations[target.id] = new_relation
        target.relations[home.id] = new_relation
        return f"{agent.name} left {origin_name} to make a life in {target.name}."

    def _maybe_migrate(self, rng: random.Random, settlements: list[Settlement]) -> list[tuple[str, str]]:
        """The non-core-cast path: same flat per-tick chance roll as
        before this pass, now reading its candidate target via the
        shared `migration_push_target` — core-cast agents are excluded
        here (see that method's docstring) since they're handled by a
        real weighed LLM decision instead. See docs/DECISIONS.md /
        `migration_push_target`'s docstring for the full design note."""
        named = [s for s in settlements if s.name]
        if len(named) < 2:
            return []
        by_id = {s.id: s for s in named}
        life_events: list[tuple[str, str]] = []
        for agent in self.agents:
            if agent.id in self.core_agent_ids:
                continue
            home = by_id.get(agent.settlement_id)
            if home is None or agent.travel_target is not None:
                continue
            found = self.migration_push_target(agent, home, by_id)
            if found is None or rng.random() >= MIGRATION_CHANCE_PER_TICK:
                continue
            target, _reason = found
            description = self.depart_for_migration(agent, home, target)
            life_events.append(("migrant_departed", description))
        return life_events

    def _tick_traits(self, rng: random.Random) -> None:
        """H6: a monthly bounded random walk on every living agent's
        trait vector — the same TRAIT_MEAN_REVERSION-toward-0/step-noise
        shape `tick_temperament`/`tick_player_standing` already use at
        the settlement level, reused here per-agent so a trait recovers
        toward neutral over time without repeated reinforcement, same as
        temperament does. Called once per real month boundary (see
        `tick`'s `month_end` param), not every tick — 400 agents each
        taking a step every tick would drift far faster than intended
        and cost real per-tick CPU for no observable benefit between
        month boundaries."""
        for agent in self.agents:
            for trait in (TRAIT_RESILIENCE, TRAIT_SOCIABILITY, TRAIT_AMBITION, TRAIT_OPENNESS):
                if trait in agent.hardened_traits:
                    continue  # Phase 3.B: a hardened trait is exempt from reversion, permanently
                current = agent.traits.get(trait, 0.0)
                step = rng.uniform(-TRAIT_STEP_MAX, TRAIT_STEP_MAX)
                reversion = _TRAIT_MEAN_REVERSION_BY_TRAIT.get(trait, TRAIT_MEAN_REVERSION)
                agent.traits[trait] = clamp(current * reversion + step, -1.0, 1.0)
            # §1 "deviance loop": ostracism fades on its own over months
            # rather than standing forever — see Agent.standing_penalty.
            if agent.standing_penalty > 0.0:
                agent.standing_penalty = max(0.0, agent.standing_penalty - STANDING_PENALTY_DECAY_PER_MONTH)

    def carrying_capacity(
        self, settlement: Settlement, housing_capacity: int, weather_harsh: bool, predator_pressure: bool,
        established_roads: int = 0, members: "list[Agent] | None" = None, map_tiles: int | None = None,
    ) -> float:
        """Dynamic carrying capacity (H1, docs/ROADMAP.md Phase H):
        composes housing (the base), economy, security, and labor/
        environment pressure into one number that moves with the
        settlement's actual situation, the same way food already gates
        reproduction via the surplus check below — rather than a flat
        scalar being the only real constraint. Called once per tick
        from `tick()`; the result also drives `_maybe_reproduce`'s gate
        and is exposed via `summary()`. Integration milestone: also
        reads institutional coordination (a sitting council), aggregate
        population skill (knowledge), and road infrastructure —
        previously this function only ever read housing/economy/
        security/labor/weather, leaving three real, effortful systems
        with no way to expand what a settlement can actually support.

        `map_tiles` (live-report finding): the final safety-valve
        ceiling below is `dynamic_population_cap(map_tiles)`, not the
        flat `POPULATION_CAP` — a settlement that fills a large map
        with housing shouldn't hit the same hard number a tiny map
        would. `None` (a caller not passing map area) keeps the old
        flat-`POPULATION_CAP` behavior unchanged."""
        # Multi-settlement pass: capacity is per community — `members`
        # scopes the human terms (sickness, labor) to this settlement's
        # own people; None keeps the legacy whole-population behavior.
        members = self.agents if members is None else members
        total = len(members)
        granaries = [
            b for b in settlement.buildings
            if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
        ]
        granary_capacity = len(granaries) * GRANARY_CAPACITY
        if granary_capacity > 0:
            granary_fill = sum(b.stored_food for b in granaries) / granary_capacity
            economy_term = (granary_fill - 0.5) * 2.0 * CARRYING_CAPACITY_ECONOMY_WEIGHT
        else:
            # No granary yet isn't a penalty — a founding party hasn't had
            # time to build infrastructure it wouldn't need at this scale.
            economy_term = 0.0

        # Direct food-security signal (v0.87.24) — always scored, no
        # granary prerequisite. See CARRYING_CAPACITY_HUNGER_WEIGHT's
        # docstring for why this closes the real starvation-collapse gap:
        # economy_term above only engages once a granary exists (and even
        # then can be swamped by a fixed-size granary against a grown
        # population); this reads the community's actual lived hunger.
        avg_member_hunger = (sum(a.hunger for a in members) / total) if total else 0.0
        hunger_term = -max(0.0, avg_member_hunger - CARRYING_CAPACITY_HUNGER_COMFORT) * CARRYING_CAPACITY_HUNGER_WEIGHT / (1.0 - CARRYING_CAPACITY_HUNGER_COMFORT)

        sick_fraction = (sum(1 for a in members if a.sick_ticks > 0) / total) if total else 0.0
        security_term = -(
            sick_fraction * 2.0 + (0.3 if predator_pressure else 0.0)
        ) * CARRYING_CAPACITY_SECURITY_WEIGHT

        # A14 "Layered organism biology," fourth slice: each mature,
        # healthy adult contributes their own real `development`
        # reading (capped 1.0) instead of a flat +1 — a chronologically
        # mature young adult who grew up through a hard famine
        # contributes measurably less labor capacity than a fully-
        # grown peer, even though both pass the same binary maturity
        # gate. See DEVELOPMENT_LABOR_WEIGHT's docstring.
        working_age = sum(
            min(1.0, a.development) * DEVELOPMENT_LABOR_WEIGHT
            for a in members if self._is_mature(a) and self._is_healthy(a)
        )
        labor_fraction = (working_age / total) if total else 1.0
        labor_term = (labor_fraction - 0.5) * CARRYING_CAPACITY_LABOR_WEIGHT

        environment_term = (-0.5 if weather_harsh else 0.2) * CARRYING_CAPACITY_ENVIRONMENT_WEIGHT

        council = settlement.council()
        if council is not None:
            disposition = self.council_disposition(council)
            # A council with nobody left alive on it coordinates nothing —
            # see _maybe_refresh_council for why that shouldn't happen in
            # practice, but this stays correct even in the gap tick
            # before a refresh fills an opened seat.
            governance_quality = (disposition["avg_ambition"] + disposition["avg_resilience"]) / 2.0 + 0.5
            # MAYOR (v0.87.44): a living mayor is real dedicated
            # leadership on top of the council's own disposition — a
            # small, bounded governance-quality nudge, not a
            # replacement for council composition mattering.
            if any(a.occupation == OCCUPATION_MAYOR for a in members):
                governance_quality += MAYOR_REPUTATION_NUDGE
            coordination_term = (
                governance_quality * CARRYING_CAPACITY_COORDINATION_WEIGHT if disposition["size"] else 0.0
            )
        else:
            coordination_term = 0.0

        avg_skill = (
            sum(
                a.skills.get(SKILL_FARMING, 0.0) + a.skills.get(SKILL_CONSTRUCTION, 0.0)
                + a.skills.get(SKILL_MEDICINE, 0.0) for a in self.agents
            ) / (3 * total) if total else 0.0
        )
        knowledge_term = avg_skill * CARRYING_CAPACITY_KNOWLEDGE_WEIGHT

        roads_per_capita = (established_roads / total) if total else 0.0
        infrastructure_term = (
            min(1.0, roads_per_capita / CARRYING_CAPACITY_ROADS_PER_CAPITA_SATURATION)
            * CARRYING_CAPACITY_INFRASTRUCTURE_WEIGHT
        )
        # Integration milestone (water/power/irrigation follow-up): a
        # standing POWER_PLANT is a second, smaller infrastructure
        # signal alongside road density — roads stay dominant.
        if settlement.has_power_plant():
            infrastructure_term += CARRYING_CAPACITY_POWER_PLANT_BONUS

        multiplier = (
            1.0 + hunger_term + economy_term + security_term + labor_term + environment_term
            + coordination_term + knowledge_term + infrastructure_term
        )
        multiplier = max(CARRYING_CAPACITY_MIN_MULTIPLIER, min(CARRYING_CAPACITY_MAX_MULTIPLIER, multiplier))
        return min(dynamic_population_cap(map_tiles), housing_capacity * multiplier)

    def _maybe_reproduce(
        self, by_position: dict[tuple[int, int], list[Agent]], rng: random.Random,
        capacity_by_id: dict[int, float], settlements: list[Settlement], tick: int,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        total_capacity = sum(capacity_by_id.values())
        if len(self.agents) >= total_capacity:
            return life_events
        settlements_by_id = {s.id: s for s in settlements}
        primary = settlements[0]
        home_counts: dict[int, int] = {s.id: 0 for s in settlements}
        hunger_sum_by_id: dict[int, float] = {s.id: 0.0 for s in settlements}
        for member in self.agents:
            home_id = member.settlement_id if member.settlement_id in settlements_by_id else primary.id
            home_counts[home_id] += 1
            hunger_sum_by_id[home_id] += member.hunger
        # Settlement-wide hunger ceiling (v0.87.24 starvation-collapse
        # fix): a hard backstop alongside carrying_capacity's softer
        # hunger_term throttle — the capacity term reacts smoothly and
        # bounds new HEADROOM, but a couple whose slot was already open
        # before that throttle caught up could otherwise still slip a
        # birth through into a settlement that is visibly, communally
        # starving. This blocks that regardless of the two parents' own
        # (possibly still-fine) personal state.
        avg_hunger_by_id = {
            s.id: (hunger_sum_by_id[s.id] / home_counts[s.id]) if home_counts[s.id] else 0.0
            for s in settlements
        }

        newborns: list[Agent] = []
        newborn_names: set[str] = set()
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                if len(self.agents) + len(newborns) >= total_capacity:
                    break
                # A child is born into its parents' community and counts
                # against THAT settlement's carrying capacity — growth
                # pressure is local, which is exactly what eventually
                # makes a crowded settlement fission.
                home = settlements_by_id.get(a.settlement_id, primary)
                if home_counts[home.id] >= capacity_by_id.get(home.id, total_capacity):
                    continue
                if not (self._is_mature(a) and self._is_mature(b)):
                    continue
                if not (self._is_healthy(a) and self._is_healthy(b)):
                    continue
                affinity_needed = REPRODUCTION_AFFINITY_THRESHOLD
                romeo_and_juliet = self.families_feuding(
                    self.family_of(a.id, home), self.family_of(b.id, home),
                )
                if romeo_and_juliet:
                    # v0.87.11 "generational feuds": a real cost, not a
                    # hard block — courtship across the feud line just
                    # needs a stronger bond to overcome it. See
                    # FAMILY_FEUD_AFFINITY_PENALTY's docstring.
                    affinity_needed += FAMILY_FEUD_AFFINITY_PENALTY
                if a.relationships.get(b.id, 0.0) < affinity_needed:
                    continue
                if avg_hunger_by_id.get(home.id, 0.0) >= REPRODUCTION_SETTLEMENT_HUNGER_CEILING:
                    continue
                # Surplus gate (carrying-capacity rework, July 2026
                # review): children follow surplus — either parent has
                # personal food set aside, or both are clearly well-fed
                # (far stricter than _is_healthy's not-starving bar).
                # This is what couples demography to the food economy:
                # a hard winter or a rotted harvest now shows up in the
                # birth rate, not just the death rate.
                has_surplus = (
                    a.inventory.get("food", 0.0) > 0.0 or b.inventory.get("food", 0.0) > 0.0
                    or (a.hunger <= REPRODUCTION_WELLFED_HUNGER and b.hunger <= REPRODUCTION_WELLFED_HUNGER)
                )
                if not has_surplus:
                    continue
                # A14 "Layered organism biology," second slice: chronic
                # stress is a real, bounded (never total) drag on the
                # reproduction roll — see STRESS_REPRODUCTION_PENALTY_
                # WEIGHT's docstring.
                avg_stress = (a.stress + b.stress) / 2.0
                # A14 "Layered organism biology," fifth slice: real
                # age-based reproductive biology stacks with the
                # psychological stress drag above — two independent
                # signals on the same roll, not competing gates. See
                # FERTILITY_REPRODUCTION_WEIGHT's docstring.
                avg_fertility = (a.fertility + b.fertility) / 2.0
                effective_chance = REPRODUCTION_CHANCE_PER_TICK * (
                    1.0 - avg_stress * STRESS_REPRODUCTION_PENALTY_WEIGHT
                ) * avg_fertility * FERTILITY_REPRODUCTION_WEIGHT
                if rng.random() >= effective_chance:
                    continue

                child_name = self._unique_name(rng, extra_taken=newborn_names)
                newborn_names.add(child_name)
                child_genome, child_traits = _inherited_genome_and_traits(a, b, rng)
                child = Agent(
                    id=self._next_id,
                    name=child_name,
                    x=a.x,
                    y=a.y,
                    max_age_ticks=rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS),
                    parents=(a.id, b.id),
                    settlement_id=home.id,
                    genome=child_genome,
                    traits=child_traits,
                )
                self._next_id += 1
                newborns.append(child)
                home_counts[home.id] += 1
                if romeo_and_juliet:
                    life_events.append((
                        "birth",
                        f"{child.name} was born to {a.name} and {b.name} — a union across "
                        "their families' long feud.",
                    ))
                else:
                    life_events.append(("birth", f"{child.name} was born to {a.name} and {b.name}."))
                # Generational memory: a newborn "knows" its parents from
                # birth (looked up by id later — parent names can change
                # by nothing here, but this fixes the names at the
                # moment they mattered), and the parents remember the
                # birth too. See docs/DECISIONS.md, interventions/
                # family-memory pass.
                _remember(child, f"I was born to {a.name} and {b.name}.")
                _remember(a, f"{child.name} was born to us.")
                _remember(b, f"{child.name} was born to us.")
                bump_emotion(a, EMOTION_JOY, EMOTION_BIRTH_JOY_BUMP)
                bump_emotion(b, EMOTION_JOY, EMOTION_BIRTH_JOY_BUMP)
                # Phase 1.B "self-evolving world": a child born is
                # squarely "success," one of the doc's named life
                # events eligible to reshape a standing ambition.
                a.life_event_since_goal = True
                b.life_event_since_goal = True
                family_event = self._extend_family(home, tick, a.id, b.id, child.id, a.name, b.name)
                if family_event is not None:
                    life_events.append(family_event)
                    _prune_extinct_families(home, {a.id for a in self.agents})
                    # v0.87.10, "ceremonies agents attend: weddings"
                    # (docs/IDEAS-2026-07-EMERGENCE.md §1, the companion
                    # to funerals): a NEW family forming is the cheapest,
                    # most unambiguous "this couple just bonded" signal
                    # this codebase has — first child together, exactly
                    # the trigger the wedding item asked for. The couple
                    # plus any kin/bonded onlookers gather at the birth
                    # tile for WEDDING_DURATION_TICKS, same override-
                    # priority movement bias `mourning_target` already
                    # established for funerals. A second child born to
                    # an already-bonded couple does NOT re-trigger this
                    # (`family_event is None` in that case) — one
                    # wedding per couple, not one per child.
                    venue = (a.x, a.y)
                    a.wedding_target = venue
                    a.wedding_ticks_remaining = WEDDING_DURATION_TICKS
                    b.wedding_target = venue
                    b.wedding_ticks_remaining = WEDDING_DURATION_TICKS
                    for guest in self.agents:
                        if guest.id in (a.id, b.id):
                            continue
                        is_kin = (
                            (guest.parents is not None and (a.id in guest.parents or b.id in guest.parents))
                            or (a.parents is not None and guest.id in a.parents)
                            or (b.parents is not None and guest.id in b.parents)
                        )
                        is_bonded = (
                            guest.relationships.get(a.id, 0.0) >= REPRODUCTION_AFFINITY_THRESHOLD
                            or guest.relationships.get(b.id, 0.0) >= REPRODUCTION_AFFINITY_THRESHOLD
                        )
                        if is_kin or is_bonded:
                            guest.wedding_target = venue
                            guest.wedding_ticks_remaining = WEDDING_DURATION_TICKS

        for nb in newborns:
            self._adopt(nb)
        self.agents.extend(newborns)
        return life_events

    @staticmethod
    def _extend_family(
        settlement: Settlement, tick: int, parent_a_id: int, parent_b_id: int, child_id: int,
        parent_a_name: str = "", parent_b_name: str = "",
    ) -> tuple[str, str] | None:
        """H3 (docs/ROADMAP.md Phase H): a birth is the cheapest, most
        unambiguous moment to form or extend a FAMILY institution — no
        LLM/goal decision involved, mirroring how A3's reproduction
        itself is deterministic scaffolding. Reuses an existing family
        if one already contains both parents (a second child born to the
        same couple joins the same family rather than starting a new
        one); otherwise creates one. Returns a `family_formed` life
        event only the first time (H9, docs/DECISIONS.md) — an
        institution actually forming is a real observatory-worthy
        moment; a routine addition to an existing family isn't."""
        existing = next(
            (
                inst for inst in settlement.institutions
                if inst.kind is InstitutionKind.FAMILY
                and parent_a_id in inst.member_agent_ids and parent_b_id in inst.member_agent_ids
            ),
            None,
        )
        if existing is not None:
            existing.member_agent_ids.add(child_id)
            return None
        family = Institution(
            id=settlement.next_institution_id,
            kind=InstitutionKind.FAMILY,
            founding_tick=tick,
            member_agent_ids={parent_a_id, parent_b_id, child_id},
        )
        settlement.next_institution_id += 1
        settlement.institutions.append(family)
        names = parent_a_name and parent_b_name
        who = f"{parent_a_name} and {parent_b_name}" if names else "a new couple"
        return ("family_formed", f"A new family began with {who}.")

    def _council_seat_key(self, agent: Agent) -> tuple[float, float]:
        """v0.87.15, "emergent leadership" (docs/IDEAS-2026-07-EMERGENCE.
        md §7): council seat selection/contest ranking — `_prominence`
        (longevity + social centrality + skill + reputation) first,
        fraction-of-lifespan-lived as a tiebreak only. Previously
        "living elders by age" was the WHOLE rule (a clean, but
        politically dead, "influence can't be earned, contested, or
        lost" shape); age now only breaks a tie between two agents of
        otherwise similar standing, rather than being the sole
        criterion — a charismatic, skilled, well-connected young founder
        can outrank a socially isolated elder."""
        age_fraction = (agent.age_ticks / agent.max_age_ticks) if agent.max_age_ticks else 0.0
        # §1 "deviance loop": an agent currently under an ostracism
        # penalty is never council material — same "gates ... council
        # eligibility" the idea doc names for standing_penalty.
        if agent.standing_penalty > 0.0:
            return (-1.0, age_fraction)
        return (self._prominence(agent), age_fraction)

    def _maybe_form_council(
        self, settlement: Settlement, tick: int, members: "list[Agent] | None" = None,
    ) -> list[tuple[str, str]]:
        """H3 extension (docs/ROADMAP.md "Phase H"): a second
        institution kind, formed the first tick a named settlement's
        population reaches COUNCIL_FORMATION_POPULATION_THRESHOLD —
        membership is the COUNCIL_SIZE most prominent living agents at
        that moment (see `_council_seat_key`), fixed at formation and
        never refreshed, same "outlives its founding moment" shape
        FAMILY institutions already use. Still fully deterministic/
        automatic — no agent goal or LLM decision founds one, matching
        how buildings/families are founded in this project. A no-op
        every tick after the one where it fires."""
        members = self.agents if members is None else members
        if not settlement.name or len(members) < COUNCIL_FORMATION_POPULATION_THRESHOLD:
            return []
        if any(inst.kind is InstitutionKind.COUNCIL for inst in settlement.institutions):
            return []
        elders = sorted(members, key=self._council_seat_key, reverse=True)[:COUNCIL_SIZE]
        council = Institution(
            id=settlement.next_institution_id,
            kind=InstitutionKind.COUNCIL,
            founding_tick=tick,
            member_agent_ids={a.id for a in elders},
        )
        settlement.next_institution_id += 1
        settlement.institutions.append(council)
        names = ", ".join(a.name for a in elders)
        return [("council_formed", f"A council of elders formed: {names}.")]

    def _maybe_refresh_council(
        self, settlement: Settlement, tick: int = 0, members: "list[Agent] | None" = None,
    ) -> list[tuple[str, str]]:
        """Integration-milestone fix: `_maybe_form_council` set
        `member_agent_ids` once at formation and nothing ever added to
        it afterward — every council member who died just stayed a
        permanent dead entry, so a long-running settlement's COUNCIL
        would silently decay into an all-dead ghost roster with zero
        living voice, the single most isolated institution in the
        codebase (no agency anywhere, and now not even a live
        membership). Institutions still never *remove* a member on
        death (see `Institution.member_agent_ids`'s docstring — an
        institution outlives its members by design), but a council
        specifically needs a *living* quorum to have any governance
        meaning, so this tops the living membership back up to
        COUNCIL_SIZE from the highest-`_council_seat_key` non-member
        agent whenever a seat opens. A no-op most ticks (only fires the
        tick after a sitting member's death, and only while enough
        living population remains to fill the seat).

        v0.87.15 ("emergent leadership") adds a SECOND, throttled check
        (`COUNCIL_DISPLACEMENT_CHECK_INTERVAL_TICKS`) even when no seat
        is open: if the single most prominent non-member clears the
        weakest sitting member's own prominence by `COUNCIL_
        DISPLACEMENT_MARGIN`, that member is displaced — "a charismatic
        young founder displacing an elder" (the idea doc's own example),
        genuinely contested and lost influence rather than a fixed
        tenure. The displaced member stays a FORMER council member in
        every other sense (their own beliefs/objective history is
        untouched; only `member_agent_ids` membership changes)."""
        members = self.agents if members is None else members
        council = next((i for i in settlement.institutions if i.kind is InstitutionKind.COUNCIL), None)
        if council is None:
            return []
        living_members = [a for a in members if a.id in council.member_agent_ids]
        seats_open = COUNCIL_SIZE - len(living_members)
        if seats_open > 0:
            candidates = sorted(
                (a for a in members if a.id not in council.member_agent_ids),
                key=self._council_seat_key, reverse=True,
            )[:seats_open]
            if not candidates:
                return []
            council.member_agent_ids.update(a.id for a in candidates)
            names = ", ".join(a.name for a in candidates)
            return [("council_seat_filled", f"{names} joined the council of elders, filling an empty seat.")]
        if tick % COUNCIL_DISPLACEMENT_CHECK_INTERVAL_TICKS != 0 or not living_members:
            return []
        non_members = [a for a in members if a.id not in council.member_agent_ids]
        if not non_members:
            return []
        challenger = max(non_members, key=self._council_seat_key)
        weakest = min(living_members, key=self._council_seat_key)
        challenger_score = self._council_seat_key(challenger)[0]
        weakest_score = self._council_seat_key(weakest)[0]
        if weakest_score <= 0 or challenger_score < weakest_score * COUNCIL_DISPLACEMENT_MARGIN:
            return []
        council.member_agent_ids.discard(weakest.id)
        council.member_agent_ids.add(challenger.id)
        return [(
            "council_seat_contested",
            f"{challenger.name} displaced {weakest.name} on the council of elders.",
        )]

    def _maybe_form_guild(
        self, settlement: Settlement, tick: int, members: "list[Agent] | None" = None,
    ) -> list[tuple[str, str]]:
        """H3 v4 (docs/DECISIONS.md "continue expanding" pass): a third
        institution kind, one per mastered trade (SKILL_FARMING/
        SKILL_CONSTRUCTION, now also SKILL_MEDICINE), formed the first
        tick at least GUILD_FORMATION_MASTER_COUNT living agents have
        reached GUILD_SKILL_MASTERY_THRESHOLD in that skill. Uses
        `Institution.name` to hold which skill this guild is for — the
        first real consumer of that field, previously always empty. A
        no-op for a skill that already has a standing guild."""
        if not settlement.name:
            return []
        members = self.agents if members is None else members
        events: list[tuple[str, str]] = []
        existing_skills = {
            inst.name for inst in settlement.institutions if inst.kind is InstitutionKind.GUILD
        }
        for skill in (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE):
            if skill in existing_skills:
                continue
            masters = [a for a in members if a.skills.get(skill, 0.0) >= GUILD_SKILL_MASTERY_THRESHOLD]
            if len(masters) < GUILD_FORMATION_MASTER_COUNT:
                continue
            guild = Institution(
                id=settlement.next_institution_id,
                kind=InstitutionKind.GUILD,
                founding_tick=tick,
                member_agent_ids={a.id for a in masters},
                name=skill,
            )
            settlement.next_institution_id += 1
            settlement.institutions.append(guild)
            names = ", ".join(a.name for a in masters)
            events.append(("guild_formed", f"A {skill} guild formed: {names}."))
        return events

    def _maybe_refresh_guild(
        self, settlement: Settlement, members: "list[Agent] | None" = None,
    ) -> list[tuple[str, str]]:
        """Unlike COUNCIL's fixed-size seat-refilling, a guild's living
        membership grows unboundedly as more agents reach mastery in its
        trade — there's no seat cap on expertise, only a floor
        (GUILD_FORMATION_MASTER_COUNT) to found one at all. A no-op most
        ticks (only fires when a living non-member agent has just
        crossed GUILD_SKILL_MASTERY_THRESHOLD in a guild's trade)."""
        events: list[tuple[str, str]] = []
        for guild in settlement.institutions:
            if guild.kind is not InstitutionKind.GUILD:
                continue
            skill = guild.name
            newly_mastered = [
                a for a in (self.agents if members is None else members)
                if a.id not in guild.member_agent_ids and a.skills.get(skill, 0.0) >= GUILD_SKILL_MASTERY_THRESHOLD
            ]
            if not newly_mastered:
                continue
            guild.member_agent_ids.update(a.id for a in newly_mastered)
            names = ", ".join(a.name for a in newly_mastered)
            events.append(("guild_joined", f"{names} mastered {skill} and joined the {skill} guild."))
        return events

    def _detect_faction_candidate(
        self, settlement: Settlement, members: "list[Agent] | None" = None,
    ) -> list[Agent] | None:
        """Phase L "Factions" (docs/VISION-2026-07.md, "Society &
        Power") — the deterministic detection half, same candidacy/
        decision split as guild founding/fission/dispute: cheap,
        no-LLM clustering finds a candidate; the engine spends an LLM
        call only to name/frame it (see `llm/faction.py`,
        `SimulationEngine._maybe_schedule_faction`).

        Union-find over living settlement members, connecting a pair
        only when trust is genuinely mutual (both directions clear
        FACTION_TRUST_EDGE_THRESHOLD) — chosen loyalty, not one agent's
        unreciprocated regard. Agents already in a living FACTION are
        excluded from the pool so this only ever proposes new
        factions among the currently unaffiliated (an agent belongs to
        at most one faction, keeping detection cheap and factions
        legible rather than an overlapping tangle). Returns the
        highest-cohesion cluster clearing both FACTION_MIN_SIZE and
        FACTION_MIN_COHESION, or None if no such cluster exists — an
        expected, common outcome, not a failure."""
        pool_source = self.agents if members is None else members
        existing_members: set[int] = {
            aid for inst in settlement.institutions
            if inst.kind is InstitutionKind.FACTION
            for aid in inst.member_agent_ids
        }
        pool = [a for a in pool_source if a.id not in existing_members]
        if len(pool) < FACTION_MIN_SIZE:
            return None
        id_to_agent = {a.id: a for a in pool}
        parent = {a.id: a.id for a in pool}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a in pool:
            for other_id, value in a.trust.items():
                other = id_to_agent.get(other_id)
                if other is None or value < FACTION_TRUST_EDGE_THRESHOLD:
                    continue
                if other.trust.get(a.id, 0.0) < FACTION_TRUST_EDGE_THRESHOLD:
                    continue
                root_a, root_b = find(a.id), find(other_id)
                if root_a != root_b:
                    parent[root_a] = root_b

        clusters: dict[int, list[Agent]] = {}
        for a in pool:
            clusters.setdefault(find(a.id), []).append(a)

        def cohesion(cluster: list[Agent]) -> float:
            ids = {a.id for a in cluster}
            total, count = 0.0, 0
            for a in cluster:
                for other_id, value in a.trust.items():
                    if other_id in ids:
                        total += value
                        count += 1
            return total / count if count else 0.0

        candidates = [c for c in clusters.values() if len(c) >= FACTION_MIN_SIZE]
        if not candidates:
            return None
        best = max(candidates, key=lambda c: (cohesion(c), len(c)))
        if cohesion(best) < FACTION_MIN_COHESION:
            return None
        return sorted(best, key=lambda a: a.id)

    def form_faction(
        self, settlement: Settlement, member_ids: list[int], tick: int, name: str,
    ) -> tuple[str, str] | None:
        """Actually create the FACTION institution once the engine's LLM
        job has named it (or fallen back to a deterministic name) — the
        detection half (`_detect_faction_candidate`) never mutates
        state, same query/apply split as guild founding. Returns None
        if the cap has no room even after pruning the fully-dead (an
        expected outcome on a very long-running world; formation simply
        doesn't happen that month)."""
        living_ids = {a.id for a in self.agents}
        _prune_extinct_institutions(settlement, living_ids, InstitutionKind.FACTION, FACTION_MAX_STORED)
        if sum(1 for i in settlement.institutions if i.kind is InstitutionKind.FACTION) >= FACTION_MAX_STORED:
            return None
        faction = Institution(
            id=settlement.next_institution_id,
            kind=InstitutionKind.FACTION,
            founding_tick=tick,
            member_agent_ids=set(member_ids),
            name=name,
        )
        settlement.next_institution_id += 1
        settlement.institutions.append(faction)
        return ("faction_formed", f'A faction has formed: "{name}".')

    def faction_of(self, agent_id: int, settlement: Settlement) -> "Institution | None":
        """The living FACTION `agent_id` belongs to, if any — consumed by
        dispute rivalry framing and fission-party assembly (Phase L)."""
        for inst in settlement.institutions:
            if inst.kind is InstitutionKind.FACTION and agent_id in inst.member_agent_ids:
                return inst
        return None

    def council_faction_majority(self, settlement: Settlement) -> "Institution | None":
        """v0.87.15, "emergent leadership" (docs/IDEAS-2026-07-EMERGENCE.
        md §7): the FACTION with the most living seats on `settlement`'s
        COUNCIL, if any faction holds a strict majority of the LIVING
        council membership — `None` if there's no council, no living
        member belongs to any faction, or no single faction commands a
        strict majority (a genuinely split council has no "majority,"
        which is itself meaningful and left for the caller to read as
        "no bias"). Consumed by dispute-outcome framing (`llm/
        dispute.py`'s `council_faction` bias) and town_brain framing
        (`compute_priority`'s tiebreak) — "let a faction majority on
        the council bias dispute rulings and town-brain framing," the
        idea doc's own phrasing."""
        council = next((i for i in settlement.institutions if i.kind is InstitutionKind.COUNCIL), None)
        if council is None:
            return None
        living_members = [a for a in self.agents if a.id in council.member_agent_ids]
        if not living_members:
            return None
        counts: dict[int, int] = {}
        for member in living_members:
            faction = self.faction_of(member.id, settlement)
            if faction is not None:
                counts[faction.id] = counts.get(faction.id, 0) + 1
        if not counts:
            return None
        top_faction_id = max(counts, key=lambda fid: counts[fid])
        if counts[top_faction_id] * 2 <= len(living_members):
            return None
        return next(i for i in settlement.institutions if i.id == top_faction_id)

    def institution_objective_for(self, agent_id: int, settlement: Settlement) -> str:
        """v0.87.12 "institution objectives" (docs/IDEAS-2026-07-
        EMERGENCE.md §7): the first non-blank `Institution.objective`
        among every institution (FAMILY/GUILD/COUNCIL/FACTION)
        `agent_id` belongs to in `settlement` — "" if none, or if every
        institution's objective is still blank (the common early-game
        case before the monthly institution-belief job has ever
        supplied one). Deterministic first-match by `settlement.
        institutions`'s own order; an agent belonging to more than one
        institution with a real objective just reads the first — this
        is prompt-bias garnish, not a resolution mechanism that needs
        to be exhaustive."""
        for inst in settlement.institutions:
            if agent_id in inst.member_agent_ids and inst.objective:
                return inst.objective
        return ""

    def family_of(self, agent_id: int, settlement: Settlement) -> "Institution | None":
        """The FAMILY `agent_id` belongs to, if any — same shape as
        `faction_of` but checked against `member_agent_ids` directly
        (never pruned on death, so this also resolves a deceased
        member's family — feud membership is meant to outlive the
        individual, same as the institution itself). Consumed by
        dispute rivalry framing (`rival_families`) and `_maybe_
        reproduce`'s cross-feud-line affinity gate (v0.87.11)."""
        for inst in settlement.institutions:
            if inst.kind is InstitutionKind.FAMILY and agent_id in inst.member_agent_ids:
                return inst
        return None

    @staticmethod
    def families_feuding(family_a: "Institution | None", family_b: "Institution | None") -> bool:
        """True when two different FAMILY institutions have a durable
        feud entry naming each other (`Institution.feuds`) — not just a
        raw id mismatch (every pair of different families would trivially
        satisfy that); a real promoted feud is required."""
        if family_a is None or family_b is None or family_a.id == family_b.id:
            return False
        return any(f["family_id"] == family_b.id for f in family_a.feuds)

    def _maybe_welcome_migrant(
        self, rng: random.Random, settlement: Settlement,
        core_cast_target: int = POPULATION_CRITICAL_THRESHOLD,
        terrain: list[list[Tile]] | None = None,
        region_population_density: float | None = None,
        region_scarcity: float | None = None,
        region_ownership: float | None = None,
        region_heat: float | None = None,
        region_cultural_influence: float | None = None,
        region_beauty: float | None = None,
        region_wildlife: float | None = None,
    ) -> list[tuple[str, str]]:
        """The population equivalent of wildlife's `_maybe_recolonize` —
        a settlement crashed down to a handful of survivors (predation,
        starvation, disaster, or simply old age outpacing sparse births)
        can otherwise sit at 1-3 people forever with no path back, since
        reproduction needs a compatible, colocated, mature, healthy pair.
        A rare newcomer arriving at the settlement (or, if unnamed, near
        an existing survivor) breaks that dead end.

        **Also resettles from true 0 population** (v0.85.1 — direct
        reversal of the prior "0 is a legitimate, permanent ending, never
        auto-revive" rule, per a live 60,000-tick report of a world
        stuck at 0 population with no path back). Uses the same chance
        formula as the near-extinction band below (no openness nudge —
        there's nobody left to have an opinion). A settlement whose
        every building has also fully decayed and been reclaimed
        (`settlement.buildings` empty — the case that actually happened
        in the live report) has no building or survivor to anchor a
        migrant's arrival position on, since settlements are never
        pre-placed (see `World.create_new`); `_center_walkable_tile`
        (deterministic, scans outward from the map's geometric center)
        is the neutral fallback anchor for that case. `terrain` is
        optional only for callers that can't supply it (legacy/test call
        sites) — without it, resettlement from a buildingless 0
        population can't find a safe tile and is skipped that tick
        rather than risk placing a migrant in water.

        `core_cast_target` (`Config.llm_core_cast_size`, passed down
        from `World.tick()`) is the gate's ceiling, not just
        `POPULATION_CRITICAL_THRESHOLD` — explicit user request: once
        the world population falls below the LLM-authored cast size,
        outsiders should be able to hear of the opening and settle,
        same "drawn by word of its need" framing as the near-extinction
        case, not only once down to a handful of survivors. The three
        bands read differently: at 0, or at/below `POPULATION_CRITICAL_
        THRESHOLD`, the full chance applies (a genuine demographic
        emergency); above that but still below `core_cast_target` only a
        gentler trickle does (`MIGRANT_BELOW_CORE_CAST_CHANCE_MULT`) —
        filling out a thin roster is a much lower-stakes need than
        averting a dead end, and shouldn't feel like a sudden influx the
        instant the core cast comes up one short.

        `region_population_density` (A20, roadmap Stage IV step 29):
        `World.fields`'s `population_density` region field (A1),
        0..1 read at this settlement's own center — see `MIGRANT_
        DENSITY_DAMPENING`'s docstring. `region_scarcity` (A4, Tier 1):
        `World.fields`'s `scarcity` region field, same shape — see
        `MIGRANT_SCARCITY_DAMPENING`'s docstring. `region_ownership`
        (A1, Tier 1 item 3): `World.fields`'s `ownership` region field,
        same shape — see `MIGRANT_OWNERSHIP_PULL`'s docstring.
        `region_wildlife` (A10, field-substrate fold-in): `World.
        fields`'s `wildlife` region field, sourced from live GRAZER-herd
        presence — see `MIGRANT_WILDLIFE_PULL`'s docstring."""
        count = len(self.agents)
        floor = max(1, core_cast_target)
        if count >= floor:
            return []
        chance = MIGRANT_CHECK_CHANCE_PER_TICK * (1.0 + max(0.0, settlement.temperament) * MIGRANT_TEMPERAMENT_INFLUENCE)
        if count >= POPULATION_CRITICAL_THRESHOLD:
            chance *= MIGRANT_BELOW_CORE_CAST_CHANCE_MULT
        if count > 0:
            # H6 v4: the surviving remnant's own average openness nudges
            # how readily it welcomes a stranger — see TRAIT_OPENNESS_
            # MIGRANT_WELCOME_INFLUENCE. No survivors at count==0 means
            # no one left to have an opinion, so this term is skipped
            # rather than dividing by zero.
            avg_openness = sum(a.traits.get(TRAIT_OPENNESS, 0.0) for a in self.agents) / count
            chance *= 1.0 + avg_openness * TRAIT_OPENNESS_MIGRANT_WELCOME_INFLUENCE
        if region_population_density is not None:
            chance *= 1.0 - region_population_density * MIGRANT_DENSITY_DAMPENING
        if region_scarcity is not None:
            chance *= 1.0 - region_scarcity * MIGRANT_SCARCITY_DAMPENING
        if region_ownership is not None:
            chance *= 1.0 + region_ownership * MIGRANT_OWNERSHIP_PULL
        if region_heat is not None:
            chance *= 1.0 - region_heat * MIGRANT_HEAT_DAMPENING
        if region_cultural_influence is not None:
            chance *= 1.0 + region_cultural_influence * MIGRANT_CULTURAL_PULL
        if region_beauty is not None:
            chance *= 1.0 + region_beauty * MIGRANT_BEAUTY_PULL
        if region_wildlife is not None:
            chance *= 1.0 + region_wildlife * MIGRANT_WILDLIFE_PULL
        chance = max(0.0, chance)
        if rng.random() >= chance:
            return []
        if settlement.buildings:
            building = settlement.buildings[rng.randrange(len(settlement.buildings))]
            x, y = building.x, building.y
        elif count > 0:
            anchor = self.agents[rng.randrange(count)]
            x, y = anchor.x, anchor.y
        elif terrain is not None:
            pos = self._center_walkable_tile(terrain)
            if pos is None:
                return []
            x, y = pos
        else:
            return []
        name = self._unique_name(rng)
        migrant = Agent(
            id=self._next_id, name=name, x=x, y=y, age_ticks=MATURITY_TICKS,
            max_age_ticks=rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS),
            # A14 "development": a migrant is an already-grown adult
            # arriving from outside, not a homegrown child — unlike a
            # newborn (development=0.0 default), they start fully
            # developed, matching their explicit age_ticks=MATURITY_
            # TICKS above.
            development=1.0,
        )
        self._next_id += 1
        self._adopt(migrant)
        self.agents.append(migrant)
        destination = settlement.name or "the dwindling settlement"
        _remember(migrant, f"I came to {destination} from a village elsewhere, looking for a new start.")
        return [("migrant_arrived", f"{name} arrived at {destination} from outside, drawn by word of its need.")]

    @staticmethod
    def _center_walkable_tile(terrain: list[list[Tile]]) -> tuple[int, int] | None:
        """Deterministic resettlement anchor for a settlement that has
        lost every building and every inhabitant (`_maybe_welcome_
        migrant`'s true-0-population case) — there's no "last known
        location" to fall back on since settlements are never pre-placed
        (see `World.create_new`'s "settlements emerge from population
        behavior" comment). Scans outward ring by ring from the map's
        geometric center for the nearest walkable tile — a neutral,
        always-available anchor, not tied to any prior settlement's
        history. Returns None only if the entire map is unwalkable (not
        expected in practice)."""
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        if height == 0 or width == 0:
            return None
        cx, cy = width // 2, height // 2
        max_radius = max(width, height)
        for radius in range(0, max_radius + 1):
            for dy in range(-radius, radius + 1):
                y = cy + dy
                if not (0 <= y < height):
                    continue
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    x = cx + dx
                    if not (0 <= x < width):
                        continue
                    if _is_walkable(terrain, x, y):
                        return (x, y)
        return None

    def _unique_name(self, rng: random.Random, extra_taken: set[str] = frozenset()) -> str:
        """A name no *living* inhabitant currently bears. `generate_names`
        draws from a 50-name pool with replacement across calls, so at a
        couple hundred living agents duplicate names were near-certain —
        and `beliefs.resolve_subject_agent_id` deliberately refuses to
        resolve an ambiguous name, so per-person beliefs (and the omen
        subjects/dialogue context built on them) quietly stopped working
        exactly when the village got interesting (July 2026 architecture
        review, §8). Retries the pool a few times, then falls back to
        generational suffixes ("Wren II") that are themselves checked.
        `extra_taken` covers names claimed earlier in the same tick but
        not yet in `self.agents` — two newborns from the same tick's
        batch must not match either (the exact duplicate observed once
        in a 30k-tick verification run before this parameter existed)."""
        living = {a.name for a in self.agents} | set(extra_taken)
        candidate = ""
        for _ in range(8):
            candidate = generate_names(1, rng)[0]
            if candidate not in living:
                return candidate
        base = candidate
        suffix = 2
        while f"{base} {_roman(suffix)}" in living:
            suffix += 1
        return f"{base} {_roman(suffix)}"

    @staticmethod
    def _is_mature(agent: Agent) -> bool:
        return agent.age_ticks >= MATURITY_TICKS

    @staticmethod
    def _is_healthy(agent: Agent) -> bool:
        return agent.hunger <= 0.7 and agent.energy >= 0.3

    # --- settlement: construction & repair (Phase C) --------------------------

    @staticmethod
    def _advance_construction(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement,
        skill_masteries: "list[tuple[int, str]] | None" = None,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        for building in settlement.buildings:
            if building.stage is not BuildingStage.UNDER_CONSTRUCTION:
                continue
            workers = [
                a for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE
            ][:MAX_WORKERS]
            if not workers:
                continue
            # H5 extension: a skilled crew builds faster — the average
            # construction proficiency among the (capped) workers present,
            # same "practiced yield bonus" shape SKILL_FARMING already
            # established. See SKILL_CONSTRUCTION_SPEED_BONUS.
            avg_skill = sum(a.skills.get(SKILL_CONSTRUCTION, 0.0) for a in workers) / len(workers)
            # BUILDER (v0.87.44): a builder's own presence contributes
            # BUILDER_WORK_BONUS worth of ordinary labor instead of 1.
            weighted_workers = sum(
                BUILDER_WORK_BONUS if a.occupation == OCCUPATION_BUILDER else 1.0 for a in workers
            )
            work = (
                CONSTRUCTION_WORK_PER_TICK * weighted_workers * _tech_factor(settlement)
                * _specialization_factor(settlement, "structural")
                * (1.0 + avg_skill * SKILL_CONSTRUCTION_SPEED_BONUS)
            )
            if settlement.materials >= MATERIALS_PER_CONSTRUCTION_TICK:
                settlement.materials -= MATERIALS_PER_CONSTRUCTION_TICK
                work *= CONSTRUCTION_MATERIALS_MULTIPLIER
            building.progress = min(1.0, building.progress + work)
            for a in workers:
                before = a.skills.get(SKILL_CONSTRUCTION, 0.0)
                after = min(1.0, before + SKILL_PRACTICE_GAIN)
                a.skills[SKILL_CONSTRUCTION] = after
                if before < MASTERY_THRESHOLD <= after:
                    _nudge_trait(a, TRAIT_AMBITION, TRAIT_AMBITION_MASTERY_NUDGE)
                    _remember(a, "Became a master of construction after years of practice.")
                    life_events.append(("skill_mastered", f"{a.name} became a true master of construction."))
                    if skill_masteries is not None:
                        skill_masteries.append((a.id, "construction"))
            if building.progress >= 1.0:
                building.stage = BuildingStage.STANDING
                building.condition = 1.0
                life_events.append(("building_completed", f"A structure was completed at ({building.x}, {building.y})."))
        return life_events

    @staticmethod
    def _maybe_repair(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> list[tuple[str, str]]:
        for building in settlement.buildings:
            if building.stage is not BuildingStage.STANDING or building.condition >= REPAIR_THRESHOLD:
                continue
            present = [a for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE]
            if not present:
                continue
            # BUILDER (v0.87.44): counted at BUILDER_WORK_BONUS, same
            # shape as _advance_construction, capped alongside everyone
            # else at MAX_WORKERS worth of total weighted labor.
            workers = min(
                sum(BUILDER_WORK_BONUS if a.occupation == OCCUPATION_BUILDER else 1.0 for a in present),
                float(MAX_WORKERS),
            )
            # A5/A6's "Entity.properties" half: a material's real
            # numeric workability (not just its boolean affordance
            # tags) scales how fast this specific instance repairs —
            # see material_repair_factor's docstring.
            repair = (
                REPAIR_WORK_PER_TICK * workers * _tech_factor(settlement)
                * _specialization_factor(settlement, "structural")
                * material_repair_factor(effective_material_name(building))
            )
            building.condition = min(1.0, building.condition + repair)
            if building.condition >= REPAIR_THRESHOLD:
                # Discrete "repair completed" count (v0.86.7) — how many
                # assets NPCs have actually repaired/maintained, exposed
                # in the UI. This branch's own outer gate only revisits a
                # building while condition < REPAIR_THRESHOLD, so
                # crossing back above it here is the mechanism's own
                # "no longer needs repair" signal — counting a rise to
                # 1.0 instead would almost never fire, since nothing
                # keeps working a building once it clears the threshold.
                settlement.buildings_repaired += 1
        return []  # repair progress isn't eventful enough on its own to log per-tick

    @classmethod
    def _maybe_start_construction(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlements: list[Settlement],
        farms: FarmGrid, rng: random.Random, roads: RoadNetwork | None = None,
        resources: ResourceGrid | None = None, terrain: list[list[Tile]] | None = None,
        ruin_scars: dict[tuple[int, int], float] | None = None,
        mining_scars: dict[tuple[int, int], float] | None = None,
        disaster_scars: dict[tuple[int, int], float] | None = None,
        road_scars: dict[tuple[int, int], float] | None = None,
        construction_history: dict[tuple[int, int], int] | None = None,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        settlements_by_id = {s.id: s for s in settlements}
        for (x, y), group in by_position.items():
            if len(group) < 2 or any(s.at(x, y) is not None for s in settlements) or farms.get(x, y) is not None:
                continue
            eligible = [a for a in group if cls._is_mature(a) and cls._is_healthy(a)]
            if len(eligible) < 2:
                continue
            # The founders build for their own community — materials,
            # priority steer, and the finished structure all belong to
            # the first founder's home settlement.
            settlement = settlements_by_id.get(eligible[0].settlement_id, settlements[0])
            # Deliberate site choice ("where to build, fully agent-pathed"
            # — the last colocation-only piece of urban growth): the
            # founders survey BUILD_SITE_SEARCH_RADIUS around themselves
            # and stake out the best-scoring tile, which may not be the
            # one they're standing on. Builders then *walk* to the staked
            # site (an under-construction building is a WANDER-goal
            # attractor, see _dispatch_movement), so a site chosen for
            # its road/resource adjacency genuinely draws its own labor.
            bx, by = cls._choose_build_site(
                x, y, terrain, settlements, farms, roads, resources, settlement.era, settlement=settlement,
                ruin_scars=ruin_scars, mining_scars=mining_scars, disaster_scars=disaster_scars,
                road_scars=road_scars,
            )
            settle_chance = SETTLE_CHANCE_PER_TICK
            if settlement.current_priority == "growth":
                settle_chance *= SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER
            elif settlement.current_priority:
                settle_chance *= SETTLE_CHANCE_OFF_PRIORITY_MULTIPLIER
            # The adjacency multipliers now read the *chosen* site rather
            # than the founders' feet — the same two signals the site
            # chooser ranks by, so a group that found a good spot nearby
            # is exactly as likely to act on it as one standing on it.
            if roads is not None and any(
                roads.is_road(bx + dx, by + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ):
                settle_chance *= URBAN_GROWTH_ROAD_ADJACENCY_MULTIPLIER
            if resources is not None and _near_productive_resource(resources, bx, by):
                settle_chance *= SETTLE_CHANCE_RESOURCE_ADJACENCY_MULTIPLIER
            elif terrain is not None and is_adjacent_to_water(terrain, bx, by):
                settle_chance *= SETTLE_CHANCE_RESOURCE_ADJACENCY_MULTIPLIER
            if rng.random() >= settle_chance:
                continue
            if any(s.at(bx, by) is not None for s in settlements):
                continue  # another group staked this exact tile earlier this same tick
            # Which kind gets built is weighted by the settlement's
            # current civic priority (the seasonal "town brain" LLM
            # decision) — a real steer, not just a coin flip. See
            # buildings.choose_building_kind, docs/DECISIONS.md,
            # "LLM-as-brain batch."
            kind = choose_building_kind(
                rng, settlement.current_priority, settlement.era, has_tradition=bool(settlement.traditions),
                caravans_visited=settlement.caravans_visited,
                water_adjacent=terrain is not None and is_adjacent_to_water(terrain, bx, by),
                branch=settlement.era_branch,
            )
            cost = MATERIALS_COST_BY_KIND[kind]
            if settlement.materials < cost:
                continue  # presence alone isn't enough — building needs material on site
            settlement.materials -= cost
            # H4, integration milestone: a HUT is personally owned by one
            # eligible founder, picked with an ambition-weighted random
            # draw rather than the old arbitrary lowest-id tie-break — a
            # more ambitious agent is more likely (never guaranteed) to
            # be the one who claims it. Every other kind stays commons
            # (owner_agent_id=None), see Building.owner_agent_id.
            if kind is BuildingKind.HUT:
                weights = [
                    max(0.05, 1.0 + a.traits.get(TRAIT_AMBITION, 0.0) * TRAIT_AMBITION_FOUNDER_SELECTION_WEIGHT)
                    for a in eligible
                ]
                owner_agent_id = rng.choices(eligible, weights=weights, k=1)[0].id
            else:
                owner_agent_id = None
            settlement.start_construction(bx, by, kind=kind, owner_agent_id=owner_agent_id)
            if construction_history is not None:
                # A19 "Persistent spatial memory": a real, permanent
                # per-tile record of how many times something has been
                # built here — never decays, unlike the scar dicts (see
                # World.construction_history's own docstring for why).
                construction_history[(bx, by)] = construction_history.get((bx, by), 0) + 1
            # H6 extension: founding a building is a tangible
            # achievement for its founders — see TRAIT_AMBITION_FOUNDING_NUDGE.
            for a in eligible:
                _nudge_trait(a, TRAIT_AMBITION, TRAIT_AMBITION_FOUNDING_NUDGE)
            if (bx, by) == (x, y):
                description = f"{kind.value.capitalize()} construction began at ({bx}, {by}), using {cost:.0f} materials."
            else:
                description = (
                    f"{kind.value.capitalize()} construction was staked out at ({bx}, {by})"
                    f" — a better spot than where its founders stood — using {cost:.0f} materials."
                )
            life_events.append(("construction_started", description))
        return life_events

    @classmethod
    def _choose_build_site(
        cls, x: int, y: int, terrain: list[list[Tile]] | None, settlements: list[Settlement],
        farms: FarmGrid, roads: RoadNetwork | None, resources: "ResourceGrid | None",
        era: str = "industrial", settlement: Settlement | None = None,
        ruin_scars: dict[tuple[int, int], float] | None = None,
        mining_scars: dict[tuple[int, int], float] | None = None,
        disaster_scars: dict[tuple[int, int], float] | None = None,
        road_scars: dict[tuple[int, int], float] | None = None,
    ) -> tuple[int, int]:
        """The best buildable tile within BUILD_SITE_SEARCH_RADIUS of the
        founders at (x, y) — scored by road/resource/water adjacency
        minus a per-step distance penalty (see the three BUILD_SITE_*
        constants). Falls back to (x, y) itself when terrain isn't
        provided (legacy callers) or nothing else scores higher. Ties
        keep the earliest-scanned tile, which the scan order below makes
        the one nearest the founders. `era` unlocks MOUNTAIN as a
        candidate tile once the settlement has real mining/tunneling
        technology (ERA_UNLOCKS_MOUNTAIN_BUILDING) — before that it's
        excluded exactly like water, a real geography constraint that
        eases with tech level rather than never applying at all
        (v0.68.0 fix).

        A7 (roadmap Stage IV step 27): `settlement` (optional — `None`
        reproduces the exact pre-A7 behavior for any caller without one
        in scope) adds `world/layout_grammar.py`'s deterministic layout-
        style bonus on top of the existing road/resource score, so a
        settlement's own layout style (radial/linear/clustered, stable
        for its lifetime) genuinely steers where it grows, not just
        road/resource adjacency.

        A3 (roadmap Stage IV step 28): `ruin_scars` (optional — `World.
        ruin_scars`, `None` reproduces the exact pre-A3 behavior)
        biases site choice toward a tile with a prior ruin — "the
        village rebuilds on old foundations," a real callback loop
        between A3's own ruin-formation mechanism and construction.

        A9 feedback-loop audit (docs/ROADMAP-2026-07-REMAINING.md,
        Tier 1 item 1): `mining_scars`/`disaster_scars` were both
        confirmed real write-only producers — nothing downstream ever
        read them, unlike `ruin_scars` above. A small penalty (not a
        hard exclusion — badly-scarred ground is still buildable, just
        less attractive than untouched land) gives both a genuine
        mechanical consumer, closing the loop the same way `ruin_scars`
        already closes its own."""
        if terrain is None:
            return (x, y)
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        mountain_unlocked = era in ERA_UNLOCKS_MOUNTAIN_BUILDING
        layout_style = None
        standing_positions: frozenset[tuple[int, int]] = frozenset()
        if settlement is not None:
            layout_style = settlement.effective_layout_style
            standing_positions = frozenset(
                (b.x, b.y) for b in settlement.buildings if b.stage is BuildingStage.STANDING
            )
        best = (x, y)
        best_score = None
        # Ring-by-ring from radius 0 outward so equal scores resolve to
        # the closest tile without a separate tie-break pass.
        for radius in range(0, BUILD_SITE_SEARCH_RADIUS + 1):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    cx, cy = x + dx, y + dy
                    if not (0 <= cx < width and 0 <= cy < height):
                        continue
                    if not _is_walkable(terrain, cx, cy, mountain_unlocked):
                        continue
                    if any(s.at(cx, cy) is not None for s in settlements) or farms.get(cx, cy) is not None:
                        continue
                    score = -radius * BUILD_SITE_DISTANCE_PENALTY
                    if roads is not None and any(
                        roads.is_road(cx + ox, cy + oy) for ox, oy in _NEIGHBOR_OFFSETS
                    ):
                        score += BUILD_SITE_ADJACENCY_SCORE
                    if (resources is not None and _near_productive_resource(resources, cx, cy)) or (
                        is_adjacent_to_water(terrain, cx, cy)
                    ):
                        score += BUILD_SITE_ADJACENCY_SCORE
                    if settlement is not None and layout_style is not None:
                        score += layout_site_bonus(
                            layout_style, settlement.center_x, settlement.center_y, cx, cy, standing_positions,
                        )
                    if (
                        ruin_scars is not None or mining_scars is not None or disaster_scars is not None
                        or road_scars is not None
                    ):
                        # A9 follow-up (docs/ROADMAP-2026-07-REMAINING.
                        # md): routed through spatial_memory's real
                        # read-side unification (A19) instead of three
                        # separate ad-hoc `.get()` calls — this is now
                        # the actual mechanism `location_character`
                        # exists to back, not a still-unused sibling.
                        # M1/M9: `road_scars` is the fourth axis added
                        # to this same unification, same "the village
                        # rebuilds along its own old paths" positive
                        # pull `ruin_scars` already gets.
                        character = location_character_from_dicts(
                            mining_scars, disaster_scars, None, ruin_scars, cx, cy, road_scars=road_scars,
                        )
                        score += character.get("ruin", 0.0) * RUIN_SITE_BONUS_SCALE
                        score += character.get("road", 0.0) * ROAD_SCAR_SITE_BONUS_SCALE
                        score -= character.get("mining", 0.0) * MINING_SCAR_SITE_PENALTY_SCALE
                        score -= character.get("disaster", 0.0) * DISASTER_SCAR_SITE_PENALTY_SCALE
                    if best_score is None or score > best_score:
                        best, best_score = (cx, cy), score
        return best

    @staticmethod
    def under_construction_positions(settlement: Settlement) -> list[tuple[int, int]]:
        """Staked-out/in-progress sites — merged with damaged buildings
        into the WANDER-goal work attractor (see _dispatch_movement), so
        a deliberately-chosen site a few tiles from its founders draws
        builders instead of waiting on incidental colocation. Same
        no-distance-cap rationale as damaged_building_positions: the
        community knows where its own half-built structures are."""
        return [
            (b.x, b.y) for b in settlement.buildings
            if b.stage is BuildingStage.UNDER_CONSTRUCTION
        ]

    @staticmethod
    def _maybe_trade_food(by_position: dict[tuple[int, int], list[Agent]], rng: random.Random) -> int:
        """Direct agent-to-agent barter: a hungry agent colocated with a
        non-rival neighbor who's carrying personal food (see
        `Agent.inventory`, stashed by `_maybe_forage`'s skim) receives a
        share, at a small relationship cost to the giver's own reserve
        and a small relationship gain for both — the one place in this
        project food moves between two named individuals directly,
        rather than through the settlement's communal granary/currency.
        Deliberately scoped to a single good and one-hop, presence-only
        exchange (no hauling, no market, no price discovery) — the
        first slice of the "per-agent inventory/trade" gap, not the
        full economy CLAUDE.md leaves as a still-larger future effort.
        Returns how many trades occurred. See docs/DECISIONS.md,
        "per-agent inventory and trade" pass."""
        trades = 0
        for group in by_position.values():
            if len(group) < 2:
                continue
            hungry = [a for a in group if a.hunger >= FORAGE_HUNGER_THRESHOLD and a.inventory.get("food", 0.0) <= 0.0]
            if not hungry:
                continue
            givers = [a for a in group if a.inventory.get("food", 0.0) > 0.0]
            for recipient in hungry:
                giver = next(
                    (
                        g for g in givers
                        if g.id != recipient.id
                        and g.relationships.get(recipient.id, 0.0) > _trade_relationship_threshold(g)
                    ),
                    None,
                )
                if giver is None:
                    continue
                amount = min(giver.inventory.get("food", 0.0), TRADE_FOOD_AMOUNT)
                if amount <= 0.0:
                    continue
                giver.inventory["food"] = giver.inventory.get("food", 0.0) - amount
                relief = TRADE_HUNGER_RELIEF * (amount / TRADE_FOOD_AMOUNT)
                recipient.hunger = max(0.0, recipient.hunger - relief)
                for a, b in ((giver, recipient), (recipient, giver)):
                    a.relationships[b.id] = clamp(a.relationships.get(b.id, 0.0) + TRADE_RELATIONSHIP_BOOST, -1.0, 1.0)
                    _nudge_trait(a, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
                _record_debt(recipient, giver, amount)
                _remember(recipient, f"{giver.name} shared food with me.", routine=True)
                if giver.inventory.get("food", 0.0) <= 0.0:
                    givers.remove(giver)
                trades += 1
        return trades

    @staticmethod
    def _maybe_stock_granaries(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> None:
        """Well-fed awake agents present at a standing granary passively
        contribute surplus each tick — presence-driven like every other
        mechanic here, not a hauling/inventory system. See
        docs/DECISIONS.md, D7. A full granary sells the surplus instead of
        wasting it (D10). v0.87.44: a present BAKER counts as
        `OCCUPATION_STAFF_BONUS` contributors instead of 1 (see
        `occupation_staff_weight`)."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.GRANARY or building.stage is not BuildingStage.STANDING:
                continue
            contributors = sum(
                occupation_staff_weight(a, OCCUPATION_BAKER, True)
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if contributors == 0:
                continue
            deposit = GRANARY_DEPOSIT_PER_TICK * contributors * _tech_factor(settlement)
            if building.stored_food >= GRANARY_CAPACITY:
                # Overflow food sells at the market's food price when one
                # stands — see tick_market_prices.
                settlement.currency = min(
                    CURRENCY_CAPACITY,
                    settlement.currency + deposit * CURRENCY_PER_OVERFLOW_UNIT * settlement.market_price("food"),
                )
                continue
            building.stored_food = min(GRANARY_CAPACITY, building.stored_food + deposit)

    @staticmethod
    def _maybe_run_husbandry(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """PASTURE (animal husbandry) and HATCHERY (fish husbandry),
        v0.86.7 — explicit user direction: deliberate, invested food
        sources distinct from wild grazer hunting/fish foraging. Each
        standing building produces food into its own `stored_food`
        (withdrawable exactly like a granary, see `_maybe_forage`) on
        two layers: a small passive trickle regardless of staffing
        (herds/stocks tend themselves, slowly) plus a substantially
        larger boost per well-fed, awake agent present tending it — same
        "presence-driven production" shape `_maybe_run_workshops` uses
        for currency, applied to food instead. One shared loop for both
        kinds since the shape is identical; only the constants differ."""
        for building in settlement.buildings:
            if building.stage is not BuildingStage.STANDING:
                continue
            if building.kind is BuildingKind.PASTURE:
                capacity, passive, tended = PASTURE_CAPACITY, PASTURE_PASSIVE_YIELD_PER_TICK, PASTURE_TENDED_YIELD_PER_TICK
            elif building.kind is BuildingKind.HATCHERY:
                capacity, passive, tended = HATCHERY_CAPACITY, HATCHERY_PASSIVE_YIELD_PER_TICK, HATCHERY_TENDED_YIELD_PER_TICK
            else:
                continue
            if building.stored_food >= capacity:
                continue
            # FISHERMAN (v0.87.44) staff-weights only at HATCHERY, not
            # PASTURE — a fisherman's occupation applies to fish stocks,
            # not herded livestock.
            matching_occupation = OCCUPATION_FISHERMAN if building.kind is BuildingKind.HATCHERY else None
            tenders = sum(
                occupation_staff_weight(a, matching_occupation, True) if matching_occupation else 1.0
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            yield_amount = (
                (passive + tended * min(tenders, MAX_WORKERS))
                * _tech_factor(settlement) * _specialization_factor(settlement, "agricultural")
            )
            building.stored_food = min(capacity, building.stored_food + yield_amount)

    @staticmethod
    def _maybe_run_workshops(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Staffed presence at a standing workshop generates currency
        directly — a business, distinct from D10's overflow-selling. See
        WORKSHOP_INCOME_PER_TICK, docs/DECISIONS.md, "LLM-as-brain batch.\""""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.WORKSHOP or building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(
                occupation_staff_weight(a, OCCUPATION_BUSINESSMAN, True)
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = WORKSHOP_INCOME_PER_TICK * staff * _tech_factor(settlement) * _specialization_factor(settlement, "mercantile")
            if settlement.has_power_plant():
                income *= POWER_GRID_INDUSTRY_MULTIPLIER
            settlement.currency = min(CURRENCY_CAPACITY, settlement.currency + income)

    @staticmethod
    def _maybe_craft_tools(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """H4 (docs/ROADMAP.md "Phase H"): a standing workshop's awake,
        well-fed staff also convert shared materials into *personal*
        tools for themselves, one worker at a time each tick as long as
        materials last — additive to `_maybe_run_workshops`'s currency
        income, not a replacement. This is the project's first genuinely
        owned crafted good: unlike currency (settlement-wide) or stored
        food (communal granary), the tools land directly in the specific
        worker's own `Agent.inventory`. See WORKSHOP_CRAFT_MATERIALS_
        COST_PER_TICK/WORKSHOP_CRAFT_TOOLS_PER_TICK."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.WORKSHOP or building.stage is not BuildingStage.STANDING:
                continue
            workers = [
                a for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            ]
            for worker in workers:
                if settlement.materials < WORKSHOP_CRAFT_MATERIALS_COST_PER_TICK:
                    break
                if worker.inventory.get("tools", 0.0) >= TOOLS_CAPACITY:
                    continue
                settlement.materials -= WORKSHOP_CRAFT_MATERIALS_COST_PER_TICK
                crafted = WORKSHOP_CRAFT_TOOLS_PER_TICK
                # §8 expanded mineral economy: iron on hand sweetens the
                # craft with a real quality bonus, on top of the plain
                # materials-only rate — see IRON_TOOL_BONUS_PER_TICK.
                if settlement.minerals.get("iron", 0.0) >= IRON_TOOL_COST_PER_TICK:
                    settlement.minerals["iron"] -= IRON_TOOL_COST_PER_TICK
                    crafted += IRON_TOOL_BONUS_PER_TICK
                worker.inventory["tools"] = min(
                    TOOLS_CAPACITY, worker.inventory.get("tools", 0.0) + crafted
                )

    @staticmethod
    def _maybe_trade_tools(by_position: dict[tuple[int, int], list[Agent]], rng: random.Random) -> int:
        """Same shape as `_maybe_trade_food`, for the H4 tools good — a
        GATHER-goal agent with no tools of their own, colocated with a
        non-rival neighbor who has spare tools, receives a share.
        Deliberately reuses TRADE_MIN_RELATIONSHIP/TRADE_RELATIONSHIP_
        BOOST rather than introducing parallel constants for a second
        good. Returns how many trades occurred."""
        trades = 0
        for group in by_position.values():
            if len(group) < 2:
                continue
            wanting = [
                a for a in group if a.goal is AgentGoal.GATHER and a.inventory.get("tools", 0.0) <= 0.0
            ]
            if not wanting:
                continue
            givers = [a for a in group if a.inventory.get("tools", 0.0) > 0.0]
            for recipient in wanting:
                giver = next(
                    (
                        g for g in givers
                        if g.id != recipient.id
                        and g.relationships.get(recipient.id, 0.0) > _trade_relationship_threshold(g)
                    ),
                    None,
                )
                if giver is None:
                    continue
                amount = min(giver.inventory.get("tools", 0.0), TRADE_TOOLS_AMOUNT)
                if amount <= 0.0:
                    continue
                giver.inventory["tools"] = giver.inventory.get("tools", 0.0) - amount
                recipient.inventory["tools"] = min(TOOLS_CAPACITY, recipient.inventory.get("tools", 0.0) + amount)
                for a, b in ((giver, recipient), (recipient, giver)):
                    a.relationships[b.id] = clamp(a.relationships.get(b.id, 0.0) + TRADE_RELATIONSHIP_BOOST, -1.0, 1.0)
                    _nudge_trait(a, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
                _record_debt(recipient, giver, amount)
                _remember(recipient, f"{giver.name} shared tools with me.", routine=True)
                if giver.inventory.get("tools", 0.0) <= 0.0:
                    givers.remove(giver)
                trades += 1
        return trades

    @staticmethod
    def _maybe_craft_medicine(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """H4 extension (docs/ROADMAP.md "Phase H"): the second crafted-
        good supply chain, same shape as `_maybe_craft_tools` — a
        standing hospital's awake, well-fed staff convert shared
        materials into personal medicine for themselves. See
        HOSPITAL_CRAFT_MATERIALS_COST_PER_TICK/HOSPITAL_CRAFT_MEDICINE_
        PER_TICK, `_tick_disease` for the consumption side.

        "Continue expanding, round three": a worker's own SKILL_MEDICINE
        proficiency now boosts their crafted yield per tick (same
        "practiced yield bonus" shape SKILL_FARMING/SKILL_CONSTRUCTION
        already have — see SKILL_MEDICINE_YIELD_BONUS) and grows by
        SKILL_MEDICINE_PRACTICE_GAIN each tick they craft, closing what
        was otherwise the only crafted good with no personal-skill
        hook at all."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.HOSPITAL or building.stage is not BuildingStage.STANDING:
                continue
            workers = [
                a for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            ]
            for worker in workers:
                if settlement.materials < HOSPITAL_CRAFT_MATERIALS_COST_PER_TICK:
                    break
                if worker.inventory.get("medicine", 0.0) >= MEDICINE_CAPACITY:
                    continue
                settlement.materials -= HOSPITAL_CRAFT_MATERIALS_COST_PER_TICK
                medicine_skill = worker.skills.get(SKILL_MEDICINE, 0.0)
                yield_amount = HOSPITAL_CRAFT_MEDICINE_PER_TICK * (1.0 + medicine_skill * SKILL_MEDICINE_YIELD_BONUS)
                worker.inventory["medicine"] = min(
                    MEDICINE_CAPACITY, worker.inventory.get("medicine", 0.0) + yield_amount
                )
                worker.skills[SKILL_MEDICINE] = min(1.0, medicine_skill + SKILL_MEDICINE_PRACTICE_GAIN)

    @staticmethod
    def _maybe_trade_medicine(by_position: dict[tuple[int, int], list[Agent]], rng: random.Random) -> int:
        """Same shape as `_maybe_trade_tools`, for the H4 extension's
        medicine good — a sick agent with none, colocated with a non-
        rival neighbor who has spare, receives a share. Returns how
        many trades occurred."""
        trades = 0
        for group in by_position.values():
            if len(group) < 2:
                continue
            wanting = [a for a in group if a.sick_ticks > 0 and a.inventory.get("medicine", 0.0) <= 0.0]
            if not wanting:
                continue
            givers = [a for a in group if a.inventory.get("medicine", 0.0) > 0.0]
            for recipient in wanting:
                giver = next(
                    (
                        g for g in givers
                        if g.id != recipient.id
                        and g.relationships.get(recipient.id, 0.0) > _trade_relationship_threshold(g)
                    ),
                    None,
                )
                if giver is None:
                    continue
                amount = min(giver.inventory.get("medicine", 0.0), TRADE_MEDICINE_AMOUNT)
                if amount <= 0.0:
                    continue
                giver.inventory["medicine"] = giver.inventory.get("medicine", 0.0) - amount
                recipient.inventory["medicine"] = min(
                    MEDICINE_CAPACITY, recipient.inventory.get("medicine", 0.0) + amount
                )
                for a, b in ((giver, recipient), (recipient, giver)):
                    a.relationships[b.id] = clamp(a.relationships.get(b.id, 0.0) + TRADE_RELATIONSHIP_BOOST, -1.0, 1.0)
                    _nudge_trait(a, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
                _record_debt(recipient, giver, amount)
                _remember(recipient, f"{giver.name} shared medicine with me.", routine=True)
                if giver.inventory.get("medicine", 0.0) <= 0.0:
                    givers.remove(giver)
                trades += 1
        return trades

    @staticmethod
    def _maybe_run_factories(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Same shape as `_maybe_run_workshops`, at FACTORY_INCOME_PER_TICK
        (double the rate) — the settlement's industrial-era-or-later
        economic upgrade. See docs/DECISIONS.md, real-calendar/
        genesis-seed follow-up."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.FACTORY or building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(
                occupation_staff_weight(a, OCCUPATION_BUSINESSMAN, True)
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = FACTORY_INCOME_PER_TICK * staff * _tech_factor(settlement) * _specialization_factor(settlement, "mercantile")
            if settlement.has_power_plant():
                income *= POWER_GRID_INDUSTRY_MULTIPLIER
            settlement.currency = min(CURRENCY_CAPACITY, settlement.currency + income)

    @staticmethod
    def _maybe_run_docks(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Same shape as `_maybe_run_workshops`, at DOCK_INCOME_PER_TICK
        — a water-adjacent trade port. See BuildingKind.DOCK."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.DOCK or building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(
                occupation_staff_weight(a, OCCUPATION_BUSINESSMAN, True)
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = DOCK_INCOME_PER_TICK * staff * _tech_factor(settlement) * _specialization_factor(settlement, "mercantile")
            settlement.currency = min(CURRENCY_CAPACITY, settlement.currency + income)

    @staticmethod
    def _maybe_run_oil_rigs(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Same shape as `_maybe_run_factories`, at OIL_RIG_INCOME_PER_
        TICK — offshore extraction, the water-infrastructure batch's
        industrial-scale income building. See BuildingKind.OIL_RIG."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.OIL_RIG or building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(
                occupation_staff_weight(a, OCCUPATION_BUSINESSMAN, True)
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = OIL_RIG_INCOME_PER_TICK * staff * _tech_factor(settlement) * _specialization_factor(settlement, "mercantile")
            if settlement.has_power_plant():
                income *= POWER_GRID_INDUSTRY_MULTIPLIER
            settlement.currency = min(CURRENCY_CAPACITY, settlement.currency + income)

    @classmethod
    def _maybe_assign_occupations(cls, settlement: Settlement, members: list[Agent]) -> None:
        """v0.87.44 jobs/economy batch: every mature, healthy, still-
        occupationless member of `settlement` gets assigned whichever
        occupation the settlement currently has the fewest of (MAYOR
        capped at one living holder) — deterministic, not LLM-authored
        (see occupations.py's module docstring for why: an LLM call per
        assignment would blow the per-agent LLM-volume budget). Keeps a
        town's occupation mix roughly proportionate as it grows, rather
        than every newly-mature agent independently rolling the same
        occupation. Cheap in the common case (a settlement with nobody
        newly eligible this tick does one list comprehension and
        returns) — the full count/assign pass only runs once a real
        candidate exists."""
        eligible = [
            a for a in members
            if not a.occupation and cls._is_mature(a) and cls._is_healthy(a)
        ]
        if not eligible:
            return
        counts = {occ: 0 for occ in ALL_OCCUPATIONS}
        for a in members:
            if a.occupation in counts:
                counts[a.occupation] += 1
        for a in eligible:
            candidates = [
                occ for occ in ALL_OCCUPATIONS
                if occ != OCCUPATION_MAYOR or counts[OCCUPATION_MAYOR] == 0
            ]
            chosen = min(candidates, key=lambda o: counts[o])
            a.occupation = chosen
            counts[chosen] += 1

    @staticmethod
    def _mark_explored(
        agent: Agent, home: Settlement, terrain: list[list[Tile]],
        resources: ResourceGrid, minerals: "MineralGrid | None", settlements: list[Settlement], tick: int,
    ) -> list[tuple[str, str]]:
        """v0.87.45 exploration/surveyor batch: a SURVEYOR-occupation
        agent (only — see the call site, `Population.tick`) reveals a
        small radius (`EXPLORATION_VISION_RADIUS`) of tiles around their
        own position into `home.explored_tiles` every tick they're
        awake, and records a capped finding (`home.exploration_
        findings`) for anything notable a newly-revealed tile turns up:
        a mineral vein, a rich wild-food/fish site, or another
        settlement's structures. Scoped to surveyors specifically
        (not every agent) so this stays a bounded per-surveyor cost,
        not an O(population) one — most agents never leave their
        settlement's already-explored neighborhood anyway."""
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        new_tiles: list[tuple[int, int]] = []
        for dx in range(-EXPLORATION_VISION_RADIUS, EXPLORATION_VISION_RADIUS + 1):
            for dy in range(-EXPLORATION_VISION_RADIUS, EXPLORATION_VISION_RADIUS + 1):
                x, y = agent.x + dx, agent.y + dy
                if not (0 <= x < width and 0 <= y < height):
                    continue
                pos = (x, y)
                if pos in home.explored_tiles:
                    continue
                home.explored_tiles.add(pos)
                new_tiles.append(pos)
        if not new_tiles:
            return []
        life_events: list[tuple[str, str]] = []
        for x, y in new_tiles:
            finding: tuple[str, str] | None = None
            mineral = minerals.get(x, y) if minerals is not None else None
            if mineral is not None:
                finding = ("mineral", f"{agent.name} charted a {mineral.kind.value} vein at ({x}, {y}).")
            else:
                node = resources.get(x, y)
                if node is not None and node.kind in (ResourceKind.FOOD, ResourceKind.FISH):
                    finding = ("resource", f"{agent.name} charted a rich {node.kind.value.lower()} site at ({x}, {y}).")
                elif any(s.id != home.id and s.at(x, y) is not None for s in settlements):
                    finding = ("settlement", f"{agent.name} sighted another settlement's structures at ({x}, {y}).")
            if finding is None:
                continue
            kind, description = finding
            home.exploration_findings.append({"tick": tick, "x": x, "y": y, "kind": kind, "description": description})
            if len(home.exploration_findings) > EXPLORATION_FINDINGS_MAX:
                home.exploration_findings = home.exploration_findings[-EXPLORATION_FINDINGS_MAX:]
            life_events.append(("surveyor_finding", description))
        return life_events

    @staticmethod
    def _maybe_run_forges(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Same shape as `_maybe_run_workshops`, at FORGE_INCOME_PER_TICK
        — a bronze_age+ smithy, this era's economic building before
        WORKSHOP/FACTORY exist. No POWER_GRID_INDUSTRY_MULTIPLIER (no
        electricity this early). See BuildingKind.FORGE."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.FORGE or building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(
                occupation_staff_weight(a, OCCUPATION_BLACKSMITH, True)
                for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = FORGE_INCOME_PER_TICK * staff * _tech_factor(settlement) * _specialization_factor(settlement, "mercantile")
            settlement.currency = min(CURRENCY_CAPACITY, settlement.currency + income)

    @staticmethod
    def _maybe_run_market_workers(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """A BANKER present at a standing MARKET generates currency
        directly (BANKER_INCOME_PER_TICK per banker) — distinct from
        SHOPKEEPER, who instead negotiates a better caravan-trade bonus
        (see `_maybe_schedule_caravan`'s call site in engine.py, since
        that's a monthly event-time effect, not a per-tick one). Same
        presence-driven shape as `_maybe_run_workshops`."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.MARKET or building.stage is not BuildingStage.STANDING:
                continue
            bankers = sum(
                1 for a in by_position.get((building.x, building.y), [])
                if a.occupation == OCCUPATION_BANKER
                and a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if bankers == 0:
                continue
            income = BANKER_INCOME_PER_TICK * bankers * _tech_factor(settlement) * _specialization_factor(settlement, "mercantile")
            settlement.currency = min(CURRENCY_CAPACITY, settlement.currency + income)

    @staticmethod
    def _maybe_run_schools(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Staffed presence at a standing school (or its university
        upgrade) slowly raises settlement-wide education, which boosts
        invention chance — see SCHOOL_EDUCATION_PER_TICK,
        buildings.education_invention_bonus."""
        if settlement.education_level >= EDUCATION_CAPACITY:
            return
        for building in settlement.buildings:
            if building.kind not in (BuildingKind.SCHOOL, BuildingKind.UNIVERSITY, BuildingKind.LIBRARY):
                continue
            if building.stage is not BuildingStage.STANDING:
                continue
            # LIBRARY is staffed preferentially by SCRIBE, SCHOOL/UNIVERSITY
            # by TEACHER — same education-boost mechanic either way (v1
            # audit fix, full historical era ladder).
            matching_occupation = OCCUPATION_SCRIBE if building.kind is BuildingKind.LIBRARY else OCCUPATION_TEACHER
            staff = sum(
                occupation_staff_weight(a, matching_occupation, True)
                for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE
            )
            if staff == 0:
                continue
            multiplier = UNIVERSITY_EDUCATION_MULTIPLIER if building.kind is BuildingKind.UNIVERSITY else 1.0
            gain = SCHOOL_EDUCATION_PER_TICK * staff * multiplier
            settlement.education_level = min(EDUCATION_CAPACITY, settlement.education_level + gain)

    @classmethod
    def _maybe_upgrade_university(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement, rng: random.Random,
    ) -> list[tuple[str, str]]:
        """A standing school becomes a university once the settlement is
        advanced enough (UNIVERSITY_TECH_REQUIREMENT inventions) and a
        colocated, mature, healthy pair is present to do the work — an
        upgrade of an existing structure, not founded fresh from the
        weighted pool. See docs/DECISIONS.md, "LLM-as-brain batch.\""""
        life_events: list[tuple[str, str]] = []
        if settlement.tech_level < UNIVERSITY_TECH_REQUIREMENT or settlement.materials < UNIVERSITY_MATERIALS_COST:
            return life_events
        schools = [b for b in settlement.buildings if b.kind is BuildingKind.SCHOOL and b.stage is BuildingStage.STANDING]
        if not schools:
            return life_events
        for school in schools:
            group = by_position.get((school.x, school.y), [])
            eligible = [a for a in group if cls._is_mature(a) and cls._is_healthy(a)]
            if len(eligible) < 2:
                continue
            settlement.materials -= UNIVERSITY_MATERIALS_COST
            school.kind = BuildingKind.UNIVERSITY
            life_events.append((
                "building_completed",
                f"The school at ({school.x}, {school.y}) was upgraded into a university.",
            ))
            break  # one upgrade per tick is plenty — a rare, deliberate event
        return life_events

    # --- vehicles: hauling carts & personal mounts -------------------------

    @staticmethod
    def _advance_vehicle_construction(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        for vehicle in settlement.vehicles:
            if vehicle.stage is not VehicleStage.BUILDING:
                continue
            workers = sum(
                1 for a in by_position.get((vehicle.x, vehicle.y), []) if a.state is AgentState.AWAKE
            )
            if workers == 0:
                continue
            work = VEHICLE_CONSTRUCTION_WORK_PER_TICK * min(workers, VEHICLE_MAX_WORKERS) * _tech_factor(settlement) * _specialization_factor(settlement, "structural")
            vehicle.progress = min(1.0, vehicle.progress + work)
            if vehicle.progress >= 1.0:
                vehicle.stage = VehicleStage.READY
                vehicle.condition = 1.0
                life_events.append(("vehicle_completed", f"A {vehicle.kind.value} was finished at ({vehicle.x}, {vehicle.y})."))
        return life_events

    @staticmethod
    def _maybe_repair_vehicles(
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> None:
        for vehicle in settlement.vehicles:
            if vehicle.stage not in (VehicleStage.READY, VehicleStage.BROKEN):
                continue
            if vehicle.stage is VehicleStage.READY and vehicle.condition >= VEHICLE_REPAIR_THRESHOLD:
                continue
            workers = sum(
                1 for a in by_position.get((vehicle.x, vehicle.y), []) if a.state is AgentState.AWAKE
            )
            if workers == 0:
                continue
            repair = VEHICLE_REPAIR_WORK_PER_TICK * min(workers, VEHICLE_MAX_WORKERS) * _tech_factor(settlement) * _specialization_factor(settlement, "structural")
            vehicle.condition = min(1.0, vehicle.condition + repair)
            if vehicle.stage is VehicleStage.BROKEN and vehicle.condition >= VEHICLE_REPAIR_THRESHOLD:
                vehicle.stage = VehicleStage.READY
                settlement.vehicles_repaired += 1  # v0.86.7: discrete repair-completion tally

    @classmethod
    def _maybe_assign_mounts(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
    ) -> None:
        """An awake agent colocated with a ready, unclaimed personal
        vehicle (mount or the era-gated automobile upgrade) and not
        already riding one claims it — first-come, presence-driven like
        everything else here, not a deliberate goal/cognition decision."""
        mounted_ids = {
            v.assigned_agent_id for v in settlement.vehicles
            if v.kind in PERSONAL_VEHICLE_KINDS and v.assigned_agent_id is not None
        }
        for vehicle in settlement.vehicles:
            if (
                vehicle.kind not in PERSONAL_VEHICLE_KINDS or vehicle.stage is not VehicleStage.READY
                or vehicle.assigned_agent_id is not None
            ):
                continue
            for agent in by_position.get((vehicle.x, vehicle.y), []):
                if agent.state is AgentState.AWAKE and agent.id not in mounted_ids:
                    vehicle.assigned_agent_id = agent.id
                    mounted_ids.add(agent.id)
                    break

    @staticmethod
    def _wear_carts(settlement: Settlement) -> None:
        ready_carts = [v for v in settlement.vehicles if v.kind is VehicleKind.CART and v.stage is VehicleStage.READY]
        if not ready_carts:
            return
        wear = CART_USE_DECAY / len(ready_carts)
        for cart in ready_carts:
            cart.condition = max(0.0, cart.condition - wear)

    @staticmethod
    def _wear_rafts(settlement: Settlement) -> None:
        """Same shape as `_wear_carts`, triggered per fish catch instead
        of per gather tick — see RAFT_USE_DECAY."""
        ready_rafts = [v for v in settlement.vehicles if v.kind is VehicleKind.RAFT and v.stage is VehicleStage.READY]
        if not ready_rafts:
            return
        wear = RAFT_USE_DECAY / len(ready_rafts)
        for raft in ready_rafts:
            raft.condition = max(0.0, raft.condition - wear)

    @classmethod
    def _maybe_start_vehicle(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement,
        farms: FarmGrid, rng: random.Random, terrain: list[list[Tile]] | None = None,
    ) -> list[tuple[str, str]]:
        """A vehicle presupposes an existing community (see
        VEHICLE_CHANCE_PER_TICK) — nothing is built before the settlement
        itself has a name."""
        life_events: list[tuple[str, str]] = []
        if not settlement.name:
            return life_events
        for (x, y), group in by_position.items():
            if (
                len(group) < 2 or settlement.at(x, y) is not None or farms.get(x, y) is not None
                or settlement.vehicle_at(x, y) is not None
            ):
                continue
            eligible = [a for a in group if cls._is_mature(a) and cls._is_healthy(a)]
            if len(eligible) < 2:
                continue
            if rng.random() >= VEHICLE_CHANCE_PER_TICK:
                continue
            # Carts/mounts stay foundable at every era (horse-drawn
            # transport genuinely coexisted with early industry); the
            # automobile only enters the pool once the era has advanced
            # past `industrial` — the settlement's transport modernizes
            # alongside its buildings, not just carts forever. See
            # buildings.ERA_UNLOCKS_AUTOMOBILE, docs/DECISIONS.md,
            # "vehicle era-progression follow-up." A RAFT only joins the
            # roll at a build site actually adjacent to water — same
            # gating idea as FISH resource nodes (world/resources.py's
            # is_adjacent_to_water) — a raft built inland makes no sense.
            # BOAT (v0.87.42) joins the same water-adjacent-only slice of
            # the roll, alongside RAFT.
            water_adjacent = terrain is not None and is_adjacent_to_water(terrain, x, y)
            roll = rng.random()
            if water_adjacent:
                if settlement.era in ERA_UNLOCKS_AUTOMOBILE:
                    kind = (
                        VehicleKind.CART if roll < 0.25 else VehicleKind.MOUNT if roll < 0.45
                        else VehicleKind.AUTOMOBILE if roll < 0.6 else VehicleKind.RAFT if roll < 0.8
                        else VehicleKind.BOAT
                    )
                else:
                    kind = (
                        VehicleKind.MOUNT if roll < 0.3 else VehicleKind.CART if roll < 0.55
                        else VehicleKind.RAFT if roll < 0.75 else VehicleKind.BOAT
                    )
            elif settlement.era in ERA_UNLOCKS_AUTOMOBILE:
                kind = VehicleKind.CART if roll < 0.4 else VehicleKind.MOUNT if roll < 0.7 else VehicleKind.AUTOMOBILE
            else:
                kind = VehicleKind.MOUNT if roll < 0.5 else VehicleKind.CART
            cost = {
                VehicleKind.MOUNT: MOUNT_MATERIALS_COST, VehicleKind.CART: CART_MATERIALS_COST,
                VehicleKind.BOAT: BOAT_MATERIALS_COST,
                VehicleKind.AUTOMOBILE: AUTOMOBILE_MATERIALS_COST, VehicleKind.RAFT: RAFT_MATERIALS_COST,
            }[kind]
            if settlement.materials < cost:
                continue
            settlement.materials -= cost
            settlement.start_vehicle(x, y, kind=kind)
            life_events.append((
                "vehicle_started",
                f"{kind.value.capitalize()} construction began at ({x}, {y}), using {cost:.0f} materials.",
            ))
        return life_events

    @classmethod
    def _maybe_start_bridge(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement,
        farms: FarmGrid, rng: random.Random, terrain: list[list[Tile]] | None = None,
    ) -> list[tuple[str, str]]:
        """Same colocation-gate shape as `_maybe_start_vehicle`'s RAFT
        founding, but the payoff is real water-crossing pathing, not a
        passive bonus (see BuildingKind.BRIDGE). Only a group standing
        on a shore tile (water-adjacent, same gate RAFT uses) ever
        attempts the (more expensive) span search — most ticks, most
        colocated groups aren't near water at all, so the cheap
        `is_adjacent_to_water` check filters almost everything before
        `_find_bridge_span`'s BFS ever runs."""
        life_events: list[tuple[str, str]] = []
        if not settlement.name or terrain is None:
            return life_events
        mountain_unlocked = settlement.era in ERA_UNLOCKS_MOUNTAIN_BUILDING
        for (x, y), group in by_position.items():
            if len(group) < 2 or settlement.at(x, y) is not None or farms.get(x, y) is not None:
                continue
            if not is_adjacent_to_water(terrain, x, y):
                continue
            eligible = [a for a in group if cls._is_mature(a) and cls._is_healthy(a)]
            if len(eligible) < 2:
                continue
            if rng.random() >= BRIDGE_CHANCE_PER_TICK:
                continue
            span = _find_bridge_span(terrain, (x, y), mountain_unlocked)
            if span is None:
                continue
            cost = max(BRIDGE_MIN_MATERIALS_COST, len(span) * BRIDGE_MATERIALS_COST_PER_SPAN_TILE)
            if settlement.materials < cost:
                continue
            settlement.materials -= cost
            settlement.start_construction(x, y, kind=BuildingKind.BRIDGE, bridge_span=span)
            life_events.append((
                "construction_started",
                f"A bridge crossing {len(span)} tile{'s' if len(span) != 1 else ''} of water was staked "
                f"out at ({x}, {y}), using {cost:.0f} materials.",
            ))
        return life_events

    def _apply_inheritance(
        self, agent: Agent, settlement: Settlement, dying_ids: set[int], tick: int = 0,
        rng: random.Random | None = None,
        ownership_history: dict[tuple[int, int], int] | None = None,
    ) -> list[tuple[str, str]]:
        """H7 (docs/ROADMAP.md "Phase H"): a death moves what a person
        had to a living heir instead of it simply vanishing — land
        (any HUT they owned, see H4), personal goods (food/tools), a
        partial transfer of accumulated skill (a "last lesson," not a
        full copy — see INHERITANCE_SKILL_TRANSFER_FRACTION), and a
        carried-over bias (a strong distrust they held of someone still
        living, see INHERITANCE_BIAS_THRESHOLD). Genuinely blocked on H3
        landing first, per the roadmap's own note: the heir is found via
        `Settlement.family_for`, so a lone survivor with no living
        family leaves nothing behind but grief and memory — a legitimate
        outcome, not a gap. Only logs an `inheritance` event when
        something concrete actually changed hands, so most deaths (an
        agent with no home, no goods, no notable skill or grudge) don't
        spam the feed."""
        family = settlement.family_for(agent.id)
        if family is None:
            return []
        candidates = [
            a for a in self.agents
            if a.id in family.member_agent_ids and a.id != agent.id and a.id not in dying_ids
        ]
        if not candidates:
            return []
        heir = max(candidates, key=lambda a: (agent.relationships.get(a.id, 0.0), -a.id))

        inherited: list[str] = []
        homes_inherited = 0
        for building in settlement.buildings:
            if building.owner_agent_id == agent.id:
                building.owner_agent_id = heir.id
                homes_inherited += 1
                if ownership_history is not None:
                    # A19 "Persistent spatial memory": a real, permanent
                    # per-tile record of how many times this exact site
                    # has changed hands — see World.ownership_history's
                    # own docstring.
                    pos = (building.x, building.y)
                    ownership_history[pos] = ownership_history.get(pos, 0) + 1
        if homes_inherited == 1:
            inherited.append("a home")
        elif homes_inherited > 1:
            inherited.append(f"{homes_inherited} homes")

        good_caps = {"food": PERSONAL_FOOD_CAPACITY, "tools": TOOLS_CAPACITY, "medicine": MEDICINE_CAPACITY}
        for good, amount in agent.inventory.items():
            if amount <= 0.0:
                continue
            cap = good_caps.get(good)
            current = heir.inventory.get(good, 0.0)
            heir.inventory[good] = min(cap, current + amount) if cap is not None else current + amount
            inherited.append(good)

        for skill, level in agent.skills.items():
            heir_level = heir.skills.get(skill, 0.0)
            if level > heir_level:
                heir.skills[skill] = min(1.0, heir_level + INHERITANCE_SKILL_TRANSFER_FRACTION * (level - heir_level))
                inherited.append(f"{skill} technique")

        for source_id, value in agent.trust.items():
            if value <= INHERITANCE_BIAS_THRESHOLD and source_id not in dying_ids and source_id != heir.id:
                current = heir.trust.get(source_id, 0.0)
                heir.trust[source_id] = max(
                    -1.0, min(1.0, current + INHERITANCE_BIAS_TRANSFER_FRACTION * (value - current))
                )
                inherited.append("a wariness of someone")

        # Deferred item 3 (docs/VISION-2026-07-LEARNING.md), "cross-
        # generational lesson inheritance": one of the deceased's
        # lessons passes to the heir, IMPERFECTLY — attributed to the
        # parent, not claimed as the heir's own hard-won experience, and
        # not a guaranteed transfer (only INHERITANCE_LESSON_CHANCE of
        # the time — a lesson is exactly the kind of thing that can get
        # lost between generations). The freshest lesson is favored (the
        # one the deceased was most recently living by), same "freshest
        # wins" convention `_matching_lesson` already uses. Deterministic
        # — no LLM call, matching item 1's discipline.
        if agent.lessons and rng is not None and rng.random() < INHERITANCE_LESSON_CHANCE:
            source = max(agent.lessons, key=lambda e: e.get("formed_tick", 0))
            push_lesson(
                heir, source["situation"], f"{agent.name} used to say: {source['text']}", tick,
            )
            inherited.append("a lesson")

        # Phase 3.B "deeper inheritance" (docs/VISION-2026-07-21-
        # SELFEVOLVING.md): same imperfect-transmission shape as the
        # lesson transfer above, applied to the deceased's freshest
        # personal belief instead — attributed, not claimed as the
        # heir's own, and at reduced confidence (secondhand conviction).
        if agent.beliefs and rng is not None and rng.random() < INHERITANCE_BELIEF_CHANCE:
            source_belief = max(agent.beliefs, key=lambda b: b.get("formed_tick", 0))
            heir.beliefs.append({
                "subject": source_belief.get("subject", ""),
                "belief": f"{agent.name} used to believe: {source_belief.get('belief', '')}",
                "confidence": source_belief.get("confidence", 0.5) * INHERITANCE_BELIEF_CONFIDENCE_FRACTION,
                "formed_tick": tick,
            })
            if len(heir.beliefs) > MAX_PERSONAL_BELIEFS:
                del heir.beliefs[0]
            inherited.append("a private belief")

        # v0.87.6, "deathbed release of secrets" (docs/IDEAS-2026-07-
        # EMERGENCE.md §1): a kept secret currently just dies with its
        # holder. The heir already resolved above (the same person H7
        # hands goods/skill/bias to) may learn the deceased's freshest
        # secret, attributed to the deathbed rather than the original
        # confidant. Rarer still, it also slips out as a vague rumor
        # (never the secret's actual contents) via the existing
        # spread_rumor machinery — zero LLM cost either way.
        if agent.secrets and rng is not None and rng.random() < DEATHBED_SECRET_HEIR_CHANCE:
            secret_text = agent.secrets[-1]
            push_secret(heir, f"{agent.name} told me on their deathbed: {secret_text}")
            inherited.append("a secret")
            if rng.random() < DEATHBED_SECRET_RUMOR_CHANCE:
                self.spread_rumor(
                    f"On their deathbed, {agent.name} spoke of something long kept quiet.",
                    DEATHBED_SECRET_RUMOR_LISTENER_COUNT, rng,
                )

        # v0.87.15 "knowledge lifecycle: diffusion, loss, rediscovery"
        # (docs/IDEAS-2026-07-EMERGENCE.md §7): if the deceased was the
        # LAST knower of a tracked invention (already dormant — see
        # `_apply_deaths`'s knower-removal pass, which runs before this
        # for the same death), the heir has one chance to rediscover it
        # via family papers, same "heir memory already does this"
        # mechanism as the lesson/secret transfers above.
        if rng is not None:
            for entry, info in settlement.invention_knowledge.items():
                if info.get("dormant") and info.get("_dormant_since_id") == agent.id:
                    if rng.random() < INVENTION_REDISCOVERY_CHANCE:
                        info["knowers"] = [heir.id]
                        info["dormant"] = False
                        info.pop("_dormant_since_id", None)
                        inherited.append(f"the rediscovered craft of {entry.split(':')[0]}")
                    else:
                        info.pop("_dormant_since_id", None)

        if not inherited:
            return []
        _remember(heir, f"I inherited from {agent.name}: {', '.join(inherited)}.", because=f"{agent.name} died")
        return [("inheritance", f"{heir.name} inherited from {agent.name}: {', '.join(inherited)}.")]

    def _apply_deaths(
        self, killed_by_predator: set[int] = frozenset(), settlements: list[Settlement] | None = None,
        died_of_disease: set[int] = frozenset(), tick: int = 0, rng: random.Random | None = None,
        ownership_history: dict[tuple[int, int], int] | None = None,
    ) -> list[tuple[str, str]]:
        life_events: list[tuple[str, str]] = []
        settlements = settlements or []
        settlements_by_id = {s.id: s for s in settlements}
        primary = settlements[0] if settlements else None

        def home_of(a: Agent) -> "Settlement | None":
            return settlements_by_id.get(a.settlement_id, primary)

        # Resilience-minded traditions soften (never erase) grief's
        # energy cost — a village with mourning customs carries loss
        # better; the custom that matters is the MOURNER's own
        # community's. See culture_effect_multiplier.
        grief_by_id = {
            s.id: GRIEF_ENERGY_PENALTY / culture_effect_multiplier(s.culture_effects, "resilience")
            for s in settlements
        }

        def grief_penalty_for(mourner: Agent) -> float:
            if primary is None:
                return GRIEF_ENERGY_PENALTY
            return grief_by_id.get(mourner.settlement_id, grief_by_id[primary.id])
        dying_ids: set[int] = set()
        for agent in self.agents:
            if (
                agent.id in killed_by_predator
                or agent.id in died_of_disease
                or agent.starving_ticks >= _starvation_threshold(agent)
                or agent.age_ticks >= agent.max_age_ticks
            ):
                dying_ids.add(agent.id)

        survivors: list[Agent] = []
        for agent in self.agents:
            if agent.id not in dying_ids:
                survivors.append(agent)
                continue
            if agent.id in killed_by_predator:
                # Already logged by _maybe_predator_attack (the "death"
                # event was appended there so the description could
                # reference the specific attack) — just count it here.
                self.deaths_predator += 1
                cause = "killed by predators"
            elif agent.id in died_of_disease:
                life_events.append(("death", f"{agent.name} died of illness."))
                self.deaths_disease += 1
                cause = "died of illness"
            # Same resilience-adjusted threshold the dying_ids check above
            # used — audit fix: this arm previously compared against the
            # raw STARVATION_TICKS_TO_DEATH, so a fragile (negative-
            # resilience) agent whose personal threshold sits below the
            # base died of starvation but fell through to the "old age"
            # arm, miscounting the death and logging a young agent as
            # dying of old age.
            elif agent.starving_ticks >= _starvation_threshold(agent):
                life_events.append(("death", f"{agent.name} died of starvation."))
                self.deaths_starvation += 1
                cause = "died of starvation"
            else:
                life_events.append(("death", f"{agent.name} died of old age."))
                self.deaths_old_age += 1
                cause = "died of old age"
            home = home_of(agent)
            if home is not None:
                # A grave mark where they fell — history becomes
                # physically visible, applied to people. See
                # SettlementInfrastructure.memorials.
                home.add_memorial(agent.x, agent.y, agent.name, cause, tick)
            left_record = len(agent.memories) >= RECORD_MIN_MEMORIES
            if left_record:
                # The letter's existence is an objective fact of this
                # tick; its text is interpretive and gets authored by
                # the LLM/fallback in the background — see
                # last_written_records' docstring.
                best_belief = (
                    max(agent.beliefs, key=lambda b: b["confidence"])["belief"] if agent.beliefs else ""
                )
                self.last_written_records.append({
                    "author": agent.name, "memories": list(agent.memories), "belief": best_belief,
                    "settlement_id": agent.settlement_id,
                })
            # Grief: a survivor bonded to the dying agent remembers them
            # and pays a real cost, not just a log line. See
            # docs/DECISIONS.md, relationship-memory pass.
            #
            # v0.87.9, "ceremonies agents attend: funerals" (docs/IDEAS-
            # 2026-07-EMERGENCE.md §1): the same kin/bonded survivors
            # this loop already identifies also have their movement
            # biased toward the grave just created above
            # (`mourning_target`/`mourning_ticks_remaining`, consumed by
            # `_dispatch_movement`/`_tick_mourning`) — mourning as a
            # real, visible gathering, not just an internal emotion
            # bump. Gated on `home is not None` since a memorial (the
            # grave to gather at) is only ever created in that case.
            record_kept = False
            for other in self.agents:
                if other.id == agent.id or other.id in dying_ids:
                    continue
                is_child = other.parents is not None and agent.id in other.parents
                is_parent = agent.parents is not None and other.id in agent.parents
                if left_record and not record_kept and (is_child or is_parent):
                    # The physical letter stays with the first grieving
                    # relative — memory that outlives the 8-entry cap,
                    # since the record itself persists on the settlement.
                    _remember(other, f"I keep the letter {agent.name} left behind.", because=f"{agent.name} died")
                    record_kept = True
                if is_child or is_parent:
                    # Family grief lands regardless of the numeric
                    # relationship value — a newborn's affinity with its
                    # own parent may not have accrued much yet, but
                    # losing a parent (or a child) is memorable
                    # regardless. See docs/DECISIONS.md, family-memory
                    # pass.
                    label = "parent" if is_child else "child"
                    _remember(other, f"My {label}, {agent.name}, died.", because=f"{agent.name} died")
                    other.energy = max(0.0, other.energy - grief_penalty_for(other))
                    self.last_triggered_agent_ids.add(other.id)
                    _nudge_trait(other, TRAIT_RESILIENCE, TRAIT_GRIEF_NUDGE)
                    bump_emotion(other, EMOTION_GRIEF, EMOTION_DEATH_GRIEF_BUMP)
                    # Phase 1.B: losing a parent or child is squarely
                    # "death," one of the doc's named life events.
                    other.life_event_since_goal = True
                    if home is not None:
                        other.mourning_target = (agent.x, agent.y)
                        other.mourning_ticks_remaining = MOURNING_DURATION_TICKS
                elif other.relationships.get(agent.id, 0.0) >= REPRODUCTION_AFFINITY_THRESHOLD:
                    _remember(other, f"{agent.name} died. I miss them.", because=f"{agent.name} died")
                    other.energy = max(0.0, other.energy - grief_penalty_for(other))
                    self.last_triggered_agent_ids.add(other.id)
                    _nudge_trait(other, TRAIT_RESILIENCE, TRAIT_GRIEF_NUDGE)
                    bump_emotion(other, EMOTION_GRIEF, EMOTION_DEATH_GRIEF_BUMP)
                    other.life_event_since_goal = True
                    # Phase 3.B "identity, irreversible change": widowhood
                    # is one of the vision doc's three named extreme-
                    # event triggers for a permanent trait shift.
                    _maybe_harden_trait(other)
                    if home is not None:
                        other.mourning_target = (agent.x, agent.y)
                        other.mourning_ticks_remaining = MOURNING_DURATION_TICKS
            if home is not None:
                # v0.87.15 "knowledge lifecycle": remove the deceased as
                # a knower of every tracked invention; if they were the
                # LAST one, it goes dormant — "the old bridge-craft died
                # with Maren" — tagged `_dormant_since_id` so the
                # inheritance pass just below (same death) can offer the
                # heir a chance to rediscover it via family papers.
                for entry, info in home.invention_knowledge.items():
                    knowers = info.get("knowers", [])
                    if agent.id in knowers:
                        knowers.remove(agent.id)
                        if not knowers and not info.get("dormant"):
                            info["dormant"] = True
                            info["_dormant_since_id"] = agent.id
                            life_events.append((
                                "knowledge_lost",
                                f"The craft behind {entry.split(':')[0]} died with {agent.name}.",
                            ))
                life_events.extend(
                    self._apply_inheritance(
                        agent, home, dying_ids, tick, rng, ownership_history=ownership_history,
                    )
                )
        self.agents = survivors
        if self._store is not None:
            # Drop the dead from the native store too, keeping it in
            # lockstep with self.agents. Swap-with-last removal internally
            # reindexes surviving slots; the store's id-keyed map absorbs
            # that, so no live Agent handle is affected. `dying_ids` is
            # exactly the removed set (computed above from self.agents).
            for dead_id in dying_ids:
                self._store.remove(dead_id)
        if dying_ids:
            # Strip every survivor's relationships/trust entries for the
            # dying — a dead agent is never colocated again, so these
            # entries would otherwise sit in every acquaintance's dict
            # for the rest of the world's history, forever. Grief itself
            # already ran above (it reads relationships/parents for the
            # dying before this point); this is pure post-death cleanup,
            # same "dead weight, no observable behavior change" rationale
            # as the decayed-to-zero pruning in _update_relationships.
            # See docs/DECISIONS.md, "memory leak: unpruned
            # relationships" pass.
            for survivor in survivors:
                for dying_id in dying_ids:
                    survivor.relationships.pop(dying_id, None)
                    survivor.trust.pop(dying_id, None)
                    # Tier 0.1/0.2 additions: same "dead weight" cleanup
                    # — a feud/grievance against someone who died is
                    # meaningless to keep locked or tagged. Death is
                    # itself an explicit resolution.
                    survivor.relationship_flags.pop(dying_id, None)
                    survivor.grievances.pop(dying_id, None)
        if dying_ids:
            # A dead rider's mount goes back to the unclaimed pool rather
            # than staying claimed forever by nobody.
            for stl in settlements:
                for vehicle in stl.vehicles:
                    if vehicle.assigned_agent_id in dying_ids:
                        vehicle.assigned_agent_id = None
        return life_events

    def _tick_mourning(self) -> None:
        """v0.87.9, "ceremonies agents attend: funerals" — counts down
        every mourner's `mourning_ticks_remaining` (set by `_apply_
        deaths`, above), same "duration counter ticking down to a
        revert" shape as `sick_ticks`/`immune_ticks` (see `_tick_
        disease`). On reaching 0, grief eases (MOURNING_GRIEF_EASE —
        never to 0, the loss isn't erased) and both mourning fields
        reset, handing movement back to the agent's normal goal. Cheap:
        a flat scan of `self.agents`, only agents with a nonzero counter
        do any real work."""
        for agent in self.agents:
            if agent.mourning_ticks_remaining <= 0:
                continue
            agent.mourning_ticks_remaining -= 1
            if agent.mourning_ticks_remaining <= 0:
                agent.mourning_target = None
                current = agent.emotions.get(EMOTION_GRIEF, 0.0)
                agent.emotions[EMOTION_GRIEF] = max(0.0, current - MOURNING_GRIEF_EASE)

    def _tick_weddings(self) -> None:
        """v0.87.10, "ceremonies agents attend: weddings" — the joyful
        companion to `_tick_mourning` above, same duration-counter shape.
        Counts down every guest's `wedding_ticks_remaining` (set by
        `_maybe_reproduce`); on reaching 0, every guest gets a real joy
        bump (WEDDING_JOY_BUMP — the celebration itself, distinct from
        the couple's own EMOTION_BIRTH_JOY_BUMP already applied at the
        triggering birth) and both wedding fields reset, handing
        movement back to the guest's normal goal."""
        for agent in self.agents:
            if agent.wedding_ticks_remaining <= 0:
                continue
            agent.wedding_ticks_remaining -= 1
            if agent.wedding_ticks_remaining <= 0:
                agent.wedding_target = None
                bump_emotion(agent, EMOTION_JOY, WEDDING_JOY_BUMP)

    # --- LLM core cast (v0.70.0) ----------------------------------------------

    def is_core(self, agent_id: int) -> bool:
        """True if `agent_id` is in the LLM-driven core cast — the gate the
        engine consults before spending an Ollama call on this agent's
        cognition, or on a dialogue pair. See `core_agent_ids`."""
        return agent_id in self.core_agent_ids

    def _prominence(self, agent: Agent) -> float:
        """A cheap 'how much of a protagonist is this agent' score used
        only to refill an open core-cast seat (see maintain_core_cast).
        Longevity + social centrality + skill + reputation, weighted so
        no single signal dominates. Not persisted, not consumed by any
        other mechanic — purely a ranking key, recomputed on demand.
        Phase L (docs/VISION-2026-07.md) added the reputation term: the
        vision doc explicitly calls for extending this ranking's inputs
        rather than adding a parallel one. Phase 3.B ("occupation ->
        identity/status") adds `OCCUPATION_STATUS_BONUS` the same way —
        a mayor/priest's office itself carries real baseline standing,
        the "positive counterpart" to `standing_penalty`'s ostracism-
        only negative signal."""
        bonds = sum(1 for v in agent.relationships.values() if abs(v) >= PROMINENCE_BOND_THRESHOLD)
        skill = sum(agent.skills.values())
        return (
            float(agent.age_ticks)
            + bonds * PROMINENCE_BOND_WEIGHT
            + skill * PROMINENCE_SKILL_WEIGHT
            + self.reputation(agent.id) * PROMINENCE_REPUTATION_WEIGHT
            + OCCUPATION_STATUS_BONUS.get(agent.occupation, 0.0)
        )

    def reputation(self, agent_id: int) -> float:
        """Phase L "Reputation" (docs/VISION-2026-07.md, "Society &
        Power"): -1..1, the mean trust every living agent who has an
        opinion holds toward `agent_id` — a derived aggregate, not new
        per-pair state (Agent.trust already carries the raw signal; this
        just reads it from the other direction and caches the read).
        Reads 0.0 (neutral) for an unknown id or one held by fewer than
        REPUTATION_MIN_SOURCES agents. Refreshed monthly by
        `_refresh_reputation` — a live-tick value would need an O(agents)
        rescan on every call, and reputation is exactly the kind of slow-
        moving social signal that doesn't need tick-fresh precision.

        §9 'long-term reputation and family legacy': a dead agent isn't
        simply neutral — their last known standing lingers, fading, in
        `_deceased_reputation_legacy` (see that field's docstring)."""
        if agent_id in self._reputation_cache:
            return self._reputation_cache[agent_id]
        return self._deceased_reputation_legacy.get(agent_id, 0.0)

    def family_legacy_reputation(self, member_agent_ids: set[int]) -> float:
        """§9 'long-term reputation and family legacy': an institution's
        (typically FAMILY's) standing across ALL members it ever had,
        living or dead — `member_agent_ids` never shrinks on death (see
        `Institution.member_agent_ids`'s docstring), so this is a real
        aggregate of a household's reputation across generations, not
        just its currently-living members. Reads 0.0 for an institution
        with no member ever crossing REPUTATION_MIN_SOURCES."""
        values = [
            self.reputation(agent_id) for agent_id in member_agent_ids
            if agent_id in self._reputation_cache or agent_id in self._deceased_reputation_legacy
        ]
        return sum(values) / len(values) if values else 0.0

    def _refresh_reputation(self) -> None:
        """Monthly rebuild of `_reputation_cache` — one O(agents) pass
        over every living agent's `trust` dict (each entry read from the
        truster's side, attributed to the trusted party), then averaged.
        Called from the engine's existing month_end temperament tick
        (see `_maybe_tick_temperament`) — same cheap, no-LLM cadence,
        not its own scheduled job.

        §9 'long-term reputation and family legacy': before dropping an
        id that's no longer alive, snapshot its last cached reputation
        into `_deceased_reputation_legacy` (only the first time — a
        second death-adjacent month must not re-snapshot and undo any
        fade already applied), then fade every already-tracked legacy
        entry by LEGACY_REPUTATION_DECAY, pruning past LEGACY_
        REPUTATION_FLOOR."""
        sums: dict[int, float] = {}
        counts: dict[int, int] = {}
        for agent in self.agents:
            for target_id, value in agent.trust.items():
                sums[target_id] = sums.get(target_id, 0.0) + value
                counts[target_id] = counts.get(target_id, 0) + 1
        alive_ids = {a.id for a in self.agents}
        new_cache = {
            target_id: sums[target_id] / counts[target_id]
            for target_id in sums
            if target_id in alive_ids and counts[target_id] >= REPUTATION_MIN_SOURCES
        }
        for target_id, value in self._reputation_cache.items():
            if target_id not in new_cache and target_id not in self._deceased_reputation_legacy:
                self._deceased_reputation_legacy[target_id] = value
        self._reputation_cache = new_cache
        faded: dict[int, float] = {}
        for target_id, value in self._deceased_reputation_legacy.items():
            value *= 1.0 - LEGACY_REPUTATION_DECAY
            if abs(value) >= LEGACY_REPUTATION_FLOOR:
                faded[target_id] = value
        self._deceased_reputation_legacy = faded

    def maintain_core_cast(self, cast_size: int) -> list[Agent]:
        """Keep `core_agent_ids` at `cast_size` living members. Called once
        per tick by the engine before it schedules cognition/dialogue.
        Returns the agents newly added this call (v0.78.4, for `Agent.
        mind`'s one-time genesis-style authoring — empty list on every
        tick that doesn't fill a seat, i.e. almost always).

        Two rules, in order:
        1. Prune the dead — a departed protagonist frees a seat.
        2. Fill open seats from the most-prominent living non-members
           (`_prominence`), tie-broken by lowest id for determinism.
        Members are never demoted while alive: the cast is deliberately
        sticky so the town's LLM-driven characters are a stable presence
        across a long run, not a set that churns every time someone
        newly-notable is born (persistent identity, CLAUDE.md). Seeding
        is automatic — on a fresh world the founders are the only agents,
        so the first call fills the cast from them. `cast_size <= 0`
        empties the cast (LLM cognition/dialogue fully off)."""
        alive_ids = {a.id for a in self.agents}
        self.core_agent_ids &= alive_ids
        if cast_size <= 0:
            self.core_agent_ids.clear()
            return []
        # Sticky cap: if the cast is somehow over size (cast_size lowered
        # at runtime), let attrition bring it down rather than evicting a
        # living protagonist mid-life.
        deficit = cast_size - len(self.core_agent_ids)
        if deficit <= 0:
            return []
        candidates = [a for a in self.agents if a.id not in self.core_agent_ids]
        candidates.sort(key=lambda a: (-self._prominence(a), a.id))
        added = candidates[:deficit]
        for agent in added:
            self.core_agent_ids.add(agent.id)
        return added

    def _maybe_rotate_core_cast(self, rng: random.Random) -> tuple[Agent, Agent] | None:
        """Called once a month (see CORE_CAST_ROTATION_MARGIN's
        docstring for why this exists). At most one swap per call: finds
        the weakest living core member and the strongest living
        non-member by `_prominence`; if the outsider clears the margin
        AND the monthly roll hits, swaps them — the incumbent keeps
        every bit of their accumulated history (memories, mind, secrets,
        relationships, life_digest all live on the plain `Agent`, never
        cleared here), they simply stop being the target of new core-
        cast-gated LLM cognition/dialogue/belief jobs going forward.
        Returns (outgoing, incoming) on a real swap, else None — the
        caller can turn a real swap into a life event."""
        core_members = [a for a in self.agents if a.id in self.core_agent_ids]
        if not core_members:
            return None
        outgoing = min(core_members, key=lambda a: (self._prominence(a), -a.id))
        non_members = [a for a in self.agents if a.id not in self.core_agent_ids]
        if not non_members:
            return None
        incoming = max(non_members, key=lambda a: (self._prominence(a), -a.id))
        weakest_score = self._prominence(outgoing)
        strongest_score = self._prominence(incoming)
        # A non-positive weakest score has no meaningful multiplicative
        # margin to clear against — fall back to requiring the outsider
        # be positive at all (a real, if modest, protagonist claim).
        required = weakest_score * CORE_CAST_ROTATION_MARGIN if weakest_score > 0 else 0.0
        if strongest_score <= required:
            return None
        if rng.random() >= CORE_CAST_ROTATION_CHANCE_PER_MONTH:
            return None
        self.core_agent_ids.discard(outgoing.id)
        self.core_agent_ids.add(incoming.id)
        return outgoing, incoming

    def decay_memory_salience(self) -> None:
        """Deferred item 4 of docs/VISION-2026-07-LEARNING.md: called
        once/sim-day (`day_end`) to apply `MEMORY_FADE_DECAY_PER_DAY` to
        every living agent's `memory_salience` list — the deterministic
        "gradual continuous fade" half of the batch (item 5's LLM-
        authored skill-mastery narration is the one new call). Population-
        wide, not core-cast-gated: this touches no LLM budget at all, so
        the standing per-agent-LLM-decision gating rule doesn't apply.
        Cheap — bounded by `population * MAX_AGENT_MEMORIES`, a few
        thousand float multiplications even at `POPULATION_CAP`."""
        for agent in self.agents:
            salience = agent.memory_salience
            causes = agent.memory_causes
            for i in range(len(salience)):
                # v0.87.16 "improve memory weighting — major life
                # events should remain influential for years": a memory
                # tagged with a KNOWN objective cause (`memory_causes`
                # — a death, a dispute outcome, an inheritance; see
                # v0.87.14 "causal memory links") always decays at the
                # much slower MEMORY_MAJOR_EVENT_DECAY_PER_DAY rate,
                # permanently — checking `because` rather than the
                # CURRENT (already-decaying) salience avoids a subtle
                # trap: a threshold check against the decayed value
                # would let a memory slip below the slow-rate cutoff
                # partway through, switch to the fast rate for its
                # remaining life, and still converge to the floor
                # within about a year regardless of how significant it
                # started — defeating the whole point. An UNTAGGED
                # memory (no known cause, just emotionally vivid at
                # formation) still gets the slow rate WHILE its current
                # salience remains high, a lighter-weight bonus without
                # the same permanence guarantee.
                if causes[i] if i < len(causes) else False:
                    rate = MEMORY_MAJOR_EVENT_DECAY_PER_DAY
                elif salience[i] >= MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD:
                    rate = MEMORY_MAJOR_EVENT_DECAY_PER_DAY
                else:
                    rate = MEMORY_FADE_DECAY_PER_DAY
                salience[i] = max(MEMORY_FADE_FLOOR, salience[i] * rate)

    def tick_plans(self) -> None:
        """v0.87.15, "bounded episodic planning" (docs/IDEAS-2026-07-
        EMERGENCE.md §7): called once/sim-day (`day_end`), same cadence
        as `decay_memory_salience` above — decrements every living
        agent's active `Agent.plan["days_remaining"]`, clearing it
        (reverts to `None`) once it reaches 0. Reflect() (`Simulation
        Engine._maybe_schedule_personal_belief`) may form a fresh plan
        afterward if the agent's situation still warrants one.
        Population-wide, zero LLM cost — bounded by population size,
        one dict-or-None check per agent.

        Audit follow-up (v1.3.38 cognition-architecture audit, "a
        plan-fulfillment check"): a genuine deterministic judgment on
        expiry rather than silently reverting to `None` — a plan whose
        `progress_note` was ever updated read as real, lived pursuit
        ("pursued, ran out of time"); one that was never touched read
        as truly abandoned (formed, then nothing came of it). Not a
        second LLM call — the judgment is purely "was this plan ever
        acted on," derivable from state Reflect() already writes."""
        for agent in self.agents:
            if agent.plan is None:
                continue
            agent.plan["days_remaining"] -= 1
            if agent.plan["days_remaining"] <= 0:
                intent = agent.plan.get("intent", "")
                if agent.plan.get("progress_note"):
                    _remember(
                        agent, f"Their plan to {intent} ran out of time, though they'd made real headway.",
                        because="a plan resolved (pursued)",
                    )
                elif intent:
                    _remember(
                        agent, f"Their plan to {intent} never came to anything.",
                        because="a plan resolved (abandoned)",
                    )
                agent.plan = None

    # --- cognition (Phase B) --------------------------------------------------

    def due_for_cognition(self, tick: int, ticks_per_day: int) -> list[Agent]:
        """Agents whose once-per-sim-day goal reevaluation falls on this
        tick. Staggered by agent id (rather than all agents re-deciding on
        the same tick) so a full day's worth of LLM calls spreads evenly
        across the day instead of arriving in one burst — see
        docs/DECISIONS.md, B2."""
        if ticks_per_day <= 0:
            return []
        return [agent for agent in self.agents if (tick + agent.id) % ticks_per_day == 0]

    @classmethod
    def nearest_food_steps(
        cls, agent: Agent, farms: FarmGrid, settlement: Settlement,
        resources: ResourceGrid, wildlife: WildlifeGrid,
    ) -> int | None:
        """Manhattan distance to the nearest food source the agent's
        movement layer would actually target (same candidate set as
        _dispatch_movement's FORAGE branch), or None if nothing is known.
        Built for the cognition prompt: the LLM chooses between
        forage/socialize/etc. far better when told whether food is even
        reachable (July 2026 review, LLM-cognition pass). Called only for
        the few agents due for cognition on a given tick — not per-agent
        per-tick."""
        target = (
            cls._nearest_position(agent, cls.ready_farm_positions(farms))
            or cls._nearest_position(agent, cls.stocked_granary_positions(settlement))
            or cls._nearest_grazer_herd(agent, wildlife)
            or cls._nearest_resource(agent, resources)
        )
        if target is None:
            return None
        return abs(target[0] - agent.x) + abs(target[1] - agent.y)

    def apply_goal(self, agent_id: int, goal: AgentGoal, reason: str, seek_target_id: int | None = None) -> None:
        """Apply a resolved goal to an agent by id. A no-op if the agent
        has since died — cognition results can arrive on a later tick than
        they were requested on (see SimulationEngine).

        `seek_target_id` (v0.87.8) is only meaningful alongside
        `AgentGoal.SEEK_PERSON` — always cleared for every other goal so
        a stale target from a PREVIOUS seek never lingers once the
        agent's goal moves on to something else."""
        for agent in self.agents:
            if agent.id == agent_id:
                agent.goal = goal
                agent.goal_reason = reason
                agent.seek_target_id = seek_target_id if goal is AgentGoal.SEEK_PERSON else None
                return

    def get(self, agent_id: int) -> Agent | None:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    def due_for_triggered_cognition(self, tick: int, cooldown_ticks: int) -> list[Agent]:
        """Agents in `last_triggered_agent_ids` (set fresh this tick by
        `tick()`/`_apply_deaths` — a hunger emergency or fresh grief)
        whose event-trigger cooldown has expired, so an agent stuck
        critically hungry for a long stretch gets re-reasoned-about
        periodically rather than hammering the LLM every single tick.
        Same cooldown-dict-plus-pruning shape as due_for_dialogue, keyed
        by a single agent id instead of a pair. Marks the returned
        agents' cooldown immediately, same rationale as due_for_dialogue.
        See docs/DECISIONS.md, "cognition triggers beyond daily
        cadence" pass."""
        if not self.last_triggered_agent_ids:
            return []
        alive_ids = {a.id for a in self.agents}
        prune_horizon = cooldown_ticks * 8
        stale_keys = [
            agent_id for agent_id, last in self.cognition_trigger_cooldowns.items()
            if agent_id not in alive_ids or tick - last > prune_horizon
        ]
        for key in stale_keys:
            del self.cognition_trigger_cooldowns[key]

        due: list[Agent] = []
        for agent in self.agents:
            if agent.id not in self.last_triggered_agent_ids:
                continue
            last = self.cognition_trigger_cooldowns.get(agent.id, -cooldown_ticks)
            if tick - last < cooldown_ticks:
                continue
            due.append(agent)
            self.cognition_trigger_cooldowns[agent.id] = tick
        return due

    # --- dialogue (Phase E2) ---------------------------------------------------

    def due_for_dialogue(
        self, seed: int, tick: int, cooldown_ticks: int,
    ) -> list[tuple[Agent, Agent]]:
        """Colocated, awake pairs whose cooldown has expired, up to
        MAX_DIALOGUES_PER_TICK — every one of these resolves via the
        deterministic fallback (relationship/trust/gossip effects still
        apply, no Ollama call). Explicit user directive: LLM dialogue no
        longer scales with core-cast size at all — it's reserved for the
        single fixed `voice_pair_ids` pair, scheduled separately via
        `due_for_voice_dialogue`. That exact pair is excluded here (their
        conversational energy goes into the voice thread, not a
        redundant fallback exchange with each other) — they're still
        eligible for an ordinary fallback exchange with anyone ELSE.

        Selection is a deterministic namespaced-RNG shuffle, reproducible
        for a given seed. Marks each returned pair's cooldown
        immediately, so it isn't re-selected next tick.

        Also prunes `dialogue_cooldowns`: entries for dead agents and
        entries stale past `cooldown_ticks * 8` (they no longer prevent
        anything) — the dict otherwise grew unbounded on a long run. See
        docs/DECISIONS.md, diagnostics pass."""
        alive_ids = {a.id for a in self.agents}
        prune_horizon = cooldown_ticks * 8
        stale_keys = [
            key for key, last in self.dialogue_cooldowns.items()
            if key[0] not in alive_ids or key[1] not in alive_ids or tick - last > prune_horizon
        ]
        for key in stale_keys:
            del self.dialogue_cooldowns[key]
            self.dialogue_topics.pop(key, None)

        by_position: dict[tuple[int, int], list[Agent]] = {}
        for agent in self.agents:
            if agent.state is AgentState.AWAKE:
                by_position.setdefault((agent.x, agent.y), []).append(agent)

        voice_pair_set = set(self.voice_pair_ids) if self.voice_pair_ids else set()
        candidates: list[tuple[Agent, Agent]] = []
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                if {a.id, b.id} == voice_pair_set:
                    continue
                last = self.dialogue_cooldowns.get((a.id, b.id), -cooldown_ticks)
                if tick - last < cooldown_ticks:
                    continue
                candidates.append((a, b))

        rng = _namespaced_rng(seed, tick, "dialogue_select")
        rng.shuffle(candidates)
        fallback_pairs = candidates[:MAX_DIALOGUES_PER_TICK]
        for a, b in fallback_pairs:
            self.dialogue_cooldowns[(a.id, b.id)] = tick
        return fallback_pairs

    def _narrative_significance(self, agent, extra_scores: dict[int, float] | None = None) -> float:
        """"Shifting protagonists rather than permanent stars" (explicit
        user directive): a `_prominence`-baseline score (so an otherwise
        quiet week still favors an established figure) layered with real
        narrative-event bonuses — the same signal a reader would point
        to and say "that's who the story is about right now." `extra_
        scores` (agent_id -> bonus) carries the two signals that live
        outside `Agent`/`Population` and must be computed at the engine
        call site: a recent invention (`World.invented_concepts`) and
        active COUNCIL membership ("a council elder") — both read
        Settlement/World state `Population` deliberately doesn't hold a
        reference to."""
        score = self._prominence(agent)
        emotion = dominant_emotion(agent.emotions)
        if emotion == EMOTION_GRIEF:
            score += NARRATIVE_GRIEF_BONUS  # "a grieving parent"
        elif emotion is not None:
            score += NARRATIVE_EMOTION_BONUS
        if any(flag == "feud" for flag in agent.relationship_flags.values()):
            score += NARRATIVE_REBEL_BONUS  # ostracized/hardened feud — "a rebel"
        score += agent.extreme_event_count * NARRATIVE_EXTREME_EVENT_WEIGHT
        if extra_scores:
            score += extra_scores.get(agent.id, 0.0)
        return score

    def _strongest_core_bond(self, agent_id: int, exclude_ids: frozenset[int] = frozenset()) -> int | None:
        """The living core-cast member `agent_id` has the strongest
        relationship with, excluding `exclude_ids` and themself. `None`
        if `agent_id` is unknown or has no such bond."""
        agent = self.get(agent_id)
        if agent is None:
            return None
        alive_ids = {a.id for a in self.agents}
        bonded = [
            (other_id, score) for other_id, score in agent.relationships.items()
            if other_id in self.core_agent_ids and other_id in alive_ids
            and other_id != agent_id and other_id not in exclude_ids
        ]
        return max(bonded, key=lambda pair: pair[1])[0] if bonded else None

    def select_voice_pair(
        self, exclude_ids: frozenset[int] = frozenset(), extra_scores: dict[int, float] | None = None,
    ) -> tuple[int, int] | None:
        """Picks this week's "protagonist" — the living core-cast member
        with the highest `_narrative_significance` (tie-broken by lowest
        id), excluding `exclude_ids` — then partners them with their
        strongest bond among the remaining core cast, falling back to
        the next-highest-significance candidate if the protagonist has
        no such bond. Used for the initial pick, the "both died, start
        fresh" rotation case, and the weekly reselection. Returns None
        if fewer than 2 eligible core-cast members exist yet (a very
        young world)."""
        candidates = [
            a for a in self.agents if a.id in self.core_agent_ids and a.id not in exclude_ids
        ]
        if len(candidates) < 2:
            return None
        candidates.sort(key=lambda a: (-self._narrative_significance(a, extra_scores), a.id))
        protagonist = candidates[0]
        partner_id = self._strongest_core_bond(protagonist.id, exclude_ids=exclude_ids)
        if partner_id is None:
            partner_id = candidates[1].id
        return (protagonist.id, partner_id)

    def maintain_voice_pair(
        self, tick: int, week_rotation: bool = False, extra_scores: dict[int, float] | None = None,
    ) -> tuple[int, int] | None:
        """Explicit user directive: keeps exactly one fixed pair of core-
        cast members as the sole LLM-dialogue voice of the town, called
        every tick (cheap — a no-op unless the pair actually changed).
        Picks an initial pair via `select_voice_pair` if there is none
        yet; if one member has since died, rotates to the survivor's
        strongest remaining bond among the current core cast (falling
        back to `select_voice_pair` if the survivor has no bonds at all);
        if both have died, picks an entirely fresh pair.

        `week_rotation=True` (the caller passes this on a real in-game
        week boundary) forces a fresh `select_voice_pair` reselection
        regardless of whether the current pair is still alive — "shifting
        protagonists rather than permanent stars": some weeks the mayor
        dominates, other weeks it's a grieving parent, later an inventor
        or a council elder. The still-living previous pair is naturally
        excluded from consideration (see `select_voice_pair`'s partner-
        bond fallback) only if they no longer score highest; there is no
        forced "never repeat" rule — if the same pair is still genuinely
        the town's liveliest story, they stay.

        Any change clears `voice_conversation` — a new partner has no
        business continuing the old thread. Returns the NEW pair only
        when it actually changed this call, else None (so the caller can
        log a real "the town's voice passes to..." event only on a
        genuine change, not every tick)."""
        alive_ids = {a.id for a in self.agents}
        if self.voice_pair_ids is None:
            new_pair = self.select_voice_pair(extra_scores=extra_scores)
            if new_pair is None:
                return None
            self.voice_pair_ids = new_pair
            self.voice_conversation = []
            return new_pair
        a_id, b_id = self.voice_pair_ids
        a_alive, b_alive = a_id in alive_ids, b_id in alive_ids
        if a_alive and b_alive and not week_rotation:
            return None
        if week_rotation and a_alive and b_alive:
            new_pair = self.select_voice_pair(extra_scores=extra_scores)
        elif not a_alive and not b_alive:
            new_pair = self.select_voice_pair(extra_scores=extra_scores)
        else:
            survivor_id = a_id if a_alive else b_id
            replacement_id = self._strongest_core_bond(survivor_id)
            if replacement_id is None:
                fallback = self.select_voice_pair(exclude_ids=frozenset({survivor_id}), extra_scores=extra_scores)
                replacement_id = fallback[0] if fallback else None
            new_pair = (survivor_id, replacement_id) if replacement_id is not None else None
        if new_pair is None:
            self.voice_pair_ids = None
            self.voice_conversation = []
            return None
        if new_pair == self.voice_pair_ids:
            return None  # week_rotation reselected the same pair — not a real change
        self.voice_pair_ids = new_pair
        self.voice_conversation = []
        return new_pair

    def due_for_voice_dialogue(self, tick: int, cooldown_ticks: int) -> tuple[Agent, Agent] | None:
        """The voice pair's own dedicated scheduling path — colocated,
        both awake, cooldown expired. Returns None otherwise (no pair
        set yet, one or both not present/awake, or still cooling down).
        Marks the cooldown immediately on a hit, same "don't re-select
        while in flight" discipline as `due_for_dialogue`."""
        if self.voice_pair_ids is None:
            return None
        a = self.get(self.voice_pair_ids[0])
        b = self.get(self.voice_pair_ids[1])
        if a is None or b is None:
            return None
        if a.state is not AgentState.AWAKE or b.state is not AgentState.AWAKE:
            return None
        if (a.x, a.y) != (b.x, b.y):
            return None
        if tick - self.voice_dialogue_last_tick < cooldown_ticks:
            return None
        self.voice_dialogue_last_tick = tick
        return (a, b)

    def record_voice_line(self, speaker_id: int, text: str, tick: int) -> None:
        """Appends one line to `voice_conversation` (oldest dropped past
        MAX_VOICE_CONVERSATION_STORED) — the voice pair's own running
        thread, read back by `llm/dialogue.py`'s `build_voice_prompt` as
        "the conversation so far" so the next call genuinely continues
        it rather than re-opening small talk."""
        self.voice_conversation.append({"speaker_id": speaker_id, "text": text, "tick": tick})
        if len(self.voice_conversation) > MAX_VOICE_CONVERSATION_STORED:
            del self.voice_conversation[: len(self.voice_conversation) - MAX_VOICE_CONVERSATION_STORED]

    def recent_dialogue_topics(self, a_id: int, b_id: int) -> list[str]:
        """The stored `dialogue_topics` ring for this pair, if any —
        v0.87.12 "dialogue novelty memory". Read at the call site right
        before building a fresh LLM dialogue prompt for the pair."""
        key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        return self.dialogue_topics.get(key, [])

    def record_dialogue_topic(self, a_id: int, b_id: int, topic: str) -> None:
        """Append `topic` to this pair's ring, capped at DIALOGUE_TOPICS_
        RING_MAX (oldest dropped first) — called once a real LLM-
        authored exchange supplies a non-blank topic.

        Root-cause fix for a live audit finding (P0.2a): appended
        unconditionally, so a pair stuck on one recurring subject filled
        their own ring with the SAME topic repeated — `dialogue.
        build_prompt`'s novelty line then literally read "You two have
        lately talked about: garden, garden, garden," which is the
        opposite of a novelty prompt. Skip the append when it's a
        repeat of the ring's own last entry (case/whitespace-
        insensitive) — a pair can still return to a topic after
        something else came up, just not stutter on it back-to-back."""
        if not topic:
            return
        key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
        ring = self.dialogue_topics.setdefault(key, [])
        if ring and ring[-1].strip().lower() == topic.strip().lower():
            return
        ring.append(topic)
        if len(ring) > DIALOGUE_TOPICS_RING_MAX:
            del ring[: len(ring) - DIALOGUE_TOPICS_RING_MAX]

    def apply_dialogue(
        self, a_id: int, b_id: int, sentiment: str, rumor: str = "", line_a: str = "", line_b: str = "",
        promise: str = "", debt_delta: float = 0.0, secret_revealed: bool = False,
        misunderstanding: bool = False, goal_change: bool = False,
    ) -> tuple[Agent, Agent, bool] | None:
        """Apply a resolved dialogue's sentiment as a relationship nudge,
        on top of the passive per-tick colocation gain. Returns None (a
        no-op) if either agent has since died — dialogue results can
        arrive on a later tick than requested, same as cognition.

        Also the entry point for relationship *memory* (not just a
        number): crossing into a close bond or a rivalry, and hearing a
        rumor, each leave a short entry in both agents'
        `Agent.memories` — see docs/DECISIONS.md, relationship-memory
        pass. Deliberately not triggered by the passive per-tick
        colocation gain/decay — only these explicit dialogue-driven
        moments are memorable enough to log, or every agent's memory
        would fill with "still standing near someone" noise.

        The third return value, `surfaced`, is True exactly when this
        exchange crossed into a close bond/rivalry or carried a rumor —
        i.e. exactly the moments memorable enough to also log — so the
        caller (SimulationEngine) can distinguish a "surfaced"
        conversation from routine background chatter in the UI's main
        event feed without duplicating this threshold logic. See
        docs/DECISIONS.md, Observatory UI pass.

        `promise`/`debt_delta`/`secret_revealed`/`misunderstanding`/
        `goal_change` (Phase 2, "dialogue as a simulation event",
        docs/VISION-2026-07-21-SELFEVOLVING.md): optional structured
        outcomes an LLM-authored exchange may report (never present on
        a deterministic-fallback exchange — `dialogue.parse_dialogue`
        only ever surfaces these from a real model response). Each is
        independently a no-op at its default ("" / 0.0 / False) — most
        exchanges are still just talk. `promise` writes onto the
        LEDGER (Phase 0), not `memories`, so a later dialogue call
        between the same pair can read it back as an open thread
        (`Ledger.open_promises`, see `SimulationEngine._schedule_due_
        dialogue`'s `open_thread` param)."""
        agent_a, agent_b = self.get(a_id), self.get(b_id)
        if agent_a is None or agent_b is None:
            return None
        surfaced = False
        delta = DIALOGUE_SENTIMENT_DELTA.get(sentiment, 0.0)
        # Trust in the speaker of a rumor (below) is read *before* this
        # exchange's own nudge — the receiving agent's existing opinion
        # of the source's credibility, not one freshly inflated by the
        # warm chat that happened to also carry the rumor.
        trust_a_in_b = agent_a.trust.get(b_id, 0.0)
        trust_b_in_a = agent_b.trust.get(a_id, 0.0)
        if delta:
            before = agent_a.relationships.get(b_id, 0.0)
            new_value = clamp(before + delta, -1.0, 1.0)
            agent_a.relationships[b_id] = new_value
            agent_b.relationships[a_id] = clamp(agent_b.relationships.get(a_id, 0.0) + delta, -1.0, 1.0)
            if before < REPRODUCTION_AFFINITY_THRESHOLD <= new_value:
                _remember(agent_a, f"Grew close with {agent_b.name}.")
                _remember(agent_b, f"Grew close with {agent_a.name}.")
                surfaced = True
            elif before > RIVALRY_THRESHOLD >= new_value:
                _remember(agent_a, f"Fell out with {agent_b.name}.")
                _remember(agent_b, f"Fell out with {agent_a.name}.")
                surfaced = True
        trust_delta = TRUST_DELTA.get(sentiment, 0.0)
        if trust_delta:
            agent_a.trust[b_id] = clamp(trust_a_in_b + trust_delta, -1.0, 1.0)
            agent_b.trust[a_id] = clamp(trust_b_in_a + trust_delta, -1.0, 1.0)
        if rumor:
            # Trust lever: an agent who already doesn't put much stock in
            # the speaker remembers the rumor as hearsay, not fact —
            # that skepticism then reaches this agent's own future
            # cognition prompts (build_prompt reads the latest memory),
            # not just a flavor difference. See Agent.trust's docstring,
            # docs/DECISIONS.md, "trust lever" pass.
            if trust_a_in_b < TRUST_SKEPTICISM_THRESHOLD:
                _remember(agent_a, f"{agent_b.name} claims: {rumor} — I'm not sure I believe them.")
            else:
                _remember(agent_a, f"Heard a rumor: {rumor}")
            if trust_b_in_a < TRUST_SKEPTICISM_THRESHOLD:
                _remember(agent_b, f"{agent_a.name} claims: {rumor} — I'm not sure I believe them.")
            else:
                _remember(agent_b, f"Heard a rumor: {rumor}")
            self._apply_gossip_contagion(agent_a, agent_b, rumor, trust_a_in_b, trust_b_in_a)
            self.rumors_seeded_total += 1
            self.rumor_listener_exposures_total += 2
            surfaced = True
        if surfaced and line_a:
            # A conversation memorable enough to surface is memorable
            # enough to *remember having had* — previously two agents
            # could never reference their last exchange, because only
            # the rumor/bond-crossing side effects left memories, not
            # the conversation itself (July 2026 review, §3.5).
            _remember(agent_a, f'Talked with {agent_b.name} — they said "{line_b}"')
            _remember(agent_b, f'Talked with {agent_a.name} — they said "{line_a}"')
        if promise:
            agent_a.ledger.add_promise(b_id, {"text": promise, "made_tick": None})
            _remember(agent_a, f"I told {agent_b.name}: {promise}", because="made a promise")
            _remember(agent_b, f"{agent_a.name} promised: {promise}")
            surfaced = True
        if debt_delta:
            if debt_delta > 0:
                agent_a.debts[b_id] = agent_a.debts.get(b_id, 0.0) + debt_delta
            else:
                agent_b.debts[a_id] = agent_b.debts.get(a_id, 0.0) + (-debt_delta)
            surfaced = True
        if secret_revealed:
            for discloser, other in ((agent_a, agent_b), (agent_b, agent_a)):
                own_secret = next((s for s in discloser.secrets if other.name in s), None)
                if own_secret is not None:
                    discloser.secrets.remove(own_secret)
                    _remember(discloser, f"Let slip something I'd been holding back about {other.name}.")
                    _remember(other, f"{discloser.name} finally told me something they'd been hiding.")
                    surfaced = True
                    break
        if misunderstanding:
            agent_a.trust[b_id] = clamp(agent_a.trust.get(b_id, 0.0) - DIALOGUE_MISUNDERSTANDING_TRUST_PENALTY, -1.0, 1.0)
            agent_b.trust[a_id] = clamp(agent_b.trust.get(a_id, 0.0) - DIALOGUE_MISUNDERSTANDING_TRUST_PENALTY, -1.0, 1.0)
        if goal_change:
            agent_a.life_event_since_goal = True
            agent_b.life_event_since_goal = True
        return agent_a, agent_b, surfaced

    def _apply_gossip_contagion(
        self, agent_a: Agent, agent_b: Agent, rumor: str, trust_a_in_b: float, trust_b_in_a: float,
    ) -> None:
        """If the rumor names a specific living third villager, each
        listener's opinion of that person relaxes toward the speaker's —
        gossip as a real social force, not just a memory string. Uses
        word-boundary name matching; skips ambiguous matches (multiple
        named villagers) the same way belief resolution does, and skips
        listeners who don't trust the speaker (the existing skepticism
        threshold). See GOSSIP_OPINION_CONTAGION in agents/agent.py."""
        tokens = {token.strip(".,!?;:'\"") for token in rumor.lower().split()}
        subjects = [
            agent for agent in self.agents
            if agent.id not in (agent_a.id, agent_b.id)
            and agent.name.split()[0].lower() in tokens
        ]
        if len(subjects) != 1:
            return  # nobody named, or ambiguous — a rumor about "the harvest" moves no opinions
        subject = subjects[0]
        for listener, speaker, trust in (
            (agent_a, agent_b, trust_a_in_b), (agent_b, agent_a, trust_b_in_a),
        ):
            if trust < TRUST_SKEPTICISM_THRESHOLD:
                continue  # skeptical listeners don't let hearsay move their opinion
            speaker_view = speaker.relationships.get(subject.id, 0.0)
            listener_view = listener.relationships.get(subject.id, 0.0)
            step = GOSSIP_OPINION_CONTAGION * (speaker_view - listener_view)
            step = max(-GOSSIP_OPINION_MAX_STEP, min(GOSSIP_OPINION_MAX_STEP, step))
            if step:
                listener.relationships[subject.id] = clamp(listener_view + step, -1.0, 1.0)

    def _apply_rumor_retelling_fitness(self, agent: Agent, retelling: str, fitness: float) -> str | None:
        """A17's "false beliefs propagate if fit, not suppressed for
        being false" axis (`world.memetics.rumor_fitness`). Distinct
        from `_apply_gossip_contagion` above (a two-listener exchange
        pulling toward the speaker's view): this is the RETELLER's own
        opinion of whoever their retelling names polarizing FURTHER in
        whichever direction it already leans, scaled by the retelling's
        dramatic fitness alone. See RUMOR_FITNESS_POLARIZE_SCALE's
        docstring for why truth never enters this calculation — a
        rehearsed, embellished retelling entrenches the reteller's own
        view exactly as readily whether or not it stayed faithful to
        what was actually heard. Returns the named subject's name (for
        dev-console diagnostics) or None if nobody nameable was found."""
        tokens = {token.strip(".,!?;:'\"") for token in retelling.lower().split()}
        subjects = [
            other for other in self.agents
            if other.id != agent.id and other.name.split()[0].lower() in tokens
        ]
        if len(subjects) != 1:
            return None
        subject = subjects[0]
        view = agent.relationships.get(subject.id, 0.0)
        if view == 0.0:
            return None  # nothing to polarize yet — never invents a direction
        step = RUMOR_FITNESS_POLARIZE_SCALE * fitness * (1.0 if view > 0 else -1.0)
        agent.relationships[subject.id] = clamp(view + step, -1.0, 1.0)
        return subject.name

    # --- disputes: rare LLM-mediated resolution of a festered feud (v0.64.0) ----

    def due_for_dispute(self, tick: int, cooldown_ticks: int) -> tuple[Agent, Agent] | None:
        """At most one deeply-soured pair per tick (EITHER side's
        relationship at or below DISPUTE_RELATIONSHIP_THRESHOLD, both
        alive, cooldown expired) whose feud is ripe for a rare
        LLM-mediated resolution moment — see SimulationEngine.
        _maybe_schedule_dispute. Marks the cooldown immediately, same
        convention as due_for_dialogue. Colocation deliberately NOT
        required: a feud simmers regardless of where either party
        happens to be standing.

        "Definitive checklist" Tier 2.2 (2026-07-21): previously
        required BOTH sides to have soured past the threshold — "the
        resentment must be mutual, not one-sided." That's a real
        interaction most disputes don't have: one party can resent the
        other (a theft victim, someone who was refused help) while the
        other party's own relationship reading stays neutral, and the
        old gate meant that grievance could never surface as a dispute
        at all. Now either direction crossing the threshold is enough —
        one-sided resentment is exactly the case `apply_dispute`'s
        "ostracism" outcome and grievance tagging (Agent.grievances)
        exist to dramatize."""
        alive_ids = {a.id for a in self.agents}
        prune_horizon = cooldown_ticks * 4
        stale_keys = [
            key for key, last in self.dispute_cooldowns.items()
            if key[0] not in alive_ids or key[1] not in alive_ids or tick - last > prune_horizon
        ]
        for key in stale_keys:
            del self.dispute_cooldowns[key]

        by_id = {a.id: a for a in self.agents}
        for agent in self.agents:
            for other_id, value in agent.relationships.items():
                if other_id <= agent.id:
                    continue  # each pair once (lower id first)
                other = by_id.get(other_id)
                if other is None:
                    continue
                mutual_value = other.relationships.get(agent.id, 0.0)
                if value > DISPUTE_RELATIONSHIP_THRESHOLD and mutual_value > DISPUTE_RELATIONSHIP_THRESHOLD:
                    continue  # neither side has genuinely festered
                key = (agent.id, other_id)
                last = self.dispute_cooldowns.get(key, -cooldown_ticks)
                if tick - last < cooldown_ticks:
                    continue
                self.dispute_cooldowns[key] = tick
                return agent, other
        return None

    def apply_dispute(
        self, a_id: int, b_id: int, outcome: str, tick: int = 0, ostracized_id: int | None = None,
    ) -> tuple[Agent, Agent] | None:
        """Apply a resolved dispute outcome with real mechanical effects
        (see the DISPUTE_* constants) — a no-op returning None if either
        party has since died, same convention as apply_dialogue. `tick`
        (default 0 for legacy/test callers that don't pass one — only
        used as `Agent.lessons`' `formed_tick` metadata, never gates
        behavior) backs the deterministic reconciliation lesson below.
        `ostracized_id` (§1 "deviance loop") is required when `outcome
        == "ostracism"` — the caller resolves which of a_id/b_id via
        `llm.dispute.parse_dispute`'s `ostracized` field."""
        agent_a, agent_b = self.get(a_id), self.get(b_id)
        if agent_a is None or agent_b is None:
            return None
        pairs = ((agent_a, agent_b), (agent_b, agent_a))
        if outcome == "ostracism" and ostracized_id in (a_id, b_id):
            shunned, other = (agent_a, agent_b) if ostracized_id == a_id else (agent_b, agent_a)
            shunned.standing_penalty = min(1.0, shunned.standing_penalty + OSTRACISM_PENALTY)
            shunned.relationships[other.id] = max(-1.0, shunned.relationships.get(other.id, 0.0) + DISPUTE_FEUD_DEEPEN)
            other.relationships[shunned.id] = max(-1.0, other.relationships.get(shunned.id, 0.0) + DISPUTE_FEUD_DEEPEN)
            # Tier 0.1/0.2: ostracism is as much a hardened rupture as a
            # "feud" outcome — same decay-lock + tagged grievance.
            shunned.relationship_flags[other.id] = "feud"
            other.relationship_flags[shunned.id] = "feud"
            # Phase 3.B "identity, irreversible change": a permanent
            # feud is one of the vision doc's three named extreme-event
            # triggers for a permanent trait shift.
            _maybe_harden_trait(shunned)
            _maybe_harden_trait(other)
            add_grievance(shunned, other.id, "The village ostracized me.")
            _nudge_trait(shunned, TRAIT_SOCIABILITY, TRAIT_OSTRACISM_SOCIABILITY_NUDGE)
            _remember(shunned, "The village has turned its back on me.", because="ostracized by the village")
            _remember(other, f"The village ostracized {shunned.name} over what happened between us.", because=f"dispute with {shunned.name}")
            bump_emotion(shunned, EMOTION_GRIEF, EMOTION_DISPUTE_ANGER_BUMP)
        elif outcome == "reconcile":
            for me, them in pairs:
                me.relationships[them.id] = DISPUTE_RECONCILE_RELATIONSHIP
                me.trust[them.id] = clamp(me.trust.get(them.id, 0.0) + DISPUTE_TRUST_DELTA, -1.0, 1.0)
                # Tier 0.1: an explicit reconciliation is the only thing
                # that resolves a locked "feud" flag/grievance — it never
                # just fades out on its own. See relationship_flags'/
                # grievances' docstrings on Agent.
                me.relationship_flags.pop(them.id, None)
                clear_grievance(me, them.id)
                _remember(me, f"{them.name} and I made peace after our long feud.", because=f"dispute with {them.name}")
                # H6 extension: trusting someone again after a real feud and
                # being right about it teaches you to keep trusting — a
                # dedicated, slightly larger nudge than the routine trade-
                # contact one. See TRAIT_RECONCILE_NUDGE.
                _nudge_trait(me, TRAIT_SOCIABILITY, TRAIT_RECONCILE_NUDGE)
                bump_emotion(me, EMOTION_JOY, EMOTION_RECONCILE_JOY_BUMP)
                # Deferred item 1: deterministic, population-wide lesson
                # formation — see RECOVERY_LESSON_TEMPLATES's docstring.
                template = RECONCILE_LESSON_TEMPLATES[me.id % len(RECONCILE_LESSON_TEMPLATES)]
                push_lesson(me, "conflict", template, tick)
        elif outcome == "council_ruling":
            for me, them in pairs:
                # A ruling suppresses the feud without warming it — a
                # cool, enforced truce, not a reconciliation. Still an
                # explicit resolution (Tier 0.1): the lock lifts and the
                # truce value is free to drift like any ordinary
                # relationship from here.
                me.relationships[them.id] = DISPUTE_TRUCE_RELATIONSHIP
                me.relationship_flags.pop(them.id, None)
                clear_grievance(me, them.id)
                _remember(me, f"The council ruled on my dispute with {them.name}; we keep our distance now.", because=f"dispute with {them.name}")
        else:  # feud — the default/worst outcome
            for me, them in pairs:
                me.relationships[them.id] = max(
                    -1.0, me.relationships.get(them.id, 0.0) + DISPUTE_FEUD_DEEPEN
                )
                me.trust[them.id] = clamp(me.trust.get(them.id, 0.0) - DISPUTE_TRUST_DELTA, -1.0, 1.0)
                # Tier 0.1/0.2: "hardened for good" now means it —
                # exempted from ambient relationship decay (see
                # _update_relationships) until an explicit reconcile/
                # council_ruling, and the specific wrong is tagged in a
                # protected store the routine-memory flood can't evict.
                me.relationship_flags[them.id] = "feud"
                _maybe_harden_trait(me)  # Phase 3.B: permanent feud is an extreme-event trigger
                add_grievance(me, them.id, f"{them.name} and I have an unresolved feud.")
                _remember(me, f"My feud with {them.name} has hardened for good.", because=f"dispute with {them.name}")
                _nudge_trait(me, TRAIT_RESILIENCE, TRAIT_GRIEF_NUDGE)
                _nudge_trait(me, TRAIT_SOCIABILITY, TRAIT_FEUD_SOCIABILITY_NUDGE)
                bump_emotion(me, EMOTION_ANGER, EMOTION_DISPUTE_ANGER_BUMP)
        # Phase 1.B "self-evolving world" (docs/VISION-2026-07-21-
        # SELFEVOLVING.md): a resolved dispute — any outcome — is
        # exactly "a major dispute," one of the life events the doc
        # names as eligible to reshape a standing ambition. Consumed
        # by the next Reflect() call for whichever of these two gets
        # picked (see SimulationEngine._run_personal_belief).
        agent_a.life_event_since_goal = True
        agent_b.life_event_since_goal = True
        return agent_a, agent_b

    # --- deliberate guild founding (v0.64.0) ------------------------------------

    def deliberate_guild_candidate(
        self, settlement: Settlement, members: "list[Agent] | None" = None,
    ) -> tuple[Agent, str, list[Agent]] | None:
        """An ambitious master who might push a guild into existence
        early — see DELIBERATE_GUILD_MIN_MASTERS. Returns (founder,
        skill, current masters) for the first qualifying trade, or None.
        Pure query; the founding itself only happens if the LLM decision
        (or its fallback) says so — see found_guild."""
        existing_skills = {
            inst.name for inst in settlement.institutions if inst.kind is InstitutionKind.GUILD
        }
        for skill in (SKILL_FARMING, SKILL_CONSTRUCTION, SKILL_MEDICINE):
            if skill in existing_skills:
                continue
            masters = [
                a for a in (self.agents if members is None else members)
                if a.skills.get(skill, 0.0) >= GUILD_SKILL_MASTERY_THRESHOLD
            ]
            if not (DELIBERATE_GUILD_MIN_MASTERS <= len(masters) < GUILD_FORMATION_MASTER_COUNT):
                continue  # 0-1 masters is nothing to organize; 3+ auto-forms anyway
            founder = max(masters, key=lambda a: a.traits.get(TRAIT_AMBITION, 0.0))
            if founder.traits.get(TRAIT_AMBITION, 0.0) < DELIBERATE_GUILD_FOUNDER_AMBITION:
                continue
            return founder, skill, masters
        return None

    def found_guild(self, settlement: Settlement, skill: str, founder_id: int, tick: int) -> tuple[str, str] | None:
        """Actually found the guild a deliberate-founding decision
        approved. Re-validates at apply time (the decision resolves
        ticks later: the guild may have auto-formed meanwhile, or
        masters may have died below the deliberate minimum). Returns the
        life event, or None if founding is no longer valid."""
        if any(
            inst.kind is InstitutionKind.GUILD and inst.name == skill
            for inst in settlement.institutions
        ):
            return None
        masters = [
            a for a in self.agents
            if a.settlement_id == settlement.id and a.skills.get(skill, 0.0) >= GUILD_SKILL_MASTERY_THRESHOLD
        ]
        founder = self.get(founder_id)
        if founder is None or len(masters) < DELIBERATE_GUILD_MIN_MASTERS:
            return None
        guild = Institution(
            id=settlement.next_institution_id,
            kind=InstitutionKind.GUILD,
            founding_tick=tick,
            member_agent_ids={a.id for a in masters},
            name=skill,
        )
        settlement.next_institution_id += 1
        settlement.institutions.append(guild)
        _nudge_trait(founder, TRAIT_AMBITION, TRAIT_AMBITION_FOUNDING_NUDGE)
        _remember(founder, f"I brought the {skill} guild into being.")
        names = ", ".join(a.name for a in masters)
        return (
            "guild_formed",
            f"At {founder.name}'s urging, a {skill} guild formed early: {names}.",
        )

    # --- settlement fission (multiple named settlements, v0.65.0) ---------------

    def fission_candidate(
        self, settlements: list[Settlement], tick: int,
    ) -> tuple[Agent, Settlement] | None:
        """An ambitious member of a crowded, established settlement who
        might lead a founding party out — the deterministic candidacy
        half; whether they actually go is an LLM decision
        (llm/fission.py), same candidacy/decision split as deliberate
        guild founding. Pure query, no state change."""
        if len(settlements) >= MAX_SETTLEMENTS:
            return None
        if tick - self.last_fission_tick < FISSION_COOLDOWN_TICKS:
            return None
        settlements_by_id = {s.id: s for s in settlements}
        counts: dict[int, int] = {s.id: 0 for s in settlements}
        for a in self.agents:
            counts[a.settlement_id if a.settlement_id in settlements_by_id else settlements[0].id] += 1
        for stl in settlements:
            if not stl.name or counts[stl.id] < FISSION_MIN_POPULATION:
                continue
            housing = CAMP_TOLERANCE + HUT_CAPACITY * hut_capacity_multiplier(stl.era) * sum(
                1 for b in stl.buildings
                if b.kind is BuildingKind.HUT and b.stage is BuildingStage.STANDING
            )
            if counts[stl.id] <= housing:
                continue  # only real crowding pressure pushes people out
            leaders = [
                a for a in self.agents
                if a.settlement_id == stl.id and self._is_mature(a) and self._is_healthy(a)
                and a.traits.get(TRAIT_AMBITION, 0.0) >= FISSION_LEADER_AMBITION
            ]
            if not leaders:
                continue
            leader = max(leaders, key=lambda a: a.traits.get(TRAIT_AMBITION, 0.0))
            return leader, stl
        return None

    def fission_party(self, leader: Agent, home: Settlement) -> list[Agent] | None:
        """Who follows the leader out: their own family first (the
        FAMILY institutions that contain them), then whoever likes them
        enough (FISSION_PARTY_RELATIONSHIP), bounded by FISSION_PARTY_
        MIN/MAX and the mother settlement's FISSION_MIN_REMAINING floor.
        Returns None when a viable party can't be assembled — the
        candidacy then simply lapses until conditions change."""
        members = [a for a in self.agents if a.settlement_id == home.id]
        party: list[Agent] = [leader]
        taken = {leader.id}
        for inst in home.institutions:
            if inst.kind is not InstitutionKind.FAMILY or leader.id not in inst.member_agent_ids:
                continue
            for a in members:
                if len(party) >= FISSION_PARTY_MAX:
                    break
                if a.id in inst.member_agent_ids and a.id not in taken:
                    party.append(a)
                    taken.add(a.id)
        # Phase L (docs/VISION-2026-07.md "Society & Power"): a faction
        # is chosen loyalty, so a leader's faction-mates follow the same
        # way family does — after blood, before mere fondness.
        leader_faction = self.faction_of(leader.id, home)
        if leader_faction is not None:
            for a in members:
                if len(party) >= FISSION_PARTY_MAX:
                    break
                if a.id in leader_faction.member_agent_ids and a.id not in taken:
                    party.append(a)
                    taken.add(a.id)
        ranked = sorted(
            (a for a in members if a.id not in taken),
            key=lambda a: leader.relationships.get(a.id, 0.0),
            reverse=True,
        )
        for a in ranked:
            if len(party) >= FISSION_PARTY_MAX:
                break
            if leader.relationships.get(a.id, 0.0) >= FISSION_PARTY_RELATIONSHIP:
                party.append(a)
                taken.add(a.id)
        if len(party) < FISSION_PARTY_MIN:
            return None
        if len(members) - len(party) < FISSION_MIN_REMAINING:
            return None
        return party

    def depart_for_fission(
        self, party: list[Agent], new_settlement: Settlement, site: tuple[int, int],
        tick: int, home_name: str,
    ) -> None:
        """Actually send the party off: reassign their home, point their
        travel_target at the chosen site (see _dispatch_movement's
        journey override), and mark the world-wide fission cooldown.
        The new Settlement object itself (and its seed-materials grant)
        is created by the engine, which owns site selection."""
        for a in party:
            a.settlement_id = new_settlement.id
            a.travel_target = site
            _remember(a, f"We left {home_name} to found a new settlement of our own.")
        self.last_fission_tick = tick

    # --- festivals (collective behaviour) ---------------------------------------

    def avg_hunger(self) -> float:
        if not self.agents:
            return 0.0
        return sum(a.hunger for a in self.agents) / len(self.agents)

    # --- D6 "social scaling": districts (collective population) ----------------

    def _assign_to_district(self, settlement: Settlement, tick: int) -> District:
        """Returns the district a newly-collectivized person joins — the
        settlement's last district if it still has room, otherwise a
        freshly founded one (`district.DISTRICT_MAX_POPULATION`, the
        "smaller towns" half of D6's directive: growth beyond one
        district's cap reads as a new named ward, not an ever-growing
        blob). Mutates `settlement.districts`/`next_district_id`."""
        if settlement.districts and settlement.districts[-1].population < DISTRICT_MAX_POPULATION:
            return settlement.districts[-1]
        ordinal = settlement.next_district_id
        district = District(
            id=ordinal, settlement_id=settlement.id, name=fallback_district_name(ordinal),
            population=0, founding_tick=tick, avg_hunger=self.avg_hunger(),
        )
        settlement.districts.append(district)
        settlement.next_district_id += 1
        return district

    def _maybe_collectivize_excess_population(
        self, settlements: list[Settlement], tick: int,
    ) -> list[tuple[Settlement, str]]:
        """D6 (docs/ROADMAP-2026-07-REMAINING.md): once a settlement's
        individually-simulated non-core population crosses `district.
        DISTRICT_INDIVIDUAL_CAP`, the least-prominent excess is
        genuinely removed from individual simulation and folded into a
        District — see `hearthmind.settlement.district`'s module
        docstring for why this is the actual fix (bounds the pairwise
        Ledger social surface), not a cosmetic population count. The
        core cast and any living MAYOR are never candidates — same
        "named cast stays named" boundary `core_agent_ids` already
        draws for LLM budget, applied here to identity/social-surface
        scaling instead. Reuses the exact per-survivor Ledger cleanup
        `_apply_deaths` established (v0.42.0) — a collectivized person
        is gone from every acquaintance's relationships/trust/flags/
        grievances dict the same way a dead one is, since neither can
        ever be colocated again. Deliberately NOT reusing `_apply_
        deaths` itself: no grief, no memorial, no inheritance — this
        person didn't die, they moved into a life this simulation no
        longer tracks individually. Returns `(settlement, district_
        name)` pairs for each settlement's FIRST district founded this
        call, so the caller can narrate it once, not per person."""
        newly_founded: list[tuple[Settlement, str]] = []
        for settlement in settlements:
            non_core = [
                a for a in self.agents
                if a.settlement_id == settlement.id and a.id not in self.core_agent_ids
                and a.occupation != OCCUPATION_MAYOR
            ]
            excess = len(non_core) - DISTRICT_INDIVIDUAL_CAP
            if excess <= 0:
                continue
            candidates = sorted(non_core, key=lambda a: self._prominence(a))[:excess]
            candidate_ids = {a.id for a in candidates}
            had_district = bool(settlement.districts)
            for _ in candidates:
                district = self._assign_to_district(settlement, tick)
                district.population += 1
            if not had_district and settlement.districts:
                newly_founded.append((settlement, settlement.districts[0].name))
            self.agents = [a for a in self.agents if a.id not in candidate_ids]
            if self._store is not None:
                for cid in candidate_ids:
                    self._store.remove(cid)
            # Same "dead weight" per-field cleanup _apply_deaths uses
            # (v0.42.0/Tier 0.1) — a collectivized person can never be
            # colocated again either.
            for survivor in self.agents:
                for cid in candidate_ids:
                    survivor.relationships.pop(cid, None)
                    survivor.trust.pop(cid, None)
                    survivor.relationship_flags.pop(cid, None)
                    survivor.grievances.pop(cid, None)
        return newly_founded

    def tick_districts(self, settlements: list[Settlement]) -> list[tuple[Settlement, str]]:
        """Daily aggregate growth/shrink for every settlement's
        districts (`district.tick_district`) plus a small passive
        materials contribution to the settlement economy — a
        collectivized population is still real background economic
        activity, not narrative fluff (see `DISTRICT_MATERIALS_PER_
        CAPITA_PER_DAY`'s docstring for why it's deliberately small).
        Returns `(settlement, district_name)` for every district that
        dissolved (population reached 0, e.g. sustained famine) this
        call, so the caller can log it."""
        settlement_hunger = self.avg_hunger()
        dissolved: list[tuple[Settlement, str]] = []
        for settlement in settlements:
            for dist in list(settlement.districts):
                tick_district(dist, settlement_hunger)
                settlement.materials += dist.population * DISTRICT_MATERIALS_PER_CAPITA_PER_DAY
                if dist.population <= 0:
                    settlement.districts.remove(dist)
                    dissolved.append((settlement, dist.name))
        return dissolved

    def hold_festival(
        self, settlement: Settlement | None = None,
        ritual_activity: dict[tuple[int, int], float] | None = None,
    ) -> int:
        """Apply a one-time relationship boost to every currently-
        colocated pair of awake agents — the mechanical effect of a
        festival (hearthmind/llm/festival.py): the village gathers,
        bonds strengthen. A pair colocated on a standing SHRINE's tile
        gets SHRINE_FESTIVAL_BOOST_MULTIPLIER applied on top — the
        settlement's own invented culture deepening its own festival.
        Returns how many pairs were affected. See docs/DECISIONS.md,
        collective-behaviour pass and "culture-specific building
        types" pass.

        A19 "Persistent spatial memory" (roadmap Stage IV step 26):
        `ritual_activity` (optional, `World.ritual_activity` — mutated
        in place, same shape as every other terrain_evolution.py-
        mutated dict this method's caller already passes down) is the
        one real consequence this slice ships — a shrine tile that has
        hosted rituals before amplifies the boost of the NEXT one
        ("a ritual site draws ritual," scoped to a magnitude effect;
        see `world/terrain_evolution.py`'s `RITUAL_ACTIVITY_BOOST_
        SCALE`). `None` (the default) reproduces the exact pre-A19
        behavior for any caller that doesn't have a `World` in scope."""
        by_position: dict[tuple[int, int], list[Agent]] = {}
        for agent in self.agents:
            if agent.state is AgentState.AWAKE:
                by_position.setdefault((agent.x, agent.y), []).append(agent)

        affected = 0
        for (x, y), group in by_position.items():
            if len(group) < 2:
                continue
            boost = FESTIVAL_RELATIONSHIP_BOOST
            if settlement is not None:
                # Festivity-minded traditions deepen every festival —
                # culture begetting warmer culture, see
                # culture_effect_multiplier.
                boost *= culture_effect_multiplier(settlement.culture_effects, "festivity")
                shrine = settlement.at(x, y)
                if (
                    shrine is not None and shrine.kind is BuildingKind.SHRINE
                    and shrine.stage is BuildingStage.STANDING
                ):
                    boost *= SHRINE_FESTIVAL_BOOST_MULTIPLIER
                    # PRIEST (v0.87.44): a priest presiding over a shrine
                    # gathering deepens it further — occupation-based,
                    # stacks with the shrine's own flat boost.
                    if any(a.occupation == OCCUPATION_PRIEST for a in group):
                        boost *= PRIEST_RITUAL_BOOST_MULTIPLIER
                    if ritual_activity is not None:
                        prior = ritual_activity.get((x, y), 0.0)
                        boost *= 1.0 + prior * RITUAL_ACTIVITY_BOOST_SCALE
                        apply_ritual_activity((x, y), ritual_activity)
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                a.relationships[b.id] = clamp(a.relationships.get(b.id, 0.0) + boost, -1.0, 1.0)
                b.relationships[a.id] = clamp(b.relationships.get(a.id, 0.0) + boost, -1.0, 1.0)
                bump_emotion(a, EMOTION_JOY, EMOTION_FESTIVAL_JOY_BUMP)
                bump_emotion(b, EMOTION_JOY, EMOTION_FESTIVAL_JOY_BUMP)
                affected += 1
        return affected

    def spread_rumor(self, text: str, count: int, rng: random.Random) -> list[str]:
        """Integration milestone: seed a piece of news (currently only
        a caravan's outside rumor, see llm/caravan.py) into up to
        `count` living agents' own memories — the same `_remember`
        mechanism ordinary in-village events already use, so it can
        propagate further through the *existing* dialogue gossip/trust
        contagion rather than a bespoke broadcast. Returns the names of
        who heard it firsthand, for event logging.

        A16 "information-propagation-as-graph-algorithm": the FIRST
        listener is still a genuine uniform draw (the caravan's point
        of contact could be anyone) — but every listener after that is
        now chosen via `graph_algorithms.bfs_distances` from the first,
        weighted toward whoever's socially CLOSER (fewer hops) to that
        point of contact, not independently uniform over the whole
        population. Previously a caravan's news reaching four total
        strangers with no connection to each other was exactly as
        likely as it rippling outward through one person's actual
        friends — a real gap for a mechanism whose own docstring
        already claimed the news "propagates further through the
        existing... gossip contagion." Listeners still need not end up
        colocated with each other; this only biases WHO among the
        living population is more likely to be one, never requires it."""
        if not self.agents:
            return []
        first = rng.choice(self.agents)
        listeners = [first]
        remaining = min(count, len(self.agents)) - 1
        if remaining > 0:
            graph = build_relationship_graph(self.agents)
            distances = bfs_distances(graph, first.id)
            pool = [a for a in self.agents if a.id != first.id]
            for _ in range(min(remaining, len(pool))):
                weights = [
                    RUMOR_BFS_BASELINE_WEIGHT + 1.0 / (1 + distances[a.id])
                    if a.id in distances else RUMOR_BFS_BASELINE_WEIGHT
                    for a in pool
                ]
                choice = rng.choices(pool, weights=weights, k=1)[0]
                listeners.append(choice)
                pool.remove(choice)
        for agent in listeners:
            _remember(agent, text)
            _nudge_trait(agent, TRAIT_OPENNESS, TRAIT_OPENNESS_CARAVAN_NUDGE)
        if listeners:
            self.rumors_seeded_total += 1
            self.rumor_listener_exposures_total += len(listeners)
        return [a.name for a in listeners]

    def council_disposition(self, council: "Institution") -> dict:
        """Integration milestone: the living council's average traits —
        the concrete "who's on the council actually matters" mechanism
        consumed by `town_brain.compute_priority`'s tie-break and (via
        `build_prompt`) offered as context for the LLM path too. Reads
        only living members (`member_agent_ids` outlives them, same as
        `family_for`'s reasoning) — a council of the dead has no
        disposition to speak of, and this returns all-zero (a neutral
        tie-break) rather than raising when that happens."""
        members = [a for a in self.agents if a.id in council.member_agent_ids]
        if not members:
            return {"avg_ambition": 0.0, "avg_resilience": 0.0, "avg_sociability": 0.0, "size": 0}
        return {
            "avg_ambition": sum(a.traits.get(TRAIT_AMBITION, 0.0) for a in members) / len(members),
            "avg_resilience": sum(a.traits.get(TRAIT_RESILIENCE, 0.0) for a in members) / len(members),
            "avg_sociability": sum(a.traits.get(TRAIT_SOCIABILITY, 0.0) for a in members) / len(members),
            "size": len(members),
        }

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        total = len(self.agents)
        resting = sum(1 for a in self.agents if a.state is AgentState.RESTING)
        avg_hunger = sum(a.hunger for a in self.agents) / total if total else 0.0
        avg_energy = sum(a.energy for a in self.agents) / total if total else 0.0
        avg_age = sum(a.age_ticks for a in self.agents) / total if total else 0.0

        all_values = [v for a in self.agents for v in a.relationships.values()]
        avg_affinity = sum(all_values) / len(all_values) if all_values else 0.0
        # Each relationship is stored on both sides, so count pairs once.
        bonds = sum(1 for a in self.agents for v in a.relationships.values() if v >= REPRODUCTION_AFFINITY_THRESHOLD) // 2
        rivalries = sum(1 for a in self.agents for v in a.relationships.values() if v <= RIVALRY_THRESHOLD) // 2
        avg_personal_food = (
            sum(a.inventory.get("food", 0.0) for a in self.agents) / total if total else 0.0
        )
        sick_count = sum(1 for a in self.agents if a.sick_ticks > 0)
        immune_count = sum(1 for a in self.agents if a.immune_ticks > 0)
        occupation_counts: dict[str, int] = {}
        for a in self.agents:
            if a.occupation:
                occupation_counts[a.occupation] = occupation_counts.get(a.occupation, 0) + 1

        return {
            "total": total,
            "awake": total - resting,
            "resting": resting,
            "avg_hunger": round(avg_hunger, 3),
            "avg_energy": round(avg_energy, 3),
            "avg_age_ticks": round(avg_age, 1),
            "deaths_starvation": self.deaths_starvation,
            "deaths_old_age": self.deaths_old_age,
            "deaths_predator": self.deaths_predator,
            "deaths_disease": self.deaths_disease,
            "avg_affinity": round(avg_affinity, 3),
            "close_bonds": bonds,
            "rivalries": rivalries,
            "avg_personal_food": round(avg_personal_food, 3),
            "sick_count": sick_count,
            "immune_count": immune_count,
            "occupation_counts": occupation_counts,
            "carrying_capacity": round(self.last_carrying_capacity, 1),
            "avg_farming_skill": round(
                sum(a.skills.get(SKILL_FARMING, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_construction_skill": round(
                sum(a.skills.get(SKILL_CONSTRUCTION, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_medicine_skill": round(
                sum(a.skills.get(SKILL_MEDICINE, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_tools": round(
                sum(a.inventory.get("tools", 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_medicine": round(
                sum(a.inventory.get("medicine", 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_resilience": round(
                sum(a.traits.get(TRAIT_RESILIENCE, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_sociability": round(
                sum(a.traits.get(TRAIT_SOCIABILITY, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_ambition": round(
                sum(a.traits.get(TRAIT_AMBITION, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "avg_openness": round(
                sum(a.traits.get(TRAIT_OPENNESS, 0.0) for a in self.agents) / total, 3
            ) if total else 0.0,
            "rumors_seeded_total": self.rumors_seeded_total,
            "rumor_listener_exposures_total": self.rumor_listener_exposures_total,
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "agents": [a.to_dict() for a in self.agents],
            "next_id": self._next_id,
            "deaths_starvation": self.deaths_starvation,
            "deaths_old_age": self.deaths_old_age,
            "deaths_predator": self.deaths_predator,
            "deaths_disease": self.deaths_disease,
            "rumors_seeded_total": self.rumors_seeded_total,
            "rumor_listener_exposures_total": self.rumor_listener_exposures_total,
            "dialogue_cooldowns": {
                f"{a_id}:{b_id}": tick for (a_id, b_id), tick in self.dialogue_cooldowns.items()
            },
            "dialogue_topics": {
                f"{a_id}:{b_id}": list(topics) for (a_id, b_id), topics in self.dialogue_topics.items()
            },
            "dispute_cooldowns": {
                f"{a_id}:{b_id}": tick for (a_id, b_id), tick in self.dispute_cooldowns.items()
            },
            "cognition_trigger_cooldowns": dict(self.cognition_trigger_cooldowns),
            "core_agent_ids": sorted(self.core_agent_ids),
            "last_fission_tick": self.last_fission_tick,
            "voice_pair_ids": list(self.voice_pair_ids) if self.voice_pair_ids else None,
            "voice_conversation": list(self.voice_conversation),
            "voice_dialogue_last_tick": self.voice_dialogue_last_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Population":
        agents = [Agent.from_dict(a) for a in data["agents"]]
        dialogue_cooldowns = {}
        for key, tick in data.get("dialogue_cooldowns", {}).items():
            a_id, b_id = key.split(":")
            dialogue_cooldowns[(int(a_id), int(b_id))] = tick
        dialogue_topics = {}
        for key, topics in data.get("dialogue_topics", {}).items():
            a_id, b_id = key.split(":")
            dialogue_topics[(int(a_id), int(b_id))] = list(topics)
        dispute_cooldowns = {}
        for key, tick in data.get("dispute_cooldowns", {}).items():
            a_id, b_id = key.split(":")
            dispute_cooldowns[(int(a_id), int(b_id))] = tick
        cognition_trigger_cooldowns = {
            int(agent_id): tick for agent_id, tick in data.get("cognition_trigger_cooldowns", {}).items()
        }
        return cls(
            agents=agents,
            _next_id=data["next_id"],
            deaths_starvation=data.get("deaths_starvation", 0),
            deaths_old_age=data.get("deaths_old_age", 0),
            deaths_predator=data.get("deaths_predator", 0),
            deaths_disease=data.get("deaths_disease", 0),
            rumors_seeded_total=data.get("rumors_seeded_total", 0),
            rumor_listener_exposures_total=data.get("rumor_listener_exposures_total", 0),
            dialogue_cooldowns=dialogue_cooldowns,
            dialogue_topics=dialogue_topics,
            dispute_cooldowns=dispute_cooldowns,
            cognition_trigger_cooldowns=cognition_trigger_cooldowns,
            core_agent_ids=set(data.get("core_agent_ids", [])),
            last_fission_tick=data.get("last_fission_tick", -1_000_000),
            voice_pair_ids=tuple(data["voice_pair_ids"]) if data.get("voice_pair_ids") else None,
            voice_conversation=list(data.get("voice_conversation", [])),
            voice_dialogue_last_tick=data.get("voice_dialogue_last_tick", -1_000_000),
        )
