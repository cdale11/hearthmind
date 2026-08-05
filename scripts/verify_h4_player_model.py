#!/usr/bin/env python3
"""Tier 7 HCA Stage H, H4 (docs/ROADMAP-2026-07-REMAINING.md, Phase 4,
explicit user instruction "Continue H4" -- the last item Stage H
names, closing Stage H in full).

H4's own claim: the Player Model is a real OBSERVER-domain specialist
-- read-only, distinct from the Town Consciousness's own interventions
(`World.consciousness_player_model`, untouched by this item), grounded
in the one real signal already tracked about the observer (`World.
observer_attention`). Verified here, same three-part shape H3
established for MACHINE: (1) `hearthmind.cognition.player_model`
declares `SPECIALIST_DOMAIN = Domain.OBSERVER` and the real tree stays
clean under `check_domain_write_scope()`; (2) `predict()`/`error()`/
`bid()` behave correctly as pure functions and a real coalition-of-one
`GlobalWorkspace` cycle; (3) the real production call site
(`SimulationEngine._record_observer_attention`) genuinely predicts
BEFORE observing, scores correctly, and — the real headline test —
a before/after `World.to_dict()` diff around a real forced call proves
ZERO world-state change; `self._observer_workspace` is structurally
distinct from `self._machine_workspace` and every WORLD-domain
workspace; and `_send_pillar_message` never references it either.
"""
from __future__ import annotations

import copy
import sys

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    from hearthmind.cognition import player_model
    from hearthmind.cognition.player_model import (
        PlayerAttentionModel, predict_next_focus, prediction_error, propose_player_model_bid,
    )
    from hearthmind.cognition.workspace import Domain, GlobalWorkspace
    import scripts.verify_runtime_invariant as invariant  # noqa: E402

    # --- structural: the module declares itself, and the real tree
    #     stays clean under the write-scope check with it in place ---
    check("player_model declares SPECIALIST_DOMAIN = Domain.OBSERVER",
          player_model.SPECIALIST_DOMAIN is Domain.OBSERVER)
    real_violations = invariant.check_domain_write_scope()
    check("the real hearthmind/ tree has zero domain write-scope violations "
          "with the OBSERVER marker in place",
          real_violations == {})

    # --- predict()/error() as pure functions ---
    check("predict_next_focus returns None with no observations at all",
          predict_next_focus({}) is None)
    check("predict_next_focus picks the highest-count agent",
          predict_next_focus({1: 3, 2: 7, 3: 1}) == 2)
    check("predict_next_focus breaks a genuine tie toward the smallest id (no RNG)",
          predict_next_focus({5: 4, 2: 4, 9: 4}) == 2)
    check("prediction_error is 0.0 on a real hit",
          prediction_error(7, 7) == 0.0)
    check("prediction_error is 1.0 on a real miss",
          prediction_error(7, 8) == 1.0)
    check("prediction_error is 1.0 when there was no prediction to compare (None)",
          prediction_error(None, 8) == 1.0)

    # --- PlayerAttentionModel's own bounded, measured hit rate ---
    model = PlayerAttentionModel()
    check("a fresh PlayerAttentionModel reports no hit rate yet (None, not a guessed 0)",
          model.hit_rate() is None)
    model.record(1, 1)
    model.record(1, 1)
    model.record(1, 2)
    check("hit_rate reflects the real measured ratio (2 hits of 3)",
          abs(model.hit_rate() - (2.0 / 3.0)) < 1e-9)

    # --- propose_player_model_bid + a coalition-of-one workspace,
    #     same "provably behavior-preserving" proof every W1-W4/H2
    #     site already used ---
    ws = GlobalWorkspace()
    fired: list[tuple] = []
    for predicted, actual in [(None, 1), (1, 1), (1, 2), (2, 2)]:
        err = prediction_error(predicted, actual)
        bid = propose_player_model_bid(predicted, err, lambda p=predicted, a=actual: fired.append((p, a)))
        check(f"propose_player_model_bid({predicted!r}, ...) is a real OBSERVER-domain bid",
              bid.domain is Domain.OBSERVER and bid.subject == "player_model")
        ws.submit(bid)
        winner = ws.arbitrate()
        if winner is not None:
            winner.resolver()
    check("a solo-bidder OBSERVER workspace resolves every real cycle to that bid",
          fired == [(None, 1), (1, 1), (1, 2), (2, 2)])
    check("the workspace's own competition log recorded every real cycle",
          len(ws.history) == 4 and all(r.winner is not None and r.losers == () for r in ws.history))

    # --- real production wiring ---
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine
    from hearthmind.world.state import World

    def new_engine(seed: int) -> SimulationEngine:
        config = Config(db_path=":memory:", llm_enabled=False, seed=seed)
        world = World.create_new(config)
        conn = connect(":memory:")
        return SimulationEngine(conn, config, world)

    engine = new_engine(9191)
    check("SimulationEngine._observer_workspace is a real, distinct GlobalWorkspace",
          isinstance(engine._observer_workspace, GlobalWorkspace)
          and engine._observer_workspace is not engine._machine_workspace
          and engine._observer_workspace is not engine._naming_workspace)
    check("the observer workspace shares no identity with any WORLD-domain workspace container",
          engine._observer_workspace not in engine._w2_workspaces.values()
          and engine._observer_workspace not in engine._w3_workspaces.values())

    # a first real observation: no prior counts, so predicted is None -> a real miss
    before_cycles = engine._observer_workspace._cycle
    living_ids = [a.id for a in engine.world.population.agents]
    check("the fresh engine has real living agents to inspect", len(living_ids) >= 2)
    first_id, second_id = living_ids[0], living_ids[1]

    engine._record_observer_attention(first_id)
    check("a real first observation advances the observer workspace's cycle counter",
          engine._observer_workspace._cycle == before_cycles + 1)
    check("a real first observation is recorded as a genuine miss (no prior prediction)",
          engine._player_model_history[-1]["predicted_agent_id"] is None
          and engine._player_model_history[-1]["hit"] is False)
    check("World.observer_attention itself was still updated (the ordinary §4 bookkeeping)",
          engine.world.observer_attention.get("agent_view_counts", {}).get(first_id) == 1)

    # a second observation of the SAME agent: now predict() should hit
    engine._record_observer_attention(first_id)
    check("a real repeat observation is correctly predicted and scored as a hit",
          engine._player_model_history[-1]["predicted_agent_id"] == first_id
          and engine._player_model_history[-1]["hit"] is True)

    # a third observation of a DIFFERENT agent: predict() still favors
    # the more-viewed first_id, so this should score as a miss
    engine._record_observer_attention(second_id)
    check("a real observation of a less-viewed agent is correctly scored as a miss",
          engine._player_model_history[-1]["predicted_agent_id"] == first_id
          and engine._player_model_history[-1]["actual_agent_id"] == second_id
          and engine._player_model_history[-1]["hit"] is False)

    # --- the H4 headline test: cross-domain isolation, real forced call ---
    engine2 = new_engine(9191)
    living_ids2 = [a.id for a in engine2.world.population.agents]
    before_world = copy.deepcopy(engine2.world.to_dict())
    engine2._record_observer_attention(living_ids2[0])
    after_world = engine2.world.to_dict()
    # `observer_attention` is real, intended §4 bookkeeping (not the
    # invariant under test) -- strip it from both sides before
    # comparing, then confirm every OTHER field is byte-identical.
    before_world.pop("observer_attention", None)
    after_world.pop("observer_attention", None)
    check("a real observer-model cycle leaves every other World field byte-identical "
          "(only the pre-existing §4 observer_attention bookkeeping changes)",
          before_world == after_world)

    import ast
    import inspect
    from hearthmind.simulation.engine import SimulationEngine as _SE
    src = inspect.getsource(_SE)
    tree = ast.parse(src)

    class _SendMessageVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.touches_observer_workspace = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node.name == "_send_pillar_message":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) and sub.attr == "_observer_workspace":
                        self.touches_observer_workspace = True
            self.generic_visit(node)

    visitor = _SendMessageVisitor()
    visitor.visit(tree)
    check("_send_pillar_message (the real WORLD-domain messaging arrow) never references _observer_workspace",
          not visitor.touches_observer_workspace)

    # --- diagnostics surfacing ---
    diag = engine.full_diagnostics()
    check("full_diagnostics() surfaces player_model_domain",
          "player_model_domain" in diag)
    check("player_model_domain reports a real measured hit_rate and history",
          diag["player_model_domain"]["hit_rate"] is not None
          and len(diag["player_model_domain"]["history_recent"]) == 3)

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
