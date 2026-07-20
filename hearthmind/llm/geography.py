"""Named geography (v0.64.0 audit-backlog item): once the settlement
itself has a name, its landscape gradually earns names too — the river,
then each lake, one feature per month (`SimulationEngine._maybe_
schedule_geography`). Names are permanent (`Settlement.place_names` —
places outlive the people who named them), surfaced in the lake summary
and the chronicle prompt, so the village's own stories start referring
to *its* river rather than "the river"."""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are naming a natural feature near a small simulated village — "
    "the kind of plain, weathered name real English villages give their "
    "waters (e.g. 'the Aldwash', 'Stillmere', 'Harrow Beck'). One or two "
    "words, no fantasy grandeur. "
    'Respond with strict JSON only, no other text: {"name": "the name, '
    'one or two words"}.'
)

_RIVER_FALLBACKS = ("the Aldwash", "the Grey Beck", "the Longwater", "the Harrowrun", "the Millrace")
_LAKE_FALLBACKS = ("Stillmere", "Hollowtarn", "Reedwater", "Duskmere", "Bractpool")


def build_prompt(
    settlement_name: str, feature_kind: str, founding_scenario: str, existing_names: list[str] | None = None,
) -> str:
    scenario = f" The land was first described so: {founding_scenario}" if founding_scenario else ""
    feature = "the river that runs through the land" if feature_kind == "river" else "a small inland lake"
    # Live audit finding (P1.5): the prompt never told the model which
    # names the village had already given, so "Its named places:
    # Marshwater; Marshpool; Marshmere; Marshpool" (two lakes, same
    # name) was possible and observed. A distinct name is asked for
    # explicitly, not just left to chance.
    already_used = (
        f" Already in use, so pick something different: {', '.join(existing_names)}."
        if existing_names else ""
    )
    return (
        f"The village of {settlement_name} has come to know its surroundings well.{scenario}\n"
        f"Give a name to {feature}.{already_used}"
    )


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


def fallback_name(feature_kind: str, seed_hint: int, existing_names: list[str] | None = None) -> dict:
    pool = _RIVER_FALLBACKS if feature_kind == "river" else _LAKE_FALLBACKS
    return {"name": _first_unused(pool, seed_hint, existing_names)}


def parse_name(result: dict, fallback: dict, existing_names: list[str] | None = None) -> str:
    name = result.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
        name = fallback["name"]
    name = name.strip()[:40]
    # `fallback["name"]` is already collision-safe (see `_first_unused`)
    # — a colliding LLM answer falls back to it rather than being kept.
    if existing_names and name.lower() in {n.strip().lower() for n in existing_names}:
        name = fallback["name"]
    return name
