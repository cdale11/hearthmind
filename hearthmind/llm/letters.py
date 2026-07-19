"""Letters carried between settlements (§2, docs/IDEAS-2026-07-
EMERGENCE.md, "Between settlements"): core-cast agents with a real
cross-settlement bond occasionally write a letter — one small LLM call,
grounded in what the sender actually knows/feels — that travels at
caravan speed (a real multi-day delay, `LETTER_TRAVEL_TICKS`) and is
delivered as a memory (and, occasionally, a rumor) to the recipient.
Latency is the feature: a letter queued before its sender or recipient
dies can still arrive afterward — `SimulationEngine`'s delivery check
handles that case directly rather than silently dropping it. Rides the
existing monthly-job/records-adjacent machinery; no new map entity or
pathfinding.
"""
from __future__ import annotations

from hearthmind.agents.agent import Agent, describe_traits

LETTER_TRAVEL_TICKS = 400
"""How long a letter takes to arrive — a real multi-day delay (at
default pacing, several sim-days), deliberately slow enough that a lot
can change at either end before it's read; see module docstring."""

LETTER_RUMOR_CHANCE = 0.3
"""Chance a delivered letter's news also seeds a rumor for the
recipient's own settlement (via the existing `spread_rumor` machinery)
— most letters stay a private, personal thing between the two people."""

SYSTEM_PROMPT = (
    "You are one villager writing a short letter to someone you care about "
    "who now lives in another settlement. Ground it in what you actually "
    "know and feel right now — a real thing happening in your life, not "
    "generic pleasantries. Keep it brief and personal, like a real letter "
    "someone might actually write, not a report. "
    'Respond with strict JSON only, no other text: {"text": "the letter '
    'itself, one to three short sentences, first-person"}.'
)


def build_prompt(sender: Agent, recipient_name: str, sender_settlement: str, recipient_settlement: str) -> str:
    personality = describe_traits(sender.traits)
    personality_text = f" You are {personality}." if personality else ""
    recent = sender.memories[-2:]
    memory_text = f" On your mind lately: {' | '.join(recent)}." if recent else ""
    return (
        f"You are {sender.name}, living in {sender_settlement}.{personality_text} "
        f"You are writing to {recipient_name}, who now lives in {recipient_settlement}.{memory_text} "
        "What do you write?"
    )


def fallback_letter(sender: Agent, recipient_name: str) -> dict:
    """Deterministic stand-in: a plain, genuine-reading line grounded in
    the sender's own name — never fabricated content about events that
    didn't happen, just an honest "thinking of you.\""""
    return {"text": f"{sender.name} writes: I think of you often, {recipient_name}. I hope you are well."}


def parse_letter(result: dict, fallback: dict) -> str:
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        text = fallback["text"]
    return text.strip()[:280]
