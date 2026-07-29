"""A7, first slice, settlement-layout domain (see `world/dialect_
grammar.py`'s module docstring for the shared design decision this
batch resolves). A small closed set of layout STYLES, each a real
deterministic scoring bias over `Population._choose_build_site`'s
existing road/resource-adjacency scan — not a full graph grammar
rewriting an explicit settlement graph, but the same spirit at the
scope this project's site-selection already has: "the grammar expands
and varies deterministically and cheaply" on top of the LLM-free
scoring that already exists, rather than a new subsystem replacing it.

`settlement_layout_style` is a pure function of the settlement's own
id — stable for that settlement's whole lifetime, no RNG, so it can't
introduce any native-soak-parity risk when wired into a hot path."""

from __future__ import annotations

import hashlib

LAYOUT_STYLES: tuple[str, ...] = ("radial", "linear", "clustered")
"""radial: buildings prefer a consistent ring-distance from the
settlement's center, echoing a wheel/hub layout. linear: buildings
prefer sites that keep roughly the same offset along one axis from
center, echoing a street/line layout. clustered: buildings prefer
sites immediately adjacent to already-standing ones, echoing a tight
huddled layout — no consistent geometry, just density."""

RADIAL_TARGET_RING = 3
"""Preferred distance-from-center (Chebyshev) for the radial style —
matches `BUILD_SITE_SEARCH_RADIUS`'s own scale so the bonus is
reachable within a single search, not a target outside the scan."""

LAYOUT_BONUS_SCALE = 1.0
"""Same order of magnitude as `BUILD_SITE_ADJACENCY_SCORE` (road/
resource adjacency) — a real, comparable factor in site choice, not a
token nudge nor a score-dominating override."""


def settlement_layout_style(settlement_id: int) -> str:
    """Deterministic, stable for the settlement's whole lifetime. Used
    only for a settlement with no lineage to inherit from (the founding
    settlement, or any legacy snapshot predating `Settlement.layout_
    style`'s existence) — see `drift_layout_style` for the real
    generational production rule a fission daughter goes through
    instead."""
    return LAYOUT_STYLES[settlement_id % len(LAYOUT_STYLES)]


LAYOUT_DRIFT_STAY_WEIGHT = 2
"""A7 follow-up (roadmap Tier 3, layout domain — dialect_grammar's
`drift_term` and architecture_grammar's per-instance descriptor already
had their own recursive/varying mechanisms; layout was the one domain
still a flat `settlement_id % 3` hash with zero lineage awareness).
`drift_layout_style` is the real one-generation production rule: with
weight `LAYOUT_DRIFT_STAY_WEIGHT` the daughter keeps its parent's style
exactly (most fissions shouldn't visibly change a village's spatial
character), otherwise the style rewrites to the NEXT style in `LAYOUT_
STYLES`' fixed cycle — a small, closed alphabet, so "rotate to the next
option" is the natural production rule (mirrors `dialect_grammar`'s own
small-alphabet rewrite shape, just discrete-cycle instead of string-
mutation). Called once per fission (a real generational step), so a
lineage several fissions deep can end up several styles removed from
its founding settlement's tradition — the same "further-removed
lineages drift further" effect `dialect_grammar.drift_term`'s `steps`
parameter gives coined terms, achieved here by simple repeated
one-step application across generations rather than a single call with
a `steps` count, since (unlike a coined word) each generation's style
is itself real persisted state a later fission reads directly."""


def _pick(seed_text: str, options: tuple[str, ...]) -> str:
    """Same deterministic hash-pick shape `architecture_grammar.py`
    already established — sha256 the seed, index into a small closed
    option pool by its first byte."""
    digest = hashlib.sha256(seed_text.encode()).digest()
    return options[digest[0] % len(options)]


def drift_layout_style(style: str, seed: str) -> str:
    """One real production-rule application: a fission daughter's
    layout style is (usually) its parent's, occasionally rewritten to
    the next style in the cycle. `seed` must be unique per fission
    event (the caller passes the new settlement's id) so two daughters
    fissioning from the same parent in the same tick can still draw
    independently."""
    if style not in LAYOUT_STYLES:
        style = LAYOUT_STYLES[0]
    pool = ("stay",) * LAYOUT_DRIFT_STAY_WEIGHT + ("drift",)
    if _pick(f"{seed}:layout_drift", pool) == "stay":
        return style
    idx = LAYOUT_STYLES.index(style)
    return LAYOUT_STYLES[(idx + 1) % len(LAYOUT_STYLES)]


def layout_site_bonus(
    style: str, center_x: int, center_y: int, x: int, y: int,
    standing_positions: frozenset[tuple[int, int]],
) -> float:
    """The one real production-rule expansion this slice ships: how
    much extra score a candidate `(x, y)` site earns under `style`,
    on top of `Population._choose_build_site`'s existing road/resource
    scoring. `standing_positions` (already-built tiles in this
    settlement) is only consulted by `clustered`."""
    if style == "radial":
        ring = max(abs(x - center_x), abs(y - center_y))
        return LAYOUT_BONUS_SCALE * max(0.0, 1.0 - abs(ring - RADIAL_TARGET_RING) / max(1, RADIAL_TARGET_RING))
    if style == "linear":
        offset = abs(y - center_y) if abs(x - center_x) >= abs(y - center_y) else abs(x - center_x)
        return LAYOUT_BONUS_SCALE * max(0.0, 1.0 - offset / 2.0)
    if style == "clustered":
        if not standing_positions:
            return 0.0
        nearest = min(
            max(abs(x - px), abs(y - py)) for px, py in standing_positions
        )
        return LAYOUT_BONUS_SCALE * max(0.0, 1.0 - nearest / 3.0)
    return 0.0
