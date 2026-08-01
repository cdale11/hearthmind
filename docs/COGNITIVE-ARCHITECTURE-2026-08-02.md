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

**It does change** four things, each justified in §3:

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
 ├─ L3  GLOBAL WORKSPACE  one serial winner per cycle → BROADCAST to all
 │                       ▲ bids (coalitions, carrying salience)
 ├─ L2  WORKING MEMORY ── small, bounded, activation-ranked (ACT-R)
 │                       ▲ prediction errors only
 ├─ L1  SPECIALISTS ───── many, parallel, cheap, always-on.
 │                       predict() / observe() / error() / bid()
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
uniform four-method interface:

```
predict()  → what this specialist expects next (cheap forward model, EMA)
observe()  → what actually happened
error()    → precision-weighted surprise: |actual − predicted| / (σ + ε)
bid()      → a coalition proposal, carrying salience, or nothing
```

**A specialist never calls the LLM.** It bids. This single rule is what
converts ~55 independent racing call sites into one arbitrated system,
and it is the mechanical content of "the LLM is one subsystem."

Most specialists will bid essentially never — which is correct, and is
the fix for §1.3.

### Layer 2 — Working memory

Small, bounded, shared, **activation-ranked** by the ACT-R equation of
§2.5 rather than by recency or insertion order. `Pillar.working_memory`
is already this structure with a weaker ranking rule; agents get the
same treatment via `retrieve_relevant_memories`.

Only prediction errors that clear a precision-weighted threshold enter.
This is the filter that stops the Humans pillar remembering forty
consecutive instances of hungry people foraging.

### Layer 3 — The Global Workspace

One serial channel. Per cognitive cycle:

1. Collect all coalition bids.
2. Score: `salience = w₁·surprise + w₂·urgency + w₃·staleness +
   w₄·goal_relevance`, all precision-weighted.
3. **One winner.**
4. **Broadcast the winner to every subscribed subsystem**, attenuated
   by relevance — not just back to the bidder.
5. Log the full competition: winner, losers, scores, and reason.

Two properties do the real work:

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

**Starvation guarantee.** Every subsystem holds a guaranteed minimum
share of workspace access across a window (B2.2's bounded-deferral
mechanism, reused as-is). This is what fixes §1.2: a system that has
never run accrues unbounded staleness and must eventually win.

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

---

## 4. How existing systems re-map (almost nothing is discarded)

The strongest argument for this direction is that Tier 5 already built
most of the machinery a global workspace needs — it simply had no
client. Every Tier 5 entry in `CLAUDE.md` ends with some variant of
*"not wired into any real control point."* Tier 7 is the client.

| Existing | HCA role | Fit |
|---|---|---|
| B1 `TaskRegistry` (declared reads/writes) | specialist interface + dependency graph | direct |
| B2 `Scheduler` (priority, budgets, bounded deferral) | workspace arbitration + starvation floor | direct |
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
| Tier 6 L2.1 value head | salience/consequence estimation | direct |
| Tier 6 L2.2 policy | the cheap resolver tier | direct |
| Tier 6 L1.1 embedding | semantic-pointer space (§2.6) | direct |
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
  scores. Watching the losers is most of the insight.
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

**Stage E — The Observatory**
- **E1** The "why reasoning was invoked" panel. *Test:* every cycle in
  a live run has a legible one-line reason.
- **E2** Workspace + losing-coalitions panel.
- **E3** Memory activation and competing-goals panels.
- **E4** The learning chart (§8's metric, live).

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
  become HCA's cheap-resolver tier. The two documents compose.
- **`HEARTHBENCH-RUNTIME-2026-07-23.md`** — unchanged; Part B is the
  workspace's execution substrate (§4).
- **`MASTERCHECKLIST-2026-07-22.md`** — unchanged; its Body items are
  Layer 0, its Mind items are Layers 1–5.
- **`VISION-2026-07-24-LIVINGMAP.md`** — unchanged; the surprise
  overlay (A3) is a new Living Map layer meeting its own bar.

---

*Nothing in this document has been implemented. Per the standing
convention for every vision document in this repository, work from it
only on explicit future direction naming a specific item.*
