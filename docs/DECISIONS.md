# Design decisions

A running log of non-obvious choices and why they were made, so future
contributors (including future us) don't relitigate them without context.

**Older entries have been moved to [docs/DECISIONS-ARCHIVE.md](docs/DECISIONS-ARCHIVE.md) to keep this file readable** — full detail preserved there, nothing lost. This file keeps the most recent decisions.

---

## Dialogue grounding fix + settlement-resolution bug (v0.66.0)

User: "the npc-npc conversations are very off." Read `llm/dialogue.py`
end to end: the prompt already grounded an exchange in hunger/energy/
weather/relationship-band/culture/beliefs/personality — a reasonable
amount of context — but never `agent.memories` (the per-agent memory
list that `llm/cognition.py`'s goal-setting prompt already reads from,
see `RECENT_MEMORIES_IN_PROMPT`) and never each speaker's current
`goal` (what they're actually doing right now). Two colocated villagers
could only ever talk about their stats and the weather, never about
anything that had actually happened to either of them — a death, a
bond, a rumor heard, a mastered skill — which reads as generic small
talk ("Quiet day." / "Quiet enough.") regardless of how good the model
is, since the prompt never gave it anything more specific to say.
Fixed: `build_prompt` now includes each speaker's current activity and
most recent memory (`DIALOGUE_MEMORY_IN_PROMPT = 1` — a line only has
room for one concrete thing per speaker), and `SYSTEM_PROMPT` now
explicitly instructs preferring that grounding over small talk.

Separately, and likely compounding on any world that has fissioned
(v0.65.0): `SimulationEngine._schedule_due_dialogue` unconditionally
read `self.world.settlement` (a property returning the *founding*
settlement, `settlements[0]`) for the "They live in {settlement_name}"
culture line and for belief resolution — a colocated pair who'd
fissioned into settlement #2 or #3 would be told they live in the
wrong town, with the wrong settlement's traditions/beliefs feeding
their exchange. Fixed by resolving `agent_a.settlement_id` via
`_settlement_by_id` per pair, same pattern already used for dispute
resolution (`dispute_home = self._settlement_by_id(agent_a.
settlement_id)`).

Not changed: dialogue's fallback pools (`_TENSE_POOL`/`_WARM_POOL`/
`_NEUTRAL_POOL`) or the malformed-response guards in `_is_sane_line` —
those already handle "the model degrades to canned lines" and "the
model leaks/hallucinates" respectively; the actual gap was upstream,
in what the prompt gave a *working* model to talk about.

## Personality visibly steers profession (v0.66.0)

User: NPC personality should visibly steer profession. Traced through
`llm/cognition.py`: the live-LLM prompt already describes personality
in words (`describe_traits`), but `fallback_goal` — the deterministic
path taken whenever the LLM is disabled, unreachable, or backpressured,
which by this project's own liveness design is a real fraction of
ticks, not a rare edge case — split content (not hungry, not tired)
agents purely by `agent_id % 3` among SOCIALIZE/GATHER/WANDER, with
zero reference to `Agent.traits`. An agent's "profession" (which goal
they gravitate to when nothing urgent is happening) was an arbitrary
id-based caste, completely disconnected from the psychology vector H6
built. Fixed: a standout `TRAIT_AMBITION` (>= `TRAIT_NOTABLE_THRESHOLD`)
now leans the fallback toward GATHER ("driven to make something of
themself"), a standout `TRAIT_SOCIABILITY` leans it toward SOCIALIZE,
overriding the id%3 split; a neutral-personality agent (traits near 0,
the common case for an agent whose trait walk hasn't drifted far) gets
the exact old split, so this is additive, not a behavior change for
the average agent. The live-LLM `SYSTEM_PROMPT` also gained one
sentence asking the model to let personality break ties the same way,
closing the gap on the LLM path too (previously personality was
*described* in the prompt but never explicitly tied to the decision).

## Boats/rafts (v0.66.0)

User: add boats/rafts. Scoped deliberately: actual water-crossing
pathing would mean walkable-tile logic (`WALKABLE_BIOMES`, greedy/BFS
movement) learning to traverse `DEEP_WATER`/`SHALLOW_WATER` tiles for
raft-carrying agents specifically — a real pathing-system change, not
a "smallest coherent milestone." Instead followed the existing CART
pattern (settlement-wide passive bonus building, not a personally
claimed vehicle like MOUNT/AUTOMOBILE): `VehicleKind.RAFT`, built at a
water-adjacent site only (mirrors `is_adjacent_to_water`'s gate on FISH
resource nodes), each ready raft adds 30% to a fish catch's hunger
relief up to a cap of 2 (+60% — deliberately lower than CART_BONUS_CAP
of 3, since fishing already gets its own multiplier via
`FISH_HUNGER_RELIEF_MULTIPLIER`). This is the concrete "make fishing a
real investment, not just an incidental catch" lever the fishing-
visibility fix above set up, landed in the same batch since they're the
same feature from two angles. True water transport (a raft that lets
an agent actually cross water tiles, or ferries a fission party faster
than the existing greedy+BFS land journey) is a real follow-up but a
separate, bigger milestone — noted here rather than half-built.

## Era progression re-investigated: multi-settlement dilution (v0.66.0)

User: "no era change from industrial to modern observed yet." Re-read
the v0.44.0 investigation (already-tuned `INVENTION_CHANCE_PER_SEASON`)
and did the arithmetic at current settings: 0.2 chance x 4 seasonal
rolls/year, expected time to `tech_level` 7 (`modern`) is ~8.75
in-game years. At default `sim_minutes_per_tick=15`/`tick_seconds=1.0`
(96 ticks/day, ~35040 ticks/year), that's ~85 real hours of continuous
uptime — several days, not a single sitting. No hidden gating bug
found; `era_for_tech_level`/`ERA_TECH_THRESHOLDS` and the prosperity
gate all behave as designed. This is very plausibly just "hasn't run
long enough yet," matching the v0.44.0 finding almost exactly (it
concluded the same "reads as stuck, isn't" pattern for `electrical`).

One genuine, newly-found compounding factor for a world that HAS
fissioned (v0.65.0): `_maybe_schedule_invention` calls
`settlement = self._job_target()`, the same month-indexed round-robin
used by every settlement-scoped monthly LLM job — with N named
settlements, any given settlement's invention roll (and thus its own
`tech_level`/era progress) only fires on its 1-in-N turn, not every
season. This is the documented, deliberate trade-off `_job_target`'s
own docstring states ("keeps total monthly LLM volume flat no matter
how many settlements exist... with one settlement this is exactly the
old behavior") — not a bug, but worth naming explicitly here since it
directly multiplies the real-world wait for *any single settlement* to
reach `modern`/`digital` by roughly its settlement count. Not changed:
giving every settlement its own independent invention roll would
multiply LLM call volume by settlement count, which the whole
multi-settlement design explicitly ruled out for 8GB-target hardware.
Actionable check for the user: `inspect_world`/`/diagnostics` already
show `tech_level` and `era` live — watch it rise over real hours rather
than assuming a fixed threshold means a fixed wall-clock time.

## Shipped: cross-settlement relationships, further supernatural emergence, dialogue turn-taking, perf pass (v0.67.0)

Built the two items deferred below, plus two new requests: dialogue
turns reading as "disconnected," and a general performance pass.

**Cross-settlement relationships**, following the scoping below closely:
`Settlement.relations: dict[int, float]` on `SettlementDisposition`
(same domain as `temperament`/`player_standing`), seeded at fission via
`seed_relation(origin.temperament, rng)` — base warmth 0.3 (a peaceful
split, not an exile), colored +-0.2 by the origin's mood at the moment
of departure, small jitter so no two fissions seed identically. Ticks
monthly via `tick_relation` (pure mean-reversion + noise, no fortune-
category input like temperament — a between-settlement relationship is
driven by recorded contact, not the settlement's own general luck),
same cadence as `_maybe_tick_temperament`. Two real mechanical hooks,
matching the two candidates this entry originally proposed: (1)
`market_relation_factor` — a settlement's average standing with its
named sisters nudges its own market-price target +-10%
(`RELATION_MARKET_INFLUENCE`), wired into `tick_market_prices`; (2)
cross-settlement dialogue — `SimulationEngine._apply_pending_dialogue_
results` now checks whether a resolved dialogue pair belongs to two
different settlements (rare but real: the map is shared, so a pair can
be colocated near a settlement border even though each settlement's
population mostly stays near its own home) and nudges both
settlements' mutual relation by `DIALOGUE_SENTIMENT_DELTA` — the same
per-exchange magnitude a personal `Agent.relationships` nudge gets.
`dialogue.build_prompt` also reads the pair's cross-settlement relation
(when one exists) into the prompt as ambient context ("Rivertown and
Hillside are on warm/cold terms"), the same way personal affinity
already colors the `tie` text one level up.

**Further supernatural emergence**: `omens.CROSS_SETTLEMENT_OMEN_
CHANCE` (0.3) — when `_maybe_schedule_omen` is about to author a new
omen and at least one *other* named settlement has its own
`omen_history`, there's a 30% chance one of that settlement's past
omens is blended into the local `past_omens` pool passed to the
prompt, using the exact same "if it fits naturally, this could echo
something noticed before" framing `omens.build_prompt` already offers
for in-settlement echoes. Deliberately minimal: no settlement name or
cross-settlement framing is ever mentioned in the prompt or the
resulting omen text — from the LLM's (and the player's) point of view
it's indistinguishable from any other echo. The only way this is ever
visible is if a player compares two different settlements' omen
histories and notices the same phrase in both — exactly the kind of
connection this project leaves for the player to find, never narrates
directly. Matches Phase G's standing rule: extend incrementally, never
escalate toward anything explicit.

**Dialogue turn-taking**: user report that NPC-NPC exchanges could
read as disconnected — line_b not clearly responding to line_a. Both
lines are already generated in one JSON call, so the model technically
has "context" of both simultaneously, but `SYSTEM_PROMPT` never
explicitly required line_b to be a response rather than an independent
statement, which a weaker model can (and evidently did) produce as two
plausible-but-unrelated lines. A true multi-turn generation (produce
line_a, then feed it into a second call to produce line_b as a reply)
would double dialogue's LLM call volume for a fix achievable in the
prompt — added one explicit instruction instead: "line_b must directly
respond to, react to, or answer what line_a just said... not a restart
on a new topic."

**Performance pass**: profiled a 60-agent/64x64/2000-tick run with
cProfile rather than guessing where to optimize. `Population.
_nearest_resource` — the function v0.65.2's fishing-preference fix
touched — was the clear largest self-time hotspot: a full scan of
every resource node on the map (~800 nodes on this map) on every call,
regardless of `FORAGE_SEARCH_RADIUS` (6). Rewrote it to scan the
bounded (2*radius+1)^2 = 169-cell box directly via `dict.get` lookups
instead of iterating `resources.nodes.items()` — behavior-identical
(same FISH-preferred, same distance tie-break), but now a fixed cost
independent of map size or node density instead of scaling with total
node count. Measured: 1.554s -> 0.219s self-time in the profiled run
(~7x), total profiled time down ~11%. This is exactly CLAUDE.md's
pre-approved first escalation step ("spatial buckets for nearest-X
scans") applied to the one function that actually warranted it —
checked the rest of the top-25 profile entries too (`Settlement.at`
already position-indexed/O(1); `_update_relationships`'s cost is
proportional to genuine relationship count/colocation, not wasted
work) and found nothing else worth changing without a measured reason.
Clean (unprofiled) throughput after the fix: 1.42ms/tick at population
60 on a 64x64 map — still ~700x headroom against the 1000ms/tick
budget. Restating the standing finding: the tick loop was never
CPU-bound and still isn't; this was a genuine, measured hotspot worth
fixing on its own merits, not evidence otherwise.

## Deferred (shipped in v0.67.0, see above): cross-settlement relationships, further supernatural emergence

User requested both in the same batch as the items above. Not built
this pass — both are genuine new subsystems, not incremental fixes to
existing mechanics, and CLAUDE.md's own "smallest coherent milestone at
a time" / Phase G "ambiguity discipline, extend incrementally, never
escalate toward anything explicit" rules argue for a deliberate design
pass rather than bolting them on inside an already-large mixed batch.

Scoped for next time: **cross-settlement relationships** would need a
`Settlement.relations: dict[int, float]` (settlement id -> affinity,
same shape as `Agent.relationships`), seeded at fission from some
signal of how the departing party felt about the settlement they left
(founder ambition/grievance, or the fission LLM decision's own
rationale), mean-reverting like `temperament`, and wired into at least
one real mechanic — most natural candidates: a trade-price modifier
between settlements (extends `tick_market_prices`) or a migration/
caravan bias (extends the existing caravan mechanism to sometimes be
*inter-settlement* rather than only external). **Further supernatural
emergence** would extend `llm/omens.py`/`Settlement.omen_history` to
occasionally reference a *different* settlement (echoing the existing
"omen echoes a past omen" mechanic across settlements instead of only
within one) — deliberately small, since Phase G's standing rule is
that this stays ambiguous and never escalates toward anything explicit;
a bigger swing here needs its own careful pass, not a rushed addition.

## Fixed: four live-report bugs — births, naming, disease, mountain geography (v0.68.0)

Four symptoms reported from a real long-running world (year 2, tick
~15000). Each investigated to root cause before fixing (per the
standing "audit before continuing" rule), not patched on guesswork.

**No births by tick 15000.** `carrying_capacity`'s multiplier starts
below 1.0 for a freshly-founded settlement: founders start at
`age_ticks=0` (`_generate_founders`), so until `MATURITY_TICKS` passes,
`labor_term = (labor_fraction - 0.5) * CARRYING_CAPACITY_LABOR_WEIGHT`
is negative (nobody is mature+healthy yet). `CAMP_TOLERANCE` — the
housing-free baseline capacity — was set to exactly
`Config.initial_population` (12 == 12), so this early negative
multiplier pushed capacity *below* the founding population itself,
and `_maybe_reproduce`'s `len(self.agents) >= total_capacity` gate
blocked every birth from tick 0. Capacity does recover once agents
mature (labor_term turns positive) and further once economy/knowledge
terms kick in, but the margin stays thin without a standing HUT, and a
run that's had bad luck on other terms (harsh weather, any sickness)
can sit right at the cap indefinitely. Fix: raised `CAMP_TOLERANCE` to
18 (`hearthmind/settlement/buildings.py`) so a founding party always
has real headroom independent of the multiplier's early swings.
Verified with a 20,000-tick engine run (real `SimulationEngine._tick_once`
loop, not a bare `World.tick()` — see the note below): 216 births,
population 12 -> 227.

**Village never gets its LLM-proposed name.** `World.tick()` gives
every settlement an instant deterministic placeholder the first tick a
building stands, and a background LLM job is supposed to replace it
with a better, context-aware name. `SimulationEngine._maybe_schedule_naming`
keyed the *entire* scheduling decision off `World.newly_named_
settlement_ids`, which was itself only ever populated inside the
`if not stl.name` branch that assigns the placeholder — i.e. it only
ever fires the one tick the placeholder is first set. On any resume,
`stl.name` is already truthy (the placeholder was persisted in the
snapshot), so that branch never runs again, the job is never
(re)scheduled, and the settlement is stuck on its placeholder forever
— a real, structural bug, not a rare corner case, since any
long-running world under `hearthmind-server` is expected to restart
occasionally. Fix: added a persisted `Settlement.llm_named` boolean
(`SettlementCulture.llm_named`), set true only in the naming job's
`apply()` callback once it actually resolves (real name or fallback —
either is a genuine resolution). `World.tick()` now decouples
"placeholder assignment" from "queue the LLM job": it queues the job
whenever a settlement has a standing building, a name, and
`not llm_named` — every tick, not just the one the placeholder was
set — so a resumed world with an unresolved name gets it re-queued.
`SimulationEngine._naming_scheduled_ids` (in-memory, per-process)
still prevents re-scheduling within one run once the job is in flight.

**Disease effectively invisible early game.** Not a bug in the sense of
broken code — `Population._maybe_outbreak` is real, deterministic, and
fully surfaced (`sick_count`/`immune_count`/`deaths_disease` in
`summary()`, sick/immune rings in the UI, all live-wired, no stub).
The problem is calibration: `OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK
(1e-7) * len(agents)` gives roughly 1 case/year at population 200
(the documented design target), but at a founding population of ~12
that's ~1.2e-6/tick, an expected first case around tick ~830,000
(~24 sim-years) — long past any practical observation window, reading
as "disease doesn't exist" for the entire early-to-mid game. Fix:
added `OUTBREAK_MIN_CHANCE_PER_TICK = 2e-5` as a floor
(`max(chance, OUTBREAK_MIN_CHANCE_PER_TICK)` in `_maybe_outbreak`) —
puts a small settlement's first case within roughly a sim-year or two.
Any settlement large/crowded enough that the population-scaled term
already exceeds this floor is completely unaffected, so the "rare at
low population, real pressure once crowded" design intent for mature
settlements is untouched.

**Geography never interacted with technology.** `WALKABLE_BIOMES`
(`GRASSLAND, FOREST, HILLS, BEACH`) excludes `MOUNTAIN`/`SNOWCAP`
unconditionally, and nothing in `agents/population.py` or
`settlement/buildings.py` ever referenced `MOUNTAIN` — it was a hard
barrier to movement, foraging, and construction site selection at
every era, including `digital`. `tech_level`/`era` only ever gated
building *kinds* (FACTORY/POWER_PLANT past `industrial`) and vehicles
(AUTOMOBILE past `modern`), never terrain passability, despite mining/
tunneling being exactly the kind of era-appropriate technology this
project's design priorities call for modeling. Fix: added
`ERA_UNLOCKS_MOUNTAIN_BUILDING = frozenset({"electrical", "modern",
"digital"})` (`settlement/buildings.py`, same shape/threshold as
`_ERA_UNLOCKS_ELECTRICAL`) and `MOUNTAIN_WALKABLE_BIOMES` (`agents/
population.py`). `_is_walkable` takes a `mountain_unlocked: bool`
param (default False, so every existing caller is unaffected);
`_choose_build_site` now takes the settlement's `era` and includes
MOUNTAIN tiles once unlocked; `_dispatch_movement` computes
`mountain_unlocked = settlement.era in ERA_UNLOCKS_MOUNTAIN_BUILDING`
once per agent and threads it into that settlement's own
`_step_toward`/`_bfs_step` calls (both the goal-directed target step
and the long-range travel_target journey step), so agents can actually
walk onto and build on a staked mountain site once their settlement's
tech qualifies — not just "foundable in theory but unreachable," the
mistake the RAFT/water-transport precedent explicitly warns against
repeating. `SNOWCAP` stays impassable at every era (mountains become
passable, not the snowline above them). The general random-walk
fallback (`_maybe_move`) and fission-site selection (`_best_founding_
site`/`_reachable_tiles`) were deliberately left untouched — routine
wandering and initial founding don't need mountain access, and
extending those too would be scope creep beyond what was asked.
Verified via direct unit checks (`_is_walkable(terrain, x, y,
mountain_unlocked=True/False)`, `_choose_build_site` with a
synthetic all-mountain terrain at `industrial` vs `electrical` era)
since a fresh world doesn't organically reach `electrical` within a
practical verification run (tech_level 0 after 20,000 ticks in the
births-verification run above).

**Methodology note:** the first attempt at verifying the births/naming
fixes used a raw `World.tick()` loop (the pattern from the v0.67.0
profiling pass) and showed zero births, zero construction, and
materials stuck at 0.0 across 60,000 ticks — looked alarming, but was
a test artifact: per-agent goal assignment (`_schedule_due_cognition`,
which resolves to `fallback_goal` when the LLM is disabled) lives
entirely in `SimulationEngine._tick_once`, not in `World.tick()`
itself, so bypassing the engine leaves every agent's goal at its
default forever — nobody ever gathers materials or builds. Re-verified
correctly through `SimulationEngine._tick_once()` in a loop (real
entry point, matches what `hearthmind-server` actually calls), which
produced the real numbers cited above. Worth remembering for any
future ad-hoc verification script: `World.tick()` alone is the
physical-substrate layer only; goal/dialogue/most LLM-adjacent
scheduling is engine-level.

## Codebase audit + safe dedup refactor (v0.69.0)

Full read-through audit for performance, maintainability, and ease of
adding features — the detailed findings and the sequenced plan for the
deferred larger refactors live in `docs/REFACTOR-2026-07.md`. Summary
of the decisions:

- **The codebase is clean.** An AST scan found one real unused import
  (fixed) and zero dead functions. A fresh cProfile (60 agents/64×64)
  confirmed the standing finding yet again: no wasteful hotspot remains
  after v0.67.0's `_nearest_resource` fix; every top cost is
  proportional to genuine simulated activity, and the tick loop uses
  ~4 ms of a 1000 ms budget.
- **Shipped a behavior-preserving dedup pass**: a new stdlib-only
  `hearthmind/util.py` (`clamp`, `namespaced_rng`, `namespaced_roll`)
  removes a verbatim triple-copy of the namespaced-RNG helper and gives
  the recurring `clamp` idiom a named home. Every module keeps its
  historical private helper name via a one-line alias, so **no call
  site changed**. Proven equivalent by a 7000-tick event-stream hash
  match (before vs. after) plus a boot smoke test — the standard,
  test-suite-free verification this project uses.
- **The big structural refactor (splitting the three 2000–4000-line
  files) was deliberately NOT attempted in this run.** Rationale: no
  automated test net exists here, so the only safe way to move a
  method-group out of `population.py` is one group at a time behind the
  event-hash equivalence check — several careful iterations, not a
  single edit that could silently change behavior. The plan (R1:
  mixin-based package split; R2: engine scheduler registry; R3: finish
  `clamp`; R4: the explicitly-declined numpy grid pass) is written up
  concretely in `docs/REFACTOR-2026-07.md` so a future run (or the
  user's own live-verified session) can execute it incrementally. This
  is the "properly document what you can't safely finish" half of the
  brief, and it aligns with the standing "smallest coherent milestone
  at a time" / "audit before continuing" rules.

## LLM core cast + daily call ceiling: the swap-after-hours fix (v0.70.0)

**Symptom (live report):** after a few hours of running, swap usage
climbs again — the user's read was "Ollama-side, and NPC-NPC dialogue
volume seems to grow over time." Correct on both counts.

**Root cause.** Not a Python-side leak — a re-audit confirmed every
per-agent/per-pair structure is still capped/pruned (dialogue &
cognition-trigger cooldowns, agent memories, latency window, background
tasks, relationships/trust). The real mechanism is that total LLM call
*throughput scales linearly with population*:
- `due_for_cognition` schedules one goal-reevaluation per living agent
  per sim-day → population calls/day.
- `due_for_dialogue` selected up to `MAX_DIALOGUES_PER_TICK=3` pairs per
  tick, and at high population nearly every tick hit that cap.
- Settlement-level jobs are round-robin bounded (`MAX_SETTLEMENTS=3`) —
  NOT the culprit.
Concurrency is capped (semaphore at `llm_max_concurrent=2`), so this was
never about *simultaneous* calls. It's about *sustained* load: as a town
grows from ~12 to hundreds over a few real hours, Ollama goes from
lightly loaded (real idle gaps, model unloads per `keep_alive=3m`) to
continuously saturated — always 2 calls in flight, back-to-back, for
hours. Sustained saturation keeps the model + KV cache permanently
resident and lets Ollama's own slow per-call memory growth accumulate
over thousands of consecutive calls → swap on 8GB. The fix has to
decouple call volume from population, exactly as the user proposed.

**Fix 1 — LLM core cast (`Config.llm_core_cast_size`, default 11).**
`Population.core_agent_ids` is a fixed, sticky set of ~11 agents. Only
core agents get LLM cognition; only a core–core pair gets LLM dialogue.
Everyone else, and every mixed/crowd pair, uses the deterministic
fallback (which already exists and is good) — applied inline, no Ollama
call. `maintain_core_cast` (called each tick by the engine) prunes the
dead and refills open seats from the most-prominent living non-member
(`_prominence` = age + social bonds + skill, weighted so none
dominates), tie-broken by id for determinism. Members are never demoted
while alive: the cast is deliberately a stable presence (persistent
identity), seeded from the founders on a fresh world. Persisted so a
resumed world keeps the same protagonists. Dialogue selection
(`due_for_dialogue`) now returns `(llm_pairs, fallback_pairs)` and
*prefers* core–core pairs for the (small, constant)
`MAX_LLM_DIALOGUES_PER_TICK=2` LLM slots, so the cast reliably converses
via the model even though crowd pairs vastly outnumber them.

Measured with a mock client (no real Ollama): at **population 120, ~11.5
LLM calls/sim-day** vs. ~120/day under the old per-agent scheme — and
crucially flat as population grows further (it tracks cast size, not
town size). This is the load-bearing change.

**Fix 2 — daily call ceiling (`Config.llm_max_calls_per_day`, default
200).** Belt-and-braces: a hard per-sim-day cap on *all* Ollama calls
(cognition, dialogue, settlement jobs), consumed via
`SimulationEngine._consume_llm_budget`, reset at `day_end`. Once hit,
every further LLM decision that day resolves via its fallback. The core
cast already keeps volume far under this; the ceiling exists so a future
bug in cast selection or a newly-added per-agent LLM job can never
recreate the unbounded-throughput condition. Verified to hard-bound
throughput (peak never exceeds the cap; set it to 5 and exactly 5 calls
land per day). Surfaced in `/diagnostics`
(`llm_calls_today`/`llm_max_calls_per_day`/`llm_core_cast_current`).

**Design-priority note.** This trades some LLM richness (the crowd is now
deterministic) for stability, at the user's explicit direction ("swap
should not occur anymore"). It is *not* a pure loss for emergence: a
stable cast of ~11 deep, model-authored characters against a
deterministic crowd is arguably better for legible storytelling than
diffusing LLM attention across a whole growing town. Tune
`--llm-core-cast-size` up if the hardware has headroom, down if swap
ever reappears; diagnose via `/diagnostics.system_memory` first.

**Verification note.** Because this deliberately changes behavior, the
v0.69.0 golden event-hash equivalence check does NOT apply to this
feature (only to R3, which it still passes). Verified instead by: a
20,000-tick llm-disabled soak (core cast fills to 11 and stays alive,
goals still assigned, dialogues still occur, no crash, snapshot
round-trips the cast); a mock-client llm-enabled run proving the volume
bound and the daily cap; and a server-CLI boot smoke test.

## Unbounded-growth re-audit: event-log retention + query clamps (v0.71.0)

Follow-up to the v0.70.0 swap fix, per a request to hunt any remaining
place memory can grow without bound. **The RAM/Python side is clean** —
every per-agent/per-pair collection is capped or pruned: agent memories
(MAX_AGENT_MEMORIES), personal beliefs (MAX_PERSONAL_BELIEFS, evict
weakest), settlement/family/council/guild beliefs (MAX_BELIEFS /
INSTITUTION_BELIEF_CAP), belief history (BELIEF_HISTORY_MAX),
relationships/trust (pruned on decay/death), dialogue &
cognition-trigger cooldowns (pruned), traditions/inventions/festivals
(CULTURE_LIST_MAX_STORED), records (RECORDS_MAX_STORED), memorials
(MEMORIALS_MAX_STORED), omen/priority history (OMEN/PRIORITY_HISTORY_MAX),
institutions (extinction-prune at 300), core cast (llm_core_cast_size),
and every engine structure (pending goal/dialogue results cleared each
tick, `_last_llm_calls` keyed by job name, broadcast buffer capped,
snapshot-payload cache evicted). `place_names` is bounded by the map's
*fixed* lake count (`identify_lakes` runs only at world creation, so lake
ids never churn). Nothing per-agent or per-event accumulates in RAM.

Two genuine unbounded-growth vectors were found, both on the
persistence/interface boundary rather than the sim core:

**1. The `events` table had no retention.** Snapshots are already pruned
to recent + keyframes and metrics grow only ~1 row/sim-day, but `events`
logged every notable world/life event forever (~1-2 rows/tick), so a
persistent, always-running world grew the SQLite file without limit —
the exact "runs forever" failure the snapshot keyframe design already
guards against, left unaddressed for the higher-frequency table. Fix:
`snapshot._prune_events` keeps the most-recent `Config.event_log_retention`
rows (default 200k, CLI `--event-log-retention`, 0 disables), pruned on
the snapshot cadence inside the same transaction. Lossless for every
real reader — the live feed queries LIMIT 50, History LIMIT 200, both
newest-first, and deep world-state history is preserved by snapshot
keyframes; only the ability to scroll the *raw* event log back past
~months of activity is affected, which no UI does. `event_category_counts`
becomes windowed rather than literally all-time (docstring updated).
Verified: a 3000-tick run with retention=500 leaves exactly 500 rows.

**2. Unclamped query `limit`.** `/events`, `/history`, `/metrics` passed
the client's `?limit=` straight into `LIMIT ?`. Against the (now bounded
but still large) events table, a single request for a huge limit would
materialize that many rows into a Python list at once — a client-
triggered RAM spike that scaled with the table. Fix: `recent_events`/
`history_events`/`recent_metrics` clamp to `QUERY_LIMIT_MAX = 5000`
(far above any UI view: live feed 50, History 200, metrics 365). Clamped
in the query functions themselves, so every caller is protected, not
just the HTTP layer. Verified: `recent_events(limit=10_000_000)` returns
at most the clamp, never the whole table.

**3. Intervention queue** (defensive): `WorldBroadcaster._interventions`
drains every tick, but a POST burst against a stalled/paused loop could
grow it unbounded between drains. Capped at `INTERVENTION_QUEUE_MAX = 256`
(oldest dropped) — far above any realistic burst of genuine nudges.

Standing note: `metrics` (one row/sim-day) is slow enough to leave
unpruned for now; if a world runs for *years* of sim-time it too should
get a retention window, but at ~365 rows/year it is nowhere near the
`events` table's growth rate. These are DB/disk-and-request-RAM fixes;
the sim event stream is untouched (the changes are orthogonal to tick
logic — prompts only ever read the newest ~50 events, which pruning
never removes).

## Ollama swapping "worse than before": resident memory, not call volume (v0.71.1)

Live report: swap pressure is worse than ever despite the v0.70.0
core-cast fix. **Diagnosis: the previous fixes targeted the wrong
quantity.** v0.70.0 cut LLM *call volume*, which governs *sustained CPU
load* — but Ollama's *resident RAM* is model **weights** (loaded once,
resident while warm) + **KV cache**, and neither shrinks when you call
the model less often. The KV cache is the swing term on 8GB:

    KV cache ≈ num_ctx × OLLAMA_NUM_PARALLEL × bytes_per_element

and crucially it's allocated **up front at the full `num_ctx`**,
independent of how short the actual prompts are. Ollama's default
`OLLAMA_NUM_PARALLEL` is often **4**, so a stock server reserves four
full context windows of KV cache (commonly 2-4 GB) on top of ~2.6 GB of
qwen3:4b weights — that's what tips 8GB into swap, and it does so
whether Hearthmind makes 11 calls/day or 1100.

**What the app can control (done here):**
- `llm_num_ctx` 2048 → 1280, `llm_num_predict` 512 → 384. Measured the
  real prompts first (the largest, the monthly chronicle, is ~600 input
  tokens; +384 generation ≈ ~1000 peak), so 1280 fits with ~280 margin.
  This is a ~37% cut to *our* per-slot KV allocation, applied
  unconditionally. Undersizing `num_ctx` silently truncates prompts, so
  this was measured, not guessed.
- `PROMPT_RECENT_EVENTS` 50 → 30: the recent-events block dominated the
  biggest prompt (~680 of ~900 tokens); trimming it is what makes the
  lower `num_ctx` safe.
- Verified byte-identical for the deterministic (llm-disabled) sim —
  these only affect the Ollama request/prompt, never tick logic.

**What only the user can control (README, made prominent + turnkey):**
the dominant levers are Ollama *server* env vars — `OLLAMA_NUM_PARALLEL=1`
(one KV slot instead of four; safe with our `llm_max_concurrent=2` floor,
Ollama just serializes the two in-flight calls), `OLLAMA_KV_CACHE_TYPE=
q8_0` + `OLLAMA_FLASH_ATTENTION=1` (half the KV bytes), `OLLAMA_MAX_
LOADED_MODELS=1`. Together ~8× less KV cache than the stock default.
The README's old "8GB tuning" section had `NUM_PARALLEL=2` as the
recommendation and buried `=1` as a last resort; it now leads with `=1`
and a single copy-paste block. Escalation if weights are still too big:
size the model down to `qwen3:1.7b` (~1.4 GB vs ~2.6 GB) — documented
with exact commands — and/or `--llm-core-cast-size 8`.

**Standing note:** call-volume tuning (core cast, daily ceiling) and
resident-memory tuning (num_ctx, num_parallel, kv dtype, model size) are
*orthogonal*. A swap report is almost always the latter; diagnose with
`ollama ps` / `/diagnostics.system_memory` (weights vs KV vs our RSS)
before touching call volume. Do not raise `llm_num_ctx` without
re-measuring prompts.

## llama.cpp default backend + native C++ port begins (v0.72.0)

Explicit user directive: port hot engine code to C++, switch the
default LLM backend from Ollama to llama.cpp, tune for AMD Ryzen iGPU
offload (Radeon 740M/780M). Two prior standing findings pushed directly
against this: "C/C++ port: evaluated, recommended against" (the tick
loop is ~1ms against a 1000ms budget — a full port buys almost nothing
on throughput) and the earlier "why not switch to raw llama.cpp"
evaluation (Ollama's runner already *is* llama.cpp, so the memory math
is nearly identical). Both were surfaced to the user before starting,
along with the concrete risk that this project has no automated test
suite, so a full-engine C++ rewrite in one pass has no equivalence-proof
net the way the existing SHA-256 event-hash harness provides for a
scoped change. User chose to proceed with the full-port *direction*
anyway; the response was to scope execution as a sequence of provably-
equivalent increments rather than one unreviewable rewrite — same
discipline this project already uses for every other behavior-
preserving change (R2/R4), just applied to a larger target.

**llama.cpp backend.** `LlamaCppClient` (hearthmind/llm/client.py)
talks to `llama-server`'s OpenAI-compatible `/v1/chat/completions`
endpoint with `response_format: {"type": "json_object"}` — llama.cpp
enforces this via grammar-constrained sampling, structurally stronger
than Ollama's `"format": "json"` (which is a request hint, not a hard
constraint). `Config.llm_backend` (default `"llamacpp"`) / `"ollama"`
select the backend; `build_llm_client(config)` is now the single
factory both `SimulationEngine.__init__` and `server.py`'s genesis-seed
call use, closing off the class of bug where the two call sites drift
on which fields each client actually consumes (the same failure mode
the v0.63.0 CLI-default audit found once already). `LLMUnavailable`
replaces `OllamaUnavailable` as the base exception name since both
clients raise it; the old name survives as an alias so nothing else had
to change. Why llama.cpp over keeping Ollama as default: not a memory
argument (the earlier evaluation's core claim — same runner, same
weights+KV math — still holds), but Ollama's daemon adds ~100-300MB of
its own overhead and, more importantly, this project has spent several
releases fighting Ollama's *defaults* (mmap heuristics, keep_alive,
`OLLAMA_NUM_PARALLEL`) through per-request options and README
environment-variable workarounds; `llama-server` exposes the same
knobs (context size, KV quantization, thread count, GPU layers) as
direct process flags the README can hand the user verbatim, with no
daemon-level defaults to route around. AMD iGPU offload was also a
direct motivator: Ollama's bundled ROCm build didn't recognize the
Radeon 740M (gfx1103) in an earlier investigation, while llama.cpp's
Vulkan backend doesn't depend on ROCm's hardware allowlist — see the
README's "AMD Ryzen iGPU offload" section. That section is **not
verified against real hardware** by this pass (this execution
environment has no GPU) — flagged explicitly rather than presented as
tested.

**Native C++ port, module 1: `ResourceGrid.tick`.** New optional
`hearthmind._native` pybind11 extension (`cpp/src/resource_grid.cpp`,
built by `setup.py build_ext --inplace`, wired into `pyproject.toml`'s
build-system requirements so `pip install -e .` attempts it
automatically). `world/resources.py`'s `tick` now dispatches to
`_tick_native` when the extension is importable, `_tick_python`
(byte-for-byte the pre-v0.72.0 implementation) otherwise — chosen as
the first module because it's self-contained pure arithmetic over a
small key/value shape with no cross-module state, and because R4 had
already isolated its hot loop into a working-set iteration that was
straightforward to mirror in C++ exactly. Verified via a standalone
3000-tick equivalence script (randomized season changes + depletion
events) hashing final node-amount state to a SHA-256 — native and
Python paths matched exactly — plus the existing 4000-tick
`llm_enabled=False` engine soak run with the extension loaded, to
confirm the import/dispatch wiring doesn't disturb anything else in the
tick loop.

**Gotcha that cost a debugging round-trip:** the first implementation
passed the node-amounts dict to C++ as `std::unordered_map<long long,
double> &` expecting pybind11 to mutate the caller's Python dict in
place. It doesn't — pybind11's default STL casters *copy* a Python
container into a temporary C++ object on the way in; mutating that
temporary has no effect on the Python side. This compiled and ran
without error, silently producing wrong results (a bug the equivalence
hash caught immediately, which is the whole point of writing the check
before trusting the port). Fixed by having the C++ function return the
updated mapping instead of mutating a reference parameter. Recorded as
a standing gotcha for the next module: never rely on "pass a container
by reference and mutate it" across the pybind11 boundary — return the
new value.

**Scope discipline for what's NOT done.** `population.py`/`engine.py`/
`buildings.py` — the orchestration layer, ~8,400 lines combined,
touching dozens of other modules and the LLM job scheduler — are
explicitly not attempted here and are not simple mechanical
translations the way a self-contained numeric loop is; porting them
meaningfully means redesigning around C++ ownership semantics for
what's currently Python's reference/GC model, which is a redesign
project, not a port, and needs its own dedicated-session scoping (see
`docs/REFACTOR-2026-07.md`, R5, which also ties this back to R1 — a
mixin split first would make the orchestration/hot-loop boundary
cleaner to extract from). Two more self-contained candidates
(`world/weather.py`'s grid pass, `Population._nearest_resource`) are
queued next in R5, same one-module-at-a-time discipline.

**`/diagnostics.system_memory` backend-agnostic fix.** Its process
scan matched only `"ollama"` in `/proc/<pid>/comm` — with llama.cpp now
the default, this would have silently reported zero LLM-server memory
on every fresh install. Widened to also match `llama-server`/
`llama-cli`/`llama.cpp`; the JSON key stays `ollama_processes` for
backward compatibility with the existing UI/README rather than a
rename that would touch more surface for no functional benefit.

## LLM core-cast map markers + dialogue quality pass (v0.72.1)

Closed both items explicitly deferred at the end of v0.72.0.

**Map markers.** `is_core` wasn't previously part of the per-agent
broadcast payload at all — `Population.core_agent_ids` existed
server-side (v0.70.0's core-cast fix) but had no UI surface beyond a
raw count in `/diagnostics`. `_maybe_broadcast` now merges
`population.is_core(a.id)` into each agent dict; the frontend renders a
blue triangle (`drawAgentTriangle`, a new small shared helper — also
now used for the predator-pack marker, which was previously an inlined
duplicate of the same three-point-path logic) instead of the plain dot
for core-cast agents, plus a "▲ core" badge in the hover tooltip and the
NPC inspector header. Consistent with the Observatory UI direction
(CLAUDE.md): the map is the primary instrument, so this needed to be
visible there directly, not only as a number behind the dev console.

**Dialogue quality — LLM path.** `build_prompt` grounds each speaker's
activity in `goal_reason` (set by both LLM cognition and the
trait-aware fallback goal) when present — previously the prompt only
named the bare goal ("currently forage"), never the motivation, despite
`cognition.py`'s prompt already including this for goal-setting.
Measured the worst-case prompt (both speakers with long goal_reason
text, memories, beliefs, culture, cross-settlement context) at ~786
tokens including the system prompt — safely under the 1280-token
`llm_num_ctx` budget the v0.71.1 pass tuned against a ~1000-token peak
(the chronicle prompt remains the dominant one). `SYSTEM_PROMPT` also
now explicitly permits disagreement/deflection/off-topic answers —
previously it only demanded line_b "respond to" line_a, which in
practice pushed toward uniformly tidy, agreeable exchanges; added a
tense-band example to the few-shot set to make disagreement a visible
option, not just a permitted one.

**Dialogue quality — deterministic fallback.** `fallback_dialogue` was
100% static template pools (5 entries/band) with zero connection to
what had actually happened to either agent — a fallback-only run (LLM
disabled, unreachable, or a core-cast pair that lost its slot to
backpressure/budget) read as pure canned chit-chat regardless of the
model. Now splices a memory-grounded opening line ("Did you hear?
{most recent memory}") into roughly one exchange in three for non-tense
pairs (tense pairs stay pool-only — trading a memory doesn't fit an
"at odds" read the same way), with a short generic reaction pool on the
other side. Selection is deterministic from `(agent ids, tick)`, not
random, matching the project's per-site-deterministic convention (not a
determinism *requirement* — see CLAUDE.md — just the natural cheap
choice here too). Each pool also widened 5 → 8 entries for a longer
repeat cycle before a fallback-only run notices it.

**Verification:** a 6000-tick engine soak (`llm_enabled=False`, so
every dialogue exchange goes through `fallback_dialogue`) ran without
error; sampled `events` rows for `category='dialogue'` show the
memory-grounded lines ("Did you hear? Wren shared food with me.")
interleaving with the pool lines as expected, not dominating or
crowding them out.

## pyproject license fix, one-command run script, native port module 2 (v0.72.2)

**License field.** `project.license = { text = "MIT" }` triggers a
setuptools deprecation warning on modern setuptools (>=77 supports and
prefers a bare SPDX string, `license = "MIT"`, deprecating the TOML
table form with a 2027-02-18 removal date). Fixed directly. Verifying
this locally required upgrading this sandbox's own `setuptools` (68.1.2
-> 83.0.0) and `packaging` (24.0, debian-managed and broken -> 26.2 via
`--force-reinstall --ignore-installed`) — neither upgrade is shipped as
a runtime dependency of this project; they're pinned in `build-system.
requires` so `pip install -e .` resolves a matching pair via its own
build isolation regardless of what's already on the host.

**One-command run script.** `scripts/run.sh` — the practical answer to
"how do I actually start the game" now that step 1 of the LLM setup is
a separate long-running process (`llama-server`) the user has to
coordinate with `hearthmind.server` themselves. Design choices worth
recording: (1) `curl .../health` polling before starting hearthmind,
rather than a fixed sleep, since model load time varies hugely by
quantization/hardware; (2) the cleanup trap is registered once, up
front, referencing pid variables that get populated later — bash
evaluates the function body at call time, so this stays correct
regardless of where in the script a signal arrives, rather than the
first draft's bug where the trap only existed for the llama-server pid
and Ctrl+C during `python3 -m hearthmind.server` orphaned it (caught by
manually SIGTERM-testing the script, not by inspection — the orphaned
process kept running for the tool's own 2-minute timeout in testing,
which is exactly the kind of "looks right, isn't" bug live-testing
catches and code review doesn't); (3) hearthmind runs backgrounded
(`&` + `wait`) rather than as the final `exec`'d command, specifically
so the trap can still reach it — an `exec` replacement can't be reached
by a parent-registered trap once it's happened.

**Native port module 2: `Population._nearest_resource`.** Chosen after
re-examining the "queued next" list from v0.72.0/v0.72.1's R5 section,
which turned out to have named two candidates that weren't actually
good ports on closer inspection — `world/weather.py`'s `compute_weather`
is O(1) per tick (a single `WeatherState`, not a per-tile pass at all;
the original "grid pass" description was simply incorrect), and
`world/terrain_evolution.py`'s functions run weekly/monthly and touch
`Settlement`/`Farm` occupancy state — cross-module and infrequent,
the opposite of what makes `resources.tick` a good port target. Went
back to the actual evidence instead: the v0.67.0 profiling pass had
already named `_nearest_resource`'s bounded-box scan the single largest
self-time hotspot in a 60-agent run. Ported as a compiled
`ResourceIndex` class (`cpp/src/resource_grid.cpp`) wrapping a native
hash map of in-range FOOD/FISH node positions.

The nontrivial part wasn't the query (a straightforward bounded-box
scan, same shape as `resource_grid_tick`) but keeping it exactly
equivalent to the live Python dict scan across a single tick with
multiple foraging agents. `resources.tick()` runs *before*
`population.tick()` in `World.tick()`'s fixed order (confirmed by
reading `world/state.py` directly, not assumed), so rebuilding the
native index once per `resources.tick()` call captures every node's
amount as of the start of that tick's population pass — correct for
agent #1's query. But agent #2 querying later in the same
`population.tick()` call needs to see agent #1's depletion too, the way
a live Python dict always does; a once-per-tick-only rebuild would
silently diverge here. Fixed by extending `ResourceGrid.mark_
regenerating` (already called at every depletion site for R4's working
set) to also live-patch the native index's one changed entry — same
call site, same discipline, now doing two jobs. `ResourceIndex::update`
erases the entry when amount drops to/below 0, matching the
constructor's amount>0 filter (a stale zero-amount entry would
otherwise still be "found").

**Verification:** a standalone script ran 20,000 randomized bounded-box
queries against a synthetic 3000-node grid, interleaved with random
mid-run depletions (mirroring same-tick multi-agent foraging), compared
against a literal copy of the pre-port Python scan — 0 mismatches. The
existing 4000-tick `llm_enabled=False` engine soak reproduced the exact
same event-stream SHA-256 as every prior port's baseline, confirming no
behavior change end-to-end, not just in the isolated query.

**Deliberately not ported:** `Population._nearest_material_tile` (the
GATHER-goal equivalent scanning terrain biomes) has the same bounded-
box shape but no measured-hotspot evidence behind it — CLAUDE.md's
standing rule is escalation only with a measured problem, so this stays
pure-Python until profiling says otherwise, not because it's harder.

## GPU offload confirmed working: run.sh build-everything, richer LLM config, native port module 3 (v0.72.3)

**Live confirmation changes the tuning baseline.** Every LLM memory
number in this project since v0.71.1 (`llm_num_ctx`, `llm_num_predict`,
`PROMPT_RECENT_EVENTS`, `DIALOGUE_MEMORY_IN_PROMPT`, `llm_core_cast_size`,
`llm_max_calls_per_day`, `MAX_LLM_DIALOGUES_PER_TICK`) was tuned against
one shared constraint: CPU-only Ollama inference on an 8GB box, where
every KV-cache byte and every second of call latency competed directly
against the same RAM and the same clock the sim itself needed. The user
report driving this pass — GPU offload via llama.cpp confirmed working
and "much much better than expected" on real hardware — removes that
shared constraint at the root, not just for one setting: KV cache now
lives predominantly in GPU memory, and calls finish fast enough that a
larger LLM-driven cast doesn't recreate v0.70.0's sustained-saturation
condition. Rather than re-deriving each number in isolation, every
setting tuned down for that constraint was revisited together, each
with its own docstring explaining what specifically changed and why
(see `config.py`, `simulation/engine.py`'s `PROMPT_RECENT_EVENTS`,
`llm/dialogue.py`'s `DIALOGUE_MEMORY_IN_PROMPT`/`_MAX_LINE_WORDS`,
`agents/population.py`'s `MAX_LLM_DIALOGUES_PER_TICK`/`MAX_DIALOGUES_
PER_TICK`). The CPU-only 8GB path is fully preserved, not deleted —
README's dedicated section documents the non-default override
(`LLAMA_CTX_SIZE=1280 LLAMA_N_GPU_LAYERS=0` + `--llm-num-ctx 1280
--llm-core-cast-size 8`) for anyone still on that hardware profile, and
every constant's docstring says explicitly what to lower and why if
CPU-only pressure returns.

**One correction made while doing this:** the `_MAX_LINE_WORDS`
"under 10 words" dialogue line-length limit was *not* actually a
memory-driven downsize — rereading the original v0.72.1 rationale, it
was a stylistic choice for natural-sounding short dialogue, unrelated
to token budget. Loosening it to 14 words is still a legitimate
dialogue-quality improvement (a longer line reads less like a clipped
fragment), but the docstring is written to say so honestly rather than
retroactively attributing a stylistic choice to the memory pass just
because both changed in the same batch.

**`scripts/run.sh` build-everything expansion.** Previously only
launched already-built binaries. Now builds `hearthmind._native`
automatically (matches the "one command does everything" spirit the
script was written for) and, if `llama-server` is missing, builds it
too — cloning `llama.cpp` first only with explicit opt-in
(`AUTO_CLONE_LLAMA_CPP=1`), since silently fetching code from the
network without being asked is a different risk class than a local
build step; without that opt-in, it prints the exact clone command and
stops. Default launch flags now match the user's confirmed-working
command exactly (`--n-gpu-layers 999`, `--cache-type-k/-v q8_0`,
`--threads $(nproc)`).

**Native port module 3: `Population._nearest_material_tile`.**
Explicitly not a profiling-driven port — the v0.72.2 pass had
deliberately left this unported specifically because it had no measured
hotspot evidence, per CLAUDE.md's "escalate only with a measured need."
This pass overrides that on direct user instruction ("keep moving more
python code to C++"), which is a legitimate reason to proceed but a
different one than "we measured a problem," and is recorded as such
rather than silently reframed as if new profiling data existed.
Mechanically simpler than `ResourceIndex` turned out to be a genuine
discovery, not just an assumption: MATERIAL_BIOMES (FOREST/HILLS) tiles
never deplete (GATHER harvests wood/stone abstractly without touching
the tile's biome), so `TerrainMaterialIndex` needs no live-patch
mechanism the way `ResourceIndex` needed for `mark_regenerating` — a
plain full rebuild once per `Population.tick()` is already exactly
equivalent to the pure-Python scan, no incremental-sync logic required.
Built at the same point `farm_positions`/`granary_positions` already
get computed once per tick and shared across every agent, extending
`_dispatch_movement`'s signature with one new optional parameter
(`material_index`, `None`-safe, defaults to the original pure-Python
path). Verified via 20,000 randomized queries against a synthetic
70x70 terrain (0 mismatches vs. a reference Python scan) plus the
standard 6000-tick cumulative-event-hash engine soak, all three native
modules (resources.tick, ResourceIndex, TerrainMaterialIndex) enabled
vs. disabled — byte-identical.

## v0.72.4: RAM correction, run.sh simplified, native port module 4

**RAM correction.** The v0.72.3 pass raised `llm_num_ctx`/
`llm_num_predict`/`llm_core_cast_size`/`llm_max_calls_per_day` on the
assumption that confirmed GPU offload meant the full 8GB nominal RAM
was available headroom. A follow-up live report gave the real number:
`htop` shows only ~6.5GB usable on that machine. GPU offload does move
weights/KV predominantly into VRAM, but it doesn't zero out system-RAM
pressure — `llama-server`'s own process overhead, its mmap'd model
file, and hearthmind's own process still compete for whatever's
actually free, and 4096/640/18/400 were sized against a number this
machine doesn't have. Re-lowered to 3072/512/14/320 — still real
headroom over the original CPU-only-tuned 1280/384/11/200 (GPU offload
is a genuine, measured win), just not assuming unmeasured RAM. Every
touched field's docstring in `config.py` records the full 1280→4096→3072
(etc.) chain rather than overwriting the v0.72.3 rationale, so a future
reader can see both the original CPU-only tuning and the two GPU-offload
revisions in order.

**`scripts/run.sh` simplified — no longer builds/clones llama.cpp.**
The v0.72.3 auto-build/auto-clone step (`AUTO_CLONE_LLAMA_CPP`,
`LLAMA_CPP_DIR`, `USE_VULKAN` cmake flags) is removed on direct
instruction — the script now only builds `hearthmind._native` (fast,
local) and expects `llama-server` to already exist (`LLAMA_SERVER_BIN`
env var, defaulting to resolving `llama-server` on `PATH`), erroring
with the manual build instructions if it can't find one. README's
"Running the LLM (llama.cpp)" section restructured to put the
`cmake`/`git clone` build step first as an explicit prerequisite, with
`scripts/run.sh` only covering the "build native extension + launch
both processes" half. Also switched `python3` → `python` throughout the
script (was inconsistent with the rest of the project's own preference),
and added `pybind11>=2.11` to `requirements.txt` as a build-time-only
dependency (previously only reachable via `pip install pybind11`
documented in prose, not tracked as a declared dependency anywhere).

**Native port module 4: `Population._nearest_other_agent`.** The
highest-value native-port candidate flagged at the end of v0.72.3,
because unlike the terrain/resource lookups (bounded by a fixed search
radius, so cost is shaped by map density not population) SOCIALIZE's
target search has no distance cap at all (see D4) — it's a genuine
O(population) scan per SOCIALIZE-goal agent, O(population²) worst case
across a tick, growing with town size the same way the v0.70.0 LLM-call
volume problem did. `AgentPositionIndex` (`cpp/src/agent_position_
index.cpp`) is a thin linear-scan wrapper, not a spatial index structure
— there's no radius to bucket by, so a fast scan is the whole
optimization. Built once per `Population.tick()` from the exact same
`position_snapshot` list (same order) the pure-Python path already
constructs, so tie-breaking (first strictly-closer entry wins, in list
order) stays identical. Threaded through `_dispatch_movement` as one
more `None`-safe optional parameter, same shape as `material_index`.
Verified via 20,000 randomized queries against synthetic agent
populations (0 mismatches vs. a reference Python scan) plus the
cumulative-event-hash engine soak at two population scales (16 and 60
agents) — byte-identical native vs. pure-Python in both.

A verification false alarm during this pass is worth recording: an
early two-run A/B harness (`importlib.reload()`-ing `population`/
`resources` between a "native" and "python" run in the same process)
produced a real-looking mismatch (109 vs. 112 events over 3000 ticks).
Root cause was the harness, not the port: `importlib.reload()` rebinds
a module's class objects to new instances, but other already-imported
modules (`engine.py`) hold references to the *old* class objects from
their own earlier `from ... import Population` — those old classes'
methods still read the *same* module `__dict__` (reload mutates in
place, doesn't replace the module object), so patching the native-index
flag afterward does take effect either way, and the reload itself was
pure noise, not a controlled variable. Dropping the reload calls and
just patching the module attribute directly reproduced byte-identical
results consistently across repeated runs. Recorded here so this
harness mistake doesn't get rediscovered the hard way next time.

## v0.72.5: native port modules 5-6, full engine-core rewrite started (R6)

**Conflict flagged, not silently resolved.** User instruction: "port
all remaining code to C++." This is in direct tension with a standing
finding in this same file (v0.63.0 audit): a full C/C++ port was
evaluated and declined, on the grounds that the tick loop is nowhere
near CPU-bound (~1-2ms against a 1000ms budget — the real cost is LLM
wall-clock time) and a full rewrite has no automated-test-suite net to
prove equivalence. Flagged this explicitly before starting, via
`AskUserQuestion`, offering three scope options: keep going
incrementally only; attempt a full engine-core rewrite (tick loop, LLM
job scheduling, persistence orchestration) with no test suite as
equivalence proof; or also replace the Python-ecosystem-integrated
layers (SQLite, asyncio, FastAPI) with C++ equivalents. User chose the
middle option, explicitly scoping out the third: "Let's go
incrementally first and then do a full engine rewrite as well. Need
not rewrite the python libraries like SQLite in c++." This is recorded
as the standing scope for the new R6 track (docs/REFACTOR-2026-07.md):
SQLite persistence, asyncio LLM job scheduling, and the FastAPI web
layer stay Python; only the deterministic tick-time simulation logic
(math and branching over already-resolved primitives, no Python-object-
graph or I/O touching) moves to C++, one verified module at a time,
same discipline as every native-port module since v0.72.0.

**Module 5: `WildlifeGrid.nearest_grazer_herd` → `GrazerHerdIndex`.**
Same live-patch shape as `ResourceIndex`: herd positions are stable
during `Population.tick()` (only `WildlifeGrid.tick()`'s migration step
moves them, and that always runs first — see world/state.py's
`World.tick` ordering), but `hunt()` can zero a herd's count
mid-`Population.tick()`, so the index needs the same rebuild-once-plus-
live-patch shape `ResourceIndex` uses for depletion. **A real bug,
caught by the verification harness rather than assumed absent**: the
first implementation kept herds in a `std::unordered_map`, and
`nearest_grazer_herd`'s Python original resolves *tied*-Manhattan-
distance queries by dict iteration (insertion) order — an
`unordered_map`'s iteration order doesn't preserve insertion order, so
a tied query could silently return a different (equally close, but not
identical) herd than the Python path. This is invisible for a unique-
nearest query, so it wasn't caught by casual testing — it took the
20,000-randomized-query check to surface it (238/20,000 mismatches, all
tied-distance cases). Root cause understood, fixed by switching to an
insertion-order `std::vector<...>` plus a separate `id -> index`
`unordered_map` used only by `update()` (which patches the vector
entry in place, preserving order across live-patches). Re-verified at
0/20,000 mismatches, plus a separate 0/5,000 check specifically
exercising interleaved `update()` calls (simulating hunts) before
querying. **Standing lesson for any future index port:** ask explicitly
whether the underlying pure-Python function's tie-break behavior
depends on container iteration order. `ResourceIndex`/
`TerrainMaterialIndex` don't have this failure mode — both are keyed by
*position* and iterate a fixed spatial (dy, dx) loop matching the
Python original's own loop order, so the *container's* internal
iteration order never leaks into the result. `GrazerHerdIndex` (and
`AgentPositionIndex`, module 4) instead iterate object identity
directly — a list of herds/agents, not a spatial grid — so their
underlying container's order IS the tie-break order, and choosing an
order-scrambling container is a real correctness bug, not just a
missed optimization.

**Module 6: `Population._update_needs` → `update_needs` (first R6
module).** The scoping principle in practice: every object-shaped
lookup (which building an agent stands on, whether it's STANDING,
whether it's a HOSPITAL, the elder-age comparison) is resolved in
Python exactly as before and passed into the native call as plain
booleans/floats; the C++ function only does the arithmetic that follows
— hunger/energy drain-and-recovery math, sickness/weather/crowding/
night multipliers, the awake/resting state transition. This is a
different shape from modules 1-5: those are goal-gated (only an agent
pursuing a specific goal triggers the lookup), so their cost is bounded
by however many agents have that goal active; `_update_needs` runs for
every agent every tick unconditionally, so it's the actual per-tick
cost floor rather than a worst-case bound — the real justification for
calling this the start of a "full engine rewrite" track rather than
just another lookup port. Every tunable constant (15 of them) is passed
in via a `NeedsConstants` struct built once per `Population.tick()`
(values never change mid-tick) rather than duplicated as C++ literals:
`resource_grid.cpp`'s existing precedent (season-multiplier tables
embedded directly in C++) was considered and declined for this module
specifically because these particular constants are scattered across
three files (`agents/agent.py`, `agents/population.py`, `settlement/
buildings.py`) with no natural single owner, unlike a self-contained
constants table — duplicating them risks a future retune updating only
the Python side and silently diverging. Verified via 50,000 randomized
input combinations against a hand-written reference Python port of the
exact same branching (0 mismatches to floating-point tolerance 1e-9)
plus the standard cumulative-event-hash engine soak across three
different seeds, all six native modules on vs. off, byte-identical
every time.

**Queued next for R6** (docs/REFACTOR-2026-07.md has the full list):
the pure-math tail of `Population._maybe_predator_attack`'s kill-chance
computation, `FarmGrid`/`FarmPlot` growth-tick math, and building decay/
repair progress math — each will get its own module number and the
same verification discipline. This is explicitly an open-ended,
multi-session effort, not a single-turn deliverable — R6 does not
relax the "byte-identical fallback + hash-soak proof, every increment"
rule just because the eventual scope (the orchestration layer) is
larger than any single module ported so far.

## v0.72.6: native port module 7, new scope — C++ cellular-automata physical substrate (R7)

**Module 7: `Population._maybe_predator_attack`'s kill-chance math.**
Continuing the R6 queue from v0.72.5. The function has two RNG-
consuming rolls (whether an attack happens this tick, then whether it's
lethal) with pure-math kill-chance computation sandwiched between them
— only that middle computation moved to C++; both `rng.random()` calls
stay in Python, in their original order, since this project's
namespaced-RNG determinism-where-natural discipline depends on there
being exactly one RNG stream per tick/agent, not a second uncoordinated
one hiding inside a native call. `has_hospital`/`temperament`/
`resilience` are resolved in Python exactly as before. Verified via
50,000 randomized input combinations (0 mismatches to floating-point
tolerance 1e-12) plus a four-seed cumulative-event-hash soak, all seven
native modules on vs. off, byte-identical every time.

**New scope: R7, cellular-automata physical substrate, C++ from the
start.** User instruction, in the same message that asked to keep
porting: frame the deterministic physical-reality layer (already
defined in this file's design-priorities section — weather, seasons,
resources, ecology, construction, decay) as an explicitly cellular-
automata-style engine, and — the actual behavioral change — write any
*new* code in that domain directly in C++ from day one, not
Python-first-then-ported-later the way every module 1-7 so far has
been. This is scoped narrowly and deliberately: it does NOT touch the
LLM/deterministic split that's been this project's core architecture
since the beginning (town-brain, chronicle, dialogue, culture, beliefs,
dispute resolution, founding, omens/Phase G stay exactly as documented
— "town consciousness, supernatural, etc." in the user's own words,
explicitly called out as unaffected). It also does NOT mandate an
immediate rewrite of existing not-yet-ported Python in the physical
domain (`world/weather.py`, `world/terrain_evolution.py`,
`world/disasters.py`, `world/hydrology.py`, `economy/farms.py`, most of
`settlement/buildings.py`'s decay math) — that backlog keeps moving
under R6's existing incremental, byte-identical-fallback, hash-soak-
verified discipline. R7 is a going-forward rule for new work, layered
on top of R6's existing methodology rather than replacing it: the
"cellular automata" framing is honestly more a naming/scoping
clarification than a mechanics change, since these systems (resource
nodes, herds, tiles, farm plots) already update via local per-cell/
per-entity state and per-tick rules — what's new is the commitment to
implement the *next* disaster type, weather effect, terrain-evolution
rule, or agriculture mechanic as a C++ module from its first line
rather than prototyping it in Python and porting later. See
docs/REFACTOR-2026-07.md, "R7," for the full scope list and the
in-scope/out-of-scope boundary.

## v0.72.7: native port module 8 — FarmGrid.tick, first R7 module

`FarmGrid.tick` (economy/farms.py) was the natural first pick for R7:
it's already the cleanest "cellular automata" shape in the codebase —
a fixed grid of independent cells (farm plots), each updated purely
from its own prior state plus a small set of tick-level inputs (season
growth multiplier, irrigation adjacency), no cross-cell interaction.
Structurally near-identical to `resource_grid_tick` (module 1, shipped
v0.72.0): both are "for each cell, apply a local rule, collect the
cells that need removing" passes. `farm_grid_tick`
(cpp/src/farm_grid.cpp) keeps the same division of labor established
since module 6 — `is_adjacent_to_water` is a `Tile`-object terrain
lookup, so it's resolved in Python before the call and passed in as a
plain per-plot boolean; the native function only does the growth-rate/
rot-tick arithmetic and the GROWING→READY stage transition.

Verified three separate ways, more than most modules so far, because
this one has two return channels (updated plots AND a separate
rotted-positions list) where a subtle A/B harness bug could hide: (1)
20,000 randomized input combinations against a hand-written reference
Python port of the same branching, 0 mismatches; (2) 500 direct
`FarmGrid.tick()` calls on cloned grids — native path on one clone,
pure-Python path (native function temporarily nulled) on a `copy.
deepcopy`'d twin, 5 ticks each, comparing final plot dictionaries
key-by-key — 0 mismatches; (3) the standard cumulative-event-hash
engine soak across four seeds, all eight native modules on vs. off,
byte-identical. (1) proves the C++ function alone is correct against a
reference; (2) proves the actual Python wiring (building `plots_in`,
writing `updated` back onto live `FarmPlot` objects, deleting `rotted`
positions) doesn't introduce a translation bug even when (1) already
passed; (3) proves it holds up inside the real engine loop alongside
every other system. All three matter — a module with two output
channels is exactly the shape where "the pure function is right but the
plumbing around it is wrong" bugs like to hide.

## v0.72.8: native port modules 9-10 — building and vehicle decay

Continuing the R7 queue's "building decay/repair progress math" item.
Split into two functions rather than one, matching the two independent
per-cell collections `Settlement.tick` already iterates separately
(`self.buildings`, `self.vehicles`) with different rules (buildings
have a ruin→reclaim two-stage lifecycle; vehicles just decay to BROKEN,
no removal). `building_decay_tick` (cpp/src/settlement_decay.cpp)
mirrors the STANDING→decay→RUINED→rot→removed pipeline, with the civic-
vs-HUT decay-rate split (the v0.43.2 fix, see the diagnostic history
index above) preserved as two scalar inputs rather than duplicated
branching. `vehicle_decay_tick` mirrors the simpler READY-only decay-
to-BROKEN loop — non-READY vehicles are filtered out in Python before
the call (they're untouched by the pure-Python original too, so there's
nothing for the native side to do with them).

Both keep the same "object-graph resolution stays Python" split as
every module since 6: x/y/kind (needed only for human-readable event
text) never cross into C++, and the native functions return small
result-flag tuples (`removed`/`just_ruined` for buildings, `just_broke`
for vehicles) so Python's event-logging code stays exactly where it
was, just reading a flag instead of re-deriving it from a condition
comparison. Verified via 20,000 (buildings) and 10,000 (vehicles)
randomized input combinations against reference Python ports (0
mismatches each) plus the cumulative-event-hash engine soak across four
seeds at 5000 ticks each — noticeably longer than prior soaks
specifically to give building ruin/reclaim and vehicle breakdown, both
comparatively rare events, more chances to actually occur across the
run. All ten native modules on vs. off, byte-identical every time.

## v0.72.9: native port module 11 — weather blend/threshold math

`compute_weather` (world/weather.py) is the first ported function that
draws from a seeded `random.Random` stream rather than either (a)
having no randomness at all, or (b) receiving an `rng.Random` the
caller already owns and rolls itself (modules 6-7's pattern). This
raised a real design question: does porting this function mean
reproducing CPython's Mersenne Twister seeding and `genrand_res53`
output bit-for-bit in C++? Decided no, on two grounds — first, this
project's standing rule that "Determinism/reproducibility is NOT a
requirement" (explicit, CLAUDE.md workflow rules) means cross-run
reproducibility was never a goal to begin with, only "namespaced RNG
where natural"; second, and more directly relevant to the native-port
discipline specifically, what actually needs to hold is "the native
code path and the pure-Python code path produce identical results,"
not "a from-scratch C++ RNG matches CPython's C RNG implementation." So
the three `rng.uniform(...)` draws (`_tick_rng`, temperature/
precipitation/wind jitter) stay exactly where they were, in Python; only
the deterministic arithmetic that follows them — baseline + jitter,
clamping to [0, 1] for precipitation/wind, the previous-tick EMA blend,
and the snow threshold check — moved into `compute_weather_blend`
(cpp/src/weather.cpp).

Verified three ways given the RNG-boundary split makes this a different
shape from prior modules: (1) 30,000 randomized input combinations
(pre-computed jitter values, baselines, and previous-tick state) against
a hand-written reference Python port of the same arithmetic, 0
mismatches; (2) a direct 20,000-tick `compute_weather()` call sequence
across all twelve months, comparing the native-backed and pure-Python-
backed call chains tick-by-tick (each feeding its own previous
WeatherState forward, so blend-state drift over a long run would show
up), 0 mismatches; (3) the standard cumulative-event-hash engine soak
across four seeds, all eleven native modules on vs. off, byte-identical.
(2) matters specifically because `compute_weather`'s EMA blend makes
each tick's output depend on the previous tick's — a single off-by-
epsilon bug in the native path could compound over thousands of ticks
in a way a single-call equivalence check (1) wouldn't catch, so this
sequence check is the one that actually stresses accumulated drift.

## v0.72.10: native port module 12 — shared bounded-random-walk step

While looking for the next R7 candidate in `world/terrain_evolution.py`
(`tick_climate`) and `world/hydrology.py` (`tick_lakes`'s level nudge),
noticed both share an identical shape with three existing R6-era
functions in `settlement/buildings.py`
(`tick_temperament`/`tick_player_standing`/`tick_relation`): `value =
clamp(value * mean_reversion + jitter [+ an extra additive term], -1,
1)`. Rather than port `tick_climate`'s and `tick_lakes`'s copies in
isolation, wrote one shared `bounded_random_walk_step`
(cpp/src/bounded_random_walk.cpp) and wired it into all five call
sites — the same deduplication instinct that produced `util.py`'s
`clamp`/`namespaced_rng` helpers in v0.69.0, just crossing into C++
this time. `tick_temperament`/`tick_player_standing`/`tick_relation`
are Phase G's literal deterministic implementation (temperament/player-
standing) and cross-settlement institution state (relation) — not
physical substrate, so strictly R6 rather than R7 — but the function
itself is domain-agnostic pure arithmetic, and porting it once instead
of writing three near-identical R6 copies plus two R7 copies was the
obviously better call. Every call site keeps its own RNG draw in
Python, matching every prior module's "RNG stays in Python" rule.

Verified in layers given the fan-out: (1) 30,000 randomized inputs
directly against the pure function's Python reference, 0 mismatches;
(2) for each of the five call sites, a native-vs-Python multi-call
sequence (50-200 successive calls, matching the "value depends on the
previous call's result" shape these functions all have) comparing
final state, 0 mismatches in all five; (3) the standard cumulative-
event-hash engine soak across four seeds, this time at 6000 ticks
(longer than the 4000-5000 used for modules 8-11) specifically so the
monthly-cadence call sites (temperament/player_standing/relation/
climate/lakes all tick once per sim-month) actually fire multiple
times within the soak rather than sitting untested at tick 0. All
twelve native modules on vs. off, byte-identical.

## v0.72.11: native port module 13 — farm-wilt disaster math

Solved the RNG-in-loop design question flagged at the end of v0.72.10
by finding a function that actually fits the established pattern
rather than forcing one that doesn't. `world/terrain_evolution.py`'s
`apply_local_activity`/`maybe_reclaim` were correctly identified as
hard to port: the number of `rng.random()` calls in those loops depends
on which tiles clear a heat threshold or pass a neighbor check first —
a genuinely data-dependent draw count, which breaks the "pre-draw all
the rolls in Python, hand the batch to C++" pattern every module since
11 has used (that pattern only works when the draw count is fixed and
knowable before the loop runs). `world/disasters.py`'s `_wilt_farms`
(shared by `tick_heatwave` and `tick_frost`) doesn't have that problem:
it calls `rng.random()` exactly once per farm plot, every time,
unconditionally, before deciding whether that plot is "hit." Same
shape as `farm_grid_tick`'s per-plot loop (module 8), just with an
extra pre-drawn roll value per plot.

`wilt_farms_tick` (cpp/src/wilt_farms.cpp) takes the per-plot state
(stage/growth/amount/max_yield) plus one pre-drawn roll per plot, in
the same order `farms.plots.items()` would iterate, and returns
per-plot results (updated growth/amount, whether it was hit, whether it
should be removed) plus the total hit count. Python still draws every
`rng.random()` call itself, in the same loop order the original code
used, before handing the whole batch to the native function — so the
RNG stream is byte-identical between paths by construction, not by
coincidence.

Verified three ways given the fixed-shape risk (the wrong number of
rolls, or rolls in the wrong order, would silently desync the RNG
stream from what the rest of the tick expects): (1) 20,000 randomized
input combinations against a hand-written reference Python port, 0
mismatches; (2) 500 direct `_wilt_farms()` calls on cloned `FarmGrid`
instances (native path vs. pure-Python path, same starting grid, same
seeded `random.Random` instance per pair) comparing both the returned
hit count and the final plot dictionary, 0 mismatches; (3) the standard
cumulative-event-hash engine soak across four seeds, all thirteen
native modules on vs. off, byte-identical. `world/terrain_evolution.py`'s
harder-shaped loops and the rest of `world/disasters.py`/`world/
hydrology.py` remain queued, still needing their own design pass.

## v0.72.12: native port module 14 — storm flat-damage sweep

Checked `tick_flood`/`tick_wildfire`/`tick_storm` (world/disasters.py)
for the same "fixed RNG draw count" shape module 13 exploited.
`tick_flood` and `tick_wildfire` don't qualify — both roll a variable
number of `rng.random()` calls depending on which candidate tiles pass
earlier checks (flood candidate selection scans water-adjacent tiles
matching a biome filter; wildfire spread rolls once per FOREST neighbor
of each currently-burning tile, a count that changes as the fire
grows), same "data-dependent draw count" problem terrain_evolution.py's
functions have. `tick_storm` does qualify, in an even simpler way than
`_wilt_farms`: it draws **at most one** `rng.random()` per call, and
even that draw is conditional on a check (`weather.wind >=
STORM_WIND_THRESHOLD`) the caller already has all the information to
evaluate itself, before any loop runs — not a draw count that depends
on iterating anything. Once Python has decided (via that single
possible draw) whether a storm triggered, the remainder of the
function — flat, unconditional damage to every standing building and
every vehicle across every settlement — has no randomness left in it
at all.

`flat_damage_tick` (cpp/src/flat_damage.cpp) is about as simple as a
native port gets: `max(0, condition - damage)` applied to a list, no
branching. Worth documenting anyway because of what it *doesn't* do:
unlike every decay pass ported so far (modules 9-10), it never
transitions a building to RUINED or a vehicle to BROKEN even at zero
condition — the pure-Python original genuinely doesn't do that either,
so the native port had to resist the temptation to "complete" the
mirroring by adding a stage transition that would make it consistent
with `building_decay_tick`/`vehicle_decay_tick` but inconsistent with
what `tick_storm` actually does. A native port's job is to mirror the
source exactly, not to fix what might look like an oversight.

Verified via 10,000 randomized inputs against the trivial reference
(0 mismatches) plus the cumulative-event-hash engine soak across four
seeds, all fourteen native modules on vs. off, byte-identical.
`tick_flood`/`tick_wildfire` and the rest of `world/terrain_
evolution.py`/`world/hydrology.py` remain the queue's genuinely-hard
remainder — they need the "call back into Python's rng.random() from
C++ at the exact point a draw is needed" pattern (viable, but adds
real per-draw Python/C++ crossing overhead and its own risk surface)
rather than the "pre-draw everything, then hand off" pattern every
module since 11 has used successfully. Flagging this as a deliberate
scope boundary, not an oversight: escalate to that pattern only with a
measured need, per this project's own standing evaluation discipline
(see the v0.63.0 full-port audit).

## v0.72.13: native port module 15 — deforestation roll batch, and a correction to the v0.72.11/12 RNG-in-loop assessment

Re-examined `world/terrain_evolution.py`'s `apply_local_activity` after
flagging its deforestation loop as "hard" in v0.72.11/12 without
actually tracing through *why*. On closer inspection, the "data-
dependent draw count" problem that genuinely blocks a port
(`maybe_reclaim`, wildfire spread, flood candidate selection — where
an earlier iteration's outcome changes whether/how a later iteration
rolls) does NOT apply to this specific loop: each candidate tile's
eligibility for a roll depends only on (a) its current heat value and
(b) its current terrain biome — both fully known before the loop
starts, and neither is mutated by this loop until *after* a tile's own
roll resolves (and a tile never re-reads its own post-roll state, so
there's no self-dependency either). Contrast with `maybe_reclaim`,
where a tile's forest-neighbor count can include a neighbor that an
*earlier* iteration in the very same pass just converted from
grassland to forest — that's the real disqualifying shape, and it's
narrower than "this loop rolls dice" alone suggests. The lesson:
"this loop has RNG calls with a variable count" isn't itself
disqualifying — what matters is whether a *later* roll's eligibility
depends on an *earlier* roll's outcome within the same pass. Worth
recording so this distinction doesn't get lost and the remaining queue
doesn't get written off wholesale as "the hard tier" without
individually re-checking each function against it.

`roll_passes_tick` (cpp/src/roll_batch.cpp) is deliberately generic —
"which of these pre-drawn rolls beat their chance" — rather than
baked into a single call site, since the same shape will likely recur
(any future R7 code with independent per-candidate RNG-gated decisions
can reuse it directly, continuing the `util.py`/`bounded_random_walk_
step` dedup precedent). The arithmetic itself (a single `<` comparison)
is trivial — the value is in having one tested building block for the
candidate-selection-then-batch-roll pattern, not in the comparison's
own cost.

Verified via 20,000 randomized inputs against the trivial reference (0
mismatches), 300 direct `apply_local_activity()` A/B runs on synthetic
terrain grids with randomized heat/active-tile state (native path on
one terrain snapshot, pure-Python path — native function temporarily
nulled — on a separate deep-copied snapshot, same seeded RNG per pair),
comparing final terrain biomes, heat dict contents, and emitted events,
0 mismatches. Plus the standard cumulative-event-hash engine soak
across four seeds, all fifteen native modules on vs. off, byte-
identical. `maybe_reclaim`, `apply_climate_drift`'s position sampling,
`tick_flood`, `tick_wildfire`, and the rest of `world/hydrology.py`
remain queued — each should still be individually re-checked against
the "does eligibility depend on other candidates' outcomes within the
same pass" question rather than assumed hard by association.

## v0.72.14: tick_wildfire's spread roll reuses module 15's roll_passes_tick

Continuing the re-trace from v0.72.13: `tick_wildfire`'s spread step
was flagged as "hard" in v0.72.11/12 without individual verification,
grouped in with `maybe_reclaim` on the assumption that "fire spread"
sounds like it should have the same same-pass-dependency problem.
Traced it properly this time. The loop has two parts: own-tile
conversion (an active FOREST tile always burns to GRASSLAND — no RNG
at all) and neighbor-spread rolls (one `rng.random() < WILDFIRE_
SPREAD_CHANCE` per active-tile/FOREST-neighbor pair). The key
question, same as `apply_local_activity`'s: does a later pair's
eligibility depend on an earlier pair's outcome within this same tick?
No — `active_wildfire_tiles` (the set defining which tiles are
"active" and therefore excluded as spread targets) is read via
membership test throughout the loop but never mutated until `|=
frontier` after the loop completes; `frontier` itself (where roll
results land) is never consulted for eligibility either. A shared
neighbor of two active tiles gets rolled twice, independently, exactly
like the pure-Python original — `frontier` being a set only means the
*result* de-duplicates, not the roll count.

No new C++ file — this reuses module 15's `roll_passes_tick` directly,
the payoff of having built that as a generic "which pre-drawn rolls
beat their chance" utility rather than baking it into `apply_local_
activity` alone. The Python-side change splits the original single
combined loop (own-conversion interleaved with spread-checks per tile)
into two passes: an unconditional own-conversion pass over `active_
list` (captured once, since `state.active_wildfire_tiles` must not be
read via `list()` twice and risk two different orderings — Python set
iteration order is stable within a process for identical contents but
there's no reason to rely on that twice when capturing once is trivial
and safer), then a candidate-collection + roll-batch pass. Splitting
doesn't reorder the RNG stream: the original's own-conversion sub-step
draws zero random values, so interleaving it with the roll sub-step or
running it first changes nothing about which `rng.random()` calls
happen or in what order.

Verified via 300 direct `tick_wildfire()` A/B calls on synthetic
terrain with randomized active-fire-tile sets (native path vs.
pure-Python path — native function temporarily nulled — sharing a
seeded RNG per pair), comparing final terrain biomes, the resulting
`active_wildfire_tiles` set, and emitted events, 0 mismatches. Plus the
cumulative-event-hash engine soak across five seeds at 6000 ticks each
(added a fifth seed this pass for extra coverage of wildfire's
comparatively rare weekly-ignition path), byte-identical throughout.
`maybe_reclaim` (confirmed genuine same-pass dependency),
`apply_climate_drift`'s position sampling (fixed draw count but tied
to terrain biome classification not yet exposed to C++), `tick_flood`
(single-event trigger + candidate-index pick, too little batchable
content to be worth porting), and the rest of `world/hydrology.py`
remain the correctly-scoped remainder — each already individually
assessed rather than assumed hard by association, see v0.72.13's entry
for the underlying test.

## v0.73.0: LLM-only conversation feed + on-demand simulation summary

Two explicit user requests handled together with the native-port queue
left where v0.72.14 left it (see CLAUDE.md "Current state (v0.73.0)"
for the "full engine rewrite" framing — R6/R7 continue incrementally,
not addressed as a single change here).

**Event feed filtering.** The user asked that recent events/history
show only core-NPC (LLM) conversations, not deterministic ones. The
events table (`persistence/database.py`) has no per-row field
distinguishing LLM-authored from fallback dialogue — that distinction
only ever existed in *which code path* produced the result
(`SimulationEngine._run_dialogue` vs. `_queue_fallback_dialogue`), and
both funneled into the same `_pending_dialogue_results` queue with no
marker once merged. Adding a DB column was rejected as overkill for a
mechanic that's entirely resolved before logging — instead, `_pending_
dialogue_results` tuples gained a fifth element, `is_llm`, set at the
point of origin (`not used_fallback` from the real `_run_dialogue`
call — this also naturally covers a core pair whose Ollama call itself
timed out/errored inside `CognitionRunner`, which reads the same as a
crowd exchange; `False` unconditionally from `_queue_fallback_
dialogue`). `_apply_pending_dialogue_results` still applies every
exchange's relationship/trust/gossip effects unconditionally (`apply_
dialogue` doesn't know or care about `is_llm`) — only the `self._log`
call that pushes the exchange into the narrative event table is now
gated on `is_llm`. This preserves the mechanic's full richness (the
crowd is still socially alive, fallback dialogue for backpressure/
budget-demoted core pairs still happens) while trimming what a player
actually sees as "conversations" in `/events`/`/history`/the main UI.
Rumor events (`self._log("rumor", ...)`) were deliberately left
unconditional — a rumor is downstream of a conversation and reads as
its own emergent event, not raw transcript text, so hiding a rumor
that originated from fallback dialogue would remove a real piece of
history the player can currently see play out via belief/trust
effects elsewhere.

Verified via a 3000-tick, 3-seed engine run with `llm_enabled=False`
(so every dialogue pair is necessarily fallback-resolved): confirmed
zero `dialogue`/`dialogue_surfaced` rows land in the `events` table
across all three seeds, while `World.dialogue_total` still climbed
normally (136/186/162 across the three seeds) — proof the mechanic
runs unaffected, only the log entry is suppressed.

**On-demand simulation summary.** The user asked for a tab that
provides an LLM-generated summary of the simulation whenever asked.
Modeled closely on `documentary.py` (yearly narrated look-back) but
triggered by the player instead of a calendar boundary: new `llm/
summary.py` (`build_prompt`/`fallback_summary`/`parse_summary`, same
three-function shape). Wiring reuses two existing seams rather than
inventing new ones: `POST /summary/request` enqueues a
`{"type": "request_summary"}` intervention through the same `Broadcaster.
enqueue_intervention`/`drain_interventions` path every other `/intervene/*`
endpoint uses (so it applies on the engine's next tick, never touching
`World` off the tick thread), and the actual generation runs through
the existing `_schedule_llm_job` helper every settlement-level LLM job
already shares (daily call-budget gating, fallback-on-timeout, debug
recording — all for free). The one deliberate deviation from the other
settlement jobs: `_schedule_summary` is NOT gated by `_settlement_job_
backpressured()`. That gate exists specifically to smooth out the
*coincident* burst of several monthly jobs firing on the same calendar
boundary tick (see the "bursts, not just leaks" standing lesson in
CLAUDE.md) — a single user-clicked request isn't part of that cluster,
and silently dropping it would leave the UI's "generating..." spinner
waiting on a job that was never scheduled, with no way for the player
to know why. The daily ceiling (`_consume_llm_budget`, inside `_schedule_
llm_job` itself) still applies, so a spent budget degrades this to the
deterministic fallback exactly like any other job — it just never
vanishes outright.

Result storage: three new `World` fields, `sim_summary_text`/
`sim_summary_tick` (both persisted through `to_dict`/`from_dict`, same
pattern as `dialogue_total`/`rumor_total`) and `sim_summary_pending`
(deliberately NOT persisted — a generation left in-flight at shutdown
has no job left to resolve it after restart, so it must load back
`False`, not stuck `True` forever). `GET /summary` reads these off the
existing broadcast payload (`world.summary()` already runs every tick
for `/state`/the WebSocket feed; it gained a `sim_summary` key) rather
than adding a second path into the engine — the same "don't touch the
engine from a GET handler" discipline `/snapshots/{tick}` already
follows. The result is also logged under a new `sim_summary` event
category (icon 🧭, "mind" filter group, alongside chronicle/
documentary/tradition/invention/belief/omen) so it's visible in the
general event feed and dev console too, not just the dedicated tab.

Verified via a direct `_apply_intervention({"type": "request_summary"})`
call against a 500-tick world with `llm_enabled=False` (fallback
summary generated, `sim_summary_pending` correctly True immediately
after scheduling and False once the fire-and-forget task resolves a
few ticks later, one `sim_summary` event row logged) and a `World.
to_dict`/`from_dict` round-trip confirming `sim_summary_text`/`_tick`
survive a save/load cycle while `sim_summary_pending` correctly resets
to `False`.

## v0.73.1: climate_drift native port (module 16) + R8 scoping pass

**Native port.** Closes the item flagged at the end of v0.72.14:
`apply_climate_drift`'s biome-step mutation needed `classify_with_
bias`/`BIOME_ORDER` (world/terrain.py) exposed to C++, which no prior
module had done because `Biome` is a Python `str, Enum` and pybind11
can't pass an enum across the boundary directly. Resolved the same way
this codebase always resolves enum/object friction at the native
boundary — convert on the Python side, hand C++ only plain data —
except this is the first case where the *thing being converted* is the
enum itself rather than an object attribute filtered away before the
call (contrast `TerrainMaterialIndex`, which only ever sees `(x, y)`
pairs because the `tile.biome in MATERIAL_BIOMES` check already
happened in Python). Both `classify_biome_index` (mirrors `classify_
with_bias`) and `climate_drift_batch` (the one-step-toward-target
arithmetic) take/return a plain `int` index into `BIOME_ORDER`;
Python does `BIOME_ORDER.index(tile.biome)` going in and `BIOME_
ORDER[i]` coming out.

The raw-function randomized-equivalence check (50,000 inputs across
both `classify_biome_index` and `climate_drift_batch`) passed clean on
the first attempt — the arithmetic itself was never the risky part.
The direct A/B run of the actual `apply_climate_drift` wrapper
function (500 trials on synthetic 40x40 terrain) is what caught a real
bug: a consistent off-by-one in the reported `changed` tile count
every time the two paths disagreed, with the underlying terrain
biomes matching in every case. Root cause: `apply_climate_drift`
samples `sample_size` positions via `rng.randrange(width)`/`(height)`
*with replacement* — nothing dedupes the draws — so across ~48 draws
against a map with a few thousand eligible tiles, a repeat `(x, y)`
draw within the same call is common (birthday-paradox math, not rare).
The pure-Python original processes samples strictly in order and
mutates `terrain` in place as it goes, so a duplicate's second
occurrence naturally reads the tile's *already-stepped* biome from the
first occurrence and can step it again. The first implementation
attempt collected every sampled tile's `(elevation, cur_biome_idx)`
from pre-loop state and handed the whole batch to `climate_drift_
batch` in one call — correct for `classify_biome_index`/`climate_
drift_batch` themselves, but wrong for the *sequence*, since it
computed every entry from the original unstepped biome regardless of
an earlier duplicate in the same batch. This is the same disqualifying
shape as `maybe_reclaim` (a later candidate's outcome depends on an
earlier candidate's outcome within the same pass) — the twist is that
`apply_climate_drift`'s RNG-draw *count* is fixed (unlike `maybe_
reclaim`'s), so the earlier "fixed draw count = safe to pre-draw and
batch" heuristic from v0.72.11 wasn't sufficient on its own here; a
fixed draw count only guarantees the RNG stream is safe to pre-draw,
not that the *tiles being drawn* are dependency-free once duplicates
enter the picture. Fix: call `climate_drift_batch` once per sample
(single-entry list) inside the Python loop, always reading `terrain`'s
current state for that iteration — this restores read-your-own-writes
order exactly like the pure-Python original while still doing the
per-tile arithmetic in C++. Re-ran the same 500-trial A/B suite after
the fix: 0 mismatches. This is the second time in the native-port
queue a same-pass dependency wasn't visible from reading the code
alone (the first was the original `maybe_reclaim` finding) and only
surfaced via the direct wrapper-function A/B step — confirms that step
of the three-layer verification methodology is catching real bugs the
raw-function randomized check structurally cannot, and should never be
skipped as "redundant" for a module that touches any kind of stateful
sampling loop. Verified via 50,000 randomized inputs (raw functions),
500 direct `apply_climate_drift()` A/B runs (0 mismatches post-fix),
and the cumulative-event-hash engine soak across four seeds at 6000
ticks each, all sixteen native modules on vs. off, byte-identical.

**R8 scoping.** The user's standing "full engine rewrite... in C++"
directive (first raised alongside the C++-port directive that became
R5/R6, reaffirmed this session) is broad enough to mean several
different things in practice, and this project's own workflow rules
say to design an open-ended/risky change before executing it — doubly
true with no automated test suite as a safety net. Rather than guess
which reading and start moving code, docs/REFACTOR-2026-07.md's new
"R8" section lays out three readings (finish the existing R6/R7
opportunistic queue; port the object graph — `Agent`/`Settlement`/
`Population`/terrain — into C++ classes behind Python handles;
rewrite everything except the standing SQLite/asyncio/FastAPI
carve-out) with an explicit recommendation (reading 2, if the user
wants to commit to "full engine rewrite" as a real category beyond
finishing the existing queue) and an explicit non-recommendation
(reading 3 — trades away the plain-Python hackability the LLM/
emergence-design side of this project's entire session-to-session
workflow depends on, for tick-time headroom the project has no
measured need for; the same tension the original v0.63.0 audit and
v0.72.0's pre-port flag both already identified). No object-graph code
has moved — this is a scoping document only, matching the same
"flag before proceeding on an open-ended full-port directive" posture
v0.72.0 took for the original C++/llama.cpp pivot.

## v0.73.2: maybe_reclaim (17) + SimClock.advance (18, first R8 slice)

User confirmed, when asked, that both R8 readings should proceed
together: finish the R6/R7 opportunistic queue AND begin the object-
graph/engine-tick-loop track ("reading 2").

**Module 17 — `maybe_reclaim`.** Every prior module either had no
same-pass dependency (safe to pre-draw all rolls and batch) or was
explicitly left unported because it did (`maybe_reclaim`, confirmed
since v0.72.11). Rather than leave it unported indefinitely, this
version ports it using a different design: instead of pre-drawing
rolls in Python, the native function takes `rng.random` itself as a
bound Python callable and calls it inline, once per conditional roll,
in the exact same order/count the pure-Python loop would. This
preserves the same-pass dependency exactly (the C++ loop mutates its
own local biome buffer as it scans row-major, so a later tile in the
same call correctly sees an earlier tile's conversion) while still
moving the actual per-tile cost (neighbor counting, biome-code
branching) into C++. The `_is_developed`/`heat`-membership check is
precomputed once in Python before the call (it doesn't change during
the loop, so no dependency risk there) and passed as a flat bool
array. Verified via 500 direct `maybe_reclaim()` A/B runs on synthetic
terrain deliberately built with mixed grassland/forest patches (not
uniform biome, to actually exercise multi-neighbor-count scenarios
and same-pass conversions within a single call) — 0 mismatches — plus
confirming via a 20,000-tick standalone run that `terrain_reclaimed`
fires at a realistic rate (46 times) so the soak's zero-mismatch
result reflects a mechanic that's genuinely exercised, not dormant.

Cost note, for anyone extending this pattern: a callback-per-roll
design has real per-call Python-boundary overhead compared to a
batched call, so it's slower per-roll than modules that pre-draw and
batch (13-16). Not a concern here since `maybe_reclaim` is a once-a-
week job over a bounded number of grassland tiles, nowhere near the
same cost class as the always-on per-tick loops modules 6/11/18 target
— but this design shouldn't be reached for reflexively where pre-
drawing is actually available; it's specifically for the same-pass-
dependency case pre-drawing can't handle.

**Module 18 — `SimClock.advance()`, first R8 slice.** The R8 scoping
doc (v0.73.1) recommended starting the object-graph/engine-tick track
with the least-entangled piece and building confidence in the pattern
before anything larger moves. `SimClock` is a strong first candidate
independent of that recommendation: it has no references to any other
mutable object (`Agent`, `Settlement`, terrain — nothing), its state
is two integers effectively (`tick_count` plus the `Config` it was
constructed with, which supplies the calendar *shape*, not further
mutable state), and `advance()` is the single highest call-frequency
function in the entire codebase (unconditionally, exactly once per
tick, for the whole life of a world — every other ported function so
far is conditional on backpressure, cadence gates, or per-agent/per-
tile eligibility). Ported as a pure function taking the calendar shape
unpacked into plain ints/vectors (not the `Config` object) and the
current `tick_count`, returning the new `tick_count` plus which of the
five boundary flags were crossed — `SimClock` the dataclass, its other
derived properties (`day_of_month`, `season`, `clock_string`, etc.),
and its `to_dict`/`from_dict` persistence are all untouched; only the
one method that runs every tick moved. Verified via a 200,000-tick
sequential lockstep A/B — two `SimClock` instances (one forced to the
Python fallback, one native) advanced together tick-by-tick, checking
`tick_count` and the returned event list matched after every single
call — deliberately the longest and most sequentially-strict
verification run in this entire native-port history, appropriate
given this function's call frequency and the fact that any drift
would compound silently for the rest of a run (unlike a once-a-week
job, a one-tick calendar discrepancy here would be wrong forever
after). 0 mismatches across the full run, final dates identical
(`November 14, Year 6` both paths).

Both verified together via a 5-seed, 8000-tick cumulative-event-hash
engine soak (all eighteen native modules on vs. off, byte-identical)
and a live `hearthmind.server` smoke test — confirmed `terrain_
reclaimed` events fire correctly and reach the browser's event feed
during a real running server, not just the offline harness.

**R8 status after this version**: reading 2 (port the object graph
behind Python handles) is now confirmed direction, with one real slice
shipped (`SimClock.advance()`) proving the pattern works end-to-end
(build, dispatch, fallback, verify, soak) for a piece of the engine
tick loop itself, not just a physical-substrate system. The much
larger remaining scope — `Agent`/`Settlement`/`Population`/the terrain
grid itself — has not started; each needs its own design pass given
the cross-references between them (an `Agent` touches `Population`,
`Settlement`, and belief/relationship state directly, unlike the
terrain grid or `SimClock`), and per the R8 doc's own risk framing,
those need the heavier full-state-diffing verification harness
(beyond the event-hash soak) built before the first line of any of
them moves. `docs/REFACTOR-2026-07.md`'s R8 section will track this as
a live, multi-session queue the same way R5/R6/R7 do.

## v0.73.3: build flags (-O3/-march=native/-mtune=native); hydrology.py closed out

**Build flags.** User asked for `-O4` and `-march`/`-mtune=native`.
GCC and Clang both cap standard optimization at `-O3` — there is no
`-O4` in either compiler's flag set — so `-O3` (the actual maximum)
was used instead. `-Ofast` (which goes beyond `-O3` by additionally
enabling `-ffast-math` and relaxed standards compliance) was
considered and explicitly declined: `-ffast-math` permits floating-
point reassociation and other transformations that can change rounding
behavior, which risks silently breaking the byte-identical-vs-Python
guarantee every native module in this codebase has been verified
against since v0.72.0 — not worth the tradeoff for a project whose
entire native-port discipline is "provably equivalent, not just
probably faster." `-march=native`/`-mtune=native` were added as
requested; both are genuinely safe here because `hearthmind._native`
is always compiled locally on the exact machine that will run it
(`scripts/run.sh` / `pip install -e .`'s build-isolation step) rather
than distributed as a prebuilt wheel to be run on unknown hardware — a
`-march=native` binary built on one CPU and copied to a different one
can crash on an unrecognized instruction, which is the standard reason
this flag is avoided for portable/distributed builds; flagged
explicitly in `setup.py`'s comment so a future move toward shipping
prebuilt wheels doesn't inherit this silently. Guarded to non-Windows
(`sys.platform != "win32"`) since MSVC uses `/O2`-style flag syntax,
not GCC/Clang's `-O3`. Re-verified via the standard 4-seed, 6000-tick
cumulative-event-hash soak after a clean rebuild with the new flags:
hashes identical to every prior `-O2` soak run for the same seeds —
the more aggressive codegen doesn't change any observable simulation
output, as expected (no `-ffast-math`, so IEEE-754 semantics are
unchanged; `-march=native` only changes which instructions implement
the same semantics, not the semantics themselves).

**`world/hydrology.py` closed out.** The last item in the R7
opportunistic-port queue marked "not yet traced." Both remaining
un-ported functions in that file — `generate_rivers` (carves river
tiles via `rng.shuffle` + BFS pathing) and `identify_lakes` (flood-
fills connected water tiles into `LakeState` entries) — are called
exactly twice in the entire codebase: once from `World.create_new`
(new-world generation) and once from `World.from_dict`'s legacy-
snapshot migration path (backfilling a pre-hydrology-pass save). Both
are creation-time-only, never invoked from the tick loop — porting
either would buy literally zero per-tick cost reduction, the only
thing this native-port track exists to improve, regardless of how
tractable their RNG shape might otherwise be. `tick_lakes` (the one
function in this file that DOES run every tick) was already ported in
module 12 (`bounded_random_walk_step`, shared with three other
monthly-nudge functions). This closes the R7 queue in full: `apply_
local_activity` (15), `tick_wildfire`'s spread (reuses 15),
`apply_climate_drift` (16), `maybe_reclaim` (17) are ported; `tick_
flood` and now `generate_rivers`/`identify_lakes` are confirmed
correctly out of scope (too little batchable content / creation-only,
respectively) rather than simply unaddressed. Everything queued next
in native-port work is R8 (object-graph + engine-tick-loop), not R7.

## v0.74.0: bridges (real water-crossing pathing) + R8 full-state verification harness

**Bridges.** CLAUDE.md's "Known architectural gaps" section had
carried "True water transport" as an open item since v0.66.0's RAFT
shipped as a fishing-yield bonus only, explicitly documented as NOT
granting crossing pathing, with the note that a real follow-up "needs
its own pathing-system pass, not a bolt-on." Two research passes (one
on the pathing/building system, one on terrain-grid call sites for the
parallel R8 request) confirmed the shape of that pass: `Population.
_is_walkable` is the single passability gate every movement function
funnels through, and it already has a precedent for a second
passability condition beyond raw biome membership — `mountain_
unlocked` (era-gated MOUNTAIN access, v0.68.0) — threaded as a
parameter through `_is_walkable`'s six call sites rather than mutating
`Tile`/`terrain` itself. Bridges follow the identical shape: a new
`bridge_tiles: frozenset[tuple[int,int]]` parameter, checked second
(after biome membership fails) so the common non-bridge case pays
nothing extra beyond one boolean short-circuit.

Deliberately rejected: mutating `Tile.biome` on a bridge's water tiles
directly (e.g. to a hypothetical `Biome.BRIDGE_DECK`). This would have
been simpler to check but breaks every piece of code that treats
DEEP_WATER/SHALLOW_WATER membership as ground truth for hydrology
(`identify_lakes`/`tick_lakes` iterate terrain looking for water
biomes — a bridge-converted tile would silently vanish from a lake's
tracked area) and disasters (`tick_flood` targets water-adjacent
tiles). Keeping biome untouched and layering passability as a read-
time policy (exactly like the mountain-unlock precedent) means bridges
have zero interaction with any other system that reads `Tile.biome` —
a lake can still rise/recede under a bridge, a flood can still submerge
the water it crosses, none of that logic needed to change or even know
bridges exist.

**Site-finding**: `_find_bridge_span` is a bounded (`BRIDGE_MAX_
SPAN=6`) multi-source BFS starting from a shore tile's immediate water
neighbors, expanding through water tiles only, until it reaches a
walkable tile NOT already in the origin's land-reachable component
(`Population._reachable_tiles`, reused rather than reimplemented) — a
peninsula that already loops back to the same landmass by another
route correctly produces no bridge, since bridging it wouldn't connect
anything new. Uniform-cost BFS naturally returns the shortest crossing
first. This function is only ever invoked from a colocation-gated,
low-probability-rolled founding check (`_maybe_start_bridge`, mirrors
`_maybe_start_vehicle`'s exact structure — RAFT's own water-adjacency
gate reused as the pre-filter before the more expensive BFS ever
runs), so its cost (a full BFS plus one `_reachable_tiles` flood fill)
is acceptable despite not being cheap per-call.

**Founding without water colocation**: agents can't stand on water, so
bridges can't reuse the standard `_choose_build_site`/`_maybe_start_
construction` path (which requires 2+ agents physically on the chosen
tile and rejects non-walkable candidates outright). Modeled instead
exactly like vehicle founding (`_maybe_start_vehicle`): a colocated,
mature, healthy pair standing on a walkable shore tile founds the
bridge AT their own tile (`Building.x/y` = the land anchor, never
water) with `bridge_span` recording the water tiles it will come to
cover. This means `_advance_construction`'s existing generic per-kind-
agnostic progress logic, `under_construction_positions`' WANDER-
attractor mechanism, and standing-building decay/ruin/repair all work
completely unchanged for BRIDGE — nothing about the construction
lifecycle needed to know a bridge is different from a hut.

**Shared physical infrastructure, not settlement-private**: bridges
pool across every settlement into one global passability set
(`_bridge_tiles_from_settlements`, computed once per `Population.
tick()` and reused for every agent's movement that tick, plus
`SimulationEngine._choose_fission_site`'s reachability check) — same
"any agent can use it regardless of which settlement built it" shape
`RoadNetwork` already has for roads. A per-settlement bridge_tiles
dict was considered and rejected: bridges are physical structures on
the shared map, gatekeeping them by settlement ownership would be an
arbitrary restriction with no analog anywhere else in the codebase
(roads, farms, and terrain itself are all map-shared, not settlement-
private).

Verified via: unit tests of `_find_bridge_span` on synthetic terrain
(exact span found across a narrow strait; `None` correctly returned
for a gap wider than `BRIDGE_MAX_SPAN`; `None` correctly returned when
the two shores were already land-connected by another route, proving
the "don't bridge an already-reachable loop" check works); a direct
`_is_walkable`/`_step_toward` test confirming a bridge tile is walkable
only when `bridge_tiles` is passed, not by default; a full engine test
(`SimulationEngine._tick_once()`, not the isolated pathing functions)
confirming an agent with a `travel_target` on the far shore of a
STANDING bridge actually arrives there; `Building.to_dict`/`from_dict`
round-trip including legacy-snapshot backward compatibility (missing
`bridge_span` key defaults to the empty tuple, so old saves load fine);
and a 6000-tick, 3-seed regression soak confirming zero behavior
change in a world where no bridge is ever founded (the overwhelmingly
common case, since `BRIDGE_CHANCE_PER_TICK` is deliberately low and
requires a water-adjacent colocated pair).

**R8 full-state verification harness.** The v0.73.1 R8 scoping pass
flagged that "the heavier full-state-diffing verification harness ...
is also still unbuilt" as a prerequisite before the terrain-grid slice
(the recommended next R8 target) could safely begin — the existing
cumulative-event-hash soak proves narrated *consequences* match
native-vs-Python, but a state field with no corresponding life event
(a farm plot's raw sub-threshold `growth` float, an agent's `energy`
between whatever thresholds trigger events) could theoretically drift
without the event-hash soak ever noticing. `scripts/verify_native_
soak.py` closes that gap: it hashes the complete `World.to_dict()`
snapshot every single tick (not just accumulated events) across a
configurable seed list, toggling every native module's fallback flag
in one coordinated pass via a `(module, attribute)` list rather than
requiring a bespoke toggle dance per module the way ad-hoc soak scripts
in this session's own transcript needed. Deliberately committed to the
repo (previous soaks were one-off shell invocations, never saved) so
future sessions don't re-derive the same harness from scratch.
Sanity-checked before trusting its result: ran it against two
different seeds' own native-mode hash sequences to confirm they
diverge (they do — the harness isn't vacuously reporting "match" no
matter what). All eighteen native modules shipped through v0.73.3 pass
full per-tick state equality across a 6000-tick, 4-seed run — strictly
stronger evidence than any single soak run in this native-port
history's earlier entries, since prior soaks only ever compared the
event stream. Terrain-grid porting itself has not started this
version — this is purely the prerequisite tooling the R8 doc called
for, in the order the doc specified.

## v0.74.1: terrain grid native storage (R8 slice 2)

Explicit user directive to "start" the terrain-grid port after
confirming the R8 direction. The terrain-grid research pass (this
session, earlier) had already mapped the exact risk: ~63 subscript
sites, ~14 mutation sites (`terrain[y][x] = Tile(...)`), ~21 iteration
sites, and 3 serialization paths across `world/*.py`/`agents/
population.py`/`settlement/buildings.py`/`interface/*.py` all depend
on `World.terrain` behaving like `list[list[Tile]]`. A naive swap to
some other representation would need every one of those call sites
individually verified. The `SimClock.advance()` precedent (module 18)
didn't have this problem because it has zero references to any other
mutable object — the terrain grid's problem is entirely about surface
area, not entanglement.

**Solved via a compatibility shim, not a call-site migration.**
`TerrainGrid`/`TerrainRow` (world/terrain.py) implement Python's
`__getitem__`/`__setitem__`/`__len__`/`__iter__` protocol identically
to what a nested list already provides — `terrain[y][x]` returns a
freshly-materialized `Tile` from the backing store, `terrain[y][x] =
Tile(...)` writes into it, `len(terrain)` returns height,
`len(terrain[0])` (via the row proxy) returns width, `for row in
terrain: for tile in row` iterates correctly. Because every one of
those ~98 call sites only ever uses this protocol (confirmed by the
research pass, not assumed), swapping `World.terrain`'s actual type
required editing exactly two call sites end-to-end
(`World.create_new`, `World.from_dict`) — not the ~98 that touch
terrain. This is the "compatibility shim preserving existing indexing
syntax" option the v0.73.1 scoping doc named as one of two viable
paths (the other being "a more surgical opt-in path"), now proven out
in practice rather than left as a hypothetical.

**Storage design**: elevation as a flat `vector<double>`, biome as a
flat `vector<int>` indexed into `tuple(Biome)` — Python's own enum
declaration order, which (unlike `terrain_evolution.py`'s `BIOME_
ORDER`) includes all 9 members, RIVER included, since this is the
general-purpose storage layer and must be able to represent every
biome a tile can ever hold, not just the 8 elevation-classified ones
climate drift cares about. `Tile` objects are constructed fresh on
every read, never cached — the same freshness every mutation site
already got from constructing a brand-new immutable `Tile(...)` before
this change, so no code anywhere could have been relying on tile
object identity surviving a mutation (nothing in the codebase does;
confirmed by the same research pass).

**What stayed untouched by design**: `generate_terrain()` itself still
returns a plain nested list — its diamond-square midpoint-displacement
algorithm is easiest to write against ordinary Python lists, and
there's no reason to force it into the wrapper's protocol when the
wrapping happens immediately after it returns. `to_dict()`'s terrain
serialization (`[[tile.to_dict() for tile in row] for row in self.
terrain]`) needed literally zero changes — it was already written
against the iteration protocol, which `TerrainGrid` satisfies. Every
downstream consumer of `terrain` in `world/terrain_evolution.py`,
`world/disasters.py`, `world/hydrology.py`, `agents/population.py`,
and `settlement/buildings.py` is similarly untouched.

Verified in four layers, the most of any module in this native-port
history given the size of the surface area being trusted: (1)
randomized read/iteration/mutation equivalence — 500 random `(x, y,
elevation, biome)` writes applied to both a native-backed `TerrainGrid`
and a parallel plain nested list, compared after every write, 0
mismatches; (2) a full engine lifecycle test — `SimulationEngine.
load_or_create` → 3000 ticks → `save_snapshot` → `load_latest_
snapshot` → full terrain diff between the live and reloaded worlds, 0
mismatches, confirming the compiled storage survives the actual
SQLite/JSON persistence path, not just an in-memory comparison; (3) a
live `hearthmind.server` smoke test plus a browser screenshot
confirming `/terrain`/`/state` serialize correctly and the map renders
identically — the swap is completely invisible to the frontend, as it
should be; (4) `scripts/verify_native_soak.py` (the harness built in
v0.74.0 specifically to catch exactly this class of change) extended
with this module's toggle and re-run across 4 seeds at 6000 ticks
each — all nineteen native modules now shipped pass full per-tick
`World.to_dict()` equality, the strongest evidence bar this project's
verification discipline has established.

**Remaining R8 scope, still unstarted**: `Agent`/`Settlement`/
`Population` themselves. Unlike `SimClock` and the terrain grid — both
chosen specifically because they have zero references to any other
mutable object — these three are genuinely entangled with each other
(an `Agent` touches `Population`, `Settlement`, and belief/relationship
state directly; `Settlement` holds `Building`/`Vehicle` lists an
`Agent` reads and mutates). The "wrap in a compatibility shim" trick
that made this version's port low-risk doesn't obviously generalize to
an object graph with real cross-references the way it did for a single
independent grid — that's genuinely the next design question, not
assumed solvable the same way.

## v0.74.2: native-port design pass — no measured-need candidate remains

Response to a generic "continue" following v0.74.1's terrain-grid
port. Rather than force a next code change, traced whether the queued
R8 item (`Agent`/`Settlement`/`Population`) or anything else was
actually tractable/justified right now. Full three-part finding lives
in docs/REFACTOR-2026-07.md's R8 section: (1) Agent's storage shape
(many variable-size per-agent containers, not `Tile`'s two dense
scalars) doesn't fit the compatibility-shim pattern that made
`SimClock`/the terrain grid safe — the pattern that DOES apply to
Agent's hot per-tick scalar math is already in use (module 6,
`_update_needs`: extract primitives, compute in C++, write back, no
storage change); (2) every previously-flagged O(N²) hotspot in the
tick loop is already resolved (module 4's `AgentPositionIndex`; an
algorithmic, not native, fix for the old rival scan); (3) conclusion —
no measured-need candidate remains anywhere in the codebase. This is
a direct application of the standing "escalate only with a measured
need" rule that's governed every module since v0.72.0, now applied to
the meta-question of whether to keep escalating at all. Recommends the
native-port track be treated as complete for now, revisited only if a
real measured tick-time problem shows up at larger population/map
scale — the same escalation ladder (spatial buckets → numpy → PyPy →
C/C++) the original v0.63.0 audit specified, which this project
already jumped past on explicit user directive. No code changed this
version; asked the user how to proceed given the finding rather than
guessing.

## v0.74.3: AgentTable — Agent scalar-field storage primitive (R8 slice 3, staged)

User explicitly chose to pursue the Agent/Settlement/Population port
despite the v0.74.2 finding of no measured performance need — for
architectural completeness, accepting the higher risk knowingly. This
version's job was to make that risk concrete rather than estimated,
and to ship whatever slice of it can be done at the same safety bar
every other native module here has met.

**Scoping first.** A dedicated research pass counted real call sites
rather than guessing: `Agent`'s 12 scalar fields are touched roughly
700 times in `agents/population.py` alone (plus ~150 more across
`engine.py`/`buildings.py`/`llm/*.py`/`interface/*.py`), almost always
in the same expression as one of the 6 variable-size per-agent
containers (`relationships`, `trust`, `inventory`, `memories`,
`skills`, `traits`) that cannot be flattened into a fixed-schema array
— a dict whose size varies per agent and changes every tick has no
struct-of-arrays representation. This is categorically different from
the terrain port's ~60 sites, which were uniformly `terrain[y][x]`
indexing with no adjacent business logic to worry about. The research
also settled three prerequisite design questions cheaply: agent ids
are monotonic and never reused (a slot-based store doesn't need
id-recycling logic), nothing in the codebase holds a raw `Agent`
object reference across a tick boundary (every cross-tick reference is
by `.id`, re-resolved via a freshly-built `by_id` dict each time —
confirmed by grep, not assumed), and `POPULATION_CAP=400` means a
naive swap-with-last removal on every death is entirely affordable,
no free-list or generational-index scheme needed.

**What shipped: the storage primitive only.** `cpp/src/agent_table.cpp`
— `AgentTable`, a true structure-of-arrays (12 parallel `std::vector`s,
one per scalar field, not a `std::vector` of a 12-field struct) with
`append` (returns the new slot index), `remove` (swap-with-last;
returns which agent id — if any — now occupies the freed slot, so the
Python-side id→slot map can be kept in sync without the C++ side
needing to know anything about Python id semantics), and per-field
get/set. Verified via a 20,000-operation randomized fuzz test —
append/remove/mutate operations applied in the same sequence to both
`AgentTable` and a parallel pure-Python reference list of small
`RefSlot` objects, cross-checked every 500 operations and once at the
end, 0 mismatches across a final table size of ~5,000 net-appended
agents — plus explicit tests confirming out-of-range slot access
raises `IndexError` rather than reading/writing outside the backing
vectors.

**What deliberately did NOT ship: wiring it into `Population.agents`.**
This is the actual risk the scoping pass identified, and rushing it
into the same change as the storage primitive would repeat exactly the
mistake the terrain port's own research pass was designed to prevent —
verifying a new primitive in isolation is not the same as verifying
~700 call sites still behave identically once real `Agent` instances
are replaced with a compatibility-shim wrapper backed by that
primitive. The honest next-session scope: build an `Agent`-shaped
wrapper class whose scalar-field properties route through `AgentTable`
by slot index (mirroring `TerrainRow`'s role for terrain) while the
six dict/list fields stay ordinary Python attributes on a parallel
object; maintain an id→slot map updated from `AgentTable.remove`'s
result; make `Population.agents` a thin sequence view over the table
instead of a plain `list[Agent]`; and verify via `scripts/verify_
native_soak.py` (already built in v0.74.0, just needs this module's
toggle registered) across a real multi-thousand-tick run — deliberately
MORE verification than SimClock or the terrain grid needed, given this
slice's much larger risk surface, not the same amount reused by
habit.

## v0.75.0: AgentTable wired into live Population.agents (R8 slice 3 wire-in)

Context: explicit user directive — "full C++ engine, don't break the
game at all." Those two constraints are the whole design brief. A
literal 100% C++ rewrite isn't reachable (the LLM layer + asyncio/
FastAPI/SQLite/LLM-client stay Python by the v0.72.5 directive, ~1/3 of
the code), and "don't break at all" rules out a big-bang engine (no
per-slice ground truth, no automated test net). What's left is exactly
the discipline every native module here already uses: incremental
slices, each verified byte-identical against the current Python as
ground truth before the Python is removed, extension always optional.
This version does the first object-graph slice the v0.74.3 `AgentTable`
primitive was built for.

The v0.74.3 note (and the v0.74.2 scoping before it) had framed this as
large and dangerous — "~700 call sites," a per-object `_slot` with
fragile central fixup, staleness hazards. A pre-implementation grep
pass changed that estimate materially, and the final design is
smaller and safer than feared:

- **The ~700 are reads/writes through `agent.<field>`, not edits.**
  Converting `Agent` from `@dataclass` to a hand-written class whose 12
  scalar fields are `@property` accessors leaves every one of those
  sites working verbatim. The scalar *write* surface is ~51 sites and
  there are exactly **3** `Agent(...)` construction sites +
  `Agent.from_dict`, all in population.py. Landmine check (all clear):
  no deepcopy/pickle of agents, no `dataclasses.fields/asdict/replace`
  on `Agent`, no value-equality/`in`-by-value reliance (every
  comparison is `.id ==`), no `__dict__`/`setattr`/`getattr` dynamic
  access, timeline replay reconstructs from snapshots (holds no live
  `Agent`). So the dataclass→class conversion touches nothing but the
  class itself.

- **Root cause the id-keyed store fixes.** The native `AgentTable` uses
  swap-with-last removal, which moves a surviving agent's data into a
  freed slot — so any Python handle caching a slot could silently read
  the wrong agent after an unrelated death. Rather than guard ~700
  sites against that, `agents/agent_store.py`'s `AgentStore` keys its
  entire public API by agent **id** and resolves id→slot internally,
  updating that single map from the table's `remove` result
  (`moved`/`moved_agent_id`). Python never sees a slot; the staleness
  bug class is designed out at the API boundary. Agent ids are
  monotonic and never reused, so id is a stable lifetime key.
  `self.agents` stays an ordered `list[Agent]`, so iteration order is
  fully decoupled from table slot order — a death reordering slots
  reorders nothing a caller sees.

Wiring: `Population.__post_init__` builds the store (only when the
native extension is present) and calls `agent._attach(store)` on every
agent — this covers both construction paths, since `spawn_initial` and
`from_dict` both hand a finished `agents` list to `cls(agents=…)`.
Three one-line hooks handle the only three `self.agents` mutation
points: `_adopt` each newborn before `extend`, each migrant before
`append`, and `store.remove(id)` for every `dying_ids` member right
after `self.agents = survivors` (verified nothing reads a dead agent's
scalar after that point). `state`/`goal` cross the boundary as int
codes via `STATE_TO_CODE`/`GOAL_TO_CODE` in agent.py (kept next to the
enums, matching cpp/src/agent_table.cpp's header — never renumber an
existing code or a resumed native world misreads saved scalars).

Fallback: no native extension → `Population` builds no store →
`agent._attach(None)` is a no-op → scalars stay in the `_x`/… locals,
byte-identical to the pre-0.75.0 dataclass. This path is a first-class
verified target, not an afterthought.

Verification (the actual guarantee behind "don't break at all," since
there's no automated suite): (1) `scripts/verify_native_soak.py`'s new
`agent_store` toggle — full `World.to_dict()` hashed every tick, native
(AgentTable) vs fallback (detached), byte-identical across seeds at
2,000 ticks and a 12,000-tick/3-seed run long enough to span births
(maturity is 4,000 ticks, so shorter runs never exercise the `add`
hook); (2) a direct death + swap-with-last test — kill agents 2/5/7 of
10 via `_apply_deaths`, then mutate survivors and confirm native ≡
fallback `to_dict`, proving the id→slot remap keeps every survivor
pointed at its own row after the table reindexes; (3) a
save→`from_dict`→reload round-trip proving the store rebuilds
identically on load and is live afterward. A 2,000-tick match alone
would have been misleading (no births/deaths in that window) — the
death path is proven by (2) and the birth path by the 12k run.

Not done here (the honest boundary): the agent tick **logic** —
`population.py`'s method bodies — still runs in Python; it just reads
and writes the 12 scalars through the C++ store now. Moving those
method bodies into C++ over the table, one method-group at a time with
per-slice Python ground truth, is the next leg toward the full engine.
The store makes that possible (the data already lives in C++); it
doesn't do it.
