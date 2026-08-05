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

## A1 — Module layout & isolation [PARTIAL — A1.1/A1.2 shipped v1.34.160]

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
- [ ] **A1.3 — Process isolation.** Bench runs execute in a subprocess
  with their own model server config, so a benchmark can never contend
  with, pause, or corrupt a live sim. The UI page (A12) talks to a bench
  daemon, not the sim engine. Not attempted — needs A2 (adapter layer)
  and A11 (run modes) to exist first.

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
  cancellation, error taxonomy).
- [ ] **A2.4 — Server lifecycle management.** Optionally launch/stop the
  backend itself (llama-server with given flags), recording exact
  command line, so a run is reproducible from the stored record alone.

## A3 — Prompt Library & Test Definitions [MISSING]

- [ ] **A3.1 — Frozen prompt fixtures exported from the real sim.**
  **[DECIDED: frozen export, as specced.]** A `hearthbench export`
  command reads recorder archives + prompt builders and writes a
  versioned fixture pack (`fixtures/v1.4.1/*.json`) containing real
  `layer1_structured_input` + rendered prompts across every job type —
  frozen, checked-in, hash-identified.
- [ ] **A3.2 — Test definition schema (declarative, data not code):**
  ```
  TestCase: id, category, fixture_ref, system_prompt, schema_ref,
            scorers[], weight, tags[], turns[] (multi-turn),
            expected_invariants[] (grounding facts that must hold),
            seed
  ```
  Adding a benchmark category = adding data + a scorer, never touching
  the runner.
- [ ] **A3.3 — Multi-turn & stateful cases.** Personality-stability and
  memory tests need conversation *sequences* with injected state between
  turns (turn 1 establishes a fact; turn 7 tests recall; turn 12 offers
  a contradiction).
- [ ] **A3.4 — Synthetic perturbation.** Reuse `prompt_synthesis.py` to
  generate fixture variants so a model can't be tuned to the exact
  fixture set, and rare job types get enough cases for a stable score.

## A4 — Scoring & the judge problem [MISSING] — *the central design decision*

**[DECIDED: build both paths.]** Deterministic-only scoring is a
first-class run mode (`--no-judge`), used by CI (A13) and quick
screening; the judge tier is an additive layer for subjective
categories. Both produce a valid, clearly-labelled report:
`Score: 78.1 (deterministic-only; Dialogue/Personality unscored)` is
legitimate, never broken.

- [ ] **A4.1 — Tier 1: deterministic scorers (always on, free).**
  Schema validity, parse/retry/fallback rate, latency/throughput,
  grounding-violation detection, contradiction detection, repetition/
  self-similarity, lexical diversity, context-reflection rate, leak
  patterns, length compliance. Lift from `quality_labels.py`. Covers
  Grounding, Structured Outputs, Reliability, Performance, and much of
  Memory alone.
- [ ] **A4.2 — Tier 2: judge-model scorers (optional, subjective
  categories).** A configurable, separate judge adapter scoring
  naturalness/personality/emotional-realism on a fixed rubric with
  few-shot anchors; judge model + prompt version recorded per run;
  self-consistency measured by re-scoring a sample.
- [ ] **A4.3 — Tier 3: human rating UI (calibration ground truth).** A
  blind-pairwise page over stored outputs; reports judge↔human
  agreement.
- [ ] **A4.4 — Scorers are pure, versioned, registered.**
  `Scorer(id, version, fn(case, result, context) -> ScoreDetail)` —
  scorer version is part of a run's identity.

## A5 — Benchmark categories [MISSING] — every one from the brief

Each becomes a category module with concrete cases and scorers.

- [ ] **A5.1 — Dialogue.** Naturalness, coherence, personality
  expression, emotional realism, incl. an "ambient filler" penalty for
  aphorism ping-pong/mutual-agreement patterns.
- [ ] **A5.2 — Personality.** Stability across many conversations,
  long-term consistency, individual-voice distinguishability.
- [ ] **A5.3 — Memory.** Recall, appropriate forgetting, contradiction
  resistance, long-term integration.
- [ ] **A5.4 — Beliefs.** Formation from evidence, revision when
  evidence flips, theory quality, confidence calibration.
- [ ] **A5.5 — Planning.** Goal formation, multi-step coherence,
  horizon realism, adaptation when blocked.
- [ ] **A5.6 — Village cognition.** Cultural belief formation,
  institution reasoning, tradition crystallization, social reasoning.
- [ ] **A5.7 — Grounding.** Never invents objective facts — adversarial
  bait cases, reward explicit uncertainty, heavily penalize confident
  fabrication. Weighted highest (A10).
- [ ] **A5.8 — Structured outputs.** JSON validity, schema compliance,
  retry/parse-failure/fallback rate, with and without grammar
  constraints.
- [ ] **A5.9 — Performance.** Latency (p50/p95/max), TTFT, tok/s,
  RAM/swap/CPU%, sampled continuously, attributed per case.
- [ ] **A5.10 — Category extension guide.** A short doc + template.
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

## A7 — Metrics Collector [MISSING]

- [ ] **A7.1** — Per-case/per-category/per-run metric records, all raw
  values retained (A8) so aggregates can be recomputed without
  re-running.
- [ ] **A7.2** — System sampling thread (RSS, swap, CPU%, llama-server
  `/metrics`), aligned to case boundaries.
- [ ] **A7.3** — N, mean, median, p95, stdev, and a confidence interval
  per category — feeds A10/A11's score-confidence requirement.

## A8 — Diagnostics: lose nothing [MISSING]

- [ ] **A8.1 — Run record** (one directory per run): every raw prompt/
  completion/parsed JSON/validation error/retry/fallback reason/timing/
  token count/per-case score with scorer version.
- [ ] **A8.2 — Environment capture:** backend+version, model file+hash+
  quantization, context/sampler/server flags, adapter/fixture-pack/
  scorer/benchmark version, seed, host summary.
- [ ] **A8.3 — Content-addressed storage** for prompts/completions.
- [ ] **A8.4 — Retention policy.** Permanent by default; explicit
  `--prune` only, never auto-delete.

## A9 — Reports [MISSING]

- [ ] **A9.1 — HTML report** (self-contained): recommendation in plain
  language, per-category scores with confidence, failure examples with
  the actual prompt/output, latency/memory graphs.
- [ ] **A9.2 — JSON + CSV exports.**
- [ ] **A9.3 — Comparison report:** N runs side by side, per-category
  deltas, a significance flag when CIs overlap, "what changed."
- [ ] **A9.4 — The recommendation must be honest.** Low confidence
  stated prominently; a category-disqualifying weakness overrides an
  otherwise-good average.

## A10 — The HearthBench Score [MISSING]

- [ ] **A10.1 — Weighted composite, explained.** Default weights (all
  overridable, printed in the report): Grounding 20, Dialogue 15,
  Beliefs 12, Memory 12, Village cognition 10, Personality 10,
  Planning 8, Reliability/structured-output 8, Performance 5.
- [ ] **A10.2 — Disqualifying floors, not just weights** (e.g.
  grounding < 50 caps the total at 60), stated with its reason.
- [ ] **A10.3 — Normalization discipline.** Each category maps to
  0-100 via an explicit, versioned rubric, never a curve against other
  models.
- [ ] **A10.4 — Confidence.** `Score: 82.4 ± 3.1 (Full run, N=420
  cases, judge=<model>)`.

## A11 — Run modes [MISSING]

- [ ] **A11.1 — Quick** (minutes): stratified subsample, deterministic
  scorers only, no judge — "is this model worth a full run?"
- [ ] **A11.2 — Full** (long): complete fixture set, multi-turn cases,
  judge scoring, repeated sampling for variance.
- [ ] **A11.3 — Custom:** category subset / single category.
- [ ] **A11.4 — Resume.** Every completed case commits immediately;
  resume = skip completed IDs. Non-negotiable at these latencies.
- [ ] **A11.5 — Reproducibility.** Fixed seeds, recorded sampler
  settings, a `--strict-repro` mode that fails the run if the adapter
  reports non-deterministic capability.

## A12 — Web UI [MISSING]

- [ ] **A12.1** — New page in the existing UI, served by the bench
  daemon (A1.3), clearly marked as not part of the sim.
- [ ] **A12.2** — Select model/backend, configure run, start.
- [ ] **A12.3** — Live progress (case i/N, ETA), live log stream,
  running per-category scores.
- [ ] **A12.4** — Cancel + resume controls.
- [ ] **A12.5** — Browse previous runs (sortable table).
- [ ] **A12.6** — Compare runs (→ A9.3).
- [ ] **A12.7** — Drill into any case: prompt/completion/parsed output/
  scores with justifications/timing.
- [ ] **A12.8** — Download HTML/JSON/CSV.
- [ ] **A12.9** — The human-rating page (A4.3).

## A13 — Prompt-regression guard in CI [APPROVED]

Catches a prompt edit that silently degrades quality, discovered only
weeks later in a review pack.

- [ ] **A13.1 — Trigger:** any change under the prompt builders,
  `json_schemas.py`, or the shared cognition contract runs a Quick
  benchmark against a pinned model+quantization+fixture pack,
  deterministic scorers only (`--no-judge`, so CI needs no judge infra).
- [ ] **A13.2 — Gate on the objective categories only** (grounding,
  structured-output validity, leak patterns, context-reflection, length
  compliance) — never on subjective scores, too noisy for CI.
- [ ] **A13.3 — Thresholds relative to a stored baseline**, not
  absolute — reuse `eval_harness`'s regression-threshold checker (A0.2).
- [ ] **A13.4 — Baseline refresh is an explicit, reviewed commit.**
- [ ] **A13.5 — Nightly deeper run** on main (larger sample, optional
  judge) posting a trend line, so slow drift is visible even when every
  individual PR passes.

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

- [ ] **C5 — The model passport [APPROVED].** HearthBench emits a
  small, portable `passport.json` per benchmarked model that the
  **runtime reads at startup** to configure itself — closing the C2
  loop automatically instead of by hand.
  - **Contents:** model id + quantization + file hash; HearthBench and
    World scores with confidence; per-category strengths/weaknesses;
    measured throughput (prompt tok/s, completion tok/s, TTFT, latency
    p50/p95) and peak RSS at each concurrency level tested;
    recommended settings (concurrency, context size, batch, whether it
    needs grammar constraints to be reliable); and hard warnings (e.g.
    "fails grounding — not recommended").
  - **Runtime consumption:** on startup the runtime matches the
    configured model to a passport and seeds its machine profile
    (B7.2) with those priors instead of learning throughput from
    scratch over the first hour. Passport values are *priors*, not
    overrides — B6's controllers still adapt from live measurement.
  - **Safety interlock:** a passport hard warning is surfaced in the
    UI at startup rather than silently running a model known to
    hallucinate facts.
  - **Provenance:** passports record which host produced them; a
    passport from a very different machine contributes throughput
    priors with lower weight.

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
7. A4.2 judge + remaining subjective categories; A4.3 human calibration.
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
