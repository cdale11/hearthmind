# LLM Training Recorder & Dataset Pipeline

Permanent, production-grade infrastructure for recording every real LLM
task the simulation runs into a durable, append-only JSONL corpus —
built for future SFT/DPO/evaluation/regression/prompt-research use, and
as the data-collection prerequisite for §8's LoRA/QLoRA idea
(docs/IDEAS-2026-07-EMERGENCE.md). The LoRA fine-tuning run itself is
NOT implemented here — only the recorder that would feed it.

Implements the user-supplied "Hearthmind Permanent LLM Training
Recorder & Dataset Pipeline Specification" (see CHANGELOG.md for the
version this landed in).

## OFF by default

Recording never happens unless explicitly started — `POST
/recorder/start` (or the browser UI's "⚙ dev" → LLM training recorder
panel) — and can be stopped at any time (`POST /recorder/stop`). No
config flag turns it on; `Config.recorder_archive_dir` only says WHERE
it would write, not whether it's active.

## Architecture

```
Simulation (_record_llm_debug, the one call site every LLM task
already funnels through)
        |
        v
TrainingRecorder.maybe_record()  — builds one dict, never blocks
        |
        v
queue.Queue (bounded, QUEUE_MAX=5000)  — put_nowait, drops oldest-costly on full
        |
        v
Background OS thread (_writer_loop)  — the only thing that touches disk
        |
        v
JSONL archive: <archive_dir>/<task>/<date>.jsonl
```

Recording never touches the simulation's asyncio event loop — it's a
plain `queue.Queue` + a daemon `threading.Thread`, so a slow/stalled
disk can never stall a tick. `maybe_record`'s own cost when recording
is OFF is one enum comparison.

## Four-layer record

Every JSONL line is one `TrainingExample` (`hearthmind/llm/
recorder.py`):

1. **`layer1_structured_input`** — the structured simulation input
   before prompt rendering. Populated for every task explicitly named
   in the spec's own scope list (cognition, dialogue, beliefs, dreams,
   chronicles, diplomacy, consciousness, naming, folklore, caravans,
   town brain) plus `rumor_interpret`; defaults to `{}` for any other
   settlement job not yet wired with a bespoke structured-input payload
   — a known, flagged scope trim (see CHANGELOG.md), not silently
   faked. Wiring a new job's structured input is a one-line addition at
   its `_schedule_llm_job(...)` call site (`structured_input=...`).
2. **`layer2_prompt`** / **`layer2_system_prompt`** — the exact
   rendered prompt sent to the model.
3. **`layer3_raw_completion`** — the exact raw text the model returned,
   before JSON parsing, captured via an optional `capture: dict`
   side-channel threaded through `OllamaClient`/`LlamaCppClient.
   generate_json` (never a shared/instance attribute — safe under
   `Config.llm_max_concurrent` > 1). `None` on any fallback resolution
   (no real completion exists to record).
4. **`layer4_parsed_output`** — the validated parsed JSON dict (or the
   deterministic fallback dict, on a fallback resolution —
   `fallback_used` distinguishes the two).

`parse_repaired` exists in the schema for a future JSON-repair step;
this codebase has none today (a parse failure raises `LLMUnavailable`
and falls back), so it is currently always `false`.

## Metadata

`schema_version`, `recorder_version`, `hearthmind_version`, `session_id`,
`session_name`, `task`, `timestamp`, `simulation_tick`, `settlement`,
`npc_ids`, `model_name`, `latency_ms`, `estimated_prompt_tokens`/
`estimated_completion_tokens` (char/4 estimate, same convention
`llm_prompt_stats_summary` already uses — no tokenizer dependency),
`parse_repaired`, `fallback_used`, `deterministic_seed`.

## Recording policies

`RecordingPolicy`: `OFF` (default) / `ALL_TASKS` / `SELECTED_TASKS`
(only tasks named in `selected_tasks`) / `SAMPLED` (a `sample_rate`
fraction, uniformly at random) / `DEBUG` (same as `ALL_TASKS` for
recording purposes — reserved as its own value per the spec).

## Storage layout

```
<archive_dir>/
  cognition/2026-07-19.jsonl
  cognition/2026-07-19_2.jsonl   # rolled once the first crossed ~100MB
  dialogue/2026-07-19.jsonl
  town_brain/2026-07-19.jsonl
  ...
  exports/
    review_pack_20260719_143000.zip
```

One subdirectory per task, one file per UTC calendar day (rotating to
`_2`/`_3`/... within a day past `ARCHIVE_ROTATE_MAX_BYTES` ≈ 100MB).
Every write is flushed + `fsync`'d — a JSONL line is either fully
present or absent after a crash/power-loss, never partially written in
a way that corrupts a sibling line; a truncated last line (mid-write at
crash time) is simply skipped by every reader in this module.

## Review packs

`POST /recorder/export-review-pack` (payload: optional `task`,
`date_from`/`date_to` ISO dates, `limit`, `markdown`) builds a
self-contained ZIP (`review_pack.json` + `manifest.json`, optionally
`review_pack.md`) under `<archive_dir>/exports/` and returns its path;
`GET /recorder/download?path=...` serves it (path-traversal-guarded to
stay under `archive_dir`). Each example in `review_pack.json` carries
only the fields meant for AI review (all four layers, stable ID,
essential metadata) — diagnostics like `latency_ms`/queue-wait are
deliberately excluded, matching the spec's "exclude unrelated
diagnostics."

## Validation utility

`scripts/recorder_tools.py` (standalone script, not a pytest suite —
matches this project's standing "no automated test suite" convention):

```
python3 scripts/recorder_tools.py validate [--archive-dir DIR]
python3 scripts/recorder_tools.py stats [--archive-dir DIR]
python3 scripts/recorder_tools.py export-review-pack [--task T] [--date-from D] [--date-to D] [--limit N] [--markdown]
python3 scripts/recorder_tools.py export-random [--task T] [--count N] [--seed N] [--markdown]
```

`validate` walks every JSONL line, flags invalid JSON or a missing
required field (file + line number), and exits non-zero if any errors
were found — "detect corruption" from the spec. `stats` reports
per-task record counts, fallback rate, and on-disk size.

## Dataset layers (kept independent, per spec)

1. **Archive dataset** — the raw JSONL under `<archive_dir>/<task>/`,
   the permanent source of truth.
2. **Review packs** — lightweight, filtered ZIP exports for AI review
   (above).
3. **Training export** — not built yet; a future SFT/DPO export format
   would read from the archive dataset the same way review packs do,
   without either of the above needing to change shape.

## Recording sessions

Each `start()` call mints a new `session_id`/`session_name`, stamped on
every example recorded during that session — lets a later consumer
group/filter by "which run did this come from" without re-deriving it
from timestamps.

## Stable IDs

Every example gets a `uuid4` `example_id`, permanent for its lifetime —
future patch files (corrections, curation labels) can reference an
example by this ID without needing to re-identify it positionally.

## Extension points

- **New LLM task type**: needs zero recorder-specific code — every task
  already funnels through `SimulationEngine._record_llm_debug`, which
  is the recorder's one call site.
- **Richer structured input for an existing task**: add a
  `structured_input={...}` kwarg at that task's `_schedule_llm_job(...)`
  call site in `simulation/engine.py`.
- **A training export format**: read `hearthmind.llm.review_pack.
  iter_examples` the same way `export_review_pack` does; no archive
  format change needed.

## What this does NOT do

No LoRA/QLoRA training run, no automatic curation (top-5%/worst-5%/
random-1% sampling per §8's own framing is a human-supervised step
against exported review packs, not automated here), no `/slots`-style
prompt-cache inspection (same privacy stance `fetch_llama_server_
metrics` already documents). All explicitly out of scope for this pass.
