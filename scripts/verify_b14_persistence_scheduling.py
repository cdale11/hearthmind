#!/usr/bin/env python3
"""Tier 5 B14 (Persistence & background work) wired to a real control
point.

Explicit user instruction ("continue B and try closing it this turn,
build as many items as possible"). `simulation/persistence_
scheduling.py`'s `SnapshotScheduler`/`SnapshotPolicy` (B14.1/B14.2)
were real, verified standalone primitives since v1.34.181 but had zero
real call sites -- `SimulationEngine._tick_once`'s snapshot cadence was
a flat `_ticks_since_snapshot >= snapshot_every_ticks` counter.

`SimulationEngine.__init__` now builds a real `SnapshotScheduler`
(`self._snapshot_scheduler`) with `max_interval_ticks = config.
snapshot_every_ticks` -- the EXACT existing worst-case durability
guarantee, unchanged -- and `min_interval_ticks = snapshot_every_ticks
// 2`, so a genuinely LLM-quiet stretch (the same real `is_quiet_
window`/daily-backlog-history signal B7.2/B8.4 already wired) can
opportunistically snapshot as often as twice the old cadence -- real,
low-risk added durability, never LESS frequent than before. `_tick_
once` now calls `self._snapshot_scheduler.due(tick, backlog_samples,
capacity)` instead of the flat counter. B14.2 (`plan()`'s FULL/
INCREMENTAL kind) is deliberately NOT consulted -- `save_snapshot` has
no real diff/incremental-write mechanism to hand a planned kind to, so
calling `plan()` here would be decorative, not real.

This script proves, standalone (no unittest): the real `SnapshotPolicy`
an engine builds itself with matches `config.snapshot_every_ticks`
exactly on both bounds; a real engine driven through genuinely BUSY
backlog history never snapshots before `max_interval_ticks` (the old
worst-case is preserved, not weakened); a real engine driven through
genuinely QUIET backlog history snapshots as early as `min_interval_
ticks` (real, opportunistic extra durability); the scheduler's own
"first check never fires" contract holds through the real engine path,
not just the standalone module; and `save_snapshot` is never called
more often than `due()` says.
"""
import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, db_name: str, snapshot_every_ticks: int = 40) -> SimulationEngine:
    db_path = f"{tmpdir}/{db_name}"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=1,
        initial_population=5, width=32, height=32,
        snapshot_every_ticks=snapshot_every_ticks,
    )
    return SimulationEngine.load_or_create(conn, cfg)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. The real policy an engine builds itself matches config
        #    exactly on the max bound (unchanged worst-case guarantee)
        #    and is genuinely tighter on the min bound.
        eng0 = make_engine(tmpdir, "policy.db", snapshot_every_ticks=40)
        policy = eng0._snapshot_scheduler.policy
        check("max_interval_ticks matches config.snapshot_every_ticks exactly", policy.max_interval_ticks == 40)
        check("min_interval_ticks is genuinely tighter (real opportunistic durability)", policy.min_interval_ticks == 20)
        check("min_interval_ticks never exceeds max_interval_ticks", policy.min_interval_ticks <= policy.max_interval_ticks)

        # 2. A genuinely BUSY backlog history: the real engine never
        #    snapshots before max_interval_ticks -- the old worst-case
        #    guarantee is preserved, not weakened.
        eng_busy = make_engine(tmpdir, "busy.db", snapshot_every_ticks=40)
        snapshotted_before_ceiling = False
        for tick in range(1, 60):
            eng_busy._recent_llm_backlog_samples.append(1000.0)  # never quiet
            eng_busy._tick_once()
            if tick < 40 and eng_busy._snapshots_saved > 0:
                snapshotted_before_ceiling = True
        check("busy backlog: never snapshots before max_interval_ticks (the old worst-case, preserved)", not snapshotted_before_ceiling)
        check("busy backlog: exactly one snapshot by tick 40 (the hard ceiling)", eng_busy._snapshots_saved == 1)

        # 3. A genuinely QUIET backlog history: the real engine can
        #    snapshot as early as min_interval_ticks -- real added
        #    durability, strictly earlier than the busy case above.
        eng_quiet = make_engine(tmpdir, "quiet.db", snapshot_every_ticks=40)
        quiet_snapshot_tick = None
        for tick in range(1, 60):
            eng_quiet._recent_llm_backlog_samples.append(0.0)  # always quiet
            eng_quiet._tick_once()
            if eng_quiet._snapshots_saved == 1 and quiet_snapshot_tick is None:
                quiet_snapshot_tick = tick
        # (+1: `ElapsedTimeTracker`'s real baseline is set on the FIRST
        # real due() call, not tick 0 -- elapsed is measured from there,
        # same "first call never fires" contract every timescale-gated
        # consumer in this codebase already holds to.)
        check(
            "quiet backlog: first snapshot lands at min_interval_ticks (+1 for the real tracker baseline), strictly before the busy case's ceiling",
            quiet_snapshot_tick == 21,
        )

        # 4. The real "first check after construction never fires"
        #    contract holds through the actual _tick_once() path, not
        #    just the standalone SnapshotScheduler unit tests.
        eng_first = make_engine(tmpdir, "first.db", snapshot_every_ticks=40)
        for _ in range(20):
            eng_first._recent_llm_backlog_samples.append(0.0)
        eng_first._tick_once()
        check("the very first real tick after construction never snapshots", eng_first._snapshots_saved == 0)

        # 5. save_snapshot is never called more often than due() says --
        #    a direct real-file check that snapshot ROWS in the db match
        #    the counter (no double-write, no silent extra write).
        # (+1: `SimulationEngine.load_or_create` itself writes a real
        # genesis snapshot at construction, before any tick -- pre-
        # existing behavior, uncounted by `_snapshots_saved` since that
        # counter only tracks snapshots taken from inside `_tick_once`.)
        row_count = eng_quiet.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        check(
            "the real snapshots table row count matches _snapshots_saved + the genesis snapshot",
            row_count == eng_quiet._snapshots_saved + 1,
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
