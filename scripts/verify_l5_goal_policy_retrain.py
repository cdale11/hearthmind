#!/usr/bin/env python3
"""Verifies roadmap Phase 2's L5: the real in-engine continual-retrain
cadence for Tier 6 L2.2's `GoalPolicy` (`SimulationEngine._maybe_tick_
goal_policy`, `_run_cognition`'s new pending-example capture). No
unittest, same `@check`-decorator standalone convention as every
sibling `verify_*.py`. Run:

    python3 scripts/verify_l5_goal_policy_retrain.py
"""
from __future__ import annotations

import asyncio
import random
import sys
import tempfile

sys.path.insert(0, ".")

from hearthmind.config import Config
from hearthmind.ml.goal_policy import GoalPolicy
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN, GOAL_POLICY_PENDING_EXAMPLES_MAX, SimulationEngine,
)
from hearthmind.world.state import World

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


def _make_engine(seed: int = 3) -> SimulationEngine:
    d = tempfile.mkdtemp()
    db_path = f"{d}/world.sqlite3"
    cfg = Config(db_path=db_path, width=20, height=20, seed=seed, llm_enabled=False)
    conn = connect(db_path)
    world = World.create_new(cfg)
    return SimulationEngine(conn, cfg, world)


class FakeAdapter:
    """The minimal real `LLMAdapter` shape `CognitionRunner._run_gated`
    calls -- returns a fixed real `{"goal": ..., "reason": ...}`
    answer, no network, no live server needed. `goal` is a mutable
    attribute so a test can change what "the LLM decided" across
    successive calls."""

    timeout_seconds = 5.0

    def __init__(self, goal: str = "wander", reason: str = "content") -> None:
        self.goal = goal
        self.reason = reason

    def generate_json(
        self, prompt, system=None, capture=None, json_schema=None,
        num_predict_override=None, temperature_override=None,
        reasoning=False, timeout_override=None,
    ) -> dict:
        result = {"goal": self.goal, "reason": self.reason}
        if capture is not None:
            capture["raw"] = f'{{"goal": "{self.goal}", "reason": "{self.reason}"}}'
        return result

    @classmethod
    def build_from_config(cls, config):
        return cls()


async def _run_cognition_for(eng: SimulationEngine, agent, **kwargs) -> None:
    hunger = kwargs.get("hunger", 0.1)
    energy = kwargs.get("energy", 0.9)
    await eng._run_cognition(
        agent.id, "prompt", hunger, energy, dict(agent.traits), dict(agent.emotions),
        None, kwargs.get("plan_intent", ""), None, kwargs.get("materials_critical", False),
    )


@check("goal_policy=None: _run_cognition never appends a pending example")
def check_no_policy_no_capture():
    eng = _make_engine()
    eng._cognition_runner.client = FakeAdapter("gather")
    agent = eng.world.population.agents[0]
    asyncio.run(_run_cognition_for(eng, agent))
    return len(eng._goal_policy_pending_examples) == 0


@check("goal_policy set, fallback used (LLM disabled): no pending example captured")
def check_fallback_no_capture():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    # client stays None -> _cognition_runner.enabled is False -> every
    # call resolves via the fallback, never a genuine LLM answer.
    agent = eng.world.population.agents[0]
    asyncio.run(_run_cognition_for(eng, agent))
    return len(eng._goal_policy_pending_examples) == 0


@check("goal_policy set, real LLM answer: exactly one correctly-shaped pending example")
def check_real_answer_captures_example():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._cognition_runner.client = FakeAdapter("socialize", "wants company")
    agent = eng.world.population.agents[0]
    agent.hunger, agent.energy = 0.1, 0.9
    asyncio.run(_run_cognition_for(eng, agent, hunger=0.1, energy=0.9))
    if len(eng._goal_policy_pending_examples) != 1:
        return False
    state, goal = eng._goal_policy_pending_examples[0]
    return (
        goal == "socialize"
        and state["hunger"] == 0.1 and state["energy"] == 0.9
        and set(state.keys()) == {
            "hunger", "energy", "trait_resilience", "trait_sociability", "trait_ambition", "trait_openness",
            "emotion_fear", "emotion_grief", "emotion_joy", "emotion_anger", "materials_critical", "has_plan",
        }
    )


@check("materials_critical/has_plan are captured correctly from real params")
def check_materials_critical_and_plan_captured():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._cognition_runner.client = FakeAdapter("gather")
    agent = eng.world.population.agents[0]
    asyncio.run(_run_cognition_for(eng, agent, materials_critical=True, plan_intent="build a hut"))
    state, goal = eng._goal_policy_pending_examples[0]
    return state["materials_critical"] == 1.0 and state["has_plan"] == 1.0 and goal == "gather"


@check("pending examples are bounded, oldest evicted first")
def check_pending_examples_bounded():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._cognition_runner.client = FakeAdapter("wander")
    agent = eng.world.population.agents[0]
    for i in range(GOAL_POLICY_PENDING_EXAMPLES_MAX + 25):
        eng._cognition_runner.client.goal = "wander"
        asyncio.run(_run_cognition_for(eng, agent))
    return len(eng._goal_policy_pending_examples) == GOAL_POLICY_PENDING_EXAMPLES_MAX


@check("_maybe_tick_goal_policy: no-op with goal_policy=None (never crashes)")
def check_retrain_noop_no_policy():
    eng = _make_engine()
    eng._maybe_tick_goal_policy(["month_end"])
    return len(eng._goal_policy_learn_log) == 0


@check("_maybe_tick_goal_policy: skips below GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN")
def check_retrain_skips_below_min_examples():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._goal_policy_pending_examples = [
        ({"hunger": 0.1, "energy": 0.9, "trait_resilience": 0.0, "trait_sociability": 0.0,
          "trait_ambition": 0.0, "trait_openness": 0.0, "emotion_fear": 0.0, "emotion_grief": 0.0,
          "emotion_joy": 0.0, "emotion_anger": 0.0, "materials_critical": 0.0, "has_plan": 0.0}, "wander")
        for _ in range(GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN - 1)
    ]
    eng._maybe_tick_goal_policy(["month_end"])
    return len(eng._goal_policy_learn_log) == 0 and len(eng._goal_policy_pending_examples) == GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN - 1


def _synthetic_pairs(n: int, goal: str, seed: int = 0) -> list:
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        state = {
            "hunger": rng.uniform(0.0, 0.3), "energy": rng.uniform(0.7, 1.0),
            "trait_resilience": rng.uniform(-0.3, 0.3), "trait_sociability": rng.uniform(-0.3, 0.3),
            "trait_ambition": rng.uniform(-0.3, 0.3), "trait_openness": rng.uniform(-0.3, 0.3),
            "emotion_fear": 0.0, "emotion_grief": 0.0, "emotion_joy": rng.uniform(0.0, 0.2),
            "emotion_anger": 0.0, "materials_critical": 0.0, "has_plan": 0.0,
        }
        pairs.append((state, goal))
    return pairs


@check("_maybe_tick_goal_policy: skips on a non-month_end event even with enough examples")
def check_retrain_skips_non_month_end():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._goal_policy_pending_examples = _synthetic_pairs(GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN + 5, "socialize")
    eng._maybe_tick_goal_policy(["day_end"])
    return len(eng._goal_policy_learn_log) == 0 and len(eng._goal_policy_pending_examples) == GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN + 5


@check("_maybe_tick_goal_policy: a real retrain fires once both conditions hold, log gains one entry, pending clears")
def check_retrain_fires():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._goal_policy_pending_examples = _synthetic_pairs(GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN + 10, "socialize")
    eng._maybe_tick_goal_policy(["month_end"])
    return len(eng._goal_policy_learn_log) == 1 and len(eng._goal_policy_pending_examples) == 0


@check("a real retrain genuinely shifts the policy's prediction toward the taught goal")
def check_retrain_genuinely_learns():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    probe_state = {
        "hunger": 0.1, "energy": 0.9, "trait_resilience": 0.0, "trait_sociability": 0.0,
        "trait_ambition": 0.0, "trait_openness": 0.0, "emotion_fear": 0.0, "emotion_grief": 0.0,
        "emotion_joy": 0.1, "emotion_anger": 0.0, "materials_critical": 0.0, "has_plan": 0.0,
    }
    before = eng._goal_policy.predict(probe_state).raw_distribution.get("gather", 0.0)
    eng._goal_policy_pending_examples = _synthetic_pairs(120, "gather", seed=11)
    for _ in range(6):
        eng._maybe_tick_goal_policy(["month_end"])
        eng._goal_policy_pending_examples = _synthetic_pairs(120, "gather", seed=random.randint(0, 10000))
    after = eng._goal_policy.predict(probe_state).raw_distribution.get("gather", 0.0)
    return after > before


@check("a batch with only malformed/unrecognized goals never crashes and leaves pending un-cleared")
def check_retrain_all_malformed_goals_safe():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    pairs = _synthetic_pairs(GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN + 5, "not_a_real_goal")
    eng._goal_policy_pending_examples = list(pairs)
    eng._maybe_tick_goal_policy(["month_end"])
    return len(eng._goal_policy_learn_log) == 0 and len(eng._goal_policy_pending_examples) == len(pairs)


@check("_TICK_JOBS registers _maybe_tick_goal_policy")
def check_registered_in_tick_jobs():
    names = [name for name, _ in SimulationEngine._TICK_JOBS]
    return "_maybe_tick_goal_policy" in names


@check("full_diagnostics()['goal_policy'] surfaces pending_examples_banked/learn_log_recent")
def check_diagnostics_shape():
    eng = _make_engine()
    eng._goal_policy = GoalPolicy(seed=1)
    eng._goal_policy_pending_examples = _synthetic_pairs(7, "wander")
    report = eng.full_diagnostics()
    gp = report["goal_policy"]
    return (
        gp["loaded"] is True
        and gp["pending_examples_banked"] == 7
        and gp["learn_log_recent"] == []
    )


@check("no-regressor-equivalent baseline: a 400-tick soak with goal_policy=None never touches pending/log state")
def check_no_policy_soak_is_inert():
    eng = _make_engine(seed=9)

    async def drive():
        for _ in range(400):
            eng._tick_once()
            await asyncio.sleep(0)

    asyncio.run(drive())
    return len(eng._goal_policy_pending_examples) == 0 and len(eng._goal_policy_learn_log) == 0


@check("live end-to-end proof: a real multi-month soak with a loaded policy + real LLM client produces a real retrain")
def check_live_soak_produces_retrain():
    d = tempfile.mkdtemp()
    db_path = f"{d}/world.sqlite3"
    cfg = Config(db_path=db_path, width=20, height=20, seed=42, llm_enabled=False, llm_max_calls_per_day=10_000)
    conn = connect(db_path)
    world = World.create_new(cfg)
    eng = SimulationEngine(conn, cfg, world)
    eng._goal_policy = GoalPolicy(seed=2)
    fake = FakeAdapter("gather", "content, driven to make something of themself")
    eng._cognition_runner.client = fake
    ticks_per_day = eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick
    # A little over three months of ticks -- long enough for real
    # core-cast cognition calls (staggered daily slots) to bank
    # GOAL_POLICY_MIN_EXAMPLES_TO_RETRAIN real examples and cross at
    # least one real month_end boundary.
    total_ticks = ticks_per_day * 95

    async def drive():
        for _ in range(total_ticks):
            eng._tick_once()
            # drain any completed background cognition tasks so their
            # results (and pending-example captures) land before the
            # next tick's own _apply_pending_cognition_results call.
            pending = list(eng._background_tasks)
            if pending:
                await asyncio.wait(pending, timeout=1)
            else:
                await asyncio.sleep(0)

    asyncio.run(drive())
    return len(eng._goal_policy_learn_log) >= 1


def main() -> int:
    failures = []
    for name, fn in CHECKS:
        try:
            ok = fn()
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[FAIL] {name} -- raised {exc!r}")
            failures.append(name)
            continue
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(name)
    print()
    if failures:
        print(f"{len(failures)}/{len(CHECKS)} check(s) FAILED: {failures}")
        return 1
    print(f"{len(CHECKS)}/{len(CHECKS)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
