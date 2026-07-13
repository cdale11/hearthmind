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

    db_path: str = "world.sqlite3"

    # --- runtime: LLM (Ollama) cognition layer, off by default -----------------
    llm_enabled: bool = True
    """On by default as of E2: cognition, chronicle, culture, and
    NPC-to-NPC dialogue are the primary emergence levers, so a bare
    `Config()` should exercise them. Every LLM call still degrades to a
    deterministic fallback if Ollama isn't reachable — turning this off
    is only needed for a fully offline/deterministic run (e.g. a fast
    local smoke test). See docs/DECISIONS.md, E2."""

    llm_host: str = "http://localhost:11434"
    llm_model: str = "qwen3.5:2b"
    """Set per explicit user instruction (confirmed available/pulled on
    their machine) — smaller still than the prior `qwen3:4b` default,
    leaving more of the 8GB+zram budget for the simulation process
    itself. Qwen3.x is a hybrid "thinking" model; this project disables
    that (see OllamaClient.generate_json's `"think": False` and its
    defensive `<think>` stripping) since every prompt here wants a
    single strict-JSON answer, not visible chain-of-thought eating into
    the timeout budget. If a live run shows 2B is too weak for coherent
    town-brain/dialogue output, report back rather than silently
    reverting. See docs/DECISIONS.md, "LLM-as-brain batch,\" the
    real-calendar/genesis-seed follow-up, and the world-model/beliefs
    follow-up."""
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
    llm_max_concurrent: int = 1
    """How many LLM requests may be in flight at once. Lowered 4 -> 2 in
    v0.43.0 (the v0.39.0 architecture review's own recommendation,
    finally acted on) after a live report of heavy swap and an
    unresponsive 8GB system within an hour at only 100 population, LLM
    enabled; the symptom recurred even at 2, so dropped again to the
    floor, 1, in v0.43.1 (fully serialized — never more than one Ollama
    generate call in flight system-wide). Each in-flight call holds its
    own KV-cache allocation in the *separate* Ollama server process —
    invisible to this process's own RSS (the v0.42.0 relationship-leak
    probe measured only this process and stayed under 100MB), but real
    system memory pressure all the same. "Not budget-constrained on the
    user's hardware" (the reasoning that raised this to 4 in E2) was true
    for wall-clock throughput but not for concurrent memory footprint —
    those are different constraints. Trade-off, stated plainly: on an 8GB
    machine, staying responsive is worth more than LLM throughput: every
    LLM-driven decision already has a deterministic fallback (the
    liveness contract this project has held since B1), so a saturated
    single lane degrades *richness* (more agents reason via fallback,
    more often) rather than correctness or uptime. If a live run still
    swaps at max_concurrent=1, the next lever is a smaller/more quantized
    model or a shorter `llm_keep_alive`, not concurrency (already at its
    floor). See also `llm_num_ctx`/`llm_num_predict`/`llm_keep_alive`
    below, which bound the *per-call* and *idle* memory this lever no
    longer needs to multiply."""
    llm_num_ctx: int = 2048
    """Explicit Ollama context-window cap sent with every request
    (v0.43.0). Previously unset, so Ollama silently used its own default —
    fine when it happens to be small, a hidden memory multiplier
    (`llm_max_concurrent` x this) when it isn't. Every prompt in this
    project is capped short (`PROMPT_CULTURE_LIST_MAX`, `RECENT_MEMORIES_
    IN_PROMPT`, grounded single-scene cognition/dialogue prompts) and
    comfortably fits well under 2048 tokens — this is a safety ceiling on
    Ollama's per-call KV-cache allocation, not a working limit any real
    prompt here is expected to hit."""
    llm_num_predict: int = 512
    """Explicit cap on generated tokens per call (v0.43.0). Every response
    here is meant to be a short, strict-JSON answer (a goal, a line of
    dialogue, a settlement decision) — this bounds the worst case where
    the model rambles instead of terminating cleanly, which otherwise
    burns both memory and the `llm_timeout_seconds` budget for no benefit
    (the JSON parse would reject an overlong response anyway)."""
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
