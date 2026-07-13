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
| Culture | shipped (single-settlement) | E1 (naming, traditions) + E3 (prosperity-gated inventions/tech unlocks) + festivals + generational/family memory + a culture-specific building type (SHRINE); multiple named settlements not built |
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
- **[x] Per-agent inventory/trade, v1.** `Agent.inventory` (currently
  one good, `"food"`) — a deliberately scoped slice, not the full
  peer-to-peer barter economy this note originally envisioned: stashed
  from farm/granary foraging, drawn on by the agent themself first,
  then shared directly with a colocated, non-rival neighbor
  (`Population._maybe_trade_food`). See docs/DECISIONS.md, "per-agent
  inventory/trade... Phase G v4" pass. Tying `AgentGoal`/LLM cognition
  into economic decisions remains open for a future round.

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
- **[x] Culture-specific building type, v1.** `BuildingKind.SHRINE` —
  foundable only once the settlement has established a tradition,
  deepens festivals held on its tile and slightly raises the omen
  chance (the first direct culture-buildings/Phase-G interaction). See
  docs/DECISIONS.md.
- Not yet built: multiple named settlements — explicitly scoped out of
  the same batch that shipped the item above (see docs/DECISIONS.md,
  "Multiple named settlements: explicitly not attempted this batch"
  for the full rationale); remains the correct next candidate for its
  own dedicated session.

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
- **[x] Structured per-family belief resolution.**
  `beliefs.resolve_family_agent_ids` widens a belief's resolved subject
  to their living parents/children/full siblings (computed from
  `Agent.parents`, no surname system exists), stored as
  `subject_family_agent_ids` and consumed by dialogue's `beliefs_about`
  alongside the existing single-agent match. See docs/DECISIONS.md.
- Not yet built: a true scrub-through-time replay view.

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

## Phase H — Living knowledge, institutions, and dynamic carrying capacity

Explicit user directive (2026-07-13): treat knowledge as a living ecosystem —
memories evolving into beliefs, hypotheses, traditions, myths, and scientific
knowledge that spread, compete, mutate, merge, and disappear across
generations; people, settlements, and the world itself learning through
observation, experimentation, prediction, and experience; unique cultures and
emergent collective intelligence rather than static memory dumps. **This is a
direction-setting entry, not a implementation batch** — the user explicitly
asked to identify where the architecture should evolve to support this over
future releases, not to build it all now. Nothing below is `[x]`; treat every
bullet as a future session's starting brief, prioritized per the user's own
ordering.

Two things every item below should preserve, because they're why Hearthmind
works today: (1) the objective/subjective split (`World`/`Settlement`/`Agent`
ground truth vs. `Agent.memories`/`Settlement.beliefs` as fallible
interpretation) — every new "knowledge" system is another *interpretation*
layer, never a new source of ground truth; (2) deterministic-engine-does-
physics, LLM-does-judgement — a spreading/mutating idea is still judgement,
so its content stays LLM-authored even as its propagation mechanics (who
hears it, how it decays, what it competes with) can be deterministic, same
shape as gossip/rumor contagion already is.

### H1. Dynamic carrying capacity (highest priority — replaces `POPULATION_CAP`)

Current state: `POPULATION_CAP = 400` (`agents/population.py`) is a flat
safety valve with no in-world referent, and it's the direct cause of the
"town brain gets stuck on food" complaint fixed partially by disease (v0.44.0)
— disease adds a release valve but doesn't make the *ceiling itself* mean
anything. Food is already load-bearing (farm/granary carrying-capacity rework,
v0.41.0) but housing (`huts_standing`), labor (idle-agent count), civic
infrastructure (upkeep-funded capacity), security (predator/disease pressure),
and environment (terrain/climate quality) are not yet composed into one
number.

Evolution point: replace the single scalar cap with a settlement-computed
`carrying_capacity()` derived from the same signals `Settlement`'s four
domain objects (`Infrastructure`/`Economy`/`Culture`/`Disposition`) already
track — housing slots from `Infrastructure`, food surplus trend from
`Economy`, sickness/predator pressure from `Population`/`Disposition` — so
reproduction/migration gating (`Population._maybe_welcome_migrant`, birth
eligibility) reads a number that moves with the settlement's real situation
instead of a constant. `POPULATION_CAP` becomes a hard ceiling far above any
realistic computed value (an actual safety valve again, not the operative
constraint). No new entity required — this is a derived-property addition to
existing domain objects, the smallest-footprint item on this list.

### H2. Beliefs -> world models

Current state: `Settlement.beliefs` (`llm/beliefs.py`) is a small, capped,
settlement-level list of independent theory-strings, each optionally resolved
to `subject_agent_id`/`subject_family_agent_ids`. It has no structure beyond
"text + optional subject" — no confidence, no evidence trail, no notion of
one belief superseding or contradicting another, no per-agent equivalent
(only per-family resolution via `Agent.parents` matching).

Evolution point, staged rather than a single rewrite:
1. Give existing beliefs a minimal schema upgrade (confidence/strength,
   formed-tick, superseded-by-index) *within* the current list-of-dicts
   shape — same incremental-extension discipline the project has used for
   every prior beliefs expansion (subject resolution, family resolution),
   not a new store.
2. Extend belief *holders* beyond settlement-only: an agent's `memories`
   list already carries interpretation; a "personal belief" is structurally
   the same list-of-theories shape as `Settlement.beliefs`, just scoped to
   one agent instead of the settlement facade — reuse the mechanism, don't
   invent a parallel one, mirroring the explicit "don't build a second
   per-agent belief-store" instruction already honored for per-person
   beliefs.
3. Family- and institution-level beliefs (H3) become the natural next
   scope once institutions exist as addressable entities to attach a
   belief-holder to, rather than resolving only to individual agent ids.
4. "Continuously build, revise, and act upon" is the real bar — revision
   already exists (subject-string matching, not fragile index-matching per
   the v0.39.0 review fix); *acting upon* a belief already happens for
   dialogue/town-brain; extending that consumption to cognition goal
   selection itself (an agent avoiding a place its beliefs mark dangerous)
   is the concrete next mechanical payoff, not just more belief text.

### H3. Institutions as first-class entities

Current state: none. Families exist only implicitly via `Agent.parents`;
there is no persistent object representing a council, guild, market, or
religion — nothing outlives the individuals currently holding a role.

Evolution point: this is the largest structural addition on this list and
should follow the same shape as the Settlement-facade split (v0.40.0) —
introduce a lightweight base (an `Institution` dataclass: id, kind, founding
tick, member agent ids, a beliefs-shaped list of its own persistent
positions/norms, optional resource claims) rather than one bespoke class per
institution kind. Families are the cheapest first instance (derivable
today from `Agent.parents` chains — mostly a matter of giving the existing
implicit structure a persistent id and a beliefs-list) and should land before
councils/guilds/markets, both because they're structurally simplest and
because H6 (inheritance) needs an addressable family entity to inherit
*through*. Institutions should be tick-visible in `Settlement`'s composed
domain objects (most naturally a fifth domain, or folded into `Culture`)
rather than a bolt-on registry, to keep the single-writer/tick-loop
invariant intact.

### H4. Resource-driven economy: ownership, specialization, supply chains, trade

Current state: settlement-scale only (materials/currency pools,
`Agent.inventory`'s single-good personal food stash, direct neighbor food
sharing). No ownership of land/buildings by specific agents, no per-agent
production specialization, no multi-good supply chain.

Evolution point: `Agent.inventory` is already the right seam — it was
deliberately scoped to one good as v1. The natural next slice is multi-good
(materials, crafted goods) before ownership/specialization, since goods
without an owner-to-produce-them can't specialize meaningfully. Building
ownership (which agent(s) a HUT/WORKSHOP belongs to) is a small addition to
`Building` (an owner agent id, defaulting to "commons" for existing
settlement-wide buildings so nothing currently working breaks). Supply
chains (workshop consumes materials -> produces goods -> traded) are the
first place this project would need a genuine multi-step production graph;
scope that as its own dedicated session per the project's "one coherent
milestone at a time" rule, not folded into a batch with unrelated systems.

### H5. Knowledge as a system distinct from beliefs

Current state: doesn't exist as a separate axis. `tech_level` (buildings.py)
is a settlement-wide scalar unlocked by rare LLM "invention" rolls —
knowledge that a settlement has it, not knowledge any specific agent
possesses, teaches, or could fail to pass on.

Evolution point: the key design distinction to hold onto — beliefs are
*interpretive and revisable* ("the harvest failed because the town is
unlucky"), knowledge is *procedural and teachable* ("how to smith a tool").
Model it as a second list-shaped attribute (`Agent.skills` or similar),
propagated by a colocation-driven teaching/observation roll — structurally
the same shape as dialogue-driven rumor spread and gossip contagion already
use (`Population.apply_dialogue`, `GOSSIP_OPINION_CONTAGION`), just carrying
a skill/technique payload instead of an opinion. `tech_level` becomes the
settlement-aggregate signal (e.g. threshold count of agents holding a skill)
rather than an independently-rolled scalar — ties invention mechanics to
actual population knowledge instead of a disconnected dice roll, a concrete
emergence win (a settlement that loses its few skilled elders to plague
should visibly regress, not just narratively).

### H6. Psychology: habits, identity, values, trauma, ambition

Current state: `Agent` has needs (hunger/energy), relationships, trust,
memories, and a fixed small goal set. No persistent personality trait beyond
what a cognition prompt reconstructs fresh each call.

Evolution point: smallest coherent step is a compact, bounded trait vector on
`Agent` (2-4 axes to start, not a big-five system) that (a) is read into
cognition/dialogue prompts as context the way beliefs already are, and (b) is
nudged slowly by lived experience (grief, violence witnessed, sustained
hunger) using the same bounded-random-walk-plus-event-nudge shape
`temperament`/`player_standing` already establish at the settlement level —
reuse that pattern at agent scale rather than inventing a new one. Trauma
specifically should hook the *existing* memory-of-grief/violence events
already logged, not require new event types.

### H7. Cross-generational inheritance

Current state: `Agent.parents` links generations for memory/dialogue
purposes only; nothing material passes down — land/buildings aren't owned,
so nothing can be inherited; traditions/culture are settlement-wide already
so every generation "inherits" them by default, uniformly.

Evolution point: genuinely blocked on H3 (family as an addressable entity)
and H4 (ownership) landing first — inheritance is the mechanism that moves
something (land claim, a family belief, a grudge, a skill from H5) from a
dying agent to specific living relations rather than dissolving it. Once
those exist, inheritance is mostly a hook on the existing death path
(`Population._apply_deaths`) that reassigns ownership/beliefs to
`Agent.parents`/children instead of just logging grief.

### H8. The Town as an ancient, ambiguous intelligence

Current state (Phase G, already shipped): `Settlement.temperament` +
`llm/omens.py` + `Settlement.beliefs`. The permanent instruction — subtlety,
never confirmed, never labeled in the UI — is unchanged and should keep
gating every future addition here.

Evolution point: once H2 gives beliefs more structure (confidence, revision
history) and H3 gives the settlement an institution-shaped home for its own
"opinions," the Town's belief list becomes a natural place for those same
upgrades to land first (it's already the most-established belief-holder in
the codebase) — a proving ground for H2's schema before extending it to
per-agent/per-institution holders, not a separate effort.

### H9. Documentary mode, replay, timelines, developer observatory

Current state: yearly documentary narration (`llm/documentary.py`), curated
`GET /history`, capped `priority_history`/`omen_history` logs, and the
dev-console diagnostics panel — no scrub-through-time replay (flagged
open since Phase F).

Evolution point: every H1-H8 addition should log through the *existing*
categorized-event pipeline (`events` table, `SimulationEngine._log`) rather
than a parallel log, so replay/observatory tooling built once continues to
cover new systems automatically — the standing reason F's "why did this
happen" tooling has stayed cheap to extend so far. A scrub-through-time view
remains its own dedicated session (needs a keyframe+delta replay model, not
just more curated narration) and gets more valuable, not less, the more of
H1-H8 actually ships — more worth explaining accumulates over time.

### Suggested sequencing

H1 (carrying capacity) first — it's the smallest, most self-contained, and
directly answers a recurring live-diagnostic complaint. H3 (institutions,
starting with families-as-entities) next, since H4/H6/H7 all structurally
depend on having an addressable entity beyond individual `Agent`s. H2
(belief structure) and H5 (knowledge) can proceed in parallel with H3 once
it lands, since both mostly extend existing list-shaped mechanisms rather
than depending on institutions directly. H6 (psychology) and H8 (Town
belief upgrades) are cheap, low-risk, and can slot into any batch once H2's
schema exists. H4 (full supply chains) and H7 (inheritance) are the largest
and most dependent items and should each get their own dedicated session,
same treatment "multiple named settlements" already gets.

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
