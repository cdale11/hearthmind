"""A1 "Continuous environmental fields" (docs/MASTERCHECKLIST-2026-07-
22.md, Part A, Stage I step 2): a `FieldGrid` abstraction — named
scalar fields over the map, each updated per tick by a local rule.

Deliberately coarse to start, per the roadmap's own scoping: reuses
`WEATHER_REGION_GRID` (3x3, `world/state.py`) rather than a new
per-tile resolution — "the interface (named fields, per-tick update,
cross-field coupling) matters more than resolution day one." Raising
resolution later (once the C++ dense-column store lands, R7) means
swapping this module's storage, not its callers — `get_at`/`step` stay
the same shape at any resolution.

R7 deviation, flagged (same precedent as spatial weather/mining scars/
minerals — CLAUDE.md's R7 section): this is Python, not C++, despite
being new physical-substrate code. A 3x3 grid is 9 cells per field;
even a dozen fields is under 200 floats total, several orders below
the density where a native port would pay for itself. Revisit once
resolution actually rises.

First slice ships one concrete field, `population_density` (agents per
region, normalized against the region with the most): `SimulationEngine.
_maybe_favor_uncrowded_fission_site` reads it to bias new-settlement
site search away from crowded regions — a genuine "settlement siting"
consumer, per A1's own "Feeds" line.

Second slice (A1/A2 together, docs/ROADMAP-2026-07-REMAINING.md Tier 1
items 3-4) ships `disease_pressure` — the second of the eleven other
named fields, chosen because contagion is the single most natural
`diffuse()` consumer in the whole codebase: real sickness IS a
diffusion process, not a metaphorical one. `step_disease_pressure`
recomputes a raw regional sick-fraction census each tick (same "live
census, not an accumulating quantity" shape `population_density`
already established), then spreads it with `world.ca_operators.
diffuse` — contagion risk doesn't respect the coarse region boundary
any more than population density needing a real neighbor-averaging
pass would, and this is A2's stated ask ("the doc calls for a small
general operator library other systems can reuse... today only
succession uses it") getting its second real consumer. `Population.
_maybe_outbreak` weights its index-case draw by the sick agent's own
region's `disease_pressure` instead of a flat uniform choice —
genuinely wet-adjacent regions of the map (regions bordering an
already-sick one) become measurably more likely to seed the NEXT
spontaneous case, not just the literally-already-sick region itself.

Third slice (Tier 1, docs/ROADMAP-2026-07-REMAINING.md) ships
`pollution` — sourced from two already-real Body-state producers
(standing FACTORY/POWER_PLANT/OIL_RIG buildings, `World.mining_scars`)
rather than anything new, then spread via `ca_operators.diffuse` the
same way `disease_pressure` is (industrial fumes/runoff don't respect
the coarse region boundary either). Real consumer: `economy.farms.
FarmGrid.plant()` gained a `pollution` yield-penalty factor, same
bounded-floor shape `moisture` already has — "industry chokes the
fields nearby" is now a mechanical fact, not just a name on a list.

Fourth slice (Tier 1, docs/ROADMAP-2026-07-REMAINING.md) ships
`traffic` — sourced from `World.roads.wear` (already-real per-tile
road-usage state, same shape `mining_scars` gave `pollution`), spread
via `ca_operators.diffuse`. Real consumer: `SimulationEngine._maybe_
schedule_caravan`'s monthly visit chance now scales up with the
target settlement's own region traffic reading — "trade follows
roads" as a mechanical fact, the same kind of real multiplier
`has_market()`/`caravan_relation_factor` already apply to that same
`chance` value.

Fifth slice ships `scarcity` — A4's ("Continuous systems vs. scripted
events," docs/ROADMAP-2026-07-REMAINING.md) own literal ask, "economy
-> resource/price fields that flow." Sourced from each settlement's
already-real granary/materials fill ratios (`settlement.buildings.
compute_resource_fill`, factored out of the existing monthly `tick_
market_prices` so both share one read rather than duplicating the
math) rather than anything new, then spread via `ca_operators.diffuse`
the same way every prior field is. Real consumer: `Population._maybe_
welcome_migrant`'s chance now dampens with the settlement's own region
scarcity reading, same bounded shape `MIGRANT_DENSITY_DAMPENING`
already established for population density — "newcomers are less
drawn to a visibly struggling town" is now a mechanical fact.

The remaining seven named fields (fertility, nutrients, scent, heat,
cultural-influence, ownership, beauty, noise) and migrating `disaster_
scars`/the climate grid onto `FieldGrid` proper remain explicitly NOT
built here — each is its own follow-up step against the same
`FieldGrid`/`ca_operators` shape now proven against five real
fields."""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.util import clamp
from hearthmind.world.ca_operators import diffuse

FIELD_GRID_SIZE = 3
"""Matches `world.state.WEATHER_REGION_GRID` — the same coarse 3x3
region split spatial weather already uses, so a `FieldGrid` field and
a weather region always line up 1:1 without a second coordinate
mapping to maintain."""

DISEASE_PRESSURE_DIFFUSE_RATE = 0.35
"""How strongly `disease_pressure` spreads into a region's neighbors
each tick via `ca_operators.diffuse` — high enough that a region
bordering a real outbreak reads measurably elevated within a handful
of ticks (contagion risk is a regional property, not confined to the
exact region sick agents currently stand in), low enough that pressure
still visibly concentrates near its real source rather than smearing
flat across the whole map."""

POLLUTION_BUILDING_WEIGHT = 1.0
"""Each standing FACTORY/POWER_PLANT/OIL_RIG contributes this much to
its region's raw pollution reading before normalization — the
dominant source; industry is the point-source, mining scars (below)
are the secondary, more diffuse one."""

POLLUTION_MINING_SCAR_WEIGHT = 0.3
"""Each unit of `World.mining_scars` intensity in a region contributes
this fraction as much as one standing industrial building — real but
secondary; a heavily-scarred hillside alone shouldn't read as
polluted as an actual standing factory."""

POLLUTION_DIFFUSE_RATE = 0.3
"""Same role as `DISEASE_PRESSURE_DIFFUSE_RATE` — fumes/runoff from an
industrial region measurably affect its neighbors, not just the exact
region the source sits in, while still concentrating near the real
source rather than smearing flat."""

TRAFFIC_DIFFUSE_RATE = 0.3
"""Same role as `POLLUTION_DIFFUSE_RATE` — a busy road corridor's
traffic naturally reads as elevated in the regions it passes through
and touches, not just the exact tiles carrying the heaviest wear."""

SCARCITY_DIFFUSE_RATE = 0.35
"""Same role as `DISEASE_PRESSURE_DIFFUSE_RATE` — a region neighboring
a struggling settlement reads real, elevated scarcity too, not just
the settlement's own home region. A hungry town's economic strain
radiates outward the same way contagion risk does."""

OWNERSHIP_DIFFUSE_RATE = 0.3
"""Same role as `TRAFFIC_DIFFUSE_RATE` — a region bordering one with a
long history of homes passing hand to hand through inheritance reads
as measurably settled too, not just the exact tiles carrying the
handoffs."""

NOISE_DIFFUSE_RATE = 0.3
"""Same role as `TRAFFIC_DIFFUSE_RATE`/`OWNERSHIP_DIFFUSE_RATE` — a
region bordering a genuinely busy one reads as somewhat disturbed too,
not just the exact region carrying the people/traffic."""

HEAT_DIFFUSE_RATE = 0.2
"""Smaller than most — `weather_regions` already blends smoothly
region-to-region on its own (each region's `compute_weather` shares
the same monthly baseline, just independently jittered), so this only
needs to soften hard region-boundary edges slightly, not spread far."""

HEAT_COLD_C = 2.0
HEAT_WARM_C = 18.5
"""Normalization endpoints for `step_heat`, deliberately reusing two
already-real, already-tuned thresholds rather than inventing new ones:
`HEAT_COLD_C` mirrors `disasters.FROST_TEMP_THRESHOLD` (a hard freeze),
`HEAT_WARM_C` mirrors `disasters.HEATWAVE_BUILD_TEMP` (sustained-heat
onset) — 0.0 reads as "cold enough to trigger a frost event," 1.0 reads
as "hot enough to build heatwave pressure." Not imported directly (a
plain float mirror, same discipline `CLAUDE.md`'s `MIN_LIFESPAN_TICKS`
JS mirror already uses) since `disasters.py` has no other reason to be
a dependency of this module."""

NUTRIENTS_DIFFUSE_RATE = 0.3
"""Same role as `TRAFFIC_DIFFUSE_RATE` — a region bordering rich wild
foraging reads as somewhat nutrient-rich too, not just the exact tiles
carrying food nodes."""

SCENT_DIFFUSE_RATE = 0.35
"""Same role as `DISEASE_PRESSURE_DIFFUSE_RATE` — a sense of danger
radiates into neighboring regions, not just the exact tiles a predator
pack currently stands on."""

CULTURAL_INFLUENCE_DIFFUSE_RATE = 0.3
"""Same role as `TRAFFIC_DIFFUSE_RATE` — a region bordering a
culturally active one reads as somewhat influenced too, not just the
exact tiles where an adopter happens to be standing this tick."""

FERTILITY_DIFFUSE_RATE = 0.3
"""Same role as `SCARCITY_DIFFUSE_RATE` — a region bordering rich
farmland reads as somewhat fertile too, not just the exact tiles under
plow this tick."""

BEAUTY_DIFFUSE_RATE = 0.3
"""Same spatial-bleed role as `FERTILITY_DIFFUSE_RATE`. Applied on TOP
of `World.aesthetic_appraisal`'s own separate temporal smoothing
(`world/aesthetics.py`'s `BEAUTY_VOTE_SMOOTHING`) — two different axes
of smoothing, not a duplicate of one another: the source accumulator
smooths a region's opinion over TIME as new votes arrive, this diffuse
call smooths across SPACE so a lovely region's neighbors read as a
little lovely too, not just the exact region where the vote landed."""

HAZARD_DIFFUSE_RATE = 0.35
"""Same role as `DISEASE_PRESSURE_DIFFUSE_RATE` — a sense of recent
disaster damage radiates into neighboring regions, not just the exact
scarred tiles."""

STORMINESS_DIFFUSE_RATE = 0.3
"""Same role as `HEAT_DIFFUSE_RATE` — a region's own weather reading
softened toward its neighbors, same treatment every other
`weather_regions`-sourced field gets."""

STORMINESS_PRECIPITATION_WEIGHT = 0.6
STORMINESS_WIND_WEIGHT = 0.4
"""`storminess` blends both real weather axes rather than reading only
one — a genuinely windy-but-dry region and a rainy-but-still region
both read as somewhat stormy, weighted toward precipitation (the more
immediately disruptive of the two for travel)."""

WILDLIFE_DIFFUSE_RATE = 0.3
"""A10 "Ecology / food webs," field-substrate fold-in, second slice:
same role as `SCENT_DIFFUSE_RATE`'s spread, for the positive-signal
sibling field below."""

SURPRISE_DIFFUSE_RATE = 0.3
"""Tier 7 HCA Stage A, A3 ("surprise map overlay... answers one
nameable question"): same role as `HAZARD_DIFFUSE_RATE` — a settlement
whose emergence log just genuinely surprised the simulation reads as
a little surprising to its immediate neighbors too, not just the exact
settlement tile. The literal question this overlay answers: "where on
the map is something happening the town's own attention doesn't yet
have a model for?" — the direct visual counterpart to A2's now-real
`SimulationEngine._emergence_surprise` gate, same "predictable is not
notable" rule made visible rather than only logged."""


def _normalize_peak(raw: list[list[float]]) -> list[list[float]]:
    """Scales a raw non-negative grid to 0..1 against its own peak cell
    — same "normalize against whichever region currently holds the
    most" shape `step_population_density` already established. An
    all-zero grid stays all-zero (no source anywhere yet)."""
    peak = max((v for row in raw for v in row), default=0.0)
    if peak <= 0.0:
        return [[0.0 for _ in row] for row in raw]
    return [[v / peak for v in row] for row in raw]


@dataclass
class FieldGrid:
    """`fields: {name: [[value_per_cell...] * SIZE] * SIZE}` — a dict of
    named `FIELD_GRID_SIZE` x `FIELD_GRID_SIZE` dense grids. Values are
    unbounded floats; individual fields document their own natural
    range in the producer that writes them (`population_density` here
    is 0..1 by construction)."""

    fields: dict[str, list[list[float]]] = field(default_factory=dict)

    def ensure_field(self, name: str) -> list[list[float]]:
        """Returns the named field's grid, creating it zero-filled on
        first use — callers never need a separate "does this field
        exist yet" branch."""
        grid = self.fields.get(name)
        if grid is None:
            grid = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
            self.fields[name] = grid
        return grid

    def region_of(self, pos: tuple[int, int] | None, width: int, height: int) -> tuple[int, int]:
        """Same bucketing math as `World.weather_at`'s region lookup —
        kept in lockstep deliberately (a field reading and the weather
        reading for the same position should always agree on which
        region they're in)."""
        if pos is None or width <= 0 or height <= 0:
            return (0, 0)
        rx = min(FIELD_GRID_SIZE - 1, max(0, pos[0] * FIELD_GRID_SIZE // width))
        ry = min(FIELD_GRID_SIZE - 1, max(0, pos[1] * FIELD_GRID_SIZE // height))
        return (rx, ry)

    def get_at(self, name: str, pos: tuple[int, int] | None, width: int, height: int) -> float:
        rx, ry = self.region_of(pos, width, height)
        return self.ensure_field(name)[ry][rx]

    def set_region(self, name: str, rx: int, ry: int, value: float) -> None:
        self.ensure_field(name)[ry][rx] = value

    def step_population_density(self, agent_positions: list[tuple[int, int]], width: int, height: int) -> None:
        """The one concrete field this pass ships: recomputes
        `population_density` from scratch each call (cheap — O(agents),
        no decay/diffusion needed since it's a live census, not an
        accumulating quantity) and normalizes 0..1 against whichever
        region currently holds the most agents. An empty world (no
        agents yet) leaves every cell at 0.0."""
        counts = [[0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in agent_positions:
            rx, ry = self.region_of(pos, width, height)
            counts[ry][rx] += 1
        peak = max((c for row in counts for c in row), default=0)
        for ry in range(FIELD_GRID_SIZE):
            for rx in range(FIELD_GRID_SIZE):
                self.set_region(
                    "population_density", rx, ry,
                    (counts[ry][rx] / peak) if peak > 0 else 0.0,
                )

    def step_disease_pressure(self, sick_positions: list[tuple[int, int]], total_agents: int, width: int, height: int) -> None:
        """Second concrete field. Recomputes a raw regional sick-fraction
        census each call (same "live census, not accumulating" shape as
        `step_population_density`), then spreads it into neighboring
        regions via `ca_operators.diffuse` — a region with no sick
        agents of its own but adjacent to one that does reads real,
        elevated pressure, the actual point of using a diffusion
        operator here rather than a bare census. An empty world (no
        agents yet) leaves every cell at 0.0."""
        counts = [[0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in sick_positions:
            rx, ry = self.region_of(pos, width, height)
            counts[ry][rx] += 1
        raw = [
            [(counts[ry][rx] / total_agents) if total_agents > 0 else 0.0 for rx in range(FIELD_GRID_SIZE)]
            for ry in range(FIELD_GRID_SIZE)
        ]
        self.fields["disease_pressure"] = diffuse(raw, DISEASE_PRESSURE_DIFFUSE_RATE)

    def step_pollution(
        self, industrial_positions: list[tuple[int, int]],
        mining_scar_items: list[tuple[tuple[int, int], float]], width: int, height: int,
    ) -> None:
        """Third concrete field. Unlike `population_density`/`disease_
        pressure` (both live per-tick censuses), pollution's two
        sources are already slow-changing state elsewhere (standing
        buildings, `World.mining_scars`) — this just re-reads them each
        call (still cheap, same O(buildings + scarred tiles) either
        way) rather than accumulating its own separate history, keeping
        the same "recompute fresh, never drift" discipline every other
        field here follows. Normalizes against the region with the
        most raw pollution, then spreads via `ca_operators.diffuse` —
        real industrial impact isn't confined to the exact region a
        factory's tile falls in."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in industrial_positions:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += POLLUTION_BUILDING_WEIGHT
        for pos, intensity in mining_scar_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += intensity * POLLUTION_MINING_SCAR_WEIGHT
        self.fields["pollution"] = diffuse(_normalize_peak(raw), POLLUTION_DIFFUSE_RATE)

    def step_traffic(self, road_wear_items: list[tuple[tuple[int, int], float]], width: int, height: int) -> None:
        """Fourth concrete field. Same "re-read already-real slow-
        changing state" shape `step_pollution` established: `World.
        roads.wear` (per-tile, already accumulated by `RoadNetwork.
        tick`) is summed per region, normalized against the region
        with the most, then spread via `ca_operators.diffuse` — a
        region just off a busy road corridor reads real, elevated
        traffic too, not just the exact tiles carrying wear."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, wear in road_wear_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += wear
        self.fields["traffic"] = diffuse(_normalize_peak(raw), TRAFFIC_DIFFUSE_RATE)

    def step_scarcity(
        self, settlement_scarcity_items: list[tuple[tuple[int, int], float]], width: int, height: int,
    ) -> None:
        """Fifth concrete field (A4 "economy -> resource/price fields
        that flow," docs/ROADMAP-2026-07-REMAINING.md). Unlike traffic/
        pollution (unbounded raw sums normalized against a peak), each
        item here already IS a real 0..1 reading (`1 - avg(food_fill,
        materials_fill)` — `settlement.buildings.compute_resource_
        fill`) — same "already-real slow-changing state, re-read fresh
        each call" shape `step_pollution` established, just no
        normalization step needed since the source is already bounded.
        A region containing more than one settlement averages their
        readings. Spread via `ca_operators.diffuse` — a struggling
        settlement's strain radiates into neighboring regions too, not
        just its own home region."""
        totals = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        counts = [[0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, scarcity in settlement_scarcity_items:
            rx, ry = self.region_of(pos, width, height)
            totals[ry][rx] += scarcity
            counts[ry][rx] += 1
        raw = [
            [(totals[ry][rx] / counts[ry][rx]) if counts[ry][rx] > 0 else 0.0 for rx in range(FIELD_GRID_SIZE)]
            for ry in range(FIELD_GRID_SIZE)
        ]
        self.fields["scarcity"] = diffuse(raw, SCARCITY_DIFFUSE_RATE)

    def step_ownership(
        self, ownership_history_items: list[tuple[tuple[int, int], int]], width: int, height: int,
    ) -> None:
        """Sixth concrete field (A1, roadmap Tier 1 item 3's "ownership"
        entry). Same "re-read already-real slow-changing state" shape
        `step_traffic` established: `World.ownership_history` (A19,
        v1.34.55 — a permanent, non-decaying per-tile count of how many
        times a HUT has passed to a living heir, written by `Population.
        _apply_inheritance`) is summed per region, normalized against
        the region with the most, then spread via `ca_operators.
        diffuse` — a region bordering one with deep inheritance history
        reads as settled too, not just the exact tiles that changed
        hands. Deliberately reads `ownership_history`, not the momentary
        `Building.owner_agent_id` census a HUT happens to have right
        now — a region can be freshly built (no inheritance yet) or
        genuinely long-settled (many handoffs), and only the latter
        should read as "established," which a live-ownership census
        alone can't distinguish."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, count in ownership_history_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += count
        self.fields["ownership"] = diffuse(_normalize_peak(raw), OWNERSHIP_DIFFUSE_RATE)

    def step_noise(self) -> None:
        """Seventh concrete field (A1, roadmap Tier 1 item 3's "noise"
        entry). Deliberately NOT sourced from any new tracked state —
        genuinely composite, the mean of two fields this class already
        computes every tick (`population_density`/`traffic`, both
        already 0..1 by construction), then spread via `ca_operators.
        diffuse` same as every other field here. Must run AFTER both
        source fields are stepped in the same tick (see `World._tick_
        disasters`'s ordering) — reads whatever they hold via `ensure_
        field`, which zero-fills on first use rather than erroring, so
        a call before either exists degrades to an all-zero noise field
        instead of crashing. Real consumer: `WildlifeGrid._maybe_
        recolonize` dampens site selection toward quieter regions —
        "wildlife avoids resettling in the busy, well-trodden parts of
        the map," a real ecological consequence neither source field
        had on its own."""
        density = self.ensure_field("population_density")
        traffic = self.ensure_field("traffic")
        raw = [
            [(density[ry][rx] + traffic[ry][rx]) / 2.0 for rx in range(FIELD_GRID_SIZE)]
            for ry in range(FIELD_GRID_SIZE)
        ]
        self.fields["noise"] = diffuse(raw, NOISE_DIFFUSE_RATE)

    def step_heat(self, weather_region_temps: dict[tuple[int, int], float]) -> None:
        """Eighth concrete field (A1). Sourced from `World.weather_
        regions` (already-real per-region `WeatherState.temperature_c`,
        `WEATHER_REGION_GRID` == `FIELD_GRID_SIZE` == 3, so no resampling
        needed) — a genuinely new READING of existing state, not new
        tracked data. Normalized against `HEAT_COLD_C`/`HEAT_WARM_C`,
        then softened via `ca_operators.diffuse`. Real consumer:
        `Population._maybe_welcome_migrant`'s `region_heat` term —
        migrants are less drawn to a scorching region, same bounded
        "never a hard block" shape as `region_scarcity`."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for (rx, ry), temp_c in weather_region_temps.items():
            if 0 <= rx < FIELD_GRID_SIZE and 0 <= ry < FIELD_GRID_SIZE:
                span = HEAT_WARM_C - HEAT_COLD_C
                raw[ry][rx] = clamp((temp_c - HEAT_COLD_C) / span, 0.0, 1.0) if span else 0.0
        self.fields["heat"] = diffuse(raw, HEAT_DIFFUSE_RATE)

    def step_nutrients(self, food_node_items: list[tuple[tuple[int, int], float]], width: int, height: int) -> None:
        """Ninth concrete field (A1). Sums `World.resources`' standing
        FOOD-kind node amounts (already-real, already-tracked wild-food
        supply) per region, normalized against the richest region, then
        spread via `ca_operators.diffuse` — same "re-read already-real
        state" shape `step_traffic` established. Real consumer:
        `WildlifeGrid`'s grazer reproduction chance gains a small bonus
        in nutrient-rich regions (`NUTRIENTS_REPRODUCE_BONUS_MAX`) —
        distinct from the existing prey-scarcity PENALTY (predator
        pressure), this is a genuine positive signal from raw forage
        abundance."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, amount in food_node_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += amount
        self.fields["nutrients"] = diffuse(_normalize_peak(raw), NUTRIENTS_DIFFUSE_RATE)

    def step_scent(self, predator_positions: list[tuple[tuple[int, int], int]], width: int, height: int) -> None:
        """Tenth concrete field (A1). Sums live predator-pack sizes
        (already-real `WildlifeGrid.herds` state) per region, normalized
        against the most dangerous region, then spread via `ca_operators.
        diffuse` — a region-scale "how much danger is in the air" reading,
        distinct from the existing TILE-level predator avoidance
        (`Population._step_toward`/`_maybe_move`'s `predator_tiles` set,
        which only reacts once an agent is already adjacent). Real
        consumer: `SimulationEngine._choose_fission_site` prefers a
        low-scent region when an alternative exists, same "never a hard
        block" shape its existing `population_density` filter already
        uses — a founding party avoids visibly dangerous ground, not
        just crowded ground."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, count in predator_positions:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += count
        self.fields["scent"] = diffuse(_normalize_peak(raw), SCENT_DIFFUSE_RATE)

    def step_wildlife(self, grazer_positions: list[tuple[tuple[int, int], int]], width: int, height: int) -> None:
        """A10 "Ecology / food webs," field-substrate fold-in, second
        slice. Sums live GRAZER-herd sizes (already-real `WildlifeGrid.
        herds` state, same shape `step_scent` reads for predators) per
        region, normalized against the richest region, spread via
        `ca_operators.diffuse` — a region-scale "how much game is
        here" reading. Deliberately the POSITIVE counterpart to
        `scent`'s danger signal, not a duplicate of it: `scent` sources
        from PREDATOR packs and reads as a threat `_choose_fission_
        site` avoids; `wildlife` sources from GRAZER herds and reads as
        an opportunity. Real consumer: `Population._maybe_welcome_
        migrant`'s new `region_wildlife` term (`MIGRANT_WILDLIFE_
        PULL`) — "word travels that a place has good hunting," a
        fifth positive region-field pull alongside `ownership`/
        `cultural_influence`/`beauty`'s siblings — closing the second
        half of a genuinely bidirectional wildlife<->settlement field
        coupling (the first half, wildlife reading `population_
        density`, shipped as this fold-in's first slice)."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, count in grazer_positions:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += count
        self.fields["wildlife"] = diffuse(_normalize_peak(raw), WILDLIFE_DIFFUSE_RATE)

    def step_cultural_influence(self, adopter_positions: list[tuple[int, int]], width: int, height: int) -> None:
        """Eleventh concrete field (A1). Sourced from `World.invented_
        concepts`' already-real `InventedConcept.adopter_ids` — every
        living agent who has adopted at least one invented concept
        (technology, custom, law, ecological relationship, whatever
        origin) counts once toward their current tile's region,
        normalized against the most culturally active region, spread
        via `ca_operators.diffuse`. Same "re-read already-real slow-
        changing state" shape `step_population_density` established
        (a live census, not an accumulating quantity — an agent who
        stops being an adopter, or dies, simply stops being counted).
        Real consumer: `Population._maybe_welcome_migrant`'s new
        `region_cultural_influence` term (`MIGRANT_CULTURAL_PULL`) — a
        third POSITIVE region-field pull alongside `ownership`/`heat`'s
        siblings, "word travels that a place has real ideas.\""""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos in adopter_positions:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += 1
        self.fields["cultural_influence"] = diffuse(_normalize_peak(raw), CULTURAL_INFLUENCE_DIFFUSE_RATE)

    def step_fertility(
        self, soil_fertility_items: list[tuple[tuple[int, int], float]], width: int, height: int,
    ) -> None:
        """Twelfth concrete field (A1). Sourced from `FarmGrid.soil_
        fertility` — already a real, already-real-tracked, already-0..1
        per-farmed-tile dict — averaged per region (same already-bounded
        shape `step_scarcity` established, no `_normalize_peak` needed),
        then spread via `ca_operators.diffuse`.

        Deliberately NOT the same read `world/spatial_memory.py`'s
        `location_character` already makes: that function looks up ONE
        specific tile's own farmed history for flavor text (a bare-tile
        inspector line, an origin story). This is a REGION-scale
        aggregate consumed by a region-scoped mechanic — see
        `SimulationEngine._choose_fission_site`'s new fertility
        preference — a genuinely different question ("which broad area
        of the map is good farmland right now") than "what happened on
        this exact tile." An unfarmed region (no tiles in `soil_
        fertility` at all) reads as 0.0, not neutral — matching every
        other region-average field's own "nothing here yet" convention
        (`step_scarcity`)."""
        totals = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        counts = [[0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, fertility in soil_fertility_items:
            rx, ry = self.region_of(pos, width, height)
            totals[ry][rx] += fertility
            counts[ry][rx] += 1
        raw = [
            [(totals[ry][rx] / counts[ry][rx]) if counts[ry][rx] > 0 else 0.0 for rx in range(FIELD_GRID_SIZE)]
            for ry in range(FIELD_GRID_SIZE)
        ]
        self.fields["fertility"] = diffuse(raw, FERTILITY_DIFFUSE_RATE)

    def step_beauty(self, aesthetic_appraisal: list[list[float]]) -> None:
        """Thirteenth field (A1), and the one field in this class that
        is NOT a live re-read of already-real deterministic state — see
        `world/aesthetics.py`'s module docstring for the full design
        rationale (explicit `AskUserQuestion` decision, v1.34.74:
        "New subjective agent-vote signal"). `aesthetic_appraisal` is
        `World.aesthetic_appraisal`, itself a persistent per-region
        running average of genuinely new per-agent subjective votes,
        already 0..1 and already smoothed over TIME — this method's own
        job is purely the spatial half every other field gets, spread
        via `ca_operators.diffuse` so a lovely region's neighbors read
        as a little lovely too."""
        self.fields["beauty"] = diffuse([list(row) for row in aesthetic_appraisal], BEAUTY_DIFFUSE_RATE)

    def step_hazard(
        self, disaster_scar_items: list[tuple[tuple[int, int], float]], width: int, height: int,
    ) -> None:
        """Fourteenth field (A1) — part of migrating `World.mining_
        scars`/`disaster_scars`/the 3x3 climate grid onto `FieldGrid`
        properly (docs/ROADMAP-2026-07-REMAINING.md's own explicitly-
        deferred item, finally attempted). `mining_scars` already had a
        real region-aggregate representation (it's one of `step_
        pollution`'s two sources); `disaster_scars` never did — this is
        that missing half, same "re-read already-real slow-changing
        state" shape `step_pollution` established, normalized against
        the region with the most raw scarring, spread via `ca_
        operators.diffuse`. Deliberately NOT merged into `pollution`
        itself (disaster damage and industrial pollution are different
        stories) and deliberately NOT a replacement for `World.
        disaster_scars`'s own per-tile dict, which stays the source of
        truth for tile-precise consumers (`location_character`, the
        bare-tile inspector) — this is the coarse REGION-scale reading
        those consumers were never meant to answer."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, intensity in disaster_scar_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] += intensity
        self.fields["hazard"] = diffuse(_normalize_peak(raw), HAZARD_DIFFUSE_RATE)

    def step_storminess(self, weather_region_states: dict) -> None:
        """Fifteenth field (A1) — the other half of the same migration:
        `World.weather_regions` (the "3x3 climate grid" the roadmap's
        own note names) already fed `heat` (`temperature_c` alone);
        this reads its other two axes (`precipitation`/`wind`,
        `STORMINESS_PRECIPITATION_WEIGHT`/`_WIND_WEIGHT`) into a second
        real field. Same direct-index shape `step_heat` established (
        `WEATHER_REGION_GRID` == `FIELD_GRID_SIZE`, no resampling
        needed) — NOT a replacement for `weather_regions` itself, which
        stays the source of truth for `weather_at()` and every other
        full-`WeatherState` consumer; this is a coarse SCALAR reading
        of it for region-field consumers that only need "how stormy,"
        not the full weather state."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for (rx, ry), ws in weather_region_states.items():
            if 0 <= rx < FIELD_GRID_SIZE and 0 <= ry < FIELD_GRID_SIZE:
                raw[ry][rx] = clamp(
                    ws.precipitation * STORMINESS_PRECIPITATION_WEIGHT
                    + ws.wind * STORMINESS_WIND_WEIGHT,
                    0.0, 1.0,
                )
        self.fields["storminess"] = diffuse(raw, STORMINESS_DIFFUSE_RATE)

    def step_surprise(
        self, settlement_surprise_items: list[tuple[tuple[int, int], float]], width: int, height: int,
    ) -> None:
        """Tier 7 HCA Stage A, A3 — the surprise map overlay. Sourced
        from `World.settlement_surprise` (a small, decaying, per-
        settlement-position dict, same shape as `disaster_scars`),
        itself written by `SimulationEngine._append_emergence` whenever
        a candidate observation actually clears A1/A2's surprise gate
        for a settlement-scoped observation — never on a suppressed
        one, since a routine candidate silently leaving no trace is
        exactly the behavior this overlay exists to make visible.
        Aggregated per region (same `_normalize_peak`-then-`diffuse`
        shape `step_hazard` already established) rather than per-tile,
        matching this module's own coarse-resolution discipline."""
        raw = [[0.0 for _ in range(FIELD_GRID_SIZE)] for _ in range(FIELD_GRID_SIZE)]
        for pos, surprise in settlement_surprise_items:
            rx, ry = self.region_of(pos, width, height)
            raw[ry][rx] = max(raw[ry][rx], surprise)
        self.fields["surprise"] = diffuse(_normalize_peak(raw), SURPRISE_DIFFUSE_RATE)

    def to_dict(self) -> dict:
        return {name: [list(row) for row in grid] for name, grid in self.fields.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "FieldGrid":
        return cls(fields={name: [list(row) for row in grid] for name, grid in data.items()})
