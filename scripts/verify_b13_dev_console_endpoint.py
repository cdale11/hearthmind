#!/usr/bin/env python3
"""Tier 5 B13's dev-console/API trigger — verifies the real
`/intervene/llm-concurrency-hypothesis` -> `_apply_intervention` ->
background-task -> `full_diagnostics()` path end to end, driving the
same `WorldBroadcaster.enqueue_intervention`/`_apply_pending_
interventions` seam the real HTTP endpoint uses (no HTTP server
needed — this exercises the engine-side machinery the endpoint is a
thin wrapper over). Standalone, no unittest."""
from __future__ import annotations

import asyncio
import sys
import tempfile

from hearthmind.config import Config
from hearthmind.interface.api import WorldBroadcaster
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


async def main_async() -> int:
    d = tempfile.mkdtemp()
    db_path = f"{d}/b13_dev_console.db"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=42, initial_population=8, width=20, height=20)
    eng = SimulationEngine.load_or_create(conn, cfg)
    broadcaster = WorldBroadcaster()
    eng._broadcaster = broadcaster

    diag_before = eng.full_diagnostics()
    check("llm_concurrency_hypothesis field present before any request",
          "llm_concurrency_hypothesis" in diag_before)
    check("not running, no result before any request",
          not diag_before["llm_concurrency_hypothesis"]["running"]
          and diag_before["llm_concurrency_hypothesis"]["last_result"] is None)

    before_value = int(eng._tuning_registry.get("llm_max_concurrent").value)
    broadcaster.enqueue_intervention({
        "type": "llm_concurrency_hypothesis",
        "proposed_value": before_value + 4,
        "hypothesis": "dev-console smoke test",
    })
    eng._apply_pending_interventions()
    check("intervention application starts the background task",
          eng._llm_concurrency_hypothesis_running)

    # Real background task -- await it to completion (bounded: the
    # probe/equivalence-check are both short by construction).
    for _ in range(300):
        if not eng._llm_concurrency_hypothesis_running:
            break
        await asyncio.sleep(0.05)
    check("background task completes within the bound", not eng._llm_concurrency_hypothesis_running)

    diag_after = eng.full_diagnostics()
    section = diag_after["llm_concurrency_hypothesis"]
    check("a real result is surfaced after completion", section["last_result"] is not None)
    check("the real result reflects a genuine improvement",
          section["last_result"]["decision"] == "kept")
    check("history_recent reflects the real attempt", len(section["history_recent"]) == 1)

    # A second request while one is (artificially) marked running is dropped.
    eng._llm_concurrency_hypothesis_running = True
    broadcaster.enqueue_intervention({
        "type": "llm_concurrency_hypothesis", "proposed_value": 1, "hypothesis": "should be dropped",
    })
    eng._apply_pending_interventions()
    check("a second concurrent request is dropped, not stacked",
          len(eng._hypothesis_history.all()) == 1)
    eng._llm_concurrency_hypothesis_running = False

    # A malformed request (missing proposed_value) is a safe no-op.
    broadcaster.enqueue_intervention({"type": "llm_concurrency_hypothesis", "hypothesis": "no value"})
    eng._apply_pending_interventions()
    check("a malformed request never starts a background task",
          not eng._llm_concurrency_hypothesis_running)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
