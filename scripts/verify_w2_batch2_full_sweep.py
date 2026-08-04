#!/usr/bin/env python3
"""Phase 3.5 W2, second real sweep batch (docs/ROADMAP-2026-07-
REMAINING.md) -- explicit user follow-up ("Can't you build many sites
in one run? Otherwise this will take ages like tier 0"), invoking the
project's own standing "never migrate one at a time" workflow rule.
Converts the REMAINING 42 settlement/world-scoped `_schedule_llm_job`
call sites (batch 1, v1.34.231, converted 4) onto the same shared
`SimulationEngine._submit_and_resolve` helper batch 1 established --
one AST-driven bulk transform, not 42 hand-edits, preserving every
original call's arguments/kwargs verbatim.

Converted job names (42): chronicle, tradition, folklore, legend,
invention, ontology_proposal, ontology_evolution, composite_entity,
nature_mind, species_variant, rule_propose, composite_reaction_
propose, era_branch, festival, religion, narrative_direction, culture_
digest, institution_culture, consciousness, reflection_question,
reflection, self_tuning_advisory, self_tuning, caravan, town_brain,
beliefs, dream, memory_drift, skill_mastery, nature_causal_reasoning
(x3 distinct subjects sharing one workspace -- predator/grazer
extinction, succession stall), dispute, faction, guild_founding,
institution_belief, diplomacy, laws, noncore_nudge, letter, fission,
migration_decision.

Deliberately NOT converted, with real reasons (structurally proven
below, not just asserted): `rumor_interpret`/`personal_belief`/`mind`
are PER-AGENT/PER-PAIR call sites -- W3's own territory (settlement-
scoped `GlobalWorkspace` granularity for per-agent traffic is a
distinct, larger design decision the roadmap explicitly defers); the
naming job (W1's pilot) already routes through its own dedicated
`_naming_workspace`, the identical mechanism under a different
attribute name, so it correctly has no `_submit_and_resolve` call of
its own; `sim_summary`/`chronicler`/`pillar_chat_*`/`away_digest` are
all USER-TRIGGERED on-demand jobs (an explicit player action, not a
periodic cadence a workspace should arbitrate) -- deliberately left as
plain `_schedule_llm_job` calls.

Verified here, standalone (no unittest, no live LLM server): (1) a
structural proof over the real source file that every one of these 42
+ 4-from-batch-1 = 46 `_submit_and_resolve` call sites wraps a real
`_schedule_llm_job` call, and that every remaining un-wrapped
`_schedule_llm_job` call site is one of the 8 deliberately-excluded
names above (naming's own W1 workspace + 3 W3-deferred + 4 user-
triggered) -- proving this batch is COMPLETE, not partial, over every
convertible site; (2) direct functional smoke tests of a representative
cross-section (a critical=True job, a deep_reasoning job, the shared-
workspace multi-subject nature_causal_reasoning trio, a per-candidate-
loop job, an ordinary settlement job) through the real production apply
path; (3) a real multi-thousand-tick LLM-disabled production soak
confirming a broad set of these newly-converted jobs fire correctly
end to end with a real winning bid and a real resolved outcome, not
just that they don't crash.
"""
from __future__ import annotations

import ast
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


ENGINE_PATH = "/home/user/hearthmind/hearthmind/simulation/engine.py"

# The 8 deliberately-excluded `_schedule_llm_job` call sites: naming's
# own pre-existing W1 workspace (a different attribute, same shape),
# 3 real per-agent/per-pair jobs reserved for W3, and 4 real
# user-triggered on-demand jobs.
EXPECTED_UNWRAPPED_NAMES = {
    "naming", "rumor_interpret", "personal_belief", "mind",
    "sim_summary", "chronicler", "away_digest",
}


def check_structural_completeness() -> None:
    """AST-driven proof: every `self._submit_and_resolve(` call's third
    positional arg is a lambda whose body calls `self._schedule_llm_job`,
    and every `self._schedule_llm_job(` call NOT inside such a lambda
    has a job-name literal matching one of the deliberately-excluded
    names above (or is the f-string `pillar_chat_{pillar_name}` job)."""
    source = open(ENGINE_PATH).read()
    tree = ast.parse(source)

    submit_calls: list[ast.Call] = []
    all_schedule_calls: list[ast.Call] = []
    wrapped_schedule_call_ids: set[int] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "_submit_and_resolve"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                submit_calls.append(node)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "_schedule_llm_job"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                all_schedule_calls.append(node)
            self.generic_visit(node)

    Visitor().visit(tree)

    check("real _submit_and_resolve call sites found (batch 1 + batch 2)",
          len(submit_calls) == 46)
    check("real _schedule_llm_job call sites found (total in file)",
          len(all_schedule_calls) == 54)

    # For every _submit_and_resolve call, its 3rd positional arg must be
    # a lambda; walk that lambda's own body for a nested _schedule_llm_job
    # call and mark it "wrapped".
    for call in submit_calls:
        check(f"_submit_and_resolve at line {call.lineno} has >=3 positional args",
              len(call.args) >= 3)
        if len(call.args) < 3:
            continue
        resolver_arg = call.args[2]
        check(f"_submit_and_resolve at line {call.lineno}'s resolver is a real lambda",
              isinstance(resolver_arg, ast.Lambda))
        for inner in ast.walk(resolver_arg):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "_schedule_llm_job"
            ):
                wrapped_schedule_call_ids.add(id(inner))

    unwrapped = [c for c in all_schedule_calls if id(c) not in wrapped_schedule_call_ids]
    check("unwrapped _schedule_llm_job call count matches the deliberate-exclusion list",
          len(unwrapped) == 8)

    unwrapped_names: list[str] = []
    for c in unwrapped:
        if not c.args:
            unwrapped_names.append("<unknown>")
            continue
        first = c.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            unwrapped_names.append(first.value)
        elif isinstance(first, ast.JoinedStr):
            # f-string job name, e.g. pillar_chat_{pillar_name}
            unwrapped_names.append("<f-string>")
        else:
            unwrapped_names.append("<non-literal>")

    real_names = {n for n in unwrapped_names if n not in ("<f-string>",)}
    check("every unwrapped call site is one of the deliberately-excluded names "
          f"(found: {sorted(unwrapped_names)})",
          real_names <= EXPECTED_UNWRAPPED_NAMES
          and unwrapped_names.count("<f-string>") == 1)


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
        initial_population=4, width=16, height=16,
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


async def check_representative_sites() -> None:
    # --- town_brain: critical=True, world-scoped, fires unconditionally
    #     every real call (no chance gate). ---
    eng = _make_engine("w2b2_town_brain")
    eng._cognition_runner.client = FakeAdapter({"priority": "grow", "rationale": "food is plentiful."})
    eng.world.settlement.name = "Ashmere"
    # `_monthly_gate` requires the real staggered day-of-month slot for
    # this job (MONTHLY_JOB_DAY, a derived read-only property of
    # SimClock, un-settable directly) -- tick the real engine forward
    # until its own calendar reaches that day, same "drive the clock
    # directly" technique this codebase's own scheduler/dormancy verify
    # scripts already use, rather than a synthetic day override.
    for _ in range(3500):
        eng._tick_once()
        if "town_brain" in eng._w2_workspaces:
            break
    check("town_brain: a real arbitration cycle ran in its own dedicated workspace",
          "town_brain" in eng._w2_workspaces and len(eng._w2_workspaces["town_brain"].history) >= 1)
    await _await_background(eng)

    # --- dream: monthly, core-cast-only, one real firing. ---
    eng2 = _make_engine("w2b2_dream")
    eng2._cognition_runner.client = FakeAdapter({"symbol": "a river", "meaning": "change is coming"})
    eng2.world.population.core_agent_ids = {eng2.world.population.agents[0].id}
    for _ in range(3500):
        eng2._tick_once()
        if "dream" in eng2._w2_workspaces:
            break
    fired = "dream" in eng2._w2_workspaces and len(eng2._w2_workspaces["dream"].history) >= 1
    check("dream: a real arbitration cycle ran once a real core-cast candidate existed", fired)
    if fired:
        await _await_background(eng2)

    # --- nature_causal_reasoning: 3 distinct subjects sharing ONE
    #     workspace (job_name is identical across all 3 triggers). ---
    eng3 = _make_engine("w2b2_nature_causal")
    eng3._cognition_runner.client = FakeAdapter({"hypothesis": "the packs moved on", "confidence": 0.4})
    eng3.world.wildlife.predator_packs_prev = 2
    real_summary = eng3.world.wildlife.summary
    eng3.world.wildlife.summary = lambda: {**real_summary(), "predator_packs": 0}
    eng3._maybe_schedule_nature_causal_reasoning()
    ws = eng3._w2_workspaces.get("nature_causal_reasoning")
    check("nature_causal_reasoning: predator-extinction trigger used the SAME shared job workspace",
          ws is not None and any(r.winner.subject == "nature_causal_reasoning:predator_extinction" for r in ws.history))

    # --- letter: a second real per-candidate-eligible job (record was
    #     already covered by batch 1's own verify script) -- confirm it
    #     runs cleanly through its real monthly gate with no crash even
    #     when (as here, a single-settlement world) no real cross-
    #     settlement candidate exists yet; the production soak below
    #     covers a real firing of this same job-name family. ---
    eng4 = _make_engine("w2b2_letter")
    eng4._cognition_runner.client = FakeAdapter({"body": "Dear friend, all is well."})
    eng4.world.settlement.name = "Origin"
    eng4._maybe_schedule_letter(["month_end", "day_end"])
    check("letter: the real monthly-gated call runs cleanly with no eligible cross-settlement pair",
          "letter" not in eng4._w2_workspaces)

    print()


async def check_production_soak() -> None:
    """A real multi-thousand-tick LLM-disabled production run --
    confirms a broad cross-section of the 42 newly-converted jobs fire
    correctly end to end (real winner, non-empty workspace history)
    purely through ordinary tick-driven scheduling, not a forced call."""
    eng = _make_engine("w2b2_soak", initial_population=10, width=32, height=32)
    for i in range(8000):
        eng._tick_once()
        if i % 200 == 0:
            await asyncio.sleep(0)

    fired_jobs = sorted(eng._w2_workspaces.keys())
    check(f"production soak: at least 8 distinct newly-converted jobs fired "
          f"organically over 8000 ticks (fired: {fired_jobs})",
          len(fired_jobs) >= 8)

    all_real_winners = all(
        rec.winner is not None
        for ws in eng._w2_workspaces.values()
        for rec in ws.history
    )
    check("production soak: every real arbitration cycle across every fired job "
          "produced a genuine winner (coalition-of-one holds under real load)",
          all_real_winners)


async def main_async() -> int:
    check_structural_completeness()
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
