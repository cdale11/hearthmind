#!/usr/bin/env python3
"""Standalone verification for B12 (History compression,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.history_compression import (
    CompressionLadder,
    CompressionStage,
    StageThreshold,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def join_condense(items):
    """A trivial stand-in for a real caller summarizer (chronicle/
    documentary/culture_digest/... in production) -- just enough
    structure to verify the RIGHT items were the ones condensed."""
    return "+".join(str(i) for i in items)


def check_ingest_lands_at_raw_only():
    ladder = CompressionLadder()
    ladder.ingest("event-a", tick=0)
    ladder.ingest("event-b", tick=1)
    check("ingest: new material lands in RAW", ladder.stage_size(CompressionStage.RAW) == 2)
    for stage in (CompressionStage.EPISODE, CompressionStage.SUMMARY, CompressionStage.HISTORY, CompressionStage.CULTURAL_MEMORY):
        check(f"ingest: never lands directly in {stage.value}", ladder.stage_size(stage) == 0)


def check_no_compression_below_threshold():
    ladder = CompressionLadder()
    ladder.ingest("event-a", tick=0)
    threshold = StageThreshold(max_count=5, max_age_ticks=1000)
    key = ladder.maybe_compress(CompressionStage.RAW, tick=10, threshold=threshold, condense_fn=join_condense)
    check("maybe_compress: no-op below both count and age thresholds", key is None and ladder.stage_size(CompressionStage.RAW) == 1)


def check_volume_triggered_compression_discards_and_promotes():
    ladder = CompressionLadder()
    for i in range(5):
        ladder.ingest(f"event-{i}", tick=i)
    threshold = StageThreshold(max_count=5, max_age_ticks=1_000_000)
    key = ladder.maybe_compress(CompressionStage.RAW, tick=5, threshold=threshold, condense_fn=join_condense)
    check("volume trigger: a real archive key is returned", key is not None)
    check("volume trigger: RAW bucket is genuinely cleared (real discard)", ladder.stage_size(CompressionStage.RAW) == 0)
    check("volume trigger: total_raw_discarded counts the real cleared items", ladder.total_raw_discarded == 5)
    check("volume trigger: condensed output promoted to EPISODE", ladder.stage_size(CompressionStage.EPISODE) == 1)
    condensed_item = ladder.entries[CompressionStage.EPISODE][0][1]
    check("volume trigger: the condensed content is the real joined items, not a placeholder", condensed_item == "event-0+event-1+event-2+event-3+event-4", condensed_item)
    check("volume trigger: the condensed output is archived under its key", ladder.archive_store.get(key) == condensed_item)


def check_age_triggered_compression():
    ladder = CompressionLadder()
    ladder.ingest("stale-event", tick=0)
    ladder.ingest("fresh-event", tick=90)
    threshold = StageThreshold(max_count=1000, max_age_ticks=100)
    key_before = ladder.maybe_compress(CompressionStage.RAW, tick=50, threshold=threshold, condense_fn=join_condense)
    check("age trigger: no compression before the oldest entry's age threshold", key_before is None)
    key_after = ladder.maybe_compress(CompressionStage.RAW, tick=101, threshold=threshold, condense_fn=join_condense)
    check("age trigger: compression fires once the OLDEST entry crosses the age threshold", key_after is not None)
    check("age trigger: both entries (not just the stale one) were condensed together", ladder.archive_store[key_after] == "stale-event+fresh-event")


def check_cascade_through_the_full_ladder():
    ladder = CompressionLadder()
    ladder.ingest("raw-1", tick=0)
    threshold = StageThreshold(max_count=1, max_age_ticks=1_000_000)

    tick = 0
    ladder.maybe_compress(CompressionStage.RAW, tick=tick, threshold=threshold, condense_fn=join_condense)
    check("cascade: promoted to EPISODE", ladder.stage_size(CompressionStage.EPISODE) == 1)

    ladder.maybe_compress(CompressionStage.EPISODE, tick=tick, threshold=threshold, condense_fn=join_condense)
    check("cascade: promoted to SUMMARY", ladder.stage_size(CompressionStage.SUMMARY) == 1)

    ladder.maybe_compress(CompressionStage.SUMMARY, tick=tick, threshold=threshold, condense_fn=join_condense)
    check("cascade: promoted to HISTORY", ladder.stage_size(CompressionStage.HISTORY) == 1)

    ladder.maybe_compress(CompressionStage.HISTORY, tick=tick, threshold=threshold, condense_fn=join_condense)
    check("cascade: promoted to CULTURAL_MEMORY", ladder.stage_size(CompressionStage.CULTURAL_MEMORY) == 1)

    key = ladder.maybe_compress(CompressionStage.CULTURAL_MEMORY, tick=tick, threshold=threshold, condense_fn=join_condense)
    check("cascade: CULTURAL_MEMORY has no stage above it -- condensing it archives but does not promote further", key is not None and ladder.stage_size(CompressionStage.CULTURAL_MEMORY) == 0)
    check("cascade: five real compressions -> five distinct archive keys", ladder.total_archived() == 5)


def check_prune_to_capacity_deletes_oldest_first():
    ladder = CompressionLadder()
    threshold = StageThreshold(max_count=1, max_age_ticks=1_000_000)
    keys = []
    for i in range(6):
        ladder.ingest(f"raw-{i}", tick=i)
        keys.append(ladder.maybe_compress(CompressionStage.RAW, tick=i, threshold=threshold, condense_fn=join_condense))

    check("prune: no-op when under capacity", ladder.prune_to_capacity(max_entries=100) == 0)

    pruned = ladder.prune_to_capacity(max_entries=4)
    check("prune: removes exactly the overflow count", pruned == 2, str(pruned))
    check("prune: real archive size now at the cap", ladder.total_archived() == 4)
    check("prune: the OLDEST two keys are genuinely gone", keys[0] not in ladder.archive_store and keys[1] not in ladder.archive_store)
    check("prune: the newest four keys survive", all(k in ladder.archive_store for k in keys[2:]))
    check("prune: pruned keys are also gone from the tier manager, not just the store", all(k not in ladder.archive.tiers for k in keys[:2]))


def check_handle_reconstructs_archived_detail_and_promotes_to_hot():
    ladder = CompressionLadder()
    ladder.ingest("raw-only-entry", tick=0)
    threshold = StageThreshold(max_count=1, max_age_ticks=1_000_000)
    key = ladder.maybe_compress(CompressionStage.RAW, tick=0, threshold=threshold, condense_fn=join_condense)

    handle = ladder.handle()
    value = handle.get(key, tick=500)
    check("handle: reconstruct-on-demand returns the real archived content", value == "raw-only-entry")

    from hearthmind.simulation.hierarchical_memory import Tier
    check("handle: a real fault-in read promotes the entry to hot (B11's real contract, reused not duplicated)", ladder.archive.tier_of(key) == Tier.HOT)


def check_handle_returns_none_for_pruned_detail():
    ladder = CompressionLadder()
    threshold = StageThreshold(max_count=1, max_age_ticks=1_000_000)
    ladder.ingest("will-be-pruned", tick=0)
    key = ladder.maybe_compress(CompressionStage.RAW, tick=0, threshold=threshold, condense_fn=join_condense)
    ladder.ingest("keeps-room", tick=1)
    ladder.maybe_compress(CompressionStage.RAW, tick=1, threshold=threshold, condense_fn=join_condense)
    ladder.prune_to_capacity(max_entries=1)

    handle = ladder.handle()
    value = handle.get(key, tick=100)
    check("handle: a genuinely pruned key is honestly gone, not silently reconstructed from nothing", value is None)


def main():
    check_ingest_lands_at_raw_only()
    check_no_compression_below_threshold()
    check_volume_triggered_compression_discards_and_promotes()
    check_age_triggered_compression()
    check_cascade_through_the_full_ladder()
    check_prune_to_capacity_deletes_oldest_first()
    check_handle_reconstructs_archived_detail_and_promotes_to_hot()
    check_handle_returns_none_for_pruned_detail()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
