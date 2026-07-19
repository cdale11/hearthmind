"""The one-time "genesis" call, made before a brand-new world's terrain
and weather are generated: an evocative founding-scenario sentence
describing the site the first inhabitants are about to claim. See
CLAUDE.md, "LLM as the town's brain," and docs/DECISIONS.md,
real-calendar/genesis-seed follow-up.

Only runs for a brand-new world when `--seed` was omitted (server.py) — an
explicit seed always wins, and a resumed world never re-runs genesis.

v1 audit fix (`detect_terrain_features`, below): earlier versions hashed
the LLM's own scenario text into the world's RNG seed ("literal rather
than cosmetic"), but that meant the actual generated terrain and the
narrated founding scenario were mathematically unrelated — a genesis
sentence could promise "a river valley" over a map with no river
anywhere near spawn, since the terrain wasn't generated yet when the
text was written. `server.py`'s `_resolve_genesis_seed` now generates a
real preview terrain from its own entropy FIRST, describes what's
actually near the map's center via `detect_terrain_features`, and feeds
that into the prompt as the lean — then uses that same entropy as the
final world seed, so the terrain the genesis text describes is
guaranteed to be the terrain the world actually has. The scenario is
still LLM-authored and still the founding record everything downstream
(naming, geography, beliefs, chronicle) treats as canon — it's simply
no longer doing double duty as the RNG seed itself.
"""
from __future__ import annotations

import random

SYSTEM_PROMPT = (
    "You are imagining the founding moment of a brand-new village site, in "
    "a quiet corner of a temperate, rain-prone land, at the dawn of an "
    "industrial age. Respond with strict JSON only, no other text: "
    '{"scenario": "one evocative sentence, under 30 words, describing the '
    'unsettled land the first inhabitants are about to claim, and something '
    'of who these first inhabitants are or what brought them here"}.'
)


_TERRAIN_FLAVOR_HINTS = (
    "rolling farmland", "a river valley", "a windswept coastline", "highland moor",
    "a forest-edge clearing", "chalky downland", "a marshy lowland", "a stony upland",
    "a lakeside meadow", "a narrow wooded dale",
)
"""v0.87.37 context-selection audit ("improve world genesis prompting"):
previously `build_prompt()` took zero arguments and returned the exact
same literal string on every call — the ONLY variety across different
worlds' genesis scenarios came from the LLM's own sampling temperature,
while real per-world entropy (`_resolve_genesis_seed`'s `fallback_hint`,
already drawn from `random.SystemRandom()` before this call) sat right
there unused, spent only on the fallback pool and the final XOR. A
small rotating flavor cue drawn from that same entropy now reaches the
live-LLM prompt too — a loose starting point, not a constraint (the
model is explicitly told it's free to depart from it), so scenarios
stay varied by construction rather than hoping temperature alone
prevents convergence on a handful of similar-sounding openings.

v1 audit fix (this file, see `detect_terrain_features`): kept as the
fallback lean for callers that pass a bare `flavor_hint` with no real
terrain to inspect (tests, `fallback_scenario`'s offline pool). The
live path now prefers `detected_features` — a description of the
ACTUAL generated map near spawn — over this fixed list, since a
"lean toward a river valley" that isn't backed by any real water tile
was cosmetically varied but factually disconnected from the world it
was describing."""

_SETTLER_CIRCUMSTANCE_HINTS = (
    "a small band fleeing a failed harvest elsewhere",
    "religious dissenters seeking a place of their own",
    "a hopeful young family striking out on their own",
    "opportunists chasing rumors of good land",
    "a displaced offshoot of a larger, crowded settlement",
    "refugees from a flood upriver",
    "laborers granted this land by a distant, indifferent lord",
    "wanderers who simply stopped when the land looked kind",
    "kin following an elder's half-remembered stories of this place",
    "strangers thrown together by shared misfortune on the road",
)
"""v1 audit fix: `_TERRAIN_FLAVOR_HINTS` only ever varied landscape
aesthetics — nothing about *who* the founders are or *why* they're
here, even though genesis is a one-time, high-leverage seed for the
whole world's downstream beliefs/culture/records (`naming.py`,
`geography.py`, `beliefs.py` all eventually build atop this same
`founding_scenario` text). A second, independent hint axis — drawn
from the same real entropy, via a different modulus so it doesn't
just track the terrain pick — gives the model a human dimension to
lean on too, without constraining it any harder than the terrain
lean does."""


def detect_terrain_features(tiles: list, radius: int = 10) -> str:
    """v1 audit fix: describes what's ACTUALLY near the map's center
    (where founders cluster, per the spring-start/best-wild-food-site
    rule) in a just-generated terrain grid, for `build_prompt`'s
    `detected_features` to ground the genesis prompt in truth rather
    than an arbitrary flavor label that may not match anything the
    world actually generated. Cheap: one bounded window scan over a
    small square around center, not a full-map pass. `tiles` is a
    `list[list[Tile]]` from `world.terrain.generate_terrain`; imported
    lazily inside the function body to avoid a hard dependency for
    callers (tests, the offline fallback path) that never need it."""
    from hearthmind.world.terrain import Biome

    height = len(tiles)
    width = len(tiles[0]) if height else 0
    if width == 0 or height == 0:
        return ""
    cx, cy = width // 2, height // 2
    counts: dict[Biome, int] = {}
    total = 0
    for y in range(max(0, cy - radius), min(height, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(width, cx + radius + 1)):
            biome = tiles[y][x].biome
            counts[biome] = counts.get(biome, 0) + 1
            total += 1
    if total == 0:
        return ""
    water = counts.get(Biome.SHALLOW_WATER, 0) + counts.get(Biome.DEEP_WATER, 0)
    hills = counts.get(Biome.HILLS, 0) + counts.get(Biome.MOUNTAIN, 0)
    forest = counts.get(Biome.FOREST, 0)
    beach = counts.get(Biome.BEACH, 0)
    grassland = counts.get(Biome.GRASSLAND, 0)
    features: list[str] = []
    if beach > 0 and water / total > 0.3:
        features.append("a coastline")
    elif water / total > 0.15:
        features.append("open water nearby")
    if hills / total > 0.25:
        features.append("rolling hills or high ground")
    if forest / total > 0.35:
        features.append("dense forest")
    if grassland / total > 0.45 and not features:
        features.append("open grassland")
    if not features:
        return ""
    return " and ".join(features[:2])


def build_prompt(
    flavor_hint: int | None = None, detected_features: str | None = None,
) -> str:
    """`detected_features` (optional, preferred when available): a
    short phrase from `detect_terrain_features` describing what's
    actually near the map's center in the terrain already generated
    for this world — the genuinely grounded lean. `flavor_hint`
    (optional): an integer used to pick one of `_TERRAIN_FLAVOR_HINTS`
    (terrain) and `_SETTLER_CIRCUMSTANCE_HINTS` (who/why) as loose
    thematic leans when no real terrain is available to inspect yet —
    pass real entropy (e.g. `_resolve_genesis_seed`'s own
    `fallback_hint`) so each brand-new world's genesis prompt differs
    by more than sampling noise. Neither argument (the old, still-
    supported call shape) omits every lean, unchanged from before this
    pass. Both may be combined: `detected_features` grounds the land,
    `flavor_hint` still supplies the settler-circumstance lean, since
    "who these people are" has no terrain-derived ground truth to
    check against."""
    lean = ""
    if detected_features:
        lean = f" The land here has {detected_features}, though the details are yours to imagine."
    elif flavor_hint is not None:
        flavor = _TERRAIN_FLAVOR_HINTS[flavor_hint % len(_TERRAIN_FLAVOR_HINTS)]
        lean = f" Lean toward {flavor} as a loose starting point, but make it your own."
    if flavor_hint is not None:
        circumstance = _SETTLER_CIRCUMSTANCE_HINTS[(flavor_hint // 7) % len(_SETTLER_CIRCUMSTANCE_HINTS)]
        lean += f" The first inhabitants might be {circumstance}, or invent your own reason they've come."
    return (
        "Describe the founding scenario for a new settlement site, about to be "
        f"claimed for the first time.{lean}"
    )


_FALLBACK_SCENARIOS = (
    "Rolling grassland meets old forest along a slow river, unclaimed and quiet.",
    "A windswept hillside overlooks a valley thick with timber and old stone.",
    "Damp lowland meadow borders a dark treeline, mist clinging to the morning air.",
    "A stony ridge gives way to fertile bottomland, marked only by deer trails.",
    "Gorse-covered moorland slopes down to a sheltered, forested hollow.",
    "A chalky rise overlooks water-meadows, silent but for wind and birdsong.",
)
"""Used when the LLM is disabled or unreachable — a small rotating pool
rather than a single fixed line, so an offline run still gets some
variety (mixed with wall-clock entropy at the seed stage — see
server.py — so it isn't just one of six possible worlds forever)."""


def fallback_scenario(seed_hint: int) -> dict:
    rng = random.Random(seed_hint)
    return {"scenario": rng.choice(_FALLBACK_SCENARIOS)}


def parse_scenario(result: dict, fallback: dict) -> str:
    scenario = result.get("scenario")
    if not isinstance(scenario, str) or not scenario.strip():
        scenario = fallback["scenario"]
    return scenario.strip()[:240]
