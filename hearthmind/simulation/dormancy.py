"""Tier 5 B4 — Dormancy.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rule 4]: entities
and subsystems that aren't currently mattering shouldn't cost anything
to simulate. `DormancyManager` is the generic lifecycle machinery; it
knows nothing about any real Hearthmind entity.

**Not wired into the live tick loop, and B4.2's named real candidates
(forgotten traditions, inactive settlements, distant wildlife, unused
ideas, idle institutions) are NOT attempted this pass** — each is a
real touch to actual gameplay code (`world/`, `agents/`, `settlement/`)
needing its own sleep/wake criteria and live verification, the same
"one subsystem at a time, never big-bang" discipline every prior B-item
has held to. This module ships the general mechanism + B4.3's
lossless-wake contract + B4.4's chaos-test technique, demonstrated
against a synthetic entity — real migration remains open future work.

**B4.1's "state compressed" (dormant/archived state gets a smaller
footprint) explicitly NOT built** — that's B12 (state compression),
which doesn't exist yet. Same honest-placeholder discipline as B2.1's
"adaptive (B6)": `DormancyManager` tracks lifecycle state and elapsed
time faithfully; it does not compress anything.
"""
from __future__ import annotations

from enum import Enum


class DormancyState(Enum):
    ACTIVE = "active"
    DROWSY = "drowsy"
    DORMANT = "dormant"
    ARCHIVED = "archived"


# States in which an entity receives ZERO scheduled work (B4.1's own
# definition: "Dormant = zero scheduled work"). DROWSY is deliberately
# NOT included — the doc's own spectrum implies drowsy still runs, just
# not at full attention (B2.4's attention-follows-change would be the
# real lever for that once it exists; until then DROWSY is scheduled
# exactly like ACTIVE).
_UNSCHEDULED_STATES = frozenset({DormancyState.DORMANT, DormancyState.ARCHIVED})


class DormancyManager:
    """B4.1's `active -> drowsy -> dormant -> archived` lifecycle, with
    B4.3's lossless-wake contract baked into the API itself: `wake()`
    is the ONLY way to leave DORMANT/ARCHIVED, and it always returns
    the real elapsed-tick gap the entity was unscheduled for — a
    caller can't accidentally "wake and pretend nothing happened,"
    since ignoring the return value is a choice the caller has to make
    explicitly, not something the API defaults to.
    """

    def __init__(self) -> None:
        self._state: dict[str, DormancyState] = {}
        self._since_tick: dict[str, int] = {}

    def register(self, entity_id: str, tick: int) -> None:
        self._state[entity_id] = DormancyState.ACTIVE
        self._since_tick[entity_id] = tick

    def state_of(self, entity_id: str) -> DormancyState:
        return self._state.get(entity_id, DormancyState.ACTIVE)

    def is_scheduled(self, entity_id: str) -> bool:
        return self.state_of(entity_id) not in _UNSCHEDULED_STATES

    def sleep(self, entity_id: str, tick: int, target: DormancyState = DormancyState.DORMANT) -> None:
        """B4.2's sleep criterion transitions here — this method is
        deliberately agnostic to WHY (forgotten tradition, inactive
        settlement, ...); that judgment belongs to the real candidate
        system, not this generic manager."""
        if target is DormancyState.ACTIVE:
            raise ValueError("sleep() cannot target ACTIVE — use wake() to become active")
        current = self.state_of(entity_id)
        if current in _UNSCHEDULED_STATES and target in _UNSCHEDULED_STATES:
            return  # already unscheduled in some form -- no-op, don't reset the clock
        self._state[entity_id] = target
        self._since_tick[entity_id] = tick

    def wake(self, entity_id: str, tick: int) -> int:
        """B4.2's wake trigger (event on a subscribed channel, player
        attention, scheduled review) fires this. Returns the real
        elapsed-tick gap since the entity went DORMANT/ARCHIVED — the
        caller is expected to integrate over that gap deterministically
        (B4.3), not just resume as if the gap never happened. Waking an
        already-ACTIVE/DROWSY entity is a safe no-op returning 0 —
        there's nothing to catch up on."""
        current = self.state_of(entity_id)
        if current not in _UNSCHEDULED_STATES:
            self._state[entity_id] = DormancyState.ACTIVE
            return 0
        since = self._since_tick.get(entity_id, tick)
        elapsed = max(0, tick - since)
        self._state[entity_id] = DormancyState.ACTIVE
        self._since_tick[entity_id] = tick
        return elapsed
