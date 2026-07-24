# Hearthmind — Remaining Work Roadmap (filed v1.28.0)

Explicit user request: "build an updated roadmap to implement all the
features from all parts that you deferred for later and did not
implement in the first pass. This includes porting to C++ as well."

**Scope note, updated:** this document now covers **Part A (the
deterministic Body, det_sys.md's 25 items), Part B (the cognitive Mind,
LLM_Pillars.md's five pillars), Part C (the Body↔Mind seam), and the
C++ native-porting backlog** — all four sections of `docs/
MASTERCHECKLIST-2026-07-22.md`. (The first filing of this document
covered Part A + C++ only, on my own judgment call that B/C looked
substantially shipped from CLAUDE.md's history — not something the user
asked for. Corrected on request: B/C are shipped-a-first-version in
most places, not fully closed, and the actual open items are worth
recording just like Part A's.) Vision/audit docs outside the Master
Checklist (`docs/VISION-*`, `docs/IDEAS-2026-07-EMERGENCE.md`, `docs/
AUDIT-2026-07-20.md`) remain out of scope — each already internally
marked "fully resolved" or "historical record" per CLAUDE.md. As of
v1.34.2, `docs/HEARTHBENCH-RUNTIME-2026-07-23.md` (a separately
uploaded checklist, HearthBench model-benchmarking + the Adaptive
Runtime) is explicitly folded in as this doc's own **Tier 5** — see
the priority-ordering section below.

Every item below is a **real gap**, quoted or closely paraphrased from
the Master Checklist's own "still open" language as of this filing —
nothing here is guessed. Where a status changed mid-session (A3, A20,
A21), that's already reflected. Standing convention carries over
unchanged: work from this doc only on a future explicit "next
step"/item-naming instruction, never auto-chained.

---

## Priority ordering (this document's own read, not gospel)

Ranked by two things: (1) how many *other* open items each one unblocks
(a substrate item like A1/A11's remaining scope, or A9's feedback-loop
discipline, pays off repeatedly), and (2) how directly it serves the
project's own stated top priority, **emergence**. Sequencing inside a
tier is arbitrary.

**Tier 0 — the single biggest lever in the whole document**
0. **B1/B2/B3/B7's shared open half: refactor the ~55 scattered LLM
   jobs into real acts of the five pillars.** Every one of B1/B2/B3/B7
   is marked "shipped" today on the strength of exactly ONE
   representative job per pillar (Village=beliefs, Humans=narrative_
   direction, Nature=nature_mind, Innovation=ontology_proposal,
   Reflection=reflection) — the other ~50 LLM call sites in the
   codebase (dialogue, chronicle, dispute, founding, omens, culture
   jobs, etc.) still run exactly as they did before the pillar
   abstraction existed, untouched by observe/interpret cycling,
   attention-budget arbitration, or inbox/outbox messaging. This is
   the actual "five conscious minds inhabiting the Body" vision, not
   "five extra fields bolted onto business as usual." Bigger than any
   single Part A item; sequence it whenever a real multi-week push is
   available, not as a quick follow-up.

   **First slice shipped, v1.32.0**: a SECOND real production job per
   pillar now mirrors into `world_model`/`memory` (invention ->
   Innovation, self_tuning -> Reflection, institution_belief ->
   Village, dream -> Humans, memory-only). 2 of ~55 jobs/pillar wired
   per pillar now, not 1 — real progress, nowhere near closed.

   **Second slice shipped, v1.33.0**: a THIRD job per pillar for four
   of the five (ontology_evolution -> Innovation, species_variant ->
   Nature, dispute -> Village memory-only, migration_decision ->
   Humans memory-only; Reflection stays at 2 — no obvious third
   candidate found yet, `_maybe_schedule_reflection_question` is
   already part of the SAME job as `reflection`, not a distinct site).
   Still fully open: observe/interpret CYCLING for any of these new
   sites (they fire on their own existing cadence, not through
   `_pillar_observe_turn`/`_pillar_interpret_backpressured`),
   attention-budget arbitration for them, inbox/outbox participation,
   and the remaining ~45 call sites (dialogue, chronicle, founding,
   omens, culture jobs, festival, religion, laws, diplomacy, letters,
   fission, caravan, faction, guild_founding, rule_proposal, etc.).

**Tier 0.5 — live-diagnostic findings from a real long-running world
(filed v1.34.3, explicit user report)**, sequenced right after Tier 0
and before Tier 1: these are correctness/tuning questions about
systems Tier 0 already targets (pillar cadence) plus a few cheap-
audit-shaped findings in A9's own spirit, not new features — cheaper
and more urgent than starting Tier 1's substrate work. **Every item
below carries the user's own explicit constraint: if a change would
degrade cognition or sentience quality, don't make it** — investigate
first, only land a fix once it's confirmed genuinely free.

D1. **Reflection pillar not accumulating evidence.** A live report:
    "not yet meaningfully active despite a long simulation." Already
    partly diagnosed once before (v1.23.1, a shorter-run report): B2's
    observe/interpret cycling halves real call volume, so Reflection's
    year_end cadence needs ~2 year boundaries even in the best case
    (~70k ticks was the v1.23.1 estimate) before its first real
    interpret turn resolves — that pass's fix was "make the cold-start
    latency visible, don't change the cadence" (`Pillar.turns_
    processed` + the dev-console panel), an explicit user decision at
    the time. This new report describes a MUCH longer run still
    showing it "almost empty" — re-investigate whether cold-start
    latency alone actually explains this, or whether `_detect_
    reflection_pattern`'s own signal thresholds are separately too
    strict for a hypothesis to ever form even once interpret turns
    are firing. Fix, if any, should widen the evidence funnel
    (thresholds, what counts as a pattern) rather than force premature
    conclusions — the user's own framing ("avoiding premature
    conclusions") rules out just lowering the bar carelessly.
D2. **Nature pillar progressing much slower than the other four.**
    Same B2 halving applies (`_maybe_schedule_nature_mind`'s
    season_end cadence), but Nature's OWN gating (belief-formation
    frequency, what NATURE_EVENT_CATEGORIES counts as material) may
    independently be starving it relative to Village/Humans/
    Innovation, which don't share Nature's dependency on wildlife/
    disaster/climate events specifically. Investigate whether Nature's
    real bottleneck is the shared B2 cadence (in which case D1's fix
    helps both) or something Nature-specific.
D3. **Reduce unnecessary continuous-cadence LLM calls where event/
    milestone-driven is equivalent.** A direct precursor to Tier 5's
    Runtime Hard Rule 3 ("event-driven, not polling") but scoped to
    what's cheaply reviewable in the CURRENT architecture, not waiting
    on the full Adaptive Runtime. Audit every `_maybe_schedule_*` job's
    trigger: which ones already gate on a real state change (most do,
    via backpressure/roll chances) vs. which fire purely because a
    calendar boundary passed regardless of whether anything material
    happened since the last firing. **User's explicit constraint: any
    conversion that would degrade cognition/sentience quality is a
    hard stop, not a tradeoff to weigh.**
D4. **Justify every `deep_reasoning=True` job individually, don't
    assume all high-level cognition needs it.** v1.3.37 flagged ~20
    tasks `deep_reasoning=True` (belief revision, major life decisions,
    council deliberation, town consciousness, cultural evolution,
    invention, self-tuning) in one batch, reasoning "reallocate freed
    budget toward tasks that need genuine sentience/intelligence." That
    batch justified the CATEGORY, not each task independently. Review
    each site's actual measured latency/quality delta with vs. without
    reasoning (the recorder/review-pack tooling already captures
    `reasoning_calls_*` diagnostics for exactly this) and demote any
    task where a live measurement shows no real quality loss.
    **Same hard stop: don't demote a task if it visibly degrades
    output quality, even if it's faster.**
D5. **Rule-generation (`_maybe_schedule_rule_proposal`, `llm/rule_
    proposal.py`) occasionally produces malformed JSON.** Confirmed
    real gap: `rule_proposal` has no entry in `llm/json_schemas.py`'s
    constrained-decoding set (FT.0, v1.3.12) — it's one of the
    remaining unconstrained tasks, same class of bug FT.0 fixed for
    the eleven highest-volume tasks at the time. Give it a real JSON
    Schema (same `TriggerRule`/hook-type closed vocabulary the parser
    already validates against post-hoc) so malformed output becomes
    sampler-level near-impossible, not just retried/repaired after the
    fact.
D6. **Social scaling beyond several hundred/one thousand villagers.**
    Every agent currently has O(population) potential social surface
    (relationships/trust/debts dicts keyed by any other agent id, no
    locality partition) — realistic at a few hundred, implausible at a
    thousand+. Needs a real neighborhood/district/institution layer
    that BOUNDS an individual's implicit social awareness to people
    they'd plausibly know, with existing institutions (FAMILY/COUNCIL/
    GUILD) and factions as natural building blocks already in place.
    Real overlap with Tier 3 item 22 (A16, trade/tech/information as
    graph algorithms) and Tier 5's B10 (spatial locality partitioning)
    — this item is the SOCIAL-graph-locality counterpart to B10's
    spatial one, and probably belongs paired with it rather than
    solved twice independently.
D7. **Strengthen cumulative-culture feedback loops** (beliefs,
    inventions, traditions, institutions building on each other, not
    staying independent). A live report already confirms encouraging
    cumulative culture forming organically — this is "do more of what's
    already working," not a gap-fix. Real continuation of Tier 0's
    pillar-wiring work (more jobs feeding pillar `world_model`/memory,
    inter-pillar messages referencing prior culture) and A17
    (`world/memetics.py`'s propagation-weight primitive, still only
    wired into ontology-concept spread, not rumor/tradition/belief/
    song/technique per Tier 2 item 14).
D8. **Village-level theories' life cycle: do they ever expire, weaken,
    merge, or get accepted, or only accumulate?** `Settlement.beliefs`
    forms/revises but has no explicit "this became settled fact" or
    "this quietly faded" terminal state the way `InventedConcept` has
    `established`/`retired` (A8's evaluate+select step, v1.19.0) or
    `ReflectionEntry` has `supported`/`rejected`/`superseded`. Real
    overlap with Tier 3 item 24 (B8's un-shipped `reinforce`/
    `reinterpret`, needing per-note salience/access tracking) — a
    belief life cycle and B8's memory life cycle are close enough in
    shape that they should probably share a mechanism, not be designed
    twice.
D9. **Diagnostics should explain WHY a cognitive event happened, not
    just THAT it happened.** When a belief/invention/tradition forms,
    show which observations/memories/historical events actually fed
    that specific call's prompt — the recorder already captures
    `structured_input`/`context_snapshot` per call (v1.3.0's Context
    Influence work), so this is largely a SURFACING gap (a per-event
    "why this happened" reconstruction reading already-captured data),
    not new instrumentation. Real sibling of Tier 5's B5.4 "explain
    this tick" (execution-level why) — this is the cognition-level
    counterpart (semantic-level why); worth building with shared
    presentation conventions when both exist, not required to wait for
    B5.4 itself.
D10. **Memory consolidation over extremely long runs: still bounded
     and still preserving what matters?** `Pillar.consolidate()` (B8),
     `Agent.memories`' salience-based eviction, `Settlement.belief_
     digest`/`culture_digest`, and event-log/metrics-table retention
     are all real, already-shipped consolidation mechanisms — this
     item is a RE-VERIFICATION at much longer horizons than they were
     originally tuned/tested against (the project's longest soaks to
     date are ~20k ticks; "extremely long" live reports are pushing
     past that), not a new mechanism. Check whether any of these caps/
     thresholds need retuning at real multi-hundred-thousand-tick
     scale, and whether `Pillar.consolidate()`'s digest-of-a-digest
     folding (repeated consolidation cycles) still reads coherently
     after many rounds rather than degrading into mush.

**Tier 1 — substrate items other systems will lean on**
1. **A9** — feedback-loop audit. **Done, v1.34.0** — see its full
   entry below for findings/fixes/follow-ups.
2. **A11** — hydrology as a real field: groundwater, and (the big one)
   erosion feeding back into `Tile.elevation` so A3's rivers-re-carve
   item becomes possible at all. Blocks A3's own remaining half.
3. **A1** — the other eleven named fields (moisture is really A11's;
   fertility/nutrients/disease-pressure/pollution/scent/traffic/heat/
   cultural-influence/ownership/beauty/noise are still unbuilt) plus
   migrating `mining_scars`/`disaster_scars`/the climate grid onto
   `FieldGrid` properly instead of staying separate stores.
4. **A2** — the diffuse/reaction-diffuse/cellular-step operator library
   over A1's fields. Forest succession is the doc's own worked example
   and would give A1's future fields real consumers immediately.

**Tier 1.5 — The Living Map (filed v1.34.4, full detail docs/VISION-
2026-07-24-LIVINGMAP.md, explicit user vision)**, sequenced after
Tier 1's substrate work (specifically A11's mutable-elevation item,
which several of these depend on) and before Tier 2's mechanism gaps:
the map should let a player read the world's history off it directly
— today's rendering leans closer to "static procgen map with agents
on top" than the living-landscape target. Cross-referenced against
what's already real rather than treated as greenfield — a fair amount
partially exists (the four scar-shaped overlays, the "🗺️ fields"
toggle, layout/architecture/dialect grammar, ERA-styled cartography,
forest reclaim). Real gaps, roughly by leverage:
- **M2/M8** — `Tile.elevation` staying immutable is the single
  biggest blocker: real erosion, flooding-reshapes-the-land, quarry
  scars as actual terrain change (not a flat color tint), and rivers
  re-carving their course (A3's own remaining half) are ALL gated on
  this one item, already named in A11's own entry above.
- **M6/M7** — the existing fields overlay (v1.27.0) is an honest first
  slice, not the reference-game-quality target this vision names
  (Cities: Skylines / Workers & Resources / Timberborn / Dwarf
  Fortress conventions: gradients, hotspots, thresholds, legends).
  Pure rendering work over data that already flows to the client —
  no backend gap, a genuine UI redesign item.
- **M1/M9** — extend the scar-shaped-dict pattern (already proven 4x:
  mining/disaster/ritual/ruin) to old-road-beds, field boundaries, and
  a labeled "environmental stress"/degradation reading — reusing the
  mechanism, not inventing a new one each time.
- **M4** — a wetland/marsh concept (hydrology drives moisture today,
  not a distinct expanding/shrinking biome) and a migration-trail
  accumulator (same shape as `ritual_activity`, different trigger).
- **M10** — whether the BASE map (every overlay off) already reads as
  alive, independent of overlay quality — needs a direct look before
  scoping a fix.
- **M11/M12** — folded into the standing-discipline items (A23-A25
  above) as an ongoing completeness bar, not a one-shot task; also now
  recorded in CLAUDE.md's Observatory UI direction section directly.

**Tier 2 — real mechanism gaps, each self-contained**
5. **A3** — rivers re-carving via erosion (needs A11's mutable
   elevation first — sequence after Tier 1 item 2).
6. **A4** — convert remaining scripted subsystems (agriculture,
   infrastructure, economy, information) to continuous field/threshold
   updates instead of discrete "fires."
7. **A15** — wildlife/animal genetics (humans-only today); bridge to
   `world.wildlife.SpeciesVariant`, which stays purely descriptive.
8. **A14** — the other five named organism-biology subsystems (stress,
   reproduction, development, injury-recovery, sleep) beyond immune
   response.
9. **A18** — a real authoring system for new composite reactions (today
   exactly one hand-authored `CompositeReaction` exists); the doc's own
   "raid" example scoped down to relationship-rupture, a real combat/
   raid mechanic remains unbuilt.
10. **A19** — the six remaining named history axes (traffic, pollution,
    fertility, ownership, construction, ecology) beyond mining/
    disaster/ritual/ruin.
11. **A21** — legend feedback into tradition/religion/institution
    formation; using a formed legend as grounding context in other
    prompts; unifying with folklore.
12. **A20** — a second real multi-scale field beyond `population_
    density`; "culture aggregates settlements' information-ecosystems."
13. **A13** — a real automatic reactor (today: query-only, nothing
    actually fires a reaction and mutates a standing building's
    material after the fact).
14. **A17** — unify rumor/tradition/belief/song/technique onto
    `memetics.py`'s propagation-weight primitive; a shared mutate/
    decay/compete step; a real fitness-vs-truth axis for rumors.
15. **B5** — Innovation's affordance/reaction query (A5/A6/A13) is now
    actually buildable — those three Stage IV items shipped after B5's
    own first version deliberately deferred "until the substrate
    exists to query." Revisit: let Innovation's propose-step read
    `discover_reactions`/`discover_combinations` for real, not just
    `pattern_signal_counts` pressure.
16. **C4** — the runtime-auditor half: nothing today automatically
    retires persistent state with no reader ("reject state no system
    observes"). Today's C4 is only the review-time human discipline;
    the spec explicitly also wants a runtime check.

**Tier 3 — deepen an already-real mechanism**
17. **A5/A6** — per-instance `Entity.affordances`/`Entity.properties`
    (today: class-level `dict[BuildingKind, ...]` only); the validate-
    step half of A6 (re-checking a PROPOSED concept against this layer,
    not just grounding the generate-step).
18. **A7** — a real recursive rewrite/production system in each domain
    (today: layout is a scoring bias, architecture a fixed three-slot
    production, dialect one-rule-per-call); ritual/recipe-structure
    grammar (the spec's fourth named domain, deliberately left LLM-
    authored so far); rules themselves becoming LLM-proposable.
19. **A8** — sandbox forward-simulation (`simulation/sandbox.py`) as a
    fitness input; grammar-based mutation (A7) as an alternate generate
    path alongside the existing LLM propose/evolve/merge.
20. **A10** — migration, competition, decomposition, pollination (→
    vegetation), habitat formation; folding the food web onto A1's
    field substrate as one coupled system.
21. **A12** — per-instance `Entity.material` (today: class-level, one
    material per `BuildingKind`).
22. **A16** — trade-as-network-flow, tech-as-DAG, information-
    propagation-as-graph-algorithm (today: only centrality is shipped).
23. **B4** — reverse-direction disagreement classification: only the
    Nature→Village message site checks whether the receiver already
    disagrees; Village→Innovation/Innovation→Village default to flat
    `theory`/`discovery` tags without that check.
24. **B8** — `reinforce`/`reinterpret` (today: `consolidate`/forget
    only) — needs per-note salience/access tracking across all five
    pillars.
25. **C2** — most of the spec's named pillar-emitted intentions (invent
    tech, set custom, change law, reorganize institution, shift land
    use, domesticate, build, propose experiment) still aren't pillar-
    emitted at all — they're separate deterministic/LLM mechanics
    outside the five-pillar refactor's current reach. Real progress
    here mostly waits on Tier 0's bigger refactor.
26. **C3** — "pillars may initiate contact" (today: player-initiated
    only, via `/ask/{pillar}`).

**Tier 4 — standing discipline, re-audit periodically rather than
"finish" once**
27. **A23** — composability-over-content is a review-time rule, not a
    ships-once feature: keep enforcing it on every new subsystem.
28. **A24** — physical-consistency validation staying inviolable as
    Part B/C gain power — re-confirm whenever a pillar gains a new
    intention-writing capability.
29. **A25** — periodically re-audit LLM call sites: has anything that
    used to need genuine judgment become mechanically deterministic
    (a candidate for A7's grammars or A1's fields) since it was last
    checked?

**Tier 5 — HearthBench & the Adaptive Runtime (filed v1.34.2, a
separate two-part program, sequenced strictly AFTER Tiers 0-4)**
30. **The whole checklist in `docs/HEARTHBENCH-RUNTIME-2026-07-23.md`**
    — folded in per explicit user request, ordered to run only once
    every item above is done. Two independent programs sharing one
    telemetry seam (Part C): **HearthBench** (Part A, a standalone
    model-selection benchmark — mostly buildable on existing
    foundations: `build_llm_client`, `eval_harness.py`, `recorder.py`,
    `quality_labels.py`) and **the Adaptive Runtime** (Part B, an
    OS-like execution layer deciding when/where/how work runs — nearly
    all greenfield; today everything still runs every tick because
    time passed, which the doc's own Hard Rule 3 forbids). See that
    doc's own "SEQUENCE" section for the two tracks' internal step
    ordering (Runtime: replay-hash test first, then B0/B1 task
    declaration + B5.4 "explain this tick," then B5 profiling, B9/B3
    timescales+dirty-tracking, B2/B10/B4 budgets+locality+dormancy,
    B11/B12 memory+history, B15.5/B15.3/B15.6 reference-mode+
    escalation-ladder+profile-recording, then B6-B8/B13 adaptive
    tuning last. HearthBench: A1/A2 skeleton+adapter, A3.1 fixture
    export, A4.1+A5.7/A5.8 deterministic scorers, A13 CI regression
    guard, A7/A8 metrics+diagnostics, A9/A10/A12/C5 reports+score+UI+
    passport, A4.2/A4.3 judge+human calibration, A5.11 world-level run
    last). The two tracks run in parallel with each other, both
    starting only after Tier 4.

    **Why sequenced last, not folded into Tiers 0-4's own ordering**:
    this is infrastructure FOR building/measuring Hearthmind, not a
    Hearthmind feature itself — every earlier tier item changes what
    the simulation IS; this changes how it's run and how a model
    choice for it gets evaluated. Building it before the Body/Mind/
    Seam work above stabilizes would mean re-profiling and re-
    benchmarking against a moving target repeatedly. `B0`'s prime
    invariant ("gameplay never makes scheduling decisions") and the
    Tier 0 pillar refactor's own eventual per-pillar cadence work are
    also natural neighbors (`B9` hierarchical timescales overlaps real
    territory with B2/B3's attention-scheduler cadences already
    shipped) — worth a fresh look at that overlap when Tier 5 actually
    starts, not assumed away here.

---

## Full per-item detail

Copied close to verbatim from `docs/MASTERCHECKLIST-2026-07-22.md` so
this document stays a faithful snapshot, not a paraphrase that could
drift from the source of truth. Consult that doc directly for full
context/rationale on any item — this is the "what's left" extract.

### A1 — Continuous environmental fields
Only `population_density` is a real field; the other eleven named
(moisture — really A11's, fertility, nutrients, disease-pressure,
pollution, scent, traffic, heat, cultural-influence, ownership, beauty,
noise) are unbuilt. `terrain_activity`/`mining_scars`/`disaster_scars`
and the climate grid remain separate stores, not migrated onto
`FieldGrid`. Vegetation/wildlife/farming still don't read any field.

### A2 — CA / diffusion / reaction-diffusion operators
No `diffuse`/`reaction_diffuse`/`cellular_step` library exists yet
beyond A2's own already-shipped worked example (forest succession, via
`world/ca_operators.py`, v1.14.0) — the doc calls for a small general
operator library other systems (disease spread, fire) can reuse; today
only succession uses it.

### A3 — Procedural generation as continuous runtime
Rivers/erosion (mutating immutable, native-store-backed `Tile.
elevation`) — the biggest remaining piece. Settlements/cultures still
evolve via LLM, not deterministic procgen (arguably correct per the
Body/Mind split, flagged as an open question rather than a clear gap).

### A4 — Continuous systems vs. scripted events
Agriculture, infrastructure, economy, and information subsystems are
still partly event-driven rather than continuous field/threshold
updates. Economy → resource/price fields that flow; agriculture →
fertility/moisture field consumption; information → propagation on the
social graph (A17) are all still unconverted.

### A5/A6 — Affordances
`Entity.properties`/per-instance `Entity.affordances` (today: class-
level `dict[BuildingKind, frozenset[str]]` only). A6's validate-step
half (re-checking a PROPOSED concept against the affordance layer,
distinct from the shipped generate-step grounding) not attempted.

### A7 — Grammar-based procedural systems
None of the three shipped domains is a full graph/shape grammar
(layout = scoring bias, architecture = fixed three-slot production,
dialect = one-rule-per-call, not recursive). Ritual/recipe-structure
grammar (the spec's fourth domain) deliberately left LLM-authored.
Rules being themselves LLM-proposable not attempted.

### A8 — Evolutionary Innovation loop
Sandbox forward-simulation as a fitness input; grammar-based mutation
(A7) as an alternate *generate* path alongside the existing LLM
propose/evolve/merge — both open.

### A9 — Producer/consumer feedback loops
**CLOSED, v1.34.0-v1.34.2.** 15 named state stores checked; most
already genuinely closed loops. Three real gaps found and fixed:

- `World.mining_scars`/`disaster_scars` (v1.34.0) now bias `Population.
  _choose_build_site` away from badly scarred ground (new `MINING_
  SCAR_SITE_PENALTY_SCALE`/`DISASTER_SCAR_SITE_PENALTY_SCALE`, `world/
  terrain_evolution.py`).
- `world/spatial_memory.py`'s `location_character()` (v1.34.1): split
  into `location_character_from_dicts(...)` (the real logic) + a thin
  `World`-scoped wrapper; `_choose_build_site` now reads its mining/
  disaster/ruin scoring from ONE call to the former instead of three
  duplicate `.get()` lookups. The `World`-scoped wrapper itself still
  has zero callers (nothing with `World` in scope needs it yet) — a
  future dialogue/cognition/NPC-inspector location-flavor consumer
  remains open, not attempted (a separate, smaller finding, not
  re-opened by the "closed" verdict above — the read-side duplication
  itself IS fixed).
- `llm/ontology.py`'s `PRESSURE_SIGNAL_LABELS["materials_bottleneck"]`
  (v1.34.2): had a label with no writer anywhere. `_detect_settlement_
  bottlenecks`'s existing edge-trigger now increments it, same shape
  as `dispute_feud`/`nature_adaptation`'s existing sites.

Two of the original four "recorded, not fixed" findings were
CORRECTED on re-examination (v1.34.2), not fixed — they were never
real A9 violations: `world/architecture_grammar.py`'s per-building
descriptor and `World.causal_threads` are both deliberately UI-facing
flavor content by their own design docs (same category as dream text
or chronicle narration — never required to feed back mechanically).
`Agent.genome` is already a genuine closed loop (birth -> `Agent.
traits`, read everywhere trait behavior matters) — "never revised
post-conception" is correct biology, not a gap; `hardened_traits`
already covers "life events permanently reshape behavior" at the
phenotype layer, the right layer for that mechanism.

`Settlement.legends`'s write-only status is real but was ALREADY
tracked as its own separate finding under A21 above ("legend feedback
into tradition/institution formation... remains open") before this
audit — not a new A9 item, and not something A9's closure claims to
have resolved.

Also surfaced (unrelated finding, not an A9 item): `scripts/verify_
native_soak.py` shows a pre-existing MISMATCH at tick 1055, confirmed
via `git stash` to predate this pass — a real open native/fallback
divergence needing its own diagnostic pass.

### A10 — Ecology / food webs
Migration, competition, decomposition, pollination (→ vegetation), and
habitat formation (reads fields, writes carrying capacity) all remain
unbuilt beyond the shipped predator-prey feedback and nutrient
cycling. Folding the whole food web onto A1's field substrate as one
coupled system is real follow-up work.

### A11 — Continuous hydrology
Groundwater and erosion (feeding back into `terrain.elevation`, now
mutable) remain unbuilt — surface-water flow/evaporation is the only
piece shipped. One of the highest-leverage remaining items: water
touches agriculture, siting, disasters, and ecology, and unblocks A3's
river-re-carving.

### A12 — Material science
Per-instance `Entity.material` (today: one material per `BuildingKind`
at the class level, not per physical instance).

### A13 — Chemistry / reaction system
A real automatic reactor — the spec's literal `ReactionRule(reactants,
conditions, products, rate)` with automatic tick-loop firing that
mutates a standing building's actual material — remains unbuilt; today
ships the query half only (`discover_reactions`, read-only).

### A14 — Layered organism biology
Stress, reproduction, development, injury-recovery, and sleep (five of
the spec's six named subsystems) remain open — only immune response
(the doc's own worked example) shipped. A genetic contribution to
baseline `immune_strength` (today: nutrition/rest only) is a flagged
future connection to A15.

### A15 — Genetic inheritance
Wildlife/animal genetics (scoped to humans this pass). `world.wildlife.
SpeciesVariant` stays descriptive-only, not wired to real heritable
genes — deferred specifically to avoid `AnimalHerd`'s native-index
parity risk.

### A16 — Graph algorithms
Trade-as-network-flow, tech-as-DAG, and information-propagation-as-
graph-algorithm (A17) are unbuilt — only weighted-degree centrality is
shipped (plus community detection, already present under the `FACTION`
name).

### A17 — Information ecosystem
Rumor/tradition/belief/song/technique each stay on their own
independent, mature, deliberately-untouched mechanisms — only ontology-
concept spread uses the new `memetics.py` propagation weighting.
Folding them onto one shared mutate/decay/compete step, plus a real
fitness-vs-truth axis for rumors (false beliefs propagate if fit, not
suppressed for being false), is real follow-up work.

### A18 — Composable event reactions
Only one hand-authored `CompositeReaction` exists — no general
authoring system yet (a village can't propose its own combinations the
way `TriggerRule` is LLM-authored). The doc's own "raid" example is
scoped down to a relationship-rupture consequence; a real combat/raid
mechanic remains unbuilt.

### A19 — Persistent spatial memory
Only 3 of the spec's 9 named axes are unified (mining/disaster/ritual,
plus ruin as a 4th added later) — traffic/pollution/fertility/
ownership/construction/ecology remain separate or unbuilt. `FarmGrid.
soil_fertility`/the A1 field substrate are a different shape
(continuous fields vs. sparse per-event dicts) and folding them in is
real follow-up work.

### A20 — Multi-scale simulation
A brand-new second field beyond `population_density`, and "culture
aggregates settlements' information-ecosystems" (the spec's other
named example), remain open.

### A21 — Temporal compression
Legend → tradition/religion/institution feedback; using a formed
legend as "already legendary" grounding context in other prompts
(chronicle/dialogue/folklore); any unification with folklore itself —
all open, see CHANGELOG.md's [1.28.0] entry for exactly what shipped.

### A22 — Emergence API
Not literally "every deterministic subsystem" produces observations
yet (today: highlights, reflection hypotheses, ontology promotion, a
materials-bottleneck detector, the social-hub detector) — more
producers are a standing, ongoing follow-up as new subsystems ship.

### A23/A24/A25 — Standing discipline
Not "features" to finish — periodic re-audit items. A23: keep
rejecting isolated new mechanics at review. A24: re-confirm physical-
consistency validation stays inviolable as Part B/C gain power. A25:
periodically re-check whether an LLM call site has become a candidate
for a grammar/field/propagation mechanism instead.

---

## Part B — The Cognitive Mind (LLM_Pillars.md, five pillars)

Every item B1-B9 is marked "shipped"/"shipped a first version" in
`docs/MASTERCHECKLIST-2026-07-22.md` — genuinely real, not stubs — but
nearly every one carries the same asterisk: proven against exactly
ONE representative production call site per pillar, not the full
domain the spec names. See Tier 0 above for the one item that matters
more than all the others combined.

### B1 — The Pillar abstraction
Real `consolidate`/`forget`/`reinforce`/`reinterpret` memory semantics
(today: a capped FIFO, `consolidate` folds old notes but doesn't
selectively reinforce/reinterpret by salience — that's B8's own listed
gap). The full "refactor ~55 scattered jobs into acts of these five"
— **the single largest open item in Part B**, see Tier 0.

### B2 — The continuous cognitive cycle
Structurally complete for the one job per pillar it covers; the open
half is the same as B1's — extending observe→interpret→remember→plan→
act→reflect cycling to every LLM call site, not just five.

### B3 — The Attention Scheduler
`message_count`/`player_focus` inputs to `compute_priority()` both
still read a hardcoded 0 — real, ready inputs (B4's message bus and
C3's player-chat both now exist and could feed them) that nothing
populates yet. Round-robin arbitration is still trivial with one job
per pillar; real arbitration needs Tier 0's broader refactor first.

### B4 — Inter-pillar consciousness bus
Reverse-direction disagreement classification (does the RECEIVER
already hold a conflicting theory) is wired only at the Nature→Village
send site; Village→Innovation and Innovation→Village default to flat
`theory`/`discovery` tags without that check — see Tier 3.

### B5 — Innovation as conscious scientist
Evolve/merge untouched by this pass (only propose gained the
hypothesis/outcome loop). The real affordance/reaction query this item
always wanted was explicitly deferred "until Stage IV's substrate
exists" — Stage IV (A5/A6/A13) has since shipped first slices, so this
is now genuinely actionable, not blocked — see Tier 2 item 15.

### B6 — Reflection as meta-scientist
"Track whether its advice worked" for the advisory-proposal path was
deliberately not attempted — there's no mechanical effect to measure
an outcome against for free-text advice (unlike a governor nudge,
which has a real before/after). The human's own accept/reject marking
IS the tracked outcome by design, not a gap needing more automation.

### B7 — Humans collective consciousness
Scoped to making the collective mind AWARE of voice-pair rotation —
the deeper "individual acts locally, collective sets the mood/
direction" architecture is real but, like B1-B3, only wired at this
one site. Broader coverage needs Tier 0's refactor.

### B8 — Living memory & consolidation
`reinforce` (a frequently-accessed note resists eviction) and
`reinterpret` (an old note's meaning shifts in light of new
experience) are both unbuilt — only `consolidate` (fold old notes into
a digest) and the pre-existing FIFO `forget` exist. Needs per-note
salience/access tracking across all five pillars — see Tier 3 item 24.

### B9 — Self-model & world-model per pillar
Effectively CLOSED — "how it relates to the others" was B9's one
named gap when this section was written, and B4's inter-pillar message
bus (shipped) already covers it. No further action needed here;
flagged in case a fresh audit disagrees.

---

## Part C — The Seam (Body ↔ Mind co-evolution)

### C1 — Perception channel (Body → Mind)
CLOSED. Salience-ranking (the one real gap found) is shipped.

### C2 — Intention channel (Mind → Body)
Most of the spec's own named pillar-emitted intentions (invent tech,
set custom, change law, reorganize institution, shift land use,
domesticate, build, propose experiment) aren't pillar-emitted
intentions at all yet — they're separate deterministic/LLM mechanics
untouched by the five-pillar refactor. Not a validation gap (every
Body-touching write that DOES exist today is validated) — a coverage
gap that mostly waits on Tier 0's bigger refactor to even become
relevant.

### C3 — Player ↔ Pillar chat
"Pillars may initiate contact" (today: strictly player-initiated via
`/ask/{pillar}`) — flagged as real future scope in the doc itself, not
silently dropped.

### C4 — The acceptance gate as law
The review-time half (reject isolated mechanics, reject state no
system observes) is a standing human discipline, followed but never
automated. The RUNTIME half — an auditor that actually retires
persistent state nothing reads — doesn't exist. See Tier 2 item 16.

### C5 — Co-evolution loop
Not a discrete task — the emergent end-state every other item above
feeds. Worth re-reading this item's own one-paragraph description
after any major Tier 0/1 push, as a sanity check on whether the loop
is genuinely turning unattended yet.

---

## Addenda from a deep re-pass of the checklist doc

Two things the per-item sections above don't fully surface, found by
reading the doc's own footer/roadmap-appendix sections end to end
rather than stopping at the per-item write-ups:

- **A11's R7 native-port deviation has a different justification than
  most.** Every other flagged "not yet ported to C++" item in this
  document (weather, terrain evolution, disasters) is deferred because
  it's genuinely low-density/not-a-measured-hotspot. `world/hydrology_
  field.py` is deferred for a DIFFERENT reason, per its own module
  docstring: it's a from-scratch mechanism whose exact shape needs
  live validation before locking into a compiled interface — worth
  knowing before assuming it's just next-in-line for the same
  low-density reasoning as its neighbors.
- **A loose thread in the source doc itself, not a code gap:** the
  Master Checklist's own closing section ("Open design decision")
  states the Humans-collective-vs-individual-NPC disagreement question
  formally "needs an explicit user decision before step 14 ships."
  Step 14 (B7) DID ship (v1.12.0) — but by adopting the doc's own
  stated *default* ("individual acts locally, collective sets the
  mood/direction"), not via a fresh explicit confirmation matching
  that footer's literal requirement. Functionally resolved (the
  default is sound and already load-bearing in shipped code); flagged
  here only because the checklist doc's own footer note was never
  updated to reflect that resolution, and a future reader taking that
  footer at face value could wrongly conclude B7 never really shipped.
  No code action needed — an optional one-line correction to `docs/
  MASTERCHECKLIST-2026-07-22.md`'s own footer, if that doc is ever
  revised again.

No further items were found beyond what's already recorded in the
Part A/B/C sections above — every "remain(s) open, flagged"/"NOT
attempted"/"NOT built" occurrence in the source doc (cross-checked via
direct search, not sampling) traces back to something already listed
in this roadmap.

---

## C++ native-porting backlog

Per CLAUDE.md's own standing R7 note (Engineering Constitution, "the CA
engine's remaining Python surface") — the authoritative, currently-
tracked list, not independently re-derived here:

- `world/weather.py` — the core blend function is ported (`cpp/src/
  weather.cpp`); the rest of the module (spatial-region handling)
  is not confirmed ported. Worth a direct check before assuming either
  way.
- `world/terrain_evolution.py` — same "not yet a measured hotspot"
  status as weather.py originally had; revisit under R7's "write new
  code in C++ from the outset" rule for anything added to it going
  forward, and consider porting the existing local-activity/climate-
  drift-adjacent hot loops opportunistically.
- `world/disasters.py` — not yet ported.
- `world/hydrology.py`/`world/hydrology_field.py` — not yet ported; a
  natural pairing with the A11 hydrology work above, since a real
  erosion/groundwater expansion would be new code anyway (R7: write it
  in C++ from the start rather than porting old code later).
- `economy/farms.py` — largely ported already (`cpp/src/farm_grid.cpp`,
  `soil_fertility.cpp`, `wilt_farms.cpp`); confirm nothing newer
  (nutrient cycling, A11 moisture-yield coupling) has been added back
  in pure Python since.
- `settlement/buildings.py`'s decay/repair math — largely ported
  (`cpp/src/settlement_decay.cpp`) per CLAUDE.md's native-module list;
  confirm this pass's newer ruin-scar/layout-grammar/architecture-
  grammar additions haven't reintroduced un-ported hot-path Python
  (they're metadata/scoring, not per-tick decay math, so likely fine —
  worth a direct read-through rather than an assumption).
- **New code discipline (already in force, not a backlog item):** any
  brand-new mechanic inside the CA/physical-substrate domain (weather,
  terrain evolution, agriculture, disasters, hydrology, ecology) is
  written C++-first from its very first commit — pybind11 binding,
  pure-Python fallback, randomized-equivalence + `verify_native_soak.
  py` verification — per R7. This is a standing rule for future A1-A21
  work above, not a separate task to schedule.

**Recommended first step if this backlog is picked up:** a direct
`grep`/read pass confirming exactly which of `world/weather.py`/
`terrain_evolution.py`/`disasters.py`/`hydrology_field.py` still run
hot per-tick loops in pure Python today, since this document's list
above is inherited from CLAUDE.md's own note rather than freshly re-
verified against current source — the R7 section itself flags this
as "the backlog... is unchanged in shape" from an earlier snapshot,
not a live-verified inventory.
