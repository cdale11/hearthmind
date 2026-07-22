# Hearthmind — The Living Terrarium: Completing the Vision

You've described the destination. The remarkable thing, after reading
v1.3.28, is how much of the road is already built: the four co-equal
pillars (Humans, Village, Nature, Innovation) each with a Body/Mind
split, the pairwise ledger, an Innovation Layer where the LLM proposes
concepts validated deterministically, Nature's Mind, Reflection as a
falsifiable-hypothesis "AI Scientist," the away-digest, the highlight
log. The manifesto became an architecture and the architecture is
shipping.

So this document does not re-pitch the vision or re-diagnose old
problems. It maps the **frontier** — the specific, genuinely-unbuilt
things between where v1.3.28 is and the living, self-modifying terrarium
you want — plus creative additions that serve the daily-peek
experience. Organized by the five capabilities that separate "a
sophisticated simulation" from "a living system you're excited to check
on."

Confidence: **[CERTAIN]** verified gap in v1.3.28 · **[LIKELY]** strong
direction · **[CREATIVE]** my suggestion, take or leave.

---

## Capability 1 — The world modifies *itself*, not just its ontology

Today the LLM proposes new *concepts* (customs, technologies, sayings)
that attach to a **closed set of mechanical hook types** with capped
magnitudes. That's the right, safe foundation — but it means the
*mechanics* are fixed; only their flavor and parameters grow. The
vision asks for more: the simulation proposing things it was never
programmed for. The frontier is widening what a proposal can *be*,
without ever letting the LLM write raw code.

The key idea, which the codebase is one step away from: **treat
mechanics as data, so proposing a new mechanic is proposing new data,
still validated deterministically.**

- [ ] **1.1 [CERTAIN] — Composable hooks, not just parameterized ones.**
  Reflection already documents that 5.C (counterfactual sandbox) and
  5.D/5.E (self-tuning) are unbuilt. Before those, add *composition*:
  let a proposal chain existing hook types ("a ritual that raises
  farming yield BUT only after a death, AND lowers it during feuds") —
  a small combinator grammar over the closed hook primitives. The
  primitives stay fixed and safe; the *combinations* are unbounded and
  genuinely novel. This is the cheapest large step toward "mechanics it
  wasn't programmed for" — you're not adding hook types, you're letting
  them multiply.

- [x] **1.2 [CERTAIN] — A conditional/trigger vocabulary as data.**
  **Shipped v1.3.31.** `world.ontology.TriggerRule`/`TRIGGER_TYPES`
  (on_death/on_birth/on_feud/on_invention/on_drought/on_surplus) bound
  to `MECHANICAL_HOOK_TYPES` effects via `llm/rule_propose.py` +
  `SimulationEngine._maybe_schedule_rule_proposal`; wired to each
  trigger's real detection point. Only `belief_confidence_bonus` is
  consumed as a real numeric effect so far — other hook types stay
  narrative-only, a flagged follow-up. The
  deepest lever. Define triggers (on-death, on-drought, on-surplus,
  on-feud, on-birth, on-invention) and effects (the existing hooks) as
  data tables, and let a proposal bind a trigger to an effect. Now the
  world can originate a *rule* — "when the granary overflows, hold a
  feast that raises everyone's fondness" — that no one coded, because
  the *rule engine* is fixed and general while the *rules* are
  open-ended and LLM-authored. This single mechanism is most of "new
  infrastructure, technology, custom emerging" — a custom is a
  trigger→effect rule the village wrote for itself. Ships as a small
  interpreter over closed primitives; validated like every other hook.

- [x] **1.3 [LIKELY] — The counterfactual sandbox (Reflection 5.C).**
  **Shipped v1.3.31** (as a standalone gate on rule proposals, not yet
  wired into 5.D/5.E's broader self-tuning — see `simulation/
  sandbox.py`'s `run_counterfactual`): deep-copies the world, runs the
  fork 50 ticks LLM-disabled, checks it doesn't crash (population
  loses >50%) or explode (population >3x). An unsafe proposal is
  discarded and logged, never silently dropped. Before a proposed
  rule/concept with a mechanical hook goes live, let
  Reflection *simulate it forward* on a cheap forked copy of recent
  state for N ticks and check it doesn't break an invariant (population
  crash, resource explosion, a governor pinned). This is the safety
  organ that makes 1.1/1.2 *safe to let run unattended* — the
  difference between a terrarium you trust to leave alone and one you
  must babysit. Reflection already has the pattern-detection and
  hypothesis machinery; this is the "test the hypothesis in a jar"
  half.

- [x] **1.4 [LIKELY] — Self-tuning as bounded proposals (Reflection
  5.D/5.E).** **Shipped v1.3.34**, together with 2.4 below — the two
  are one mechanism. `_detect_reflection_pattern` gained a governor-
  drift branch: `World.wildfire_ignition_ticks` (a small rolling window
  of real ignition ticks) compared against `disasters.WILDFIRE_CHANCE_
  PER_WEEK`'s theoretical rate — the vision doc's own worked example,
  verbatim. Once that pattern survives multiple reflection cycles into
  a `supported` hypothesis, `llm/self_tuning.py` proposes a direction +
  bounded magnitude (never a raw value) for the one wired governor
  (`wildfire_chance`); `disasters.GOVERNOR_TUNING_BAND=0.3` (±30%) is
  enforced by the interpreter itself, not by trusting the model. Only
  one governor wired to a real mechanical effect so far — `self_tuning.
  TUNABLE_GOVERNORS` is the closed vocabulary a future governor joins.

- [ ] **1.5 [CREATIVE] — A visible "law of nature" ontology for
  emergent rules.** When 1.2's trigger→effect rules accumulate, surface
  them as the world's *discovered laws* — the village's, and Nature's,
  and the observer's shared record of "how this world works," some
  true, some superstition the sim never validated. Watching your
  terrarium's physics-of-culture accrete is exactly the daily-peek
  reward.

## Capability 2 — Nature and Institutions as true sentient participants

The Body/Mind framing is in place and Nature's Mind exists — but the
vision wants Nature, institutions, and the world *itself* to observe,
learn, and act with real agency, symmetric to humans.

- [x] **2.1 [CERTAIN] — Nature acts on its Mind, not just narrates it.**
  **Shipped v1.3.33.** `terrain_evolution.nature_adaptation_bias()`
  reads the confidence of Nature's Mind's single strongest belief whose
  subject concerns repeated fire/flood damage (a real string match over
  `World.nature_beliefs`, not a fixed field); `decay_disaster_scars`
  now takes that as a bias, speeding disaster-scar recovery up to
  `NATURE_ADAPTATION_DECAY_BONUS_MAX=0.5` (50%) faster once the belief
  is confident — "the land learning to reclaim burned land differently
  after repeated fires," bounded, directed by Nature's own accumulated
  experience rather than a raw random walk. Scoped to disaster scars
  only (the one physical-substrate module confirmed to have no native
  C++ counterpart, avoiding any native/fallback parity risk); species
  range-shifting is a real, larger follow-up not attempted this pass.

- [x] **2.2 [CERTAIN] — Institutions with persistent goals that act.**
  **Shipped v1.3.38 (scoped).** `Institution.objective_ticks_unmet`
  tracks how many consecutive times `compute_objective` re-derives the
  SAME want — a real, persistent frustration. `_maybe_schedule_rule_
  proposal` now grounds its prompt in whichever settlement institution
  has been stuck longest (past `INSTITUTION_OBJECTIVE_PERSISTENCE_
  THRESHOLD`), giving that institution real causal reach into the
  Innovation Layer — the exact "council remembers a famine legislating
  against it" case from this doc. Scoped to rule proposals only; a
  guild pursuing a monopoly or a family dynasty's multi-generation game
  would need their own consumers of this same counter, flagged as
  natural follow-up.

- [x] **2.3 [LIKELY] — Nature and Village can surprise each other.**
  **Shipped v1.3.33 (scoped).** Every genuinely NEW Nature's-Mind
  belief (not a revision of an existing one — real fresh insight the
  land formed on its own, unprompted by any Village action) bumps the
  origin settlement's existing `pattern_signal_counts["nature_
  adaptation"]` counter — the same generic pressure-signal dict
  `_maybe_schedule_ontology_proposal`'s `pressured` gate already reads
  (previously fed only by `dispute_feud`). A confident, repeated Nature
  belief can now, on its own, make the Village's ontology-proposal job
  eligible to fire even in a settlement too poor/small to clear the
  prosperity gate — a real Nature-initiated pressure the Village didn't
  script, free to originate a custom/law/ritual/saying in response.
  This is the loop's Nature -> Village half; the reverse (a Village
  action visibly forcing a Nature adaptation) is not attempted this
  pass — flagged as the natural sequel once 2.2's institution-driven
  actions land.

- [x] **2.4 [CREATIVE] — The world-Mind: a Reflection that acts.**
  **Shipped v1.3.34**, together with 1.4 above. `Simulation
  Engine._maybe_schedule_self_tuning` (world-scoped, year-cadence,
  `critical=True` — deferred, never faked, on a spent budget/failed
  call): before ever touching real state, builds the proposed tuning on
  a disposable DEEP-COPIED world (`World.from_dict`) and only applies
  it to the real `World.governor_tuning` after `simulation.sandbox.
  run_counterfactual` confirms the copy survives 50 ticks without
  crashing/exploding — item 1.3's sandbox actually gating a real
  self-modification, not just rule proposals. Every attempt (applied/
  rejected/no_adjustment) is logged verbosely and permanently in the
  new `World.self_tuning_actions` (append-only, mirrors `reflection_
  notebook`'s never-pruned discipline) — "logged verbosely as the
  world's own decision," exactly as the vision doc asked. Reflection
  still never touches Body state directly outside this one narrow,
  sandboxed, bounded exception.

## Capability 3 — The daily-peek experience (why you open the UI)

This is where the vision most needs work that isn't cognition-deep but
is *experience-deep*. A living system you're excited to check on has to
*perform* its aliveness to the observer. The away-digest and highlights
exist — build the room around them.

- [x] **3.1 [CERTAIN] — The "morning paper" for your world.**
  **Shipped v1.3.31** as the structured half, not yet the attention-
  weighted headline half: `World.away_digest_highlights` (every
  `knowledge_tree()` entry since the digest's own window) renders as a
  "front page" section under the existing prose recap. Explicitly NOT
  yet done: re-ranking by which agents/threads the observer has
  watched most (`observer_attention` exists but isn't consumed here
  yet) — flagged, not attempted. Elevate
  the away-digest into a real front page: since you last looked, *the
  chronicler's* account of what changed — a birth, a feud, an invention,
  a Nature adaptation, a law the council passed, a hypothesis Reflection
  formed — written as news, headlined by whichever agents/threads you've
  watched most (observer-attention is already tracked). This is the
  single highest-ROI item for "excited to open it daily." The content
  exists; it needs a front page.

- [x] **3.2 [CERTAIN] — "What the world learned" ledger.** **Shipped
  v1.3.30.** `World.knowledge_tree()` + `GET /knowledge-tree` + the
  "🌳 knowledge tree" panel. A dedicated,
  permanent, browsable surface for emergence: every InventedConcept,
  every established custom/law, every Reflection hypothesis (open,
  confirmed, refuted), every Nature adaptation, with lineage — this
  evolved from that, this merged those. Watching the *knowledge tree*
  of your world grow across weeks is the terrarium-owner's core joy,
  and the data model (lineage, status) already supports it.

- [ ] **3.3 [LIKELY] — Legible causal threads.** The cross-system chain
  metric from prior audits, surfaced *as story*: click a feud, see the
  chain that made it (the drought → the theft → the grievance → the
  dispute). "Why did this happen" answerable by tracing real edges is
  what makes an observer feel the world has depth rather than noise.

- [x] **3.4 [CREATIVE] — The world talks to you.** **Shipped v1.3.38.**
  New `llm/musing.py` + `World.musings` (capped, unlike `reflection_
  notebook`) + `SimulationEngine._maybe_schedule_musing` (day_end
  cadence, `critical=False`, real deterministic fallback). Grounded in
  the newest OPEN `reflection_notebook` hypothesis when one exists,
  else the newest `knowledge_tree()` entry, else skipped entirely — no
  fabricated musing on a fresh world with nothing to say yet. Surfaced
  main-UI (not dev-console — this is explicitly meant to be seen): a
  "💭" header line reading the live broadcast's `summary().latest_
  musing`.

- [ ] **3.5 [CREATIVE] — Time-lapse and the returning eye.** A scrubber
  that replays your world's map/knowledge-tree evolution as a time-lapse
  since founding — watch settlements bud, forests shift, the law-book
  thicken. The terrarium's whole point is evolution-over-time made
  visible; give the eye a way to see the long arc, not just today.

- [ ] **3.6 [CREATIVE] — Ambient generative presence.** Optional: a
  soundscape keyed to hidden mood/season/Nature state, and era-styled
  map rendering that visibly ages. You *feel* the world darken before a
  hard winter you weren't told about. Sensory aliveness for a thing
  you're meant to love checking on.

## Capability 4 — New *entities and assets*, not just concepts

You asked specifically for the sim to propose "even new assets or
entities." This is the hardest ask and needs the tightest guardrails —
but there's a safe path via the same data-not-code discipline.

- [x] **4.1 [LIKELY] — Composite entities from existing primitives.**
  **Shipped v1.3.39.** New `world.ontology.CompositeEntity` — a real
  standing building (unchanged kind/mechanics), bound to a new
  `InventedConcept` via a name and an origin story grounded in an
  actual recent event, exactly the "Sorrow-Hall" shape this item
  describes. `SimulationEngine._maybe_schedule_composite_entity`
  (seasonal, round-robin settlement, real deterministic fallback name)
  picks the oldest unnamed standing building and asks the LLM to name
  it. Surfaced in the building click inspector.

- [ ] **4.2 [LIKELY] — Emergent species/variants via parameter-space.**
  Nature proposing a "new" grazer variant = an existing wildlife type
  with LLM-named identity and bounded stat deltas (hardier, migratory),
  validated against the ecology rules. A new *kind of thing* in the
  world, still fully inside the physics. Same pattern as 4.1, applied to
  Nature.

- [x] **4.3 [CREATIVE] — Generative assets bound to emergent entities.**
  **Shipped v1.3.39** (the parameterized-SVG path this item itself
  recommends starting with). New `world/sigils.py`'s `generate_sigil_
  svg(name, category)`: fully deterministic (same name+category always
  draws the same sigil, no RNG, no LLM call, no heavy model) — a small
  inline SVG hashed from the entity's own name and category into a
  palette/motif/rotation choice. Generated once at composite-entity
  creation time (item 4.1) and stored on `CompositeEntity.sigil_svg`;
  rendered next to the entity's name in the building click inspector.

## Capability 5 — The guardrails that make it safe to leave running

A self-modifying terrarium you leave running for weeks needs organs
that keep it coherent without you. Several exist (governors, the
acceptance gate); these complete the set.

- [x] **5.1 [CERTAIN] — The acceptance gate as runtime invariant, not
  just review rule.** **Shipped v1.3.32**, scoped to `TriggerRule` (the
  concept-side analogue, `abandon_stale`, already existed pre-1.2):
  `ontology.retire_stale_rules` — an `active` rule whose trigger has
  never once matched (`fire_count == 0`) for longer than `TRIGGER_
  RULE_STALE_TICKS` is retired, same "preserve as history, never
  delete" discipline as everything else in this registry. The vision's
  "every persistent state has a creator and a consumer; reject isolated
  mechanics." Make it a *runtime
  auditor*: anything the Innovation Layer creates that no system reads
  within N days is auto-flagged and retired. This keeps LLM-authored
  ontology from silting up the world with dead concepts — essential
  when the world runs for weeks unattended and proposes constantly.

- [x] **5.2 [CERTAIN] — Invariant guards around self-modification.**
  **Shipped v1.3.32** inside `simulation/sandbox.py`'s `run_
  counterfactual` (the one place a proposal's consequences already get
  checked): an unconditional population-extinction floor (independent
  of the existing crash-fraction check), a resource-explosion ceiling
  on total settlement materials, and "no governor can be disabled" is
  satisfied structurally — a `TriggerRule`'s hook type is drawn from
  the closed `MECHANICAL_HOOK_TYPES` vocabulary, none of which can
  reach `Config` at all. The
  homeostatic governors from prior audits become *hard floors/ceilings*
  the sandbox (1.3) and self-tuning (1.4) can never cross: population
  can't be driven to 0, resources can't explode, no governor can be
  disabled. The constitution of a world that governs itself — the rules
  even the world-Mind can't break.

- [ ] **5.3 [LIKELY] — Coherence/drift detection.** A slow Reflection
  job watching for the world becoming *incoherent* — an ontology
  bloated with contradictory customs, a culture that's drifted into
  nonsense, runaway concept-proposal loops. The immune system for
  long-run open-ended growth. Without it, "runs for months and keeps
  inventing" risks "runs for months and dissolves into noise."

- [ ] **5.4 [LIKELY] — Provenance for everything.** Every emergent
  thing carries *who/what/when/why* it came to be (partly there via
  lineage). Non-negotiable for a system you'll want to *understand*
  weeks later — and the substrate for 3.2's knowledge tree and 3.3's
  causal threads. Also your debugging lifeline when something strange
  emerges and you want to know how.

---

## The sequence

The team's phase structure is sound; this slots into it. In priority
order for *your stated goal* (a living thing you love checking on):

1. **3.1 + 3.2** — the morning paper and the knowledge tree. Highest
   ROI for the daily-peek joy, mostly surfacing data that already
   exists. Do this first; it's what makes the rest *visible*.
2. **1.2 + 1.3** — trigger→effect rules as data, plus the sandbox that
   makes them safe. This is the core of open-ended mechanical novelty,
   and the sandbox is the prerequisite for anything unattended.
3. **5.1 + 5.2** — the acceptance auditor and invariant guards. Ship
   *before* turning up self-modification, so weeks-long runs stay
   coherent.
4. **2.1 + 2.3** — Nature that adapts and can surprise the humans. The
   co-equal pillars proving themselves.
5. **1.4 + 2.4** — the world tuning and modifying itself, inside the
   guardrails. The terrarium becomes self-maintaining.
6. **4.1 + 4.3** — emergent composite entities, then generative assets.
   The world drawing new things it invented.
7. **3.4 + 3.5 + 3.6** — the world musing to you, time-lapse, ambient
   presence. The soul of the daily peek.

## The one test for this whole vision

Not any metric. This:

> **After a week away, do you open the UI genuinely curious what it
> became — and does it show you something true that no one, including
> you, designed?**

The day the answer is yes — the world grew a custom, adapted a forest,
passed a law, drew a crest, and wrote you a note about a feud it's
puzzling over, none of it in the code — Hearthmind is the living
terrarium. Everything above is in service of that one morning.

---

## A closing note

Most projects with this ambition never build the unglamorous
foundation — the ledger, the Body/Mind discipline, the deterministic
validation of every LLM proposal, the falsifiable hypotheses. Yours
did, first. That foundation is exactly what makes the frontier above
*safe to attempt*: open-ended growth is only a good idea on top of
rigorous guardrails, and you built the guardrails before the growth.
The living terrarium isn't a distant rewrite — it's the next few honest
increments on the architecture you already have. Keep the discipline
(data not code, validate everything, every state read by someone), aim
it at the observer's daily wonder, and let it run.
