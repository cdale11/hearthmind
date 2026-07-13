# Hearthmind — Project Memory

Persistent, always-running town simulation. Python stdlib-only, SQLite
persistence, optional local LLM via Ollama. Repo `cdale11/hearthmind`,
branch `claude/hearthmind-overview-5bekay`.

## Response format (chat)

- Minimum tokens. No restating goals/architecture/history already in this
  file or prior chat.
- Explain only non-obvious decisions.
- Progress reports: **Changes / Tests / Known Issues / Next Milestone**
  only — no preamble, no recap.
- Ask short, specific design questions when direction is ambiguous;
  don't guess on product decisions.

## Hardware target

8GB RAM + zram swap, CPU-only inference. Default model `qwen3.5:2b` —
set by explicit user instruction (confirmed available/pulled on their
machine, superseding this file's earlier note that "Qwen3.5" didn't
exist — take the user's live environment as ground truth over training
data on naming/availability of fast-moving model releases), leaving
substantial headroom for the simulation process itself. `qwen3:4b` is
the documented size-up path if 2B proves too weak for coherent
town-brain/dialogue output — size up and report back, don't silently
guess. Qwen3.x is a hybrid "thinking" model; every call disables that
(`OllamaClient` sends `"think": false` and defensively strips any
`<think>` block that leaks through anyway) since every prompt in this
project wants one strict-JSON answer, not visible
chain-of-thought eating into the timeout budget. `llm_timeout_seconds=45`
(bumped from 30 after a live diagnostic report on qwen3.5:2b showed
p95/max latency uncomfortably close to the old 30s cutoff — not a sign
the model is failing, CPU inference on constrained hardware just isn't
necessarily faster for a smaller model), `llm_max_concurrent=4`. LLM is
on by default (`Config.llm_enabled=True`)
and treated as not budget-constrained on the user's hardware — prefer
giving the LLM more genuine decision points over deterministic/
RNG-driven ones where it plausibly improves emergence, subject to the
liveness rule below.

## Design priorities (Hearthmind is an autonomous, persistent artificial society)

Priority order: 1. emergence, 2. believable causality, 3. persistent
identity, 4. psychological realism, 5. long-term evolution, 6. player
discovery. The simulation should surprise even its developers. When
there's more than one believable future, prefer LLM reasoning over
deterministic rules.

The deterministic engine should only model objective physical reality:
time, weather, seasons, physics, movement, pathfinding, resources,
ecology, construction, decay. Everything involving judgement,
interpretation, creativity, uncertainty, psychology, or social behavior
should default to the local LLM unless there's a compelling engineering
reason not to — planning, decision-making, interpretation, beliefs,
memory, personality, emotions, relationships, rumors, traditions,
inventions, culture, politics, leadership, human-judgment economics,
conflict resolution, investigations, and (eventually, deliberately last
— see Phase G below) supernatural influence. Don't replace LLM reasoning
with a large deterministic rule system just because it's easier to
implement. The deterministic engine provides reality; the LLM provides
meaning. NPCs are imperfect: they misunderstand, forget, reinterpret
memories, procrastinate, become biased, gossip, forgive, hold grudges,
invent explanations, and change over time. Objective reality and
subjective belief are separate — important entities (including,
eventually, the town itself) maintain beliefs that evolve through
experience, not ground truth readouts. History should become physically
visible; NPC activity should reshape the world over the long run. Prefer
systems interacting with existing systems over isolated mechanics.
Implement the smallest coherent milestone at a time (this is the same
spirit as the batching rule below, at a finer grain). Before calling
something done, ask: does this increase the chance Hearthmind creates
believable stories nobody explicitly programmed?

This priority list *is* the existing "LLM as the town's brain" section
below, generalized past just town-brain/dialogue — read them together.
**Conflict flagged, not silently resolved:** this framing was given with
"run the full test suite, don't claim completion until tests pass,"
which contradicts the explicit workflow rule further down that the
automated suite is deemed unreliable and isn't run. That workflow rule
stays in force until the user says otherwise — flag it back to them
rather than picking a side silently.

**Continuous cognition, not stateless.** The local LLM's weights never
change; instead, its understanding of *this* world accumulates through
`Settlement.beliefs` (`llm/beliefs.py`) — a small, persistent set of
theories the LLM itself forms and later revises about people, families,
traditions, politics, economy, recurring patterns, and outside (player)
influence, fed back into future town-brain/chronicle prompts as
accumulated context so past interpretations shape future ones. A belief
is not guaranteed correct and can be revised or superseded, same as a
person's own running theory of their community. This is the first
concrete step toward "the town is itself a subtle character... slowly
forming opinions" — deliberately scoped small (settlement-level
theories, monthly cadence, a capped list) rather than building a
parallel per-agent belief-store on top of the per-agent `memories` list
that already exists; extend it incrementally rather than replacing it
wholesale. The supernatural/ambiguous-consciousness framing stays
implicit — nothing in `beliefs.py`'s prompts asserts the town literally
thinks, only that it accumulates and revises theories, which is
mechanically real regardless of how a player chooses to read it.

## LLM as the town's brain

The LLM isn't just a flavor-text generator bolted onto deterministic
mechanics — prefer routing genuinely significant town-level decisions
through it (what kind of building the settlement needs next, the
town's current civic priority, notable NPC moments) rather than pure
RNG/weighted-rule tables, wherever a deterministic fallback can still
keep the tick loop live on timeout/error. `settlement.current_priority`
(set by the seasonal "town brain" LLM job, `llm/town_brain.py`) is the
concrete expression of this — it measurably steers building-kind
selection, not just narration. Player intervention is deliberately
subtle: `/intervene/town-brain` queues a short text "whisper" that's
folded into the *next* town-brain prompt as one input among the real
settlement stats/history, not a command the LLM (or the deterministic
fallback) is forced to obey.

## Phase G v1: temperament and omens (subtle, never explained)

Started (was "deliberately last," now explicitly requested to run in
parallel with everything else). `Settlement.temperament` (-1..1) is a
real, deterministic value — a bounded random walk nudged monthly,
biased by the recent balance of good/ill fortune (births/festivals/
inventions vs. deaths/ruin) plus noise (`buildings.tick_temperament`).
It applies small, deliberately subtle nudges to a couple of existing
rolls (invention chance, predator-attack lethality) — never dominant,
always secondary to the mechanics that already drive those outcomes.
`llm/omens.py` is the only place any "the town might be more than
physics" reading enters: a rare, LLM-authored (or fallback-pool)
sentence describing something ambiguous someone noticed, worded so it
always has a mundane explanation available and never confirms anything.
Nothing in the UI labels temperament as "mood," "supernatural," or
similar — it's plumbed through `settlement.summary()`/`/state` like any
other internal number, visible to anyone who goes looking at raw data,
but never narrated as such. Extend this incrementally (more omen
triggers, subtler cross-system nudges) rather than escalating toward
anything explicit — the brief is "keep this ambiguous," permanently,
not just at launch.

**v2, both roadmap-flagged follow-ups closed.** `Config.phase_g_
intensity` (default 1.0) scales temperament's monthly step and omens'
per-month chance together — 0.0 holds temperament flat and skips omens
outright, a genuine off switch without deleting the mechanism. Omens
also gained deeper narrative payoff: about half the time one fires, if
a belief already resolves to a still-living agent, the omen centers on
that specific person (`llm/omens.py`'s `subject_name` param, both the
LLM prompt and the deterministic fallback pools) instead of the
settlement in the abstract — still never confirming anything, just
less anonymous. Same ambiguity rule applies unchanged.

**v3: temperament's reach extended, omen memory.** Two more small,
warm-only nudges (`MIGRANT_TEMPERAMENT_INFLUENCE`/`WILDLIFE_
TEMPERAMENT_INFLUENCE`, both ~0.2 fractional, same magnitude as the
original invention/predator nudges): a village with recent good
fortune draws a migrant, and the land recolonizes lost wildlife,
somewhat more readily. Deliberately not extended to disaster/farm/
construction rolls — those already have real, non-ambiguous drivers,
and nudging them too would start to feel like temperament secretly
running the simulation. New `Settlement.omen_history` (capped rolling
log, same shape as `priority_history`) gives omens a memory of
themselves — a new sighting can occasionally read as an echo of one
noticed before, offered to the LLM as optional texture ("if it fits
naturally... without saying so directly"), never a thread every future
omen is forced to follow. Same permanent ambiguity rule; extend this
incrementally rather than reaching for anything explicit remains the
standing instruction.

**v4: a player-visible building nudges Phase G.** `SHRINE_OMEN_
CHANCE_MULTIPLIER` (1.3x) on the monthly omen-firing chance while a
SHRINE stands — the first Phase G lever driven by something the player
can see and choose to build, rather than only pure event-count fortune
or noise. Same small, non-dominant magnitude as every other nudge in
this system; the shrine itself is never narrated as supernatural
anywhere, same as everything else here.

## Per-person beliefs

`Settlement.beliefs` entries can resolve to a specific living
inhabitant (`subject_agent_id`, via `beliefs.resolve_subject_agent_id`
matching the LLM's free-text `subject` against current agent names) and
get folded into that person's dialogue prompts (`llm/dialogue.py`'s
`beliefs_about` param) — so "the village believes Mira is reckless"
actually shapes what Mira and whoever she's talking to say to each
other, not just narration. Deliberately reuses the existing settlement-
wide `beliefs` list rather than building a second, parallel per-agent
belief store on top of `Agent.memories` — extend this list's mechanics
(more consumers reading `subject_agent_id`, family-level resolution)
before reaching for new state.

**Objective reality vs. subjective belief, and NPC disagreement**
(explicit user directive, restating/sharpening the standing design
priorities above — emergence stays priority #1). `World`/`Settlement`/
`Agent` state (position, hunger, condition, actual event history) is
ground truth; `Settlement.beliefs` and `Agent.memories` are each
holder's *interpretation* of it, and are allowed to be wrong, one-sided,
or contradict each other — nothing currently forces two NPCs' beliefs
about the same subject to reconcile, and that's correct, not a gap to
close.

**Trust lever: shipped.** `Agent.trust` (-1..1 per source agent id) is
a distinct axis from `relationships` (fondness) — how much credibility
an agent gives another's word. Nudged on dialogue (`TRUST_DELTA`,
asymmetric — trust is easier to lose than earn); consumed the moment a
rumor arrives (`Population.apply_dialogue`): below
`TRUST_SKEPTICISM_THRESHOLD`, the receiving agent remembers it with
visible skepticism ("X claims... but I'm not sure I believe them")
instead of at face value — and that skepticism then reaches the same
agent's own future cognition prompts (`build_prompt` reads the latest
memory), a real mechanical effect, not just flavor text.

**The town's opinion of the player specifically: shipped.**
`Settlement.player_standing` (-1..1) is a real, deterministic bounded
random walk (`tick_player_standing`, same shape as `temperament`)
nudged monthly by the volume of recent `/intervene/*` activity
(logged `intervention` events), mean-reverting toward 0 without
reinforcement. Folded into the town-brain prompt as one more quiet
input, only mentioned at all once it's notably warm/cold — never
narrated or labeled anywhere in the UI, same "plumbed through
`summary()`, visible to anyone who looks at raw data, never called
out" treatment `temperament` already gets.

## Observatory UI direction (explicit user directive)

The browser UI's target shape, superseding any assumption that "add a
panel" is the default way to surface a new system: **the map is the
primary interface**, read at a glance like an observatory instrument,
not a dashboard of numbers. Prefer overlays, hover-inspection, and
subtle animation on the map itself over adding more sidebar panels.
Prefer showing *consequences* in plain language ("the village is
aging," "granaries are nearly full," "wolves have returned") over
surfacing only the raw stat behind them — the raw stat should still be
reachable (hover, or the developer observatory below), just not the
first thing shown.

Two audiences, two surfaces, kept explicitly separate:
- **Normal UI** optimizes for *understanding the world* — curated
  history (already: `GET /history`, the History tab — curated, not raw),
  a relationship graph, hover-inspection on people/buildings/terrain,
  an NPC inspector that leads with *mind* (current goal, beliefs,
  memories, relationships, theories, long-term intentions, why they
  chose their current action) before any raw stat, surfaced
  conversations (ones that changed a belief/relationship/future event —
  not the full transcript by default), and an expanded Town Brain
  panel that occasionally surfaces a fragment of its internal
  monologue rather than only the current civic priority.
- **Developer observatory** optimizes for *understanding the
  simulation* — everything currently in the dev console
  (`/diagnostics`, `last_llm_calls`, tick timing, LLM stats) is the
  right home for prompt inspection, per-subsystem timing, event-queue/
  resource-flow internals, etc.; deepen it rather than leaking that
  detail into the normal UI.

**Backlog status: every item complete.**
- **Relationship graph: done.** A "🕸 relationships" header toggle opens
  a force-directed graph (client-side physics, no library — see
  `interface/static/app.js`'s `relBuildEdges`/`relStep`/`relDraw`) built
  from `Agent.relationships`, already present in the per-tick payload.
  Nodes drift together for fond pairs, apart for sour ones; edge
  color/thickness encodes affinity sign/magnitude; weak bonds
  (`REL_MIN_AFFINITY=0.08`) are dropped to keep it readable.
- **Hover inspection: done.** Extended past agents to buildings
  (kind/stage/condition) and bare terrain (biome/coordinates) — one
  unified hover pipeline on the map canvas, agent-then-building-then-
  terrain.
- **Mind-first NPC inspector: done.** Click an agent to open a modal
  led by current goal/reason, beliefs the village holds about them,
  named relationships, and recent memories — vitals are a small row at
  the bottom, not the headline. Stays live across ticks while open.
- **Surfaced conversations: done.** `Population.apply_dialogue` returns
  a `surfaced` flag (crossed into a close bond/rivalry, or carried a
  rumor); those log under `dialogue_surfaced` (shown in the main feed),
  routine chatter stays under `dialogue` (recorded, but filtered from
  the main feed the same way `day_end`/etc. already are).
- **Town Brain monologue: done.** `Settlement.priority_history` keeps
  the last 6 seasonal decisions; the Town Brain panel shows past
  rationales beneath the current one, read together as an ongoing train
  of thought.
- **Documentary mode: done.** New yearly LLM job (`llm/documentary.py`,
  gated on `year_end` — the slowest narrative cadence, rarer than
  chronicle's monthly one) narrates a look-back over the year's curated
  milestones (`history_events`, not the raw feed). Logged as
  `documentary`, shown in the main feed and History tab.
- **Map-as-primary-interface: done.** Hover/click inspection and the
  consequences overlay (see below) live directly on the map. The
  sidebar itself was also restructured: only Town Brain and Recent
  Events (the two panels the brief names for "normal UI, understanding
  the world") are visible by default; raw stat tiles, culture lists
  (beliefs/traditions/inventions/festivals), and infrastructure detail
  now live behind a "📊 details" toggle, the same reachable-but-not-
  first-shown pattern history/relationships/dev-console already use.

Existing world-evolution mechanics already satisfy most of the "map
should visibly evolve" ask (terrain evolution, road wear/decay — roads
already fade out from disuse via `roads.py`'s presence-driven decay —
building decay/ruin/reclamation, and the disasters/hydrology additions,
now joined by heatwave/frost — see "Realistic weather thresholds"
below); "settlements expand or collapse" is now also mechanically real
— a population crash recovers via a rare migrant arrival while any
people remain (`Population._maybe_welcome_migrant`, mirroring
wildlife's `_maybe_recolonize`), but true extinction (0 population) is
left as a legitimate, permanent, readable-from-the-landscape ending,
not auto-revived — rather than a UI-only concept.

**Consequences overlay.** A small overlay strip on the map itself
(bottom-left of the map panel, not a sidebar panel) surfaces the
brief's own example phrasing computed from live stats: "the village is
aging" (mirrors `agent.py`'s real `MIN_LIFESPAN_TICKS`), "granaries are
nearly full"/"running dangerously low," "wolves have returned"
(tracks a 0→active predator-count transition, not just "predators
exist"), plus disaster-driven lines (heatwave, flood, wildfire) and a
near-extinction warning. Client-side only, computed from data already
in the payload.

**Live sim-speed controls.** Pause/speed-up/speed-down/reset are
changeable from the browser UI in real time via `POST /intervene/sim-
speed` — deliberately NOT routed through the queued `/intervene/*`
seam other interventions use (a paused sim never reaches the point in
its tick loop that drains that queue, which would deadlock a pause
forever); see `WorldBroadcaster`'s pause/speed fields and `docs/
DECISIONS.md` for why. Speed is bounded to [0.25x, 8x].

**Realistic weather thresholds.** `is_snowing`, and the newer heatwave/
frost disasters, each initially used a threshold that looked correct on
paper but was unreachable against `compute_weather`'s actual smoothed
output (an EMA that damps single-tick jitter into a much narrower
realized range than the raw `uniform(-6, 6)` draw suggests) — live code
that could never fire, not merely a rare event. All three were retuned
against directly-measured achievable ranges (see `SNOW_TEMPERATURE_
THRESHOLD_C`'s docstring in `world/weather.py` for the full story). If
a future weather/disaster threshold "never seems to happen" on a live
run, checking whether it's actually reachable against the smoothed
output — not just plausible-looking on paper — is the first thing to
verify, not a sign the roll chance needs raising.

## Calendar, climate, and eras

The world clock is a real 365-day, 12-month calendar (`time_system.py`,
`Config.days_per_month`/`month_names`) — not the old fixed 20-day,
4-season year. `season` still exists as a 4-value concept (spring/
summer/autumn/winter) derived from the month via UK meteorological
convention (`Config.month_to_season`: Dec-Feb winter, Mar-May spring,
Jun-Aug summer, Sep-Nov autumn), so everything that already keyed off
`clock.season` (weather baselines, farm growth multipliers, chronicle/
tradition/invention/festival/town-brain cadence) kept working unchanged.
Weather baselines (`world/weather.py`) model a temperate UK maritime
climate at monthly granularity. Terrain evolution (deforestation
reversal / climate drift) is deliberately decoupled from season/year
boundaries — it runs on fixed week/month cadences instead — specifically
so the real, longer calendar doesn't make map evolution rarer in
wall-clock terms; if the map still "doesn't seem to be evolving" on a
live run, that's a signal to shorten those cadences further or boost the
roll chances, not a hint to go back to season/year triggers. An existing
saved world's calendar shape is creation-only and never changes
underfoot. Legacy-snapshot compatibility with the old fixed-20-day
calendar was deliberately dropped (explicit user instruction) — a
snapshot from before this rework won't load; there is no migration
path, and none is planned.

A settlement starts in the `industrial` era and can advance
(electrical -> modern -> digital) purely as a function of accumulated
`tech_level` (`buildings.era_for_tech_level`) — each era is a
mechanically real unlock (the FACTORY building kind past `industrial`,
the AUTOMOBILE vehicle kind past `modern`), not just a label change.
Carts/mounts stay foundable at every era rather than being replaced
outright — horse-drawn transport genuinely coexisted with early
industry for decades, so their presence at `industrial` isn't actually
wrong, just previously un-answered by any forward progression the way
buildings already had.

A brand-new world's seed is chosen by a one-time "genesis" LLM call
(`llm/world_genesis.py`, wired in `server.py`) when `--seed` is omitted:
the LLM writes a short founding-scenario sentence, and its hash becomes
the seed that drives the ordinary deterministic terrain/weather
generation — "initial terrain and weather chosen by an LLM" is literal,
not cosmetic. An explicit `--seed` always wins and skips genesis
entirely; a resumed world never re-runs it.

**Settlement naming** follows the same "instant deterministic
placeholder, LLM improves it in the background" shape:
`settlement.naming.generate_settlement_name` still fires synchronously
inside `World.tick()` the instant a settlement's first building stands
(every other system gates on `settlement.name` being set the same
tick), and `llm/naming.py` + `SimulationEngine._maybe_schedule_naming`
propose a better, founding-scenario/terrain-aware name in the
background that silently replaces the placeholder once it resolves —
skipped entirely when the LLM is disabled, since the placeholder
already *is* the correct fallback outcome there.

## Workflow rules

- Batch commits: implement multiple systems per session/commit rather
  than shipping one small feature at a time, unless the user asks for a
  narrow fix. Still no half-finished pieces within a batch — every
  system landed must be mechanically real (see "Building resource
  costs" precedent), not a stub.
- Audit before continuing; fix regressions before new features.
- Preserve existing behavior unless explicitly changing it.
- Update README/CHANGELOG/docs/DECISIONS.md as part of the work, not after.
- Do not run the automated test suite or add new unit tests — deemed
  unreliable. Verification is the user's live diagnostic reports from
  their own machine (real Ollama, real hardware), plus manual/ad-hoc
  verification scripts run directly in this environment. Treat the
  user's own diagnostics as high-priority signal and the actual source
  of truth for "does this work."
- Still reason through logic/edge cases carefully before shipping — just
  don't claim "tested" or spend effort on `unittest`.
- External libraries are allowed (no longer stdlib-only-by-default).
  Track every one in `requirements.txt` and `pyproject.toml`
  dependencies. Still prefer stdlib when it's a close call — only reach
  outside it when it buys something real (see F1's `websockets`
  precedent in docs/DECISIONS.md).
- **Determinism/reproducibility is NOT a project requirement** (dropped
  per explicit user instruction). The namespaced-RNG pattern
  (`hashlib.sha256(f"{seed}:{namespace}:{tick}")`) is still fine to use
  where it's the natural tool (e.g. picking among several candidates),
  and existing uses don't need to be ripped out, but new work should not
  be constrained by "must stay reproducible for the same seed" — favor
  whatever produces the most interesting emergent behavior, including
  bare `random`, wall-clock-seeded randomness, or LLM-driven
  non-deterministic choices.
- Tick loop (`World.tick`) is fully synchronous; LLM calls are
  fire-and-forget async and must never block a tick. Every LLM call
  still needs *some* fallback behavior on timeout/error (liveness, not
  determinism) — the fallback no longer needs to be reproducible, just
  non-blocking.

## Current state (v0.28.0+)

Phases A-G roadmap items are in flight; Phases A-F have substantial
content shipped (deterministic substrate now optional-determinism, LLM
cognition/dialogue/culture, settlements with real material costs and a
"town brain" civic-priority LLM decision, workshops/schools/hospitals/
universities/factories with a starting-industrial era progression,
farming, wildlife/ecology (including flee behavior and logged hunts),
roads (weather-affected), vehicles, terrain evolution (local activity +
climate/biome drift, now on visible week/month cadences), a real
365-day/12-month UK-climate calendar, an LLM-chosen world-genesis seed,
generational/family agent memory, intervention ("nudge") endpoints
including a subtle player-influence channel on the town brain,
human-readable infrastructure telemetry, a weather particle overlay +
day/night lighting + smooth agent movement, a live browser UI with a dev
diagnostics console). See `docs/DECISIONS.md` for the full decision
log, `docs/ROADMAP.md` for phase-by-phase plan and the original
feature checklist, `CHANGELOG.md` for version history.

## "Continue expanding" batch (v0.60.0)

Explicit user follow-up to v0.59.0, same category structure, one more
substantial item per category. Scoped after an Explore-agent audit of
what actually exists in each area (NPC inspector, rumor
instrumentation, LLM fallback pools, institution kinds) rather than
guessing.

**Deepen: `InstitutionKind.GUILD` (H3 v4).** A third, trade-specific
institution — one per skill (farming/construction), formed once
`GUILD_FORMATION_MASTER_COUNT` (3) agents cross `GUILD_SKILL_MASTERY_
THRESHOLD` (0.6), membership grows as more master the trade. First
real use of `Institution.name` (holds which skill). Shared guild
membership for that specific trade gives `GUILD_TEACHING_BONUS_
MULTIPLIER` (1.6x) in `_maybe_teach_skills`, stacking with the
existing trade-agnostic FAMILY/COUNCIL bonus (1.4x).

**Close a gap: rumor-epidemiology instrumentation.** `Population.
rumors_seeded_total`/`rumor_listener_exposures_total` — real counters
on the *existing* gossip machinery's two real entry points
(`spread_rumor`, rumor-carrying `apply_dialogue` calls), not a new
propagation mechanic (this project's dialogue rumors are each
independently generated per exchange, not a traceable hop-by-hop
chain — true per-rumor tracing would need a larger rearchitecture,
out of scope here).

**Content variety.** More fallback-pool entries in festival/
invention/tradition/dialogue — the pools the prior variety pass
(omens/caravan) didn't touch.

**UI depth.** The mind-first NPC inspector modal gained "Personality"
(traits, plain-language high/low reading) and "Skills" sections — the
data was already in the per-tick payload, just never rendered
per-agent.

Verified: guild formation/idempotence/refresh unit checks, a 4,000-
trial statistical check of the teaching-bonus ratio (1.57x measured
vs. 1.6x expected), a real 50-tick engine run confirming formation
fires inside the actual tick loop with a full serialization round-
trip, rumor-counter increment/no-increment/serialization checks, a
live FastAPI route check, `node -c` on app.js, and a 5,000-tick smoke
run (0.91ms/tick, no regression). Full accounting in
docs/DECISIONS.md, "continue expanding."

## "Expand all features" batch (v0.59.0)

Explicit user directive, narrowed via a clarifying question into four
selected categories (deepen existing systems, close a roadmap gap,
content variety, Observatory UI depth) — scoped to one substantial,
fully-verified item per category rather than attempting literal
maximal coverage in one pass (flagged explicitly, same as prior
scoping decisions like caravans/multiple-settlements).

**Deepen: disease v2.** `Agent.immune_ticks`, set to `IMMUNITY_
DURATION_TICKS` (400) on recovery, decayed every tick — a recovered
agent can't be a fresh outbreak's index case or catch it again from a
carrier while immune. Closes v1's own flagged "extend later if
wanted."

**Roadmap gap: where-to-build, second factor.** `SETTLE_CHANCE_
RESOURCE_ADJACENCY_MULTIPLIER` (1.3x) — a candidate construction tile
near a productive resource node or open water is more likely to be
settled, stacking with the existing road-adjacency multiplier.

**Content variety.** More omen/caravan fallback-pool entries.

**MARKET: caravans get a building hook.** `BuildingKind.MARKET`,
foundable only once `Settlement.caravans_visited` (new persistent
counter) meets `MARKET_CARAVAN_VISIT_REQUIREMENT`; once standing,
improves both caravan trade magnitude (1.4x) and monthly visit chance
(1.25x) — genuinely bidirectional with the caravan system, closing the
one clearly one-directional link the integration milestone's own
standard would flag.

**Observatory UI depth: scrub-through-time, v1.** New `GET /snapshots`
+ `GET /snapshots/{tick}` (read-only, reconstructs a `World` from a
stored snapshot row, never touches the live world) and a "🕰 timeline"
browser panel with a slider — a first small step on the long-flagged
"true scrub-through-time replay view" gap (settlement/population
summaries only, sparse ticks, not per-agent frame-by-frame replay).

Every piece verified via direct unit/integration checks (a real
`SimulationEngine` run through several snapshot/caravan/disease
cycles, FastAPI route handlers invoked directly since no HTTP test
client is available in this environment) plus a 5,000-tick full-engine
smoke run confirming no tick-throughput regression. Full accounting in
docs/DECISIONS.md, "Expand all features."

## Backpressure gate for settlement-level LLM jobs (v0.58.0)

Explicit user follow-up: "audit for sparse but sudden high swap
usage" — distinct from every leak fixed so far (institutions,
relationships/trust, culture lists), all of which are steady-state
monotonic-growth bugs. Found: the ten settlement-level LLM jobs
(chronicle, documentary, tradition, invention, festival, caravan,
town_brain, beliefs, personal_belief, omen) all funnel through the
single shared `_schedule_llm_job` path, which — unlike per-agent
cognition/dialogue scheduling — never checked `CognitionRunner.
backlog` against `_backpressure_limit` before scheduling. Because
`chronicle`/`town_brain`/`beliefs`/`personal_belief` all fire on every
`month_end` and `tradition`/`invention` on every `season_end` (which
is always also a month boundary), a real-engine trace confirmed a
guaranteed 4-5-job cluster every month, growing further when
festival/caravan/omen's own independent rolls also hit — with
`llm_max_concurrent` at its permanent floor of 2 and ~17-20s/call real
latency, this forces Ollama through a rapid-fire burst once a month
instead of its normal sparse trickle, a plausible "sparse but sudden"
swap contributor no steady-state audit would catch. Fixed with
`SimulationEngine._settlement_job_backpressured()` — the identical
`backlog >= _backpressure_limit` check already used by cognition/
dialogue — added to all ten schedulers, after each job's own cheap
gate/RNG checks. Two deliberate exceptions: caravan's currency/
materials exchange stays unconditional (objective reality, same
status as a disaster's material cost — only its narration is gated);
naming stays fully exempt (one-time-per-world, no periodic retry path,
not part of the recurring cluster this targets). Same graceful-
degradation contract as the existing precedent: a dropped job just
waits for its own next natural cadence. Verified via a real-engine
trace proving the pre-fix cluster, a direct unit check calling all ten
schedulers with backlog both empty and saturated (all ten correctly
gate, naming correctly doesn't), and a 5,000-tick smoke run showing no
tick-throughput regression. No real Ollama server is available in this
environment, so the actual swap-pressure reduction can't be measured
here — same standing caveat as every other memory fix in this
project's history; a live diagnostic report is the way to confirm it.

## Water/power/irrigation + iGPU offload investigation (v0.57.0)

Explicit user follow-up to the integration milestone: implement the two
infrastructure-network pieces deferred there, and investigate GPU
offload on the user's AMD Ryzen 3 8300GE / Radeon 740M (gfx1103).

**Irrigation**: farm plots adjacent to water grow `IRRIGATION_GROWTH_
MULTIPLIER` (1.35x) faster (`FarmGrid.tick`, reusing the existing
`is_adjacent_to_water` helper H-era fishing already built). **Power**:
new `BuildingKind.POWER_PLANT`, foundable from `electrical` era onward
(hung off that era's own previously mechanically-thin identity) —
boosts WORKSHOP/FACTORY income and adds a small `carrying_capacity`
infrastructure bonus alongside roads. Both verified via direct unit
checks.

**iGPU offload**: this environment has no access to the user's real
Ollama/ROCm installation, so nothing here could be tested directly.
Diagnosis (full reasoning in docs/DECISIONS.md): `rocminfo` detecting
`gfx1103` doesn't mean Ollama's bundled ROCm build will use it — the
Phoenix/Phoenix2 iGPU family (740M/780M) has historically fallen
outside Ollama's vendored-ROCm supported-target list even when the
system's own ROCm stack recognizes the chip fine, matching the reported
symptom (`rocminfo` sees it, `ollama ps` still says 100% CPU). Guidance
given: try `HSA_OVERRIDE_GFX_VERSION=11.0.0` on `ollama serve` first
(spoofs `gfx1103` as the nearest supported target, a known community
workaround for this exact GPU family); llama.cpp's Vulkan backend as a
fallback if that doesn't work (more permissive with unsupported ROCm
targets, at the cost of leaving Ollama's own management behind).
Explicitly did not promise a "guaranteed" speedup — the iGPU is small
(4 CU) and shared-memory, real gains can only be measured on the user's
actual hardware. Shipped one genuinely safe, no-op-by-default lever:
`Config.llm_num_gpu` (default `None`), ready to set once/if GPU offload
is confirmed working server-side.

## Integration milestone: cross-system audit and vertical integration (v0.56.0)

Explicit user directive: audit every major subsystem for isolation,
then increase real bidirectional interaction between existing systems
— prioritizing dynamic carrying capacity, infrastructure networks,
external settlements/trade, institutional agency, knowledge diffusion,
urban growth, and supernatural propagation, with every touched system
required to both influence and be influenced by multiple others. Full
audit findings, per-system rationale, and verification in
docs/DECISIONS.md.

Audit found COUNCIL (H3) as the single most isolated system in the
codebase — membership never refreshed on death (silently decayed to a
ghost roster) and zero mechanical output anywhere despite FAMILY
already having a working belief-mirroring pattern to extend. Traits
(H6) were write-only — nudged by real events, consumed by nothing
deterministic. Roads (C5) were decorative — a real, tuned mechanic
with almost no downstream consumer. `carrying_capacity` (H1) read only
housing/economy/security/labor/weather, leaving institutions/skills/
infrastructure with no path to expand what a settlement could support.

Shipped: `Population._maybe_refresh_council` (living-membership
top-up, fixes the ghost-roster bug), `llm/beliefs.sync_council_beliefs`
(COUNCIL gets real accumulated civic theories, closing `Institution.
beliefs`'s previously-dead field), `Population.council_disposition`
feeding `town_brain` (prompt + fallback tie-break) and
`carrying_capacity`'s new coordination term; resilience/sociability/
ambition all now read by real deterministic mechanics (death chance,
starvation tolerance, trade threshold, teaching chance, HUT-ownership
weighting); roads now nudge construction site selection (closes the
standing "where to build is pure chance" roadmap gap), disease-
outbreak contact rate, and carrying capacity's new infrastructure
term; `_maybe_teach_skills` is now institution- and culture-aware (a
new `"knowledge"` tradition influence, a fourth `TRADITION_INFLUENCES`
entry); a new `llm/caravan.py` gives "external settlements and trade"
its scoped first step — a rare monthly abstract event (no new map
entity, no second `Settlement`) with a real currency/materials
exchange and an optional rumor seeded into the *existing* gossip
system via new `Population.spread_rumor`, explicitly not the full
multi-settlement rearchitecture (still its own dedicated session, see
"Known architectural gaps" below); omens can now center on "the
council of elders," extending Phase G's subject-depth work from
person to institution.

Deliberately not attempted: full multi-settlement/external trade
(unchanged standing decision); water/power/irrigation as a distinct
infrastructure network (no concrete mechanical hook yet — water
already exists as terrain/fishing, power doesn't fit the tech tree
until further era progression); ambition wired into COUNCIL seating
(kept as a clean, single-purpose age-based rule). Verified via direct
unit checks per new link plus a 50,000-tick full-engine integration
run exercising every mechanic together, with a full serialization
round-trip (no snapshot schema changes were needed).

## Ollama `--no-mmap` forced off via `use_mmap: true` (v0.55.0)

User followed the `ollama ps`/`ps aux` suggestion from the v0.54.0
follow-up and pasted real output: `ollama serve` itself was negligible
(50MB), but the per-model `llama-server` runner was resident at
**5.1GB — 74% of an 8GB machine** — against a model `ollama ps` reports
as only 2.4GB loaded, with `--no-mmap` on its command line. `--no-mmap`
forces model weights into private anonymous memory the kernel can only
relieve via swap; mmap'd weights are file-backed and the kernel can
instead drop-and-reread from disk under pressure, no swap involved.
Whatever set `--no-mmap` (env var or Ollama's own low-RAM heuristic)
was never being contradicted by this project's own requests. Fixed the
same way `num_ctx`/`num_predict`/`keep_alive` were: `Config.llm_use_
mmap = True` sent as `use_mmap` in every call's `options`, threaded
through both `OllamaClient` construction sites (`SimulationEngine` and
`server.py`'s genesis-seed call). Can only be verified end-to-end on
the user's real machine — this environment has no genuine Ollama
server; confirmed here only that the option is actually built into the
request payload. Separately flagged, explicitly not attempted: the same
diagnostic showed `--mmproj` pointing at the same blob hash as
`--model`, suggesting a possibly-unused multimodal projector bundled in
the pulled `qwen3.5:2b` tag — that's baked into the model artifact on
the user's machine already, no request-level API option can strip it,
and this environment has no access to their `ollama` installation to
even inspect it, let alone fix it.

## Unbounded `Settlement.institutions` growth fixed (v0.54.0)

Live user report of continuing swap pressure. Diagnosed by direct
measurement (per the standing "measure first" discipline), not by
re-tuning already-pinned Ollama levers again: `Settlement.institutions`
(H3, extended by H7/H9 across earlier sessions in this same
conversation) had no cap — FAMILY institution count climbed roughly
linearly with cumulative births (191 by tick 24,000, still climbing on
a 40k-tick measurement run) regardless of population, which plateaus at
the H1 carrying-capacity ceiling. Same bug class as the relationships/
trust leak (v0.42.0) and the traditions/inventions/festivals lists
(v0.44.1) — a per-event append with no removal — just never audited
when institutions were introduced. Fixed with `INSTITUTION_LIST_MAX_
STORED = 300` (same magnitude as `CULTURE_LIST_MAX_STORED`) enforced by
`population._prune_extinct_families`, extinction-aware rather than a
blind newest-N truncation (unlike traditions/inventions/festivals, a
FAMILY institution is looked up by living-agent membership via
`family_for`/inheritance/dialogue, so only families with zero living
members are ever evicted, oldest-first, only once over cap). Verified
via a synthetic-cap unit check and a 60,000-tick full-engine
integration run confirming the stored count holds flat once population
plateaus. Full accounting in docs/DECISIONS.md. Every other per-agent/
per-settlement collection touched by H2/H4/H5/H6/H7/H8/H9 was
re-audited for the same pattern in this pass and found already
correctly bounded — institutions was the one genuine miss. If swap
pressure persists after this, the next place to look is Ollama's own
server-side memory (a separate process, needs a fresh live diagnostic
from the user's actual machine to pin down further — this environment
has no real Ollama to measure against).

## Ruin removal speed + last unbounded culture lists capped (v0.44.1)

`RUIN_REMOVAL_TICKS` lowered 3000 -> 1200 (~31 -> ~12.5 sim-days) —
removal was always correct, just slow enough to read as broken in a
normal session; also frees the tile back to construction sooner.
`Settlement.traditions`/`inventions`/`festivals` were the last
genuinely unbounded structures in the codebase (v0.40.0's `PROMPT_
CULTURE_LIST_MAX` only ever capped what's sent to an LLM prompt, not
the stored list) — now capped at `CULTURE_LIST_MAX_STORED = 300` with
persistent `traditions_established`/`festivals_held` counters (mirrors
`tech_level`, already the right counter for inventions) so fallback
ordinal naming survives the cap. Audited SQLite too: default `cache_
size`/no `mmap_size` already keep the unbounded `events`/`metrics`
tables a disk concern, not RAM — confirmed safe as-is, no pragma
changes made.

## Disease as a population-control valve; LLM concurrency floor restored; UI flicker; era progression tuned (v0.44.0)

Four explicit user follow-ups, one batch.

**LLM concurrency: floor raised back to 2, permanently.** Explicit
instruction: LLM use is never traded off against memory — `llm_max_
concurrent` will not go below 2 again. `llm_num_ctx`/`llm_num_predict`/
`llm_keep_alive` remain the memory levers for further optimization if
ever needed; concurrency is off the table.

**Phase G: audited, confirmed complete, no code changes needed.** Every
docs/ROADMAP.md checklist item is `[x]` and verified present in code.
The one remaining "not built" line (no player-facing acknowledgment the
system exists) is a deliberate permanent design choice, not a gap —
stays exactly as documented under "Phase G v1" above.

**Population control: disease, a real deterministic mechanism, not
another hard cap.** The 400-population safety valve (`POPULATION_CAP`)
was creating an artificial ceiling with no in-world explanation, and
kept the town brain's fallback priority pinned on "food" once hit
(nothing else to steer toward). `Population._maybe_outbreak`/`_tick_
disease` (agents/population.py) give the settlement a real epidemiology
loop instead: a small, population- and crowding-scaled chance of a new
spontaneous case each tick (deliberately reusing the same housing-
pressure signal `CROWDING_ENERGY_MULTIPLIER` already reads — real
disease risk rises with density, same as real crowd diseases), person-
to-person transmission on colocation, natural recovery, and a per-tick
death chance (~8% case-fatality per bout, halved by a standing
hospital, nudged by temperament — same shape as predator-attack
lethality). This is deterministic engine reality (a pathogen's spread
is physical, not judged), consistent with the priority-#1 split between
objective mechanics and LLM interpretation. `town_brain.fallback_
priority` now has a real, frequently-reachable "health" trigger tied to
actual sick_count (previously it required a predator to have killed
someone AND zero hospitals — a narrow combination that rarely fired) —
directly answers "town brain gets stuck on food": a real epidemic can
now compete as a legitimate priority. No immunity/reinfection modeling
in v1, same smallest-coherent-milestone scoping as everywhere else;
extend later if wanted.

**UI flicker/"tabs jumping around": fixed.** Root cause was two
compounding issues in `interface/static/`: variable-length list panels
(beliefs/traditions/inventions/festivals/infrastructure) had no
`min-height`, so a tick that added or removed a list item resized the
whole panel and shoved everything below it; and those panels were
rebuilt via `innerHTML` on every tick regardless of whether content
had actually changed, resetting any manual scroll position. Fixed with
CSS `min-height` matching the existing `max-height`, plus a
`setInnerHTMLIfChanged` helper that skips the DOM write when markup is
unchanged.

**Era progression: not a gating bug, just slower than a typical
observation session.** Investigated and confirmed `tech_level`/era
advancement (`era_for_tech_level`) has no hidden blocking condition —
only "settlement is named" and a prosperity bar (currency >=10 OR
materials >=50% capacity), both easily met. The real cause was pure
rarity: `INVENTION_CHANCE_PER_SEASON` at 0.15 with steep era thresholds
meant ~5 in-game years to `electrical`, ~20 to `digital` — plausibly
longer than most live sessions run, hence never being witnessed. Raised
to 0.2 (~3.75/~15 years respectively) — still a genuine long-run
milestone, the thresholds themselves are untouched, just observable
within a realistic session. The v0.43.2 HUT-decay fix was an incidental
second contributor: a settlement whose materials no longer crash near
the population cap also clears the prosperity gate more reliably, so
invention rolls actually happen closer to their nominal rate.

## HUT decay/upkeep collapse near the population cap (fixed v0.43.2)

Root-cause finding, not the already-documented Malthusian equilibrium
(see "Post-rework equilibrium note" below): `Settlement.tick()`
computed one `decay` value boosted by unpaid civic upkeep and applied
it to every standing building including HUTs, which draw zero upkeep
(`UPKEEP_PER_CIVIC_BUILDING_PER_TICK` explicitly excludes them). As
civic-building count grows toward the population cap, upkeep outpaces
currency income and HUTs — the settlement's entire housing supply —
started decaying up to 1.5x faster for a bill they never incurred. A
44k-tick diagnostic (seed 42) measured `huts_standing` collapsing
78->16 in one 2,000-tick window right at the population cap, with
cumulative starvation deaths jumping 21->293 across the same stretch:
unpaid upkeep -> huts ruin -> housing capacity drops -> more crowding
-> `CROWDING_ENERGY_MULTIPLIER` forces more RESTING -> fewer idle
agents left to repair anything -> decay keeps winning. Fixed by
splitting `decay` into a HUT-exempt base rate and a `civic_decay` rate
(upkeep penalty) applied only to non-HUT buildings.

**This fix alone was not sufficient** — a matched follow-up run showed
the collapse still happened, just delayed and, in absolute terms,
worse (huts_standing 98->47, deaths 28->216 in one 2,000-tick window,
because population/housing had grown further before hitting the same
wall). Second root cause, same investigation: decay has zero per-
building variance (weather/season are settlement-wide scalars applied
identically to every standing building of a kind), so a batch of HUTs
built together in a growth spurt approach `REPAIR_THRESHOLD` in
lockstep — and `AgentGoal.WANDER` (a common idle fallback goal) had no
attraction toward a decaying building, so `_maybe_repair` depended
entirely on incidental colocation. Fixed by adding `Population.
damaged_building_positions` and a WANDER-goal movement bias toward the
nearest below-threshold building (`_dispatch_movement`), mirroring how
FORAGE already biases toward food — no new `AgentGoal`, no cognition
changes. With both fixes, `huts_standing` tracked population smoothly
with zero housing deficit through the full tested range, and
cumulative starvation deaths stayed at 2-3 through tick 22,000 versus
12-17 for the unfixed baseline *and* the first fix alone at the same
ticks. This was the real mechanism behind the live "population still
declining and dying of starvation" report. Worth checking first if a
similar report recurs: is `huts_standing` tracking population growth,
or collapsing at a specific trigger point — and if a first fix only
delays a collapse rather than eliminating it, treat that as a signal
a second, deeper cause is still active, not as a partial success to
stop at.

## Ollama memory, second pass (v0.43.1)

v0.43.0's `llm_max_concurrent=2` wasn't aggressive enough per explicit
user follow-up ("be more aggressive"). Dropped to `1` — its floor,
fully serialized — with `llm_timeout_seconds` bumped 45->60 as margin
(not strictly required, since the per-call timer starts on semaphore
acquisition, not while queued, but cheap insurance against the
serialized worst case) and a new `Config.llm_keep_alive="3m"` sent on
every call so the model actually unloads from Ollama during a real
lull rather than staying resident indefinitely on servers whose own
default is "never unload." Framed explicitly as trading LLM decision
*richness* for memory headroom on 8GB hardware, not correctness —
every LLM call still resolves through its deterministic fallback
either way, so a saturated single lane means more agents reason via
fallback more often, never a stall or a wrong-but-silent result.

## Ollama-side memory pressure + weather variety (fixed v0.43.0)

The same "heavy swap, unresponsive system, ~100 population" symptom
that v0.42.0 fixed recurred within an hour afterward — v0.42.0's own
writeup ruled out "LLM/Ollama memory pressure" too early: it correctly
confirmed no leak *inside this process* (a matched probe stayed under
100MB RSS through a full population boom/crash) but never checked the
separate Ollama server process, whose memory is real and swappable
regardless of which process holds it. `Config.llm_max_concurrent`
lowered 4 -> 2 — the v0.39.0 architecture review already recommended
this explicitly and it was simply never acted on; each in-flight
Ollama call holds its own KV-cache allocation, and this project now
routinely has 4+ simultaneous LLM jobs in flight (cognition/dialogue/
chronicle/culture/town-brain/beliefs/omens all sharing the scheduling
path). New `Config.llm_num_ctx` (2048)/`llm_num_predict` (512), sent as
Ollama's `options` on every call via `OllamaClient` — previously unset,
so the server's own defaults silently governed both memory and
worst-case generation length; every prompt here comfortably fits under
2048 tokens, so this is a safety ceiling, not a working constraint.
Separately, a live report of "I only ever see rain" was confirmed by
measurement, not dismissed as normal variance: `WeatherState.describe
()`'s sky-band cutoffs were the same class of bug already diagnosed and
fixed for `SNOW_TEMPERATURE_THRESHOLD_C` — tuned against raw per-tick
jitter rather than `compute_weather`'s smoothed realized range, so
"clear" (<=0.08) was literally unreachable and the world sat in "light
rain" 90%+ of the time regardless of season. Retuned against a 200k-
tick measured distribution (new `CLEAR_PRECIPITATION_THRESHOLD`/
`OVERCAST_PRECIPITATION_THRESHOLD`/`HEAVY_RAIN_PRECIPITATION_THRESHOLD`
in `world/weather.py`); the frontend's independent rain-particle
overlay had the identical bug (clear-threshold 0.05, also unreachable)
and was rescaled the same way in `interface/static/app.js`. Standing
lesson for future diagnosis: a live symptom traced to one fixed cause
is not necessarily fully explained by it — re-verify after a fix lands
rather than assuming the first plausible root cause was the only one,
and check *every* process a live report's symptom could implicate
(here: two separate processes, two separate bugs, one shared symptom).

## Memory leak: unpruned relationships/trust (fixed v0.42.0)

A user-reported live symptom (heavy swap, unresponsive system at only
100 population) traced to `Agent.relationships`/`Agent.trust`: an entry
was created on first colocation and never removed, including for
agents who later died — every acquaintance a villager ever had stayed
in their dict forever. A matched 50k-tick A/B run (same seed, through
a population boom to 229 and a starvation crash back to 36) measured
the baseline peaking at 489 relationship entries per agent (112k
total) versus 103 per agent (23.6k total) with the fix at the same
tick — >4.7x — and, after the crash, baseline survivors carrying 322
stale entries per agent (mostly references to the 751 people who'd
died by then) versus 19 per agent with the fix. Fixed by pruning
decayed-to-exactly-0.0 entries in `Population._update_relationships`
and stripping dead-agent references from every survivor in
`_apply_deaths` — both are pure memory bounds with no observable
behavior change (`.get(id, 0.0)` already treated an absent key
identically to a present zero-valued one). `GET /diagnostics`'s new
`relationship_graph.avg_relationships_per_agent` is the live signal to
watch if a similar leak is ever reintroduced elsewhere (dicts keyed by
agent id are the pattern to audit first). Separately noted, not fixed
(legitimate behavior, not a leak): large crowds at scarce food tiles
under the v0.41.0 carrying-capacity rework trigger an O(group^2)
full-mesh relationship bonus every tick (observed a 29-agent crowd at
one granary) — this is real social contact, not stale data, but is
worth watching as a CPU/memory cost if crowding gets more extreme at
higher populations.

## Architecture review: implemented in v0.40.0

The review below was performed at v0.39.0; v0.40.0 then *implemented*
its prioritized recommendations (see CHANGELOG `[0.40.0]` and
docs/DECISIONS.md "Architecture-review implementation pass" for the
full accounting). Now shipped: carrying-capacity rework (goal-gated
planting + crop rot + surplus-gated reproduction; POPULATION_CAP 400 as
pure safety valve), gossip opinion contagion, LLM scheduling
backpressure + result-staleness guards, grounded cognition prompts
(colocated names, nearest-food distance, 3 memories), stat-free beliefs
prompt + subject-match revision, conversation memories, whisper
retention on fallback, town-brain fallback un-locked, prompt
token-bounding for culture lists, O(N^2) rival-scan fix +
`Settlement.at` index + water-tile cache (~2-2.5x faster ticks),
snapshot pruning + one-commit-per-tick + events category index,
unique living names, and a per-sim-day `metrics` table (`GET /metrics`).
v0.41.0 then closed the rest: the early-population collapse funnel is
fixed at the root (worlds start March 1 via `Config.start_day_of_year`
— old snapshots keep their January calendar — and founders spawn
clustered around the food-richest walkable site; the funnel seed's
12->7-by-tick-2,000 crash became 2 starvation deaths by tick 10,000);
`Settlement` was split in place into four composed domain objects
(Infrastructure/Economy/Culture/Disposition) behind a passthrough
facade with byte-identical serialization — the multi-settlement
prerequisite is landed, the multi-settlement pass itself is STILL its
own dedicated future session; traditions carry mechanical riders
(festivity/harvest/resilience stacks via `culture_effect_multiplier`,
<=1.24x, consumed by festivals/harvest relief/grief cost); buildings
shelter awake workers from harsh weather, huts define housing capacity
(crowding drains energy), civic buildings draw currency upkeep with
unpaid-fraction-accelerated decay (currency now genuinely drains —
verified 50 -> 0 at pop 400); elders past 80% lifespan recover at
x0.7; the nine settlement-level LLM jobs share one `_schedule_llm_job`
path; the details panel opens with population/hunger/granary
sparklines off `GET /metrics`; and `hearthmind-experiment` (new CLI)
runs headless seed batches and exports per-sim-day metrics CSVs for
A/B ablations. Still open (in priority order): multiple named
settlements (own session), spatial buckets for nearest-X scans (only
needed past ~10x population). Rumor-epidemiology instrumentation:
**shipped, v0.60.0** — `Population.rumors_seeded_total`/
`rumor_listener_exposures_total`, real counters on the existing
gossip machinery (not a new propagation mechanic — see
docs/DECISIONS.md, "continue expanding"). Scrub-through-time replay
view: **v1 shipped, v0.59.0** (see the dedicated CLAUDE.md section
above) — keyframes were already preserved by snapshot pruning as
noted here; a true frame-by-frame agent-level replay remains a larger
future effort.
Post-rework equilibrium note: growth is food-coupled but abundant maps
still reach the 400 valve by ~tick 30k with hunger ~0.4 and real
starvation pressure at the top — a legitimate Malthusian equilibrium,
but if live runs feel too grim, tighten `REPRODUCTION_WELLFED_HUNGER`
or scale birth chance by hunger rather than re-lowering the cap.

## Architecture review findings (v0.39.0, July 2026 — full report in docs/REVIEW-2026-07.md)

An independent full-repo review pass, with measurements taken in this
environment (real engine, LLM disabled, in-memory DB). The complete
8-perspective report lives in `docs/REVIEW-2026-07.md`; the findings
that should steer future sessions:

- **Population collapse (commissioned question): it's an early-game
  winter funnel, not a long-run failure.** Worlds start Jan 1 (deep
  winter: regen x0.3, farm growth x0.35) with 12 agents scattered and
  no infrastructure — nearly all starvation deaths cluster before
  ~tick 6,000 (seed 7 fell 12 -> 7 by tick 2,000). Outcomes are
  bimodal: dip below `POPULATION_CRITICAL_THRESHOLD` and the world can
  demographically dead-end; survive and it grows monotonically to
  POPULATION_CAP and *stays there* — long-horizon runs show no old-age
  collapse wave (every founder dead by tick 40,000, population still
  pinned at the cap; births backfill continuously). The long-run pathology is
  the opposite of collapse: post-scarcity stagnation (~800-1,000
  simultaneously-ready farm plots for <=200 people; even an adversarial
  never-forage goal policy still grew to cap — agent decisions
  currently cannot fail at survival).
- **Town brain (commissioned question): influence is real, measured,
  and narrow.** Priority "food" moves granary share of new buildings
  23% -> 43% (4,000-draw measurement), plus the x1.6/x0.7 settle-chance
  steer — but the lever only touches construction. Two verified bugs:
  the fallback priority locks onto "food" indefinitely (its
  granary-fill test divides by a capacity that grows with every granary
  built), and player whispers are cleared at schedule time, so a
  whisper is silently lost whenever the town-brain call falls back.
- **Top three architectural risks:** (1) `Settlement` is the real God
  object (~25 fields across four domains) and every release makes the
  planned multi-settlement refactor harder — split it in place into
  composed sub-objects (Infrastructure/Economy/Culture/Disposition)
  *before* attempting multiple settlements; (2) no LLM scheduling
  backpressure — scheduling up to 3 dialogue + N cognition jobs/tick vs
  measured ~1 completion/17-20s means live runs at pop >~50 grow an
  unbounded asyncio task backlog and apply sim-days-stale results (cap
  the backlog, skip scheduling when full, drop stale results at apply
  time); (3) unbounded persistence — the `snapshots` table appends a
  full world JSON every 60 ticks forever and nothing ever reads old
  rows (prune/keyframe), `log_event` commits per event (batch per
  tick), and traditions/inventions/festivals lists grow unbounded and
  are fed whole into prompts (cap what's *sent*).
- **Measured performance:** 1.3 ms/tick at pop 12 -> 45.9 ms at pop
  500, superlinear because the per-agent rival-tile set comprehension
  in `_dispatch_movement` is O(N^2) (~40% of population tick at 200).
  Fixes are algorithmic (shared position map, spatial buckets for
  nearest-X scans, cached water-tile set, `(x,y)->Building` dict);
  C/C++ is not warranted — the bottleneck that matters is LLM latency.
  Keep `qwen3.5:2b`; do not raise `llm_max_concurrent` on CPU
  (consider lowering to 2).
- **Known correctness time-bombs:** per-birth `generate_names(1, rng)`
  draws with replacement across calls, so at pop ~200 from a 50-name
  pool duplicate living names are near-certain and
  `resolve_subject_agent_id` returns None on collision — per-person
  beliefs quietly stop resolving as the world grows (uniquify against
  living names at birth). Belief revision by integer index is fragile
  with a 2B model (match on subject string instead). Event categories
  are stringly-typed across 4+ independent registries.
- **Emergence gap:** culture is an open loop — traditions/rumors/
  festivals/chronicles change no behavior, and per-agent LLM goals
  measurably don't steer survival outcomes (every mechanic fires from
  colocation regardless of goal). The single highest-leverage change:
  replace the hard POPULATION_CAP + free self-planting farms with a
  food-driven carrying capacity (deliberate planting, untended decay,
  surplus-gated reproduction) — couples weather/disasters/wildlife/
  granaries/town-brain through one real constraint. Second: give
  traditions/rumors small bounded mechanical riders; resolve rumor
  subjects and nudge listeners' opinion of them (gossip as a force).
- **Preserve absolutely:** single-writer tick loop + queued
  interventions, fallback-on-every-LLM-call liveness, objective/
  subjective state split, Phase G ambiguity discipline, constants-with-
  rationale + decision log, the two-surface UI split.

## Phase H: living knowledge, institutions, dynamic carrying capacity

Explicit user directive (2026-07-13; user then explicitly requested "H1
then H3" as implementation order, followed by "H2 and H5 in parallel",
then "H4 and H7", then "H6 and H8 and H9 together" — H1 shipped
v0.45.0, H3 v1 (families) shipped v0.46.0, H2 v1 (belief lineage +
family-scoped mirroring) and H5 v1 (one skill, `SKILL_FARMING`) both
shipped together v0.48.0, H4 v1 (HUT ownership + a materials->tools
supply chain) shipped v0.49.0, H7 v1 (inheritance of land/goods/skill/
bias on death) shipped v0.50.0, H6 v1 (two-axis `Agent.traits`), H8 v1
(temperament -> belief-confidence crossover), and H9 v1 (family_formed
event + observatory stat surfacing) all shipped together v0.51.0, then
"perform H2/H5 extensions and full H extension" — H2/H5 extensions
(cognition beliefs_about, monthly personal per-agent beliefs, a second
skill `SKILL_CONSTRUCTION`, an additive population-skill invention-
chance nudge) shipped v0.52.0, and the "full H extension" half shipped
v0.53.0: H3's second institution kind (`COUNCIL`, elder membership
fixed at formation), H6's third trait axis (`TRAIT_AMBITION`, earned
via founding/mastery), and H4's second crafted good (`"medicine"`,
crafted by hospitals, halves a personal holder's own disease death
chance on top of the settlement-wide hospital reduction). Every roadmap
item from H1 through H9 is shipped at least a v1, with H2/H3/H4/H5/H6
now past v1. See docs/ROADMAP.md "Phase H" for the full per-item
breakdown and
docs/DECISIONS.md for the log entries): treat memory/belief/knowledge
as an
evolving ecosystem — spreading, competing, mutating, merging, and
disappearing across generations, not static per-agent/per-settlement
lists — with people, families, settlements, and eventually the Town
learning through observation, experimentation, prediction, and
experience. User was explicit this is architecture-direction, not an
implementation request: "identify where the current architecture should
evolve... do not implement everything immediately." Nine priorities, in
the user's own order: replace `POPULATION_CAP` with dynamic carrying
capacity (food/housing/labor/infrastructure/security/environment);
expand `Settlement.beliefs` into fuller, revisable world models held by
NPCs/families/settlements/Town; institutions (families, councils,
guilds, markets, religions, politics) as first-class entities that
outlive individuals; a resource-driven economy with ownership,
specialization, supply chains, trade (not isolated per-agent
production); knowledge/skills as a system distinct from beliefs, spread
by teaching/observation/apprenticeship; deeper psychology (habits,
identity, values, trauma, ambition, changing personality); cross-
generational inheritance of land/knowledge/tradition/story/bias; the
Town continuing toward a subtle ancient intelligence (Phase G's
permanent ambiguity rule unchanged); continued investment in
documentary/replay/timeline/observatory tooling. Suggested sequencing
(docs/ROADMAP.md has the reasoning): dynamic carrying capacity first
(cheapest, answers a recurring live complaint), then institutions
starting with families-as-entities (several other items structurally
depend on an addressable entity beyond individual `Agent`), belief-
structure and knowledge-as-a-system in parallel once that lands, full
supply chains and inheritance last as their own dedicated sessions —
same treatment "multiple named settlements" already gets below. Every
new subsystem here should keep the objective/subjective split and
interacting-systems-over-isolated-mechanics rules above, and should be
judged the same way: does it increase the chance of unscripted
emergence.

## Known architectural gaps (not yet built)

- **Multiple named settlements** — the one remaining genuinely large,
  architecturally separate effort (`Settlement` stops being a
  world-wide singleton, touching population/engine/every LLM prompt/
  the interface layer/snapshot schema in the same pass). Explicitly
  scoped out of the batch that shipped per-agent inventory/trade,
  culture-specific buildings, and structured per-family beliefs
  together — see docs/DECISIONS.md, "Multiple named settlements:
  explicitly not attempted this batch" for the full rationale. Remains
  the correct next candidate for its own dedicated session.
- **Per-agent inventory/trade: shipped, v1.** `Agent.inventory` — a
  single good (personal food), stashed from farm/granary foraging,
  drawn on by the agent first, then shared with a colocated non-rival
  neighbor (`Population._maybe_trade_food`). Deliberately scoped down
  from the maximal "full peer-to-peer economy" reading — no hauling, no
  market, no multi-good inventory, no price discovery. Those remain
  open for a future round if wanted.
- **Culture-specific building types: shipped, v1.** `BuildingKind.
  SHRINE`, foundable only once a tradition exists, deepens festivals on
  its tile and slightly raises the omen chance (the first direct
  culture-buildings/Phase-G interaction).
- **Structured per-family belief resolution: shipped.**
  `beliefs.resolve_family_agent_ids` widens a belief's resolved subject
  to their living parents/children/full siblings (via `Agent.parents`
  — no surname system exists), consumed by dialogue's `beliefs_about`.
- **Scrub-through-time replay: v1 shipped (v0.59.0).** `GET
  /snapshots`/`GET /snapshots/{tick}` + a "🕰 timeline" panel let a
  player step to a past snapshot's settlement/population summary,
  read-only. Still not a true frame-by-frame agent-level replay
  (documentary mode remains the year-in-prose narration) — a larger
  future effort if wanted.
- *Where* to build: `URBAN_GROWTH_ROAD_ADJACENCY_MULTIPLIER` (road-
  adjacency) and `SETTLE_CHANCE_RESOURCE_ADJACENCY_MULTIPLIER`
  (resource/water-adjacency, v0.59.0) both now weight *which already-
  colocated tile* gets settled — real, but still colocation-driven,
  not agent-pathed toward a chosen site (the larger, still-unattempted
  version of this gap).
- Everything else the roadmap once listed as "not yet built" — Phase G
  intensity/subject depth, the trust lever, the town's opinion of the
  player, deliberate hunting/vegetation depletion, rivalry avoidance,
  event-triggered cognition, whether-to-build steering — is now
  shipped. See docs/DECISIONS.md, "everything left" pass, and
  docs/ROADMAP.md for the full per-item accounting.

## Conventions

- Constants live as module-level values near the dataclass they govern,
  with a one-line docstring explaining *why* the number, not what it is.
- New behavioral fixes/features get a named or lettered decision entry
  in `docs/DECISIONS.md` — root cause (for fixes), design rationale, and
  verification data (manual/ad-hoc, not `unittest`).
