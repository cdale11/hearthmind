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
from hearthmind.agents.agent import EMOTION_ANGER, EMOTION_FEAR, EMOTION_GRIEF, EMOTION_JOY
from hearthmind.settlement.institutions import Institution, InstitutionKind
from hearthmind.settlement.district import District
from hearthmind.world.memetics import find_near_duplicate
from hearthmind.settlement.vehicles import (
    VEHICLE_DECAY_CATALYST_SCALE,
    VEHICLE_DECAY_PER_TICK_BASE,
    Vehicle,
    VehicleKind,
    VehicleStage,
)
from hearthmind.world.weather import WeatherState
from hearthmind.world.layout_grammar import settlement_layout_style
from hearthmind.world.terrain_evolution import apply_ruin_scar

try:
    from hearthmind._native import building_decay_tick as _native_building_decay_tick
    from hearthmind._native import vehicle_decay_tick as _native_vehicle_decay_tick
    from hearthmind._native import bounded_random_walk_step as _native_bounded_random_walk_step
except ImportError:
    _native_building_decay_tick = None
    _native_vehicle_decay_tick = None
    _native_bounded_random_walk_step = None
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
    PASTURE = "pasture"
    """Animal husbandry (v0.86.7, explicit user direction — a deliberate
    food source distinct from wild grazer hunting): once standing,
    passively produces a small trickle of food into its own `stored_
    food` regardless of staffing (herds tend themselves, slowly), boosted
    substantially by awake, well-fed agents present tending it — same
    "presence-driven production" shape WORKSHOP/FACTORY use for currency,
    applied to food. Withdrawable by hungry agents exactly like a
    GRANARY (see `Population._maybe_forage`'s cultivated-food-source
    tier). See PASTURE_CAPACITY/PASTURE_PASSIVE_YIELD_PER_TICK/
    PASTURE_TENDED_YIELD_PER_TICK."""
    HATCHERY = "hatchery"
    """Fish husbandry/aquaculture (v0.86.7) — same shape as PASTURE, but
    only enters the foundable pool at a water-adjacent site (see
    `choose_building_kind`'s `water_adjacent` gate, the same check RAFT/
    BRIDGE already use), distinct from the existing wild FISH resource-
    node forage mechanic (`world/resources.py`) — this is a deliberate,
    invested food source a settlement chooses to build, not an
    opportunistic wild catch. See HATCHERY_CAPACITY/HATCHERY_PASSIVE_
    YIELD_PER_TICK/HATCHERY_TENDED_YIELD_PER_TICK."""
    DOCK = "dock"
    """v0.87.42 water-infrastructure batch (live report: "water is an
    untapped resource"): a real trade port, not a decorative waterside
    building — staffed presence generates settlement currency the same
    "presence-driven production" shape WORKSHOP already uses (see
    DOCK_INCOME_PER_TICK), and it's the site BOAT vehicles are founded
    from (`Population._maybe_start_vehicle`). Only enters the foundable
    pool at a water-adjacent site, same `water_adjacent` gate RAFT/
    BRIDGE/HATCHERY already use."""
    OIL_RIG = "oil_rig"
    """Same water-infrastructure batch: offshore extraction, the
    genuinely industrial-scale water-based income building (double
    DOCK's rate, same ratio FACTORY has over WORKSHOP — see OIL_RIG_
    INCOME_PER_TICK). Only enters the foundable pool once BOTH the site
    is water-adjacent AND the settlement's era has advanced past
    `industrial` (`_ERA_UNLOCKS_ELECTRICAL`, the same gate FACTORY/
    POWER_PLANT use) — offshore rigs are a real industrial-tech
    concept, not a founding-day structure."""
    BRIDGE = "bridge"
    """The true-water-transport gap CLAUDE.md flagged as needing "its
    own pathing-system pass, not a bolt-on": unlike RAFT (a passive
    fishing-yield bonus that never touches passability), a STANDING
    BRIDGE's spanned water tiles (`Building.bridge_span`) actually
    become walkable — see `Population._is_walkable`'s `bridge_tiles`
    parameter. Founded like a vehicle (`Population._maybe_start_
    bridge`), not through the normal `choose_building_kind` civic-
    priority pool: a colocated group standing on a shore tile
    (water-adjacent, same gate RAFT uses) triggers a search
    (`Population._find_bridge_span`) for the nearest opposite shore
    reachable via a bounded run of water tiles (`BRIDGE_MAX_SPAN`),
    and only founds if one exists. `Building.x`/`y` stays the land
    anchor tile (so agent-pathed construction/repair/decay all work
    unchanged — builders walk to solid ground, never onto the water
    itself); `bridge_span` is the ordered water-tile path the bridge
    covers once STANDING. Bridges are physical infrastructure on the
    shared map, not settlement-private — every settlement's STANDING
    bridges pool into one global passability set, the same "physical
    structure anyone can use" shape roads already have. See
    docs/DECISIONS.md, "bridges/water-crossing pathing."
    """
    FORGE = "forge"
    """v1 audit fix (full historical era ladder): the bronze_age+ economic
    building, same "staffed presence converts into settlement currency"
    shape WORKSHOP already established — a smithy is this era's business,
    not yet the industrial-scale WORKSHOP/FACTORY. Foundable once the
    settlement's era has advanced past `stone_age` (see `_ERA_UNLOCKS_
    BRONZE`). Staffed preferentially by the new BLACKSMITH occupation.
    See FORGE_INCOME_PER_TICK, `Population._maybe_run_forges`."""
    LIBRARY = "library"
    """v1 audit fix: the classical+ knowledge building, folded into the
    same education-boost mechanic SCHOOL/UNIVERSITY already use
    (`Population._maybe_run_schools`) rather than a parallel one — a
    library IS this era's schoolhouse, mechanically. Foundable once the
    settlement's era has advanced past `iron_age` (see `_ERA_UNLOCKS_
    CLASSICAL`). Staffed preferentially by the new SCRIBE occupation."""
    SMELTER = "smelter"
    """A13's real ore-reachable reactor (explicit user decision, "New
    BuildingKind defaulting to ore"): `world.materials.BUILDING_
    MATERIALS[SMELTER] = "ore"` is the missing precondition `world.
    chemistry.REACTION_RULES`' `ore + heat -> metal` rule needed — no
    prior `BuildingKind` ever defaulted to ore, so that rule was
    reachable only through `discover_reactions`' query half, never the
    real automatic reactor (`tick_building_reactions`). A standing
    SMELTER genuinely holds raw ore, and (like FORGE) itself carries
    `can_conduct_heat`/`can_burn` in `world.affordances.BUILDING_
    AFFORDANCES` — a furnace supplies its own heat, so a lone SMELTER
    is self-sufficient; it doesn't need a separate FORGE standing to
    eventually convert. Foundable from `bronze_age` onward, same
    `_ERA_UNLOCKS_BRONZE` gate as FORGE — ore smelting is bronze-age
    metallurgy, not a founding-day structure."""


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

DECAY_PER_TICK_BASE = 0.00022
"""Baseline condition lost per tick for a standing building in fair
weather — roughly a full decay from perfect condition over ~4500 ticks
(~47 sim-days at default pacing) with no repair. Halved from the
original 0.0004 (v0.87.13, live report: "everything wears down too
quickly") — the old binary `DECAY_WEATHER_MULTIPLIER=3.0` gate fired
on any of three loose conditions (`precipitation > 0.4 or wind > 0.5
or is_snowing`), which — measured against the real weather distribution
(see world/weather.py's v0.87.12 retune) — covered close to half of
all ticks at full 3x severity, so the EFFECTIVE average decay rate was
much faster than this base number alone suggested. Replaced by
`_weather_decay_catalyst` below: real wear now differentiates by
CAUSE (damp/rot, dry heat/cracking, frost/freeze-thaw, wind/structural)
scaled continuously by actual weather intensity, instead of one flat
multiplier gated on/off. C3's standing principle (docs/DECISIONS.md:
"decay is never zero even in perfect weather") is preserved — this
base rate alone still erodes a building over time with zero weather
input."""

RAIN_ROT_DECAY_WEIGHT = 0.9
DRY_HEAT_CRACK_DECAY_WEIGHT = 0.4
FROST_DECAY_WEIGHT = 0.7
WIND_STRUCTURAL_DECAY_WEIGHT = 0.6
"""v0.87.13 "weather as wear catalysts" (live report: decay was too
fast AND too undifferentiated — every tick applied the same flat
multiplier regardless of what kind of weather was actually happening).
Each weight is the MAXIMUM extra multiplier that catalyst can add at
its most extreme reading (see `_weather_decay_catalyst`) — persistent
damp is the single worst offender for timber/thatch (rot), a real
freeze-thaw cycle close behind (masonry cracking as trapped water
expands), gale-force wind a real but lesser structural stressor, and
dry heat the mildest (only relevant at all in the rare hot-and-dry
band this climate model produces). Deliberately NOT stacked to a
single old-style flat multiplier — a genuinely miserable day (cold,
wet, windy all at once) now compounds several real catalysts rather
than tripping one binary switch, while an ordinary overcast or breezy
day (the majority of ticks under the v0.87.12 weather retune) adds
only a small fraction of any of these, not the old flat 3x."""

SEASON_DECAY_MULTIPLIER = {"winter": 1.15, "autumn": 1.05, "spring": 1.0, "summer": 0.95}
"""Applied on top of `_weather_decay_catalyst`, not instead of it —
narrowed from {1.4, 1.15, 1.0, 0.85} in v0.87.13: the old wide swing
existed specifically to represent "winter's freeze-thaw cycles and
persistent winter damp" as a coarse seasonal AVERAGE, but that's now
captured far more precisely by the real per-tick frost/damp catalysts
above (which already run harder in winter simply because winter
actually has more cold/wet ticks — an emergent, not hardcoded,
seasonal skew). This table now only covers the residual, genuinely
season-specific effect (shorter freeze-thaw-favorable temperature
swings in winter, drier structural timber in summer) that isn't
already priced in by the weather catalysts themselves. A season absent
from this table (shouldn't happen — all four exist) defaults to 1.0.
See docs/DECISIONS.md, "map/UI/ecology follow-up.\""""


def _weather_decay_catalyst(weather: WeatherState) -> float:
    """v0.87.13 "weather as wear catalysts": returns a >=1.0 multiplier
    built from FOUR independent, continuously-scaled failure modes
    instead of one binary "harsh weather" gate — see the *_DECAY_
    WEIGHT constants above for the reasoning behind each weight.
    Diminishing, not multiplicative: each catalyst adds its own share
    on top of 1.0, so a day that's simultaneously wet AND windy
    compounds two real effects rather than double-multiplying into an
    unrealistic spike."""
    from hearthmind.world.weather import (
        CALM_WIND_THRESHOLD, CLEAR_PRECIPITATION_THRESHOLD, LIGHT_RAIN_PRECIPITATION_THRESHOLD,
    )
    span = max(1e-6, LIGHT_RAIN_PRECIPITATION_THRESHOLD - CLEAR_PRECIPITATION_THRESHOLD)
    damp = min(1.0, max(0.0, (weather.precipitation - CLEAR_PRECIPITATION_THRESHOLD) / span))
    dry_heat = min(1.0, max(0.0, (weather.temperature_c - 18.0) / 12.0)) * (1.0 - damp)
    frost = 1.0 if weather.is_snowing else min(1.0, max(0.0, (2.0 - weather.temperature_c) / 8.0))
    gale = min(1.0, max(0.0, (weather.wind - CALM_WIND_THRESHOLD) / max(1e-6, 1.0 - CALM_WIND_THRESHOLD)))
    return (
        1.0
        + RAIN_ROT_DECAY_WEIGHT * damp
        + DRY_HEAT_CRACK_DECAY_WEIGHT * dry_heat
        + FROST_DECAY_WEIGHT * frost
        + WIND_STRUCTURAL_DECAY_WEIGHT * gale
    )

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

FOLKLORE_MAX_STORED = 24
"""Cap on `SettlementCulture.folklore` — Phase K's "folklore
condensation" (docs/VISION-2026-07.md, "Knowledge & Story"), scoped down
to reuse the events log's existing "rumor" category rather than the
vision's fuller per-rumor hops/mutation tracking (deferred — no such
tracking exists yet; see `llm/folklore.py`). Monthly, settlement-scoped,
same call-volume shape as tradition/invention/festival (one bounded job
in the existing rotation, not a new per-agent gate). Deliberately much
smaller than `CULTURE_LIST_MAX_STORED=300` — a village's enduring
legends are meant to read as a curated handful of old tales, not
hundreds; oldest dropped first, same eviction shape as traditions."""

LEGENDS_MAX_STORED = 16
"""Cap on `SettlementCulture.legends` — A21 "Temporal compression,"
first slice (see the field's own docstring). Smaller than `FOLKLORE_
MAX_STORED`: a legend is meant to be rarer and more significant than
an ordinary folk tale (it takes `LEGEND_SUBSYSTEM_THRESHOLD` repeated
noteworthy observations from the SAME subsystem to mint one), so a
settlement realistically accumulates far fewer of them over its
lifetime."""

FOLKLORE_LEGEND_PERSISTENCE_THRESHOLD = 6
"""A21 "Temporal compression," third slice ("unify folklore/legend
pipeline"): how many CONSECUTIVE monthly folklore-job firings must
pass with the current newest `folklore` tale left unsuperseded before
`SimulationEngine._promote_folklore_to_legend` graduates it into
`SettlementCulture.legends` — see `SettlementCulture.folklore_
persistence_count`'s own docstring. Six months (half a year) is
deliberately longer than `RITUAL_PROMOTION_THRESHOLD`'s three: a
ritual only needs to recur, but a tale earning legend status needs to
have genuinely outlasted several real chances to be replaced by
something newer, the actual "temporal compression" signal."""

RITUAL_PROMOTION_THRESHOLD = 3
"""How many times a candidate pattern (a festival held, a death mourned
at a standing shrine) must recur before `SimulationEngine._maybe_
promote_ritual` promotes it from `ritual_signal_counts` into a real
`SettlementCulture.rituals` entry — one or two is coincidence, three is
a pattern. Deliberately small: this is free (no LLM call), so there's
no call-budget reason to make it rare; it just needs to not fire on a
single lucky festival."""

PATTERN_SIGNAL_BELIEF_THRESHOLD = 3
"""Same "one or two is coincidence, three is a pattern" bar as
RITUAL_PROMOTION_THRESHOLD above, for `SettlementCulture.pattern_
signal_counts` — once a settlement's running `dispute_feud`/
`starvation_death` count reaches this, `SimulationEngine._maybe_
schedule_beliefs` folds one extra plain-language "pattern noticed"
sentence into the belief-forming prompt and resets that count (same
consume-and-reset discipline `ritual_signal_counts` already uses), so
the LLM gets a chance to notice and name a recurring hardship instead
of only ever reacting to the single most-recent event."""

LEXICON_MAX_STORED = 6
"""Cap on `SettlementCulture.lexicon` — a village's coined terms are
meant to read as a short, memorable handful, same shape as `laws`."""

LEXICON_MEANING_MERGE_OVERLAP = 0.5
"""A17's shared "compete" step: a newly-coined term whose MEANING
overlaps an already-coined entry's meaning this much is treated as a
second word for the same idea, not a genuinely new one — the earlier
coinage wins, the new one is dropped rather than appended. Distinct
from `validate_coined_term`'s existing exact-TERM duplicate check
(which catches the same word coined twice); this catches two
different words for the same underlying idea."""

LEXICON_MAX_AGE_TICKS = 100_000
"""A17's shared "decay" step: a coined term nobody has reinforced (no
matching or near-duplicate coinage) in this many ticks (~3 years at
the default 15-sim-min tick) quietly falls out of use — distinct from
`LEXICON_MAX_STORED`'s flat count cap, a genuine age-based decay a
small, rarely-refreshed lexicon would otherwise never trigger."""

RECENT_TOPICS_MAX_STORED = 40
"""Cap on `SettlementCulture.recent_topics` — a rolling window wide
enough for `top_topics()` to read as a genuine "what's been talked
about lately" signal (roughly the last several days of core-cast
dialogue) without growing unbounded across a long-running world."""

TOPIC_MERGE_OVERLAP = 0.55
"""A17's shared "compete" step (`world.memetics.find_near_duplicate`):
a freshly-recorded topic whose word overlap against something already
in `recent_topics` clears this bar collapses to the EXISTING phrasing
instead of being tallied as a second, separately-counted entry — "the
tools shortage" and "the town's need for tools" read as the same
recurring topic, not two different ones diluting each other's count.
Doesn't touch `RECENT_TOPICS_MAX_STORED`/`top_topics()`'s own math at
all, only what gets appended."""

LAWS_MAX_STORED = 6
"""Cap on `SettlementCulture.laws` — a village's codified norms are
meant to read as a short, memorable handful (see `laws` docstring),
not an accumulating legal code."""

LAW_SIGNAL_THRESHOLD = 3
"""Occurrence count (in `SettlementCulture.law_signal_counts`) a pattern
must cross before `SimulationEngine._maybe_schedule_laws` will spend a
real LLM call considering whether to codify it — same "recurring, not
a single bad afternoon" discipline as RITUAL_PROMOTION_THRESHOLD/
FAMILY_FEUD_PROMOTION_THRESHOLD."""

VILLAGE_PATTERN_CONVICTION_LAW_THRESHOLD = 0.75
"""C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-2026-07-
22.md's Part C, Tier 3, "change law"): the bar `village_pillar`'s own
standing confidence about a pattern category must clear to genuinely
INITIATE a law proposal on its own, ahead of fresh occurrences
re-accumulating to `LAW_SIGNAL_THRESHOLD`. Distinct from confidence's
existing use as a mere tiebreak in `_maybe_schedule_laws` (which only
ever resolves a tie among categories that already crossed the real
threshold): this lets Village's own accumulated conviction — which can
persist from BEFORE a prior enactment reset the raw occurrence counter
— re-open the question early, "the village hasn't forgotten, even
though the fresh count reset." Still requires at least one real
recent occurrence (never invents hardship from nothing — Body stays
authoritative, see docs/CONSTITUTION.md's priority order); only the
FULL-threshold requirement is what conviction alone can bypass. See
`SimulationEngine._maybe_schedule_laws`."""

RITUAL_MAX_STORED = 12
"""Cap on `SettlementCulture.rituals` — a village's genuinely distinct
recurring practices are meant to read as a short, curated list (there
are currently only two detectable pattern kinds — see
`_detect_ritual_signals` — so this ceiling is generous headroom for
future pattern kinds, not an expected steady-state count)."""

NARRATIVE_THEMES_MAX_STORED = 8
"""Cap on `SettlementCulture.narrative_themes` — Phase M "Narrative
Direction" fires at most once a season (4/year), so this is several
years of history; only the newest entry is ever read as the "current"
theme, the rest is context for the LLM's own next call to notice a
theme shifting or persisting."""

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

INVENTION_KNOWLEDGE_MAX_TRACKED = 20
"""v0.87.15, "knowledge lifecycle" (docs/IDEAS-2026-07-EMERGENCE.md
§7): how many of the most recent `inventions` entries carry live
`invention_knowledge` (knower-tracking, dormancy, rediscovery) — far
below `CULTURE_LIST_MAX_STORED`, deliberately: this is meant to model
FRAGILE, still-narrow knowledge, not the settlement's entire
technological history (which would need every knower tracked forever
for no real payoff — see `SettlementCulture.invention_knowledge`'s
docstring for the scope boundary)."""

INVENTION_REDISCOVERY_CHANCE = 0.35
"""Chance an heir who inherits from the LAST knower of a now-dormant
invention rediscovers it (via family papers/journals, same "heir
memory already does this" mechanism H7 established) — see `Population.
_apply_inheritance`. Below 0.5 so a lost invention staying lost is the
more common, and more narratively interesting, outcome."""

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
PASTURE_MATERIALS_COST = 5.0
"""Same as GRANARY — another cultivated-food-source building, same
civic weight."""
HATCHERY_MATERIALS_COST = 6.0
"""Slightly above PASTURE — founding is also gated by a real site
constraint (water adjacency), reflecting the extra effort of building
at a waterside location."""
DOCK_MATERIALS_COST = 6.0
"""Same as HATCHERY — another water-adjacent-gated civic building."""
OIL_RIG_MATERIALS_COST = 16.0
"""Costlier than FACTORY (14.0) — offshore extraction infrastructure is
a bigger commitment than a land-based factory, matching its higher
income rate."""
FORGE_MATERIALS_COST = 3.5
"""Between HUT (3.0) and WORKSHOP (4.0) — a bronze_age settlement's
first real economic building, cheaper than the industrial-era WORKSHOP
it eventually stands alongside."""
LIBRARY_MATERIALS_COST = 5.5
"""Between GRANARY/SHRINE (5.0) and SCHOOL (6.0) — a classical-era
knowledge building, mechanically SCHOOL's peer."""
SMELTER_MATERIALS_COST = 4.5
"""Between FORGE (3.5) and WORKSHOP (4.0)'s neighbor SHRINE/GRANARY
(5.0) — a bronze_age building, same tier as FORGE, priced a touch
higher since it needs a real sustained-heat commitment (`world.
chemistry.tick_building_reactions`) to pay off, not immediate income."""
BRIDGE_MATERIALS_COST_PER_SPAN_TILE = 2.5
"""Bridges cost scales with how much water they actually cross
(`len(Building.bridge_span)`) rather than a flat price like every other
kind — a one-tile hop across a narrow channel is cheap, a full
BRIDGE_MAX_SPAN crossing is a real commitment (roughly comparable to a
HOSPITAL at max span). See Population._maybe_start_bridge."""
BRIDGE_MIN_MATERIALS_COST = 4.0
"""Floor under BRIDGE_MATERIALS_COST_PER_SPAN_TILE so even a one-tile
span costs a genuine amount, not less than a HUT."""

BRIDGE_CHANCE_PER_TICK = 0.003
"""Slightly rarer than VEHICLE_CHANCE_PER_TICK (0.004) — founding also
requires `Population._find_bridge_span` to actually find a valid
crossing near the colocated group's shore, so the effective rate is
lower still; this is the roll gating whether the (more expensive) span
search runs at all."""
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
    BuildingKind.PASTURE: PASTURE_MATERIALS_COST,
    BuildingKind.HATCHERY: HATCHERY_MATERIALS_COST,
    BuildingKind.DOCK: DOCK_MATERIALS_COST,
    BuildingKind.OIL_RIG: OIL_RIG_MATERIALS_COST,
    BuildingKind.FORGE: FORGE_MATERIALS_COST,
    BuildingKind.LIBRARY: LIBRARY_MATERIALS_COST,
    BuildingKind.SMELTER: SMELTER_MATERIALS_COST,
}

def cheapest_founding_cost() -> float:
    """The lowest `MATERIALS_COST_BY_KIND` entry — the real bar a
    settlement's stockpile has to clear before ANY building can be
    founded at all. Used as the "materials critically low" threshold
    (see `Population.fallback_goal`'s `materials_critical` param and
    `cognition.build_prompt`'s matching grounding line) — a live audit
    finding (P0.3): sinks (repairs, tools, workshop/hospital crafting)
    draw from the same stockpile as founding, and nothing gave GATHER
    real urgency the way hunger/energy already have, so a small
    population's stockpile could sit permanently below even the
    cheapest kind's cost."""
    return min(MATERIALS_COST_BY_KIND.values())


BUILDING_KIND_BASE_WEIGHTS: dict[str, float] = {
    "hut": 0.42, "granary": 0.23, "workshop": 0.15, "school": 0.12, "hospital": 0.08,
    "factory": 0.10, "shrine": 0.07, "power_plant": 0.06, "market": 0.07,
    "pasture": 0.14, "hatchery": 0.10, "dock": 0.09, "oil_rig": 0.07,
    "forge": 0.13, "library": 0.10, "smelter": 0.09,
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

BUILDING_KIND_PILLAR_LEAN_MAX = 1.15
"""Tier 0 (29th site, explicit user decision — a deliberately reopened,
already-tuned system): the maximum multiplier `choose_building_kind`'s
`pillar_lean` can apply to one kind's weight, from `village_pillar.
subject_confidence(kind_value)` — "the village keeps building what it
tends to build," real cultural momentum. Deliberately the SMALLEST of
the three multiplicative steers here (PRIORITY_KIND_BOOST=2.5 for
town_brain's real decided priority, ERA_BRANCH_BOOST=1.35 for the
LLM-authored era character) so a pillar's accumulated lean can nudge
which of several already-eligible kinds gets built, never override
either of the two live-diagnostic-tuned signals above it. `pillar_
lean=None` (the default) reproduces the exact prior weights/RNG-
consumption pattern byte-for-byte — the roll itself is untouched,
only the weights feeding it gain one more multiplicative term."""

_PRIORITY_TO_KIND = {
    "growth": "hut", "food": "granary", "commerce": "workshop",
    "education": "school", "health": "hospital", "defense": "hut",
}
"""Maps a `Settlement.current_priority` value to the `BuildingKind`
value it boosts. "defense" has no dedicated building yet, so it boosts
huts (more shelter, more hands) rather than doing nothing. "food"
boosts GRANARY specifically (storage) rather than PASTURE/HATCHERY
(production) — deliberately kept simple; a priority-driven husbandry
boost would need a second civic-priority value this project doesn't
have yet."""

# --- eras: the town starts in the stone age and advances as it invents -----

ERA_ORDER = (
    "stone_age", "bronze_age", "iron_age", "classical", "medieval",
    "renaissance", "industrial", "electrical", "modern", "digital",
)
"""v1 audit fix (explicit user request: "introduce more intermediate
eras following human history closely" + "make progression to new eras
a bit less harder"): previously four eras (`industrial` through
`digital`), with settlements starting industrial and CLAUDE.md
explicitly noting "no tribal stage." Extended to a full ten-era ladder
spanning a settlement's whole realistic technological history, six new
eras ahead of the original four. `era_for_tech_level_gated` already
walks `ERA_ORDER` generically one step at a time regardless of its
length — no logic change needed there, just a longer tuple."""

ERA_TECH_THRESHOLDS: dict[str, int] = {
    "stone_age": 0, "bronze_age": 1, "iron_age": 2, "classical": 4,
    "medieval": 6, "renaissance": 9, "industrial": 12, "electrical": 15,
    "modern": 19, "digital": 24,
}
"""Cumulative `tech_level` (established inventions) required for each
era — deliberately front-loaded with small, cheap early steps (a young
settlement improvising its first tools/smelting/ironwork should feel
fast and legible) and progressively larger later gaps, same overall
shape as the old 0/3/7/12 spacing but spread across six more rungs so
real progress is visible far more often per the "less harsh" request:
a settlement now reaches SOME new era every ~1-3 inventions on average
across the whole ladder, versus the old scheme's 3-5-invention gaps
with only four milestones total to look forward to. `digital` (24) is
higher in raw count than the old `digital` (12) since it's now the
FINAL rung of ten rather than the fourth of four, but per-era pacing
is faster throughout — see docs/DECISIONS.md for the full worked
before/after comparison this reset was checked against."""
ERA_DESCRIPTIONS: dict[str, str] = {
    "stone_age": "flaked stone tools and a first fire kept alive",
    "bronze_age": "smelted bronze, the first real metal tools",
    "iron_age": "iron tools and weapons, harder-wearing than bronze",
    "classical": "organized civic life, roads, and written record-keeping",
    "medieval": "stone keeps, guilds, and settled feudal order",
    "renaissance": "renewed learning, art, and scientific curiosity",
    "industrial": "smokestacks and hand tools",
    "electrical": "the first wired lights and machinery",
    "modern": "motorised tools and mass production",
    "digital": "computing woven into daily civic life",
}

ERA_HUT_CAPACITY_MULTIPLIER: dict[str, float] = {
    "stone_age": 1.0, "bronze_age": 1.0, "iron_age": 1.0, "classical": 1.05,
    "medieval": 1.1, "renaissance": 1.15, "industrial": 1.0, "electrical": 1.0,
    "modern": 1.3, "digital": 1.6,
}
"""v0.87.43 era-scaled-infrastructure batch (live report: "improve
building/road/infrastructure types with era"): a settlement's own huts
house more people as tech advances — denser building techniques
(multi-story housing, better materials) without needing a new
persisted BuildingKind/schema field, the same "derive from era, don't
store a duplicate flag" shape `era_condition_multiplier`-style helpers
elsewhere use. `modern`/`digital` read as genuinely denser housing
(row houses/apartment blocks) versus `industrial`/`electrical`'s
single-family-cottage baseline (no bonus — matches the FACTORY/
AUTOMOBILE precedent of "real change happens at electrical+/modern+,
not from day one"). See `hut_capacity_multiplier`, `Population.
carrying_capacity`'s housing term, `_housing_pressure`, and the
fission-eligibility housing check — all three read this the same way
CAMP_TOLERANCE/HUT_CAPACITY already are."""


def hut_capacity_multiplier(era: str) -> float:
    """`ERA_HUT_CAPACITY_MULTIPLIER` lookup with a safe default for an
    unrecognized/legacy era string (1.0, the industrial-era baseline)."""
    return ERA_HUT_CAPACITY_MULTIPLIER.get(era, 1.0)


_ERA_UNLOCKS_BRONZE = frozenset(ERA_ORDER[ERA_ORDER.index("bronze_age"):])
"""FORGE is foundable from `bronze_age` onward — computed as a slice of
`ERA_ORDER` (not a hardcoded era-name set like the electrical-era gates
below, which predate this ladder) so it never needs updating if the
ladder is extended again."""

_ERA_UNLOCKS_CLASSICAL = frozenset(ERA_ORDER[ERA_ORDER.index("classical"):])
"""LIBRARY is foundable from `classical` onward — same slice-of-ERA_
ORDER shape as `_ERA_UNLOCKS_BRONZE`."""

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


ERA_BRANCH_KIND_WEIGHTS: dict[str, dict[str, float]] = {
    "industrious": {"workshop": 1.4, "factory": 1.4, "forge": 1.4, "oil_rig": 1.3},
    "scholarly": {"school": 1.4, "library": 1.4},
    "devout": {"shrine": 1.5},
    "mercantile": {"market": 1.5, "dock": 1.3},
    "agrarian": {"granary": 1.3, "pasture": 1.3, "hatchery": 1.3},
}
"""v1 audit fix (explicit user request: "let emergence/LLM steer its
own course of era progression by inventing new eras" — scoped, per the
AskUserQuestion decision, to LLM branching influence over a settlement's
OWN technological/cultural character rather than forking the shared
`ERA_ORDER` ladder itself, which every building/vehicle unlock is keyed
to and would need per-branch duplication to fork safely). A settlement
picks (or is assigned, deterministic fallback) one named branch each
time it advances era (`Settlement.era_branch`, sticky until the next
advance) — `choose_building_kind`'s `branch` param nudges civic-building
odds toward that character, same multiplicative-boost shape `PRIORITY_
KIND_BOOST` already uses for `current_priority`, just smaller (a real
lean, never dominant — a settlement can still found any kind). Two
settlements reaching the same era via the same tech path can end up
with visibly different building mixes depending on which branch each
one settled into — genuine emergent divergence, bounded to existing,
mechanically-supported BuildingKinds rather than the LLM inventing
unsupported new ones. See llm/era_branch.py, SimulationEngine._maybe_
advance_era."""

ERA_BRANCH_NAMES: tuple[str, ...] = tuple(ERA_BRANCH_KIND_WEIGHTS.keys())

ERA_BRANCH_BOOST = 1.35
"""Multiplier applied to each of a branch's favored kinds' weights in
`choose_building_kind` — smaller than `PRIORITY_KIND_BOOST` (2.5) since
a branch is a slow-forming background character trait, not the
settlement's active seasonal priority; the two stack multiplicatively
when they happen to favor the same kind."""


def era_for_tech_level(tech_level: int) -> str:
    era = ERA_ORDER[0]
    for name in ERA_ORDER:
        if tech_level >= ERA_TECH_THRESHOLDS[name]:
            era = name
    return era


ERA_INFRASTRUCTURE_REQUIREMENTS: dict[str, dict[str, int]] = {
    "bronze_age": {"huts": 2, "roads": 2, "schools": 0, "carts": 0},
    "iron_age": {"huts": 3, "roads": 4, "schools": 0, "carts": 1},
    "classical": {"huts": 4, "roads": 6, "schools": 1, "carts": 1},
    "medieval": {"huts": 5, "roads": 9, "schools": 1, "carts": 1},
    "renaissance": {"huts": 5, "roads": 12, "schools": 1, "carts": 2},
    "electrical": {"huts": 6, "roads": 15, "schools": 1, "carts": 2},
    "modern": {"huts": 10, "roads": 30, "schools": 2, "carts": 4},
    "digital": {"huts": 15, "roads": 50, "schools": 3, "carts": 6},
}
"""Extended (v1 audit fix) to cover the new pre-industrial eras — kept
genuinely light for the earliest rungs (a scrappy stone-age camp
should clear bronze_age/iron_age's bars almost incidentally through
ordinary early growth) and scaling up gradually toward the original
`electrical`/`modern`/`digital` bars, which are unchanged. `industrial`
still has no entry (the same "nothing gates re-entering a once-earlier
starting era" rule, now just no longer literally the first era) and
`stone_age` (the actual new starting era) likewise has none."""
"""docs/IDEAS-2026-07-EMERGENCE.md §9's last item: root-caused a live
"civilization doesn't progress after 50,000 ticks" report to
`era_for_tech_level` gating purely on `tech_level`, itself incremented
ONLY by `llm/invention.py`'s rare seasonal roll — a settlement could
have built dozens of huts/roads/schools/carts and still sit at
`industrial` forever if the roll simply never landed, with zero
correlation between visible development and actual progression. Fixed
by making these two things mutually reinforcing rather than gating one
behind the other in isolation: (1) `era_for_tech_level_gated` below
won't let `tech_level` alone vault a settlement past an era whose real
infrastructure hasn't been built yet — "small, legible, era-by-era
steps... each step unlocks new buildings/infra" (explicit user
framing), not a lucky invention roll suddenly unlocking FACTORY with
zero factories'-worth of civic development behind it; (2)
`_maybe_schedule_invention`'s chance calculation (simulation/engine.py)
reads `era_infrastructure_progress` toward the SAME requirement as a
genuine, deterministic bonus — a settlement that has already built
what the next era needs invents measurably more readily, so investing
in visible infrastructure is a real, controllable lever toward
progression rather than window dressing while waiting on the RNG.
`industrial` (the starting era) has no entry — nothing gates entering
the era every settlement already starts in. Counts are deliberately
modest relative to `POPULATION_CAP=400`-scale settlements (a handful
of huts/roads/one school/two carts unlocks `electrical`) — the goal is
a settlement's own real growth naturally clearing each bar in due
course, not a second grind layered on top of the invention roll."""

INFRASTRUCTURE_INVENTION_BONUS_WEIGHT = 0.5
"""How much `era_infrastructure_progress` toward the NEXT era's
requirement can boost `_maybe_schedule_invention`'s chance (same
multiplicative-stacking shape as `education_invention_bonus`/
`SKILL_INVENTION_BONUS_WEIGHT`/`TEMPERAMENT_INVENTION_INFLUENCE`) — at
full progress (1.0, infra requirement already met) this roughly
doubles the base chance*education*skill product; at zero progress it's
a no-op. Deliberately smaller than education's bonus (education_
invention_bonus can exceed 2x on its own) since infrastructure is a
secondary, supporting lever here, not the primary "did you invest in
learning" signal."""


def era_infrastructure_progress(era: str, huts: int, roads: int, schools: int, carts: int) -> float:
    """Fraction (0..1) of `era`'s `ERA_INFRASTRUCTURE_REQUIREMENTS` met
    by the given counts — 1.0 for an era with no requirement entry
    (`industrial`, or an unrecognized name). Each of the four counts
    contributes an equal quarter-share, individually capped at 1.0 (a
    surplus of huts doesn't compensate for zero roads) — matches the
    "many small, legible steps" framing rather than one aggregate score
    a settlement could game by overbuilding a single kind."""
    requirement = ERA_INFRASTRUCTURE_REQUIREMENTS.get(era)
    if not requirement:
        return 1.0
    shares = [
        min(1.0, huts / requirement["huts"]) if requirement["huts"] else 1.0,
        min(1.0, roads / requirement["roads"]) if requirement["roads"] else 1.0,
        min(1.0, schools / requirement["schools"]) if requirement["schools"] else 1.0,
        min(1.0, carts / requirement["carts"]) if requirement["carts"] else 1.0,
    ]
    return sum(shares) / len(shares)


def era_infrastructure_met(era: str, huts: int, roads: int, schools: int, carts: int) -> bool:
    requirement = ERA_INFRASTRUCTURE_REQUIREMENTS.get(era)
    if not requirement:
        return True
    return (
        huts >= requirement["huts"] and roads >= requirement["roads"]
        and schools >= requirement["schools"] and carts >= requirement["carts"]
    )


def era_for_tech_level_gated(tech_level: int, current_era: str, huts: int, roads: int, schools: int, carts: int) -> str:
    """Like `era_for_tech_level`, but never advances past an era whose
    own `ERA_INFRASTRUCTURE_REQUIREMENTS` aren't yet met — walks
    `ERA_ORDER` forward ONE step at a time from `current_era`, stopping
    at the first era that fails either the tech-level threshold or the
    infrastructure requirement, so a settlement can never skip a visible
    development step even if `tech_level` alone would qualify it for a
    much later era. Never demotes: if `current_era` is already ahead of
    what `tech_level`/infrastructure would newly justify (e.g. an older
    save from before this gate existed), this simply returns
    `current_era` unchanged rather than pulling it backward."""
    start_index = ERA_ORDER.index(current_era) if current_era in ERA_ORDER else 0
    era = current_era if current_era in ERA_ORDER else ERA_ORDER[0]
    for index in range(start_index + 1, len(ERA_ORDER)):
        name = ERA_ORDER[index]
        if tech_level < ERA_TECH_THRESHOLDS[name]:
            break
        if not era_infrastructure_met(name, huts, roads, schools, carts):
            break
        era = name
    return era


PRIORITY_HISTORY_MAX = 6
OMEN_HISTORY_MAX = 6
"""How many past town-brain decisions `Settlement.priority_history`
keeps — enough for the UI's "internal monologue" reveal to feel like a
running train of thought, not so many it grows unbounded across a
long-running world."""


def choose_building_kind(
    rng, current_priority: str, era: str = "stone_age", has_tradition: bool = False,
    caravans_visited: int = 0, water_adjacent: bool = False, branch: str = "",
    pillar_lean: "dict[str, float] | None" = None,
) -> "BuildingKind":
    """Weighted pick among the foundable civic kinds (not UNIVERSITY,
    which upgrades an existing school instead) — base odds nudged
    toward whatever the settlement's current priority calls for,
    FACTORY/POWER_PLANT excluded entirely until `era` has advanced past
    `industrial`, SHRINE excluded until the settlement has established
    at least one tradition (`has_tradition`), MARKET excluded until
    at least MARKET_CARAVAN_VISIT_REQUIREMENT caravans have ever
    reached the settlement (`caravans_visited`), and HATCHERY/DOCK/
    OIL_RIG excluded unless the chosen construction site is water-
    adjacent (`water_adjacent`, v0.86.7/v0.87.42 — same "physical
    siting constraint" shape RAFT/BRIDGE already require), OIL_RIG
    additionally excluded until era has advanced past `industrial`
    (same era gate as FACTORY/POWER_PLANT). Falls back to the
    unweighted base odds for an unrecognized/
    empty priority (e.g. before the first town-brain decision has ever
    run). See docs/DECISIONS.md, "LLM-as-brain batch\", the real-
    calendar/genesis-seed follow-up, "culture-specific building types,\"
    "Integration milestone: water/power/irrigation," and "animal/fish
    husbandry.\""""
    weights = dict(BUILDING_KIND_BASE_WEIGHTS)
    if era not in _ERA_UNLOCKS_BRONZE:
        weights.pop("forge", None)
        weights.pop("smelter", None)
    if era not in _ERA_UNLOCKS_CLASSICAL:
        weights.pop("library", None)
    if era not in _ERA_UNLOCKS_ELECTRICAL:
        weights.pop("factory", None)
        weights.pop("power_plant", None)
        weights.pop("oil_rig", None)
    if not has_tradition:
        weights.pop("shrine", None)
    if caravans_visited < MARKET_CARAVAN_VISIT_REQUIREMENT:
        weights.pop("market", None)
    if not water_adjacent:
        weights.pop("hatchery", None)
        weights.pop("dock", None)
        weights.pop("oil_rig", None)
    boosted = _PRIORITY_TO_KIND.get(current_priority)
    if boosted in weights:
        weights[boosted] *= PRIORITY_KIND_BOOST
    for kind_value in ERA_BRANCH_KIND_WEIGHTS.get(branch, {}):
        if kind_value in weights:
            weights[kind_value] *= ERA_BRANCH_BOOST
    if pillar_lean:
        for kind_value in weights:
            lean = pillar_lean.get(kind_value, 0.0)
            if lean > 0.0:
                weights[kind_value] *= 1.0 + lean * (BUILDING_KIND_PILLAR_LEAN_MAX - 1.0)
    total = sum(weights.values())
    roll = rng.random() * total
    upto = 0.0
    for kind_value, weight in weights.items():
        upto += weight
        if roll <= upto:
            return BuildingKind(kind_value)
    return BuildingKind.HUT  # unreachable in practice; keeps the function total


VILLAGE_LAND_USE_CONVICTION_THRESHOLD = 0.85
"""C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-2026-07-
22.md's Part C, Tier 3, "shift land use"): the bar `village_pillar`'s
own standing conviction about one of `LAND_USE_SHIFT_TARGET_KIND`'s
shortage subjects must clear before it's trusted to genuinely FORCE
the settlement's next construction site to that kind — a stronger
intervention than every other C2 slice so far (invention/laws/
self_tuning only ever INITIATE a call that would otherwise not
happen; this one overrides an already-decided outcome, `choose_
building_kind`'s own weighted roll), so it's held to the highest bar
of the four. Deliberately never applied when the settlement already
has a standing/under-construction building of the target kind (see
`Population._maybe_start_construction`'s `land_use_override_kind`
consumption) — this is a one-time strategic reallocation of what the
NEXT parcel of land becomes, not a permanent override that would
starve every other building kind forever while conviction stays high."""

LAND_USE_SHIFT_TARGET_KIND = {
    "food_shortage": BuildingKind.PASTURE,
    "housing_shortage": BuildingKind.HUT,
    "currency_shortage": BuildingKind.WORKSHOP,
}
"""Closed vocabulary for the "shift land use" C2 slice: each subject is
an already-real `village_pillar.world_model` category (Tier 0
producers `_detect_food_shortage`/`_detect_housing_shortage`/`_detect_
currency_shortage`), mapped to a `BuildingKind` deliberately chosen
because `choose_building_kind` never gates it behind era/tradition/
caravan/water-adjacency — an override can never produce an invalid
building regardless of settlement state. GRANARY was considered for
`food_shortage` but PASTURE was chosen instead: a granary only stores
food that already exists, while a pasture is the settlement genuinely
changing how it uses land to PRODUCE more — the literal "shift land
use" the intention names, not just more storage."""

VILLAGE_CIVIC_BUILD_CONVICTION_THRESHOLD = 0.9
"""C2 "Intention channel" (Mind -> Body, Tier 3), "build" — the
eighth and final named intention. The bar `village_pillar`'s
confidence about `"prosperity"` (the already-real category-keyed
producer, `SimulationEngine._detect_prosperity`) must clear before
`Population._maybe_civic_construction` genuinely INITIATES a real
construction attempt with no colocated founders required at all —
`_maybe_start_construction`'s ordinary path only ever fires when two
eligible agents happen to occupy the same tile; this bypasses that
colocation trigger entirely, the largest structural bypass of any C2
slice (every other slice still needed a real Body precondition to
already exist at the moment it acted). Deliberately the highest bar of
any C2 threshold — 0.05 above every sibling's 0.85 — since spending
real settlement materials on a brand-new construction site from
conviction alone, with no founders having chosen to build there
themselves, warrants the strictest bar in the whole channel."""


GRANARY_CAPACITY = 90.0
"""Max food a standing granary can hold. Raised from 15.0 -> 40.0 -> 90.0
across two rounds within v0.87.24's starvation-collapse fix. First
round (15 -> 40) was measured directly: at 15.0, `granary_food`
repeatedly hit exactly 0.0 under any settlement past ~15-20 population
(GRANARY_WITHDRAW_AMOUNT 0.25 x one withdrawal per hungry agent roughly
every 40 ticks drains a 15.0 granary in well under a day of sim-time) —
almost no real buffer at all. Second round (40 -> 90) responds to a
follow-up finding: `CARRYING_CAPACITY_MIN_MULTIPLIER`'s docstring
narrates a 40,000-tick soak (seed 23) where a settlement grew to ~92
before a sudden hunger spike (0.35 -> 0.72 in ~4,000 ticks) triggered
mass starvation — with `REPRODUCTION_SETTLEMENT_HUNGER_CEILING`
already blocking every new birth by then, the crash was pure existing-
population starvation, and even a 40.0 granary drains in well under a
tick's worth of real time against ~90 hungry withdrawals. 90.0 is sized
to actually matter at that scale; still a single settlement can build
more than one granary for proportionally more buffer, this just raises
the floor one granary alone provides."""

GRANARY_WELLFED_HUNGER_THRESHOLD = 0.3
"""An awake agent at or below this hunger, present at a standing granary,
contributes surplus each tick — presence-driven like every other
mechanic here (foraging, construction), not a hauling/inventory system."""

GRANARY_DEPOSIT_PER_TICK = 0.02
"""Food added per well-fed agent present, per tick, up to GRANARY_CAPACITY."""

PASTURE_CAPACITY = 12.0
"""Max food a standing pasture's own stock can hold — slightly below
GRANARY_CAPACITY (15.0), since husbandry is a smaller-scale, per-
building production source rather than the settlement's central
buffer."""

PASTURE_PASSIVE_YIELD_PER_TICK = 0.005
"""Food added every tick a PASTURE stands, regardless of staffing —
herds tend themselves, slowly, even with nobody actively working the
pasture. Small deliberately: this is a trickle, not the main yield."""

PASTURE_TENDED_YIELD_PER_TICK = 0.02
"""Additional food added per well-fed, awake agent present at a
standing PASTURE, per tick, on top of the passive trickle — same
"presence-driven production" shape WORKSHOP_INCOME_PER_TICK uses for
currency, applied to food. A tended pasture with MAX_WORKERS present
comfortably out-produces a granary's own deposit rate."""

HATCHERY_CAPACITY = 12.0
"""Same as PASTURE_CAPACITY."""

HATCHERY_PASSIVE_YIELD_PER_TICK = 0.006
"""Slightly above PASTURE_PASSIVE_YIELD_PER_TICK — fish stocks recover
somewhat faster than livestock even untended, matching FISH_REGEN_PER_
TICK being faster than plain food regen in the wild-forage mechanic."""

HATCHERY_TENDED_YIELD_PER_TICK = 0.025
"""Same shape as PASTURE_TENDED_YIELD_PER_TICK, at HATCHERY's slightly
higher rate."""

VILLAGE_DOMESTICATE_CONVICTION_THRESHOLD = 0.85
"""C2 "Intention channel" (Mind -> Body, Tier 3), "domesticate" — the
bar `village_pillar`'s confidence about a settlement's "grazer_
abundance" signal must clear before `SimulationEngine._maybe_
domesticate_grazers` genuinely INITIATES capturing wild GRAZER animals
into a standing PASTURE's own stock. Unlike every other C2 slice,
which reuses an existing mirror/action, no wild-herd-to-tame-stock
conversion existed anywhere in this codebase before this slice — this
is a wholly new capability, gated the same way "invent tech" gates a
wholly new invention attempt. Same bar as every other C2 slice."""

DOMESTICATE_MIN_HERD_SIZE = 4
"""A wild GRAZER herd must hold at least this many animals before it's
mirrored as a real domestication candidate — `AnimalHerd.count` starts
at `INITIAL_HERD_SIZE=4` (world/wildlife.py), so this requires a herd
that has at minimum recovered to its own starting size, not a fresh or
badly thinned one."""

DOMESTICATE_HERD_FLOOR = 2
"""Domestication never takes a wild herd below this floor — it skims a
genuine surplus from an already-healthy population, it never risks
extirpating the wild stock the ecology itself depends on (the same
"Body stays authoritative" discipline as every other C2 slice, applied
here to a shared natural resource rather than a settlement one)."""

DOMESTICATE_CAPTURE_SIZE = 1
"""How many animals a single domestication event captures from the
wild herd, via `WildlifeGrid.hunt` (the same native-index-safe removal
primitive a predator kill already uses — zero added native-parity
risk). Small and gated by `DOMESTICATE_HERD_FLOOR`/PASTURE headroom, so
this reads as a slow, repeated absorption over many days, not a single
sweep that empties the herd."""

DOMESTICATE_FOOD_PER_ANIMAL = 2.0
"""Food credited to a PASTURE's `stored_food` per captured animal —
well above `PASTURE_PASSIVE_YIELD_PER_TICK`'s per-tick trickle, since
this represents a real, discrete addition of livestock to the pasture's
stock, not an incremental yield tick."""

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

MINERAL_CAPACITY = 8.0
"""Max iron or gold a settlement's stockpile can hold per kind — well
below MATERIALS_CAPACITY (30.0): a specific ore vein's yield is a
luxury/specialty good, not bulk construction stock. See Population.
_maybe_gather, world/minerals.py."""

MINERAL_GATHER_PER_TICK = 0.015
"""Iron/gold added per GATHER-goal agent present on a HILLS tile
carrying a MineralDeposit, per tick — half MATERIALS_GATHER_PER_TICK,
reflecting that working a specific vein is slower/more careful labor
than general quarrying."""

MINERAL_CURRENCY_VALUE = {"iron": 3.0, "gold": 12.0}
"""Currency earned per unit of iron/gold sold at capacity (the same
overflow-sale mechanic materials/food already use) — well above
CURRENCY_PER_OVERFLOW_UNIT's flat 1.0, reflecting real per-unit value:
gold sells for 4x iron, both far above bulk materials. This is also
what makes a gold vein "worth fighting over" (docs/IDEAS-2026-07-
EMERGENCE.md §8) even before any dedicated dispute/theft hook exists
for it — a settlement's economy already feels the difference."""

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

CURRENCY_SHORTAGE_THRESHOLD = 5.0
"""Tier 0, new producer: below this, a settlement's coffers read as a
genuine shortage — half of `INVENTION_CURRENCY_THRESHOLD` (10.0, the
existing "prosperous enough to invent" bar), i.e. 10% of `CURRENCY_
CAPACITY` against invention's 20%. Backs `SimulationEngine._detect_
currency_shortage`."""

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

DOCK_INCOME_PER_TICK = 0.03
"""Same shape/rate as WORKSHOP_INCOME_PER_TICK — a trade port is a
water-adjacent business, not a differently-themed passive bonus like
RAFT. See BuildingKind.DOCK."""

OIL_RIG_INCOME_PER_TICK = 0.06
"""Same shape as FACTORY_INCOME_PER_TICK (double DOCK's rate) — offshore
extraction is the water-infrastructure batch's industrial-scale income
building. See BuildingKind.OIL_RIG."""

FORGE_INCOME_PER_TICK = 0.02
"""Same shape as WORKSHOP_INCOME_PER_TICK, at a lower rate — a
bronze_age smithy is this era's business, but a genuinely smaller-scale
one than an industrial-era WORKSHOP. Not multiplied by POWER_GRID_
INDUSTRY_MULTIPLIER (no electricity yet). See BuildingKind.FORGE,
Population._maybe_run_forges."""

POWER_GRID_INDUSTRY_MULTIPLIER = 1.3
"""Multiplies WORKSHOP_INCOME_PER_TICK/FACTORY_INCOME_PER_TICK/OIL_RIG_
INCOME_PER_TICK settlement-wide while a standing POWER_PLANT exists
(`Population._maybe_run_workshops`/`_maybe_run_factories`/`_maybe_run_
oil_rigs`) — electrified industry produces more, the concrete payoff
for `electrical` era being more than a label. Not applied to DOCK_
INCOME_PER_TICK — a trade port's income is commerce, not electrified
industrial output, same reasoning WORKSHOP gets it and MARKET doesn't.
Applied once per settlement (not per powered building — there's no
per-building grid-connection concept, matching every other
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


def compute_resource_fill(settlement: "Settlement") -> tuple[float, float]:
    """The real supply/demand read `tick_market_prices` uses — factored
    out (A4, "economy -> resource/price fields that flow," docs/
    ROADMAP-2026-07-REMAINING.md) so `World.tick()`'s new `FieldGrid.
    step_scarcity` can read the SAME granary/materials fill ratios
    without duplicating the logic or requiring a standing MARKET (a
    settlement's actual stores are real economic reality regardless of
    whether it has price discovery yet). Returns (food_fill,
    materials_fill), each 0..1 (0.5 neutral default with no granaries/
    zero capacity, same fallback `tick_market_prices` always used)."""
    granaries = [
        b for b in settlement.buildings
        if b.kind is BuildingKind.GRANARY and b.stage is BuildingStage.STANDING
    ]
    granary_capacity = len(granaries) * GRANARY_CAPACITY
    food_fill = (sum(b.stored_food for b in granaries) / granary_capacity) if granary_capacity else 0.5
    materials_fill = settlement.materials / MATERIALS_CAPACITY if MATERIALS_CAPACITY else 0.5
    return food_fill, materials_fill


def tick_market_prices(settlement: "Settlement", population_hint: int = 0) -> None:
    """Called on month boundaries (SimulationEngine). Mutates
    `settlement.economy.market_prices` in place — see MARKET_PRICE_MIN's
    docstring for the model."""
    prices = settlement.economy.market_prices
    if not settlement.has_market():
        if prices:
            prices.clear()
        return
    food_fill, materials_fill = compute_resource_fill(settlement)
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

IRON_TOOL_COST_PER_TICK = 0.01
IRON_TOOL_BONUS_PER_TICK = 0.012
"""§8 expanded mineral economy (v0.87.25): when the settlement has iron
on hand, a workshop worker's craft also consumes a small amount of it
alongside materials for a real quality bonus — extends the existing H4
tools chain rather than building a parallel one, same "iron ore feeds
better tools" logic real smithing has. Optional, not required: a
settlement with no iron still crafts tools exactly as before at the
plain WORKSHOP_CRAFT_TOOLS_PER_TICK rate."""
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

CARRYING_CAPACITY_HUNGER_WEIGHT = 0.55
CARRYING_CAPACITY_HUNGER_COMFORT = 0.28
"""Direct, always-on food-security term (v0.87.24 starvation-collapse
fix) — unlike ECONOMY_WEIGHT's granary_fill term, which docstring-
documents its own gap ("only scored once a granary exists, so a
founding party ... isn't penalized"), this reads the settlement's own
real average member hunger every tick, with no infrastructure
prerequisite. Root cause of "starvation is the dominant collapse
mode in almost every playthrough": before a granary exists (or once
one exists but is too small to buffer a grown population —
GRANARY_CAPACITY is a flat per-building constant, not scaled to
population), `carrying_capacity` had ZERO food-supply signal — capacity
was driven purely by housing (huts) and the `_maybe_reproduce` per-
couple `has_surplus` check, which only reads the reproducing PAIR's own
momentary hunger, not the community's. That let population keep
growing on housing supply alone while food production silently fell
behind, and the only feedback loop that could ever catch the mismatch
was mass starvation deaths themselves — never a graceful birth-rate
slowdown. `hunger_term` closes this: once a settlement's average
member hunger rises past COMFORT (deliberately the same bar
`REPRODUCTION_WELLFED_HUNGER`-adjacent state already treats as "not
truly fed"), capacity contracts smoothly and reproduction throttles
BEFORE the community is in a visible crisis, not after. Weighted well
above ECONOMY (0.55 vs 0.25) since this is the direct signal food
scarcity actually is, not a proxy for it. COMFORT tightened 0.35 -> 0.28
and WEIGHT raised 0.4 -> 0.55 after a first-pass version (still
measurably too permissive — a 40,000-tick soak still saw population
overshoot to 62 then crash to 8 before recovering) proved too loose;
see CHANGELOG.md v0.87.24 for the confirming re-run's numbers once
posted — if a future soak still shows a crash of this shape, tighten
further rather than treating these as final."""

CARRYING_CAPACITY_MIN_MULTIPLIER = 0.5
CARRYING_CAPACITY_MAX_MULTIPLIER = 1.5
"""Bounds on the composed multiplier above — a settlement in crisis
(plague, siege, famine) can still support down to half its housing-based
capacity, and a thriving one can stretch to 1.5x it, but neither factor
set can send the ceiling to zero or unbounded growth on its own.
v0.87.24 starvation-collapse fix, investigated then reverted: a
40,000-tick soak (seed 23) tried lowering MIN to 0.3 to give the
hunger term more room against a settlement that had already built
ahead of its food supply — the resulting soak was BYTE-IDENTICAL to
the 0.5 run, proving `carrying_capacity`'s floor was never the binding
constraint in this crash at all. `REPRODUCTION_SETTLEMENT_HUNGER_
CEILING` had already blocked every new birth once average hunger
crossed 0.45; the crash that followed (population 92 -> 13, mostly
starvation) was entirely EXISTING population dying once a sudden
hunger spike (0.35 -> 0.72 in ~4,000 ticks — a real seasonal/weather-
driven food-production shock) hit a settlement too large for its
granary buffer to smooth over. No demand-side throttle (reproduction
gating, capacity contraction) can undo an already-large population's
food need — see GRANARY_CAPACITY's docstring for the supply-side lever
actually aimed at this failure mode, and CHANGELOG.md v0.87.24 for the
full investigation."""

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


def tick_temperament(
    temperament: float, recent_events: list[dict], rng, intensity: float = 1.0, extra: float = 0.0,
) -> float:
    """Nudge temperament one step (called monthly, alongside beliefs —
    see SimulationEngine._maybe_tick_temperament). `recent_events` is
    the same recent_events(conn, limit=...) shape used elsewhere
    (dicts with a "category" key). `intensity` is Config.phase_g_
    intensity — scales the step itself (noise and fortune-bias alike),
    so 0.0 holds temperament flat at its mean-reverted value (drifting
    to 0 over time, never nudged) rather than requiring a separate
    on/off flag. `extra` is a one-shot bounded nudge folded straight into
    the step, UNSCALED by `intensity` (Phase N, docs/VISION-2026-07.md:
    a `temperament_nudge` consciousness intervention) — the shared
    `bounded_random_walk_step` primitive (module 12) already supports
    this exact `value*mean_reversion + jitter + extra` shape, just not
    threaded through this call site until now. Defaults to 0.0, so every
    existing caller is unaffected."""
    good = sum(1 for e in recent_events if e.get("category") in _GOOD_FORTUNE_CATEGORIES)
    ill = sum(1 for e in recent_events if e.get("category") in _ILL_FORTUNE_CATEGORIES)
    fortune = (good - ill) / (good + ill) if (good + ill) else 0.0
    jitter = rng.uniform(-TEMPERAMENT_STEP_MAX, TEMPERAMENT_STEP_MAX)
    step = (jitter + fortune * TEMPERAMENT_FORTUNE_WEIGHT) * intensity
    if _native_bounded_random_walk_step is not None:
        return _native_bounded_random_walk_step(temperament, TEMPERAMENT_MEAN_REVERSION, step, extra, -1.0, 1.0)
    return clamp(temperament * TEMPERAMENT_MEAN_REVERSION + step + extra, -1.0, 1.0)

# --- mood: Phase I "Collective Psychology" — aggregated from individual ---
# --- minds, the layer directly above Agent.emotions in the vision's ---
# --- hierarchy (docs/VISION-2026-07.md, Phase I). Distinct in shape from ---
# --- temperament (event-fortune-driven): mood tracks a live aggregate. ---

MOOD_KEYS = ("hope", "fear", "grief", "suspicion")
"""The four axes `Settlement.mood` holds. Each maps to one `Agent.
emotions` axis aggregated across this settlement's own living members
(see `tick_mood`'s `_MOOD_EMOTION_SOURCE`) — a settlement doesn't feel
"joy" or "anger" as such, so the mapped names read as the collective,
social version of the individual feeling: widespread joy reads as
hope, widespread anger reads as suspicion (a village that's recently
had a lot of hardened feuds trusts itself less as a whole, not just the
two parties involved)."""

_MOOD_EMOTION_SOURCE = {
    "hope": EMOTION_JOY,
    "fear": EMOTION_FEAR,
    "grief": EMOTION_GRIEF,
    "suspicion": EMOTION_ANGER,
}

MOOD_STEP_MAX = 0.03
MOOD_MEAN_REVERSION = 0.9
"""Same bounded-random-walk shape as `TEMPERAMENT_STEP_MAX`/
`TEMPERAMENT_MEAN_REVERSION`, but a noticeably stronger mean-reversion
(0.9 vs 0.97) — mood is meant to visibly track the population's current
felt state (see `MOOD_TRACKING_WEIGHT`) rather than drift like
temperament's slower fortune-ratio walk, so it needs to be pulled back
toward 0 faster whenever the underlying agent emotions have calmed
down, or a single bad month would linger for years."""
MOOD_TRACKING_WEIGHT = 0.3
"""How much of the gap between the current mood value and this month's
live agent-emotion aggregate closes per tick_mood call — the actual
"individual minds aggregate into collective psychology" mechanism.
0.3 means roughly 3-4 consecutive months of a sustained population
feeling closes most of the gap, not an instant snap (a single festival
shouldn't flip the whole village's hope from cold to warm in one
sitting) but also not multi-year lag."""


def tick_mood(
    mood: dict[str, float], agent_emotions: list[dict[str, float]], rng, intensity: float = 1.0,
) -> dict[str, float]:
    """Nudge every `Settlement.mood` axis one step (called monthly,
    alongside temperament — see SimulationEngine._maybe_tick_temperament,
    which now also calls this). `agent_emotions` is this settlement's own
    living members' `Agent.emotions` dicts (missing keys read 0.0, same
    convention as the source dicts) — the aggregate mean of each mapped
    axis (see `_MOOD_EMOTION_SOURCE`) is the "signal" this month's step
    tracks toward, rescaled from emotions' 0..1 intensity range to mood's
    -1..1 bounded-walk range. `intensity` is `Config.phase_g_intensity` —
    scales the step (noise and tracking pull alike), so 0.0 holds every
    axis flat at its mean-reverted value, matching `tick_temperament`'s
    own intensity=0.0 behavior. Returns a new dict (never mutates the
    input) — same "settlement.temperament = tick_temperament(...)"
    call-site shape as the sibling functions."""
    result: dict[str, float] = {}
    for key in MOOD_KEYS:
        current = mood.get(key, 0.0)
        source = _MOOD_EMOTION_SOURCE[key]
        if agent_emotions:
            avg = sum(e.get(source, 0.0) for e in agent_emotions) / len(agent_emotions)
        else:
            avg = 0.0
        # Root-cause fix for a live audit finding (P0.1): emotions decay
        # TOWARD 0 (calm), so the old `avg * 2.0 - 1.0` mapped an
        # ordinary, calm population (avg ~= 0) to signal ~= -1 on EVERY
        # axis — "nobody is afraid" was being encoded as "profound
        # anti-fear," pinning hope/fear/grief/suspicion all toward -1
        # forever regardless of what was actually happening. `avg` (0..1
        # emotion intensity) maps directly onto mood's own -1..1 range:
        # calm correctly tracks toward neutral (0), and MOOD_MEAN_
        # REVERSION already pulls existing saved moods back from any
        # pre-fix -1 pinning over the next few months without a separate
        # migration. The true negative register (a village that's
        # unusually safe/hope-drained/etc, "very calm" moods) comes from
        # jitter/mean-reversion drift and inherited state, same as
        # temperament's own asymmetric-signal shape.
        signal = avg
        jitter = rng.uniform(-MOOD_STEP_MAX, MOOD_STEP_MAX)
        step = (jitter + (signal - current) * MOOD_TRACKING_WEIGHT) * intensity
        if _native_bounded_random_walk_step is not None:
            result[key] = _native_bounded_random_walk_step(current, MOOD_MEAN_REVERSION, step, 0.0, -1.0, 1.0)
        else:
            result[key] = clamp(current * MOOD_MEAN_REVERSION + step, -1.0, 1.0)
    return result


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
    jitter = rng.uniform(-TEMPERAMENT_STEP_MAX, TEMPERAMENT_STEP_MAX)
    step = (jitter + touches * PLAYER_STANDING_STEP_PER_INTERVENTION) * intensity
    if _native_bounded_random_walk_step is not None:
        return _native_bounded_random_walk_step(standing, PLAYER_STANDING_MEAN_REVERSION, step, 0.0, -1.0, 1.0)
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
    if _native_bounded_random_walk_step is not None:
        return _native_bounded_random_walk_step(value, RELATION_MEAN_REVERSION, step, 0.0, -1.0, 1.0)
    return clamp(value * RELATION_MEAN_REVERSION + step, -1.0, 1.0)


def seed_relation(origin_temperament: float, rng) -> float:
    """Starting mutual affinity between a fission's origin and daughter
    settlement — see RELATION_SEED_BASE/RELATION_SEED_TEMPERAMENT_WEIGHT.
    A small independent random jitter keeps every fission from seeding
    an identical value."""
    jitter = rng.uniform(-0.05, 0.05)
    return clamp(RELATION_SEED_BASE + origin_temperament * RELATION_SEED_TEMPERAMENT_WEIGHT + jitter, -1.0, 1.0)


DIPLOMATIC_HOSTILITY_THRESHOLD = -0.5
"""Tier 0, new producer: a cross-settlement relation this cold reads as
a genuine diplomatic crisis, not just `llm/diplomacy.py`'s own "cold"
narration tone (-0.3) — deeper than merely chilly, since this backs a
real settlement-wide law/hardship signal (`SimulationEngine._detect_
diplomatic_hostility`), not just how a narration prompt is worded."""

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


RELATION_CARAVAN_INFLUENCE = 0.25
"""Max swing `caravan_relation_factor` applies to caravan visit chance
at a fully warm (+1.0) or fully cold (-1.0) average relation — §2
"settlement-level stance (proto-diplomacy)"'s named deterministic
lever: a region on good terms with itself draws more outside trade
traffic through it, a region full of cold neighbors draws less.
Deliberately larger than `RELATION_MARKET_INFLUENCE` (0.1) since this
gates whether contact happens at all, not just its terms."""


def caravan_relation_factor(settlement: "Settlement") -> float:
    """Same shape as `market_relation_factor`, applied to caravan visit
    *chance* instead of price — see RELATION_CARAVAN_INFLUENCE. Returns
    1.0 (no effect) for a settlement with no recorded relations yet."""
    values = list(settlement.relations.values())
    if not values:
        return 1.0
    avg = sum(values) / len(values)
    return 1.0 + avg * RELATION_CARAVAN_INFLUENCE

# --- Phase E3: inventions (tech-tier unlocks) -------------------------------

TECH_BONUS_PER_LEVEL = 0.15
"""Multiplicative bonus per invention, applied to construction/repair
work and to cultivated-food yield (farm harvest, granary stock/withdraw)
— NOT wild foraging, which is deliberately untouched by "technique." A
settlement with 3 inventions works/harvests/stores at 1.45x baseline.
Uncapped: inventions are meant to be rare (see INVENTION_CHANCE_PER_SEASON),
so runaway compounding is self-limiting in practice. See
docs/DECISIONS.md, E3."""

INVENTION_CATEGORIES: tuple[str, ...] = ("agricultural", "structural", "mercantile", "general")
"""Post-v1 follow-up: closed-choice category `llm/invention.py` picks
alongside an invention's name/description, so a specific invention
carries a specific mechanical lean rather than every invention doing
the identical generic thing. "medical" was deliberately left out this
pass — disease/predator death-chance code is higher-blast-radius to
touch than yield/income/work-rate multipliers, flagged as a follow-up,
not attempted. "general" is always a safe, valid choice with no
specific consumption, for an invention that genuinely doesn't fit."""

INVENTION_SPECIALIZATION_STEP = 0.03
INVENTION_SPECIALIZATION_CAP = 0.18
"""Per-category bonus step/cap on `Settlement.invention_specializations`
— six matching inventions saturate a category at the cap (diminishing
returns, same "can't stack to dominance" discipline capped values use
elsewhere in this project). Deliberately smaller than TECH_BONUS_PER_
LEVEL's per-invention 0.15 (uncapped, generic, applies regardless of
category) — this is a differentiating LEAN on top of that baseline,
not a replacement for it."""

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

INNOVATION_HYPOTHESIS_CONFIDENCE_THRESHOLD = 0.6
"""C2 "Intention channel" (Mind -> Body, docs/MASTERCHECKLIST-2026-07-
22.md's Part C): the bar `innovation_pillar`'s own leading open
(`status="hypothesis"`) `world_model` belief must clear before it's
trusted as a genuine seed for the next invention attempt — not every
half-formed hunch, only one Innovation's own cognition has actually
converged on. See `SimulationEngine._maybe_schedule_invention`."""

INNOVATION_HYPOTHESIS_INVENTION_BONUS_WEIGHT = 0.5
"""Max multiplicative boost to `INVENTION_CHANCE_PER_SEASON` from a
qualifying leading hypothesis, scaled by its own confidence (0.6..1.0
-> roughly +30%..+50%) — real but bounded, same "never dominant" shape
as `TEMPERAMENT_INVENTION_INFLUENCE`/`SKILL_INVENTION_BONUS_WEIGHT`.
Applied AFTER the prosperity gate, never in place of it — a pillar's
own conviction makes a breakthrough come more readily once the
village can actually afford one, it never substitutes for real
surplus (Body stays authoritative; see docs/CONSTITUTION.md's
priority order)."""

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

FAMILY_FEUD_FESTIVAL_PENALTY = 0.4
"""§9 'more cross-system interactions' (docs/IDEAS-2026-07-EMERGENCE.md)
— its own named example ("tax -> guild unrest -> canceled festival")
built the same ad hoc way: a settlement with at least one standing
`Institution.feuds` entry among its FAMILY institutions has its real,
lived discord dampen the mood, multiplying FESTIVAL_CHANCE_PER_MONTH
by (1 - this) rather than blocking festivals outright — a rift in the
community makes a celebration less likely, not impossible."""

PROSPERITY_MATERIALS_FRACTION = 0.7
"""Tier 0, new producer: fraction of `MATERIALS_CAPACITY` a settlement
must sustain, alongside `PROSPERITY_CURRENCY_FRACTION`, to read as
genuinely prosperous (not just one flush stockpile) — see
`SimulationEngine._detect_prosperity`."""

PROSPERITY_CURRENCY_FRACTION = 0.7
"""Companion to `PROSPERITY_MATERIALS_FRACTION` — both must hold at
once, real broad-based prosperity rather than a single resource
spike."""

PROSPERITY_FESTIVAL_BONUS = 0.3
"""Tier 0, new producer: the positive counterpart to `FAMILY_FEUD_
FESTIVAL_PENALTY` — a settlement currently flagged prosperous (see
`SimulationEngine._detect_prosperity`) multiplies `FESTIVAL_CHANCE_
PER_MONTH` by `(1 + this)` rather than being blocked/boosted outright,
same bounded-nudge shape every other festival-chance modifier here
uses — a comfortable village celebrates more, not automatically."""

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
    """0..GRANARY_CAPACITY for a STANDING GRANARY, or 0..PASTURE_
    CAPACITY / 0..HATCHERY_CAPACITY for a STANDING PASTURE/HATCHERY
    (v0.86.7) — same generic field reused across every food-producing/
    storing building kind rather than one field per kind."""
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
    bridge_span: tuple[tuple[int, int], ...] = ()
    """Meaningful only for `BuildingKind.BRIDGE`: the ordered water
    tiles it covers from `(x, y)`'s far shore-adjacent water neighbor to
    the opposite shore, found once at founding time
    (`Population._find_bridge_span`) and fixed thereafter — the bridge
    doesn't grow/shrink, it's either standing (its span is walkable) or
    it isn't. Empty for every other kind."""
    material: str | None = None
    """A13 "Chemistry / reaction system" (roadmap Stage IV step 20):
    per-INSTANCE material override, `None` meaning "use `world.
    materials.BUILDING_MATERIALS[kind]`'s default" (every building
    that was never converted, i.e. almost all of them). Only ever set
    by `world.chemistry.tick_building_reactions` — a standing
    building whose effective material matches a `ReactionRule`'s
    reactant, held under that rule's condition for `rate` consecutive
    ticks, genuinely converts (e.g. a SHRINE's clay firing into
    ceramic under sustained heat). See `world.materials.
    effective_material_name`, the one place that resolves this
    override against the per-kind default."""
    reaction_progress: int = 0
    """Consecutive ticks this building's effective material has sat
    under a matching `ReactionRule`'s condition, uninterrupted — reset
    to 0 the instant the condition or material stops matching (same
    "sustained, not cumulative-forever" discipline as `World.mining_
    scar_sustained_ticks`). Meaningless (stays 0) once a conversion has
    already happened for this reactant, since the CONVERTED material
    (e.g. ceramic) has no further `REACTION_RULES` entry of its own."""

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
            "bridge_span": [[x, y] for x, y in self.bridge_span],
            "material": self.material,
            "reaction_progress": self.reaction_progress,
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
            bridge_span=tuple((x, y) for x, y in data.get("bridge_span", [])),
            ruined_ticks=data.get("ruined_ticks", 0),
            stored_food=data.get("stored_food", 0.0),
            owner_agent_id=data.get("owner_agent_id"),
            material=data.get("material"),
            reaction_progress=data.get("reaction_progress", 0),
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
    pending_letters: list[dict] = field(default_factory=list)
    """§2 "letters carried by caravans" (docs/IDEAS-2026-07-EMERGENCE.
    md): in-transit mail, queued on the RECIPIENT's settlement —
    `{from_id, from_name, to_id, to_name, text, deliver_tick}`. Written
    by `SimulationEngine._maybe_schedule_letter` (monthly, core-cast
    bonded cross-settlement pairs only); delivered by `_deliver_
    letters` (day_end) once `deliver_tick` passes — as a memory on the
    recipient if still alive, or a `letter_arrived_too_late` event
    otherwise (the sender or recipient may have died in transit; see
    module docstring, "latency is the feature"). Bounded naturally by
    `LETTER_MAX_PENDING` (delivery/expiry keeps this small; letters
    aren't accumulated indefinitely)."""


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
    minerals: dict = field(default_factory=dict)
    """§8 expanded mineral economy (v0.87.25): {"iron": float, "gold":
    float}, each 0..MINERAL_CAPACITY — distinct from `materials`
    (bulk wood/stone) the way a specific ore vein differs from a quarry.
    Gathered by GATHER-goal agents on a hills tile carrying a
    `MineralDeposit` (world/minerals.py), consumed by tool-crafting
    (iron) and overflow-sold at a much higher per-unit price than
    materials (both) once at capacity. See Population._maybe_gather."""
    fish_caught: int = 0
    """Persistent, never-decremented count of meals relieved from a
    FISH resource node (Population._maybe_forage) — same shape as
    `caravans_visited`. Fishing was mechanically real since the
    resource-variety pass but had no visible tally anywhere; this is
    the "make fishing visible" counter, surfaced in the UI's wild-
    resources tile instead of logging a per-catch event (which would
    spam the curated event log at population scale). See
    docs/DECISIONS.md, "fishing visibility.\""""
    buildings_repaired: int = 0
    """Persistent, never-decremented count of times a standing building
    was worked back up to full condition (1.0) by present agents
    (`Population._maybe_repair`) — repair itself has been mechanically
    real since v0.85.2 (deterministic side always was; the v0.85.2 fix
    made a live LLM aware `'wander'` could mean going to help), but had
    no visible tally anywhere, same "make real NPC labor visible" gap
    `fish_caught`/`caravans_visited` already closed for their own
    mechanics. Counts *completed* repairs (crossing back to 1.0), not
    every tick work happens, so this reads as a discrete achievement
    count rather than a fast-climbing continuous one."""
    vehicles_repaired: int = 0
    """Same shape as `buildings_repaired`, for `Population._maybe_
    repair_vehicles` — counts a vehicle's `BROKEN -> READY` transition
    (the vehicle system's own existing "repair completed" signal), not
    the routine READY-but-below-threshold top-up case."""
    thefts_committed: int = 0
    """Persistent, never-decremented count of `Population._maybe_
    commit_theft` events (item 8a, "crime & theft") — same visibility
    shape as `fish_caught`/`buildings_repaired`, surfaced as a stat
    tile rather than a per-theft event-log entry."""


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
    era: str = "stone_age"
    """One of ERA_ORDER — advances purely as `tech_level` grows (see
    `era_for_tech_level`); gates FACTORY and (via vehicles) AUTOMOBILE."""
    era_branch: str = ""
    """v1 audit fix: one of ERA_BRANCH_NAMES, chosen (LLM-authored, or
    deterministic fallback) each time `era` advances — see llm/
    era_branch.py, SimulationEngine._maybe_advance_era. Empty until the
    first era advance. Sticky between advances, re-chosen (not
    accumulated) on each new one — a settlement's character can shift
    over its history, it doesn't layer indefinitely."""
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
    invention_knowledge: dict = field(default_factory=dict)
    """v0.87.15, "knowledge lifecycle: diffusion, loss, rediscovery"
    (docs/IDEAS-2026-07-EMERGENCE.md §7) — invention text (matching an
    `inventions` entry) -> `{"knowers": [agent ids], "dormant": bool}`.
    Deliberately NOT tracked for every entry in the (up to 300-long)
    `inventions` list — only the most recent `INVENTION_KNOWLEDGE_
    MAX_TRACKED` inventions carry live knower tracking (oldest evicted
    first, same shape `inventions` itself caps at). An invention that
    ages out of tracking (or predates this feature on an old snapshot)
    is treated as settled common knowledge, never dormant — this is a
    deliberate scope boundary, not a bug: only RECENT, still-narrow
    knowledge is fragile enough to plausibly die with one person.
    `Population._maybe_teach_skills`'s existing colocation loop spreads
    a tracked invention the same way it spreads skills; `_apply_deaths`
    removes a knower and flips `dormant=True` once none remain
    (`knowledge_lost` event); `_apply_inheritance` gives an heir a
    chance to rediscover a dormant invention they inherit alongside
    goods/skill/bias (H7)."""
    invention_specializations: dict = field(default_factory=dict)
    """Post-v1 follow-up: previously EVERY invention had the identical
    mechanical effect (`tech_level += 1`, feeding the flat, invention-
    agnostic `_tech_factor`) — the LLM's own choice of WHAT to invent
    carried zero mechanical weight beyond its narrated flavor text.
    `llm/invention.py` now also picks a closed-choice category
    (`INVENTION_CATEGORIES`) alongside the name/description; each
    matching invention nudges `invention_specializations[category]` up
    by `INVENTION_SPECIALIZATION_STEP`, capped at `INVENTION_
    SPECIALIZATION_CAP` per category (diminishing returns — a
    settlement can't stack one category to dominance from a lucky
    naming streak). Consumed multiplicatively alongside `_tech_factor`
    at category-matched call sites (agricultural: farm/husbandry yield;
    mercantile: workshop/factory/dock/oil_rig/forge/banker income;
    structural: construction/repair work rate) — see `Population.
    _specialization_factor`. `general` is a safe always-valid category
    with no specific consumption, for inventions that genuinely don't
    fit a category."""
    festivals: list[str] = field(default_factory=list)
    """Festivals held, same shape — wellbeing-gated, with a direct
    mechanical effect (FESTIVAL_RELATIONSHIP_BOOST). Capped in storage
    at CULTURE_LIST_MAX_STORED, same as traditions."""
    festivals_held: int = 0
    """Total festivals ever held, never decremented — same decoupling
    rationale as `traditions_established`."""
    folklore: list[dict] = field(default_factory=list)
    """Phase K: `{"tale": str, "tick": int}` entries, LLM-condensed
    monthly from the settlement's own recent rumor-category events —
    see `llm/folklore.py` and `FOLKLORE_MAX_STORED`. Feeds dialogue/
    omen/chronicle prompts, the same "accumulated interpretation feeds
    future interpretation" loop `beliefs` already established, one
    layer more folk than formal theory."""
    legends: list[dict] = field(default_factory=list)
    """A21 "Temporal compression" (roadmap Stage IV step 30, docs/
    MASTERCHECKLIST-2026-07-22.md), first slice: `{"subsystem": str,
    "legend": str, "tick": int}` entries — DISTINCT from `folklore`
    (which condenses raw rumor text). A legend forms from `World.
    emergence_log`'s already-structured stream instead: `world/
    legends.py`'s deterministic detector counts this settlement's
    recent Emergence API observations by `subsystem`, and once one
    subsystem crosses `LEGEND_SUBSYSTEM_THRESHOLD` the LLM narrates
    the accumulated pattern into one short legend sentence — "event-
    aggregate -> LLM-narrate-significant -> deterministic-legend-
    detection," the doc's own worked pipeline shape, using data this
    codebase already collects rather than a new raw-text corpus. Once
    formed, that subsystem's counter resets so the same pattern
    doesn't keep re-mining the identical legend. Capped at
    `LEGENDS_MAX_STORED`."""
    folklore_persistence_count: int = 0
    """A21 "Temporal compression," third slice (explicit user
    instruction, "unify folklore/legend pipeline"): the real fold
    between folklore's rumor-condensation chain and `legends`'
    Emergence-API chain — previously two totally parallel mechanisms
    that never fed each other, despite this item's own spec literally
    naming their unification. Counts consecutive monthly folklore-job
    firings that produced NOTHING new (empty rumor window, an LLM "not
    worth telling" answer, or a near-duplicate rejected by `folklore.
    parse_folklore`'s dedup) while the newest `folklore` tale stood
    unchanged — i.e. the village's current dominant tale enduring
    without being supplanted, the temporal-compression signal itself:
    something repeated/retold long enough without new material IS a
    legend. Resets to 0 the moment a genuinely new tale forms. See
    `FOLKLORE_LEGEND_PERSISTENCE_THRESHOLD`."""
    folklore_persistence_promoted: bool = False
    """Guards `_promote_folklore_to_legend` from re-promoting the SAME
    enduring tale every month once it first crosses `FOLKLORE_LEGEND_
    PERSISTENCE_THRESHOLD` — cleared back to False only when a new
    folklore tale actually forms (see `folklore_persistence_count`)."""
    beliefs: list[dict] = field(default_factory=list)
    """The village's own accumulated, revisable theories about itself
    (`{subject, belief, confidence, subject_agent_id, ...}`), capped at
    llm/beliefs.MAX_BELIEFS — the concrete expression of "cognition as
    continuous rather than stateless". Not guaranteed correct, exactly
    like a person's own beliefs about their community."""
    belief_digest: str = ""
    """One short LLM-authored sentence condensing the overall shape of
    everything in `beliefs` together — written as an extra field on the
    existing monthly belief-forming/revising call (zero added LLM
    volume, same "extend an existing job" discipline `Agent.semantic_
    memories` already established), not a separate summarization call.
    Lets `chronicle`/`town_brain` ground their prompt in the *gist* of
    the village's full accumulated self-theory instead of dumping many
    raw belief entries — see docs/DECISIONS.md, "intelligent belief
    digest" pass. Retained (not cleared) on a fallback call, same
    "never silently lose a queued value to a flaky LLM stretch"
    discipline `player_influence`/`omen_seed`/`dream_seed` already use."""
    culture_digest: str = ""
    """One short LLM-authored sentence condensing the overall shape of
    `traditions`/`inventions`/`festivals`/`records` together — the
    `belief_digest` treatment applied to the settlement's accumulated
    culture and history, which (unlike beliefs) has no natural
    "revise the whole list" call to piggyback a digest onto for free.
    Written by a genuinely new quarterly job (`llm/culture_digest.py`,
    `SimulationEngine._maybe_schedule_culture_digest`) — one real call
    per season, traded against `chronicle`/`town_brain` needing an
    ever-larger raw slice of these lists as history accumulates.
    Retained (not cleared) on a fallback call, same discipline as
    `belief_digest`."""
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
    explored_tiles: set = field(default_factory=set)
    """v0.87.45 exploration/surveyor batch: every `(x, y)` any awake
    agent has come within `EXPLORATION_VISION_RADIUS` of — the
    settlement's own accumulated "we've been there" knowledge, written
    by `Population._mark_explored` (every awake agent contributes, not
    only SURVEYOR-occupation agents, but a surveyor's forced EXPLORE
    goal deliberately biases toward the frontier rather than re-walking
    already-known ground near home). Never shrinks. Serialized as a
    sorted list of `[x, y]` pairs (see `to_dict`/`from_dict`) since JSON
    has no native set/tuple type."""
    exploration_findings: list[dict] = field(default_factory=list)
    """Capped (EXPLORATION_FINDINGS_MAX) log of notable content a
    surveyor's exploration turned up — `{tick, x, y, kind, description}`
    — a mineral vein, a wild resource node, another settlement, or a
    good farmland site, discovered outside the settlement's own already-
    known territory. The concrete "feed findings back to town" payoff:
    fission site search (`Population.fission_candidate`) prefers a
    surveyed-good site over blind local search when one exists."""
    institutions: list["Institution"] = field(default_factory=list)
    """Persistent entities the population organizes into — v1 only
    forms FAMILY institutions, automatically, on a child's birth (H3,
    docs/ROADMAP.md "Phase H"). Lives on Culture rather than a new
    fifth domain: an institution is "part of what the village has
    become," the same category traditions/beliefs already occupy, and
    this avoids a facade-wide passthrough churn for one new list."""
    next_institution_id: int = 0
    districts: list["District"] = field(default_factory=list)
    """D6 (docs/ROADMAP-2026-07-REMAINING.md, "social scaling beyond
    several hundred/one thousand villagers"): once this settlement's
    individually-simulated non-core population crosses `district.
    DISTRICT_INDIVIDUAL_CAP`, the excess is collectivized here instead
    — see `hearthmind.settlement.district`'s module docstring. Lives on
    Culture next to `institutions` for the same reason that field does
    (avoids a facade-wide passthrough churn for one new list)."""
    next_district_id: int = 0
    rituals: list[dict] = field(default_factory=list)
    """Phase M (docs/VISION-2026-07.md, "Faith & Meaning"): `{"pattern":
    str, "description": str, "formed_tick": int}` — deterministic, free
    detection of repeated real coincidence (SimulationEngine.
    _detect_ritual_signals/_maybe_promote_ritual), not an LLM guess.
    Once a pattern (a repeated festival, a death mourned at a standing
    shrine) recurs `RITUAL_PROMOTION_THRESHOLD` times, it's promoted
    here. This is the raw material `_maybe_schedule_religion` is later
    allowed to reason about — accumulating rituals doesn't itself cost
    a call. Capped at RITUAL_MAX_STORED."""
    ritual_signal_counts: dict = field(default_factory=dict)
    """pattern key -> running occurrence count, the working state behind
    `rituals` above — NOT itself surfaced as "the village's culture" (a
    count of 1 or 2 isn't a ritual yet). Cleared for a pattern once it's
    promoted, so a pattern can't re-promote a duplicate entry."""
    pattern_signal_counts: dict = field(default_factory=dict)
    """"the LLM (and the town) learns like a human" batch: `dispute_
    feud`/`starvation_death` running occurrence counts, same shape and
    discipline as `ritual_signal_counts` above (accumulate, threshold-
    check, consume-and-reset — never itself surfaced directly). Read by
    `SimulationEngine._maybe_schedule_beliefs` to fold one extra
    deterministic, zero-LLM-cost "pattern noticed" grounding sentence
    into the belief-forming prompt once a count crosses `PATTERN_
    SIGNAL_BELIEF_THRESHOLD` — gives the settlement-wide belief job a
    chance to notice and name a *recurring* hardship (several bitter
    feuds, several starvation deaths) rather than only ever reacting to
    whichever single event happens to be freshest in the recency-sliced
    event window."""
    recent_goal_counts: dict = field(default_factory=dict)
    """Phase 1.C "self-evolving world" (docs/VISION-2026-07-21-
    SELFEVOLVING.md) — goal-value -> count, tallying every REAL
    per-agent goal decision this settlement's population has actually
    made since the last town_brain call (`SimulationEngine.
    _apply_pending_cognition_results`, the single choke point every
    LLM-decided or forced-survival goal passes through — deliberately
    NOT incremented for a player-issued `/intervene` goal nudge or the
    surveyor's permanently-forced EXPLORE, neither of which is a real
    NPC decision). Read once by `_maybe_schedule_town_brain` as a
    concrete "what have people actually been doing lately" grounding
    line, then reset to `{}` — a since-last-check window, same shape
    `away_digest_since_tick` already uses, so this stays "recent" and
    bounded rather than an ever-growing all-time tally."""
    family_feud_counts: dict = field(default_factory=dict)
    """v0.87.11, "generational feuds between FAMILY institutions"
    (docs/IDEAS-2026-07-EMERGENCE.md §1). Same accumulate/threshold/
    consume-and-reset discipline as `ritual_signal_counts`/`pattern_
    signal_counts` above, but keyed by rival family-institution-id pair
    (`"{min_id}_{max_id}"`, string for JSON round-trip) instead of a
    single pattern name — a running count of `outcome == "feud"`
    dispute results between members of two different FAMILY
    institutions. `SimulationEngine._maybe_schedule_dispute`'s apply()
    increments the relevant pair's count on every feud outcome and
    promotes it into a real `Institution.feuds` entry on both families
    (mirroring `_maybe_promote_ritual`'s shape) once it crosses
    `FAMILY_FEUD_PROMOTION_THRESHOLD` — a repeated PATTERN of conflict
    between two households, not one bad afternoon."""
    religion: dict | None = None
    """Phase M: `{"name": str, "tenets": list[str], "formed_tick": int,
    "schism_of": int | None}` once `_maybe_schedule_religion` (seasonal,
    gated on having enough accumulated `rituals`) genuinely crystallizes
    one — deliberately NOT guaranteed to ever form; the fallback path
    for this job is always "not yet," never an invented placeholder
    faith. `schism_of` is the origin settlement's id when this religion
    is a fissioned offshoot (see `llm/fission.py`'s optional schism
    field) rather than an independently-formed one. Tenets are also
    pushed as one representative entry into `beliefs` above (and
    institution-mirrored through the same `beliefs.sync_*` helpers
    every other belief uses) so every existing beliefs-consumer already
    picks this up for free."""
    narrative_themes: list[dict] = field(default_factory=list)
    """Phase M "Narrative Direction": `{"themes": list[str], "formed_
    tick": int}`, quarterly (season_end-gated, one LLM call reading
    chronicle + folklore + mood trajectory). Consumed ONLY as prompt
    bias — town_brain/omens/chronicle/dream read `narrative_themes[-1]`
    for a "current theme" line — never schedules or scripts an event on
    its own. Capped at NARRATIVE_THEMES_MAX_STORED."""
    laws: list[dict] = field(default_factory=list)
    """§7 item 7 ("Laws, customs, taboos") + item 8's "politics" ask:
    `{"text": str, "kind": str, "formed_tick": int}` (kind is one of
    "law"/"custom"/"taboo"). `SimulationEngine._maybe_schedule_laws`
    (seasonal, gated on accumulated `pattern_signal_counts`/`family_
    feud_counts` texture — the same "spend the call only once real
    material exists" discipline as `religion`) may codify a norm in
    direct response to a recurring hardship the village has actually
    lived through. Never fabricated by the fallback (a genuine no-op,
    same as `religion`'s "not yet"). Consumed by `dispute.py` (a
    matching law biases the outcome harsher) and `Population._maybe_
    commit_theft` (a law against theft sharpens the trust penalty).
    Capped at LAWS_MAX_STORED."""
    law_signal_counts: dict = field(default_factory=dict)
    """Working accumulator behind `laws` above, same accumulate/
    threshold/consume-and-reset shape as `pattern_signal_counts` —
    currently keyed by `"theft"`/`"feud"`."""
    lexicon: list[dict] = field(default_factory=list)
    """§2 "dialect drift" (docs/IDEAS-2026-07-EMERGENCE.md): `{"term":
    str, "meaning": str, "formed_tick": int}` — rides `narrative_
    direction`'s existing quarterly call (zero added LLM volume) via
    its optional `coined_term`/`coined_meaning` fields, only populated
    when one event has genuinely dominated a settlement's recent life
    enough to earn its own name. Consumed by `dialogue.py` as grounding
    so a settlement's own conversations gradually prefer its own words
    — two settlements descended from one fission slowly stop sounding
    alike. Capped at LEXICON_MAX_STORED."""
    recent_topics: list[str] = field(default_factory=list)
    """§9 "diversify cultural topics" + "competing narratives"
    (docs/IDEAS-2026-07-EMERGENCE.md): a settlement-WIDE ring of every
    genuine LLM-authored dialogue topic (`Population.dialogue_topics`
    is per-PAIR only — this generalizes the same signal to settlement
    scope, zero added LLM volume). Appended by `SimulationEngine.
    _apply_pending_dialogue_results` alongside the existing per-pair
    `record_dialogue_topic` call, capped at RECENT_TOPICS_MAX_STORED.
    `top_topics()` derives frequency counts from this on demand — no
    separate counter dict to keep in sync."""
    lineage_depth: int = 0
    """A7 follow-up (roadmap Tier 3 item 18, docs/ROADMAP-2026-07-
    REMAINING.md): 0 for the founding settlement, `parent.lineage_
    depth + 1` for a daughter born by fission — makes `dialect_grammar.
    drift_term`'s single-application rule into a genuine RECURSIVE
    rewrite system: a term inherited N fissions removed from its
    origin has drifted N compounding rounds by the time it's grounded
    in a granddaughter's own lexicon, not just one flat mutation no
    matter how far removed. See `SimulationEngine._maybe_schedule_
    fission`'s apply()."""
    layout_style: str | None = None
    """A7 (roadmap Tier 3): `None` means "no lineage recorded" — the
    founding settlement, or a legacy snapshot predating this field —
    and reads as `layout_grammar.settlement_layout_style(id)` (the
    original flat hash) via `Settlement.effective_layout_style`, byte-
    identical to pre-A7 behavior. A fission daughter gets a REAL value
    here, written by `layout_grammar.drift_layout_style` from its
    parent's own `effective_layout_style` — closes the item's own
    critique that layout stayed "a single-application scoring bias"
    with zero lineage awareness, unlike dialect's already-recursive
    `drift_term`/architecture's per-instance descriptor."""

    def record_topic(self, topic: str) -> None:
        if not topic:
            return
        # A17's shared "compete" step: a near-restatement of a recently
        # seen topic collapses to the existing phrasing rather than
        # being tracked as a genuinely separate entry — see TOPIC_
        # MERGE_OVERLAP's docstring.
        merged = find_near_duplicate(topic, self.recent_topics, TOPIC_MERGE_OVERLAP)
        self.recent_topics.append(merged if merged is not None else topic)
        if len(self.recent_topics) > RECENT_TOPICS_MAX_STORED:
            del self.recent_topics[: len(self.recent_topics) - RECENT_TOPICS_MAX_STORED]

    def top_topics(self, n: int = 3) -> list[tuple[str, int]]:
        """The `n` most frequent entries in `recent_topics`, most-common
        first (ties broken by first-seen order) — "what the village has
        lately been talking about," consumed as a dialogue steering
        line (item 1) and surfaced directly in the main UI as the
        settlement's "currently running storylines" (item 6) without
        needing a second, parallel tracking structure."""
        if not self.recent_topics:
            return []
        counts: dict[str, int] = {}
        for topic in self.recent_topics:
            counts[topic] = counts.get(topic, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], self.recent_topics.index(kv[0])))[:n]


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
    omen_seed: str = ""
    """Phase N: a queued `omen_phrasing_seed` consciousness intervention
    (`llm.consciousness`), consumed and cleared by the next
    `_maybe_schedule_omen` call — same "queued input for the next job"
    shape as `player_influence`, just single-valued and settlement-
    internal rather than player-facing."""
    dream_seed: str = ""
    """Phase N: a queued `dream_symbol_seed` consciousness intervention,
    consumed and cleared by the next `_maybe_schedule_dream` call."""
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
    mood: dict[str, float] = field(default_factory=dict)
    """Phase I "Collective Psychology" (docs/VISION-2026-07.md): the
    settlement-wide reading of hope/fear/grief/suspicion, each -1..1
    (0.0/missing key = neutral, same bounded-random-walk convention as
    `temperament`) — distinct from `temperament`'s event-fortune signal.
    `tick_mood` derives each axis monthly from the *aggregate* of this
    settlement's own living agents' `Agent.emotions` (joy->hope,
    fear->fear, grief->grief, anger->suspicion — widespread anger reading
    as a suspicious village is the one non-obvious mapping, see
    `tick_mood`'s docstring), so this is literally "individual minds
    aggregate into collective psychology," the layer directly above
    `Agent.emotions` in the vision's hierarchy. Biases prompts and small
    deterministic rates the same non-dominant way temperament does;
    never labeled "mood" in the UI (same ambiguity discipline)."""
    prophecy: dict | None = None
    """§3 "self-fulfilling prophecy" (docs/IDEAS-2026-07-EMERGENCE.md):
    `{"text": str, "tone": "ominous"|"hopeful", "formed_tick": int,
    "resolve_tick": int, "status": "pending"|"confirmed"|"forgotten"}`
    — a rare, vague forward-looking line riding `llm/omens.py`'s
    existing monthly call (`PROPHECY_CHANCE`). While `status ==
    "pending"`, it's folded into cognition/town_brain as one more
    grounding input (a fearful reading biases toward stockpiling, a
    hopeful one toward building) — nothing in the engine ever makes it
    true; if the village *acts* on it, that's the villagers' own doing
    manufacturing the confirming evidence. Resolved deterministically
    at `resolve_tick` (`SimulationEngine._maybe_resolve_prophecy`) by
    checking whether a matching hardship/prosperity event actually
    occurred in the settlement's own event record during the window —
    confirmed or forgotten either way, then cleared so at most one
    prophecy is ever live at a time."""
    last_intervention_tick: int = -1
    """§3 "the observer enters the theology": the last tick a queued
    `/intervene/*` item actually applied to this settlement — read
    (never written) by `_maybe_schedule_beliefs` to decide whether a
    recent event is close enough to a real player nudge to invite the
    beliefs job to optionally attribute it to a nameless something
    ("the Quiet Neighbor"), worded so it could equally be superstition.
    -1 (never intervened) is the common case for most worlds."""
    predecessor_id: int | None = None
    """§5 "Ruins mode / successor worlds" (docs/IDEAS-2026-07-EMERGENCE.
    md): set only on a settlement founded via `SimulationEngine._found_
    successor_world` — the id of the defunct settlement (population 0,
    its ruins/memorials/records/place_names left exactly as they were)
    this settlement was founded to succeed, on the SAME map. Read (never
    written elsewhere) by `llm/beliefs.py` to fold in one optional
    grounding line inviting a theory about the old ruins/records that
    may misread them — "they got the old stories wrong" is a feature of
    the new settlement's imperfect knowledge, not a bug. None for every
    ordinary settlement (founding or fission-born)."""
    social_hub_agent_id: str | None = None
    """A16 "Graph algorithms" (docs/MASTERCHECKLIST-2026-07-22.md,
    roadmap Stage I step 3): the living agent with the highest weighted-
    degree centrality in this settlement's relationship graph (`world.
    graph_algorithms.most_central_agent`), recomputed on a season
    cadence by `SimulationEngine._detect_social_hub`. A structural fact
    ("who the village's social network actually centers on"), not an
    LLM judgment — zero added LLM volume. `None` until the first
    computation or if the settlement has no living agents with any
    relationship edges yet."""


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
        era: str = "stone_age", era_branch: str = "",
        founding_scenario: str = "", llm_named: bool = False, temperament: float = 0.0,
        beliefs: list[dict] | None = None, belief_digest: str = "", culture_digest: str = "",
        folklore: list[dict] | None = None, legends: list[dict] | None = None,
        folklore_persistence_count: int = 0, folklore_persistence_promoted: bool = False,
        omen_history: list[dict] | None = None,
        player_standing: float = 0.0, traditions_established: int = 0, festivals_held: int = 0,
        institutions: list[Institution] | None = None, next_institution_id: int = 0,
        districts: list[District] | None = None, next_district_id: int = 0,
        caravans_visited: int = 0, fish_caught: int = 0, market_prices: dict | None = None,
        buildings_repaired: int = 0, vehicles_repaired: int = 0,
        relations: dict[int, float] | None = None,
        memorials: list[dict] | None = None, place_names: dict | None = None,
        records: list[dict] | None = None, id: int = 0,
        center_x: int = -1, center_y: int = -1,
        mood: dict[str, float] | None = None,
        rituals: list[dict] | None = None, ritual_signal_counts: dict | None = None,
        religion: dict | None = None, narrative_themes: list[dict] | None = None,
        omen_seed: str = "", dream_seed: str = "",
        pattern_signal_counts: dict | None = None,
        recent_goal_counts: dict | None = None,
        family_feud_counts: dict | None = None,
        invention_knowledge: dict | None = None,
        invention_specializations: dict | None = None,
        laws: list[dict] | None = None, law_signal_counts: dict | None = None,
        thefts_committed: int = 0,
        lexicon: list[dict] | None = None,
        recent_topics: list[str] | None = None,
        lineage_depth: int = 0,
        layout_style: str | None = None,
        pending_letters: list[dict] | None = None,
        prophecy: dict | None = None, last_intervention_tick: int = -1,
        predecessor_id: int | None = None,
        social_hub_agent_id: str | None = None,
        minerals: dict | None = None,
        explored_tiles: set | list | None = None,
        exploration_findings: list[dict] | None = None,
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
            pending_letters=pending_letters if pending_letters is not None else [],
        )
        self.economy = SettlementEconomy(
            materials=materials, currency=currency, education_level=education_level,
            caravans_visited=caravans_visited, fish_caught=fish_caught,
            buildings_repaired=buildings_repaired, vehicles_repaired=vehicles_repaired,
            market_prices=market_prices if market_prices is not None else {},
            thefts_committed=thefts_committed,
            minerals=minerals if minerals is not None else {},
        )
        self.culture = SettlementCulture(
            name=name, founding_scenario=founding_scenario, llm_named=llm_named, era=era, era_branch=era_branch,
            tech_level=tech_level,
            traditions=traditions if traditions is not None else [],
            traditions_established=traditions_established,
            culture_effects=culture_effects if culture_effects is not None else {},
            inventions=inventions if inventions is not None else [],
            invention_knowledge=invention_knowledge if invention_knowledge is not None else {},
            invention_specializations=invention_specializations if invention_specializations is not None else {},
            festivals=festivals if festivals is not None else [],
            festivals_held=festivals_held,
            beliefs=beliefs if beliefs is not None else [],
            belief_digest=belief_digest,
            culture_digest=culture_digest,
            folklore=folklore if folklore is not None else [],
            legends=legends if legends is not None else [],
            folklore_persistence_count=folklore_persistence_count,
            folklore_persistence_promoted=folklore_persistence_promoted,
            place_names=place_names if place_names is not None else {},
            records=records if records is not None else [],
            institutions=institutions if institutions is not None else [],
            next_institution_id=next_institution_id,
            districts=districts if districts is not None else [],
            next_district_id=next_district_id,
            rituals=rituals if rituals is not None else [],
            ritual_signal_counts=ritual_signal_counts if ritual_signal_counts is not None else {},
            pattern_signal_counts=pattern_signal_counts if pattern_signal_counts is not None else {},
            recent_goal_counts=recent_goal_counts if recent_goal_counts is not None else {},
            family_feud_counts=family_feud_counts if family_feud_counts is not None else {},
            religion=religion,
            narrative_themes=narrative_themes if narrative_themes is not None else [],
            laws=laws if laws is not None else [],
            law_signal_counts=law_signal_counts if law_signal_counts is not None else {},
            lexicon=lexicon if lexicon is not None else [],
            recent_topics=recent_topics if recent_topics is not None else [],
            lineage_depth=lineage_depth,
            layout_style=layout_style,
            explored_tiles=set(tuple(t) for t in explored_tiles) if explored_tiles is not None else set(),
            exploration_findings=exploration_findings if exploration_findings is not None else [],
        )
        self.disposition = SettlementDisposition(
            temperament=temperament,
            omen_history=omen_history if omen_history is not None else [],
            player_standing=player_standing,
            player_influence=player_influence if player_influence is not None else [],
            current_priority=current_priority, priority_rationale=priority_rationale,
            priority_history=priority_history if priority_history is not None else [],
            relations=relations if relations is not None else {},
            mood=mood if mood is not None else {},
            omen_seed=omen_seed, dream_seed=dream_seed,
            prophecy=prophecy, last_intervention_tick=last_intervention_tick,
            predecessor_id=predecessor_id,
            social_hub_agent_id=social_hub_agent_id,
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
    def buildings_repaired(self) -> int:
        return self.economy.buildings_repaired

    @buildings_repaired.setter
    def buildings_repaired(self, value: int) -> None:
        self.economy.buildings_repaired = value

    @property
    def vehicles_repaired(self) -> int:
        return self.economy.vehicles_repaired

    @vehicles_repaired.setter
    def vehicles_repaired(self, value: int) -> None:
        self.economy.vehicles_repaired = value

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
    def era_branch(self) -> str:
        return self.culture.era_branch

    @era_branch.setter
    def era_branch(self, value: str) -> None:
        self.culture.era_branch = value

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
    def invention_knowledge(self) -> dict:
        return self.culture.invention_knowledge

    @invention_knowledge.setter
    def invention_knowledge(self, value: dict) -> None:
        self.culture.invention_knowledge = value

    @property
    def invention_specializations(self) -> dict:
        return self.culture.invention_specializations

    @invention_specializations.setter
    def invention_specializations(self, value: dict) -> None:
        self.culture.invention_specializations = value

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
    def belief_digest(self) -> str:
        return self.culture.belief_digest

    @belief_digest.setter
    def belief_digest(self, value: str) -> None:
        self.culture.belief_digest = value

    @property
    def culture_digest(self) -> str:
        return self.culture.culture_digest

    @culture_digest.setter
    def culture_digest(self, value: str) -> None:
        self.culture.culture_digest = value

    @property
    def folklore(self) -> list[dict]:
        return self.culture.folklore

    @folklore.setter
    def folklore(self, value: list[dict]) -> None:
        self.culture.folklore = value

    @property
    def legends(self) -> list[dict]:
        return self.culture.legends

    @legends.setter
    def legends(self, value: list[dict]) -> None:
        self.culture.legends = value

    @property
    def folklore_persistence_count(self) -> int:
        return self.culture.folklore_persistence_count

    @folklore_persistence_count.setter
    def folklore_persistence_count(self, value: int) -> None:
        self.culture.folklore_persistence_count = value

    @property
    def folklore_persistence_promoted(self) -> bool:
        return self.culture.folklore_persistence_promoted

    @folklore_persistence_promoted.setter
    def folklore_persistence_promoted(self, value: bool) -> None:
        self.culture.folklore_persistence_promoted = value

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
    def districts(self) -> list[District]:
        return self.culture.districts

    @districts.setter
    def districts(self, value: list[District]) -> None:
        self.culture.districts = value

    @property
    def next_district_id(self) -> int:
        return self.culture.next_district_id

    @next_district_id.setter
    def next_district_id(self, value: int) -> None:
        self.culture.next_district_id = value

    @property
    def rituals(self) -> list[dict]:
        return self.culture.rituals

    @rituals.setter
    def rituals(self, value: list[dict]) -> None:
        self.culture.rituals = value

    @property
    def ritual_signal_counts(self) -> dict:
        return self.culture.ritual_signal_counts

    @ritual_signal_counts.setter
    def ritual_signal_counts(self, value: dict) -> None:
        self.culture.ritual_signal_counts = value

    @property
    def pattern_signal_counts(self) -> dict:
        return self.culture.pattern_signal_counts

    @pattern_signal_counts.setter
    def pattern_signal_counts(self, value: dict) -> None:
        self.culture.pattern_signal_counts = value

    @property
    def recent_goal_counts(self) -> dict:
        return self.culture.recent_goal_counts

    @recent_goal_counts.setter
    def recent_goal_counts(self, value: dict) -> None:
        self.culture.recent_goal_counts = value

    @property
    def family_feud_counts(self) -> dict:
        return self.culture.family_feud_counts

    @family_feud_counts.setter
    def family_feud_counts(self, value: dict) -> None:
        self.culture.family_feud_counts = value

    @property
    def laws(self) -> list[dict]:
        return self.culture.laws

    @laws.setter
    def laws(self, value: list[dict]) -> None:
        self.culture.laws = value

    @property
    def law_signal_counts(self) -> dict:
        return self.culture.law_signal_counts

    @law_signal_counts.setter
    def law_signal_counts(self, value: dict) -> None:
        self.culture.law_signal_counts = value

    @property
    def thefts_committed(self) -> int:
        return self.economy.thefts_committed

    @thefts_committed.setter
    def thefts_committed(self, value: int) -> None:
        self.economy.thefts_committed = value

    @property
    def lexicon(self) -> list[dict]:
        return self.culture.lexicon

    @lexicon.setter
    def lexicon(self, value: list[dict]) -> None:
        self.culture.lexicon = value

    @property
    def lineage_depth(self) -> int:
        return self.culture.lineage_depth

    @lineage_depth.setter
    def lineage_depth(self, value: int) -> None:
        self.culture.lineage_depth = value

    @property
    def layout_style(self) -> str | None:
        return self.culture.layout_style

    @layout_style.setter
    def layout_style(self, value: str | None) -> None:
        self.culture.layout_style = value

    @property
    def effective_layout_style(self) -> str:
        """The real value to actually use — `layout_style` if this
        settlement has a real lineage-derived one (a fission daughter),
        else the original id-derived hash (the founding settlement, or
        a legacy snapshot). See `layout_style`'s own docstring."""
        if self.culture.layout_style is not None:
            return self.culture.layout_style
        return settlement_layout_style(self.id)

    @property
    def recent_topics(self) -> list[str]:
        return self.culture.recent_topics

    @recent_topics.setter
    def recent_topics(self, value: list[str]) -> None:
        self.culture.recent_topics = value

    def record_topic(self, topic: str) -> None:
        self.culture.record_topic(topic)

    def top_topics(self, n: int = 3) -> list[tuple[str, int]]:
        return self.culture.top_topics(n)

    @property
    def religion(self) -> dict | None:
        return self.culture.religion

    @religion.setter
    def religion(self, value: dict | None) -> None:
        self.culture.religion = value

    @property
    def narrative_themes(self) -> list[dict]:
        return self.culture.narrative_themes

    @narrative_themes.setter
    def narrative_themes(self, value: list[dict]) -> None:
        self.culture.narrative_themes = value

    @property
    def memorials(self) -> list[dict]:
        return self.infrastructure.memorials

    @memorials.setter
    def memorials(self, value: list[dict]) -> None:
        self.infrastructure.memorials = value

    @property
    def pending_letters(self) -> list[dict]:
        return self.infrastructure.pending_letters

    @pending_letters.setter
    def pending_letters(self, value: list[dict]) -> None:
        self.infrastructure.pending_letters = value

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
    def explored_tiles(self) -> set:
        return self.culture.explored_tiles

    @explored_tiles.setter
    def explored_tiles(self, value: set) -> None:
        self.culture.explored_tiles = value

    @property
    def exploration_findings(self) -> list[dict]:
        return self.culture.exploration_findings

    @exploration_findings.setter
    def exploration_findings(self, value: list[dict]) -> None:
        self.culture.exploration_findings = value

    @property
    def market_prices(self) -> dict:
        return self.economy.market_prices

    @property
    def minerals(self) -> dict:
        return self.economy.minerals

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
    def mood(self) -> dict[str, float]:
        return self.disposition.mood

    @mood.setter
    def mood(self, value: dict[str, float]) -> None:
        self.disposition.mood = value

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
    def omen_seed(self) -> str:
        return self.disposition.omen_seed

    @omen_seed.setter
    def omen_seed(self, value: str) -> None:
        self.disposition.omen_seed = value

    @property
    def dream_seed(self) -> str:
        return self.disposition.dream_seed

    @dream_seed.setter
    def dream_seed(self, value: str) -> None:
        self.disposition.dream_seed = value

    @property
    def prophecy(self) -> dict | None:
        return self.disposition.prophecy

    @prophecy.setter
    def prophecy(self, value: dict | None) -> None:
        self.disposition.prophecy = value

    @property
    def last_intervention_tick(self) -> int:
        return self.disposition.last_intervention_tick

    @last_intervention_tick.setter
    def last_intervention_tick(self, value: int) -> None:
        self.disposition.last_intervention_tick = value

    @property
    def predecessor_id(self) -> int | None:
        return self.disposition.predecessor_id

    @predecessor_id.setter
    def predecessor_id(self, value: int | None) -> None:
        self.disposition.predecessor_id = value

    @property
    def social_hub_agent_id(self) -> str | None:
        return self.disposition.social_hub_agent_id

    @social_hub_agent_id.setter
    def social_hub_agent_id(self, value: str | None) -> None:
        self.disposition.social_hub_agent_id = value

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
        bridge_span: tuple[tuple[int, int], ...] = (),
    ) -> Building:
        building = Building(
            id=self._next_id, x=x, y=y, kind=kind, owner_agent_id=owner_agent_id, bridge_span=bridge_span,
        )
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

    def tick(
        self, weather: WeatherState, season: str = "summer",
        ruin_scars: dict[tuple[int, int], float] | None = None,
        material_decay_factors: dict[int, float] | None = None,
    ) -> list[tuple[str, str]]:
        """Weather- and season-driven decay of standing buildings into
        ruins, and eventual removal of long-abandoned ruins. Returns
        life-cycle events as (category, description) pairs.
        Construction/repair progress (which needs agent presence) is
        handled separately by Population.tick, since Settlement has no
        agent awareness.

        A3 (roadmap Stage IV step 28): `ruin_scars` (optional —
        `World.ruin_scars`, `None` reproduces the exact pre-A3
        behavior for any caller without a `World` in scope) records a
        real, slow-decaying mark at a building's position the instant
        it's fully reclaimed, so a dead settlement's ground keeps a
        trace long after its last ruin physically crumbles away.

        A5/A6 (roadmap Tier 3): `material_decay_factors` (optional,
        keyed by `Building.id`, `None` reproducing the exact pre-A5/A6
        flat rate) is the per-instance material-driven decay multiplier
        `world/materials.py`'s `material_decay_factor` computes — this
        module can't compute it directly (`world.materials` imports
        `BuildingKind` FROM here, so the reverse import would be
        circular), so the caller (`World.tick`, which already imports
        both) resolves it once per building and passes the finished
        dict down, same "compute where both dependencies already meet"
        shape `nature_adaptation_bias` uses for `decay_disaster_scars`.
        A building with no entry (or `None` outright) decays at exactly
        1.0x — the old flat rate, unchanged."""
        events: list[tuple[str, str]] = []
        survivors: list[Building] = []

        weather_catalyst = _weather_decay_catalyst(weather)
        decay = (
            DECAY_PER_TICK_BASE * weather_catalyst
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
                (
                    _bstage_in[b.stage], b.condition, b.kind is BuildingKind.HUT, b.ruined_ticks,
                    material_decay_factors.get(b.id, 1.0) if material_decay_factors is not None else 1.0,
                )
                for b in self.buildings
            ]
            results = _native_building_decay_tick(inputs, decay, civic_decay, RUIN_REMOVAL_TICKS)
            for building, (stage, condition, ruined_ticks, removed, just_ruined) in zip(self.buildings, results):
                if removed:
                    events.append(
                        ("building_reclaimed", f"Nature reclaimed the ruins at ({building.x}, {building.y}).")
                    )
                    if ruin_scars is not None:
                        apply_ruin_scar((building.x, building.y), ruin_scars)
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
                    if material_decay_factors is not None:
                        building_decay *= material_decay_factors.get(building.id, 1.0)
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
                        if ruin_scars is not None:
                            apply_ruin_scar((building.x, building.y), ruin_scars)
                        continue  # dropped from survivors — removed from the world

                survivors.append(building)

        if len(survivors) != len(self.buildings):
            self._position_index = None  # a ruin was reclaimed — see at()'s cache
        self.buildings = survivors

        # Vehicles get the same catalysts as buildings, scaled down —
        # same ratio the old flat multipliers had (2.0 vs 3.0: vehicles
        # feel 2/3 of a building's excess weather wear, not all of it).
        vehicle_weather_catalyst = 1.0 + (weather_catalyst - 1.0) * VEHICLE_DECAY_CATALYST_SCALE
        vehicle_decay = (
            VEHICLE_DECAY_PER_TICK_BASE * vehicle_weather_catalyst
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

    def summary(self, established_roads: int = 0) -> dict:
        """`established_roads` (v9's "stalled era progression" fix): the
        caller's own world-wide `RoadNetwork.summary()["established_
        roads"]` count, threaded in since `Settlement` has no reference
        to `World.roads` (roads aren't settlement-scoped) — see
        `World.summary()`/`SimulationEngine`'s `settlement_summaries`
        call sites. Omitting it (the default) just reads as "no roads
        yet" for `era_infrastructure` below; every real call site
        supplies the actual count."""
        under_construction = sum(1 for b in self.buildings if b.stage is BuildingStage.UNDER_CONSTRUCTION)
        standing = [b for b in self.buildings if b.stage is BuildingStage.STANDING]
        ruined = sum(1 for b in self.buildings if b.stage is BuildingStage.RUINED)
        avg_condition = sum(b.condition for b in standing) / len(standing) if standing else 0.0
        granaries = [b for b in standing if b.kind is BuildingKind.GRANARY]
        pastures = [b for b in standing if b.kind is BuildingKind.PASTURE]
        hatcheries = [b for b in standing if b.kind is BuildingKind.HATCHERY]
        huts_standing = sum(1 for b in standing if b.kind is BuildingKind.HUT)
        kind_counts = {
            kind.value: sum(1 for b in standing if b.kind is kind)
            for kind in (
                BuildingKind.WORKSHOP, BuildingKind.SCHOOL, BuildingKind.HOSPITAL,
                BuildingKind.UNIVERSITY, BuildingKind.FACTORY, BuildingKind.SHRINE,
                BuildingKind.POWER_PLANT, BuildingKind.MARKET,
                BuildingKind.DOCK, BuildingKind.OIL_RIG,
                BuildingKind.FORGE, BuildingKind.LIBRARY, BuildingKind.SMELTER,
            )
        }
        vehicle_summary = self._vehicle_summary()
        next_era_index = ERA_ORDER.index(self.era) + 1 if self.era in ERA_ORDER else len(ERA_ORDER)
        if next_era_index < len(ERA_ORDER):
            next_era = ERA_ORDER[next_era_index]
            requirement = ERA_INFRASTRUCTURE_REQUIREMENTS.get(next_era, {})
            era_infrastructure = {
                "next_era": next_era,
                "requirement": dict(requirement),
                "current": {
                    "huts": huts_standing, "roads": established_roads,
                    "schools": kind_counts["school"], "carts": vehicle_summary["carts_ready"],
                },
                "progress": round(
                    era_infrastructure_progress(
                        next_era, huts_standing, established_roads, kind_counts["school"],
                        vehicle_summary["carts_ready"],
                    ), 3,
                ),
            }
        else:
            era_infrastructure = None  # already at the last era — nothing further to work toward
        return {
            "id": self.id,
            "center": self.center(),
            "layout_style": self.effective_layout_style,
            "total": len(self.buildings),
            "under_construction": under_construction,
            "standing": len(standing),
            "ruined": ruined,
            "avg_condition": round(avg_condition, 3),
            "granaries": len(granaries),
            "granary_food": round(sum(b.stored_food for b in granaries), 3),
            "granary_capacity": round(len(granaries) * GRANARY_CAPACITY, 3),
            "pastures": len(pastures),
            "pasture_food": round(sum(b.stored_food for b in pastures), 3),
            "pasture_capacity": round(len(pastures) * PASTURE_CAPACITY, 3),
            "hatcheries": len(hatcheries),
            "hatchery_food": round(sum(b.stored_food for b in hatcheries), 3),
            "hatchery_capacity": round(len(hatcheries) * HATCHERY_CAPACITY, 3),
            "materials": round(self.materials, 3),
            "materials_capacity": MATERIALS_CAPACITY,
            "currency": round(self.currency, 3),
            "currency_capacity": CURRENCY_CAPACITY,
            "name": self.name,
            "traditions": list(self.traditions),
            "culture_effects": dict(self.culture_effects),
            "tech_level": self.tech_level,
            "inventions": list(self.inventions),
            "invention_knowledge": self.invention_knowledge,
            "invention_specializations": dict(self.invention_specializations),
            "festivals": list(self.festivals),
            "vehicles": vehicle_summary,
            "workshops": kind_counts["workshop"],
            "schools": kind_counts["school"],
            "hospitals": kind_counts["hospital"],
            "universities": kind_counts["university"],
            "factories": kind_counts["factory"],
            "shrines": kind_counts["shrine"],
            "power_plants": kind_counts["power_plant"],
            "markets": kind_counts["market"],
            "docks": kind_counts["dock"],
            "oil_rigs": kind_counts["oil_rig"],
            "forges": kind_counts["forge"],
            "libraries": kind_counts["library"],
            "smelters": kind_counts["smelter"],
            "caravans_visited": self.caravans_visited,
            "fish_caught": self.fish_caught,
            "buildings_repaired": self.buildings_repaired,
            "vehicles_repaired": self.vehicles_repaired,
            "market_prices": dict(self.market_prices),
            "minerals": {k: round(v, 3) for k, v in self.minerals.items()},
            "place_names": dict(self.place_names),
            "records": list(self.records),
            "explored_tile_count": len(self.explored_tiles),
            "exploration_findings": list(self.exploration_findings[-8:]),
            "education_level": round(self.education_level, 3),
            "education_capacity": EDUCATION_CAPACITY,
            "current_priority": self.current_priority,
            "priority_rationale": self.priority_rationale,
            "priority_history": list(self.priority_history),
            "pending_player_whispers": list(self.player_influence),
            "era": self.era,
            "era_description": ERA_DESCRIPTIONS.get(self.era, ""),
            "era_branch": self.era_branch,
            "era_infrastructure": era_infrastructure,
            "founding_scenario": self.founding_scenario,
            "llm_named": self.llm_named,
            "beliefs": list(self.beliefs),
            "belief_digest": self.belief_digest,
            "culture_digest": self.culture_digest,
            "folklore": list(self.folklore),
            "legends": list(self.legends),
            "temperament": round(self.temperament, 3),
            "mood": {k: round(v, 3) for k, v in self.mood.items()},
            "omen_history": list(self.omen_history),
            "player_standing": round(self.player_standing, 3),
            "relations": {str(k): round(v, 3) for k, v in self.relations.items()},
            "institutions": {
                "total": len(self.institutions),
                "families": sum(1 for i in self.institutions if i.kind is InstitutionKind.FAMILY),
                "councils": sum(1 for i in self.institutions if i.kind is InstitutionKind.COUNCIL),
                "guilds": [i.name for i in self.institutions if i.kind is InstitutionKind.GUILD],
                "factions": [i.name for i in self.institutions if i.kind is InstitutionKind.FACTION],
            },
            "districts": {
                "count": len(self.districts),
                "collectivized_population": sum(d.population for d in self.districts),
                "names": [d.name for d in self.districts],
            },
            "rituals": list(self.rituals),
            "religion": dict(self.religion) if self.religion is not None else None,
            "narrative_themes": list(self.narrative_themes),
            "omen_seed": self.omen_seed,
            "dream_seed": self.dream_seed,
            "laws": list(self.laws),
            "thefts_committed": self.thefts_committed,
            "lexicon": list(self.lexicon),
            "lineage_depth": self.lineage_depth,
            "top_topics": self.top_topics(),
            "prophecy": dict(self.prophecy) if self.prophecy is not None else None,
            "predecessor_id": self.predecessor_id,
            "social_hub_agent_id": self.social_hub_agent_id,
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
        boats = [v for v in self.vehicles if v.kind is VehicleKind.BOAT]
        ready_carts = [v for v in carts if v.stage is VehicleStage.READY]
        ready_mounts = [v for v in mounts if v.stage is VehicleStage.READY]
        ready_automobiles = [v for v in automobiles if v.stage is VehicleStage.READY]
        ready_rafts = [v for v in rafts if v.stage is VehicleStage.READY]
        ready_boats = [v for v in boats if v.stage is VehicleStage.READY]
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
            "boats_total": len(boats),
            "boats_ready": len(ready_boats),
            "boats_building": sum(1 for v in boats if v.stage is VehicleStage.BUILDING),
            "boats_broken": sum(1 for v in boats if v.stage is VehicleStage.BROKEN),
            "boats_claimed": sum(1 for v in ready_boats if v.assigned_agent_id is not None),
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
            "invention_knowledge": self.invention_knowledge,
            "invention_specializations": dict(self.invention_specializations),
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
            "era_branch": self.era_branch,
            "founding_scenario": self.founding_scenario,
            "llm_named": self.llm_named,
            "beliefs": list(self.beliefs),
            "belief_digest": self.belief_digest,
            "culture_digest": self.culture_digest,
            "folklore": list(self.folklore),
            "legends": list(self.legends),
            "folklore_persistence_count": self.folklore_persistence_count,
            "folklore_persistence_promoted": self.folklore_persistence_promoted,
            "temperament": round(self.temperament, 4),
            "mood": {k: round(v, 4) for k, v in self.mood.items()},
            "omen_history": list(self.omen_history),
            "player_standing": round(self.player_standing, 4),
            "relations": {str(k): round(v, 4) for k, v in self.relations.items()},
            "institutions": [i.to_dict() for i in self.institutions],
            "next_institution_id": self.next_institution_id,
            "districts": [d.to_dict() for d in self.districts],
            "next_district_id": self.next_district_id,
            "caravans_visited": self.caravans_visited,
            "fish_caught": self.fish_caught,
            "buildings_repaired": self.buildings_repaired,
            "vehicles_repaired": self.vehicles_repaired,
            "market_prices": dict(self.market_prices),
            "minerals": dict(self.minerals),
            "memorials": list(self.memorials),
            "place_names": dict(self.place_names),
            "records": list(self.records),
            "explored_tiles": sorted([x, y] for x, y in self.explored_tiles),
            "exploration_findings": list(self.exploration_findings),
            "rituals": list(self.rituals),
            "ritual_signal_counts": dict(self.ritual_signal_counts),
            "pattern_signal_counts": dict(self.pattern_signal_counts),
            "recent_goal_counts": dict(self.recent_goal_counts),
            "family_feud_counts": dict(self.family_feud_counts),
            "religion": dict(self.religion) if self.religion is not None else None,
            "narrative_themes": list(self.narrative_themes),
            "omen_seed": self.omen_seed,
            "dream_seed": self.dream_seed,
            "laws": list(self.laws),
            "law_signal_counts": dict(self.law_signal_counts),
            "thefts_committed": self.thefts_committed,
            "lexicon": list(self.lexicon),
            "lineage_depth": self.lineage_depth,
            "layout_style": self.layout_style,
            "recent_topics": list(self.recent_topics),
            "pending_letters": list(self.pending_letters),
            "prophecy": dict(self.prophecy) if self.prophecy is not None else None,
            "last_intervention_tick": self.last_intervention_tick,
            "predecessor_id": self.predecessor_id,
            "social_hub_agent_id": self.social_hub_agent_id,
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
            invention_knowledge=dict(data.get("invention_knowledge", {})),
            invention_specializations=dict(data.get("invention_specializations", {})),
            festivals=list(data.get("festivals", [])),
            festivals_held=data.get("festivals_held", len(data.get("festivals", []))),
            vehicles=vehicles, _next_vehicle_id=data.get("next_vehicle_id", 0),
            education_level=data.get("education_level", 0.0),
            current_priority=data.get("current_priority", ""),
            priority_rationale=data.get("priority_rationale", ""),
            priority_history=list(data.get("priority_history", [])),
            player_influence=list(data.get("player_influence", [])),
            era=data.get("era", "stone_age"),
            era_branch=data.get("era_branch", ""),
            founding_scenario=data.get("founding_scenario", ""),
            llm_named=data.get("llm_named", False),
            beliefs=list(data.get("beliefs", [])),
            belief_digest=data.get("belief_digest", ""),
            culture_digest=data.get("culture_digest", ""),
            folklore=list(data.get("folklore", [])),
            legends=list(data.get("legends", [])),
            folklore_persistence_count=data.get("folklore_persistence_count", 0),
            folklore_persistence_promoted=data.get("folklore_persistence_promoted", False),
            temperament=data.get("temperament", 0.0),
            mood=dict(data.get("mood", {})),
            omen_history=list(data.get("omen_history", [])),
            player_standing=data.get("player_standing", 0.0),
            relations={int(k): v for k, v in data.get("relations", {}).items()},
            institutions=[Institution.from_dict(i) for i in data.get("institutions", [])],
            next_institution_id=data.get("next_institution_id", 0),
            districts=[District.from_dict(d) for d in data.get("districts", [])],
            next_district_id=data.get("next_district_id", 0),
            caravans_visited=data.get("caravans_visited", 0),
            fish_caught=data.get("fish_caught", 0),
            buildings_repaired=data.get("buildings_repaired", 0),
            vehicles_repaired=data.get("vehicles_repaired", 0),
            market_prices=dict(data.get("market_prices", {})),
            minerals=dict(data.get("minerals", {})),
            memorials=list(data.get("memorials", [])),
            place_names=dict(data.get("place_names", {})),
            explored_tiles=data.get("explored_tiles", []),
            exploration_findings=list(data.get("exploration_findings", [])),
            records=list(data.get("records", [])),
            id=data.get("id", 0),
            center_x=data.get("center_x", -1), center_y=data.get("center_y", -1),
            rituals=list(data.get("rituals", [])),
            ritual_signal_counts=dict(data.get("ritual_signal_counts", {})),
            pattern_signal_counts=dict(data.get("pattern_signal_counts", {})),
            recent_goal_counts=dict(data.get("recent_goal_counts", {})),
            family_feud_counts=dict(data.get("family_feud_counts", {})),
            religion=dict(data["religion"]) if data.get("religion") is not None else None,
            narrative_themes=list(data.get("narrative_themes", [])),
            omen_seed=data.get("omen_seed", ""),
            dream_seed=data.get("dream_seed", ""),
            laws=list(data.get("laws", [])),
            law_signal_counts=dict(data.get("law_signal_counts", {})),
            thefts_committed=data.get("thefts_committed", 0),
            lexicon=list(data.get("lexicon", [])),
            lineage_depth=data.get("lineage_depth", 0),
            layout_style=data.get("layout_style"),
            recent_topics=list(data.get("recent_topics", [])),
            pending_letters=list(data.get("pending_letters", [])),
            prophecy=dict(data["prophecy"]) if data.get("prophecy") is not None else None,
            last_intervention_tick=data.get("last_intervention_tick", -1),
            predecessor_id=data.get("predecessor_id"),
            social_hub_agent_id=data.get("social_hub_agent_id"),
        )
