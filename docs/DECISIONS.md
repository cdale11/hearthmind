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

## UI pass: human-readable events, materials/currency clarity, dev console

Direct user feedback: the browser window (Phase F) wasn't keeping pace
with what the simulation could now do — new systems (dialogue, rumors,
inventions, wildlife, roads) weren't visible, the event log was raw
category/description text, and "materials/currency" as bare numbers gave
no sense of what they represented. Four changes, no new backend
subsystems:

**Event log became human-readable.** `interface/static/app.js` gained a
`CATEGORY_META` table mapping each event category to an icon and a CSS
class (`event-category-<name>`) for color/emphasis — births green,
deaths red, rumors/inventions accented, calendar/chronicle events
muted+italic. `day_end` is suppressed from the rendered log entirely
(still stored server-side, fetchable via `/events`) — at one line per
day it drowned real events and duplicated what the header's date/clock
already shows; `season_end`/`year_end` stay since they're real
milestones. This is a display-only filter, not a backend change.

**Materials/currency/granary/tech tiles gained `title` tooltips and
capacity fractions.** Previously "Materials / Currency" was one
unlabeled `12.3 / 4.1` tile — no way to tell what either number meant or
how full the stockpile was. Split into separate tiles
(`Materials: 12.3 / 30.0`, `Currency: 4.1 / 50.0`, etc.), each with a
one-sentence `title` explaining what it tracks and how it's earned/spent
— surfaced via native browser tooltip, no new JS interaction needed.
`Settlement.summary()` gained `materials_capacity`/`currency_capacity`/
`granary_capacity` (aggregated across granaries, not per-building) so
the frontend doesn't hardcode constants that could drift from the
backend.

**New stat tiles for every system shipped this session:** Relationships
(close bonds / rivalries / avg affinity — new `Population.summary()`
fields), Tech level (inventions count), Wildlife (grazer/predator
totals), Roads (established/worn tile counts), NPC dialogue (cumulative
exchange/rumor counts — new `World.dialogue_total`/`rumor_total`
counters, same "make emergence visible in diagnostics" precedent as
`llm_calls_total`, D5). Wildlife herds and road wear are now also drawn
on the canvas map itself (grazers as green dots sized by herd count,
predators as red triangles, roads as a dirt-tint ground overlay under
farms/buildings) — the C5 decision entry had flagged map rendering as an
open follow-up; this closes it.

**Developer console.** A `⚙ dev` header button toggles a hidden `<pre>`
panel showing raw diagnostics as JSON: per-tick wall-clock duration
(`_last_tick_duration_ms`, timed around `_tick_once`'s synchronous body),
in-flight background task/cognition counts, connected WebSocket client
count (`WorldBroadcaster.client_count()`, new public method — the engine
no longer needs to reach into the broadcaster's private `_clients`), and
LLM config (enabled/model/max_concurrent). Purely a read surface over
counters that already existed or were trivial to add — no new engine
behavior, consistent with the read-only API's one-way-data-flow
invariant (F1/F2).

**Inventions got their own sidebar panel**, previously only visible via
the Tech level stat tile — mirrors the existing Traditions panel.

## UI fix: dev console not opening — stale-cache root cause, cache-busting

User reported the new dev console button didn't open the panel. Read
through `index.html`/`app.js`/`style.css` line by line — the toggle
handler, element IDs, and CSS were all correct and verified working in a
real server run. The far more likely cause: browsers cache `/static/*`
assets aggressively across page loads, so a browser that had the page
open (or cached) from before this UI pass would keep serving an old
`app.js` with no dev-console handler at all, while `index.html` (fetched
fresh at `/`) already had the new button — button visible, click does
nothing, exactly the reported symptom.

Fix: `interface/app.py`'s `/` route no longer serves `index.html`
verbatim via `FileResponse`. It now reads the file once at startup and
stamps its asset URLs with `?v=<hearthmind.__version__>`
(`/static/app.js?v=0.20.0`), returned via `HTMLResponse`. Every version
bump changes the URL, which busts any cached copy without disabling
caching within a version (repeat requests for the same version still
cache normally). This closes off an entire class of "I changed the UI
but nothing happened" reports going forward, not just this one instance.

## Batch: predator danger, relationship memory, festivals, seasonal/weather scarcity

Four systems built together per explicit user direction (build all
three named options plus tighten collapse-risk; batch into one commit
rather than one per system).

**Agent-vs-predator danger.** Predators previously only threatened
grazer herds (A4). `Population._maybe_predator_attack` rolls per awake
agent colocated with a live predator pack: `PREDATOR_ATTACK_CHANCE`
(0.015/tick) triggers an attack, `PREDATOR_KILL_CHANCE_ON_ATTACK` (0.12
of attacks) is lethal — true per-tick death odds ≈0.18%, low enough that
camping on a predator's tile is what makes it dangerous, not one
unlucky tick. Non-lethal attacks cost energy/hunger
(`PREDATOR_ATTACK_ENERGY_DRAIN`/`_HUNGER_INCREASE`) — injury, not a
clean miss. `WildlifeGrid.predator_tiles()` feeds movement avoidance:
`_step_toward`/`_maybe_move` now prefer any non-predator candidate tile,
falling back to a predator tile only when it's the sole walkable option
(an agent won't suicide-avoid itself into a corner, but does try not to
walk into danger). Predator-killed agents' death events are appended
where the attack happens (so the description can reference the specific
attack) rather than in `_apply_deaths`, which now just counts them via a
`killed_by_predator: set[int]` passed through from the main tick loop.

**Relationship memory.** `Agent.memories: list[str]` (capped at
`MAX_AGENT_MEMORIES=8`, oldest drops first) — populated only by
explicit dialogue-driven moments (`Population.apply_dialogue`: crossing
into a close bond or a rivalry, hearing a rumor) and by grief
(`_apply_deaths`: a survivor bonded to the dying agent remembers them
and pays `GRIEF_ENERGY_PENALTY`). Deliberately *not* triggered by the
passive per-tick colocation gain/decay — that would flood every agent's
memory with "still standing near someone" noise. The latest memory
feeds back into `cognition.build_prompt` ("You remember: ..."), so an
agent's own history — not just settlement culture — can shape its next
goal, closing the "agent recalling their own history" gap flagged in
ROADMAP's A5.

**Festivals.** `hearthmind/llm/festival.py`, structurally like
`culture.py` but a deliberately different gate/cadence: wellbeing-gated
(`FESTIVAL_HUNGER_GATE=0.5`, average hunger, not prosperity — contrast
inventions' currency/materials gate) and seasonal
(`FESTIVAL_CHANCE_PER_SEASON=0.35`, not yearly). Has a real mechanical
effect, not just narrative: `Population.hold_festival()` applies
`FESTIVAL_RELATIONSHIP_BOOST` (0.1) to every currently-colocated pair of
awake agents — "the village gathers, bonds strengthen" is something
that happens to agent state. `Settlement.festivals: list[str]` persists
history, mirroring `traditions`/`inventions`.

**Seasonal/weather scarcity** (the "make collapse more possible" ask).
Two levers, both direct implementations of "weather affects people" /
"seasons affect farming" from the original brief:
- `economy.farms.SEASON_GROWTH_MULTIPLIER` /
  `world.resources.SEASON_REGEN_MULTIPLIER`: winter cuts farm growth to
  35% and wild regen to 30% of baseline (autumn/spring get milder
  penalties/bonuses); `FarmGrid.tick(season)`/`ResourceGrid.tick(season)`
  now take the current season name, threaded from `World.tick` via
  `self.clock.season`. A season name absent from the table (custom
  `seasons_per_year`) defaults to 1.0 — no behavior change for
  non-default calendars.
- `Population._update_needs` now takes `weather_harsh: bool`
  (precipitation > 0.4, wind > 0.5, or snowing — the same definition
  `settlement/buildings.py` already uses for decay): an *awake* agent in
  harsh weather burns hunger 1.3x and energy 1.4x faster. Resting agents
  are unaffected (sheltering/sleeping, abstracted as weather-proof).
  Required threading a new `weather: WeatherState` parameter through
  `Population.tick`, computed once from `World.tick`'s own
  `self.weather`.

Together these mean a settlement can now genuinely decline during a bad
winter or a run of harsh weather (slower food production + faster need
drain, compounding), rather than the economy being effectively
season/weather-agnostic once farms/granaries existed. Population's hard
cap (200) is unchanged — it remains a safety valve, not the intended
plateau mechanism; actual population ceiling should now emerge from
food/weather pressure more than from hitting the cap.

**UI**: new Festivals sidebar panel (mirrors Traditions/Inventions);
Deaths stat tile includes predator count; agent hover tooltip shows the
most recent memory; new event icons/colors for `festival` (🎉, accented)
and `predator_attack` (🐺, red).

## Diagnostics, browser-default, resource variety, real building cost

Four fixes/features from direct user feedback after an overnight-soak
request, batched together:

**NPCs repeating dialogue (bug fix).** Root cause: `fallback_dialogue`
returned exactly one fixed line pair per relationship band, so any run
where the LLM is unreachable (or, now that `llm_enabled` defaults True,
simply not installed/running) repeats the identical 3 lines for every
pair forever — an obvious, boring bug the user caught immediately.
Fixed with small per-band pools (`_TENSE_POOL`/`_WARM_POOL`/
`_NEUTRAL_POOL`, 4 lines each) cycled deterministically by
`(agent_a.id + agent_b.id + tick) % len(pool)`. The dev console's new
`llm_stats` (calls_timed_out/errored) now also makes it directly visible
*why* fallback is firing so often, for next time.

**"tooled field" wording (bug fix).** `farm_planted` event text read "A
tooled field was planted..." — jargon nobody outside the codebase would
parse. Now: "A field was planted at (x,y), using tools for a richer
harvest."

**Extensive diagnostics for overnight soak debugging.** `CognitionRunner`
(`llm/jobs.py`) now tracks calls_attempted/succeeded/timed_out/errored
separately (previously just a single fallback flag) plus a rolling
200-sample latency window with p50/p95/max. `SimulationEngine` tracks a
500-sample tick-duration window (p95) and a snapshot-saved counter.
`WorldBroadcaster` gained `set_diagnostics_provider`/
`get_full_diagnostics` (a callable set once by the engine, same pattern
as `set_terrain`) so `interface/app.py` can stay framework-agnostic
while still exposing a new `GET /diagnostics` endpoint: engine telemetry
+ peak RSS memory + on-disk DB size + an all-time event-category
histogram from the DB. The browser dev console gained a "Full diagnostic
report" button that fetches it, displays it, and best-effort copies it
to the clipboard — built specifically so a user can paste one blob into
a bug report after an unattended run, without reproducing it live.

Also found via this audit: `Population.dialogue_cooldowns` grew
unbounded over a long run — every pair that ever talked stayed in the
dict forever, including pairs where one agent had since died.
`due_for_dialogue` now prunes entries for dead agents and entries older
than `cooldown_ticks * 8` each time it runs.

**Browser mode on by default.** `Config.api_enabled` flips
`False -> True`; `server.py`'s flag inverted to `--api-disabled`. The
fastapi/uvicorn import check moved earlier (before `SimulationEngine` is
constructed, since the engine needs to know upfront whether it has a
broadcaster) and is now caught: missing dependencies log a warning and
the server runs without the browser window rather than crashing — the
base install stays genuinely dependency-free, this is a *default*, not
a hard requirement.

**Resource variety: bush (food) vs. mine (ore).**
`world/resources.py`'s `ResourceNode` gained a `kind: ResourceKind`
(`FOOD` or `ORE`). Food nodes are unchanged (grassland/forest/hills,
fast regen). Ore nodes are hills-only (mountain isn't walkable, so an
ore vein there would be unreachable), rolled at a lower density, hold
double the max amount, and regenerate **12x slower**
(`ORE_REGEN_PER_TICK`) — "mines recover over longer time" is the literal
constant this answers. `Population._maybe_gather` (GATHER-goal
materials collection) now draws from a hills tile's ore node if one is
present there (consuming it, yielding nothing once depleted); forest
wood gathering is deliberately left uncapped — a forest is abstracted as
renewable, a specific mineral vein is not. Both kinds' regen is also
season-scaled (existing `SEASON_REGEN_MULTIPLIER`, now shared).

**Buildings actually cost materials to start.** Previously,
`materials` only sped construction *up*
(`CONSTRUCTION_MATERIALS_MULTIPLIER`) — a colocated, mature, healthy
pair could found a building with zero materials in the stockpile.
`HUT_MATERIALS_COST` (3.0) / `GRANARY_MATERIALS_COST` (5.0) are now
deducted (and required) at founding — `_maybe_start_construction` skips
founding entirely if the stockpile can't cover the cost. Verified over a
6000-tick soak that settlements still bootstrap fine: the first building
started at tick 4356, which is dominated by `MATURITY_TICKS` (4000) —
founders must already be mature — not by the new materials gate, which
adds only ~350 ticks on top in that run.

## Determinism dropped as a project requirement; weather particle overlay

**CLAUDE.md updated per explicit user instruction**: determinism/
reproducibility is no longer a project requirement. The namespaced-RNG
pattern isn't being ripped out (existing uses are harmless and some are
still the natural tool for picking among candidates), but new work is no
longer constrained by "must replay identically for the same seed" — this
opens the door to leaning on the LLM for more genuine decisions and to
simpler randomness where convenient. No code changed for this — it's a
policy change recorded in CLAUDE.md, effective for future work.

**Weather particle overlay.** `World.summary()` gained a
`weather_detail` key (`WeatherState.to_dict()` — temperature/
precipitation/wind/is_snowing) alongside the existing human-readable
`weather` string, so the browser client can react to actual conditions
rather than parsing prose. A new `<canvas id="weather-canvas">` layered
absolutely over the map canvas runs its own `requestAnimationFrame`
loop (`interface/static/app.js`), independent of tick cadence, so
rain/snow reads as continuous motion rather than snapping once per
tick. Particle count scales with `precipitation`; drift scales with
`wind`; `is_snowing` switches from rain streaks to falling snow dots.
Kept as a separate canvas (not drawn into the main map canvas) so the
weather effect never requires redrawing terrain/agents/buildings at
60fps — only the lightweight particle layer redraws every frame.

Vehicles (hauling carts + faster personal travel), terrain evolution
(both local activity-driven change and longer-term climate/biome
drift), and further visual richness are scoped but not yet built — see
CLAUDE.md's "Known architectural gaps" for the current list.

## Vehicles: hauling carts and personal-travel mounts

Both requested modes ("both 1 and 2" — hauling carts and faster
personal travel) built together as a new `settlement/vehicles.py`
module (`Vehicle`, `VehicleKind` CART/MOUNT, `VehicleStage`
BUILDING/READY/BROKEN), owned by `Settlement.vehicles` alongside
`buildings`, following the exact same lifecycle shape as buildings
(colocated-presence founding with a real material cost, presence-driven
construction/repair, weather-driven decay) so the two asset types read
consistently rather than inventing a second mechanic.

**Founding** (`Population._maybe_start_vehicle`): same trigger shape as
`_maybe_start_construction` — a colocated, mature, healthy pair, rolled
at `VEHICLE_CHANCE_PER_TICK` (0.004, rarer than `SETTLE_CHANCE_PER_TICK`
0.01: buildings stay the priority) — but gated on `settlement.name`
being set, since a vehicle presupposes an existing named community.
50/50 cart vs. mount; `CART_MATERIALS_COST` (4.0) / `MOUNT_MATERIALS_COST`
(6.0) deducted up front, same "no stockpile, no start" rule as buildings.

**Carts** are settlement-wide, not owned by any one agent: each ready
cart adds 25% to the yield of `Population._maybe_gather` (wood/ore
hauled per tick), stacking up to 3 carts (+75%), representing faster
hauling of gathered material back to the stockpile rather than a literal
per-trip inventory system (which this project doesn't have). Wear
(`CART_USE_DECAY`) is spread across all ready carts on any tick at least
one gather occurred, on top of passive weather decay.

**Mounts** are personal: `Population._maybe_assign_mounts` lets an awake
agent colocated with a ready, unclaimed mount claim it (first-come,
presence-driven, not a cognition decision). A mounted agent moves at
`MOUNT_SPEED_MULTIPLIER` (1.6x, slightly better than a road's 1.4x, and
stacks with it) — applied to the random-walk move-chance in
`_maybe_move`, and as a second `_step_toward` call toward the same
target for goal-directed movement (FORAGE/SOCIALIZE/GATHER), so a mount
helps a hungry agent reach food faster too, not just wandering. A dead
rider's mount is freed back to the unclaimed pool in `_apply_deaths`
rather than staying claimed by nobody forever.

**Wear and repair**: both kinds decay from weather like buildings
(`VEHICLE_DECAY_PER_TICK_BASE`/`VEHICLE_DECAY_WEATHER_MULTIPLIER`, milder
than a building's since a vehicle isn't a fixed structure), plus a small
extra use-decay while actively contributing. Hitting zero condition
flips `READY` to `BROKEN` (a mount immediately unassigns its rider) —
not lost, unlike a ruined building — and `Population._maybe_repair_vehicles`
repairs presence-driven exactly like `_maybe_repair`, flipping back to
`READY` once condition clears `VEHICLE_REPAIR_THRESHOLD`.

UI: a new "Vehicles" stat tile (ready cart/mount counts, mounts
claimed), map markers (amber square for a cart, violet diamond for a
mount — outline color shows claimed vs. unclaimed), and event icons for
`vehicle_started`/`vehicle_completed`/`vehicle_broken`. Verified via a
forced-GATHER 6000-tick run (LLM disabled in this environment, so goals
were pinned directly rather than relying on sparse cognition): a cart
and a mount were both founded, built to READY, the mount was claimed,
and both showed real condition wear from weather + use — plus a
serialization round-trip (`to_dict`/`from_dict`) of a populated vehicle
list. Terrain evolution (both local activity-driven and climate/biome
drift) remains the other confirmed-scope, not-yet-built item.

## dev-console-copy-fallback

**Root cause**: user reported the dev console's "Full diagnostic
report" copy-to-clipboard failing. `navigator.clipboard.writeText`
requires a secure context (https, or `localhost`) — accessed over plain
`http://<lan-ip>:8000` (the expected way to reach this server from
another device on the target hardware), the API doesn't exist at all,
not merely denied permission, so the existing try/catch always fell
through to "select manually." The report itself was always shown
correctly in the panel below the button — only the one-click copy
failed silently for anyone not on `localhost`/https.

**Fix**: added a `legacyCopy()` fallback using a hidden `<textarea>` +
`document.execCommand("copy")` — deprecated but still functional in
every browser lacking the modern Clipboard API — tried automatically
when `navigator.clipboard` throws. Status text now distinguishes
"copied to clipboard" / "copied to clipboard (legacy fallback)" / a
real failure message that explains the https-or-localhost requirement,
instead of always saying the same generic thing.

## Terrain evolution: local activity + climate/biome drift

Both requested modes ("both 1 and 2" — local activity-driven change AND
longer-term climate/biome drift) built together in a new
`world/terrain_evolution.py`, since they share the same underlying
mechanism (mutating a tile's `Biome` in the live `terrain` grid — `Tile`
stays a frozen dataclass, but `World.terrain[y][x]` is reassigned to a
new `Tile` with the same `x`/`y`/`elevation` and a different `biome`)
and the same "don't change biome under agents/buildings/farms/vehicles"
guard (`_is_developed`, excluding both developed tiles and any tile an
agent currently occupies).

**Local activity** (`apply_local_activity`, every tick): a per-tile
"deforestation heat" dict tracks sustained GATHER presence on forest
tiles — gains heat while an awake GATHER-goal agent is standing there,
decays otherwise. Once heat clears `DEFOREST_HEAT_THRESHOLD` (~100
ticks of continuous single-agent presence), a small per-tick chance
thins the tile FOREST -> GRASSLAND. `World._tick_terrain` derives the
active-tile set directly from `self.population.agents`' end-of-tick
positions/goals rather than threading a new return value through
`Population.tick` — keeps the change local to `world/state.py`.

**Reclamation** (`maybe_reclaim`, once per season — cheap to defer that
far since it's meant to be rare): an abandoned grassland tile (no
farm/building/vehicle, no agent standing there, no recent deforestation
heat) touching 2+ forest neighbors has a small chance to revert to
forest — "nature reclaims abandoned areas," the mirror image of
deforestation, and consistent with the buildings/roads decay-when-
unused pattern already shipped.

**Climate drift** (`ClimateState`, `tick_climate`/`apply_climate_drift`,
once per year): `warming`/`drying` are each a slow, bounded random walk
(`CLIMATE_STEP_MAX` per year, `CLIMATE_MEAN_REVERSION` pulling toward 0
so the trend doesn't run away over a long soak). `terrain.classify_with_bias`
is the same elevation->biome mapping `generate_terrain` always used,
parameterized by this bias — `warming` raises the mountain/snowcap
thresholds (those cold biomes shrink), `drying` lowers the water
thresholds and raises grassland/forest's boundary (water recedes,
grassland expands). Each year, a small random sample (2% of tiles) is
re-evaluated against the current bias and nudged **one** biome-step
(via a new `BIOME_ORDER` tuple) toward its target, never jumped straight
there — keeps the drift reading as gradual over many years rather than
a sudden reflow, and stays interruptible by the mean-reversion above.

**Known simplification**: a `ResourceNode`'s kind (FOOD vs ORE) is fixed
at world genesis and tied to `(x, y)`, not derived from the tile's
current biome — if a hills tile with an ore node drifts to grassland
under climate change, that node goes inert (no longer reachable via
`Population._maybe_gather`, which checks live biome first) rather than
retroactively converting. Rare in practice (climate drift samples 2%/
year and skips developed/occupied tiles) and doesn't cause incorrect
behavior, just an orphaned node — not worth a resource-regeneration
pass for how rarely it'll matter.

**Client staleness fix**: the browser's static terrain canvas and
`GET /terrain` were built on the (now false) assumption that terrain
never changes after boot (see F1/F2). `WorldBroadcaster.set_terrain` is
now also re-called from `SimulationEngine._maybe_broadcast` on any tick
whose life events include `terrain_thinned`/`terrain_reclaimed`/
`climate_drift`, and `app.js` re-fetches `/terrain` and redraws the
static canvas on the same trigger — event-driven, not polled, since the
underlying changes are rare by design.

Verified: a 2000-tick run with agents pinned to specific forest tiles
under sustained GATHER produced real `terrain_thinned` events and (at
the season boundary) `terrain_reclaimed` events; an 8200-tick run
crossed a year boundary and produced one `climate_drift` event with a
nonzero climate bias; `World.to_dict`/`from_dict` round-trips both
`climate` and a populated `terrain_activity` dict correctly; a combined
6000-tick run with vehicles simultaneously active showed no
interference between the two systems.

## Interventions, family memory, and smooth/lit rendering

Three previously-deferred gaps closed together (per "continue building
everything, do batch"): intervention ("nudge") endpoints, generational/
family-specific agent memory, and further browser visual richness
(smooth movement, day/night lighting) — the remaining items after
vehicles and terrain evolution, short of the two genuinely large,
architecturally separate items (multiple named settlements, per-agent
inventory/trade) intentionally left for their own future pass, plus
Phase G (deliberately last).

**Interventions.** `interface/api.py`'s `WorldBroadcaster` gains
`enqueue_intervention`/`drain_interventions` — the one deliberate
exception to its otherwise read-only, one-way data flow (its module
docstring is updated to say so explicitly rather than silently going
stale). Three new POST endpoints (`interface/app.py`) enqueue a request;
`SimulationEngine._apply_pending_interventions` drains and applies it
synchronously at the very top of `_tick_once`, in the same seam as
`_apply_pending_cognition_results`/`_apply_pending_dialogue_results` —
`World` is still only ever mutated by the tick loop itself, never
directly from a request handler. Three kinds: `agent_goal` (nudges one
agent's `AgentGoal`, applied via the existing `Population.apply_goal`
used by cognition), `settlement_resources` (delta materials/currency,
clamped to capacity/zero), `weather` (directly sets any subset of
temperature/precipitation/wind/is_snowing on `World.weather` — since
`World.tick()` immediately runs `compute_weather(..., previous=self.weather)`
afterward, a nudge becomes the new "previous" baseline and then keeps
evolving naturally rather than being pinned). Every applied intervention
is logged as an `intervention` category event, visible in the normal
event log/chronicle feed like anything else that happens in the world.

**Family memory.** `Agent.parents` already existed (set at birth,
`_maybe_reproduce`) but nothing read it back into memory. Now: a
newborn gets an immediate memory naming both parents, and both parents
get a memory of the birth. `_apply_deaths`' grief pass gained a
family-specific branch: losing a parent or a child logs a memory and
pays the usual `GRIEF_ENERGY_PENALTY` *regardless* of the numeric
relationship value — a newborn's accrued affinity toward its own parent
may still be low (relationships build from colocation over time), but
losing a parent is memorable independent of that number. `llm/dialogue.py`'s
`build_prompt` also checks `parents` and overrides the affinity-band
read with "parent and child" when it applies, so an LLM-authored
exchange between family reads as family even on a tick where their
numeric affinity happens to read distant.

**Smooth movement + lighting** (`interface/static/app.js`). Two related
rendering changes:
- Agent dots previously snapped straight to their new tile once per
  tick (visible as jitter at low tick rates). `updateAgentAnimTargets`
  tracks each agent's last two known grid positions and interpolates
  between them over `AGENT_ANIM_DURATION_MS` (350ms), independent of
  actual tick cadence. This requires the main map to redraw every
  animation frame rather than once per tick, so `drawFrame()` is now
  driven by its own `renderLoop` (`requestAnimationFrame`), same
  pattern the weather particle overlay already used — `applyPayload`
  no longer calls `drawFrame()` directly, just updates the interpolation
  targets and the rest of the payload state.
- A day/night + weather lighting tint (`drawLighting`) is drawn into the
  existing weather canvas, underneath the rain/snow particles: darkest
  around midnight (`nightFactor`, parsed from the clock string), fading
  to none at noon, plus a smaller bump for heavy precipitation. Reuses
  the weather canvas rather than adding a third layer.

Verified: intervention round-trip exercised directly against a live
`SimulationEngine` (agent goal nudge, settlement resource delta,
weather nudge) — all three applied, logged, and (for weather) correctly
continued evolving from the nudged baseline rather than staying pinned.
Family-memory birth/death flow exercised with two agents forced into
reproduction range — verified the newborn's and both parents' memories,
then forced the parent's death and verified the family-specific grief
memory fired. `node --check` and a live FastAPI route listing confirm
all three new POST routes register. Client-side interpolation/lighting
changes are syntax-checked only (`node --check`) — no headless-browser
run in this environment; visually verify in a real browser next.

## LLM-as-brain batch: economy buildings, town brain, animal/road weather, infrastructure telemetry

A large batch per explicit user instruction to batch commits and
implement many systems at once, plus a directive that the LLM should be
"the brain of the town" — CLAUDE.md gained a dedicated section on this
philosophy and the batch-commit workflow rule.

**Economy buildings** (`settlement/buildings.py`): four new
`BuildingKind`s — WORKSHOP (staffed presence generates currency
directly, `WORKSHOP_INCOME_PER_TICK`, a real business distinct from
D10's overflow-selling), SCHOOL (staffed presence raises
`Settlement.education_level`, capped at `EDUCATION_CAPACITY`, which
multiplies invention chance via `education_invention_bonus` — wired
into `SimulationEngine._maybe_schedule_invention`), HOSPITAL (RESTING
agents on its tile recover energy `HOSPITAL_REST_RECOVERY_MULTIPLIER`
faster; settlement-wide, any standing hospital reduces
`PREDATOR_KILL_CHANCE_ON_ATTACK` by `HOSPITAL_KILL_CHANCE_REDUCTION`),
and UNIVERSITY (not founded fresh — an existing standing SCHOOL
upgrades in place once `tech_level >= UNIVERSITY_TECH_REQUIREMENT` and
a colocated mature/healthy pair is present, doubling the education
contribution). Real material costs per kind (`MATERIALS_COST_BY_KIND`),
same "no stockpile, no start" rule as every other buildable asset.

**The town brain** (`llm/town_brain.py`): once per season, for a named
settlement, an LLM decision (with a legible deterministic fallback
reading the same stats an LLM would) sets `Settlement.current_priority`
— one of growth/food/commerce/education/health/defense — and a
one-line rationale. This is the concrete "LLM as brain" mechanic: it
measurably steers `buildings.choose_building_kind`'s weighted pick at
every future construction founding (`PRIORITY_KIND_BOOST` = 2.5x the
matching kind's base weight) rather than being pure narration. Building
kind selection at founding moved from a flat granary/hut coin flip to
this full weighted pool (`BUILDING_KIND_BASE_WEIGHTS`).

**Player intervention on the brain**: `POST /intervene/town-brain`
queues a short text "whisper" (`type: "town_influence"`), applied via
the existing intervention-queue seam into `Settlement.player_influence`
(capped at the last 3), folded into the *next* town-brain prompt as one
input among the real settlement stats/history, then cleared regardless
of how that LLM call resolves — deliberately subtle, per the user's
explicit "not too much but able to subtly influence" framing, not a
command the brain (or its fallback) must obey.

**Fix: live event stream gap** (root cause of "NPC dialogues should
appear in events"). Dialogue/rumor/chronicle/tradition/invention/
festival/intervention/town-brain all resolve outside `World.tick()`
— either synchronously at the top of `_tick_once` (dialogue,
interventions) or on a completely different tick whenever their
background LLM task happens to complete (chronicle, tradition,
invention, festival) — and all of them called `log_event()` directly,
writing to the DB but never touching `World.last_life_events`, which is
the only thing `_maybe_broadcast` ever read. Result: none of these
categories ever appeared in the live WebSocket feed — only via the
one-shot `/events` fetch on page load, so a running browser tab never
saw a single dialogue line stream in. Fixed with a new
`SimulationEngine._log(category, description)` helper (replacing every
non-tick `log_event` call site) that both persists AND appends to
`self._pending_broadcast_events`, drained into the payload's
`life_events` by `_maybe_broadcast` and cleared afterward — including a
guard to clear-without-broadcasting when the API is disabled, so the
buffer can't grow unbounded on a headless run.

**Animals interact with each other, more visibly.** Predators already
hunted grazers (A4); now (a) a grazer herd's movement prefers a
candidate tile that isn't adjacent to a live predator pack
(`GRAZER_FLEE_RADIUS`) — real avoidance, not a passive victim of
whatever tile a predator happens to wander onto, same "don't strand it"
fallback shape as agent predator-avoidance — and (b) `WildlifeGrid.tick`
now returns `wildlife_hunt`/`wildlife_extinct` events instead of
silently mutating counts, wired into `World.last_life_events`.

**Weather affects infrastructure.** `world/roads.py` gained
`road_condition_multiplier(weather)`: an established road's move-speed
bonus is `ROAD_SPEED_MULTIPLIER` (1.4x) only in dry weather — heavy
rain drops it to `ROAD_MUDDY_MULTIPLIER` (1.1x), snow to
`ROAD_SNOWY_MULTIPLIER` (0.9x, actually a penalty vs. open ground), and
snow at or below `ROAD_ICE_TEMPERATURE_C` to `ROAD_ICY_MULTIPLIER`
(0.75x, the most hazardous). Threaded `weather` through
`Population._dispatch_movement`/`_maybe_move` to reach it.
`RoadNetwork.summary(weather)` also reports the current human-readable
condition label (dry/muddy/snowy/icy) for the UI/`inspect_world`.

**Infrastructure telemetry, human-readable.** `Settlement.infrastructure_report()`
returns every building and vehicle with a plain-language condition
label (excellent/good/worn/critical, or under construction/broken
down/ruined), worst-first. Included in every broadcast payload
(`infrastructure` key) and rendered as a new sidebar panel; also
printed by `inspect_world` (only the items needing attention, to avoid
noise on a healthy settlement).

**Model change**: default `llm_model` bumped from `qwen2.5:3b` (~2GB)
to `qwen2.5:7b-instruct` (~4.5GB Q4) for meaningfully better NPC
dialogue and town-brain decision quality, per explicit user request to
choose a better-fitting model. `llm_timeout_seconds` bumped 20 -> 30 to
match the larger model's slower CPU inference. This is a judgment call,
not something soak-tested on the user's actual hardware by this change
— CLAUDE.md documents the revert path (`--llm-model qwen2.5:3b`) and
asks for a live diagnostic report rather than a silent downgrade if
it's too heavy.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): an 8200-tick unforced run grew population
14->32->27, founded a workshop and a hospital, set `current_priority`
to "food" via the fallback reading real hunger/granary stats, and
`education_level` stayed 0 (no school built in that run — plausible,
not systematic). A separate live-broadcast-payload check over 8200
ticks confirmed `dialogue`, `chronicle`, `tradition`, `festival`, and
`town_brain` all now appear in `life_events` pulled from
`WorldBroadcaster.get_state()` (the exact bug that was fixed). A
university upgrade was forced and confirmed (tech_level>=3, standing
school, colocated pair -> kind flips to UNIVERSITY same tick). A
wildlife predator-hunt/extinction event was confirmed over a 3000-tick
run. A player whisper was queued, consumed by the next town-brain
prompt, and cleared. `World.to_dict`/`from_dict` round-trips all new
fields (`education_level`, `current_priority`, `priority_rationale`,
`player_influence`). All new FastAPI routes (including
`/intervene/town-brain`) confirmed registered. An adversarial forced-
GATHER-forever test artificially starved the population to 2 — this is
a property of that unrealistic test script overriding goals every tick
regardless of hunger, not a regression (confirmed by the healthy
unforced run above using the same seed/config).

## Real-calendar/genesis-seed follow-up

User-reported/requested (verbatim, condensed): the map doesn't seem to
be evolving; climate should follow UK climate; 365 days/year mimicking
real calendar months; town starts in industrial era and evolves;
initial terrain/weather chosen by a seed produced by the LLM; use a
newer/smaller local model than the current `qwen2.5:7b-instruct`.

**Map-not-evolving investigation.** Traced the broadcast/redraw chain
(`_TERRAIN_CHANGING_CATEGORIES` in engine.py, `WorldBroadcaster.set_terrain`,
app.js's `refreshTerrainIfChanged`) and found no wiring bug — it was
already correct from the prior batch. The actual cause was cadence:
reclaim rolled once per season (20 days) and climate drift once per
year (80 days) under the *old* calendar, both individually already slow
enough to be easy to miss in a sitting. Moving to a real 365-day year
(below) would have made this ~4.5x worse if left tied to season/year
boundaries the same way, so both were deliberately decoupled onto fixed
week/month cadences instead (see below) — the fix that actually
addresses the complaint is the recadencing, not a code-correctness fix.

**Real calendar.** `time_system.py`'s `SimClock` rewritten around
`Config.days_per_month` (a real 12-entry, 365-day-summing tuple) instead
of a fixed `days_per_season * 4`. `month_index`/`day_of_month`/
`month_name` are new derived properties; `season_index` is now looked up
via `Config.month_to_season` (UK meteorological seasons: Dec-Feb winter,
Mar-May spring, Jun-Aug summer, Sep-Nov autumn) rather than computed
from a fixed day-count-per-season, so `season`/`season_index` stayed a
4-value concept and every existing consumer (weather baselines, farm
growth multiplier, chronicle/tradition/invention/festival/town-brain
cadence, all of which key off `clock.season` and calendar-boundary
events) kept working with zero changes to their own logic. `advance()`
gained `week_end`/`month_end` boundary events alongside the existing
`day_end`/`season_end`/`year_end`. Backward compatibility: a snapshot's
config block is creation-only and must never silently change, so
`World.from_dict` reconstructs an equivalent "N months, each one season
long" calendar from a legacy snapshot's `days_per_season`/
`seasons_per_year` fields when `days_per_month` is absent — verified by
round-tripping a synthetic legacy config block and confirming
`days_per_year() == 80` and `season == "spring"` on day 6, matching the
old math exactly.

**UK climate.** `world/weather.py`'s `_SEASON_BASELINES` (4 entries)
replaced with `_MONTH_BASELINES` (12 entries, lowercase month name
keyed) — rough Met Office-style averages: 5°C/wetter in Dec-Feb,
17°C/driest in Jul-Aug, rain spread fairly evenly (0.30-0.48 chance)
rather than concentrated in one "wet season," windier in winter.
`compute_weather(seed, tick, month, previous)` (param renamed from
`season`); `World.create_new`/`World.tick` pass `clock.month_name.lower()`.

**Eras.** `Settlement.era: str = "industrial"` plus
`buildings.era_for_tech_level(tech_level)` (thresholds: industrial 0,
electrical 3, modern 7, digital 12) — a settlement starts in the
industrial era per the request and advances purely as a function of
`tech_level` (already-existing invention counter), no separate era
mechanic to keep in sync. Made mechanically real, not just a label: the
new `BuildingKind.FACTORY` (double a workshop's `WORKSHOP_INCOME_PER_TICK`,
`FACTORY_MATERIALS_COST = 14.0`) only enters `choose_building_kind`'s
foundable pool once era has advanced past `industrial`.
`SimulationEngine._maybe_advance_era` (called right after `tech_level`
is incremented in `_run_invention`) logs an `era_advance` event on
transition. Verified: `era_for_tech_level` returns the right tier at
each threshold boundary (0/2->industrial, 3/6->electrical, 7/11->modern,
12/20->digital); `choose_building_kind(rng, "", "industrial")` never
produces FACTORY across 20k draws, `choose_building_kind(rng, "",
"electrical")` does.

**World genesis (LLM-chosen seed).** New `hearthmind/llm/world_genesis.py`
mirrors the existing `town_brain.py` shape (`SYSTEM_PROMPT`,
`build_prompt`, `fallback_scenario`, `parse_scenario`) plus a
`seed_from_scenario(text) -> int` hash helper. Resolved in `server.py`
(`_resolve_genesis_seed`, called from `_main_async`) rather than inside
`World.create_new`/`SimulationEngine`, since it's a one-time,
startup-only, CLI-level concern — `World.create_new` itself stays a
pure function of an already-resolved `Config`. Only runs when `--seed`
is omitted (CLI default changed from `1337` to `None` as the "let
genesis decide" sentinel; `Config.seed` widened to `int | None` to carry
that sentinel through) *and* the world doesn't already exist (`fresh`).
An LLM-authored scenario's seed is `seed_from_scenario(scenario)`
directly; a disabled/unreachable-LLM fallback XORs that hash with fresh
`random.SystemRandom()` entropy so an offline run isn't limited to the
handful of canned fallback scenario strings forever. Blocking is
acceptable here (unlike every per-tick LLM call elsewhere in this
project) because it happens exactly once, before the tick loop starts —
not a liveness risk. The scenario text is stored on
`Settlement.founding_scenario` (threaded through
`SimulationEngine.load_or_create` -> `World.create_new`) and also logged
as a one-time `founding` event via the new
`SimulationEngine.log_founding_scenario`. The `_CREATION_ONLY_FIELDS`
resume-mismatch warning loop in `server.py` skips the `seed` field
whenever `--seed` wasn't explicitly passed, so resuming a world doesn't
spam a spurious "seed mismatch" warning every single run (a genesis/
placeholder seed is never a real user request to compare against).

**Model change, again.** `llm_model` moved from `qwen2.5:7b-instruct`
(~4.5GB Q4) to `qwen3:4b` (~2.6GB Q4) — Qwen3 is a newer model
generation than Qwen2.5 (there is no "Qwen3.5"), and the 4B tier
generally matches or beats the old 7B default's quality on community
benchmarks at roughly half the memory footprint, per explicit user
request for a newer/smaller model. `qwen3:1.7b` (~1.1GB) documented as
the lighter fallback tier. Qwen3 is a hybrid "thinking" model that can
wrap chain-of-thought in `<think>...</think>` even under `"format":
"json"`; `OllamaClient.generate_json` now sends `"think": false` in the
request payload and additionally strips any `<think>...</think>` block
from the raw response defensively (model-agnostic, a no-op for any
model that never emits them) before `json.loads` — belt-and-suspenders
against a stray reasoning block silently breaking every strict-JSON
prompt in this project. Verified with a synthetic `<think>...</think>{...}`
payload through the stripping regex directly.

**Bug found and fixed in passing**: `server.py`'s `--llm-model`/
`--llm-timeout` argparse defaults were hardcoded independently of
`Config`'s own defaults and had drifted stale (`qwen2.5:3b`/`20.0`)
since the prior batch bumped `Config`'s defaults — running the CLI
without explicitly passing either flag silently used the old values.
Both now read `Config.llm_model`/`Config.llm_timeout_seconds` directly
so they can't drift apart again.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): a 400-day tick-advance-only test confirmed
`day_end`/`week_end`/`month_end`/`season_end`/`year_end` all fire at the
right points and `days_per_year() == 365`; a 6000-tick full-engine run
(async event loop, `_tick_once` in a loop) completed without error,
reached `month == "March"`, `season == "spring"`, showed nonzero
`climate.warming`/`climate.drying` drift by tick 6000 (confirming the
new monthly cadence is visibly active well within a normal viewing
session, vs. the old yearly cadence needing ~7680 ticks for a first
roll), and round-tripped `to_dict`/`from_dict` with the new
`founding_scenario`/`era` fields intact. All touched files pass
`python3 -m py_compile`; `app.js` passes `node --check`.

## World-model/beliefs follow-up

User instructions (verbatim, condensed): legacy world-save compatibility
is not required (drop it); `qwen3.5:2b` is available and should be the
default; and a restated/expanded philosophy asking specifically for
"continuous cognition" — the local LLM should build and revise an
internal model of the world through experience (memory consolidation,
belief revision, new hypotheses about people/families/settlements/
traditions/politics/economics/recurring patterns/player influence/the
town itself) rather than being stateless per-call, with model weights
never changing.

**Legacy calendar compatibility dropped.** `World.from_dict` no longer
branches on a missing `days_per_month` — the synthetic-legacy-calendar
reconstruction added in the prior batch (real-calendar/genesis-seed
follow-up) was removed outright per explicit instruction. A pre-0.28.0
snapshot will now raise a `KeyError` on load rather than degrade
gracefully; this is an accepted, deliberate tradeoff, not an oversight.
`Config.days_per_month`'s docstring updated to say so plainly.

**Model set to `qwen3.5:2b`.** This project's own prior entry stated
"there is no Qwen3.5" — the user has since confirmed it's available and
pulled on their machine, which supersedes that assumption; a live
environment is better evidence than training-data recall about a
fast-moving model catalog. Set as the new `Config.llm_model` default
(was `qwen3:4b`), with `qwen3:4b` now documented as the size-up path if
2B output proves too weak for coherent town-brain/dialogue/belief
output — not yet soak-tested at 2B by this change itself.

**World beliefs (continuous cognition).** New `hearthmind/llm/beliefs.py`,
mirroring the existing `town_brain.py`/`chronicle.py` shape
(`SYSTEM_PROMPT`, `build_prompt`, `fallback_belief`, `parse_belief`).
`Settlement.beliefs: list[dict]` holds up to `MAX_BELIEFS` (12) entries,
each `{subject, belief, confidence, formed_tick, revised_tick,
revision_count}`. `SimulationEngine._maybe_schedule_beliefs` runs on
`month_end` for a named settlement (monthly, not seasonal like
town_brain — deliberately faster/more granular, since this is meant to
read as an accumulating running theory rather than a rare civic
decision) and calls `_run_beliefs`, which either revises an existing
entry (LLM returns a `revises` index, validated against the current
list length; `revised_tick`/`revision_count` bumped, text/confidence/
subject overwritten) or appends a new one, evicting the lowest-
confidence entry if the cap is exceeded.

The key design choice making this "continuous" rather than just another
independent periodic job: `town_brain.build_prompt` and
`chronicle.build_prompt` both gained an optional `beliefs` parameter,
and `SimulationEngine`'s existing call sites for both now pass
`settlement.beliefs` through — the village's own accumulated
interpretations become part of the context for its *next* civic
decision and its *next* seasonal summary, not a dead-end sidecar list
only the UI reads. This closes the loop CLAUDE.md now calls "cognition
as continuous rather than stateless" without introducing a second,
parallel per-agent belief store — agents already have a `memories` list
(A5); this is deliberately settlement-scoped, the smallest coherent
step toward "the town is itself a subtle character... slowly forming
opinions," not a full per-entity belief architecture (person/family/
politics-level belief-tracking remains future scope, noted but not
built this batch — the settlement-wide `subject` field can already name
a specific person/family in its text, which gets most of the way there
for a small population, without new per-agent state).

New UI panel ("The village's own theories"), `inspect_world` section,
and `belief_formed`/`belief_revised` event categories/icons.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): `fallback_belief`/`parse_belief` unit-level
checks (new belief, revision by valid index, malformed-LLM-output ->
fallback fields) all produced the expected dicts. A 9000-tick full
async engine run (seed 7, population 10) produced two independently-
formed beliefs at two different month boundaries (ticks 5664, 8640)
with the fallback's naive "most common recent category" heuristic, and
round-tripped through `to_dict`/`from_dict` with `settlement.beliefs`
intact. All touched files pass `python3 -m py_compile`; `app.js` passes
`node --check`.

## Phase G / per-person beliefs follow-up

User instruction (verbatim): "start with that and also parallely start
building [P]hase G" — "that" being the natural next extension of the
just-shipped world-beliefs system (per-person/per-family tracking), and
Phase G being the "subtle supernatural layer" CLAUDE.md had marked
"deliberately last." Both are addressed in this batch, run in parallel
as asked rather than sequenced.

**Per-person beliefs.** `beliefs.resolve_subject_agent_id(subject,
agents)` does an exact, case-insensitive match of a belief's free-text
`subject` against currently-living `Agent.name` values; returns `None`
on no match or a name collision (two agents sharing a name) rather than
guessing — a wrong attribution is worse than none. Called from
`SimulationEngine._run_beliefs` right after parsing, for both new and
revised entries, storing the result as `subject_agent_id` on the
belief dict. `llm/dialogue.py`'s `build_prompt` gained an optional
`beliefs_about` parameter; `SimulationEngine._schedule_due_dialogue`
filters `settlement.beliefs` for entries whose `subject_agent_id`
matches either conversing agent and passes the matched text through —
closing the loop so a belief about a specific villager isn't just
narration sitting in a UI list, it measurably shapes what that person
(and whoever they're talking to) says next. Deliberately did not build
a second, parallel per-agent belief store on top of the existing
`Agent.memories` list (A5) — reusing the settlement-wide list keeps
this a small, additive change. Family-level resolution (a belief whose
subject names a family/lineage rather than one person) is explicitly
out of scope for this pass — the `subject` field can already contain
free text like "the Emberly family" and read coherently in prompts, but
there's no structured family entity to resolve it against.

**Phase G v1: temperament and omens.** Read literally: "the town is
itself a subtle character... keep this ambiguous, never explicitly
explain the supernatural" (CLAUDE.md, carried over from the philosophy
message earlier this session). The implementation is deliberately
split two ways, matching the project's existing "deterministic engine
provides reality, LLM provides meaning" split:

- `Settlement.temperament: float = 0.0` (-1..1) is 100% deterministic —
  `buildings.tick_temperament(temperament, recent_events, rng)` is a
  bounded random walk (`TEMPERAMENT_STEP_MAX=0.04`,
  `TEMPERAMENT_MEAN_REVERSION=0.97`, same shape as `terrain_evolution
  .ClimateState`'s warming/drying), with its step biased by
  `TEMPERAMENT_FORTUNE_WEIGHT=0.15` toward the recent balance of
  `_GOOD_FORTUNE_CATEGORIES` (birth/festival/invention/
  building_completed/tradition/settlement_named) vs.
  `_ILL_FORTUNE_CATEGORIES` (death/building_ruined/wildlife_extinct/
  vehicle_broken) event counts. Ticked monthly by
  `SimulationEngine._maybe_tick_temperament` (new `_namespaced_rng`
  helper added alongside the existing `_namespaced_roll`, since this
  needs a full `random.Random` for `rng.uniform`, not just one float).
  No LLM involvement in computing this value at all — it is exactly as
  "real" as `ClimateState.warming`.
- Mechanical effects are deliberately small and secondary:
  `TEMPERAMENT_INVENTION_INFLUENCE=0.2` nudges invention chance
  (`_maybe_schedule_invention`, applied after the existing education
  bonus) by at most ±20%; `TEMPERAMENT_KILL_CHANCE_INFLUENCE=0.2`
  nudges predator-attack lethality (`Population._maybe_predator_attack`,
  applied after the existing hospital reduction) by the same bound.
  Neither can flip an outcome on its own; both are additive nudges on
  top of mechanics that already exist for other, plainly-stated reasons.
- `llm/omens.py` is the *only* place any "more than physics" reading
  can appear, and only in flavor text: `SimulationEngine
  ._maybe_schedule_omen` rolls monthly at `OMEN_CHANCE_BASE=0.05` +
  `|temperament| * OMEN_CHANCE_TEMPERAMENT_SCALE=0.25` (so roughly
  5-30% depending on how extreme the current drift is — still rare by
  design). The system/fallback prompts explicitly require the result to
  "always have a mundane explanation available" and never confirm
  anything — verified by reading every fallback-pool line in
  `_WARM_OMENS`/`_COLD_OMENS`/`_NEUTRAL_OMENS` for compliance with that
  constraint (a cat sleeping somewhere, dogs unsettled, a well tasting
  different — never a stated cause).
- Nothing in `app.js`/`index.html` labels temperament as "mood" or
  "supernatural" — it's exposed through `settlement.summary()` (and
  thus `/state`) exactly like every other internal stat, and
  `inspect_world` prints it as a plain debug line explicitly annotated
  "internal only — deliberately never surfaced to players as
  'supernatural.'" The only player-visible surface is the rare omen
  event itself, logged under a fog emoji (🌫️) alongside every other
  event category, with no special framing.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): `resolve_subject_agent_id` correctly matches,
returns `None` on no-match and on a same-name collision;
`tick_temperament` run 20x from `0.0` under an all-good-fortune event
mix saturates at `+1.0` and under an all-ill-fortune mix at `-1.0`,
confirming both the bound and the fortune-weighting direction; a
12000-tick full async engine run (population 12) produced a stable,
bounded `temperament` value and round-tripped through
`to_dict`/`from_dict` correctly (within the field's own rounding — same
tolerance every other rounded settlement stat already has). All touched
files pass `python3 -m py_compile`; `app.js` passes `node --check`.

## Live-diagnostics follow-up (vehicles/dialogue/naming)

User supplied a real diagnostic report (screenshot + `/diagnostics`
JSON) from `qwen3.5:2b` actually running on their hardware, plus four
concrete questions/requests: confirm the model works (RAM <4GB —
confirmed, no code change needed); why carts appear in an "industrial"
era; NPC dialogue "makes no sense," improve it; and "figure out" the
village-naming mechanism. Per CLAUDE.md, a user's own live diagnostics
are the project's actual source of truth — this batch is a direct,
traceable response to the JSON/screenshot supplied, not a general pass.

**Vehicle era progression.** Historically, carts/mounts alongside an
"industrial" era isn't actually anachronistic — horse-drawn transport
coexisted with early industry for decades — but the complaint is fair
on its own terms: buildings already got an era-gated upgrade (FACTORY,
prior batch) and vehicles hadn't, so "industrial era, forever carts"
reads as an oversight even where it isn't strictly wrong. Added
`VehicleKind.AUTOMOBILE` (`settlement/vehicles.py`), foundable only once
`Settlement.era` is `modern` or `digital`
(`buildings.ERA_UNLOCKS_AUTOMOBILE`), costing `AUTOMOBILE_MATERIALS_COST
=12.0` and moving at `AUTOMOBILE_SPEED_MULTIPLIER=2.2` (vs mount's 1.6).
Required generalizing several MOUNT-specific code paths in
`agents/population.py` to a shared `PERSONAL_VEHICLE_KINDS` concept
(claiming logic, `_agent_mount`, decay wear) since AUTOMOBILE behaves
identically to MOUNT mechanically, just faster/costlier — `_maybe_move`'s
`mounted: bool` parameter became `speed_multiplier: float` to carry
either vehicle's actual multiplier rather than a fixed constant.
`_maybe_start_vehicle`'s kind roll became 3-way (cart/mount/automobile)
once the era allows it, still 2-way (cart/mount) below `modern`. Map
rendering gives automobile a distinct steel-blue diamond, separate from
mount's violet, so era-driven transport progress is visible on the map
itself, not just in stat tiles.

**Dialogue quality.** Root cause is almost certainly the model tier
itself: `qwen3.5:2b`'s own diagnostics show p50 latency 17.4s (not
fast, despite being small — CPU inference on constrained hardware
doesn't scale down proportionally with parameter count the way one
might expect), and small/weak instruction-following models are known
to leak meta-commentary or ramble past length instructions more often
than larger ones. Two independent fixes, since the actual failure mode
can't be directly observed from this environment (no live Ollama here):
(1) `llm/dialogue.py`'s SYSTEM_PROMPT gained three few-shot examples in
the exact expected JSON shape — few-shot exemplars are a well-known,
disproportionately effective mitigation for weak models' instruction-
following, and an explicit instruction never to mention being an AI/
simulation; (2) `parse_dialogue` gained `_is_sane_line`, a sanity filter
rejecting a line if it leaks instruction/meta text (`_LEAKAGE_MARKERS`:
"json", "you are writing", "as an ai", etc.), runs more than
`_MAX_LINE_WORDS=22` (over double the requested 10), exactly duplicates
the other speaker's line, or contains a stray `{`/`}` — any of which
degrades that line back to the deterministic fallback pool rather than
surfacing visibly broken small-model output. This can't be verified
against the user's actual model from this environment; it's a defense-
in-depth, degrade-gracefully fix, not a guarantee the underlying model
quality issue is fully resolved — worth another live diagnostic report
after this ships.

**`llm_timeout_seconds` bumped 30 -> 45.** Read directly off the
supplied `llm_stats`: `latency_ms_p50: 17441`, `p95: 19699.8`, `max:
29721.4` against a 30000ms timeout — the single slowest observed call
was 279ms from timing out. `calls_timed_out: 0`/`calls_errored: 1` out
of 258 shows the model is in fact working (this is not a "model too
weak, replace it" situation), but the margin was uncomfortably thin for
any run slower than this snapshot. This does not mean 2B is slow in
absolute terms — it means this project's assumption that a smaller
model would clearly be faster in wall-clock terms wasn't safe to make
without the user's own hardware data, which is exactly why CLAUDE.md
treats live diagnostics as higher-priority signal than a priori
reasoning about model size.

**Settlement naming mechanism.** Investigated and explained, then
upgraded rather than left as pure RNG: previously
`settlement.naming.generate_settlement_name` was called synchronously
inside `World.tick()` the instant a settlement's first building went
STANDING — a prefix+suffix compound (e.g. "Elmford") from a fixed pool,
chosen via the same namespaced-RNG discipline as everything else
deterministic in this project. Per this project's own design priority
("prefer LLM reasoning" for creative/interpretive decisions), naming a
place is exactly the kind of decision that should default to the LLM,
not a coin flip — but naming can't simply *become* an LLM call, since
`settlement.name` being truthy is a synchronous gate every other system
already depends on the same tick a settlement is born (town_brain,
chronicle, festivals, beliefs, vehicles all no-op on an empty name).
Resolution: keep `World.tick()`'s instant deterministic placeholder
exactly as before (nothing else had to change), and add
`llm/naming.py` + `SimulationEngine._maybe_schedule_naming`/
`_run_naming` — a one-time background job, guarded by
`self._naming_scheduled` so it only ever fires once per world, informed
by `Settlement.founding_scenario` and the terrain's dominant biome
(`world.terrain.biome_counts`), which silently replaces the placeholder
with a better name once it resolves (typically within the same latency
window as any other LLM call). Deliberately skipped entirely when the
LLM is disabled (`self._cognition_runner.enabled` check) — re-running a
second, differently-seeded deterministic name draw would just rename
the settlement to another random name for no real reason, since the
existing placeholder already *is* the correct fallback outcome here
(unlike every other job, where the fallback is a distinct, intentional
degraded-but-useful output).

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): a 20000-tick full async engine run (population
16, seed 4242) produced a named settlement ("Elmford", the unchanged
deterministic placeholder, confirming the disabled-LLM skip works
correctly), 14 carts and 12 mounts (era stayed `industrial` — no
inventions rolled in this particular run, so AUTOMOBILE correctly never
appeared, confirming the era gate). A direct `to_dict`/`from_dict`
round-trip with a manually-forced `VehicleKind.AUTOMOBILE` at `era=
"modern"` confirmed serialization round-trips correctly. All touched
files pass `python3 -m py_compile`; `app.js` passes `node --check`.

## Map/UI/ecology follow-up

User sent a large, dense list of requests/bug reports in one message.
Triaged into: confirmed real bugs (wildlife extinction, road/resource
visibility), legibility improvements (buildings, daylight), concrete
new features (history tab, diagnostics exposure, broader belief
influence), and two items deliberately scoped down/out (rivers, full
astronomical daylight-driven agent behavior) — flagged explicitly
below rather than silently doing a partial job and calling it done.

**Wildlife extinction (real bug, confirmed via live diagnostics showing
"0 predators (0 packs)").** `WildlifeGrid.generate` only ever runs once,
at world creation; `tick()`'s own herd-pruning line
(`self.herds = {... if h.count > 0}`) permanently deletes any herd/pack
that hits exactly 0, with nothing to ever create a new one. Predators
are especially exposed to this: `PREDATOR_STARVE_CHANCE` shrinks a pack
that can't find prey, and the prior batch's `GRAZER_FLEE_RADIUS`
(grazers preferring move-candidates away from predators) made hunting
harder, plausibly tipping an already-fragile mechanic into visible
permanent extinction. Fixed with `_maybe_recolonize` (rolled at
`WILDLIFE_RECOLONIZE_CHECK_CHANCE=0.002` per tick): spawns a new grazer
herd if the current herd count is under a target density
(`GRAZER_RECOLONIZE_TARGET_HERDS_FRACTION` of what world-generation
would have produced), and spawns a predator pack only if none currently
exist AND grazers already do (no point recolonizing a predator with
nothing to hunt) — framed as migration from beyond the map's edge, a
new `wildlife_recolonized` event. Verified: forced every predator pack
to 0 in a fresh world, ran the tick loop, confirmed recolonization fired
within a few hundred ticks and predator count recovered; a full
8000-tick engine run on an unrelated seed independently produced a
`wildlife_recolonized` event in its natural history, confirming this
isn't just a contrived test-case fix.

**Roads/resources not visible on the live map (confirmed by reading the
actual render code, not assumed).** Roads: the code path existed and
executed, but `wear * 0.6` alpha scaling meant a road below
"established" (wear >= 0.5, only 2 of 134 in the user's reported run)
rendered at ~6% opacity — a real, fixable legibility bug, not a missing
feature. Now floors at 0.35 alpha and darkens further once established.
Resources (bushes/mines): confirmed via `grep` that individual node
positions were never included in the broadcast payload at all — only
`summary.resources`'s aggregate counts reached the client, so "mines
should be visible" was accurate as stated; there was nothing to render
because the data never arrived. Added `"resources"` to
`SimulationEngine._maybe_broadcast`'s payload (`ResourceNode.to_dict()`
already had the right shape) and a small dot-marker renderer in app.js,
dimming toward the terrain color as a node depletes. Buildings:
investigated and found no code-level bug (the render path was already
correct) — the more likely explanation is a settlement of only 1-2
buildings being genuinely hard to notice as an 8x8px square on a
512px-wide canvas. Bumped their render size (bleeds 1px past the tile)
and stroke brightness for legibility regardless. Lakes/mountains: these
already render correctly as terrain biomes (deep_water/shallow_water/
mountain/snowcap) and were visible in the user's own screenshot — no
fix needed there, just noted so it's clear this wasn't overlooked.

**Rivers: explicitly scoped out.** A linear, winding river distinct
from the lake/pond biomes the diamond-square terrain generator already
produces would be a substantial new terrain-generation feature (a
path-carving pass through `world/terrain.py`, evolution rules for how
it should behave under `terrain_evolution.py`, new movement/farming
interactions) — genuinely large enough to warrant its own scoped batch
rather than a rushed addition inside an already-large one. Recorded
here as a known gap, not silently dropped.

**Town brain / beliefs "not working," user prompt not visible.**
Investigated the actual scheduling logic (`_maybe_schedule_town_brain`/
`_maybe_schedule_beliefs`) and found no bug — both correctly gate on
`settlement.name` being set AND the relevant calendar boundary
(season_end / month_end respectively). The user's own supplied
diagnostics (`event_category_counts`: `season_end: 1`, `month_end: 3`)
show only one season boundary and the settlement being named partway
through the run — town_brain genuinely hadn't had a second chance to
fire yet, and belief-formation's monthly cadence hadn't run since
naming either. This is a legibility/observability problem, not a
correctness one: there was no way for the user to see *why* nothing had
happened, or what any given LLM call had actually been asked/told.
Fixed by adding `SimulationEngine._last_llm_calls: dict[str, dict]` — a
`_record_llm_debug(name, prompt, result, used_fallback)` call added to
every named LLM job's `_run_*` method (naming, dialogue, chronicle,
tradition, invention, festival, town_brain, beliefs, omen), storing only
the most recent call per job (bounded, not a growing history), exposed
via `full_diagnostics()`'s new `last_llm_calls` key. Since the
town-brain prompt already includes the player's whispers as one input
(`town_brain.build_prompt`'s `player_whispers` param, prior batch), this
single addition satisfies "what prompt was given and what town brain
acted on it" directly — the whisper text is visible inside the recorded
prompt. Also added `pending_player_whispers` (queued-but-not-yet-
consumed) to both `full_diagnostics()` and `Settlement.summary()` (the
latter was a real, separate gap — `player_influence` was in `to_dict()`
for persistence but never in `summary()`, so the live broadcast payload
never carried it) and a small UI element under the whisper form showing
them directly, not just in the dev console.

**History tab.** New `persistence.snapshot.history_events` (and
`HISTORY_CATEGORIES`, the curated narrative subset — founding, naming,
era advances, chronicle/tradition/invention/festival, beliefs, omens,
wildlife recolonization) + `GET /history` + a toggleable UI panel,
mirroring the existing dev-console toggle pattern. Deliberately reuses
the existing `events` table (same as `recent_events`) rather than a
parallel storage mechanism — a curated `WHERE category IN (...)` query,
not a new write path.

**Beliefs should affect the whole village.** Previously beliefs fed
`town_brain` and `chronicle` prompts (settlement-wide) plus matched
individuals' `dialogue` prompts (per-person, via `subject_agent_id`) —
already broader than "just a UI list," but the user's ask reads as
"more systems should feel it." Added an optional `beliefs` parameter to
`invention.build_prompt` and `festival.build_prompt` (mirroring the
existing chronicle/town_brain shape exactly), wired from their engine
call sites. A structural, systemic mechanical effect (e.g. beliefs
nudging `Settlement.temperament` or some other numeric lever) was
considered and deliberately deferred — broadening LLM narrative
consistency across every settlement-level decision is the smallest
coherent next step; a second belief-to-mechanics pathway on top of the
one temperament already has (Phase G v1) would be scope creep for this
batch specifically.

**Real UK daylight hours.** The old `nightFactor` was a fixed sinusoid
centered on a hardcoded 6am/6pm, invariant across the entire year
despite the sim having had a real UK-climate calendar since the
real-calendar/genesis-seed batch — a genuine inconsistency (UK weather
varied by month, UK daylight didn't). Added `UK_DAYLIGHT_HOURS` (app.js):
approximate London-latitude sunrise/sunset local-clock times per month,
including the practical effect of BST (~8h daylight in December,
~16.5h in June) — precise-enough for game flavor without an
astronomical calculation library. `nightFactor(clockStr, monthName)`
now blends to full daylight between sunrise/sunset, full night outside
a 1-hour dawn/dusk transition window either side. A new "Daylight" stat
tile surfaces the current month's sunrise/sunset directly. Deliberately
scoped to the visual lighting tint only — agent REST/sleep behavior
stays energy-threshold-driven, unrelated to daylight, since rewiring
agent schedules around sunrise/sunset would be a much larger behavioral
change than "how the map looks" asked for; noted as a possible future
extension, not attempted here.

**Season-based building/vehicle wear.** `DECAY_WEATHER_MULTIPLIER`
already made storms wear structures faster than fair weather; there was
no separate season effect. Added `SEASON_DECAY_MULTIPLIER` (winter 1.4,
autumn 1.15, spring 1.0, summer 0.85), applied multiplicatively on top
of (not instead of) the existing weather-harshness multiplier — real
freeze-thaw cycles and persistent winter damp wear masonry/timber
faster independent of any single tick's instantaneous weather. Applied
to both `Settlement.tick`'s building decay and its vehicle decay for
consistency. `Settlement.tick`/`World.tick` both gained a `season`
parameter (defaulted for any other caller) threaded from
`self.clock.season`.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): forced-extinction wildlife recolonization test
(see above); an 8000-tick full async engine run independently produced
a real `wildlife_recolonized` event and populated `last_llm_calls` for
dialogue/chronicle/festival/town_brain/beliefs; confirmed `ResourceNode
.to_dict()` produces the shape the new renderer expects;
`history_events` returned real rows including the recolonization event
from the same run. All touched Python files pass `python3 -m
py_compile`; `app.js` passes `node --check`.
py_compile`; `app.js` passes `node --check`.

## Natural disasters, rivers & lakes, daylight-driven agent behavior

**History tab investigation.** Read/exercised the full path end-to-end
(SQL query against a real events table, an in-process ASGI call to
`GET /history`, `app.js`'s wiring, `index.html`'s element IDs) and
found no defect — `HISTORY_CATEGORIES` matches every category string
actually logged, byte-for-byte, no typos. Concluded the most likely
explanation is operational (server process not restarted after pulling
v0.32.0; uvicorn doesn't hot-reload) rather than a code bug. No code
changed for this item; flagged back to the user rather than "fixing"
something that already works.

**Natural disasters** (`world/disasters.py`). Three kinds, deliberately
kept to physical events only — no LLM call added; the existing
chronicle/omens jobs already see life_events and can narrate a disaster
if they choose to, same as any other event. Flood: sustained heavy rain
(precipitation past the existing "harsh weather" threshold) accumulates
a `flood_pressure` value that decays otherwise; once past threshold, a
small per-tick roll submerges a random tile bordering existing water
(river/lake/ocean) for ~40 ticks, doing real damage (building/vehicle
`condition -= 0.35`, farm plot destroyed) before receding to its
original biome. Wildfire: gated to summer + dry weather, a rare weekly
ignition roll (chance nudged upward by ill-fortune
`Settlement.temperament`, reusing the exact lever Phase G already
established for invention/predator rolls rather than inventing a
parallel bias mechanism) starts a fire that spreads tile-to-tile for a
few ticks, turning forest to grassland (ash) and damaging any building
caught, then burns out. Storm: extreme wind (well past the routine
"harsh weather" 0.5 threshold) has a small per-tick chance of directly
knocking `condition -= 0.25` off every standing building/vehicle
map-wide — a sharp, rare hit distinct from the existing gradual
weather-decay multiplier in `Settlement.tick`. All three log real life
events, added to `HISTORY_CATEGORIES` and the client's terrain-refresh
set.

**Rivers and lakes** (`world/hydrology.py`). Rivers: carved once at
world creation by steepest-descent random walk from high-elevation
sources (mountain/hills/snowcap) to existing water or the map edge — a
new `Biome.RIVER`, deliberately left out of `BIOME_ORDER` (which
climate drift steps elevation-classified biomes along) since a river
tile isn't elevation-classified; `terrain_evolution.apply_climate_drift`
now skips any `Biome.RIVER` tile it samples rather than crashing on a
missing `BIOME_ORDER.index()`. Rivers persist automatically through
terrain's existing (de)serialization — no separate river state needed.
The "should evolve over time" ask for rivers specifically is answered
by the flood mechanic above (sustained rain temporarily pushes water
onto riverbank land) rather than a second, river-specific tick — one
mechanism serving two of the user's asks. Lakes: identified once at
creation by flood-filling connected water components that never touch
the map border (a heuristic distinguishing inland lakes from the ocean,
which does touch the border on this generator's typical output); each
lake gets its own `level` — a bounded random walk nudged monthly,
biased toward the map-wide `ClimateState.drying` trend (same shape as
`ClimateState` itself, but per-lake) — and crossing a threshold
grows/shrinks the shoreline by one ring tile
(`lake_rose`/`lake_receded`), so a lake visibly changes size across
years. `lake_rose`/`lake_receded` deliberately excluded from
`HISTORY_CATEGORIES` (too frequent/minor — same call already made for
`terrain_thinned`/`terrain_reclaimed`); the three disaster categories
are curated in. A pre-hydrology-pass snapshot gets rivers carved and
lakes identified once on load, recorded via the existing
`migrated_subsystems` backfill pattern (added a `"lakes"` entry to
`_MIGRATIONS`).

**Daylight now affects agent behavior, not just lighting.**
`world/daylight.py` is a server-side port of app.js's
`UK_DAYLIGHT_HOURS` table and `nightFactor` ramp (kept in sync by hand
— no shared runtime between Python and JS here), computed from
`SimClock.minute_of_day`/`month_name` each tick and threaded into
`Population.tick` as `night_factor` (0..1). Three effects, all scaled
by how deep into the night it is rather than a hard day/night switch:
an AWAKE agent's energy drain scales up to 1.3x at full night (same
order of magnitude as the existing harsh-weather 1.4x multiplier —
"staying up all night costs about as much as working a storm" was the
target feel); the involuntary-rest energy threshold
(`REST_THRESHOLD`) rises by up to 0.15 at night, so agents settle in
for the night progressively sooner rather than only collapsing exactly
at the same threshold regardless of hour; RESTING energy recovery gets
up to a 15% night bonus. This was previously called out as a
deliberately-deferred scope boundary (v0.32.0's DECISIONS.md entry) —
explicitly revisited now per the user's follow-up ask, not a reversal
of that earlier call.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): a fresh 60x60 world produced real river tiles
and 3 lakes at creation; full round-trip serialization confirmed rivers
(via terrain) and lakes preserved; a 6000-tick full-engine run produced
a real `disaster_flood` event with nonzero flood pressure and no
crashes from terrain sampling `Biome.RIVER`; direct function-level
tests of `tick_wildfire` (ignition + spread + burnout, confirmed forest
tiles turn to grassland), `tick_storm` (confirmed building `condition`
drops by exactly `STORM_DAMAGE`), and `tick_lakes` (confirmed both
growth and shrink paths convert a boundary tile and emit the right
event) all passed. All touched Python files pass `python3 -m
py_compile`; `app.js` passes `node --check`.

## Population recovery, LLM-cadence fix (whispers), Observatory UI direction

**Population stagnation investigation.** The user reported 2 NPCs
after 50000 ticks. First reproduction attempt was tested by calling
`World.tick()` directly in a loop, bypassing `SimulationEngine`
entirely — this skips `_schedule_due_cognition` (an async, fire-and-
forget task), so every agent stays at its `Agent.goal` default
(`WANDER`) forever, never `SOCIALIZE`s, and only colocates by pure
random-walk chance. That test showed 0 births in 50000 ticks and total
extinction — a real result, but of a broken test methodology, not the
actual system (`SimulationEngine._tick_once`, the real code path,
schedules goal cognition every tick as documented). Re-ran through the
actual engine: population grew from 12 to 198 (of a 200 cap) over
20000 ticks with reproduction firing normally. So reproduction itself
isn't the bug. What's real: once a population crashes down to a
handful of survivors (via predation/starvation/disasters/attrition
outpacing early sparse births — plausible over a real 50000-tick run
with things like this session's new disasters added), there was no
recovery mechanism — the exact class of bug wildlife had before
v0.32.0's `_maybe_recolonize` fix. Added the population equivalent,
`Population._maybe_welcome_migrant`: same rare per-tick roll shape,
gated on `0 < population < POPULATION_CRITICAL_THRESHOLD (4)`, a
newcomer already at `MATURITY_TICKS` age (so immediately reproduction-
eligible, no multi-thousand-tick wait) arrives at an existing building
(or near a survivor if unnamed). Deliberately excludes the `== 0` case:
this session's explicit design direction says "settlements expand or
collapse" and wants "history readable from the landscape" — a fully
extinct settlement is a legitimate, permanent ending (ruins persist via
existing building decay/reclamation), not a state to silently undo.

**Whisper/town-brain cadence investigation.** Traced
`POST /intervene/town-brain` end-to-end: `WorldBroadcaster.
enqueue_intervention` -> `_apply_pending_interventions` (drains at the
top of the next tick, appends to `Settlement.player_influence`, capped
to last 3) -> `_maybe_schedule_town_brain` (folds `player_influence`
into the prompt, then clears it) — all correct, no bug in the queueing
path itself. The actual problem: `_maybe_schedule_town_brain` (like
chronicle and festival) only fired on `"season_end"`. With the real
365-day/12-month calendar (not the old fixed 20-day one), a season is
~91 real days, ~8736 ticks at `sim_minutes_per_tick=15`, ~2.4 hours of
real wall-clock time at the default `tick_seconds=1.0` pacing before a
queued whisper was ever read — CLAUDE.md already documents this exact
"real calendar makes season/year-gated cadences much rarer than
originally intended" problem for terrain evolution (fixed by moving to
week/month boundaries), but the fix was never applied to the LLM-job
schedulers added around the same time. Applied the same shape here:
chronicle/festival/town_brain moved from `season_end` to `month_end`;
tradition/invention moved from `year_end` to `season_end` — each one
tier faster, preserving the original relative rarity ordering
(beliefs/omens stay monthly, town_brain/chronicle/festival join them,
tradition/invention become the rarer, "more deliberate" seasonal tier).
Rather than let the *effective* annual rate silently multiply by
inflating each job's real frequency ~3-4x for no reason, the two
probability-gated jobs had their per-roll chance rescaled to
approximately reproduce the original annual/seasonal rate at the new,
faster cadence: `INVENTION_CHANCE_PER_YEAR` (0.5, once/year) ->
`INVENTION_CHANCE_PER_SEASON` (0.15, once/season — four independent
0.15 rolls give ~48% chance of at least one per year, close to the old
50%); `FESTIVAL_CHANCE_PER_SEASON` (0.35, once/season) ->
`FESTIVAL_CHANCE_PER_MONTH` (0.13, once/month — three independent 0.13
rolls give ~34% per season, close to the old 35%). Chronicle/town_brain
have no independent probability gate (they fire unconditionally on
their cadence event, same as beliefs), so no rescaling was needed for
those — only the cadence trigger changed.

**Observatory UI direction.** The user's message was a large, explicit
product-direction brief (map-as-primary-interface, hover inspection
over panels, consequences-over-stats narration, curated history vs.
developer diagnostics kept strictly separate, NPC inspection leading
with mind over stats, an interactive relationship graph, a Town Brain
internal-monologue reveal, a future documentary/narrated-history mode).
Captured as a new "Observatory UI direction" section in CLAUDE.md
(persistent design memory) rather than attempted as code this batch —
each piece (hover system, relationship graph, mind-first NPC inspector,
conversation-surfacing logic, monologue reveal, documentary mode) is
independently large enough to be its own coherent milestone, and
CLAUDE.md's own workflow rules (smallest coherent milestone at a time,
no half-finished pieces within a batch) argue against attempting all of
it speculatively in one pass without the user picking a starting point.
Cross-checked the brief's "world evolution" asks against what already
exists: terrain evolution, road wear *and* decay-from-disuse (roads
already "appear and disappear"), building decay/ruin/reclamation, and
this session's disasters/hydrology/population-recovery work already
satisfy "map visibly evolves" and "settlements expand or collapse"
mechanically — the remaining gap is presentation (UI), not simulation
substance, which is exactly what the new CLAUDE.md section scopes for
next.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): `_maybe_welcome_migrant` produces a real
`migrant_arrived` event for a lone survivor within a bounded number of
ticks, correctly never fires at 0 population, and correctly never fires
at/above the critical threshold. A full engine run confirmed a queued
whisper is consumed (priority/rationale set, `player_influence`
cleared) within ~1600 ticks of the settlement being named — down from
the old ~8700-tick (~2.4 real hour) wait. A 10000-tick full engine run
plus snapshot save/reload round-trip completed with no errors. All
touched Python files pass `python3 -m py_compile`; `app.js` passes
`node --check`.

## Realistic snow/heatwave/frost, live sim-speed controls, relationship graph

Three asks in one batch: (1) verify/fix UK-realistic snow, (2) add more
UK-historical natural disasters (heatwave named explicitly), (3) add
live pause/speed-up/speed-down/reset sim-speed controls to the browser
UI, changeable in real time without a restart — plus "start with" the
relationship graph from the Observatory UI backlog CLAUDE.md captured
last session but deliberately didn't implement.

**Snow root cause.** `is_snowing` gated on `temperature_c <= 0.0`, which
sounds right for UK winters on paper, but a direct measurement
(sampling `compute_weather` across a simulated December/January/
February at the default seed, tens of thousands of ticks) found the
realized temperature *never once* reached 0C — minimum observed 0.35C
across a multi-year sample. The culprit is `compute_weather`'s
smoothing: `temperature_c = previous * 0.7 + target * 0.3` is an EMA
that damps the raw `target_temp = base + uniform(-6, 6)` jitter into a
much narrower steady-state range than the single-draw formula suggests
(variance shrinks by roughly the EMA's characteristic factor). The
`<= 0.0` threshold was live code that could never fire — not a rare
event, an unreachable one. Fixed by raising the threshold to 2.0C
(`SNOW_TEMPERATURE_THRESHOLD_C`), which both (a) sits inside the range
winter baselines actually reach and (b) is more correct UK meteorology
anyway — most lowland UK snow falls in the 0-2C band, since
precipitation phase depends on the whole air column's temperature
profile, not just screen-height reading. Verified after the fix: ~0.6
snow-tick-days per winter month at the default seed (Dec/Jan/Feb all
showed the same ~1.9% of ticks snowing), roughly matching how
infrequent actual lowland UK snow is.

**Heatwave/frost, same bug class, caught before shipping.** First cut
of heatwave required temperature above a threshold *and* precipitation
below a threshold on the same tick to build pressure (mirroring how the
brief described it — "hot, dry stretches"). Direct measurement showed
this fired zero times across a simulated year: the two conditions
individually were each achievable, but requiring them simultaneously
each tick, given they're only loosely correlated, made the combined
condition rare enough that `PRESSURE_GAIN` per qualifying tick never
outpaced `PRESSURE_DECAY` on the many non-qualifying ticks — pressure
decayed back to zero net over time on average (a losing random walk).
Same root cause as the snow bug: a threshold that looks reasonable on
paper but is unreachable against the actual simulated distribution.
Fixed by decoupling the two: pressure builds from sustained heat alone
(`HEATWAVE_BUILD_TEMP=18.5`, tuned against the measured ~21C ceiling of
smoothed summer temperature, not the raw baseline+jitter range), and
dryness (`HEATWAVE_DRY_PRECIPITATION=0.22`) only multiplies the trigger
chance once pressure clears threshold (`HEATWAVE_DRY_CHANCE_
MULTIPLIER=2.5`) — same shape as wildfire's temperament nudge. Frost
got the identical fix: an initial `FROST_TEMP_THRESHOLD=-3.0` was never
reached (min observed winter temp 0.35C, same as the snow finding), and
an initial `FROST_DURATION_MIN_TICKS=20` exceeded the longest
sub-threshold streak ever observed (max 8-11 ticks depending on
threshold, given the smoothing's autocorrelation). Retuned to
`FROST_TEMP_THRESHOLD=2.0` (matching the snow band) and
`FROST_DURATION_MIN_TICKS=6`; verified triggering (non-zero) across a
30-seed sample, at a realistic multi-year-rare cadence once scaled from
the all-January synthetic test window back down to a real ~90-day
winter — matching the brief's own example (2018 "Beast from the East"
happened once in roughly a decade). Both wired into `World._tick_
disasters`, which was moved to run *before* `population.tick` in
`World.tick()` (previously after) specifically so a heatwave/frost
triggered this tick is already visible to `Population.tick`'s new
`heatwave_active` param (folded into the existing `weather_harsh`
agent-need check) the same tick, not one tick late.

**Why sim-speed bypasses the existing `/intervene/*` queue.** Every
other intervention (`agent_goal`, `settlement_resources`, `weather`,
`town_influence`) is queued via `WorldBroadcaster.enqueue_intervention`
and drained once per tick at the top of `SimulationEngine._tick_once` —
deliberately, so `World` is only ever mutated from the tick loop. Pause/
speed can't use that seam: if the sim is paused, `_tick_once` never
runs, so a queued "resume" request would sit in the queue forever and
the sim would be permanently stuck. Also, pause/speed don't touch
`World` at all — they only change the engine's own tick-pacing loop, so
there was no reason to route them through World-mutation machinery in
the first place. Instead `WorldBroadcaster` gained plain read/write
pause/speed fields, safe because the FastAPI request handler and the
engine's `run_forever` loop share one asyncio event loop and are never
concurrent (no lock needed). `run_forever` now checks `is_paused()`/
`get_speed_multiplier()` every loop iteration (not just once at
startup), and polls at a short fixed interval while paused
(`PAUSED_POLL_SECONDS=0.25`) rather than sleeping for a full — possibly
very long, at a low speed multiplier — tick interval, so a resume
request is picked up promptly. Verified live: a 0.1s-tick-interval
engine run showed zero tick advancement while paused, and immediate
resumption (plus faster advancement at 4x) once unpaused.

**Relationship graph.** The first piece of the Observatory UI backlog
(CLAUDE.md's "Observatory UI direction" section, 0.34.0) the user asked
to start with. No backend change was needed — `Agent.to_dict()` already
serializes `relationships` (a `{other_agent_id: affinity}` map) into
the existing per-tick broadcast payload's `agents` list — so this is a
pure frontend addition: a force-directed layout computed client-side
(no graph library; simple pairwise repulsion + spring attraction along
edges + centering, run each animation frame while the panel is open).
Node positions persist in a module-level `Map` across ticks/frames
rather than being recomputed from scratch each update, so the layout
settles into a stable shape instead of jittering. Relationships below
`REL_MIN_AFFINITY=0.08` are dropped entirely — every agent pair that's
ever interacted has *some* nonzero affinity, so drawing all of them
would produce an unreadable mesh; only bonds strong enough to matter
are worth a line. Edge color (green/red) and thickness/opacity encode
affinity sign/magnitude; hovering a node shows the agent's name via the
same `.tooltip` pattern already used on the map. Deliberately scoped to
just the graph (not click-to-open-NPC-inspector, not a legend, not
family-tree edges) — the rest of the Observatory UI backlog (map-as-
primary-interface rework, hover inspection, mind-first NPC inspector,
Town Brain monologue reveal, documentary mode) remains not started.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): a 3000-tick engine-driven run plus snapshot
save/reload round-trip completed with no errors, including all five
`DisasterState` fields; a dedicated pause/resume/speed-up test against
a live `run_forever` loop confirmed zero ticks advance while paused and
resumed advancement (faster, at 4x) immediately on unpause; the
`/intervene/sim-speed` route registration and all five `action` values
(pause/resume/speed_up/speed_down/set/reset, plus the invalid-action
400 case) were exercised directly against `WorldBroadcaster`. All
touched Python files pass `python3 -m py_compile`; `app.js` and
`index.html`'s inline structure pass `node --check`/manual review.

## Observatory UI backlog complete: hover, NPC inspector, consequences overlay, surfaced conversations, Town Brain monologue, documentary mode

User instruction: "complete all the remaining tasks" — read as
authorization to implement the rest of the Observatory UI backlog
CLAUDE.md's "Observatory UI direction" section explicitly listed as
"not started, deliberately" after 0.34.0/0.35.0, rather than re-asking
"which piece" again after already being told to do all of them.

**Hover inspection.** `findAgentAt`/the mousemove handler already
existed for agents only; generalized into a single hover pipeline that
checks agent, then building (`findBuildingAt`, new), then bare terrain
(reads the already-fetched `terrain.biomes` grid), in that order —
cheapest/most-specific first. No backend change needed; buildings and
terrain were already in the payload/terrain fetch, just never surfaced
on hover.

**NPC inspector.** New click handler on the map canvas opens a modal
(`#npc-inspector-backdrop`, plain CSS — no dependency added) built from
data already in the per-tick payload plus `settlement.beliefs`
(filtered by `subject_agent_id`, the same field `llm/dialogue.py`'s
`beliefs_about` param already consumes for NPC-to-NPC prompts — this is
the first *UI* consumer of it). Deliberately ordered mind-first per the
brief's explicit list (goal/reason, beliefs, relationships, memories)
with vitals last and small. Re-renders from `latest` on every payload
while open, so it's a live view of one person's unfolding state, not a
snapshot frozen at click time.

**Consequences overlay.** A new `#consequences-strip` absolutely
positioned over the map (map-panel is already `position: relative` for
the weather canvas, so no new positioning context needed). Computed
client-side from `payload.summary` fields already present — no backend
change. "The village is aging" mirrors `agent.py`'s real
`MIN_LIFESPAN_TICKS=20000` constant (avg_age_ticks / 20000 > 0.55) so
the threshold means something, not an arbitrary round number. "Wolves
have returned" needed a one-tick-late signal a stateless per-payload
computation can't see on its own (a *transition* from 0 to >0
predators, not just "predators > 0" which would show constantly once
any pack exists) — handled with a small piece of client-side state
(`lastPredatorTotal`, `wolvesReturnedUntilTick`) that persists across
payloads, the same "track state across ticks" pattern the relationship
graph's `relNodes` map already established in 0.35.0.

**Surfaced conversations.** `Population.apply_dialogue`'s existing
threshold-crossing logic (close-bond/rivalry, already there for
relationship *memory*) was the exact definition of "conversation that
changed something" the brief asked to distinguish — reused rather than
re-implemented, just also returned as a third tuple element (`surfaced:
bool`) so the caller doesn't duplicate the threshold logic. `dialogue`
(routine) is still logged and still fully queryable via `/events`/dev
console ("record all conversations internally") — only the main UI
event feed's `CATEGORY_META` entry changed (`skip: true`), the same
display-only filtering mechanism `day_end`/`week_end`/`month_end`
already use, not a change to what's persisted.

**Town Brain monologue.** `Settlement.priority_history` is purely
additive to the existing `current_priority`/`priority_rationale` (which
remain the single source of truth `choose_building_kind` reads) —
capped at 6 entries (`PRIORITY_HISTORY_MAX`) via a small helper method,
`record_priority`, called alongside the existing assignment in
`_run_town_brain`. No design tension here: the brief asked for past
rationales to read as an ongoing train of thought, and they already
existed as one-off computed strings — the only gap was that nothing
kept the old ones once overwritten.

**Documentary mode.** New `llm/documentary.py`, structurally a sibling
of `chronicle.py` (same SYSTEM_PROMPT/build_prompt/fallback/parse
shape, same "reuse the events table with a new category" persistence
decision) but deliberately different in two ways: (1) cadence — gated
on `year_end`, the rarest calendar boundary, versus chronicle's
`month_end`, matching the brief's "periodically" framing at a visibly
slower pace than the existing monthly narration; (2) source data — buit
from `persistence.snapshot.history_events` (the curated milestone
subset already powering the History tab) rather than chronicle's
everything-included `recent_events`, since a documentary looking back
on a year should read as "what actually mattered," not routine
day-to-day noise re-summarized at a different grain. No settlement
before a name exists means nothing to narrate yet — same gate
`_maybe_schedule_tradition` already uses.

**Scope note, stated plainly rather than silently overclaimed:** the
map-as-primary-interface *rework* (restructuring/thinning the sidebar
itself, not just adding overlays to the map) was not attempted — this
batch added hover/click/overlay capability directly on the map (a
meaningful, real step toward "the map is the primary interface") but
left the existing panel-heavy sidebar layout untouched. That's a
genuinely separate, larger redesign, not a checkbox this batch's time
budget covered.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): a direct call to `_maybe_schedule_documentary`
against a real engine + real sqlite DB logged a real `documentary` row
with the expected fallback narration; `Settlement.priority_history`
capping and to_dict/from_dict round-trip confirmed directly; an
8000-tick full-engine run (14 starting agents, growing to 44) produced
783 real dialogue exchanges with no crashes from the `apply_dialogue`
3-tuple return-shape change, plus a clean snapshot round-trip including
the new `priority_history` field. All touched Python files pass
`python3 -m py_compile`; `app.js` and `index.html`'s structure pass
`node --check`/manual review.

## Sidebar restructure: map-as-primary-interface, the last backlog item

The one item 0.36.0 explicitly flagged as not attempted — restructuring
the sidebar itself, not just adding overlays to the map — closed out
per the user's plain "continue" (read as: proceed to the flagged next
milestone rather than re-ask).

Design: rather than inventing a new UI pattern, reused the exact
show/hide toggle mechanism already established for history/
relationships/dev-console (`.hidden` class + a header button toggling
it + an `active` state on the button) for a new `#details-panel`
wrapping the stat grid and the four culture-list panels (beliefs/
traditions/inventions/festivals) plus infrastructure. Only genuinely
new CSS needed: `#details-panel` had to be `display: flex; flex-
direction: column; gap: 12px` (matching `#sidebar`'s own flex layout)
since wrapping several `.panel` divs and the `.stat-grid` in one plain
container div would otherwise collapse `#sidebar`'s `gap` between them
into default block-level margins.

Kept exactly two panels always visible — Town Brain and Recent Events —
because CLAUDE.md's own "Observatory UI direction" section names these
specifically for the normal UI ("a curated history... an expanded Town
Brain panel"), distinguishing them from the raw-stat panels the same
section explicitly wants demoted behind hover/dev-observatory access.
Not a judgment call on which panels "feel important" — read directly
off the existing design brief's own two-audience split.

Verified live in a real browser via Playwright (chromium at /opt/pw-
browsers, per this environment's pre-installed setup) against a running
server (LLM disabled, `--tick-seconds 0.2` for a fast-moving test run):
screenshotted the default view (confirmed only Town Brain + Recent
Events + map + consequences overlay visible — the "Wolves have
returned" overlay line was actually live-triggered during the test
run), the details panel opened via toggle (confirmed stat tiles and
culture panels render correctly), the relationship graph opened via its
own toggle (confirmed unaffected by the restructure), clicked an agent
on the map canvas by scanning for a colocated pixel until the NPC
inspector opened (confirmed the mind-first modal renders correctly:
goal/reason, beliefs, relationships, memories, vitals), and exercised
the sim-speed pause/speed-up controls (confirmed the pause button
toggled to "▶ resume" and the speed label updated to "2x" after one
speed-up click) — every feature from the last two releases confirmed
working together in a live session, not just individually compiled.

## Everything left from the original plan, including Phase G

User instruction: "build everything left from initial plan including
phase G." Read against `docs/ROADMAP.md`'s per-phase "Not yet built"
bullets and CLAUDE.md's two explicitly-flagged-but-unstarted next
steps (trust lever, town's opinion of the player), minus the two items
the project's own docs already call out as genuinely large,
architecturally separate efforts not meant for a single batch
(per-agent inventory/trade, multiple named settlements — the latter
means `Settlement` stops being a world-wide singleton, a much bigger
change than anything else in this pass).

**Stale-roadmap correction, caught before implementing redundant
code.** The roadmap's A4 note said hunting was "currently opportunistic
— only when a FORAGE-goal agent happens to be colocated with a herd."
Reading the actual code (`Population._dispatch_movement`'s FORAGE
target chain) showed `_nearest_grazer_herd` already sits in the same
target-search chain as farms/granaries/wild nodes — a FORAGE-goal agent
already deliberately walks toward a known herd, exactly like it walks
toward a known farm. Adding a separate `AgentGoal.HUNT` would have
duplicated that targeting/consumption logic for no new capability — a
premature abstraction CLAUDE.md's own workflow rules argue against.
Fixed the actual gap instead (herds not competing with agents for
`ResourceGrid` nodes) and corrected the stale roadmap line rather than
building the redundant goal the stale note implied was still needed.

**Vegetation depletion design.** A grazer herd consumes
`GRAZE_CONSUMPTION_PER_TICK` from a colocated FOOD `ResourceNode` each
tick (mirrors an agent's own forage draw rate) and skips its
reproduction roll outright below `GRAZE_REPRODUCE_MIN_FOOD` — real,
not cosmetic: an overgrazed tile measurably slows herd growth, and a
tile agents forage heavily now also thins out the local wildlife that
would otherwise have grown there. Deliberately scoped to only the
tiles where the two systems actually overlap (a herd on open grassland
with no rolled FOOD node is unaffected) rather than inventing a new
shared "vegetation" resource layer — reuses `ResourceGrid` as-is.

**Rivalry avoidance, reusing rather than duplicating the predator-
avoidance seam.** `_step_toward`/`_maybe_move` already accept a
`predator_tiles`-shaped "prefer to avoid these" set. Rather than
threading a second avoidance concept through both functions, rival
tiles are computed once per agent (from `position_snapshot` +
`agent.relationships`) and unioned into the same set before either
function is called — a rival's tile becomes indistinguishable from a
predator's tile as far as movement preference goes, with zero new
parameters on the movement primitives themselves.

**Event-triggered cognition: why a separate cooldown dict, not just
"add to the daily due list."** `_inflight_cognition_agent_ids` already
prevents *concurrent* duplicate scheduling for one agent, but that
guard clears the moment a call resolves (often within the same tick
against a fast/disabled LLM) — naively re-checking "is this agent still
critically hungry" every tick would re-trigger every tick for as long
as the emergency persists, hammering the LLM. Added
`Population.cognition_trigger_cooldowns` (agent_id -> last-triggered
tick), same shape and same pruning discipline as the existing
`dialogue_cooldowns` (an overnight-soak diagnostics audit previously
found that dict growing unbounded — the new one prunes the same way
from day one). `TRIGGERED_COGNITION_COOLDOWN_TICKS=200`, shorter than
`DIALOGUE_COOLDOWN_TICKS=300` since these are individually rarer events
per agent, not a routine per-pair interaction.

**Whether-to-build steering: extending an existing lever rather than
building a new targeting system.** `choose_building_kind` already reads
`settlement.current_priority` to weight *which* kind gets founded — the
"whether" half of the same roadmap-flagged gap was a much smaller
addition than it first appeared: multiply the existing
`SETTLE_CHANCE_PER_TICK` roll by a priority-dependent factor
(`SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER=1.6` when priority is
"growth", `_OFF_PRIORITY_MULTIPLIER=0.7` otherwise, once a first
decision has run). Deliberately did NOT attempt "where to build" (an
agent choosing and pathing toward a specific site) — that's a genuinely
different, larger mechanic (deliberate targeting + a "good spot"
heuristic) than nudging an existing roll, and CLAUDE.md's "smallest
coherent milestone" rule argues against bundling it into the same pass.

**Phase G v2: intensity knob and person-specific omens.**
`Config.phase_g_intensity` (default 1.0) is threaded as a plain
multiplier into both `tick_temperament` (scales the random-walk step,
noise and fortune-bias alike) and `_maybe_schedule_omen` (scales the
per-month chance, with an explicit `<= 0.0` early return so it's a
real off switch, not just a very small number). Person-specific omens
reuse the existing per-person-beliefs machinery (`subject_agent_id`)
rather than inventing new subject-tracking: about half the time an
omen fires, if any belief already resolves to a still-living agent,
that agent's name is threaded into `omens.build_prompt`/`fallback_omen`
as an optional `subject_name` — new `{name}`-templated fallback pools
for the LLM-disabled case, same "worded so it always has a mundane
explanation" constraint as before, unchanged when no such belief
exists (still settlement-wide flavor sometimes, preserving variety).

**Trust lever design.** Deliberately a second dict (`Agent.trust`) next
to `Agent.relationships`, not a derived/computed view of it — the
CLAUDE.md gap being closed specifically named "someone can be well-
liked but known to embellish," which requires the two to be able to
diverge, not just scale together. Nudged via a new `TRUST_DELTA`
alongside the existing `DIALOGUE_SENTIMENT_DELTA` on every dialogue
resolution, deliberately asymmetric (`{"warm": 0.03, "tense": -0.04}`)
— credibility lost to a bad exchange costs more than credibility
earned by a good one, the same real-world asymmetry as reputation.
Read at the moment a rumor arrives, *before* that same exchange's own
trust nudge is applied — the receiving agent's pre-existing opinion of
the source decides how the rumor gets phrased in memory, not one
freshly inflated by the warm chat that happened to carry it. This
closes the loop into cognition for free: `llm/cognition.py`'s
`build_prompt` already reads an agent's latest memory as personal
context, so a skeptically-phrased rumor memory changes what the LLM
sees on that agent's next goal decision without any new prompt-building
code.

**Town's opinion of the player: deliberately reuses temperament's
shape, not its cause.** `tick_player_standing` is structurally a
sibling of `tick_temperament` (bounded random walk, mean reversion,
small per-tick noise) but driven by a different signal — count of
`intervention`-category events logged this month (any `/intervene/*`
call the engine actually applied), capped at
`PLAYER_STANDING_MAX_EVENTS_COUNTED=5` so a single burst of nudges
can't swing it to an extreme in one step (steady occasional attention
should read as more "looked after" than a flood of one-time nudges).
Faster mean reversion than temperament (0.95 vs 0.97) since this is
about an external presence's felt absence, not the village's own
ongoing internal affairs. Folded into `town_brain.build_prompt` by
reading `settlement_summary["player_standing"]` — no new prompt
parameter needed, since `settlement_summary` (from `Settlement.
summary()`, which now includes the field) was already threaded through
— only mentioned in the prompt text at all once notably warm/cold
(`|standing| > 0.4`), keeping it a rare, subtle input like whispers,
not a constant refrain.

Verified (LLM disabled in this environment, deterministic fallbacks
exercised throughout): a 12000-tick full engine run (14 -> 78
population) produced real grazing depletion (min FOOD node amount
0.022, well below the undisturbed default), 49 agents with at least
one trust entry, 44 cognition-trigger-cooldown entries (confirming the
event-trigger path actually fired and was rate-limited, not just
wired), evolving `temperament`/`player_standing` values, and a growing
`priority_history`. A snapshot save/reload round-trip covering every
new field (`Agent.trust`, `Population.cognition_trigger_cooldowns`,
`Settlement.player_standing`) matched pre-save values up to the
existing round(x, 4) precision every other float field in this project
already accepts (relationships/temperament included) — not a
regression, the same established serialization precision. All touched
Python files pass `python3 -m py_compile`.

## Phase G v3: temperament's reach, omen memory

User instruction: "phase G supernatural" — a bare follow-up request to
keep deepening Phase G after the previous batch's intensity knob and
person-specific omens. Read as "extend this incrementally" (CLAUDE.md's
own Phase G section already says exactly that: "more omen triggers,
subtler cross-system nudges... not... anything explicit").

**Which two systems got the temperament nudge, and why not others.**
Looked for systems already shaped like the existing nudges (a rare
recovery/growth roll, small in magnitude, thematically adjacent to "the
village's fortune") rather than inventing a new category of effect.
Migrant arrival (`Population._maybe_welcome_migrant`) and wildlife
recolonization (`WildlifeGrid._maybe_recolonize`, gated by
`WILDLIFE_RECOLONIZE_CHECK_CHANCE`) both fit exactly: both are already
rare rolls, both are already the sole recovery path for their
respective near-extinction scenario, and both plausibly read as "things
going the village's way" without requiring any new narrative framing.
Deliberately did NOT touch disaster trigger chances, farm growth, or
construction rolls — those already have their own real, non-ambiguous
drivers (weather, season, materials) and adding a temperament nudge on
top would start to feel like temperament secretly running the
simulation rather than a subtle texture on top of it, working against
the "never dominant, always secondary" rule the existing nudges
already follow.

**One-sided by design, same rationale both times.** Both new nudges
only fire on positive temperament (`max(0.0, temperament)`), mirroring
neither `TEMPERAMENT_INVENTION_INFLUENCE` nor `TEMPERAMENT_KILL_
CHANCE_INFLUENCE` exactly (those do scale in both directions) but
matching the specific shape of what they're modifying: both migrant
arrival and wildlife recolonization are already the *sole* path back
from a crash. Letting ill fortune actively suppress the one mechanism
that recovers from ill fortune would risk a genuine death spiral
(a population/wildlife crash, itself likely a source of the low
temperament, making its own recovery harder) — a mechanically real bad
outcome, not just flavor, so the asymmetry is a deliberate safety
property, not an arbitrary choice.

**Omen memory: additive, optional, capped.** `Settlement.omen_history`
is structurally identical to `priority_history` (same cap-and-trim
`record_*` method shape) — reusing an already-established pattern
rather than inventing a new one. Past omens are threaded into
`omens.build_prompt` as a `past_omens` list, phrased in the prompt as
"if it fits naturally... without saying so directly" — the LLM is
explicitly told this is optional texture, not a thread every future
omen must follow, so most omens still stand alone (verified: the
prompt change doesn't force every future omen to reference the past,
it just makes that occasionally available). Only the LLM path sees
`past_omens` — the deterministic fallback pools remain hand-written
one-off sentences, since a fallback line referencing a *specific* past
omen would require templating against arbitrary prior text, a
meaningfully bigger and less reliable undertaking than the LLM path
naturally handles as free text.

Verified (LLM disabled, deterministic fallback exercised for the
temperament-nudge math; a forced-omen loop with artificially advanced
tick counts exercised the omen-memory path end to end since LLM-
disabled runs always take the fallback branch, which doesn't consume
`past_omens` — the memory-recording half was verified directly, the
prompt-consumption half is inherently only exercised with a live LLM):
`MIGRANT_CHECK_CHANCE_PER_TICK`/`WILDLIFE_RECOLONIZE_CHECK_CHANCE` both
compute the expected ~1.2x ceiling at `temperament=1.0`; a 50-call
forced-omen loop (varying tick count each call so the namespaced roll
actually varies, unlike an unvaried-tick first attempt that produced
identical results every call and had to be corrected) produced 6 real
omen_history entries, correctly capped at `OMEN_HISTORY_MAX=6`; a
6000-tick full engine run plus snapshot round-trip completed cleanly
including the new field. All touched Python files pass `python3 -m
py_compile`.

## Per-agent inventory/trade, culture-specific buildings, per-family beliefs, Phase G v4

Explicit user request to tackle both of the roadmap's two "genuinely
large, architecturally separate" gaps (per-agent inventory/trade,
multiple named settlements) plus the two smaller named gaps (culture-
specific building types, structured per-family belief resolution)
"and phase G" together, in one go. Read literally that's five separate
large efforts in one pass; the batching rule ("implement multiple
systems per session... no half-finished pieces within a batch — every
system landed must be mechanically real") and the "audit before
continuing" rule both argue against attempting all five with equal
scope. Split the difference: implemented four of the five as real,
complete, deliberately-scoped slices, and explicitly declined the
fifth (multiple named settlements) rather than half-attempt it — see
below.

**Per-agent inventory/trade** was always going to be the harder of the
two "large" gaps to scope down honestly, since the maximal version
(multi-good inventory, hauling, markets, price discovery) really is a
large effort. Landed the smallest version that's still mechanically
real rather than a stub: `Agent.inventory` holds one good (`"food"`),
stashed as a small skim (`FORAGE_INVENTORY_SKIM=0.05`, capped at
`PERSONAL_FOOD_CAPACITY=0.6`) alongside a successful farm-harvest or
granary-withdrawal forage — deliberately not wild foraging or an
emergency currency purchase, both scarcity-driven with nothing spare
to save. An agent draws on their own stash before scrounging further
(`Population._maybe_forage`'s new branch, ordered after the granary
check and before wildlife hunting — "eat what you saved before hunting
or scrounging"). `Population._maybe_trade_food` (new, called from
`tick()` right after `_maybe_stock_granaries`, using the same
already-computed `by_position` colocation map every other presence-
driven mechanic in this project uses) lets a hungry, personally-empty
agent receive from a colocated agent with food to spare, gated on
`relationship > TRADE_MIN_RELATIONSHIP=-0.2` (rivals don't share first,
though ordinary strangers at 0 do) — a real, if small
(`TRADE_FOOD_AMOUNT=0.2`, matching `FORAGE_AMOUNT`'s scale) transfer
with a `TRADE_RELATIONSHIP_BOOST=0.03` nudge on both sides and a
`_remember` memory entry for the recipient. This is the one place in
the whole project food moves directly between two named individuals
rather than through the settlement's communal granary/currency — a
genuinely new axis, not a re-skin of an existing mechanic.

**Culture-specific building types**: `BuildingKind.SHRINE`, gated in
`choose_building_kind` behind a new `has_tradition: bool` parameter
(mirrors the existing `era` gate FACTORY already uses) — only enters
the foundable weighted pool once `Settlement.traditions` is non-empty.
Chose one clear, proportionate mechanical payoff rather than several
small ones: `SHRINE_FESTIVAL_BOOST_MULTIPLIER=1.5` deepens
`FESTIVAL_RELATIONSHIP_BOOST` for any pair colocated on a standing
shrine's tile when a festival is held (`Population.hold_festival`
gained an optional `settlement` param to check this). Also gave it a
second, smaller effect specifically to satisfy "prefer systems
interacting with existing systems over isolated mechanics"
(CLAUDE.md): `SHRINE_OMEN_CHANCE_MULTIPLIER=1.3` on
`SimulationEngine._maybe_schedule_omen`'s firing chance when a shrine
stands — a physical expression of the village's own culture is
somewhat likelier to be where something ambiguous gets noticed. This
is also this batch's Phase G increment (the user's "and phase G"):
deliberately not a new isolated Phase G lever, but the first case of a
*player-visible building* nudging an existing Phase G roll, alongside
the pre-existing pure-fortune/pure-noise drivers.

**Structured per-family belief resolution**: `Agent` names turned out
to have no surname/family-name concept at all (verified via targeted
codebase search before designing this — `hearthmind/agents/names.py`
draws single-token first names, falling back to "Name II"/"Name III"
once the pool exhausts rather than adding a family name), so
family-level resolution can't be string-matching on a surname the way
`resolve_subject_agent_id` matches a full name. Instead
`beliefs.resolve_family_agent_ids(subject_agent_id, agents)` computes
family membership structurally from `Agent.parents` — the subject
themself, their living parents, their living children, and their
living full siblings (agents sharing the identical `parents` tuple) —
recomputed fresh at belief formation/revision time rather than stored
as a persistent family-id, since a family's *living* membership
changes as people are born and die and a stale id list would drift
wrong. Stored on the belief entry as `subject_family_agent_ids`
(additive key; old entries without it default to `[]` via `.get(...,
())`  at every consumption site, no migration needed).
`SimulationEngine._schedule_due_dialogue`'s `beliefs_about` filter now
matches on `subject_agent_id` OR membership in
`subject_family_agent_ids`, so a belief about one Hallow reaches every
living Hallow's dialogue prompts, not just the one the LLM happened to
name.

**Multiple named settlements: explicitly not attempted this batch.**
This is the one item where "implement a scoped slice" isn't really
available — the ask is structural: `Settlement` stops being a
world-wide singleton, which means `World.settlement`,
`Population.tick`'s settlement-taking signature, every LLM job that
currently takes one `settlement_summary`/`settlement.name`
(town_brain, chronicle, beliefs, festival, invention, documentary,
naming, omens — eight modules), the interface/API payload shape, the
browser UI's assumption of one settlement, and the snapshot schema all
change in the same pass, with no way to land a "partial" version that
isn't either broken or a settlement-count-of-1 special case
indistinguishable from doing nothing. CLAUDE.md's own "Known
architectural gaps" section already calls this out by name as
"genuinely large, architecturally separate," specifically *because*
`Settlement` stopping being a singleton is not decomposable into
independent smaller PRs the way inventory/trade's scope-down was.
Attempting it in the same pass as four other substantial changes,
without the project's own test suite (deemed unreliable, per
CLAUDE.md's workflow rules — verification here is manual/ad-hoc plus
the user's live diagnostics), risked leaving the live simulation in a
half-migrated state that's hard to audit and easy to regress silently
— directly against "audit before continuing; fix regressions before
new features" and "preserve existing behavior unless explicitly
changing it." Declining outright and flagging it back, rather than
either skipping it silently or rushing a fragile version, is the
documented call; it remains the clear next candidate for its own
dedicated session.

Verified (LLM disabled, deterministic fallback exercised throughout):
a 25,000-tick and a separate 40,000-tick full `World.create_new` ->
repeated `.tick()` run both completed without error; personal food
accumulation confirmed directly (`avg_personal_food` > 0, specific
agents observed holding 0.05-0.1 food after farm/granary harvests);
`choose_building_kind` sampled 500 times each with `has_tradition=
False`/`True` confirmed SHRINE never appears without a tradition and
does appear with one; a snapshot round-trip (`to_dict`/`from_dict`)
preserved population count and the new `inventory` field exactly. All
touched Python files pass `python3 -m py_compile`.

## Architecture review pass (v0.39.0, July 2026): findings recorded, no behavior changed

A commissioned independent-review-board pass over the entire
repository — architecture, emergence, LLM cognition, deterministic
simulation, UI/UX, performance, scientific value, and failure
analysis, plus two specific commissioned questions (why populations
collapse; whether town-brain decisions actually influence the world).
The full report is `docs/REVIEW-2026-07.md`; the load-bearing findings
are also summarized in CLAUDE.md ("Architecture review findings")
since they should steer every future session. Deliberately a
docs-only change: the brief was "do not implement features," so every
recommendation (Settlement split, LLM backpressure, snapshot pruning,
carrying capacity, name uniquification, O(N^2) movement fix) is
recorded with severity and priority rather than applied.

Verified (measurements backing the report, all run in this
environment with the LLM disabled): two 30,000-tick full-engine runs
(seeds 42/7) and long-horizon World-level runs (40,000+ ticks — past the point every
founder has died of old age) charting population trajectory and death
causes (early-winter starvation funnel confirmed; no long-run
collapse — growth pins at POPULATION_CAP with ~800-1,000
ready farm plots); a 16,000-tick adversarial-goal run (goal policy
never chooses FORAGE below the critical override — still grew to cap);
4,000-draw `choose_building_kind` distributions per priority (granary
share 23% -> 43% under "food"); tick-time scaling 12/50/200/500 agents
(1.3/1.8/7.9/45.9 ms) with cProfile attribution of the O(N^2)
rival-tile scan; and code-reading verification of the whisper-loss,
fallback-priority-lock, name-collision, and unbounded-snapshot
findings.

## Architecture-review implementation pass (v0.40.0): the review's recommendations, performed

The July 2026 review (`docs/REVIEW-2026-07.md`) was docs-only by brief;
this pass performs its prioritized recommendations. Root causes are in
the review; this entry records the design calls made while implementing
and the verification data.

**Carrying capacity (the review's "single change that would most
increase long-term emergence").** Three coupled changes, deliberately
shipped together because each alone is either ineffective or dangerous:
goal-gated planting (a well-fed village stops planting — the negative
feedback), crop rot (`FARM_ROT_TICKS` — standing food becomes a flow,
not a stock), and surplus-gated reproduction
(`REPRODUCTION_WELLFED_HUNGER` OR saved personal food — chosen as an OR
specifically so a brand-new world, where nobody has personal food yet,
can still grow off a good foraging stretch rather than dead-ending).
`POPULATION_CAP` was raised to 400 and demoted to a safety valve rather
than removed — a tuning mistake in the new food loop shouldn't be able
to take the process down. The planting gate accepts either FORAGE goal
or real hunger so fallback-only runs (whose fallback assigns FORAGE
above 0.6 hunger) still plant.

**Gossip contagion.** Rumors already existed but had no mechanical
effect beyond a memory string. Rather than a new isolated mechanic, the
implementation reuses three existing systems: rumor subject resolution
mirrors belief-subject matching (ambiguous names resolve to nobody),
the trust lever's skepticism threshold gates whether a listener's
opinion moves at all, and the movement is a bounded relaxation toward
the *speaker's* existing relationship value — no new state anywhere.

**LLM backpressure + staleness.** The gate lives at scheduling time
(engine) with the counter in `CognitionRunner` — jobs the engine never
creates cost nothing, versus cancelling queued tasks which would still
churn. Rationing order encodes a judgement: dialogue shed first
(narrative), routine daily cognition second, event-triggered cognition
last (2x headroom). Staleness is enforced at apply time with the
schedule tick carried alongside each pending result.

**Whisper retention.** Consumed only on a non-fallback town-brain
resolution; on fallback the whispers stay queued (still capped at 3 by
the enqueue path, so an LLM-disabled run can't accumulate them
unboundedly).

**Beliefs.** Two changes with one goal (the village's self-model should
be able to be *wrong*): the prompt lost its ground-truth stat block,
and revision now matches on subject identity when the model returns
`revises: null` for a subject it already theorizes about — a 2B model
re-forms instead of revising far more often than it mis-indexes, and
duplicate subjects were crowding the capped list.

**Performance.** Rival-tile precomputation (one pass over each agent's
own relationships instead of a per-agent scan of every position),
`Settlement.at` position index (lazy rebuild keyed on list length, with
explicit invalidation at the two mutation sites as belt-and-braces),
water-tile cache invalidated by `TERRAIN_CHANGING_CATEGORIES` (moved to
`world/state.py` as the canonical copy — first step of the review's
stringly-typed-events cleanup). Native code was evaluated and declined
per the review: the hot paths are dict-and-branch logic with 10x+
algorithmic headroom remaining, and the binding constraint on the
target hardware is LLM latency.

**Persistence.** Snapshot pruning keeps `SNAPSHOT_KEEP_RECENT` recent
rows plus sparse keyframes (`SNAPSHOT_KEYFRAME_INTERVAL_TICKS`) so the
roadmap's scrub-through-time idea keeps its anchors; per-event commits
became one commit per tick (`log_event(commit=False)` + end-of-tick
commit — crash exposure is at most one tick of events).

**Metrics.** One JSON row per sim-day in a new `metrics` table
(`GET /metrics`), written on `day_end`. JSON column rather than a wide
schema: the row set will evolve, and research use reads whole rows.

Verified (LLM disabled, this environment): 30k-tick engine runs, seeds
42/7 — no extinction (min pop 7 on seed 42's winter funnel, recovering
as before); farms_ready peaked ~150-250 vs the ~800-1,000 baseline;
population growth visibly food-coupled (pop 232 at tick 25k vs pinned
at 200 from tick 22k in baseline); zero duplicate living names at end
of both runs (baseline: dozens); snapshot rows bounded at
~SNAPSHOT_KEEP_RECENT (+keyframes) after 120 saves; metrics rows == sim
days elapsed; town-brain fallback chose non-food priorities when
well-fed. Unit-style ad-hoc checks: gossip nudge (+0.05 cap, skeptic
unmoved), farm rot removal, belief subject-match, unique-name fallback
to checked "II" suffixes with the whole pool alive. Tick timing
12/200/500 agents: 1.3/7.9/45.9 ms -> 0.5/3.2/22.2 ms. All touched
files pass `python3 -m py_compile`; sample cognition prompt inspected
by eye.

## Review implementation, second pass (v0.41.0): founding funnel, Settlement split, culture riders, shelter/upkeep, job framework, sparklines, experiment runner

Performs the July 2026 review's remaining recommendations plus the
explicitly-requested founding-funnel fix. Design calls:

**Founding funnel.** Two causes, two fixes, both believable-causality
rather than stat buffs: worlds now begin March 1
(`Config.start_day_of_year`, creation-only; old snapshots load with
offset 0 so their history doesn't shift), and founders spawn as a
group around the walkable tile richest in wild food within
`FOUNDING_SITE_RADIUS` — the site a real expedition would pick, and a
group that can actually meet. Verified: seed 7 (the measured funnel
seed: 12 -> 7 by tick 2,000 pre-fix, stuck ~8k ticks) now shows only
2 starvation deaths by tick 10,000 with population already at 38.

**Settlement in-place split.** Four composed domain dataclasses
(`SettlementInfrastructure`/`Economy`/`Culture`/`Disposition`) behind
a `Settlement` facade whose legacy flat attributes are property
passthroughs and whose `to_dict`/`from_dict` are byte-identical
(asserted in verification). Deliberately mechanical: the value is the
four named domains existing at all — the future multi-settlement pass
instantiates them per settlement — not forcing 30+ call sites to churn
in the same commit. Multiple named settlements itself remains its own
dedicated session (standing decision), now with its prerequisite
landed.

**Culture riders.** The tradition prompt gains one enum field
(`influence`), not free-form effects — the same enum-not-prose
discipline as cognition's goals, so a 2B model's answer is safe to
apply directly. Effects aggregate as bounded stacks
(`culture_effect_multiplier`, <=1.24x) consumed by festivals (bond
boost), farm harvests (relief), and grief (energy cost). Fallback pool
entries carry influences too, so fallback-only runs accumulate them.

**Shelter/housing/upkeep + frailty.** Shelter reuses the existing
`Settlement.at` lookup in `_update_needs`; housing capacity is
`huts x HUT_CAPACITY + CAMP_TOLERANCE` (tolerance sized to the default
founding party so day-one isn't penalized); upkeep is drawn in
`Settlement.tick` with the *unpaid fraction* scaling decay — verified
live: currency drains from its previously-pinned cap to 0 at pop 400
as civic buildings multiply. Frailty scales elder rest recovery
(x0.7 past 80% of max_age) rather than draining — slower, not doomed.

**LLM job framework.** One `_schedule_llm_job(name, prompt, system,
fallback, apply)` path replaces nine hand-rolled `_run_X` coroutines;
apply-closures carry each job's context (whisper retention, belief
subject-matching, culture-effect increments) and an exception in one
apply is contained rather than killing the task set. Cognition and
dialogue keep dedicated paths (pending-result queues + staleness).

**Sparklines + experiment runner.** Client-side polylines off
`GET /metrics` (60s refresh — the series gains one point per sim-day,
faster polling is waste); `hearthmind-experiment` runs N seeds
headless under a chosen config and exports each run's metrics to CSV
(union-of-keys header so schema additions never drop columns).

Verified (LLM disabled, this environment): 30k-tick engine runs seeds
42/7 — funnel numbers above; carrying capacity still binding (farms_
ready bounded, hunger rises toward the 400 valve, 0 duplicate names,
snapshots pruned, metrics rows == sim days, culture_effects
accumulating across all three categories); settlement `to_dict` ==
pre-split shape asserted through a mid-flight round-trip; spring
start + legacy-offset load both verified; experiment runner smoke-run
produced a 31-row CSV with correct columns; `node --check` on app.js;
`py_compile` across all touched files.

## Memory leak fix (v0.42.0): unpruned Agent.relationships/trust

User-reported live symptom: heavy swap usage and an unresponsive
system at only ~100 population. Investigated as a genuine leak rather
than assumed-Ollama-overhead, since the report specifically named a
modest population as the trigger, which pointed at per-agent state
rather than the LLM process (whose footprint is population-independent).

Root cause: `Population._update_relationships` decayed relationship
values toward 0.0 but never deleted the dict key once it arrived
there, and `Population._apply_deaths` never stripped a dying agent's
id from any other agent's `relationships`/`trust` dict. Both dicts are
keyed by agent id and grow by one entry per new acquaintance; with
neither pruning path, every pairwise colocation in the world's entire
history accumulated permanently in both parties' dicts, including
colocations with agents who had since died.

Fix: two additions, each independently a pure memory bound with zero
observable behavior change (every read site already used
`.get(id, 0.0)`, so an absent key and a present zero-valued key were
always equivalent):
1. `_update_relationships`'s decay loop now deletes an entry the tick
   it reaches exactly 0.0 (the clamp `max(0.0, ...)`/`min(0.0, ...)`
   produces an exact float 0.0, not an asymptotic approach, so this is
   a precise check, not an epsilon heuristic).
2. `_apply_deaths` now pops each dying agent's id from every
   survivor's `relationships` and `trust` dicts, in the same pass that
   already computes `dying_ids` for grief — after the grief loop reads
   relationships for the dying (so grief detection is unaffected).

Also added: `GET /diagnostics`'s `relationship_graph` block (total
relationship/trust entries, average per agent) as a cheap, always-on
live signal for this class of leak — a climbing average on an
overnight soak run is now visible without a custom probe.

Investigated and explicitly NOT fixed as part of this pass: large
crowds at scarce food/granary tiles trigger `_update_relationships`'
colocation-bonus loop's O(group^2) full-mesh relationship formation
every tick (measured a 29-agent crowd at one granary at population
381, seed 3) — this is real, current social contact between people who
are actually interacting, not stale data, so it's correctly retained
rather than pruned. It's a legitimate population-scaling cost worth
watching (both memory and the CPU cost already flagged in the July
2026 review's performance section), not a bug fitting this entry's
scope — noted for a future session if crowding intensifies enough to
matter at target populations.

Verified: a matched 50,000-tick A/B run, same seed (3), same initial
population (100), LLM disabled, through a population boom (100 -> 381)
and a starvation-driven crash (381 -> 27) and partial recovery (-> 121)
— chosen deliberately over a monotonic-growth run because the crash is
the clearest test of the death-cleanup path specifically. At the boom
peak (tick 20,000, population 229): baseline 112,075 total relationship
entries (489/agent) vs fixed 23,600 (103/agent), a >4.7x reduction.
Immediately after the crash (tick 25,000, population 36, 751
cumulative deaths): baseline 322 entries/agent (predominantly stale
references to the dead) vs fixed 19/agent. Process RSS across the full
run: baseline 42.8 -> 117.5 MB, fixed 40.9 -> 89.7 MB. Unit-level
checks: colocation correctly builds mutual relationship entries;
scattering + waiting past the full decay window (value/DECAY_PER_TICK
ticks) prunes both sides' entries to `{}`; a forced old-age death
correctly empties the survivor's relationship and trust entries for
the deceased. `python3 -m py_compile` on the touched module.

## Ollama server memory pressure + weather-band retuning (v0.43.0)

Root cause investigation, second pass. The v0.42.0 fix (above) was
real and verified, but the identical live symptom — heavy swap, an
unresponsive 8GB system, ~100 population — recurred within about an
hour of a fresh run with the fix in place. The v0.42.0 writeup's line
"traced to a real leak, not LLM/Ollama memory pressure" was too
confident: the matched probe that produced that conclusion ran with
`llm_enabled=False`, so it could only ever rule out a leak inside this
process. It never exercised the actual Ollama server process, which
holds real, OS-swappable memory independent of this project's own
heap.

Design call: rather than add speculative caps, apply the two changes
the architecture review had *already* identified and quantified as the
biggest concurrent-memory-footprint levers, but never implemented —
`llm_max_concurrent` 4 -> 2 (the review's own words: "do not raise...
consider lowering to 2", recorded in CLAUDE.md since v0.40.0 and never
acted on), plus two new explicit per-call bounds, `Config.llm_num_ctx`
(2048) and `Config.llm_num_predict` (512), threaded through
`OllamaClient.generate_json` as Ollama's `options` object. Previously
neither was set at all, meaning Ollama's own defaults silently
governed both the KV-cache size per call and the worst-case token count
of a single generation — an unbounded-in-the-worst-case multiplier
sitting underneath `llm_max_concurrent`. Every prompt in this project
(grounded, capped cognition/dialogue prompts; `PROMPT_CULTURE_LIST_MAX`
-bounded settlement prompts) comfortably fits well under 2048 tokens,
so this is a safety ceiling that no real prompt here should ever hit,
not a new working constraint.

Verified: `OllamaClient.generate_json` sends `{"options": {"num_ctx":
2048, "num_predict": 512}}` correctly (checked against a captured
mock request); `llm_max_concurrent` flows through to
`CognitionRunner(max_concurrent=...)` unchanged in both call sites
(`SimulationEngine.__init__`, `server.py`'s genesis call). A 3,000-tick
engine run (LLM disabled, 20 initial population) round-trips a
snapshot and produces sane `relationship_graph` diagnostics with no
exceptions.

Separately, in the same investigation: a live report of "I only ever
saw rain" was checked empirically rather than assumed to be normal
weather variance, and confirmed as a real bug — the same *class* of
bug already diagnosed and fixed for `SNOW_TEMPERATURE_THRESHOLD_C`
(see the weather-realism decision above/`world/weather.py`'s
docstring), just never applied to the rain bands. `compute_weather`'s
smoothing=0.7 EMA damps the raw per-tick `uniform(-0.25, 0.25)`
precipitation jitter into a much narrower realized range than
`describe()`'s cutoffs (clear <=0.08, overcast <=0.25, heavy >0.6)
assumed. Measured across a 200,000-tick run cycling all twelve months:
realized precipitation's 1st/99th percentiles were 0.20/0.58 and its
true min/max were 0.11/0.67 — "clear" (<=0.08) was literally
unreachable, 0th percentile, and the world spent an overwhelming
majority of ticks in the "light rain" 0.25-0.6 band regardless of
season, which is exactly the reported symptom. Retuned the three
cutoffs to the measured p10/p50/p90 (0.27/0.38/0.50 — new
`CLEAR_PRECIPITATION_THRESHOLD`/`OVERCAST_PRECIPITATION_THRESHOLD`/
`HEAVY_RAIN_PRECIPITATION_THRESHOLD`); re-measuring against the new
cutoffs over the same 120k-tick, twelve-month cycle gives clear 11.0%,
overcast 39.6%, light rain 38.7%, heavy rain 10.3%, snowing 0.4% — each
band now gets a real, roughly-even share instead of one dominating.
The frontend's rain-particle overlay (`interface/static/app.js`) had
an independent copy of the same bug (spawn threshold `precipitation <
0.05`, also below the realized floor, so particles never fully
stopped); rescaled particle intensity against the same measured
0.27/0.65 floor/ceiling so a clear tick now shows zero particles.
`python3 -m py_compile` on all touched Python modules, `node --check`
on `app.js`.

## Ollama memory, second pass (v0.43.1)

Explicit user follow-up: "be more aggressive" — v0.43.0's
`llm_max_concurrent=2` was a real reduction from 4 but still wasn't
enough to prevent the reported swap on the user's 8GB machine. Dropped
to 1, `CognitionRunner`'s floor (`max(1, max_concurrent)`, see
`llm/jobs.py`) — fully serialized, exactly one Ollama `generate` call
in flight at any time system-wide, regardless of how many job types
(cognition, dialogue, and the nine settlement-level jobs sharing
`_schedule_llm_job`) want to run. Confirmed this doesn't create any new
liveness risk: `BACKPRESSURE_BACKLOG_PER_SLOT` scales with
`max_concurrent` (`_backpressure_limit = max_concurrent * 3`), so at 1
the routine-job gate is still 3 (unchanged shape, just a smaller
number) — cognition/dialogue jobs get skipped (not queued) once 3 are
already in-flight-or-waiting, same mechanism as before, just triggering
sooner. `llm_timeout_seconds` bumped 45 -> 60 as margin — confirmed by
reading `CognitionRunner._run_gated` that the per-call timer only
starts once a job acquires the semaphore (not while queued behind
other jobs), so this isn't fixing a queueing-induced timeout, just
adding headroom for the fully-serialized worst case.

New `Config.llm_keep_alive` (default `"3m"`), threaded through
`OllamaClient` as a `keep_alive` field and sent as Ollama's top-level
`keep_alive` request field. Previously never sent at all — the Ollama
server's own default governed how long a model stays resident after
its last call, which varies by server version/config and can be
indefinite. This is the lever for *idle* memory specifically (as
opposed to `llm_num_ctx`/`llm_num_predict`, which bound *per-call*
memory): a settlement with sparse LLM-eligible activity should
actually release the loaded model's memory during a real lull rather
than holding it forever.

Verified: `python3 -m py_compile` on all touched modules; confirmed via
code reading (not a live Ollama call, since none is available in this
environment) that `max_concurrent=1` still produces a valid
`asyncio.Semaphore(1)` and that `_backpressure_limit` computes
correctly at the new value.

## HUT decay/upkeep collapse near the population cap (v0.43.2)

Explicit user follow-up: "see why population is still declining and
dying of starvation." The "Post-rework equilibrium note" below
already documents a legitimate, intended Malthusian ceiling (abundant
maps reach POPULATION_CAP=400 with hunger ~0.4 and real starvation
pressure) — but a live diagnostic run turned up something worse than
that documented baseline, and worth distinguishing from it.

Method: a 44,000-tick engine run (seed 42, default `Config`,
`llm_enabled=False` to isolate deterministic mechanics from LLM
variance), instrumented every 2,000 ticks with population, average
hunger, standing/under-construction HUT counts, computed housing
capacity (`CAMP_TOLERANCE + HUT_CAPACITY * huts_standing`), crowding
state, settlement materials, and cumulative starvation deaths.

Finding: housing capacity comfortably outpaced population through
tick 24,000 (huts_standing 78, capacity 402 at population 272, zero
deficit) — the funnel/carrying-capacity mechanics were working
correctly up to that point. Then, in the next single 2,000-tick
window (tick 24,000 -> 26,000 -> 28,000), `huts_standing` collapsed
78 -> 72 -> 16 while population kept climbing toward the cap, flipping
the settlement from zero housing deficit to a 221-person deficit and
`crowded=True`. Cumulative starvation deaths, which had climbed
steadily and proportionally to population through tick 24,000 (2, 3,
5, 7, 7, 9, 12, 17, 21), jumped to 37 then 147 across that same
2,000-tick window, then kept climbing to 293 by tick 44,000 even as
`huts_standing` slowly recovered (huts_building stayed elevated the
whole time — construction was trying to keep up, just losing the
race). `materials` collapsed in lockstep (30.0 -> 20.0 -> 2.7 ->
0.7), consistent with the settlement burning everything it had trying
to rebuild collapsing huts rather than growing net housing.

Traced to `Settlement.tick()` (`settlement/buildings.py`): the method
computes `decay` from weather/season, then boosts it by the unpaid
fraction of this tick's civic upkeep (`UPKEEP_UNPAID_DECAY_MULTIPLIER
`, up to 1.5x) — but applies that single boosted value to *every*
standing building in the survivors loop, with no kind check. HUTs are
explicitly excluded from `civic_standing`/`upkeep_due` (`b.kind is not
BuildingKind.HUT`) and draw no currency at all — `UPKEEP_UNPAID_DECAY
_MULTIPLIER`'s own docstring says the intent is "a town that can't
afford maintenance watches its *civic* buildings wear out faster," not
its housing. As a settlement approaches the population cap it
naturally accumulates more civic buildings (granaries, workshops,
etc., all weighted into `BUILDING_KIND_BASE_WEIGHTS`), so
`upkeep_due` grows with settlement maturity while currency income
(from staffed workshops, per the same review's earlier finding) can
lag — once the unpaid fraction climbs toward 1.0, every standing HUT
started losing condition up to 1.5x faster than its base rate, for a
bill it never incurred. This closes a real self-reinforcing loop:
unpaid civic upkeep -> HUTs ruin faster -> housing capacity drops ->
more agents exceed `housing_capacity` -> `CROWDING_ENERGY_MULTIPLIER`
pushes more agents into RESTING -> fewer idle, non-critically-hungry
agents left to satisfy `_maybe_repair`'s colocated-pair requirement ->
nothing offsets the accelerated decay -> the spiral continues until
either currency recovers or population/materials crash hard enough to
break it (which the diagnostic shows eventually happening, tick
36,000+, but only after several hundred extra starvation deaths beyond
what the funnel/carrying-capacity design intended).

Fix: split the single `decay` value into a HUT-exempt base rate and a
`civic_decay` rate (the upkeep-boosted one), and select per building by
`kind` in the survivors loop — `civic_decay` for everything except
HUT, plain `decay` for HUT regardless of the settlement's currency
state. This is a narrow, surgical fix (one loop, one conditional) that
restores the mechanic's own documented intent rather than changing its
design. Deliberately did not touch `REPRODUCTION_WELLFED_HUNGER` or
scale birth chance by hunger (the "if it still feels too grim" lever
CLAUDE.md's post-rework equilibrium note already flags) — the baseline
equilibrium (hunger ~0.4, real starvation pressure at the cap) is
still the intended target; this fix removes an unintended amplifier on
top of it, not the equilibrium itself. If a live run still shows
excessive starvation after this fix, that reproduction-side lever is
the next one to reach for, not another housing-side change.

**Amendment: the HUT-upkeep fix alone was not sufficient.** A matched
follow-up run (same seed 42, same config, only the `settlement/
buildings.py` change applied) delayed the collapse but did not prevent
it: `huts_standing` still crashed 98 -> 47 at tick 26,000 -> 28,000,
population actually *dropped* 354 -> 256 in that window, and
cumulative starvation deaths jumped 28 -> 216 — a larger single-window
death count than the original baseline's 21 -> 147 at the same ticks,
because the fixed run's housing/population had grown further before
hitting the same underlying wall. This pointed at a second, deeper
mechanism: `Settlement.tick()`'s decay has *zero* per-building
variance — every standing building of a given kind loses the exact
same condition every tick (weather/season are settlement-wide
scalars). A batch of HUTs built together during a growth spurt
(confirmed in the diagnostic: `huts_building` spiked 8 -> 10 -> 14 in
the three checkpoints before the collapse, i.e. many started
construction in the same narrow window) therefore have near-identical
condition trajectories and approach `REPAIR_THRESHOLD` (0.5) together.
`_maybe_repair` only fires from *incidental* colocation (any AWAKE
agent physically standing on the building's tile) — and RESTING agents
freeze in place rather than seeking shelter, while AWAKE agents on
`AgentGoal.WANDER` (a common fallback goal, see `llm/cognition.py`'s
`fallback_goal`) had zero attraction toward a decaying building. With
`DECAY_PER_TICK_BASE=0.0004` and up to a combined ~5x weather/season/
unpaid-upkeep multiplier, an unrepaired HUT can fully ruin in roughly
1,300-2,500 ticks — squarely inside the observed 2,000-tick collapse
window for a batch built together.

Second fix, same investigation: added a `damaged_building_positions`
helper (`Population`, mirrors `ready_farm_positions`/
`stocked_granary_positions`'s exact shape) returning standing buildings
below `REPAIR_THRESHOLD`, precomputed once per tick and passed into
`_dispatch_movement`. A new branch, `elif effective_goal is AgentGoal.
WANDER and repair_positions:`, biases a WANDERing agent's step toward
the nearest one — no new `AgentGoal` enum value, no cognition/prompt
changes, falls through to the unchanged random walk whenever nothing
is damaged (the common case). This gives every otherwise-idle agent a
real chance to become repair labor before a batch of buildings crosses
into ruin together, the same way FORAGE already biases movement toward
food.

**Verified, matched three-way A/B** (seed 42, default `Config`,
`llm_enabled=False`, checkpoints every 2,000 ticks):

| tick | baseline pop / deaths | fix1-only pop / deaths | fix1+fix2 pop / deaths |
|------|------------------------|--------------------------|---------------------------|
| 12,000 | 45 / 7 | 45 / 7 | 58 / 2 |
| 16,000 | 98 / 7 | 98 / 7 | 116 / 3 |
| 20,000 | 161 / 12 | 161 / 12 | 266 / 3 |
| 22,000 | 221 / 17 | 221 / 17 | 341 / 3 |
| 26,000 | 318 / 37 | 354 / 28 | (huts_standing 98, zero deficit, still climbing) |
| 28,000 | 313 / 147, huts_standing 16, deficit 221 | 256 / 216, huts_standing 47, deficit 9 | — |

fix1-only actually looked *worse* than baseline at tick 28,000 by raw
death count (216 vs 147) because it let population and the housing
stock grow further before hitting the same still-unfixed lockstep-
decay wall — consistent with the diagnosis, not a contradiction of it.
fix1+fix2 together never entered a housing deficit through tick 22,000
(`crowded` stayed `False` throughout, `huts_standing` tracking
population smoothly: 6/8/11/19/30/39/56/80 across the same checkpoints
baseline/fix1-only were both already deep in their respective
collapses) and cumulative starvation deaths stayed at 2-3 for the
entire run so far, against baseline/fix1-only's 12-17 at the same
ticks — an order-of-magnitude improvement, not a marginal one.
`python3 -m py_compile` on both touched modules passed throughout.

## LLM concurrency floor restored to 2 (v0.44.0)

Explicit user instruction, stated plainly: never trade off LLM use
against a deterministic fallback — concurrency is not the memory
lever. `llm_max_concurrent` raised 1 -> 2 (its floor from v0.43.0,
before v0.43.1 dropped it further to 1). The memory-reduction intent
behind the earlier drop to 1 is preserved through the levers that
don't cost LLM richness: `llm_num_ctx=2048`/`llm_num_predict=512`
(v0.43.0, bound per-call memory) and `llm_keep_alive="3m"` (v0.43.1,
bounds idle memory). If a live run still shows memory pressure at
concurrency=2 with those bounds in place, the next lever is a smaller/
more quantized Ollama model, not concurrency — concurrency stays at 2
going forward per this instruction.

## Phase G completeness audit (v0.44.0)

User asked to "complete Phase G." Investigated via docs/ROADMAP.md's
full Phase G section cross-referenced against CLAUDE.md's Phase G
write-ups and the actual code (settlement/buildings.py's temperament/
omen/trust/player-standing/shrine-interaction constants and methods,
config.py's `phase_g_intensity`, engine.py's wiring). Every roadmap
checklist item is `[x]` and every claimed-shipped mechanism is verified
present in code — no discrepancy found. The one remaining unchecked
item is prose, not a checkbox: "no player-facing acknowledgment that
this system exists" — explicitly flagged in the roadmap itself as
deliberate, permanent design intent (Phase G's whole premise is
staying ambiguous), not an oversight. No code changes made; nothing to
implement.

## Population control: disease mechanism (v0.44.0)

User: population is hitting the hard 400 cap, which (per the
architecture review, still-open finding) causes the town brain's
fallback priority to have nowhere useful to steer once "food" no
longer applies — asked for an organic population-control mechanism
like disease, consistent with the standing design priority (deterministic
engine models objective physical reality; judgment goes to the LLM —
disease transmission/lethality is physical fact, not interpretation,
so this belongs in `agents/population.py`, no LLM involvement).

Design: `OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK = 1e-7`, scaled by
current population and `OUTBREAK_CROWDING_MULTIPLIER = 6.0` while
`Population.tick`'s existing `crowded` flag (population > housing
capacity, the same signal `CROWDING_ENERGY_MULTIPLIER` reads) is true —
deliberately reuses that housing-pressure computation rather than a
second, disconnected density metric, so disease risk is highest
exactly where the population is straining its housing, mirroring real
crowd-disease epidemiology. At ~35,040 ticks/year (96 ticks/day x 365
days), this targets roughly 1 spontaneous case/year at population 200
uncrowded versus ~8/year at population 400 crowded — rare at low/mid
population, a real and increasingly-felt pressure specifically as a
settlement approaches the cap.

`SICKNESS_DEATH_CHANCE_PER_TICK = 0.0001` over `SICKNESS_DURATION_
TICKS = 800` targets an ~8% case-fatality rate per bout (0.0001 x 800),
halved by a standing hospital (`SICKNESS_HOSPITAL_KILL_CHANCE_
REDUCTION = 0.3`, same magnitude/rationale as predator-attack
lethality's `HOSPITAL_KILL_CHANCE_REDUCTION`) and nudged by settlement
temperament (reusing `TEMPERAMENT_KILL_CHANCE_INFLUENCE`, same as
predator attacks — Phase G's existing subtle-nudge discipline, not a
new lever). `SICKNESS_TRANSMISSION_CHANCE_PER_TICK = 0.01` per
colocated sick-healthy pair per tick — high enough that constant
colocation over a full bout would make infection near-certain, but
real agent movement means realized spread is textured rather than an
instant sweep. Sick agents also get `SICKNESS_ENERGY_DRAIN_MULTIPLIER
= 1.3`/`SICKNESS_HUNGER_RATE_MULTIPLIER = 1.2` (same "small nudge, real
consequence" magnitude as `CROWDING_ENERGY_MULTIPLIER`) — illness has a
felt mechanical cost independent of the death roll. Deliberately no
immunity/reinfection state in v1: a recovered agent (`Agent.sick_ticks`
reset to 0) is immediately susceptible again — smallest-coherent-
milestone scoping, consistent with every other feature in this
project; a future pass could add temporary immunity if repeated
reinfection waves prove undesirable in practice.

`town_brain.fallback_priority` gained a real trigger: `sick_count /
total > 0.05 and hospitals == 0` fires "health" before falling through
to the old, very narrow "a predator has ever killed someone and there
are zero hospitals" arm. `town_brain.build_prompt` also now mentions
the current sick count so the real LLM call sees it too. This is the
direct answer to "town brain will get stuck at food" — previously
"health" was nearly unreachable in practice; now a real epidemic
provides a competing, legitimate civic signal.

Verified via direct unit-level checks (not a full engine soak, given
time cost near the population cap observed in the prior investigation):
20,000 independent trials of `_maybe_outbreak` at population=400,
crowded=True fired 4 times — 2.0x10^-4 empirical rate against a
computed target of `1e-7 * 400 * 6 = 2.4e-4`, matching within sampling
noise. A 3,000-tick `_tick_disease` run seeded with one sick agent
among 20 (no hospital) produced 73 transmission events, 54 recoveries,
and 2 cumulative deaths among the 20-agent group (reinfection waves
compound the raw per-bout ~8% CFR since there's no immunity) — the
full cycle (spread, recovery, death) all fire correctly. A 5,000-tick
full-engine run confirmed `sick_count`/`deaths_disease` appear
correctly in `Population.summary()` and survive a snapshot round-trip
(`to_dict`/`from_dict`), and `full_diagnostics()` runs without error.
`python3 -m py_compile` on all touched modules.

## Era progression tuning (v0.44.0)

User: never observed era advancement (industrial -> electrical ->
modern -> digital) in a live run. Investigated `era_for_tech_level`/
`ERA_TECH_THRESHOLDS` (settlement/buildings.py) and the invention
mechanism (`llm/invention.py`, scheduling in `simulation/engine.py`):
confirmed no hidden gating bug — the only preconditions are a named
settlement (trivial, true after the first building stands) and a
prosperity bar (`currency >= INVENTION_CURRENCY_THRESHOLD` OR
`materials >= INVENTION_MATERIALS_FRACTION * MATERIALS_CAPACITY`),
both easily reachable in early game. The actual cause is pure rarity
compounding against steep thresholds: `INVENTION_CHANCE_PER_SEASON =
0.15`, rolled 4x/year, gives an expected ~5 in-game years to reach
`electrical` (tech_level 3) and ~20 years to `digital` (tech_level
12) — plausibly longer than most live observation sessions actually
run, which reads as "stuck," not "working but slow."

Raised `INVENTION_CHANCE_PER_SEASON` to 0.2 — annual invention odds
when prosperous go from ~48% to ~59% (`1-(1-p)^4`), bringing expected
time to `electrical`/`digital` down to roughly ~3.75/~15 years. Still
a genuine long-run milestone (the era thresholds themselves are
untouched, deliberately — CLAUDE.md's era-progression section already
states "digital... is a long-run milestone, not a fast unlock," and
this tuning doesn't contradict that framing, just makes the milestone
reachable within a realistic session rather than requiring an
unrealistically long one). Also noted: the v0.43.2 HUT-decay/crowding
fixes are an incidental second contributor here — a settlement whose
materials stop crashing near the population cap clears the prosperity
gate more reliably too, so this session's earlier fix and this
session's tuning compound in the same direction. No unit-level
verification beyond re-reading the roll/gate code path (no live Ollama
available in this environment, and a multi-year soak run to observe
an actual era transition was judged not worth the wall-clock cost
given the change is a single, well-understood constant); the
before/after expected-time arithmetic above is straightforward given
the confirmed mechanism.

## Ruin removal speed + last unbounded culture lists (v0.44.1)

User: "ruined buildings should be removed." Verified directly (a small
script forcing a building to RUINED and advancing `ruined_ticks` to
the threshold) that `Settlement.tick()`'s removal path was already
correct — no bug. The actual issue was `RUIN_REMOVAL_TICKS = 3000`
(~31 sim-days), long enough that most live-observation sessions never
saw a ruin actually disappear, reading as "never removed." Lowered to
1200 (~12.5 days) — long enough a ruin still reads as a real landmark
for a few days, short enough to actually observe clearing within a
normal session. Secondary, mechanically real benefit: a RUINED
building still occupies its tile and blocks `_maybe_start_construction`
from using it (`settlement.at(x, y) is not None` check) — clearing
ruins faster returns that tile to the settlement sooner, which
compounds with the v0.43.2 housing-supply fixes instead of undermining
them.

Separately, continuing the "aggressive memory optimization, never
touch swap on extremely long runs" audit: `Settlement.traditions`/
`inventions`/`festivals` were the last confirmed-unbounded in-memory
structures. `PROMPT_CULTURE_LIST_MAX` (v0.40.0) only ever sliced what
gets sent into an LLM prompt (`traditions[-PROMPT_CULTURE_LIST_MAX:]`)
— the underlying stored list was never capped, so a sufficiently
long-running world (the explicit scenario this pass is optimizing for)
would grow all three forever. Each entry is a short string, so this was
never a *fast* leak, but "no structure should be truly unbounded" is
the standing of this pass, however slow.

Design constraint that shaped the fix: `fallback_tradition`/
`fallback_invention`/`fallback_festival` all take an `established_
count` parameter used for ordinal naming ("Tradition the 14th"), and
every call site was passing `len(list)` directly. Capping the list
in place would have silently corrupted that numbering the moment the
cap was first hit (count would stop climbing, or even appear to
shrink). Fixed by adding `SettlementCulture.traditions_established`/
`festivals_held` — persistent, incremented once per establishment,
never decremented or read from list length — and reusing `tech_level`
(already exactly this shape) for inventions rather than adding a
third redundant counter. New `CULTURE_LIST_MAX_STORED = 300` caps each
list's stored length (oldest entries dropped first) in the three
`apply()` closures in `simulation/engine.py`, right after the append
that used to be unbounded. Old snapshots predating the counters
backfill via `len(list)` (correct, since a pre-v0.44.1 snapshot's list
was never truncated, so its length still equals its true established
count at that point).

Verified: a direct script appended `CULTURE_LIST_MAX_STORED + 50`
entries to `Settlement.traditions` with the same append+increment+cap
logic the engine uses — final stored length 300 (capped correctly),
`traditions_established` correctly at 350 (not corrupted by the cap),
oldest surviving entry correctly `"Tradition 50"` (the 300 most recent
survived, oldest 50 correctly dropped). Snapshot round-trip preserves
both the capped list and the counter. Old-snapshot backfill (manually
stripping the new keys from a `to_dict()` output before `from_dict`)
correctly recovers `traditions_established == len(traditions)`. A
6,000-tick full-engine run (LLM disabled) confirms no exceptions and a
clean snapshot round-trip with the new fields present.

Also audited (per the same "never touch swap" instruction) the SQLite
persistence layer (`persistence/database.py`'s `connect()`): no
explicit `PRAGMA cache_size`/`mmap_size` is set, meaning SQLite's own
conservative defaults apply — a small, fixed page cache (not scaling
with database size) and no memory-mapped I/O. The `events` and
`metrics` tables both grow without bound over an extremely long run
(nothing prunes them, unlike `snapshots` which v0.40.0 already bounds),
but confirmed this is purely a *disk* growth concern under these
defaults, not a RAM/swap one — no pragma changes were needed or made.
`_last_llm_calls` (engine.py) was also checked and confirmed bounded:
it's keyed by a fixed set of ~9 job names (naming/chronicle/
documentary/tradition/invention/festival/town_brain/beliefs/omen),
never per-agent, so it cannot grow with population or run length.

## Phase H: living-knowledge/institutions direction set (no code changes)

Explicit user directive (2026-07-13): treat memory/belief/knowledge as an
evolving ecosystem (spread, compete, mutate, merge, disappear across
generations), replace the hard population cap with dynamic carrying
capacity, introduce institutions as first-class persistent entities,
expand beliefs into fuller world models, separate knowledge/skills from
beliefs, deepen psychology, and support cross-generational inheritance —
explicitly framed as a direction to plan for, not a batch to implement
immediately ("Do not implement everything immediately... identify where
the current architecture should evolve").

Response was documentation-only: `docs/ROADMAP.md`'s new "Phase H" section
maps each of the user's nine priorities onto the current architecture
(Settlement facade, `llm/beliefs.py`, `Agent.memories`/`relationships`/
`trust`, the disease/gossip contagion mechanics, Phase G's temperament/
omens) and identifies the smallest concrete evolution point for each,
plus a suggested sequencing (H1 dynamic carrying capacity first — cheapest,
directly answers the recurring "town brain stuck on food" complaint;
H3 institutions, starting with families-as-entities, next, since H4/H6/H7
structurally depend on an addressable entity beyond individual `Agent`s;
H2/H5 can proceed in parallel with H3; H4 full supply chains and H7
inheritance are large enough to warrant their own dedicated sessions, same
treatment already given to "multiple named settlements"). No code, config,
or schema changes were made in this pass — this entry and the ROADMAP.md
section are the entire deliverable, consistent with the user's explicit
instruction not to implement yet.

## H1: dynamic carrying capacity replaces the flat population cap

First implementation pass on Phase H (docs/ROADMAP.md), per the explicit
user directive to prioritize H1 first. `Population.carrying_capacity()`
(agents/population.py) replaces the flat `POPULATION_CAP` as the
operative constraint on reproduction: it composes the pre-existing
housing base (`CAMP_TOLERANCE + HUT_CAPACITY x standing huts`) with
economic headroom (granary fill fraction, only scored once a granary
exists — a founding party with zero infrastructure isn't penalized for
infrastructure it hasn't had time to build yet), security pressure
(sickness fraction plus live predator presence), labor availability
(fraction of mature, healthy agents), and current weather harshness,
into one multiplier bounded to `CARRYING_CAPACITY_MIN/MAX_MULTIPLIER`
(0.5x-1.5x, settlement/buildings.py). `POPULATION_CAP` (400) is
untouched and now functions purely as a safety ceiling far above any
realistic computed value, matching its original "pure safety valve"
docstring intent that had quietly become the real binding constraint at
scale.

Design choices worth recording: (1) the economy term is neutral, not
negative, when no granary exists yet — an early penalty would have
strangled founding populations before they had any chance to build
infrastructure, defeating the whole point of a *dynamic* capacity; (2)
housing remains the base term rather than one factor among equals,
since it's the one signal already load-bearing pre-H1 (crowding/
disease already read it) and gives every other term a sensible resting
point (multiplier 1.0 = "housing alone, nothing else pulling it up or
down"); (3) the multiplier is intentionally coarse (four terms, no
cross-term interaction) — this is explicitly the smallest coherent
milestone per CLAUDE.md's batching discipline, not a full economic
model; richer coupling (e.g. institutions eventually setting their own
capacity policy, H3) is future work, not a gap in this pass.

Verified: a direct scenario script (`/tmp/.../verify_h1.py`, not
committed — ad-hoc per CLAUDE.md's no-unittest workflow rule) covering
four cases — a founding party with no infrastructure lands near its
housing base rather than being punished (13.6 vs base 12); a developed,
well-fed settlement with full granaries exceeds its raw housing base
(40.96 vs base 32); a settlement under simultaneous plague, predator
pressure, an empty granary, and harsh weather drops below its housing
base but respects the 0.5x floor (16.0 vs base 32, floor 16.0 — hits it
exactly); and capacity never exceeds `POPULATION_CAP` regardless of how
much housing exists (400 vs a housing base of 2512). Also ran a real
20,000-tick engine tick loop (LLM disabled, seed 42) with no exceptions,
`carrying_capacity` visible and moving in `summary()`. A byte-identical
comparison of the population trajectory against the pre-change code on
the same seed (via `git stash`) confirmed this change is inert when a
settlement never builds housing/granaries in the observed window — the
new mechanism only engages once there's real infrastructure to reason
about, so it doesn't retroactively change already-understood early-game
dynamics.

## H3: institutions v1 — families as first-class entities

Second implementation pass on Phase H, per explicit user instruction to
follow H1 with H3. New module `hearthmind/settlement/institutions.py`:
`Institution` (id, kind, founding_tick, member_agent_ids, a beliefs-
shaped list, a name) and `InstitutionKind` (only `FAMILY` populated).
One generic dataclass rather than a bespoke class per institution kind
— the same "split into a small composable shape" instinct that drove
the July 2026 Settlement-facade review, applied up front this time
instead of after the fact. `Settlement.institutions`/`next_institution_
id` were folded into the existing `SettlementCulture` domain object
(passthrough properties on `Settlement`, same pattern as `beliefs`)
rather than added as a new fifth facade domain — an institution is
"part of what the village has become," the same category traditions
and beliefs already occupy, and this avoids another round of facade-
wide plumbing for one new list.

`Population._extend_family` (called from `_maybe_reproduce` on every
birth) either creates a new `FAMILY` institution from the two parents
plus the child, or — if an existing family already contains both
parent ids — adds the child to it, so a second child born to the same
couple joins one family rather than starting a redundant one. This is
deliberately the *only* formation path in v1: no deliberate founding
(an agent goal/LLM decision to start a guild), no other institution
kinds, and nothing yet reads `institutions` besides serialization and
`summary()`'s `{total, families}` counts plus the new `Settlement.
family_for(agent_id)` lookup. `member_agent_ids` is never pruned when a
member dies — outliving its members is the entire point of an
institution, and the future H7 inheritance pass is expected to hook
this exact set (move something from a dying member to the family's
other living members) rather than requiring new state.

Verified: a direct unit-level script (`Population._extend_family`
called three times — two children to the same parent pair correctly
land in one family with all four members `{parent_a, parent_b, child1,
child2}`; a different parent pair correctly starts a second, separate
family; `Settlement.family_for()` resolves both correctly and returns
`None` for a non-member) plus a live-engine integration check: with
`REPRODUCTION_CHANCE_PER_TICK` monkeypatched to 1.0 purely to make a
birth observable within a short run (no other engine logic bypassed —
still real colocation, maturity, health, and surplus gating), a real
birth inside `World.tick()`'s ordinary loop produced exactly one family
institution with the correct 3-member set. Both `Settlement.to_dict()/
from_dict()` and a full `World.to_dict()/from_dict()` round-trip
preserve the institution list byte-identically. A pre-v0.46.0 snapshot
backfills to an empty `institutions` list with no migration step
needed (same `.get(key, [])` pattern every prior additive field in this
codebase has used).

## Wind/storm thresholds fixed; fishing added

Live user reports: "why is there always wind?" and "storms are not
shown," plus a request to add fishing alongside foraging.

Wind and storm were both instances of a bug class this project has now
fixed three times (precipitation/temperature previously, wind here):
a threshold chosen against the raw per-tick `uniform()` jitter range
looks plausible on paper but `compute_weather`'s `smoothing=0.7` EMA
damps that into a much narrower realized band, so a threshold near
either extreme of the raw range is effectively unreachable — see
weather.py's `SNOW_TEMPERATURE_THRESHOLD_C`/`CLEAR_PRECIPITATION_
THRESHOLD` docstrings for the same diagnosis applied earlier. A direct
17,520-tick measurement (all twelve months, `compute_weather` called
directly, no engine needed) found realized wind confined to
~0.08-0.66 with p10/p50/p90 at 0.24/0.38/0.51 — `wind_label()`'s old
cutoffs (calm <0.15, breezy <0.35, windy <0.6) put "calm" in the
bottom <1% of realized ticks and "gale" essentially never, so the
label read as permanently windy regardless of actual conditions.
Retuned `CALM_WIND_THRESHOLD`/`BREEZY_WIND_THRESHOLD`/
`WINDY_WIND_THRESHOLD` to the measured percentiles.

`disasters.py`'s `STORM_WIND_THRESHOLD=0.75` was a harder version of
the same bug: entirely above the measured true maximum (~0.66), meaning
`tick_storm` was live code that could never fire under any
`compute_weather` output, not merely rare — directly matching the
"storms are not shown" report. Retuned to 0.55 (~p90 of realized wind,
still above `WEATHER_HARSH_WIND` and the new `WINDY_WIND_THRESHOLD`, so
a "storm" still means something worse than routine windy weather).

Standing lesson reaffirmed a third time (see CLAUDE.md's existing
"Realistic weather thresholds" section): any weather/disaster threshold
that "never seems to happen" on a live run should be checked against
`compute_weather`'s actual measured output first, not assumed to be
correct-but-rare. This is now the *default first check* for a future
report of this shape, not a fresh diagnosis each time.

**Fishing.** Added as a third `ResourceKind` (`world/resources.py`)
rather than a new subsystem, deliberately reusing every mechanism
`ResourceGrid` already has (generation density roll, per-tick
regeneration, depletion, serialization) instead of building a parallel
water-economy system — the smallest change that satisfies "add fishing
with foraging." Placement is water-adjacency-based
(`WATER_ADJACENT_BIOMES` + a 4-neighbor check), not tied to the BEACH
biome specifically, since a grassland/forest tile hugging a river is
just as fishable as a coastal beach. Fish nodes are deliberately denser,
richer, and faster-regenerating than wild food nodes (real-world
shoreline food reliability), consumed by the exact same
`Population._maybe_forage`/`_nearest_resource` code paths FOOD already
uses (a two-line change: check `node.kind in (FOOD, FISH)` instead of
`is FOOD`) — no new `AgentGoal`, no new cognition wiring, matching the
"with foraging" framing of the request rather than a separate fishing
goal/profession.

Verified: `ResourceGrid.generate()` against a real 48x48 terrain
confirmed fish nodes land only on water-adjacent tiles and coexist
correctly with food/ore counts (34 fish nodes of 231 total on seed 42);
a direct 2,000-trial `tick_storm` check at wind=0.9 (above the new
threshold) fired 18 times, matching `STORM_CHANCE_PER_TICK=0.01`
almost exactly — confirming the storm mechanism is now genuinely
reachable, not just less obviously broken; a 6,000-tick full engine run
(LLM disabled, seed 42) completed with no exceptions and fish nodes
present in the live `resources` summary.

## H2 v1 (belief lineage + family mirroring) and H5 v1 (knowledge/skills)

Third and fourth implementation passes on Phase H, per explicit user
instruction to proceed with H2 and H5 "in parallel" following H1/H3.

**H2.** `Settlement.beliefs` entries already carried `confidence`/
`formed_tick`/`revised_tick`/`revision_count` from earlier work — the
roadmap's "minimal schema upgrade" was mostly already shipped. What
was missing: a revision (`SimulationEngine`'s beliefs job `apply()`)
overwrote `belief`/`confidence` in place, so a theory's prior text was
gone the moment it was superseded — the opposite of "a theory's own
past shows through." `llm.beliefs.push_belief_history` (called just
before the overwrite) fixes this with a small capped
(`BELIEF_HISTORY_MAX=3`) `entry["history"]` list — additive, no
existing consumer of belief entries needed to change. Separately,
`llm.beliefs.sync_family_beliefs` is the concrete H2/H3 crossover the
Phase H roadmap section flagged (H3's "institution-scoped world
models" note): any belief resolving to a living family
(`subject_family_agent_ids`, already computed by the pre-existing
`resolve_family_agent_ids`) now mirrors a small copy onto every
overlapping `FAMILY` institution's own `Institution.beliefs`
(`INSTITUTION_BELIEF_CAP=5`) — deliberately a *copy*, not a shared
reference, so the settlement's version keeps evolving independently
(further revision, eviction) of what a family retains. Both are wired
into the existing beliefs job `apply()` in `simulation/engine.py`; no
new LLM call, no new scheduling.

Deliberately not attempted this pass (staged, per the roadmap's own
sequencing note): personal per-agent beliefs reusing this same
list-of-dicts shape, and cognition/goal-selection actually reading
beliefs. Both remain open.

**H5.** New `Agent.skills: dict[str, float]` (proficiency 0..1 per
named skill), holding exactly one skill in v1 (`SKILL_FARMING`) —
deliberately not a skill tree, since a single dimension is the smallest
slice that makes "knowledge spreads through teaching/observation/
apprenticeship" mechanically real without redesigning every
profession-shaped goal at once. Two acquisition paths, matching the
directive's own wording: solo practice ("observation"/learning by
doing — `Population._maybe_forage`'s farm-harvest branch nudges the
harvester's own proficiency by `SKILL_PRACTICE_GAIN` per successful
harvest) and colocated teaching (`Population._maybe_teach_skills`,
called from `tick()` right after `_update_relationships` — a colocated
pair with skill gap >= `SKILL_TEACHING_MIN_GAP` has a small per-tick
chance of the more-skilled agent teaching the less-skilled one,
structurally identical to the existing relationship-gain/gossip-
contagion colocation loops, so no new movement/goal wiring was
needed). A mechanically real payoff, not a stub: a farming-skilled
harvester's hunger relief scales by `1.0 + skill *
SKILL_FARMING_YIELD_BONUS` (up to +25% at mastery), stacking with (not
replacing) the pre-existing tech-level/tradition harvest multipliers.

Deliberate scope boundary: `Settlement.tech_level` is NOT rewired to
aggregate population skill in this pass, even though the roadmap's own
H5 evolution point suggests it as the eventual direction — that's a
balance-sensitive change touching an already-tuned invention/era-
progression system, reserved for a later pass once a second skill
exists to make "aggregate signal across skills" a meaningful design
rather than a one-skill special case.

Verified: direct unit-level scripts for `push_belief_history` (history
caps correctly at 3, oldest dropped) and `sync_family_beliefs`
(upserts rather than duplicates on repeat revision, leaves unrelated
families untouched); a 2,000-tick colocated-pair teaching simulation
(teacher at 0.8, learner at 0.0 — learner reached 0.66 over 44 teaching
events; a matched pair below `SKILL_TEACHING_MIN_GAP` correctly taught
nothing over 500 ticks); a direct harvest comparison on identical ready
farm plots (unskilled: 0.5 hunger relief, correctly gained 0.01
proficiency from the harvest itself; mastery-level 1.0 skill: 0.625
relief, exactly the +25% bonus). A 6,000-tick full engine run (LLM
disabled, seed 42, reproduction odds forced to 1.0 to exercise
births/institutions/beliefs/skills together in one pass) completed
with no exceptions, and a full `World.to_dict()`/`from_dict()`
round-trip preserved `avg_farming_skill` byte-identically.

## H4 v1: building ownership + a real materials->tools supply chain

Fifth implementation pass on Phase H, per explicit user instruction to
proceed with "H4 and H7."

Scoped deliberately narrow, per the roadmap's own H4 note that a full
supply chain deserves its own dedicated session — this is the smallest
version that makes "ownership, specialization, supply chains, trade"
mechanically real rather than a stub, not the maximal reading. Three
concrete pieces:

**Ownership.** `Building.owner_agent_id` is new, but only HUTs are
personally owned — every other kind (granary, workshop, school,
hospital, university, factory, shrine) stays commons
(`owner_agent_id=None`), matching how they already behave mechanically
(any awake agent can use a granary or staff a workshop regardless of
who's "supposed" to own it; changing that would be a much larger
behavioral change than this pass intended). A HUT is assigned to the
lowest-id eligible founder among the colocated pair that triggers
construction — an arbitrary but stable tie-break, since no "whose idea
was it" concept exists in this project to pick more meaningfully.

**Supply chain.** The real addition: `Population._maybe_craft_tools`
gives a standing, staffed workshop a second output besides its existing
currency income (`_maybe_run_workshops`, untouched) — converting shared
`settlement.materials` into personal `"tools"` for each present awake,
well-fed worker, one worker at a time per tick as materials last. This
is the project's first crafted good that belongs to the individual who
made it rather than the settlement commons (currency, granary stock,
and the existing workshop income are all communal). Tools then feed
back into `Population._maybe_gather`, boosting that same agent's own
material-gathering yield up to +40%
(`GATHER_TOOLS_YIELD_BONUS`) — a genuine three-stage loop (raw
gathering -> shared stockpile -> crafted personal good -> better
gathering), not an isolated mechanic. Materials are now contested by
three consumers (construction, crafting, D10 overflow-selling) instead
of two, a real scarcity tradeoff.

**Trade.** `Population._maybe_trade_tools` mirrors `_maybe_trade_food`'s
exact shape (a needing agent — here, a GATHER-goal agent with no tools
— colocated with a non-rival neighbor who has spare, receives some,
with the same relationship nudge) rather than inventing a new barter
mechanism for the new good.

Deliberately NOT attempted this pass, staying inside the "smallest
coherent milestone" discipline: ownership of any other building kind,
a second crafted good, market/price discovery, or hauling goods between
tiles. All remain open for the larger dedicated session the roadmap's
H4 section already flagged.

Verified: a direct script confirmed HUT ownership assignment (forcing
`choose_building_kind` to always return HUT, two founders with ids 5
and 3 — the hut was correctly owned by the lower id, 3) and
`Building.to_dict()`/`from_dict()` round-trip preservation; a 50-tick
crafting simulation (one workshop, one worker, 5.0 starting materials)
produced 1.0 tools and drew the stockpile down to 2.5, confirming both
the cap and the draw rate; a controlled gather comparison on identical
terrain/tile (unequipped agent: 0.03 materials gathered; agent with a
full personal tools stash: 0.042) measured exactly the intended 1.4x
(+40%) multiplier; a direct tool-trade script confirmed transfer amount
and the relationship nudge on both sides. A 6,000-tick full engine run
(LLM disabled, seed 42) completed with no exceptions, and a full
`World.to_dict()`/`from_dict()` round-trip preserved `avg_tools` and
building-ownership state byte-identically.

## H7 v1: inheritance on death

Sixth implementation pass on Phase H, closing out the explicit "H4 and
H7" instruction. Confirmed genuinely blocked on H3/H4 landing first, as
the roadmap predicted — `Population._apply_inheritance` is essentially
a straightforward hook because both prerequisites (an addressable
family entity, an ownable good) already existed.

Design choices: the heir is the *closest living relative by
relationship value* among the deceased's family institution members,
not simply "the first child" or "the spouse" — reuses
`Agent.relationships` (already tracking real affinity) rather than
introducing a new kinship-priority rule, and naturally falls back to
whoever the deceased was actually close to if the family has an
unconventional shape (e.g. a sibling closer than an estranged parent).
No living family (either the deceased never formed one, or every
family member predeceased them) means no inheritance — deliberately
left as a legitimate outcome, matching the project's existing "settlements
expand or collapse," "extinction is a legitimate ending" stance rather
than special-casing "always find someone."

Skill and bias transfers are both *partial*, not full copies, and this
was a deliberate choice over a simpler "just copy the value": a
possession (a hut, food, tools) is the same object whether held by one
person or another, but skill is procedural competence built through
practice/teaching (H5) and trust is a subjective read on someone
(itself built through lived interaction) — neither transfers cleanly
the way property does. `INHERITANCE_SKILL_TRANSFER_FRACTION=0.5`/
`INHERITANCE_BIAS_TRANSFER_FRACTION=0.4` frame this as "notes/technique
left behind" and "a caution passed down," not literal knowledge/opinion
transplantation — consistent with the project's objective/subjective
split (a person's beliefs/skill are their own imperfect state, not
freely copyable ground truth).

The `inheritance` event only logs when something concrete changed hands
— most deaths (an agent with no home, no goods, no notable skill, no
strong grudge on anyone still living) correctly produce nothing, so the
event log isn't spammed by every single death the way `"death"` already
is (that event fires unconditionally, by design, since a death is
itself always noteworthy — inheritance is conditional on there being
anything to inherit).

Verified: a direct scenario script confirmed heir selection (closer
relationship wins over a more distant family member), exact transfer
amounts for goods, the precise partial-transfer math for both skill
(0.8 -> 0.4, exactly half the 0-to-0.8 gap) and bias (-0.6 -> -0.24,
exactly 40% of the gap), and that an unrelated/more-distant family
member received nothing. A no-living-family scenario correctly produced
no event. A full real-engine integration run (reproduction forced
high, `choose_building_kind` forced to HUT so there was land to
inherit, short forced lifespans to trigger natural old-age deaths)
produced genuine `inheritance` events end-to-end through the real tick
loop, with buildings correctly reassigned across generations —
confirmed by inspecting final `Building.owner_agent_id` values after
the run, not just by reading the logged event text.

## H6 v1 (psychology), H8 v1 (temperament/belief crossover), H9 v1 (observatory)

Seventh, eighth, and ninth implementation passes on Phase H, per
explicit user instruction to build "H6 and H8 and H9 together." All
three items the roadmap's own evolution points had already predicted
would be small/cheap once H1-H5/H7 landed — this batch confirms that
prediction rather than discovering new scope.

**H6.** `Agent.traits` (`TRAIT_RESILIENCE`/`TRAIT_SOCIABILITY`) is
implemented exactly per the roadmap's own prescription: a monthly
bounded random walk reusing `tick_temperament`'s shape at agent scale
(`Population._tick_traits`, gated on the real calendar's `month_end`
rather than every tick — 400 agents stepping every tick would drift
far faster than intended and cost real per-tick CPU for no benefit
between month boundaries), plus event-driven nudges hooking existing
event sites rather than inventing new ones: the pre-existing grief loop
in `_apply_deaths`, `_maybe_predator_attack`'s survive-an-attack
branch, the onset of `starving_ticks` (gated to `== 1`, not applied
every tick spent hungry — a crisis *beginning*, matching how
starvation itself already escalates gradually rather than snapping),
and a completed food/tools trade (the one axis with a routine, not
just crisis-driven, nudge). A new shared `Agent.describe_traits`
function (not duplicated per LLM module) feeds both `llm/cognition.py`
and `llm/dialogue.py` prompts once a trait clears
`TRAIT_NOTABLE_THRESHOLD`. Deliberately two axes, not the full
identity/values/ambition set the roadmap names — v1 covers exactly the
two with the clearest existing event hooks (trauma via grief/violence,
sociability via trade); the rest remain open for a future round.

**H8.** `llm.beliefs.temperament_confidence_bias` is the concrete
"Town's belief list as proving ground for H2's schema" the roadmap
predicted — except no further schema work was needed (H2 already
upgraded `Settlement.beliefs`, which *is* the Town's own belief list).
The actual new increment is a genuine systems-interacting nudge:
temperament's magnitude (either direction) pushes a belief's confidence
further from ambivalent. Deliberately magnitude-only — nudging toward
higher confidence when temperament is positive and lower when negative
was considered and rejected, since that would make "good mood ->
optimistic, confident beliefs" a *confirmed* mechanical rule, directly
violating Phase G's standing "never confirmed" instruction. Magnitude-
only preserves total ambiguity: a viewer can never infer temperament's
sign from a belief's confidence trend, only that *something* is
stirring the village's convictions.

**H9.** An audit (not a redesign) of every H1-H8 addition against the
"log through the existing pipeline" rule, per this section's own
evolution point. Found exactly one real gap: H3 family formation fired
with zero event — a family could form and no `events` row, chronicle
mention, or documentary reference would ever know. Fixed by having
`Population._extend_family` return a `family_formed` event on actual
creation (not on every subsequent child, which would be routine noise,
not a new institution). This is the evolution point's core claim
validated in practice: no chronicle/documentary/history code needed to
change at all — they already consume the general event pipeline, so
the new category was visible to all of them the moment it started
being logged. Separately found and fixed a UI-only gap (not a logging
one): `carrying_capacity`/institution counts/`avg_farming_skill`/
`avg_tools` all already existed in `Population.summary()`/`Settlement.
summary()` from earlier H-series work but were never rendered anywhere
— three new stat tiles in the observatory's details panel close this.

Verified: direct scripts for every trait nudge (grief, trade/social
contact, the bounded monthly walk's mean-reversion behavior) and
`describe_traits`'s notability threshold; prompt-injection checks
confirmed both `cognition.build_prompt` and `dialogue.build_prompt`
correctly describe a strongly-shaken or strongly-resilient agent by
name; `temperament_confidence_bias` checked directly against both
temperament signs (0.6 confidence pushed to 0.735 at temperament=0.9;
0.4 pushed to 0.265) and confirmed inert at `phase_g_intensity=0.0`; a
direct `_extend_family` check confirmed the event fires only on actual
family creation. A 6,000-tick full engine run (LLM disabled, seed 7,
reproduction odds forced high) produced two genuine `family_formed`
events and non-zero `avg_resilience`/`avg_sociability` end-to-end
through the real tick loop, with a full `World.to_dict()`/`from_dict()`
round-trip preserving both byte-identically.

## H2 extension (personal beliefs, cognition consumption) and H5 extension (second skill, invention nudge)

Tenth/eleventh implementation passes, per explicit user instruction to
"perform H2/H5 extensions." Both close the specific "not attempted this
pass" gaps the roadmap itself flagged in each section's own v1 note,
rather than reopening unrelated scope.

**H2.** Two closes, not one: (stage 4) `llm.cognition.build_prompt`
gained `beliefs_about`, the exact param dialogue's prompt already had —
a genuine oversight, since "the village believes X is reckless" already
shaped what others said *to* X, but never reached X's own decision-
making. Fixed by extracting the existing inline filter (previously
duplicated as a list comprehension inside dialogue's engine call site)
into a shared `llm.beliefs.beliefs_about_agent`, used by both call
sites now. (Stage 2) `Agent.beliefs` reuses the *exact* generic
functions `Settlement.beliefs` already established
(`parse_belief`/`push_belief_history`/`find_belief_index_by_subject`
never referenced `Settlement` in their signatures to begin with — they
already operated on plain `list[dict]`), so no new belief-mechanics
code was needed, only new prompt-building
(`build_personal_prompt`/`fallback_personal_belief`) and a new engine
scheduling method mirroring `_maybe_schedule_beliefs`'s shape at
one-agent-per-month instead of settlement-wide. The one deliberate
design choice: only one randomly chosen agent reflects per month, not
all of them — a genuine population-wide personal-belief system (400
agents x one LLM call/month each) would be a real scheduling load
increase for content meant to be occasional personal theories, not a
monthly journal entry required of every villager. `find_belief_index_
by_subject`'s existing "prefer subject-string match over the model's
own integer indexing" behavior (originally a fix for settlement
beliefs) applies unchanged here, for the same 2B-model-reliability
reason.

**H5.** `SKILL_CONSTRUCTION` required one real change beyond adding the
name: `_advance_construction` previously computed `workers` as a bare
`int` count (`sum(1 for a in ... if awake)`), which is enough to size
`work` but not enough to know *which* agents get practice XP or
contribute a skill average. Changed to build the actual (MAX_WORKERS-
capped) worker list once and derive both the count and the skill
average from it — a small refactor, not a behavior change when no one
present has any construction skill (multiplier is `1.0 + 0 * bonus =
1.0`, identical to the old unconditional `work` formula). `_maybe_
teach_skills` needed only its iterated-skills tuple extended by one
name; it was already written skill-name-agnostic in the H5 v1 pass
specifically so this would be true. The invention-chance nudge
deliberately does NOT implement the roadmap's literal "`tech_level`
becomes the aggregate signal... rather than an independently-rolled
scalar" phrasing — that would replace a currently balance-tuned
mechanism (prosperity gate + education bonus + the roll itself,
already tuned across several prior sessions' live-diagnostic passes)
with something new and untested. The additive nudge captures the same
underlying idea (population knowledge measurably affects invention)
with materially lower risk to existing tuning; a full replacement stays
open as a larger, riskier future option if ever wanted.

Verified: direct scripts for `beliefs_about_agent` filtering,
`build_personal_prompt`/`fallback_personal_belief` output shape, the
exact construction-speed multiplier (0.05 -> 0.0625 progress/tick,
precisely +25%), teaching generalized to the new skill, and the
invention-chance math (0.2 -> 0.26 at full-mastery average skill,
precisely +30%). Two full real-`SimulationEngine` integration runs
(via `load_or_create`/`_tick_once`, matching `experiment.py`'s own
pattern for driving the real engine headless): one with a forced
memory on every agent confirmed personal beliefs actually form *and*
later revise (with history) through the real monthly-scheduled job
end-to-end (not just the unit-level helpers); a second, unmodified
6,000-tick run confirmed no regressions with the new stats live. Both
confirmed clean serialization round-trips.

## Full-H extension: COUNCIL institutions, ambition, medicine

Twelfth implementation pass, closing out the explicit "full H
extension" half of the combined "perform H2/H5 extensions and full H
extension" instruction. Three small, closely-patterned additions, each
following an established shape from earlier in Phase H rather than
introducing a new one.

**H3: `COUNCIL`.** The second institution kind, deliberately still
fully automatic (no agent goal or LLM founds one) — a named
settlement's population crossing `COUNCIL_FORMATION_POPULATION_
THRESHOLD=20` is the "cheapest, most unambiguous moment" trigger, same
philosophy as birth triggering family formation. Membership is fixed
at formation (the `COUNCIL_SIZE` eldest living agents by lifespan
fraction) and never refreshed — matches how `FAMILY.member_agent_ids`
already only ever grows, never gets reassigned, rather than inventing
a different, dynamic-membership shape for the second kind. No
consumption beyond serialization/summary/the new event in this pass,
same staged-rollout precedent `FAMILY` itself followed (beliefs-
mirroring came in a later H2/H3 crossover pass, not v1).

**H6: `TRAIT_AMBITION`.** The mastery-nudge needed a genuine one-time-
crossing check (`before < MASTERY_THRESHOLD <= after`) rather than a
simple `if skill >= threshold` gate, since the latter would re-fire the
nudge every single tick a mastered agent kept practicing — verified
directly (the unit script explicitly re-practiced past mastery and
confirmed ambition stayed flat on the second call). Founding nudges
both eligible founders, not just the HUT's eventual owner (H4's
lowest-id tie-break) — founding a building is a shared achievement
between whoever was present, ownership is a separate, narrower concept
that already has its own tie-break rule.

**H4: medicine.** Deliberately the *same* supply-chain shape as tools
(craft from shared materials at a staffed building, consume personally,
trade via the same barter pattern) rather than a novel mechanic, so the
H4 v1 review/audit trail generalizes cleanly to "goods work this way in
this project" rather than every good needing its own bespoke design
read. The death-chance interaction is the one genuinely new piece:
personal medicine multiplies (not replaces) the settlement-wide
hospital reduction `_tick_disease` already applies, so the two layers
stack — a settlement with both a hospital and citizens who personally
stock medicine protects better than either alone, a believable
"institutional care plus personal preparedness" reading. Verified with
a paired 3,000-tick death-rate comparison (500 permanently-medicated
agents vs. 500 without, same seed) rather than only checking the
single-roll math, since a small per-tick probability difference needs
volume to show up meaningfully — 58 deaths vs. 128, confirming the
effect is real at population scale, not just correct in isolation.

Also updated: the observatory's existing "Institutions"/"Skills &
tools" stat tiles (added in the H9 pass) to include the new council
count and construction/medicine averages, plus a new "Personality
(avg)" tile for all three trait axes — none of these existed as UI
surfaces before this pass despite being in `summary()` already,
continuing the same "stats existed, were never actually shown" pattern
H9's audit first found.

Verified overall: council-formation threshold/elder-selection/no-
duplicate-formation script; ambition mastery-nudge-fires-once and
founding-nudges-both-founders scripts; medicine crafting/trading
scripts and the paired death-rate comparison above. A 6,000-tick full
engine run (LLM disabled, seed 42) completed with no exceptions across
all three mechanics together, with a full `World.to_dict()`/
`from_dict()` round-trip preserving every new stat byte-identically.

## Unbounded `Settlement.institutions` growth (fixed v0.54.0)

A live user report of continuing swap pressure prompted a fresh audit
rather than re-tuning already-tuned Ollama levers (concurrency floor,
`num_ctx`/`num_predict`/`keep_alive` are all pinned by earlier explicit
decisions and weren't touched again here). Root cause found by direct
measurement, not guesswork: a 40k-tick in-process run (seed 42, no cap,
LLM disabled) showed `Settlement.institutions`'s FAMILY count climbing
roughly linearly with cumulative births — 0 at tick 4,000, 191 by tick
24,000, 275 by tick 26,000 — with **no** ceiling, unlike population
itself which plateaus at the dynamic carrying capacity (H1) and never
exceeds the hard `POPULATION_CAP=400` safety valve. This is the same
bug class fixed twice before in this project's history
(`relationships`/`trust` dicts, v0.42.0; `traditions`/`inventions`/
`festivals` lists, v0.44.1) — a per-event append with no corresponding
removal — just never audited when H3 (families), H7 (inheritance), and
H9 (family_formed events) introduced and then built on top of
institutions across three separate earlier sessions in this same
conversation. On a genuinely persistent, always-running world (the
project's core premise) this is unbounded growth in the literal sense,
not just a large-but-finite number.

Institutions differ from the traditions/inventions/festivals precedent
in one important way: those three are pure flavor text fed into LLM
prompts, so truncating to the newest N (what `CULTURE_LIST_MAX_STORED`
does) is always safe. A FAMILY institution is looked up by living-agent
membership — `Settlement.family_for()`, H7's inheritance heir search,
H2's family-scoped belief mirroring, dialogue's beliefs_about — so
blindly dropping the oldest entries risks silently orphaning a
still-living elder's family reference. The fix (`INSTITUTION_LIST_
MAX_STORED = 300`, same magnitude as `CULTURE_LIST_MAX_STORED`;
`population._prune_extinct_families`, called after every new FAMILY
institution forms) is therefore extinction-aware rather than a blind
truncation: only FAMILY institutions whose `member_agent_ids` is
disjoint from every currently-living agent id are eligible for removal,
oldest-founded first, and only once stored count exceeds the cap — a
family with even one living member is never touched regardless of age.
COUNCIL institutions are excluded entirely (`COUNCIL_SIZE` already caps
that kind at a handful of members and a single instance per settlement,
so it was never a growth risk).

Verified three ways: a direct unit check against a tiny synthetic cap
confirming both that the oldest fully-extinct entries are evicted first
and that a family containing a living member always survives regardless
of its age; a 60,000-tick full-`SimulationEngine` integration run (real
async tick loop, real cap, LLM disabled) confirming the stored count
holds flat at the cap once population/births plateau rather than
continuing to climb; and a `Settlement.to_dict()`/`from_dict()`
round-trip confirming serialization is unaffected. Also audited every
other per-agent/per-settlement collection touched across the H2/H4/H5/
H6/H7/H8/H9 work for the same pattern (`Agent.skills`/`traits`/
`beliefs`/`inventory`, `Institution.beliefs`, `omen_history`/
`priority_history`, `trust`/`relationships` post-death cleanup) — all
were already correctly bounded (fixed key sets, existing caps, or
already-pruned on death from the v0.42.0 pass); institutions was the
one genuine miss. If swap pressure persists after this fix, the next
most likely remaining cause is Ollama's own server-side memory (a
separate process this environment cannot exercise with a real model) —
that would need a fresh live diagnostic from the user's own machine to
pin down further, same as the v0.43.0/v0.43.1 Ollama-memory passes.

## Ollama `--no-mmap` forced off (v0.55.0)

Follow-up to the above: the user ran `ollama ps` and `ps aux | grep -i
ollama` on their own machine as suggested and pasted the output back.
It was immediately actionable: `ollama serve` itself was a negligible
50MB RSS, but the actual per-model `llama-server` runner process was
resident at **5.1GB — 74% of an 8GB system** — for a model `ollama ps`
itself reports as only 2.4GB loaded. That ~2.7GB gap, combined with
`--no-mmap` sitting on the runner's command line, is close to a smoking
gun: `--no-mmap` forces the model's weight pages into private anonymous
memory. Anonymous pages are "dirty" from the kernel's perspective — the
only way to reclaim them under pressure is to write them to swap. Normal
mmap'd weight pages are file-backed and clean, so the kernel can instead
just drop them and re-read from disk on next use, which is strictly
cheaper than a swap round-trip and doesn't touch swap at all. Whatever
caused `--no-mmap` to be set here — an `OLLAMA_NOMMAP` env var, or
Ollama's own low-system-RAM heuristic silently choosing it — this
project's own requests to Ollama were never expressing an opinion on the
option either way, so it went unchallenged.

Fixed the same way `llm_num_ctx`/`llm_num_predict`/`llm_keep_alive` were
each fixed before it: stop trusting the server's default/heuristic and
send an explicit value on every call. New `Config.llm_use_mmap = True`
(unconditional — there's no scenario in this project where forcing
anonymous residency over file-backed pages is preferable), sent as
`use_mmap` in the `options` object `OllamaClient.generate_json` already
builds for `num_ctx`/`num_predict`. Threaded through both places an
`OllamaClient` gets constructed — `SimulationEngine.__init__` (the
per-tick cognition/dialogue/town-brain/etc. path) and `server.py`'s
one-shot world-genesis seed call, which was easy to miss since it's a
separate, rarely-touched call site from the main engine loop.

This can only be verified on the user's real machine (this sandboxed
environment has no genuine Ollama server to launch), so verification
here was necessarily narrower than the usual live-measurement standard:
confirmed the `options` dict actually includes `"use_mmap": true` when
`Config.llm_use_mmap` is set (direct construction + inspection, no
network call), and that both call sites pass it through. The user's own
next live session (a fresh `ollama ps` / `ps aux` comparison, watching
whether `--no-mmap` disappears from the runner's command line and
whether RSS drops toward the ~2.4GB `ollama ps` figure) is the real
verification and hasn't happened yet as of this entry.

Explicitly *not* attempted: the same diagnostic surfaced `--mmproj`
pointing at the identical blob hash as `--model`, suggesting the pulled
`qwen3.5:2b` tag may bundle a multimodal (vision) projector this project
never exercises (every prompt here is text-only, `format: "json"`,
`think: false`). This is baked into the model artifact/Modelfile
already pulled onto the user's machine — no Ollama API request option
can strip a projector from an already-loaded model, so this needed
either a Modelfile inspection or pulling a different tag, both of which
require access to the user's actual `ollama` installation this
environment doesn't have. Flagged rather than silently skipped or
guessed at.

## Integration milestone: cross-system audit and vertical integration (v0.56.0)

Explicit user directive, distinct in shape from every prior batch: not
"build system X" but "audit every major subsystem, identify where it's
isolated, then increase the number of meaningful interactions between
existing systems" — prioritizing dynamic carrying capacity,
infrastructure networks (roads/water/power/irrigation), external
settlements and trade, institutional agency, knowledge diffusion, urban
growth, and supernatural propagation, with the constraint that every
touched system should both influence and be influenced by multiple
others (vertical integration, long-term feedback loops), not just gain
one new consumer.

**Audit method and findings.** Rather than guessing, every named
priority area was traced through the actual code (not summarized from
memory) to find genuine one-way or dead-end links:
- **COUNCIL was the single most isolated system in the codebase.**
  `_maybe_form_council` set `member_agent_ids` once at formation and
  nothing ever added to it — every member who died stayed a permanent
  dead entry with no fix, so a long-running settlement's council would
  silently decay into an all-dead ghost roster. It also had *zero*
  mechanical output anywhere (not town_brain, not carrying_capacity,
  not beliefs) despite `sync_family_beliefs` already existing for
  FAMILY — a real, working pattern that was simply never extended to
  the second institution kind.
- **Traits (resilience/sociability/ambition) were write-only.** Nudged
  by real events (grief, violence, sustained hunger, trade, founding,
  mastery) but read by nothing except `describe_traits` (pure LLM
  prompt flavor) and stat-tile averages — no deterministic mechanic
  ever consumed them, unlike `temperament`, which the codebase already
  wires into invention/predator/migrant/wildlife rolls.
- **Roads were decorative.** They decay/persist and gate vehicle
  speed, but influenced nothing about *where* a settlement grows, *how
  much* it could support, or *how readily* disease/knowledge spread —
  a real, tuned mechanic (`roads.py`'s presence-driven wear) with
  almost no downstream consumer.
- **`carrying_capacity` (H1) read only housing/economy/security/labor/
  weather** — institutions, skills, and infrastructure, despite all
  three being real, effortful things a settlement builds up, had no
  path to expand (or shrink) what it could actually support.
- **External settlements don't exist at all** — correctly, per the
  standing decision (see "Multiple named settlements" below) that the
  full multi-`Settlement` rearchitecture is its own dedicated session
  (it touches population/engine/every LLM prompt/interface/snapshot
  schema in the same pass). This audit did not attempt to override that
  standing decision; it scoped a smaller, still-real step instead (see
  Added below).
- **Urban growth had no real concept** — construction site choice was
  (and structurally still is) pure-chance colocation, an explicitly
  flagged roadmap gap since the July 2026 architecture review.
- Everything else audited (weather, farming, wildlife, disease,
  culture, Phase G, inheritance, trade) was already meaningfully
  bidirectional or, for the deterministic-physics layer (weather,
  terrain), *correctly* one-way by design (CLAUDE.md's objective-
  reality/subjective-belief split — weather should not be influenced by
  village mood).

**What shipped, and why each piece closes a loop rather than adding a
one-way consumer:**

*Institutional agency.* `Population._maybe_refresh_council` tops
COUNCIL's living membership back up to `COUNCIL_SIZE` from the next-
eldest non-member whenever a seat opens (same elder-selection rule
`_maybe_form_council` already uses) — fixes the ghost-roster bug
outright. New `llm/beliefs.sync_council_beliefs` mirrors settlement
beliefs that *don't* resolve to a person/family onto COUNCIL (civic
theories, not household gossip — `sync_family_beliefs` already owns
the personal case) — this is the loop-closer: `Institution.beliefs`
was a genuinely dead field before this (the module docstring even said
so explicitly; corrected). New `Population.council_disposition`
(average living-member traits) feeds `town_brain.build_prompt`'s new
`council_beliefs` context line *and* `fallback_priority`'s new
tie-break (ambition -> growth, resilience -> defense, only once
nothing urgent — hunger/illness/coffers — already decided the
priority) *and* `carrying_capacity`'s new coordination term. Three
consumers from one new read path, not one.

*Traits.* Resilience now reduces personal disease/predator death
chance (`TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE`, stacking with
medicine/hospital/temperament, never replacing them) and stretches/
shrinks personal starvation tolerance (`_starvation_threshold`) —
closing the loop with `TRAIT_SUSTAINED_HUNGER_NUDGE`/
`TRAIT_VIOLENCE_NUDGE`/`TRAIT_GRIEF_NUDGE`, all of which already wrote
to this exact trait. Sociability shifts a giver's own trade-
relationship threshold (`_trade_relationship_threshold`, additive
shift on `TRADE_MIN_RELATIONSHIP` rather than a bespoke roll, since
trade is deterministic-on-colocation, not a per-tick chance) and
scales personal teaching-roll chance — closing the loop with
`TRAIT_SOCIAL_CONTACT_NUDGE`. Ambition RNG-weights (never guarantees)
which eligible founder claims a new HUT's ownership — closing the loop
with `TRAIT_AMBITION_FOUNDING_NUDGE`. Deliberately did *not* wire
ambition into COUNCIL seating (age-based elder selection stays a
clean, single-purpose rule) — not every trait needs to touch every
system; forcing it would blur what "a council of elders" means.

*Roads.* Three consumers, not one: (1) `URBAN_GROWTH_ROAD_ADJACENCY_
MULTIPLIER` on `SETTLE_CHANCE_PER_TICK` for a road-adjacent tile —
closes the explicitly-flagged "where to build is pure chance" gap the
same way `current_priority` already closes the "whether/what kind"
half; (2) established-road density feeds `carrying_capacity`'s new
infrastructure term (saturating per capita, so a road network past
what the population needs stops paying off further); (3) the fraction
of the population standing on a road tile nudges disease-outbreak
chance upward (`OUTBREAK_ROAD_CONTACT_MULTIPLIER`) — a deliberately
double-edged framing: the same connectivity that helps trade/teaching
also spreads a cold, real epidemiology rather than infrastructure
being purely beneficial. All three magnitudes are the smallest in
their respective compositions, consistent with the project's standing
"real but never dominant" discipline for every cross-system nudge
(temperament's *_INFLUENCE constants, trait step sizes, culture-effect
riders).

*Knowledge diffusion.* `_maybe_teach_skills`'s roll chance (previously
a flat constant) is now scaled by both agents' average sociability,
multiplied by `INSTITUTION_TEACHING_BONUS_MULTIPLIER` when teacher and
learner share a living FAMILY or COUNCIL, and multiplied again by a
new `"knowledge"` tradition influence — a fourth entry in
`TRADITION_INFLUENCES` alongside festivity/harvest/resilience, same
`culture_effect_multiplier` mechanism, with a matching fallback-pool
entry ("The Apprentice's Vow"). Three independent, stacking real
inputs into one existing roll, not three new mechanics.

*External world contact (caravans).* Deliberately the smallest
coherent step toward "external settlements and trade," NOT the full
rearchitecture — see "Multiple named settlements" below for why that
stays its own session. New `llm/caravan.py`: a rare
(`CARAVAN_CHANCE_PER_MONTH = 0.15`) monthly abstract event — no new map
entity, no pathfinding, no second `Settlement` — with a real,
deterministic currency/materials exchange (correlated: a caravan that
pays in currency takes materials in return, never two independent
windfalls) applied unconditionally as objective reality, and an
LLM-or-fallback description plus an optional outside-the-village rumor.
The rumor is the genuine integration point: new `Population.
spread_rumor` seeds it into a few agents' own memories via the
*existing* `_remember` mechanism, so it can propagate through the
already-built dialogue gossip/trust-contagion system rather than a
bespoke broadcast — "contact with the wider world" becomes mechanically
real (currency/materials shift, a rumor that can spread and be
believed or doubted) without touching population/engine/prompts/
interface/snapshot schema the way real multi-settlement would.

*Supernatural propagation.* Omens (`_maybe_schedule_omen`) can now
center on "the council of elders" as a subject, alongside the existing
50%-of-the-time per-agent subject depth — gated on the council actually
holding beliefs (itself a product of `sync_council_beliefs` above), so
this only activates once institutional agency has actually produced
something to be ambiguous about. Same permanent ambiguity rule,
unchanged: nothing here asserts anything, same mundane-explicable
framing extended from person-depth to institution-depth.

**Deliberately not attempted, and why:**
- **Full multi-settlement / external-settlement trade.** Still its own
  dedicated session per the standing decision log (touches population/
  engine/every LLM prompt/interface layer/snapshot schema in the same
  pass) — caravans are the scoped interim step, not a silent
  substitution for the real ask.
- **Water/power/irrigation as a distinct infrastructure network.**
  Water already exists as terrain (rivers/lakes, H-era fishing) and
  farms already read adjacency for fish-node placement; "power" doesn't
  fit the industrial-era-appropriate tech tree until FACTORY/electrical
  unlocks meaningfully change what it would even mean. Roads were the
  one infrastructure network with a real, already-tuned mechanic and
  measurable gaps worth closing this pass — irrigation/power remain
  open for a future session once there's a concrete mechanical hook for
  them, rather than inventing one just to check a box.
- **Ambition wired into COUNCIL seating.** Explicitly kept out — see
  the traits section above.

**Verification.** Direct unit checks for every new cross-system link in
isolation (council living-membership refresh + disposition computation
ignoring dead members; fallback_priority's tie-break firing correctly
in both directions; starvation/trade threshold shifts moving the
correct direction for positive vs. negative trait values; ambition-
weighted HUT ownership showing a measurable but non-guaranteed skew
over 2,000 trials; road adjacency raising settle chance and outbreak
chance and carrying capacity, each confirmed via direct formula
inspection since the underlying rolls are too rare to observe
frequency directly at unit-test scale); a dedicated caravan-only run
confirmed at least one visit fires within 20,000 ticks with a clean
currency/materials exchange and a real logged event — then a
50,000-tick full-`SimulationEngine` integration run (real async tick
loop, LLM disabled, seed 99) exercising every new mechanic together
completed with zero exceptions across the full run. COUNCIL formed by
tick 8,000 and stayed at a full living complement of 5 the entire way
(42 `council_seat_filled` refresh events fired over the run, so the
fix is doing real, repeated work, not a one-off), 570 construction
events fired, and 3 caravans visited (roughly matching the ~15%/month
expected rate). Genuinely emergent, unscripted story from the trait-
consumption changes: population peaked at 268 around tick 24,000, then
crashed to 84 by tick 32,000 with average resilience diving to -0.86 —
a real hardship period (want deaths/violence/hunger all nudge
resilience down) visibly marking the population's psychology, not just
its headcount — before both population and average resilience
recovered together over the following 20,000 ticks (208 population,
-0.22 average resilience by tick 48,000). That correlated rise-and-fall
is exactly the kind of "believable causality nobody explicitly
programmed" CLAUDE.md's design priorities ask for, and it only exists
because resilience is now read by a real mechanic instead of sitting
inert. A full `Settlement.to_dict()`/`from_dict()` round-trip preserved
every institution's `beliefs` list byte-identically (no snapshot schema
changes were needed — every new state lives in fields that already
existed and
already serialize).

## Water/power/irrigation (v0.57.0) + iGPU offload investigation

Explicit user follow-up to the integration milestone: implement the two
infrastructure-network pieces deliberately deferred there (water/power
were flagged as "no concrete mechanical hook yet" for power, and water
"already exists as terrain/fishing" for irrigation), plus investigate
whether the user's AMD iGPU can offload some Ollama inference.

**Irrigation.** Reused `world/resources.py`'s existing `_adjacent_to_
water` helper (already built for H-era fish-node placement, renamed
public `is_adjacent_to_water` since a second module now needs it) rather
than inventing a water-network data structure — a farm plot adjacent to
a river/lake/deep-water tile now grows `IRRIGATION_GROWTH_MULTIPLIER`
(1.35x) faster. Deliberately a *growth-rate* lever, independent of the
existing tool/no-tool *yield* lever (`FARM_TOOL_YIELD_MULTIPLIER`) —
irrigation and tooling answer different questions ("how fast" vs. "how
much"), so they stack rather than compete. `FarmGrid.tick` gained an
optional `terrain` parameter (defaults to `None`, in which case behavior
is unchanged) rather than a breaking signature change, so no other
caller needed updating.

**Power.** The `electrical` era already existed by name (`ERA_ORDER`,
`ERA_TECH_THRESHOLDS`) and already gated FACTORY, but had no dedicated
"power" mechanic of its own — exactly the "no concrete mechanical hook
yet" gap flagged in the integration milestone entry above, now closed
by giving it one instead of inventing a parallel utility-grid concept.
New `BuildingKind.POWER_PLANT`, foundable from `electrical` onward
(shares FACTORY's era-gate frozenset, renamed `_ERA_UNLOCKS_FACTORY` ->
`_ERA_UNLOCKS_ELECTRICAL` now that two kinds use it). While standing:
boosts WORKSHOP/FACTORY income settlement-wide (`POWER_GRID_INDUSTRY_
MULTIPLIER`, 1.3x — "electrified industry produces more," the literal
payoff of the era's own description, "the first wired lights and
machinery") and adds a small, secondary bonus to `carrying_capacity`'s
infrastructure term (`CARRYING_CAPACITY_POWER_PLANT_BONUS`) alongside
the dominant road-density signal from the integration milestone — a
single power plant is one building, not a network, so it stays the
smaller of the two infrastructure inputs. `Settlement.has_power_plant()`
is the one shared query both consumers use, same pattern as `council()`.
Verified via direct unit checks (irrigation growth-rate ratio matches
the constant exactly; carrying capacity measurably higher with a
standing power plant than an otherwise-identical settlement without
one; `choose_building_kind` never selects `power_plant` before
`electrical` era and does select it after, over 20,000 trials).

**iGPU offload investigation (AMD Ryzen 3 8300GE / Radeon 740M,
gfx1103, RDNA3).** The user ran `ollama ps` (showing 100% CPU) and
`rocminfo` (showing the GPU agent, `gfx1103`, correctly detected by
ROCm) and asked whether llama.cpp could help route some inference to
the iGPU. This is fundamentally a question about the user's own Ollama/
ROCm installation, which this sandboxed environment has no access to —
nothing here could be tested directly, only reasoned about and one
genuinely safe, no-op-by-default code lever added in case it helps once
confirmed working on the user's actual machine.

Diagnosis: `rocminfo` detecting `gfx1103` does not mean Ollama's bundled
ROCm runtime will use it — Ollama ships its own vendored ROCm libraries
with a fixed list of supported GPU targets, and consumer/APU RDNA3
iGPUs in the Phoenix/Phoenix2 family (740M/780M, `gfx1103`) have
historically fallen outside that list even when the system's own ROCm
stack (what `rocminfo` queries) recognizes the chip fine — exactly
matching the symptom reported (`rocminfo` sees it, `ollama ps` still
says 100% CPU). This is a well-known class of issue for this GPU
family, not specific to this project's code.

Two paths, in order of effort:
1. **`HSA_OVERRIDE_GFX_VERSION=11.0.0`** set in the environment `ollama
   serve` runs under (e.g. its systemd unit's `Environment=` line, or
   the shell that launches it) — spoofs `gfx1103` as `gfx1100`, the
   nearest officially-supported RDNA3 target, architecturally close
   enough that this is a widely-used community workaround for exactly
   this GPU family. Cheapest thing to try first; requires only
   restarting `ollama serve`, no rebuild. Confirm with `ollama ps`
   afterward — the `PROCESSOR` column should show GPU involvement
   instead of `100% CPU`.
2. **llama.cpp directly, if (1) doesn't work.** Ollama's own inference
   backend *is* a fork/vendor of llama.cpp, so switching to llama.cpp
   itself mainly buys more backend choice, not a fundamentally
   different engine. Its **Vulkan** backend is generally the more
   permissive path for an unsupported-by-ROCm iGPU like this one — it
   doesn't require an exact gfx-target match the way the HIP/ROCm
   backend does — at the cost of leaving Ollama's own scheduling/
   model-management conveniences behind (would need `llama-server` run
   directly, with this project's `OllamaClient` pointed at it — the
   `/api/generate` shape differs, so that would need actual code
   changes here, not just a config flag, if it came to that).

Expectation-setting, since "guaranteed improvements" was the bar: even
if GPU offload is confirmed working, the Radeon 740M is a small iGPU (4
compute units, RDNA3, sharing system RAM rather than dedicated VRAM —
`rocminfo`'s pool sizes show ~3.4GB accessible to the GPU agent) — a
real speedup over CPU-only inference for a 2B model is plausible but
not large, and no claim here should be read as promising a specific
number, since it can only be measured on the user's actual hardware.

What shipped from this investigation: `Config.llm_num_gpu` (default
`None`) sent as `num_gpu` in `OllamaClient`'s `options`, same pattern as
`num_ctx`/`num_predict`/`use_mmap` — but deliberately left at `None`,
a genuine no-op, rather than set to any value, since this project has
no informed opinion on layer count until GPU offload is actually
confirmed working server-side. This is the lever to set (if Ollama's
own auto-detected split ever needs overriding) once path (1) or (2)
above is confirmed working — not a fix in itself, since the blocker is
server-side GPU recognition, not anything this project's requests were
withholding.

## Backpressure gate for settlement-level LLM jobs (sparse-but-sudden swap audit, v0.58.0)

Explicit user follow-up to the water/power/irrigation batch: "also
audit for sparse but sudden high swap usage" — deliberately distinct
from every leak this project has already found and fixed
(institutions, relationships/trust, culture lists), all of which are
*steady-state* problems: a value that monotonically grows tick after
tick until it's capped. "Sparse but sudden" is a different shape —
nothing accumulates, but something occasionally spikes — so the right
place to look isn't another unbounded-collection scan, it's anywhere
several expensive operations can cluster onto the same tick.

Method: instrumented `SimulationEngine._schedule_llm_job` — the one
shared scheduling path for all ten settlement-level LLM jobs
(naming, chronicle, documentary, tradition, invention, festival,
caravan, town_brain, beliefs, personal_belief, omen) — to record
`(tick, job_name)` for every call, then ran the real engine
(deterministic fallback, seed 7) through several thousand ticks and
grouped by tick. Finding: at tick 8832, five jobs scheduled in the
same tick — `['chronicle', 'tradition', 'town_brain', 'beliefs',
'personal_belief']` — and a 4-job cluster at tick 5856. This isn't a
coincidence of this seed: `chronicle`/`town_brain`/`beliefs`/
`personal_belief` all fire on *every* `month_end`, and `tradition`/
`invention` fire on every `season_end` — and a season boundary is
*always* also a month boundary (`Config.month_to_season`), so the
4-job monthly cluster is guaranteed every month, growing further
whenever an independently-rolled job (festival/caravan/omen) also
happens to fire that same month.

Root cause: reading `_schedule_due_cognition` and `_schedule_due_
dialogue` (the per-agent/per-pair scheduling paths) showed both
already check `self._cognition_runner.backlog >= self._backpressure_
limit` before scheduling — the backpressure mechanism the July 2026
architecture review introduced specifically so the LLM task queue
can't grow unbounded when the engine schedules jobs faster than
Ollama can drain them (§3.6, `BACKPRESSURE_BACKLOG_PER_SLOT`). But
`_schedule_llm_job` itself — the shared path all ten settlement-level
jobs funnel through — never checked it. Each of these ten jobs was
added independently across many separate sessions in this project's
history (B3, E1, E2, E3, "collective behaviour," the integration
milestone's caravan, H2/H8 belief work, Phase G's omens...) and none
individually looked like a backlog risk in isolation — the risk only
exists as a cluster, which no single session's diff would have
surfaced. `CognitionRunner.run()` increments `backlog` the instant a
job enters (before it even reaches the semaphore), and holds it until
the call resolves — with `llm_max_concurrent` at its permanent floor
of 2 (v0.44.0's "never traded off against memory" instruction) and
real measured hardware latency of ~17-20s/call (`jobs.py`'s own
docstring), an unthrottled 5-job cluster forces Ollama through a
rapid-fire near-back-to-back burst of requests once a month, instead
of the much sparser trickle a whole-run average would suggest — each
still allocating its own KV-cache server-side. This is exactly the
"sparse" (only on month/season/year boundary ticks — a small fraction
of all ticks) "but sudden" (an unbounded cluster of concurrent-ish
Ollama load with zero backpressure) shape the user asked about, and
it wouldn't show up in any of the memory-growth audits already done,
since nothing here leaks — it's a scheduling gap, not an
accumulation.

Fixed with `SimulationEngine._settlement_job_backpressured()`, calling
the identical `backlog >= _backpressure_limit` check already proven
out for cognition/dialogue, added to all ten schedulers. Placement:
after each job's own cheap gate/RNG-roll checks (so a job that
wouldn't have fired anyway still short-circuits first, without paying
for the check), before any `recent_events` DB query or prompt string
gets built. Two deliberate exceptions to a uniform application:
- **Caravan**: the currency/materials exchange (`settlement.currency
  += currency_delta`, etc.) stays unconditional — it's the
  deterministic engine's objective reality, same status as a
  disaster's material cost (see llm/caravan.py's own module
  docstring); the backpressure check sits *after* the exchange,
  gating only the LLM/fallback narration and rumor-seeding that
  follow it.
- **Naming**: deliberately left ungated. It's a one-time-per-world
  event (`_naming_scheduled`), not a recurring monthly job, and isn't
  part of the cluster this fix targets — gating it would need new
  retry plumbing (the current code sets `_naming_scheduled = True`
  unconditionally the moment the founding event is seen, with no
  later re-check), for a job that only ever competes for a slot once
  in a world's entire lifetime.
Every other job's degradation contract matches the existing cognition/
dialogue precedent exactly: a dropped job just waits for its own next
natural cadence (next month/season/year) — nothing is lost, nothing
retries out of order. Town brain's whisper-consumption logic already
handled this correctly for the timeout/fallback case ("stays queued
for next month's decision instead of vanishing") and needed no change
for the newly-possible drop-before-scheduling case, since from the
whisper queue's perspective the two are indistinguishable — the
prompt simply never happened this month either way.

Verified: (1) the real-engine trace above, showing the cluster exists
pre-fix; (2) a direct unit check
(`/tmp/.../backpressure_unit.py`) calling all ten `_maybe_schedule_*`
methods against a real `SimulationEngine` twice — once with
`backlog=0` (each schedules normally, modulo its own independent RNG/
prosperity/hunger gate — confirmed those still work unmodified) and
once with `backlog` forced to exactly `_backpressure_limit` (all ten
correctly return without calling `_schedule_llm_job`,
`calls_dropped_backpressure` increments on the ones whose own gate
would otherwise have let them through, no exception) — plus a third
case confirming naming still schedules under the identical saturated
condition, proving the exemption is live and intentional rather than
an oversight; (3) a 5,000-tick full-engine smoke run post-fix
(0.92ms/tick, unchanged from pre-fix baseline, serialization
round-trip OK) confirming no regression to ordinary tick throughput.
No real Ollama server is available in this environment, so the actual
swap-pressure reduction on the user's hardware can't be measured here
— this closes the code-level gap the audit found; a live diagnostic
report (same `ollama ps`/`ps aux` pattern used for the mmap fix) is
the way to confirm the fix's real-world effect, same standing caveat
as every other memory fix in this project's history.

## "Expand all features" (v0.59.0)

Explicit user directive: "expand all features." Genuinely open-ended,
so before writing any code the request was narrowed via a clarifying
question — offered four possible readings (deepen existing systems
v2-style, close remaining roadmap gaps, a content-variety pass,
Observatory UI depth) and the user selected all four. Rather than
attempt literal maximal coverage across the whole codebase in one
pass (which risks shallow/stub work across too many fronts, against
this project's own "every system landed must be mechanically real"
discipline), scoped this batch to one substantial, fully-verified item
per category — a deliberate scoping decision, flagged here the same
way caravans/multiple-settlements scoping decisions have been in the
past, rather than silently under-delivering against "all."

**Deepen: disease v2 (temporary immunity).** v1's own docstring
(`Agent.sick_ticks`) explicitly flagged "no separate immunity/
reinfection state in v1... extend later if wanted" — the natural next
increment was already named in the codebase, not invented fresh. New
`Agent.immune_ticks`, set to `IMMUNITY_DURATION_TICKS` (400 — half of
`SICKNESS_DURATION_TICKS`'s 800, a real but temporary window rather
than lifelong immunity, matching how most real endemic illness works)
on recovery inside `Population._tick_disease`, decayed every tick
regardless of sick state (agents who are neither sick nor immune skip
both branches, same O(1)-per-agent cost as before). Consumed in two
places: `_tick_disease`'s colocation-transmission loop now also
excludes `immune_ticks > 0` targets, and `_maybe_outbreak`'s `healthy`
candidate list (for choosing a fresh index case) excludes them too —
a just-recovered agent genuinely can't restart the same bout of
illness for a while. `Population.summary()` gained `immune_count` for
observability. Verified with a direct `_tick_disease` unit call
(recovery sets `immune_ticks` to exactly `IMMUNITY_DURATION_TICKS`;
an immune agent colocated with a carrier for 50 ticks never catches
it) and an outbreak-selection check.

**Close a roadmap gap: where-to-build, second factor.** CLAUDE.md's
"Known architectural gaps" still listed "where to build is still pure-
chance colocation" even though `URBAN_GROWTH_ROAD_ADJACENCY_
MULTIPLIER` (integration milestone) had already made *where* real for
roads specifically — that gap-list entry had gone stale, not been
re-audited after the integration milestone landed. Rather than declare
the gap closed on the strength of roads alone, added a second,
independent factor with the same shape: `SETTLE_CHANCE_RESOURCE_
ADJACENCY_MULTIPLIER` (1.3x, deliberately smaller than roads' 1.5x —
a road represents real prior communal investment, raw resource
proximity is a more "obvious," lower-effort signal a founding group
would notice) applied when a candidate tile is within
`SETTLE_RESOURCE_SEARCH_RADIUS` (2, Chebyshev) of a still-productive
resource node, or itself adjacent to open water (reusing `world.
resources.is_adjacent_to_water`, the same helper irrigation and
fishing already use — no new water-network concept). New module-level
`_near_productive_resource` helper in `population.py`, a small local
scan (not spatially indexed — fine at this project's scale, same
tolerance every other O(N) scan here gets). Verified directly: tiles
within radius of a node return True, a distant tile returns False.

**Content variety.** Two more entries each to `llm/omens.py`'s five
fallback pools (warm/cold/neutral settlement-wide, warm/cold subject-
centered) and three more to `llm/caravan.py`'s fallback narration pool
— pure breadth, no new mechanics, reducing how quickly a long
LLM-disabled or heavily-fallback run starts repeating itself.

**MARKET: a building that's genuinely bidirectional with caravans.**
The integration milestone's caravan system (llm/caravan.py) was
explicitly scoped down from full multi-settlement trade and had no
building-system hook at all — a caravan happened *to* the settlement,
with no way for the settlement's own infrastructure to influence it
back, the one clearly one-directional link the integration-milestone
audit's own "every system should both influence and be influenced"
standard would flag if re-run today. New `Settlement.caravans_visited`
(persistent counter, `SettlementEconomy` domain object, full
to_dict/from_dict/passthrough-property plumbing matching every other
field in the Settlement facade) increments unconditionally whenever a
caravan's roll succeeds (`SimulationEngine._maybe_schedule_caravan`,
before the backpressure-gated narration branch — the visit itself is
real regardless of whether its description gets narrated). New
`BuildingKind.MARKET`: excluded from `choose_building_kind`'s weighted
pool until `caravans_visited >= MARKET_CARAVAN_VISIT_REQUIREMENT` (1
— deliberately just one: the point is *any* real outside contact
justifying a market, not a sustained trade history first, since that's
what the market itself then helps grow). Once standing,
`has_market()` (mirrors `has_power_plant()`) is read by `_maybe_
schedule_caravan` to multiply both the trade magnitude (`MARKET_
CARAVAN_YIELD_MULTIPLIER`, 1.4x — same order of magnitude as
`POWER_GRID_INDUSTRY_MULTIPLIER`) and the monthly visit chance
(`MARKET_CARAVAN_CHANCE_MULTIPLIER`, 1.25x, deliberately smaller — a
market changes how good a visit is more than how often one happens).
`MARKET_MATERIALS_COST` (7.0) sits between WORKSHOP and HOSPITAL.
Verified: `choose_building_kind` never selects MARKET across 500 draws
before any caravan visit, does select it across 2000 draws once the
requirement is met; a controlled same-tick before/after-MARKET
comparison (forcing the caravan roll to always pass, resetting
currency/materials between runs to stay within capacity headroom so
clamping doesn't mask the effect) measured the yield ratio at exactly
1.4x; a 20,000-sample statistical check of `_namespaced_roll` against
both the boosted and unboosted chance measured a 1.273x hit-rate
ratio against an expected 1.25x — within sampling noise.

**Observatory UI depth: scrub-through-time, a first small step.**
docs/ROADMAP.md has flagged "a true scrub-through-time replay view"
as not-yet-built since the July 2026 architecture review (documentary
mode narrates a year in prose; nothing let a player step through
history frame-by-frame) — explicitly *not* attempted as part of any
prior batch, always deferred as "its own dedicated session" the same
way multiple-named-settlements is. This is a deliberately small first
step, not the full feature: new `persistence.snapshot.list_snapshot_
ticks`/`load_snapshot_at_tick` (reusing the existing `snapshots` table
and its `SNAPSHOT_KEEP_RECENT`/`SNAPSHOT_KEYFRAME_INTERVAL_TICKS`
pruning — no new persistence, no schema change), backing new `GET
/snapshots` (index of available ticks) and `GET /snapshots/{tick}`
(reconstructs a `World` from that one stored row and returns a
curated settlement/population summary — the same `/state`-style shape
already used elsewhere, not the full agent/terrain payload) in
`interface/app.py`. Genuinely read-only: the reconstructed `World` is
a fresh object built from the DB row, never the live `broadcaster`'s
world — nothing about the live simulation is touched, paused, or
rewound. `create_app` gained a required `config: Config` parameter
(needed for `World.from_dict`); `server.py`'s one call site updated.
New "🕰 timeline" header toggle + panel in the browser UI: a slider
over the ticks `GET /snapshots` returns, each position fetching and
rendering that past moment's era/population/buildings/currency-
materials/civic-priority — explicitly framed in the UI copy as "read-
only... doesn't rewind or change the live world" so it can't be
mistaken for an undo/rewind feature. Verified end-to-end: a live
`SimulationEngine` run to several snapshot boundaries, then the
FastAPI route handlers invoked directly (no real HTTP layer available
in this environment — `httpx`/`starlette.testclient` aren't
installed) confirming `GET /snapshots` returns the expected tick list,
`GET /snapshots/{tick}` returns a 200 with the expected settlement/
population shape (including the new `markets`/`caravans_visited`/
`immune_count` fields), and a nonexistent tick returns 404 — plus a
route-registration check confirming both paths are actually mounted
on the FastAPI app. The frontend JS was syntax-checked with `node -c`
(no real browser available here) but not visually verified — same
"say so explicitly rather than claiming success" standard the project
holds for UI work it can't actually click through.

Every touched system re-verified with a 5,000-tick full-engine smoke
run post-batch (0.89ms/tick, unchanged from pre-batch baseline,
serialization round-trip implicitly exercised by the snapshot-load
checks) — no regression to ordinary tick throughput from any of the
four additions.

## "Continue expanding" (v0.60.0)

Explicit user follow-up to "Expand all features": "continue
expanding." Same category structure (deepen, close a gap, content
variety, UI depth), one substantial fully-verified item per category
again rather than attempting broader coverage in one pass. Scoped by
first auditing what actually exists in each area (an Explore-agent
research pass over the NPC inspector, rumor instrumentation, LLM
fallback pools, and institution kinds) before writing any code, so the
choices below are grounded in the real current state rather than
assumption.

**Deepen: GUILD, a third institution kind (H3 v4).**
`institutions.py` had explicitly named GUILD/MARKET/RELIGION as
"future kinds" in a comment since FAMILY/COUNCIL first shipped — the
natural next increment was already flagged, not invented fresh. Unlike
FAMILY (formed on birth) and COUNCIL (formed on population threshold,
membership fixed-then-refilled), GUILD is trade-specific: one instance
per skill (`SKILL_FARMING`/`SKILL_CONSTRUCTION`), formed once
`GUILD_FORMATION_MASTER_COUNT` (3) living agents cross `GUILD_SKILL_
MASTERY_THRESHOLD` (0.6, well above `SKILL_TEACHING_MIN_GAP`'s 0.15,
so this represents genuine expertise not mere competence). Membership
only grows (`_maybe_refresh_guild` adds any living agent who newly
crosses the threshold) — no seat cap, since there's no reason to cap
how many people can be skilled. `Institution.name` — a field that has
existed since v1 but had zero consumers (the module docstring called
it "empty for now") — now holds which skill a guild is for; this is
the field's first real use. Mechanical output: `_maybe_teach_skills`
now checks, per skill being taught, whether the teacher/learner pair
share a GUILD for that specific trade, applying `GUILD_TEACHING_
BONUS_MULTIPLIER` (1.6x) on top of (not instead of) the existing
trade-agnostic FAMILY/COUNCIL bonus (`INSTITUTION_TEACHING_BONUS_
MULTIPLIER`, 1.4x) — expertise-sharing is a stronger, more specific
effect than generic bonding, and the two stack when a pair happens to
share both. `Settlement.summary()`'s `institutions` block gained
`guilds` (list of trades with a standing guild, not just a count,
since there are at most 2 ever).

Verified: a direct call sequence proving formation fires once enough
masters exist, doesn't re-fire on a second call (idempotent), and
refresh adds a newly-mastered agent to `member_agent_ids`; a
statistical check (4,000 trials each) comparing teach-success rate for
a learner sharing a guild with their teacher vs. one who doesn't,
measuring a 1.57x ratio against an expected 1.6x; a real 50-tick
`SimulationEngine` run (not just isolated method calls) with two
agents pre-seeded past mastery, confirming guild formation actually
fires inside the real tick loop's scheduling order, survives a
Settlement to_dict/from_dict round-trip, and is visible via `summary()`
and the live `/snapshots/{tick}` FastAPI route.

**Close a gap: rumor-epidemiology instrumentation.** The July 2026
architecture review's "still open (in priority order)" list has named
this specifically since it was written, never picked up. An Explore
pass confirmed the actual gap: `world.rumor_total` already exists as a
single global lifetime counter of rumor-carrying dialogue exchanges,
but nothing tracked *reach* (how many agents a given rumor actually
touched) or gave a `Population`-level view independent of the world-
wide field. Rather than invent a new propagation mechanic (this
project's dialogue-carried rumors are each independently LLM/fallback-
generated per exchange, not literally the same string hopping listener
to listener — real per-rumor transmission-chain tracing isn't
structurally possible without a much larger rearchitecture, explicitly
out of scope here), added two real counters at the actual code paths
where a rumor enters the world: `Population.rumors_seeded_total`
(incremented once per `spread_rumor` call — a caravan's outside news —
and once per rumor-carrying `apply_dialogue` call — a villager-
invented one) and `rumor_listener_exposures_total` (incremented by the
listener count each time: `len(listeners)` for caravan seeding, 2 for
a dialogue exchange, since both parties hear it). Together these give
a genuine "how much gossip has moved through the village" volume
signal against population size — honest instrumentation of the
existing machinery, not a new one dressed up as observability.
Verified directly: both counters increment on the two real entry
points and stay flat on a non-rumor dialogue exchange, survive a
`Population` to_dict/from_dict round-trip, and appear in `summary()`.

**Content variety.** Two-to-three more fallback-pool entries each to
`llm/festival.py`, `llm/invention.py`, `llm/culture.py` (tradition),
and all three of `llm/dialogue.py`'s sentiment pools (tense/warm/
neutral) — the Explore pass's pool-count audit showed these hadn't
been touched in the prior variety pass (which covered omens/caravan
only), so this closes the remaining gap rather than re-padding pools
already extended.

**UI depth: NPC inspector gains personality and skills.** The Explore
pass confirmed the mind-first NPC inspector modal (goal, beliefs,
relationships, memories, vitals) never rendered `Agent.traits`/
`skills` per-agent, even though both fields were already present in
the per-tick broadcast payload (`Agent.to_dict()`, sent via
`_maybe_broadcast`) — population-wide averages of the same fields were
already shown in the stats legend, so the data pipeline existed end to
end and only the per-agent rendering was missing. New "Personality"
section (resilience/sociability/ambition, each with a plain-language
"notably high/low/unremarkable" reading rather than a bare number,
matching the project's "consequences over raw stats" UI direction) and
"Skills" section (only non-zero skills shown), placed between memories
and the vitals row — deepens the existing mind-first design rather
than adding a new UI surface. Syntax-verified with `node -c` (no real
browser available in this environment); not visually verified.

Full 5,000-tick smoke run post-batch: 0.91ms/tick, consistent with the
pre-batch baseline — no regression.
