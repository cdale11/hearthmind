#!/usr/bin/env python3
"""B10.2 discovery scanner (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, Locality). Standalone script, same convention as `verify_
runtime_invariant.py`: static AST inspection, no unittest, no CI
pipeline exists in this repo to wire it into — run manually.

**This is the DISCOVERY tool a real B10.2 audit would use, not the
audit itself.** Converting a flagged loop to a region-indexed query
needs individual live judgment per site (is it genuinely hot? does an
index already exist to query instead? is O(population) actually fine
here because it only runs monthly?) — the same "needs judgment, not a
mechanism" class as B3.3/B9.3's own audit deferrals. This script never
fails the run (informational only) and never claims a flagged loop is
actually a problem — it just makes candidates easy to find instead of
requiring a manual `grep` sweep.

Two candidate patterns, both heuristic:
  1. `for X in <expr>.<attr>` where `<attr>` is one of a known set of
     full-collection names (agents, buildings, tiles, nodes, ...) —
     candidate O(population) or O(map-size) scan.
  2. A `for ... in range(...)` loop directly nested inside another
     `for ... in range(...)` loop — candidate full-grid double-loop
     (the classic `for x in range(width): for y in range(height)`
     shape).
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

GOVERNED_DIRS = ("world", "agents", "settlement", "economy")

FULL_COLLECTION_ATTRS = (
    "agents", "buildings", "tiles", "nodes", "herds", "vehicles",
    "institutions", "settlements", "resources", "farms",
)


def _governed_files() -> list:
    files = []
    for d in GOVERNED_DIRS:
        base = REPO_ROOT / "hearthmind" / d
        if base.is_dir():
            files.extend(sorted(base.rglob("*.py")))
    return files


def _scan_file(path: Path) -> list:
    findings = []
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return findings

    for_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
    for_node_ids = {id(n) for n in for_nodes}

    for node in for_nodes:
        if isinstance(node.iter, ast.Attribute) and node.iter.attr in FULL_COLLECTION_ATTRS:
            findings.append(
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: candidate full-collection scan "
                f"(iterates '.{node.iter.attr}')"
            )
        if _is_range_call(node.iter):
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, ast.For) and id(child) in for_node_ids and _is_range_call(child.iter):
                    findings.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: candidate full-grid double loop "
                        f"(nested range() loop at line {child.lineno})"
                    )
                    break

    return findings


def _is_range_call(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range"


def main() -> None:
    all_findings = []
    for path in _governed_files():
        all_findings.extend(_scan_file(path))

    print(f"Scanned {len(_governed_files())} files under {GOVERNED_DIRS}.")
    print(f"{len(all_findings)} candidate global-scan site(s) found (informational only, not a failure):\n")
    for finding in all_findings:
        print(f"  {finding}")

    if not all_findings:
        print("  (none)")

    print(
        "\nThis is a discovery pass, not an audit verdict — each finding needs live "
        "judgment (B10.2) before deciding whether/how to convert it. Exit code is "
        "always 0; nothing here blocks anything."
    )


if __name__ == "__main__":
    main()
