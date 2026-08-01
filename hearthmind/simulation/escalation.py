"""B15 -- Semantic safety: the determinism guarantee (docs/HEARTHBENCH-
RUNTIME-2026-07-23.md, Part B [Hard Rule 1]). Standalone infrastructure,
same "never big-bang" discipline as every other Tier 5 Runtime module --
not wired into `simulation/engine.py`'s real LLM-pressure pacing yet.

B15.1 -- Replay-hash equivalence test in CI: ALREADY SHIPPED as
     `scripts/verify_replay_hash.py` (v1.34.102, "the safety net every
     later [runtime] change leans on") -- re-confirmed clean as part of
     this pass's own regression sweep, not rebuilt. Nothing in this
     module duplicates it.
B15.2 -- The two-part guarantee: a recorded product DECISION (the doc's
     own "[DECIDED 2026-07-23]" tag), not a build item -- Strict Body /
     Adaptive cognition-breadth / the accepted cross-machine-story
     consequence. Nothing to implement; `TWO_PART_GUARANTEE` below is a
     literal, checkable restatement of the decision so future code can
     assert against it rather than re-deriving it from prose.
B15.3 `EscalationLadder`: the doc's own named five-rung ladder (reorder/
     batch -> defer within deadline -> slow sim-time -> pause -> reduce
     cognition breadth), escalating/de-escalating exactly ONE rung per
     `observe()` call -- never skips a rung, matching B11's `demote_
     stale`/B9's timescale-gate "one step at a time" precedent. Rung 5
     is reachable ONLY from a SUSTAINED run of pressured readings while
     already sitting at rung 4 ("rungs 1-4 exhausted... not a transient
     spike") -- a lone pressured reading at rungs 1-3 escalates freely
     (per the doc's own framing, those rungs are cheap: "free, zero
     semantic effect" / "bounded, nothing dropped"), only rung 5's real
     visible degradation needs real sustained evidence. `reference_mode`
     is B15.5's hard pin -- `observe()` becomes a genuine no-op.
B15.4 `CognitionBudget`: the runtime's ENTIRE say in cognition selection
     is a bare integer count -- the dataclass has exactly one field,
     structurally incapable of naming a specific agent/pillar. "Which
     agents/pillars fill it" stays the simulation's own salience rules,
     never this module's business, per the item's own text: "Without
     this line, 'adapt to hardware' would leak world-meaning decisions
     into the scheduler."
B15.5 Reference mode: `EscalationLadder(reference_mode=True, pinned_
     rung=...)` -- a fixed execution profile (cognition-per-window,
     cadences, adaptation) used by HearthBench's world-level runs and
     any cross-machine comparison, since adaptive cognition would
     otherwise make a comparative measurement meaningless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

SUSTAINED_PRESSURE_THRESHOLD = 5


class Rung(Enum):
    REORDER_BATCH = 1
    DEFER_WITHIN_DEADLINE = 2
    SLOW_SIM_TIME = 3
    PAUSE = 4
    REDUCE_COGNITION_BREADTH = 5


_RUNG_ORDER = (
    Rung.REORDER_BATCH,
    Rung.DEFER_WITHIN_DEADLINE,
    Rung.SLOW_SIM_TIME,
    Rung.PAUSE,
    Rung.REDUCE_COGNITION_BREADTH,
)

TWO_PART_GUARANTEE = {
    "strict": "the deterministic Body is replay-identical regardless of any runtime decision -- budgets, dormancy, batching, parallelism, host",
    "adaptive": "cognition breadth may scale with the machine -- more cores means more Tier-2 agents and shorter pillar cadences, never a degraded world",
    "accepted_consequence": "the same seed on different hardware produces different stories -- sim-level A/B testing must pin the budget (reference_mode) and save files must record the profile",
}


@dataclass
class EscalationEvent:
    """B15.3's own logging requirement -- "each rung is logged"."""

    tick: int
    from_rung: Rung
    to_rung: Rung
    reason: str


@dataclass
class CognitionBudget:
    """B15.4. Exactly one field, on purpose -- a count, never a
    selection. `dataclasses.fields(CognitionBudget)` names are checked
    directly in verification to keep this a structural guarantee, not
    just a docstring promise."""

    count: int


@dataclass
class EscalationLadder:
    """B15.3/B15.5. `pinned_rung` (only meaningful with `reference_
    mode=True`) fixes the ladder's starting/permanent rung for a
    reference-profile run; `current_rung` is otherwise free to move."""

    reference_mode: bool = False
    pinned_rung: Rung = Rung.REORDER_BATCH
    current_rung: Rung = field(init=False)
    streak_at_current_rung: int = field(default=0, init=False)
    history: list = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.current_rung = self.pinned_rung

    def observe(self, tick: int, pressured: bool) -> Rung:
        """One real pressure reading. Returns the (possibly unchanged)
        current rung. `reference_mode=True` makes this a hard no-op --
        B15.5's whole point."""
        if self.reference_mode:
            return self.current_rung

        if not pressured:
            self.streak_at_current_rung = 0
            if self.current_rung is not Rung.REORDER_BATCH:
                self._deescalate_one(tick)
            return self.current_rung

        self.streak_at_current_rung += 1

        if self.current_rung is Rung.REDUCE_COGNITION_BREADTH:
            return self.current_rung

        if self.current_rung is Rung.PAUSE:
            if self.streak_at_current_rung >= SUSTAINED_PRESSURE_THRESHOLD:
                self._escalate_one(tick, "sustained pressure at the PAUSE rung -- rungs 1-4 exhausted, not a transient spike")
            return self.current_rung

        self._escalate_one(tick, "pressure detected")
        return self.current_rung

    def _escalate_one(self, tick: int, reason: str) -> None:
        idx = _RUNG_ORDER.index(self.current_rung)
        new_rung = _RUNG_ORDER[idx + 1]
        self.history.append(EscalationEvent(tick, self.current_rung, new_rung, reason))
        self.current_rung = new_rung
        self.streak_at_current_rung = 0

    def _deescalate_one(self, tick: int) -> None:
        idx = _RUNG_ORDER.index(self.current_rung)
        new_rung = _RUNG_ORDER[idx - 1]
        self.history.append(EscalationEvent(tick, self.current_rung, new_rung, "pressure cleared"))
        self.current_rung = new_rung

    def cognition_budget_for_rung(self, base_budget: int, reduced_budget: int) -> CognitionBudget:
        """B15.4. The runtime's whole contribution is this ONE number
        -- `reduced_budget` only applies at rung 5, every other rung
        leaves the simulation's own base cognition budget untouched.
        Never returns anything resembling a selection of WHICH agents/
        pillars -- that stays entirely the simulation's own call."""
        if self.current_rung is Rung.REDUCE_COGNITION_BREADTH:
            return CognitionBudget(count=reduced_budget)
        return CognitionBudget(count=base_budget)
