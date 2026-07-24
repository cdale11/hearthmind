# Hearthmind — The Living Map (filed v1.34.4, explicit user vision)

Explicit user directive, verbatim intent preserved below in M1-M12:
the world map currently reads as "a static procedurally generated map
with moving agents placed on top of it." It should instead read as "a
living landscape continuously rewritten by the interaction between
civilization, nature, and time, where every century leaves visible
evidence on the terrain" — a player should be able to reconstruct the
world's history by looking at the map alone, without opening
diagnostics.

**Filed as its own vision doc** (project convention: large multi-part
design directives get their own doc, referenced from `docs/ROADMAP-
2026-07-REMAINING.md` rather than pasted whole into it — same
treatment `VISION-2026-07-21-SELFEVOLVING.md`/`VISION-2026-07-22-
LIVINGTERRARIUM.md` got). Cross-referenced against what already ships
today rather than treated as a blank slate — a fair amount of real
backend AND some real map rendering already exists for pieces of this
(scar-shaped overlays, the "🗺️ fields" toggle, ERA-styled
cartography, layout/architecture/dialect grammar); the honest gap is
narrower than "build this from nothing," but still substantial,
especially on rivers/hydrology and overlay UX quality.

## M1 — The map must communicate history, not just current state
Civilization, nature, climate, disasters, and wildlife should all
leave PERSISTENT visible marks — a player should be able to read the
world's history off the map alone.

**Already real, partial coverage**: `mining_scars`/`disaster_scars`/
`ritual_activity`/`ruin_scars` (all four scar-shaped dicts, `world/
terrain_evolution.py`) are real, slowly-decaying, map-painted overlays
— a genuine persistent-mark mechanism already exists and already has
a map consumer (`app.js` overlay rendering, per-category colors).
`world/spatial_memory.py`'s `location_character_from_dicts` (A9,
v1.34.1) is the read-side unification of exactly these four axes.
**Real gap**: coverage is 4 axes, not "all history" — no visible mark
exists yet for ordinary farming/grazing/road traffic/quarrying/
forestry short of the disaster/mining/ritual/ruin thresholds.

## M2 — Terrain must become dynamic, not just internally-tracked
Erosion, flooding, drought, forest regrowth, repeated farming,
quarrying, overgrazing, abandoned roads, heavy traffic should
gradually reshape terrain APPEARANCE over years, not only hidden
values.

**Already real**: `world/terrain_evolution.py`'s `apply_local_
activity`/`maybe_reclaim` (biome flips, forest succession — A2's
`compute_succession_pressure`, v1.14.0), `HydrologyField.moisture`
(A11, surface-only), `FarmGrid.soil_fertility`. **Real gap, the
biggest one**: `Tile.elevation` is still immutable (A11's own
roadmap entry already names this — "the biggest remaining piece,
touches the native-ported `TerrainGrid`, needs its own equivalence
pass") — real erosion/flooding-reshapes-the-land, quarry scars as
actual elevation changes rather than a flat color overlay, and A3's
"rivers re-carve their course" are ALL blocked on this one item.
Overgrazing/heavy-traffic have no visible-mark mechanism at all yet.

## M3 — Human civilization must visibly transform the landscape
Old roads visible after disuse, abandoned fields overgrow, ruins leave
foundations/debris, quarries scar hillsides, forests retreat/reclaim,
civilization's accumulated footprint obvious from the map.

**Already real**: ruins (`ruin_scars`, map overlay + build-site bias),
forest reclaim (`maybe_reclaim`, A2's succession pressure), mining
scars overlay. Roads decay (`world/roads.py`'s wear model) with a
map-visible paved/unpaved distinction, but **real gap**: does a fully
decayed/removed road leave any lasting trace, or does it vanish
cleanly? (Needs a direct check — likely no persistent "old road bed"
mark today, unlike the ruin-on-building-removal precedent.) Abandoned-
field overgrowth has no dedicated visual beyond ordinary fallow-tile
reclaim.

## M4 — Nature must visibly reclaim the world
Forests spread into abandoned regions, wetlands expand/shrink with
hydrology, migration creates recognizable paths/grazing patterns,
repeated natural events alter the landscape visibly.

**Already real**: forest reclaim, `WildlifeGrid`'s seasonal migration
(leave-in-winter/return-in-spring, v0.64.0). **Real gap**: no wetland
concept exists yet (hydrology drives moisture, not a distinct
wetland/marsh biome that expands/shrinks); no migration-PATH visual
(herds move, but nothing accumulates a "well-worn trail" mark the way
`ritual_activity` accumulates from repeated festivals — same
mechanism shape, different trigger, real reuse opportunity).

## M5 — Recently-shipped deterministic systems need real map
representation, not diagnostics-only
Hydrology, procedural terrain evolution, ecology, climate.

**Already real**: the "🗺️ fields" toggle (v1.27.0) IS exactly this
for moisture/soil-fertility/population-density — a real, if basic,
answer to this ask already shipped. Climate has no dedicated overlay
(only feeds weather/season, no persistent visual signature). Ecology
(wildlife density/trophic state) has stat tiles but no map overlay.

## M6 — Overlays must be genuinely informative, not uniform tinting
Study Cities: Skylines / Workers & Resources / Timberborn / Dwarf
Fortress conventions — gradients, hotspots, thresholds, spatial
patterns at a glance, never a guessing game about what an overlay
means.

**Real gap, and the sharpest critique in this whole request**: the
existing fields overlay (v1.27.0) is explicitly, honestly, a first
slice — flat tint bands, no legend, no threshold markers, no hotspot/
gradient emphasis. This is a genuine UI redesign item, not a backend
gap — the DATA (moisture, soil fertility, population density) is
real and already flowing to the client; only the rendering treatment
needs the reference-game-quality pass this item asks for.

## M7 — Every overlay should answer one specific gameplay question
Fertility → where farming is best. Moisture/groundwater → irrigation/
river influence. Wildlife → migration corridors/habitats. Pollution/
degradation → environmental stress. Never ambiguous.

Direct extension of M6 — reframes "redesign the overlay rendering" as
"design each overlay around ONE answerable question," a concrete
acceptance test for M6's redesign work. No pollution/degradation
concept exists in the sim yet at all (a real new-data gap, not just a
rendering one) — closest existing analog is the scar dicts (M1), which
already are a form of localized "environmental stress," just not
labeled or overlaid as one.

## M8 — Rivers/hydrology must visibly evolve: floodplains, seasonal
channels, marshes, sediment, dried riverbeds
**Real gap, blocked on M2's elevation-mutability item.** Rivers today
are fixed at world-gen (per CLAUDE.md's own MASTERCHECKLIST finding:
"rivers carved once... no material/affordance/genetics/chemistry
model" — det_sys.md's "procedural generation as continuous runtime,
not a world-gen step" through-line gap, A3/A11's own already-recorded
territory). This item is A3 + A11's elevation-mutability work, reframed
as a visual outcome rather than a mechanism — same underlying blocker,
worth sequencing together, not solving twice.

## M9 — A visual-history layer: fires, abandoned villages, ruined
structures, old roads, field boundaries, ancient walls, dried lakes,
reclaimed forests
This is M1 generalized into a name — the scar-shaped-dict pattern
already covers 4 of these ~8 named categories (fires -> could map onto
`disaster_scars`' wildfire branch already; abandoned villages/ruined
structures -> `ruin_scars`; reclaimed forests -> already visible via
biome flip, though not "marked" as former-farmland the way a ruin is
marked as former-building). Old roads, field boundaries, ancient
walls, dried lakes remain genuinely unbuilt.

## M10 — Environmental readability through landmarks, not just
numerical overlays — readable even with every overlay OFF
Distinct forests/cultivated regions/grazing lands/quarries/ruins/
wetlands/trade routes/settlements should stand out through the terrain
ITSELF.

**Real gap, and a distinct design axis from M6/M7** (those are about
overlay QUALITY; this is about whether the BASE map needs overlays at
all to read as alive). Partially addressed by `architecture_grammar`'s
per-building visual variety and paved-road color distinction, but a
farm tile, a grazing tile, a quarry tile, and untouched wilderness are
likely still visually similar today without an overlay active — worth
a direct check before scoping a fix.

## M11 — Every deterministic system should have SOME map
representation where possible
General restatement of M1/M5 as a standing completeness bar, not a
one-time task — same "review time discipline" shape as A23-A25's
standing items already in this roadmap (composability-over-content,
physical-consistency, LLM-call-site re-audit). Worth adding to that
same standing-discipline tier once the initial visual-history push
below lands, rather than as a one-shot item.

## M12 — Standing design philosophy
"Hearthmind should not resemble a static procedurally generated map
with moving agents on top of it... every century leaves visible
evidence on the terrain." Recorded as a standing directive in
CLAUDE.md's Observatory UI direction section (the natural home for
this — that section already governs map-vs-panel priority), not just
here — a philosophy statement should live where future work will
actually be checked against it.

---

Work from this doc only on future explicit direction naming a
specific item (M1-M11) or the roadmap's own Tier entry for it — same
standing convention as every other vision doc in this project.
