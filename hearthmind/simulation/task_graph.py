"""Tier 5 B1 — Task declaration & the work graph.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B: "Gameplay systems
declare *what* work exists. The runtime decides *when*, *where*, and
*how* it executes" (B0, CLAUDE.md's "Adaptive Runtime prime
invariant"). `Task` is what a subsystem declares instead of scheduling
itself; `TaskRegistry` turns a set of declarations into a dependency
graph and a deterministic execution order.

**Not wired into the live tick loop yet — this module is pure
infrastructure, imported by nothing in `simulation/engine.py`.** Per
B0.3/B1.4's own explicit "never big-bang" instruction, the ~200 real
schedule points inside `engine.py` stay exactly as they are today;
migrating them onto this graph, one subsystem at a time, each verified
against `scripts/verify_replay_hash.py`, is real future Part B work
(B2's budgeted scheduler is what would actually execute a
`TaskRegistry`'s tasks — this module only builds and orders the graph).

B1.4's incremental-adoption shim is `Task.legacy(...)`: a declaration
an un-migrated subsystem can use *as-is*, with no real reads/writes
analysis done yet — it conflicts with everything (`writes={LEGACY_
WILDCARD}`), so the registry can never assume it's safe to reorder or
parallelize against any other task. This lets legacy and migrated
tasks coexist in one graph without legacy code needing to be
understood first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

# Sentinel write key every `Task.legacy(...)` declaration carries —
# conflicts with every other task's reads/writes (including another
# legacy task's), so legacy tasks always stay in a real, stable total
# order relative to one another, matching "keeps running exactly as
# today" rather than being silently reordered.
LEGACY_WILDCARD = "*"


class TriggerKind(Enum):
    PERIODIC = "periodic"
    ON_EVENT = "on_event"
    ON_DIRTY = "on_dirty"
    PREDICTED = "predicted"


class Locality(Enum):
    REGION = "region"
    GLOBAL = "global"
    ENTITY = "entity"


class Determinism(Enum):
    STRICT = "strict"
    REORDERABLE = "reorderable"


class PriorityClass(Enum):
    """Placeholder vocabulary — becomes load-bearing once B2's budgeted
    scheduler exists to actually read it. B1 only needs Task to be able
    to *carry* a priority class, not act on one yet."""

    CRITICAL = "critical"
    STANDARD = "standard"
    DEFERRABLE = "deferrable"
    BACKGROUND = "background"
    IDLE_ONLY = "idle_only"


@dataclass(frozen=True)
class Task:
    """B1.1's descriptor — what a subsystem declares instead of calling
    itself. `reads`/`writes` are what let the runtime reorder and
    parallelize *safely*: two tasks with disjoint write-sets (and no
    read/write overlap) may run concurrently; overlapping ones may not.
    """

    id: str
    subsystem: str
    fn: Callable[..., object]
    trigger: TriggerKind
    reads: frozenset[str] = field(default_factory=frozenset)
    writes: frozenset[str] = field(default_factory=frozenset)
    timescale: str = "tick"
    priority_class: PriorityClass = PriorityClass.STANDARD
    cost_hint: float = 1.0
    locality: Locality = Locality.GLOBAL
    determinism: Determinism = Determinism.STRICT

    @classmethod
    def legacy(cls, id: str, subsystem: str, fn: Callable[..., object]) -> "Task":
        """B1.4's incremental-adoption shim — declare an un-migrated
        call site as-is, with no reads/writes analysis done. Always
        conflicts with every other task (including other legacy ones),
        so it can never be silently reordered or parallelized against
        anything until someone deliberately migrates it with real
        reads/writes."""
        return cls(
            id=id,
            subsystem=subsystem,
            fn=fn,
            trigger=TriggerKind.PERIODIC,
            reads=frozenset(),
            writes=frozenset({LEGACY_WILDCARD}),
            locality=Locality.GLOBAL,
            determinism=Determinism.STRICT,
        )

    def conflicts_with(self, other: "Task") -> bool:
        """True if `self` must not be assumed safe to run concurrently
        with or reordered arbitrarily against `other` — a write/write or
        read/write overlap on any key, or either side carrying the
        legacy wildcard."""
        if LEGACY_WILDCARD in self.writes or LEGACY_WILDCARD in other.writes:
            return True
        if self.writes & other.writes:
            return True
        if self.writes & other.reads:
            return True
        if other.writes & self.reads:
            return True
        return False


class CycleError(ValueError):
    """B1.2: raised at graph-build time ("rejected at boot") when a set
    of declared tasks contains a dependency cycle."""

    def __init__(self, cycle_ids: list[str]):
        self.cycle_ids = cycle_ids
        super().__init__(f"task dependency cycle: {' -> '.join(cycle_ids)}")


class TaskRegistry:
    """B1.2's registry + dependency graph, built at startup from
    declarations. B1.3's deterministic ordering rule lives on
    `topological_order()`: a stable topological sort with a
    deterministic tiebreak (task id) — independent of registration
    order, wall-clock, or thread completion order, which is what makes
    the eventual B2 scheduler's reordering safe."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def register(self, task: Task) -> None:
        if task.id in self._tasks:
            raise ValueError(f"duplicate task id: {task.id!r}")
        self._tasks[task.id] = task

    def __len__(self) -> int:
        return len(self._tasks)

    def _edges(self) -> dict[str, set[str]]:
        """task_id -> set of task_ids that must run before it (an edge
        A->B exists whenever A conflicts with B and A sorts before B by
        id — the direction itself is arbitrary for a pure conflict, but
        must be assigned consistently so the graph is acyclic when the
        real dependency is symmetric write/write or write/read overlap
        with no other ordering signal)."""
        ids = sorted(self._tasks)
        deps: dict[str, set[str]] = {tid: set() for tid in ids}
        for i, a_id in enumerate(ids):
            a = self._tasks[a_id]
            for b_id in ids[i + 1:]:
                b = self._tasks[b_id]
                if a.writes & b.reads:
                    deps[b_id].add(a_id)
                if b.writes & a.reads:
                    deps[a_id].add(b_id)
                if a.conflicts_with(b) and not (a.writes & b.reads) and not (b.writes & a.reads):
                    # Symmetric conflict (write/write or the legacy
                    # wildcard) with no read-driven direction — break
                    # the tie deterministically by id so every conflict
                    # still yields a real, stable ordering constraint.
                    deps[b_id].add(a_id)
        return deps

    def topological_order(self) -> list[str]:
        """Kahn's algorithm, always picking the lexicographically
        smallest ready task id — the deterministic tiebreak B1.3 asks
        for. Raises CycleError if the declared tasks can't be fully
        ordered."""
        deps = self._edges()
        remaining = {tid: set(d) for tid, d in deps.items()}
        ordered: list[str] = []
        ready = sorted(tid for tid, d in remaining.items() if not d)

        while ready:
            ready.sort()
            current = ready.pop(0)
            ordered.append(current)
            del remaining[current]
            for tid, d in remaining.items():
                if current in d:
                    d.discard(current)
                    if not d and tid not in ready:
                        ready.append(tid)

        if remaining:
            raise CycleError(sorted(remaining))
        return ordered
