"""Deterministic settlement-name generation.

Same "small fixed pool, no external dependencies" approach as
agents/names.py, kept as a separate module since it's a different
namespace (place names vs. person names) with a different generation
rule (prefix+suffix compound rather than draw-without-replacement). See
docs/DECISIONS.md, E1.
"""
from __future__ import annotations

import random

_PREFIXES: tuple[str, ...] = (
    "Ash", "Bramble", "Cros", "Dun", "Elm", "Fern", "Green", "Hollow",
    "Iron", "Lark", "Mill", "Oak", "Ridge", "Stone", "Thorn", "Wren",
)

_SUFFIXES: tuple[str, ...] = (
    "ford", "haven", "hollow", "mere", "moor", "reach", "stead", "vale",
    "watch", "wick", "wood",
)


def generate_settlement_name(rng: random.Random) -> str:
    return rng.choice(_PREFIXES) + rng.choice(_SUFFIXES)
