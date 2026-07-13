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
