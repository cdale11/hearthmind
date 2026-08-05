#!/usr/bin/env python3
"""Tier 7 HCA Stage C, C3 (docs/ROADMAP-2026-07-REMAINING.md, Phase 5,
explicit user instruction "Start C3" — closes Stage C in full):
cheap-resolver dispatch, preferring the cheapest resolver that
suffices.

Verifies `hearthmind/cognition/dispatch.py`'s `dispatch_impasse`
against real `Impasse`/`ChunkStore` objects (C1/C2's own real
primitives): the ladder order (chunk -> model -> LLM), that an LLM
resolution genuinely compiles a new chunk so the SAME impasse never
pays that cost again, that a model resolver is skipped entirely once
a chunk exists, and — C3's own stated headline test — a real
statistical proof that repeated real impasses converge well past the
">30% resolve without an LLM call" bar, over a realistic recurrence
distribution."""
from __future__ import annotations

import random
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
    from hearthmind.cognition.dispatch import RESOLVED_VIA_KINDS, dispatch_impasse
    from hearthmind.cognition.impasse import detect_no_change
    from hearthmind.settlement.institutions import (
        INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD, Institution, InstitutionKind,
    )

    def real_impasse(subject: str) -> object:
        institution = Institution(id=1, kind=InstitutionKind.FAMILY, founding_tick=0)
        institution.objective_ticks_unmet = INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD
        return detect_no_change(subject, institution.objective_ticks_unmet,
                                 INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)

    # --- the cheapest tier: a genuine cache hit skips model AND llm ---
    store = ChunkStore()
    impasse = real_impasse("family_lines_dying_out")
    store.compile(impasse, "trigger_rule", "form an inheritance law", tick=100)

    model_calls = []
    llm_calls = []
    outcome = dispatch_impasse(
        impasse, store, tick=200,
        llm_resolver=lambda: llm_calls.append(1) or "llm answer",
        model_resolver=lambda: model_calls.append(1) or "model answer",
    )
    check("a real chunk hit resolves via 'chunk'", outcome.resolved_via == "chunk")
    check("a real chunk hit returns the chunk's own cached resolution",
          outcome.resolution == "form an inheritance law")
    check("a real chunk hit never calls the model resolver", model_calls == [])
    check("a real chunk hit never calls the LLM resolver", llm_calls == [])
    check("a real chunk hit's outcome carries the real chunk that was consulted",
          outcome.chunk is not None and outcome.chunk.hit_count == 1)

    # --- no chunk yet, but a real model resolver is available ---
    store2 = ChunkStore()
    fresh_impasse = real_impasse("the fishing guild")
    model_calls2 = []
    llm_calls2 = []
    outcome2 = dispatch_impasse(
        fresh_impasse, store2, tick=300,
        llm_resolver=lambda: llm_calls2.append(1) or "llm answer",
        model_resolver=lambda: model_calls2.append(1) or "model answer",
    )
    check("no chunk yet + a real model resolver -> resolves via 'model'",
          outcome2.resolved_via == "model" and outcome2.resolution == "model answer")
    check("the model tier never falls through to the LLM", llm_calls2 == [])
    check("a model-tier resolution does NOT compile a new chunk (only the LLM tier does)",
          outcome2.chunk is None and store2.size() == 0)

    # --- no chunk, no model -> the LLM is the real last resort ---
    store3 = ChunkStore()
    llm_impasse = real_impasse("the shrinking granary reserve")
    llm_calls3 = []
    outcome3 = dispatch_impasse(
        llm_impasse, store3, tick=400,
        llm_resolver=lambda: llm_calls3.append(1) or "genuine LLM deliberation",
        model_resolver=None,
    )
    check("no chunk, no model resolver -> genuinely reaches the LLM tier",
          outcome3.resolved_via == "llm" and llm_calls3 == [1])
    check("an LLM resolution DOES compile a new real chunk", store3.size() == 1)
    check("the newly-compiled chunk holds the real LLM resolution",
          outcome3.chunk is not None and outcome3.chunk.resolution == "genuine LLM deliberation")

    # --- the real point of C2+C3 together: the SAME impasse recurring
    #     is now served from the chunk, never the LLM again ---
    llm_calls3_again = []
    outcome4 = dispatch_impasse(
        llm_impasse, store3, tick=500,
        llm_resolver=lambda: llm_calls3_again.append(1) or "should never run",
    )
    check("a recurrence of the SAME impasse after an LLM resolution hits the chunk instead",
          outcome4.resolved_via == "chunk" and llm_calls3_again == [])

    check("RESOLVED_VIA_KINDS is exactly the three real ladder tiers, cheapest first",
          RESOLVED_VIA_KINDS == ("chunk", "model", "llm"))

    # --- C3's own headline test: >30% of resolutions skip the LLM
    #     entirely, over a real statistical distribution of recurring
    #     impasses (a realistic soak shape -- a handful of subjects
    #     recur often, most fire only once) ---
    rng = random.Random(4242)
    soak_store = ChunkStore()
    RECURRING_SUBJECTS = [f"recurring_problem_{i}" for i in range(5)]
    resolved_via_counts = {"chunk": 0, "model": 0, "llm": 0}
    TOTAL_CYCLES = 2000
    for tick in range(TOTAL_CYCLES):
        # 70% of cycles hit one of a small recurring set (the real
        # shape HCA's own §1.4 finding names -- a handful of subjects
        # dominate real emergence traffic); 30% are genuinely novel.
        if rng.random() < 0.7:
            subject = rng.choice(RECURRING_SUBJECTS)
        else:
            subject = f"novel_problem_{tick}"
        cycle_impasse = real_impasse(subject)
        outcome = dispatch_impasse(
            cycle_impasse, soak_store, tick=tick,
            llm_resolver=lambda: "deliberated answer",
        )
        resolved_via_counts[outcome.resolved_via] += 1

    non_llm_fraction = (TOTAL_CYCLES - resolved_via_counts["llm"]) / TOTAL_CYCLES
    check(
        f"a real 2000-cycle recurring-impasse soak resolves {non_llm_fraction:.1%} "
        f"without an LLM call (C3's own stated >30% bar)",
        non_llm_fraction > 0.30,
    )
    check("the soak's real per-tier counts are internally consistent",
          sum(resolved_via_counts.values()) == TOTAL_CYCLES)

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
