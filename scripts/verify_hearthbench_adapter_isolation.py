#!/usr/bin/env python3
"""HearthBench A2.2's own lint rule: "Adapters are the only place
model-specific logic may live — enforce with a lint rule banning
model-name string comparisons outside `adapters/`."

Static AST inspection (same standalone-script convention as `verify_
hearthbench_isolation.py`/`verify_runtime_invariant.py`, no unittest):
flags any string literal containing a known model-family name
substring (nemotron/qwen/llama/gemma/gpt/claude/mistral/mixtral/phi/
deepseek — case-insensitive) used as an operand of a comparison
(`==`, `!=`, `in`, `not in`) anywhere under `hearthbench/` OUTSIDE
`hearthbench/adapters/`. A benchmark category/prompt file NAMING a
model in a comment, docstring, or a plain non-comparison string (a
log message, a report label) is not itself model-specific *logic* —
only a literal being *branched on* is, so this deliberately checks
comparison operands specifically rather than every string literal
containing one of these substrings.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL_FAMILY_SUBSTRINGS = (
    "nemotron", "qwen", "llama", "gemma", "gpt", "claude",
    "mistral", "mixtral", "phi-", "deepseek",
)


def _string_constants_in_compare_operands(tree: ast.AST):
    """Yields every `ast.Constant` string literal that appears as one
    of a `Compare` node's `left`/`comparators` operands, anywhere a
    `==`/`!=`/`In`/`NotIn` op is used — the shape a "branch on this
    model's name" check takes, regardless of how deeply nested the
    comparison is inside other expressions."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        has_membership_or_equality_op = any(
            isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops
        )
        if not has_membership_or_equality_op:
            continue
        operands = [node.left, *node.comparators]
        for operand in operands:
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                yield node.lineno, operand.value
            # `"qwen" in name.lower()` -- the literal is a Constant
            # directly; `.lower()`/`.upper()` calls on the OTHER side
            # don't change the literal itself, so no special-casing
            # is needed beyond the direct Constant check above.


def _check_file(path: Path) -> list[str]:
    violations = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for lineno, literal in _string_constants_in_compare_operands(tree):
        lowered = literal.lower()
        for substring in MODEL_FAMILY_SUBSTRINGS:
            if substring in lowered:
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}:{lineno}: compares against {literal!r} (matches {substring!r})")
                break
    return violations


def main() -> int:
    hearthbench_dir = REPO_ROOT / "hearthbench"
    adapters_dir = hearthbench_dir / "adapters"

    violations: list[str] = []
    checked = 0
    for py_file in sorted(hearthbench_dir.rglob("*.py")):
        if adapters_dir in py_file.parents or py_file.parent == adapters_dir:
            continue
        checked += 1
        violations += _check_file(py_file)

    if violations:
        print("HearthBench adapter-isolation lint FAILED — model-name comparisons found outside adapters/:")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(f"HearthBench adapter-isolation lint OK — {checked} non-adapter files checked, zero model-name comparisons.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
