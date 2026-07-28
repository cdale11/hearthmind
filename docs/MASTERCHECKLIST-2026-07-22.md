# Hearthmind — The Complete Master Checklist

Single master document, deep specs, covering **every system in
det_sys.md (the deterministic Body, items 1–25) and LLM_Pillars.md (the
cognitive Mind, the five pillars)** — each checked against v1.4.1 and
marked with real status, a data model, what it extends or replaces, and
what it feeds. Nothing swept into a deferred pointer this time.

Two layers, one architecture:
- **Body (Part A)** — det_sys.md. The deterministic universe: continuous,
  rule-bound, endlessly generative. No LLM.
- **Mind (Part B)** — LLM_Pillars.md. Five persistent conscious pillars
  inhabiting the Body. LLM only.
- **The seam (Part C)** — how Mind perceives and reshapes Body without
  ever violating it.

Status legend: **[PRESENT]** exists and matches the vision ·
**[PARTIAL]** exists but shallow/static vs. the vision ·
**[MISSING]** not in the codebase. Verified against v1.4.1 source.

The governing law, from both docs:
> The deterministic layer answers *"what is objectively possible?"*; the
> LLM answers *"given what's possible, what happens next, and why?"* No
> pillar ever violates a deterministic rule; the LLM never invents fact.

---

# PART A — THE DETERMINISTIC BODY (det_sys.md, 25 systems)

The one-sentence diagnosis of the whole Body layer, verified across
`world/`: **most systems exist but are generated-once-at-creation and
static-or-random-walk thereafter** (rivers carved once; terrain a
9-region grid, not per-tile; no material/affordance model; no chemistry;
no genetics). det_sys.md's core ask — "procedural generation as a
*continuous runtime process*, not a world-generation step" — is the
through-line for nearly every PARTIAL below.

### A1 — Continuous environmental fields [det #1] — SHIPPED (scoped, v1.4.9) → the foundation

- [ ] **Status:** A 9-region climate grid and sparse `terrain_activity`/
  `mining_scars`/`disaster_scars` dicts exist in `world/state.py`;
  explicitly *not* per-tile fields (deferred as "R7/C++-first").
- [x] **Spec:** Introduce a `FieldGrid` abstraction — a set of named
  scalar fields over the map (moisture, fertility, nutrients, disease-
  pressure, pollution, scent, traffic, heat, cultural-influence,
  ownership, beauty, noise), each a 2D array updated per tick by a
  local rule. Start coarse (the existing region grid resolution) and
  raise resolution as the C++ store allows; the *interface* (named
  fields, per-tick update, cross-field coupling) matters more than
  resolution day one. **Shipped**: `world/fields.py`'s `FieldGrid`
  abstraction, coarse (3x3, matching `WEATHER_REGION_GRID`). Only
  `population_density` is a real field so far — the other eleven named
  above are NOT built; each is a future follow-up onto the same grid.
- [x] **Data model:** `World.fields: dict[str, ndarray]` (or C++ dense
  columns), each with a per-tick `step(fields, terrain) -> delta`
  function; bounded, clamped, serialized. **Shipped** (Python dense
  lists, not C++ — R7 deviation flagged, a 3x3 grid is too small to
  justify a native port yet; `to_dict`/`from_dict` serialize it).
- [ ] **Replaces/extends:** Generalizes `terrain_activity`/scars (which
  become *two fields* among many) and the region climate grid. NOT
  done — `terrain_activity`/`mining_scars`/`disaster_scars` and the
  climate grid remain their own separate stores; migrating them onto
  `FieldGrid` is future work, not attempted this pass.
- [ ] **Feeds:** *Everything.* "Trees don't exist; they emerge because
  the fields allow them" (det #1) — vegetation, wildlife, farming,
  settlement siting all read fields. This is the single most load-
  bearing Body item; A2–A11 largely become field-update rules once this
  exists. Two real consumers now shipped (fission-site selection AND
  migrant-draw dampening both read `population_density`, v1.27.0, see
  A20) — vegetation/wildlife/farming still do not read fields.
- [x] **Map visibility, v1.27.0** (explicit user request: "the map
  should change and evolve with the simulation... implement Part A
  items to be visible on the map itself"): `population_density` was
  real backend state with zero map representation. New toggleable
  "🗺️ fields" header button cycles a live heatmap overlay (off / soil
  moisture / soil fertility / population density) over the map canvas
  — the first two are A11/soil-fertility fields, not A1's, grouped
  into the same toggle since all three are DENSE fields (every tile/
  region has a value) that would fight the map's readability shown
  simultaneously, unlike the sparse scar overlays. `interface/api.py`'s
  `set_terrain` gained `moisture`/`soil_fertility`/`population_density`
  params; `_maybe_broadcast` now also resyncs on a `week_end` calendar
  boundary (none of the three fire a `TERRAIN_CHANGING_CATEGORIES`
  event of their own) plus a client-side 20s periodic re-fetch as a
  belt-and-suspenders freshness guarantee.
- [x] **Sequencing:** First. It's the substrate the rest of Part A
  writes to. Shipped ahead of A2-A11, per this line's own instruction.

### A2 — Interacting local-rule systems: CA / diffusion / reaction-diffusion [det #2] — PARTIAL

- [ ] **Status:** `terrain_evolution` does local forest activity;
  wildlife has local rules; no diffusion or reaction-diffusion engine.
- [ ] **Spec:** A small library of field operators — `diffuse(field,
  rate)` (heat, moisture, scent spread), `reaction_diffuse(a, b,
  params)` (vegetation patterning, disease fronts), `cellular_step(field,
  rule)` (fire spread, succession) — composed each tick over A1's
  fields. Forest succession (grass→bush→young→old forest, gated by
  sunlight/grazing/fire/soil/moisture) is the worked example from
  det_sys.md and the first consumer.
- [ ] **Data model:** operators are pure `(field(s), params) -> field`;
  a per-tick pipeline lists which run in what order.
- [ ] **Feeds:** succession (A-ecology), disease spread (A-biology), fire
  (A-disasters) all become operator pipelines rather than bespoke code.
- [ ] **Note:** This is where CPU cost concentrates — profile; the C++
  native store is the right home for the hot operators.

### A3 — Procedural generation as continuous runtime [det #3] — PARTIAL

- [x] **Status: shipped a first slice, v1.26.0** (roadmap Stage IV step
  28). The spec's own worked example: "ruins should form where
  settlements die." Before this pass a fully-decayed building was
  simply deleted (`RUIN_REMOVAL_TICKS`, `settlement/buildings.py`) —
  a dead settlement left literally no trace once its last ruin
  crumbled away. New `World.ruin_scars` (same scar-shaped-dict pattern
  as `mining_scars`/`disaster_scars`/`ritual_activity`): gained via
  `apply_ruin_scar` at both building-removal code paths (native fast
  path and pure-Python fallback), decays slowly weekly (~1.6 years to
  fully clear — by far the slowest of the four). Real consequence: a
  new building's site search (`Population._choose_build_site`) now
  biases toward a tile with a prior ruin — "the village rebuilds on
  old foundations." Added as a 4th axis to A19's `location_character`
  unification. `terrain_evolution`, road paving, lake-level walk stay
  continuous as before; rivers/erosion (mutating `Tile.elevation`,
  immutable and native-store-backed) remain explicitly NOT attempted —
  the biggest remaining piece, flagged follow-up, same as prior
  CLAUDE.md notes. Settlements/cultures still evolve via LLM, not
  deterministic procgen.
- [ ] **Spec:** Audit every "generated once at world creation" call and
  ask "should this keep evolving?" Rivers should re-carve as erosion
  (A-hydrology) shifts elevation; ruins should form where settlements
  die (shipped, see above); roads already pave — extend the pattern.
  The principle: world-gen is just tick 0 of the same rules that run
  forever.
- [ ] **Feeds:** a world that looks different after a sim-year even with
  no humans — the terrarium's baseline aliveness.

### A4 — Continuous deterministic systems vs scripted events [det #4] — PARTIAL

- [ ] **Status:** weather/climate/wildlife/disasters are continuous;
  agriculture, infrastructure, economy, information still partly
  event-driven.
- [ ] **Spec:** Convert remaining scripted/event subsystems to
  continuous field/rule updates. Economy → resource/price fields that
  flow (A-graphs); agriculture → fertility/moisture field consumption;
  information → propagation on the social graph (A17). Nothing "fires";
  everything *flows and crosses thresholds*.
- [ ] **Feeds:** removes the "isolated incident" texture the prior audits
  flagged; events become threshold-crossings of continuous state.

### A5 — Capabilities/affordances over object classes [det #5] — MISSING

- [x] **Status:** **Shipped a first slice, v1.16.0** (roadmap Stage IV
  step 18). New `world/affordances.py`: the exact closed `AFFORDANCE_
  TAGS` vocabulary named in this spec, plus `BUILDING_AFFORDANCES` —
  `BuildingKind` (the one existing entity class with a real foundable/
  standing lifecycle) hand-tagged with which affordances its own
  existing identity/mechanics already imply (a GRANARY already
  `can_store_food`, a FORGE already invokes heat/tools, etc.).
- [x] **Spec:** Hand-tagged this pass (not yet derived from A12
  properties — A12 doesn't exist yet, see below). `BuildingKind` stays
  exactly as it is (closed enum, native-store-mirrored) — this attaches
  an ADDITIONAL, purely-Python, purely-additive tag-set alongside it,
  per the spec's own "wrap, don't replace" framing.
- [ ] **Data model:** Scoped down from the spec's literal `Entity.
  affordances`/`Entity.properties` per-instance fields (a real
  generalization to every entity kind, not just buildings) — this pass
  is a class-level `dict[BuildingKind, frozenset[str]]`, not per-
  instance state. `Entity.properties` (physical properties feeding A12
  material science) explicitly NOT built this pass — real, larger
  follow-up, flagged.
- [x] **Replaces/extends:** confirmed — zero changes to `BuildingKind`
  or any native-store code; wraps it entirely as external data.
- [x] **Feeds:** wired — see A6 below.

### A6 — Exposed affordances for discovery [det #6] — MISSING

- [x] **Status:** **Shipped a first slice, v1.16.0**, alongside A5 (same
  module). `affordances_present(standing_kinds)` — "what here can_X?" —
  aggregates affordance tags over a settlement's actually-standing
  buildings. `discover_combinations(present_tags)` — "what combination
  of affordances would achieve Y?" — a small closed `KNOWN_
  COMBINATIONS` registry (5 entries: e.g. `can_carry_water` +
  `can_store_food` → `irrigation_store`, `can_conduct_heat` +
  `can_sharpen` → `tempered_tools`) returns every entry genuinely
  achievable from what's standing right now.
- [x] **Spec:** the query layer is real and deterministic — a
  combination is only "discoverable" if both its required tags are
  actually present among standing buildings, not asserted by the LLM.
  The "physically coherent" validation is structural (the registry
  itself only contains pairs judged coherent at authoring time), not a
  runtime physics check — a real but narrower interpretation of
  "validates whether a proposed combination is physically coherent"
  than a general-purpose coherence engine would be.
- [x] **Feeds:** Innovation's generate-step wired — `llm/ontology.py`'s
  `build_propose_prompt` gained an optional `discoverable_combinations`
  param, populated at `_maybe_schedule_ontology_proposal`'s call site
  from the settlement's own standing buildings, grounding the proposal
  prompt in real physical affordances alongside (not replacing) the
  existing prosperity/pressure grounding. The validate-step half
  (Innovation's deterministic re-verification, `validate_hook`, cross-
  checking a PROPOSED concept's claimed mechanism against this layer)
  is explicitly NOT attempted this pass — real follow-up, flagged; this
  slice covers the harder/more novel generate-step half per the spec's
  own framing ("the prerequisite that lets Innovation discover
  unprogrammed combinations").

### A7 — Grammar-based procedural systems [det #7] — MISSING (deterministic form)

- [x] **Status:** The LLM does architecture/ritual/language/myth
  creatively; there's no *deterministic* grammar layer.
  **Shipped a first slice, v1.25.0**, all three deterministic domains
  in one batch (explicit user decision — accepted the doc's own
  default split below, and "do everything" rather than one domain):
  `world/dialect_grammar.py` (rewrite rules over an existing coined
  term — a fissioning daughter settlement inherits a few of its
  origin's terms, each independently drift-mutated), `world/layout_
  grammar.py` (a settlement's stable radial/linear/clustered style
  biases `Population._choose_build_site`'s existing road/resource
  scoring), `world/architecture_grammar.py` (a deterministic per-
  building-instance structural descriptor, distinct from `world/
  materials.py`'s per-KIND-only "Built of" line).
- [ ] **Spec:** Add L-systems / graph grammars / production rules for the
  systems where deterministic generativity beats an LLM call:
  settlement layout (graph grammar over terrain+roads), architecture
  (shape grammar), language/dialect drift (rewrite rules over a lexicon),
  ritual/recipe structure (production grammar). The LLM *seeds and names*;
  the grammar *expands and varies* deterministically and cheaply.
  **Still open**: none of the three are a full graph/shape grammar —
  layout is a scoring bias over the EXISTING site-search, architecture
  is a fixed three-slot production (roof/wall/ornament), dialect is
  one-rule-per-call over a single term, not a recursive rewrite system.
  Ritual/recipe structure (the spec's fourth named domain) explicitly
  NOT attempted — it's closer to "meaning," the doc's own carve-out for
  staying LLM-authored. Rules being themselves LLM-proposable (ties to
  Innovation) also not attempted — every rule here is hand-authored.
- [ ] **Data model:** per-domain grammar (axiom + production rules +
  constraints); rules can themselves be LLM-proposed (ties to Innovation)
  but expansion is deterministic.
- [ ] **Feeds:** offloads infinite cheap variation from the LLM budget to
  deterministic generation — directly serves "all LLM budget to
  cognition" (LLM_Pillars).
- [x] **Design decision needed:** which domains get grammars vs. stay
  LLM-authored. My default: layout/architecture/dialect deterministic;
  myth/custom/law stay LLM (they need meaning, not just structure).
  **Resolved via `AskUserQuestion`**: accepted this default as-is.

### A8 — Evolutionary Innovation (generate→mutate→evaluate→select) [det #8] — PARTIAL

- [x] **Status:** **Shipped a first slice, v1.19.0** (roadmap Stage IV
  step 21). `ontology.py` already had propose/evolve/merge with lineage
  (*generate*); this pass adds a real *evaluate* + *select* loop on top
  — concepts now spread AND retire by evaluated survival, not adoption
  count alone.
- [x] **Spec:** *evaluate*: `evaluate_fitness(world, concept)` — "did
  adopters prosper?" read as the mean `Population.reputation` of a
  concept's living adopters relative to its origin settlement's living-
  population mean, a real deterministic signal already computed
  elsewhere in the codebase (Phase L). *select*: `run_selection`
  (monthly cadence, paired with the existing `abandon_stale` sweep)
  retires a `spreading`/`established` concept whose mean fitness over
  its last `FITNESS_EVALUATION_MIN_READINGS` readings falls below
  `FITNESS_UNFIT_THRESHOLD` (`status = "retired"`, distinct from
  `abandoned`); `fit_established_concepts`/`concept_fitness_weight`
  make `_maybe_schedule_ontology_evolution`'s evolve/merge parent pick
  a real fitness-WEIGHTED draw instead of flat-uniform, so fit concepts
  are genuinely more likely to become parents. Sandbox forward-sim
  (A-C's `simulation/sandbox.py`) as a fitness input, and grammar-based
  mutation (A7) as an alternate *generate* path, remain open — the
  existing LLM propose/evolve/merge is still the only generate
  mechanism.
- [x] **Data model:** `InventedConcept` gained `fitness_history`
  (bounded, `FITNESS_HISTORY_MAX`) and `generation` (0 for an original
  proposal, `max(parents) + 1` for evolve/merge) — `parent_ids` itself
  was already covered by the existing `lineage` DAG, not duplicated.
- [x] **Feeds:** wired — a fit concept is now more likely to be evolved/
  merged into a descendant, closing the "LLM proposes creatively, the
  deterministic loop selects ruthlessly" loop the spec names. Farming
  techniques/building layouts/governance/customs weren't singled out
  for special treatment — every `InventedConcept` regardless of
  category goes through the same real evaluate/select mechanism.

### A9 — Every subsystem producer + consumer (feedback loops) [det #9] — PARTIAL

- [ ] **Status:** Some loops exist (fire→scar→biome); many systems still
  write their own state and read only affinity/their domain (the
  recurring "collection not graph" finding from prior audits).
- [ ] **Spec:** The acceptance-gate made physical: every field/subsystem
  must both *read* upstream fields and *write* downstream ones. Fire→soil
  →vegetation→wildlife→settlement→pollution→ecology→behavior, as an
  explicit dependency graph. Reject any subsystem that only produces or
  only consumes.
- [ ] **Feeds:** density of feedback = combinatorial state growth (A23) =
  emergence. This is the Body-layer version of the whole prior-audit
  thesis.

### A10 — Ecology as interacting populations / food webs [det #10] — PRESENT-ish

- [ ] **Status:** Food webs / predator-prey feedback shipped (v1.3.26,
  Phase 3.D). Closest-to-vision system in Part A.
- [x] **Spec (deepen), nutrient cycling only:** **Shipped a first slice,
  v1.15.0** (roadmap Stage IV step 17) — `economy/farms.
  apply_nutrient_cycling(farms, herds)`: any `FarmGrid.soil_fertility`-
  tracked tile within `NUTRIENT_CYCLING_RADIUS` (Manhattan) of a
  `WildlifeGrid` herd gains a small per-tick fertility bonus scaled by
  herd size, bounded by `NUTRIENT_CYCLING_MAX_BONUS_PER_TICK` (several
  large overlapping herds can't instantly max out a tile) and by the
  existing 1.0 fertility ceiling. Called at week_end cadence from
  `World._tick_disasters` (same cadence as A11's `tick_hydrology`,
  same reasoning: bound the real-time cost of a full-grid-adjacent
  Python pass). Deliberately a standalone module function — reads
  `WildlifeGrid.herds` read-only, only ever touches tiles already
  present in `soil_fertility` (already-farmed-at-least-once tiles) —
  so it never touches either grid's native fast path
  (`_native_farm_grid_tick`/`_native_soil_fertility_*`/the wildlife
  grazer native port) and carries zero native/fallback parity risk by
  construction, verified anyway via `scripts/verify_native_soak.py`.
  Migration, competition, decomposition, pollination (→ vegetation),
  and habitat formation (reads fields, writes carrying capacity) are
  explicitly NOT attempted this pass — real, larger follow-ups, not
  silently dropped; "fold the existing food web onto the A1 field
  substrate" as one coupled system also remains open.
- [x] **Feeds:** nutrient cycling closes a loop into farming — a farm
  sited near sustained wildlife activity now measurably out-recovers
  ordinary fallow rest. Migration giving Nature-the-pillar something to
  perceive and react to remains open (needs the migration sub-item).

### A11 — Continuous hydrology [det #11] — PARTIAL

- [ ] **Status:** Rivers carved once & static; lake levels random-walk;
  floods temporarily expand water. No runoff/groundwater/erosion.
- [ ] **Spec:** Make water a field (A1): precipitation → surface water →
  flows downhill by elevation (network-flow) → pools, infiltrates
  (groundwater field), evaporates (climate-coupled), erodes elevation
  (feeds back into terrain → re-carves rivers, A3). Watersheds emerge
  from the elevation field rather than being carved once.
- [ ] **Data model:** `fields['surface_water']`, `fields['groundwater']`,
  coupling to `terrain.elevation` (now mutable).
- [ ] **Feeds:** agriculture (irrigation, drought), settlement siting,
  disasters (flood/drought as field extremes), ecology (moisture). One
  of the highest-leverage A-items: water touches everything.
- [x] **Map visibility, v1.27.0**: `HydrologyField.moisture` was a
  real full per-tile grid with zero map representation (only the
  settlement-average "Soil moisture" stat tile existed). Now a live
  map heatmap option under the same "🗺️ fields" toggle A1's note
  describes — see that entry for the shared mechanism.

### A12 — Material science / physical properties [det #12] — MISSING

- [x] **Status:** **Shipped a first slice, v1.17.0** (roadmap Stage IV
  step 19). New `world/materials.py`: `Material` (all ten named
  properties, each 0..1) and a small closed `MATERIALS` registry (wood/
  stone/clay/metal/fiber), each hand-authored with real-world-plausible
  relative ordering (stone harder/denser/less flammable than wood,
  metal most conductive, fiber most flammable-and-workable-but-least-
  durable).
- [x] **Spec:** `BUILDING_MATERIALS` assigns each of A5's tagged
  `BuildingKind`s its primary material (grounded in each kind's own
  existing docstring identity — wood huts/docks, stone forges/bridges,
  worked metal at a forge/factory). `derive_affordances(material)` is
  the real "hard+workable → can_sharpen, flammable → can_burn" bridge
  the spec names, deliberately partial (only the axes that genuinely
  follow from raw material, not shape-derived affordances like
  `can_store_food`).
- [x] **Data model:** class-level `dict[BuildingKind, str]` +
  `dict[str, Material]`, not the spec's literal per-instance `Entity.
  material: Material` (a real generalization to every entity kind, not
  just buildings — flagged follow-up, same scope-down A5 itself took).
  `world.affordances.BUILDING_AFFORDANCES` (A5's hand-tagged set) now
  has a real properties-derived UNION alongside it via `materials.
  building_affordances(kind)` — hand-tagging never disappears, it's
  extended.
- [x] **Feeds:** wired — `_maybe_schedule_ontology_proposal`'s A5/A6
  affordance query (step 18) now reads `materials.building_
  affordances` instead of the bare hand-tagged set, so a material-
  driven combination (e.g. a metal FORGE's `can_conduct_heat` genuinely
  following from conductivity, not just a hand tag) is reachable by
  Innovation's generate-step too. A13's chemistry/reaction system
  actually consuming these properties remains open, flagged.

### A13 — Chemistry / reaction system [det #13] — MISSING

- [x] **Status:** **Shipped a first slice, v1.18.0** (roadmap Stage IV
  step 20). New `world/chemistry.py`: exactly the doc's own three
  worked examples, reinterpreted against A12's real registry — clay +
  heat → ceramic, ore + heat → metal, fiber + water_and_time →
  cured_fiber (the "plant + water + time" process, fiber
  tanning/curing). All three products are real, fully-propertied
  `Material` entries in `world.materials.MATERIALS`, not a special
  second-class output type.
- [x] **Spec:** `discover_reactions(available_materials, present_
  affordances)` is the real "what does X produce under Y?" query —
  conditions (`heat`/`water_and_time`) are themselves derived from the
  A5/A6/A12 affordance layer (`can_conduct_heat`/`can_burn` imply
  heat; `can_carry_water` implies water_and_time), so a settlement
  needs the right MATERIAL and the right STANDING BUILDINGS, not a
  flag set by hand.
- [ ] **Data model:** Scoped down from the spec's literal `ReactionRule
  (reactants, conditions, products, rate)` + "a deterministic reactor
  that fires rules when conditions meet" (i.e. an automatic tick-loop
  mechanism that mutates world state) — this ships the QUERY half only
  (`ReactionRule(reactant, condition, product)`, one reactant per
  rule, no rate/no automatic firing). A real reactor that changes a
  standing building's actual material after the fact is flagged,
  larger follow-up work needing its own design pass.
- [x] **Feeds:** wired into Innovation's generate-step exactly like
  A5/A6's `discoverable_combinations` — `llm/ontology.py`'s `build_
  propose_prompt` gained a `discoverable_reactions` param, populated at
  `_maybe_schedule_ontology_proposal`'s call site from the same
  standing-building query already computed for step 18/19.

### A14 — Layered organism biology [det #14] — PARTIAL

- [x] **Status:** **Shipped a first slice, v1.21.0** (roadmap Stage IV
  step 23), the doc's own worked example — "immune response (illness
  resistance as state, not a coin flip)". Hunger/energy/illness/aging
  are still discrete otherwise; this pass adds the one real coupled
  subsystem named explicitly in the spec, not the full six-subsystem
  model.
- [x] **Spec:** `Agent.immune_strength`, a real continuous 0..1 state —
  metabolism/nutrition (hunger) and rest (energy) pull it toward a
  target each tick via exponential smoothing (a real physiological
  lag, not instantaneous); actively fighting an infection drains it
  further (the reverse coupling). Modulates (never replaces)
  `SICKNESS_TRANSMISSION_CHANCE_PER_TICK`/`SICKNESS_DEATH_CHANCE_
  PER_TICK`, centered so the neutral baseline is a true no-op against
  every existing tuned rate. Stress/reproduction/development/injury-
  recovery/sleep — the spec's other five named subsystems — remain
  open, explicitly flagged, not silently folded into this one.
- [x] **Feeds:** disease is now measurably immune-state-dependent, not
  a flat coin flip, for the one axis (infection resistance/survival)
  this slice covers. Genetics (A15, v1.20.0) already acts on the
  trait layer immune_strength itself doesn't touch; a genetic
  contribution to baseline immune_strength (rather than only
  nutrition/rest) is a real, flagged future connection, not built
  this pass. Nature/Humans pillars perceiving this new state directly
  and a genuine immune-vs-pathogen (not just resistance-scalar)
  dynamic remain open.

### A15 — Genetic inheritance / mutation / drift / selection [det #15] — MISSING

- [x] **Status:** **Shipped a first slice, v1.20.0** (roadmap Stage IV
  step 22), scoped to humans — the doc's own "humans slowly vary too"
  half. Trait inheritance was blend+noise (v0.87.6); replaced with real
  diploid genetics: `Agent.genome: dict[trait, (allele_a, allele_b)]`,
  `traits` (the phenotype every consuming call site already reads)
  now the mean of its two alleles.
- [x] **Spec:** real sexual recombination (a child's allele per trait
  per parent is independently drawn from that parent's OWN two
  alleles — real genetic drift, not an average) + mutation
  (`GENOME_MUTATION_CHANCE` per allele) + drift, over the four existing
  `TRAIT_RESILIENCE`/`SOCIABILITY`/`AMBITION`/`OPENNESS` axes.
  *Natural selection* (differential survival/reproduction from real
  fitness) needed no new mechanism — these traits already causally
  affect survival/reproduction odds (H6/"traits mechanically
  consumed," resilience's starvation/predator-death tolerance,
  sociability's reproduction pairing) — genetics just gives that
  pre-existing selection pressure a real heritable substrate to act
  on, closing "no authored progression" honestly rather than adding a
  second parallel fitness system. Founders now genuinely vary at
  spawn (`seed_founder_genome`) — every prior founder started flat
  0.0 on all four axes; this closes that as a real side effect.
- [x] **Data model:** `Agent.genome` (not a literal `ndarray` — a small
  dict of `(float, float)` pairs, matching the existing trait-axis
  shape rather than introducing a numpy dependency for four values);
  `_agent_allele_pair`/`_inherited_genome_and_traits` are the
  expression/inheritance functions. A genome-less legacy agent (any
  pre-A15 snapshot) reads as "homozygous at its current phenotype" —
  inheritance stays total, never a crash or skipped axis.
- [ ] **Feeds:** scoped to humans this pass — wildlife/animal genetics
  (the doc's "species adapt over generations"/domestication half,
  A14's organism-biology layer as a prerequisite for non-trait genes)
  remain open, explicitly flagged. `world.wildlife.SpeciesVariant`
  (Vision item 4.2) stays descriptive-only, not wired to this — a real
  future bridge, not attempted here to avoid `AnimalHerd`'s native-
  index parity risk (same reasoning that deferred it originally).

### A16 — Graph representation + graph algorithms [det #16] — PARTIAL (scoped, v1.4.9)

- [ ] **Status:** The pairwise ledger is an edge store; economy/farms
  have adjacency; but no graph *algorithms* (centrality, flow,
  community detection) are run.
- [x] **Spec:** Represent relationships, institutions, economy, trade,
  transport, beliefs, tech, ecosystems as explicit graphs and *analyze*
  them: trade as network-flow, influence as centrality, factions as
  community-detection, tech as a dependency DAG, information as
  propagation (A17). Cheap, deterministic, and a rich Emergence-API
  source. **Shipped**: `world/graph_algorithms.py`'s weighted-degree
  centrality over the existing relationship ledger (`build_
  relationship_graph`/`degree_centrality`/`most_central_agent`).
  Community detection was already shipped as `InstitutionKind.FACTION`
  detection (v0.80.0) under a different name — confirmed, not
  duplicated. Trade-as-network-flow, tech-as-DAG, and information-
  propagation (A17) are NOT built — centrality is the only algorithm
  shipped.
- [x] **Feeds:** the pillars perceive *structural* facts ("this family
  became the trade hub," "the village split into two communities") they
  currently can't see. Graph metrics are high-signal, low-token
  observations — ideal cognition inputs. **Shipped**: `Settlement.
  social_hub_agent_id` + `SimulationEngine._detect_social_hub` (season
  cadence, edge-triggered) emits an A22 `unexplained_shift` observation
  when the structural fact changes — feeds the Emergence API exactly
  as this line asks.

### A17 — Information as a deterministic ecosystem [det #17] — PRESENT-ish

- [x] **Status:** Rumor spread/distortion + `invention_knowledge`
  teach/lose/rediscover + ontology lineage exist — the closest to vision.
  **Shipped a first slice, v1.22.0**: new `world/memetics.py`'s
  `weighted_spread_target`/`propagation_weight` — the one piece every
  future propagation mechanism needs and none of today's had, a
  reusable "who catches this next" weighting over the real
  relationship/trust graph (Phase 0's `Ledger`), replacing uniform
  random selection. Real production proof: ontology concept adoption
  spread (`SimulationEngine._maybe_spread_concepts`) now spreads
  preferentially to people close to an existing adopter instead of a
  flat `rng.choice` over every eligible core-cast member.
- [ ] **Spec (deepen):** unify knowledge/rumor/tradition/belief/song/map/
  custom/technique into one propagation model on the social graph (A16):
  each unit spreads, mutates, decays, competes, merges, dies by the same
  rules. Truth is not privileged — false beliefs propagate if fit.
  **Still open**: only ontology-concept spread uses the new weighting
  this pass; rumor/tradition/belief/song/technique staying on their
  own independent mechanisms (each mature and deliberately untouched)
  is the explicitly flagged remainder — folding them onto
  `memetics.py`, plus a shared mutate/decay/compete step and a real
  fitness-vs-truth axis for rumors, is real follow-up work.
- [ ] **Feeds:** Village/Humans pillars perceive a living memeticscape;
  cultural evolution becomes measurable.

### A18 — Events as composable reactions [det #18] — PARTIAL

- [x] **Status:** Some composite events; no general composer.
  **Shipped a first slice, v1.23.0**: new `world/reactions.py` +
  `SimulationEngine._maybe_tick_composite_reactions` — a real,
  general AND-combination engine (the fixed part) over a small closed
  registry of hand-authored `CompositeReaction`s (the open-ended
  part), same "engine is general, content is data" split `TriggerRule`
  already established for single triggers. One worked reaction ships
  ("Desperate Times": `drought` + `feud` + `food_shortage`, all
  independently tracked Body signals, crossing simultaneously
  escalates a family feud into an immediate relationship rupture
  between the two families — real, bounded, deterministic).
- [ ] **Spec:** An event is a *reaction* fired when a combination of
  field/social/economic conditions crosses a threshold — not a scripted
  incident. A drought-field + a feud-edge + a food-shortage compose into
  a raid nobody hand-authored. A small condition→consequence rule engine
  (the trigger→effect vocabulary from the terrarium doc, generalized to
  the Body).
  **Still open**: only one hand-authored reaction exists (no general
  authoring system yet — a village can't propose its OWN combinations
  the way `TriggerRule` is LLM-authored); the doc's own "raid" example
  is scoped down to a relationship-rupture consequence rather than a
  new combat/raid mechanic, flagged as real follow-up work.
- [ ] **Feeds:** "entirely new emergent situations without handcrafted
  event chains" — the combinatorial heart of Body-layer emergence.

### A19 — Persistent spatial memory [det #19] — PARTIAL

- [x] **Status:** `terrain_activity`/`mining_scars`/`disaster_scars`
  track some per-location history; not general.
  **Shipped a first slice, v1.24.0**: new `World.ritual_activity`
  (same shape as `mining_scars`/`disaster_scars`) is a fourth tracked
  axis, gained when a shrine-boosted festival gathering happens on a
  tile. New `world/spatial_memory.py`'s `location_character(world, x,
  y)` is the real unification the doc calls for — one read-side query
  over the three existing per-tile dicts (`mining`/`disaster`/
  `ritual`), not three independent lookups. Real consequence: a shrine
  tile with prior ritual activity amplifies the NEXT festival held
  there (`Population.hold_festival`) — the doc's own "a ritual site
  draws ritual" worked example, scoped to a magnitude effect.
- [ ] **Spec:** Every location accumulates a bounded history vector:
  traffic, battles, rituals, pollution, fertility, disasters, ownership,
  construction, ecology. Places gain *character* that influences future
  simulation (a battle site stays scarred; a ritual site draws ritual).
  **Still open**: only 3 of the spec's 9 named axes are unified
  (mining/disaster/ritual); traffic/pollution/fertility/ownership/
  construction/ecology remain separate or unbuilt — `FarmGrid.soil_
  fertility`/the A1 field substrate are a different shape (continuous
  fields, not sparse per-event dicts) and folding them in is real
  follow-up work, flagged in `world/spatial_memory.py`'s own docstring.
- [ ] **Data model:** `fields['history_*']` or a per-tile bounded record;
  ties to A1.
- [ ] **Feeds:** the "unlucky house," folklore sites, why settlements
  re-form where they did — places as actors, and rich pillar perception.

### A20 — Multi-scale simulation [det #20] — PARTIAL

- [x] **Status: extended, v1.27.0** (roadmap Stage IV step 29). A1's
  `World.fields` `population_density` region field previously had
  exactly one consumer (`_maybe_favor_uncrowded_fission_site`) and no
  UI visibility — both real gaps for a "multi-scale" claim. New
  `MIGRANT_DENSITY_DAMPENING` (`agents/population.py`): the same
  region-level computed field now also dampens migrant draw at an
  already-crowded settlement (`_maybe_welcome_migrant`'s new `region_
  population_density` param), a genuinely independent second consumer
  in a different subsystem. The field is also now a real live map
  overlay (see A1/A11 note below) — the region aggregate is visible,
  not just consumed. A brand-new second field, and the "culture
  aggregates settlements' information-ecosystems" half of the spec,
  remain open, flagged.
- [ ] **Status (pre-v1.27.0):** agent/settlement/world scales exist as separate objects;
  higher scales aren't *emergent aggregations* of lower ones.
- [ ] **Spec:** Regional/world behavior should *aggregate* from local
  fields/graphs rather than being separately simulated: a "region"
  is a computed summary of its tiles' fields; "culture" aggregates
  settlements' information-ecosystems. Zoom levels read the same
  substrate at different resolutions.
- [ ] **Feeds:** coherent world-scale story from local rules; lets a
  pillar reason at the scale its attention is at.

### A21 — Temporal compression (event→legend→myth) [det #21] — PARTIAL

- [x] **Status: first slice shipped, v1.28.0** (roadmap Stage IV step
  30). Prior audit found `Settlement.folklore` had no structured
  subject to detect legends against — resolved by NOT touching
  folklore at all: new `world/legends.py` + `llm/legend.py` build a
  SEPARATE, parallel pipeline reusing A22's already-structured
  Emergence API stream instead (`World.emergence_log`, whose entries
  already carry a real `subsystem` tag and `settlement` name — no raw-
  text heuristic needed). Deterministic aggregation (`detect_legend_
  candidate`: N recent observations from the same subsystem, for the
  same settlement) → LLM narrates the accumulated pattern into one
  legend sentence → stored in new `Settlement.legends` (capped,
  distinct from `folklore`) → deterministic one-legend-per-subsystem-
  lifetime dedup (a subsystem that already produced a legend is
  skipped in future detection passes). This is exactly the doc's own
  "deterministic event-aggregate -> LLM-narrate-significant ->
  deterministic-legend-detection" shape. New monthly job (`_maybe_
  schedule_legend_detection`), zero LLM cost most months (same "skip
  when the precondition guarantees nothing" discipline as folklore/
  invention). UI: new "Legends" panel, `legend` event-feed icon.
- [ ] **Status (pre-v1.28.0):** chronicle→documentary→culture-digest, folklore, era
  branches exist — a real strength.
- [ ] **Spec (deepen):** the "legends into myth/tradition/institution"
  half remains open — a formed legend doesn't yet feed back into
  tradition/religion/institution formation, or ground future
  chronicle/dialogue/folklore prompts as "already legendary" context
  (the way `place_names`/`beliefs` already ground other prompts).
  Folklore itself also remains untouched/un-unified with this new
  mechanism — "replacing today's more ad-hoc chronicle/folklore
  chain" is still aspirational, not attempted this pass.
- [ ] **Feeds:** years remain cognitively manageable; the knowledge tree
  (terrarium doc 3.2) is this pipeline's output.

### A22 — The Emergence API [det #22] — SHIPPED (scoped, v1.4.8)

- [x] **Status:** The highlight/anomaly log prototypes the idea; not a
  per-subsystem structured stream. **Now superseded**: `world/
  emergence.py` + `World.emergence_log` is the real structured stream;
  `highlights` still exists unchanged underneath it (mirrored into
  emergence via `_HIGHLIGHT_EMERGENCE_MAP`), not replaced.
- [x] **Spec:** Every deterministic subsystem exposes a stream of
  *interesting* observations — anomalies (metric off its rolling norm),
  novel combinations (affordance/reaction never seen), bottlenecks
  (network-flow saturation), unexplained shifts, opportunities — tagged
  by which pillar would care. Not raw state: *curated salience*.
  **Shipped**: all five `OBSERVATION_KINDS` implemented; producers
  today are highlights (8 kinds), the reflection hypothesis lifecycle,
  ontology concept promotion, a settlement materials-bottleneck
  detector, and (v1.4.9) the social-hub graph-centrality detector — NOT
  literally "every deterministic subsystem" yet, more producers are
  future follow-ups onto the same stream.
- [x] **Data model:** `subsystem.emergence_events() -> list[Observation]`
  with type, magnitude, location, pillar-relevance. **Shipped** as
  `world.emergence.make_observation()` (kind/subsystem/summary/
  pillars/magnitude/settlement/data), validated against closed
  `OBSERVATION_KINDS`/`PILLARS` vocabularies.
- [x] **Feeds:** **this is the pillars' senses** (Part C). It's the
  single most important Body↔Mind interface item — without it, cognition
  drowns in raw data or eats hand-picked slices. Build it alongside the
  pillar refactor, not after. The stream itself shipped first (v1.4.8);
  B1 (v1.5.0) is the first pillar refactor step, but no pillar reads
  `emergence_log` yet — that's still ahead (Stage II, B2 onward).

### A23 — Composability over content [det #23] — PRINCIPLE

- [ ] **Spec:** A standing design rule, not a feature: every new Body
  subsystem must add *interactions* with existing systems (read/write
  shared fields, A9), so world-states grow combinatorially not linearly.
  Fold into the acceptance gate (C4). Reject isolated mechanics at review.

### A24 — Physical consistency; no pillar violates rules [det #24] — PRESENT

- [ ] **Status:** The deterministic-validation discipline is already
  core (every LLM proposal validated before it moves a number).
- [ ] **Spec:** Keep it inviolable as the pillars gain power (Part B).
  Every pillar intention passes through Body validation. This is the
  guardrail that makes open-ended cognition safe.

### A25 — LLM exclusively cognition [det #25] — PRESENT (aspirationally)

- [ ] **Status:** Body/Mind discipline is established; but LLM budget
  still partly spends on things a grammar (A7) or field (A1) could do.
- [ ] **Spec:** Audit every LLM job: if a deterministic/procedural/RNG
  system could produce it, move it there (grammars, fields, propagation),
  freeing budget for genuine cognition. This is the explicit bridge to
  Part B: **Part A exists so Part B can have the whole budget.**

---

# PART B — THE COGNITIVE MIND (LLM_Pillars.md, five pillars)

Covered in depth in FIVE-PILLARS-REFACTOR-2026-07-22; summarized here so
the master is complete, with the Body-dependencies made explicit.

### B1 — The Pillar abstraction — SHIPPED, all five pillars (v1.5.3) — the keystone

- [x] Five persistent conscious entities (Humans, Village, Nature,
  Innovation, Reflection), each with identity, self-model, world-model
  (typed theories, confidence, observations-vs-hypotheses), living memory
  (consolidate/forget/reinforce/reinterpret), objectives, inbox/outbox.
  Refactor the ~55 scattered jobs into acts of these five. **Depends on
  A22** (senses) and **A16** (structural perception). **Shipped for all
  five pillars** (explicit user directive: "you have only built nature
  pillar up until now, build all the other pillars"): `cognition/
  pillar.py` gained `default_village_pillar`/`default_humans_pillar`/
  `default_innovation_pillar`/`default_reflection_pillar`; `World.
  village_pillar`/`humans_pillar`/`innovation_pillar`/`reflection_
  pillar` each proven against ONE existing representative job per
  pillar (`_maybe_schedule_beliefs`, `_maybe_schedule_narrative_
  direction`, `_maybe_schedule_ontology_proposal`, `_maybe_schedule_
  reflection` respectively) — the same "prove the shape against a real
  production call site" discipline B1 established for Nature, not
  four independent designs. Still NOT attempted: real consolidate/
  forget/reinforce memory semantics (still a capped FIFO), inbox/
  outbox delivery (B4), and the full "refactor ~55 scattered jobs" —
  each pillar has exactly one representative job wired, deliberately,
  not all jobs touching that pillar's domain.

### B2 — The continuous cognitive cycle — SHIPPED, all five pillars (v1.5.3)

- [x] Each pillar runs observe→interpret→remember→plan→act→reflect,
  resumed across cognitive turns (not timer-fired jobs). Bounded
  attention, working memory, uncertainty, incomplete knowledge — a mind,
  not an oracle. **Shipped for all five pillars**: the observe/interpret
  split, backpressure-scaled deferral, and cycle-close logic Nature's
  `_maybe_schedule_nature_mind` originated were extracted into three
  shared engine helpers (`_pillar_observe_turn`/`_pillar_interpret_
  backpressured`/`_pillar_close_cycle`, parameterized by pillar name)
  and reused, unchanged, by all five representative jobs — one real
  mechanism, not five copies. Same "two of six named stages are
  separately persisted stops, the other four bundle into `interpret`'s
  single call" simplification as the Nature-only version, now applied
  uniformly.

### B3 — The Attention Scheduler — SHIPPED, all five pillars (v1.5.3)

- [x] One budget arbiter over all five (round-robin deep + shallow-
  frequent), wired to the **existing dynamic pacing** so sim-time slows
  when cognition lags (verified present). Priority from A22 salience +
  staleness + player focus + inter-pillar messages. **Shipped for all
  five pillars**: `cognition/attention.py`'s `compute_priority()`/
  `backpressure_fraction()` are consumed identically by all five
  representative jobs via `_pillar_interpret_backpressured`. Round-
  robin is still trivial in the sense that each pillar has exactly one
  job checking in, not the full "~55 jobs" arbitration; `message_
  count`/`player_focus` still both read 0 (no B4 message bus, no
  player-focus mechanism) — real, ready inputs, unchanged from the
  Nature-only pass.

### B4 — Inter-pillar consciousness bus — SHIPPED (roadmap Stage III step 11, v1.9.0)

- [x] Typed messages (observation/question/theory/hypothesis/warning/
  request/discovery/disagreement) between pillars; the four influence-
  arrows (Nature→Village→Innovation→Village, Reflection observing all)
  made real; disagreement persists and drives behavior. **Shipped**:
  `Pillar.send_message`/`receive_message` (bounded `INBOX_MAX`/
  `OUTBOX_MAX=8`) + `SimulationEngine._send_pillar_message` (builds via
  `cognition.pillar.make_message`, validates `kind` against the closed
  vocabulary). Delivery rides the existing B2/C1 perception channel:
  `_pillar_observe_turn` now merges undelivered `inbox` messages into
  the same salience-ranked competition for bounded `working_memory` as
  Emergence API observations (a per-kind synthetic magnitude —
  `disagreement`/`warning` outrank routine traffic); only messages that
  actually get delivered are removed from `inbox`, so an outranked
  message genuinely persists for a future turn. All three real arrows
  wired at their natural existing trigger points: Nature→Village (a
  genuinely new nature belief), Village→Innovation (a genuinely new,
  confident settlement belief), Innovation→Village (a newly registered
  concept). Reflection→"observing all" needed no new wiring — it
  already reads all four pillars' Body state directly (`_detect_
  reflection_pattern`), which already satisfies "observing all" without
  a message bus. `Pillar.disagrees_with()` gives "disagreement" a
  mechanical, non-semantic definition: does the receiving pillar already
  hold a confident (>=0.5) theory whose SUBJECT LABEL substantially
  overlaps the incoming one? Used at the Nature→Village send site
  (Village→Innovation/Innovation→Village default to `theory`/
  `discovery` — no natural "does the receiver already have an opinion"
  check exists at those two sites yet, flagged as a smaller follow-up).

### B5 — Innovation as conscious scientist — PARTIAL, first version shipped (roadmap Stage III step 12, v1.10.0)

- [x] Ontology propose/evolve/merge exists; make it *query affordances
  (A5/A6) and reactions (A13) to invent unprogrammed combinations*, and
  wrap in the evolutionary loop (A8). B-Innovation is the LLM half; A8 is
  its deterministic selection. **Shipped, scoped against today's closed-
  hook vocabulary** (per this item's own note: "can ship a first version
  against today's closed-hook vocabulary and re-target later" — A5/A6/A8/
  A13 are Stage IV, not built yet). The real gap this pass closes:
  `_maybe_schedule_ontology_proposal` already gated itself on the
  settlement being "pressured" (`pattern_signal_counts` crossing
  `PATTERN_SIGNAL_BELIEF_THRESHOLD`) but never told the LLM WHICH
  pressure, so a genuinely pressured proposal was invented exactly as
  freely as an unpressured, prosperity-driven one — no real hypothesis
  was possible. Fixed: the dominant crossed signal (e.g.
  `materials_bottleneck`, `dispute_feud`) is now named in the prompt in
  plain language (`llm/ontology.py`'s new `PRESSURE_SIGNAL_LABELS`), and
  the model is asked for a genuine `hypothesis` field — the real problem
  or need its idea is meant to help with, or the literal "no specific
  problem" when it's just culture for its own sake (a legitimate answer,
  not a missing one). `InventedConcept.hypothesis` + `world_model_entry_
  id` (new fields) make this a real hypothesize-observe-revise loop, not
  a one-shot claim: when a concept's own real adoption lifecycle later
  confirms it (`established`) or refutes it (`abandoned`, the existing
  `abandon_stale` stale sweep), `world/ontology.py`'s new `_record_
  hypothesis_outcome` revises Innovation's OWN `world_model` belief
  about that exact concept in place (`revises_id`) — confidence up to
  0.85/status `observation` on confirmation, down to 0.1 on refutation —
  zero added LLM cost, the outcome is read off state (`status`,
  `adopter_ids`) that already exists. This is the concrete "track
  whether its own ideas actually worked" scientist behavior, scoped to
  the registry Innovation already has rather than waiting on Stage IV's
  affordance/reaction layer. Surfaced: `knowledge_tree()`'s concept
  entries append the hypothesis as plain-language context ("a hopeful
  answer to: ...") when one exists — real UI value in the existing
  🌳 knowledge-tree panel, no new panel needed. Evolve/merge (untouched
  this pass) and a genuine affordance/reaction query remain open,
  explicitly deferred to when Stage IV's substrate exists to query.

### B6 — Reflection as meta-scientist — PARTIAL, first version shipped (roadmap Stage III step 13, v1.11.0)

- [x] Reflection + self_tuning exist (falsifiable hypotheses, bounded
  sandbox-validated governor nudges). Extend `TUNABLE_GOVERNORS` to the
  major levers; add the advisory-proposal inbox (human-reviewed) for
  changes beyond governors; track whether its advice worked. **Shipped,
  scoped**: previously a supported hypothesis whose subject didn't
  exactly match one of two hardcoded governor labels was silently
  dropped — no governor to nudge meant no response at all, even though
  Reflection had already formed a real, evidence-backed belief. Two
  fixes, both real: (1) `SimulationEngine._governor_key_for_subject`
  matches a hypothesis subject against `TUNABLE_GOVERNORS` by PREFIX,
  not exact equality — `_detect_reflection_pattern`'s settlement-scoped
  subjects (`f"{label} in {settlement_name}"`, varies per settlement)
  can now reach self-tuning at all, not just the two global subjects
  that happened to match verbatim; `disease_outbreak_chance` (consumed
  by `Population._maybe_outbreak`'s new `chance_multiplier` param) is
  the worked example proving this actually closes the loop end to end.
  (2) `World.advisory_proposals` (new, capped-by-low-natural-volume
  append-only list) + `_schedule_advisory`: a supported hypothesis that
  STILL names no governor now gets a real LLM call asking Reflection
  for one short piece of free-text advice, logged with `status=
  "pending"`. `POST /advisory/{id}/review` (`status: accepted|
  rejected`) is the ONLY way that status changes — a human decision,
  never auto-applied to any mechanic, deliberately kept out-of-band
  from the sandboxed numeric self-tuning path. "Track whether its
  advice worked" is intentionally NOT attempted for the advisory path
  (there's no mechanical effect to measure an outcome against, unlike
  a governor nudge) — the human's own accepted/rejected marking IS the
  tracked outcome, not a further automated judgment. Dev-console-only
  surfacing (`advisory_proposals_recent` in `full_diagnostics()`), same
  depth as `self_tuning_actions_recent`.

### B7 — Humans: collective consciousness + coordinator — PARTIAL, first version shipped (roadmap Stage III step 14, v1.12.0)

- [x] One collective mind (mood/values/direction) + a capped pool of
  cheap per-NPC calls on dramatically-salient individuals (fold in the
  voice-pair machinery); everyone else deterministic. Individuality from
  the ledger + Body systems + occasional cheap calls. **Shipped a first
  version, scoped**: the two mechanisms this item names were both
  already real BEFORE this pass, just structurally unaware of each
  other. "One collective mind (mood/values/direction)" is `humans_
  pillar` itself, already B1-generalized against `_maybe_schedule_
  narrative_direction` (that job's own docstring already reads this as
  "B7's collective consciousness read literally," since `Settlement.
  mood` is the real aggregate of every living agent's `Agent.
  emotions`). "A capped pool of cheap per-NPC calls on dramatically-
  salient individuals" is core-cast cognition (`Population.
  core_agent_ids`, bounded by `llm_core_cast_size`) layered with the
  voice pair's own narrative-significance selection (`Population.
  maintain_voice_pair`) — also already real. The genuine gap this pass
  closes: `SimulationEngine`'s voice-pair-rotation call site logged a
  `voice_pair_change` event but never told the collective mind about
  it at all — Humans' own `self_model` had no record of who currently
  carries the village's voice, and the rotation never reached the
  Emergence API, so the collective mind's own `observe` turn couldn't
  perceive it either. Fixed: the rotation site now writes `humans_
  pillar.self_model["current_protagonists"] = [name_a, name_b]`
  directly (zero LLM cost — this is Humans' own persistent record of
  its current salient individuals, per B9's self-model framing) and
  emits a real `"opportunity"`-kind, `humans`-tagged Emergence API
  observation, so the rotation reaches the collective mind's next real
  `observe` turn as perceived context exactly like any other pillar's
  genuine news. This doc's own standing design decision (§"Two flags
  before building": "when the Humans collective consciousness and an
  individual NPC disagree, who speaks... individual acts locally,
  collective sets the mood/direction they're measured against") is
  respected structurally — `current_protagonists` is the collective's
  own AWARENESS of who's salient, never a channel that speaks or acts
  on an individual's behalf. Dev-console-only surfacing (reachable via
  `full_diagnostics()["humans_pillar"]`), matching every other pillar's
  internals — the rotation itself already had real main-UI visibility
  via the pre-existing `voice_pair_change` event log entry.

### B8 — Living memory & consolidation — PARTIAL, all five pillars (roadmap Stage II step 8)

- [x] Per-pillar: consolidate detailed experience into higher-level
  knowledge periodically; forget trivia; reinforce/reinterpret; connect
  into concepts. Keeps years cognitively manageable while preserving
  identity. (Human memory partly does this; generalize to all pillars.)
  **Shipped, scoped**: `Pillar.consolidate()` (`cognition/pillar.py`) —
  once `memory` reaches `MEMORY_CONSOLIDATE_THRESHOLD` (30, under the
  hard `MEMORY_MAX=40` FIFO cap), folds the oldest `MEMORY_CONSOLIDATE_
  BATCH` (8) raw notes into one condensed digest note. Real forgetting
  (individual notes gone) + a literal "connect into concepts" (several
  become one), zero LLM cost (matches "maximize emergence per LLM
  call"). Called once per closed cognitive cycle via `SimulationEngine.
  _pillar_close_cycle`, so all five pillars get it automatically.
  Deliberately NOT `reinforce`/`reinterpret` — that needs per-note
  salience/access tracking this pass doesn't add; flagged as a smaller
  follow-up, not the full B8 spec.

### B9 — Self-model & world-model per pillar — SHIPPED, all five pillars (roadmap Stage II step 4, generalized in the B1 pass)

- [x] Each pillar knows what it is, wants, how it changed, how it
  relates to the others (self-model); holds revisable evidence-backed
  theories, distinguishing observation from hypothesis, tracking
  uncertainty (world-model). The substrate for genuine "it can be
  wrong." **Shipped as part of B1's generalization** (v1.5.3/1.6.0):
  every pillar's `self_model`/`objectives` (identity/wants) and
  `world_model` (revisable, confidence-tracked, `status` distinguishing
  `observation`/`hypothesis`) shipped together with B1 — this item was
  effectively subsumed rather than a separate later step. "How it
  relates to the others" is NOT shipped — that's B4's inter-pillar
  message bus (inbox/outbox stay structurally present but empty).

---

# PART C — THE SEAM (Body ↔ Mind co-evolution)

Where LLM_Pillars.md and det_sys.md meet — the bidirectional interface.

### C1 — Perception channel (Body → Mind) — SHIPPED (roadmap Stage II step 9)

- [x] A22's Emergence API *is* this channel: curated observations flow to
  each pillar's observe() step. No pillar reads raw state; none is
  omniscient. Bounded, salience-ranked, pillar-tagged. **Shipped**: this
  was already structurally true for all five pillars since B2's
  generalization (`_pillar_observe_turn` reads `World.emergence_log`,
  never raw state) — bounded (`Pillar.WORKING_MEMORY_MAX=5`) and
  pillar-tagged (`pillar_name in obs["pillars"]`) held from the start.
  "Salience-ranked" did not: candidates were fed to `working_memory` in
  plain recency order, so `WORKING_MEMORY_MAX`'s FIFO eviction could
  silently discard a genuinely high-`magnitude` observation for a
  later-but-less-salient one. Fixed: candidates are now sorted by
  `magnitude` (descending, unranked last) before only the top
  `WORKING_MEMORY_MAX` are noted — a pillar's bounded attention is now
  deliberately spent on what matters most, not what happened to log
  most recently.

### C2 — Intention channel (Mind → Body) — PARTIAL, one gap closed (roadmap Stage II step 9)

- [x] Every pillar acts *only* by emitting intentions the Body validates
  and executes (invent tech, set custom, change law, reorganize
  institution, shift land use, domesticate, build, propose experiment).
  The deterministic layer executes and validates per its own rules.
  Partly exists (LLM proposals are validated); generalize to all pillar
  actions. **Audited every Body-touching write across all five
  representative jobs**: Village (`beliefs`) and Reflection
  (`reflection`) write only to their own Mind-state (theories/
  hypotheses), never Body — nothing to validate. Innovation (`ontology_
  proposal`) and Nature (`nature_mind`'s ecological-concept origination)
  already validate before writing (`ontology.validate_hook`/`is_near_
  duplicate`). Humans (`narrative_direction`'s dialect-drift term
  coining, `Settlement.lexicon`) was the one real gap — it wrote a
  brand-new persistent state entry with only a non-blank check, no Body
  validation at all. Fixed: new `narrative_direction.validate_coined_
  term()` rejects an exact case-insensitive duplicate of an
  already-coined term before the write, same discipline as `validate_
  hook`. Still PARTIAL in the sense the spec names (invent tech, set
  custom, change law, reorganize institution, shift land use,
  domesticate, build, propose experiment) — most of those aren't
  pillar-emitted intentions yet at all (they're separate deterministic/
  LLM mechanics outside the five-pillar refactor's current reach), not
  a validation gap this pass could close.

### C3 — Player ↔ Pillar chat — SHIPPED (roadmap Stage III step 10, v1.8.0)

- [x] Generalize `/ask-chronicler` (verified present) to `/ask/{pillar}`:
  ask any pillar what it believes/fears/plans/predicts/why, answered from
  its real self/world-model (can be wrong). Nudges enter cognition as
  weighable inputs, never commands; conversations are remembered (a light
  per-pillar player-model). Pillars may initiate contact. **Shipped**:
  new `llm/pillar_chat.py` (one shared prompt template, voiced per-pillar
  via `self_model["voice"]`), `GET /pillar/{pillar}`/`POST /ask/{pillar}`
  (`interface/app.py`), `SimulationEngine._schedule_pillar_answer` (same
  enqueue-now/apply-next-tick seam as the chronicler). `Pillar` gained
  `conversation_log`/`last_question`/`last_answer`/`last_answer_tick`/
  `pending` — "a light per-pillar player-model." The exchange is folded
  into the SAME pillar's next real `interpret` cognition call via
  `note_observation()` (the working_memory slot every representative
  job's prompt already reads via `emergence_observations`) — a genuine
  weighable input, never a direct belief write or overridden decision.
  Main-UI panel (a select + ask form under the explore menu), per the
  standing UI-surfacing workflow rule — this is explicitly player-
  facing, not dev-console material. "Pillars may initiate contact" is
  NOT attempted — flagged as real future scope, not silently dropped.

### C4 — The acceptance gate as law — PARTIAL

- [ ] "Every persistent state has a creator and a consumer; reject
  isolated mechanics; reject state no system observes." Enforce as the
  standing review rule for every A- and B-item, human- or LLM-authored,
  and as a runtime auditor retiring unread state.

### C5 — Co-evolution loop — the destination

- [ ] Body generates novel situations (A) → pillars perceive (C1), learn,
  re-model (B) → pillars act via intentions (C2) → Body executes,
  changing itself → new situations. Both layers increase each other's
  complexity over time without either violating its role. When this loop
  turns unattended, Hearthmind is the living terrarium.

---

# SEQUENCE (the whole thing, ordered)

**Phase 1 — Senses & substrate (unblocks everything):**
A22 Emergence API · A1 FieldGrid · A16 graph algorithms. The pillars
can't be minds without senses (A22), and the Body can't be continuous
without fields (A1).

**Phase 2 — The five minds (the refactor):**
B1 Pillar abstraction · B2 cycle · B3 scheduler (→ existing pacing) ·
B9 self/world-models · B8 consolidation. One pillar at a time, Nature
first. C1/C2 seam wired as each pillar lands. C3 player chat early
(cheap, high daily value).

**Phase 3 — Interaction (emergence turns on):**
B4 inter-pillar bus · B5 Innovation-as-scientist · B6 Reflection
advisory + extended self-tuning · B7 Humans collective+coordinator.

**Phase 4 — Deepen the Body (continuous world), each feeding A22:**
A11 hydrology · A2 CA/diffusion operators · A10 ecology-on-fields ·
A5/A6 affordances · A12 materials · A13 chemistry · A8 evolutionary
Innovation · A15 genetics · A14 organism biology · A17 information ·
A18 composable events · A19 spatial memory · A7 grammars · A3/A4
continuous procgen · A20 multi-scale · A21 temporal compression.
(Ordered by leverage; each ships to the Emergence API as it lands so
cognition feels it immediately.)

**Standing throughout:** A9 feedback loops · A23 composability · A24
consistency · A25 budget-to-cognition · C4 acceptance gate.

---

# THE ONE TEST

> After a week away, you open the UI, ask **Nature** what it fears; it
> answers from what's actually happening to its fields and species;
> you watch it warn **Village** unprompted; Village changes a **law**;
> **Innovation**, prompted by the pressure, invents a technique by
> combining affordances no one programmed; **Reflection** hypothesizes
> about the whole chain and proposes a nudge — and every step was
> executed through deterministic physics that no pillar could violate.

The day that runs end to end, both docs are satisfied at once: an
endlessly generative deterministic Body, five conscious Minds inhabiting
it, co-evolving into things you never wrote.

---

## Two flags before building

- **This is a large program, not a sprint.** The value is that Part A and
  Part B are separable and each is independently useful — a richer Body
  improves the current sim even before the pillars land, and the pillars
  improve cognition even on today's Body. Build so each phase ships value
  alone.
- **One decision I still need** (carried from the pillars doc): when the
  Humans collective consciousness and an individual NPC disagree, who
  speaks in dialogue/chronicle? Default: individual acts locally,
  collective sets the mood/direction they're measured against.

---

## Implementation roadmap (added 2026-07-22, hearthmind-side)

The doc's own SEQUENCE section (above) gives four phases by theme; this
section breaks those into a concrete, ordered step list — one step per
independently-shippable unit of work, matching this project's standing
"batch = one landable slice" discipline. 39 checklist items (25 Body +
9 Mind + 5 Seam) collapse to **30 steps** — 5 items are standing
principles/guardrails (A9, A23, A24, A25, C4), not separate steps; they
get enforced *within* every other step, not built once and done.

**Do not start any step without an explicit go-ahead naming it** — same
convention as every other vision doc filed here (docs/VISION-2026-07-
21-SELFEVOLVING.md, docs/VISION-2026-07-22-LIVINGTERRARIUM.md,
docs/archive/IDEAS-2026-07-EMERGENCE.md): this document records the plan, it
is not authorization to start executing it.

### Stage I — Senses & substrate (3 steps, unblocks everything)

1. **A22 Emergence API** — per-subsystem `emergence_events()` stream,
   salience-tagged, pillar-relevance-tagged. Build first: every later
   pillar depends on having something to perceive. **Shipped v1.4.8**:
   `world/emergence.py` + `World.emergence_log`, populated by mirroring
   highlights/reflection/ontology-promotion plus a new settlement
   bottleneck detector; `GET /emergence`; dev-console-only surfacing
   (no consumer yet — that's Stage II). See CLAUDE.md's "Current state
   (v1.4.8)" and CHANGELOG.md for full detail.
2. **A1 FieldGrid** — named scalar fields over the map, coarse
   resolution to start (existing region-grid granularity), per-tick
   `step()` per field. The Body's new substrate. **Shipped v1.4.9**:
   `world/fields.py`'s `FieldGrid` abstraction (3x3, matching
   `WEATHER_REGION_GRID`) + `World.fields`, stepped every tick right
   after `population.tick`; one concrete field (`population_density`)
   proves the shape and feeds a real consumer (fission-site search now
   avoids crowded regions when an alternative exists). The other
   eleven named fields det_sys.md lists are explicitly NOT built yet —
   each is its own future step onto the same grid.
3. **A16 Graph algorithms** — centrality/flow/community-detection over
   the existing pairwise ledger + economy/trade adjacency. Cheap,
   deterministic, immediately feeds A22. **Shipped v1.4.9**:
   `world/graph_algorithms.py`'s weighted-degree centrality over the
   relationship ledger; `SimulationEngine._detect_social_hub` (season
   cadence, edge-triggered) tracks each settlement's `social_hub_
   agent_id` and emits an A22 observation when it changes. Community
   detection was already shipped as `InstitutionKind.FACTION`
   detection (v0.80.0) under a different name — not duplicated.
   Betweenness/network-flow/tech-DAG metrics remain future follow-ups.

### Stage II — The five minds (6 steps, the refactor)

4. **B1 Pillar abstraction, Nature first** — identity/self-model/
   world-model/memory/objectives/inbox-outbox for one pillar, proving
   the shape before replicating it four more times. **Shipped v1.5.0**:
   `cognition/pillar.py`'s `Pillar` class (self_model/world_model/
   memory/objectives/inbox/outbox, typed `MESSAGE_KINDS` for B4) +
   `World.nature_pillar` (seeded identity/self-model/objectives).
   `_maybe_schedule_nature_mind`'s existing apply() now mirrors every
   belief form/revision into `nature_pillar.world_model` and writes a
   `remember()` note, alongside the untouched `World.nature_beliefs`
   every existing reader still uses. Deliberately NOT the full "refactor
   ~55 scattered jobs into acts of five pillars" — that's B2 (the
   cognitive cycle) and beyond; inbox/outbox stay structurally present
   but empty (no second pillar exists to message yet). Dev-console-only
   surfacing (`full_diagnostics()["nature_pillar"]`).
5. **B2 Continuous cognitive cycle** — observe→interpret→remember→
   plan→act→reflect, resumable across turns, wired to Nature.
   **Shipped v1.5.1**: `Pillar.cycle_stage`/`working_memory`;
   `_maybe_schedule_nature_mind` alternates a cheap `observe` season
   (reads A22 into `working_memory`) with an `interpret` season (the
   existing LLM call, grounded in what was observed, closing the cycle
   back to `observe`). Halves `nature_mind`'s LLM call volume as a real
   trade for genuine resumability. Only Nature; the other four stage
   names stay bundled into one call.
6. **B3 Attention scheduler** — one budget arbiter across pillars,
   wired to the already-existing dynamic pacing (`llm_pressure_ratio`).
   **Shipped v1.5.2 (Nature), generalized to all five v1.5.3/1.6.0.**
   Steps 4-6 (B1/B2/B3) were then generalized from Nature-only to all
   five pillars in one later pass, per explicit user correction — see
   CLAUDE.md's "Current state (v1.5.3)"/"(v1.6.0)".
7. **B9 Self/world-models** — generalized once Nature proves them out
   (step 4), applied to the remaining four pillars. **Shipped** as part
   of the same B1-generalization pass (step 4/6 above) rather than as
   its own separate step — self_model/world_model were already part of
   `Pillar`'s shape from v1.5.0 onward, so generalizing B1 to all five
   pillars generalized B9 with it. The "relates to the others" half
   stays open (needs B4).
8. **B8 Living memory & consolidation** — per-pillar periodic
   consolidate/forget/reinforce, generalizing the human-memory pattern
   that already exists. **Shipped, scoped** (explicit user instruction,
   "Continue the roadmap"): `Pillar.consolidate()` — periodic fold-
   oldest-into-one-digest, zero LLM cost, wired into `_pillar_close_
   cycle` so all five pillars get it. `reinforce`/`reinterpret` NOT
   attempted (needs per-note salience tracking) — flagged follow-up.
9. **C1/C2 seam wiring** — perception channel (A22 → each pillar's
   observe()) and intention channel (pillar → Body validate/execute)
   made real for whichever pillars exist by this point. **Shipped**
   (explicit user instruction, "Build step 9"): C1 was already
   structurally real for all five pillars since B2, missing only real
   salience-ranking (fixed — `_pillar_observe_turn` now sorts candidate
   observations by `magnitude` before filling bounded `working_memory`,
   instead of plain recency order). C2 audit found Innovation/Nature
   already validate their Body-touching proposals; Village/Reflection
   have no Body-touching writes to validate; Humans' dialect-drift term
   coining was the one real gap (wrote a new `Settlement.lexicon` entry
   with no Body-side check at all) — closed with `narrative_direction.
   validate_coined_term()`. See CHANGELOG.md's "C1/C2 seam wiring"
   entry.

### Stage III — Player-facing + interaction (5 steps, emergence turns on)

10. **C3 `/ask/{pillar}` chat** — generalize the existing `/ask-
    chronicler` pattern to any pillar; cheap, high daily value, ship
    early even if only Nature exists yet. **Shipped v1.8.0** — see
    Part C's own C3 entry above for full detail.
11. **B4 Inter-pillar consciousness bus** — typed messages between
    pillars, the four influence-arrows made real. **Shipped v1.9.0** —
    see Part B's own B4 entry above for full detail.
12. **B5 Innovation as conscious scientist** — extend `ontology.py`'s
    propose/evolve/merge to query the (still Stage IV) affordance/
    reaction layer once it lands; can ship a first version against
    today's closed-hook vocabulary and re-target later. **Shipped a
    first version, v1.10.0** — see Part B's own B5 entry above for
    full detail (hypothesis-driven proposals grounded in a named real
    pressure signal, confirmed/refuted against Innovation's own belief
    once the concept's adoption fate is known; evolve/merge and the
    real affordance/reaction query left for Stage IV).
13. **B6 Reflection as meta-scientist** — extend `TUNABLE_GOVERNORS`,
    add the human-reviewed advisory-proposal inbox, track advice
    outcomes. **Shipped a first version, v1.11.0** — see Part B's own
    B6 entry above for full detail (prefix-matched governor lookup so
    every settlement-scoped pattern is now governable, `disease_
    outbreak_chance` as the worked example, plus a real human-reviewed
    advisory inbox for a supported hypothesis that names no governor).
14. **B7 Humans collective + coordinator** — one collective mind plus
    the capped per-NPC pool, folding in the existing voice-pair
    machinery rather than replacing it. **Shipped a first version,
    v1.12.0** — see Part B's own B7 entry above for full detail (both
    named mechanisms already existed; this pass wired the missing
    awareness link between them). **This closes Stage III** — all 5
    steps (10-14) shipped.

### Stage IV — Deepen the Body (16 steps, ordered by leverage)

Each step should ship its own Emergence API events (Stage I, step 1) as
it lands, so cognition feels the deepening immediately rather than
waiting for a later integration pass.

15. **A11 Continuous hydrology** — water as a field, network-flow
    downhill, groundwater/evaporation/erosion feeding back into
    (now-mutable) elevation. Highest-leverage single item: touches
    agriculture, siting, disasters, ecology at once. **Shipped a first
    slice, v1.13.0**: a real per-tile `HydrologyField` (`world/
    hydrology_field.py`) — precipitation, single-pass downhill
    redistribution, evaporation, ticked weekly. Real consumer:
    `FarmGrid.plant()`'s yield now scales with the actual local
    moisture reading, not just soil fertility. Real Emergence API
    consumer: `_detect_hydrology_drought` (edge-triggered, `nature`/
    `village`-tagged). Groundwater and erosion-into-mutable-elevation
    (the item's two biggest remaining pieces) explicitly deferred —
    see `hydrology_field.py`'s own module docstring for the full scope
    and the flagged R7 deviation (pure Python, weekly cadence, not yet
    natively ported — this is a from-scratch mechanism whose exact
    shape needs live validation before locking into a compiled
    interface, same reasoning class as every other flagged R7
    deviation in this codebase, applied here to "new" rather than
    "low-density").
16. **A2 CA/diffusion/reaction-diffusion operators** — `diffuse`/
    `reaction_diffuse`/`cellular_step` library over A1's fields;
    forest succession as the worked first consumer. **Shipped, v1.14.0**:
    new `world/ca_operators.py` — three generic, pure, reusable
    operators, none tied to one subsystem. Forest succession consumer:
    `terrain_evolution.compute_succession_pressure` diffuses a 0/1
    forest-indicator grid into a real "how forested is my neighborhood"
    reading, averages it against A11's real per-tile moisture field,
    and the result MODULATES (not replaces) the existing `REFOREST_
    MIN_FALLOW_WEEKS` threshold per tile — a well-forested, moist
    neighborhood reclaims in as few as 1 week, a poor one takes up to
    2x longer, bounded both directions. Deliberately a modulation of
    already-tuned behavior, not a wholesale replacement, to keep
    regression risk low on a mechanic with a native fast path
    (`maybe_reclaim`'s reforest-chance roll) — the eligibility
    computation `_tick_fallow` modifies stays pure Python either way,
    so native/fallback parity is unaffected.
17. **A10 Ecology on fields** — fold the existing food-web/predator-
    prey system onto the field substrate; add migration, competition,
    decomposition, nutrient cycling, pollination. **Shipped a first
    slice, v1.15.0**: nutrient cycling only — see the A10 section above
    for full detail. Migration, competition, decomposition, pollination,
    habitat formation, and the full field-substrate fold-in all remain
    open, explicitly flagged.
18. **A5/A6 Affordances + discovery query layer** — tag entities with
    `can_X` capabilities and physical properties; the query/validate
    layer Innovation needs for real unprogrammed-combination discovery.
    **Shipped a first slice, v1.16.0**: see the A5/A6 sections above.
    `BuildingKind` hand-tagged with the spec's own closed affordance
    vocabulary; `affordances_present`/`discover_combinations` are a
    real query layer wired into Innovation's ontology-proposal generate-
    step. Per-instance `Entity.affordances`/properties (A12-derived),
    and the validate-step half, remain open, flagged.
19. **A12 Material science** — a material registry (hardness, density,
    flammability, etc.); affordances (18) start deriving from
    properties rather than being hand-tagged. **Shipped a first slice,
    v1.17.0**: see the A12 section above. Per-instance material
    assignment and A13's chemistry/reaction rules remain open, flagged.
20. **A13 Chemistry/reaction system** — `A + B + condition → C` rule
    table over materials (18/19); Innovation queries it instead of
    hardcoded recipes. **Shipped a first slice, v1.18.0**: see the A13
    section above. The automatic-firing reactor half (a rule actually
    mutating world state on a tick) remains open, flagged.
21. **A8 Evolutionary Innovation loop** — wrap Innovation's output in
    generate→evaluate→select using the fitness/lineage fields already
    on `InventedConcept`. **Shipped a first slice, v1.19.0**: see the
    A8 section above. Sandbox-forward-sim-as-fitness and grammar-based
    mutation (A7) as a second generate path remain open, flagged.
22. **A15 Genetic inheritance** — genome vectors, sexual recombination,
    mutation, drift, real differential-fitness selection, replacing
    the current blend+noise trait inheritance. **Shipped a first
    slice, v1.20.0**, scoped to humans: see the A15 section above.
    Wildlife/animal genetics and A14-dependent physiological genes
    remain open, flagged.
23. **A14 Layered organism biology** — metabolism/nutrition/immune/
    stress/development as coupled continuous subsystems, replacing the
    current discrete hunger/energy/illness/aging state; genetics (22)
    acts on this layer. **Shipped a first slice, v1.21.0**: real
    continuous immune state coupled to nutrition/rest, modulating
    disease. Stress/reproduction/development/injury-recovery/sleep
    remain open, flagged.
24. **A17 Information ecosystem unification** — one propagation model
    on the social graph (3) for knowledge/rumor/tradition/belief/song/
    custom/technique, replacing several parallel mechanisms. **Shipped
    a first slice, v1.22.0**: see the A17 section above — a reusable
    social-graph propagation weight, proven against ontology concept
    spread. Folding rumor/tradition/belief/song/technique onto it, plus
    shared mutate/decay/compete, remain open, flagged.
25. **A18 Events as composable reactions** — a condition→consequence
    rule engine generalizing the terrarium doc's trigger→effect
    vocabulary from settlement-scoped to the whole Body. **Shipped a
    first slice, v1.23.0**: see the A18 section above — a general
    AND-combination engine, proven against one worked composite
    reaction. A real authoring system for new combinations, and
    consequences beyond relationship rupture, remain open, flagged.
26. **A19 Persistent spatial memory** — bounded per-location history
    vectors (traffic/battles/rituals/pollution/etc.), generalizing
    `mining_scars`/`disaster_scars`. **Shipped a first slice, v1.24.0**:
    see the A19 section above — a new ritual-activity axis plus a real
    read-side unification (`location_character`) over mining/disaster/
    ritual, proven against shrine festival boosts. The other six named
    axes remain open, flagged.
27. **A7 Grammar-based procedural systems** — L-systems/graph grammars
    for settlement layout, architecture, dialect drift; needs the
    "which domains get grammars vs. stay LLM" design decision the
    checklist flags, resolved before starting. **Shipped a first
    slice, v1.25.0**: design decision resolved (accepted the doc's own
    default), all three domains shipped in one batch — see the A7
    section above. Not a full graph/shape grammar in any domain; a
    genuine rewrite/production system (vs. the current single-slot/
    single-rule scope) and LLM-proposable rules remain open, flagged.
28. **A3/A4 Continuous procgen + scripted-event conversion — first
    slice shipped v1.26.0** (A3's own worked example, "ruins should
    form where settlements die" — see the A3 section above). Rivers
    re-carving via elevation/erosion (item 15) and A4's economy/
    agriculture/information continuous-field conversion remain open,
    explicitly not attempted this pass.
29. **A20 Multi-scale aggregation — extended, v1.27.0** (see the A20
    section above): `population_density`'s existing region field
    gained a second, independent real consumer (migrant-draw
    dampening) plus live map visibility. A genuinely new second field
    and the "culture aggregates settlements' information-ecosystems"
    half of the spec remain open, flagged.
30. **A21 Temporal compression pipeline — first slice shipped v1.28.0**:
    deterministic event-aggregate (`world/legends.py`, reusing A22's
    already-structured Emergence API stream instead of folklore's raw
    text) → LLM-narrate-significant (`llm/legend.py`) → deterministic
    one-legend-per-subsystem dedup → `Settlement.legends`. Folding
    legends back into myth/tradition/institution formation, grounding
    other prompts with "already legendary" context, and unifying with
    folklore remain open, flagged — see the A21 section above.

### Standing discipline (not steps — enforced within every step above)

**A9** (every subsystem both reads upstream and writes downstream state)
· **A23** (every new subsystem adds interactions, never ships isolated)
· **A24** (every pillar intention passes deterministic validation,
inviolable as Part B gains power) · **A25** (audit LLM jobs — if a
grammar/field/propagation system could produce it, move it there) ·
**C4** (the acceptance gate: every persistent field needs a creator and
a consumer, reject state nothing reads). These are review-time checks
applied to steps 1–30, not separate line items — folding them into the
gate is what keeps Stage IV from regressing into isolated content the
way the original 25-system audit found Part A had drifted.

### Open design decision (blocks step 14 in full, not steps 1–13)

Per the checklist's own flag: when the Humans collective consciousness
(step 14) and an individual NPC disagree, who speaks in dialogue/
chronicle? Default carried from the source doc: the individual acts
locally; the collective sets the mood/direction the individual is
measured against, not what it says. Needs an explicit user decision
before step 14 ships, not before Stage I–III.
