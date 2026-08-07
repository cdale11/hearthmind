#!/usr/bin/env python3
"""Roadmap Phase 3, E3's "competing-goals half" (docs/ROADMAP-2026-07-
REMAINING.md, explicit user instruction "start e3"): the real, new
per-agent goal-arbitration mechanism (`hearthmind.cognition.goal_
arbitration`), its opt-in wiring into `llm.cognition.fallback_goal`,
and its real production wiring into `SimulationEngine` (bounded to the
core cast, pruned every tick, surfaced via `full_diagnostics()
['goal_competition_snapshot']`)."""
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
    from hearthmind.agents.agent import (
        EMOTION_ANGER, EMOTION_FEAR, EMOTION_GRIEF, EMOTION_JOY,
        TRAIT_AMBITION, TRAIT_OPENNESS, TRAIT_SOCIABILITY, AgentGoal,
    )
    from hearthmind.cognition.goal_arbitration import (
        GOAL_ARBITRATION_SPECIALIST_ID,
        arbitrate_content_goal, compute_content_goal_bids,
    )
    from hearthmind.cognition.observatory import workspace_snapshot
    from hearthmind.cognition.workspace import Domain, GlobalWorkspace
    from hearthmind.llm.cognition import fallback_goal

    # --- compute_content_goal_bids: real, correctly-scored bids ---
    bids = compute_content_goal_bids({}, {})
    check("compute_content_goal_bids returns exactly 3 bids for a neutral agent", len(bids) == 3)
    check("every bid carries the shared specialist_id",
          all(b.specialist_id == GOAL_ARBITRATION_SPECIALIST_ID for b in bids))
    check("every bid is WORLD-domain", all(b.domain is Domain.WORLD for b in bids))
    check("subjects are exactly the three real content goals",
          {b.subject for b in bids} == {AgentGoal.SOCIALIZE.value, AgentGoal.GATHER.value, AgentGoal.WANDER.value})
    check("a neutral agent's three bids score identically (base score, no trait term)",
          len({round(b.score, 6) for b in bids}) == 1)
    check("every score is strictly positive (required for B2 staleness gain to behave)",
          all(b.score > 0.0 for b in bids))

    ambitious = compute_content_goal_bids({TRAIT_AMBITION: 1.0}, {})
    by_subject = {b.subject: b.score for b in ambitious}
    check("a standout ambition raises GATHER's score above SOCIALIZE/WANDER",
          by_subject[AgentGoal.GATHER.value] > by_subject[AgentGoal.SOCIALIZE.value]
          and by_subject[AgentGoal.GATHER.value] > by_subject[AgentGoal.WANDER.value])

    sociable = compute_content_goal_bids({TRAIT_SOCIABILITY: 1.0}, {EMOTION_JOY: 1.0})
    by_subject = {b.subject: b.score for b in sociable}
    check("a standout sociability + joy raises SOCIALIZE's score above the other two",
          by_subject[AgentGoal.SOCIALIZE.value] > by_subject[AgentGoal.GATHER.value]
          and by_subject[AgentGoal.SOCIALIZE.value] > by_subject[AgentGoal.WANDER.value])

    open_angry = compute_content_goal_bids({TRAIT_OPENNESS: 1.0}, {EMOTION_ANGER: 1.0})
    by_subject = {b.subject: b.score for b in open_angry}
    check("a standout openness + anger raises WANDER's score above the other two",
          by_subject[AgentGoal.WANDER.value] > by_subject[AgentGoal.GATHER.value]
          and by_subject[AgentGoal.WANDER.value] > by_subject[AgentGoal.SOCIALIZE.value])

    # --- arbitrate_content_goal: real workspace cycle, real shape ---
    ws = GlobalWorkspace()
    result = arbitrate_content_goal(ws, {TRAIT_AMBITION: 1.0}, {})
    check("arbitrate_content_goal returns the {goal, reason} shape",
          set(result) == {"goal", "reason"})
    check("a real trait standout genuinely wins its own cycle",
          result["goal"] == AgentGoal.GATHER.value)
    check("the workspace recorded exactly one real cycle",
          len(ws.history) == 1 and ws.history[0].winner is not None)
    check("the recorded winner has real losers (a genuine 3-bid competition, not a coalition of one)",
          len(ws.history[0].losers) == 2)

    # --- headline test: staleness gain gives a genuinely neutral agent
    #     real variety over many cycles, not a fixed winner forever ---
    ws2 = GlobalWorkspace()
    seen_goals: set[str] = set()
    for _ in range(12):
        r = arbitrate_content_goal(ws2, {}, {})
        seen_goals.add(r["goal"])
    check("a genuinely tied (neutral-trait) agent visits all three goals over 12 real cycles "
          "(staleness gain rotates the winner, not a fixed choice)",
          seen_goals == {AgentGoal.SOCIALIZE.value, AgentGoal.GATHER.value, AgentGoal.WANDER.value})

    # --- workspace_snapshot (E2's own generic function) renders any
    #     goal workspace with zero new "describe" function needed ---
    snap = workspace_snapshot(ws2, recent=5)
    check("workspace_snapshot renders real goal-arbitration cycles",
          len(snap) == 5 and all(c["winner"] is not None for c in snap))

    # --- fallback_goal: goal_workspace=None reproduces the exact prior
    #     id%3/trait-standout behavior byte-for-byte (the required
    #     backward-compatibility proof) ---
    for aid in range(9):
        before = fallback_goal(0.1, 0.9, agent_id=aid, traits={}, emotions={})
        after = fallback_goal(0.1, 0.9, agent_id=aid, traits={}, emotions={}, goal_workspace=None)
        check(f"agent_id={aid}: goal_workspace=None is a byte-for-byte no-op vs. the old default",
              before == after)

    # --- fallback_goal: goal_workspace real wiring, only reached once
    #     goal_policy is None and every forced branch has ruled itself
    #     out ---
    # Below TRAIT_NOTABLE_THRESHOLD (0.3) so `fallback_goal`'s own
    # pre-existing trait-STANDOUT override branch stays unreached — the
    # goal_workspace branch is what actually resolves this, not a
    # coincidental match with the older override.
    ws3 = GlobalWorkspace()
    r = fallback_goal(0.1, 0.9, agent_id=3, traits={TRAIT_AMBITION: 0.2}, emotions={}, goal_workspace=ws3)
    check("fallback_goal's goal_workspace branch fires for a content agent and reflects real ambition",
          r["goal"] == AgentGoal.GATHER.value and len(ws3.history) == 1)

    # --- fallback_goal: every forced branch stays a real override even
    #     with a goal_workspace supplied — the arbitration mechanism
    #     never gets a say over a genuine emergency ---
    ws4 = GlobalWorkspace()
    hungry = fallback_goal(0.9, 0.9, agent_id=1, traits={}, emotions={}, goal_workspace=ws4)
    check("SURVIVAL_HUNGER override still wins with a goal_workspace present",
          hungry["goal"] == AgentGoal.FORAGE.value)
    check("the forced hunger branch never touches the goal_workspace at all",
          len(ws4.history) == 0)

    ws5 = GlobalWorkspace()
    tired = fallback_goal(0.1, 0.1, agent_id=1, traits={}, emotions={}, goal_workspace=ws5)
    check("SURVIVAL_ENERGY override still wins with a goal_workspace present",
          tired["goal"] == AgentGoal.REST.value)
    check("the forced energy branch never touches the goal_workspace at all",
          len(ws5.history) == 0)

    ws6 = GlobalWorkspace()
    fearful = fallback_goal(0.1, 0.9, agent_id=1, traits={}, emotions={EMOTION_FEAR: 0.9}, goal_workspace=ws6)
    check("a real fear override still wins with a goal_workspace present",
          fearful["goal"] == AgentGoal.REST.value and len(ws6.history) == 0)

    ws7 = GlobalWorkspace()
    grieving = fallback_goal(0.1, 0.9, agent_id=1, traits={}, emotions={EMOTION_GRIEF: 0.9}, goal_workspace=ws7)
    check("a real grief override still wins with a goal_workspace present",
          grieving["goal"] == AgentGoal.WANDER.value and len(ws7.history) == 0)

    ws8 = GlobalWorkspace()
    starving_village = fallback_goal(
        0.1, 0.9, agent_id=1, traits={}, emotions={}, materials_critical=True, goal_workspace=ws8,
    )
    check("materials_critical override still wins with a goal_workspace present",
          starving_village["goal"] == AgentGoal.GATHER.value and len(ws8.history) == 0)

    # --- goal_policy keeps its existing priority over goal_workspace
    #     (the deliberate, documented precedence order) ---
    class _FixedGoalPolicy:
        def sample_goal(self, state, rng, allowed_goals=None):
            return AgentGoal.WANDER.value

    ws9 = GlobalWorkspace()
    r = fallback_goal(
        0.1, 0.9, agent_id=1, traits={}, emotions={},
        goal_policy=_FixedGoalPolicy(), goal_workspace=ws9,
    )
    check("a real goal_policy keeps priority over goal_workspace when both are supplied",
          r["goal"] == AgentGoal.WANDER.value)
    check("goal_workspace is never touched when goal_policy already resolved the branch",
          len(ws9.history) == 0)

    # --- real production wiring through SimulationEngine ---
    import asyncio

    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine
    from hearthmind.world.state import World

    def _drive(eng: "SimulationEngine", ticks: int) -> None:
        # `_tick_once` fires real fire-and-forget background tasks
        # (`asyncio.create_task`) regardless of `llm_enabled`, per
        # this codebase's own documented structural fact (see
        # `scripts/verify_b13_5_pacing_genome_evolution.py`'s `_drive`)
        # -- needs a real running event loop even with the LLM off.
        async def _run() -> None:
            for _ in range(ticks):
                eng._tick_once()
            for _ in range(200):
                if not eng._background_tasks:
                    break
                await asyncio.sleep(0.005)
        asyncio.run(_run())

    config = Config(db_path=":memory:", llm_enabled=False, seed=99, initial_population=6)
    world = World.create_new(config)
    conn = connect(":memory:")
    engine = SimulationEngine(conn, config, world)
    # `core_agent_ids` is only populated inside `_tick_once` (`maintain_
    # core_cast` is called there, not in `__init__`) -- one real tick
    # gets a genuine core cast to test against.
    _drive(engine, 1)

    core_id = next(iter(engine.world.population.core_agent_ids), None)
    non_core_candidates = [
        a.id for a in engine.world.population.agents if a.id not in engine.world.population.core_agent_ids
    ]
    check("a fresh engine seeds a real non-empty core cast to test against", core_id is not None)

    ws_core = engine._goal_workspace_for(core_id)
    check("_goal_workspace_for returns a real GlobalWorkspace for a core-cast agent",
          isinstance(ws_core, GlobalWorkspace))
    check("_goal_workspace_for is idempotent (same object on a second call)",
          engine._goal_workspace_for(core_id) is ws_core)
    if non_core_candidates:
        check("_goal_workspace_for returns None for a non-core agent",
              engine._goal_workspace_for(non_core_candidates[0]) is None)
    check("the lazily-created workspace is tracked in self._goal_workspaces",
          core_id in engine._goal_workspaces)

    # --- pruning: a stale id (never in the live core cast) is dropped
    #     from self._goal_workspaces the next time maintain_core_cast
    #     runs. A real living core member can't stand in for this --
    #     discarding it from core_agent_ids risks maintain_core_cast's
    #     own refill logic simply re-adding it the same tick (it's
    #     still alive and may still be the most prominent candidate),
    #     which would make the prune check pass for the wrong reason. A
    #     synthetic id that will never be a real candidate isolates the
    #     prune logic itself. ---
    fake_stale_id = -1
    check("the synthetic id is genuinely not a real agent (sanity check for the test itself)",
          fake_stale_id not in {a.id for a in engine.world.population.agents})
    engine._goal_workspaces[fake_stale_id] = GlobalWorkspace()
    _drive(engine, 1)
    check("a stale id never in the live core cast is pruned from self._goal_workspaces on the next tick",
          fake_stale_id not in engine._goal_workspaces)

    # --- full_diagnostics() surfacing: honest None before any real
    #     favored-agent inspection, populated once one exists ---
    diag_before = engine.full_diagnostics()
    check("full_diagnostics() surfaces goal_competition_snapshot",
          "goal_competition_snapshot" in diag_before)
    check("goal_competition_snapshot is honestly None before any observer inspection",
          diag_before["goal_competition_snapshot"] is None)

    core_id2 = next(iter(engine.world.population.core_agent_ids))
    engine.world.observer_attention["agent_view_counts"] = {core_id2: 3}
    engine.world.observer_attention["last_agent_id"] = core_id2
    real_ws = engine._goal_workspace_for(core_id2)
    fallback_goal(0.1, 0.9, agent_id=core_id2, traits={}, emotions={}, goal_workspace=real_ws)
    snap = engine._goal_competition_snapshot()
    check("_goal_competition_snapshot populates once the favored agent has a real cycle",
          snap is not None and snap["agent_id"] == core_id2 and len(snap["cycles"]) == 1)
    diag_after = engine.full_diagnostics()
    check("full_diagnostics() reflects the same real snapshot",
          diag_after["goal_competition_snapshot"] is not None
          and diag_after["goal_competition_snapshot"]["agent_id"] == core_id2)

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
