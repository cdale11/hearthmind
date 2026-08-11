"""HearthBench A11.1/A11.2/A11.3/A11.5 — run modes for the real runner.

The shared execution slice (`run_cases_with_resume`) is A11.4 and
already exists; this module is the mode layer *on top of it*, the
"quick/full/custom/resume/strict-repro" abstraction the earlier A11
filings flagged as unbuilt. What each mode means here:

- **Quick (A11.1)**: a stratified subsample of each category's own
  ordered case list, deterministic scorers only (never a judge model —
  no adapter is even consulted for scoring), giving a cheap
  regression check. Stratification = evenly spaced draws across the
  case list, which is deterministic (a pure function of the list) and
  keeps spread rather than taking a contiguous prefix.
- **Full (A11.2)**: the complete fixture set per category with the
  full per-category registry (Tier 1 + the category's own Tier 2
  judge scorer when it has one), and `--samples N` repeated sampling
  for variance — each repetition lands in its own `sample-<i>`
  subdirectory, so resume stays per-repetition honest.
- **Custom (A11.3)**: a caller-named subset of categories.
- **Strict repro (A11.5)**: fixed seeds + recorded sampler settings,
  and a fail-fast gate: if strict-repro is requested but the adapter
  reports `capabilities().seed` falsy, we refuse to start before any
  case runs — never a silently unseeded run. The seed itself is
  threaded by the *caller* at adapter construction time
  (`seed_override`), because that is the explicit single send site;
  this module records it in every run manifest and gates on it.

Honest gaps, stated rather than engineered around: `structured_
outputs` needs a real fixture pack and `performance` needs an
existing category's cases to attach latency scorers to (the same
reason `cli._cases_for_category` raises for them). Neither has a
standalone case builder here, so both are **skipped** by every mode
with a note in the returned report — never a fabricated empty run.

Import isolation (A1.2): stdlib + `hearthbench.*` only.
"""
from __future__ import annotations

import os
from pathlib import Path

from hearthbench.diagnostics import build_environment_snapshot
from hearthbench.runner.run import run_cases_with_resume
from hearthbench.scoring import DEFAULT_REGISTRY, ScorerRegistry
from hearthbench.tests import (
    CATEGORY_REGISTRY,
    build_beliefs_cases,
    build_dialogue_cases,
    build_grounding_bait_cases,
    build_judge_scorer_for,
    build_memory_cases,
    build_personality_cases,
    build_planning_cases,
    build_village_cognition_cases,
)

MODE_QUICK = "quick"
MODE_FULL = "full"
MODE_CUSTOM = "custom"
RUN_MODES = (MODE_QUICK, MODE_FULL, MODE_CUSTOM)

DEFAULT_QUICK_SAMPLE_SIZE = 4
"""A11.1's default stratified subsample size per quick-mode category."""

DEFAULT_STRICT_SEED = 0
"""A11.5's fixed seed when strict-repro is requested without `--seed`."""

# The six subjective categories with a real A4.2 judge-scorer factory
# (`build_*_judge_scorer(adapter)` in hearthbench.tests) to wire into
# Full-mode registries. Grounding/structured_outputs/performance are
# Tier-1-only by design; the judge wiring decision for them is
# deliberately no-op, not an omission.
JUDGE_CATEGORY_IDS = frozenset(
    {"dialogue", "personality", "memory", "beliefs", "planning", "village_cognition"}
)

# Categories that ship real standalone case builders. structured_
# outputs and performance are deliberately absent (see module
# docstring) — `cases_for_category` returns `[]` for them and every
# mode skips them with a reported note.
CATEGORY_CASE_BUILDERS = {
    "dialogue": build_dialogue_cases,
    "personality": build_personality_cases,
    "memory": build_memory_cases,
    "beliefs": build_beliefs_cases,
    "planning": build_planning_cases,
    "village_cognition": build_village_cognition_cases,
    "grounding": build_grounding_bait_cases,
}


def tier1_category_ids() -> list:
    """The categories whose every declared `scorer_ids` id resolves in
    `DEFAULT_REGISTRY` — i.e. quick mode's selection, computed live
    rather than a second hardcoded table that could drift from the
    real registrations (the same discipline `Category.weight` holds
    vs. A10's composite table)."""
    return [
        category.id
        for category in CATEGORY_REGISTRY.values()
        if all(sid in DEFAULT_REGISTRY for sid in category.scorer_ids)
    ]


def judge_category_ids() -> list:
    return [category.id for category in CATEGORY_REGISTRY.values() if category.id in JUDGE_CATEGORY_IDS]


def cases_for_category(category_id: str) -> list:
    """The category's real `TestCase`s, or `[]` when no standalone
    case builder exists (see module docstring)."""
    builder = CATEGORY_CASE_BUILDERS.get(category_id)
    if builder is None:
        return []
    return list(builder())


def quick_cases(cases: list, sample_size: int) -> list:
    """A11.1's stratified subsample: divide the ordered case list into
    `sample_size` strata and take the first element of each. A pure
    function of the list (deterministic across runs), keeps spread
    across the whole case list rather than a contiguous prefix, and
    caps at the full list — a list shorter than `sample_size` is
    returned whole, never padded or duplicated."""
    n = len(cases)
    if n == 0:
        return []
    k = min(sample_size, n)
    if k == n:
        return list(cases)
    return [cases[(i * n) // k] for i in range(k)]


def registry_for_category(category_id: str, adapter) -> ScorerRegistry:
    """The per-run registry for one category: every Tier 1 scorer from
    `DEFAULT_REGISTRY`, plus (for the six judge categories) the
    category's own Tier 2 judge scorer — constructed from the live
    adapter at this run's call site, per A4.2's never-auto-registered
    Tier 2 discipline. Its scorer id follows each category module's
    documented convention (`judge_dialogue_quality`, ...), which is
    what the category's `TestCase.scorers` resolve against."""
    registry = ScorerRegistry()
    for scorer in DEFAULT_REGISTRY.all():
        registry.register(scorer)
    if category_id in JUDGE_CATEGORY_IDS:
        judge = build_judge_scorer_for(category_id, adapter)
        registry.register(
            judge.as_scorer(
                scorer_id=f"judge_{category_id}_quality",
                category=category_id,
            )
        )
    return registry


def build_run_environment(
    adapter,
    category_id: str,
    case_ids: list,
    *,
    mode: str,
    seed,
    strict_repro: bool,
    samples: int,
    sample_index: int,
    quick_sample_size,
    run_dir: str,
) -> dict:
    """A8 environment snapshot carrying the mode's sampler settings —
    A11.5's "recorded sampler settings" half — alongside the A12
    contract's `category`/`expected_case_ids` keys every daemon-
    browsed run expects."""
    extra = {
        "category": category_id,
        "expected_case_ids": list(case_ids),
        "mode": mode,
        "strict_repro": strict_repro,
        "seed": seed,
        "samples": samples,
        "sample_index": sample_index,
        "sample_count": samples,
    }
    if quick_sample_size is not None:
        extra["quick_sample_size"] = quick_sample_size
    return build_environment_snapshot(
        adapter=adapter,
        run_id=os.path.basename(os.path.normpath(run_dir)),
        extra=extra,
    )


def _supports_seed(adapter) -> bool:
    """Duck-typed read of the adapter's seeding capability — handles
    both an attribute-style capabilities object and a dict."""
    caps = adapter.capabilities()
    value = getattr(caps, "seed", None) if not isinstance(caps, dict) else caps.get("seed")
    return bool(value)


def planned_category_ids(mode: str, category_id=None, categories=None) -> list:
    """Resolve `mode`'s intro option into an explicit, validated list
    of category ids. Quick starts from the live Tier 1 resolution,
    Full from the full registry order, Custom from the caller's own
    list — each optionally narrowed to one `category_id`."""
    if mode == MODE_QUICK:
        if category_id is not None:
            _validate_category_id(category_id)
            return [category_id]
        return tier1_category_ids()
    if mode == MODE_FULL:
        if category_id is not None:
            _validate_category_id(category_id)
            return [category_id]
        return [category.id for category in CATEGORY_REGISTRY.values()]
    if categories and category_id:
        raise ValueError(
            f"custom mode ({MODE_CUSTOM!r}) takes --categories or a single --category, not both"
        )
    chosen = list(categories or [])
    if category_id is not None:
        chosen = [category_id] + chosen
    if not chosen:
        raise ValueError(
            f"custom mode ({MODE_CUSTOM!r}) requires at least one category"
        )
    for category_id in chosen:
        _validate_category_id(category_id)
    return list(dict.fromkeys(chosen))


def _validate_category_id(category_id: str) -> None:
    if category_id not in CATEGORY_REGISTRY:
        raise ValueError(
            f"unsupported category {category_id!r} — known: {sorted(CATEGORY_REGISTRY)}"
        )


def run_mode(
    *,
    mode: str,
    adapter,
    run_dir,
    seed=None,
    strict_repro: bool = False,
    samples: int = 1,
    category_id=None,
    categories=None,
    quick_sample_size: int = DEFAULT_QUICK_SAMPLE_SIZE,
) -> dict:
    """Run one mode across its planned categories.

    Returns a report dict (never writes anything outside the run
    directories): one `runs` entry per category/(repetition) with the
    `run_cases_with_resume` result, plus an honestly-worded
    `skipped_categories` list for categories without a standalone case
    builder (structured_outputs/performance)."""
    if mode not in RUN_MODES:
        raise ValueError(f"unsupported run mode {mode!r} — known: {RUN_MODES}")
    if samples < 1:
        raise ValueError(f"samples must be >= 1, got {samples}")
    if quick_sample_size < 1:
        raise ValueError(f"quick_sample_size must be >= 1, got {quick_sample_size}")
    if strict_repro:
        if not _supports_seed(adapter):
            raise ValueError(
                "strict-repro (A11.5) requires an adapter that reports "
                f"capabilities().seed, but {type(adapter).__name__} reports otherwise — "
                "refusing to start before any case runs (a silently unseeded run "
                "would be a fabricated its-reproducible claim)"
            )
        if seed is None:
            seed = DEFAULT_STRICT_SEED

    category_ids = planned_category_ids(mode, category_id=category_id, categories=categories)
    report = {
        "mode": mode,
        "seed": seed,
        "strict_repro": strict_repro,
        "samples": samples,
        "runs": [],
        "skipped_categories": [],
    }
    multiple = len(category_ids) > 1
    for category_id in category_ids:
        cases = cases_for_category(category_id)
        if not cases:
            report["skipped_categories"].append(
                {
                    "category": category_id,
                    "why": (
                        f"{category_id!r} has no standalone case builder yet — "
                        + (
                            "needs a real fixture pack"
                            if category_id == "structured_outputs"
                            else "needs an existing category's cases to attach latency scorers to"
                        )
                    ),
                }
            )
            continue
        if mode == MODE_QUICK:
            cases = quick_cases(cases, quick_sample_size)
        case_ids = [case.id for case in cases]
        base = Path(run_dir) / category_id if multiple else Path(run_dir)
        for sample_index in range(1, samples + 1):
            target = base if samples == 1 else base / f"sample-{sample_index}"
            environment = build_run_environment(
                adapter,
                category_id,
                case_ids,
                mode=mode,
                seed=seed,
                strict_repro=strict_repro,
                samples=samples,
                sample_index=sample_index,
                quick_sample_size=(quick_sample_size if mode == MODE_QUICK else None),
            )
            registry = registry_for_category(category_id, adapter)
            results = run_cases_with_resume(
                cases,
                adapter,
                registry,
                str(target),
                environment=environment,
            )
            report["runs"].append(
                {
                    "category": category_id,
                    "run_dir": str(target),
                    "cases_planned": len(case_ids),
                    "results": results,
                }
            )
    return report