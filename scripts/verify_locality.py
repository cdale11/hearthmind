#!/usr/bin/env python3
"""Standalone verification for B10.1/B10.3 (Locality,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.locality import (
    RegionGrid,
    find_cross_region_write_conflicts,
    plan_region_parallel_batches,
    region_key,
)
from hearthmind.simulation.task_graph import Locality, PriorityClass, Task, TaskRegistry, TriggerKind

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_region_coords_and_ids():
    grid = RegionGrid(width=64, height=64, region_size=8)
    check("region_coords: origin tile is region (0,0)", grid.region_coords(0, 0) == (0, 0))
    check("region_coords: tile at the region boundary rolls into the next region", grid.region_coords(8, 0) == (1, 0))
    check("region_coords: tile just before the boundary stays in the same region", grid.region_coords(7, 7) == (0, 0))
    check("region_id: matches region_coords", grid.region_id(20, 5) == "2,0")


def check_region_dims_and_all_region_ids():
    grid = RegionGrid(width=17, height=9, region_size=8)
    cols, rows = grid.region_dims()
    check("region_dims: partial trailing region still counted (ceil, not floor)", (cols, rows) == (3, 2), str((cols, rows)))
    ids = grid.all_region_ids()
    check("all_region_ids: count matches cols * rows", len(ids) == cols * rows)
    check("all_region_ids: every id is well-formed", all("," in rid for rid in ids))


def check_neighbors_are_4_connected_and_bounded():
    grid = RegionGrid(width=24, height=24, region_size=8)  # 3x3 regions
    center_neighbors = grid.neighbors("1,1")
    check("neighbors: an interior region has all 4 neighbors", len(center_neighbors) == 4, str(center_neighbors))
    check("neighbors: interior neighbor set is exactly the 4-connected set", set(center_neighbors) == {"0,1", "2,1", "1,0", "1,2"})

    corner_neighbors = grid.neighbors("0,0")
    check("neighbors: a corner region only has 2 neighbors (bounded, no wraparound)", len(corner_neighbors) == 2, str(corner_neighbors))
    check("neighbors: corner neighbors never include an out-of-range region", all(
        0 <= int(rid.split(",")[0]) < 3 and 0 <= int(rid.split(",")[1]) < 3 for rid in corner_neighbors
    ))


def _region_task(task_id, region_id, base_write_key):
    return Task(
        id=task_id,
        subsystem="test",
        fn=lambda: None,
        trigger=TriggerKind.PERIODIC,
        writes=frozenset({region_key(base_write_key, region_id)}),
        locality=Locality.REGION,
        priority_class=PriorityClass.STANDARD,
    )


def check_region_key_makes_different_regions_non_conflicting_in_taskregistry():
    # The real B1 integration point: two REGION tasks writing the SAME
    # base key but in DIFFERENT regions must not create a dependency
    # edge in the real TaskRegistry -- proof region_key genuinely
    # composes with B1's existing conflict-detection, not a
    # reimplementation of it.
    t1 = _region_task("soil-2,3", "2,3", "soil")
    t2 = _region_task("soil-5,1", "5,1", "soil")
    registry = TaskRegistry()
    registry.register(t1)
    registry.register(t2)
    order = registry.topological_order()
    check("region_key + TaskRegistry: two same-base-key tasks in different regions register without a cycle", set(order) == {"soil-2,3", "soil-5,1"})

    # Same region, same base key -> a REAL conflict (this is the
    # existing TaskRegistry behavior; region_key doesn't and shouldn't
    # change it).
    t3 = _region_task("soil-2,3-again", "2,3", "soil")
    registry2 = TaskRegistry()
    registry2.register(t1)
    registry2.register(t3)
    edges = registry2._edges()
    check(
        "region_key + TaskRegistry: two tasks in the SAME region with the same base key still conflict normally",
        any(t3.id in deps or t1.id in deps for deps in edges.values()),
    )


def check_plan_region_parallel_batches_no_conflict():
    grid = RegionGrid(width=32, height=32, region_size=8)
    tasks = [
        _region_task("t-a", "0,0", "resources"),
        _region_task("t-b", "1,0", "resources"),
        _region_task("t-c", "0,1", "resources"),
    ]
    region_of = lambda t: next(iter(t.writes)).split("@")[1]  # noqa: E731
    groups, conflicts = plan_region_parallel_batches(tasks, region_of)
    check("plan_region_parallel_batches: groups every task by its own region", set(groups.keys()) == {"0,0", "1,0", "0,1"})
    check("plan_region_parallel_batches: genuinely region-scoped tasks produce zero conflicts", conflicts == [], str(conflicts))
    del grid  # only used to document the scale this scenario represents


def check_find_cross_region_write_conflicts_catches_a_real_bug():
    # A task incorrectly declared REGION but actually writing a
    # GLOBAL (untagged) key -- this must be caught, not silently
    # trusted as parallel-safe.
    global_leak_task = Task(
        id="leaky",
        subsystem="test",
        fn=lambda: None,
        trigger=TriggerKind.PERIODIC,
        writes=frozenset({"town_treasury"}),
        locality=Locality.REGION,
    )
    other_region_task = Task(
        id="other",
        subsystem="test",
        fn=lambda: None,
        trigger=TriggerKind.PERIODIC,
        writes=frozenset({"town_treasury"}),
        locality=Locality.REGION,
    )
    groups = {"region-a": [global_leak_task], "region-b": [other_region_task]}
    conflicts = find_cross_region_write_conflicts(groups)
    check("find_cross_region_write_conflicts: catches two 'different region' groups secretly sharing a global write key", len(conflicts) == 1, str(conflicts))


def check_empty_and_single_region_are_trivially_safe():
    groups_empty, conflicts_empty = plan_region_parallel_batches([], lambda t: "x")
    check("plan_region_parallel_batches: empty task list is trivially conflict-free", groups_empty == {} and conflicts_empty == [])

    single = [_region_task("solo", "3,3", "farms")]
    groups_one, conflicts_one = plan_region_parallel_batches(single, lambda t: next(iter(t.writes)).split("@")[1])
    check("plan_region_parallel_batches: a single region is trivially conflict-free", conflicts_one == [] and len(groups_one) == 1)


def main():
    check_region_coords_and_ids()
    check_region_dims_and_all_region_ids()
    check_neighbors_are_4_connected_and_bounded()
    check_region_key_makes_different_regions_non_conflicting_in_taskregistry()
    check_plan_region_parallel_batches_no_conflict()
    check_find_cross_region_write_conflicts_catches_a_real_bug()
    check_empty_and_single_region_are_trivially_safe()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
