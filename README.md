# Hearthmind

Hearthmind is a persistent, always-running artificial world — "a town in a box."

The simulation runs continuously as a standalone server process. The browser
interface only ever *observes* and *nudges* the world; it is never required
for the simulation to keep going. Closing every client, or having no client
at all, does not pause anything.

## Design philosophy

- **The server owns time.** The simulation advances on its own fixed tick loop.
  Nothing about ticking depends on a client being connected.
- **Physical core, interpretive surface.** The deterministic engine models
  objective reality (time, weather, physics, resources, ecology,
  construction, decay); everything involving judgement, psychology, or
  social behavior routes through a local LLM with a deterministic fallback
  — agents reason about a world whose physics they can't talk their way
  around. Reproducibility-for-a-given-seed is *not* a project requirement
  (dropped deliberately — emergence wins over replayability), though most
  physical systems still happen to use seeded RNG where it's the natural
  tool.
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
  config.py            # tunable simulation parameters (CLI defaults mirror these)
  time_system.py       # SimClock: ticks -> real 365-day/12-month calendar
  world/
    terrain.py           # deterministic terrain generation (midpoint displacement)
    terrain_evolution.py # deforestation, reclamation, climate/biome drift
    weather.py           # deterministic UK-maritime monthly weather
    daylight.py          # real UK sunrise/sunset -> night factor
    hydrology.py         # rivers (carved at creation) + lakes with living levels
    disasters.py         # floods, wildfires, storms, heatwaves, frost
    resources.py         # depletable, regenerating forage/ore/fishing nodes
    wildlife.py          # grazer herds + predator packs, huntable ecology
    roads.py             # foot-traffic-driven path wear/decay
    state.py             # World: the aggregate root, (de)serializes to dict
  agents/
    agent.py             # Agent: needs, traits, skills, memories, lifecycle constants
    population.py        # Population: the whole per-tick agent loop (forage, build,
                         #   trade, teach, disease, institutions, birth, death)
    names.py             # deterministic name generation
  settlement/
    buildings.py         # Building/Settlement (4 composed domains), eras, upkeep
    institutions.py      # FAMILY / COUNCIL / GUILD entities that outlive members
    vehicles.py          # carts, mounts, era-gated automobiles
    naming.py            # deterministic placeholder settlement names
  economy/
    farms.py             # FarmGrid/FarmPlot: planting, growth, rot, irrigation
  persistence/
    database.py          # SQLite schema + connection helper (WAL)
    snapshot.py          # snapshots (pruned + keyframes), event log, metrics
  llm/
    client.py            # minimal stdlib Ollama HTTP client
    jobs.py              # CognitionRunner: bounded concurrency + fallback guarantee
    cognition.py         # per-agent goals      chronicle.py    # monthly narration
    dialogue.py          # NPC-to-NPC dialogue  documentary.py  # yearly look-back
    culture.py           # traditions           invention.py    # tech unlocks
    festival.py          # festivals            caravan.py      # outside trade contact
    town_brain.py        # civic priority       beliefs.py      # evolving town theories
    omens.py             # Phase G ambiguity    naming.py       # LLM settlement naming
    world_genesis.py     # one-time LLM-chosen world seed
  interface/
    api.py               # WorldBroadcaster: framework-free bridge engine <-> web
    app.py               # FastAPI app: /state /terrain /events /history /metrics
                         #   /diagnostics /snapshots /intervene/* + WS /ws
    static/              # plain HTML/CSS/JS browser client, no build step
  simulation/
    engine.py            # SimulationEngine: the tick loop + LLM/API scheduling
  server.py              # CLI entrypoint that runs the engine forever
  inspect_world.py       # CLI to print a summary of the saved world state
  experiment.py          # headless seed-batch runs -> per-sim-day metrics CSVs
```

## Running it

> **On 8GB RAM and Ollama is swapping?** Jump to
> [⚠️ Running on 8GB RAM](#-running-on-8gb-ram--stop-ollama-from-swapping-read-this-first)
> first — the fix is mostly a handful of `OLLAMA_*` environment variables
> set before `ollama serve`, and it's the difference between a smooth run
> and constant swap. Or run `--llm-disabled` for a fully offline,
> zero-Ollama world.

```bash
# Start (or resume) the world. Ctrl+C for a graceful, saved shutdown.
python3 -m hearthmind.server --db world.sqlite3

# In another terminal, peek at the world without stopping the server:
python3 -m hearthmind.inspect_world --db world.sqlite3

# Headless research runs: N seeds under a chosen config, each run's
# per-sim-day metrics exported to CSV (see "GET /metrics") — the A/B
# harness for questions like "does the LLM measurably change outcomes?"
python3 -m hearthmind.experiment --seeds 1,2,3 --ticks 30000 --no-llm --label baseline
python3 -m hearthmind.experiment --seeds 1,2,3 --ticks 30000 --label with-llm
```

New worlds begin on March 1 (spring) — a founding party's first season —
with everyone spawning as a group near the map's best wild-food spot;
resumed older worlds keep the calendar they were created with.

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
  (default `qwen3:4b-instruct`), `--llm-timeout SECONDS` (default 60 —
  CPU inference under contention on 8GB+zram can be slower than a quiet
  benchmark, see `docs/DECISIONS.md` D5), `--llm-max-concurrent INT`
  (default 2 — deliberately low for 8GB-memory headroom; every CLI
  default mirrors its `Config` attribute, see the v0.63.0 audit) — all
  runtime settings, safe to change between runs.
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
unreachable, or times out. The default model, `qwen3:4b-instruct`, was
set per a live user report on their own 8GB machine (see the memory-
tuning section below) — it uses less real memory than the smaller
`qwen3.5:2b` it replaced, leaving substantial 8GB+zram headroom for the
simulation
process itself — if a live run shows 2B is too weak for coherent
town-brain/dialogue output, size up (e.g. `--llm-model qwen3:4b`) and
let the maintainers know. Qwen3.x is a hybrid "thinking" model; this
project always disables that (`"think": false`, plus a defensive
`<think>`-block strip) since every prompt here wants one strict-JSON
answer. See `docs/DECISIONS.md`, "LLM-as-brain batch," B4, and the
real-calendar/genesis-seed and world-model/beliefs follow-ups.

```bash
# 1. Install and start Ollama (see https://ollama.com), then pull a model:
ollama pull qwen3:4b-instruct

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

### ⚠️ Running on 8GB RAM — stop Ollama from swapping (read this first)

If Ollama is pushing your machine into swap, **the fix is almost
entirely Ollama *server* configuration, not this app.** Here's why: on
an 8GB box the memory Ollama holds resident is dominated by two things —
the model **weights** (loaded once, resident while the model is warm)
and the **KV cache**, whose size is `num_ctx × OLLAMA_NUM_PARALLEL ×
(bytes per element)`. That KV cache is allocated *up front at the full
`num_ctx`*, regardless of how short the actual prompts are. Ollama's
default `OLLAMA_NUM_PARALLEL` can be **4**, so out of the box it may
reserve *four* full context windows of KV cache — often 2-4 GB — on top
of the ~2.6 GB of weights. That's what tips an 8GB machine into swap,
and **reducing how often Hearthmind calls the model does not shrink it**
(the v0.70.0 core-cast fix cut call *volume*, which matters for
sustained CPU load, but resident weights + KV cache sit there while the
model is warm no matter how rarely you call it).

**Do this — set these before `ollama serve`, then restart Ollama:**

```bash
export OLLAMA_NUM_PARALLEL=1        # ONE KV-cache slot, not 4 — the single biggest win
export OLLAMA_KV_CACHE_TYPE=q8_0    # 8-bit KV cache: ~half the KV memory, negligible quality loss
export OLLAMA_FLASH_ATTENTION=1     # required for q8_0 KV; set both together
export OLLAMA_MAX_LOADED_MODELS=1   # never hold two models resident at once
export OLLAMA_KEEP_ALIVE=3m         # release the model during real lulls
# then (re)start the server:
ollama serve
```

`OLLAMA_NUM_PARALLEL=1` is safe with Hearthmind: `Config.llm_max_
concurrent=2` is our scheduling floor (two calls can be *in flight* from
our side), but with `NUM_PARALLEL=1` Ollama simply serves them one at a
time using a single KV slot — the second call waits ~17-20s longer, no
richness is lost. Combined with `q8_0` KV, this typically cuts Ollama's
KV cache by **~8×** versus the default (4 slots × f16).

**Already done for you on the app side (v0.71.1):** `llm_num_ctx` was
lowered `2048 → 1280` and `llm_num_predict` `512 → 384` after *measuring*
the real prompts (the biggest, the monthly chronicle, peaks at ~1000
tokens including generation — 1280 fits it with margin), and the
recent-events fed into prompts was trimmed `50 → 30`. That shrinks our
KV footprint ~37% on its own, on top of whatever the env vars save. You
don't need to touch these, but if you *raise* `--llm-num-ctx` you'll
grow Ollama's KV cache proportionally.

**If it still swaps after the env vars — size the model down.** The
model weights are the other big resident chunk (~2.6 GB for
`qwen3:4b-instruct`). A smaller model roughly halves that:

```bash
ollama pull qwen3:1.7b
python3 -m hearthmind.server --db world.sqlite3 --llm-model qwen3:1.7b
```

`qwen3:1.7b` (~1.4 GB) is the documented size-down path. It's a hybrid
"thinking" model, which Hearthmind already handles (`"think": false` +
a `<think>`-block strip on every call), so it behaves like an instruct
model here. Town-brain/dialogue prose will be a little less polished
than 4B; that's the trade for headroom. You can also shrink the
LLM-driven cast with `--llm-core-cast-size 8` (fewer deep NPCs, fewer
concurrent-ish calls) — though on 8GB the env vars + model size are the
levers that actually move resident memory.

**Confirm what's actually resident** while a run is live:

```bash
ollama ps                              # shows the loaded model's real size + whether it fits RAM
# or, from the running Hearthmind server, the attributed breakdown:
curl -s localhost:8765/diagnostics | python3 -m json.tool | grep -A20 system_memory
```

`/diagnostics.system_memory` reports this process's RSS/swap and each
Ollama process's RSS/swap separately, so you can see exactly where the
memory is going before changing anything.

### Use more CPU, not more memory (`--llm-num-thread`, v0.65.0)

The engine's own tick loop is nowhere near CPU-bound — ~0.9-1.2ms
against a 1000ms-per-tick budget (see `docs/DECISIONS.md`'s C/C++-port
evaluation) — so "maximize CPU usage" has no lever on the Python side;
burning more CPU there would buy nothing. The real CPU-bound work is
each Ollama inference call, and on CPU-only hardware Ollama's default
thread count is often conservative, leaving cores idle mid-call. This
is a genuinely *free* trade against memory: `--llm-num-thread` (default
`os.cpu_count()`, i.e. every core on the machine) tells Ollama to use
all available cores for a single call, finishing it faster — which
shortens the window that call's KV-cache allocation actually holds
memory. Unlike raising `--llm-max-concurrent`, this adds zero
concurrent KV-cache buffers; it just does the same work faster. Pass
`--llm-num-thread 0` to leave Ollama's own heuristic in charge instead
(e.g. if something else on the machine also needs CPU headroom).

**Diagnosing before changing anything:** as of v0.65.0,
`GET /diagnostics` (and the browser dev console) includes a
`system_memory` section attributing memory live — Hearthmind's own
RSS/swap, every Ollama process's RSS/swap, and system-wide
MemAvailable/swap-used. Check it during a pressure episode: if the
Ollama runner's `swap_mb` dominates, the levers above (and the model
choice below) are the fix; if `mem_available_mb` is low while Ollama is
modest, something else on the machine (often the browser tab itself) is
the real tenant. v0.65.0 also staggered the monthly LLM jobs across
different days of the month instead of firing all ~10 in one burst on
every month boundary — the "sparse but sudden" monthly swap spike came
from that cluster, not from any steady leak.

**Model choice (v0.65.2 update):** the default is now
`qwen3:4b-instruct`, changed from `qwen3.5:2b` on the strength of a
live user report — `qwen3.5:2b` showed memory-leak-like growth and
swapping on real 8GB hardware, while the larger `qwen3:4b-instruct`
stayed under 4.5GB with no swapping. **`qwen3.5:2b` is no longer
recommended** on this project: it isn't a real released Qwen tag (Qwen
releases are Qwen, 1.5, 2, 2.5, 3 — there is no "3.5"), so whatever it
resolved to locally was never a verified-good quantization the way an
official tag is; treat its apparent leak as a property of that specific
local blob, not of small models in general. If `system_memory` still
shows pressure on `qwen3:4b-instruct`, try `qwen3:1.7b` or
`qwen3:1.7b-instruct` (`ollama pull qwen3:1.7b`, then
`--llm-model qwen3:1.7b`) before going smaller — both are official
Qwen3 tags. Note the non-`-instruct` `qwen3:1.7b` is a hybrid-thinking
model, so `OllamaClient`'s `"think": false` handling becomes load-
bearing again for that one. `qwen3:0.6b` exists below that but
noticeably degrades the multi-field JSON decisions (town brain,
disputes, beliefs) — try it only as a last resort. Report back with
what you observe rather than silently switching, same standing policy
as before.

**Model choice under a 6GB ceiling, weighed against dialogue quality
(v0.66.0):** dialogue is the one output where raw model size matters
most directly — a bigger model writes less repetitive, more in-
character lines and hits `_is_sane_line`'s leakage/length rejection
far less often, on top of the grounding fix above. That pulls toward
staying on the largest model that fits; memory pulls the other way.
At the user-reported measurement (`qwen3:4b-instruct`, under 4.5GB,
no swap observed), the budget math from the section above still
leaves roughly 1.5GB of headroom under a strict 6GB ceiling (OS
~1-1.5GB, Hearthmind's own process under 200MB, Ollama daemon
overhead ~300-500MB — the model + KV cache is the rest) — tight but
workable, and the recommendation stays `qwen3:4b-instruct` rather than
sizing down preemptively. Apply `OLLAMA_FLASH_ATTENTION=1` +
`OLLAMA_KV_CACHE_TYPE=q8_0` (above) first if that margin ever gets
eaten by something else running on the same 6GB box — it buys back KV-
cache headroom without touching the model at all. Only size down to
`qwen3:1.7b` if a live `system_memory` reading still shows pressure
after that lever, and go in expecting a real, noticeable dialogue-
quality regression (shorter, more generic lines, more fallback-pool
triggers) as the direct cost — this is a case where the memory fix and
the "dialogue is off" fix are in tension, so don't downsize past the
point the 6GB ceiling actually forces. Non-Qwen alternatives (Llama
3.2 3B Instruct, Phi-3.5-mini, Gemma 2 2B) weren't adopted: staying in
the Qwen3 family keeps the existing `"think": false`/`<think>`-stripping
handling and every-generation-tested prompt shapes intact, and none of
them is a clear enough quality-per-GB win over `qwen3:4b-instruct` to
justify re-validating a whole new model family for this project.

**Why not switch to raw llama.cpp:** evaluated and recommended against
for now (see `docs/DECISIONS.md`, "Model default: `qwen3:4b-instruct`
replaces `qwen3.5:2b`"). Ollama's own runner already *is* llama.cpp —
the memory an `ollama` process holds is overwhelmingly model weights +
KV cache, which a direct llama.cpp deployment would use just as much of
for the same model/quantization/context. Ollama's own overhead on top
of that is real but small (~100-300MB, its Go daemon + blob store), not
the multi-GB swap-triggering delta a migration would be chasing —
whereas rewriting `OllamaClient` around a different API is a genuine
engineering cost. Revisit only if `system_memory` still shows the
Ollama runner dominant after every lever above (flash attention + q8_0
KV cache, `OLLAMA_NUM_PARALLEL=1`, `--llm-num-thread`, and the
`qwen3:4b-instruct` switch) is actually applied and measured.

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
festivals, a relationship graph, an NPC "mind-first" inspector, a
history tab, a scrub-through-time timeline, live pause/speed controls,
and a `⚙ dev` toggle exposing raw engine telemetry (tick timing,
background task counts, connected clients, LLM latency) plus a
"Full diagnostic report" button (`GET /diagnostics`) for debugging an
unattended overnight run — all updating once per tick over a WebSocket
while a client is connected (with none connected, the payload is
rebuilt every ~10 ticks just to keep `GET /state` serviceable — the
sim itself never slows down or speeds up either way). Intervention
("nudge") endpoints exist under `/intervene/*` — agent goals,
settlement stores, weather, a whispered suggestion to the town brain,
and sim pause/speed.

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

## Verification

This project does **not** run its automated unit test suite (a standing
workflow decision — it was deemed unreliable). Changes are verified via
ad-hoc scripts against the real engine, multi-thousand-tick smoke runs,
and — as the actual source of truth — live diagnostic reports from real
hardware with a real Ollama server. See `docs/TESTING.md` for the
workflow and the CLI smoke tests that are still worth running.

## Status

All original phases (A–F), the ambient Phase G layer, and the full
Phase H program (dynamic carrying capacity, institutions —
families/councils/guilds, evolving beliefs/world-models at settlement,
family, and personal scale, skills and teaching, supply chains and
personal property, inheritance, psychology traits) have shipped at
least a v1, plus an integration milestone wiring the systems into each
other. As of v0.65.0 the three last architectural gaps are closed too:
**multiple named settlements** (a crowded settlement can fission — an
LLM-decided founding party walks to a distant site and builds a second
named community with its own economy, institutions, temperament, and
place in the monthly LLM job rotation), **fully agent-pathed
construction** (founders stake out the best nearby site and builders
walk to it), and **true frame-by-frame replay** (the timeline's ▶
button plays the world's real past maps snapshot by snapshot). The one
surviving deliberate deferral is WebSocket delta payloads — see
`CLAUDE.md`.

See `CHANGELOG.md` for the version-by-version history,
`docs/DECISIONS.md` for the reasoning behind non-obvious choices (the
project's primary archive), and `docs/ROADMAP.md` for the phase plan
and its per-item accounting.
