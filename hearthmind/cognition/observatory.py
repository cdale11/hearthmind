"""Tier 7 HCA Stage E, E2/E3 (docs/ROADMAP-2026-07-REMAINING.md, Phase
7): the workspace + memory-activation halves of the Cognitive
Observatory.

**E2** (explicit user instruction "Start E2"): workspace contents +
the losing coalitions panel — docs/COGNITIVE-ARCHITECTURE-2026-08-02.
md's own Observatory spec: "workspace contents AND the losing
coalitions," the deliberate correction (§2.10/§3.3) over a plain
priority queue, which can only ever show a winner.

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
multi-bid cycle exists.

**E3, memory-activation half** (explicit user instruction "Start E3"):
`describe_memory_activation` is a real, live read of D1's ACT-R
formula (`hearthmind.cognition.activation.memory_activation`) applied
to one agent's own real `memories`/`memory_salience`/`memory_ticks`/
`memory_causes` — "what's active in this agent's declarative memory
right now," ranked, not just the newest slice. Real production state
(`_remember` stamps every one of these fields on every real memory,
unconditionally, whether or not `retrieve_relevant_memories` is ever
called for that agent) — a genuine rendering pass, same as E2.
Deliberately scored with `relevance=0.0` (no live retrieval context to
compare against, unlike a real `retrieve_relevant_memories` call) —
this is a standing snapshot of what's active, not an answer to a
specific query.

**E3, competing-goals half: NOT shipped this pass, stated honestly.**
Investigated first, not assumed: this codebase's real per-agent goal
selection (`llm/cognition.py`'s `fallback_goal`) is a flat sequential
if-chain, never a scored competition — there is no real Bid-based
goal-vs-goal arbitration anywhere in production to render a panel
over. Building one would be a genuinely NEW mechanism (a per-agent
`GlobalWorkspace` over candidate goals with real utilities), not a
presentation pass over already-real state like every other E-item
shipped so far — flagged as real, distinct future work rather than
forced through as a fabricated panel over numbers nothing computes
today.

**E4** (explicit user instruction "Start E4"): the "learning chart" —
HCA's own headline falsification test (§8 in the doc's own words):
"deliberative cost per unit of emergence must FALL as a world
matures... if LLM calls fall but emergence falls proportionally,
impasse-gating is just starvation with extra steps." `compute_
deliberation_sample` is the real math one live sample needs — it takes
two already-real cumulative counters at two points in time (never a
synthetic proxy): `CognitionRunner.calls_succeeded` (a call that
genuinely happened and returned a real answer — the real deliberative
cost paid) and `World.next_emergence_id` (A2's own surprise-gated
counter — it only advances once a candidate clears the precision-
weighted surprise threshold, so this is real emergence, never routine
noise inflating the count). `SimulationEngine._maybe_sample_
deliberation_emergence` is the real daily production sampler feeding a
bounded live history — see that method's own docstring."""
from __future__ import annotations

from typing import Any

from hearthmind.cognition.activation import memory_activation
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


def describe_memory_activation(agent: "Any", current_tick: int, top_n: int = 10) -> list[dict]:
    """A real, live snapshot of one agent's declarative memory
    activation — D1's ACT-R `memory_activation` formula applied to
    every real entry in `agent.memories`, ranked highest-first.

    Every input is read straight off real, already-populated `Agent`
    state (`memory_salience`/`memory_ticks`/`memory_causes`, all
    index-aligned with `memories` per D1's own persisted-field
    discipline) — no synthetic stand-in. `relevance=0.0` throughout:
    this is a standing "what's active right now" reading, not a scored
    answer to a specific retrieval query (a real `retrieve_relevant_
    memories` call supplies its own real relevance term instead).
    Bounded to the top `top_n` — the same "don't dump an unbounded list
    into a dev-console panel" discipline `workspace_snapshot`'s own
    `recent` bound already holds."""
    entries = []
    for i, text in enumerate(agent.memories):
        salience = agent.memory_salience[i] if i < len(agent.memory_salience) else 0.0
        formed_at = agent.memory_ticks[i] if i < len(agent.memory_ticks) else current_tick
        causal_present = bool(agent.memory_causes[i]) if i < len(agent.memory_causes) else False
        score = memory_activation(
            [formed_at], current_tick, salience=salience, relevance=0.0, causal_present=causal_present,
        )
        entries.append({
            "text": text,
            "activation": round(score, 4),
            "salience": round(salience, 4),
            "age_ticks": max(0, current_tick - formed_at),
            "causal_link": causal_present,
        })
    entries.sort(key=lambda e: -e["activation"])
    return entries[:top_n]


def compute_deliberation_sample(
    tick: int, prev_tick: int,
    calls_succeeded: int, prev_calls_succeeded: int,
    emergence_total: int, prev_emergence_total: int,
) -> dict | None:
    """One real E4 "learning chart" sample — deliberative calls and
    real emergence, both converted to a rate per 1,000 ticks over the
    real elapsed window since the previous sample, plus §8's own
    headline falsification-test ratio (`cost_per_emergence`: how many
    real deliberative calls it took per unit of real emergence this
    window — the number that should trend DOWN as a world matures).

    Every input is a real cumulative counter read at two points in
    time; deltas are clamped at 0 (a counter can only ever grow, but a
    caller passing stale/reordered snapshots shouldn't produce a
    fabricated negative rate). Returns `None` for a degenerate window
    (`elapsed <= 0` — a same-tick or out-of-order sample, nothing real
    to measure) rather than a divide-by-zero or a meaningless zero
    rate. `cost_per_emergence` is itself `None` when this window's real
    emergence count is zero — an undefined ratio, not a free 0.0."""
    elapsed = tick - prev_tick
    if elapsed <= 0:
        return None
    calls_delta = max(0, calls_succeeded - prev_calls_succeeded)
    emergence_delta = max(0, emergence_total - prev_emergence_total)
    calls_per_1000 = calls_delta / elapsed * 1000.0
    emergence_per_1000 = emergence_delta / elapsed * 1000.0
    cost_per_emergence = (calls_delta / emergence_delta) if emergence_delta > 0 else None
    return {
        "tick": tick,
        "elapsed_ticks": elapsed,
        "deliberative_calls": calls_delta,
        "deliberative_calls_per_1000_ticks": round(calls_per_1000, 3),
        "emergence_count": emergence_delta,
        "emergence_per_1000_ticks": round(emergence_per_1000, 3),
        "cost_per_emergence": round(cost_per_emergence, 3) if cost_per_emergence is not None else None,
    }
