#!/usr/bin/env python3
"""Adaptive Runtime prime-invariant check (Tier 5 B0.2).

Standalone verification script, not a unittest — per this project's
standing rule ("Do not run the automated test suite or add new unit
tests"), same convention as scripts/verify_hearthbench_isolation.py /
verify_native_soak.py / verify_replay_hash.py — run manually, no CI
pipeline exists in this repo to wire it into yet.

Mechanically enforces B0's prime invariant (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Part B): "gameplay systems declare *what* work exists.
The runtime decides *when*, *where*, and *how* it executes." Concretely
this bans `threading`/`concurrent.futures` imports, `time.sleep` calls,
and executor construction inside `world/`, `agents/`, `settlement/`,
`economy/` — those are execution-layer concerns that belong to the tick
loop (`simulation/engine.py`) and, once B1-B15 exist, the future task
scheduler, never to a subsystem describing its own domain logic.

Static AST inspection, not a live import — catches every `import`/
`from ... import` statement and every `time.sleep(...)` call site
without needing the package's runtime dependencies installed.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories the prime invariant governs (gameplay/domain logic).
GOVERNED_DIRS = ("world", "agents", "settlement", "economy")

# Modules a governed file may never import.
FORBIDDEN_MODULES = ("threading", "concurrent.futures", "concurrent")

# Executor/threading-primitive constructor names forbidden as calls,
# however they were imported (e.g. `from concurrent.futures import
# ThreadPoolExecutor` then `ThreadPoolExecutor(...)`).
FORBIDDEN_CALL_NAMES = (
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "Thread",
    "Timer",
)


def _violations_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_MODULES:
                    violations.append(f"line {node.lineno}: imports {alias.name!r}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in FORBIDDEN_MODULES or any(
                node.module == m or node.module.startswith(m + ".") for m in FORBIDDEN_MODULES
            ):
                violations.append(f"line {node.lineno}: imports from {node.module!r}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in FORBIDDEN_CALL_NAMES:
                violations.append(f"line {node.lineno}: calls {name}(...)")
            # time.sleep(...) specifically — `time` itself is fine (used
            # for wall-clock reads), only the blocking-sleep call is banned.
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "sleep"
                and isinstance(func.value, ast.Name)
                and func.value.id == "time"
            ):
                violations.append(f"line {node.lineno}: calls time.sleep(...)")

    return violations


def main() -> int:
    all_violations: dict[str, list[str]] = {}
    file_count = 0
    for dirname in GOVERNED_DIRS:
        governed_dir = REPO_ROOT / "hearthmind" / dirname
        if not governed_dir.is_dir():
            continue
        for py_file in sorted(governed_dir.rglob("*.py")):
            file_count += 1
            violations = _violations_in_file(py_file)
            if violations:
                rel = py_file.relative_to(REPO_ROOT)
                all_violations[str(rel)] = violations

    if all_violations:
        print("Runtime invariant FAILED — violations found:")
        for rel, violations in all_violations.items():
            for v in violations:
                print(f"  - {rel}: {v}")
        return 1

    print(f"Runtime invariant OK — {file_count} files under "
          f"{', '.join(GOVERNED_DIRS)}, zero threading/sleep/executor use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
