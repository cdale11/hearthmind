"""B3 "The Attention Scheduler" (docs/MASTERCHECKLIST-2026-07-22.md,
Part B, Stage II step 6): the priority math for a "budget arbiter over
all five [pillars]" — scoped, like B1/B2 before it, to Nature (the
only pillar that exists so far). "Round-robin over five" is trivial
with one pillar (it's always Nature's turn); the real deliverable here
is the priority FORMULA itself — salience + staleness + inter-pillar
messages + player focus — computed once a genuine second pillar exists
to arbitrate against.

"Wired to the existing dynamic pacing so sim-time slows when cognition
lags" is already true globally (`SimulationEngine.llm_pressure_ratio`/
the tick-pacing slowdown, both pre-existing) and is NOT pillar-scoped —
nothing here duplicates or replaces that. What IS new: a pillar's own
backpressure tolerance now scales with its computed priority rather
than using the same flat threshold every other settlement job shares
(`_settlement_job_backpressured`) — a genuinely salient/stale/message-
carrying turn tolerates more backlog before deferring; a quiet one
defers earlier, freeing budget for turns that matter more. Never a
full bypass: the tolerance is a fraction of the same shared limit,
capped at 1.0 (never above the ordinary flat gate) — same "scale the
threshold, don't disable it" shape `DIALOGUE_BACKPRESSURE_FRACTION`/
`RUMOR_INTERPRET_BACKPRESSURE_FRACTION` already use elsewhere."""
from __future__ import annotations

STALENESS_SATURATION_TICKS = 40_000
"""Ticks since a pillar's last real turn (observe or interpret) at
which staleness maxes out at 1.0 — roughly a season and a half at the
default 15-simulated-minutes-per-tick/96-ticks-a-day pace. A pillar
that hasn't turned in this long is judged maximally overdue regardless
of how much further neglect stretches it."""

DEFAULT_SALIENCE = 0.3
"""Baseline salience when no tagged Emergence API observation exists
since the pillar's last turn (or none carried a `magnitude`) — a
genuine "nothing notable happened" reading, not zero (zero would read
as "actively uninteresting," which isn't a fact this function can
actually establish from an empty window)."""

MIN_BACKPRESSURE_FRACTION = 0.5
"""The floor a priority-0 turn's backpressure tolerance scales down
to — even the least salient/freshest/quietest pillar turn still gets
half the shared backpressure limit's worth of tolerance, never zero
(a genuinely idle pillar should still eventually get a turn, just
later than a busy one)."""


def pillar_salience(emergence_log: list[dict], pillar_name: str, since_tick: int) -> float:
    """The strongest `magnitude` among Emergence API entries tagged for
    `pillar_name` since `since_tick` (this pillar's last turn) — the
    single loudest thing this pillar would have perceived, not an
    average (a rare strong signal should read as salient even amid a
    quiet stretch, not get diluted by it). `DEFAULT_SALIENCE` when
    nothing tagged/magnituded exists in the window."""
    relevant = [
        o for o in emergence_log
        if pillar_name in o.get("pillars", ()) and o.get("tick", -1) > since_tick
    ]
    magnitudes = [o["magnitude"] for o in relevant if o.get("magnitude") is not None]
    if not magnitudes:
        return DEFAULT_SALIENCE
    return max(magnitudes)


def compute_priority(
    salience: float, staleness_ticks: int, message_count: int = 0, player_focus: float = 0.0,
) -> float:
    """Combines the doc's four named priority inputs into one 0..1
    score. Weights (salience 0.5, staleness 0.3, messages 0.15, player
    focus 0.05) favor "something genuinely interesting happened" over
    "it's just been a while," reflecting the project's standing
    "maximize emergence per LLM call" priority — mere staleness alone
    shouldn't dominate a real signal. `message_count` (B4's inter-pillar
    bus) and `player_focus` both read 0 for every pillar today (no
    second pillar exists to message from; nothing connects player
    attention to a specific pillar yet) — both terms are real and
    ready, just currently always-zero inputs, not placeholders to be
    swapped out later."""
    staleness_norm = min(1.0, max(0.0, staleness_ticks) / STALENESS_SATURATION_TICKS)
    message_norm = min(1.0, message_count / 3.0)
    player_norm = max(0.0, min(1.0, player_focus))
    priority = 0.5 * salience + 0.3 * staleness_norm + 0.15 * message_norm + 0.05 * player_norm
    return max(0.0, min(1.0, priority))


def backpressure_fraction(priority: float) -> float:
    """Maps a 0..1 priority score to a 0..1 fraction of the shared
    backpressure limit this turn tolerates before deferring —
    `MIN_BACKPRESSURE_FRACTION` at priority 0, 1.0 (the same tolerance
    every other settlement job gets) at priority 1. Linear: no
    principled reason for a curve here, and a straight line is easiest
    to reason about when re-tuning the floor later."""
    return MIN_BACKPRESSURE_FRACTION + priority * (1.0 - MIN_BACKPRESSURE_FRACTION)
