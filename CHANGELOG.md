# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

## [0.53.0] — Full-H extension: council institutions, ambition, medicine

### Added

- **H3 extension: a second institution kind, `COUNCIL`.** Forms
  automatically the first tick a named settlement's population reaches
  `COUNCIL_FORMATION_POPULATION_THRESHOLD=20` — membership is the
  `COUNCIL_SIZE=5` oldest living agents at that moment (by fraction of
  their own lifespan lived), fixed at formation and never refreshed,
  same shape `FAMILY` institutions already use. New `council_formed`
  event. `Settlement.summary()`'s `institutions` dict gained `councils`.
- **H6 extension: a third trait axis, `TRAIT_AMBITION`.** Nudged up by
  tangible achievement — founding a building
  (`Population._maybe_start_construction`) or a skill first crossing
  `MASTERY_THRESHOLD=0.95` through practice (both `_maybe_forage`'s
  farming-practice line and `_advance_construction`'s, each gated to
  fire exactly once per skill per agent, on the crossing tick only) —
  rather than by hardship/social contact like the other two axes.
  Included in the monthly bounded random walk and `describe_traits`.
  `summary()` gained `avg_ambition`.
- **H4 extension: a second crafted good, `"medicine"`.** Mirrors the
  materials-to-tools chain exactly: a standing, staffed hospital
  converts shared materials into personal medicine for its workers
  (`Population._maybe_craft_medicine`). Consumed by `_tick_disease`: a
  sick agent personally holding medicine gets their own death-chance
  roll multiplied by `(1 - MEDICINE_DEATH_CHANCE_REDUCTION)` — a second,
  individually-earned protection layer on top of the settlement-wide
  hospital reduction everyone already gets — and draws the stock down
  each tick it's helping. `Population._maybe_trade_medicine` mirrors
  the existing tools-trade shape. `summary()` gained `avg_medicine`.
  Observatory stat tiles ("Institutions," "Skills & tools," "Personality
  (avg)") updated to surface all of the above alongside the existing
  H1-H5/H7 stats.

Verified: a direct council-formation script confirmed threshold
gating, correct elder selection (eldest-by-lifespan-fraction), and
no duplicate council on repeat calls; a mastery-crossing script
confirmed the ambition nudge fires exactly once (not on every practice
tick past mastery) and a founding-nudge script confirmed both founders
gain ambition; a direct medicine-crafting script confirmed production
and materials draw-down; a 3,000-tick paired death-rate comparison
(500 permanently-medicated agents vs. 500 without, same seed) measured
58 deaths with medicine vs. 128 without — medicine measurably,
substantially reduces the death rate, not just in isolated single-tick
math. A 6,000-tick full engine run (LLM disabled, seed 42) completed
with no exceptions across all three new mechanics together, with a
full `World.to_dict()`/`from_dict()` round-trip preserving every new
stat byte-identically.

## [0.52.0] — H2 extension: personal beliefs; H5 extension: second skill

### Added

- **H2 extension: cognition prompts now see "what the village believes
  about you."** New shared `llm.beliefs.beliefs_about_agent` (also
  refactored into dialogue's existing call site, no behavior change
  there). Wired into `SimulationEngine._schedule_due_cognition` via a
  new `beliefs_about` param on `llm.cognition.build_prompt` — closes the
  gap where dialogue already had this context and cognition didn't,
  directly matching the roadmap's own "next mechanical payoff" framing.
- **H2 extension: personal per-agent beliefs.** New `Agent.beliefs`
  (same shape as `Settlement.beliefs` — reuses the generic, Settlement-
  independent `parse_belief`/`push_belief_history`/`find_belief_index_
  by_subject` functions rather than a parallel mechanism). New monthly
  `SimulationEngine._maybe_schedule_personal_belief`: one randomly
  chosen living agent with memories reflects on their own recent
  experience, forming or revising a private theory
  (`llm.beliefs.build_personal_prompt`/`fallback_personal_belief`, a
  new `PERSONAL_SYSTEM_PROMPT`). Capped at `MAX_PERSONAL_BELIEFS=4`.
  Fed back into that same agent's own cognition prompt as "your own
  private theory" — the concrete "act upon a personal belief" payoff.
  Deliberately one agent per month, not all of them: 400 agents each
  getting a monthly LLM call would be a large scheduling load for a
  mechanic meant to surface occasional personal theories, not a diary
  entry for everyone.
- **H5 extension: a second skill, `SKILL_CONSTRUCTION`.** Gained by
  practice (`Population._advance_construction`, which now iterates
  actual worker agents instead of just counting them) and colocated
  teaching (`_maybe_teach_skills`, already skill-name-agnostic — one
  line added). A skilled crew builds/repairs up to 25% faster
  (`SKILL_CONSTRUCTION_SPEED_BONUS`), stacking with the existing
  materials-multiplier and tech-level bonuses. `summary()` gained
  `avg_construction_skill`.
- **H5 extension: population skill nudges invention chance.** The
  settlement-wide average of both skills gives a small additive
  multiplier to invention chance
  (`SKILL_INVENTION_BONUS_WEIGHT=0.3`, up to +30% at full average
  mastery) in `SimulationEngine._maybe_schedule_invention`, on top of
  the existing prosperity gate and education bonus — the roadmap's own
  suggested "tie tech_level to actual population knowledge" direction,
  taken as an additive nudge rather than a full replacement of the
  existing roll (which stays exactly as tuned).

Verified: direct scripts confirmed `beliefs_about_agent`'s filtering;
`build_personal_prompt`/`fallback_personal_belief`'s output shape; a
controlled construction-speed comparison (unskilled crew: 0.05
progress/tick with zero materials; a fully-skilled agent: 0.0625 —
exactly the +25% bonus) and the practice gain itself; teaching-
generalization for the new skill; and the invention-chance nudge's
exact math (0.2 base -> 0.26 at full-mastery average skill, exactly
+30%). Two full-engine integration runs (real `SimulationEngine` via
`load_or_create`/`_tick_once`, LLM disabled) confirmed: (1) with a
forced memory on every agent, personal beliefs actually form and later
revise (with history) through the real monthly-scheduled job, and (2) a
6,000-tick run with no forced state produces no exceptions with
`avg_construction_skill` live in `summary()`. Both confirmed clean
`World.to_dict()`/`from_dict()` round-trips.

## [0.51.0] — H6: psychology; H8: temperament/belief crossover; H9: observatory

### Added

- **H6: a compact, bounded personality vector.** New `Agent.traits`
  (`TRAIT_RESILIENCE`, `TRAIT_SOCIABILITY`, -1..1, deliberately two
  axes, not a big-five system). Nudged by lived experience — grief
  (existing grief loop in `_apply_deaths`), surviving a predator attack,
  the onset of a hunger crisis (`starving_ticks == 1`, not every tick
  spent hungry), and positive social contact (a completed food/tools
  trade) — plus a monthly bounded random walk (`Population._tick_
  traits`, called on the real calendar's `month_end`), the same shape
  `Settlement.temperament`/`player_standing` already use, reused at
  agent scale. Read into both `llm/cognition.py` and `llm/dialogue.py`
  prompts via a new shared `Agent.describe_traits` helper once a trait
  clears `TRAIT_NOTABLE_THRESHOLD` — same "only mentioned once notably
  warm/cold" treatment `player_standing` gets. `summary()` gained
  `avg_resilience`/`avg_sociability`.
- **H8: temperament colors belief confidence.** New `llm.beliefs.
  temperament_confidence_bias`, wired into the existing beliefs job
  `apply()` — the settlement's current `temperament` magnitude (either
  direction) pushes a freshly formed/revised belief's confidence
  further from ambivalent (0.5), so an agitated village holds its
  current theories more starkly, whatever they already lean toward.
  Deliberately not sign-correlated with "optimistic vs. pessimistic"
  (that would read as a confirmed mood-to-belief rule, breaking Phase
  G's permanent ambiguity discipline) — only magnitude matters.
  Respects `Config.phase_g_intensity` like every other Phase G
  consumer.
- **H9: family formation logged; new stats surfaced in the observatory.**
  `Population._extend_family` now returns a `family_formed` life event
  the first time a family institution is actually created (not on a
  routine additional child) — closes an observability gap where
  families formed silently. New dev-console/details-panel stat tiles
  ("Carrying capacity", "Institutions", "Skills & tools") surface H1's
  `carrying_capacity`, H3's institution counts, and H5/H4's
  `avg_farming_skill`/`avg_tools` — all of which already existed in
  `summary()` but were never actually shown anywhere in the UI.

Verified: direct scripts confirmed the grief/social-contact trait
nudges, the monthly random walk's bounded mean-reversion, and
`describe_traits`'s threshold behavior; prompt-injection checks
confirmed both `cognition.build_prompt` and `dialogue.build_prompt`
correctly describe a notably-shaken or notably-resilient agent;
`temperament_confidence_bias` was checked directly against both signs
of temperament and confirmed to respect `phase_g_intensity=0.0`; a
direct `_extend_family` check confirmed the event fires only on actual
family formation, not on a second child joining an existing one. A
6,000-tick full engine run (LLM disabled, seed 7, reproduction odds
forced high) produced genuine `family_formed` events end-to-end and
non-zero `avg_resilience`/`avg_sociability`, with a full `World.
to_dict()`/`from_dict()` round-trip preserving both byte-identically.

## [0.50.0] — H7: inheritance (land, goods, skill, bias) on death

### Added

- **`Population._apply_inheritance`**, called for every dying agent
  from inside `_apply_deaths` (right after grief, before the agent is
  removed). Finds a living heir via the existing H3 family institution
  (`Settlement.family_for`) — the closest living relative by
  relationship value, or nobody if no family survives, a legitimate
  outcome, not a gap. When an heir exists, transfers:
  - **Land**: any HUT the deceased owned (H4) — `Building.owner_
    agent_id` reassigned to the heir.
  - **Goods**: personal `food`/`tools` inventory, added to the heir's
    own (capped the same way each good already is).
  - **Knowledge**: a partial skill transfer — the heir's proficiency in
    any skill the deceased held closes half the gap toward the
    deceased's own level (`INHERITANCE_SKILL_TRANSFER_FRACTION`), "a
    last lesson" rather than a full copy, since skill is procedural and
    can't simply be handed over the way a possession can.
  - **Bias**: a strong distrust the deceased held of someone still
    living (`trust <= INHERITANCE_BIAS_THRESHOLD`) partially carries
    over to the heir's own trust in that person
    (`INHERITANCE_BIAS_TRANSFER_FRACTION`) — an inherited grudge/
    caution, mechanically real rather than only narrated.
  Logs a new `inheritance` category event (UI icon added) only when
  something concrete actually changed hands — most deaths (no home, no
  goods, nothing notable to pass on) stay silent, so the feed isn't
  spammed by every death.

Verified: a direct scenario script (a deceased owning a HUT, holding
food/tools, a farming skill, and a strong distrust of a third living
agent; a family institution linking the deceased to a closer heir and
a more distant relative) confirmed the closer-relationship heir was
correctly selected and received the hut, exact inventory amounts, the
expected partial skill bump (0.8 -> 0.4, exactly half the 0-to-0.8
gap), and the expected partial bias transfer (-0.6 trust -> -0.24,
exactly 40% of the gap) — the more distant relative received nothing.
A no-living-family case correctly produced no inheritance event. A
full end-to-end integration run (real engine tick loop, reproduction
odds forced high, `choose_building_kind` forced to always pick HUT so
ownership had something to transfer, short lifespans to force natural
old-age deaths) produced real `inheritance` events with correct
descriptions ("Ulric inherited from Fenwick: 5 homes, farming
technique.") and left buildings correctly reassigned across
generations, confirmed via `Building.owner_agent_id` inspection after
the run.

## [0.49.0] — H4: building ownership + a real materials->tools supply chain

### Added

- **Building ownership.** New `Building.owner_agent_id: int | None` —
  only HUTs are personally owned in v1 (a home is the natural first
  case of "property"; every other kind stays commons). Set at founding
  (`Population._maybe_start_construction`, the lowest-id eligible
  founder) via a new `owner_agent_id` param on `Settlement.
  start_construction`.
- **A genuine multi-good supply chain.** New personal good `"tools"`
  in `Agent.inventory` (cap `TOOLS_CAPACITY=5.0`). A standing,
  staffed workshop now also converts shared `settlement.materials`
  into personal tools for its awake, well-fed workers, one worker at a
  time each tick as materials last (`Population._maybe_craft_tools`,
  `WORKSHOP_CRAFT_MATERIALS_COST_PER_TICK`/`WORKSHOP_CRAFT_TOOLS_
  PER_TICK`) — additive to the existing `_maybe_run_workshops` currency
  income, not a replacement. Tools then feed back into `Population.
  _maybe_gather`: a tool-equipped gatherer hauls up to
  `GATHER_TOOLS_YIELD_BONUS` (40%) more materials at a full personal
  stash — closing a real loop (gather -> shared materials -> crafted
  tools -> better gathering) where the crafted output belongs to the
  specific worker who made it, the first genuinely owned crafted good
  in the project (everything else workshops/factories produce is
  settlement-wide currency or communal stock). `Population.
  _maybe_trade_tools` mirrors `_maybe_trade_food`'s shape for the new
  good (a GATHER-goal agent with none, colocated with a non-rival
  neighbor who has spare, receives a share). `summary()` gained
  `avg_tools`.

Materials are now a genuinely contested resource across three
consumers (construction, crafting, D10's overflow-selling) rather than
two — a real tradeoff, not just more content. Verified: direct scripts
confirmed HUT ownership assignment (lowest-id eligible founder) and
serialization round-trip; a 50-tick crafting simulation (one workshop,
one worker, 5.0 starting materials) produced tools and drew down the
stockpile; a controlled gather comparison (unequipped vs. a fully
tool-equipped agent on the identical tile/terrain) measured exactly the
intended +40% yield (0.042 vs 0.03 materials/tick); a direct tool-trade
script confirmed transfer + relationship nudge. A 6,000-tick full
engine run (LLM disabled, seed 42) completed with no exceptions and a
full `World.to_dict()`/`from_dict()` round-trip preserved `avg_tools`
and building ownership byte-identically.

## [0.48.0] — H2: belief lineage + family-scoped beliefs; H5: knowledge/skills

### Added

- **H2: belief revision no longer silently overwrites.**
  `llm.beliefs.push_belief_history` snapshots a belief's pre-revision
  `{belief, confidence, revised_tick}` into a new `entry["history"]`
  list (capped at `BELIEF_HISTORY_MAX=3`) before the engine's beliefs
  `apply()` overwrites it — a theory's own past is now visible, not
  destroyed on every revision.
- **H2/H3 crossover: family-scoped beliefs.** `llm.beliefs.
  sync_family_beliefs` mirrors a small copy of any belief that resolves
  to a living family (`subject_family_agent_ids`, from the existing
  per-family belief resolution) onto every overlapping FAMILY
  institution's own `Institution.beliefs` (capped at
  `INSTITUTION_BELIEF_CAP=5`) — "the village believes the Hallow family
  is reckless" is now readable from the family's own institution record,
  not only a settlement-wide list a future consumer would have to
  filter themselves. Wired into `SimulationEngine`'s existing beliefs
  job `apply()`; no new LLM call.
- **H5: knowledge as a system distinct from beliefs.** New `Agent.
  skills: dict[str, float]` (proficiency 0..1 per named skill) —
  deliberately separate from `Settlement.beliefs`/`Agent.memories`
  (interpretive, revisable) since a skill is procedural: applied
  correctly or not. v1 ships exactly one skill, `SKILL_FARMING`, gained
  two ways: slow solo practice (`Population._maybe_forage`'s harvest
  branch nudges the harvester's own proficiency up by
  `SKILL_PRACTICE_GAIN` per successful harvest — "observation"/learning
  by doing) and faster colocated teaching (new `Population.
  _maybe_teach_skills`, same contagion shape as relationship gain/
  gossip contagion: a colocated pair with a wide enough skill gap has a
  small per-tick chance of the more-skilled agent teaching the less-
  skilled one). Mechanically real, not a stub: a farming-skilled
  harvester gets up to +25% hunger relief per harvest
  (`SKILL_FARMING_YIELD_BONUS`), stacking with (not replacing) the
  existing tech-level/tradition harvest bonuses. `summary()` gained
  `avg_farming_skill`.

Verified with direct unit-level scripts: `push_belief_history`/
`sync_family_beliefs` (history caps correctly at 3, family beliefs
upsert rather than duplicate, unrelated families untouched); a 2,000-
tick colocated-pair teaching simulation (skill 0.8 teacher, 0.0 learner
— learner reached 0.66 proficiency, 44 teaching events, a below-
threshold gap correctly taught nothing); a direct harvest comparison
(unskilled harvester: 0.5 hunger relief and gained 0.01 proficiency
from the harvest itself; a mastery-level (1.0) harvester on an
identical plot: 0.625 relief — exactly the +25% bonus). A 6,000-tick
full engine run (LLM disabled, seed 42) with reproduction odds forced
to 1.0 confirmed no exceptions with beliefs/institutions/skills all
live in the tick loop, and a full `World.to_dict()`/`from_dict()`
round-trip preserved `avg_farming_skill` byte-identically.

## [0.47.0] — Wind/storm thresholds fixed; fishing added

### Fixed

- **Wind label ("always windy") and storms ("never shown") were both the
  same class of bug already fixed twice before for precipitation/
  temperature: a threshold tuned against raw per-tick jitter, not
  `compute_weather`'s actual EMA-smoothed realized range.** A 17,520-
  tick measurement across all twelve months found realized wind confined
  to ~0.08-0.66 with p10/p50/p90 of 0.24/0.38/0.51 — `wind_label()`'s old
  cutoffs (calm <0.15, breezy <0.35, windy <0.6) meant "calm" fired on
  under 1% of ticks and "gale" never, so the label read as permanently
  windy. New `CALM_WIND_THRESHOLD`/`BREEZY_WIND_THRESHOLD`/
  `WINDY_WIND_THRESHOLD` (weather.py) retuned to the measured
  percentiles — calm/breezy/windy/gale now each get a real, roughly-even
  share of ticks (measured 10.6%/39.8%/39.9%/9.7%). Separately,
  `disasters.py`'s `STORM_WIND_THRESHOLD` (0.75) was *entirely
  unreachable* against that same measured max of ~0.66 — storms were
  dead code that could never fire, not a rare event, matching the live
  "storms are not shown" report exactly. Retuned to 0.55 (~p90 of
  realized wind, still above `WEATHER_HARSH_WIND`/the new
  `WINDY_WIND_THRESHOLD`) — a direct 2,000-trial check at wind=0.9 fired
  18 times, matching `STORM_CHANCE_PER_TICK=0.01` almost exactly.

### Added

- **Fishing.** New `ResourceKind.FISH` (`world/resources.py`) — a third
  wild-resource kind placed on any walkable tile bordering water
  (river/lake/sea, not tied to the BEACH biome specifically), denser
  than wild food nodes (`FISH_NODE_DENSITY=0.35`), richer per catch
  (`MAX_FISH_AMOUNT=1.5`, `FISH_HUNGER_RELIEF_MULTIPLIER=1.2`× wild
  forage's relief), and faster-regenerating than a bush
  (`FISH_REGEN_PER_TICK`, 1.5× `REGEN_PER_TICK` — a fish stock
  replenishes by migration/spawning, not static local regrowth).
  `Population._maybe_forage`'s wild-node branch and `_nearest_resource`
  (the FORAGE goal's target-seeking chain) both now treat FOOD and FISH
  as the same tier of last-resort wild food, so a hungry agent near
  water fishes exactly the way one near a berry bush forages — no new
  `AgentGoal`, no cognition changes, same shape as the existing
  food/ore split. Map rendering and the "Wild resources" stat tile
  tooltip (`interface/static/app.js`) both distinguish fish nodes
  (blue marker, richer color) from food/ore.

Verified: a direct `ResourceGrid.generate()` check on a real 48x48
terrain confirmed fish nodes generate only adjacent to water and
coexist with the food/ore node counts (34 fish nodes among 231 total on
one seed); a 6,000-tick full engine run (LLM disabled) confirmed no
exceptions with fish nodes present in `resources` summary output.

## [0.46.0] — H3: institutions as first-class entities (families, v1)

### Added

- **`hearthmind.settlement.institutions`** (new module): `Institution`
  — a persistent entity (`id`, `kind`, `founding_tick`,
  `member_agent_ids`, a `beliefs`-shaped list of its own, a `name`) that
  outlives the individuals who belong to it, and `InstitutionKind`
  (only `FAMILY` populated in v1; `Institution`'s shape is deliberately
  generic so future kinds — council, guild, market, religion — reuse it
  rather than each getting a bespoke class). `Settlement.institutions`
  (folded into the existing `SettlementCulture` domain rather than a
  new fifth facade domain — an institution is "part of what the village
  has become," the same category traditions/beliefs already occupy) and
  `Settlement.next_institution_id` are new passthrough-property fields,
  fully wired through `to_dict`/`from_dict`/`summary()` (an empty
  `"institutions"` list backfills cleanly for every pre-v0.46.0
  snapshot). `Settlement.family_for(agent_id)` returns the most
  recently formed family an agent belongs to, or `None`.
- **`Population._extend_family`**: a birth (`_maybe_reproduce`) now
  forms or extends a `FAMILY` institution automatically — a second
  child born to the same parent pair joins the existing family rather
  than starting a new one (matched by both parent ids already being
  members). Deliberately deterministic and unconditional, mirroring how
  reproduction itself is deterministic scaffolding (A3) rather than an
  LLM/goal decision — no consumer beyond serialization/`summary()`
  reads institutions yet in this v1; that's the natural next slice
  (dialogue/beliefs referencing "the Hearth family," H7 inheritance
  moving things through a family on death) once this base exists.

### Notes

Scope is deliberately v1-narrow, per docs/ROADMAP.md's H3 sequencing
call (families first, cheapest and a prerequisite for later items):
only automatic family formation on birth, no deliberate founding (an
agent choosing to start a guild/council/market), no consumption of
`institutions` by cognition/dialogue/beliefs prompts yet, and
`member_agent_ids` is never pruned on death (an institution outliving
its members is the entire point — also the intended anchor point for a
future H7 inheritance pass). `Institution.beliefs` exists but is
unpopulated by anything in this pass — reserved for a future H2/H3
crossover (institution-scoped world models, the same shape
`Settlement.beliefs` already uses).

Verified with a direct unit-level script (three `_extend_family` calls
— two children to the same couple correctly join one family with all
four members; a different couple correctly starts a second family;
`family_for()` resolves both correctly and returns `None` for a
non-member) plus a live-engine integration check: a real birth inside
`World.tick()`'s ordinary tick loop (reproduction odds forced to 1.0
via a monkeypatched constant purely to make a birth observable inside a
short run — no engine logic was bypassed, only the RNG threshold) was
confirmed to produce exactly one family institution with the correct
membership, and both `Settlement.to_dict()`/`from_dict()` and a full
`World.to_dict()`/`from_dict()` round-trip preserve it byte-identically.

## [0.45.0] — H1: dynamic carrying capacity replaces the flat population cap

### Added

- **`Population.carrying_capacity()`** (docs/ROADMAP.md "Phase H",
  explicit user directive to move toward knowledge/economy/institutions
  as living systems rather than hard caps). Composes housing (huts x
  `HUT_CAPACITY` + `CAMP_TOLERANCE`, the pre-existing base), economic
  headroom (granary fill — only scored once a granary exists, so a
  founding party with no infrastructure isn't penalized for
  infrastructure it hasn't had time to build), security pressure
  (sickness fraction + live predator presence), labor availability
  (fraction of mature/healthy agents), and current weather harshness
  into one bounded multiplier (`CARRYING_CAPACITY_MIN/MAX_MULTIPLIER`,
  0.5x-1.5x) applied to the housing base, clamped to `POPULATION_CAP`.
  Recomputed once per tick, stored as `Population.last_carrying_
  capacity`, and exposed via `summary()["carrying_capacity"]` — visible
  to anyone looking at raw data, same treatment temperament/player_
  standing already get.

### Changed

- **`_maybe_reproduce`'s gate is now the dynamic capacity, not the flat
  `POPULATION_CAP`.** `POPULATION_CAP` (400) itself is untouched and
  remains a hard ceiling far above any realistic computed value — a
  safety valve against a tuning mistake in the new composition, not the
  operative constraint anymore. This is the mechanism the July 2026
  review and later live reports both flagged: the town brain's "food"
  priority getting stuck once population approached the flat cap with
  nothing else to steer toward. A settlement now stops growing when its
  actual situation (housing/food/health/labor/weather) says so, not
  when an arbitrary number is hit.

Verified with a direct scenario script (four cases: a founding party
with no infrastructure isn't penalized; a well-fed, developed
settlement with full granaries exceeds its raw housing base; a
settlement under plague + predator pressure + empty granaries + harsh
weather drops capacity below housing but respects the 0.5x floor; and
capacity never exceeds `POPULATION_CAP` regardless of housing size) plus
a real 20,000-tick engine run (LLM disabled, seed 42) confirming no
exceptions and `carrying_capacity` tracking the settlement's state
sensibly tick to tick. A byte-for-byte comparison against the
pre-change population trajectory on the same seed confirmed this
change doesn't itself alter outcomes when housing/granaries never
materialize (both trajectories identical) — the new mechanism only
bites once a settlement actually has infrastructure to reason about.

## [0.44.1] — Ruined buildings clear faster; last unbounded lists capped

### Changed

- **`RUIN_REMOVAL_TICKS` lowered 3000 -> 1200** (~31 sim-days -> ~12.5).
  The removal mechanism was always correct (verified directly — a ruin
  reliably transitions to removed once `ruined_ticks` crosses the
  threshold), but at 3000 ticks it outlived most normal live-observation
  sessions, reading as "ruined buildings are never removed." Also frees
  a ruin's tile back to new construction sooner, which compounds with
  the v0.43.2 housing fixes rather than fighting them (a ruin blocks
  `_maybe_start_construction` from using that tile until it's gone).

### Fixed

- **`Settlement.traditions`/`inventions`/`festivals` grew without
  bound.** v0.40.0 only ever capped what's *sent* to an LLM prompt
  (`PROMPT_CULTURE_LIST_MAX`), not the underlying stored lists — a
  genuinely long-running world would grow these forever. New
  `CULTURE_LIST_MAX_STORED = 300` caps stored length (oldest dropped
  first); new `traditions_established`/`festivals_held` persistent
  counters (inventions already had one: `tech_level`) decouple fallback
  ordinal naming ("Tradition the 14th") from list length, so capping
  the list can't corrupt the numbering. `Settlement.beliefs` was
  already capped (`llm/beliefs.MAX_BELIEFS`) — no change needed there.
  Audited the SQLite layer too: no explicit `cache_size`/`mmap_size`
  pragma is set, so SQLite's own conservative defaults (small fixed
  page cache, no memory-mapping) already keep the ever-growing
  `events`/`metrics` tables a disk concern, not a RAM one — confirmed
  safe, no change needed.

## [0.44.0] — Disease as a population-control valve; LLM concurrency restored to 2; UI flicker fixed; era progression tuned

Five explicit user requests in one batch: never trade LLM richness for
memory (concurrency floor raised back 1 -> 2), a Phase G completeness
check, a UI flicker/layout-jump fix, a real population-control
mechanism now that runs reach the 400 cap, and a look at why era
progression (industrial -> electrical -> modern -> digital) was never
observed live.

### Changed

- **`llm_max_concurrent` raised 1 -> 2.** Explicit instruction: LLM use
  is non-negotiable, memory optimization must come from elsewhere.
  `llm_num_ctx`/`llm_num_predict`/`llm_keep_alive` (v0.43.0/v0.43.1)
  remain the memory levers; concurrency will not be lowered below 2
  again. See docs/DECISIONS.md, "LLM concurrency floor restored."
- **Phase G: audited, confirmed complete.** Every docs/ROADMAP.md Phase
  G checklist item is already `[x]` and verified present in code
  (temperament, omens, intensity knob, trust lever, player standing,
  shrine/omen interaction, omen memory). The one remaining "not built"
  note (no player-facing acknowledgment the system exists) is a
  deliberate permanent design choice, not a gap. No code changes were
  needed or made.
- **`INVENTION_CHANCE_PER_SEASON` raised 0.15 -> 0.2**, after measuring
  that reaching `electrical` took ~5 in-game years on average and
  `digital` ~20 — plausibly longer than most live sessions run, hence
  never being observed. Now roughly ~3.75/~15 years — still a genuine
  long-run milestone (era thresholds themselves untouched), just
  observable within a realistic play/observation session. The v0.43.2
  HUT-decay/crowding fixes were an incidental beneficiary too: a
  settlement whose materials no longer crash near the population cap
  also clears the invention prosperity gate more reliably.

### Added

- **Disease: a real, deterministic population-control mechanism.**
  `Population._maybe_outbreak` rolls a small, settlement-wide chance
  each tick for a new spontaneous illness case, scaled by population
  size and boosted while the settlement is crowded (reusing the same
  housing-pressure signal that already drives `CROWDING_ENERGY_
  MULTIPLIER`) — real epidemiology: crowd diseases originate and
  spread more readily in dense, under-housed populations, so this
  engages exactly where the hard 400 cap was creating an artificial,
  invisible ceiling instead of a believable one. `Population.
  _tick_disease` advances every sick agent (`Agent.sick_ticks`) each
  tick: person-to-person transmission to colocated healthy agents,
  natural recovery after `SICKNESS_DURATION_TICKS`, and a per-tick
  death chance calibrated to roughly an 8% case-fatality rate per bout,
  halved by a standing hospital (mirroring predator-attack lethality's
  `HOSPITAL_KILL_CHANCE_REDUCTION`) and nudged by settlement
  temperament. Sick agents also drain energy/hunger faster
  (`SICKNESS_ENERGY_DRAIN_MULTIPLIER`/`SICKNESS_HUNGER_RATE_
  MULTIPLIER`), so illness has a felt mechanical cost, not just a
  death roll. New `deaths_disease` counter, `sick_count` in population
  summary/diagnostics, `illness`/`recovery` event categories (🤒/💊 in
  the UI), and a consequences-overlay line ("Sickness is spreading
  through the village") once >5% of the population is sick.
  Deliberately no immunity/reinfection modeling in v1 — a recovered
  agent is immediately susceptible again, same "smallest coherent
  milestone" scoping as everywhere else in this project.
- **Town brain gets a real disease-driven "health" priority trigger.**
  `town_brain.fallback_priority` now checks actual illness burden
  (>5% of population sick, no hospital) instead of only the old, very
  narrow "a predator has ever killed someone and there's no hospital"
  arm — and the LLM prompt itself now mentions the current sick count.
  Directly addresses the standing "town brain gets stuck on food"
  complaint: a real epidemic can now surface a competing, equally
  legitimate civic priority.

### Fixed

- **UI: sidebar panels "jumping around" / flickering.** Root cause
  (confirmed by direct investigation): variable-length list panels
  (beliefs/traditions/inventions/festivals/infrastructure) had no
  minimum height, so every tick's list rebuild could resize the panel
  and shove everything stacked below it up or down — plus those lists
  were fully rebuilt via `innerHTML` on *every* tick regardless of
  whether the content actually changed, losing any manual scroll
  position in the process. Fixed with a CSS `min-height` matching the
  existing `max-height` cap on the five affected list elements, and a
  new `setInnerHTMLIfChanged` helper (`interface/static/app.js`) that
  skips the DOM write entirely when the new markup is identical to
  what's already rendered — cuts needless per-tick reflow and stops
  scroll position from resetting on unchanged data.

## [0.43.2] — Fixed: unpaid civic upkeep + lockstep building decay were collapsing HUT housing near the population cap

Root-cause investigation into a live report of population "still
declining and dying of starvation." Found two compounding real bugs,
not just the already-documented Malthusian equilibrium — the first fix
alone measurably delayed but did not prevent the collapse, so a second
fix followed in the same investigation. Verified with a matched
three-way A/B (baseline / fix 1 only / both fixes, seed 42, default
config, LLM disabled): cumulative starvation deaths at tick 20,000 were
12 (baseline), 12 (fix 1 only, unaffected — the bug it fixes hadn't
been hit yet at that tick), and 3 with both fixes; by tick 26,000-
28,000, both baseline and fix-1-only had collapsed into deep housing
deficits (huts_standing 78->16 and 98->47 respectively, cumulative
deaths 147 and 216), while both fixes together showed zero housing
deficit and huts_standing climbing smoothly with population throughout.

### Fixed

- **`Settlement.tick()`'s upkeep-driven decay penalty was applied to
  every standing building, including HUTs, which draw zero upkeep.**
  `UPKEEP_UNPAID_DECAY_MULTIPLIER`'s own docstring says it should make
  "civic buildings wear out faster" when the settlement can't afford
  their upkeep — but the code computed one shared `decay` value
  (boosted by the unpaid-upkeep fraction) and applied it to *every*
  standing building in the loop, HUTs included, even though HUTs are
  explicitly excluded from `civic_standing`/`upkeep_due` and draw no
  currency at all. As a settlement's civic-building count grows near
  the population cap, per-tick upkeep (`civic_standing x
  UPKEEP_PER_CIVIC_BUILDING_PER_TICK`) outpaces currency income, the
  unpaid fraction climbs toward 1.0, and every HUT — the settlement's
  entire housing supply — started decaying up to 1.5x faster for a
  bill they never incurred. A matched 44,000-tick diagnostic (seed 42,
  default config, LLM disabled) showed `huts_standing` collapsing 78 ->
  16 in a single 2,000-tick window right as population approached the
  400 cap, with cumulative starvation deaths jumping from 21 to 293
  across the same stretch — a self-reinforcing spiral: unpaid upkeep ->
  huts ruin faster -> housing capacity drops -> more agents crowded ->
  `CROWDING_ENERGY_MULTIPLIER` forces more agents into RESTING -> fewer
  idle agents left to repair anything (`_maybe_repair` needs a
  colocated, non-critically-hungry pair) -> decay keeps winning. Fixed
  by splitting the shared `decay` into a HUT-exempt base rate and a
  `civic_decay` rate (upkeep penalty included) applied only to non-HUT
  standing buildings — HUTs now always decay at the plain weather/
  season rate regardless of the settlement's currency situation,
  matching the mechanic's own stated design.
- **Building decay has zero per-building variance, so HUTs built in the
  same growth spurt approach ruin in lockstep — and idle agents had no
  way to notice.** A matched follow-up run (same seed, only the fix
  above applied) showed the collapse still happened, just delayed and
  arguably worse in absolute terms (huts_standing 98 -> 47, cumulative
  deaths 28 -> 216 in one 2,000-tick window) — `Settlement.tick()`
  applies the exact same `decay` value to every standing building of a
  kind every tick (weather/season are settlement-wide), so a batch
  built together has near-identical condition trajectories and crosses
  `REPAIR_THRESHOLD` together. `_maybe_repair` only fires from
  *incidental* colocation, and `AgentGoal.WANDER` (a common idle
  fallback goal) had zero attraction toward a decaying building — so a
  synchronized batch of HUTs could collectively run out of repair
  attention with nobody nearby to catch it. Fixed by adding
  `Population.damaged_building_positions` (mirrors `ready_farm_
  positions`/`stocked_granary_positions`) and a new WANDER-goal branch
  in `_dispatch_movement` that biases movement toward the nearest
  below-threshold building — the same pattern FORAGE already uses for
  food, no new `AgentGoal` or cognition-prompt changes. With both fixes
  together, `huts_standing` tracked population smoothly through the
  entire tested range with zero housing deficit, and cumulative
  starvation deaths stayed at 2-3 through tick 22,000 versus 12-17 for
  both the unfixed baseline and the first fix alone at the same ticks.

## [0.43.1] — More aggressive Ollama memory optimization: concurrency floor, keep_alive

v0.43.0's `llm_max_concurrent=2` still wasn't enough to prevent the
reported swap/unresponsiveness at 100 population on real hardware — a
user request for "more aggressive" optimization.

### Changed

- **`llm_max_concurrent` lowered 2 -> 1** (its floor — fully serialized,
  never more than one Ollama `generate` call in flight system-wide).
  This trades LLM-driven decision *richness* (more agents/settlement
  jobs resolve via deterministic fallback under a saturated single
  lane) for memory headroom, not correctness or liveness — every LLM
  call already has an instant fallback.
- **`llm_timeout_seconds` bumped 45 -> 60.** Not strictly required (the
  per-call timer starts once a job acquires the semaphore, not while
  queued), but buys real margin against the now fully-serialized worst
  case at negligible cost.
- **New `Config.llm_keep_alive` (`"3m"`), sent as Ollama's top-level
  `keep_alive` field on every call.** Previously never sent, so the
  Ollama server's own default governed how long the model stays loaded
  after the last call — on some servers that's indefinite. 3 minutes is
  short enough to actually release memory during a real lull in
  activity, long enough to avoid constant reload churn during normal
  sim cadence. `OllamaClient` gained a `keep_alive` field to carry this.

## [0.43.0] — Fixed: Ollama-side memory pressure; weather variety ("only rain")

The same live symptom as v0.42.0 (heavy swap, unresponsive 8GB system,
~100 population) recurred within an hour even after that fix landed —
the v0.42.0 writeup's claim that the symptom was "not LLM/Ollama memory
pressure" was too narrow: it correctly ruled out a leak *inside this
process* (confirmed by the matched probe, which stayed under 100MB
RSS) but never checked the separate Ollama server process, which is
real system memory the OS can swap regardless of which process holds
it.

### Fixed

- **`llm_max_concurrent` lowered 4 -> 2.** The v0.39.0 architecture
  review already recommended this ("do not raise `llm_max_concurrent`
  on CPU; consider lowering to 2" — recorded verbatim in this file's
  CLAUDE.md) but it was never acted on. Each in-flight Ollama `generate`
  call holds its own KV-cache allocation in the Ollama server process;
  4 simultaneous calls (now routine, since cognition/dialogue/chronicle/
  culture/town-brain/beliefs/omens all share the same scheduling path)
  multiply that footprint 4x. "Not budget-constrained on the user's
  hardware" (the reasoning that raised this 2->4 in E2) was true for
  wall-clock throughput but is a different axis from concurrent memory
  footprint.
- **`Config.llm_num_ctx` (2048) / `Config.llm_num_predict` (512), new,
  sent on every Ollama call.** Previously unset, so Ollama used its own
  server-side default context window and had no cap on generated
  tokens — a hidden, unbounded-in-the-worst-case memory/latency
  multiplier on top of `llm_max_concurrent`. Every prompt in this
  project is capped short and comfortably fits well under 2048 tokens;
  this is a safety ceiling, not a working limit anything here should
  hit. `OllamaClient` now accepts `num_ctx`/`num_predict` and sends
  them as Ollama's `options` object when set.
- **Weather showed rain almost every tick regardless of season — a
  live-reported "I only see rain" symptom, confirmed by measurement.**
  `WeatherState.describe()`'s sky-band cutoffs (clear <=0.08, overcast
  <=0.25, heavy >0.6) were tuned against the raw per-tick jitter, but
  `compute_weather`'s smoothing (the same EMA already documented for
  the snow-threshold fix) damps that into a much narrower realized
  range. A 200k-tick measurement across all twelve months found
  realized precipitation essentially never below ~0.11 or above ~0.67
  — "clear" was literally unreachable (0th percentile) and the world
  sat in "light rain" (0.25-0.6) roughly 90%+ of the time. Retuned the
  three cutoffs to the measured p10/p50/p90 (0.27/0.38/0.50), giving
  clear/overcast/light-rain/heavy-rain each a real, roughly-even share
  (measured post-fix: 11%/40%/39%/10% + 0.4% snow). The frontend rain-
  particle overlay (`interface/static/app.js`) had the identical bug
  independently — it spawned particles off raw `precipitation` with a
  clear-threshold of 0.05 (also unreachable), so rain visually never
  stopped; rescaled against the same measured floor/ceiling so a clear
  sky now shows no particles at all and intensity actually varies.

## [0.42.0] — Fixed: unbounded relationship/trust memory growth

A user-reported live symptom (heavy swap usage and an unresponsive
system at only 100 population) traced to a real leak, not LLM/Ollama
memory pressure — see docs/DECISIONS.md for the measured before/after.

### Fixed

- **`Agent.relationships`/`Agent.trust` grew without bound.** A
  relationship entry was created the first tick two agents shared a
  tile and never removed — not when it decayed back to 0 (a
  transient, one-time encounter), and not when the other agent died.
  Every acquaintance a villager ever had, living or dead, stayed in
  their dict for the rest of the world's life. Measured (fallback-only,
  seed 3, population starting at 100, matched A/B run to tick 50,000
  through a population boom and a starvation-driven crash): the
  boom peaked at 112,075 total relationship entries at population 229
  (489 per agent) in the unfixed baseline, versus 23,600 entries (103
  per agent) at the same tick with the fix — a >4.7x reduction at the
  same moment in the same run. The crash (population 229 -> 36 by
  starvation) is the clearest demonstration of the bug: baseline
  survivors kept 322 relationship entries per agent afterward — mostly
  references to the 751 people who had died by that point — while the
  fix dropped to 19 per agent, correctly reflecting who was actually
  still alive to know. Process RSS over the full 50k-tick run: baseline
  43 -> 118 MB (2.7x), fix 41 -> 90 MB, with the fixed run's peak driven
  by the same legitimate population boom rather than accumulated dead
  weight.
- Fix, in `Population._update_relationships`/`_apply_deaths`: an entry
  that decays to exactly 0.0 is now deleted (a pair whose bond faded
  reads identically via `.get(id, 0.0)` either way — no behavior
  change, purely a memory bound), and every survivor's relationship/
  trust entries for a dying agent are stripped at the same point grief
  is processed.
- `GET /diagnostics` now reports `relationship_graph` (total entries,
  trust entries, average per agent) so this class of leak — a live
  soak run's average climbing over time — is visible without a custom
  probe if anything similar is ever reintroduced.

## [0.41.0] — Founding funnel fixed; Settlement split; culture riders; shelter/upkeep; job framework; sparklines; experiment runner

The remaining July 2026 architecture-review recommendations, performed
(docs/REVIEW-2026-07.md; see docs/DECISIONS.md "review implementation,
second pass" for design calls and verification data).

### Fixed — the early-population collapse funnel

- **Worlds now begin March 1** (`Config.start_day_of_year`, creation-
  only): the measured funnel was twelve strangers scattered across a
  deep-winter map (regen x0.3, farm growth x0.35) with no
  infrastructure. Older snapshots keep their original January-start
  calendar (offset defaults to 0 on load).
- **Founders spawn as a group near food**: the walkable tile with the
  most wild food nodes within `FOUNDING_SITE_RADIUS` becomes the
  founding site, and everyone starts within `FOUNDING_CLUSTER_RADIUS`
  of it — the spot a real expedition would have chosen, and the group
  can actually meet (bonds, construction pairs) in days instead of
  weeks.

### Added — architecture (the multi-settlement enabler)

- **`Settlement` split in place** into four composed domain objects —
  `SettlementInfrastructure` (buildings/vehicles/id spaces),
  `SettlementEconomy` (materials/currency/education),
  `SettlementCulture` (name/era/tech/traditions/inventions/festivals/
  beliefs), `SettlementDisposition` (temperament/omens/player standing/
  whispers/civic priority) — with property passthroughs for every
  legacy flat attribute and byte-identical serialization. Call sites
  and snapshots are unchanged; the future multiple-named-settlements
  pass now instantiates four small objects per settlement instead of
  untangling a ~25-field God object.
- **LLM job framework**: the nine settlement-level jobs (naming,
  chronicle, documentary, tradition, invention, festival, town brain,
  beliefs, omen) now share one `_schedule_llm_job` path (bounded run +
  apply-closure + contained apply errors + debug/fallback bookkeeping)
  instead of nine hand-rolled `_run_X` coroutine copies.

### Added — emergence

- **Culture with mechanical teeth**: a new tradition also classifies
  which lever of village life it strengthens (`influence`: festivity /
  harvest / resilience / none — fixed menu, safe for a 2B model), and
  each accumulates a bounded stack (`Settlement.culture_effects`,
  `culture_effect_multiplier`, at most ~1.24x): festivity deepens every
  festival's bond boost, harvest stretches farm-harvest relief,
  resilience softens grief's energy cost. Two villages with different
  histories now mechanically *work differently*.
- **Buildings shelter people**: an awake agent on a standing building's
  tile is exempt from harsh-weather need multipliers
  (`SHELTER_NEGATES_WEATHER`) — working indoors.
- **Housing pressure**: population beyond `huts x HUT_CAPACITY +
  CAMP_TOLERANCE` applies a mild awake energy-drain multiplier — the
  town brain's "growth" priority (more huts) finally relieves a real
  pressure.
- **Civic upkeep**: standing non-hut buildings draw currency per tick;
  the unpaid fraction accelerates their decay — the economy's first
  recurring sink, closing currency -> upkeep -> decay -> repair labor.
- **Age-graded frailty**: past 80% of their own lifespan, agents
  recover energy at x0.7 while resting — elders visibly slow down
  before the end instead of dying off a cliff.

### Added — observability & research

- **Sparklines**: the details panel opens with "A year in curves" —
  population, hunger, and granary-food sparklines drawn client-side
  from `GET /metrics` (one point per sim-day, refreshed on a slow
  timer).
- **`hearthmind-experiment`**: a headless batch runner
  (`hearthmind/experiment.py`) — N seeds x M ticks under a chosen
  config (`--no-llm`, `--phase-g-intensity`, `--label`), each run's
  per-sim-day metrics exported to CSV. The A/B harness that finally
  lets "did the LLM measurably change macro outcomes?" be answered
  with paired runs.

### Changed — performance

- Ready-farm and worth-the-walk-granary position lists are computed
  once per tick and shared by every food-seeking agent (previously
  each agent re-walked the plots dict/building list).
- `TERRAIN_CHANGING_CATEGORIES` is now canonical in `world/state.py`;
  the engine's broadcast invalidation imports it instead of keeping
  its own copy.

## [0.40.0] — Architecture review implemented: carrying capacity, LLM backpressure, gossip, metrics

Performs the July 2026 architecture review's recommendations
(`docs/REVIEW-2026-07.md`) — the emergence, LLM-architecture,
performance, and persistence changes it prioritized. Verified against
its own measured baselines (see docs/DECISIONS.md).

### Changed — emergence (carrying capacity replaces the hard cap as the real limit)

- **Planting is now a deliberate act**: a farm is only planted when a
  colocated awake agent is food-focused (FORAGE goal, or genuinely
  hungry) — a well-fed village stops planting. This also gives the
  cognition layer's goal choice real mechanical teeth for the first
  time (the review measured that goals previously didn't affect
  survival outcomes at all).
- **Standing crops rot**: a READY farm plot unharvested for
  `FARM_ROT_TICKS` (~15 sim-days) spoils and reverts to open land —
  food is a flow to be harvested in its window, not an ever-growing
  stock. (Baseline measurement: ~800-1,000 simultaneously-ready plots
  for <=200 people; post-change: peaks around 150-250.)
- **Reproduction follows surplus**: a pair now also needs saved
  personal food or both parents clearly well-fed
  (`REPRODUCTION_WELLFED_HUNGER`) — a hard winter shows up in the
  birth rate, not just the death rate.
- `POPULATION_CAP` raised 200 -> 400 and demoted to a pure safety
  valve — the food economy is meant to be the binding constraint now.
- **Gossip moves opinion**: a rumor naming a living third villager
  relaxes each trusting listener's opinion of them toward the
  speaker's (`GOSSIP_OPINION_CONTAGION`, capped per rumor, skipped by
  skeptical listeners) — opinions now propagate through conversations,
  not only through direct contact.

### Changed — LLM architecture

- **Backpressure**: no new routine cognition/dialogue jobs are
  scheduled while the runner's backlog exceeds
  `llm_max_concurrent x BACKPRESSURE_BACKLOG_PER_SLOT` (triggered
  emergencies get 2x headroom; dialogue is shed first). Fixes the
  unbounded task backlog + sim-days-stale results the review found in
  live runs at pop >~50. Drops are counted
  (`calls_dropped_backpressure`) and visible in the dev console.
- **Staleness guards**: cognition results older than
  `STALE_GOAL_RESULT_TICKS` (and dialogue older than
  `STALE_DIALOGUE_RESULT_TICKS`) are dropped at apply time instead of
  steering agents on days-old snapshots.
- **Cognition prompt grounding**: the goal prompt now includes who is
  colocated, distance to the nearest known food, the agent's current
  goal, and the last 3 memories (was: only the single newest memory,
  no local facts).
- **Beliefs can now be wrong**: the beliefs prompt no longer receives
  the ground-truth stat block — only event narrations and its own
  prior theories — so the village's self-model can genuinely drift and
  get corrected, per the design goal.
- **Belief revision by subject**: a new-belief answer whose subject the
  village already theorizes about revises that entry instead of piling
  up duplicates (`find_belief_index_by_subject`) — subject identity is
  more reliable than a 2B model's integer indexing.
- **Conversations are remembered**: surfaced exchanges leave a
  "Talked with X — ..." memory in both agents, so future prompts can
  reference the last conversation.
- **Whispers survive fallback**: `player_influence` is now only
  consumed when the town-brain LLM call actually succeeded; on
  timeout/fallback the whisper stays queued for next month (was:
  silently discarded).
- **Town-brain fallback un-locked**: the "food" arm's granary test now
  also requires people to actually be somewhat hungry — the review
  measured the fallback stuck on "food" for entire 30k-tick runs
  because its denominator grew with every granary built.
- **Prompt token bounding**: only the newest `PROMPT_CULTURE_LIST_MAX`
  traditions/inventions reach any single prompt (the stored lists are
  untouched).

### Changed — performance (measured: ~2-2.5x faster ticks at every population)

- The per-agent rival-tile scan in movement was O(N^2) per tick (~40%
  of population-tick time at 200 agents); rival positions are now
  precomputed once per tick from each agent's own relationships.
  12/200/500 agents: 1.3/7.9/45.9 ms -> 0.5/3.2/22.2 ms per tick.
- `Settlement.at` is now a lazily-rebuilt `(x, y) -> Building` index
  instead of a linear scan (it's called several times per agent per
  tick).
- The flood system's water-tile set is cached and only recomputed
  after a tick that actually changed some tile's biome
  (`TERRAIN_CHANGING_CATEGORIES`, now canonical in `world/state.py`).

### Changed — persistence (the "runs forever" fixes)

- **Snapshots are pruned**: `save_snapshot` keeps the newest
  `SNAPSHOT_KEEP_RECENT` rows plus one keyframe per
  `SNAPSHOT_KEYFRAME_INTERVAL_TICKS` — the table was append-only
  full-world JSON forever, the review's biggest disk-growth finding.
- **One commit per tick**: events (and metrics) written during a tick
  batch into a single end-of-tick commit instead of one fsync per
  event.
- New index `idx_events_category` — `/history` and the category
  histogram stop scanning as the log grows.

### Added

- **Daily metrics time-series**: a new `metrics` table gets one
  compact row per sim-day (population, hunger, deaths by cause, bonds/
  rivalries, farm/granary/materials/currency, wildlife, tech,
  priority, temperament, rumor/fallback counters), exposed at
  `GET /metrics` — the instrumentation layer for studying the sim as
  an artificial society (ablations, rumor spread, belief drift).
- **Unique agent names**: births/migrants now draw a name no living
  inhabitant bears (`Population._unique_name`) — duplicate names were
  near-certain at ~200 living agents and silently broke per-person
  belief resolution (`resolve_subject_agent_id` refuses ambiguous
  names).

## [0.39.0] — Per-agent inventory/trade, culture-specific buildings, per-family beliefs, Phase G v4

Picks up two of the remaining large-and-explicitly-flagged gaps (scoped,
not the maximal version of either) plus two smaller named gaps and one
more Phase G increment, per explicit user request.

### Added

- **Per-agent inventory/trade** (`Agent.inventory`) — a deliberately
  scoped first slice of the "genuinely large, architecturally separate"
  per-agent economy gap: a single good (personal food), stashed as a
  skim off successful farm/granary foraging (`FORAGE_INVENTORY_SKIM`),
  drawn on by the agent themselves before scrounging elsewhere, and
  directly shared with a colocated, non-rival, food-lacking neighbor
  (`Population._maybe_trade_food`) at a small relationship cost/gain to
  both sides. Not a market, not hauling, not multi-good — a real,
  mechanically complete first step, not a stub.
- **Culture-specific building type**: `BuildingKind.SHRINE`, foundable
  only once the settlement has established at least one tradition
  (`choose_building_kind`'s new `has_tradition` gate). A standing
  shrine deepens festivals held on its tile
  (`SHRINE_FESTIVAL_BOOST_MULTIPLIER`) and slightly raises the monthly
  omen-firing chance (`SHRINE_OMEN_CHANCE_MULTIPLIER`) — the first
  direct interaction between the new culture-buildings gap and Phase G.
- **Structured per-family belief resolution**:
  `beliefs.resolve_family_agent_ids` widens a belief's resolved
  `subject_agent_id` to that person's living parents/children/full
  siblings (computed fresh from `Agent.parents` each formation/
  revision, not a separate family-id store), stored as
  `subject_family_agent_ids`. Dialogue's `beliefs_about` now also
  matches on family membership, so "the village believes the Hallow
  family is reckless" reaches every living Hallow's conversations, not
  only whichever name the LLM happened to write.
- **Phase G v4**: `SHRINE_OMEN_CHANCE_MULTIPLIER` (see above) — the
  first Phase G nudge driven by a player-visible building rather than
  pure event-count fortune, still small and non-dominant.

### Deliberately not attempted this batch

- **Multiple named settlements** (`Settlement` stops being a
  world-wide singleton) remains out of scope — a genuinely
  architecture-breaking refactor touching population/engine/every LLM
  prompt/the interface layer/snapshot schema, correctly flagged in
  CLAUDE.md as too large to bundle safely alongside other work.
  Attempting it in the same pass as the above risked leaving the
  simulation in a half-migrated, unverifiable state, which the
  project's own "no half-finished pieces," "audit before continuing,"
  and "preserve existing behavior" rules all argue against. See
  docs/DECISIONS.md for the explicit scoping rationale.

## [0.38.0] — Phase G v3: temperament's reach, omen memory

Deepens Phase G further per explicit user request — still within the
standing "keep this ambiguous, permanently" constraint (CLAUDE.md):
nothing here confirms anything supernatural, it only extends where
`Settlement.temperament`'s existing small-magnitude influence reaches
and gives `llm/omens.py` a memory of itself.

### Added
- **Temperament's mechanical reach extended to two more systems**,
  same warm-only, small-magnitude (~0.2 fractional) treatment as the
  existing invention-chance/predator-lethality nudges:
  - **Migrant arrivals** (`Population._maybe_welcome_migrant`): a
    village with recent good fortune draws a newcomer somewhat more
    readily (`MIGRANT_TEMPERAMENT_INFLUENCE`). Deliberately one-sided
    — ill fortune doesn't suppress this, since it's already the sole
    recovery path out of a population crash and shouldn't be actively
    worked against by the same bad luck that likely caused the crash.
  - **Wildlife recolonization** (`WildlifeGrid.tick`): the land itself
    recovers a herd/pack somewhat more readily during a warm spell
    (`WILDLIFE_TEMPERAMENT_INFLUENCE`), same one-sided rationale.
- **Omen memory.** New `Settlement.omen_history` (capped rolling log,
  same shape as `priority_history`) records every omen that's fired.
  Recent omens are now optionally offered back into the next omen
  prompt as texture — a new sighting can occasionally read as an echo
  of something noticed before ("that crow again") rather than always
  being a one-off, deepening the "ancient, subtle intelligence with a
  long memory" framing. Optional, not mandatory — most omens still
  stand alone, and nothing is ever confirmed either way.

### Notes
- Still no player-facing acknowledgment that Phase G exists anywhere in
  the UI — deliberately, permanently, per CLAUDE.md.

## [0.37.0] — Everything left from the original plan, including Phase G

Closes out essentially every remaining "not yet built" item across
`docs/ROADMAP.md` and CLAUDE.md's flagged next steps — excluding the
two items the project's own docs call out as genuinely large,
architecturally separate efforts (per-agent inventory/trade, multiple
named settlements), which stay explicitly out of scope for a single
batch.

### Added — Phase A (ecology & relationships)
- **Deliberate hunting, corrected from a stale roadmap note.** FORAGE's
  target-seeking already walks a hungry agent toward a known grazer
  herd (`_nearest_grazer_herd`), not just opportunistic consumption
  when colocated by chance — a dedicated `AgentGoal.HUNT` would have
  duplicated that. `docs/ROADMAP.md` corrected.
- **Vegetation depletion tied to grazing.** A grazer herd colocated
  with a wild FOOD `ResourceNode` now consumes a small amount of it
  each tick and skips reproduction on an overgrazed tile — real
  competition between wildlife and agent foraging for the first time
  (`world/wildlife.py`'s `GRAZE_CONSUMPTION_PER_TICK`/`GRAZE_
  REPRODUCE_MIN_FOOD`).
- **Rivalry-driven avoidance.** A rival's tile (relationship at or
  below `RIVALRY_THRESHOLD`) is now folded into the same prefer-avoid
  set predator tiles already use in movement dispatch — an agent
  actively steers around a rival, not just carries a lower affinity
  number.

### Added — Phase B (cognition)
- **Event-triggered cognition, beyond the daily cadence.** A hunger
  emergency or fresh grief now schedules an immediate goal
  re-evaluation (`Population.due_for_triggered_cognition`, with its
  own per-agent cooldown so a sustained crisis doesn't hammer the LLM
  every tick) instead of waiting for the agent's next staggered daily
  slot — a real, timely reaction using current state, not stale
  up-to-a-day-old context.

### Added — Phase C (construction)
- **Civic priority now steers *whether* to build, not just *what
  kind*.** The town brain's current priority already weighted which
  building kind gets founded; it now also scales the settle-chance
  roll itself (`SETTLE_CHANCE_GROWTH_PRIORITY_MULTIPLIER`/`_OFF_
  PRIORITY_MULTIPLIER`) — a settlement prioritizing growth is
  measurably likelier to found something at all. *Where* to build
  remains pure-chance colocation, a separate and larger change not
  attempted.

### Added — Phase G (subtle supernatural layer) + adjacent gaps
- **Intensity knob.** `Config.phase_g_intensity` (default 1.0) scales
  temperament's monthly step and omens' per-month chance together;
  0.0 is a genuine off switch (temperament holds flat, omens skip
  outright) without deleting the mechanism.
- **Person-specific omens.** About half the time an omen fires, if a
  belief already resolves to a still-living agent, the omen now
  centers on that person specifically (`llm/omens.py`'s `subject_name`,
  both the LLM prompt and new subject-templated fallback pools) rather
  than the settlement in the abstract — still never confirming
  anything, just less anonymous.
- **Trust lever.** New `Agent.trust` (-1..1 per source agent), distinct
  from `relationships` (fondness) — how much credibility an agent gives
  another's word. Nudged asymmetrically on dialogue (easier to lose
  than earn); a rumor from a source below `TRUST_SKEPTICISM_THRESHOLD`
  is now remembered with visible skepticism instead of at face value,
  which reaches that agent's own future cognition prompts.
- **The town's opinion of the player.** New `Settlement.player_standing`
  (-1..1), a real deterministic bounded random walk (`tick_player_
  standing`, same shape as `temperament`) nudged monthly by recent
  `/intervene/*` volume, mean-reverting without reinforcement. Folded
  into the town-brain prompt as one more quiet input once notably
  warm/cold — never narrated or labeled in the UI.

### Notes
- Deliberately not attempted: per-agent inventory/trade, multiple named
  settlements (both flagged large/architecturally-separate in the
  project's own docs), culture-specific building types, structured
  per-family belief resolution, a true scrub-through-time replay view,
  and *where* to build. See `docs/ROADMAP.md` for the full per-item
  accounting and `CLAUDE.md`'s "Known architectural gaps" section.

## [0.36.1] — Sidebar restructure: map-as-primary-interface, the last backlog item

Closes the one item 0.36.0 explicitly left as "partial": the sidebar
itself carried its full panel set regardless of relevance. Restructured
so only the two panels the Observatory UI direction names for "normal
UI, understanding the world" — Town Brain and Recent Events — are
visible by default. Everything else (raw stat tiles, beliefs/
traditions/inventions/festivals lists, infrastructure detail) now lives
behind a new "📊 details" header toggle, using the exact same show/hide
pattern already established for history/relationships/dev-console —
reachable, not gone, just not the first thing shown, per the brief's
own wording. Verified live in a browser (Playwright): default view is
now just the map + two panels + the consequences overlay; the details
toggle correctly reveals/hides the grouped stat tiles and culture
panels; hover, the NPC inspector, and sim-speed controls all still work
unaffected by the restructure.

With this, every item CLAUDE.md's Observatory UI direction section
listed is now either done or explicitly, narrowly scoped (documentary
mode's cadence/source, the consequences overlay's specific phrasings,
etc.) — no remaining "not started, deliberately" entries.

## [0.36.0] — Observatory UI backlog complete: hover, NPC inspector, consequences overlay, surfaced conversations, Town Brain monologue, documentary mode

Closes out the rest of the Observatory UI backlog CLAUDE.md scoped last
session (0.34.0) but deliberately deferred, plus the relationship graph
started in 0.35.0. Six pieces, one batch:

### Added
- **Hover inspection extended to the whole map**, not just agents.
  Hovering a building shows kind/stage/condition (and construction
  progress while under way); hovering bare terrain shows its biome and
  coordinates. Agent hover tooltip now hints "click for details."
- **NPC inspector modal**, mind-first per the brief: clicking an agent
  opens a panel leading with their current goal and *why* they chose it
  (`goal_reason`), what the village's collective beliefs say about them
  (`Settlement.beliefs` filtered by `subject_agent_id`), their named
  relationships (not raw IDs, sorted by strength), and recent memories
  — vitals (hunger/energy/position) are a single small row at the
  bottom, not the headline. Stays open and live across ticks while
  inspecting the same agent.
- **Consequences overlay** on the map itself: a small overlay strip
  (bottom-left of the map panel) surfaces plain-language readouts —
  "The village is aging," "Granaries are nearly full," "Food stores are
  running dangerously low," "Wolves have returned," "A heatwave grips
  the land," "Floodwater has swallowed part of the village," "Wildfire
  is spreading through the forest," "The village teeters on the edge of
  extinction" — computed client-side from stats already in the payload,
  the exact examples the brief named. Threshold for "aging" mirrors
  `agent.py`'s own `MIN_LIFESPAN_TICKS` constant.
- **Surfaced conversations**: `Population.apply_dialogue` now returns
  whether an exchange was significant (crossed into a close bond or
  rivalry, or carried a rumor) alongside the two agents. Significant
  exchanges log under a new `dialogue_surfaced` category (shown in the
  main event feed and the curated History tab); routine background
  chatter stays under the existing `dialogue` category, which the main
  feed now filters out by default (still fully recorded — `/events` and
  the dev console see everything) — "record all conversations
  internally, surface the ones that changed something."
- **Town Brain monologue**: `Settlement.priority_history` keeps the
  last 6 seasonal town-brain decisions (tick/priority/rationale), not
  just the current one. The Town Brain panel now shows past rationales
  beneath the current priority — read together, they read as an
  ongoing internal train of thought ("what the town notices, values, or
  is quietly influencing"), not a single overwritten line.
- **Documentary mode**: a new yearly LLM job (`llm/documentary.py`,
  gated on the rare `year_end` calendar boundary — deliberately the
  slowest narrative cadence, rarer than chronicle's monthly one) writes
  a short narrated look-back over the year's curated milestones
  (`persistence.snapshot.history_events` — the same subset the History
  tab already shows, not the raw everything-included feed chronicle
  uses). Logged under a new `documentary` category, shown in both the
  main event feed and the History tab. Has a deterministic fallback
  (a plain factual recap) when the LLM is disabled/unreachable, same as
  every other narrative job.

### Notes
- The map-as-primary-interface ask is substantially, not fully,
  addressed: hover/click inspection and the consequences overlay now
  live directly on the map, but the sidebar still carries its full set
  of panels rather than being restructured/thinned — a genuinely
  separate, larger redesign this batch didn't attempt.
- With this batch, every item CLAUDE.md's "Observatory UI direction"
  section listed as "not started" is now started: relationship graph
  (0.35.0), hover inspection, mind-first NPC inspector, surfaced-
  conversation filtering, Town Brain monologue reveal, and documentary
  mode (this release).

## [0.35.0] — Realistic snow/heatwave/frost, live sim-speed controls, relationship graph

### Fixed
- **Snow never actually fell.** `is_snowing` required `temperature_c <=
  0.0`, but `compute_weather`'s smoothing (an EMA-like blend toward the
  previous tick, `smoothing=0.7`) damps the raw per-tick jitter into a
  much narrower realized range than the underlying `uniform(-6, 6)`
  draw suggests — verified a simulated December at the default seed
  never once reached 0C (min observed 0.35C across a multi-year
  sample). `is_snowing` was live code that could never fire. Fixed by
  raising the threshold to `SNOW_TEMPERATURE_THRESHOLD_C = 2.0`
  (`world/weather.py`) — within the range winter baselines actually
  reach, and still correct UK meteorology (most UK snow falls in the
  0-2C band, not exactly at freezing). Verified: ~0.6 snow-tick-days
  per winter month at the default seed, roughly matching real lowland
  UK snow frequency.

### Added
- **Two new natural disasters, UK-historical**: heatwave and frost/cold
  snap, joining the existing flood/wildfire/storm (`world/disasters.py`).
  Both use the same pressure-buildup shape as flood, tuned against
  `compute_weather`'s actual smoothed output range (an early cut of
  heatwave that required simultaneous hot-and-dry conditions to even
  build pressure fired zero times across a simulated year — the same
  class of "threshold the model can never reach" bug as the snow fix
  above; reworked so pressure builds from sustained heat alone, and
  dryness only sharpens the trigger roll once pressure clears
  threshold). Heatwave: wilts/spoils farm plots each tick it's active,
  raises wildfire ignition odds (`HEATWAVE_WILDFIRE_CHANCE_MULTIPLIER`),
  and now counts as harsh weather for agents (`Population.tick`'s new
  `heatwave_active` param folds into the existing `weather_harsh` check
  alongside rain/wind/snow) — echoing the UK's 2018 and 2022 heatwaves,
  both of which came with drought and a spike in wildfires. Frost: a
  sustained hard freeze (colder than the snow band, `FROST_TEMP_
  THRESHOLD = 2.0` sustained `FROST_DURATION_MIN_TICKS`) has a small
  chance of one sharp hit damaging every farm plot at once — a rare,
  multi-year event by design, echoing the UK's 2018 "Beast from the
  East". `World._tick_disasters` now runs before `population.tick` (not
  after) so a heatwave/frost triggered this tick is already felt by
  agents/farms the same tick, not one tick late. New history/event
  categories `disaster_heatwave`, `disaster_frost`.
- **Live simulation-speed controls** — pause, speed up/down, reset to
  default — changeable from the browser UI in real time, no restart
  needed. Deliberately NOT routed through the existing `/intervene/*`
  queued-intervention seam (`WorldBroadcaster.enqueue_intervention`,
  drained once per tick inside `_tick_once`): a paused sim never calls
  `_tick_once`, so a queued "resume" would never be applied and the sim
  would deadlock paused forever. Instead `WorldBroadcaster` gained
  plain pause/speed-multiplier fields (`set_paused`/`get_speed_
  multiplier`/etc., `interface/api.py`) that `SimulationEngine.
  run_forever`'s loop reads directly every iteration — safe because the
  FastAPI handler and the tick loop share one asyncio event loop and
  never run concurrently. New `POST /intervene/sim-speed` endpoint
  (`interface/app.py`) with `action` one of `pause`/`resume`/`speed_up`/
  `speed_down`/`set`/`reset`; speed is bounded to [0.25x, 8x]
  (`MIN_SPEED_MULTIPLIER`/`MAX_SPEED_MULTIPLIER`). Current pacing is
  surfaced in the per-tick diagnostics payload (`sim_pacing`) and in
  the endpoint's own response, so the UI reflects state instantly even
  while paused (when no new tick broadcast is coming). New header
  controls in the browser UI: ⏸/▶ pause toggle, −/+ speed buttons, a
  live "Nx" label, and a reset button.
- **Interactive relationship graph** — the first piece of the
  Observatory UI backlog from 0.34.0's CLAUDE.md direction ("provide an
  interactive relationship graph"). New "🕸 relationships" toggle opens
  a force-directed graph built client-side from data every agent
  already carries (`Agent.relationships`, no backend change needed):
  nodes drift together for fond pairs, apart for sour ones; edge
  color/thickness tracks bond strength (green/red, opacity and width by
  magnitude); hovering a node shows the agent's name. Relationships
  below `REL_MIN_AFFINITY = 0.08` are dropped from the graph entirely
  to keep it readable. Node positions persist across ticks so the
  layout settles rather than jittering on every update; the physics
  loop only runs while the panel is open.

### Notes
- The rest of the Observatory UI backlog (map-as-primary-interface
  rework, hover inspection, mind-first NPC inspector, Town Brain
  monologue reveal, documentary mode) remains not started, per 0.34.0's
  CLAUDE.md note — this batch completed the weather/disaster/speed-
  control asks plus the relationship graph the user asked to start
  with, not the rest of the backlog.

## [0.34.0] — Population recovery, LLM-cadence fix (whispers), Observatory UI direction

### Fixed
- **Population could stagnate/crash toward extinction with no recovery
  path.** Root-caused: reproduction itself works correctly (verified
  via a proper engine-driven run reaching 198 of the 200 population
  cap from 12 starting agents), but a population crashed down to 1-3
  survivors (predation, starvation, disasters, or just old age
  outpacing sparse early births) had no way back — reproduction needs
  a colocated, mature, healthy, mutually-affinity-0.6+ pair, and with
  only a couple of survivors left there may be nobody eligible.
  `Population._maybe_welcome_migrant` mirrors wildlife's
  `_maybe_recolonize`: a rare newcomer, already mature, arrives at the
  settlement when population is critically low (1-3) but not zero.
  Deliberately does *not* revive a fully extinct (0-population)
  settlement — per this session's explicit "settlements expand or
  collapse" design direction, total extinction is a legitimate,
  permanent, readable-from-the-landscape ending, not a bug.
- **Player whispers (`POST /intervene/town-brain`) felt broken.**
  Root cause: `town_brain` (which consumes queued whispers) only fired
  on `season_end` — with the real 365-day calendar a season is ~91
  days, ~8700 ticks, ~2.4 hours of real wall-clock time at default
  pacing before a whisper was ever read. The same "real calendar makes
  season/year cadences much rarer than intended" problem CLAUDE.md
  already documents for terrain evolution, unaddressed here until now.
  Moved town_brain/chronicle/festival to `month_end` and tradition/
  invention to `season_end` (one tier faster each, preserving their
  relative rarity ordering); `INVENTION_CHANCE_PER_YEAR` ->
  `INVENTION_CHANCE_PER_SEASON` (0.5 -> 0.15, so four seasonal rolls
  reproduce the original annual rate) and `FESTIVAL_CHANCE_PER_SEASON`
  -> `FESTIVAL_CHANCE_PER_MONTH` (0.35 -> 0.13, same reasoning).
  Verified: a queued whisper is now consumed within ~1600 ticks
  (~27 real minutes) of the next settlement, down from ~2.4 hours.

### Added
- `docs`/`CLAUDE.md`: a new "Observatory UI direction" design-memory
  section capturing this session's UI/UX brief (map as primary
  interface, hover inspection, consequences over raw stats, curated
  history vs. developer diagnostics kept separate, NPC inspection
  leading with mind over stats, relationship graph, Town Brain
  internal-monologue reveal, documentary mode) — none of the UI work
  itself was attempted this batch (explicitly scoped out: too large
  for one coherent milestone), flagged back to the user to pick a
  starting point rather than guessing.
- `migrant_arrived` life-event category, added to `HISTORY_CATEGORIES`
  and the client's category-icon table.

## [0.33.0] — Natural disasters, rivers & lakes, daylight-driven behavior

### Investigated (no code bug found)
- **"History tab not working"** — read/executed the full path (SQL
  query, `GET /history`, `app.js` wiring, `index.html` IDs) end-to-end;
  it's correct. `HISTORY_CATEGORIES` matches every category string
  actually logged, byte-for-byte. Most likely explanation: the server
  process wasn't restarted after pulling v0.32.0 (uvicorn doesn't
  hot-reload) and/or the browser served a cached pre-upgrade `app.js`
  despite the existing `?v=<version>` cache-bust. If it's still broken
  after a hard restart + hard-reload, that's new information worth a
  fresh diagnostic report.

### Added — natural disasters (`world/disasters.py`)
- **Flood**: sustained heavy rain (precipitation past the existing
  "harsh weather" threshold) builds flood pressure; once past
  threshold, a small per-tick chance submerges a random water-adjacent
  low tile for ~40 ticks, damaging any building/vehicle caught there
  and destroying any farm plot, then recedes back to its original
  biome.
- **Wildfire**: dry summer forest can ignite (rare weekly roll, chance
  nudged upward by ill-fortune `Settlement.temperament` — same lever
  Phase G already uses for invention/predator rolls), then spreads
  tile-to-tile for a few ticks, turning forest to ash (grassland) and
  damaging any building in its path, before burning out.
- **Storm**: extreme wind (well past the routine "harsh weather"
  threshold) has a small per-tick chance of directly damaging every
  standing building and vehicle map-wide — a sharper, rarer hit
  layered on top of routine weather-decay.
- All three log real life-events (`disaster_flood`, `disaster_wildfire`,
  `disaster_storm`), added to `HISTORY_CATEGORIES` and the client's
  terrain-refresh/category-icon tables, and physically alter buildings/
  vehicles/farms/terrain — not narration bolted onto nothing.

### Added — rivers and lakes (`world/hydrology.py`)
- **Rivers**: carved once at world creation by steepest-descent from
  high-elevation sources (mountain/hills/snowcap) down to existing
  water or the map edge — a new `Biome.RIVER`, visible on the map and
  in `biome_counts`. Persist automatically through terrain's existing
  (de)serialization; no extra state needed. Rivers "evolve" via the
  flood mechanic above (sustained rain temporarily expands water onto
  riverbank land) rather than a separate river-specific tick.
- **Lakes**: inland water bodies (flood-filled components that never
  touch the map border, as opposed to the ocean, which does) each get
  their own slowly-changing `level` — a bounded random walk nudged
  monthly, biased toward the map-wide climate-drying trend. Crossing a
  threshold grows or shrinks the shoreline by one tile
  (`lake_rose`/`lake_receded`), so a lake visibly changes size over
  years, same "evolves over time" contract as the existing climate
  drift. A pre-hydrology-pass snapshot gets rivers carved and lakes
  identified once on load (same backfill pattern as every other
  subsystem migration).
- New "Geography"/"Disasters" stat tiles in the UI.

### Added — daylight now affects agent behavior, not just lighting
- `world/daylight.py` mirrors the client's `UK_DAYLIGHT_HOURS` table
  and `nightFactor` ramp server-side. An AWAKE agent now burns energy
  up to 30% faster the deeper into the night it is (same order of
  magnitude as the existing harsh-weather multiplier — staying up all
  night costs about as much as working through a storm), the
  involuntary-rest energy threshold rises at night (agents settle in
  for the night sooner rather than only collapsing from exhaustion),
  and RESTING energy recovery gets a small night bonus (sleep is more
  restful than a daytime nap). Previously `night_factor`/daylight hours
  only drove the map's visual darkening tint.

## [0.32.0] — Map/UI/ecology follow-up: bug fixes + history tab + UK daylight + diagnostics

### Fixed
- **Wildlife could go permanently extinct.** `WildlifeGrid` had no
  repopulation mechanic after world creation — a species that ever hit
  0 herds/packs (predators starving out, especially likely now that
  grazers flee) was gone forever. Added `_maybe_recolonize`: a rare,
  per-tick roll that can spawn a new grazer herd or (only if grazers
  already exist to sustain it) a predator pack, migrating in from
  beyond the map's edge. Directly root-caused from a live report
  showing "0 predators (0 packs)."
- **Roads were nearly invisible.** The old `wear * 0.6` alpha scaling
  made anything below "established" (wear >= 0.5) read as ~6% opacity
  — practically invisible. Roads now get a visible tint from the first
  bit of wear.
- **Wild resource nodes (bushes/mines) weren't sent to the client at
  all** — only an aggregate count reached the UI, never actual
  positions. Now broadcast every tick and rendered as small map
  markers, dimming as they deplete.
- Buildings render larger (bleeding 1px past their tile) with a
  brighter stroke for legibility against terrain.

### Added
- `GET /history` + a History tab: a curated, summarized town history
  (founding, naming, era advances, chronicle/tradition/invention/
  festival entries, beliefs formed/revised, omens, wildlife
  recolonization) filtered out of the everything-included live event
  feed.
- Real UK daylight hours: the map's day/night lighting now varies by
  month (~8h daylight in December, ~16.5h in June) instead of a fixed
  6am-6pm ramp, via an approximate London-latitude sunrise/sunset
  table. A new "Daylight" stat tile shows the current month's sunrise/
  sunset.
- Season-based building/vehicle wear: `SEASON_DECAY_MULTIPLIER`
  (winter 1.4x, autumn 1.15x, spring 1.0x, summer 0.85x) applied on top
  of the existing weather-harshness multiplier — freeze-thaw and damp
  genuinely wear structures faster than a dry summer, independent of
  any single tick's weather.
- Beliefs now feed festival and invention prompts too (previously only
  town_brain, chronicle, and matched-agent dialogue) — broadening how
  the village's own accumulated theories shape what the LLM does, per
  "beliefs should affect the whole village."
- Extensive new diagnostics: `full_diagnostics()` now includes
  `last_llm_calls` (the most recent prompt + result + fallback flag for
  every named LLM job — town_brain, beliefs, omen, naming, chronicle,
  tradition, invention, festival, dialogue), `pending_player_whispers`,
  and `temperament`. The whisper form also shows queued-but-not-yet-
  heard whispers directly in the UI, not just in diagnostics.

See `docs/DECISIONS.md`, "map/UI/ecology follow-up," for the full
per-item root-cause writeup, including two items deliberately scoped
out of this batch (rivers as a distinct terrain feature; daylight
hours driving anything beyond the visual lighting tint).

## [0.31.0] — Live-diagnostics follow-up: vehicle eras, dialogue quality, LLM-authored naming

Driven directly by a real user diagnostic report running `qwen3.5:2b`
(confirmed working, <4GB RAM) — see docs/DECISIONS.md, "live-diagnostics
follow-up (vehicles/dialogue/naming)."

### Added
- `VehicleKind.AUTOMOBILE`: an era-gated (`modern`+) upgrade over
  MOUNT, faster (2.2x vs 1.6x) and costlier. Answers "why carts in an
  industrial era": carts/mounts stay realistic at `industrial`/
  `electrical` (horse-drawn transport genuinely coexisted with early
  industry), and transport now genuinely modernizes alongside
  buildings once the era does, the same way FACTORY already did for
  buildings.
- `llm/naming.py`: settlement naming is now LLM-authored, informed by
  the founding scenario and terrain, rather than a bare random
  prefix+suffix draw. The existing deterministic name generator still
  provides an instant placeholder the tick a settlement is born (every
  other system gates on `settlement.name` being set) — the LLM's name
  replaces it in the background once the one-time job resolves.

### Fixed
- `llm/dialogue.py`: the system prompt now includes few-shot examples
  (small/weak models benefit disproportionately from this) and
  explicitly forbids meta-commentary/instruction leakage. `parse_dialogue`
  gained a sanity filter (`_is_sane_line`) rejecting lines that leak
  instructions, run wildly over length, exactly duplicate the other
  speaker's line, or contain stray JSON braces — degrading to the
  deterministic fallback pool instead of surfacing garbled small-model
  output. Root-caused from the user's direct report that dialogue "makes
  no sense."
- `Config.llm_timeout_seconds` bumped 30 -> 45: the user's live
  diagnostics showed p50 17.4s / p95 19.7s / max 29.7s against a 30s
  timeout on `qwen3.5:2b` — a razor-thin margin despite the model
  itself working correctly (0% observed fallback rate). Not a sign the
  model is failing; a smaller model isn't necessarily faster in
  wall-clock terms on constrained CPU hardware.

## [0.30.0] — Add: Phase G v1 (temperament + omens), per-person beliefs

### Added
- **Phase G v1** (started early, in parallel, per explicit user
  instruction): `Settlement.temperament` (-1..1), a real deterministic
  bounded random walk nudged monthly by the recent balance of good/ill
  fortune (`buildings.tick_temperament`), applying small, deliberately
  subtle nudges to invention chance and predator-attack lethality.
  `llm/omens.py`: a rare, LLM-authored (or fallback-pool) ambiguous
  flavor event, chance scaled by |temperament|, worded to always have a
  mundane explanation and never confirm anything supernatural. Nothing
  in the UI labels this as "mood" or "supernatural" — it's plumbed
  through like any other internal stat.
- **Per-person beliefs**: `beliefs.resolve_subject_agent_id` matches a
  belief's free-text subject against current agent names and tags
  `subject_agent_id` on the entry; matched beliefs are now folded into
  that person's own dialogue prompts (`llm/dialogue.py`'s new
  `beliefs_about` param), so a belief about a specific villager
  actually shapes what they and their conversation partner say.

See `docs/DECISIONS.md`, "Phase G / per-person beliefs follow-up."

## [0.29.0] — Add: world beliefs (continuous cognition); model set to qwen3.5:2b; drop legacy calendar compat

### Added
- `llm/beliefs.py` + `Settlement.beliefs`: the village's own persistent,
  evolving theory of itself. Once a month, for a named settlement, the
  LLM (or its deterministic fallback) forms a new belief about a
  person/family/tradition/pattern/outside-influence, or revises one it
  already holds, given recent history — and those beliefs are fed back
  into the next town-brain and chronicle prompts as accumulated
  context, so the LLM's own past interpretations shape its future
  ones. Capped at 12 entries (lowest-confidence evicted). New "The
  village's own theories" UI panel, `inspect_world` section, and
  `belief_formed`/`belief_revised` event categories.

### Changed
- Default LLM model set to `qwen3.5:2b` per explicit user instruction
  (confirmed available on their machine, correcting this project's
  earlier assumption that no "Qwen3.5" existed).
- Legacy pre-real-calendar snapshot compatibility deliberately dropped
  per explicit user instruction — `World.from_dict` no longer
  reconstructs a synthetic calendar from an old `days_per_season`/
  `seasons_per_year`-only config block; every snapshot is expected to
  carry `days_per_month`/`month_names`/`month_to_season`.

See `docs/DECISIONS.md`, "World-model/beliefs follow-up."

## [0.28.0] — Add: real 365-day UK calendar, eras, LLM-genesis seed, model swap

### Added
- Real 365-day, 12-month calendar (`time_system.py`) replacing the old
  fixed 20-day, 4-season year — `season` is now derived from the month
  via UK meteorological convention, so everything already keyed off it
  (weather baselines, farm growth, chronicle/tradition/invention/
  festival/town-brain cadence) kept working unchanged. Existing worlds
  keep their original calendar shape (creation-only, reconstructed
  losslessly from legacy snapshots — see `World.from_dict`).
- `world/weather.py` baselines rewritten to a UK-style temperate
  maritime climate at monthly granularity (mild wet winters, cool damp
  summers, rain fairly even year-round).
- Terrain-evolution cadence (nature reclaiming abandoned land, climate/
  biome drift) decoupled from season/year boundaries onto fixed weekly/
  monthly ticks instead, plus a slightly higher climate-drift sample
  rate — the real calendar being ~4.5x longer than the old one would
  otherwise have made map evolution proportionally rarer in wall-clock
  terms, which is what "the map doesn't seem to be evolving" was
  actually pointing at (the broadcast/redraw wiring itself was already
  correct).
- Eras: a settlement starts `industrial` and advances (electrical ->
  modern -> digital) purely as a function of accumulated `tech_level`
  (`buildings.era_for_tech_level`) — each era is a mechanically real
  unlock, not a label: the new FACTORY building kind (double a
  workshop's currency income) only enters the foundable pool past
  `industrial`.
- `llm/world_genesis.py`: a one-time "genesis" LLM call, made before a
  brand-new world's terrain/weather are generated when `--seed` is
  omitted — the LLM writes a short founding-scenario sentence, and its
  hash becomes the world's seed, so "initial terrain and weather chosen
  by an LLM" is literal. Falls back to a wall-clock-mixed seed from a
  rotating scenario pool if the LLM is disabled/unreachable. An
  explicit `--seed` always skips genesis; a resumed world never re-runs
  it. The scenario text is shown once in the event log and persisted on
  `Settlement.founding_scenario`.
- Default LLM model moved to `qwen3:4b` (Qwen3, not "Qwen3.5" — that
  doesn't exist — at the 4B tier, ~2.6GB Q4) from `qwen2.5:7b-instruct`
  (~4.5GB): a newer generation, smaller, generally matching or beating
  the old default's quality on community benchmarks. `qwen3:1.7b`
  (~1.1GB) is the documented lighter fallback. `OllamaClient` now sends
  `"think": false` and defensively strips any `<think>` block, since
  Qwen3's hybrid thinking mode would otherwise risk breaking the
  strict-JSON parsing every call here relies on.

### Fixed
- `server.py`'s `--llm-model`/`--llm-timeout` CLI flag defaults had
  drifted out of sync with `Config`'s own defaults (still hardcoded to
  the pre-0.27.0 `qwen2.5:3b`/20s) — running the CLI without explicitly
  passing those flags silently used stale values. Both flags now read
  their defaults from `Config` directly so they can't drift again.

See `docs/DECISIONS.md`, "Real-calendar/genesis-seed follow-up."

## [0.27.0] — Add: economy buildings, town brain, animal/road weather, infrastructure telemetry

### Added
- Workshop/school/hospital/university buildings with real mechanical
  effects (currency income, education -> invention chance, faster
  hospital rest recovery + reduced predator lethality, school-to-
  university upgrade path).
- `llm/town_brain.py`: a seasonal LLM decision sets the settlement's
  current civic priority, which measurably steers which building kind
  gets founded next — the concrete "LLM as the town's brain" mechanic.
- `POST /intervene/town-brain`: a subtle player-influence channel — a
  short text whisper folded into the next town-brain prompt.
- Grazer herds now flee adjacent predators instead of wandering
  blindly; predator hunts/pack extinctions are now logged events.
- Roads get genuinely muddy/snowy/icy depending on weather, changing
  their move-speed bonus (icy can even be a penalty).
- `Settlement.infrastructure_report()` + a new sidebar panel: every
  building/vehicle's condition in plain language (excellent/good/worn/
  critical/broken/ruined), worst-first.
- Default LLM model bumped to `qwen2.5:7b-instruct` for better NPC
  dialogue/town-brain quality (timeout bumped 20s -> 30s to match).

### Fixed
- Dialogue, chronicle, tradition, invention, festival, intervention,
  and town-brain events never appeared in the live browser event feed
  (only on page load, via the one-shot `/events` fetch) — they resolve
  outside `World.tick()` and were never folded into the broadcast
  payload. Fixed with a new `SimulationEngine._log` helper.

See `docs/DECISIONS.md`, "LLM-as-brain batch: economy buildings, town
brain, animal/road weather, infrastructure telemetry."

## [0.26.0] — Add: interventions, family memory, smooth/lit rendering

### Added
- `/intervene/agent-goal`, `/intervene/settlement`, `/intervene/weather`
  POST endpoints — queued and applied by the engine at the top of its
  next tick, logged as `intervention` events.
- Family memory: a newborn remembers both parents from birth, parents
  remember the birth; losing a parent/child logs a memory and pays
  grief regardless of numeric relationship value. NPC dialogue prompts
  now recognize a parent/child pair as family, not just by affinity.
- Smooth inter-tick agent movement interpolation, and a day/night +
  weather lighting tint on the browser map.

See `docs/DECISIONS.md`, "Interventions, family memory, and smooth/lit
rendering."

## [0.25.0] — Add: terrain evolution (local activity + climate drift)

### Added
- `world/terrain_evolution.py`: sustained GATHER pressure thins forest
  to grassland (deforestation); an abandoned grassland tile bordered by
  forest can revert to forest once a season (reclamation); a slow,
  bounded yearly `warming`/`drying` random walk gradually shifts a
  small sample of tiles' biomes map-wide (climate drift).
- `terrain.classify_with_bias`, `BIOME_ORDER`: the same elevation-based
  biome classifier, now bias-parameterizable and steppable one biome at
  a time.
- Browser map and `GET /terrain` now refresh on an actual terrain
  change instead of assuming terrain is static after boot.
- New "Climate trend" stat tile; event icons for
  `terrain_thinned`/`terrain_reclaimed`/`climate_drift`.
- `inspect_world` prints the current climate bias.

See `docs/DECISIONS.md`, "Terrain evolution: local activity + climate/
biome drift."

## [0.24.1] — Fix: dev console diagnostics copy-to-clipboard

### Fixed
- "Full diagnostic report" copy failed silently on any non-https,
  non-localhost origin (`navigator.clipboard` requires a secure
  context — the API is simply absent over plain `http://<lan-ip>`, not
  just denied). Added a `document.execCommand("copy")` legacy fallback
  and a status message that explains the requirement instead of always
  saying the same generic thing.

See `docs/DECISIONS.md`, "dev-console-copy-fallback."

## [0.24.0] — Add: vehicles (hauling carts + personal mounts)

### Added
- `settlement/vehicles.py`: carts and mounts, built from settlement
  materials the same way buildings are (colocated founding, presence-
  driven construction/repair, weather decay + break-down).
- Carts: settlement-wide, each ready cart adds 25% to gathered-material
  haul yield (stacks up to 3).
- Mounts: an awake agent claims a ready unclaimed mount and moves ~1.6x
  faster (stacks with roads) until it breaks down or they die.
- Browser UI: "Vehicles" stat tile, map markers (cart/mount), event
  icons for `vehicle_started`/`vehicle_completed`/`vehicle_broken`.
- `inspect_world` prints vehicle counts under the settlement summary.

See `docs/DECISIONS.md`, "Vehicles: hauling carts and personal-travel
mounts."

## [0.23.0] — Add: weather particle overlay; policy: determinism dropped

### Added
- Rain/snow particle effects on the browser map (`weather-canvas`,
  independent animation loop) — driven by a new `weather_detail` field
  in `World.summary()` (raw precipitation/wind/is_snowing/temperature).

### Changed
- **CLAUDE.md**: determinism/reproducibility is no longer a project
  requirement (explicit user instruction) — existing namespaced-RNG uses
  stay, but new work isn't constrained by seed-replay reproducibility.

See `docs/DECISIONS.md`, "Determinism dropped as a project requirement;
weather particle overlay."

## [0.22.0] — Fix + add: diagnostics, browser-default, resource variety, building cost

### Fixed
- NPC dialogue fallback repeated the same 3 lines forever when the LLM
  was unreachable — now cycles through small per-band pools.
- "A tooled field was planted..." → readable wording.
- `Population.dialogue_cooldowns` grew unbounded over a long run — now
  pruned (dead agents, stale entries) each tick.

### Added
- `GET /diagnostics` + dev console "Full diagnostic report" button:
  LLM call/latency/error breakdown, tick-duration percentiles, peak
  memory, DB size, all-time event-category histogram — built for
  pasting into a bug report after an unattended overnight run.
- Resource variety: `ResourceNode.kind` (FOOD/ORE) — hills-only ore
  veins regenerate 12x slower than food nodes, season-scaled like food.
  GATHER-goal materials collection on hills now draws from ore
  specifically (forest wood stays uncapped/renewable).
- Buildings now cost real materials to found (`HUT_MATERIALS_COST`/
  `GRANARY_MATERIALS_COST`), not just a speed bonus — a settlement with
  an empty stockpile can no longer spontaneously build.

### Changed
- Browser interface (`api_enabled`) is now **on by default**;
  `--api-disabled` to opt out. Missing `fastapi`/`uvicorn` degrades to a
  warning, not a crash.

See `docs/DECISIONS.md`, "Diagnostics, browser-default, resource
variety, real building cost."

## [0.21.0] — Add: predator danger, relationship memory, festivals, scarcity

### Added
- Agent-vs-predator danger: colocated agents can be attacked (injury,
  rarely lethal) by live predator packs; agents now prefer avoiding
  predator-occupied tiles when moving, falling back only if it's the
  only path.
- Relationship memory: `Agent.memories` (capped short log) populated by
  bond/rivalry formation, rumors, and grief on a bonded partner's death
  (with a real energy cost); fed back into the agent's own cognition
  prompt.
- Festivals: a new, wellbeing-gated (not prosperity-gated), seasonal-
  cadence collective event (`hearthmind/llm/festival.py`) with a direct
  mechanical effect — every currently-colocated pair of awake agents
  gets a relationship boost when one is held.
- Seasonal/weather scarcity: winter cuts farm growth and wild-resource
  regeneration; harsh weather (heavy rain/snow/high wind) increases an
  awake agent's hunger/energy drain. Makes genuine settlement decline
  possible during a bad season/weather streak, not just a plateau at the
  population cap.

### Changed
- `Population.tick`/`_update_needs` now take `weather`;
  `FarmGrid.tick`/`ResourceGrid.tick` now take `season`.
- `inspect_world` prints predator deaths, relationship stats, tech
  level, inventions, festivals, wildlife, and roads.

See `docs/DECISIONS.md`, "Batch: predator danger, relationship memory,
festivals, seasonal/weather scarcity."

## [0.20.1] — Fix: dev console not opening (stale browser cache)

### Fixed
- `/` now stamps `app.js`/`style.css` URLs with `?v=<version>` so a
  browser cache from before a UI change can't silently keep serving a
  stale build. Root cause of the reported "dev console doesn't open" —
  likely an old cached `app.js` with no dev-console handler.

## [0.20.0] — Improve: browser UI — readable events, clearer economy, dev console

### Added
- Developer console: `⚙ dev` header toggle shows raw per-tick
  diagnostics (tick duration, background/in-flight task counts,
  connected clients, LLM config) as JSON.
- Event log: per-category icons and color/emphasis (births, deaths,
  rumors, inventions, etc.); noisy `day_end` events suppressed from the
  rendered log (still queryable via `/events`).
- Wildlife (grazer/predator markers) and road wear now drawn on the
  canvas map, not just in stats.
- New stat tiles: Relationships (bonds/rivalries/avg affinity), Tech
  level, Wildlife, Roads, NPC dialogue counts. Materials/currency/
  granary/tech tiles gained `title` tooltips and capacity fractions
  instead of bare unlabeled numbers.
- New Inventions sidebar panel (mirrors Traditions).
- `Population.summary()`: `avg_affinity`/`close_bonds`/`rivalries`.
  `Settlement.summary()`: `materials_capacity`/`currency_capacity`/
  `granary_capacity`. `World`: `dialogue_total`/`rumor_total` counters.
  `WorldBroadcaster.client_count()`. Engine: `diagnostics` block in the
  per-tick broadcast payload.

See `docs/DECISIONS.md`, "UI pass."

## [0.19.0] — Add: Phase C slice 5 — infrastructure, foot-traffic roads (C5)

### Added
- `hearthmind/world/roads.py`: `RoadNetwork` tracks per-tile wear from
  sustained agent foot traffic (building/farm tiles excluded); an
  established road (wear >= 0.5) gives agents a 1.4x random-walk move
  bonus. Unused paths decay back to untouched terrain.
- `World.roads`, migration-backfilled for pre-C5 saves; included in the
  browser broadcast payload (not yet rendered by the static client).

This completes every system in the original feature list (terrain,
weather, seasons, ecology/wildlife, humans, relationships, economy,
agriculture, construction, infrastructure, building decay, culture,
history) — see `docs/ROADMAP.md`'s feature checklist.

See `docs/DECISIONS.md`, C5.

## [0.18.0] — Add: Phase A slice 4 — wildlife & ecology (A4)

### Added
- `hearthmind/world/wildlife.py`: mobile `AnimalHerd`s — `GRAZER` herds
  (grassland/forest, reproduce when uncrowded) and `PREDATOR` packs
  (forest/hills, hunt colocated grazers, starve without a kill). A real
  second trophic level with its own dynamics independent of agents.
- Hungry agents can hunt a colocated grazer herd for richer hunger relief
  than wild foraging — integrated into the existing forage priority
  chain (farm > granary > hunt > wild resource > emergency rations), no
  new `AgentGoal`.
- `World.wildlife`, migration-backfilled for pre-A4 saves.

See `docs/DECISIONS.md`, A4.

## [0.17.0] — Add: Phase E slice 3 — inventions, tech-tier unlocks (E3)

### Added
- `hearthmind/llm/invention.py`: rare, prosperity-gated tech-tier
  unlocks for a named settlement (LLM-authored with deterministic
  fallback) — `Settlement.tech_level`/`inventions`.
- Gated on surplus (currency or materials threshold) and an independent
  `INVENTION_CHANCE_PER_YEAR = 0.5` roll — deliberately rarer than
  traditions so it reads as a real event.
- `Population._tech_factor`: each invention boosts construction/repair
  work and cultivated-food yield (farm harvest, granary stock/withdraw)
  by `TECH_BONUS_PER_LEVEL` (0.15/level); wild foraging is untouched.

See `docs/DECISIONS.md`, E3.

## [0.16.0] — Add: Phase E slice 2 — NPC dialogue, rivalry, LLM on by default (E2)

### Added
- `hearthmind/llm/dialogue.py`: colocated agents periodically exchange an
  LLM-authored short dialogue (with deterministic fallback), scheduled
  fire-and-forget like cognition/chronicle/culture.
- `Population.due_for_dialogue`/`apply_dialogue`: deterministic,
  cooldown-gated, capped-per-tick pair selection; dialogue sentiment
  nudges relationship affinity.
- Dialogue lines and any seeded rumor are logged as `dialogue`/`rumor`
  events — automatically visible to the chronicle and culture prompts
  (both already read recent events), no extra wiring needed.

### Changed
- `Agent.relationships` now range -1..1 (was 0..1): a `tense` dialogue
  can push a pair into rivalry, not just toward friendship. Decay now
  pulls toward 0 from either sign.
- `Config.llm_enabled` defaults to `True` (was `False`); `server.py`'s
  flag inverted to `--llm-disabled`. Every LLM call still has a
  deterministic fallback if Ollama is unreachable.
- `llm_max_concurrent` default raised 2 -> 4.

See `docs/DECISIONS.md`, E2.

## [0.15.0] — Add: Phase F slice 2 — FastAPI backend + browser client (F2)

### Added
- Actual browser window into the simulation:
  `hearthmind/interface/static/` (plain HTML/CSS/JS, no build step) — a
  live canvas map (terrain + agents + buildings + farms), a stat-tile
  dashboard, traditions, and a scrolling event log.
- Backend switched from raw `websockets` to **FastAPI + uvicorn**:
  `GET /` (the page), `GET /state`, `GET /terrain`, `GET /events`, and
  `WS /ws` (live per-tick push).
- `requirements.txt` added, tracking the `api` extra
  (`fastapi`, `uvicorn[standard]`) alongside `pyproject.toml`.
- External libraries are now allowed project-wide (previously a scoped
  exception for `websockets` only) — tracked in `requirements.txt` going
  forward.

## [0.14.0] — Add: Phase F slice 1 — read-only WebSocket API (F1)

### Added
- `--api-enabled` (off by default), `--api-host`, `--api-port`:
  broadcast-only WebSocket channel pushing the world summary + this
  tick's life events after every tick. No intervention endpoints yet
  (deliberately last, per the roadmap).
- `websockets` added as an **optional** dependency (`pip install
  hearthmind[api]`) — the base install is still zero-dependency unless
  `--api-enabled` is actually used. See `docs/DECISIONS.md`, F1 for the
  reasoning (asked the user directly before bending the no-dependency
  rule).

## [0.13.0] — Add: Phase E slice 1 — settlement naming, traditions, culture-aware prompts (E1)

### Added
- Settlements are named (`settlement/naming.py`) the first tick a
  building stands, deterministically.
- Named settlements invent one new tradition per year
  (`hearthmind/llm/culture.py`), LLM-authored or deterministic fallback,
  persisted on `Settlement.traditions`.
- Settlement name + latest tradition now appear in per-agent cognition
  prompts and the seasonal chronicle prompt, closing the "chronicle isn't
  read back into prompts" gap noted since B3. `inspect_world` shows the
  settlement name in its header and lists established traditions.

## [0.12.0] — Add: farm-yield materials boost (D9); settlement currency (D10)

### Added
- Tooled farm plots: planting spends `FARM_TOOL_MATERIALS_COST` (2.0
  materials) for `FARM_TOOL_YIELD_MULTIPLIER` (1.5x) yield when materials
  are available. `FarmPlot` now carries its own `max_yield`.
- `Settlement.currency`: generated from food/materials surplus that would
  otherwise be wasted at capacity; spent on emergency rations at a
  standing granary as a last resort, once nothing free is available. No
  per-agent inventory/trade system — see `docs/DECISIONS.md`, D10 for why
  that's scoped out. `inspect_world` shows the currency balance.

## [0.11.0] — Add: production chains (D8)

### Added
- New `AgentGoal.GATHER`: collects wood/stone from forest/hills into a
  settlement-wide `materials` stockpile (`MATERIALS_CAPACITY` 30.0).
  Construction now consumes materials for a 2x speed boost
  (`CONSTRUCTION_MATERIALS_MULTIPLIER`) when available. LLM prompt and
  deterministic fallback both updated so GATHER is reachable with or
  without a live LLM. `inspect_world` shows the materials stockpile.

## [0.10.0] — Add: Granaries (D7)

### Added
- Dedicated `BuildingKind.GRANARY` (30% of new construction, vs. HUT).
  Well-fed agents present passively stock it (`GRANARY_CAPACITY` 15.0);
  hungry agents withdraw from it, priority farm > granary > wild forage.
  FORAGE/critical-hunger movement now also targets granaries (uncapped
  search, like farms/D6). `inspect_world` shows granary count + stored
  food.

## [0.9.0] — Fix: FORAGE never targeted farms (D6); qualitative wind

### Fixed
- 16 starvation deaths at tick 660 despite 27 harvest-ready farms — FORAGE
  movement only ever targeted wild resource nodes, never farms. Added
  `_nearest_ready_farm` (uncapped, like D4's SOCIALIZE), preferred over
  wild nodes. Verified: 0 starvation deaths over 6000 ticks, same config
  that previously produced 16 by tick 660.

### Changed
- `WeatherState.describe()` reports wind as calm/breezy/windy/gale
  (`wind_label()`) instead of a raw float.

## [0.8.0] — Fix: critical-hunger movement override (D5) + diagnostics

### Fixed
- **A critically hungry but *awake* agent could keep walking away from
  food.** `AgentGoal` is only reevaluated once per sim-day; an agent
  assigned SOCIALIZE or WANDER while well-fed had nothing making it
  deliberately seek food again before its next reevaluation, by which
  point hunger could have risen by ~0.96 (a full day at `HUNGER_RATE`).
  D3 only fixed the equivalent problem for a *resting* agent (emergency
  wake); this closes the same gap for movement dispatch generally.
  `Population.tick` now passes `critically_hungry` into
  `_dispatch_movement`, which forces FORAGE-seeking as an effective goal
  for movement purposes only — the agent's actual assigned `goal`/
  `goal_reason` (and hence what the UI/LLM sees) is unchanged. Found via
  a real soak run against live Ollama on the user's own machine (12 -> 5
  inhabitants, all dying before reaching maturity). See
  `docs/DECISIONS.md`, D5.

### Changed
- Default `--llm-timeout` raised from 10s to 20s — CPU inference sharing
  an 8GB+zram machine with the simulation itself is realistically slower
  under contention than a quiet benchmark; the same run that surfaced the
  bug above also logged one LLM timeout that correctly fell back, but
  with no headroom to spare.

### Added
- **Persisted diagnostics, surfaced by `inspect_world`:**
  - `World.llm_calls_total` / `llm_fallback_total` — cumulative LLM call
    count and how many fell back to deterministic behavior, shown as a
    fallback rate.
  - `Population.deaths_starvation` / `deaths_old_age` — cumulative death
    counts by cause, so a population crash between two snapshots is
    visible as a number instead of something you infer from "there used
    to be more agents."
  - `inspect_world --agents` now also shows each agent's `starving_ticks`
    and a maturity countdown, distinguishing "nothing has happened yet
    because nobody's mature" from an actual bug.

## [0.7.0] — Fix: social dispersion (D4) — the town finally forms

### Fixed
- **Root-caused and fixed the D2 finding** (farming let agents survive
  indefinitely alone, with reproduction/construction never occurring even
  with multiple mature, well-fed agents alive simultaneously). Two
  concrete bugs, not a deep balance problem:
  - `SOCIALIZE`'s target search shared `FORAGE`'s local radius
    (`GOAL_SEARCH_RADIUS`, 6 tiles) — far too small for a 64x64+ map.
    Once ordinary wander drift put two agents more than 6 tiles apart
    (which happens within a few hundred ticks), `SOCIALIZE` could never
    find them again — a one-way ratchet toward permanent isolation.
    Removed the distance cap for agent-seeking entirely (renamed the
    constant to `FORAGE_SEARCH_RADIUS`, now FORAGE-only).
  - `fallback_goal` (used whenever Ollama is disabled/unreachable) never
    returned `SOCIALIZE` at all — only forage/rest/wander. Every soak
    test in this project's history ran without Ollama, so this alone was
    enough to explain the total absence of clustering. Content agents now
    split deterministically by `agent_id` parity between SOCIALIZE and
    WANDER instead of always wandering.

### Verified
- Re-ran the *exact* 30-agent/48x48 configuration (seed 7) that produced
  D2's "three lonely survivors, zero reproduction, zero construction"
  result. With both fixes: **30+ births**, a building lifecycle
  (construction → completion → weathering → ruin) repeating across at
  least 8 distinct structures, and the first **old-age death** observed
  in any soak test in this project — sustained for 25,657 ticks (~3
  sim-years) with population fluctuating between ~10 and ~30 rather than
  trending to zero. This is the first time every subsystem built so far
  (terrain, weather, needs, foraging, farming, relationships,
  reproduction, settlement, aging) has been observed working together as
  a genuinely self-sustaining town, not just individually correct.
- 3 new/updated tests (`test_cognition.py`, `test_agents.py`) covering
  the parity split and the unbounded SOCIALIZE search. Full suite: 166
  tests, all passing.

See `docs/DECISIONS.md`, D4, for the full writeup.

## [0.6.1] — Fix: starvation trap found via live Ollama verification

### Fixed
- **Real bug, found on real hardware.** A maintainer's first live run
  against an actual Ollama instance (not the fake test server) showed
  population collapsing while `--agents` output revealed the LLM was
  correctly diagnosing hunger emergencies (`goal=forage`, reasons like
  "Need to find food before hunger reaches critical level") — but
  starving agents never acted on it, because `Population._maybe_forage`
  only ran while `AgentState.AWAKE`, and nothing could interrupt rest for
  a hunger emergency. An agent could wake, fail to reach food before
  energy drained back down, and re-sleep indefinitely while hunger
  climbed regardless of sleep state.
- Fixed with two coordinated changes gated on a new
  `CRITICAL_HUNGER_THRESHOLD` (0.9): agents can now forage/harvest food
  at their current tile while resting (not just awake), and a resting
  agent whose hunger crosses the critical threshold wakes immediately,
  with `goal=REST` no longer able to re-sleep them while still
  critically hungry.
- See `docs/DECISIONS.md`, D3, for the full incident writeup — this is
  the first bug this project found through actual multi-thousand-tick
  play with a real LLM rather than through unit tests, and a concrete
  example of why "tested against a fake server" and "verified" are
  different claims.

### Verified
- LLM integration is now confirmed genuinely working against real Ollama
  (previously only tested against a fake server standing in for it) —
  `goal_reason` text observed was contextual and weather-aware, not
  fallback boilerplate.
- 5 new regression tests (`tests/test_agents.py`,
  `TestStarvationTrapFix`) replicate the exact trap shape. Full suite:
  164 tests, all passing.

## [0.6.0] — Phase D (slice 1): Agriculture

### Added
- `hearthmind/economy/farms.py`: `FarmPlot`/`FarmGrid` — any single
  awake agent may plant a farm plot on an unclaimed grassland tile (no
  maturity/health/colocation requirement, unlike founding a building).
  Plots grow automatically over ~250 ticks with no tending needed, then
  yield substantially more food per harvest than wild foraging.
  `Population._maybe_forage` prefers a ready farm over a wild resource
  node whenever one's present at the agent's tile.
- Farm planting is logged as a `farm_planted` event.
- `World.summary()` / `inspect_world.py` now report farm counts
  (growing / ready to harvest).
- Generalized migration mechanism extended to the new `farms` subsystem.

### Verified (not just built)
Re-ran the exact soak configurations that produced total population
extinction in Phase C (see `docs/DECISIONS.md`, C5), now with farming:
- 6-agent/32x32 run (seed 42): 5 of 6 agents still died on essentially
  the same schedule as before farming existed, but the 6th survived to
  age 4082 — past `MATURITY_TICKS` (4000) — versus dying early in the
  pre-farming run. A direct, measured ~3x lifespan improvement.
- 30-agent/48x48 run (seed 7): **3 agents survived to age 27,035**
  (nearly 7x `MATURITY_TICKS`), run still going when testing ended —
  versus complete extinction in the equivalent pre-farming run.
- Farming is a verified fix for starvation-before-maturity, not a
  hoped-for one. See `docs/DECISIONS.md`, D2, for the full write-up.

### Known gaps / new finding (tracked for later phases)
- **No reproduction or construction occurred in either verification
  run**, including the 27,035-tick one with three simultaneously alive,
  well-fed, mature agents. They ended up scattered across the map with
  decayed relationships — farming lets an agent survive indefinitely
  *alone*, so nothing currently creates pressure to cluster. This is a
  distinct bottleneck from the one farming fixed; see `docs/DECISIONS.md`,
  D2, for a candidate next slice (bias settling/farming toward proximity
  to other agents).
- No storage/granaries (food is consumed immediately, not stockpiled),
  no production chains, no trade/currency — later Phase D territory.

## [0.5.0] — Phase C (slice 1): Settlements & construction

### Added
- `hearthmind/settlement/buildings.py`: `Building` (under_construction /
  standing / ruined lifecycle) and `Settlement` (the collection of
  buildings in the world, parallel to `Population`/`ResourceGrid`).
- Colocated, mature, healthy agent pairs may found a building at their
  shared tile (deterministic per-tick chance, mirroring A3's reproduction
  mechanic — not yet an LLM/goal decision, see `docs/DECISIONS.md` C1).
- Any awake agent physically present at a building's tile contributes
  work each tick: advancing construction toward completion, or repairing
  a standing building below `REPAIR_THRESHOLD` — automatic based on
  presence, the same way foraging already works, not a separate explicit
  action (see C2).
- Standing buildings decay every tick (faster during harsh weather —
  precipitation, wind, snow) into ruins; ruins persist, inspectable, for
  a long while before nature finishes reclaiming them and they're removed
  from the world (see C3).
- Worlds start with an empty settlement — nothing is pre-placed; whether
  a world becomes settled at all emerges entirely from population
  behavior (see C4).
- Construction/repair/ruin/reclamation are logged as events
  (`construction_started`, `building_completed`, `building_ruined`,
  `building_reclaimed`).
- `World.summary()` / `inspect_world.py` now report settlement counts
  (under construction / standing / ruined) and average condition.
- Generalized migration mechanism extended to the new `settlement`
  subsystem — a pre-Phase-C save backfills an empty `Settlement()` the
  same way `population`/`resources` were backfilled before it.

### Tested
- 23 new tests (21 in `tests/test_settlement.py` plus 2 migration tests
  in `test_persistence.py`/`test_engine.py`) covering construction
  eligibility, presence-driven work, weathering (including a harsh-vs-
  clear-weather comparison), ruin/reclamation timing, and serialization
  round-trips. Full suite: 134 tests, all passing.
- Full CLI release checklist per `docs/TESTING.md`: fresh-world smoke
  test, resume test, and a migration test (settlement backfill on a
  pre-Phase-C save), all passing.
- **Honesty note:** two long soak attempts (~8,600 and ~17,000 ticks,
  6 and 30 initial agents respectively) specifically trying to observe
  organic construction through unassisted play did not succeed — every
  agent died of starvation before reaching `MATURITY_TICKS` in both
  runs. The construction/repair/weathering/reclamation mechanism itself
  is directly unit-tested and the integration/persistence path is CLI-
  verified, but a completed building has not personally been witnessed
  through organic play in this session. See `docs/DECISIONS.md`, C5, for
  the full finding and what it implies for Phase D.

### Known gaps (intentional, tracked for later phases)
- Building placement is pure chance (gated by eligibility), not yet
  influenced by `AgentGoal` or LLM cognition — the natural next slice.
- No roads, no building types/variety, no resource cost for construction
  beyond agent time — that's Phase D (agriculture/economy) territory.
- Populations tend toward starvation before reaching the maturity
  threshold needed to found a settlement under current tuning (see C5) —
  not fixed in this release; flagged as a real balance question for
  Phase D or a dedicated tuning pass.

## [0.4.0] — Phase B (slice 1): LLM cognition layer (Ollama)

### Added
- `hearthmind/llm/`: a stdlib-only (`urllib`) Ollama client
  (`client.py`), a bounded-concurrency async job runner with mandatory
  timeout + deterministic fallback (`jobs.py`), per-agent goal
  prompt/parse/fallback logic (`cognition.py`), and seasonal chronicle
  summarization (`chronicle.py`). Off by default (`Config.llm_enabled`,
  `--llm-enabled`).
- Agents now have a `goal` (wander/forage/socialize/rest), re-evaluated
  once per sim-day (staggered across the day), that biases movement:
  FORAGE/SOCIALIZE move toward the nearest visible resource node/agent,
  REST proactively pauses activity, WANDER is the unchanged pre-Phase-B
  behavior. Goal decisions come from the LLM when enabled, or a
  deterministic hunger/energy rule when not — the simulation is
  unaffected either way beyond richer/simpler goal choices.
- A seasonal `chronicle` event (LLM-authored prose, or a deterministic
  templated count-based summary as fallback) is logged on every
  `season_end`, reusing the existing `events` table.
- All LLM-backed work is scheduled and collected entirely inside
  `SimulationEngine` as fire-and-forget background tasks — `World.tick()`
  stays fully synchronous and unaware the LLM exists, preserving the
  Milestone-1 invariant that the engine is the only thing that mutates
  the World and never blocks the tick loop.
- `inspect_world.py --agents`: lists each inhabitant's position, state,
  goal, goal reason, needs, and age — the first way to inspect individual
  agents rather than only population aggregates.
- CLI flags: `--llm-enabled`, `--llm-host`, `--llm-model`,
  `--llm-timeout`, `--llm-max-concurrent`.

### Tested
- LLM-facing code tested against a fake local HTTP server
  (`tests/_llm_fake_server.py`) covering success, malformed JSON,
  non-200 status, connection-refused, and timeout paths, plus an
  engine-level end-to-end test proving a fake server's response actually
  reaches an agent's `goal`/`goal_reason`.
- **Not yet verified against a real Ollama installation** — no Ollama
  available in the environment this was built in. See README's "LLM
  cognition layer" section and `docs/TESTING.md` section 6b for the
  checklist to run before trusting this in production.

### Known gaps (intentional, tracked for later phases)
- No priority distinction between cognition and background-enrichment
  job types yet — a single bounded semaphore is enough at current scale.
- The chronicle isn't read back into agent cognition prompts yet (no
  long-term LLM memory loop) — planned once Phase E (culture) needs it.
- Only four fixed goals; no free-form reasoning or richer triggers beyond
  the daily cadence.

## [0.3.0] — Phase A: Foraging, lifecycle, relationships and birth

### Added
- `hearthmind/world/resources.py`: discrete, depletable `ResourceNode`s
  scattered on forageable terrain (forest/grassland/hills) at world
  creation, regenerating slowly (~500 ticks from empty to full). Closes
  the M2-2 gap — hungry agents now forage nearby nodes instead of hunger
  only ever rising.
- Agents now age (`age_ticks`) and carry a per-agent lifespan
  (`max_age_ticks`, randomized at spawn) — dying of old age when reached.
- Starvation death: sustained (200+ consecutive ticks) high hunger with no
  food available kills an agent; a single bad tick does not.
- Lightweight relationships: agents build affinity with others they're
  colocated with, decaying otherwise. Mature, healthy, sufficiently
  affinitied pairs can reproduce (small per-tick chance), producing a new
  agent with recorded parent lineage — gated by a hard population cap
  (200) as a safety valve.
- Births and deaths are logged as `birth`/`death` events, visible via
  `inspect_world`'s recent-events list.
- `World.summary()` / `inspect_world.py` now also report resource-node
  counts/fullness and average population age.
- The pre-Milestone-2 snapshot-migration mechanism (M2-3) is generalized:
  `migrated_population: bool` became `migrated_subsystems: list[str]`, so
  the new `resources` subsystem (and any future one) is backfilled on
  load the same way, without a bespoke branch per field.
- `docs/ROADMAP.md`: the long-term phased plan (Phase A through Phase G).
- `docs/TESTING.md`: the release-testing checklist (unit tests + real CLI
  smoke tests for fresh-world, resume, and migration paths).

### Known gaps (intentional, tracked for later phases)
- No LLM involvement yet — reproduction/relationships are a deliberately
  cheap deterministic placeholder Phase B's cognition layer will build on
  top of, not replace outright.
- No settlements, buildings, or agriculture yet — foraging is still the
  only food source (Phase C/D).
- The population cap (200) is a blunt safety valve, not an emergent limit;
  Phase D's economy should make it unreachable in practice.

## [0.2.0] — Milestone 2 (slice 1): Agents — population, needs, movement

### Added
- `hearthmind/agents/` package: `Agent` (position + hunger/energy needs +
  awake/resting state), `Population` (spawns and ticks a collection of
  agents), and a small deterministic name generator.
- Agents spawn on walkable terrain (grassland, forest, hills, beach) when a
  world is first created; count is controlled by `Config.initial_population`
  / `--initial-population` (default 12, creation-only).
- Agents' needs decay deterministically each tick (seeded by
  `(world_seed, tick)`, same discipline as weather): hunger always rises;
  energy drains while awake and recovers while resting. Awake agents
  occasionally wander to an adjacent walkable tile; low energy triggers
  resting, which pauses movement until energy recovers.
- `World.summary()` and `inspect_world.py` now report population counts and
  average hunger/energy.
- Loading a pre-0.2.0 snapshot (no population yet) now spawns an initial
  population on load, logs a `population_migration` event, and persists a
  snapshot immediately — existing saves keep working (see
  `docs/DECISIONS.md`, M2-3).
- `pyproject.toml` added: real package metadata, console-script entry points
  (`hearthmind-server`, `hearthmind-inspect`), and a `dependencies` list
  ready for Milestone 3's Ollama client.
- This changelog.

### Known gaps (intentional, tracked for the next slice)
- No food source or consumption — hunger only ever rises. There is no death
  or starvation mechanic yet; that arrives with foraging/agriculture.
- No inter-agent interaction, relationships, or social behavior yet — agents
  currently wander independently.
- Snapshots remain full-JSON (not incremental); adding ~a dozen agents does
  not yet make this a problem, but it is the same scaling concern flagged in
  M1-4 and will need addressing before population/building counts grow much
  further.

## [0.1.0] — Milestone 1: Core sim loop + persistence

Retroactive entry for the pre-changelog baseline.

### Added
- Deterministic terrain generation (diamond-square elevation + biome
  classification), seeded and reproducible.
- `SimClock`: tick-count-driven calendar (minute/day/season/year), no
  wall-clock dependency.
- Deterministic, seasonally-aware weather derived per-tick from
  `(seed, tick)`, smoothed against the previous tick for continuity.
- SQLite persistence: `world_meta`, append-only `snapshots`, append-only
  `events`; WAL mode for concurrent reads.
- `SimulationEngine`: async tick loop, graceful start/stop/resume via
  SIGINT/SIGTERM, periodic + final snapshotting.
- `server.py` CLI entrypoint and `inspect_world.py` read-only inspector.
- Sim time does not fast-forward while the server is off (see
  `docs/DECISIONS.md`, M1-1) — a deliberate, revisitable Milestone-1 choice.
- Zero external dependencies (stdlib only).
