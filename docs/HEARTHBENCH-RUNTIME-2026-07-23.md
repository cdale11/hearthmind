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
**[MISSING]** greenfield. Verified against v1.4.1 source.

**Headline status:** HearthBench has real foundations to reuse
(`OllamaClient`/`LlamaCppClient` behind `build_llm_client`, plus
`eval_harness`, `recorder`, `quality_labels`, `review_diagnostics`).
The Runtime is **nearly all greenfield** — whole-tick timing and LLM
backpressure exist, but there are no per-subsystem budgets, no
per-subsystem profiling, no dormancy or dirty-tracking, and no cadence
framework. Everything currently runs every tick because time passed,
which is precisely what Hard Rule 3 forbids.

---

# PART A — HEARTHBENCH

## A0 — Foundations to reuse, not rebuild [CONFIRMED, v1.34.161 — no new code, by the item's own text]

Each A0.x item's own wording is "formalize/share/reuse/lift... rather
than writing a new one" — deferred to A2/A4, not action items in
themselves. Re-verified each claim directly against current source
(v1.34.160) rather than trusting the doc's prior [PARTIAL] tag as-is:

- [x] **A0.1 — CONFIRMED.** `llm/client.py` has `OllamaClient`
  (line 266), `LlamaCppClient` (line 445), both behind `build_llm_
  client(config)` (line 725) — a real de-facto adapter layer.
  Formalizing it into A2's `ModelAdapter` Protocol remains open.
- [x] **A0.2 — CONFIRMED.** `llm/eval_harness.py` has `split_holdout`
  (hash-based held-out split), `build_golden_set` (stratified
  golden-prompt sampler, `GOLDEN_SET_MIN_SIZE`), and `check_
  regressions` (regression-threshold checker) — all real, all reusable
  by A4.4/A13.3 as-is rather than reimplemented.
- [x] **A0.3 — CONFIRMED.** `llm/recorder.py`'s `TrainingRecorder`
  writes exactly the four-layer schema (`structured_input` → `prompt`
  → `raw_completion` → `parsed_output`, `SCHEMA_VERSION = 1`,
  `structured_input_hash`) A0.3 describes — real, versioned, ready for
  A8.1's run-record format to reuse directly.
- [x] **A0.4 — CONFIRMED.** `llm/quality_labels.py` has `schema_valid`,
  `check_leaks`, `length_in_bounds`, `dialogue_responds`, `topic_
  novel`, combined by `label_example` — real per-example scorers, a
  direct A4 Tier-1-deterministic-scorer set once lifted into a shared
  library.
- [ ] **Rule — still open.** The shared `hearthmind.cognition_contract`
  package itself doesn't exist yet — that's real A2/A4 forward work
  (lifting the four confirmed pieces above into an importable location
  both `hearthmind` and `hearthbench` can share without either
  importing the other's runtime), not something A0 itself builds.

## A1 — Module layout & isolation [PARTIAL — A1.1/A1.2 shipped v1.34.160]

- [x] **A1.1 — Package skeleton — SHIPPED, v1.34.160.** `hearthbench/`
  as a sibling of `hearthmind/`, with the brief's modules as
  submodules: `runner/`, `adapters/`, `prompts/`, `tests/`,
  `validation/`, `metrics/`, `diagnostics/`, `reporting/`, `ui/` — each
  a reserved `__init__.py` naming its own future spec item, no logic
  yet. `pyproject.toml` gained a `bench = []` extra
  (`pip install -e .[bench]`) and `hearthbench*` in
  `tool.setuptools.packages.find`.
- [x] **A1.2 — Import firewall test — SHIPPED, v1.34.160.**
  `scripts/verify_hearthbench_isolation.py` — a standalone AST-based
  script (same convention as `verify_native_soak.py`/
  `verify_replay_hash.py`, not a unittest, per this project's own
  standing "don't add unit tests" rule) walking every `.py` file under
  both packages and asserting neither imports the other in the
  forbidden direction. Confirmed clean against the current tree (10
  hearthbench files, 129 hearthmind files, zero violations). Not yet
  wired into a CI pipeline (no CI exists in this repo to wire it into)
  — it's a manually-run gate for now, same as its siblings.
- [ ] **A1.3 — Process isolation.** Bench runs execute in a subprocess
  with their own model server config, so a benchmark can never contend
  with, pause, or corrupt a live sim. The UI page (A12) talks to a bench
  daemon, not the sim engine. Not attempted — needs A2 (adapter layer)
  and A11 (run modes) to exist first before there's a real process to
  isolate.
- [ ] **A1.3 — Process isolation.** Bench runs execute in a subprocess
  with their own model server config, so a benchmark can never contend
  with, pause, or corrupt a live sim. The UI page (A12) talks to a bench
  daemon, not the sim engine.

## A2 — Model Adapter Layer [PARTIAL]

- [ ] **A2.1 — `ModelAdapter` Protocol.** One interface all backends
  implement:
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
  being disqualified).
- [ ] **A2.2 — Three adapters at launch:** `LlamaCppAdapter` (wrapping
  the existing client + `/metrics` polling), `OllamaAdapter`,
  `OpenAICompatAdapter` (any `/v1/chat/completions`). Adapters are the
  *only* place model-specific logic may live — enforce with a lint rule
  banning model-name string comparisons outside `adapters/`.
- [ ] **A2.3 — Adapter conformance suite.** A test each new adapter must
  pass (schema honoring, token accounting, seed behavior, timeout,
  cancellation, error taxonomy). This is what makes "never modify
  Hearthmind simulation code when adding a new model" true in practice.
- [ ] **A2.4 — Server lifecycle management.** Optionally launch/stop the
  backend itself (llama-server with given flags), recording exact
  command line, so a run is reproducible from the stored record alone.

## A3 — Prompt Library & Test Definitions [MISSING]

- [ ] **A3.1 — Frozen prompt fixtures exported from the real sim.**
  **[DECIDED 2026-07-23: frozen export, as specced.]**
  The brief wants realistic prompts *and* isolation. Resolve by
  **exporting**, not importing at runtime: a `hearthbench export`
  command reads recorder archives + prompt builders and writes a
  versioned fixture pack (`fixtures/v1.4.1/*.json`) containing real
  `layer1_structured_input` + rendered prompts across every job type.
  Fixtures are frozen data, checked in, hash-identified. Bench runs are
  reproducible forever and comparable across models even after the sim's
  prompts evolve; a fixture-pack version bump is an explicit, reviewable
  event.
- [ ] **A3.2 — Test definition schema (declarative, data not code):**
  ```
  TestCase: id, category, fixture_ref, system_prompt, schema_ref,
            scorers[], weight, tags[], turns[] (multi-turn),
            expected_invariants[] (grounding facts that must hold),
            seed
  ```
  Adding a benchmark category = adding data + a scorer, never touching
  the runner. Satisfies "easy to extend."
- [ ] **A3.3 — Multi-turn & stateful cases.** Personality-stability and
  memory tests need conversation *sequences* with injected state between
  turns. The schema must support a scripted state timeline (turn 1
  establishes a fact; turn 7 tests recall; turn 12 offers a
  contradiction).
- [ ] **A3.4 — Synthetic perturbation.** Reuse `prompt_synthesis.py` to
  generate variants of fixtures (different stats, moods, belief sets) so
  a model can't be tuned to the exact fixture set, and so rare job types
  (town_brain, consciousness) get enough cases for a stable score.

## A4 — Scoring & the judge problem [MISSING] — *the central design decision*

**[DECIDED 2026-07-23: build both paths.]** Deterministic-only scoring
is a first-class, fully supported run mode (`--no-judge`), not a
degraded fallback — it is what CI (A13) and quick screening use, and it
runs anywhere with zero extra infrastructure. The judge tier is an
additive layer for the subjective categories when you want a full
picture. Both must produce a valid, clearly-labelled report:
`Score: 78.1 (deterministic-only; Dialogue/Personality unscored)` is a
legitimate result, never a broken one.

Categories like "naturalness" and "emotional realism" cannot be scored
by regex. Three scorer tiers, all recorded so any score is auditable:

- [ ] **A4.1 — Tier 1: deterministic scorers (always on, free).**
  Schema validity, parse/retry/fallback rate, latency/throughput,
  grounding-violation detection (named entity not in supplied state →
  hallucination), contradiction detection (turn-N output vs. established
  fact), repetition/self-similarity, lexical diversity, context-
  reflection rate (which supplied threads the output used), leak
  patterns (coordinates, scaffolding), length compliance. Lift from
  `quality_labels.py`. **These alone cover Grounding, Structured
  Outputs, Reliability, Performance, and much of Memory.**
- [ ] **A4.2 — Tier 2: judge-model scorers (optional, for the
  subjective categories).** A configurable, *separate* judge adapter
  (typically a larger model, run offline — it is not the model under
  test) scoring naturalness/personality/emotional-realism on a fixed
  rubric with few-shot anchors, forced to output a structured verdict
  with a one-line justification. **Requirements:** judge model + prompt
  version recorded in every run; the same judge must score all compared
  runs (never compare across judges); judge self-consistency measured by
  re-scoring a sample and reporting agreement. Where no judge is
  configured, subjective categories report "unscored" rather than being
  silently faked.
- [ ] **A4.3 — Tier 3: human rating UI (calibration ground truth).** A
  blind-pairwise page in the bench UI ("which of these two exchanges is
  more natural?") over stored outputs. Cheap to use occasionally, and it
  is the only way to know whether Tier 2 correlates with your taste.
  Report judge↔human agreement; when it drops, the judge rubric is
  wrong, not your taste.
- [ ] **A4.4 — Scorers are pure, versioned, registered.**
  `Scorer(id, version, fn(case, result, context) -> ScoreDetail)`.
  Scorer version is part of a run's identity, so a scoring change never
  silently reshuffles historical rankings.

## A5 — Benchmark categories [MISSING] — every one from the brief

Each becomes a category module with concrete cases and scorers.

- [ ] **A5.1 — Dialogue.** Naturalness, coherence (does line B answer
  line A — token/semantic overlap + judge), personality expression
  (does the line match the supplied voice/mind), emotional realism.
  Includes the failure mode this project has fought: aphorism ping-pong
  and mutual-agreement patterns → an explicit "ambient filler" penalty
  scorer.
- [ ] **A5.2 — Personality.** Stability across many conversations
  (variance of trait expression across N turns for one persona),
  long-term consistency (turn 1 vs turn 30), individual voice
  (distinguishability — can a classifier/judge tell two personas apart
  from output alone? a real, cheap metric).
- [ ] **A5.3 — Memory.** Recall (fact planted at turn k retrieved at
  turn n), appropriate forgetting (trivia should *not* dominate),
  contradiction resistance (reject or flag a fact that conflicts with
  established state), long-term integration (does an old memory inform
  a new judgment).
- [ ] **A5.4 — Beliefs.** Formation from evidence, revision when
  evidence flips, theory quality (specific and falsifiable vs. vague),
  confidence calibration (does stated confidence track evidence
  strength), reflection depth.
- [ ] **A5.5 — Planning.** Goal formation from state, multi-step
  coherence, horizon realism, adaptation when the plan is blocked.
- [ ] **A5.6 — Village cognition.** Cultural belief formation,
  village-level theories, institution reasoning, tradition
  crystallization, social reasoning over a supplied relationship graph.
- [ ] **A5.7 — Grounding.** *Never invents objective facts.* Adversarial
  cases: prompts that bait invention (ask about an unnamed neighbor, an
  unstated harvest number). Reward explicit uncertainty; heavily
  penalize confident fabrication. Given the project's Body/Mind law,
  weight this category highest (A10).
- [ ] **A5.8 — Structured outputs.** JSON validity, schema compliance,
  retry rate, parse failures, fallback rate — with and without
  grammar constraints, so the report shows how much the model relies on
  the sampler.
- [ ] **A5.9 — Performance.** Latency (p50/p95/max), TTFT, tokens/sec
  (prompt + completion separately), prompt/completion token counts, RAM,
  peak RAM, swap, CPU%. Sampled continuously during the run, attributed
  per case.
- [ ] **A5.10 — Category extension guide.** A short doc + template so a
  new category is: fixtures + scorers + weight entry. No runner changes.

- [ ] **A5.11 — World-level emergence run [APPROVED 2026-07-23].** The
  only test that measures what you actually care about: run a real
  fixed-seed simulation (e.g. 2k–5k ticks, LLM on) with the candidate
  model and score the *emergent output*, not the per-prompt output.
  - **Metrics:** cross-system causal chain length (the emergence metric
    from the prior audits), topic diversity, belief accuracy
    (village-belief vs. ground truth), want-resolution rate, dialogue
    ambient-filler share, invention adoption/abandonment ratio, and
    stability (no population collapse / governor pinned).
  - **Reported separately as a "World Score," not folded into the
    100-point composite.** Rationale: it has far higher variance and a
    much smaller N than the prompt categories, so blending it would
    corrupt a stable, comparable headline score. The report shows both:
    `HearthBench 82.4 ± 3.1 · World Score 71 (1 run, 3k ticks)`.
  - **Must run in reference mode (B15.5).** Cognition budget pinned to
    a fixed value so the run measures *the model*, not your machine —
    otherwise a faster host inflates the score. This is the direct
    consequence of the Q3 decision below; the two features have to be
    built together or the World Score is meaningless across machines.
  - **Isolation exception, declared explicitly.** This is the one place
    HearthBench must invoke the simulation. Keep it behind a separate
    optional entry point (`hearthbench.world`) that shells out to a sim
    subprocess via CLI — never an in-process import — so the A1.2 import
    firewall still holds for the core benchmark.
  - **Full runs only**, opt-in flag, with a prominent runtime warning.

## A6 — Structured Output Validator [PARTIAL]

- [ ] **A6.1** — Reuse the sim's `json_schemas.py` definitions via the
  shared contract package so bench validation is *identical* to
  production validation.
- [ ] **A6.2** — Record the full repair ladder per call: raw text →
  parse attempt → repair attempt → schema validation → fallback, with
  the reason at each rung. Retry/fallback rates are first-class metrics,
  not error logs.
- [ ] **A6.3** — Score both *constrained* and *unconstrained* modes when
  the adapter supports schemas, and report the delta. A model that only
  works under grammar constraints is a different risk profile than one
  that is natively reliable.

## A7 — Metrics Collector [MISSING]

- [ ] **A7.1** — Per-case metric record; per-category aggregate; per-run
  summary. All raw values retained (A8) so aggregates can be recomputed
  without re-running.
- [ ] **A7.2** — System sampling thread: RSS, peak RSS, swap, CPU%,
  plus backend-native metrics (llama-server `/metrics`: KV-cache usage,
  prompt/predicted tokens per second, slots busy). Sample on a timer,
  align to case boundaries.
- [ ] **A7.3** — Statistical hygiene: N per category, mean, median, p95,
  stdev, and a **confidence interval** — feeding the score-confidence
  requirement in A10/A11.

## A8 — Diagnostics: lose nothing [MISSING]

- [ ] **A8.1 — Run record** (one directory per run, JSONL + manifest):
  every raw prompt, raw completion, parsed JSON, validation error, retry
  attempt, fallback reason, timing, token counts, per-case scores with
  scorer versions.
- [ ] **A8.2 — Environment capture:** backend + version/commit, model
  file + hash + quantization, context size, sampler settings, all server
  flags, adapter version, fixture-pack version, scorer versions,
  benchmark version, seed, host summary (CPU model, cores, RAM, OS).
  The brief's bar: *future debugging possible from stored results
  alone* — that requires the environment, not just the outputs.
- [ ] **A8.3 — Content-addressed storage** for prompts/completions
  (hash-keyed) so repeated fixtures across runs don't multiply disk use.
- [ ] **A8.4 — Retention policy.** Runs are permanent by default;
  compression for old runs; explicit `--prune` only. Never auto-delete.

## A9 — Reports [MISSING]

- [ ] **A9.1 — HTML report** (self-contained, no server needed):
  overall recommendation in plain language, per-category scores with
  confidence, strengths, weaknesses, **failure examples with the actual
  prompt and output**, example conversations, example beliefs, example
  memories, example structured outputs, latency graphs, memory graphs,
  success rates.
- [ ] **A9.2 — JSON + CSV exports** of the same data (machine-readable
  for your own analysis; CSV flat per-case).
- [ ] **A9.3 — Comparison report:** N runs side by side, per-category
  deltas, significance flag when CIs overlap, and a "what changed"
  section (model? quant? fixture pack? scorer version?).
- [ ] **A9.4 — The recommendation must be honest.** If confidence is
  low, say so prominently; if a model wins on average but fails
  grounding, the recommendation says *don't use it* and explains why.
  A number that hides a disqualifying weakness is worse than no number.

## A10 — The HearthBench Score [MISSING]

- [ ] **A10.1 — Weighted composite, explained.** Proposed default
  weights, tuned to what actually determines Hearthmind's experience —
  every weight visible and overridable in config, and printed in the
  report next to the score:
  - Grounding **20** (the Body/Mind law; violations are fatal to the
    design)
  - Dialogue **15**
  - Beliefs **12**
  - Memory **12**
  - Village cognition **10**
  - Personality **10**
  - Planning **8**
  - Reliability / structured output **8**
  - Performance **5**
- [ ] **A10.2 — Disqualifying floors, not just weights.** Any category
  below its floor caps the overall score (e.g. grounding < 50 caps the
  total at 60) so a fast, fluent hallucinator cannot score well. State
  the cap and its reason in the report.
- [ ] **A10.3 — Normalization discipline.** Each category maps to 0–100
  via an explicit, versioned rubric (not a curve against other models),
  so scores are comparable across time and don't shift when you add a
  new model.
- [ ] **A10.4 — Confidence.** Report `Score: 82.4 ± 3.1 (Full run, N=420
  cases, judge=<model>)`. Quick runs carry visibly wider intervals.

## A11 — Run modes [MISSING]

- [ ] **A11.1 — Quick (minutes):** stratified subsample, deterministic
  scorers only, no judge; produces a screening score with wide CI.
  Purpose: "is this model worth a full run?"
- [ ] **A11.2 — Full (long):** complete fixture set, multi-turn cases,
  judge scoring, repeated sampling for variance. Purpose: the decision.
- [ ] **A11.3 — Custom:** category subset / single category (e.g.
  re-test grounding after a prompt change).
- [ ] **A11.4 — Resume.** Every completed case is committed to the run
  directory immediately; resume = skip completed case IDs. Cancellation
  is clean and resumable. (Non-negotiable at these latencies — a full
  run on a small local model is hours.)
- [ ] **A11.5 — Reproducibility.** Fixed seeds per case; temperature and
  sampler recorded; `--strict-repro` mode that fails the run if the
  adapter reports non-deterministic capability. Note honestly in the
  report that CPU/threading may still yield token-level nondeterminism.

## A12 — Web UI [MISSING]

- [ ] **A12.1** — New page in the existing Hearthmind UI, served by the
  bench daemon (A1.3), clearly marked as not part of the sim.
- [ ] **A12.2** — Select model/backend (adapter form driven by
  `describe()`/`capabilities()`), configure run (mode, categories,
  judge, seed), start.
- [ ] **A12.3** — Live progress (case i/N, ETA from measured latency),
  live log stream, per-category running scores.
- [ ] **A12.4** — Cancel + resume controls.
- [ ] **A12.5** — Browse previous runs (sortable table: model, quant,
  score, date, mode, confidence).
- [ ] **A12.6** — Compare runs (multi-select → A9.3 comparison view).
- [ ] **A12.7** — Drill into any case: prompt, completion, parsed
  output, scores with justifications, timing.
- [ ] **A12.8** — Download HTML/JSON/CSV.
- [ ] **A12.9** — The human-rating page (A4.3).

## A13 — Prompt-regression guard in CI [APPROVED 2026-07-23]

Catches the failure mode this project has hit repeatedly: a prompt edit
that silently degrades quality, discovered only weeks later in a review
pack.

- [ ] **A13.1 — Trigger:** any change under the prompt builders,
  `json_schemas.py`, or the shared cognition contract runs a Quick
  benchmark against a **pinned model + pinned quantization + pinned
  fixture pack**, deterministic scorers only (A4 `--no-judge`, so CI
  needs no judge infrastructure and stays fast).
- [ ] **A13.2 — Gate on the objective categories only:** grounding,
  structured-output validity, leak patterns, context-reflection,
  length compliance. Never gate on subjective scores — too noisy for CI.
- [ ] **A13.3 — Thresholds are relative to a stored baseline**, not
  absolute: fail on a regression beyond the stored confidence interval,
  not on an arbitrary number. Reuse `eval_harness`'s regression-threshold
  checker (A0.2) rather than writing a second one.
- [ ] **A13.4 — Baseline refresh is an explicit, reviewed commit** (like
  a snapshot-test update), so an intentional prompt improvement re-bases
  the guard deliberately and visibly.
- [ ] **A13.5 — Nightly deeper run** on the main branch (larger sample,
  optional judge) posting a trend line, so slow drift is visible even
  when every individual PR passes.

---

# PART B — THE ADAPTIVE RUNTIME

## B0 — The prime invariant [PARTIAL — B0.1/B0.2 shipped v1.34.161]

> **Gameplay systems declare *what* work exists. The runtime decides
> *when*, *where*, and *how* it executes. Gameplay never makes
> scheduling, threading, batching, or hardware decisions.**

- [x] **B0.1 — Adopt it as a written architectural law — SHIPPED,
  v1.34.161.** CLAUDE.md's "The Adaptive Runtime's prime invariant"
  section, placed right after "Preserve absolutely," same enforcement
  weight as the Body/Mind split.
- [x] **B0.2 — Enforce it mechanically — SHIPPED, v1.34.161.**
  `scripts/verify_runtime_invariant.py` (AST-based, same convention as
  `verify_hearthbench_isolation.py`): bans `threading`/`concurrent.
  futures` imports, `time.sleep(...)` calls, and executor/Thread/Timer
  construction inside `world/`/`agents/`/`settlement/`/`economy/`.
  Confirmed clean against the current tree (47 files, zero violations)
  and confirmed to actually catch a real violation (tested against a
  synthetic file exercising every banned pattern). "Scheduling
  arithmetic" from the item's own text is NOT separately checked — no
  principled AST pattern distinguishes ordinary domain math from
  scheduling math without a real B1 `Task` graph to compare against;
  left honestly unenforced rather than faked with a guess-prone
  heuristic.
- [ ] **B0.3 — Migration reality.** Today ~200 schedule points live
  inside `engine.py` and subsystems. Migrating them is the bulk of Part
  B and must be incremental (B1.4). Not an action item — a scoping
  note recorded in CLAUDE.md's new B0 section, unchanged.

## B1 — Task declaration & the work graph [PARTIAL — B1.1-B1.4 shipped v1.34.162, not yet wired into the live tick loop]

- [x] **B1.1 — `Task` descriptor — SHIPPED, v1.34.162.**
  `hearthmind/simulation/task_graph.py`'s frozen `Task` dataclass,
  exactly the doc's own shape: `id`, `subsystem`, `fn`, `timescale`,
  `priority_class` (new `PriorityClass` enum — a placeholder
  vocabulary until B2's scheduler exists to act on it), `reads`/
  `writes` (frozensets), `trigger` (`TriggerKind`: PERIODIC/ON_EVENT/
  ON_DIRTY/PREDICTED), `cost_hint`, `locality` (`Locality`: REGION/
  GLOBAL/ENTITY), `determinism` (`Determinism`: STRICT/REORDERABLE).
- [x] **B1.2 — Registry + dependency graph — SHIPPED, v1.34.162.**
  `TaskRegistry.register`/`topological_order` builds real edges from
  declared `reads`/`writes` overlaps (a write/read overlap gets a real
  directed edge; a symmetric write/write or legacy-wildcard conflict
  breaks the tie by task id) and rejects a genuine cycle at build time
  via `CycleError`, not silently.
- [x] **B1.3 — Deterministic ordering rule — SHIPPED, v1.34.162.**
  `topological_order()` is Kahn's algorithm always picking the
  lexicographically smallest ready task id — independent of
  registration order (verified directly: registering the same tasks in
  reverse order produces byte-identical output) and of any wall-clock/
  thread-completion signal (there is none in this pure-graph module).
- [x] **B1.4 — Incremental adoption — SHIPPED (the shim only), v1.34.162.**
  `Task.legacy(id, subsystem, fn)` — the escape hatch an un-migrated
  call site can use as-is, with `writes={LEGACY_WILDCARD}` so it always
  conflicts with (and thus stays in a real, stable total order behind/
  ahead of) every other task, including other legacy ones. **What
  "shipped" does NOT mean here**, stated plainly: no real subsystem has
  actually been migrated onto this graph yet, and the graph is not
  called from anywhere in `simulation/engine.py`'s real tick loop — the
  ~200 real schedule points (B0.3) are completely untouched. This pass
  ships the graph/registry/ordering machinery and the shim mechanism
  the future incremental migration will use; the migration itself, and
  B2's budgeted scheduler that would actually execute a `TaskRegistry`,
  remain fully open. Verified against `scripts/verify_replay_hash.py`
  in spirit only (nothing changed that a replay-hash check could catch
  — no engine code path was touched); a real per-subsystem migration
  pass must re-run it for real, per B1.4's own instruction.

## B2 — Budgets & scheduling [Hard Rules 2, 9] [PARTIAL — B2.1/B2.2/B2.3/B2.5 shipped v1.34.164, not yet wired into the live tick loop]

- [x] **B2.1 — Explicit per-subsystem execution budgets — SHIPPED
  (static form), v1.34.164.** `hearthmind/simulation/scheduler.py`'s
  `SubsystemBudget` (`seconds_per_tick`, real wall-clock measured via
  `time.perf_counter()` around each task's `fn()` call). "Adaptive
  (B6)" from the item's own text is NOT built — B6 (continuous
  profiling) doesn't exist yet, so this stays an honest static
  per-subsystem dial, not a faked adaptive one.
- [x] **B2.2 — Priority classes — SHIPPED, v1.34.164.** Reuses B1's
  `PriorityClass` enum (CRITICAL/STANDARD/DEFERRABLE/BACKGROUND/
  IDLE_ONLY). Bounded deferral: `DEFAULT_MAX_DEFERRALS` gives each
  class a real deferral-count ceiling; a task that hits it is
  force-run ("promoted") regardless of remaining budget — verified
  directly (a DEFERRABLE task deferred exactly `bound` times, then
  force-run and flagged `promoted` on the next tick). CRITICAL always
  runs, budget or not.
- [x] **B2.3 — Overrun policy — SHIPPED, v1.34.164.** A task that
  overruns its subsystem's remaining budget is DEFERRED (`TickReport.
  deferred`), never skipped — it stays a real candidate next tick.
  `SubsystemBudget.debt_seconds` accrues real overrun, never silently
  reset by `reset_tick()` — verified directly (debt strictly increases
  across two ticks of sustained overrun). No `/diagnostics/runtime`
  surface exists yet (that's B15) to expose it externally.
- [ ] **B2.4 — Attention-follows-change [Rule 9] — explicitly NOT
  attempted.** Its own text requires B10's timescales and B11's
  locality "to be honest" — neither exists. A per-region activity
  score built without real timescale/locality machinery behind it
  would be a guess dressed as a feature; left open rather than faked.
- [x] **B2.5 — Work-conserving — SHIPPED, v1.34.164.** `Scheduler.
  run_tick`'s optional `tick_time_budget_seconds` param: once every
  subsystem-budgeted task has run or deferred, genuinely spare overall
  tick time runs deferred BACKGROUND/IDLE_ONLY work within the SAME
  tick (`TickReport.ran_via_spare_capacity`) rather than waiting for a
  future one — verified directly (a budget-starved BACKGROUND task
  stays deferred with no spare-time budget given, but runs immediately
  once one is). Deliberately does NOT reallocate one subsystem's
  UNUSED per-subsystem budget to another subsystem's over-budget
  tasks — a subsystem's own dial stays its own; only genuinely
  UNSPENT overall tick time is worked-conserved.

**Not wired into the live tick loop this pass** — same discipline as
B1: no import from `scheduler.py` exists in `simulation/engine.py`,
and the scheduler has only ever been run against synthetic tasks
(`scripts/verify_scheduler.py`). It's real, tested infrastructure
ready for a future subsystem migration to actually use, not a
migration itself.

## B3 — Event-driven execution [Hard Rule 3] [PARTIAL — B3.1/B3.2 shipped v1.34.165, not yet wired into the live tick loop]

- [x] **B3.1 — Dirty tracking — SHIPPED, v1.34.165.** New
  `hearthmind/simulation/reactivity.py`'s `DirtyTracker`: every
  `writes[]` key gets a monotonic per-key VERSION bump (not a plain
  boolean flag — lets several independent `ON_DIRTY` readers of the
  same key each observe one write exactly once, on their own schedule,
  without racing to clear a shared bit first). `Scheduler.run_tick`
  gates EVERY task (all priority classes, before any budget logic) on
  a real `_is_due` check: an `ON_DIRTY` task with clean reads is
  `skipped_clean` and never touches the budget/deferral machinery at
  all — the actual CPU win the item's own text names. Verified
  directly (two independent readers each see one write exactly once
  and go clean immediately after; an `ON_DIRTY` task with no declared
  `reads` never fires at all — a real, documented edge case, not a
  bug: use `PERIODIC` for an unconditional task).
- [x] **B3.2 — Event bus — SHIPPED, v1.34.165.** `reactivity.py`'s
  `EventBus`: `publish(event_type)` queues a signal for the CURRENT
  tick only, `clear()` (called by the scheduler at tick end) drops it
  — deliberately one-shot, unlike `DirtyTracker`'s persistent
  versions, since a discrete "did this happen" event has no "still
  pending" concept once its tick has passed. `Task` gained an additive
  `event_types: frozenset[str]` field (default empty — every
  pre-B3 `Task`, including every `Task.legacy(...)`, is unaffected) an
  `ON_EVENT` task subscribes with. Verified directly (a subscribed
  task only runs on the tick its event was published, never before or
  after).
- [ ] **B3.3 — Audit polling — explicitly NOT attempted.** A real
  case-by-case audit of the ~200 live schedule points in `engine.py`
  (B0.3), each needing individual judgment plus live replay-hash
  verification to convert safely — not a mechanism to build. Real
  future work, same shape as B1.4's actual subsystem migration.

**Not wired into the live tick loop this pass** — same discipline as
B1/B2: no import from `reactivity.py` exists in `simulation/engine.py`,
and both primitives have only ever been exercised against synthetic
task sets (`scripts/verify_scheduler.py`, extended with 5 new B3
checks alongside the existing 5 B2 ones).

## B4 — Dormancy [Hard Rule 4] [PARTIAL — B4.1/B4.3/B4.4 shipped v1.34.166 (generic mechanism only, no real candidate migrated)]

- [x] **B4.1 — `Dormant` lifecycle — SHIPPED (mechanism only), v1.34.166.**
  New `hearthmind/simulation/dormancy.py`'s `DormancyManager`: real
  `ACTIVE -> DROWSY -> DORMANT -> ARCHIVED` state machine, `is_
  scheduled()` reads False only for DORMANT/ARCHIVED (DROWSY stays
  scheduled — the doc's own spectrum implies reduced attention, not
  zero, and B2.4's attention-follows-change, the real lever for that,
  doesn't exist yet). Wake triggers themselves (event/player-attention/
  scheduled-review) are the CALLER's responsibility to decide when to
  invoke `wake()` — this module supplies the state machine, not the
  three trigger sources. "State compressed" from the item's own text
  is NOT built — that's B12 (state compression), which doesn't exist
  yet; same honest-placeholder discipline as B2.1's "adaptive (B6)."
- [ ] **B4.2 — Candidates named in the brief — explicitly NOT
  attempted.** Forgotten traditions/inactive settlements/distant
  wildlife/unused ideas/idle institutions each need real, live-tested
  sleep/wake criteria touching actual `world/`/`agents/`/`settlement/`
  gameplay code — the same "one subsystem at a time, never big-bang"
  migration discipline B0.3/B1.4/B3.3 all defer for the same reason.
  Real future work; `DormancyManager` is ready for the first one to
  use whenever that migration starts.
- [x] **B4.3 — Semantic safety — SHIPPED, v1.34.166.** Baked directly
  into the API rather than left as a discipline to remember: `wake()`
  is the ONLY way to leave DORMANT/ARCHIVED and it ALWAYS returns the
  real elapsed-tick gap the entity was unscheduled for (0 for a safe
  no-op wake on an already-active entity) — a caller can silently
  ignore the return value, but can't accidentally not receive it.
  Verified directly (correct elapsed count across a sleep/wake pair;
  a second `sleep()` call while already dormant does NOT reset the
  original clock).
- [x] **B4.4 — Chaos testing for dormancy — SHIPPED (technique
  demonstrated, not yet pointed at a real subsystem), v1.34.166.**
  `scripts/verify_dormancy.py`'s `check_chaos_dormancy_matches_no_
  dormancy_baseline`: since no real candidate exists yet (B4.2), this
  demonstrates the exact technique the item asks for — random force-
  sleep/wake sequences across 20 seeds x 500 ticks against a synthetic
  accumulator entity, each asserted to produce the EXACT SAME final
  value as a no-dormancy baseline — proving B4.3's lossless-wake
  catch-up integration actually holds under adversarial random
  timing, not just in the straight-line lifecycle checks. Once a real
  B4.2 candidate exists, the same technique applies directly to it
  against `scripts/verify_replay_hash.py`'s real hash instead of a
  synthetic counter; wiring that up is real future work, not this
  pass's scope.

## B5 — Continuous profiling [Hard Rules 5, 15] [PARTIAL — B5.1/B5.2/B5.4 shipped v1.34.167]

- [x] **B5.1 — Per-task instrumentation, always on — SHIPPED (real
  subset), v1.34.167.** New `hearthmind/simulation/profiling.py`'s
  `TaskMetrics`, one entry per task, updated by `Scheduler` itself so
  no registered task can go unmetered (see B5.3 below): `call_count`,
  `error_count`, `skipped_clean_count`, `deferred_count`, `promoted_
  count`, `ran_via_spare_capacity_count`, `total_wall_seconds`, a
  bounded ring buffer of recent per-call wall times (`recent_wall_
  seconds`, `mean_wall_seconds()`), and a derived `idle_ratio()`. Of
  the item's own named list, "queue depth"/"cache hit rate" are
  honestly NOT tracked — no per-task queue or cache exists anywhere in
  this runtime for either to read from; "memory delta" is also not
  tracked — real per-call `tracemalloc` sampling is a genuine,
  not-yet-built follow-up, not silently skipped. Wall time doubles as
  the CPU-time proxy (this scheduler is single-threaded and
  synchronous, where the two are the same number). "Budget
  utilization"/"deferral debt" are already real and live on
  `SubsystemBudget` (B2.1/B2.3), not duplicated here.
- [x] **B5.2 — Low-overhead design — SHIPPED (measured, not just
  asserted), v1.34.167.** `scripts/verify_scheduler.py`'s `check_
  instrumentation_overhead_measured` times 50 tasks x 200 ticks under
  the real `Scheduler` against the same functions called bare, and
  PRINTS the real measured per-task-tick overhead (~12us on this
  environment's hardware) rather than assuming instrumentation is
  cheap — "a profiler that costs 5% must say so" now has a real number
  attached, checked against a sanity bound so a future accidental
  O(n²) regression would fail this script, not just look fine in review.
- [ ] **B5.3 — Expose everything at `/diagnostics/runtime` + dev
  console — explicitly NOT attempted.** There's no real engine
  subsystem running through `Scheduler` yet to expose (same "not wired
  into the live tick loop" reason every prior B-item gives). The "no
  subsystem may be a black box" review rule is instead a real
  STRUCTURAL guarantee in this design, not a CI policy: `Scheduler.
  metrics_for`/`all_metrics` mean every task processed even once
  already has a real `TaskMetrics` entry — there is no code path for a
  registered task to skip being metered, so a CI rule enforcing it
  would have nothing to catch.
- [x] **B5.4 — "Explain this tick" — SHIPPED, v1.34.167.** New
  `profiling.py`'s `TickTrace`/`TaskTraceEntry`: `Scheduler.run_tick`
  now builds a full trace EVERY tick (not an opt-in "profiling mode")
  recording, per task, its real outcome (`ran`/`deferred`/`skipped_
  clean`/`error`) and a SPECIFIC reason string naming which trigger
  fired and why (e.g. `"ON_DIRTY: reads ['soil'] changed since last
  observed"`, `"budget exhausted for 'x' (remaining=0.000000s)"`,
  `"deferral bound reached (3 >= 3) -- force-run"`), plus real cost
  and the promoted/spare-capacity flags — appended to a bounded ring
  buffer (`Scheduler.tick_traces`, `TICK_TRACE_HISTORY=500`), matching
  the item's own "ring buffer of the last N tick-traces (cheap,
  bounded)" implementation note. **Built alongside B2/B3 rather than
  after**, honoring the item's own "build it with B1, not after" —
  this ships in the same pass the scheduling logic it explains was
  extended, not as a bolt-on later. The item's second half — an
  on-demand "trace next tick in FULL detail" toggle for something more
  expensive than the always-on trace — is NOT built: at this module's
  current abstraction (no real task arguments/state to snapshot) there
  is nothing genuinely heavier to capture yet; a toggle with nothing
  extra behind it would be theater, so it's left honestly unbuilt
  rather than faked. The emergence-lens framing (pairing this with a
  causal-chain metric) is out of scope — no causal-chain metric exists
  in this runtime yet.

## B6 — Adaptive tuning [Hard Rule 6] [PARTIAL — B6.1/B6.2/B6.3 shipped v1.34.168, not wired into any real control point]

- [x] **B6.1 — Tunables registry — SHIPPED, v1.34.168.** New
  `hearthmind/simulation/tuning.py`'s `Tunable`/`TunableRegistry`: a
  real legal range (`min_value`/`max_value`), a step size, and a
  `SafetyClass` (`SAFE`/`SENSITIVE`) per tunable — `adjust`/`set_value`
  always clamp to range, verified directly (repeated adjustment past
  either bound never overshoots).
- [x] **B6.2 — Controllers — SHIPPED (bang-bang only), v1.34.168.**
  `BangBangController`: pushes a named tunable one step toward a
  target with a real hysteresis dead-zone (verified: several readings
  inside the band produce zero change, not just "small" change) — the
  doc's own "PID-ish OR bang-bang" gave a real choice; bang-bang was
  picked as the simpler, more directly testable of the two. Genuinely
  deterministic, no LLM anywhere in this module, matching the item's
  own explicit instruction — see CLAUDE.md's v1.34.168 entry for the
  broader LLM/ML-candidate audit this pass also ran, which reaches the
  same "classical control, not a trained model" conclusion
  independently.
- [x] **B6.3 — Existing LLM pacing folds in here — SHIPPED (metadata
  only), v1.34.168.** `register_llm_pacing_tunables` registers the
  real existing `llm_pressure_*`/`llm_max_concurrent` constants
  (CLAUDE.md's own long-documented lineage) as a real `Tunable` set
  under this general framework — all `SENSITIVE`, all with real
  descriptions. This does NOT rewire `simulation/engine.py`'s actual
  pacing code to read from the registry — that's a real migration
  needing the same kind of live-diagnostic verification every past
  retune of these exact constants has needed, not something to flip
  blind in this pass (same "one subsystem at a time" discipline as
  every prior B-item's real migration work).

## B7 — Hardware model [Hard Rule 7] [PARTIAL — B7.1-B7.4 shipped v1.34.173, not wired into any real control point]

- [x] **B7.1 — Host probe — SHIPPED, v1.34.173.** New
  `hearthmind/simulation/hardware_profile.py`'s `HostProbe.sample()`:
  logical + usable (`os.sched_getaffinity`, cgroup/taskset-aware, same
  discipline as `setup.py`'s parallel-build core count) cores, RAM
  total/available + swap (reuses the `/proc/meminfo` parsing shape
  `system_memory_report()` already established in `engine.py`, kept as
  a fresh standalone read rather than importing engine.py), 1-minute
  load average, a small (4 MiB) storage write/read micro-benchmark,
  best-effort GPU presence (`/proc/driver/nvidia`) and thermal state
  (`/sys/class/thermal`, "throttled" past 90°C). Zero new dependency;
  every field degrades to `None` rather than raising when unavailable
  on this platform/kernel — a probe must never be able to crash the
  process that calls it. NUMA nodes and true physical-vs-logical core
  counts are NOT distinguished (would need a real dependency or manual
  `/sys/devices/system/cpu` topology parsing beyond this pass's scope)
  — `usable_cores` is the honest, already-useful substitute.
- [x] **B7.2 — Persistent machine profile — SHIPPED, v1.34.173.**
  `MachineProfile`, keyed by `host_fingerprint()` (hostname + cpu_count
  + machine arch, stable across runs on the same host). Every measured
  field (`measured_llm_throughput_tokens_per_s`, `optimal_worker_
  count`, `storage_write_mb_s`/`storage_read_mb_s`) is an exponential
  moving average across sessions (`record_llm_throughput`/`record_
  storage_benchmark`), not a flat overwrite — "gradually evolves,"
  verified directly (a single new sample moves the average partway,
  never all the way; a sustained new value converges the average to
  it). Versioned JSON blob `save`/`load`, same "ship as data" discipline
  the ML weight blobs already use, incl. rejecting an unsupported
  `schema_version`.
- [x] **B7.3 — Strategy selection — SHIPPED, v1.34.173.**
  `select_strategy(probe, profile=None)`: a pure function over profile
  data (never a hardware-specific branch baked into gameplay code, per
  the item's own text) producing `llm_max_concurrent_hint`/`worker_
  count_hint`/`cache_size_hint`/`dormancy_aggressiveness`. Verified
  directly: a many-core/high-RAM host gets more concurrency/workers/
  cache than a modest one; memory pressure, active swap, or thermal
  throttling all lower concurrency and raise dormancy aggressiveness
  regardless of how beefy the raw hardware otherwise reads; a
  `MachineProfile`'s own measured `optimal_worker_count` overrides the
  generic hint once one exists.
- [x] **B7.4 — Host-OS citizenship — SHIPPED, v1.34.173.**
  `GoodCitizenPolicy` (`Aggressiveness.CONSERVATIVE`/`BALANCED`/
  `AGGRESSIVE`, each with its own memory-headroom fraction and load
  multiplier threshold): `should_back_off(probe)` — verified directly
  that a conservative policy backs off at moderate memory pressure or
  ANY active swap use while an aggressive policy tolerates both, that
  extreme external load or thermal throttling trigger back-off
  regardless of aggressiveness setting, and that a genuinely healthy
  reading never backs off under any setting. "Lower priority for
  background work" itself needs a real scheduler to lower priority
  IN — that's B2's job, not this module's; `should_back_off` is the
  input signal such a scheduler would consult, not the mechanism.

**Not wired into any real control point** — same "never big-bang"
discipline as every prior B-item: no import from `hardware_profile.py`
exists in `simulation/engine.py` or `server.py`, `select_strategy`'s
output isn't consulted by any real LLM-concurrency/scheduling code
yet, and no `MachineProfile` is ever actually persisted/loaded across
a real server run. Real future work, naturally paired with B6.3's own
already-registered `llm_pressure_*`/`llm_max_concurrent` tunables once
a real migration pass wires either.

## B8 — Predictive scheduling [Hard Rule 8] [PARTIAL — B8.1-B8.4 shipped v1.34.174, not wired into any real control point]

- [x] **B8.1 — Workload forecaster — SHIPPED, v1.34.174.** New
  `hearthmind/simulation/forecasting.py`'s `WorkloadForecaster`: a
  small `hearthmind.ml.primitives.MLP` regressor over a generic
  `WORKLOAD_FORECAST_SCHEMA` (backlog, recent dialogue/cognition rate,
  active-disaster flag, festival-scheduled flag, season) — the item's
  own three named triggers (storm → dialogue/cognition spike, harvest
  season → economy surge, a scheduled festival → event burst) map
  directly onto this vector; a new trigger is a schema field, never a
  new pipeline. Verified directly: training measurably cuts loss on a
  synthetic ground truth, and the trained model correctly predicts
  higher load when `active_disaster=1` than otherwise. **Explicit user
  instruction, same pass: "the AI/ML models should learn from all
  previous runs if possible."** New `hearthmind/ml/cross_run.py`'s
  `pool_examples_across_runs`/`discover_runs`: pools training examples
  from every past-run archive found under a `runs_root` directory (a
  caller-supplied `example_loader` per run, tolerant of a corrupted/
  unreadable run — skipped, not fatal), capped per-run and in total via
  uniform random sampling so one unusually large run can't drown out
  every other one. This is deliberately distinct from L5's per-world
  continual-learning loop (`hearthmind/ml/lifelong.py`) — L5 keeps ONE
  world's own Mind models learning across its own lifetime (and stays
  per-world by `docs/ML-ARCHITECTURE-2026-08-01.md`'s guardrail #3);
  cross-run pooling is for models that describe the MACHINE, not any
  one world's cognition, so nothing prevents them from learning across
  every run that has ever happened on this host. Verified end-to-end: a
  `WorkloadForecaster` trained on a pool assembled from three synthetic
  past-run directories learns just as well as one trained on a single
  run's worth of data.
- [x] **B8.2 — Reservation mechanism — SHIPPED, v1.34.174.**
  `plan_reservation(predicted_load, current_capacity, reliability_
  weight)`: a deterministic, capacity-bounded hint (never a hard
  block) — verified to scale with both predicted load and reliability,
  never exceed capacity, and reserve nothing at zero reliability. The
  actual "fill reserved capacity with cheap-to-preempt background
  work" mechanism is B2's own job (its `PriorityClass`/deferral
  machinery already exists) — this ships the reservation SIZE
  computation, not a second scheduler.
- [x] **B8.3 — Forecast accuracy tracking — SHIPPED, v1.34.174.**
  `ForecastAccuracyTracker`: a bounded (predicted, actual) history plus
  `reliability_weight()`, scaled against the MAE of a naive "always
  predict the historical mean" baseline — a forecaster doing no better
  than that baseline scores 0.0 (full distrust), a perfect one scores
  1.0. Verified directly: an accurate forecaster scores high, a
  consistently-wrong one scores low, a fresh tracker with no evidence
  yet defaults to full trust rather than false distrust.
- [x] **B8.4 — Idle-window scheduling — SHIPPED, v1.34.174.**
  `is_quiet_window(recent_loads, capacity, threshold_fraction)`: a
  plain deterministic read of recent load history — true only when
  EVERY recent reading stayed below the threshold fraction of
  capacity, so a single spike correctly breaks "quiet."

**Not wired into any real control point** — same "never big-bang"
discipline as every prior B-item: no import from `forecasting.py`/
`cross_run.py` exists in `simulation/engine.py`/`server.py`, no real
recorder/metrics archive is ever fed through `pool_examples_across_
runs`, and `plan_reservation`'s output isn't consulted by B2's real
scheduler. Real future work, naturally paired with B7's own unwired
`select_strategy`/`GoodCitizenPolicy` once a real migration pass wires
the Runtime modules into the live tick loop.

## B9 — Hierarchical timescales [Hard Rule 10] [PARTIAL — B9.1/B9.2 shipped v1.34.175, B9.3 (the real audit) not attempted]

- [x] **B9.1 — Declared timescale per task — SHIPPED, v1.34.175.** New
  `hearthmind/simulation/timescales.py`'s `TimescaleLadder`: the doc's
  own named ladder (tick → minute → hour → day → week → month → season
  → year), with every rung's minimum real-tick interval DERIVED from a
  world's own calendar shape — the same `sim_minutes_per_tick`/
  `minutes_per_day`/`days_per_month` conventions `SimClock` itself uses
  — rather than a guessed constant; verified directly against hand-
  computed calendar math (1440 min/day at 5 sim-min/tick = exactly 288
  ticks/day) and that a faster tick rate produces a correspondingly
  larger tick-count floor for the same real calendar day. `enforce
  (timescale, requested_interval)` is the real enforcement the item's
  own text asks for: a task's own configured interval can never be
  shorter than its declared timescale's calendar floor — a per-tick
  request against a "day" timescale is clamped up to the real floor,
  not merely warned about.
- [x] **B9.2 — Elapsed-time integration — SHIPPED, v1.34.175.**
  `ElapsedTimeTracker` generalizes `DormancyManager.wake()`'s own
  "always return the real elapsed tick count" contract (B4.3) beyond
  dormancy specifically — `elapsed_since` is non-mutating (repeated
  peeks report the same value, verified directly) and returns `None`
  rather than `0` for a task with no prior baseline (there is
  genuinely no history to integrate from yet, a different case from
  "zero time has passed"). `TimescaleGate.check` combines both halves
  into the one call a real scheduled task would make: verified a
  brand-new task never fires on its first observation, fires exactly
  once its declared timescale's real floor has elapsed, and that
  elapsed time is measured from the last REAL firing (not from an
  intervening no-op check) — the property that makes "running a slow
  system less often is mathematically equivalent, not an
  approximation" actually true for a generic consumer. Also verified
  two tasks at different declared timescales (daily vs. monthly)
  behave fully independently against the same ladder.
- [ ] **B9.3 — Audit every current subsystem** for timescale mismatch
  — explicitly NOT attempted this pass, same "needs individual live
  judgment, not a mechanism" class as B3.3's own audit deferral. This
  pass ships the tool such an audit would use to convert a finding
  into a real enforced timescale, not the audit itself.

**Not wired into any real control point** — no import from
`timescales.py` exists in `simulation/engine.py`, and `Task.timescale`
(the free-string field B1 already added) is not yet cross-checked
against a real `TimescaleLadder` anywhere. Real future work, naturally
paired with B9.3's own still-open audit and the rest of the unwired
Runtime modules (B2 through B8) once a real migration pass begins.

## B10 — Locality [Hard Rule 11] [PARTIAL — B10.1/B10.3 shipped v1.34.177, B10.2 (the real audit/conversion) not attempted; its discovery tool shipped]

- [x] **B10.1 — Spatial index / region partition — SHIPPED, v1.34.177.**
  New `hearthmind/simulation/locality.py`'s `RegionGrid`: a uniform-
  grid spatial partition (grid, not quadtree — the item's own text
  offers either, grid is the simpler, more directly testable choice,
  same reasoning B6.2 used picking bang-bang over PID). `region_key`
  is the real integration point with B1: tagging a `Task`'s declared
  `reads`/`writes` with its region (`f"{base_key}@{region_id}"`) means
  the dependency graph `TaskRegistry` (B1.2) ALREADY builds from
  read/write overlap naturally treats two different regions as
  non-conflicting — verified directly against the real `TaskRegistry`,
  not a parallel mechanism. `Locality.REGION` (already on `Task` since
  B1.1) now has real semantics rather than being an inert enum value.
- [ ] **B10.2 — Ban global scans in hot paths** — the real audit/
  conversion explicitly NOT attempted this pass, same "needs
  individual live judgment, not a mechanism" class as B3.3/B9.3's own
  deferrals (is a given flagged loop actually hot? does an index
  already exist to query instead? is O(population) fine because it's
  monthly?). **The discovery tool such an audit would use SHIPPED,
  v1.34.177**: `scripts/scan_global_scans.py`, a static AST scanner
  over `world/`/`agents/`/`settlement/`/`economy/` flagging two
  candidate patterns (a loop over a known full-collection attribute —
  `.agents`/`.buildings`/`.tiles`/etc. — and a nested `range()`-over-
  `range()` double loop). Always informational, always exits 0 — run
  against the real tree this pass and found 89 candidate sites,
  matching the item's own "expect large, immediate CPU wins here."
  Converting any of them remains real, unscoped future work.
- [x] **B10.3 — Region-parallel execution — SHIPPED, v1.34.177.**
  `plan_region_parallel_batches`/`find_cross_region_write_conflicts`:
  groups region-tagged tasks by region and VERIFIES (not assumes) the
  partition is genuinely write-disjoint across regions before treating
  it as parallel-safe — catches a task incorrectly declared `Locality.
  REGION` that actually writes an untagged/global key, verified
  directly with a deliberately-broken synthetic task. Returns the
  grouping/safety-check result only — no real threading or execution
  happens here (B0's prime invariant bans real threading in `world/`/
  `agents/`/`settlement/`/`economy/`; this module lives in
  `simulation/` but still stays a planning primitive, not an executor,
  same "never big-bang" discipline as every sibling module).

**Not wired into any real control point** — no import from
`locality.py` exists in `simulation/engine.py`, and no real `Task`
anywhere declares `Locality.REGION` yet (only B1.4's `Task.legacy`
wildcard-write tasks exist in practice today). Real future work,
naturally paired with B2.4's attention allocation (the doc's own named
partner for B10.3) and B10.2's still-open real audit.

## B11 — Hierarchical memory [Hard Rule 12] [MISSING]

- [ ] **B11.1 — Four tiers with explicit migration policy:** hot
  (in-memory, active), warm (in-memory, compact/compressed), cold
  (on-disk, lazily loaded), archive (compressed, rarely touched).
- [ ] **B11.2 — Access-driven migration:** LRU/frequency demotion,
  fault-in on access, migration performed in idle windows (B8.4).
- [ ] **B11.3 — Transparent handles** so gameplay code touches state
  without knowing its tier (a cold read blocks and promotes; gameplay
  never manages memory — B0).
- [ ] **B11.4 — Memory-pressure response:** under host pressure, demote
  aggressively rather than letting the OS swap (B7.4). Current diagnostics
  already show swap in use — this is a live problem, not a theoretical one.

## B12 — History compression [Hard Rule 13] [PARTIAL]

- [ ] **B12.1 — The ladder as an automatic pipeline:** raw events →
  episodes → summaries → history → cultural memory, each stage
  triggered by age/volume thresholds, each bounded.
- [ ] **B12.2 — Reuse the existing narrative pipeline** (chronicle →
  documentary → culture-digest, folklore, era branches) as the semantic
  half; add the *storage* half — raw events must actually be discarded
  or archived after summarization, with a hard ceiling on total history
  size. **Never allow unbounded growth** (the DB is already ~60 MB).
- [ ] **B12.3 — Reconstruct-on-demand:** archived detail retrievable for
  the UI/debugging, at a latency cost, so compression is not loss.

## B13 — Optimization hypotheses [Hard Rule 14] [MISSING]

- [ ] **B13.1 — Hypothesis loop:** observe → hypothesize ("ecology at 45
  min instead of 30 may cut CPU without changing outcomes") → apply
  behind a flag → measure → **keep or roll back**, all recorded.
- [ ] **B13.2 — Semantic-safety gate:** any `sensitive` tunable change
  must pass a replay-hash equivalence check (B17.1) on a forked run
  before it is kept. A performance win that changes outcomes is
  automatically rejected — no judgment call.
- [ ] **B13.3 — Adaptation history** as a first-class, browsable record:
  what was tried, measured, kept, rolled back, and why.
- [ ] **B13.4 — Strict separation from Reflection.** The Runtime
  optimizes *execution*; Reflection (the pillar) optimizes *world
  balance*. They must never touch each other's tunables. Write this as
  an invariant — two self-modifying systems with overlapping authority
  is the single most dangerous failure mode in this design.
- [ ] **B13.5 — Optional evolutionary search** over multi-dimensional
  tunable sets (the doc's suggestion): population of configurations,
  fitness = throughput under the semantic-safety constraint. Only after
  B13.1–B13.2 are solid.

## B14 — Persistence & background work [MISSING]

- [ ] **B14.1** — Snapshot/persistence becomes a scheduled, budgeted,
  idle-preferring task with adaptive frequency (B6.1) rather than a
  fixed cadence.
- [ ] **B14.2** — Incremental/differential snapshots to cut write cost
  and storage; full snapshot on a longer cycle.
- [ ] **B14.3** — Storage-speed-aware batching from the machine profile
  (B7.2).

## B15 — Semantic safety: the determinism guarantee [Hard Rule 1]

*This deserves its own section because Hard Rule 1 and adaptive LLM
scheduling are in genuine tension, and the resolution must be explicit.*

- [ ] **B15.1 — Replay-hash equivalence test in CI.** Same seed, LLM
  off, N ticks → identical world-state hash, with the runtime enabled
  and disabled, and across different budget/tunable settings. This is
  the mechanical proof of "never change simulation semantics" for the
  deterministic core.
- [ ] **B15.2 — The two-part guarantee [DECIDED 2026-07-23: the sim
  adapts to hardware].** You chose hardware adaptation over cross-machine
  story-identity, so the boundary is drawn here:
  - **Strict (non-negotiable):** the deterministic **Body** is
    replay-identical regardless of any runtime decision — budgets,
    dormancy, batching, parallelism, host. This is what makes bugs
    reproducible and B13's rollback test meaningful. It never bends.
  - **Adaptive (by design):** **cognition breadth may scale with the
    machine.** A 4-core laptop runs fewer Tier-2 agents and longer pillar
    cadences than a 32-core desktop; both are *correct*, neither is
    degraded. The world thinks as richly as the host allows.
  - **The accepted consequence, stated plainly:** the same seed on
    different hardware produces *different stories*. That is the intended
    trade — the alternative is running every machine at the weakest
    machine's budget. Sim-level A/B testing must therefore pin the budget
    (B15.5), and save files must record the profile (B15.6).

- [ ] **B15.3 — The escalation ladder** — reconciling "adapt to
  hardware" with your standing instruction to *slow or pause when the
  LLM lags*. Under pressure the runtime escalates **in this order**,
  never skipping a rung, and each rung is logged:
  1. **Reorder / batch** — free, zero semantic effect.
  2. **Defer within deadline** — bounded, nothing dropped.
  3. **Slow sim-time** — the world thinks *the same*, just slower. Your
     stated default; the existing `llm_pressure` slowdown band already
     implements this rung.
  4. **Pause** — "the town is thinking." Already implemented.
  5. **Reduce cognition breadth** — fewer Tier-2 agents, longer pillar
     cadences, shallower loops. **Only** when rungs 1–4 are exhausted or
     the host profile shows sustained inadequacy (not a transient spike),
     and only as a *declared, visible, logged* degradation with a UI
     indicator. Never silent.
  Rung 5 is the one your Q3 answer unlocks; rungs 1–4 stay first so a
  brief spike never costs you a thought.

- [ ] **B15.4 — Selection stays a simulation decision; only *how many*
  is the runtime's.** Even at rung 5, the runtime sets the *budget*
  (how many cognitions this window) — the simulation still decides
  *which* agents/pillars fill it, by its own salience rules. This keeps
  the story's logic in the sim and the resource math in the runtime,
  preserving B0's prime invariant. Without this line, "adapt to
  hardware" would leak world-meaning decisions into the scheduler.

- [ ] **B15.5 — Reference mode.** A pinned-budget execution profile
  (fixed cognition-per-window, fixed cadences, adaptation disabled) used
  by HearthBench's world-level run (A5.11), sim-level A/B tests, and
  any cross-machine comparison. Without it, adaptive cognition makes
  every comparative measurement meaningless. **Build this alongside
  B15.2, not after.**

- [ ] **B15.6 — Record the profile in the save and the diagnostics:**
  host fingerprint, effective cognition budget, and the full rung-5
  degradation history. When two runs of the same seed diverge, this is
  what explains why — and it makes the divergence a documented property
  rather than a mystery.
- [ ] **B15.7 — Fuzz the scheduler.** Randomize task ordering within
  declared-safe bounds, budgets, and dormancy aggressiveness; assert the
  replay hash is invariant. This catches an illegal hidden dependency
  far better than review. Pairs with the dormancy chaos test (B4.4).
- [ ] **B15.8 — Semantic-safety class on every tunable** (B6.1), checked
  at registration.

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

- [ ] **C5 — The model passport [APPROVED 2026-07-23].** HearthBench
  emits a small, portable `passport.json` per benchmarked model that the
  **runtime reads at startup** to configure itself — closing the C2 loop
  automatically instead of by hand.
  - **Contents:** model id + quantization + file hash; HearthBench and
    World scores with confidence; per-category strengths/weaknesses;
    measured throughput (prompt tok/s, completion tok/s, TTFT, latency
    p50/p95) and peak RSS at each concurrency level tested; **recommended
    settings** (concurrency, context size, batch, whether it needs
    grammar constraints to be reliable); and hard warnings (e.g. "fails
    grounding — not recommended").
  - **Runtime consumption:** on startup the runtime matches the
    configured model to a passport and seeds its machine profile (B7.2)
    with those priors instead of learning throughput from scratch over
    the first hour. Passport values are *priors*, not overrides — B6's
    controllers still adapt from live measurement, since your machine's
    state differs from the bench machine's.
  - **Safety interlock:** if the passport carries a hard warning, the
    runtime surfaces it in the UI at startup rather than silently running
    a model known to hallucinate facts. A grounding failure is a
    world-integrity problem, not a performance note.
  - **Provenance:** passports record which host produced them; a
    passport from a very different machine contributes throughput priors
    with lower weight.

# SEQUENCE

**Runtime (highest immediate value, since it is nearly all greenfield):**
1. B15.1 replay-hash test *first* — the safety net every later change
   leans on.
2. B0 prime invariant + B1 task declaration + shim (incremental), with
   **B5.4 "explain this tick" built alongside** — the moment scheduling
   becomes conditional you will need it daily.
3. B5 profiling (you cannot budget what you cannot measure).
4. B9 timescales + B3 dirty-tracking — the two biggest CPU wins.
5. B2 budgets/priorities + B10 locality; then B4 dormancy **with B4.4
   chaos testing from day one** (dormancy bugs are silent).
6. B11 memory tiers + B12 history compression (the DB and swap pressure
   are real today).
7. **B15.5 reference mode + B15.3 escalation ladder + B15.6 profile
   recording** — required *before* adaptive cognition ships, or nothing
   is measurable across machines.
8. B6 adaptive tuning → B7 hardware model → B8 prediction → B13
   hypotheses. Adaptation last: it needs the measurement and safety
   layers beneath it.

**HearthBench (parallel, independent):**
1. A1 skeleton + A1.2 firewall, A2 adapter Protocol over existing
   clients.
2. A3.1 fixture export (unblocks everything downstream).
3. A4.1 deterministic scorers + A5.7/A5.8 (grounding + structured
   output) — the categories that need no judge and matter most.
4. **A13 CI regression guard** — lands as soon as (3) works; it is the
   cheapest item on this list and it protects every future prompt edit.
5. A7/A8 metrics + diagnostics; A11.4 resume.
6. A9 reports + A10 score; A12 UI; **C5 model passport** (trivial once
   the report exists, and it is what makes the runtime benefit).
7. A4.2 judge + remaining subjective categories; A4.3 human calibration.
8. **A5.11 world-level run** — last, and only after B15.5 reference mode
   exists on the runtime side.

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
   (`--no-judge`), used by CI and quick screening; the judge tier is an
   additive layer for subjective categories. Both produce valid,
   clearly-labelled reports. → **A4 intro, A13.1.**
2. **Fixture provenance → default (frozen export).** → **A3.1.**
3. **Determinism boundary → the sim adapts to hardware.** Body stays
   strictly replay-identical; cognition *breadth* scales with the
   machine. Reconciled with your standing "slow or pause when the LLM
   lags" instruction as a five-rung escalation ladder — reorder → defer
   → slow → pause → *only then* reduce breadth, visibly and never
   silently. → **B15.2–B15.6.**

**Suggestions:** 1 ✅ world-level run (**A5.11**) · 2 ✅ CI regression
guard (**A13**) · 3 ✅ model passport (**C5**) · 4 ✅ explain-this-tick
(**B5.4**) · 5 ❌ power/battery profile — *declined* · 6 ✅ dormancy
chaos testing (**B4.4**).

**Note on the declined item:** I removed only *my addition* — a
first-class power/battery strategy with a UI toggle. Your own
`runtime_opt.md` lists thermal behavior, power state, and battery-aware
sleeping under hardware awareness, so **B7.1's probe and B7.3's
thermal/battery strategy examples remain** as specced. If you meant to
drop those too, say so and I will strip them from B7.

**Three consequences of decision 3 worth holding onto**, because they
changed the shape of the plan rather than just adding items:

- **Same seed + different hardware = different stories.** Accepted and
  intended. It also means every cross-machine comparison — including
  HearthBench's World Score — requires pinned-budget reference mode
  (B15.5). That is why A5.11 and B15.5 must ship together; either alone
  is misleading.
- **The runtime sets *how many*, the sim still decides *which*.**
  (B15.4.) Without that line, "adapt to hardware" would quietly move
  world-meaning decisions into the scheduler and break B0's prime
  invariant.
- **Degradation must be visible.** Rung 5 is a declared, logged, UI-
  surfaced state, recorded in the save (B15.6) — so when two runs
  diverge, the reason is documented rather than mysterious.
