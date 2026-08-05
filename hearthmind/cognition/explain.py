"""Tier 7 HCA Stage E, E1 (docs/ROADMAP-2026-07-REMAINING.md, Phase 7,
explicit user instruction "Start phase 7 E1"): the "why reasoning was
or was not invoked" panel — CLAUDE.md's own "Observatory UI direction"
section names the exact target line shape (headline panel, "The
Mind"):

    IMPASSE(no-change) · "family lines dying out" · 590 occurrences,
    no rule · DELIBERATED (94s)

    no impasse · peak surprise 0.3 < threshold 1.5 · cheap path

`explain_cycle` is the real function that produces exactly this line
— built entirely on C1's `Impasse` and C3's `DispatchOutcome`, the two
real primitives that already carry every piece of information the
line needs (kind, subject, detail, and how — or whether — the impasse
was actually resolved). No new detection/dispatch mechanism; this
module is pure presentation over what Stage C already computes.

Deliberately no dev-console UI wired this pass: C1/C2/C3 are not
wired into any real production `_schedule_llm_job` call site yet
(each item's own stated scope, `docs/ROADMAP-2026-07-REMAINING.md`'s
Phase 5 entries) — there is no real per-cycle `Impasse`/`DispatchOutcome`
pair flowing through the live tick loop for a panel to render today.
Same "ship the interface, wire the first real consumer next"
discipline every prior Stage A/B/C/D item in this codebase has used;
a dev-console panel rendering this line is real, distinct future
work, gated on that same production-wiring pass C3's own docstring
already names."""
from __future__ import annotations

from hearthmind.cognition.dispatch import DispatchOutcome
from hearthmind.cognition.impasse import Impasse

_RESOLUTION_LABELS = {
    "chunk": "CHUNK HIT (no deliberation)",
    "model": "MODEL RESOLVED (no deliberation)",
}
"""Plain-language labels for the two cheap `DispatchOutcome.resolved_
via` tiers — the LLM tier is handled separately below, since it's the
one case that carries a real elapsed-time figure worth reporting
(`deliberation_seconds`), matching the doc's own worked example
("DELIBERATED (94s)")."""


def explain_cycle(
    impasse: "Impasse | None",
    outcome: "DispatchOutcome | None" = None,
    deliberation_seconds: float | None = None,
    no_impasse_detail: str = "",
) -> str:
    """The one real line E1's panel exists to show, for a single real
    arbitration cycle.

    `impasse=None` (no named trigger fired this cycle — the common
    case): `"no impasse"`, plus `no_impasse_detail` if the caller
    supplies the real signal that stayed below its own threshold (e.g.
    A1's own surprise reading — `detect_novelty` returns `None` with
    no detail on a sub-threshold reading, so a caller wanting to show
    WHY must pass the raw number itself), always closed with
    `"cheap path"` — genuinely no deliberation was even considered.

    `impasse` present: `IMPASSE(<kind>) · "<subject>" · <detail>`,
    C1's own three fields verbatim (never re-derived or guessed at),
    plus a resolution clause from `outcome` when supplied — `outcome=
    None` (the impasse was detected but not yet dispatched) leaves the
    resolution clause off entirely rather than fabricating one.
    `resolved_via="llm"` reports real elapsed time via `deliberation_
    seconds` when the caller has one (`"DELIBERATED (Ns)"`); omitted
    it reads `"DELIBERATED"` alone — an honest degrade, never a
    invented number."""
    if impasse is None:
        detail = f" · {no_impasse_detail}" if no_impasse_detail else ""
        return f"no impasse{detail} · cheap path"

    kind_label = impasse.kind.value.replace("_", "-")
    line = f'IMPASSE({kind_label}) · "{impasse.subject}" · {impasse.detail}'
    if outcome is None:
        return line

    if outcome.resolved_via == "llm":
        resolution_label = (
            f"DELIBERATED ({deliberation_seconds:.0f}s)" if deliberation_seconds is not None
            else "DELIBERATED"
        )
    else:
        resolution_label = _RESOLUTION_LABELS.get(outcome.resolved_via, outcome.resolved_via.upper())
    return f"{line} · {resolution_label}"
