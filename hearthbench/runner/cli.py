"""HearthBench A1.3 — the real, minimal CLI entry point a bench run
subprocess actually launches (`python -m hearthbench.runner.cli run
...`). Deliberately small: one subcommand, one real runnable category
(`grounding` — the one category whose own `TestCase`s carry a real
executable prompt with no fixture pack needed, same reason `hearthbench.
reporting.ci_guard.build_default_ci_cases` reuses it exclusively).
Structured-outputs/performance need a real fixture pack or an existing
category's own cases to attach a `latency` scorer to respectively —
real, distinct future work extending `_cases_for_category`, not
attempted here.

Every real function this module calls is already production code
exercised by this package's own sibling scripts (`run_cases_with_
resume`, `build_environment_snapshot`, `build_grounding_bait_cases`)
— this file is orchestration, not new logic, which is exactly what
lets `hearthbench.runner.process.BenchRunProcess` treat "launch a real
Python subprocess running this module" as a genuine, testable process-
isolation boundary rather than a parallel reimplementation.

Import isolation (A1.2): stdlib + `hearthbench.*` only.
"""
from __future__ import annotations

import argparse
import os
import sys

from hearthbench.adapters import OpenAICompatAdapter
from hearthbench.diagnostics import build_environment_snapshot
from hearthbench.runner.run import run_cases_with_resume
from hearthbench.scoring import DEFAULT_REGISTRY
from hearthbench.tests import build_grounding_bait_cases

CATEGORY_BUILDERS = {
    "grounding": build_grounding_bait_cases,
}


def _cases_for_category(category: str) -> list:
    if category not in CATEGORY_BUILDERS:
        raise ValueError(
            f"unsupported category for CLI runs: {category!r} "
            f"(only {sorted(CATEGORY_BUILDERS)} have runnable prompts of their own; "
            "other categories need a real fixture pack, not attempted here)"
        )
    return CATEGORY_BUILDERS[category]()


def _build_adapter(args: argparse.Namespace) -> OpenAICompatAdapter:
    return OpenAICompatAdapter(
        endpoint=args.adapter_endpoint, model=args.adapter_model,
        api_key=args.adapter_api_key, quantization=args.adapter_quantization,
        context=args.adapter_context,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hearthbench.runner.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a real HearthBench category against a real adapter.")
    run_parser.add_argument("--category", default="grounding", choices=sorted(CATEGORY_BUILDERS))
    run_parser.add_argument("--run-dir", required=True)
    run_parser.add_argument("--adapter-endpoint", required=True)
    run_parser.add_argument("--adapter-model", required=True)
    run_parser.add_argument("--adapter-api-key", default=None)
    run_parser.add_argument("--adapter-quantization", default=None)
    run_parser.add_argument("--adapter-context", type=int, default=None)
    return parser


def main(argv: "list | None" = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "run":
        cases = _cases_for_category(args.category)
        adapter = _build_adapter(args)
        run_id = os.path.basename(os.path.normpath(args.run_dir))
        # A12's daemon (hearthbench.daemon.server) reads these back out
        # of a real run's own manifest.json to compute progress/crashed
        # honestly for ANY run it discovers on disk — including one it
        # didn't itself launch, or one launched before the daemon process
        # that's now browsing it even started. Real, already-decided-here
        # data, not re-derived or guessed at read time.
        environment = build_environment_snapshot(
            adapter, run_id=run_id,
            extra={"category": args.category, "expected_case_ids": [c.id for c in cases]},
        )
        run_cases_with_resume(cases, adapter, DEFAULT_REGISTRY, args.run_dir, environment=environment)
        return 0

    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
