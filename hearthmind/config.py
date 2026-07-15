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
    llm_model: str = "qwen3:4b-instruct"
    """Changed from `qwen3.5:2b` in v0.65.2 per a live user report: on
    their real 8GB machine, `qwen3.5:2b` showed memory-leak-like growth
    and swapping over long runs, while `qwen3:4b-instruct` — a *larger*
    model — stayed below 4.5GB with no swapping observed. Counter-
    intuitive on paper (bigger model, less memory) but the project's own
    standing rule is to trust the user's live environment over training-
    data assumptions about model naming/behavior; `qwen3.5:2b` isn't a
    real released Qwen tag, so whatever it resolved to on the user's
    Ollama install was never a known-good quantization the way
    `qwen3:4b-instruct` (an official released tag) is. `-instruct`
    means non-thinking/non-hybrid by design, so `OllamaClient`'s
    `"think": False` + `<think>` stripping becomes a defensive no-op
    for this model rather than a load-bearing setting — left in place
    since it's harmless and keeps the size-down path (below) working if
    a future choice is a hybrid-thinking model again. If this model
    proves too weak or too heavy on other hardware, report back rather
    than silently reverting. See docs/DECISIONS.md, "model default:
    qwen3:4b-instruct (v0.65.2)."""
    llm_timeout_seconds: float = 60.0
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
    still has an instant deterministic fallback either way). See
    docs/DECISIONS.md, "dialogue quality follow-up" (qwen3.5:2b
    diagnostics), and D5 for the original version of this rationale."""
    llm_max_concurrent: int = 2
    """How many LLM requests may be in flight at once. Raised back 1 -> 2
    in v0.44.0 per explicit user instruction: LLM richness is
    non-negotiable — concurrency is not the lever for memory pressure
    beyond this floor, `llm_num_ctx`/`llm_num_predict`/`llm_keep_alive`
    are. History: 4 (E2) -> 2 (v0.43.0, the v0.39.0 architecture review's
    own recommendation) -> 1 (v0.43.1, after the symptom recurred at 2)
    -> back to 2 (v0.44.0). Each in-flight call holds its own KV-cache
    allocation in the *separate* Ollama server process — invisible to
    this process's own RSS, but real system memory pressure all the
    same; 2 is the floor this project will trade for memory headroom.
    Further memory reduction must come from elsewhere (shorter
    `llm_keep_alive`, a smaller/more quantized model, or Python-side
    savings) — see docs/DECISIONS.md, "LLM concurrency floor restored.\""""
    llm_num_ctx: int = 1280
    """Explicit Ollama context-window cap sent with every request.
    **This is the single most important memory knob this code controls**:
    Ollama allocates a KV cache sized at `num_ctx` for *every* parallel
    slot it opens (`OLLAMA_NUM_PARALLEL`), and that allocation is made up
    front at `num_ctx` tokens regardless of how full any given prompt
    actually is. So lowering `num_ctx` cuts resident Ollama memory
    directly and unconditionally. Lowered 2048 -> 1280 in the v0.71.1
    "Ollama is swapping" pass after *measuring* the real prompts: the
    largest (the monthly chronicle, with PROMPT_RECENT_EVENTS recent
    events + culture) is ~620 input tokens, and `num_predict` (384) bounds
    the generation, so the worst-case peak is ~1000 tokens — 1280 leaves
    a safe ~280-token margin while shrinking the KV cache ~37% vs 2048.
    Do NOT raise this without re-measuring prompts (undersizing silently
    truncates a prompt and degrades the answer); do lower it further only
    if you also shrink prompts (PROMPT_RECENT_EVENTS). The other big KV
    levers are Ollama-server env vars, not code — see the README's "8GB /
    avoiding swap" section (OLLAMA_NUM_PARALLEL, OLLAMA_KV_CACHE_TYPE,
    OLLAMA_FLASH_ATTENTION)."""
    llm_num_predict: int = 384
    """Explicit cap on generated tokens per call. Every response here is a
    short, strict-JSON answer (a goal, a line of dialogue, a settlement
    decision) — this bounds the worst case where the model rambles
    instead of terminating cleanly, which otherwise burns memory (the
    generated tokens also occupy the KV cache), the `llm_timeout_seconds`
    budget, and would be rejected by the JSON parse anyway. Lowered
    512 -> 384 in the v0.71.1 Ollama-memory pass (no real answer here
    approaches even 384 tokens); counts against `llm_num_ctx`'s budget,
    so keep the two in step."""
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
    llm_core_cast_size: int = 11
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
    cognition/dialogue entirely (settlement-level jobs still run)."""
    llm_max_calls_per_day: int = 200
    """Belt-and-braces hard ceiling on total Ollama calls per sim-day
    (v0.70.0) — cognition, dialogue, AND settlement-level jobs all count
    against it; once hit, every further LLM decision that day resolves
    via its deterministic fallback until the counter resets at day_end.
    The core cast (`llm_core_cast_size`) is the primary volume limiter
    and already keeps calls well under this; this ceiling exists so that
    even a future bug in cast selection or a new per-agent LLM job can
    never re-create the unbounded-throughput condition that caused the
    swap. Sized generously above expected core-cast volume (~11
    cognition/day + a bounded trickle of core-core dialogue + a few
    settlement jobs) so it never rations a healthy run — lower it if a
    live `system_memory` reading still shows pressure. See
    docs/DECISIONS.md, "core cast + daily LLM ceiling" pass."""

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

    def days_per_year(self) -> int:
        return sum(self.days_per_month)
