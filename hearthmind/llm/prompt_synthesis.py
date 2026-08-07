"""FT.4 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap): "synthesize
prompts programmatically by perturbing archived structured inputs...
the prompt builders are pure functions, so generating 500 diverse
town_brain situations is a script, not a sim-year of waiting."

`llm/task_mix.py` is the "how much of each task" half of FT.4; this
module is the "where do the extra rare-task examples come from" half.
Scoped to `town_brain` — the audit's own named example, and the
clearest case of a real gap (1-6 archived examples for the hardest
structured tasks) meeting a prompt builder with an already fully
keyword-argument, side-effect-free signature (`town_brain.build_
prompt`). Deliberately NOT attempted for every task in one pass: each
`build_prompt` has its own structured-input shape and its own
plausible-range judgment calls (what counts as a realistic settlement
stat block is a domain question, not a mechanical one) — extend this
module task-by-task as a real archive shows which rare tasks actually
need it, per FT.4's own scoping.

Every generated prompt is synthetic INPUT only — no gold output is
attached here. FT.3's rejection-sampling path (`llm/rejection_
sampling.py`) or an offline teacher pass is what turns a synthesized
prompt into a trainable (prompt, completion) pair; this module's job
ends at "a diverse, plausible structured_input + the real prompt text
built from it."
"""
from __future__ import annotations

import random

from hearthmind.llm import town_brain

_VALID_PRIORITIES = town_brain._VALID_PRIORITIES  # noqa: SLF001 — reused, not duplicated

_SETTLEMENT_NAMES = (
    "Marshcroft", "Tidefell", "Hollowmere", "Ashwick", "Brookhaven",
    "Foxglen", "Stonewear", "Wrenhollow", "Millbrook", "Cinderford",
)
_NARRATIVE_THEMES = (
    "", "Grief, Renewal", "Striving, Cautious Hope", "Scarcity, Resolve",
    "Prosperity, Ambition", "Suspicion, Fracture",
)
_EVENT_TEMPLATES = (
    "A field was planted, using tools for a richer harvest.",
    "A structure was completed.",
    "{a} has recovered from illness.",
    "{a} caught the illness from {b}.",
    "{a} mastered farming and joined the farming guild.",
    "A new family began with {a} and {b}.",
    "{a} died of illness.",
    "A cart was finished.",
    "{a}: \"Another season turning, {b}.\" — {b}: \"The weaving keeps fraying.\"",
    "Nature reclaimed the ruins.",
)
_NAME_POOL = (
    "Aldric", "Branwen", "Corwin", "Dagny", "Edda", "Fenwick", "Gareth",
    "Hilde", "Isolde", "Jorah", "Katla", "Lennart", "Nissa", "Odette",
    "Petra", "Quenna", "Rosalind", "Soren", "Thea", "Ursula",
)


def _sample_recent_events(rng: random.Random, count: int) -> list[dict]:
    events = []
    for _ in range(count):
        template = rng.choice(_EVENT_TEMPLATES)
        a, b = rng.sample(_NAME_POOL, 2)
        events.append({"description": template.format(a=a, b=b)})
    return events


def synthesize_town_brain_situation(rng: random.Random) -> dict:
    """One randomized-but-plausible `town_brain.build_prompt` call's
    worth of structured input — every numeric range chosen to stay
    inside what a real settlement snapshot could plausibly show (see
    inline bounds), not uniform-random nonsense a model would learn to
    ignore. Returns `{"structured_input": {...}, "prompt": str}` — the
    structured_input dict mirrors the shape `SimulationEngine._schedule_
    town_brain`'s own `structured_input=` kwarg already records into the
    training archive (see `_schedule_llm_job` call site in engine.py),
    so a synthesized example and an organically-recorded one are
    interchangeable in a training set."""
    settlement_name = rng.choice(_SETTLEMENT_NAMES)
    population = rng.randint(20, 800)
    avg_hunger = round(rng.uniform(0.1, 0.9), 2)
    sick_count = rng.randint(0, max(1, population // 4))
    materials = round(rng.uniform(0.0, 30.0), 1)
    materials_capacity = float(rng.choice([20, 30, 40, 60]))
    currency = round(rng.uniform(0.0, 60.0), 1)
    currency_capacity = float(rng.choice([30, 50, 80]))
    education_level = round(rng.uniform(0.0, 1.0), 2)
    standing = rng.randint(1, max(1, population // 2))
    hospitals = rng.randint(0, standing // 10 + 1)
    schools = rng.randint(0, standing // 8 + 1)
    workshops = rng.randint(0, standing // 6 + 1)
    player_standing = round(rng.uniform(-1.0, 1.0), 2)
    narrative_theme = rng.choice(_NARRATIVE_THEMES)
    event_count = rng.randint(3, 30)
    priority = rng.choice(_VALID_PRIORITIES)
    """v1.34.277 fix: `town_brain.build_prompt`'s real signature is
    `(settlement_name, priority, recent_events, population_summary,
    settlement_summary, player_whispers, ...)` — `priority` is a
    required positional param this function never supplied at all,
    shifting every argument after `settlement_name` one slot out of
    place (a list of event dicts landing in `priority`, a population
    summary landing in `recent_events`, etc.) and raising a real
    `TypeError` (missing `settlement_summary`) on the very first call.
    `_VALID_PRIORITIES` was already imported for exactly this purpose
    (see its own module-level docstring: "reused, not duplicated") but
    never actually wired in — this function had genuinely never been
    exercised end to end before HearthBench A3.4 became its first real
    caller. v1.3.35's own note records `town_brain.compute_priority` as
    THE deterministic decision fed to `build_prompt` for narration —
    a synthesized situation needs the identical treatment, so `priority`
    is drawn from the real closed vocabulary rather than re-deriving
    the full `compute_priority` formula here (this module's own scope,
    per its docstring, is "plausible input," not re-implementing
    Body-side decision logic a second time)."""

    population_summary = {"total": population, "avg_hunger": avg_hunger, "sick_count": sick_count}
    settlement_summary = {
        "materials": materials, "materials_capacity": materials_capacity,
        "currency": currency, "currency_capacity": currency_capacity,
        "education_level": education_level, "standing": standing,
        "hospitals": hospitals, "schools": schools, "workshops": workshops,
        "player_standing": player_standing,
    }
    recent_events = _sample_recent_events(rng, event_count)

    prompt = town_brain.build_prompt(
        settlement_name, priority, recent_events, population_summary, settlement_summary,
        player_whispers=[], narrative_theme=narrative_theme,
    )
    return {
        "task": "town_brain",
        "structured_input": {
            "priority": priority,
            "population_summary": population_summary,
            "settlement_summary": settlement_summary,
            "narrative_theme": narrative_theme,
            "event_count": event_count,
        },
        "prompt": prompt,
        "system_prompt": town_brain.SYSTEM_PROMPT,
    }


def synthesize_town_brain_batch(count: int, seed: int | None = None) -> list[dict]:
    """`count` synthesized town_brain situations via a dedicated
    namespaced RNG (never the live simulation's own RNG — this runs
    fully offline, no `World`/`Config` needed). `seed=None` (the
    default) draws from OS entropy, matching this project's standing
    "determinism is not a requirement" rule; pass an explicit seed for
    a reproducible batch (e.g. to regenerate an eval-harness golden
    set, see `llm/eval_harness.py`)."""
    rng = random.Random(seed)
    return [synthesize_town_brain_situation(rng) for _ in range(count)]
