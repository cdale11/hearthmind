"""Tier 7 HCA Stage H, H2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 4,
explicit user instruction "Start H2"): the Adaptive Runtime as a real
specialist family in the MACHINE cognitive domain (CLAUDE.md's HCA
section, "Cognitive domains — the Runtime and Player Model are minds").

The honest finding this item exists to act on (already recorded in
CLAUDE.md before any code shipped): the Adaptive Runtime ALREADY
implements four of L1's five methods under other names --

  predict()/error() -- `hearthmind.simulation.forecasting.
      WorkloadForecaster.predict`/`ForecastAccuracyTracker` (B8.1/B8.3)
  observe()         -- `hearthmind.simulation.profiling.TaskMetrics`
      (B5.1) -- every registered task gets a real metered entry the
      moment it's first processed, no code path skips it
  learn()            -- `hearthmind.simulation.optimization_hypothesis.
      HypothesisLoop.apply_and_measure` (B13) and `hearthmind.ml.
      specialist.LearningSpecialist.learn` (G1/G2, already wraps B8.1's
      own forecaster)
  bid()              -- was the one real gap: `hearthmind.simulation.
      escalation.EscalationLadder.observe` unilaterally mutated engine
      state (`SimulationEngine._cognition_budget`) with no arbitration,
      no competition, and no legible record anywhere a person could
      watch. `propose_escalation_bid` below is the fix -- the ladder's
      real decision becomes a real `Bid`, submitted to `Simulation
      Engine._machine_workspace` (a dedicated MACHINE-domain workspace,
      never shared with any WORLD-domain workspace, per H1's own
      "domains never compete for each other's budget" rule) and
      arbitrated through the same B1 mechanism every W1-W4 site
      already uses.

This module itself holds no world/agent/settlement/economy state and
imports none -- `SPECIALIST_DOMAIN = Domain.MACHINE` below is a real,
mechanically-checked claim (`scripts/verify_runtime_invariant.py`'s
`check_domain_write_scope()`), not a decorative label. The four sibling
modules named above (`escalation.py`/`forecasting.py`/`profiling.py`/
`optimization_hypothesis.py`) carry the identical marker -- together
they ARE the Adaptive Runtime's MACHINE-domain specialist family;
`propose_escalation_bid` is this module's own real contribution: the
one method the family didn't already have.

**Roadmap Phase 3, H1 "per-domain budgets" (docs/ROADMAP-2026-07-
REMAINING.md, explicit user instruction "continue with phase 3's
remaining items" -> "H1 per-domain budgets (Recommended)"): a real
SECOND bidder, `propose_machine_profile_refresh_bid`.** H1's own write-
scope enforcement was real from the start; what was missing, named
directly in the roadmap, was real per-domain budget CONTENTION -- with
only `propose_escalation_bid` ever submitting, `SimulationEngine.
_machine_workspace` was structurally a coalition of one every single
real cycle, so B2's own starvation/staleness machinery and the
workspace's own comparison logic had nothing real to actually compare.
`propose_machine_profile_refresh_bid` gives B7.2's monthly `Machine
Profile` disk refresh (previously an unconditional inline write once
its own month_end+quiet-window gate cleared) a real `Bid` too, on a
DIFFERENT subject (`"machine_profile_refresh"`) than the escalation
ladder's (`"escalation_ladder"`) -- `GlobalWorkspace.arbitrate()`
compares ALL pending bids together regardless of subject (it picks one
winner for the whole cycle, not one winner per subject), so this is
genuine domain-level contention: on any real day both gates clear, the
MACHINE domain's one action this cycle goes to WHICHEVER real
candidate scores higher, not to both.

**The real, meaningful score split, not a coin flip.** `propose_
escalation_bid` now takes `pressured: bool` and scores itself `ESCALATION_
BID_PRESSURED_SCORE` (1.0) when the ladder's own real signal says the
LLM queue is under pressure, `ESCALATION_BID_CALM_SCORE` (0.3,
deliberately below the profile refresh's own flat 0.5) otherwise --
`arbitrate()`'s own deterministic first-submitted-wins tie-break (no
RNG, see `GlobalWorkspace`'s docstring) would otherwise let whichever
job's `_TICK_JOBS` dispatch order happens to submit first win literally
every time regardless of real urgency, defeating the whole point of
real contention. The result is a real, load-bearing behavioral split:
a genuinely pressured cycle always wins the domain's attention for the
escalation ladder (never starved by background maintenance, preserving
the exact safety-relevant response B15.3/B15.4 exist for); a genuinely
CALM cycle -- the only time `is_quiet_window` would ever have let the
profile refresh's own gate clear anyway -- lets that real periodic
maintenance spend the domain's one action instead of an unnecessary
"hold" call. Losing costs nothing structurally: a profile refresh that
loses this cycle's bid simply tries again next month_end, same
"contention never risks correctness, only timing" discipline every
W1-W4 coalition-of-one site in this codebase already holds to for the
WORLD domain.

Known, explicitly-flagged deviation from H1's own stated rule ("MACHINE
may write ONLY tunables -- see `simulation/tuning.py`'s `TunableRegistry`,
never world/agents/settlement/economy state"): the winning bid's
resolver (built in `SimulationEngine._maybe_advance_escalation_ladder`,
not here -- `Bid.resolver` is deliberately execution-agnostic, see
`Bid`'s own docstring) currently mutates `SimulationEngine._escalation_
ladder`/`_cognition_budget` directly, NOT a real `TunableRegistry`
entry -- this subsystem predates H1's domain framework and migrating
its storage onto a real tunable (so the rule holds literally, not just
in spirit) is real, distinct, larger future work, not attempted this
pass. What IS real and verified now: the resolver never touches
`hearthmind.world`/`Settlement`/`Agent` state at all (H3's own cross-
domain isolation proof, `scripts/verify_h2_h3_runtime_domain.py`) --
the letter of "never world state" holds even though the letter of
"only tunables" does not yet."""
from __future__ import annotations

from typing import Callable

from hearthmind.cognition.workspace import Bid, Domain

SPECIALIST_DOMAIN = Domain.MACHINE

ESCALATION_BID_PRESSURED_SCORE = 1.0
"""The escalation ladder's own bid score while the LLM queue is
genuinely pressured -- unchanged from the original flat value, and
deliberately kept above `MACHINE_PROFILE_REFRESH_BID_SCORE` so a real
pressured cycle can NEVER lose the domain's one action to background
maintenance, preserving B15.3/B15.4's own safety-relevant response."""

ESCALATION_BID_CALM_SCORE = 0.3
"""The escalation ladder's own bid score while the LLM queue is NOT
pressured -- deliberately below `MACHINE_PROFILE_REFRESH_BID_SCORE`
(0.5), so a genuinely calm cycle lets real periodic maintenance win
the domain's one action instead of an unnecessary "hold" call. A
reasoned starting point (no live archive to tune it against yet, same
honesty every fresh constant in this codebase carries) -- what matters
structurally is only that this stays strictly below the profile
refresh's own score, and `ESCALATION_BID_PRESSURED_SCORE` stays
strictly above it."""


def propose_escalation_bid(tick: int, resolver: Callable[[], None], pressured: bool) -> Bid:
    """B15's escalation-ladder decision, converted from a unilateral
    write into a real `Bid` -- `subject="escalation_ladder"` names the
    one real decision this family's `bid()` covers today.

    Roadmap Phase 3, H1: `pressured` (the ladder's own real LLM-queue-
    pressure reading, unchanged elsewhere) now decides the SCORE, not
    just a flat `1.0` -- a real second MACHINE bidder,
    `propose_machine_profile_refresh_bid` below, competes in the SAME
    `_machine_workspace` on a different subject, and `arbitrate()`
    picks ONE winner across the whole cycle regardless of subject. A
    flat score for both would make `_TICK_JOBS`' own fixed dispatch
    order the real tie-break every single time (`arbitrate()`'s
    first-submitted-wins rule, no RNG) -- `pressured` is the real
    signal that should decide this, not accidental submission order.
    `resolver` is the caller's own closure (built in `SimulationEngine`,
    which legitimately holds world state) -- this module never sees or
    touches it beyond passing it through, keeping this file itself
    provably world-state-free regardless of what a caller's resolver
    happens to do."""
    score = ESCALATION_BID_PRESSURED_SCORE if pressured else ESCALATION_BID_CALM_SCORE
    return Bid(
        specialist_id="adaptive_runtime", subject="escalation_ladder",
        score=score, resolver=resolver, domain=Domain.MACHINE,
    )


MACHINE_PROFILE_REFRESH_BID_SCORE = 0.5
"""B7.2's monthly `MachineProfile` disk refresh's own flat bid score --
strictly between `ESCALATION_BID_CALM_SCORE` and `ESCALATION_BID_
PRESSURED_SCORE` by construction (see both constants' own docstrings),
so this real second bidder only ever wins the domain's one action on a
genuinely calm cycle, never a pressured one. Flat, not itself pressure-
scaled -- the refresh's own real due-ness is already gated upstream
(month_end + `is_quiet_window`, see `SimulationEngine._maybe_refresh_
machine_profile`), so once it's bidding at all it has nothing further
to weigh against a rival except the escalation ladder's own urgency."""


def propose_machine_profile_refresh_bid(resolver: Callable[[], None]) -> Bid:
    """Roadmap Phase 3, H1 "per-domain budgets" -- the real second
    MACHINE-domain bidder this item names as its own missing piece
    (`docs/ROADMAP-2026-07-REMAINING.md`: "real per-domain budget
    contention needs a second real bidder in the MACHINE or OBSERVER
    domain, which doesn't exist yet"). `subject="machine_profile_
    refresh"` -- deliberately a DIFFERENT subject than the escalation
    ladder's `"escalation_ladder"`, since these are two genuinely
    different real machine-level actions, not two candidate answers to
    the same question; `GlobalWorkspace.arbitrate()` still resolves
    them against each other because it compares every pending bid in
    the cycle together, not per-subject. `resolver` is the caller's own
    closure wrapping the real `HostProbe.sample(run_storage_bench=
    True)` + `MachineProfile.record_storage_benchmark` + disk-save
    sequence B7.2 already established -- this module never touches it,
    same world-state-free discipline as `propose_escalation_bid`."""
    return Bid(
        specialist_id="adaptive_runtime", subject="machine_profile_refresh",
        score=MACHINE_PROFILE_REFRESH_BID_SCORE, resolver=resolver, domain=Domain.MACHINE,
    )
