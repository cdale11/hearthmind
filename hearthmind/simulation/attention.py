"""B2.4 -- Attention-follows-change (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B [Hard Rule 9]). Standalone infrastructure, same
"never big-bang" discipline as every other Tier 5 Runtime module --
not wired into `simulation/engine.py`'s real tick loop yet.

This item's own text was explicitly left unbuilt at B2's own pass
("requires timescales and locality machinery 'to be honest' -- would
be a guess dressed as a feature otherwise") until both existed for
real. Both now do (B9's `TimescaleLadder`, shipped v1.34.175; B10's
`RegionGrid`/`region_key`, shipped v1.34.177) -- this closes the gap
by reusing them directly, plus B3's dirty-tracking shape, rather than
inventing a fourth "activity" mechanism:

  - B3.1's `DirtyTracker` established "a write bumps a real counter,
    not a guessed heuristic" -- `RegionActivityTracker` applies the
    same idea at REGION granularity (any write tagged via B10's own
    `region_key` bumps that region's activity), with exponential decay
    so activity fades back toward zero once a region goes quiet again.
  - B9.1's `TimescaleLadder.floor_for` supplies the real, non-
    negotiable floor -- a region can never be revisited faster than
    its own declared timescale allows, no matter how much real change
    it has seen. "Attention follows change" only ever COMPRESSES an
    interval toward that floor or STRETCHES it toward a configured
    ceiling; it never breaks the floor, verified directly.
  - B9.2's `ElapsedTimeTracker` is reused unmodified for "how long
    since this region was actually checked," exactly like `TimescaleGate`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.simulation.timescales import ElapsedTimeTracker, TimescaleLadder

DEFAULT_CEILING_MULTIPLIER = 3.0
DEFAULT_MAX_ACTIVITY_FOR_FULL_COMPRESSION = 5.0


@dataclass
class RegionActivityTracker:
    """Aggregates real writes into a per-region activity score with
    exponential decay (`decay_half_life_ticks`) -- a region hit by many
    recent writes reads high; one that hasn't changed in a while decays
    back toward zero on its own, without needing an explicit reset."""

    decay_half_life_ticks: float
    _last_touch_tick: dict = field(default_factory=dict)
    _activity: dict = field(default_factory=dict)

    def _decay_to(self, region_id, tick: int) -> None:
        last = self._last_touch_tick.get(region_id)
        if last is None or tick <= last:
            return
        elapsed = tick - last
        half_lives = elapsed / self.decay_half_life_ticks
        self._activity[region_id] = self._activity.get(region_id, 0.0) * (0.5 ** half_lives)
        self._last_touch_tick[region_id] = tick

    def record_write(self, region_id, tick: int) -> None:
        """A real write touched this region this tick -- same "a write
        is the ground truth" discipline B3.1's `DirtyTracker` already
        established, applied at region granularity."""
        self._decay_to(region_id, tick)
        self._activity[region_id] = self._activity.get(region_id, 0.0) + 1.0
        self._last_touch_tick[region_id] = tick

    def activity_score(self, region_id, tick: int) -> float:
        self._decay_to(region_id, tick)
        return self._activity.get(region_id, 0.0)


def attention_interval(
    ladder: TimescaleLadder,
    timescale: str,
    activity_score: float,
    max_activity_for_full_compression: float = DEFAULT_MAX_ACTIVITY_FOR_FULL_COMPRESSION,
    ceiling_multiplier: float = DEFAULT_CEILING_MULTIPLIER,
) -> int:
    """The real compress/stretch rule: `floor` (B9's own real
    calendar-derived floor for `timescale`) is the hard minimum, never
    violated regardless of activity. `ceiling` (`floor *
    ceiling_multiplier`) is how far a genuinely QUIET region's real
    check interval may stretch. Activity linearly interpolates between
    them -- zero activity means the full ceiling, activity at or above
    `max_activity_for_full_compression` means the full floor."""
    floor = ladder.floor_for(timescale)
    ceiling = floor * ceiling_multiplier
    if max_activity_for_full_compression <= 0:
        fraction = 0.0
    else:
        fraction = min(1.0, max(0.0, activity_score / max_activity_for_full_compression))
    interval = ceiling - fraction * (ceiling - floor)
    return max(floor, int(round(interval)))


@dataclass
class RegionAttentionGate:
    """Combines `RegionActivityTracker` + `TimescaleLadder` +
    `ElapsedTimeTracker` into the one call a real per-region scheduled
    task would make -- the direct region-scoped counterpart to B9's
    own `TimescaleGate.check`, with a DYNAMIC (activity-compressed)
    interval instead of a fixed one."""

    ladder: TimescaleLadder
    activity: RegionActivityTracker
    tracker: ElapsedTimeTracker = field(default_factory=ElapsedTimeTracker)
    max_activity_for_full_compression: float = DEFAULT_MAX_ACTIVITY_FOR_FULL_COMPRESSION
    ceiling_multiplier: float = DEFAULT_CEILING_MULTIPLIER

    def _tracker_key(self, region_id) -> str:
        return f"attention@{region_id}"

    def check(self, region_id, timescale: str, tick: int) -> tuple:
        """Returns `(due, elapsed_ticks)`. A region with no prior
        baseline establishes one now and reports not due yet -- same
        "no real history to integrate from" contract `TimescaleGate`
        already holds."""
        key = self._tracker_key(region_id)
        elapsed = self.tracker.elapsed_since(key, tick)
        if elapsed is None:
            self.tracker.mark_run(key, tick)
            return False, 0

        interval = attention_interval(
            self.ladder, timescale, self.activity.activity_score(region_id, tick),
            self.max_activity_for_full_compression, self.ceiling_multiplier,
        )
        if elapsed >= interval:
            self.tracker.mark_run(key, tick)
            return True, elapsed
        return False, elapsed
