"""A19 (docs/MASTERCHECKLIST-2026-07-22.md, roadmap step 26), first
slice: "Persistent spatial memory — every location accumulates a
bounded history vector: traffic, battles, rituals, pollution,
fertility, disasters, ownership, construction, ecology. Places gain
*character* that influences future simulation."

Status before this pass (the doc's own words): "`terrain_activity`/
`mining_scars`/`disaster_scars` track some per-location history; not
general." Each of those is real, but they're three totally independent
dicts nobody reads together — there was no single place a pillar (or a
future UI panel) could ask "what does this tile remember?" This module
is that single place: `location_character` reads the existing scar/
activity dicts (real state, not duplicated) into one bounded per-tile
vector.

Deliberately NOT a new storage layer — `mining_scars`/`disaster_scars`/
`ritual_activity` (A18's own new tile-history axis, `world/terrain_
evolution.py`) stay exactly where they are, each still written/decayed
by its own existing mechanism. This is a read-side unification only.

Explicit user follow-up ("start A19"): traffic/pollution/fertility
are now folded in too, despite genuinely being a different SHAPE than
the sparse per-event dicts above (traffic/pollution are continuous
`FieldGrid` regions; fertility is `FarmGrid.soil_fertility`, a
dense-per-farmed-tile dict defaulting to 1.0/pristine rather than
0.0/absent) — `location_character_from_dicts` reads each through its
own already-resolved-for-this-tile value rather than forcing them into
the sparse-dict calling convention, and only surfaces a reading past a
real notability threshold (heavily depleted soil, elevated traffic/
pollution), same "absence means neutral" discipline the other axes
already hold.

Third slice (explicit user instruction, "continue A19"): ownership/
construction close too. Both needed a genuinely new per-tile HISTORY
store (a building's current owner/stage was only ever instantaneous
state) — `World.construction_history`/`ownership_history`, written at
the two real events that already exist for each (`Population._maybe_
start_construction`'s call to `Settlement.start_construction`;
`Population._apply_inheritance`'s owner hand-off, H7) rather than
anything new invented just to populate this axis. Both are permanent,
non-decaying counts (unlike the scar dicts) — a site rebuilt three
times or passed through several owners has genuinely more history than
one that hasn't, and that shouldn't fade the way a mining scar's
cosmetic mark should. Battles remains unfolded (no combat mechanic
exists to source it, same note A18 already carries) — this closes
every other axis the spec names."""

from __future__ import annotations

LOCATION_HISTORY_CATEGORIES: tuple[str, ...] = (
    "mining", "disaster", "ritual", "ruin", "road", "migration", "dry_lakebed",
    "traffic", "pollution", "fertility", "construction", "ownership",
)
"""The closed set of axes `location_character` currently reads —
each backed by a real, already-existing per-tile/per-region store.
`ruin` added in A3 (roadmap step 28, `World.ruin_scars`); `road` added
in M1/M9 "The Living Map" (`World.road_scars`); `migration` added
closing A19's first slice (`World.migration_trails`, M4 "wildlife
migration trails" — the closest real existing data to the spec's named
"ecology" axis: a GRAZER herd's own worn crossing points); `dry_
lakebed` added in a Tier 1.5 pass (`World.dry_lakebed_scars` — M1/M9's
own explicit "dried lakes... remain genuinely unbuilt" line); `traffic`
/`pollution` (`World.fields`, A1's `FieldGrid`) and `fertility`
(`FarmGrid.soil_fertility`) added closing A19's second slice — the
same unification this module already provides, extended past the
sparse-scar-dict shape to the field/farm substrate rather than left
as three independent silos. `construction`/`ownership` (`World.
construction_history`/`ownership_history`) added closing A19's third
slice — permanent per-tile counts, written at `Population._maybe_
start_construction`/`_apply_inheritance`'s real events, closing the
last of the spec's named axes this codebase can actually source.
Battles has no data source since Hearthmind has no combat mechanic,
see A18's own note — the one axis that genuinely stays open."""


FERTILITY_NOTABLE_THRESHOLD = 0.5
"""`FarmGrid.soil_fertility` defaults to 1.0 (pristine) for any tile
never farmed at all, and only ever appears in the dict once a tile has
been farmed at least once — so unlike the sparse scar dicts, presence
alone doesn't mean "notable." Only a genuinely worked-out reading below
this floor surfaces as a `location_character` axis (worn-out farmland
is memorable; ordinary or fresh soil isn't)."""

TRAFFIC_NOTABLE_THRESHOLD = 0.5
POLLUTION_NOTABLE_THRESHOLD = 0.5
"""Both `traffic`/`pollution` (`World.fields`, A1's `FieldGrid`) are
normalized 0..1 against their own current map-wide peak each tick —
only a region reading past the halfway point (genuinely busy/fouled
relative to the rest of the map right now) surfaces as a location-
character axis, same "notable, not just present" discipline
`FERTILITY_NOTABLE_THRESHOLD` uses."""

CONSTRUCTION_NOTABLE_COUNT = 2
"""`World.construction_history` is a raw, unbounded integer count (how
many times something has been built at this exact tile) — a single
first-ever construction is completely ordinary, so it takes at least
one REBUILD (count >= 2) before a site's construction history is worth
naming. Normalized 0..1 by `min(1.0, count / CONSTRUCTION_NOTABLE_
COUNT)` the same way every other axis here caps its own intensity."""

OWNERSHIP_NOTABLE_COUNT = 1
"""`World.ownership_history` counts real inheritance hand-offs only
(H7, far rarer than construction — bounded by deaths with a living
family heir) — even a single transfer is already a real, nameable fact
("this home has passed to a new family"), so unlike `CONSTRUCTION_
NOTABLE_COUNT` the floor is the first occurrence, not the second."""


def location_character_from_dicts(
    mining_scars: dict[tuple[int, int], float] | None,
    disaster_scars: dict[tuple[int, int], float] | None,
    ritual_activity: dict[tuple[int, int], float] | None,
    ruin_scars: dict[tuple[int, int], float] | None,
    x: int, y: int,
    road_scars: dict[tuple[int, int], float] | None = None,
    migration_trails: dict[tuple[int, int], float] | None = None,
    dry_lakebed_scars: dict[tuple[int, int], float] | None = None,
    soil_fertility: dict[tuple[int, int], float] | None = None,
    traffic_at: float | None = None,
    pollution_at: float | None = None,
    construction_history: dict[tuple[int, int], int] | None = None,
    ownership_history: dict[tuple[int, int], int] | None = None,
) -> dict[str, float]:
    """The real read-side logic `location_character` below wraps — split
    out so a caller that already has the scar dicts on hand
    individually (e.g. `Population._choose_build_site`, which is
    intentionally decoupled from `World` and receives each dict as its
    own parameter, same shape as `ruin_scars` before it) can use the
    SAME unification this module exists for, instead of re-deriving it
    with its own duplicate `.get()` calls. Any dict may be `None` (a
    caller not passing that axis simply omits it from the result, same
    "absence means neutral" convention as below). `road_scars`
    (M1/M9), `migration_trails` (closing A19's first slice), `dry_
    lakebed_scars` (a later Tier 1.5 pass), `soil_fertility`/
    `traffic_at`/`pollution_at` (closing A19's second slice), and
    `construction_history`/`ownership_history` (closing A19's third)
    are all keyword-only-by-convention, appended after `x, y` rather
    than inserted earlier, so every existing positional call site keeps
    working unchanged. `traffic_at`/`pollution_at` are the CALLER's own
    already-resolved region reading for this specific tile (via
    `FieldGrid.get_at`) — this function has no `World`/width/height to
    do that lookup itself, unlike the sparse per-tile dicts above."""
    pos = (x, y)
    character: dict[str, float] = {}
    mining = mining_scars.get(pos) if mining_scars else None
    if mining:
        character["mining"] = mining
    disaster = disaster_scars.get(pos) if disaster_scars else None
    if disaster:
        character["disaster"] = disaster
    ritual = ritual_activity.get(pos) if ritual_activity else None
    if ritual:
        character["ritual"] = ritual
    ruin = ruin_scars.get(pos) if ruin_scars else None
    if ruin:
        character["ruin"] = ruin
    road = road_scars.get(pos) if road_scars else None
    if road:
        character["road"] = road
    migration = migration_trails.get(pos) if migration_trails else None
    if migration:
        character["migration"] = migration
    dry_lakebed = dry_lakebed_scars.get(pos) if dry_lakebed_scars else None
    if dry_lakebed:
        character["dry_lakebed"] = dry_lakebed
    fertility = soil_fertility.get(pos) if soil_fertility else None
    if fertility is not None and fertility < FERTILITY_NOTABLE_THRESHOLD:
        character["fertility"] = 1.0 - fertility  # intensity = how depleted
    if traffic_at is not None and traffic_at >= TRAFFIC_NOTABLE_THRESHOLD:
        character["traffic"] = traffic_at
    if pollution_at is not None and pollution_at >= POLLUTION_NOTABLE_THRESHOLD:
        character["pollution"] = pollution_at
    construction = construction_history.get(pos) if construction_history else None
    if construction is not None and construction >= CONSTRUCTION_NOTABLE_COUNT:
        character["construction"] = min(1.0, construction / CONSTRUCTION_NOTABLE_COUNT)
    ownership = ownership_history.get(pos) if ownership_history else None
    if ownership is not None and ownership >= OWNERSHIP_NOTABLE_COUNT:
        character["ownership"] = min(1.0, ownership / (OWNERSHIP_NOTABLE_COUNT + 1))
    return character


def location_character(world, x: int, y: int) -> dict[str, float]:
    """One tile's real accumulated history/character, read from the
    twelve existing per-location/per-region stores `World` already
    maintains. Only keys present are ones with non-zero real intensity
    (or, for fertility/traffic/pollution/construction/ownership, past
    their own notability threshold) — same "sparse, absence means
    neutral" convention the underlying stores already use, so a caller
    can't mistake "not in this dict" for "explicitly zero.\""""
    traffic_at = world.fields.get_at("traffic", (x, y), world.config.width, world.config.height)
    pollution_at = world.fields.get_at("pollution", (x, y), world.config.width, world.config.height)
    return location_character_from_dicts(
        world.mining_scars, world.disaster_scars, world.ritual_activity, world.ruin_scars, x, y,
        road_scars=world.road_scars, migration_trails=world.migration_trails,
        dry_lakebed_scars=world.dry_lakebed_scars, soil_fertility=world.farms.soil_fertility,
        traffic_at=traffic_at, pollution_at=pollution_at,
        construction_history=world.construction_history, ownership_history=world.ownership_history,
    )


LOCATION_CHARACTER_LABELS: dict[str, str] = {
    "mining": "old mining activity", "disaster": "a past disaster", "ritual": "past rituals held here",
    "ruin": "the ruin of an older structure", "road": "an old well-traveled road bed",
    "migration": "a wildlife migration crossing", "dry_lakebed": "the bed of a lake that once reached here",
    "traffic": "heavy foot traffic", "pollution": "the fouled air of nearby industry",
    "fertility": "soil worn thin by hard farming",
    "construction": "a site rebuilt many times over", "ownership": "a home passed down through generations",
}
"""Plain-language label per `LOCATION_HISTORY_CATEGORIES` axis — closes
A19's own "Feeds" checklist item ("places as actors... rich pillar
perception"): the first real, human-readable consumer of `location_
character` beyond `Population._choose_build_site`'s bare numeric
scoring, used by `SimulationEngine._maybe_schedule_composite_entity`
to ground a newly-named place's origin story in what the SITE itself
remembers, not just the single most recent settlement-wide event."""


def location_character_text(character: dict[str, float]) -> str:
    """The strongest 1-2 axes of `character` (by intensity) rendered as
    a short clause, or `""` if the tile has no notable history — plain-
    English so it can drop straight into an LLM prompt without the
    caller needing to know the closed axis vocabulary."""
    if not character:
        return ""
    strongest = sorted(character.items(), key=lambda kv: -kv[1])[:2]
    labels = [LOCATION_CHARACTER_LABELS.get(axis, axis) for axis, _ in strongest]
    return " and ".join(labels)
