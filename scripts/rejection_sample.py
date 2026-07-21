#!/usr/bin/env python3
"""FT.3 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap), no-teacher
gold-target generation: for each prompt in an input JSONL, sample k
completions from a real local LLM server at a spread of temperatures,
score each with `llm/quality_labels.py` (FT.2), keep the best as the
gold target, and bank (chosen, rejected) pairs for a later DPO pass.
See `hearthmind/llm/rejection_sampling.py` for the actual sampling/
scoring logic — this script is just the CLI/IO wrapper around it,
matching this project's standing "no test suite, ad-hoc standalone
scripts instead" convention (CLAUDE.md), same shape as
`scripts/verify_native_soak.py`/`scripts/recorder_tools.py`.

Unlike `scripts/recorder_tools.py` (archive-only, no live LLM needed),
this script makes real network calls to a running llama-server/Ollama
— it needs the same `--llm-*` flags `hearthmind.server` takes, and
will do nothing useful if no server is reachable at the given host.

Input JSONL: one record per line, accepting either shape —
  - `{"task", "prompt", "system_prompt", "structured_input"}` (what
    `hearthmind.llm.prompt_synthesis.synthesize_town_brain_batch`
    writes, and what `scripts/recorder_tools.py synthesize-town-brain`
    saves to disk), or
  - `{"task", "layer2_prompt", "layer2_system_prompt",
    "layer1_structured_input"}` (a real archive record's own shape,
    e.g. from `scripts/recorder_tools.py export-sft`'s output, letting
    you re-sample better completions for prompts you already have).

Output JSONL: one banked (chosen, rejected) preference-pair record per
input prompt that produced a real preference (see `bank_preference_
pair`'s own "no preference signal" skip condition) — never the raw
per-candidate output, since that's already recoverable by re-running
this script with the same prompt if needed, and the bank is what a
DPO pass actually consumes.

Usage:
    python3 scripts/rejection_sample.py --input prompts.jsonl --out pairs.jsonl
        [--k 4] [--llm-backend llamacpp] [--llm-llamacpp-host URL]
        [--llm-host URL] [--llm-model NAME] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.config import Config  # noqa: E402
from hearthmind.llm.client import build_llm_client  # noqa: E402
from hearthmind.llm.rejection_sampling import bank_preference_pair, sample_and_select  # noqa: E402


def _normalize_record(record: dict) -> dict:
    """Accepts either the `prompt_synthesis`/`synthesize-town-brain`
    shape or a real archive record's `layerN_*` shape; returns the
    flat `{"task", "prompt", "system_prompt", "structured_input"}`
    shape `sample_and_select`/`bank_preference_pair` expect."""
    if "layer2_prompt" in record:
        return {
            "task": record.get("task"),
            "prompt": record.get("layer2_prompt"),
            "system_prompt": record.get("layer2_system_prompt"),
            "structured_input": record.get("layer1_structured_input") or {},
        }
    return {
        "task": record.get("task"),
        "prompt": record.get("prompt"),
        "system_prompt": record.get("system_prompt"),
        "structured_input": record.get("structured_input") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="Input JSONL of prompts to sample against.")
    parser.add_argument("--out", required=True, help="Output JSONL of banked preference pairs.")
    parser.add_argument("--k", type=int, default=4, help="Completions to sample per prompt (default 4).")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N input records.")
    parser.add_argument("--llm-backend", choices=["llamacpp", "ollama"], default=Config.llm_backend)
    parser.add_argument("--llm-llamacpp-host", default=Config.llm_llamacpp_host)
    parser.add_argument("--llm-host", default=Config.llm_host)
    parser.add_argument("--llm-model", default=Config.llm_model)
    parser.add_argument("--llm-timeout", type=float, default=Config.llm_timeout_seconds)
    args = parser.parse_args()

    config = Config(
        llm_backend=args.llm_backend, llm_llamacpp_host=args.llm_llamacpp_host,
        llm_host=args.llm_host, llm_model=args.llm_model, llm_timeout_seconds=args.llm_timeout,
        llm_enabled=True,
    )
    client = build_llm_client(config)

    with open(args.input, "r", encoding="utf-8") as fh:
        raw_records = [json.loads(line) for line in fh if line.strip()]
    if args.limit is not None:
        raw_records = raw_records[: args.limit]

    banked = 0
    skipped_no_preference = 0
    skipped_all_failed = 0
    with open(args.out, "w", encoding="utf-8") as out_fh:
        for i, raw in enumerate(raw_records):
            record = _normalize_record(raw)
            if not record["task"] or not record["prompt"]:
                continue
            result = sample_and_select(
                client, record["prompt"], record["system_prompt"], record["task"],
                structured_input=record["structured_input"], k=args.k,
            )
            if result["chosen"] is None:
                skipped_all_failed += 1
                print(f"[{i + 1}/{len(raw_records)}] {record['task']}: all {args.k} calls failed", file=sys.stderr)
                continue
            pair = bank_preference_pair(record, result)
            if pair is None:
                skipped_no_preference += 1
                print(
                    f"[{i + 1}/{len(raw_records)}] {record['task']}: no distinct rejected candidate, skipped",
                    file=sys.stderr,
                )
                continue
            out_fh.write(json.dumps(pair, ensure_ascii=False, default=str) + "\n")
            banked += 1
            print(
                f"[{i + 1}/{len(raw_records)}] {record['task']}: banked "
                f"(chosen sft_eligible={pair['chosen_labels']['sft_eligible']}, "
                f"{len(pair['rejected'])} rejected)",
                file=sys.stderr,
            )

    print(json.dumps({
        "total_input": len(raw_records), "banked": banked,
        "skipped_no_preference": skipped_no_preference, "skipped_all_failed": skipped_all_failed,
        "out": args.out,
    }, indent=2))


if __name__ == "__main__":
    main()
