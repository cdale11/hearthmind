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


def build_prompt(settlement_name: str, feature_kind: str, founding_scenario: str) -> str:
    scenario = f" The land was first described so: {founding_scenario}" if founding_scenario else ""
    feature = "the river that runs through the land" if feature_kind == "river" else "a small inland lake"
    return (
        f"The village of {settlement_name} has come to know its surroundings well.{scenario}\n"
        f"Give a name to {feature}."
    )


def fallback_name(feature_kind: str, seed_hint: int) -> dict:
    pool = _RIVER_FALLBACKS if feature_kind == "river" else _LAKE_FALLBACKS
    return {"name": pool[seed_hint % len(pool)]}


def parse_name(result: dict, fallback: dict) -> str:
    name = result.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
        name = fallback["name"]
    return name.strip()[:40]
