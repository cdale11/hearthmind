# The Self-Evolving World — Architecture & Roadmap (v1.1, 2026-07-21)

Explicit user directive, 2026-07-21: Hearthmind's objective is not to
simulate a predefined world, but to build a **self-evolving world**
where **Humans, Village, Nature, and Innovation** continuously reshape
one another, expanding the world's ontology and future possibilities
while remaining internally coherent. Synthesized from a user-supplied
checklist manifesto (~150 bullets) into a dependency-ordered,
codebase-grounded roadmap. This is a design doc, not a shipped
changelog entry — no code changes in this pass; held uncommitted per
explicit user instruction until Phase 0 code lands.

**v1.1 revision note**: v1 structured this as "Phase 1: Innovation
Layer" followed by "Phase 3/4/5: Human/Village/Nature emergence" —
explicit user correction: that reads as Innovation being the special
new pillar with the other three deferred, when the whole point is that
**all four are co-equal and simultaneously interdependent**, not a
sequence. Restructured below: Phase 1 gives all four pillars their
first real slice *together* (including a genuine cross-pillar wire,
not four isolated slivers), Phase 3 deepens all four together a second
time, rather than pillar-by-pillar phases.

**Relationship to `docs/archive/DEFINITIVECHECKLIST-2026-07-21.md`**: explicit
user instruction — **additional layer, not a replacement**. That
checklist's still-open Tiers (1 ledger, 2.1/2.3, 3-7) are largely
*prerequisite infrastructure* this vision consumes rather than a
competing track: the pairwise ledger Tier 1 asks for is exactly what
"dialogue creates promises/debts/favours" below needs to write to;
Tier 3's wants-drive-goals is exactly "give every NPC one long-term
goal... goals influence planning" below. Where the two documents name
the same mechanism, this doc treats the checklist's item as already
scoped and doesn't re-litigate it — it says so and moves on.

**Scope confirmation from the user**: ontology expansion is "a mix of
genuinely open-ended and some bounded expansion slots" — the Innovation
work below is designed around that split explicitly (see "Why not a
fully open schema" under Phase 1.A).

**v1.2 revision note (2026-07-21, later same day) — Body/Mind framing,
explicit user correction.** Prior wording in this doc and in chat
described the LLM as a "layer" added on top of deterministic
simulation ("simulation + optional LLM enhancement"). Corrected
framing, standing going forward: every major system — each of the four
pillars — is **one system with two inseparable parts**, not a
simulation with cognition bolted on:

- **Body (deterministic)**: owns objective reality for that pillar.
  Always authoritative; the LLM never invents or overrides an objective
  fact. Physics, ecology, weather, economy, relationships (the ledger),
  construction, pathfinding, resources, time.
- **Mind (LLM)**: owns *subjective understanding* of that pillar's
  reality — perception, memory interpretation, belief formation, goal
  reasoning, planning, social/cultural interpretation, concept
  invention, long-term abstraction. Not decoration or post-processing —
  this *is* the pillar's cognition.

So: Humans -> human cognition, Village -> collective cognition, Nature
-> ecological cognition, Innovation -> conceptual cognition. Every
pillar should eventually have both halves; a pillar whose Mind half is
thin (Nature today — deterministic ecology/weather/wildlife with
almost no LLM interpretation layer) is *incomplete*, not "correctly
mostly-deterministic by design." This reframes several already-shipped
mechanisms as a pillar's Mind half rather than a bolt-on: `Settlement.
beliefs`/`town_brain` (Village's mind), per-agent cognition/`Agent.
mind`/personal beliefs (Human's mind — currently core-cast-gated, not
whole-population, by the call-budget rule below), `llm/ontology.py`'s
propose/evolve/merge (Innovation's mind). Nature's mind is the
identified gap — see Phase 3.E below for the follow-up that closed it.

**Reflection is not a fifth pillar.** It's the meta-cognitive system
observing all four Minds — detecting long-term patterns across them,
forming hypotheses, running counterfactuals, maintaining a scientific
notebook, and improving *how* the four Minds reason over time. It
never touches Body state directly and never invents objective facts;
it studies and improves cognition, one level up from the four pillars.

This doesn't change any standing engineering constraint — the LLM-
call-budget gating (core cast, daily ceiling, `critical`-vs-fallback
scheduling per docs/CONSTITUTION.md) still bounds how much of a
pillar's Mind runs on any given tick; "every pillar needs a Mind" is a
completeness target for what genuinely warrants an LLM call, not
license to remove the gating. When implementing a pillar feature going
forward, frame it as **Body (objective state) <-> Mind (subjective
cognition)** for that pillar, not "simulation + optional LLM
enhancement."

---

## Reading the manifesto as one architecture, not five checklists

Stripped of repetition, the ~150 bullets reduce to five real claims:

1. **Four autonomous, co-equal participants — none merely supports
   another.** Humans, Village, Nature, Innovation each need their own
   persistent state/memory/dynamics *and* every one of them must be
   legible to (and alterable by) the other three, symmetrically. Today:
   Humans and Village are reasonably autonomous (Settlement/Population
   are real objects with real state); Nature is autonomous physically
   but has near-zero human-facing legibility (the prior checklist's
   unshipped N1); Innovation barely exists as a participant at all —
   `llm/invention.py` fires one closed-category roll a season and
   produces a flat `tech_level += 1`, nothing more. **The roadmap below
   deliberately advances all four together each phase rather than
   finishing one pillar before starting the next** — a world where
   Innovation is sophisticated but Nature still can't touch a human
   would be exactly the "one system propping up another" failure mode
   the manifesto rejects.
2. **Innovation is specifically the ontology-expansion mechanism**,
   not a fourth thing bolted alongside the other three. A system where
   the LLM can add real new *kinds of thing* to the world during play,
   validated and persisted, doesn't exist anywhere in the codebase —
   this is the one genuinely novel architectural piece in the whole
   manifesto. But most of what makes it matter is how the OTHER three
   pillars consume it (villages developing distinct customs/laws/
   rituals via it, humans inventing tools via it, nature developing
   new equilibria the humans then have to react to) — so it ships
   alongside Human/Village/Nature work each phase, not before it.
3. **Persistence-by-default, decay-by-exception.** Same direction as
   the prior checklist's Tier 0, generalized past interpersonal state
   to disasters/landscape/village identity: significant state gets
   *resolved*, not faded.
4. **Dialogue stops being an LLM-narrated snapshot and becomes a
   simulation event with hidden state and mechanical write-backs.**
   The single most concretely-scoped rewrite in the manifesto —
   deliberately its own phase since it's genuinely cross-cutting
   (touches Humans directly, Village indirectly through institutions/
   reputation) rather than belonging to one pillar.
5. **A literal acceptance gate** ("every persistent state has a
   creator and a consumer," "reject isolated mechanics," "reject state
   no other system observes") — this is a review checklist for every
   future feature in this project, human or LLM-authored. It gets
   folded into CLAUDE.md's workflow rules once Phase 0 ships, not
   treated as a one-time checkbox.

---

## Phase 0 — Shared substrate (prerequisite, mostly already scoped)

**Status: SHIPPED, v1.3.18.** `agents/ledger.py` — see CHANGELOG.md's
[1.3.18] entry for the full account, including a real bug the native
soak caught mid-migration (a naive "neutral value means absent" scheme
auto-pruned an edge on an explicit `agent.debts[id] = 0.0` write,
breaking the very next re-read — fixed with a genuine `None` presence
sentinel).

Nothing below is safe to build on top of the current scattered
`relationships`/`trust`/`debts` scalars — the manifesto's own "one
shared relationship ledger used by every interpersonal system" is this
project's Tier 1 from the prior checklist, verbatim. This vision does
not change that scoping — it just makes the ledger's urgency higher,
since Phase 1's inventor/adopter tracking, dialogue's promises/debts,
and every pillar's deepening in Phase 3 all want to write typed edges
onto the same substrate.

**"Make all relationships directional rather than symmetric"**:
already true structurally today — `Agent.relationships`/`Agent.trust`
are each agent's own dict keyed by source id (`a.relationships[b.id]`
and `b.relationships[a.id]` are independent values, not a shared
symmetric edge). Worth stating explicitly so the ledger migration
*preserves* this rather than accidentally collapsing it into one
shared bidirectional edge for storage convenience.

**Deliverable**: `agents/ledger.py` — one typed pairwise entry per
(observer_id, subject_id): fondness, trust, debt/favor amount,
`relationship_flags` (from v1.3.17, reused not replaced), tagged
grievances (from v1.3.17, reused not replaced), a new bounded
`promises: list[dict]` (Phase 2 needs this), `history_tags: set[str]`
for cheap "have these two ever X'd" checks. Every interpersonal
consumer (`theft`, `trade`, `dialogue`, `dispute`, `seek_person`,
teaching, courtship, inheritance) migrates to read/write through it.
Given the size, this ships as its own dedicated pass — audit each
consumer, migrate one at a time, verify after each, not a single
big-bang rewrite.

---

## Phase 1 — First slice of all four pillars, built together

Each pillar gets its single most load-bearing new mechanism in this
phase — not a token gesture, but scoped narrow enough that four of
them landing together in one batch is realistic. Chosen so that at
least one slice is itself a genuine cross-pillar wire (1.D, Nature →
Human), proving the "co-equal and interdependent" framing from day
one rather than deferring the actual interaction to later.

### 1.A — Innovation: the core proposal → validate → persist pipeline

**Status: SHIPPED, v1.3.19** (elevated to also include evolve/merge —
see explicit user follow-up below — rather than deferring them to
Phase 3.A as originally scoped here). See CHANGELOG.md's [1.3.19]
entry for the full account. Not yet done: full main-UI stat-tile
surfacing (dev-console diagnostics shipped; flagged fast-follow) and
full reuse of `invention_knowledge`'s teach/lose/rediscover lifecycle
for adoption spread (a minimal independent spread step shipped
instead, documented simplification).

**Explicit user follow-up (2026-07-21)**, received after this section
was first written: "invented concepts shouldn't just exist. They
should become building blocks... treated as first-class persistent
entities that any system can discover, reference, reinterpret,
combine, mutate, and build upon indefinitely." This confirmed/
sharpened the design below rather than changing it — the `lineage`
field and "parents are never destroyed" discipline were already
planned for Phase 3.A; the change is that evolve/merge ship NOW,
alongside propose, not later.

The manifesto's genuinely novel architectural ask, and the one that
needed the most design work up front.

**Why not a fully open schema.** `BuildingKind`/`AgentGoal`/
`InstitutionKind`/`SkillId` etc. are Python enums, several mirrored
into the C++ native store's integer code tables (`agent_table.cpp`'s
goal codes, `AgentStore`'s dense columns). A literal "the LLM adds a
new enum member at runtime" is not just risky, it's close to
structurally impossible without a native-store schema migration
mid-run — not worth attempting. The user's own answer ("a mix of
genuinely open-ended and some bounded expansion slots") gives the
right shape instead:

- **Bounded expansion slots**: the existing closed-enum systems keep
  their fixed mechanical categories — building/goal/institution kinds
  don't change — but **host open-ended content**: an invention's NAME,
  DESCRIPTION, flavor, and which of a small set of *mechanical hook
  types* it attaches to are LLM-authored and genuinely unbounded. This
  is exactly the pattern `era_branch.py` (closed branch names, open
  building-mix bias) and `invention.py` (closed category enum, open
  name/description) already established — Phase 1.A generalizes it
  into the load-bearing mechanism instead of one narrow job.
- **The open-ended half**: an invented concept is itself a first-class,
  freely-shaped simulation object (not one of a fixed enum) that
  persists, spreads, mutates, and gets referenced by later cognition/
  dialogue/culture — the ontology genuinely grows even though the
  mechanical vocabulary it's built from stays closed.

**New persistent object: `InventedConcept`** — `world/ontology.py`
(new), `World.invented_concepts: dict[int, dict]` (shared across
settlements — an idea can spread beyond its origin, same "ideas aren't
settlement-private" reasoning `roads`' paving tier already
established):

```
id, name, description,          # LLM-authored, free text
category,                        # CLOSED enum: technology | custom | law
                                  #   | ritual | saying | profession
                                  #   | institution_flavor | ecological
origin_settlement_id, tick_invented, inventor_agent_id,
status,                          # proposed -> spreading -> established
                                  #   -> abandoned | merged | evolved
mechanical_hook: dict | None,    # see below — None is valid (pure flavor)
adopter_ids: set[int],           # bounded, see MAX_CONCEPT_ADOPTERS_STORED
lineage: {"evolved_from": id | None, "merged_from": [id, id] | None},
```

**`mechanical_hook`** is the bounded-slot half: a small closed set of
hook *types* (`skill_yield_bonus`, `building_kind_flavor_of:<existing
kind>`, `goal_flavor_bias`, `belief_confidence_bonus`,
`invention_specialization_category` (reuses v1.2.0's existing
`INVENTION_CATEGORIES` mechanism directly), `custom_text_only`), each
with a small numeric magnitude capped the same way `INVENTION_
SPECIALIZATION_CAP` already caps v1.2.0's invention bonuses. An
invented concept with `mechanical_hook=None` is real (persists,
spreads, gets referenced in prompts/culture) but has zero numeric
effect — pure texture, same tier as folklore/omens. This is
deliberately how "sayings" and most "customs"/"rituals" work — the
manifesto doesn't actually ask every custom to move a number, it asks
every custom to be REAL (persistent, spreadable, historically
referenceable), which `mechanical_hook=None` satisfies honestly
instead of forcing a fabricated numeric effect onto every entry.

**Pipeline** (new `llm/ontology.py`, reusing `llm/invention.py`'s
existing shape rather than replacing it — `invention.py`'s job becomes
ontology.py's `category="technology"` path once this ships):

1. **Trigger**: same seasonal roll `invention.py` already has, plus
   pressure signals per "grounded in existing pressures" — a
   settlement pattern-signal counter crossing threshold (same
   `pattern_signal_counts` mechanism disputes/rituals already use), a
   sustained resource shortage, a repeated dispute pattern, a notable
   ecological event (this is where 1.A reads 1.D's output — see
   below).
2. **Propose**: LLM call returns `{name, description, category,
   mechanical_hook_type, mechanical_hook_target, magnitude}` against a
   JSON schema (FT.0's grammar-constrained decoding applies directly).
3. **Validate** (deterministic, before promotion — never an LLM
   self-check): category reachable at current era/tech_level (reuses
   `ERA_INFRASTRUCTURE_REQUIREMENTS`'s existing gating shape);
   `mechanical_hook_target` must name a real existing skill/building-
   kind/goal; magnitude clamped to the per-hook-type cap; duplicate-
   name check (same Jaccard-overlap pattern folklore's duplicate-tale
   guard uses). A rejected proposal is a genuine "not yet" — logged,
   not silently retried into acceptance.
4. **Persist**: validated proposal becomes an `InventedConcept`,
   `status="proposed"`.
5. **Spread**: reuses the existing knowledge-diffusion mechanism (§7
   item 6, `agents/population.py`) — an invented concept diffuses/is
   lost/is rediscovered through the same substrate skills already do.
   `Phase 1 scope`: technology-category concepts only, spreading via
   this mechanism. Full category coverage (custom/law/ritual/saying/
   profession/institution_flavor/ecological) and evolve/merge are
   Phase 3.A's deepening pass, not this phase's scope — landing all
   seven categories plus spread/evolve/merge at once alongside three
   other pillars' first slices in one batch is not realistic.

**Grounding in future cognition**: once `established`, an
`InventedConcept` becomes reference material — threaded into
`town_brain`/`chronicle`/`beliefs`/`dialogue` prompts the same way
`Settlement.folklore`/`place_names` already are.

### 1.B — Humans: long-term goal drives planning

**Status: SHIPPED, v1.3.20.** `Agent.long_term_goal`/`life_event_
since_goal` — see CHANGELOG.md's [1.3.20] entry.

Prior checklist's Tier 3.1, unshipped: `Agent.plan` (existing, bounded
episodic planning) already covers "immediate objective." New
`Agent.long_term_goal: dict | None` (core cast only, LLM-authored,
changes only after a life event — success/failure/death/major
dispute) is the missing piece; `plan` becomes the step *toward* it
rather than an independent thing, closing "wants are described then
ignored in favor of ambient verbs" directly.

### 1.C — Village: NPC-behavior feeds village-cognition

**Status: SHIPPED, v1.3.20.** `Settlement.recent_goal_counts` — see
CHANGELOG.md's [1.3.20] entry.

Village-as-participant is closer to already-true than any other
pillar: `Settlement`/`town_brain`/`culture_digest`/institutions are
real objects nobody personally owns, and village → NPC is already
well-established (`current_priority` biasing goal choice). The weak
direction is NPC-behavior → village-cognition. `town_brain`'s prompt
already reads real aggregate stats; extend it to read a rolling digest
of recent *NPC-initiated* events (a wave of individual GATHER
decisions, a cluster of disputes, a fresh invention from 1.A) as
explicit grounding — same shape P2.5's "cite an actual number" fix
already established, widened to cite recent NPC-driven events too.

### 1.D — Nature → Human: disasters leave a permanent mark (the cross-pillar wire)

**Status: SHIPPED, v1.3.20, extended v1.3.21.** Storm now wired
(settlement-wide mark, since it has no per-tile tracking unlike flood/
wildfire) and a real "helper" bond added (a bystander who visibly
moved toward the disaster tile) — see CHANGELOG.md's [1.3.21] entry.
The non-helper grievance half remains unimplemented — no disaster-
response mechanic exists yet to ground who "could have helped," and
fabricating awareness would violate the project's evidence-only
discipline.

Prior checklist's unshipped N1, promoted into Phase 1 specifically
*because* it's the clearest available proof that two pillars are
actually talking to each other from day one, not four isolated
slivers shipped in the same commit by coincidence. Concretely: a
survived disaster (flood/fire/storm) writes a protected memory (same
mechanism as v1.3.17's `grievances` — significant, not subject to the
8-slot flood), a bounded lasting fear-emotion nudge, a bond with
whoever was colocated and helped (relationship_flags-adjacent — reuse
the ledger once Phase 0 lands, additive `Agent.emotions`/memory in the
meantime if sequencing requires it sooner), and a grievance against
anyone who was colocated, capable of helping, and didn't. Zero new
persistent object needed — this is wiring an existing physics event
(disasters already fire, already touch buildings/resources) into
existing agent-state mechanisms (memories, emotions, grievances) that
v1.3.17 already built.

---

## Phase 2 — Dialogue as a simulation event

**Status: SHIPPED, v1.3.21-v1.3.22.** All five items now live. Items 1
(hidden state/objectives) and 3 (structured outcome, mechanically
applied) shipped v1.3.21 — `objectives`/`open_thread` in `dialogue.
build_prompt`, the five structured-outcome fields in `apply_dialogue`.
Item 2 (explicitly supplying BOTH sides' objectives and asking the
model not to resolve the tension) is folded into item 1's prompt
wording, not a separate mechanism. Item 4 (continuation weeks later)
completed v1.3.22 — `_is_significant_pair` (dialogue's LLM-slot
prioritizer) now also treats an open ledger promise between the pair
as significant, so a pair with an unresolved thread genuinely gets
prioritized for the next LLM slot, not just allowed to surface
incidentally. Item 5 (voice consumed more consistently) also completed
v1.3.22 — `llm/letters.py` now reads `agent.voice` the same way
dialogue does (a letter is first-person written speech from a specific
agent, the same shape). See CHANGELOG.md's [1.3.21]/[1.3.22] entries.

The most concretely-scoped rewrite in the manifesto, deliberately its
own phase (cross-cutting Humans + Village, not one pillar's turn).
Current `llm/dialogue.py` produces one exchange + sentiment in a
single call; this replaces it with a richer shape:

1. **Hidden state, generated first** (as leading fields in one wider
   schema call — one call, not two, for LLM-volume discipline): each
   participant's `intent`, `emotional_state`, and `conversational_
   objective` for this exchange, drawn from the ledger (Phase 0) and
   Phase 1.B's `long_term_goal` — what does THIS agent want out of
   THIS conversation, grounded in their goal and their ledger view of
   the other party (debt owed, open grievance, a promise pending).
2. **Conflicting objectives**: the prompt explicitly supplies both
   sides' objectives and asks for an exchange that plays the tension,
   not a mutual-agreement resolution — extends v1.3.x's existing "ban
   the mutual-agreement aphorism pattern" note into a structural fix.
3. **Structured outcome, mechanically applied** (`apply_dialogue`
   already exists as the single call site — extend its result schema):
   `sentiment` (existing) plus optional `promise: str | None`,
   `debt_delta: float`, `secret_revealed: str | None`,
   `misunderstanding: bool`, `goal_change: str | None`, `belief_
   change: str | None`. Every non-null field writes to the ledger/
   agent state the same tick — "every conversation changes at least
   one simulation state" becomes literally enforced by a schema that
   makes zero-effect exchanges the exception the model has to actively
   choose (`silence`/no-op is a valid explicit outcome per the
   manifesto, not the default).
4. **Continuation weeks later**: an open `promise`/pending
   conversational thread (ledger-stored) is eligible grounding context
   for a FUTURE dialogue call between the same pair — reuses `due_for_
   dialogue`'s existing pair-selection, adds "this pair has an open
   thread" as a priority signal.
5. **Persistent conversational habits**: extends the existing per-agent
   `voice` field (one-time-authored at genesis) rather than needing new
   state — `voice` needs consuming more consistently across every
   dialogue call site (an audit item).

---

## Phase 3 — Deepen all four pillars together, second slice

Same "advance all four in one batch" discipline as Phase 1, now going
past the minimum viable slice into the manifesto's remaining items per
pillar.

### 3.A — Innovation: remaining refinements

**Partially shipped early**, folded into 1.A (v1.3.19) instead of
waiting for this section: full category coverage (custom/law/ritual/
saying/profession/institution_flavor/ecological, via `_maybe_
schedule_ontology_proposal`) and evolve/merge (`_maybe_schedule_
ontology_evolution`) are both live. **Reserved deeper reasoning:
SHIPPED, v1.3.22** — `_schedule_llm_job`'s new `deep_reasoning=True`
param (the ontology proposal/evolve/merge call sites only) applies
`DEEP_REASONING_NUM_PREDICT_MULT`/`DEEP_REASONING_TEMPERATURE` on top
of `Config`'s normal generation config, per-call only, via new
`num_predict_override`/`temperature_override` params threaded through
`CognitionRunner.run` -> both LLM clients' `generate_json`. **Adoption
thresholds: SHIPPED, v1.3.24** — `maybe_promote_status` now scales
against the concept's origin settlement's actual core-cast headcount
(`CONCEPT_SPREADING_FRACTION=0.2`/`CONCEPT_ESTABLISHED_FRACTION=0.5`,
floored at the original flat values `CONCEPT_SPREADING_ADOPTERS`/
`CONCEPT_ESTABLISHED_ADOPTERS` so a small/new cast still promotes at
the original pace) — core-cast headcount, not total settlement
population, since only core-cast members can ever become tracked
adopters (`_maybe_spread_concepts`'s candidate filter). Still open: the
full `invention_knowledge`-lifecycle reuse flagged in 1.A's
shipped-status note above.

### 3.B — Humans: identity, irreversible change, deeper inheritance

- **Personality evolves through experience, sometimes irreversibly**:
  **SHIPPED, v1.3.22.** New `Agent.hardened_traits`/`extreme_event_
  count`, `Population._maybe_harden_trait` — three extreme-event
  triggers (surviving a disaster from 1.D, a feud/ostracism outcome
  hardening, widowhood) increment a counter; crossing `EXTREME_EVENT_
  HARDEN_THRESHOLD=3` locks TRAIT_RESILIENCE into `hardened_traits`
  (exempt from `_tick_traits`'s monthly reversion from then on) with
  one real, permanent bump. Same "closed-choice enforced server-side"
  shape as v1.3.17's `relationship_flags` lock, applied to traits
  instead of relationships.
- **Occupation → identity/status/dialogue register**: **SHIPPED,
  v1.3.23** (prior checklist's unshipped N2), two of three sub-items.
  `OCCUPATION_STATUS_BONUS` (mayor/priest) feeds directly into
  `Population._prominence` — the positive counterpart to `standing_
  penalty`'s ostracism-only signal, consumed by council eligibility and
  core-cast refill (both already `_prominence`-driven). `OCCUPATION_
  DIALOGUE_REGISTER` (priest/banker/mayor/teacher/scribe) is a light
  manner-of-speaking hint in `dialogue.build_prompt` — "a priest speaks
  to belief, a banker to debt," literally the manifesto's own example.
  Rivalry between same-occupation agents sharing a building/market
  deliberately NOT attempted — it needs a real colocation-detection
  mechanism that doesn't exist yet; flagged as a future follow-up
  rather than faked.
- **Deeper inheritance**: **SHIPPED (partial), v1.3.23.** `_apply_
  inheritance` gained a personal-belief transfer, same imperfect-
  transmission shape lesson inheritance already established — the
  deceased's freshest belief passes to the heir at `INHERITANCE_
  BELIEF_CHANCE=0.4`, attributed and at reduced confidence. Traditions/
  rivalries/occupation-lean/reputation transfer remain open —
  reputation specifically is a derived/cached value (`Population.
  reputation()`), not per-agent stored state, so "inheriting" it isn't
  mechanically meaningful without a new stored field; flagged rather
  than forced.

### 3.C — Village: traditions/laws/architecture via the Innovation Layer

Traditions/festivals/laws/architecture-evolving-through-history are
mostly 3.A's category coverage applied (`category="custom"` /
`"law"` / `"ritual"`) — not a sixth mechanism, and already live.
"Priorities shift from accumulated history" was already true
mechanically (`known_concepts` grounds town_brain per 1.A,
`recent_goal_counts` per 1.C) — audited, no further code needed there.

**Architecture visibly changing on the map: SHIPPED, v1.3.25.** The
map-rendering half flagged in the prior pass as needing live design
judgment now has a real, contained hook: `world/ontology.py`'s new
`ARCHITECTURE_RELEVANT_CATEGORIES = ("technology",
"institution_flavor")` (the two categories that plausibly reshape what
gets *built*, not just believed/said/done) and `dominant_architecture_
concept(world, settlement_id)` — a settlement's own most-recently-
established concept in one of those categories, or `None`. "Most
recent" (by `tick_invented`) deliberately keeps this revisable, not a
one-time lock-in — a newer established concept can genuinely change a
settlement's visible style again later.

`SimulationEngine._maybe_broadcast` computes `architecture_styles`
(per-settlement `{name, category, concept_id}`) and tags each broadcast
building with its `settlement_id` (computed at broadcast time only,
never persisted on `Building` itself — the frontend needs it only to
look up the style). `app.js`'s building-paint loop outlines a
settlement's buildings in a color deterministically hashed from the
concept's id (`architectureStyleColor`) instead of the flat default
border, and the building hover tooltip names the style
("built in the ... style") when one exists. No concept yet -> no tint,
identical to today's rendering.

### 3.D — Nature: food webs, succession, permanent scars

- **Food webs / predator-prey feedback: SHIPPED, v1.3.26.** The
  existing hunt/starve mechanic already had a real per-tile loop
  (predators only reproduce on a successful same-tile hunt, and starve
  out without one) — the actual gap was that it was purely local: a
  pack that happened to land on prey bred fine even while the map-wide
  population was collapsing, and a herd bred at its normal rate even
  under heavy predation pressure it hadn't personally been hunted by
  yet. `WildlifeGrid.tick()` now computes two cheap O(n) aggregate
  ratios once per tick (R7 deviation — Python, aggregate scalar over
  the herd dict it already iterates, not a new per-tile hot loop, same
  precedent as the scar/soil modules): `predator_pressure_ratio`
  (total predator animals / total grazer animals) above `PREDATOR_
  PRESSURE_RATIO_THRESHOLD=0.25` measurably halves grazer reproduction
  map-wide (`PREDATOR_PRESSURE_REPRODUCE_PENALTY`) — a "landscape of
  fear" effect distinct from the direct kills the hunt mechanic already
  does. `prey_scarce` (grazer-herd-count below `PREY_SCARCITY_RATIO_
  THRESHOLD=0.5` of world-gen's own expected support,
  `GRAZER_TO_PREDATOR_RATIO` herds per pack) halves predator
  reproduction chance and doubles starvation risk even for a pack that
  got a lucky same-tile hunt. Both ratios are surfaced in `WildlifeGrid.
  summary()` and the "Wildlife" stat tile (a "prey scarce"/"heavy
  predation" suffix). River course drift and ecology->weather
  bidirectional feedback remain flagged, not attempted.
- **Forest succession (cleared land regrowing through real intermediate
  stages, not an instant biome flip): SHIPPED, v1.3.25.** `maybe_
  reclaim` used to flip an eligible grassland tile to forest the very
  first week it qualified. New `World.fallow_ticks` (same additive
  Python-dict-overlay shape as `mining_scars`/`disaster_scars`, same
  R7-deviation rationale — a low-density weekly tile scan) tracks
  consecutive qualifying weeks per tile via `terrain_evolution._tick_
  fallow`; only a tile that's stayed undeveloped and forest-bordered
  for `REFOREST_MIN_FALLOW_WEEKS=3` straight weeks is even offered to
  the existing roll. A tile that stops qualifying resets to 0 rather
  than pausing — an interrupted fallow period doesn't bank progress.
  River course drift is NOT attempted this pass (rivers are currently
  static geometry in `world/hydrology.py`, not a per-tile biome the
  existing reclaim/scar machinery can extend into — a real gap, larger
  scope than this batch).
- **Permanent landscape scars from disasters**: **SHIPPED, v1.3.22.**
  New `World.disaster_scars` + `world/terrain_evolution.py`'s `apply_
  disaster_scars`/`decay_disaster_scars` — exact same shape as `mining_
  scars` (cosmetic-only intensity, R7-deviation-flagged Python, same
  precedent), gaining on any tile actively flooded/burning each tick
  and decaying weekly. Map overlay + "Disaster scars" stat tile shipped
  in the same batch per the standing UI-surfacing rule.
- **Weather↔ecology bidirectional**: weather→ecology already exists;
  ecology→weather (deforestation measurably shifting local
  precipitation) is flagged `[HYPOTHESIS]` — confirm it's reachable
  against the existing spatial-weather smoothing before committing
  (same "unreachable threshold" lesson CLAUDE.md already documents).

---

## Phase 3.E — Nature's Mind (Body/Mind framing, v1.3.27)

Explicit user correction (2026-07-21, same day as the Body/Mind
architecture correction recorded in CLAUDE.md and this doc's v1.2
revision note): every pillar is a Body (deterministic, authoritative)
and a Mind (LLM, subjective cognition) — not a simulation with an LLM
layer bolted on. Of the four pillars, Nature was the one with almost no
Mind at all: weather/wildlife/disasters/terrain evolution are all real,
rich Body state, but nothing ever formed a subjective interpretation of
it, the way Village has `town_brain`/`beliefs` and Innovation has
`llm/ontology.py`'s propose/evolve/merge.

**Status: first slice SHIPPED, v1.3.27.** New `llm/nature_mind.py` +
`SimulationEngine._maybe_schedule_nature_mind` (world-scoped,
`season_end` cadence, same `critical=True` discipline as settlement
beliefs — deferred, never fabricated, on a spent budget/failed call).
Grounded ONLY in Nature's own Body state: `WildlifeGrid.summary()`'s
trophic-pressure ratios (3.D), `World.disaster_scars`/`mining_scars`
counts, `World.fallow_ticks` (succession progress), `World.climate`'s
warming/drying trend, season — never settlement prosperity, era, or
tech level, which is what accidentally gated Nature's only prior
ontology-origination path (see the shared-ontology correction below).
One combined LLM call does two things, same "maximize emergence per
call" discipline as everywhere else:

1. **Belief formation** — `World.nature_beliefs`, same shape/discipline
   as `Settlement.beliefs` (subject/belief/confidence, revisable,
   allowed to be wrong, capped at `llm.beliefs.MAX_BELIEFS`). Reuses
   `llm.beliefs.parse_belief`/`is_noop_belief_revision` rather than
   re-implementing belief mechanics.
2. **Concept invention** — may (not must) originate one new
   `category="ecological"` entry into the SHARED ontology registry
   (`world.ontology.register_concept`) — a migration route, symbiosis,
   habitat, climate phenomenon, or landscape identity.

Surfaced in `World.summary()`'s `nature_beliefs` and a new "The land's
own sense" stat tile (app.js) alongside Wildlife/scar tiles.

**Not attempted this slice** (real follow-up, not silently dropped):
Nature's Mind currently only *interprets and occasionally invents* — it
doesn't yet feed back into the Body the way Village's `current_
priority` measurably biases `choose_building_kind`'s odds. A future
slice could have a strongly-held nature belief nudge something
mechanical (e.g. a confidently-held "the herds are struggling" belief
slightly raising `PREDATOR_STARVE_CHANCE`'s own variance, or biasing
where `_maybe_recolonize` spawns) — flagged, not built, needs live
design judgment on which knob to touch without corrupting the Body's
own authority over objective reality (Mind interprets, it must never
override the Body's ground truth).

### Shared ontology correction: every pillar expands it, not just Innovation

Explicit user correction, same session: the ontology (`world/
ontology.py`'s `InventedConcept` registry) is a **cross-pillar
capability**, not an Innovation-pillar subsystem — Humans should
originate customs/professions/social roles/myths/traditions, Village
should originate institutions/laws/festivals/political structures,
Nature should originate ecological relationships/migration routes/
habitats/climate phenomena, Innovation should originate technologies/
techniques/philosophies/theories. All land in the SAME shared registry
so any system can discover/reference/combine/reinterpret/evolve/merge
across origins indefinitely — the registry was already architected this
way (`ONTOLOGY_CATEGORIES` has always spanned all four pillars'
flavors: `technology`, `custom`, `law`, `ritual`, `saying`,
`profession`, `institution_flavor`, `ecological`), but the *scheduling*
had accidentally collapsed to one mechanism: `_maybe_schedule_ontology_
proposal` let the LLM pick ANY of the eight categories from a single
"collective imagination of the village" job gated on SETTLEMENT
prosperity — meaning even an `ecological` concept was, in practice,
Village-originated, not Nature-originated.

**Fixed this slice**: `ecological` is now `_maybe_schedule_nature_mind`'s
exclusive territory (see above), grounded in Nature's own Body state;
`llm/ontology.py`'s `VILLAGE_PROPOSE_CATEGORIES` narrows the Village
job to the other seven, and `parse_propose` deterministically redirects
a hallucinated `ecological` answer back to a real Village category
rather than trusting the model's own claim. **Not attempted this
slice**: a true Human-originated origination pathway (grounded in
individual agent lived experience rather than settlement-level
aggregate) distinct from Village's — today `custom`/`profession`/
`saying` concepts are still Village-job-originated even though they're
conceptually "Human" in the four-pillar sense; splitting Human from
Village origination is real future scope, flagged rather than
attempted here (the two pillars share a lot of surface area — an NPC's
custom IS the village's custom — and a clean split needs its own design
pass, not a rushed one alongside Nature's Mind).

---

## Phase 4 — Cross-pillar feedback audit + persistence generalization

The manifesto's Human↔Nature/Human↔Village/Village↔Nature bullet lists
(36 items) are mostly an audit checklist against work already scoped
in Phases 1-3, not new mechanisms — go through each individually once
those land, confirm it's wired, fill the specific gaps found (expected
to be small — most resolve to "yes, once the relevant phase shipped"
rather than needing bespoke code). Persistence: generalize v1.3.17's
decay-lock pattern to disasters/village-identity/landscape scars
explicitly, rather than each phase reinventing its own convention.

**Status: initial pass, v1.3.24.** Spot-checked representative wiring
across all three cross-pillar directions, no code gap found this pass
(consistent with the doc's own "expected to be small" framing):

- **Nature -> Human**: 1.D (`Population._mark_disaster_survivors`) —
  shipped.
- **Human -> Nature**: mining scars accumulate from sustained GATHER-
  goal presence on HILLS (v0.87.27); disaster scars (3.D, v1.3.22)
  extend the same shape.
- **Village -> Human**: `current_priority` (town_brain's monthly
  decision) biases `choose_building_kind`'s odds — confirmed live in
  `settlement/buildings.py`.
- **Human -> Village**: `_maybe_schedule_town_brain` reads `materials_
  critical` (a real per-settlement shortage flag) and `recent_goal_
  counts` (1.C) — the village's own priority decision is grounded in
  aggregate NPC-driven state, not detached from it.
- **Nature -> Village**: disasters damage buildings directly
  (`tick_flood`/`tick_wildfire`/`tick_storm`), which feeds `materials_
  critical` the same way scarcity from any other cause does — no
  separate code path needed, already the same mechanism.
- **Village -> Nature**: construction/farming site selection already
  reads real terrain (`_maybe_start_construction`'s reachability-
  filtered scan) — expanding settlements measurably draw down nearby
  wild resources and drive local deforestation via the existing
  GATHER-goal `terrain_activity` heat mechanic, no settlement-specific
  code needed since it's individual agent behavior aggregated.

**Persistence generalization**: audited, no new mechanism needed. The
Tier 0.1 decay-lock convention (`relationship_flags`, v1.3.17) exists
specifically because interpersonal rupture has a "should never
silently heal on its own" design intent — the opposite intent from
disasters/landscape scars, which are explicitly DESIGNED to fade if
left alone (`decay_mining_scars`/`decay_disaster_scars`, "nature
recovers if left alone," same as `maybe_reclaim`). Applying a lock
there would contradict the mechanic's own purpose, not generalize a
convention. What Phase 1.D actually needed from that same "protect
what should endure" family — and got — is a DIFFERENT existing
mechanism: `_remember(..., because=...)`'s `core_memories` graduation,
which is itself already the generalized "significant + causally-tagged
survives eviction/decay" pattern, just applied to memory instead of
relationships. Village-identity (`Settlement.current_priority`/`era_
branch`/`recent_topics`) was checked for unintended erosion and found
clean — none of these fields have any decay mechanic at all; they
persist until explicitly overwritten by their own owning job, which is
the correct behavior for identity state. No code changes from this
audit pass; remaining manifesto bullets not spot-checked here are
lower-priority follow-up, not flagged gaps.

---

## Phase 5 — Reflection & Self-Improvement (the AI Scientist)

**Status: 5.A/5.B SHIPPED, v1.3.28 ("Start the 5th item").** 5.C/5.D/5.E
remain design-only, not yet implemented — see their own sections below.
Explicit user directive (2026-07-21): a large pasted checklist ("Reflection & Self-Improvement",
"Hearthmind Reflection (AI Scientist)", "Scientific Method",
"Self-Improvement", "Counterfactual Reasoning", "Research Questions",
"Architectural Reflection", "AI Co-Developer", "Reflection Rules",
"Reflection Acceptance Criteria" — ~90 bullets across nine headers),
consolidated here into one scoped design rather than implemented
verbatim as nine parallel systems. Where the pasted checklist and
existing standing rules overlap, the existing rule wins (e.g. "never
modify deterministic simulation code or objective world state directly
at runtime" is already CLAUDE.md's Constitution — this phase doesn't
relax it, it's the same boundary Town Consciousness's interventions
already respect).

**Framing**: this is a FIFTH participant, not a bolt-on diagnostic tool
— it observes the other four pillars (Humans, Village, Nature,
Innovation) the way the Town Consciousness observes the town, except
its subject is the SIMULATION'S OWN BEHAVIOR over long horizons, and
its output is understanding, not narrative. It never touches objective
world state or deterministic code directly; every actionable output is
either (a) a bounded nudge through the SAME deniable-intervention seam
Town Consciousness already uses, or (b) an offline engineering
recommendation requiring human approval — never a live code edit.

### 5.A — The research notebook (persistent, not a log)

**Shipped v1.3.28.** `World.reflection_notebook`/`next_reflection_
entry_id` implemented exactly as specified below; surfaced via
`_diagnostics_snapshot()` (`reflection_notebook_total`, `_by_status`,
`_recent`) — dev-console/raw-JSON only, per the Observatory UI split
(this is diagnostics-depth content, not main-UI).

New `World.reflection_notebook` (world-scoped, durable-logged per the
Constitution §6 pattern every other persistent-cognition store already
uses — `consciousness_log`/`agent_memory_log`'s shape, not a fresh
mechanism). One typed record per entry, never deleted, only appended
or status-transitioned:

```
ReflectionEntry:
  id, created_tick, kind: observation|hypothesis|experiment|conclusion|question
  subject: text (what pillar(s)/mechanism it concerns)
  content: text
  confidence: float (0..1, hypotheses/conclusions only)
  evidence_for: list[entry_id | event_ref]
  evidence_against: list[entry_id | event_ref]
  status: open|supported|rejected|superseded
  supersedes: entry_id | None
```

A rejected hypothesis is a `status="rejected"` entry, never deleted —
"preserve rejected hypotheses as historical knowledge" is structural,
not a promise. An unanswered `question` entry has no expiry; it's
eligible to be picked back up by any future reflection pass, "learn
from decades" made literal by simply not pruning this table on the
usual retention cadence other logs use.

### 5.B — The reflection job (pattern detection → hypothesis → evidence)

**Shipped v1.3.28.** `_detect_reflection_pattern`/`_reevaluate_
reflection_hypotheses`/`_maybe_schedule_reflection` implemented as
specified below, reusing `pattern_signal_counts` (Village/Human),
`WildlifeGrid.summary()`'s `prey_scarce`/`predator_pressure_ratio`
(Nature), and a new read-only aggregate over `world.invented_concepts`
category counts (Innovation/cross-pillar) — no new instrumentation
beyond that one aggregate. An existing open hypothesis with the same
`subject` skips the LLM call (deterministic re-evaluation handles it
instead), verified via a multi-cycle test.

One new round-robin-bounded LLM job (`llm/reflection.py`,
`_maybe_schedule_reflection`, same shape as the quarterly `culture_
digest`/`institution_culture` jobs — flat call volume regardless of
world size, `critical=False`: reflection is ambient self-improvement,
not blocking cognition, so it keeps the real deterministic "skip this
cycle" fallback like every other narrative job). Fires on a long
cadence (season or year boundary, not monthly — "decades and
generations," not "every tick").

Each firing:
1. Reads a DETERMINISTIC pattern-detection pass over recent history
   (reuses existing counters — `pattern_signal_counts`, `recent_goal_
   counts` from 1.C, dispute/feud/invention rates, disaster frequency
   vs. `Population._mark_disaster_survivors` outcomes — no new
   instrumentation, this is the same "grounded in real numbers, cite an
   actual figure" discipline P2.5/town_brain already enforce) looking
   for a recurring pattern above a threshold, not a single event.
2. If a pattern clears the threshold, ONE LLM call proposes a
   hypothesis explaining it, grounded in the actual numbers (never a
   free invention) — written as a new `hypothesis` entry with initial
   confidence and both an `evidence_for` (the triggering pattern) and
   an explicit prompt instruction to also name what WOULD contradict
   it, so `evidence_against` isn't structurally empty from birth.
3. Existing OPEN hypotheses are re-evaluated against fresh evidence
   every firing (deterministic re-scan, not a new LLM call each time —
   confidence moves via a small bounded step, same `bounded_random_
   walk_step`-adjacent shape temperament/mood already use, nudged by
   whether the latest evidence supports or contradicts) — "confidence
   increases or decreases as new evidence appears" without spending a
   call on every re-check.

### 5.C — Counterfactual experiments (safe, never touch real state)

"Test hypotheses through safe experiments before adopting conclusions"
is the one item needing genuine new plumbing, not reuse: a
`counterfactual_run(world_snapshot, parameter_overrides, ticks) ->
outcome_summary` harness — deep-copies a `World` from an existing
snapshot (the save/load path already exists, `from_dict`/`to_dict`),
runs it forward LLM-disabled (deterministic-only, matching every
verification script in this repo) for a bounded tick count with one
parameter perturbed, and diffs the outcome against the real world's
actual trajectory over the same window. This is EXPLICITLY sandboxed:
runs on a throwaway in-memory `World` object, never the live one,
never writes back — "hypothetical simulations that never affect
objective history" is enforced by construction (no code path from a
counterfactual run back to `self.world`), not by convention. A
hypothesis whose counterfactual outcome matches its prediction gains
confidence; a miss lowers it and gets recorded as contradicting
evidence, per 5.A's schema. Real cost (extra tick-compute) means this
only runs for a small number of the highest-confidence-worthy open
hypotheses per reflection cycle, not every one — first genuinely
resource-scoped item in the doc.

### 5.D — Self-improving reasoning (prompt/heuristic evolution, not fact accumulation)

The pasted checklist's "invent new reasoning strategies/abstractions/
frameworks" is the highest-risk item to implement literally (arbitrary
runtime-generated code is exactly what the Constitution's "never modify
deterministic code at runtime" rule exists to prevent). Scoped down to
what's actually safe and useful: reflection may propose PROMPT-LEVEL
and HEURISTIC-PARAMETER changes as offline recommendations — "this
system prompt's example set biases toward X, evidence suggests Y is
more accurate," "the current `RUMOR_NOVELTY_MIN_COUNT` threshold looks
too strict against three seasons of measured data" — surfaced as
`kind="conclusion"` notebook entries with a `proposed_change` field
naming the exact constant/prompt/config value and citing the evidence,
NEVER auto-applied. This is 5.E's "AI Co-Developer" role, not a
separate mechanism — a recommendation with evidence and an estimated
benefit, for a human to accept or reject, same review gate as any
other CLAUDE.md-governed change. A recommendation a human DOES accept
(a real prompt/config edit in a later coding session) closes the loop:
its outcome over the following reflection cycles becomes evidence for
or against reflection's OWN track record, tracked per-recommendation
so "learn from accepted and rejected developer decisions" is a real
measurement, not aspiration.

### 5.E — Architectural reflection → engineering proposals

Same offline-recommendation shape as 5.D, scoped to structural gaps
rather than tuning: reflection may notice a recurring pattern that no
existing mechanism explains (a repeated `question` entry that stays
unanswered across many cycles is itself the signal — "an idea nothing
in the engine currently models keeps recurring") and write a
`kind="conclusion"` entry proposing a new or extended mechanic, with
confidence, cited evidence, and an estimated benefit — ranked, not
auto-prioritized. Surfaced in the dev console (new "Reflection" panel,
notebook browsable by kind/status/confidence) exactly like every other
Phase N/§4-§6 internals-only feature — this is diagnostics-depth
content per the Observatory UI split, not main-UI.

### Explicitly NOT this phase

- No runtime code generation or self-modifying prompts/policies.
  Everything in 5.D/5.E is a recommendation record; a human session
  applies it, same as any other CLAUDE.md-governed change.
- No new LLM call volume scaling with population — reflection is
  settlement/world-scoped and round-robin bounded like culture_digest,
  never per-agent.
- No literal one-to-one implementation of all nine pasted headers as
  separate systems — "Reflection & Self-Improvement," "Hearthmind
  Reflection (AI Scientist)," "Scientific Method," and "Reflection
  Rules/Acceptance Criteria" describe the SAME loop from four angles;
  5.A-5.C implement it once. "Self-Improvement" and "AI Co-Developer"
  are 5.D. "Architectural Reflection" is 5.E. "Counterfactual
  Reasoning" is 5.C. "Research Questions" is the `question`-kind entry
  type in 5.A's schema, not a sixth mechanism.

### First slice (when this phase starts)

5.A (notebook schema + persistence) is the prerequisite everything else
needs, same role Phase 0's ledger played for Phase 1 — implement it
first, alone, then 5.B (the actual reflection job) as the smallest
piece that makes the notebook non-empty. 5.C/5.D/5.E depend on 5.B
producing real hypotheses to act on.

---

## The acceptance gate (folds into CLAUDE.md once Phase 0 ships)

The manifesto's Emergence Rules + Acceptance Criteria sections are a
literal review checklist, not aspirational prose — every future
feature (human or LLM-authored, including the Innovation Layer's own
inventions) should be checked against:

- Has at least one creator and one consumer in the simulation.
- Has lasting, irreversible-by-default consequences.
- Touches more than one of Humans/Village/Nature/Innovation.
- Creates a new feedback loop, not just new content.
- Cannot be replaced by a scripted event or bare RNG roll.

This becomes a standing CLAUDE.md workflow-rule addition once Phase 0
ships — not re-litigated per feature, applied the way the existing
"CLI defaults must reference Config" rule already is.

---

## Confirmed build order

**Phase 0 (ledger) first — confirmed.** Then Phase 1 (all four pillars'
first slice, together, including the 1.D Nature→Human cross-wire) —
Phase 2 (dialogue-as-event) — Phase 3 (all four pillars' second slice,
together) — Phase 4 (cross-pillar audit, last, since it's an audit of
the other phases, not independent work). Phase 5 (Reflection) is
sequenced last among the currently-designed phases, not because it's
lowest priority but because it's an OBSERVER of the other four pillars
— it needs Phases 1-4's mechanisms already producing real history to
have anything worth reflecting on; start it whenever explicitly
directed, it doesn't strictly require 2-4 to be fully shipped first
(5.A/5.B only need SOME real event/pattern history, which Phase 0+1
alone already produce).

Next step: Phase 2 implementation (dialogue-as-event) — Phase 0 and
Phase 1 (all four pillars) are shipped as of v1.3.20.
