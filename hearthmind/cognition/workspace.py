"""Tier 7 HCA Stage B, B1+B2+B3+B4+B5+B6+B7 (docs/COGNITIVE-
ARCHITECTURE-2026-08-02.md §3, Layer 3 "The Global Workspace"): the
base coalition-bidding/arbitration engine, now with every one of its
own named refinements attached — this closes Stage B in full (only
the real production wiring, Phase 3.5's `W1`-`W3`, remains). Per the
roadmap's own Phase 3 sequencing: "the base workspace/arbitration
engine must exist (B1) before its later refinements can attach to
anything."

**B7, the roadmap's own framing:** "learning to bid from realised
outcomes (did the broadcast reduce anyone's subsequent prediction
error? did real emergence follow? was a chunk produced?), credited
back to winning coalitions and — where a counterfactual is honestly
available — to losing ones." `OutcomeLearner`/`credit_winning_
coalition`/`credit_losing_bid` below implement exactly this: a real,
bounded per-specialist running estimate of measured usefulness, fed
straight into B5's own already-real `BidFactors.historical_usefulness`
multiplicative slot — B5's own docstring named this precise gap
("LEARNING what value it should hold... is explicitly B7's job").
Deliberately the smallest real thing that makes B7 true: reuses Stage
G's own "revise a bounded scalar from real evidence, never guess"
shape rather than a full model, since the ONE number B5 needs is a
scalar, not a trained network. Both of the HCA amendment's named
guardrails hold by construction, not by convention — see `OutcomeLearner`'s
own docstring for exactly how.

**B6, the roadmap's own framing:** "arbitration determinism and the
starvation bound. Test: identical evidence produces an identical
winner across two independent process runs (the `verify_replay_
hash.py` technique applied to the workspace), no RNG appears anywhere
in the arbitration path, and a specialist that never wins on merit
provably wins within a stated bounded interval on staleness gain
alone." All three were already TRUE by construction from B1/B2 onward
(no RNG was ever imported, `arbitrate()`'s tie-break was deterministic
from the start) -- B6's real job is proving each claim mechanically
rather than trusting the module's own prose. `staleness_win_bound()`
below is the third claim made into a real closed-form guarantee (the
exact minimum consecutive-loss count before a win, not just an
empirically-observed number); `scripts/verify_b6_arbitration_
determinism.py` proves the first two via a real cross-process hash
comparison and a real AST scan for banned RNG imports.

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
pass.** B1's/B2's/B3's/B4's/B5's/B6's/B7's own "every LLM call site
converted to a bid" is real, large, separate migration work -- this codebase's own A2 finding
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
this codebase has used.

**B5, the roadmap's own framing:** "evidence-based scoring: the
seven-factor bid record (surprise, consequence, confidence,
uncertainty, urgency, staleness, historical usefulness, each with
provenance); historical usefulness as a multiplicative gain, not an
addend; uncertainty as a `+beta*sqrt(uncertainty)` exploration bonus;
staleness as an unbounded multiplier." `BidFactors`/`compute_evidence_
score`/`evidence_bid` below implement six of the seven named factors
as a real, auditable formula -- staleness, the seventh, is
deliberately NOT reproduced here: `GlobalWorkspace` already tracks and
applies it (B2), keyed by subject, at comparison time; a second
staleness field on `BidFactors` would just be redundant state a caller
could get out of sync with the workspace's own real tracking, not a
second real signal. `historical_usefulness` (multiplicative gain,
default `1.0` = neutral) is a real field a caller supplies -- LEARNING
what value it should hold from realised outcomes is explicitly B7's
job (needs Stage G's `learn()`, per the doc's own dependency), not
this module's; B5 only ships the formula that CONSUMES the value once
something learns it. `provenance` is a real field on `BidFactors` too
(a short human-readable reason per factor) -- the Observatory's own
future "why did this win" panel (E1/E2) reads it directly, so leaving
it empty is a real authoring gap for a caller, not merely optional
metadata."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class Domain(Enum):
    """Tier 7 HCA Stage H, H1 (§3.2, explicit user instruction: "Start
    phase 3.5 W1 and a parallel task of your choice with biggest
    impact" -- H1 is the first item Stage B + Stage G both closing
    genuinely unblocks): the three cognitive domains named in CLAUDE.md's
    own HCA amendment -- `WORLD` (the simulated world, read/write),
    `MACHINE` (computation/scheduling, may write ONLY tunables -- see
    `simulation/tuning.py`'s `TunableRegistry`, never `world/`/`agents/`/
    `settlement/`/`economy/` state), `OBSERVER` (the player, read-only).
    Every `Bid` below carries one -- defaulting to `WORLD`, since every
    real bid this codebase has ever submitted (Phase 3.5 W1's naming
    pilot included) is genuinely WORLD-domain, and no MACHINE/OBSERVER
    specialist exists yet to need a different default. `scripts/verify_
    runtime_invariant.py`'s new `check_domain_write_scope()` is the real
    mechanical enforcement of "MACHINE/OBSERVER may never write world
    state" -- see that function's own docstring for the actual
    mechanism (a module-level marker + an import-scope AST scan, same
    technique `scripts/verify_hearthbench_isolation.py` already
    established for a structurally identical problem: proving one part
    of this codebase never reaches into another)."""
    WORLD = "world"
    MACHINE = "machine"
    OBSERVER = "observer"


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
    actually says so. `domain` (H1) names which of the three cognitive
    domains this bid belongs to -- see `Domain`'s own docstring;
    defaults to `WORLD`, reproducing every prior bid's real behavior
    with zero call-site changes needed. `message_kind`/`message_data`
    (Phase 3.5 W4, docs/ROADMAP-2026-07-REMAINING.md) exist ONLY for
    `PillarBus`-routed inter-pillar messages -- `message_kind` carries
    `cognition.pillar.MESSAGE_KINDS` (a message's real typed category,
    e.g. "warning"/"disagreement", consumed by `SimulationEngine.
    _pillar_observe_turn`'s salience ranking, which has no other way to
    read it off a bare `Bid`); `message_data` carries the message's
    optional structured payload. Every other bid family (LLM-scheduling
    W1-W3 sites, A1's `SurpriseSpecialist`, every `scripts/verify_b*`
    fixture) leaves both at their default `None`, reproducing identical
    behavior -- same "additive field, zero call-site changes needed"
    precedent `domain` itself already set."""
    specialist_id: str
    subject: str
    score: float
    resolver: Callable[[], Any] | None = None
    reason: str = ""
    evidence_source: str | None = None
    domain: Domain = Domain.WORLD
    message_kind: str | None = None
    message_data: dict | None = None


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


def staleness_win_bound(weak_score: float, strong_score: float, gain_per_cycle: float = STALENESS_GAIN_PER_CYCLE) -> int:
    """B6's own "the starvation bound," made a real closed-form
    guarantee rather than an empirically-observed number: the EXACT
    minimum consecutive-loss count `k` at which a `weak_score` bid,
    gained by B2's own formula, first strictly exceeds a rival's real
    `strong_score` -- solving `weak_score * (1 + gain_per_cycle * k) >
    strong_score` for the smallest integer `k` that satisfies it. `0`
    when `strong_score <= weak_score` (already winning or tied with no
    staleness needed at all). Raises `ValueError` for a non-positive
    `weak_score` -- there is no finite `k` that makes zero (or a
    negative bid) exceed a positive rival, so no real bound exists to
    state. This is the module's own answer to B6's stated test ("a
    specialist that never wins on merit provably wins within a stated
    bounded interval on staleness gain alone") -- `scripts/verify_b6_
    arbitration_determinism.py` drives a real `GlobalWorkspace` and
    confirms this formula's own predicted `k` matches exactly where a
    real simulated win actually happens, for many real ratios, not
    just the one 9x example B2's own test already used."""
    if weak_score <= 0.0:
        raise ValueError("weak_score must be positive for a finite staleness bound to exist")
    if strong_score <= weak_score:
        return 0
    required = (strong_score / weak_score - 1.0) / gain_per_cycle
    return math.floor(required) + 1


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


EVIDENCE_UNCERTAINTY_BETA = 0.3
"""B5's own UCB-style exploration weight (Auer et al. 2002, the same
citation CLAUDE.md's own HCA section names) -- how much a `+beta*sqrt
(uncertainty)` bonus can add on top of a factor combination that's
already bounded to [0, 1]. 0.3 is a reasoned starting point (same "no
live archive to tune against yet" honesty every fresh constant in this
codebase carries): large enough that a genuinely maximal-uncertainty
reading (`uncertainty=1.0`, bonus `+0.3`) can meaningfully outweigh a
real but modest edge in the base factors, small enough that
uncertainty alone can never manufacture a win over a coalition with a
clearly stronger, well-understood reading (base factors near 1.0) --
re-tune from a real future soak the same way every other reasoned-not-
measured constant here already is."""


@dataclass(frozen=True)
class BidFactors:
    """B5's own six real, distinct scalars feeding one evidence score
    (the seventh, staleness, is `GlobalWorkspace`'s own tracked state,
    not reproduced here -- see the module docstring). `surprise`/
    `consequence`/`confidence`/`urgency` are each expected in [0, 1]
    and clamped defensively if not (a caller's own bug should never
    crash arbitration); `uncertainty` is likewise [0, 1] (0 = fully
    known, 1 = maximally uncertain); `historical_usefulness` is a
    positive multiplicative GAIN, not a [0, 1] score -- `1.0` is
    neutral, `>1.0` amplifies a proven-reliable source, `<1.0`
    attenuates a chronically-unreliable one, clamped at `0.0` (a gain
    can never go negative and flip a bid's own sign). `provenance` is
    a real per-factor audit trail -- one short string per factor name
    naming WHY it holds this value, not decorative metadata."""
    surprise: float
    consequence: float
    confidence: float
    urgency: float
    uncertainty: float = 0.0
    historical_usefulness: float = 1.0
    provenance: dict = field(default_factory=dict)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_evidence_score(factors: BidFactors, beta: float = EVIDENCE_UNCERTAINTY_BETA) -> float:
    """B5's own real formula, matching the roadmap's own three stated
    design rules exactly: (1) the four base factors combine as a plain
    mean (each already meant to read on the same [0, 1] scale, so
    averaging keeps the combined base on that same scale rather than
    letting factor COUNT alone inflate a score); (2) `historical_
    usefulness` is applied as a multiplicative GAIN on that base, never
    an added constant -- a proven-reliable source's own factors get
    amplified, a chronically-unreliable source's get attenuated, but
    neither can single-handedly manufacture a win the base factors
    didn't earn; (3) the `uncertainty` exploration bonus is ADDED on
    top, after the gain, per the doc's own literal `+beta*sqrt
    (uncertainty)` formula -- deliberately square-rooted (not linear),
    so the exploration bonus grows fast for a truly novel reading (low
    uncertainty -> some uncertainty) and saturates for an already-very-
    uncertain one, the same diminishing-returns shape `merged_
    coalition_score`'s own noise-OR combination (B4) already uses
    elsewhere in this module. Staleness is deliberately NOT applied
    here -- `GlobalWorkspace.arbitrate()` already multiplies whatever
    raw score this function returns by its own tracked staleness gain
    (B2) at comparison time; applying it twice would double-count the
    same signal."""
    base = (
        _clamp01(factors.surprise)
        + _clamp01(factors.consequence)
        + _clamp01(factors.confidence)
        + _clamp01(factors.urgency)
    ) / 4.0
    gained = base * max(0.0, factors.historical_usefulness)
    exploration_bonus = beta * math.sqrt(_clamp01(factors.uncertainty))
    return gained + exploration_bonus


def evidence_bid(
    specialist_id: str, subject: str, factors: BidFactors,
    resolver: Callable[[], Any] | None = None, reason: str = "",
    evidence_source: str | None = None, beta: float = EVIDENCE_UNCERTAINTY_BETA,
) -> Bid:
    """The one real construction path B5 adds: build a `Bid` whose
    `score` is `compute_evidence_score(factors, beta)` rather than a
    caller hand-picking a raw number -- every other `Bid` field (used
    by B1's arbitration, B2's staleness, B3's broadcast, B4's coalition
    merge) is untouched and passed straight through."""
    return Bid(
        specialist_id=specialist_id, subject=subject, score=compute_evidence_score(factors, beta),
        resolver=resolver, reason=reason, evidence_source=evidence_source,
    )


OUTCOME_EMA_RATE = 0.2
"""B7's own learning rate for `OutcomeLearner`'s per-specialist running
mean of measured realised outcomes -- the same "many small nudges over
many ticks, no value ever fully replaced" exponential-smoothing shape
`STALENESS_GAIN_PER_CYCLE`/`BEAUTY_VOTE_SMOOTHING` already establish
elsewhere in this codebase. One measured outcome nudges a specialist's
running mean by at most 20% of the gap to that outcome -- fast enough
that a real, sustained reliability difference shows up within a
handful of credited outcomes (matching the roadmap's own test, "invert
in rank order over a run"), slow enough that one noisy measurement
can't single-handedly flip a specialist's own standing."""

HISTORICAL_USEFULNESS_FLOOR = 0.3
HISTORICAL_USEFULNESS_CEILING = 1.7
"""The real range `OutcomeLearner.historical_usefulness_for` maps a
specialist's `[0, 1]` running outcome mean onto -- a chronically
unreliable source (mean near 0.0) attenuates to `0.3x`, a chronically
reliable one (mean near 1.0) amplifies to `1.7x`, and the exact
midpoint (`0.5`, matching a specialist with no evidence yet) maps to
`1.0` -- neutral, the same default `BidFactors.historical_usefulness`
already carries. Symmetric around neutral by construction (`(FLOOR +
CEILING) / 2 == 1.0`) so a specialist that's never been credited reads
identically to one credited only ever at exactly the midpoint -- "no
evidence" and "genuinely mixed evidence" are honestly the same
starting point, not silently biased toward amplification or
attenuation."""


class OutcomeLearner:
    """Tier 7 HCA Stage B, B7 (§3.3 step 5; explicit user instruction:
    "Start B7") -- "learning to bid from realised outcomes... credited
    back to winning coalitions and, where a counterfactual is honestly
    available, to losing ones." This is L1's `learn()` applied to the
    BIDDING POLICY specifically (per CLAUDE.md's own HCA amendment,
    "specialists learn to bid better from measured realised outcomes"),
    reusing Stage G's already-shipped shape (a bounded per-specialist
    running estimate, updated only from real measured evidence) rather
    than inventing a parallel mechanism -- `hearthmind.ml.specialist.
    LearningSpecialist`'s own `learn()` trains a model's WEIGHTS from
    replayed examples; this class trains one scalar per specialist
    (its own `historical_usefulness` gain, B5's own real multiplicative
    slot) from replayed OUTCOMES, the same "revise, never replace
    outright" ontogeny, scoped down to the one number B5 already needs.

    Two guardrails, both from the same HCA amendment CLAUDE.md records,
    and both held BY CONSTRUCTION here, not by convention: (1)
    "staleness gain is never learnable" -- this class never touches
    `GlobalWorkspace`'s own `_cycles_stale` state, has no reference to
    a `GlobalWorkspace` instance at all, and nothing in `GlobalWorkspace
    .arbitrate()` reads from an `OutcomeLearner` -- the two mechanisms
    are structurally disconnected, so a never-winning specialist's
    staleness gain literally cannot be affected by anything this class
    does, whether or not that specialist is ever credited. (2) "a bid
    is only credited when its outcome was actually measured" -- `credit
    ()` takes a real `outcome` value from the CALLER; nothing in this
    module estimates, guesses, or defaults one on a caller's behalf."""

    def __init__(self, ema_rate: float = OUTCOME_EMA_RATE) -> None:
        self._ema_rate = ema_rate
        self._outcome_mean: dict[str, float] = {}
        self._credited_count: dict[str, int] = {}

    def credit(self, specialist_id: str, outcome: float) -> float:
        """Record ONE real, measured outcome for `specialist_id` (0..1
        -- did the broadcast reduce a subscriber's later prediction
        error? did real emergence follow? was a chunk produced? --
        whatever the caller's own measurement actually is, clamped
        defensively). Never call this with an estimated/guessed value
        -- that's precisely the guardrail this class exists to hold.
        Returns the specialist's updated `historical_usefulness_for`
        gain, so a caller can immediately re-bid with the fresh value
        if it wants to."""
        outcome = _clamp01(outcome)
        prior = self._outcome_mean.get(specialist_id, 0.5)
        self._outcome_mean[specialist_id] = prior + (outcome - prior) * self._ema_rate
        self._credited_count[specialist_id] = self._credited_count.get(specialist_id, 0) + 1
        return self.historical_usefulness_for(specialist_id)

    def historical_usefulness_for(self, specialist_id: str) -> float:
        """The real value to feed `BidFactors.historical_usefulness`
        for this specialist -- `1.0` (neutral) for one never credited,
        otherwise its running outcome mean linearly remapped from
        `[0, 1]` onto `[HISTORICAL_USEFULNESS_FLOOR,
        HISTORICAL_USEFULNESS_CEILING]`."""
        mean = self._outcome_mean.get(specialist_id, 0.5)
        return HISTORICAL_USEFULNESS_FLOOR + mean * (HISTORICAL_USEFULNESS_CEILING - HISTORICAL_USEFULNESS_FLOOR)

    def credited_count(self, specialist_id: str) -> int:
        """How many real outcomes this specialist has ever been
        credited with -- `0` for one never credited, distinct from a
        specialist genuinely credited exactly at the neutral 0.5
        midpoint (both currently read `historical_usefulness_for ==
        1.0`, but only the latter has real evidence behind it)."""
        return self._credited_count.get(specialist_id, 0)


def credit_winning_coalition(learner: OutcomeLearner, coalition: Coalition, outcome: float) -> None:
    """B7's own real consumer of B4's `Coalition`: every genuinely
    independent member of a WINNING coalition corroborated the call
    that produced this cycle's real, measured `outcome` -- each of
    their specialists is credited with the same value. A duplicate-
    source loser inside `coalition.members` that didn't survive into
    `independent_members` is correctly NOT credited a second time for
    the same underlying reading, matching B4's own "two views of one
    underlying reading are one bidder, not two" discipline."""
    for bid in coalition.independent_members:
        learner.credit(bid.specialist_id, outcome)


def credit_losing_bid(learner: OutcomeLearner, bid: Bid, counterfactual_outcome: float) -> None:
    """The roadmap's own explicit second half: "where a counterfactual
    is honestly available" -- a LOSING bid's specialist can still be
    credited, but ONLY when the caller supplies a real counterfactual
    outcome (e.g. from a real sandboxed dual-fork re-running the cycle
    with this bid as the winner instead, `simulation/sandbox.py`'s
    existing machinery) -- this function never fabricates one on its
    own, same guardrail `OutcomeLearner.credit` itself already holds."""
    learner.credit(bid.specialist_id, counterfactual_outcome)
