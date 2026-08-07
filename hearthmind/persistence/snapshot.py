"""Save/load World snapshots, and append to the event log."""
from __future__ import annotations

import json
import sqlite3
import time

from hearthmind.config import Config
from hearthmind.persistence.diff import apply_patch, diff_dict
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

QUERY_LIMIT_MAX = 5000
"""Hard ceiling clamped onto the `limit` of every events/metrics query
(`recent_events`/`history_events`/`recent_metrics`). These are reachable
from the browser API's `?limit=` query param (interface/app.py); without
a clamp, a single request for a huge limit against the (now bounded, but
still large) events table would pull that many rows into a Python list
in one go — a client-triggered RAM spike that grows with the table.
5000 is far more than any UI view shows (the live feed uses 50, History
200) while capping the worst case. See docs/DECISIONS.md, v0.71.0
memory-audit pass."""


def _reconstruct_snapshot_dict(conn: sqlite3.Connection, snapshot_id: int) -> dict | None:
    """B14.2's real reconstruction path: a `kind='full'` row's own
    `world_json` IS the world dict, returned as-is. A `kind=
    'incremental'` row's `world_json` is instead a `diff.diff_dict`
    PATCH against its own `base_snapshot_id` — reconstruction walks
    that chain back (recursing; bounded by `SnapshotPolicy.
    full_snapshot_every`, so this never recurses deep) until it hits a
    real FULL row, then applies every patch forward in order via
    `diff.apply_patch`. Returns `None` only if `snapshot_id` doesn't
    exist (a genuinely missing row, not a normal case — `_prune_
    snapshots` is specifically written to never let this happen for a
    row still reachable from a kept snapshot)."""
    row = conn.execute(
        "SELECT world_json, kind, base_snapshot_id FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if row is None:
        return None
    world_json, kind, base_id = row
    data = json.loads(world_json)
    if kind != "incremental" or base_id is None:
        return data
    base_dict = _reconstruct_snapshot_dict(conn, base_id)
    if base_dict is None:
        # A real corruption case (an incremental row's own base was
        # somehow deleted) — surface it loudly rather than silently
        # returning a half-reconstructed dict a caller might persist
        # forward as if it were real world state.
        raise ValueError(
            f"snapshot {snapshot_id} is incremental against missing base snapshot {base_id} "
            "(this should be structurally impossible — _prune_snapshots keeps every ancestor "
            "of every retained snapshot; this indicates real database corruption)"
        )
    return apply_patch(base_dict, data)


def save_snapshot(conn: sqlite3.Connection, world: World, kind: str = "full") -> None:
    """`kind`: `"full"` (default, and every pre-B14.2 caller's exact
    prior behavior — a complete `world.to_dict()` dump) or
    `"incremental"` (B14.2's real diff format: stores only what changed
    since the most recently saved snapshot, `kind`/`base_snapshot_id`
    unchanged). An `"incremental"` request with no prior snapshot to
    diff against (a brand-new world) degrades to a real `"full"` save
    instead — there's nothing to diff against yet, and forcing one
    would just be a full dump wearing the wrong label."""
    new_dict = world.to_dict()
    base_id = None
    if kind == "incremental":
        prev = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if prev is None:
            kind = "full"
        else:
            base_id = prev[0]
            base_dict = _reconstruct_snapshot_dict(conn, base_id)
            payload = diff_dict(base_dict, new_dict)
    if kind != "incremental":
        payload = new_dict
    conn.execute(
        "INSERT INTO snapshots (tick, saved_at, world_json, kind, base_snapshot_id) VALUES (?, ?, ?, ?, ?)",
        (world.clock.tick_count, time.time(), json.dumps(payload), kind, base_id),
    )
    _prune_snapshots(conn)
    _prune_events(conn, world.config.event_log_retention)
    _prune_metrics(conn, world.config.metrics_log_retention)
    _prune_consciousness_log(conn, world.config.consciousness_log_retention)
    _prune_agent_memory_log(conn, world.config.agent_memory_log_retention)
    conn.commit()


def _prune_events(conn: sqlite3.Connection, keep: int) -> None:
    """Keep only the most-recent `keep` rows of the `events` table.

    `events` is the one genuinely unbounded-growth table on a persistent,
    always-running world (snapshots are already pruned to recent +
    keyframes; metrics grow only one row per sim-day). It logs every
    notable world/life event — ~1-2 rows/tick sustained — so an
    indefinite run would grow the DB file without limit. Nothing reads
    beyond the recent tail (the live feed queries LIMIT 50, History
    LIMIT 200, both newest-first), and deep world-state history is
    preserved separately by snapshot keyframes, so trimming the raw log
    to a large recent window is lossless for every actual reader. Runs on
    the snapshot cadence (every `snapshot_every_ticks`), inside the same
    transaction. `keep <= 0` disables pruning (unbounded, opt-in). See
    docs/DECISIONS.md, v0.71.0 memory-audit pass."""
    if keep <= 0:
        return
    conn.execute(
        """
        DELETE FROM events WHERE id NOT IN (
            SELECT id FROM events ORDER BY id DESC LIMIT ?
        )
        """,
        (keep,),
    )


def _prune_metrics(conn: sqlite3.Connection, keep: int) -> None:
    """Keep only the most-recent `keep` rows of the `metrics` table —
    same shape as `_prune_events`, added in v0.78.1 once "meant to run
    stably for years" made the previously-deferred "revisit only for
    multi-year sim runs" condition (see `Config.metrics_log_retention`)
    concretely true. `keep <= 0` disables pruning (unbounded, opt-in)."""
    if keep <= 0:
        return
    conn.execute(
        """
        DELETE FROM metrics WHERE id NOT IN (
            SELECT id FROM metrics ORDER BY id DESC LIMIT ?
        )
        """,
        (keep,),
    )


def _prune_consciousness_log(conn: sqlite3.Connection, keep: int) -> None:
    """Keep only the most-recent `keep` rows of `consciousness_log` —
    same shape as `_prune_events`/`_prune_metrics`. `keep <= 0` disables
    pruning (unbounded, opt-in). See database.py's schema docstring for
    why this is a separate table from `events`."""
    if keep <= 0:
        return
    conn.execute(
        """
        DELETE FROM consciousness_log WHERE id NOT IN (
            SELECT id FROM consciousness_log ORDER BY id DESC LIMIT ?
        )
        """,
        (keep,),
    )


def log_consciousness_entry(
    conn: sqlite3.Connection, tick: int, kind: str, text: str, commit: bool = False,
) -> None:
    """Durable, much-larger-than-in-RAM record of one Town Consciousness
    entry (`kind` in "memory"/"player_theory"/"objective"/"intervention")
    — called from `SimulationEngine._maybe_schedule_consciousness`'s
    `apply()` alongside (not instead of) the small capped in-RAM lists
    (`World.consciousness_memory` etc.), which stay exactly as they were
    for prompt-building/snapshot size. `commit=False` matches `_log`'s
    per-tick batching convention — see its docstring."""
    conn.execute(
        "INSERT INTO consciousness_log (tick, logged_at, kind, text) VALUES (?, ?, ?, ?)",
        (tick, time.time(), kind, text),
    )
    if commit:
        conn.commit()


def recent_consciousness_log(conn: sqlite3.Connection, kind: str | None = None, limit: int = 50) -> list[dict]:
    """Newest-first `consciousness_log` rows, optionally filtered to one
    `kind`. Developer-observatory-only reader (Phase G/N dev-console-only
    discipline) — never consumed by any LLM prompt (see database.py's
    schema docstring for why the durable log is a separate table)."""
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
    if kind is not None:
        rows = conn.execute(
            "SELECT tick, logged_at, kind, text FROM consciousness_log WHERE kind = ? ORDER BY id DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT tick, logged_at, kind, text FROM consciousness_log ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return [
        {"tick": tick, "logged_at": logged_at, "kind": kind_, "text": text}
        for tick, logged_at, kind_, text in rows
    ]


def consciousness_log_count(conn: sqlite3.Connection) -> int:
    """Total retained `consciousness_log` rows — the diagnostics-panel
    signal that the durable history is actually accumulating (compare
    against the tiny in-RAM cap counts already shown alongside it)."""
    return conn.execute("SELECT COUNT(*) FROM consciousness_log").fetchone()[0]


def _prune_agent_memory_log(conn: sqlite3.Connection, keep: int) -> None:
    """Keep only the most-recent `keep` rows of `agent_memory_log`
    GLOBALLY (across all agents), same shape as `_prune_events`/
    `_prune_consciousness_log`. A global cap rather than a per-agent one
    is deliberate: it bounds total DB growth regardless of population
    size, matching the "memory bounded" priority — a long-lived world
    with hundreds of agents still gets one predictable ceiling, not one
    per agent. `keep <= 0` disables pruning (unbounded, opt-in)."""
    if keep <= 0:
        return
    conn.execute(
        """
        DELETE FROM agent_memory_log WHERE id NOT IN (
            SELECT id FROM agent_memory_log ORDER BY id DESC LIMIT ?
        )
        """,
        (keep,),
    )


def log_agent_memory_entry(
    conn: sqlite3.Connection, tick: int, agent_id: int, kind: str, text: str, commit: bool = False,
) -> None:
    """Durable record of one agent's memory (`kind` "episodic" for a
    significant memory evicted from `Agent.memories`, or "semantic" for
    a distilled self-theory written to `Agent.semantic_memories`) — see
    database.py's schema docstring. Called from `Population._remember`'s
    eviction branch (episodic, drained by the engine each tick — see
    `hearthmind.agents.population._pending_memory_evictions`) and from
    `SimulationEngine._maybe_schedule_personal_belief`'s `apply()`
    (semantic, at write time). `commit=False` matches `_log`'s per-tick
    batching convention."""
    conn.execute(
        "INSERT INTO agent_memory_log (agent_id, tick, logged_at, kind, text) VALUES (?, ?, ?, ?, ?)",
        (agent_id, tick, time.time(), kind, text),
    )
    if commit:
        conn.commit()


def recent_agent_memory_log(
    conn: sqlite3.Connection, agent_id: int, kind: str | None = None, limit: int = 100,
) -> list[dict]:
    """Newest-first `agent_memory_log` rows for one agent, optionally
    filtered to one `kind`. Backs `GET /agents/{id}/memory_log` — the
    NPC inspector's on-demand "full life history" fetch, main-UI
    visible per explicit user direction (unlike `consciousness_log`)."""
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
    if kind is not None:
        rows = conn.execute(
            "SELECT tick, logged_at, kind, text FROM agent_memory_log "
            "WHERE agent_id = ? AND kind = ? ORDER BY id DESC LIMIT ?",
            (agent_id, kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT tick, logged_at, kind, text FROM agent_memory_log "
            "WHERE agent_id = ? ORDER BY id DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
    return [
        {"tick": tick, "logged_at": logged_at, "kind": kind_, "text": text}
        for tick, logged_at, kind_, text in rows
    ]


def agent_memory_log_count(conn: sqlite3.Connection, agent_id: int) -> int:
    """Total retained `agent_memory_log` rows for one agent — the "N
    memories preserved from a fuller life" count the NPC inspector shows
    even before the on-demand full-history fetch is triggered."""
    return conn.execute(
        "SELECT COUNT(*) FROM agent_memory_log WHERE agent_id = ?", (agent_id,)
    ).fetchone()[0]


def _prune_snapshots(conn: sqlite3.Connection) -> None:
    """Delete snapshot rows that are neither recent (last
    SNAPSHOT_KEEP_RECENT) nor a keyframe (the earliest row in each
    SNAPSHOT_KEYFRAME_INTERVAL_TICKS bucket) — same real selection as
    before B14.2 — EXTENDED to also keep every real ANCESTOR of a kept
    row, walking each one's `base_snapshot_id` chain back to its
    nearest FULL root. This is the concrete fix for the correctness
    hazard B14.2 was flagged against: without it, a kept INCREMENTAL
    row's own base could be a plain unprotected row and get deleted
    out from under it, silently orphaning a snapshot nothing could
    ever reconstruct again. Runs inside `save_snapshot`'s transaction."""
    keep_rows = conn.execute(
        """
        SELECT id FROM snapshots WHERE id IN (
            SELECT id FROM snapshots ORDER BY tick DESC LIMIT ?
        ) OR id IN (
            SELECT MIN(id) FROM snapshots GROUP BY tick / ?
        )
        """,
        (SNAPSHOT_KEEP_RECENT, SNAPSHOT_KEYFRAME_INTERVAL_TICKS),
    ).fetchall()
    keep_ids = {row[0] for row in keep_rows}
    if not keep_ids:
        return
    frontier = list(keep_ids)
    while frontier:
        current_id = frontier.pop()
        row = conn.execute("SELECT base_snapshot_id FROM snapshots WHERE id = ?", (current_id,)).fetchone()
        base_id = row[0] if row else None
        if base_id is not None and base_id not in keep_ids:
            keep_ids.add(base_id)
            frontier.append(base_id)
    conn.execute(
        f"DELETE FROM snapshots WHERE id NOT IN ({','.join('?' * len(keep_ids))})",
        tuple(keep_ids),
    )


def load_latest_snapshot(conn: sqlite3.Connection, runtime_config: Config) -> World | None:
    row = conn.execute(
        "SELECT id FROM snapshots ORDER BY tick DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    data = _reconstruct_snapshot_dict(conn, row[0])
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


def log_events_batch(conn: sqlite3.Connection, rows: list[tuple[int, float, str, str]]) -> None:
    """Tier 5 B14.3's real first consumer (`SimulationEngine._flush_
    event_write_buffer`): one `executemany()` INSERT for several
    buffered rows instead of `log_event`'s own one-`execute()`-per-row
    shape — the real batched-write mechanism `batch_size_for_storage`
    (`simulation/persistence_scheduling.py`) was built to size, and
    never had a live consumer until this pass. `rows` are `(tick,
    logged_at, category, description)` tuples, the exact positional
    shape a single `log_event` call already inserts — never
    auto-commits, same `commit=False` convention every other logger in
    this module already follows (the caller decides when to commit,
    exactly as before this function existed)."""
    if not rows:
        return
    conn.executemany(
        "INSERT INTO events (tick, logged_at, category, description) VALUES (?, ?, ?, ?)",
        rows,
    )


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
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
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
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
    rows = conn.execute(
        "SELECT tick, logged_at, category, description FROM events ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"tick": tick, "logged_at": logged_at, "category": category, "description": description}
        for tick, logged_at, category, description in rows
    ]


ROUTINE_EVENT_CATEGORIES = frozenset({
    "day_end", "week_end", "month_end", "season_end", "year_end",
    "farm_planted", "construction_started", "building_completed",
    "recovery", "wildlife_recolonized",
    # Added per a live audit finding (P0.2d): `terrain_reclaimed`/
    # `terrain_thinned` (world/terrain_evolution.py) fire the same
    # bursty, physical-substrate-tick way `farm_planted`/`recovery`
    # already do (many tiles can reclaim/thin in one pass) but were
    # missing from this set entirely — a live beliefs prompt showed 14
    # consecutive "Nature reclaimed abandoned ground at (x, y)" lines,
    # crowding out the rarer social/dramatic events this cap exists to
    # protect, exactly the failure mode this frozenset's own docstring
    # describes for every category already in it.
    "terrain_reclaimed", "terrain_thinned",
})
"""Categories that fire routinely at high volume (a calendar tick, a farm
plot planted, a wall going up) rather than marking something a chronicle
or a person would actually remark on. Plain chronological `recent_events`
lets these crowd out the rarer social/dramatic events a 50-row window is
meant to surface — this is v0.78.0's fix for the live-reported "chronicles
and conversations are dominated by weather and farming" complaint (there
is no separate weather-event category; the actual culprits are these
routine physical/calendar rows outnumbering social ones many-to-one over
any real stretch of ticks)."""


def _dedupe_rumor_topics(events: list[dict]) -> list[dict]:
    """Prompt-token audit fix (2026-07): when a rumor spreads through
    several pairs (a common, natural gossip pattern — `SimulationEngine.
    _apply_pending_dialogue_results` logs a `rumor`-category row "X and
    Y: <rumor text>" for every pair that shares it), each occurrence
    left undeduped crowds an LLM prompt's event window with many
    near-identical lines about the same single topic — a live-observed
    saturated prompt showed the same rumor text 6 times in one chronicle
    call, more than half its "recent events" list. Keeps only the
    newest occurrence of each distinct rumor text (matched by the text
    after the first ": ", so it's agent-name-agnostic), appending an
    "echoed by N more pairs" count instead of dropping the fact that it
    spread — a hierarchical summary rather than a raw list, per this
    project's prompt-density audit. Every other category passes through
    completely unchanged; this only touches the copy handed to `recent_
    events_diverse`'s LLM-prompt callers, never the raw `events` table
    or /events history."""
    seen: dict[str, dict] = {}
    result: list[dict] = []
    for event in events:  # newest-first
        if event["category"] != "rumor":
            result.append(event)
            continue
        _, _, topic = event["description"].partition(": ")
        topic_key = topic.strip().lower() or event["description"]
        existing = seen.get(topic_key)
        if existing is not None:
            existing["_echo_count"] = existing.get("_echo_count", 1) + 1
            continue
        entry = dict(event)
        seen[topic_key] = entry
        result.append(entry)
    for entry in result:
        count = entry.pop("_echo_count", None)
        if count:
            plural = "s" if count - 1 != 1 else ""
            entry["description"] = f"{entry['description']} (echoed by {count - 1} more pair{plural})"
    return result


def recent_events_diverse(conn: sqlite3.Connection, limit: int = 20, routine_cap: int | None = None) -> list[dict]:
    """Same shape/order as `recent_events` (newest-first list of dicts)
    but caps how many `ROUTINE_EVENT_CATEGORIES` rows can occupy the
    window, so a burst of farm-planting or calendar ticks doesn't push a
    rarer dispute/birth/omen/rumor out of an LLM prompt's event digest.
    Pulls a wider raw batch (`limit * 4`, still bounded by
    QUERY_LIMIT_MAX) so there's enough non-routine material to fill the
    window even when routine events dominate the raw stream, then keeps
    every non-routine row plus up to `routine_cap` (default limit // 3)
    of the newest routine ones, re-sorted back to newest-first and
    trimmed to `limit`. Only for LLM-prompt consumers (chronicle,
    town_brain, beliefs, documentary, personal_belief/reflection) — the
    public `/events`/`/history` API keeps calling plain `recent_events`
    so nothing is ever hidden from a reader, only from what a prompt
    happens to sample."""
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
    if routine_cap is None:
        routine_cap = max(1, limit // 3)
    raw = recent_events(conn, limit=min(limit * 4, QUERY_LIMIT_MAX))
    raw = _dedupe_rumor_topics(raw)
    kept: list[dict] = []
    routine_kept = 0
    for event in raw:  # newest-first
        if event["category"] in ROUTINE_EVENT_CATEGORIES:
            if routine_kept >= routine_cap:
                continue
            routine_kept += 1
        kept.append(event)
        if len(kept) >= limit:
            break
    return kept


def events_by_category(conn: sqlite3.Connection, category: str, limit: int = 20) -> list[dict]:
    """Newest-first events of exactly one category — used by `llm/
    folklore.py`'s monthly condensation job to pull recent rumor-
    category events without pulling (and client-side filtering) the
    whole diverse event window. Same `limit` clamp as every other
    events query."""
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
    rows = conn.execute(
        "SELECT tick, logged_at, category, description FROM events WHERE category = ? ORDER BY id DESC LIMIT ?",
        (category, limit),
    ).fetchall()
    return [
        {"tick": tick, "logged_at": logged_at, "category": category, "description": description}
        for tick, logged_at, category, description in rows
    ]


def events_since_tick(
    conn: sqlite3.Connection, since_tick: int, limit: int = 200, routine_cap: int | None = None,
) -> list[dict]:
    """§5 "While you were away" digest (docs/IDEAS-2026-07-EMERGENCE.md):
    newest-first events with `tick > since_tick`, filtered the same way
    `recent_events_diverse` bounds routine noise — a gap of many days
    away could otherwise be dominated by `day_end`/farm-planting rows.
    Unlike `recent_events_diverse` (which windows by row COUNT), this
    windows by TICK RANGE first so a short absence doesn't pull in
    unrelated older history and a long one doesn't silently truncate to
    only the last `limit` routine-heavy rows without at least trying to
    keep the non-routine ones from the whole gap."""
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
    if routine_cap is None:
        routine_cap = max(1, limit // 3)
    rows = conn.execute(
        "SELECT tick, logged_at, category, description FROM events WHERE tick > ? ORDER BY id DESC LIMIT ?",
        (since_tick, min(limit * 4, QUERY_LIMIT_MAX)),
    ).fetchall()
    raw = [
        {"tick": tick, "logged_at": logged_at, "category": category, "description": description}
        for tick, logged_at, category, description in rows
    ]
    raw = _dedupe_rumor_topics(raw)
    kept: list[dict] = []
    routine_kept = 0
    for event in raw:  # newest-first
        if event["category"] in ROUTINE_EVENT_CATEGORIES:
            if routine_kept >= routine_cap:
                continue
            routine_kept += 1
        kept.append(event)
        if len(kept) >= limit:
            break
    return kept


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
    limit = max(1, min(limit, QUERY_LIMIT_MAX))
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
    """Histogram of event categories across the retained event log — part
    of the extensive diagnostic report (`GET /diagnostics`) built for
    debugging an unattended overnight soak run: how many dialogues/
    rumors/deaths/etc. are on file, not just the recent-events tail.
    Counts are over the retained window (`Config.event_log_retention`,
    v0.71.0), not literally all-time, once pruning has kicked in on a
    very long run. See docs/DECISIONS.md, diagnostics pass."""
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
        "SELECT id FROM snapshots WHERE tick = ? LIMIT 1", (tick,)
    ).fetchone()
    if row is None:
        return None
    data = _reconstruct_snapshot_dict(conn, row[0])
    return World.from_dict(data, runtime_config)
