#!/usr/bin/env python3
"""Tier 7 HCA Stage B, B6 (explicit user instruction: "Start B6"):
arbitration determinism and the starvation bound. Three real claims,
each verified mechanically rather than trusted from prose:
(1) identical evidence produces an identical winner across two
independent process runs -- the `verify_replay_hash.py` technique
applied to `hearthmind/cognition/workspace.py`; (2) no RNG appears
anywhere in the arbitration path -- a real AST scan, proven to catch a
genuine violation, not just pass on already-clean code; (3) a
specialist that never wins on merit provably wins within a stated
bounded interval on staleness gain alone -- `staleness_win_bound()`'s
own closed-form formula, checked against many real ratios via a real
`GlobalWorkspace` simulation, not just the one example B2's own test
used.

No unittest, same standalone-script convention as every sibling
`verify_*.py`. Run with `--worker` to execute the deterministic
scenario alone and print its hash (used internally via subprocess for
check 1) -- not a normal invocation.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/hearthmind")

_ROOT = Path("/home/user/hearthmind")
_WORKSPACE_MODULE_PATH = _ROOT / "hearthmind" / "cognition" / "workspace.py"

_BANNED_RNG_MODULES = {"random", "numpy", "numpy.random", "secrets", "uuid"}

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def _deterministic_scenario_hash() -> str:
    """A fixed sequence of `Bid` submissions/`arbitrate()` calls over
    several settlement-shaped subjects, no external input, no RNG --
    every score is a pure function of `(cycle, specialist_index)`."""
    from hearthmind.cognition.workspace import Bid, GlobalWorkspace

    ws = GlobalWorkspace()
    subjects = ["food_shortage", "predator_extinction", "guild_decline", "family_extinction", "diplomatic_hostility"]
    records = []
    for cycle in range(60):
        for i, subject in enumerate(subjects):
            score = ((cycle * 7 + i * 13) % 97) / 97.0
            ws.submit(Bid(specialist_id=f"specialist_{i}", subject=subject, score=score))
        winner = ws.arbitrate()
        records.append({
            "cycle": cycle,
            "winner": None if winner is None else
                {"specialist_id": winner.specialist_id, "subject": winner.subject, "score": winner.score},
        })
    payload = json.dumps(records, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _no_banned_rng_imports(module_path: Path) -> bool:
    """AST scan (same technique `scripts/verify_runtime_invariant.py`
    already established elsewhere in this codebase): walks every real
    `Import`/`ImportFrom` node, rejecting any of the banned RNG-
    producing modules regardless of how it's imported (`import random`,
    `from random import choice`, `import numpy.random as npr`, ...)."""
    tree = ast.parse(module_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _BANNED_RNG_MODULES:
                    return False
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _BANNED_RNG_MODULES:
                return False
    return True


def main() -> int:
    if "--worker" in sys.argv:
        print(_deterministic_scenario_hash())
        return 0

    from hearthmind.cognition.workspace import Bid, GlobalWorkspace, staleness_win_bound

    # --- claim 1: identical evidence -> identical winner across two
    #     REAL, independent process runs (real subprocess isolation,
    #     the same reason verify_replay_hash.py insists on it -- hash
    #     randomization/scheduling jitter can only ever surface across
    #     a real process boundary, never within one). ---
    hashes = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            capture_output=True, text=True, check=True, cwd=str(_ROOT),
        )
        hashes.append(result.stdout.strip())
    check("both independent process runs produced real, non-empty output",
          all(h for h in hashes))
    check(
        "identical evidence produces an identical winner sequence across two independent "
        "process runs (the verify_replay_hash.py technique, applied to the workspace)",
        hashes[0] == hashes[1],
    )

    # --- claim 2: no RNG anywhere in the arbitration path -- proven to
    #     genuinely catch a violation, not just pass on clean code. ---
    check("the real workspace.py module imports no banned RNG-producing module",
          _no_banned_rng_imports(_WORKSPACE_MODULE_PATH))

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
        tf.write("import random\n\ndef pick(bids):\n    return random.choice(bids)\n")
        synthetic_path = Path(tf.name)
    try:
        check("the AST scan genuinely CATCHES a real violation, not just passes on clean code",
              _no_banned_rng_imports(synthetic_path) is False)
    finally:
        synthetic_path.unlink()

    # --- claim 3: the staleness bound is a real closed-form guarantee,
    #     checked against MANY real ratios (not just B2's own one 9x
    #     example) via a real GlobalWorkspace simulation. `strong` is
    #     always submitted FIRST each cycle -- this removes tie-break-
    #     order ambiguity entirely (a tie always resolves to `strong`,
    #     per the module's own deterministic submission-order rule),
    #     so any real win by `weak` can only ever come from genuinely
    #     STRICTLY exceeding `strong`'s score, matching `staleness_win_
    #     bound`'s own literal "first strictly exceeds" contract with
    #     zero order-dependent slack. Because staleness applied on
    #     cycle `c` reflects `c - 1` PRIOR losses, the real win cycle
    #     is `bound + 1`, not `bound` itself -- `bound` is the loss
    #     COUNT the formula guarantees is enough, not a cycle number. ---
    ratio_pairs = [(0.1, 0.9), (0.1, 0.2), (0.05, 1.0), (0.3, 0.9), (0.02, 0.5)]
    all_bounds_exact = True
    for weak_score, strong_score in ratio_pairs:
        bound = staleness_win_bound(weak_score, strong_score)
        ws = GlobalWorkspace()
        first_win_cycle = None
        for cycle in range(1, bound + 5):
            ws.submit(Bid(specialist_id="strong", subject="strong_subject", score=strong_score))
            ws.submit(Bid(specialist_id="weak", subject="weak_subject", score=weak_score))
            winner = ws.arbitrate()
            if winner.subject == "weak_subject":
                first_win_cycle = cycle
                break
        if first_win_cycle != bound + 1:
            all_bounds_exact = False
    check(
        "staleness_win_bound()'s own predicted loss count matches EXACTLY where a real "
        "simulated win happens (cycle bound+1, since staleness reflects prior losses), "
        "across five real (weak, strong) score ratios -- not merely 'eventually'",
        all_bounds_exact,
    )

    # --- the bound is a genuine LOWER bound too: the weak bid never
    #     wins any cycle strictly before its own predicted bound. ---
    weak_score, strong_score = 0.1, 0.9
    bound = staleness_win_bound(weak_score, strong_score)
    ws2 = GlobalWorkspace()
    premature_win = False
    for cycle in range(1, bound + 1):
        ws2.submit(Bid(specialist_id="strong", subject="strong_subject", score=strong_score))
        ws2.submit(Bid(specialist_id="weak", subject="weak_subject", score=weak_score))
        if ws2.arbitrate().subject == "weak_subject":
            premature_win = True
            break
    check("the bound is a genuine lower bound -- the weak bid never wins any cycle before it",
          not premature_win)

    # --- edge cases: already-winning/tied returns 0; non-positive
    #     weak_score has no finite bound (raises, doesn't lie) ---
    check("a weak bid already at or above the rival's score needs 0 staleness cycles",
          staleness_win_bound(0.9, 0.5) == 0 and staleness_win_bound(0.5, 0.5) == 0)
    raised = False
    try:
        staleness_win_bound(0.0, 0.5)
    except ValueError:
        raised = True
    check("a non-positive weak_score raises rather than returning a false finite bound", raised)

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
