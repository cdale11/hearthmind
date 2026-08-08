"""HearthBench A4.4 — "scorers are pure, versioned, registered."

The literal checklist shape: `Scorer(id, version, fn(case, result,
context) -> ScoreDetail)`, with "scorer version is part of a run's
identity" (so a report can always say exactly which rubric produced a
number, and a later scorer-formula change never silently reinterprets
an old run's stored scores).

Import isolation (A1.2): stdlib only, plus `hearthbench.prompts.schema`
(the same package, not `hearthmind.simulation`/`.agents`/`.world`).

`CaseResult` is this module's one real design decision, not named
directly in the checklist: a scorer's `fn(case, result, context)`
needs a `result` shape to read, but A6 (the structured-output
validator with its own full run-record) and A11 (the runner that would
actually produce a live `result`) are both still unbuilt. Rather than
block every A4 scorer on either, `CaseResult` is a small, honest bridge
— the minimal set of fields A4.1's own checklist bullets actually need
(the parsed output, what it was grounded in, the raw text, whether a
fallback/repair happened, timing) — duck-typed onto both A2's live
`AdapterResult` (`from_adapter_result`) and an already-archived
recorder example (`from_archive_example`, the exact shape A3.1's
`fixtures.py` already reads via `review_pack.iter_examples`). A future
A6 run-record can carry strictly more detail than this; nothing here
assumes it won't.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from hearthbench.validation.repair_ladder import classify_repair


@dataclass
class CaseResult:
    """One case's real outcome, in the shape every A4.1 scorer reads.
    `output`/`structured_input` mirror `TrainingExample.layer4_parsed_
    output`/`layer1_structured_input` exactly (the same dict shapes
    `quality_labels.py`'s scorers already accept) so lifting a scorer
    from there is a signature-compatible call, not a rewrite."""

    task: str
    output: dict = field(default_factory=dict)
    structured_input: dict = field(default_factory=dict)
    raw_text: str = ""
    fallback_used: bool = False
    parse_repaired: bool = False
    repair_rung: str | None = None
    """A6.2's own real ladder rung this call landed on (`"raw"`/
    `"repaired"`/`"failed"`) — see `hearthbench.validation.repair_
    ladder.classify_repair`. `None` only for `from_archive_example`
    (a pre-A6.2 archived record carries no `AdapterResult` to classify
    from — an honest "not measured," never guessed)."""
    repair_reason: str | None = None
    """The human-readable reason for `repair_rung`, same source."""
    retries: int = 0
    latency_ms: float | None = None
    ttft_ms: float | None = None
    error: str | None = None

    @classmethod
    def from_adapter_result(cls, task: str, structured_input: dict, result: Any) -> "CaseResult":
        """`result` is an A2 `AdapterResult` (or anything with the
        same attribute names — duck-typed deliberately, so this
        doesn't import `hearthbench.adapters` and create a scoring<-
        >adapters coupling neither package needs). `parse_repaired`/
        `repair_rung`/`repair_reason` are real, computed via A6.2's
        `classify_repair` against this result's own `text`/`parsed`/
        `error` — not a hardcoded stub."""
        repair = classify_repair(
            getattr(result, "text", "") or "", getattr(result, "parsed", None), getattr(result, "error", None),
        )
        return cls(
            task=task,
            output=result.parsed if isinstance(getattr(result, "parsed", None), dict) else {},
            structured_input=dict(structured_input or {}),
            raw_text=getattr(result, "text", "") or "",
            fallback_used=getattr(result, "parsed", None) is None,
            parse_repaired=repair["parse_repaired"],
            repair_rung=repair["rung"], repair_reason=repair["reason"],
            retries=int(getattr(result, "retries", 0) or 0),
            latency_ms=getattr(result, "latency_ms", None),
            ttft_ms=getattr(result, "ttft_ms", None),
            error=getattr(result, "error", None),
        )

    @classmethod
    def from_archive_example(cls, example: dict) -> "CaseResult":
        """`example` is the `to_dict()` shape `review_pack.iter_
        examples`/A3.1's `fixtures.py` already read — reuses an
        archived recorder line directly as a `CaseResult`, so every
        A4.1 scorer can be exercised against real recorded data with
        zero adaptation."""
        output = example.get("layer4_parsed_output")
        return cls(
            task=example.get("task") or "",
            output=output if isinstance(output, dict) else {},
            structured_input=dict(example.get("layer1_structured_input") or {}),
            raw_text=example.get("layer3_raw_completion") or "",
            fallback_used=bool(example.get("fallback_used")),
            parse_repaired=bool(example.get("parse_repaired")),
            retries=0,
            latency_ms=example.get("latency_ms"),
            ttft_ms=None,
            error=None,
        )


@dataclass
class ScoreDetail:
    """One scorer's verdict on one case. `value` is a normalized
    `[0.0, 1.0]` "how good" reading (higher is better) — `None` when
    the scorer is a pure *measurement* rather than a judgment (e.g.
    latency: a number worth recording, but not itself good/bad without
    a threshold A10's future rubric would supply) or when the scorer
    genuinely doesn't apply to this case (mirrors `quality_labels.py`'s
    own `bool | None` convention: `None` means "can't judge this one,"
    never "judged and found lacking"). `passed`/`value` can both be
    set (a boolean gate plus a graded score) or either alone."""

    scorer_id: str
    scorer_version: str
    value: float | None = None
    passed: bool | None = None
    detail: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScoreDetail":
        return cls(
            scorer_id=data["scorer_id"], scorer_version=data["scorer_version"],
            value=data.get("value"), passed=data.get("passed"),
            detail=dict(data.get("detail") or {}), error=data.get("error"),
        )


ScorerFn = Callable[[Any, CaseResult, dict], ScoreDetail]
"""`fn(case: hearthbench.prompts.schema.TestCase, result: CaseResult,
context: dict) -> ScoreDetail` — the checklist's own literal signature.
`context` is free-form (a future runner's own choice what to put in
it — e.g. a judge adapter for Tier 2, prior outputs in the same run
for a repetition scorer); no scorer is required to use it."""


@dataclass(frozen=True)
class Scorer:
    """A4.4: "pure, versioned, registered." `id`/`version` are stamped
    onto every `ScoreDetail` this scorer produces regardless of what
    `fn` itself sets, so a scorer author can't accidentally desync a
    result's own identity from the registry's — `Scorer.score()` is
    the one call site that does the stamping, `fn` only needs to
    return the `value`/`passed`/`detail` half."""

    id: str
    version: str
    fn: ScorerFn
    tier: int
    """1 (deterministic, always-on), 2 (judge-model, optional), or 3
    (human, calibration-only) — A4's own three-tier split."""
    category: str = ""
    """Which A5 benchmark category this scorer primarily backs (e.g.
    "grounding", "structured_outputs") — informational only, never
    consulted by `score()` itself; a future A10 composite reads it to
    know which category a scorer's result rolls up into."""
    description: str = ""

    def score(self, case: Any, result: CaseResult, context: dict | None = None) -> ScoreDetail:
        """Never raises — a scorer bug degrades to a `ScoreDetail`
        carrying `error`, the same "a bad example degrades to no
        signal, not a crashed run" discipline every other per-example
        function in this codebase already holds (`quality_labels.
        label_example`, `check_leaks`, ...)."""
        try:
            detail = self.fn(case, result, context or {})
        except Exception as exc:  # noqa: BLE001 - a scorer must never abort a run
            return ScoreDetail(scorer_id=self.id, scorer_version=self.version, error=repr(exc))
        detail.scorer_id = self.id
        detail.scorer_version = self.version
        return detail
