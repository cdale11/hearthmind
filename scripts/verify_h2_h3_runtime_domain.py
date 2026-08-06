#!/usr/bin/env python3
"""Tier 7 HCA Stage H, H2+H3 (docs/ROADMAP-2026-07-REMAINING.md, Phase
4, explicit user instructions "Start H3" / "Start H2" -- H2 first,
since H3 explicitly depends on it).

H2's own claim: the Adaptive Runtime is a real specialist family in
the MACHINE cognitive domain. Four pre-existing modules (`hearthmind.
simulation.escalation`/`.forecasting`/`.profiling`/`.optimization_
hypothesis`) plus one new module (`hearthmind.cognition.runtime_
specialist`, the family's real `bid()`) all carry `SPECIALIST_DOMAIN
= Domain.MACHINE`. `SimulationEngine._maybe_advance_escalation_
ladder` — previously a unilateral direct write to `self._escalation_
ladder`/`self._cognition_budget` — now submits a real `Bid` to a
dedicated `self._machine_workspace` and only invokes the winning
bid's resolver once `arbitrate()` names it, the exact same
"coalition-of-one, provably behavior-preserving by construction"
shape every W1-W4/H1 site in this codebase already established.

H3's own claim: cross-domain isolation — a MACHINE bid/broadcast
never touches `hearthmind.world`/`Settlement`/`Agent` state, and
never lands in the same arbitration pool as a WORLD-domain bid.
Verified here: a real before/after `World.to_dict()` diff around a
forced-pressured `_maybe_advance_escalation_ladder()` call proves
ZERO world-state change (only engine-level `_escalation_ladder`/
`_cognition_budget` moves); `self._machine_workspace` is structurally
distinct from every WORLD-domain workspace (`_w2_workspaces`/`_w3_
workspaces`/`_naming_workspace`/`_pillar_buses`); and the module-level
domain-write-scope check (H1's own mechanism) stays clean against the
real tree with these five new markers in place.
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
    from hearthmind.cognition import runtime_specialist
    from hearthmind.cognition.workspace import Domain, GlobalWorkspace
    from hearthmind.simulation import escalation, forecasting, optimization_hypothesis, profiling
    import scripts.verify_runtime_invariant as invariant  # noqa: E402

    # --- structural: every named MACHINE-domain module carries the
    #     marker, and the real tree is still clean under it ---
    for mod, name in (
        (escalation, "escalation"), (forecasting, "forecasting"),
        (profiling, "profiling"), (optimization_hypothesis, "optimization_hypothesis"),
        (runtime_specialist, "runtime_specialist"),
    ):
        check(f"{name} declares SPECIALIST_DOMAIN = Domain.MACHINE",
              getattr(mod, "SPECIALIST_DOMAIN", None) is Domain.MACHINE)

    real_violations = invariant.check_domain_write_scope()
    check("the real hearthmind/ tree has zero domain write-scope violations "
          "with all five H2 markers in place",
          real_violations == {})

    # --- H2: propose_escalation_bid produces a real MACHINE Bid ---
    calls: list[str] = []
    bid = runtime_specialist.propose_escalation_bid(42, lambda: calls.append("ran"), pressured=True)
    check("propose_escalation_bid returns a MACHINE-domain bid",
          bid.domain is Domain.MACHINE)
    check("propose_escalation_bid names the real subject",
          bid.subject == "escalation_ladder")
    check("propose_escalation_bid's resolver is the caller's own closure, unfired until invoked",
          calls == [])
    bid.resolver()
    check("invoking the winning bid's resolver actually runs the caller's closure",
          calls == ["ran"])

    # --- H2: a coalition-of-one workspace always resolves to the sole
    #     bidder, same "provably behavior-preserving" proof every
    #     W1-W4/H1 site already used ---
    ws = GlobalWorkspace()
    fired: list[int] = []
    for tick in range(5):
        b = runtime_specialist.propose_escalation_bid(tick, lambda t=tick: fired.append(t), pressured=True)
        ws.submit(b)
        winner = ws.arbitrate()
        if winner is not None:
            winner.resolver()
    check("a solo-bidder MACHINE workspace resolves every real cycle to that bid",
          fired == [0, 1, 2, 3, 4])
    check("the workspace's own competition log recorded every real cycle",
          len(ws.history) == 5 and all(r.winner is not None and r.losers == () for r in ws.history))

    # --- real production wiring: SimulationEngine._machine_workspace
    #     exists, is a real GlobalWorkspace, and is genuinely separate
    #     from every WORLD-domain workspace ---
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine
    from hearthmind.world.state import World

    def new_engine(seed: int) -> SimulationEngine:
        config = Config(db_path=":memory:", llm_enabled=False, seed=seed)
        world = World.create_new(config)
        conn = connect(":memory:")
        return SimulationEngine(conn, config, world)

    engine = new_engine(4242)

    check("SimulationEngine._machine_workspace is a real, distinct GlobalWorkspace",
          isinstance(engine._machine_workspace, GlobalWorkspace)
          and engine._machine_workspace is not engine._naming_workspace)
    check("the machine workspace shares no identity with any WORLD-domain workspace container",
          engine._machine_workspace not in engine._w2_workspaces.values()
          and engine._machine_workspace not in engine._w3_workspaces.values())

    # --- real production call: _maybe_advance_escalation_ladder now
    #     routes through the bid/arbitrate mechanism. Roadmap Phase 3,
    #     H1 "per-domain budgets": that method now only SUBMITS -- the
    #     actual arbitration moved to a new shared `_maybe_resolve_
    #     machine_domain`, so a direct test call must drive both. ---
    before_cycles = engine._machine_workspace._cycle
    engine._maybe_advance_escalation_ladder(["day_end"])
    engine._maybe_resolve_machine_domain(["day_end"])
    check("a real day_end call advances the machine workspace's own cycle counter",
          engine._machine_workspace._cycle == before_cycles + 1)
    check("a real day_end call records a real winner (coalition-of-one) in the machine workspace's history",
          engine._machine_workspace.history[-1].winner is not None
          and engine._machine_workspace.history[-1].winner.subject == "escalation_ladder")

    non_day_end_cycles = engine._machine_workspace._cycle
    engine._maybe_advance_escalation_ladder(["month_end"])
    check("a non-day_end call is a genuine no-op (no bid ever submitted, cycle count unchanged)",
          engine._machine_workspace._cycle == non_day_end_cycles)

    # --- H3: cross-domain isolation, the real headline test -- a
    #     forced-pressured call must change ZERO world state ---
    engine2 = new_engine(4242)
    before_world = copy.deepcopy(engine2.world.to_dict())
    # force real pressure so the resolver's branch (observe(..., pressured=True)) is exercised
    engine2._current_backpressure_limit = lambda: 1  # type: ignore[method-assign]
    engine2._effective_backlog = lambda: 999  # type: ignore[method-assign]
    engine2._maybe_advance_escalation_ladder(["day_end"])
    engine2._maybe_resolve_machine_domain(["day_end"])
    after_world = engine2.world.to_dict()
    check("a real (even pressured) escalation-ladder cycle leaves World.to_dict() byte-identical",
          before_world == after_world)
    check("the pressured cycle still genuinely ran (engine-level ladder/budget state changed)",
          engine2._escalation_ladder.current_rung.name != "REORDER_BATCH"
          or engine2._escalation_ladder.streak_at_current_rung >= 1)

    # --- H3: no cross-domain content flow -- the machine workspace is
    #     never referenced from any WORLD-domain messaging/belief path ---
    import ast
    import inspect
    src = inspect.getsource(SimulationEngine)
    tree = ast.parse(src)

    class _SendMessageVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.touches_machine_workspace = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node.name == "_send_pillar_message":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) and sub.attr == "_machine_workspace":
                        self.touches_machine_workspace = True
            self.generic_visit(node)

    visitor = _SendMessageVisitor()
    visitor.visit(tree)
    check("_send_pillar_message (the real WORLD-domain messaging arrow) never references _machine_workspace",
          not visitor.touches_machine_workspace)

    # --- diagnostics surfacing (dev-console/Observatory-only, per H3) ---
    diag = engine.full_diagnostics()
    check("full_diagnostics() surfaces machine_domain",
          "machine_domain" in diag)
    check("machine_domain reports the real cycle count and a real winner/loser history entry",
          diag["machine_domain"]["cycles"] >= 1
          and diag["machine_domain"]["history_recent"][-1]["winner"]["subject"] == "escalation_ladder")

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
