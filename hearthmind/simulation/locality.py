"""B10 -- Locality (docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B,
Hard Rule 11). Standalone infrastructure, same "never big-bang"
discipline as every other Tier 5 Runtime module -- not wired into
`simulation/engine.py` or the live tick loop yet.

B10.1 `RegionGrid`: a plain grid spatial partition (region or quadtree
     per the item's own text -- a uniform grid is the simpler, more
     directly testable of the two, same choice B6.2 made for bang-bang
     over PID). `region_key` is the real integration point with B1's
     `TaskRegistry`: tagging a `Task`'s declared `reads`/`writes` with
     its region (`f"{base_key}@{region_id}"`) means the dependency
     graph B1 ALREADY builds from read/write overlap naturally treats
     two different regions as non-conflicting -- no second conflict-
     detection mechanism needed, this reuses the one B1 already has.
`Locality.REGION` already exists on `Task` (B1.1) -- this module gives
     it real semantics rather than adding a new field.
B10.3 `plan_region_parallel_batches`: groups a set of region-tagged
     tasks by region and VERIFIES (not just assumes) their declared
     write-sets are genuinely disjoint across regions -- the real
     safety check B10.3's own "where write-sets are disjoint by
     region" condition asks for, catching a region-tag that doesn't
     match what a task actually declared it writes.

B10.2 (a live audit converting real `world/`/`agents/`/`settlement/`/
`economy/` full-population/full-map loops to indexed/local queries) is
explicitly NOT attempted here -- same "needs individual live
judgment, not a mechanism" class as B3.3/B9.3's own audit deferrals.
`scripts/scan_global_scans.py` ships the DISCOVERY tool such an audit
would use (an informational scan flagging candidate global-loop
patterns), not the audit/conversion itself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

_NEIGHBOR_OFFSETS = ((-1, 0), (1, 0), (0, -1), (0, 1))


@dataclass(frozen=True)
class RegionGrid:
    """B10.1. Partitions a `width` x `height` map into
    `region_size` x `region_size` cells. A region id is the plain
    string `"{rx},{ry}"` -- deliberately a string (not a tuple) so it
    can be embedded directly into a `Task.reads`/`writes` frozenset
    entry via `region_key`."""

    width: int
    height: int
    region_size: int = 8

    def region_coords(self, x: int, y: int) -> tuple:
        return x // self.region_size, y // self.region_size

    def region_id(self, x: int, y: int) -> str:
        rx, ry = self.region_coords(x, y)
        return f"{rx},{ry}"

    def region_dims(self) -> tuple:
        cols = max(1, math.ceil(self.width / self.region_size))
        rows = max(1, math.ceil(self.height / self.region_size))
        return cols, rows

    def all_region_ids(self) -> list:
        cols, rows = self.region_dims()
        return [f"{rx},{ry}" for ry in range(rows) for rx in range(cols)]

    def neighbors(self, region_id: str) -> list:
        rx, ry = (int(v) for v in region_id.split(","))
        cols, rows = self.region_dims()
        out = []
        for dx, dy in _NEIGHBOR_OFFSETS:
            nx, ny = rx + dx, ry + dy
            if 0 <= nx < cols and 0 <= ny < rows:
                out.append(f"{nx},{ny}")
        return out


def region_key(base_key: str, region_id: str) -> str:
    """Tags a read/write key with the region it's scoped to -- a
    `Task` declaring `writes={region_key("soil", "2,3")}` is
    automatically recognized as non-conflicting with a task writing
    `region_key("soil", "5,1")` by B1's own existing `TaskRegistry`
    dependency-graph logic, with zero changes to that logic."""
    return f"{base_key}@{region_id}"


def group_tasks_by_region(tasks: list, region_of) -> dict:
    """`region_of(task) -> region_id`. Groups tasks by their declared
    region -- the partition B10.3's parallel execution plan works
    over."""
    groups: dict = {}
    for task in tasks:
        rid = region_of(task)
        groups.setdefault(rid, []).append(task)
    return groups


def find_cross_region_write_conflicts(groups: dict) -> list:
    """B10.3's real safety check: two DIFFERENT region groups must
    never declare an overlapping write key. If they do, they are not
    actually disjoint by region despite being grouped as if they were
    -- a real bug (a task writing an untagged/global key while
    declared `Locality.REGION`), not something to trust silently."""
    conflicts = []
    region_ids = list(groups.keys())
    write_sets = {
        rid: frozenset().union(*(t.writes for t in tasks)) if tasks else frozenset()
        for rid, tasks in groups.items()
    }
    for i in range(len(region_ids)):
        for j in range(i + 1, len(region_ids)):
            a, b = region_ids[i], region_ids[j]
            overlap = write_sets[a] & write_sets[b]
            if overlap:
                conflicts.append(f"region {a!r} and region {b!r} share write keys: {sorted(overlap)}")
    return conflicts


def plan_region_parallel_batches(tasks: list, region_of):
    """The one call B10.3 describes: partition `tasks` by region and
    verify the partition is genuinely safe to run in parallel (across
    regions -- tasks within the same region still serialize against
    each other, only different regions are the parallelism source).
    Returns `(groups, conflicts)`; a real caller should refuse to
    treat any two conflicting groups as parallel-safe."""
    groups = group_tasks_by_region(tasks, region_of)
    conflicts = find_cross_region_write_conflicts(groups)
    return groups, conflicts
