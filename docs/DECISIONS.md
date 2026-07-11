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
