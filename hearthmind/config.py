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
    llm_timeout_seconds: float = 30.0
    """CPU inference on an 8GB+zram machine that's also running the
    simulation itself is noticeably slower under contention than a quiet
    benchmark — a real soak run saw an occasional timeout at the old 10s
    default even with qwen2.5:3b. Bumped again (20 -> 30) alongside the
    qwen2.5:7b-instruct default above, which is slower per-token on CPU.
    Every call still has a deterministic fallback (see
    hearthmind/llm/jobs.py), so this only trades a slightly longer
    worst-case wait for a lower fallback rate. See docs/DECISIONS.md, D5."""
    llm_max_concurrent: int = 4
    """How many LLM requests may be in flight at once — the lever for
    keeping Ollama's own thread pool busy without overwhelming it. Raised
    from 2 (E2): dialogue jobs now run alongside cognition/chronicle/
    culture jobs, and the user has confirmed local LLM throughput is not
    budget-constrained on their hardware — this is still bounded (not
    unlimited) to avoid overwhelming Ollama's own thread pool at once."""

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
