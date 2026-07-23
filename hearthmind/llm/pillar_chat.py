"""C3 "Player <-> Pillar chat" (docs/MASTERCHECKLIST-2026-07-22.md,
Part C, roadmap Stage III step 10): generalizes the existing Ask-the-
Chronicler pattern (`llm/chronicler.py`) from one settlement-scoped
narrative voice to any of the five cognitive pillars.

Same discipline as the chronicler: the pillar answers ONLY from its
own real, persistent `Pillar` state (`description`/`self_model`/
`objectives`/`world_model`/`memory`) — never raw Body/World stats, and
never fabricates certainty beyond what its own theories support. A
pillar's answer can be wrong, incomplete, or "I don't know" — that's
the whole point of asking a subjective mind rather than reading a
stat block. Unlike the chronicler (one fixed in-fiction role), each
pillar's voice comes from its own `self_model["voice"]` — Nature
"never speaks as a person," Reflection "proposes hypotheses, never
asserts certainty," and so on — so the same prompt shape produces five
genuinely different registers.

"Nudges enter cognition as weighable inputs, never commands" (the
checklist's own phrasing): a player's question and the pillar's answer
are recorded in `Pillar.conversation_log` and the exchange is folded
into that pillar's NEXT `interpret` turn as one more piece of context
(see `SimulationEngine._pillar_observe_turn`'s caller sites) — the
pillar may let a recent question color what it notices or forms an
opinion about, but the player is never able to directly set a belief,
override a decision, or otherwise command the pillar. "Pillars may
initiate contact" (the checklist's stretch goal) is explicitly NOT
attempted here — flagged as a real future step, not silently dropped."""
from __future__ import annotations

SYSTEM_PROMPT_TEMPLATE = (
    "You are {description} Someone from outside is asking you a question. "
    "{voice_hint} Answer using ONLY what you actually believe and know about "
    "yourself, given below — your own sense of what you are, what you want, "
    "and the real (sometimes uncertain, sometimes wrong) theories you "
    "currently hold. Never invent a fact you weren't given, never claim "
    "certainty your own theories don't support, and if you genuinely don't "
    "know or haven't formed an opinion, say so plainly rather than guessing. "
    "Keep the answer to 2-4 sentences. "
    'Respond with strict JSON only, no other text: {{"answer": "..."}}.'
)
"""One shared template, not five hand-written prompts — `description`/
`voice_hint` come from the pillar's own `description`/`self_model
["voice"]`, so the five pillars' answers stay genuinely distinct
without maintaining five near-duplicate SYSTEM_PROMPT strings."""


def build_system_prompt(pillar_description: str, voice_hint: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        description=pillar_description or "one part of a small simulated village's mind",
        voice_hint=(f"Speak the way you always do: {voice_hint}" if voice_hint else "Answer in your own voice."),
    )


def build_prompt(
    pillar_name: str, question: str, objectives: list[str], world_model: list[dict],
    memory: list[str], recent_conversation: list[dict] | None = None,
) -> str:
    """`world_model`/`memory` are given newest-last-few only (same
    "recency + what's actually relevant" budget every other prompt in
    this codebase uses) — a pillar answering a question isn't meant to
    dump its entire theory list, just speak from what it currently
    holds most in mind. `recent_conversation` (optional): the last
    couple of exchanges with this SAME pillar, so a follow-up question
    reads as a continuing conversation, not amnesia between asks."""
    objectives_text = "; ".join(objectives) if objectives else "(no fixed objectives beyond attending to your domain)"
    if world_model:
        beliefs_text = "\n".join(
            f"  [{e['status']}, confidence {e['confidence']:.2f}] {e['subject']}: {e['belief']}"
            for e in world_model[-6:]
        )
    else:
        beliefs_text = "  (you hold no real theories yet)"
    memory_text = " | ".join(memory[-4:]) if memory else "(nothing notable comes to mind)"
    conversation_text = ""
    if recent_conversation:
        lines = [f"  Q: {c['question']}\n  A: {c['answer']}" for c in recent_conversation[-2:]]
        conversation_text = "Earlier in this same conversation:\n" + "\n".join(lines) + "\n"
    return (
        f"What you want: {objectives_text}\n"
        f"What you currently believe:\n{beliefs_text}\n"
        f"What's on your mind lately: {memory_text}\n"
        f"{conversation_text}"
        f"A visitor asks you: \"{question}\"\n"
        "Answer from what you actually believe."
    )


def fallback_answer(pillar_name: str) -> dict:
    """Deterministic stand-in: an honest in-character non-answer, same
    "no LLM means no fabricated certainty" discipline as `llm/
    chronicler.py`'s own fallback — a pillar that genuinely has nothing
    to say right now is itself an in-fiction-consistent answer, not a
    degraded experience to apologize for."""
    return {
        "answer": (
            f"{pillar_name.capitalize()} holds no clear answer to that right now — "
            "some things take longer to come to mind than others."
        )
    }


def parse_answer(result: dict, fallback: dict) -> str:
    text = result.get("answer")
    if not isinstance(text, str) or not text.strip():
        return fallback["answer"]
    return text.strip()[:600]
