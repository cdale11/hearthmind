"""Tier 6 L1.1's real corpus-building pass (docs/ROADMAP-2026-07-REMAINING.
md, Phase 1) -- the piece every prior L1.1/L2.3/HCA F1 filing flagged as
still open: "needs a real corpus-building pass from World/Agent text."

Deliberately reuses only text that is ALREADY real, persisted state --
no new tracked field, no LLM call of its own. Unlike Tier 6's other
still-blocked items (a trained goal policy, an LLM cost regressor), this
one needs no live-deployment archive at all: `World.emergence_log`
summaries and `Agent.memories`/`semantic_memories` are populated by the
deterministic fallback path too, so a corpus can be built from ANY
world -- online or offline, LLM-enabled or not, including a fresh one
this dev environment can create and tick locally. That is the concrete
answer to "why did L1.1 stay blocked so long": it never needed a live
LLM archive, only someone to write this extraction pass.

Corpus-agnostic on the OTHER side too, matching `embedding.py`'s own
design: this module hands `train_skipgram` a plain `list[str]`, never
reaches into `hearthmind.ml/` itself.
"""
from __future__ import annotations

MIN_TEXT_LEN = 8


def _is_real_sentence(text) -> bool:
    """A guard against the many short/templated/near-empty strings this
    codebase's own state carries (single-word tags, `""` placeholders,
    a bare name) -- these would only pollute the skip-gram vocabulary
    with noise, not teach it anything about meaning."""
    return isinstance(text, str) and len(text.strip()) >= MIN_TEXT_LEN


def collect_world_corpus(world) -> list[str]:
    """Extracts every real sentence-shaped string already living in a
    `World`'s own persisted state -- emergence-log summaries (A2's own
    surprise-gated log, real regardless of LLM enablement), every
    agent's `memories`/`semantic_memories`, every settlement's
    `beliefs`/`folklore`/`legends`/`records`, and each of the five
    cognitive pillars' `world_model` belief text. Deduplicated
    (`dict.fromkeys` preserves first-seen order) since several of these
    stores legitimately share near-identical sentences (a mirrored
    pillar belief and its settlement-level source, for instance) and
    training on the same sentence twice teaches the embedding nothing
    a single copy didn't already."""
    sentences: list[str] = []

    for entry in world.emergence_log:
        summary = entry.get("summary") if isinstance(entry, dict) else None
        if _is_real_sentence(summary):
            sentences.append(summary)

    for agent in world.population.agents:
        for text in agent.memories:
            if _is_real_sentence(text):
                sentences.append(text)
        for text in agent.semantic_memories:
            if _is_real_sentence(text):
                sentences.append(text)

    for settlement in world.settlements:
        for belief in settlement.beliefs:
            text = belief.get("belief") if isinstance(belief, dict) else None
            if _is_real_sentence(text):
                sentences.append(text)
        for text in getattr(settlement, "folklore", []) or []:
            if _is_real_sentence(text):
                sentences.append(text)
        for text in getattr(settlement, "legends", []) or []:
            if _is_real_sentence(text):
                sentences.append(text)
        for record in getattr(settlement, "records", []) or []:
            text = record.get("text") if isinstance(record, dict) else record
            if _is_real_sentence(text):
                sentences.append(text)

    for pillar_name in ("village_pillar", "humans_pillar", "innovation_pillar", "nature_pillar", "reflection_pillar"):
        pillar = getattr(world, pillar_name, None)
        if pillar is None:
            continue
        for entry in getattr(pillar, "world_model", []) or []:
            text = entry.get("belief") if isinstance(entry, dict) else None
            if _is_real_sentence(text):
                sentences.append(text)

    return list(dict.fromkeys(sentences))
