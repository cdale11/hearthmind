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
