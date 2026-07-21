"""Phase 0 of the "self-evolving world" architecture
(docs/VISION-2026-07-21-SELFEVOLVING.md): one typed pairwise ledger
entry per (agent, other_id), consolidating storage that used to live
in five separate scattered dicts on `Agent` (`relationships`, `trust`,
`debts`, `relationship_flags`, `grievances`).

The external shape of those five attributes is UNCHANGED — each is
still a plain dict-like object, independently sparse (only pairs where
THAT specific field differs from its neutral default appear, exactly
like the standalone dicts they replace), via the `_FieldView` proxy
below. This means the ~90 existing call sites across the codebase that
read/write `agent.relationships[...]`/`.trust.get(...)`/`.debts.pop(
...)`/etc. did not need to change — same "compatibility-shim property,
zero call-site changes" discipline the native `AgentStore` migration
(v0.65.0) already established for a different set of scalars ("zero of
the ~700 scalar touch sites needed editing").

Two genuinely new capabilities land on the same `LedgerEdge` rather
than as a sixth/seventh scattered dict: `promises` (Phase 2, dialogue-
created commitments) and `history_tags` (cheap "have these two ever
X'd" checks). This is the actual point of Phase 0 — one place every
future interpersonal system reads/writes through, not one more axis
bolted on alongside the old scattered ones.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field

MAX_PROMISES_PER_EDGE = 4
"""Small and FIFO — a handful of live commitments between two people,
not a growing ledger of every promise ever made. Resolved/broken
promises are dropped, not archived here (Agent.memories/grievances are
where a broken promise's narrative residue belongs)."""


@dataclass
class LedgerEdge:
    """One agent's own view of one other agent — directional, not a
    shared symmetric edge (agent A's `LedgerEdge` for B is independent
    of agent B's `LedgerEdge` for A), preserving the directionality
    the old per-agent dicts already had (each agent's `relationships`/
    `trust` was always its own dict, never a shared bidirectional
    value) — see docs/VISION-2026-07-21-SELFEVOLVING.md, Phase 0's
    "already true structurally" note."""

    # Deliberately `float | None`, not `float = 0.0` — existing call
    # sites throughout the codebase do `agent.debts[id] = 0.0` (a
    # settlement, e.g. a reversed trade fully cancelling out) and then
    # immediately re-read `agent.debts[id]` on the next line before an
    # explicit `.pop(id, None)`. A "the neutral value means absent"
    # scheme would prune the edge on that write and turn the very next
    # read into a spurious KeyError — real bug, caught by the native
    # soak. `None` is the only "not present" sentinel; an explicit 0.0
    # is a legitimate, readable, still-present value until something
    # actually deletes the key, exactly like the plain dicts this
    # replaces.
    fondness: float | None = None
    trust: float | None = None
    debt: float | None = None
    flag: str = ""  # "" = none; "feud" is the only value in use today (v1.3.17)
    grievances: list[str] = field(default_factory=list)
    promises: list[dict] = field(default_factory=list)
    history_tags: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return (
            self.fondness is None and self.trust is None and self.debt is None
            and not self.flag and not self.grievances and not self.promises
            and not self.history_tags
        )


class _FieldView(MutableMapping):
    """Dict-like proxy over ONE field of every edge in a `Ledger` —
    preserves the exact old per-field sparsity (a key appears only
    when THIS field differs from its default), so every existing
    `agent.trust.get(x, 0.0)` / `for id, v in agent.relationships.
    items()` / `del agent.debts[id]` / `id in agent.grievances` call
    site keeps working unmodified against the new shared storage.

    Deliberately NOT used for `grievances` (a mutable list field) —
    `dict.setdefault(key, [])`'s return value is meant to be a live
    reference callers mutate in place, which would race against this
    view's own on-write pruning (setting to the empty-list default
    would immediately drop the edge under the caller's feet). See
    `Ledger.add_grievance`, the dedicated method that avoids this."""

    __slots__ = ("_ledger", "_attr", "_default")

    def __init__(self, ledger: "Ledger", attr: str, default) -> None:
        self._ledger = ledger
        self._attr = attr
        self._default = default

    def __getitem__(self, key):
        edge = self._ledger.edges.get(key)
        if edge is None:
            raise KeyError(key)
        value = getattr(edge, self._attr)
        if value is None or value == self._default:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value) -> None:
        # Deliberately never auto-prunes on a default-valued write (see
        # `LedgerEdge.fondness`'s docstring) — an explicit `agent.
        # debts[id] = 0.0` must stay readable until something actually
        # deletes the key, same as the plain dict this replaces. Only
        # `__delitem__` below prunes.
        edge = self._ledger.get_or_create(key)
        setattr(edge, self._attr, value)

    def __delitem__(self, key) -> None:
        edge = self._ledger.edges.get(key)
        if edge is None:
            raise KeyError(key)
        value = getattr(edge, self._attr)
        if value is None or value == self._default:
            raise KeyError(key)
        setattr(edge, self._attr, self._default)
        self._ledger.prune_if_empty(key)

    def __iter__(self):
        for key, edge in self._ledger.edges.items():
            value = getattr(edge, self._attr)
            if value is not None and value != self._default:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __repr__(self) -> str:
        return repr(dict(self.items()))


class _GrievanceView(MutableMapping):
    """Read/delete proxy over `LedgerEdge.grievances` — see
    `_FieldView`'s docstring for why the mutable-list field can't use
    the generic proxy. Writes go through `Ledger.add_grievance`/
    `clear_grievance`, not `__setitem__` (present only so `.pop(id,
    None)`, `.get(id)`, `in`, and `.items()` — the read-side patterns
    already in use — keep working)."""

    __slots__ = ("_ledger",)

    def __init__(self, ledger: "Ledger") -> None:
        self._ledger = ledger

    def __getitem__(self, key):
        edge = self._ledger.edges.get(key)
        if edge is None or not edge.grievances:
            raise KeyError(key)
        return edge.grievances

    def __setitem__(self, key, value) -> None:
        edge = self._ledger.get_or_create(key)
        edge.grievances = list(value)
        if not edge.grievances:
            self._ledger.prune_if_empty(key)

    def __delitem__(self, key) -> None:
        edge = self._ledger.edges.get(key)
        if edge is None or not edge.grievances:
            raise KeyError(key)
        edge.grievances = []
        self._ledger.prune_if_empty(key)

    def __iter__(self):
        for key, edge in self._ledger.edges.items():
            if edge.grievances:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __repr__(self) -> str:
        return repr(dict(self.items()))


class Ledger:
    """One agent's full set of directional pairwise edges, keyed by
    the other agent's id. Backs `Agent.relationships`/`trust`/`debts`/
    `relationship_flags`/`grievances` (via the views below, unchanged
    external shape) plus the new `promises`/`history_tags` axes."""

    def __init__(self) -> None:
        self.edges: dict[int, LedgerEdge] = {}
        self.fondness_view = _FieldView(self, "fondness", None)
        self.trust_view = _FieldView(self, "trust", None)
        self.debt_view = _FieldView(self, "debt", None)
        self.flag_view = _FieldView(self, "flag", "")
        self.grievance_view = _GrievanceView(self)

    def get_or_create(self, other_id: int) -> LedgerEdge:
        edge = self.edges.get(other_id)
        if edge is None:
            edge = LedgerEdge()
            self.edges[other_id] = edge
        return edge

    def prune_if_empty(self, other_id: int) -> None:
        edge = self.edges.get(other_id)
        if edge is not None and edge.is_empty():
            del self.edges[other_id]

    def prune_dead(self, alive_ids: set[int]) -> None:
        """Same "dead weight, no observable behavior change" discipline
        as the pre-ledger per-dict death cleanup (v0.42.0/v1.3.17) —
        drop every edge pointing at someone no longer alive."""
        for other_id in [k for k in self.edges if k not in alive_ids]:
            del self.edges[other_id]

    # --- grievances (mutable-list field, see _GrievanceView) --------------

    def add_grievance(self, other_id: int, text: str, cap: int) -> None:
        if not text:
            return
        edge = self.get_or_create(other_id)
        edge.grievances.append(text)
        if len(edge.grievances) > cap:
            del edge.grievances[0]

    def clear_grievance(self, other_id: int) -> None:
        edge = self.edges.get(other_id)
        if edge is None:
            return
        edge.grievances = []
        self.prune_if_empty(other_id)

    # --- promises (Phase 2) ------------------------------------------------

    def add_promise(self, other_id: int, promise: dict) -> None:
        edge = self.get_or_create(other_id)
        edge.promises.append(promise)
        if len(edge.promises) > MAX_PROMISES_PER_EDGE:
            del edge.promises[0]

    def open_promises(self, other_id: int) -> list[dict]:
        edge = self.edges.get(other_id)
        return list(edge.promises) if edge is not None else []

    def resolve_promise(self, other_id: int, index: int) -> None:
        edge = self.edges.get(other_id)
        if edge is None or not (0 <= index < len(edge.promises)):
            return
        del edge.promises[index]
        self.prune_if_empty(other_id)

    # --- history tags --------------------------------------------------

    def add_history_tag(self, other_id: int, tag: str) -> None:
        self.get_or_create(other_id).history_tags.add(tag)

    def has_history_tag(self, other_id: int, tag: str) -> bool:
        edge = self.edges.get(other_id)
        return edge is not None and tag in edge.history_tags

    # --- serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            str(other_id): {
                "fondness": round(edge.fondness, 4) if edge.fondness is not None else None,
                "trust": round(edge.trust, 4) if edge.trust is not None else None,
                "debt": round(edge.debt, 4) if edge.debt is not None else None,
                "flag": edge.flag,
                "grievances": list(edge.grievances),
                "promises": [dict(p) for p in edge.promises],
                "history_tags": sorted(edge.history_tags),
            }
            for other_id, edge in self.edges.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ledger":
        ledger = cls()
        for key, entry in data.items():
            ledger.edges[int(key)] = LedgerEdge(
                fondness=entry.get("fondness"),
                trust=entry.get("trust"),
                debt=entry.get("debt"),
                flag=entry.get("flag", ""),
                grievances=list(entry.get("grievances", [])),
                promises=[dict(p) for p in entry.get("promises", [])],
                history_tags=set(entry.get("history_tags", [])),
            )
        return ledger
