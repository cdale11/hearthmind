"""B14.2's real diff format (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B) — the concrete mechanism `simulation/persistence_scheduling.
py`'s `SnapshotScheduler.plan()` was built to consume but, until now,
had no real writer for. `plan()`'s own docstring names the design
constraint this module exists to satisfy: `_prune_snapshots` (see
`persistence/snapshot.py`) has no concept of a FULL+INCREMENTAL chain,
so a naive diff format would let pruning silently orphan an
unreconstructable snapshot — see `snapshot.py`'s `_prune_snapshots`
for how the chain is kept intact.

`diff_dict`/`apply_patch` are a plain recursive structural diff over
JSON-serializable dicts: nested DICT values are diffed recursively key
by key; every other value (list, str, int, float, bool, None) is
compared by `==` and, if changed, replaced WHOLESALE — no element-wise
list diffing. This is a deliberate scope trim, not an oversight: `World.
to_dict()`'s dominant top-level branches (`terrain`, `settlements`,
`population`, ...) are each large sub-dicts/sub-lists that mostly
either change together (a settlement's own dict) or stay fully static
for long stretches (terrain, unless a rare terraforming event fires) —
recursing into DICTS already captures the real win (an unchanged
branch contributes nothing to the patch) without the correctness risk
of a general list-diff algorithm (index drift, list-of-dicts identity
tracking) on a codebase with no automated test suite. A future pass
that measures real patch sizes on a live run and finds list-heavy
branches (e.g. `population.agents`) still dominate patch size could
extend this to a keyed list diff (matching list-of-dict elements by a
stable `id` field) as a strict addition — this format's own round-trip
contract doesn't change either way.
"""
from __future__ import annotations

_SENTINEL = object()


def diff_dict(old: dict, new: dict) -> dict:
    """Structural diff from `old` to `new`. Returns a patch dict with
    up to three keys:

    - `"set"`: keys added or replaced wholesale (their new value, taken
      directly — could itself be a dict, just not one both sides had
      to recurse into).
    - `"recurse"`: keys where BOTH `old[k]` and `new[k]` are dicts —
      the value is the nested patch from `diff_dict(old[k], new[k])`.
    - `"del"`: keys present in `old` but absent from `new`.

    A key unchanged (`old[k] == new[k]`, or a recursed key whose nested
    diff is itself empty) is omitted entirely — the whole point of the
    format. `apply_patch(old, diff_dict(old, new)) == new` for any two
    JSON-serializable dicts; see `scripts/verify_b14_snapshot_diff.py`
    for the randomized property test proving this."""
    set_: dict = {}
    recurse: dict = {}
    del_: list = []

    for key, new_value in new.items():
        old_value = old.get(key, _SENTINEL)
        if old_value is _SENTINEL:
            set_[key] = new_value
            continue
        if old_value == new_value:
            continue
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            nested = diff_dict(old_value, new_value)
            if nested["set"] or nested["recurse"] or nested["del"]:
                recurse[key] = nested
            continue
        set_[key] = new_value

    for key in old:
        if key not in new:
            del_.append(key)

    return {"set": set_, "recurse": recurse, "del": del_}


def apply_patch(old: dict, patch: dict) -> dict:
    """The exact inverse of `diff_dict`: reconstructs `new` from `old`
    and `patch`. Never mutates `old` — returns a fresh dict (and fresh
    nested dicts wherever `"recurse"` descends), so a caller can safely
    reuse `old` as the base for a second, independent reconstruction
    (e.g. two different INCREMENTAL descendants of the same FULL
    ancestor)."""
    result = dict(old)
    for key in patch.get("del", ()):
        result.pop(key, None)
    for key, value in patch.get("set", {}).items():
        result[key] = value
    for key, nested in patch.get("recurse", {}).items():
        result[key] = apply_patch(result.get(key, {}), nested)
    return result
