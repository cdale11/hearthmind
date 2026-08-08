# Hearthmind — HearthBench & Adaptive Runtime: Implementation Checklist

Everything in `hearthbench.md` and `runtime_opt.md`, folded into
actionable items with deep specs, checked against v1.4.1.

Two independent programs that share one nervous system (profiling):

- **Part A — HearthBench.** *"If I plug this model into Hearthmind, how
  good will the experience be?"* A standalone, model-agnostic evaluation
  framework. Answers a **selection** question.
- **Part B — The Adaptive Runtime.** An OS-like execution layer that
  decides *when/where/how* work runs, never *what it means*. Answers an
  **execution** question.

They meet in Part C: the runtime's permanent profiler is the same
telemetry HearthBench's performance category consumes, and HearthBench's
model measurements feed the runtime's LLM-throughput model.

Status legend: **[PRESENT]** exists · **[PARTIAL]** foundations exist ·
**[MISSING]** greenfield.

**Status note (v1.34.251, consolidated).** This doc is the original
spec for both programs and its Part A status (below) is still accurate
— HearthBench itself is almost entirely unbuilt, see `docs/ROADMAP-
2026-07-REMAINING.md`'s Phase 6 for the dependency-ordered build order.
Part B (the Adaptive Runtime) is the opposite: it shipped extensively
since this doc was written (B0-B7, B14 fully; B4/B9/B10/B13/B15 mostly;
B8/B11/B12 have real substrate with real production wiring only for
part of each). Part B's own per-item narrative below is now a *compact*
summary — the original ran to ~1,870 lines of "shipped, vX.Y.Z, here's
what was built and verified" prose duplicating `CHANGELOG.md`/
`CLAUDE.md`'s own history log; that detail lives there now, not here.
Genuinely open Part B work is tracked in the roadmap's Phase 2 (B13.5),
Phase 4 (B3.3, B4.2's last candidate, B9.3), and Phase 5 (B8.1-B8.3 —
see the correction below, B11, B12's remaining cascade, B14.3, B15.6-8).

---

# PART A — HEARTHBENCH

## A0 — Foundations to reuse, not rebuild [CONFIRMED, v1.34.161 — no new code, by the item's own text]

Each A0.x item's own wording is "formalize/share/reuse/lift... rather
than writing a new one" — deferred to A2/A4, not action items in
themselves.

- [x] **A0.1 — CONFIRMED.** `llm/client.py` has `OllamaClient`,
  `LlamaCppClient`, both behind `build_llm_client(config)` — a real
  de-facto adapter layer. Formalizing it into A2's `ModelAdapter`
  Protocol remains open.
- [x] **A0.2 — CONFIRMED.** `llm/eval_harness.py` has `split_holdout`
  (hash-based held-out split), `build_golden_set` (stratified
  golden-prompt sampler), and `check_regressions` — all real, all
  reusable by A4.4/A13.3 as-is rather than reimplemented.
- [x] **A0.3 — CONFIRMED.** `llm/recorder.py`'s `TrainingRecorder`
  writes exactly the four-layer schema (`structured_input` → `prompt`
  → `raw_completion` → `parsed_output`, `SCHEMA_VERSION`) A0.3
  describes — real, versioned, ready for A8.1's run-record format to
  reuse directly.
- [x] **A0.4 — CONFIRMED.** `llm/quality_labels.py` has `schema_valid`,
  `check_leaks`, `length_in_bounds`, `dialogue_responds`, `topic_
  novel`, combined by `label_example` — real per-example scorers, a
  direct A4 Tier-1-deterministic-scorer set once lifted into a shared
  library.
- [ ] **Rule — still open.** The shared `hearthmind.cognition_contract`
  package itself doesn't exist yet — real A2/A4 forward work (lifting
  the four confirmed pieces above into an importable location both
  `hearthmind` and `hearthbench` can share without either importing the
  other's runtime).

## A1 — Module layout & isolation [PARTIAL — A1.1/A1.2 shipped v1.34.160, A1.3 shipped v1.34.283]

- [x] **A1.1 — Package skeleton — SHIPPED, v1.34.160.** `hearthbench/`
  as a sibling of `hearthmind/`, with the brief's modules as reserved
  submodules (`runner/`, `adapters/`, `prompts/`, `tests/`,
  `validation/`, `metrics/`, `diagnostics/`, `reporting/`, `ui/`), each
  a placeholder `__init__.py`, no logic yet. `pyproject.toml` gained a
  `bench = []` extra and `hearthbench*` in `packages.find`.
- [x] **A1.2 — Import firewall test — SHIPPED, v1.34.160.**
  `scripts/verify_hearthbench_isolation.py` — a standalone AST-based
  script walking every `.py` file under both packages, asserting
  neither imports the other in the forbidden direction. Not wired into
  a CI pipeline (none exists in this repo) — a manually-run gate.
- [x] **A1.3 — Process isolation — SHIPPED, v1.34.283.** Two real,
  independent isolation layers: A2.4's `ServerLifecycle` already
  isolates the model SERVER (llama-server) in its own process; this
  item isolates the BENCH RUN ITSELF. New `hearthbench/runner/cli.py`:
  a real `python -m hearthbench.runner.cli run ...` entry point
  driving `run_cases_with_resume` in a fresh interpreter (grounding
  cases only today — the one category with a runnable prompt of its
  own, no fixture pack needed). New `hearthbench/runner/process.py`'s
  `BenchRunProcess`: a real `subprocess.Popen` wrapper (start/is_
  running/wait/stop, mirroring `ServerLifecycle`'s own shape) whose
  `poll_progress` reads the run's real `completed_case_ids()` straight
  off disk (A8) — no socket/pipe IPC, the shared run directory does
  the work. A real end-to-end verify script found and fixed a real,
  previously-shipped bug in the same pass: `BlobStore.__init__`
  eagerly `mkdir`'d its root even behind a read-only `RunRecordReader`,
  so reading back a broken (non-directory) run path crashed a reader
  instead of degrading — fixed by making `BlobStore` fully lazy about
  directory creation (only `put()`, a real write, ever creates one).

## A2 — Model Adapter Layer [SHIPPED, v1.34.276]

- [x] **A2.1 — `ModelAdapter` Protocol — SHIPPED.** `hearthbench/
  adapters/protocol.py`: a `typing.Protocol` (not an ABC — no shared
  inheritance needed, only structural typing), plus `AdapterResult`/
  `AdapterCapabilities`/`AdapterDescribe`/`HealthStatus` dataclasses,
  matching the spec's literal shape:
  ```
  generate(prompt, system, schema|None, max_tokens, temperature, seed)
      -> AdapterResult(text, parsed, prompt_tokens, completion_tokens,
                       latency_ms, ttft_ms, raw_response, retries)
  capabilities() -> {json_schema: bool, grammar: bool, seed: bool,
                     logprobs: bool, metrics_endpoint: bool}
  describe() -> {model, quantization, context, backend, build_id, ...}
  health() -> ok | error
  ```
  `capabilities()` is what lets tests degrade gracefully (a backend
  without schema support gets scored on raw-JSON validity instead of
  being disqualified). `seed` support needed one small additive
  upstream change: `hearthmind.llm.client`'s `OllamaClient`/
  `LlamaCppClient.generate_json` gained a trailing `seed_override`
  param (mirrors the existing `num_predict_override`/`temperature_
  override` pattern exactly) so the wrapping adapters can honestly
  report `seed=True` for a capability the backend genuinely has,
  rather than reporting it falsely `False` to avoid reimplementing the
  HTTP call — A0.1's own "reuse, don't rebuild" applied one level
  deeper than the adapter itself.
- [x] **A2.2 — Three adapters at launch — SHIPPED.** `LlamaCppAdapter`/
  `OllamaAdapter` (`hearthbench/adapters/llamacpp.py`/`ollama.py`) thin-
  wrap `hearthmind.llm.client`'s existing `LlamaCppClient`/
  `OllamaClient` (real reuse, not reimplemented HTTP calls — `hearthmind.
  llm.client` imports nothing from `hearthmind.simulation`/`.agents`/
  `.world`, so this stays within A1.2's firewall); `LlamaCppAdapter`
  also exposes `poll_metrics()` reusing `fetch_llama_server_metrics`
  directly. `OpenAICompatAdapter` (`openai_compat.py`) is genuinely
  new — a model-family-agnostic client for any `/v1/chat/completions`
  endpoint, self-contained JSON-recovery rather than reaching into
  `hearthmind.llm.client`'s own underscore-private helpers. New
  `hearthbench/adapters/registry.py`'s `ADAPTER_REGISTRY`/`build_
  adapter`, mirroring the sim-side registry's own one-line-per-backend
  shape. The lint rule shipped as `scripts/verify_hearthbench_adapter_
  isolation.py` — an AST scan flagging any string literal containing a
  model-family substring (nemotron/qwen/llama/gemma/gpt/claude/
  mistral/mixtral/phi/deepseek) used as a comparison operand anywhere
  under `hearthbench/` outside `hearthbench/adapters/`; clean on the
  real tree today.
- [x] **A2.3 — Adapter conformance suite — SHIPPED.**
  `hearthbench/adapters/conformance.py`'s `run_conformance_suite`:
  adapter-shape-agnostic (only calls the four `ModelAdapter` Protocol
  methods), checking schema honoring, token accounting, error
  taxonomy, and the Protocol's own "`generate()` never raises"
  contract — verified against a REAL local stdlib HTTP server (canned,
  shape-accurate responses) for the success path and a REAL
  unreachable host (a genuine connection-refused error, not a mock)
  for the failure path, plus a deliberately-broken synthetic adapter
  proving the suite genuinely catches a real contract violation rather
  than rubber-stamping every adapter. "Cancellation" scoped out
  honestly (a future runner's concern — `generate()` is synchronous/
  blocking by contract, so there's no in-adapter cancellation surface
  to check independently of A11).
- [x] **A2.4 — Server lifecycle management — SHIPPED.**
  `hearthbench/adapters/lifecycle.py`'s `build_llama_server_command`
  (pure — model path + tuning knobs -> the exact argv, mirroring
  `scripts/run.sh`'s own confirmed-working defaults without depending
  on the shell script) + `ServerLifecycle` (a generic subprocess
  launch/stop/health-poll wrapper — deliberately knows nothing about
  `llama-server` specifically, all of that lives in the command-
  builder). Deliberately scoped narrower than `run.sh`'s full ~20-flag
  tuning surface (an `extra_args` escape hatch covers the rest) — the
  real deliverable is the reproducibility record (`LaunchRecord`:
  command/pid/started_at/stopped_at/exit_code), not flag-for-flag
  parity. Verified against a real generic subprocess (this offline
  environment has no `llama-server` binary to launch) — start/is_
  running/double-start-rejection/stop/exit-code-recording/health-poll-
  bails-out-on-a-dead-process all proven against genuine `subprocess.
  Popen` mechanics, not a fake.

## A3 — Prompt Library & Test Definitions [SHIPPED, v1.34.277]

- [x] **A3.1 — Frozen prompt fixtures exported from the real sim —
  SHIPPED.** **[DECIDED: frozen export, as specced.]**
  `hearthbench/prompts/fixtures.py`'s `export_fixture_pack` reads a
  real `hearthmind.llm.recorder` archive (via `hearthmind.llm.review_
  pack.iter_examples` — real reuse, not a second archive walker) and
  writes `<output_dir>/<version>/<task>.json` + a `manifest.json`
  naming every task's count and a content-addressed `pack_hash` —
  frozen, checked-in, hash-identified. Deduplicates by a real content
  hash (task+structured_input+prompt+system_prompt) so a re-recorded
  near-identical situation collapses to one fixture rather than
  crowding out real variety; a deterministic per-task seeded sample
  (`select_fixtures_per_task`) means re-exporting the SAME archive with
  the SAME seed reproduces a byte-identical pack — verified directly,
  not assumed. `scripts/hearthbench_export.py fixtures` is the real
  `hearthbench export` command.
- [x] **A3.2 — Test definition schema — SHIPPED.**
  `hearthbench/prompts/schema.py`'s `TestCase`/`Turn`, the literal
  checklist shape:
  ```
  TestCase: id, category, fixture_ref, system_prompt, schema_ref,
            scorers[], weight, tags[], turns[] (multi-turn),
            expected_invariants[] (grounding facts that must hold),
            seed
  ```
  `test_case_from_fixture(fixture, category, scorers=[...])` is the
  real "adding a benchmark category = adding data + a scorer, never
  touching the runner" mechanism — a `FixtureExample` (A3.1's data) +
  a scorer-id list (A4's future registry, referenced by string id
  only, no import) produces a complete `TestCase` with zero runner
  code touched.
- [x] **A3.3 — Multi-turn & stateful cases — SHIPPED.** No separate
  mechanism needed: `TestCase.turns: list[Turn]`, `Turn` carrying
  `injected_fact`/`expects_recall_of`/`offers_contradiction` — a
  single-shot case is simply `turns=[]`. `render_turn_sequence(test_
  case)` is the one real piece of logic (pure, sorts by index,
  accumulates every prior turn's `injected_fact` into each later
  turn's `context`) turning declarative `turns` data into the ordered
  sequence a future A11 runner would actually send — proven directly
  against the checklist's own worked example ("turn 1 establishes a
  fact... turn 7 tests recall... turn 12 offers a contradiction").
- [x] **A3.4 — Synthetic perturbation — SHIPPED.**
  `hearthbench/prompts/perturbation.py`'s `synthesize_fixtures`
  wraps ANY `(count, seed) -> [...]` synthesizer as real
  `FixtureExample`s (`synthetic=True`, `fixture_id` prefixed
  `synthetic-` so a mixed pack can always tell organic vs. synthesized
  fixtures apart); `synthesize_town_brain_fixtures` is the one real
  wired instance, reusing `hearthmind.llm.prompt_synthesis.
  synthesize_town_brain_batch` directly (real reuse, per the
  checklist's own text). **Exercising this reuse path for the first
  time found and fixed a real pre-existing bug**: `synthesize_town_
  brain_situation` never actually supplied `town_brain.build_prompt`'s
  required `priority` argument, shifting every following positional
  argument one slot out of place and raising a `TypeError` on the
  very first real call — `_VALID_PRIORITIES` had been imported into
  `prompt_synthesis.py` for exactly this purpose but never wired in.
  This function (and `scripts/recorder_tools.py synthesize-town-
  brain`, its only prior real call site) had genuinely never worked
  end to end before this pass; fixed by drawing `priority` from the
  real closed vocabulary and passing it in the correct position. See
  CHANGELOG.md's [1.34.277] entry for the full incident detail.

## A4 — Scoring & the judge problem [SHIPPED, v1.34.278] — *the central design decision*

**[DECIDED: build both paths.]** Deterministic-only scoring is a
first-class run mode (`--no-judge`), used by CI (A13) and quick
screening; the judge tier is an additive layer for subjective
categories. Both produce a valid, clearly-labelled report:
`Score: 78.1 (deterministic-only; Dialogue/Personality unscored)` is
legitimate, never broken. `hearthbench/scoring/` ships all three
tiers as real, independently-testable primitives (full detail in
`docs/ROADMAP-2026-07-REMAINING.md`'s Phase 6 / `CLAUDE.md`'s
"Current state (v1.34.278)") — A10's actual weighted composite
(`--no-judge` mode itself, the disqualifying floors) is A10's own
later job, not built here; A4 only ships the scorers and their
registry.

- [x] **A4.1 — Tier 1: deterministic scorers (always on, free) —
  SHIPPED.** Nine scorers: `schema_validity`/`length_compliance`/
  `leak_freedom`/`context_reflection` lifted directly from
  `quality_labels.py`/`review_diagnostics.py`; `fallback_free`/
  `latency` (parse/retry/fallback rate, latency/throughput);
  `lexical_diversity`/`repetition_self_similarity` (new, stdlib-only);
  `multi_turn_recall` (A3.3's `Turn.expects_recall_of` made scoreable
  — the real, honest slice of "contradiction/grounding-violation
  detection" this pass ships; a genuine active-contradiction check
  needs semantic understanding, left to Tier 2).
- [x] **A4.2 — Tier 2: judge-model scorers (optional, subjective
  categories) — SHIPPED, generalized v1.34.286.** `JudgeScorer` wraps
  any A2 `ModelAdapter` behind a versioned rubric with worked anchors;
  judge model + rubric version recorded on every result; `measure_
  self_consistency` re-scores a sample and reports the real stdev/
  agreement. Originally one fixed rubric (naturalness/personality/
  emotional-realism, hardcoded via module constants); now takes
  optional `rubric_prompt`/`axes`/`rubric_version` constructor params,
  defaulting to that exact original rubric unchanged — the real
  mechanism A5.2-A5.6 each needed their own distinct rubric to exist
  at all, with zero behavior change for any pre-existing call site.
- [x] **A4.3 — Tier 3: human rating (calibration ground truth) —
  PARTIAL.** The blind-pairwise DATA MODEL (`HumanRatingTask`/
  `HumanRating`, append-only JSONL storage) and `judge_human_agreement`
  are real and shipped; the rating PAGE itself is A12.9, not attempted
  this pass.
- [x] **A4.4 — Scorers are pure, versioned, registered — SHIPPED.**
  `Scorer(id, version, fn(case, result, context) -> ScoreDetail)` +
  `ScorerRegistry` (rejects re-registering an id at a different
  version) — scorer version is part of a run's identity, mechanically
  enforced, not just stated.

## A5 — Benchmark categories [PARTIAL, v1.34.286] — every one from the brief

Each becomes a category module with concrete cases and scorers. Per
the checklist's own SEQUENCE, step 6 shipped the three OBJECTIVE
categories (A5.7/A5.8/A5.9, none needing a judge model) plus A5.10's
guide; step 7 ("A4.2 judge + remaining subjective categories") ships
now — all six subjective categories are real. A5.11 (gated on B15.5)
remains open — see `docs/ROADMAP-2026-07-REMAINING.md`'s Phase 6 entry
for full detail.

Made possible by generalizing A4.2's own `JudgeScorer`
(`hearthbench/scoring/judge.py`): it previously hardcoded ONE rubric
(dialogue's) via module-level constants; it now takes optional
`rubric_prompt`/`axes`/`rubric_version` constructor params, defaulting
to that exact original rubric unchanged — `JudgeScorer(adapter)` with
no extra args is still byte-for-byte the same dialogue scorer as
before (verified directly). A5.1 (Dialogue) reuses that default rubric
as-is, since its own checklist text is exactly what it already scored;
A5.2-A5.6 each get a genuinely distinct rubric/axes matching their own
stated criteria below — never a copy-pasted dialogue rubric with the
category name swapped (verified: all five are pairwise-distinct texts).

- [x] **A5.1 — Dialogue — SHIPPED.** `hearthbench/tests/dialogue.py`,
  weight 15. Naturalness/coherence/personality/emotional realism via
  A4.2's own default judge rubric, unmodified. New category-specific
  Tier 1 scorer `no_ambient_filler`: a closed, hand-authored vocabulary
  of the exact generic-agreement/aphorism phrases ("wise words," "true
  enough," "so it goes," ...) this project's own dialogue system has
  independently fought before under a different failure shape
  (`VOICE_LINE_DUPLICATE_OVERLAP`/`FOLKLORE_DUPLICATE_OVERLAP` catch
  verbatim repeats; this catches never-identical-but-still-empty
  agreement filler) — bounded penalty, same shape as grounding's
  `no_unsupported_specifics`. Two real hand-authored cases.
- [x] **A5.2 — Personality — SHIPPED.** `hearthbench/tests/
  personality.py`, weight 10. Judge axes: voice consistency/
  distinctiveness/trait plausibility. Honest scope trim stated in the
  module's own docstring: a single judge call scores one case's output
  against a stated personality profile — a real, testable proxy for
  "consistency," not literal cross-conversation aggregation (which
  needs a future A11 runner comparing several real outputs from the
  same subject, not attempted here). Two cases with deliberately
  opposite stated profiles (blunt/impatient vs. gentle/patient).
- [x] **A5.3 — Memory — SHIPPED.** `hearthbench/tests/memory.py`,
  weight 12. Judge axes: recall accuracy/appropriate forgetting/
  contradiction resistance, alongside the real deterministic
  `multi_turn_recall`/`context_reflection` scorers (A4.1). Real
  multi-turn cases built on A3.3's own `Turn.injected_fact`/`expects_
  recall_of`/`offers_contradiction` machinery — `memory:recall_after_
  gap` (a fact stated early, recalled several turns later) and
  `memory:contradiction_resistance` (a later turn states something
  false that conflicts with an established fact; the case checks the
  character HOLDS to the truth rather than flipping).
- [x] **A5.4 — Beliefs — SHIPPED.** `hearthbench/tests/beliefs.py`,
  weight 12. Judge axes: evidence grounding/revision quality/
  confidence calibration. The deliberate mirror image of Memory's
  contradiction-resistance case: `beliefs:revision_on_new_evidence`
  reuses the identical `Turn` machinery, but this time the LATER turn
  establishes genuinely NEW real evidence (not a bare false claim), and
  the case checks the character's THEORY correctly updates in response
  — Memory tests holding a known truth against a false contradiction,
  Beliefs tests revising a theory when the evidence actually changes.
  Plus `beliefs:formation_from_evidence` (a theory formed from a stated
  anomaly with no prior belief to revise).
- [x] **A5.5 — Planning — SHIPPED.** `hearthbench/tests/planning.py`,
  weight 8. Judge axes: goal coherence/horizon realism/adaptation when
  blocked. Two cases: a real goal-formation scenario (repair a granary
  before winter) and a real mid-plan obstacle (a washed-out bridge)
  testing whether the stated plan actually changes in response.
- [x] **A5.6 — Village cognition — SHIPPED.** `hearthbench/tests/
  village_cognition.py`, weight 10. Judge axes: cultural reasoning/
  institutional grounding/social plausibility. Distinct in shape from
  every other subjective category: cases are authored from the
  SETTLEMENT-scale collective "village voice" this project's own
  production code already speaks in (`llm/town_brain.py`, `llm/
  beliefs.py`'s settlement-scoped path, `llm/culture.py`), never a
  single named agent — a real tradition-crystallization case and a
  real declining-institution case.
- [x] **A5.7 — Grounding — SHIPPED.** `hearthbench/tests/grounding.py`,
  weight 20 (A10.1's stated highest default). Four real hand-authored
  adversarial bait `TestCase`s (each a single `Turn` withholding the
  exact fact its own question asks for — population count, a spouse's
  name, a harvest yield, a weather forecast — plus `expected_
  invariants` naming what's deliberately unstated). New category-
  specific scorer `no_unsupported_specifics`: flags a number/proper-
  noun claim in the output with no support anywhere in the case's own
  `structured_input` — "reward explicit uncertainty" needs no separate
  logic, since a hedge states no new specifics and so already scores
  clean under the same heuristic.
- [x] **A5.8 — Structured outputs — SHIPPED.** `hearthbench/tests/
  structured_outputs.py`, weight 8. `build_structured_output_cases()`
  derives a real `(grammar, no_grammar)` `TestCase` pair per task
  actually registered in `hearthmind.llm.json_schemas.TASK_SCHEMAS` —
  zero hardcoded task list, grows automatically. `score_structured_
  output_delta` is this pass's real answer to A6.3's identical "score
  both modes, report the delta," needing nothing from the still-
  unbuilt A6.
- [x] **A5.9 — Performance — SHIPPED.** `hearthbench/tests/
  performance.py`, weight 5. Wraps A4.1's `latency` scorer (a pure
  measurement); `summarize_latency` computes real p50/p95/max/mean for
  latency, TTFT, and completion tok/s (derived from `AdapterResult`'s
  own token counts) — the "attributed per case" half of A5.9's own
  text. Continuous RAM/swap/CPU% sampling (A7.2) is real, distinct,
  unstarted future work.
- [x] **A5.10 — Category extension guide — SHIPPED.** `docs/
  HEARTHBENCH-CATEGORY-GUIDE.md` (the doc) + `hearthbench/tests/
  _template.py` (the template — deliberately unregistered, not in
  `CATEGORY_REGISTRY`) — both literally what this item's own text
  asks for.
- [ ] **A5.11 — World-level emergence run [APPROVED].** Run a real
  fixed-seed sim (2k-5k ticks, LLM on) and score the *emergent output*
  (causal chain length, topic diversity, belief accuracy, want-
  resolution rate, ambient-filler share, invention adoption ratio,
  stability). Reported as a separate "World Score," never folded into
  the 100-point composite (far higher variance/lower N). **Needs
  reference mode (B15.5)** so it measures the model, not the host.
  Keep behind a separate `hearthbench.world` entry point that shells
  out to a sim subprocess (never an in-process import), so the A1.2
  firewall still holds for the core benchmark. Last item to build —
  needs B15.5 on the runtime side first.

## A6 — Structured Output Validator [PARTIAL]

- [ ] **A6.1** — Reuse `json_schemas.py` via the shared contract package
  so bench validation is identical to production validation.
- [ ] **A6.2** — Record the full repair ladder per call (raw → parse →
  repair → schema → fallback) with the reason at each rung.
- [ ] **A6.3** — Score both constrained and unconstrained modes when
  supported, report the delta.

## A7 — Metrics Collector [PARTIAL, A7.1+A7.3 shipped v1.34.281]

- [x] **A7.1 — SHIPPED.** `hearthbench.metrics.aggregate.recompute_
  run_metrics(run_dir)`: reads a run's raw per-case `ScoreDetail`s
  straight back off disk (A8's `RunRecordReader`) and re-derives real
  per-category/per-scorer statistics via A7.3's own `summarize_scores`
  — the literal claim ("aggregates can be recomputed without
  re-running") proven directly: zero adapter calls, zero re-scoring,
  only re-aggregation of what A8.1 already committed.
- [ ] **A7.2** — System sampling thread (RSS, swap, CPU%, llama-server
  `/metrics`), aligned to case boundaries. Real, distinct, unstarted —
  needs a live long-running benchmark process to sample against.
- [x] **A7.3 — SHIPPED (v1.34.279).** N, mean, median, p95, stdev, and
  a confidence interval per category — feeds A10/A11's score-confidence
  requirement. `hearthbench.tests.category.summarize_scores`/
  `CategoryScoreSummary` ship exactly this math, real and tested, now
  wired to a real stored run (A7.1) as well as a live one
  (`hearthbench.runner.run.aggregate_scores`).

## A8 — Diagnostics: lose nothing [PARTIAL, A8.1/A8.2/A8.3/A8.4 shipped v1.34.281]

New `hearthbench/diagnostics/run_record.py`.

- [x] **A8.1 — Run record — SHIPPED.** `RunRecordWriter`/
  `RunRecordReader`: one real directory per run, `cases.jsonl` (one
  `CaseRecord` line per case — parsed JSON, structured input,
  fallback/repair/retry flags, timing, token counts, per-scorer
  `ScoreDetail`s with scorer version) + `manifest.json` (A8.2).
  `commit_case` writes, flushes, and `os.fsync`s IMMEDIATELY on every
  call — never batched in memory — which is the real mechanism A11.4
  (resume) depends on.
- [x] **A8.2 — Environment capture — SHIPPED.** `build_environment_
  snapshot(adapter, run_id)` reuses A2's own `AdapterDescribe`/
  `AdapterCapabilities` directly (duck-typed off `adapter.describe()`/
  `.capabilities()`) — model/quantization/context/backend/build_id +
  capability flags, written once into `manifest.json` at run creation,
  never silently overwritten by a later resume call.
- [x] **A8.3 — Content-addressed storage — SHIPPED.** `BlobStore`:
  sha256-keyed files under `<run_dir>/blobs/`, genuinely deduplicated
  (re-storing an identical prompt/completion is a real no-op write,
  verified directly) — a `CaseRecord` references prompt/completion
  text by hash, never inlines it twice.
- [x] **A8.4 — Retention policy — SHIPPED.** Permanent by default —
  nothing in `run_record.py` ever deletes a run directory on its own.
  `prune_run(run_dir)` is the ONE explicit-only deletion path, never
  called by `RunRecordWriter`/a normal run or resume call — the same
  discipline A13.4's `save_baseline` already established for this
  package.

## A9 — Reports [PARTIAL, A9.1-A9.4 shipped v1.34.282]

New `hearthbench/reporting/report.py`.

- [x] **A9.1 — HTML report — SHIPPED (partial).** `render_html_report`:
  self-contained (no external CSS/JS), the plain-language recommendation
  (A9.4) up top, per-category scores WITH confidence, a real "not yet
  measured" disclosure list, and — when a real `run_dir` is supplied —
  real failure examples pulled directly through A8's `RunRecordReader`/
  `BlobStore` (an actual committed case's actual prompt/completion
  text, never synthesized). Latency/memory GRAPHS are explicitly NOT
  attempted — no charting dependency exists in this repo; the report
  prints the real p50/p95/max numbers as a plain table instead, with
  an honest note that a chart isn't built.
- [x] **A9.2 — JSON + CSV exports — SHIPPED.** `export_json`/`export_
  csv`, stdlib `json`/`csv` only.
- [x] **A9.3 — Comparison report — SHIPPED.** `compare_runs(labeled_
  scores)`: N real `HearthBenchScore`s against the first as baseline,
  real per-category deltas, and a genuine significance flag per
  category per non-baseline run — the baseline's and candidate's real
  95%-CI-derived confidence intervals either overlap (not flagged) or
  don't (`significant_change=True`); `None` when either side lacks a
  real margin (honest "can't tell," never guessed).
- [x] **A9.4 — Honest recommendation — SHIPPED.** `recommendation_
  text`: any real A10.2 disqualification is stated FIRST, before the
  headline number; a wide confidence margin is flagged `LOW CONFIDENCE`
  prominently; a genuinely unscored run states so rather than printing
  a fabricated total.

## A10 — The HearthBench Score [PARTIAL, A10.1-A10.4 shipped v1.34.282]

New `hearthbench/reporting/score.py`.

- [x] **A10.1 — Weighted composite, explained — SHIPPED.** Each real
  `Category.weight` (already the checklist's own stated default —
  Grounding 20, Reliability/structured-output 8, Performance 5, the
  only three categories real today) IS the composite's weight table —
  no second hardcoded copy. `MISSING_SUBJECTIVE_CATEGORY_WEIGHTS`
  records the other six named weights (Dialogue 15, Beliefs 12, Memory
  12, Village cognition 10, Personality 10, Planning 8) purely so
  `compute_score` can report them as genuinely unmeasured rather than
  silently omitted. `compute_score` renormalizes weight over ONLY the
  categories with real scored data this run — a category with zero
  cases contributes neither a fabricated zero nor silent full credit.
- [x] **A10.2 — Disqualifying floors — SHIPPED.** `DEFAULT_
  DISQUALIFYING_FLOORS` ships the checklist's own worked example
  verbatim (grounding < 50 caps the total at 60, with its stated
  reason); only checked against a category that was actually scored
  this run. Verified with real fabricated-answer data: a real model
  confidently inventing specific facts genuinely trips a real
  (calibrated-to-what-was-measured) floor and genuinely caps the total.
- [x] **A10.3 — Normalization discipline — SHIPPED.** Every category
  score is real `[0, 100]`, `SCORE_RUBRIC_VERSION`-stamped, never a
  curve against another run. Grounding/structured-outputs (and future
  subjective categories) score from real `CategoryScoreSummary.pass_
  rate`/`.mean`; Performance — which has NO gradeable scorer at all
  (`latency`'s own `ScoreDetail.value` is `None` by design, "A10's
  future rubric decides") — is scored for the first time via `score_
  from_latency_stats`'s real `LATENCY_SCORE_BANDS_MS` p50-latency
  rubric, this item's own literal "future rubric" made real.
- [x] **A10.4 — Confidence — SHIPPED.** `HearthBenchScore.category_
  confidence_margin` (a real 95% CI half-width per scored category,
  reusing `CategoryScoreSummary.confidence_interval_95` directly) +
  `overall_confidence_margin` (the WIDEST — least confident — margin
  among the categories that actually contributed, "only as confident
  as the shakiest measured input") + `n_cases_total` (a real summed
  case count).

## A11 — Run modes [PARTIAL, core execution slice v1.34.280 + A11.4 resume v1.34.281]

- [~] **A11 core (unnamed in the checklist, real prerequisite for
  A11.1-A11.5) — SHIPPED.** `hearthbench/runner/run.py`: given a
  `TestCase` + a real A2 `ModelAdapter` + a `ScorerRegistry`, resolves
  what to actually send (`render_case_prompt` — a `turns`-carrying
  case's last turn, or a `fixture_ref` resolved against a caller-
  supplied fixture pack; a case with neither is honestly skipped, never
  faked), calls the adapter, and scores the result. `run_cases_against_
  adapter`/`aggregate_scores`/`summaries_to_metrics_dict` chain into a
  real `{category: {scorer: CategoryScoreSummary}}` → dotted-path
  metrics dict. This is the one mechanism every A11.1-A11.5 mode below
  would share — none of those modes themselves are built.
- [ ] **A11.1 — Quick** (minutes): stratified subsample, deterministic
  scorers only, no judge — "is this model worth a full run?"
- [ ] **A11.2 — Full** (long): complete fixture set, multi-turn cases,
  judge scoring, repeated sampling for variance.
- [ ] **A11.3 — Custom:** category subset / single category.
- [x] **A11.4 — Resume — SHIPPED, v1.34.281.** `hearthbench.runner.
  run.run_cases_with_resume(cases, adapter, registry, run_dir, ...)`:
  the checklist's own literal words made real — reads A8's `RunRecord
  Reader.completed_case_ids()` fresh off disk at call time and skips
  every case already committed there; each newly-run case commits to
  `run_dir` (A8.1) the instant it completes. A run interrupted mid-way
  and re-invoked against the SAME `run_dir` picks up exactly where it
  left off — verified directly (a 2-of-4-case partial "session"
  followed by a full-4-case resume call makes exactly 2 NEW HTTP
  requests, never re-running the first 2; a third call against an
  already-complete run makes zero).
- [ ] **A11.5 — Reproducibility.** Fixed seeds, recorded sampler
  settings, a `--strict-repro` mode that fails the run if the adapter
  reports non-deterministic capability.

## A12 — Web UI [PARTIAL, A12.1-A12.5 shipped v1.34.285]

- [x] **A12.1 — SHIPPED, v1.34.285.** A real page served by the bench
  daemon itself (new `hearthbench/daemon/` — `server.py`'s `create_app`,
  a real standalone FastAPI app; `page.py`'s self-contained vanilla-JS
  page), deliberately separate from `hearthmind.interface.app` (the
  live sim's own web server), clearly banner-marked "NOT the live town
  simulation."
- [x] **A12.2 — SHIPPED, v1.34.285.** `POST /api/runs` — select
  category/adapter endpoint/model/quantization/context, start a real,
  process-isolated `BenchRunProcess` (A1.3). Only `OpenAICompatAdapter`
  is exposed (matching `hearthbench.runner.cli`'s own current scope —
  no `--backend` flag there either); wiring `LlamaCppAdapter`/
  `OllamaAdapter` through needs the CLI extended first, real future
  work on both sides.
- [x] **A12.3 — PARTIAL, v1.34.285.** `GET /api/runs/{id}/progress` +
  the page's own polling refresh give real live case-count progress.
  **Not shipped**: a genuine push/WebSocket log stream and running
  per-category scores mid-run (today only case-count progress is
  live; category scores are computed once a run is queried via the
  report route) — real, distinct, unstarted future work, flagged
  rather than faked.
- [x] **A12.4 — PARTIAL, v1.34.285.** `POST /api/runs/{id}/cancel` — a
  real `BenchRunProcess.stop()` against a run THIS daemon process
  itself launched (proven against a genuinely running subprocess, not
  just an already-finished one). **Not shipped**: resume, and cancel
  for a run launched by a DIFFERENT daemon process/instance — needs a
  real PID-file/lock mechanism this pass didn't build (a fresh daemon
  can browse but not control a run it didn't launch, proven directly
  by the new verify script's own real 404).
- [x] **A12.5 — SHIPPED, v1.34.285.** `GET /api/runs` discovers EVERY
  real run under `runs_root` by scanning for a real `manifest.json`
  (A8.2) — never an in-memory registry, so a restarted daemon browses
  every past run with nothing to rebuild; proven directly with a
  SECOND, independent daemon instance against the same `runs_root`
  correctly listing a run it never launched.
- [ ] **A12.6** — Compare runs (→ A9.3). Real future work — `hearthbench.
  reporting.report.compare_runs` already exists; only the route doesn't.
- [ ] **A12.7** — Drill into any case: prompt/completion/parsed output/
  scores with justifications/timing. Real future work.
- [ ] **A12.8** — Download HTML/JSON/CSV. Real future work —
  `export_json`/`export_csv` already exist; only the routes don't.
- [ ] **A12.9** — The human-rating page (A4.3). Real future work.

## A13 — Prompt-regression guard in CI [PARTIAL, A13.1-A13.4 shipped v1.34.280]

Catches a prompt edit that silently degrades quality, discovered only
weeks later in a review pack. Per the checklist's own SEQUENCE ("A13
CI regression guard — lands as soon as [A4.1 deterministic scorers +
A5.7/A5.8] works"), ships right after those, well ahead of A6-A12 —
`hearthbench/reporting/ci_guard.py`, real and standalone (no CI
pipeline is wired into this repo yet — same gap `scripts/verify_
runtime_invariant.py`'s own docstring already names — ready to be
invoked from a future CI workflow the moment one exists).

- [x] **A13.1 — Trigger — SHIPPED.** `is_relevant_change(changed_
  files)`: any change under `hearthmind/llm/` (every prompt builder +
  `json_schemas.py` already live there) or `hearthbench/prompts/`/
  `hearthbench/scoring/` (the shared cognition-contract surface)
  triggers — a real glob-prefix check, not a hand-maintained per-file
  list that goes stale. `run_ci_guard` runs the real objective-
  category cases (deterministic scorers only — no judge adapter is
  ever constructed) through the new `hearthbench/runner/run.py`
  (A11's own real execution-core slice, built to unblock this item —
  see A11's entry).
- [x] **A13.2 — Objective-only gate — SHIPPED.** `DEFAULT_CI_
  THRESHOLDS` names only grounding/structured-outputs metrics
  (`no_unsupported_specifics`/`leak_freedom`/`schema_validity`/
  `length_compliance`/`fallback_free` pass rates) — nothing from a
  judge-scored category, mechanically checked by the new verify script.
- [x] **A13.3 — Baseline-relative thresholds — SHIPPED.** Real reuse
  of A0.2's `hearthmind.llm.eval_harness.check_regressions` — `run_ci_
  guard` shapes its real metrics into the same dotted-path dict shape
  that function already walks; no second regression-comparison
  mechanism built.
- [x] **A13.4 — Explicit baseline refresh — SHIPPED.** `save_
  baseline`/`load_baseline` — a plain JSON file, one write path, never
  called implicitly by a regular guard run.
- [ ] **A13.5 — Nightly deeper run** — real, distinct, unstarted future
  work; needs actual CI infrastructure this repo doesn't have.

---

# PART B — THE ADAPTIVE RUNTIME

**Consolidated (v1.34.251).** Each item below is what it is + its
current status + genuinely open sub-items only; the original per-
module implementation/verification narrative (scripts run, check
counts, replay-hash results per shipped increment) is gone — that
detail lives in `CHANGELOG.md`/`CLAUDE.md`'s "Current state" log, not
here. Every "SHIPPED"/"PARTIAL" tag below was cross-checked against
that log at consolidation time.

- **B0 — The prime invariant [SHIPPED].** Gameplay code (`world/`,
  `agents/`, `settlement/`, `economy/`) never makes scheduling/
  threading/batching decisions — mechanically enforced by
  `scripts/verify_runtime_invariant.py` (an AST ban on `threading`/
  `time.sleep`/executor construction in those directories). All 56 of
  the real `_TICK_JOBS` schedule points are migrated onto the B1 task
  graph.

- **B1 — Task declaration & the work graph [SHIPPED].**
  `simulation/task_graph.py`'s frozen `Task` descriptor (id/subsystem/
  fn/timescale/priority_class/reads/writes/trigger/cost_hint/
  locality/determinism) + `TaskRegistry` (builds real dependency edges
  from declared read/write overlap, rejects a genuine cycle at build
  time) + deterministic `topological_order()` (Kahn's algorithm,
  always the lexicographically-smallest ready id — independent of
  registration order) + `Task.legacy()` (an incremental-adoption shim
  with a wildcard write). Fully wired into the live tick loop via B0.

- **B2 — Budgets & scheduling [Hard Rules 2, 9] [SHIPPED].**
  `simulation/scheduler.py`'s `SubsystemBudget` (real wall-clock via
  `time.perf_counter()`), `PriorityClass`-bounded deferral (a task
  hitting its deferral bound is force-run and flagged `promoted` —
  never starves), overrun-defers-not-skips with accruing `debt_
  seconds`, B2.4 attention-follows-change (`simulation/attention.py`'s
  `RegionActivityTracker`/`RegionAttentionGate` — a busy region's
  check interval compresses toward B9's calendar floor, a quiet
  region's stretches toward a ceiling, verified never violates the
  floor), and B2.5 work-conserving spare-capacity execution. Wired to
  one real control point (`_maybe_broadcast`, a `DEFERRABLE` task with
  a measured budget) — every B0-migrated job is `CRITICAL`
  (deliberately, to reproduce pre-migration "always runs" behavior),
  so most of B2's own budget/deferral logic still has limited live
  exercise beyond that one site.

- **B3 — Event-driven execution [Hard Rule 3] [SHIPPED].**
  `simulation/reactivity.py`'s `DirtyTracker` (per-key write-version
  counters) + `EventBus` (one-shot per-tick pub/sub); `Scheduler.
  run_tick` gates every task on real due-ness *before* touching budget
  machinery. One real production job (`institution_dormancy`)
  converted to `ON_EVENT`; the remaining ~200 candidate per-tick call
  sites are the roadmap's Phase 4 item B3.3.

- **B4 — Dormancy [Hard Rule 4] [PARTIAL].** `simulation/dormancy.py`'s
  `DormancyManager` — a real `ACTIVE→DROWSY→DORMANT→ARCHIVED`
  lifecycle with a lossless-wake contract (`wake()` always returns the
  real elapsed-tick gap) and a 20-seed chaos-tested equivalence proof.
  Four of five named B4.2 candidates shipped (idle institutions,
  unused ideas, forgotten traditions, inactive settlements); "distant
  wildlife" remains — the roadmap's Phase 4.

- **B5 — Continuous profiling [Hard Rules 5, 15] [SHIPPED].**
  `simulation/profiling.py`'s per-task `TaskMetrics` (always-on,
  measured ~12μs/task/tick overhead) + a full per-tick `TickTrace`
  naming a specific reason for every task's outcome (not just
  "deferred," but *why*) + `runtime_diagnostics.py`'s real `/
  diagnostics`-reachable report builder. Wired to one real live
  scheduler (`institution_dormancy`); a full aggregate across all ~57
  real per-job schedulers is flagged, not built.

- **B6 — Adaptive tuning [Hard Rule 6] [SHIPPED].** `simulation/
  tuning.py`'s `TunableRegistry` (real range + `SafetyClass`) + a
  deterministic `BangBangController` (hysteresis dead-zone, no LLM
  anywhere in the module). Wired live: `llm_max_concurrent` is now
  daily-retuned from real rolling p95 latency, resizing the actual
  concurrency semaphore in-flight (`CognitionRunner.resize_
  concurrency`, a `_ResizableSemaphore` that never interrupts a
  held permit).

- **B7 — Hardware model [Hard Rule 7] [SHIPPED].** `simulation/
  hardware_profile.py`'s `HostProbe` (cores/RAM/swap/load/storage-
  bench/thermal — every field degrades to `None` rather than crashing)
  + a persisted, host-fingerprinted `MachineProfile` + `select_
  strategy` (pure function: hardware → a recommended concurrency/
  dormancy/cache profile) + `GoodCitizenPolicy` back-off. Wired as a
  downward-only veto/cap layered alongside B6's own latency-driven
  controller.

- **B8 — Predictive scheduling [Hard Rule 8] [PARTIAL, but see
  correction].** `simulation/forecasting.py`'s `WorkloadForecaster`
  (small MLP), `plan_reservation`, `ForecastAccuracyTracker`, `is_
  quiet_window`. This doc's original text left B8.1-B8.3 explicitly
  unwired pending a real trained forecaster — **that forecaster was
  later built and wired for real under Tier 7 HCA's Stage G (`G2`,
  see `CLAUDE.md`'s v1.34.217 entry)**, a genuine real production
  consumer this doc predates and never updated to reflect. B8.4
  (idle-window scheduling) is wired directly (a real daily backlog
  sample gates a real monthly storage micro-benchmark).

- **B9 — Hierarchical timescales [Hard Rule 10] [PARTIAL].**
  `simulation/timescales.py`'s `TimescaleLadder` (a real calendar-
  derived minimum-tick-interval floor per rung: tick→minute→hour→
  day→week→month→season→year) + `ElapsedTimeTracker`/`TimescaleGate`
  (a generic "fires no more often than its floor, catches up
  losslessly" gate any task can use). B9.3 — the real audit of ~200
  per-tick call sites for timescale mismatch — was never attempted;
  the roadmap's Phase 4.

- **B10 — Locality [Hard Rule 11] [PARTIAL].** `simulation/
  locality.py`'s `RegionGrid`/`region_key` (tags a `Task`'s reads/
  writes by region, so B1's dependency graph treats different regions
  as non-conflicting for free — real integration with the existing
  graph, not a parallel mechanism) + region-parallel batch planning
  (verifies write-disjointness before treating a batch as parallel-
  safe). B10.2 (converting flagged global-population/global-map scans
  to indexed/local queries): a discovery tool
  (`scripts/scan_global_scans.py`) plus four real pilot conversions
  shipped, then the remaining ~72 flagged sites were **re-audited and
  confirmed exhausted** — every one is either a full-grid CA loop that
  must touch every tile regardless, or an unfiltered per-tick scan
  that must touch every entity regardless of kind. Genuinely closed,
  not an open item.

- **B11 — Hierarchical memory [Hard Rule 12] [PARTIAL, not wired].**
  `simulation/hierarchical_memory.py`'s `Tier` enum (hot/warm/cold/
  archive) + `MemoryTierManager` (idle-threshold demotion, touch-
  promotes) + `TransparentHandle` (fault-in on a cold/archive read,
  indistinguishable in call shape from a hot read) + a pressure-aware
  tighter-threshold mode (reuses B7's `GoodCitizenPolicy`). No real
  large-persisted-state consumer wired to it yet — the roadmap's
  Phase 5.

- **B12 — History compression [Hard Rule 13] [PARTIAL].**
  `simulation/history_compression.py`'s `CompressionStage`/
  `CompressionLadder` (a real five-stage ladder — raw→episode→
  summary→history→cultural_memory — threshold-triggered condense-and-
  promote, real hard-capacity pruning that never orphans a fault-in
  read). Only the RAW→archived-digest stage is wired (`World.
  emergence_log`'s own eviction); the rest of the cascade needs a real
  chronicle/documentary/culture-digest producer chain per stage — the
  roadmap's Phase 5.

- **B13 — Optimization hypotheses [Hard Rule 14] [mostly SHIPPED].**
  `simulation/optimization_hypothesis.py`'s `HypothesisLoop` (real
  observe→hypothesize→apply→measure→keep-or-roll-back) + a semantic-
  safety gate (a `SENSITIVE` tunable change is kept only if a real
  caller-supplied equivalence check — e.g. a forked-world replay-hash
  comparison — passes; no check at all is treated as a *failed* gate,
  never a free pass) + a bounded, browsable `AdaptationHistory` + hard
  cross-authority enforcement (a loop can only touch its own owned
  tunables, raises immediately otherwise). Wired for real to
  `llm_max_concurrent`, with both a manual dev-console trigger and an
  automatic monthly cadence gated on B6's own reactive controller
  having gone quiet first (so the two controllers can't fight over the
  same tunable). B13.5 (evolutionary search over multi-dimensional
  tunable sets, `tunable_evolution.py`) shipped standalone and
  verified but has no real cadence wired — the roadmap's Phase 2.

- **B14 — Persistence & background work [SHIPPED].**
  `SnapshotScheduler` (idle-preferring minimum interval + a hard
  maximum-interval ceiling regardless of load, real full/incremental
  cadence) wired to the real snapshot call site; a real diff-format
  writer (a genuine FULL+INCREMENTAL snapshot chain, chain-aware
  pruning that can never orphan an unreconstructable snapshot) shipped
  and wired. B14.3's `batch_size_for_storage` (a real function, sizes
  a write batch from measured storage speed) has no real batched-write
  mechanism to size for yet — the snapshot writer is still one
  `INSERT` per row; the roadmap's Phase 5.

- **B15 — Semantic safety: the determinism guarantee [Hard Rule 1]
  [mostly SHIPPED].** B15.1 `scripts/verify_replay_hash.py` — the
  safety net every later change leans on: same seed, LLM disabled,
  byte-identical `World.to_dict()` across independent process runs.
  B15.2 records the "sim adapts to hardware, Body stays strict,
  cognition breadth scales" decision as a literal checkable
  `TWO_PART_GUARANTEE`. B15.3 `EscalationLadder` (five rungs — reorder/
  batch → defer → slow sim-time → pause → reduce cognition breadth —
  one rung at a time, rung 5 only reachable from sustained, not
  transient, pressure) wired to the real `llm_pressure_ratio()`
  signal. B15.4 `CognitionBudget` is structurally a single scalar
  count — can name *how many* agents get cognition this tick, never
  *which* ones or *what* they think (the runtime decides how much the
  world thinks, never what it thinks). B15.5 `reference_mode`/
  `pinned_rung` (a genuine hard no-op under sustained pressure, for
  cross-machine comparability) shipped but never consumed — no
  HearthBench run mode exists yet to request one (see A5.11/A11).
  B15.6 (record host fingerprint/cognition-budget/rung-5 history in
  the save file + diagnostics), B15.7 (fuzz the scheduler — randomize
  task order/budgets/dormancy, assert the replay-hash invariant still
  holds), and B15.8 (a semantic-safety class check at tunable
  *registration* time, not just at hypothesis-apply time) all remain
  unbuilt — the roadmap's Phase 5.

---

# PART C — WHERE THEY MEET

- [ ] **C1** — The runtime's permanent profiler (B5) is the source for
  HearthBench's Performance category (A5.9) — one telemetry
  implementation, two consumers.
- [ ] **C2** — HearthBench's measured model throughput seeds the
  runtime's machine profile (B7.2): benchmark a model once, and the
  runtime starts with a good LLM-concurrency prior instead of learning
  from scratch.
- [ ] **C3** — Shared `cognition_contract` package (schemas, fixtures,
  scorers) is the only coupling; enforced by the import firewall (A1.2).
- [ ] **C4** — Shared record schema (A0.3) means a live-sim quality
  regression can be diagnosed with the same tooling as a bench run.

- [x] **C5 — The model passport [APPROVED]. SHIPPED, v1.34.284.** Both
  halves real: `hearthbench/reporting/passport.py` (emission) +
  `hearthmind/simulation/hardware_profile.py`'s `seed_machine_profile_
  from_passport`/`load_passport_dict` (runtime consumption), wired at
  `SimulationEngine.__init__`.
  - **Contents:** model id + quantization + file hash; the real
    HearthBench score with confidence (`world_score` honestly `None` —
    A5.11 doesn't exist yet); per-category strengths/weaknesses; real
    measured throughput (completion tok/s, TTFT, latency p50/p95, never
    fabricated when unmeasured); `recommended_settings.needs_grammar_
    constraints`; real hard warnings, one per A10.2 disqualification
    that fired. **Scope trim, honestly flagged**: peak RSS per
    concurrency level ships empty (no A7.2 system-sampling thread
    exists yet to source it from); `recommended_settings` covers only
    `needs_grammar_constraints` today, not concurrency/context/batch
    (those need a real concurrency-sweep benchmark, same A7.2
    prerequisite).
  - **Runtime consumption:** real. `SimulationEngine.__init__` matches
    `Config.llm_model` to a passport (`passports/<slug>.json`, sibling
    to the world's own `MachineProfile`) and seeds `measured_llm_
    throughput_tokens_per_s` ONLY while that profile has never had a
    real live measurement of its own — priors, not overrides, exactly
    as this item's own text asks.
  - **Safety interlock:** real. `full_diagnostics()['machine_profile']`
    carries `passport_warnings`, rendered in the dev console's
    "Adaptive runtime" panel as a real "Model passport: ⚠ ..." line.
  - **Provenance, partially shipped, honestly flagged.** `produced_by_
    host()` records a real host fingerprint on every passport (proven
    to exactly match `hearthmind`'s own independent `host_fingerprint()`
    formula via a real cross-implementation parity check in `scripts/
    verify_c5_model_passport.py`) — but "a passport from a very
    different machine contributes throughput priors with lower weight"
    is NOT implemented: `seed_machine_profile_from_passport` seeds
    unconditionally regardless of host match. Real, distinct future
    work — needs a genuine similarity metric between two hardware
    profiles this pass didn't design.

# SEQUENCE

**Runtime (highest immediate value, since it was nearly all
greenfield at the time this doc was written):**
1. B15.1 replay-hash test *first* — the safety net every later change
   leans on.
2. B0 prime invariant + B1 task declaration + shim (incremental), with
   **B5.4 "explain this tick" built alongside**.
3. B5 profiling (you cannot budget what you cannot measure).
4. B9 timescales + B3 dirty-tracking — the two biggest CPU wins.
5. B2 budgets/priorities + B10 locality; then B4 dormancy **with B4.4
   chaos testing from day one**.
6. B11 memory tiers + B12 history compression.
7. **B15.5 reference mode + B15.3 escalation ladder + B15.6 profile
   recording** — required *before* adaptive cognition ships.
8. B6 adaptive tuning → B7 hardware model → B8 prediction → B13
   hypotheses. Adaptation last: it needs the measurement and safety
   layers beneath it.

**HearthBench (parallel, independent):**
1. A1 skeleton + A1.2 firewall, A2 adapter Protocol over existing
   clients.
2. A3.1 fixture export (unblocks everything downstream).
3. A4.1 deterministic scorers + A5.7/A5.8 (grounding + structured
   output).
4. **A13 CI regression guard** — lands as soon as (3) works.
5. A7/A8 metrics + diagnostics; A11.4 resume.
6. A9 reports + A10 score; A12 UI; **C5 model passport**.
7. **A4.2 judge + remaining subjective categories — SHIPPED, v1.34.286**
   (A5.1-A5.6 all real now); A4.3 human calibration stays PARTIAL (the
   rating page is still A12.9, not attempted).
8. **A5.11 world-level run** — last, only after B15.5 exists.

# THE TESTS

- **HearthBench:** *Two people benchmark the same model on different
  machines and get the same category scores; a model that scores 85
  demonstrably produces a better sim than one that scores 65.*
- **Runtime:** *Toggle the runtime on/off, change every budget, enable
  aggressive dormancy — the LLM-off replay hash never changes, and the
  sim runs materially faster with lower memory.*

---

# DECISIONS RECORD (2026-07-23) — all resolved, all folded in

**Open questions:**

1. **Judge model → both.** Deterministic-only is a first-class run mode
   (`--no-judge`); the judge tier is additive. → **A4 intro, A13.1.**
2. **Fixture provenance → default (frozen export).** → **A3.1.**
3. **Determinism boundary → the sim adapts to hardware.** Body stays
   strictly replay-identical; cognition *breadth* scales with the
   machine — a five-rung escalation ladder (reorder → defer → slow →
   pause → *only then* reduce breadth, visibly, never silently). →
   **B15.2–B15.6.**

**Suggestions:** 1 ✅ world-level run (**A5.11**) · 2 ✅ CI regression
guard (**A13**) · 3 ✅ model passport (**C5**) · 4 ✅ explain-this-tick
(**B5.4**) · 5 ❌ power/battery profile — *declined* · 6 ✅ dormancy
chaos testing (**B4.4**).

**Three consequences of decision 3 worth holding onto**, because they
changed the shape of the plan rather than just adding items:

- **Same seed + different hardware = different stories.** Accepted and
  intended — every cross-machine comparison, including HearthBench's
  World Score, requires pinned-budget reference mode (B15.5), which is
  why A5.11 and B15.5 must ship together.
- **The runtime sets *how many*, the sim still decides *which*.**
  (B15.4.) Without that line, "adapt to hardware" would quietly move
  world-meaning decisions into the scheduler and break B0's prime
  invariant.
- **Degradation must be visible.** Rung 5 is a declared, logged, UI-
  surfaced state, recorded in the save (B15.6) — so when two runs
  diverge, the reason is documented rather than mysterious.
