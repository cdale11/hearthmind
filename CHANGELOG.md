# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

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
