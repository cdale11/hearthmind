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

from hearthmind.settlement.vehicles import (
    VEHICLE_DECAY_PER_TICK_BASE,
    VEHICLE_DECAY_WEATHER_MULTIPLIER,
    Vehicle,
    VehicleKind,
    VehicleStage,
)
from hearthmind.world.weather import WeatherState


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

SETTLE_CHANCE_PER_TICK = 0.01
"""Rolled only for mature, healthy, colocated (2+) agents standing on a
tile with no existing building — see Population._maybe_start_construction.
Raised from 0.003 (D6): with D4/D5/D6's survival fixes, qualifying pairs
are no longer rare, so the original rate left construction lagging behind
demand. Matches PLANT_CHANCE_PER_TICK's cadence."""

MATURE_WORKER_ONLY = False
"""Whether construction/repair work requires workers to be "mature"
(see agents.agent.MATURITY_TICKS). False: any awake agent present helps —
only *founding* a new building requires maturity (see C1)."""

RUIN_REMOVAL_TICKS = 3000
"""Ticks a ruined building persists (still inspectable) before nature
finishes reclaiming it and it's removed from the world entirely."""

HUT_MATERIALS_COST = 3.0
GRANARY_MATERIALS_COST = 5.0
WORKSHOP_MATERIALS_COST = 4.0
SCHOOL_MATERIALS_COST = 6.0
HOSPITAL_MATERIALS_COST = 8.0
UNIVERSITY_MATERIALS_COST = 10.0
FACTORY_MATERIALS_COST = 14.0
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
}

BUILDING_KIND_BASE_WEIGHTS: dict[str, float] = {
    "hut": 0.42, "granary": 0.23, "workshop": 0.15, "school": 0.12, "hospital": 0.08,
    "factory": 0.10,
}
"""Baseline odds a new civic building is each kind, before
`Settlement.current_priority` (the seasonal "town brain" LLM
decision — see llm/town_brain.py) reweights them. UNIVERSITY is
deliberately excluded: it's an upgrade of an existing SCHOOL, not
founded from this pool. FACTORY is present here but filtered out by
`choose_building_kind` until the settlement's era allows it (see
`era_for_tech_level`) — it's an industrial-era-or-later kind, not
foundable from a settlement's earliest days."""

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
inventions are already rare (INVENTION_CHANCE_PER_YEAR), so reaching
`digital` is a long-run milestone, not a fast unlock."""
ERA_DESCRIPTIONS: dict[str, str] = {
    "industrial": "smokestacks and hand tools",
    "electrical": "the first wired lights and machinery",
    "modern": "motorised tools and mass production",
    "digital": "computing woven into daily civic life",
}

_ERA_UNLOCKS_FACTORY = frozenset({"electrical", "modern", "digital"})
"""FACTORY is foundable from `electrical` onward, not `industrial` —
the settlement starts industrial with only the earlier building kinds
available; a factory represents genuine progress past that baseline."""

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


def choose_building_kind(rng, current_priority: str, era: str = "industrial") -> "BuildingKind":
    """Weighted pick among the foundable civic kinds (not UNIVERSITY,
    which upgrades an existing school instead) — base odds nudged
    toward whatever the settlement's current priority calls for, and
    FACTORY excluded entirely until `era` has advanced past
    `industrial`. Falls back to the unweighted base odds for an
    unrecognized/empty priority (e.g. before the first town-brain
    decision has ever run). See docs/DECISIONS.md, "LLM-as-brain
    batch\" and the real-calendar/genesis-seed follow-up."""
    weights = dict(BUILDING_KIND_BASE_WEIGHTS)
    if era not in _ERA_UNLOCKS_FACTORY:
        weights.pop("factory", None)
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
(see `_ERA_UNLOCKS_FACTORY`)."""

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

TEMPERAMENT_KILL_CHANCE_INFLUENCE = 0.2
"""Fractional nudge to predator-attack lethality from temperament — see
Population._maybe_predator_attack. Same small-magnitude rationale as
TEMPERAMENT_INVENTION_INFLUENCE, applied after the hospital reduction."""


def tick_temperament(temperament: float, recent_events: list[dict], rng) -> float:
    """Nudge temperament one step (called monthly, alongside beliefs —
    see SimulationEngine._maybe_tick_temperament). `recent_events` is
    the same recent_events(conn, limit=...) shape used elsewhere
    (dicts with a "category" key)."""
    good = sum(1 for e in recent_events if e.get("category") in _GOOD_FORTUNE_CATEGORIES)
    ill = sum(1 for e in recent_events if e.get("category") in _ILL_FORTUNE_CATEGORIES)
    fortune = (good - ill) / (good + ill) if (good + ill) else 0.0
    step = rng.uniform(-TEMPERAMENT_STEP_MAX, TEMPERAMENT_STEP_MAX) + fortune * TEMPERAMENT_FORTUNE_WEIGHT
    return max(-1.0, min(1.0, temperament * TEMPERAMENT_MEAN_REVERSION + step))

# --- Phase E3: inventions (tech-tier unlocks) -------------------------------

TECH_BONUS_PER_LEVEL = 0.15
"""Multiplicative bonus per invention, applied to construction/repair
work and to cultivated-food yield (farm harvest, granary stock/withdraw)
— NOT wild foraging, which is deliberately untouched by "technique." A
settlement with 3 inventions works/harvests/stores at 1.45x baseline.
Uncapped: inventions are meant to be rare (see INVENTION_CHANCE_PER_YEAR),
so runaway compounding is self-limiting in practice. See
docs/DECISIONS.md, E3."""

INVENTION_CURRENCY_THRESHOLD = 10.0
INVENTION_MATERIALS_FRACTION = 0.5
"""A settlement is "prosperous" enough to invent something when its
currency or materials stockpile clears one of these bars — inventions
are a product of surplus, not survival. Checked at the same `year_end`
cadence as traditions (Population.tick -> SimulationEngine), one
independent roll each. See docs/DECISIONS.md, E3."""

INVENTION_CHANCE_PER_YEAR = 0.5
"""Rolled once per year for a prosperous, named settlement — deliberately
rare (half the eligible years produce nothing) so an invention stays a
notable event, not a yearly formality."""

# --- collective behaviour: festivals ----------------------------------------

FESTIVAL_HUNGER_GATE = 0.5
"""A settlement whose average hunger is above this can't hold a festival
— gated on wellbeing, not wealth (contrast INVENTION_CURRENCY_THRESHOLD),
so a starving village never celebrates while people are suffering."""

FESTIVAL_CHANCE_PER_SEASON = 0.35
"""Rolled once per season (more frequent than yearly traditions/
inventions, matching the seasonal cadence of the chronicle) for a named,
well-fed settlement."""

FESTIVAL_RELATIONSHIP_BOOST = 0.1
"""One-time relationship nudge applied to every currently-colocated pair
of awake agents when a festival is held — the mechanical payoff of
"the village gathers" (see Population.hold_festival), distinct from the
much smaller per-tick passive colocation gain."""


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
        )


@dataclass
class Settlement:
    """All buildings in the world. Named distinctly from any per-agent
    concept to leave room for a future named-settlement/culture layer
    (Phase E) grouping buildings without a confusing rename here."""

    buildings: list[Building] = field(default_factory=list)
    _next_id: int = 0
    materials: float = 0.0
    """Shared wood/stone stockpile, 0..MATERIALS_CAPACITY — see D8. Global
    to the settlement rather than per-building/per-tile: unlike food
    (which must be consumed near where it's stored), materials are
    fungible and this project has no hauling/transport system to move
    them tile-by-tile."""
    currency: float = 0.0
    """Settlement-wide wealth, 0..CURRENCY_CAPACITY — see D10. Generated
    from food/materials surplus that would otherwise be wasted at
    capacity; spent on emergency food when a granary's own stock runs
    out. Settlement-wide for the same reason as `materials`: no
    per-agent wallet/inventory system exists."""
    name: str = ""
    """Set once, deterministically, the first tick a building of any kind
    is STANDING (see World.tick) — empty until then, meaning "not yet a
    real settlement." See docs/DECISIONS.md, E1."""
    traditions: list[str] = field(default_factory=list)
    """LLM-authored (or deterministic-fallback) customs invented once per
    year once the settlement is named — "Name: description" strings, in
    the order established. Generational memory, and fed back into both
    future chronicle entries and per-agent cognition prompts. See E1."""
    tech_level: int = 0
    """Count of inventions established — see `inventions` and
    TECH_BONUS_PER_LEVEL. See docs/DECISIONS.md, E3."""
    inventions: list[str] = field(default_factory=list)
    """LLM-authored (or deterministic-fallback) tech-tier unlocks, "Name:
    description" strings, in the order established — a rarer, prosperity-
    gated sibling of `traditions`. See docs/DECISIONS.md, E3."""
    festivals: list[str] = field(default_factory=list)
    """LLM-authored (or deterministic-fallback) festivals held, "Name:
    description" strings, in the order held — a wellbeing-gated,
    seasonal-cadence sibling of `traditions`/`inventions`, with a direct
    mechanical effect (see FESTIVAL_RELATIONSHIP_BOOST,
    Population.hold_festival) rather than being purely narrative."""
    vehicles: list[Vehicle] = field(default_factory=list)
    _next_vehicle_id: int = 0
    """Carts and mounts — see settlement/vehicles.py. A separate id space
    from `buildings` since they're a distinct kind of asset."""
    education_level: float = 0.0
    """0..EDUCATION_CAPACITY, raised by staffed schools/universities —
    see education_invention_bonus."""
    current_priority: str = ""
    """One of "growth"/"food"/"commerce"/"education"/"health"/"defense",
    set by the seasonal "town brain" LLM decision (llm/town_brain.py) —
    empty until the first decision runs. Measurably steers
    `choose_building_kind`, not just narration. See docs/DECISIONS.md,
    "LLM-as-brain batch.\""""
    priority_rationale: str = ""
    """One-line LLM-authored (or deterministic-fallback) reason for
    `current_priority` — shown in the UI alongside the priority itself."""
    player_influence: list[str] = field(default_factory=list)
    """Short text "whispers" queued via POST /intervene/town-brain,
    consumed (and cleared) by the next town-brain prompt — the
    deliberately subtle channel for player influence on the LLM brain.
    See docs/DECISIONS.md, "LLM-as-brain batch.\""""
    era: str = "industrial"
    """One of ERA_ORDER — a settlement starts industrial and advances
    as `tech_level` grows (see `era_for_tech_level`,
    SimulationEngine._maybe_advance_era). Gates the FACTORY building
    kind; also shown in the UI and folded into narrative prompts as
    period flavor. See docs/DECISIONS.md, real-calendar/genesis-seed
    follow-up."""
    founding_scenario: str = ""
    """The one-time "genesis" LLM call's founding-scenario sentence
    (see hearthmind.llm.world_genesis) — the same text whose hash chose
    this world's seed. Empty for worlds created before this existed, or
    when `--seed` was passed explicitly (genesis is skipped)."""
    temperament: float = 0.0
    """-1 (a run of ill fortune) .. 1 (a run of good fortune), a
    deterministic bounded random walk nudged monthly by the recent
    balance of good/ill events (see `tick_temperament`). Applies small,
    deliberately subtle nudges to a few existing rolls (invention
    chance, predator-attack lethality) and is the substrate `llm/
    omens.py` narrates ambiguous, never-explained flavor events from.
    Never labeled "supernatural" in any UI text — see docs/DECISIONS.md,
    "World-G follow-up.\""""
    beliefs: list[dict] = field(default_factory=list)
    """The village's own accumulated, LLM-formed (or deterministic-
    fallback) theories about itself — people, families, traditions,
    politics, economy, recurring patterns, outside influence. Each is
    `{subject, belief, confidence, formed_tick, revised_tick,
    revision_count}`. Formed/revised monthly (see llm/beliefs.py,
    SimulationEngine._maybe_schedule_beliefs) and fed back into future
    town-brain/chronicle prompts as accumulated context — the concrete
    expression of "cognition as continuous rather than stateless."
    Capped at MAX_BELIEFS; not guaranteed correct, exactly like a
    person's own beliefs about their community."""

    # --- queries -------------------------------------------------------------

    def at(self, x: int, y: int) -> Building | None:
        for building in self.buildings:
            if building.x == x and building.y == y:
                return building
        return None

    def vehicle_at(self, x: int, y: int) -> Vehicle | None:
        for vehicle in self.vehicles:
            if vehicle.x == x and vehicle.y == y:
                return vehicle
        return None

    # --- construction ------------------------------------------------------

    def start_construction(self, x: int, y: int, kind: BuildingKind = BuildingKind.HUT) -> Building:
        building = Building(id=self._next_id, x=x, y=y, kind=kind)
        self._next_id += 1
        self.buildings.append(building)
        return building

    def start_vehicle(self, x: int, y: int, kind: VehicleKind = VehicleKind.CART) -> Vehicle:
        vehicle = Vehicle(id=self._next_vehicle_id, x=x, y=y, kind=kind)
        self._next_vehicle_id += 1
        self.vehicles.append(vehicle)
        return vehicle

    # --- tick: weathering, ruin, reclamation ----------------------------------

    def tick(self, weather: WeatherState) -> list[tuple[str, str]]:
        """Weather-driven decay of standing buildings into ruins, and
        eventual removal of long-abandoned ruins. Returns life-cycle
        events as (category, description) pairs. Construction/repair
        progress (which needs agent presence) is handled separately by
        Population.tick, since Settlement has no agent awareness."""
        events: list[tuple[str, str]] = []
        survivors: list[Building] = []

        weather_harsh = weather.precipitation > 0.4 or weather.wind > 0.5 or weather.is_snowing
        decay = DECAY_PER_TICK_BASE * (DECAY_WEATHER_MULTIPLIER if weather_harsh else 1.0)

        for building in self.buildings:
            if building.stage is BuildingStage.STANDING:
                building.condition = max(0.0, building.condition - decay)
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

        self.buildings = survivors

        vehicle_decay = VEHICLE_DECAY_PER_TICK_BASE * (VEHICLE_DECAY_WEATHER_MULTIPLIER if weather_harsh else 1.0)
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
                BuildingKind.UNIVERSITY, BuildingKind.FACTORY,
            )
        }
        return {
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
            "tech_level": self.tech_level,
            "inventions": list(self.inventions),
            "festivals": list(self.festivals),
            "vehicles": self._vehicle_summary(),
            "workshops": kind_counts["workshop"],
            "schools": kind_counts["school"],
            "hospitals": kind_counts["hospital"],
            "universities": kind_counts["university"],
            "factories": kind_counts["factory"],
            "education_level": round(self.education_level, 3),
            "education_capacity": EDUCATION_CAPACITY,
            "current_priority": self.current_priority,
            "priority_rationale": self.priority_rationale,
            "era": self.era,
            "era_description": ERA_DESCRIPTIONS.get(self.era, ""),
            "founding_scenario": self.founding_scenario,
            "beliefs": list(self.beliefs),
            "temperament": round(self.temperament, 3),
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
        ready_carts = [v for v in carts if v.stage is VehicleStage.READY]
        ready_mounts = [v for v in mounts if v.stage is VehicleStage.READY]
        ready_automobiles = [v for v in automobiles if v.stage is VehicleStage.READY]
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
        }

    # --- (de)serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "buildings": [b.to_dict() for b in self.buildings],
            "next_id": self._next_id,
            "materials": round(self.materials, 4),
            "currency": round(self.currency, 4),
            "name": self.name,
            "traditions": list(self.traditions),
            "tech_level": self.tech_level,
            "inventions": list(self.inventions),
            "festivals": list(self.festivals),
            "vehicles": [v.to_dict() for v in self.vehicles],
            "next_vehicle_id": self._next_vehicle_id,
            "education_level": round(self.education_level, 4),
            "current_priority": self.current_priority,
            "priority_rationale": self.priority_rationale,
            "player_influence": list(self.player_influence),
            "era": self.era,
            "founding_scenario": self.founding_scenario,
            "beliefs": list(self.beliefs),
            "temperament": round(self.temperament, 4),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Settlement":
        buildings = [Building.from_dict(b) for b in data["buildings"]]
        vehicles = [Vehicle.from_dict(v) for v in data.get("vehicles", [])]
        return cls(
            buildings=buildings, _next_id=data["next_id"],
            materials=data.get("materials", 0.0), currency=data.get("currency", 0.0),
            name=data.get("name", ""), traditions=list(data.get("traditions", [])),
            tech_level=data.get("tech_level", 0), inventions=list(data.get("inventions", [])),
            festivals=list(data.get("festivals", [])),
            vehicles=vehicles, _next_vehicle_id=data.get("next_vehicle_id", 0),
            education_level=data.get("education_level", 0.0),
            current_priority=data.get("current_priority", ""),
            priority_rationale=data.get("priority_rationale", ""),
            player_influence=list(data.get("player_influence", [])),
            era=data.get("era", "industrial"),
            founding_scenario=data.get("founding_scenario", ""),
            beliefs=list(data.get("beliefs", [])),
            temperament=data.get("temperament", 0.0),
        )
