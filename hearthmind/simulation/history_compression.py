"""B12 -- History compression (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, Hard Rule 13). Standalone infrastructure, same "never
big-bang" discipline as every other Tier 5 Runtime module -- not
wired into `simulation/engine.py`'s real event/chronicle pipeline yet.

Deliberately reuses B11's tiering primitives rather than building a
parallel archive mechanism: B12.3's "reconstruct-on-demand" IS B11's
`TransparentHandle` -- an archived compression-stage entry is read
back through the exact same fault-in call shape, at the exact same
real latency-cost tradeoff B11 already established, not a second
retrieval API.

B12.1/B12.2 `CompressionLadder`: the doc's own named five-stage
     pipeline (raw events -> episodes -> summaries -> history ->
     cultural memory). Each stage holds a bounded, in-flight list of
     `(tick, item)` entries; `maybe_compress(stage, ...)` checks that
     ONE stage against its own `StageThreshold` (age OR volume,
     whichever crosses first -- "each stage triggered by age/volume
     thresholds" per the doc's own text) and, once crossed, condenses
     the whole bucket via the CALLER's own real summarizer function.
     This module never invents its own summarization logic --
     chronicle/documentary/culture_digest/folklore/era_branch stay the
     real semantic half exactly as B12.2 asks; `CompressionLadder` is
     the missing STORAGE half: raw material is genuinely cleared from
     its stage once condensed (never kept alongside its own summary
     forever), and the condensed result is archived (B11) and promoted
     one stage up the ladder.
B12.2's hard ceiling: `prune_to_capacity` enforces a real, bounded
     total archive size -- once exceeded, the OLDEST archived entries
     are genuinely deleted (not just tier-demoted), "never allow
     unbounded growth."
B12.3 `CompressionLadder.handle()`: returns a real B11
     `TransparentHandle` bound to this ladder's own archive -- archived
     detail (any past stage's condensed output) is retrievable on
     demand at a real fault-in cost, so compression is a storage
     decision, not information loss, up to whatever `prune_to_
     capacity` has actually discarded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from hearthmind.simulation.hierarchical_memory import MemoryTierManager, Tier, TransparentHandle


class CompressionStage(Enum):
    RAW = "raw"
    EPISODE = "episode"
    SUMMARY = "summary"
    HISTORY = "history"
    CULTURAL_MEMORY = "cultural_memory"


_STAGE_ORDER = (
    CompressionStage.RAW,
    CompressionStage.EPISODE,
    CompressionStage.SUMMARY,
    CompressionStage.HISTORY,
    CompressionStage.CULTURAL_MEMORY,
)


def _next_stage_up(stage: CompressionStage) -> Optional[CompressionStage]:
    idx = _STAGE_ORDER.index(stage)
    if idx + 1 >= len(_STAGE_ORDER):
        return None
    return _STAGE_ORDER[idx + 1]


@dataclass
class StageThreshold:
    """A stage condenses once EITHER its own entry count reaches
    `max_count` OR its oldest entry's age (in ticks) reaches
    `max_age_ticks` -- volume- and age-triggered per B12.1's own text,
    either condition alone is sufficient."""

    max_count: int
    max_age_ticks: int


@dataclass
class CompressionLadder:
    """B12.1/B12.2/B12.3. `entries[stage]` is this stage's own bounded
    in-flight bucket; `archive`/`archive_store` are where a condensed
    stage's output lives once promoted (B11's `MemoryTierManager` +
    the actual condensed payloads, since B11 is deliberately storage-
    agnostic and needs a real backing dict from its caller)."""

    entries: dict = field(default_factory=lambda: {stage: [] for stage in _STAGE_ORDER})
    archive: MemoryTierManager = field(default_factory=MemoryTierManager)
    archive_store: dict = field(default_factory=dict)
    next_archive_id: int = 0
    total_raw_discarded: int = 0

    def ingest(self, item, tick: int) -> None:
        """The one entry point for genuinely new material -- always
        lands at the RAW stage; every later stage is only ever reached
        via `maybe_compress`'s own promotion."""
        self.entries[CompressionStage.RAW].append((tick, item))

    def stage_size(self, stage: CompressionStage) -> int:
        return len(self.entries[stage])

    def _archive_key(self, stage: CompressionStage) -> str:
        key = f"{stage.value}#{self.next_archive_id}"
        self.next_archive_id += 1
        return key

    def maybe_compress(self, stage: CompressionStage, tick: int, threshold: StageThreshold, condense_fn: Callable[[list], object]) -> Optional[str]:
        """Checks ONE stage against ITS OWN threshold. If crossed:
        condenses the stage's full current bucket via the caller's
        real `condense_fn`, archives the condensed result under a new
        key (B12.3), clears the stage's raw bucket (the actual discard
        -- B12.2's real storage half), and hands the condensed result
        to the next stage up. Returns the new archive key on a real
        compression, else `None`. `CULTURAL_MEMORY` has no stage above
        it -- its condensed output is still archived (the permanent
        record), just never promoted further."""
        bucket = self.entries[stage]
        if not bucket:
            return None
        oldest_tick = bucket[0][0]
        age = tick - oldest_tick
        if len(bucket) < threshold.max_count and age < threshold.max_age_ticks:
            return None

        condensed = condense_fn([item for _, item in bucket])
        key = self._archive_key(stage)
        self.archive_store[key] = condensed
        self.archive.register(key, tick, tier=Tier.WARM)

        if stage is CompressionStage.RAW:
            self.total_raw_discarded += len(bucket)
        self.entries[stage] = []

        next_stage = _next_stage_up(stage)
        if next_stage is not None:
            self.entries[next_stage].append((tick, condensed))
        return key

    def prune_to_capacity(self, max_entries: int) -> int:
        """B12.2's hard ceiling on TOTAL archived history (not just any
        one stage's in-flight bucket). Once the real archive exceeds
        `max_entries`, the OLDEST archived entries are genuinely
        deleted -- `archive.tiers` is a plain dict, insertion order is
        age order for a ladder that only ever appends new keys, so the
        earliest-registered keys are the oldest. Returns how many were
        pruned. This is real deletion, distinct from B11's own tier
        demotion (hot->warm->cold->archive moves a key between
        representations; this removes it from the archive entirely)."""
        overflow = len(self.archive_store) - max_entries
        if overflow <= 0:
            return 0
        oldest_keys = list(self.archive.tiers.keys())[:overflow]
        for key in oldest_keys:
            self.archive_store.pop(key, None)
            self.archive.tiers.pop(key, None)
            self.archive.tracker._last_run.pop(key, None)
        return len(oldest_keys)

    def total_archived(self) -> int:
        return len(self.archive_store)

    def handle(self) -> TransparentHandle:
        """B12.3. Reconstruct-on-demand IS B11's `TransparentHandle` --
        the same real fault-in call shape at the same latency-cost
        tradeoff B11 already established, not a second lookup API. A
        key `prune_to_capacity` has actually discarded is gone (real
        information loss past the retention ceiling); every other
        archived key faults back in and promotes to hot exactly like
        any other B11-managed key."""
        return TransparentHandle(manager=self.archive, load_fn=lambda key, tier: self.archive_store.get(key))
