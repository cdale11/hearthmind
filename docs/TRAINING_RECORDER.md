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

## v1.1.0 "Recorder Enhancement Pass" (backward compatible)

Purely additive — every v1.0.0 field/behavior above is unchanged;
`SCHEMA_VERSION` stays 1 (see `recorder.py`'s module docstring for why
a field-only addition doesn't bump it). Each JSONL line gained:

- **`generation_config`**: the actual sampling/context knobs the call
  was made with (`temperature`, `max_tokens`, `context_length`,
  backend-specific fields like `num_gpu`/`use_mmap` for Ollama) —
  distinguishes "the model changed behavior" from "the config changed."
  Supplied by `SimulationEngine._generation_config_snapshot`; only
  includes knobs this project actually sets (no invented `top_p`/
  `top_k`/`repeat_penalty` — neither client sends those).
- **`prompt_metadata`**: `{template_name, template_version,
  system_prompt_version}`. `template_name` defaults to the task name
  when not explicitly supplied; `system_prompt_version` is a short hash
  of the system prompt text itself, so it changes automatically the
  moment a prompt author edits that text — no manual version bump
  needed anywhere.
- **`prompt_hash`** / **`structured_input_hash`**: SHA-256 of the
  rendered prompt / of the structured input (JSON-canonicalized via
  `sort_keys=True`) — enables duplicate/repeated-scenario detection
  without diffing long strings.
- **`session`**: `{name, tags}` — a nested view of the same session
  info `session_id`/`session_name` already carried (kept unchanged),
  plus new free-text `tags` set at `start()` time (`POST /recorder/
  start`'s `tags` field, or the dev-console panel's tags input, comma-
  separated, editable before recording begins).
- **`outcome`**: `{status, ...}` — what actually happened with the
  model's answer, using information the engine already has synchronously
  at record time (no new instrumentation): `"executed"` (a non-critical
  job's `apply()` ran against a genuine LLM answer), `"fallback_used"`,
  `"deferred_critical"` (Constitution §3/§7 jobs that defer rather than
  fabricate), `"queued_pending_apply"` (cognition/dialogue, whose real
  apply happens on a later tick via the pending-results queues),
  `"target_gone"` (rumor_interpret, listener no longer alive), plus an
  `apply_failed: bool` where relevant. Designed to accept richer values
  later without a shape change — deliberately not wired into every
  gameplay system this pass.
- **`dataset`**: `{schema_version, simulation_version, archive_version}`
  — lets a reviewer compare two archives produced months apart.

**Recorder statistics** (`status()`'s new `examples_per_task`/
`total_examples`/`oldest_example_ts`/`newest_example_ts`): seeded via
one real archive scan at `start()` time (not on every `/recorder/
status` poll — that call now does zero filesystem I/O), then maintained
incrementally by the writer thread as an O(1) update per write.

**Review pack `manifest.json`** gained `task_distribution`, `model`
(models seen), `prompt_versions` (system-prompt-version hashes seen),
`recording_session` (session id/name/tags for every session
represented in the pack), and `date_range` — computed from the already-
collected in-memory example list, no extra archive scan. `REVIEW_PACK_
FIELDS` gained the new per-example fields too (all `.get(...)`-safe —
an older archive line simply yields `None` for them).

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
self-contained ZIP (`review_pack.json` + `manifest.json` +
`diagnostics.json` + `diagnostics.md`, optionally `review_pack.md`)
under `<archive_dir>/exports/` and returns its path; `GET
/recorder/download?path=...` serves it (path-traversal-guarded to stay
under `archive_dir`). Each example in `review_pack.json` carries only
the fields meant for AI review (all four layers, stable ID, essential
metadata) — per-example diagnostics like `latency_ms`/queue-wait are
deliberately excluded, matching the spec's "exclude unrelated
diagnostics" — but see below for the *aggregate* diagnostics report
every export now carries alongside it. `export_random_subset` (`POST
.../export-random`) produces the same four/five files.

### Automatic diagnostics report (`llm/review_diagnostics.py`)

Explicit live request: "Every exported review pack should include an
automatic diagnostics report... to objectively identify simulator
regressions and improvements before manual review." Computed from the
SAME `raw_examples` list `review_pack.py` already collected for the
export (no second archive scan, pure/read-only, stdlib-only — no
numpy, matching this project's `llm_prompt_stats_summary` char-based-
estimate convention). Every field degrades to `None`/omitted rather
than a misleading zero when the underlying metadata predates a given
archive line (mixed-vintage archives are expected, never special-cased
by the caller).

`diagnostics.json` covers: task distribution; prompt/completion length
(estimated tokens + prompt chars, avg/median/p95/max); latency overall
and per-task; fallback rate overall and per-task; parse-repaired rate;
prompt/structured-input duplicate rates (via the existing `prompt_
hash`/`structured_input_hash` fields); per-task context-usage rates
(fraction of examples that had each optional context field present,
read from `structured_input["context_available"]`); dialogue topic
diversity (unique-topic ratio, dominant topic + its share of all
exchanges — the direct "is one narrative like 'spring rhythm'
dominating" signal); dialogue conversation-opportunity balance (which
`dialogue.build_opportunity_candidates` categories actually got
selected, from `structured_input["opportunities"]`); a coarse NPC/
personality diversity ratio (unique NPCs touched vs. total NPC
appearances); and a day-by-day historical-trends table (example count,
fallback rate, avg prompt tokens, avg latency, dialogue topic
diversity) so a reviewer can see whether a config/prompt change moved
these numbers over time, not just their all-time average.
`diagnostics.md` is the same data rendered for a human reviewer to
skim before opening any individual example.

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
