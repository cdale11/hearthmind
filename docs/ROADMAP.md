# Roadmap

This is the long-term plan for Hearthmind, organized into phases rather than
strict version numbers (see `CHANGELOG.md` for what's actually shipped).

**Emergence is the primary objective.** Every system below exists to produce
behavior nobody scripted — a famine that reshapes settlement culture, a
building that decays into a landmark, a tradition born from a specific
agent's death. Systems are judged by what they let *emerge* from their
interaction, not by how complete they are in isolation.

## Feature checklist (original scope)

The full feature set discussed at project inception, and where each one
currently lives. This is the map back to "did we build what we said we'd
build" — phases below are the *how*, this table is the *what*.

| Feature | Status | Where |
|---|---|---|
| Terrain | shipped | `world/terrain.py` (generation, Milestone 1) + `world/terrain_evolution.py` (local activity-driven change and climate/biome drift) |
| Weather | shipped | `world/weather.py`; UK-climate monthly baselines, qualitative labels since D6 |
| Seasons | shipped | `time_system.py`: real 365-day/12-month calendar, `season` derived per-month (UK meteorological); `year_end`/`season_end`/`month_end`/`week_end` drive culture/chronicle/terrain-evolution cadence |
| Ecology & wildlife | shipped | A4 (`hearthmind/world/wildlife.py`) — grazer herds flee predators, predator packs hunt (now a logged event), huntable |
| Humans (agents, needs, aging) | shipped | Phase A |
| Relationships | shipped | A3 (proximity affinity + birth) + E2 (rivalry, -1..1) + A5 (memory of specific bond/rivalry/rumor/grief moments, fed into cognition) |
| Economy | shipped (settlement-scale) | Phase D (D8-D10: materials, currency) + workshops/schools/hospitals/universities (currency income, education->invention chance, health) + a seasonal LLM "town brain" civic-priority decision that steers what gets built; real seasonal/weather scarcity pressure so decline is genuinely possible; no per-agent trade — see Phase D open item |
| Agriculture | shipped | D1, D9 (farms, tool-boosted yield) |
| Construction | shipped | Phase C + economy buildings (workshop/school/hospital/university/factory) + a starting-`industrial`, tech-level-driven era progression (industrial -> electrical -> modern -> digital) |
| Infrastructure | shipped | C5 (`hearthmind/world/roads.py`) — foot-traffic-driven path wear/decay, established roads speed movement, now weather-dependent (mud/snow/ice); human-readable condition telemetry (`Settlement.infrastructure_report`) |
| Building decay | shipped | C1-C4 (weathering, ruin, reclamation) |
| Culture | shipped (single-settlement) | E1 (naming, traditions) + E3 (prosperity-gated inventions/tech unlocks) + festivals + generational/family memory; multiple named settlements not built |
| History | partial | B3 (chronicle) + E1 (traditions feed prompts); no replay/browsable history view (Phase F) |
| Optional subtle supernatural elements | shipped | Phase G — `Settlement.temperament` (deterministic mood-like drift, subtle mechanical nudges) + `llm/omens.py` (rare, never-confirmed ambient events, optionally person-specific) + `Config.phase_g_intensity` (tunable, 0.0 = off) |

Two design principles drive the phase ordering below:

1. **The LLM is expensive and slow relative to a tick.** It cannot run
   per-agent-per-tick on modest hardware. The architecture separates
   deterministic, cheap, every-tick simulation (physics, needs, movement,
   decay) from sparse, LLM-driven, high-level decisions (goals,
   relationships, culture) made periodically and then executed by the
   deterministic layer over many subsequent ticks. This split needs to
   exist *before* the LLM is wired in, which is why LLM infrastructure
   (Phase B) comes earlier than "add the LLM once everything else exists."
2. **Idle-CPU utilization is an architectural constraint, not a feature.**
   A background job-queue/worker-pool model (tick-critical work vs.
   enrichment work) needs to exist before LLM cognition and
   history-generation land, or they'll either starve the tick loop or
   leave cores idle. Phase B builds this once, and every later phase that
   wants LLM involvement is just another consumer of that queue.

## Phase A — Close the deterministic substrate

Finishes what Milestone 2 slice 1 (agent needs/movement) opened.

- **[x] A1. Foraging & food economy.** Discrete, depletable resource
  nodes scattered across forageable terrain; hungry agents forage them;
  nodes regenerate slowly. Closes the M2-2 gap where hunger only ever
  rose. **Extended (resource-variety pass):** nodes now have a `kind`
  (FOOD/"bush" vs. ORE/"mine") — hills-only ore veins regenerate 12x
  slower than food and feed GATHER-goal materials collection
  specifically (forest wood stays uncapped). See `docs/DECISIONS.md`,
  "Diagnostics, browser-default, resource variety, real building cost."
- **A2. Aging, starvation death, old-age death.** Agents track age and a
  per-agent lifespan; sustained starvation or old age removes them from
  the population.
- **A3. Lightweight relationships & birth.** Proximity-based affinity
  between agents; mature, healthy, sufficiently-affinitied pairs can
  reproduce, gated by a hard population cap as a safety valve. This is
  deliberately *not* LLM-driven — it's cheap, deterministic scaffolding
  that gives the Phase B LLM something real to reason about later.
- **[x] A4. Ecology & wildlife.** Mobile `AnimalHerd`s
  (`hearthmind/world/wildlife.py`): grazer herds (grassland/forest,
  reproduce when uncrowded) and predator packs (forest/hills, hunt
  colocated grazers, starve without a kill) — a real second trophic
  level with its own dynamics independent of agents. Hungry agents can
  hunt a colocated grazer herd for richer relief than wild foraging,
  slotted into the existing forage priority chain. See
  `docs/DECISIONS.md`, A4.
- **[x] Agent-vs-predator danger.** Colocated agents can be attacked
  (injury, rarely lethal) by live predator packs; movement now prefers
  avoiding predator-occupied tiles. See `docs/DECISIONS.md`, "Batch:
  predator danger...".
- **[x] Deliberate hunting.** Corrected from an earlier "not yet built"
  note: FORAGE's target-seeking chain already walks a hungry agent
  toward a known grazer herd (`Population._nearest_grazer_herd`), not
  just opportunistic consumption when already colocated — the same
  shape as farms/granaries, so a dedicated `AgentGoal.HUNT` would only
  have duplicated existing targeting/consumption logic. A real gap did
  remain: herds didn't compete with agents for `ResourceGrid` food.
  Closed — a grazer herd colocated with a wild FOOD node now consumes a
  small amount of it each tick and skips reproduction on an overgrazed
  tile (`GRAZE_CONSUMPTION_PER_TICK`/`GRAZE_REPRODUCE_MIN_FOOD`, world/
  wildlife.py). See docs/DECISIONS.md, "everything left" pass.
- **[x] A5. Deeper relationships.** A3 shipped birth-gating affinity; E2
  added dialogue-driven rivalry (-1..1); a later batch added
  `Agent.memories` (bond/rivalry formation, rumors, grief with a real
  energy cost on a bonded partner's death) fed back into the agent's own
  cognition prompt. Rivalry-driven behavior closed this batch: a rival's
  tile is folded into the same prefer-avoid set predator tiles already
  use in movement (`Population._dispatch_movement`), not just a lower
  affinity number. See `docs/DECISIONS.md`, "Batch: predator danger..."
  and "everything left" pass.

## Phase B — LLM infrastructure (the foundation, not a feature)

- **[x] B1. Ollama client + job architecture (slice 1 shipped).** A
  stdlib-only (`urllib`) blocking client wrapped in an async, bounded-
  concurrency `CognitionRunner` (`hearthmind/llm/`) — this is the
  BOINC-style idle-CPU lever described in the project brief: Ollama's own
  thread pool does inference, and `llm_max_concurrent` controls how many
  requests are in flight to keep it busy. Every call has a timeout and a
  deterministic fallback and never raises into the tick loop. Tested
  against a fake local server; **not yet verified against a real Ollama
  install** — see README. Not yet built: a true priority queue
  distinguishing cognition vs. background-enrichment work — at current
  scale (single population, no chronicle backlog) a flat semaphore was
  enough; revisit once Phase C/D add more LLM-consuming subsystems.
- **[x] B2. Sparse agent cognition (slice 1 shipped).** Agents get one of
  four fixed goals (wander/forage/socialize/rest) once per sim-day,
  staggered across the day, executed deterministically by `Population`'s
  movement logic every tick until re-evaluated. Decision-first, not
  dialogue-first, per the plan above. **Event triggers beyond the daily
  cadence: shipped.** A hunger emergency or fresh grief now schedules an
  immediate re-reasoning (`Population.due_for_triggered_cognition`, a
  per-agent cooldown so a sustained crisis doesn't hammer the LLM every
  tick) rather than waiting for the next staggered daily slot — see
  docs/DECISIONS.md, "everything left" pass. Stranger-arrival triggers
  and goals richer than the current four remain open.
- **[x] B3. World chronicle / narrator (slice 1 shipped).** Seasonal LLM
  summarization of recent events into the existing `events` table
  (category `chronicle`). This is early long-term memory content, not
  yet read back into later prompts (B2's agent cognition doesn't consult
  it) — that's the natural next slice once culture (Phase E) needs it.

## Phase C — Settlements & construction

- **[x] C1-C4. Buildings, construction, weathering, repair, reclamation
  (slice 1 shipped).** Colocated, mature, healthy agents may found a
  building (deterministic in this slice, mirroring A3's reproduction
  mechanic — not yet an LLM/goal decision, see `docs/DECISIONS.md` C1);
  any awake agent present advances construction or repairs a damaged
  standing building; weather-driven decay turns neglected buildings into
  ruins; long-abandoned ruins are eventually reclaimed and removed. This
  is where "prosper, stagnate, or disappear" becomes visible at the
  settlement level, not just per-agent.
- **[x] C5. Infrastructure.** `hearthmind/world/roads.py`'s
  `RoadNetwork`: walkable, building/farm-free tiles wear from sustained
  agent presence and decay when abandoned, mirroring C1-C4's
  construction/decay shape rather than being planned/pathfound. An
  established road (wear >= 0.5) gives agents a 1.4x random-walk move
  bonus. See `docs/DECISIONS.md`, C5.
- **[x] Resource cost for construction.** Founding a building now costs
  real materials (`HUT_MATERIALS_COST`/`GRANARY_MATERIALS_COST`),
  deducted upfront — a settlement with an empty stockpile can no longer
  spontaneously build. See `docs/DECISIONS.md`, "buildings-need-
  resources pass."
- Building types beyond the generic hut/granary shipped separately
  (workshop/school/hospital/university/factory, Phase D/E). **Tying
  civic-priority cognition into *whether* to build: shipped** — the
  town brain's current priority now also scales the settle-chance roll
  itself (`SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER`/`_OFF_PRIORITY_
  MULTIPLIER`, `Population._maybe_start_construction`), not just which
  kind gets founded. *Where* to build remains pure-chance (wherever 2+
  eligible agents happen to be colocated) — a genuinely separate,
  larger change (agent-driven pathing toward a chosen site) not
  attempted. See docs/DECISIONS.md, "everything left" pass.
- **[x] Vehicles.** `hearthmind/settlement/vehicles.py`: hauling carts
  (settlement-wide, boost gathered-material yield) and personal-travel
  mounts (an agent claims one, moves faster), built/repaired/decayed the
  same way buildings are. See `docs/DECISIONS.md`, "Vehicles: hauling
  carts and personal-travel mounts."

## Phase D — Agriculture & economy

- **[x] D1. Farming (slice 1 shipped).** Any awake agent can plant a
  farm plot on grassland; it grows automatically over time and yields
  substantially more food than wild foraging once ready — `Population`
  prefers a ready farm over wild forage whenever one's available.
- **[x] D2/D4: social dispersion found and fixed.** D2 found that farming
  let agents survive indefinitely alone, with no pressure to cluster.
  Root-caused to two concrete bugs, not a deep design gap: SOCIALIZE's
  target search shared FORAGE's local radius (too small for the map, and
  once agents drifted apart there was no way back), and the deterministic
  fallback (used whenever Ollama is off) never chose SOCIALIZE at all.
  Both fixed in D4. **Verified with the exact 30-agent/48x48 run that
  previously produced zero clustering:** the same config now produces a
  self-sustaining, multi-generational population — 30+ births, a
  repeating building lifecycle across 8+ structures, and the first
  old-age death observed in any soak test, sustained for ~3 sim-years.
  See `docs/DECISIONS.md`, D2/D4.
- **[x] D3: starvation trap found via live Ollama play, fixed.** The
  first real run against live Ollama (not a fake test server) surfaced a
  bug where a correctly LLM-assigned FORAGE goal was never executed
  because resting blocked all foraging, with nothing able to interrupt
  rest for a hunger emergency. Fixed with a critical-hunger emergency-wake
  mechanism. See `docs/DECISIONS.md`, D3.
- **[x] D5: a second live-play soak run surfaced a related gap and fixed
  it, plus added diagnostics.** A critically hungry but *awake* agent
  whose assigned goal was SOCIALIZE/WANDER had nothing making it
  deliberately seek food until its next once-per-day goal reevaluation —
  D3 only fixed the resting case. Fixed with the same critical-hunger
  override, applied to movement dispatch generally. Also: raised the
  default LLM timeout for 8GB+zram headroom, and added persisted
  diagnostics (`inspect_world` now shows cumulative LLM
  calls/fallback-rate, cumulative deaths by cause, and per-agent
  starving-ticks/maturity countdown) so a population crash or a flaky
  Ollama instance is visible from a snapshot alone. See
  `docs/DECISIONS.md`, D5.
- **[x] D6/D7: FORAGE now targets farms; granaries added.** D6 fixed
  FORAGE never targeting farms (root cause of a 16-death cascade). D7
  added `BuildingKind.GRANARY` — presence-driven stock/withdraw, a
  community food buffer. See `docs/DECISIONS.md`, D6/D7.
- **[x] D8: production chains, slice 1.** New `AgentGoal.GATHER` feeds a
  settlement-wide materials stockpile; construction consumes it for a 2x
  speed boost. See `docs/DECISIONS.md`, D8.
- **[x] D9: farm-yield boost from materials.** Tooled plots (materials
  spent at planting) yield 1.5x. See `docs/DECISIONS.md`, D9.
- **[x] D10: settlement currency.** Generated from food/materials surplus
  at capacity, spent on emergency rations as a last resort. Deliberately
  settlement-wide, not per-agent — no inventory system exists to support
  literal barter; see `docs/DECISIONS.md`, D10 for the scoping rationale.
  **Phase D is now feature-complete per the original roadmap scope.**
- Open for a future round: per-agent inventory/trade (would let D10's
  currency become genuine peer-to-peer barter), tying `AgentGoal`/LLM
  cognition into economic decisions now that an economy exists.

## Phase E — Culture & history

Named traditions, festivals, generational memory, settlement names and
lore — mostly an extension of B3 (chronicle) plus new LLM prompt
templates that read the chronicle back as context. Where the world
starts producing content that surprises its creator.

- **[x] E1: culture, slice 1.** Settlements are named once a building
  stands; named settlements invent one tradition per year
  (`hearthmind/llm/culture.py`); settlement name + latest tradition now
  appear in per-agent cognition prompts and the chronicle prompt, closing
  the B3 "chronicle isn't read back into prompts" gap. See
  `docs/DECISIONS.md`, E1.
- **[x] E2: NPC-to-NPC dialogue, relationships extended to rivalry, LLM
  on by default.** Colocated agents periodically exchange an
  LLM-authored dialogue line (`hearthmind/llm/dialogue.py`); sentiment
  nudges relationship affinity, and any seeded rumor is logged as a
  normal event, so it's automatically visible to the chronicle/culture
  prompts without new wiring — a private exchange between two agents can
  ripple into settlement-level culture. `Agent.relationships` now range
  -1..1 (was 0..1) to represent rivalry, not just friendship. LLM is now
  on by default (`Config.llm_enabled = True`) with the user's local
  hardware confirmed not budget-constrained. See `docs/DECISIONS.md`, E2.
- **[x] E3: Inventions, tech-tier unlocks.** Rare, prosperity-gated
  (`hearthmind/llm/invention.py`): a named, surplus-rich settlement may
  invent something once a year (independent 50% roll, deliberately rarer
  than traditions). Each invention raises `Settlement.tech_level`,
  boosting construction/repair speed and cultivated-food yield
  (farm/granary) by 15% per level — wild foraging untouched. See
  `docs/DECISIONS.md`, E3.
- **[x] Festivals.** A wellbeing-gated (not prosperity-gated), seasonal-
  cadence collective event (`hearthmind/llm/festival.py`) with a direct
  mechanical effect: every currently-colocated pair of awake agents gets
  a relationship boost when one is held. Distinct from traditions
  (yearly, prosperity-agnostic, narrative-only). See
  `docs/DECISIONS.md`, "Batch: predator danger...".
- **[x] Generational/family memory.** A newborn remembers both parents
  from birth, parents remember the birth; losing a parent/child logs a
  family-specific memory and pays grief regardless of numeric
  relationship value (a newborn's affinity toward its own parent may
  not have accrued much yet). NPC dialogue prompts recognize a parent/
  child pair as family. See `docs/DECISIONS.md`, "Interventions, family
  memory, and smooth/lit rendering."
- Not yet built: multiple named settlements, culture-specific building
  types.

## Phase F — Browser interface

Deliberately late. Everything through Phase E is server-only and
testable via `inspect_world`. Once there's a rich world to look at,
build: a read-only HTTP/WebSocket API in front of the engine (the engine
never blocks on it, per the Milestone 1 architecture), map view,
telemetry/diagnostics, inhabitant/location inspection, conversation/event
history, and — last — sparse intervention tools (the "nudge" mechanic).
The engine-owns-time invariant makes this safe to build without risk to
the simulation.

- **[x] F1: read-only WebSocket API, slice 1.** `--api-enabled` broadcasts
  the world summary + life events after every tick, fire-and-forget, same
  liveness guarantee as the LLM layer. See `docs/DECISIONS.md`, F1.
- **[x] F2: FastAPI backend + actual browser client, slice 2.** External
  libraries are now allowed project-wide (user-confirmed), tracked in
  `requirements.txt`. Backend switched to FastAPI + uvicorn (`GET /`,
  `/state`, `/terrain`, `/events`, `WS /ws`). A real static browser page
  (plain HTML/CSS/JS, no build step) renders a live canvas map, stat
  dashboard, traditions, and event log. See `docs/DECISIONS.md`, F2.
- **[x] UI pass: human-readable events, materials/currency clarity, dev
  console.** Event log gained per-category icons/color, noisy `day_end`
  suppressed; stat tiles gained tooltips/capacities and coverage for
  every system shipped this session (relationships, tech level,
  wildlife, roads, dialogue); wildlife and road wear are now drawn on
  the map; a `⚙ dev` toggle exposes raw engine telemetry (tick timing,
  task counts, connected clients). See `docs/DECISIONS.md`, "UI pass."
- **[x] Smooth movement + day/night lighting.** Agent dots interpolate
  between grid positions over `AGENT_ANIM_DURATION_MS` instead of
  snapping once per tick; a day/night + weather lighting tint darkens
  the map at night and under heavy precipitation. See
  `docs/DECISIONS.md`, "Interventions, family memory, and smooth/lit
  rendering."
- **[x] Intervention ("nudge") endpoints.** `POST /intervene/agent-goal`,
  `/intervene/settlement`, `/intervene/weather`, and (LLM-as-brain
  batch) `/intervene/town-brain` — queued via
  `WorldBroadcaster.enqueue_intervention` and applied synchronously by
  the engine at the top of its next tick, the same seam as pending
  cognition/dialogue results, so `World` is still only ever mutated
  from the tick loop. `/intervene/town-brain` is deliberately subtle: a
  text whisper folded into the LLM brain's next civic-priority prompt,
  not a command. See `docs/DECISIONS.md`, same entry and "LLM-as-brain
  batch."
- **[x] Fix: live event stream gap.** Dialogue/chronicle/tradition/
  invention/festival/intervention/town-brain events resolve outside
  `World.tick()` and were only ever written to the DB directly, never
  reaching the live WebSocket feed (only the one-shot `/events` fetch
  on page load saw them). Fixed with `SimulationEngine._log`. See
  `docs/DECISIONS.md`, "LLM-as-brain batch."
- **[x] Infrastructure telemetry panel.** Every building/vehicle's
  condition in plain language, worst-first — `Settlement.infrastructure_report()`,
  a new sidebar panel, and an `inspect_world` section. See
  `docs/DECISIONS.md`, "LLM-as-brain batch."
- **[x] Real 365-day/12-month calendar + UK climate.** Replaces the old
  fixed 20-day/4-season year; weather baselines are monthly and
  UK-maritime-flavored; terrain evolution recadenced onto fixed weekly/
  monthly ticks (was season/year-boundary-triggered) so the longer
  calendar doesn't make map evolution rarer to observe. See
  `docs/DECISIONS.md`, "Real-calendar/genesis-seed follow-up."
- **[x] Eras.** A settlement starts `industrial` and advances
  (electrical -> modern -> digital) with `tech_level`, unlocking the
  FACTORY building kind past `industrial`. See same entry.
- **[x] LLM-chosen world-genesis seed.** `llm/world_genesis.py` — a
  one-time LLM call picks a founding-scenario sentence whose hash
  becomes a brand-new world's seed when `--seed` is omitted. See same
  entry.
- **[x] World beliefs (continuous cognition).** `llm/beliefs.py` +
  `Settlement.beliefs` — the village's own persistent, LLM-formed-and-
  revised theories about itself, fed back into town-brain/chronicle
  prompts. See `docs/DECISIONS.md`, "World-model/beliefs follow-up."
- **[x] Per-person beliefs.** `beliefs.resolve_subject_agent_id` matches
  a belief's free-text subject against current agent names and tags
  `subject_agent_id`; matched beliefs are folded into that person's
  dialogue prompts (`llm/dialogue.py`'s `beliefs_about`). See
  `docs/DECISIONS.md`, "Phase G / per-person beliefs follow-up."
- **[x] Per-agent click-to-inspect.** Clicking an agent on the map opens
  a mind-first NPC inspector (goal/reason, beliefs about them, named
  relationships, recent memories, vitals last) — see docs/DECISIONS.md,
  Observatory UI pass.
- **[x] Historical/replay view, v1.** The curated History tab (`GET
  /history`) plus a new yearly "documentary mode" LLM job
  (`llm/documentary.py`, gated on `year_end`) narrating the year's
  curated milestones — not a scrub-through-time replay, but a real
  narrated look-back using actual simulation history. See
  docs/DECISIONS.md, Observatory UI pass.
- Not yet built: structured per-family belief resolution (family-
  labeled beliefs remain free text, not resolved to a lineage entity),
  a true scrub-through-time replay view.

## Phase G — Supernatural / psychological horror layer

Was "explicitly last," started early per explicit user instruction
(running in parallel with other work rather than after it) — still
explicitly subtle. **v1 shipped:** `Settlement.temperament`
(`settlement/buildings.py`) is a real, deterministic bounded random walk
nudged monthly by the recent balance of good/ill fortune, applying
small nudges to invention chance and predator-attack lethality; `llm/
omens.py` is a rare, LLM-authored (or fallback-pool) ambiguous flavor
event scaled by |temperament|, worded to always have a mundane
explanation and never confirm anything. See `docs/DECISIONS.md`,
"Phase G / per-person beliefs follow-up."

**[x] Intensity knob.** `Config.phase_g_intensity` (default 1.0) scales
both temperament's monthly step and omens' per-month chance; 0.0 holds
temperament flat and skips omens outright — a fully off switch without
deleting the mechanism.

**[x] Deeper narrative payoff.** About half the time an omen fires, if
a belief already resolves to a still-living agent, the omen now centers
on that specific person (`llm/omens.py`'s `subject_name` param) instead
of the settlement in the abstract — still never confirming anything,
just less anonymous. See docs/DECISIONS.md, "everything left" pass.

**[x] v3: temperament's mechanical reach extended, omen memory.** Two
more small, warm-only nudges — migrant-arrival chance
(`MIGRANT_TEMPERAMENT_INFLUENCE`) and wildlife-recolonization chance
(`WILDLIFE_TEMPERAMENT_INFLUENCE`), same ~0.2 fractional magnitude as
the original invention/predator nudges, both deliberately one-sided
since each is already the sole recovery path for its own near-
extinction scenario. New `Settlement.omen_history` (capped rolling
log) gives omens continuity — a new sighting can occasionally echo one
noticed before, offered to the LLM as optional texture, never forced.
See docs/DECISIONS.md, "Phase G v3" pass.

Still not built (deliberately): any player-facing acknowledgment that
this system exists (see CLAUDE.md).

### Related: trust and "the town's opinion of the player"

Two adjacent, previously-flagged gaps, closed alongside Phase G:

- **[x] Trust lever.** `Agent.trust` (-1..1 per source agent id) is a
  distinct axis from `relationships` (fondness) — how much credibility
  an agent gives another's word. Nudged on dialogue (`TRUST_DELTA`,
  asymmetric — easier to lose than earn); consumed when a rumor
  arrives: below `TRUST_SKEPTICISM_THRESHOLD`, the receiving agent
  remembers it with visible skepticism instead of at face value, which
  then reaches that agent's own future cognition prompts. The discrete
  "who does an agent believe more readily, or discount" lever CLAUDE.md
  flagged as a real gap.
- **[x] The town's opinion of the player.** `Settlement.player_standing`
  (-1..1), a real deterministic bounded random walk (`tick_player_
  standing`, same shape as temperament) nudged monthly by the volume of
  recent `/intervene/*` activity, mean-reverting without reinforcement.
  Folded into the town-brain prompt as one more quiet input once it's
  notably warm/cold — never narrated or labeled in the UI, same
  treatment as temperament. The discrete tracked lever CLAUDE.md flagged
  as not yet built, alongside temperament for general mood.

See docs/DECISIONS.md, "everything left" pass.

## Cross-cutting, ongoing at every phase

- **Snapshot scaling.** Flagged since Milestone 1 (`docs/DECISIONS.md`
  M1-4): full-JSON snapshots won't hold up once buildings/history/
  chronicle text accumulate. Needs to become event-sourced or incremental
  probably by Phase C, not later.
- **Backward-compatible migrations.** The pattern established in M2-3
  and generalized in Phase A (detect-missing-key, backfill, log,
  persist-once) is the template for every future save-format change.
- **Docs/CHANGELOG discipline.** Every phase updates `README.md`,
  `CHANGELOG.md`, and `docs/DECISIONS.md` as part of the work, not after.
- **Release testing.** See `docs/TESTING.md` for the checklist run before
  every release, from Milestone 1's CLI onward through the eventual
  browser interface.
