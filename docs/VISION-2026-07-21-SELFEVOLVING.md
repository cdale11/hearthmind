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

**Relationship to `docs/DEFINITIVECHECKLIST-2026-07-21.md`**: explicit
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

Prior checklist's Tier 3.1, unshipped: `Agent.plan` (existing, bounded
episodic planning) already covers "immediate objective." New
`Agent.long_term_goal: dict | None` (core cast only, LLM-authored,
changes only after a life event — success/failure/death/major
dispute) is the missing piece; `plan` becomes the step *toward* it
rather than an independent thing, closing "wants are described then
ignored in favor of ambient verbs" directly.

### 1.C — Village: NPC-behavior feeds village-cognition

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

### 3.A — Innovation: full category coverage + spread lifecycle

Remaining `InventedConcept` categories (custom/law/ritual/saying/
profession/institution_flavor/ecological) beyond 1.A's technology-only
scope; evolve/merge as a rare round-robin-bounded follow-on LLM job
(same shape as culture_digest/institution_culture) — a mutation of an
established concept (new entry, `lineage.evolved_from` set) or a merge
of two co-adopted concepts, both re-run through 1.A's validate step,
never a shortcut. `status` transitions `spreading -> established`
once adoption crosses a meaningful population fraction, `-> abandoned`
if it never spreads and ages out. Reserved deeper reasoning: the
proposal call gets a larger `llm_num_predict`/lower temperature than
routine dialogue/cognition (per-task generation-config override,
extending existing per-call plumbing) — "reserve deeper reasoning for
discoveries... keep routine dialogue lightweight," concretely.

### 3.B — Humans: identity, irreversible change, deeper inheritance

- **Personality evolves through experience, sometimes irreversibly**:
  H6 trait nudges are already event-driven but small/bounded/mean-
  reverting by design (CLAUDE.md's own anti-homogenization fix). This
  adds a genuinely IRREVERSIBLE personality shift after a small number
  of extreme events (a survived disaster from 1.D, a permanent feud, a
  widowhood) — a new small "hardened trait" concept, same shape as
  v1.3.17's `relationship_flags` lock applied to `Agent.traits`.
- **Occupation → identity/status/dialogue register** (prior
  checklist's unshipped N2): occupation feeds `standing_penalty`'s
  positive counterpart (a mayor/priest carries baseline status),
  dialogue system-prompt gets an occupation-keyed register line ("a
  priest speaks to belief, a banker to debt" — literally in the
  manifesto), rivalry between same-occupation agents sharing one
  building/market becomes a ledger-flag signal.
- **Deeper inheritance**: H7's existing inheritance function
  (land/goods/skill/trust-bias) extends to also pass beliefs,
  traditions, rivalries, occupation lean, and reputation — more fields
  on an existing mechanism, not a new one.

### 3.C — Village: traditions/laws/architecture via the Innovation Layer

Traditions/festivals/laws/architecture-evolving-through-history are
mostly 3.A's category coverage applied (`category="custom"` /
`"law"` / `"ritual"`) — not a sixth mechanism. The village-specific
remainder: architecture visibly changing (building-kind flavor hooks
from 1.A rendering as a real map/UI difference, not just a stat), and
strengthening the 1.C wiring further — village priorities genuinely
shifting over decades in response to accumulated NPC-driven and
Innovation-driven history, not just the existing monthly `current_
priority` recompute.

### 3.D — Nature: food webs, succession, permanent scars

- **Food webs / predator-prey feedback**: `world/wildlife.py`
  currently tracks predator/prey as separate populations with a
  kill-chance mechanic — a real trophic feedback loop (prey scarcity
  suppresses predator reproduction, predator pressure suppresses prey
  population, independent of human action) is the gap. R7 (CA-
  substrate, C++-first) applies to any new code here.
- **Forest succession / river evolution / gradual terrain change**:
  `world/terrain_evolution.py` already has reclaim/mining-scar/wear
  mechanics — succession (cleared land regrowing through real
  intermediate stages, not an instant biome flip) and river course
  drift extend the same module.
- **Permanent landscape scars from disasters**: direct extension of
  1.D's psychology-side scarring to the physical layer — a
  sufficiently severe disaster leaves a marked tile region (same shape
  `mining_scars` already established) instead of fully healing.
- **Weather↔ecology bidirectional**: weather→ecology already exists;
  ecology→weather (deforestation measurably shifting local
  precipitation) is flagged `[HYPOTHESIS]` — confirm it's reachable
  against the existing spatial-weather smoothing before committing
  (same "unreachable threshold" lesson CLAUDE.md already documents).

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
the other phases, not independent work).

Next step: Phase 0 implementation (the pairwise ledger).
