"""Tier 7 HCA Stage H, H4 (docs/ROADMAP-2026-07-REMAINING.md, Phase 4,
explicit user instruction "Continue H4"): the Player Model as a real
OBSERVER-domain specialist -- the last item Stage H names, independent
of H2/H3 (only needed H1's domain type to exist).

CLAUDE.md's own HCA section states this plainly: "The Player Model
joins as an OBSERVER specialist -- and is deliberately NOT the Town
Consciousness's *interventions* (false memories, weather nudges,
misplaced objects), which do write world state and stay exactly as
they are; Phase G's discipline becomes partly structural, since
OBSERVER content is dev-console-only by domain rule." `World.
consciousness_player_model` (the Town Consciousness's own hidden
theory about the player, Phase N) is untouched by this item -- that
belongs to the WORLD domain (it's part of the town's own mind, and it
DOES feed real interventions). This module is a second, genuinely
distinct thing: a read-only prediction about the observer, grounded in
the one real signal already tracked about them, `World.observer_
attention` (`agent_view_counts`/`last_agent_id`/`last_seen_tick`,
already shipped for the §4/§5 items this same attention state backs).

Real L1 shape, same as every prior specialist family in this codebase:
`predict()` guesses which agent the observer will look at next (the
agent they've viewed most so far -- the simplest honest baseline);
`observe()`/`error()` score that guess the moment the NEXT real
inspection actually happens (hit=0.0, miss=1.0, same binary-error
shape A1's own `SurpriseSpecialist` established for a different
signal); `bid()` (`propose_player_model_bid` below) is what makes this
legible rather than a silent internal counter -- a real `Bid` in the
OBSERVER domain, submitted to `SimulationEngine._observer_workspace`
(a workspace dedicated to this domain alone, per H1's "domains never
compete for each other's budget," never shared with `_machine_
workspace` or any WORLD-domain workspace).

Structurally read-only by construction, not just by convention: this
module imports nothing from `hearthmind.world`/`.agents`/`.settlement`/
`.economy` -- `SPECIALIST_DOMAIN = Domain.OBSERVER` below is a real,
mechanically-checked claim (`scripts/verify_runtime_invariant.py`'s
`check_domain_write_scope()`), the same enforcement H2's MACHINE
markers already proved out. The winning bid's own resolver (built in
`SimulationEngine._record_observer_attention`, not here -- `Bid.
resolver` is deliberately execution-agnostic) only ever appends to a
bounded engine-level history for dev-console display; it never writes
`hearthmind.world`/`Settlement`/`Agent` state, verified directly in
`scripts/verify_h4_player_model.py` the same way H3 verified it for
MACHINE."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from hearthmind.cognition.workspace import Bid, Domain

SPECIALIST_DOMAIN = Domain.OBSERVER

ACCURACY_HISTORY_MAX = 200
"""Bounded (predicted, hit) pair history -- same "small, bounded,
never grows without limit" discipline every other runtime-only
history in this codebase already holds to."""


def predict_next_focus(agent_view_counts: dict) -> int | None:
    """The real `predict()`: the agent the observer has inspected most
    so far, ties broken by the smallest agent id (stable, no RNG --
    same "no randomness in arbitration/prediction" discipline the rest
    of this cognitive-architecture work already holds to). `None` when
    the observer has never inspected anyone yet -- a genuine "no
    prediction to make," not a guessed default."""
    if not agent_view_counts:
        return None
    return max(agent_view_counts, key=lambda aid: (agent_view_counts[aid], -aid))


def prediction_error(predicted: int | None, actual: int) -> float:
    """The real `error()`: 0.0 on a hit, 1.0 on a miss or an
    unresolvable prediction (`predicted is None` -- there was nothing
    to compare against, which is itself a miss, not a free pass)."""
    if predicted is None:
        return 1.0
    return 0.0 if predicted == actual else 1.0


@dataclass
class PlayerAttentionModel:
    """The specialist's own small learned state: a bounded running
    history of (predicted, hit) pairs and the derived accuracy this
    predictor has actually earned -- the real, measured signal a
    future consumer (Observatory panel, or a later real `learn()`
    pass) would use, not a placeholder. Deliberately simpler than
    `ForecastAccuracyTracker` (B8.3) -- a hit-rate over a binary
    outcome needs no baseline-vs-naive comparison, unlike a continuous
    forecast."""

    _pairs: deque = field(default_factory=lambda: deque(maxlen=ACCURACY_HISTORY_MAX))

    def record(self, predicted: int | None, actual: int) -> float:
        """Scores one real observation and records it. Returns the
        real error for this single observation (what `bid()`'s own
        `reason` reports)."""
        err = prediction_error(predicted, actual)
        self._pairs.append((predicted, err))
        return err

    def hit_rate(self) -> float | None:
        """`None` with no observations yet -- a genuine "no evidence,"
        distinct from a real measured 0% hit rate."""
        if not self._pairs:
            return None
        hits = sum(1 for _, err in self._pairs if err == 0.0)
        return hits / len(self._pairs)


def propose_player_model_bid(
    predicted_agent_id: int | None, error: float, resolver: Callable[[], None],
) -> Bid:
    """H4's real `bid()`. `subject="player_model"` names the one real
    decision this OBSERVER-domain family covers today -- a future
    second OBSERVER specialist naming a different subject would
    compete in the SAME `_observer_workspace`, the real point of a
    dedicated workspace rather than resolving inline (same reasoning
    `runtime_specialist.propose_escalation_bid` already established
    for MACHINE). `score=1.0`: flat, same placeholder every solo-
    bidder family in this codebase uses until a real second bidder
    exists to weigh against. `resolver` is the caller's own closure --
    this module never sees or touches it beyond passing it through,
    keeping this file itself provably world-state-free regardless of
    what the caller's resolver happens to do."""
    reason = (
        f"predicted agent {predicted_agent_id}" if predicted_agent_id is not None
        else "no prediction yet"
    ) + (", hit" if error == 0.0 else ", miss")
    return Bid(
        specialist_id="player_model", subject="player_model",
        score=1.0, resolver=resolver, reason=reason, domain=Domain.OBSERVER,
    )
