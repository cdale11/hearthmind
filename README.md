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
- **Base install is dependency-free; the browser interface isn't.**
  Everything the simulation itself needs is Python standard library
  (`sqlite3`, `asyncio`, `dataclasses`, `random`, `hashlib`, `json`,
  `urllib`) — trivially runnable on modest hardware, easy to pick up.
  Ollama (see "LLM cognition layer" below) is an optional local
  *service*, not a pip package — talking to it only needed `urllib`. The
  browser interface (see below, Phase F) uses FastAPI + uvicorn, tracked
  in `requirements.txt` and the `api` extra (`pip install
  hearthmind[api]`). The browser interface is **on by default** — install
  the extra to use it; without it, `server.py` logs a warning and runs
  without the browser window rather than crashing (`--api-disabled` to
  turn it off on purpose). External libraries are allowed project-wide
  as of Phase F; see `docs/DECISIONS.md`, F1/F2.
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
    wildlife.py          # grazer herds + predator packs, huntable (A4)
    roads.py             # foot-traffic-driven path wear/decay (C5)
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
    culture.py                  # yearly tradition invention (Phase E)
    invention.py                # rare, prosperity-gated tech unlocks (E3)
    dialogue.py                 # NPC-to-NPC ambient dialogue (E2)
    festival.py                 # wellbeing-gated, seasonal collective events
  interface/
    api.py                        # WorldBroadcaster: framework-free bridge from engine to web layer
    app.py                         # FastAPI app: /, /state, /terrain, /events, WS /ws
    static/                         # plain HTML/CSS/JS browser client, no build step
  simulation/
    engine.py                   # SimulationEngine: the tick loop + lifecycle + LLM/API scheduling
  server.py                      # CLI entrypoint that runs the engine (+ optional browser API) forever
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
  Omit it and a brand-new world runs a one-time "genesis" LLM call to pick
  an evocative founding scenario whose text becomes the seed (falls back to
  a wall-clock-derived seed if the LLM is disabled/unreachable) — see
  "World genesis" below.
- `--tick-seconds FLOAT` — real seconds per tick (default 1.0).
- `--sim-minutes-per-tick INT` — sim-minutes advanced per tick (default 15).
- `--snapshot-every INT` — ticks between snapshots (default 60).
- `--width / --height` — terrain grid size (default 64x64).
- `--initial-population INT` — inhabitants spawned when a world is first
  created (default 12; only used the first time, like `--seed`).
- `--llm-disabled` — turn off the Ollama cognition/dialogue/culture layer
  (on by default as of E2; see below). Every LLM call still has a
  deterministic fallback, so this flag is only needed for a fully
  offline/deterministic run.
- `--llm-host URL` (default `http://localhost:11434`), `--llm-model NAME`
  (default `qwen3.5:2b`), `--llm-timeout SECONDS` (default 30 —
  CPU inference under contention on 8GB+zram can be slower than a quiet
  benchmark, see `docs/DECISIONS.md` D5), `--llm-max-concurrent INT`
  (default 4) — all runtime settings, safe to change between runs.
- `--api-disabled` — turn off the browser interface (on by default; see
  below). `--api-host` (default `0.0.0.0`), `--api-port` (default `8765`).

With the defaults, 1 real second = 15 sim-minutes, so a full sim day
(24h) passes roughly every 96 real seconds — fast enough to watch seasons
turn over in a single sitting while developing, but every constant is a flag
so this is easy to slow down later for a "real" long-running deployment.

## LLM cognition layer (Ollama)

On by default as of E2 — agent goals, the seasonal chronicle, yearly
culture/traditions, and NPC-to-NPC dialogue are all LLM-authored when
Ollama is reachable. The simulation stays fully functional without
Ollama installed (`fallback_goal`/`fallback_summary`/`fallback_tradition`/
`fallback_dialogue` stand in for it, see `docs/DECISIONS.md` B1-B3, E1,
E2) — nothing raises or blocks a tick if the LLM is disabled,
unreachable, or times out. The default model, `qwen3.5:2b`, was set by
explicit user instruction (confirmed pulled/available on their
machine), leaving substantial 8GB+zram headroom for the simulation
process itself — if a live run shows 2B is too weak for coherent
town-brain/dialogue output, size up (e.g. `--llm-model qwen3:4b`) and
let the maintainers know. Qwen3.x is a hybrid "thinking" model; this
project always disables that (`"think": false`, plus a defensive
`<think>`-block strip) since every prompt here wants one strict-JSON
answer. See `docs/DECISIONS.md`, "LLM-as-brain batch," B4, and the
real-calendar/genesis-seed and world-model/beliefs follow-ups.

```bash
# 1. Install and start Ollama (see https://ollama.com), then pull a model:
ollama pull qwen3.5:2b

# 2. Run the server (LLM is on by default):
python3 -m hearthmind.server --db world.sqlite3

# To run fully offline/deterministic instead:
python3 -m hearthmind.server --db world.sqlite3 --llm-disabled
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

## World genesis (LLM-chosen seed) and calendar

Omit `--seed` and a brand-new world runs a one-time "genesis" LLM call
before generating terrain/weather: the LLM writes a short founding-
scenario sentence ("Rolling grassland meets old forest along a slow
river, unclaimed and quiet."), and the hash of that sentence becomes the
world's seed — the same deterministic terrain/weather generation then
runs exactly as it would with an explicit `--seed`. If the LLM is
disabled or unreachable, a rotating pool of fallback scenarios stands in
(mixed with wall-clock entropy so it isn't the same handful of worlds
every time). Passing `--seed` explicitly always skips genesis. The
scenario text is shown once in the event log and in the settlement
summary (`founding_scenario`).

The world clock runs a real 365-day, 12-month calendar with UK-style
maritime weather baselines by month (mild wet winters, cool damp
summers, rain fairly even year-round) — `season` (spring/summer/autumn/
winter) is still derived from the month for anything that already used
it. A settlement starts in the `industrial` era and can advance
(electrical -> modern -> digital) as it accumulates inventions,
unlocking the FACTORY building kind past `industrial`.

## Browser interface (Phase F)

**On by default.** A real, live window into the world: a canvas map
(terrain, agents, buildings, farms, wildlife, road wear), a stat
dashboard covering every system (population, relationships, economy,
tech level, wildlife, roads, LLM/dialogue diagnostics), a human-readable
event log (icons, color-coded by category), traditions, inventions,
festivals, and a `⚙ dev` toggle exposing raw engine telemetry (tick
timing, background task counts, connected clients, LLM latency) plus a
"Full diagnostic report" button (`GET /diagnostics`) for debugging an
unattended overnight run — all updating once per tick over a WebSocket.
No intervention endpoints yet — this is observation-only, per the
roadmap (`docs/ROADMAP.md`, Phase F).

```bash
pip install -r requirements.txt   # or: pip install hearthmind[api]
python3 -m hearthmind.server --db world.sqlite3
```

Then open `http://localhost:8765` in a browser. If `fastapi`/`uvicorn`
aren't installed, the server logs a warning and runs without the browser
window instead of crashing — the simulation itself never depends on it.
Pass `--api-disabled` to turn it off on purpose. Endpoints, if you want
to script against it directly instead:

- `GET /state` — current world summary + agents/buildings/farms (same
  shape as one WebSocket tick).
- `GET /terrain` — the static biome grid (fetch once; it never changes).
- `GET /events?limit=N` — recent event-log history.
- `GET /metrics?limit=N` — the per-sim-day time-series (population,
  food, bonds, temperament, ...), oldest-first and chart-ready — the
  research counterpart to `/events`' narrative feed.
- `GET /diagnostics` — extensive on-demand report: engine telemetry, LLM
  call/latency/error breakdown, memory/DB size, all-time event-category
  histogram. Built for pasting into a bug report after a long soak run.
- `WS /ws` — one JSON message per tick, same shape as `GET /state`.

External libraries are allowed for this feature (project policy since
Phase F — see `docs/DECISIONS.md`, F2) but are still an **optional
extra**: the base simulation stays dependency-free — install
`requirements.txt` to get the browser window, or run with
`--api-disabled` (or without the extra installed) to skip it.

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
- [x] **Phase D — Agriculture & economy. Feature-complete per the
      original roadmap scope.** Farming, granaries, production chains
      (materials → construction speed + farm yield), and settlement
      currency (surplus → traded for emergency rations). Two real
      starvation bugs found via live-play diagnostics and fixed (D3, D5,
      D6 — resting blocking food, goal not overriding for critical
      hunger, FORAGE never targeting farms). See `docs/DECISIONS.md`,
      D1-D10.
- [x] **Phase E — Culture & history, slice 1.** Settlements are named
      once a building stands; named settlements invent one tradition per
      year; settlement name + latest tradition now appear in per-agent
      cognition prompts and the chronicle prompt. See `docs/DECISIONS.md`,
      E1.
- [x] **Phase F — Browser interface, slices 1-2.** A real, live browser
      window, on by default: canvas map, stat dashboard, traditions,
      festivals, event log, dev console, all updating once per tick over
      WebSocket (FastAPI + uvicorn backend). Intervention endpoints are
      deliberately not built yet — last, per the roadmap. External
      libraries are now allowed project-wide, tracked in
      `requirements.txt`. See
      `docs/DECISIONS.md`, F1/F2.
- [ ] Phase G — Supernatural / psychological horror layer.

See `CHANGELOG.md` for a version-by-version history, `docs/DECISIONS.md`
for the reasoning behind non-obvious choices, and `docs/ROADMAP.md` for
the longer-term plan.
