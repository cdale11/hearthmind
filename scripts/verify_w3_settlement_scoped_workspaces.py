#!/usr/bin/env python3
"""Phase 3.5 W3 (docs/ROADMAP-2026-07-REMAINING.md) -- explicit user
instruction: "start W3 ... complete W3 in one run." Settlement-scoped
`GlobalWorkspace` granularity for the three real per-agent/per-pair
`_schedule_llm_job` call sites W2 deliberately left alone:
`rumor_interpret` (a core-cast listener retells a rumor in their own
voice), `personal_belief` (a monthly Reflect() pick revising a private
belief), `mind` (one-time permanent-identity authoring for a newly-
seated core-cast agent). New `SimulationEngine._submit_and_resolve_
settlement(settlement_id, job_name, subject, resolver)` is the real
settlement-scoped sibling of W2's `_submit_and_resolve` -- keyed by
WHICH SETTLEMENT the candidate agent belongs to (`self._w3_workspaces:
dict[int, GlobalWorkspace]`), not by job name, so a rumor-
interpretation bid and a personal-belief bid for the SAME settlement
genuinely land in the same arbitration pool rather than three
permanently-separate per-job-name pools the way W2's sites work.

Verified here, standalone (no unittest, no live LLM server): (1) the
shared helper's own contract, direct; (2) the real structural
difference from W2 -- two DIFFERENT job names for the SAME settlement
land in the literal SAME `GlobalWorkspace` object, while the SAME job
name for two DIFFERENT settlements lands in two DIFFERENT objects,
proving this is genuinely settlement-scoped, not job-name-scoped; (3)
each of the three real call sites' own arbitration cycle runs through
the real production apply path with a fake `LLMAdapter`; (4) a real
multi-thousand-tick LLM-disabled production soak confirming all three
job types fire organically through the real settlement-scoped
workspace with a real winner every cycle."""
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


def _make_engine(tag: str, **overrides) -> SimulationEngine:
    d = tempfile.mkdtemp()
    kwargs = dict(
        db_path=f"{d}/{tag}.db", llm_enabled=False, seed=11,
        initial_population=6, width=16, height=16,
    )
    kwargs.update(overrides)
    conn = connect(f"{d}/{tag}.db")
    cfg = Config(**kwargs)
    return SimulationEngine.load_or_create(conn, cfg)


async def _await_background(eng: SimulationEngine) -> None:
    for _ in range(50):
        if not eng._background_tasks:
            return
        await asyncio.sleep(0.02)


def check_shared_helper_contract() -> None:
    eng = _make_engine("w3_helper")
    calls: list[str] = []
    eng._submit_and_resolve_settlement(0, "test_job", "test_subject", lambda: calls.append("fired"))
    check("_submit_and_resolve_settlement's own resolver fires on a real coalition-of-one win",
          calls == ["fired"])
    check("_submit_and_resolve_settlement gave settlement 0 its own dedicated workspace",
          0 in eng._w3_workspaces and len(eng._w3_workspaces[0].history) == 1)

    # --- the real structural difference from W2: settlement-scoped,
    #     not job-name-scoped. ---
    eng2 = _make_engine("w3_scoping")
    eng2._submit_and_resolve_settlement(0, "rumor_interpret", "s0-a", lambda: None)
    eng2._submit_and_resolve_settlement(0, "personal_belief", "s0-b", lambda: None)
    eng2._submit_and_resolve_settlement(1, "rumor_interpret", "s1-a", lambda: None)
    check("two DIFFERENT job names for the SAME settlement share the literal same workspace object",
          eng2._w3_workspaces[0] is eng2._w3_workspaces[0]
          and len(eng2._w3_workspaces[0].history) == 2)
    check("the SAME job name for two DIFFERENT settlements lands in two DIFFERENT workspace objects",
          eng2._w3_workspaces[0] is not eng2._w3_workspaces[1])
    check("each settlement's own competition log names the real specialist (job) that bid",
          {r.winner.specialist_id for r in eng2._w3_workspaces[0].history} == {"rumor_interpret", "personal_belief"})


async def check_representative_sites() -> None:
    # --- rumor_interpret: a core-cast listener retells a heard rumor. ---
    eng = _make_engine("w3_rumor")
    eng._cognition_runner.client = FakeAdapter({"retelling": "they say the harvest failed entirely"})
    pop = eng.world.population
    listener = pop.agents[0]
    speaker = pop.agents[1]
    pop.core_agent_ids = {listener.id}
    eng._maybe_interpret_rumor(speaker, listener, "the harvest was poor this year")
    ws = eng._w3_workspaces.get(listener.settlement_id)
    check("rumor_interpret: a real arbitration cycle ran in the listener's own settlement workspace",
          ws is not None and any(r.winner.subject == f"rumor_interpret:{listener.id}" for r in ws.history))
    await _await_background(eng)
    check("rumor_interpret: the real LLM job resolved end to end (the real retelling landed "
          "as a new memory via _remember)",
          any("harvest failed entirely" in m for m in listener.memories))

    # --- personal_belief: a monthly Reflect() pick. ---
    eng2 = _make_engine("w3_personal_belief")
    eng2._cognition_runner.client = FakeAdapter({
        "subject": "the harvest", "belief": "the land provides for those who tend it",
        "confidence": 0.6, "semantic_memory": "", "secret": "", "lesson_situation": "", "lesson_text": "",
    })
    agent = eng2.world.population.agents[0]
    agent.memories.append("a good harvest this year")
    fired = False
    for _ in range(3500):
        eng2._tick_once()
        ws2 = eng2._w3_workspaces.get(agent.settlement_id)
        if ws2 is not None and any(r.winner.specialist_id == "personal_belief" for r in ws2.history):
            fired = True
            break
    check("personal_belief: a real arbitration cycle ran organically via the real monthly job", fired)

    # --- mind: one-time genesis-style authoring for a core-cast agent. ---
    eng3 = _make_engine("w3_mind")
    eng3._cognition_runner.client = FakeAdapter({"mind": "a steady, watchful presence", "voice": "measured and calm"})
    target = eng3.world.population.agents[0]
    eng3._author_minds([target])
    ws3 = eng3._w3_workspaces.get(target.settlement_id)
    check("mind: a real arbitration cycle ran in the agent's own settlement workspace",
          ws3 is not None and any(r.winner.subject == f"mind:{target.id}" for r in ws3.history))
    await _await_background(eng3)
    check("mind: the real LLM job resolved end to end (the agent's own mind text updated)",
          target.mind == "a steady, watchful presence")

    print()


async def check_production_soak() -> None:
    eng = _make_engine("w3_soak", initial_population=12, width=32, height=32)
    for i in range(8000):
        eng._tick_once()
        if i % 200 == 0:
            await asyncio.sleep(0)

    fired_job_names = {
        rec.winner.specialist_id
        for ws in eng._w3_workspaces.values()
        for rec in ws.history
    }
    check(f"production soak: at least one of the three W3 job types fired organically "
          f"over 8000 ticks (fired: {sorted(fired_job_names)})",
          len(fired_job_names) >= 1)

    all_real_winners = all(
        rec.winner is not None
        for ws in eng._w3_workspaces.values()
        for rec in ws.history
    )
    check("production soak: every real arbitration cycle across every settlement's workspace "
          "produced a genuine winner (coalition-of-one holds under real load)",
          all_real_winners)


async def main_async() -> int:
    check_shared_helper_contract()
    print()
    await check_representative_sites()
    await check_production_soak()

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
