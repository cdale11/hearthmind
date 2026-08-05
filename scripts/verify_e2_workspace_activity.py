#!/usr/bin/env python3
"""Tier 7 HCA Stage E, E2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 7,
explicit user instruction "Start E2"): workspace contents + the
losing coalitions panel.

Verifies `hearthmind.cognition.observatory`'s `describe_bid`/`describe_
competition`/`workspace_snapshot` directly against real `Bid`/
`CompetitionRecord`/`GlobalWorkspace` objects (including a genuine
multi-bid cycle constructed by hand, proving losers ARE captured
correctly when they exist, even though no real production call site
generates one today), then end to end through a real `SimulationEngine`
— the exact same `_make_engine`/`FakeAdapter` technique `scripts/
verify_phase35_w1_naming_workspace.py` already established — confirming
`full_diagnostics()['naming_workspace_activity']` genuinely reflects a
real production arbitration cycle, including the honest coalition-of-
one shape (empty `losers`) every real production workspace has today."""
from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


class FakeAdapter:
    """Same minimal real `LLMAdapter` shape `verify_phase35_w1_naming_
    workspace.py` already uses — no network, no live server needed."""

    timeout_seconds = 5.0

    def __init__(self, name: str) -> None:
        self._name = name

    def generate_json(
        self, prompt, system=None, capture=None, json_schema=None,
        num_predict_override=None, temperature_override=None,
        reasoning=False, timeout_override=None,
    ) -> dict:
        if capture is not None:
            capture["raw"] = '{"name": "%s"}' % self._name
        return {"name": self._name}

    @classmethod
    def build_from_config(cls, config):
        return cls("Testville")


def _make_engine(tag: str):
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    d = tempfile.mkdtemp()
    conn = connect(f"{d}/{tag}.db")
    cfg = Config(db_path=f"{d}/{tag}.db", llm_enabled=False, seed=7, initial_population=4, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


async def main_async() -> int:
    from hearthmind.cognition.observatory import describe_bid, describe_competition, workspace_snapshot
    from hearthmind.cognition.workspace import Bid, CompetitionRecord, GlobalWorkspace

    # --- describe_bid: every real field, verbatim ---
    bid = Bid(specialist_id="alpha", subject="the granary", score=0.732, reason="real reason text")
    described = describe_bid(bid)
    check("describe_bid reports every real field verbatim",
          described == {
              "specialist_id": "alpha", "subject": "the granary", "score": 0.732,
              "domain": "world", "reason": "real reason text",
          })

    # --- describe_competition: a real empty cycle ---
    empty_record = CompetitionRecord(cycle=1, winner=None, losers=())
    check("describe_competition reports a real empty cycle honestly (winner=None, zero losers)",
          describe_competition(empty_record) == {"cycle": 1, "winner": None, "losers": [], "loser_count": 0})

    # --- describe_competition: a genuine multi-bid cycle (built by
    #     hand — no real production site generates one yet, but the
    #     function itself must be proven correct against a real case) ---
    winner_bid = Bid(specialist_id="w", subject="s", score=0.9)
    loser_bid_1 = Bid(specialist_id="l1", subject="s", score=0.5)
    loser_bid_2 = Bid(specialist_id="l2", subject="s", score=0.3)
    multi_record = CompetitionRecord(cycle=5, winner=winner_bid, losers=(loser_bid_1, loser_bid_2))
    described_multi = describe_competition(multi_record)
    check("describe_competition reports the real winner AND every real loser",
          described_multi["winner"]["specialist_id"] == "w"
          and described_multi["loser_count"] == 2
          and {l["specialist_id"] for l in described_multi["losers"]} == {"l1", "l2"})

    # --- workspace_snapshot: real bounded history, newest last, via a
    #     real GlobalWorkspace driven through several real cycles ---
    ws = GlobalWorkspace()
    for i in range(5):
        ws.submit(Bid(specialist_id=f"s{i}", subject=f"subject_{i}", score=float(i)))
        ws.arbitrate()
    snap = workspace_snapshot(ws, recent=3)
    check("workspace_snapshot returns exactly the requested count, newest last",
          len(snap) == 3 and snap[-1]["winner"]["specialist_id"] == "s4")
    check("workspace_snapshot over an empty workspace returns an empty list, never crashes",
          workspace_snapshot(GlobalWorkspace()) == [])

    # --- end to end: a real SimulationEngine's own naming workspace,
    #     the exact same production pilot verify_phase35_w1_naming_
    #     workspace.py already proved wires into _naming_workspace ---
    eng = _make_engine("e2_naming")
    eng._cognition_runner.client = FakeAdapter("Rivenmoor")
    stl = eng._settlement_by_id(0)
    stl.name = "Placeholder Town"
    stl.llm_named = False
    eng.world.newly_named_settlement_ids = [0]

    report_before = eng.full_diagnostics()
    check("before any naming, the real diagnostics field is an honest empty list",
          report_before["naming_workspace_activity"] == [])

    eng._maybe_schedule_naming()
    for _ in range(50):
        if not eng._background_tasks:
            break
        await asyncio.sleep(0.02)

    report_after = eng.full_diagnostics()
    activity = report_after["naming_workspace_activity"]
    check("after a real naming cycle, full_diagnostics() reports exactly one real cycle",
          len(activity) == 1)
    check("the reported cycle's real winner is naming's own bid for this settlement",
          activity[0]["winner"]["specialist_id"] == "naming" and activity[0]["winner"]["subject"] == "naming:0")
    check("the reported cycle honestly shows zero losers (today's real coalition-of-one shape)",
          activity[0]["loser_count"] == 0 and activity[0]["losers"] == [])

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
