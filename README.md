# Hearthmind

Hearthmind is a persistent, always-running artificial world — "a town in a box."

The simulation runs continuously as a standalone server process. A browser (added
in a later milestone) will only ever *observe* and *nudge* the world; it is never
required for the simulation to keep going. Closing every client, or having no
client at all, does not pause anything.

## Design philosophy

- **The server owns time.** The simulation advances on its own fixed tick loop.
  Nothing about ticking depends on a client being connected.
- **Deterministic core, emergent surface.** Milestone 1 has no LLM yet. Every
  system (terrain, clock, weather) is seeded and deterministic, so the same
  seed always produces the same world and the same sequence of weather. This
  matters because later, an LLM "cognition" layer will sit *on top of* this
  deterministic substrate rather than replacing it — agents will reason about
  a world whose physics they can't talk their way around.
- **Persistence is not an afterthought.** The world is checkpointed to SQLite
  on an interval and on graceful shutdown. Restarting the server resumes the
  same world at the same tick — it does not regenerate anything.
- **Sim time only advances while the server is running.** If the server is off
  for three days, the world does not silently fast-forward three days' worth
  of ticks when it comes back — it resumes exactly where it left off. This is
  a deliberate milestone-1 decision (see `docs/DECISIONS.md`) that keeps
  compute bounded and avoids a "catch-up burst" of simulation; it can be
  revisited once we have costlier per-tick systems (agents, economy) where
  "what happened while I was gone" becomes an interesting question in itself.
- **No external dependencies.** Everything here is Python standard library
  (`sqlite3`, `asyncio`, `dataclasses`, `random`, `hashlib`, `json`). This
  keeps the project trivially runnable on modest hardware and easy for new
  open-source contributors to pick up. The LLM (Ollama) integration in a
  later milestone will be the first real external dependency.

## Project layout

```
hearthmind/
  config.py          # tunable simulation parameters
  time_system.py      # SimClock: ticks -> minutes/day/season/year
  world/
    terrain.py         # deterministic terrain generation (midpoint displacement)
    weather.py          # deterministic, seasonally-aware weather system
    state.py             # World: the aggregate root, (de)serializes to dict
  persistence/
    database.py          # SQLite schema + connection helper
    snapshot.py           # save_snapshot / load_latest_snapshot / event log
  simulation/
    engine.py              # SimulationEngine: the tick loop + lifecycle
  server.py                 # CLI entrypoint that runs the engine forever
  inspect_world.py           # CLI to print a summary of the saved world state
tests/                        # unittest-based tests (stdlib only)
```

## Running it

```bash
# Start (or resume) the world. Ctrl+C for a graceful, saved shutdown.
python3 -m hearthmind.server --db world.sqlite3

# In another terminal, peek at the world without stopping the server:
python3 -m hearthmind.inspect_world --db world.sqlite3
```

Useful flags on `server.py`:

- `--seed INT` — only used the first time a world is created at that DB path.
- `--tick-seconds FLOAT` — real seconds per tick (default 1.0).
- `--sim-minutes-per-tick INT` — sim-minutes advanced per tick (default 15).
- `--snapshot-every INT` — ticks between snapshots (default 60).
- `--width / --height` — terrain grid size (default 64x64).

With the defaults, 1 real second = 15 sim-minutes, so a full sim day
(24h) passes roughly every 96 real seconds — fast enough to watch seasons
turn over in a single sitting while developing, but every constant is a flag
so this is easy to slow down later for a "real" long-running deployment.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Milestone status

- [x] **Milestone 1 — Core sim loop + persistence.** Deterministic terrain,
      clock, and weather; SQLite snapshots + event log; graceful
      start/stop/resume. No LLM, no network interface yet.
- [ ] Milestone 2 — Agents (population, needs, movement) on top of this
      substrate.
- [ ] Milestone 3 — LLM cognition layer (Ollama) for agent decisions/memory.
- [ ] Milestone 4 — Browser interface (read-mostly observation + sparse
      intervention actions).
