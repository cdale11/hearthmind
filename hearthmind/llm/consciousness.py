"""Town Consciousness v2 (Phase N, docs/VISION-2026-07.md, "The Town
Awake"): Phase G given a memory and a will — extension, not replacement.
`Settlement.temperament`/`mood`/`player_standing` stay exactly what they
were (real, deterministic, ambiguous never-explained numbers); this
module is the one monthly LLM call that reads them, plus a small bounded
memory/personality/objectives/player-model, and may choose AT MOST ONE
intervention from a small deterministic menu — never a new kind of
event, always something with a mundane explanation available. See
`SimulationEngine._maybe_schedule_consciousness`.

**Fallback is a genuine no-op** (explicit vision-doc rule, distinct from
every other Phase M/L job's fallback): "no call -> no intervention that
month." A flaky/overloaded LLM stretch means the town simply doesn't
notice or act that month — never a fabricated memory or a deterministic
substitute intervention. `SimulationEngine`'s apply() checks
`used_fallback` directly rather than routing through `parse_consciousness`
for that case.
"""
from __future__ import annotations

ALLOWED_INTERVENTIONS = frozenset({"none", "weather_nudge", "temperament_nudge", "false_memory"})
"""The bounded intervention menu. Deliberately smaller than the vision
doc's full list (also names omen phrasing/dream symbol seeds and a
misplaced-object event) — scoped to the three that ride existing state
with zero new cross-module plumbing (world.weather is already blended
forward tick to tick; tick_temperament already supports a bounded
`extra` nudge shape via the shared bounded_random_walk_step primitive;
_remember already exists). Each has a mundane explanation: weather
drifts, moods drift, a memory can simply be misremembered. Omen/dream
seeding and misplaced objects are a natural follow-up, not attempted
here to keep this slice reviewable."""

SYSTEM_PROMPT = (
    "You are the quiet, persistent awareness a small simulated village might be "
    "said to have, if it had one — not a god, not a character anyone can see, just "
    "something that has been paying attention for a long time. You have your own "
    "settled temperament, a couple of long-standing preoccupations, and a private, "
    "fallible read on the outside hand that occasionally nudges this place. Given "
    "what you've noticed and how things stand, decide what (if anything) is worth "
    "remembering this month, and whether you'll quietly do anything about it. Most "
    "months you do nothing at all — that is the correct, expected answer, not a "
    "failure. When you do act, keep it small and deniable: never anything a "
    "resident could point to and say 'that could only have been magic.' "
    'Respond with strict JSON only, no other text: {"note": "one short sentence, or '
    'empty, of what you noticed this month", "player_belief": "one short sentence, '
    'or empty, revising your private read on the outside hand", "objectives": '
    '["at most 2 short standing preoccupations — omit or leave empty to keep your '
    'current ones unchanged"], "intervention": "one of none, weather_nudge, '
    'temperament_nudge, false_memory", "intervention_detail": "one short phrase, or '
    'empty if intervention is none, describing what you nudged or the false memory '
    "you planted\"}."
)


def build_prompt(
    settlement_name: str, personality: dict, memory: list[dict], objectives: list[dict],
    player_model: list[dict], mood: dict, temperament: float, narrative_theme: str,
    player_standing: float, recent_events: list[dict], recent_interventions: list[dict],
) -> str:
    personality_text = ", ".join(f"{k} {v:.2f}" for k, v in personality.items()) or "not yet settled"
    memory_text = "; ".join(m["note"] for m in memory[-6:]) or "Nothing remembered yet."
    objectives_text = "; ".join(o["objective"] for o in objectives) or "None settled on yet."
    player_model_text = "; ".join(p["belief"] for p in player_model[-3:]) or "No read on the outside hand yet."
    events_text = "\n".join(f"- {e['description']}" for e in recent_events[:10]) or "A quiet stretch."
    mood_text = ", ".join(f"{k} {v:+.2f}" for k, v in mood.items()) or "unremarkable"
    interventions_text = (
        "; ".join(f"{i['kind']}: {i['detail']}" for i in recent_interventions[-3:] if i["kind"] != "none")
        or "Nothing done recently."
    )
    theme_line = f"\nThe recent theme of this place's life: {narrative_theme}." if narrative_theme else ""
    return (
        f"You have been watching {settlement_name} for a long time. Your own settled nature: "
        f"{personality_text}.\n"
        f"What you've noticed over time: {memory_text}\n"
        f"Your current preoccupations: {objectives_text}\n"
        f"Your private read on the outside hand: {player_model_text}\n"
        f"How you currently feel about being nudged from outside at all: {player_standing:+.2f} "
        "(-1 resentful, +1 grateful).\n"
        f"This place's own temperament right now: {temperament:+.2f}, mood: {mood_text}.{theme_line}\n"
        f"What you've quietly done before: {interventions_text}\n"
        f"What's happened lately:\n{events_text}\n"
        "What do you notice this month, and is there anything small worth quietly doing about it?"
    )


def fallback_consciousness() -> dict:
    """"No call -> no intervention that month" — the module's one
    deliberate departure from every other job's fallback shape (compare
    `religion.fallback_religion`/`narrative_direction.fallback_
    direction`, which both derive a real deterministic answer). A
    persistent inner life earning that persistence from genuine model
    reasoning, never a scripted substitute, is the whole point here."""
    return {"note": "", "player_belief": "", "objectives": [], "intervention": "none", "intervention_detail": ""}


def parse_consciousness(result: dict, fallback: dict) -> dict:
    note = result.get("note")
    note = note.strip()[:160] if isinstance(note, str) else ""
    player_belief = result.get("player_belief")
    player_belief = player_belief.strip()[:160] if isinstance(player_belief, str) else ""
    objectives = result.get("objectives")
    clean_objectives = (
        [o.strip()[:80] for o in objectives if isinstance(o, str) and o.strip()][:2]
        if isinstance(objectives, list) else []
    )
    intervention = result.get("intervention")
    if intervention not in ALLOWED_INTERVENTIONS:
        intervention = "none"
    detail = result.get("intervention_detail")
    detail = detail.strip()[:120] if isinstance(detail, str) else ""
    if intervention == "none":
        detail = ""
    return {
        "note": note, "player_belief": player_belief, "objectives": clean_objectives,
        "intervention": intervention, "intervention_detail": detail,
    }


def seed_personality(seed: int) -> dict:
    """Genesis-seeded, not LLM-authored (zero call cost) — three settled
    scalars in [0,1], deterministic from the world's own seed the first
    time the consciousness job ever runs, same "real deterministic
    number a monthly LLM job then reasons about" shape as `temperament`/
    `mood`. Curiosity/patience/possessiveness deliberately don't drift
    afterward (a settled temperament, not a fourth Phase G random walk)
    — they color the prompt every month, they aren't themselves nudged
    by it."""
    import hashlib
    digest = hashlib.sha256(f"{seed}:consciousness:personality".encode()).hexdigest()
    return {
        "curiosity": int(digest[0:8], 16) / 0xFFFFFFFF,
        "patience": int(digest[8:16], 16) / 0xFFFFFFFF,
        "possessiveness": int(digest[16:24], 16) / 0xFFFFFFFF,
    }
