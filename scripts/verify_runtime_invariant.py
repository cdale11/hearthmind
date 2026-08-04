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

**H1 extension (Tier 7 HCA Stage H, explicit user instruction: "Start
phase 3.5 W1 and a parallel task of your choice with biggest impact"):
`check_domain_write_scope()` mechanically enforces the OTHER half of
H1's own stated test — "no MACHINE- or OBSERVER-domain code path
writes `world/`/`agents/`/`settlement/`/`economy/` state." Where the
check above governs by DIRECTORY (any file physically under `world/`
etc. may never import threading), this one governs by DOMAIN MARKER: a
module hosting a MACHINE- or OBSERVER-domain specialist/resolver
(`hearthmind.cognition.workspace.Domain`) declares a module-level
`SPECIALIST_DOMAIN = Domain.MACHINE` (or `.OBSERVER`) constant, and
this check verifies that module never imports from `hearthmind.world`/
`hearthmind.agents`/`hearthmind.settlement`/`hearthmind.economy` at
all — the same "zero import, not just zero write" discipline `scripts/
verify_hearthbench_isolation.py` already established for the
structurally identical problem of proving one part of this codebase
never reaches into another. No real MACHINE/OBSERVER-domain module
exists in production yet (that's H2/H4's later job) — this check scans
the WHOLE `hearthmind/` tree today and correctly finds nothing to flag;
its own genuine ability to catch a real violation is proven by `scripts/
verify_h1_cognitive_domains.py` against a synthetic marked file."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories the prime invariant governs (gameplay/domain logic).
GOVERNED_DIRS = ("world", "agents", "settlement", "economy")

# H1: the module-level constant name a MACHINE/OBSERVER-domain module
# declares itself with, and the two domain values that trigger the
# write-scope check (WORLD is exempt — it's expected to touch world
# state).
DOMAIN_MARKER_NAME = "SPECIALIST_DOMAIN"
RESTRICTED_DOMAIN_ATTRS = ("MACHINE", "OBSERVER")

# H1: the packages a MACHINE/OBSERVER-domain module may never import
# from — the real gameplay-state packages the prime invariant's own
# GOVERNED_DIRS above name, referenced by their real import path.
WRITE_FORBIDDEN_PACKAGES = (
    "hearthmind.world", "hearthmind.agents", "hearthmind.settlement", "hearthmind.economy",
)

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


def _declared_domain(tree: ast.AST) -> str | None:
    """H1: find a real top-level `SPECIALIST_DOMAIN = Domain.<X>`
    assignment (module-level only, per the marker convention — a
    domain declared inside a function/class body doesn't describe the
    whole module) and return `<X>` (`"MACHINE"`/`"OBSERVER"`/`"WORLD"`)
    if present, else `None`. Deliberately tolerant of the exact import
    alias `Domain` was given (`ast.Attribute` on any name, not
    hard-coded to `Domain` specifically) — a synthetic test file can
    import it under any alias and still be recognized correctly."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == DOMAIN_MARKER_NAME for t in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Attribute):
            return value.attr
    return None


def _domain_write_violations_in_file(path: Path) -> list[str]:
    """H1's own real check: a module declaring itself MACHINE- or
    OBSERVER-domain (via `SPECIALIST_DOMAIN`) may never import from any
    of `WRITE_FORBIDDEN_PACKAGES` — the real gameplay-state packages
    the prime invariant's own `GOVERNED_DIRS` name. WORLD-domain (or
    undeclared) modules are exempt — WORLD is expected to read/write
    world state, that's the entire point of the domain."""
    tree = ast.parse(path.read_text(), filename=str(path))
    domain = _declared_domain(tree)
    if domain not in RESTRICTED_DOMAIN_ATTRS:
        return []
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == p or alias.name.startswith(p + ".") for p in WRITE_FORBIDDEN_PACKAGES):
                    violations.append(
                        f"line {node.lineno}: {domain}-domain module imports {alias.name!r}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if any(node.module == p or node.module.startswith(p + ".") for p in WRITE_FORBIDDEN_PACKAGES):
                violations.append(
                    f"line {node.lineno}: {domain}-domain module imports from {node.module!r}"
                )
    return violations


def check_domain_write_scope(scan_root: Path | None = None) -> dict[str, list[str]]:
    """H1's public entry point (importable directly, same convention
    `verify_hearthbench_isolation.py`'s own checker function follows,
    for a future `full_diagnostics()`/CI consumer or a sibling verify
    script to reuse without re-parsing the whole tree). Scans every
    `.py` file under `hearthmind/` (NOT scoped to `GOVERNED_DIRS` —
    a MACHINE/OBSERVER-domain module is expected to live OUTSIDE
    `world/`/`agents/`/`settlement/`/`economy/`, so this check must
    range wider than the directory-scoped one above) for a real
    `SPECIALIST_DOMAIN` marker and, where found and restricted,
    verifies its imports. Returns `{relative_path: [violations]}` —
    empty when clean, same shape `_violations_in_file`'s caller uses."""
    root = scan_root if scan_root is not None else (REPO_ROOT / "hearthmind")
    violations: dict[str, list[str]] = {}
    for py_file in sorted(root.rglob("*.py")):
        file_violations = _domain_write_violations_in_file(py_file)
        if file_violations:
            rel = py_file.relative_to(REPO_ROOT) if root.is_relative_to(REPO_ROOT) else py_file
            violations[str(rel)] = file_violations
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

    # H1: the domain write-scope check, over the whole hearthmind/ tree.
    domain_violations = check_domain_write_scope()
    if domain_violations:
        print("H1 domain write-scope FAILED — violations found:")
        for rel, violations in domain_violations.items():
            for v in violations:
                print(f"  - {rel}: {v}")
        return 1
    print("H1 domain write-scope OK — no MACHINE/OBSERVER-domain module "
          "imports world/agents/settlement/economy state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
