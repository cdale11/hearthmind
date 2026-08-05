#!/usr/bin/env python3
"""Tier 7 HCA Stage D, D2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 6,
explicit user instruction "Start D2"): declarative/procedural
separation made architectural.

Verifies `hearthmind.cognition.memory_kind`'s real `MemoryKind` type
and classification, then `scripts/verify_runtime_invariant.py`'s new
`check_memory_kind_separation()` — same shape H1's own domain-check
verify script used: the real production tree is clean today (`D1`'s
`activation.py`/C2's `chunk.py` genuinely marked, C3's `dispatch.py`
deliberately unmarked as the real neutral composition layer), a
synthetic DECLARATIVE module importing the procedural store IS caught,
a synthetic PROCEDURAL module importing the declarative store IS
caught, the identical import under no marker at all is correctly NOT
flagged, and a real end-to-end scan over a synthetic directory finds
exactly the two real violations and nothing else."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    from hearthmind.cognition.memory_kind import (
        DECLARATIVE_STORE_NAMES, PROCEDURAL_STORE_NAMES, MemoryKind, memory_kind_of,
    )
    import scripts.verify_runtime_invariant as invariant  # noqa: E402 -- sys.path set above

    check("MemoryKind has exactly the two named kinds",
          {k.name for k in MemoryKind} == {"DECLARATIVE", "PROCEDURAL"})
    check("a real Agent declarative store classifies correctly",
          memory_kind_of("memories") is MemoryKind.DECLARATIVE)
    check("a real procedural artifact kind classifies correctly",
          memory_kind_of("chunk") is MemoryKind.PROCEDURAL)
    check("an unrecognized name classifies as None, never guessed at",
          memory_kind_of("not_a_real_store") is None)
    check("no name appears in both classifications (a real, non-overlapping split)",
          set(DECLARATIVE_STORE_NAMES).isdisjoint(PROCEDURAL_STORE_NAMES))

    # --- the real production tree is clean today ---
    real_violations = invariant.check_memory_kind_separation()
    check("the real hearthmind/ tree has zero memory-kind separation violations today",
          real_violations == {})

    # --- the two real production modules are genuinely marked, and
    #     C3's dispatch.py is genuinely NOT (the neutral composition
    #     layer) -- confirmed directly against the real files, not a
    #     synthetic stand-in. ---
    import ast
    activation_tree = ast.parse((Path("/home/user/hearthmind/hearthmind/cognition/activation.py")).read_text())
    chunk_tree = ast.parse((Path("/home/user/hearthmind/hearthmind/cognition/chunk.py")).read_text())
    dispatch_tree = ast.parse((Path("/home/user/hearthmind/hearthmind/cognition/dispatch.py")).read_text())
    check("the real activation.py declares itself DECLARATIVE",
          invariant._declared_memory_kind(activation_tree) == "DECLARATIVE")
    check("the real chunk.py declares itself PROCEDURAL",
          invariant._declared_memory_kind(chunk_tree) == "PROCEDURAL")
    check("the real dispatch.py (the neutral composition layer) declares NEITHER kind",
          invariant._declared_memory_kind(dispatch_tree) is None)

    d = Path(tempfile.mkdtemp())

    # --- a genuine synthetic violation: a DECLARATIVE module reaching
    #     into the procedural store -- must be caught. ---
    declarative_bad = d / "declarative_bad.py"
    declarative_bad.write_text(
        "from hearthmind.cognition.memory_kind import MemoryKind\n"
        "MEMORY_KIND = MemoryKind.DECLARATIVE\n"
        "from hearthmind.cognition.chunk import ChunkStore\n"
    )
    check("a synthetic DECLARATIVE module importing the real procedural store IS caught",
          invariant._memory_kind_violations_in_file(declarative_bad) != [])

    # --- a genuine synthetic violation: a PROCEDURAL module reaching
    #     into the declarative store -- must be caught. ---
    procedural_bad = d / "procedural_bad.py"
    procedural_bad.write_text(
        "from hearthmind.cognition.memory_kind import MemoryKind\n"
        "MEMORY_KIND = MemoryKind.PROCEDURAL\n"
        "from hearthmind.agents.agent import retrieve_relevant_memories\n"
    )
    check("a synthetic PROCEDURAL module importing the real declarative store IS caught",
          invariant._memory_kind_violations_in_file(procedural_bad) != [])

    # --- no marker at all -- must NOT be flagged. ---
    undeclared = d / "undeclared.py"
    undeclared.write_text(
        "from hearthmind.cognition.chunk import ChunkStore\n"
        "from hearthmind.agents.agent import retrieve_relevant_memories\n"
    )
    check("a file with no MEMORY_KIND marker at all is correctly NOT flagged, "
          "even importing BOTH stores",
          invariant._memory_kind_violations_in_file(undeclared) == [])

    # --- a real end-to-end proof over a synthetic directory ---
    scanned = invariant.check_memory_kind_separation(scan_root=d)
    check("check_memory_kind_separation() over the synthetic directory finds exactly the "
          "two real violations (declarative_bad.py, procedural_bad.py) and nothing else",
          set(scanned.keys()) == {str(declarative_bad), str(procedural_bad)})

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
