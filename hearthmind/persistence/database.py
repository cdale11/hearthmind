"""SQLite connection + schema management.

Three tables:
- `snapshots`: full world-state checkpoints (append-only; we keep history
  rather than overwriting, which is cheap at this scale and means we can
  later add "rewind to an earlier point" as a feature almost for free).
- `events`: an append-only log of notable calendar/world events. This is
  intentionally separate from snapshots — it's meant to become the backbone
  of a "current events" / history feed in the future browser interface, and
  potentially a replay log (see docs/DECISIONS.md, M1-4).
- `world_meta`: a single row of facts fixed at world creation (seed, size,
  created_at), so we can sanity-check that `server.py` isn't being pointed
  at the wrong config for an existing world.
- `metrics`: one small JSON row per sim-day (see
  `snapshot.log_metrics`) — the fixed-cadence time-series that makes a
  long run *analyzable* (population/food/social curves over years)
  rather than only inspectable at "now". Deliberately a separate table
  from `events` (which is narrative, irregular, and unbounded-ish) so
  research queries never scan the event log. See docs/DECISIONS.md,
  architecture-review implementation pass.
- `consciousness_log` (v0.86.2, Engineering Constitution §6 "cold
  information belongs on disk, not permanently in RAM"): the durable,
  much-larger-than-in-RAM history behind `World.consciousness_memory`/
  `consciousness_player_model`/`consciousness_objectives`/
  `consciousness_intervention_log`, which are deliberately tiny
  (capped 16/6/2/12) for prompt-building and snapshot size — without
  this table, everything past those caps was silently and permanently
  forgotten, unlike `Settlement.traditions`/`inventions`/etc., whose
  full text already survives past their own caps via the `events`
  table. Deliberately a SEPARATE table from `events` rather than a new
  `events` category: the consciousness's private inner
  memory/theories/objectives must never leak into `recent_events`/
  `recent_events_diverse`, which every other settlement-scoped LLM
  prompt (chronicle, town_brain, beliefs, ...) reads — the "hidden
  intelligence... nudging through deniable channels" design (CLAUDE.md)
  would break if its own private log fed other jobs' prompts. Pruned on
  the snapshot cadence like `events`/`metrics` (see `Config.
  consciousness_log_retention`); reachable only via the developer
  observatory (`event_category_counts`-style query), same Phase G/N
  dev-console-only discipline as `temperament`/`consciousness` itself.
- `agent_memory_log` (v0.86.3, same Constitution §6 motivation, but
  **main-UI visible** per explicit user direction — unlike
  `consciousness_log`, this is meant to be discovered, not hidden): the
  durable per-agent counterpart. `kind="episodic"` rows are significant
  (non-routine) memories evicted from `Agent.memories` past its small
  cap (8) — routine ones (frequent food/tool/medicine-sharing notes) are
  deliberately excluded to keep volume bounded to genuinely memorable
  moments, not noise. `kind="semantic"` rows are every distilled
  self-theory `Agent.semantic_memories` has ever held (capped at 3 in
  RAM), giving a full "how this person's understanding of themselves
  evolved" arc on disk. This is the concrete "the world should appear
  to learn continuously... visible to the observer" mechanism: an NPC's
  full life history/self-understanding survives past its RAM caps and
  is fetchable on demand (`GET /agents/{id}/memory_log`) for the NPC
  inspector, not just the last few entries a live snapshot shows.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS world_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    saved_at REAL NOT NULL,
    world_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_tick ON snapshots (tick);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    logged_at REAL NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_tick ON events (tick);
CREATE INDEX IF NOT EXISTS idx_events_category ON events (category, id);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    logged_at REAL NOT NULL,
    metrics_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_tick ON metrics (tick);

CREATE TABLE IF NOT EXISTS consciousness_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    logged_at REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consciousness_log_kind ON consciousness_log (kind, id);

CREATE TABLE IF NOT EXISTS agent_memory_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    logged_at REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_memory_log_agent ON agent_memory_log (agent_id, id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True) if Path(db_path).parent != Path("") else None
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    # NORMAL is the documented pairing for WAL: the WAL file is still
    # synced at checkpoint, so a crash can lose at most the final
    # not-yet-checkpointed commits, never corrupt the database — and it
    # removes a per-commit fsync from every tick, which matters on the
    # target hardware's slow storage far more than the durability of the
    # last in-flight tick does (a lost tick is one sim-minute of drift;
    # the periodic snapshot is the real recovery point regardless).
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def is_fresh(conn: sqlite3.Connection) -> bool:
    """True if this database has no world_meta row yet (brand new world)."""
    row = conn.execute("SELECT 1 FROM world_meta WHERE id = 1").fetchone()
    return row is None


def write_world_meta(conn: sqlite3.Connection, seed: int, width: int, height: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO world_meta (id, seed, width, height, created_at) VALUES (1, ?, ?, ?, ?)",
        (seed, width, height, time.time()),
    )
    conn.commit()


@contextmanager
def open_db(db_path: str):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
