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

- [ ] **1.4 [LIKELY] — Self-tuning as bounded proposals (Reflection
  5.D/5.E).** Let Reflection propose *adjustments to its own world's
  balance constants* — but only ones expressed as bounded nudges to
  existing governors (the homeostatic bands), never raw values, and
  only after 1.3's sandbox validates them. "Wildfires feel too rare to
  matter; widen the ignition band 10%." The simulation tuning itself,
  inside guardrails. This is "proposes modifications to itself" made
  real and safe.

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

- [ ] **2.1 [CERTAIN] — Nature acts on its Mind, not just narrates it.**
  Verify: Nature's Mind currently interprets ecological state. Close
  the loop so its *understanding changes its Body behavior* within
  physical law — a forest "learning" (via a slow bounded bias) to
  reclaim burned land differently after repeated fires, a species
  shifting range toward where it survived. Not magic: bounded
  adaptation the ecology rules permit, but *directed by* Nature's
  accumulated experience rather than pure random walk. Nature that
  remembers what happened to it and adapts is the difference between
  scenery and a participant.

- [ ] **2.2 [CERTAIN] — Institutions with persistent goals that act.**
  Institution objectives exist; ensure they *drive* — a council that
  remembers a famine legislating against it (via 1.2's rule
  proposals!), a guild pursuing a monopoly, a family dynasty playing a
  multi-generation game. Institutions should be able to author customs/
  laws through the Innovation Layer, giving them a real will that
  outlives members.

- [ ] **2.3 [LIKELY] — Nature and Village can surprise each other.** The
  manifesto's co-equal test: a Nature adaptation (2.1) the humans
  didn't cause should force a human/village response (migrate, invent,
  ritualize), and vice-versa. One concrete cross-pillar loop where
  neither side scripted the other is worth more than ten isolated
  deepenings — it's the proof the pillars are actually interdependent.

- [ ] **2.4 [CREATIVE] — The world-Mind: a Reflection that acts.**
  Today Reflection observes and hypothesizes but "never touches Body."
  Consider a narrow, sacred exception downstream of the sandbox (1.3):
  Reflection may enact *one* validated self-tuning proposal per long
  period, logged verbosely as the world's own decision. This is the
  simulator itself becoming the fifth sentient agent — the terrarium
  that doesn't just get maintained, but maintains itself, and tells you
  it did.

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

- [ ] **3.4 [CREATIVE] — The world talks to you.** A once-a-day line
  from the simulation itself (Reflection's voice) — "I've been noticing
  the eastern families never intermarry; I wonder if the old feud
  outlives everyone who remembers it." Not a stat, a *musing*. The
  terrarium acknowledging its observer, sharing what it's puzzling over.
  One LLM call a day, enormous presence.

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

- [ ] **4.1 [LIKELY] — Composite entities from existing primitives.** A
  new "entity" need not be new code — it can be a *named, persistent
  composite* of existing primitives: a new building "kind" that is
  mechanically a known kind + an InventedConcept hook + a place-name +
  an origin story (the "Sorrow-Hall," mechanically a memorial with a
  grief-decay hook, born of a specific plague). New to the world, novel
  to the observer, structurally just composition. This is how "new
  infrastructure it wasn't programmed for" ships safely.

- [ ] **4.2 [LIKELY] — Emergent species/variants via parameter-space.**
  Nature proposing a "new" grazer variant = an existing wildlife type
  with LLM-named identity and bounded stat deltas (hardier, migratory),
  validated against the ecology rules. A new *kind of thing* in the
  world, still fully inside the physics. Same pattern as 4.1, applied to
  Nature.

- [ ] **4.3 [CREATIVE] — Generative assets bound to emergent entities.**
  The genuinely futuristic slice: when 4.1/4.2 create a novel entity,
  generate its *representation* to match — an SVG sigil for a new
  institution, a procedural icon for a new building, a generated crest
  for a dynasty, from a local image/vector model or even parameterized
  SVG templates (no heavy model needed). Your terrarium literally
  *drawing new things it invented*. Start with parameterized SVG
  (cheap, deterministic, on-brand with the diagram tooling); graduate to
  a local generative model if you want. Nothing makes "it made something
  new" land harder than *seeing* the new thing.

## Capability 5 — The guardrails that make it safe to leave running

A self-modifying terrarium you leave running for weeks needs organs
that keep it coherent without you. Several exist (governors, the
acceptance gate); these complete the set.

- [ ] **5.1 [CERTAIN] — The acceptance gate as runtime invariant, not
  just review rule.** The vision's "every persistent state has a creator
  and a consumer; reject isolated mechanics." Make it a *runtime
  auditor*: anything the Innovation Layer creates that no system reads
  within N days is auto-flagged and retired. This keeps LLM-authored
  ontology from silting up the world with dead concepts — essential
  when the world runs for weeks unattended and proposes constantly.

- [ ] **5.2 [CERTAIN] — Invariant guards around self-modification.** The
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
