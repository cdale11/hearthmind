# Design decisions

A running log of non-obvious choices and why they were made, so future
contributors (including future us) don't relitigate them without context.

## M1-1: Sim time pauses when the server is off

Alternatives considered: fast-forwarding by the elapsed wall-clock time on
restart (simulating every missed tick), or timestamp-jumping the clock
without simulating the gap.

Chosen: sim time only advances while the process is alive and ticking.

Why: fast-forwarding requires either (a) actually running potentially
thousands of missed ticks synchronously on startup, which is unbounded
compute with no clear cap, or (b) jumping the clock without simulating
anything, which silently invalidates state (e.g. weather "in progress",
crops that should have grown) without doing the work to make that true.
Once there are agents and an economy, "what happened while the server was
down" becomes a real design question worth solving properly (e.g. a bounded
catch-up simulation, or an explicit "you were away" summary) — but for a
terrain/clock/weather-only world it's not worth the complexity yet. This is
the kind of decision meant to be revisited, not a permanent stance.

## M1-2: Weather is derived per-tick, not stored as an RNG stream

`WeatherSystem` doesn't persist a `random.Random` object's internal state.
Instead, each tick's weather is derived from `hash(seed, tick)` fed into a
fresh `random.Random`. This makes weather a pure function of
`(world_seed, tick)` — reproducible from a snapshot without needing to
serialize RNG internals, and trivially safe to "replay" or inspect for any
past tick without re-simulating everything before it.

## M1-3: Terrain generation uses midpoint displacement, not Perlin/Simplex noise

No external dependencies were introduced for Milestone 1 (see README). Pure
midpoint displacement (diamond-square) gives plausible, seed-deterministic
elevation without numpy or a noise library. This can be swapped out later
(e.g. for multi-octave noise with rivers carved by simulated water flow)
behind the same `generate_terrain(seed, width, height) -> Grid` interface,
so nothing downstream should need to change.

## M1-4a: `sim_minutes_per_tick` is creation-only, not runtime-tunable

Caught by actually running the server, killing it, and inspecting the saved
state rather than by reasoning about it in advance: `sim_minutes_per_tick`
was initially (incorrectly) grouped with `tick_seconds` as a "safe to change
between runs" field. It isn't — `total_sim_minutes = tick_count *
sim_minutes_per_tick`, so changing it between runs retroactively reinterprets
what every previous tick meant (a world saved at tick 30 with 240
min/tick was "5 days in"; reloaded with the default 15 min/tick it silently
became "7.5 hours in" with no error). It's now stored in the snapshot
alongside seed/width/height/calendar-shape and ignored (with a logged
warning) if a differing value is passed on resume — the same treatment as
the other creation-only fields. `tick_seconds` (real seconds per tick) stays
runtime-tunable because it only controls wall-clock pacing, not the meaning
of a tick.

## M1-4: Snapshots store full world state as JSON, not incremental diffs

Simple and easy to reason about at this scale (a 64x64 grid + a handful of
scalars). Once agents, buildings, and history exist, this will likely need
to change to incremental/differential snapshotting or a proper event-sourced
rebuild, since re-serializing the whole world every N ticks won't scale. The
`events` table already exists as an append-only log partly to make that
future migration easier — it's meant to become the source of truth for
"current events" in the interface, and could eventually support rebuilding
state by replay instead of only reading snapshots.

## M2-1: Agent needs/movement use a namespaced per-tick RNG, like weather

`Population.tick` derives its randomness from `hashlib.sha256(f"{seed}:population_tick:{tick}")`,
the same pattern `weather.py` uses (M1-2), rather than carrying a live
`random.Random` on the population. Same reasoning: a pure function of
`(world_seed, tick)` needs no RNG-state serialization and is safe to inspect
or replay for any past tick. `population_init` (initial spawn placement) is
namespaced separately from `population_tick` so the two don't collide if
both ever need the same tick number's entropy.

## M2-2: Hunger has no consumption mechanic yet — this is intentional

Agents in this slice have a `hunger` need that always increases; there is no
food source, foraging, or death. This looks unfinished but is a deliberate
scope cut: modeling starvation meaningfully requires a food economy
(foraging, farms, granaries) to exist first, otherwise "death from hunger"
would just be a countdown timer with no interesting causes or texture. Needs
tracking was added now because movement/state (awake vs. resting) already
needed *some* signal to key off, and energy/resting was enough to justify
the `AgentState` machinery — hunger came along for consistency and because
the next slice (foraging) will want it already wired into serialization.

## M2-3: Loading a pre-Milestone-2 snapshot spawns a population, once

Old saves have no `"population"` key. Rather than fail to load, refuse to
load, or silently leave the world population-less forever,
`World.from_dict` detects the missing key, spawns a fresh initial population
on that terrain, and sets a `migrated_population` flag (not itself
serialized) so `SimulationEngine.load_or_create` can log a
`population_migration` event and persist a snapshot immediately — so the
migration only happens once per save, not on every future load. This is the
same "detect absence, backfill, log it" shape we'll want for future save
format changes, so it's worth establishing as the convention now rather than
inventing a new one per field. (Generalized in A4, below.)

## D1: Farms are a second food source, not a replacement for wild foraging

`FarmGrid` (`hearthmind/economy/farms.py`) mirrors `ResourceGrid`'s shape
closely (get/tick/summary/to_dict/from_dict) but adds a planting step:
any single awake agent on an unclaimed grassland tile may plant a plot
(no maturity/health/colocation requirement — farming is meant to be an
easy, individual act, unlike founding a building), which then grows
automatically over ~250 ticks with no further tending needed, and yields
substantially more food per harvest (`MAX_FARM_YIELD` 3.0,
`HARVEST_HUNGER_RELIEF` 0.5) than a wild `ResourceNode`. `Population.
_maybe_forage` checks for a ready farm at the agent's tile before falling
back to wild foraging, so once farms exist they're strictly preferred.
Deliberately narrower biome eligibility (`FARMABLE_BIOMES` = grassland
only) than `FORAGEABLE_BIOMES` (forest/grassland/hills) — cleared,
cultivated fields shouldn't appear inside forest the same way wild
berries do.

## D2 (finding): Farming fixed survival-to-maturity, but revealed a second bottleneck — social dispersion

Re-running the exact soak configurations that caused total population
extinction in C5, now with farming: a 6-agent/32x32 run (seed 42) still
lost 5 of 6 agents on essentially the *same* schedule as before farming
existed (ticks 491–1581, unchanged), but the 6th survived to age 4082 —
past `MATURITY_TICKS` (4000) — instead of dying early, a ~3x
improvement in that agent's lifespan directly attributable to farming.
A larger 30-agent/48x48 run (seed 7) went further: **3 agents survived
to age 27,035** (nearly 7x `MATURITY_TICKS`) with the run still going
when the test ended, versus complete extinction in the equivalent
pre-farming C5 test. Farming is a verified, working fix for the
starvation-before-maturity problem, not just a plausible one.

But no reproduction or construction occurred in either run, including
the 27,035-tick one where three mature, farm-fed, well-nourished agents
were alive simultaneously. Inspecting their final positions explained
why: they'd ended up scattered across the map (tens of tiles apart) with
`relationships` decayed to ~0 — farming lets an agent survive
indefinitely *alone*, since it doesn't require another agent's presence
the way foraging-adjacent survival tactics might, so there's no pressure
pulling survivors toward each other. This is a different bottleneck than
C5's (which was raw survival) — reproduction/construction need
`REPRODUCTION_AFFINITY_THRESHOLD`/colocation, which requires agents to
actually spend time together, and nothing currently creates that
pressure once individual survival is solved. A candidate next slice:
either bias the SOCIALIZE goal (or a new farming-adjacent goal) to prefer
settling *near* other agents' farms rather than planting wherever an
agent happens to be, or make `PLANT_CHANCE_PER_TICK` fire less often for
solitary agents than colocated ones — either would make "settling near
others" a more natural outcome of farming instead of purely coincidental.

**Update (D4): resolved.** See below — the root cause turned out to be
two concrete, fixable gaps rather than a deep balance problem.

## D3 (bug fix, found via live play with real Ollama): resting blocked foraging, creating a starvation trap

The first real-world run against a live Ollama instance (not the fake
test server) surfaced a severe bug within ~1250 ticks: population fell
from 12 to 4 agents, all four survivors simultaneously resting with
average hunger 0.64 and climbing, while 10 of 11 farm plots sat ready
and unharvested. `--agents` output showed the LLM had correctly
diagnosed the emergency — `goal=forage` with reasons like *"Need to find
food before hunger reaches critical level"* for agents at hunger=1.00 —
but it made no difference, because `Population._maybe_forage` only ran
`if agent.state is AgentState.AWAKE`, and nothing could interrupt rest
for a hunger emergency. An agent could wake (via `WAKE_THRESHOLD`), fail
to reach food before energy drained back down to `REST_THRESHOLD`, and
re-sleep — repeating indefinitely while hunger climbed every tick
regardless of sleep state. This is what killed the other eight agents in
that run; the LLM's cognition was correct and irrelevant, because the
deterministic execution layer never gave it a chance to act.

Fixed with two coordinated changes, both gated on a new
`CRITICAL_HUNGER_THRESHOLD` (0.9, deliberately below
`STARVATION_HUNGER_THRESHOLD`'s 0.95 so the fix engages before the death
countdown even starts):
1. `_maybe_forage` no longer requires `AgentState.AWAKE` — an agent can
   eat food at their current tile while resting, without needing to
   fully wake first.
2. A resting agent whose hunger crosses `CRITICAL_HUNGER_THRESHOLD` wakes
   immediately (interrupting rest early, before `WAKE_THRESHOLD`), and a
   `goal=REST` no longer re-sleeps an agent that's still critically
   hungry — both closing the "wake briefly, can't reach food in time,
   sleep again" loop.

This is the kind of bug that's structurally invisible to unit tests
written against the same assumptions the code was written under — it
took a real multi-thousand-tick run with real population dynamics (and a
real LLM correctly identifying the emergency, which is what made the
"correct goal, ignored" pattern legible at all) to surface. Regression
tests were added afterward (`tests/test_agents.py`,
`TestStarvationTrapFix`) replicating the exact trap shape.

## D4: Fixing social dispersion — two concrete gaps, not a deep balance problem

D2 found that farming let agents survive indefinitely alone, with no
pressure pulling survivors toward each other — three well-fed, mature
agents could sit alive simultaneously for tens of thousands of ticks
without ever reproducing or building anything. Investigating turned up
two specific, fixable causes rather than a fundamental design gap:

1. **`SOCIALIZE`'s target search shared `FORAGE`'s local radius
   (`GOAL_SEARCH_RADIUS`, 6 tiles).** That's a reasonable cap for wild
   food awareness, but on a 64x64 (or larger) map, ordinary WANDER drift
   routinely puts agents more than 6 tiles apart within a few hundred
   ticks — at which point `SOCIALIZE`'s `_nearest_other_agent` finds
   nobody, silently falls back to wandering, and there is no mechanism to
   ever re-converge. Once agents exceed that distance, they're
   permanently isolated from each other. Fixed by removing the distance
   cap for `_nearest_other_agent` entirely (renamed the constant to
   `FORAGE_SEARCH_RADIUS` since it's now FORAGE-only) — an agent actively
   seeking company is assumed to know roughly where the (small)
   population's other members are, not just what's locally visible.
2. **`fallback_goal` (`hearthmind/llm/cognition.py`) never returned
   SOCIALIZE at all** — only forage, rest, or wander. This meant that
   whenever Ollama was disabled or unreachable, nothing in the entire
   system could ever choose to socialize; only a live LLM could. Every
   soak test in this project's own development (including all of C5/D2's
   soak tests) ran without Ollama, so this alone would have been enough
   to explain the total absence of clustering, independent of the radius
   issue. Fixed by having content (not hungry, not tired) agents split
   deterministically by `agent_id` parity between SOCIALIZE and WANDER,
   rather than always wandering.

**Verified with the exact 30-agent/48x48 configuration (seed 7) that
produced D2's "three lonely survivors" result.** With both fixes: the
population reached a self-sustaining, multi-generational equilibrium —
**30+ births** across the run, a full building lifecycle repeating
multiple times (`construction_started` → `building_completed` →
`building_ruined`, across at least 8 distinct structures), and
population turnover through both starvation *and*, for the first time in
any soak test, **old age** (`Ursula died of old age` at tick 25,192) —
sustained continuously for 25,657 ticks (~3 sim-years) with population
fluctuating between roughly 10 and 30 individuals rather than trending to
zero. This is the first time every subsystem built so far (terrain,
weather, needs, foraging, farming, relationships, reproduction,
settlement, aging) has been observed working together as a genuinely
self-sustaining "town in a box," not just individually correct in
isolation.

## D5 (bug fix, found via a real soak run against live Ollama): a critically hungry agent could keep walking the wrong way

A follow-up diagnostic from the user's own machine, running with
`--llm-enabled` against a real Ollama instance, showed a population
collapsing early (12 -> 5 inhabitants) well before any agent reached
`MATURITY_TICKS`, with the survivors' shared age (2760 ticks, all
original spawns, zero births) confirming the die-off happened before
farms or reproduction had a chance to help. The LLM itself was reasoning
correctly — the visible agents had genuine, contextual, weather-aware
`goal_reason` text — so this wasn't a repeat of D3 (resting blocking
foraging; that fix already applied) but a related, previously-unnoticed
gap in the same area.

`AgentGoal` is only reevaluated once per sim-day
(`Population.due_for_cognition`), and hunger rises at a fixed
`HUNGER_RATE` every tick regardless of goal. If an agent is assigned
SOCIALIZE or WANDER while well-fed, nothing about `_dispatch_movement`
deliberately seeks food again until the *next* day's reevaluation — over
a full day at default pacing that's up to ~0.96 hunger accumulated
(96 ticks * `HUNGER_RATE` 0.01) between checks, i.e. an agent can arrive
at the doorstep of `CRITICAL_HUNGER_THRESHOLD` (0.9) purely by chance of
what goal it happened to be assigned. The D3 fix only handled a resting
agent being unable to wake up and forage in place; it never addressed an
*awake* agent whose assigned goal has it walking toward company, or
nowhere in particular, while starving.

Fixed the same way D3 fixed the resting case: `Population.tick` now
passes `critically_hungry` (`hunger >= CRITICAL_HUNGER_THRESHOLD`) into
`_dispatch_movement`, which substitutes an effective goal of FORAGE for
movement-targeting purposes only — the agent's actual assigned `goal`
(and `goal_reason`) is left untouched, so this reads as a temporary
survival reflex, not a goal change the LLM didn't make. See
`tests/test_agents.py`,
`test_critical_hunger_overrides_socialize_goal_to_seek_food`.

The same diagnostic run also showed one `LLM call failed ... timed out`
warning. The fallback handled it correctly (that's the whole point of
B1's design), but it was invisible from a saved snapshot — you'd only
know it happened by reading server logs at the time. Two changes address
this directly rather than guessing at a "fix" for a single observed
timeout:

- **`llm_timeout_seconds` default raised from 10s to 20s** — CPU
  inference sharing an 8GB+zram machine with the simulation process
  itself is realistically slower under contention than a quiet
  benchmark; every call still degrades to the deterministic fallback
  regardless, so this only trades a longer worst-case wait for fewer
  unnecessary fallbacks.
- **Cumulative diagnostics now persisted on `World`/`Population` and
  surfaced by `inspect_world`:** `llm_calls_total`/`llm_fallback_total`
  (so a flaky/overloaded Ollama instance shows up as a fallback rate in
  a snapshot, not just in logs you may not have kept), and
  `deaths_starvation`/`deaths_old_age` (so a population crash between
  two snapshots — like the one that prompted this investigation — is
  visible as a number, not something you have to infer from "there used
  to be more agents"). `inspect_world --agents` also now shows each
  agent's `starving_ticks` and a maturity countdown, so "why hasn't
  anything happened yet" can be answered directly ("nobody's mature yet"
  vs. "something is actually broken") without reading source code.

## D6 (bug fix, found via live-play diagnostics): FORAGE never targeted farms

Diagnostic at tick 660 (30-agent config): 16 starvation deaths despite 27
harvest-ready farms and 0 LLM fallbacks (LLM reasoning fine). Root cause:
`_dispatch_movement`'s FORAGE branch only ever called `_nearest_resource`
(wild nodes) — a ready farm plot was never a movement target, only
harvestable by luck of standing on one. Fixed: added `_nearest_ready_farm`
(uncapped distance, same rationale as D4's SOCIALIZE — cultivated land is
known to its community, unlike wild forage) and FORAGE/critical-hunger
movement now prefers it over wild nodes. Verified: seed=7/48x48/30-pop,
6000 ticks, 0 starvation deaths (previously 16 by tick 660 on similar
config). Also: wind now reported as a qualitative label
(calm/breezy/windy/gale) via `WeatherState.wind_label()` instead of a raw
float, in both `describe()` and future diagnostic output.

## D7: Granaries — dedicated building type, presence-driven stock/withdraw

First building-kind differentiation (`BuildingKind`: HUT/GRANARY). No
per-agent inventory system exists in this project, so deposit/withdraw
follow the established presence-driven pattern (like foraging,
construction) rather than a hauling goal: well-fed awake agents
(`hunger <= GRANARY_WELLFED_HUNGER_THRESHOLD`) present at a standing
granary contribute surplus each tick; hungry agents there withdraw,
between a wild forage and a fresh farm harvest in value. `_maybe_forage`
priority: farm > granary > wild. FORAGE/critical-hunger movement targets
farm > granary > wild resource, with granaries getting the same uncapped
search as farms (D6) — a built structure is known to its community.
30% of new constructions roll GRANARY vs HUT (`GRANARY_KIND_CHANCE`);
not yet an agent/LLM choice, same caveat as C1.

## D8: Production chains — GATHER goal, materials stockpile, construction speed boost

First production-chain slice: new `AgentGoal.GATHER` (forest/hills ->
settlement-wide `materials` stockpile, presence-driven like every other
mechanic, no per-agent inventory). Consumed by `_advance_construction`:
while materials are available, `MATERIALS_PER_CONSTRUCTION_TICK` (0.1) is
drawn per tick in exchange for `CONSTRUCTION_MATERIALS_MULTIPLIER` (2x)
progress — verified directly (0.05 -> 0.1 progress/tick, 5.0 -> 4.9
materials, matching the constants exactly).

SYSTEM_PROMPT updated so a live LLM can actually choose GATHER; fallback
split changed from 2-way (SOCIALIZE/WANDER) to 3-way
(SOCIALIZE/GATHER/WANDER) by `agent_id % 3`, same reachability rationale
as D4 — a goal only a live LLM can ever pick has no fallback-only
coverage.

Design call made without a user round-trip (per "continue"): materials
are a single settlement-wide scalar, not per-tile/per-building — no
hauling/transport system exists, and food-storage (granaries, D7)
already established that model. Farm-yield boost from materials was
scoped out of this slice to keep it to one clear effect (construction
speed); flagged as the natural next slice if wanted.

## D9: Farm-yield boost from materials ("tooled" plots)

Closes the other end of D8's production chain. `_maybe_plant` spends
`FARM_TOOL_MATERIALS_COST` (2.0) from the settlement stockpile, if
available, to plant a "tooled" plot instead of a plain one — `FarmPlot`
now carries its own `max_yield` (set at planting: `MAX_FARM_YIELD *
FARM_TOOL_YIELD_MULTIPLIER`, 1.5x, or the plain constant), rather than
every plot sharing one global constant. Verified directly: a tooled plot
ripened to 4.5 (3.0 * 1.5) vs. a plain plot's 3.0, exactly as configured.

## D10: Currency — settlement-wide, no per-agent trade

The roadmap's "trade/currency" line item, scoped deliberately: this
project has no per-agent inventory/wallet system, and building one from
scratch to support literal peer-to-peer barter would be a much larger,
separate design decision than "implement the next roadmap items" should
make unilaterally. Instead, `Settlement.currency` (0..`CURRENCY_CAPACITY`,
50.0) represents trade with an abstract outside economy, symmetric with
the `materials`/granary pattern already established (D7/D8):

- **Generated** from food/materials surplus that would otherwise be
  wasted once a granary or the materials stockpile is already at
  capacity — selling what the settlement can't use or store.
- **Spent** as a last-resort "emergency rations" purchase
  (`CURRENCY_EMERGENCY_RATION_COST` 2.0 for `CURRENCY_EMERGENCY_HUNGER_RELIEF`
  0.4) at a standing granary, only once nothing free (farm, granary
  stock, wild forage) is available — the granary doubles as the
  settlement's trade post rather than introducing a new building kind.
  `_nearest_stocked_granary` now also targets an empty granary if the
  settlement can afford rations there.

Verified directly: granary-at-capacity deposits converted to currency
(0.18 accrued, granary held steady at its cap); a hungry agent with nothing
else available bought emergency rations for the exact configured cost and
relief.

True per-agent trade (an agent with personal surplus selling directly to
a hungry neighbor) remains unbuilt and would need an inventory system
first — flagged for a future roadmap discussion, not assumed here.

## E1: Culture, slice 1 — settlement naming, traditions, chronicle feeds back into cognition

Phase E's first slice, staying tightly scoped to what the roadmap
actually describes (settlement names, generational memory, chronicle
read back into later prompts) rather than inventing new subsystems:

- **Naming**: the first tick any building becomes STANDING, `World.tick`
  deterministically names the settlement (`settlement/naming.py`,
  prefix+suffix compound, namespaced RNG like every other generator in
  this project) and logs a `settlement_named` event. Unnamed = "not yet
  a real settlement," used as the gate for everything below.
- **Traditions**: once named, a new `year_end`-cadence job
  (`hearthmind/llm/culture.py`) invents one named tradition per year —
  slower than B3's seasonal chronicle, matching "generational." Stored
  as `Settlement.traditions: list[str]`, persisted, unbounded (no cap
  needed at the timescales this project runs). Deterministic fallback
  cycles a fixed 5-entry pool by count-established, so a fallback-only
  run still accumulates distinct culture across years rather than
  repeating one entry forever.
- **Feeds back into prompts** (closing the gap flagged since B3): both
  `cognition.build_prompt` (per-agent goals) and `chronicle.build_prompt`
  (seasonal summary) now take optional `settlement_name`/traditions
  context, appended only once a settlement exists — early-game prompts
  are unaffected (verified: an unnamed-settlement prompt is byte-identical
  to the pre-E1 prompt shape).

Verified end-to-end through `SimulationEngine` (not a standalone
`World.tick()` loop, so cognition/chronicle/tradition scheduling all
actually ran): seed=7/48x48/30-pop, ~2 sim-years — settlement named
"Oakreach," two distinct traditions established via the fallback pool
("The First Harvest," "Hearthlight"), confirmed via direct prompt
inspection that a named settlement's context string renders correctly.

Not built (left for a future round, not assumed): named individual
lore/generational memory *per agent* (e.g. an agent recalling their own
history), multiple settlements, and any building type specifically for
"culture" (currently piggybacks on the settlement being named at all,
not on a particular structure).

## F1: Phase F slice 1 — read-only WebSocket API, one dependency exception

First Phase F slice: a broadcast-only WebSocket channel
(`hearthmind/interface/api.py`), `--api-enabled` (off by default, same
pattern as `--llm-enabled`). No intervention endpoints — the roadmap
explicitly puts those last, once there's something worth looking at.

**Dependency exception, made deliberately, not by default:** Python's
stdlib has no WebSocket support, and Phase F's own roadmap entry calls
for one. Asked the user directly rather than silently picking a library
or hand-rolling the protocol; chose to add `websockets` as an **optional
extra** (`pip install hearthmind[api]`), not a hard dependency — the
base install (`dependencies = []` in `pyproject.toml`) stays exactly as
zero-dependency as before for anyone who never passes `--api-enabled`.
`hearthmind.simulation.engine` only imports `WorldBroadcaster` under
`TYPE_CHECKING`, and `server.py` only imports the `interface.api` module
at all when `config.api_enabled` is true, so `websockets` being
uninstalled is a non-issue unless the feature is actually requested.

**Never blocks a tick**, the same liveness invariant as the LLM layer
(B1): `WorldBroadcaster.broadcast()` is fired as a background task from
`_tick_once`, never awaited inline; a slow or dead client can't stall
the simulation, and disconnects are cleaned up opportunistically.

Payload is the same `World.summary()` dict `inspect_world`/the CLI
already produce, plus that tick's `last_life_events` — no new data model,
just a new transport for state that already existed.

Verified for real, not just unit-level: ran `hearthmind.server
--api-enabled`, connected a genuine `websockets` client, received a live
tick broadcast with the correct payload shape, and confirmed both the
engine and the API server shut down together on stop (they share
`engine.stop_event`).

## F2: Phase F slice 2 — FastAPI backend, static browser client, external libraries allowed

Follow-up to F1, after the user explicitly allowed external libraries
project-wide (tracked in `requirements.txt`, no longer just a scoped
websockets-only exception). Four design questions were asked and
answered before building (see chat, not repeated here):

1. **Frontend**: plain HTML/CSS/JS, no build step
   (`hearthmind/interface/static/`) — a single page, vanilla JS, canvas
   map. No npm/node toolchain to run alongside the Python server.
2. **Backend**: switched from raw `websockets` (F1) to **FastAPI +
   uvicorn** — one framework serving static files, a REST snapshot
   endpoint, and the WebSocket stream, replacing hand-rolled glue.
   `requirements.txt` added (previously only `pyproject.toml`'s
   `[project.optional-dependencies]` tracked this); both are kept in
   sync in the `api` extra.
3. **First view**: live map + dashboard together, not staged — canvas
   terrain (drawn once, static) with agents/buildings/farms as a dynamic
   overlay redrawn every tick, plus a stat-tile sidebar and event log.
4. **REST alongside WebSocket**: yes, `GET /state` (current snapshot),
   `GET /terrain` (static grid, fetched once), `GET /events` (history) —
   the page paints immediately from these before the first WebSocket
   tick arrives, rather than showing a blank page.

**Architecture**: `interface/api.py` (`WorldBroadcaster`, framework-free)
stays the one bridge between the engine and the web layer — it now also
holds `_last_payload` (for `GET /state`) and a one-time `_terrain_payload`
(set once in `SimulationEngine.__init__`, since terrain never changes —
NOT part of the per-tick broadcast, keeping tick payloads small).
`interface/app.py` isolates all FastAPI/Starlette imports to one module.
`server.py` runs `uvicorn.Server.serve()` alongside `engine.run_forever()`
in the same `asyncio.gather`, wired to `engine.stop_event` for a shared
clean shutdown. The engine still never awaits anything web-related
inline — `_maybe_broadcast` remains fire-and-forget, unchanged in
principle from F1.

**Per-tick payload** now includes `agents`, `buildings`, `farms` (not
just the summary) — needed for the map's dynamic overlay. At current
soak scales (dozens of agents) this is small; flagged as a place to
revisit (e.g. delta-only updates) if population/building counts grow
much larger, per the M1-4 snapshot-scaling note.

Verified for real end-to-end: ran the server with `--api-enabled`,
fetched `/terrain`, `/state`, `/events` over plain HTTP, connected a
genuine WebSocket client and received a correctly-shaped live tick, and
loaded `/` + `/static/app.js` to confirm the page and script serve.

## C1: Building placement is deterministic in this slice, not yet an LLM/goal decision

The roadmap describes buildings as "an agent/B2 decision," but this slice
places them the same way A3 places births: colocated, mature, healthy
agents roll a small per-tick chance (`SETTLE_CHANCE_PER_TICK`) to found a
building at their shared tile, with no existing structure there. This
mirrors `_maybe_reproduce`'s shape deliberately — it's cheap, testable
scaffolding that gives Phase B's goal system (and later, Phase E's
culture layer) something concrete to influence once "where/whether to
settle" becomes a real decision worth spending an LLM call on. Wiring
`AgentGoal` into building placement is the natural next slice, not
something this one tries to preempt.

## C2: Construction/repair progress requires physical presence, not an explicit intent

An agent doesn't need a "build" goal to contribute to a building under
construction (or a damaged one below `REPAIR_THRESHOLD`) — any awake
agent standing on that tile counts as a worker each tick, up to
`MAX_WORKERS` (3; more agents than that don't speed things up further,
a crude stand-in for "only so much useful room to work"). This keeps
construction consistent with how foraging already works (automatic
based on state, not an explicit chosen action) rather than introducing
a second, inconsistent mechanism. The cost: an agent with
`goal=SOCIALIZE` who happens to end up on an under-construction tile
while seeking another agent will incidentally contribute labor. That's
treated as a feature, not a bug, for now — "showing up" mattering is
exactly the kind of emergent texture the project wants — but it may need
revisiting once agents have work assignments that should be exclusive.

## C3: Weathering is a flat per-tick decay, amplified (not gated) by harsh weather

`Settlement.tick` reduces a standing building's condition by
`DECAY_PER_TICK_BASE` every tick, tripled (`DECAY_WEATHER_MULTIPLIER`)
when precipitation/wind/snow cross a threshold. Decay is never zero even
in perfect weather — buildings should erode gradually just from time and
use, not only during storms, so "abandoned in a mild climate" is still a
real trajectory toward ruin, just a slower one. Ruined buildings persist
(inspectable, part of `Settlement.buildings`) for `RUIN_REMOVAL_TICKS`
(3000, ~31 sim-days at default pacing) before being removed entirely —
long enough that a visiting deity (the user) can actually witness the
ruin, not just its sudden disappearance.

## C4: Settlements start empty; nothing is pre-placed at world creation

`World.create_new` gives every world a `Settlement()` with zero
buildings — construction only ever happens through the population's own
behavior (C1), never seeded. This is a thematic choice as much as a
technical one: Milestone 1 hands the deity a wild, ungoverned world, and
whether it becomes settled at all is something that emerges (or doesn't)
from the population that inhabits it, not something the world generator
decides in advance.

## C5: Populations tend to collapse from starvation before reaching settlement — an honest finding, not (yet) a fix

While verifying Phase C's release checklist, I ran two long CLI sessions
(6 agents on a 32x32 map for ~8,600 ticks; 30 agents on a 48x48 map for
~17,000 ticks) specifically trying to observe organic construction. In
both, every agent eventually died of starvation — none reached
`MATURITY_TICKS` (4000). Construction/repair/weathering/reclamation are
all directly unit-tested (`tests/test_settlement.py`, 21 tests calling
the mechanism functions with controlled inputs, the same approach used
for A3's reproduction) and the integration/persistence/migration path is
verified through the real CLI (see `docs/TESTING.md`), so the mechanism
itself is trustworthy — but I have **not** personally witnessed a
building complete through unassisted play, and said so plainly rather
than write a CHANGELOG entry implying I had.

This is being recorded as a finding, not silently patched: system-wide
food *production* (nodes × regen rate) comfortably exceeds population
*demand* at these population sizes by the numbers, which points at
*access* (agents finding/reaching enough of the available nodes,
especially via pure WANDER before their first daily cognition
evaluation) rather than raw scarcity as the likely bottleneck — but this
hasn't been root-caused with certainty, only observed. Deliberately not
rebalancing Phase A's forage constants speculatively here: the project
explicitly wants "prosper, stagnate, or disappear" to be real outcomes,
population collapse under current tuning is a legitimate (if maybe too
easy to trigger) instance of "disappear," and Phase D (agriculture) is
specifically the mechanism meant to relieve foraging-only scarcity — so
this finding is a natural argument for prioritizing Phase D's design
carefully, not a bug to quietly paper over in Phase C. A future session
should either tune Phase A's forage/movement balance directly (increase
`GOAL_SEARCH_RADIUS`, `NODE_DENSITY`, or the FORAGE goal's trigger
threshold) or treat it as expected and let Phase D's agriculture be the
actual fix.

**Update (D2):** Phase D's agriculture was the actual fix, and this was
re-verified, not just hoped for — see D2 below. Farming resolved the
starvation-before-maturity problem this entry describes; a related but
distinct bottleneck (agents surviving alone rather than forming groups)
took its place.

## A1: Foraging uses discrete, depletable resource nodes, not a passive per-biome rate

Alternatives considered: a passive "agents on grassland/forest lose hunger
slower" rule (no spatial resource state at all), or per-tile continuous
food density.

Chosen: sparse `ResourceNode`s scattered at world creation (12% of
forageable tiles), each holding up to 1.0 units, consumed by foraging and
regenerating slowly (~500 ticks to fully regrow from empty).

Why: the roadmap's emergence goal needs scarcity to be a *place-based* fact,
not an ambient property of a biome. A passive rate can never run out, so a
crowded area can never actually be foraged bare — which forecloses the most
interesting future dynamics (competition, migration pressure, a settlement
outgrowing its foraging grounds). Discrete depletable nodes cost more state
than a passive rate but are what makes "a population that grows faster than
its foraging grounds regenerate should feel real scarcity" true rather than
aspirational. Fish/water-adjacent foraging was considered and deferred —
`FORAGEABLE_BIOMES` covers forest/grassland/hills only for now.

## A2: Agent lifespan is tracked in ticks as an abstract "vitality" budget, not literal years

Each agent gets `max_age_ticks`, randomized at spawn between
`MIN_LIFESPAN_TICKS` (20,000) and `MAX_LIFESPAN_TICKS` (40,000). At the
default config (15 sim-min/tick, 96 ticks/day) that's roughly 2.6–5.2
sim-years — short for a human lifespan, but deliberately so: these are
round numbers chosen for something to actually observably die of old age
within a reasonably short test/dev run, not a literal claim about how long
a Hearthmind villager should live. Revisit once the calendar/pacing is
tuned for a "real" long-running deployment (see the README's note on
`--tick-seconds`/`--sim-minutes-per-tick`).

Starvation death uses a separate mechanism: `starving_ticks` counts
consecutive ticks at or above `STARVATION_HUNGER_THRESHOLD` (0.95); it
resets to zero the moment hunger drops below that (e.g. from a successful
forage), and death only fires after `STARVATION_TICKS_TO_DEATH` (200)
consecutive ticks — so a single bad tick doesn't kill an agent, but
sustained inability to eat does.

A hard `POPULATION_CAP` (200) exists purely as a safety valve against
unbounded growth before food scarcity or (later) an economy can naturally
cap population through starvation pressure. It is not meant to be the
long-term mechanism — Phase D (agriculture/economy) should make it
unreachable in practice well before it needs raising.

## A3: Reproduction requires mutual affinity built through colocation

Agents accumulate a per-pair `relationships` affinity (0.0–1.0) that rises
while colocated (`RELATIONSHIP_GAIN_PER_TICK_COLOCATED`) and decays
otherwise (`RELATIONSHIP_DECAY_PER_TICK`), independent of and much simpler
than anything an LLM will eventually do with relationships (Phase B/E).
Reproduction requires both agents mature (`age_ticks >= MATURITY_TICKS`),
healthy (hunger ≤ 0.7, energy ≥ 0.3), colocated, and above
`REPRODUCTION_AFFINITY_THRESHOLD` (0.6) — then rolls a small per-tick chance
(`REPRODUCTION_CHANCE_PER_TICK`, 1%). This is intentionally the cheapest
possible model: no genetics, no explicit pair-bonding/monogamy, no
preference beyond raw affinity. It exists so the population has *some*
deterministic, testable growth mechanic before Phase B's LLM gets involved
in anything relationship-shaped — replacing or layering on top of this is
expected, not something this decision tries to preempt.

## B1: Ollama client built on stdlib `urllib`, not `requests`/`httpx`

Ollama is the project's first real external dependency (see README), but
talking HTTP to a local REST API doesn't need a new pip package on top of
it — `urllib.request` is sufficient and keeps `pyproject.toml`'s
`dependencies` list empty for one release longer. `requests` happened to
already be present in this development sandbox, which made it tempting,
but that's an environment accident, not something to design around;
revisit only if the stdlib client becomes a real maintenance burden (e.g.
needing HTTP/2 or connection pooling Ollama's API would actually benefit
from).

The client (`hearthmind/llm/client.py`) is deliberately dumb: one method,
one endpoint (`/api/generate` with `format: "json"`), blocking by design.
Async orchestration lives one layer up in `hearthmind/llm/jobs.py`
(`CognitionRunner`), which wraps the blocking call in
`asyncio.to_thread` — this keeps the client trivially unit-testable
without any asyncio machinery, and keeps "how do we run this without
blocking the event loop" as a separate, explicit concern.

`CognitionRunner` is the single choke point every LLM-backed feature (B2
goals, B3 chronicle) goes through: a bounded semaphore
(`llm_max_concurrent`, default 2) caps in-flight requests — this is the
idle-CPU-utilization lever described in the project brief. Ollama's own
thread pool does the actual inference; keeping more than one request in
flight is what lets it use more than one core. Every call goes through a
timeout and a caller-supplied deterministic fallback and *never raises* —
LLM failure must degrade quality, never liveness. This was tested against
a fake local HTTP server standing in for Ollama (`tests/_llm_fake_server.py`)
covering success, malformed JSON, non-200 status, connection-refused, and
timeout paths — but genuine interop with a real Ollama installation has
**not** been verified in this environment (Ollama isn't installed in this
sandbox). Treat that as a real gap to close, not a formality — verify
against an actual `ollama serve` + pulled model before relying on this in
production.

## B2: Goals are a fixed enum, not free text — decision-first, not dialogue-first

The LLM chooses one of four fixed goals (`AgentGoal`: wander/forage/
socialize/rest) rather than producing free-form text. This keeps the
output structured, cheap to validate (`parse_goal` degrades any
unexpected value to WANDER rather than guessing), and — critically —
directly executable by deterministic movement logic. This is what
"decision-first, not dialogue-first" (from the project roadmap) means
concretely: the LLM's job is to pick from a small set of consequential
choices, not to produce prose the rest of the system has to interpret.

Goals are re-evaluated once per sim-day, staggered by agent id
(`(tick + agent.id) % ticks_per_day == 0`) so a full day's cognition
spreads evenly across the day's ticks instead of arriving as one burst
that would spike LLM load and desync from a "thundering herd" pattern.
WANDER is both the default goal and exactly the pre-Phase-B movement
behavior — an agent with no goal assigned yet (or loaded from a
pre-Phase-B save, where `Agent.from_dict`'s `.get("goal", "wander")`
default applies) behaves identically to Phase A. FORAGE/SOCIALIZE bias
movement toward the nearest visible target (`GOAL_SEARCH_RADIUS`, 6
tiles) via a simple greedy step, falling back to ordinary wandering when
nothing is in range; REST proactively pauses an agent even below the
energy threshold that would otherwise force it. None of this requires the
LLM to be enabled — `CognitionRunner` resolves to `fallback_goal()`
(a simple hunger/energy rule) when disabled, so the goal system has real
behavioral effect even without Ollama installed.

Cognition requests are scheduled and their results collected entirely
inside `SimulationEngine` (fire-and-forget `asyncio.Task`s, results
applied at the top of the *next* `_tick_once`) rather than inside
`Population`/`World`. This preserves the existing invariant from M1
("the engine is the only thing that mutates the World... it never blocks
the loop") without weakening it — `World.tick()` stays fully synchronous
and is unaware the LLM exists at all.

## B3: Chronicle reuses the `events` table; triggered on `season_end`

Rather than a new `chronicle` table, chronicle entries are just `events`
rows with `category="chronicle"` — the table already stores arbitrary
tick/category/description text, and a chronicle paragraph is only a
longer description. Avoids a schema migration for what is, structurally,
the same kind of record. Triggered once per season turn (not every day —
that would be both expensive and repetitive at this population/event
scale) and built from the last 50 events plus a population summary.
Falls back to a deterministic templated summary (birth/death counts) when
the LLM is unavailable — less evocative than prose, but still a real,
useful record, and consistent with every other Phase B fallback in this
project: degrade quality, not existence.

## B4: Default model is `qwen2.5:3b`, sized for an 8GB-RAM machine running zram

The project brief targets modest desktop hardware — specifically, running
comfortably on 8GB of RAM with zram swap, alongside the simulation process
itself and whatever else the machine is doing. That budget rules out
7B-class models: even Q4-quantized, a 7B model's weights (~4-5GB) plus KV
cache for a live context, plus Ollama's own overhead, plus the Python
process, leaves uncomfortably little headroom — and zram swap absorbing
the overflow means *slower*, not just tighter, which matters for a model
that needs to answer dozens of short prompts per sim-day without falling
behind.

`qwen2.5:3b` at Ollama's default quantization is roughly 2GB of weights —
comfortable on 8GB with real headroom for the OS, Ollama, the simulation,
and `llm_max_concurrent` (2) simultaneous requests. Qwen2.5's instruction-
tuned models are specifically known for reliable structured/JSON output
compliance relative to their size, which matters more here than raw
reasoning depth: every prompt in this project (`cognition.py`,
`chronicle.py`) demands strict JSON back, and a model that occasionally
wanders into prose or malformed JSON just means more fallback triggers,
degrading the feature rather than breaking anything — but a model that's
*reliably* good at the format gets more real LLM-authored content through
rather than deterministic fallback text.

This is a starting point, not a mandate — `--llm-model` is a runtime flag
precisely so a deployer with more RAM (or wanting to trade latency for
quality) can size up (e.g. `qwen2.5:7b`) or size down (e.g. `qwen2.5:1.5b`
on a tighter machine) without touching code. If real-world use on 8GB
hardware (once verified against an actual Ollama install — see B1)
reveals `qwen2.5:3b` is too slow for the daily-cognition cadence at
default pacing, the fix is tuning `--tick-seconds`/cognition frequency
before it's changing the default model.

## A4: Migration flag generalized to `migrated_subsystems`

M2-3 introduced a single `migrated_population: bool`. Phase A needed the
same "detect absence, backfill, log it" behavior for a second subsystem
(`resources`), so the boolean became `migrated_subsystems: list[str]`,
and `SimulationEngine.load_or_create` iterates it against a
per-subsystem lookup table (`_MIGRATIONS` in `simulation/engine.py`,
mapping subsystem name to `(description_template, count_fn)`) instead of
hand-writing a new `if world.migrated_x:` branch per subsystem. Future
subsystems that need backfill-on-load should add an entry to that table
and a branch in `World.from_dict`, not invent a third mechanism.

**Update (Phase D code review):** originally this was two separate
dicts, `_MIGRATION_DESCRIPTIONS` and `_MIGRATION_COUNTS`, keyed by the
same subsystem names — a code review after Phase D added a 4th subsystem
(`farms`) flagged that two parallel dicts needing to stay in sync by hand
was already showing strain, so they were merged into one `_MIGRATIONS`
dict of tuples. `World.from_dict`'s four sequential if/else blocks were
*not* further generalized into a registry/loop — with only four
subsystems, each needing a genuinely different `from_dict`/default-factory
pair, a loop-based registry felt like premature abstraction for the
current scale; revisit if a 5th or 6th subsystem makes the copy-paste
pattern there start to hurt.

## E2: NPC-to-NPC dialogue, relationships extended to rivalry, LLM on by default

The user's explicit brief: "NPCs talk/speak with each other and
influence each other and the world," with emergence as the primary
objective, and "local LLM has no budget constraints — enable by
default." Three changes:

**LLM enabled by default.** `Config.llm_enabled` flips `False -> True`;
`llm_max_concurrent` raised `2 -> 4`. `server.py`'s `--llm-enabled` flag
became `--llm-disabled` (inverted) to match — every LLM call still
degrades to its deterministic fallback if Ollama isn't reachable, so this
only changes what a bare `Config()`/no-flags run does, not safety.

**NPC dialogue (`hearthmind/llm/dialogue.py`).** Colocated, awake agent
pairs periodically get an LLM-authored short exchange (`line_a`/`line_b`,
a `sentiment`, and an optional `rumor`), scheduled the same
fire-and-forget way as cognition/chronicle/culture — never inline with a
tick. Selection lives in `Population.due_for_dialogue`: scan colocated
awake pairs, filter by a per-pair cooldown (`DIALOGUE_COOLDOWN_TICKS =
300`, stored in `Population.dialogue_cooldowns`), cap at
`MAX_DIALOGUES_PER_TICK = 3`, then pick via a namespaced RNG shuffle
(deterministic per seed/tick, same discipline as everything else). The
cooldown is stamped at *selection* time, not when the LLM result arrives
— this doubles as in-flight tracking, so a slow LLM call can't cause the
same pair to be re-selected next tick. Dialogue lines and any rumor are
logged as ordinary `dialogue`/`rumor` events, which means they
automatically feed back into the chronicle and culture prompts (both
already read `recent_events`) with no extra wiring — a rumor seeded by
two agents can end up shaping a later tradition or chronicle entry
without either subsystem knowing about dialogue specifically. This is the
main emergence lever this slice adds: content that started as a private
exchange between two agents can ripple into settlement-level culture.

**Relationships extended to rivalry (-1..1, was 0..1).** A `tense`
dialogue sentiment nudges affinity negative (`DIALOGUE_SENTIMENT_DELTA`),
which needed `Agent.relationships` to support negative values —
previously `_update_relationships`'s decay clamped at a `0.0` floor,
which would have silently eaten any negative value back to neutral every
tick. Decay now pulls toward `0.0` from whichever side a value is on.
Passive colocation gain (`RELATIONSHIP_GAIN_PER_TICK_COLOCATED`) is
unchanged — forced proximity still nudges a relationship toward positive
regardless of sign, which is a deliberate call ("time spent together
matters even between rivals") rather than an oversight. Reproduction
(`REPRODUCTION_AFFINITY_THRESHOLD = 0.6`) needed no change: a negative
value already fails that comparison the same as a low positive one.
`RIVALRY_THRESHOLD = -0.4` is the read used by the dialogue prompt/
fallback to decide when two agents are framed as "at odds" rather than
merely unacquainted.

**Scoping note:** persistent per-agent memory of *specific* past
exchanges (not just an aggregate affinity number) and rumor-driven
behavior change (an agent avoiding a rival, not just a relationship
number going negative) are left for a future slice — this one makes
dialogue *exist* and *feed relationships/culture*, not agents *reasoning*
about their social history. Tracked as A5 in `docs/ROADMAP.md`.

## E3: Inventions — rare, prosperity-gated tech-tier unlocks

The last of the three systems from the "build all together" brief
(dialogue/E2, inventions/E3, wildlife/A4 — this is E3). Mechanically a
sibling of E1's traditions (same `year_end` cadence, same LLM-authored-
name-plus-description shape, same deterministic-fallback-pool pattern)
but deliberately rarer and gated, so it reads as a real event rather than
a yearly formality:

- **Gate:** only rolled for a *named* settlement that's also
  *prosperous* — `currency >= INVENTION_CURRENCY_THRESHOLD` (10.0) or
  `materials >= MATERIALS_CAPACITY * INVENTION_MATERIALS_FRACTION`
  (half of 30.0). A settlement still scraping by never invents anything;
  surplus is the precondition, matching the real-world intuition that
  invention follows slack, not survival.
- **Roll:** independent of the tradition roll, `INVENTION_CHANCE_PER_YEAR
  = 0.5` via a new deterministic `_namespaced_roll(seed, tick, namespace)`
  helper in `simulation/engine.py` — a lighter-weight sibling of
  `Population`'s `_namespaced_rng` for the rare cases (just this one, so
  far) where the engine needs a single deterministic float rather than a
  full `random.Random`.
- **Effect:** each invention increments `Settlement.tech_level`, read via
  a new `Population._tech_factor(settlement) = 1 + TECH_BONUS_PER_LEVEL *
  tech_level` (0.15/level) multiplier applied to construction work,
  repair work, farm-harvest hunger relief, granary-withdraw hunger
  relief, and granary deposit rate. Deliberately *not* applied to wild
  foraging — invention represents cultivated/civilized technique, not
  something that makes berries taste better. Uncapped: self-limiting in
  practice since inventions themselves are rare and gated by surplus that
  the compounding bonus itself helps generate (a believable "rich get
  richer" dynamic, not a runaway exploit — a settlement still has to
  survive weather decay, starvation risk, and reproduction gates
  regardless of tech level).
- **New module:** `hearthmind/llm/invention.py`, structurally identical
  to `culture.py` (`build_prompt`/`fallback_invention`/`parse_invention`)
  — kept as a separate file rather than folded into `culture.py` because
  the two have materially different trigger conditions (prosperity-gated
  + independent roll vs. flat yearly) even though the LLM-authoring shape
  is the same.

Settlement gained two new persisted fields (`tech_level: int`,
`inventions: list[str]`) — both `Settlement.to_dict`/`from_dict` default
missing keys to `0`/`[]`, so old saves load without a migration entry
(same pattern as every other additive field in this project).

## A4: Wildlife & ecology — grazer herds, predator packs, huntable

The last of the three "build all together" systems (dialogue/E2,
inventions/E3, this one). Closes the biggest gap flagged in
`docs/ROADMAP.md`'s original feature checklist: terrain/weather/seasons
existed, but nothing *living* occupied the terrain besides the
settlement itself.

**Model (`hearthmind/world/wildlife.py`).** Discrete, mobile
`AnimalHerd`s (not a per-animal simulation — herds, like `Population` is
per-agent but wildlife doesn't need that granularity) of two species:
`GRAZER` (grassland/forest, reproduces slowly when under
`MAX_HERD_SIZE`) and `PREDATOR` (forest/hills, hunts colocated grazer
herds, starves and shrinks if it goes too long without a kill —
`PREDATOR_STARVE_GRACE_TICKS`/`PREDATOR_STARVE_CHANCE`). This is a real
second trophic level, not flavor text: predators measurably suppress
grazer growth, and a predator pack that can't find prey genuinely
starves out (verified over a 2000-tick run: grazer population grew
while the sole surviving predator pack dwindled from 4 to 1 for lack of
prey in its wandering radius — the ecosystem has its own internal state,
independent of anything agents do).

**Movement is a slower, sparser drift than agent wandering**
(`MOVE_CHANCE = 0.3` vs. agents' 0.5, `HERD_DENSITY = 0.02` vs.
resources' `NODE_DENSITY = 0.12`) — herds should read as migrating
wildlife, not another population of townsfolk.

**Hunting integrates into the existing forage chain, not a new
`AgentGoal`.** A hungry agent colocated with a live grazer herd hunts it
automatically inside `Population._maybe_forage`, slotted between
"stocked granary" and "wild resource node" — richer yield than either
(`HUNT_YIELD_PER_ANIMAL = 0.6` vs. `FORAGE_HUNGER_RELIEF = 0.3`,
`HARVEST_HUNGER_RELIEF = 0.5`), the payoff for a chancier food source
(herds wander; a farm doesn't). `_dispatch_movement`'s FORAGE branch
gained `_nearest_grazer_herd`, bounded by `WILDLIFE_SEARCH_RADIUS`
(matches `FORAGE_SEARCH_RADIUS`'s "locally visible, not map-wide"
rationale) — inserted after the granary check and before wild-resource
search, so a known food source (farm/granary) is still preferred over a
riskier hunt. Deliberately *not* a new `AgentGoal.HUNT`: adding one would
require touching the cognition prompt/fallback/validation surface for a
mechanic that fits naturally into the existing forage priority chain
without it.

**Threading `WildlifeGrid` through `Population.tick`.** Added as a
required parameter (`wildlife: WildlifeGrid`) alongside `resources`/
`farms`/`settlement`, same pattern as every other subsystem — not
optional/defaulted, since every world has wildlife by construction (see
migration below).

**Persistence/migration.** `World` gained a `wildlife: WildlifeGrid`
field; a snapshot missing it (any pre-A4 save) gets
`WildlifeGrid.generate()` backfilled and logged via the existing
`_MIGRATIONS` table in `simulation/engine.py` — same "detect absence,
backfill, log it" pattern as `population`/`resources`/`settlement`/
`farms`, no new mechanism invented.

**Scoping note:** no per-agent "hunting goal" or pathfinding toward prey
beyond the existing FORAGE-goal step-toward-target logic; no distinct
predator-vs-agent interaction (predators only prey on grazers, never
threaten agents) — kept out deliberately to avoid a second combat/danger
system this slice didn't ask for. Revisit if the user wants wildlife to
be a threat, not just a food source.

## C5: Infrastructure — foot-traffic-driven roads

The last item from `docs/ROADMAP.md`'s original feature checklist.
`hearthmind/world/roads.py`'s `RoadNetwork` tracks a `wear: dict[(x,y),
float]`, mirroring `settlement/buildings.py`'s construction/decay shape
rather than being planned/pathfound: a walkable tile with no building and
no farm on it gains `ROAD_WEAR_PER_TICK` (0.01) whenever at least one
awake agent stands on it that tick, and loses `ROAD_DECAY_PER_TICK`
(0.0008 — deliberately ~12x slower than the gain rate) otherwise. At
`ROAD_ESTABLISHED_WEAR` (0.5) a tile counts as an established road,
which gives agents standing on it a `ROAD_SPEED_MULTIPLIER` (1.4x)
random-walk move-chance bonus in `Population._maybe_move` — the concrete
payoff for a well-trodden path, applied only to the undirected wander
case (goal-directed `_step_toward` already moves deterministically every
call, so a speed bonus there would be a no-op).

Occupancy is computed in a new `Population._update_roads`, called once
per tick right after `by_position` is finalized (post-movement, so a
tile only wears from where agents actually ended up, not where they
started). Excludes building/farm tiles deliberately — the intent is
paths *between* things, not wear registering on top of a granary or a
field, which already have their own condition/stage tracking.

Threaded through `Population.tick`/`_dispatch_movement`/`_maybe_move` as
a required `roads: RoadNetwork` parameter, same pattern as `wildlife` in
A4. `World.roads` persists and migration-backfills to an empty
`RoadNetwork()` for pre-C5 saves (no retroactive guessing at where paths
"should" have been, matching the `settlement`/`farms` migration
precedent). Also included in the browser broadcast payload
(`_maybe_broadcast`'s `"roads"` key) though the static client doesn't
render it yet — left as a follow-up for whoever next touches
`interface/static/app.js`.

This closes every system named in the user's original full feature list
(terrain, weather, seasons, ecology/wildlife, humans, relationships,
economy, agriculture, construction, infrastructure, building decay,
culture, history, supernatural-reserved-for-Phase-G) — see
`docs/ROADMAP.md`'s feature checklist table for the complete map from
request to implementation.
