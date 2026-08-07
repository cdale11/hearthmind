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

- **B3.3** — convert the remaining `ON_DIRTY`/`ON_EVENT` reactivity sites
  (only `institution_dormancy` converted so far, of ~200 candidates).
- **B9.3** — audit ~200 per-tick call sites for timescale mismatch
  against the real `TimescaleLadder`.
- **B4.2, the last two dormancy candidates** — "inactive settlements" and
  "distant wildlife" (of five originally named; three already shipped).
  Both touch real Body-deterministic per-tick simulation and need a
  genuinely lossless elapsed-tick reconstruction design before they can
  sleep safely, unlike their Mind-layer-only siblings.

## Phase 5 — Finish wiring the Adaptive Runtime's remaining pieces

- **B11** hierarchical memory tiering has no real large-persisted-state
  consumer wired to it yet.
- **B12** — only the RAW→archived-digest stage is wired (the emergence
  log). The remaining cascade (EPISODE→SUMMARY→HISTORY→CULTURAL_MEMORY)
  needs a real chronicle/documentary/culture-digest producer chain per
  stage.
- **B14.3** — `batch_size_for_storage` has no real batched-write
  mechanism to size for yet (the snapshot writer is still one `INSERT`
  per row); needs real new design, not a cheap wire-up.
- **B15.6/B15.7/B15.8** (docs/HEARTHBENCH-RUNTIME-2026-07-23.md) — record
  host fingerprint/cognition-budget/rung-5 history in the save file +
  diagnostics; fuzz the scheduler (randomize task order/budgets/
  dormancy, assert the replay-hash invariant still holds); a semantic-
  safety class check at tunable *registration* time, not just at
  hypothesis-apply time.

## Phase 6 — HearthBench (build the benchmark itself)

Only `A0` (confirmed reusable pieces) and `A1.1`/`A1.2` (package skeleton
+ import-isolation firewall) exist. Everything else, in dependency order:

`A2` model adapter layer → `A3` prompt library/test definitions → `A4`
scoring ("the judge problem," the doc's own central design fork) → `A5`
the 9 benchmark categories → `A6` structured-output validator → `A7`/`A8`/
`A9` metrics collector/diagnostics/reports → `A10` the HearthBench Score
→ `A11` run modes (unblocks **B15.5**'s `reference_mode`, currently
built but unused for lack of this) → `A1.3` process isolation (gated on
A2+A11) → `A12` web UI → `A13` CI prompt-regression guard (needs the
whole pipeline first).

## Phase 7 — Native performance (opportunistic, not gated on anything)

Not performance-justified today (Ollama/LLM latency dominates the tick
budget, not Python) — pick up only on explicit direction or a genuine
measured need, never a default next step.

- **R8** — agent tick *logic* (`population.py`'s methods, still reading/
  writing through the already-native `AgentStore`) ported to C++. The
  largest remaining native-porting item.
- Re-audit `world/weather.py`'s 3x3 `WEATHER_REGION_GRID` spatial-region
  handling for a real unported per-tile hot loop (the blend function
  itself is already ported; the region grid was never directly
  re-confirmed either way).

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
