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
  exists. Only ONE real consumer shipped (fission-site selection reads
  `population_density`) — vegetation/wildlife/farming do not read
  fields yet.
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

- [ ] **Status:** `terrain_evolution`, road paving, lake-level walk are
  continuous; rivers carved once and static; settlements/cultures
  evolve via LLM, not deterministic procgen.
- [ ] **Spec:** Audit every "generated once at world creation" call and
  ask "should this keep evolving?" Rivers should re-carve as erosion
  (A-hydrology) shifts elevation; ruins should form where settlements
  die; roads already pave — extend the pattern. The principle: world-gen
  is just tick 0 of the same rules that run forever.
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

- [ ] **Status:** Object classes throughout (`BuildingKind` enum,
  discrete tools, etc.). No affordance model.
- [ ] **Spec:** Add an affordance tag-set to entities: a thing is defined
  by *what it can do* (`can_burn`, `can_shelter`, `can_carry_water`,
  `can_sharpen`, `can_store_food`, `can_redirect_water`, `can_fertilize`,
  `can_poison`, `can_support_weight`, `can_conduct_heat`) plus physical
  properties (A12). Keep the closed enums for the native store's sake,
  but attach an open affordance set as data.
- [ ] **Data model:** `Entity.affordances: set[str]`, `Entity.
  properties: dict[str, float]`; a registry mapping affordance → the
  deterministic effect it enables.
- [ ] **Replaces/extends:** wraps existing classes rather than replacing
  them (safe path: tag, don't rewrite).
- [ ] **Feeds:** **Innovation** (B) — this is the prerequisite that lets
  Innovation discover *unprogrammed combinations* (a thing that
  can_carry_water + can_store_food → an irrigation store nobody coded)
  instead of naming within closed hooks. Without A5/A6, Innovation can
  never be what LLM_Pillars.md asks.

### A6 — Exposed affordances for discovery [det #6] — MISSING

- [ ] **Status:** —
- [ ] **Spec:** The query layer over A5: systems (especially Innovation)
  can ask "what here can_X?" and "what combination of affordances would
  achieve Y?" A deterministic affordance-matcher that validates whether
  a proposed combination is physically coherent.
- [ ] **Feeds:** Innovation's generate-step (B) queries this; the
  validate-step checks against it. This is the "discover new combinations
  without programmer-authored recipes" mechanism.

### A7 — Grammar-based procedural systems [det #7] — MISSING (deterministic form)

- [ ] **Status:** The LLM does architecture/ritual/language/myth
  creatively; there's no *deterministic* grammar layer.
- [ ] **Spec:** Add L-systems / graph grammars / production rules for the
  systems where deterministic generativity beats an LLM call:
  settlement layout (graph grammar over terrain+roads), architecture
  (shape grammar), language/dialect drift (rewrite rules over a lexicon),
  ritual/recipe structure (production grammar). The LLM *seeds and names*;
  the grammar *expands and varies* deterministically and cheaply.
- [ ] **Data model:** per-domain grammar (axiom + production rules +
  constraints); rules can themselves be LLM-proposed (ties to Innovation)
  but expansion is deterministic.
- [ ] **Feeds:** offloads infinite cheap variation from the LLM budget to
  deterministic generation — directly serves "all LLM budget to
  cognition" (LLM_Pillars).
- [ ] **Design decision needed:** which domains get grammars vs. stay
  LLM-authored. My default: layout/architecture/dialect deterministic;
  myth/custom/law stay LLM (they need meaning, not just structure).

### A8 — Evolutionary Innovation (generate→mutate→evaluate→select) [det #8] — PARTIAL

- [ ] **Status:** `ontology.py` has propose/evolve/merge with lineage —
  but no *fitness/selection* loop; concepts spread by adoption, not by
  evaluated survival.
- [ ] **Spec:** Wrap Innovation's output in an evolutionary loop:
  *generate* (LLM proposes, or grammar A7 mutates an existing concept),
  *evaluate* (deterministic fitness: did adopters prosper? did the
  hooked metric improve? sandbox A-C forward-sim), *select* (fit concepts
  spread and become parents; unfit are abandoned — the status field
  already exists). Farming techniques, building layouts, governance,
  customs all evolve this way instead of one-off invention.
- [ ] **Data model:** each `InventedConcept` gains `fitness_history`,
  `generation`, `parent_ids` (lineage exists); a selection pass each
  cycle promotes/retires.
- [ ] **Feeds:** genuine open-ended tech/culture evolution — the thing
  Innovation-the-pillar is *for*. Pairs with B-Innovation's cognition:
  the LLM proposes creatively, the deterministic loop selects ruthlessly.

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
- [ ] **Spec (deepen):** add migration, competition, decomposition,
  nutrient cycling (→ fertility field A1), pollination (→ vegetation),
  habitat formation (reads fields, writes carrying capacity). Fold the
  existing food web onto the A1 field substrate so ecology and
  environment are one coupled system.
- [ ] **Feeds:** nutrient cycling closes a loop into farming; migration
  gives Nature-the-pillar something to perceive and react to.

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

### A12 — Material science / physical properties [det #12] — MISSING

- [ ] **Status:** —
- [ ] **Spec:** A material registry: each material has hardness, density,
  conductivity, elasticity, durability, decay-rate, flammability,
  toxicity, thermal-capacity, workability. Tools/buildings/vehicles are
  *made of* materials and inherit derived capabilities (a hard+workable
  material → good blade; flammable → fire risk).
- [ ] **Data model:** `Material(props...)`; `Entity.material: Material`;
  affordances (A5) *derive* from properties (`can_sharpen` if hardness >
  τ).
- [ ] **Feeds:** Innovation (B) discovers tools/tech by combining
  material properties, not recipes — "new tools emerge from combining
  properties." Prerequisite for real material-driven invention.

### A13 — Chemistry / reaction system [det #13] — MISSING

- [ ] **Status:** —
- [ ] **Spec:** General reaction rules over materials/substances:
  `A + B + condition → C` (clay + fire → ceramic; ore + heat → metal;
  plant + water + time → fermentation) as a small rule table, not
  per-recipe code. Reactions are discovered by Innovation querying "what
  does X + Y under Z produce?"
- [ ] **Data model:** `ReactionRule(reactants, conditions, products,
  rate)`; a deterministic reactor that fires rules when conditions meet.
- [ ] **Feeds:** Innovation discovers transformations from principles;
  material science (A12) + chemistry (A13) together are the "invent
  metallurgy without hardcoding metallurgy" engine.

### A14 — Layered organism biology [det #14] — PARTIAL

- [ ] **Status:** hunger/energy/illness/aging exist as fairly discrete
  state; no metabolism/immune/stress/development layers.
- [ ] **Spec:** Model each organism (human, animal) as coupled
  subsystems: metabolism (energy in/out), nutrition (needs → deficiency
  effects), immune response (illness resistance as state, not a coin
  flip), stress, reproduction, development (life stages with changing
  physiology), injury/recovery, sleep. Continuous, not a state machine.
- [ ] **Feeds:** genetics (A15) acts on these; Nature/Humans pillars
  perceive real physiological state; disease becomes an immune-vs-
  pathogen dynamic, not a flag.

### A15 — Genetic inheritance / mutation / drift / selection [det #15] — MISSING

- [ ] **Status:** Trait inheritance is blend+noise (v0.87-era), not
  genetics.
- [ ] **Spec:** A genome per organism (a vector of genes → physiological/
  behavioral traits via A14), with sexual recombination, mutation, drift,
  and *natural selection* (differential survival/reproduction from real
  fitness). Species adapt over generations with no authored progression;
  humans slowly vary too.
- [ ] **Data model:** `Organism.genome: ndarray`; expression function
  genome → traits; inheritance at reproduction.
- [ ] **Feeds:** Nature-the-pillar can *observe its species adapting*
  (2.1 from the terrarium doc, done right); domestication becomes real
  (selective pressure from humans). Emergent species variants (already
  prototyped via LLM) get a deterministic substrate.

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

- [ ] **Status:** Rumor spread/distortion + `invention_knowledge`
  teach/lose/rediscover + ontology lineage exist — the closest to vision.
- [ ] **Spec (deepen):** unify knowledge/rumor/tradition/belief/song/map/
  custom/technique into one propagation model on the social graph (A16):
  each unit spreads, mutates, decays, competes, merges, dies by the same
  rules. Truth is not privileged — false beliefs propagate if fit.
- [ ] **Feeds:** Village/Humans pillars perceive a living memeticscape;
  cultural evolution becomes measurable.

### A18 — Events as composable reactions [det #18] — PARTIAL

- [ ] **Status:** Some composite events; no general composer.
- [ ] **Spec:** An event is a *reaction* fired when a combination of
  field/social/economic conditions crosses a threshold — not a scripted
  incident. A drought-field + a feud-edge + a food-shortage compose into
  a raid nobody hand-authored. A small condition→consequence rule engine
  (the trigger→effect vocabulary from the terrarium doc, generalized to
  the Body).
- [ ] **Feeds:** "entirely new emergent situations without handcrafted
  event chains" — the combinatorial heart of Body-layer emergence.

### A19 — Persistent spatial memory [det #19] — PARTIAL

- [ ] **Status:** `terrain_activity`/`mining_scars`/`disaster_scars`
  track some per-location history; not general.
- [ ] **Spec:** Every location accumulates a bounded history vector:
  traffic, battles, rituals, pollution, fertility, disasters, ownership,
  construction, ecology. Places gain *character* that influences future
  simulation (a battle site stays scarred; a ritual site draws ritual).
- [ ] **Data model:** `fields['history_*']` or a per-tile bounded record;
  ties to A1.
- [ ] **Feeds:** the "unlucky house," folklore sites, why settlements
  re-form where they did — places as actors, and rich pillar perception.

### A20 — Multi-scale simulation [det #20] — PARTIAL

- [ ] **Status:** agent/settlement/world scales exist as separate objects;
  higher scales aren't *emergent aggregations* of lower ones.
- [ ] **Spec:** Regional/world behavior should *aggregate* from local
  fields/graphs rather than being separately simulated: a "region"
  is a computed summary of its tiles' fields; "culture" aggregates
  settlements' information-ecosystems. Zoom levels read the same
  substrate at different resolutions.
- [ ] **Feeds:** coherent world-scale story from local rules; lets a
  pillar reason at the scale its attention is at.

### A21 — Temporal compression (event→legend→myth) [det #21] — PRESENT-ish

- [ ] **Status:** chronicle→documentary→culture-digest, folklore, era
  branches exist — a real strength.
- [ ] **Spec (deepen):** make it a deterministic pipeline with LLM
  seasoning, not LLM-per-step: events aggregate (deterministic) →
  significant ones get LLM-narrated → repeated narratives crystallize
  into legend (deterministic detection) → legends into myth/tradition/
  institution. Preserve identity across long timescales cheaply.
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

### B1 — The Pillar abstraction — PARTIAL (Nature only, v1.5.0) — the keystone

- [x] Five persistent conscious entities (Humans, Village, Nature,
  Innovation, Reflection), each with identity, self-model, world-model
  (typed theories, confidence, observations-vs-hypotheses), living memory
  (consolidate/forget/reinforce/reinterpret), objectives, inbox/outbox.
  Refactor the ~55 scattered jobs into acts of these five. **Depends on
  A22** (senses) and **A16** (structural perception). **Shipped, scoped
  to ONE of five**: `cognition/pillar.py`'s `Pillar` class (identity,
  self_model, typed world_model — status observation-vs-hypothesis,
  memory — a capped FIFO list, not yet real consolidate/forget/
  reinforce, objectives, inbox/outbox with B4's typed message
  vocabulary) proven against `World.nature_pillar`, mirroring the
  existing `nature_mind` belief job. Humans/Village/Innovation/
  Reflection do NOT have a Pillar instance yet; the "refactor ~55
  scattered jobs" is NOT attempted — only nature_mind's one job writes
  through this shape so far.

### B2 — The continuous cognitive cycle — MISSING

- [ ] Each pillar runs observe→interpret→remember→plan→act→reflect,
  resumed across cognitive turns (not timer-fired jobs). Bounded
  attention, working memory, uncertainty, incomplete knowledge — a mind,
  not an oracle.

### B3 — The Attention Scheduler — MISSING

- [ ] One budget arbiter over all five (round-robin deep + shallow-
  frequent), wired to the **existing dynamic pacing** so sim-time slows
  when cognition lags (verified present). Priority from A22 salience +
  staleness + player focus + inter-pillar messages.

### B4 — Inter-pillar consciousness bus — MISSING (the emergence engine)

- [ ] Typed messages (observation/question/theory/hypothesis/warning/
  request/discovery/disagreement) between pillars; the four influence-
  arrows (Nature→Village→Innovation→Village, Reflection observing all)
  made real; disagreement persists and drives behavior.

### B5 — Innovation as conscious scientist — PARTIAL

- [ ] Ontology propose/evolve/merge exists; make it *query affordances
  (A5/A6) and reactions (A13) to invent unprogrammed combinations*, and
  wrap in the evolutionary loop (A8). B-Innovation is the LLM half; A8 is
  its deterministic selection.

### B6 — Reflection as meta-scientist — PARTIAL

- [ ] Reflection + self_tuning exist (falsifiable hypotheses, bounded
  sandbox-validated governor nudges). Extend `TUNABLE_GOVERNORS` to the
  major levers; add the advisory-proposal inbox (human-reviewed) for
  changes beyond governors; track whether its advice worked.

### B7 — Humans: collective consciousness + coordinator — PARTIAL

- [ ] One collective mind (mood/values/direction) + a capped pool of
  cheap per-NPC calls on dramatically-salient individuals (fold in the
  voice-pair machinery); everyone else deterministic. Individuality from
  the ledger + Body systems + occasional cheap calls.

### B8 — Living memory & consolidation — PARTIAL

- [ ] Per-pillar: consolidate detailed experience into higher-level
  knowledge periodically; forget trivia; reinforce/reinterpret; connect
  into concepts. Keeps years cognitively manageable while preserving
  identity. (Human memory partly does this; generalize to all pillars.)

### B9 — Self-model & world-model per pillar — MISSING

- [ ] Each pillar knows what it is, wants, how it changed, how it relates
  to the others (self-model); holds revisable evidence-backed theories,
  distinguishing observation from hypothesis, tracking uncertainty
  (world-model). The substrate for genuine "it can be wrong."

---

# PART C — THE SEAM (Body ↔ Mind co-evolution)

Where LLM_Pillars.md and det_sys.md meet — the bidirectional interface.

### C1 — Perception channel (Body → Mind) — MISSING

- [ ] A22's Emergence API *is* this channel: curated observations flow to
  each pillar's observe() step. No pillar reads raw state; none is
  omniscient. Bounded, salience-ranked, pillar-tagged.

### C2 — Intention channel (Mind → Body) — PARTIAL

- [ ] Every pillar acts *only* by emitting intentions the Body validates
  and executes (invent tech, set custom, change law, reorganize
  institution, shift land use, domesticate, build, propose experiment).
  The deterministic layer executes and validates per its own rules.
  Partly exists (LLM proposals are validated); generalize to all pillar
  actions.

### C3 — Player ↔ Pillar chat — PARTIAL

- [ ] Generalize `/ask-chronicler` (verified present) to `/ask/{pillar}`:
  ask any pillar what it believes/fears/plans/predicts/why, answered from
  its real self/world-model (can be wrong). Nudges enter cognition as
  weighable inputs, never commands; conversations are remembered (a light
  per-pillar player-model). Pillars may initiate contact.

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
docs/IDEAS-2026-07-EMERGENCE.md): this document records the plan, it
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
6. **B3 Attention scheduler** — one budget arbiter across pillars,
   wired to the already-existing dynamic pacing (`llm_pressure_ratio`).
7. **B9 Self/world-models** — generalized once Nature proves them out
   (step 4), applied to the remaining four pillars.
8. **B8 Living memory & consolidation** — per-pillar periodic
   consolidate/forget/reinforce, generalizing the human-memory pattern
   that already exists.
9. **C1/C2 seam wiring** — perception channel (A22 → each pillar's
   observe()) and intention channel (pillar → Body validate/execute)
   made real for whichever pillars exist by this point.

### Stage III — Player-facing + interaction (5 steps, emergence turns on)

10. **C3 `/ask/{pillar}` chat** — generalize the existing `/ask-
    chronicler` pattern to any pillar; cheap, high daily value, ship
    early even if only Nature exists yet.
11. **B4 Inter-pillar consciousness bus** — typed messages between
    pillars, the four influence-arrows made real.
12. **B5 Innovation as conscious scientist** — extend `ontology.py`'s
    propose/evolve/merge to query the (still Stage IV) affordance/
    reaction layer once it lands; can ship a first version against
    today's closed-hook vocabulary and re-target later.
13. **B6 Reflection as meta-scientist** — extend `TUNABLE_GOVERNORS`,
    add the human-reviewed advisory-proposal inbox, track advice
    outcomes.
14. **B7 Humans collective + coordinator** — one collective mind plus
    the capped per-NPC pool, folding in the existing voice-pair
    machinery rather than replacing it.

### Stage IV — Deepen the Body (16 steps, ordered by leverage)

Each step should ship its own Emergence API events (Stage I, step 1) as
it lands, so cognition feels the deepening immediately rather than
waiting for a later integration pass.

15. **A11 Continuous hydrology** — water as a field, network-flow
    downhill, groundwater/evaporation/erosion feeding back into
    (now-mutable) elevation. Highest-leverage single item: touches
    agriculture, siting, disasters, ecology at once.
16. **A2 CA/diffusion/reaction-diffusion operators** — `diffuse`/
    `reaction_diffuse`/`cellular_step` library over A1's fields;
    forest succession as the worked first consumer.
17. **A10 Ecology on fields** — fold the existing food-web/predator-
    prey system onto the field substrate; add migration, competition,
    decomposition, nutrient cycling, pollination.
18. **A5/A6 Affordances + discovery query layer** — tag entities with
    `can_X` capabilities and physical properties; the query/validate
    layer Innovation needs for real unprogrammed-combination discovery.
19. **A12 Material science** — a material registry (hardness, density,
    flammability, etc.); affordances (18) start deriving from
    properties rather than being hand-tagged.
20. **A13 Chemistry/reaction system** — `A + B + condition → C` rule
    table over materials (18/19); Innovation queries it instead of
    hardcoded recipes.
21. **A8 Evolutionary Innovation loop** — wrap Innovation's output in
    generate→evaluate→select using the fitness/lineage fields already
    on `InventedConcept`.
22. **A15 Genetic inheritance** — genome vectors, sexual recombination,
    mutation, drift, real differential-fitness selection, replacing
    the current blend+noise trait inheritance.
23. **A14 Layered organism biology** — metabolism/nutrition/immune/
    stress/development as coupled continuous subsystems, replacing the
    current discrete hunger/energy/illness/aging state; genetics (22)
    acts on this layer.
24. **A17 Information ecosystem unification** — one propagation model
    on the social graph (3) for knowledge/rumor/tradition/belief/song/
    custom/technique, replacing several parallel mechanisms.
25. **A18 Events as composable reactions** — a condition→consequence
    rule engine generalizing the terrarium doc's trigger→effect
    vocabulary from settlement-scoped to the whole Body.
26. **A19 Persistent spatial memory** — bounded per-location history
    vectors (traffic/battles/rituals/pollution/etc.), generalizing
    `mining_scars`/`disaster_scars`.
27. **A7 Grammar-based procedural systems** — L-systems/graph grammars
    for settlement layout, architecture, dialect drift; needs the
    "which domains get grammars vs. stay LLM" design decision the
    checklist flags, resolved before starting.
28. **A3/A4 Continuous procgen + scripted-event conversion** — audit
    every "generated once" call (rivers re-carving via 15, ruins
    forming, etc.) and every remaining scripted-event subsystem,
    converting to continuous field/rule updates.
29. **A20 Multi-scale aggregation** — region/culture-level state
    becomes a computed summary over local fields/graphs instead of a
    separately-simulated object.
30. **A21 Temporal compression pipeline** — deterministic event-
    aggregate → LLM-narrate-significant → deterministic-legend-
    detection → myth/tradition pipeline, replacing today's more ad-hoc
    chronicle/folklore chain.

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
