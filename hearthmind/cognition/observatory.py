"""Tier 7 HCA Stage E, E2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 7,
explicit user instruction "Start E2"): workspace contents + the
losing coalitions panel — docs/COGNITIVE-ARCHITECTURE-2026-08-02.md's
own Observatory spec: "workspace contents AND the losing coalitions,"
the deliberate correction (§2.10/§3.3) over a plain priority queue,
which can only ever show a winner.

Unlike Stage C (C1/C2/C3), this one has real production data to show
from day one: B1's `GlobalWorkspace` has been wired into ~54 real
`_schedule_llm_job` call sites since Phase 3.5 (`W1`-`W4`) — every real
firing already appends a real `CompetitionRecord` to a real, bounded
`GlobalWorkspace.history`. `describe_bid`/`describe_competition`/
`workspace_snapshot` are pure presentation over that already-real
state, same "rendering pass over already-real backend state, not a new
mechanism" shape E5 used for `WorkloadForecaster.error_history`.

Honest limitation, stated up front rather than glossed over: every one
of those ~54 production sites is, by W1/W2/W3's own docstrings, a real
"coalition of one" — submit-then-immediately-arbitrate at each call
site, so `CompetitionRecord.losers` is always empty in production
today. The panel is genuinely real and genuinely wired (not a
synthetic stand-in), it just has nothing to lose against yet — the
same real gap Phase 8 (wiring a genuine multi-bid competition, e.g.
Stage C's chunk/model/LLM ladder as competing bids) would close.
`describe_competition`/`workspace_snapshot` themselves make no
assumption about coalition size, so they need no change once a real
multi-bid cycle exists."""
from __future__ import annotations

from hearthmind.cognition.workspace import Bid, CompetitionRecord, GlobalWorkspace


def describe_bid(bid: "Bid") -> dict:
    """One real bid's own fields, flattened into the shape a panel
    would render — every field read straight off the real `Bid`, never
    re-derived."""
    return {
        "specialist_id": bid.specialist_id,
        "subject": bid.subject,
        "score": round(bid.score, 4),
        "domain": bid.domain.value,
        "reason": bid.reason,
    }


def describe_competition(record: "CompetitionRecord") -> dict:
    """One real cycle's full arbitration outcome — the winner AND every
    real loser, HCA's own "workspace contents and the losing
    coalitions" ask made concrete. A genuinely empty cycle (`winner is
    None`) is reported honestly, not hidden."""
    return {
        "cycle": record.cycle,
        "winner": describe_bid(record.winner) if record.winner is not None else None,
        "losers": [describe_bid(loser) for loser in record.losers],
        "loser_count": len(record.losers),
    }


def workspace_snapshot(workspace: "GlobalWorkspace", recent: int = 20) -> list[dict]:
    """The most recent `recent` real cycles from a real `GlobalWorkspace.
    history` (already bounded at `COMPETITION_LOG_MAX`), newest last —
    same chronological-order convention every other bounded-history
    dev-console field in this codebase already uses (e.g. `learn_log_
    recent`)."""
    return [describe_competition(record) for record in workspace.history[-recent:]]
