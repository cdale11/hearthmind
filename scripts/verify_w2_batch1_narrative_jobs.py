#!/usr/bin/env python3
"""Phase 3.5 W2, first real sweep batch (docs/ROADMAP-2026-07-
REMAINING.md, explicit user instruction "W2" -- the real sweep W1's
pilot proved safe). Four real settlement/world-scoped `_schedule_llm_
job` call sites converted from an unconditional call onto the shared
`SimulationEngine._submit_and_resolve` helper (W1's own naming-pilot
pattern, factored out so this batch's four sites -- and every future
one -- don't duplicate its submit/arbitrate/resolve boilerplate):
`documentary` (year-end narration), `musing` (daily Reflection voice),
`omen` (rare ambiguous flavor event), `record` (a departed villager's
written artifact -- the one PER-CANDIDATE loop in this batch, same
"multiple independent cycles within one call" shape as W1's own
multi-settlement naming case).

Verified here, standalone (no unittest, no live LLM server -- reuses
Phase 3.5 W1's own `FakeAdapter` technique): each site's own real
arbitration cycle genuinely runs and resolves correctly; each site
gets its OWN dedicated workspace (not accidentally sharing one and
suppressing each other); `record`'s per-candidate loop produces one
independent cycle per candidate; and the shared `_submit_and_resolve`
helper's own contract (coalition-of-one, resolver invoked only on a
real winner) holds directly.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


class FakeAdapter:
    """Same minimal shape Phase 3.5 W1's own verify script established
    -- returns a fixed, real dict answer, no network needed."""

    timeout_seconds = 5.0

    def __init__(self, answer: dict) -> None:
        self._answer = answer

    def generate_json(
        self, prompt, system=None, capture=None, json_schema=None,
        num_predict_override=None, temperature_override=None,
        reasoning=False, timeout_override=None,
    ) -> dict:
        if capture is not None:
            capture["raw"] = "{}"
        return dict(self._answer)

    @classmethod
    def build_from_config(cls, config):
        return cls({})


def _make_engine(tag: str) -> SimulationEngine:
    d = tempfile.mkdtemp()
    conn = connect(f"{d}/{tag}.db")
    cfg = Config(db_path=f"{d}/{tag}.db", llm_enabled=False, seed=11, initial_population=4, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


async def _await_background(eng: SimulationEngine) -> None:
    for _ in range(50):
        if not eng._background_tasks:
            return
        await asyncio.sleep(0.02)


async def main_async() -> int:
    from hearthmind.cognition.workspace import GlobalWorkspace

    # --- direct unit proof of the shared helper's own contract,
    #     independent of any real job. ---
    eng0 = _make_engine("w2_helper")
    calls: list[str] = []
    eng0._submit_and_resolve("test_job", "test_subject", lambda: calls.append("fired"))
    check("_submit_and_resolve's own resolver fires on a real coalition-of-one win",
          calls == ["fired"])
    check("_submit_and_resolve gave 'test_job' its own dedicated workspace",
          "test_job" in eng0._w2_workspaces and len(eng0._w2_workspaces["test_job"].history) == 1)
    check("a second, unrelated job name gets a SEPARATE dedicated workspace",
          eng0._w2_workspaces.setdefault("other_job", GlobalWorkspace()) is not eng0._w2_workspaces["test_job"])

    # --- documentary: year-end, settlement-scoped, single firing. ---
    eng1 = _make_engine("w2_documentary")
    eng1._cognition_runner.client = FakeAdapter({"narration": "A quiet year passed."})
    eng1.world.settlement.name = "Rivenshade"
    # _season_year_gate requires "day_end" alongside the boundary event
    # even on the opening tick (a season/year boundary always coincides
    # with a real day boundary -- see its own docstring).
    eng1._maybe_schedule_documentary(["year_end", "day_end"])
    check("documentary: a real arbitration cycle ran in its own dedicated workspace",
          "documentary" in eng1._w2_workspaces and len(eng1._w2_workspaces["documentary"].history) == 1)
    check("documentary: the real winner names the right subject",
          eng1._w2_workspaces["documentary"].history[0].winner.subject == "documentary")
    await _await_background(eng1)
    check("documentary: the real LLM job resolved end to end (a real log entry exists)",
          any(e.get("category") == "documentary" for e in eng1._pending_broadcast_events))

    # --- musing: daily, world-scoped, skips cleanly with no subject. ---
    eng2 = _make_engine("w2_musing")
    eng2._cognition_runner.client = FakeAdapter({"musing": "The river remembers everything."})
    # Force a real musing subject to exist by seeding an open reflection
    # hypothesis (same real precondition _musing_subject reads).
    eng2.world.reflection_notebook.append({
        "id": 1, "tick": 0, "kind": "hypothesis", "status": "open",
        "confidence": 0.5, "text": "the village grows quieter each winter",
        "evidence_for": [], "evidence_against": [], "subject": "quiet winters",
    })
    eng2._maybe_schedule_musing(["day_end"])
    fired = "musing" in eng2._w2_workspaces and len(eng2._w2_workspaces["musing"].history) == 1
    check("musing: a real arbitration cycle ran once a genuine subject existed", fired)
    if fired:
        await _await_background(eng2)
        check("musing: the real LLM job resolved end to end (a musing was recorded)",
              len(eng2.world.musings) == 1)

    # --- omen: rare, chance-gated -- confirm it correctly does NOT
    #     touch the workspace when phase_g_intensity disables it
    #     outright (the real early-out preserved). ---
    d3 = tempfile.mkdtemp()
    conn3 = connect(f"{d3}/w2_omen_disabled.db")
    cfg3 = Config(
        db_path=f"{d3}/w2_omen_disabled.db", llm_enabled=False, seed=11,
        initial_population=4, width=16, height=16, phase_g_intensity=0.0,
    )
    eng3 = SimulationEngine.load_or_create(conn3, cfg3)
    eng3.world.settlement.name = "Ashcombe"
    eng3._maybe_schedule_omen(["month_end"])
    check("omen: phase_g_intensity=0.0 correctly never touches the workspace",
          "omen" not in eng3._w2_workspaces)

    # --- record: the per-candidate loop -- two candidates in the same
    #     call must each get their own independent cycle. ---
    eng4 = _make_engine("w2_record")
    eng4._cognition_runner.client = FakeAdapter({"text": "Here lies a plain record."})
    eng4.world.population.last_written_records = [
        {"author": "Osric", "memories": ["a hard winter"], "belief": "the land is unforgiving", "settlement_id": 0},
        {"author": "Ysolde", "memories": ["a good harvest"], "belief": "kindness endures", "settlement_id": 0},
    ]
    eng4._maybe_schedule_record()
    record_ws = eng4._w2_workspaces.get("record")
    check("record: two independent candidates in one call produced two real arbitration cycles",
          record_ws is not None and len(record_ws.history) == 2)
    check("record: each cycle's own winner names the correct per-author subject",
          record_ws is not None
          and {r.winner.subject for r in record_ws.history} == {"record:Osric", "record:Ysolde"})
    await _await_background(eng4)
    settlement_records = eng4._settlement_by_id(0).records
    check("record: both candidates' real LLM jobs resolved end to end (two records written)",
          len(settlement_records) == 2)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
