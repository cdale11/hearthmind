"""The population: the collection of agents living on a World's terrain.

Follows the same determinism discipline as terrain/weather (see
docs/DECISIONS.md, M1-2/M1-3): both initial placement and per-tick behavior
are derived from `(world_seed, tick)` via a namespaced RNG, never from
unseeded `random` calls, so a given seed always produces the same
population history.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from dataclasses import dataclass, field

from hearthmind.agents.agent import (
    CRITICAL_HUNGER_THRESHOLD,
    DIALOGUE_SENTIMENT_DELTA,
    ELDER_AGE_FRACTION,
    ELDER_RECOVERY_MULTIPLIER,
    ENERGY_DRAIN_AWAKE,
    ENERGY_RECOVERY_RESTING,
    FORAGE_AMOUNT,
    FORAGE_HUNGER_RELIEF,
    FORAGE_HUNGER_THRESHOLD,
    FORAGE_INVENTORY_SKIM,
    GATHER_TOOLS_YIELD_BONUS,
    GOSSIP_OPINION_CONTAGION,
    GOSSIP_OPINION_MAX_STEP,
    GRIEF_ENERGY_PENALTY,
    HUNGER_RATE,
    IMMUNITY_DURATION_TICKS,
    INSTITUTION_TEACHING_BONUS_MULTIPLIER,
    MATURITY_TICKS,
    MAX_AGENT_MEMORIES,
    MAX_LIFESPAN_TICKS,
    MIN_LIFESPAN_TICKS,
    MOVE_CHANCE,
    OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK,
    OUTBREAK_CROWDING_MULTIPLIER,
    OUTBREAK_ROAD_CONTACT_MULTIPLIER,
    PERSONAL_FOOD_CAPACITY,
    POPULATION_CAP,
    REPRODUCTION_AFFINITY_THRESHOLD,
    REPRODUCTION_CHANCE_PER_TICK,
    RELATIONSHIP_DECAY_PER_TICK,
    RELATIONSHIP_GAIN_PER_TICK_COLOCATED,
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
    TRAIT_GRIEF_NUDGE,
    TRAIT_MEAN_REVERSION,
    TRAIT_NOTABLE_THRESHOLD,
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
    TRAIT_VIOLENCE_NUDGE,
    TRUST_DELTA,
    TRUST_SKEPTICISM_THRESHOLD,
    WAKE_THRESHOLD,
    Agent,
    AgentGoal,
    AgentState,
)
from hearthmind.agents.names import _roman, generate_names
from hearthmind.economy.farms import (
    FARM_TOOL_MATERIALS_COST,
    HARVEST_AMOUNT,
    HARVEST_HUNGER_RELIEF,
    PLANT_CHANCE_PER_TICK,
    FarmGrid,
    FarmStage,
)
from hearthmind.settlement.buildings import (
    CAMP_TOLERANCE,
    CARRYING_CAPACITY_COORDINATION_WEIGHT,
    CARRYING_CAPACITY_ECONOMY_WEIGHT,
    CARRYING_CAPACITY_ENVIRONMENT_WEIGHT,
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
    FACTORY_INCOME_PER_TICK,
    FESTIVAL_RELATIONSHIP_BOOST,
    GRANARY_CAPACITY,
    GRANARY_DEPOSIT_PER_TICK,
    GRANARY_HUNGER_RELIEF,
    GRANARY_WELLFED_HUNGER_THRESHOLD,
    GRANARY_WITHDRAW_AMOUNT,
    HOSPITAL_CRAFT_MATERIALS_COST_PER_TICK,
    HOSPITAL_CRAFT_MEDICINE_PER_TICK,
    HOSPITAL_KILL_CHANCE_REDUCTION,
    HOSPITAL_REST_RECOVERY_MULTIPLIER,
    HUT_CAPACITY,
    INSTITUTION_LIST_MAX_STORED,
    MEDICINE_CAPACITY,
    MEDICINE_CONSUMPTION_PER_TICK,
    MEDICINE_DEATH_CHANCE_REDUCTION,
    MATERIALS_CAPACITY,
    POWER_GRID_INDUSTRY_MULTIPLIER,
    MATERIALS_COST_BY_KIND,
    MATERIALS_GATHER_PER_TICK,
    MATERIALS_PER_CONSTRUCTION_TICK,
    MAX_WORKERS,
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
)
from hearthmind.settlement.institutions import Institution, InstitutionKind
from hearthmind.settlement.vehicles import (
    AUTOMOBILE_MATERIALS_COST,
    CART_BONUS_CAP,
    CART_HAUL_BONUS_PER_CART,
    CART_MATERIALS_COST,
    CART_USE_DECAY,
    MOUNT_MATERIALS_COST,
    PERSONAL_VEHICLE_KINDS,
    PERSONAL_VEHICLE_SPEED_MULTIPLIER,
    PERSONAL_VEHICLE_USE_DECAY,
    VEHICLE_CHANCE_PER_TICK,
    VEHICLE_CONSTRUCTION_WORK_PER_TICK,
    VEHICLE_MAX_WORKERS,
    VEHICLE_REPAIR_THRESHOLD,
    VEHICLE_REPAIR_WORK_PER_TICK,
    Vehicle,
    VehicleKind,
    VehicleStage,
)
from hearthmind.world.resources import (
    FISH_HUNGER_RELIEF_MULTIPLIER,
    ORE_BIOMES,
    ResourceGrid,
    ResourceKind,
    is_adjacent_to_water,
)
from hearthmind.world.roads import ROAD_SPEED_MULTIPLIER, RoadNetwork, road_condition_multiplier
from hearthmind.world.terrain import Biome, Tile
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

WALKABLE_BIOMES = frozenset({Biome.GRASSLAND, Biome.FOREST, Biome.HILLS, Biome.BEACH})
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
membership shape for the second kind."""

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

POPULATION_CRITICAL_THRESHOLD = 4
"""Below this many living inhabitants (but above 0 — total extinction is
a legitimate, permanent settlement-collapse outcome, see
_maybe_welcome_migrant, not a bug to route around), a population is one
incompatible or unlucky pair away from a demographic dead end even
though people remain: reproduction needs two colocated, mature, healthy
agents whose mutual affinity has crossed REPRODUCTION_AFFINITY_THRESHOLD
— with only 1-3 survivors left, there may be nobody eligible to pair
with at all."""

MIGRANT_CHECK_CHANCE_PER_TICK = 0.003
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

DISPUTE_COOLDOWN_TICKS = 3000
"""Minimum ticks between two dispute-resolution moments for the same
pair (~31 sim-days at default pacing) — a resolution is a rare, notable
event, not a recurring mechanic; an outcome needs time to settle (or
fester again) before the question can reopen."""

DISPUTE_RECONCILE_RELATIONSHIP = 0.1
DISPUTE_TRUCE_RELATIONSHIP = -0.1
DISPUTE_FEUD_DEEPEN = -0.2
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

MAX_DIALOGUES_PER_TICK = 3
"""Caps how many LLM-authored dialogue exchanges are scheduled in a
single tick regardless of how many colocated pairs qualify — keeps LLM
load bounded as population/clustering grows, same rationale as
`llm_max_concurrent`. See Population.due_for_dialogue, docs/DECISIONS.md,
E2."""


def _namespaced_rng(seed: int, tick: int, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{namespace}:{tick}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _tech_factor(settlement: Settlement) -> float:
    """Multiplicative bonus from established inventions — see
    TECH_BONUS_PER_LEVEL, docs/DECISIONS.md, E3."""
    return 1.0 + TECH_BONUS_PER_LEVEL * settlement.tech_level


def _haul_factor(settlement: Settlement) -> float:
    """Multiplicative bonus from ready carts on gathered-material yield —
    see CART_HAUL_BONUS_PER_CART/CART_BONUS_CAP, docs/DECISIONS.md,
    vehicles pass."""
    ready_carts = sum(1 for v in settlement.vehicles if v.kind is VehicleKind.CART and v.stage is VehicleStage.READY)
    return 1.0 + CART_HAUL_BONUS_PER_CART * min(ready_carts, CART_BONUS_CAP)


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


def _remember(agent: Agent, text: str) -> None:
    """Append to an agent's short personal log, capped at
    MAX_AGENT_MEMORIES (oldest drops first). See docs/DECISIONS.md,
    relationship-memory pass."""
    agent.memories.append(text)
    if len(agent.memories) > MAX_AGENT_MEMORIES:
        agent.memories.pop(0)


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
    agent.traits[trait] = max(-1.0, min(1.0, agent.traits.get(trait, 0.0) + delta))


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
    families = [i for i in settlement.institutions if i.kind is InstitutionKind.FAMILY]
    if len(families) <= INSTITUTION_LIST_MAX_STORED:
        return
    extinct = sorted(
        (i for i in families if i.member_agent_ids.isdisjoint(living_ids)),
        key=lambda i: i.founding_tick,
    )
    excess = len(families) - INSTITUTION_LIST_MAX_STORED
    to_remove = {inst.id for inst in extinct[:excess]}
    if to_remove:
        settlement.institutions = [i for i in settlement.institutions if i.id not in to_remove]


def _is_walkable(terrain: list[list[Tile]], x: int, y: int) -> bool:
    return terrain[y][x].biome in WALKABLE_BIOMES


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
            agents.append(Agent(id=i, name=names[i], x=x, y=y, max_age_ticks=max_age))
        return cls(agents=agents, _next_id=count)

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
            s.id: CAMP_TOLERANCE + HUT_CAPACITY * sum(
                1 for b in s.buildings
                if b.kind is BuildingKind.HUT and b.stage is BuildingStage.STANDING
            )
            for s in settlements
        }
        crowded_by_id = {s.id: members_count[s.id] > housing_by_id[s.id] for s in settlements}
        crowded = any(crowded_by_id.values())
        farm_positions = self.ready_farm_positions(farms)
        granary_positions_by_id = {s.id: self.stocked_granary_positions(s) for s in settlements}
        work_positions_by_id = {
            s.id: self.damaged_building_positions(s) + self.under_construction_positions(s)
            for s in settlements
        }
        self.last_triggered_agent_ids = set()
        self.last_written_records = []
        for agent in self.agents:
            home = home_of(agent)
            agent.age_ticks += 1
            self._update_needs(agent, weather_harsh, settlements, night_factor, crowded_by_id[home.id])
            critically_hungry = agent.hunger >= CRITICAL_HUNGER_THRESHOLD
            if critically_hungry:
                # A hunger emergency deserves the LLM's actual reasoning
                # (a real goal + rationale), not just the movement-layer
                # override _dispatch_movement already forces regardless
                # of assigned goal — see due_for_triggered_cognition.
                self.last_triggered_agent_ids.add(agent.id)
            if critically_hungry and agent.state is AgentState.RESTING:
                agent.state = AgentState.AWAKE  # emergency wake: starving beats sleeping
            self._maybe_forage(agent, resources, farms, settlements, wildlife)  # can eat while resting, not just awake
            if self._maybe_gather(agent, terrain, home, resources):
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
                self._dispatch_movement(
                    agent, terrain, rng, resources, farms, home, wildlife, roads,
                    predator_tiles, position_snapshot, critically_hungry, weather,
                    rival_tiles=rival_tiles_by_agent.get(agent.id),
                    food_positions=(farm_positions, granary_positions_by_id[home.id]),
                    work_positions=work_positions_by_id[home.id],
                )
            by_position.setdefault((agent.x, agent.y), []).append(agent)

        self._update_roads(by_position, settlements, farms, roads)
        self._update_relationships(by_position)
        self._maybe_teach_skills(by_position, rng, settlements)
        if month_end:
            self._tick_traits(rng)
        hospital_settlement_ids = {sid for sid, has in has_hospital_by_id.items() if has}
        disease_events, died_of_disease = self._tick_disease(
            self.agents, by_position, hospital_settlement_ids, primary.temperament, rng,
        )
        life_events.extend(disease_events)
        life_events.extend(self._maybe_outbreak(rng, crowded, roads))
        # Building-driven subsystems run once per settlement over the
        # global colocation map: each settlement's own structures get
        # worked/stocked/crafted-at by whoever is physically present —
        # a visiting neighbor genuinely can help raise a wall or study
        # at the other village's school.
        for stl in settlements:
            life_events.extend(self._advance_construction(by_position, stl))
            life_events.extend(self._maybe_repair(by_position, stl))
            self._maybe_stock_granaries(by_position, stl)
            self._maybe_run_workshops(by_position, stl)
            self._maybe_craft_tools(by_position, stl)
            self._maybe_craft_medicine(by_position, stl)
            self._maybe_run_factories(by_position, stl)
            self._maybe_run_schools(by_position, stl)
            life_events.extend(self._maybe_upgrade_university(by_position, stl, rng))
            life_events.extend(self._advance_vehicle_construction(by_position, stl))
            self._maybe_repair_vehicles(by_position, stl)
            self._maybe_assign_mounts(by_position, stl)
            if any_gather_occurred:
                self._wear_carts(stl)
            life_events.extend(self._maybe_start_vehicle(by_position, stl, farms, rng))
        self._maybe_trade_food(by_position, rng)
        self._maybe_trade_tools(by_position, rng)
        self._maybe_trade_medicine(by_position, rng)
        life_events.extend(
            self._maybe_start_construction(by_position, settlements, farms, rng, roads, resources, terrain)
        )
        life_events.extend(self._maybe_plant(by_position, farms, settlements, terrain, rng))
        established_roads = roads.summary()["established_roads"]
        capacity_by_id = {
            s.id: self.carrying_capacity(
                s, housing_by_id[s.id], weather_harsh, bool(predator_tiles),
                established_roads=established_roads,
                members=[a for a in self.agents if home_of(a).id == s.id],
            )
            for s in settlements
        }
        self.last_carrying_capacity = sum(capacity_by_id.values())
        life_events.extend(
            self._maybe_reproduce(by_position, rng, capacity_by_id, settlements, tick)
        )
        life_events.extend(self._apply_deaths(killed_by_predator, settlements, died_of_disease, tick=tick))
        life_events.extend(self._maybe_welcome_migrant(rng, primary))
        for stl in settlements:
            members = [a for a in self.agents if home_of(a).id == stl.id]
            life_events.extend(self._maybe_form_council(stl, tick, members))
            life_events.extend(self._maybe_refresh_council(stl, members))
            life_events.extend(self._maybe_form_guild(stl, tick, members))
            life_events.extend(self._maybe_refresh_guild(stl, members))
        return life_events

    @staticmethod
    def _update_needs(
        agent: Agent, weather_harsh: bool = False, settlements: list[Settlement] | None = None,
        night_factor: float = 0.0, crowded: bool = False,
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
            sheltered = (
                SHELTER_NEGATES_WEATHER
                and building is not None and building.stage is BuildingStage.STANDING
            )
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
            if (
                building is not None and building.kind is BuildingKind.HOSPITAL
                and building.stage is BuildingStage.STANDING
            ):
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
        kill_chance = PREDATOR_KILL_CHANCE_ON_ATTACK
        if has_hospital:
            kill_chance *= (1.0 - HOSPITAL_KILL_CHANCE_REDUCTION)
        kill_chance = max(0.0, kill_chance * (1.0 - temperament * TEMPERAMENT_KILL_CHANCE_INFLUENCE))
        # Integration milestone: the agent's own resilience gets a say
        # too, alongside the settlement-wide temperament nudge — see
        # TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE.
        resilience = agent.traits.get(TRAIT_RESILIENCE, 0.0)
        kill_chance = max(0.0, kill_chance * (1.0 - resilience * TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE))
        if rng.random() < kill_chance:
            return (("death", f"{agent.name} was killed by predators."), True)
        agent.energy = max(0.0, agent.energy - PREDATOR_ATTACK_ENERGY_DRAIN)
        agent.hunger = min(1.0, agent.hunger + PREDATOR_ATTACK_HUNGER_INCREASE)
        return (("predator_attack", f"{agent.name} was attacked by predators and barely escaped."), False)

    def _maybe_outbreak(
        self, rng: random.Random, crowded: bool, roads: RoadNetwork | None = None,
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
        `_tick_disease` already exempts from person-to-person spread."""
        healthy = [a for a in self.agents if a.sick_ticks == 0 and a.immune_ticks == 0]
        if not healthy:
            return []
        chance = OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK * len(self.agents)
        if crowded:
            chance *= OUTBREAK_CROWDING_MULTIPLIER
        if roads is not None and self.agents:
            on_road_fraction = sum(1 for a in self.agents if roads.is_road(a.x, a.y)) / len(self.agents)
            chance *= 1.0 + on_road_fraction * OUTBREAK_ROAD_CONTACT_MULTIPLIER
        if rng.random() >= chance:
            return []
        index_case = rng.choice(healthy)
        index_case.sick_ticks = 1
        return [("illness", f"{index_case.name} has fallen ill.")]

    @staticmethod
    def _tick_disease(
        agents: list[Agent], by_position: dict[tuple[int, int], list[Agent]],
        hospital_settlement_ids: set[int], temperament: float, rng: random.Random,
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
            if rng.random() < agent_death_chance:
                died_of_disease.add(agent.id)
                continue
            if agent.sick_ticks >= SICKNESS_DURATION_TICKS:
                agent.sick_ticks = 0
                agent.immune_ticks = IMMUNITY_DURATION_TICKS
                life_events.append(("recovery", f"{agent.name} has recovered from illness."))
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
                    if rng.random() < SICKNESS_TRANSMISSION_CHANCE_PER_TICK:
                        target.sick_ticks = 1
                        life_events.append(("illness", f"{target.name} caught the illness from {carrier.name}."))
                        break
        return life_events, died_of_disease

    @staticmethod
    def _maybe_forage(
        agent: Agent, resources: ResourceGrid, farms: FarmGrid, settlements: list[Settlement],
        wildlife: WildlifeGrid,
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
            consumed = farms.harvest(agent.x, agent.y, HARVEST_AMOUNT)
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
                return

        # A stocked granary is preferred over wild foraging too — a
        # deliberate community buffer, second only to a fresh farm.
        granary, granary_owner = None, home
        for stl in settlements:
            candidate = stl.at(agent.x, agent.y)
            if candidate is not None:
                granary, granary_owner = candidate, stl
                break
        if (
            granary is not None and granary.kind is BuildingKind.GRANARY
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
            relief = FORAGE_HUNGER_RELIEF * (consumed / FORAGE_AMOUNT)
            if node.kind is ResourceKind.FISH:
                relief *= FISH_HUNGER_RELIEF_MULTIPLIER
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
        it's a foraging spot, not a mine."""
        biome = terrain[agent.y][agent.x].biome
        if agent.goal is not AgentGoal.GATHER or agent.state is not AgentState.AWAKE:
            return False
        if biome not in MATERIAL_BIOMES:
            return False

        gathered = MATERIALS_GATHER_PER_TICK
        if biome in ORE_BIOMES:
            node = resources.get(agent.x, agent.y)
            if node is None or node.kind is not ResourceKind.ORE or node.amount <= 0:
                return False
            gathered = min(node.amount, MATERIALS_GATHER_PER_TICK)
            node.amount -= gathered

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
            farms.plant(x, y, tooled=tooled)
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

        # A long-range journey (today: a fission party walking to its
        # new settlement's site) overrides goal-directed movement — but
        # never a hunger emergency: a starving traveler detours for food
        # first, the same override precedence everything else follows.
        # See Agent.travel_target.
        if agent.travel_target is not None and not critically_hungry:
            if (agent.x, agent.y) == agent.travel_target:
                agent.travel_target = None
            else:
                journey_mount = _agent_mount(settlement, agent.id)
                moved = cls._step_toward(agent, agent.travel_target, terrain, predator_tiles)
                if moved and journey_mount is not None and agent.travel_target is not None:
                    if cls._step_toward(agent, agent.travel_target, terrain, predator_tiles):
                        journey_mount.condition = max(
                            0.0, journey_mount.condition - PERSONAL_VEHICLE_USE_DECAY[journey_mount.kind]
                        )
                if agent.travel_target is not None and not moved:
                    # Greedy step blocked (concave water/mountain pocket
                    # — greedy would oscillate forever): take one step
                    # of a real BFS path instead. Unreachable target =
                    # the journey is abandoned where they stand.
                    step = cls._bfs_step(terrain, (agent.x, agent.y), agent.travel_target)
                    if step is None:
                        agent.travel_target = None
                    else:
                        agent.x, agent.y = step
                        moved = True
                if agent.travel_target is not None and (agent.x, agent.y) == agent.travel_target:
                    agent.travel_target = None
                if moved:
                    return

        effective_goal = AgentGoal.FORAGE if critically_hungry else agent.goal
        target = None
        if effective_goal is AgentGoal.FORAGE:
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
            target = cls._nearest_other_agent(agent, position_snapshot)
        elif effective_goal is AgentGoal.GATHER:
            target = cls._nearest_material_tile(agent, terrain)
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

        mount = _agent_mount(settlement, agent.id)
        if target is not None and cls._step_toward(agent, target, terrain, predator_tiles):
            if mount is not None and cls._step_toward(agent, target, terrain, predator_tiles):
                # A ready personal vehicle (mount or the era-gated
                # automobile upgrade) covers ground twice as fast toward
                # a deliberate target — the goal-directed equivalent of
                # PERSONAL_VEHICLE_SPEED_MULTIPLIER's boost to the
                # random walk below.
                mount.condition = max(0.0, mount.condition - PERSONAL_VEHICLE_USE_DECAY[mount.kind])
            return
        cls._maybe_move(
            agent, terrain, rng, roads, predator_tiles,
            speed_multiplier=PERSONAL_VEHICLE_SPEED_MULTIPLIER[mount.kind] if mount is not None else 1.0,
            weather=weather,
        )
        if mount is not None:
            mount.condition = max(0.0, mount.condition - PERSONAL_VEHICLE_USE_DECAY[mount.kind])

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
        """Worth-the-walk granaries: stocked, or empty but the settlement
        can afford emergency rations (D10) — a built granary is a known
        community landmark (D7), so no distance cap when targeted."""
        can_buy_rations = settlement.currency >= CURRENCY_EMERGENCY_RATION_COST * settlement.market_price("food")
        return [
            (b.x, b.y) for b in settlement.buildings
            if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
            and (b.stored_food > 0 or can_buy_rations)
        ]

    @staticmethod
    def damaged_building_positions(settlement: Settlement) -> list[tuple[int, int]]:
        """Standing buildings at or below REPAIR_THRESHOLD — the WANDER-
        goal repair attractor (v0.43.2 follow-up, see _dispatch_movement).
        No distance cap when targeted, same rationale as farm/granary
        positions: a settlement's own buildings are known landmarks to
        its residents, not something they have to stumble across."""
        return [
            (b.x, b.y) for b in settlement.buildings
            if b.stage is BuildingStage.STANDING and b.condition < REPAIR_THRESHOLD
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
        behavior. Root cause of the "NPCs never seem to fish" report."""
        best_food: tuple[int, int] | None = None
        best_food_dist: int | None = None
        best_fish: tuple[int, int] | None = None
        best_fish_dist: int | None = None
        for (x, y), node in resources.nodes.items():
            if node.kind not in (ResourceKind.FOOD, ResourceKind.FISH) or node.amount <= 0:
                continue
            if max(abs(x - agent.x), abs(y - agent.y)) > FORAGE_SEARCH_RADIUS:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if node.kind is ResourceKind.FISH:
                if best_fish_dist is None or dist < best_fish_dist:
                    best_fish, best_fish_dist = (x, y), dist
            else:
                if best_food_dist is None or dist < best_food_dist:
                    best_food, best_food_dist = (x, y), dist
        return best_fish if best_fish is not None else best_food

    @staticmethod
    def _nearest_material_tile(agent: Agent, terrain: list[list[Tile]]) -> tuple[int, int] | None:
        """Scans a bounded box (no discrete registry like resources/farms
        exist for terrain biomes) within GATHER_SEARCH_RADIUS. See D8."""
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

    @staticmethod
    def _nearest_other_agent(
        agent: Agent, position_snapshot: list[tuple[int, int, int]]
    ) -> tuple[int, int] | None:
        """No distance cap, unlike _nearest_resource: an agent actively
        seeking company is assumed to know roughly where the (small)
        population's other members are, not just what's locally visible —
        see docs/DECISIONS.md, D4."""
        best: tuple[int, int] | None = None
        best_dist: int | None = None
        for other_id, x, y in position_snapshot:
            if other_id == agent.id:
                continue
            dist = abs(x - agent.x) + abs(y - agent.y)
            if best_dist is None or dist < best_dist:
                best, best_dist = (x, y), dist
        return best

    @staticmethod
    def _step_toward(
        agent: Agent, target: tuple[int, int], terrain: list[list[Tile]],
        predator_tiles: set[tuple[int, int]] = frozenset(),
    ) -> bool:
        """Take one greedy step toward `target`. Returns False (and leaves
        `agent` unmoved) if already there or if both preferred directions
        are blocked, so the caller can fall back to wandering.

        Avoids stepping onto a live predator's tile when an alternative
        exists — an agent still walks into danger if that's the only way
        forward (e.g. the target itself is past a predator), it just
        doesn't prefer to. See docs/DECISIONS.md, danger pass."""
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
            if not (0 <= nx < width and 0 <= ny < height and _is_walkable(terrain, nx, ny)):
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
        node_cap: int = 4096,
    ) -> tuple[int, int] | None:
        """First step of a real shortest path from `start` toward
        `target` over walkable tiles — used ONLY when a travel_target
        journey's greedy step is blocked (a concave water/mountain
        pocket makes greedy stepping oscillate forever; a fission party
        must actually arrive). Deliberately not used for routine
        FORAGE/GATHER targeting: journeys are rare (one party per
        FISSION_COOLDOWN_TICKS) so a full-map BFS per blocked traveler
        per tick is nothing, but running it for every goal-seeking
        agent every tick would be a real cost for no observed problem.
        Returns None when target is unreachable within `node_cap`
        expansions (an island) — the caller then abandons the
        journey."""
        if start == target:
            return None
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        from collections import deque as _deque
        first_step: dict[tuple[int, int], tuple[int, int]] = {}
        queue = _deque([start])
        seen = {start}
        expanded = 0
        while queue and expanded < node_cap:
            cx, cy = queue.popleft()
            expanded += 1
            for dx, dy in _NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                    continue
                if not _is_walkable(terrain, nx, ny):
                    continue
                seen.add((nx, ny))
                first_step[(nx, ny)] = first_step.get((cx, cy), (nx, ny))
                if (nx, ny) == target:
                    return first_step[(nx, ny)]
                queue.append((nx, ny))
        return None

    @staticmethod
    def _reachable_tiles(terrain: list[list[Tile]], origin: tuple[int, int]) -> set[tuple[int, int]]:
        """The walkable connected component containing `origin` — one
        flood fill, used by the engine's fission-site chooser so a
        founding party is never pointed at land it cannot walk to (the
        map's rivers/lakes genuinely disconnect some regions)."""
        from collections import deque as _deque
        seen = {origin}
        queue = _deque([origin])
        height = len(terrain)
        width = len(terrain[0]) if height else 0
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in _NEIGHBOR_OFFSETS:
                nx, ny = cx + dx, cy + dy
                if (
                    0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                    and _is_walkable(terrain, nx, ny)
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
            # "LLM-as-brain batch."
            road_multiplier = road_condition_multiplier(weather) if weather is not None else ROAD_SPEED_MULTIPLIER
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
        if candidates:
            agent.x, agent.y = rng.choice(candidates)

    @staticmethod
    def _update_roads(
        by_position: dict[tuple[int, int], list[Agent]], settlements: list[Settlement],
        farms: FarmGrid, roads: RoadNetwork,
    ) -> None:
        """Tiles with at least one awake agent present, excluding
        building/farm tiles (paths form between things, not on top of
        them) — see docs/DECISIONS.md, C5."""
        occupied = {
            (x, y) for (x, y), group in by_position.items()
            if any(a.state is AgentState.AWAKE for a in group)
            and all(s.at(x, y) is None for s in settlements) and farms.get(x, y) is None
        }
        roads.tick(occupied)

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
                value = agent.relationships[other_id]
                if value > 0.0:
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
                current = agent.traits.get(trait, 0.0)
                step = rng.uniform(-TRAIT_STEP_MAX, TRAIT_STEP_MAX)
                agent.traits[trait] = max(-1.0, min(1.0, current * TRAIT_MEAN_REVERSION + step))

    def carrying_capacity(
        self, settlement: Settlement, housing_capacity: int, weather_harsh: bool, predator_pressure: bool,
        established_roads: int = 0, members: "list[Agent] | None" = None,
    ) -> float:
        """Dynamic carrying capacity (H1, docs/ROADMAP.md Phase H):
        composes housing (the base), economy, security, and labor/
        environment pressure into one number that moves with the
        settlement's actual situation, the same way food already gates
        reproduction via the surplus check below — rather than the flat
        `POPULATION_CAP` scalar being the only real constraint. Called
        once per tick from `tick()`; the result also drives
        `_maybe_reproduce`'s gate and is exposed via `summary()`.
        Integration milestone: also reads institutional coordination
        (a sitting council), aggregate population skill (knowledge), and
        road infrastructure — previously this function only ever read
        housing/economy/security/labor/weather, leaving three real,
        effortful systems with no way to expand what a settlement can
        actually support."""
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

        sick_fraction = (sum(1 for a in members if a.sick_ticks > 0) / total) if total else 0.0
        security_term = -(
            sick_fraction * 2.0 + (0.3 if predator_pressure else 0.0)
        ) * CARRYING_CAPACITY_SECURITY_WEIGHT

        working_age = sum(1 for a in members if self._is_mature(a) and self._is_healthy(a))
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
            1.0 + economy_term + security_term + labor_term + environment_term
            + coordination_term + knowledge_term + infrastructure_term
        )
        multiplier = max(CARRYING_CAPACITY_MIN_MULTIPLIER, min(CARRYING_CAPACITY_MAX_MULTIPLIER, multiplier))
        return min(float(POPULATION_CAP), housing_capacity * multiplier)

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
        for member in self.agents:
            home_counts[member.settlement_id if member.settlement_id in settlements_by_id else primary.id] += 1

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
                if a.relationships.get(b.id, 0.0) < REPRODUCTION_AFFINITY_THRESHOLD:
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
                if rng.random() >= REPRODUCTION_CHANCE_PER_TICK:
                    continue

                child_name = self._unique_name(rng, extra_taken=newborn_names)
                newborn_names.add(child_name)
                child = Agent(
                    id=self._next_id,
                    name=child_name,
                    x=a.x,
                    y=a.y,
                    max_age_ticks=rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS),
                    parents=(a.id, b.id),
                    settlement_id=home.id,
                )
                self._next_id += 1
                newborns.append(child)
                home_counts[home.id] += 1
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
                family_event = self._extend_family(home, tick, a.id, b.id, child.id, a.name, b.name)
                if family_event is not None:
                    life_events.append(family_event)
                    _prune_extinct_families(home, {a.id for a in self.agents})

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

    def _maybe_form_council(
        self, settlement: Settlement, tick: int, members: "list[Agent] | None" = None,
    ) -> list[tuple[str, str]]:
        """H3 extension (docs/ROADMAP.md "Phase H"): a second
        institution kind, formed the first tick a named settlement's
        population reaches COUNCIL_FORMATION_POPULATION_THRESHOLD —
        membership is the COUNCIL_SIZE oldest living agents at that
        moment (elders, by fraction of their own lifespan lived), fixed
        at formation and never refreshed, same "outlives its founding
        moment" shape FAMILY institutions already use. Still fully
        deterministic/automatic — no agent goal or LLM decision founds
        one, matching how buildings/families are founded in this
        project. A no-op every tick after the one where it fires."""
        members = self.agents if members is None else members
        if not settlement.name or len(members) < COUNCIL_FORMATION_POPULATION_THRESHOLD:
            return []
        if any(inst.kind is InstitutionKind.COUNCIL for inst in settlement.institutions):
            return []
        elders = sorted(
            members,
            key=lambda a: (a.age_ticks / a.max_age_ticks) if a.max_age_ticks else 0.0,
            reverse=True,
        )[:COUNCIL_SIZE]
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
        self, settlement: Settlement, members: "list[Agent] | None" = None,
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
        COUNCIL_SIZE from the next-eldest non-member agent whenever a
        seat opens, same elder-selection rule `_maybe_form_council`
        already uses. A no-op most ticks (only fires the tick after a
        sitting member's death, and only while enough living population
        remains to fill the seat)."""
        members = self.agents if members is None else members
        council = next((i for i in settlement.institutions if i.kind is InstitutionKind.COUNCIL), None)
        if council is None:
            return []
        living_members = [a for a in members if a.id in council.member_agent_ids]
        seats_open = COUNCIL_SIZE - len(living_members)
        if seats_open <= 0:
            return []
        candidates = sorted(
            (a for a in members if a.id not in council.member_agent_ids),
            key=lambda a: (a.age_ticks / a.max_age_ticks) if a.max_age_ticks else 0.0,
            reverse=True,
        )[:seats_open]
        if not candidates:
            return []
        council.member_agent_ids.update(a.id for a in candidates)
        names = ", ".join(a.name for a in candidates)
        return [("council_seat_filled", f"{names} joined the council of elders, filling an empty seat.")]

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

    def _maybe_welcome_migrant(self, rng: random.Random, settlement: Settlement) -> list[tuple[str, str]]:
        """The population equivalent of wildlife's `_maybe_recolonize` —
        a settlement crashed down to a handful of survivors (predation,
        starvation, disaster, or simply old age outpacing sparse births)
        can otherwise sit at 1-3 people forever with no path back, since
        reproduction needs a compatible, colocated, mature, healthy pair.
        A rare newcomer arriving at the settlement (or, if unnamed, near
        an existing survivor) breaks that dead end. Deliberately does
        NOT fire at 0 population — a fully extinct settlement is a
        legitimate, permanent, readable-from-the-landscape ending (see
        CLAUDE.md's "settlements expand or collapse"), not something to
        auto-revive."""
        count = len(self.agents)
        if count == 0 or count >= POPULATION_CRITICAL_THRESHOLD:
            return []
        chance = MIGRANT_CHECK_CHANCE_PER_TICK * (1.0 + max(0.0, settlement.temperament) * MIGRANT_TEMPERAMENT_INFLUENCE)
        # H6 v4: the surviving remnant's own average openness nudges how
        # readily it welcomes a stranger — see TRAIT_OPENNESS_MIGRANT_
        # WELCOME_INFLUENCE.
        avg_openness = sum(a.traits.get(TRAIT_OPENNESS, 0.0) for a in self.agents) / count
        chance *= 1.0 + avg_openness * TRAIT_OPENNESS_MIGRANT_WELCOME_INFLUENCE
        chance = max(0.0, chance)
        if rng.random() >= chance:
            return []
        if settlement.buildings:
            building = settlement.buildings[rng.randrange(len(settlement.buildings))]
            x, y = building.x, building.y
        else:
            anchor = self.agents[rng.randrange(count)]
            x, y = anchor.x, anchor.y
        name = self._unique_name(rng)
        migrant = Agent(
            id=self._next_id, name=name, x=x, y=y, age_ticks=MATURITY_TICKS,
            max_age_ticks=rng.randint(MIN_LIFESPAN_TICKS, MAX_LIFESPAN_TICKS),
        )
        self._next_id += 1
        self.agents.append(migrant)
        destination = settlement.name or "the dwindling settlement"
        _remember(migrant, f"I came to {destination} looking for a new start.")
        return [("migrant_arrived", f"{name} arrived at {destination}, drawn by word of its need.")]

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
        by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement
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
            work = (
                CONSTRUCTION_WORK_PER_TICK * len(workers) * _tech_factor(settlement)
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
            workers = sum(
                1 for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE
            )
            if workers == 0:
                continue
            repair = REPAIR_WORK_PER_TICK * min(workers, MAX_WORKERS) * _tech_factor(settlement)
            building.condition = min(1.0, building.condition + repair)
        return []  # repair progress isn't eventful enough on its own to log per-tick

    @classmethod
    def _maybe_start_construction(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlements: list[Settlement],
        farms: FarmGrid, rng: random.Random, roads: RoadNetwork | None = None,
        resources: ResourceGrid | None = None, terrain: list[list[Tile]] | None = None,
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
            bx, by = cls._choose_build_site(x, y, terrain, settlements, farms, roads, resources)
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
    ) -> tuple[int, int]:
        """The best buildable tile within BUILD_SITE_SEARCH_RADIUS of the
        founders at (x, y) — scored by road/resource/water adjacency
        minus a per-step distance penalty (see the three BUILD_SITE_*
        constants). Falls back to (x, y) itself when terrain isn't
        provided (legacy callers) or nothing else scores higher. Ties
        keep the earliest-scanned tile, which the scan order below makes
        the one nearest the founders."""
        if terrain is None:
            return (x, y)
        height = len(terrain)
        width = len(terrain[0]) if height else 0
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
                    if not _is_walkable(terrain, cx, cy):
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
                    a.relationships[b.id] = max(-1.0, min(1.0, a.relationships.get(b.id, 0.0) + TRADE_RELATIONSHIP_BOOST))
                    _nudge_trait(a, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
                _remember(recipient, f"{giver.name} shared food with me.")
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
        wasting it (D10)."""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.GRANARY or building.stage is not BuildingStage.STANDING:
                continue
            contributors = sum(
                1 for a in by_position.get((building.x, building.y), [])
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
    def _maybe_run_workshops(by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement) -> None:
        """Staffed presence at a standing workshop generates currency
        directly — a business, distinct from D10's overflow-selling. See
        WORKSHOP_INCOME_PER_TICK, docs/DECISIONS.md, "LLM-as-brain batch.\""""
        for building in settlement.buildings:
            if building.kind is not BuildingKind.WORKSHOP or building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(
                1 for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = WORKSHOP_INCOME_PER_TICK * staff * _tech_factor(settlement)
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
                worker.inventory["tools"] = min(
                    TOOLS_CAPACITY, worker.inventory.get("tools", 0.0) + WORKSHOP_CRAFT_TOOLS_PER_TICK
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
                    a.relationships[b.id] = max(-1.0, min(1.0, a.relationships.get(b.id, 0.0) + TRADE_RELATIONSHIP_BOOST))
                    _nudge_trait(a, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
                _remember(recipient, f"{giver.name} shared tools with me.")
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
                    a.relationships[b.id] = max(-1.0, min(1.0, a.relationships.get(b.id, 0.0) + TRADE_RELATIONSHIP_BOOST))
                    _nudge_trait(a, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
                _remember(recipient, f"{giver.name} shared medicine with me.")
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
                1 for a in by_position.get((building.x, building.y), [])
                if a.state is AgentState.AWAKE and a.hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD
            )
            if staff == 0:
                continue
            income = FACTORY_INCOME_PER_TICK * staff * _tech_factor(settlement)
            if settlement.has_power_plant():
                income *= POWER_GRID_INDUSTRY_MULTIPLIER
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
            if building.kind not in (BuildingKind.SCHOOL, BuildingKind.UNIVERSITY):
                continue
            if building.stage is not BuildingStage.STANDING:
                continue
            staff = sum(1 for a in by_position.get((building.x, building.y), []) if a.state is AgentState.AWAKE)
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
            work = VEHICLE_CONSTRUCTION_WORK_PER_TICK * min(workers, VEHICLE_MAX_WORKERS) * _tech_factor(settlement)
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
            repair = VEHICLE_REPAIR_WORK_PER_TICK * min(workers, VEHICLE_MAX_WORKERS) * _tech_factor(settlement)
            vehicle.condition = min(1.0, vehicle.condition + repair)
            if vehicle.stage is VehicleStage.BROKEN and vehicle.condition >= VEHICLE_REPAIR_THRESHOLD:
                vehicle.stage = VehicleStage.READY

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

    @classmethod
    def _maybe_start_vehicle(
        cls, by_position: dict[tuple[int, int], list[Agent]], settlement: Settlement,
        farms: FarmGrid, rng: random.Random,
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
            # "vehicle era-progression follow-up."
            roll = rng.random()
            if settlement.era in ERA_UNLOCKS_AUTOMOBILE:
                kind = VehicleKind.CART if roll < 0.4 else VehicleKind.MOUNT if roll < 0.7 else VehicleKind.AUTOMOBILE
            else:
                kind = VehicleKind.MOUNT if roll < 0.5 else VehicleKind.CART
            cost = {
                VehicleKind.MOUNT: MOUNT_MATERIALS_COST, VehicleKind.CART: CART_MATERIALS_COST,
                VehicleKind.AUTOMOBILE: AUTOMOBILE_MATERIALS_COST,
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

    def _apply_inheritance(
        self, agent: Agent, settlement: Settlement, dying_ids: set[int],
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

        if not inherited:
            return []
        _remember(heir, f"I inherited from {agent.name}: {', '.join(inherited)}.")
        return [("inheritance", f"{heir.name} inherited from {agent.name}: {', '.join(inherited)}.")]

    def _apply_deaths(
        self, killed_by_predator: set[int] = frozenset(), settlements: list[Settlement] | None = None,
        died_of_disease: set[int] = frozenset(), tick: int = 0,
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
                    _remember(other, f"I keep the letter {agent.name} left behind.")
                    record_kept = True
                if is_child or is_parent:
                    # Family grief lands regardless of the numeric
                    # relationship value — a newborn's affinity with its
                    # own parent may not have accrued much yet, but
                    # losing a parent (or a child) is memorable
                    # regardless. See docs/DECISIONS.md, family-memory
                    # pass.
                    label = "parent" if is_child else "child"
                    _remember(other, f"My {label}, {agent.name}, died.")
                    other.energy = max(0.0, other.energy - grief_penalty_for(other))
                    self.last_triggered_agent_ids.add(other.id)
                    _nudge_trait(other, TRAIT_RESILIENCE, TRAIT_GRIEF_NUDGE)
                elif other.relationships.get(agent.id, 0.0) >= REPRODUCTION_AFFINITY_THRESHOLD:
                    _remember(other, f"{agent.name} died. I miss them.")
                    other.energy = max(0.0, other.energy - grief_penalty_for(other))
                    self.last_triggered_agent_ids.add(other.id)
                    _nudge_trait(other, TRAIT_RESILIENCE, TRAIT_GRIEF_NUDGE)
            if home is not None:
                life_events.extend(self._apply_inheritance(agent, home, dying_ids))
        self.agents = survivors
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
        if dying_ids:
            # A dead rider's mount goes back to the unclaimed pool rather
            # than staying claimed forever by nobody.
            for stl in settlements:
                for vehicle in stl.vehicles:
                    if vehicle.assigned_agent_id in dying_ids:
                        vehicle.assigned_agent_id = None
        return life_events

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

    def apply_goal(self, agent_id: int, goal: AgentGoal, reason: str) -> None:
        """Apply a resolved goal to an agent by id. A no-op if the agent
        has since died — cognition results can arrive on a later tick than
        they were requested on (see SimulationEngine)."""
        for agent in self.agents:
            if agent.id == agent_id:
                agent.goal = goal
                agent.goal_reason = reason
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

    def due_for_dialogue(self, seed: int, tick: int, cooldown_ticks: int) -> list[tuple[Agent, Agent]]:
        """Colocated, awake pairs whose cooldown has expired, capped at
        MAX_DIALOGUES_PER_TICK and chosen deterministically (namespaced
        RNG shuffle, not scan order) so which pairs talk first is
        reproducible for a given seed. Marks the selected pairs' cooldown
        immediately (not when the LLM result arrives) — the cooldown
        itself prevents re-selecting a pair while its exchange is still
        in flight, so no separate inflight-tracking set is needed. See
        docs/DECISIONS.md, E2.

        Also prunes `dialogue_cooldowns`: entries for agents no longer
        alive, and entries stale enough (well past their own cooldown
        window) that they're no longer preventing anything — found via
        an overnight-soak diagnostics audit that this dict grew
        unbounded over a long run (every pair that ever talked stayed in
        it forever). See docs/DECISIONS.md, diagnostics pass."""
        alive_ids = {a.id for a in self.agents}
        prune_horizon = cooldown_ticks * 8
        stale_keys = [
            key for key, last in self.dialogue_cooldowns.items()
            if key[0] not in alive_ids or key[1] not in alive_ids or tick - last > prune_horizon
        ]
        for key in stale_keys:
            del self.dialogue_cooldowns[key]

        by_position: dict[tuple[int, int], list[Agent]] = {}
        for agent in self.agents:
            if agent.state is AgentState.AWAKE:
                by_position.setdefault((agent.x, agent.y), []).append(agent)

        candidates: list[tuple[Agent, Agent]] = []
        for group in by_position.values():
            if len(group) < 2:
                continue
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                last = self.dialogue_cooldowns.get((a.id, b.id), -cooldown_ticks)
                if tick - last < cooldown_ticks:
                    continue
                candidates.append((a, b))
        if not candidates:
            return []

        rng = _namespaced_rng(seed, tick, "dialogue_select")
        rng.shuffle(candidates)
        selected = candidates[:MAX_DIALOGUES_PER_TICK]
        for a, b in selected:
            self.dialogue_cooldowns[(a.id, b.id)] = tick
        return selected

    def apply_dialogue(
        self, a_id: int, b_id: int, sentiment: str, rumor: str = "", line_a: str = "", line_b: str = "",
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
        docs/DECISIONS.md, Observatory UI pass."""
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
            new_value = max(-1.0, min(1.0, before + delta))
            agent_a.relationships[b_id] = new_value
            agent_b.relationships[a_id] = max(-1.0, min(1.0, agent_b.relationships.get(a_id, 0.0) + delta))
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
            agent_a.trust[b_id] = max(-1.0, min(1.0, trust_a_in_b + trust_delta))
            agent_b.trust[a_id] = max(-1.0, min(1.0, trust_b_in_a + trust_delta))
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
                listener.relationships[subject.id] = max(-1.0, min(1.0, listener_view + step))

    # --- disputes: rare LLM-mediated resolution of a festered feud (v0.64.0) ----

    def due_for_dispute(self, tick: int, cooldown_ticks: int) -> tuple[Agent, Agent] | None:
        """At most one deeply-soured pair per tick (mutual relationship
        at or below DISPUTE_RELATIONSHIP_THRESHOLD, both alive, cooldown
        expired) whose feud is ripe for a rare LLM-mediated resolution
        moment — see SimulationEngine._maybe_schedule_dispute. Marks the
        cooldown immediately, same convention as due_for_dialogue.
        Colocation deliberately NOT required: a feud simmers regardless
        of where either party happens to be standing."""
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
                if other_id <= agent.id or value > DISPUTE_RELATIONSHIP_THRESHOLD:
                    continue  # each pair once (lower id first), and only genuinely festered feuds
                other = by_id.get(other_id)
                if other is None:
                    continue
                if other.relationships.get(agent.id, 0.0) > DISPUTE_RELATIONSHIP_THRESHOLD:
                    continue  # the resentment must be mutual, not one-sided
                key = (agent.id, other_id)
                last = self.dispute_cooldowns.get(key, -cooldown_ticks)
                if tick - last < cooldown_ticks:
                    continue
                self.dispute_cooldowns[key] = tick
                return agent, other
        return None

    def apply_dispute(self, a_id: int, b_id: int, outcome: str) -> tuple[Agent, Agent] | None:
        """Apply a resolved dispute outcome with real mechanical effects
        (see the DISPUTE_* constants) — a no-op returning None if either
        party has since died, same convention as apply_dialogue."""
        agent_a, agent_b = self.get(a_id), self.get(b_id)
        if agent_a is None or agent_b is None:
            return None
        pairs = ((agent_a, agent_b), (agent_b, agent_a))
        if outcome == "reconcile":
            for me, them in pairs:
                me.relationships[them.id] = DISPUTE_RECONCILE_RELATIONSHIP
                me.trust[them.id] = max(-1.0, min(1.0, me.trust.get(them.id, 0.0) + DISPUTE_TRUST_DELTA))
                _remember(me, f"{them.name} and I made peace after our long feud.")
                _nudge_trait(me, TRAIT_SOCIABILITY, TRAIT_SOCIAL_CONTACT_NUDGE)
        elif outcome == "council_ruling":
            for me, them in pairs:
                # A ruling suppresses the feud without warming it — a
                # cool, enforced truce, not a reconciliation.
                me.relationships[them.id] = DISPUTE_TRUCE_RELATIONSHIP
                _remember(me, f"The council ruled on my dispute with {them.name}; we keep our distance now.")
        else:  # feud — the default/worst outcome
            for me, them in pairs:
                me.relationships[them.id] = max(
                    -1.0, me.relationships.get(them.id, 0.0) + DISPUTE_FEUD_DEEPEN
                )
                me.trust[them.id] = max(-1.0, min(1.0, me.trust.get(them.id, 0.0) - DISPUTE_TRUST_DELTA))
                _remember(me, f"My feud with {them.name} has hardened for good.")
                _nudge_trait(me, TRAIT_RESILIENCE, TRAIT_GRIEF_NUDGE)
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
            housing = CAMP_TOLERANCE + HUT_CAPACITY * sum(
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

    def hold_festival(self, settlement: Settlement | None = None) -> int:
        """Apply a one-time relationship boost to every currently-
        colocated pair of awake agents — the mechanical effect of a
        festival (hearthmind/llm/festival.py): the village gathers,
        bonds strengthen. A pair colocated on a standing SHRINE's tile
        gets SHRINE_FESTIVAL_BOOST_MULTIPLIER applied on top — the
        settlement's own invented culture deepening its own festival.
        Returns how many pairs were affected. See docs/DECISIONS.md,
        collective-behaviour pass and "culture-specific building
        types" pass."""
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
            for a, b in itertools.combinations(sorted(group, key=lambda ag: ag.id), 2):
                a.relationships[b.id] = max(-1.0, min(1.0, a.relationships.get(b.id, 0.0) + boost))
                b.relationships[a.id] = max(-1.0, min(1.0, b.relationships.get(a.id, 0.0) + boost))
                affected += 1
        return affected

    def spread_rumor(self, text: str, count: int, rng: random.Random) -> list[str]:
        """Integration milestone: seed a piece of news (currently only
        a caravan's outside rumor, see llm/caravan.py) into up to
        `count` living agents' own memories — the same `_remember`
        mechanism ordinary in-village events already use, so it can
        propagate further through the *existing* dialogue gossip/trust
        contagion rather than a bespoke broadcast. Returns the names of
        who heard it firsthand, for event logging. Listeners need not
        be colocated with each other — a caravan's news reaches whoever
        happened to deal with it, not the whole village at once."""
        if not self.agents:
            return []
        listeners = rng.sample(self.agents, k=min(count, len(self.agents)))
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
        consumed by `town_brain.fallback_priority`'s tie-break and (via
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
            "dispute_cooldowns": {
                f"{a_id}:{b_id}": tick for (a_id, b_id), tick in self.dispute_cooldowns.items()
            },
            "cognition_trigger_cooldowns": dict(self.cognition_trigger_cooldowns),
            "last_fission_tick": self.last_fission_tick,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Population":
        agents = [Agent.from_dict(a) for a in data["agents"]]
        dialogue_cooldowns = {}
        for key, tick in data.get("dialogue_cooldowns", {}).items():
            a_id, b_id = key.split(":")
            dialogue_cooldowns[(int(a_id), int(b_id))] = tick
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
            dispute_cooldowns=dispute_cooldowns,
            cognition_trigger_cooldowns=cognition_trigger_cooldowns,
            last_fission_tick=data.get("last_fission_tick", -1_000_000),
        )
