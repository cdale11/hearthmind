"""Tier 7 HCA Stage C, C1 (docs/ROADMAP-2026-07-REMAINING.md, Phase 5,
explicit user instruction "Start C1"): the four typed impasses as the
deliberation trigger.

Soar's decision procedure declares a typed impasse only when it cannot
choose, and creates a subgoal to resolve it (docs/COGNITIVE-
ARCHITECTURE-2026-08-02.md §2.4/§3, Layer 4). This module is that
typing, applied over signals this codebase ALREADY measures in
production — no new detection mechanism is invented, each detector
just classifies an existing real reading:

    tie        -- `hearthmind.cognition.workspace.CompetitionRecord`
                  (B1, real every real arbitration cycle since Stage B
                  shipped): the winner's score and the closest loser's
                  score are within tolerance.
    no_change  -- a real streak counter that has crossed a threshold
                  with no progress (e.g. `Institution.objective_ticks_
                  unmet`, laws.py's own real repeated-hardship-no-rule
                  counters, `EscalationLadder.streak_at_current_rung`)
                  -- HCA's own worked example is exactly this shape:
                  "590 family extinctions, no rule."
    conflict   -- `Pillar.disagrees_with(subject)` (B4, real since
                  v1.9.0): two minds hold confident, contradictory
                  theories about the recognizably same subject.
    novelty    -- `hearthmind.cognition.surprise.SurpriseSpecialist.
                  error()` (A1, real since Stage A): precision-weighted
                  surprise clears a threshold with no matching schema.

Deliberately scoped to the trigger primitive alone, per this
codebase's own "ship the interface, wire the first real consumer next"
discipline (every prior Stage A/B/G/H item used this same shape).
C1's own stated test ("every LLM call in a soak carries a named
impasse") describes the END STATE of C1+C2+C3 combined in production
-- a real, large dispatch migration that is C3's own territory, not
attempted here. What ships now: the four real, tested classifiers,
each verified directly against real production data structures
(`scripts/verify_c1_impasse.py`), ready for C2 (chunking a resolved
impasse into a cheap artifact) and C3 (cheap-resolver dispatch) to
consume."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hearthmind.cognition.workspace import CompetitionRecord

TIE_SCORE_TOLERANCE = 0.05
"""How close a winner's (gained) score and the closest loser's own
score must be for `detect_tie_from_competition` to call it a genuine
tie rather than a clean win. A reasoned starting point (same "no live
archive to tune it against yet" honesty every other fresh constant in
this codebase carries) -- small enough that an ordinary decisive
arbitration cycle (the overwhelming common case, per every real
`scripts/verify_*` soak already run) never trips it, large enough to
catch a genuinely close call rather than requiring bit-for-bit
equality."""


class ImpasseKind(Enum):
    """Soar's four types (§2.4), transferred directly -- see this
    module's own docstring table for what each one means and which
    real signal backs it."""

    TIE = "tie"
    NO_CHANGE = "no_change"
    CONFLICT = "conflict"
    NOVELTY = "novelty"


@dataclass(frozen=True)
class Impasse:
    """A real, named deliberation trigger -- never fabricated for a
    calendar tick, only produced by one of the four `detect_*`
    functions below when their own real underlying signal actually
    crosses its own real threshold. `detail` is a plain-language,
    human-readable account of WHY this specific impasse fired (the
    number that crossed the threshold, and what it was compared
    against) -- the same discipline the doc's own headline Observatory
    panel example uses ("IMPASSE(no-change) · '...' · 590 occurrences,
    no rule")."""

    kind: ImpasseKind
    subject: str
    detail: str


def detect_tie_from_competition(
    record: CompetitionRecord, tolerance: float = TIE_SCORE_TOLERANCE,
) -> Impasse | None:
    """A real `CompetitionRecord` (produced by every real `Global
    Workspace.arbitrate()` cycle since B1) is a tie when the winner's
    own score and the CLOSEST loser's own score are within `tolerance`
    of each other -- "two options score equal; the cheap layer cannot
    choose." A genuinely empty cycle (`winner is None`) or a real
    coalition-of-one (`not record.losers`, the common shape every W1-W4
    site in this codebase still produces) can never be a tie -- there
    is nothing to be tied against."""
    if record.winner is None or not record.losers:
        return None
    closest_loser_score = max(loser.score for loser in record.losers)
    if abs(record.winner.score - closest_loser_score) > tolerance:
        return None
    return Impasse(
        kind=ImpasseKind.TIE, subject=record.winner.subject,
        detail=(
            f"winner {record.winner.specialist_id!r} scored {record.winner.score:.3f} "
            f"vs. closest loser {closest_loser_score:.3f} (tolerance {tolerance})"
        ),
    )


def detect_no_change(subject: str, streak: int, threshold: int) -> Impasse | None:
    """`streak` is a real, caller-supplied count of consecutive
    observations where the same state persisted with no progress (e.g.
    `Institution.objective_ticks_unmet`) -- crossing `threshold` is
    HCA's own worked example, "590 family extinctions, no rule." This
    function classifies an existing streak; it never invents or
    increments one itself, since every real streak already has its own
    real owner and its own real reset-on-progress logic."""
    if streak < threshold:
        return None
    return Impasse(
        kind=ImpasseKind.NO_CHANGE, subject=subject,
        detail=f"{streak} consecutive occurrences with no progress (threshold {threshold})",
    )


def detect_conflict(subject: str, disagrees: bool, detail: str = "") -> Impasse | None:
    """`disagrees` is the real, caller-supplied result of `Pillar.
    disagrees_with(subject)` (B4) -- "two subsystems hold contradictory
    beliefs." This function adds no new disagreement logic of its own;
    it only names the result an impasse when it's `True`."""
    if not disagrees:
        return None
    return Impasse(
        kind=ImpasseKind.CONFLICT, subject=subject,
        detail=detail or "another mind already holds a confident, contradictory theory about this subject",
    )


def detect_novelty(subject: str, surprise: float, threshold: float) -> Impasse | None:
    """`surprise` is the real, caller-supplied result of
    `SurpriseSpecialist.error()` (A1) -- "high surprise with no
    matching schema." This function classifies an existing surprise
    reading; it never computes surprise itself, since A1's own
    precision-weighted formula already owns that."""
    if surprise < threshold:
        return None
    return Impasse(
        kind=ImpasseKind.NOVELTY, subject=subject,
        detail=f"surprise {surprise:.3f} >= threshold {threshold}",
    )
