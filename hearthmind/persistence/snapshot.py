"""Save/load World snapshots, and append to the event log."""
from __future__ import annotations

import json
import sqlite3
import time

from hearthmind.config import Config
from hearthmind.world.state import World


SNAPSHOT_KEEP_RECENT = 48
"""How many most-recent snapshot rows survive pruning (see
`save_snapshot`) — ~48 minutes of rewind at the default 60-tick cadence
and 1s ticks. Found by the July 2026 architecture review: the table was
append-only-forever while nothing ever read any row but the newest, so
a long-running world's DB grew without bound (a full world JSON every
60 ticks, indefinitely) — the single biggest threat to "runs forever."
"""

SNAPSHOT_KEYFRAME_INTERVAL_TICKS = 50_000
"""Older snapshots aren't deleted wholesale: the first snapshot at or
after each multiple of this interval is kept as a permanent keyframe,
so a future scrub-through-time/replay feature (docs/ROADMAP.md) still
has sparse anchors across the world's whole history without the
unbounded growth."""


def save_snapshot(conn: sqlite3.Connection, world: World) -> None:
    conn.execute(
        "INSERT INTO snapshots (tick, saved_at, world_json) VALUES (?, ?, ?)",
        (world.clock.tick_count, time.time(), json.dumps(world.to_dict())),
    )
    _prune_snapshots(conn)
    conn.commit()


def _prune_snapshots(conn: sqlite3.Connection) -> None:
    """Delete snapshot rows that are neither recent (last
    SNAPSHOT_KEEP_RECENT) nor a keyframe (the earliest row in each
    SNAPSHOT_KEYFRAME_INTERVAL_TICKS bucket). Runs inside
    `save_snapshot`'s transaction — cheap (indexed on tick) and keeps
    the table bounded on an arbitrarily long run."""
    conn.execute(
        """
        DELETE FROM snapshots WHERE id NOT IN (
            SELECT id FROM snapshots ORDER BY tick DESC LIMIT ?
        ) AND id NOT IN (
            SELECT MIN(id) FROM snapshots GROUP BY tick / ?
        )
        """,
        (SNAPSHOT_KEEP_RECENT, SNAPSHOT_KEYFRAME_INTERVAL_TICKS),
    )


def load_latest_snapshot(conn: sqlite3.Connection, runtime_config: Config) -> World | None:
    row = conn.execute(
        "SELECT world_json FROM snapshots ORDER BY tick DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    return World.from_dict(data, runtime_config)


def log_event(
    conn: sqlite3.Connection, tick: int, category: str, description: str, commit: bool = True,
) -> None:
    """`commit=False` lets a caller that logs many events per tick (the
    engine) batch them into one commit at the end of the tick instead of
    one fsync per event — found by the July 2026 architecture review to
    be the dominant per-tick I/O cost on a busy tick. Rows written with
    commit=False are still visible to reads on the same connection
    before the commit lands."""
    conn.execute(
        "INSERT INTO events (tick, logged_at, category, description) VALUES (?, ?, ?, ?)",
        (tick, time.time(), category, description),
    )
    if commit:
        conn.commit()


def log_metrics(conn: sqlite3.Connection, tick: int, metrics: dict, commit: bool = False) -> None:
    """Append one time-series row (see database.py's `metrics` table).
    Called by the engine once per sim-day — same batched-commit
    convention as `log_event`."""
    conn.execute(
        "INSERT INTO metrics (tick, logged_at, metrics_json) VALUES (?, ?, ?)",
        (tick, time.time(), json.dumps(metrics)),
    )
    if commit:
        conn.commit()


def recent_metrics(conn: sqlite3.Connection, limit: int = 365) -> list[dict]:
    """Most-recent metrics rows, oldest-first (chart-ready). Each row is
    the stored dict plus its tick."""
    rows = conn.execute(
        "SELECT tick, metrics_json FROM metrics ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for tick, metrics_json in reversed(rows):
        entry = json.loads(metrics_json)
        entry["tick"] = tick
        out.append(entry)
    return out


def recent_events(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT tick, logged_at, category, description FROM events ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"tick": tick, "logged_at": logged_at, "category": category, "description": description}
        for tick, logged_at, category, description in rows
    ]


HISTORY_CATEGORIES = (
    "founding", "genesis", "settlement_named", "era_advance", "chronicle",
    "tradition", "invention", "festival", "belief_formed", "belief_revised",
    "omen", "wildlife_recolonized", "wildlife_extinct",
    "disaster_flood", "disaster_wildfire", "disaster_storm", "disaster_heatwave", "disaster_frost",
    "migrant_arrived", "dialogue_surfaced", "documentary",
    "dispute", "record_written", "place_named", "institution_belief",
    "family_formed", "council_formed", "guild_formed", "settlement_founded",
)
"""The curated, narrative subset of event categories — settlement-level
history, not per-tick noise (day_end, dialogue, farm_planted, etc.).
Backs `GET /history` / the UI's History tab: a summarized town history
distinct from the main event log's live, everything-included feed. See
docs/DECISIONS.md, "map/UI/ecology follow-up.\""""


def history_events(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    placeholders = ",".join("?" for _ in HISTORY_CATEGORIES)
    rows = conn.execute(
        f"SELECT tick, logged_at, category, description FROM events "
        f"WHERE category IN ({placeholders}) ORDER BY id DESC LIMIT ?",
        (*HISTORY_CATEGORIES, limit),
    ).fetchall()
    return [
        {"tick": tick, "logged_at": logged_at, "category": category, "description": description}
        for tick, logged_at, category, description in rows
    ]


def event_category_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """All-time histogram of event categories — part of the extensive
    diagnostic report (`GET /diagnostics`) built for debugging an
    unattended overnight soak run: how many dialogues/rumors/deaths/etc.
    happened over the whole run, not just the recent-events tail. See
    docs/DECISIONS.md, diagnostics pass."""
    rows = conn.execute("SELECT category, COUNT(*) FROM events GROUP BY category").fetchall()
    return {category: count for category, count in rows}


def total_event_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def snapshot_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def list_snapshot_ticks(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    """Observatory UI depth pass (docs/ROADMAP.md's flagged "a true
    scrub-through-time replay view" gap): every tick a snapshot is
    still on file for, newest-first — the `SNAPSHOT_KEEP_RECENT` window
    plus any surviving `SNAPSHOT_KEYFRAME_INTERVAL_TICKS` keyframes, so
    a long-running world's timeline has sparse-but-real anchors across
    its whole history, not just the last hour. Read-only, no live state
    touched — backs `GET /snapshots`."""
    rows = conn.execute(
        "SELECT tick, saved_at FROM snapshots ORDER BY tick DESC LIMIT ?", (limit,)
    ).fetchall()
    return [{"tick": tick, "saved_at": saved_at} for tick, saved_at in rows]


def load_snapshot_at_tick(conn: sqlite3.Connection, tick: int, runtime_config: Config) -> World | None:
    """Load one specific past snapshot by its exact tick (must be a
    value `list_snapshot_ticks` actually returned — snapshots are
    pruned, so an arbitrary tick isn't guaranteed to exist) rather than
    always the newest. Same reconstruction path as `load_latest_
    snapshot`; the caller is responsible for only reading from the
    result, never advancing or persisting it — this is a read-only
    scrub-through-time view, not a rewind of the live world. See
    `GET /snapshots/{tick}`."""
    row = conn.execute(
        "SELECT world_json FROM snapshots WHERE tick = ? LIMIT 1", (tick,)
    ).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    return World.from_dict(data, runtime_config)
