"""Tier 7 HCA Stage B, B1+B2+B3+B4 (docs/COGNITIVE-ARCHITECTURE-2026-
08-02.md §3, Layer 3 "The Global Workspace"): the base coalition-
bidding/arbitration engine everything else in Stage B (B5's evidence-
based scoring, B6's determinism guarantee, B7's learned bidding)
attaches to. Per the roadmap's own Phase 3 sequencing: "the base
workspace/arbitration engine must exist (B1) before its later
refinements can attach to anything."

**B4, the roadmap's own framing:** "coalition formation: bids naming
the same subject/region/entity merge, superadditively but sublinearly,
counting only genuinely independent bidders (two views of one
underlying reading are one bidder, not two). Test: five independent
mild corroborating bids beat one strong isolated bid on the same
cycle, and ten weak ones still lose to a genuine crisis -- both
thresholds stated in advance." `form_coalitions`/`Coalition`/`merged_
coalition_score` below are that mechanism -- see their own docstrings.
Deliberately does NOT change `GlobalWorkspace.arbitrate()`'s own
comparison this pass: B1's docstring already named step 3 (scoring) as
B5's job, not B4's ("step 3's scoring is the raw bid score... until
B5's seven-factor formula replaces it") -- B4 ships the real, tested,
STANDALONE merge mechanism step 3 will consume once it exists, same
"ship the interface, wire the first real consumer next" discipline
every prior Stage A/G/B item here has used. A caller with `bids` in
hand can call `form_coalitions(bids)` directly today; wiring it INTO
`arbitrate()`'s own comparison is B5's real integration point.

**B3, the roadmap's own framing:** "broadcast bus replacing B4['s
predecessor, the original inter-pillar messaging item]'s ten hand-
wired arrows. Test: a Nature belief measurably moves an Innovation
decision with no Nature->Innovation-specific code." `PillarBus` below
is that bus: any pillar `subscribe()`s ONCE, generically, to receive
every future winning bid this bus arbitrates -- no per-sender-pillar
branch anywhere in a subscriber's own handler, unlike `SimulationEngine
._send_pillar_message`'s ~29 real call sites (each hand-wiring one
FIXED sender/receiver PAIR, e.g. "Nature -> Village" specifically).
That older point-to-point mechanism (`Pillar.send_message`/`receive_
message`, shipped v1.9.0) is NOT removed or migrated this pass -- same
"ship the interface, wire the first real consumer next" discipline B1
used for the ~78 real LLM call sites migrating those ~29 arrows onto a
real `PillarBus` per settlement/domain is real, separate future work,
not attempted here.

Scoped to B1+B2's own literal ask only -- "coalition bidding; one
arbitrated winner per cycle" plus "starvation: the *primary* mechanism
is competitive (unbounded staleness gain)" -- deliberately NOT the full
2026-08-02 arbitration amendment's seven-factor evidence scoring (B5),
coalition MERGING of same-subject bids (B4), or learned bid gains (B7);
those are distinct, later items layered on top of this one, per the
doc's own explicit sequencing (§3.3's steps 2/3/5 vs. this module's
step 1). What ships here implements L3's own per-cycle mechanism (§3)
for steps 1, 4, 5, 6 verbatim: collect bids, pick one winner (now
staleness-weighted, B2), broadcast to subscribers, log the full
competition (winner + every loser). Step 2 (coalition merge) is a
no-op pass-through until B4 exists -- every bid competes individually,
so a genuinely single-bidder cycle already behaves exactly as B4 will
special-case it. Step 3's scoring is the raw bid score, staleness-
gained (B2), until B5's full seven-factor formula replaces it. Step 7
(measure realised value, credit it back to bidders) is B7's own later,
`learn()`-dependent addition.

**B2's staleness gain, the roadmap's own framing:** "the *primary*
mechanism is competitive (unbounded staleness gain); B2.2's bounded-
deferral floor is kept only as a hard backstop beneath it." B2.2 here
means the Adaptive Runtime's OWN already-shipped bounded-deferral
priority classes (`simulation/scheduler.py`'s `PriorityClass`/
`DEFAULT_MAX_DEFERRALS`) -- an entirely separate, untouched mechanism;
this module doesn't call into it. What ships here is the *primary*
guarantee referenced above it: a `subject` that keeps bidding and
losing has its effective score multiplied by an ever-growing,
deliberately UNBOUNDED gain (`STALENESS_GAIN_PER_CYCLE`), so it always
eventually outscores a merely-higher-raw-score rival, no matter how
large the gap -- "nothing starves on merit" (the HCA doc's own phrase,
CLAUDE.md's HCA section). The gain resets to zero the moment its
subject wins; it only accrues for a subject that actually competed and
lost THIS cycle (a subject that submits no bid this cycle is neither
penalized nor rewarded -- its staleness clock freezes, it doesn't tick
while absent). Two non-negotiable guardrails from the same HCA
amendment, both trivially honored by this module's own current scope:
staleness gain is never learnable (there is no `learn()` hook anywhere
in this module to make it one), and nothing here credits a bid's
outcome without it being measured (B7's own later, distinct concern --
this module never attempts to).

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
pass.** B1's/B2's/B3's/B4's own "every LLM call site converted to a bid" is real,
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
    it's handed. `evidence_source` (B4) names the underlying reading
    this bid is ultimately grounded in -- defaults to `None`, which
    `form_coalitions` below treats as "this bid IS its own source"
    (falls back to `specialist_id`); set it explicitly when two
    DIFFERENT specialists would otherwise bid from the exact same raw
    observation (e.g. two wrappers both reading `population_density`)
    -- B4's own "two views of one underlying reading are one bidder,
    not two" only has something real to dedupe against once a caller
    actually says so."""
    specialist_id: str
    subject: str
    score: float
    resolver: Callable[[], Any] | None = None
    reason: str = ""
    evidence_source: str | None = None


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

STALENESS_GAIN_PER_CYCLE = 0.15
"""B2's own starvation-prevention rate: each consecutive cycle a
`subject` bids and loses multiplies its NEXT effective score by an
extra `(1 + STALENESS_GAIN_PER_CYCLE)` -- deliberately unbounded (no
cap anywhere in this module), so a chronically-losing-but-real subject
always eventually outscores a rival, however large the raw-score gap,
rather than merely getting more likely to. 0.15 is a reasoned starting
point (same "no live archive to tune against yet" honesty every other
fresh constant in this codebase carries) chosen so a subject scoring
~9x below a chronic winner overtakes it within roughly 3-4 dozen
cycles, not 2 (too twitchy, corroboration would never get a fair
hearing) and not 200+ (too slow to matter against the doc's own
64k-tick soak horizon) -- re-tune from a real future soak the same way
every other reasoned-not-measured constant in this codebase already
is."""


class GlobalWorkspace:
    """L3's own per-cycle mechanism (§3), scoped to B1+B2's literal
    ask. "One serial channel per domain" (§3.2) -- this module doesn't
    itself enforce domain typing (that's H1's later job); a caller
    wanting per-domain isolation just constructs one `GlobalWorkspace`
    per domain, same as it would construct one per settlement or one
    per agent for a per-mind channel, per §3.1's nesting."""

    def __init__(self) -> None:
        self._pending: list[Bid] = []
        self._cycle = 0
        self.history: list[CompetitionRecord] = []
        self._cycles_stale: dict[str, int] = {}

    def submit(self, bid: Bid) -> None:
        """Step 1: collect a bid for the CURRENT cycle. Never resolves
        it, never scores it against anything yet -- scoring only
        happens once `arbitrate()` runs the whole cycle's pool
        together."""
        self._pending.append(bid)

    def pending_count(self) -> int:
        return len(self._pending)

    def staleness_for(self, subject: str) -> int:
        """B2's own state, made externally readable for diagnostics/
        testing without reaching into a private attribute: how many
        CONSECUTIVE cycles `subject` has bid and lost, with zero wins
        in between. `0` for a subject that has never bid, just won, or
        simply hasn't been seen yet -- all three read identically,
        since none of them is "starved" in the sense this exists to
        catch."""
        return self._cycles_stale.get(subject, 0)

    def arbitrate(self) -> Bid | None:
        """Steps 4-6: pick exactly one winner among this cycle's
        pending bids -- highest STALENESS-GAINED score (B2: `bid.score
        * (1 + STALENESS_GAIN_PER_CYCLE * cycles_stale[bid.subject])`,
        never the raw score alone); ties broken by submission order via
        `max()`'s own stability (the first-submitted bid among equal
        gained scores always wins, never `random.choice`, per the
        standing "no RNG in arbitration" rule) -- clears the pending
        queue for the next cycle, and logs the full competition (winner
        plus every loser, `Bid.score` itself untouched -- gain is
        applied only for THIS comparison, never written back onto the
        bid). The winning subject's staleness resets to 0; every real
        loser's staleness this cycle increments by 1 -- a subject that
        didn't bid at all this cycle is neither reset nor incremented,
        its clock simply doesn't run while it's silent. Returns `None`
        on a genuinely empty cycle -- never fabricates a winner just to
        have one, and touches no staleness state either. Does NOT
        invoke the winner's `resolver` -- that decision belongs to the
        caller driving this cycle, since resolution may need to be
        awaited."""
        bids = self._pending
        self._pending = []
        self._cycle += 1
        if not bids:
            self._append_history(CompetitionRecord(cycle=self._cycle, winner=None, losers=()))
            return None

        def _gained_score(b: Bid) -> float:
            return b.score * (1.0 + STALENESS_GAIN_PER_CYCLE * self._cycles_stale.get(b.subject, 0))

        winner = max(bids, key=_gained_score)
        losers = tuple(b for b in bids if b is not winner)
        self._cycles_stale[winner.subject] = 0
        for loser in losers:
            self._cycles_stale[loser.subject] = self._cycles_stale.get(loser.subject, 0) + 1
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


class PillarBus:
    """B3's own real broadcast bus. Wraps a single `GlobalWorkspace` --
    subscription is pillar-GENERIC: any pillar `subscribe()`s once,
    with one handler that works for ANY sender, and from then on
    receives every winning bid this bus arbitrates, regardless of
    which pillar submitted it. This is the direct generalization of
    `SimulationEngine._send_pillar_message`'s ~29 hand-wired arrows
    (each one a fixed, dedicated Python call naming a SPECIFIC sender
    AND a SPECIFIC receiver) into the real thing L3 always described:
    "broadcast the winner to every subscribed subsystem," a genuinely
    generic mechanism, not a growing pile of one-off pairs -- a NEW
    sender pillar reaches every existing subscriber for free, with
    zero new code at any subscriber, the property a hand-wired arrow
    can never have (a new sender there needs a brand new arrow written
    for every receiver that should hear it)."""

    def __init__(self, workspace: GlobalWorkspace | None = None) -> None:
        self.workspace = workspace if workspace is not None else GlobalWorkspace()
        self._subscribers: dict[str, Callable[[Bid], None]] = {}

    def submit(self, bid: Bid) -> None:
        """Pass-through to the underlying workspace's step 1 (collect
        a bid for the current cycle) -- `PillarBus` adds subscription
        and broadcast on top, it doesn't reimplement arbitration."""
        self.workspace.submit(bid)

    def subscribe(self, pillar_name: str, handler: Callable[[Bid], None]) -> None:
        """A pillar registers ONE handler, ONCE, to receive every
        future winning bid -- no per-sender arrow, no per-pair code,
        and critically no branch inside `handler` on `bid.specialist_
        id` naming who sent it (that would just be a hand-wired arrow
        wearing a bus's clothing). Re-subscribing under the same name
        replaces the prior handler -- a pillar holds exactly one live
        subscription at a time, same "revise in place, don't
        duplicate" discipline the rest of this codebase already
        holds to for a pillar's own persisted state."""
        self._subscribers[pillar_name] = handler

    def unsubscribe(self, pillar_name: str) -> None:
        self._subscribers.pop(pillar_name, None)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish_cycle(self) -> Bid | None:
        """The one call a caller drives once per real cycle: arbitrate
        this cycle's pending bids (B1/B2's own real mechanism,
        untouched), then broadcast the real winner to EVERY subscribed
        pillar -- INCLUDING the winning bid's own submitter, since a
        specialist hearing its own broadcast winning is itself real
        information (L3's "broadcast to every subscribed subsystem,"
        never "every subsystem except the sender"). Returns the real
        winner, or `None` on a genuinely empty cycle -- `broadcast()`
        is never called at all when there's no real winner to
        broadcast, same "never fabricate a winner just to have one"
        discipline `GlobalWorkspace.arbitrate()` already holds to."""
        winner = self.workspace.arbitrate()
        if winner is not None:
            self.workspace.broadcast(winner, list(self._subscribers.values()))
        return winner


def _independent_bids(bids: tuple[Bid, ...]) -> tuple[Bid, ...]:
    """B4's own dedup step: group by `evidence_source` (falling back to
    `specialist_id` when unset), keep only the HIGHEST-scoring bid per
    group. Two bids sharing a source are "two views of one underlying
    reading" -- the module's own literal phrase -- so only the better
    of the two survives to count as a real, independent corroborating
    voice; the weaker duplicate contributes nothing extra."""
    best_by_source: dict[str, Bid] = {}
    for bid in bids:
        source = bid.evidence_source if bid.evidence_source is not None else bid.specialist_id
        current = best_by_source.get(source)
        if current is None or bid.score > current.score:
            best_by_source[source] = bid
    return tuple(best_by_source.values())


def merged_coalition_score(bids: tuple[Bid, ...]) -> float:
    """B4's own coalition-formation formula, applied only to the
    genuinely independent subset (`_independent_bids` above) --
    "superadditively but sublinearly," the roadmap's own two-word
    spec. Uses noisy-OR combination (Pearl's canonical model for
    independent evidence toward one conclusion): `1 - product(1 -
    s_i)` over each independent bid's own score. This is exactly the
    shape the spec asks for: SUPERADDITIVE (several real independent
    readings raise the combined score higher than any single one
    could alone -- real corroboration counts) but SUBLINEAR/saturating
    (bounded strictly by 1.0 regardless of how many terms multiply in,
    so a pile of weak evidence has a hard ceiling a single strong,
    genuine reading can still clear -- "ten weak ones still lose to a
    genuine crisis"). A lone bid's own "coalition of one" reproduces
    its raw score exactly (`1 - (1 - s) == s`), matching B1's own
    documented guarantee that a genuinely single-bidder cycle behaves
    identically whether or not B4 exists."""
    independent = _independent_bids(bids)
    if not independent:
        return 0.0
    product_of_complements = 1.0
    for bid in independent:
        product_of_complements *= (1.0 - max(0.0, min(1.0, bid.score)))
    return 1.0 - product_of_complements


@dataclass(frozen=True)
class Coalition:
    """B4's own real coalition: every pending bid naming the same
    `subject` this cycle, merged. `members` keeps every raw bid
    (including a duplicate-source loser, for a full audit trail);
    `independent_members` is the deduped subset `merged_score` was
    actually computed from. A single-bid subject is still a real
    `Coalition` (of one) -- `members == independent_members ==
    (that one bid,)`, `merged_score == that bid's own raw score`."""
    subject: str
    members: tuple[Bid, ...]
    independent_members: tuple[Bid, ...]
    merged_score: float


def form_coalitions(bids: list[Bid]) -> list[Coalition]:
    """B4's own step 2 (§3's per-cycle mechanism): group this cycle's
    pending bids by `subject` -- everything naming the same subject
    forms one real `Coalition`, scored via `merged_coalition_score`.
    Bids naming DIFFERENT subjects never merge, regardless of how
    similar their content might read -- `subject` is the one real
    grouping key this module has, same as everywhere else in this
    codebase's own bid-comparison logic (`GlobalWorkspace`'s own
    staleness tracking is subject-keyed for the identical reason).
    Order of the returned list matches first-appearance order of each
    subject among `bids` -- deterministic, no RNG, same standing rule
    every sibling function in this module already holds to."""
    grouped: dict[str, list[Bid]] = {}
    for bid in bids:
        grouped.setdefault(bid.subject, []).append(bid)
    coalitions: list[Coalition] = []
    for subject, members in grouped.items():
        members_t = tuple(members)
        independent = _independent_bids(members_t)
        coalitions.append(Coalition(
            subject=subject,
            members=members_t,
            independent_members=independent,
            merged_score=merged_coalition_score(members_t),
        ))
    return coalitions
