"""Buildings: constructed, decaying, repairable structures on the terrain.

Emergence lever, paralleling resources.py: buildings are finite, local,
and require sustained agent presence to build or maintain. Left untended,
weather erodes them; abandoned ruins are eventually reclaimed by nature.
Placement is deterministic in this slice — colocated, mature, healthy
agents may found a building, the same shape as A3's reproduction — not
yet an LLM/goal decision. See docs/DECISIONS.md, C1-C4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hearthmind.util import clamp
from hearthmind.settlement.institutions import Institution, InstitutionKind
from hearthmind.settlement.vehicles import (
    VEHICLE_DECAY_PER_TICK_BASE,
    VEHICLE_DECAY_WEATHER_MULTIPLIER,
    Vehicle,
    VehicleKind,
    VehicleStage,
)
from hearthmind.world.weather import WeatherState

try:
    from hearthmind._native import building_decay_tick as _native_building_decay_tick
    from hearthmind._native import vehicle_decay_tick as _native_vehicle_decay_tick
except ImportError:
    _native_building_decay_tick = None
    _native_vehicle_decay_tick = None
"""Optional compiled fast path for Settlement.tick's building/vehicle
decay-ruin-reclaim passes (modules 9-10, see cpp/src/settlement_decay.
cpp, docs/DECISIONS.md "Native extension port"). `None` when the
extension wasn't built — falls back to the equivalent pure-Python loops
in that case."""


class BuildingStage(str, Enum):
    UNDER_CONSTRUCTION = "under_construction"
    STANDING = "standing"
    RUINED = "ruined"


class BuildingKind(str, Enum):
    HUT = "hut"
    GRANARY = "granary"
    """Communal food storage — see docs/DECISIONS.md, D7. Once standing,
    well-fed agents present passively stock it, and hungry agents can draw
    from it (Population._maybe_forage/_nearest_food_target) — a buffer
    against a bad patch of wild-forage/farm luck rather than a
    per-agent inventory system, which doesn't exist in this project."""
    WORKSHOP = "workshop"
    """A business: staffed presence (awake, healthy agents) converts
    directly into settlement currency each tick — the town's economy
    beyond selling overflow food/materials. See WORKSHOP_INCOME_PER_TICK,
    docs/DECISIONS.md, "LLM-as-brain batch.\""""
    SCHOOL = "school"
    """Staffed presence slowly raises `Settlement.education_level`
    (capped), which boosts invention chance — an educated town invents
    more. See SCHOOL_EDUCATION_PER_TICK."""
    HOSPITAL = "hospital"
    """A standing hospital speeds hunger/energy recovery for RESTING
    agents present on its tile, and settlement-wide slightly reduces the
    chance a predator attack proves lethal — care exists, and it
    measurably helps. See HOSPITAL_REST_RECOVERY_MULTIPLIER,
    HOSPITAL_KILL_CHANCE_REDUCTION."""
    UNIVERSITY = "university"
    """A school's upgrade, not foundable directly — requires an existing
    standing SCHOOL and UNIVERSITY_TECH_REQUIREMENT inventions already
    established. Doubles a school's education contribution. See
    Population._maybe_start_construction/_maybe_start_vehicle-style
    founding gate, docs/DECISIONS.md, "LLM-as-brain batch.\""""
    FACTORY = "factory"
    """A workshop's industrial-era upgrade in kind (not a literal
    workshop->factory conversion; a separately foundable building) —
    only enters the foundable pool once the settlement has advanced
    past the `industrial` baseline era (see `Settlement.era`,
    `era_for_tech_level`), and produces currency per staffed worker at
    twice a workshop's rate. See FACTORY_INCOME_PER_TICK,
    docs/DECISIONS.md, real-calendar/genesis-seed follow-up."""
    SHRINE = "shrine"
    """The settlement's first genuinely culture-specific building kind
    — only enters the foundable pool once at least one tradition has
    been established (see `choose_building_kind`'s `has_tradition`
    gate), because a shrine is a physical expression of a custom the
    village has actually invented, not a generic civic structure
    available from day one. A standing shrine measurably deepens
    festivals held there (see SHRINE_FESTIVAL_BOOST_MULTIPLIER,
    Population.hold_festival) — culture begetting more culture, not
    just a differently-named hut. See docs/DECISIONS.md,
    "culture-specific building types" pass."""
    POWER_PLANT = "power_plant"
    """Integration milestone ("infrastructure networks"): the `power`
    half of that priority, hung off the era system's own already-named
    but previously mechanically-thin `electrical` era rather than
    inventing a parallel utility-grid data structure. Foundable from
    `electrical` onward, same era gate as FACTORY (`_ERA_UNLOCKS_
    ELECTRICAL`). While standing, boosts WORKSHOP/FACTORY income
    settlement-wide (`POWER_GRID_INDUSTRY_MULTIPLIER`) — electrified
    industry produces more — and contributes to `Population.
    carrying_capacity`'s infrastructure term alongside roads. See
    docs/DECISIONS.md, "Integration milestone: water/power/irrigation."
    """
    MARKET = "market"
    """Content-variety/roadmap pass: a genuinely bidirectional building
    with the caravan system (llm/caravan.py) — only enters the
    foundable pool once at least MARKET_CARAVAN_VISIT_REQUIREMENT
    caravans have ever reached the settlement (`Settlement.
    caravans_visited`, real outside contact justifying a market, same
    "physical expression of something the town has actually
    experienced" shape SHRINE already established for traditions), and
    once standing, measurably improves both future caravan trade terms
    (`MARKET_CARAVAN_YIELD_MULTIPLIER`) and how often a caravan chooses
    to visit at all (`MARKET_CARAVAN_CHANCE_MULTIPLIER`) — the town's
    outside contact and its own infrastructure reinforce each other,
    rather than caravans being a one-way, un-influenceable event.
    """


CONSTRUCTION_WORK_PER_TICK = 0.05
"""Progress added per tick, per present worker (capped at MAX_WORKERS
counted workers) — a hut takes ~20 ticks of one agent's continuous
presence, faster with more hands."""

REPAIR_WORK_PER_TICK = 0.03
"""Condition restored per tick, per present worker, for a standing
building below REPAIR_THRESHOLD."""

MAX_WORKERS = 3
"""Extra agents beyond this at one site don't speed construction/repair
further — a crude stand-in for "there's only so much useful room to work.\""""

REPAIR_THRESHOLD = 0.5
"""Standing buildings below this condition attract repair work from any
awake agents present, in addition to whatever else those agents are doing."""


def _condition_label(condition: float) -> str:
    """Human-readable band for a 0..1 condition value — used by
    `Settlement.infrastructure_report` for the UI telemetry panel and
    `inspect_world`. See docs/DECISIONS.md, "LLM-as-brain batch.\""""
    if condition >= 0.85:
        return "excellent"
    if condition >= REPAIR_THRESHOLD:
        return "good"
    if condition >= 0.2:
        return "worn"
    return "critical"

DECAY_PER_TICK_BASE = 0.0004
"""Baseline condition lost per tick for a standing building — roughly a
full decay from perfect condition over ~2500 ticks (~26 sim-days at
default pacing) with no weather effect and no repair."""

DECAY_WEATHER_MULTIPLIER = 3.0
"""Multiplier applied to decay during precipitation or high wind — storms
wear structures down faster than fair weather."""

SEASON_DECAY_MULTIPLIER = {"winter": 1.4, "autumn": 1.15, "spring": 1.0, "summer": 0.85}
"""Applied on top of DECAY_WEATHER_MULTIPLIER, not instead of it — real
building wear isn't just "is it raining right now," it's also the
season: winter's freeze-thaw cycles (water expanding in cracks) and
persistent damp are genuinely harder on masonry/timber than a dry
summer, independent of any single tick's weather. A season absent from
this table (shouldn't happen — all four exist) defaults to 1.0. See
docs/DECISIONS.md, "map/UI/ecology follow-up.\""""

SETTLE_CHANCE_PER_TICK = 0.01
"""Rolled only for mature, healthy, colocated (2+) agents standing on a
tile with no existing building — see Population._maybe_start_construction.
Raised from 0.003 (D6): with D4/D5/D6's survival fixes, qualifying pairs
are no longer rare, so the original rate left construction lagging behind
demand. Matches PLANT_CHANCE_PER_TICK's cadence."""

SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER = 1.6
SETTLE_CHANCE_OFF_PRIORITY_MULTIPLIER = 0.7
"""The town brain's civic priority already steers *what kind* gets built
(choose_building_kind's boosted weight); this closes the "whether"
half of the same "not yet built" roadmap gap — a settlement whose
current priority is "growth" is measurably likelier to found something
at all this tick, and less likely when the priority points elsewhere
(materials/attention presumably going toward whatever the priority
actually calls for instead). Applied in
Population._maybe_start_construction. No effect before the first
town-brain decision (current_priority == "" matches neither branch)."""

URBAN_GROWTH_ROAD_ADJACENCY_MULTIPLIER = 1.5
"""Integration milestone: `SETTLE_CHANCE_PER_TICK`'s multiplier for a
candidate tile adjacent to an established road — the standing roadmap
gap ("where to build is still pure chance") closed the same way
current_priority already closes the "whether/what kind" half: a real,
legible bias, never a hard rule (still colocation-driven, still a
chance roll). Roads accrete near existing activity (`roads.py`'s
presence-driven wear), so this creates a real, emergent "settlements
grow outward along their own roads" pattern rather than scattering
new buildings uniformly at random."""

SETTLE_CHANCE_RESOURCE_ADJACENCY_MULTIPLIER = 1.3
"""Second, independent "where to build" factor (stacks with roads'
above): a candidate tile within SETTLE_RESOURCE_SEARCH_RADIUS of a
still-productive resource node or open water is measurably more
likely to be settled — real towns cluster near the food/materials
they depend on, not just near their own existing roads. Deliberately
a smaller multiplier than roads' 1.5x: raw resource proximity is a
more "obvious" factor a founding group would notice at a glance,
while a road represents real prior communal investment, so it earns
the stronger pull. Applied in Population._maybe_start_construction."""

SETTLE_RESOURCE_SEARCH_RADIUS = 2
"""Chebyshev radius `_maybe_start_construction` scans around a
candidate tile for a productive resource node — small and local (a
founding group notices what's nearby, not across the whole map),
matching the radius order of magnitude other proximity checks in this
project use (e.g. road-adjacency's own 1-tile neighbor check)."""

MATURE_WORKER_ONLY = False
"""Whether construction/repair work requires workers to be "mature"
(see agents.agent.MATURITY_TICKS). False: any awake agent present helps —
only *founding* a new building requires maturity (see C1)."""

MEMORIALS_MAX_STORED = 150
"""Cap on stored grave marks (`SettlementInfrastructure.memorials`) —
oldest pruned first: the oldest graves fade from living memory, same
bounded-memory discipline as every other capped list. Generous enough
that a normal settlement's whole visible history of loss stays on the
map for many sim-years."""

RECORDS_MAX_STORED = 40
"""Cap on stored written artifacts (`SettlementCulture.records`) —
letters are rare (one per notable death, see RECORD_MIN_MEMORIES), so
this is a true safety ceiling, not a working limit."""

INSTITUTION_LIST_MAX_STORED = 300
"""Cap on the *stored* count of FAMILY institutions in
`Settlement.institutions` (v0.54.0) — a 40k-tick live measurement (seed
42, no cap) showed family count climbing roughly linearly with
cumulative births regardless of population (191 families at pop 295,
still climbing), unlike population itself which plateaus at the carrying
capacity: on a genuinely persistent world this is unbounded growth, the
same bug class as the pre-v0.44.1 traditions/inventions/festivals lists.
Unlike those three (pure flavor text, safe to hard-truncate to the
newest N), a FAMILY institution is looked up by living-agent membership
(`family_for`, inheritance, dialogue) — blindly dropping the oldest
entries could silently orphan a still-living elder's family. Pruning
(`population._prune_extinct_families`) is therefore extinction-aware:
only FAMILY institutions with zero living members are eligible for
removal, oldest-founded first, and only once the stored count exceeds
this cap — a family with even one living member is never touched.
COUNCIL institutions are never pruned (COUNCIL_SIZE keeps that kind
inherently small)."""

CULTURE_LIST_MAX_STORED = 300
"""Cap on the *stored* length of Settlement.traditions/inventions/
festivals (v0.44.1) — previously unbounded: `PROMPT_CULTURE_LIST_MAX`
(see simulation/engine.py) only ever capped what's *sent* to an LLM
prompt, not the underlying list itself, so a sufficiently long-running
world would grow these three lists forever. Each entry is a short
string, so this was never a fast leak, but "aggressive memory
optimization for extremely long runs" means no structure should be
truly unbounded, however slow-growing. 300 is generous relative to how
these actually accumulate (traditions ~1/season at a low roll chance,
festivals ~1/month at a low roll chance, inventions ~1/season at
INVENTION_CHANCE_PER_SEASON) — a settlement would need centuries of
sim-time to hit this cap under normal play, so it's a true safety
ceiling, not a working limit. Fallback ordinal naming ("Tradition the
14th") no longer reads list length directly (which the cap would
otherwise corrupt) — see `SettlementCulture.traditions_established`/
`festivals_held` below and `Settlement.tech_level` (inventions already
had its own persistent counter, reused here rather than duplicated)."""

RUIN_REMOVAL_TICKS = 1200
"""Ticks a ruined building persists (still inspectable) before nature
finishes reclaiming it and it's removed from the world entirely.
Lowered from 3000 (v0.44.1) — at 3000 ticks (~31 sim-days) a ruin
outlived most normal live-observation sessions, reading as "ruined
buildings are never removed" even though the removal mechanism was
always correct (verified: `Settlement.tick()` reliably transitions
RUINED -> removed once `ruined_ticks >= RUIN_REMOVAL_TICKS`). ~12.5
sim-days is long enough to read as a real ruin, not an instant clean-up,
short enough to actually observe clearing within a normal session.
Secondary benefit: a ruin occupies its tile and blocks new construction
there (`Settlement.at(x, y) is not None` in `_maybe_start_construction`)
— clearing it sooner frees that tile back to the settlement faster,
compounding with the v0.43.2 housing fixes rather than fighting them."""

HUT_MATERIALS_COST = 3.0
GRANARY_MATERIALS_COST = 5.0
WORKSHOP_MATERIALS_COST = 4.0
SCHOOL_MATERIALS_COST = 6.0
HOSPITAL_MATERIALS_COST = 8.0
UNIVERSITY_MATERIALS_COST = 10.0
FACTORY_MATERIALS_COST = 14.0
SHRINE_MATERIALS_COST = 5.0
POWER_PLANT_MATERIALS_COST = 12.0
"""Comparable investment to a FACTORY — a real infrastructure
commitment, not a cheap add-on."""
MARKET_MATERIALS_COST = 7.0
"""Between WORKSHOP (4.0) and HOSPITAL (8.0) — a real but modest civic
investment, not gated by cost so much as by MARKET_CARAVAN_VISIT_
REQUIREMENT (the town needs a reason to build one before it can afford
to want to)."""
"""Materials deducted from the settlement stockpile when construction is
founded — buildings are now genuinely "built from resources available"
(previously materials only sped construction up, via
CONSTRUCTION_MATERIALS_MULTIPLIER; a colocated, mature, healthy pair
could found a building with zero materials on hand). A settlement with
no stockpile can no longer spontaneously start a building — presence
alone is no longer sufficient, matching real construction needing
material on site before ground is broken. Costs scale roughly with
civic weight: a hut is cheapest, a hospital (the biggest health
investment) is the most expensive foundable kind, and a university
(upgrading an existing school, not founded fresh) costs the most of
all. See docs/DECISIONS.md, buildings-need-resources pass and
"LLM-as-brain batch.\""""

MATERIALS_COST_BY_KIND: dict[BuildingKind, float] = {
    BuildingKind.HUT: HUT_MATERIALS_COST,
    BuildingKind.GRANARY: GRANARY_MATERIALS_COST,
    BuildingKind.WORKSHOP: WORKSHOP_MATERIALS_COST,
    BuildingKind.SCHOOL: SCHOOL_MATERIALS_COST,
    BuildingKind.HOSPITAL: HOSPITAL_MATERIALS_COST,
    BuildingKind.UNIVERSITY: UNIVERSITY_MATERIALS_COST,
    BuildingKind.FACTORY: FACTORY_MATERIALS_COST,
    BuildingKind.SHRINE: SHRINE_MATERIALS_COST,
    BuildingKind.POWER_PLANT: POWER_PLANT_MATERIALS_COST,
    BuildingKind.MARKET: MARKET_MATERIALS_COST,
}

BUILDING_KIND_BASE_WEIGHTS: dict[str, float] = {
    "hut": 0.42, "granary": 0.23, "workshop": 0.15, "school": 0.12, "hospital": 0.08,
    "factory": 0.10, "shrine": 0.07, "power_plant": 0.06, "market": 0.07,
}
"""Baseline odds a new civic building is each kind, before
`Settlement.current_priority` (the seasonal "town brain" LLM
decision — see llm/town_brain.py) reweights them. UNIVERSITY is
deliberately excluded: it's an upgrade of an existing SCHOOL, not
founded from this pool. FACTORY is present here but filtered out by
`choose_building_kind` until the settlement's era allows it (see
`era_for_tech_level`) — it's an industrial-era-or-later kind, not
foundable from a settlement's earliest days. SHRINE is likewise
filtered out until the settlement has established at least one
tradition (see the `has_tradition` gate) — a settlement's culture has
to actually exist before it gets a building expressing it."""

PRIORITY_KIND_BOOST = 2.5
"""Multiplier applied to one kind's weight when it matches the
settlement's current civic priority — a real, measurable steer, not
just flavor text, but not so dominant that other kinds stop appearing
entirely (see docs/DECISIONS.md, "LLM-as-brain batch")."""

_PRIORITY_TO_KIND = {
    "growth": "hut", "food": "granary", "commerce": "workshop",
    "education": "school", "health": "hospital", "defense": "hut",
}
"""Maps a `Settlement.current_priority` value to the `BuildingKind`
value it boosts. "defense" has no dedicated building yet, so it boosts
huts (more shelter, more hands) rather than doing nothing."""

# --- eras: the town starts industrial and advances as it invents -----------

ERA_ORDER = ("industrial", "electrical", "modern", "digital")
ERA_TECH_THRESHOLDS: dict[str, int] = {"industrial": 0, "electrical": 3, "modern": 7, "digital": 12}
"""A settlement's era is purely a function of accumulated `tech_level`
(established inventions, see llm/invention.py) — no separate era-only
mechanic to keep in sync. Thresholds are deliberately steep:
inventions are already rare (INVENTION_CHANCE_PER_SEASON), so reaching
`digital` is a long-run milestone, not a fast unlock."""
ERA_DESCRIPTIONS: dict[str, str] = {
    "industrial": "smokestacks and hand tools",
    "electrical": "the first wired lights and machinery",
    "modern": "motorised tools and mass production",
    "digital": "computing woven into daily civic life",
}

_ERA_UNLOCKS_ELECTRICAL = frozenset({"electrical", "modern", "digital"})
"""FACTORY and POWER_PLANT are foundable from `electrical` onward, not
`industrial` — the settlement starts industrial with only the earlier
building kinds available; both represent genuine progress past that
baseline (renamed from `_ERA_UNLOCKS_FACTORY` when POWER_PLANT started
sharing the same gate — integration milestone)."""

ERA_UNLOCKS_MOUNTAIN_BUILDING = frozenset({"electrical", "modern", "digital"})
"""Mining/tunneling technology past `industrial` lets a settlement stake
construction sites on MOUNTAIN terrain and lets its agents actually walk
onto it (`Population._choose_build_site`, `_dispatch_movement`'s
mountain_unlocked threading into `_step_toward`/`_bfs_step`) — before
this era, MOUNTAIN/SNOWCAP stay outside `WALKABLE_BIOMES` entirely, a
hard, unconditional barrier at every era (v0.68.0 fix for a live report
that geography never interacted with tech level at all). Same gate as
FACTORY/POWER_PLANT (`_ERA_UNLOCKS_ELECTRICAL`) — reused conceptually,
not the same object, since this one is consumed by `agents/population.py`
and importing a private name across modules is worse than one more
frozenset literal."""

ERA_UNLOCKS_AUTOMOBILE = frozenset({"modern", "digital"})
"""The AUTOMOBILE vehicle kind (settlement/vehicles.py) is foundable
from `modern` onward — carts and mounts stay realistic transport at
`industrial`/`electrical` (horse-drawn transport genuinely coexisted
with early industry for decades); an automobile represents the
settlement's transport actually modernizing, not just its buildings."""


def era_for_tech_level(tech_level: int) -> str:
    era = ERA_ORDER[0]
    for name in ERA_ORDER:
        if tech_level >= ERA_TECH_THRESHOLDS[name]:
            era = name
    return era


PRIORITY_HISTORY_MAX = 6
OMEN_HISTORY_MAX = 6
"""How many past town-brain decisions `Settlement.priority_history`
keeps — enough for the UI's "internal monologue" reveal to feel like a
running train of thought, not so many it grows unbounded across a
long-running world."""


def choose_building_kind(
    rng, current_priority: str, era: str = "industrial", has_tradition: bool = False,
    caravans_visited: int = 0,
) -> "BuildingKind":
    """Weighted pick among the foundable civic kinds (not UNIVERSITY,
    which upgrades an existing school instead) — base odds nudged
    toward whatever the settlement's current priority calls for,
    FACTORY/POWER_PLANT excluded entirely until `era` has advanced past
    `industrial`, SHRINE excluded until the settlement has established
    at least one tradition (`has_tradition`), and MARKET excluded until
    at least MARKET_CARAVAN_VISIT_REQUIREMENT caravans have ever
    reached the settlement (`caravans_visited`). Falls back to the
    unweighted base odds for an unrecognized/empty priority (e.g.
    before the first town-brain decision has ever run). See
    docs/DECISIONS.md, "LLM-as-brain batch\", the real-calendar/
    genesis-seed follow-up, "culture-specific building types,\" and
    "Integration milestone: water/power/irrigation.\""""
    weights = dict(BUILDING_KIND_BASE_WEIGHTS)
    if era not in _ERA_UNLOCKS_ELECTRICAL:
        weights.pop("factory", None)
        weights.pop("power_plant", None)
    if not has_tradition:
        weights.pop("shrine", None)
    if caravans_visited < MARKET_CARAVAN_VISIT_REQUIREMENT:
        weights.pop("market", None)
    boosted = _PRIORITY_TO_KIND.get(current_priority)
    if boosted in weights:
        weights[boosted] *= PRIORITY_KIND_BOOST
    total = sum(weights.values())
    roll = rng.random() * total
    upto = 0.0
    for kind_value, weight in weights.items():
        upto += weight
        if roll <= upto:
            return BuildingKind(kind_value)
    return BuildingKind.HUT  # unreachable in practice; keeps the function total


GRANARY_CAPACITY = 15.0
"""Max food a standing granary can hold — several farm harvests' worth
(MAX_FARM_YIELD is 3.0), enough to matter as a buffer without trivializing
scarcity."""

GRANARY_WELLFED_HUNGER_THRESHOLD = 0.3
"""An awake agent at or below this hunger, present at a standing granary,
contributes surplus each tick — presence-driven like every other
mechanic here (foraging, construction), not a hauling/inventory system."""

GRANARY_DEPOSIT_PER_TICK = 0.02
"""Food added per well-fed agent present, per tick, up to GRANARY_CAPACITY."""

GRANARY_WITHDRAW_AMOUNT = 0.25
"""Food consumed from a granary per successful withdrawal (see
Population._maybe_forage) — between a wild forage (FORAGE_AMOUNT 0.2) and
a farm harvest (HARVEST_AMOUNT 0.3): better than scrounging, worse than a
fresh crop."""

GRANARY_HUNGER_RELIEF = 0.4
"""Hunger relief for a full granary withdrawal — between
FORAGE_HUNGER_RELIEF (0.3) and HARVEST_HUNGER_RELIEF (0.5)."""

MATERIALS_CAPACITY = 30.0
"""Max wood/stone a settlement's shared stockpile can hold — see D8."""

MATERIALS_GATHER_PER_TICK = 0.03
"""Materials added per GATHER-goal agent present on forest/hills, per
tick, up to MATERIALS_CAPACITY — see Population._maybe_gather."""

MATERIALS_PER_CONSTRUCTION_TICK = 0.1
"""Materials consumed per tick a construction site draws on the
stockpile, in exchange for CONSTRUCTION_MATERIALS_MULTIPLIER — see
Population._advance_construction."""

CONSTRUCTION_MATERIALS_MULTIPLIER = 2.0
"""Construction progress multiplier while materials are available and
being consumed — the actual payoff of the D8 production chain (gather ->
stockpile -> faster building) over presence alone."""

CURRENCY_CAPACITY = 50.0
"""Max settlement currency — see D10."""

CURRENCY_PER_OVERFLOW_UNIT = 1.0
"""Currency generated per unit of food/materials that would otherwise be
wasted once a granary/the materials stockpile is already at capacity —
"trade" here means selling surplus to an abstract outside economy, not
literal per-agent barter, since no per-agent inventory exists in this
project (see docs/DECISIONS.md, D10 for the full rationale)."""

CURRENCY_EMERGENCY_RATION_COST = 2.0
"""Currency spent per emergency-ration purchase — see
Population._maybe_forage, D10."""

CURRENCY_EMERGENCY_HUNGER_RELIEF = 0.4
"""Hunger relief per emergency-ration purchase — matches
GRANARY_HUNGER_RELIEF: bought food is as good as stored food, just costs
currency instead of being free."""

# --- economy buildings: workshops, schools, hospitals -----------------------

WORKSHOP_INCOME_PER_TICK = 0.03
"""Currency generated per awake, healthy agent present at a standing
workshop, per tick, up to CURRENCY_CAPACITY — a business, not just
overflow-selling: this is currency income from nothing being wasted,
same order of magnitude as MATERIALS_GATHER_PER_TICK."""

FACTORY_INCOME_PER_TICK = 0.06
"""Same shape as WORKSHOP_INCOME_PER_TICK, at twice the rate — a
factory is the settlement's industrial-era-or-later economic upgrade,
foundable only once `Settlement.era` has advanced past `industrial`
(see `_ERA_UNLOCKS_ELECTRICAL`)."""

POWER_GRID_INDUSTRY_MULTIPLIER = 1.3
"""Multiplies WORKSHOP_INCOME_PER_TICK/FACTORY_INCOME_PER_TICK
settlement-wide while a standing POWER_PLANT exists (`Population.
_maybe_run_workshops`/`_maybe_run_factories`) — electrified industry
produces more, the concrete payoff for `electrical` era being more
than a label. Applied once per settlement (not per powered building —
there's no per-building grid-connection concept, matching every other
building-effect's settlement-wide scope in this project)."""

CARRYING_CAPACITY_POWER_PLANT_BONUS = 0.03
"""Flat addition to `Population.carrying_capacity`'s infrastructure
term while a POWER_PLANT stands, alongside the existing road-density
component — small on purpose (roads remain the dominant infrastructure
signal; a power plant is a single building, not a network)."""

MARKET_CARAVAN_VISIT_REQUIREMENT = 1
"""How many caravans must have ever reached the settlement
(`Settlement.caravans_visited`) before MARKET enters the foundable
pool (`choose_building_kind`) — just one, deliberately: the point is
that a market needs *any* real outside contact to make sense at all,
not that it needs a sustained trade history first (that's what the
market itself, once built, then helps grow)."""

MARKET_CARAVAN_YIELD_MULTIPLIER = 1.4
"""Multiplies a caravan's currency/materials exchange magnitude while
a standing MARKET exists (`SimulationEngine._maybe_schedule_caravan`)
— a town with a real place to trade gets better terms from a visiting
caravan, the direct payoff for building one. Same order of magnitude
as POWER_GRID_INDUSTRY_MULTIPLIER (1.3x)."""

MARKET_PRICE_MIN = 0.5
MARKET_PRICE_MAX = 2.0
MARKET_PRICE_SMOOTHING = 0.6
"""Multi-good market pricing (v0.64.0 audit-backlog item): while a
MARKET stands, the settlement carries a per-good price multiplier
(`SettlementEconomy.market_prices`, food/materials), re-derived monthly
from actual scarcity — a good's price drifts toward `2.0 - 1.5 x fill
ratio` (empty stores -> 2.0x, full stores -> 0.5x), smoothed so one
lean month doesn't whipsaw the economy. Deterministic (objective
economics, the engine's domain — same reasoning as the caravan
exchange itself). Consumed by overflow-selling (scarce goods fetch
more when sold to the abstract outside economy) and the emergency-
ration purchase (famine food costs more) — so a MARKET makes the
settlement's economy *react to its own state* instead of trading at
flat constants forever. Without a standing market, prices reset to
1.0: informal barter has no price discovery."""


def tick_market_prices(settlement: "Settlement", population_hint: int = 0) -> None:
    """Called on month boundaries (SimulationEngine). Mutates
    `settlement.economy.market_prices` in place — see MARKET_PRICE_MIN's
    docstring for the model."""
    prices = settlement.economy.market_prices
    if not settlement.has_market():
        if prices:
            prices.clear()
        return
    granaries = [
        b for b in settlement.buildings
        if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
    ]
    granary_capacity = len(granaries) * GRANARY_CAPACITY
    food_fill = (sum(b.stored_food for b in granaries) / granary_capacity) if granary_capacity else 0.5
    materials_fill = settlement.materials / MATERIALS_CAPACITY if MATERIALS_CAPACITY else 0.5
    # Cross-settlement relations (v0.67.0) add a small, ambient regional-
    # trade nudge on top of the supply/demand target — see
    # market_relation_factor/RELATION_MARKET_INFLUENCE.
    relation_factor = market_relation_factor(settlement)
    for good, fill in (("food", food_fill), ("materials", materials_fill)):
        target = MARKET_PRICE_MAX - (MARKET_PRICE_MAX - MARKET_PRICE_MIN) * clamp(fill, 0.0, 1.0)
        target *= relation_factor
        current = prices.get(good, 1.0)
        blended = current * MARKET_PRICE_SMOOTHING + target * (1.0 - MARKET_PRICE_SMOOTHING)
        prices[good] = round(max(MARKET_PRICE_MIN, min(MARKET_PRICE_MAX, blended)), 3)


MARKET_CARAVAN_CHANCE_MULTIPLIER = 1.25
"""Multiplies CARAVAN_CHANCE_PER_MONTH while a standing MARKET exists
— traders are more likely to detour toward a settlement known to have
one, closing the loop the other direction: outside contact justifies
building a market (MARKET_CARAVAN_VISIT_REQUIREMENT), and a market in
turn draws more outside contact. Deliberately smaller than the yield
multiplier — a market changes how good a visit is more than how often
one happens."""

TOOLS_CAPACITY = 5.0
"""H4 (docs/ROADMAP.md "Phase H"): max personal `"tools"` an agent's
inventory can hold — see `Agent.inventory`, same shape as
PERSONAL_FOOD_CAPACITY but a separate cap since tools and food are
different goods with different scarcity."""

WORKSHOP_CRAFT_MATERIALS_COST_PER_TICK = 0.05
WORKSHOP_CRAFT_TOOLS_PER_TICK = 0.02
"""H4: the first real multi-good supply chain — a staffed, standing
workshop with materials available converts `WORKSHOP_CRAFT_MATERIALS_
COST_PER_TICK` of the settlement's shared stockpile into
`WORKSHOP_CRAFT_TOOLS_PER_TICK` *personal* tools for each present awake
worker (added directly to `Agent.inventory["tools"]`, up to
TOOLS_CAPACITY) — a real ownership/specialization step: crafted output
belongs to the specific worker who made it, not the commons, unlike
every other workshop/factory mechanic in this project so far. Additive
to (not replacing) WORKSHOP_INCOME_PER_TICK's existing currency income;
the two compete for the same finite materials stockpile as construction
already does, which is the point — materials are now a genuinely
contested resource across three consumers (building, crafting,
overflow-selling), not just two. See Population._maybe_craft_tools."""

MEDICINE_CAPACITY = 3.0
"""H4 extension (docs/ROADMAP.md "Phase H"): max personal `"medicine"`
an agent's inventory can hold — same shape as TOOLS_CAPACITY, a second
good with its own cap since medicine/tools/food are all separately
scarce."""

HOSPITAL_CRAFT_MATERIALS_COST_PER_TICK = 0.05
HOSPITAL_CRAFT_MEDICINE_PER_TICK = 0.02
"""H4 extension: the second crafted-good supply chain, same shape as
WORKSHOP_CRAFT_MATERIALS_COST_PER_TICK/WORKSHOP_CRAFT_TOOLS_PER_TICK —
a staffed, standing hospital converts shared materials into personal
medicine for its present awake workers. See Population._maybe_craft_
medicine."""

MEDICINE_DEATH_CHANCE_REDUCTION = 0.5
"""A sick agent personally holding medicine has their own disease
death-chance roll multiplied by (1 - this), on top of (not instead of)
the settlement-wide SICKNESS_HOSPITAL_KILL_CHANCE_REDUCTION a standing
hospital already gives everyone — personal medicine is a second,
individually-earned layer of protection, same "specialization has a
real, individual payoff" shape TOOLS/SKILL_FARMING_YIELD_BONUS
established. See Population._tick_disease."""

MEDICINE_CONSUMPTION_PER_TICK = 0.02
"""Medicine drawn down each tick a stocked agent is sick — roughly
matches HOSPITAL_CRAFT_MEDICINE_PER_TICK's craft rate, so sustained
treatment through a full bout (SICKNESS_DURATION_TICKS) requires
ongoing production, not a one-time stockpile."""

EDUCATION_CAPACITY = 1.0
"""Max `Settlement.education_level` — see SCHOOL_EDUCATION_PER_TICK and
`education_invention_bonus`."""

SCHOOL_EDUCATION_PER_TICK = 0.01
UNIVERSITY_EDUCATION_MULTIPLIER = 2.0
"""Education added per awake, healthy agent present at a standing
school, per tick, up to EDUCATION_CAPACITY — a university (an upgraded
school) contributes at this multiple instead."""

UNIVERSITY_TECH_REQUIREMENT = 3
"""A school can only be upgraded to a university once the settlement
has this many established inventions — a university presupposes an
already fairly advanced town, not something foundable from scratch."""


def education_invention_bonus(education_level: float) -> float:
    """Multiplicative bonus on invention chance from accumulated
    education — an educated town invents more. Mirrors
    `_tech_factor`'s shape (1.0 + something), used by
    SimulationEngine._maybe_schedule_invention. See docs/DECISIONS.md,
    "LLM-as-brain batch.\""""
    return 1.0 + education_level


HOSPITAL_REST_RECOVERY_MULTIPLIER = 1.5
"""A RESTING agent physically present on a standing hospital's tile
recovers energy this much faster than resting elsewhere — see
Population._update_needs."""

HOSPITAL_KILL_CHANCE_REDUCTION = 0.3
"""Fractional reduction to PREDATOR_KILL_CHANCE_ON_ATTACK, settlement-
wide, once at least one hospital is standing — care exists and
measurably improves survival odds, not just narrative flavor. See
Population._maybe_predator_attack."""

# --- shelter, housing, and upkeep: buildings that actually do something ----

HUT_CAPACITY = 5
"""Comfortable residents per standing HUT — the hut's first real
mechanical function (previously it was a pure materials sink with no
effect; the July 2026 review's "huts do nothing" finding). Total
housing = standing huts x this, plus CAMP_TOLERANCE below."""

CAMP_TOLERANCE = 18
"""People a settlement absorbs comfortably with no housing at all — a
founding party camps fine, so crowding pressure only begins once the
population has genuinely outgrown tents. Deliberately kept above
`Config.initial_population` (12): `carrying_capacity`'s multiplier
starts below 1.0 for an immature founding party (all agents start at
age_ticks=0 in `_generate_founders`, so `labor_term` is negative until
MATURITY_TICKS), which combined with a tolerance exactly equal to the
founding size left zero reproduction headroom until the first HUT was
built — a live report of "no births by tick 15000" traced to this
(v0.68.0). See Population.tick's crowding computation and
Population.carrying_capacity."""

CROWDING_ENERGY_MULTIPLIER = 1.12
"""Awake energy-drain multiplier while the population exceeds total
housing (huts x HUT_CAPACITY + CAMP_TOLERANCE) — rough nights without a
roof wear people down. Deliberately mild (same order as the night
multiplier), but it finally gives the town brain's "growth" priority a
real consequence: building huts relieves a measurable pressure."""

CARRYING_CAPACITY_ECONOMY_WEIGHT = 0.25
CARRYING_CAPACITY_SECURITY_WEIGHT = 0.25
CARRYING_CAPACITY_LABOR_WEIGHT = 0.2
CARRYING_CAPACITY_ENVIRONMENT_WEIGHT = 0.15
"""Weights composing `Population.carrying_capacity`'s multiplier applied
to housing (the base term, huts x HUT_CAPACITY + CAMP_TOLERANCE): granary
fill (economy — only scored once a granary exists, so a founding party
with no infrastructure yet isn't penalized for infrastructure it hasn't
had time to build), sickness/predator pressure (security), the fraction
of mature/healthy agents (labor), and current weather harshness
(environment). H1, docs/ROADMAP.md Phase H — replaces the flat
`POPULATION_CAP` as the operative constraint on reproduction/migration;
`POPULATION_CAP` itself remains untouched as a hard ceiling far above any
realistic computed value, a safety valve against a tuning mistake here,
not the intended limiting mechanism."""

CARRYING_CAPACITY_COORDINATION_WEIGHT = 0.1
CARRYING_CAPACITY_KNOWLEDGE_WEIGHT = 0.1
CARRYING_CAPACITY_INFRASTRUCTURE_WEIGHT = 0.1
"""Integration-milestone extension to the weights above — carrying
capacity previously read only housing/economy/security/labor/weather,
leaving institutions, skills, and infrastructure with no way to expand
(or shrink) what the settlement can actually support, despite all three
being real, effortful things a village can build up. Deliberately the
smallest three weights in the composition (a sitting council, a skilled
population, and a road network all matter, but none should ever
outweigh whether people are literally fed or housed) — see
`Population.carrying_capacity` for how each term is actually computed.
COORDINATION scores 0 with no COUNCIL (nothing to coordinate yet) up to
this weight at a fully organized, high-disposition council; KNOWLEDGE
scores off the same population-average skill level `_maybe_schedule_
invention` already reads (SKILL_FARMING/SKILL_CONSTRUCTION); INFRASTRUCTURE
scores off established road tiles per capita, capped so a sprawling road
network past what the population could ever need stops paying off."""

CARRYING_CAPACITY_ROADS_PER_CAPITA_SATURATION = 0.15
"""Established road tiles per living agent at which INFRASTRUCTURE's
term maxes out (see CARRYING_CAPACITY_INFRASTRUCTURE_WEIGHT) — roughly
one worn road tile per ~7 people comfortably saturates the term; more
roads past that point are still useful (site selection, contact rate)
but stop adding further capacity headroom on their own."""

CARRYING_CAPACITY_MIN_MULTIPLIER = 0.5
CARRYING_CAPACITY_MAX_MULTIPLIER = 1.5
"""Bounds on the composed multiplier above — a settlement in crisis
(plague, siege, famine) can still support down to half its housing-based
capacity, and a thriving one can stretch to 1.5x it, but neither factor
set can send the ceiling to zero or unbounded growth on its own."""

SHELTER_NEGATES_WEATHER = True
"""An AWAKE agent standing on any STANDING building's tile is treated
as working indoors: the harsh-weather hunger/energy multipliers don't
apply (resting agents were already abstracted as sheltered). Buildings
now interact with the weather system from the human side, not just by
decaying. See Population._update_needs."""

UPKEEP_PER_CIVIC_BUILDING_PER_TICK = 0.002
"""Currency drawn per tick per standing non-HUT building (workshops,
granaries, schools, hospitals, universities, factories, shrines) — the
economy's first recurring *sink* (the review measured currency pinned
at its cap with only the rare emergency-ration purchase spending it).
Sized well below one staffed workshop's income (0.03/tick), so a
working town runs a surplus; a town whose businesses stop being staffed
starts visibly deferring maintenance instead."""

UPKEEP_UNPAID_DECAY_MULTIPLIER = 1.5
"""Standing-building decay multiplier applied in proportion to the
unpaid fraction of this tick's upkeep — a town that can't afford
maintenance watches its civic buildings wear out faster, closing the
loop currency -> upkeep -> decay -> repair labor. See Settlement.tick."""

# --- temperament: a deterministic, ambiguous "does this place have moods?" --

TEMPERAMENT_STEP_MAX = 0.04
TEMPERAMENT_MEAN_REVERSION = 0.97
"""Same bounded-random-walk shape as world/terrain_evolution.py's
ClimateState (small step, slight decay toward 0 each tick) — not a
runaway trend. `Settlement.temperament` (-1..1) is entirely
deterministic: a real value computed from real recent-event counts plus
bounded noise, same as everything else in the deterministic engine.
Nothing here asserts the town is "conscious" — that reading is left to
the player and to whatever an LLM chooses to write about it (see
llm/omens.py). See docs/DECISIONS.md, "World-G follow-up.\""""

TEMPERAMENT_FORTUNE_WEIGHT = 0.15
"""How strongly the recent balance of good/ill fortune (see
`_GOOD_FORTUNE_CATEGORIES`/`_ILL_FORTUNE_CATEGORIES`) biases
temperament's random-walk step, alongside pure noise — a town that's
recently seen more births/festivals/inventions than deaths/ruin drifts
warmer, and vice versa, but slowly and never deterministically from a
single event."""

_GOOD_FORTUNE_CATEGORIES = frozenset({
    "birth", "festival", "invention", "building_completed", "tradition", "settlement_named",
})
_ILL_FORTUNE_CATEGORIES = frozenset({
    "death", "building_ruined", "wildlife_extinct", "vehicle_broken",
})

TEMPERAMENT_INVENTION_INFLUENCE = 0.2
"""Fractional nudge to invention chance from temperament — see
SimulationEngine._maybe_schedule_invention. Deliberately small: a
strongly warm town invents at most ~1.2x baseline, a strongly cold one
~0.8x — noticeable across a long run, never a dominant factor next to
prosperity gates/education."""

SHRINE_OMEN_CHANCE_MULTIPLIER = 1.3
"""Applied to `llm/omens.py`'s per-month firing chance when a SHRINE is
standing — a place the village built for its own invented culture is
somewhat likelier to be where something ambiguous gets noticed, the
first place a new system (culture-specific buildings) and Phase G
(omens) deliberately interact rather than staying isolated. Same small,
non-dominant magnitude as every other Phase G nudge. See
docs/DECISIONS.md, "Phase G v4: shrine/omen interaction" pass."""

TEMPERAMENT_KILL_CHANCE_INFLUENCE = 0.2
"""Fractional nudge to predator-attack lethality from temperament — see
Population._maybe_predator_attack. Same small-magnitude rationale as
TEMPERAMENT_INVENTION_INFLUENCE, applied after the hospital reduction."""


def tick_temperament(temperament: float, recent_events: list[dict], rng, intensity: float = 1.0) -> float:
    """Nudge temperament one step (called monthly, alongside beliefs —
    see SimulationEngine._maybe_tick_temperament). `recent_events` is
    the same recent_events(conn, limit=...) shape used elsewhere
    (dicts with a "category" key). `intensity` is Config.phase_g_
    intensity — scales the step itself (noise and fortune-bias alike),
    so 0.0 holds temperament flat at its mean-reverted value (drifting
    to 0 over time, never nudged) rather than requiring a separate
    on/off flag."""
    good = sum(1 for e in recent_events if e.get("category") in _GOOD_FORTUNE_CATEGORIES)
    ill = sum(1 for e in recent_events if e.get("category") in _ILL_FORTUNE_CATEGORIES)
    fortune = (good - ill) / (good + ill) if (good + ill) else 0.0
    step = (rng.uniform(-TEMPERAMENT_STEP_MAX, TEMPERAMENT_STEP_MAX) + fortune * TEMPERAMENT_FORTUNE_WEIGHT) * intensity
    return clamp(temperament * TEMPERAMENT_MEAN_REVERSION + step, -1.0, 1.0)

# --- player standing: a discrete "how does the village feel about being --
# --- nudged from outside" lever, alongside temperament's general mood ---

PLAYER_STANDING_MEAN_REVERSION = 0.95
"""Faster decay toward 0 than temperament's 0.97 — the village's sense
of the outside hand fades a little quicker than its own internal mood
without repeated reinforcement, since it's about an external presence
rather than the village's own affairs."""

PLAYER_STANDING_STEP_PER_INTERVENTION = 0.06
PLAYER_STANDING_MAX_EVENTS_COUNTED = 5
"""Each `intervention`-category event this month (a whisper, a resource
nudge, a weather/goal nudge) moves standing warmer by this much, capped
at MAX_EVENTS_COUNTED events so a burst of nudges in one month doesn't
swing it to the extreme in a single step — steady, occasional attention
reads as more genuinely "looked after" than a flood of one-time nudges,
mechanically expressed as the same diminishing-returns shape used
throughout the project (e.g. TECH_BONUS_PER_LEVEL is additive, not
multiplicative, for the same reason)."""


def tick_player_standing(standing: float, recent_events: list[dict], rng, intensity: float = 1.0) -> float:
    """Nudge player_standing one step (called monthly, alongside
    temperament/beliefs). Every recorded `intervention` this month
    (any `/intervene/*` call the engine applied and logged — see
    SimulationEngine._apply_intervention) counts as one touch from
    outside; more touches (up to the cap) read as warmer standing, with
    small noise and mean reversion so this stays a real signal, not a
    monotonically-increasing counter. `recent_events` is the same
    recent_events(conn, limit=...) shape used by tick_temperament."""
    touches = min(PLAYER_STANDING_MAX_EVENTS_COUNTED, sum(
        1 for e in recent_events if e.get("category") == "intervention"
    ))
    step = (rng.uniform(-TEMPERAMENT_STEP_MAX, TEMPERAMENT_STEP_MAX) + touches * PLAYER_STANDING_STEP_PER_INTERVENTION) * intensity
    return clamp(standing * PLAYER_STANDING_MEAN_REVERSION + step, -1.0, 1.0)

# --- cross-settlement relations: a settlement's own read of its sister ----
# --- settlements, seeded at fission and nudged by cross-settlement talk ---

RELATION_SEED_BASE = 0.3
"""Starting affinity a fresh fission creates between origin and daughter
— warm by default (a peaceful split, not an exile): the two communities
were one village a moment before, so indifference (0.0) would undersell
how recently they were the same people."""

RELATION_SEED_TEMPERAMENT_WEIGHT = 0.2
"""The origin settlement's `temperament` at the moment of fission colors
the seed a little further — a fission launched from a settlement in a
sour mood starts its daughter relationship somewhat cooler than one
launched from a settlement doing well, without ever flipping the base
warmth negative on its own (temperament is bounded -1..1, so the
adjustment is bounded -0.2..+0.2)."""

RELATION_STEP_MAX = 0.02
RELATION_MEAN_REVERSION = 0.98
"""Slower decay than temperament's 0.97 — a between-settlement
relationship, built from rarer direct contact (cross-settlement
dialogue, not a monthly settlement-wide mood roll), should drift back
toward neutral more slowly than the village's own internal weather."""

RELATION_DIALOGUE_NUDGE_SCALE = 1.0
"""Multiplies `DIALOGUE_SENTIMENT_DELTA` (agent.py, +-0.05/warm-tense)
when a colocated dialogue pair belongs to two different settlements —
the same per-exchange nudge magnitude as an individual `Agent.
relationships` nudge, reused rather than a bespoke constant so a
cross-settlement encounter counts for exactly as much as any other
one. See SimulationEngine._apply_pending_dialogue_results."""


def tick_relation(value: float, rng, intensity: float = 1.0) -> float:
    """Nudge one cross-settlement relation value one step (called
    monthly per settlement pair with a recorded relation, alongside
    temperament/player_standing) — pure mean-reversion plus noise, no
    fortune-category input like temperament: a between-settlement
    relationship is driven by recorded direct contact (fission origin,
    cross-settlement dialogue), not the settlement's own general luck.
    `intensity` is `Config.phase_g_intensity`, same convention as
    `tick_temperament`/`tick_player_standing` — 0.0 holds it flat."""
    step = rng.uniform(-RELATION_STEP_MAX, RELATION_STEP_MAX) * intensity
    return clamp(value * RELATION_MEAN_REVERSION + step, -1.0, 1.0)


def seed_relation(origin_temperament: float, rng) -> float:
    """Starting mutual affinity between a fission's origin and daughter
    settlement — see RELATION_SEED_BASE/RELATION_SEED_TEMPERAMENT_WEIGHT.
    A small independent random jitter keeps every fission from seeding
    an identical value."""
    jitter = rng.uniform(-0.05, 0.05)
    return clamp(RELATION_SEED_BASE + origin_temperament * RELATION_SEED_TEMPERAMENT_WEIGHT + jitter, -1.0, 1.0)


RELATION_MARKET_INFLUENCE = 0.1
"""Max swing from `market_relation_factor` at a fully warm (+1.0) or
fully cold (-1.0) average relation — a 10% price nudge, the same order
of magnitude as a single invention's TECH_BONUS_PER_LEVEL (0.15) but
deliberately a touch smaller since this is ambient/systemic rather than
an earned settlement achievement."""


def market_relation_factor(settlement: "Settlement") -> float:
    """Small multiplicative nudge to this settlement's own market prices
    from its average standing with named sister settlements — a
    regional trade-network effect: a settlement on generally warm terms
    with the settlements it split from/alongside sees modestly better
    prices (trade flows more easily), cold terms modestly worse.
    Deliberately small and centered on 1.0, same "never dominant" shape
    as every other Phase G nudge (temperament's own influence on
    invention/predator/migrant chances). Returns 1.0 (no effect) for a
    settlement with no recorded relations yet."""
    values = list(settlement.relations.values())
    if not values:
        return 1.0
    avg = sum(values) / len(values)
    return 1.0 + avg * RELATION_MARKET_INFLUENCE

# --- Phase E3: inventions (tech-tier unlocks) -------------------------------

TECH_BONUS_PER_LEVEL = 0.15
"""Multiplicative bonus per invention, applied to construction/repair
work and to cultivated-food yield (farm harvest, granary stock/withdraw)
— NOT wild foraging, which is deliberately untouched by "technique." A
settlement with 3 inventions works/harvests/stores at 1.45x baseline.
Uncapped: inventions are meant to be rare (see INVENTION_CHANCE_PER_SEASON),
so runaway compounding is self-limiting in practice. See
docs/DECISIONS.md, E3."""

INVENTION_CURRENCY_THRESHOLD = 10.0
INVENTION_MATERIALS_FRACTION = 0.5
"""A settlement is "prosperous" enough to invent something when its
currency or materials stockpile clears one of these bars — inventions
are a product of surplus, not survival. Checked at the same `season_end`
cadence as traditions (Population.tick -> SimulationEngine), one
independent roll each. See docs/DECISIONS.md, E3."""

INVENTION_CHANCE_PER_SEASON = 0.2
"""Rolled once per season (was once per year at 0.5 — moved for the
same real-365-day-calendar reason as every other season/year-gated LLM
job, see docs/DECISIONS.md "cadence decoupling" pass) for a prosperous,
named settlement. Raised 0.15 -> 0.2 (v0.44.0) after a live report of
never observing era advancement (industrial -> electrical -> modern ->
digital, see era_for_tech_level/ERA_TECH_THRESHOLDS below) in practice
— at 0.15 and the steep tech_level thresholds, reaching `electrical`
took ~5 in-game years on average and `digital` ~20, plausibly longer
than most live sessions actually run. 0.2 brings that down to roughly
~3.75/~15 years — still a genuine long-run milestone (the era
thresholds themselves are untouched), just observable within a more
realistic play/observation session. The INVENTION_CURRENCY_THRESHOLD/
INVENTION_MATERIALS_FRACTION prosperity gate below was also an
incidental beneficiary of the v0.43.2 HUT-decay/crowding fixes, which
reduced how often a settlement's materials crash near the population
cap — a settlement that clears the prosperity bar more reliably now
also rolls for inventions more reliably, on top of this direct chance
increase. Deliberately still rare — four independent seasonal rolls at
0.2 give ~59% annual invention odds when prosperous (was ~48% at 0.15),
not a fast unlock. See docs/DECISIONS.md, "population control: disease"
and "era progression" pass.

0.15 was originally chosen so four independent seasonal rolls
reproduce roughly the pre-real-calendar annual rate (1-(1-0.15)^4 ~=
0.48 ~= the old 0.5), deliberately rare so an invention stays a notable
event, not
a formality."""

# --- collective behaviour: festivals ----------------------------------------

FESTIVAL_HUNGER_GATE = 0.5
"""A settlement whose average hunger is above this can't hold a festival
— gated on wellbeing, not wealth (contrast INVENTION_CURRENCY_THRESHOLD),
so a starving village never celebrates while people are suffering."""

FESTIVAL_CHANCE_PER_MONTH = 0.13
"""Rolled once per month (was once per season at 0.35 — moved for the
same real-calendar reason as every other season/year-gated LLM job) for
a named, well-fed settlement. 0.13 was chosen so three independent
monthly rolls reproduce roughly the original seasonal rate
(1-(1-0.13)^3 ~= 0.34 ~= the old 0.35)."""

FESTIVAL_RELATIONSHIP_BOOST = 0.1
"""One-time relationship nudge applied to every currently-colocated pair
of awake agents when a festival is held — the mechanical payoff of
"the village gathers" (see Population.hold_festival), distinct from the
much smaller per-tick passive colocation gain."""

CULTURE_EFFECT_STEP = 0.06
CULTURE_EFFECT_MAX_STACKS = 4
"""Each tradition carrying a mechanical influence (see
llm/culture.TRADITION_INFLUENCES) adds one stack to its category in
`Settlement.culture_effects`; `culture_effect_multiplier` turns stacks
into 1.0 + STEP x min(stacks, MAX_STACKS) — at most a 1.24x lever, so
accumulated culture is a real, visible tilt on how this particular
village works (its festivals bond deeper, or its harvests stretch
further, or its griefs cut less) without ever dominating the underlying
mechanics. Bounded stacking is the same diminishing-returns discipline
as PLAYER_STANDING_MAX_EVENTS_COUNTED."""


def culture_effect_multiplier(culture_effects: dict, influence: str) -> float:
    """1.0 when the village has no traditions of that influence."""
    stacks = min(int(culture_effects.get(influence, 0)), CULTURE_EFFECT_MAX_STACKS)
    return 1.0 + CULTURE_EFFECT_STEP * stacks


SHRINE_FESTIVAL_BOOST_MULTIPLIER = 1.5
"""A festival's FESTIVAL_RELATIONSHIP_BOOST is multiplied by this for
any pair colocated on a standing SHRINE's tile when the festival is
held — a shrine gives the village's own invented culture somewhere to
gather that measurably deepens the bond, not just flavor text. See
Population.hold_festival, docs/DECISIONS.md, "culture-specific building
types" pass."""


@dataclass
class Building:
    id: int
    x: int
    y: int
    kind: BuildingKind = BuildingKind.HUT
    stage: BuildingStage = BuildingStage.UNDER_CONSTRUCTION
    progress: float = 0.0
    """0..1, meaningful while UNDER_CONSTRUCTION."""
    condition: float = 1.0
    """0..1, meaningful while STANDING (and while decaying toward RUINED)."""
    ruined_ticks: int = 0
    """Ticks spent as a ruin so far — see RUIN_REMOVAL_TICKS."""
    stored_food: float = 0.0
    """0..GRANARY_CAPACITY, meaningful only for a STANDING GRANARY."""
    owner_agent_id: int | None = None
    """H4 (docs/ROADMAP.md "Phase H"): the agent this building belongs
    to, or None for a commons building (every kind except HUT, and any
    HUT founded before this field existed). Only HUTs are personally
    owned in v1 — a home is the natural first case of "property," while
    granaries/workshops/schools/etc. are deliberately kept communal,
    matching how they already behave mechanically (any awake agent can
    use a granary or staff a workshop, ownership would change nothing
    there yet). Set at founding (`Population._maybe_start_construction`)
    and reassigned to a living heir on the owner's death — see H7,
    `Population._apply_deaths`."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "kind": self.kind.value,
            "stage": self.stage.value,
            "progress": round(self.progress, 4),
            "condition": round(self.condition, 4),
            "ruined_ticks": self.ruined_ticks,
            "stored_food": round(self.stored_food, 4),
            "owner_agent_id": self.owner_agent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Building":
        return cls(
            id=data["id"],
            x=data["x"],
            y=data["y"],
            kind=BuildingKind(data.get("kind", BuildingKind.HUT.value)),
            stage=BuildingStage(data["stage"]),
            progress=data["progress"],
            condition=data["condition"],
            ruined_ticks=data.get("ruined_ticks", 0),
            stored_food=data.get("stored_food", 0.0),
            owner_agent_id=data.get("owner_agent_id"),
        )


@dataclass
class SettlementInfrastructure:
    """The physical plant: structures and vehicles, with their id
    spaces. One of the four composed domains `Settlement` now delegates
    to — the in-place split the July 2026 architecture review called
    the prerequisite for ever having multiple settlements (each future
    settlement instantiates its own four sub-objects instead of
    untangling ~25 flat fields under pressure)."""

    buildings: list[Building] = field(default_factory=list)
    next_id: int = 0
    vehicles: list[Vehicle] = field(default_factory=list)
    """Carts and mounts — see settlement/vehicles.py. A separate id
    space from `buildings` since they're a distinct kind of asset."""
    next_vehicle_id: int = 0
    memorials: list[dict] = field(default_factory=list)
    """Graveyard marks (v0.64.0 audit-backlog item): `{x, y, name,
    cause, tick}` appended on every death at the place it happened —
    "history becomes physically visible" applied to people. Rendered
    as small persistent map marks with hover text; capped at
    MEMORIALS_MAX_STORED (oldest graves fade from living memory first,
    the same bounded-memory discipline as every other list here)."""


@dataclass
class SettlementEconomy:
    """Communal stores and human capital."""

    materials: float = 0.0
    """Shared wood/stone stockpile, 0..MATERIALS_CAPACITY — see D8.
    Global to the settlement rather than per-building/per-tile: unlike
    food (which must be consumed near where it's stored), materials are
    fungible and this project has no hauling/transport system."""
    currency: float = 0.0
    """Settlement-wide wealth, 0..CURRENCY_CAPACITY — see D10. Earned
    from surplus and staffed businesses; spent on emergency rations and
    (as of the review-implementation pass) recurring civic upkeep."""
    education_level: float = 0.0
    """0..EDUCATION_CAPACITY, raised by staffed schools/universities —
    see education_invention_bonus."""
    caravans_visited: int = 0
    """Persistent, never-decremented count of caravan events that have
    reached the settlement (llm/caravan.py, SimulationEngine._maybe_
    schedule_caravan) — content-variety/roadmap-gap-closing pass: gates
    MARKET's foundability (a market only makes sense once the town has
    had real outside contact) and is the first counter in this project
    that makes "external settlements and trade" (integration milestone)
    feed back into the building/construction system, not just currency/
    materials and an occasional rumor."""
    market_prices: dict = field(default_factory=dict)
    """good name -> price multiplier, empty (all goods read 1.0) unless
    a MARKET stands — see `tick_market_prices`/MARKET_PRICE_MIN."""
    fish_caught: int = 0
    """Persistent, never-decremented count of meals relieved from a
    FISH resource node (Population._maybe_forage) — same shape as
    `caravans_visited`. Fishing was mechanically real since the
    resource-variety pass but had no visible tally anywhere; this is
    the "make fishing visible" counter, surfaced in the UI's wild-
    resources tile instead of logging a per-catch event (which would
    spam the curated event log at population scale). See
    docs/DECISIONS.md, "fishing visibility.\""""


@dataclass
class SettlementCulture:
    """Identity and accumulated invention: everything the village has
    *become* rather than what it physically owns."""

    name: str = ""
    """Set once, deterministically, the first tick a building of any
    kind is STANDING (see World.tick) — empty until then, meaning "not
    yet a real settlement." See docs/DECISIONS.md, E1."""
    founding_scenario: str = ""
    """The one-time "genesis" LLM call's founding-scenario sentence
    (hearthmind.llm.world_genesis) — the same text whose hash chose the
    world's seed. Empty when `--seed` was passed (genesis skipped)."""
    llm_named: bool = False
    """True once the background LLM naming job has actually resolved
    (real or fallback) and replaced the deterministic placeholder — as
    opposed to `bool(name)`, which goes true the instant the placeholder
    itself is assigned. `SimulationEngine._maybe_schedule_naming` used to
    key entirely off `not stl.name` to decide when to schedule that job,
    which only ever fires the one tick the placeholder is first set; on
    any resume `name` is already non-empty so the job silently never
    (re)schedules and a village can be stuck on its placeholder forever
    (v0.68.0 fix for a live "village never named" report). Persisted so
    a resumed world can tell "never scheduled" apart from "already
    proposed a real name"."""
    era: str = "industrial"
    """One of ERA_ORDER — advances purely as `tech_level` grows (see
    `era_for_tech_level`); gates FACTORY and (via vehicles) AUTOMOBILE."""
    tech_level: int = 0
    """Count of inventions established — see TECH_BONUS_PER_LEVEL, E3."""
    traditions: list[str] = field(default_factory=list)
    """LLM-authored (or fallback) customs, "Name: description" strings
    in the order established — fed back into chronicle and cognition
    prompts. Capped in storage at CULTURE_LIST_MAX_STORED (oldest
    dropped first); See E1."""
    traditions_established: int = 0
    """Total traditions ever established, never decremented — decoupled
    from `len(traditions)` specifically so capping the stored list
    (CULTURE_LIST_MAX_STORED) can't corrupt fallback ordinal naming
    ("Tradition the 14th"). See docs/DECISIONS.md, "aggressive memory
    optimization" pass."""
    culture_effects: dict = field(default_factory=dict)
    """influence category -> stack count, accumulated as traditions
    with a mechanical rider are established (llm/culture.TRADITION_
    INFLUENCES, culture_effect_multiplier) — the aggregate the
    mechanics read, so consumers never re-parse the traditions list."""
    inventions: list[str] = field(default_factory=list)
    """Prosperity-gated tech-tier unlocks, same shape as traditions —
    see docs/DECISIONS.md, E3. `tech_level` above already is a
    persistent established-count (one per invention, never
    decremented), reused as the ordinal-naming source now that this
    list is capped in storage — no separate counter needed."""
    festivals: list[str] = field(default_factory=list)
    """Festivals held, same shape — wellbeing-gated, with a direct
    mechanical effect (FESTIVAL_RELATIONSHIP_BOOST). Capped in storage
    at CULTURE_LIST_MAX_STORED, same as traditions."""
    festivals_held: int = 0
    """Total festivals ever held, never decremented — same decoupling
    rationale as `traditions_established`."""
    beliefs: list[dict] = field(default_factory=list)
    """The village's own accumulated, revisable theories about itself
    (`{subject, belief, confidence, subject_agent_id, ...}`), capped at
    llm/beliefs.MAX_BELIEFS — the concrete expression of "cognition as
    continuous rather than stateless". Not guaranteed correct, exactly
    like a person's own beliefs about their community."""
    place_names: dict = field(default_factory=dict)
    """Named geography (v0.64.0 audit-backlog item): feature key ->
    LLM-authored (or fallback) name, e.g. `{"river": "The Aldwash",
    "lake_0": "Stillmere"}`. Named once per feature by a monthly
    background job once the settlement itself is named; consumed by
    the chronicle prompt and the UI's geography surfaces. A name, once
    given, is permanent — places outlive the people who named them."""
    records: list[dict] = field(default_factory=list)
    """Written artifacts (v0.64.0 audit-backlog item): `{tick, author,
    text}` — letters/records a notable villager leaves behind at death,
    LLM-authored from their own memories/beliefs (fallback assembles
    from the same). Outlives the author: fed into the yearly
    documentary prompt and left as a memory with the heir — the memory-
    beyond-the-8-entry-cap mechanism the roadmap asked for. Capped at
    RECORDS_MAX_STORED."""
    institutions: list["Institution"] = field(default_factory=list)
    """Persistent entities the population organizes into — v1 only
    forms FAMILY institutions, automatically, on a child's birth (H3,
    docs/ROADMAP.md "Phase H"). Lives on Culture rather than a new
    fifth domain: an institution is "part of what the village has
    become," the same category traditions/beliefs already occupy, and
    this avoids a facade-wide passthrough churn for one new list."""
    next_institution_id: int = 0


@dataclass
class SettlementDisposition:
    """The village's mood, its governance instinct, and its relationship
    with the outside hand — the Phase G / town-brain domain."""

    temperament: float = 0.0
    """-1..1, a deterministic bounded random walk nudged monthly by the
    balance of good/ill fortune (`tick_temperament`) — small subtle
    nudges to a few rolls, never labeled "supernatural" anywhere. See
    docs/DECISIONS.md, "World-G follow-up.\""""
    omen_history: list[dict] = field(default_factory=list)
    """Rolling log of past omens (`{tick, omen, subject_name}`), capped
    at OMEN_HISTORY_MAX — future omens may read as recurrences."""
    player_standing: float = 0.0
    """-1..1, how the village has come to feel about being nudged from
    outside at all (`tick_player_standing`) — plumbed through summary(),
    never narrated. See docs/DECISIONS.md, "town's opinion of the
    player" pass."""
    player_influence: list[str] = field(default_factory=list)
    """Queued player "whispers" (POST /intervene/town-brain), consumed
    by the next *successful* town-brain call (retained on fallback)."""
    current_priority: str = ""
    """The town brain's current civic priority — measurably steers
    `choose_building_kind` and settle chance. Empty until the first
    decision. See docs/DECISIONS.md, "LLM-as-brain batch.\""""
    priority_rationale: str = ""
    priority_history: list[dict] = field(default_factory=list)
    """Rolling log of past town-brain decisions, capped at
    PRIORITY_HISTORY_MAX — the UI's Town Brain monologue."""
    relations: dict[int, float] = field(default_factory=dict)
    """Other named settlement id -> affinity, -1..1 — this settlement's
    own (possibly one-sided) read of how it stands with each sister
    settlement, same shape as `Agent.relationships` one level up.
    Seeded at fission (`Population.depart_for_fission`) from the
    departing party's own temperament/ambition, nudged by cross-
    settlement dialogue sentiment (`Population.apply_dialogue`), and
    mean-reverts monthly like `temperament` (`tick_relation`). Feeds a
    market-price modifier (`tick_market_prices`) and colors the "tie"
    a colocated cross-settlement pair's dialogue starts from — the
    "cross-settlement relationships" milestone. See docs/DECISIONS.md."""


class Settlement:
    """The world's one settlement, now a facade over four composed
    domain objects (`infrastructure`, `economy`, `culture`,
    `disposition`) with property passthroughs for every legacy flat
    attribute — the in-place split recommended by the July 2026
    architecture review so the eventual multiple-named-settlements
    refactor becomes "instantiate N of these" instead of untangling a
    ~25-field God object. Serialization (`to_dict`/`from_dict`) and
    every call site's `settlement.materials`-style access are
    deliberately unchanged; new code (and the future multi-settlement
    pass) should prefer the domain objects directly."""

    def __init__(
        self,
        buildings: list[Building] | None = None, _next_id: int = 0,
        materials: float = 0.0, currency: float = 0.0, name: str = "",
        traditions: list[str] | None = None, culture_effects: dict | None = None,
        tech_level: int = 0, inventions: list[str] | None = None,
        festivals: list[str] | None = None, vehicles: list[Vehicle] | None = None,
        _next_vehicle_id: int = 0, education_level: float = 0.0,
        current_priority: str = "", priority_rationale: str = "",
        priority_history: list[dict] | None = None, player_influence: list[str] | None = None,
        era: str = "industrial", founding_scenario: str = "", llm_named: bool = False, temperament: float = 0.0,
        beliefs: list[dict] | None = None, omen_history: list[dict] | None = None,
        player_standing: float = 0.0, traditions_established: int = 0, festivals_held: int = 0,
        institutions: list[Institution] | None = None, next_institution_id: int = 0,
        caravans_visited: int = 0, fish_caught: int = 0, market_prices: dict | None = None,
        relations: dict[int, float] | None = None,
        memorials: list[dict] | None = None, place_names: dict | None = None,
        records: list[dict] | None = None, id: int = 0,
        center_x: int = -1, center_y: int = -1,
    ):
        self.id = id
        """Stable settlement identity (multi-settlement pass, v0.65.0):
        0 is always the founding settlement; daughters take the next
        free id at fission. Agents point home via Agent.settlement_id;
        engine job closures re-resolve targets by this id so a result
        arriving ticks later can't apply to the wrong settlement."""
        self.center_x = center_x
        self.center_y = center_y
        """Nominal heart of the settlement — set at fission for a
        daughter (its chosen founding site); -1/-1 for the founding
        settlement until `center()` lazily backfills it from the
        centroid of its own buildings. Used for fission-site distance,
        migrant assignment, and the map's name labels — nothing
        mechanical pins buildings to it."""
        # Legacy flat-kwarg constructor, kept so from_dict/tests/callers
        # predating the split keep working unchanged.
        self.infrastructure = SettlementInfrastructure(
            buildings=buildings if buildings is not None else [],
            next_id=_next_id,
            vehicles=vehicles if vehicles is not None else [],
            next_vehicle_id=_next_vehicle_id,
            memorials=memorials if memorials is not None else [],
        )
        self.economy = SettlementEconomy(
            materials=materials, currency=currency, education_level=education_level,
            caravans_visited=caravans_visited, fish_caught=fish_caught,
            market_prices=market_prices if market_prices is not None else {},
        )
        self.culture = SettlementCulture(
            name=name, founding_scenario=founding_scenario, llm_named=llm_named, era=era, tech_level=tech_level,
            traditions=traditions if traditions is not None else [],
            traditions_established=traditions_established,
            culture_effects=culture_effects if culture_effects is not None else {},
            inventions=inventions if inventions is not None else [],
            festivals=festivals if festivals is not None else [],
            festivals_held=festivals_held,
            beliefs=beliefs if beliefs is not None else [],
            place_names=place_names if place_names is not None else {},
            records=records if records is not None else [],
            institutions=institutions if institutions is not None else [],
            next_institution_id=next_institution_id,
        )
        self.disposition = SettlementDisposition(
            temperament=temperament,
            omen_history=omen_history if omen_history is not None else [],
            player_standing=player_standing,
            player_influence=player_influence if player_influence is not None else [],
            current_priority=current_priority, priority_rationale=priority_rationale,
            priority_history=priority_history if priority_history is not None else [],
            relations=relations if relations is not None else {},
        )
        self._position_index: dict | None = None
        """(x, y) -> Building cache behind `at()` — never serialized,
        rebuilt lazily whenever `buildings`' length changes (buildings
        are only ever appended or dropped, never moved). See the July
        2026 review's measured scaling costs."""

    # --- legacy flat-attribute passthroughs ---------------------------------
    # One property pair per pre-split field. Deliberately mechanical: the
    # split's value is the four named domain objects existing at all (and
    # being what a future multi-settlement pass instantiates), not in
    # forcing 30+ call sites to churn in the same commit.

    @property
    def buildings(self) -> list[Building]:
        return self.infrastructure.buildings

    @buildings.setter
    def buildings(self, value: list[Building]) -> None:
        self.infrastructure.buildings = value

    @property
    def _next_id(self) -> int:
        return self.infrastructure.next_id

    @_next_id.setter
    def _next_id(self, value: int) -> None:
        self.infrastructure.next_id = value

    @property
    def vehicles(self) -> list[Vehicle]:
        return self.infrastructure.vehicles

    @vehicles.setter
    def vehicles(self, value: list[Vehicle]) -> None:
        self.infrastructure.vehicles = value

    @property
    def _next_vehicle_id(self) -> int:
        return self.infrastructure.next_vehicle_id

    @_next_vehicle_id.setter
    def _next_vehicle_id(self, value: int) -> None:
        self.infrastructure.next_vehicle_id = value

    @property
    def materials(self) -> float:
        return self.economy.materials

    @materials.setter
    def materials(self, value: float) -> None:
        self.economy.materials = value

    @property
    def currency(self) -> float:
        return self.economy.currency

    @currency.setter
    def currency(self, value: float) -> None:
        self.economy.currency = value

    @property
    def education_level(self) -> float:
        return self.economy.education_level

    @education_level.setter
    def education_level(self, value: float) -> None:
        self.economy.education_level = value

    @property
    def caravans_visited(self) -> int:
        return self.economy.caravans_visited

    @caravans_visited.setter
    def caravans_visited(self, value: int) -> None:
        self.economy.caravans_visited = value

    @property
    def fish_caught(self) -> int:
        return self.economy.fish_caught

    @fish_caught.setter
    def fish_caught(self, value: int) -> None:
        self.economy.fish_caught = value

    @property
    def name(self) -> str:
        return self.culture.name

    @name.setter
    def name(self, value: str) -> None:
        self.culture.name = value

    @property
    def founding_scenario(self) -> str:
        return self.culture.founding_scenario

    @founding_scenario.setter
    def founding_scenario(self, value: str) -> None:
        self.culture.founding_scenario = value

    @property
    def llm_named(self) -> bool:
        return self.culture.llm_named

    @llm_named.setter
    def llm_named(self, value: bool) -> None:
        self.culture.llm_named = value

    @property
    def era(self) -> str:
        return self.culture.era

    @era.setter
    def era(self, value: str) -> None:
        self.culture.era = value

    @property
    def tech_level(self) -> int:
        return self.culture.tech_level

    @tech_level.setter
    def tech_level(self, value: int) -> None:
        self.culture.tech_level = value

    @property
    def traditions(self) -> list[str]:
        return self.culture.traditions

    @traditions.setter
    def traditions(self, value: list[str]) -> None:
        self.culture.traditions = value

    @property
    def traditions_established(self) -> int:
        return self.culture.traditions_established

    @traditions_established.setter
    def traditions_established(self, value: int) -> None:
        self.culture.traditions_established = value

    @property
    def culture_effects(self) -> dict:
        return self.culture.culture_effects

    @culture_effects.setter
    def culture_effects(self, value: dict) -> None:
        self.culture.culture_effects = value

    @property
    def inventions(self) -> list[str]:
        return self.culture.inventions

    @inventions.setter
    def inventions(self, value: list[str]) -> None:
        self.culture.inventions = value

    @property
    def festivals(self) -> list[str]:
        return self.culture.festivals

    @festivals.setter
    def festivals(self, value: list[str]) -> None:
        self.culture.festivals = value

    @property
    def festivals_held(self) -> int:
        return self.culture.festivals_held

    @festivals_held.setter
    def festivals_held(self, value: int) -> None:
        self.culture.festivals_held = value

    @property
    def beliefs(self) -> list[dict]:
        return self.culture.beliefs

    @beliefs.setter
    def beliefs(self, value: list[dict]) -> None:
        self.culture.beliefs = value

    @property
    def institutions(self) -> list[Institution]:
        return self.culture.institutions

    @institutions.setter
    def institutions(self, value: list[Institution]) -> None:
        self.culture.institutions = value

    @property
    def next_institution_id(self) -> int:
        return self.culture.next_institution_id

    @next_institution_id.setter
    def next_institution_id(self, value: int) -> None:
        self.culture.next_institution_id = value

    @property
    def memorials(self) -> list[dict]:
        return self.infrastructure.memorials

    @memorials.setter
    def memorials(self, value: list[dict]) -> None:
        self.infrastructure.memorials = value

    @property
    def place_names(self) -> dict:
        return self.culture.place_names

    @place_names.setter
    def place_names(self, value: dict) -> None:
        self.culture.place_names = value

    @property
    def records(self) -> list[dict]:
        return self.culture.records

    @records.setter
    def records(self, value: list[dict]) -> None:
        self.culture.records = value

    @property
    def market_prices(self) -> dict:
        return self.economy.market_prices

    def market_price(self, good: str) -> float:
        """Current price multiplier for a good — 1.0 (flat/no market)
        unless a standing MARKET has discovered a price. See
        `tick_market_prices`."""
        return self.economy.market_prices.get(good, 1.0)

    def add_memorial(self, x: int, y: int, name: str, cause: str, tick: int) -> None:
        """Append a grave mark, oldest pruned past MEMORIALS_MAX_STORED
        — see SettlementInfrastructure.memorials."""
        self.infrastructure.memorials.append(
            {"x": x, "y": y, "name": name, "cause": cause, "tick": tick}
        )
        if len(self.infrastructure.memorials) > MEMORIALS_MAX_STORED:
            del self.infrastructure.memorials[: len(self.infrastructure.memorials) - MEMORIALS_MAX_STORED]

    def add_record(self, tick: int, author: str, text: str) -> None:
        """Append a written artifact, oldest pruned past
        RECORDS_MAX_STORED — see SettlementCulture.records."""
        self.culture.records.append({"tick": tick, "author": author, "text": text})
        if len(self.culture.records) > RECORDS_MAX_STORED:
            del self.culture.records[: len(self.culture.records) - RECORDS_MAX_STORED]

    def family_for(self, agent_id: int) -> Institution | None:
        """The most recently formed FAMILY institution `agent_id` belongs
        to, or None. An agent can accumulate membership in more than one
        family across a lifetime (the one they were born into, then one
        they start with a partner) — "most recent" is the practical
        default for any future consumer (dialogue, inheritance) that
        wants a single answer to "this person's family" rather than the
        full list."""
        matches = [
            inst for inst in self.institutions
            if inst.kind is InstitutionKind.FAMILY and agent_id in inst.member_agent_ids
        ]
        return max(matches, key=lambda inst: inst.founding_tick) if matches else None

    def council(self) -> Institution | None:
        """The settlement's one COUNCIL institution, or None before it
        forms (see COUNCIL_FORMATION_POPULATION_THRESHOLD). Integration-
        milestone helper — town_brain and carrying_capacity both need a
        single answer to "is there an active council, and who's on it"
        rather than each re-filtering `institutions` themselves."""
        return next((inst for inst in self.institutions if inst.kind is InstitutionKind.COUNCIL), None)

    def has_power_plant(self) -> bool:
        """Whether a POWER_PLANT is currently standing — consumed by
        `Population._maybe_run_workshops`/`_maybe_run_factories`
        (income multiplier) and `carrying_capacity` (infrastructure
        term). Integration milestone."""
        return any(
            b.kind is BuildingKind.POWER_PLANT and b.stage is BuildingStage.STANDING
            for b in self.buildings
        )

    def has_market(self) -> bool:
        """Whether a MARKET is currently standing — consumed by
        `SimulationEngine._maybe_schedule_caravan` (better trade terms
        and a higher visit chance). See MARKET_CARAVAN_YIELD_MULTIPLIER."""
        return any(
            b.kind is BuildingKind.MARKET and b.stage is BuildingStage.STANDING
            for b in self.buildings
        )

    @property
    def temperament(self) -> float:
        return self.disposition.temperament

    @temperament.setter
    def temperament(self, value: float) -> None:
        self.disposition.temperament = value

    @property
    def omen_history(self) -> list[dict]:
        return self.disposition.omen_history

    @omen_history.setter
    def omen_history(self, value: list[dict]) -> None:
        self.disposition.omen_history = value

    @property
    def player_standing(self) -> float:
        return self.disposition.player_standing

    @player_standing.setter
    def player_standing(self, value: float) -> None:
        self.disposition.player_standing = value

    @property
    def relations(self) -> dict[int, float]:
        return self.disposition.relations

    @relations.setter
    def relations(self, value: dict[int, float]) -> None:
        self.disposition.relations = value

    def relation_with(self, other_settlement_id: int) -> float:
        """0.0 (neutral, unopinionated) for a settlement this one has no
        relation on record with yet — the common case before fission
        ever happens, or for a sister settlement that's never come up."""
        return self.disposition.relations.get(other_settlement_id, 0.0)

    @property
    def player_influence(self) -> list[str]:
        return self.disposition.player_influence

    @player_influence.setter
    def player_influence(self, value: list[str]) -> None:
        self.disposition.player_influence = value

    @property
    def current_priority(self) -> str:
        return self.disposition.current_priority

    @current_priority.setter
    def current_priority(self, value: str) -> None:
        self.disposition.current_priority = value

    @property
    def priority_rationale(self) -> str:
        return self.disposition.priority_rationale

    @priority_rationale.setter
    def priority_rationale(self, value: str) -> None:
        self.disposition.priority_rationale = value

    @property
    def priority_history(self) -> list[dict]:
        return self.disposition.priority_history

    @priority_history.setter
    def priority_history(self, value: list[dict]) -> None:
        self.disposition.priority_history = value

    def center(self) -> tuple[int, int] | None:
        """See `center_x`'s docstring. None only while a settlement has
        neither an assigned center nor any buildings to infer one from
        (a brand-new world before its first construction)."""
        if self.center_x >= 0 and self.center_y >= 0:
            return (self.center_x, self.center_y)
        if not self.buildings:
            return None
        self.center_x = round(sum(b.x for b in self.buildings) / len(self.buildings))
        self.center_y = round(sum(b.y for b in self.buildings) / len(self.buildings))
        return (self.center_x, self.center_y)

    def living_member_count(self, agents) -> int:
        """How many of `agents` call this settlement home — the routine
        "is this settlement alive / how big is it" query the
        multi-settlement partition asks everywhere."""
        return sum(1 for a in agents if a.settlement_id == self.id)

    # --- queries -------------------------------------------------------------

    def at(self, x: int, y: int) -> Building | None:
        if self._position_index is None or len(self._position_index) != len(self.buildings):
            self._position_index = {(b.x, b.y): b for b in self.buildings}
        return self._position_index.get((x, y))

    def vehicle_at(self, x: int, y: int) -> Vehicle | None:
        for vehicle in self.vehicles:
            if vehicle.x == x and vehicle.y == y:
                return vehicle
        return None

    # --- construction ------------------------------------------------------

    def start_construction(
        self, x: int, y: int, kind: BuildingKind = BuildingKind.HUT, owner_agent_id: int | None = None,
    ) -> Building:
        building = Building(id=self._next_id, x=x, y=y, kind=kind, owner_agent_id=owner_agent_id)
        self._next_id += 1
        self.buildings.append(building)
        self._position_index = None  # explicit invalidation, belt-and-braces beyond at()'s length check
        return building

    def start_vehicle(self, x: int, y: int, kind: VehicleKind = VehicleKind.CART) -> Vehicle:
        vehicle = Vehicle(id=self._next_vehicle_id, x=x, y=y, kind=kind)
        self._next_vehicle_id += 1
        self.vehicles.append(vehicle)
        return vehicle

    # --- tick: weathering, ruin, reclamation ----------------------------------

    def tick(self, weather: WeatherState, season: str = "summer") -> list[tuple[str, str]]:
        """Weather- and season-driven decay of standing buildings into
        ruins, and eventual removal of long-abandoned ruins. Returns
        life-cycle events as (category, description) pairs.
        Construction/repair progress (which needs agent presence) is
        handled separately by Population.tick, since Settlement has no
        agent awareness."""
        events: list[tuple[str, str]] = []
        survivors: list[Building] = []

        weather_harsh = weather.precipitation > 0.4 or weather.wind > 0.5 or weather.is_snowing
        decay = (
            DECAY_PER_TICK_BASE * (DECAY_WEATHER_MULTIPLIER if weather_harsh else 1.0)
            * SEASON_DECAY_MULTIPLIER.get(season, 1.0)
        )

        # Upkeep: civic buildings draw currency; whatever fraction goes
        # unpaid accelerates *civic* decay proportionally — HUTs draw no
        # upkeep (see UPKEEP_PER_CIVIC_BUILDING_PER_TICK) and must not
        # share this penalty. Bug fixed v0.43.2: `civic_decay` used to be
        # applied to every standing building via a single shared `decay`
        # variable, so an unpaid civic bill also accelerated HUT decay —
        # HUTs are the settlement's housing/crowding pressure valve
        # (HUT_CAPACITY), so punishing them for buildings that never drew
        # on them created a self-reinforcing collapse: unpaid upkeep ->
        # huts ruin faster -> housing capacity drops -> more agents
        # crowded -> CROWDING_ENERGY_MULTIPLIER forces more RESTING ->
        # fewer idle agents available to repair anything (`_maybe_repair`
        # needs a colocated non-critically-hungry pair) -> decay keeps
        # winning -> starvation deaths spike. See docs/DECISIONS.md.
        civic_standing = sum(
            1 for b in self.buildings
            if b.stage is BuildingStage.STANDING and b.kind is not BuildingKind.HUT
        )
        upkeep_due = civic_standing * UPKEEP_PER_CIVIC_BUILDING_PER_TICK
        civic_decay = decay
        if upkeep_due > 0:
            paid = min(self.currency, upkeep_due)
            self.currency -= paid
            unpaid_fraction = 1.0 - paid / upkeep_due
            if unpaid_fraction > 0:
                civic_decay = decay * (1.0 + (UPKEEP_UNPAID_DECAY_MULTIPLIER - 1.0) * unpaid_fraction)

        if _native_building_decay_tick is not None:
            # Native fast path (modules 9-10): x/y/kind stay in Python
            # (needed only for event text), the native call does the
            # decay/ruin-threshold/rot arithmetic.
            _bstage_out = {0: BuildingStage.UNDER_CONSTRUCTION, 1: BuildingStage.STANDING, 2: BuildingStage.RUINED}
            _bstage_in = {BuildingStage.UNDER_CONSTRUCTION: 0, BuildingStage.STANDING: 1, BuildingStage.RUINED: 2}
            inputs = [
                (_bstage_in[b.stage], b.condition, b.kind is BuildingKind.HUT, b.ruined_ticks)
                for b in self.buildings
            ]
            results = _native_building_decay_tick(inputs, decay, civic_decay, RUIN_REMOVAL_TICKS)
            for building, (stage, condition, ruined_ticks, removed, just_ruined) in zip(self.buildings, results):
                if removed:
                    events.append(
                        ("building_reclaimed", f"Nature reclaimed the ruins at ({building.x}, {building.y}).")
                    )
                    continue  # dropped from survivors — removed from the world
                building.stage = _bstage_out[stage]
                building.condition = condition
                building.ruined_ticks = ruined_ticks
                if just_ruined:
                    events.append(("building_ruined", f"A structure at ({building.x}, {building.y}) fell into ruin."))
                survivors.append(building)
        else:
            for building in self.buildings:
                if building.stage is BuildingStage.STANDING:
                    building_decay = decay if building.kind is BuildingKind.HUT else civic_decay
                    building.condition = max(0.0, building.condition - building_decay)
                    if building.condition <= 0.0:
                        building.stage = BuildingStage.RUINED
                        events.append(("building_ruined", f"A structure at ({building.x}, {building.y}) fell into ruin."))
                elif building.stage is BuildingStage.RUINED:
                    building.ruined_ticks += 1
                    if building.ruined_ticks >= RUIN_REMOVAL_TICKS:
                        events.append(
                            ("building_reclaimed", f"Nature reclaimed the ruins at ({building.x}, {building.y}).")
                        )
                        continue  # dropped from survivors — removed from the world

                survivors.append(building)

        if len(survivors) != len(self.buildings):
            self._position_index = None  # a ruin was reclaimed — see at()'s cache
        self.buildings = survivors

        vehicle_decay = (
            VEHICLE_DECAY_PER_TICK_BASE * (VEHICLE_DECAY_WEATHER_MULTIPLIER if weather_harsh else 1.0)
            * SEASON_DECAY_MULTIPLIER.get(season, 1.0)
        )
        if _native_vehicle_decay_tick is not None:
            ready_vehicles = [v for v in self.vehicles if v.stage is VehicleStage.READY]
            results = _native_vehicle_decay_tick([v.condition for v in ready_vehicles], vehicle_decay)
            for vehicle, (condition, just_broke) in zip(ready_vehicles, results):
                vehicle.condition = condition
                if just_broke:
                    vehicle.stage = VehicleStage.BROKEN
                    vehicle.assigned_agent_id = None
                    events.append(("vehicle_broken", f"A {vehicle.kind.value} at ({vehicle.x}, {vehicle.y}) broke down."))
        else:
            for vehicle in self.vehicles:
                if vehicle.stage is not VehicleStage.READY:
                    continue
                vehicle.condition = max(0.0, vehicle.condition - vehicle_decay)
                if vehicle.condition <= 0.0:
                    vehicle.stage = VehicleStage.BROKEN
                    vehicle.assigned_agent_id = None
                    noun = vehicle.kind.value
                    events.append(("vehicle_broken", f"A {noun} at ({vehicle.x}, {vehicle.y}) broke down."))

        return events

    def record_priority(self, tick: int, priority: str, rationale: str) -> None:
        """Called alongside setting `current_priority`/`priority_rationale`
        (SimulationEngine._run_town_brain) to also append to the rolling
        `priority_history` — see that field's docstring."""
        self.priority_history.append({"tick": tick, "priority": priority, "rationale": rationale})
        if len(self.priority_history) > PRIORITY_HISTORY_MAX:
            self.priority_history = self.priority_history[-PRIORITY_HISTORY_MAX:]

    def record_omen(self, tick: int, omen: str, subject_name: str = "") -> None:
        """Called alongside logging an omen event (SimulationEngine.
        _run_omen) to also append to the rolling `omen_history` — see
        that field's docstring."""
        self.omen_history.append({"tick": tick, "omen": omen, "subject_name": subject_name})
        if len(self.omen_history) > OMEN_HISTORY_MAX:
            self.omen_history = self.omen_history[-OMEN_HISTORY_MAX:]

    # --- summary -------------------------------------------------------------

    def summary(self) -> dict:
        under_construction = sum(1 for b in self.buildings if b.stage is BuildingStage.UNDER_CONSTRUCTION)
        standing = [b for b in self.buildings if b.stage is BuildingStage.STANDING]
        ruined = sum(1 for b in self.buildings if b.stage is BuildingStage.RUINED)
        avg_condition = sum(b.condition for b in standing) / len(standing) if standing else 0.0
        granaries = [b for b in standing if b.kind is BuildingKind.GRANARY]
        kind_counts = {
            kind.value: sum(1 for b in standing if b.kind is kind)
            for kind in (
                BuildingKind.WORKSHOP, BuildingKind.SCHOOL, BuildingKind.HOSPITAL,
                BuildingKind.UNIVERSITY, BuildingKind.FACTORY, BuildingKind.SHRINE,
                BuildingKind.POWER_PLANT, BuildingKind.MARKET,
            )
        }
        return {
            "id": self.id,
            "center": self.center(),
            "total": len(self.buildings),
            "under_construction": under_construction,
            "standing": len(standing),
            "ruined": ruined,
            "avg_condition": round(avg_condition, 3),
            "granaries": len(granaries),
            "granary_food": round(sum(b.stored_food for b in granaries), 3),
            "granary_capacity": round(len(granaries) * GRANARY_CAPACITY, 3),
            "materials": round(self.materials, 3),
            "materials_capacity": MATERIALS_CAPACITY,
            "currency": round(self.currency, 3),
            "currency_capacity": CURRENCY_CAPACITY,
            "name": self.name,
            "traditions": list(self.traditions),
            "culture_effects": dict(self.culture_effects),
            "tech_level": self.tech_level,
            "inventions": list(self.inventions),
            "festivals": list(self.festivals),
            "vehicles": self._vehicle_summary(),
            "workshops": kind_counts["workshop"],
            "schools": kind_counts["school"],
            "hospitals": kind_counts["hospital"],
            "universities": kind_counts["university"],
            "factories": kind_counts["factory"],
            "shrines": kind_counts["shrine"],
            "power_plants": kind_counts["power_plant"],
            "markets": kind_counts["market"],
            "caravans_visited": self.caravans_visited,
            "fish_caught": self.fish_caught,
            "market_prices": dict(self.market_prices),
            "place_names": dict(self.place_names),
            "records": list(self.records),
            "education_level": round(self.education_level, 3),
            "education_capacity": EDUCATION_CAPACITY,
            "current_priority": self.current_priority,
            "priority_rationale": self.priority_rationale,
            "priority_history": list(self.priority_history),
            "pending_player_whispers": list(self.player_influence),
            "era": self.era,
            "era_description": ERA_DESCRIPTIONS.get(self.era, ""),
            "founding_scenario": self.founding_scenario,
            "llm_named": self.llm_named,
            "beliefs": list(self.beliefs),
            "temperament": round(self.temperament, 3),
            "omen_history": list(self.omen_history),
            "player_standing": round(self.player_standing, 3),
            "relations": {str(k): round(v, 3) for k, v in self.relations.items()},
            "institutions": {
                "total": len(self.institutions),
                "families": sum(1 for i in self.institutions if i.kind is InstitutionKind.FAMILY),
                "councils": sum(1 for i in self.institutions if i.kind is InstitutionKind.COUNCIL),
                "guilds": [i.name for i in self.institutions if i.kind is InstitutionKind.GUILD],
            },
        }

    def infrastructure_report(self) -> list[dict]:
        """Human-readable per-structure condition breakdown — buildings
        and vehicles together, sorted worst-condition-first so the UI's
        telemetry panel surfaces what needs attention. See
        docs/DECISIONS.md, "LLM-as-brain batch.\""""
        rows: list[dict] = []
        for b in self.buildings:
            if b.stage is BuildingStage.UNDER_CONSTRUCTION:
                status, condition = "under construction", round(b.progress, 3)
            elif b.stage is BuildingStage.RUINED:
                status, condition = "ruined", 0.0
            else:
                condition = round(b.condition, 3)
                status = _condition_label(condition)
            rows.append({
                "kind": b.kind.value, "x": b.x, "y": b.y, "condition": condition, "status": status,
                "asset_type": "building",
            })
        for v in self.vehicles:
            if v.stage is VehicleStage.BUILDING:
                status, condition = "under construction", round(v.progress, 3)
            elif v.stage is VehicleStage.BROKEN:
                status, condition = "broken down", 0.0
            else:
                condition = round(v.condition, 3)
                status = _condition_label(condition)
            rows.append({
                "kind": v.kind.value, "x": v.x, "y": v.y, "condition": condition, "status": status,
                "asset_type": "vehicle",
            })
        rows.sort(key=lambda r: r["condition"])
        return rows

    def _vehicle_summary(self) -> dict:
        carts = [v for v in self.vehicles if v.kind is VehicleKind.CART]
        mounts = [v for v in self.vehicles if v.kind is VehicleKind.MOUNT]
        automobiles = [v for v in self.vehicles if v.kind is VehicleKind.AUTOMOBILE]
        rafts = [v for v in self.vehicles if v.kind is VehicleKind.RAFT]
        ready_carts = [v for v in carts if v.stage is VehicleStage.READY]
        ready_mounts = [v for v in mounts if v.stage is VehicleStage.READY]
        ready_automobiles = [v for v in automobiles if v.stage is VehicleStage.READY]
        ready_rafts = [v for v in rafts if v.stage is VehicleStage.READY]
        return {
            "carts_total": len(carts),
            "carts_ready": len(ready_carts),
            "carts_building": sum(1 for v in carts if v.stage is VehicleStage.BUILDING),
            "carts_broken": sum(1 for v in carts if v.stage is VehicleStage.BROKEN),
            "mounts_total": len(mounts),
            "mounts_ready": len(ready_mounts),
            "mounts_building": sum(1 for v in mounts if v.stage is VehicleStage.BUILDING),
            "mounts_broken": sum(1 for v in mounts if v.stage is VehicleStage.BROKEN),
            "mounts_claimed": sum(1 for v in ready_mounts if v.assigned_agent_id is not None),
            "automobiles_total": len(automobiles),
            "automobiles_ready": len(ready_automobiles),
            "automobiles_building": sum(1 for v in automobiles if v.stage is VehicleStage.BUILDING),
            "automobiles_broken": sum(1 for v in automobiles if v.stage is VehicleStage.BROKEN),
            "automobiles_claimed": sum(1 for v in ready_automobiles if v.assigned_agent_id is not None),
            "rafts_total": len(rafts),
            "rafts_ready": len(ready_rafts),
            "rafts_building": sum(1 for v in rafts if v.stage is VehicleStage.BUILDING),
            "rafts_broken": sum(1 for v in rafts if v.stage is VehicleStage.BROKEN),
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "center_x": self.center_x,
            "center_y": self.center_y,
            "buildings": [b.to_dict() for b in self.buildings],
            "next_id": self._next_id,
            "materials": round(self.materials, 4),
            "currency": round(self.currency, 4),
            "name": self.name,
            "traditions": list(self.traditions),
            "traditions_established": self.traditions_established,
            "culture_effects": dict(self.culture_effects),
            "tech_level": self.tech_level,
            "inventions": list(self.inventions),
            "festivals": list(self.festivals),
            "festivals_held": self.festivals_held,
            "vehicles": [v.to_dict() for v in self.vehicles],
            "next_vehicle_id": self._next_vehicle_id,
            "education_level": round(self.education_level, 4),
            "current_priority": self.current_priority,
            "priority_rationale": self.priority_rationale,
            "priority_history": list(self.priority_history),
            "player_influence": list(self.player_influence),
            "era": self.era,
            "founding_scenario": self.founding_scenario,
            "llm_named": self.llm_named,
            "beliefs": list(self.beliefs),
            "temperament": round(self.temperament, 4),
            "omen_history": list(self.omen_history),
            "player_standing": round(self.player_standing, 4),
            "relations": {str(k): round(v, 4) for k, v in self.relations.items()},
            "institutions": [i.to_dict() for i in self.institutions],
            "next_institution_id": self.next_institution_id,
            "caravans_visited": self.caravans_visited,
            "fish_caught": self.fish_caught,
            "market_prices": dict(self.market_prices),
            "memorials": list(self.memorials),
            "place_names": dict(self.place_names),
            "records": list(self.records),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Settlement":
        buildings = [Building.from_dict(b) for b in data["buildings"]]
        vehicles = [Vehicle.from_dict(v) for v in data.get("vehicles", [])]
        return cls(
            buildings=buildings, _next_id=data["next_id"],
            materials=data.get("materials", 0.0), currency=data.get("currency", 0.0),
            name=data.get("name", ""), traditions=list(data.get("traditions", [])),
            # `traditions_established`/`festivals_held` are new (v0.44.1,
            # see CULTURE_LIST_MAX_STORED) — an old snapshot predating
            # them has no truncated history yet, so its list length *is*
            # the correct established-count backfill.
            traditions_established=data.get("traditions_established", len(data.get("traditions", []))),
            culture_effects=dict(data.get("culture_effects", {})),
            tech_level=data.get("tech_level", 0), inventions=list(data.get("inventions", [])),
            festivals=list(data.get("festivals", [])),
            festivals_held=data.get("festivals_held", len(data.get("festivals", []))),
            vehicles=vehicles, _next_vehicle_id=data.get("next_vehicle_id", 0),
            education_level=data.get("education_level", 0.0),
            current_priority=data.get("current_priority", ""),
            priority_rationale=data.get("priority_rationale", ""),
            priority_history=list(data.get("priority_history", [])),
            player_influence=list(data.get("player_influence", [])),
            era=data.get("era", "industrial"),
            founding_scenario=data.get("founding_scenario", ""),
            llm_named=data.get("llm_named", False),
            beliefs=list(data.get("beliefs", [])),
            temperament=data.get("temperament", 0.0),
            omen_history=list(data.get("omen_history", [])),
            player_standing=data.get("player_standing", 0.0),
            relations={int(k): v for k, v in data.get("relations", {}).items()},
            institutions=[Institution.from_dict(i) for i in data.get("institutions", [])],
            next_institution_id=data.get("next_institution_id", 0),
            caravans_visited=data.get("caravans_visited", 0),
            fish_caught=data.get("fish_caught", 0),
            market_prices=dict(data.get("market_prices", {})),
            memorials=list(data.get("memorials", [])),
            place_names=dict(data.get("place_names", {})),
            records=list(data.get("records", [])),
            id=data.get("id", 0),
            center_x=data.get("center_x", -1), center_y=data.get("center_y", -1),
        )
