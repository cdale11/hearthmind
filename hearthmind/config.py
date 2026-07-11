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
    seed: int = 1337
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
    days_per_season: int = 20
    seasons_per_year: tuple[str, ...] = ("spring", "summer", "autumn", "winter")

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
    llm_enabled: bool = False
    """Off by default: the simulation is fully deterministic and testable
    without Ollama installed. Turning this on requires a reachable Ollama
    server with `llm_model` pulled; see README."""

    llm_host: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:3b"
    llm_timeout_seconds: float = 20.0
    """CPU inference on an 8GB+zram machine that's also running the
    simulation itself is noticeably slower under contention than a quiet
    benchmark — a real soak run saw an occasional timeout at the old 10s
    default even with qwen2.5:3b. Every call still has a deterministic
    fallback (see hearthmind/llm/jobs.py), so this only trades a slightly
    longer worst-case wait for a lower fallback rate. See
    docs/DECISIONS.md, D5."""
    llm_max_concurrent: int = 2
    """How many LLM requests may be in flight at once — the lever for
    keeping Ollama's own thread pool busy without overwhelming it."""

    def days_per_year(self) -> int:
        return self.days_per_season * len(self.seasons_per_year)
