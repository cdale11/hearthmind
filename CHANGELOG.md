# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

## [1.23.0] — A18 "Events as composable reactions," first slice — a general AND-combination engine (roadmap Stage IV step 25)

Explicit user instruction: "Next step" — Stage IV step 25, docs/
MASTERCHECKLIST-2026-07-22.md's A18: "an event is a *reaction* fired
when a combination of field/social/economic conditions crosses a
threshold — not a scripted incident... a drought-field + a feud-edge
+ a food-shortage compose into [something] nobody hand-authored."

Deliberately distinct from `world/ontology.py`'s `TriggerRule` (a
SINGLE named trigger, LLM-authored per rule) — this is the doc's own
"small condition->consequence rule engine," where the combinatorial
part is real: three independently-tracked Body signals crossing their
OWN thresholds *simultaneously* compose into a consequence no single
condition would cause alone. New `world/reactions.py`: `CONDITION_
KEYS` (`drought`/`feud`/`food_shortage`, each backed by an already-real
or cheaply-computed signal — drought/food_shortage are edge-detected
the same heat_pressure/granary-fill readings `TriggerRule`'s `on_
drought`/`on_surplus` already use, just the opposite fill edge for
`food_shortage`; `feud` reads `Institution.feuds` directly),
`CompositeReaction` (an AND of `conditions`, matched via `matching_
reactions`). New `SimulationEngine._maybe_tick_composite_reactions`
(every tick, deliberately independent of `_maybe_tick_trigger_state_
edges` which early-returns with no stored `TriggerRule`s — a composite
reaction has nothing to do with village-authored rules): computes each
settlement's active condition set, checks it against the registry,
cooldown-gates (`COMPOSITE_REACTION_COOLDOWN_TICKS=1500`, longer than
a single `TriggerRule`'s 500 — a composite firing is a stronger event),
and applies via `_apply_composite_reaction`.

Scoped down hard, per this project's standing "first slice, not the
full spec" discipline: one hand-authored `CompositeReaction` ships
("Desperate Times": `drought` + `feud` + `food_shortage`), proving the
combinator itself works, not a general authoring system yet (a village
can't propose its own combinations the way `TriggerRule` is
LLM-authored — flagged follow-up). The doc's own worked example ("a
raid nobody hand-authored") is scoped down to a buildable, already-real
consequence rather than a new combat/raid mechanic: the two feuding
families' living members take a bounded, immediate relationship hit
(`COMPOSITE_REACTION_RELATIONSHIP_PENALTY=0.25`, smaller than a single
LLM-mediated dispute's own worst-case swing) plus a real Emergence API
`unexplained_shift` observation and a new `composite_reaction` event/
highlight entry.

UI: new `composite_reaction` event-log icon (💥) and filter-group
mapping (alongside `family_feud`/`dispute` under "people") — reuses the
existing event-log/highlights machinery rather than adding a new panel.

Verified: a real production-path test (manufactured two feuding FAMILY
institutions, forced `heat_pressure`/an empty granary to trigger
`drought`/`food_shortage`, called `_maybe_tick_composite_reactions`
directly) confirming the relationship penalty applies correctly, a
real `unexplained_shift` Emergence entry is appended, and the cooldown
correctly blocks an immediate re-fire. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — `_composite_reaction_last_
fired` is transient (same non-persisted precedent as `_prev_drought_
state`), no persisted field touched.

## [1.22.0] — A17 "Information ecosystem unification," first slice — social-graph-weighted propagation (roadmap Stage IV step 24)

Explicit user instruction: "Next step" — Stage IV step 24, docs/
MASTERCHECKLIST-2026-07-22.md's A17: "unify knowledge/rumor/tradition/
belief/song/map/custom/technique into one propagation model on the
social graph... each unit spreads... by the same rules."

Scoped down hard, per this project's standing "first slice, not the
full spec" discipline — the full unification is a large, genuinely
risky rewrite of several independent mature mechanisms (rumor
distortion, `invention_knowledge`'s teach/lose/rediscover, ontology
lineage) and is explicitly NOT attempted here. What ships: the one
piece every future propagation mechanism actually needs and none of
today's have — new `world/memetics.py`'s `propagation_weight`/
`weighted_spread_target`, a reusable "who catches this next" weighting
that traces the real relationship graph (`Agent.relationships`/
`.trust`, Phase 0's `Ledger`) instead of picking a next carrier
uniformly at random. A candidate's pull is the strongest single tie
among current carriers (`PROPAGATION_FONDNESS_WEIGHT=0.7`,
`PROPAGATION_TRUST_WEIGHT=0.3`, floored at 0 — an existing carrier who
dislikes a candidate exerts no pull, never a negative one) plus a
`PROPAGATION_BASELINE_WEIGHT=0.15` floor so word can still travel
beyond direct friendship, and so a concept with zero adopters yet
(empty `carriers`) degrades cleanly to uniform selection rather than
being unable to start spreading at all.

Real production proof: `SimulationEngine._maybe_spread_concepts`
(ontology concept adoption growth) previously picked a concept's next
adopter via a flat `rng.choice` over every eligible core-cast member
in the origin settlement, with zero regard for who was already an
adopter — a real gap against A17's own "propagation on the social
graph" framing, which had been true only of the docstring, not the
code. Now spreads via `memetics.weighted_spread_target(candidates,
carriers, rng)`, `carriers` being the concept's current living
adopters — a friend of an adopter is now measurably more likely to
pick up a new custom/technology next than a stranger is. Verified via
a direct distribution test (a candidate with a 0.95 fondness/0.8 trust
tie to the sole existing carrier was chosen ~55% of the time against 7
candidates, vs. ~14% under the old uniform pick) and a real production-
path test driving `_maybe_spread_concepts` itself through a live
`SimulationEngine`.

Deliberately NOT attempted this pass, flagged in docs/MASTERCHECKLIST-
2026-07-22.md: folding rumor/tradition/belief/song/technique spread
onto this same function, a shared mutate/decay/compete step, or "false
beliefs propagate if fit" (no fitness-vs-truth axis exists yet for
rumors) — `memetics.py` is the propagation-weight primitive the full
unification would need next, not the unification itself. No UI
surfacing this pass — this changes HOW an existing mechanism's next
adopter is chosen, not what state is exposed; concept adoption counts
were already reachable via the existing knowledge-tree panel.

Verified: a direct smoke test of `weighted_spread_target`/
`propagation_weight` (weighted pick skews correctly toward a strong
tie, degrades to uniform with no carriers, `None` on an empty
candidate list), a real production-path test exercising the actual
`_maybe_spread_concepts` engine method through a live `SimulationEngine
.load_or_create` instance. `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — `memetics.py` touches only plain
Python-side agent/world state already covered by the soak's full
`World.to_dict()` comparison, no new persisted field.

## [1.21.0] — A14 "Layered organism biology," first slice — real immune state + full UI exposure pass (roadmap Stage IV step 23)

Explicit user instruction: "Next step" — Stage IV step 23, docs/
MASTERCHECKLIST-2026-07-22.md's A14, the spec's own worked example:
"immune response (illness resistance as state, not a coin flip)."
Followed immediately by an explicit user request mid-turn: "All these
new features should appear in the live map of UI as well, expose them
to UI" — addressed in the same batch (see the UI section below), not
deferred.

New `Agent.immune_strength`: a real continuous 0..1 state, plain
Python-side (not native-store-backed, same as `traits`/`genome` —
zero parity risk). `Population._tick_immune_strength` (every tick, all
agents): hunger/energy pull it toward a nutrition/rest-derived target
via exponential smoothing (`IMMUNE_ADAPT_RATE` — a real physiological
lag, not instantaneous like hunger/energy themselves); an active
infection drains it further (`SICKNESS_IMMUNE_DRAIN_PER_TICK`, the
reverse coupling — fighting illness taxes the immune system). `_tick_
disease` now multiplies both `SICKNESS_TRANSMISSION_CHANCE_PER_TICK`
and the per-tick death-chance roll by `_immune_modulation_factor`,
stacking with (never replacing) the existing resilience/medicine/
hospital modifiers. Centered so `IMMUNE_BASELINE=0.5` is a true no-op
against every already-tuned sickness rate — the modulation only ever
pushes rates up or down from the well-calibrated center that existed
before this system, never silently re-tunes the baseline.

Scoped to the ONE subsystem the spec names explicitly (immune
response); stress, reproduction, development/life-stages, injury-
recovery, and sleep — the other five named subsystems — remain open,
explicitly flagged rather than silently folded into this slice. A
genetic contribution to baseline immune_strength (beyond nutrition/
rest) is a real, flagged future connection to A15 (v1.20.0), not built
here.

**UI exposure pass** (explicit user request, this same batch): audited
every feature shipped across the last several roadmap steps (18-23)
for real main-UI/map visibility, not just dev-console/NPC-inspector
reachability:
- `World.summary()` (the regular per-tick broadcast, not `full_
  diagnostics()`'s dev-console-only payload) now includes a real
  `discoverable` field per settlement — the same A5/A6/A12/A13 query
  Innovation's own proposal prompt already grounds on, computed live
  from standing buildings. New "Discoverable" main-UI stat tile
  aggregating combinations/reactions across all settlements.
- Agent map markers gained a third status ring: a faint amber ring
  when `immune_strength` is notably low (run down from nutrition/rest
  neglect) but not currently sick/recently-immune — visually distinct
  from the existing starving/sick/immune rings, a real glanceable
  "this person is vulnerable" signal on the live map itself.
- NPC inspector's health line (`healthLabel`) and Personality section
  gained plain-language immune-state readings ("healthy, but run
  down" / "immune constitution: robust/steady/run down").
- Genetics (A15) and evolutionary innovation (A8) were confirmed
  already reaching real UI (NPC inspector's "mixed inheritance" line,
  knowledge-tree's "generation N" marker) — no gap found there.

Verified: direct tests for `_tick_immune_strength` (nutrition/rest
pull in both directions, sickness drain, floor clamping, average-
hunger/energy staying at baseline) and `_immune_modulation_factor`
(exactly 1.0 at baseline, bounded, correct direction at extremes);
`Agent.to_dict`/`from_dict` round-trip including legacy backfill to
`IMMUNE_BASELINE`; a 3000-tick real production-path engine run
confirming genuine population-wide immune_strength drift; a full
`World.to_dict`/`from_dict` round trip; a direct `World.summary()`
test confirming the new `discoverable` field. `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical, re-run after both the
population.py/agent.py changes and the state.py UI-exposure change. A
Node syntax check confirmed the app.js edits parse cleanly.

## [1.20.0] — A15 "Genetic inheritance," first slice, scoped to humans (roadmap Stage IV step 22)

Explicit user instruction: "Next step" — Stage IV step 22, docs/
MASTERCHECKLIST-2026-07-22.md's A15. Direct target: `_inherited_
traits`'s own docstring already confessed "Trait inheritance is
blend+noise (v0.87-era), not genetics" — exactly this doc's own
Status line for A15.

Replaces v0.87.6's flat parent-average-plus-Gaussian-noise trait
blend with real diploid genetics. New `Agent.genome: dict[trait,
(allele_a, allele_b)]` over the four existing psychology axes
(resilience/sociability/ambition/openness) — `Agent.traits` (the
phenotype every existing trait-consuming call site already reads,
completely unchanged in meaning) is now the mean of its two alleles,
so zero downstream code needed to change.

Inheritance (`Population._inherited_genome_and_traits`, replacing
`_inherited_traits`): for each trait axis, a child's allele from each
parent is independently drawn from THAT parent's own two alleles (real
genetic drift — which allele passes on is random, not an average) and
independently subject to `GENOME_MUTATION_CHANCE` of instead being
replaced by a fresh mutated value (`GENOME_MUTATION_STDDEV`) — real
Mendelian-style recombination + mutation, not the old deterministic
blend. A parent with no recorded genome (any pre-A15 agent) is treated
as "homozygous at its current phenotype," so inheritance stays total
even from a genome-less parent — never a crash or a silently-skipped
axis. `TRAIT_INHERITANCE_MUTATION_STDDEV` kept as a historical record,
no longer read by any code.

Founders (`Population.spawn_initial`/`spawn_successor_founders`) now
draw a real diploid genome at spawn (`agent.seed_founder_genome`,
`GENOME_FOUNDER_ALLELE_STDDEV`) — every prior founder started flat 0.0
on all four axes (traits were "never rolled at spawn, only earned via
lifetime event nudges," per `TRAIT_INHERITANCE_MUTATION_STDDEV`'s own
old docstring); this closes that as a real, verified side effect
(founder resiliences now spread genuinely, e.g. -0.43 to +0.43 in one
12-founder test run) rather than a separate fix.

*Natural selection* (the doc's third named mechanism, "differential
survival/reproduction from real fitness") needed no new code: these
four traits already causally affect survival/reproduction odds
(H6/"traits mechanically consumed, not write-only" — resilience's
starvation-tolerance and predator-death-chance influence, sociability's
role in reproduction pairing) — genetics gives that PRE-EXISTING
selection pressure a real heritable substrate to act on for the first
time, rather than adding a second, parallel, redundant fitness
mechanism. This is called out explicitly rather than silently assumed.

Scoped deliberately to humans only. Wildlife/animal genetics (the
doc's "species adapt over generations... no authored progression"
half, and domestication as selective pressure from humans) remain
open — `world.wildlife.SpeciesVariant` (Vision item 4.2) stays
descriptive-only, not wired to a genome, for the same `AnimalHerd`
native-index parity-risk reason it was originally deferred. A14
("Layered organism biology," physiological genes beyond the existing
psychology-trait axes) is a real prerequisite for a fuller genome and
also remains open. `Organism.genome: ndarray` (the spec's literal data
model) was deliberately not used — a `dict[str, tuple[float, float]]`
matches the existing trait-axis shape exactly, with no numpy
dependency needed for four scalar pairs.

UI: NPC inspector's Personality section gained a plain-language "carries
a mixed inheritance in ..." line when an agent's alleles for a trait are
notably divergent (a real reading of the underlying genome, not raw
allele numbers) — reachable wherever the existing trait display already
is, no new panel needed.

Verified: direct tests for `seed_founder_genome` (covers all four
axes, values bounded), `_agent_allele_pair` (genome present/absent/
neither), `_inherited_genome_and_traits` (bounded output, `traits`
genuinely the mean of the returned `genome` alleles), a 2000-trial
statistical test confirming ~93% of inherited alleles trace to an
actual parental allele at the default mutation chance (matching
`1 - GENOME_MUTATION_CHANCE`), `Agent.to_dict`/`from_dict` round-trip
including legacy-snapshot backfill to `{}`, `spawn_initial` producing
real founder trait variance. A 6000-tick real production-path engine
run (LLM disabled) observed a real birth and inspected its genome
directly. A full `World.to_dict`/`from_dict` round trip confirmed
genome persistence (within the existing 4-decimal rounding convention
every other float field already uses). `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — `genome`/`traits` are plain
Python-side agent state, never native-store-backed, so this carries
zero parity risk by construction, confirmed anyway.

## [1.19.0] — A8 "Evolutionary Innovation loop," first slice (roadmap Stage IV step 21)

Explicit user instruction: "Next step" — Stage IV step 21, docs/
MASTERCHECKLIST-2026-07-22.md's A8. `world/ontology.py` already had
propose/evolve/merge with a real lineage DAG (*generate*); this closes
the loop with a real *evaluate* + *select* pass — concepts now spread
AND retire by evaluated survival, not adoption count alone.

*Evaluate*: `evaluate_fitness(world, concept)` — the doc's own "did
adopters prosper?" — reads as the mean `Population.reputation` (Phase
L, already-existing, already-cached monthly) of a concept's currently-
LIVING adopters, relative to its origin settlement's living-population
mean reputation. Returns `None` (not a faked 0.0) when there's nothing
real to measure (no living adopters, or no living settlement members).

*Select*: `run_selection(world, tick)`, paired at the exact same
monthly cadence/call site as the existing `abandon_stale` sweep. Every
`spreading`/`established` concept gets one fresh fitness reading
appended to a bounded `fitness_history` (`FITNESS_HISTORY_MAX=8`,
skipped not zero-padded when unevaluable). Only once at least
`FITNESS_EVALUATION_MIN_READINGS=3` real readings exist does sustained
mean fitness below `FITNESS_UNFIT_THRESHOLD=-0.05` retire the concept
(`status = "retired"` — a new, distinct terminal state from
`abandoned`: this concept DID catch on for a while, unlike a stale
`proposed` one that never adopted at all) and revise Innovation's own
mirrored world-model belief about its hypothesis, same mechanism
`abandon_stale` already uses. `retired` concepts join `abandoned` ones
as the first tier `prune_concepts` clears when `MAX_CONCEPTS_STORED`
is exceeded.

The real consumer wiring: `fit_established_concepts`/`concept_fitness_
weight` make `_maybe_schedule_ontology_evolution`'s evolve/merge parent
pick a genuine fitness-WEIGHTED draw (via `random.choices`) instead of
a flat-uniform `rng.choice` — a concept with a real positive mean
fitness reading is measurably more likely to become a parent, closing
the spec's own "fit concepts spread and become parents" framing. An
un-evaluated or mildly-below-average `established` concept is never
categorically excluded (floored weight 0.1) — real evolutionary
diversity, not a hard cutoff duplicating `run_selection`'s own
retirement bar. `InventedConcept` gained `generation` (0 for an
original proposal, `max(parents) + 1` for evolve/merge, threaded
through `register_concept`'s new param) — `parent_ids` itself needed
no new field, already covered by the existing `lineage` DAG.

Scoped down from the spec's full generate→mutate→evaluate→select
description: sandbox forward-simulation (`simulation/sandbox.py`,
A-C) as a fitness input, and grammar-based mutation (A7) as a second
*generate* path alongside LLM propose/evolve/merge, are real, larger
follow-ups, explicitly flagged rather than attempted. Every concept
category (technology/custom/law/ritual/saying/profession/institution_
flavor/ecological) goes through the same mechanism — farming
techniques/governance/customs weren't singled out for special
treatment, matching how `InventedConcept` was already category-
agnostic.

UI: knowledge-tree entries for a concept with `generation > 0` now show
a "generation N" marker in the same lineage-bits slot as "evolved
from"/"merged from" — reachable in the existing 🌳 panel, no new UI
surface needed.

Verified: direct tests for `evaluate_fitness` (positive/negative
signal, no-living-adopters, no-settlement-members), `run_selection`
(sustained-unfitness retirement, history cap, neutral-fitness-stays-
established, proposed/abandoned concepts never evaluated),
`concept_fitness_weight`'s neutral/positive/floored-negative cases,
`fit_established_concepts`' status filter, `register_concept`'s new
`generation` param, and full `InventedConcept.to_dict`/`from_dict`
round-trip (including legacy-snapshot backfill to 0/empty-list) plus a
`World`-level `to_dict`/`from_dict` round trip. A 1500-tick real
production-path engine run (LLM disabled) completed with no error; a
direct `knowledge_tree()` test confirms the generation field surfaces
correctly. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical, re-run after both the ontology.py changes and the
state.py/knowledge_tree() change.

## [1.18.0] — A13 "Chemistry / reaction system," first slice (roadmap Stage IV step 20)

Explicit user instruction: "Next step" — Stage IV step 20, docs/
MASTERCHECKLIST-2026-07-22.md's A13, the direct continuation of A12
(v1.17.0) — "material science + chemistry together are the 'invent
metallurgy without hardcoding metallurgy' engine."

New `world/chemistry.py`: exactly the doc's own three worked examples,
reinterpreted against A12's real `MATERIALS` registry — `clay` + `heat`
→ `ceramic`, `ore` + `heat` → `metal`, `fiber` + `water_and_time` →
`cured_fiber` (fiber tanning/curing, the real-world "plant + water +
time" process the doc names). `world/materials.py`'s `MATERIALS`
registry gained three new entries backing these: `ore` (metal's raw,
harder-to-work, less-conductive precursor), `ceramic` (fired clay —
harder, far more durable, zero flammability, but far less workable),
`cured_fiber` (tanned/cured fiber — notably more durable and decay-
resistant than raw fiber). Every reaction product is a real, fully-
propertied `Material` like any other — a discovered reaction product
is immediately `derive_affordances`-capable, not a special second-class
output type.

`discover_reactions(available_materials, present_affordances)` is the
real "what does X produce under Y?" query the doc names — conditions
(`heat`/`water_and_time`, closed vocabulary) are themselves derived
from the SAME A5/A6/A12 affordance layer step 18/19 already built
(`can_conduct_heat`/`can_burn` imply `heat`; `can_carry_water` implies
`water_and_time`), so a settlement genuinely needs both the right
material present AND the right kind of building standing, not a flag
set by hand.

Scoped down from the spec's literal `ReactionRule(reactants,
conditions, products, rate)` + "a deterministic reactor that fires
rules when conditions meet" (an automatic tick-loop mechanism that
would mutate world state) — this ships the QUERY half only, same
"query first, automatic effects later" scoping A5/A6 itself took with
its own validate-step deferral. A real reactor changing a standing
building's material after the fact needs its own design pass (what
would that even change mechanically?) — explicitly flagged, not
attempted.

Real consumer, wired exactly like A5/A6's `discoverable_combinations`:
`_maybe_schedule_ontology_proposal` computes standing-building
materials/affordances (reusing the same query already built for step
18/19) and passes `discover_reactions`'s result into `llm/ontology.py`'s
`build_propose_prompt` (new optional `discoverable_reactions` param).
New dev-console `discoverable_reactions` diagnostic, same shape/depth
as `discoverable_affordance_combinations`.

Verified: direct tests for `world/chemistry.py` (every rule's reactant/
product/condition resolves against real closed vocabularies,
`available_conditions`'s heat/water_and_time derivation from
affordance tags, `discover_reactions` for each of the three worked
examples individually and in combination, the "material present but
no condition" negative case). A direct test of `build_propose_prompt`'s
new param. A 400-tick real production-path engine run (LLM disabled)
completed with no error; a direct `_diagnostics_snapshot()` test
confirms a SHRINE (clay) + FORGE (heat-capable) settlement surfaces
`ceramic` as discoverable. `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical.

## [1.17.0] — A12 "Material science / physical properties," first slice (roadmap Stage IV step 19)

Explicit user instruction: "Next step" — Stage IV step 19, docs/
MASTERCHECKLIST-2026-07-22.md's A12, the direct continuation of v1.16.0's
A5/A6 — "affordances start deriving from properties rather than being
hand-tagged."

New `world/materials.py`: `Material` (all ten spec-named properties —
hardness, density, conductivity, elasticity, durability, decay_rate,
flammability, toxicity, thermal_capacity, workability — each 0..1) and
a small closed `MATERIALS` registry: wood, stone, clay, metal, fiber.
Hand-authored (not measured), same discipline as A5's hand-tagging,
with real-world-plausible relative ordering (stone harder/denser/less
flammable than wood; metal most conductive; fiber most flammable-and-
workable-but-least-durable) — the ordering is what makes derivation
below produce sensible output, not literal material-science accuracy.
`BUILDING_MATERIALS` assigns each of A5's tagged `BuildingKind`s its
primary material, grounded in each kind's own existing docstring
identity (wood huts/docks, stone forges/bridges, worked metal at a
forge/factory/power-plant, fiber at pasture/hatchery fencing, clay at
the shrine).

The real bridge: `derive_affordances(material)` maps property
thresholds to a subset of `world.affordances.AFFORDANCE_TAGS`
(hardness+workability → `can_sharpen`; flammability → `can_burn`;
conductivity OR thermal capacity → `can_conduct_heat`; hardness+density
→ `can_support_weight`; toxicity → `can_poison`) — deliberately
partial, since `can_store_food`/`can_carry_water`/`can_redirect_water`/
`can_fertilize` are shape-derived, not raw-material-derived, and this
function only ever derives what genuinely follows from material
properties alone. New `building_affordances(kind)` is the real union
point: `world.affordances.BUILDING_AFFORDANCES`'s existing hand-tagged
set PLUS whatever the assigned material derives — hand-tagging never
disappears, it's extended.

Real consumer: `_maybe_schedule_ontology_proposal` (Innovation's A5/A6-
wired generate-step, v1.16.0) now computes standing-building
affordances via `materials.building_affordances` instead of the bare
hand-tagged set, so a genuinely material-driven combination (e.g. a
metal FORGE's `can_conduct_heat` following from conductivity, not just
a hand tag) is reachable by the proposal prompt too. The dev-console
`discoverable_affordance_combinations` diagnostic (v1.16.0) widened the
same way.

Scoped down from the full spec: per-instance `Entity.material:
Material` (every tool/vehicle/agent-crafted good carrying its own
material, not one closed per-`BuildingKind` lookup) and A13's
chemistry/reaction system (`A + B + condition → C` over these
properties) are real, larger follow-ups, explicitly flagged rather
than attempted.

UI: building click inspector gained a "Built of" line (client-side
`BUILDING_MATERIAL` mirror of `BUILDING_MATERIALS`, same mirroring
precedent as `daylight.py`'s `UK_DAYLIGHT_HOURS`) — plain
environmental fact, not Phase-G-gated.

Verified: direct tests (every `BUILDING_MATERIALS` entry resolves to a
real registered material; every `derive_affordances` output stays
within the closed vocabulary; metal derives `can_conduct_heat`/
`can_sharpen`, fiber derives `can_burn` but not `can_support_weight`,
stone derives `can_support_weight` but never `can_burn`;
`material_for_building` known/unknown; `building_affordances` always a
superset of the hand-tagged set, and empty for an untagged kind). A
400-tick real production-path engine run (LLM disabled) completed with
no error; a direct `_diagnostics_snapshot()` test confirms a standing
FORGE now surfaces both `tempered_tools` and `kiln_process`.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.16.0] — A5/A6 "Affordances + discovery query layer," first slice (roadmap Stage IV step 18)

Explicit user instruction: "Next step" — Stage IV step 18, docs/
MASTERCHECKLIST-2026-07-22.md's A5/A6, the prerequisite the doc itself
names for Innovation to discover unprogrammed combinations rather than
only ever naming within its existing closed hook vocabulary.

New `world/affordances.py`: `AFFORDANCE_TAGS`, the exact closed
vocabulary named in det_sys.md's own A5 example (`can_burn`,
`can_shelter`, `can_carry_water`, `can_sharpen`, `can_store_food`,
`can_redirect_water`, `can_fertilize`, `can_poison`,
`can_support_weight`, `can_conduct_heat`). `BUILDING_AFFORDANCES`
hand-tags `BuildingKind` — deliberately the "wrap, don't replace"
path the spec itself names: `BuildingKind` stays exactly as it is (a
closed enum mirrored into the C++ native store's integer code
tables — unsafe to touch mid-run), this attaches an ADDITIONAL,
purely-Python, purely-additive tag-set as external data. Each tag
reflects something that kind's existing identity/mechanics already
imply (a GRANARY already `can_store_food` per its own docstring; a
FORGE's description already invokes heat and tools).

A6's query layer: `affordances_present(standing_kinds)` — "what here
can_X?" — and `discover_combinations(present_tags)` — "what
combination of affordances would achieve Y?" — over a small, closed
`KNOWN_COMBINATIONS` registry (5 entries, e.g. `can_carry_water` +
`can_store_food` → `irrigation_store`, `can_conduct_heat` +
`can_sharpen` → `tempered_tools`). A combination surfaces only when
both its required tags are genuinely present among a settlement's
actually-standing buildings — deterministic, not LLM-asserted.

Real consumer, wired into Innovation's generate-step per the spec's
own "Feeds" line: `_maybe_schedule_ontology_proposal` now computes the
settlement's standing-building affordances and passes `discover_
combinations`'s result into `llm/ontology.py`'s `build_propose_prompt`
(new optional `discoverable_combinations` param) — the proposal prompt
is now grounded in real physical capability alongside (not replacing)
the existing prosperity/pressure-signal grounding. The validate-step
half named in the spec (re-checking a PROPOSED concept's claimed
mechanism against this layer, the way `validate_hook` already
re-verifies skill/goal targets) is explicitly NOT attempted this
pass — flagged follow-up; this slice covers the harder, more novel
generate-step half.

Also scoped down from the full spec: `Entity.affordances`/`Entity.
properties` as genuine PER-INSTANCE fields (any entity, not just
buildings) and A12's material-property registry (affordances DERIVED
from properties rather than hand-tagged) are real, larger follow-ups,
not attempted. This pass is a class-level `dict[BuildingKind,
frozenset[str]]` over the one entity class with an existing real
foundable/standing lifecycle to ground a proposal in.

New dev-console diagnostic: `full_diagnostics()`'s per-tick snapshot
gained `discoverable_affordance_combinations` (per settlement, live-
computed, not persisted state) — same depth as `invented_concepts_by_
category`.

Verified: direct tests for `affordances_present`/`discover_
combinations` (aggregation across multiple standing kinds, an
untagged kind contributing nothing, empty input, the exact-tag-pair-
subset requirement, deterministic sort order) and every `BUILDING_
AFFORDANCES`/`KNOWN_COMBINATIONS` tag confirmed to stay within the
closed `AFFORDANCE_TAGS` vocabulary; a direct test of `build_propose_
prompt`'s new param (grounding text present/absent). A 400-tick real
production-path engine run (LLM disabled) completed with no error, and
a direct `_diagnostics_snapshot()` test confirms the new field
computes correctly against real standing buildings.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.15.0] — A10 "Ecology as interacting populations / food webs," nutrient cycling (roadmap Stage IV step 17)

Explicit user instruction: "Next step" — Stage IV step 17, docs/
MASTERCHECKLIST-2026-07-22.md's A10. Scoped down from the full A10
spec (migration, competition, decomposition, nutrient cycling,
pollination, habitat formation, folding the food web onto the A1 field
substrate) to a single well-justified first slice: nutrient cycling
into farming, per the doc's own explicit "Feeds: nutrient cycling
closes a loop into farming" line.

New `economy/farms.apply_nutrient_cycling(farms, herds)`: any
`FarmGrid.soil_fertility`-tracked tile (i.e. a tile that's ever been
farmed) within `NUTRIENT_CYCLING_RADIUS=2` (Manhattan) of a
`WildlifeGrid` herd gains a small per-tick fertility bonus scaled by
`herd.count * NUTRIENT_CYCLING_BONUS_PER_ANIMAL`, summed across every
nearby herd but capped at `NUTRIENT_CYCLING_MAX_BONUS_PER_TICK` per
tile per call (several large overlapping herds can't instantly max a
tile out) and by the existing 1.0 fertility ceiling — real grazing/
dung enrichment, bounded the same way `SOIL_FERTILITY_MIN`/`_RECOVERY_
PER_TICK` are already bounded. Called from `World._tick_disasters` on
`"week_end" in calendar_events`, same cadence as A11's `tick_hydrology`
and the same reasoning: bound the real-time cost of a full-grid-
adjacent Python pass rather than running it every tick.

Deliberately a standalone module function, not a `FarmGrid`/
`WildlifeGrid` method: reads `WildlifeGrid.herds` read-only, writes
only into tiles already present in `soil_fertility` (never expands the
tracked-tile set), and never touches either grid's native fast path
(`_native_farm_grid_tick`, `_native_soil_fertility_deplete_step`/
`_recover_step`, or the wildlife grid's native-ported grazer branch) —
zero native/fallback parity risk by construction, still confirmed via
the soak run below. Migration, competition, decomposition (as a
distinct nutrient source beyond live-herd enrichment), pollination, and
habitat formation are explicitly NOT attempted this pass — real,
larger follow-ups, flagged in docs/MASTERCHECKLIST-2026-07-22.md's A10
section rather than silently dropped; the "fold the existing food web
onto the A1 field substrate into one coupled system" framing item also
remains open.

UI: new "Soil fertility" main-UI stat tile (`summary.farms.avg_soil_
fertility`, already computed, previously unsurfaced) — plain
environmental state, not Phase-G-gated, tooltip explains both the
existing fallow-recovery mechanic and the new nutrient-cycling bonus.

Verified: direct tests for `apply_nutrient_cycling` (no-op on an
untracked tile, in-radius bonus, out-of-radius no-effect, clamp to
1.0, the per-tick max-bonus cap actually engaging with several large
herds, and the exact Manhattan-radius boundary). A real production-
path test drives a real `SimulationEngine`/`World` through ~8 real
week boundaries with a large herd parked on a previously-depleted
farmed tile, confirming `soil_fertility` measurably rises (0.3 -> 0.81
over the run) beyond what ordinary fallow recovery alone would give
it. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical.

## [1.14.0] — A2 "CA/diffusion/reaction-diffusion operators" (roadmap Stage IV step 16)

Explicit user instruction: "Next step" — Stage IV step 16, docs/
MASTERCHECKLIST-2026-07-22.md's A2.

New `world/ca_operators.py`: a small library of generic, pure field
operators, per det_sys.md's own spec — `diffuse(grid, rate)` (spread
toward neighbor average — heat, moisture, scent), `reaction_diffuse(a,
b, rate_a_to_b, rate_b_to_a)` (two coupled fields exchange value,
conserving mass at each cell), `cellular_step(grid, rule)` (the
generic Conway-style per-cell rule, `rule(own_value, neighbor_values)
-> new_value`). Each is a pure function over any `list[list[float]]` —
not tied to `world/fields.py`'s coarse 3x3 `FieldGrid`, so any future
full-resolution field can compose them, matching the spec's own
"a per-tick pipeline lists which run in what order."

Forest succession — det_sys.md's own worked example, "the first
consumer" — is real, not a demo: new `terrain_evolution.compute_
succession_pressure` builds a 0/1 forest-tile indicator grid, runs it
through `diffuse` to get a genuine smoothed "how forested is my
neighborhood" reading (not just a flat 4-neighbor count), and averages
it against A11's real per-tile moisture field (v1.13.0's `Hydrology
Field`) — a direct "systems interacting with existing systems" tie-in,
not an isolated new field. The result MODULATES `_tick_fallow`'s
existing `REFOREST_MIN_FALLOW_WEEKS` threshold per tile: a well-
forested, moist neighborhood can reclaim in as few as `SUCCESSION_
WEEKS_MIN=1` week; a poor one can take up to `REFOREST_MIN_FALLOW_
WEEKS * SUCCESSION_WEEKS_MAX_MULTIPLIER` (2x) — bounded both
directions, real det_sys.md "gated by ... moisture" behavior.

Deliberately a MODULATION of the existing, already-tuned reclaim rate,
not a wholesale replacement — `maybe_reclaim`'s reforest-CHANCE roll
has a native C++ fast path (`_native_maybe_reclaim_tick`); rewriting
that mechanic outright would have real regression risk on a live-tuned
number. The eligibility computation this pass touches (`_tick_fallow`)
stays pure Python regardless of which path the chance-roll takes, so
native/fallback parity is structurally unaffected — confirmed by the
soak run below. `moisture=None` (a caller without a hydrology field,
or an old test) keeps the original flat-threshold behavior exactly,
verified directly.

Verified: direct tests for all three operators (`diffuse`'s spread
and no-op-at-rate-0 behavior, `reaction_diffuse`'s mass conservation,
`cellular_step`'s neighbor-rule application), `compute_succession_
pressure`'s moisture-sensitivity, `_tick_fallow`'s flat-rate backward
compatibility (unchanged when `succession_pressure` is omitted) and
its modulated fast/slow paths (a well-forested+moist tile reclaims
faster than the flat rate; a sparse+dry one reclaims slower), and a
real production-path test through `maybe_reclaim`'s actual native-vs-
fallback dispatch. A 700-tick full-engine run (LLM disabled) completed
with no error. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical.

## [1.13.0] — A11 "Continuous hydrology," first slice (roadmap Stage IV step 15 — starts Stage IV)

Explicit user instruction: "Start Stage 4's first step" — the first
step of Stage IV ("Deepen the Body," 16 steps), docs/MASTERCHECKLIST-
2026-07-22.md's A11, the roadmap's own "highest-leverage single item."

The existing `world/hydrology.py` only ever answered "is this tile a
river or a lake" — rivers carved once at genesis, lakes with their own
slow bounded-random-walk level. What A11 actually asks for is water as
a genuinely CONTINUOUS field every tile carries, with real flow and
feedback into agriculture/siting/disasters/ecology. Given the size of
the full spec (four real pieces: flow, groundwater, evaporation,
erosion-into-mutable-elevation), this ships a real, working first
slice rather than attempting all four at once — the same "scoped first
version, deferrals flagged explicitly" discipline every Stage III step
this session used.

New `world/hydrology_field.py`: `HydrologyField`, a real per-tile
0..1 `moisture` grid. `tick_hydrology` runs three real passes each
week: precipitation gain (scaled by `WeatherState.precipitation`),
a single-pass downhill transfer (each land tile pushes a bounded
fraction of its above-neighbor moisture excess to its lowest-elevation
orthogonal neighbor, computed against a snapshot so no tile's transfer
depends on iteration order), and evaporation (faster in summer). Water-
biome tiles stay pinned at full saturation. Two of A11's four pieces
are explicitly NOT attempted and flagged rather than silently dropped:
groundwater (no subsurface reservoir layer — surface moisture only)
and erosion feeding back into now-mutable elevation (`Tile.elevation`
stays immutable this pass — the single biggest remaining piece of
A11, deliberately deferred since it touches the already-native-ported
`TerrainGrid` and needs its own careful equivalence pass).

Real consumers, not a number nothing reads: `FarmGrid.plant()` gained
a `moisture` param (new `FARM_MOISTURE_YIELD_MIN_FACTOR=0.5` floor —
a bone-dry tile still yields half of a fully-watered one's potential,
never zero) threaded from `Population._maybe_plant`/`Population.tick`
through `World.tick`'s existing `population.tick(...)` call site,
reading `World.hydrology_field.moisture` at the exact tile a field is
planted on — a planting decision's real yield now genuinely depends on
local water, not just soil fertility. New `SimulationEngine._detect_
hydrology_drought` (Emergence API, edge-triggered like `_detect_
settlement_bottlenecks`): a genuinely widespread drought (>=50% of all
tiles below `HYDROLOGY_DROUGHT_THRESHOLD=0.15`) emits one `bottleneck`
observation tagged `nature`/`village`, silent while it persists or once
it recovers.

R7 deviation, flagged (docs/CONSTITUTION.md's "new physical-substrate
code is C++-first" rule): ships in pure Python, weekly cadence (not
per-tick, to bound the real-time cost of an un-ported full-grid pass),
not yet natively ported. Justification, explicit: this is a genuinely
NEW field-based mechanism, not a reimplementation of an existing
pattern the way mining_scars/soil_fertility were — the flow-
accumulation algorithm's exact shape needs to prove itself against
real gameplay before being locked into a compiled interface expensive
to iterate on further. Port to C++ once the shape is confirmed live,
following `cpp/src/soil_fertility.cpp`'s precedent exactly.

New silent-backfill persistence: `World.hydrology_field` gets a fresh
field via `create_hydrology_field(terrain)` when loading a pre-A11
snapshot — deliberately NOT routed through the `migrated_subsystems`
narrative-announcement machinery (rivers/lakes use that since they're
one-time genesis events a player would notice being added); a
background field silently rebuilding is the same treatment
`_biome_counts_cache` already gets.

Surfaced: `World.summary()["hydrology"]["avg_moisture"]`, a new "Soil
moisture" stat tile in the main UI (average moisture as a percentage)
— explicitly player-facing per the standing workflow rule, not
dev-console-only, since it's plain environmental state like weather.

Verified: direct tests for `create_hydrology_field`/`tick_hydrology`
(water-tile saturation, moisture rising under sustained rain, falling
under sustained drought, round trip), `FarmGrid.plant()`'s moisture-
scaled yield (wet vs. dry vs. default-unset backward compatibility),
a real production-path test driving the actual weekly tick through
`SimulationEngine._tick_once` and confirming the field visibly changes,
`World.to_dict`/`from_dict` round trip including legacy-snapshot silent
backfill, and the drought detector's edge-trigger discipline (fires
once on the falling edge, doesn't re-fire while still in drought,
clears silently on recovery). `scripts/verify_native_soak.py` (2 seeds
x 800 ticks, long enough to cross a real week boundary) byte-identical
— the new field only mutates inside `World.tick`'s deterministic
weekly branch, exercised identically by both native and fallback runs
since nothing in this pass touches a native-ported module.

This starts Stage IV. 15 steps remain (16-30); per the roadmap's own
scoping note, each is a substantially larger effort than any single
Stage I-III step — continuing only on explicit future direction naming
the next step, same standing convention as every other vision doc.

## [1.12.0] — B7 "Humans collective consciousness + coordinator," first version (roadmap Stage III step 14 — closes Stage III)

Explicit user instruction: "Continue with next roadmap" — Stage III
step 14, docs/MASTERCHECKLIST-2026-07-22.md's B7, the last of Stage
III's 5 steps.

Audit first: both mechanisms this item names already existed. "One
collective mind (mood/values/direction)" is `humans_pillar` itself —
`_maybe_schedule_narrative_direction`'s own docstring already reads
this as "B7's collective consciousness read literally," since
`Settlement.mood` is the real aggregate of every living agent's
`Agent.emotions`. "A capped pool of cheap per-NPC calls on
dramatically-salient individuals" is core-cast cognition
(`Population.core_agent_ids`, bounded by `llm_core_cast_size`) plus
the voice pair's own narrative-significance selection (`Population.
maintain_voice_pair`) — also already real. The genuine gap: these two
mechanisms ran entirely unaware of each other. `SimulationEngine`'s
voice-pair-rotation call site logged a `voice_pair_change` event but
never told the collective mind anything — Humans' `self_model` had no
record of who currently carries the village's voice, and the rotation
never reached the Emergence API, so the collective mind's own
`observe` turn had no way to perceive it.

Fixed: the rotation site now writes `humans_pillar.self_model[
"current_protagonists"] = [name_a, name_b]` directly (zero LLM cost —
Humans' own persistent record of its current salient individuals, per
B9's self-model framing) and emits a real `"opportunity"`-kind,
`humans`-tagged Emergence API observation, so a rotation reaches the
collective mind's next real `observe` turn as perceived context,
exactly like any other pillar's genuine news already does. This
doc's own standing design decision (§"Two flags before building":
"when the Humans collective consciousness and an individual NPC
disagree, who speaks... individual acts locally, collective sets the
mood/direction they're measured against") is respected structurally —
`current_protagonists` is the collective's own AWARENESS of who's
salient, never a channel that speaks or acts on an individual's
behalf; the individual voice pair still speaks for itself via the
existing dialogue machinery, untouched.

`default_humans_pillar()`'s seeded `self_model` gained a
`"current_protagonists": []` default key so every fresh world starts
with the field present and empty rather than absent until the first
rotation.

Surfaced: dev-console-only (`full_diagnostics()["humans_pillar"]`),
matching every other pillar's internals — the rotation itself already
had real main-UI visibility via the pre-existing `voice_pair_change`
event log entry, so no new panel was needed for this pass's actual
delta.

**This closes Stage III of the roadmap** — all 5 steps (10 C3, 11 B4,
12 B5, 13 B6, 14 B7) are now shipped, each a real, scoped first
version. Stage IV ("Deepen the Body," 16 steps) remains open.

Verified: a direct engine-level test drives the actual voice-pair-
rotation call site through a real multi-tick run (LLM disabled),
confirming `Population.voice_pair_ids` gets selected, `humans_pillar.
self_model["current_protagonists"]` is populated with the real
selected names, and a matching `humans`-tagged Emergence API
observation is appended — the full real production path, not an
isolated unit test. `Pillar.self_model`'s `to_dict`/`from_dict` round
trip re-verified with the new key present. `scripts/verify_native_
soak.py` (2 seeds x 500 ticks) byte-identical — the new writes only
occur inside the existing tick-loop voice-pair-maintenance call site
(itself deterministic and already exercised identically by both
native and fallback runs), never inside an async apply() callback or
any native-ported path.

## [1.11.0] — B6 "Reflection as meta-scientist," first version (roadmap Stage III step 13)

Explicit user instruction: "Continue with next roadmap" — Stage III
step 13, docs/MASTERCHECKLIST-2026-07-22.md's B6.

Root gap: `_maybe_schedule_self_tuning` matched a supported reflection
hypothesis's subject against `self_tuning.TUNABLE_GOVERNORS` by EXACT
equality against only two hardcoded global labels ("wildfire
frequency", "ontology coherence"). But `_detect_reflection_pattern`'s
other five signal families (materials bottleneck, dispute feud,
starvation death, disease outbreak, wildlife recolonization, nature
adaptation) all produce SETTLEMENT-scoped subjects
(`f"{label} in {settlement_name}"`) — these could never match a fixed
dict key regardless of what governor existed, so a real, evidence-
backed, supported hypothesis about any of them was silently dropped
every single time, with no response at all.

Fixed with two pieces, matching the roadmap item's own two asks.
First, "extend TUNABLE_GOVERNORS to the major levers": new
`SimulationEngine._governor_key_for_subject` matches a hypothesis
subject against `TUNABLE_GOVERNORS` by PREFIX (`subject.startswith
(label)`), not exact equality — this alone makes every settlement-
scoped pattern reachable, not just the two subjects that happened to
be global. `TUNABLE_GOVERNORS` gained a real worked example for this
path: `"disease outbreak" -> "disease_outbreak_chance"`, consumed by a
new `chance_multiplier` param on `Population._maybe_outbreak` (applied
to the base per-tick chance, before the existing small-settlement
floor, which stays a real guarantee regardless of any governor nudge)
— `World.governor_tuning.get("disease_outbreak_chance", 1.0)` is
threaded through `Population.tick`'s call site in `world/state.py`
exactly like the existing `wildfire_chance` wiring. `_maybe_outbreak`
is ordinary per-tick Python logic, not native-ported, so this carries
no native/fallback parity risk (unlike wildlife/predator mechanics,
which stay untouched this pass for exactly that reason).

Second, "add the human-reviewed advisory-proposal inbox (human-
reviewed) for changes beyond governors": a supported hypothesis that
STILL names no governor (even after the prefix-matching fix) is no
longer silently skipped — `SimulationEngine._schedule_advisory` fires
a real, `critical=True` LLM call (`llm/self_tuning.py`'s new
`SYSTEM_PROMPT_ADVISORY`/`build_advisory_prompt`/`fallback_advisory`/
`parse_advisory`) asking Reflection for one short, free-text piece of
advice grounded in the hypothesis, logged into new `World.advisory_
proposals` (`{id, tick, hypothesis_id, subject, advice, status}`,
`status` starting `"pending"`). New `POST /advisory/{id}/review`
(`{status: "accepted"|"rejected"}`) — routed through the existing
`_apply_intervention` seam via a new `review_advisory` kind and
`SimulationEngine._review_advisory` — is the ONLY way that status ever
changes; nothing auto-applies an advisory to any real mechanic, kept
strictly out-of-band from the sandboxed, bounded numeric self-tuning
path that governors still use. "Track whether its advice worked" is
deliberately NOT attempted as a further automated measurement — there
is no mechanical effect from an advisory to score an outcome against
(unlike a governor nudge, whose real multiplier IS the measurable
thing); the human's own accepted/rejected marking on `POST /advisory/
{id}/review` is itself the tracked outcome, not a placeholder for one.

Both `self_tuning_actions` (governor path) and `advisory_proposals`
(advisory path) are checked together for "already acted on this
hypothesis" (`acted_hypothesis_ids` now unions both lists) so the same
supported hypothesis can never trigger both an LLM job types across
different firings. Surfaced: `advisory_proposals_recent` (last 10) in
`full_diagnostics()`, same dev-console-only depth as `self_tuning_
actions_recent` — this is Reflection's own internal record, not a
player-facing feature, matching Phase G/self-tuning's existing
precedent.

Verified: direct tests for the new prefix-matching helper, the
advisory prompt/fallback/parse layer, the outbreak-multiplier wiring
(a `chance_multiplier=0.0` smoke test), and `World.advisory_proposals`/
`next_advisory_id`'s `to_dict`/`from_dict` round trip including legacy-
snapshot compatibility. Two real production-path tests (monkeypatched
fake LLM client) exercise `_maybe_schedule_self_tuning`'s actual apply()
end to end: one showing a settlement-scoped `"disease outbreak in
Elmswick"` subject now correctly reaches the governor path via prefix
match and applies a real bounded nudge; one showing a subject with no
matching governor (`"predator pressure"`) correctly takes the advisory
path instead, and that `POST /advisory/{id}/review`'s intervention
dispatch correctly updates its status. `scripts/verify_native_soak.py`
(2 seeds x 500 ticks) byte-identical — `_maybe_outbreak`'s multiplier
only ever differs from 1.0 inside an async self-tuning apply() callback,
never inside `_tick_once`'s deterministic path, and stays 1.0 (a true
no-op) on every soak run since no governor tuning is ever applied there.

## [1.10.0] — B5 "Innovation as conscious scientist," first version (roadmap Stage III step 12)

Explicit user instruction: "Continue with next roadmap" — Stage III
step 12, docs/MASTERCHECKLIST-2026-07-22.md's B5. The doc's own item
names its full scope (query the Stage IV affordance/reaction layer)
but explicitly permits "a first version against today's closed-hook
vocabulary" — that's what ships here.

Root gap: `_maybe_schedule_ontology_proposal` already gated itself on
whether the settlement was "pressured" (any `Settlement.pattern_
signal_counts` value crossing `PATTERN_SIGNAL_BELIEF_THRESHOLD`) but
never told the LLM WHICH pressure was live — a proposal made under
real strain was invented exactly as freely as one made purely from
prosperity, so no genuine hypothesis was ever possible even when the
gate had already fired on a specific problem.

Fixed with two pieces. First, grounding: the engine now computes the
dominant crossed signal (max value among `pattern_signal_counts`,
e.g. `materials_bottleneck`, `dispute_feud`) and passes it to `llm/
ontology.py`'s `build_propose_prompt` as `pressure_signal`, rendered
in plain language via a new `PRESSURE_SIGNAL_LABELS` table ("a
shortage of building materials," "a run of bitter disputes and
feuding," ...). The model is now explicitly told: if a problem was
named, treat your idea as a real hypothesis for it — a guess that
might be wrong; if nothing was named, it's free to just be culture for
its own sake. Second, a real `hypothesis` JSON field (parsed/validated
same as every other field, "no specific problem" normalizes to an
empty string — a legitimate value, not a missing one) is stored on
`InventedConcept.hypothesis`.

The scientist half — closing the loop, not just naming a claim once —
is `world/ontology.py`'s new `_record_hypothesis_outcome`: the
concept's mirrored entry in `World.innovation_pillar.world_model`
(its id captured at proposal time as the new `InventedConcept.
world_model_entry_id`) gets REVISED IN PLACE (`revises_id`, not a new
entry) when the concept's real adoption lifecycle later confirms it
(`add_adopter` promotes it to `established` — confidence raised to
0.85, status `observation`) or refutes it (`abandon_stale`'s existing
stale sweep marks it `abandoned` — confidence dropped to 0.1). Zero
added LLM cost: the outcome is read straight off state that already
exists (`status`, `adopter_ids`), not asked of the model a second
time. A concept with no hypothesis (or, defensively, no captured
`world_model_entry_id`) is a correct no-op — nothing to confirm or
refute. This is the concrete "an idea is a testable guess, and the
Innovation pillar tracks whether its own guesses actually panned out"
mechanism the doc's "conscious scientist" framing asks for, scoped to
the registry Innovation already has (not waiting on Stage IV's
affordance/reaction substrate, which doesn't exist yet).

UI: `World.knowledge_tree()`'s existing concept entries now append the
hypothesis as plain-language context ("... (a hopeful answer to: a
response to a shortage of building materials)") when one exists — real
value in the already-shipped 🌳 knowledge-tree panel, no new panel
needed since nothing else consumes this field yet.

Deliberately NOT attempted this pass: evolve/merge (`_maybe_schedule_
ontology_evolution`) stay unchanged — hypothesis-tracking wasn't
extended to them; and any real query against affordances/reactions,
since that substrate is Stage IV, not built. Both flagged as the
re-targeting this item's own text anticipates once Stage IV lands.

Verified: direct tests for the confirm path (adopters -> established
-> confidence 0.85/status observation), the refute path (stale sweep
-> abandoned -> confidence 0.1), the no-hypothesis no-op, `InventedConcept.
to_dict`/`from_dict` round trip including legacy-snapshot compatibility
(old dicts missing the two new fields load with correct defaults), and
the prompt/fallback/parse layer's hypothesis wiring (pressure_signal
grounding text, "no specific problem" normalization). A real
production-path test (monkeypatched fake LLM client) exercises `_maybe_
schedule_ontology_proposal`'s actual apply() end to end, confirming the
hypothesis and `world_model_entry_id` land on the registered concept
and the mirrored belief starts at 0.4/`hypothesis` as before.
`scripts/verify_native_soak.py` (2 seeds x 500 ticks) byte-identical —
the new mechanism only runs inside async LLM-job apply() callbacks and
the existing monthly `abandon_stale`/`add_adopter` calls, never inside
`_tick_once`'s deterministic native-ported path.

## [1.9.0] — B4 "Inter-pillar consciousness bus" (roadmap Stage III step 11)

Explicit user instruction: "Next step" — Stage III step 11, docs/
MASTERCHECKLIST-2026-07-22.md's B4. The five pillars' `inbox`/`outbox`/
`MESSAGE_KINDS`/`make_message()` (`cognition/pillar.py`) had existed
structurally since B1 (v1.5.0) but were never actually delivered
between pillars — this ships real typed-message delivery, making a
pillar's `inbox` a genuine second input channel alongside the
Emergence API.

`Pillar.send_message`/`receive_message` (bounded `OUTBOX_MAX`/
`INBOX_MAX=8`, oldest dropped past cap — same discipline as `working_
memory`/`conversation_log`). New `Pillar.disagrees_with(subject_text)`:
a real mechanical definition of disagreement — does the pillar already
hold a confident (`>=0.5`) `world_model` theory whose `subject` label
substantially overlaps the incoming subject, via exact substring
containment or Jaccard word overlap (`word_overlap()`, new module-level
helper) at or above `DISAGREEMENT_OVERLAP_THRESHOLD=0.2`. Comparing
short `subject` labels rather than full belief sentences was a
deliberate correction made during development: an initial version
compared full sentence text at a 0.3 threshold and a direct test showed
two genuinely-related but independently-phrased sentences ("drought and
water scarcity" vs. "The land is drying, water grows scarce.") overlap
at only ~0.1 word-for-word — nowhere near enough to ever fire. Subject
labels ("drought") are short and directly comparable, so the switch
plus a lower threshold makes the check actually reliable against real
LLM-authored phrasing, verified via both isolated tests and a real
production-path test (monkeypatched fake LLM call) confirming correct
`"disagreement"` vs. `"warning"`/`"observation"` classification.

`SimulationEngine._send_pillar_message(from, to, kind, summary, data)`
constructs a message via `make_message` and delivers it into both
sides' outbox/inbox. Three concrete arrows wired at existing apply()
call sites, each gated on a genuinely new belief/concept (not every
tick): **Nature -> Village** (`_maybe_schedule_nature_mind`, kind is
`"disagreement"` when `village_pillar.disagrees_with(subject)`, else
`"warning"` at confidence >=0.6, else `"observation"`); **Village ->
Innovation** (`_maybe_schedule_beliefs`, kind `"theory"`, confidence
>=0.5 gate); **Innovation -> Village** (`_maybe_schedule_ontology_
proposal`, kind `"discovery"`, fires on every newly registered
concept). Reflection's "observes all four Minds" arrow needed no new
code — `_detect_reflection_pattern` already reads every pillar's Body
state directly, a one-way read not a message. The reverse disagreement-
aware classification (Village/Innovation checking whether the SENDER
disagrees) is flagged as a follow-up — only the Nature->Village site
does real disagreement classification this pass.

`_pillar_observe_turn` (the B3 salience scheduler) now merges
undelivered `inbox` messages into the SAME magnitude-ranked candidate
pool as Emergence API observations, via a new `_PILLAR_MESSAGE_
MAGNITUDE` table giving each message kind a synthetic magnitude
(`disagreement` 0.9 highest, down to `observation` 0.45) — a
disagreement message competes for and usually wins one of the five
`working_memory` slots on a pillar's next observe turn. Only messages
that actually get delivered this turn are removed from `inbox`; an
outranked message survives to compete again next cycle — this is the
literal mechanism behind "disagreement persists" rather than being
silently dropped or unconditionally force-fed regardless of priority.

Verified: direct tests for `send_message`/`receive_message` bounds,
`disagrees_with`'s subject-comparison correctness (substring + Jaccard
paths, both true/false cases), the inbox-merge/delivery/survival logic
in `_pillar_observe_turn`, a full `to_dict`/`from_dict` round trip with
an undelivered message surviving persistence, and a real production-
path test (monkeypatched fake LLM client) exercising `_maybe_schedule_
nature_mind`'s actual apply() showing correct message-kind
classification end to end. `scripts/verify_native_soak.py` (2 seeds x
500 ticks) byte-identical — message delivery only occurs inside async
LLM-job apply() callbacks, never inside `_tick_once`'s deterministic
native-ported path.

## [1.8.0] — C3 "Player <-> Pillar chat" (roadmap Stage III step 10)

Explicit user instruction: "Start [Stage] 3's first step" — the first
of Stage III's 5 steps, docs/MASTERCHECKLIST-2026-07-22.md.
Generalizes the existing Ask-the-Chronicler pattern (settlement-scoped,
narrative-only) to any of the five cognitive pillars.

New `llm/pillar_chat.py`: one shared `SYSTEM_PROMPT_TEMPLATE` (not five
hand-written prompts) — each pillar's answer is voiced through its own
`self_model["voice"]`/`description`, so Nature "never speaks as a
person" while Reflection "proposes hypotheses, never asserts
certainty" without maintaining five near-duplicate prompt strings.
Answers are built ONLY from the pillar's own real `objectives`/
`world_model`/`memory` — same "never a ground-truth readout dressed up
as in-character text" discipline the chronicler already holds.

`Pillar` (`cognition/pillar.py`) gained `conversation_log` (bounded,
`CONVERSATION_LOG_MAX=10` — "a light per-pillar player-model"),
`last_question`/`last_answer`/`last_answer_tick` (persisted), `pending`
(not persisted, same "in-flight state never survives a restart" reason
as `World.chronicler_pending`). New `GET /pillar/{pillar}`/`POST /ask/
{pillar}` (`interface/app.py`) and `SimulationEngine._schedule_pillar_
answer`, same enqueue-now/apply-next-tick seam as `_schedule_
chronicler_answer`.

"Nudges enter cognition as weighable inputs, never commands" (the
checklist's own phrasing): the resolved Q&A exchange is written into
`working_memory` via `note_observation()` — the SAME list every
representative pillar job's real `interpret` cognition call already
reads via `emergence_observations=list(world.<pillar>_pillar.working_
memory)` (the B2 mechanism). A recent question genuinely reaches that
pillar's next real cognitive turn as one more thing it noticed,
exactly like a salient Emergence API observation would — there is no
path from a player's question to a direct belief write or a bypassed
decision. "Pillars may initiate contact" (the checklist's own stretch
goal) is explicitly NOT attempted — flagged as real future scope.

UI: a new "🗣 ask a pillar" panel (pillar-select dropdown + question
form) under the explore menu, mirroring the existing chronicler panel
— per the standing workflow rule, this is explicitly player-facing
(Stage III's own title), not dev-console material.

Verified: direct engine-level test of the full `ask_pillar` ->
`_schedule_pillar_answer` -> apply -> `Pillar` state round trip
(pending clears, conversation recorded, working_memory updated,
`World.summary()["pillars"]` reflects it, `to_dict`/`from_dict`
survives with `pending` correctly resetting to `False`); an unknown-
pillar/blank-question no-op test; `scripts/verify_native_soak.py` (2
seeds x 400 ticks) byte-identical (a real-time-request-driven feature,
no change to the deterministic tick path).

## [1.7.1] — C1/C2 seam wiring (roadmap Stage II step 9)

Explicit user instruction: "Build step 9." Part C of docs/
MASTERCHECKLIST-2026-07-22.md ("THE SEAM") asks for the perception
channel (C1, Body → Mind) and intention channel (C2, Mind → Body) to
be made real for whichever pillars exist. Both were mostly already
real by construction once B1-B3 generalized to all five pillars — this
pass audited both against their exact spec wording and closed the two
real gaps found.

**C1 "bounded, salience-ranked, pillar-tagged"**: bounded (`Pillar.
WORKING_MEMORY_MAX=5`) and pillar-tagged were already true for every
pillar since B2. "Salience-ranked" was not — `_pillar_observe_turn`
fed pillar-tagged candidates from the 40-entry Emergence API window
into `working_memory` in plain recency order, so the FIFO cap could
silently discard a genuinely high-`magnitude` observation in favor of
a later, less salient one purely because it logged first. Fixed:
candidates are now sorted by `magnitude` (descending, unranked-`None`
sorted last) before only the top `WORKING_MEMORY_MAX` are noted — a
pillar's small attention budget is now deliberately spent on what
matters most this turn.

**C2 "every pillar acts only by emitting intentions the Body
validates and executes"**: audited every Body-touching write across
all five representative jobs. Village (`beliefs`) and Reflection
(`reflection`) write only their own Mind-state (theories/hypotheses),
never Body — nothing to validate, correctly. Innovation (`ontology_
proposal`) and Nature (`nature_mind`'s ecological-concept origination)
already validate before writing (`ontology.validate_hook`/`is_near_
duplicate`). Humans (`narrative_direction`'s dialect-drift term
coining) was the one real gap: it created a brand-new persistent
`Settlement.lexicon` entry with only a non-blank/length check, no Body-
side validation at all. New `narrative_direction.validate_coined_
term()` rejects an exact case-insensitive duplicate of an already-
coined term before the write — same discipline `validate_hook` already
enforces for Innovation. The spec's broader action list (invent tech,
set custom, change law, reorganize institution, shift land use,
domesticate, build, propose experiment) mostly isn't pillar-emitted at
all yet — those remain separate deterministic/LLM mechanics outside
the five-pillar refactor's current reach, correctly flagged PARTIAL
rather than force-completed.

Verified: direct smoke test of `_pillar_observe_turn`'s salience
ranking (mixed-magnitude/mixed-order candidates → top-5-by-magnitude
selected, unranked entries sorted last); direct `validate_coined_term`
test (duplicate rejected case-insensitively, novel term accepted);
`scripts/verify_native_soak.py` (2 seeds x 400 ticks) byte-identical.

## [1.7.0] — Symmetric idle speedup + B8 Living memory & consolidation (roadmap Stage II step 8)

Two explicit user requests in one turn: "the adaptive slowing of the
simulation should also adaptively speed up the simulation when LLM
load is low and system is sitting idle," and "continue the roadmap."

**Idle speedup.** `_llm_pressure_interval_multiplier()` (`simulation/
engine.py`) previously only ever stretched the real-time gap between
ticks (>= 1.0x) as LLM backlog pressure rose — a genuinely idle queue
(a fresh world, a quiet stretch, or `llm_enabled=False` entirely) ran
at exactly the user's configured/selected speed regardless of how much
spare LLM/CPU capacity was sitting unused. New `LLM_PRESSURE_SPEEDUP_
START_RATIO=0.15`/`LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER=0.4` mirror the
existing slowdown shape on the low side: below a pressure ratio of
0.15 (comfortably under the existing slowdown band's own 0.75 floor,
so there's a real flat "just right" zone at 0.15-0.75 that behaves
exactly as before), the multiplier scales linearly DOWN to 0.4 (up to
2.5x faster ticks) as the ratio approaches 0. Faster ticks mean agents
become cognition/dialogue-due sooner in real time (staggered-daily
eligibility is tick-count-based, the same mechanism the slowdown side
already leans on in reverse), converting idle LLM capacity into more
calls per real second rather than a merely cosmetic faster clock.
Purely a function of the existing `llm_pressure_ratio()` — no new
"is the system idle" signal needed, since an idle queue (including
`llm_enabled=False`) already reads as ratio 0.0 by construction. New
`full_diagnostics()["llm_pressure_interval_multiplier"]` surfaces the
live value (<1.0 sped up, 1.0 normal, >1.0 slowed) for the dev console.

**B8 — Living memory & consolidation, all five pillars** (docs/
MASTERCHECKLIST-2026-07-22.md, roadmap Stage II step 8). New `Pillar.
consolidate()` (`cognition/pillar.py`): once a pillar's `memory` list
reaches `MEMORY_CONSOLIDATE_THRESHOLD` (30, comfortably under the
existing hard `MEMORY_MAX=40` FIFO safety-net cap), folds the oldest
`MEMORY_CONSOLIDATE_BATCH` (8) raw notes into ONE condensed digest note
instead of letting them sit until the blind evict-oldest cap silently
drops them. Real forgetting (the individual raw notes are gone, not
merely capped) plus a literal form of "connect into concepts" (several
granular notes become one higher-level one) — deliberately zero LLM
cost, matching "maximize emergence per LLM call" (a genuine LLM-
authored summarization would be a real future upgrade, not this pass's
scope). Wired into the shared `SimulationEngine._pillar_close_cycle`
helper (already called once per closed cognitive cycle for all five
pillars since the B1-B3 generalization pass), so every pillar gets
real periodic consolidation automatically with no per-pillar wiring.
Deliberately NOT `reinforce`/`reinterpret` (the rest of B8's spec) —
that needs per-note salience/access tracking this pass doesn't add,
flagged as a smaller follow-up. Also updates the roadmap doc: B9
("self-model & world-model per pillar") is retroactively marked
SHIPPED — it was effectively subsumed by the earlier B1-generalization
pass (self_model/world_model have been part of `Pillar`'s shape for
every pillar since v1.5.0/v1.5.3), not a separate step as the roadmap
originally implied.

Verified: direct smoke test of `_llm_pressure_interval_multiplier()`
across idle/mid-zone/saturated backlog states (0.4x / 1.0x / 6.0x as
expected); a direct `Pillar.consolidate()` test (35 notes → fold to
28, correct digest content, no-op below threshold); `scripts/verify_
native_soak.py` (2 seeds x 400 ticks) byte-identical (both changes are
either real-time-pacing-only or a pillar-memory operation neither soak
harness's deterministic `_tick_once()` path exercises differently).

## [1.6.0] — Per-fallback diagnostics + single-adapter model-agnostic LLM layer

Explicit multi-part user request: (1) diagnose why `personal_belief`'s
`deep_reasoning=True` calls were still falling back so heavily; (2)
expose `raw_model_output`/`parsed_json`/`validation_errors`/`fallback_
reason`/`fallback_result` in the dev console whenever ANY LLM call
falls back; (3) refactor so adding a new LLM backend requires
implementing exactly one adapter class, with simulation/cognition/
prompts/validation/memory/game-logic staying completely model-
agnostic; (4) re-confirm Nemotron 3 Nano 4B as the default and tune the
adapter specifically around it.

**Root-cause finding for (1)**: `personal_belief` (`llm/beliefs.py`'s
`PERSONAL_SYSTEM_PROMPT`) asks for by far the largest JSON contract of
any `deep_reasoning=True` job in the codebase — 14 fields, several with
their own multi-clause instructions — versus 2-4 fields for every other
reasoning job (dispute, tradition, invention, laws, ...). It also can't
use a `json_schema` grammar (deliberately, since v1.3.37 — a grammar
would suppress the preceding `<think>` block), so its reasoning trace
and its unusually large free-form answer shared the exact same flat
`DEEP_REASONING_NUM_PREDICT_MULT` (1.5x) token budget every simple
2-field reasoning job also gets. On a real model, a genuine Nemotron 3
reasoning trace over this much required output can plausibly consume
the whole budget before any JSON is written; `_UNCLOSED_THINK_RE`
(client.py) then strips the entire dangling `<think>` block, leaving
nothing for `json.loads` — a `calls_errored` fallback with no visible
cause in the aggregate counters, exactly the blind spot item (2) below
fixes. New `PERSONAL_BELIEF_NUM_PREDICT_MULT=3.0` (`_schedule_llm_job`
gained a `num_predict_mult` override param) gives this one job real
extra headroom instead of raising the budget for every reasoning task;
the request-level timeout now scales proportionally with whatever
multiplier a job actually used (previously hardcoded to the flat 1.5x
regardless), so a job asking for more tokens also gets a fair chance to
generate them before the socket times it out.

**(2) Fallback diagnostics.** `CognitionRunner.run`/`_run_gated`
(llm/jobs.py) now return a 4th element, `diag` — a dict of
`fallback_reason`/`raw_model_output`/`parsed_json`/`validation_errors`,
populated on EVERY failure path (outer timeout, client socket timeout,
malformed JSON, unexpected exception), not just the aggregate counters
that already existed. The key fix making this possible: the client's
`capture["raw"]` dict was already being filled with the exact raw
completion text before any JSON-parse attempt (see `client.py`'s
docstrings) — but `_run_gated`'s exception handlers previously
discarded it entirely, returning bare `(fallback(), True, None)` with
the raw text silently lost. It's now read directly off the same local
`capture` dict every exception handler already has in scope, plus a
best-effort re-parse (`_diagnose_raw_output`, reusing `client.py`'s
`_extract_json_object`) so the dev console can show not just THAT a
call failed but WHAT the model actually said and WHY it didn't parse.
`_schedule_llm_job`'s `_runner` threads `diag` through to `_record_llm_
debug`, which folds it into `_last_llm_calls[name]` — already reachable
via `full_diagnostics()`'s existing raw-JSON dev-console dump, same
reachability precedent as `reflection_notebook`/`nature_pillar`, no new
endpoint needed. The daily-budget-exhaustion path (a separate, non-
`CognitionRunner` fallback route) gets its own synthetic `diag`
(`fallback_reason="daily_llm_budget_exhausted"`) for the same
visibility. `fallback_result` (the caller-side fallback dict, not
knowable inside `CognitionRunner`) is attached at each of the four
call sites in `simulation/engine.py`.

**(3) Single-adapter model-agnostic refactor.** New `llm.client.
LLMAdapter` (ABC): the entire contract between Hearthmind and any local
LLM backend — one `generate_json(...)` method plus a `build_from_
config(cls, config)` classmethod. `OllamaClient`/`LlamaCppClient` now
both inherit it; neither `llm/jobs.py`, `simulation/engine.py`, nor any
prompt/parse module under `llm/` imports either class by name or
branches on `config.llm_backend` — they only ever hold an `LLMAdapter`
reference and call `.generate_json(...)` on it (this was already
mostly true structurally via duck typing; the ABC + registry make it an
enforced, documented contract rather than an implicit convention). New
`llm.client.ADAPTER_REGISTRY: dict[str, type[LLMAdapter]]` is the
single dispatch point; `build_llm_client(config)` is now a two-line
registry lookup + `adapter_cls.build_from_config(config)` delegation
instead of a hand-rolled per-backend branch duplicating each adapter's
constructor fields. Adding a new backend is exactly: write a class
inheriting `LLMAdapter`, implement `generate_json`/`build_from_config`,
add one `ADAPTER_REGISTRY["name"] = MyAdapter` line — nothing else in
the codebase changes.

**(4) Nemotron 3 Nano 4B tuning.** `Config.llm_model` was already
`nemotron-3-nano-4b` (set v1.3.36) and `llm_backend` already
`"llamacpp"` (the default backend, v0.72.0) — this pass confirms
`LlamaCppClient` IS the Nemotron-tuned adapter (not a parallel unused
subclass — it already implements the "detailed thinking on/off"
system-prompt toggle plus the `reasoning_budget`/`enable_thinking`
request-level enforcement this model specifically needs, and lets
llama-server's own GGUF-embedded chat template handle role formatting
rather than hand-rolling one). New optional `top_p`/`min_p` fields
(`Config.llm_top_p`/`llm_min_p`, both `None`/unset by default) are
wired through but deliberately left unset: an attempt to consult the
model card at huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF for
its recommended sampling defaults was blocked by an outbound-fetch
failure in this environment (403 on every URL tried), so per CLAUDE.md's
"live user reports over unverified specs" discipline, no unconfirmed
number was invented — these two levers are ready for a future live-
tuning pass instead.

Verified: direct unit-style smoke tests of `CognitionRunner.run`
against a fake adapter for the malformed-JSON, LLM-disabled, and
success paths (confirming `diag` shape and raw-text recovery in each);
an engine-level test confirming `_schedule_llm_job`'s full budget-
exhausted fallback path writes the expected `fallback_reason` into
`_last_llm_calls`; `ADAPTER_REGISTRY`/`build_llm_client` construction
smoke test; `scripts/verify_native_soak.py` (2 seeds x 300 ticks)
byte-identical (no native module touched by this batch).

## [1.5.3] — B1/B2/B3 generalized to all five pillars

Explicit user directive, mid-turn correction on the B1/B2/B3 work below:
"you have only built nature pillar up until now, build all the other
pillars. Don't do half-jobs. Complete each and every checklist item
fully." The prior three versions proved the Pillar abstraction/
cognitive cycle/attention scheduler against Nature only, by design
(prove the shape once, generalize once proven) — this version is that
generalization.

New `cognition/pillar.py` factories: `default_village_pillar`/
`default_humans_pillar`/`default_innovation_pillar`/`default_
reflection_pillar`, each seeded with a real identity/self_model/
objectives for that pillar's actual domain. New `World.village_pillar`/
`humans_pillar`/`innovation_pillar`/`reflection_pillar`, fully wired
into `to_dict`/`from_dict`.

Rather than reimplement B2/B3's observe/interpret/backpressure/close
logic four more times, it was extracted from Nature's original inline
implementation into three shared `SimulationEngine` helpers —
`_pillar_observe_turn(pillar_name)`, `_pillar_interpret_backpressured
(pillar_name)`, `_pillar_close_cycle(pillar_name)` — and Nature's own
job was refactored to use them first (verified byte-identical
behavior), before wiring the four new pillars through the identical
helpers. Each pillar got exactly ONE representative existing job wired
through this shape (matching Nature's own precedent, not the larger
"refactor ~55 scattered jobs" ask, which stays explicitly out of
scope): Village → `_maybe_schedule_beliefs` (settlement-wide theory
formation), Humans → `_maybe_schedule_narrative_direction` (collective
mood/theme), Innovation → `_maybe_schedule_ontology_proposal` (new
concept origination), Reflection → `_maybe_schedule_reflection`
(cross-pillar hypothesis formation). Each job's prompt-builder
(`llm/beliefs.py`, `llm/narrative_direction.py`, `llm/ontology.py`,
`llm/reflection.py`) gained the same `emergence_observations` param
`nature_mind.build_prompt` already had. Confidence for a pillar's
mirrored `world_model` entry uses whatever real signal that job
already has (Village/Reflection: the job's own confidence field;
Innovation: 0.4, matching a freshly `"proposed"` concept's real
adoption-lifecycle starting value; Humans: the strongest real
`Settlement.mood` axis magnitude) — never a fabricated placeholder.

Dev-console surfacing: `full_diagnostics()` gained `village_pillar`/
`humans_pillar`/`innovation_pillar`/`reflection_pillar`, same raw-JSON-
only depth as the existing `nature_pillar` entry (nothing player-facing
reads any of the five yet).

Verified: direct smoke tests confirming all four new jobs' real observe
→interpret cycle-stage transitions and working_memory population; full
end-to-end apply()-completion tests (world_model entry creation,
working_memory clearing, cycle_stage reset to `observe`) for Humans and
Reflection specifically, awaiting the real async fallback resolution
path; a full `World.to_dict()`/`from_dict()` round trip covering all
five pillars simultaneously with each mutated; `scripts/verify_native_
soak.py` (2 seeds x 300 ticks) byte-identical.

## [1.5.2] — B3 "The Attention Scheduler," Nature first (roadmap Stage II, step 6)

Explicit user instruction: "Continue with roadmap" — Stage II step 6,
following step 5's cognitive cycle. B3 asks for "one budget arbiter
over all five [pillars]... priority from A22 salience + staleness +
player focus + inter-pillar messages," wired to the existing dynamic
pacing. Scoped like every step before it: round-robin over five
pillars is trivial with only Nature existing (it's always Nature's
turn); the real deliverable is the priority FORMULA itself, ready for
a genuine second pillar to arbitrate against.

New `hearthmind/cognition/attention.py`: `pillar_salience()` (the
strongest `magnitude` among A22 Emergence API entries tagged for a
pillar since its last turn — MAX not average, so one loud signal reads
as salient even amid a quiet stretch, `DEFAULT_SALIENCE=0.3` when
nothing tagged/magnituded exists), `compute_priority()` (weighted
combination — salience 0.5, staleness 0.3, inter-pillar messages 0.15,
player focus 0.05 — reflecting "maximize emergence per LLM call" over
mere time-since-last-turn), `backpressure_fraction()` (maps priority
0..1 to a 0.5..1.0 fraction of the shared backpressure limit a turn
tolerates before deferring — never a full bypass, same "scale the
threshold" shape `DIALOGUE_BACKPRESSURE_FRACTION` already uses
elsewhere, just computed instead of hardcoded).

`Pillar` gained `last_turn_tick` (the tick its cycle last genuinely
advanced — observe or interpret — feeding staleness), persisted.
`_maybe_schedule_nature_mind`'s `interpret` branch now computes a real
priority from the observations noticed since the pillar's last turn
(`world.emergence_log` filtered to `"nature"`) and staleness, then
defers under backpressure using that priority's scaled fraction
instead of the flat `_settlement_job_backpressured()` gate every other
settlement job shares — a quiet, fresh turn defers earlier under
pressure; a salient or long-overdue one tolerates more backlog first.
"Wired to the existing dynamic pacing" is otherwise already true
globally (the tick-loop's LLM-pressure-aware slowdown predates this
work and isn't pillar-scoped) — nothing here duplicates or replaces
it.

Deliberately not attempted: `message_count`/`player_focus` are both
real, ready inputs that read 0 for every pillar today — no second
pillar exists to message from (B4), and nothing connects player
attention to a specific pillar yet. Both terms activate automatically
once those exist, no further wiring needed here.

Verified: direct smoke tests (`pillar_salience`'s max-not-average
behavior, pillar-filtering, and window-boundary handling;
`compute_priority`'s bounds at 0 and 1; `backpressure_fraction`'s
floor/ceiling), an engine-level test confirming a real `_maybe_
schedule_nature_mind` observe turn sets `last_turn_tick` and that a
baseline-priority computation yields a real sub-1.0 tolerance fraction,
plus a `to_dict`/`from_dict` round-trip for the new field.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.5.1] — B2 "The continuous cognitive cycle," Nature first (roadmap Stage II, step 5)

Explicit user instruction: "Continue with roadmap" — Stage II step 5,
following step 4's Pillar abstraction (v1.5.0). B2 asks for each
pillar to run a genuine observe→interpret→remember→plan→act→reflect
cycle, resumed across turns rather than a single timer-fired job.

`cognition/pillar.py`'s `Pillar` gained `cycle_stage`/`CYCLE_STAGES`
(the full six-stage vocabulary, reserved for future generality),
`working_memory` (bounded `WORKING_MEMORY_MAX=5` scratch space, distinct
from the long-lived `memory` list), `note_observation()`, `clear_
working_memory()`, `set_cycle_stage()` — all persisted.

`_maybe_schedule_nature_mind` now branches on `nature_pillar.
cycle_stage` instead of firing the same monolithic call every season:
an `observe` season reads `World.emergence_log_recent()` (A22) filtered
to entries tagged `"nature"`, writes their summaries into `working_
memory` (zero LLM cost), and advances to `interpret` — a real C1
"perception channel" wiring (Nature now genuinely reads the curated
Emergence API, not just raw event categories; nothing read `emergence_
log` before this). The FOLLOWING season is the `interpret` turn: the
existing LLM call fires exactly as before, now also grounded in the
observations gathered last turn (`llm/nature_mind.py`'s `build_prompt`
gained an optional `emergence_observations` param, rendered as "What
you noticed since last time:" when non-empty) — remember/plan/act/
reflect still happen synchronously inside one call (`apply()`), which
then clears `working_memory` and returns `cycle_stage` to `observe`,
closing the cycle. A no-op revision (the model finds nothing worth
changing) also closes the cycle rather than leaving it stuck retrying
`interpret` forever.

Real consequence, not free: `nature_mind`'s LLM call volume is now
halved (one real call every OTHER season instead of every season) —
a genuine trade of raw call frequency for a resumable, perception-
grounded cycle, consistent with "maximize emergence per LLM call."
If a critical call is ever deferred (budget/failure), `cycle_stage`
stays on `interpret` and the next season retries from there — nothing
is lost, matching the standing critical-cognition deferral discipline
(CLAUDE.md's tick-loop workflow rule).

Deliberately NOT attempted: bounded bookkeeping for the four
intermediate stage names (`remember`/`plan`/`act`/`reflect`) as
separate persisted stops — Nature's one LLM call still performs all
four synchronously, matching the project's "one call does everything"
convention; splitting them across turns is future work if a pillar
ever needs it. B3 (attention scheduler) and generalizing this cycle
beyond Nature remain open Stage II steps.

Verified: direct smoke tests (`Pillar` cycle-stage/working-memory
semantics + round-trip, `nature_mind.build_prompt`'s new param), an
engine-level test calling the real `_maybe_schedule_nature_mind`
directly and confirming the observe→interpret stage transition and
working-memory population from a seeded `emergence_log` entry.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.5.0] — B1 "The Pillar abstraction," Nature first (roadmap Stage II, step 4)

Explicit user request: "Start stage 2" — the first step of the
roadmap's Stage II (docs/MASTERCHECKLIST-2026-07-22.md), the "five
minds" refactor. B1 is the doc's own "keystone": each future pillar
(Humans, Village, Nature, Innovation, Reflection) is meant to be a
persistent conscious entity with identity, self-model, world-model,
living memory, objectives, and inbox/outbox — this pass proves that
shape against ONE pillar (Nature) before replicating it four more
times, per the roadmap's explicit sequencing.

New `hearthmind/cognition/pillar.py`: `Pillar` (self_model — an open
dict of what the pillar is/wants; `world_model` — a list of typed,
revisable theories via `make_world_model_entry`, explicitly tagging
`status: "observation"|"hypothesis"` per B9's "distinguish observation
from hypothesis" line; `memory` — a capped consolidated-knowledge list,
`MEMORY_MAX=40`, the simplest possible stand-in for B8's real
consolidate/forget/reinforce cycle; `objectives`; `inbox`/`outbox` —
B4's typed `MESSAGE_KINDS` vocabulary, structurally present but unused
until a second pillar exists to message). Plain-dict-backed
(`to_dict`/`from_dict`), same persistence convention as every other
World-scoped store.

New `World.nature_pillar` (seeded via `default_nature_pillar()` —
genesis-time identity/self-model/objectives, not LLM-authored: what a
pillar fundamentally is isn't itself a revisable belief).
`_maybe_schedule_nature_mind`'s existing apply() (unchanged mechanics)
now mirrors every belief formation/revision into `nature_pillar.
world_model` (tracked via a new `pillar_entry_id` key on each
`World.nature_beliefs` entry, so a later revision updates the same
pillar entry) and appends a `remember()` note — `World.nature_beliefs`
itself is completely untouched, so every existing reader (town_brain
grounding, the ontology bridge, `/diagnostics`) keeps working exactly
as before. This is additive proof the shape holds against a genuine
production call site, not a standalone demo structure nobody writes
to.

Deliberately NOT attempted this pass: the checklist's larger B1 ask
("refactor the ~55 scattered jobs into acts of five pillars") — that's
B2 (the continuous observe→interpret→remember→plan→act→reflect cycle)
and the rest of Stage II; inter-pillar messaging (B4) stays inert since
Nature is the only pillar that exists yet; B8's real memory-
consolidation cycle stays a capped FIFO list, not genuine
consolidate/forget/reinforce/reinterpret.

UI: `full_diagnostics()["nature_pillar"]` — same dev-console-only
reachability as `reflection_notebook`/`emergence_log` (nothing
player-facing reads a pillar's self-model/world-model yet; the shape
is being proven, not shown off).

Verified: direct smoke tests (`Pillar`'s upsert-or-append world-model
semantics, memory cap, `to_dict`/`from_dict` round-trip, `make_
world_model_entry`/`make_message` validation), an engine-level test
exercising the actual `nature_mind` apply() mirroring logic (new
belief, revision, round-trip through `World.from_dict`, `full_
diagnostics()` reachability). `scripts/verify_native_soak.py` (2 seeds
x 800 ticks) byte-identical — the mirrored write only runs inside a
critical LLM job's `apply()`, which never fires in an LLM-disabled
soak, so this is a pure regression check on everything else.

## [1.4.9] — A1 FieldGrid + A16 Graph algorithms (roadmap Stage I, steps 2-3 — Stage I complete)

Explicit user request: "complete stage 1" — the remaining two steps of
the roadmap's Stage I (docs/MASTERCHECKLIST-2026-07-22.md), after
v1.4.8 shipped step 1 (the Emergence API). Both scoped to a real,
minimal proof-of-shape rather than the doc's full wishlist, matching
the same discipline v1.4.8 used.

**A1 FieldGrid** (step 2): new `hearthmind/world/fields.py` —
`FieldGrid`, a dict of named `FIELD_GRID_SIZE`x`FIELD_GRID_SIZE` (3x3,
matching `WEATHER_REGION_GRID`) dense scalar grids, deliberately coarse
per the roadmap's own scoping note ("the interface matters more than
resolution day one"). `World.fields`, stepped once per tick right
after `population.tick` (agent positions must be current). Ships one
concrete field, `population_density` (agents per region, normalized),
as a real per-tick-computed consumer proof rather than bare
infrastructure: `_choose_fission_site` now prefers a region the field
doesn't read as crowded (`POPULATION_DENSITY_FISSION_AVOID_THRESHOLD
=0.75`) when an alternative exists — never a hard block. The other
eleven named fields det_sys.md lists (moisture, fertility, disease-
pressure, ...) are explicitly not built this pass; each is an additive
follow-up onto the same grid. R7 deviation flagged (Python, not C++)
— same precedent as spatial weather/mining scars/minerals: a 3x3 grid
is under 200 floats total, several orders below where a native port
would pay for itself.

**A16 Graph algorithms** (step 3): new `hearthmind/world/graph_
algorithms.py` — `build_relationship_graph`/`degree_centrality`/`most_
central_agent`, a real graph-theoretic algorithm (weighted-degree
centrality, negative edges clamped to 0 since this measures
connectedness not fondness) run over the existing pairwise relationship
ledger rather than a second graph structure. New `Settlement.social_
hub_agent_id` + `SimulationEngine._detect_social_hub` (season cadence,
every settlement — cheap enough not to need round-robin gating, zero
LLM cost) recomputes each settlement's most-central living agent and
emits an A22 `unexplained_shift` observation only when the hub actually
changes (edge-triggered, same discipline as `_detect_settlement_
bottlenecks`). Community detection — the doc's other headline example
— was already shipped as `InstitutionKind.FACTION` detection (v0.80.0)
under a different name; not duplicated. Betweenness/network-flow/tech-
dependency-DAG metrics remain flagged future follow-ups.

UI: `social_hub_agent_id` reaches `Settlement.summary()`; a new
"Social hub" stat-tile row (main UI, per the Observatory direction's
"plain-language facts" precedent — this is a structural fact about a
real named person, not under Phase G's ambiguity discipline) resolves
the id to a name via the existing live agent broadcast. `world.fields`
and the graph algorithms module stay dev-console-invisible for now
(no diagnostics field added) — nothing yet needs to inspect the raw
grid; `population_density`'s only visible effect is fission-site
behavior, same as any other deterministic mechanic.

This closes roadmap Stage I ("Senses & substrate") — all three steps
shipped (v1.4.8-v1.4.9). Stage II (the five-pillar refactor) is the
first real consumer of `emergence_log`/`fields`/graph algorithms
together; work from it only on future explicit direction.

Verified: direct smoke tests (`FieldGrid` region bucketing/step/round-
trip, `graph_algorithms` centrality/tie-breaking/isolated-node
handling, `_detect_social_hub`'s edge-triggering + round-trip
persistence, a real engine tick confirming `population_density`
populates). `scripts/verify_native_soak.py` (2 seeds x 800 ticks, plus
a longer single-seed run crossing a real season boundary to exercise
`_detect_social_hub` in the live tick loop) — byte-identical.

## [1.4.8] — A22 "The Emergence API" (roadmap Stage I, step 1)

Explicit user request: "Start step 1: the Emergence API" — the first
concrete implementation step off v1.4.7's roadmap
(docs/MASTERCHECKLIST-2026-07-22.md). A22 asks for a per-subsystem
structured observation stream from the deterministic Body — anomalies,
novel combinations, bottlenecks, unexplained shifts, opportunities —
tagged by which future cognitive pillar (humans/village/nature/
innovation/reflection) would care, ahead of any pillar actually
consuming it ("build the sense organ before the mind that uses it,"
same sequencing `Population.voice_conversation` had before the voice-
pair feature read it).

New `hearthmind/world/emergence.py`: `OBSERVATION_KINDS`/`PILLARS`
closed vocabularies and `make_observation()`, a plain-dict factory
(same convention as `highlights`/`reflection_notebook` — no per-type
(de)serialization to maintain) that validates both vocabularies at
construction (`ValueError` on a bad call site, since this is an
internal producer contract, not user input). New `World.emergence_log`
(capped `EMERGENCE_LOG_MAX_STORED=500` — a busier future stream than
`highlights`' 30, but still small dicts) + `World.next_emergence_id`,
wired into `to_dict`/`from_dict`; `World.emergence_log_recent()`
mirrors `knowledge_tree()`/`causal_threads_list()`'s newest-first
on-demand shape.

Deliberately reused already-computed, already-edge-triggered signals
rather than building a new scanning system: `SimulationEngine.
_append_highlight` now mirrors into `_append_emergence` for every
highlight kind with an entry in the new `_HIGHLIGHT_EMERGENCE_MAP`
(first_invention, era_advance, first_ritual, first_religion,
family_feud, successor_founded, extinction_near_miss,
population_anomaly — every existing highlight kind, each given a
kind/subsystem/pillar-tuple mapping); the reflection hypothesis
lifecycle (`_maybe_schedule_reflection`'s `apply` closure on formation,
`_append_reflection_conclusion` on confirm/refute) each emit one
observation; `_maybe_spread_concepts` emits `novel_combination` the
first tick an `InventedConcept`'s status transitions to `established`.
One genuinely new detector: `_detect_settlement_bottlenecks` (riding
`_log_daily_metrics`'s existing once-per-sim-day cadence, no new
polling loop) emits `bottleneck` the first day a settlement's
materials drop below `cheapest_founding_cost()` — the same bar
`cognition.py`'s per-agent `materials_critical` flag already uses, but
settlement-scoped and edge-triggered (`_materials_critical_flagged`,
a plain runtime set, never persisted) so it fires once on the crossing
and again only after a real recovery, not every day the settlement
stays poor.

`GET /emergence` (interface/app.py) + `WorldBroadcaster.
set_emergence_log_provider`/`get_emergence_log` (interface/api.py, same
on-demand-provider shape as knowledge-tree/causal-threads — up to 500
entries is too large for the per-tick WS payload, and nothing needs
sub-second freshness). UI surfacing: `full_diagnostics()` gained
`emergence_log_total`/`emergence_log_by_kind`/`emergence_log_recent`
(last 10, kind/subsystem/summary/pillars only) — the dev console's
existing "Full diagnostic report" button already dumps this raw, the
same reachability `reflection_notebook` has always had with no
dedicated panel; a stream with no consumer yet doesn't warrant a new
main-UI surface ahead of Stage II's pillar refactor actually reading
it.

No pillar reads `emergence_log` yet — that's Stage II of the roadmap.
Verified: direct smoke tests (`make_observation` kind/pillar
validation + magnitude clamping; `_append_highlight`→`_append_emergence`
mirroring including a non-mapped highlight kind correctly emitting
nothing extra; the 500-entry cap; `emergence_log_recent`'s newest-first
ordering; `to_dict`/`from_dict` round-trip; the bottleneck detector's
edge-triggering — fires once on crossing, silent while still critical,
clears on recovery without emitting again). `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — no native module
touched, but `_append_emergence`/`_detect_settlement_bottlenecks` run
inside/adjacent to the tick loop.

## [1.4.7] — File the Master Checklist (Body/Mind/Seam audit) + a 30-step implementation roadmap

Explicit user request: add an uploaded consolidated audit doc,
"Hearthmind — The Complete Master Checklist," to the project docs, and
produce a concrete implementation roadmap (sequence + step count) for
it. Docs-only — no code changed.

The checklist covers three parts against v1.4.1: **Part A**, the
deterministic "Body" (25 systems from an external `det_sys.md` — fields,
CA/diffusion, procgen-as-runtime, affordances, materials, chemistry,
genetics, graphs, information ecosystems, the Emergence API, etc.);
**Part B**, the cognitive "Mind" (9 items from an external `LLM_
Pillars.md` — five persistent pillars: Humans/Village/Nature/
Innovation/Reflection, each with identity/self-model/world-model/
memory/attention); **Part C**, the "Seam" (5 items — how Mind perceives
and reshapes Body without violating it). Headline finding: most of
today's Body systems are generated-once-at-creation and static/random-
walk thereafter (rivers carved once, a 9-region climate grid not
per-tile fields, no material/affordance/genetics/chemistry model) —
det_sys.md's "procedural generation as continuous runtime, not a
world-gen step" is the through-line gap across nearly every PARTIAL
item.

Filed verbatim as `docs/MASTERCHECKLIST-2026-07-22.md`, same convention
as every other externally-submitted vision/audit doc this project
keeps (docs/IDEAS-2026-07-EMERGENCE.md, docs/VISION-2026-07-21-
SELFEVOLVING.md, docs/VISION-2026-07-22-LIVINGTERRARIUM.md, docs/
DEFINITIVECHECKLIST-2026-07-21.md). New "Implementation roadmap"
section appended to the same file: the doc's own 4-phase thematic
SEQUENCE (senses/substrate → five minds → interaction → deepen the
Body) is broken into **30 concrete, independently-shippable steps** —
Stage I (senses & substrate, 3 steps: Emergence API, FieldGrid, graph
algorithms) → Stage II (the five minds, 6 steps, Nature first) → Stage
III (player-facing + interaction, 5 steps) → Stage IV (deepen the
Body, 16 steps, ordered by leverage — hydrology first, temporal-
compression pipeline last). 5 of the checklist's 39 items (A9/A23/A24/
A25/C4) are standing review-time discipline folded into every step
rather than separate line items, hence 39 checklist items → 30 build
steps. One design decision flagged as blocking only Stage III's step
14 (Humans collective vs. individual-NPC disagreement in dialogue),
not any earlier step. A short CLAUDE.md pointer entry added alongside
the doc's other vision-doc pointers, same "work from it only on future
explicit direction naming a specific step" standing rule as every
other filed vision doc — this pass is planning/filing only, nothing
implemented.

## [1.4.6] — Widen voice_conversation's retention cap so the repetition backstop actually reaches

Explicit user follow-up on v1.4.5, off a fresh `/diagnostics` +
dialogue log: self-naming is fixed (confirmed absent across the whole
log) and `calls_errored`/`calls_timed_out` both stayed low/zero — but
exact-line repeats were still visible ("Wilhelmina: 'Is that so.'"
recurring, "then we'll dream it real, don't we?" recurring), even
though v1.4.5's dedup backstop is running.

Root cause: `dialogue._is_near_duplicate_line` only ever checks
against what's still IN `Population.voice_conversation`'s ring, capped
at `MAX_VOICE_CONVERSATION_STORED=24`. The reported repeats recurred
~650 ticks apart — at the voice pair's fastest cadence (`VOICE_
DIALOGUE_COOLDOWN_TICKS=5`) that's 100+ exchanges, meaning the earlier
occurrence had long since been evicted from a 24-entry ring by the
time the repeat happened; the backstop was working exactly as coded,
its lookback window was just too short to ever catch a repeat that far
apart. Fixed by raising `MAX_VOICE_CONVERSATION_STORED` 24 -> 220 —
comfortably covers 1000+ ticks of continuous fastest-cadence exchanges
before evicting anything, at negligible memory cost (small dicts, a
capped list, no LLM cost either way since the PROMPT itself still only
ever reads the newest `VOICE_CONVERSATION_HISTORY_TURNS` (6) — only
the backstop's own lookback widens).

Verified: `MAX_VOICE_CONVERSATION_STORED` constant check,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— no native module touched, and this constant only governs how much
of an already-deterministic Python list gets retained.

## [1.4.5] — Fix voice-pair repetition attractor and self-name addressing

Explicit user follow-up after v1.4.4 made the voice pair's dialogue
visible in the UI for the first time: reading the actual conversation
history showed two real quality bugs — the pair converges onto a
handful of images/complaints and recites them near-verbatim many
exchanges apart ("Ash still smells like home, Osric." repeated
verbatim 5+ times across a ~500-tick span; "Cold bread? I'm already
cold from the wind." similarly), and a speaker sometimes addresses
THEMSELF by name mid-line (Osric saying "...Osric" about himself,
Liora saying "...Liora" about herself) rather than only ever naming
the other person.

**Repetition.** No novelty/dedup check existed for voice-pair lines at
all — `_run_dialogue`'s `is_spreading_tic` (tail-fingerprint check
across DIFFERENT speakers) was never wired into `_run_voice_dialogue`,
and there was nothing checking a speaker's line against their OWN
prior lines either way. Root cause: the voice pair's frequent cadence
(`VOICE_DIALOGUE_COOLDOWN_TICKS=5`) plus a small model repeatedly
handed similar internal-state/town-digest input converges onto the
same few images rather than writing something new each time — the
exact "small model re-condenses the same idea when shown similar
context" shape `FOLKLORE_DUPLICATE_OVERLAP` already fixed for monthly
tale-telling (v1.3.2), just for this much higher-frequency job. Two-
part fix, same "prompt hint + deterministic backstop" pattern as that
earlier fix: `VOICE_SYSTEM_PROMPT` now explicitly tells the model not
to repeat an image/complaint it's already used; new `dialogue.
_is_near_duplicate_line`/`VOICE_LINE_DUPLICATE_OVERLAP=0.6` (Jaccard
word overlap, stdlib only) is the deterministic backstop for when a
weak model doesn't comply — checked per speaker against the FULL
stored `Population.voice_conversation` ring (up to `MAX_VOICE_
CONVERSATION_STORED=24` lines), not just the ~6 turns fed into the
prompt itself, since the live-reported repeats recurred well outside
that shorter prompt window. A near-duplicate degrades only THAT one
side to the deterministic fallback pool — the other speaker's
(presumably still-novel) line is kept, rather than discarding the
whole exchange the way `_is_sane_line` failures already do.

**Self-naming.** `VOICE_SYSTEM_PROMPT` now explicitly says a speaker
may name the OTHER person but must never say their own name — a real
person doesn't call themself by name mid-sentence. New `dialogue.
_strip_self_address(line, own_name)` is the deterministic backstop:
strips a clear vocative use of the speaker's own name (immediately
after/before a comma — "...we were, Osric." or "Osric, I still...")
while leaving the OTHER speaker's name and any non-vocative substring
occurrence untouched. `parse_voice_dialogue` gained optional
`speaker_a_name`/`speaker_b_name`/`recent_lines_a`/`recent_lines_b`
params (backward compatible — all default to empty/`None`, a no-op)
wired at the one call site, `SimulationEngine._run_voice_dialogue`.

Verified: direct unit tests (trailing/leading self-vocative stripping,
the other speaker's name staying untouched, near-duplicate detection
on both an exact repeat and a light paraphrase while sparing a genuine
novel line, and an end-to-end `parse_voice_dialogue` check confirming
a repeated line degrades to fallback on only its own side while the
novel side survives). `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — no native module or persisted field touched.

## [1.4.4] — Fix timeout misclassification/truncation on reasoning calls; visible voice-pair dialogue; deep-reasoning diagnostics

Explicit user follow-up on v1.4.3, with a fresh review pack + `/diagnostics`
attached: reasoning calls were still failing, no voice-pair dialogue was
visible anywhere in the UI, and some completions looked truncated
mid-sentence. Four real bugs found and fixed, none of them the same
bug as v1.4.3's fix (which genuinely worked — `calls_errored` in the
new diagnostic was 2/313, not the near-100% of before).

**Timeout misclassification (the "is timeout playing a role" question).**
`LlamaCppClient`/`OllamaClient.generate_json` open the HTTP request
with `urlopen(request, timeout=self.timeout_seconds)`; `jobs.py`'s
`CognitionRunner._run_gated` separately wraps the whole call in
`asyncio.wait_for(..., timeout=self.client.timeout_seconds + 5.0)` as
"defense in depth." Since the inner socket timeout is strictly smaller
than the outer one, the inner timeout ALWAYS fires first — and it
raised plain `LLMUnavailable`, landing in `calls_errored`, not
`calls_timed_out`. The `calls_timed_out` counter has read 0 in every
diagnostic this project has ever produced; it was structurally
incapable of ever incrementing. New `client.LLMTimeout(LLMUnavailable)`
raised specifically on a socket-level timeout (`TimeoutError`, or a
`URLError` whose `.reason` is one); `jobs.py` now catches it before the
generic `LLMUnavailable` and counts it correctly.

**Reasoning calls genuinely needed a longer timeout.** The new
diagnostic's `personal_belief` (a `deep_reasoning=True` task) showed
p95 latency 146.7s against an un-scaled 125s timeout (120s config + 5s
grace) — the socket timeout was cutting off calls that were still
legitimately generating a `<think>` trace plus an answer, not stuck.
New `DEEP_REASONING_TIMEOUT_MULT=1.5` (`simulation/engine.py`, mirrors
`DEEP_REASONING_NUM_PREDICT_MULT`'s own ratio) scales the timeout in
step with the already-scaled token budget whenever `reasoning=True`;
both clients' `generate_json` and `CognitionRunner.run`/`_run_gated`
gained a `timeout_override` param threaded end to end.

**Truncation.** A `json_schema`'s `maxLength` is enforced by the
sampler at the character level — the grammar force-closes the JSON
string (and the object around it) the instant the cap is hit, with no
chance for the model to finish its sentence. Both diagnostics showed
this exact shape (`mind.voice` ending "...a whisper that remains, a
rhythm," `chronicle.summary` ending "...ends not with fanfare but
with"), both landing within a couple characters of that field's
`maxLength`. New `client._trim_truncated_string`/`_trim_truncated_
strings`: only touches a string field whose length is at/near its
schema's declared cap, trimming back to the last complete sentence (or
the last complete word before a dangling comma fragment if no sentence
exists) — applied to every schema-constrained call's parsed result in
both clients.

**"No dialogue at all" — a real UI bug, not a backend gap.** The
attached diagnostic's own `event_category_counts` showed `dialogue:
137` and `voice_dialogue` (the LLM task) calls succeeding fine — the
voice pair WAS talking. The bug: since v1.4.0's redesign, `is_llm` in
`_apply_pending_dialogue_results` can only ever be the one dedicated
voice pair (every other pair resolves through the always-`is_llm=False`
deterministic path), but the category logic still gated visibility on
`surfaced` (a rumor/relationship-threshold flag) — an ordinary
voice-pair line that didn't cross that threshold logged under the
plain `dialogue` category, which is `skip: true` in `app.js` (a
holdover from when many core-cast pairs produced real LLM chatter and
most of it needed hiding). The pair's actual conversation — the whole
point of the feature — was invisible in the main event feed unless a
line happened to also cross the surfaced threshold. Fixed: an ordinary
voice-pair line now logs under a new, visible `voice_dialogue`
category (💬); `dialogue_surfaced` (💬✨) still marks the stronger case.
`app.js`'s thought-flash map marker (a brief pulse over a core-cast
agent on a genuine LLM exchange) updated to match.

**Deep-reasoning diagnostics, per explicit request.** `CognitionRunner`
gained `reasoning_calls_attempted/succeeded/timed_out/errored` plus a
reasoning-only latency percentile window, surfaced as a new `reasoning`
sub-object in `llm_stats` (`/diagnostics`); `_last_llm_calls` and
`llm_prompt_stats` entries now carry a `reasoning: bool` tag so a
reasoning-specific failure is traceable per-task, not just in the
aggregate.

Verified: direct unit tests for `LLMTimeout` classification (socket
timeout vs. connection-refused vs. generic failure), `timeout_override`
reaching the request, `_trim_truncated_string`/`_trim_truncated_
strings` (sentence-boundary trim, dangling-fragment trim, only-near-cap
gating), the voice-pair dialogue category fix (an `is_llm=True` queued
result now logs `voice_dialogue`/`dialogue_surfaced`, never the hidden
`dialogue`), and the reasoning load-shed/timeout-scaling interaction
end to end through `_schedule_llm_job`. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — no native module or persisted
field touched.

## [1.4.3] — Fix reasoning-mode calls erroring out; dynamic/load-aware reasoning toggle

Explicit user follow-up on v1.4.2: a fresh review pack + `/diagnostics`
showed calls STILL erroring after that fix — this time `calls_errored`
5/5 (100%) on the `mind` task specifically, a task that has never been
`deep_reasoning=True`. Avg latency for those calls was ~114s against a
measured ~11.24 tok/s decode rate — roughly 1280 tokens generated
against a 512-token `max_tokens` request, i.e. the model was still
generating well past its budget with no JSON ever produced.

Root cause: `scripts/run.sh`'s `LLAMA_REASONING=auto` (the v1.3.37
default) leaves the server's reasoning budget open for every call: the
app's own per-call "detailed thinking off" system-prompt phrase is
only a soft hint, and this model does not reliably honor it — it kept
generating an (unclosed, budget-exhausted) `<think>` trace even for
routine, non-`deep_reasoning` tasks, so `content` never contained an
answer at all. `_THINK_BLOCK_RE` only ever matched a *closed*
`<think>...</think>` pair, so a truncated trace reached `json.loads`
whole and failed every time. Both LLM clients (`hearthmind/llm/
client.py`) now assert `reasoning=False` at the REQUEST level, not
just the prompt level — `LlamaCppClient` sends `reasoning_budget: 0` +
`chat_template_kwargs: {"enable_thinking": false}` (llama-server's
per-request equivalent of the already-proven `--reasoning-budget 0`
CLI flag; both fields are additive/ignored if the server build doesn't
recognize them) whenever `reasoning=False`, which is sampler-enforced
rather than merely requested — this is the actual fix. New `_UNCLOSED_
THINK_RE` strips a dangling, never-closed `<think>` block (applied
only when `_THINK_BLOCK_RE` finds no closed pair) as defense-in-depth
for any server/model combination where the per-request override is a
no-op — the completion still fails cleanly as `LLMUnavailable`/
fallback (there genuinely is no answer in a truncated trace), just
without dumping a multi-hundred-token half-finished reasoning trace
into the error message.

Second, explicit user directive: reasoning is expensive (several times
a routine call's latency) and should be reserved for genuinely crucial
tasks, dynamically shed under load rather than either a global on/off.
New `REASONING_LOAD_SHED_RATIO=0.9` (`simulation/engine.py`) —
`_schedule_llm_job`'s `reasoning` computation now also requires `llm_
pressure_ratio() < REASONING_LOAD_SHED_RATIO`; a `deep_reasoning=True`
job whose queue is already backing up runs WITHOUT a trace that one
call (same fast path as every routine task) instead of deferring or
dropping — the decision still gets made, just without the extra cost,
shedding load at exactly its most expensive point, before `LLM_
PRESSURE_SLOWDOWN_START_RATIO` (0.75) pacing or `LLM_PRESSURE_PAUSE_
RATIO` (2.0) even engage. `scripts/run.sh`'s `LLAMA_REASONING` doc
comment rewritten to describe both the server-wide ceiling and the new
per-request/per-load override together, since a reader tuning one
without knowing about the other would draw the wrong conclusion about
what each lever actually controls.

Verified: direct unit tests (`reasoning=False` sends the request-level
override, `reasoning=True` omits it and keeps the server default;
closed vs. unclosed `<think>` blocks parse correctly on both clients;
`_schedule_llm_job` keeps `reasoning=True` under low `llm_pressure_
ratio()` and drops to `False` under high pressure even with `deep_
reasoning=True`, and a routine non-`deep_reasoning` job never gets
`reasoning=True` regardless of pressure), `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — no native module or
persisted field touched.

## [1.4.2] — Fix voice_dialogue's missing JSON schema; harden JSON extraction against wrapped completions

Live-diagnostic-driven fix: a pasted `/diagnostics` snapshot showed
`llm_stats.calls_errored` at 50% (6 of 12 attempted) on the voice
pair's own call (now the highest-volume task after v1.4.1's cooldown
drop to 5 ticks), plus one successful "mind" call whose `voice` field
came back containing visible leaked reasoning text ("speaks in short,
plain sentences 12 words? Actually voice field is ").

Root cause of the error spike: `_run_voice_dialogue` was the one
dialogue-shaped LLM call site never given a `json_schema` — every
other schema-eligible task (`cognition`, `dialogue`, `mind`, ...) went
through FT.0's grammar-constrained decoding (structurally guaranteed
valid JSON at the sampler level), but `voice_dialogue` didn't exist
yet when that schema set was built and was left unconstrained,
free-generating on a model that (per the "mind" evidence) doesn't
reliably keep meta-commentary out of its answer even when explicitly
told "detailed thinking off." New `"voice_dialogue"` entry in
`llm/json_schemas.py` (line_a/line_b/sentiment/topic, mirroring
`"dialogue"`'s shape at the wider `VOICE_MAX_LINE_CHARS`), wired into
`_run_voice_dialogue`'s `_cognition_runner.run(json_schema=schema_for_
task("voice_dialogue"))` call.

Defense in depth for every remaining unconstrained task (`beliefs`/
`personal_belief`, and anything future): `llm/client.py`'s new
`_extract_json_object()` — when a raw completion isn't itself valid
JSON, retries with the substring from the first `{` to the last `}`
before giving up. Recovers a completion wrapped in stray prose
("Sure, here's the JSON: {...}") or a markdown code fence that a
grammar-less small model occasionally emits despite the system
prompt's explicit instruction not to — a no-op for the already-common
case of a bare JSON response. Wired into both `OllamaClient` and
`LlamaCppClient`'s final parse step, tried only after the plain
`json.loads` has already failed once.

The garbled-but-schema-valid "mind" content itself (a call that
technically succeeded, `additionalProperties: False` + grammar
correctly enforced the shape) is a separate, harder problem — the
model producing low-quality-but-structurally-valid string content —
not something a schema or JSON-extraction fix can address; flagged as
a live model-quality observation, not a bug fixed here.

Verified: direct test of `_extract_json_object` against bare/prefixed/
code-fenced/unparseable inputs, `scripts/verify_native_soak.py` (2
seeds × 800 ticks) byte-identical (no native module touched, but the
LLM-call path runs on every schedule regardless of LLM enablement).

## [1.4.1] — Shifting protagonists: narrative-significance-driven voice pair rotation

Explicit user follow-up on v1.4.0's voice pair: trigger far more often
("every 5 ticks or something like that"), and rotate WHO the pair is
roughly weekly, driven by narrative significance rather than fixed
prominence — "some weeks the mayor dominates, other weeks it's a
grieving parent, later an inventor, a rebel, or a council elder... a
simulation with shifting protagonists rather than permanent stars."

**Cadence**: `VOICE_DIALOGUE_COOLDOWN_TICKS` 60 -> 5.

**Narrative-significance scoring**: new `Population._narrative_
significance(agent, extra_scores)` — a `_prominence` baseline (so an
otherwise-quiet week still favors an established figure) layered with
real event bonuses: `NARRATIVE_GRIEF_BONUS` (dominant emotion is
grief — "a grieving parent"), `NARRATIVE_EMOTION_BONUS` (any other
dominant emotion), `NARRATIVE_REBEL_BONUS` (an active hardened feud in
`Agent.relationship_flags` — "a rebel"), and `NARRATIVE_EXTREME_EVENT_
WEIGHT` × `Agent.extreme_event_count` (Phase 3.B's disaster-survival/
feud/widowhood tracker — a life visibly marked by extreme events).
`extra_scores` (an `{agent_id: bonus}` dict) carries the two signals
that live outside `Population` — a recent invention (`World.invented_
concepts`, `VOICE_NARRATIVE_INVENTOR_BONUS`, ~a season's recency
window) and active COUNCIL membership (`VOICE_NARRATIVE_COUNCIL_
BONUS`, "a council elder") — both computed by the new `SimulationEngine.
_voice_narrative_extra_scores()` since `Population` deliberately
doesn't reference `World`/`Settlement`.

**Selection**: `select_voice_pair` now picks this week's "protagonist"
(highest narrative significance) then partners them with their
strongest bond among the remaining core cast (falling back to the
next-highest-significance candidate if they have no such bond) —
reusing a new shared `_strongest_core_bond` helper also used by the
existing death-triggered rotation.

**Weekly rotation**: `maintain_voice_pair` gained `week_rotation: bool`
— the engine passes `"week_end" in events` (the calendar boundary
`SimClock` already computes) alongside `extra_scores`, forcing a fresh
`select_voice_pair` reselection even when the current pair is still
alive. No forced "never repeat" rule: if the same pair genuinely
remains the town's liveliest story, they stay — a no-op reselect isn't
treated as a change (no spurious `voice_pair_change` event/thread
reset). Death-triggered rotation (survivor's strongest bond, fresh
pair if both die) is unchanged.

Verified: direct smoke test (baseline prominence tie -> grief bonus
promotes the grieving agent -> partnering picks their strongest bond
-> week_rotation reselecting the same winner is a no-op -> an
inventor's extra score wins the next week's rotation),
`scripts/verify_native_soak.py` (2 seeds × 800 ticks) byte-identical.

## [1.4.0] — The voice pair: LLM dialogue narrowed to one deep, continuing conversation

Explicit user directive: disable LLM dialogue for every NPC pair except
exactly ONE fixed core-cast pair, and spend the freed-up budget making
that one pair's conversation genuinely deep — longer lines, real
continuity across calls (each reply picks up from what was just said,
not a fresh small-talk opener), grounded in a concise town summary and
each speaker's own internal state. Rotates to a new pair on death. All
other dialogue (the vast majority) stays deterministic-only, same as
it's always been for non-core pairs — unchanged mechanically, just no
longer LLM-eligible even for a core-core pairing that isn't the voice
pair.

**`Population.voice_pair_ids`** (a fixed `(agent_id, agent_id)` tuple,
persisted): the sole LLM-dialogue pair. `select_voice_pair` picks the 2
most prominent living core-cast members (reuses `_prominence`, the
same ranking `maintain_core_cast` already uses); `maintain_voice_pair`
(called every tick, cheap no-op unless something changed) rotates to
the survivor's strongest remaining core-cast bond if one dies, or picks
an entirely fresh pair if both do — logged as a `voice_pair_change`
event, surfaced with a new 🗣 icon. A pair change clears `voice_
conversation` (a new partner has no business continuing the old
thread).

**`due_for_dialogue` simplified**: no longer partitions core-core vs.
crowd pairs — every colocated pair (including former core-core ones)
now resolves via the deterministic fallback, EXCEPT the exact voice
pair, which is excluded here and scheduled separately via the new
`due_for_voice_dialogue` (its own `VOICE_DIALOGUE_COOLDOWN_TICKS=60`,
far shorter than the ordinary 300 — "call often," since this is now
the only pair spending LLM budget at all). `MAX_LLM_DIALOGUES_PER_TICK`
and the now-dead `_is_significant_pair` LLM-slot prioritizer are
removed — no longer meaningful once there's only ever one LLM-eligible
pair.

**New `llm/dialogue.py` voice-mode prompt/parse path**
(`VOICE_SYSTEM_PROMPT`/`build_voice_prompt`/`parse_voice_dialogue`/
`fallback_voice_dialogue`), deliberately separate from the ordinary
`build_prompt`/`parse_dialogue` (tuned for brief small talk between
people who may barely know each other) rather than a mode flag on it:
- `VOICE_MAX_LINE_WORDS=40` (vs. 26 for ordinary dialogue) — real
  conversation between two people who know each other runs longer.
- `conversation_so_far`: the pair's last `VOICE_CONVERSATION_HISTORY_
  TURNS=6` lines (`Population.voice_conversation`, a new persisted
  ring, `MAX_VOICE_CONVERSATION_STORED=24`), fed back so the model
  continues the actual thread instead of reopening small talk each
  call — the system prompt explicitly instructs this.
- `town_digest`: one concise sentence (current town-brain priority +
  population/season) — deliberately NOT the full grounding apparatus
  (opportunities/beliefs/lexicon/place-names/etc.) ordinary dialogue
  uses, per the explicit "very concise summary" request.
- `internal_state_a`/`_b`: each speaker's own hunger/energy/current
  goal/emotion, one line each.
- The model is never asked for the Phase-2 structured-outcome fields
  (promise/debt/secret/misunderstanding/goal_change) — `parse_voice_
  dialogue`'s return dict carries them at inert defaults so it's a
  drop-in for the SAME shared `_apply_pending_dialogue_results`
  pipeline ordinary dialogue already uses (is_llm-gated event
  surfacing, topic-ring recording, cross-settlement relation nudge —
  reused unchanged, not duplicated).

New `SimulationEngine._schedule_voice_dialogue`/`_run_voice_dialogue`
(mirrors `_schedule_due_dialogue`/`_run_dialogue`'s shape, backpressure/
budget-exhausted ticks degrade to the deterministic fallback same as
every other LLM job) records both lines into `voice_conversation`
regardless of whether the result later resolves via fallback, so the
thread itself always remembers what was actually said.

"Only surface these dialogues in events" was already structurally true
before this change (the `is_llm` event-surfacing gate, v0.73.0) — with
LLM dialogue now concentrated on exactly one pair, this guarantee is
simply sharper: the `dialogue`/`dialogue_surfaced` event categories now
mean, specifically, this one pair's real conversation.

Verified: direct smoke test (initial pair selection, maintain no-op on
an unchanged pair, death-triggered rotation to the survivor's strongest
bond, prompt/parse round trip including a too-long-line rejection),
`scripts/verify_native_soak.py` (2 seeds × 800 ticks) byte-identical.

## [1.3.41] — Living Terrarium batch: laws-of-nature panel, causal threads, time-lapse knowledge counter, ambient seasonal presence

Explicit user follow-up ("Yes do that") on the four items deferred from
v1.3.40 as UI-heavy: 1.5, 3.3, 3.5, 3.6.

**1.5, a visible "law of nature" ontology.** New "⚖ laws of nature"
panel — a filtered, reformatted view over the existing `/knowledge-tree`
data (rule/law/custom/taboo entry types), foregrounding each rule's
real trigger→effect and a "validated"/"untested" badge read from
`TriggerRule.fire_count` (and the secondary side's own last-fired
tick). `World.knowledge_tree()`'s `rule` entries gained `hook_type`/
`fire_count`/`secondary_trigger`/`validated` fields to support this —
"validated" means it has actually fired at least once, never that it's
objectively true, matching the doc's own "some true, some superstition
the sim never validated" framing.

**3.3, legible causal threads (scoped).** A fully generic event-graph
(every event linked to its real cause) would need every event-emission
site threaded with stable ids — out of scope for one batch. Scoped
instead to the one call site that already computes real grounding
facts for a dispute outcome: `_maybe_schedule_dispute`'s apply() now
captures the same souring-level/debt/rival-faction/rival-family/
reputation-gap/law facts already used to build the LLM prompt into a
new `world.ontology.CausalThread` (feud/ostracism/council_ruling
outcomes only — a plain reconcile has no rupture worth tracing). New
`World.causal_threads`/`causal_threads_list()`, `GET /causal-threads`,
and a "🔗 causal threads" panel — click through and see why a feud
actually formed, not just that it did.

**3.5, time-lapse and the returning eye (scoped).** The map-scrubber/
replay/year-reel-export machinery was already fully shipped (v0.65.0,
§5); the new piece is "watch the law-book thicken." Since knowledge-
tree entries are permanent and only ever grow, "how many things were
known as of tick X" is honestly reconstructable from the CURRENT full
tree by counting entries with origination tick `<= X` — no new
per-tick history needed. `loadTimelineIndex` fetches the tree once per
timeline session; `loadTimelineTick` now shows a live "🌳 N things
known so far" line via a binary search over the sorted tick list,
updating as you scrub or replay.

**3.6, ambient generative presence (scoped).** The soundscape half was
already substantially shipped (§6, keyed to weather/night/
temperament); this pass adds Nature's Mind's own strongest-belief
confidence as one more subtle input (a small filter-cutoff nudge) and
ships the genuinely new piece — a faint seasonal color-grade over the
map (`#season-vignette`, a CSS radial-gradient overlay keyed to
`summary.season`, darkening toward winter and lightening through
spring/summer) so the world visibly darkens ahead of a hard winter
without any text announcing it. Era-styled cartography itself was
already shipped (§5 item 5).

Verified: `python3 -c "import hearthmind.simulation.engine; import
hearthmind.interface.app; import hearthmind.interface.api"`, `node
--check app.js`, direct round-trip tests for `CausalThread` and
`TriggerRule.fire_count`, `scripts/verify_native_soak.py` (2 seeds ×
800 ticks) byte-identical.

## [1.3.40] — Living Terrarium batch: composable hooks, species variants, coherence detection, provenance + 4 audit follow-ups

Explicit user request ("Start all of that") over the remaining Living
Terrarium vision-doc items plus four flagged follow-ups from the
v1.3.38 cognition-architecture audit. Scoped down from the full list
(1.1, 1.5, 3.3, 3.5, 3.6, 4.2, 5.3, 5.4 + 4 audit items) to the
backend/data-model-tractable half — 1.5 (visible "law of nature"
ontology), 3.3 (legible causal threads), 3.5 (time-lapse/returning
eye), and 3.6 (ambient generative presence) are all real UI-heavy
efforts better done as their own dedicated batch, deliberately
deferred rather than rushed. See docs/VISION-2026-07-22-LIVINGTERRARIUM.md
for each shipped item's own scoping note.

**1.1, composable hooks (scoped).** A full boolean/AND-NOT combinator
grammar over trigger *state* would need new trigger-recency
infrastructure; shipped a bounded, testable slice instead — a
`TriggerRule` may now bind a SECOND, independent (trigger, hook) pair
alongside its primary one (`ontology.TriggerRule.secondary_trigger`/
`secondary_hook_type`/`secondary_hook_target`/`secondary_magnitude`/
`secondary_last_fired_tick`, each side its own cooldown).
`llm/rule_propose.py`'s prompt/schema/parser extended to let the LLM
propose the secondary side (optional — defaults to empty rather than
falling back to a substitute, since there's nothing to preserve the
weight of for an optional field). `retire_stale_rules` now counts
either side firing as "ever fired."

**4.2, emergent species/variants (scoped).** New `world/wildlife.
SpeciesVariant` registry (id/name/species/herd_id/trait/description)
+ `SPECIES_VARIANT_TRAITS` closed vocabulary (hardier/migratory/timid/
aggressive/prolific) + `llm/species_variant.py` +
`_maybe_schedule_species_variant` (year_end cadence, one un-named
existing herd per firing). Deliberately identity/narrative-only —
`AnimalHerd` has C++-native-index parity requirements (R7); wiring a
variant-conditional numeric stat delta into the native wildlife tick
risks native/fallback divergence and is flagged as real follow-up
work, not silently dropped.

**5.3, coherence/drift detection (scoped).** `_detect_reflection_
pattern` gained an "ontology coherence" branch: once
`REFLECTION_COHERENCE_MIN_TOTAL` (10) concepts exist and
`REFLECTION_COHERENCE_ABANDONED_RATIO` (0.5) of them were abandoned,
this becomes a real Reflection hypothesis through the existing
pipeline. `self_tuning.TUNABLE_GOVERNORS` gained `"ontology
coherence" -> "ontology_proposal_chance"`, consumed as a multiplier
on `_maybe_schedule_ontology_proposal`'s chance calc — a confirmed
hypothesis can genuinely slow the world's own rate of new-concept
proposals. The semantic/qualitative half ("culture drifted into
nonsense") is NOT attempted — needs its own LLM judgment call,
flagged as follow-up.

**5.4, provenance for everything.** `World.knowledge_tree()`'s
entries already carried tick/status/lineage; every entry now also
carries a `"who"` field — a real living agent's name where one
genuinely exists (a concept's inventor, a law's proposing
settlement), a fixed attribution for non-agent origins ("the land
itself" for Nature's beliefs/species variants, "Hearthmind's own
reflection" for hypotheses/conclusions/questions, "Hearthmind itself"
for self-tuning actions), or "the village" where authorship is
genuinely collective. Surfaced in the existing knowledge-tree panel
(`app.js`'s `renderKnowledgeTreeEntry`) — no new panel needed, the
vehicle already existed.

**Audit follow-up: reflection `kind="question"`/`"conclusion"`
entries.** `_reevaluate_reflection_hypotheses` now appends a
deterministic, zero-LLM-cost `kind="conclusion"` notebook entry
(`status="confirmed"`/`"refuted"`, `supersedes` the hypothesis id) at
the exact moment a hypothesis transitions to supported/rejected — a
rejected hypothesis's refutation is now itself a permanent knowledge-
tree entry, not silent. `_maybe_schedule_reflection`'s "pattern
already has an open hypothesis" branch — previously a bare skip —
now asks a genuine open QUESTION about that hypothesis instead
(new `llm/reflection.py` `SYSTEM_PROMPT_QUESTION`/`build_question_
prompt`/`fallback_question`/`parse_question`, new `_maybe_schedule_
reflection_question`) — same year-cadence call slot, zero added LLM
volume.

**Audit follow-up: plan-fulfillment judgment.** `Population.
tick_plans()` previously let an expired `Agent.plan` silently vanish
with no fulfilled/abandoned judgment. Now writes a real memory on
expiry: "a plan resolved (pursued)" if `progress_note` was ever set
during the plan's life, "a plan resolved (abandoned)" if the plan had
a real intent but no progress was ever logged.

**Audit follow-up: relationship-weighted SOCIALIZE targeting.**
`Population`'s SOCIALIZE goal previously picked the plain-nearest
other agent, regardless of any actual relationship — "judgment call
dressed as a heuristic." New `_nearest_liked_agent` (`SOCIALIZE_
RELATIONSHIP_RADIUS=12`, `SOCIALIZE_DISTANCE_PENALTY=0.02`) scores
candidates within radius by `relationship - distance * penalty`,
falling back to the old plain-nearest behavior when the agent has no
relationships yet or none are in range.

**Audit follow-up: genesis-time `Agent.long_term_goal` seeding.**
`llm/mind.py`'s one-time permanent-identity prompt (`_author_one_
mind`, core cast only, fired once per agent's life) now also asks for
an `initial_goal` — new `parse_initial_goal` is deliberately
fallback-less (unlike mind/voice): a missing/empty answer just means
no goal is seeded yet, and the existing monthly life-event-gated job
still forms one naturally later. Applied only when `target.long_term_
goal is None`, so it never overwrites a goal that already formed
some other way, and only on a genuine (non-fallback) LLM answer.

Verified: `python3 -c "import hearthmind.simulation.engine"` after
every edit; `scripts/verify_native_soak.py` (2 seeds × 800 ticks)
byte-identical, run twice across this batch.

## [1.3.39] — Living Terrarium items 4.1/4.3: composite entities + generated sigils

Explicit user request: implement items 4.1 and 4.3 from
docs/VISION-2026-07-22-LIVINGTERRARIUM.md ("New entities and assets,
not just concepts").

**4.1, composite entities from existing primitives:** new `world.
ontology.CompositeEntity` — mechanically nothing more than one real
standing `Building` (unchanged kind/stats — never a new `BuildingKind`)
bound to one real `InventedConcept` via a name and an origin story, the
doc's own "Sorrow-Hall" example (a memorial-shaped building + an
institution_flavor concept, the entity is the sum). New `llm/composite_
entity.py` (same closed-category/hook-vocabulary shape as `llm/
ontology.py`/`llm/rule_propose.py` — a category from `ONTOLOGY_
CATEGORIES`, an optional bounded mechanical hook via the existing
`validate_hook`). `SimulationEngine._maybe_schedule_composite_entity`
(seasonal, round-robin settlement via `_job_target`, `critical=False`
with a real deterministic fallback name) finds the oldest standing
building in the settlement that no entity has named yet
(`_composite_entity_candidate_building`) and grounds the naming prompt
in the settlement's single most notable recent event. `World.
composite_entities` (capped, world-scoped like `invented_concepts`/
`trigger_rules`) also feeds `knowledge_tree()`.

**4.3, generative assets bound to emergent entities:** the parameterized-
SVG path the vision doc itself recommends starting with. New `world/
sigils.py`'s `generate_sigil_svg(name, category)` — fully deterministic
(hashes name+category into a palette/motif/rotation choice, no RNG
state, no LLM call, no heavy model), generated once at composite-entity
creation and stored on `CompositeEntity.sigil_svg`.

Surfaced main-UI (not dev-console — per the standing rule these are
meant to be discovered): the building click inspector shows a named
building's sigil, name, and origin story above the ordinary building
facts (`app.js`'s `renderTargetInspector`, new `latest.composite_
entities` broadcast field); `_diagnostics_snapshot`'s `composite_
entities_total` gives the dev console a raw count.

Verified: direct `_composite_entity_candidate_building` test (finds
the oldest unnamed standing building, correctly excludes an already-
named one on a second call); a direct end-to-end `_maybe_schedule_
composite_entity` test confirming the fallback path names a building,
registers a real `InventedConcept`, generates a sigil, and the entity
survives a `World.to_dict()`/`from_dict()` round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
(no deterministic tick-state code touched).

## [1.3.38] — Cognition-architecture audit + Living Terrarium items 2.2/3.4

Explicit user request: an audit focused on WHERE cognition should
live, not prompt wording — (1) text-only LLM calls that could update
persistent state, (2) deterministic judgment calls that could become
real LLM cognition, (3) opportunities to extend decision horizon
(plans/goals/experiments/belief revision) over more narration, (4)
fewer-but-more-meaningful calls whose output persists and conditions
later calls, (5) agents/settlement forming hypotheses and carrying
intentions across months/years. Plus: finish a few items from
docs/VISION-2026-07-22-LIVINGTERRARIUM.md.

A research pass across `simulation/engine.py` and every `llm/*.py`
module produced five sections of findings (full text kept in this
session's record, condensed here): confirmed `World.reflection_
notebook` is the only place with a real "am I right about this yet"
evidence loop; found several write-once/read-never LLM outputs
(`culture_digest`/`institution_culture`/`narrative_direction`,
`chronicler` Q&A); found `Agent.plan` silently expires with no
fulfilled/abandoned judgment; confirmed SOCIALIZE targeting and
`_maybe_assign_occupations` are judgment calls dressed as heuristics
that ignore `Agent.relationships`/`trust`/`skills`; confirmed vision
item 2.2 (institutions with persistent goals) was the already-designed
answer to the long-horizon-institution gap. Top follow-ups flagged,
not shipped this pass: `reflection_notebook` `kind="question"`/
`"conclusion"` entries (SELFEVOLVING §5.D/5.E), a plan-fulfillment
check in `Population.tick_plans`, relationship/trust-weighted
SOCIALIZE targeting, an `Agent.long_term_goal` seed at genesis
(`llm/mind.py`).

**Vision item 2.2 shipped (scoped):** `Institution.objective_ticks_
unmet` (`settlement/institutions.py`) tracks how many consecutive
times `compute_objective` re-derives the identical want — a real,
persistent frustration, not a fresh one each check (incremented/reset
in `_maybe_schedule_institution_belief`, zero added LLM volume).
`_maybe_schedule_rule_proposal` now grounds its prompt in whichever
institution has been stuck longest past `INSTITUTION_OBJECTIVE_
PERSISTENCE_THRESHOLD=3`, giving that institution real causal reach
into the Innovation Layer's rule-proposal pipeline — the doc's own
"council remembers a famine legislating against it" case. `rule_
propose.SYSTEM_PROMPT` now asks the model to prefer a rule that
actually responds to a named institutional want when one is given.

**Vision item 3.4 shipped:** new `llm/musing.py` + `World.musings`
(capped at `MUSING_HISTORY_MAX=60` — daily texture, unlike `reflection_
notebook`'s never-pruned discipline) + `SimulationEngine._maybe_
schedule_musing` (day_end cadence, `critical=False`, genuine
deterministic fallback). Grounded in the newest OPEN `reflection_
notebook` hypothesis when one exists, else the newest `knowledge_
tree()` entry, else the call is skipped entirely — no fabricated
musing on a fresh world with nothing yet to say. Surfaced main-UI
(this is explicitly meant to be seen, not dev-console depth): a "💭"
header line reading `World.summary()`'s new `latest_musing` field off
the live broadcast.

Verified: direct `World.to_dict()`/`from_dict()` round-trip for both
`musings` and `Institution.objective_ticks_unmet`; a direct end-to-end
test of `_maybe_schedule_rule_proposal` confirming a stuck institution
grounds the resulting rule and its `rule_originated` log line; a direct
`_musing_subject()` test confirming a fresh world (nothing learned yet)
correctly yields `None`; `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical (no deterministic tick-state code touched).

## [1.3.37] — Enable real reasoning traces for genuine judgment tasks; free their LLM budget

Explicit user directive, table-form: enable reasoning for personal
belief revision, major life decisions, council deliberation, town
consciousness, cultural evolution, and innovation & discovery — keep
it off for dialogue, rumors, dreams, and NPC moment-to-moment
cognition. Change `scripts/run.sh` defaults if required to actually
enable it, and reallocate freed LLM budget toward the tasks that need
real sentience/intelligence — the pillars' own Mind-half tasks and the
game's own self-improvement (Reflection/self-tuning), not just
narration.

**Root blocker found and fixed first:** `scripts/run.sh`'s
`LLAMA_REASONING` defaulted to `off` (`--reasoning-budget 0`,
server-wide) — this silently made every existing `deep_reasoning=True`
job's per-call "detailed thinking on" phrase a no-op regardless of
what the app asked for. Default -> `auto`; `off` still available to
restore the old floor.

**~20 tasks now carry `deep_reasoning=True`** (was 2 — Innovation
Layer propose/evolve only), one flag per the user's table, each tagged
at its call site: `personal_belief`/`beliefs` (personal + settlement
belief revision), `migration_decision`/`fission`/`guild_founding`/
`dispute` (major life decisions), `institution_belief` (council/
family/guild deliberation), `consciousness` (town consciousness),
`tradition`/`religion`/`narrative_direction`/`culture_digest`/
`institution_culture`/`faction`/`laws`/`rule_propose` (cultural
evolution), `invention` (alongside the existing `ontology_proposal`/
`ontology_evolution`, innovation & discovery), `reflection`/
`self_tuning` (the game learning/improving itself — not in the user's
table verbatim but a direct fit for "the game itself to learn and
improve," same Reflection/self-tuning system CLAUDE.md already frames
that way). Dialogue/rumor_interpret/dream/cognition (moment-to-moment
goal decisions) deliberately untouched — already fast, matching the
"off" column. town_brain/era_branch/geography stay untouched too
(already deterministic-decided-plus-LLM-narrated as of v1.3.35 — no
decision left to reason about).

**Schema/reasoning conflict resolved by dropping two schemas, not by
silently keeping reasoning off:** `personal_belief`/`beliefs` were the
only two of the newly-flagged tasks with a `json_schemas.py` grammar —
a grammar enforces the full output shape from the first token, which
suppresses a preceding `<think>` block entirely (`_schedule_llm_job`'s
own structural rule, `reasoning = deep_reasoning and task_schema is
None`, would otherwise silently keep reasoning off for exactly the two
tasks the user named first). Removed both from `TASK_SCHEMAS` — belief
revision benefits more from a real reasoning trace than from strict-
schema enforcement, and `beliefs.parse_*` already tolerated schema-less
output before FT.0 added the grammar.

**Budget reallocation:** `DIALOGUE_BACKPRESSURE_FRACTION` 0.75 -> 0.6,
`RUMOR_INTERPRET_BACKPRESSURE_FRACTION` 0.5 -> 0.35 — pure narration
now sheds its queue slot even earlier under real backlog pressure,
since ~20 tasks now cost 1.5x tokens each (existing `DEEP_REASONING_
NUM_PREDICT_MULT`/`_TEMPERATURE`, unchanged values, now applied far
more broadly) and should get first claim on the shared concurrency
limit.

Verified: direct `_schedule_llm_job` unit test confirming `reasoning=
True`/no schema/boosted num_predict-temperature/correct apply for a
representative newly-flagged task (`beliefs`); a full audit confirming
zero of the ~20 flagged tasks retain a `TASK_SCHEMAS` entry;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
(this batch touches only the async LLM-call path, never deterministic
tick state).

## [1.3.36] — Genuine decision-point expansion (migration); Nemotron 3 Nano 4B reasoning support

Explicit user directive, two parts. First: "move the LLM from
describing the world to thinking within the world" — clarified via
follow-up as an audit-driven expansion of which decisions the LLM
makes (not a prompt-wording/person-framing change), classifying each
decision point as deterministic/subjective/hybrid per the user's own
framework and converting hybrid/deterministic judgment calls that are
genuinely subjective into real LLM decisions. This is the opposite
direction from v1.3.35's settlement/civic conversions, which stay
correct — that pass targeted decisions that were actually objective
once the facts were separated out; this pass targets a decision that
is genuinely a judgment call. Second: "optimize all the prompts and
parser to work with Nemotron 3 Nano 4B."

**Individual migration decision** (`llm/migration.py`, new module,
audit's #1-ranked item): a core-cast agent with a real push/pull
reason to leave (bonded partner elsewhere, real hunger next to a
better-fed settlement, overcrowding, standing/feud pressure) used to
migrate on a flat chance roll. Same candidacy/decision split as
`llm/fission.py`/`llm/founding.py`: `Population.migration_push_target`
finds the deterministic preconditions (extracted, unchanged logic,
from the old `_maybe_migrate`); `Population.core_migration_candidates`
scans the core cast only (per-agent LLM decisions stay call-volume-
bounded, standing CLAUDE.md rule); a new engine job (`_maybe_schedule_
migration_decision`, gated by `MIGRATION_CHANCE_PER_TICK`, ambient/
non-critical — a sensible deterministic fallback exists) asks the LLM
to actually weigh the agent's life against the reason, with declining
to leave a real, valid outcome. `Population.depart_for_migration`
carries the extracted mutation logic (settlement reassignment, standing
reset, travel target, memory, relations nudge) unchanged. Non-core-cast
agents keep the original flat-chance-roll path exactly as before.

**Nemotron 3 Nano 4B support** (`llm/client.py`): `Config.llm_model`
default `gemma-4-e4b-it` -> `nemotron-3-nano-4b`. Unlike Gemma
(non-thinking by design), Nemotron 3 is genuinely hybrid-thinking, but
its `<think>` chain-of-thought is controlled purely by an exact
system-prompt phrase ("detailed thinking on"/"detailed thinking off")
that must be the model's first-seen instruction — not an API field.
Both LLM clients' `generate_json` gained a `reasoning: bool = False`
param that prepends the correct phrase (`OllamaClient` also sets its
native `"think"` field to match, for Qwen3 compatibility); harmless
boilerplate for any other model family, sent on every call regardless
of which model is actually loaded. Never combined with `json_schema`
(a grammar enforces the full output shape from the first token,
suppressing a preceding `<think>` block) — `_schedule_llm_job` enforces
this structurally (`reasoning = deep_reasoning and task_schema is
None`), reusing the existing Phase 3.A `deep_reasoning` flag (ontology
propose/evolve, neither of which uses a schema) rather than adding a
new one. `scripts/run.sh`'s `LLAMA_REASONING` doc comment updated to
note Nemotron 3 alongside Qwen3 and flag that a server-wide `off`
default makes this per-call phrase a no-op for `deep_reasoning=True`
jobs unless overridden.

Verified: direct mocked-client tests for both `LlamaCppClient`/
`OllamaClient` reasoning toggle (system-prompt content, Ollama `think`
field), a direct end-to-end migration-decision test (candidacy
detection, job scheduling, apply logic for both depart=True/False),
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical,
a 4000-tick LLM-disabled engine soak with round-trip equality.

Audit's remaining prioritized items — `choose_building_kind`
(settlement-level, low volume), SOCIALIZE targeting (highest per-tick
call volume; likely needs a non-LLM relationship-weighted heuristic
fix first), `_maybe_assign_occupations` (infrequent per-agent event) —
flagged as follow-up, not attempted this pass.

## [1.3.35] — Deterministic decisions, LLM-authored motivation; diagnostics fixes

Explicit user directive: several settlement/civic decisions were being
asked of the LLM when they should be computed — "the LLM can explain
the motivation afterward." Converts five systems from LLM-decided to
deterministic-decided-plus-LLM-explained, and fixes two diagnostics
gaps.

**Diagnostics.** `/diagnostics`'/dev-console's `llm_model` now reads
the actual `MODEL_PATH` env var (`scripts/run.sh`'s llama-server launch
flag) when set, falling back to `Config.llm_model` only when it isn't
— a live model switch no longer silently drifts from what diagnostics
reports (same root cause class as v1.3.15's `llm_model` default fix,
now closed at the read site instead of just the default). New
`trigger_rules_total`/`trigger_rules_by_status`/`wildfire_ignition_
ticks_recorded` fields close the gap for the two most recent Living
Terrarium systems — `governor_tuning`/`self_tuning_actions_recent`
were already present (v1.3.34) but nothing else from that pass was;
the dev console already dumps the whole `diagnostics` payload as raw
JSON, so any field added here is immediately visible with no frontend
change needed.

**Geography naming** (`llm/geography.py`): fully procedural now, zero
LLM call — a plain weathered place name ("Stillmere", "the Aldwash")
carries no interpretation the LLM would meaningfully add. Reuses the
existing collision-safe fallback pool as the only naming path.

**Era branch** (`llm/era_branch.py`): `compute_branch` scores each of
the five named branches by the settlement's own real STANDING-building
mix (the same `ERA_BRANCH_KIND_WEIGHTS` `choose_building_kind` already
reads), picking the highest — ties favor the sticky current branch,
then a namespaced random pick only when there's genuinely no signal
yet. The one remaining LLM call explains the computed lean in one
sentence; it can no longer choose a different one.

**Town brain priority** (`llm/town_brain.py`): `fallback_priority`
renamed `compute_priority` and promoted from fallback to THE decision
— "Food? Health? Construction? Just compute. Highest wins." Applied
synchronously before any LLM call; `Settlement.current_priority`
reflects it immediately regardless of LLM availability. The job is no
longer `critical` (nothing to defer — the priority is never in
question, only its one-sentence rationale is, and that already has a
real deterministic fallback).

**Institution objectives** (`settlement/institutions.py`): new
`compute_objective` — per-kind deterministic reads (FAMILY: feud
status / household size; COUNCIL: materials shortfall / ambition-vs-
resilience disposition, reusing `town_brain`'s own council-disposition
signal; GUILD: currency shortfall vs. teaching-focus). `Institution.
objective` is set immediately; the institution-belief LLM call (same
call, zero added volume) now only supplies `objective_reason`, an
explanation of the already-decided want, logged as a new
`institution_objective` event.

**Narrative Direction** (`llm/narrative_direction.py`): `compute_
themes` reads `Settlement.mood`'s own real axes (hope/fear/grief/
suspicion — already a statistical aggregate of lived events, Phase I)
and picks the strongest past a real threshold, same signal the old
`fallback_direction` used as its non-LLM path, now THE decision. The
LLM's remaining jobs: a one-sentence summary of the computed theme, and
its one genuinely creative side task (coining a local term for a
dominant event) — unchanged, since naming an unprecedented thing isn't
"choosing among a closed set of moods."

Verified: direct unit tests for every new deterministic function
(`era_branch.compute_branch` tie-breaking, `institutions.compute_
objective` across all three kinds' branches, `narrative_direction.
compute_themes` threshold behavior, `_resolve_llm_model_label`'s
MODEL_PATH precedence), a direct engine-level test confirming `town_
brain`'s priority/rationale/history apply synchronously before the LLM
job resolves, `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical, and a 6000-tick LLM-disabled engine soak with full
`World.to_dict()` round-trip equality.

## [1.3.34] — Living Terrarium items 1.4, 2.4: self-tuning, and Reflection that acts

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence,
"5. 1.4 + 2.4 — the world tuning and modifying itself, inside
guardrails." The two items are one mechanism: 1.4 is the proposal,
2.4 is the (sandboxed) act.

**The signal.** `World.wildfire_ignition_ticks` (a small capped
rolling window) records the real tick of every wildfire ignition;
`_detect_reflection_pattern` gained a governor-drift branch comparing
the realized mean gap between ignitions against the theoretical gap
`disasters.WILDFIRE_CHANCE_PER_WEEK` implies (`GOVERNOR_DRIFT_RATIO=
2.0`, needs `GOVERNOR_DRIFT_MIN_SAMPLES=5` real ignitions first) — the
vision doc's own worked example ("wildfires feel too rare to matter"),
grounded only in Body state, never a free-text hunch. This is the same
existing Reflection pipeline everything else in Phase 5 uses — a
recurring pattern becomes an open hypothesis, then (via the existing
deterministic `_reevaluate_reflection_hypotheses`) a `supported` one
once it survives multiple year-cadence cycles.

**The proposal (1.4).** New `llm/self_tuning.py`: once a `supported`
hypothesis names a governor in the closed `TUNABLE_GOVERNORS`
vocabulary (`{"wildfire frequency": "wildfire_chance"}` — the only
governor wired to a real mechanical effect so far), one LLM call
proposes a direction (raise/lower) and a magnitude (0..1, a FRACTION of
the allowed band, never a raw value). `disasters.GOVERNOR_TUNING_BAND
=0.3` (±30%) is enforced by `apply_bounded_nudge`, the interpreter
itself — structurally, regardless of what the model asks for.
`tick_wildfire` gained a `chance_multiplier` param reading `World.
governor_tuning.get("wildfire_chance", 1.0)`; `decay_disaster_scars`-
style, this is the second governor items 2.1/2.3 and 1.4 both touch
(disaster_scars via `nature_adaptation_bias`, wildfire ignition via
self-tuning) — deliberately the same low-native-parity-risk module
region.

**The act (2.4).** `SimulationEngine._maybe_schedule_self_tuning`
(world-scoped, year-cadence, `critical=True` — a genuine judgment
about the world's own balance, deferred rather than faked). The
proposed tuning is built on a disposable DEEP-COPIED world (`World.
from_dict`) FIRST — real `World.governor_tuning` is never touched
until `simulation.sandbox.run_counterfactual` confirms the copy
survives 50 ticks without crashing/exploding (item 1.3's sandbox
actually gating a real self-modification, not just rule proposals).
New `World.self_tuning_actions` (append-only, never pruned, same
discipline as `reflection_notebook`) logs every attempt — applied,
rejected by the sandbox, or a deliberate no-op below `SELF_TUNING_MIN_
MAGNITUDE=0.05` — "logged verbosely as the world's own decision,"
exactly as the vision doc asked. A hypothesis is only ever acted on
once (`self_tuning_actions`' own `hypothesis_id`s gate re-firing).
Reflection still never touches Body state directly outside this one
narrow, sandboxed, bounded exception.

**Surfacing.** Dev-console depth, same treatment as `reflection_
notebook` (`_diagnostics_snapshot()` gained `governor_tuning`/`self_
tuning_actions_recent`); an *applied* action also appears in `World.
knowledge_tree()` (new `type: "self_tuning"` entry, 🎛 icon) — visible
in the existing knowledge-tree UI panel alongside every other LLM-
originated persistent decision.

Verified: direct tests for `nature_adaptation_bias`-adjacent
`GOVERNOR_DRIFT_RATIO` detection (no ignitions, severe drift, normal
spacing — each producing the right pattern/no-pattern), `self_tuning.
apply_bounded_nudge`/`parse_self_tuning`, and a full synchronous
pipeline test (seeded `supported` hypothesis -> faked LLM proposal ->
sandbox-validated -> `governor_tuning` mutated for real -> re-firing on
the same hypothesis id correctly skipped). `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — `tick_wildfire` sits in
`World.tick()`'s hot path. A 3000-4000-tick LLM-disabled engine soak
with full `World.to_dict()` round-trip equality, `knowledge_tree()`/
`_diagnostics_snapshot()` both exercised without error.

## [1.3.33] — Living Terrarium items 2.1, 2.3: Nature that adapts and can surprise the Village

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence,
"4. 2.1 + 2.3 — Nature that adapts and can surprise the humans."

**2.1, Nature acts on its Mind.** New `terrain_evolution.
nature_adaptation_bias(nature_beliefs)`: the confidence of Nature's
Mind's single strongest belief whose subject concerns repeated fire/
flood/disaster damage (string-matched over `World.nature_beliefs`), or
0.0 if it holds none. `decay_disaster_scars` now takes this as an
`adaptation_bias` parameter and speeds the weekly scar-recovery rate up
to `NATURE_ADAPTATION_DECAY_BONUS_MAX=0.5` (50%) faster once the belief
is confident — the land genuinely recovering faster from repeated
disaster damage it has "paid attention to," bounded and directed by
Nature's own accumulated experience rather than a raw random walk.
Deliberately scoped to disaster scars — the one physical-substrate
module confirmed to have no native C++ counterpart (`apply_disaster_
scars`/`decay_disaster_scars`'s own long-standing R7-deviation note),
so this adds new logic with zero native/fallback parity risk.
`World.tick()`'s existing `decay_disaster_scars` call site now passes
`nature_adaptation_bias(self.nature_beliefs)`.

**2.3, Nature and Village can surprise each other (scoped).** Every
genuinely NEW Nature's-Mind belief (the `else` branch of `_maybe_
schedule_nature_mind`'s apply callback — real fresh insight the land
formed on its own, not a revision of an existing belief) now bumps the
origin settlement's `pattern_signal_counts["nature_adaptation"]` — the
same generic pressure-signal dict `_maybe_schedule_ontology_proposal`'s
`pressured` gate already reads (previously fed only by `dispute_
feud`). A settlement too poor/small to clear the prosperity gate can
now still have its ontology-proposal job made eligible purely by
Nature's own accumulated, unprompted insight — a real Nature-initiated
pressure the Village didn't script, free to originate a custom/law/
ritual/saying in response. Ships the Nature -> Village half of the
loop only; the reverse (a Village action visibly forcing a Nature
adaptation) is flagged as the natural sequel once 2.2 (institution-
driven actions) lands.

Verified: direct tests for `nature_adaptation_bias` (empty list, no
matching subject, matching subject) and the biased decay rate (1.0
bias applies the full 50% bonus, 0.0 bias unchanged), a direct test of
the `pattern_signal_counts` bump shape, `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — `decay_disaster_scars` sits in
`World.tick()`'s hot path even though the function itself isn't
natively ported, so this re-confirms no native/fallback divergence was
introduced — and a 4000-tick LLM-disabled engine soak with full
`World.to_dict()` round-trip equality.

## [1.3.32] — Living Terrarium items 5.1, 5.2: the guardrails

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence,
"3. 5.1 + 5.2 — the acceptance auditor and invariant guards. Ship
*before* turning up self-modification, so weeks-long runs stay
coherent."

**5.1, the acceptance gate as a runtime invariant.** New `world.
ontology.retire_stale_rules` + `TRIGGER_RULE_STALE_TICKS=40_000`: an
`active` `TriggerRule` whose trigger has never once matched
(`fire_count == 0`) past the stale window is retired — the concrete
gap this closes, since `InventedConcept` already had this via
`abandon_stale`'s adopter-based staleness but `TriggerRule` (new in
v1.3.31) had no analogous mechanism yet. Called from `_maybe_schedule_
rule_proposal`'s own gated cadence, same precedent as `abandon_stale`'s
call site. Retired, never deleted — same historical-record discipline
as every other status-transition in this registry.

**5.2, invariant guards around self-modification.** Extended
`simulation/sandbox.py`'s `run_counterfactual` (the one place a
proposal's consequences already get checked, rather than a second
parallel gate) with the vision doc's three named invariants:
`POPULATION_HARD_FLOOR` (population reaching exactly 0 is always
unsafe, unconditionally — independent of the existing 50%-loss
fraction check, which could theoretically miss a small-population edge
case) and `RESOURCE_EXPLOSION_MULTIPLE=5.0` (total settlement
materials exploding beyond 5x starting value). "No governor can be
disabled" is satisfied structurally rather than by a new runtime
check: a `TriggerRule`'s `hook_type` is drawn from the closed
`MECHANICAL_HOOK_TYPES` vocabulary, none of which reads or writes
`Config` — there's no vector through which a proposal could reach a
governor at all.

Verified: direct tests for `retire_stale_rules` (a never-fired rule
retires past the window, a once-fired rule doesn't), the sandbox's new
extinction/resource checks (including the edge case of an
already-extinct world not being falsely flagged as newly-caused),
`scripts/verify_native_soak.py` byte-identical, a 6000-tick
LLM-disabled engine soak with round-trip equality.

## [1.3.31] — Living Terrarium items 3.1, 1.2, 1.3

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md down its own
stated priority sequence: "1. 3.1 + 3.2 ... 2. 1.2 + 1.3."

**3.1, "the morning paper".** The away-digest gained a structured
"front page" section alongside its existing prose recap:
`World.away_digest_highlights` is every `knowledge_tree()` entry
originated strictly after the digest's own `since_tick` window — what
the world originated for itself while the observer was away — computed
in the same `apply` callback at zero extra LLM cost (a pure read over
already-computed state). `GET /digest` now returns a `highlights`
array; the digest panel renders it under the headline using the same
entry renderer the knowledge-tree panel uses (hoisted above both so
they share it, not duplicated).

**1.2, "a conditional/trigger vocabulary as data".** New `world.
ontology.TriggerRule` (+ `TRIGGER_TYPES`: on_death/on_birth/on_feud/
on_invention/on_drought/on_surplus) — a village-originated rule binding
a real trigger to a real mechanical hook (reuses `MECHANICAL_HOOK_
TYPES`/`validate_hook` verbatim, same closed-vocabulary discipline as
`InventedConcept`). New `llm/rule_propose.py` +
`SimulationEngine._maybe_schedule_rule_proposal` (season_end, world-
scoped, round-robins settlements like the ontology-proposal job).
Firing is wired to each trigger's real, pre-existing detection point:
`on_death`/`on_birth` off `World.last_life_events`, `on_feud` off
`llm.dispute`'s feud outcome, `on_invention` off a genuine invention
forming, `on_drought`/`on_surplus` off a new low->high edge-detected
crossing of `World.disasters.heat_pressure`/a settlement's granary
fill fraction (transient per-settlement previous-state tracking,
`_prev_drought_state`/`_prev_surplus_state`). `TRIGGER_RULE_COOLDOWN_
TICKS=500` prevents a burst of matching events from turning one rule
into runaway repeated narration. Only `belief_confidence_bonus` is
actually consumed as a real numeric effect this pass — the other hook
types stay narrative-only, flagged not silently dropped (same honesty
as `InventedConcept`'s own not-yet-consumed hook types, a pre-existing
gap this pass did not attempt to close). Rules surface in the
knowledge tree (new `type: "rule"`, ⚙ icon).

**1.3, the counterfactual sandbox.** New `simulation/sandbox.py`'s
`run_counterfactual`: before a proposed rule goes live, deep-copies the
world via its own `to_dict`/`from_dict` round trip, runs the fork
forward 50 ticks with the LLM forced off (a physics/invariant check,
not a cognition test), and checks it doesn't crash (population loses
>50%) or explode (population >3x) — the two invariants the vision doc
names concretely. An unsafe proposal is discarded and logged
(`trigger_rule_rejected`), never silently dropped. Properly cancels and
awaits the fork's own background LLM-fallback tasks before closing its
throwaway in-memory DB connection (caught live during verification —
an early version left a dangling task writing to an already-closed
connection). Runtime-invariant floors/ceilings as a standing guardrail
(item 5.2) and coherence/drift detection (item 5.3) remain separate,
larger, unattempted vision-doc items.

Verified: direct tests for digest highlights (window correctness across
two consecutive requests), trigger detection + cooldown (direct calls,
same-tick re-fire suppression), the full rule-proposal ->
sandbox -> registration pipeline end-to-end with a fake LLM client, the
sandbox's isolation from the real world (population/tick unchanged
after a sandboxed run) and its background-task cleanup fix,
`scripts/verify_native_soak.py` byte-identical (no native module
touched), an 8000-tick and a 15000-tick LLM-disabled engine soak with
round-trip equality.

## [1.3.30] — The Living Terrarium vision doc + item 3.2 (knowledge tree)

New docs/VISION-2026-07-22-LIVINGTERRARIUM.md (user-uploaded, filed as
the next-frontier vision doc following docs/VISION-2026-07-21-
SELFEVOLVING.md's pattern): maps five capabilities toward a "living
terrarium" — self-modifying mechanics (composable/trigger hooks +
counterfactual sandbox + bounded self-tuning), Nature/institutions as
true participants, the daily-peek experience, new entities/assets, and
runtime safety guardrails. Confidence-tagged [CERTAIN]/[LIKELY]/
[CREATIVE]; ships its own priority sequence.

This pass: item 3.2, "What the world learned" ledger — [CERTAIN],
first in the doc's stated sequence, "mostly surfacing data that
already exists." New `World.knowledge_tree(limit=200)`: a single,
newest-first, read-only aggregation of every LLM-originated persistent
entity across all four pillars plus Reflection — `invented_concepts`
(with `lineage`), each settlement's `laws` (law/custom/taboo),
`reflection_notebook` hypotheses (status/confidence), and `nature_
beliefs` — no new state, no new LLM call, each underlying store
already independently capped. Reached via a new on-demand provider
hook (`WorldBroadcaster.set_knowledge_tree_provider`/`get_knowledge_
tree`, same shape as the existing `full_diagnostics` provider) and
`GET /knowledge-tree`. New "🌳 knowledge tree" panel in the explore
menu, same toggle/fetch/render pattern as the existing highlights
panel — lineage rendered inline ("evolved from #N" / "merged from
#N + #N") when present.

Verified: direct aggregation/sort/lineage tests, a round-trip
(`to_dict`/`from_dict`) equality check, an end-to-end FastAPI
`TestClient` request through the real provider chain, a JS syntax
check, `scripts/verify_native_soak.py` byte-identical (no native
module touched), a 500-tick LLM-disabled engine run with round-trip
equality. The doc's remaining items (3.1 "morning paper," the
1.x self-modification frontier, 2.x Nature/institution agency, 4.x/5.x)
are recorded as open in the vision doc itself — not attempted this
pass, picked up on future explicit direction per this project's
"smallest coherent milestone" discipline.

## [1.3.29] — LLM integration architecture audit

Explicit user directive: audit every LLM call site, classify what each
one does (dialogue/planning/narration/cognition/other), and refactor
only where necessary so every LLM interaction passes through a single
cognition interface, without changing gameplay.

**Finding: the unification mostly already existed.** `_schedule_llm_
job` (engine.py, established the "July 2026 architecture review §1.2"
collapse of ~10 hand-rolled `_run_X` coroutines into one shared runner)
is already the single interface ~30 settlement/world-scoped jobs go
through — budget consume, backpressure pre-check convention, JSON-
schema-constrained decoding, critical-vs-ambient fallback discipline,
debug/call recording, all centralized. Three call sites bypassed it:
`_run_cognition` (per-agent goals) and `_run_dialogue` (per-pair
dialogue) are documented, structurally-necessary exceptions — both
carry pending-result queues and staleness handling `_schedule_llm_
job`'s fire-and-immediate-apply shape doesn't need. `_maybe_interpret_
rumor` had no such justification: it duplicated `_schedule_llm_job`'s
budget-consume/debug-record/call-record bookkeeping in a hand-rolled
`_runner()` coroutine for no structural reason.

**The one refactor**: `_maybe_interpret_rumor` now builds its prompt/
fallback and calls `_schedule_llm_job` like every other settlement job,
keeping its own tighter backpressure fraction check as an explicit
pre-check (same pattern every other job's `_settlement_job_
backpressured()` pre-check already uses). One deliberate, documented
behavior change: on a day whose LLM budget is already spent, this used
to skip the rumor retelling entirely (silent no-op); now it applies the
deterministic fallback retelling, matching every other non-critical
job's convention instead of being the one outlier that silently drops
its ambient texture. `server.py`'s one-shot world-genesis call and
`llm/rejection_sampling.py`'s standalone offline training tool are both
legitimate, out-of-scope exceptions (no engine/World exists yet for the
former; not part of the live tick loop for the latter) — left as-is.

Verified: direct end-to-end test (FakeClient) confirming memory
formation and counters unchanged through the new path,
`scripts/verify_native_soak.py` byte-identical (no native module
touched), a 6000-tick LLM-disabled engine soak with round-trip
equality. Files changed: `hearthmind/simulation/engine.py` only.

Explicit user directive: "Start the 5th item and extend LLM 4-5
pillars." Reflection is a meta-cognitive system observing the four
Minds (Humans, Village, Nature, Innovation), not a fifth pillar — see
v1.3.27's Body/Mind correction. Ships 5.A (persistent research
notebook) and 5.B (the reflection job) only; 5.C (counterfactual
sandbox), 5.D/5.E (prompt/architectural self-improvement) remain
design-only, flagged not attempted this pass.

New `World.reflection_notebook`/`next_reflection_entry_id`: typed
`ReflectionEntry` records (`kind: observation|hypothesis|experiment|
conclusion|question`, `subject`, `content`, `confidence`,
`evidence_for`/`evidence_against`, `status: open|supported|rejected|
superseded`, `supersedes`), never pruned by design — a rejected
hypothesis stays as historical knowledge, not deleted.

New `llm/reflection.py` + `SimulationEngine._maybe_schedule_reflection`
(world-scoped, `season_end`, `critical=False` — ambient self-
improvement, not blocking cognition, keeps a real deterministic
fallback). Each firing: (1) `_detect_reflection_pattern` — a
deterministic pass reusing existing counters across all four pillars,
no new instrumentation beyond one read-only aggregate: `Settlement.
pattern_signal_counts` (Village/Human), `WildlifeGrid.summary()`'s
`prey_scarce`/`predator_pressure_ratio` (Nature), and established-
concept category-imbalance over `world.invented_concepts` (Innovation/
cross-pillar, new `REFLECTION_ONTOLOGY_IMBALANCE_MIN_TOTAL=6`/
`_RATIO=3.0`); (2) if a pattern clears threshold and no open hypothesis
already shares its subject, one LLM call proposes a grounded hypothesis
plus explicit "what would contradict it" evidence, written as a new
notebook entry; (3) `_reevaluate_reflection_hypotheses` — every
existing OPEN hypothesis gets a small bounded confidence nudge
(`REFLECTION_CONFIDENCE_STEP=0.08`) from fresh evidence, transitioning
to `supported`/`rejected` at `REFLECTION_SUPPORTED_THRESHOLD=0.85`/
`REFLECTION_REJECTED_THRESHOLD=0.15`, no LLM call. Surfaced via
`_diagnostics_snapshot()` (`reflection_notebook_total`, `_by_status`,
`_recent`) — dev-console/raw-JSON only, matching Phase G/consciousness
precedent for internals-depth content.

Verified: direct production-path tests (hypothesis formation with a
FakeClient, multi-cycle confidence-nudge/dedup showing exactly 1
notebook entry persists across 3 firing cycles despite the pattern
recurring, ontology-imbalance detection, critical-job-deferral N/A
since `critical=False`), a 6000-tick engine soak + round-trip equality,
`scripts/verify_native_soak.py` byte-identical (no native module
touched).

## [1.3.27] — Body/Mind architecture correction + Nature's Mind

Explicit user correction: stop describing the LLM as a layer "bolted
on to" deterministic simulation — each pillar (Humans, Village, Nature,
Innovation) is one system with two inseparable halves: Body
(deterministic, always-authoritative objective reality) and Mind (LLM,
that pillar's subjective cognition — perception, memory interpretation,
belief formation, goal/social/cultural reasoning, concept invention).
A pillar with a thin Mind is incomplete, not correctly-mostly-
deterministic-by-design. Reflection is not a fifth pillar — it's the
meta-cognitive system observing the four Minds, one level up, never
touching Body state directly. Full text: docs/VISION-2026-07-21-
SELFEVOLVING.md's new "v1.2 revision note"; summarized as a standing
rule in CLAUDE.md's design-priorities section.

**Follow-up correction, same session: the shared ontology is a cross-
pillar capability, not an Innovation subsystem.** Every pillar should
originate its own kind of first-class entity into the SAME `world.
ontology.InventedConcept` registry — Humans (customs/professions/
myths/traditions), Village (institutions/laws/festivals/political
structures), Nature (ecological relationships/migration routes/
habitats/climate phenomena), Innovation (technologies/philosophies/
theories) — so any system can discover/combine/reinterpret/evolve/
merge across origins indefinitely. `ONTOLOGY_CATEGORIES` already spans
all four pillars' flavors, but scheduling had collapsed to one
mechanism: `_maybe_schedule_ontology_proposal` let the LLM pick ANY of
the eight categories from a single settlement-prosperity-gated
"village imagination" job — meaning even an `ecological` concept was,
in practice, Village-originated.

**Closed this pass: Nature's Mind (the identified gap) + the ontology
fix together.** New `llm/nature_mind.py` + `SimulationEngine._maybe_
schedule_nature_mind` — world-scoped, `season_end` cadence, `critical=
True` (deferred, never fabricated, on a spent budget/failed call, same
discipline as settlement beliefs). Grounded ONLY in Nature's own Body
state: `WildlifeGrid.summary()`'s trophic-pressure ratios (3.D),
`World.disaster_scars`/`mining_scars` counts, `World.fallow_ticks`
(succession progress, 3.D), `World.climate`'s warming/drying trend,
season — never settlement prosperity/era/tech level. One combined LLM
call does two things (same "maximize emergence per call" discipline):
(1) forms/revises a belief in new `World.nature_beliefs` (same shape/
discipline as `Settlement.beliefs`, reuses `llm.beliefs.parse_belief`/
`is_noop_belief_revision`); (2) may originate one new `category=
"ecological"` concept into the shared registry. `llm/ontology.py`'s new
`VILLAGE_PROPOSE_CATEGORIES` narrows the Village-imagination job to the
other seven categories — `ecological` is now `nature_mind`'s exclusive
territory — and `parse_propose` deterministically redirects a
hallucinated `ecological` answer back to a real Village category.

Not attempted this pass (flagged, real future scope): Nature's Mind
doesn't yet feed back into the Body mechanically (Village's `current_
priority` does, via `choose_building_kind`); a genuine Human-vs-Village
ontology-origination split (both still route through the same Village
job today).

Surfaced: `World.summary()`'s `nature_beliefs`, a new "The land's own
sense" stat tile in app.js.

Verified: direct unit tests (belief formation + concept origination
through the real production `_schedule_llm_job` path with a fake
client; correct critical-job deferral with the LLM disabled — state
left untouched, `calls_deferred_critical` incremented, nothing
fabricated), category-redirect test for the narrowed Village-imagination
job, a 6000-tick LLM-disabled engine soak with round-trip `to_dict()`/
`from_dict()` equality, `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — no native module touched.

## [1.3.26] — Phase 3.D food webs / predator-prey feedback

Explicit user request: "continue with food webs and predator-prey
feedback" — the last open item in docs/VISION-2026-07-21-
SELFEVOLVING.md's Phase 3.D.

`world/wildlife.py`'s hunt/starve mechanic already had a real local
loop (a predator pack only reproduces on a successful same-tile hunt,
and starves out without one) — the actual gap was that it was purely
local: a pack that happened to land on prey bred normally even while
the map-wide grazer population was collapsing, and a herd bred at its
normal rate even under heavy predation pressure it hadn't personally
been hunted by yet.

`WildlifeGrid.tick()` now computes two cheap aggregate ratios once per
tick (R7 deviation — Python, an O(n) scalar reduction over the herd
dict the tick loop already iterates, not a new per-tile hot loop, same
precedent as the mining/disaster-scar and soil-fertility modules):
`predator_pressure_ratio` (total predator animals / total grazer
animals) crossing `PREDATOR_PRESSURE_RATIO_THRESHOLD=0.25` halves
grazer reproduction chance map-wide (`PREDATOR_PRESSURE_REPRODUCE_
PENALTY=0.5`) — a "landscape of fear" effect distinct from the direct
kills the existing hunt mechanic already applies. `prey_scarce`
(current grazer-herd-count below `PREY_SCARCITY_RATIO_THRESHOLD=0.5`
of world-gen's own expected support, `GRAZER_TO_PREDATOR_RATIO` herds
per pack) halves predator reproduction chance
(`PREY_SCARCITY_REPRODUCE_PENALTY`) and doubles starvation risk
(`PREY_SCARCITY_STARVE_MULTIPLIER`) even for a pack that got a lucky
same-tile hunt this exact tick. Both ratios are surfaced in
`WildlifeGrid.summary()` and the "Wildlife" stat tile (a "prey
scarce"/"heavy predation" suffix, plus an updated tooltip explaining
the loop).

River course drift and ecology->weather bidirectional feedback remain
flagged, not attempted — the doc's own §3.D scope was food webs +
succession + scars; succession and scars already shipped (v1.3.22/
v1.3.25), this closes food webs, the last of the three.

Verified: direct unit tests exercising both directions of the loop in
isolation (heavy-predation-suppresses-grazer-breeding,
prey-scarcity-suppresses-predator-breeding-and-raises-starvation), an
8000-tick LLM-disabled engine soak sampling `wildlife.summary()` every
2000 ticks (stable, non-collapsing populations throughout) with a
round-trip `to_dict()`/`from_dict()` equality check,
`scripts/verify_native_soak.py` (2 seeds x 2500 ticks) byte-identical.

## [1.3.25] — Phase 3.C architecture + Phase 3.D succession

Explicit user request: "continue with 3.C and 3.D" — the two remaining
open items from docs/VISION-2026-07-21-SELFEVOLVING.md's Phase 3
second slice.

**3.C: architecture visibly changing on the map.** New `world/
ontology.py` `ARCHITECTURE_RELEVANT_CATEGORIES = ("technology",
"institution_flavor")` and `dominant_architecture_concept(world,
settlement_id)` — a settlement's own most-recently-established concept
(by `tick_invented`) in one of the two categories that plausibly
reshape what gets built, or `None`. `SimulationEngine._maybe_broadcast`
now computes `architecture_styles` (per-settlement `{name, category,
concept_id}`) and tags each broadcast building with its `settlement_id`
(broadcast-only, not persisted on `Building`). `app.js` outlines a
settlement's buildings in a color hashed from the concept id
(`architectureStyleColor`) instead of the flat default border, and
building hover tooltips name the style when one exists. No established
architecture-relevant concept yet -> unchanged rendering.

**3.D: forest succession, real intermediate stages.** `maybe_reclaim`
previously flipped an eligible abandoned-grassland tile straight to
forest the first week it qualified — no gradual regrowth. New `World.
fallow_ticks` (same additive-Python-dict-overlay shape as `mining_
scars`/`disaster_scars`, same R7-deviation rationale) tracks
consecutive qualifying weeks per tile via `terrain_evolution._tick_
fallow`; only a tile fallow for `REFOREST_MIN_FALLOW_WEEKS=3`
consecutive weeks is even offered to the existing roll, and a tile that
stops qualifying resets to 0 rather than pausing. Caught and fixed a
real native-vs-fallback divergence while verifying: the Python fallback
originally iterated the eligible-tile set in undefined hash order,
drawing RNG rolls in a different order than the native path's row-major
scan — fixed by sorting the fallback's iteration into the same
`(y, x)` order the native path implicitly uses.

Flagged, not attempted this pass (real remaining scope, not silently
dropped): food webs / predator-prey trophic feedback (`world/
wildlife.py`), river course drift (rivers are static geometry in
`world/hydrology.py`, not a per-tile biome the reclaim/scar machinery
can extend into), and ecology->weather bidirectional feedback
(flagged `[HYPOTHESIS]`, needs a reachability check against existing
spatial-weather smoothing first).

Verified: direct smoke tests (dominant-concept selection, payload
construction, round-trip `World.to_dict()`/`from_dict()` equality for
`fallow_ticks`), a live `SimulationEngine._maybe_broadcast` run through
a real asyncio loop confirming `architecture_styles`/`buildings[].
settlement_id` reach the actual broadcast payload, a 6000-tick
LLM-disabled engine soak, `scripts/verify_native_soak.py` (2 seeds x
2500 ticks, plus a re-run at 800 ticks) byte-identical after the
ordering fix above.

## [1.3.24] — Phase 3.A adoption thresholds + Phase 4 initial audit

Explicit user request: "start both" — Phase 3's last open 3.A item
plus starting Phase 4 (cross-pillar audit + persistence
generalization), docs/VISION-2026-07-21-SELFEVOLVING.md.

**3.A: population-scaled adoption thresholds.** `world/ontology.py`'s
`maybe_promote_status` now scales its spreading/established thresholds
against the concept's origin settlement's actual core-cast headcount
(`CONCEPT_SPREADING_FRACTION=0.2`/`CONCEPT_ESTABLISHED_FRACTION=0.5`),
floored at the original flat values so a small/new core cast still
promotes at the original pace. Core-cast headcount, not total
settlement population, since only core-cast members can ever become
tracked adopters (`_maybe_spread_concepts`'s existing candidate
filter) — scaling against unreachable population would have made
large settlements' concepts nearly impossible to promote.

**Phase 4 initial audit pass.** Spot-checked representative wiring
across all three cross-pillar directions (Nature<->Human, Village<->
Human, Nature<->Village) — no code gap found, consistent with the
audit's own "expected to be small" framing; findings documented in the
vision doc's Phase 4 section. Persistence-generalization item audited
and resolved as "already consistent by design, no new mechanism
needed": the Tier 0.1 decay-lock convention exists specifically
because interpersonal rupture has a "should never silently heal"
intent, the opposite of disasters/landscape-scars' deliberate "nature
recovers if left alone" intent — applying a lock there would
contradict the mechanic's own purpose. Village-identity fields
(`current_priority`/`era_branch`/`recent_topics`) checked for
unintended erosion and found clean — none have any decay mechanic,
persisting until their own owning job overwrites them.

Verified: direct smoke tests for `maybe_promote_status`'s scaling
(small vs. large core cast), `scripts/verify_native_soak.py` (2 seeds
x 3000 ticks) byte-identical — the audit pass made no code changes
beyond the 3.A threshold fix.

## [1.3.23] — Phase 3.B remaining items: occupation-as-status, dialogue register, deeper inheritance

Explicit user follow-up ("continue"): closes 3.B's two remaining
unshipped items (occupation → identity/status/dialogue register,
deeper inheritance) from docs/VISION-2026-07-21-SELFEVOLVING.md.

New `agents/occupations.py` constants: `OCCUPATION_STATUS_BONUS`
(mayor/priest only) feeds directly into `Population._prominence` — the
"positive counterpart" to `Agent.standing_penalty`'s ostracism-only
negative signal, consumed by the same council-eligibility ranking and
core-cast refill `_prominence` already drives. `OCCUPATION_DIALOGUE_
REGISTER` (priest/banker/mayor/teacher/scribe) is a light manner-of-
speaking hint in `dialogue.build_prompt` — "a priest speaks to belief,
a banker to debt," the doc's own example — same "garnish, never
forced" treatment `voice` already gets; every other occupation is a
genuine no-op. Rivalry between same-occupation agents sharing a
building/market (the doc's third occupation-status bullet) is
deliberately NOT attempted this pass — it needs a real colocation-
detection mechanism that doesn't exist yet, flagged as a future
follow-up rather than faked.

Deeper inheritance: `Population._apply_inheritance` gained a personal-
belief transfer, same imperfect-transmission shape v0.87.0's lesson
inheritance already established — the deceased's freshest `Agent.
beliefs` entry passes to the heir at `INHERITANCE_BELIEF_CHANCE=0.4`,
attributed ("X used to believe...") and at reduced confidence
(`INHERITANCE_BELIEF_CONFIDENCE_FRACTION=0.6`) rather than claimed as
the heir's own hard-won theory.

Verified: direct smoke tests (status bonus in `_prominence`, dialogue
register text, belief-inheritance transfer shape), a clean 5000-tick
LLM-disabled engine run with round-trip byte-equality,
`scripts/verify_native_soak.py` (2 seeds x 3000 ticks) byte-identical.

## [1.3.22] — Phase 2 completion, Phase 3 first slice (3.A/3.B/3.D)

Explicit user request: "complete phase 2 and start phase 3" —
docs/VISION-2026-07-21-SELFEVOLVING.md.

**Phase 2 completion.** Item 4 ("continuation weeks later"):
`_is_significant_pair` (dialogue's LLM-slot prioritizer) now also
treats an open ledger promise between the pair as significant, so a
pair with an unresolved thread genuinely competes for the next LLM
slot instead of only surfacing incidentally. Item 5 (voice consumed
more consistently): `llm/letters.py`'s prompt now reads `agent.voice`
the same way `dialogue.py` already does — a letter is first-person
written speech from a specific agent, the same "speaking as
themselves" shape.

**Phase 3 first slice** (one load-bearing mechanism per pillar, same
discipline as Phase 1):

- **3.A Innovation, "reserved deeper reasoning"**: both LLM clients'
  `generate_json` gained optional `num_predict_override`/`temperature_
  override` params, threaded through `CognitionRunner.run` and
  `_schedule_llm_job`'s new `deep_reasoning=True` flag — applied only
  to the Innovation Layer's propose/evolve/merge calls
  (`DEEP_REASONING_NUM_PREDICT_MULT=1.5`, `DEEP_REASONING_
  TEMPERATURE=0.5`), every other job's generation config unaffected.
- **3.B Humans, irreversible personality shift**: new `Agent.hardened_
  traits`/`extreme_event_count`, `Population._maybe_harden_trait`.
  Three extreme-event triggers (surviving a disaster from 1.D, a
  feud/ostracism outcome hardening, widowhood) increment a counter;
  crossing `EXTREME_EVENT_HARDEN_THRESHOLD=3` locks TRAIT_RESILIENCE
  into `hardened_traits` (exempt from `_tick_traits`'s monthly
  reversion from then on) with one real, permanent bump.
- **3.C Village**: audited, not further built — `known_concepts`
  (1.A) and `recent_goal_counts` (1.C) already ground every town_brain
  call with accumulated NPC/Innovation history. The map-rendering half
  (architecture visibly differing per established concept) needs live
  design judgment, not a mechanical extension — flagged as a future
  follow-up rather than built speculatively this pass.
- **3.D Nature, permanent landscape scars**: new `World.disaster_
  scars` + `world/terrain_evolution.py`'s `apply_disaster_scars`/
  `decay_disaster_scars` — same shape as `mining_scars` (cosmetic-only
  intensity, same R7-deviation rationale: Python, not yet worth a
  native port). A tile actively flooded/burning gains scar intensity
  each tick, decays weekly if left alone. Food-web/succession/
  weather-ecology items in 3.D remain open, not attempted this pass.

Full UI-surfacing pass in the same batch per the standing workflow
rule: a `disaster_scarred` map overlay (`paintDisasterScars`, distinct
ashen tint from mining's dark-pit color) and a "Disaster scars" stat
tile, both mirroring `mining_scars`' existing treatment exactly.

Verified: direct smoke tests for every new mechanic (client generation-
config overrides, trait hardening + reversion-exemption + round-trip,
disaster-scar gain/threshold-event/decay), a clean 5000-tick
LLM-disabled engine run with a full to_dict/from_dict round-trip
byte-equality check, `scripts/verify_native_soak.py` (2 seeds x 3000
ticks) byte-identical, and a Node.js syntax check on the modified
frontend file.


---

**Older entries (everything before the version above) have been moved to [docs/CHANGELOG-ARCHIVE.md](docs/CHANGELOG-ARCHIVE.md) to keep this file readable** — full detail preserved there, nothing lost.
