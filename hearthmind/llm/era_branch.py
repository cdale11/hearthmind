"""One-time-per-era-advance job: picks which of a small, fixed set of
named "branches" (settlement/buildings.py's ERA_BRANCH_NAMES) best fits
this settlement's own recent history — v1 audit fix, "let emergence/
LLM steer its own course of era progression."

Made deterministic (explicit user directive): the branch itself is now
COMPUTED from the settlement's own real standing-building mix — the
same signal `ERA_BRANCH_KIND_WEIGHTS` already ties to each branch's
`choose_building_kind` boost, so "what a settlement has actually built"
directly decides "what it leans toward," not an LLM impression of it.
The LLM's only remaining job is to explain the computed lean in one
sentence, grounded in the actual counts — narration, not decision."""
from __future__ import annotations

from hearthmind.settlement.buildings import ERA_BRANCH_KIND_WEIGHTS, BuildingStage

SYSTEM_PROMPT = (
    "You are describing the emerging character of a small simulated village as it enters "
    "a new era of its history. You have been told which path it has ALREADY leaned toward, "
    "computed from what it has actually built — your job is only to explain why in one "
    "short sentence, grounded in the given facts, never to choose a different path. "
    'Respond with strict JSON only, no other text: {"reason": "one short sentence, under '
    '20 words, explaining why, citing an actual count or fact given to you"}.'
)


def compute_branch(settlement, rng) -> tuple[str, dict[str, float]]:
    """Deterministic: score each branch by the weighted count of its
    matching STANDING buildings (the same `ERA_BRANCH_KIND_WEIGHTS`
    `choose_building_kind` itself reads) — the settlement's own
    already-built character decides its lean, not a free-text guess.
    Ties (including the common all-zero case for a settlement that just
    entered its first branch-eligible era with nothing matching built
    yet) favor the settlement's current branch if it has one, then fall
    back to a namespaced random pick among the tied branches — a real
    choice, not an arbitrary fixed default, when there's genuinely no
    signal yet."""
    standing_kinds = [b.kind.value for b in settlement.buildings if b.stage is BuildingStage.STANDING]
    scores = {
        branch: sum(weights.get(kind, 0.0) for kind in standing_kinds)
        for branch, weights in ERA_BRANCH_KIND_WEIGHTS.items()
    }
    best_score = max(scores.values())
    tied = [b for b, s in scores.items() if s == best_score]
    if len(tied) == 1:
        return tied[0], scores
    if settlement.era_branch in tied:
        return settlement.era_branch, scores
    return rng.choice(tied), scores


def build_prompt(settlement_name: str, era: str, branch: str, scores: dict[str, float]) -> str:
    facts = ", ".join(f"{b}: {s:.1f}" for b, s in sorted(scores.items(), key=lambda kv: -kv[1]))
    return (
        f"The village of {settlement_name} has just entered the {era} era, and its own "
        f"building mix shows it leaning {branch} (scores by path — {facts}).\n"
        f"Explain in one sentence why {branch} fits."
    )


def fallback_reason() -> dict:
    """Genuine no-op — a computed branch needs no fabricated
    explanation to function mechanically (`choose_building_kind` reads
    `Settlement.era_branch` directly), so an unresolved LLM call simply
    means no reason sentence gets logged this time."""
    return {"reason": ""}


def parse_reason(result: dict, fallback: dict) -> str:
    reason = result.get("reason")
    if not isinstance(reason, str):
        reason = fallback["reason"]
    return reason.strip()[:160]
