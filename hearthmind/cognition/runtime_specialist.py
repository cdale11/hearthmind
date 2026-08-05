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


def propose_escalation_bid(tick: int, resolver: Callable[[], None]) -> Bid:
    """B15's escalation-ladder decision, converted from a unilateral
    write into a real `Bid` -- `subject="escalation_ladder"` names the
    one real decision this family's `bid()` covers today (a second
    MACHINE specialist naming a different subject would compete in the
    SAME `_machine_workspace`, the real point of giving it a dedicated
    workspace rather than resolving inline). `score=1.0`: flat, same as
    every W1-W4 coalition-of-one bid in this codebase -- nothing else
    bids into this workspace yet, so there is no real signal to weigh
    it against; a future second MACHINE specialist would need a real
    B5-style evidence score, not this placeholder. `resolver` is the
    caller's own closure (built in `SimulationEngine`, which legitimately
    holds world state) -- this module never sees or touches it beyond
    passing it through, keeping this file itself provably world-state-
    free regardless of what a caller's resolver happens to do."""
    return Bid(
        specialist_id="adaptive_runtime", subject="escalation_ladder",
        score=1.0, resolver=resolver, domain=Domain.MACHINE,
    )
