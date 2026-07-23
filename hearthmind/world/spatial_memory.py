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

LOCATION_HISTORY_CATEGORIES: tuple[str, ...] = ("mining", "disaster", "ritual", "ruin")
"""The closed set of axes `location_character` currently reads —
each backed by a real, already-existing per-tile dict. `ruin` added
in A3 (roadmap step 28, `World.ruin_scars`) — the same unification
this module already provides, extended to the newest scar-shaped
dict rather than left as a fourth independent silo. Deliberately NOT
the spec's full nine-axis list (traffic/battles/pollution/fertility/
ownership/construction/ecology remain unfolded, see this module's own
docstring)."""


def location_character(world, x: int, y: int) -> dict[str, float]:
    """One tile's real accumulated history, read from the three
    existing per-location dicts `World` already maintains. Only keys
    present are ones with non-zero real intensity — same "sparse,
    absence means neutral" convention the underlying dicts already
    use, so a caller can't mistake "not in this dict" for "explicitly
    zero.\""""
    pos = (x, y)
    character: dict[str, float] = {}
    mining = world.mining_scars.get(pos)
    if mining:
        character["mining"] = mining
    disaster = world.disaster_scars.get(pos)
    if disaster:
        character["disaster"] = disaster
    ritual = world.ritual_activity.get(pos)
    if ritual:
        character["ritual"] = ritual
    ruin = world.ruin_scars.get(pos)
    if ruin:
        character["ruin"] = ruin
    return character
