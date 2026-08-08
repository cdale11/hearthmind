"""HearthBench C5 — the model passport [APPROVED].

HearthBench emits a small, portable `passport.json` per benchmarked
model that the runtime reads at startup to seed its own machine
profile — closing the C2 loop ("HearthBench's measured model
throughput seeds the runtime's machine profile") automatically
instead of by hand.

**Contents**, per the checklist's own literal spec: model id +
quantization + file hash; the real `HearthBenchScore` with confidence
(`world_score` stays `None` until A5.11's world-level run exists —
last in SEQUENCE, gated on B15.5); per-category strengths/weaknesses
(scored at/above `STRENGTH_THRESHOLD`/at-or-below `WEAKNESS_THRESHOLD`
— a loosely-reasoned starting point, same class as every other
threshold in this package, not a validated cutoff); measured
throughput (completion tok/s, TTFT, latency p50/p95, from `hearthbench.
tests.performance.summarize_latency`'s own stats — every value `None`
when not measured, never fabricated); recommended settings (today just
`needs_grammar_constraints`, derived from the real structured_outputs
category score — a model that scores low unconstrained genuinely needs
a grammar to be reliable); and hard warnings, one per real A10.2
disqualification that actually fired this run.

`peak_rss_mb_by_concurrency` is deliberately shipped empty — no
concurrency-sweep benchmarking mechanism exists anywhere in this
codebase yet to source it from (A7.2, a system-sampling thread, is the
real prerequisite); an honestly-empty dict here, never a fabricated
reading.

**Runtime consumption is the other half of C5 and deliberately lives
on the `hearthmind` side, not here** —
`hearthmind.simulation.hardware_profile.seed_machine_profile_from_
passport` reads this module's own JSON shape directly (plain `dict`,
no import of this package) and seeds `MachineProfile.measured_llm_
throughput_tokens_per_s` only for a genuinely fresh profile, per the
checklist's own "priors, not overrides — B6's controllers still adapt
from live measurement." Per A1.2's import firewall (which runs BOTH
directions — `hearthbench` never imports `hearthmind.simulation`/
`.agents`/`.world`, and `hearthmind` never imports `hearthbench`), the
passport's own field shape (this module's `to_dict`/`from_dict`) is
the ONLY coupling — the same "shared record schema, not a shared
import" precedent A0.3/C4 already established for this project.

Import isolation (A1.2): stdlib + `hearthbench.reporting.score` only.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from dataclasses import asdict, dataclass, field

from hearthbench.reporting.score import HearthBenchScore

PASSPORT_SCHEMA_VERSION = 1

STRENGTH_THRESHOLD = 80.0
WEAKNESS_THRESHOLD = 50.0
"""A category scoring at/above `STRENGTH_THRESHOLD` is listed as a
strength; at/below `WEAKNESS_THRESHOLD` as a weakness. A score strictly
between the two lands in neither list — a genuine "unremarkable"
middle band, not forced into either bucket."""


def produced_by_host() -> str:
    """A local, hearthbench-only host identifier for a passport's own
    provenance — deliberately NOT `hearthmind.simulation.hardware_
    profile.host_fingerprint()` (that module lives under the banned
    `hearthmind.simulation` import path, per A1.2's firewall); this is
    the exact same formula, reimplemented standalone, so a passport's
    `produced_by_host` is directly comparable to a runtime `Machine
    Profile.host_fingerprint` on the other side without either package
    importing the other. Deliberately non-cryptographic — just a key
    for "was this passport produced on THIS machine," per the
    checklist's own "a passport from a very different machine
    contributes throughput priors with lower weight.\""""
    raw = f"{platform.node()}|{os.cpu_count()}|{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ModelPassport:
    """A small, portable record of one benchmarked model — see this
    module's own docstring for the field-by-field rationale."""

    model_id: "str | None" = None
    quantization: "str | None" = None
    file_hash: "str | None" = None
    hearthbench_score: "float | None" = None
    hearthbench_confidence_margin: "float | None" = None
    world_score: "float | None" = None
    category_strengths: list = field(default_factory=list)
    category_weaknesses: list = field(default_factory=list)
    measured_throughput: dict = field(default_factory=dict)
    """`{completion_tokens_per_s, ttft_ms, latency_p50_ms, latency_p95_ms}`
    — flat real values (each `None` when unmeasured), sourced from a
    real run's own `hearthbench.tests.performance.summarize_latency`
    output, never fabricated."""
    peak_rss_mb_by_concurrency: dict = field(default_factory=dict)
    recommended_settings: dict = field(default_factory=dict)
    hard_warnings: list = field(default_factory=list)
    produced_at: float = field(default_factory=time.time)
    produced_by_host: "str | None" = None
    schema_version: int = PASSPORT_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelPassport":
        if d.get("schema_version") != PASSPORT_SCHEMA_VERSION:
            raise ValueError(f"unsupported passport schema_version={d.get('schema_version')!r}")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def build_passport(
    score: HearthBenchScore, adapter_describe: dict, latency_stats: "dict | None" = None,
) -> ModelPassport:
    """Builds a real passport from a real, already-computed
    `HearthBenchScore` (A10) + a real adapter's `describe()` (A2.1,
    already converted to a plain dict by A8's `build_environment_
    snapshot`, or supplied directly) + a run's own real `summarize_
    latency` output. Never called with fabricated inputs by any code
    in this package — a caller with no real latency stats simply
    passes `None` and gets an honestly-empty `measured_throughput`."""
    adapter_describe = adapter_describe or {}
    strengths = []
    weaknesses = []
    for category_id, category_score in score.category_scores.items():
        if category_score >= STRENGTH_THRESHOLD:
            strengths.append(category_id)
        elif category_score <= WEAKNESS_THRESHOLD:
            weaknesses.append(category_id)

    throughput: dict = {}
    if latency_stats:
        latency_ms = latency_stats.get("latency_ms") or {}
        ttft_ms = latency_stats.get("ttft_ms") or {}
        tok_s = latency_stats.get("completion_tokens_per_sec") or {}
        throughput = {
            "completion_tokens_per_s": tok_s.get("p50"),
            "ttft_ms": ttft_ms.get("p50"),
            "latency_p50_ms": latency_ms.get("p50"),
            "latency_p95_ms": latency_ms.get("p95"),
        }

    structured_score = score.category_scores.get("structured_outputs")
    recommended = {
        "needs_grammar_constraints": structured_score is not None and structured_score < STRENGTH_THRESHOLD,
    }

    hard_warnings = [
        f"fails {d['category']} ({d['actual']:.1f} < {d['floor']:.1f}) — {d['reason']}"
        for d in score.disqualifications
    ]

    return ModelPassport(
        model_id=adapter_describe.get("model"),
        quantization=adapter_describe.get("quantization"),
        file_hash=(adapter_describe.get("extra") or {}).get("file_hash"),
        hearthbench_score=score.total,
        hearthbench_confidence_margin=score.overall_confidence_margin,
        category_strengths=sorted(strengths),
        category_weaknesses=sorted(weaknesses),
        measured_throughput=throughput,
        recommended_settings=recommended,
        hard_warnings=hard_warnings,
        produced_by_host=produced_by_host(),
    )


def save_passport(passport: ModelPassport, path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(passport.to_dict(), fh, indent=2, sort_keys=True, default=str)


def load_passport(path: str) -> ModelPassport:
    with open(path, "r", encoding="utf-8") as fh:
        return ModelPassport.from_dict(json.load(fh))
