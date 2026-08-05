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
  (substrate), not yet wired.** `hearthmind/ml/embedding.py`: a
  pure-Python skip-gram-with-negative-sampling word embedding, trained
  on a caller-supplied text corpus (corpus-agnostic by design, same
  "decouple from World internals" discipline `cross_run.py` already
  established). `SkipGramEmbedding.text_similarity(a, b)` is the real
  "do these two pieces of text mean the same thing" function —
  verified against the architecture doc's own worked example ("the
  wolves took Bram" scores measurably closer to "a predator killed my
  brother" than to an unrelated harvest sentence, `scripts/verify_ml_
  l1_embedding.py`, 19 checks). Real waiting consumers (memory
  retrieval's hand-tuned weights, four text-dedup sites, `Pillar.
  word_overlap`, topic-novelty checks) are NOT wired yet — needs a real
  corpus-building pass from `World`/`Agent` text plus a live-consumer
  migration, same "ship the substrate, wire it once a real consumer
  exists" discipline every other L-layer piece has shipped under.
  Unblocks L2.3/HCA `F1` at the substrate level; both still need their
  own real wiring pass.
- **L2.2 — Goal policy** (the flagship, the largest single remaining Tier
  6 item) — **SHIPPED (substrate), not yet wired.** `hearthmind/ml/
  goal_policy.py`: a closed-7-class softmax `AgentGoal` classifier,
  meant to replace `llm/cognition.py`'s `fallback_goal` if-ladder (the
  path that handles the majority of real goal decisions, since only
  the core cast reaches a live LLM call). Real two-phase curriculum —
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
  learn`, all backward-compatible, default stays `"mse"`). NOT wired
  into `cognition.py`/`Population` — needs a real recorder archive
  (`layer1_structured_input -> layer4_parsed_output`) this offline
  environment has no live run to source, same discipline every other
  Tier 6 substrate item shipped under. `Agent.plan` absorption (a real
  L1.1 `text_vector` concatenated into the feature schema) is
  deliberately NOT done yet — `FeatureSchema` only encodes flat
  numeric/categorical slots today; a small schema extension is needed
  first, flagged as real follow-up.
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
- **Five more `fallback_goal`-shaped LLM/deterministic sites, found by a
  background audit while scoping L2.2, none yet promoted to an L-layer
  slot:** `llm/dispute.py`'s `fallback_dispute` (4-class: reconcile/
  council_ruling/feud/ostracism), `llm/fission.py` and `llm/migration.
  py` (binary leave-or-stay), `llm/laws.py` (which hardship becomes a
  law, among real candidates), `llm/founding.py` (found/don't). Each is
  structurally identical to what L2.2 already targets — a bounded-
  choice decision made today by a hand-written if-ladder or an LLM
  call whenever the LLM path doesn't fire, with a real recorded-
  outcome history this world already accumulates. ML-AUDIT's own §2b
  SPLIT table already names all five alongside `cognition`; none was
  ever carried into ML-ARCHITECTURE-2026-08-01.md's 8-model plan.
  Building an `L2.2`-shaped policy for each (reusing `goal_policy.py`'s
  own pattern — closed-class schema, `build_distillation_examples`,
  `reweight_by_outcome`, `LearningSpecialist`) is real, scoped,
  unstarted follow-up work — resume only on future explicit direction
  naming one.

## Phase 2 — Wire the already-built ML substrate to real consumers

Every one of these shipped as a real, tested, standalone module with no
live production call site — the recurring gap across Tier 6.

- **L2.1** value/consequence model → a real `B2.4`/`L2.2` consumer (needs
  a real accumulated emergence-log/life-events archive from a live
  world).
- **L3.1/L3.2** (LLM cost regressor, workload forecaster) → real call
  sites; needs a real training archive. L3.2's own "true autoregression
  over the `metrics` table" stays a further, distinct open piece.
- **L4.1** belief-confidence calibration → a real consumer; needs a real
  settled-hypothesis history from a live world.
- **L5** the lifelong-learning loop → a real per-model retrain cadence
  (needs a real per-model decision of "what counts as new examples").
- **L6** evolutionary model-genome participation → a real evolutionary
  cadence / `simulation/engine.py` call site.
- **B13.5** evolutionary tunable-set search (`tunable_evolution.py`) →
  a real cadence (built and verified in isolation only).

## Phase 3 — Close the last Tier 7 (HCA) gaps

- **E3, competing-goals half.** The memory-activation half shipped; the
  competing-goals half needs a genuinely NEW per-agent `GlobalWorkspace`
  arbitrating candidate goals — `llm/cognition.py`'s `fallback_goal` is
  still a flat if-chain, not a scored competition. Real new mechanism,
  not a rendering pass.
- **H1, per-domain budgets.** Write-scope enforcement (WORLD/MACHINE/
  OBSERVER) is real; real per-domain budget contention needs a second
  real bidder in the MACHINE or OBSERVER domain, which doesn't exist yet.
- **A real chunk-expiry mechanism for C2's `ChunkStore`.** Currently
  keyed on subject text with no expiry — fine for texture-only musing,
  but it's what blocks safely sweeping `_maybe_schedule_rule_proposal`
  into Stage C's dispatch ladder (a stale cached "no rule" outcome could
  suppress a genuinely-overdue law for a worsening problem indefinitely).
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
and a Cognitive Observatory UI showing all of it — Stages A-D, G, H
closed in full, Stage E closed but for E3's competing-goals half above);
an Adaptive Runtime (task graph, scheduler, dormancy, hardware-adaptive
tuning, a real escalation ladder) largely wired to production; and a
from-genesis-to-digital-era historical ladder with LLM-steered branching.
Full narrative detail — every version's rationale, root cause, and
verification data — lives in `CHANGELOG.md` (chronological) and
`CLAUDE.md`'s "Current state" log (topical, most-recent-first). This
document no longer duplicates that record; consult those two files for
"why," this one for "what's left."
