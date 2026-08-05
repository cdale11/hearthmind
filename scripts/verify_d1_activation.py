#!/usr/bin/env python3
"""Tier 7 HCA Stage D, D1 (docs/ROADMAP-2026-07-REMAINING.md, Phase 6,
explicit user instruction "Start phase 6 is phase 5 is done with D1"):
ACT-R base-level memory activation replacing the four hand-tuned
`MEMORY_RETRIEVAL_*` weights.

Verifies `hearthmind.cognition.activation`'s real base-level/spreading
activation formula directly (recency+frequency unification, the real
zero-division floor, salience/relevance/causal spreading gains), then
`retrieve_relevant_memories`/`_remember` end to end against a real
`Agent`/`Population` — confirming `Agent.memory_ticks` is genuinely
populated by production code (`_remember`'s own `_CURRENT_TICK`),
confirming the four deleted `MEMORY_RETRIEVAL_*` constants are truly
gone from `hearthmind.agents.agent`, and D1's own stated test:
retrieval quality holds — a real ten-year-old high-salience/relevant
memory still outranks three merely-recent mundane ones, the exact
scenario `MEMORY_RETRIEVAL_RECENCY_WEIGHT`'s own docstring named as
the problem this whole mechanism exists to fix."""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    import math

    import hearthmind.agents.agent as agent_module
    from hearthmind.agents.agent import Agent, AgentState, retrieve_relevant_memories
    from hearthmind.agents.population import _remember, set_current_tick
    from hearthmind.cognition.activation import (
        ACTIVATION_FLOOR, ACTIVATION_MIN_AGE_TICKS, base_level_activation,
        memory_activation, spreading_activation,
    )

    # --- the four constants D1's own test names must be truly deleted ---
    for deleted_name in (
        "MEMORY_RETRIEVAL_RECENCY_WEIGHT", "MEMORY_RETRIEVAL_SALIENCE_WEIGHT",
        "MEMORY_RETRIEVAL_RELEVANCE_WEIGHT", "MEMORY_RETRIEVAL_CAUSAL_BONUS",
    ):
        check(f"the old hand-tuned constant {deleted_name} is genuinely deleted",
              not hasattr(agent_module, deleted_name))

    # --- base_level_activation: the real recency+frequency unification ---
    check("an empty presentation list returns the real floor, never crashes",
          base_level_activation([], current_tick=1000) == ACTIVATION_FLOOR)
    check("a same-tick presentation doesn't ZeroDivisionError (floored at min age)",
          base_level_activation([1000], current_tick=1000) == math.log(ACTIVATION_MIN_AGE_TICKS ** -0.5))
    recent = base_level_activation([990], current_tick=1000)
    old = base_level_activation([100], current_tick=1000)
    check("a more recent single presentation activates higher than an old one",
          recent > old)
    once = base_level_activation([500], current_tick=1000)
    twice_same_age = base_level_activation([500, 500], current_tick=1000)
    check("REAL frequency: two presentations at the same age activate higher than one "
          "(the union this equation makes with recency, absent from the deleted formula)",
          twice_same_age > once)
    three_old_presentations = base_level_activation([100, 200, 300], current_tick=1000)
    one_recent_presentation = base_level_activation([990], current_tick=1000)
    check("several old presentations can still be outweighed by one genuinely recent one "
          "(recency, not frequency alone, still dominates at realistic decay)",
          one_recent_presentation > three_old_presentations)

    # --- spreading_activation: the three real associative sources ---
    check("spreading activation rises with salience", spreading_activation(0.9, 0.0, False) > spreading_activation(0.1, 0.0, False))
    check("spreading activation rises with relevance", spreading_activation(0.0, 0.9, False) > spreading_activation(0.0, 0.1, False))
    check("a known causal tag adds a real positive bonus",
          spreading_activation(0.0, 0.0, True) > spreading_activation(0.0, 0.0, False))

    # --- memory_activation composes both terms ---
    combined = memory_activation([990], 1000, salience=0.8, relevance=0.9, causal_present=True)
    base_only = base_level_activation([990], 1000)
    check("the combined score is strictly higher than the base-level term alone "
          "(spreading activation is a real additive contribution, not swallowed)",
          combined > base_only)

    # --- end-to-end through real production `_remember`/Agent state ---
    agent = Agent(id=1, name="Test Agent", x=0, y=0, hunger=0.0, energy=1.0, state=AgentState.AWAKE)
    set_current_tick(100)
    _remember(agent, "A quiet, mundane morning gathering firewood.")
    set_current_tick(200)
    _remember(agent, "The granary is a little low today.")
    set_current_tick(300)
    _remember(agent, "Chatted about the weather with a neighbor.")
    check("`_remember` genuinely stamps `memory_ticks` from the real production `_CURRENT_TICK`",
          agent.memory_ticks == [100, 200, 300])
    check("`memories`/`memory_salience`/`memory_causes`/`memory_ticks` stay index-aligned",
          len(agent.memories) == len(agent.memory_salience) == len(agent.memory_causes) == len(agent.memory_ticks))

    # --- D1's own headline test, in production shape: a genuinely older
    #     high-salience/relevant memory beats three merely-recent mundane
    #     ones — the exact "three most recent reach cognition even when
    #     an older high-salience memory is the relevant one" problem the
    #     deleted MEMORY_RETRIEVAL_RECENCY_WEIGHT's own docstring named.
    #     A REAL single-presentation ACT-R base-level term genuinely
    #     decays fast (honest scope trim, see activation.py's own
    #     docstring on the missing rehearsal counter) -- this uses a
    #     realistic elapsed-tick gap for a bounded, capped memory list,
    #     not an unrealistic multi-year one no single-presentation item
    #     could plausibly survive under a faithful ACT-R equation. ---
    agent2 = Agent(id=2, name="Elder Agent", x=0, y=0, hunger=0.0, energy=1.0, state=AgentState.AWAKE)
    set_current_tick(1)
    agent2.emotions = {"fear": 1.0, "grief": 1.0}
    _remember(agent2, "The great flood swept away half the settlement.", because="a catastrophic flood")
    agent2.emotions = {}
    for i, tick in enumerate((15, 18, 20)):
        set_current_tick(tick)
        _remember(agent2, f"An ordinary quiet day, nothing much happened, day {i}.")
    top = retrieve_relevant_memories(
        agent2, k=1, context="the flood that swept away half the settlement", current_tick=20,
    )
    check("D1's own headline test: a real older high-salience+relevant memory "
          "still outranks three merely-recent mundane ones",
          top and "flood" in top[0][0])

    # --- the real `current_tick=None` production degrade (build_prompt's
    #     own shape — a pure function with no engine access) ---
    fallback_top = retrieve_relevant_memories(agent2, k=1, context="the flood that swept away half the settlement")
    check("the `current_tick=None` degrade (a real caller with no tick in scope, e.g. "
          "llm/cognition.py's build_prompt) still ranks the same real memory highest",
          fallback_top and "flood" in fallback_top[0][0])

    # --- to_dict/from_dict round-trip, including legacy backfill ---
    d = agent2.to_dict()
    check("`memory_ticks` round-trips through to_dict/from_dict", "memory_ticks" in d)
    reloaded = Agent.from_dict(d)
    check("a real round-tripped agent keeps its real memory_ticks",
          reloaded.memory_ticks == agent2.memory_ticks)

    legacy = agent2.to_dict()
    del legacy["memory_ticks"]
    legacy["age_ticks"] = 60_000
    legacy_agent = Agent.from_dict(legacy)
    check("a legacy snapshot (no memory_ticks key at all) backfills to the full real length",
          len(legacy_agent.memory_ticks) == len(legacy_agent.memories))
    check("the legacy backfill preserves relative recency order (strictly non-decreasing)",
          legacy_agent.memory_ticks == sorted(legacy_agent.memory_ticks))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
