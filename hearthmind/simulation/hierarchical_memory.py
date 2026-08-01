"""B11 -- Hierarchical memory (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, Hard Rule 12). Standalone infrastructure, same "never
big-bang" discipline as every other Tier 5 Runtime module -- not
wired into `simulation/engine.py` or the live tick loop yet.

Deliberately reuses two already-shipped Runtime primitives rather than
building parallel ones:

  - B11.2's "how long has this key gone untouched" reuses B9.2's
    `ElapsedTimeTracker` (`simulation/timescales.py`) directly -- the
    same real-elapsed-ticks contract every other consumer of that
    class already gets, not a second idle-time tracker.
  - B11.4's "demote more aggressively under pressure" reuses B7.4's
    `GoodCitizenPolicy`/`HostProbe` (`simulation/hardware_profile.py`)
    directly -- the SAME pressure signal already drives back-off
    decisions elsewhere, not a second pressure detector.

B11.1 `Tier`/`MemoryTierManager`: four tiers (hot/warm/cold/archive),
     an explicit per-key current tier, and `demote_stale` -- a key
     idle longer than its current tier's own configured threshold
     migrates exactly one tier down per call (never skips a tier),
     matching a real migration POLICY rather than a single jump.
     Compression/on-disk persistence stay the caller's own concern --
     this module owns WHEN a key moves between tiers, never HOW a
     tier's bytes are represented (deliberately storage-agnostic, so
     it composes with whatever `persistence/database.py` mechanism a
     real integration eventually uses).
B11.2 `MemoryTierManager.demote_stale`/`touch`: access-driven
     migration -- `touch` (a real access) always promotes a key back
     to hot and resets its idle clock; a key regularly touched is
     therefore NEVER demoted, only genuinely stale ones are.
B11.3 `TransparentHandle`: `get(key, tick)` is the one call gameplay
     code would make -- it never has to know or check a key's current
     tier; a cold/archive read "faults in" via the caller's own
     `load_fn` and is promoted back to hot as a side effect of being
     read, exactly like a real access.
B11.4 `pressure_response`: demotes using a TIGHTER threshold set
     exactly when `GoodCitizenPolicy.should_back_off(probe)` is true
     -- "demote aggressively rather than letting the OS swap," reusing
     the real signal B7.4 already computes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hearthmind.simulation.timescales import ElapsedTimeTracker


class Tier(Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


_TIER_ORDER = (Tier.HOT, Tier.WARM, Tier.COLD, Tier.ARCHIVE)


def _next_tier_down(tier: Tier) -> Tier | None:
    idx = _TIER_ORDER.index(tier)
    if idx + 1 >= len(_TIER_ORDER):
        return None
    return _TIER_ORDER[idx + 1]


@dataclass
class MemoryTierManager:
    """B11.1/B11.2. Tracks each key's current tier plus (via the
    reused `ElapsedTimeTracker`) how long it has gone untouched."""

    tracker: ElapsedTimeTracker = field(default_factory=ElapsedTimeTracker)
    tiers: dict = field(default_factory=dict)

    def register(self, key: str, tick: int, tier: Tier = Tier.HOT) -> None:
        self.tiers[key] = tier
        self.tracker.mark_run(key, tick)

    def tier_of(self, key: str) -> Tier:
        return self.tiers.get(key, Tier.HOT)

    def touch(self, key: str, tick: int) -> None:
        """A real access: always promotes to hot and resets the idle
        clock, whatever tier the key was previously in."""
        self.tiers[key] = Tier.HOT
        self.tracker.mark_run(key, tick)

    def demote_stale(self, tick: int, thresholds: dict) -> list:
        """B11.2's real migration policy. `thresholds` maps a `Tier`
        to how many idle ticks a key may sit in that tier before
        demoting one step further down (a tier with no entry in
        `thresholds` never auto-demotes -- e.g. `Tier.ARCHIVE` has
        nowhere further to go). Returns the list of `(key, from_tier,
        to_tier)` migrations actually performed this call, so a caller
        can log/observe what happened without re-deriving it."""
        migrations = []
        for key, tier in list(self.tiers.items()):
            threshold = thresholds.get(tier)
            if threshold is None:
                continue
            elapsed = self.tracker.elapsed_since(key, tick)
            if elapsed is None or elapsed < threshold:
                continue
            new_tier = _next_tier_down(tier)
            if new_tier is None:
                continue
            self.tiers[key] = new_tier
            migrations.append((key, tier, new_tier))
        return migrations


@dataclass
class TransparentHandle:
    """B11.3. `load_fn(key, tier) -> value` is the caller's own
    storage-tier-specific fetch (in-memory dict lookup for hot/warm,
    a real disk read for cold/archive, etc.) -- this class's only job
    is making the CALLER of `get()` never have to know which tier a
    key was in, and ensuring a real read always counts as a real
    access for B11.2's migration policy."""

    manager: MemoryTierManager
    load_fn: object

    def get(self, key: str, tick: int):
        tier = self.manager.tier_of(key)
        value = self.load_fn(key, tier)
        self.manager.touch(key, tick)
        return value


def pressure_response(manager: MemoryTierManager, tick: int, base_thresholds: dict, aggressive_thresholds: dict, policy, probe) -> list:
    """B11.4. Reuses `hardware_profile.GoodCitizenPolicy.should_
    back_off(probe)` directly as the pressure signal -- under real
    pressure, demotion uses the tighter `aggressive_thresholds` set
    instead of `base_thresholds`, "demote aggressively rather than
    letting the OS swap." No second pressure detector is built here."""
    thresholds = aggressive_thresholds if policy.should_back_off(probe) else base_thresholds
    return manager.demote_stale(tick, thresholds)
