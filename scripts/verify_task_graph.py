#!/usr/bin/env python3
"""Tier 5 B1 verification (task declaration & the work graph).

Standalone verification script, not a unittest — same convention as
every other verify_*.py in this directory. Exercises `hearthmind.
simulation.task_graph` against a synthetic task set (this module is
not wired into the live tick loop yet, per B1.4's own "never
big-bang" — there is no real subsystem migration to soak-test here).

Checks:
  1. Disjoint reads/writes never impose an ordering constraint.
  2. A real read/write dependency imposes the correct direction.
  3. A genuine cycle is detected and rejected at build time (B1.2).
  4. Topological order is deterministic regardless of registration
     order (B1.3) — registering the same tasks in reverse order
     produces the identical output.
  5. Two `Task.legacy(...)` declarations always end up in a real,
     stable total order relative to each other (B1.4's shim),
     independent of registration order.
"""
from __future__ import annotations

import sys

from hearthmind.simulation.task_graph import CycleError, Task, TaskRegistry, TriggerKind


def _noop() -> None:
    pass


def check_disjoint_no_constraint() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=_noop, trigger=TriggerKind.PERIODIC, writes=frozenset({"foo"})))
    reg.register(Task(id="b", subsystem="y", fn=_noop, trigger=TriggerKind.PERIODIC, writes=frozenset({"bar"})))
    order = reg.topological_order()
    assert set(order) == {"a", "b"}, order
    assert order == sorted(order), "disjoint tasks should fall back to id order"


def check_real_dependency_direction() -> None:
    reg = TaskRegistry()
    # "z" registered first but depends on "a" writing what it reads —
    # the real dependency must win over registration order.
    reg.register(Task(id="z", subsystem="y", fn=_noop, trigger=TriggerKind.PERIODIC, reads=frozenset({"foo"})))
    reg.register(Task(id="a", subsystem="x", fn=_noop, trigger=TriggerKind.PERIODIC, writes=frozenset({"foo"})))
    order = reg.topological_order()
    assert order.index("a") < order.index("z"), order


def check_cycle_rejected() -> None:
    reg = TaskRegistry()
    reg.register(Task(id="a", subsystem="x", fn=_noop, trigger=TriggerKind.PERIODIC,
                       reads=frozenset({"y"}), writes=frozenset({"x"})))
    reg.register(Task(id="b", subsystem="y", fn=_noop, trigger=TriggerKind.PERIODIC,
                       reads=frozenset({"x"}), writes=frozenset({"y"})))
    try:
        reg.topological_order()
    except CycleError as exc:
        assert set(exc.cycle_ids) == {"a", "b"}, exc.cycle_ids
    else:
        raise AssertionError("expected CycleError for a<->b cycle")


def check_deterministic_regardless_of_registration_order() -> None:
    tasks = [
        Task(id="c", subsystem="x", fn=_noop, trigger=TriggerKind.PERIODIC, writes=frozenset({"m"})),
        Task(id="a", subsystem="x", fn=_noop, trigger=TriggerKind.PERIODIC, reads=frozenset({"m"})),
        Task(id="b", subsystem="x", fn=_noop, trigger=TriggerKind.PERIODIC, writes=frozenset({"n"})),
    ]
    reg1 = TaskRegistry()
    for t in tasks:
        reg1.register(t)
    order1 = reg1.topological_order()

    reg2 = TaskRegistry()
    for t in reversed(tasks):
        reg2.register(t)
    order2 = reg2.topological_order()

    assert order1 == order2, (order1, order2)


def check_legacy_shim_total_order() -> None:
    reg = TaskRegistry()
    reg.register(Task.legacy(id="z_legacy", subsystem="engine", fn=_noop))
    reg.register(Task.legacy(id="a_legacy", subsystem="engine", fn=_noop))
    order = reg.topological_order()
    assert order == ["a_legacy", "z_legacy"], order

    # Reversed registration order must still produce the same result.
    reg2 = TaskRegistry()
    reg2.register(Task.legacy(id="a_legacy", subsystem="engine", fn=_noop))
    reg2.register(Task.legacy(id="z_legacy", subsystem="engine", fn=_noop))
    assert reg2.topological_order() == order


def main() -> int:
    checks = [
        check_disjoint_no_constraint,
        check_real_dependency_direction,
        check_cycle_rejected,
        check_deterministic_regardless_of_registration_order,
        check_legacy_shim_total_order,
    ]
    for check in checks:
        check()
        print(f"OK: {check.__name__}")
    print(f"Task graph verification OK — {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
