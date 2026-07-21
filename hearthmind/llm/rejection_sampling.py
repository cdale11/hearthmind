"""FT.3 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap): the
no-teacher-needed half — "for each prompt, sample k=4-8 completions
from the *current* model at temperature, score with FT.2's labels,
keep the best... it also yields (chosen, rejected) pairs — bank those
for a later DPO pass."

Deliberately scoped to this half only. FT.3's OTHER half (teacher
distillation through a much larger model) needs an actual larger model
this environment has no access to — there is no local "teacher" beyond
the same server this project already talks to, and standing this up is
an infrastructure decision for whoever runs the real training pipeline,
not something to fake here. Rejection sampling needs nothing beyond
the client this project already has: it's real gold-target generation,
fully local, using `llm/quality_labels.py` (FT.2) as the judge instead
of a second model.

This module makes k *live* LLM calls per prompt — unlike every other
`llm/*.py` module (which only builds prompts / parses results), it is
not something the tick loop ever calls; it's an offline tool
(`scripts/rejection_sample.py` is the CLI wrapper) that a human runs
against a real llama-server, same "no test suite, ad-hoc verified
scripts instead" posture as `scripts/verify_native_soak.py`.
"""
from __future__ import annotations

import dataclasses
import time

from hearthmind.llm.json_schemas import schema_for_task
from hearthmind.llm.quality_labels import label_example

DEFAULT_K = 4
"""FT.3's own stated range is 4-8; 4 is the cheap end — each sample is
a real LLM call, so this is a genuine wall-clock/compute cost per
prompt, not a free parameter to crank up by default."""

DEFAULT_TEMPERATURE_SPREAD = (0.5, 0.7, 0.9, 1.1)
"""A temperature per sample rather than one repeated value — sampling
identically k times from a low-temperature model mostly just re-rolls
the same answer, defeating the point of exploring the output space for
a genuinely better (or a genuinely worse, for the DPO "rejected" side)
completion. Spans from noticeably more conservative than this
project's live default (`Config.llm_temperature=0.7`) to noticeably
more exploratory, so both extremes of drift are represented among the
rejected candidates too."""


def _score(task: str, structured_input: dict | None, output: dict, used_fallback: bool) -> dict:
    """Wraps `quality_labels.label_example` (which expects one on-disk
    archive record's shape) around a single live candidate — reuses the
    exact same judge FT.2 built for post-hoc archive curation, so a
    rejection-sampled example and an organically-recorded one are
    scored by identical rules."""
    fake_record = {
        "task": task,
        "layer1_structured_input": structured_input or {},
        "layer4_parsed_output": output,
        "fallback_used": used_fallback,
    }
    return label_example(fake_record)


def _rank_key(labels: dict) -> tuple:
    """Higher is better. `sft_eligible` dominates (a structurally-sound,
    leak-free, on-topic completion always beats one that isn't,
    regardless of finer-grained scores); `context_reflected`/`dialogue_
    responds` break ties among otherwise-eligible candidates toward the
    one that actually used what it was given; fewer leak flags is a
    last tiebreak among ineligible candidates (so "rejected" still has
    a real best-to-worst order for anyone inspecting the bank, not an
    arbitrary one)."""
    return (
        bool(labels.get("sft_eligible")),
        bool(labels.get("context_reflected")),
        bool(labels.get("dialogue_responds", True)),
        -len(labels.get("leak_flags") or []),
    )


def sample_and_select(
    client, prompt: str, system: str | None, task: str,
    structured_input: dict | None = None, k: int = DEFAULT_K,
    temperatures: tuple[float, ...] = DEFAULT_TEMPERATURE_SPREAD,
) -> dict:
    """Blocking — makes up to `k` real LLM calls (one per temperature in
    `temperatures`, cycling if `k` exceeds its length). Returns:
    `{"chosen": {...}, "rejected": [...], "candidates": [...], "k_attempted": int,
    "k_succeeded": int}` where each candidate/chosen/rejected entry is
    `{"output": dict, "raw": str | None, "temperature": float, "labels": dict}`.
    A candidate whose call fails (any exception — network, timeout,
    unparseable JSON) is simply skipped, never raises; `chosen` is
    `None` if every candidate failed, so a caller can tell "no gold
    target produced this round" from "produced one." This is offline
    tooling, not tick-loop code, so it deliberately does NOT use
    `CognitionRunner`'s async/backpressure machinery — one prompt at a
    time, synchronous, exactly as many calls as `k` asks for."""
    json_schema = schema_for_task(task)
    candidates: list[dict] = []
    for i in range(k):
        temperature = temperatures[i % len(temperatures)]
        sample_client = dataclasses.replace(client, temperature=temperature)
        capture: dict = {}
        try:
            result = sample_client.generate_json(prompt, system, capture, json_schema)
        except Exception:
            continue
        labels = _score(task, structured_input, result, used_fallback=False)
        candidates.append({
            "output": result, "raw": capture.get("raw"),
            "temperature": temperature, "labels": labels,
        })

    if not candidates:
        return {"chosen": None, "rejected": [], "candidates": [], "k_attempted": k, "k_succeeded": 0}

    ranked = sorted(candidates, key=lambda c: _rank_key(c["labels"]), reverse=True)
    return {
        "chosen": ranked[0],
        "rejected": ranked[1:],
        "candidates": candidates,
        "k_attempted": k,
        "k_succeeded": len(candidates),
    }


def bank_preference_pair(prompt_record: dict, sample_result: dict) -> dict | None:
    """Builds one (chosen, rejected) DPO-bankable record from a `sample_
    and_select` result, or `None` if there's nothing to bank (no chosen
    candidate, or every candidate identical to the chosen one — no real
    preference signal). `prompt_record` is whatever the caller already
    has identifying the prompt (`{"task", "prompt", "system_prompt",
    "structured_input", ...}`, matching the shape `llm/prompt_
    synthesis.py`/an archive example already produces) — kept separate
    from `sample_result` so a caller can build several banked pairs
    from one synthesized prompt without re-deriving it each time."""
    chosen = sample_result.get("chosen")
    if chosen is None:
        return None
    rejected = [r for r in sample_result.get("rejected", []) if r["output"] != chosen["output"]]
    if not rejected:
        return None
    return {
        "timestamp": time.time(),
        "task": prompt_record.get("task"),
        "prompt": prompt_record.get("prompt"),
        "system_prompt": prompt_record.get("system_prompt"),
        "structured_input": prompt_record.get("structured_input"),
        "chosen": chosen["output"],
        "chosen_labels": chosen["labels"],
        "rejected": [r["output"] for r in rejected],
        "rejected_labels": [r["labels"] for r in rejected],
    }
