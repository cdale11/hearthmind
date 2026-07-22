"""Named geography (v0.64.0 audit-backlog item): once the settlement
itself has a name, its landscape gradually earns names too — the river,
then each lake, one feature per month (`SimulationEngine._maybe_
schedule_geography`). Names are permanent (`Settlement.place_names` —
places outlive the people who named them), surfaced in the lake summary
and the chronicle prompt, so the village's own stories start referring
to *its* river rather than "the river".

Made fully procedural (explicit user directive): a plain, weathered
place name ("Stillmere", "the Aldwash") carries no interpretation or
judgment the LLM would meaningfully add — it's the same category of
decision as `world_genesis`'s deterministic placeholder settlement
name, just never superseded. No LLM call site remains for this job."""
from __future__ import annotations

_RIVER_FALLBACKS = ("the Aldwash", "the Grey Beck", "the Longwater", "the Harrowrun", "the Millrace")
_LAKE_FALLBACKS = ("Stillmere", "Hollowtarn", "Reedwater", "Duskmere", "Bractpool")


def _first_unused(pool: tuple[str, ...], seed_hint: int, existing_names: list[str] | None) -> str:
    used = {n.strip().lower() for n in existing_names} if existing_names else set()
    for offset in range(len(pool)):
        candidate = pool[(seed_hint + offset) % len(pool)]
        if candidate.strip().lower() not in used:
            return candidate
    # Exhausted a 5-entry pool against already-used names — vanishingly
    # rare (would need 5+ features already named), but never return a
    # colliding fallback: disambiguate with a plain numeral.
    return f"{pool[seed_hint % len(pool)]} II"


def name_feature(feature_kind: str, seed_hint: int, existing_names: list[str] | None = None) -> str:
    pool = _RIVER_FALLBACKS if feature_kind == "river" else _LAKE_FALLBACKS
    return _first_unused(pool, seed_hint, existing_names)
