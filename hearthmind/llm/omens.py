"""Omens: rare, ambiguous, never-explained flavor events.

`Settlement.temperament` is entirely deterministic — a real value computed
from real recent-event counts plus bounded noise (see
`settlement.buildings.tick_temperament`). This module is purely the LLM's
narrative layer riding on top of it: when temperament is running strongly
warm or cold, there's a small chance the village notices *something* —
worded so it could be pure coincidence, local superstition, or nothing at
all. Nothing here, in the fallback pool, or in any prompt ever asserts the
town is literally conscious or magical; that reading is left entirely to
the player. See CLAUDE.md, "the town is itself a subtle character... keep
this ambiguous, never explicitly explain the supernatural."
"""
from __future__ import annotations

OMEN_CHANCE_BASE = 0.05
"""Base per-month roll, before the temperament-magnitude scaling below —
deliberately rare; an omen every month would stop reading as unusual."""

OMEN_CHANCE_TEMPERAMENT_SCALE = 0.25
"""Additional chance scaled by |temperament| — a strongly warm or cold
month makes an omen somewhat more likely to be noticed, without ever
making it common."""

SYSTEM_PROMPT = (
    "You are noting a small, unexplained occurrence noticed in a simulated "
    "village — something residents mention to each other without quite "
    "agreeing on what it meant. It should be ordinary enough to have a "
    "mundane explanation (an animal's behavior, a trick of light, a run of "
    "coincidences, an old building's odd creak) and never confirmed as "
    "anything more. Match the tone to whether the village's fortunes have "
    "lately felt lucky or unlucky, without saying so directly. "
    'Respond with strict JSON only, no other text: {"omen": "one sentence, '
    'under 25 words, described as something noticed, not explained"}.'
)


def build_prompt(
    settlement_name: str, temperament: float, recent_events: list[dict], subject_name: str = "",
    past_omens: list[str] | None = None,
) -> str:
    lean = "unusually fortunate" if temperament > 0.15 else "unusually unlucky" if temperament < -0.15 else "unremarkable"
    lines = [f"- {event['description']}" for event in recent_events[:10]]
    events_text = "\n".join(lines) if lines else "Nothing notable happened recently."
    subject_line = (
        f"\nCenter the noticed thing on {subject_name} specifically — something people have started saying "
        f"about {subject_name}, or that {subject_name} has noticed themselves — while keeping it just as "
        "mundane-explicable as ever, never confirming anything unusual about them."
        if subject_name else ""
    )
    # Continuity, not escalation: past omens are offered only as optional
    # texture (the village half-remembering something similar before),
    # never as a thread the new omen is required to follow — most omens
    # should still stand alone. See Settlement.omen_history's docstring.
    memory_line = (
        "\nIf it fits naturally, this could echo something noticed before (without saying so directly): "
        + "; ".join(past_omens[-3:])
        if past_omens else ""
    )
    return (
        f"The village of {settlement_name} has had a run of {lean} fortune lately.\n"
        f"Recent history:\n{events_text}{subject_line}{memory_line}\n"
        "Note one small, unexplained thing someone in the village noticed."
    )


_WARM_OMENS = (
    "A stray cat has taken to sleeping on the granary steps, and no one has the heart to move it.",
    "Someone swears the old well echoes a beat longer than it used to.",
    "Three separate households found their bread rose higher than usual this week.",
    "The oldest tree by the square has started budding out of season.",
    "A flock of birds has taken to circling the square each dusk before scattering — no one's alarmed by it.",
    "The bell in the square has been ringing a note truer than anyone remembers tuning it to.",
)
_COLD_OMENS = (
    "The dogs won't settle after dark this week, for no reason anyone can name.",
    "A crow has taken to circling the square each morning before flying off.",
    "Someone's lantern keeps going out on the same stretch of path, windless or not.",
    "The well water has tasted faintly of iron since the last frost.",
    "The mill's wheel groans at the same hour each night, though nothing is turning it.",
    "Footprints keep appearing on the north road at dawn that no one will claim.",
)
_NEUTRAL_OMENS = (
    "Nothing unusual, exactly — just a quiet the older residents say feels different lately.",
    "A traveler passing through paused at the village edge a moment longer than seemed necessary.",
    "The weathervane has settled on the same direction for three days straight, wind or no wind.",
)

_WARM_SUBJECT_OMENS = (
    "{name} has had an odd run of good luck lately, small enough that no one's quite said it aloud.",
    "Something about {name} has people smiling a little more than the occasion calls for.",
    "{name}'s shadow seemed to fall a beat later than it should have this evening — or so someone claimed.",
    "Every plant {name} has touched this week seems to be doing a little better than the rest.",
)
_COLD_SUBJECT_OMENS = (
    "The dogs go quiet whenever {name} walks past, though no one can say why.",
    "{name} mentioned a dream three nights running, and stopped mentioning it after the third.",
    "Someone noticed {name}'s reflection lag half a step behind them at the well — probably just the light.",
    "{name}'s candle keeps guttering indoors, though the windows are shut.",
)
"""Subject-referencing fallback pools, {name}-templated — the same
mundane-explicable ambiguity as the settlement-wide pools above, just
narrowed to a specific person rather than the village in the abstract.
Used only when `subject_name` is given; no neutral-temperament subject
pool since a person-centered omen already reads as more pointed than
the settlement-wide neutral filler."""


def fallback_omen(temperament: float, seed_hint: int, subject_name: str = "") -> dict:
    import random
    rng = random.Random(seed_hint)
    if subject_name and temperament > 0.15:
        return {"omen": rng.choice(_WARM_SUBJECT_OMENS).format(name=subject_name)}
    if subject_name and temperament < -0.15:
        return {"omen": rng.choice(_COLD_SUBJECT_OMENS).format(name=subject_name)}
    if temperament > 0.15:
        pool = _WARM_OMENS
    elif temperament < -0.15:
        pool = _COLD_OMENS
    else:
        pool = _NEUTRAL_OMENS
    return {"omen": rng.choice(pool)}


def parse_omen(result: dict, fallback: dict) -> str:
    omen = result.get("omen")
    if not isinstance(omen, str) or not omen.strip():
        omen = fallback["omen"]
    return omen.strip()[:200]
