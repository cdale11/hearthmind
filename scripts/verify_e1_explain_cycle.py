#!/usr/bin/env python3
"""Tier 7 HCA Stage E, E1 (docs/ROADMAP-2026-07-REMAINING.md, Phase 7,
explicit user instruction "Start phase 7 E1"): the "why reasoning was
or was not invoked" panel.

Verifies `hearthmind.cognition.explain.explain_cycle` against real
`Impasse`/`DispatchOutcome` objects (C1/C3's own real primitives, the
same shape `verify_c1_impasse.py`/`verify_c3_dispatch.py` already
drive): the no-impasse "cheap path" line, the with-detail no-impasse
line, a bare impasse line with no dispatch outcome yet, and all three
real resolution tiers (chunk hit, model resolved, LLM deliberated —
with and without a real elapsed-time figure) — plus E1's own stated
test, driven over a real soak: every one of a batch of real cycles
produces a genuinely legible one-line reason, never a blank/malformed
one."""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    from hearthmind.cognition.chunk import ChunkStore
    from hearthmind.cognition.dispatch import DispatchOutcome, dispatch_impasse
    from hearthmind.cognition.explain import explain_cycle
    from hearthmind.cognition.impasse import detect_no_change, detect_novelty
    from hearthmind.settlement.institutions import (
        INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD, Institution, InstitutionKind,
    )

    # --- no impasse: the cheap-path line, both with and without a
    #     real caller-supplied "why it stayed below threshold" detail ---
    bare = explain_cycle(None)
    check("a real no-impasse cycle reads 'no impasse ... cheap path'",
          bare == "no impasse · cheap path")
    novelty_none = detect_novelty("a quiet settlement", surprise=0.3, threshold=1.5)
    check("a real sub-threshold novelty reading genuinely returns no impasse",
          novelty_none is None)
    with_detail = explain_cycle(None, no_impasse_detail="peak surprise 0.30 < threshold 1.50")
    check("a supplied no-impasse detail is genuinely included",
          with_detail == "no impasse · peak surprise 0.30 < threshold 1.50 · cheap path")

    # --- a real impasse, no dispatch outcome yet (detected, not yet
    #     resolved -- the resolution clause must be honestly absent) ---
    institution = Institution(id=1, kind=InstitutionKind.FAMILY, founding_tick=0)
    institution.objective_ticks_unmet = INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD + 590
    impasse = detect_no_change(
        "family lines dying out", institution.objective_ticks_unmet,
        INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD,
    )
    check("a real no_change impasse fires past its own threshold", impasse is not None)
    undispatched_line = explain_cycle(impasse)
    check("a real impasse with no outcome yet carries no fabricated resolution clause",
          "IMPASSE(no-change)" in undispatched_line and "family lines dying out" in undispatched_line
          and "DELIBERATED" not in undispatched_line and "HIT" not in undispatched_line)

    # --- the three real resolution tiers, each through a real
    #     ChunkStore/dispatch_impasse cycle ---
    store = ChunkStore()
    llm_outcome = dispatch_impasse(impasse, store, tick=100, llm_resolver=lambda: "form an inheritance law")
    check("a genuine LLM resolution reports DELIBERATED", llm_outcome.resolved_via == "llm")
    llm_line_with_time = explain_cycle(impasse, llm_outcome, deliberation_seconds=94.0)
    check("a real LLM deliberation with a real elapsed time reports it",
          llm_line_with_time.endswith("DELIBERATED (94s)"))
    llm_line_no_time = explain_cycle(impasse, llm_outcome)
    check("a real LLM deliberation with no supplied elapsed time degrades honestly (no fabricated number)",
          llm_line_no_time.endswith("DELIBERATED") and "94" not in llm_line_no_time)

    chunk_outcome = dispatch_impasse(impasse, store, tick=200, llm_resolver=lambda: "should never run")
    check("the SAME impasse recurring now hits the real compiled chunk",
          chunk_outcome.resolved_via == "chunk")
    check("a real chunk-hit cycle reports CHUNK HIT with no deliberation",
          explain_cycle(impasse, chunk_outcome).endswith("CHUNK HIT (no deliberation)"))

    model_outcome = DispatchOutcome(impasse=impasse, resolved_via="model", resolution="a real model answer")
    check("a real model-resolved cycle reports MODEL RESOLVED with no deliberation",
          explain_cycle(impasse, model_outcome).endswith("MODEL RESOLVED (no deliberation)"))

    # --- E1's own stated test: every cycle in a real soak has a
    #     legible one-line reason -- a batch of real, mixed cycles
    #     (some impassed, some not, each real dispatch tier) never
    #     produces a blank or malformed line. ---
    import random

    rng = random.Random(99)
    soak_store = ChunkStore()
    lines: list[str] = []
    for tick in range(200):
        subject = f"subject_{tick % 7}"
        streak = rng.randint(0, INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD + 5)
        cycle_impasse = detect_no_change(subject, streak, INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
        if cycle_impasse is None:
            lines.append(explain_cycle(None, no_impasse_detail=f"streak {streak} < threshold"))
            continue
        cycle_outcome = dispatch_impasse(cycle_impasse, soak_store, tick=tick, llm_resolver=lambda: "answer")
        lines.append(explain_cycle(cycle_impasse, cycle_outcome, deliberation_seconds=float(tick)))

    check("every one of 200 real soak cycles produced a real, legible, non-empty line",
          len(lines) == 200 and all(isinstance(line, str) and line.strip() for line in lines))
    check("every real soak line starts with either 'IMPASSE(' or 'no impasse' -- never malformed",
          all(line.startswith("IMPASSE(") or line.startswith("no impasse") for line in lines))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
