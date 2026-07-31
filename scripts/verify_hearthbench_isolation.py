#!/usr/bin/env python3
"""HearthBench import-firewall check (Tier 5 A1.2).

Standalone verification script, not a unittest — per this project's
standing rule ("Do not run the automated test suite or add new unit
tests"), verification here is a real ad-hoc script, same convention
as scripts/verify_native_soak.py / scripts/verify_replay_hash.py.

Mechanically enforces A1's isolation rule: `hearthbench` must never
import from `hearthmind.simulation`/`hearthmind.agents`/
`hearthmind.world` (a benchmark run must never be able to contend
with, pause, or corrupt a live simulation), and `hearthmind` must
never import anything from `hearthbench` (prompt/scorer drift must
flow through a shared contract package, never a live sim import).

Static AST inspection, not a live import — catches every `import`/
`from ... import` statement in every .py file under both packages
without needing either package's runtime dependencies installed.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# hearthmind modules hearthbench must never reach into.
FORBIDDEN_FOR_HEARTHBENCH = ("hearthmind.simulation", "hearthmind.agents", "hearthmind.world")


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _check_package(package_dir: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations = []
    for py_file in sorted(package_dir.rglob("*.py")):
        rel = py_file.relative_to(REPO_ROOT)
        for module in _imported_modules(py_file):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden_prefixes):
                violations.append(f"{rel}: imports {module!r}")
    return violations


def main() -> int:
    hearthbench_dir = REPO_ROOT / "hearthbench"
    hearthmind_dir = REPO_ROOT / "hearthmind"

    violations = []
    violations += _check_package(hearthbench_dir, FORBIDDEN_FOR_HEARTHBENCH)
    violations += _check_package(hearthmind_dir, ("hearthbench",))

    if violations:
        print("HearthBench isolation FAILED — violations found:")
        for v in violations:
            print(f"  - {v}")
        return 1

    hb_files = sorted(hearthbench_dir.rglob("*.py"))
    hm_files = sorted(hearthmind_dir.rglob("*.py"))
    print(f"HearthBench isolation OK — {len(hb_files)} hearthbench files, "
          f"{len(hm_files)} hearthmind files, zero forbidden imports either direction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
