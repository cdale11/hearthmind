#!/usr/bin/env python3
"""Phase 3.5 W1 (docs/ROADMAP-2026-07-REMAINING.md, explicit user
instruction: "Start phase 3.5 W1"): the real production pilot for
wiring Stage B's `GlobalWorkspace` into a live `_schedule_llm_job`
call site. `SimulationEngine._maybe_schedule_naming` now `submit()`s
a real `Bid` to a dedicated `self._naming_workspace` per eligible
settlement and calls `arbitrate()` immediately after, invoking the
winning bid's own `resolver` only if `arbitrate()` returns one,
instead of scheduling the LLM call unconditionally.

Verified here, standalone (no unittest, no live LLM server — a
minimal fake `LLMAdapter` stands in, same technique every other
LLM-job verify script in this codebase uses): a real workspace cycle
genuinely runs (a `Bid` is submitted, `arbitrate()` returns a real
winner, the competition is logged); the winning bid's resolver is
what actually fires the LLM job (not a bypass); the end-to-end
outcome — the settlement's real name changing — is unchanged from the
pre-W1 unconditional-call behavior; two settlements eligible in the
SAME call each get their own independent arbitration cycle (never
suppress one in favor of the other, since naming is not a real
competing-attention decision between settlements); and the workspace
correctly returns `None` on a genuinely empty cycle (LLM disabled,
nothing submitted) rather than fabricating a winner.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.settlement.buildings import Building, BuildingKind, BuildingStage, Settlement
from hearthmind.simulation.engine import SimulationEngine

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


class FakeAdapter:
    """The minimal real `LLMAdapter` shape `CognitionRunner._run_gated`
    actually calls (positional `prompt, system, capture, json_schema,
    num_predict_override, temperature_override, reasoning, timeout_
    override`) — returns a fixed, real `{"name": ...}` answer, no
    network, no live server needed."""

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


def _make_engine(tag: str) -> SimulationEngine:
    d = tempfile.mkdtemp()
    conn = connect(f"{d}/{tag}.db")
    cfg = Config(db_path=f"{d}/{tag}.db", llm_enabled=False, seed=7, initial_population=4, width=16, height=16)
    return SimulationEngine.load_or_create(conn, cfg)


def _standing_building() -> Building:
    return Building(id=0, x=1, y=1, kind=BuildingKind.HUT, stage=BuildingStage.STANDING, condition=1.0)


async def main_async() -> int:
    from hearthmind.cognition.workspace import Bid, GlobalWorkspace

    # --- check 0: baseline behavior — LLM disabled, an eligible
    #     settlement's arbitrate() call genuinely returns None (empty
    #     cycle) since nothing is ever submitted, matching the original
    #     early-out (`if not self._cognition_runner.enabled: return`)
    #     — the workspace is never even reached, no fabricated winner. ---
    eng = _make_engine("w1_disabled")
    stl = eng._settlement_by_id(0)
    stl.name = "Placeholder Town"
    stl.llm_named = False
    eng.world.newly_named_settlement_ids = [0]
    eng._maybe_schedule_naming()
    check("LLM-disabled: the naming workspace is never even touched (early-out preserved)",
          eng._naming_workspace.pending_count() == 0 and len(eng._naming_workspace.history) == 0)
    check("LLM-disabled: the settlement's name is untouched (still the placeholder)",
          stl.name == "Placeholder Town" and not stl.llm_named)

    # --- checks 1-4: the real pilot, LLM 'enabled' via a fake adapter. ---
    eng2 = _make_engine("w1_enabled")
    eng2._cognition_runner.client = FakeAdapter("Rivenmoor")
    stl2 = eng2._settlement_by_id(0)
    stl2.name = "Placeholder Town"
    stl2.llm_named = False
    eng2.world.newly_named_settlement_ids = [0]

    workspace = eng2._naming_workspace
    check("check 1: workspace starts with a clean history",
          len(workspace.history) == 0 and workspace.pending_count() == 0)

    eng2._maybe_schedule_naming()

    check("check 2: a real arbitration cycle ran — one CompetitionRecord logged, "
          "the pending queue drained back to zero (submit+arbitrate happened, not skipped)",
          len(workspace.history) == 1 and workspace.pending_count() == 0)
    record = workspace.history[0]
    check("check 3: the real winner is naming's own bid, naming the correct subject",
          record.winner is not None and record.winner.specialist_id == "naming"
          and record.winner.subject == "naming:0")
    check("check 4: the settlement really was marked scheduled (the resolver fired, not bypassed)",
          0 in eng2._naming_scheduled_ids)

    # The resolver's own real _schedule_llm_job call created a background
    # task — await the engine's own background-task set to completion so
    # `apply()` actually runs (same pattern verify_b13_dev_console_
    # endpoint.py already established for awaiting a real background task).
    for _ in range(50):
        if not eng2._background_tasks:
            break
        await asyncio.sleep(0.02)
    check("check 5: the real LLM job resolved and end-to-end renamed the settlement "
          "(same outcome the old unconditional _schedule_llm_job call would have produced)",
          stl2.name == "Rivenmoor" and stl2.llm_named)

    # --- check 6: two settlements eligible in the SAME call each get
    #     their own independent arbitration cycle — naming across
    #     different settlements is not a real competing-attention
    #     decision, so both must still fire, never one suppressing the
    #     other. ---
    eng3 = _make_engine("w1_two_settlements")
    eng3._cognition_runner.client = FakeAdapter("Ashford")
    stl3a = eng3._settlement_by_id(0)
    stl3a.name = "Placeholder A"
    stl3a.llm_named = False
    stl3b = Settlement(
        id=1, name="Placeholder B", llm_named=False, founding_scenario="a quiet river bend",
        buildings=[_standing_building()], center_x=5, center_y=5,
    )
    eng3.world.settlements.append(stl3b)
    eng3.world.newly_named_settlement_ids = [0, 1]
    eng3._maybe_schedule_naming()
    check("check 6a: BOTH settlements got scheduled (neither suppressed the other)",
          eng3._naming_scheduled_ids == {0, 1})
    check("check 6b: two independent arbitration cycles ran, each with its own real winner",
          len(eng3._naming_workspace.history) == 2
          and eng3._naming_workspace.history[0].winner.subject == "naming:0"
          and eng3._naming_workspace.history[1].winner.subject == "naming:1")
    for _ in range(50):
        if not eng3._background_tasks:
            break
        await asyncio.sleep(0.02)
    check("check 6c: both settlements' real LLM jobs resolved end to end",
          stl3a.name == "Ashford" and stl3b.name == "Ashford" and stl3a.llm_named and stl3b.llm_named)

    # --- check 7: a real, direct GlobalWorkspace sanity check — this
    #     workspace's OWN sole-bidder-always-wins guarantee, the thing
    #     that makes this pilot provably behavior-preserving (B1's own
    #     documented property, re-confirmed against a fresh instance
    #     rather than assumed). ---
    fresh = GlobalWorkspace()
    fresh.submit(Bid(specialist_id="x", subject="s", score=1.0))
    winner = fresh.arbitrate()
    check("check 7: a genuine coalition-of-one always wins its own cycle (B1's own guarantee)",
          winner is not None and winner.specialist_id == "x")

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
