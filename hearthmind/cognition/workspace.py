"""Tier 7 HCA Stage B, B1 (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md
§3, Layer 3 "The Global Workspace"): the base coalition-bidding/
arbitration engine everything else in Stage B (B2's competitive
starvation, B3's real broadcast bus, B4's coalition formation, B5's
evidence-based scoring, B6's determinism guarantee, B7's learned
bidding) attaches to. Per the roadmap's own Phase 3 sequencing: "the
base workspace/arbitration engine must exist (B1) before its later
refinements can attach to anything."

Scoped to B1's own literal ask only -- "coalition bidding; one
arbitrated winner per cycle" -- deliberately NOT the full 2026-08-02
arbitration amendment's seven-factor evidence scoring (B5), coalition
MERGING of same-subject bids (B4), or learned bid gains (B7); those are
distinct, later items layered on top of this one, per the doc's own
explicit sequencing (§3.3's steps 2/3/5 vs. this module's step 1).
What ships here implements L3's own per-cycle mechanism (§3) for
steps 1, 4, 5, 6 verbatim: collect bids, pick one winner, broadcast to
subscribers, log the full competition (winner + every loser). Step 2
(coalition merge) is a no-op pass-through until B4 exists -- every bid
competes individually, so a genuinely single-bidder cycle already
behaves exactly as B4 will special-case it. Step 3's scoring is the
raw bid score alone until B5's seven-factor formula replaces it. Step
7 (measure realised value, credit it back to bidders) is B7's own
later, `learn()`-dependent addition.

**No RNG anywhere in arbitration** -- a standing HCA rule repeated at
every later stage (B6 states it as a hard determinism requirement),
honored from the start here rather than retrofitted later: `arbitrate
()`'s tie-break is deterministic (highest score; ties broken by
submission order, since `max()` is stable and returns the FIRST
element achieving the max) -- never `random.choice`. This is the "OS
scheduler for cognition" the Adaptive Runtime was always meant to have
(§3's own framing), and its determinism is what keeps a future
`scripts/verify_replay_hash.py`-style equivalence check meaningful for
the Mind layer, the same way it already is for the deterministic Body.

**Deliberately NOT wired into any real production LLM call site this
pass.** B1's own "every LLM call site converted to a bid" is real,
large, separate migration work -- this codebase's own A2 finding
counted ~78 real `_append_emergence`-adjacent call sites, and a
comparable number of independent `_schedule_llm_job` sites elsewhere,
the kind of big-bang rewrite this project's own standing "never
migrate one at a time, but never big-bang either" discipline is
explicit about doing incrementally once a pattern is proven safe. This
ships the arbitration primitive itself, verified against real
competing bids (including a real integration with A1's own
`SurpriseSpecialist`, proving this is a genuinely usable base, not a
mock-only exercise) -- the actual site-by-site migration, and B1's own
stated test ("pillar-level call share rises from 1.4% to > 15% without
raising total calls"), is real, scoped future work once this primitive
exists for that migration to land on. Same "ship the interface, wire
the first real consumer next" discipline every prior Stage A/G item in
this codebase has used."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Bid:
    """One specialist's coalition proposal for the current cycle --
    L1's own `bid()` method (§3) returns one of these, or `None` (most
    specialists bid essentially never, which is correct per L1's own
    docstring). `resolver` is what actually executes if this bid wins
    -- a plain zero-arg callable, never invoked by `GlobalWorkspace`
    itself, only by whichever caller drives `arbitrate()`'s real
    winner; kept deliberately execution-agnostic (sync or the caller's
    own async wrapping) since this module makes no assumption about
    how a real LLM call or cached-chunk/learned-model resolution
    (C3's later job) actually runs. `score` is the bid's own raw
    salience for THIS cycle -- B5's seven-factor formula is a distinct,
    later replacement for HOW a bid computes this number, not for
    anything in this module, which only ever compares whatever score
    it's handed."""
    specialist_id: str
    subject: str
    score: float
    resolver: Callable[[], Any] | None = None
    reason: str = ""


@dataclass
class CompetitionRecord:
    """One cycle's full arbitration outcome -- L3 step 6, "log the full
    competition: winner, losers, every factor's contribution, and the
    reason." `factor_contributions` is deliberately empty here (B5's
    own seven-factor breakdown doesn't exist yet) -- kept as a real
    field so B5 can populate it later without changing this record's
    shape. A genuinely empty cycle (`winner=None`) is a real, valid,
    recorded outcome, not a skipped one -- silence is itself
    information for whoever reads the history later."""
    cycle: int
    winner: Bid | None
    losers: tuple[Bid, ...]
    factor_contributions: dict = field(default_factory=dict)


COMPETITION_LOG_MAX = 200
"""Bounded history of past `CompetitionRecord`s -- same "small,
bounded, never grows without limit" discipline every other runtime-
only history in this codebase already holds to (e.g. `Scheduler.
tick_traces`, `AdaptationHistory`)."""


class GlobalWorkspace:
    """L3's own per-cycle mechanism (§3), scoped to B1's literal ask.
    "One serial channel per domain" (§3.2) -- this module doesn't
    itself enforce domain typing (that's H1's later job); a caller
    wanting per-domain isolation just constructs one `GlobalWorkspace`
    per domain, same as it would construct one per settlement or one
    per agent for a per-mind channel, per §3.1's nesting."""

    def __init__(self) -> None:
        self._pending: list[Bid] = []
        self._cycle = 0
        self.history: list[CompetitionRecord] = []

    def submit(self, bid: Bid) -> None:
        """Step 1: collect a bid for the CURRENT cycle. Never resolves
        it, never scores it against anything yet -- scoring only
        happens once `arbitrate()` runs the whole cycle's pool
        together."""
        self._pending.append(bid)

    def pending_count(self) -> int:
        return len(self._pending)

    def arbitrate(self) -> Bid | None:
        """Steps 4-6: pick exactly one winner among this cycle's
        pending bids (highest `score`; ties broken by submission
        order via `max()`'s own stability -- the first-submitted bid
        among equal scores always wins, never `random.choice`, per the
        standing "no RNG in arbitration" rule), clear the pending
        queue for the next cycle, and log the full competition (winner
        plus every loser). Returns `None` on a genuinely empty cycle --
        never fabricates a winner just to have one. Does NOT invoke the
        winner's `resolver` -- that decision belongs to the caller
        driving this cycle, since resolution may need to be awaited."""
        bids = self._pending
        self._pending = []
        self._cycle += 1
        if not bids:
            self._append_history(CompetitionRecord(cycle=self._cycle, winner=None, losers=()))
            return None
        winner = max(bids, key=lambda b: b.score)
        losers = tuple(b for b in bids if b is not winner)
        self._append_history(CompetitionRecord(cycle=self._cycle, winner=winner, losers=losers))
        return winner

    def _append_history(self, record: CompetitionRecord) -> None:
        self.history.append(record)
        if len(self.history) > COMPETITION_LOG_MAX:
            self.history = self.history[-COMPETITION_LOG_MAX:]

    def broadcast(self, winner: Bid, subscribers: list[Callable[[Bid], None]]) -> None:
        """Step 5: "broadcast the winner to every subscribed
        subsystem" -- deliberately every subscriber, not just back to
        the bidder that won, per L3's own "not just back to the
        bidder" framing (the doc's own example: "today a dream's
        result reaches one agent... under HCA it reaches Humans,
        Village and Reflection as well"). A subscriber callback that
        raises is NOT caught here -- same "never silently swallow a
        real bug" discipline `simulation/scheduler.py`'s own error-
        propagation already holds to; per-subscriber fault isolation,
        if a real production incident ever calls for it, is future
        work layered on top, not assumed away here."""
        for subscriber in subscribers:
            subscriber(winner)
