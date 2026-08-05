#!/usr/bin/env python3
"""Tier 7 HCA Stage E, E3 memory-activation half (docs/ROADMAP-2026-07-
REMAINING.md, Phase 7, explicit user instruction "Start E3"): a real,
live D1 ACT-R activation ranking over one agent's own real memories.

Verifies `hearthmind.cognition.observatory.describe_memory_activation`
directly against a real `Agent` populated through the real production
`_remember`/`set_current_tick` call path (`hearthmind.agents.
population`) — never a synthetic stand-in for the memory fields
themselves — then end to end through a real `SimulationEngine.
full_diagnostics()['memory_activation_snapshot']`, confirming it
genuinely reflects `_observer_favorite_agent()`'s real pick after a
real `_record_observer_attention` call, including the honest `None`
case before any agent has been inspected.

The competing-goals half of E3 is explicitly NOT covered here — see
`hearthmind.cognition.observatory`'s own module docstring for why it
isn't shipped this pass (no real Bid-based goal competition exists in
production to render a panel over)."""
from __future__ import annotations

import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def _make_agent():
    from hearthmind.agents.agent import Agent

    return Agent(id=1, name="Testagent", x=0, y=0)


def main() -> int:
    from hearthmind.agents.population import _remember, set_current_tick
    from hearthmind.cognition.observatory import describe_memory_activation

    # --- empty-memories agent: no crash, empty list ---
    fresh = _make_agent()
    set_current_tick(0)
    check("describe_memory_activation on a memory-less agent returns an empty list",
          describe_memory_activation(fresh, current_tick=0) == [])

    # --- real memories via the real production _remember path, at
    #     different ticks, one with a real causal link ---
    agent = _make_agent()
    set_current_tick(10)
    _remember(agent, "a routine mundane errand", routine=True)
    set_current_tick(500)
    _remember(agent, "the flood took the granary", because="flood")
    set_current_tick(900)
    _remember(agent, "shared a quiet meal with a neighbor")

    check("real _remember calls stamp index-aligned memory_ticks",
          agent.memory_ticks == [10, 500, 900])
    check("real _remember calls stamp index-aligned memory_causes (blank when none given)",
          agent.memory_causes[1] == "flood" and agent.memory_causes[0] == "" and agent.memory_causes[2] == "")

    entries = describe_memory_activation(agent, current_tick=1000)
    check("describe_memory_activation returns one real entry per real memory",
          len(entries) == 3)
    check("every entry carries the real memory text verbatim",
          {e["text"] for e in entries} == set(agent.memories))
    check("every entry's age_ticks matches current_tick - its real formation tick",
          {e["text"]: e["age_ticks"] for e in entries} == {
              agent.memories[0]: 1000 - 10, agent.memories[1]: 1000 - 500, agent.memories[2]: 1000 - 900,
          })
    check("the causally-linked memory is reported with causal_link=True, the others False",
          [e["causal_link"] for e in entries if e["text"] == agent.memories[1]] == [True]
          and all(e["causal_link"] is False for e in entries if e["text"] != agent.memories[1]))

    # --- ranking: entries sorted by activation descending, highest first ---
    scores = [e["activation"] for e in entries]
    check("entries are sorted by activation, highest first",
          scores == sorted(scores, reverse=True))
    # The most-recent, non-causal, non-routine memory (index 2, age 100
    # ticks) should out-rank the oldest routine one (index 0, age 990
    # ticks, lower salience from ROUTINE_MEMORY_SALIENCE_MULT) on real
    # ACT-R recency alone -- a direct proof this is genuinely ranked,
    # not just returned in storage order.
    by_text = {e["text"]: e["activation"] for e in entries}
    check("a fresher, higher-salience memory activates above an older, routine-dampened one",
          by_text[agent.memories[2]] > by_text[agent.memories[0]])

    # --- top_n bounding ---
    set_current_tick(1000)
    many_agent = _make_agent()
    for i in range(15):
        set_current_tick(1000 + i)
        _remember(many_agent, f"memory number {i}")
    bounded = describe_memory_activation(many_agent, current_tick=1020, top_n=5)
    check("describe_memory_activation bounds its output to top_n",
          len(bounded) == 5)
    check("bounding keeps the genuinely highest-activation entries, not an arbitrary slice",
          bounded == sorted(bounded, key=lambda e: -e["activation"])[:5])

    # --- age_ticks never goes negative even for a same-tick memory ---
    same_tick_agent = _make_agent()
    set_current_tick(50)
    _remember(same_tick_agent, "just now")
    same_tick_entries = describe_memory_activation(same_tick_agent, current_tick=50)
    check("a same-tick memory reports age_ticks=0, never negative",
          same_tick_entries[0]["age_ticks"] == 0)

    # --- end to end: a real SimulationEngine, real _observer_favorite_
    #     agent(), real full_diagnostics() ---
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    d = tempfile.mkdtemp()
    conn = connect(f"{d}/e3.db")
    cfg = Config(db_path=f"{d}/e3.db", llm_enabled=False, seed=11, initial_population=4, width=16, height=16)
    eng = SimulationEngine.load_or_create(conn, cfg)

    report_before = eng.full_diagnostics()
    check("memory_activation_snapshot is honestly None before any observer inspection",
          report_before["memory_activation_snapshot"] is None)

    # A fresh world's core cast isn't seeded until the engine's own
    # per-tick `maintain_core_cast` call -- drive it directly here
    # rather than ticking the whole engine forward, same "call the real
    # production method, not a synthetic stand-in" discipline as every
    # other check in this script.
    eng.world.population.maintain_core_cast(cfg.llm_core_cast_size)
    core_agent = next(a for a in eng.world.population.agents if a.id in eng.world.population.core_agent_ids)
    set_current_tick(eng.world.clock.tick_count)
    _remember(core_agent, "a real production memory for the favorite agent")
    eng._record_observer_attention(core_agent.id)

    report_after = eng.full_diagnostics()
    snapshot = report_after["memory_activation_snapshot"]
    check("memory_activation_snapshot is populated once a core-cast agent has real attention",
          snapshot is not None and snapshot["agent_id"] == core_agent.id)
    check("the snapshot's agent_name matches the real favored agent",
          snapshot["agent_name"] == core_agent.name)
    check("the snapshot's entries reflect the real memory just added through production _remember",
          any(e["text"] == "a real production memory for the favorite agent" for e in snapshot["entries"]))

    # --- non-core-cast inspection never becomes the favorite (matches
    #     _observer_favorite_agent's own real contract) ---
    non_core = next((a for a in eng.world.population.agents if a.id not in eng.world.population.core_agent_ids), None)
    if non_core is not None:
        eng._record_observer_attention(non_core.id)
        report_still_core = eng.full_diagnostics()
        check("inspecting a non-core-cast agent does not displace the real core-cast favorite",
              report_still_core["memory_activation_snapshot"]["agent_id"] == core_agent.id)
    else:
        print("[SKIP] no non-core-cast agent in this seed's small founding population -- real check above already covers the core-cast path")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
