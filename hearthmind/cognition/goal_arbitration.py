"""Roadmap Phase 3, E3's "competing-goals half" (docs/ROADMAP-2026-07-
REMAINING.md, explicit user instruction "start e3"): a genuinely NEW
mechanism, not a rendering pass over already-real state like every
other Stage E item — `cognition/observatory.py`'s own docstring had
flagged this exact gap: "`llm/cognition.py`'s `fallback_goal` is a
flat sequential if-chain, never a scored competition — there is no
real Bid-based goal-vs-goal arbitration anywhere in production to
render a panel over."

This module builds that real arbitration, scoped deliberately narrow
to match `hearthmind.ml.goal_policy.GoalPolicy`'s own already-shipped
scope (Tier 6 L2.2): the same three "content" goals `fallback_goal`
resolves once every forced branch above it (survival hunger/energy,
fear/grief, materials-critical, plan-intent) has already been ruled
out. Those forced branches are real, non-negotiable OVERRIDES, not
choices to arbitrate — an agent past `SURVIVAL_HUNGER_THRESHOLD` isn't
"competing" between foraging and gathering, there is (per `cognition.
build_prompt`'s own closing text) "no real choice about it." This
module never touches that logic; it only replaces what was a flat,
population-blind `agent_id % 3` split (or an optional trained
`GoalPolicy`) for the genuinely open "what should a content agent do
today" question.

**Real competition, not decoration.** `compute_content_goal_bids`
scores SOCIALIZE/GATHER/WANDER from the exact same trait/emotion
signals `fallback_goal` already reads (`TRAIT_SOCIABILITY`/`TRAIT_
AMBITION`/`TRAIT_OPENNESS`, `EMOTION_JOY`/`EMOTION_ANGER`) — a
standout trait genuinely raises its matching goal's score, same
direction `fallback_goal`'s own trait-standout branch already used.
`arbitrate_content_goal` submits all three to a real `GlobalWorkspace`
(`cognition.workspace`, the same B1/B2 arbitration primitive every
other HCA specialist family bids into) and returns the real winner.

**Why staleness gain matters here, not just as an abstract guarantee.**
A neutral-trait agent (the common case — three near-equal raw scores)
is exactly the scenario B2's unbounded staleness gain exists for:
`GlobalWorkspace.arbitrate()`'s per-subject staleness state, keyed on
the goal name itself, makes a losing goal's gained score climb every
consecutive cycle it doesn't win — so a genuinely tied agent's daily
goal choice ROTATES over time instead of settling on one fixed branch
forever (what a flat `max()` over static scores would do), and a real
trait standout still reliably dominates its matching goal without
starving the other two outright, since staleness eventually overtakes
even a real, sustained score gap (see `staleness_win_bound`). This
replaces `agent_id % 3`'s fixed, population-wide, personality-blind
split with something that varies over an individual agent's own
history — real per-agent variety, not a caste assigned at spawn.

**Bounded to one caller-supplied `GlobalWorkspace` per call, never
created here.** This module holds no state of its own — a caller
(`SimulationEngine`) owns the workspace's lifetime, lets its real
history accumulate across many real cognition cycles for one agent,
and can render it via `cognition.observatory.workspace_snapshot`
(already generic over any `GlobalWorkspace`, so this pass needed no
new "describe" function at all)."""
from __future__ import annotations

from hearthmind.agents.agent import (
    EMOTION_ANGER,
    EMOTION_JOY,
    TRAIT_AMBITION,
    TRAIT_OPENNESS,
    TRAIT_SOCIABILITY,
    AgentGoal,
)
from hearthmind.cognition.workspace import Bid, Domain, GlobalWorkspace

GOAL_ARBITRATION_SPECIALIST_ID = "content_goal_arbitration"
"""The one `Bid.specialist_id` every candidate this module submits
shares — there is exactly one real "specialist" here (this mechanism),
proposing several candidate SUBJECTS (the goals) each cycle, not
several specialists proposing about one subject; `subject` is what
actually varies per bid."""

GOAL_ARBITRATION_BASE_SCORE = 1.0
"""Every candidate goal's floor score before any trait/emotion term is
added — chosen so the weighted terms below (max magnitude 0.5 + 0.2 =
0.7) can never drive a score to zero or below, keeping every bid
usable by B2's staleness-gain multiplier (which only ever GROWS a
positive score; a zero or negative one would break that guarantee).
A reasoned starting point, not yet tuned against a live archive, same
honesty every other fresh constant in this codebase carries."""

GOAL_ARBITRATION_TRAIT_WEIGHT = 0.5
"""How strongly a standout trait (range -1..1) tilts its matching
goal's score. Deliberately smaller than `TRAIT_NOTABLE_THRESHOLD`'s
own override strength in `fallback_goal` — this is a real competing
bid, not a hard branch, so even a strongly ambitious agent's GATHER
bid can still lose to a genuinely sustained staleness gain on the
other two, unlike the flat threshold override it replaces."""

GOAL_ARBITRATION_EMOTION_WEIGHT = 0.2
"""A smaller secondary nudge from momentary emotion (range 0..1,
already-decaying per Phase I) on top of the trait term — joy invites
company, a flash of anger makes wandering off more appealing than
seeking either people or work. Deliberately weaker than the trait
weight: a fleeting feeling should nudge, not dominate, a personality-
level tendency."""


def compute_content_goal_bids(traits: dict | None, emotions: dict | None) -> list[Bid]:
    """The three real candidate bids for a content agent's next goal —
    same trait/emotion inputs `fallback_goal`'s own trait-standout
    branch already reads, `None` degrading to an all-neutral (0.0)
    read exactly like every sibling `.get(..., 0.0)` call in this
    codebase. Each bid's `reason` is a short provenance string (the
    Observatory's own "why did this score what it scored" ask, per B5's
    `provenance` field precedent) rather than left blank."""
    traits = traits or {}
    emotions = emotions or {}
    sociability = traits.get(TRAIT_SOCIABILITY, 0.0)
    ambition = traits.get(TRAIT_AMBITION, 0.0)
    openness = traits.get(TRAIT_OPENNESS, 0.0)
    joy = emotions.get(EMOTION_JOY, 0.0)
    anger = emotions.get(EMOTION_ANGER, 0.0)
    socialize_score = (
        GOAL_ARBITRATION_BASE_SCORE
        + sociability * GOAL_ARBITRATION_TRAIT_WEIGHT
        + joy * GOAL_ARBITRATION_EMOTION_WEIGHT
    )
    gather_score = GOAL_ARBITRATION_BASE_SCORE + ambition * GOAL_ARBITRATION_TRAIT_WEIGHT
    wander_score = (
        GOAL_ARBITRATION_BASE_SCORE
        + openness * GOAL_ARBITRATION_TRAIT_WEIGHT
        + anger * GOAL_ARBITRATION_EMOTION_WEIGHT
    )
    return [
        Bid(
            specialist_id=GOAL_ARBITRATION_SPECIALIST_ID, subject=AgentGoal.SOCIALIZE.value,
            score=socialize_score, domain=Domain.WORLD,
            reason=f"sociability {sociability:+.2f}, joy {joy:.2f}",
        ),
        Bid(
            specialist_id=GOAL_ARBITRATION_SPECIALIST_ID, subject=AgentGoal.GATHER.value,
            score=gather_score, domain=Domain.WORLD,
            reason=f"ambition {ambition:+.2f}",
        ),
        Bid(
            specialist_id=GOAL_ARBITRATION_SPECIALIST_ID, subject=AgentGoal.WANDER.value,
            score=wander_score, domain=Domain.WORLD,
            reason=f"openness {openness:+.2f}, anger {anger:.2f}",
        ),
    ]


_CONTENT_GOAL_REASON = {
    AgentGoal.SOCIALIZE.value: "content, seeking company",
    AgentGoal.GATHER.value: "content, gathering materials",
    AgentGoal.WANDER.value: "content",
}
"""Mirrors `llm.cognition._CONTENT_GOAL_REASON` verbatim (kept as a
local copy rather than importing a private name across modules) — the
exact same reason text every prior fallback path already produced for
these three goals, so a caller can't tell from `reason` alone whether
this module or the old flat split chose it."""


def arbitrate_content_goal(workspace: GlobalWorkspace, traits: dict | None, emotions: dict | None) -> dict:
    """Submits all three real candidate bids to `workspace` and
    arbitrates one real cycle, returning the exact `{"goal", "reason"}`
    shape `fallback_goal`'s other branches already return. `workspace`
    is always driven to a real winner here — three bids are always
    submitted, so `arbitrate()` can only return `None` if `workspace`
    already held OTHER pending bids from an unrelated caller sharing
    it, which no real call site does (see `SimulationEngine._goal_
    workspace_for`'s own docstring); degrades to WANDER rather than
    raising in that structurally-unreachable case, matching every
    other "should never happen, but never crash a live cognition call
    over it" degrade in this codebase."""
    for bid in compute_content_goal_bids(traits, emotions):
        workspace.submit(bid)
    winner = workspace.arbitrate()
    goal = winner.subject if winner is not None else AgentGoal.WANDER.value
    return {"goal": goal, "reason": _CONTENT_GOAL_REASON.get(goal, "content")}
