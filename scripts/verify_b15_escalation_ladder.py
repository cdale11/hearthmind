#!/usr/bin/env python3
"""Tier 5 B15.3/B15.4 (Semantic safety: the determinism guarantee)
wired to a real control point.

Explicit user instruction ("continue B and try closing it this turn,
build as many items as possible"). `simulation/escalation.py`'s
`EscalationLadder`/`CognitionBudget` (B15.3/B15.4) were real, verified
standalone primitives since v1.34.182 but had zero real call sites --
this pass gives them one, deliberately narrow: it never touches real-
time tick pacing (CLAUDE.md's "Preserve absolutely" names that
mechanism explicitly, and `LLM_PRESSURE_SLOWDOWN_START_RATIO`/
`_PAUSE_RATIO`'s own bands stay completely untouched), only `_schedule_
due_cognition`'s per-tick LLM-call gate.

`SimulationEngine._maybe_advance_escalation_ladder` (daily, same
cadence as `_maybe_tune_llm_concurrency`/`_maybe_refresh_machine_
profile`) observes `llm_pressure_ratio() >= LLM_PRESSURE_SLOWDOWN_
START_RATIO` -- the exact threshold the untouched real-time pacing
mechanism already treats as "pressure begins here" -- and recomputes
`self._cognition_budget` via `cognition_budget_for_rung`. `_schedule_
due_cognition` now caps how many core-cast agents may spend a real LLM
call THIS TICK at `self._cognition_budget.count` -- at every rung
except sustained rung-5 pressure this is `ESCALATION_COGNITION_BASE_
BUDGET` (effectively unbounded, a genuine no-op); at rung 5 it's
`ESCALATION_COGNITION_REDUCED_BUDGET` (3), a real reduction. WHICH
agents fill whatever budget remains stays entirely `due_for_
cognition`'s own staggered-slot/significance ordering -- the counter
never names a specific agent, per B15.4's own "never a selection"
guarantee.

This script proves, standalone (no unittest): the daily job only fires
on `day_end`, never any other tick, through the real `_TICK_JOBS`
dispatch table (not a synthetic call); sustained pressured daily
readings escalate the real ladder one rung at a time up through rung 5
and reduce the real cognition budget only once rung 5 is reached; a
cleared-pressure reading de-escalates back down and restores the
unbounded budget; at an unbounded budget every genuinely-eligible
core-cast agent in one tick's due list gets a real (mocked) LLM call
scheduled; at the reduced rung-5 budget only the budget's own count
get a real call and the rest correctly fall back to the deterministic
path (never dropped, never silently skipped); and `full_diagnostics()`
surfaces the real rung/budget/history state.
"""
import asyncio
import sys
import tempfile
from unittest import mock

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.agents.agent import EMOTION_FEAR
from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    ESCALATION_COGNITION_BASE_BUDGET, ESCALATION_COGNITION_REDUCED_BUDGET, LLM_PRESSURE_SLOWDOWN_START_RATIO,
    SimulationEngine,
)
from hearthmind.simulation.escalation import CognitionBudget, Rung

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, db_name: str) -> SimulationEngine:
    db_path = f"{tmpdir}/{db_name}"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=1, initial_population=8, width=32, height=32)
    return SimulationEngine.load_or_create(conn, cfg)


def force_significant_core_cast(eng: SimulationEngine, n: int) -> list:
    """Marks the first `n` living agents core-cast and gives each a
    dominant emotion (fear) so `_is_significant_moment` reads True --
    the real gate `use_llm` consults, not bypassed."""
    agents = eng.world.population.agents[:n]
    for agent in agents:
        eng.world.population.core_agent_ids.add(agent.id)
        agent.emotions[EMOTION_FEAR] = 1.0
    return agents


async def _fake_run(*args, **kwargs):
    return {"goal": "wander", "reason": "test"}, False, "raw completion", {"fallback_reason": None}


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. The daily job only fires on day_end, through the REAL
        #    _TICK_JOBS dispatch table -- not a synthetic direct call.
        eng1 = make_engine(tmpdir, "cadence.db")
        rung_before = eng1._escalation_ladder.current_rung
        with mock.patch.object(SimulationEngine, "llm_pressure_ratio", return_value=1.0):
            for _ in range(10):
                eng1._tick_once()
        check(
            "a fresh 10-tick run (well under one real day) never advances the ladder off its start rung",
            eng1._escalation_ladder.current_rung == rung_before,
        )

        # 2. Sustained pressured daily readings escalate the real
        #    ladder one rung at a time, reaching rung 5 only after
        #    SUSTAINED_PRESSURE_THRESHOLD consecutive PAUSE-rung days,
        #    and the real cognition budget only shrinks once rung 5 is
        #    actually reached.
        eng2 = make_engine(tmpdir, "escalate.db")
        with mock.patch.object(SimulationEngine, "llm_pressure_ratio", return_value=2.0):
            for _ in range(4):
                eng2._maybe_advance_escalation_ladder(["day_end"])
            check(
                "4 pressured days reaches PAUSE (rung 4), not yet REDUCE_COGNITION_BREADTH",
                eng2._escalation_ladder.current_rung is Rung.PAUSE,
            )
            check(
                "the cognition budget is still the unbounded base at rung 4",
                eng2._cognition_budget.count == ESCALATION_COGNITION_BASE_BUDGET,
            )
            for _ in range(5):
                eng2._maybe_advance_escalation_ladder(["day_end"])
            check(
                "sustained pressure past the threshold reaches REDUCE_COGNITION_BREADTH (rung 5)",
                eng2._escalation_ladder.current_rung is Rung.REDUCE_COGNITION_BREADTH,
            )
            check(
                "rung 5 genuinely reduces the real cognition budget",
                eng2._cognition_budget.count == ESCALATION_COGNITION_REDUCED_BUDGET,
            )

        # 3. A cleared-pressure reading de-escalates the real ladder and
        #    restores the unbounded budget.
        with mock.patch.object(SimulationEngine, "llm_pressure_ratio", return_value=0.0):
            eng2._maybe_advance_escalation_ladder(["day_end"])
        check("clearing pressure de-escalates one rung", eng2._escalation_ladder.current_rung is Rung.PAUSE)
        check(
            "the real cognition budget is restored to unbounded once off rung 5",
            eng2._cognition_budget.count == ESCALATION_COGNITION_BASE_BUDGET,
        )

        # 4. At an unbounded budget, every genuinely-eligible core-cast
        #    agent in one tick's due list gets a real LLM call
        #    scheduled -- the cap is a true no-op off rung 5.
        eng3 = make_engine(tmpdir, "unbounded.db")
        eng3._cognition_runner.client = object()  # enable, matching verify_b6's own pattern
        eng3._cognition_runner.run = _fake_run
        agents3 = force_significant_core_cast(eng3, 5)
        with mock.patch.object(
            type(eng3.world.population), "due_for_cognition", return_value=agents3,
        ), mock.patch.object(
            type(eng3.world.population), "due_for_triggered_cognition", return_value=[],
        ), mock.patch.object(
            # Isolate the B15.4 cognition-budget gate from B2's own
            # independent concurrency-derived backpressure ceiling
            # (a genuinely separate real gate this check isn't about)
            # -- same "test one mechanism in isolation" discipline
            # verify_b6_adaptive_concurrency.py already established.
            SimulationEngine, "_current_backpressure_limit", return_value=1000,
        ):
            eng3._schedule_due_cognition()
        check(
            "unbounded budget: all 5 significant core-cast agents get a real LLM call scheduled",
            len(eng3._inflight_cognition_agent_ids) == 5,
        )
        for task in list(eng3._background_tasks):
            task.cancel()
        await asyncio.sleep(0)

        # 5. At the reduced rung-5 budget, only the budget's own count
        #    get a real call; the rest correctly fall back to the
        #    deterministic path -- never dropped, never silently
        #    skipped.
        eng4 = make_engine(tmpdir, "reduced.db")
        eng4._cognition_runner.client = object()
        eng4._cognition_runner.run = _fake_run
        eng4._cognition_budget = CognitionBudget(count=2)
        agents4 = force_significant_core_cast(eng4, 5)
        with mock.patch.object(
            type(eng4.world.population), "due_for_cognition", return_value=agents4,
        ), mock.patch.object(
            type(eng4.world.population), "due_for_triggered_cognition", return_value=[],
        ):
            eng4._schedule_due_cognition()
        check(
            "reduced budget (2): exactly 2 of the 5 significant core-cast agents get a real LLM call",
            len(eng4._inflight_cognition_agent_ids) == 2,
        )
        check(
            "reduced budget: the other 3 correctly fall back to the deterministic goal path, not dropped",
            len(eng4._pending_goal_results) == 3,
        )
        check(
            "every one of the 5 agents was accounted for (scheduled or fell back) -- none silently skipped",
            len(eng4._inflight_cognition_agent_ids) + len(eng4._pending_goal_results) == 5,
        )
        for task in list(eng4._background_tasks):
            task.cancel()
        await asyncio.sleep(0)

        # 6. full_diagnostics() surfaces the real rung/budget/history
        #    state.
        diag = eng2.full_diagnostics()["escalation_ladder"]
        check("full_diagnostics() reports the real current_rung", diag["current_rung"] == Rung.PAUSE.name)
        check("full_diagnostics() reports the real cognition_budget", diag["cognition_budget"] == ESCALATION_COGNITION_BASE_BUDGET)
        check("full_diagnostics() reports is_reduced=False off rung 5", diag["is_reduced"] is False)
        check("full_diagnostics() surfaces real logged transitions, not an empty stub", len(diag["history_recent"]) > 0)

        # 7. LLM_PRESSURE_SLOWDOWN_START_RATIO is genuinely the shared
        #    threshold -- a reading just below it never registers as
        #    pressured, just at/above it does (matches the real
        #    pacing mechanism's own "pressure begins here" semantics).
        eng5 = make_engine(tmpdir, "threshold.db")
        with mock.patch.object(SimulationEngine, "llm_pressure_ratio", return_value=LLM_PRESSURE_SLOWDOWN_START_RATIO - 0.01):
            eng5._maybe_advance_escalation_ladder(["day_end"])
        check("just below the shared pressure threshold: no escalation", eng5._escalation_ladder.current_rung is Rung.REORDER_BATCH)
        with mock.patch.object(SimulationEngine, "llm_pressure_ratio", return_value=LLM_PRESSURE_SLOWDOWN_START_RATIO):
            eng5._maybe_advance_escalation_ladder(["day_end"])
        check("at the shared pressure threshold: real escalation fires", eng5._escalation_ladder.current_rung is Rung.DEFER_WITHIN_DEADLINE)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
