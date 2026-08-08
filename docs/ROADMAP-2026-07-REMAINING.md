# Hearthmind — Final Roadmap

Consolidated and restructured per explicit user instruction: "consolidate
the roadmap and summarize everything at the bottom... make a new phase-
based roadmap at the top... this final roadmap should be a final pass and
after completing that should ship the game I always have wanted."

Everything genuinely open across the whole project — Part A (deterministic
Body), Part B (cognitive Mind), Part C (Body↔Mind seam), Tier 5
(HearthBench + the Adaptive Runtime), Tier 6 (learned models), Tier 7
(HCA), and the C++ native-porting backlog — is captured below in
dependency order. Nothing shipped is repeated here; **all shipped history
now lives in `CHANGELOG.md` and `CLAUDE.md`'s "Current state" log**, which
this doc no longer duplicates (see "Shipped so far," bottom). Standing
convention unchanged: this is a reference, not a queue — work starts only
on an explicit "next step"/item-naming instruction, never auto-chained.

---

## Phase 1 — Semantic substrate + the goal-policy flagship

The two Tier 6 items everything else in this roadmap either builds on or
gates behind.

- **L1.1 — Semantic embedding** of the sim's own vocabulary — **SHIPPED
  and WIRED into production (v1.34.259).** `hearthmind/ml/embedding.py`:
  a pure-Python skip-gram-with-negative-sampling word embedding, trained
  on a caller-supplied text corpus (corpus-agnostic by design, same
  "decouple from World internals" discipline `cross_run.py` already
  established). `SkipGramEmbedding.text_similarity(a, b)` is the real
  "do these two pieces of text mean the same thing" function —
  verified against the architecture doc's own worked example ("the
  wolves took Bram" scores measurably closer to "a predator killed my
  brother" than to an unrelated harvest sentence, `scripts/verify_ml_
  l1_embedding.py`, 19 checks).

  **The corpus-building pass, closed.** New `hearthmind/ml/corpus.py`'s
  `collect_world_corpus(world)` extracts every real sentence-shaped
  string already living in a `World`'s own persisted state —
  `emergence_log` summaries, every agent's `memories`/`semantic_
  memories`, every settlement's `beliefs`/`folklore`/`legends`/
  `records`, and all five cognitive pillars' `world_model` belief
  text — deduplicated, no new tracked field, no LLM call of its own.
  The load-bearing finding this pass corrects: unlike L2.2 (which
  genuinely needed a live-LLM recorder archive), L1.1 needed no
  external archive at all — this codebase's deterministic-fallback
  path already writes plenty of real sentences (event/chronicle
  templates), so a corpus can be built from ANY world, including one
  freshly created and ticked right here with the LLM disabled;
  verified directly against exactly such a fixture.

  **Real wiring.** Same file-next-to-`db_path`/never-auto-created
  pattern as `GOAL_POLICY_FILENAME` — new `EMBEDDING_FILENAME`/
  `_embedding_path_for`/`_load_embedding` in `simulation/engine.py`;
  a random-init untrained embedding would score WORSE than the bag-
  of-words relevance it replaces (no real semantic structure), so
  absence means the exact prior behavior, not a degraded one.
  `SimulationEngine.__init__` loads it once (`self._embedding`);
  `_run_personal_belief` (the one real engine-side `retrieve_
  relevant_memories` call site) now passes `embedding=self._embedding`
  — `full_diagnostics()['embedding']` surfaces `{loaded, path,
  vocab_size}`. `cognition.py`/`letters.py`'s own `retrieve_relevant_
  memories` calls are pure `build_prompt` functions with no engine
  access by design and stay at the default, same as before.

  New `scripts/train_embedding_from_world.py`: loads a real, already-
  persisted `World` from any operator's own `db_path` (the same load
  path `server.py` itself uses), builds its corpus via `collect_
  world_corpus`, trains, and saves to the exact path `Simulation
  Engine` auto-loads — **needs no live-LLM training-recorder archive,
  unlike `train_goal_policy_from_archive.py`.** Real waiting consumers
  named in earlier filings (four text-dedup sites, `Pillar.word_
  overlap`, topic-novelty checks, L2.3's retrieval scorer, HCA `F1`'s
  end-to-end concept-vector pull) are NOT migrated onto this embedding
  yet — each needs its own real wiring pass, same discipline as every
  other L-layer piece; this pass closes the corpus-building gap every
  one of them was actually blocked on.
  Unblocks L2.3/HCA `F1` at the substrate level; both still need their
  own real wiring pass.
- **L2.2 — Goal policy** (the flagship, the largest single remaining Tier
  6 item) — **SHIPPED and WIRED into production (v1.34.258)**, once a
  real user-uploaded `review_pack.json` export (420 real, non-fallback
  `cognition`-task examples) gave this the live archive every prior
  filing had flagged as the one missing prerequisite. `hearthmind/ml/
  goal_policy.py`: a closed-7-class softmax `AgentGoal` classifier
  replacing `llm/cognition.py`'s `fallback_goal` if-ladder's one
  genuinely-arbitrary branch (the `agent_id % 3` content-agent split;
  every forced branch — critical hunger/energy, fear, grief, materials-
  critical — stays exactly as deterministic as before, `goal_policy`
  never touches them). Real two-phase curriculum —
  `build_distillation_examples` (phase 1, teacher→student) and
  `reweight_by_outcome` (phase 2, deterministic oversampling by a
  real externally-measured outcome weight — never the policy's own
  output fed back in) — verified end to end (`scripts/verify_ml_l2_2_
  goal_policy.py`, 20 checks) including the doc's own literal headline
  claim: a student trained on a genuinely noisy/sometimes-wrong
  teacher label, then outcome-reweighted, measurably shifts toward the
  answer that actually worked, away from blind imitation. Personality-
  conditioning and the entropy floor (`_apply_entropy_floor`, an exact
  per-class minimum, not an approximation) are both real and tested;
  survival overrides are explicitly out of scope, left untouched in
  `fallback_goal`. Needed and got a real fix to shared L0 substrate:
  `hearthmind/ml/training.py` previously supported a `"softmax"`
  output head at INFERENCE time only (`_sgd_step`'s backward pass
  never special-cased it) — added real, verified `loss="cross_entropy"`
  backprop (`train_mlp_sgd`/`continual_train_mlp`/`LearningSpecialist.
  learn`, all backward-compatible, default stays `"mse"`).

  **Real wiring (v1.34.258).** `GoalPolicy.predict`/`sample_goal`
  gained an `allowed_goals` mask — restricts the softmax to a caller-
  chosen subset before the entropy floor, renormalized over just that
  subset — so the trained policy is structurally incapable of
  introducing a goal the branch it replaces never produced (`explore`
  in particular stays reserved for the surveyor role, forced
  separately elsewhere; only `socialize`/`gather`/`wander` are ever
  masked in). New `GoalPolicy.to_dict`/`from_dict`/`save`/`load`
  (schema-versioned, same discipline as every other persisted weight
  blob). `fallback_goal(..., goal_policy=None, rng=None)` — `None`
  (still every call site's default until a real weights file exists)
  reproduces the exact prior `agent_id % 3` output byte-for-byte,
  verified directly. `simulation/engine.py` gained `_goal_policy_path_
  for`/`_load_goal_policy` (same file-next-to-`db_path`, never-auto-
  created pattern B7.2's `MachineProfile` established — a fresh host
  gets no default weights, since "weights are per-world/per-deployment
  state" is a real architectural guardrail, not a convenience);
  `SimulationEngine.__init__` loads it once, threaded into both real
  `fallback_goal(...)` call sites; `full_diagnostics()['goal_policy']`
  surfaces `{loaded, path}`.

  New `scripts/train_goal_policy_from_archive.py` — the real offline
  trainer: consumes either a `review_pack.json` export or a raw
  recorder archive directory, extracts only `fallback_used=False`
  `cognition` pairs (the standing anti-self-reinforcement guard),
  trains via a real held-out shadow-gate split, and saves weights to
  the exact path `SimulationEngine` auto-loads. Run against the user's
  own 420-example archive: shadow gate ACCEPTED, holdout accuracy
  28.6% (vs. an ~16.7% uniform floor across the 6 goals actually
  present in that archive) — a genuine, if modest, real above-baseline
  fit, not a synthetic proof. `lr=0.003`/`epochs=200` were the values
  a real sweep against this archive settled on — the same plain-SGD
  divergence class already fixed once for the workload forecaster
  (v1.34.257) reproduced here at the module's bare defaults
  (`lr=0.03`-`0.05` reliably diverged the candidate past the shadow
  gate on this real data); documented at the call site, re-tune from a
  live holdout-accuracy reading if a future archive's feature
  distribution proves different.

  `Agent.plan` absorption (a real L1.1 `text_vector` concatenated into
  the feature schema) remains deliberately NOT done — `FeatureSchema`
  only encodes flat numeric/categorical slots today; a small schema
  extension is needed first, flagged as real follow-up. L2.1's own
  still-open outcome-influence labeling job remains the real blocker
  for a future Phase 2 (outcome-reweighted) retrain — this pass only
  ran Phase 1 distillation, honestly, since no real outcome label
  exists in the archive yet.
- **L2.3 — Semantic retrieval scorer** — **SHIPPED (substrate), partly
  wired.** Two real pieces. (1) A genuine, live L1.1 consumer:
  `agents/agent.py`'s `retrieve_relevant_memories` gained an optional
  `embedding` param (duck-typed, `agents/` still never imports
  `hearthmind.ml/`) — when a real trained `SkipGramEmbedding` is
  supplied, relevance is real semantic similarity instead of bag-of-
  words; `None` (every real call site today) reproduces the exact
  prior behavior byte-for-byte. Verified through the real production
  call path: a memory sharing ZERO tokens with the query context is
  still surfaced when a real embedding is attached (`scripts/verify_
  ml_l2_3_retrieval_scorer.py`, 14 checks). No world attaches a
  trained embedding yet — needs L1.1's own still-open corpus-building
  pass. (2) `hearthmind/ml/retrieval_scorer.py`: a learned sigmoid
  scorer over the SAME four real inputs `cognition/activation.py`
  already combines (base-level activation, salience, relevance,
  causal-tag presence) — merges the audit's M3-consumer + M4 into one
  model, replacing `activation.py`'s hand-tuned `ACTIVATION_SALIENCE_
  GAIN`/`ACTIVATION_RELEVANCE_GAIN`/`ACTIVATION_CAUSAL_GAIN` gains.
  NOT wired into `retrieve_relevant_memories`'s own sort — needs a
  real "did this memory demonstrably influence the output" label from
  a live recorder archive, same discipline as L2.2. **Correction
  (found while building L2.2):** both this item's own text and
  ML-AUDIT's §3a cite `agents/agent.py:472-474`'s old hand-set linear
  weights as the thing to replace — that formula no longer exists
  there, superseded by Tier 7 HCA's D1 before this Tier 6 item was
  ever scoped; the real current target was and is `cognition/
  activation.py`, confirmed and acted on this pass.
- **HCA `F1` — Semantic pointers** (gated on L1.1) — **SHIPPED
  (substrate), partly wired.** New `hearthmind/cognition/semantic_
  pointers.py`: real VSA primitives over L1.1's trained embeddings —
  `bundle` (elementwise-mean superposition, the SET operation, lossy)
  and `bind` (circular convolution, the real Holographic Reduced
  Representation binding operation, Plate 1995 — reversible via
  `unbind`/circular correlation, a structured "A combined-with-B"
  relation). `generate_candidates(vec_a, vec_b, embedding=None)`
  produces exactly these two algebraic candidates with a real
  coherence score (mean cosine similarity to both parents) and,
  given a trained embedding, a real nearest-vocabulary gist
  (`nearest_vocab`); `select_best_candidate` picks deterministically
  by coherence, zero LLM calls anywhere in generation or selection.
  Real wiring: `llm/ontology.py`'s `build_merge_prompt` gained an
  optional `candidate_hint` param (`format_candidate_hint` is the
  intended caller) that grounds the LLM's synthesis prompt in the
  winning candidate's own real semantic neighborhood; empty string
  (every real call site today — `simulation/engine.py`'s merge job
  still calls positionally) reproduces the prior prompt text byte-
  for-byte. Not yet wired end-to-end into a real `simulation/
  engine.py` call site (no world has a trained embedding attached to
  pull real concept vectors from yet — same L1.1 corpus-building gap
  L2.3 is also blocked on). Falsifiable test satisfied by construction,
  not measurement: today's real merge pipeline already makes exactly
  one LLM call per combination (no naive multi-candidate pipeline
  exists in production to beat directly) — the real comparison is
  against a hypothetical K-candidate generate-then-judge pipeline
  (`K+1` LLM calls), which this module's algebraic generation +
  deterministic selection beats with exactly 1 call regardless of K;
  proven directly in `scripts/verify_hca_f1_semantic_pointers.py`'s
  own headline check (21 checks total, incl. a real HRR bind/unbind
  round-trip proof and an end-to-end real-embedding-to-hinted-prompt
  test).
- **Four of the five `fallback_goal`-shaped LLM/deterministic sites
  found by the background audit above — SHIPPED and WIRED (v1.34.260).**
  New `hearthmind/ml/decision_policy.py`'s `DecisionPolicy(classes,
  schema)` generalizes `GoalPolicy` once (identical softmax-MLP/
  entropy-floor/`allowed_classes`-masking/shadow-gated-continual-
  learning machinery, parameterized instead of hard-coded to
  `AgentGoal`) rather than four near-duplicate copies; `goal_policy.py`
  itself is untouched. Four real site configs (`DISPUTE_POLICY_
  CONFIG`/`FISSION_POLICY_CONFIG`/`MIGRATION_POLICY_CONFIG`/
  `FOUNDING_POLICY_CONFIG`), each mirroring exactly what that site's
  own real `fallback_*` function already reads. `llm/dispute.py`'s
  `fallback_dispute`, `llm/fission.py`/`llm/migration.py`'s `fallback_
  decision`, and `llm/founding.py`'s `fallback_founding` all gained an
  optional `policy`/`rng` param pair — `policy=None` (every call
  site's default until real weights exist) reproduces each function's
  exact original if-ladder output byte-for-byte. Dispute's `allowed_
  classes` masking is load-bearing, not cosmetic: `council_ruling`/
  `ostracism` are structurally excluded whenever `has_council` is
  `False`, the same "real constraint enforced by masking" discipline
  `GoalPolicy`'s own `explore` exclusion established. `simulation/
  engine.py` gained `DECISION_POLICY_FILENAMES`/`_decision_policy_
  path_for`/`_load_decision_policy` (one file per site, file-next-to-
  `db_path`, never-auto-created, same pattern as `GOAL_POLICY_
  FILENAME`) — `DecisionPolicy.from_dict`'s own `kind`/`classes`/
  schema cross-check rejects a file trained for the wrong site, not
  just a version mismatch. All four real `_schedule_llm_job` call
  sites also gained a `structured_input` dict (previously none of the
  four ever recorded one) matching each site's own real fallback
  inputs exactly — the prerequisite a live archive needs to actually
  train these four, closed in the same pass rather than left as a
  silent gap the trainer would hit later. New `scripts/train_decision_
  policies_from_archive.py` trains whichever of the four sites has
  enough real recorded examples in a given archive, skipping the rest
  honestly. Verified: `scripts/verify_decision_policies_wiring.py` (18
  checks) — round-trip/mismatched-config rejection, masking/
  renormalization, `policy=None` byte-for-byte parity for all four
  `fallback_*` functions, the engine's per-site loading (no-file/
  corrupted-file/real-file/wrong-site-file), and a full subprocess
  end-to-end training-script run. A live smoke test confirmed all four
  policies load and a real `SimulationEngine` runs 50 real ticks with
  every site wired, zero crash. `scripts/verify_replay_hash.py`/
  `verify_native_soak.py` — both MATCH, confirming the default
  (all four `None`) path is completely unaffected.
- **`llm/laws.py`'s "which hardship becomes a law"** — **SHIPPED and
  WIRED (v1.34.261)**, the fifth and last flagged Phase-1 site, via a
  genuinely different mechanism than the four above. New `hearthmind/
  ml/law_scorer.py`'s `LawCandidateScorer`: the same L2.3 `Retrieval
  Scorer` pattern (one scalar sigmoid score, never a softmax over
  named classes) over a deliberately generic schema (occurrence
  count, `village_pillar` confidence, conviction-initiated flag — no
  candidate NAME anywhere) — the same trained scorer applies to any
  of the 14 named `pattern_key`s today and any future one Tier 0 adds,
  with no schema change. Never touches `forms`/`kind`/text — `laws.
  fallback_laws()` stays the same honest "not yet" no-op; the scorer
  is only ever a real third-level tiebreak in `_maybe_schedule_laws`'s
  candidate pick, after the real occurrence count (dominant) and
  `village_pillar.subject_confidence` (secondary) — a constant `0.0`
  with no scorer loaded reproduces the exact prior tiebreak byte-for-
  byte. `_maybe_schedule_laws`'s `_schedule_llm_job` call gained
  `structured_input` too, the missing prerequisite a future archive
  needs to train it. New `scripts/train_law_scorer_from_archive.py` +
  `scripts/verify_law_scorer_wiring.py` (19 checks — round-trip,
  occurrence-count capping, both the no-op AND the live-tiebreak-flip
  proof, the three real engine loading cases, a full subprocess
  training run). `scripts/verify_replay_hash.py`/`verify_native_
  soak.py` — both MATCH. **This closes all five of Phase 1's flagged
  `fallback_goal`-shaped sites.**

## Phase 2 — Wire the already-built ML substrate to real consumers — CLOSED IN FULL, v1.34.266

Every one of these shipped as a real, tested, standalone module with no
live production call site — the recurring gap across Tier 6. All six
named items (L2.1, L3.1, L3.2, L4.1, L5, L6) are now wired, verified,
and locally trainable — see README's "Local ML training" section and
`scripts/train_all.py` for how to actually train and use them. B13.5
(a related, Tier 5 Adaptive Runtime item flagged in this same section
since it shared the identical "built and verified in isolation only"
gap) closed the same way in v1.34.266 — zero open items remain here.

- **L2.1 SHIPPED, v1.34.265.** `hearthmind/ml/value_model.py` gained
  real persistence and a real call site: `SimulationEngine._voice_
  narrative_extra_scores` (the weekly voice-pair "who's the
  protagonist" score) folds in a loaded model's predicted consequence
  as a bounded additive bonus alongside the existing hand-set
  inventor/council/Humans-pillar bonuses — `None` reproduces the exact
  prior behavior byte-for-byte. New `scripts/train_value_model_from_
  archive.py`: trains directly from a live world's own db (no recorder
  archive needed) — one example per living core-cast agent, features =
  current state, label derived from that agent's own already-tracked
  `extreme_event_count`/`core_memories` (honestly one snapshot-in-time
  per agent, since `Observation` carries no `agent_id` to reconstruct a
  true per-observation historical pair from). `scripts/verify_l2_1_l4_
  1_wiring.py` (23 checks, shared with L4.1 below).
- **L3.1 SHIPPED, v1.34.262.** `LLMCostRegressor` gained real
  persistence (schema-versioned/kind-tagged, same file-next-to-
  `db_path`/never-auto-created discipline as every prior Tier 6 model)
  and a real call site: `SimulationEngine._schedule_llm_job` consults
  a loaded regressor right after the daily-budget check — a call
  predicted unusually slow under an already-elevated queue resolves
  synchronously to the deterministic fallback instead of ever being
  dispatched, attacking `calls_dropped_backpressure` at its root. A
  real numerical-stability bug (`LATENCY_SCALE_MS` too small for this
  project's own documented deep_reasoning-outlier latency range,
  reliably diverging training to NaN/inf) was found and fixed in the
  same pass, via a direct sweep against realistic data. New `scripts/
  train_llm_cost_regressor_from_archive.py` (honest gap: no per-
  example backlog/concurrency reading exists in the recorder archive
  today, both default to 0.0 for training). `scripts/verify_llm_cost_
  regressor_wiring.py` (19 checks). **L3.2 was already shipped**
  (`WorkloadForecaster`, wired under HCA's own G2, v1.34.217) — this
  bullet's prior grouping was stale, corrected here. L3.2's own "true
  autoregression over the `metrics` table" stays a further, distinct
  open piece, unrelated to L3.1's own closure.
- **L4.1 SHIPPED, v1.34.265.** `hearthmind/ml/belief_calibration.py`
  gained real persistence and a real call site via a new shared
  `SimulationEngine._calibrated_confidence` helper, wired at `_maybe_
  schedule_self_tuning`'s C2 conviction gate (whether a still-`"open"`
  hypothesis's raw stated confidence is trustworthy enough to initiate
  a real sandboxed self-tuning experiment). New `scripts/train_belief_
  calibrator_from_archive.py`: trains directly from `World.reflection_
  notebook`'s own real settled outcomes — no recorder archive needed,
  though real settled hypotheses accumulate slowly (Reflection's own
  multi-cycle evidence loop). Also new `scripts/train_all.py`, a
  one-command wrapper running every local trainer this project ships
  against one world, and a substantially extended README "Local ML
  training" section (a new "how long to wait, do I need to stop the
  world" subsection, per direct user question — training is read-only/
  offline and safe against a live world).
- **L5 SHIPPED, v1.34.263.** The goal policy's own real per-model
  retrain cadence — the flagship's long-flagged gap: `GoalPolicy` was
  already built on G1's `LearningSpecialist` internally, but nothing
  fed it a real live cadence the way G2 built for `WorkloadForecaster`.
  `SimulationEngine._run_cognition` now captures a real `(agent_state,
  goal)` pair from every genuine (non-fallback) LLM cognition answer,
  encoded identically to `fallback_goal`'s own consumption and the
  offline trainer's own extraction — the concrete answer to "what
  counts as new examples." New `_maybe_tick_goal_policy` (monthly)
  retrains once enough real examples bank, reusing `scripts/train_
  goal_policy_from_archive.py`'s own settled `lr`/`epochs`. Weights
  deliberately stay in-memory only (not written back to disk), same
  choice G2 made for `WorkloadForecaster`. `scripts/verify_l5_goal_
  policy_retrain.py` (15 checks). L6/B13.5 remain their own,
  structurally different open items — L5's own lifelong-learning
  substrate (`hearthmind/ml/lifelong.py`) is otherwise already fully
  real and consumed (`LearningSpecialist`, wired for both `Workload
  Forecaster` and now `GoalPolicy`).
- **L6 SHIPPED, v1.34.264.** The workload forecaster's own real
  evolutionary cadence — `hearthmind/ml/evolution.py`'s `GenomePopulation`/
  G4's `train_and_score_genome_via_specialist` (proven since v1.34.176)
  finally has a real live consumer. New `SimulationEngine._maybe_
  evolve_workload_genomes` (yearly, placed before `_maybe_tick_workload_
  forecaster` in `_TICK_JOBS`) evolves a real small population (6, mu=3)
  against the same accumulated examples the monthly retrain already
  uses; a genuinely fitter best genome, compared against a throwaway
  "live" stand-in never appended to the population, updates the
  monthly retrain's own `learning_rate`/`epochs` overrides — L6's
  phylogeny (population variation/selection over hyperparameter
  configs) made real and distinct from L5's already-wired ontogeny
  (one lineage's continual retrain). `scripts/verify_l6_workload_
  genome_evolution.py` (14 checks), including a real end-to-end
  multi-year soak via a deliberately coarser `sim_minutes_per_tick=120`
  test config (harmless — the check's claim depends only on elapsed
  calendar units, not tick-to-simulated-time fidelity; measured 8x
  fewer real ticks needed for the same 370 simulated days).
- **B13.5 SHIPPED, v1.34.266** (explicit user instruction: "phase 2
  b13.5"). `hearthmind/ml`-sibling `tunable_evolution.py`'s
  `TunableGenomePopulation`/`evaluate_tunable_genome_fitness` (built
  and verified in isolation only) now has a real yearly cadence:
  `SimulationEngine._maybe_evolve_pacing_genomes` evolves the three
  `llm_pressure_*` pacing-ratio tunables (never `llm_max_concurrent`,
  which stays B13.1's own single-tunable `HypothesisLoop` territory) —
  a real, deterministic fitness function (`pacing_interval_multiplier`,
  extracted pure from `_llm_pressure_interval_multiplier`) scored
  against three fixed pressure-ratio samples, and a real generalized
  async equivalence-check gate mirroring B13.2's own. Spawned as a
  fire-and-forget background task (gated on `self._cognition_runner.
  enabled`, so it structurally can never fire on an LLM-disabled
  world) after a real pre-existing async-task-creation crash was found
  and fixed mid-implementation. `scripts/verify_b13_5_pacing_genome_
  evolution.py` (22 checks). **This closes Phase 2 down to zero open
  items.**

## Phase 3 — Close the last Tier 7 (HCA) gaps

- **E3, competing-goals half — SHIPPED, v1.34.269** (explicit user
  instruction "start e3"). New `hearthmind/cognition/goal_arbitration.py`:
  a genuinely NEW per-agent `GlobalWorkspace` arbitrating SOCIALIZE/
  GATHER/WANDER — the same three "content" goals `hearthmind.ml.
  goal_policy.GoalPolicy` (L2.2) already scopes itself to, resolved
  once every forced branch above them (survival/fear-grief/materials-
  critical/plan-intent) has already ruled itself out; those forced
  branches stay real, untouched overrides, never part of the
  competition. `compute_content_goal_bids` scores each goal from the
  same trait/emotion signals `fallback_goal`'s old flat `agent_id % 3`
  split ignored (`TRAIT_SOCIABILITY`/`TRAIT_AMBITION`/`TRAIT_OPENNESS`,
  `EMOTION_JOY`/`EMOTION_ANGER`); B2's staleness gain (keyed on the
  goal name itself) is the real headline mechanism — a genuinely
  tied/neutral agent's goal choice ROTATES over many cycles instead of
  settling on one fixed branch forever, real per-agent variety instead
  of a population-blind caste. `llm/cognition.py`'s `fallback_goal`
  gained an optional `goal_workspace` param, checked only when `goal_
  policy is None` — a real trained `GoalPolicy` keeps its existing
  priority unchanged, no regression for a deployment already
  benefiting from it. `SimulationEngine._goal_workspace_for` bounds
  this to the CORE CAST only (mirroring every other richer per-agent
  mechanism's own gating precedent), pruned every tick against the
  live cast so `self._goal_workspaces` can never outgrow it. Needed NO
  new "describe" function for the Observatory: `cognition.observatory.
  workspace_snapshot` already renders any real `GlobalWorkspace`
  generically, reused directly by the new `_goal_competition_snapshot`
  and surfaced via `full_diagnostics()['goal_competition_snapshot']` +
  a new dev-console "HCA E3: competing goals" panel. New `scripts/
  verify_e3_competing_goals.py` (41 checks, all pass first run — incl.
  a `goal_workspace=None` byte-for-byte parity proof across 9 agent
  ids, every forced-branch-still-overrides-with-a-workspace-present
  case, the real `goal_policy`-keeps-priority precedence proof, and the
  headline staleness-rotation test over 12 real cycles). **This closes
  roadmap Phase 3 in full** (E3/H1 both shipped; "confirm B1's headline
  test live" stays explicitly deferred — impossible in this offline
  environment, no real production deployment to measure against).
- **H1, per-domain budgets — SHIPPED, v1.34.268.** Write-scope
  enforcement (WORLD/MACHINE/OBSERVER) was already real; this ships the
  real second MACHINE-domain bidder the item itself named as missing.
  `propose_machine_profile_refresh_bid` gives B7.2's monthly `Machine
  Profile` disk refresh a real `Bid`, submitted to the SAME `_machine_
  workspace` `propose_escalation_bid` already uses, on a different
  subject (`escalation_ladder` vs. `machine_profile_refresh`) —
  `arbitrate()` still resolves ONE winner per cycle across all pending
  bids regardless of subject, so this is genuine domain-level
  contention. Both submitters (`_maybe_advance_escalation_ladder`/
  `_maybe_refresh_machine_profile`) now only SUBMIT; a new shared
  `_maybe_resolve_machine_domain` runs the real `arbitrate()` call once
  per day_end, after both have had a chance to bid. The escalation
  bid's own score now depends on `pressured` (1.0 pressured, 0.3 calm)
  against the profile refresh's flat 0.5 — a pressured cycle always
  wins for the ladder (never starved of its safety-relevant response),
  a calm cycle lets real periodic maintenance spend the domain's one
  action instead.
- **A real chunk-expiry mechanism for C2's `ChunkStore` — SHIPPED,
  v1.34.267.** `ChunkStore.compile()` gained an optional `ttl_ticks`
  (`None` = never expires, byte-for-byte the original behavior);
  `lookup()` gained an optional `tick` — a chunk found past its own
  `expires_at_tick` is treated as a genuine miss and deleted outright.
  `dispatch_impasse` threads both straight through. Real second
  production consumer: `_maybe_schedule_rule_proposal` now sweeps its
  own already-computed `stuck_institution` tiebreak into the dispatch
  ladder — a real per-institution streak across consecutive seasonal
  firings is the C1 `no_change` signal, and `RULE_PROPOSAL_CHUNK_TTL_
  YEARS` (a real per-world tick count, derived from the live calendar
  config) is what stops a cached "no rule yet" outcome from suppressing
  a genuinely-overdue law forever — the exact limitation the musing
  pilot's own docstring flagged as accepted-not-engineered-around.
- **Confirm B1's own headline test** ("pillar-level call share rises from
  1.4% to >15%") against a real live production run — the wiring (W1-W4)
  shipped but the number itself was never re-measured live.

## Phase 4 — The two ~200-site live-judgment audits

Both explicitly need individual per-site judgment plus live replay-hash
verification, not a mechanism — real, slow, careful work, never rushed
through in one pass per this project's own "never big-bang" discipline.

- **B3.3** — convert the remaining `ON_DIRTY`/`ON_EVENT` reactivity sites.
  **Partially shipped, v1.34.270.** Investigated every `_TICK_JOBS` entry
  gated behind `_monthly_gate`/`_season_year_gate` (both start with
  `if "day_end" not in events: return False`, a coarse per-tick guard
  the scheduler itself never got to see) plus a handful of jobs with a
  simpler direct `"month_end" in events`/`"day_end" in events` check —
  42 real, uniform, safely-batch-convertible sites found and converted
  in one pass, per this project's own "never one at a time" discipline
  (institution_dormancy stays the one prior conversion; 4 more
  dormancy-adjacent + narrative-cadence jobs move to `event_types=
  {"month_end"}`, 38 more — chronicle, town_brain, beliefs, dream,
  invention, ontology_proposal/evolution, laws, dispute-adjacent
  narrative jobs, culture/religion/faction/guild/institution jobs,
  reflection/self_tuning, letters, fission, musing, and more — move to
  `event_types={"day_end"}`). Behavior-preserving by construction:
  `Scheduler._due_and_reason`'s `ON_EVENT` check is based solely on
  `EventBus.pending()`, entirely independent of the positional
  `events`/`previous_season` args still forwarded unchanged to
  `task.fn(*args)` once the task IS due — each job's own fine-grained
  internal gate (staggered day-of-month, retry windows) is completely
  untouched; only the scheduler's own coarse due-check moves from
  "call the function every tick, it immediately returns" to "never
  call the function at all on a non-matching tick" (a genuine
  `skipped_clean`, never touching budget/deferral machinery — the
  real CPU win B3.1 was built for). New `_MONTH_END_GATED_JOBS`/
  `_DAY_END_GATED_JOBS` frozenset constants (`simulation/engine.py`)
  drive `_tick_once`'s publish loop. `scripts/verify_b0_runtime_
  migrations.py`'s `EVENT_DRIVEN_TASK_IDS` set (previously just
  `{"institution_dormancy"}`) extended to all 42 newly-converted
  task ids — same special-casing shape that script already used for
  the one prior ON_EVENT job, all 176 checks re-pass. Verified via a
  direct 3000-tick production-path run (`full_diagnostics()
  ['runtime_diagnostics']` confirms correct call-vs-skipped-clean
  counts, e.g. a daily job firing ~once/day with the rest genuinely
  skipped-clean); `scripts/verify_replay_hash.py` (800 ticks, seed
  777, `--in-process`) — MATCH, byte-identical; `scripts/verify_
  native_soak.py` (seeds 1/55, 800 ticks) — MATCH; `scripts/verify_
  b3_dirty_events.py`/`verify_runtime_diagnostics.py`/`verify_
  runtime_invariant.py`/`verify_scheduler.py`/`verify_task_graph.py`/
  `verify_dormancy.py` all re-run clean; `pyflakes` clean (only the
  six known pre-existing forward-ref findings in `engine.py`). What's
  left: `sim_summary`/`chronicler`/`pillar_chat_*`/`away_digest`
  (real user-triggered on-demand jobs — never periodic, structurally
  can't gate on a calendar event) and the three per-agent/per-pair
  sites (`rumor_interpret`/`personal_belief`/`mind`) stay un-migrated
  by design, same exclusion list W2 already established for a
  different reason (settlement-scoped `GlobalWorkspace` granularity,
  not B3.3's own territory) — genuinely nothing further to convert in
  that direction. Resume only on a fresh site actually found, or on
  future explicit direction.
- **B9.3** — audit ~200 per-tick call sites for timescale mismatch
  against the real `TimescaleLadder`. **Investigated in full, v1.34.271
  — genuinely closed, not just deferred.** After B3.3's 42-site batch
  above, exactly 14 `_TICK_JOBS` entries remain `TriggerKind.PERIODIC`
  (`naming`, `retry_mind_authoring`, `trigger_state_edges`, `spread_
  concepts`, `spread_tradition_keeping`, `trigger_rules_life_events`,
  `composite_reactions`, `record`, `dispute`, `migration_decision`,
  `due_cognition`, `due_dialogue`, `voice_dialogue`, `broadcast`) — read
  each one directly rather than trusting the ~200 estimate. All 14 fall
  into one of three classes, none of which is a real timescale
  mismatch: (1) genuine per-tick stochastic processes that need a fresh
  roll every real tick to mean what their own tuned constant says
  (`spread_concepts`'s `CONCEPT_SPREAD_CHANCE_PER_TICK`, `dispute`/
  `record`/`migration_decision`'s per-candidate cooldown rolls); (2)
  genuine edge-detection over a continuously-varying Body signal that
  would silently miss the exact crossing tick if checked any less
  often (`trigger_state_edges`'s drought/surplus low->high detection,
  explicit in its own docstring: "a naive 'check every tick' would fire
  every tick the state stays above threshold" — the FIX for that is
  the tick-scale check itself, not a coarser cadence); (3) already-cheap
  O(1) early-exits on a small transient collection that changes
  unpredictably tick-to-tick, not on a calendar boundary (`naming`'s
  `newly_named_settlement_ids`, `retry_mind_authoring`'s pending-agent
  deque, `trigger_rules_life_events`'s `last_life_events` categories) —
  technically convertible to `ON_DIRTY`, but the real CPU cost of the
  current check is already ~0 (an empty-collection truthiness test),
  so converting would buy real correctness RISK (a missed `DirtyTracker.
  mark_dirty` call at one of several mutation sites silently starves
  the job forever) for no measurable win, the opposite trade B3.3's own
  42 conversions made. `due_cognition`/`due_dialogue`/`voice_dialogue`
  are inherently per-agent-due-timer scans (agents become individually
  eligible on their own staggered schedule, not a shared calendar
  event) and `broadcast` is real-time UI infrastructure — both
  genuinely tick-scale by design. Nothing here needs `TimescaleLadder`/
  `ElapsedTimeTracker` wiring; the module stays real, verified,
  standalone infrastructure for a future consumer that DOES have a
  genuine mismatch (none exists in the live tree today). This closes
  B9.3 — resume only if a future new job introduces a real mismatch.
- **B4.2, the last dormancy candidate** — **"inactive settlements" was
  already shipped (v1.34.210, `_update_settlement_dormancy`) — this
  roadmap entry's own "the last two" framing was stale, corrected
  v1.34.271.** Only **"distant wildlife"** remains open, of five
  originally named (idle institutions/unused ideas/forgotten
  traditions/inactive settlements all shipped as Mind-layer-attention-
  only dormancy — see each one's own `_update_*_dormancy` docstring).
  Re-investigated directly this pass (`world/wildlife.py`'s
  `WildlifeGrid.tick`), not just re-flagged: unlike its four siblings,
  there is no Mind-layer-only reframe available — wildlife carries no
  institutional/narrative memory of its own for a "which herd gets this
  month's attention" rotation to gate. `WildlifeGrid.tick()` is real
  Body-deterministic per-tick simulation with a single shared RNG
  stream consumed in `self.herds.values()` iteration order across
  movement, reproduction, hunting, and migration rolls — critically,
  predator-grazer collision (`prey = next(...) if h.x == herd.x and
  h.y == herd.y...`) is a real same-tile check inside this SAME loop,
  so a "distant" predator herd silently frozen while a "distant" grazer
  herd nearby keeps ticking (or vice versa) would change which animals
  live or die based purely on an arbitrary runtime scheduling decision
  — exactly what `docs/CONSTITUTION.md`'s B15 `TWO_PART_GUARANTEE`
  ("the deterministic Body is replay-identical regardless of any
  runtime decision") exists to forbid. Freezing BOTH species together
  by shared distance-to-nearest-settlement would avoid that specific
  hazard but still needs a real product decision on what a woken herd's
  population should read after N frozen ticks (freeze it exactly as it
  was, or a closed-form "coarse ecology" catch-up formula) — a design
  question, not an implementation gap. Confirmed, not merely repeated:
  this is the fourth session to independently reach the same
  conclusion (v1.34.183, v1.34.190, v1.34.192, v1.34.208/.210, now
  this one) — stop re-investigating it without a real product decision
  naming which tradeoff to take.

## Phase 5 — Finish wiring the Adaptive Runtime's remaining pieces

- **B11 — SHIPPED (first slice), v1.34.273.** B11.1-B11.3's `Memory
  TierManager`/`TransparentHandle` primitives get a real first
  consumer: `GET /agents/{id}/memory_log` (`interface/app.py`)
  previously ran a fresh `recent_agent_memory_log` SQL query against
  the durable `agent_memory_log` table on EVERY request — no caching
  at all. New `SimulationEngine._agent_memory_log_tiers`/`_agent_
  memory_log_cache` (runtime-only, never persisted): `cached_agent_
  memory_log(agent_id, limit)` — the real provider wired to `World
  Broadcaster.set_agent_memory_log_provider` — only engages the cache
  for the ONE real request shape any caller actually makes (`limit ==
  AGENT_MEMORY_LOG_CACHE_LIMIT`, the NPC inspector's own default); a
  different `limit` bypasses the cache and queries directly, avoiding
  a second cache dimension for a request shape nothing makes today.
  New `_maybe_demote_agent_memory_log_cache` (monthly, ON_EVENT/
  month_end, same B0.3-migrated-scheduler shape as every dormancy
  job): demotes an idle agent's tier via `MemoryTierManager.demote_
  stale` against `AGENT_MEMORY_LOG_TIER_THRESHOLDS` (real elapsed-
  SIMULATED-tick windows, HOT 20k/WARM 60k/COLD 200k) and, past HOT,
  actually POPS the cached rows out of the dict — the real point of
  tiering (reclaiming RAM for an agent nobody's inspected in a long
  while), not just relabeling. A re-fetch at any tier re-queries,
  re-caches, and promotes straight back to HOT via `Transparent
  Handle.get`'s own `touch()`. `full_diagnostics()['agent_memory_log_
  cache']` surfaces live tier counts + cached-agent count. New
  `scripts/verify_b11_agent_memory_log_cache.py` (24 checks, all pass
  first run — cache hit/miss, non-default-limit bypass, empty-result
  caching, tier promotion on access, real demotion freeing RAM, the
  real registered job's own end-to-end behavior, a never-requested
  agent as a safe no-op, `_TICK_JOBS`/month_end-gating registration,
  diagnostics surfacing, a real `WorldBroadcaster`-provider end-to-end
  proof incl. the no-provider-registered `None` fallback `interface/
  app.py`'s route itself relies on, byte-identical parity against the
  direct uncached query, and a real 400-tick production soak).
  **B11.4 (host-pressure-driven demotion, `pressure_response`)
  deliberately NOT wired this pass** — this first slice stays scoped
  to elapsed-tick demotion alone, same "ship the interface, wire the
  first real consumer" pattern every prior Tier 5/6/7 item here uses;
  real, distinct future work if a second real large-persisted-state
  consumer ever wants the pressure-aware variant.
- **B12 — cascade completion SHIPPED, v1.34.274; a real LLM-authored
  producer chain per stage stays open.** Investigating "wire the
  remaining cascade" found a genuine bug first, not just a gap:
  `_emergence_compression.entries[EPISODE]` (and every stage above it)
  had NOTHING ever calling `maybe_compress` on them — a real unbounded
  runtime-only growth (one entry added per RAW compression, forever),
  the exact "memory-leak pattern to audit first" shape this file's own
  standing lesson names, just slow enough to be invisible in an
  ordinary few-thousand-tick soak. Fixed by wiring EPISODE/SUMMARY/
  HISTORY compression too — new `EMERGENCE_COMPRESSION_EPISODE_/
  SUMMARY_/HISTORY_THRESHOLD` (each groups 5 of the stage below it,
  `max_count=5`) and a shared `_merge_emergence_digests` `condense_fn`
  that recursively merges the existing digest shape (`tick_start`/
  `tick_end`/`count`/`kind_counts`/`notable_summary`) at every
  promotion, so CULTURAL_MEMORY's own archived entries eventually
  represent ~12,500 raw observations each, still bounded overall by
  `EMERGENCE_COMPRESSION_ARCHIVE_MAX`. `full_diagnostics()
  ['emergence_compression']['stage_pending']` surfaces a live per-
  stage census — the real, cheap proof no stage's bucket grows past
  its threshold. **Deliberately still NOT what "a real chronicle/
  documentary/culture-digest producer chain per stage" originally
  asked for** — that would need those independently-scheduled LLM jobs
  redesigned to also fire on a compression event, a materially larger
  change; every stage here condenses deterministically instead, real,
  distinct future work if the richer narrative version is wanted.
  New `scripts/verify_b12_cascade_completion.py` (21 checks, all
  pass — one real bug caught before shipping, `_merge_emergence_
  digests([])` crashed on `max()` of an empty sequence; `maybe_
  compress` never actually calls it that way in production, but fixed
  to degrade safely regardless of that invariant holding forever).
- **B14.3 — SHIPPED, v1.34.275.** `batch_size_for_storage` had no real
  batched-write mechanism to size for -- the `snapshots` table stays
  one `INSERT` per row (correctly; each snapshot is legitimately one
  row/one JSON blob, not a batching opportunity), but the `events`
  table's writer was ALSO still one `execute()` per row, a genuine
  per-tick hot path (the calendar-events loop plus `last_life_events`
  inside `_tick_once`, plus every `_log(...)` call from dialogue/
  rumor/chronicle/tradition/invention/festival/intervention/town-brain
  async apply() closures). New `SimulationEngine._event_write_buffer`
  (a plain list, runtime-only) + `_buffer_event`/`_event_batch_byte_
  budget`/`_flush_event_write_buffer`, backed by a new `persistence.
  snapshot.log_events_batch` (one real `conn.executemany()` call
  instead of N `execute()` calls). `_log` and both of `_tick_once`'s
  direct event-logging loops now buffer instead of writing immediately;
  the buffer flushes automatically once it crosses `_event_batch_byte_
  budget()` (real `batch_size_for_storage` output, driven by B7.2's
  measured `MachineProfile.storage_write_mb_s` -- an unmeasured host
  falls back to `EVENT_BATCH_MIN_BYTES`) and is force-flushed at
  exactly the two real `conn.commit()` call sites in the whole engine
  (`_tick_once`'s own end-of-tick commit; `run_forever`'s shutdown
  `finally:` block, which bypasses `_tick_once` entirely and needed
  its own explicit flush). Traced every commit site and every `_log`
  call path first to confirm this introduces zero NEW data-loss risk
  beyond what `_log`'s own docstring already documented (an async
  apply() closure's event can already land "at most one tick" late,
  since it's scheduled via `asyncio.create_task` outside `_tick_once`'s
  synchronous sequence) -- buffering the `execute()` itself, not just
  deferring the commit, stays inside that same existing window.
  `full_diagnostics()['event_write_batching']` surfaces `buffered_
  pending`/`byte_budget`/`flush_count`. New `scripts/verify_b14_3_
  event_batching.py` (22 checks, all pass -- `log_events_batch`'s real
  `executemany` write incl. an empty-list no-op; buffering genuinely
  deferring the DB write until flush; the byte-budget formula against
  real `storage_write_mb_s` readings incl. the unmeasured-floor and
  ceiling-clamp cases; a small forced budget genuinely auto-flushing
  mid-tick, not just once per tick; both loops inside `_tick_once`
  routing through the buffer; the flush-before-commit guarantee at
  both real commit sites, the shutdown one driven the same way `run_
  forever`'s own finally-block does it; diagnostics surfacing; a real
  400-tick production soak confirming events -- including real
  `day_end` calendar rows -- land correctly through the batched path).
  One real test-fixture bug caught and fixed before shipping (not a
  bug in the module under test): a "buffered row not yet visible"
  check assumed zero pre-existing events, but world creation itself
  already logs one real synchronous genesis event outside this buffer
  -- fixed to filter by the test's own specific category instead of
  an absolute count. **This closes Phase 5 in full** -- B11
  (v1.34.273), B12 (v1.34.274), B14.3 (this pass) join B15.6-B15.8
  (v1.34.272), leaving no open item in Phase 5.
- **B15.6/B15.7/B15.8 — SHIPPED, v1.34.272.** New `World.machine_
  profile_history` (bounded, `MACHINE_PROFILE_HISTORY_MAX=100`,
  persisted through `to_dict`/`from_dict`, legacy-backfilled): a real
  `session_started` entry per `SimulationEngine` construction (real
  host fingerprint) plus `rung5_entered`/`rung5_exited` entries on a
  genuine `Rung.REDUCE_COGNITION_BREADTH` transition (`_maybe_advance_
  escalation_ladder`'s own resolver, the only writer) — B15.2's own
  "save files must record the profile" text, finally real; distinct
  from `full_diagnostics()['escalation_ladder']['history_recent']`
  (runtime-only, every rung, wiped on restart) — this is the smaller
  persisted cross-session subset, surfaced as a sibling `machine_
  profile_history_recent` diagnostics key. New `scripts/verify_b15_7_
  scheduler_fuzz.py`: `verify_replay_hash.py`'s own two-independent-
  runs technique looped over K randomized runtime configs (`llm_max_
  concurrent`/`snapshot_every_ticks`/forced `dormancy_aggressiveness`)
  — the correct reading of B15.2's guarantee worked out carefully in
  the script's own docstring: NOT that different configs must produce
  the same world state (Mind-layer content legitimately varies by
  hardware, per B15.2's own "adaptive" half), but that a GIVEN
  randomized config must still reproduce byte-identically across two
  independent runs of itself — a genuine fuzz that can catch a hidden
  nondeterminism the one fixed default config might not exercise.
  `TunableRegistry.register()` gained two real registration-time
  checks: an out-of-range starting value is rejected, and a
  `SafetyClass.SENSITIVE` tunable with no `description` is rejected —
  the same "constants need a one-line docstring explaining why" this
  codebase already holds everywhere else, made structural for exactly
  the tunables risky enough to need B13.2's equivalence gate. New
  `scripts/verify_b15_6_and_b15_8.py` (20 checks). This closes B15 in
  full — B15.1-B15.8 all real.

## Phase 6 — HearthBench (build the benchmark itself)

`A0` (confirmed reusable pieces), `A1.1`/`A1.2`/`A1.3` (package
skeleton, import-isolation firewall, process isolation), `A2` (model
adapter layer), `A3` (prompt library/test definitions), `A4` in full —
including `A4.3`'s own real rating page — (scoring, "the judge
problem," the doc's own central design fork), `A5` in full — the three
OBJECTIVE categories (`A5.7`/`A5.8`/`A5.9`, needing no judge model,
plus `A5.10`'s guide) AND all six SUBJECTIVE categories (`A5.1`-`A5.6`,
real judge rubrics + real hand-authored cases each) — `A13`'s CI
regression guard (`A13.1`-`A13.4`), `A7.1`/`A8` (the real run record +
recomputable metrics)/`A11.4` (resume), `A9`/`A10` (reports + the real
weighted composite Score), **C5** (the model passport, both halves —
real emission on the `hearthbench` side, real runtime consumption on
the `hearthmind` side), and `A12` in full — `A12.1`-`A12.5` (start/
poll/cancel/browse), `A12.6`-`A12.8` (compare/drill-in/download), and
`A12.9` (the real human-rating page) — and **A6** (structured output
validator: `A6.1` schema-constrained decoding wired from a case's own
`schema_ref`, `A6.2` the real repair-ladder classifier, `A6.3` real
per-case dual-mode scoring) — are all shipped. **This closes step 6,
step 7, AND every flagged gap within them (A4.3/A12.9, A6) in full.**
Remaining in the checklist's own real order:

`A5.11` the world-level emergence run, gated on **B15.5**'s `reference_
mode` (built, still unused — now genuinely closer, since A11.4/A8/A9/
A10/A1.3/C5/A12.1-A12.9/A4.3/A5.1-A5.6/A6 all exist; step 8, explicitly
last, the checklist's own final item — this is now the only real
SEQUENCED item left in Phase 6). `A7.2` (a system-sampling thread —
needed for C5's own
`peak_rss_mb_by_concurrency` field, honestly shipped empty until it
exists), `A11.1`-`A11.3`/`A11.5` (the fuller quick/full/custom/
strict-repro run-mode abstraction), and A9.1's latency/memory GRAPHS
(no charting
dependency exists in this repo) stay real, distinct, unstarted future
work within their own already-partial items.

- **A6 (structured output validator, all three sub-items) — SHIPPED,
  v1.34.289.** Un-sequenced per the checklist's own SEQUENCE, but
  closes real, previously-flagged gaps rather than being decorative.

  `A6.1`: new `hearthbench/validation/schema_resolver.py`'s `resolve_
  schema(schema_ref)` reuses `hearthmind.llm.json_schemas.schema_for_
  task` DIRECTLY — legal under A1.2 (only `hearthmind.simulation`/
  `.agents`/`.world` are banned, `hearthmind.llm` isn't), real reuse
  ahead of A0's still-unbuilt shared `cognition_contract` package.
  Closed a real, previously-unexercised gap: `TestCase.schema_ref`
  (A3.2's own field) had never been consumed by the runner —
  `hearthbench/runner/run.py`'s `_execute_case` hardcoded `schema=
  None` on every call regardless of what a case named. Now wired;
  `schema_ref=None` (every case shipped before this pass) reproduces
  the exact prior unconstrained request byte-for-byte.

  `A6.2`: new `hearthbench/validation/repair_ladder.py`'s `classify_
  repair(text, parsed, error)` — a real, uniform "raw"/"repaired"/
  "failed" classifier over any A2.2 adapter's own `AdapterResult`, no
  per-adapter instrumentation needed. Wired into `hearthbench.scoring.
  types.CaseResult.from_adapter_result`, replacing a `parse_repaired=
  False` stub that had NEVER been computed since A4.4 first shipped —
  a real pre-existing gap, not new scope. New `CaseResult`/`CaseRecord`
  `repair_rung`/`repair_reason` fields (additive, backward-compatible),
  surfaced through the daemon's case-detail route and `page.py`.

  `A6.3`: new `hearthbench/validation/dual_mode.py`'s `run_case_dual_
  mode` — the SAME case run through the adapter twice (constrained/
  unconstrained), real per-scorer delta, deliberately opt-in (two real
  calls, not folded into the fast single-call default every ordinary
  run keeps using). `constrained_supported=False` (never a fabricated
  delta) when no `schema_ref` or the adapter can't do constrained
  decoding — confirmed a real skip case makes only ONE HTTP request,
  never a wasted second call. Distinct from A5.8's own pre-existing
  category-level `score_structured_output_delta` (that one operates on
  `CategoryScoreSummary.pass_rate` across a whole pre-built case pair;
  A6.3 operates per-case, per-scorer) — the two compose, neither
  duplicates the other.

  New `scripts/verify_a6_structured_output_validator.py` (32 checks,
  3 consecutive clean runs, real local HTTP server through the real
  `OpenAICompatAdapter`, never mocked): `resolve_schema`'s exact match
  against the real production schema; `classify_repair`'s four real
  cases; `CaseResult`/`CaseRecord` wiring incl. backward-compatible
  degradation on a pre-A6.2 record; a real outgoing HTTP request proof
  that `schema_ref` genuinely requests `json_schema` decoding on a
  capable adapter, degrades to `json_object` on an incapable one
  (A2.1's own documented fallback), and sends no `response_format` at
  all when no `schema_ref` is named; three real end-to-end runs
  through `run_cases_with_resume` proving a clean/prose-wrapped/
  unrecoverable completion commits the correct real rung to a
  `CaseRecord` read back purely off disk; `run_case_dual_mode`'s real
  2-request/1-request/0-request proofs across all five real scenarios.

  Verified: the new script; `scripts/verify_hearthbench_isolation.py`/
  `verify_hearthbench_adapter_isolation.py`/`verify_a1_3_process_
  isolation.py`/`verify_a2_model_adapters.py`/`verify_a3_prompt_
  library.py`/`verify_a4_scoring.py`/`verify_a5_categories.py`/
  `verify_a5_1_6_subjective_categories.py`/`verify_a7_a8_run_
  diagnostics.py`/`verify_a9_a10_score_report.py`/`verify_a13_ci_
  guard.py`/`verify_c5_model_passport.py`/`verify_a12_bench_daemon.py`
  all re-run clean — the `CaseResult`/`CaseRecord` field additions and
  `_execute_case`'s new `schema` argument disturbed nothing already
  shipped. `pyflakes` clean on all touched/new files. No `simulation/
  engine.py` code path or native module touched — pure `hearthbench/`
  work, no replay-hash/native-soak re-run needed.

- **A12.9 (the human-rating page, closes A4.3) — SHIPPED, v1.34.287.**
  Built entirely on A4.3's own already-real `HumanRatingTask`/`Human
  Rating`/`judge_human_agreement` (`hearthbench/scoring/human.py`,
  untouched) — the data model was real, only the page consuming it was
  missing. `GET /api/rating/tasks?run_a=X&run_b=Y` builds a real
  blind-pairwise queue straight from two real run directories (A8): a
  task's own `task_id` is a stable hash of `(run_a, run_b, case_id)`,
  so the task itself needs no separate persistence — it's always
  re-derivable from what A8 already keeps on disk — and which run's
  text lands in slot "a" vs. "b" is derived from that same hash, not a
  fixed order. The wire response never includes `candidate_a_source`/
  `candidate_b_source`/either judge score — A4.3's own "must not be
  surfaced to the rater" holds at the HTTP boundary, not only in
  `page.py`'s rendering. `POST /api/rating/submit` appends a real
  `HumanRating` via A4.3's own `append_rating` to one JSONL file under
  `<runs_root>/_ratings/`. `GET /api/rating/agreement?run_a=X&run_b=Y`
  is real reuse of `judge_human_agreement`, scoped to the pair's own
  task ids. `page.py` gained a real "Human rating" panel per the
  standing UI-surfacing rule: two run selects (auto-populated from
  `/api/runs`), a rater-id field, "Load tasks"/"Show agreement report"
  buttons, a one-task-at-a-time prompt/candidate-A/candidate-B display
  with A/Tie/B buttons, and a note field.

  `scripts/verify_a12_bench_daemon.py` extended (52 -> 63 checks): a
  real 4-task queue built from the two runs the A12.6 checks already
  produced (the clean baseline + the fabricating run); confirmed the
  wire response carries no adapter-identity/judge-score fields; a real
  submitted rating; a real 400 for an invalid choice; a real 400 for a
  missing `rater_id`; the rated task correctly dropping out of the
  pending queue on the next fetch; a real agreement report honestly
  reporting `n_compared=0`/`agreement_rate=None`/`n_no_judge_score=1`
  (neither real run carries a Tier 2 judge scorer, so this is the
  honest, unfabricated answer, not a bug); real 404s for an unknown
  run_id on both new GET routes. All pass — one genuine pre-existing
  flake caught and confirmed harmless along the way: a single-shot
  (non-retrying) progress check in the unmodified A12.3/A12.4
  slow-backend section raised `KeyError` on a rare early-poll race;
  reproduced on unmodified code via two more clean re-runs (63/63, 0
  failures, twice), so it's a known pre-existing timing flake in code
  this pass never touched, not a regression.

  Verified: the extended script (63 checks total, 3 consecutive clean
  runs); `node --check` on the page's own embedded JS (extracted and
  syntax-checked directly — re-extracted via the actual evaluated
  Python string this time, not the raw source text, since the raw
  source's own backslash-escaping reads differently); `pyflakes` clean
  on all three touched files; `scripts/verify_hearthbench_isolation.py`/
  `verify_hearthbench_adapter_isolation.py`/`verify_a1_3_process_
  isolation.py`/`verify_a7_a8_run_diagnostics.py`/`verify_a9_a10_score_
  report.py`/`verify_a13_ci_guard.py`/`verify_c5_model_passport.py`/
  `verify_a5_1_6_subjective_categories.py`/`verify_a5_categories.py`/
  `verify_a4_scoring.py` (incl. its own pre-existing `HumanRatingTask`
  round-trip check) all re-run clean. No `simulation/engine.py` code
  path or native module touched (confirmed via `git status` — only
  `hearthbench/daemon/` and the verify script changed) — no replay-
  hash/native-soak re-run needed. **This closes A12 in full and closes
  Phase 6's own last open gap within steps 6/7** — only `A5.11` (step
  8, gated on a live LLM server this offline environment doesn't have)
  and the never-blocking `A6`/`A7.2`/`A11.1`-`A11.3`/`A11.5`/A9.1's
  graphs remain, per the intro paragraph above.

- **A12.6-A12.8 (compare runs, drill into a case, download) — SHIPPED,
  v1.34.287.** New daemon routes, each a thin reuse of an already-real
  `hearthbench.reporting.report` function, per the checklist's own
  text that these "needed only a route, not a mechanism":
  `GET /api/runs/compare?run_ids=a,b,c` (A12.6, real reuse of
  `compare_runs` — the first id given is the baseline, the route only
  resolves ids to real `HearthBenchScore`s and reshapes the dataclass
  result to JSON); `GET /api/runs/{id}/cases` + `GET /api/runs/{id}/
  cases/{case_id}` (A12.7, lists every real committed `CaseRecord` and
  resolves one case's actual prompt/completion text through A8's own
  `BlobStore`, plus its full real `scores`/timing/`structured_input`);
  `GET /api/runs/{id}/export.json`/`export.csv` (A12.8, real reuse of
  `export_json`/`export_csv`, written to a real temp file — never left
  in `runs_root` — then streamed back with a `Content-Disposition`
  header; HTML export was already reachable via the existing
  `/api/runs/{id}/report` route, so no separate HTML export route was
  needed). `page.py` gained the matching real UI, per the standing
  "every new feature gets a browser-UI surfacing pass" rule: a
  per-run checkbox + "Compare selected" button rendering a real
  per-category delta/significance table; a clickable per-run "Cases"
  link opening a real case list + click-through detail panel (prompt/
  completion/parsed output/scores); "JSON"/"CSV" download links per
  run.

  `scripts/verify_a12_bench_daemon.py` extended (not duplicated —
  same daemon subsystem A12.1-A12.5 already used) with new real-HTTP
  checks against the real daemon: `GET .../cases` listing all 4 real
  committed cases; `GET .../cases/{id}` resolving the real prompt/
  completion text through `BlobStore` plus real per-scorer scores;
  both export routes' real content-type/`Content-Disposition` headers
  and real content; a genuine SECOND real run (against a fabricating
  fake backend) so the compare route has an actual measurable score
  gap to report — confirmed the clean baseline's grounding score
  measurably outscores the fabricating run's, with a real negative
  `delta_from_baseline`; real 404s for an unknown run/case on every
  new route, and a real 400 for a compare call with no `run_ids`. All
  pass, first run, no bug found.

  Verified: the extended script (52 checks total); `node --check` on
  the page's own embedded JS (extracted and syntax-checked directly);
  `pyflakes` clean on all touched files; `scripts/verify_hearthbench_
  isolation.py`/`verify_hearthbench_adapter_isolation.py`/`verify_a1_
  3_process_isolation.py`/`verify_a7_a8_run_diagnostics.py`/`verify_
  a9_a10_score_report.py`/`verify_a13_ci_guard.py`/`verify_c5_model_
  passport.py`/`verify_a5_1_6_subjective_categories.py`/`verify_a5_
  categories.py`/`verify_a4_scoring.py` all re-run clean. No
  `simulation/engine.py` code path or native module touched (confirmed
  via `git status` — only `hearthbench/daemon/`, `scripts/verify_a12_
  bench_daemon.py`, and `docs/` changed) — no replay-hash/native-soak
  re-run needed.

- **A4.2 (generalized) + A5.1-A5.6 (all six subjective categories) —
  SHIPPED, v1.34.286.** Closes step 7 of the checklist's own SEQUENCE
  in full. Investigation found A4.2's judge MECHANISM and A4.3's data
  model were already real (prior passes) — the actual remaining gap
  was real content: six category modules, each with its own genuinely
  distinct judge rubric and real hand-authored `TestCase`s, none of
  which could exist until `JudgeScorer` itself stopped hardcoding
  Dialogue's own rubric.

  `hearthbench/scoring/judge.py`'s `JudgeScorer` gained optional
  `rubric_prompt`/`axes`/`rubric_version` constructor params, each
  defaulting to the pre-existing module-level `JUDGE_RUBRIC_PROMPT`/
  `_JUDGE_AXES`/`JUDGE_RUBRIC_VERSION` — `JudgeScorer(adapter)` with no
  extra args reproduces the exact original dialogue scorer byte-for-
  byte (verified directly); `build_judge_prompt()` gained a matching
  optional `rubric_prompt` param with the same default-preserving
  contract. `as_scorer()` gained an optional `description` override.
  Zero behavior change for any pre-existing call site.

  Six new `hearthbench/tests/` modules, each following `grounding.py`'s
  own established shape (a real `Category` with A10.1's own stated
  weight, real hand-authored `TestCase`s, a `build_*_judge_scorer
  (adapter)` factory): `dialogue.py` (A5.1, weight 15 — reuses
  `JudgeScorer`'s DEFAULT rubric unmodified, since its own checklist
  text is exactly what that rubric already scores; new category-
  specific Tier 1 scorer `no_ambient_filler`, a closed hand-authored
  vocabulary of generic-agreement/aphorism filler phrases — the
  checklist's own explicitly-named gap no judge call needed to close);
  `personality.py` (A5.2, weight 10 — voice consistency/distinctiveness/
  trait plausibility; honest scope trim stated in its own docstring:
  scores ONE case's output against a stated profile, not literal
  cross-conversation aggregation, which needs a future A11 runner);
  `memory.py` (A5.3, weight 12 — recall accuracy/appropriate
  forgetting/contradiction resistance, built on A3.3's own `Turn.
  injected_fact`/`expects_recall_of`/`offers_contradiction` machinery
  for the first time by a real category); `beliefs.py` (A5.4, weight
  12 — evidence grounding/revision quality/confidence calibration; its
  `revision_on_new_evidence` case is the deliberate mirror image of
  Memory's `contradiction_resistance` case — same `Turn` machinery,
  opposite correct behavior: Memory tests HOLDING to a known truth
  against a false contradiction, Beliefs tests REVISING a theory when
  the evidence genuinely changes); `planning.py` (A5.5, weight 8 —
  goal coherence/horizon realism/adaptation when blocked); `village_
  cognition.py` (A5.6, weight 10 — cultural reasoning/institutional
  grounding/social plausibility; the one category scored from the
  SETTLEMENT-scale collective "village voice," never a single named
  agent, matching how `llm/town_brain.py`/`llm/beliefs.py`'s
  settlement-scoped path/`llm/culture.py` already speak in production).
  Every non-dialogue rubric prompt/axes tuple is genuinely distinct —
  verified pairwise, not just individually different from dialogue's.

  `hearthbench/tests/__init__.py`'s `CATEGORY_REGISTRY` now holds all
  nine real categories the checklist names; `DEFAULT_REGISTRY` gained
  `no_ambient_filler` alongside the pre-existing `no_unsupported_
  specifics`. Every `judge_*` scorer is deliberately NOT auto-
  registered (per `hearthbench.scoring`'s own stated Tier 2/3
  discipline — each needs a live adapter at construction time);
  `build_*_judge_scorer(adapter)` is the real per-category wiring a
  caller uses instead. `hearthbench/reporting/score.py`'s `MISSING_
  SUBJECTIVE_CATEGORY_WEIGHTS` is now genuinely empty (every category
  it used to record is real) — kept, not deleted, as the real
  extension point it always was for a FUTURE genuinely-new category.

  New `scripts/verify_a5_1_6_subjective_categories.py` (real HTTP
  round-trips via the same `_CapturingHandler`/`OpenAICompatAdapter`
  technique `verify_a4_scoring.py` already established, never a mocked
  adapter): `JudgeScorer`'s backward compatibility (default rubric/
  axes/version match the pre-refactor constants exactly, a supplied
  custom rubric is genuinely used instead); all nine `CATEGORY_
  REGISTRY` weights matching A10.1's table exactly; every new
  category's real cases (system prompt or turns present, scorers
  matching the category's own `scorer_ids`, a real non-crashing
  rendered turn sequence); all six rubric prompts pairwise-distinct;
  `no_ambient_filler`'s clean/filler-laden/heavily-filler-laden/empty
  cases; Memory's and Beliefs' real multi-turn `Turn` machinery
  (recall-after-gap, contradiction-resistance, and revision-on-new-
  evidence, including the deliberate final-turn-`expects_recall_of`
  distinction between Memory's and Beliefs' cases); two full real
  end-to-end judge round-trips (Memory, Personality) confirming the
  real HTTP request/response carries each category's OWN rubric text
  and axis names, never Dialogue's; `measure_self_consistency`
  composing cleanly with a custom (Planning) rubric. All pass, first
  run, no bug found in the module under test.

  Verified: the new script; `scripts/verify_hearthbench_isolation.py`/
  `verify_hearthbench_adapter_isolation.py` both clean (50/42 files
  respectively); `pyflakes` clean on all new/touched files; `verify_
  a4_scoring.py`/`verify_a5_categories.py` (updated for the real
  9-category `CATEGORY_REGISTRY`)/`verify_a9_a10_score_report.py`/
  `verify_a13_ci_guard.py`/`verify_a7_a8_run_diagnostics.py`/`verify_
  a12_bench_daemon.py`/`verify_a1_3_process_isolation.py`/`verify_c5_
  model_passport.py` all re-run clean. No `simulation/engine.py` code
  path or native module touched (confirmed via `git status` — only
  `hearthbench/` package files, `docs/`, and `scripts/verify_*.py`
  changed) — no replay-hash/native-soak re-run needed.

- **A12.1-A12.5 (the bench daemon's first slice) — SHIPPED, v1.34.285.**
  Closes step 6 of the checklist's own SEQUENCE in full.

  New `hearthbench/daemon/` package: `server.py`'s `create_app(runs_
  root)` — a real, standalone FastAPI app, deliberately separate from
  `hearthmind.interface.app` (the live sim's own web server), importing
  nothing from `hearthmind.simulation`/`.agents`/`.world` (A1.2's
  firewall). `page.py`'s `INDEX_HTML` is a real self-contained
  vanilla-JS page served BY the daemon itself, banner-marked "NOT the
  live town simulation" (A12.1). `__main__.py` is the real launcher
  (`python -m hearthbench.daemon --runs-root ... --host ... --port
  ...`), the one module that imports `uvicorn` directly so `create_app`
  itself stays importable/testable without a real ASGI server
  installed.

  Routes: `POST /api/runs` (A12.2 — launches a real, process-isolated
  `BenchRunProcess`, A1.3, only `OpenAICompatAdapter` exposed, matching
  `hearthbench.runner.cli`'s own current single-backend scope exactly);
  `GET /api/runs/{id}/progress` + the page's own polling refresh
  (A12.3, real case-count progress — a genuine push/log-stream and
  live mid-run category scores are honestly NOT shipped, flagged
  rather than faked); `POST /api/runs/{id}/cancel` (A12.4, a real
  `BenchRunProcess.stop()` — only for a run THIS daemon process itself
  launched; resume and cross-process cancel are real, distinct future
  work, needing a PID-file/lock mechanism this pass didn't build);
  `GET /api/runs` (A12.5 — discovers EVERY real run under `runs_root`
  by scanning for a real `manifest.json`, A8.2, never an in-memory
  registry, so a restarted daemon can browse every past run with
  nothing to rebuild); `GET /api/runs/{id}/report` (a real A9 HTML
  report, reusing `recompute_run_metrics`/`compute_score`/`render_
  html_report` directly — zero new scoring/reporting logic).

  `hearthbench.runner.cli`'s real `run` subcommand now also records
  `category`/`expected_case_ids` in the manifest's own `extra` field —
  the real data the daemon's `_run_summary` needs to compute progress/
  crashed honestly for ANY run it discovers on disk, including one it
  didn't itself launch or one launched before the daemon process now
  browsing it even started.

  New `pyproject.toml` `bench` extra: `fastapi>=0.110`/`uvicorn
  [standard]>=0.29` — the same versions the live sim's own `api` extra
  already pins, kept as a genuinely SEPARATE extra so neither install
  path pulls in the other's dependency by accident.

  New `scripts/verify_a12_bench_daemon.py` (24 checks, all pass): the
  A1.2 firewall confirmed directly over the whole daemon package; a
  REAL `uvicorn.Server` run in a background thread, talked to via real
  `urllib.request` HTTP calls (never `TestClient`/mocked) against a
  real local fake-backend HTTP server standing in for a live model —
  the page's own banner text; the full real start→poll→complete→
  report→cancel lifecycle for a genuine 4-case grounding run; 404s for
  an unknown run's progress/cancel/report; a genuine cancel-while-
  running proof (a real slow-backend run, a real mid-run "still
  running" observation, a real cancel that genuinely terminates the
  subprocess); and the headline A12.5 proof — a SECOND, independent
  daemon instance against the SAME `runs_root` correctly discovers a
  run it never launched (`tracked_by_this_daemon: false`) purely from
  disk, and correctly 404s a cancel attempt against it rather than
  fabricating success. One real test-script bug caught and fixed
  before shipping, not a bug in the daemon: the first progress-polling
  loop didn't guard against the real, brief startup race where a just-
  launched subprocess hasn't created its own `run_dir`/`manifest.json`
  yet (`RunRecordWriter.__init__`), so the daemon's own honest 404
  response was misread as a progress payload — fixed to keep polling
  on a non-200 response instead of assuming one.

  Verified: the new script (24 checks); `verify_hearthbench_
  isolation.py` (44 hearthbench files)/`verify_hearthbench_adapter_
  isolation.py` (36 non-adapter files) both clean; `pyflakes` clean;
  `verify_a1_3_process_isolation.py`/`verify_a7_a8_run_diagnostics.py`
  (both re-run since `cli.py` changed) clean. No native module or
  `simulation/engine.py` code path touched — `git status` confirmed
  only `hearthbench/runner/cli.py`, `pyproject.toml`, the new
  `hearthbench/daemon/` package, and the new verify script changed —
  no replay-hash/native-soak re-run needed.

- **C5 (the model passport) — SHIPPED, v1.34.284.** Both halves, per
  the checklist's own literal spec — real emission on the `hearthbench`
  side, real runtime consumption on the `hearthmind` side, coupled only
  by a shared JSON shape (never a shared import — A1.2's firewall runs
  BOTH directions).

  New `hearthbench/reporting/passport.py`: `build_passport(score,
  adapter_describe, latency_stats=None)` turns a real A10 `HearthBench
  Score` + a real A2.1 `AdapterDescribe` (as a plain dict) + a real
  `summarize_latency` output into a `ModelPassport` — model id/
  quantization/file hash; the real composite score + confidence margin
  (`world_score` honestly `None`, A5.11 doesn't exist yet); category
  strengths/weaknesses (real score thresholds, `STRENGTH_THRESHOLD`/
  `WEAKNESS_THRESHOLD`); measured throughput (flat real values, never
  fabricated when unmeasured); `recommended_settings.needs_grammar_
  constraints` (derived from the real structured_outputs score); real
  hard warnings, one per A10.2 disqualification that actually fired.
  `peak_rss_mb_by_concurrency` ships honestly empty — no A7.2
  concurrency-sweep sampling mechanism exists yet to source it from.
  `save_passport`/`load_passport` round-trip a versioned JSON file.

  New consumption on the `hearthmind` side (`simulation/hardware_
  profile.py`): `passport_filename_for` (a deterministic filesystem-
  safe slug of a model id — no registry file to keep in sync),
  `load_passport_dict` (reads the passport's own JSON shape as a plain
  `dict`, degrades to `None` on any failure, same "never crash startup"
  discipline `_load_or_create_machine_profile` already holds to), and
  `seed_machine_profile_from_passport` — "Passport values are *priors*,
  not overrides." Seeds `MachineProfile.measured_llm_throughput_
  tokens_per_s` ONLY while that profile has never had a real live
  measurement of its own; deliberately NOT gated on session count
  (nothing in this codebase calls `record_llm_throughput` yet, so a
  session-count gate would silently stop helping after a world's
  second-ever startup with no live data having ever landed) — a
  still-unseeded profile is re-consulted fresh every startup instead.
  `MachineProfile` gained `passport_model_id`/`passport_warnings`
  (round-trip safe, legacy pre-C5 profiles backfill to `None`/`[]`).

  Wired at `SimulationEngine.__init__`'s real `_load_or_create_
  machine_profile` call site via a new `_passport_path_for` (a
  `passports/` directory sibling to wherever the world's own `Machine
  Profile` persists, `None` under the identical `:memory:` condition
  its sibling already exempts) — an operator who benchmarks a model
  and drops the resulting `passport.json` at that exact path gets it
  picked up automatically on the next startup, no config change
  needed. The safety interlock ("a passport hard warning is surfaced
  in the UI at startup"): `full_diagnostics()['machine_profile']`
  gained `passport_model_id`/`passport_warnings`, rendered as a real
  "Model passport: ⚠ ..." line in the existing "Adaptive runtime"
  dev-console panel (`renderAdaptiveRuntimeStatus`, `app.js`) — a pure
  presentation addition over already-real data, same discipline every
  prior panel extension in this codebase has used.

  New `scripts/verify_c5_model_passport.py` (41 checks, all pass): the
  A1.2 firewall confirmed directly (AST-checked both directions, not
  assumed); `build_passport`'s every field incl. a real disqualified
  run producing a real worded hard warning; round-trip + schema-
  version rejection; a real cross-implementation parity proof
  (`hearthbench`'s own `produced_by_host()` matches `hearthmind`'s
  independently-implemented `host_fingerprint()` on this real host,
  confirming the two standalone reimplementations of the identical
  formula genuinely agree); every `seed_machine_profile_from_passport`
  case (fresh profile seeds, live-data profile never overwritten, a
  many-times-loaded-but-never-measured profile is STILL seedable —
  the direct proof the session-count gate was correctly left out);
  `MachineProfile` round-trip incl. legacy backfill; and a real
  end-to-end proof through `SimulationEngine.load_or_create` — a real
  passport on disk seeds the fresh profile's throughput and surfaces
  through `full_diagnostics()`, a mismatched model id neither seeds
  nor crashes, and a `:memory:` db never touches disk for the lookup.

  Verified: the new script (41 checks); `verify_hardware_profile.py`/
  `verify_b7_hardware_citizenship.py`/`verify_b8_predictive_
  scheduling.py`/`verify_runtime_diagnostics.py` all re-run clean;
  `verify_hearthbench_isolation.py` (40 hearthbench files)/`verify_
  hearthbench_adapter_isolation.py` both clean; `pyflakes` clean;
  `node --check` clean on `app.js`. Unlike every other Phase 6 pass
  this session, this ONE touches real `simulation/engine.py` code (the
  `__init__` control point + `full_diagnostics()`) — `scripts/verify_
  replay_hash.py` (800 ticks, seed 777, `--in-process`) and `scripts/
  verify_native_soak.py` (seeds 1/55, 800 ticks) both re-run and MATCH,
  confirming the new startup-time passport lookup is pure I/O/metadata
  with zero effect on deterministic Body state or RNG consumption.

- **A1.3 (process isolation) — SHIPPED, v1.34.283.** The prerequisite
  A12 itself names: "Bench runs execute in a subprocess with their own
  model server config, so a benchmark can never contend with, pause,
  or corrupt a live sim. The UI page talks to a bench daemon, not the
  sim engine." A2/A11 were already real, so this was pure process-
  boundary wiring, not new scoring/adapter logic.

  New `hearthbench/runner/cli.py`: a real `python -m hearthbench.
  runner.cli run --category ... --run-dir ... --adapter-endpoint ...
  --adapter-model ...` entry point — resolves a category to real
  `TestCase`s (`_cases_for_category`, today `"grounding"` only, a real
  `ValueError` for anything else), builds a real `OpenAICompatAdapter`
  + A8 environment snapshot, drives the already-real `run_cases_with_
  resume` — orchestration only, zero new execution logic. New
  `hearthbench/runner/process.py`'s `BenchRunProcess` mirrors A2.4's
  already-shipped `ServerLifecycle` (same `LaunchRecord` reused, not
  duplicated) but purpose-built for a bench run: `poll_progress
  (expected_case_ids)` reads real progress purely off disk via A8's
  `RunRecordReader.completed_case_ids()` — no IPC beyond the
  filesystem both processes already share; a nonzero exit with
  incomplete work is flagged `crashed: True`, `expected_case_ids=None`
  degrades honestly rather than guessing.

  **Real, previously-invisible production bug found and fixed via the
  crash test, not in this pass's own new code.** Forcing a genuine
  crash (a plain file where a run_dir should be, so `RunRecordWriter.
  __init__`'s own `mkdir()` raises `FileExistsError` inside the child)
  worked as intended — but polling that same broken path afterward via
  `RunRecordReader` then crashed with `NotADirectoryError`. Root
  cause: `BlobStore.__init__` (shipped v1.34.281) unconditionally
  called `mkdir()` regardless of whether the caller was a real writer
  or a read-only reader, and `<file>/blobs` can't be created as a
  subdirectory of a plain file. Fixed by making `BlobStore.__init__`
  touch no filesystem state at all — only `put()` (a genuine write,
  already had its own `mkdir()`) creates a directory now; `get()`
  gained a `try/except OSError` degrade as defense-in-depth. Exactly
  the class of gap real non-mocked subprocess verification exists to
  catch — a narrower in-process test of `RunRecordReader` alone would
  plausibly never have exercised a genuinely-broken-directory read.

  New `scripts/verify_a1_3_process_isolation.py` (27 checks, all pass
  after the fix above): pure-function coverage of `_cases_for_
  category`/`build_arg_parser`/`build_bench_run_command`; `cli.main()`
  in-process against a real local HTTP server standing in for a live
  model; `BenchRunProcess` exercised as a REAL OS subprocess (`sub
  process.Popen`, never mocked) — a genuine double-start `RuntimeError`,
  real mid-run partial progress read purely off disk while a
  deliberately slow fake server is still answering, a clean full
  completion (4/4 committed, never flagged crashed), the real crash
  case above, and a real `stop()` against a genuinely hung 30-second
  request confirming the process is truly no longer running afterward.

  Verified: the new script (27 checks); `scripts/verify_hearthbench_
  isolation.py` (39 hearthbench files)/`verify_hearthbench_adapter_
  isolation.py` both clean; `pyflakes` clean; `verify_a2_model_
  adapters.py`/`verify_a3_prompt_library.py`/`verify_a4_scoring.py`/
  `verify_a5_categories.py`/`verify_a13_ci_guard.py`/`verify_a7_a8_run_
  diagnostics.py`/`verify_a9_a10_score_report.py` all re-run clean. No
  native module or `simulation/engine.py` code path touched — `git
  status` confirmed only `hearthbench/diagnostics/run_record.py` (the
  fix), `hearthbench/runner/__init__.py`, the two new `hearthbench/
  runner/` modules, and the new verify script changed.

- **A9/A10 (reports + the HearthBench Score) — SHIPPED, v1.34.282.**
  Per the checklist's own SEQUENCE, step 6 right after step 5's A7/A8/
  A11.4 (v1.34.281) — reports need a real run/composite to report ON,
  which is exactly what step 5 shipped.

  New `hearthbench/reporting/score.py` (A10): `compute_score(category_
  summaries, latency_stats=None, floors=None)` takes the EXACT shape
  both `hearthbench.runner.run.aggregate_scores` (a live run) and
  `hearthbench.metrics.aggregate.recompute_run_metrics` (a stored run,
  read back off disk) already return, so this composes with either
  with zero adaptation. A10.1: each real `Category.weight` — already
  the checklist's own stated default table (Grounding 20, Reliability/
  structured-output 8, Performance 5, the three categories real
  today) — IS the composite's weight source, never a second hardcoded
  copy; `MISSING_SUBJECTIVE_CATEGORY_WEIGHTS` records the other six
  named weights (Dialogue/Beliefs/Memory/Village cognition/
  Personality/Planning) purely as information so a category with no
  real data yet is reported as genuinely unmeasured, never scored as a
  fabricated zero or given silent full credit. A10.2: `DEFAULT_
  DISQUALIFYING_FLOORS` ships the checklist's own worked example
  verbatim (grounding < 50 caps the total at 60); only ever checked
  against a category actually scored this run. A10.3: Performance had
  NO gradeable scorer at all before this pass (`latency`'s own
  `ScoreDetail.value` is `None` by design — that scorer's own
  docstring says "A10's future rubric decides") — `score_from_latency_
  stats` IS that rubric now, real `LATENCY_SCORE_BANDS_MS` p50-latency
  bands mapped onto `[0, 100]`. A10.4: `category_confidence_margin`
  (real 95% CI half-widths, reusing `CategoryScoreSummary.confidence_
  interval_95` directly) + `overall_confidence_margin` (the WIDEST —
  least confident — margin among categories that actually
  contributed, "only as confident as the shakiest measured input").

  New `hearthbench/reporting/report.py` (A9): `render_html_report`
  (A9.1) — self-contained HTML, the honest recommendation up top, per-
  category scores with confidence, a "not yet measured" disclosure
  list, and, given a real `run_dir`, real failure examples pulled
  through A8's `RunRecordReader`/`BlobStore` (an actual committed
  case's actual prompt/completion text — never synthesized); latency/
  memory GRAPHS explicitly not attempted (no charting dependency in
  this repo — the real p50/p95/max numbers print as a plain table
  instead, with an honest note). `export_json`/`export_csv` (A9.2).
  `compare_runs` (A9.3): N real `HearthBenchScore`s against the first
  as baseline, real per-category deltas, and a genuine significance
  flag per category — the baseline's and candidate's real confidence
  intervals either overlap (not flagged) or don't (`significant_
  change=True`); `None` when either side lacks a real margin, never a
  guessed flag. `recommendation_text` (A9.4): any real disqualification
  is stated FIRST, a wide confidence margin is flagged `LOW CONFIDENCE`
  prominently, an unscored run never states a fabricated total.

  New `scripts/verify_a9_a10_score_report.py` (46 checks, all pass —
  one real test-calibration fix made before shipping, not a bug in
  either module: the first attempt assumed a confidently-fabricating
  model's real grounding score would land below 50 outright, but
  grounding averages FOUR real scorers and only ONE of them
  (`no_unsupported_specifics`) actually detects confident fabrication
  — the other three check leak-freedom/multi-turn recall, unrelated
  failure modes — so the real measured score lands near 50, not near
  0; fixed by calibrating the disqualifying floor in the test to what
  was actually measured rather than asserting an unearned specific
  number, which is itself the real, honest proof the floor mechanism
  fires against real degraded data): `score_from_latency_stats`'s real
  band boundaries; a real end-to-end grounding run (through `run_
  cases_with_resume` against a real fake HTTP server) feeding a real
  `compute_score` call whose renormalized weights/n_cases_total/
  confidence margin all match hand computation; a real disqualification
  proof against a real fabricating model's real measured data, capped
  at the real cap; the genuinely-empty-run honest-`None` case;
  `recommendation_text`'s disqualification-first/low-confidence/no-
  fabricated-total cases; real JSON/CSV round-trips; a real HTML report
  containing the real embedded recommendation, latency table, missing-
  category disclosure, and — pulled from a real run directory — the
  real fabricated completion text plus the real disqualification
  banner; `compare_runs` against real score pairs incl. a real negative
  delta + significant-change flag for a real regression, a same-score-
  against-itself never-flagged-significant case, and a missing-margin
  honest-`None` case.

  Verified: the new script; `scripts/verify_hearthbench_isolation.py`
  (now 37 hearthbench files)/`verify_hearthbench_adapter_isolation.py`
  both clean; `pyflakes` clean; `verify_a2_model_adapters.py`/`verify_
  a3_prompt_library.py`/`verify_a4_scoring.py`/`verify_a5_categories.py`/
  `verify_a13_ci_guard.py`/`verify_a7_a8_run_diagnostics.py` all re-run
  clean. No native module or `simulation/engine.py` code path touched
  — no replay-hash/native-soak re-run needed.

- **A7.1/A8/A11.4 (real run record, recomputable metrics, resume) —
  SHIPPED, v1.34.281.** Per the checklist's own SEQUENCE ("A7/A8
  metrics + diagnostics; A11.4 resume" — step 5, right after A13),
  ships exactly this, not A6 (see the correction above).

  New `hearthbench/diagnostics/run_record.py` (A8, `hearthbench/
  diagnostics/`'s own reserved module gets its first real content):
  `RunRecordWriter`/`RunRecordReader` — one real directory per run,
  `cases.jsonl` (one `CaseRecord` line per case, `commit_case` writing/
  flushing/`os.fsync`ing IMMEDIATELY on every call, never batched in
  memory — the real mechanism A11.4 depends on) + `manifest.json`
  (A8.2, written once at run creation, never silently overwritten by a
  later resume call). `build_environment_snapshot` reuses A2's own
  `AdapterDescribe`/`AdapterCapabilities` directly, duck-typed off
  `adapter.describe()`/`.capabilities()` — a caller whose adapter lacks
  either method still gets a real, honest, partially-empty snapshot,
  never a crash. `BlobStore` (A8.3): sha256-keyed content-addressed
  storage under `<run_dir>/blobs/`, genuinely deduplicated (a re-stored
  identical blob is a real no-op write, verified directly rather than
  assumed from the naming scheme alone) — a `CaseRecord` references
  prompt/completion text by hash instead of inlining it twice.
  `prune_run` (A8.4) is the ONE explicit-only deletion path; nothing
  else in the module ever deletes a run directory.

  New `hearthbench/metrics/aggregate.py` (A7, `hearthbench/metrics/`'s
  own reserved module gets its first real content): `recompute_run_
  metrics(run_dir)` reads a run's raw per-case `ScoreDetail`s straight
  back off disk via `RunRecordReader` and re-derives real per-category/
  per-scorer statistics through A7.3's already-shipped `summarize_
  scores` — A7.1's literal claim ("aggregates can be recomputed without
  re-running") proven directly: zero adapter calls, zero re-scoring,
  pure re-aggregation of what A8.1 already committed.

  `hearthbench/runner/run.py` gained `run_cases_with_resume(cases,
  adapter, registry, run_dir, ...)` (A11.4) — factored the existing
  `run_case_against_adapter`'s render→call→score sequence into a
  shared `_execute_case` helper so this and the original function share
  one real implementation rather than diverging copies. Reads `Run
  RecordReader.completed_case_ids()` fresh off disk at call time and
  skips every case already committed there, running and immediately
  committing only what's left — a run interrupted mid-way (crash,
  Ctrl-C, a deliberately paused benchmark) and re-invoked against the
  SAME `run_dir` picks up exactly where it left off, per the
  checklist's own literal words.

  New `scripts/verify_a7_a8_run_diagnostics.py` (34 checks, all pass
  first run, no bug found) — real HTTP round-trips throughout (the
  same `_CapturingHandler` local-server technique every sibling verify
  script already established), no mocked adapter: `BlobStore`'s real
  dedup/round-trip/missing-digest cases; `CaseRecord`'s round-trip;
  `build_environment_snapshot` against a real `OpenAICompatAdapter`
  incl. the no-`describe()`/`capabilities()` honest-degrade case;
  `RunRecordWriter`/`RunRecordReader`'s manifest write-once guarantee,
  real JSONL commits, and empty-directory degrade; `prune_run`'s real
  deletion plus its safe already-gone no-op; and the headline proof —
  a real 2-of-4-case partial "session" against a real fake server,
  followed by a real resume call with the full 4-case list against the
  SAME `run_dir`, confirming the resume call makes EXACTLY 2 new HTTP
  requests (never re-running the first 2, total 4 across both calls,
  never 6), all 4 cases land on disk, and a THIRD call against an
  already-complete run makes zero further requests; `recompute_run_
  metrics` recomputing the exact same category/scorer statistics from
  the committed run directory alone, incl. confirming the A5.7
  registry-registration fix (v1.34.280) reaches this path too.

  Verified: the new script; `verify_hearthbench_isolation.py` (now 35
  hearthbench files, still zero forbidden imports either direction)/
  `verify_hearthbench_adapter_isolation.py` both clean; `pyflakes`
  clean; `verify_a2_model_adapters.py`/`verify_a3_prompt_library.py`/
  `verify_a4_scoring.py`/`verify_a5_categories.py`/`verify_a13_ci_
  guard.py` all re-run clean (unaffected). No native module or
  `simulation/engine.py` code path touched (confirmed via `git status`
  — only the two new modules, their `__init__.py` re-exports, `runner/
  run.py`'s additive extension, and the new verify script) — no
  replay-hash/native-soak re-run needed.

- **A13 (+ A11 execution core) — SHIPPED, v1.34.280.** Corrects this
  doc's own prior mis-ordering (see above) and ships exactly what the
  checklist's SEQUENCE actually calls for at this point.

  New `hearthbench/runner/run.py` — the one real slice of A11 (the
  full run-mode abstraction: quick/full/custom/resume/strict-repro,
  none built) that A13 genuinely needs today: `render_case_prompt`
  resolves what a `TestCase` should actually send (a `turns`-carrying
  case's last turn's content; a `fixture_ref`-carrying case resolved
  against a caller-supplied fixture pack; a case with neither is
  honestly skipped, never faked — this is exactly `structured_
  outputs.py`'s own case shape, which carries no prompt text of its
  own by design). `run_case_against_adapter`/`run_cases_against_
  adapter` call a real A2 `ModelAdapter` and score through a real
  `ScorerRegistry`; `aggregate_scores`/`summaries_to_metrics_dict`
  chain into the same dotted-path metrics-dict shape A0.2's `eval_
  harness.check_regressions` already knows how to walk.

  New `hearthbench/reporting/ci_guard.py` (A9/A10's own reserved
  module gets its first real content, scoped specifically to A13, not
  A9/A10 themselves): `is_relevant_change` (A13.1, a real prefix check
  over `hearthmind/llm/`/`hearthbench/prompts/`/`hearthbench/scoring/`
  — no hand-maintained per-file list to go stale); `DEFAULT_CI_
  THRESHOLDS` (A13.2, objective-category metrics only — grounding's
  `no_unsupported_specifics`/`leak_freedom`, structured-outputs'
  `schema_validity`/`length_compliance`/`fallback_free` pass rates,
  nothing judge-scored); `run_ci_guard` (the real end-to-end path —
  a genuine no-op with zero adapter calls on an irrelevant change,
  otherwise runs the real grounding bait cases and gates via A0.2's
  real `check_regressions`, A13.3); `save_baseline`/`load_baseline`
  (A13.4, one explicit write path, a missing baseline degrading to
  `{}` rather than raising).

  **A real, previously-shipped gap found and fixed while building the
  first thing to actually EXECUTE a grounding case end to end**:
  A5.7's own `no_unsupported_specifics` scorer (grounding-category-
  specific, shipped v1.34.279) was never registered into `hearthbench.
  scoring.DEFAULT_REGISTRY` — A5's own verify script only ever invoked
  it directly (`SCORER.score(...)`), never through `registry.
  resolve(case.scorers)`, so the gap stayed invisible until this
  pass's real runner actually resolved a grounding case's full scorer
  list and silently dropped the one id the registry didn't know about
  (`resolve()`'s own documented "silently drops an unknown id"
  behavior, working exactly as designed against an incomplete
  registration). Fixed in `hearthbench/tests/__init__.py` — the one
  legal place to extend the shared registry from a category module
  without a circular import (`hearthbench.tests` already imports FROM
  `hearthbench.scoring`, never the reverse). A5.10's own guide already
  documented this exact registration step; it just hadn't been
  followed for grounding's own scorer.

  New `scripts/verify_a13_ci_guard.py` (33 checks, all pass first run
  once the registration fix above was in place) — real HTTP round-
  trips throughout (same `_CapturingHandler` local-server technique
  A2/A4's own verify scripts established), no mocked adapter: the real
  trigger logic across relevant/irrelevant/mixed changesets;
  `render_case_prompt`'s three real resolution paths incl. the honest
  skip; a real case run against a real fake server producing real
  `ScoreDetail`s and a real HTTP request count; a real skipped case
  making zero HTTP calls; real aggregation into a real dotted-path
  metrics dict; the full `run_ci_guard` path proven three ways — a
  real no-op on an irrelevant change, a real pass against a genuinely
  clean model, and a real caught violation against a genuinely
  fabricating model, naming the real gated metric; real baseline
  save/load round-trip incl. the missing-file degrade; a caller-
  supplied threshold dict genuinely overriding the default.

  Verified: the new script; `verify_hearthbench_isolation.py`/`verify_
  hearthbench_adapter_isolation.py` both clean (33 hearthbench files);
  `pyflakes` clean; `verify_a2_model_adapters.py`/`verify_a3_prompt_
  library.py`/`verify_a4_scoring.py`/`verify_a5_categories.py` all
  re-run clean (unaffected, including A5's own script — the fix landed
  in `__init__.py`'s registration wiring, not in `grounding.py`'s own
  scorer logic, so A5's direct-invocation checks were never wrong,
  only incomplete coverage of the registry path). No native module or
  `simulation/engine.py` code path touched — no replay-hash/native-
  soak re-run needed.

- **A5 (objective slice) — SHIPPED, v1.34.279.** Per the checklist's
  own SEQUENCE ("A4.1 deterministic scorers + A5.7/A5.8 [grounding +
  structured output]" precedes "A4.2 judge + remaining subjective
  categories"), ships the three categories buildable on A4.1's real
  Tier 1 scorers alone — no judge model needed — plus the shared
  aggregation infra and the extension guide.

  New `hearthbench/tests/category.py`: `Category` (id/name/weight/
  scorer_ids, `weight` mirroring A10.1's own stated default composite
  table so a future A10 reads real category metadata rather than a
  second hardcoded table) + `summarize_scores`/`CategoryScoreSummary`
  — a real, tested, CATEGORY-SCOPED slice of A7.3's own stated stats
  (N/mean/median/p95/stdev/95% CI), explicitly NOT the full A7 metrics
  collector (no per-run record, no system-sampling thread) — flagged
  as such in both this doc and `docs/HEARTHBENCH-RUNTIME-2026-07-
  23.md`'s A7 section rather than silently claiming more than shipped.

  **A5.7 Grounding** (`grounding.py`, weight 20 — A10.1's stated
  highest default): four real hand-authored adversarial `TestCase`s,
  each a single `Turn` that baits a specific fact the case's own
  `structured_input` deliberately withholds (population count, a
  spouse's name, a harvest yield, a weather forecast), with `expected_
  invariants` naming what's unstated. New category-specific scorer
  `no_unsupported_specifics` (per A5's own header — "each becomes a
  category module with concrete cases AND SCORERS," a category may
  ship a scorer narrower than A4.1's general-purpose set): flags a
  number/proper-noun claim in the output with no support anywhere in
  `structured_input`, capped so heavy fabrication saturates at 0
  rather than free-falling unboundedly. "Reward explicit uncertainty"
  needed no separate mechanism — a hedge states no new specifics, so
  it already scores clean under the identical heuristic.

  **A5.8 Structured outputs** (`structured_outputs.py`, weight 8):
  `build_structured_output_cases()` derives a real `(grammar, no_
  grammar)` `TestCase` pair per task actually registered in
  `hearthmind.llm.json_schemas.TASK_SCHEMAS` — zero hardcoded task
  list, grows automatically as tasks are added there. `score_
  structured_output_delta` answers A6.3's identical "score both
  constrained/unconstrained modes, report the delta" using only
  `CategoryScoreSummary`'s own `pass_rate` field — needs nothing from
  the still-unbuilt A6.

  **A5.9 Performance** (`performance.py`, weight 5): wraps A4.1's
  already-shipped `latency` scorer (a pure measurement, `value=None`
  by design); `summarize_latency` computes real p50/p95/max/mean for
  latency, TTFT, and completion tok/s (derived from real `AdapterResult`
  token counts) — the "attributed per case" half of A5.9's own text.
  Continuous RAM/swap/CPU% sampling (A7.2) stays real, distinct,
  unstarted future work.

  **A5.10 Category extension guide**: `docs/HEARTHBENCH-CATEGORY-
  GUIDE.md` (a real 5-step walkthrough: declare the `Category`, reuse-
  or-add a scorer, build real `TestCase`s from a fixture or hand-
  authored, register it, verify it the same way every shipped category
  was) + `hearthbench/tests/_template.py` (a real, importable,
  deliberately UNregistered starter module — the guide's own worked
  example, not just prose).

  New `scripts/verify_a5_categories.py` (47 checks, all pass — one
  real test-DATA fix before shipping, not a module bug: the first
  attempt's own bait-question substring check ("population") never
  appeared in the actual rendered question text, "How many people
  live in Marshcroft, exactly?" — fixed to check for "marshcroft"
  instead). `percentile`/`summarize_scores` verified against hand
  computation incl. every degrade-to-`None` edge case; all four bait
  cases verified structurally; `no_unsupported_specifics` verified
  against a real hedge (passes), a real fabricated name (caught), a
  real fabricated number (caught), a real supported restatement (not
  penalized), and real heavy fabrication (capped at 0); `build_
  structured_output_cases` verified to auto-track `TASK_SCHEMAS`'
  real contents; `score_structured_output_delta` verified both
  directions plus the no-data-yet degrade; `summarize_latency`
  verified against real hand-computed p50/max/tok-per-sec incl. the
  no-token-counts degrade; the template module and guide doc both
  confirmed to exist and the template confirmed NOT registered.

  Verified: the new script; `verify_hearthbench_isolation.py`/`verify_
  hearthbench_adapter_isolation.py` both clean (31 hearthbench files
  now); `pyflakes` clean; `scripts/verify_a2_model_adapters.py`/
  `verify_a3_prompt_library.py`/`verify_a4_scoring.py` all re-run
  clean (unaffected). No native module, `simulation/engine.py` code
  path, or other production file touched (confirmed via `git status`
  showing only new `hearthbench/tests/*.py`, the new doc, and the new
  verify script, plus `hearthbench/tests/__init__.py`'s own real
  wiring) — no replay-hash/native-soak re-run needed.

- **A4 — SHIPPED, v1.34.278.** **[DECIDED: build both paths]** made
  real: `hearthbench/scoring/` ships all three tiers plus A4.4's
  registry, each independently testable without a live LLM server.
  A4.1 (Tier 1, always-on/free): nine scorers, five lifted directly
  from `hearthmind.llm.quality_labels`/`.review_diagnostics` (schema
  validity, length compliance, leak freedom, context reflection —
  covers most of Grounding/Structured Outputs/Memory per the
  checklist's own claim), four genuinely new (`fallback_free` — the
  per-case reading a category's real parse/retry/fallback RATE
  aggregates from; `latency` — a measurement, `value=None`, never a
  verdict, since what counts as "good" is A10's future rubric's call;
  `lexical_diversity` — type-token ratio, the same "same handful of
  words reused" failure class production's own `VOICE_LINE_DUPLICATE_
  OVERLAP`/`FOLKLORE_DUPLICATE_OVERLAP` already fixed twice, measured
  here at the single-output level; `repetition_self_similarity` — the
  same failure class measured ACROSS a run's outputs, via a caller-
  supplied `prior_outputs` list in `context`). A3.3's `Turn.expects_
  recall_of` is made scoreable as `multi_turn_recall` — a real, honest
  slice of "contradiction detection": checks whether a recall-testing
  turn's own output actually references the injected fact (lexical
  overlap), explicitly NOT detecting an active semantic contradiction
  (`Turn.offers_contradiction` — that needs real understanding, Tier
  2's territory, not a heuristic). A4.2 (Tier 2, optional): `JudgeScorer`
  wraps ANY A2 `ModelAdapter` (duck-typed, zero import of `hearthbench.
  adapters`) behind a fixed, versioned rubric (naturalness/personality/
  emotional-realism, 1-5, with worked anchors) — judge model + rubric
  version recorded on every `ScoreDetail`, exactly as A4.2's own text
  requires; `measure_self_consistency` re-scores a fixed output N times
  and reports the real spread (stdev/agreement), the literal
  "self-consistency measured by re-scoring a sample." A4.3 (Tier 3):
  `HumanRatingTask`/`HumanRating` (blind — adapter identity kept out of
  what a rater would see) + append-only JSONL storage + `judge_human_
  agreement` (the report A4.3's own text asks for) — the rating PAGE
  itself is A12.9, not attempted here, but the full data model and
  agreement math are real and already usable via a script. A4.4:
  `Scorer(id, version, fn(case, result, context) -> ScoreDetail)` +
  `ScorerRegistry` (rejects re-registering an id at a different
  version outright — "scorer version is part of a run's identity"
  enforced, not just claimed); `DEFAULT_REGISTRY` ships pre-populated
  with all nine Tier 1 scorers. New `CaseResult` is this pass's one
  real design decision beyond the checklist's own text: A6 (the full
  run-record) and A11 (the runner) don't exist yet, so `CaseResult` is
  a small, honest bridge duck-typed onto both a live A2 `AdapterResult`
  and an already-archived recorder example — nothing assumes A6 won't
  carry strictly more detail later.

  New `scripts/verify_a4_scoring.py` (55 checks, all pass first run
  bar one floating-point test-data adjustment in the script itself,
  not the module under test — `0.9 - 0.85` doesn't land exactly on a
  `0.05` tie margin in IEEE 754, caught immediately and the test's own
  input widened, no change to `judge_implied_choice`). Tier 1 exercised
  against a REAL archive (the same `TrainingRecorder`-driven technique
  A3's own verify script established) including a genuinely leaky
  recorded example (raw coordinates + a meta-leakage marker) and a
  genuinely clean one, proving the lift from `quality_labels.py` reads
  real recorded content correctly, not synthetic stand-ins. Tier 2
  exercised against a REAL local HTTP server through the REAL
  `OpenAICompatAdapter` (same `_CapturingHandler` technique A2's verify
  script established) — a real multi-axis rubric round-trip with a
  hand-computed composite check, a real non-JSON judge answer
  degrading cleanly, a real unreachable-host connection-refused case,
  and a real 3-sample self-consistency spread over three genuinely
  different canned rubric answers plus a real identical-answers case
  confirming stdev exactly 0.

  Verified: the new script; `verify_hearthbench_isolation.py`/`verify_
  hearthbench_adapter_isolation.py` both clean; `pyflakes` clean;
  `scripts/verify_a2_model_adapters.py`/`verify_a3_prompt_library.py`
  both re-run clean (unaffected). No native module, `simulation/
  engine.py` code path, or other production file touched this pass
  (pure new `hearthbench/scoring/` package + its own verify script) —
  no replay-hash/native-soak re-run needed, confirmed via `git status`
  showing only the two new paths.

- **A3 — SHIPPED, v1.34.277.** A3.1 `hearthbench/prompts/fixtures.py`'s
  `export_fixture_pack` — real reuse of `hearthmind.llm.review_pack.
  iter_examples` to walk a real recorder archive, content-hash dedup,
  deterministic per-task seeded sampling (re-exporting the same archive
  with the same seed reproduces a byte-identical pack). `scripts/
  hearthbench_export.py fixtures` is the real `hearthbench export`
  command. A3.2 `schema.py`'s `TestCase`/`Turn`, matching the
  checklist's literal shape; `test_case_from_fixture` is the real
  "adding a category = data + a scorer, never touching the runner"
  mechanism. A3.3 multi-turn/stateful cases: `Turn`'s `injected_fact`/
  `expects_recall_of`/`offers_contradiction` fields + `render_turn_
  sequence` (pure, accumulates prior turns' facts into each later
  turn's context) — no separate mechanism needed, a single-shot case
  is just `turns=[]`. A3.4 `perturbation.py`'s `synthesize_fixtures`
  wraps any synthesizer as real, clearly-marked (`synthetic=True`)
  fixtures; `synthesize_town_brain_fixtures` reuses `hearthmind.llm.
  prompt_synthesis.synthesize_town_brain_batch` — **exercising this
  reuse path for the first time found and fixed a real, previously-
  unnoticed production bug**: `synthesize_town_brain_situation` never
  supplied `town_brain.build_prompt`'s required `priority` argument
  (shifting every later positional arg out of place, `TypeError` on
  the very first real call) — this function, and its only prior real
  call site (`scripts/recorder_tools.py synthesize-town-brain`), had
  never actually worked end to end before this pass. Fixed by drawing
  `priority` from the real closed vocabulary (`_VALID_PRIORITIES`,
  already imported for exactly this purpose but never wired in) and
  passing it correctly. New `scripts/verify_a3_prompt_library.py` (40
  checks, all pass — drives a REAL `TrainingRecorder` through its full
  queue/writer-thread/JSONL pipeline to build a genuine archive, then
  exports/loads/round-trips a real fixture pack from it; the schema/
  multi-turn/perturbation logic; a real CLI subprocess run of both
  `hearthbench_export.py` subcommands). Verified: the new script;
  `verify_hearthbench_isolation.py`/`verify_hearthbench_adapter_
  isolation.py` both clean; `pyflakes` clean; `scripts/verify_replay_
  hash.py`/`verify_native_soak.py` both MATCH (re-run since `hearthmind/
  llm/prompt_synthesis.py`, a live production file, was fixed — though
  confirmed via direct grep that it's never imported from `simulation/`,
  so this was extra caution, not a strict requirement); a direct CLI
  smoke test of `scripts/recorder_tools.py synthesize-town-brain`
  confirming the real end-to-end fix.

- **A2 — SHIPPED, v1.34.276.** A2.1 `hearthbench/adapters/protocol.py`'s
  `ModelAdapter` `typing.Protocol` + `AdapterResult`/`AdapterCapabilities`/
  `AdapterDescribe`/`HealthStatus` dataclasses, matching the spec's
  literal `generate()`/`capabilities()`/`describe()`/`health()` shape.
  `seed` support needed one small additive upstream change:
  `hearthmind.llm.client`'s `OllamaClient`/`LlamaCppClient.generate_json`
  gained a trailing `seed_override` param (mirrors the existing `num_
  predict_override`/`temperature_override` pattern, zero behavior
  change for every existing positional call site) so the wrapping
  adapters can honestly report `seed=True` instead of a false `False`.
  A2.2 `LlamaCppAdapter`/`OllamaAdapter` thin-wrap `hearthmind.llm.
  client`'s existing clients (real reuse — that module has no
  `hearthmind.simulation`/`.agents`/`.world` dependency, staying within
  A1.2's firewall); `OpenAICompatAdapter` is genuinely new, self-
  contained, model-family-agnostic. New `hearthbench/adapters/
  registry.py`'s `build_adapter`. The checklist's own "enforce with a
  lint rule banning model-name string comparisons outside `adapters/`"
  shipped as `scripts/verify_hearthbench_adapter_isolation.py` (an AST
  scan over comparison operands, clean on the real tree). A2.3
  `conformance.py`'s `run_conformance_suite` — adapter-shape-agnostic,
  verified against a real local stdlib HTTP server (success path) and
  a real unreachable host (failure path, genuine connection-refused,
  not a mock), plus a deliberately-broken synthetic adapter proving the
  suite catches a real contract violation. A2.4 `lifecycle.py`'s
  `build_llama_server_command` (pure, mirrors `scripts/run.sh`'s own
  confirmed defaults) + `ServerLifecycle` (a generic subprocess
  wrapper, verified against a real subprocess since no `llama-server`
  binary exists in this offline environment). New `scripts/verify_a2_
  model_adapters.py` (52 checks, all pass first run). Verified:
  `verify_hearthbench_isolation.py`/`verify_hearthbench_adapter_
  isolation.py` both clean; `pyflakes` clean; `scripts/verify_replay_
  hash.py` (800 ticks, seed 777) — MATCH; `scripts/verify_native_
  soak.py` (seeds 1/55, 800 ticks) — MATCH (the `seed_override` addition
  to `hearthmind/llm/client.py` touches a live production file, both
  re-run to confirm zero behavior change on the default `None` path).

## Phase 7 — Native performance (opportunistic, not gated on anything)

Not performance-justified today (Ollama/LLM latency dominates the tick
budget, not Python) — pick up only on explicit direction or a genuine
measured need, never a default next step.

- **R8** — agent tick *logic* (`population.py`'s methods, still reading/
  writing through the already-native `AgentStore`) ported to C++. The
  largest remaining native-porting item. **Investigated, v1.34.290,
  deliberately not attempted in full**: `population.py`'s tick methods
  number in the dozens (needs/movement/reproduction/repair/
  occupations/construction/vehicles/dormancy/skills/inheritance/
  psychology, each with its own real conditionals and RNG draws),
  several already read/write through the native `AgentStore`
  piecemeal — a genuine full port needs the SAME per-function
  randomized-equivalence + full-`World.to_dict()` hash-soak discipline
  every other native module in `cpp/src/` already carries, one
  function at a time, never big-bang, per this project's own standing
  R6/R7 porting discipline. Ollama/LLM latency (tens of seconds per
  call) still dominates the real tick budget (sub-millisecond) by
  several orders of magnitude, so there is no live-measured need
  driving a wholesale port.
  **First real slice shipped, v1.34.291** (explicit user instruction:
  "continue R8"), proving the pattern rather than attempting the whole
  item: `Population.decay_memory_salience`'s per-memory decay step —
  new `cpp/src/memory_salience_decay.cpp`'s `memory_salience_decay_
  step` (a pure scalar rate-select/multiply/floor function, same
  per-scalar-call shape module 12's `bounded_random_walk_step`/
  module 20's `relationship_decay_step` already established) crosses
  the pybind11 boundary once per `(agent, memory-index)` pair — chosen
  because `Agent.memory_salience`/`memory_causes` are plain per-
  instance Python lists (index-aligned with `memories`), NOT part of
  the native `AgentStore`'s fixed scalar fields, so this is a genuine
  new native surface, not a re-registration of already-native state.
  Called once per real sim-day (`day_end`), bounded by `population *
  MAX_AGENT_MEMORIES` — real, if lighter-cadence, work. `None` when
  the extension isn't built reproduces the exact prior inline-Python
  branching. Verified: a 200,000-trial randomized-equivalence test
  against a direct Python reference (0 mismatches, including near-
  threshold edge cases); a real production-path proof driving 1,500
  ticks through `SimulationEngine._tick_once()` confirming the native
  path is genuinely reached with real accumulated agent memories;
  `scripts/verify_native_soak.py` (3 seeds x 3000 ticks, new
  `_native_memory_salience_decay_step` toggle added to its
  `_NATIVE_TOGGLES` list) — MATCH, byte-identical full `World.
  to_dict()` state every tick, native vs. Python fallback; `pyflakes`
  clean on both touched files (only the six known pre-existing
  forward-ref findings elsewhere). One real function of the dozens R8
  ultimately needs — resume with the next one only on future explicit
  direction naming it, same "never big-bang" discipline as every prior
  slice.
- ~~Re-audit `world/weather.py`'s 3x3 `WEATHER_REGION_GRID` spatial-
  region handling for a real unported per-tile hot loop~~ **CLOSED,
  v1.34.290 — re-confirmed already resolved, no code change needed.**
  Two things corrected in the item's own framing during this re-audit:
  (1) `WEATHER_REGION_GRID` never lived in `world/weather.py` — the
  real constant (`= 3`) is `world/state.py`'s own, that file's own
  docstring stating outright it's "Deliberately NOT a per-tile field
  (that's a genuinely larger R7/C++-first undertaking...) — this is
  the smallest real step"; (2) direct re-reading of every real
  consumer found no unported per-tile loop anywhere in this path.
  `World.weather_at(pos)` is an O(1) region lookup (`world/state.py`);
  `World.tick()`'s own region-weather computation is a FIXED 3×3=9-
  iteration double loop (`for rx in range(WEATHER_REGION_GRID): for ry
  in range(WEATHER_REGION_GRID):`), each iteration calling the already
  native-backed `compute_weather()` (`world/weather.py`'s own
  `_native_compute_weather_blend` import, module 11, `cpp/src/
  weather.cpp`) — 9 calls/tick into already-ported code, not a
  per-tile scan. `world/fields.py`'s `FieldGrid` (Tier 1's A1, ~18
  region-scalar fields — moisture/scarcity/traffic/heat/hazard/
  storminess/etc.) reuses the identical `FIELD_GRID_SIZE == WEATHER_
  REGION_GRID == 3` grid by explicit, extensively-documented design
  ("Deliberately coarse to start... reuses `WEATHER_REGION_GRID`
  rather than a new per-tile resolution") — every one of its own
  `step_*` methods is the same bounded 3×3 pass, several already using
  `ca_operators.diffuse` (itself already native-backed where it
  matters, module 2). No genuine per-tile hot loop was ever hiding
  here; the roadmap item's own wording (both the stale file location
  and "never directly re-confirmed either way") is what was actually
  stale, now corrected.

## Phase 8 — Residual polish on already-shipped mechanisms

Small, independent, no-dependency-order-required items, each real but
minor relative to Phases 1-7.

- **Flagged, not decided: `Population.carrying_capacity` as a possible
  learned regression target.** Found by the same background audit that
  scoped L2.2's siblings above. `settlement/buildings.py`'s carrying-
  capacity formula is a 10-term hand-set weighted sum (economy/
  security/labor/environment/coordination/knowledge/infrastructure/
  hunger, plus saturation/comfort constants) gating reproduction/
  migration — the same "hand-tuned constant standing in for a
  judgment, with a real label already in the world's own history (did
  the settlement actually starve/overflow/collapse near the predicted
  capacity)" shape L2.1's value/consequence model already targets.
  Genuinely ambiguous whether this crosses `CONSTITUTION.md`'s Body/
  Mind line (carrying capacity is today part of the deterministic
  Body, which the Constitution says must stay strictly deterministic)
  or is Mind-adjacent enough to be a legitimate L2.1-style target —
  flagged rather than decided; needs an explicit product call before
  either building or dismissing it.
- **A1** — 11 of `FieldGrid`'s 12 named fields still unbuilt (only
  `population_density` is real): moisture, fertility, nutrients,
  disease-pressure, pollution, scent, traffic, heat, cultural-influence,
  ownership, beauty, noise. `mining_scars`/`disaster_scars`/the 3x3
  climate grid were never migrated onto the `FieldGrid` abstraction.
- **A2** — `cellular_step`'s fuller fire-spread mechanics (today only
  ignition-SITE is weighted; whether/how-often/how fire actually spreads
  stays the native-backed mechanism, deliberately not forced onto).
- **A3** — whether settlement/culture generation should ever move off
  LLM-authored and onto deterministic procgen stays a real open design
  question, not a closed one.
- **A4** — migrate `RoadNetwork.wear`/gossip contagion onto `FieldGrid`
  proper (currently correct, independent per-tick local rules) — a real
  but purely structural follow-up.
- **A5/A6** — per-instance `Entity.affordances`/`Entity.properties`
  (currently class-level only); the validate-step half (deterministic
  re-verification of a proposed concept's claimed mechanism) was never
  attempted.
- **A7** — the full graph/shape grammar (layout AND architecture, beyond
  the "zero lineage awareness" gap already closed), plus rules becoming
  LLM-proposable. Both explicitly unattempted.
- **A8** — grammar-based mutation as an alternate generate path (needs
  A7's shape-grammar work landing first).
- **A9** — give `World.location_character()`'s bare wrapper a real
  consumer (a future dialogue/cognition/NPC-inspector location-flavor
  read) — zero callers today.
- **A10** — ecology-on-fields is only nutrient cycling; migration,
  competition, decomposition, pollination, and habitat formation all
  stay unbuilt, as does folding the whole food web onto A1's substrate
  as one coupled system.
- **A11** — hydrology's two biggest remaining pieces: groundwater and
  real erosion into mutable elevation.
- **A12** — per-instance material generalization beyond `Building`/
  `Vehicle` — audited, no real consumer motivates it yet.
- **A13** — the automatic-firing reactor half (a rule genuinely
  mutating world state on its own tick) — only the query half shipped.
- **A14** — stress/reproduction/development/injury-recovery/sleep as
  coupled continuous subsystems (only `immune_strength` shipped); a
  genetic contribution to baseline immune_strength is a flagged future
  connection to A15.
- **A15** — wildlife/animal genetics (species adapting across
  generations, domestication) — entirely unscoped; humans-only shipped.
- **A16** — trade-as-network-flow and tech-as-DAG graph algorithms;
  only centrality shipped.
- **A17** — folding rumor/tradition/belief/song/technique onto
  `memetics.py`'s weighting, a shared mutate/decay/compete step, and a
  real fitness-vs-truth axis for rumors — only ontology-concept spread
  uses the mechanism today.
- **A18** — a real authoring system letting a village propose its own
  composable-reaction combinations (today hand-authored only), and
  consequences beyond relationship-rupture.
- **A19** — 6 of 9 named spatial-memory history axes still separate/
  unbuilt: traffic, pollution, fertility, ownership, construction,
  ecology.
- **A20** — a genuinely new second `FieldGrid` field, and "culture
  aggregates settlements' information-ecosystems," both still open.
- **A21** — folklore/legend pipeline unification remains the one
  genuinely open piece ("aspirational, not attempted").
- **A22** — keep adding Emergence API producers as new deterministic
  subsystems ship; open-ended by design, not a single closable task.
- **Part B pillars (B1/B2/B3/B7)** — each has a real first wired job, but
  the FULL "refactor ~55 scattered LLM jobs into acts of five pillars,"
  full observe→interpret→remember→plan→act→reflect cycling everywhere,
  and real (non-round-robin) arbitration all stay open — the same
  underlying refactor Tier 0 named, now ongoing/opportunistic rather than
  blocking (see Phase 9).
- **B5** — Innovation-as-scientist's evolve/merge paths stay untouched
  by the hypothesize→observe→revise loop propose already has; a real
  affordance/reaction query (waiting on Stage IV substrate) is open.
- **B6** — Reflection-as-meta-scientist never tracks whether *advisory*-
  path advice (as opposed to governor-nudge advice) actually worked.
- **B8** — living memory's `reinforce`/`reinterpret` (per-note salience/
  access tracking) was never attempted; only `consolidate` shipped.
- **R1** (docs/REFACTOR-2026-07.md) — split `population.py`
  (~3,930 lines) into a mixin-based package (`_pathfinding.py`/
  `_needs.py`/`_social.py`/`_settlement_ops.py`/`core.py`); a fully
  scoped, never-executed maintainability refactor, the single largest
  named piece of structural debt in the codebase.
- **R3** (docs/REFACTOR-2026-07.md) — finish the `clamp()` migration:
  25+ remaining `max(lo, min(hi, x))` sites across `population.py`,
  `agents/agent.py`, `llm/beliefs.py`, etc. Low-value, low-risk,
  mechanical.

## Phase 9 — Standing discipline (perpetual, never "finished")

Not a queue item — re-apply on every relevant future change, forever.

- **A23** — composability-over-content, enforced at review time on every
  new subsystem.
- **A24** — physical-consistency validation stays inviolable as Part B/C
  gain power; re-confirm on every new intention-writing capability.
- **A25** — periodically re-audit LLM call sites: has anything that
  needed genuine judgment become mechanically deterministic?
- **C4** (docs/MASTERCHECKLIST-2026-07-22.md) — "the acceptance gate as
  law": enforce as a standing review rule *and* as a real runtime
  auditor that retires unread/unused invented state — no such auditor
  exists yet. Same standing-discipline shape as A23-A25.
- **Per-agent cognition's volume-safe mirroring design** — the design
  question (what the volume gate should be, beyond the one narrow
  instance already shipped for core-cast goal changes) stays open;
  three candidate designs never chosen between.
- **Tier 0's mirror-write → pillar-authored conversion** — closed as a
  blocking item, reclassified to ongoing opportunistic maintenance: keep
  converting a site whenever a genuine one is found.
- **Tier 0.5 live-diagnostic re-measurement** — `D1`-`D4`/`D9`, and
  `D10`'s consolidation-coherence half, were all closed by code-level
  audit only (no live LLM server in this environment); re-measure against
  real inference traffic once one's available. Also re-measure every
  weather/disaster threshold constant over a FULL real year before
  further tuning (a past audit only sampled ~90 days and drew two wrong
  conclusions from it).

---

**Once Phases 1-8 close, this is the shipped game** — Phase 9 continues
by design, the same way code review and threshold re-tuning never
"finish" for a live, always-running world.

---

## Shipped so far (consolidated)

Every item not listed above is done. Hearthmind ships: a deterministic
physical Body (terrain/weather/hydrology/ecology/disasters/roads/
farming/construction, largely C++-native) paired with an LLM-authored
Mind across four co-equal pillars (Humans/Village/Nature/Innovation) plus
a fifth, Reflection, observing all four; persistent per-agent/settlement/
institution memory, belief, and culture; the full Tier 7 Cognitive
Architecture (specialists that bid, a real arbitrated global workspace,
impasse-gated deliberation with chunk caching, ACT-R memory activation,
and a Cognitive Observatory UI showing all of it — Stages A-H all
closed in full);
an Adaptive Runtime (task graph, scheduler, dormancy, hardware-adaptive
tuning, a real escalation ladder) largely wired to production; and a
from-genesis-to-digital-era historical ladder with LLM-steered branching.
Full narrative detail — every version's rationale, root cause, and
verification data — lives in `CHANGELOG.md` (chronological) and
`CLAUDE.md`'s "Current state" log (topical, most-recent-first). This
document no longer duplicates that record; consult those two files for
"why," this one for "what's left."
