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
Fertility (soil), traffic, pollution, ownership, construction, and
ecology axes the spec names are explicitly NOT folded in this pass —
`FarmGrid.soil_fertility` and the A1 field substrate are a different
shape (continuous fields, not sparse per-event dicts) and unifying
them is real follow-up work, flagged rather than silently attempted."""

from __future__ import annotations

LOCATION_HISTORY_CATEGORIES: tuple[str, ...] = ("mining", "disaster", "ritual", "ruin", "road", "migration")
"""The closed set of axes `location_character` currently reads —
each backed by a real, already-existing per-tile dict. `ruin` added
in A3 (roadmap step 28, `World.ruin_scars`); `road` added in M1/M9
"The Living Map" (`World.road_scars`); `migration` added closing A19
(`World.migration_trails`, M4 "wildlife migration trails" — the
closest real existing data to the spec's named "ecology" axis: a
GRAZER herd's own worn crossing points) — the same unification this
module already provides, extended to the newest scar-shaped dict
rather than left as a sixth independent silo.
Deliberately NOT the spec's full nine-axis list (traffic/battles/
pollution/fertility/ownership/construction remain unfolded — traffic/
pollution/fertility are a different shape, continuous `FieldGrid`
regions rather than sparse per-tile dicts, per this module's own
docstring; ownership/construction have no dedicated per-tile store at
all; battles has no data source since Hearthmind has no combat
mechanic, see A18's own note)."""


def location_character_from_dicts(
    mining_scars: dict[tuple[int, int], float] | None,
    disaster_scars: dict[tuple[int, int], float] | None,
    ritual_activity: dict[tuple[int, int], float] | None,
    ruin_scars: dict[tuple[int, int], float] | None,
    x: int, y: int,
    road_scars: dict[tuple[int, int], float] | None = None,
    migration_trails: dict[tuple[int, int], float] | None = None,
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
    (M1/M9) and `migration_trails` (closing A19) are keyword-only-by-
    convention, appended after `x, y` rather than inserted earlier, so
    every existing positional call site keeps working unchanged."""
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
    return character


def location_character(world, x: int, y: int) -> dict[str, float]:
    """One tile's real accumulated history, read from the six
    existing per-location dicts `World` already maintains. Only keys
    present are ones with non-zero real intensity — same "sparse,
    absence means neutral" convention the underlying dicts already
    use, so a caller can't mistake "not in this dict" for "explicitly
    zero.\""""
    return location_character_from_dicts(
        world.mining_scars, world.disaster_scars, world.ritual_activity, world.ruin_scars, x, y,
        road_scars=world.road_scars, migration_trails=world.migration_trails,
    )


LOCATION_CHARACTER_LABELS: dict[str, str] = {
    "mining": "old mining activity", "disaster": "a past disaster", "ritual": "past rituals held here",
    "ruin": "the ruin of an older structure", "road": "an old well-traveled road bed",
    "migration": "a wildlife migration crossing",
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
