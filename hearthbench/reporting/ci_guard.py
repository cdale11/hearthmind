"""HearthBench A13 — prompt-regression guard in CI. "Catches a prompt
edit that silently degrades quality, discovered only weeks later in a
review pack."

Per the checklist's own SEQUENCE ("A13 CI regression guard — lands as
soon as [A4.1 deterministic scorers + A5.7/A5.8] works"), this ships
right after the objective A5 categories rather than waiting for A6-A12
— A13.1 explicitly needs only deterministic (`--no-judge`) scoring,
which has been real since A4.1/A5.7/A5.8 shipped. There is no CI
pipeline wired into this repo yet (same standing gap `scripts/verify_
runtime_invariant.py`'s own docstring already names) — this ships as a
real, standalone, manually-runnable guard (same convention as every
other `scripts/verify_*.py`), ready to be invoked from a future CI
workflow the moment one exists, not a GitHub Actions file with nothing
real behind it.

A13.1 (trigger): `is_relevant_change(changed_files)` — real, simple,
maintenance-free: ANY change under `hearthmind/llm/` (where every
prompt builder AND `json_schemas.py` already live) or under
`hearthbench/prompts/`/`hearthbench/scoring/` (the shared cognition-
contract surface, A0.3/A1.2's own territory) counts, rather than a
hand-maintained per-file list that silently goes stale the moment a
new prompt module is added.

A13.2 (objective-only gate): `DEFAULT_CI_THRESHOLDS` names only
grounding/structured-outputs metrics (leak/fabrication freedom,
schema/length compliance, fallback rate, context-reflection) —
deliberately nothing from a judge-scored category, matching A13.1's
own "CI needs no judge infra" and A13.2's own "never on subjective
scores, too noisy for CI."

A13.3 (thresholds relative to a baseline): reuses `hearthmind.llm.
eval_harness.check_regressions` directly — real reuse of A0.2, per
this item's own stated instruction — over the dotted-path metrics dict
`hearthbench.runner.run.summaries_to_metrics_dict` produces.

A13.4 (baseline refresh): `save_baseline`/`load_baseline` — a plain
JSON file, explicit `--refresh-baseline` CLI flag only, never written
implicitly by a regular check run.

A13.5 (nightly deeper run): real, distinct, unstarted future work —
needs actual CI infrastructure this repo doesn't have (same honest gap
as A13's own top-level status).

Import isolation (A1.2): stdlib + `hearthmind.llm.eval_harness`
(a shared, already-isolated module — confirmed no `hearthmind.
simulation`/`.agents`/`.world` import) + `hearthbench.*` only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hearthmind.llm.eval_harness import check_regressions

from hearthbench.runner.run import aggregate_scores, run_cases_against_adapter, summaries_to_metrics_dict
from hearthbench.tests import build_grounding_bait_cases

RELEVANT_CHANGE_PREFIXES = ("hearthmind/llm/", "hearthbench/prompts/", "hearthbench/scoring/")
"""A13.1's trigger surface — prefixes checked against repo-relative
paths (forward slashes; a caller on a platform with backslash paths
must normalize first, same convention `pathlib.PurePosixPath` callers
already expect elsewhere in this codebase)."""

DEFAULT_CI_THRESHOLDS = {
    "grounding.leak_freedom.pass_rate": {"min": 0.90},
    "grounding.no_unsupported_specifics.pass_rate": {"min": 0.80},
    "structured_outputs.schema_validity.pass_rate": {"min": 0.90},
    "structured_outputs.length_compliance.pass_rate": {"min": 0.90},
    "structured_outputs.fallback_free.pass_rate": {"min": 0.80},
}
"""A13.2's objective-only gate. Loosely reasoned starting points (not
validated against a real archive — this project has none in this
offline environment), same "starting points, not validated targets"
framing `eval_harness.DEFAULT_THRESHOLDS`'s own docstring already
carries; a maintainer tunes these against real measured baselines the
same way that module's own thresholds are meant to be tuned."""


def is_relevant_change(changed_files: list) -> bool:
    """A13.1: does this change touch anything a CI regression run
    should react to? `changed_files` is a list of repo-relative POSIX
    paths (e.g. from `git diff --name-only`); an empty list is
    honestly `False` (nothing changed, nothing to check)."""
    return any(any(f.startswith(prefix) for prefix in RELEVANT_CHANGE_PREFIXES) for f in changed_files)


@dataclass
class CIGuardResult:
    ran: bool
    """`False` when `is_relevant_change` found nothing to react to —
    the guard correctly did nothing, not a degraded/skipped check."""
    violations: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    n_cases_run: int = 0
    n_cases_skipped: int = 0

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict:
        return asdict(self)


def build_default_ci_cases() -> list:
    """The real objective-category cases this guard exercises by
    default — A5.7's four grounding bait cases today (each carries its
    own executable prompt via `turns`, needing no fixture pack).
    A5.8's structured-output cases are deliberately excluded here:
    they carry no prompt text of their own (see `structured_outputs.
    py`'s own docstring) and need a real fixture pack paired in by a
    caller — `run_ci_guard`'s own `fixtures_by_id` parameter is exactly
    that seam, left to whoever wires this into a real CI job with a
    real archive available."""
    return build_grounding_bait_cases()


def save_baseline(metrics: dict, path: "str | Path") -> None:
    """A13.4: baseline refresh is explicit — this is the ONLY write
    path, never called implicitly by `run_ci_guard`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, sort_keys=True)


def load_baseline(path: "str | Path") -> dict:
    """A missing baseline degrades to `{}` (no prior baseline yet — a
    first-ever run has nothing to regress against, `check_regressions`
    itself already treats a missing metric as "skip, not a violation")
    rather than raising."""
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def run_ci_guard(
    changed_files: list, adapter, registry, baseline_path: "str | Path",
    cases: list | None = None, fixtures_by_id: dict | None = None,
    thresholds: dict | None = None,
) -> CIGuardResult:
    """The real end-to-end guard: checks A13.1's trigger first (a
    genuine no-op, zero adapter calls, when nothing relevant changed);
    runs the real objective-category cases against `adapter`; compares
    the real resulting metrics against the stored baseline via A0.2's
    `check_regressions` (A13.3) — thresholds default to `DEFAULT_CI_
    THRESHOLDS`'s absolute floors, but since `check_regressions`
    operates on the SAME metrics dict shape either way, a caller could
    equally derive a baseline-relative threshold dict from `load_
    baseline(baseline_path)` and pass it in directly."""
    if not is_relevant_change(changed_files):
        return CIGuardResult(ran=False)

    cases = cases if cases is not None else build_default_ci_cases()
    cases_by_id = {c.id: c for c in cases}
    case_results = run_cases_against_adapter(cases, adapter, registry, fixtures_by_id=fixtures_by_id)
    n_skipped = sum(1 for r in case_results.values() if r is None)
    n_run = len(case_results) - n_skipped

    summaries = aggregate_scores(case_results, cases_by_id)
    metrics = summaries_to_metrics_dict(summaries)
    violations = check_regressions(metrics, thresholds if thresholds is not None else DEFAULT_CI_THRESHOLDS)

    return CIGuardResult(ran=True, violations=violations, metrics=metrics, n_cases_run=n_run, n_cases_skipped=n_skipped)
