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
cpp/
  src/                   # C++ sources for hearthmind._native (pybind11 extension)
setup.py                 # builds hearthmind._native (optional — see below)
scripts/
  run.sh                 # starts llama-server + hearthmind.server together
```

## Native C++ extension (optional)

Started in v0.72.0 as an incremental port of the engine's hottest
per-tick loops into C++ (see `docs/DECISIONS.md`, "Native extension
port"). **Optional and additive** — every ported function has a
byte-identical pure-Python fallback in `hearthmind/`, so the simulation
runs correctly with or without a compiler. Fifteen modules ported so far:
`world/resources.py`'s `ResourceGrid.tick` (regrowing foraged/mined/
fished nodes), `agents/population.py`'s `_nearest_resource` (the
bounded-box FOOD/FISH lookup for foraging), `_nearest_material_tile`
(the same for GATHER-goal wood/stone), `_nearest_other_agent` (the
SOCIALIZE-goal lookup — uncapped by radius, so it scales with population
squared rather than map size), `world/wildlife.py`'s
`nearest_grazer_herd`, `_update_needs` (hunger/energy/aging math — the
first module from the **R6 "full engine rewrite"** track, started
v0.72.5: unlike the others, this runs unconditionally every tick for
every agent), `_maybe_predator_attack`'s kill-chance math,
`economy/farms.py`'s `FarmGrid.tick` (the first module from the **R7
"cellular-automata physical substrate"** track, started v0.72.6: new
code in the agriculture/ecology/weather/disasters/terrain-evolution
domain is now written in C++ from the start rather than ported later —
see `docs/REFACTOR-2026-07.md`, "R6" and "R7"), `settlement/
buildings.py`'s building decay/ruin/reclaim and vehicle decay passes,
`world/weather.py`'s `compute_weather` blend/threshold math (RNG
draws stay in Python; only the deterministic arithmetic moved), a
shared `bounded_random_walk_step` used by five separate monthly-nudge
functions across `settlement/buildings.py`, `world/terrain_
evolution.py`, and `world/hydrology.py`, `world/disasters.py`'s
`_wilt_farms` (heatwave/frost) and `tick_storm`'s flat-damage sweep,
and `apply_local_activity`'s/`tick_wildfire`'s roll batches (the latter
two share the same underlying native function). More hot loops and
physical-substrate modules move over incrementally, one
provably-equivalent module at a time (see "Refactor status" below).

```bash
pip install pybind11              # build-time only, not a runtime dependency
python3 setup.py build_ext --inplace
```

This builds `hearthmind/_native.*.so`. If it fails (no compiler, no
pybind11, unsupported platform) `pip install -e .` / running the
simulation still works — you'll just be on the pure-Python path for the
ported modules, exactly as before v0.72.0. `pip install -e .` also
attempts this build automatically via `pyproject.toml`'s build-system
requirement on `pybind11`. `scripts/run.sh` builds this automatically
every run (see below); set `SKIP_NATIVE_BUILD=1` to skip.

## Running it

> **New to this repo?** The LLM backend defaults to **llama.cpp**
> (`llama-server`) as of v0.72.0 — jump to
> [Running the LLM (llama.cpp)](#running-the-llm-llamacpp) to set it up,
> or [⚠️ Running on 8GB RAM](#-running-on-8gb-ram--stop-the-llm-server-from-swapping-read-this-first)
> if memory is tight. Prefer Ollama? Pass `--llm-backend ollama` — it's
> still fully supported, see [Alternative: Ollama backend](#alternative-ollama-backend).
> Or run `--llm-disabled` for a fully offline, zero-LLM world.
> **Once llama-server is built, `MODEL_PATH=... ./scripts/run.sh` starts
> both it and the game together** — see step 4 below.

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
- `--llm-disabled` — turn off the LLM cognition/dialogue/culture layer
  (on by default as of E2; see below). Every LLM call still has a
  deterministic fallback, so this flag is only needed for a fully
  offline/deterministic run.
- `--llm-backend {llamacpp,ollama}` (default `llamacpp`, v0.72.0) — which
  local LLM server to talk to; see
  [Running the LLM (llama.cpp)](#running-the-llm-llamacpp).
  `--llm-llamacpp-host URL` (default `http://localhost:8080`) for the
  llama.cpp backend, `--llm-host URL` (default `http://localhost:11434`)
  for the Ollama backend, `--llm-model NAME` (default `qwen3:4b-instruct`),
  `--llm-timeout SECONDS` (default 60 — CPU inference under contention
  on 8GB+zram can be slower than a quiet benchmark, see
  `docs/DECISIONS.md` D5), `--llm-max-concurrent INT` (default 2 —
  deliberately low for 8GB-memory headroom; every CLI default mirrors its
  `Config` attribute, see the v0.63.0 audit) — all runtime settings, safe
  to change between runs.
- `--api-disabled` — turn off the browser interface (on by default; see
  below). `--api-host` (default `0.0.0.0`), `--api-port` (default `8765`).

With the defaults, 1 real second = 15 sim-minutes, so a full sim day
(24h) passes roughly every 96 real seconds — fast enough to watch seasons
turn over in a single sitting while developing, but every constant is a flag
so this is easy to slow down later for a "real" long-running deployment.

## LLM cognition layer

On by default as of E2 — agent goals, the seasonal chronicle, yearly
culture/traditions, and NPC-to-NPC dialogue are all LLM-authored when
the local LLM server is reachable. The simulation stays fully functional
without it running (`fallback_goal`/`fallback_summary`/`fallback_
tradition`/`fallback_dialogue` stand in, see `docs/DECISIONS.md` B1-B3,
E1, E2) — nothing raises or blocks a tick if the LLM is disabled,
unreachable, or times out.

**Two backends, `Config.llm_backend` / `--llm-backend`:**

- **`llamacpp` (default, v0.72.0)** — talks to `llama-server`, llama.cpp's
  own HTTP server. See [Running the LLM (llama.cpp)](#running-the-llm-llamacpp)
  below for setup.
- **`ollama`** — the original backend, still fully supported for anyone
  with an existing Ollama install. See
  [Alternative: Ollama backend](#alternative-ollama-backend).

The default model tag/GGUF is `qwen3:4b-instruct` either way (set per a
live user report — see "Model choice" below); `-instruct` means
non-thinking by design, and this project always disables hybrid
"thinking" output regardless (`"think": false` for Ollama, plus a
defensive `<think>`-block strip applied by both clients) since every
prompt here wants one strict-JSON answer.

Any LLM failure (unreachable server, timeout, malformed response)
transparently falls back to the same deterministic behavior used when
it's disabled — see `hearthmind/llm/jobs.py`. To check it's actually
working:

```bash
python3 -m hearthmind.inspect_world --db world.sqlite3 --agents
```

for each inhabitant's current `goal`/`goal_reason`, and watch the
`Recent events` list for `chronicle` entries — see `docs/TESTING.md`.

## Running the LLM (llama.cpp)

llama.cpp talked to directly, rather than through Ollama's management
daemon, for three reasons: it removes Ollama's own ~100-300MB daemon
overhead and its opinionated defaults (mmap heuristics, keep-alive,
`OLLAMA_NUM_PARALLEL`) this project spent several releases fighting
around; it exposes context size, KV-cache quantization, thread count,
and GPU layer offload as direct process flags instead of environment
variables set on the user's behalf; and it's a straightforward path to
Vulkan iGPU offload (see the AMD Radeon 740M section below), which
Ollama's bundled ROCm build didn't recognize on this hardware (see
`docs/DECISIONS.md`, "iGPU offload investigation").

First, build `llama-server` yourself (`scripts/run.sh` does **not**
build or install llama.cpp — see below):

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_NATIVE=ON   # add -DGGML_VULKAN=ON for AMD iGPU offload, see below
cmake --build build --config Release -j$(nproc) --target llama-server
```

**Then, the easy way — one command builds `hearthmind._native` and runs
both processes:**

```bash
LLAMA_SERVER_BIN=/path/to/llama.cpp/build/bin/llama-server \
  MODEL_PATH=/path/to/Qwen3-4B-Instruct-Q4_K_M.gguf ./scripts/run.sh --db world.sqlite3
```

`scripts/run.sh` builds `hearthmind._native` (the C++ extension, see
above), starts `llama-server` (found via `LLAMA_SERVER_BIN` or on
`PATH`) with the flags below, waits for its `/health` endpoint, then
starts `hearthmind.server` — and stops both cleanly on Ctrl+C
(hearthmind's own graceful shutdown/snapshot runs first). See the
script's header comment for every environment variable it reads
(`LLAMA_CTX_SIZE`, `LLAMA_N_GPU_LAYERS`, etc. — all optional, defaults
match this section). Get a GGUF first: search Hugging Face for a
quantization of `Qwen3-4B-Instruct` (community accounts like
`bartowski`/`unsloth` publish these routinely) and download a `Q4_K_M`
file (~2.6GB).

**Confirmed working** on real GPU-offloaded hardware — noticeably
better than the CPU-only path this project started from.

**The fully manual way**, if you'd rather run both processes yourself
(this is exactly what `scripts/run.sh`'s launch step automates):

```bash
./build/bin/llama-server \
  --model /path/to/Qwen3-4B-Instruct-Q4_K_M.gguf \
  --ctx-size 3072 --parallel 1 \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --no-mmproj --port 8080 \
  --n-gpu-layers 999 --threads $(nproc)

# in another terminal:
python -m hearthmind.server --db world.sqlite3

# fully offline/deterministic instead (no llama-server needed either way):
python -m hearthmind.server --db world.sqlite3 --llm-disabled
# or: ./scripts/run.sh --llm-disabled --db world.sqlite3
```

- `--ctx-size 3072` matches `Config.llm_num_ctx` — the KV-cache size
  llama.cpp allocates up front regardless of how full a given prompt
  is. Raised from an earlier 1280 once GPU offload was confirmed
  working, then re-lowered from an initial 4096 once a live `htop`
  reading showed only ~6.5GB usable RAM rather than the full 8GB
  nominal (see `Config.llm_num_ctx`'s docstring) — on CPU-only 8GB
  hardware, use `LLAMA_CTX_SIZE=1280` (or the manual `--ctx-size 1280`)
  instead, see the 8GB section below.
- `--parallel 1` — one KV-cache slot; safe against `Config.llm_max_
  concurrent=2` (a second in-flight request just waits its turn).
- `--cache-type-k/-v q8_0` — 8-bit KV cache, ~half the memory of the f16
  default, free either way.
- `--no-mmproj` — explicitly disables multimodal/vision (mmproj)
  loading. Hearthmind never sends images, so this is free memory back
  with zero functionality lost.
- `--n-gpu-layers 999` — offload every layer the backend can fit.
  Confirmed working on real hardware; use `0` to force CPU-only.
- `--threads $(nproc)` — every CPU core for whatever inference work
  stays on CPU ("maximize CPU, minimize memory": the tick loop itself
  is nowhere near CPU-bound, ~1ms against a 1000ms budget, so idle
  cores should go to the one thing that takes real wall-clock time).
- `--port 8080` — matches `Config.llm_llamacpp_host` default.

### AMD Ryzen iGPU offload (Radeon 740M / 780M, Vulkan)

**Confirmed working** — GPU offload via llama.cpp's Vulkan backend is
the real thing on this hardware, noticeably better than CPU-only
inference. Ollama's bundled ROCm build didn't recognize this hardware
(gfx1103) by default; llama.cpp's Vulkan backend sidesteps that since it
doesn't depend on ROCm's own hardware allowlist.

```bash
# Vulkan SDK + loader must be installed first (distro package, e.g.
# `vulkan-tools mesa-vulkan-drivers` on Debian/Ubuntu with Mesa's RADV
# driver, which supports RDNA2/RDNA3 iGPUs including the 740M/780M).
vulkaninfo --summary   # confirm the iGPU is visible to Vulkan before building

cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j$(nproc) --target llama-server

./build/bin/llama-server \
  --model /path/to/Qwen3-4B-Instruct-Q4_K_M.gguf \
  --ctx-size 3072 --parallel 1 --cache-type-k q8_0 --cache-type-v q8_0 \
  --no-mmproj --port 8080 \
  --n-gpu-layers 999 --threads $(nproc)

# then, in another terminal (or LLAMA_SERVER_BIN=... ./scripts/run.sh):
python -m hearthmind.server --db world.sqlite3 --llm-llamacpp-host http://localhost:8080
```

`Config.llm_num_gpu` (Ollama's own GPU-layer option) has no llama.cpp
equivalent needed here since `--n-gpu-layers` is a server launch flag,
not a per-request one — set it once at server startup (or via
`LLAMA_N_GPU_LAYERS` for `scripts/run.sh`, defaults to GPU-on now — see
the script's header comment). iGPU memory is shared
with system RAM on this hardware, so offloading doesn't free up RAM the
way a discrete GPU would — it mainly trades CPU time for GPU time,
which still helps the "maximize CPU, minimize memory" goal indirectly
(faster calls finish sooner, shortening how long the KV cache stays
allocated) and, confirmed on real hardware, meaningfully speeds up
inference itself. `Config.llm_num_ctx`/`llm_num_predict`/
`llm_core_cast_size` were all raised in the v0.72.3 pass on the strength
of this confirmation — see their docstrings in `config.py`.

### ⚠️ Running on 8GB RAM — stop the LLM server from swapping (read this first)

If the LLM server is pushing your machine into swap, **the fix is
almost entirely server configuration, not this app.** On an 8GB box the
memory it holds resident is dominated by two things — the model
**weights** (loaded once, resident while the model is warm) and the
**KV cache**, whose size is `ctx_size × parallel_slots × bytes_per_
element`. That KV cache is allocated *up front at the full context
size*, regardless of how short the actual prompts are. **Reducing how
often Hearthmind calls the model does not shrink it** (the v0.70.0
core-cast fix cut call *volume*, which matters for sustained CPU load,
but resident weights + KV cache sit there while the model is warm no
matter how rarely you call it).

**Note (v0.72.4, corrected from v0.72.3):** the defaults documented
elsewhere in this README (`--ctx-size 3072`, `--n-gpu-layers 999`)
assume GPU offload is working — confirmed on real hardware to be a
real, meaningful improvement — but were revised down from an initial
v0.72.3 pass (`--ctx-size 4096`, `llm_core_cast_size=18`,
`llm_max_calls_per_day=400`) once a live `htop` reading on that same
hardware showed only ~6.5GB usable RAM, not the full 8GB nominal;
GPU offload moves weights/KV predominantly into VRAM, but llama-server,
its mmap'd model file, and hearthmind itself still compete for whatever
system RAM is actually free. If you're on CPU-only 8GB (or GPU offload
isn't set up yet), use the tighter recipe below instead — these are no
longer the project's defaults, but every lever still works exactly the
same way:

```bash
LLAMA_CTX_SIZE=1280 LLAMA_N_GPU_LAYERS=0 \
  MODEL_PATH=/path/to/Qwen3-4B-Instruct-Q4_K_M.gguf ./scripts/run.sh --db world.sqlite3 \
  --llm-num-ctx 1280 --llm-core-cast-size 8
```

`--ctx-size 1280`/`--parallel 1`/`--cache-type-k/-v q8_0` together are
roughly an **8×** smaller KV cache than an untuned launch (`--ctx-size
2048+ --parallel 4`, f16 cache, no GPU offload). If it still swaps, size
the model down (next section) before touching anything else. Pass
`--llm-num-ctx 1280`/`--llm-num-predict 384` to `hearthmind.server` (or
`scripts/run.sh`, which forwards them) to keep the app-side prompt
budget in step with a lowered `--ctx-size` — raising one without the
other either wastes the smaller KV cache or risks truncating a prompt.

**If it still swaps — size the model down.** The model weights are the
other big resident chunk (~2.6GB for `qwen3:4b-instruct` at Q4_K_M). A
smaller quant roughly halves that — search Hugging Face for a
`Qwen3-1.7B` GGUF (~1.4GB at Q4_K_M) and point `--model` at it (llama.cpp)
or run `ollama pull qwen3:1.7b` + `--llm-model qwen3:1.7b` (Ollama
backend). `qwen3:1.7b` is a hybrid "thinking" model — both clients'
`<think>`-stripping handles this correctly, so it behaves like an
instruct model in practice. Town-brain/dialogue prose will be a little
less polished than 4B; that's the trade for headroom. You can also
shrink the LLM-driven cast with `--llm-core-cast-size 8` (fewer deep
NPCs, fewer concurrent-ish calls), though the launch flags + model size
are the levers that actually move resident memory.

**Confirm what's actually resident** while a run is live:

```bash
ps aux | grep llama-server            # RSS of the actual llama.cpp process
# or, from the running Hearthmind server, the attributed breakdown:
curl -s localhost:8765/diagnostics | python3 -m json.tool | grep -A20 system_memory
```

`/diagnostics.system_memory` reports this process's RSS/swap and the
LLM server process's RSS/swap separately (matches on `ollama`,
`llama-server`, `llama-cli`, or `llama.cpp` in the process name — same
report either backend) so you can see exactly where the memory is going
before changing anything.

### Model choice history

The default model tag, `qwen3:4b-instruct`, was set in v0.65.2 per a
live user report on real 8GB hardware: `qwen3.5:2b` (not a real
released Qwen tag) showed memory-leak-like growth and swapping, while
the larger, official `qwen3:4b-instruct` stayed under 4.5GB with no
swapping — counter-intuitive on paper, but this project trusts a live
environment report over training-data assumptions about model
naming/behavior. If `system_memory` still shows pressure on
`qwen3:4b-instruct` after every server-side lever above, try
`qwen3:1.7b` before going smaller (`qwen3:0.6b` exists but noticeably
degrades multi-field JSON decisions like town-brain/disputes/beliefs —
last resort only). Dialogue quality is the output most sensitive to
model size (`_is_sane_line`'s leakage/length rejection fires more on
weaker models) — see `docs/DECISIONS.md` for the full v0.65.2/v0.66.0
narrative if you're deciding whether to size down. Report back what you
observe rather than silently switching, same standing policy as always.

### Alternative: Ollama backend

Still fully supported for anyone with an existing Ollama setup — pass
`--llm-backend ollama` (or `Config.llm_backend="ollama"`):

```bash
# 1. Install and start Ollama (see https://ollama.com), then pull a model:
ollama pull qwen3:4b-instruct

# 2. Run with the Ollama backend explicitly:
python3 -m hearthmind.server --db world.sqlite3 --llm-backend ollama
```

Every Ollama-specific memory lever from earlier releases still applies
and is unchanged — set these before `ollama serve`:

```bash
export OLLAMA_NUM_PARALLEL=1        # ONE KV-cache slot, not the default of 4
export OLLAMA_KV_CACHE_TYPE=q8_0    # 8-bit KV cache: ~half the KV memory
export OLLAMA_FLASH_ATTENTION=1     # required for q8_0 KV; set both together
export OLLAMA_MAX_LOADED_MODELS=1   # never hold two models resident at once
export OLLAMA_KEEP_ALIVE=3m         # release the model during real lulls
ollama serve
```

`--llm-num-thread` (default `os.cpu_count()`) still applies to the
Ollama backend the same way it always did — points Ollama at every
available core for a single call so it finishes faster, shortening the
window its KV-cache allocation holds memory, without adding a second
call's worth of concurrent KV cache the way raising
`--llm-max-concurrent` would.

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
