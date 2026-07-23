"""A7, first slice, architecture domain (see `world/dialect_grammar.py`'s
module docstring for the shared design decision this batch resolves).
A small closed shape grammar producing ONE structural descriptor phrase
per building instance — the axiom is "a building of this kind, in this
material, in this settlement's layout tradition"; production rules fill
three independent feature slots (roof/wall/ornament) from small closed
vocabularies. Deterministic, hash-seeded per building id — no LLM call,
no RNG stream, and genuinely varies between two buildings of the same
kind/material (unlike `world/materials.py`'s per-kind-only `Built of`
line, which reads identically for every HUT)."""

from __future__ import annotations

import hashlib

ROOF_FEATURES: tuple[str, ...] = ("a steep thatched roof", "a low turf roof", "a shallow shingled roof")
WALL_FEATURES: tuple[str, ...] = ("packed walls", "close-set timber framing", "a raised stone plinth")
ORNAMENT_FEATURES: tuple[str, ...] = (
    "carved lintels", "a hearth-stone worn smooth", "woven wind-charms at the eaves", "no ornament to speak of",
)

_LAYOUT_ROOF_BIAS: dict[str, tuple[str, ...]] = {
    "radial": ("a steep thatched roof",),
    "linear": ("a shallow shingled roof",),
    "clustered": ("a low turf roof",),
}
"""A settlement's layout style biases (not forces) its buildings' roof
feature toward one option — "a building echoes its village's layout
tradition." Falls through to the full `ROOF_FEATURES` pool when the
style-preferred option would otherwise dominate every building of that
style identically (see `_pick`'s fallback)."""


def _pick(seed_text: str, options: tuple[str, ...]) -> str:
    digest = hashlib.sha256(seed_text.encode()).digest()
    return options[digest[0] % len(options)]


def building_descriptor(building_id: int, kind: str, material: str, layout_style: str | None = None) -> str:
    """One deterministic sentence fragment describing this specific
    building instance — stable for the building's lifetime (seeded by
    its own id, not kind/material alone, so two HUTs of the same
    material still read differently)."""
    seed = f"{building_id}:{kind}:{material}"
    roof_pool = ROOF_FEATURES
    if layout_style in _LAYOUT_ROOF_BIAS and _pick(seed + ":style", ("bias", "bias", "free")) == "bias":
        roof_pool = _LAYOUT_ROOF_BIAS[layout_style]
    roof = _pick(seed + ":roof", roof_pool)
    wall = _pick(seed + ":wall", WALL_FEATURES)
    ornament = _pick(seed + ":ornament", ORNAMENT_FEATURES)
    return f"{roof}, {wall}, {ornament}"
