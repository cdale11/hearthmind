#!/usr/bin/env python3
"""HearthBench A3.1's own "`hearthbench export` command" — reads a real
`hearthmind.llm.recorder` archive and writes a frozen, versioned,
checked-in fixture pack. Same standalone-CLI convention as `scripts/
recorder_tools.py`.

Usage:
    python3 scripts/hearthbench_export.py fixtures \\
        --archive-dir /path/to/recorder/archive \\
        --output-dir hearthbench/prompts/fixtures \\
        --version v1 [--max-per-task 20] [--seed 0]

    python3 scripts/hearthbench_export.py fixtures-synthetic \\
        --output-dir hearthbench/prompts/fixtures \\
        --version v1 --task town_brain --count 20 [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthbench.prompts import (
    export_fixture_pack,
    load_fixture_pack,
    synthesize_town_brain_fixtures,
)

_SYNTHESIZERS = {"town_brain": synthesize_town_brain_fixtures}


def _cmd_fixtures(args: argparse.Namespace) -> int:
    manifest = export_fixture_pack(
        args.archive_dir, args.output_dir, args.version,
        max_per_task=args.max_per_task, seed=args.seed,
    )
    print(json.dumps(manifest, indent=2))
    return 0


def _cmd_fixtures_synthetic(args: argparse.Namespace) -> int:
    synthesizer = _SYNTHESIZERS.get(args.task)
    if synthesizer is None:
        print(f"hearthbench_export.py: no synthesizer registered for task {args.task!r} "
              f"(available: {sorted(_SYNTHESIZERS)})", file=sys.stderr)
        return 1
    fixtures = synthesizer(args.count, args.seed)
    pack_dir = Path(args.output_dir) / args.version
    pack_dir.mkdir(parents=True, exist_ok=True)
    task_path = pack_dir / f"{args.task}.json"
    existing = [f.to_dict() for f in load_fixture_pack(args.output_dir, args.version, task=args.task)]
    combined = existing + [f.to_dict() for f in fixtures]
    with open(task_path, "w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=2, sort_keys=True)
    print(f"wrote {len(fixtures)} synthetic fixtures for task={args.task!r} "
          f"({len(combined)} total in {task_path})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fixtures_parser = subparsers.add_parser("fixtures", help="Export a frozen fixture pack from a real recorder archive.")
    fixtures_parser.add_argument("--archive-dir", required=True)
    fixtures_parser.add_argument("--output-dir", required=True)
    fixtures_parser.add_argument("--version", required=True)
    fixtures_parser.add_argument("--max-per-task", type=int, default=20)
    fixtures_parser.add_argument("--seed", type=int, default=0)
    fixtures_parser.set_defaults(func=_cmd_fixtures)

    synth_parser = subparsers.add_parser(
        "fixtures-synthetic", help="Append synthetic (A3.4) fixtures for one task to an existing/new pack.",
    )
    synth_parser.add_argument("--output-dir", required=True)
    synth_parser.add_argument("--version", required=True)
    synth_parser.add_argument("--task", required=True)
    synth_parser.add_argument("--count", type=int, default=20)
    synth_parser.add_argument("--seed", type=int, default=None)
    synth_parser.set_defaults(func=_cmd_fixtures_synthetic)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
