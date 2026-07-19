# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

## [0.87.19] — §2 close-out: a world, not parallel towns

Direct follow-up per explicit user request ("finish 2 of ideas.md")
— closes docs/IDEAS-2026-07-EMERGENCE.md §2's four items, all
previously unchecked. Also caught and removed a leftover duplicate,
already-superseded "Migration by choice" line that had survived at
the bottom of §1 from the v0.87.18 edit (the real entry was correctly
checked off higher up in the same section — a doc-editing mistake, not
a functionality gap).

**Letters carried by caravans** (`llm/letters.py`, `Settlement.
pending_letters`, new): monthly, core-cast-only, round-robin —
finds a core-cast agent with a real bond (`MIGRATION_BOND_THRESHOLD`,
same threshold `_maybe_migrate` uses) to a living agent in another
named settlement, writes one small grounded LLM letter, and queues it
on the RECIPIENT's settlement with a real multi-day travel delay
(`LETTER_TRAVEL_TICKS=400`). `SimulationEngine._deliver_letters`
(day_end) resolves delivery: a genuine memory (+ `LETTER_RUMOR_
CHANCE` seeded rumor) if the recipient survived the wait, or a
`letter_arrived_too_late` event if they didn't — latency is the
feature, not a dropped edge case.

**Settlement-level stance (proto-diplomacy)**: the underlying
mechanism (`Settlement.relations`) and its LLM-narrated layer
(diplomacy, v0.87.17) already existed; this closes the two missing
pieces the idea specifically named. `caravan_relation_factor`
(`settlement/buildings.py`, same shape as `market_relation_factor`) is
the deterministic caravan-frequency lever — a region on warm terms
with its sister settlements draws more outside trade traffic, cold
terms less. A successful individual migration now nudges both
settlements' relation warmer (`RELATION_MIGRATION_NUDGE`) — the
"migrant treatment" feed input. "Disaster aid" was not built (no
aid-transfer mechanic exists yet to feed from) — flagged, not
silently dropped.

**Refugees after disasters**: reuses `_maybe_migrate` (§1, v0.87.18)
rather than a parallel mechanism — `Population._housing_pressure`
(population / standing-hut capacity) is exactly the causal chain the
idea names, since a disaster ruining huts drops capacity directly with
no separate disaster-detection needed. Past `MIGRATION_HOUSING_
PRESSURE_THRESHOLD=1.3`, individuals push toward the named alternative
with the most housing headroom — same physically-walking, memory-
carrying migration every other push condition already uses.

**Dialect drift**: rides `narrative_direction`'s existing quarterly
call for zero added LLM volume — new optional `coined_term`/`coined_
meaning` schema fields, populated only when one event has genuinely
dominated a settlement's recent life enough to earn a name (most
quarters, nothing does). `Settlement.lexicon` (capped) feeds back into
`dialogue.py` as a light steering line ("locally, people sometimes
say...") — two settlements descended from one fission slowly stop
sounding alike.

New UI: "Local terms" line in the Town Brain panel; new event icons
(`dialect_coined` 🗣️, `letter_delivered` ✉️, `letter_arrived_too_late`
📭).

Verified: direct production-path tests for `_housing_pressure`/the
refugee push condition (synthetic overcrowded-vs-spacious settlement
pair), the full letters lifecycle (queued via a forced job call
through the real `CognitionRunner`, delivered with correct memory
text, and the "recipient died in transit" branch logging the correct
event) — not a reimplementation. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical; a 20,000-tick organic
LLM-disabled soak completes with zero crashes.

## [0.87.18] — §1 close-out: deviance/justice loop completion, migration by choice

Direct follow-up per explicit user request ("finish 1 of ideas.md") —
closes docs/IDEAS-2026-07-EMERGENCE.md §1's two remaining unchecked
items, the last ones in that section.

**Deviance/justice loop completion.** v0.87.17's theft mechanic gets
the two pieces the idea named but that batch deferred: theft now
plants a real `Agent.secrets` entry on the thief (`push_secret`, not
just a routine memory) via `THEFT_SECRET_TEXT_TEMPLATE`, and a third
colocated agent has a `THEFT_WITNESS_RUMOR_CHANCE` chance to notice and
remember it — the classic deviance → gossip seed. Dispute outcomes
gain a fourth option beyond reconcile/feud/council_ruling:
**ostracism** (`llm/dispute.py`, `_VALID_OUTCOMES`, only offered where
a council exists, the prompt explicitly reserving it for a genuinely
severe, clear-wrongdoing case). New `Agent.standing_penalty` (0..1,
`Population.apply_dispute`'s new branch) gates SOCIALIZE targeting
(`_nearest_other_agent` gained an `ostracized_ids` exclusion set) and
council candidacy (`_council_seat_key` returns a sentinel below any
real prominence while penalized), decaying monthly
(`STANDING_PENALTY_DECAY_PER_MONTH`, `_tick_traits`) rather than
standing forever. The deterministic fallback can also independently
reach ostracism on a sufficiently lopsided `reputation()` gap
(`OSTRACISM_REPUTATION_GAP`), same "legible rule, not a coin flip"
discipline the rest of `fallback_dispute` already follows.

**Migration by choice, not just fission** (`Population._maybe_
migrate`, new). Individuals could previously only move settlements as
part of a whole fission party. A rare, deterministic per-agent check
against push/pull signals already tracked elsewhere: a bonded partner
already living in another named settlement (highest-priority pull), a
codified ostracism, family feud pressure (`Institution.feuds`), or
genuine starvation next to a meaningfully better-fed sister settlement
(`_granary_fill_ratio`, `MIGRATION_GRANARY_ADVANTAGE`). Reuses
`depart_for_fission`'s exact shape at individual scale — settlement_id
reassigned immediately, `travel_target` set so the agent physically
walks there via the existing journey machinery — so a migrant carries
their own memories/beliefs/secrets into a population that doesn't
share them for free (nothing new needed touching those). `standing_
penalty` resets on arrival — a fresh settlement doesn't know what the
old one held against someone. New `migrant_departed` event (🎒).

**UI**: new "Standing" NPC-inspector section (shown only while
ostracized, fading penalty %); `theft`/`law_enacted`/`diplomacy_event`
event icons from v0.87.17 unchanged; `migrant_departed` icon added.

Verified: direct production-path tests for the theft secret/witness
completion (deterministic-rng forced trigger), `apply_dispute`'s
ostracism branch (asymmetric standing_penalty/relationship effects),
`_council_seat_key`'s exclusion, monthly decay, `_nearest_other_agent`'s
`ostracized_ids` exclusion (both with and without the native index
path), and all three `_maybe_migrate` push/pull paths (bonded partner,
starvation+granary, ostracism-with-reset) via synthetic two-settlement
populations; a real end-to-end engine test (fake `generate_json`)
confirming a forced ostracism dispute reaches the actual `Cognition
Runner`/`apply_dispute` pipeline and produces the correct decayed
`standing_penalty` after a month. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical; a 60,000-tick organic LLM-
disabled soak completes with zero crashes.

## [0.87.17] — Items 8 & 9: crime & justice, inter-settlement diplomacy, laws & customs, non-core LLM nudges

Direct follow-up per explicit user request ("complete my items 8 and 9
first"), closing out the two items deferred by the user's own
sequencing choice at the end of v0.87.16.

**Item 8a — Crime & theft** (`Population._maybe_commit_theft`,
`agents/population.py`): entirely deterministic, zero LLM cost — a
desperate, distrustful colocated agent may take some of another's
personal food stock. Consequences land asymmetrically on the victim's
read of the thief (trust/relationship penalty, same "easy to lose,
hard to earn" shape as dialogue's own nudges); a `Settlement.
thefts_committed` counter and `law_signal_counts["theft"]` accumulator
feed forward into item 8c.

**Item 8b — Inter-settlement diplomacy** (`llm/diplomacy.py`,
`SimulationEngine._maybe_schedule_diplomacy`): the underlying affinity
mechanism (`Settlement.relations`) has been fully deterministic since
v0.67.0 (seeded at fission, nudged by cross-settlement dialogue, felt
in market prices) but was never LLM-narrated or shown in the main UI.
This adds the occasional named moment on top (an envoy, a trade pact,
a border dispute) — round-robin over settlement PAIRS so volume stays
flat regardless of settlement count, and a genuine no-op with fewer
than two named settlements (the common case). Fallback is a genuine
no-op, never a fabricated event.

**Item 8c / §7 item 7 — Laws, customs, taboos** (`llm/laws.py`,
`Settlement.laws`/`law_signal_counts`, `SimulationEngine._maybe_
schedule_laws`): folded together since both closed the same "the
village should accumulate real norms from lived history" gap. Gated on
`law_signal_counts`/`pattern_signal_counts` crossing a threshold (theft
or dispute-feud recurrence) — same "spend the call only once real
texture exists" discipline `_maybe_schedule_religion` established;
fallback is a genuine "not yet," never an invented norm. A formed
law/custom/taboo has real mechanical bite: `dispute.py`'s prompt and
fallback both read a norm against feuding as social pressure toward
resolution, and `_theft_forbidden_by_law` sharpens theft's trust
penalty (`THEFT_LAW_PENALTY_MULT`) — laws interacting with the systems
they were written in response to, not an isolated mechanic.

**Item 9 — Occasional LLM nudges for non-core-cast agents**
(`llm/noncore_nudge.py`, `SimulationEngine._maybe_schedule_noncore_
nudge`): the user's own framing — "not fully LLM authored but
partially and occasionally." Exactly one call a month for the ENTIRE
world (round-robin `_job_target`, one random non-core agent per
firing), never per-agent-scaled like core-cast cognition. A genuine
answer nudges one trait by a small bounded amount
(`NUDGE_TRAIT_STEP=0.12`) and plants one durable reflective memory;
fallback is a real no-op — an "occasional" nudge that doesn't happen
most months is correct, not a failure.

New job slots added to the existing staggered-monthly-job calendar
(`MONTHLY_JOB_DAY`): diplomacy=2, laws=5, noncore_nudge=9 — all three
get the standard `MONTHLY_JOB_RETRY_WINDOW_DAYS` retry window.

**UI**: new "Laws & customs" panel (mirrors Faith & Rituals' flat-list
styling); new "Crime & justice" stat tile (thefts committed, norms
codified); new "Diplomacy" stat tile (per-sister-settlement relation
tone, shown only once a second named settlement exists); new event
icons (`theft` 🕵️, `law_enacted` 📜, `diplomacy_event` 🤝).

Verified: direct production-path tests for the theft mechanic
(condition gating, law-penalty multiplier, trust/relationship math,
counter increments) via synthetic colocated pairs; all three new LLM
job parse functions (`laws.parse_laws`, `diplomacy.parse_diplomacy`,
`noncore_nudge.parse_nudge`) against forms/no-forms/malformed inputs;
real end-to-end engine tests (fake `generate_json` through the actual
`CognitionRunner`) confirming all three new monthly jobs fire through
the real gate/backpressure/scheduling pipeline and correctly mutate
`Settlement.laws`/`relations`/agent traits — not a reimplementation.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
no native module touched.

## [0.87.16] — Cognition-quality cluster: diversity, memory weighting, competing beliefs, historical identity

Explicit user direction: the cultural/cognitive simulation was
converging too strongly on a single dominant narrative and a narrow
set of conversation topics. This batch is the "cognition-quality
cluster" half of that request (items 2-7 of the original ask); item 8
(broad deterministic-sim expansion: economy/politics/crime/diplomacy/
tech) and item 9 (periodic LLM nudges for non-core agents) are
explicitly deferred to a follow-up batch, per direct user sequencing
choice.

**Occupation-shaped, personality-consistent interpretation** (items 2,
6): `SimulationEngine._occupation_for` reads an agent's dominant skill
(farmer/builder/healer) back as a plain-language trade; `describe_
traits`, previously never reaching the personal-belief (Reflect())
job at all, now does. `PERSONAL_SYSTEM_PROMPT` explicitly instructs
the model to let occupation and temperament color HOW an event is
interpreted and to stay consistent with who the agent already is,
rather than reinterpreting identically every time.

**Support multiple competing beliefs** (item 5): `find_belief_index_
by_subject` gained `max_competing` — previously ANY same-subject
match force-merged a `revises: null` answer unconditionally, a real
convergence engine. Both settlement (`_maybe_schedule_beliefs`) and
personal (`_maybe_schedule_personal_belief`) jobs now allow up to
`MAX_COMPETING_BELIEFS_PER_SUBJECT=2` distinct theories about the same
subject to coexist before the safety-net merge kicks back in; both
system prompts (settlement + personal) now explicitly invite a second,
competing theory when a genuinely different interpretation is
warranted, rather than always converging.

**Reduce conversational convergence** (item 3): dialogue's weather
clause is no longer unconditional — `weather_notable` (computed from
`WeatherState.sky()`/`wind_label()`) gates it to genuinely notable
weather only; an ordinary clear/partly-cloudy/overcast day contributes
nothing. `SYSTEM_PROMPT` now explicitly lists the breadth of real
subject matter (family, guild/trade, ambitions, births/deaths, debts/
trade, festivals, animals, buildings, personal goals) and de-prioritizes
weather as filler; the weather-flavored few-shot example was swapped
for a family one.

**Improve memory weighting** (item 4): `_remember` now dampens a new
memory's salience (`MEMORY_REPETITION_DAMPING`) when its text shares
`MEMORY_REPETITION_OVERLAP_THRESHOLD`+ meaningful words with anything
already stored — repeated near-identical events fade faster.
`decay_memory_salience` now uses a permanently slower rate
(`MEMORY_MAJOR_EVENT_DECAY_PER_DAY`, ~0.999/day) for any memory
carrying a known causal tag (`memory_causes`, v0.87.14) — checked by
tag rather than current (already-decaying) salience, since a threshold
check against the decayed value would let a memory slip below the
slow-rate cutoff partway through and still converge to the floor
within about a year regardless of how significant it started.

**Deepen long-term historical identity** (item 7): new `Agent.
core_memories`/`core_memory_salience` — a small (`MAX_CORE_MEMORIES=5`)
permanent tier a memory graduates INTO on eviction from the ordinary
8-slot `memories` window when it's causally-tagged or cleared
`MEMORY_MAJOR_EVENT_SALIENCE_THRESHOLD`. Consumed in cognition prompts
(keyword-matched against the agent's current situation, "" when
nothing echoes it) and personal-belief/Reflect() prompts (given
unfiltered, since that job weighs someone's whole life). New "Never
forgotten" NPC-inspector section.

**Deliberately not attempted this pass** (flagged, not silently
dropped): item 2's caravan/migrant-introduces-competing-ideas ask and
generational drift (younger agents reinterpreting/forgetting
traditions differently from elders) — both real, scoped-out follow-up
increments, not covered by anything above.

Verified: direct production-path tests for every piece — occupation
labeling from real skill levels, competing-theory threshold behavior
(below cap lets a new entry stand, at cap merges), weather-notable
gating (silent on an ordinary day, mentioned on a real storm),
repetition dampening on a near-duplicate memory, because-tagged
major-event decay measured over a simulated year (stays >3x an
ordinary memory's salience) vs. the original salience-threshold
design (which was measured to converge to the same floor within a
year and rejected), core-memory graduation on eviction (forced via a
deliberately-oldest-tied setup) capped correctly, round-trip +
legacy-snapshot defaults for both new `Agent` fields. `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical after each of the
four sub-batches — this pass touches no native module.

## [0.87.15] — §7 close-out: planning, leadership, knowledge lifecycle; survival-decision framing

Closes three more docs/IDEAS-2026-07-EMERGENCE.md §7 items (bounded
episodic planning, emergent leadership, knowledge lifecycle), plus a
direct user-directed change to how survival decisions are posed to the
LLM. §7's last item (laws/customs/taboos) is explicitly deferred, not
attempted this pass — flagged, not silently dropped.

**Survival-decision framing** (explicit user direction): past
`SURVIVAL_HUNGER_THRESHOLD`/`SURVIVAL_ENERGY_THRESHOLD` (0.6/0.3, same
values `fallback_goal` already hardcoded — now sourced from these
constants), `cognition.build_prompt` no longer poses goal-setting as
an open "what should you focus on" question — physical need has
already decided it. The closing line becomes "your current priority
is X — explain briefly, in character, how you go about it," narrowing
the LLM's contribution to the "reason" field rather than the choice
itself, mirroring the deterministic-reality/LLM-meaning split the
critical-hunger movement override already enforces at the movement
layer.

**Bounded episodic planning**: new `Agent.plan` ({intent,
horizon_days, days_remaining, progress_note, formed_tick}), authored/
revised by the existing Reflect() job (zero added calls) via new
`llm.beliefs.parse_plan`. Consumed as one cognition-prompt line and a
small deterministic goal-bias in `fallback_goal` (keyword-matched
against the plan's intent). `Population.tick_plans` (daily cadence)
counts down and expires it.

**Emergent leadership**: council seat selection/refill now ranks by
`Population._prominence` (age as tiebreak only, not the sole
criterion) instead of pure age. New throttled contest check
(`COUNCIL_DISPLACEMENT_CHECK_INTERVAL_TICKS`, `COUNCIL_DISPLACEMENT_
MARGIN`): a sufficiently more-prominent non-member can displace the
council's weakest sitting member (`council_seat_contested` event). New
`Population.council_faction_majority` biases dispute-outcome framing
(`llm/dispute.py`'s `council_favors_a/b`) and town_brain framing
(names the dominant faction) when a single FACTION holds a majority of
living council seats.

**Knowledge lifecycle**: new `Settlement.invention_knowledge` tracks
knowers for the most recent `INVENTION_KNOWLEDGE_MAX_TRACKED=20`
inventions (deliberately not the full 300-cap history — see its
docstring for the scope boundary). An inventor is assigned at
formation; `Population._maybe_teach_skills`'s existing colocation loop
spreads it like a skill; `_apply_deaths` removes a dying knower and
flips `dormant=True` once none remain (`knowledge_lost` event,
"the craft behind X died with Y"); `_apply_inheritance` gives the heir
a chance (`INVENTION_REDISCOVERY_CHANCE`) to rediscover it. UI marks a
dormant invention "💤 dormant — no living knower" in the existing
Inventions panel. Cross-settlement diffusion (migrant/caravan carrying
knowledge to another settlement) is explicitly out of scope this pass.

Verified: direct tests against real production paths for all four
pieces — survival-framing prompt output at/below both thresholds; plan
formation/continuation/progress-note update/expiry via `Population.
tick_plans`; council contest via a real `_maybe_refresh_council` call
(challenger with boosted skill/bonds displaces the weakest elder);
`council_faction_majority` on a real Institution graph reaching both
`dispute.build_prompt` and `town_brain.build_prompt`; knowledge death/
dormancy/rediscovery over a 60-trial rng sweep (both outcomes
observed) and diffusion via a real `_maybe_teach_skills` call. Round-
trip + legacy-snapshot defaults confirmed for `Agent.plan` and
`Settlement.invention_knowledge`. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — this batch touches no native
module.

## [0.87.14] — Adaptive retrieval + causal memory links

Implements docs/IDEAS-2026-07-EMERGENCE.md §7 items 1-2, per explicit
user direction ("implement adaptive retrieval and causal memory
links").

**Causal memory links**: new `Agent.memory_causes` — an optional
`because` tag, index-aligned with `memories`/`memory_salience` (same
pad/truncate legacy-snapshot discipline), written only where
`Population._remember` call sites objectively know the cause:
inheritance/letter-keeping/kin-grief/bonded-grief memories at death
(`because=f"{name} died"`) and all three dispute outcomes — reconcile,
council_ruling, feud (`because=f"dispute with {them.name}"`). The
LLM-subjective half of this item ("let Reflect() author *possibly
wrong* causal links") is deliberately deferred, not implemented —
flagged as a natural next increment, not silently dropped.

**Adaptive retrieval layer**: new `retrieve_relevant_memories` (
`hearthmind/agents/agent.py`) scores every stored memory by recency,
salience, keyword-overlap relevance to the agent's current situation
(`_overlap_tokens`, relocated here from `simulation/engine.py` so the
new function can share it without an engine->agent import inversion),
and a small bonus for a known causal link — replacing `cognition.
build_prompt`'s previously-fixed `memories[-3:]` slice with the same
prompt-slot BUDGET (`RECENT_MEMORIES_IN_PROMPT=3`) but content that
earns its place. Scoped to `cognition.build_prompt`'s memory selection
only this pass — `dialogue.py`/`beliefs.py`'s own fixed slices and
non-memory stores (folklore/lessons) are untouched, left as a future
increment if the pattern proves out. A `because`-tagged memory shown
in a prompt gets a "(because: ...)" suffix.

New `retrieval_diagnostics()` (the idea doc's explicit ask: "measured,
not assumed") tracks call count and how often the scored top-k
diverged from a plain recency slice, surfaced at `/diagnostics.
memory_retrieval` (dev console only, same JSON-dump reachability as
`llm_prompt_stats`).

Verified: direct tests confirm relevance can surface an older
high-salience memory over a merely-recent one; `because`/
`memory_causes` round-trip through `to_dict`/`from_dict`, legacy
snapshots default cleanly (pad-short/truncate-long both covered); a
real `Population._remember` eviction test confirms all three parallel
lists stay aligned; a real `Population.apply_dispute` call (not a
re-implementation) confirms feud/reconcile outcomes correctly tag
`because`; a real built `cognition.build_prompt` call confirms a
`because` tag reaches the actual prompt text. `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — this batch touches no
native module.

## [0.87.13] — Weather as wear catalysts, slower baseline decay

Direct fix for a live report: "everything wears down too quickly."
Root cause: `Settlement.tick`'s building/vehicle decay used one binary
"harsh weather" gate (`precipitation > 0.4 or wind > 0.5 or
is_snowing`) that flipped a flat 3.0x (buildings) / 2.0x (vehicles)
multiplier on or off — measured against the real weather distribution,
that gate fired across a large share of all ticks, so the EFFECTIVE
average decay rate was much faster than the base constants alone
suggested, and every kind of "bad weather" produced the identical
generic penalty regardless of what was actually happening.

**Halved the baseline rates**: `buildings.DECAY_PER_TICK_BASE`
0.0004 -> 0.00022, `vehicles.VEHICLE_DECAY_PER_TICK_BASE` 0.0003 ->
0.00016 — full decay from perfect condition in fair weather now takes
~4500 ticks instead of ~2500. C3's standing principle (docs/
DECISIONS.md: "decay is never zero even in perfect weather") is
preserved — this is a rate change, not a new gate.

**Replaced the binary gate with `buildings._weather_decay_catalyst`**:
four independent, continuously-scaled catalysts instead of one flat
switch — damp/rot (scales with precipitation), dry-heat/cracking
(scales with high temperature, only relevant when NOT damp), frost/
freeze-thaw (scales as temperature approaches freezing, full strength
while snowing), and wind/structural stress (scales with wind past the
calm threshold). Each adds its own share on top of 1.0 rather than
multiplying, so a single "bad" reading (e.g. just windy) is a mild
bump, while a genuinely miserable day (cold, wet, and windy at once)
compounds several real catalysts — measured against a 30,000-tick
realistic weather sample, the new effective average full-decay time is
~3059 ticks, well above the old best case. Vehicles read the same
catalyst scaled to 2/3 strength (`VEHICLE_DECAY_CATALYST_SCALE=0.67`,
preserving the old 2.0-vs-3.0 ratio between vehicle and building
weather sensitivity) — a vehicle isn't a fixed structure exposed to
the elements the same way.

`SEASON_DECAY_MULTIPLIER`'s range narrowed ({1.4, 1.15, 1.0, 0.85} ->
{1.15, 1.05, 1.0, 0.95}) — its old wide swing existed to approximate
winter's freeze-thaw/damp as a coarse seasonal average; that's now
captured far more precisely by the real per-tick frost/damp catalysts
themselves (which naturally run harder in winter simply because winter
has more cold/wet ticks — an emergent, not hardcoded, seasonal skew),
so the season table now only covers the small genuinely-season-
specific residual.

Both native fast paths (`_native_building_decay_tick`/`_native_
vehicle_decay_tick`) take precomputed scalar decay values, not weather
directly — this change is entirely Python-side (the catalyst math runs
before the native call either way), so no C++ changes were needed.

Verified: direct tests confirm the catalyst function is always >= 1.0,
orders weather severity correctly (clear < overcast < heavy rain,
clear < gale, clear < frost, and a compound "miserable" day exceeds
any single factor), and the measured 30k-tick effective average decay
rate is meaningfully slower than the old worst-case baseline; a real
`Settlement.tick` integration test confirms buildings decay faster
than vehicles under identical weather (proportional to the 0.67 scale)
and both decay faster in a winter storm than in clear summer weather.
Re-verified against the rebuilt native extension (byte-identical
native-vs-Python at the new rates); `scripts/verify_native_soak.py`
(3 seeds x 2000 ticks) confirms native and pure-Python paths match
exactly at the new rates (not byte-identical to the OLD snapshot
baseline, since this is a deliberate rate/behavior change).

## [0.87.12] — Weather retune + three §7 cognition-infrastructure items

Two independent pieces per explicit user direction ("try closing point
7 first" = docs/IDEAS-2026-07-EMERGENCE.md §7 "Cognition
infrastructure," all 9 items; "reduce the amount of rain, there is no
variety").

**Weather retune** (`hearthmind/world/weather.py`): measured the
realized sky-band distribution directly (100k-tick sample, default
seed, across all twelve months) — the v0.43.0 cutoffs were
mathematically balanced (~48% dry, ~47% rain) but only four distinct
labels, so "raining" read as roughly a coin flip regardless of season.
Retuned against finer percentiles and split into SIX bands (`clear`/
`partly_cloudy`/`overcast`/`drizzle`/`light_rain`/`heavy_rain`,
new `WeatherState.sky()` machine-readable accessor alongside
`describe()`) — measured post-retune: dry (clear+partly_cloudy+
overcast) ~74%, real rain (drizzle+light+heavy) ~22% (down from ~47%),
snow ~4% unchanged. Frontend `RAIN_FLOOR` moved from the old light-rain
cutoff (0.38) to the new drizzle onset (0.45) so map particles start
exactly when the sky label first mentions precipitation. Zero effect on
persisted/soaked state — `describe()`/`sky()` are derived display-only
properties, `compute_weather`'s underlying blend math is untouched.

**§7 items shipped this pass** (3 of 9 — see docs/IDEAS-2026-07-
EMERGENCE.md for the other 6, now explicitly ticked/unticked to track
status):

- **Per-agent voice**: `Agent.voice` (`MAX_VOICE_TEXT_CHARS=100`),
  authored at the same one-time genesis `mind`-authoring call
  (`llm/mind.py`'s `SYSTEM_PROMPT` widened with one more JSON field,
  zero added LLM volume), deterministic fallback keyed by agent id
  (`describe_voice_fallback`, 8 templates) so a fallback-only run still
  gives every core-cast member a distinct-sounding tag. Consumed in
  `llm/dialogue.py`'s prompt alongside `mind`.
- **Institution objectives**: `Institution.objective` (one slow-revised
  line of what a FAMILY/GUILD/COUNCIL wants), authored by the existing
  monthly `_maybe_schedule_institution_belief` job (`beliefs.py`'s
  `INSTITUTION_SYSTEM_PROMPT` widened, `parse_institution_objective`
  only overwrites on a genuine non-blank answer — retained across a
  blank/fallback stretch, same discipline as `belief_digest`). New
  `Population.institution_objective_for` consumed in `cognition.
  build_prompt` as one grounding line. Not yet wired into dispute
  framing — flagged, not faked.
- **Dialogue novelty memory**: `Population.dialogue_topics` (per-pair
  ring, `DIALOGUE_TOPICS_RING_MAX=3`, same key/prune shape as
  `dialogue_cooldowns`) — `llm/dialogue.py`'s schema gained a `topic`
  field (never fabricated for the deterministic fallback, only a real
  LLM answer ever populates it), fed back into the SAME pair's next
  exchange as a "you've lately talked about X, Y — find something new"
  steering line.

Verified: direct tests for all three against real production paths
(genesis call sets voice via a fake LLM client and `_author_minds`;
institution-belief job sets objective via a fake client and `_maybe_
schedule_institution_belief`; dialogue schedule/apply cycle records and
reads back a topic via `_schedule_due_dialogue`/`_apply_pending_
dialogue_results`); round-trip + legacy-snapshot defaults for
`Agent.voice`/`Institution.objective`/`Population.dialogue_topics`; a
direct weather-distribution measurement confirming all six new bands
fire and the rain share dropped as intended. Re-verified against the
rebuilt native extension; `scripts/verify_native_soak.py` (3 seeds x
2000 ticks) byte-identical (weather change touches no persisted field;
the three §7 items touch no native module).

## [0.87.11] — Generational feuds between FAMILY institutions

Continued docs/IDEAS-2026-07-EMERGENCE.md §1 backlog per explicit user
direction ("continue... yes please"). "Generational feuds between
FAMILY institutions": promote a repeated pattern of pair-level `dispute`
`outcome == "feud"` results between members of two different FAMILY
institutions into a durable, institution-level feud — households
carrying a grudge, not just two individuals.

New `Institution.feuds: list[dict]` (`{"family_id", "formed_tick"}`,
capped `FAMILY_FEUD_MAX_STORED=4`) and `Settlement.family_feud_counts`
(pattern-count working state, same accumulate/threshold/consume-and-
reset discipline as `ritual_signal_counts`/`pattern_signal_counts`,
keyed by sorted family-id pair). New `Population.family_of`/
`families_feuding` helpers (mirroring the existing `faction_of`).
`SimulationEngine._maybe_promote_family_feud` (event-driven, called
directly from `_maybe_schedule_dispute`'s apply() on a real feud
outcome, not a per-tick scan) writes the feud symmetrically onto both
families once `FAMILY_FEUD_PROMOTION_THRESHOLD=3` real feud outcomes
land between them. Inheritance is free: `Institution.member_agent_ids`
already outlives individual members (H7's anchor point), so a feud
naturally covers descendants without any new mechanism.

**Consequences, reusing only existing mechanics**: dispute framing
gained a `rival_families` parameter (same shape as the existing
`rival_factions`) — both `llm/dispute.py`'s prompt and its deterministic
fallback treat a cross-feud-line dispute as harder to reconcile.
`Population._maybe_reproduce`'s affinity gate now demands
`REPRODUCTION_AFFINITY_THRESHOLD + FAMILY_FEUD_AFFINITY_PENALTY` (not
an outright block) for a pair from two feuding families — a real cost
that a strong enough bond can still overcome, the emergent "Romeo and
Juliet" the idea doc names, falling out of existing affinity mechanics
colliding with this one gate rather than any scripted event. A birth
that clears the higher bar gets its own distinctive event text noting
the union crossed the feud line.

**UI**: new `family_feud` event (⚔️, grouped under the "people" filter
chip alongside `dispute`) — zero new UI code beyond the icon/grouping
entries, the main feed already renders any logged category generically.

Verified: direct tests for `family_of`/`families_feuding`, promotion
threshold/symmetry/no-double-promotion, round-trip (`Institution.feuds`
+ `Settlement.family_feud_counts`, including legacy-snapshot defaults),
dispute prompt/fallback wiring, and the reproduction affinity gate
(ordinary threshold correctly rejected across a feud line, a stronger
bond correctly overcomes it, a non-feuding control pair is unaffected).
A real end-to-end test drives the actual `_maybe_schedule_dispute`
production path (fake LLM client always returning "feud") across
`FAMILY_FEUD_PROMOTION_THRESHOLD` real dispute cycles between two
synthetic families and confirms the symmetric institution-level feud
forms through the genuine scheduling pipeline. Re-verified against the
rebuilt native extension; `scripts/verify_native_soak.py` (3 seeds x
2000 ticks) byte-identical.

## [0.87.10] — Wedding ceremonies + season/year LLM job retry window

Two independent pieces per explicit user direction ("keep checking off
incomplete things from the list. Try to minimize dropping completed
LLM calls... instead make each LLM call count").

**Season/year LLM job retry window (fewer wasted opportunities)**: a
2026-07 audit found that `tradition`/`religion`/`narrative_direction`/
`culture_digest` (season_end) and `documentary` (year_end) were all
still gated on a single exact tick, unlike the monthly jobs
(`MONTHLY_JOBS_WITH_RETRY`, v0.81.1) — a backpressured boundary tick
meant a FULL SEASON or YEAR of silent loss, worse odds than the
monthly case this pattern was built to fix. New `SimulationEngine.
_season_year_gate`/`_mark_season_year_resolved` (`SEASON_YEAR_JOBS_
WITH_RETRY`, `SEASON_YEAR_JOB_RETRY_WINDOW_DAYS=5`) mirror the monthly
mechanism: a `SEASON_YEAR_JOB_RETRY_WINDOW_DAYS`-day window opens on
the boundary tick and stays open until the job gets through backpressure
once, closing the same "one unlucky tick costs a whole cadence" gap.
`invention` is deliberately excluded — unlike the other five, it rolls
its own per-tick RNG chance (`INVENTION_CHANCE_PER_SEASON`) after the
boundary gate, and widening its window would re-roll that chance on
every day of the window, inflating the effective per-season invention
probability beyond what it was tuned for (the same reason festival/
caravan/omen stay excluded from the monthly version).

Verified: direct tests confirm the gate opens/closes/expires correctly
and reopens for a fresh season/year ordinal; a real end-to-end engine
test forces backpressure on a season_end tick (real `_maybe_schedule_
religion`, fake LLM client) and confirms the job is dropped on the
boundary tick but succeeds on the very next tick via the open retry
window. `scripts/verify_native_soak.py` unaffected (Python-only
scheduling logic, no native module touched).

**Wedding ceremonies** (docs/IDEAS-2026-07-EMERGENCE.md §1, the
deferred half of v0.87.9's "ceremonies agents attend" item — "A
wedding = the same shape on a reproduction-pair formation"). The
missing piece last pass flagged was a real "this couple just bonded"
trigger; it already existed and was unused for this purpose: `_extend_
family` returns a `family_formed` event only the FIRST time two
parents have a child together (a second child to an already-bonded
couple returns `None`) — exactly the once-per-couple signal a wedding
needs, no new tracking required.

`Population._maybe_reproduce`, on a genuine `family_formed` event, sets
new `Agent.wedding_target`/`wedding_ticks_remaining` (`WEDDING_
DURATION_TICKS=48`, half `MOURNING_DURATION_TICKS` — a celebration of
what's already happened, not a grief process to work through) on the
couple plus any kin/bonded guests (same is-kin/is-bonded test the
funeral grief loop already established), all anchored at the birth
tile. `Population._dispatch_movement` gained a wedding override block
mirroring mourning's exactly (checked just after it, so an agent
somehow both mourning and celebrating finishes the funeral first) —
guests walk to the venue and hold there until `Population._tick_
weddings` (new, same duration-counter shape as `_tick_mourning`)
expires the gathering, at which point every guest gets a real joy bump
(`WEDDING_JOY_BUMP=0.25`, smaller than the couple's own `EMOTION_
BIRTH_JOY_BUMP` — the secondhand lift of attending, not the couple's
own). Same "zero LLM cost, zero new UI code" shape as funerals — guests
converging on the birth tile is visible through existing map/agent
rendering, and `family_formed` already has a main-feed icon (🏡).

Verified: direct tests against the real `_maybe_reproduce`/`_dispatch_
movement`/`_tick_weddings` methods (couple + bonded onlooker invited,
unrelated agent correctly not invited, guest walks to and holds at the
venue, expiry bumps joy and clears state, a second child to the same
couple does NOT re-trigger a wedding); round-trip. A real 30,000-tick
organic engine run (LLM disabled, population 20) produced 845 ticks of
active wedding gatherings with zero test-side scripting. Re-verified
against the rebuilt native extension; `scripts/verify_native_soak.py`
(3 seeds x 2000 ticks) byte-identical.

## [0.87.9] — Ceremonies agents attend: funerals

Direct continuation of the docs/IDEAS-2026-07-EMERGENCE.md §1 backlog
per explicit user direction ("continue with the things still left to
implement from vision"). Third item from §1: "ceremonies agents attend
— funerals and weddings." Funerals only this pass (weddings need more
design work — see "Not implemented" below).

**Mechanic**: `Population._apply_deaths` already identifies which
survivors are kin (`is_child`/`is_parent`) or bonded
(`relationships >= REPRODUCTION_AFFINITY_THRESHOLD`) to the deceased,
for the existing grief-bump loop — that same loop now also sets two
new `Agent` fields on each of those survivors: `mourning_target` (the
grave position, the same tile `Settlement.add_memorial` already
records) and `mourning_ticks_remaining` (`Agent.MOURNING_DURATION_
TICKS = 96`, matching a default-config day's tick count — "biases
their movement for a day," per the idea doc). `Population._dispatch_
movement` treats a nonzero `mourning_ticks_remaining` as an override
between `travel_target` (long journeys, higher priority) and the
agent's normal goal: the mourner walks to the grave and then, unlike
`travel_target`, HOLDS there rather than resuming normal movement —
a funeral is a gathering, not a one-shot errand. `Population._tick_
mourning` (new, called once per `Population.tick()` right after
`_apply_deaths`, same "duration counter ticks down to a revert" shape
`sick_ticks`/`immune_ticks` already establish) decrements the counter
every tick and, on expiry, eases (never erases) the survivor's grief
by `Agent.MOURNING_GRIEF_EASE = 0.15` and clears both fields, handing
movement back to the agent's normal goal.

Zero LLM cost, zero new scheduling machinery: the observer sees
mourners physically converge on and linger at a fresh grave marker
using purely existing map/agent rendering (memorials already render as
persistent map marks; agent positions already render as dots) — no new
UI code needed to make the gathering visible.

**Not implemented**: weddings (the idea doc's other ceremony) — unlike
a death, this codebase has no single "a couple formed" event to hook a
gathering onto (reproduction can recur between the same pair, and
there's no existing "first bonded" marker); flagged as a natural
follow-up once/if that state exists, not faked here with a shakier
trigger.

Verified: direct tests against the real `_apply_deaths`/`_dispatch_
movement`/`_tick_mourning` production methods — mourning state
correctly set on both kin and bonded survivors at the real memorial
position; movement walks a mourner to the grave and holds there
(doesn't wander off) while mourning is active; expiry eases grief by
exactly `MOURNING_GRIEF_EASE` and correctly resumes normal goal-
directed movement; `Agent.mourning_target`/`mourning_ticks_remaining`
round-trip through `to_dict`/`from_dict`. A real 30,000-tick engine run
(no test-side scripting) organically produced 13 deaths and 1,204
ticks with at least one agent actively mourning. All tests re-run
against the rebuilt native extension with identical results.
`scripts/verify_native_soak.py` (3 seeds x 2000 ticks) byte-identical.

## [0.87.8] — SEEK_PERSON directed intent + C++ build parallelism root-cause fix

Explicit user directive: continue implementing the emergence backlog
(LLM cost no longer a hard constraint), fix the C++ build still not
compiling in parallel, and diagnose an optional gemma-4-e4b model
error (blocked pending the actual startup log/error text).

**C++ build parallelism, actual root cause found and fixed.** The
"still not parallel" report was real — v0.85.6/v0.87.3 tuned
`build_ext`'s own `--parallel`/`self.parallel`, but that mechanism
only parallelizes ACROSS multiple `Extension` objects: verified
directly against `setuptools._distutils` source that
`build_ext._build_extensions_parallel()` submits one `ThreadPoolExecutor`
task per `Extension`, and the base `CCompiler.compile()` loops over
one extension's own source list strictly serially with zero per-file
dispatch. This project declares exactly ONE `Pybind11Extension` (~21
.cpp files), so neither prior fix could ever have had any effect on
this build regardless of the worker count it computed. `setup.py` now
installs pybind11's `ParallelCompile` (its own documented fix for
exactly this shape of project), which monkey-patches
`CCompiler.compile()` itself to thread-pool over individual source
files within one extension — capped at the same cgroup-aware core
count (`os.sched_getaffinity`) as before, overridable via
`HEARTHMIND_BUILD_JOBS`. Verified live: a clean rebuild showed 5
concurrent `cc1plus` processes (previously exactly 1), the extension
loads and passes the native soak byte-identical.

**SEEK_PERSON directed intent** (docs/IDEAS-2026-07-EMERGENCE.md §1,
the audit's own "single biggest structural finding": rich inner life,
but only five undirected movement-bias goals). New `AgentGoal.
SEEK_PERSON` pathfinds to a SPECIFIC other agent (`Agent.
seek_target_id`, re-resolved from the live per-tick position snapshot
every call so it tracks a moving target) rather than SOCIALIZE's
nearest-anyone. `Population._seek_person_candidate` deterministically
picks at most one same-settlement candidate + intent from EXISTING
state, zero new tracking: **console** (a bonded partner whose grief is
notable), **confront** (someone named in one of the agent's own kept
secrets whom they also distrust), **confide** (their most-trusted
living partner, only offered when they hold a secret worth confiding).
Deliberately does not implement "apologize" (the doc's fourth intent)
— that needs real per-pair dispute-history tracking this codebase
doesn't persist today.

Core-cast-only in practice: SEEK_PERSON is only ever chosen by LLM
cognition (`cognition.py`'s `SYSTEM_PROMPT` now offers it as a fifth
goal, grounded by one new optional prompt line naming the real
candidate + reason — the model is never asked to invent a target),
never the deterministic fallback, so call volume stays bounded by
`Config.llm_core_cast_size` automatically, same as every other
core-cast-gated decision. On arrival (same tile as the target), the
EXISTING colocated-dialogue mechanism (`Population.due_for_dialogue`)
picks the pair up exactly like an ordinary SOCIALIZE-driven meeting —
the intent reaches the dialogue prompt for free via `Agent.goal_reason`
(`dialogue.py`'s `_activity` already surfaces it), so this adds zero
new dialogue-scheduling logic and zero new LLM call volume beyond the
existing cognition/dialogue slots it rides. UI surfacing is free too —
the NPC inspector and map tooltips already render `agent.goal`/
`goal_reason` generically for any goal string.

New persisted field `Agent.seek_target_id` (int|None, round-trips
through `to_dict`/`from_dict`, defaults `None` on legacy snapshots) and
new `AgentGoal` enum member (code 5 in the native `AgentTable`'s int
mapping — appended, not renumbered, per that mapping's own "never
renumber an existing code" rule).

**gemma-4-e4b**: not yet actionable — asked the user for the actual
llama-server startup error/log text (confirmed to be a startup
failure, not a hearthmind-side error) since nothing in this codebase
hardcodes model-specific handling (the model name/GGUF path are plain
config strings), so a real fix requires the actual failure mode, not a
guess.

Verified: direct tests for `_seek_person_candidate`'s three-intent
priority order, `Agent.seek_target_id` round-trip, `cognition.
build_prompt`'s new grounding line, `Population.apply_goal`'s set/clear
discipline, movement toward a live (re-resolved) target position with
correct arrival detection via direct `_dispatch_movement` calls; a full
end-to-end engine test with a fake LLM client confirms the real
`_schedule_due_cognition` -> `_run_cognition` -> `_apply_pending_
cognition_results` pipeline correctly captures the candidate at
scheduling time and applies it only when the model actually returns
`seek_person`. All tests re-run against the rebuilt native extension
(goal-code round-trip through `AgentTable`) with identical results.
`scripts/verify_native_soak.py` (3 seeds x 2000 ticks) byte-identical.

## [0.87.7] — First two items from docs/IDEAS-2026-07-EMERGENCE.md §1

Direct follow-up to v0.87.6, per explicit user request to start
implementing the filed backlog. Picked the two highest-leverage, zero-
LLM-cost, self-contained items from §1 ("agents as protagonists" — the
audit's own "single biggest structural finding"), each extending an
existing mechanism rather than adding a parallel one.

**Heritable temperament with mutation.** Audit corrected the item's
own premise while implementing it: `Agent.traits` was never actually
rolled randomly at spawn — every founder and every newborn started
perfectly neutral (all four axes at 0.0), with a lifetime of event
nudges (`_nudge_trait`) the only source of variance. So the real gap
wasn't "replace a random roll with inheritance," it was "give newborns
*any* inherited variance at all." New `Population._inherited_traits`
(`hearthmind/agents/population.py`) blends each of the two parents'
values for all four axes (average, so neither parent dominates) plus
independent Gaussian mutation noise per axis (new `Agent.
TRAIT_INHERITANCE_MUTATION_STDDEV = 0.15`), clamped back to -1..1 —
wired into `_maybe_reproduce`'s `Agent(...)` construction as
`traits=_inherited_traits(a, b, rng)`. Zero new LLM calls, zero new
persisted fields (reuses the existing `traits` dict). Over many
generations a family's statistical tendency ("the stubborn Aldertons")
should now be a real, noticeable pattern the beliefs/folklore layer
can independently notice and name — not scripted here, an emergent
consequence of the mechanism.

**Deathbed release of secrets.** `Agent.secrets` previously died with
its holder — a real dead end for three otherwise-shipped systems
(Reflect()/dispute-planted secrets, rumor distortion via
InterpretRumor(), folklore condensation). `Population._apply_
inheritance` (H7's existing on-death heir-resolution job — the same
heir goods/skill/bias/lessons already transfer to) now also has a
`DEATHBED_SECRET_HEIR_CHANCE = 0.3` chance
to pass the deceased's freshest secret to that same heir, attributed
to the deathbed rather than the original confidant ("X told me on
their deathbed: ..."), and a further `DEATHBED_SECRET_RUMOR_CHANCE =
0.4` chance it also leaks as a vague rumor via the existing
`Population.spread_rumor` — deliberately never the secret's actual
contents, just "on their deathbed, X spoke of something long kept
quiet," heard by `DEATHBED_SECRET_RUMOR_LISTENER_COUNT = 2` nearby
agents. Both constants live in `hearthmind/agents/agent.py` alongside
`MAX_SECRETS`. Secrets now have the real lifecycle the audit doc
named: planted (Reflect()/disputes) -> guarded in dialogue -> leaked
at death -> distorted by InterpretRumor() -> maybe condensed into
folklore a generation later. Zero new LLM calls, zero new persisted
fields.

Verified: direct tests against the real production code paths — 2000-
sample `_inherited_traits` calls confirm the mean tracks the parent
average (within noise) and stays clamped, confirmed via a genuine
`SimulationEngine`/`_maybe_reproduce` tick loop that a real child born
in-engine inherits a high-resilience tendency from high-resilience
parents; a 400-trial direct `_apply_inheritance` test (real heir
resolution via `Settlement.family_for`, forced max-affinity heir)
confirms the deathbed-secret transfer rate lands at ~0.31 against the
expected ~0.3. `scripts/verify_native_soak.py` (3 seeds x 2000 ticks)
byte-identical — this batch touches no native module and reuses
existing persisted fields, so no snapshot migration is needed.

## [0.87.6] — llama-server `/metrics` polling (v0.87.5's flagged next step) + emergence idea backlog

Direct follow-up to v0.87.5, per explicit user request: implement its
own recommended-but-deferred next step (poll llama-server's real
server-side diagnostics instead of only char-based prompt estimates)
and file the externally-submitted "What's Still Missing" emergence
audit as tracked backlog.

**`/metrics` polling**: `scripts/run.sh` gained `LLAMA_METRICS_ENDPOINT`
(default `1`) passing `--metrics` to `llama-server`, exposing its
Prometheus-format `/metrics` endpoint (KV-cache occupancy, queue depth,
prompt/predicted-token throughput counters — no prompt content).
Deliberately does NOT pass `--slots`: that endpoint echoes live prompt
text back to the caller for cache inspection, a real privacy exposure
this project doesn't need to take on for aggregate numbers `/metrics`
already provides. New `llm.client.fetch_llama_server_metrics()` does a
plain stdlib `urllib` GET and parses the Prometheus text format (line
regex, no new dependency), returning `None` on any failure (server not
running `--metrics`, unreachable, wrong backend) — pure diagnostics,
never allowed to affect the tick loop or LLM call path.
`SimulationEngine` polls it every `LLAMA_METRICS_POLL_SECONDS=30` from
`run_forever`'s loop as a fire-and-forget background task (same
discipline as every LLM job) — real-time gated, not tick-gated, so
polling continues even while ticking is paused (LLM pressure, a
llama-server restart, or the user's own pause button). A no-op on the
`ollama` backend (no equivalent endpoint) or when the LLM is disabled.
Result surfaced at `/diagnostics.llama_server_metrics`, alongside the
existing char-based `llm_prompt_stats` estimates rather than replacing
them (the estimates still let you compare prompt sizes on paper before
a server is even running).

**Idea backlog**: an externally-submitted, checked-against-the-code
wishlist audit ("What's Still Missing," ~70 items across agent
action-vocabulary gaps, inter-settlement dynamics, meaning-loop
closure, observer-aware Town Consciousness, deep-time legibility,
substrate gaps, and cognition-infrastructure items like adaptive
retrieval/causal memory/episodic planning) is now filed at
`docs/IDEAS-2026-07-EMERGENCE.md`, tracked as backlog the same way
`docs/VISION-2026-07*.md` is. Status: idea checklist only, nothing
implemented or green-lit — worked from only on future explicit
direction.

**LLM utilization upscale** (directed, per explicit user follow-up):
a live report that `LLAMA_CACHE_RAM=0` (v0.87.5) resolved the swap/
memory pressure driving several prior config pull-backs — in
hindsight, that flag's stock 8GB reservation plausibly explains more
of the historical swap history than the KV-cache/concurrency sizing
those pull-backs targeted. Raised, all documented in `config.py` with
the full reasoning and explicitly marked as directed increases pending
live re-verification, not fresh measurements themselves:
`llm_max_concurrent` 2 -> 3, `llm_num_ctx` 2560 -> 3072, `llm_num_
predict` 448 -> 512, `llm_core_cast_size` 14 -> 18 (restoring the
original v0.72.3 value), `llm_max_calls_per_day` 320 -> 480.
`scripts/run.sh`'s `LLAMA_PARALLEL` (2 -> 3) and `LLAMA_CTX_SIZE`
(5120 -> 9216 = `llm_num_ctx * LLAMA_PARALLEL`) kept in step per the
existing "llama-server divides one shared `--ctx-size` across
`--parallel` slots" rule. `server.py`'s CLI defaults reference these
`Config` attributes directly (the standing rule from the v0.63.0
audit), so they pick up the new numbers automatically — no separate
server.py edit needed. **Deliberately not full restores** of the
higher v0.72.3 peaks (4096 ctx / 640 predict / cast 18 was already
restored) — a partial, verifiable step. Report back a live
`/diagnostics.system_memory` + `llm_prompt_stats` + the new `llama_
server_metrics` (this same release) reading after adopting these;
re-lower any of the five together if pressure reappears. Model choice
(the user is separately testing a q5_k_m quant of `gemma-4-e2b-it`)
left untouched — no config change made on the strength of an
in-progress test, per this project's standing "report back real
numbers" model-change discipline.

Verified: `Config()` constructs with the five new default values;
`bash -n scripts/run.sh`; `scripts/verify_native_soak.py` (2 seeds x
1200 ticks) byte-identical — this addendum touches no simulation
logic, only tuning defaults.

Verified (metrics polling): direct tests for `fetch_llama_server_metrics` (Prometheus
parsing incl. label-stripping, unreachable-host → `None`, no
exception) and for the engine's polling method against a real mock
HTTP server end-to-end (poll fires once per window, stores the result,
reaches `full_diagnostics()`, correctly skips a repoll within the
30s window, correctly no-ops on the `ollama` backend). `bash -n
scripts/run.sh` syntax check. `scripts/verify_native_soak.py` (2 seeds
x 1500 ticks) byte-identical — this batch touches no native module.

**Also discussed this pass, not yet acted on**: user reports
`LLAMA_CACHE_RAM=0` (v0.87.5) resolved the swap/memory pressure that
had driven several prior tuning passes, and is trying a q5_k_m
quantization of `gemma-4-e2b-it` — no config change made yet pending a
live diagnostic under the new quant/cache-ram combination, per this
project's standing "measure before tuning" rule; re-tune `llm_num_ctx`/
`llm_num_predict`/`llm_max_concurrent`/`llm_max_calls_per_day` from a
fresh `/diagnostics.system_memory`+`llm_prompt_stats`+`llama_server_
metrics` reading once one exists, rather than upscaling ahead of data.

## [0.87.5] — Prompt-density audit + llama-server host-RAM cache disabled by default

Explicit user directive: audit `--cache-ram` for memory savings, and
perform an extensive audit of every LLM prompt in the project — treat
prompt tokens as a scarce resource, prefer retrieval/hierarchical
summaries over raw event dumps, add token/latency telemetry so future
optimization is measurement-driven. This entry covers what shipped;
see the live diagnostics reasoning inline for what was investigated
and deliberately left alone.

**`--cache-ram` researched and disabled by default** (`scripts/run.sh`,
new `LLAMA_CACHE_RAM`, default `0`): llama-server's host-RAM prompt
cache defaults to **8192 MiB (8GB)** when the flag is never passed at
all — confirmed against the upstream `tools/server/README.md` (`-cram,
--cache-ram N: set the maximum cache size in MiB (default: 8192, -1 no
limit, 0 disable)`), not assumed. That default exists to skip
recomputing a REPEATED prompt prefix across calls — genuinely valuable
for a shared-system-prompt/many-similar-prompts workload, but this
project's own prompts are the opposite: every cognition/dialogue/
chronicle/beliefs/... call builds a fresh string from that specific
agent's/settlement's current state (hunger, position, memories,
relationships, recent events) — the only STRUCTURALLY repeated
content across calls is each job's fixed `SYSTEM_PROMPT` string, a
small fraction of total prompt tokens (see the token-count table
below). An 8GB reservation ceiling for a low-hit-rate cache is a poor
trade on hardware this project has treated as memory-scarce since
v0.42.0. `LLAMA_CACHE_RAM=0` (disable) is now the default; documented
as re-enable-if-measured (a real `-1`/positive-MiB override, guided by
`/diagnostics.llm_prompt_stats`, is one env var away) rather than a
permanent floor — same "best-measured default, not dogma" convention
every other `scripts/run.sh` tunable in this project follows.

**Prompt-density audit — one concrete fix shipped, most of the
codebase re-confirmed already tight from prior passes.** Measured
real prompt sizes (both live-diagnostic examples the user supplied and
synthetic saturated-state reconstructions, same methodology as
v0.85.3-.5's prior audits) across every LLM job:

| job | prompt tokens (real example) | note |
|---|---|---|
| chronicle | ~776-926 | dominant cost; see fix below |
| dialogue | ~251 | already tight (v0.85.0 routine-memory-salience fix) |
| personal_belief | ~110 | tight |
| mind | ~18 | one-time per agent, negligible |
| dream | ~24 | negligible |

**Found and fixed a real, measurable redundancy**: a rumor spreading
through several pairs (a natural, common gossip pattern) logs one
`rumor`-category event row per pair — `_apply_pending_dialogue_
results` already did this correctly, but neither `rumor` nor
`dialogue`/`dialogue_surfaced` are in `ROUTINE_EVENT_CATEGORIES`, so
`recent_events_diverse` (feeding chronicle/town_brain/beliefs/
documentary/personal_belief) never deduped them. The user's own
supplied live diagnostic showed this exactly: a real chronicle prompt
with 40 event lines, 13 of them (32.5%) the "X and Y: <rumor text>"
shape, 9 of those the literal same rumor ("Thea's bread is
enchanted."/variants) repeated across different pairs — over 1/3 of
the fixed-size event window spent re-stating one fact.

New `persistence/snapshot.py:_dedupe_rumor_topics` — a hierarchical-
summary fix, not a truncation: keeps only the newest occurrence of
each EXACTLY-matching rumor text (matched agent-name-agnostically, on
the text after the first ": "), appending "(echoed by N more pairs)"
to the kept line instead of silently dropping the fact that it spread.
Slightly-reworded retellings (the deliberate `InterpretRumor()`
distortion feature) are correctly NOT merged — only true duplicates
are, so genuine narrative texture (a rumor mutating as it spreads) is
preserved. Wired into `recent_events_diverse` as an extra pass before
the routine-category cap, so it benefits every one of its five LLM-
prompt callers (chronicle, town_brain, beliefs, documentary,
personal_belief) at once. Net effect measured on a synthetic 30-day
saturated run: rumor-category rows in a 40-event window dropped from
14 (undeduped) to 3 (deduped to distinct topics) — freeing roughly a
third of the window for genuinely new content instead of restating
what's already been said, directly the "avoid redundancy while
preserving reasoning quality" objective. `/events`/`/history` (the
raw feed) are completely untouched — every occurrence is still
logged and visible there; only the LLM-prompt-facing copy dedupes.

**Everywhere else, re-audited and confirmed already tight** (this
project's prior passes — v0.85.3 chronicle/town_brain belief-slicing,
v0.85.4 `belief_digest`, v0.85.5 `culture_digest`, v0.86.6's
folklore-call-skip, v0.87.1's dialogue-lesson audit — already did the
bulk of this work): cognition (~9 grounding sentences, each one line,
each individually gated on real state being present); dialogue
(already salience/routine-aware); personal_belief, dream, mind
(inherently short, no list to bound); dispute/invention/town_brain/
beliefs (already sliced to small `PROMPT_*_MAX` constants from prior
audits). No further raw-list-to-summary conversion found with a
measurable token cost to justify one — the standing "measure before
changing" rule applies here as much as to any other tuning knob.

**New telemetry: prompt/completion size and latency BY JOB TYPE**
(`simulation/engine.py`, new `_llm_prompt_stats`/`llm_prompt_stats_
summary()`) — closes a real gap the audit found: `llm_stats.latency_
ms_p50/p95` was aggregate-only, with no way to tell whether a slow
p95 traces to one verbose job type or is spread evenly. Every
`_record_llm_debug` call (the shared choke point `_schedule_llm_job`
already routes every settlement/per-agent job through, now also
called for `cognition`, which previously wasn't tracked in `last_llm_
calls` at all — a real telemetry gap, not just a display omission)
folds in prompt/completion character counts (a documented ~4-chars/
token estimate, `_TOKEN_CHARS_ESTIMATE` — deliberately not a real
tokenizer count; adding a tokenizer dependency just for telemetry is a
new-dependency decision this pass didn't make unprompted) and,
separately, wall-clock latency including any backpressure/queue wait
(distinct from `CognitionRunner`'s own pure-inference aggregate,
documented inline so the two aren't confused). Bounded rolling window
per job name (`LLM_PROMPT_STATS_WINDOW=200`). Surfaced as `/diagnostics.
llm_prompt_stats`, keyed by job name: `{calls, fallback_calls, avg_
prompt_tokens_est, p95_prompt_tokens_est, avg_completion_tokens_est,
avg_latency_ms, p95_latency_ms}`.

**Recommended next step, not implemented this pass** (documented
inline at `LLM_PROMPT_STATS_WINDOW`'s definition): llama-server itself
exposes real KV-cache/context-utilization/prompt-cache-hit-rate
numbers via its own `/slots`/`/metrics` endpoints. Polling those from
`hearthmind.server` would replace this pass's char-based estimates
with the real thing and add fields neither this project nor the
estimate can provide (true token counts, KV-cache occupancy, real
prompt-cache hit rate). Scoped out here because it's a genuinely new
polling subsystem (own interval, failure handling for an older
llama-server without those endpoints, a diagnostics-schema decision)
— flagged as the concrete next increment if deeper measurement is
wanted.

Verified: direct tests for `_dedupe_rumor_topics` (exact-topic merge +
echo-count text + singular/plural phrasing + non-rumor categories
pass through unchanged + preserves newest-first order); a direct
`_llm_prompt_stats`/`llm_prompt_stats_summary()` test against the real
`_schedule_llm_job` production path (fake LLM client, confirms call
counts, token estimates, and latency all populate correctly, and reach
`full_diagnostics()`); `bash -n scripts/run.sh` syntax check.
`scripts/verify_native_soak.py` (3 seeds x 2000 ticks) byte-identical
— this batch touches no native module.

## [0.87.4] — Close all remaining "learns like a human" deferred items

Explicit user directive: implement all six items on docs/VISION-2026-07-
LEARNING.md's deferred list in one batch. See that doc's "Shipped in
v0.87.4" section for full detail; durable facts only here.

**Item 1, non-core-cast population-wide lessons** (`agents/population.py`):
new `RECOVERY_LESSON_TEMPLATES`/`RECONCILE_LESSON_TEMPLATES` constants,
picked deterministically (`agent.id % len(...)`, no RNG) at the two
existing deterministic trigger sites — illness recovery (`_tick_disease`,
gained a `tick` parameter) and dispute reconciliation (`apply_dispute`,
gained a `tick` parameter, threaded from `_apply_deaths`/engine.py's
dispute apply()). Applies to EVERY agent, not just the core cast — zero
LLM cost, so the standing per-agent-LLM-call gating rule doesn't apply.
Reuses `llm.beliefs.push_lesson` (now imported directly into
`population.py`; audited for circular imports, none exist).

**Item 2, keyword-overlap fallback matching** (`simulation/engine.py`):
new module-level `_overlap_tokens`/`_OVERLAP_STOPWORDS` (pure stdlib
`re`, no embeddings/vector DB — a deliberate alternative to the
deferred item's "real semantic similarity" ambition, which would have
required a new dependency decision this batch didn't make unprompted).
`_matching_lesson` now falls back to comparing the agent's most recent
`working_memory` entry against every stored lesson's text when no
exact situation-tag match exists, surfacing the best-overlapping one
if it clears `LESSON_KEYWORD_OVERLAP_MIN=2` shared meaningful words.
Exact-tag matches are checked first and still win.

**Item 3, cross-generational lesson inheritance** (`agents/population.
py`, `Population._apply_inheritance`): new `Config`-independent
`Agent.INHERITANCE_LESSON_CHANCE=0.5` constant — the deceased's
freshest lesson (by `formed_tick`) passes to the resolved heir that
fraction of the time, reworded as attribution ("X used to say: ...")
via `push_lesson`, never claimed as the heir's own experience. Threaded
an `rng: random.Random | None` parameter through `_apply_deaths` ->
`_apply_inheritance` (the population-tick-scoped namespaced RNG,
matching this project's determinism discipline) — `None`-safe for any
legacy/test caller that doesn't pass one.

**Item 4, gradual continuous memory-salience fade** (`agents/agent.py`,
`agents/population.py`): new `MEMORY_FADE_DECAY_PER_DAY=0.985`/
`MEMORY_FADE_FLOOR=0.05`/`MEMORY_FADE_DISPLAY_THRESHOLD=0.25` constants
and `faded_memory_text()` helper. New `Population.decay_memory_
salience()`, called once/sim-day (`SimulationEngine._tick_once`'s
existing `day_end` block) multiplies every agent's stored `memory_
salience` values by the decay factor (floored, never truly zero) — a
memory that's never evicted or LLM-drifted still slowly reads as
hazier over real elapsed time, distinct from both mechanisms. `llm/
cognition.py`/`llm/dialogue.py`'s "You remember"/"recently" lines now
wrap a sufficiently-faded memory's text via `faded_memory_text` before
it reaches a prompt ("I only vaguely recall: ...") — the underlying
stored text is untouched, only the prompt-facing copy changes.

**Item 5, LLM-narrated skill mastery** (new `llm/skill_mastery.py`,
`simulation/engine.py`): the one genuinely new LLM call this batch
adds (approved small-call-volume budget). New `Population.last_skill_
masteries: list[tuple[int, str]]` (transient, reset every tick, same
"consumed the same tick" shape as `last_written_records`) — populated
at both existing `skill_mastered` sites (`_maybe_forage`'s farming
branch, `_advance_construction`'s construction branch, both gained an
optional `skill_masteries` output parameter). New `SimulationEngine.
_maybe_schedule_skill_mastery` (called every tick, reactive rather than
cadence-gated — mastery crossings are already naturally rare) only
acts on core-cast agents: schedules a non-critical LLM job that
replaces the memory `_remember` just wrote THIS SAME tick (in place,
by index, with the same old-text-identity guard `memory_drift.py`
established) with a reflection grounded in the agent's own recent
memories. Non-core agents and the settlement-wide `skill_mastered`
event log are completely untouched by this — personal narration only,
never public record. Fallback is a genuine no-op.

**Item 6, consciousness player-theory revision, round 2** (`llm/
consciousness.py`, `simulation/engine.py`, `world/state.py`): new
`revises_leading` JSON field (SYSTEM_PROMPT extended, `parse_
consciousness` validates it — forces False whenever `player_belief`
itself is empty, so a malformed response can never blank-overwrite the
leading theory) lets the monthly job say a fresh `player_belief` is a
refinement of its existing leading theory rather than an independent
new one. When true, `consciousness_player_model`'s highest-confidence
entry is updated IN PLACE (`belief` replaced, `confidence` nudged up by
new `CONSCIOUSNESS_REVISION_CONFIDENCE_GAIN=0.1` capped at 1.0,
`revision_count`/`revised_tick` incremented) instead of appending a
duplicate entry — closes a real dead-schema gap: those two fields have
existed since v0.84.0 but nothing ever incremented them, since every
prior write unconditionally appended a brand-new dict with
`revision_count=0`.

Verified: direct production-code tests for all six pieces (illness-
recovery/reconciliation lesson formation across both templates,
keyword-overlap fallback matching including the exact-tag-still-wins
case and the zero-overlap/no-lessons empty cases, inheritance's
imperfect-chance + freshest-lesson-wins + attribution text + "no
lessons -> never inherits" case, salience decay converging toward the
floor + `faded_memory_text`'s threshold behavior, a real fake-LLM-
client end-to-end engine test confirming core-cast mastery narration
replaces the memory in place while a non-core agent's deterministic
template is completely unchanged and no LLM job is scheduled for it,
and consciousness revision-vs-append branching including the "no
belief -> forced False" guard and the real in-place mutation of
`confidence`/`revision_count`/`revised_tick`). `scripts/verify_native_
soak.py` (3 seeds x 2000 ticks) byte-identical — this batch touches no
native module.

## [0.87.3] — Parallel-build hardening, restart-aware pausing, consciousness trend theory, perf audit

Five items from one user turn: the C++ build still not visibly
parallelizing, a request to reconsider simulation-size defaults for
speed/memory/smoothness, where repair/upkeep counters show in the UI,
continuing deferred item 4 of `docs/VISION-2026-07-LEARNING.md`
(richer Town Consciousness narrative modeling), and making
`LLAMA_RESTART_HOURS` restarts pause the simulation and show in the UI/
diagnostics instead of relying on per-call fallback.

**Parallel build hardening** (`setup.py`): `BuildExtOptional.finalize_
options` now sizes its `--parallel` default from `os.sched_getaffinity(0)`
(falling back to `os.cpu_count()` on platforms without it, e.g. macOS)
instead of `os.cpu_count()` alone. `cpu_count()` reports the machine's
total logical CPUs, ignoring any cgroup quota/`taskset` affinity
restriction the build process is actually confined to — a live report
that the build "still isn't parallel" despite this defaulting mechanism
existing since v0.85.6 is consistent with exactly that gap on a
constrained host. Verified locally (a 4-core sandbox): a clean `python
setup.py build_ext --inplace` now runs 4 concurrent `cc1plus` processes
throughout the build (previously observed to still complete correctly
but the fix's actual robustness against affinity-restricted hosts was
unverified) and the extension imports and builds byte-identical output.

**Simulation-defaults audit** (map size/population/tick pacing): ran a
real headless soak (`SimulationEngine._tick_once` in a tight loop, LLM
disabled, default 64x64/pop-12 config) instead of guessing at new
defaults — measured tick cost genuinely rises with population (6.2ms/
tick at pop 12-14, 9.8ms/tick at pop 83) but stays under 1% of the
1000ms `tick_seconds` budget even at that rate; extrapolated to
`POPULATION_CAP=400` it would still leave over 95% of the tick budget
free. Peak RSS stayed at 37MB. Conclusion: the deterministic tick loop
is not, and does not become, the bottleneck at any population within
the current cap — this project's own repeated live-diagnostic history
(CLAUDE.md) already establishes the actual "speed/smoothness"
constraint is LLM call throughput/config, not map size, population cap,
or tick pacing, and those knobs are already tuned from real hardware
reports. No default changed here — changing `width`/`height`/
`POPULATION_CAP`/`tick_seconds` without a measured problem they'd
solve would violate this project's own "measure before tuning"
discipline. If population/map size are ever raised well past current
defaults, the real future lever is finishing R8 (porting `Population`'s
remaining per-agent tick logic to the C++ store, see CLAUDE.md).

**Repair/upkeep UI location**: no code change — this already exists as
the "Repairs & upkeep" stat tile (v0.86.7, `buildings_repaired`/
`vehicles_repaired`), visible under the main UI's stat tiles.

**Richer Town Consciousness narrative modeling** (`simulation/
engine.py`, deferred item 4): `_player_intervention_trend` now folds
the consciousness's own highest-confidence `consciousness_player_model`
entry (`_leading_player_theory`, new helper) directly into the
frequency-trend sentence instead of leaving the two facts to sit
unconnected in the prompt (trend line vs. `player_model_text`, both
already present separately since v0.87.0) — e.g. `"increasing (your
leading theory: \"...\")"`. Zero added LLM call volume; the monthly
consciousness job's prompt shape is otherwise unchanged.

**LLAMA_RESTART_HOURS now pauses the simulation** (`config.py`,
`simulation/engine.py`, `server.py`, `scripts/run.sh`, frontend): new
`Config.llm_restart_sentinel_path` — a file path `scripts/run.sh`'s
restart supervisor subshell touches right before killing the old
llama-server process and removes once the replacement answers
`/health`. `SimulationEngine.llama_server_restarting()` polls the
path's existence the same way `llm_pressure_paused()` is already
polled; `run_forever`'s loop treats a restart exactly like the existing
LLM-pressure pause (ticking fully skipped, `PAUSED_POLL_SECONDS`
polling cadence) rather than leaving every individual LLM call to
independently fall back/defer during the ~1-10s outage. Tracks
`_llama_server_restarts` (counted on the absent->present edge, not
per-poll) and logs a real `llama_server_restart` event on both edges,
forcing an out-of-band `_maybe_broadcast()` on the edge so connected
UI clients see the transition promptly rather than only after ticking
resumes (ticking itself is what normally drives a broadcast). Surfaced
as `llama_server_restarting`/`llama_server_restarts_total` in
`/diagnostics` and the live broadcast; new header banner ("🔁
llama-server restarting — the town pauses…", reusing the existing
`.consciousness-indicator`/`.consciousness-paused` CSS convention).
`scripts/run.sh` creates a fresh (not-yet-existing) sentinel path via
`mktemp -u`, passes `--llm-restart-sentinel` to `hearthmind.server`
only when the restart supervisor is actually active (LLAMA_RESTART_
HOURS>0 — zero added cost otherwise), and cleans it up on exit
alongside the existing pidfile.

Verified: direct tests against the real `SimulationEngine` production
code confirm `llama_server_restarting()`'s absent->present->absent edge
transitions increment the restart counter exactly once per cycle (not
per poll), correctly skip `_tick_once()` for the whole window, surface
both new diagnostics fields, and stay a permanent zero-cost no-op when
no sentinel path is configured; a second test confirms `_player_
intervention_trend`'s theory-folding reaches a real `consciousness.
build_prompt` call. `scripts/verify_native_soak.py` (2 seeds x 2000
ticks) byte-identical — this batch touches no native module.

## [0.87.2] — Deeper settlement pattern-recognition + llama-server heap tuning without restart

Two independent pieces per explicit user direction: continue item 2 of
`docs/VISION-2026-07-LEARNING.md`'s deferred list (deeper settlement
pattern-recognition), and investigate reducing llama-server heap
growth without relying on `LLAMA_RESTART_HOURS` (v0.86.9).

**Settlement pattern-recognition** (`simulation/engine.py`):
`_detect_ritual_signals` (runs every tick, already the home of the
`starvation_death`/`dispute_feud` counters) gained two more
`pattern_signal_counts` categories: `disease_outbreak` (matched on
`Population._maybe_outbreak`'s "fallen ill" index-case text
specifically, NOT the "illness" category alone, which also covers
person-to-person spread — that's the same disease already noticed, not
a new one starting) and `wildlife_recolonization` (the existing
`wildlife_recolonized` event category, already flowing through
`World.last_life_events`). `_maybe_schedule_beliefs` gained the two
matching "pattern noticed" grounding sentences, same additive-not-
replacing treatment the original two categories established — the
settlement-wide beliefs job can now notice a recurring disease problem
or repeated wildlife pressure, not just recurring feuds/starvation.
Zero added LLM call volume (same existing monthly beliefs call).

**llama-server heap tuning** (`scripts/run.sh`): three new optional
glibc malloc-tuning env vars — `LLAMA_MALLOC_ARENA_MAX`,
`LLAMA_MALLOC_MMAP_THRESHOLD_KB`, `LLAMA_MALLOC_TRIM_THRESHOLD_KB` —
exported (via an `env` prefix, scoped to only the llama-server child
process) as glibc's `MALLOC_ARENA_MAX`/`MALLOC_MMAP_THRESHOLD_`/
`MALLOC_TRIM_THRESHOLD_`. All default empty/unset (glibc's own
defaults, verified unchanged behavior). This is a complement to
`LLAMA_RESTART_HOURS`, not a replacement — it reduces the RATE general
heap fragmentation accumulates (capping per-thread arena fragmentation,
forcing large/varying allocations through mmap instead of the sbrk'd
heap so they return to the OS on free, and lowering how much free space
glibc holds onto before returning it) rather than periodically
reclaiming it via restart; the two are meant to be tried together, with
restart as the reliable backstop if tuning alone doesn't hold.

Verified: direct tests against the real production code paths confirm
the new counters increment correctly (an outbreak-origin illness event
increments `disease_outbreak`, a person-to-person "caught the illness
from" event does NOT), the pattern sentences reach a captured beliefs
prompt, and counters reset after being consumed; `scripts/verify_
native_soak.py` byte-identical. The malloc-tuning env vars were
verified end-to-end against a mock llama-server binary confirming the
converted byte values reach only the llama-server child process
(never hearthmind.server or run.sh itself) and that the default
(all three unset) path is unchanged from before this change.

## [0.87.1] — Dialogue reads lessons too + a fresh RAM-to-disk audit

Direct follow-up to v0.87.0, per explicit user direction: implement
the highest-priority deferred item from `docs/VISION-2026-07-LEARNING.
md` (dialogue consumption of lessons), and re-audit for any RAM state
that could move to disk-backed on-demand retrieval to curb LLM-related
memory growth.

**Dialogue lessons** (`llm/dialogue.py`, `simulation/engine.py`):
`dialogue.build_prompt` gained a `lessons: tuple[str, str]` parameter
— each speaker's one lesson (if any) matching their current situation,
folded in with the same per-agent loop shape memory/emotion/mind/
secret bits already use. `_schedule_due_dialogue` computes both via
the existing `_current_situation_tag`/`_matching_lesson` helpers
(unchanged, already built for cognition in v0.87.0) — zero new state,
zero added LLM call volume, purely a prompt-input extension. Closes
item 1 of `docs/VISION-2026-07-LEARNING.md`'s deferred list.

**RAM-to-disk audit (no code changes resulted — see rationale below)**:
re-checked every candidate structure this project keeps in memory,
specifically the state added since the last full audit (v0.86.9):
`Agent.lessons` (cap 4), `Settlement.pattern_signal_counts` (2 keys),
the `memory_drift` job's own transient prompt state. All are already
either (a) tiny fixed-size caps that exist specifically to be read on
every relevant prompt-build (moving them to disk would add a SQLite
round-trip to the hottest code paths — per-tick cognition/dialogue
scheduling — for zero real memory benefit, since the RAM cost of a
4-entry list of short strings times population is negligible), or (b)
already durably logged in full via existing mechanisms (`agent_memory_
log`'s new `lesson`/`episodic_drifted` kinds, `events` table). Also
re-confirmed two longstanding capped lists (`Settlement.records`/
`memorials`) already have durable backing: every record's full text is
logged via the `record_written` event on write (`_apply_record`), and
every memorial's underlying death is logged via the `death` life
event — only the map-decoration detail (exact grave-marker position)
fades past `MEMORIALS_MAX_STORED=150`, which is intentional ("history
becomes physically visible... over the long run," not "every death
ever must remain visibly marked forever").

**Where real LLM memory growth is actually addressed**: this project's
whole history on this topic (see CLAUDE.md's "Diagnostic history
index") is that Python-side RAM has never been the source — it's
llama-server's own process heap over long real-time uptimes, fixed in
v0.86.9 via `LLAMA_RESTART_HOURS`. This pass found nothing to add to
that; the Python side remains genuinely bounded.

Verified: a real `_schedule_due_dialogue`/direct `dialogue.build_
prompt` call confirms a stored lesson matching a speaker's current
situation reaches the built prompt text, and the non-matching speaker
correctly gets no lesson line; `scripts/verify_native_soak.py` (2 seed
runs) byte-identical.

## [0.87.0] — "Learns like a human": lessons, memory drift, trait consequences, pattern-beliefs, consciousness trend

Explicit user directive: push emergent, persistent, disk-backed
learning as far as possible in one batch across every layer at once
(individual minds, collective/settlement, Town Consciousness/player
model, population-wide reach) and every mechanism discussed
(consequence-driven behavior change, smarter recall, gradual
forgetting/distortion, skill mastery through repetition) — small new
LLM call volume explicitly approved, main UI surfacing wanted, rest
scoped into a roadmap doc (`docs/VISION-2026-07-LEARNING.md`). Built as
two parallel tracks (this session + one background agent in an
isolated worktree) to cover the whole request in one pass.

**Individual minds — `Agent.lessons`** (`agents/agent.py`, `llm/
beliefs.py`, "smarter recall, not just storage"): new `MAX_LESSONS=4`
list of situation-tagged takeaways (`hunger`/`conflict`/`grief`/
`danger`/`social`, closed vocabulary — see `beliefs.LESSON_SITUATIONS`
— cheap deterministic matching, no embeddings), written by extending
the existing Reflect() job (zero added call volume; `beliefs.
parse_lesson`/`push_lesson`, evicts the oldest entry sharing the same
situation first). New `SimulationEngine._current_situation_tag`/
`_matching_lesson` deterministically classify an agent's CURRENT
situation and surface the one matching lesson into `cognition.
build_prompt` — the agent's most RELEVANT past takeaway now reaches
the prompt, not just whatever's newest regardless of relevance.

**Individual minds — memory drift** (`llm/memory_drift.py`, new
module, "gradual forgetting/distortion"): a deliberately NEW, rare LLM
call (the one small approved budget increase) — monthly round-robin,
core-cast only, gated to 20% chance
(`SimulationEngine.MEMORY_DRIFT_CHANCE`) on top of that — reinterprets
one of an agent's older memories in place (never the single freshest),
same "distortion via the existing memory mechanism" scoping
`InterpretRumor()` already established for rumors, applied instead to
an agent's own memory some time after formation. Non-critical
(`critical=False`): the fallback is a genuine no-op (leave the memory
exactly as it was), so a spent budget or failed call just means no
drift that month.

**Population-wide, zero-LLM-cost — trait consequences & skill mastery**
(`agents/population.py`, `agents/agent.py`): a successful dispute
reconciliation now nudges sociability up (`TRAIT_RECONCILE_NUDGE`) and
recovering from illness nudges resilience up
(`TRAIT_RECOVERY_RESILIENCE_NUDGE`) — the missing positive
counterparts to the existing negative-consequence nudges (feud ->
resilience down, sustained hunger -> resilience down). Crossing
`MASTERY_THRESHOLD` on any skill now also plants a durable memory
("Became a master of farming/construction after years of practice")
and logs a `skill_mastered` event, alongside the existing ambition
nudge — mastery is now narrated, not just numerically tracked.

**Collective/settlement — pattern-beliefs** (`settlement/buildings.py`,
`simulation/engine.py`): new `Settlement.pattern_signal_counts`
(`dispute_feud`/`starvation_death` running counts, same
accumulate-threshold-reset shape as the existing `ritual_signal_
counts`) — once a count crosses `PATTERN_SIGNAL_BELIEF_THRESHOLD=3`
in a season, the monthly settlement-beliefs job gets one extra
deterministic "pattern noticed" sentence folded into its prompt
(zero added call volume), giving the town a chance to form a real
belief about a RECURRING hardship instead of only ever reacting to
whichever single event is freshest.

**Town Consciousness — player-pattern trend** (`llm/consciousness.py`,
`simulation/engine.py`): new `SimulationEngine._player_intervention_
trend` computes a deterministic increasing/decreasing/steady read on
`/intervene/*` frequency (90-day rolling comparison) from `World.
consciousness_intervention_log`, folded into the existing monthly
consciousness prompt as one more line — zero added call volume.
Deliberately dev-console/raw-state only, NOT the main UI, per the
Phase G ambiguity discipline's standing exception for consciousness/
player_standing-adjacent state (CLAUDE.md) — this is the one piece of
the batch that doesn't get main-UI surfacing, and why is spelled out in
`docs/VISION-2026-07-LEARNING.md`.

**UI**: new "Lessons learned" NPC-inspector section (between "Their
own reflections" and "Full life history"); new `lesson`/
`episodic_drifted` memory-log kind labels.

**Docs**: `docs/VISION-2026-07-LEARNING.md` (new) records what shipped
here and scopes 8 explicitly deferred next-increment items (dialogue
consumption of lessons, non-core-cast learning, real semantic-
similarity retrieval, cross-generational lesson inheritance, deeper
pattern-recognition, richer consciousness narrative modeling,
continuous memory fade, LLM-narrated mastery) per the user's own
"scope the rest into a roadmap" instruction.

Verified: direct tests exercising the real production code paths —
`push_lesson`'s same-situation-first eviction; a real `_maybe_
schedule_personal_belief` call confirms a lesson lands on `Agent.
lessons` and `_current_situation_tag`/`_matching_lesson` correctly
retrieve it; a real `_maybe_schedule_memory_drift` call confirms
in-place replacement (list length unchanged, freshest memory never
touched); `Agent.lessons` round-trips through `to_dict`/`from_dict`,
legacy snapshots default cleanly to `[]`; `Population.apply_dispute`
reconciliation confirmed to nudge sociability up; a real `_maybe_
schedule_beliefs` call with the pattern counter forced past threshold
confirms the extra sentence reaches a captured prompt and the counter
resets; `_player_intervention_trend` confirmed empty pre-history and
correctly reads "increasing" from synthetic log data.
`scripts/verify_native_soak.py` (multiple seed runs, both the personal
Reflect()-extension work and the deterministic trait/pattern work)
byte-identical throughout — this batch's LLM-path changes don't touch
per-tick deterministic state, and the deterministic pieces (trait
nudges, skill-mastery narration, pattern counters) were soak-verified
directly.

## [0.86.9] — Memory/swap re-audit for long runs + llama-server periodic restart

Direct response to a live report: "LLM memory usage... still increasing
and swapping has increased for very long runs." Re-audited every
capped/pruned in-process Python structure this project tracks
(`SimulationEngine`'s scheduling dicts/sets, `Agent.relationships`/
`trust`/`debts`/`memories`/`beliefs`/`secrets`, `Settlement.beliefs`/
`traditions`/`inventions`/`records`/`memorials`, `Institution.beliefs`,
`World.consciousness_*`, the `agent_memory_log`/`consciousness_log`
SQLite retention pruning added in v0.86.2/.3, `AgentStore`'s swap-with-
last compaction, wildlife herd caps) — every one confirmed still
correctly bounded; nothing newly added since the last audit (v0.86.3–
v0.86.8) introduced an unbounded structure. Verified live, not just by
inspection: a synthetic soak (fake instant-responding LLM client so the
full LLM-scheduling code path runs at volume without a real model,
population run from 40 to its cap) showed hearthmind's own RSS
plateauing in step with population (39.6MB@pop31 -> 41.3MB@pop99 ->
62.8MB@pop333, then flat) rather than climbing independently of it —
consistent with every prior memory audit this project has run
(CLAUDE.md's "Diagnostic history index": swap pressure has always
traced to the LLM server side, never this process).

Given that, the fix targets the one mechanism the Python-side audit
can't reach: llama-server's own process heap over a genuinely long
(days/weeks) uptime. `--defrag-thold` (existing, v0.78.5) only
defragments the KV cache; general heap fragmentation from many
different prompt/response allocation sizes accumulating over a long-
lived C++ process's lifetime is a distinct, well-known failure mode no
in-request flag reclaims — and matches the reported symptom shape
exactly ("increases on very long runs," not short ones). New
`LLAMA_RESTART_HOURS` (`scripts/run.sh`, default `0`/disabled): when
set, restarts llama-server on that real-time cadence to reclaim
fragmentation via a clean process restart. `start_llama_server`/
`wait_llama_ready` were extracted from the previously inline launch
block into reusable functions (zero behavior change for the default
`LLAMA_RESTART_HOURS=0` path — verified via a live smoke run) so the
new periodic-restart supervisor (a background subshell, coordinating
through a pidfile since a subshell can't write back to the parent
shell's `$llama_pid`) can call the exact same launch/readiness logic
the initial startup uses. hearthmind.server needs no changes to survive
a restart — a mid-restart LLM call fails over to the existing
deterministic fallback/defer path exactly as it already does for any
timed-out or errored call (CLAUDE.md, "Tick loop... LLM calls are
fire-and-forget async and must never block a tick").

Verified: a live smoke run of the unmodified default path
(`LLAMA_RESTART_HOURS=0`, `--llm-disabled`) confirms unchanged
startup/shutdown behavior; a live run against a mock llama-server (a
minimal HTTP stub answering `/health`) with a shortened restart
interval confirms the supervisor correctly kills the old process,
launches a replacement, updates the pidfile, and that `cleanup()` on
SIGTERM stops whichever llama-server pid is current — zero orphaned
processes after shutdown, hearthmind.server's own tick loop unaffected
(continues ticking and snapshotting through the restart window, LLM
calls transparently falling back during the brief gap).

## [0.86.8] — UI polish pass on v0.86.3–v0.86.7's newer panels

Explicit user directive: a dedicated frontend polish pass on the panels
that landed functionally in v0.86.3–v0.86.7 (per-agent `life_digest` +
"Full life history" memory log, `belief_digest`/`culture_digest`,
"Repairs & upkeep" and "Husbandry" stat tiles) but never got their own
visual-consistency pass. `hearthmind/interface/static/style.css` only —
no backend/Python files touched.

Found: `belief_digest`/`culture_digest` sat directly above `#beliefs-
list`/`#traditions-list`, but only `#traditions-list` had ever been
opted into the flat divider-list styling (`#traditions-list`/`#event-
log`/`#infrastructure-list`) — `#beliefs-list` (and, same gap,
`#folklore-list`/`#rituals-list`/`#inventions-list`/`#festivals-list`/
`#records-list`) were still on the browser's default bulleted `<ul>`,
so the two new digest panels read inconsistently right next to each
other despite being twins in the code. Extended the existing flat-list
selector group (and the matching `min-height: 200px` anti-jump rule) to
cover all of them. Gave `#belief-digest`/`#culture-digest` their own
block + bottom rule for breathing room above the now-zero-margin list
— using `:not(.hidden)` rather than a bare rule so it can't tie on
specificity with `.hidden{display:none}` and silently defeat the
toggle (the same landmine `.consciousness-indicator` hit in v0.82.0).

The NPC inspector's "Full life history" (`agent_memory_log`, v0.86.3)
section — verified live with an 18-entry seeded agent (mixed episodic/
semantic/belief/secret kinds, one 100+ word entry) — inherited the
generic `#npc-inspector-content ul li { padding: 2px 0 }` rule shared
by every other inspector list, which read as an undifferentiated wall
of text once entries ran a full sentence or more. `.npc-memory-log`
now gets its own divider styling matching the flat lists above instead
of a third list convention; confirmed via Playwright that the section's
own `max-height: 220px; overflow-y: auto` scrolls correctly (18 entries
measured at `scrollHeight: 1209` against `clientHeight: 220`) rather
than blowing out the modal, and that the long paragraph entry wraps
without horizontal overflow.

Minor accessibility/consistency items found while in there: `.event-
chip`/`.settlement-chip` had no `:hover` state (state changed only on
click via `.active`), added a subtle border/color hover cue matching
every other clickable chip/button in the file. `main`/`header` had no
`flex-wrap`, so a narrow viewport forced the sidebar to overlap the
fixed-size map canvas rather than stacking; added `flex-wrap: wrap` to
both — the sidebar now correctly wraps below the map at narrow widths.
Not fixed (flagged, not attempted — genuinely out of scope for a polish
pass, not a "new panel" issue): the map canvas itself renders at a
fixed pixel size and isn't responsive, so a very narrow viewport still
shows some horizontal scroll on the map itself; making the canvas
responsive would be a real redesign of the map rendering path, not a
CSS tweak.

Repairs & upkeep / Husbandry stat tiles were already built correctly
against the existing `.stat-tile` convention (same `title` tooltip,
`.label`/`.value` structure as Granaries/Vehicles/etc.) — audited, no
change needed. Map legend colors for `pasture`/`hatchery` were already
present in `BUILDING_COLORS`; no separate on-map legend UI exists to
update.

Verified live: `python -m hearthmind.server --llm-disabled` against a
throwaway DB seeded with rich state (nonzero `belief_digest`/`culture_
digest`, `buildings_repaired`/`vehicles_repaired`, a standing PASTURE/
HATCHERY, one agent with 18 durable `agent_memory_log` rows) +
Playwright (pinned chromium): details panel, NPC inspector with the
loaded memory log (scrolled through all entries), and a 480px-viewport
pass — screenshotted each, zero JS console errors (one pre-existing
404 for a missing `/favicon.ico`, unrelated to this change and present
before it too).

## [0.86.7] — Personal life-digest, repair/upkeep tally, animal & fish husbandry, wider invention scope

Four-part batch, explicit user direction: (1) "immediately start taking
steps for the LLM to 'learn' about the simulation" — extends the
digest/summarized-context pattern to the individual level; (2) UI
exposure of NPC repair/maintenance labor; (3) animal husbandry and fish
husbandry as deliberate food sources beyond farming; (4) invention
should be able to surface genuinely novel outcomes the simulation
wasn't explicitly built for.

### Added

- **`Agent.life_digest`** — one LLM-authored sentence condensing an
  agent's ENTIRE accumulated self-understanding (private beliefs +
  semantic memories together), the individual-scale counterpart to
  `Settlement.belief_digest`/`culture_digest`. Written by extending the
  existing Reflect() job (`_maybe_schedule_personal_belief`) — zero
  added LLM call volume, only overwritten on a genuine answer (job is
  `critical=True`). Fed back into the agent's own cognition prompt
  (`llm/cognition.py`'s `build_prompt`, new `life_digest` parameter) —
  this is the concrete "read persistent memory back into the LLM" loop
  closing at the personal scale, and shown in the NPC inspector's
  "Their own reflections" section.
- **`Settlement.buildings_repaired`/`vehicles_repaired`** — persistent
  counters of completed repairs (a building crossing back above
  `REPAIR_THRESHOLD`, a vehicle transitioning `BROKEN -> READY`), not
  every work-tick, so this reads as a discrete achievement tally.
  Surfaced in a new "Repairs & upkeep" UI stat tile — real NPC labor
  that had zero visibility anywhere before.
- **`BuildingKind.PASTURE`/`HATCHERY`** — deliberate animal/fish
  husbandry, distinct from wild grazer hunting and opportunistic fish
  foraging (both already mechanically real). Each standing building
  produces food into its own `stored_food` on two layers: a small
  passive trickle regardless of staffing (herds/stocks tend themselves,
  slowly) plus a substantially larger boost per well-fed, awake agent
  tending it (`Population._maybe_run_husbandry`, same "presence-driven
  production" shape `_maybe_run_workshops` uses for currency). PASTURE
  is foundable anywhere; HATCHERY requires a water-adjacent
  construction site (`choose_building_kind`'s new `water_adjacent`
  gate, same siting-constraint shape RAFT/BRIDGE already use).
  Withdrawable by hungry agents exactly like a GRANARY (`_maybe_forage`'s
  cultivated-food-source tier, generalized to accept all three kinds).
  Surfaced as a new "Husbandry" UI stat tile and given map colors.
- `llm/invention.py`'s `SYSTEM_PROMPT` widened beyond its original
  build/farm framing — the LLM is now invited toward whatever this
  settlement's specific history plausibly leads to (a husbandry
  technique, a genuinely new food source, a hardship-born medical
  remedy, or anything else), not steered into a fixed category list.
  Purely a prompt change: the JSON contract and mechanical effect
  (`tech_level += 1`) are unchanged, so a wilder answer never risks
  breaking anything downstream.

### Verified

- Direct engine test: a working personal_belief LLM client's
  `life_digest` field is written to `Agent.life_digest` and reaches a
  real cognition prompt.
- Direct test: `Population._maybe_repair` only counts a completed
  repair when condition crosses back above `REPAIR_THRESHOLD` (the
  mechanism's own re-eligibility gate — it never restores a building to
  a literal 1.0, so that was the wrong signal to count on).
- Direct tests: `choose_building_kind` never selects HATCHERY without
  `water_adjacent=True`, and does select it when true; husbandry
  production respects passive vs. tended rates and the capacity cap;
  withdrawal via `_maybe_forage` correctly draws from a PASTURE.
- Round-trip test: new Settlement/Building fields survive `to_dict`/
  `from_dict`; a legacy snapshot missing them defaults cleanly to 0.
- End-to-end test: a real 30,000-tick engine run (LLM disabled)
  organically founds a standing PASTURE via the normal construction
  pipeline with zero test-side scripting.
- `scripts/verify_native_soak.py` (2 seeds x 1000 ticks) byte-identical
  — no native module touched.

## [0.86.6] — Skip wasted folklore LLM calls with no rumor material

Constitution §7/§8 (LLM-call efficiency) pass. `_maybe_schedule_
folklore` (hearthmind/simulation/engine.py) previously made a real LLM
call every eligible month regardless of whether there was any rumor
material to condense — `llm/folklore.py`'s own `fallback_folklore`
already documents that it "only proposes a tale when there's real
rumor material to draw from," so a call against a prompt reading "No
rumors have been circulating lately" was near-guaranteed to spend real
LLM budget/latency confirming an answer already known deterministically
("most months that's the real, expected answer," per the function's own
docstring).

Now checks `rumor_events` before the backpressure check/LLM scheduling:
empty rumor material skips the call entirely (still marks the month
resolved, matching the existing observable "no folklore forms" outcome
exactly), non-empty rumor material is completely unaffected — same
"skip a call whose precondition guarantees a trivial result" discipline
`_maybe_schedule_invention`'s prosperity gate already uses. Also
audited `llm/jobs.py`, `llm/client.py`, `cognition.py`'s/`dialogue.py`'s/
`town_brain.py`'s prompt builders for redundant fields or oversized
token budgets — found nothing else concrete enough to change without
guessing ahead of live diagnostic data.

Verified: a direct engine test with a call-counting fake LLM client
confirms zero calls with no rumor events (month still marked resolved)
and exactly one real call once rumor material exists, unchanged from
before. `scripts/verify_native_soak.py` (2 seeds x 1500 ticks)
unaffected — LLM path disabled in that harness.

## [0.86.5] — Module 22: wildlife grazer-branch native port

Continues the R6 "opportunistic pure-math port" queue (Constitution §4).
Audited every remaining not-yet-ported physical-substrate module
(`world/hydrology.py`, `world/terrain_evolution.py`, `world/
disasters.py`, `economy/farms.py`, `settlement/buildings.py`) looking
for a fresh per-tick loop doing repeated scalar arithmetic — all five
turned out already native-ported from prior R6/R7 passes (bounded
random walk, farm grid tick, building/vehicle decay, wilt/flat-damage/
roll-batch sweeps, climate drift, reclaim). `world/wildlife.py`'s
`WildlifeGrid.tick` was the one remaining candidate: a per-tick loop
over every live herd/pack, with the GRAZER branch (node-consumption +
overgraze check + reproduce roll) being a self-contained per-herd scalar
computation with no cross-herd dependency — unlike the PREDATOR branch,
which needs a prey lookup across the herd dict and stays in Python.

New `cpp/src/wildlife_step.cpp` exposes `grazer_tick_step`, bundling the
three GRAZER-branch operations into one call; the reproduce roll is
drawn by the caller (`rng.random()`) and passed in, preserving RNG draw
order exactly, same discipline as `bounded_random_walk_step`'s jitter
and `roll_passes_tick`'s pre-drawn rolls. `world/wildlife.py` gained the
standard try/except-ImportError native-fast-path wiring with an
identical pure-Python fallback; herd/dict iteration and movement
(terrain-dependent candidate search) stay in Python either way.

Verified: 300,000-case randomized equivalence test (0 mismatches);
`scripts/verify_native_soak.py` full-state hash soak (2 seeds x 1500
ticks) confirms byte-identical output with the native path on vs. off.

## [0.86.4] — Durable belief + secret history (extends v0.86.3)

Direct extension of v0.86.3's `agent_memory_log`, per explicit user
request to keep pushing engineered emergent learning further. Two more
gaps closed:

### Added

- **`kind="belief"` rows**: every private belief `Agent.beliefs` has
  ever formed OR revised (logged unconditionally in `_maybe_schedule_
  personal_belief`'s `apply()`, not gated on whether it was a new entry
  vs. a revision) — the personal counterpart to `Settlement.beliefs`,
  which was already durably logged via `_log`'s "belief_formed"/
  "belief_revised" events since it's a settlement-scoped job. A personal
  belief past `MAX_PERSONAL_BELIEFS` (weakest-confidence eviction) was
  previously lost with zero record anywhere.
- **`kind="secret"` rows**: every secret `Agent.secrets` has ever held,
  at both write sites — the Reflect()-authored secret in `_maybe_
  schedule_personal_belief`, and the deterministic dispute-feud-planted
  secret in `_maybe_schedule_dispute`. `MAX_SECRETS=2` is a very small
  FIFO cap, so a secret was easily displaced by a second one with no
  trace.
- Frontend: the NPC inspector's "Full life history" section now labels
  these kinds distinctly ("private belief", "secret") instead of
  falling back to the generic "memory" label.

### Verified

- Direct engine test exercising the REAL `_maybe_schedule_personal_
  belief` and `_maybe_schedule_dispute` methods (not a re-implementation
  of their logic): 3 belief-job calls durably log exactly 3 belief rows
  and 3 secret rows with the correct marker text; a real feud outcome
  (agents seeded with a mutually deeply-soured relationship so `due_
  for_dispute` selects them) durably logs the correct resentment text.
- Native soak (2 seeds x 800 ticks) byte-identical — no native module
  touched.

## [0.86.3] — Emergent per-agent + town learning, disk-backed, main-UI visible

Direct response to explicit user direction: highest priority is
**engineered emergent learning** — the LLM never retrained, but the
simulation should appear to learn continuously through persistent,
summarized, disk-backed context, and this learning should be **visible
to the observer**, not hidden. User confirmed scope via clarifying
questions: per-agent AND world/settlement, main-UI surfaced, both raw
retention and distilled summaries.

### Added

- **`agent_memory_log` SQLite table** — the durable per-agent
  counterpart to v0.86.2's `consciousness_log`, but deliberately
  **main-UI visible** (not dev-console-only): `kind="episodic"` rows are
  significant memories evicted from `Agent.memories` past its cap (8);
  `kind="semantic"` rows are every distilled self-theory `Agent.
  semantic_memories` has ever held (capped at 3 in RAM). Routine
  evictions (frequent food/tool/medicine-sharing notes) are deliberately
  excluded from the durable log to keep volume bounded to genuinely
  memorable moments, not noise — same "deprioritized, never hidden"
  treatment `working_memory` already gives routine entries.
- `Population._pending_memory_evictions`: a transient module-level
  buffer `_remember`'s eviction branch appends to (only on a non-routine
  call), drained and durably logged by `SimulationEngine._tick_once()`
  every tick. Module-level rather than an instance field because
  `_remember` receives only `agent`, with no reference back to its
  owning Population/the engine's DB connection — see its docstring for
  why this is safe under the project's single-threaded-asyncio,
  one-World-per-process tick loop.
- `_maybe_schedule_personal_belief`'s `apply()` now also durably logs
  every real semantic-memory write (`kind="semantic"`) — reuses the
  existing Reflect() job entirely, zero added LLM call volume.
- `snapshot.log_agent_memory_entry`/`recent_agent_memory_log`/
  `agent_memory_log_count`/`_prune_agent_memory_log`, new `Config.
  agent_memory_log_retention=100_000` (global, not per-agent — bounds
  total DB growth regardless of population size), pruned on the
  snapshot cadence.
- **`GET /agents/{id}/memory_log`** — an NPC's full durable history,
  fetched on demand (not part of the hot broadcast payload).
- **Main UI**: NPC inspector gained a "Full life history" section with
  a "Load full life history from disk" button, showing every durably-
  logged entry (newest first) once fetched — the `agent.memories`/
  `semantic_memories` shown elsewhere in the inspector are still only
  the small in-RAM tail; this reaches everything, past those caps.
  `Settlement.belief_digest`/`culture_digest` (already computed since
  v0.85.4/.5 but never actually rendered anywhere) now show above the
  "The village's own theories"/"Traditions" panels — a real gap fixed:
  the town-level engineered-learning signal existed in every prompt but
  was invisible to any observer until now.

### Verified

- Direct unit test: a non-routine `_remember` eviction buffers correctly;
  a routine one does not (noise exclusion holds).
- End-to-end engine test: `_tick_once()` drains the buffer into the
  durable table (evicted text retrievable via `recent_agent_memory_log`);
  a forced `_maybe_schedule_personal_belief` call durably logs the real
  semantic-memory text.
- Pruning test: `_prune_agent_memory_log` correctly trims to the keep
  count; `keep<=0` correctly no-ops rather than deleting everything.
- Live end-to-end: real server + `GET /agents/{id}/memory_log` returns
  seeded entries correctly through the full FastAPI stack.
- Live browser (Playwright) verification: `#belief-digest`/`#culture-
  digest` render the correct text once the details panel is open; the
  NPC inspector's "Load full life history" button correctly fetches and
  renders all 6 seeded entries (5 episodic + 1 semantic) for a test
  agent, newest-first; zero uncaught JS errors during the flow.
- `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
  no native module touched.

## [0.86.2] — Durable Town Consciousness history to disk (Engineering Constitution §6)

First slice of §6 ("efficient persistent storage... cold information
belongs on disk, not permanently in RAM") from the sequenced follow-up
to v0.86.0. Audited every capped in-RAM list against this rule first:
`Settlement.traditions`/`inventions`/`festivals`/`folklore`/`rituals`/
`records` are all capped small in RAM, but every formation is ALREADY
durably logged via `SimulationEngine._log()` → the `events` table
(200k-row retention) — so culture/history already satisfies §6. The one
genuine gap: `World.consciousness_memory`/`consciousness_player_model`/
`consciousness_objectives`/`consciousness_intervention_log` (Phase N,
"Town Consciousness") are capped tiny (16/6/2/12) with **no durable
record at all** — an entry past the cap was silently and permanently
forgotten, unlike everything else.

### Added

- **New `consciousness_log` SQLite table** (`hearthmind/persistence/
  database.py`), deliberately SEPARATE from `events` rather than a new
  event category: the consciousness's private inner memory/theories/
  objectives must never leak into `recent_events`/`recent_events_
  diverse`, which every other settlement-scoped LLM prompt (chronicle,
  town_brain, beliefs, ...) reads — mixing them would break the "hidden
  intelligence... nudging through deniable channels" design.
- `snapshot.log_consciousness_entry`/`recent_consciousness_log`/
  `consciousness_log_count`/`_prune_consciousness_log`, same shape as
  the existing `events`/`metrics` helpers. Pruned on the snapshot
  cadence via new `Config.consciousness_log_retention` (default 5,000 —
  centuries of headroom at the job's monthly cadence).
- `SimulationEngine._maybe_schedule_consciousness`'s `apply()` now logs
  every memory note/player-theory/objective/intervention to the durable
  table ALONGSIDE (not instead of) the existing capped in-RAM lists,
  which are untouched — this is additive, not a behavior change to
  prompt-building or snapshot size.
- `full_diagnostics()`'s `consciousness` dict gained `durable_log_count`
  — dev-console-only, same Phase G/N ambiguity discipline as
  `temperament`/the rest of that dict (no main-UI surfacing).

### Verified

- End-to-end engine test: ~30 in-game months with a client returning a
  uniquely-marked consciousness result each call confirms (1) the
  in-RAM `consciousness_memory` list stays capped at 16 exactly as
  before, (2) the durable `consciousness_log` count exceeds 16, (3) the
  earliest marker note — already evicted from RAM by then — is still
  retrievable from the durable log (the actual fix, not just a
  duplicate write), and (4) zero consciousness marker text appears in
  `recent_events_diverse()`, confirming no leakage into other jobs'
  prompts.
- `scripts/verify_native_soak.py` unaffected — no native module touched.

## [0.86.1] — Module 21: road-wear native port

Continues the R6 "opportunistic pure-math port" queue (Constitution §4:
"prefer C++ for performance-critical systems"). `RoadNetwork.tick`
(world/roads.py) runs every tick over every occupied and every worn
tile, doing scalar gain/decay arithmetic per tile — same shape as
module 20's `relationship_step`. New `cpp/src/road_wear.cpp` exposes
`road_wear_gain_step`/`road_wear_decay_step`; the sparse tile->wear
dict iteration and prune-on-fade-to-zero deletion stay in Python (not a
flat-array fit per the R8 scoping pass), only the per-tile arithmetic
moves to C++. `world/roads.py` gained the standard try/except-ImportError
native-fast-path wiring with an identical pure-Python fallback.

Verified: 400,000-case randomized equivalence test (0 mismatches);
`scripts/verify_native_soak.py` full-state hash soak (2 seeds x 1500
ticks) confirms byte-identical output with the native path on vs. off.

## [0.86.0] — Critical cognition defers, never fabricates (Engineering Constitution §3/§7)

First implementation pass against the new **Hearthmind Engineering
Constitution** (docs/CONSTITUTION.md). The Constitution reorders the
project's priorities — Emergent cognition > world behaviour > learning >
memory > performance > code quality > deterministic physics > save
compatibility — and adds one principle that directly reverses prior
architecture:

> "Never replace [crucial cognition] with simplistic deterministic
> fallbacks simply to keep the simulation running. If cognition falls
> behind, slow or pause the simulation instead." (§3, §7)

Previously **every** LLM job — including the individual minds' goal
reasoning, belief revision, the town brain, dreams, and the town
consciousness — resolved to a *fabricated* deterministic substitute
whenever the real call couldn't run (daily budget spent) or failed
(timeout/error). That kept throughput up at the cost of quietly
replacing genuine cognition with rule-based output, exactly what the
Constitution forbids.

### Changed

- **`SimulationEngine._schedule_llm_job` gained a `critical` flag.** A
  critical job is one whose deterministic fallback would be a fabricated
  substitute for genuine cognition rather than an objective-reality
  answer. For a critical job, when the real call can't happen (daily
  ceiling reached) or fails (timeout/error), `apply` is **not** called
  with a fabricated result — the relevant state is left exactly as it
  was and the job re-attempts on its next natural cadence. Marked
  critical: `beliefs`, `town_brain`, `personal_belief`, `dream`,
  `consciousness` (the last already hand-rolled this via a `used_
  fallback` early-return; the flag generalizes the pattern). Ambient/
  narrative jobs (chronicle, tradition, folklore, invention, festival,
  religion, narrative_direction, culture_digest, caravan, omen, naming,
  record, geography, faction, guild_founding, institution_belief,
  dispute, market_prices) keep their deterministic fallback — those
  genuinely have a sensible deterministic answer and are ambient
  texture, not crucial cognition.
- **Per-agent cognition defers instead of fabricating.** In `_schedule_
  due_cognition`, a core-cast agent at a genuinely significant/triggered
  moment that hits the daily LLM ceiling now keeps its current
  LLM-authored goal and is re-evaluated at its next staggered slot,
  rather than snapping to a rule-based `fallback_goal`. Likewise
  `_run_cognition` on a timeout/error leaves the agent's current goal in
  place instead of writing a fabricated one. Physical survival is
  unaffected — the deterministic critical-hunger movement override (D5)
  still forces foraging regardless of goal, so deferring the *goal* call
  never risks starvation. This is the Constitution's deterministic-
  physics / LLM-meaning split working exactly as intended: objective
  reality (survival movement) stays deterministic and always-live, while
  the *interpretation* (what to pursue) waits for real cognition. The
  significance gate is untouched — a routine "gather or socialize today"
  is mundane by design and still uses the deterministic goal (the
  Constitution explicitly assigns mundane routines to deterministic
  systems, §3).
- The existing live-backlog pacing (`run_forever`/`llm_pressure_paused`,
  v0.82.0) is the mechanism that *gives inference time to catch up* —
  the world already slows and then pauses ticking under sustained LLM
  backlog. This batch makes the other half true: the work that does get
  deferred waits for genuine cognition instead of being faked.

### Added

- **`CognitionRunner.calls_deferred_critical`** counter, surfaced in
  `stats()` → `/diagnostics.llm_stats` → the dev console (same path as
  `calls_dropped_backpressure`, no front-end change needed). A rising
  count against a low `calls_succeeded` now reads as "the LLM can't keep
  up and the world is correctly waiting for it," distinct from silent
  degradation.
- **docs/CONSTITUTION.md** — the Engineering Constitution, checked in as
  the canonical priority/architecture guide it declares itself to be.

### Verified

- End-to-end engine test (`test_critical_defer.py`): with an
  always-failing LLM client over ~3 in-game months, critical belief
  jobs form **zero** fabricated beliefs and `calls_deferred_critical`
  climbs, while non-critical chronicle fallbacks keep flowing (no
  over-deferral); a control run with a working belief client confirms
  the critical jobs DO mutate state (real LLM-authored beliefs appear) —
  proving the deferral is failure-specific, not a permanent disable.
- `scripts/verify_native_soak.py` unaffected — this batch touches no
  native module (the LLM path is disabled in that harness, so its
  byte-identical guarantee is unchanged).

## [0.85.6] — Whisper routing fix, parallel g++ build, relationship-step native port

Three-part batch: a real bug fix found while investigating a live "I've
whispered to the town brain many times and it never visibly does
anything" report, a build-speed request ("make g++ use all available
threads"), and continued incremental C++ porting per the standing R6
opportunistic-port queue.

### Fixed

- **Whisper/settlement-nudge routing bug.** `POST /intervene/town-brain`
  and `POST /intervene/settlement` always applied to the FOUNDING
  settlement (`world.settlement`) server-side, regardless of which
  settlement the player had selected in the UI. In a single-settlement
  world (the common case) this is invisible — but `_maybe_schedule_
  town_brain`'s round-robin `_job_target()` only reads a given
  settlement's `player_influence` on that settlement's own turn, so in
  a post-fission multi-settlement world a whisper aimed at a
  non-founding settlement could sit queued and unread for many months,
  reading as "whispering does nothing." Fixed: both endpoints accept an
  optional `settlement_id` (the whisper form now sends the UI's active
  settlement); `SimulationEngine._apply_intervention` resolves the
  target settlement via `_settlement_by_id`, falling back to the
  founding settlement when omitted (old, still-correct behavior for a
  single-settlement world). Verified via a direct test: a whisper with
  `settlement_id` lands on that exact settlement and reaches its
  `town_brain` prompt; a whisper without `settlement_id` still falls
  back to the founding settlement; `settlement_resources` respects
  `settlement_id` the same way.

### Changed

- **Parallel g++ compilation.** `setup.py`'s `BuildExtOptional` now
  defaults `build_ext`'s stock `--parallel`/`-j` option to `os.cpu_
  count()` instead of distutils' own default of 1 — a bare `pip install
  -e .`/`python setup.py build_ext --inplace` (as `scripts/run.sh` runs
  on every launch) previously compiled this extension's ~20 .cpp files
  one at a time. Confirmed via a live rebuild: multiple `cc1plus`
  processes now run concurrently instead of strictly one-at-a-time.

### Added

- **`cpp/src/relationship_step.cpp`** (module 20, continuing the R6
  opportunistic-port queue): native fast path for the two scalar
  operations inside `Population._update_relationships` — decay-toward-
  zero and colocation-gain-capped-at-1.0. Same shape as module 12
  (`bounded_random_walk.cpp`): the per-agent dict iteration,
  `itertools.combinations` pairing, and prune-on-reach-zero bookkeeping
  all stay in Python (variable-size per-agent dicts, not a fit for a
  flat-array port per the R8 scoping pass); only the per-value
  arithmetic moves to C++. Optional, pure-Python fallback identical.
  Verified via a 200,000-case randomized equivalence test (native ==
  pure-Python exactly, zero mismatches) and `scripts/verify_native_
  soak.py`'s full-state hash comparison (new toggle entries added).

## [0.85.5] — Culture digest: an occasional LLM job to summarise accumulated history

Direct follow-up to v0.85.4, per explicit request: "maybe we can cue an
LLM job occasionally to summarise large prompts." v0.85.4's
`belief_digest` was free (it extended an existing monthly job) — but
`Settlement.traditions`/`inventions`/`festivals`/`records` have no
natural "revise the whole list" call to piggyback a digest onto, so
this is the generalization: a genuinely new, deliberately infrequent
job, on the same quarterly cadence `llm/narrative_direction.py`
already established (`season_end` — a season already IS a real-
calendar quarter, no new cadence machinery needed).

### Added

- New `llm/culture_digest.py`: one short LLM-authored sentence
  condensing the overall shape of the settlement's accumulated
  traditions/inventions/festivals/records — the `belief_digest`
  treatment applied to culture and history. `fallback_digest()` is a
  genuine no-op ("no call -> no update this quarter"), same discipline
  as `llm/consciousness.py`; `Settlement.culture_digest` is only
  overwritten on a real (non-fallback) answer, never fabricated by the
  deterministic path.
- New `Settlement.culture_digest: str`, wired through `__init__`,
  property passthrough, `to_dict`/`from_dict`/`summary()` — same shape
  as `belief_digest`; a legacy snapshot missing the field defaults
  cleanly to `""`.
- `SimulationEngine._maybe_schedule_culture_digest`, registered in
  `_TICK_JOBS` right after `narrative_direction`: one call per season,
  round-robin `_job_target()`-scoped so volume stays flat regardless of
  settlement count. Input bounded by new `CULTURE_DIGEST_INPUT_MAX=30`
  (newest N of each list) so this job's own prompt can't itself grow
  unbounded on a very long-running world, even though it deliberately
  sees more history than the `PROMPT_CULTURE_LIST_MAX=5` slice that
  reaches `chronicle`/`town_brain` directly.
- `chronicle.py`/`town_brain.py` both gained a `culture_digest`
  parameter, read as one additional grounding line alongside the
  existing `belief_digest` line — same "if it fits" treatment as
  folklore/narrative_theme.

### Verified

Direct tests: `culture_digest.parse_digest`/`fallback_digest`/
`build_prompt` validated directly; a real end-to-end engine test
confirms the job fires on a synthetic `season_end` event, writes
`Settlement.culture_digest` from a real (non-fallback) result, and that
the digest reaches both a captured `chronicle` prompt and a captured
`town_brain` prompt; a forced-failure follow-up call confirms the
stored digest is retained unchanged rather than cleared or
overwritten. `culture_digest` round-trips through `to_dict`/
`from_dict`/`summary()`. A 3-seed x 15,000-tick engine soak (LLM
disabled — this change is LLM-path-only, soak confirms no import/
serialization regression) completes with zero crashes.

## [0.85.4] — Intelligent belief digest, replacing blind slicing

Direct follow-up to v0.85.3's fix, per explicit request: "instead of
just slicing the prompts can we intelligently summarise it, without
losing much of the context?" v0.85.3's `PROMPT_BELIEFS_MAX` slice
(newest N beliefs) bounded the token cost but silently drops whatever
falls out of the recency window — a real theory the village holds,
just an older one, loses all representation in `chronicle`/`town_
brain` prompts.

### Added

- New `Settlement.belief_digest: str` — one short LLM-authored sentence
  condensing the overall shape of the settlement's ENTIRE current
  belief set (not just the newest few). Written by extending the
  existing monthly belief-forming/revising job (`llm/beliefs.py`) with
  one extra requested field — **zero added LLM call volume**, the same
  "extend an existing job" discipline `Agent.semantic_memories`/
  `Agent.mind` already established, rather than a separate
  summarization call that would cost real budget just to shrink a
  prompt.
- `llm.beliefs.parse_digest` extracts/validates the field; only
  overwrites `belief_digest` on a genuine (non-fallback) LLM answer —
  retained across a flaky-LLM stretch, never fabricated by the
  deterministic fallback, same discipline `player_influence`/`omen_
  seed`/`dream_seed` already use (verified directly: a forced
  fallback-only stretch leaves a previously-set digest untouched).
- `chronicle.py`/`town_brain.py` now read `belief_digest` as the
  primary "what does the village believe" line, alongside a much
  smaller raw-belief slice (`PROMPT_SETTLEMENT_BELIEFS_MAX=2`, down
  from `PROMPT_BELIEFS_MAX=5`) for concrete grounding — digest for
  overall shape, a couple of specifics on top, the same split `Agent.
  semantic_memories` already has alongside raw `Agent.memories`.
  `town_brain`'s `council_beliefs` (a narrower per-institution list,
  no digest mechanism) keeps the plain `PROMPT_BELIEFS_MAX` slice.

### Verified

Direct tests: `parse_digest` validates/truncates correctly; a real
end-to-end engine test confirms the digest reaches both a captured
chronicle prompt and a captured town_brain prompt once the belief job
has run at least once; a forced fallback-only stretch after one real
success leaves the stored digest exactly unchanged. `belief_digest`
round-trips through `to_dict`/`from_dict`/`summary()`; a legacy
snapshot missing the field defaults cleanly to `""`. A 5-seed x
15,000-tick engine soak (LLM disabled — this change is LLM-path-only,
soak confirms no import/serialization regression) completes with zero
crashes.

## [0.85.3] — Audit: prompt growth over a long-running world

Direct response to an explicit request: "check for prompt growth over
multiple in-game decades, we should summarise large prompts and keep
them bounded."

### Audit method

A real multi-decade simulated run isn't practical to wait out in a
session (96 ticks/day * 365 = 35,040 ticks/year — even 200,000 ticks is
only ~5.7 years). Instead, directly measured every settlement-scoped
and per-agent `build_prompt` function against a *synthetically
saturated* Settlement/Agent — every capped list (`Settlement.
traditions`/`inventions`/`festivals` at `CULTURE_LIST_MAX_STORED=300`,
`folklore` at `FOLKLORE_MAX_STORED=24`, `rituals` at `RITUAL_MAX_
STORED=12`, `beliefs` at `llm.beliefs.MAX_BELIEFS=12`, `records` at
`RECORDS_MAX_STORED=40`, `Agent.memories`/`semantic_memories`/`secrets`
at their own caps) filled to its ceiling, the state any sufficiently
long-running world eventually reaches and then stays at. This measures
the actual steady-state plateau directly rather than waiting for RNG
to reach it.

### Findings

Every collection this project's own prior memory-leak audits already
capped in *storage* (traditions/inventions/festivals/folklore/rituals/
beliefs/records/narrative_themes, plus per-agent memories/semantic
memories/secrets) is in fact bounded — confirming those audits did
their job. Most `build_prompt` callers already additionally slice down
to a smaller *prompt* budget on top of the storage cap (`PROMPT_
CULTURE_LIST_MAX=5` for traditions/inventions, internal `[-N:]` slices
in `chronicle.py`/`narrative_direction.py`/`religion.py`/`omens.py` for
folklore/omens). `Settlement.place_names` has no explicit cap but is
naturally self-limiting (keyed by a fixed geographic feature per map:
one river, one entry per lake — bounded by world generation, not
runtime accumulation).

**Two real gaps found**: `chronicle.py` and `town_brain.py` both
received the *entire* capped `Settlement.beliefs` list unsliced (`town_
brain` sends TWO such lists — settlement and council). At full
saturation this measured ~1291 and ~1442 tokens respectively — more
than half of `Config.llm_num_ctx=2560` on the prompt alone, before the
system prompt (~100-130 tokens) or the reserved `llm_num_predict=448`
response budget, on a prompt that will genuinely reach this size on any
world that runs long enough for its belief list to fill up (not a
hypothetical edge case).

### Fixed

New `SimulationEngine.PROMPT_BELIEFS_MAX=5`, same "bound the prompt,
not the store" shape as the existing `PROMPT_CULTURE_LIST_MAX` — applied
at all five belief-list-into-prompt call sites (`chronicle`,
`invention`, `festival`, `town_brain`'s settlement beliefs, `town_
brain`'s council beliefs). `Settlement.beliefs`/`Institution.beliefs`
still persist their full capped list; this only bounds what reaches
the prompt. `llm/beliefs.py`'s own belief-*revision* job prompt
(`existing_beliefs`) was deliberately left unsliced — that job
genuinely needs the current full belief set to correctly merge/revise
without duplicating an existing belief, and it measured under budget
(~1118 tokens) even unsliced.

### Verified

Re-measured every prompt against the same saturated worst case after
the fix: `chronicle` ~1158 tokens (was ~1291), `town_brain` ~1176
tokens (was ~1442) — both now comfortably under budget even summed
with their system prompt and `llm_num_predict`. A direct end-to-end
engine test (fake LLM client, settlement beliefs forced to the full
`MAX_BELIEFS=12` with uniquely-markered text) confirms the real
production code path — not just the standalone measurement script —
sends exactly 5 beliefs to both a captured chronicle prompt and a
captured town_brain prompt.

## [0.85.2] — Fix: NPCs weren't actually repairing buildings

Direct response to a live report: "make sure NPCs actually repair/
maintain buildings and other infrastructure. Looks like they aren't."

### Root cause

`Population._maybe_repair` only ever fires from incidental colocation
(an awake agent already standing on a damaged building's tile), and
the deterministic movement layer (`_dispatch_movement`'s WANDER
branch) already biases WANDER-goal agents toward the nearest damaged
building via `work_positions`. But with a live LLM choosing goals
(the project default), `llm/cognition.py`'s prompt never told the
model a building needed repair, or that `'wander'` was how an agent
would go help with one — the model had no information to rationally
choose it over forage/socialize/gather, so repair was left to chance
colocation and whatever sliver of goal choices happened to land on
'wander' for unrelated reasons. Roads are unaffected (self-maintaining
via foot traffic, no agent decision involved) — this was specifically
a buildings/repair information gap in the LLM-cognition path, not a
missing mechanic.

### Fixed

- `llm/cognition.py`'s `SYSTEM_PROMPT` now explicitly explains that
  `'wander'` covers going to help repair a nearby building, and that a
  building needing repair is worth leaning toward `'wander'` for
  regardless of personality — the same weight `'gather'` already gets
  for an ambitious villager.
- `build_prompt` gained `needs_repair: bool = False`; when true, the
  prompt adds one grounding sentence ("A building nearby has fallen
  into disrepair and could use a hand — 'wander' would take you
  there."), the same "ground the choice in what's actually reachable"
  treatment `nearest_food_steps` already gets for `'forage'`.
- `SimulationEngine._schedule_due_cognition` computes `needs_repair =
  bool(population.damaged_building_positions(home))` and passes it
  through — the deterministic side (`work_positions`) was already
  correct; this closes the information gap on the LLM side.
- The deterministic fallback path (`fallback_goal`, used when the LLM
  is disabled/unreachable/off-budget) was not changed — it already
  sends roughly a third of "content" agents to WANDER, which already
  gets biased toward damaged buildings deterministically; that path
  was not the reported gap.

### Verified

Direct prompt-construction tests confirm `needs_repair=True` adds the
repair sentence and `False` omits it. A real end-to-end engine test
(fake always-succeeding LLM client, a building forced below
`REPAIR_THRESHOLD`, emotions forced to trigger the significance gate so
real cognition calls fire) confirms an actual captured cognition prompt
correctly includes the repair sentence.

## [0.85.1] — Fix: population stuck at 0 never recovers

Direct response to a live 60,000-tick diagnostic: `population_total: 0`
with no path back, despite v0.85.0's below-core-cast migrant trickle —
that trickle explicitly excluded `count == 0` ("a fully extinct
settlement is a legitimate, permanent ending, not something to
auto-revive" — the project's own prior standing rule). The user asked
for this fixed rather than kept as a legitimate ending, so this is a
direct reversal of that rule, not a bug in its implementation.

### Fixed

- `Population._maybe_welcome_migrant` now also fires at `count == 0`,
  using the same chance formula as the near-extinction band (no
  openness term — there are no survivors to have an opinion, avoids a
  divide-by-zero).
- New `Population._center_walkable_tile(terrain)`: a settlement that
  has hit 0 population *and* had every building fully decay away and
  get reclaimed (`settlement.buildings` empty — confirmed to be
  exactly what happened in the live diagnostic: `building_completed`,
  `building_ruined`, and `building_reclaimed` were all equal at 3) has
  no building or survivor position to anchor a migrant's arrival on,
  since settlements are never pre-placed. Scans outward ring-by-ring
  from the map's geometric center for the nearest walkable tile — a
  neutral, always-available resettlement anchor. `terrain` threaded
  through `Population.tick()` (already available there) to this call
  site; without it (legacy/test callers), a buildingless 0-population
  resettlement is safely skipped rather than risking a migrant placed
  in water.
- `CLAUDE.md`'s prior standing rule ("true extinction is a legitimate
  permanent ending... never auto-revive an empty world") updated to
  record the reversal — do not reintroduce the old behavior without an
  equally explicit instruction.

### Verified

Direct unit tests: `_center_walkable_tile` finds the correct nearest
walkable tile when the map center itself is water, and correctly
returns `None` on a fully unwalkable map (no crash, resettlement
skipped that tick); `_maybe_welcome_migrant` with 0 population, 0
buildings, and terrain supplied resettles within the expected number
of ticks at the map center. A real end-to-end `World.tick()` test —
population and buildings force-wiped to reproduce the live scenario
exactly — confirms resettlement happens through the actual production
code path, not just the isolated Population method. A 5-seed x
12,000-tick engine soak, two of which force an extinction event
mid-run (with and without remaining buildings), confirms no crash and
recovery in both cases.

## [0.85.0] — Repopulation, model default, snow, dialogue variety, doc trim

Batch response to several live requests in one turn.

### Added

- **Repopulation from outside**: `Population._maybe_welcome_migrant`'s
  gate was previously only `POPULATION_CRITICAL_THRESHOLD=4` (a
  near-extinction rescue). Now also fires, at a gentler trickle
  (`MIGRANT_BELOW_CORE_CAST_CHANCE_MULT=0.25`), whenever world
  population falls below `Config.llm_core_cast_size` (default 14) —
  explicit request: a town short of its LLM-authored cast size should
  be able to draw newcomers "from other villages... outside" to
  rebuild toward it, not only once down to a handful of survivors.
  Threaded through `Population.tick(core_cast_target=...)` and
  `World.tick()`. Migrant flavor text updated to explicitly say
  "from a village elsewhere" / "from outside".

### Changed

- **Default LLM model** `qwen3:4b-instruct` -> `gemma-4-e2b-it`, per a
  live report that it performs best on the user's hardware — trusted
  as-is per this project's standing policy on live model reports (see
  `Config.llm_model`'s docstring). No other LLM tuning knob changed
  alongside it; report back real `/diagnostics` numbers if it needs
  its own re-tune.
- **Snow probability in winter raised**: `SNOW_TEMPERATURE_THRESHOLD_C`
  2.0 -> 3.5 (`world/weather.py`). Measured directly rather than
  guessed: at 2.0C, winter's realized `is_snowing` frequency was only
  ~1.6% of ticks (precipitation already clears its own threshold on
  ~100% of winter ticks — the gate was purely temperature-bound); 3.5C
  measures to ~16% of Dec/Jan/Feb ticks, near-zero in the shoulder
  months, per a live "increase the probability of snow in winter more"
  request.
- **Docs trimmed**: `CLAUDE.md`'s ~40 oldest "Current state" version
  sections (v0.65.2–v0.81.1) consolidated into one dense summary
  section (2595 -> 1024 lines) — full detail for that range remains in
  this file and `docs/DECISIONS.md`, nothing was lost, only
  de-duplicated out of the context-injected file. `docs/ROADMAP.md`
  (a now-fully-shipped phase checklist) trimmed to a status pointer
  (955 -> ~35 lines).

### Fixed

- **NPC dialogue over-indexing on food-sharing**: root cause was
  `_maybe_trade_food`/`_maybe_trade_tools`/`_maybe_trade_medicine`
  planting a "X shared food with me"-style memory via `_remember` on
  every successful barter (frequent — roughly once per hunger cycle
  per agent leaning on neighbors), which very often ended up as the
  single freshest entry in the strictly-FIFO `Agent.working_memory`
  that dialogue/cognition's "just now" line reads unconditionally.
  `_remember` gained a `routine: bool` parameter (new
  `ROUTINE_MEMORY_SALIENCE_MULT=0.5`): a routine memory is still
  recorded in episodic `memories` (nothing hidden) at a discounted
  salience (evicted sooner from the capped list) but never enters
  `working_memory` at all, so it can no longer crowd out whatever
  else actually just happened. The three trade call sites now pass
  `routine=True`.

### Verified

Direct unit tests: `_remember(..., routine=True)` skips working_memory
and lowers salience; a built dialogue prompt with both a routine trade
memory and a distinctive one correctly surfaces the distinctive one.
Migration: direct engine runs confirm migrants arrive at the expected
rate in both bands (near-extinction vs. below-core-cast) and not at
all once at/above the core cast target; the near-extinction rate is
unchanged from before this batch. Snow: direct 129,600-tick sample
across Dec/Jan/Feb confirms ~16.2% realized frequency post-change. A
5-seed x 15,000-tick engine soak (LLM disabled, mixed population sizes
and geographies) confirms no crash across all of the above combined.

## [0.84.4] — Fix: settlements can go unnamed/buildingless forever on unlucky geography

Direct response to a live report: a settlement stayed unnamed after
20,000 ticks, and some settlements never get any buildings at all.
Root-caused and fixed.

### Fixed

- **`Population._dispatch_movement`'s GATHER branch had no fallback**
  when no FOREST/HILLS tile fell within the small, fixed
  `GATHER_SEARCH_RADIUS` (6 tiles) of a GATHER-goal agent — unlike
  FORAGE (three fallback tiers) or SOCIALIZE (no radius cap at all),
  a GATHER agent with nothing nearby simply got `target=None` forever
  and degraded to a pure random walk. `Settlement.materials` then
  never crosses `HUT_MATERIALS_COST`, so the settlement can go tens of
  thousands of ticks with zero buildings — and since settlement naming
  itself gates on a STANDING building existing (`World.tick()`), it
  stays unnamed indefinitely too. Confirmed directly: a founding party
  whose nearest reachable material tile sits just outside the bounded
  radius stayed at exactly 0.0 materials / 0 buildings / unnamed
  through a full 20,000-tick run on the unpatched code.
- Fix: new `Population._nearest_material_tile_global` — once the
  bounded local scan comes back empty and the agent isn't already on a
  journey, a one-time reachability-filtered scan (`_reachable_tiles`,
  the same flood fill the fission site-chooser and bridge search
  already use) finds the nearest FOREST/HILLS tile the agent can
  actually walk to and sets it as `agent.travel_target` — the existing
  greedy+BFS journey machinery (already used for fission travel and
  stuck-pocket escapes) then carries them there over many ticks. Only
  fires while no nearby material exists and no journey is already
  under way, so it adds no routine per-tick cost. Filtering by real
  walkable reachability (not just raw distance) matters: an earlier
  version of this fix picked the nearest material tile by distance
  alone, which could be a real island across a lake/river the agent
  can never reach — that produced an infinite retry loop (travel_target
  set, journey pathing correctly detects it's unreachable and abandons
  it, next tick's GATHER dispatch rediscovers and reassigns the exact
  same unreachable tile). A settlement whose entire reachable region
  genuinely contains no forest/hills (a small island with none of its
  own) now correctly stays materials-starved rather than looping —
  same "true extinction is a legitimate permanent ending" acceptance
  this project already applies to population going to zero.

### Verified

Confirmed via a direct unit test (`_dispatch_movement` on synthetic
terrain: bounded local scan returns None, global fallback sets the
correct distant travel_target, the agent journeys there and arrives,
local scan then succeeds). Confirmed via a real `SimulationEngine`
A/B on two live-generated seeds: a genuinely isolated-island seed
stays at exactly 0 materials/buildings both before and after the fix
(correct — no reachable material exists at all); a far-but-reachable
seed goes from 49 buildings pre-fix (materials only from lucky
random-walk drift over the population, no deliberate journey) to 86
buildings post-fix over the same 20,000 ticks. A 6-seed x 15,000-tick
stability soak (LLM disabled) confirms no crash across a mix of
reachable and unreachable-material geographies.

## [0.84.3] — Phase N complete: misplaced_object intervention

Closes the last item on the vision doc's Town Consciousness
intervention menu — `misplaced_object` — completing Phase N's full
scope across v0.84.0/.2/.3.

### Added

- `misplaced_object` (`SimulationEngine._apply_consciousness_
  intervention`, `llm/consciousness.py`): relocates a partial amount
  (`MISPLACED_OBJECT_FRACTION=0.4` of the donor's current stock) of one
  inventory good — food, tools, or medicine — from one core-cast agent
  to another in the founding settlement, capped by the recipient's own
  personal capacity for that good. A genuinely mechanical nudge (real
  inventory quantities move, total conserved — nothing is created or
  destroyed), not narration-only, matching this project's standing
  "deterministic engine provides reality" priority even for a Phase
  G-tier intervention. Plants the same flavor-text memory on both the
  donor and recipient (same "quietly noticed" register as the other
  interventions).
- `ALLOWED_INTERVENTIONS` now covers the vision doc's full menu (6
  items); `llm/consciousness.py`'s system prompt updated to match.

### Verified

Direct test confirms the total quantity of the moved good is exactly
conserved across the transfer (relocated, not fabricated) and exactly
two agents receive the memory; a 20,000-tick engine soak cycling
through all 7 intervention kinds (including `misplaced_object`)
completes with zero crashes, bounded consciousness state, and
inventory totals still non-negative and capacity-respecting.
`scripts/verify_native_soak.py` unaffected — this batch touches no
native module.

## [0.84.2] — Phase N follow-up: omen/dream seeding interventions

Direct emergence follow-up to v0.84.0/.1, per the "both in parallel"
direction: closes two of the vision doc's two remaining Phase N menu
items (`omen_phrasing_seed`, `dream_symbol_seed`) that `llm/
consciousness.py`'s own module docstring had explicitly flagged as "a
natural follow-up, not attempted here." Both ride existing state with
minimal new plumbing, matching the same discipline as the original
three interventions.

### Added

- `Settlement.omen_seed`/`dream_seed` (new, `settlement/buildings.py`):
  single-valued queued strings, same "queued input for the next job"
  shape as `player_influence`, always founding-settlement-scoped (the
  consciousness is world-scoped, not per-settlement) regardless of
  which settlement's own omen/dream turn it is. Retained on a fallback
  (only cleared on a genuine, non-fallback LLM success) so a flaky LLM
  stretch never silently drops a queued seed — same discipline
  `player_influence` already established.
- `llm/omens.py`'s `build_prompt` and `llm/dream.py`'s `build_prompt`
  each gained an optional `seed_phrase`/`symbol_seed` parameter, folded
  in with the same "texture, never a required thread" treatment as
  `past_omens`/`folklore`/`narrative_theme` already get — the model is
  always free to ignore it.
- `llm/consciousness.py`'s `ALLOWED_INTERVENTIONS` and system prompt
  extended to include both; `SimulationEngine._apply_consciousness_
  intervention` queues the detail text onto the relevant seed field;
  `_maybe_schedule_omen`/`_maybe_schedule_dream` read and (on success)
  clear it.
- **Scope note**: a misplaced-object event remains the one unattempted
  item from the vision doc's fuller menu — it implies a new inventory-
  shuffle mechanic rather than reusing existing state, a larger unit of
  work than this follow-up slice.

### Verified

Direct tests: both interventions correctly queue their seed onto the
founding settlement; `build_prompt` for both omens and dreams correctly
folds a queued seed into the generated prompt text; a forced real
`_maybe_schedule_omen` call confirms the seed reaches the engine-built
prompt and is cleared only after a genuine (non-fallback) success;
`omen_seed`/`dream_seed` round-trip exactly through `to_dict`/
`from_dict`, legacy snapshots missing them default cleanly to `""`; a
20,000-tick engine soak with a fake client cycling through all five
intervention kinds (including both new ones) completes with zero
crashes and bounded memory/intervention-log lengths.
`scripts/verify_native_soak.py` unaffected — this batch touches no
native module.

## [0.84.1] — Observatory follow-up: consciousness in the dev console

Direct follow-up to v0.84.0, per the "keep both moving in parallel"
direction: Town Consciousness v2's persistent state was reachable via
raw `/state` JSON but not actually surfaced in the developer
observatory itself, unlike its Phase G siblings (`temperament` is a
concise value in `full_diagnostics()`'s on-demand report). Deepens the
observatory rather than the main UI, matching the standing ambiguity
discipline exactly.

### Added

- `renderDevConsole`'s lightweight, auto-refreshing dev-console pane
  now includes `payload.summary.consciousness` alongside `diagnostics`/
  `llm` — reads straight off the existing broadcast payload, no new
  endpoint.
- `SimulationEngine.full_diagnostics()` gained a `consciousness` key
  (personality, objectives, memory/player-model counts, latest memory,
  latest intervention) — the same "concise glanceable summary next to
  the full raw lists" treatment `temperament` already gets, reachable
  via the "Full diagnostic report" button / `GET /diagnostics`.

### Verified

Direct unit check of `full_diagnostics()`'s new key against synthetic
consciousness state; a live server (LLM disabled) confirms `GET /state`
and `GET /diagnostics` both return the new fields with the correct
empty-state shape before any consciousness activity has occurred.

## [0.84.0] — Phase N: The Town Awake (Town Consciousness v2)

Phase N (docs/VISION-2026-07.md, "The Town Awake"), per the user's
"continue" direction following Phase M — Phase G given a memory and a
will, extension rather than replacement. Deliberately scoped down from
the vision doc's full menu (also names omen-phrasing/dream-symbol seeds
and a misplaced-object event) to the three interventions that ride
existing state with zero new cross-module plumbing; the fallback is a
genuine no-op ("no call -> no intervention that month"), a deliberate
departure from every other Phase L/M job's fallback shape.

### Added

- **Persistent inner state** (`World.consciousness_memory`/
  `_personality`/`_objectives`/`_player_model`/`_intervention_log`,
  `world/state.py`): a bounded memory of what it's noticed (cap 16), a
  genesis-seeded personality (curiosity/patience/possessiveness,
  deterministic from `config.seed`, zero LLM cost — `llm.consciousness.
  seed_personality`), at most 2 standing objectives revised only when
  the model actually supplies new ones, and a private, capped (6) theory
  about the player (same belief shape as `Settlement.beliefs` but never
  institution-mirrored — this is the consciousness's read on the
  *outside hand*, not a village belief). World-scoped, not per-
  settlement — tied to the founding settlement, same as player_standing/
  documentary/whispers.
- **Monthly consciousness job** (`llm/consciousness.py`,
  `SimulationEngine._maybe_schedule_consciousness`, one call): reads its
  memory/personality/objectives/player-model plus the settlement's real
  temperament/mood/narrative-theme, and may choose at most one
  intervention from a bounded menu — `weather_nudge` (perturbs `World.
  weather` directly, small enough to stay within the smoothed range
  `compute_weather` actually realizes, decays naturally through the
  existing EMA blend next tick), `temperament_nudge` (`tick_temperament`
  gained an `extra` parameter, the shared `bounded_random_walk_step`
  primitive already supported this shape — just not threaded through
  until now), or `false_memory` (plants a fabricated-but-plausible
  memory on a core-cast agent via the existing `_remember`). Most months
  the honest answer is "none," per the vision doc's own framing.
- **Emotional contagion**: `false_memory` plants the identical
  fabricated text on the chosen agent's most-bonded living partner too
  (opportunistic — skipped if none) — the vision's "two agents receiving
  the same seed in the same month" reading, achieved as a side effect of
  the mechanism already being built rather than separate dream-seed
  plumbing. Pure seed-sharing, free, and only ever noticeable by a
  player comparing two NPC inspectors.
- **UI**: `consciousness_intervention` event icon (🌫️, deliberately the
  same as `omen`'s — a consciousness intervention is meant to read
  exactly like one), grouped under the "mind" filter chip. No main-UI
  panel — Phase G ambiguity discipline applies here exactly as it does
  to temperament/mood/player_standing: reachable only via the dev
  console/raw `/state` JSON (`World.summary()`'s new `consciousness`
  key), never labeled in the normal UI.

### Verified

Direct fake-client tests: the monthly job correctly writes memory/
player-model/objectives/personality on a real LLM result, `false_memory`
plants on exactly one core-cast agent plus its bonded partner
(contagion), `weather_nudge`/`temperament_nudge` stay bounded within
their documented ranges; the fallback path is confirmed to be a genuine
no-op (no memory, no intervention logged) rather than a fabricated
substitute; `consciousness_*` fields round-trip exactly through
to_dict/from_dict, legacy snapshots missing them default cleanly to
empty; a 20,000-tick engine soak (fake instant LLM client, population
25) completes with zero crashes, bounded memory/intervention-log
lengths, and healthy LLM stats. `scripts/verify_native_soak.py`
unaffected — this batch touches no native module.

## [0.83.0] — Phase M: Faith & Meaning (ritual→religion, Narrative Direction)

First implementation slice of the long-term vision's Phase M
(docs/VISION-2026-07.md, "Faith & Meaning"), per explicit user
direction to pursue Phase M first while continuing UI/pacing work in
parallel. Both pieces follow the standing "maximize emergence per LLM
call" discipline: detection is free and deterministic, a call is spent
only once there's real accumulated texture to ask about, and the
fallback for "does this form" is always an honest "not yet" — never an
invented placeholder.

### Added

- **Ritual detection** (`SimulationEngine._detect_ritual_signals`/
  `_maybe_promote_ritual`, zero LLM cost, every tick): recognizes two
  patterns from real coincidence already tracked elsewhere —
  `communal_feast` (the settlement has held enough festivals, each
  already implicitly "after good fortune" via the existing
  well-fed gate) and `shrine_mourning` (a death lands while a STANDING
  shrine stands). Promoted into `Settlement.rituals` (capped
  `RITUAL_MAX_STORED=12`), logged as `ritual_formed`.
- **Religion crystallization** (`llm/religion.py`,
  `SimulationEngine._maybe_schedule_religion`, season_end-gated, one
  call): once a settlement has at least one accumulated ritual, asks
  the LLM whether its practices/omens/folklore genuinely coalesce into
  a shared named belief — most of the time the honest answer is no.
  A formed religion (`Settlement.religion`: name + up to 4 tenets) also
  pushes one representative entry into the existing `Settlement.
  beliefs` list (institution-mirrored via the existing sync
  helpers) rather than building a parallel consumption path. Logged as
  `religion_formed`.
- **Schism on fission** (`llm/fission.py`): a departing party from a
  settlement with a formed religion may now reform it independently —
  the fission LLM call's existing JSON schema gained one optional
  `schism` boolean field (zero added call volume), and a schism copies
  the parent's tenets onto the new settlement as `"Reformed <name>"`
  with `schism_of` set to the parent's id.
- **Narrative Direction** (`llm/narrative_direction.py`,
  `SimulationEngine._maybe_schedule_narrative_direction`,
  season_end-gated — a season already is a real-calendar quarter, one
  call): names the theme(s) running through a settlement's recent
  events/folklore/mood (e.g. "quiet renewal," "unease"). Consumed ONLY
  as one ambient-bias sentence folded into `town_brain`/`omens`/
  `chronicle`/`Dream()` prompts (`_narrative_theme_bias`) — never
  schedules or scripts an event on its own. Stored capped
  (`NARRATIVE_THEMES_MAX_STORED=8`).
- UI: new "Faith & rituals" panel (religion name/tenets + ritual list)
  alongside Folklore, and a "recent theme of village life" line in the
  Town Brain panel — both reachable under the existing "📊 details"
  toggle, same as their siblings. Three new event icons/groups
  (`ritual_formed` 🕯️, `religion_formed` ⛩️, `narrative_direction` 📖,
  all grouped under the "mind" filter chip).

### Verified

- Direct fake-client tests: `_detect_ritual_signals`/`_maybe_promote_
  ritual` correctly promote both patterns from synthetic festival/death
  history; `_maybe_schedule_religion` crystallizes a religion only once
  a ritual exists and never re-forms one that already exists; schism on
  fission produces a correctly-tagged reformed offshoot religion on the
  new settlement.
- `religion`/`rituals`/`ritual_signal_counts`/`narrative_themes`
  round-trip exactly through `to_dict`/`from_dict`; legacy snapshots
  missing these fields default cleanly (`None`/`{}`/`[]`).
- Live browser (Playwright) verification of the new "Faith & rituals"
  panel and narrative-theme line rendering real injected data.
- A 20,000-tick engine soak (fake instant LLM client, Phase M jobs
  active) completes with zero crashes and healthy LLM stats
  (1728 calls attempted/succeeded, 0 errors); `scripts/verify_native_
  soak.py` unaffected — this batch touches no native module.

## [0.82.0] — LLM-pressure tick pacing; snow fix; "town is alive" UI cues

Explicit standing priority: LLM decision quality over simulation
throughput — when they compete for the same resource, quality wins.
Backend pacing change plus two frontend bug fixes plus a first UI
feature connecting an LLM-authored moment to the map itself.

### Added

- `SimulationEngine.llm_pressure_ratio()`/`llm_pressure_paused()`/
  `_llm_pressure_interval_multiplier()`: `run_forever` now stretches
  (up to 6x) or fully pauses the real-time gap between ticks when the
  LLM backlog is saturated, instead of only dropping jobs that can't
  get a slot. A live diagnostic showed backlog at 2x the adaptive
  backpressure limit with 3006 dropped calls against only 134
  attempted — the tick loop was generating scheduling opportunities
  faster than the (20-40s/call) hardware could ever clear them. The
  existing drop-based backpressure/adaptive-limit machinery is
  unchanged and still the real safety valve for a pathological
  backlog. Surfaced in diagnostics/broadcast as `llm_pressure_ratio`/
  `llm_pressure_paused`.
- UI: a header "the town is thinking…" / "deep in thought…" indicator
  reading the pacing state above, and a brief pulsing ring over a
  core-cast agent's map position the instant a genuine LLM-authored
  dialogue exchange lands (parsed from the existing event description,
  no schema change) — both verified live via Playwright.

### Fixed

- Snow was invisible whenever it followed rain (a common real
  transition): `spawnWeatherParticles` only set a particle's `snow`
  type at creation, so particles already on screen from a moment ago
  kept behaving as the old weather type forever. Verified live: before
  the fix, particles stayed 100% rain-typed after `is_snowing` flipped
  true; after, 100% convert on the next frame. Also added a pale
  ground-tint overlay when snowing (distinct from rain's darkening
  tint) so it reads at a glance even with sparse particles.
- `.consciousness-indicator`'s bare `display:flex` rule tied on CSS
  specificity with the shared `.hidden{display:none}` rule and won by
  source order, silently defeating its own show/hide toggle — fixed
  via `:not(.hidden)`.

### Verified

- Direct unit tests for the pacing ratio/multiplier/pause thresholds
  and a `run_forever` test confirming zero ticks advance while
  pressure stays severe.
- Live browser (Playwright) tests: rain->snow particle conversion,
  consciousness-indicator hidden/slowed/paused states, thought-flash
  ring positioning for a synthetic dialogue event.
- `scripts/verify_native_soak.py` (2 seeds, 1500 ticks) byte-identical
  — this batch touches no native module.

## [0.81.1] — Monthly settlement jobs get a bounded retry window

Direct response to a live report: a village had never once formed a
belief or gotten a town-brain decision after 20,000 ticks. Confirmed
the scheduling/parsing/write/UI-display path itself was correct (fake-
client tests populate both reliably within ~10k ticks) and that
`current_priority` is mechanically real (drives `choose_building_kind`,
not just narration) — the actual bug was scheduling fragility.

### Fixed

- `_monthly_gate` previously gave a job exactly ONE tick's chance per
  month; if that tick landed during a backpressured stretch (plausible
  given v0.81.0's own diagnostic: 616 backpressure drops vs. 100
  attempted calls), the job silently waited a full month before trying
  again — for 7 straight months in the reported case. New `MONTHLY_JOB_
  RETRY_WINDOW_DAYS=3` + `MONTHLY_JOBS_WITH_RETRY` (11 of the 14
  monthly jobs — chronicle, folklore, town_brain, beliefs, personal_
  belief, dream, faction, guild_founding, institution_belief, fission,
  geography) + `_mark_monthly_resolved`: these jobs now get up to 3
  days to get past backpressure, marking themselves done the instant
  they do (still at most one real attempt per job per month).
  Deliberately excludes festival/caravan/omen, each of which has its
  own independent per-month RNG roll that must NOT be re-evaluated on
  multiple days (would inflate their tuned monthly probability) — kept
  their original single-exact-day gating unchanged.

### Verified

- A live-shaped test force-blocking backpressure specifically on
  town_brain's/beliefs' first scheduled day each month confirms both
  now recover within the same month instead of waiting for the next.
- Direct `_monthly_gate` unit tests: festival's gate stays exactly
  single-day; beliefs' stays open across its window until marked
  resolved, then closes for the rest of the month.
- `scripts/verify_native_soak.py` (2 seeds, 1500 ticks) byte-identical
  — this batch touches no native module.

## [0.81.0] — LLM scheduler: backpressure fix, adaptive load control, config re-tune; movement bug fix

Direct response to a live `/diagnostics` report at population 231:
`calls_dropped_backpressure` 616 vs. 100 attempted, `backlog` 11,
latency p50/p95/max 31.8s/69.8s/101.9s, while `system_memory` showed
the v0.78.x swap crisis resolved (`mem_available` 3321MB of 7045MB,
~0 swap). Root-caused the "queued jobs go stale" symptom to a scheduler
bug, not a config problem alone; found and fixed a real movement bug
while investigating.

### Fixed

- **Backpressure reservation gap**: `CognitionRunner.backlog` only
  increments once a scheduled task's coroutine body actually starts
  running — impossible until the fully-synchronous `_tick_once`
  returns and the event loop gets a turn. Every backpressure check
  within one tick was therefore reading the same stale pre-tick value,
  even after several jobs had already been scheduled moments earlier
  that same tick — letting a single busy tick (the documented month-end
  settlement-job cluster, a cognition+dialogue burst) admit more jobs
  than the concurrency-derived limit intended. New `SimulationEngine.
  _reserved_this_tick`, incremented at every real scheduling call site,
  reset every tick; every backpressure check now reads `_effective_
  backlog()` instead of the raw counter. This is what actually explains
  "queued jobs become irrelevant before they execute" — audited the
  existing staleness/dedup machinery (`STALE_GOAL_RESULT_TICKS`/
  `STALE_DIALOGUE_RESULT_TICKS`, dead-agent no-ops in `apply_goal`/
  `apply_dialogue`, synchronous cooldown-marking preventing duplicate
  per-pair/per-agent scheduling, Phase J's already-merged belief +
  semantic-memory + secret reflection call) and found it already sound;
  the backlog was simply growing past what it was tuned to expect.
- **Movement: stuck-agent BFS escape**: `_step_toward`'s greedy step
  only ever tries the 1-2 cardinal directions that reduce Manhattan
  distance (exactly ONE candidate when dy=0) — a blocked straight line
  left zero alternatives, silently degrading routine goal-directed
  movement (FORAGE/SOCIALIZE/GATHER/WANDER) to a pure random walk
  indefinitely even when the target was reachable by a longer route.
  `travel_target` journeys already had a BFS escape for this; routine
  movement never did. New `Agent.stuck_ticks` (plain int, round-trips
  through to_dict/from_dict) triggers one bounded `_bfs_step` after
  `MOVEMENT_STUCK_TICKS_THRESHOLD` (4) consecutive blocked ticks.

### Added

- **Adaptive load control**: `SimulationEngine._current_backpressure_
  limit` scales the static concurrency-derived limit down using
  `CognitionRunner.stats()`'s existing rolling p95 latency — halves
  past `ADAPTIVE_LATENCY_ELEVATED_MS` (45s), quarters past `ADAPTIVE_
  LATENCY_SEVERE_MS` (80s), never below `llm_max_concurrent`, recovers
  automatically as latency drops.
- Diagnostics: `llm_backlog_effective`, `llm_backlog_reserved_this_
  tick`, `llm_backpressure_limit`, `llm_backpressure_limit_effective`,
  `agents_movement_stuck`, `oldest_pending_goal_ticks`, `oldest_
  pending_dialogue_ticks`.

### Changed

- `Config.llm_max_concurrent` 1 -> 2, `Config.llm_timeout_seconds` 60
  -> 120 (both docstrings carry the full live-diagnostic rationale).
- `scripts/run.sh`: new `LLAMA_PARALLEL` (default 2, replacing a
  hardcoded `--parallel 1`); `LLAMA_CTX_SIZE` default 2560 -> 5120
  (= `llm_num_ctx * LLAMA_PARALLEL` — llama-server divides one shared
  `--ctx-size` across its `--parallel` slots, so this keeps each slot
  at the full `llm_num_ctx` budget); `LLAMA_FIT_TARGET` 2560 -> 2048.
  README's 8GB CPU-only recipe updated to explicitly pin
  `LLAMA_PARALLEL=1 --llm-max-concurrent 1` (it previously didn't set
  `--parallel` at all, so it would have silently inherited the new
  default of 2 and halved to 640 tokens/slot).

### Verified

- Direct Agent.stuck_ticks round-trip + legacy-snapshot default test.
- Synthetic concave-water-wall grid: agent reaches an otherwise-
  unreachable-by-greedy target within a few ticks via the BFS escape; a
  fully-enclosed target never crosses the wall and stuck_ticks stays
  bounded rather than growing.
- Direct adaptive-backpressure-limit tests (healthy/elevated/severe
  latency tiers) and a direct same-tick-reservation-visibility test
  (the exact gap being fixed).
- 1500-tick engine soak with a fake slow LLM client (`llm_max_
  concurrent=2`, 30 agents, 10-agent core cast): 101 calls attempted/
  succeeded, 0 errors, backlog/reservation counters bounded and
  resetting correctly tick to tick, no crash.
- `scripts/verify_native_soak.py` (2 seeds, 1500 ticks) byte-identical
  — this batch touches no native module.

## [0.80.0] — Phase L: Society & Power (Reputation, Factions, Economy depth)

All three Phase L pieces in one batch — the vision doc's own budget
analysis already resolved every call-volume fork in this phase's favor,
so no scoping question was needed first.

### Added

- `Population.reputation(agent_id)`/`_refresh_reputation()` — mean
  trust every living agent holds toward someone, cached monthly (no new
  LLM call, rides the existing month_end temperament tick). Wired into
  `_prominence` and `llm/dispute.py`.
- `InstitutionKind.FACTION` + `Population._detect_faction_candidate`
  (union-find over mutual-trust edges, cohesion-gated) + `llm/
  faction.py` + `SimulationEngine._maybe_schedule_faction` — a real
  candidate cluster is detected for free every month; naming it costs
  one LLM call, and only once per cluster ever (membership fixed at
  formation). Biases dispute framing/fallback (rival factions) and
  fission-party assembly (faction-mates follow after family).
  `_prune_extinct_families` generalized into `_prune_extinct_
  institutions(settlement, living_ids, kind, cap)`, shared with the new
  `FACTION_MAX_STORED=20` cap.
- `Agent.debts` + `_record_debt`/`decay_debts` — a bounded per-pair
  debt ledger riding the existing food/tools/medicine barter mechanic
  (a recipient owes the giver half the traded amount; reversed trades
  net down first; decays slowly, same prune-small-entries discipline as
  trust/relationships/emotions). Feeds dispute framing/fallback.
- UI: NPC inspector "Debts" section, faction line in "Institutions",
  faction count in the Institutions stat tile, `faction_formed` event
  icon/group.

### Scope cuts (explicit, not silently decided)

- "Scarcity-driven specialization pressure" — the vision doc itself
  notes this mostly already exists via the skills system; no new work.
- "Black-market flag on trades defying a council price-nudge" —
  dropped. This codebase's trade mechanic is presence-driven barter,
  not price-driven exchange; there's no existing council-price-nudge
  concept an agent-to-agent trade could defy, and inventing one just to
  hang a flag off it was the wrong kind of scope creep for what's meant
  to be a light extension of existing state.

### Verified

- Direct union-find/cohesion tests (candidate detection, formation,
  faction_of lookup, exclusion of already-affiliated agents).
- Direct `_record_debt`/`decay_debts`/round-trip tests (settlement,
  decay-to-prune, to_dict/from_dict exact).
- Live 8000-tick engine run (LLM disabled): no crash, populated
  reputation cache.
- `scripts/verify_native_soak.py` (multi-seed) byte-identical — this
  batch touches no native module.

## [0.79.1] — Phase K complete: InterpretRumor() + Dream()

Closes Phase K's two pieces deferred from v0.79.0, both implemented at
their most budget-conscious viable scope per the standing memory-
pressure directive (scope-downs documented, not silently decided).

### Added

- `llm/rumor_interpret.py` + `SimulationEngine._maybe_interpret_rumor`
  — a core-cast rumor listener may retell it coloured by their own
  nature, landing as a new memory (not a new rumor-object/hops model).
  New `INTERPRET_RUMOR_MAX_PER_DAY=3` (fires per listening event, needs
  its own ceiling beyond the shared daily budget).
- `llm/dream.py` + `SimulationEngine._maybe_schedule_dream` — monthly,
  symbolic, never predictive. New `MONTHLY_JOB_DAY["dream"]=23`.
  **Scoped to a one-agent-a-month round-robin**, not all core-cast
  agents monthly as the vision doc describes (~14x less call volume for
  a 14-agent cast); schema kept to one field.

### Verified

- Fake-client test: InterpretRumor() plants a distorted memory,
  respects its daily cap; Dream() picks exactly one core-cast agent.
  Round-trip exact (both reuse existing `memories` serialization).
  `scripts/verify_native_soak.py` (2 seeds, 1500 ticks): byte-identical.

## [0.79.0] — Phase K start: folklore condensation + Historian v2

Phase K (docs/VISION-2026-07.md, "Knowledge & Story"), scoped to 2 of
4 pieces per an explicit scoping question — rumor distortion
(InterpretRumor()) and Dream() deferred, both would add real new
recurring per-agent LLM call volume.

### Added

- `Settlement.folklore` (`settlement/buildings.py`, cap
  `FOLKLORE_MAX_STORED=24`) + `llm/folklore.py` — monthly settlement job
  (new `MONTHLY_JOB_DAY["folklore"]=20`), same call-volume shape as
  tradition/invention/festival. Condenses recent rumor-category events
  into a short tale, or honestly says nothing's worth telling yet
  (the common, expected outcome).
- `persistence/snapshot.py`: `events_by_category` — category-filtered
  event query, used by the folklore job to read the literal rumor
  stream (not the diversity-adjusted digest).
- UI: "Folklore" panel (index.html/app.js), tales newest-first.

### Changed

- `llm/chronicle.py` ("Historian v2"): system prompt now asks the model
  to interpret the season, not just summarize it; prompt gains the
  settlement's newest folklore as an optional interpretive lens.
- `llm/omens.py`: folklore feeds the existing "echo of something
  noticed before" mechanism, same optional-texture treatment as
  `past_omens`.

### Verified

- Direct `_maybe_schedule_folklore` call with a fake client and a real
  rumor event: folklore entry lands, appears in a subsequently-built
  chronicle prompt. Round-trip exact. `scripts/verify_native_soak.py`
  (2 seeds, 1500 ticks): byte-identical.

## [0.78.5] — LLM config tuning: concurrency floor, batch/ubatch, defrag

Explicit user-directed config tuning for a long stable run on ~6.88GB
available RAM, all synced between `Config` and `scripts/run.sh`.

### Changed

- `Config.llm_max_concurrent` 2 -> 1, explicitly superseding the
  v0.44.0 "permanent floor of 2" per direct user instruction —
  `--parallel 1` already meant a second in-flight request was dead
  weight against a server that could only serve one at a time.
- `scripts/run.sh`: `LLAMA_CTX_SIZE` 1280 -> 2560 (now synced with
  `Config.llm_num_ctx`, closing a drift footgun), `LLAMA_FIT_TARGET`
  unset -> 2560, `LLAMA_BATCH_SIZE`/`LLAMA_UBATCH_SIZE` unset -> 512/128
  (down from llama.cpp's own 2048/512, tuned for the single-lane
  `--parallel 1` workload this project runs).
- README's manual command examples and flag bullets updated to match.

### Added

- `scripts/run.sh`: `LLAMA_DEFRAG_THOLD` (default 0.1) — passes
  `--defrag-thold`, triggering periodic KV-cache defragmentation aimed
  at "runs stably for years" (many different prompt lengths reusing the
  same cache over a long session fragments it).

## [0.78.4] — Phase J: permanent mind schema + Reflect()-planted secrets

Closes both pieces deferred from v0.78.3 ("do both, ask when in
doubt"). Asked one clarifying question on the mind schema's scope
before building (call-volume implications differed by option); user
chose "permanent tier only."

### Added

- `Agent.mind` (`agents/agent.py`, cap `MAX_MIND_TEXT_CHARS=220`) —
  one-time-authored durable identity paragraph, core cast only, never
  revised. `Population.maintain_core_cast` now returns newly-added
  agents; `SimulationEngine._author_minds` sets a deterministic
  fallback synchronously (`describe_mind_fallback`) then schedules one
  optional background LLM call per new agent (`llm/mind.py`, new),
  backpressure-gated against a genesis-time burst. Fed into cognition/
  dialogue prompts for core-cast agents; surfaced in the NPC inspector
  as "At their core."
- `llm/beliefs.py`: `parse_secret` + a sixth optional `"secret"` field
  on the personal-belief/Reflect() job's existing schema — reuses that
  job's one monthly call slot, left blank almost every call, no
  fallback-invented secrets, planted only on core-cast targets.

### Scope decisions (explicit, user-approved)

- The vision doc's "slow"/"fast" mind tiers are declared aliases of
  existing state (`traits`' own drift; `goal_reason`/`working_memory`)
  rather than new fields — avoids duplicating existing mechanisms and,
  for "slow," a new recurring LLM job.

### Verified

- Fake-client test: every core-cast agent gets immediate deterministic
  mind text, LLM-authored version lands when the call succeeds; forced
  Reflect() call with a `"secret"` field plants it on the target.
  `mind`/`secrets` round-trip exact. `scripts/verify_native_soak.py`
  (2 seeds, 1500 ticks): byte-identical.

## [0.78.3] — Phase J: secrets (dispute-planted) + memory-pressure pass over old code

Continues Phase J with the "Secrets & lies" piece, plus a standing
instruction to keep optimizing LLM memory pressure wherever found,
including in already-shipped code.

### Added

- `Agent.secrets` (`agents/agent.py`, cap `MAX_SECRETS=2`, FIFO) +
  `push_secret` helper. Planted only by a hardened "feud" dispute
  outcome, core-cast only — deterministic derivation from the existing
  `llm/dispute.py` output, not a new LLM field, so zero added call
  volume/schema risk. `llm/dialogue.py`'s prompt surfaces a speaker's
  secret only when it's about the other person present, with system-
  prompt guidance to let it show as tension rather than being stated
  outright. Dev-console/raw-JSON reachable only, never in the main UI.

### Changed

- `PROMPT_RECENT_EVENTS` 50 -> 40 (`simulation/engine.py`) — the
  v0.78.0 diversity-aware event sampling means fewer rows carry
  comparable signal, for ~20% less prompt-token cost on the largest
  prompts in the codebase.

### Audited, no change needed

- Re-checked `memorials`/`omen_history`/institution belief lists
  (`settlement/buildings.py`) for unbounded growth per the "old code
  too" instruction — all already capped from prior passes.

### Verified

- Direct `_maybe_schedule_dispute` call with a fake client forcing
  "feud": secret planted on both core-cast parties, present in the
  built dialogue prompt. `Agent.secrets` round-trip exact.
  `scripts/verify_native_soak.py` (2 seeds, 1200 ticks): byte-identical.

## [0.78.2] — years-long stability: metrics retention, --mlock, population reassurance

Follow-up to v0.78.1: "meant to run stably for years, how do I reduce
or eliminate swapping, is population growth to 301 healthy?"

### Added

- `Config.metrics_log_retention` (default 20,000 rows) + `_prune_
  metrics` (`persistence/snapshot.py`), same shape as the existing
  `event_log_retention`/`_prune_events`, wired into `save_snapshot`'s
  prune transaction + new `--metrics-log-retention` CLI flag. Closes
  the one table the v0.71.0 "runs forever" audit left unpruned pending
  a genuine multi-year-run request.
- `scripts/run.sh`: `LLAMA_MLOCK=1` opt-in `--mlock` — pins llama-
  server's memory resident, converting silent swap-degradation into a
  loud startup failure/OOM-kill if the allocation is undersized.
  Documented as "size first, then lock," not a default.

### Documented

- New README section, "Running stably for years — reducing or
  eliminating swap": population growth toward `POPULATION_CAP=400` is
  the designed equilibrium and does not scale LLM memory (fixed core
  cast, startup-time-only KV cache) — not a lever to chase; concrete
  swap-reduction levers (ctx/predict size, `q4_0` KV cache, batch/
  ubatch); `--mlock` as the actual swap-elimination mechanism; and
  operational guidance for unattended years-long runs (process
  supervisor + restart-on-crash into the existing snapshot/resume path,
  periodic `/diagnostics.system_memory` checks, zram over disk swap).

### Verified

- 2000-tick soak with `metrics_log_retention=5`: table stays capped,
  `recent_metrics`/`/metrics` keep working.

## [0.78.1] — llama-server memory pressure: live diagnostic, config pull-back

Direct response to a live `/diagnostics` report showing sustained
memory pressure on a long-running game (301 population, 13,094 ticks)
with the local llama.cpp backend.

### Diagnosed

- `system_memory` showed hearthmind's own process at a flat 57.9MB
  RSS/11.1MB swap (no leak, consistent with every prior audit) while
  `llama-server` sat at 121MB RSS but **2048MB in swap**, with system
  `mem_available` at 174MB of 7046MB total. Low RSS + high swap on the
  LLM server is its fixed KV-cache/compute-buffer allocation sitting
  cold and getting paged out under system-wide pressure over a long
  session — config, not a Python-side bug.
- Checked and ruled out as red herrings: `dialogue_cooldown_entries`
  (11,746) and `relationship_entries` (23,382) both read high but are
  genuinely bounded by existing pruning (staleness horizon; decay-to-
  zero + death) and cost negligible real memory (confirmed by the flat
  self-process RSS above).

### Changed

- `Config.llm_num_ctx` 3072 -> 2560, `Config.llm_num_predict` 512 -> 448
  (both `config.py`) — a second pull-back below the v0.72.3 GPU-offload-
  optimistic numbers, this time driven by a real long-running-game
  diagnostic rather than a short soak.
- README's llama-server example commands updated to match; new
  "Note (v0.78.1)" explaining the reading and the shared-memory-iGPU
  angle (`--fit-target`/`LLAMA_FIT_TARGET` trades offload for headroom
  on hardware where "VRAM" is drawn from the same system-RAM pool).

### Added

- `scripts/run.sh`: `LLAMA_BATCH_SIZE`/`LLAMA_UBATCH_SIZE` — optional
  `--batch-size`/`--ubatch-size` overrides, omitted unless set (zero
  risk to existing launches), shrink the compute-buffer allocation
  independently of the KV cache for further memory-pressure headroom.

## [0.78.0] — Phase J start: semantic memory + event-triggered reflection + event diversity

Phase J (docs/VISION-2026-07.md, "Deeper Minds"), scoped to one slice
per explicit direction to keep optimizing LLM memory pressure while
adding psychological depth: event-triggered psychological updates,
memory abstraction, and event diversity so chronicles/conversations
aren't dominated by routine physical events.

### Added

- `Agent.semantic_memories` (`agents/agent.py`, cap
  `MAX_SEMANTIC_MEMORIES=3`, FIFO) — a third memory layer: condensed
  lasting self-theories distilled from episodic memory, distinct from
  individual-event `memories` and settlement-shaped `beliefs`.
- `persistence/snapshot.py`: `ROUTINE_EVENT_CATEGORIES` +
  `recent_events_diverse` — caps how many routine (calendar/farm-
  planted/construction/recovery/wildlife-recolonized) rows can occupy
  an LLM prompt's event window, so rarer social/dramatic events aren't
  crowded out. Swapped into 9 LLM-prompt call sites in `simulation/
  engine.py`; the public `/events`/`/history` API and the temperament/
  mood tracker keep reading the literal `recent_events` stream.
- `llm/beliefs.py`: `parse_semantic_memory`/`push_semantic_memory`;
  `PERSONAL_SYSTEM_PROMPT`/`build_personal_prompt` extended to also
  request/accept a distilled semantic memory alongside the existing
  belief field.

### Changed

- `simulation/engine.py`'s `_maybe_schedule_personal_belief` (monthly,
  one agent) is now significance-first: prefers a core-cast agent with
  a notable emotion or active feud (`_is_significant_moment`, reused
  from v0.77.0) over the old uniform random pool, falling back to it
  when nothing stands out. Same one call/month — zero added LLM call
  volume, richer output per call ("maximize emergence per LLM call").
- `llm/cognition.py`/`llm/dialogue.py` prompts gained one short line
  each surfacing the agent's freshest semantic memory.

### UI

- NPC inspector: new "Their own reflections" section — semantic
  memories plus the agent's own private `beliefs` (previously written,
  never surfaced; retrofit opportunistically per the standing rule),
  distinct from the existing "What the village believes about them".

### Verified

- Direct call to `_maybe_schedule_personal_belief` against a fake LLM
  client with one emotionally-significant core-cast agent present: that
  agent (not a random pick) receives both the belief revision and the
  semantic memory.
- 6000-tick soak: raw 200-row event window is 70% routine categories;
  `recent_events_diverse`'s 50-row window is 32% — newest-first order
  and no duplicates confirmed.
- `to_dict`/`from_dict` round trip exact with the new field populated.
- `scripts/verify_native_soak.py` (3 seeds, 1500 ticks): byte-identical
  — this batch touches no native module.

## [0.77.0] — cognition scheduler: significance gate + LLM memory flags + UI

Batch response to a live report (`calls_dropped_backpressure` ~400
after 2800 ticks) and an explicit request to redesign the cognition
scheduler around "reserve LLM calls for high-impact moments," disable
llama.cpp reasoning output, add memory-reduction flags, audit for real
memory growth, and surface Phase I in the UI.

### Changed
- `simulation/engine.py`: new `_is_significant_moment` gates whether a
  core-cast agent's *routine* (non-triggered) daily cognition slot
  spends an LLM call — only when a notable emotion or active feud makes
  the moment worth the model's discretion. Triggered emergencies
  (critical hunger, fresh grief) bypass the gate, unchanged. Measured:
  `calls_dropped_backpressure` 0 (was ~400), `calls_attempted` 265 vs.
  ~406 routine-slot opportunities over a 2800-tick/30-agent run.
- `agents/population.py`: `due_for_dialogue`'s core-core candidates are
  now stably sorted so a feuding/emotional pair wins the limited
  `MAX_LLM_DIALOGUES_PER_TICK` slots over routine chat (cap unchanged).
- `scripts/run.sh`/README: new defaults `--reasoning off
  --reasoning-budget 0` (confirmed working — no prompt here wants a
  `<think>` block) and `--flash-attn on` (lower attention memory,
  faster inference). Both env-var-gated (`LLAMA_REASONING`/`LLAMA_
  FLASH_ATTN`) and omit-if-empty for an older llama-server build.

### Added
- NPC inspector: a new "Feeling" section surfacing `Agent.emotions`
  (Phase I) — emoji + label + magnitude per notable emotion, same
  styling as the existing traits/skills rows.
- CLAUDE.md: standing rule — every new feature gets a UI-surfacing pass
  in the same batch it lands in.

### Investigated — no Python-side leak found
- 12,000-tick real `SimulationEngine` soak (LLM disabled, full event
  churn): RSS flat at 37.7→37.8MB, GC object count stable. Audited
  every prompt-building call site for unbounded growth — all bounded
  (`PROMPT_RECENT_EVENTS=50`, memories/beliefs capped, colocated_names
  sliced to 4). The reported memory growth is very likely the llama-
  server subprocess, not this process — matches this project's own
  standing "swap pressure has always been Ollama-side" lesson.
  Recommended: check `/diagnostics.system_memory` during a live episode
  to confirm which process is growing.

### Verified
- Fake-client cognition-volume measurement (above).
- 12,000-tick RSS soak (above).
- `scripts/verify_native_soak.py` (3 seeds, 1500 ticks): byte-identical
  — this batch touches no native module.

## [0.76.3] — Phase I complete: layered memory v1

Closes Phase I (docs/VISION-2026-07.md), the third piece deliberately
deferred from v0.76.1.

### Added
- `Agent.memory_salience` (`agents/agent.py`): index-aligned with
  `Agent.memories`, maintained by `agents/population.py`'s `_remember`.
  Each memory is scored at write time from the agent's current
  `emotions` (baseline 0.2, up to 1.0 under real emotion). Eviction at
  `MAX_AGENT_MEMORIES` now drops the lowest-salience entry (ties toward
  oldest) instead of strict FIFO — memorable experiences outlast
  mundane ones.
- `Agent.working_memory` (cap 2, strictly FIFO): a second, faster
  buffer written alongside `memories` — guarantees "what just happened"
  stays available even after salience-weighted eviction drops it from
  the longer-term episodic log.
- `llm/cognition.py`/`llm/dialogue.py` prompts: a "Just now: ..." line
  from `working_memory`'s freshest entry, shown only when it isn't
  already covered by the episodic slice (shared `Agent.just_now_text`
  helper avoids a duplicated sentence).

### Verified
- Direct eviction test: fill to cap with mundane memories, inject one
  high-salience memory, push 8 more mundane ones through — the
  memorable one survives.
- 6000-tick real `SimulationEngine` soak (LLM disabled): `memory_
  salience` stays index-aligned with `memories`, `working_memory` never
  exceeds its cap, salience stays in [0.2, 1.0], to_dict/from_dict
  round trip exact.
- `scripts/verify_native_soak.py` (3 seeds, 1500 ticks): byte-identical
  — this slice touches no native module.
- Legacy snapshots (missing the two new fields, or with a corrupted/
  mismatched-length `memory_salience`) load with defensive
  pad/truncate rather than trusting the data raw.

### Not native-ported (by design)
- The eviction scan is a `min()` over at most 8 entries, firing only
  inside `_remember` on real events — not a per-tick, per-agent hot
  path like `decay_emotions`. Stays pure Python per the "escalate only
  with a measured need" rule (see v0.72.13's precedent for the exact
  same reasoning).

## [0.76.2] — new native module: emotion decay in C++

Direct follow-up to v0.76.1, per explicit user instruction to write new
Phase I code in C++ from the start where it fits (applying R6's
existing "pure math over already-resolved primitives" discipline to
the emotion system rather than revisiting it later).

### Added
- `cpp/src/emotion_decay.cpp`: native `decay_emotions`/`EmotionState` —
  the per-tick, per-agent multiply behind `agents/agent.py`'s
  `decay_emotions`, same "runs unconditionally every tick for every
  agent" shape as module 6 (`_update_needs`). Takes the four emotion
  axes as plain doubles (sparse-dict bookkeeping and the <0.005 prune
  decision stay in Python) since `Agent.emotions` is a sparse dict, not
  a fixed-slot struct.
- `scripts/verify_native_soak.py`: two new toggles
  (`_native_decay_emotions`, `_NativeEmotionState`).

### Verified
- 20,000 randomized native-vs-Python-fallback trials (0 mismatches).
- 500-tick direct `decay_emotions()` A/B sequence with bump events
  mixed in (0 mismatches).
- `scripts/verify_native_soak.py` full-state hash soak, native vs.
  fallback, byte-identical every tick.

### Not ported
- `tick_mood` (settlement-level, monthly aggregation) — evaluated and
  deliberately left Python: it already reuses the native `bounded_
  random_walk_step` module for its bounded step, and a once-a-month
  loop over one settlement's agents isn't hot enough to justify a
  second native call per the project's "escalate only with a measured
  need" rule.

## [0.76.1] — Phase I (Inner Life): per-agent emotions + settlement mood

First implementation slice of docs/VISION-2026-07.md's roadmap, per
explicit user go-ahead. Deterministic, near-zero-LLM-cost — the layer
every later cognition prompt reads from.

### Added
- `Agent.emotions` (`agents/agent.py`): a new 0..1 dict — fear/joy/
  grief/anger, missing key reads 0.0 (same convention as `traits`), but
  fast-changing/decaying rather than near-permanent. `decay_emotions`
  runs every tick after `_update_needs`; `bump_emotion` fires at real
  events: predator attack survived, sustained critical hunger, illness
  onset (fear); birth, festival attendance (joy); dispute reconciliation
  (joy) vs. hardened feud (anger); a death that lands real grief today
  (grief). `describe_emotion`/`dominant_emotion` mirror `describe_
  traits`' shared-helper pattern.
- Consumed in `llm/cognition.py`'s prompt, `llm/dialogue.py`'s prompt,
  and — real even with the LLM off — `fallback_goal` now takes
  `emotions` and a notable fear/grief overrides the usual split toward
  REST/WANDER.
- `Settlement.mood` (`settlement/buildings.py`): a new -1..1 dict —
  hope/fear/grief/suspicion — living beside `temperament` on
  `SettlementDisposition`. `tick_mood` (monthly, alongside
  `tick_temperament`) tracks each axis toward the live aggregate of
  that settlement's own agents' emotions (joy->hope, fear->fear,
  grief->grief, anger->suspicion), reusing the native `bounded_random_
  walk_step` module. Reachable via `summary()`/`to_dict()` like every
  other Phase G number; never labeled "mood" in the UI.

### Verified
- 9000-tick real `SimulationEngine` soak (LLM disabled, crosses 3
  month boundaries): emotions stay bounded [0,1], mood stays bounded
  [-1,1], mood visibly tracks real in-run events, to_dict->from_dict
  round trip stable (including a second reload).
- `scripts/verify_native_soak.py` (1500 ticks x 2 seeds): full
  `World.to_dict()` state, native vs. Python-fallback, byte-identical
  every tick — confirms `tick_mood`'s reuse of the native bounded-
  random-walk module didn't disturb anything.
- Legacy snapshots (missing `emotions`/`mood` keys) load with empty
  defaults — additive-only serialization.

### Deferred
- Layered memory v1 (working/episodic split of `Agent.memories`) — the
  third Phase I piece, held for its own slice so this one stays
  reviewable, same staging discipline as v0.74.3's storage-only
  AgentTable before v0.75.0 wired it in.

## [0.76.0] — long-term design vision: audit + roadmap (design only, no code)

Explicit user directive: adopt the "living civilization simulator"
long-term vision ("maximize emergence per LLM call", two-layer engine,
hierarchical intelligence up through Town Consciousness and Narrative
Direction) — and write the audit + implementation roadmap **without
implementing anything yet**.

### Added
- `docs/VISION-2026-07.md`: full codebase audit against the vision
  (deterministic layer ≈ fully built and already on the C++ R6/R7/R8
  track; cognition hierarchy is the real gap), the
  extend-don't-duplicate map, LLM budget arithmetic (entire roadmap ≈
  +4.6 calls/day against the 320/day ceiling), two flagged conflicts
  with standing rules (core cast 14 vs "~11"; Town Consciousness
  "directly causes events" reconciled to deniable-channels-only), and
  a six-phase roadmap: I Inner Life (deterministic emotions/settlement
  mood/layered memory) → J Deeper Minds (mind schema, Reflect(),
  secrets) → K Knowledge & Story (rumor distortion → folklore → myth,
  dreams, historian v2) → L Society & Power (reputation, factions,
  economy depth) → M Faith & Meaning (ritual → religion → schism,
  narrative themes) → N The Town Awake (Town Consciousness v2 as a
  Phase G extension).
- CLAUDE.md: standing "Long-term design vision (2026-07)" section +
  Current state (v0.76.0) entry.

### Changed
- Nothing — zero code changes in this version, by instruction.

## [0.75.2] — NPC dialogue quality: temperature control + garbled-line filter

Response to a live report that NPC-NPC dialogue got "extremely worse" —
repetitive, off-topic, and garbled at once. `llm/dialogue.py`'s prompt
is unchanged since v0.72.1, so the regression is backend/model-side (the
llama.cpp default backend + the small default model under grammar-
constrained JSON). Two contained, low-risk code levers, plus a
live-tuning recommendation.

### Added
- `Config.llm_temperature` (default 0.7) + `--llm-temperature` CLI flag,
  sent with every call on both backends (previously left to the server's
  ~0.8 default). Lower temperature curbs the rambling/off-shape output
  small models produce under the JSON constraint — targets the "garbled
  / off-topic" symptom. Tunable live (0.5-0.6 for a small model that
  still wanders, 0.9 for variety on a stronger one).

### Changed
- `_is_sane_line` (the filter that degrades a bad LLM line to the
  deterministic fallback so broken text never reaches the feed) now also
  rejects garbled output: mostly-symbol/mojibake lines, single-token
  repetition loops ("no no no no"), and more leakage markers (field
  names like `line_a`, markdown fences, "here is"/"output:" preambles).
  Short interjections ("Hm.", "Aye.") still pass.

### Recommended (live-tuning, not a code change)
- All three symptoms at once is the fingerprint of an under-powered
  model. Now that GPU offload is confirmed working, the highest-leverage
  fix is a larger model (e.g. an 8B): the prompt and mechanics are
  sound; the 4B default is the bottleneck. Verify against your own runs
  (the project's source of truth) — the levers above help, but won't
  match a stronger model.

## [0.75.1] — weather "only rain" map fix + llama.cpp dynamic GPU fit

### Fixed
- Map showed falling rain on ~89% of ticks even though only ~49% of the
  year is actually labelled rain. Cause: the frontend's `RAIN_FLOOR`
  (`app.js`) — the precipitation below which no rain particles spawn —
  was `0.27`, the *clear/overcast* cutoff, so every "overcast" tick
  (~40% of the measured year) drew rain despite its dry label. Raised to
  `0.38`, the light-rain onset (`OVERCAST_PRECIPITATION_THRESHOLD` in
  `weather.py`'s `describe()`), so the map shows rain exactly when the
  sky label reads "light/heavy rain"; clear and overcast ticks are now
  dry (overcast still just reads darker via the existing weather tint).
  Verified by measuring the realized sky-band distribution over a full
  simulated year (clear 11% / overcast 40% / light rain 38% / heavy rain
  10% / snow <1%), per CLAUDE.md's standing "measure the reachable range
  before touching a weather threshold" rule. No engine/`weather.py`
  change — the deterministic model was already varied; only the display
  floor was miscalibrated.

### Changed
- `scripts/run.sh` and README now launch `llama-server` with
  `--n-gpu-layers auto --fit on` (new `LLAMA_FIT`/`LLAMA_FIT_TARGET` env
  vars) instead of the hardcoded `--n-gpu-layers 999`. `auto` + `--fit`
  (both llama.cpp defaults on recent builds) let llama.cpp dynamically
  size the GPU-layer offload to available VRAM. Older llama.cpp builds
  without `auto`/`--fit` fall back with `LLAMA_N_GPU_LAYERS=999
  LLAMA_FIT=` (documented in the script header and README).

### Note
- The `-O3 -march=native -mtune=native` extension compile flags reported
  as missing were already present (setup.py, added v0.73.3) and applied
  on every `pip install -e .` / `run.sh` build — no change needed; a
  rebuild picks them up if an older build predates them.

## [0.75.0] — AgentTable wired into live Population.agents (R8 slice 3 wire-in)

### Added
- `hearthmind/agents/agent_store.py` — `AgentStore`, an **id-keyed**
  structure-of-arrays store over the native `AgentTable` (v0.74.3). It
  resolves agent id→table slot internally on every access and updates
  that map from the table's swap-with-last `remove` result, so no
  Python-side `Agent` handle ever holds a slot and the staleness bug
  class the v0.74.2 scoping flagged is closed at the API boundary.

### Changed
- `Agent` (agents/agent.py) converted from a `@dataclass` to a
  hand-written class so its 12 dense scalar fields (`x, y, hunger,
  energy, state, age_ticks, max_age_ticks, starving_ticks, sick_ticks,
  immune_ticks, goal, settlement_id`) can be `@property` accessors
  backed by a native `AgentStore` once `Population` adopts the agent —
  the same compatibility-shim pattern `TerrainGrid`/`TerrainRow` used
  for the terrain grid. The `__init__` keyword signature and
  `to_dict`/`from_dict` are byte-for-byte preserved, so **zero of the
  ~700 scalar touch sites changed**. The six variable-size per-agent
  dict/list fields stay ordinary Python attributes. `state`/`goal`
  cross the C++ boundary as int codes via `STATE_TO_CODE`/`GOAL_TO_CODE`
  (agent.py, matching cpp/src/agent_table.cpp's header).
- `Population`: `__post_init__` builds the store (native only) and
  adopts every agent — covering both `spawn_initial` and `from_dict`;
  three one-line hooks adopt newborns (before `extend`) and migrants
  (before `append`) and remove the dead (`dying_ids`) after
  `self.agents = survivors`. `self.agents` stays an ordered
  `list[Agent]`; iteration order is decoupled from table slot order.
- **Fallback unchanged**: with no native extension, `Population` builds
  no store and every `Agent` keeps its scalars in plain `_x`/… locals,
  byte-identical to the pre-0.75.0 dataclass.

### Verified
- `scripts/verify_native_soak.py` gains an `agent_store` toggle: full
  `World.to_dict()` per-tick state is byte-identical native (AgentTable)
  vs. fallback (detached) across multiple seeds at 2,000 ticks and a
  12,000-tick/3-seed run (long enough to span births — agents mature at
  4,000 ticks). Plus a direct death + swap-with-last equivalence test
  (survivors stay correctly id-mapped after the dead are removed and
  the table reindexes) and a save→`from_dict`→reload round-trip
  (identical state, store live after load).

### Not yet done
- The agent tick **logic** (`population.py` method bodies) still runs in
  Python, now reading/writing scalars through the C++ store. Porting
  those to run in C++ over the table is the next leg toward the full
  engine — one method-group at a time, each verified against the Python
  it replaces before deletion.

## [0.74.3] — AgentTable: Agent scalar-field storage primitive (R8 slice 3, staged)

### Added
- `cpp/src/agent_table.cpp`'s `AgentTable` — a true structure-of-arrays
  (12 parallel `std::vector`s, one per `Agent` scalar field: `id, x, y,
  hunger, energy, state, age_ticks, max_age_ticks, starving_ticks,
  sick_ticks, immune_ticks, goal, settlement_id`) with `append`,
  swap-with-last `remove` (reports which agent id — if any — now
  occupies the freed slot, for the caller's id→slot map), and per-field
  get/set. Explicit user directive to pursue the Agent/Settlement/
  Population port despite v0.74.2's finding of no measured performance
  need. A dedicated scoping pass (before any code moved) found `Agent`'s
  scalar fields are touched ~700 times in `agents/population.py` alone,
  almost always interleaved with the six variable-size per-agent dict/
  list fields that can't flatten into a fixed-schema array — a much
  larger and riskier surface than terrain's ~60 clean indexing sites.
  Given that, **this version ships only the storage primitive**,
  verified in isolation; wiring it into the live `Population.agents`
  list (the compatibility-shim wrapper class + the ~700-site
  verification pass) is explicitly staged as separate follow-up work,
  not bundled into the same change. See docs/REFACTOR-2026-07.md's "R8
  slice 3" for the full scoping writeup and next-session plan.

### Verified
- 20,000-operation randomized fuzz test (append/remove/mutate) against
  a parallel Python reference implementation, checked every 500
  operations and at the end, 0 mismatches. Explicit bounds tests
  confirming out-of-range slot access raises rather than corrupting
  memory.

## [0.74.2] — R8/native-port design pass: no further code moved

### Changed
- Design-only pass (no code moved) on whether `Agent`/`Settlement`/
  `Population` are a tractable next R8 target, and whether any other
  native-port opportunity remains anywhere in the codebase. Findings
  (full writeup in docs/REFACTOR-2026-07.md's R8 section):
  - `Agent`'s storage (many variable-size per-agent dicts/lists, not
    two dense scalars like `Tile`) doesn't fit the `TerrainGrid`
    compatibility-shim pattern — the applicable pattern for Agent's
    hot scalar math is what module 6 (`_update_needs`) already does:
    extract primitives, compute in C++, write back, no storage change.
  - Re-checked every O(N)/O(N²)-flagged comment in `agents/
    population.py`'s tick loop — both previously-flagged quadratic
    spots are already resolved (module 4's `AgentPositionIndex` for
    SOCIALIZE; an algorithmic fix, not native code, for the old rival
    scan). No other function carries an unresolved cost flag.
  - **Conclusion: no measured-need candidate remains** for further
    native porting. R6/R7's queues are closed, R8's two safe storage
    slices (`SimClock`, terrain grid) are shipped. Recommends treating
    the native-port track as complete for now (not permanently
    closed) per CLAUDE.md's standing "escalate only with a measured
    need" rule — revisit only if population/map-size scale up enough
    to produce an actual measured tick-time problem.

## [0.74.1] — terrain grid native storage (R8 slice 2)

### Added
- `World.terrain` now stored via `TerrainGrid` (`world/terrain.py`),
  backed by a compiled flat-array store (`cpp/src/terrain_grid.cpp`,
  `hearthmind._native.TerrainGrid`) when available — the first R8
  module that ports actual object-graph STORAGE rather than an
  isolated pure function. `TerrainGrid`/`TerrainRow` implement the
  exact same indexing/iteration/length protocol a plain
  `list[list[Tile]]` already had (`terrain[y][x]`, `terrain[y][x] =
  Tile(...)`, `len(terrain)`, `for row in terrain: for tile in row`),
  so none of the ~60+ call sites across `world/*.py`/`agents/
  population.py`/`settlement/buildings.py` needed to change — Tile
  objects are materialized on demand from the flat elevation/biome
  arrays, never cached. Biome is stored as a plain int index into
  `tuple(Biome)` (all 9 members including RIVER, unlike terrain_
  evolution.py's `BIOME_ORDER`, which deliberately excludes it).
  Falls back to a genuine nested list when the native extension isn't
  built — byte-identical either way. Wired into `World.create_new`
  and `World.from_dict` via `TerrainGrid.from_nested(...)`; `to_dict`
  needed no change at all (iteration already produces the same nested
  structure).
- `scripts/verify_native_soak.py` gained the new toggle
  (`hearthmind.world.terrain._NativeTerrainGridImpl`).

### Verified
- Randomized read/iteration/mutation equivalence (500 random
  mutations) between the native-backed and pure-Python-fallback paths
  on a real `generate_terrain()` map, 0 mismatches. Full engine test:
  world creation → 3000 ticks → snapshot save → snapshot reload, with
  a full terrain diff after reload — 0 mismatches, confirming the
  compiled storage round-trips through `to_dict`/`from_dict` (and
  therefore SQLite persistence) correctly. Live `hearthmind.server`
  smoke test: `/terrain` and `/state` both serialize correctly, and a
  browser screenshot confirms the map renders identically — the swap
  is completely transparent to the frontend. Full-state verification
  harness (`scripts/verify_native_soak.py`, now including this
  toggle): all nineteen native modules match byte-for-byte across
  every tick, 4 seeds, 6000 ticks each.

## [0.74.0] — bridges (real water-crossing pathing); R8 full-state verification harness

### Added
- **Bridges**: closes the "True water transport" architectural gap
  CLAUDE.md flagged as needing "its own pathing-system pass, not a
  bolt-on." New `BuildingKind.BRIDGE` — unlike RAFT (a passive
  fishing-yield bonus that never touches passability), a STANDING
  bridge's spanned water tiles actually become walkable.
  `Population._is_walkable` gained a `bridge_tiles` parameter (same
  shape as the existing `mountain_unlocked` era-gate), threaded
  through `_step_toward`/`_bfs_step`/`_reachable_tiles`/`_dispatch_
  movement`. Bridges are founded like vehicles: a colocated group
  standing on a shore tile (water-adjacent) rolls `BRIDGE_CHANCE_PER_
  TICK`, then `_find_bridge_span` (a bounded multi-source BFS through
  water tiles, capped at `BRIDGE_MAX_SPAN`) searches for the nearest
  opposite shore not already reachable by land. `Building.x`/`y` stays
  the land anchor (agent-pathed construction/repair/decay all work
  unchanged); `Building.bridge_span` is the ordered water-tile path,
  fixed at founding time. Bridges are shared physical infrastructure
  across every settlement (`_bridge_tiles_from_settlements`), same as
  roads. Cost scales with span length (`BRIDGE_MATERIALS_COST_PER_
  SPAN_TILE`, floored at `BRIDGE_MIN_MATERIALS_COST`). Frontend: new
  "🌉"-colored building marker plus a rendered deck across the actual
  water span (`app.js`).
- **R8 full-state verification harness** (`scripts/verify_native_
  soak.py`): every native module until now was verified via a
  cumulative-event-hash soak (proves narrated consequences match, but
  a state field that never produces a life event could theoretically
  drift unnoticed). This script instead hashes the complete `World.
  to_dict()` snapshot every tick across a configurable seed list, with
  every native module's Python-fallback toggle flipped in one pass —
  the "heavier full-state-diffing verification harness" the R8 scoping
  doc (v0.73.1) called for building before the next object-graph
  slice. Sanity-checked to actually detect divergence (two different
  seeds produce different hashes) before trusting its "no divergence"
  result. All eighteen native modules pass full per-tick state
  equality across a 6000-tick, 4-seed run.

### Verified
- `_find_bridge_span` unit-tested against synthetic terrain: exact
  span found across a narrow strait, `None` correctly returned for a
  gap wider than `BRIDGE_MAX_SPAN`, `None` correctly returned when the
  two "shores" were already land-connected elsewhere (no redundant
  bridge). Direct engine test: a founded bridge reaches STANDING and an
  agent's `travel_target` successfully routes across a STANDING
  bridge's span through a full `SimulationEngine._tick_once()` loop
  (not just the isolated pathing functions). `Building.to_dict`/
  `from_dict` round-trip verified, including legacy-snapshot backward
  compatibility (missing `bridge_span` key defaults to `()`). 6000-
  tick/3-seed regression soak confirms no behavior change when bridges
  aren't present (the common case). Live `hearthmind.server` smoke
  test confirmed `/state` serializes bridge buildings without error.

## [0.73.3] — build flags (-O3/-march=native); world/hydrology.py fully traced

### Added
- `setup.py`'s native extension now compiles with `-O3 -march=native
  -mtune=native` (non-Windows only — MSVC uses different flag syntax).
  `-O4` isn't a real GCC/Clang flag (both cap at `-O3`); `-Ofast` goes
  further but changes floating-point semantics in ways that could
  affect this project's byte-identical-vs-Python verification
  discipline, so it's deliberately not used. `-march=native` is safe
  specifically because this extension is always built locally on the
  machine that runs it (`scripts/run.sh` / `pip install -e .`), never
  distributed as a prebuilt wheel — a binary built for one CPU and
  copied to a different one could crash on an unsupported instruction,
  which is why this flag isn't used for portable wheel builds
  generally. Re-verified via a 4-seed, 6000-tick cumulative-event-hash
  soak after rebuilding with the new flags — identical hashes to every
  prior `-O2` soak run, confirming the more aggressive codegen changes
  nothing observable.
- `world/hydrology.py` fully traced (closing the one item still marked
  "not yet traced" in the R7 queue): `generate_rivers`/`identify_lakes`
  are both world-creation-only (called once from `World.create_new`
  and once from the legacy-snapshot-migration backfill path in `World.
  from_dict`), never per-tick — zero tick-time cost to port, so
  correctly out of scope regardless of RNG shape. `tick_lakes` was
  already ported (module 12, `bounded_random_walk_step`). This closes
  out the R7 opportunistic-port queue entirely — every function in the
  original queue is now either ported, individually confirmed
  not-worth-porting, or confirmed one-time/creation-only.

## [0.73.2] — maybe_reclaim native port (17); SimClock.advance native port (18, first R8 slice)

### Added
- Native port module 17: `maybe_reclaim`'s scan/roll loop (world/
  terrain_evolution.py) → `maybe_reclaim_tick` (`cpp/src/reclaim.cpp`)
  — the first module using a callback-into-Python-RNG design rather
  than pre-drawing. `maybe_reclaim` has a genuine same-pass dependency
  (an earlier tile's reclaim in the same pass changes a later tile's
  forest-neighbor count), confirmed unportable via pre-drawing since
  v0.72.11. The C++ loop calls back into `rng.random` for each
  conditional roll, preserving the exact same-pass order/count while
  moving the neighbor-scan/branching into C++. Verified via 500 direct
  `maybe_reclaim()` A/B runs on synthetic mixed grassland/forest
  terrain (0 mismatches) plus the cumulative-event-hash engine soak.
- Native port module 18: `SimClock.advance()` (time_system.py) →
  `sim_clock_advance` (`cpp/src/sim_clock.cpp`) — the first module
  that IS the engine advancing a world tick, not a system running on
  one; runs unconditionally exactly once per tick for a world's entire
  life. Pure calendar arithmetic, no RNG, no object graph (Config's
  calendar shape unpacked to plain values before the call). The first,
  deliberately small slice of the R8 "engine running world ticks"
  track. Verified via a 200,000-tick sequential lockstep A/B (native
  vs. Python fallback clocks advancing together) spanning multiple
  years and every calendar boundary, 0 mismatches.
- Both verified together via a 5-seed, 8000-tick cumulative-event-hash
  engine soak, all eighteen native modules on vs. off, byte-identical.
  Live-server smoke test confirmed `terrain_reclaimed` events fire
  correctly through the browser UI's event feed.

## [0.73.1] — climate_drift native port (module 16); R8 full-rewrite scoping

### Added
- Native port module 16: `apply_climate_drift`'s biome-step mutation
  (world/terrain_evolution.py) → `classify_biome_index`/`climate_drift_
  batch` (`cpp/src/climate_drift.cpp`) — the first module where a
  `Biome` enum value crosses the pybind11 boundary, expressed as a
  plain `int` index into `BIOME_ORDER` on both sides (Python converts
  both ways; no precedent existed for the enum itself crossing).
  Direct A/B verification of the wrapper function (not just the raw
  functions) caught a genuine same-pass dependency the raw-function
  check missed: `rng.randrange` samples tiles with replacement, so a
  duplicate `(x, y)` draw's second occurrence must read the first
  occurrence's already-stepped biome — fixed by calling the native
  function once per sample (reading current terrain state each
  iteration) rather than batching every sample into one call. Verified
  via 50,000 randomized inputs against the raw functions, 500 direct
  `apply_climate_drift()` A/B runs (0 mismatches after the fix), and
  the cumulative-event-hash engine soak across four seeds at 6000
  ticks each, all sixteen native modules on vs. off, byte-identical.
  See docs/DECISIONS.md for the full root-cause writeup.
- R8 scoping (docs/REFACTOR-2026-07.md): a design-first pass on the
  "full engine rewrite" directive, laying out three readings from
  narrowest (finish the R6/R7 opportunistic-port queue — already in
  flight) to broadest (rewrite everything but SQLite/asyncio/FastAPI).
  No object-graph porting has started — recommends confirming scope
  with the user before committing to it, given the lack of an
  automated test suite and the real risk profile of porting `Agent`/
  `Settlement`/`Population` themselves versus porting isolated pure
  functions as every module so far has done.

## [0.73.0] — event feed filters to LLM conversations; on-demand summary tab

### Added
- Event log filtering: `/events` and `/history` (and the main UI's
  Recent Events feed) now only show `dialogue`/`dialogue_surfaced`
  entries for genuine core-cast LLM-authored exchanges — deterministic
  fallback dialogue (the crowd, and any core pair that degraded to its
  fallback under backpressure/budget) still runs its full mechanic
  (relationships/trust/gossip effects, `dialogue_total`) but no longer
  reaches the narrative event log. `SimulationEngine._pending_dialogue_
  results` carries a new `is_llm` flag (`not used_fallback` from
  `_run_dialogue`, `False` from `_queue_fallback_dialogue`) threaded
  through to `_apply_pending_dialogue_results`, which now only calls
  `_log` for `is_llm=True` exchanges. Rumor events stay unconditional
  (an emergent consequence, not raw conversation text).
- On-demand simulation summary: new "🧭 summary" tab — `POST /summary/
  request` queues a `request_summary` intervention (same enqueue-now/
  apply-next-tick seam as every other intervention), applied by
  `SimulationEngine._schedule_summary` via the shared `_schedule_llm_
  job` path (daily LLM ceiling still applies; deliberately NOT gated by
  `_settlement_job_backpressured` since that gate exists to smooth the
  monthly job cluster, not a single user-triggered request). New
  `llm/summary.py` (`build_prompt`/`fallback_summary`/`parse_summary`,
  same shape as `documentary.py`). Result persists on `World.
  sim_summary_text`/`sim_summary_tick` (serialized; `sim_summary_
  pending` deliberately not persisted — a generation left in flight at
  shutdown must load back as `False`, not stuck). `GET /summary` reads
  it off the existing broadcast payload (`world.summary()`'s new
  `sim_summary` key) rather than touching the engine directly. Also
  logged under a new `sim_summary` event category (icon 🧭, "mind"
  filter group) so it reaches the main event feed and dev console too.
- Verified via a 3000-tick, 3-seed `llm_enabled=False` soak (fallback
  dialogue mechanic still runs, `dialogue`/`dialogue_surfaced` event
  rows correctly absent) plus a direct `_apply_intervention({"type":
  "request_summary"})` round-trip and a `World.to_dict`/`from_dict`
  persistence round-trip for the new fields.

## [0.72.14] — tick_wildfire's spread roll now reuses module 15

### Added
- `tick_wildfire`'s spread step (world/disasters.py) now dispatches to
  module 15's `roll_passes_tick` — no new C++ needed. Re-traced the
  spread loop (previously assumed hard, alongside `maybe_reclaim`) and
  found each (active tile, neighbor) pair's spread eligibility depends
  only on the pre-loop snapshot of `active_wildfire_tiles` and terrain
  biomes, never on another pair's outcome within the same pass —
  own-tile conversion draws no RNG at all, so it stays a plain Python
  pass; only the neighbor-spread rolls get batched. Verified via 300
  direct `tick_wildfire()` A/B runs on synthetic terrain/fire state (0
  mismatches) plus the cumulative-event-hash engine soak across five
  seeds at 6000 ticks each, byte-identical.

## [0.72.13] — Native port module 15: deforestation roll batch

### Added
- Native port module 15: `apply_local_activity`'s deforestation roll
  (world/terrain_evolution.py) → `roll_passes_tick`
  (`cpp/src/roll_batch.cpp`), a small shared "which of these pre-drawn
  rolls beat their chance" utility. Re-examined the RNG-in-loop concern
  flagged in v0.72.11/12: this specific loop's per-tile eligibility
  (heat value + current biome) depends only on state that exists
  *before* the loop runs, never on another tile's outcome within the
  same pass — unlike `maybe_reclaim` (a forest-neighbor count that
  changes as earlier tiles in the same loop convert), which genuinely
  doesn't fit this pattern and stays pure Python. Python determines the
  candidate set, pre-draws one roll per candidate (same order the
  original loop would), and hands the batch to the native comparison.
  Verified via 20,000 randomized inputs against the trivial reference
  (0 mismatches), 300 direct `apply_local_activity()` A/B runs on
  synthetic terrain/heat state (0 mismatches), and the cumulative-
  event-hash engine soak across four seeds, all fifteen native modules
  on vs. off, byte-identical.

## [0.72.12] — Native port module 14: storm flat-damage sweep

### Added
- Native port module 14: the flat-damage sweep inside `tick_storm`
  (world/disasters.py) → `flat_damage_tick` (`cpp/src/flat_damage.cpp`).
  The single storm-trigger roll (gated on wind threshold, short-
  circuited so the RNG draw is itself conditional) stays in Python
  exactly as before; once triggered, every standing building and every
  vehicle (regardless of stage) across all settlements takes a flat,
  unconditional `max(0, condition - damage)` hit with no further
  randomness — the simplest possible per-cell local rule. Verified via
  10,000 randomized inputs (0 mismatches) plus the cumulative-event-
  hash engine soak across four seeds, all fourteen native modules on
  vs. off, byte-identical.

## [0.72.11] — Native port module 13: farm-wilt disaster math

### Added
- Native port module 13: `_wilt_farms` (world/disasters.py, shared by
  `tick_heatwave` and `tick_frost`) → `wilt_farms_tick`
  (`cpp/src/wilt_farms.cpp`). Rolls exactly one `rng.random()` per farm
  plot, unconditionally — unlike `world/terrain_evolution.py`'s
  activity/reclaim loops (where the number of rolls depends on which
  tiles clear a heat threshold first, making the total draw count
  itself data-dependent), this has a fixed, data-independent draw
  count per call, so Python pre-draws the whole roll batch (preserving
  exact stream order) and hands it to the native call. Verified via
  20,000 randomized input combinations against a reference Python port
  (0 mismatches), 500 direct `_wilt_farms()` A/B runs on cloned farm
  grids (0 mismatches), and the cumulative-event-hash engine soak
  across four seeds, all thirteen native modules on vs. off,
  byte-identical.

## [0.72.10] — Native port module 12: shared bounded-random-walk step

### Added
- Native port module 12: the bounded-random-walk step shared by
  `Settlement.tick_temperament`/`tick_player_standing`/`tick_relation`
  (settlement/buildings.py) and `tick_climate`/the lake-level nudge
  inside `tick_lakes` (world/terrain_evolution.py, world/hydrology.py)
  → `bounded_random_walk_step` (`cpp/src/bounded_random_walk.cpp`). All
  five call sites shared the identical `value*mean_reversion + jitter
  [+ extra], clamped to [-1, 1]` shape, so this is one native function
  reused five times rather than five near-identical ports — same
  dedup principle as `util.py`'s existing `clamp`/`namespaced_rng`
  helpers. RNG draws stay in Python at every call site. Verified via
  30,000 randomized inputs against the pure function (0 mismatches),
  direct multi-call sequences for each of the five call sites (0
  mismatches), and the cumulative-event-hash engine soak across four
  seeds at 6000 ticks each (long enough to span several months, so the
  monthly-cadence call sites actually fire), all twelve native modules
  on vs. off, byte-identical.

## [0.72.9] — Native port module 11: weather blend/threshold math

### Added
- Native port module 11: `compute_weather`'s blend/threshold math →
  `compute_weather_blend` (`cpp/src/weather.cpp`). Unlike modules 1-10,
  `compute_weather` draws from a seeded `random.Random` stream — the
  three `rng.uniform(...)` jitter draws stay in Python (reproducing
  CPython's Mersenne Twister bit-for-bit in C++ isn't needed under this
  project's "determinism is not a requirement" rule, and would be a
  project of its own); only the baseline+jitter/clamp/EMA-blend/snow-
  threshold arithmetic that follows crosses into C++. Verified via
  30,000 randomized input combinations against a reference Python port
  (0 mismatches), a direct 20,000-tick `compute_weather()` A/B run
  across all twelve months (0 mismatches), and the cumulative-event-
  hash engine soak across four seeds, all eleven native modules on vs.
  off, byte-identical.

## [0.72.8] — Native port modules 9-10: building and vehicle decay

### Added
- Native port modules 9-10: `Settlement.tick`'s building decay/ruin/
  reclaim pass → `building_decay_tick`, and its READY-vehicle decay
  pass → `vehicle_decay_tick` (both in `cpp/src/settlement_decay.cpp`).
  Same shape as `farm_grid_tick` (module 8) — a fixed collection of
  independent cells (buildings/vehicles), each updated purely from its
  own prior state. Event text (needs building/vehicle x/y) stays in
  Python; the native calls return per-cell result flags
  (`just_ruined`/`removed`/`just_broke`) so Python knows exactly when
  to log which event. Verified via 20,000 (buildings) and 10,000
  (vehicles) randomized input combinations (0 mismatches) plus the
  cumulative-event-hash engine soak across four seeds at 5000 ticks
  each, all ten native modules on vs. off, byte-identical.

## [0.72.7] — Native port module 8: FarmGrid.tick (first R7 module)

### Added
- Native port module 8: `FarmGrid.tick` → `farm_grid_tick`
  (`cpp/src/farm_grid.cpp`), the first module shipped under R7. Plain
  per-plot local rule (GROWING accumulates growth and flips to READY;
  READY accumulates ready-ticks and rots past `FARM_ROT_TICKS`) — same
  shape as `resource_grid_tick` (module 1). Irrigation adjacency stays
  a Python-side terrain lookup, resolved before the call. Verified via
  20,000 randomized input combinations (0 mismatches), 500 direct
  `FarmGrid.tick()` A/B runs on cloned grids (0 mismatches), and the
  cumulative-event-hash engine soak across four seeds, all eight native
  modules on vs. off, byte-identical.

## [0.72.6] — Native port module 7, new scope: C++ cellular-automata physical substrate (R7)

### Added
- Native port module 7: `Population._maybe_predator_attack`'s
  kill-chance math → `predator_kill_chance`
  (`cpp/src/predator_kill_chance.cpp`). Pure arithmetic only — both
  `rng.random()` rolls stay in Python, in original order, so the
  namespaced-RNG stream is untouched. Verified via 50,000 randomized
  inputs (0 mismatches) plus a four-seed cumulative-event-hash soak,
  all seven native modules on vs. off, byte-identical.
- **New standing scope, R7** (docs/REFACTOR-2026-07.md, CLAUDE.md
  design priorities): the deterministic physical-reality layer
  (agriculture, ecology/wildlife, weather, environment effects,
  disasters, terrain evolution) is now explicitly framed as a
  cellular-automata-style substrate, and any *new* code in that domain
  is written directly in C++ from the start — pybind11 binding + pure-
  Python fallback + verification pass from the first commit, not
  Python-first-then-ported. Existing not-yet-ported Python in this
  domain (weather.py, terrain_evolution.py, disasters.py, hydrology.py,
  economy/farms.py, most of buildings.py's decay math) keeps moving
  incrementally under R6's existing queue; R7 governs new code, it
  doesn't force an immediate rewrite of the backlog. The LLM/
  deterministic split (town consciousness, supernatural ambiguity,
  everything judgment/social/psychological) is explicitly unchanged.

## [0.72.5] — Native port modules 5-6, full engine-core rewrite started (R6)

Explicit user directive: port all remaining code to C++, then begin a
full engine rewrite (SQLite persistence, asyncio LLM scheduling, and
FastAPI stay Python — see docs/DECISIONS.md for the scope discussion
and the conflict this raises with the project's earlier "full C++ port:
evaluated, recommended against" finding).

### Added
- Native port module 5: `WildlifeGrid.nearest_grazer_herd` →
  `GrazerHerdIndex` (`cpp/src/wildlife_index.cpp`). Live-patched by
  `hunt()`, same shape as `ResourceIndex`. A real ordering bug was
  caught during verification (unordered_map iteration order didn't
  match Python dict insertion order, causing wrong tie-break resolution
  on 238/20,000 randomized queries) and fixed with an insertion-order
  vector — see docs/REFACTOR-2026-07.md for the full writeup.
- Native port module 6 (first from the new R6 "full engine rewrite"
  track): `Population._update_needs` → `update_needs`
  (`cpp/src/needs.cpp`). Unlike modules 1-5 (goal-gated lookups), this
  runs unconditionally for every agent every tick. Constants passed as
  parameters (via a `NeedsConstants` struct) rather than duplicated as
  C++ literals, since they're spread across three Python files with no
  single home. Verified via 50,000 randomized input combinations (0
  mismatches) plus the cumulative-event-hash soak across three seeds.
- `docs/REFACTOR-2026-07.md` gained an "R6: full engine-core rewrite"
  section scoping what's in bounds (pure deterministic math/branching
  over already-resolved primitives) vs. out of bounds (anything
  touching the Python object graph, SQLite, asyncio, or the LLM client)
  and a queued-next list for future R6 modules.

## [0.72.4] — RAM correction (real ~6.5GB usable), run.sh simplified, native port module 4

Follow-up to v0.72.3 based on a live `htop` reading: actual usable RAM
on the target machine is ~6.5GB, not the full 8GB v0.72.3 assumed when
raising LLM config. Dials the LLM config back down accordingly (still
above the original CPU-only-tuned baseline — GPU offload is a genuine
win), removes `scripts/run.sh`'s llama.cpp build/clone automation
(build llama.cpp yourself; the script only builds `hearthmind._native`),
switches the script to `python` instead of `python3`, adds `pybind11` to
`requirements.txt`, and ports a fourth module to C++.

### Changed
- `Config.llm_num_ctx` 4096 → **3072**, `llm_num_predict` 640 → **512**,
  `llm_core_cast_size` 18 → **14**, `llm_max_calls_per_day` 400 → **320**
  — re-lowered from the v0.72.3 pass once the user's live `htop` reading
  showed only ~6.5GB usable RAM. Still real headroom over the original
  CPU-only-tuned values (1280/384/11/200); see each field's docstring in
  `config.py` for the full before/after chain.
- `scripts/run.sh` no longer builds or clones `llama.cpp`/`llama-server`
  — build it yourself (see README) and point `LLAMA_SERVER_BIN` at the
  binary, or have it on `PATH`. Removed `LLAMA_CPP_DIR`,
  `AUTO_CLONE_LLAMA_CPP`, and `USE_VULKAN` (Vulkan builds are now a
  manual `cmake` step, documented in README). Still builds
  `hearthmind._native` automatically (`SKIP_NATIVE_BUILD=1` to skip).
  Uses `python` instead of `python3` throughout.
- `requirements.txt` now lists `pybind11>=2.11` (build-time only, for
  `hearthmind._native`) alongside the existing `--api-enabled` deps.

### Added
- Native port module 4: `Population._nearest_other_agent` (the
  SOCIALIZE-goal lookup) — `AgentPositionIndex`
  (`cpp/src/agent_position_index.cpp`), rebuilt once per
  `Population.tick()` from the same `position_snapshot` the pure-Python
  path already builds. This is the highest-value native port so far:
  unlike the terrain/resource lookups, SOCIALIZE has no distance cap,
  so the scan genuinely scales with population squared, not map size.
  Verified via 20,000 randomized queries (0 mismatches) plus the
  cumulative-event-hash engine soak at both a small and a 60-agent
  population (byte-identical both times).

## [0.72.3] — GPU-offload confirmed: run.sh builds everything, richer LLM config, native port module 3

Response to a live report: GPU offload via llama.cpp is confirmed
working and "much much better than expected" on real hardware. Uses
that confirmation to relax settings that were tuned tight for CPU-only
8GB inference, and to expand `scripts/run.sh` into a full build+run tool.

### Added
- `scripts/run.sh` now builds `hearthmind._native` automatically
  (`SKIP_NATIVE_BUILD=1` to skip) and builds `llama-server` itself if
  missing (cloning `llama.cpp` first if `AUTO_CLONE_LLAMA_CPP=1`, or
  printing the clone command otherwise; `USE_VULKAN=1` for AMD iGPU
  offload). New defaults match the confirmed-working GPU recipe:
  `LLAMA_N_GPU_LAYERS=999`, `LLAMA_CACHE_TYPE_K/V=q8_0`.
- `--llm-num-ctx`/`--llm-num-predict` CLI flags on `server.py` (existed
  as `Config` fields but had no CLI exposure until now).
- Native port module 3: `Population._nearest_material_tile` (the
  GATHER-goal equivalent of `_nearest_resource`) — `TerrainMaterialIndex`
  (`cpp/src/terrain_index.cpp`), rebuilt once per `Population.tick()`.
  Simpler than `ResourceIndex`: MATERIAL_BIOMES tiles never deplete, so
  no live-patch is needed. Verified via 20,000 randomized queries (0
  mismatches) plus the standard cumulative-event-hash engine soak.

### Changed (LLM config, now that GPU offload is confirmed)
- `Config.llm_num_ctx` 1280 → **4096**, `llm_num_predict` 384 → **640**
  — the CPU-only-Ollama KV-cache pressure that motivated the tight
  v0.71.1 numbers doesn't apply the same way with GPU offload + q8_0 KV
  quantization.
- `PROMPT_RECENT_EVENTS` 30 → **50** (restored to its pre-v0.71.1 level),
  `DIALOGUE_MEMORY_IN_PROMPT` 1 → **2** — richer context per prompt.
- `Config.llm_core_cast_size` 11 → **18**, `llm_max_calls_per_day`
  200 → **400**, `MAX_LLM_DIALOGUES_PER_TICK` 2 → **4**,
  `MAX_DIALOGUES_PER_TICK` 3 → **6** — confirmed-fast GPU inference
  affords a larger LLM-driven cast and more core-core dialogue volume
  without recreating the sustained-saturation swap condition v0.70.0
  fixed.
- Dialogue line-length budget "under 10 words" → "under 14 words"
  (`_MAX_LINE_WORDS` 22 → 26) and `SYSTEM_PROMPT` gained a tense-band
  few-shot example, for less clipped, more natural exchanges.
- README's 8GB/CPU-only recipe is preserved and clearly marked as the
  non-default path (`LLAMA_CTX_SIZE=1280 LLAMA_N_GPU_LAYERS=0` +
  `--llm-num-ctx 1280 --llm-core-cast-size 8`) for anyone still on that
  hardware profile.

## [0.72.2] — pyproject license fix, one-command run script, native port module 2

### Fixed
- `pyproject.toml`'s `project.license` moved from the deprecated
  `{ text = "MIT" }` TOML table to the SPDX string form (`license =
  "MIT"`) — silences the setuptools deprecation warning on `pip install
  -e .`. Requires `setuptools>=77`/`packaging>=24.2`, bumped in
  `build-system.requires`; resolved automatically by `pip install -e .`
  via build isolation.

### Added
- **`scripts/run.sh`**: one command that starts `llama-server` (with
  this project's tuned 8GB flags) and `hearthmind.server` together,
  waits for llama-server's `/health` before starting the sim, and
  forwards Ctrl+C to both processes cleanly (hearthmind's own graceful
  shutdown/snapshot runs first). Configurable via `MODEL_PATH`,
  `LLAMA_SERVER_BIN`, `LLAMA_HOST`, `LLAMA_CTX_SIZE`, `LLAMA_THREADS`,
  `LLAMA_N_GPU_LAYERS`, `LLAMA_EXTRA_ARGS`; every other argument passes
  through to `hearthmind.server`.
- **Native port, module 2: `Population._nearest_resource`.** A compiled
  `ResourceIndex` (`cpp/src/resource_grid.cpp`) — the bounded-box
  FOOD/FISH lookup the v0.67.0 profiling pass identified as the top
  hotspot. Rebuilt once per `ResourceGrid.tick()`, live-patched at each
  forage/gather depletion site (via the existing `mark_regenerating`
  call, same hook R4's working set already uses) so same-tick ordering
  between agents matches the pure-Python scan exactly. Verified via
  20,000 randomized queries (0 mismatches vs. a reference Python scan)
  plus the existing 4000-tick engine soak (identical event-stream hash
  to pre-port).

### Corrected
- `docs/REFACTOR-2026-07.md`'s R5 "queued next" list previously named
  `world/weather.py`'s "per-tile grid pass" and `world/terrain_
  evolution.py` as native-port candidates — on closer inspection
  neither is: `compute_weather` is O(1) per tick, not a grid pass, and
  terrain evolution runs on a weekly/monthly cadence touching cross-
  module state. Corrected; `_nearest_material_tile` is the more honest
  next candidate but is deliberately left unported pending a measured
  hotspot, not ported speculatively.

## [0.72.1] — LLM core-cast map markers + dialogue quality pass

Closes the two items explicitly deferred from v0.72.0.

### Added
- **LLM core-cast agents render as blue triangles** on the live map
  instead of the plain dot everyone else gets — `is_core` is now
  broadcast per-agent (`SimulationEngine._maybe_broadcast`, backed by
  `Population.is_core`). Hover tooltip and the NPC inspector both show a
  "▲ core" badge with an explanatory title/tooltip. Shared
  `drawAgentTriangle` helper (also now used for predator-pack markers,
  previously inlined separately).

### Changed (dialogue quality, both LLM and deterministic paths)
- `llm/dialogue.py`'s `build_prompt` now grounds each speaker's current
  activity in *why* (`agent.goal_reason`, when cognition set one) —
  previously only the bare goal name ("currently forage") reached the
  prompt. Measured worst-case prompt size with this addition: ~786
  tokens including the system prompt, still comfortably under the
  1280-token `llm_num_ctx` budget tuned in v0.71.1.
- `SYSTEM_PROMPT` explicitly permits disagreement, deflection, and
  imperfect exchanges (previously implicitly pushed toward tidy
  back-and-forth agreement) and adds a tense-band example, aiming at
  less uniformly pleasant dialogue.
- `fallback_dialogue` (the deterministic path, used whenever the LLM is
  disabled/unreachable/backpressured) now splices in a memory-grounded
  opening line roughly one exchange in three for non-tense pairs,
  referencing whichever speaker has a recent memory — previously 100%
  static template pools with zero connection to what had actually
  happened in the world. Each sentiment pool widened 5 → 8 entries for
  a longer repeat cycle.

Verified via a 6000-tick engine soak (`llm_enabled=False`): no crash,
sampled dialogue events show the memory-grounded lines interleaving
correctly with the pool lines.

## [0.72.0] — llama.cpp default backend + native C++ port begins

Response to an explicit user directive: port hot engine code to C++,
switch the default LLM backend from Ollama to llama.cpp, and tune for
AMD Ryzen iGPU offload. Scoped to a realistic, verifiable increment per
session rather than attempted as one unreviewable rewrite — see
`docs/REFACTOR-2026-07.md`, "R5" for the full rationale and queued next
steps.

### Added
- **`hearthmind._native`**, an optional pybind11 C++ extension
  (`cpp/src/resource_grid.cpp`, built via `setup.py build_ext --inplace`
  or automatically by `pip install -e .`). First ported module:
  `world/resources.py`'s `ResourceGrid.tick`. Every ported function has
  a pure-Python fallback (`_tick_python`) used automatically when the
  extension isn't built — never a hard dependency. Verified
  byte-identical to the pure-Python path via a 3000-tick equivalence
  script hashing final node-amount state, plus a 4000-tick engine soak
  with the extension loaded.
- **`LlamaCppClient`** (`hearthmind/llm/client.py`) — talks to
  llama.cpp's own `llama-server` via its OpenAI-compatible
  `/v1/chat/completions` endpoint, using `response_format: json_object`
  for grammar-constrained JSON output. `Config.llm_backend` (default
  `"llamacpp"`) selects it; `"ollama"` keeps the original `OllamaClient`
  fully supported. `build_llm_client(config)` factory used by both
  `SimulationEngine` and `server.py` so the two call sites can't drift.
- `Config.llm_llamacpp_host` (default `http://localhost:8080`),
  `--llm-backend`/`--llm-llamacpp-host` CLI flags.
- README: full llama.cpp build/run instructions (CPU + AMD iGPU Vulkan
  offload for the Radeon 740M/780M family, `--no-mmproj` to drop
  unneeded image support, 8GB memory tuning via `--ctx-size`/
  `--parallel`/`--cache-type-k/-v`), plus a "Native C++ extension"
  section.

### Changed
- `LLMUnavailable` replaces `OllamaUnavailable` as the base exception
  name (both backends raise it); `OllamaUnavailable` kept as an alias
  for compatibility.
- `system_memory_report()`'s process-matching now also recognizes
  `llama-server`/`llama-cli`/`llama.cpp` process names, not just
  `ollama` — `/diagnostics.system_memory` attributes memory correctly
  under either backend (still reported under the `ollama_processes` key
  for UI/README backward compatibility).

### Known limitations (be honest about scope)
- This sandbox has no GPU — the AMD Vulkan iGPU instructions are
  correct llama.cpp usage but **not verified against real Radeon
  740M/780M hardware** by this pass; report back what you observe.
- The native C++ port covers exactly one module so far. `population.py`/
  `engine.py`/`buildings.py` (the orchestration layer, ~8,400 lines
  combined) are explicitly NOT ported and are not simple mechanical
  translations — see `docs/REFACTOR-2026-07.md` R5 for why, and what's
  queued next.

## [0.71.1] — Ollama memory: shrink KV cache + definitive 8GB README

Response to "swap is even worse than before." Audit conclusion: reducing
LLM *call volume* (v0.70.0) never shrinks Ollama's *resident* memory —
model weights + KV cache sit in RAM while the model is warm regardless
of call frequency. Resident Ollama memory = weights + `num_ctx ×
OLLAMA_NUM_PARALLEL × dtype` KV cache, and the KV cache is allocated up
front at `num_ctx` no matter how short prompts are.

### Changed (app-side KV-cache reduction, verified byte-identical for
the deterministic sim)
- `llm_num_ctx` 2048 → **1280** and `llm_num_predict` 512 → **384**,
  after *measuring* real prompts: the largest (monthly chronicle) peaks
  at ~1000 tokens incl. generation, so 1280 fits with a ~280-token
  margin. Cuts our KV footprint ~37% unconditionally.
- Recent events fed into settlement prompts 50 → **30**
  (`PROMPT_RECENT_EVENTS`) — the dominant prompt term — so the lower
  `num_ctx` can't truncate a real prompt.

### Docs
- Rewrote the README's 8GB section into a prominent, turnkey **"⚠️
  Running on 8GB RAM — stop Ollama from swapping"** recipe: the
  dominant fix is Ollama *server* env vars (`OLLAMA_NUM_PARALLEL=1` —
  down from a default of 4 — plus `OLLAMA_KV_CACHE_TYPE=q8_0` +
  `OLLAMA_FLASH_ATTENTION=1`, together ~8× less KV cache), with the
  model size-down (`qwen3:1.7b`) and `--llm-core-cast-size` as
  escalations, and `ollama ps` / `/diagnostics.system_memory` to
  confirm. Added a pointer to it from "Running it".

## [0.71.0] — Unbounded-growth audit: event-log retention + query clamps

Follow-up to the v0.70.0 swap fix: a full re-audit for any structure
that can grow without bound. The Python/RAM side is clean — every
per-agent/per-pair collection is capped or pruned (memories, beliefs at
MAX_PERSONAL_BELIEFS, institution beliefs at INSTITUTION_BELIEF_CAP,
relationships/trust, cooldowns, omen/priority history, records,
memorials, core cast, engine pending/debug dicts, broadcast buffer,
snapshot-payload cache, place_names is bounded by the map's fixed lake
count). Two genuine unbounded-growth vectors were found and fixed, both
on the persistence/interface boundary rather than the sim core:

### Fixed
- **Events table had no retention** — the one truly unbounded table on a
  persistent, always-running world (snapshots already prune to recent +
  keyframes; metrics grow ~1 row/sim-day). At ~1-2 rows/tick an
  indefinite run grew the DB file without limit. Added `_prune_events`
  on the snapshot cadence, keeping `Config.event_log_retention` (default
  200k) most-recent rows — lossless for every reader (live feed reads 50,
  History 200, deep state lives in snapshot keyframes). CLI
  `--event-log-retention` (0 disables). Bounds the DB to tens of MB.
- **Unclamped query `limit`** — `/events`, `/history`, `/metrics` took a
  client-supplied `?limit=` straight to SQLite; against a large events
  table a huge limit would pull that many rows into RAM in one request.
  `recent_events`/`history_events`/`recent_metrics` now clamp to
  `QUERY_LIMIT_MAX` (5000, far above any UI view).
- **Intervention queue** — defensively capped at `INTERVENTION_QUEUE_MAX`
  (256); it drains every tick, but a POST burst against a stalled/paused
  loop could otherwise grow it unbounded. Oldest dropped past the cap.

## [0.70.0] — LLM core cast + daily call ceiling (swap-after-hours fix)

Root-causes and fixes the live report that swap usage climbs after a
few hours of running. Also lands R3 of the refactor roadmap (finish the
`clamp()` migration); R1/R2/R4 remain paused for this urgent fix.

### Fixed — Ollama swap climbs over hours
- **Root cause**: total LLM call *throughput* scaled linearly with
  population. Cognition scheduled one goal-reevaluation per agent per
  sim-day (→ population calls/day) and dialogue up to
  `MAX_DIALOGUES_PER_TICK` per tick; as a town grew from ~12 to hundreds
  over a few real hours, Ollama went from lightly loaded (idle gaps, the
  model unloads per `keep_alive`) to **continuously saturated** — always
  2 calls in flight, back-to-back for hours. Sustained saturation keeps
  the model + KV cache permanently resident and lets Ollama's own slow
  per-call memory growth accumulate into swap on 8GB. The Python side
  has no leak — every per-agent/per-pair structure was already
  capped/pruned (re-audited).
- **Fix — LLM core cast** (`Config.llm_core_cast_size`, default 11):
  only a fixed, sticky cast of ~11 NPCs gets LLM cognition, and only a
  *pair* of them gets LLM-authored dialogue; every other agent and every
  mixed/crowd pair runs on the already-real deterministic fallback.
  Total Ollama call volume is now **decoupled from population** —
  verified ~11.5 calls/sim-day at population 120 (vs. ~120/day before).
  The cast is seeded from founders, sticky (a member stays until death),
  and refilled from the most-prominent living non-member on death
  (`Population.maintain_core_cast`/`_prominence`). Persisted. Also a
  design win: the cast are the persistent LLM-driven protagonists, the
  crowd is deterministic texture.
- **Fix — daily call ceiling** (`Config.llm_max_calls_per_day`, default
  200): belt-and-braces hard cap on total Ollama calls per sim-day
  (cognition + dialogue + settlement jobs all count); once hit, every
  further LLM decision that day falls back deterministically until the
  counter resets at day_end. Verified to hard-bound throughput (peak
  never exceeds the cap). Surfaced in `/diagnostics` (`llm_calls_today`,
  `llm_core_cast_current`, etc.).
- New CLI flags `--llm-core-cast-size` and `--llm-max-calls-per-day`
  (both default to their `Config` attributes).

### Changed
- **R3**: finished the `clamp()` migration — every remaining
  `max(lo, min(hi, x))` idiom (25 sites across population/engine/beliefs/
  weather/terrain_evolution/hydrology) now uses `util.clamp`. Proven
  byte-identical by the 7000-tick event-stream hash.

## [0.69.0] — Codebase audit + safe dedup refactor

Full read-through audit for performance/maintainability/features, with
a behavior-preserving bias. Findings and the sequenced plan for the
larger (deferred) refactors are in `docs/REFACTOR-2026-07.md`.

### Changed
- **New `hearthmind/util.py`** (stdlib-only, cycle-safe bottom of the
  dependency graph) consolidating three cross-cutting helpers:
  `clamp(value, low, high)`, and `namespaced_rng`/`namespaced_roll`
  which had been **copy-pasted verbatim** into `agents/population.py`,
  `world/state.py`, and `simulation/engine.py`. Each module keeps its
  historical private `_namespaced_rng`/`_namespaced_roll` name via a
  one-line alias, so no call site changed. Migrated the 5 `clamp`
  sites in `settlement/buildings.py`'s Phase-G/market math.
- **Import hygiene**: removed a dead `import random`
  (`llm/caravan.fallback_caravan`) and the `hashlib`/`random` imports
  left unused in `state.py`/`engine.py` once the RNG helpers moved;
  hoisted two function-local `deque` imports in `population.py` to
  module scope.
- Verified **byte-identical**: a 7000-tick fresh-world run (deterministic
  fallback) produced the same SHA-256 of the entire event stream before
  and after, exercising construction, naming, temperament, and player
  standing; plus a server-CLI boot smoke test.

### Documented (deferred, not done — see docs/REFACTOR-2026-07.md)
- **R1**: split the three oversized modules (`population.py` ~3930,
  `buildings.py` ~2140, `engine.py` ~2090) into packages via **mixins**
  (preserves `self`/`cls`/MRO and every call site), one cohesive
  method-group at a time behind the event-hash equivalence check.
- **R2**: collapse `engine.py`'s ~20 near-identical `_maybe_schedule_*`
  methods into a declarative job registry.
- **R3**: finish the `clamp` migration (25+ remaining sites).
- **R4**: numpy grid-pass vectorization — **explicitly declined** (tick
  loop has ~250× headroom; would add a heavy dependency for <1% of an
  unspent budget), consistent with CLAUDE.md's escalation order.

## [0.68.0] — Four live-report bug fixes: births, naming, disease, mountain geography

Investigated and fixed four symptoms from a real year-2/tick-15000 run.

### Fixed
- **No births by tick 15000**: `CAMP_TOLERANCE` (12) was exactly equal
  to `Config.initial_population` (12), and founders start at
  `age_ticks=0` — so `carrying_capacity`'s `labor_term` starts
  *negative* (immature population) and stays thin for a long stretch
  after maturity too, leaving zero real reproduction headroom until a
  HUT is actually built. Raised `CAMP_TOLERANCE` to 18 so a founding
  party has genuine growth room independent of the multiplier's early
  swings. Verified via a 20,000-tick engine run: 216 births, population
  12 -> 227.
- **Village never gets its LLM-proposed name**: `_maybe_schedule_naming`
  keyed entirely off `not stl.name`, which only ever fires the one tick
  the deterministic placeholder is first assigned — on any resume,
  `name` is already truthy so the background LLM naming job silently
  never (re)schedules, and the settlement is stuck on its placeholder
  forever. Added a persisted `Settlement.llm_named` flag, set true only
  when the naming job actually resolves (real name or fallback); the
  engine now schedules the job whenever a settlement has a placeholder
  it hasn't gotten a real name for yet, not just the tick it was set.
- **Disease effectively invisible early game**: fully real and
  surfaced (`sick_count`/`immune_count`, sick/immune UI rings) but
  `OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK * population` gives an
  expected first case around tick ~830,000 (~24 sim-years) at a
  founding population of 12 — calibrated for a large, mature
  settlement, reading as "disease doesn't exist" for the entire early
  game. Added `OUTBREAK_MIN_CHANCE_PER_TICK` floor so a small
  settlement's first case lands within roughly a sim-year or two;
  larger/crowded settlements are unaffected (their population-scaled
  chance already exceeds the floor).
- **Geography never interacted with technology**: MOUNTAIN terrain was
  a hard, unconditional barrier to movement and construction at every
  era, including `digital` — `tech_level` only ever gated building
  *kinds*, never terrain passability. Added
  `ERA_UNLOCKS_MOUNTAIN_BUILDING` (same `electrical`-onward gate as
  FACTORY/POWER_PLANT, representing real mining/tunneling tech):
  `_choose_build_site` now includes MOUNTAIN tiles once a settlement's
  era qualifies, and `_dispatch_movement` threads a `mountain_unlocked`
  flag into that settlement's own goal/journey pathing
  (`_step_toward`/`_bfs_step`) so agents can actually walk onto and
  build on mountains once unlocked. SNOWCAP stays impassable at every
  era. Verified via direct unit checks (`_is_walkable`,
  `_choose_build_site`) since a fresh world doesn't reach `electrical`
  within a practical verification run.

## [0.67.0] — Cross-settlement relationships, cross-settlement omens, dialogue turn-taking, perf pass

Builds the two items deferred from v0.66.0, plus two direct follow-up
requests: dialogue turns reading as disconnected, and a performance
pass grounded in real profiling data.

### Added
- **Cross-settlement relationships**: `Settlement.relations` (id ->
  affinity, -1..1), seeded warm at fission (`seed_relation`, colored by
  the origin settlement's temperament), mean-reverting monthly
  (`tick_relation`, same shape as `temperament`). Two real mechanical
  hooks: a small market-price nudge from a settlement's average
  standing with its sisters (`market_relation_factor`, +-10% at fully
  warm/cold, wired into `tick_market_prices`), and a nudge from
  cross-settlement dialogue sentiment (colocated pairs from different
  settlements are rare but real on the shared map — each exchange
  nudges both settlements' mutual relation the same way it nudges the
  two agents' personal one). Surfaced in `summary()`/`to_dict()`.
- **Cross-settlement omens**: `omens.CROSS_SETTLEMENT_OMEN_CHANCE` —
  when authoring a new omen, a 30% chance blends in a past omen from a
  *different* named settlement's own history into the existing "echo
  of something noticed before" pool, using the exact same ambiguous
  framing as an in-settlement echo. No settlement attribution is ever
  surfaced in the prompt or output — a shared phrase turning up in two
  villages' histories is left for a player to notice, never narrated
  as a connection. Small, incremental, same Phase G ambiguity
  discipline as everything else in this system.

### Fixed
- **Dialogue turns could read as disconnected.** `llm/dialogue.py`'s
  `SYSTEM_PROMPT` asked for two lines but never explicitly required
  `line_b` to respond to `line_a` — a weaker model could (and did)
  produce two independently-plausible statements instead of a real
  back-and-forth. Added an explicit instruction: line_b must directly
  respond to, react to, or answer what line_a just said.

### Performance
- Profiled a 60-agent/64x64/2000-tick run (cProfile): `Population.
  _nearest_resource` (the FORAGE-goal targeting function touched in
  v0.65.2's fishing fix) was the single largest self-time hotspot —
  it scanned every resource node on the map (~800 on this map) per
  call regardless of the agent's actual `FORAGE_SEARCH_RADIUS`. Now
  scans the bounded (2*radius+1)^2 box directly via dict lookups —
  fixed cost regardless of map size/node density, ~7x less self-time
  in the profiled run (1.554s -> 0.219s). Same behavior, same tie-
  break, just not scanning tiles that were always going to be
  filtered out. Clean (unprofiled) throughput: 1.42ms/tick at
  population 60 on a 64x64 map — still ~700x headroom against the
  1000ms/tick budget; this was a real measured hotspot worth fixing,
  not evidence the engine was ever close to CPU-bound.

## [0.66.0] — Dialogue grounding, fishing visibility, boats, personality-steered profession

Direct response to a numbered feedback list: dialogue quality, fishing
visibility, boats/rafts, personality steering profession. (Cross-
settlement relationships and further supernatural-emergence work were
also requested — scoped out of this batch, see docs/DECISIONS.md for
why and what a v1 of each would involve.)

### Fixed
- **NPC-NPC dialogue never used `agent.memories` or current activity.**
  `llm/dialogue.py`'s prompt grounded conversations in hunger/energy/
  weather/relationship/culture/beliefs/personality, but never what
  either speaker was actually doing (`agent.goal`) or had recently
  experienced (`agent.memories` — a death, a bond, a rumor) — the one
  concrete thing that would make a line feel like it was about *this*
  world instead of generic small talk. cognition.py already fed
  memories into goal-setting; dialogue now does the same, plus a
  SYSTEM_PROMPT instruction to prefer that grounding over small talk.
- **Post-fission dialogue used the wrong settlement.** `engine.py`'s
  `_schedule_due_dialogue` unconditionally read `world.settlement`
  (the founding settlement) for name/tradition/beliefs context, even
  for a colocated pair who'd fissioned to settlement #2 or #3 — now
  resolves each pair's actual home settlement.
- **`inspect_world.py` never printed a fish count** (see v0.65.2) —
  carried forward, also added a fish-caught tally (below).

### Added
- **Fishing visibility**: `Settlement.fish_caught`, a persistent count
  of meals relieved from a FISH resource node, surfaced in the UI's
  Wild Resources tile and `inspect_world`'s Resources line.
- **Boats/rafts**: `VehicleKind.RAFT` — same settlement-wide passive-
  bonus shape as CART (not a personally-claimed vehicle), each ready
  raft adds 30% to a fish catch's hunger relief (cap 2, +60%). Only
  enters the vehicle-founding roll at a build site actually adjacent to
  water (`is_adjacent_to_water`), costs 5.0 materials, wears with use
  like a cart. Rendered on the map as a teal square (carts are amber).
  Does not grant water crossing/pathing — a concrete "make fishing an
  investment" mechanic, not a transport mechanic.
- **Personality visibly steers profession.** `llm/cognition.py`'s
  `fallback_goal` (the deterministic path used whenever the LLM is
  disabled/unreachable/backpressured — a meaningful fraction of ticks
  by design) previously split content agents purely by `agent_id % 3`,
  completely ignoring their trait vector. A standout `TRAIT_AMBITION`
  now leans GATHER, a standout `TRAIT_SOCIABILITY` leans SOCIALIZE,
  overriding the id-based split; neutral-personality agents (the common
  case) are unaffected. The live-LLM `SYSTEM_PROMPT` also now
  explicitly asks the model to let personality break ties the same way.

### Investigated, no code change
- **Era progression (industrial → modern)**: re-confirmed no gating
  bug. At default pacing, reaching `modern` (tech_level 7) is ~8.75
  in-game years — roughly 85 real hours of continuous uptime at
  `tick_seconds=1.0` — a genuine long-run milestone per the v0.44.0
  tuning pass, not evidence of something stuck. One real caveat: on a
  world that has fissioned into multiple named settlements, each
  settlement's invention roll is diluted 1/N by the round-robin
  `_job_target()` design (deliberate — keeps total LLM volume flat).
  See docs/DECISIONS.md for the full arithmetic.
- **Best model at a 6GB ceiling, considering dialogue quality**: see
  README's memory-tuning section — recommendation is unchanged from
  `qwen3:4b-instruct` (v0.65.2) but with the 6GB headroom explicitly
  reasoned through, since dialogue quality scales with model size more
  than any other single lever here.

## [0.65.2] — Fishing fix, model default swap, llama.cpp evaluation

Direct response to a live-hardware report: "why are npcs not fishing,"
a request to push CPU/RAM tuning further, "move to llama.cpp if
required," and a report that `qwen3:4b-instruct` uses under 4.5GB with
no swapping versus `qwen3.5:2b`.

### Fixed
- **NPCs weren't visibly fishing.** The mechanic was real (`FISH`
  resource nodes, richer/faster-relieving than a bush) but
  `Population._nearest_resource` treated FOOD and FISH nodes
  identically and returned whichever was physically closest. FISH nodes
  only roll on the thin ring of water-adjacent tiles, so they almost
  never won a raw-distance tie-break against the far more numerous FOOD
  nodes scattered across every forest/grassland/hills tile — fishing
  only ever happened by incidental colocation. Now a FISH node within
  `FORAGE_SEARCH_RADIUS` is always preferred over a farther-but-closer
  FOOD node, matching the resource-variety pass's own stated intent
  that fish is the deliberately preferred catch.
- **`inspect_world.py` never showed a fish count.** Its `Resources:`
  line printed bushes/mines only — a leftover from before the fishing
  pass added `fish_nodes`/`fish_avg_amount` to `ResourceGrid.summary()`.
  A live smoke-tested world had 80 fishing spots that the project's own
  primary CLI verification tool never surfaced. Now prints them.

### Changed
- **Default model: `qwen3.5:2b` → `qwen3:4b-instruct`.** Live report:
  `qwen3.5:2b` (never an officially released Qwen tag) showed
  memory-leak-like growth/swapping on the user's 8GB machine, while the
  larger, official `qwen3:4b-instruct` stayed under 4.5GB with no
  swapping. `-instruct` is non-thinking by design; the existing
  `"think": false` handling in `OllamaClient` stays as a defensive
  no-op for it. README/CLAUDE.md/docs/DECISIONS.md updated throughout
  (pull command, size-up/size-down guidance, memory budget numbers);
  `qwen3.5:2b` is now explicitly flagged as not recommended.

### Evaluated (no change)
- **llama.cpp migration**: considered per the report that "the ollama
  process is taking the most memory," and declined for now. Ollama's
  own runner already is llama.cpp — the memory is model weights + KV
  cache either way, not Ollama-specific overhead (which is a real but
  small ~100-300MB Go-daemon/blob-store cost). A migration would trade
  a real engineering cost (rewriting `OllamaClient`, losing Ollama's
  model management/`keep_alive`) for a saving already available via
  already-documented server-side levers plus the model switch above.
  See docs/DECISIONS.md for the full reasoning and the revisit
  condition.

## [0.65.1] — Maximize CPU, minimize memory: an unused Ollama thread lever

Direct response to "maximize cpu usage and minimize memory usage."
The tick loop itself has no CPU lever to pull (already ~1ms against a
1000ms budget); the free trade was on the Ollama side.

### Added
- **`Config.llm_num_thread` / `--llm-num-thread`**: how many CPU
  threads Ollama devotes to a single inference call, sent as the
  request's `num_thread` option (`OllamaClient`, `SimulationEngine`,
  and the one-time genesis call in `server.py` all wired). Defaults to
  `os.cpu_count()` at the CLI (every core on the machine) — `Config`'s
  own default stays `None` (defer to Ollama), matching the "don't
  touch it without reason" convention `num_gpu` already set. This is
  distinct from `llm_max_concurrent`: more threads per call finishes
  that call faster, shrinking the window its KV-cache allocation holds
  memory, without adding a second call's worth of concurrent KV cache
  the way raising concurrency would — CPU utilization goes up, peak
  memory does not. Pass `--llm-num-thread 0` to opt back out.

### Verification
Confirmed `num_thread` reaches the actual Ollama request payload via a
mocked `urlopen` call; `--help` shows the CLI default resolving to this
machine's real core count (4); full compile check.

## [0.65.0] — Multiple named settlements, agent-pathed construction, true replay, memory-spike fix

The three remaining "Known architectural gaps" from CLAUDE.md, plus a
direct response to the live "swap pressure reduced but memory still
very high" report.

### Fixed — memory
- **Staggered the monthly LLM job cluster across days of the month**
  (`MONTHLY_JOB_DAY`). Every monthly job — chronicle, festival,
  caravan, town brain, settlement/personal/institution beliefs, omens,
  guild founding, geography, and the new fission job — used to
  schedule on the same `month_end` tick: up to ~10 back-to-back Ollama
  calls twelve times a year (a minute-plus of continuous inference at
  concurrency 2), the exact "sparse but sudden" swap-spike shape that
  every steady-state leak audit kept coming back clean against. Same
  per-month volume and cadence, now at most one routine settlement job
  per day. Deterministic month-end work (market prices, temperament)
  stays on `month_end`; seasonal/yearly jobs keep their boundaries.
- **`GET /diagnostics` now attributes memory live** (`system_memory`):
  this process's RSS/swap, every Ollama process's RSS/swap, and
  system-wide MemAvailable/swap from /proc — so the next pressure
  report says who owns the memory instead of requiring another
  guess-and-fix cycle.
- **README: remaining Ollama levers documented** —
  `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (halves KV
  cache), `OLLAMA_NUM_PARALLEL=1` as a memory-vs-burst-latency trade
  that keeps the client concurrency floor of 2, and the model
  size-down path (`qwen3:1.7b`, same family) with the explicit
  diagnose-first workflow. The default model is unchanged.

### Added — multiple named settlements (the last big architectural gap)
- **Settlement fission**: a crowded settlement (population over housing,
  ≥ `FISSION_MIN_POPULATION`) with an ambitious leader triggers a real
  LLM decision (`llm/fission.py` — declining is a valid outcome). On
  yes, a founding party (leader's family first, then close bonds, 4-8
  people, mother settlement keeps ≥ 16) hauls a 40% materials grant and
  *walks* (`Agent.travel_target`) to a distant food-scored, reachable
  site — then first hut, placeholder name, background LLM naming, and
  everything else happens through the same machinery as the founding
  settlement. Capped at `MAX_SETTLEMENTS` (3) with a ~208-sim-day
  cooldown.
- **Per-community ownership on one shared physical world**: agents have
  a home settlement (`Agent.settlement_id`); granaries/stockpiles/
  rations/priorities/carrying-capacity/councils/guilds/families resolve
  per home, while movement, colocation, trade, dialogue, teaching, and
  disease stay spatial — visitors genuinely help build and shelter, and
  a child is born into (and gated by) its parents' community.
- **Round-robin monthly LLM jobs** (`_job_target`): each settlement
  takes turns owning the month's chronicle/town-brain/beliefs/omen/
  festival/caravan/tradition/invention/guild/institution jobs — total
  LLM volume stays flat no matter how many settlements exist.
- **Disasters and terrain evolution see every settlement** (floods,
  wildfire, storms damage any community's structures; reclamation and
  climate drift respect them all).
- **UI**: floating name labels at each settlement's center (live map,
  minimap source, and replay frames), plus a settlement switcher above
  the details stats when more than one community exists. Whispers and
  the documentary stay with the founding settlement.
- **Snapshots**: `World.to_dict` writes a `settlements` list;
  pre-multi-settlement snapshots load as the founding settlement,
  unchanged.

### Added — where to build, fully agent-pathed
- Founders now survey `BUILD_SITE_SEARCH_RADIUS` and stake out the
  best-scoring nearby tile (road/resource/water adjacency minus a
  distance penalty) instead of always building underfoot; the chance
  multipliers read the *chosen* site so the two "where does the town
  grow" mechanisms agree. Under-construction sites join damaged
  buildings as WANDER-goal work attractors, so builders walk to the
  staked site.
- **Bounded BFS pathing for journeys**: a fission party whose greedy
  step is blocked by a concave water pocket takes a real
  shortest-path step instead of oscillating forever; unreachable
  targets abandon the journey, and the fission site chooser only
  considers land actually reachable from the leader.

### Added — true frame-by-frame replay
- The Timeline panel's ▶ replay button plays the stored snapshots in
  order over timeline v2's real past maps (terrain as it was,
  buildings/agents/farms/graves/name labels), at 1/2/4 frames per
  second with prefetch; `GET /snapshots/{tick}` keeps a small FIFO
  cache of built frames so scrubbing replayed ground is instant.
  Hand-scrubbing or closing the timeline stops the replay.

### Verification
39-check ad-hoc script (staggered days actually fire on their assigned
distinct days; memory probe; site choice + work attractor + journey
override incl. blocked/unreachable cases; forced fission end to end —
party departs, walks, arrives, builds, and the daughter settlement
earns its own name in a real engine run; serialization round-trip +
legacy snapshot load; replay frames served with labels and cache), plus
CLI fresh/resume smoke tests and 1.2 ms/tick at 64x64 (budget 1000 ms).

## [0.64.0] — The whole audit backlog: seven emergence systems + six UI features

Explicit user directive: take the v0.63.0 audit's entire suggested
backlog and "pick them all one by one and finish it." Every item below
is mechanically real per the standing workflow rules. Also per user
decision: the unused `tests/` directory is deleted outright.

### Added — emergence

- **Institutions Stage 3 — own belief formation**: one institution with
  living members per month now *forms/revises its own theory*
  (`beliefs.INSTITUTION_SYSTEM_PROMPT`/`apply_institution_belief`,
  `origin: "own"` marker) — no longer only mirrored copies of
  settlement beliefs. Group theories may contradict the village's; the
  existing consumers (council -> town-brain prompt, family -> dialogue)
  read them from the same `Institution.beliefs` store.
- **Deliberate institution founding**: an ambitious master can push a
  guild into existence at 2 masters — below the automatic 3 — via a
  monthly LLM decision (`llm/founding.py`, fallback keyed on the
  founder's own ambition). The first institution-formation path that
  runs through an agent's decision rather than a census threshold.
- **LLM-mediated dispute resolution**: a mutually-festered pair
  (relationship ≤ -0.6 both ways) gets a rare resolution moment
  (`llm/dispute.py`): reconcile / hardened feud / council ruling (only
  if a council exists), each with real effects — relationships/trust
  move, memories are left, traits nudge (`Population.apply_dispute`,
  per-pair cooldown ~31 sim-days).
- **Named geography**: once the settlement is named, its river and each
  lake earn permanent LLM-authored names, one per month
  (`llm/geography.py`, `Settlement.place_names`) — consumed by the
  chronicle prompt, the lake summary/`river_name`, and the UI's
  Geography tile.
- **Written artifacts**: a dying villager with a full-enough life
  (≥4 memories) leaves a letter — existence decided synchronously at
  death, text LLM-authored from their own memories/belief
  (`llm/artifacts.py`, `Settlement.records`, capped 40). Records feed
  the yearly documentary prompt ("words the departed left behind"),
  the first grieving relative keeps the letter as a memory, and a
  Written Records panel shows them in the UI.
- **Seasonal wildlife migration**: grazer reproduction now follows the
  calendar (winter 0.3x, spring 1.3x), cold-season herds can drift off
  the map entirely (`wildlife_migrated` events), and the spring
  recolonization surge (3x) brings them back — a yearly
  departure-and-return cycle, not a static backdrop.
- **Multi-good market pricing**: while a MARKET stands, monthly
  per-good price multipliers derive from real scarcity
  (`tick_market_prices`, 0.5x–2.0x, smoothed): overflow food/materials
  sales earn the current price and emergency famine rations cost it.
  No market -> flat 1.0x (no price discovery).

### Added — UI

- **Graveyard/memorials**: every death leaves a small grey cross on the
  map where it happened (`Settlement.memorials`, capped 150, persisted
  and broadcast) — hover a tile to read who rests there; the tile
  inspector lists name/cause/tick.
- **Building & tile click-inspector**: parity with the NPC inspector —
  click a building (kind, stage, condition, owner by name, stores,
  who's inside) or any bare tile (biome, resource node fullness, field
  state, path wear, graves).
- **Event-log filter chips**: all/people/town/nature/mind, display-only
  filtering over the existing categorized log.
- **Zoom/pan + minimap**: wheel-zoom around the cursor (1x–8x), drag to
  pan, and a corner minimap with a viewport rectangle (click to jump)
  that appears once zoomed — at 1x everything renders exactly as
  before.
- **Follow-agent camera + movement trails**: a "follow on map" button
  in the NPC inspector keeps that agent centered (auto-zooms to 3x)
  and draws their recent path as a fading trail; manual pan or their
  death releases the camera.
- **Timeline v2 — render the past map**: scrubbing the timeline now
  *shows* the world as it was — full past terrain (floods/
  deforestation/climate drift included, since snapshots carry
  terrain), buildings, agents, farms, and memorials — with a
  "return to live" banner. `GET /snapshots/{tick}` gained an on-demand
  `map` payload.

### Removed / decided

- `tests/` deleted entirely (explicit user decision; the suite was
  already unused per the standing workflow rule).
- WebSocket delta payloads: deliberately NOT implemented — the backlog
  item's own condition ("only if bandwidth ever measured as a
  problem") remains unmet.

## [0.63.0] — Full audit: six bug fixes, idle-CPU/memory optimizations, docs cleanup

An extensive whole-codebase audit (bugs, memory, performance, long-term
stability), with every confirmed finding fixed in the same batch. Full
accounting in docs/DECISIONS.md, "full audit pass."

### Fixed

- **`hearthmind-server` ran double the tuned LLM concurrency by
  default**: the CLI's `--llm-max-concurrent` default was a hardcoded
  `4`, never updated when `Config.llm_max_concurrent` was deliberately
  tuned down to `2` for 8GB-memory headroom (v0.43.0/v0.44.0) — so any
  plain launch without that flag ran twice the intended simultaneous
  Ollama calls, a direct contributor to live swap pressure. Every CLI
  default now references its `Config` attribute so the two can never
  drift again.
- **`phase_g_intensity` (and every other runtime config field) was
  silently reset to its default on world resume**: `World.from_dict`
  rebuilt `world.config` from a hand-picked field list that omitted the
  runtime section, and the engine reads `world.config.phase_g_intensity`
  — so the documented Phase G off-switch only ever worked on a
  brand-new world. `from_dict` now starts from the runtime config and
  overlays only the snapshot's creation-only fields.
- **Floods never actually submerged the tile**: `tick_flood` recorded
  the "original biome" at onset and restored it on recede, but the
  submerge itself (converting the tile to shallow water) was missing —
  the restore was a no-op and a flood was invisible on the map and to
  every water-biome consumer. Onset now converts the tile to
  `SHALLOW_WATER`; recede restores the recorded original, as always
  intended.
- **Wildfires burned an empty decoy `FarmGrid()`**: `tick_wildfire`'s
  spread path passed a fresh empty grid to the damage helper instead of
  the world's farms, so crops could never burn. The real `FarmGrid` is
  now threaded through.
- **Starvation deaths of fragile agents were logged as old age**: death
  *eligibility* used the resilience-adjusted starvation threshold but
  death *classification* compared against the raw base constant, so a
  negative-resilience agent dying early of starvation fell through to
  the old-age arm (miscounted, and narrated as a young agent dying of
  old age). Classification now uses the same adjusted threshold.
- **Inherited medicine ignored `MEDICINE_CAPACITY`**: H7's inheritance
  capped food/tools but not medicine, letting an heir exceed the
  personal cap.

### Changed (performance / memory)

- **Idle broadcast skipping**: with zero browser clients connected, the
  full per-tick payload (`to_dict()` of every agent/building/farm/
  resource/wildlife entity plus three summary passes) was still built
  every tick purely to keep `GET /state` fresh — the largest recurring
  per-tick cost on an always-running, mostly-unobserved server. It is
  now rebuilt every 10th tick while no clients are connected (events
  from skipped ticks are buffered, bounded, and flushed into the next
  payload); per-tick broadcasting resumes automatically the moment a
  client connects.
- **`biome_counts` cached**: `World.summary()` scanned every tile
  (16,384 on a 128x128 world) every tick for counts that only change on
  the rare terrain-changing events — now cached with the same
  invalidation signal the water-tile cache already uses.
- **Teaching scan de-quadratic'd**: `_maybe_teach_skills` ran an
  `any()` over the full stored institutions list (capped at 300) for
  every colocated pair every tick; a one-pass membership index now
  answers the same shared-family/council/guild questions.
- **Predator-attack early-out**: `_maybe_predator_attack` called the
  O(herds) `wildlife.at()` for every awake agent every tick; it now
  early-outs against the tick's precomputed predator-tile set.
- **SQLite `synchronous=NORMAL`** (the documented WAL pairing): removes
  one fsync per tick-commit; a crash can lose at most the final
  not-yet-checkpointed commits, never corrupt the database.

### Removed / cleaned

- Stale local caches (`.pytest_cache/`, `__pycache__/`) deleted;
  `.gitignore` now covers `.pytest_cache/` and `*.sqlite3` sidecars.
- `README.md` refreshed (stale milestone list, stale flag defaults,
  stale "no intervention endpoints yet" claims, unittest-first testing
  section replaced with the project's actual verification workflow).
- `docs/TESTING.md` rewritten to match the standing workflow rule
  (automated suite not run; verification = ad-hoc scripts + CLI smoke
  tests + the user's live diagnostics).
- `CLAUDE.md` consolidated: superseded per-version narratives compressed
  into a diagnostic-history index pointing at docs/DECISIONS.md; all
  standing rules/directives kept; new audit-backlog section added.

## [0.62.0] — Continue expanding, round three: SKILL_MEDICINE, guild belief mirroring, chronicle variety, disease UI

Third follow-up batch, scoped after an Explore-agent audit of skills,
belief mirroring, LLM fallback pools, and the frontend's disease-state
rendering, to find genuine unimplemented next steps.

### Added

- **`SKILL_MEDICINE`**: a third skill axis alongside `SKILL_FARMING`/
  `SKILL_CONSTRUCTION`, closing the one crafted good (medicine) that
  previously had no personal-skill hook. Gained by a hospital worker's
  own practice while crafting (`_maybe_craft_medicine`); boosts their
  own crafted yield up to +30% at full mastery
  (`SKILL_MEDICINE_YIELD_BONUS`). Wired into every place the other two
  skills already reach: colocated teaching, GUILD formation (a third
  possible guild, one per mastered trade), the settlement's
  `carrying_capacity` knowledge term, and the invention-chance
  aggregate skill nudge — introduced and fully consumed in the same
  batch, per the project's standing "no write-only mechanics" rule.
  `Population.summary()` gained `avg_medicine_skill`.
- **GUILD belief mirroring (`sync_guild_beliefs`)**: closes the one
  institution kind FAMILY/COUNCIL's belief-mirroring pattern never
  covered — a settlement belief whose text names a guild's trade (e.g.
  "farming") is now mirrored onto that GUILD's own `Institution.
  beliefs`, the same "mirroring, not independent formation" mechanism
  the other two kinds already use. Independent institution-level belief
  *formation* (the roadmap's still-open "Stage 3") remains a distinct,
  larger future step.
- **Chronicle fallback template variety**: `chronicle.fallback_summary`
  — the season-end summary fallback, arguably the most frequently-fired
  narrative fallback in the project — was still a single hardcoded
  line with zero variation, unlike every other narrative fallback
  touched by the last two variety passes. Now cycles a small 3-entry
  pool by seed, same shape as disaster narration's own template
  variety (no LLM call added).
- **Sick/immune status rendering**: `sick_ticks`/`immune_ticks` were
  already broadcast per-agent (disease v2, v0.59.0) but never rendered
  anywhere. Map agent dots now show a magenta ring while sick, a faint
  green ring while recently immune; the NPC inspector's Vitals row
  gained a plain-language Health line ("sick, N ticks" / "recently
  immune, N ticks" / "healthy").

## [0.61.0] — Continue expanding: TRAIT_OPENNESS, family-tree edges, disaster variety, NPC institutions

Second follow-up batch, scoped after an Explore-agent audit of trait
axes, the H4 supply chain, the relationship graph, and disaster
narration to find genuine unimplemented next steps rather than
re-covering ground already shipped.

### Added

- **`TRAIT_OPENNESS` (H6 v4)**: a fourth personality axis, closing the
  "identity/values remain open" note the roadmap has carried since
  ambition (the third axis) shipped. -1 = rooted in the village's own
  ways, +1 = drawn to the unfamiliar. Nudged up on direct outside
  contact — every listener a caravan's rumor reaches
  (`Population.spread_rumor`) — and consumed by `_maybe_welcome_
  migrant`'s roll chance (a village whose survivors lean open welcomes
  a stranger more readily). Included in the monthly trait random walk,
  `Population.summary()`'s `avg_openness`, `describe_traits`'
  cognition/dialogue prompt text, and the browser stats legend/NPC
  inspector.
- **Family-tree edges in the relationship graph**: the browser's
  per-tick payload now broadcasts full `Settlement.institutions`
  (previously only counts-only via `summary()`). The relationship
  graph draws a distinct dashed-gold line for any pair sharing a
  living FAMILY institution — kinship, shown regardless of current
  affinity (even below the graph's normal `REL_MIN_AFFINITY` cutoff) —
  distinct from the existing green/red fondness-based edges. Closes an
  item flagged (never built) since the original relationship-graph
  work.
- **NPC inspector shows institution membership**: a new "Institutions"
  section (family members by name, council seat, guild trade) using
  the same broadcast data as the family-tree edges above.
- **Disaster narration variety**: flood/wildfire onset, storm damage,
  heatwave onset, and frost damage each gained 2 more deterministic
  template variants, cycled by the tick's own RNG — no new LLM call
  (the module's standing "no new LLM call is added here" decision is
  unchanged; this is pure template variety, the same "cycle a small
  fixed pool" shape the LLM fallback pools use, just without ever
  touching an LLM).

Verified: direct checks that `spread_rumor` nudges every listener's
openness and that `_maybe_welcome_migrant`'s success rate measurably
rises with average population openness; a 20,000-tick real-engine run
confirming family institutions form and their broadcast-payload shape
(`kind`, `member_agent_ids`) matches what the frontend code expects; a
live `WorldBroadcaster` check confirming `institutions` reaches the
per-tick payload; a sampling check confirming all disaster template
variants get used; `node -c` on app.js; a 5,000-tick full-engine smoke
run (0.80ms/tick, no regression).

## [0.60.0] — Continue expanding: GUILD institutions, rumor instrumentation, content variety, NPC personality

Explicit user follow-up ("continue expanding") to v0.59.0's four-front
batch — one more substantial item per category.

### Added

- **`InstitutionKind.GUILD`** (H3 v4): a third, trade-specific
  institution kind — one instance per skill (`SKILL_FARMING`/
  `SKILL_CONSTRUCTION`), formed once at least
  `GUILD_FORMATION_MASTER_COUNT` (3) living agents reach
  `GUILD_SKILL_MASTERY_THRESHOLD` (0.6) in that trade
  (`Population._maybe_form_guild`). Membership grows (never shrinks
  back down, matches FAMILY/COUNCIL's "outlives its members" shape) as
  more agents master the trade (`_maybe_refresh_guild`). Shared guild
  membership for the specific skill being taught gives
  `GUILD_TEACHING_BONUS_MULTIPLIER` (1.6x) in `_maybe_teach_skills`,
  stacking with the existing trade-agnostic FAMILY/COUNCIL bonus
  (1.4x). First real use of `Institution.name` (previously always
  empty). `Settlement.summary()`'s `institutions` gained `guilds` (a
  list of which trades currently have one).
- **Rumor-epidemiology instrumentation**: `Population.rumors_seeded_
  total`/`rumor_listener_exposures_total`, incremented at both real
  rumor-entry points (`spread_rumor`'s caravan-news seeding,
  `apply_dialogue`'s LLM/fallback-generated rumors) — closes the
  long-flagged "rumor-epidemiology instrumentation" gap from the July
  2026 architecture review with real counters on the *existing*
  gossip/trust-contagion machinery, not a new propagation mechanic.
  Surfaced in `Population.summary()`.
- **Content variety**: two-three more fallback-pool entries each to
  `llm/festival.py`, `llm/invention.py`, `llm/culture.py` (tradition),
  and `llm/dialogue.py`'s three sentiment pools.
- **NPC inspector shows personality and skills**: the browser's
  mind-first NPC inspector modal (click an agent) gained "Personality"
  (resilience/sociability/ambition, with a plain-language "notably
  high/low/unremarkable" reading) and "Skills" sections, between
  memories and vitals — the data (`Agent.traits`/`skills`) was already
  in the per-tick payload but never rendered per-agent.

Verified: direct unit checks for guild formation/idempotence/refresh,
a statistical check of the teaching-bonus ratio (measured 1.57x vs.
expected 1.6x across 4,000 trials), a real-engine 50-tick run
confirming guild formation fires inside the actual tick loop (not just
the isolated method) with a full to_dict/from_dict round-trip, direct
checks of both rumor counters' increment/no-increment paths plus
serialization round-trip, a live FastAPI route check confirming the
new fields reach `/snapshots/{tick}`, `node -c` syntax check on
app.js, and a 5,000-tick full-engine smoke run (0.91ms/tick, no
regression).

## [0.59.0] — "Expand all features": disease v2, where-to-build, MARKET, scrub-through-time

Explicit user directive to expand across four fronts at once: deepen
existing systems, close a remaining roadmap gap, add content variety,
and push Observatory UI depth further.

### Added

- **Disease v2: temporary post-recovery immunity.** `Agent.immune_
  ticks` (new field), set to `IMMUNITY_DURATION_TICKS` (400, half
  `SICKNESS_DURATION_TICKS`) on recovery, decayed every tick regardless
  of sick state. While immune, an agent can neither become a fresh
  outbreak's index case (`Population._maybe_outbreak`) nor catch the
  illness from a colocated carrier (`_tick_disease`) — real but
  temporary resistance, not lifelong immunity. `Population.summary()`
  gained `immune_count`. Closes v1's explicitly-flagged "no immunity/
  reinfection modeling... extend later if wanted."
- **Where-to-build: resource-proximity steering.** Second, independent
  "where to build" factor alongside the existing road-adjacency
  multiplier: a candidate construction tile within
  `SETTLE_RESOURCE_SEARCH_RADIUS` of a still-productive resource node,
  or adjacent to open water, gets `SETTLE_CHANCE_RESOURCE_ADJACENCY_
  MULTIPLIER` (1.3x) applied to its settle chance
  (`Population._maybe_start_construction`, new `_near_productive_
  resource` helper).
- **`BuildingKind.MARKET`**, a genuinely bidirectional addition to the
  caravan system: only enters the foundable pool once at least
  `MARKET_CARAVAN_VISIT_REQUIREMENT` (1) caravan has ever reached the
  settlement (new `Settlement.caravans_visited` counter, persistent,
  incremented in `SimulationEngine._maybe_schedule_caravan`); once
  standing, a MARKET measurably improves future caravan trade
  magnitude (`MARKET_CARAVAN_YIELD_MULTIPLIER`, 1.4x) and how often a
  caravan visits at all (`MARKET_CARAVAN_CHANCE_MULTIPLIER`, 1.25x) —
  outside contact justifies the building, and the building draws more
  outside contact. `Settlement.summary()` gained `markets`/
  `caravans_visited`.
- **Content variety**: two more entries each to omens' warm/cold/
  neutral/warm-subject/cold-subject fallback pools, and three more
  entries to caravan's fallback narration pool — more texture when the
  LLM is disabled/unavailable or a call falls back.
- **Scrub-through-time viewer (Observatory UI depth)**: new `GET
  /snapshots` (every tick a snapshot is still on file for, newest-
  first) and `GET /snapshots/{tick}` (a curated, read-only settlement/
  population summary reconstructed from that snapshot — never touches
  or advances the live world) in `interface/app.py`, backed by new
  `persistence.snapshot.list_snapshot_ticks`/`load_snapshot_at_tick`.
  New "🕰 timeline" header toggle opens a slider over the available
  ticks, showing that past moment's era/population/buildings/
  currency-materials/priority. A first, deliberately small step on the
  roadmap's flagged "a true scrub-through-time replay view" gap — not
  a rewind/undo feature, and not a frame-by-frame agent-level replay.

## [0.58.0] — Backpressure gate for settlement-level LLM jobs (sparse-but-sudden swap audit)

### Fixed

- **Unthrottled monthly/seasonal LLM job clusters.** Explicit user
  follow-up: audit for swap spikes that are sparse but sudden, distinct
  from the steady-state leaks already fixed (institutions,
  relationships/trust, culture lists). Traced by instrumenting
  `_schedule_llm_job` (the shared path for chronicle, documentary,
  tradition, invention, festival, caravan, town_brain, beliefs,
  personal_belief, omen — 10 settlement-level jobs) and running the
  real engine through several month/season boundaries: up to 5 of these
  jobs schedule on the *exact same tick* whenever `month_end` and
  `season_end` coincide (which they always do — a season boundary is
  also a month boundary), more when an independently-rolled job
  (festival/caravan/omen) also happens to fire that month. Unlike
  per-agent cognition (`_schedule_due_cognition`) and dialogue
  (`_schedule_due_dialogue`), which both already check
  `CognitionRunner.backlog` against `_backpressure_limit` before
  scheduling, none of the 10 settlement-level jobs ever did — each was
  added independently across many sessions and none looked like a
  backlog risk in isolation, but the cluster is the risk: with
  `llm_max_concurrent` at its permanent floor of 2 and real hardware
  latency ~17-20s/call (per `jobs.py`'s own docstring), an unthrottled
  5-job cluster forces Ollama through a rapid-fire back-to-back burst
  once a month instead of its normal much sparser trickle — a
  plausible source of "sparse but sudden" swap pressure that the
  existing leak audits (which look for monotonic growth) can't surface,
  since nothing here leaks; it's a burst-concurrency gap, not an
  accumulation.
- Fixed with `SimulationEngine._settlement_job_backpressured()`, the
  same `backlog >= _backpressure_limit` check already used by
  cognition/dialogue, called at the top of all 10 schedulers (after
  each job's own cheap gate/RNG-roll checks, so a job that wouldn't
  have fired anyway still short-circuits before the check). Same
  graceful-degradation contract as the existing precedent: a dropped
  job just waits for its next natural cadence (next month/season/year),
  nothing is lost. Caravan's economic exchange (currency/materials) is
  deliberately exempt — it's objective reality, same as a disaster's
  material cost, and stays unconditional; only its LLM/fallback
  *narration* is gated. Town brain's whisper-consumption behavior is
  unaffected: a whisper dropped by this gate stays queued for the next
  month's decision, matching its existing timeout/fallback handling.
  Naming (`_maybe_schedule_naming`) is deliberately NOT gated — it's a
  one-time-per-world event with no periodic retry path, and isn't part
  of the recurring monthly cluster this exists to smooth.
- Verified via a real-engine trace (deterministic fallback, 9,000 ticks,
  seed 7) confirming the pre-fix cluster (5 jobs on one tick), then a
  direct unit check calling all 10 schedulers both with an empty
  backlog (each schedules normally, modulo its own independent
  RNG/gate roll) and with `backlog` forced to `_backpressure_limit`
  (all 10 correctly skip, `calls_dropped_backpressure` increments,
  no exception) — plus naming confirmed still schedules under the same
  saturated condition, proving the exemption is intentional and live.
  A 5,000-tick full-engine smoke run post-fix completed cleanly
  (0.92ms/tick, serialization round-trip OK).

## [0.57.0] — Water/power/irrigation; iGPU offload investigation

### Added

- **Irrigation**: `FarmGrid.tick` now accepts `terrain` and applies
  `IRRIGATION_GROWTH_MULTIPLIER` (1.35x) to any plot adjacent to water
  (`world/resources.is_adjacent_to_water`, made public — the same
  helper H-era fishing already uses for node placement, reused rather
  than a new water-network data structure). Independent lever from
  tool/no-tool yield (which affects `max_yield`, not growth rate).
- **Power**: new `BuildingKind.POWER_PLANT`, foundable from the
  `electrical` era onward (same gate as FACTORY — `_ERA_UNLOCKS_
  ELECTRICAL`, renamed from `_ERA_UNLOCKS_FACTORY` now that both kinds
  share it). While standing, boosts WORKSHOP/FACTORY income settlement-
  wide (`POWER_GRID_INDUSTRY_MULTIPLIER`, 1.3x) and adds a small bonus
  to `Population.carrying_capacity`'s infrastructure term alongside
  road density. This is the "power" half of the integration milestone's
  infrastructure-networks priority — hung off the era system's
  already-named-but-previously-thin `electrical` era rather than
  inventing a parallel utility grid. `Settlement.has_power_plant()`
  is the shared query both consumers use.
- **iGPU offload investigation.** User has an AMD Ryzen 3 8300GE with
  Radeon 740M (gfx1103, RDNA3) — `rocminfo` detects the GPU agent, but
  `ollama ps` showed 100% CPU. Diagnosis and guidance in
  docs/DECISIONS.md (this environment has no access to the user's real
  Ollama/ROCm stack to test directly). New `Config.llm_num_gpu`
  (default `None`, genuinely a no-op until GPU offload is confirmed
  working server-side) sent as `num_gpu` in `OllamaClient`'s options,
  same optional-lever pattern as `num_ctx`/`num_predict`/`use_mmap` —
  ready for the user to set once/if GPU acceleration is confirmed.

## [0.56.0] — Integration milestone: cross-system audit and vertical integration

Explicit user directive: audit every major subsystem for isolation, then
increase real bidirectional interaction between existing systems, prioritizing
dynamic carrying capacity, infrastructure networks, external settlements/trade,
institutional agency, knowledge diffusion, urban growth, and supernatural
propagation. Audit findings and full rationale in docs/DECISIONS.md.

### Added

- **Institutional agency (COUNCIL was the most isolated system in the
  codebase).** `Population._maybe_refresh_council` tops COUNCIL's *living*
  membership back up to `COUNCIL_SIZE` as members die — it previously silently
  decayed into a roster of the dead with no fix. New `llm/beliefs.
  sync_council_beliefs` gives COUNCIL its own accumulated civic theories
  (mirrors `sync_family_beliefs`, triggered by settlement beliefs that don't
  resolve to a person/family). New `Population.council_disposition` feeds
  living members' average traits into `town_brain.build_prompt`'s new
  `council_beliefs` line and `fallback_priority`'s new tie-break (an ambitious
  council leans "growth," a resilience-minded one "defense" — only at the
  bottom of the chain, never overriding an urgent signal), and into
  `carrying_capacity`'s new coordination term.
- **Traits (resilience/sociability/ambition) were write-only.** Now
  consumed: resilience reduces personal disease/predator death chance
  (`TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE`) and stretches/shrinks personal
  starvation tolerance; sociability shifts a giver's own trade-relationship
  threshold (`_trade_relationship_threshold`) and boosts personal
  teaching-roll chance; ambition RNG-weights which eligible founder actually
  claims a new HUT's ownership (`TRAIT_AMBITION_FOUNDER_SELECTION_WEIGHT`).
- **Roads: infrastructure, not decoration.** Road-adjacent tiles are now
  measurably likelier to be settled (`URBAN_GROWTH_ROAD_ADJACENCY_MULTIPLIER`
  — closes the roadmap's "where to build is pure chance" gap); established
  road density feeds `carrying_capacity`'s new infrastructure term; and the
  fraction of the population standing on a road tile nudges disease-outbreak
  chance upward (`OUTBREAK_ROAD_CONTACT_MULTIPLIER`) — the same connectivity
  that helps trade/teaching also spreads a cold, the double-edged framing
  roads already get elsewhere.
- **`Population.carrying_capacity` gained three new terms**: coordination
  (COUNCIL presence/disposition), knowledge (aggregate population skill —
  the same signal `_maybe_schedule_invention` already reads), and
  infrastructure (established roads per capita, saturating). All three are
  the smallest of the composition's weights — real, but never dominant next
  to housing/economy/security/labor.
- **Knowledge diffusion is now institution- and culture-aware.**
  `_maybe_teach_skills`'s roll chance is scaled by both agents' average
  sociability, boosted `INSTITUTION_TEACHING_BONUS_MULTIPLIER`x when teacher
  and learner share a living FAMILY/COUNCIL, and boosted further by a new
  `"knowledge"` tradition influence (`TRADITION_INFLUENCES` — a fourth
  mechanical rider alongside festivity/harvest/resilience, same
  `culture_effect_multiplier` shape).
- **External world contact: caravans** (new `llm/caravan.py`) — a scoped,
  deliberately non-invasive first step toward "external settlements and
  trade." Explicitly *not* the full multi-settlement rearchitecture (still
  flagged in docs/DECISIONS.md as its own dedicated session — touches
  population/engine/every LLM prompt/interface/snapshot schema). A rare
  monthly abstract event (no new map entity, no pathfinding): a real
  currency/materials exchange applied deterministically (objective reality),
  with an LLM-or-fallback description and an optional rumor from outside the
  village folded into a few agents' own memories via new
  `Population.spread_rumor` — propagates through the *existing* gossip/trust
  contagion machinery rather than a bespoke broadcast.
- **Omens can now center on COUNCIL**, alongside the existing per-agent
  subject depth — "the council of elders" as a candidate subject once it
  holds its own beliefs, same permanent ambiguity rule, extended from
  person-depth to institution-depth.
- Stale docstrings in `settlement/institutions.py` (claiming `Institution.
  beliefs` was "deliberately unpopulated" — no longer true since H2 ext's
  `sync_family_beliefs`) corrected to describe actual current behavior.

## [0.55.0] — Force `use_mmap: true` on every Ollama call (swap-pressure follow-up #2)

### Fixed

- **The Ollama server was loading model weights with `--no-mmap`.** A
  live diagnostic on the user's own 8GB machine (`ollama ps` + `ps aux`)
  found the actual `llama-server` runner process resident at 5.1GB RSS
  (74% of system memory) against a model `ollama ps` itself reports as
  only 2.4GB loaded — a ~2.7GB gap, with `--no-mmap` on the runner's
  command line. Without mmap, model weights sit in private anonymous
  memory the kernel can only relieve by writing to swap under pressure;
  with mmap, weight pages are file-backed and the kernel can instead
  just drop and re-read them from disk — categorically cheaper than
  swapping. New `Config.llm_use_mmap = True`, sent as `use_mmap` in
  every request's `options` (same pattern as `llm_num_ctx`/
  `llm_num_predict`), threaded through `OllamaClient.generate_json` and
  both call sites (`SimulationEngine`, `server.py`'s genesis-seed
  call). This project takes an explicit position on every option that
  meaningfully affects memory rather than trusting whatever the server
  happens to default to (or whatever heuristic/env var pushed it toward
  `--no-mmap` here) — same rationale as `num_ctx`/`num_predict`/
  `keep_alive` before it.
- **Not fixed here, and can't be from this repo:** the same diagnostic
  showed `--mmproj` pointing at the same blob hash as `--model` — i.e.
  the loaded model may be carrying a multimodal (vision) projector this
  project never uses (every call here is text-only). That's baked into
  the pulled model artifact/Modelfile on the user's own machine, not
  something any Ollama API request option can strip — would need the
  user to inspect `ollama show qwen3.5:2b --modelfile` or pull a
  text-only tag if one exists.

## [0.54.0] — Fix unbounded `Settlement.institutions` growth (swap-pressure follow-up)

### Fixed

- **`Settlement.institutions` was unbounded.** Live measurement (seed
  42, no cap, in-process engine, LLM disabled) showed FAMILY institution
  count climbing roughly linearly with cumulative births — 191 families
  by tick 24,000, 275 by tick 26,000 — regardless of population, which
  plateaus at the carrying-capacity cap. On a genuinely persistent
  world this is unbounded growth: the same bug class already fixed
  twice before (`relationships`/`trust`, v0.42.0; `traditions`/
  `inventions`/`festivals`, v0.44.1), just never audited when H3/H7/H9
  introduced institutions across this session's own earlier batches.
  New `INSTITUTION_LIST_MAX_STORED = 300` (same magnitude as
  `CULTURE_LIST_MAX_STORED`), enforced by
  `population._prune_extinct_families` — called after every new FAMILY
  institution forms. Unlike traditions/inventions/festivals (pure
  flavor text, safe to hard-truncate to the newest N), a FAMILY
  institution is looked up by living-agent membership (`family_for`,
  inheritance, dialogue), so pruning is extinction-aware: only
  FAMILY institutions with zero living members are eligible for
  removal, oldest-founded first, and only once the stored count exceeds
  the cap — a family with even one living member is never touched, so
  this can never orphan a still-living agent's `family_for` lookup.
  COUNCIL institutions are never pruned (`COUNCIL_SIZE` already keeps
  that kind small). Verified via a direct unit check (tiny synthetic
  cap, confirms oldest-extinct-first eviction and confirms a family
  with a living member always survives regardless of age) and a
  22,000-tick full-`SimulationEngine` integration run (real async tick
  loop, artificially small cap for a fast check) confirming the prune
  path fires exactly when a fully-extinct family exists and never
  touches a family with any living member, plus a serialization
  round-trip check. Note: because eligibility requires a family's
  *every ever-member* to be dead, the cap is a genuine ceiling in the
  long run but engages lazily — a young or fast-growing world won't
  see it trim anything until enough full lineages die out; this bounds
  worst-case growth without ever risking a living agent's `family_for`
  lookup, but is not, by itself, a guarantee of a small list at every
  possible tick count. If swap pressure persists, this list was a
  real but modest-sized leak (a few hundred bytes per institution) —
  Ollama's own server-side memory remains the more likely dominant
  contributor and needs a live diagnostic from the user's actual
  machine to pin down further, since this environment has no real
  Ollama process to measure against.
- Audited every other per-agent/per-settlement collection added or
  extended across the H2/H4/H5/H6/H7/H8/H9 work for the same unbounded-
  growth pattern (`Agent.skills`/`traits`/`beliefs`/`inventory`,
  `Institution.beliefs`, `Settlement.omen_history`/`priority_history`,
  `Agent.trust`/`relationships` death-cleanup): all already correctly
  bounded (fixed key sets, existing caps, or already-pruned on death).
  No further unbounded growth found in this pass.

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
