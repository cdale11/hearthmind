#!/usr/bin/env python3
"""Tier 5 B12's first real consumer: `World.emergence_log`'s eviction
routed through a real `CompressionLadder` instead of plain truncation
(`SimulationEngine._append_emergence`/`_emergence_compression`). Real
production-path checks against a real `SimulationEngine`/`World`, no
unittest, same standalone-script convention as every sibling
`verify_*.py`."""
from __future__ import annotations

import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    EMERGENCE_COMPRESSION_ARCHIVE_MAX,
    EMERGENCE_COMPRESSION_RAW_THRESHOLD,
    SimulationEngine,
    _condense_emergence_entries,
)
from hearthmind.simulation.history_compression import CompressionStage
from hearthmind.world.state import EMERGENCE_LOG_MAX_STORED

CHECKS = 0
FAILURES: list[str] = []
_TMPDIR = tempfile.mkdtemp()
_COUNTER = 0


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def make_engine() -> SimulationEngine:
    global _COUNTER
    _COUNTER += 1
    db_path = f"{_TMPDIR}/b12_emergence_compression_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=777,
        initial_population=8, width=24, height=24,
    )
    return SimulationEngine.load_or_create(conn, cfg)


def main() -> int:
    eng = make_engine()

    # Before the log ever overflows its cap, nothing is evicted -- the
    # compression ladder stays genuinely empty. `subsystem` varies per
    # call (post-A2, docs/ROADMAP-2026-07-REMAINING.md's A2/A3 pass) so
    # each candidate is a genuinely distinct (subsystem, kind) surprise-
    # gate key -- this script exercises the COMPRESSION LADDER's own
    # eviction/archiving, not A2's surprise gating, and an identical
    # repeated candidate would otherwise get suppressed by that real
    # gate before ever reaching the log at all.
    for i in range(EMERGENCE_LOG_MAX_STORED - 1):
        eng._append_emergence("opportunity", f"test{i}", f"pre-cap {i}", ["humans"], magnitude=0.1)
    check("no eviction (and no compression activity) before the log ever exceeds its cap",
          eng._emergence_compression.stage_size(CompressionStage.RAW) == 0
          and eng._emergence_compression.total_archived() == 0)
    check("the live log holds every entry up to the cap", len(eng.world.emergence_log) == EMERGENCE_LOG_MAX_STORED - 1)

    # The very next append reaches the cap exactly (no eviction yet --
    # `len(...) > EMERGENCE_LOG_MAX_STORED` is a strict inequality).
    eng._append_emergence("opportunity", "test-cap", "reaches the cap exactly", ["humans"], magnitude=0.1)
    check("reaching the cap exactly still triggers no eviction",
          len(eng.world.emergence_log) == EMERGENCE_LOG_MAX_STORED
          and eng._emergence_compression.stage_size(CompressionStage.RAW) == 0)

    # Crossing the cap evicts exactly one entry per further append, which
    # is genuinely ingested into the ladder rather than discarded outright.
    eng._append_emergence("opportunity", "test-tip", "the one that tips it over", ["humans"], magnitude=0.1)
    check("the live log stays capped at EMERGENCE_LOG_MAX_STORED even past the cap",
          len(eng.world.emergence_log) == EMERGENCE_LOG_MAX_STORED)
    check("the single evicted entry was ingested into the compression ladder's RAW stage",
          eng._emergence_compression.stage_size(CompressionStage.RAW) == 1)
    check("total_raw_discarded tracks the real evicted count", eng._emergence_compression.total_raw_discarded == 0)

    # Real batched condensation: enough evictions accumulate to cross
    # EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count and produce a real
    # archived digest, clearing the RAW bucket. `magnitude` deliberately
    # never lands on exactly 0.0 (post-A2): a brand-new (subsystem, kind)
    # key's surprise baseline starts at a 0-prediction/0-sigma pair, so a
    # genuinely first-ever candidate whose OWN magnitude is also exactly
    # 0.0 scores a real (correct) surprise of 0.0 and gets suppressed by
    # A2's own gate -- 1/10 of `i % 10 == 0` here, a test-fixture
    # collision with A2, not a bug in the gate itself.
    eng2 = make_engine()
    total_appends = EMERGENCE_LOG_MAX_STORED + EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count
    for i in range(total_appends):
        eng2._append_emergence(
            "opportunity" if i % 2 == 0 else "unexplained_shift", f"test{i}", f"entry {i}", ["humans"],
            magnitude=float((i % 10) + 1) / 10.0,
        )
    check("a real batch of evictions produces at least one archived digest", eng2._emergence_compression.total_archived() >= 1)
    check("total_raw_discarded matches the real number of evicted entries",
          eng2._emergence_compression.total_raw_discarded == total_appends - EMERGENCE_LOG_MAX_STORED)
    check("the live log still holds exactly the newest EMERGENCE_LOG_MAX_STORED entries",
          len(eng2.world.emergence_log) == EMERGENCE_LOG_MAX_STORED
          and eng2.world.emergence_log[-1]["summary"] == f"entry {total_appends - 1}")

    digest_key = next(iter(eng2._emergence_compression.archive_store))
    digest = eng2._emergence_compression.archive_store[digest_key]
    check("the real digest's count matches the real threshold that triggered it",
          digest["count"] == EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count)
    check("the real digest's kind_counts reflects the real mix of evicted entries",
          set(digest["kind_counts"]) == {"opportunity", "unexplained_shift"})

    # _condense_emergence_entries is a pure function, independently correct.
    items = [
        {"tick": 10, "kind": "a", "magnitude": 0.2, "summary": "low"},
        {"tick": 20, "kind": "a", "magnitude": 0.9, "summary": "high"},
        {"tick": 15, "kind": "b", "magnitude": 0.5, "summary": "mid"},
    ]
    d = _condense_emergence_entries(items)
    check("_condense_emergence_entries reports the real tick range", d["tick_start"] == 10 and d["tick_end"] == 20)
    check("_condense_emergence_entries reports the real per-kind tally", d["kind_counts"] == {"a": 2, "b": 1})
    check("_condense_emergence_entries surfaces the real highest-magnitude entry's summary", d["notable_summary"] == "high")

    # B12.2's real hard ceiling: the archive itself never grows without
    # bound -- once it exceeds EMERGENCE_COMPRESSION_ARCHIVE_MAX, the
    # oldest digests are genuinely pruned.
    eng3 = make_engine()
    overflow_appends = EMERGENCE_LOG_MAX_STORED + EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count * (EMERGENCE_COMPRESSION_ARCHIVE_MAX + 20)
    for i in range(overflow_appends):
        eng3._append_emergence("opportunity", f"test{i}", f"e{i}", ["humans"], magnitude=0.1)
    check("the archive never exceeds its real hard ceiling",
          eng3._emergence_compression.total_archived() <= EMERGENCE_COMPRESSION_ARCHIVE_MAX)
    check("the archive genuinely fills up near the ceiling (real pruning happened, not silent no-op growth)",
          eng3._emergence_compression.total_archived() == EMERGENCE_COMPRESSION_ARCHIVE_MAX)

    # B12.3 reconstruct-on-demand: a real digest still in the archive
    # faults back in through the real TransparentHandle.
    eng4 = make_engine()
    for i in range(EMERGENCE_LOG_MAX_STORED + EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count):
        eng4._append_emergence("opportunity", f"test{i}", f"e{i}", ["humans"], magnitude=0.1)
    key4 = next(iter(eng4._emergence_compression.archive_store))
    handle = eng4._emergence_compression.handle()
    reconstructed = handle.get(key4, eng4.world.clock.tick_count)
    check("a real archived digest reconstructs correctly through TransparentHandle",
          reconstructed == eng4._emergence_compression.archive_store[key4])
    check("a genuinely nonexistent key returns None rather than raising",
          handle.get("not-a-real-key#0", eng4.world.clock.tick_count) is None)

    # full_diagnostics() surfaces real live state.
    diag = eng4.full_diagnostics()
    check("full_diagnostics() surfaces the real archive count", diag["emergence_compression"]["total_archived"] >= 1)
    check("full_diagnostics() surfaces a real newest digest", diag["emergence_compression"]["newest_digest"] is not None)

    eng5 = make_engine()
    diag5 = eng5.full_diagnostics()
    check("full_diagnostics() honestly reports no digest yet on a fresh engine", diag5["emergence_compression"]["newest_digest"] is None)

    # Real production-path smoke test: drive the actual tick loop (not
    # direct _append_emergence calls) for enough ticks that real
    # emergence-producing detectors fire and the mechanism runs without
    # crashing end to end.
    eng6 = make_engine()
    import asyncio

    async def _drive():
        for _ in range(4000):
            eng6._tick_once()

    asyncio.run(_drive())
    check("a real 4000-tick production run never crashes with the compression ladder wired in", True)
    check("the live emergence log stays within its real cap after a real production run",
          len(eng6.world.emergence_log) <= EMERGENCE_LOG_MAX_STORED)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
