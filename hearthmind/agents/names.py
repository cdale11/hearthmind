"""Deterministic name generation for agents.

A small fixed pool rather than a markov chain or external wordlist, kept
in the same "no external dependencies" spirit as terrain/weather (see
README). Swappable later without touching callers.
"""
from __future__ import annotations

import random

_NAME_POOL: tuple[str, ...] = (
    "Aldric", "Branwen", "Cedric", "Dagny", "Edda", "Fenwick", "Gareth", "Hilde",
    "Ivo", "Jorah", "Kestrel", "Liora", "Merrick", "Nissa", "Osric", "Petra",
    "Quill", "Rosalind", "Sten", "Tamsin", "Ulric", "Vesna", "Wren", "Yorick",
    "Aveline", "Bartholomew", "Corwin", "Delphine", "Emrys", "Freya", "Godfrey",
    "Halvard", "Isolde", "Jasper", "Katla", "Lennart", "Mireille", "Nolan",
    "Odette", "Percival", "Quenna", "Roswitha", "Soren", "Thea", "Ursula",
    "Varian", "Wilhelmina", "Xander", "Ysolde", "Zephyrine",
)


def generate_names(count: int, rng: random.Random) -> list[str]:
    """Return `count` names, deterministic given `rng`'s state.

    Draws without replacement from the pool while it lasts, then falls back
    to "<name> II", "<name> III", ... so an arbitrarily large population
    never runs out of names.
    """
    pool = list(_NAME_POOL)
    rng.shuffle(pool)

    names: list[str] = []
    generation = 1
    index = 0
    while len(names) < count:
        if index >= len(pool):
            index = 0
            generation += 1
        base = pool[index]
        names.append(base if generation == 1 else f"{base} {_roman(generation)}")
        index += 1
    return names


def _roman(n: int) -> str:
    values = (10, 9, 5, 4, 1)
    symbols = ("X", "IX", "V", "IV", "I")
    result = []
    for value, symbol in zip(values, symbols):
        count, n = divmod(n, value)
        result.append(symbol * count)
    return "".join(result)
