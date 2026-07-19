#!/usr/bin/env python3
"""Validation + export utility for the permanent LLM training recorder's
on-disk archive (hearthmind/llm/recorder.py, §8). Spec: "Provide tools
to validate JSON, validate schema, count records, detect corruption,
report statistics, export random subsets, export task subsets, and
export date ranges." Standalone script, not a pytest suite — matches
this project's standing "no automated test suite" convention
(CLAUDE.md); this is the ad-hoc/reusable tool that convention calls for.

Usage:
    python3 scripts/recorder_tools.py validate [--archive-dir DIR]
    python3 scripts/recorder_tools.py stats [--archive-dir DIR]
    python3 scripts/recorder_tools.py export-review-pack [--archive-dir DIR]
        [--task TASK] [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
        [--limit N] [--markdown]
    python3 scripts/recorder_tools.py export-random [--archive-dir DIR]
        [--task TASK] [--count N] [--seed N] [--markdown]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.llm.review_pack import archive_stats, export_random_subset, export_review_pack, validate_archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["validate", "stats", "export-review-pack", "export-random"])
    parser.add_argument("--archive-dir", default="training_archive")
    parser.add_argument("--task", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    if args.command == "validate":
        result = validate_archive(args.archive_dir)
        print(json.dumps(result, indent=2))
        sys.exit(1 if result["error_count"] else 0)
    elif args.command == "stats":
        print(json.dumps(archive_stats(args.archive_dir), indent=2))
    elif args.command == "export-review-pack":
        path = export_review_pack(
            args.archive_dir, task=args.task, date_from=args.date_from, date_to=args.date_to,
            limit=args.limit, markdown=args.markdown,
        )
        print(f"Wrote {path}")
    elif args.command == "export-random":
        path = export_random_subset(
            args.archive_dir, count=args.count, task=args.task, seed=args.seed, markdown=args.markdown,
        )
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
