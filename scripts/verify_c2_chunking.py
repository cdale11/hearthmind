#!/usr/bin/env python3
"""Tier 7 HCA Stage C, C2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 5,
explicit user instruction "Start C2"): chunking — compile a resolved
impasse into a cheap reusable artifact.

Verifies `hearthmind/cognition/chunk.py`'s `ChunkStore` against real
`Impasse` objects produced by C1's own real classifiers (a real
no-change impasse from a real `Institution.objective_ticks_unmet`
streak, and a real tie impasse from a real arbitrated
`CompetitionRecord`) — not synthetic stand-ins.
"""
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
    from hearthmind.cognition.chunk import ARTIFACT_KINDS, CHUNK_STORE_MAX, Chunk, ChunkStore, chunk_signature
    from hearthmind.cognition.impasse import ImpasseKind, detect_no_change, detect_tie_from_competition
    from hearthmind.cognition.workspace import Bid, GlobalWorkspace

    # --- a real no-change impasse, from a real institution scenario
    #     (HCA's own worked example: "590 family extinctions, no rule") ---
    from hearthmind.settlement.institutions import (
        INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD, Institution, InstitutionKind,
    )

    institution = Institution(id=7, kind=InstitutionKind.FAMILY, founding_tick=0)
    institution.objective_ticks_unmet = INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD
    no_change = detect_no_change("family_lines_dying_out", institution.objective_ticks_unmet,
                                  INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
    check("a real no-change impasse exists to compile against", no_change is not None)

    store = ChunkStore()
    check("a fresh ChunkStore starts empty", store.size() == 0)
    check("a lookup against an empty store returns None, never fabricates a chunk",
          store.lookup(no_change) is None)

    chunk = store.compile(no_change, "trigger_rule",
                           {"rule": "on_family_extinction", "action": "inheritance_law"}, tick=1000)
    check("compile() returns a real Chunk keyed by the impasse's own signature",
          chunk.signature == chunk_signature(no_change) and chunk.artifact_kind == "trigger_rule")
    check("the store now holds exactly one chunk", store.size() == 1)
    check("a freshly-compiled chunk has zero hits and no last_hit_tick yet",
          chunk.hit_count == 0 and chunk.last_hit_tick is None)

    # --- the real point of chunking: the NEXT occurrence of the SAME
    #     impasse is a cheap lookup, not fresh deliberation ---
    institution.objective_ticks_unmet += 1  # the 591st occurrence, so to speak
    repeat_impasse = detect_no_change("family_lines_dying_out", institution.objective_ticks_unmet,
                                       INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
    found = store.lookup(repeat_impasse)
    check("the SAME recurring impasse (same kind+subject, different streak count in its own detail) "
          "hits the existing chunk — chunking is keyed by signature, not by the exact detail text",
          found is not None and found is chunk)

    store.record_hit(found, tick=1001)
    check("record_hit genuinely increments the real hit count", found.hit_count == 1)
    check("record_hit genuinely records the real tick it was reused at", found.last_hit_tick == 1001)

    # --- a DIFFERENT subject never accidentally hits the same chunk ---
    other_institution = Institution(id=8, kind=InstitutionKind.GUILD, founding_tick=0)
    other_institution.objective_ticks_unmet = INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD
    other_impasse = detect_no_change("the fishing guild", other_institution.objective_ticks_unmet,
                                      INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
    check("a genuinely different subject's impasse does NOT hit an unrelated chunk",
          store.lookup(other_impasse) is None)

    # --- a real tie impasse, from a real arbitrated CompetitionRecord ---
    ws = GlobalWorkspace()
    ws.submit(Bid(specialist_id="a", subject="build_site", score=0.601))
    ws.submit(Bid(specialist_id="b", subject="build_site", score=0.599))
    ws.arbitrate()
    tie = detect_tie_from_competition(ws.history[-1])
    check("a real tie impasse exists to compile against", tie is not None and tie.kind is ImpasseKind.TIE)
    tie_chunk = store.compile(tie, "cached_decision", "prefer the northern site", tick=2000)
    check("a tie impasse compiles into its own distinct chunk",
          store.size() == 2 and tie_chunk.signature != chunk.signature)

    # --- an unrecognized artifact_kind is rejected, not silently accepted ---
    try:
        Chunk(signature="x", artifact_kind="not_a_real_kind", resolution=None, created_tick=0)
        rejected = False
    except ValueError:
        rejected = True
    check("compiling with an artifact_kind outside HCA's own closed vocabulary is rejected",
          rejected)
    check("ARTIFACT_KINDS is exactly HCA's own stated four-item vocabulary",
          set(ARTIFACT_KINDS) == {"cached_decision", "model_update", "trigger_rule", "revised_belief"})

    # --- bounded eviction: least-recently-reused goes first, the chunk
    #     just compiled is always protected from its own eviction pass ---
    small_store = ChunkStore()
    filler_impasses = []
    for i in range(CHUNK_STORE_MAX):
        imp = detect_no_change(f"subject_{i}", INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD,
                                INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
        filler_impasses.append(imp)
        small_store.compile(imp, "cached_decision", i, tick=i)
    check(f"the store holds exactly its own configured cap ({CHUNK_STORE_MAX}) before overflow",
          small_store.size() == CHUNK_STORE_MAX)

    # touch every chunk but the very first one, so it's genuinely the
    # least-recently-reused when the store overflows
    for i, imp in enumerate(filler_impasses[1:], start=1):
        small_store.record_hit(small_store.lookup(imp), tick=10_000 + i)

    overflow_impasse = detect_no_change("subject_overflow", INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD,
                                         INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD)
    small_store.compile(overflow_impasse, "cached_decision", "overflow", tick=99_999)
    check("the store never grows past its own configured cap",
          small_store.size() == CHUNK_STORE_MAX)
    check("the genuinely least-recently-reused chunk (never hit, oldest) was evicted",
          small_store.lookup(filler_impasses[0]) is None)
    check("a chunk that WAS reused survives the eviction pass",
          small_store.lookup(filler_impasses[1]) is not None)
    check("the chunk just compiled this same call is never the one evicted",
          small_store.lookup(overflow_impasse) is not None)

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
