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
marked "fully resolved" or "historical record" per CLAUDE.md.

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

**Tier 1 — substrate items other systems will lean on**
1. **A9** — feedback-loop audit (every subsystem reads upstream AND
   writes downstream). Not a feature; a review pass that likely finds
   several quiet one-way producers. Cheap, high-leverage, do first.
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
No formal audit has been run confirming every subsystem both reads
upstream and writes downstream state. Recommended as the very first
Tier-1 item — likely finds real gaps cheaply.

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
