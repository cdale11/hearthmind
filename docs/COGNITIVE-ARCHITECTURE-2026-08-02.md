# The Hearthmind Cognitive Architecture (HCA)

**Filed 2026-08-02, on explicit user direction.** Docs-only; no code
changed in the filing pass. This document is *authoritative* for how
minds are organised in Hearthmind — individual and collective alike —
and it amends several standing rules. Where it conflicts with an
earlier design note, this document wins; where it conflicts with
`CONSTITUTION.md`'s priority ordering, the Constitution wins.

---

## 0. The instruction, and what actually changes

The direction given:

> Hearthmind's primary goal is to explore whether human-like cognition
> can emerge from interacting computational systems. NPCs are a
> consequence of that goal, not the goal itself. […] functionally
> mimic how the brain is organized: many specialized systems operating
> mostly subconsciously, interacting continuously, with only a small
> amount of information reaching conscious reasoning. […] Treat the
> LLM as one cognitive subsystem rather than the entire mind if the
> evidence supports it.

This is a genuine reframing, not a relabelling, and it is worth being
precise about what it changes:

**It does not change** the four-pillar Body/Mind split, the
deterministic substrate, Phase G's ambiguity discipline, the
Observatory UI direction, or the priority ordering in
`CONSTITUTION.md`. Those stay exactly as they are. HCA describes how
the *inside of a Mind* is organised; it does not redraw the pillars.

**It does change** seven things, each justified in §3 (item 5 added
2026-08-02 via a direct user amendment, see §2.5a; items 6 and 7 added
the same date via a second amendment, see §2.10 and §3.2):

1. **How the LLM is invoked.** Today ~55 call sites each independently
   ask "is it my turn, and am I backpressured?" Under HCA nothing calls
   the LLM directly. Subsystems *bid* for a scarce serial channel, and
   deliberation fires on a named **impasse**, not on a calendar.
2. **What counts as worth noticing.** Today "something happened" is the
   trigger. Under HCA the trigger is **prediction error** — surprise
   relative to a cheap forward model. Predictable events are not news.
3. **Where a resolved thought goes.** Today a job's result is written
   back to whoever asked for it. Under HCA a resolved workspace item is
   **broadcast to every subsystem**. This is the change that creates
   genuinely new cross-system interaction.
4. **What the UI is for.** The map shows the world; a new **Cognitive
   Observatory** shows the mind. This is a deliberate amendment to the
   standing two-surface rule (§6).
5. **What a specialist is.** Today's forward model is a fixed formula
   (a hand-set EMA). Under HCA it is a **learned model that keeps
   improving**, revised from accumulated experience and capable of
   unlearning a pattern that stopped holding — "a society of learning
   cognitive processes rather than a collection of fixed modules."
6. **How attention is decided.** The first draft scored bids with a
   fixed weighted sum — a priority queue, which does not resemble
   attention. Under HCA attention **emerges from competition between
   coalitions**: bids merge, gains are learned from realised outcomes,
   uncertainty earns an explicit exploration bonus, and staleness grows
   without bound so nothing can starve — with no randomness anywhere
   (§2.10, §3.3).
7. **Who counts as a cognitive participant.** The Adaptive Runtime —
   and later the Player Model — become **first-class specialists in
   their own cognitive domains**, predicting, bidding, learning and
   broadcasting like any other, while remaining structurally incapable
   of writing deterministic world state. They reason about computation
   and about the observer; never about the world (§3.2).

And one further claim that makes the whole thing falsifiable: under
HCA, **LLM cost per unit of emergence should fall as a world matures**,
because resolved impasses are compiled into cheap reusable artifacts.
If that does not happen, this architecture is wrong (§8).

---

## 1. The evidence: what the 64,453-tick soak actually shows

This reframe is not motivated by theory alone. A real overnight run on
real hardware (pasted `/diagnostics`, 64,453 ticks, population 174,
`nemotron-4b-q5_k_m`, `llm_max_concurrent=1`) shows four specific
pathologies, each of which one of the principles below directly fixes.
Every number here is from that run.

### 1.1 The scarce channel is spent almost entirely on chatter

| Task | Calls | Share |
|---|---|---|
| `voice_dialogue` | 1,077 | 42% |
| `cognition` (per-agent goals) | 563 | 22% |
| `musing` | 441 | 17% |
| `record` | 154 | 6% |
| `mind` | 126 | 5% |
| **narration + per-agent flavour subtotal** | **~2,412** | **~93%** |
| `town_brain` | 11 | 0.4% |
| `institution_belief` | 11 | 0.4% |
| `culture_digest` | 5 | 0.2% |
| `beliefs` (settlement theory revision) | 4 | 0.15% |
| `narrative_direction` | 3 | 0.1% |
| `nature_mind` | 1 | 0.04% |
| `ontology_proposal` | 1 (failed) | 0.04% |
| `ontology_evolution` | 1 | 0.04% |

The settlement- and pillar-level cognition that this project describes
as its actual mind received roughly **37 calls in 64,453 ticks**, while
ambient narration received about 2,400. Nothing is wrong with any
individual gate; the aggregate is simply an unarbitrated race, and the
high-frequency jobs win it by construction.

### 1.2 The metacognitive layer never ran at all

```
"reflection_notebook_total": 0,
"reflection_notebook_by_status": {},
"pillar_cognition_status": {
  "reflection": { "stage": "Pattern analysis", "years_observed": 2,
                  "years_needed_for_first_hypothesis": 2,
                  "pattern_detector": "Eligible", "hypothesis": "Deferred" } }
```

Reflection was **eligible and deferred**. In a full 64k-tick run the
system whose entire job is to notice long-run patterns produced zero
hypotheses. Pillar cycle counters agree: `village_pillar.
turns_processed: 0`, `humans_pillar: 0`, `innovation_pillar: 0`,
`nature_pillar: 2`, `reflection_pillar: 2`.

A system that has *never once run* should have overwhelming priority.
Under a cadence-plus-backpressure scheme it has none, because staleness
is not an input to the decision.

### 1.3 Attention is spent on the least surprising events available

```
"emergence_log_by_kind": { "unexplained_shift": 466, "opportunity": 29,
                           "bottleneck": 5 }
```

93% of the emergence log — the stream that is supposed to carry what is
*notable* — is tagged `unexplained_shift`. The ten most recent entries
are:

> "Merrick decided to socialize: content, seeking company"
> "Roswitha II decided to socialize: content, seeking company"
> "Delphine decided to socialize: content, seeking company" … (×10)

A content agent choosing to socialise is the single most predictable
event the simulation can produce. The same flooding has consumed the
Humans pillar's bounded memory: of its 40 slots, ~35 read "X decided to
forage: hungry" or "X decided to rest: tired".

The Humans pillar — the collective mind of everyone in the village —
currently remembers almost nothing except that hungry people look for
food.

### 1.4 Deliberation without compilation repeats forever

```
"laws": { "calls": 7, ... }   // every one returned forms: false
```

The prompt for one of those calls reads:

> "The village of Ridgehaven has lived through this same hardship
> **590 separate times**: family lines dying out, one after another.
> Norms it already holds: None yet. Has the village settled on a real
> rule in response, or is it still too soon to say?"

Answer: `{"forms": false}`. Five hundred and ninety occurrences, seven
deliberations, zero rules, no memory that the question was already
asked six times. There is no mechanism by which repeated failure to
resolve becomes either a resolution or a learned "stop asking."

### 1.5 Two incidental bugs found in the same data

Worth recording, though they are ordinary defects rather than
architectural findings:

- **`ontology_proposal` emitted nothing.** `used_fallback: true`,
  `raw_model_output: ""`, `reasoning: true`. This is the same failure
  mode fixed for `personal_belief` in v1.6.0 (`PERSONAL_BELIEF_NUM_
  PREDICT_MULT = 3.0`): a large output schema plus a reasoning trace
  exhausts the token budget before any JSON is written. The fix was
  never generalised to the other large-schema reasoning jobs.
  `ontology_proposal`, `beliefs`, `institution_belief` and
  `narrative_direction` are all in the same class.
- **Deep-reasoning latency is extreme.** `personal_belief` p95 =
  498,194 ms (8.3 minutes); `nature_mind` = 243,916 ms; reasoning-tier
  p50 = 95,500 ms. This is a hard constraint, not a bug to fix, and it
  is *why* impasse-gating matters: at ~95 s per deliberative thought,
  every one of them must be worth having.

These are tracked as Tier 7 preflight items (§7), not as part of the
architecture.

---

## 2. Principles adopted — and what is rejected

The brief named several architectures and invited better ones. Here is
what I actually took from each, what I left, and why.

### 2.1 The primary anchor: the Standard Model of Mind

Laird, Lebiere & Rosenbloom (2017), *A Standard Model of the Mind*, is
the field's own consensus synthesis across ACT-R, Soar and Sigma. It is
the best answer to "if better evidence-supported architectures exist,
prefer those" — it *is* the aggregation. Its structural commitments,
adopted here nearly wholesale:

- Separate **declarative** and **procedural** long-term memory.
- A small **working memory / global buffer** that modules communicate
  through, rather than calling each other directly.
- A **serial cognitive cycle** with **parallel within-module**
  processing — the exact shape of Hearthmind's runtime already.
- **Incremental, online learning** rather than batch retraining.
- Perception and action as modules that touch the world, never the
  other modules.

### 2.2 Global Workspace Theory (Baars; LIDA as its implementation)

Many parallel unconscious specialists compete; a winning coalition is
*broadcast* globally. This maps onto Hearthmind's real engineering
situation better than anything else available: the LLM is a scarce
serial resource (one slot, ~18–95 s per call) surrounded by hundreds of
cheap parallel deterministic processes. That is a global workspace
whether or not it is called one.

**Taken:** competition among coalitions on salience; a single serial
winner per cycle; global broadcast of the winner.
**Left:** LIDA's specific 300 ms cycle timing (meaningless at
Hearthmind's tick scale) and its full module inventory.

**Stated plainly, because the brief raises sentience:** GWT is adopted
here as an *engineering* architecture for organising computation under
a serial bottleneck. Whether a global workspace produces phenomenal
experience is contested and unsettled, and nothing in this codebase
should claim it does. HCA is a bet on functional cognitive
organisation. That bet is testable (§8); the harder question is not,
and the code should stay honest about the difference.

### 2.3 Predictive processing / active inference (Rao & Ballard; Clark; Friston)

Perception is prediction; only **prediction error** propagates upward;
attention is **precision-weighting** of that error.

This is the direct fix for §1.3. A specialist that keeps a cheap
running forward model of its own signal can compute
`surprise = |actual − predicted| / (σ + ε)` in about five lines, with
no machine learning at all. "Content agent socialises" then scores ~0
and never reaches the workspace; "590th family extinction during
recorded prosperity" scores high and does.

Precision-weighting matters as much as the error itself: a chronically
noisy channel should not be able to hijack attention just by being
noisy. Dividing by the running standard deviation gives that for free.

**Taken:** hierarchical prediction, error-gated propagation,
precision-weighted attention.
**Left:** the strong Free Energy Principle claims (contested, and the
full variational machinery is intractable here) and any literal
generative-model inversion. The engineering core is well-supported and
cheap; the metaphysics is not needed.

### 2.4 Soar: impasse-driven subgoaling and chunking

Soar's decision procedure, when it cannot choose, declares a typed
**impasse** and creates a subgoal to resolve it — then **chunks** the
resolution into a rule so the same impasse never recurs.

This answers the single most important open question in Hearthmind:
*when is it worth spending a deliberative call?* The answer stops being
"every N ticks, round-robin" and becomes **"when the cheap layer is
genuinely stuck, and this is the most important place it is stuck."**
Soar's four impasse types transfer directly (§3, Layer 4).

Chunking is the other half, and it is what §1.4 is missing entirely:
the result of a deliberation must become a cheap artifact that handles
the next occurrence without deliberating again.

**Taken:** typed impasses as the deliberation trigger; chunking as the
learning mechanism.
**Left:** Soar's full production-rule substrate. Hearthmind's cheap
layer is Python/C++ and Tier 6 models, not a RETE network.

### 2.5 ACT-R: declarative memory activation

ACT-R's base-level activation equation is the evidence-supported,
decades-replicated version of what `retrieve_relevant_memories` already
approximates with three hand-set weights (`agent.py:472-475`):

```
A_i = ln( Σ_j (t − t_j)^(−d) )  +  Σ_k W_k · S_ki  +  ε
      └── recency + frequency ──┘   └─ spreading ─┘   noise
```

with `d ≈ 0.5`. Every input already exists: `memory_salience`,
`memory_access` (the reinforce counters shipped in B8 — the soak shows
real values of 53, 25, 18 against many zeros, so the signal is live and
currently used only for eviction ordering), `memory_causes`, and the
bag-of-words relevance term. Adopting the real equation unifies four
hand-tuned mechanisms into one principled one and yields forgetting
curves, recency, frequency and context priming together.

**Taken:** the activation equation, declarative/procedural separation,
utility-based conflict resolution for goal selection.
**Left:** ACT-R's buffer/module timing model.

### 2.5a Complementary Learning Systems: specialists that adapt, not just observe

**Added 2026-08-02, explicit user amendment to the filed architecture:**
*"Every subsystem should itself be capable of adaptation. Specialists
should not remain static feature extractors forever. They should
accumulate experience, revise internal models, forget obsolete
assumptions, and improve predictions over time. The architecture
should evolve toward a society of learning cognitive processes rather
than a collection of fixed modules communicating through a
workspace."*

This is a real amendment to Layer 1 as originally specified (§3), not
a rewording. The original text gave every specialist a `predict()`
method but left *how the forward model gets better* unstated — in
practice this meant "a hand-set EMA," which is a feature extractor,
not a learner. The amendment makes that a defect, not a simplification
worth keeping.

**Evidence-supported principle taken:** Complementary Learning Systems
theory (McClelland, McNaughton & O'Reilly 1995; Kumaran, Hassabis &
McClelland 2016) — the mechanism biological memory actually uses to
get *both* fast adaptation and stable long-term knowledge without one
destroying the other. A fast, high-plasticity store (hippocampus)
absorbs new experience immediately; a slow, high-capacity store
(neocortex) consolidates it later via **interleaved replay**, which is
precisely what prevents new learning from catastrophically overwriting
old — the specific, well-documented failure mode any naive "just keep
training the same model on new data" scheme runs into.

This is not a new mechanism to invent: **Tier 6's L5 lifelong-learning
loop (`ML-ARCHITECTURE-2026-08-01.md`, `hearthmind/ml/lifelong.py`)
already IS a CLS implementation**, built and verified in v1.34.172, and
never previously connected to L1 in the HCA design:

- `ReplayBuffer` (Algorithm-R reservoir sampling) is the interleaved-
  replay half — new experience mixed with a representative sample of
  everything the model has ever seen, the exact mechanism CLS theory
  names as the fix for catastrophic forgetting. Verified against the
  real theoretical reservoir-sampling retention rate, not just "seems
  to work."
- `continual_train_mlp` (warm-start fine-tuning, never reinitializing
  from scratch) is revising an internal model rather than replacing it
  — "accumulate experience" made literal.
- `passes_shadow_gate` (L5.3) is how **"forget obsolete assumptions"
  stays safe rather than reckless**: a retrained candidate replaces the
  live model only if it doesn't regress a held-out metric. A specialist
  is allowed to change its mind, but never allowed to silently get
  worse at its one job.
- `CheckpointHistory` gives every specialist's own learning a
  bounded, versioned, inspectable past — directly answers the
  Observatory's own "show me the learning" panel (§6.2) with real
  data instead of an aspiration.

**What L6's model-genome evolution (`hearthmind/ml/evolution.py`,
v1.34.176) adds beyond L5:** L5 is *ontogeny* — one specialist's
lineage getting better across its own lifetime. L6 is *phylogeny* —
variation and selection across a whole population of candidate
specialist configurations (`GenomePopulation.evaluate_and_select`, a
real μ+λ evolutionary step). Together they are the two axes the user's
"society of learning cognitive processes" phrase actually names: each
process learns individually, and populations of processes can be
selected over. Neither was previously wired to a real L1 specialist
— see the new Stage G items below (§7).

**Taken:** every L1 specialist gets a `learn()` capacity alongside
`predict()`/`observe()`/`error()`/`bid()` — see the amended Layer 1
definition (§3) — backed by L5's replay-buffer-plus-shadow-gate
pattern specifically, not a bespoke per-specialist scheme.
**Left:** full biological plausibility (no claim this models an actual
hippocampus/neocortex split, only the functional replay-plus-gate
mechanism that theory motivates) and any specialist learning through
raw backprop on live simulation ticks (learning happens on an offline/
async cadence against accumulated experience, per Tier 6's own
"offline training, cheap inference" discipline — the runtime tick loop
never blocks on gradient computation, same invariant B0 already
enforces for scheduling).

### 2.6 SPA / Nengo: semantic pointers, minus the neurons

Eliasmith's Semantic Pointer Architecture represents concepts as
high-dimensional vectors and *composes* them algebraically — binding by
circular convolution, bundling by normalised addition.

The brief explicitly says the goal is functional organisation, not
biological simulation, so the spiking-neuron substrate (Nengo's actual
contribution) is correctly out of scope. The *representational* idea is
not: Hearthmind's `InventedConcept` registry currently composes
concepts only as LLM-authored text, which means it cannot do analogy,
cannot measure conceptual distance, and cannot generate candidate
combinations without a call.

With Tier 6's L1.1 embedding as the vector space, binding and bundling
are roughly ten lines of numpy, and the LLM's job shrinks to *naming
and judging* the best algebraically-generated candidate rather than
inventing from scratch.

**Honest flag:** this is the most speculative item in the document and
is gated behind L1.1 actually existing. It is scheduled last (§7).

### 2.7 Attention Schema Theory (Graziano)

The brain builds a simplified *model of its own attention*. This is a
precise description of what the Reflection pillar and the Town
Consciousness are already groping toward, and it makes the Cognitive
Observatory something the simulation can read as well as the player:
the attention schema is itself broadcastable content, so a mind can
notice that it has been ignoring something.

**Taken:** an explicit, inspectable self-model of attention allocation.

### 2.8 Clarion, and the dual-process framing

Sun's Clarion separates implicit (fast, subsymbolic) from explicit
(slow, symbolic) processing, with bidirectional transfer between them.
That is exactly Hearthmind's deterministic/LLM divide, and it supplies
the vocabulary for explaining HCA to a player: **System 1 is the
simulation, System 2 is the workspace.** Kahneman's framing is the
legible surface; Clarion is the mechanism underneath, including the
crucial *bottom-up* direction (implicit regularities becoming explicit
rules) that chunking implements.

### 2.9 Explicitly rejected

- **Spiking-neural / neuromorphic substrate.** Ruled out by the brief
  itself and by the runtime budget.
- **Full Bayesian active inference.** Intractable at this scale;
  precision-weighted error gets the useful 90%.
- **A single monolithic "agent brain" LLM prompt.** Directly contrary
  to the whole document and to the standing "never giant prompts" rule.
- **Replacing the four pillars with a new taxonomy.** The pillars are
  the *scales* at which minds exist; HCA is what is inside one. Both
  are needed.
- **Any claim that this produces sentience.** See §2.2.

### 2.10 Bandit-style exploration and outcome credit assignment

*(Added 2026-08-02, second amendment. The evidence base for §3.3's
arbitration redesign.)*

The first draft of Layer 3 scored bids with `w₁·surprise + w₂·urgency
+ w₃·staleness + w₄·goal_relevance` and took the maximum. That is a
**priority queue with a nicer name**, and the objection to it is
correct on three independent grounds:

1. **Fixed weights are not attention.** Real attention is not a
   constant function of feature values; the *gain* on a channel varies
   with how informative that channel has proven to be. A fixed `w₁`
   says surprise from a well-calibrated specialist and surprise from a
   chronic false-alarmer are worth the same. They are not.
2. **A max over independent scores cannot express agreement.** GWT's
   central claim (§2.2) is that *coalitions* compete, not individual
   processes. Five specialists independently surprised about the same
   subject is qualitatively different evidence from one specialist
   shouting, and a per-bid max cannot represent the difference.
3. **Exploitation-only scoring never investigates what it does not
   already understand.** A bid the mind is deeply uncertain about is
   *worth attending precisely because attending resolves the
   uncertainty* — but under a value-maximising score it loses to a
   confident, well-understood, mildly-surprising bid every time. For a
   project whose stated purpose is emergent cognition, that is the
   wrong failure mode to build in.

**Taken:** the *upper-confidence-bound* formulation from the bandit
literature (Auer, Cesa-Bianchi & Fischer 2002) as the exploration
mechanism — `score = value_estimate + β·√(uncertainty)`. This is the
principled, **non-random** answer to exploration: an uncertain bid
wins because its *plausible upside* is high, not because a die landed
on it. It gives the mind a real reason to look at what it does not
understand, and the term shrinks by itself as evidence accumulates —
so curiosity about a given subject is self-limiting without any decay
constant to hand-tune.

**Also taken:** temporal credit assignment (Sutton & Barto) as the
mechanism by which a specialist learns to bid better. After a
workspace winner is resolved, a *realised value* is measured (did the
broadcast reduce anyone's subsequent prediction error? did downstream
emergence follow? was a chunk produced?) and credited back to every
specialist in the winning coalition. Reliable bidders earn gain;
chronic false-alarmers lose it. This is L1 `learn()` (§2.5a) applied
to a specialist's *bidding policy* rather than only its forward model,
and it reuses Tier 6 L2.1's already-planned value head as the
estimator rather than inventing a second one.

**Left:** full RL. No policy-gradient learner sits in the arbitration
path, no exploration schedule to tune, no reward function anyone has
to design — realised value is *measured* from signals the simulation
already produces. Also left: probability matching / softmax sampling,
the other standard answer to exploration. It is rejected deliberately:
it re-introduces randomness into arbitration, which would break
replay-hash equivalence for the Mind layer and would make the
Observatory's "why did this win?" panel unanswerable. **Attention here
is deterministic given the same evidence** — the variety comes from
competition, not from a die.

**The one thing that must NOT be learnable.** Staleness gain stays
structural and fixed. If a specialist that never wins learned to bid
lower, starvation would become self-reinforcing — the exact failure
this whole redesign exists to prevent, re-created inside the learning
loop. This mirrors the standing guardrail in
`ML-ARCHITECTURE-2026-08-01.md` against training a model on its own
unweighted outputs.

---

## 3. The architecture

Six layers. **The same six apply at every scale** — an agent, a
settlement, Nature, Innovation, Reflection — which is the brief's
requirement that this not be a humans-only design.

```
 ┌─ L5  METACOGNITION ── watches L3's own history; retunes precision;
 │                       maintains the attention schema
 ├─ L4  DELIBERATION ─── impasse-gated. Resolver may be a cached chunk,
 │                       a learned model, or the LLM. Result is chunked.
 ├─ L3  GLOBAL WORKSPACE  coalitions COMPETE → one winner → BROADCAST
 │                       ▲ bids merge into coalitions; gains are learned
 │                         from realised outcomes; staleness unbounded
 │                       ▲ domains: WORLD | MACHINE | OBSERVER (§3.2)
 ├─ L2  WORKING MEMORY ── small, bounded, activation-ranked (ACT-R)
 │                       ▲ prediction errors only
 ├─ L1  SPECIALISTS ───── many, parallel, cheap, always-on, ADAPTIVE.
 │                       predict() / observe() / error() / bid() / learn()
 └─ L0  SUBSTRATE ─────── deterministic Body. Physics, ecology, economy.
```

### Layer 0 — Substrate (unchanged)

The deterministic Body: terrain, weather, hydrology, ecology, economy,
construction, decay. C++ where hot, per R7. This is *the world*, not a
mind, and HCA does not touch it. Consequence worth stating: because HCA
changes only Mind scheduling, `scripts/verify_replay_hash.py` remains a
valid equivalence check for the deterministic layer throughout.

### Layer 1 — Specialists (the subconscious)

Every existing `_detect_*`, every `FieldGrid` field, every per-tick
deterministic job is *already* a specialist. The reframe gives them a
uniform five-method interface — **amended 2026-08-02** to add the
fifth, per the explicit user direction that specialists must not
remain static feature extractors (§2.5a):

```
predict()  → what this specialist expects next (a LEARNED forward model)
observe()  → what actually happened
error()    → precision-weighted surprise: |actual − predicted| / (σ + ε)
bid()      → a coalition proposal, carrying salience, or nothing
learn()    → revise the forward model from accumulated (predict, observe)
             pairs — replay-buffered, shadow-gated (§2.5a), never live-tick
             gradient descent
```

**A specialist never calls the LLM.** It bids. This single rule is what
converts ~55 independent racing call sites into one arbitrated system,
and it is the mechanical content of "the LLM is one subsystem."

**A specialist is not a fixed function of its inputs.** `predict()`
consults whatever model `learn()` has most recently produced — a hand-
set EMA is a legitimate, cheap STARTING point for a young specialist
with no accumulated experience, never the permanent ceiling. This is
the difference between "a collection of fixed modules communicating
through a workspace" (rejected, per the amendment's own wording) and
"a society of learning cognitive processes": the same specialist that
bid confidently on tick 1,000 should bid *more accurately* by tick
100,000, and should be measurably able to unlearn a pattern that
stopped holding (a predator species going extinct, a trade route
closing) rather than keep predicting against it forever.

Most specialists will bid essentially never — which is correct, and is
the fix for §1.3. Learning does not raise that rate: `learn()` runs on
its own async cadence against accumulated `(predict, observe)` pairs
(the same "offline training, cheap inference" split Tier 6 already
holds to), never inside the hot bid path.

### Layer 2 — Working memory

Small, bounded, shared, **activation-ranked** by the ACT-R equation of
§2.5 rather than by recency or insertion order. `Pillar.working_memory`
is already this structure with a weaker ranking rule; agents get the
same treatment via `retrieve_relevant_memories`.

Only prediction errors that clear a precision-weighted threshold enter.
This is the filter that stops the Humans pillar remembering forty
consecutive instances of hungry people foraging.

### Layer 3 — The Global Workspace

One serial channel per domain (§3.2). Per cognitive cycle:

1. Collect all bids.
2. **Merge overlapping bids into coalitions** (§3.3).
3. **Score each coalition** by the evidence-based rule of §3.3 — not a
   fixed weighted sum.
4. **One winner.**
5. **Broadcast the winner to every subscribed subsystem**, attenuated
   by relevance — not just back to the bidder.
6. Log the full competition: winner, losers, every factor's
   contribution, and the reason.
7. Measure the winner's **realised value** once resolved, and credit it
   back to the bidders (§3.3, §2.10).

*(Steps 2, 3 and 7 were added by the 2026-08-02 arbitration amendment.
The original design collapsed them into a single weighted-sum max —
see §3.3 for why that was wrong.)*

Three properties do the real work:

- **Attention emerges from competition, not from a fixed priority
  order.** §3.3 is the whole mechanism.

- **Broadcast, not point-to-point.** Today a dream's result reaches one
  agent. Under HCA it reaches Humans, Village and Reflection as well.
  Cross-system emergence stops being something individual jobs have to
  be hand-wired for (B4's ten hand-placed arrows) and becomes the
  default behaviour of the bus.
- **Substrate-agnostic resolution.** The winner is resolved by whichever
  of three resolvers is adequate: a **cached chunk**, a **learned
  model**, or **the LLM**. Only the third is expensive. This is
  precisely "the LLM is one cognitive subsystem," expressed as a
  dispatch decision rather than an aspiration.

**Starvation guarantee.** Two layers, deliberately: the *primary*
mechanism is competitive — a subsystem's staleness gain grows without
bound, so anything ignored long enough eventually out-competes
everything else on merit (§3.3). B2.2's bounded-deferral floor is kept
only as a hard backstop underneath it, because a gain is a tendency
and a floor is a guarantee. This is what fixes §1.2: a system that has
never run cannot stay unrun.

### Layer 4 — Deliberation

Fires **only on a named impasse**, after Soar:

| Impasse | Meaning | Live example from the soak |
|---|---|---|
| **tie** | two options score equal; the cheap layer cannot choose | two equally-scarce occupations to assign |
| **no-change** | the same state persists past threshold with no progress | 590 family extinctions, no rule (§1.4) |
| **conflict** | two subsystems hold contradictory beliefs | already detectable via `Pillar.disagrees_with` |
| **novelty** | high surprise with no matching schema | first predator-pack extinction |

Then **chunking**: the resolution is compiled into a cheap reusable
artifact — a cached decision keyed by the impasse signature, a Tier 6
model update, a new `TriggerRule`, a revised belief. The next
occurrence is handled without deliberation.

This is the continual learning the brief asks for, and it has a
strong consequence: **deliberative cost per unit of emergence should
fall as a world matures.** A ten-year-old village should think hard
*less* often than a young one, about *harder* things. That is both the
design goal and the falsification test (§8).

**Two distinct learning mechanisms, not one, and both are now real
(§2.5a).** L4 chunking is *discrete and symbolic* — one resolved
impasse becomes one cached artifact, keyed by that impasse's exact
signature; it generalises only as far as future signatures match. L1
`learn()` is *continuous and statistical* — a specialist's forward
model gets incrementally better at its one narrow job from ordinary
`(predict, observe)` pairs, with no impasse required at all. A
specialist doesn't need to have ever caused a deliberation to still be
learning; a chunk doesn't need an underlying learned model to be
useful. They compose: L4's own "Tier 6 model update" artifact type
*is* L1's `learn()` being triggered as one impasse's resolution, but
the reverse is not required — most `learn()` calls happen on the
ordinary async cadence, never touching L4 at all.

### Layer 5 — Metacognition

Watches Layer 3's own history rather than the world: which coalitions
win, which impasses recur unresolved, whether specialists' predictions
are calibrated. Produces (a) precision/salience retuning, (b)
hypotheses, (c) an **attention schema** — an explicit model of what
this mind has been attending to and ignoring, itself broadcastable.

Reflection already occupies this role and currently starves; under HCA
it is a first-class citizen with a guaranteed floor.

### 3.1 Nesting: minds inside minds

The scales compose. **An agent's workspace broadcast is an input event
to the village's specialists.** A settlement's broadcast is an input to
the world-scale Reflection and Consciousness layers. Collective
cognition stops being a metaphor and becomes the literal claim that
one mind's conscious content is another mind's sensory input.

This is why the six layers must be scale-generic, and it is the
structural answer to "the same principle should apply to higher-level
systems, not only individual humans."

### 3.2 Cognitive domains: the Runtime and the Player Model as minds

*(Added 2026-08-02, second amendment.)*

**The question.** HCA claims the six layers are scale-generic and apply
to every cognitive participant. Two participants were quietly exempt:
the **Adaptive Runtime** (Tier 5 Part B) and the **Player Model**
(Phase G's Town Consciousness). Should they become first-class
specialists that predict, bid, learn and broadcast?

**The evaluation — yes, and the reason is that they already are one in
substance.** The Runtime already implements all five L1 methods under
other names, and it is worth listing the correspondence exactly,
because it shows this is a reframe rather than a new subsystem:

| L1 method | The Runtime's existing implementation |
|---|---|
| `predict()` | B8.1 `WorkloadForecaster` — a real trained MLP predicting load |
| `observe()` | B5.1 `TaskMetrics` — real per-task call counts and wall times |
| `error()` | B8.3 `ForecastAccuracyTracker` — measured predicted-vs-actual, already reliability-weighted |
| `bid()` | B15.3 `EscalationLadder` — "I need rung 5: reduce cognition breadth" |
| `learn()` | B13 `HypothesisLoop` — observe, hypothesise, apply, measure, keep or roll back |

**So the honest finding is not "should we add this" but "this is
already a mind, running unarbitrated and unobserved."** That is the
real defect. B15's ladder today *unilaterally decides* to reduce
cognition breadth — a decision with direct authority over how much the
world gets to think — without competing for it, without being logged
into any workspace, and without appearing anywhere a person can watch
it happen. Making it bid is what makes that power legible.

**The mechanism: typed cognitive domains.** Every specialist,
coalition and broadcast carries a `domain`:

| Domain | Reasons about | May write | Example specialists |
|---|---|---|---|
| **WORLD** | the simulated world | Mind-layer world state (beliefs, goals, culture) | every existing `_detect_*`, `FieldGrid`, pillar |
| **MACHINE** | computation and scheduling | *only* B6 `TunableRegistry` tunables and runtime control state | forecaster, escalation ladder, dormancy, budgets |
| **OBSERVER** | the player watching | *nothing* — read-only prediction | the Player Model |

Three rules make the domains load-bearing rather than decorative:

1. **Write scope is mechanically enforced, not documented.** A
   MACHINE-domain specialist may never write `world/`, `agents/`,
   `settlement/` or `economy/` state. This is checkable by the same AST
   technique `scripts/verify_runtime_invariant.py` already uses for
   B0's prime invariant, and it is the structural answer to *"remaining
   incapable of directly changing deterministic world state."* Note the
   guarantee is already half-built: B15's `TWO_PART_GUARANTEE` states
   the deterministic Body is replay-identical regardless of any runtime
   decision. Domains make that a property of the cognitive
   architecture, not only of the runtime.
2. **Domains do not compete for each other's budget.** Each domain
   arbitrates its own scarce channel. A MACHINE bid can never
   out-compete a Nature belief for the LLM slot, because it is not
   bidding for that slot at all — it is bidding to *set the size of the
   budget* the WORLD domain then arbitrates within. This is §3.1's
   nesting applied honestly: the Runtime is one level up, adjusting the
   frame, not a rival inside it. Without this rule the architecture
   would contain an obvious inversion — the machine deciding the world
   should think less, and winning that argument on its own merits.
3. **Cross-domain content flows only through L5.** A MACHINE broadcast
   reaches the WORLD mind's *metacognition* (which is the layer whose
   job is already "watch the mind, not the world") and the Observatory.
   It never reaches a WORLD-domain L1 or L2. A settlement can therefore
   never form a belief about being throttled — that would be a
   category error and a leak of the Machine surface into the fiction.

**The Player Model, specifically.** Its bid is a prediction about the
observer ("this person is about to stop watching"; "this person has
intervened three times this week and will again"). It is a genuine
cognitive participant and benefits from the same learning loop as any
other specialist. But it is **read-only by domain**, and this matters:
it must not be confused with the Town Consciousness's *interventions*
(false memories, weather nudges, misplaced objects), which do change
world state. Those are a separate, already-existing, deliberately
deniable channel and are **not** part of the OBSERVER domain. Phase G's
discipline is unchanged and is now partly structural: an
OBSERVER-domain broadcast is dev-console-only by domain rule, not by
convention, so its content cannot be narrated to the player by any
future Observatory panel.

**What this buys, stated as a claim to be checked.** The Runtime stops
being an invisible hand that silently throttles thought, and becomes a
participant whose reasoning is inspectable next to everyone else's —
which is exactly the project's stated purpose applied to the one
subsystem that had escaped it. Roadmap: **Stage H** (§7).

### 3.3 Arbitration: how a coalition wins

*(Added 2026-08-02, second amendment. Supersedes the fixed weighted
sum in the original Layer 3 step 2. Evidence base: §2.10.)*

**Step 1 — Coalitions form before anything is scored.** Bids naming
the same subject, region or entity merge. A coalition's strength is
**superadditive but sublinear**: several specialists independently
surprised about one thing is stronger evidence than the strongest of
them alone, but ten weak corroborations never beat one genuine crisis.
Concretely, strength grows with the number of independent corroborating
specialists at a diminishing rate, and corroboration counts only when
the bidders are genuinely independent — two views of the same
underlying reading are one bidder, not two. This step is what a
priority queue structurally cannot express, and it is the mechanism
that makes agreement matter.

**Step 2 — Each coalition carries evidence, not a number.** A bid is a
record with a provenance for each factor, so the Observatory can show
*why* something won, factor by factor:

| Factor | What it is | Where it comes from |
|---|---|---|
| **surprise** | precision-weighted prediction error | L1 `error()` |
| **consequence** | estimated downstream impact if true | Tier 6 L2.1 value head |
| **confidence** | how much the bidder trusts its own reading | the specialist's own calibration |
| **uncertainty** | how little the mind knows about this subject | variance of the value estimate |
| **urgency** | does the window to act close soon | deadline/timescale (B9) |
| **staleness** | time since this subsystem last won | workspace history |
| **historical usefulness** | did attending to this bidder pay off before | realised-value credit (step 5) |

**Step 3 — Scoring, and why it is not a weighted sum.** Three
mechanisms, each doing something a linear score cannot:

- **Historical usefulness is a *gain*, not an addend.** It multiplies
  the coalition's surprise and consequence terms rather than adding
  alongside them. A specialist that has repeatedly proven worth
  attending has its whole signal amplified; a chronic false-alarmer is
  attenuated toward silence without ever being hard-muted. This is
  precision-weighting (§2.3) applied to *sources* rather than signals,
  and it is the difference between "attention" and "a fixed policy."
- **Uncertainty is an exploration bonus, not a penalty.** Score carries
  a `+ β·√(uncertainty)` term (§2.10). A coalition the mind understands
  poorly can win *because* winning resolves the uncertainty — the mind
  investigates what it does not understand, deterministically, with no
  randomness. The bonus shrinks by itself as evidence accumulates.
- **Staleness is an unbounded multiplier.** A subsystem's gain grows
  with time since its last win, without ceiling. Anything ignored long
  enough eventually wins on merit. This is why the design does not
  depend on reserved slots or fixed priority floors — those remain only
  as a hard backstop (Layer 3).

**Step 4 — No randomness, anywhere.** Ties break on accumulated
staleness first, then on the coalition carrying the largest unexplained
error — never `rng.choice`. Two consequences worth stating plainly:
the Observatory's "why did this win?" panel is always answerable, and
Mind-layer arbitration stays replayable given the same evidence, so
`verify_replay_hash.py`'s discipline extends naturally to it. **The
variety comes from competition between many learning bidders, not from
a die.**

**Step 5 — Learning to bid, from outcomes.** Once a winner is
resolved, a **realised value** is measured from signals the simulation
already produces: did the broadcast reduce any subscriber's subsequent
prediction error? did a real emergence event of nontrivial magnitude
follow? was a chunk produced (L4), or was the deliberation wasted?
That value is credited back to every specialist in the winning
coalition, updating its historical-usefulness gain. Losing coalitions
are credited too, where a counterfactual is honestly available: a
coalition that lost and whose predicted consequence then materialised
anyway earns gain, which is how a systematically-ignored specialist
climbs out on evidence rather than on a floor.

Two guardrails, both non-negotiable:

- **Staleness gain is never learnable.** If a specialist that never
  wins learned to bid lower, starvation would become self-reinforcing —
  the exact failure this redesign exists to prevent, re-created inside
  the learning loop (§2.10).
- **A bid is only credited when its outcome was actually measured.**
  Never train the bidding policy on unmeasured bids, mirroring
  `ML-ARCHITECTURE-2026-08-01.md`'s standing guardrail against a model
  training on its own unweighted outputs.

This is L1 `learn()` (§2.5a) applied to the bidding policy — which is
the direct answer to *"specialists should improve their bidding over
time from outcomes."* It therefore **depends on Stage G**, and the
roadmap sequences it accordingly (§7).

---

## 4. How existing systems re-map (almost nothing is discarded)

The strongest argument for this direction is that Tier 5 already built
most of the machinery a global workspace needs — it simply had no
client. Every Tier 5 entry in `CLAUDE.md` ends with some variant of
*"not wired into any real control point."* Tier 7 is the client.

| Existing | HCA role | Fit |
|---|---|---|
| B1 `TaskRegistry` (declared reads/writes) | specialist interface + dependency graph | direct |
| B2 `Scheduler` (priority, budgets, bounded deferral) | per-domain budgets + the hard starvation backstop under §3.3's competitive gain | extend |
| B6 `TunableRegistry` (`SAFE`/`SENSITIVE`) | the MACHINE domain's entire legal write scope (§3.2) | direct |
| B8.3 `ForecastAccuracyTracker` | a specialist's `error()`, and the seed of its historical-usefulness gain | direct |
| B13 `HypothesisLoop` + `AdaptationHistory` | the Runtime's own `learn()` and its learning trail (§3.2) | direct |
| B15.3 `EscalationLadder` | the Runtime's `bid()` — today unarbitrated and unlogged (§3.2) | extend |
| B2.4 `RegionAttentionGate` | attention allocation | direct |
| B3 `DirtyTracker` / `EventBus` | change detection — the *input* to surprise | partial; detects change, not surprise |
| B5 `TickTrace` reason strings | "why was reasoning invoked" UI | direct |
| B8 `WorkloadForecaster` | a forward model, already built | direct |
| B9 `TimescaleLadder` | hierarchical cycle rates | direct |
| B10 `RegionGrid` / locality | *where* surprise is | direct |
| B11 hierarchical memory tiers | declarative memory tiering | direct |
| B12 compression ladder | memory consolidation | direct |
| B13 hypothesis loop | metacognitive retuning (L5) | direct |
| B15 escalation ladder | graceful degradation under load | direct |
| Tier 6 L2.1 value head | consequence estimation *and* realised-value credit assignment (§3.3 step 5) | direct |
| Tier 6 L2.2 policy | the cheap resolver tier | direct |
| Tier 6 L1.1 embedding | semantic-pointer space (§2.6) | direct |
| Tier 6 L5 lifelong learning (`ml/lifelong.py`) | L1 `learn()`'s implementation — replay buffer + shadow gate (§2.5a) | direct |
| Tier 6 L6 model-genome evolution (`ml/evolution.py`) | variation/selection across a specialist's candidate configurations (§2.5a) | direct |
| `cognition/attention.py` `pillar_salience` | an early, partial arbitration | extend |
| `Pillar` observe/interpret cycle | L1→L2→L3 cycle, under-differentiated | extend |
| `world/emergence.py` | the bid stream — needs surprise, not just magnitude | extend |
| `Pillar` inbox/outbox (B4) | ten hand-wired arrows → one broadcast bus | replace |
| `_schedule_llm_job` cadence gates | replaced by impasse + bid | replace |

Two genuine replacements, everything else extended or wired. That is a
much cheaper reframe than it first appears.

---

## 5. What this predicts will improve

Stated as expectations so they can be checked against a future soak,
not as promises:

- **Pillar cognition stops starving.** Guaranteed floors plus staleness
  in the salience term mean `reflection_notebook_total` should be
  non-zero well inside a 64k-tick run.
- **The emergence log becomes signal.** `unexplained_shift` should drop
  from 93% to a small minority, because unsurprising events no longer
  qualify.
- **Repeated hardship resolves.** 590 identical occurrences should
  produce either a rule or a chunked "this does not produce a rule" —
  never a 591st identical deliberation.
- **Deliberative calls fall while emergence holds.** The headline
  metric (§8).
- **Cross-system surprises appear.** Broadcast means Nature's belief
  can move Innovation without anyone wiring a Nature→Innovation arrow.
- **Specialists get measurably better at their own job.** A learning
  specialist's prediction error should trend down over its own
  lifetime on a stationary signal, and should visibly re-adapt (not
  stay wrong forever) when the underlying pattern genuinely shifts —
  the direct test for §2.5a's amendment, tracked live in the
  Observatory's learning chart (§6.2).
- **Attention stops looking like a fixed policy.** With learned gains
  and an exploration term, which subsystem wins should shift visibly
  over a long run as bidders prove themselves or fail to — and no
  subsystem's win-share should sit at zero across any window, without
  any reserved slot doing the work (§3.3).
- **The Runtime's decisions become legible.** Every escalation to
  reduced cognition breadth appears in the Observatory as a bid that
  won, against named losers — rather than happening silently inside
  the scheduler as it does today (§3.2).

---

## 6. The Cognitive Observatory

The brief asks for a UI in which the *emergence of cognition itself*
becomes observable. This is a deliberate amendment to a standing rule.

### 6.1 Amendment to the two-surface rule

`CLAUDE.md` currently specifies two surfaces: the normal UI (understand
the world) and the developer observatory (prompts, timing, internals).
HCA makes that insufficient, because the mind is now the *subject*, not
an implementation detail. **Three surfaces:**

| Surface | Question it answers | Audience |
|---|---|---|
| **The World** — map, events, inspectors | *What is happening?* | everyone |
| **The Mind** — Cognitive Observatory | *How is it being thought about?* | the primary audience of this project |
| **The Machine** — `⚙ dev`, `/diagnostics` | *Is the runtime healthy?* | developer |

The Mind surface is a promotion, not a leak: material that was
dev-console-only because nothing consumed it becomes first-class
because watching it *is the point of the project*.

**Phase G is unaffected and explicitly re-scoped.** The Observatory
covers agent and pillar cognition. The Town Consciousness's own
workspace — its personality, objectives, player model, interventions —
stays dev-console-only exactly as today. Temperament, mood and omens
stay unlabelled. Nothing in the Observatory narrates anything as
supernatural, and the ambiguity discipline is permanent.

### 6.2 Panels, mapped to the brief's own list

- **Workspace contents** — what won this cycle, its content, and its
  broadcast reach. Beneath it, **the coalitions that lost**, with
  scores. Watching the losers is most of the insight. Each coalition
  breaks down by factor (§3.3) — which specialists joined it, and how
  much surprise / consequence / uncertainty / staleness each
  contributed — so "why did this win?" is always answerable. A domain
  filter (WORLD / MACHINE / OBSERVER, §3.2) sits on this panel;
  OBSERVER content is dev-console-only by domain rule.
- **Attention shifts** — a live timeline of winners; a spotlight that
  visibly moves between subsystems.
- **Prediction errors** — per-specialist surprise sparklines, plus a
  **surprise map overlay**. This composes with the existing `FieldGrid`
  overlays and satisfies the Living Map rule that every overlay answer
  one nameable question at a glance: *where is the world behaving
  unexpectedly?*
- **Memory activation** — for an inspected agent, activation-ranked
  memories decaying live, with spreading activation from current
  context highlighted. This makes forgetting visible.
- **Competing goals** — the candidate goals and their utilities, not
  only the winner.
- **Belief revision** — a diff when a belief changes, showing the
  evidence that moved it and by how much.
- **Concept evolution** — the existing knowledge tree, plus lineage
  animation and (once §2.6 lands) the semantic neighbourhood.
- **Learning** — chunks compiled over time; model versions;
  **deliberative-calls-per-1000-ticks trended against emergence rate**,
  which is the falsification chart from §8 rendered live.
- **Why reasoning was or was not invoked** — the headline panel. One
  line per cycle, in plain language:
  - `IMPASSE(no-change) · "family lines dying out" · 590 occurrences, no rule · DELIBERATED (LLM, 94s)`
  - `IMPASSE(tie) · occupation assignment · resolved by CHUNK #212, no call`
  - `no impasse · peak surprise 0.3 < threshold 1.5 · cheap path`

That last panel is the single most important thing in this document
from a user's perspective: it makes the architecture's central decision
legible every time it is made.

---

## 7. Roadmap: Tier 7

Filed into `ROADMAP-2026-07-REMAINING.md` as **Tier 7 — The Cognitive
Architecture**. Sequenced by dependency; **each item carries a
falsifiable success test**, which is the guard against renaming
existing systems in new vocabulary and calling it progress.

Standing convention preserved: nothing here is built without explicit
direction naming a specific item.

**Preflight (ordinary bug fixes, not architecture)**
- **P1** Generalise `PERSONAL_BELIEF_NUM_PREDICT_MULT` to every
  large-schema reasoning job (`ontology_proposal`, `beliefs`,
  `institution_belief`, `narrative_direction`).
  *Test:* `ontology_proposal` fallback rate falls from 100%.
- **P2** Re-frame the `laws` prompt, which is biased toward "not yet"
  and has produced zero rules in 64k ticks against 590 occurrences.
  *Test:* a law forms in a long soak.

**Stage A — Surprise (the cheapest large win)**
- **A1** `predict()`/`error()` on specialists; precision-weighted
  surprise. *Test:* replaying the soak's event stream, "content agent
  socialises" scores < 0.1 and family-extinction-during-prosperity
  scores > 2.0.
- **A2** Gate `world/emergence.py` on surprise, not occurrence.
  *Test:* `unexplained_shift` share drops from 93% to < 40%.
- **A3** Surprise map overlay. *Test:* renders, and a real disaster is
  visibly the brightest region.

**Stage B — The workspace**
- **B1** Coalition bidding; one arbitrated winner per cycle; every LLM
  call site converted to a bid. *Test:* pillar-level call share rises
  from 1.4% to > 15% without raising total calls.
- **B2** Starvation floors. *Test:* `reflection_notebook_total > 0` in
  a 64k-tick soak.
- **B3** Broadcast bus replacing B4's hand-wired arrows. *Test:* a
  Nature belief measurably influences an Innovation decision with no
  Nature→Innovation-specific code.
- **B4** *(§3.3 step 1, added 2026-08-02)* Coalition formation: bids
  naming the same subject/region/entity merge, superadditively but
  sublinearly, counting only genuinely independent bidders. *Test:*
  five independent mild corroborating bids beat one strong isolated
  bid on the same cycle, and ten weak ones still lose to a genuine
  crisis — both thresholds stated in advance.
- **B5** *(§3.3 steps 2-3)* Evidence-based scoring: the seven-factor
  bid record; historical usefulness as a multiplicative *gain*;
  uncertainty as a `+β·√(uncertainty)` exploration bonus; staleness as
  an unbounded multiplier. *Test:* with expected value held equal, the
  higher-uncertainty coalition wins — the direct proof exploration is
  real and is not randomness.
- **B6** *(§3.3 step 4)* Arbitration determinism and the starvation
  bound. *Test:* identical evidence produces an identical winner across
  two independent process runs (the `verify_replay_hash.py` technique
  applied to the workspace), no RNG appears anywhere in the arbitration
  path, and a specialist that never wins on merit provably wins within
  a stated bounded interval on staleness gain alone.
- **B7** *(§3.3 step 5; depends on Stage G)* Learning to bid from
  realised outcomes, with both guardrails enforced. *Test:* a
  deliberately unreliable specialist and a reliable one, given
  identical raw bids, invert in rank order over a run — and a
  never-winning specialist's staleness gain is verified NOT to have
  been learned downward (the self-reinforcing-starvation guard).

**Stage C — Impasse and chunking**
- **C1** The four typed impasses as the deliberation trigger.
  *Test:* every LLM call in a soak carries a named impasse.
- **C2** Chunking: resolutions compile to cheap artifacts.
  *Test:* the 591st family extinction consumes no LLM call.
- **C3** Cheap-resolver dispatch (chunk → model → LLM).
  *Test:* > 30% of workspace winners resolve without an LLM call.

**Stage D — Memory**
- **D1** ACT-R activation replacing the four hand-tuned mechanisms.
  *Test:* retrieval quality holds or improves on the recorder archive
  while four constants are deleted.
- **D2** Declarative/procedural separation made architectural.

**Stage G — Learning specialists** *(§2.5a, added 2026-08-02)*
- **G1** The `learn()` interface on `Task`/the specialist base shape,
  wired to Tier 6 L5's `ReplayBuffer`/`continual_train_mlp`/`passes_
  shadow_gate` directly (no new learning mechanism). *Test:* a
  specialist's own prediction error trends down over its lifetime on a
  stationary synthetic signal, using the real shadow gate, not a mock.
- **G2** Wire one real, already-existing L1 specialist to G1 — B8's
  `WorkloadForecaster` (already flagged in §4 as "an early, partial
  arbitration") is the natural first target, since it already IS a
  small trained MLP with no continual-retrain loop attached yet.
  *Test:* forecast error on held-out real workload data falls after a
  real `learn()` cycle, and the shadow gate provably rejects a
  retrain that would have made it worse (same test shape L5.3's own
  `passes_shadow_gate` verification already used).
- **G3** "Forget obsolete assumptions," made testable: a specialist
  trained against a pattern that then genuinely stops holding (a
  species goes extinct, a trade route closes) should measurably
  re-adapt within a bounded number of `learn()` cycles, not keep
  predicting the stale pattern indefinitely. *Test:* a synthetic
  regime-change scenario — pre-shift error low, post-shift error
  spikes then falls back down within N cycles, N stated in advance.
- **G4** L6 population-level variation for one specialist family (the
  *phylogeny* half of §2.5a, distinct from G1-G3's *ontogeny*).
  *Test:* a genome population's mean fitness climbs over generations
  on a real specialist's own task, using the real `GenomePopulation.
  evaluate_and_select` (already verified in isolation, never against a
  real L1 consumer).

**Stage H — Non-world minds** *(§3.2, added 2026-08-02; depends on
Stage B for the workspace and Stage G for `learn()`)*
- **H1** Cognitive domains as a real, mechanically-enforced type:
  `WORLD` / `MACHINE` / `OBSERVER` on every specialist, coalition and
  broadcast, with per-domain budgets. *Test:* an AST check (extending
  `scripts/verify_runtime_invariant.py`) proves no MACHINE- or
  OBSERVER-domain code path writes `world/`/`agents/`/`settlement/`/
  `economy/` state, and it genuinely catches a synthetic violation —
  not merely passes on clean code.
- **H2** The Adaptive Runtime as a first-class specialist family: B8's
  forecaster as `predict()`/`error()`, B5's metrics as `observe()`,
  B15's escalation ladder converted from a unilateral actor into a
  real `bid()`, B13's hypothesis loop as its `learn()`. *Test:* a real
  escalation to reduced cognition breadth appears in the workspace log
  as a bid that won against named losers, with its factors recorded —
  where today it happens silently inside the scheduler.
- **H3** Cross-domain isolation: a MACHINE broadcast reaches the WORLD
  mind's L5 and the Observatory only. *Test:* no WORLD-domain L1 or L2
  ever receives MACHINE content, verified directly; no settlement can
  form a belief mentioning scheduling, load or budgets.
- **H4** The Player Model as an OBSERVER-domain specialist —
  read-only, predicting the observer, learning from realised outcomes.
  *Test:* it predicts and learns without writing any world state, and
  its broadcasts are provably unreachable from any player-facing
  surface (the structural half of Phase G's discipline). Explicitly
  **not** in scope: the Town Consciousness's own interventions, which
  stay exactly as they are today.

**Stage E — The Observatory**
- **E1** The "why reasoning was invoked" panel. *Test:* every cycle in
  a live run has a legible one-line reason.
- **E2** Workspace + losing-coalitions panel.
- **E3** Memory activation and competing-goals panels.
- **E4** The learning chart (§8's metric, live).
- **E5** *(depends on Stage G)* Per-specialist learning curves — live
  prediction-error-over-time, one line per specialist, with the
  regime-change re-adaptation from G3 visibly plotted. *Test:* a
  specialist visibly re-adapting after a real regime shift (G3) is
  legible on this panel without reading logs.
- **E6** *(depends on Stage H)* A MACHINE-domain lane in the workspace
  panel: the Runtime's own bids, wins and escalations shown beside the
  world's, on the Machine surface. *Test:* an escalation is watchable
  as it happens, without reading logs.

**Stage F — Semantic pointers** *(gated behind Tier 6 L1.1)*
- **F1** Concept vectors; bundling/binding; LLM names the best
  algebraic candidate. *Test:* a concept combination is generated and
  judged with strictly fewer LLM calls than today's pipeline.

### 7.1 What this does to Tiers 5 and 6

Neither is discarded; both are **re-scoped as substrate for Tier 7**,
which is also the honest explanation for why they have felt inert:
Tier 5 built a runtime with no client, and Tier 6 built resolvers with
nothing to resolve. Tier 7 is the consumer that gives both a purpose,
and §4's mapping table shows the fit is close to one-to-one. Remaining
Tier 5 items (B0.3, B3.3, B4.2, B9.3, and B10.2's other 88 sites)
retain their existing scope and priority.

---

## 8. Risks, and what would falsify this

**The dominant risk is cognitive-architecture cosplay** — adopting the
vocabulary, renaming `_schedule_llm_job` to `workspace.bid()`, and
declaring victory. The defence is structural: every Tier 7 item above
carries a falsifiable test, and an item that cannot state one does not
ship.

**The headline falsification test.** HCA claims deliberative cost per
unit of emergence falls as a world matures. Concretely: across a long
soak, plot LLM calls per 1,000 ticks against a stable emergence-event
rate. If calls fall *and* emergence holds, the architecture works. **If
calls fall and emergence falls proportionally, impasse-gating is just
starvation with extra steps, and this direction should be abandoned.**
That chart is Stage E4, rendered live.

**Other risks, recorded honestly:**

- **Latency dominates everything.** At reasoning p50 ≈ 95 s, a
  deliberative thought is minutes of wall time. HCA is designed *for*
  this constraint rather than around it — scarcity is the premise, not
  an obstacle — but no amount of architecture makes a 4B model on 8 GB
  fast, and this document should not be read as a performance fix.
- **Surprise thresholds are a new tuning surface**, and this project's
  own history (`compute_weather`, flood pressure) shows thresholds are
  where its worst bugs live. Every threshold must be validated against
  *measured* realised distributions over a full simulated year, per the
  standing rule in `CLAUDE.md`.
- **Broadcast could flood.** Point-to-point arrows are noisy but
  bounded; a bus is not. Attenuation by relevance and hard per-cycle
  caps are required from the first commit, not added later.
- **Chunking can ossify.** A compiled decision that stops being correct
  is worse than deliberating. Chunks need confidence decay and
  invalidation on high surprise — the same "beliefs may be wrong and
  revisable" discipline the project already applies to beliefs.
- **A learning specialist can catastrophically forget or drift silently
  worse (§2.5a).** This is precisely the risk CLS theory's replay
  mechanism and L5's shadow gate exist to bound — but the gate is only
  as good as its held-out metric, and a specialist with a poorly-chosen
  metric could pass the gate while genuinely degrading at the thing
  that actually matters. G1/G2 (§7) must verify against a real,
  meaningful held-out signal, not a convenient proxy.
- **The machine could starve the mind (§3.2).** A Runtime that bids —
  and whose whole job is protecting throughput — is one design mistake
  away from winning the argument that the world should think less.
  Per-domain budgets are the structural defence (a MACHINE bid never
  competes for the WORLD channel; it sets the frame the WORLD channel
  arbitrates within), and it must be verified as a real property, not
  assumed. If a future measurement shows world cognition falling as
  MACHINE-domain activity rises, the domain boundary has leaked.
- **Learned bid gains could collapse into self-reinforcing starvation
  (§3.3).** A specialist that never wins could learn to bid ever lower
  and never win again. The staleness term is deliberately excluded from
  learning for exactly this reason, and B7's own test checks it — but
  this is the subtlest failure mode in the whole arbitration design and
  deserves a live-diagnostic check, not only a unit test.
- **The Machine could leak into the fiction (§3.2).** An OBSERVER- or
  MACHINE-domain broadcast reaching a WORLD-domain specialist would let
  a settlement form beliefs about scheduling, or let Phase G material
  surface where it must not. The cross-domain rule is the defence and
  is mechanically checkable; it must be checked, because a convention
  here would erode.
- **This is a large reframe of a working system.** It must land the way
  everything else here lands: incrementally, one subsystem at a time,
  verified, never big-bang.

---

## 9. Relationship to existing documents

- **`CONSTITUTION.md`** — unchanged and still supreme on priorities.
  HCA is a *means* to its top priority (emergence), not a competitor.
- **`CLAUDE.md`** — gains a standing HCA section and the three-surface
  UI amendment (§6.1). The Body/Mind pillar framing is untouched.
- **`ROADMAP-2026-07-REMAINING.md`** — gains Tier 7; Tiers 5 and 6
  re-scoped as its substrate (§7.1).
- **`ML-ARCHITECTURE-2026-08-01.md`** — unchanged; its four layers
  become HCA's cheap-resolver tier, and its **L5/L6 are now the
  direct, load-bearing implementation of L1 `learn()`** (§2.5a), not
  just adjacent substrate — the strongest coupling between the two
  documents anywhere in this filing.
- **`HEARTHBENCH-RUNTIME-2026-07-23.md`** — the *document* is unchanged
  (it is a filed user-uploaded spec and stays verbatim, same convention
  as `MASTERCHECKLIST-2026-07-22.md`), but its **role is amended**: as
  of §3.2, Part B's Adaptive Runtime is not only the workspace's
  execution substrate — it is itself a **mind**, in the MACHINE domain,
  with B8/B5/B15/B13 already supplying four of the five L1 methods.
  B0's prime invariant is untouched and in fact reinforced: a MACHINE
  specialist reasons about *when/where/how* work executes and can never
  write world state.
- **`MASTERCHECKLIST-2026-07-22.md`** — unchanged; its Body items are
  Layer 0, its Mind items are Layers 1–5.
- **`VISION-2026-07-24-LIVINGMAP.md`** — unchanged; the surprise
  overlay (A3) is a new Living Map layer meeting its own bar.

---

*Nothing in this document has been implemented. Per the standing
convention for every vision document in this repository, work from it
only on explicit future direction naming a specific item.*
