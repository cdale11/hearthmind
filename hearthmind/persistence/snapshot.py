"""Save/load World snapshots, and append to the event log."""
from __future__ import annotations

import json
import sqlite3
import time

from hearthmind.config import Config
from hearthmind.world.state import World


def save_snapshot(conn: sqlite3.Connection, world: World) -> None:
    conn.execute(
        "INSERT INTO snapshots (tick, saved_at, world_json) VALUES (?, ?, ?)",
        (world.clock.tick_count, time.time(), json.dumps(world.to_dict())),
    )
    conn.commit()


def load_latest_snapshot(conn: sqlite3.Connection, runtime_config: Config) -> World | None:
    row = conn.execute(
        "SELECT world_json FROM snapshots ORDER BY tick DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    return World.from_dict(data, runtime_config)


def log_event(conn: sqlite3.Connection, tick: int, category: str, description: str) -> None:
    conn.execute(
        "INSERT INTO events (tick, logged_at, category, description) VALUES (?, ?, ?, ?)",
        (tick, time.time(), category, description),
    )
    conn.commit()


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
    "disaster_flood", "disaster_wildfire", "disaster_storm",
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
