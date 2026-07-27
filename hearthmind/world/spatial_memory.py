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
already hold. Ownership/construction remain explicitly NOT folded —
neither has any real per-tile HISTORY store (a building's current
owner/stage is instantaneous state, not an accumulated memory the way
every other axis here is); building one would be new, unscoped
follow-up, not a read-side unification of something that already
exists. Battles remains unfolded (no combat mechanic exists to
source it, same note A18 already carries)."""

from __future__ import annotations

LOCATION_HISTORY_CATEGORIES: tuple[str, ...] = (
    "mining", "disaster", "ritual", "ruin", "road", "migration", "dry_lakebed",
    "traffic", "pollution", "fertility",
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
as three independent silos. Deliberately still NOT the spec's full
nine-axis list: ownership/construction remain unfolded (no dedicated
per-tile HISTORY store exists for either — real, unscoped follow-up);
battles has no data source since Hearthmind has no combat mechanic,
see A18's own note."""


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
    lakebed_scars` (a later Tier 1.5 pass), and `soil_fertility`/
    `traffic_at`/`pollution_at` (closing A19's second slice) are all
    keyword-only-by-convention, appended after `x, y` rather than
    inserted earlier, so every existing positional call site keeps
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
    return character


def location_character(world, x: int, y: int) -> dict[str, float]:
    """One tile's real accumulated history/character, read from the ten
    existing per-location/per-region stores `World` already maintains.
    Only keys present are ones with non-zero real intensity (or, for
    fertility/traffic/pollution, past their own notability threshold)
    — same "sparse, absence means neutral" convention the underlying
    stores already use, so a caller can't mistake "not in this dict"
    for "explicitly zero.\""""
    traffic_at = world.fields.get_at("traffic", (x, y), world.config.width, world.config.height)
    pollution_at = world.fields.get_at("pollution", (x, y), world.config.width, world.config.height)
    return location_character_from_dicts(
        world.mining_scars, world.disaster_scars, world.ritual_activity, world.ruin_scars, x, y,
        road_scars=world.road_scars, migration_trails=world.migration_trails,
        dry_lakebed_scars=world.dry_lakebed_scars, soil_fertility=world.farms.soil_fertility,
        traffic_at=traffic_at, pollution_at=pollution_at,
    )


LOCATION_CHARACTER_LABELS: dict[str, str] = {
    "mining": "old mining activity", "disaster": "a past disaster", "ritual": "past rituals held here",
    "ruin": "the ruin of an older structure", "road": "an old well-traveled road bed",
    "migration": "a wildlife migration crossing", "dry_lakebed": "the bed of a lake that once reached here",
    "traffic": "heavy foot traffic", "pollution": "the fouled air of nearby industry",
    "fertility": "soil worn thin by hard farming",
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
