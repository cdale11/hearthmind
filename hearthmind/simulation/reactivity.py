"""Tier 5 B3.1/B3.2 — dirty tracking and the event bus.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rule 3]: two
deliberately distinct reactivity primitives answering two different
questions. `DirtyTracker` answers "has this data changed since I last
looked" (state-based, persistent per-key versions). `EventBus` answers
"did this specific thing just happen" (signal-based, consumed once per
tick then gone). B1's `Task.reads`/`.writes`/`.trigger`/`.event_types`
are what a declared task uses to hook into either.

**Not wired into the live tick loop yet** — same discipline as B1/B2.
`simulation/scheduler.py`'s `Scheduler` is the one real consumer of
both classes so far, itself still only exercised against synthetic
tasks.
"""
from __future__ import annotations

from collections.abc import Iterable


class DirtyTracker:
    """B3.1: every declared `writes[]` marks its targets dirty; a task
    whose `reads[]` are all clean and whose trigger is `ON_DIRTY`
    simply doesn't run — "the single biggest CPU win available," per
    the item's own text.

    A monotonic per-key VERSION counter (not a plain boolean flag) is
    what lets several independent `ON_DIRTY` readers each observe the
    same write exactly once, on their own schedule, without racing
    each other to clear a shared flag first — reader A consuming the
    change must never hide it from reader B, which is exactly what a
    single "dirty bit" cleared-on-read would do.
    """

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def mark_written(self, keys: Iterable[str]) -> None:
        for key in keys:
            self._versions[key] = self._versions.get(key, 0) + 1

    def version(self, key: str) -> int:
        return self._versions.get(key, 0)

    def is_dirty_for(self, reads: Iterable[str], observed: dict[str, int]) -> bool:
        """True if any of `reads` has advanced past what `observed` (a
        per-task key->version snapshot, owned by the caller) last saw."""
        return any(self.version(key) > observed.get(key, 0) for key in reads)

    def mark_observed(self, reads: Iterable[str], observed: dict[str, int]) -> None:
        """Snapshot the current version of every read key into
        `observed`, called once a reader has actually run and seen the
        current state — so the same write doesn't re-trigger it again
        next tick with nothing new to react to."""
        for key in reads:
            observed[key] = self.version(key)


class EventBus:
    """B3.2: subsystems emit typed events, `ON_EVENT` tasks subscribe —
    replaces "check every tick whether something happened" with a real
    publish/subscribe signal. Deliberately one-shot: `publish(...)`
    queues an event type for the CURRENT tick only; `clear()` (called
    by the scheduler at tick end) drops it, so an `ON_EVENT` task fires
    on the tick the event was published and never again for that same
    occurrence — unlike `DirtyTracker`'s persistent versions, there is
    no "still dirty" concept for a discrete happened-or-didn't event.
    """

    def __init__(self) -> None:
        self._pending: set[str] = set()

    def publish(self, event_type: str) -> None:
        self._pending.add(event_type)

    def is_pending(self, event_types: Iterable[str]) -> bool:
        return bool(self._pending.intersection(event_types))

    def clear(self) -> None:
        self._pending.clear()
