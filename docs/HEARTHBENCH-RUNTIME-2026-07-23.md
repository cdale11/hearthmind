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

## A0 — Foundations to reuse, not rebuild [PARTIAL]

- [ ] **A0.1** — `llm/client.py` already has `OllamaClient` and
  `LlamaCppClient` behind a `build_llm_client(config)` factory. That is
  a de-facto adapter layer; formalize it (A2) rather than writing a new
  one.
- [ ] **A0.2** — `eval_harness.py` (hash-based held-out split,
  stratified golden-prompt sampler, regression thresholds) already
  solves *fine-tune regression*. HearthBench is the **model-selection**
  sibling. Share the split/sampler code; do not duplicate it.
- [ ] **A0.3** — `recorder.py`'s four-layer schema (structured input →
  prompt → raw completion → parsed output, with hashes and versions) is
  exactly HearthBench's diagnostics record. Reuse the schema so
  benchmark records and live-sim records are mutually analyzable.
- [ ] **A0.4** — `quality_labels.py` already computes per-example
  labels (schema-valid, context-reflection, leak flags, novelty). These
  are HearthBench scorers. Lift them into the shared scoring library
  (A4) and let both call it.
- [ ] **Rule:** HearthBench imports *from* a small shared
  `hearthmind.cognition_contract` package (schemas, prompt fixtures,
  scorers). It never imports the simulation engine, and the simulation
  never imports HearthBench. That satisfies the brief's isolation
  requirement while preventing prompt drift.

## A1 — Module layout & isolation [MISSING]

- [ ] **A1.1 — Package skeleton.** `hearthbench/` as a sibling of
  `hearthmind/` in the same repo, with the brief's modules as
  submodules: `runner/`, `adapters/`, `prompts/`, `tests/`,
  `validation/`, `metrics/`, `diagnostics/`, `reporting/`, `ui/`.
  Separate `pyproject` extra (`pip install -e .[bench]`) so a bench
  dependency can never enter the sim's runtime path.
- [ ] **A1.2 — Import firewall test.** A CI test asserting
  `hearthbench` imports nothing from `hearthmind.simulation`,
  `hearthmind.agents`, `hearthmind.world`, and that `hearthmind`
  imports nothing from `hearthbench`. Enforce the brief's "the
  simulation should never know anything about HearthBench" mechanically,
  not by convention.
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

## B0 — The prime invariant [MISSING] — *build this first*

> **Gameplay systems declare *what* work exists. The runtime decides
> *when*, *where*, and *how* it executes. Gameplay never makes
> scheduling, threading, batching, or hardware decisions.**

- [ ] **B0.1 — Adopt it as a written architectural law** in `CLAUDE.md`
  alongside the existing Body/Mind law, with the same enforcement
  culture.
- [ ] **B0.2 — Enforce it mechanically:** a lint/CI rule banning
  `threading`, `time.sleep`, executor creation, and scheduling
  arithmetic inside `world/`, `agents/`, `settlement/`, `economy/`.
  Those may only *declare* tasks.
- [ ] **B0.3 — Migration reality.** Today ~200 schedule points live
  inside `engine.py` and subsystems. Migrating them is the bulk of Part
  B and must be incremental (B1.4).

## B1 — Task declaration & the work graph [MISSING]

- [ ] **B1.1 — `Task` descriptor** — what a subsystem declares instead
  of calling itself:
  ```
  Task(id, subsystem, fn, timescale, priority_class,
       reads[], writes[],            # for dependency + parallelism
       trigger: Periodic|OnEvent|OnDirty|Predicted,
       cost_hint, locality: region|global|entity,
       determinism: strict|reorderable)
  ```
  `reads`/`writes` are what let the runtime reorder and parallelize
  *safely* — two tasks with disjoint write-sets may run concurrently;
  overlapping ones may not.
- [ ] **B1.2 — Registry + dependency graph.** Built at startup from
  declarations; cycles rejected at boot. The graph is the scheduler's
  input and the profiler's key space.
- [ ] **B1.3 — Deterministic ordering rule.** Within a tick, tasks are
  ordered by a stable topological sort with a deterministic tiebreak
  (task id), *independent of wall-clock and thread completion order*.
  This is what makes reordering safe.
- [ ] **B1.4 — Incremental adoption.** A shim lets un-migrated code keep
  running exactly as today while migrated subsystems move under the
  scheduler, one at a time, each verified by the replay-hash test
  (B17.1). Never big-bang.

## B2 — Budgets & scheduling [Hard Rules 2, 9] [MISSING]

- [ ] **B2.1 — Explicit per-subsystem execution budgets** (ecology,
  humans, culture, innovation, recorder, LLM, pathfinding, persistence,
  UI): a time slice per tick/frame, adaptive (B6).
- [ ] **B2.2 — Priority classes:** `critical` (must run this tick),
  `standard`, `deferrable`, `background`, `idle-only`. Deferral is
  bounded — a deferrable task carries a deadline after which it is
  promoted, so nothing starves (starvation would silently change
  outcomes and violate Hard Rule 1).
- [ ] **B2.3 — Overrun policy.** When a subsystem exceeds its budget,
  the runtime may *defer remaining work to the next tick* but never
  skip it. Track debt per subsystem; surface it (B15).
- [ ] **B2.4 — Attention-follows-change [Rule 9].** A per-region
  activity score (derived from event rate / field deltas / agent
  presence) scales the compute allocated to region-local tasks. Quiet
  regions get coarse, infrequent updates; busy regions get fine ones —
  *without* changing the rules applied, only the allocation of effort.
  Requires B10's timescales and B11's locality to be honest.
- [ ] **B2.5 — Work-conserving.** Spare capacity flows to the next
  eligible task rather than idling; leftover time runs background/idle
  work (persistence, compression, maintenance).

## B3 — Event-driven execution [Hard Rule 3] [MISSING]

- [ ] **B3.1 — Dirty tracking.** Every declared `writes[]` marks its
  targets dirty; tasks whose `reads[]` are clean and whose trigger is
  `OnDirty` simply don't run. This is the single biggest CPU win
  available and the rule the current code most violates.
- [ ] **B3.2 — Event bus.** Subsystems emit typed events; tasks
  subscribe. Replaces "check every tick whether something happened."
- [ ] **B3.3 — Audit polling.** Enumerate current per-tick work; for
  each, classify as genuinely-continuous (fields, weather) vs.
  polling-in-disguise (most checks). Convert the latter. Publish a
  "polling remaining" count as a tracked metric so it trends to zero.

## B4 — Dormancy [Hard Rule 4] [MISSING]

- [ ] **B4.1 — `Dormant` lifecycle** for entities/subsystems:
  `active → drowsy → dormant → archived`, with explicit wake triggers
  (event on a subscribed channel, player attention, scheduled review).
  Dormant = zero scheduled work, state compressed (B12).
- [ ] **B4.2 — Candidates named in the brief:** forgotten traditions,
  inactive settlements, distant wildlife, unused ideas, idle
  institutions. Each needs a *sleep criterion* and a *wake criterion*,
  declared next to the system.
- [ ] **B4.3 — Semantic safety.** Dormancy must be *lossless*: on wake,
  the entity computes catch-up deterministically (elapsed-time
  integration) rather than pretending nothing happened, or it must be
  provably inert while dormant. This is the subtlest correctness risk in
  the whole runtime — every dormancy rule needs a replay test.

- [ ] **B4.4 — Chaos testing for dormancy [APPROVED 2026-07-23].** A
  test mode that randomly force-sleeps and force-wakes subsystems and
  entities at arbitrary moments, then asserts the LLM-off replay hash
  is unchanged versus a no-dormancy run. Because dormancy bugs are
  *silent* (a sleeping institution that quietly stops accruing state
  looks like normal behavior, not a crash), this is the only practical
  way to trust B4 — review cannot catch a missing catch-up integration.
  Run it in the nightly soak with a fresh chaos seed each night, and
  keep the failing seed on any breakage for direct reproduction.

## B5 — Continuous profiling [Hard Rules 5, 15] [PARTIAL]

- [ ] **B5.1 — Per-task instrumentation, always on:** CPU time, wall
  time, call count, wake frequency, idle ratio, queue depth, cache
  hit rate, memory delta, budget utilization, deferral debt. Ring-buffer
  aggregates, not raw logs. No "profiling mode" — profiling *is* the
  runtime.
- [ ] **B5.2 — Low-overhead design.** Sampling + counters, with the
  profiler's own overhead measured and reported (a profiler that costs
  5% must say so).
- [ ] **B5.3 — Expose everything** at `/diagnostics/runtime` and in the
  dev console: per-subsystem tables, flame-ish breakdown by task,
  adaptation history. **No subsystem may be a black box** — make it a
  review rule that a new task declaring no metrics fails CI.

- [ ] **B5.4 — "Explain this tick" [APPROVED 2026-07-23].** For any
  chosen tick, a full execution trace: every task that ran, **why** it
  ran (which trigger fired — periodic, event, dirty-flag, prediction),
  what it cost, what it read and wrote, what was deferred and to when,
  what was skipped because a dependency was clean, and what slept.
  - **Build it with B1, not after.** The moment work moves from
    "everything runs every tick" to conditional scheduling, the question
    "why didn't X run?" becomes constant — and unanswerable without
    this. It is the debugging tool that makes the whole runtime
    tractable to reason about.
  - **Implementation:** a ring buffer of the last N tick-traces (cheap,
    bounded) plus an on-demand "trace next tick in full detail" toggle
    for expensive capture.
  - **Also the emergence lens:** paired with the causal-chain metric,
    this answers "what actually happened in the world this tick, and in
    what order" — useful far beyond performance work.

## B6 — Adaptive tuning [Hard Rule 6] [PARTIAL for LLM only]

- [ ] **B6.1 — Tunables registry:** update intervals, batch sizes,
  worker counts, queue priorities/lengths, cache sizes, memory limits,
  persistence frequency, LLM concurrency. Each with a legal range, a
  step size, and a semantic-safety class (`safe` = cannot change
  outcomes; `sensitive` = requires replay verification).
- [ ] **B6.2 — Controllers.** Simple feedback control (PID-ish or
  bang-bang with hysteresis) driving each tunable toward a target
  (e.g. tick-time budget, memory headroom). Deterministic, no LLM —
  per the doc's closing note (evolutionary algorithms, statistics,
  optimization, feedback control).
- [ ] **B6.3 — Existing LLM pacing folds in here.** `llm_pressure_*`
  (slowdown band, pause, backpressure) is the one adaptive controller
  that exists — re-express it as a registered tunable set under the
  general framework rather than a special case.

## B7 — Hardware model [Hard Rule 7] [MISSING]

- [ ] **B7.1 — Host probe at startup + periodically:** CPU topology
  (physical/logical cores), cache sizes, RAM capacity + availability,
  memory pressure, swap, NUMA nodes, storage latency/throughput
  (micro-benchmark), GPU presence/utilization, thermal + power state,
  current system load.
- [ ] **B7.2 — Persistent machine profile** keyed by a host fingerprint,
  stored across runs, refined each session: measured LLM throughput,
  optimal worker count, optimal batch size, storage characteristics.
  The doc's "gradually evolves into the most efficient strategy for
  *this* machine" needs persistence to be true.
- [ ] **B7.3 — Strategy selection from the profile,** not from
  hardware-specific code paths in gameplay: many-core → more
  parallelism; low-RAM → smaller caches, earlier compression;
  battery/thermal-throttled → aggressive dormancy, lower LLM
  concurrency; fast GPU → higher concurrency.
- [ ] **B7.4 — Host-OS citizenship [Runtime Philosophy]:** respect
  system memory pressure (back off before the OS swaps), yield under
  external CPU load, lower priority for background work, respond to
  thermal throttling, coexist cleanly. Explicit "good citizen" policy
  with configurable aggressiveness (a dedicated box may want more).

## B8 — Predictive scheduling [Hard Rule 8] [MISSING]

- [ ] **B8.1 — Workload forecaster:** short-horizon predictions from
  simulation state and history — storm approaching → dialogue/cognition
  spike → pre-reserve LLM capacity; harvest season → economy update
  surge → preallocate workers; a festival scheduled → event burst.
- [ ] **B8.2 — Reservation mechanism:** the scheduler can hold capacity
  for a predicted need without idling (fill with background work that is
  cheap to preempt).
- [ ] **B8.3 — Forecast accuracy is measured** and feeds back; a
  consistently wrong predictor is down-weighted automatically. Prediction
  that is never scored becomes superstition.
- [ ] **B8.4 — Idle-window scheduling:** expensive maintenance
  (compression, persistence, archive migration, index rebuilds) is
  deliberately scheduled into predicted-quiet periods.

## B9 — Hierarchical timescales [Hard Rule 10] [MISSING]

- [ ] **B9.1 — Declared timescale per task** (the doc's ladder):
  physics ~ms, humans ~minutes, culture ~days, institutions ~months,
  civilizations ~years. The scheduler *enforces* that a slow system
  cannot be scheduled at a fast frequency.
- [ ] **B9.2 — Elapsed-time integration** for slow systems: they compute
  from `Δt` since last run, so running them less often is
  mathematically equivalent, not an approximation. Required for B4
  dormancy and B2.4 attention scaling to be semantically safe.
- [ ] **B9.3 — Audit every current subsystem** for timescale mismatch
  (things running per-tick that need only run per-day). Expect large,
  immediate CPU wins here.

## B10 — Locality [Hard Rule 11] [MISSING]

- [ ] **B10.1 — Spatial index / region partition** (grid or quadtree)
  with per-region task queues; tasks declare `locality`.
- [ ] **B10.2 — Ban global scans in hot paths.** Audit and convert
  full-population/full-map iterations to local propagation or indexed
  queries; add a CI check flagging new global scans in per-tick code.
- [ ] **B10.3 — Region-parallel execution** where write-sets are
  disjoint by region — the main safe parallelism source, and the natural
  partner to B2.4's attention allocation.

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
