"""Dream() (Phase K, docs/VISION-2026-07.md, "Knowledge & Story"):
monthly, symbolic, never predictive — reads an agent's current emotional
state and writes one dream memory. Scoped down from the vision doc's
fuller version (reads emotions/preoccupation/folklore, writes a memory
PLUS a tiny belief/trust nudge, all core-cast agents monthly): this
slice keeps the schema to one field (matching this project's standing
"fewer fields per call = fewer ways for a small model to get it wrong"
discipline) and rotates through the core cast round-robin, one agent a
month — same shape as `_maybe_schedule_personal_belief`'s own
significance-first pick, not all ~14 agents dreaming every month. See
`SimulationEngine._maybe_schedule_dream` for the volume reasoning.

Ambiguity discipline (CLAUDE.md, Phase G/omens' standing rule) applies
here too: a dream is symbolic and interpretive, never a coded prophecy
— nothing here or in the fallback ever confirms a dream "came true."
"""
from __future__ import annotations

from hearthmind.agents.agent import describe_emotion

SYSTEM_PROMPT = (
    "You are describing a dream one villager in a small simulated world had "
    "last night — symbolic, not literal, shaped by what's been weighing on "
    "them lately. It should read like a real dream: strange, a little "
    "disjointed, open to interpretation, never a clear message or a "
    "prediction of what will happen. "
    'Respond with strict JSON only, no other text: {"dream": "one or two '
    'sentences, under 30 words, described as something dreamed, third '
    'person or first person"}.'
)


def build_prompt(agent_name: str, emotions: dict, preoccupation: str, latest_folklore: str = "") -> str:
    emotion_text = describe_emotion(emotions)
    feeling_line = f" Lately they've been feeling {emotion_text}." if emotion_text else ""
    preoccupation_line = f" On their mind: {preoccupation}." if preoccupation else ""
    folklore_line = f" A tale they've heard: {latest_folklore}." if latest_folklore else ""
    return (
        f"{agent_name} fell asleep last night.{feeling_line}{preoccupation_line}{folklore_line} "
        "Describe the dream they had."
    )


def fallback_dream(agent_name: str, emotions: dict) -> dict:
    """Deterministic stand-in: a plain, genuinely ambiguous dream image,
    varied by whichever emotion (if any) is currently dominant — no
    fallback pool tries to be clever, since inventing vivid symbolism
    without a model is exactly the kind of "ungrounded" content this
    project avoids elsewhere (see llm/folklore.py's honesty discipline)."""
    fear = emotions.get("fear", 0.0)
    grief = emotions.get("grief", 0.0)
    joy = emotions.get("joy", 0.0)
    if fear >= 0.35 and fear >= max(grief, joy):
        dream = f"{agent_name} dreamed of a door that wouldn't stay shut."
    elif grief >= 0.35 and grief >= joy:
        dream = f"{agent_name} dreamed of an empty chair at a familiar table."
    elif joy >= 0.35:
        dream = f"{agent_name} dreamed of a field in full bloom, though it isn't the season for it."
    else:
        dream = f"{agent_name} dreamed of walking a road that kept resetting behind them."
    return {"dream": dream}


def parse_dream(result: dict, fallback: dict) -> str:
    text = result.get("dream")
    if not isinstance(text, str) or not text.strip():
        text = fallback["dream"]
    return text.strip()[:200]
