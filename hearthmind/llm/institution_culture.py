"""Quarterly LLM job: condenses ONE institution's own accumulated
beliefs/objective/feud history into a short, independently-authored
digest sentence — §9's "institutions get their own persistent memory"
+ "multi-layer culture" (docs/IDEAS-2026-07-EMERGENCE.md). Distinct
from `Institution.beliefs` (a filtered MIRROR of settlement-wide
beliefs, see that field's docstring) and from `llm/culture_digest.py`
(the whole settlement's shape): this is the one place an institution's
own character is actually authored on its own terms, not derived from
the settlement it sits inside. Round-robin over every institution in
the world (`SimulationEngine._institution_job_target`), same "flat
call volume regardless of count" shape `_job_target` already gives
settlement-scoped jobs.
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are the accumulated character of one institution inside a small simulated "
    "village — a family, a council, a guild, or a faction. Given what it believes, what "
    "it wants, and its history of rivalries, condense its own distinct character into one "
    "short sentence — not a list, a gist, the way you'd describe this specific household "
    "or body's reputation to someone who'd never met them. "
    'Respond with strict JSON only, no other text: {"digest": "one sentence, under 22 '
    'words"}.'
)


def build_prompt(
    kind: str, name: str, settlement_name: str, beliefs: list[dict], objective: str,
    feud_count: int,
) -> str:
    label = name or f"the {kind}"
    label = label[:1].upper() + label[1:] if label else label
    beliefs_text = (
        "; ".join(b.get("belief", "") for b in beliefs if b.get("belief")) if beliefs else "None yet."
    )
    objective_text = objective or "None stated yet."
    feud_text = (
        f"{feud_count} standing generational feud(s)." if feud_count else "No standing feuds."
    )
    return (
        f"{label}, a {kind} in the village of {settlement_name}.\n"
        f"What it believes: {beliefs_text}\n"
        f"What it wants: {objective_text}\n"
        f"Its rivalries: {feud_text}\n"
        "Condense this into one sentence capturing this institution's own distinct character."
    )


def fallback_digest() -> dict:
    """Genuine no-op — "no call -> no update this quarter," same
    discipline as `llm.culture_digest.fallback_digest`. The engine only
    overwrites `Institution.culture_digest` on a real (non-fallback)
    answer."""
    return {"digest": ""}


def parse_digest(result: dict) -> str:
    text = result.get("digest")
    if not isinstance(text, str) or not text.strip():
        return ""
    return text.strip()[:160]
