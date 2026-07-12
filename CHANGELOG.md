# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

## [0.39.0] — Per-agent inventory/trade, culture-specific buildings, per-family beliefs, Phase G v4

Picks up two of the remaining large-and-explicitly-flagged gaps (scoped,
not the maximal version of either) plus two smaller named gaps and one
more Phase G increment, per explicit user request.

### Added

- **Per-agent inventory/trade** (`Agent.inventory`) — a deliberately
  scoped first slice of the "genuinely large, architecturally separate"
  per-agent economy gap: a single good (personal food), stashed as a
  skim off successful farm/granary foraging (`FORAGE_INVENTORY_SKIM`),
  drawn on by the agent themselves before scrounging elsewhere, and
  directly shared with a colocated, non-rival, food-lacking neighbor
  (`Population._maybe_trade_food`) at a small relationship cost/gain to
  both sides. Not a market, not hauling, not multi-good — a real,
  mechanically complete first step, not a stub.
- **Culture-specific building type**: `BuildingKind.SHRINE`, foundable
  only once the settlement has established at least one tradition
  (`choose_building_kind`'s new `has_tradition` gate). A standing
  shrine deepens festivals held on its tile
  (`SHRINE_FESTIVAL_BOOST_MULTIPLIER`) and slightly raises the monthly
  omen-firing chance (`SHRINE_OMEN_CHANCE_MULTIPLIER`) — the first
  direct interaction between the new culture-buildings gap and Phase G.
- **Structured per-family belief resolution**:
  `beliefs.resolve_family_agent_ids` widens a belief's resolved
  `subject_agent_id` to that person's living parents/children/full
  siblings (computed fresh from `Agent.parents` each formation/
  revision, not a separate family-id store), stored as
  `subject_family_agent_ids`. Dialogue's `beliefs_about` now also
  matches on family membership, so "the village believes the Hallow
  family is reckless" reaches every living Hallow's conversations, not
  only whichever name the LLM happened to write.
- **Phase G v4**: `SHRINE_OMEN_CHANCE_MULTIPLIER` (see above) — the
  first Phase G nudge driven by a player-visible building rather than
  pure event-count fortune, still small and non-dominant.

### Deliberately not attempted this batch

- **Multiple named settlements** (`Settlement` stops being a
  world-wide singleton) remains out of scope — a genuinely
  architecture-breaking refactor touching population/engine/every LLM
  prompt/the interface layer/snapshot schema, correctly flagged in
  CLAUDE.md as too large to bundle safely alongside other work.
  Attempting it in the same pass as the above risked leaving the
  simulation in a half-migrated, unverifiable state, which the
  project's own "no half-finished pieces," "audit before continuing,"
  and "preserve existing behavior" rules all argue against. See
  docs/DECISIONS.md for the explicit scoping rationale.

## [0.38.0] — Phase G v3: temperament's reach, omen memory

Deepens Phase G further per explicit user request — still within the
standing "keep this ambiguous, permanently" constraint (CLAUDE.md):
nothing here confirms anything supernatural, it only extends where
`Settlement.temperament`'s existing small-magnitude influence reaches
and gives `llm/omens.py` a memory of itself.

### Added
- **Temperament's mechanical reach extended to two more systems**,
  same warm-only, small-magnitude (~0.2 fractional) treatment as the
  existing invention-chance/predator-lethality nudges:
  - **Migrant arrivals** (`Population._maybe_welcome_migrant`): a
    village with recent good fortune draws a newcomer somewhat more
    readily (`MIGRANT_TEMPERAMENT_INFLUENCE`). Deliberately one-sided
    — ill fortune doesn't suppress this, since it's already the sole
    recovery path out of a population crash and shouldn't be actively
    worked against by the same bad luck that likely caused the crash.
  - **Wildlife recolonization** (`WildlifeGrid.tick`): the land itself
    recovers a herd/pack somewhat more readily during a warm spell
    (`WILDLIFE_TEMPERAMENT_INFLUENCE`), same one-sided rationale.
- **Omen memory.** New `Settlement.omen_history` (capped rolling log,
  same shape as `priority_history`) records every omen that's fired.
  Recent omens are now optionally offered back into the next omen
  prompt as texture — a new sighting can occasionally read as an echo
  of something noticed before ("that crow again") rather than always
  being a one-off, deepening the "ancient, subtle intelligence with a
  long memory" framing. Optional, not mandatory — most omens still
  stand alone, and nothing is ever confirmed either way.

### Notes
- Still no player-facing acknowledgment that Phase G exists anywhere in
  the UI — deliberately, permanently, per CLAUDE.md.

## [0.37.0] — Everything left from the original plan, including Phase G

Closes out essentially every remaining "not yet built" item across
`docs/ROADMAP.md` and CLAUDE.md's flagged next steps — excluding the
two items the project's own docs call out as genuinely large,
architecturally separate efforts (per-agent inventory/trade, multiple
named settlements), which stay explicitly out of scope for a single
batch.

### Added — Phase A (ecology & relationships)
- **Deliberate hunting, corrected from a stale roadmap note.** FORAGE's
  target-seeking already walks a hungry agent toward a known grazer
  herd (`_nearest_grazer_herd`), not just opportunistic consumption
  when colocated by chance — a dedicated `AgentGoal.HUNT` would have
  duplicated that. `docs/ROADMAP.md` corrected.
- **Vegetation depletion tied to grazing.** A grazer herd colocated
  with a wild FOOD `ResourceNode` now consumes a small amount of it
  each tick and skips reproduction on an overgrazed tile — real
  competition between wildlife and agent foraging for the first time
  (`world/wildlife.py`'s `GRAZE_CONSUMPTION_PER_TICK`/`GRAZE_
  REPRODUCE_MIN_FOOD`).
- **Rivalry-driven avoidance.** A rival's tile (relationship at or
  below `RIVALRY_THRESHOLD`) is now folded into the same prefer-avoid
  set predator tiles already use in movement dispatch — an agent
  actively steers around a rival, not just carries a lower affinity
  number.

### Added — Phase B (cognition)
- **Event-triggered cognition, beyond the daily cadence.** A hunger
  emergency or fresh grief now schedules an immediate goal
  re-evaluation (`Population.due_for_triggered_cognition`, with its
  own per-agent cooldown so a sustained crisis doesn't hammer the LLM
  every tick) instead of waiting for the agent's next staggered daily
  slot — a real, timely reaction using current state, not stale
  up-to-a-day-old context.

### Added — Phase C (construction)
- **Civic priority now steers *whether* to build, not just *what
  kind*.** The town brain's current priority already weighted which
  building kind gets founded; it now also scales the settle-chance
  roll itself (`SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER`/`_OFF_
  PRIORITY_MULTIPLIER`) — a settlement prioritizing growth is
  measurably likelier to found something at all. *Where* to build
  remains pure-chance colocation, a separate and larger change not
  attempted.

### Added — Phase G (subtle supernatural layer) + adjacent gaps
- **Intensity knob.** `Config.phase_g_intensity` (default 1.0) scales
  temperament's monthly step and omens' per-month chance together;
  0.0 is a genuine off switch (temperament holds flat, omens skip
  outright) without deleting the mechanism.
- **Person-specific omens.** About half the time an omen fires, if a
  belief already resolves to a still-living agent, the omen now
  centers on that person specifically (`llm/omens.py`'s `subject_name`,
  both the LLM prompt and new subject-templated fallback pools) rather
  than the settlement in the abstract — still never confirming
  anything, just less anonymous.
- **Trust lever.** New `Agent.trust` (-1..1 per source agent), distinct
  from `relationships` (fondness) — how much credibility an agent gives
  another's word. Nudged asymmetrically on dialogue (easier to lose
  than earn); a rumor from a source below `TRUST_SKEPTICISM_THRESHOLD`
  is now remembered with visible skepticism instead of at face value,
  which reaches that agent's own future cognition prompts.
- **The town's opinion of the player.** New `Settlement.player_standing`
  (-1..1), a real deterministic bounded random walk (`tick_player_
  standing`, same shape as `temperament`) nudged monthly by recent
  `/intervene/*` volume, mean-reverting without reinforcement. Folded
  into the town-brain prompt as one more quiet input once notably
  warm/cold — never narrated or labeled in the UI.

### Notes
- Deliberately not attempted: per-agent inventory/trade, multiple named
  settlements (both flagged large/architecturally-separate in the
  project's own docs), culture-specific building types, structured
  per-family belief resolution, a true scrub-through-time replay view,
  and *where* to build. See `docs/ROADMAP.md` for the full per-item
  accounting and `CLAUDE.md`'s "Known architectural gaps" section.

## [0.36.1] — Sidebar restructure: map-as-primary-interface, the last backlog item

Closes the one item 0.36.0 explicitly left as "partial": the sidebar
itself carried its full panel set regardless of relevance. Restructured
so only the two panels the Observatory UI direction names for "normal
UI, understanding the world" — Town Brain and Recent Events — are
visible by default. Everything else (raw stat tiles, beliefs/
traditions/inventions/festivals lists, infrastructure detail) now lives
behind a new "📊 details" header toggle, using the exact same show/hide
pattern already established for history/relationships/dev-console —
reachable, not gone, just not the first thing shown, per the brief's
own wording. Verified live in a browser (Playwright): default view is
now just the map + two panels + the consequences overlay; the details
toggle correctly reveals/hides the grouped stat tiles and culture
panels; hover, the NPC inspector, and sim-speed controls all still work
unaffected by the restructure.

With this, every item CLAUDE.md's Observatory UI direction section
listed is now either done or explicitly, narrowly scoped (documentary
mode's cadence/source, the consequences overlay's specific phrasings,
etc.) — no remaining "not started, deliberately" entries.

## [0.36.0] — Observatory UI backlog complete: hover, NPC inspector, consequences overlay, surfaced conversations, Town Brain monologue, documentary mode

Closes out the rest of the Observatory UI backlog CLAUDE.md scoped last
session (0.34.0) but deliberately deferred, plus the relationship graph
started in 0.35.0. Six pieces, one batch:

### Added
- **Hover inspection extended to the whole map**, not just agents.
  Hovering a building shows kind/stage/condition (and construction
  progress while under way); hovering bare terrain shows its biome and
  coordinates. Agent hover tooltip now hints "click for details."
- **NPC inspector modal**, mind-first per the brief: clicking an agent
  opens a panel leading with their current goal and *why* they chose it
  (`goal_reason`), what the village's collective beliefs say about them
  (`Settlement.beliefs` filtered by `subject_agent_id`), their named
  relationships (not raw IDs, sorted by strength), and recent memories
  — vitals (hunger/energy/position) are a single small row at the
  bottom, not the headline. Stays open and live across ticks while
  inspecting the same agent.
- **Consequences overlay** on the map itself: a small overlay strip
  (bottom-left of the map panel) surfaces plain-language readouts —
  "The village is aging," "Granaries are nearly full," "Food stores are
  running dangerously low," "Wolves have returned," "A heatwave grips
  the land," "Floodwater has swallowed part of the village," "Wildfire
  is spreading through the forest," "The village teeters on the edge of
  extinction" — computed client-side from stats already in the payload,
  the exact examples the brief named. Threshold for "aging" mirrors
  `agent.py`'s own `MIN_LIFESPAN_TICKS` constant.
- **Surfaced conversations**: `Population.apply_dialogue` now returns
  whether an exchange was significant (crossed into a close bond or
  rivalry, or carried a rumor) alongside the two agents. Significant
  exchanges log under a new `dialogue_surfaced` category (shown in the
  main event feed and the curated History tab); routine background
  chatter stays under the existing `dialogue` category, which the main
  feed now filters out by default (still fully recorded — `/events` and
  the dev console see everything) — "record all conversations
  internally, surface the ones that changed something."
- **Town Brain monologue**: `Settlement.priority_history` keeps the
  last 6 seasonal town-brain decisions (tick/priority/rationale), not
  just the current one. The Town Brain panel now shows past rationales
  beneath the current priority — read together, they read as an
  ongoing internal train of thought ("what the town notices, values, or
  is quietly influencing"), not a single overwritten line.
- **Documentary mode**: a new yearly LLM job (`llm/documentary.py`,
  gated on the rare `year_end` calendar boundary — deliberately the
  slowest narrative cadence, rarer than chronicle's monthly one) writes
  a short narrated look-back over the year's curated milestones
  (`persistence.snapshot.history_events` — the same subset the History
  tab already shows, not the raw everything-included feed chronicle
  uses). Logged under a new `documentary` category, shown in both the
  main event feed and the History tab. Has a deterministic fallback
  (a plain factual recap) when the LLM is disabled/unreachable, same as
  every other narrative job.

### Notes
- The map-as-primary-interface ask is substantially, not fully,
  addressed: hover/click inspection and the consequences overlay now
  live directly on the map, but the sidebar still carries its full set
  of panels rather than being restructured/thinned — a genuinely
  separate, larger redesign this batch didn't attempt.
- With this batch, every item CLAUDE.md's "Observatory UI direction"
  section listed as "not started" is now started: relationship graph
  (0.35.0), hover inspection, mind-first NPC inspector, surfaced-
  conversation filtering, Town Brain monologue reveal, and documentary
  mode (this release).

## [0.35.0] — Realistic snow/heatwave/frost, live sim-speed controls, relationship graph

### Fixed
- **Snow never actually fell.** `is_snowing` required `temperature_c <=
  0.0`, but `compute_weather`'s smoothing (an EMA-like blend toward the
  previous tick, `smoothing=0.7`) damps the raw per-tick jitter into a
  much narrower realized range than the underlying `uniform(-6, 6)`
  draw suggests — verified a simulated December at the default seed
  never once reached 0C (min observed 0.35C across a multi-year
  sample). `is_snowing` was live code that could never fire. Fixed by
  raising the threshold to `SNOW_TEMPERATURE_THRESHOLD_C = 2.0`
  (`world/weather.py`) — within the range winter baselines actually
  reach, and still correct UK meteorology (most UK snow falls in the
  0-2C band, not exactly at freezing). Verified: ~0.6 snow-tick-days
  per winter month at the default seed, roughly matching real lowland
  UK snow frequency.

### Added
- **Two new natural disasters, UK-historical**: heatwave and frost/cold
  snap, joining the existing flood/wildfire/storm (`world/disasters.py`).
  Both use the same pressure-buildup shape as flood, tuned against
  `compute_weather`'s actual smoothed output range (an early cut of
  heatwave that required simultaneous hot-and-dry conditions to even
  build pressure fired zero times across a simulated year — the same
  class of "threshold the model can never reach" bug as the snow fix
  above; reworked so pressure builds from sustained heat alone, and
  dryness only sharpens the trigger roll once pressure clears
  threshold). Heatwave: wilts/spoils farm plots each tick it's active,
  raises wildfire ignition odds (`HEATWAVE_WILDFIRE_CHANCE_MULTIPLIER`),
  and now counts as harsh weather for agents (`Population.tick`'s new
  `heatwave_active` param folds into the existing `weather_harsh` check
  alongside rain/wind/snow) — echoing the UK's 2018 and 2022 heatwaves,
  both of which came with drought and a spike in wildfires. Frost: a
  sustained hard freeze (colder than the snow band, `FROST_TEMP_
  THRESHOLD = 2.0` sustained `FROST_DURATION_MIN_TICKS`) has a small
  chance of one sharp hit damaging every farm plot at once — a rare,
  multi-year event by design, echoing the UK's 2018 "Beast from the
  East". `World._tick_disasters` now runs before `population.tick` (not
  after) so a heatwave/frost triggered this tick is already felt by
  agents/farms the same tick, not one tick late. New history/event
  categories `disaster_heatwave`, `disaster_frost`.
- **Live simulation-speed controls** — pause, speed up/down, reset to
  default — changeable from the browser UI in real time, no restart
  needed. Deliberately NOT routed through the existing `/intervene/*`
  queued-intervention seam (`WorldBroadcaster.enqueue_intervention`,
  drained once per tick inside `_tick_once`): a paused sim never calls
  `_tick_once`, so a queued "resume" would never be applied and the sim
  would deadlock paused forever. Instead `WorldBroadcaster` gained
  plain pause/speed-multiplier fields (`set_paused`/`get_speed_
  multiplier`/etc., `interface/api.py`) that `SimulationEngine.
  run_forever`'s loop reads directly every iteration — safe because the
  FastAPI handler and the tick loop share one asyncio event loop and
  never run concurrently. New `POST /intervene/sim-speed` endpoint
  (`interface/app.py`) with `action` one of `pause`/`resume`/`speed_up`/
  `speed_down`/`set`/`reset`; speed is bounded to [0.25x, 8x]
  (`MIN_SPEED_MULTIPLIER`/`MAX_SPEED_MULTIPLIER`). Current pacing is
  surfaced in the per-tick diagnostics payload (`sim_pacing`) and in
  the endpoint's own response, so the UI reflects state instantly even
  while paused (when no new tick broadcast is coming). New header
  controls in the browser UI: ⏸/▶ pause toggle, −/+ speed buttons, a
  live "Nx" label, and a reset button.
- **Interactive relationship graph** — the first piece of the
  Observatory UI backlog from 0.34.0's CLAUDE.md direction ("provide an
  interactive relationship graph"). New "🕸 relationships" toggle opens
  a force-directed graph built client-side from data every agent
  already carries (`Agent.relationships`, no backend change needed):
  nodes drift together for fond pairs, apart for sour ones; edge
  color/thickness tracks bond strength (green/red, opacity and width by
  magnitude); hovering a node shows the agent's name. Relationships
  below `REL_MIN_AFFINITY = 0.08` are dropped from the graph entirely
  to keep it readable. Node positions persist across ticks so the
  layout settles rather than jittering on every update; the physics
  loop only runs while the panel is open.

### Notes
- The rest of the Observatory UI backlog (map-as-primary-interface
  rework, hover inspection, mind-first NPC inspector, Town Brain
  monologue reveal, documentary mode) remains not started, per 0.34.0's
  CLAUDE.md note — this batch completed the weather/disaster/speed-
  control asks plus the relationship graph the user asked to start
  with, not the rest of the backlog.

## [0.34.0] — Population recovery, LLM-cadence fix (whispers), Observatory UI direction

### Fixed
- **Population could stagnate/crash toward extinction with no recovery
  path.** Root-caused: reproduction itself works correctly (verified
  via a proper engine-driven run reaching 198 of the 200 population
  cap from 12 starting agents), but a population crashed down to 1-3
  survivors (predation, starvation, disasters, or just old age
  outpacing sparse early births) had no way back — reproduction needs
  a colocated, mature, healthy, mutually-affinity-0.6+ pair, and with
  only a couple of survivors left there may be nobody eligible.
  `Population._maybe_welcome_migrant` mirrors wildlife's
  `_maybe_recolonize`: a rare newcomer, already mature, arrives at the
  settlement when population is critically low (1-3) but not zero.
  Deliberately does *not* revive a fully extinct (0-population)
  settlement — per this session's explicit "settlements expand or
  collapse" design direction, total extinction is a legitimate,
  permanent, readable-from-the-landscape ending, not a bug.
- **Player whispers (`POST /intervene/town-brain`) felt broken.**
  Root cause: `town_brain` (which consumes queued whispers) only fired
  on `season_end` — with the real 365-day calendar a season is ~91
  days, ~8700 ticks, ~2.4 hours of real wall-clock time at default
  pacing before a whisper was ever read. The same "real calendar makes
  season/year cadences much rarer than intended" problem CLAUDE.md
  already documents for terrain evolution, unaddressed here until now.
  Moved town_brain/chronicle/festival to `month_end` and tradition/
  invention to `season_end` (one tier faster each, preserving their
  relative rarity ordering); `INVENTION_CHANCE_PER_YEAR` ->
  `INVENTION_CHANCE_PER_SEASON` (0.5 -> 0.15, so four seasonal rolls
  reproduce the original annual rate) and `FESTIVAL_CHANCE_PER_SEASON`
  -> `FESTIVAL_CHANCE_PER_MONTH` (0.35 -> 0.13, same reasoning).
  Verified: a queued whisper is now consumed within ~1600 ticks
  (~27 real minutes) of the next settlement, down from ~2.4 hours.

### Added
- `docs`/`CLAUDE.md`: a new "Observatory UI direction" design-memory
  section capturing this session's UI/UX brief (map as primary
  interface, hover inspection, consequences over raw stats, curated
  history vs. developer diagnostics kept separate, NPC inspection
  leading with mind over stats, relationship graph, Town Brain
  internal-monologue reveal, documentary mode) — none of the UI work
  itself was attempted this batch (explicitly scoped out: too large
  for one coherent milestone), flagged back to the user to pick a
  starting point rather than guessing.
- `migrant_arrived` life-event category, added to `HISTORY_CATEGORIES`
  and the client's category-icon table.

## [0.33.0] — Natural disasters, rivers & lakes, daylight-driven behavior

### Investigated (no code bug found)
- **"History tab not working"** — read/executed the full path (SQL
  query, `GET /history`, `app.js` wiring, `index.html` IDs) end-to-end;
  it's correct. `HISTORY_CATEGORIES` matches every category string
  actually logged, byte-for-byte. Most likely explanation: the server
  process wasn't restarted after pulling v0.32.0 (uvicorn doesn't
  hot-reload) and/or the browser served a cached pre-upgrade `app.js`
  despite the existing `?v=<version>` cache-bust. If it's still broken
  after a hard restart + hard-reload, that's new information worth a
  fresh diagnostic report.

### Added — natural disasters (`world/disasters.py`)
- **Flood**: sustained heavy rain (precipitation past the existing
  "harsh weather" threshold) builds flood pressure; once past
  threshold, a small per-tick chance submerges a random water-adjacent
  low tile for ~40 ticks, damaging any building/vehicle caught there
  and destroying any farm plot, then recedes back to its original
  biome.
- **Wildfire**: dry summer forest can ignite (rare weekly roll, chance
  nudged upward by ill-fortune `Settlement.temperament` — same lever
  Phase G already uses for invention/predator rolls), then spreads
  tile-to-tile for a few ticks, turning forest to ash (grassland) and
  damaging any building in its path, before burning out.
- **Storm**: extreme wind (well past the routine "harsh weather"
  threshold) has a small per-tick chance of directly damaging every
  standing building and vehicle map-wide — a sharper, rarer hit
  layered on top of routine weather-decay.
- All three log real life-events (`disaster_flood`, `disaster_wildfire`,
  `disaster_storm`), added to `HISTORY_CATEGORIES` and the client's
  terrain-refresh/category-icon tables, and physically alter buildings/
  vehicles/farms/terrain — not narration bolted onto nothing.

### Added — rivers and lakes (`world/hydrology.py`)
- **Rivers**: carved once at world creation by steepest-descent from
  high-elevation sources (mountain/hills/snowcap) down to existing
  water or the map edge — a new `Biome.RIVER`, visible on the map and
  in `biome_counts`. Persist automatically through terrain's existing
  (de)serialization; no extra state needed. Rivers "evolve" via the
  flood mechanic above (sustained rain temporarily expands water onto
  riverbank land) rather than a separate river-specific tick.
- **Lakes**: inland water bodies (flood-filled components that never
  touch the map border, as opposed to the ocean, which does) each get
  their own slowly-changing `level` — a bounded random walk nudged
  monthly, biased toward the map-wide climate-drying trend. Crossing a
  threshold grows or shrinks the shoreline by one tile
  (`lake_rose`/`lake_receded`), so a lake visibly changes size over
  years, same "evolves over time" contract as the existing climate
  drift. A pre-hydrology-pass snapshot gets rivers carved and lakes
  identified once on load (same backfill pattern as every other
  subsystem migration).
- New "Geography"/"Disasters" stat tiles in the UI.

### Added — daylight now affects agent behavior, not just lighting
- `world/daylight.py` mirrors the client's `UK_DAYLIGHT_HOURS` table
  and `nightFactor` ramp server-side. An AWAKE agent now burns energy
  up to 30% faster the deeper into the night it is (same order of
  magnitude as the existing harsh-weather multiplier — staying up all
  night costs about as much as working through a storm), the
  involuntary-rest energy threshold rises at night (agents settle in
  for the night sooner rather than only collapsing from exhaustion),
  and RESTING energy recovery gets a small night bonus (sleep is more
  restful than a daytime nap). Previously `night_factor`/daylight hours
  only drove the map's visual darkening tint.

## [0.32.0] — Map/UI/ecology follow-up: bug fixes + history tab + UK daylight + diagnostics

### Fixed
- **Wildlife could go permanently extinct.** `WildlifeGrid` had no
  repopulation mechanic after world creation — a species that ever hit
  0 herds/packs (predators starving out, especially likely now that
  grazers flee) was gone forever. Added `_maybe_recolonize`: a rare,
  per-tick roll that can spawn a new grazer herd or (only if grazers
  already exist to sustain it) a predator pack, migrating in from
  beyond the map's edge. Directly root-caused from a live report
  showing "0 predators (0 packs)."
- **Roads were nearly invisible.** The old `wear * 0.6` alpha scaling
  made anything below "established" (wear >= 0.5) read as ~6% opacity
  — practically invisible. Roads now get a visible tint from the first
  bit of wear.
- **Wild resource nodes (bushes/mines) weren't sent to the client at
  all** — only an aggregate count reached the UI, never actual
  positions. Now broadcast every tick and rendered as small map
  markers, dimming as they deplete.
- Buildings render larger (bleeding 1px past their tile) with a
  brighter stroke for legibility against terrain.

### Added
- `GET /history` + a History tab: a curated, summarized town history
  (founding, naming, era advances, chronicle/tradition/invention/
  festival entries, beliefs formed/revised, omens, wildlife
  recolonization) filtered out of the everything-included live event
  feed.
- Real UK daylight hours: the map's day/night lighting now varies by
  month (~8h daylight in December, ~16.5h in June) instead of a fixed
  6am-6pm ramp, via an approximate London-latitude sunrise/sunset
  table. A new "Daylight" stat tile shows the current month's sunrise/
  sunset.
- Season-based building/vehicle wear: `SEASON_DECAY_MULTIPLIER`
  (winter 1.4x, autumn 1.15x, spring 1.0x, summer 0.85x) applied on top
  of the existing weather-harshness multiplier — freeze-thaw and damp
  genuinely wear structures faster than a dry summer, independent of
  any single tick's weather.
- Beliefs now feed festival and invention prompts too (previously only
  town_brain, chronicle, and matched-agent dialogue) — broadening how
  the village's own accumulated theories shape what the LLM does, per
  "beliefs should affect the whole village."
- Extensive new diagnostics: `full_diagnostics()` now includes
  `last_llm_calls` (the most recent prompt + result + fallback flag for
  every named LLM job — town_brain, beliefs, omen, naming, chronicle,
  tradition, invention, festival, dialogue), `pending_player_whispers`,
  and `temperament`. The whisper form also shows queued-but-not-yet-
  heard whispers directly in the UI, not just in diagnostics.

See `docs/DECISIONS.md`, "map/UI/ecology follow-up," for the full
per-item root-cause writeup, including two items deliberately scoped
out of this batch (rivers as a distinct terrain feature; daylight
hours driving anything beyond the visual lighting tint).

## [0.31.0] — Live-diagnostics follow-up: vehicle eras, dialogue quality, LLM-authored naming

Driven directly by a real user diagnostic report running `qwen3.5:2b`
(confirmed working, <4GB RAM) — see docs/DECISIONS.md, "live-diagnostics
follow-up (vehicles/dialogue/naming)."

### Added
- `VehicleKind.AUTOMOBILE`: an era-gated (`modern`+) upgrade over
  MOUNT, faster (2.2x vs 1.6x) and costlier. Answers "why carts in an
  industrial era": carts/mounts stay realistic at `industrial`/
  `electrical` (horse-drawn transport genuinely coexisted with early
  industry), and transport now genuinely modernizes alongside
  buildings once the era does, the same way FACTORY already did for
  buildings.
- `llm/naming.py`: settlement naming is now LLM-authored, informed by
  the founding scenario and terrain, rather than a bare random
  prefix+suffix draw. The existing deterministic name generator still
  provides an instant placeholder the tick a settlement is born (every
  other system gates on `settlement.name` being set) — the LLM's name
  replaces it in the background once the one-time job resolves.

### Fixed
- `llm/dialogue.py`: the system prompt now includes few-shot examples
  (small/weak models benefit disproportionately from this) and
  explicitly forbids meta-commentary/instruction leakage. `parse_dialogue`
  gained a sanity filter (`_is_sane_line`) rejecting lines that leak
  instructions, run wildly over length, exactly duplicate the other
  speaker's line, or contain stray JSON braces — degrading to the
  deterministic fallback pool instead of surfacing garbled small-model
  output. Root-caused from the user's direct report that dialogue "makes
  no sense."
- `Config.llm_timeout_seconds` bumped 30 -> 45: the user's live
  diagnostics showed p50 17.4s / p95 19.7s / max 29.7s against a 30s
  timeout on `qwen3.5:2b` — a razor-thin margin despite the model
  itself working correctly (0% observed fallback rate). Not a sign the
  model is failing; a smaller model isn't necessarily faster in
  wall-clock terms on constrained CPU hardware.

## [0.30.0] — Add: Phase G v1 (temperament + omens), per-person beliefs

### Added
- **Phase G v1** (started early, in parallel, per explicit user
  instruction): `Settlement.temperament` (-1..1), a real deterministic
  bounded random walk nudged monthly by the recent balance of good/ill
  fortune (`buildings.tick_temperament`), applying small, deliberately
  subtle nudges to invention chance and predator-attack lethality.
  `llm/omens.py`: a rare, LLM-authored (or fallback-pool) ambiguous
  flavor event, chance scaled by |temperament|, worded to always have a
  mundane explanation and never confirm anything supernatural. Nothing
  in the UI labels this as "mood" or "supernatural" — it's plumbed
  through like any other internal stat.
- **Per-person beliefs**: `beliefs.resolve_subject_agent_id` matches a
  belief's free-text subject against current agent names and tags
  `subject_agent_id` on the entry; matched beliefs are now folded into
  that person's own dialogue prompts (`llm/dialogue.py`'s new
  `beliefs_about` param), so a belief about a specific villager
  actually shapes what they and their conversation partner say.

See `docs/DECISIONS.md`, "Phase G / per-person beliefs follow-up."

## [0.29.0] — Add: world beliefs (continuous cognition); model set to qwen3.5:2b; drop legacy calendar compat

### Added
- `llm/beliefs.py` + `Settlement.beliefs`: the village's own persistent,
  evolving theory of itself. Once a month, for a named settlement, the
  LLM (or its deterministic fallback) forms a new belief about a
  person/family/tradition/pattern/outside-influence, or revises one it
  already holds, given recent history — and those beliefs are fed back
  into the next town-brain and chronicle prompts as accumulated
  context, so the LLM's own past interpretations shape its future
  ones. Capped at 12 entries (lowest-confidence evicted). New "The
  village's own theories" UI panel, `inspect_world` section, and
  `belief_formed`/`belief_revised` event categories.

### Changed
- Default LLM model set to `qwen3.5:2b` per explicit user instruction
  (confirmed available on their machine, correcting this project's
  earlier assumption that no "Qwen3.5" existed).
- Legacy pre-real-calendar snapshot compatibility deliberately dropped
  per explicit user instruction — `World.from_dict` no longer
  reconstructs a synthetic calendar from an old `days_per_season`/
  `seasons_per_year`-only config block; every snapshot is expected to
  carry `days_per_month`/`month_names`/`month_to_season`.

See `docs/DECISIONS.md`, "World-model/beliefs follow-up."

## [0.28.0] — Add: real 365-day UK calendar, eras, LLM-genesis seed, model swap

### Added
- Real 365-day, 12-month calendar (`time_system.py`) replacing the old
  fixed 20-day, 4-season year — `season` is now derived from the month
  via UK meteorological convention, so everything already keyed off it
  (weather baselines, farm growth, chronicle/tradition/invention/
  festival/town-brain cadence) kept working unchanged. Existing worlds
  keep their original calendar shape (creation-only, reconstructed
  losslessly from legacy snapshots — see `World.from_dict`).
- `world/weather.py` baselines rewritten to a UK-style temperate
  maritime climate at monthly granularity (mild wet winters, cool damp
  summers, rain fairly even year-round).
- Terrain-evolution cadence (nature reclaiming abandoned land, climate/
  biome drift) decoupled from season/year boundaries onto fixed weekly/
  monthly ticks instead, plus a slightly higher climate-drift sample
  rate — the real calendar being ~4.5x longer than the old one would
  otherwise have made map evolution proportionally rarer in wall-clock
  terms, which is what "the map doesn't seem to be evolving" was
  actually pointing at (the broadcast/redraw wiring itself was already
  correct).
- Eras: a settlement starts `industrial` and advances (electrical ->
  modern -> digital) purely as a function of accumulated `tech_level`
  (`buildings.era_for_tech_level`) — each era is a mechanically real
  unlock, not a label: the new FACTORY building kind (double a
  workshop's currency income) only enters the foundable pool past
  `industrial`.
- `llm/world_genesis.py`: a one-time "genesis" LLM call, made before a
  brand-new world's terrain/weather are generated when `--seed` is
  omitted — the LLM writes a short founding-scenario sentence, and its
  hash becomes the world's seed, so "initial terrain and weather chosen
  by an LLM" is literal. Falls back to a wall-clock-mixed seed from a
  rotating scenario pool if the LLM is disabled/unreachable. An
  explicit `--seed` always skips genesis; a resumed world never re-runs
  it. The scenario text is shown once in the event log and persisted on
  `Settlement.founding_scenario`.
- Default LLM model moved to `qwen3:4b` (Qwen3, not "Qwen3.5" — that
  doesn't exist — at the 4B tier, ~2.6GB Q4) from `qwen2.5:7b-instruct`
  (~4.5GB): a newer generation, smaller, generally matching or beating
  the old default's quality on community benchmarks. `qwen3:1.7b`
  (~1.1GB) is the documented lighter fallback. `OllamaClient` now sends
  `"think": false` and defensively strips any `<think>` block, since
  Qwen3's hybrid thinking mode would otherwise risk breaking the
  strict-JSON parsing every call here relies on.

### Fixed
- `server.py`'s `--llm-model`/`--llm-timeout` CLI flag defaults had
  drifted out of sync with `Config`'s own defaults (still hardcoded to
  the pre-0.27.0 `qwen2.5:3b`/20s) — running the CLI without explicitly
  passing those flags silently used stale values. Both flags now read
  their defaults from `Config` directly so they can't drift again.

See `docs/DECISIONS.md`, "Real-calendar/genesis-seed follow-up."

## [0.27.0] — Add: economy buildings, town brain, animal/road weather, infrastructure telemetry

### Added
- Workshop/school/hospital/university buildings with real mechanical
  effects (currency income, education -> invention chance, faster
  hospital rest recovery + reduced predator lethality, school-to-
  university upgrade path).
- `llm/town_brain.py`: a seasonal LLM decision sets the settlement's
  current civic priority, which measurably steers which building kind
  gets founded next — the concrete "LLM as the town's brain" mechanic.
- `POST /intervene/town-brain`: a subtle player-influence channel — a
  short text whisper folded into the next town-brain prompt.
- Grazer herds now flee adjacent predators instead of wandering
  blindly; predator hunts/pack extinctions are now logged events.
- Roads get genuinely muddy/snowy/icy depending on weather, changing
  their move-speed bonus (icy can even be a penalty).
- `Settlement.infrastructure_report()` + a new sidebar panel: every
  building/vehicle's condition in plain language (excellent/good/worn/
  critical/broken/ruined), worst-first.
- Default LLM model bumped to `qwen2.5:7b-instruct` for better NPC
  dialogue/town-brain quality (timeout bumped 20s -> 30s to match).

### Fixed
- Dialogue, chronicle, tradition, invention, festival, intervention,
  and town-brain events never appeared in the live browser event feed
  (only on page load, via the one-shot `/events` fetch) — they resolve
  outside `World.tick()` and were never folded into the broadcast
  payload. Fixed with a new `SimulationEngine._log` helper.

See `docs/DECISIONS.md`, "LLM-as-brain batch: economy buildings, town
brain, animal/road weather, infrastructure telemetry."

## [0.26.0] — Add: interventions, family memory, smooth/lit rendering

### Added
- `/intervene/agent-goal`, `/intervene/settlement`, `/intervene/weather`
  POST endpoints — queued and applied by the engine at the top of its
  next tick, logged as `intervention` events.
- Family memory: a newborn remembers both parents from birth, parents
  remember the birth; losing a parent/child logs a memory and pays
  grief regardless of numeric relationship value. NPC dialogue prompts
  now recognize a parent/child pair as family, not just by affinity.
- Smooth inter-tick agent movement interpolation, and a day/night +
  weather lighting tint on the browser map.

See `docs/DECISIONS.md`, "Interventions, family memory, and smooth/lit
rendering."

## [0.25.0] — Add: terrain evolution (local activity + climate drift)

### Added
- `world/terrain_evolution.py`: sustained GATHER pressure thins forest
  to grassland (deforestation); an abandoned grassland tile bordered by
  forest can revert to forest once a season (reclamation); a slow,
  bounded yearly `warming`/`drying` random walk gradually shifts a
  small sample of tiles' biomes map-wide (climate drift).
- `terrain.classify_with_bias`, `BIOME_ORDER`: the same elevation-based
  biome classifier, now bias-parameterizable and steppable one biome at
  a time.
- Browser map and `GET /terrain` now refresh on an actual terrain
  change instead of assuming terrain is static after boot.
- New "Climate trend" stat tile; event icons for
  `terrain_thinned`/`terrain_reclaimed`/`climate_drift`.
- `inspect_world` prints the current climate bias.

See `docs/DECISIONS.md`, "Terrain evolution: local activity + climate/
biome drift."

## [0.24.1] — Fix: dev console diagnostics copy-to-clipboard

### Fixed
- "Full diagnostic report" copy failed silently on any non-https,
  non-localhost origin (`navigator.clipboard` requires a secure
  context — the API is simply absent over plain `http://<lan-ip>`, not
  just denied). Added a `document.execCommand("copy")` legacy fallback
  and a status message that explains the requirement instead of always
  saying the same generic thing.

See `docs/DECISIONS.md`, "dev-console-copy-fallback."

## [0.24.0] — Add: vehicles (hauling carts + personal mounts)

### Added
- `settlement/vehicles.py`: carts and mounts, built from settlement
  materials the same way buildings are (colocated founding, presence-
  driven construction/repair, weather decay + break-down).
- Carts: settlement-wide, each ready cart adds 25% to gathered-material
  haul yield (stacks up to 3).
- Mounts: an awake agent claims a ready unclaimed mount and moves ~1.6x
  faster (stacks with roads) until it breaks down or they die.
- Browser UI: "Vehicles" stat tile, map markers (cart/mount), event
  icons for `vehicle_started`/`vehicle_completed`/`vehicle_broken`.
- `inspect_world` prints vehicle counts under the settlement summary.

See `docs/DECISIONS.md`, "Vehicles: hauling carts and personal-travel
mounts."

## [0.23.0] — Add: weather particle overlay; policy: determinism dropped

### Added
- Rain/snow particle effects on the browser map (`weather-canvas`,
  independent animation loop) — driven by a new `weather_detail` field
  in `World.summary()` (raw precipitation/wind/is_snowing/temperature).

### Changed
- **CLAUDE.md**: determinism/reproducibility is no longer a project
  requirement (explicit user instruction) — existing namespaced-RNG uses
  stay, but new work isn't constrained by seed-replay reproducibility.

See `docs/DECISIONS.md`, "Determinism dropped as a project requirement;
weather particle overlay."

## [0.22.0] — Fix + add: diagnostics, browser-default, resource variety, building cost

### Fixed
- NPC dialogue fallback repeated the same 3 lines forever when the LLM
  was unreachable — now cycles through small per-band pools.
- "A tooled field was planted..." → readable wording.
- `Population.dialogue_cooldowns` grew unbounded over a long run — now
  pruned (dead agents, stale entries) each tick.

### Added
- `GET /diagnostics` + dev console "Full diagnostic report" button:
  LLM call/latency/error breakdown, tick-duration percentiles, peak
  memory, DB size, all-time event-category histogram — built for
  pasting into a bug report after an unattended overnight run.
- Resource variety: `ResourceNode.kind` (FOOD/ORE) — hills-only ore
  veins regenerate 12x slower than food nodes, season-scaled like food.
  GATHER-goal materials collection on hills now draws from ore
  specifically (forest wood stays uncapped/renewable).
- Buildings now cost real materials to found (`HUT_MATERIALS_COST`/
  `GRANARY_MATERIALS_COST`), not just a speed bonus — a settlement with
  an empty stockpile can no longer spontaneously build.

### Changed
- Browser interface (`api_enabled`) is now **on by default**;
  `--api-disabled` to opt out. Missing `fastapi`/`uvicorn` degrades to a
  warning, not a crash.

See `docs/DECISIONS.md`, "Diagnostics, browser-default, resource
variety, real building cost."

## [0.21.0] — Add: predator danger, relationship memory, festivals, scarcity

### Added
- Agent-vs-predator danger: colocated agents can be attacked (injury,
  rarely lethal) by live predator packs; agents now prefer avoiding
  predator-occupied tiles when moving, falling back only if it's the
  only path.
- Relationship memory: `Agent.memories` (capped short log) populated by
  bond/rivalry formation, rumors, and grief on a bonded partner's death
  (with a real energy cost); fed back into the agent's own cognition
  prompt.
- Festivals: a new, wellbeing-gated (not prosperity-gated), seasonal-
  cadence collective event (`hearthmind/llm/festival.py`) with a direct
  mechanical effect — every currently-colocated pair of awake agents
  gets a relationship boost when one is held.
- Seasonal/weather scarcity: winter cuts farm growth and wild-resource
  regeneration; harsh weather (heavy rain/snow/high wind) increases an
  awake agent's hunger/energy drain. Makes genuine settlement decline
  possible during a bad season/weather streak, not just a plateau at the
  population cap.

### Changed
- `Population.tick`/`_update_needs` now take `weather`;
  `FarmGrid.tick`/`ResourceGrid.tick` now take `season`.
- `inspect_world` prints predator deaths, relationship stats, tech
  level, inventions, festivals, wildlife, and roads.

See `docs/DECISIONS.md`, "Batch: predator danger, relationship memory,
festivals, seasonal/weather scarcity."

## [0.20.1] — Fix: dev console not opening (stale browser cache)

### Fixed
- `/` now stamps `app.js`/`style.css` URLs with `?v=<version>` so a
  browser cache from before a UI change can't silently keep serving a
  stale build. Root cause of the reported "dev console doesn't open" —
  likely an old cached `app.js` with no dev-console handler.

## [0.20.0] — Improve: browser UI — readable events, clearer economy, dev console

### Added
- Developer console: `⚙ dev` header toggle shows raw per-tick
  diagnostics (tick duration, background/in-flight task counts,
  connected clients, LLM config) as JSON.
- Event log: per-category icons and color/emphasis (births, deaths,
  rumors, inventions, etc.); noisy `day_end` events suppressed from the
  rendered log (still queryable via `/events`).
- Wildlife (grazer/predator markers) and road wear now drawn on the
  canvas map, not just in stats.
- New stat tiles: Relationships (bonds/rivalries/avg affinity), Tech
  level, Wildlife, Roads, NPC dialogue counts. Materials/currency/
  granary/tech tiles gained `title` tooltips and capacity fractions
  instead of bare unlabeled numbers.
- New Inventions sidebar panel (mirrors Traditions).
- `Population.summary()`: `avg_affinity`/`close_bonds`/`rivalries`.
  `Settlement.summary()`: `materials_capacity`/`currency_capacity`/
  `granary_capacity`. `World`: `dialogue_total`/`rumor_total` counters.
  `WorldBroadcaster.client_count()`. Engine: `diagnostics` block in the
  per-tick broadcast payload.

See `docs/DECISIONS.md`, "UI pass."

## [0.19.0] — Add: Phase C slice 5 — infrastructure, foot-traffic roads (C5)

### Added
- `hearthmind/world/roads.py`: `RoadNetwork` tracks per-tile wear from
  sustained agent foot traffic (building/farm tiles excluded); an
  established road (wear >= 0.5) gives agents a 1.4x random-walk move
  bonus. Unused paths decay back to untouched terrain.
- `World.roads`, migration-backfilled for pre-C5 saves; included in the
  browser broadcast payload (not yet rendered by the static client).

This completes every system in the original feature list (terrain,
weather, seasons, ecology/wildlife, humans, relationships, economy,
agriculture, construction, infrastructure, building decay, culture,
history) — see `docs/ROADMAP.md`'s feature checklist.

See `docs/DECISIONS.md`, C5.

## [0.18.0] — Add: Phase A slice 4 — wildlife & ecology (A4)

### Added
- `hearthmind/world/wildlife.py`: mobile `AnimalHerd`s — `GRAZER` herds
  (grassland/forest, reproduce when uncrowded) and `PREDATOR` packs
  (forest/hills, hunt colocated grazers, starve without a kill). A real
  second trophic level with its own dynamics independent of agents.
- Hungry agents can hunt a colocated grazer herd for richer hunger relief
  than wild foraging — integrated into the existing forage priority
  chain (farm > granary > hunt > wild resource > emergency rations), no
  new `AgentGoal`.
- `World.wildlife`, migration-backfilled for pre-A4 saves.

See `docs/DECISIONS.md`, A4.

## [0.17.0] — Add: Phase E slice 3 — inventions, tech-tier unlocks (E3)

### Added
- `hearthmind/llm/invention.py`: rare, prosperity-gated tech-tier
  unlocks for a named settlement (LLM-authored with deterministic
  fallback) — `Settlement.tech_level`/`inventions`.
- Gated on surplus (currency or materials threshold) and an independent
  `INVENTION_CHANCE_PER_YEAR = 0.5` roll — deliberately rarer than
  traditions so it reads as a real event.
- `Population._tech_factor`: each invention boosts construction/repair
  work and cultivated-food yield (farm harvest, granary stock/withdraw)
  by `TECH_BONUS_PER_LEVEL` (0.15/level); wild foraging is untouched.

See `docs/DECISIONS.md`, E3.

## [0.16.0] — Add: Phase E slice 2 — NPC dialogue, rivalry, LLM on by default (E2)

### Added
- `hearthmind/llm/dialogue.py`: colocated agents periodically exchange an
  LLM-authored short dialogue (with deterministic fallback), scheduled
  fire-and-forget like cognition/chronicle/culture.
- `Population.due_for_dialogue`/`apply_dialogue`: deterministic,
  cooldown-gated, capped-per-tick pair selection; dialogue sentiment
  nudges relationship affinity.
- Dialogue lines and any seeded rumor are logged as `dialogue`/`rumor`
  events — automatically visible to the chronicle and culture prompts
  (both already read recent events), no extra wiring needed.

### Changed
- `Agent.relationships` now range -1..1 (was 0..1): a `tense` dialogue
  can push a pair into rivalry, not just toward friendship. Decay now
  pulls toward 0 from either sign.
- `Config.llm_enabled` defaults to `True` (was `False`); `server.py`'s
  flag inverted to `--llm-disabled`. Every LLM call still has a
  deterministic fallback if Ollama is unreachable.
- `llm_max_concurrent` default raised 2 -> 4.

See `docs/DECISIONS.md`, E2.

## [0.15.0] — Add: Phase F slice 2 — FastAPI backend + browser client (F2)

### Added
- Actual browser window into the simulation:
  `hearthmind/interface/static/` (plain HTML/CSS/JS, no build step) — a
  live canvas map (terrain + agents + buildings + farms), a stat-tile
  dashboard, traditions, and a scrolling event log.
- Backend switched from raw `websockets` to **FastAPI + uvicorn**:
  `GET /` (the page), `GET /state`, `GET /terrain`, `GET /events`, and
  `WS /ws` (live per-tick push).
- `requirements.txt` added, tracking the `api` extra
  (`fastapi`, `uvicorn[standard]`) alongside `pyproject.toml`.
- External libraries are now allowed project-wide (previously a scoped
  exception for `websockets` only) — tracked in `requirements.txt` going
  forward.

## [0.14.0] — Add: Phase F slice 1 — read-only WebSocket API (F1)

### Added
- `--api-enabled` (off by default), `--api-host`, `--api-port`:
  broadcast-only WebSocket channel pushing the world summary + this
  tick's life events after every tick. No intervention endpoints yet
  (deliberately last, per the roadmap).
- `websockets` added as an **optional** dependency (`pip install
  hearthmind[api]`) — the base install is still zero-dependency unless
  `--api-enabled` is actually used. See `docs/DECISIONS.md`, F1 for the
  reasoning (asked the user directly before bending the no-dependency
  rule).

## [0.13.0] — Add: Phase E slice 1 — settlement naming, traditions, culture-aware prompts (E1)

### Added
- Settlements are named (`settlement/naming.py`) the first tick a
  building stands, deterministically.
- Named settlements invent one new tradition per year
  (`hearthmind/llm/culture.py`), LLM-authored or deterministic fallback,
  persisted on `Settlement.traditions`.
- Settlement name + latest tradition now appear in per-agent cognition
  prompts and the seasonal chronicle prompt, closing the "chronicle isn't
  read back into prompts" gap noted since B3. `inspect_world` shows the
  settlement name in its header and lists established traditions.

## [0.12.0] — Add: farm-yield materials boost (D9); settlement currency (D10)

### Added
- Tooled farm plots: planting spends `FARM_TOOL_MATERIALS_COST` (2.0
  materials) for `FARM_TOOL_YIELD_MULTIPLIER` (1.5x) yield when materials
  are available. `FarmPlot` now carries its own `max_yield`.
- `Settlement.currency`: generated from food/materials surplus that would
  otherwise be wasted at capacity; spent on emergency rations at a
  standing granary as a last resort, once nothing free is available. No
  per-agent inventory/trade system — see `docs/DECISIONS.md`, D10 for why
  that's scoped out. `inspect_world` shows the currency balance.

## [0.11.0] — Add: production chains (D8)

### Added
- New `AgentGoal.GATHER`: collects wood/stone from forest/hills into a
  settlement-wide `materials` stockpile (`MATERIALS_CAPACITY` 30.0).
  Construction now consumes materials for a 2x speed boost
  (`CONSTRUCTION_MATERIALS_MULTIPLIER`) when available. LLM prompt and
  deterministic fallback both updated so GATHER is reachable with or
  without a live LLM. `inspect_world` shows the materials stockpile.

## [0.10.0] — Add: Granaries (D7)

### Added
- Dedicated `BuildingKind.GRANARY` (30% of new construction, vs. HUT).
  Well-fed agents present passively stock it (`GRANARY_CAPACITY` 15.0);
  hungry agents withdraw from it, priority farm > granary > wild forage.
  FORAGE/critical-hunger movement now also targets granaries (uncapped
  search, like farms/D6). `inspect_world` shows granary count + stored
  food.

## [0.9.0] — Fix: FORAGE never targeted farms (D6); qualitative wind

### Fixed
- 16 starvation deaths at tick 660 despite 27 harvest-ready farms — FORAGE
  movement only ever targeted wild resource nodes, never farms. Added
  `_nearest_ready_farm` (uncapped, like D4's SOCIALIZE), preferred over
  wild nodes. Verified: 0 starvation deaths over 6000 ticks, same config
  that previously produced 16 by tick 660.

### Changed
- `WeatherState.describe()` reports wind as calm/breezy/windy/gale
  (`wind_label()`) instead of a raw float.

## [0.8.0] — Fix: critical-hunger movement override (D5) + diagnostics

### Fixed
- **A critically hungry but *awake* agent could keep walking away from
  food.** `AgentGoal` is only reevaluated once per sim-day; an agent
  assigned SOCIALIZE or WANDER while well-fed had nothing making it
  deliberately seek food again before its next reevaluation, by which
  point hunger could have risen by ~0.96 (a full day at `HUNGER_RATE`).
  D3 only fixed the equivalent problem for a *resting* agent (emergency
  wake); this closes the same gap for movement dispatch generally.
  `Population.tick` now passes `critically_hungry` into
  `_dispatch_movement`, which forces FORAGE-seeking as an effective goal
  for movement purposes only — the agent's actual assigned `goal`/
  `goal_reason` (and hence what the UI/LLM sees) is unchanged. Found via
  a real soak run against live Ollama on the user's own machine (12 -> 5
  inhabitants, all dying before reaching maturity). See
  `docs/DECISIONS.md`, D5.

### Changed
- Default `--llm-timeout` raised from 10s to 20s — CPU inference sharing
  an 8GB+zram machine with the simulation itself is realistically slower
  under contention than a quiet benchmark; the same run that surfaced the
  bug above also logged one LLM timeout that correctly fell back, but
  with no headroom to spare.

### Added
- **Persisted diagnostics, surfaced by `inspect_world`:**
  - `World.llm_calls_total` / `llm_fallback_total` — cumulative LLM call
    count and how many fell back to deterministic behavior, shown as a
    fallback rate.
  - `Population.deaths_starvation` / `deaths_old_age` — cumulative death
    counts by cause, so a population crash between two snapshots is
    visible as a number instead of something you infer from "there used
    to be more agents."
  - `inspect_world --agents` now also shows each agent's `starving_ticks`
    and a maturity countdown, distinguishing "nothing has happened yet
    because nobody's mature" from an actual bug.

## [0.7.0] — Fix: social dispersion (D4) — the town finally forms

### Fixed
- **Root-caused and fixed the D2 finding** (farming let agents survive
  indefinitely alone, with reproduction/construction never occurring even
  with multiple mature, well-fed agents alive simultaneously). Two
  concrete bugs, not a deep balance problem:
  - `SOCIALIZE`'s target search shared `FORAGE`'s local radius
    (`GOAL_SEARCH_RADIUS`, 6 tiles) — far too small for a 64x64+ map.
    Once ordinary wander drift put two agents more than 6 tiles apart
    (which happens within a few hundred ticks), `SOCIALIZE` could never
    find them again — a one-way ratchet toward permanent isolation.
    Removed the distance cap for agent-seeking entirely (renamed the
    constant to `FORAGE_SEARCH_RADIUS`, now FORAGE-only).
  - `fallback_goal` (used whenever Ollama is disabled/unreachable) never
    returned `SOCIALIZE` at all — only forage/rest/wander. Every soak
    test in this project's history ran without Ollama, so this alone was
    enough to explain the total absence of clustering. Content agents now
    split deterministically by `agent_id` parity between SOCIALIZE and
    WANDER instead of always wandering.

### Verified
- Re-ran the *exact* 30-agent/48x48 configuration (seed 7) that produced
  D2's "three lonely survivors, zero reproduction, zero construction"
  result. With both fixes: **30+ births**, a building lifecycle
  (construction → completion → weathering → ruin) repeating across at
  least 8 distinct structures, and the first **old-age death** observed
  in any soak test in this project — sustained for 25,657 ticks (~3
  sim-years) with population fluctuating between ~10 and ~30 rather than
  trending to zero. This is the first time every subsystem built so far
  (terrain, weather, needs, foraging, farming, relationships,
  reproduction, settlement, aging) has been observed working together as
  a genuinely self-sustaining town, not just individually correct.
- 3 new/updated tests (`test_cognition.py`, `test_agents.py`) covering
  the parity split and the unbounded SOCIALIZE search. Full suite: 166
  tests, all passing.

See `docs/DECISIONS.md`, D4, for the full writeup.

## [0.6.1] — Fix: starvation trap found via live Ollama verification

### Fixed
- **Real bug, found on real hardware.** A maintainer's first live run
  against an actual Ollama instance (not the fake test server) showed
  population collapsing while `--agents` output revealed the LLM was
  correctly diagnosing hunger emergencies (`goal=forage`, reasons like
  "Need to find food before hunger reaches critical level") — but
  starving agents never acted on it, because `Population._maybe_forage`
  only ran while `AgentState.AWAKE`, and nothing could interrupt rest for
  a hunger emergency. An agent could wake, fail to reach food before
  energy drained back down, and re-sleep indefinitely while hunger
  climbed regardless of sleep state.
- Fixed with two coordinated changes gated on a new
  `CRITICAL_HUNGER_THRESHOLD` (0.9): agents can now forage/harvest food
  at their current tile while resting (not just awake), and a resting
  agent whose hunger crosses the critical threshold wakes immediately,
  with `goal=REST` no longer able to re-sleep them while still
  critically hungry.
- See `docs/DECISIONS.md`, D3, for the full incident writeup — this is
  the first bug this project found through actual multi-thousand-tick
  play with a real LLM rather than through unit tests, and a concrete
  example of why "tested against a fake server" and "verified" are
  different claims.

### Verified
- LLM integration is now confirmed genuinely working against real Ollama
  (previously only tested against a fake server standing in for it) —
  `goal_reason` text observed was contextual and weather-aware, not
  fallback boilerplate.
- 5 new regression tests (`tests/test_agents.py`,
  `TestStarvationTrapFix`) replicate the exact trap shape. Full suite:
  164 tests, all passing.

## [0.6.0] — Phase D (slice 1): Agriculture

### Added
- `hearthmind/economy/farms.py`: `FarmPlot`/`FarmGrid` — any single
  awake agent may plant a farm plot on an unclaimed grassland tile (no
  maturity/health/colocation requirement, unlike founding a building).
  Plots grow automatically over ~250 ticks with no tending needed, then
  yield substantially more food per harvest than wild foraging.
  `Population._maybe_forage` prefers a ready farm over a wild resource
  node whenever one's present at the agent's tile.
- Farm planting is logged as a `farm_planted` event.
- `World.summary()` / `inspect_world.py` now report farm counts
  (growing / ready to harvest).
- Generalized migration mechanism extended to the new `farms` subsystem.

### Verified (not just built)
Re-ran the exact soak configurations that produced total population
extinction in Phase C (see `docs/DECISIONS.md`, C5), now with farming:
- 6-agent/32x32 run (seed 42): 5 of 6 agents still died on essentially
  the same schedule as before farming existed, but the 6th survived to
  age 4082 — past `MATURITY_TICKS` (4000) — versus dying early in the
  pre-farming run. A direct, measured ~3x lifespan improvement.
- 30-agent/48x48 run (seed 7): **3 agents survived to age 27,035**
  (nearly 7x `MATURITY_TICKS`), run still going when testing ended —
  versus complete extinction in the equivalent pre-farming run.
- Farming is a verified fix for starvation-before-maturity, not a
  hoped-for one. See `docs/DECISIONS.md`, D2, for the full write-up.

### Known gaps / new finding (tracked for later phases)
- **No reproduction or construction occurred in either verification
  run**, including the 27,035-tick one with three simultaneously alive,
  well-fed, mature agents. They ended up scattered across the map with
  decayed relationships — farming lets an agent survive indefinitely
  *alone*, so nothing currently creates pressure to cluster. This is a
  distinct bottleneck from the one farming fixed; see `docs/DECISIONS.md`,
  D2, for a candidate next slice (bias settling/farming toward proximity
  to other agents).
- No storage/granaries (food is consumed immediately, not stockpiled),
  no production chains, no trade/currency — later Phase D territory.

## [0.5.0] — Phase C (slice 1): Settlements & construction

### Added
- `hearthmind/settlement/buildings.py`: `Building` (under_construction /
  standing / ruined lifecycle) and `Settlement` (the collection of
  buildings in the world, parallel to `Population`/`ResourceGrid`).
- Colocated, mature, healthy agent pairs may found a building at their
  shared tile (deterministic per-tick chance, mirroring A3's reproduction
  mechanic — not yet an LLM/goal decision, see `docs/DECISIONS.md` C1).
- Any awake agent physically present at a building's tile contributes
  work each tick: advancing construction toward completion, or repairing
  a standing building below `REPAIR_THRESHOLD` — automatic based on
  presence, the same way foraging already works, not a separate explicit
  action (see C2).
- Standing buildings decay every tick (faster during harsh weather —
  precipitation, wind, snow) into ruins; ruins persist, inspectable, for
  a long while before nature finishes reclaiming them and they're removed
  from the world (see C3).
- Worlds start with an empty settlement — nothing is pre-placed; whether
  a world becomes settled at all emerges entirely from population
  behavior (see C4).
- Construction/repair/ruin/reclamation are logged as events
  (`construction_started`, `building_completed`, `building_ruined`,
  `building_reclaimed`).
- `World.summary()` / `inspect_world.py` now report settlement counts
  (under construction / standing / ruined) and average condition.
- Generalized migration mechanism extended to the new `settlement`
  subsystem — a pre-Phase-C save backfills an empty `Settlement()` the
  same way `population`/`resources` were backfilled before it.

### Tested
- 23 new tests (21 in `tests/test_settlement.py` plus 2 migration tests
  in `test_persistence.py`/`test_engine.py`) covering construction
  eligibility, presence-driven work, weathering (including a harsh-vs-
  clear-weather comparison), ruin/reclamation timing, and serialization
  round-trips. Full suite: 134 tests, all passing.
- Full CLI release checklist per `docs/TESTING.md`: fresh-world smoke
  test, resume test, and a migration test (settlement backfill on a
  pre-Phase-C save), all passing.
- **Honesty note:** two long soak attempts (~8,600 and ~17,000 ticks,
  6 and 30 initial agents respectively) specifically trying to observe
  organic construction through unassisted play did not succeed — every
  agent died of starvation before reaching `MATURITY_TICKS` in both
  runs. The construction/repair/weathering/reclamation mechanism itself
  is directly unit-tested and the integration/persistence path is CLI-
  verified, but a completed building has not personally been witnessed
  through organic play in this session. See `docs/DECISIONS.md`, C5, for
  the full finding and what it implies for Phase D.

### Known gaps (intentional, tracked for later phases)
- Building placement is pure chance (gated by eligibility), not yet
  influenced by `AgentGoal` or LLM cognition — the natural next slice.
- No roads, no building types/variety, no resource cost for construction
  beyond agent time — that's Phase D (agriculture/economy) territory.
- Populations tend toward starvation before reaching the maturity
  threshold needed to found a settlement under current tuning (see C5) —
  not fixed in this release; flagged as a real balance question for
  Phase D or a dedicated tuning pass.

## [0.4.0] — Phase B (slice 1): LLM cognition layer (Ollama)

### Added
- `hearthmind/llm/`: a stdlib-only (`urllib`) Ollama client
  (`client.py`), a bounded-concurrency async job runner with mandatory
  timeout + deterministic fallback (`jobs.py`), per-agent goal
  prompt/parse/fallback logic (`cognition.py`), and seasonal chronicle
  summarization (`chronicle.py`). Off by default (`Config.llm_enabled`,
  `--llm-enabled`).
- Agents now have a `goal` (wander/forage/socialize/rest), re-evaluated
  once per sim-day (staggered across the day), that biases movement:
  FORAGE/SOCIALIZE move toward the nearest visible resource node/agent,
  REST proactively pauses activity, WANDER is the unchanged pre-Phase-B
  behavior. Goal decisions come from the LLM when enabled, or a
  deterministic hunger/energy rule when not — the simulation is
  unaffected either way beyond richer/simpler goal choices.
- A seasonal `chronicle` event (LLM-authored prose, or a deterministic
  templated count-based summary as fallback) is logged on every
  `season_end`, reusing the existing `events` table.
- All LLM-backed work is scheduled and collected entirely inside
  `SimulationEngine` as fire-and-forget background tasks — `World.tick()`
  stays fully synchronous and unaware the LLM exists, preserving the
  Milestone-1 invariant that the engine is the only thing that mutates
  the World and never blocks the tick loop.
- `inspect_world.py --agents`: lists each inhabitant's position, state,
  goal, goal reason, needs, and age — the first way to inspect individual
  agents rather than only population aggregates.
- CLI flags: `--llm-enabled`, `--llm-host`, `--llm-model`,
  `--llm-timeout`, `--llm-max-concurrent`.

### Tested
- LLM-facing code tested against a fake local HTTP server
  (`tests/_llm_fake_server.py`) covering success, malformed JSON,
  non-200 status, connection-refused, and timeout paths, plus an
  engine-level end-to-end test proving a fake server's response actually
  reaches an agent's `goal`/`goal_reason`.
- **Not yet verified against a real Ollama installation** — no Ollama
  available in the environment this was built in. See README's "LLM
  cognition layer" section and `docs/TESTING.md` section 6b for the
  checklist to run before trusting this in production.

### Known gaps (intentional, tracked for later phases)
- No priority distinction between cognition and background-enrichment
  job types yet — a single bounded semaphore is enough at current scale.
- The chronicle isn't read back into agent cognition prompts yet (no
  long-term LLM memory loop) — planned once Phase E (culture) needs it.
- Only four fixed goals; no free-form reasoning or richer triggers beyond
  the daily cadence.

## [0.3.0] — Phase A: Foraging, lifecycle, relationships and birth

### Added
- `hearthmind/world/resources.py`: discrete, depletable `ResourceNode`s
  scattered on forageable terrain (forest/grassland/hills) at world
  creation, regenerating slowly (~500 ticks from empty to full). Closes
  the M2-2 gap — hungry agents now forage nearby nodes instead of hunger
  only ever rising.
- Agents now age (`age_ticks`) and carry a per-agent lifespan
  (`max_age_ticks`, randomized at spawn) — dying of old age when reached.
- Starvation death: sustained (200+ consecutive ticks) high hunger with no
  food available kills an agent; a single bad tick does not.
- Lightweight relationships: agents build affinity with others they're
  colocated with, decaying otherwise. Mature, healthy, sufficiently
  affinitied pairs can reproduce (small per-tick chance), producing a new
  agent with recorded parent lineage — gated by a hard population cap
  (200) as a safety valve.
- Births and deaths are logged as `birth`/`death` events, visible via
  `inspect_world`'s recent-events list.
- `World.summary()` / `inspect_world.py` now also report resource-node
  counts/fullness and average population age.
- The pre-Milestone-2 snapshot-migration mechanism (M2-3) is generalized:
  `migrated_population: bool` became `migrated_subsystems: list[str]`, so
  the new `resources` subsystem (and any future one) is backfilled on
  load the same way, without a bespoke branch per field.
- `docs/ROADMAP.md`: the long-term phased plan (Phase A through Phase G).
- `docs/TESTING.md`: the release-testing checklist (unit tests + real CLI
  smoke tests for fresh-world, resume, and migration paths).

### Known gaps (intentional, tracked for later phases)
- No LLM involvement yet — reproduction/relationships are a deliberately
  cheap deterministic placeholder Phase B's cognition layer will build on
  top of, not replace outright.
- No settlements, buildings, or agriculture yet — foraging is still the
  only food source (Phase C/D).
- The population cap (200) is a blunt safety valve, not an emergent limit;
  Phase D's economy should make it unreachable in practice.

## [0.2.0] — Milestone 2 (slice 1): Agents — population, needs, movement

### Added
- `hearthmind/agents/` package: `Agent` (position + hunger/energy needs +
  awake/resting state), `Population` (spawns and ticks a collection of
  agents), and a small deterministic name generator.
- Agents spawn on walkable terrain (grassland, forest, hills, beach) when a
  world is first created; count is controlled by `Config.initial_population`
  / `--initial-population` (default 12, creation-only).
- Agents' needs decay deterministically each tick (seeded by
  `(world_seed, tick)`, same discipline as weather): hunger always rises;
  energy drains while awake and recovers while resting. Awake agents
  occasionally wander to an adjacent walkable tile; low energy triggers
  resting, which pauses movement until energy recovers.
- `World.summary()` and `inspect_world.py` now report population counts and
  average hunger/energy.
- Loading a pre-0.2.0 snapshot (no population yet) now spawns an initial
  population on load, logs a `population_migration` event, and persists a
  snapshot immediately — existing saves keep working (see
  `docs/DECISIONS.md`, M2-3).
- `pyproject.toml` added: real package metadata, console-script entry points
  (`hearthmind-server`, `hearthmind-inspect`), and a `dependencies` list
  ready for Milestone 3's Ollama client.
- This changelog.

### Known gaps (intentional, tracked for the next slice)
- No food source or consumption — hunger only ever rises. There is no death
  or starvation mechanic yet; that arrives with foraging/agriculture.
- No inter-agent interaction, relationships, or social behavior yet — agents
  currently wander independently.
- Snapshots remain full-JSON (not incremental); adding ~a dozen agents does
  not yet make this a problem, but it is the same scaling concern flagged in
  M1-4 and will need addressing before population/building counts grow much
  further.

## [0.1.0] — Milestone 1: Core sim loop + persistence

Retroactive entry for the pre-changelog baseline.

### Added
- Deterministic terrain generation (diamond-square elevation + biome
  classification), seeded and reproducible.
- `SimClock`: tick-count-driven calendar (minute/day/season/year), no
  wall-clock dependency.
- Deterministic, seasonally-aware weather derived per-tick from
  `(seed, tick)`, smoothed against the previous tick for continuity.
- SQLite persistence: `world_meta`, append-only `snapshots`, append-only
  `events`; WAL mode for concurrent reads.
- `SimulationEngine`: async tick loop, graceful start/stop/resume via
  SIGINT/SIGTERM, periodic + final snapshotting.
- `server.py` CLI entrypoint and `inspect_world.py` read-only inspector.
- Sim time does not fast-forward while the server is off (see
  `docs/DECISIONS.md`, M1-1) — a deliberate, revisitable Milestone-1 choice.
- Zero external dependencies (stdlib only).
