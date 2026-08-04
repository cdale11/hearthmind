#!/usr/bin/env python3
"""Tier 7 HCA Stage H, H1 (explicit user instruction: "Start phase
3.5 W1 and a parallel task of your choice with biggest impact" — H1
is the first item Stage B (closed v1.34.229) + Stage G (closed
v1.34.219) both genuinely unblock): cognitive domains as a real,
mechanically-enforced type.

H1's own stated test: "an AST check (extending `scripts/verify_
runtime_invariant.py`) proves no MACHINE- or OBSERVER-domain code
path writes `world/`/`agents/`/`settlement/`/`economy/` state, and
genuinely catches a synthetic violation rather than merely passing on
clean code." Verified here: `Domain`/`Bid.domain` exist and default
correctly; the real tree is clean today (no MACHINE/OBSERVER module
exists yet); a synthetic MACHINE-domain file importing real world
state is genuinely caught; a synthetic OBSERVER-domain file importing
real agent state is genuinely caught; a synthetic WORLD-domain file
doing the identical import is correctly NOT flagged (WORLD is
expected to touch world state); an undeclared (no marker at all) file
is likewise not flagged; and a real `Bid`'s `domain` survives
`GlobalWorkspace.arbitrate()` unchanged.
"""
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
    from hearthmind.cognition.workspace import Bid, Domain, GlobalWorkspace
    import scripts.verify_runtime_invariant as invariant  # noqa: E402 -- sys.path set above

    check("Domain has exactly the three named cognitive domains",
          {d.name for d in Domain} == {"WORLD", "MACHINE", "OBSERVER"})
    check("a Bid with no explicit domain defaults to WORLD",
          Bid(specialist_id="s", subject="x", score=0.5).domain is Domain.WORLD)
    check("a Bid can carry an explicit MACHINE domain",
          Bid(specialist_id="s", subject="x", score=0.5, domain=Domain.MACHINE).domain is Domain.MACHINE)

    # --- the real production tree is clean today: no real MACHINE/
    #     OBSERVER-domain module exists yet (that's H2/H4's later job) ---
    real_violations = invariant.check_domain_write_scope()
    check("the real hearthmind/ tree has zero domain write-scope violations today",
          real_violations == {})

    d = Path(tempfile.mkdtemp())

    # --- a genuine synthetic violation: MACHINE-domain module
    #     importing real world state -- must be caught. ---
    machine_bad = d / "machine_bad.py"
    machine_bad.write_text(
        "from hearthmind.cognition.workspace import Domain\n"
        "SPECIALIST_DOMAIN = Domain.MACHINE\n"
        "from hearthmind.world.state import World\n"
    )
    check("a synthetic MACHINE-domain file importing real world state IS caught",
          invariant._domain_write_violations_in_file(machine_bad) != [])

    # --- a genuine synthetic violation: OBSERVER-domain module
    #     importing real agent state -- must be caught. ---
    observer_bad = d / "observer_bad.py"
    observer_bad.write_text(
        "from hearthmind.cognition.workspace import Domain\n"
        "SPECIALIST_DOMAIN = Domain.OBSERVER\n"
        "import hearthmind.agents.population\n"
    )
    check("a synthetic OBSERVER-domain file importing real agent state IS caught",
          invariant._domain_write_violations_in_file(observer_bad) != [])

    # --- the identical import, but WORLD-domain -- must NOT be
    #     flagged (WORLD is expected to touch world state). ---
    world_ok = d / "world_ok.py"
    world_ok.write_text(
        "from hearthmind.cognition.workspace import Domain\n"
        "SPECIALIST_DOMAIN = Domain.WORLD\n"
        "from hearthmind.world.state import World\n"
    )
    check("the identical import under a WORLD-domain marker is correctly NOT flagged",
          invariant._domain_write_violations_in_file(world_ok) == [])

    # --- no marker at all -- must NOT be flagged (only a real
    #     MACHINE/OBSERVER declaration triggers this check). ---
    undeclared = d / "undeclared.py"
    undeclared.write_text("from hearthmind.world.state import World\n")
    check("a file with no SPECIALIST_DOMAIN marker at all is correctly NOT flagged",
          invariant._domain_write_violations_in_file(undeclared) == [])

    # --- a real end-to-end proof: check_domain_write_scope() over a
    #     directory containing exactly these five files finds the two
    #     real violations and only those two. ---
    scanned = invariant.check_domain_write_scope(scan_root=d)
    check("check_domain_write_scope() over the synthetic directory finds exactly the "
          "two real violations (machine_bad.py, observer_bad.py) and nothing else",
          set(scanned.keys()) == {str(machine_bad), str(observer_bad)})

    # --- domain survives real arbitration unchanged (H1 is a real
    #     field on the type the whole engine already uses, not a
    #     parallel bolt-on that could drift out of sync). ---
    ws = GlobalWorkspace()
    ws.submit(Bid(specialist_id="s", subject="x", score=0.9, domain=Domain.MACHINE))
    winner = ws.arbitrate()
    check("a real arbitration cycle preserves a bid's own domain unchanged",
          winner is not None and winner.domain is Domain.MACHINE)

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
