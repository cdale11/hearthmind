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
- **No external Python dependencies.** Everything here is Python standard
  library (`sqlite3`, `asyncio`, `dataclasses`, `random`, `hashlib`, `json`,
  `urllib`). This keeps the project trivially runnable on modest hardware
  and easy for new contributors to pick up. Ollama (see "LLM cognition
  layer" below) is the project's first real *external* dependency, but
  it's an optional local *service*, not a new pip package — talking to it
  only needed `urllib`, already in the standard library.
- **LLM failure degrades quality, never liveness.** Every LLM-backed
  decision goes through a timeout and a deterministic, rule-based
  fallback and never raises into the tick loop. Ollama being slow,
  unreachable, or not installed at all makes agents behave more simply —
  it never stalls or crashes the simulation. See `docs/DECISIONS.md`, B1.

## Project layout

```
hearthmind/
  config.py          # tunable simulation parameters
  time_system.py      # SimClock: ticks -> minutes/day/season/year
  world/
    terrain.py         # deterministic terrain generation (midpoint displacement)
    weather.py          # deterministic, seasonally-aware weather system
    resources.py         # depletable, regenerating forageable resource nodes
    state.py              # World: the aggregate root, (de)serializes to dict
  agents/
    agent.py             # Agent: needs, aging, relationships, lifecycle constants
    population.py         # Population: spawns/ticks agents; foraging, birth, death, construction
    names.py               # deterministic name generation
  settlement/
    buildings.py            # Building/Settlement: construction, weathering, repair, reclamation
  economy/
    farms.py                 # FarmGrid/FarmPlot: planting, growth, harvest
  persistence/
    database.py          # SQLite schema + connection helper
    snapshot.py           # save_snapshot / load_latest_snapshot / event log
  llm/
    client.py              # minimal stdlib-only Ollama HTTP client
    jobs.py                  # CognitionRunner: bounded-concurrency async LLM calls with fallback
    cognition.py              # per-agent goal prompt/parse/fallback
    chronicle.py               # seasonal world-history summarization
  simulation/
    engine.py                   # SimulationEngine: the tick loop + lifecycle + LLM scheduling
  server.py                      # CLI entrypoint that runs the engine forever
  inspect_world.py                # CLI to print a summary of the saved world state
tests/                             # unittest-based tests (stdlib only)
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
- `--initial-population INT` — inhabitants spawned when a world is first
  created (default 12; only used the first time, like `--seed`).
- `--llm-enabled` — turn on the Ollama cognition layer (off by default;
  see below).
- `--llm-host URL` (default `http://localhost:11434`), `--llm-model NAME`
  (default `qwen2.5:3b`), `--llm-timeout SECONDS` (default 20 — CPU
  inference under contention on 8GB+zram can be slower than a quiet
  benchmark, see `docs/DECISIONS.md` D5), `--llm-max-concurrent INT`
  (default 2) — all runtime settings, safe to change between runs.

With the defaults, 1 real second = 15 sim-minutes, so a full sim day
(24h) passes roughly every 96 real seconds — fast enough to watch seasons
turn over in a single sitting while developing, but every constant is a flag
so this is easy to slow down later for a "real" long-running deployment.

## LLM cognition layer (Ollama)

Off by default — the simulation is fully deterministic and testable
without Ollama installed at all (`fallback_goal`/`fallback_summary` stand
in for it, see `docs/DECISIONS.md` B1-B3). The default model,
`qwen2.5:3b`, is sized specifically for comfortable operation on an
8GB-RAM machine (even with zram swap) alongside the simulation itself —
~2GB of weights, fast CPU inference, and reliable structured JSON output
(see `docs/DECISIONS.md`, B4). Size up (`--llm-model qwen2.5:7b`) if you
have more RAM to spare, or down (`qwen2.5:1.5b`) on tighter hardware. To
turn it on:

```bash
# 1. Install and start Ollama (see https://ollama.com), then pull a model:
ollama pull qwen2.5:3b

# 2. Run the server with the LLM enabled:
python3 -m hearthmind.server --db world.sqlite3 --llm-enabled
```

With it enabled, each agent's daily goal (wander/forage/socialize/rest)
and the seasonal chronicle entry are LLM-authored instead of rule-based;
everything else about the simulation is unaffected. Any LLM failure
(unreachable server, timeout, malformed response) transparently falls
back to the same deterministic behavior used when it's disabled — see
`hearthmind/llm/jobs.py`.

**Verified against a real Ollama instance:** confirmed working on real
hardware — `--agents` output showed genuine, contextual, weather-aware
LLM-authored reasoning (e.g. *"To gather food before hunger increases in
rainy weather"*), not the canned fallback text. That same real run also
surfaced a severe bug (`CRITICAL_HUNGER_THRESHOLD`/D3 below) that no unit
test had caught: the LLM correctly recognized starving agents and set
`goal=forage`, but the deterministic execution layer ignored it because
resting blocked foraging entirely, with nothing able to interrupt rest
for a hunger emergency — the LLM's judgment was right and irrelevant.
Fixed in D3; see `docs/DECISIONS.md` for the full story. This is a good
demonstration of why "verified" means actually running it, not just
passing tests against a fake server.

To check it yourself:

```bash
python3 -m hearthmind.inspect_world --db world.sqlite3 --agents
```

for each inhabitant's current `goal`/`goal_reason`, and watch the
`Recent events` list for `chronicle` entries — see `docs/TESTING.md`.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

See `docs/TESTING.md` for the full release checklist (unit tests plus real
CLI smoke tests for fresh-world, resume, and migration paths) — run before
every release, not just unit tests.

## Milestone status

- [x] **Milestone 1 — Core sim loop + persistence.** Deterministic terrain,
      clock, and weather; SQLite snapshots + event log; graceful
      start/stop/resume. No LLM, no network interface yet.
- [x] **Milestone 2 — Agents (population, needs, movement, lifecycle).**
      A population of named inhabitants spawns on walkable terrain,
      wanders, forages depletable resource nodes, ages, can die of
      starvation or old age, and can reproduce with agents they've built
      affinity with — all deterministic per `(seed, tick)`, all persisted.
      Still missing: any LLM involvement (still ahead in Phase B) and any
      settlement-level structure (buildings, roads — Phase C).
- [~] **Phase B — LLM cognition layer (Ollama), slice 1.** Off by
      default. When enabled: agents get a daily LLM-chosen goal
      (wander/forage/socialize/rest) that biases their behavior, and a
      seasonal chronicle entry is written to the event log. Deterministic
      fallbacks make both features work even without Ollama installed.
      **Verified against a real running Ollama instance** — see "LLM
      cognition layer" above; that same verification run also surfaced
      and led to fixing a real starvation-trap bug (D3) that no unit test
      had caught.
- [~] **Phase C — Settlements & construction, slice 1.** Colocated,
      mature, healthy agents may found a building; any awake agent
      present advances its construction (or repairs a damaged standing
      one); weather decays standing buildings into ruins over time;
      long-abandoned ruins are eventually reclaimed and removed. Building
      placement is deterministic in this slice, not yet an
      LLM/goal-driven decision — see `docs/DECISIONS.md`, C1. **Not
      personally witnessed through organic play at first:** two early
      soak tests (~8,600 and ~17,000 ticks) saw populations collapse from
      starvation before reaching the maturity needed to found a
      settlement — later resolved by Phase D; see below and
      `docs/DECISIONS.md`, C5/D4.
- [~] **Phase D — Agriculture, slice 1 + social-dispersion fix.** Any
      awake agent can plant a farm plot on grassland; it grows
      automatically and yields far more food than wild foraging once
      ready. Farming alone fixed starvation-before-maturity (verified),
      but revealed agents surviving indefinitely alone with no pressure
      to cluster — traced to two concrete bugs (SOCIALIZE's search radius
      too small for the map size, and the deterministic fallback never
      choosing SOCIALIZE at all) and fixed. **Verified with the exact
      30-agent/48x48 run that previously showed zero clustering:** with
      both fixes, the same config produced a self-sustaining,
      multi-generational population — 30+ births, a repeating building
      lifecycle (construction → completion → weathering → ruin) across 8+
      structures, and the first old-age death observed in any soak test —
      sustained for ~3 sim-years. A follow-up real-Ollama soak run then
      surfaced a related gap (an awake, critically hungry agent assigned
      SOCIALIZE/WANDER had nothing making it deliberately seek food until
      its next once-per-day goal reevaluation) — fixed in D5, along with
      persisted diagnostics (`inspect_world` now shows cumulative LLM
      fallback rate and deaths-by-cause) for catching the next one faster.
      See `docs/DECISIONS.md`, D1-D5.
- [ ] Phase E — Culture & history.
- [ ] Phase F — Browser interface (read-mostly observation + sparse
      intervention actions).
- [ ] Phase G — Supernatural / psychological horror layer.

See `CHANGELOG.md` for a version-by-version history, `docs/DECISIONS.md`
for the reasoning behind non-obvious choices, and `docs/ROADMAP.md` for
the longer-term plan.
