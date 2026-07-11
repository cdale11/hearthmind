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

## A4: Migration flag generalized to `migrated_subsystems`

M2-3 introduced a single `migrated_population: bool`. Phase A needed the
same "detect absence, backfill, log it" behavior for a second subsystem
(`resources`), so the boolean became `migrated_subsystems: list[str]`,
and `SimulationEngine.load_or_create` iterates it against small
per-subsystem description/count-lookup tables (`_MIGRATION_DESCRIPTIONS`,
`_MIGRATION_COUNTS` in `simulation/engine.py`) instead of hand-writing a
new `if world.migrated_x:` branch per subsystem. Future subsystems that
need backfill-on-load should add an entry to those two tables and a branch
in `World.from_dict`, not invent a third mechanism.
