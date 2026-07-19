"""The one-time "genesis" call, made before a brand-new world's terrain
and weather are generated: an evocative founding-scenario sentence whose
hash becomes the world's RNG seed. This is what makes "initial terrain and
weather state chosen by an LLM" literal rather than cosmetic — the LLM's
own text is the seed, and that seed then drives the ordinary deterministic
terrain/weather generation exactly as an explicit `--seed` would (see
world/terrain.py, world/weather.py). See CLAUDE.md, "LLM as the town's
brain," and docs/DECISIONS.md, real-calendar/genesis-seed follow-up.

Only runs for a brand-new world when `--seed` was omitted (server.py) — an
explicit seed always wins, and a resumed world never re-runs genesis.
"""
from __future__ import annotations

import hashlib
import random

SYSTEM_PROMPT = (
    "You are imagining the founding moment of a brand-new village site, in "
    "a quiet corner of a temperate, rain-prone land, at the dawn of an "
    "industrial age. Respond with strict JSON only, no other text: "
    '{"scenario": "one evocative sentence, under 30 words, describing the '
    'unsettled land the first inhabitants are about to claim"}.'
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
prevents convergence on a handful of similar-sounding openings."""


def build_prompt(flavor_hint: int | None = None) -> str:
    """`flavor_hint` (optional): an integer used to pick one of
    `_TERRAIN_FLAVOR_HINTS` as a loose thematic lean — pass real entropy
    (e.g. `_resolve_genesis_seed`'s own `fallback_hint`) so each brand-
    new world's genesis prompt differs by more than sampling noise.
    `None` (the old, still-supported call shape) omits the lean
    entirely, unchanged from before this pass."""
    lean = ""
    if flavor_hint is not None:
        flavor = _TERRAIN_FLAVOR_HINTS[flavor_hint % len(_TERRAIN_FLAVOR_HINTS)]
        lean = f" Lean toward {flavor} as a loose starting point, but make it your own."
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


def seed_from_scenario(scenario: str) -> int:
    """A deterministic, always-positive int from the scenario text —
    used directly as the world seed for an LLM-authored scenario, or
    XORed with wall-clock entropy for a fallback one (see server.py)."""
    digest = hashlib.sha256(scenario.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
