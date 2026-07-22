"""Tunable parameters for a Hearthmind world.

Kept as a single flat dataclass so every knob lives in one place. Only the
fields marked "creation-only" matter after a world has been created — things
like `width`/`height`/`seed` are baked into the saved world on first run and
are ignored (with a warning) on subsequent resumes from the same database.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # --- creation-only: baked into the world the first time it's created ---
    seed: int | None = 1337
    """`None` is only meaningful coming from the CLI (`--seed` omitted):
    it tells `server.py` to run a one-time "genesis" LLM call and derive
    the seed from its answer instead of using a fixed default — see
    `hearthmind.llm.world_genesis`. Anything constructing a `Config`
    directly (tests, ad-hoc scripts, the dataclass default itself) gets
    a concrete int and never has to think about this."""
    width: int = 64
    height: int = 64

    # --- creation-only: calendar shape is baked in at world creation.
    # `sim_minutes_per_tick` belongs here, NOT in the runtime section below:
    # total_sim_minutes = tick_count * sim_minutes_per_tick, so changing it
    # between runs would retroactively change what every past tick meant
    # (e.g. tick 30 was "5 days in" at 240 min/tick; reinterpreted at 15
    # min/tick it becomes "7.5 hours in"). It must stay fixed for the life
    # of a world, exactly like `seed` or `minutes_per_day`.
    sim_minutes_per_tick: int = 15
    """Sim-minutes the world clock advances per tick. Fixed at creation."""

    minutes_per_day: int = 24 * 60

    days_per_month: tuple[int, ...] = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    """A real 12-month, 365-day calendar (no leap years — not worth the
    complexity for a simulated town). Legacy-snapshot compatibility with
    the old fixed-20-day, 4-season calendar was deliberately dropped
    (explicit user instruction) — every snapshot is expected to carry
    this field."""
    month_names: tuple[str, ...] = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    seasons_per_year: tuple[str, ...] = ("spring", "summer", "autumn", "winter")
    month_to_season: tuple[int, ...] = (3, 3, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3)
    """Index into `seasons_per_year` for each month (UK meteorological
    seasons: Dec-Feb winter, Mar-May spring, Jun-Aug summer, Sep-Nov
    autumn) — `season`/`season_index` stay a 4-value concept for every
    consumer that already keys off them (weather baselines, farm growth
    multipliers, festival/chronicle/tradition/invention/town-brain
    cadence), while the calendar underneath is now a real 12-month
    year."""

    start_day_of_year: int = 59
    """Which day of the calendar year tick 0 falls on — day 59 is
    March 1, the start of meteorological spring. Worlds previously began
    on January 1, i.e. in deep winter (resource regen x0.3, farm growth
    x0.35, harsh-weather need multipliers) with twelve strangers
    scattered across the map and no infrastructure — the July 2026
    architecture review measured nearly every early starvation death in
    that window, and the outcome was bimodal: survive the funnel or
    demographically dead-end. A spring start gives a founding
    population the same first season a real settlement expedition would
    choose. Creation-only, like the rest of the calendar shape: loaded
    worlds keep the offset they were created with (0 for older
    snapshots, so their history doesn't shift underfoot)."""

    # --- creation-only: how many inhabitants a brand-new world starts with.
    # Only consulted the first time a world is created at a given --db path;
    # changing it on an existing world has no effect (agents don't spawn or
    # despawn on config change, only through in-world events).
    initial_population: int = 12

    # --- runtime: safe to change between runs, doesn't affect calendar math ---
    tick_seconds: float = 1.0
    """Real seconds of wall-clock time between ticks (controls pacing only)."""

    snapshot_every_ticks: int = 60
    """How often (in ticks) to persist a full snapshot."""

    event_log_retention: int = 200_000
    """Most-recent rows kept in the `events` table; older rows are pruned
    on the snapshot cadence (`snapshot.save_snapshot` → `_prune_events`).
    v0.71.0 memory-audit pass: `events` was the one genuinely unbounded-
    growth table on a persistent, always-running world (snapshots already
    prune to recent + keyframes; metrics grow only ~1 row/sim-day), at
    ~1-2 rows/tick sustained → an indefinite run grew the DB file without
    limit. 200k rows is many months of the *notable* history the UI's
    History tab surfaces (the live feed and History both read only the
    newest tail — 50 and 200 rows — and deep world-state history is
    preserved by snapshot keyframes), while bounding the DB to tens of
    MB. Raise it if you have disk and want a longer raw event log; 0
    disables event pruning entirely (unbounded, opt-in)."""

    metrics_log_retention: int = 20_000
    """Most-recent rows kept in the `metrics` table, pruned on the same
    snapshot-cadence transaction as `event_log_retention`. Left unpruned
    from v0.71.0 through v0.78.1 on the reasoning that ~1 row/sim-day
    makes it "slow" growth, with an explicit note to "revisit only for
    multi-year sim runs" — a live user report of a game meant to run
    stably for years is exactly that condition. 20k rows is ~55 years of
    daily metrics (far beyond any realistic session) while giving the
    table the same hard ceiling `events`/`snapshots` already have, so
    "runs forever" no longer has a silent exception. `GET /metrics`
    (the `/metrics` chart) already reads only the newest 365 rows by
    default, so this is lossless for every actual reader. 0 disables
    pruning (unbounded, opt-in), same convention as `event_log_
    retention`."""

    consciousness_log_retention: int = 5_000
    """Most-recent rows kept in the `consciousness_log` table (v0.86.2,
    Engineering Constitution §6), pruned on the same snapshot-cadence
    transaction as `event_log_retention`/`metrics_log_retention`. This
    is the durable record behind `World.consciousness_memory`/
    `consciousness_player_model`/`consciousness_objectives`/
    `consciousness_intervention_log`, which stay small (capped 16/6/2/12)
    for prompt-building and snapshot size — without this table, every
    entry past those caps was silently and permanently forgotten. The
    consciousness job fires at most once/month, so 5,000 rows across all
    four kinds is centuries of real headroom; 0 disables pruning
    (unbounded, opt-in), same convention as `event_log_retention`."""

    agent_memory_log_retention: int = 100_000
    """Most-recent rows kept in `agent_memory_log` GLOBALLY (v0.86.3,
    Engineering Constitution §6), pruned on the same snapshot-cadence
    transaction as the other log tables. Higher than `consciousness_log_
    retention` since this is population-wide (every core-cast-eligible
    agent's significant episodic memories + every semantic-memory write,
    not one world-scoped monthly job) — still a real, predictable
    ceiling regardless of population size, matching "memory bounded."
    0 disables pruning (unbounded, opt-in), same convention as the other
    retention knobs."""

    db_path: str = "world.sqlite3"

    # --- runtime: LLM (Ollama) cognition layer, off by default -----------------
    llm_enabled: bool = True
    """On by default as of E2: cognition, chronicle, culture, and
    NPC-to-NPC dialogue are the primary emergence levers, so a bare
    `Config()` should exercise them. Every LLM call still degrades to a
    deterministic fallback if Ollama isn't reachable — turning this off
    is only needed for a fully offline/deterministic run (e.g. a fast
    local smoke test). See docs/DECISIONS.md, E2."""

    llm_backend: str = "llamacpp"
    """Which local LLM server this project talks to: `"llamacpp"`
    (default, v0.72.0) or `"ollama"`. Switched the default from Ollama to
    llama.cpp's own `llama-server` for the same reason documented in the
    earlier "llama.cpp migration" evaluation (docs/DECISIONS.md) that had
    previously declined this move: Ollama's runner *is* llama.cpp under
    the hood, so the model-memory math (weights + KV cache) is identical
    either way — but Ollama adds its own management daemon on top
    (~100-300MB baseline RSS) and its own opinions about mmap/
    keep_alive/OLLAMA_NUM_PARALLEL that this project has spent several
    releases fighting through per-request options and README env-var
    workarounds (see llm_num_ctx's docstring). Talking to `llama-server`
    directly removes that whole layer and exposes context size, KV-cache
    quantization, thread count, and GPU layer count as direct process
    launch flags instead of environment variables this project can't set
    on the user's behalf. `OllamaClient` (hearthmind/llm/client.py) is
    unchanged and fully supported via `llm_backend="ollama"` for anyone
    with an existing setup. See README, "Running the LLM (llama.cpp)"."""
    llm_host: str = "http://localhost:11434"
    """Ollama server URL — only consulted when `llm_backend="ollama"`."""
    llm_llamacpp_host: str = "http://localhost:8080"
    """`llama-server` URL — only consulted when `llm_backend="llamacpp"`
    (the default). 8080 is `llama-server`'s own default port."""
    llm_restart_sentinel_path: str | None = None
    """Path to a file `scripts/run.sh`'s `LLAMA_RESTART_HOURS` supervisor
    touches right before killing the old `llama-server` process and
    removes once the replacement answers `/health` (v0.87.3). `None`
    (the default — set only when `run.sh` launches with
    `LLAMA_RESTART_HOURS>0`) means the check is skipped entirely, zero
    added cost. When set, `SimulationEngine.run_forever` polls the
    file's existence the same way it already polls `llm_pressure_
    paused()` — a restarting llama-server pauses ticking outright
    (same `PAUSED_POLL_SECONDS` cadence) rather than relying on every
    in-flight LLM call individually timing out/falling back during the
    ~1-10s restart window. Two separate processes (this bash script and
    `hearthmind.server`) with no shared memory, so a plain file's
    existence is the simplest correct signal — matches this project's
    stdlib-first, no-new-dependency posture."""
    llm_model: str = "nemotron-3-nano-4b"
    """Changed from `gemma-4-e4b-it` per explicit user directive
    ("optimize all the prompts and parser to work with Nemotron 3 Nano
    4B") — NVIDIA's small unified reasoning/non-reasoning model. Unlike
    Gemma's `-it` (non-thinking by design, the earlier default), Nemotron
    3 is genuinely hybrid-thinking: its `<think>` chain-of-thought is
    controlled purely by an exact system-prompt phrase ("detailed
    thinking on"/"detailed thinking off", NOT an API field), which is
    where this is now load-bearing rather than a defensive no-op — see
    `llm/client.py`'s `_REASONING_OFF_PROMPT`/`_REASONING_ON_PROMPT` and
    `generate_json`'s new `reasoning` param. Every prior model-default
    change in this project follows "the actual deployed model becomes
    the code default, report real numbers if a size-down is needed" —
    `gemma-4-e4b-it` (the prior default) remains documented in
    CHANGELOG.md/git history for anyone still running that family."""
    llm_adapter_name: str | None = None
    """FT.7 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap): "Version
    the adapter in the diagnostics block next to `llm_model` so every
    archived example knows which model generation produced it." `None`
    (the default — no fine-tuned adapter has ever actually been trained
    against this project, see FT.6's docstring in the audit doc) means
    every call is running the bare base model named by `llm_model`.
    Once a real LoRA/QLoRA adapter exists and `llama-server` is
    launched with it loaded, set this to the adapter's own name/version
    string (e.g. `hearthmind-lora-v1`) — it's threaded into every new
    training-archive example's `dataset.adapter_name` field (`llm/
    recorder.py`) and into `/diagnostics`, so a future review pass can
    tell which examples were generated by which model generation
    without cross-referencing session tags by hand. Purely a label —
    changing it does not itself load or swap any adapter; that's a
    `llama-server` launch-flag concern (see FT.6's "runtime-adapter"
    note), this just keeps the archive honest about what was running."""
    llm_timeout_seconds: float = 120.0
    """A live diagnostic report on the user's own hardware running
    `qwen3.5:2b` showed p50 latency 17.4s, p95 19.7s, max 29.7s against
    the previous 30s default — a wafer-thin margin (a single call at
    29.7s is one slow token away from a spurious fallback) despite the
    model itself working correctly (0% fallback rate observed). Bumped
    30 -> 45 for real headroom, not because the model is failing.
    Counterintuitively, a smaller model isn't necessarily faster in
    wall-clock terms on constrained CPU hardware — every call still has
    a deterministic fallback (hearthmind/llm/jobs.py), so this only
    trades a longer worst-case wait for a lower fallback rate. Bumped
    again 45 -> 60 (v0.43.1) alongside dropping `llm_max_concurrent` to 1:
    a single-lane queue means a job now waits for a slot behind whatever
    is already running (the 45s measurements above were single-call
    latency with no queueing) — that per-call clock still only starts
    once the job actually begins running (see `CognitionRunner._run_
    gated`, timer starts inside the semaphore), so this isn't strictly
    required for correctness, but it buys real margin against the
    now-serialized worst case at negligible liveness cost (every call
    still has an instant deterministic fallback either way). **Raised
    60 -> 120 in v0.81.0**: a live diagnostic (population 231, `qwen3:
    4b-instruct`) measured p50/p95/max call latency of 31.8s/69.8s/
    101.9s — already brushing the old 60s ceiling (`CognitionRunner`
    adds a further +5s defense-in-depth margin on top, see `_run_gated`)
    with zero measured timeouts, meaning some legitimately-slow-but-
    successful calls were one bad tick away from a spurious fallback.
    Raising `llm_max_concurrent` 1 -> 2 in the same pass (see its own
    docstring) makes this more likely, not less: two calls can now
    genuinely overlap CPU/GPU work on the same hardware, slowing both.
    120s keeps real margin over the observed max without materially
    changing the liveness contract (every call still resolves to its
    deterministic fallback the instant it fails or times out; this only
    changes how long a *slow-but-working* call gets before being judged
    a failure). See docs/DECISIONS.md, "dialogue quality follow-up"
    (qwen3.5:2b diagnostics), and D5 for the original version of this
    rationale."""
    llm_temperature: float = 0.7
    """Sampling temperature sent with every LLM call (both backends,
    v0.75.2). Previously unset, so each call used the server's own default
    (llama-server/Ollama both ~0.8) — pinning it makes generation
    behaviour a visible, tunable config value instead of a silent server
    default, the same reason `llm_num_ctx`/`llm_num_predict` are pinned.
    0.7 is a mild step down from ~0.8 toward coherence: every prompt here
    wants one short, grounded, strict-JSON answer, not creative variety,
    and lower temperature measurably reduces the rambling/off-shape output
    small models (the 4B default) produce under a JSON constraint —
    directly targeting live-reported "garbled / off-topic" NPC dialogue.
    Lower it further (0.5-0.6) if a small model still wanders; raise
    toward 0.9 for more variety on a stronger model. Kept above 0 so a
    stuck pair doesn't get the identical deterministic-looking line every
    time."""
    llm_max_concurrent: int = 1
    """How many LLM requests may be in flight at once. History: 4 (E2) ->
    2 (v0.43.0) -> 1 (v0.43.1) -> 2 (v0.44.0, the "permanent floor") ->
    1 (v0.78.5, "make concurrent task = 1 if it reduces memory
    pressure" — it did, at the time: `scripts/run.sh` hardcoded
    llama-server's own `--parallel 1`, so a second Python-side in-flight
    request was pure dead weight, and the measured memory picture then
    (2GB of llama-server swap at population 301/13k ticks) genuinely
    justified trading concurrency for headroom) -> 2 (v0.81.0, per a
    live diagnostic showing that swap crisis resolved and the live
    symptom shifted to single-lane-queue throughput instead) -> 3
    (v0.87.6, per explicit user direction that `LLAMA_CACHE_RAM=0`
    (v0.87.5) resolved the swap pressure that had driven every prior
    pull-back — a **directed increase pending live re-verification**,
    not itself a fresh measurement). **Re-lowered 3 -> 2 (docs/AUDIT-
    2026-07-20.md, P1.2)**: that re-verification landed — a live
    session's `llama_server_metrics` measured `n_busy_slots_per_decode`
    2.58 against 3 configured slots, meaning the third slot mostly adds
    contention rather than real throughput (matches this project's own
    earlier v0.39 review finding that 2 streams at ~2x speed beat 3-4
    at ~3-4x latency), and end-to-end p95 was ~38s/decision at that
    concurrency. **Re-lowered again, 2 -> 1, in v1.3.15** (explicit
    user follow-up to the v1.3.14 latency-tuning pass, "try llm_max_
    concurrent = 1"): the diagnostic that pass acted on showed
    `n_busy_slots_per_decode` 1.88 against 2 configured slots on a
    compute-bound model predicting at only ~2.6 tok/s — the same
    "slot count exceeds what the hardware can actually run in
    parallel" shape the 3->2 re-tune found, one notch further down a
    slower/larger model. On genuinely compute-bound hardware two
    concurrent decode streams don't run twice as fast, they each run
    at roughly half speed while still occupying two KV-cache slots —
    serializing to one lane means each individual call finishes in
    closer to its true solo-latency time, directly relieving the
    47-100s call latencies and the queue-wait pileup (`queue_wait_ms_
    p50` 30s) the v1.3.14 diagnostic showed, at the cost of never
    genuinely overlapping two calls. `scripts/run.sh`'s `--parallel`
    is `LLAMA_PARALLEL` (now default 1, matching this), with `LLAMA_
    CTX_SIZE` sized as `llm_num_ctx * llm_max_concurrent` unchanged
    (one slot now gets the full shared `--ctx-size` to itself, which
    was previously split across `LLAMA_PARALLEL`'s slots). Raise back
    toward 2 if a future fast-model diagnostic shows `n_busy_slots_
    per_decode` sitting comfortably near its configured slot count
    (real parallel headroom, not contention) — this is a re-tune from
    live measurement, not a new permanent floor, same discipline every
    prior move on this constant followed. See docs/DECISIONS.md, "LLM
    concurrency: 1 -> 2 (v0.81.0)" and CHANGELOG.md v0.87.6/v1.3.14."""
    llm_num_ctx: int = 3072
    """Explicit context-window cap sent with every Ollama request (and
    documented as the `--ctx-size` llama-server launch flag for the
    llama.cpp backend — see README). **This is the single most important
    memory knob this code controls**: the KV cache is allocated up front
    at `num_ctx` tokens regardless of how full any given prompt actually
    is. Raised 1280 -> 4096 in the v0.72.3 "GPU offload confirmed
    working" pass on the assumption that GPU offload removes system-RAM
    pressure entirely; re-lowered 4096 -> 3072 in v0.72.4 once the user
    reported actual usable RAM (per `htop`) is only ~6.5GB, not the full
    8GB nominal. **Re-lowered again, 3072 -> 2560, in v0.78.1**: a live
    `/diagnostics.system_memory` report from a real long-running game
    (301 population, 13,094 ticks) showed `llama-server`'s own process
    at only 121MB RSS but **2048MB in swap** — the fixed KV-cache/
    compute-buffer allocation `num_ctx` reserves up front sits mostly
    cold and gets swapped out once system-wide memory pressure builds
    over a long session (`mem_available` had fallen to 174MB of 7046MB
    total) — while this process's own RSS stayed a flat, clean 57.9MB,
    reconfirming the standing "swap pressure is always Ollama/llama-
    server-side" lesson yet again. GPU offload moves weights predominantly
    into VRAM, but the KV cache/compute buffers this setting sizes still
    draw from system RAM (more so on a shared-memory iGPU, where "VRAM"
    itself is carved from the same pool — see `LLAMA_FIT_TARGET` in
    scripts/run.sh for the lever that trades a little offload for more
    system-RAM headroom on that hardware). 2560 keeps real margin over
    the CPU-only-tuned 1280 floor while giving a long-running large-
    population world less fixed allocation to have swapped out from
    under it. **Raised 2560 -> 3072 in v0.87.6**, a directed partial
    restore per explicit user direction now that `LLAMA_CACHE_RAM=0`
    (v0.87.5) has reportedly resolved the swap pressure this knob was
    twice pulled back for — see `llm_max_concurrent`'s docstring for the
    full reasoning (that flag's 8GB stock default plausibly explains
    more of the historical swap than this KV-cache sizing). Deliberately
    NOT restored all the way to the v0.72.3 4096 peak — a partial,
    verifiable step. Lower toward 1280 for CPU-only or genuinely tight
    8GB hardware (see README's 8GB section); this is a directed
    increase pending live re-verification, not a fresh measurement —
    report back a `/diagnostics.system_memory` + `llama_server_metrics`
    (v0.87.6) reading after adopting it."""
    llm_num_predict: int = 512
    """Explicit cap on generated tokens per call. Every response here is a
    short, strict-JSON answer (a goal, a line of dialogue, a settlement
    decision) — this bounds the worst case where the model rambles
    instead of terminating cleanly, which otherwise burns memory (the
    generated tokens also occupy the KV cache), the `llm_timeout_seconds`
    budget, and would be rejected by the JSON parse anyway. Raised
    384 -> 640 in the v0.72.3 GPU-offload pass, re-lowered 640 -> 512 in
    v0.72.4, and re-lowered again 512 -> 448 in v0.78.1 alongside
    `llm_num_ctx`'s same live-diagnostics-driven pull-back (a real
    301-population/13k-tick game showed 2GB of llama-server swap even
    at the v0.72.4 settings). **Raised 448 -> 512 in v0.87.6**, the same
    directed partial restore as `llm_num_ctx` — see its docstring and
    `llm_max_concurrent`'s. Counts against `llm_num_ctx`'s budget, so
    keep the two in step."""
    llm_keep_alive: str = "3m"
    """How long Ollama keeps the model resident in memory after the last
    call before unloading it (v0.43.1) — previously never sent, so the
    server's own default governed this, which on some Ollama versions is
    5 minutes and on others is "keep loaded forever" (`-1`). On an idle
    settlement (few LLM-eligible events, sparse cognition triggers) an
    indefinite keep-alive means the model's resident weights + whatever
    KV-cache Ollama retains sit in memory the entire session even during
    long quiet stretches. 3 minutes is short enough to actually release
    memory during a real lull, long enough that the sim's own cadence
    (multiple settlement-level jobs per in-game day, routine per-agent
    cognition/dialogue) keeps the model loaded through normal activity
    without constantly paying reload latency. Sent as Ollama's top-level
    `keep_alive` field alongside `options` on every call."""
    llm_use_mmap: bool = True
    """Explicit `use_mmap: true` sent in every call's `options` (v0.55.0).
    A live diagnostic (`ollama ps` + `ps aux`) on the user's own 8GB
    machine found the actual `llama-server` runner process resident at
    5.1GB RSS — over 2x the 2.4GB `ollama ps` reports as "loaded" — with
    `--no-mmap` on its command line. Without mmap, model weights are
    pulled into private anonymous memory the kernel can only reclaim by
    writing to swap under pressure; with mmap, weight pages are
    file-backed and the kernel can just drop and re-read them from disk
    instead, which is a categorically cheaper way to relieve memory
    pressure than swapping. Previously never sent, so whatever caused
    the server to launch with `--no-mmap` (an `OLLAMA_NOMMAP` env var, or
    Ollama's own low-RAM heuristic) went unchallenged by this project's
    own requests. `True` unconditionally — this project has no scenario
    where forcing anonymous-memory residency is preferable to letting
    the kernel manage weight pages as reclaimable file-backed memory."""
    llm_num_gpu: int | None = None
    """Explicit `num_gpu` sent in every call's `options` when set — how
    many model layers Ollama offloads to a detected GPU. `None` (the
    default) omits it entirely, leaving Ollama's own GPU-layer heuristic
    in charge, same "don't touch it unless there's a reason to" stance
    as every optional `OllamaClient` field before it (`num_ctx`/
    `num_predict` are the exception because they're safety ceilings, not
    heuristics to defer to). This is a genuinely no-op field until the
    user's Ollama server actually recognizes a GPU (see docs/DECISIONS.md,
    "iGPU offload investigation" — the user's AMD Radeon 740M iGPU
    (gfx1103) wasn't being used despite `rocminfo` detecting it, most
    likely because Ollama's bundled ROCm build doesn't include gfx1103
    by default) — set it once GPU acceleration is confirmed working, if
    Ollama's own auto-detected layer count ever needs overriding."""
    llm_num_thread: int | None = None
    """Explicit `num_thread` sent in every call's `options` when set —
    how many CPU threads Ollama devotes to a single inference call.
    `None` leaves Ollama's own (often conservative, on CPU-only
    hardware) thread heuristic in charge. This is the "maximize CPU,
    minimize memory" lever this project had been missing: the tick
    loop itself is nowhere near CPU-bound (~1ms against a 1000ms
    budget — see docs/DECISIONS.md's C/C++-port evaluation), so idle
    cores sit unused while the one thing that actually takes real
    wall-clock time, an Ollama call, runs on however many threads
    Ollama's heuristic picked. Pointing this at the machine's full
    core count finishes each call faster, which shortens the window
    its KV-cache allocation holds memory — WITHOUT adding a second
    call's worth of concurrent KV cache the way raising
    `llm_max_concurrent` would (that floor is untouched). `server.py`
    defaults `--llm-num-thread` to `os.cpu_count()` rather than
    leaving it unset, since "use every core available" is the right
    default for a dedicated box running one Ollama instance for one
    simulation."""
    llm_core_cast_size: int = 18
    """How many NPCs are the LLM-driven "core cast" (v0.70.0). Only these
    agents get LLM cognition (goal reasoning), and only a *pair* of them
    gets LLM-authored dialogue — every other agent, and every mixed/
    crowd pair, runs on the already-real deterministic fallback. This is
    the load-bearing fix for the measured "swap climbs after a few
    hours" report: total Ollama call volume used to scale linearly with
    population (one cognition call per agent per sim-day, up to
    MAX_DIALOGUES_PER_TICK dialogues per tick), so a town that grows from
    12 to hundreds over a few real hours drives Ollama from lightly
    loaded to continuously saturated, and sustained saturation is what
    lets Ollama's own per-call memory growth accumulate into swap on 8GB.
    Pinning the LLM-eligible set to a fixed cast decouples call volume
    from town size entirely. Also a *design* win, not just a perf hack:
    the core cast are the persistent protagonists whose inner lives and
    conversations are model-authored, while the crowd is deterministic
    texture — directly serves the "persistent identity" priority. The
    cast is seeded from the founders, sticky (a member stays until
    death), and refilled from the most-prominent living non-member when
    a seat opens (see Population.maintain_core_cast). 0 disables LLM
    cognition/dialogue entirely (settlement-level jobs still run).
    Raised 11 -> 18 in the v0.72.3 GPU-offload pass, then **re-lowered
    18 -> 14 in v0.72.4** once the user's live `htop` reading showed only
    ~6.5GB usable RAM rather than the full 8GB v0.72.3 assumed: GPU
    inference genuinely cuts per-call wall-clock time (the root reason a
    larger cast is affordable at all), but a bigger cast still means more
    concurrent conversational/cognition state and more frequent calls,
    so 18 was sized against headroom this specific machine doesn't have.
    14 kept a real gain over the original 11 without assuming that
    headroom. **Raised 14 -> 18 again in v0.87.6**, a directed restore
    of the original v0.72.3 value per explicit user direction — see
    `llm_max_concurrent`'s docstring for the full `LLAMA_CACHE_RAM=0`
    reasoning. `llm_max_calls_per_day` scales with this (see below);
    re-lower both together if a live `system_memory`/latency reading
    ever shows pressure again."""
    llm_max_calls_per_day: int = 480
    """Belt-and-braces hard ceiling on total Ollama calls per sim-day
    (v0.70.0) — cognition, dialogue, AND settlement-level jobs all count
    against it; once hit, every further LLM decision that day resolves
    via its deterministic fallback until the counter resets at day_end.
    The core cast (`llm_core_cast_size`) is the primary volume limiter
    and already keeps calls well under this; this ceiling exists so that
    even a future bug in cast selection or a new per-agent LLM job can
    never re-create the unbounded-throughput condition that caused the
    swap. Raised 200 -> 400 alongside the v0.72.3 core-cast-size bump
    (11 -> 18), re-lowered 400 -> 320 in v0.72.4 alongside the core-cast
    re-lowering (18 -> 14). **Raised 320 -> 480 in v0.87.6**, alongside
    `llm_core_cast_size`'s 14 -> 18 restore and `llm_max_concurrent`'s
    2 -> 3 raise (a bigger cast at higher concurrency both push more
    real volume through) — see `llm_max_concurrent`'s docstring for the
    `LLAMA_CACHE_RAM=0` reasoning behind this whole directed batch. This
    is a **directed increase pending live re-verification**, not a
    fresh measurement — report back `/diagnostics.llm_prompt_stats` +
    `llama_server_metrics` volume/latency after adopting it; lower all
    three together if a live reading ever shows pressure. See
    docs/DECISIONS.md, "core cast + daily LLM ceiling" pass, and
    CHANGELOG.md v0.87.6."""

    # --- runtime: Phase G (subtle supernatural layer), on by default -----------
    phase_g_intensity: float = 1.0
    """Scales `Settlement.temperament`'s monthly random-walk step/fortune-
    bias and `llm/omens.py`'s per-month chance — the "config knob to dial
    intensity" the roadmap flagged as not yet built. 1.0 is the original,
    tuned-by-feel default; 0.0 makes temperament hold flat at 0 and skips
    omens entirely (a fully deterministic run with the layer effectively
    off, without deleting the mechanism); values above 1.0 make the
    village's moods/omens more pronounced/frequent. Deliberately still a
    single global multiplier, not per-mechanism knobs — see
    docs/DECISIONS.md, "Phase G intensity + omen subjects" pass."""

    # --- runtime: browser interface (Phase F), on by default -------------------
    api_enabled: bool = True
    """On by default as of the UI/diagnostics pass — the browser window
    is the primary way to actually watch a run. Requires `fastapi`/
    `uvicorn` (see requirements.txt); if they aren't installed,
    server.py catches the ImportError, logs a warning, and continues
    without the API rather than crashing — the simulation itself never
    depends on this. See docs/DECISIONS.md, F1/F2, UI-default pass."""
    api_host: str = "0.0.0.0"
    api_port: int = 8765

    recorder_archive_dir: str = "training_archive"
    """Where the permanent LLM training recorder (llm/recorder.py, §8 —
    docs/IDEAS-2026-07-EMERGENCE.md's LoRA/QLoRA data-collection
    prerequisite) writes its JSONL archive, one subdirectory per LLM
    task. Recording itself is OFF by default and only ever starts via an
    explicit `/recorder/start` call or the browser UI's Recorder panel —
    this path just says WHERE it would write if started; setting it
    doesn't turn recording on."""

    def days_per_year(self) -> int:
        return sum(self.days_per_month)
