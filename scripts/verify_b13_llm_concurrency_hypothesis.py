#!/usr/bin/env python3
"""Tier 5 B13's real first wiring for `llm_max_concurrent` — verifies
`SimulationEngine._run_llm_concurrency_hypothesis`/`_probe_concurrency_
wait_ms`/`_concurrency_equivalence_check` against a real `SimulationEngine`,
no unittest, same standalone-script convention as every sibling
`verify_*.py`. All async (the real probe + equivalence check are
awaited), driven via `asyncio.run`."""
from __future__ import annotations

import asyncio
import sys
import tempfile

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

CHECKS = 0
FAILURES: list[str] = []
_TMPDIR = tempfile.mkdtemp()
_COUNTER = 0


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def make_engine() -> SimulationEngine:
    global _COUNTER
    _COUNTER += 1
    db_path = f"{_TMPDIR}/b13_hyp_{_COUNTER}.db"
    conn = connect(db_path)
    cfg = Config(
        db_path=db_path, llm_enabled=False, seed=777,
        initial_population=8, width=24, height=24, llm_max_concurrent=2,
    )
    return SimulationEngine.load_or_create(conn, cfg)


async def main_async() -> int:
    # 1. Real active probe: a lower concurrency genuinely measures a
    # higher real wall-clock wait than a higher one, for the same
    # synthetic workload.
    eng = make_engine()
    wait_low = await eng._probe_concurrency_wait_ms(1, n_tasks=8, hold_seconds=0.01)
    wait_high = await eng._probe_concurrency_wait_ms(8, n_tasks=8, hold_seconds=0.01)
    check("lower concurrency measurably waits longer than higher concurrency",
          wait_low > wait_high)

    # 2. CrossAuthorityError: the loop only owns llm_max_concurrent.
    from hearthmind.simulation.optimization_hypothesis import CrossAuthorityError
    try:
        eng._llm_concurrency_hypothesis_loop._require_ownership("some_other_tunable")
        check("CrossAuthorityError raised for an unowned tunable", False)
    except CrossAuthorityError:
        check("CrossAuthorityError raised for an unowned tunable", True)

    # 3. A genuine improvement (raising concurrency from a small value)
    # is kept, passes the real equivalence gate, and actually resizes
    # the live tunable.
    eng2 = make_engine()
    before = int(eng2._tuning_registry.get("llm_max_concurrent").value)
    record = await eng2._run_llm_concurrency_hypothesis(
        proposed_value=before + 4, hypothesis="raising concurrency should reduce real queueing wait",
    )
    check("a genuine improvement is kept", record.decision == "kept")
    check("the real registry value actually changed", eng2._tuning_registry.get("llm_max_concurrent").value == before + 4)
    check("history recorded the real attempt", eng2._hypothesis_history.all() and eng2._hypothesis_history.all()[-1] is record)

    # 4. A non-improving proposal (same value, or a value that raises
    # real wait) is rolled back and does NOT change the live tunable.
    eng3 = make_engine()
    before3 = int(eng3._tuning_registry.get("llm_max_concurrent").value)
    record3 = await eng3._run_llm_concurrency_hypothesis(
        proposed_value=1, hypothesis="lowering concurrency to 1 should not improve real wait",
    )
    check("a non-improving proposal is rolled back",
          record3.decision == "rolled_back" and eng3._tuning_registry.get("llm_max_concurrent").value == before3)

    # 5. The real equivalence check itself: llm_max_concurrent cannot
    # affect Body-deterministic World state — a real fork-and-tick
    # comparison under two different values must match.
    eng4 = make_engine()
    equiv = await eng4._concurrency_equivalence_check(1, 4)
    check("real equivalence check confirms llm_max_concurrent never affects Body state", equiv is True)

    # 6. Manual-only wiring: never present in _TICK_JOBS (no automatic
    # scheduling that could fight B6/B7's own live controller).
    job_names = [name for name, _ in SimulationEngine._TICK_JOBS]
    check("never auto-scheduled into _TICK_JOBS (manual control point only)",
          "_run_llm_concurrency_hypothesis" not in job_names)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
