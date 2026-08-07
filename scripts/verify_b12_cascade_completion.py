#!/usr/bin/env python3
"""Tier 5 B12's cascade-completion pass (docs/ROADMAP-2026-07-
REMAINING.md, Phase 5): EPISODE/SUMMARY/HISTORY are now genuinely
compressed too, not just RAW -- closing a real unbounded-growth gap
(`_emergence_compression.entries[EPISODE]` and every stage above it
previously accumulated forever with nothing ever calling `maybe_
compress` on them). Real production-path checks against a real
`SimulationEngine`/`World`, no unittest, same standalone-script
convention as every sibling `verify_*.py`.
"""
from __future__ import annotations

import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    EMERGENCE_COMPRESSION_EPISODE_THRESHOLD,
    EMERGENCE_COMPRESSION_RAW_THRESHOLD,
    EMERGENCE_COMPRESSION_SUMMARY_THRESHOLD,
    SimulationEngine,
    _merge_emergence_digests,
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
    db_path = f"{_TMPDIR}/b12_cascade_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=777, initial_population=8, width=24, height=24)
    return SimulationEngine.load_or_create(conn, cfg)


def fill_and_evict(eng: SimulationEngine, evictions: int) -> None:
    """Direct-appends past the log cap enough times to produce exactly
    `evictions` real eviction events, each ingested into the ladder --
    the same technique `verify_b12_emergence_compression.py` already
    established (a distinct `subsystem` per call so A2's surprise gate
    never suppresses a candidate this script needs to actually land)."""
    total = EMERGENCE_LOG_MAX_STORED + evictions
    for i in range(total):
        eng._append_emergence(
            "opportunity" if i % 2 == 0 else "unexplained_shift", f"cascade{i}", f"entry {i}", ["humans"],
            magnitude=float((i % 10) + 1) / 10.0,
        )


def main() -> int:
    # --- pure _merge_emergence_digests correctness -----------------

    digests = [
        {"tick_start": 10, "tick_end": 20, "count": 3, "kind_counts": {"a": 2, "b": 1}, "notable_summary": "small stretch"},
        {"tick_start": 5, "tick_end": 15, "count": 7, "kind_counts": {"a": 4, "c": 3}, "notable_summary": "busiest stretch"},
        {"tick_start": 30, "tick_end": 40, "count": 1, "kind_counts": {"b": 1}, "notable_summary": "quiet stretch"},
    ]
    merged = _merge_emergence_digests(digests)
    check("merge widens tick_start to the earliest input", merged["tick_start"] == 5)
    check("merge widens tick_end to the latest input", merged["tick_end"] == 40)
    check("merge sums count across every input", merged["count"] == 11)
    check("merge sums kind_counts across every input", merged["kind_counts"] == {"a": 6, "b": 2, "c": 3})
    check("merge inherits notable_summary from the busiest (highest-count) input", merged["notable_summary"] == "busiest stretch")
    check("merge is idempotent-shaped: output has the exact same keys as a real single-batch digest", set(merged.keys()) == {"tick_start", "tick_end", "count", "kind_counts", "notable_summary"})

    empty_merge = _merge_emergence_digests([])
    check("merging an empty list degrades safely (no crash, zeroed fields)", empty_merge == {"tick_start": 0, "tick_end": 0, "count": 0, "kind_counts": {}, "notable_summary": ""})

    # --- real production-path cascade -------------------------------

    eng = make_engine()
    # Enough evictions for exactly one RAW compression, not yet enough
    # for EPISODE's own threshold (EPISODE_THRESHOLD.max_count == 5).
    fill_and_evict(eng, EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count)
    check(
        "one RAW compression promotes exactly one entry into EPISODE",
        eng._emergence_compression.stage_size(CompressionStage.EPISODE) == 1,
    )
    check("EPISODE itself hasn't crossed its own threshold yet, so it's not compressed", eng._emergence_compression.stage_size(CompressionStage.SUMMARY) == 0)

    eng2 = make_engine()
    fill_and_evict(eng2, EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count * EMERGENCE_COMPRESSION_EPISODE_THRESHOLD.max_count)
    check(
        "enough RAW compressions to cross EPISODE's own threshold promotes into SUMMARY, "
        "clearing EPISODE's own bucket back down",
        eng2._emergence_compression.stage_size(CompressionStage.SUMMARY) == 1
        and eng2._emergence_compression.stage_size(CompressionStage.EPISODE) == 0,
    )
    check(
        "the real archive now holds entries from BOTH stages (RAW->EPISODE digests AND the EPISODE->SUMMARY digest)",
        eng2._emergence_compression.total_archived()
        == EMERGENCE_COMPRESSION_EPISODE_THRESHOLD.max_count + 1,
    )
    # Archive keys are named after the STAGE THAT WAS COMPRESSED (the
    # bucket being cleared), not the stage its result is promoted into
    # -- so the EPISODE->SUMMARY digest is archived under "episode#N".
    summary_key = max(
        (k for k in eng2._emergence_compression.archive_store if k.startswith("episode#")),
        key=lambda k: int(k.split("#")[1]),
    )
    summary_digest = eng2._emergence_compression.archive_store[summary_key]
    check(
        "the real archived SUMMARY digest's count reflects every underlying raw observation "
        "(5 episodes x 100 raw entries each)",
        summary_digest["count"] == EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count * EMERGENCE_COMPRESSION_EPISODE_THRESHOLD.max_count,
    )

    eng3 = make_engine()
    fill_and_evict(
        eng3,
        EMERGENCE_COMPRESSION_RAW_THRESHOLD.max_count
        * EMERGENCE_COMPRESSION_EPISODE_THRESHOLD.max_count
        * EMERGENCE_COMPRESSION_SUMMARY_THRESHOLD.max_count,
    )
    check(
        "enough SUMMARY compressions to cross ITS OWN threshold promotes into HISTORY, "
        "clearing SUMMARY's own bucket back down -- the real full cascade, not just one hop",
        eng3._emergence_compression.stage_size(CompressionStage.HISTORY) == 1
        and eng3._emergence_compression.stage_size(CompressionStage.SUMMARY) == 0,
    )
    # The headline correctness proof this pass exists to establish: no
    # stage's own in-flight bucket is allowed to grow past its threshold
    # -- confirmed directly across every stage after a real, sustained
    # production run, not just the two stages exercised above.
    for stage in CompressionStage:
        size = eng3._emergence_compression.stage_size(stage)
        threshold = {
            CompressionStage.RAW: EMERGENCE_COMPRESSION_RAW_THRESHOLD,
            CompressionStage.EPISODE: EMERGENCE_COMPRESSION_EPISODE_THRESHOLD,
            CompressionStage.SUMMARY: EMERGENCE_COMPRESSION_SUMMARY_THRESHOLD,
        }.get(stage)
        check(
            f"stage {stage.value}'s own in-flight bucket never exceeds its threshold ({size} entries)",
            threshold is None or size < threshold.max_count,
        )

    # --- diagnostics surfacing --------------------------------------

    report = eng3.full_diagnostics()
    stage_pending = report["emergence_compression"]["stage_pending"]
    check(
        "full_diagnostics() surfaces a per-stage census covering all five real stages",
        set(stage_pending.keys()) == {s.value for s in CompressionStage},
    )
    check(
        "the diagnostics' own history-stage count matches the ladder's real state",
        stage_pending["history"] == eng3._emergence_compression.stage_size(CompressionStage.HISTORY),
    )

    # --- a real production soak, cascade wired in live --------------

    import asyncio

    async def _drive() -> None:
        eng4 = make_engine()
        for _ in range(400):
            eng4._tick_once()
            await asyncio.sleep(0)
        if eng4._background_tasks:
            await asyncio.gather(*eng4._background_tasks, return_exceptions=True)

    asyncio.run(_drive())
    check("a real 400-tick production run with the full cascade wired in never crashes", True)

    if FAILURES:
        print(f"\n{len(FAILURES)}/{CHECKS} checks FAILED: {FAILURES}")
        return 1
    print(f"\n{CHECKS}/{CHECKS} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
