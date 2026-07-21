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
    python3 scripts/recorder_tools.py label [--archive-dir DIR] [--task TASK]
        (FT.2, docs/AUDIT-2026-07-20.md: automatic quality-label pass —
        prints a per-task aggregate report, doesn't write anything)
    python3 scripts/recorder_tools.py export-sft [--archive-dir DIR]
        [--task TASK] [--require-context-reflected]
        (FT.2: writes the filtered "SFT-eligible" subset as a JSONL
        sidecar under <archive-dir>/exports/ — never touches the
        source archive)
    python3 scripts/recorder_tools.py freeze-eval-set [--archive-dir DIR]
        [--out-dir DIR] [--holdout-fraction F] [--golden-min-size N]
        (FT.5: hash-split train/holdout, build a stratified golden set,
        write baseline diagnostics — writes holdout.jsonl/golden_set.
        jsonl/baseline_diagnostics.json under <out-dir>, default
        <archive-dir>/eval)
    python3 scripts/recorder_tools.py check-regressions --diagnostics FILE
        (FT.5: checks a review_diagnostics.compute_diagnostics(...) JSON
        file — e.g. a review pack's own diagnostics.json, or freeze-eval-
        set's baseline_diagnostics.json from a later candidate run —
        against llm/eval_harness.py's DEFAULT_THRESHOLDS; exits 1 if any
        gate fails)
    python3 scripts/recorder_tools.py synthesize-town-brain --count N
        [--seed N] [--out FILE]
        (FT.4: writes N synthesized town_brain structured_input+prompt
        pairs as JSONL — no gold output attached, see llm/rejection_
        sampling.py or scripts/rejection_sample.py to attach one)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.llm.eval_harness import check_regressions, freeze_eval_set
from hearthmind.llm.prompt_synthesis import synthesize_town_brain_batch
from hearthmind.llm.review_pack import (
    archive_stats, export_random_subset, export_review_pack, export_sft_filter,
    iter_examples, label_archive, validate_archive,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "command",
        choices=[
            "validate", "stats", "export-review-pack", "export-random", "label", "export-sft",
            "freeze-eval-set", "check-regressions", "synthesize-town-brain",
        ],
    )
    parser.add_argument("--archive-dir", default="training_archive")
    parser.add_argument("--task", default=None)
    parser.add_argument("--date-from", default=None)
    parser.add_argument("--date-to", default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument(
        "--require-context-reflected", action="store_true",
        help="export-sft only: also require context_reflected is True (off by default).",
    )
    parser.add_argument("--out-dir", default=None, help="freeze-eval-set only.")
    parser.add_argument("--holdout-fraction", type=float, default=0.1, help="freeze-eval-set only.")
    parser.add_argument("--golden-min-size", type=int, default=50, help="freeze-eval-set only.")
    parser.add_argument("--diagnostics", default=None, help="check-regressions only: path to a diagnostics.json.")
    parser.add_argument("--out", default=None, help="synthesize-town-brain only: output JSONL path.")
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
    elif args.command == "label":
        print(json.dumps(label_archive(args.archive_dir, task=args.task), indent=2))
    elif args.command == "export-sft":
        path = export_sft_filter(
            args.archive_dir, task=args.task, require_context_reflected=args.require_context_reflected,
        )
        print(f"Wrote {path}")
    elif args.command == "freeze-eval-set":
        examples = list(iter_examples(args.archive_dir, task=args.task))
        out_dir = args.out_dir or str(Path(args.archive_dir) / "eval")
        result = freeze_eval_set(
            examples, out_dir, holdout_fraction=args.holdout_fraction, golden_min_size=args.golden_min_size,
        )
        print(json.dumps(
            {k: v for k, v in result.items() if k != "baseline_diagnostics"} | {"out_dir": out_dir},
            indent=2,
        ))
    elif args.command == "check-regressions":
        if not args.diagnostics:
            print("check-regressions requires --diagnostics FILE", file=sys.stderr)
            sys.exit(2)
        with open(args.diagnostics, "r", encoding="utf-8") as fh:
            diagnostics = json.load(fh)
        violations = check_regressions(diagnostics)
        print(json.dumps({"violations": violations}, indent=2))
        sys.exit(1 if violations else 0)
    elif args.command == "synthesize-town-brain":
        batch = synthesize_town_brain_batch(args.count, seed=args.seed)
        out_path = Path(args.out) if args.out else Path(args.archive_dir) / "synthesized" / "town_brain.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            for ex in batch:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print(f"Wrote {len(batch)} synthesized town_brain prompts to {out_path}")


if __name__ == "__main__":
    main()
