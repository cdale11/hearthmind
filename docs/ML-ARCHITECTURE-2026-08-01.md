# Hearthmind — Final AI/ML Architecture

**Filed v1.34.170.** Supersedes the staged M0-M9 plan in
`docs/ML-AUDIT-2026-08-01.md` (which remains the **baseline audit** —
the evidence table, the LLM-task classification, and the correction to
v1.34.168 all still stand). This document is the architecture pass over
that plan: every proposed model challenged, four merged or removed, two
promoted, and the extensions the instruction named folded in
(distillation, outcome/reward learning, planning policy, social
learning, calibration).

**Net result: 9 loose stages → 4 layers / 8 justified models, with three
shared components that most of them reuse.**

---

## 0. What changed from the audit's plan, and why

| Audit item | Verdict | Reason |
|---|---|---|
| M1 "runtime cost model" (task half) | **REMOVED as ML** | `TaskMetrics.mean_wall_seconds()` already computes it (v1.34.167). Feeding that number to `cost_hint` is plumbing, not learning. Calling it a "model" would be theater. |
| M1 (LLM latency half) | **KEPT** → L3.1 | Genuinely predictive: estimate cost *before* paying it. |
| M3 embeddings + M4 retrieval weights | **MERGED** → L2.3 | They are one scorer. Learning combination weights over a frozen bad relevance term, or a good embedding under hand-set weights, each leaves half the win on the table. Train them together. |
| M3 (as a shared representation) | **PROMOTED** → L1 | 6+ consumers. The strongest reuse case in the plan; it belongs in the substrate layer, not stage 3. |
| M6 attention + M5's reward signal | **PARTIALLY MERGED** → shared L2.1 value head | Both need "how consequential is this state?" One model, two consumers. The *allocation* and *policy* heads stay separate — different problems. |
| M7 belief confidence | **DEMOTED** → L4.1 | This is calibration (isotonic/Platt), a solved statistical problem. An ANN here is unnecessary generalization. |
| M8 social GNN | **DOWNGRADED** → L1.5 feature extractor | `graph_algorithms.py` already ships `build_relationship_graph`, `degree_centrality`, `bfs_distances`. The value is structural *features* feeding existing models, not end-to-end graph learning. Full GNN stays optional-later. |
| Planning (raised in the instruction) | **MERGED** → L2.2 input | `Agent.plan` maps to the same closed `AgentGoal` set the policy already outputs. A separate planning model would be pure fragmentation. |
| M9 evolutionary search | **KEPT, unchanged** | Already specced as B13.5, already gated behind B13.2. |

---

## 1. The architecture

```
LAYER 0 — SUBSTRATE (no behaviour, reused by everything)
  L0.1  Feature encoder      agent/settlement/world state -> fixed vector
  L0.2  Model primitives     linear · logistic · small MLP · calibration
                             + versioned weights blob + C++ forward pass
  L0.3  Training harness      reads recorder / metrics / emergence log

LAYER 1 — SHARED REPRESENTATION (the reuse win)
  L1.1  Semantic embedding    the sim's own vocabulary        [6+ consumers]
  L1.2  Social structure      1-layer message passing over the ledger graph

LAYER 2 — COGNITION (the emergence layer)
  L2.1  Value / consequence   "how much does this state matter?"  [2 consumers]
  L2.2  Goal policy           distill from LLM -> refine on outcomes
  L2.3  Semantic retrieval    learned scorer over L1.1 + recency + salience

LAYER 3 — RUNTIME (zero emergence risk, B0-owned)
  L3.1  LLM cost regressor    predict latency before issuing a call
  L3.2  Demand forecaster     time series over the metrics table

LAYER 4 — CALIBRATION
  L4.1  Belief confidence     isotonic/Platt, not a network

LAYER 5 — LIFELONG LEARNING LOOP (closes the loop over simulated time)
  L5.1  Continual retrain scheduler   simulated-time cadence, never blocks the tick loop
  L5.2  Warm-start + replay rehearsal  fine-tune existing weights, never reinit from scratch
  L5.3  Shadow evaluation + swap gate  candidate must not regress before it goes live
  L5.4  Versioned checkpoint history   bounded per-world log, rollback on a bad swap
```

**Layer 5 exists to fix a real gap in the audit/architecture as
originally filed (added v1.34.172, explicit user correction): "weights
are per-world state" only made two worlds diverge AT TRAINING TIME —
nothing closed the loop so a model kept learning across the years of
simulated play that follow.** Without L5, L2.2's own two-phase
curriculum (distill, then reweight by outcome) is a one-shot event,
not something that keeps happening as a world accumulates more lived
history — which contradicts the instruction's own framing ("closes the
loop so worlds continue to diverge over years of simulated time and
automated learning"). L5 is the mechanism that makes divergence
compound over a world's lifetime instead of only at generation.

### L0 — Substrate

One feature encoder, one set of primitives, one training harness. The
encoder is the thing that prevents fragmentation: every model below
consumes the *same* agent/world vector, so adding a model is adding a
head, not a pipeline.

Primitives are deliberately small: logistic regression, a 2-3 layer MLP,
and a calibrator. **No deep-learning framework (no torch).** numpy is
permitted for offline training (v1.34.171 — explicit user directive
relaxed the earlier stdlib-only constraint; confirmed installable in
this environment via `pip install numpy`, gated behind the new `ml`
optional extra in `pyproject.toml`). Training runs offline (`ml`
extra); inference is a handful of dot products in `cpp/src/` with a
pure-Python, stdlib-only fallback every native module already has —
numpy is never a runtime/inference dependency, only a training-time
convenience. Weights ship as a versioned blob.

**Weights are world state.** They live in the snapshot, they are
per-world, and they are what makes two worlds with different histories
diverge behaviourally. This is also what keeps `verify_replay_hash.py`
meaningful: same seed + same weights = same result.

### L1.1 — Semantic embedding ⭐ *the strongest reuse case*

A small skip-gram embedding (32-64 dims) trained on the world's own
accumulated event/memory/belief/dialogue corpus.

**Consumers:** memory retrieval (L2.3), belief dedup, folklore dedup,
dialogue dedup, `cognition/pillar.py:60`'s `word_overlap`, topic
novelty, plan encoding for L2.2, belief-subject matching.

**Why it must be shared, not per-consumer:** these are all the *same
question* — "do these two pieces of text mean the same thing in this
world?" Today each site answers it with token overlap. Eight private
embeddings would be textbook fragmentation; one shared representation is
the justified generalization.

**Emergence value:** the highest per-unit-work gain in the whole plan.
`relevance = min(1.0, overlap / 2.0)` cannot see that *"the wolves took
Bram"* and *"a predator killed my brother"* are the same memory. An NPC
recalling the thematically right memory instead of the lexically
overlapping one is the difference between a search index and a mind.

### L1.2 — Social structure features *(not a GNN)*

One round of message passing over `agents/ledger.py`'s pair graph,
producing per-agent structural features: neighbourhood sentiment,
weighted centrality, community affiliation, bridge-ness.

**Challenged and downgraded deliberately.** A full GNN was proposed in
the audit; it is not justified *yet*. `world/graph_algorithms.py`
already computes `build_relationship_graph`, `degree_centrality`, and
`bfs_distances`. The genuine gap is that nothing *feeds those to the
decision models*. Closing that gap is cheap, interpretable, and
reuses shipped code. End-to-end graph learning is a large complexity
jump with a diffuse training signal — revisit only if L1.2's features
prove load-bearing and insufficient.

**Consumers:** L2.1 (a socially central agent's state matters more),
L2.2 (who you're embedded among shapes what you do), dispute/faction
detection.

### L2.1 — Value / consequence model *(the merge that justifies itself)*

Predicts: *how consequential is this agent's current state?* Trained on
a real, already-recorded label — `world/emergence.py`'s `magnitude`
field (0-1, clamped at `make_observation`) plus downstream `life_events`
within a horizon.

**Two consumers, one model:**
- **Attention allocation** (audit M6): spend the scarce cognition call
  on the agent whose state is most consequential. This directly unblocks
  **B2.4 "attention follows change,"** which has been blocked on exactly
  this and nothing else.
- **Policy advantage weighting** (L2.2 phase 2): weight a training
  example by how much the decision actually mattered.

Merging these is justified because it is *literally the same estimate*
asked by two callers. What stays separate is the *ranking* logic
(allocation) from the *action* logic (policy) — different problems,
different outputs.

### L2.2 — Goal policy ⭐ *the flagship, and the biggest design change*

Outputs a distribution over the closed 7-value `AgentGoal` set
(`agents/agent.py:36-48`). The LLM keeps authoring `reason` — the free
text half of `{goal, reason}` is language and stays language.

**Two-phase training curriculum. This is the extension the instruction
asked for, and it is strictly better than either phase alone:**

**Phase 1 — teacher→student distillation.** The recorder has been
storing `(layer1_structured_input → layer4_parsed_output)` for every
cognition call since v0.87.28. That is a distillation set already on
disk. Training on it bootstraps a policy that reproduces the LLM's
judgment across the whole state space — no cold-start random behaviour,
no hand-written ladder.

**Phase 2 — outcome-weighted refinement.** Pure imitation caps the
student at the teacher and inherits its mistakes. Reweighting examples
by realized outcome (did hunger actually fall, did the agent survive,
did a consequential event follow — via L2.1) lets the student **diverge
from and exceed the LLM** where the world says the teacher was wrong.

**This is where per-world emergence actually comes from.** Two worlds
with different histories reward different policies, so their agents
genuinely think differently — not because of a seed, but because of what
happened to them. A fixed if-ladder can never do this. Neither can pure
imitation.

**Replaces:** `cognition.fallback_goal`'s hand-written if-ladder, which
today handles the *majority* of all goal decisions because only the core
cast ever reaches the LLM. The whole population gets learned,
world-specific judgment. **More agents thinking, not fewer** — and the
freed LLM budget goes to language and the KEEP-LLM jobs.

**Absorbs planning:** `Agent.plan` enters as an L1.1-embedded input
feature rather than being keyword-matched. Plans steer behaviour instead
of pattern-matching on words. No separate planning model.

**Homogenization is the real risk here, and it is designed against.**
One shared policy would make every agent think alike — precisely the
failure mode v0.88.0 fixed for traits. Mitigations, all mandatory:
- the policy is **conditioned on the agent's own persistent state**
  (traits, emotions, relationships, beliefs, L1.2 social features), so
  one network produces different behaviour per personality;
- sampling keeps an **entropy floor** — never argmax;
- **survival overrides stay deterministic and untouched** (critical
  hunger/energy force their goal before the policy is consulted, exactly
  as today).

### L2.3 — Semantic retrieval scorer

Replaces `retrieve_relevant_memories`'s hand-set weights
(`agents/agent.py:472-474`) **and** its bag-of-words relevance term with
one learned scorer over L1.1 embeddings + recency + salience + causal
link. Label: did the retrieved memory demonstrably influence the
resulting output? Both sides are in the recorder.

Same k-slot prompt budget as today — bounded prompt size is preserved.

### L3.1 / L3.2 — Runtime models

**Zero emergence risk by construction:** B0's prime invariant already
guarantees the runtime never makes world-meaning decisions. The worst
failure is a mis-scheduled task, caught by `verify_replay_hash.py`.

- **L3.1 LLM cost regressor** — `structured_input` + generation config →
  `latency_ms` (both already recorded). Lets the scheduler decline a
  call it cannot afford *before* paying for it, attacking the
  `calls_dropped_backpressure` problem visible in CLAUDE.md's own live
  reports at its root rather than after the fact.
- **L3.2 Demand forecaster** — autoregression over the `metrics` table
  (`persistence/database.py:98`) predicting near-term LLM demand.
  Feeds B8.2's reservation mechanism.

These stay two models, not one: per-call cost regression and aggregate
time-series forecasting are different model classes on different
features. Merging them would be generalization for its own sake.

### L4.1 — Belief confidence calibration *(not a network)*

Maps asserted confidence → empirically calibrated confidence using
isotonic regression or Platt scaling, against whether beliefs of that
stated confidence actually held up. **Deliberately not an ANN** — this
is a solved 1-D statistical problem, and reaching for a network here
would be exactly the unnecessary generalization this pass is meant to
remove.

---

### L5 — The lifelong learning loop *(closes the loop, added v1.34.172)*

Every layer above describes a model. This layer describes how those
models keep learning **after** they're first trained — the piece that
was missing. Without it, "weights are per-world state" is true only at
the moment a model is trained; L5 is what keeps it true continuously,
for as long as a world keeps running.

**L5.1 — Continual retrain scheduler.** Each learned model (starting
with L2.2, the flagship) gets a real retrain cadence keyed to
*simulated* time — a season or year boundary, matching every other
calendar-gated LLM job in this codebase (`SEASON_YEAR_JOBS_WITH_
RETRY`), never real wall-clock time. Retraining is asynchronous and
fire-and-forget, the exact same liveness contract every `_schedule_
llm_job` call already honours (`docs/CONSTITUTION.md` §3/§7) — a
retrain in progress must never block or slow the tick loop. Once B1/B2
(the task graph + scheduler, Tier 5) are actually wired into
`simulation/engine.py`, this is a natural `DEFERRABLE`- or
`BACKGROUND`-class task; until then it can reuse the same `_schedule_
llm_job`-style async-task pattern directly.

**L5.2 — Warm-start + replay rehearsal.** A retrain fine-tunes the
model's EXISTING weights (`hearthmind/ml/training.py`'s
`continual_train_mlp`) on new examples the recorder/metrics/emergence
log have accumulated since the last retrain, mixed with a rehearsal
sample from a `hearthmind.ml.lifelong.ReplayBuffer` — a bounded
reservoir sample spanning the model's WHOLE training history, not a
sliding window. This is the concrete mechanism against catastrophic
forgetting: without rehearsal, a model that spends a season mostly
seeing one kind of situation (a famine year, a long peace) measurably
overwrites what it learned in a different kind of season before it —
verified directly in `scripts/verify_ml_substrate.py` (a model
continually retrained on a new objective loses >50% of its old-task
accuracy without replay, and recovers to within a fraction of that
loss when replay is enabled). Never reinitializes from scratch — that
would throw away everything the model already learned about this
specific world, defeating the entire point of per-world weights.

**L5.3 — Shadow evaluation + swap gate.** A candidate retrain is
scored against held-out recent examples (and, for anything that
touches Body-adjacent decisions, ideally the sandboxed counterfactual
fork `simulation/sandbox.py` already provides) BEFORE its weights ever
replace the live ones. `hearthmind.ml.lifelong.passes_shadow_gate`
implements the check: a candidate that doesn't beat (or at least not
regress past a small explicit tolerance) the current live model's
metric is rejected — same "a change that regresses is rejected without
a judgment call" discipline B15's replay-hash gate already established
for determinism, applied here to model quality instead.

**L5.4 — Versioned checkpoint history.** `CheckpointHistory` keeps a
bounded, per-world log of past weight blobs with the metric each
scored at save time — if a regression somehow gets through the shadow
gate (or the gate itself needs to be loosened later and something
regresses as a result), `rollback()` recovers the previous good
checkpoint rather than the world being stuck with a worse model
indefinitely.

**What this does NOT yet do (explicitly flagged, real future work,
not attempted this pass):** L5.1-L5.4 are real, verified, standalone
primitives (`hearthmind/ml/lifelong.py`, `scripts/verify_ml_
substrate.py`) — they are not yet wired into any real scheduling
cadence or `simulation/engine.py` call site. That wiring needs (a) a
real decision for each model of what "new examples since last retrain"
actually means concretely (a recorder query? a metrics-table window?),
and (b) the B1/B2 scheduler actually migrated into the live tick loop
first, per B0.3's own "one subsystem at a time, never big-bang"
migration discipline. Building L5.1's real trigger is naturally
sequenced alongside L2.2's own phase-2 (outcome-reweighted) training,
since that's the first model whose continual-learning story actually
matters for emergence.

---

## 2. Implementation order

Ordered by (value × certainty) ÷ risk. Each stage independently
shippable and revertible.

| # | Stage | Risk | Gate |
|---|---|---|---|
| 1 | **L0** substrate — **SHIPPED v1.34.171** | none (inert) | `scripts/verify_ml_substrate.py`, 17 checks incl. numpy-vs-pure-Python forward-pass equivalence |
| 2 | **L3.1 + L3.2** runtime | none (B0 layer) | replay-hash unchanged |
| 3 | **L1.1** embedding | low (offline artifact) | held-out similarity eval |
| 4 | **L2.3** retrieval | medium | A/B vs. current retrieval, config flag |
| 5 | **L1.2** social features | low (features only) | no behaviour change until consumed |
| 6 | **L2.1** value model | medium | outcome-prediction accuracy on held-out |
| 7 | **L2.2** policy — phase 1 distill | **high** | replay-hash, staged rollout, flag |
| 8 | **L2.2** policy — phase 2 outcomes | **high** | population-outcome metrics vs. baseline |
| 9 | **L4.1** calibration | low | calibration curve on held-out beliefs |
| 10 | **L5.1-L5.4** lifelong loop primitives — **SHIPPED v1.34.172** | none (inert, unwired) | `scripts/verify_ml_substrate.py` — reservoir-sampling fairness, checkpoint bounds/rollback, shadow-gate direction, and the load-bearing check: a model continually retrained with replay rehearsal keeps old-task performance far closer to baseline than one retrained without it |
| 11 | **L5.1** wired to a real retrain cadence, starting with L2.2 | **high** | same gates as step 8, plus the shadow gate (L5.3) on every swap |
| 12 | **B13.5** evolutionary search | low | B13.2 replay-hash gate (already specced) |

Steps 1-3 are pure infrastructure and carry no behavioural risk; the
first real behaviour change is step 4. Step 10 (the lifelong-loop
*primitives*) is likewise pure infrastructure — step 11, wiring L5.1 to
an actual retrain cadence, is where the real risk and the real payoff
both live, and is correctly sequenced after L2.2 exists to retrain.

---

## 3. Standing guardrails

1. **LLMs keep language, creativity, abstraction, reflection and
   ontology expansion.** Dialogue, chronicle/folklore/legend, naming,
   world genesis, musing, dreams, omens, religion, and the entire
   ontology-expansion family (`ontology`, `invention`, `rule_propose`,
   `composite_reaction_propose`, `species_variant`, `nature_mind`,
   `nature_causal_reasoning`) are **out of scope permanently**. A
   classifier can only choose among classes it was trained on — the
   exact opposite of what `world/ontology.py` exists to do.
2. **Deterministic ownership of objective world state is absolute.** No
   learned model writes physics, terrain, weather, decay, resources or
   population arithmetic (`docs/CONSTITUTION.md`). Models inform
   *cognition* and *scheduling* only.
3. **Weights are per-world state**, snapshotted, and diverge between
   worlds — **continuously, not just at training time** (L5, added
   v1.34.172). A world's models keep learning from its own accumulated
   history for as long as it runs; two worlds with different histories
   should keep drifting apart the longer both play, not just differ
   once at generation.
4. **Every model ships with a deterministic fallback.** A missing or
   corrupt weights blob degrades to today's behaviour, never to a crash
   — the same contract all 24 native modules already honour.
5. **Replay-hash gate** on every behaviour-touching stage. B15's rule
   holds: a win that changes outcomes is rejected without a judgment
   call.
6. **Never train a model on its own unweighted outputs.** Phase-1
   training uses LLM-authored decisions (teacher) only; phase 2 admits
   the student's own decisions *only* weighted by realized world
   outcomes. This is the guard against self-reinforcing collapse.
7. **External libraries permitted for offline training only** (revised
   v1.34.171). numpy is allowed behind the new `ml` optional extra;
   the shipped runtime inference path is always stdlib + the existing
   `cpp/src/` path, so the `ml` extra is never required to run the
   simulation, only to retrain.
8. **Anti-homogenization is a hard requirement, not a nicety** — every
   per-agent model is personality-conditioned and samples with an
   entropy floor.
9. **Continual retraining warm-starts and rehearses, never resets**
   (L5, added v1.34.172). A retrain fine-tunes a model's existing
   weights on new examples mixed with a replay-sampled slice of its
   whole training history; it never reinitializes from scratch, which
   would discard everything the model already learned about this
   specific world. A candidate retrain must clear the shadow-evaluation
   gate (L5.3) before it replaces the live weights — the retraining
   loop gets the exact same "no judgment call, no silent regression"
   discipline guardrail #5 gives every other behaviour-touching change.

## 4. Explicitly rejected

- **A full social GNN** (for now) — `graph_algorithms.py` already
  computes the structural signal; end-to-end graph learning is a large
  complexity jump with a diffuse label. Revisit only if L1.2 proves
  load-bearing and insufficient.
- **A learned task-cost model** — `TaskMetrics` already measures it.
- **A neural belief-confidence model** — calibration is the right tool.
- **A separate planning model** — folds into L2.2 as an input.
- **Per-agent policy networks** — homogenization is solved by
  conditioning, not by 300 networks.
- **LoRA fine-tuning the local LLM** — unchanged from v1.34.159, still
  correctly out of scope and still data-gated by
  `eval_harness.training_readiness_report`.
