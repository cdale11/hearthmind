# Hearthmind — Project Memory

Persistent, always-running town simulation. Python (+ an optional
incremental C++ extension, `hearthmind._native`, see v0.72.0 below),
SQLite persistence, local LLM via llama.cpp (`llama-server`, default
since v0.72.0) or Ollama (`Config.llm_backend`, both fully supported).
Repo `cdale11/hearthmind`, branch `claude/hearthmind-overview-5bekay`.

This file holds the *standing rules and current state*. The full
narrative history (root causes, measurements, per-version rationale)
lives in `docs/DECISIONS.md` and `CHANGELOG.md` — consolidated here in
v0.63.0 per an explicit user cleanup request; see "Diagnostic history
index" below for pointers.

## Response format (chat)

- Minimum tokens. No restating goals/architecture/history already in this
  file or prior chat.
- Explain only non-obvious decisions.
- Progress reports: **Changes / Tests / Known Issues / Next Milestone**
  only — no preamble, no recap.
- Ask short, specific design questions when direction is ambiguous;
  don't guess on product decisions.

## Hardware target

GPU-offloaded llama.cpp inference confirmed working on real hardware as
of v0.72.3 ("much much better than expected" — live user report) — this
is now the assumed default (`--n-gpu-layers auto --fit on` as of v0.75.0
— llama.cpp dynamically sizes the offload to VRAM, replacing the old
hardcoded `--n-gpu-layers 999`; older llama.cpp builds without
`auto`/`--fit` fall back to `999`, see README; `Config.llm_num_ctx`/
`llm_num_predict`/`llm_core_cast_size` all raised accordingly, see
"Current state (v0.72.3)" below). **Actual usable RAM on that same
machine measures ~6.5GB via `htop`, not the full 8GB nominal** (v0.72.4
live report) — the v0.72.3 config raise assumed the fuller number and
was corrected back down (see "Current state (v0.72.4)"); GPU offload
moves weights/KV predominantly into VRAM but doesn't zero out
system-RAM pressure from the llama-server process/mmap'd model file, so
config sized for "plenty of RAM" needs a live `htop`/`system_memory`
reading behind it, not just "GPU offload is confirmed working." **8GB
RAM + zram swap, CPU-only inference remains fully supported**, not
deprecated — it's a documented non-default override (README's 8GB
section, `LLAMA_CTX_SIZE=1280 LLAMA_N_GPU_LAYERS=0` + `--llm-num-ctx
1280 --llm-core-cast-size 8`). Default model
`qwen3:4b-instruct` (v0.65.2, changed from `qwen3.5:2b`) — set per a
live user report on their own machine: `qwen3.5:2b` (never a real
released Qwen tag) showed memory-leak-like growth/swapping, while the
larger, official `qwen3:4b-instruct` stayed under 4.5GB with no swap
(take the user's live environment as ground truth over training data on
model naming/availability/behavior). `-instruct` means non-thinking by
design; the hybrid-thinking `"think": false` handling below stays as a
defensive no-op for it and becomes load-bearing again for the
`qwen3:1.7b` size-down path (not an `-instruct` tag). Size up/down and
report back, don't silently guess. Every call disables "thinking" mode
(`OllamaClient` sends `"think": false` and strips any leaked `<think>`
block) since every prompt here wants one strict-JSON answer.
`llm_timeout_seconds=60`, `llm_temperature=0.7` (v0.75.2, sent on both
backends and `--llm-temperature`-tunable — previously left to the
server's ~0.8 default; lowered toward coherence since every prompt wants
one short grounded strict-JSON answer, targeting live-reported garbled/
off-topic NPC dialogue on the small default model; drop to 0.5-0.6 for a
weak model, raise to 0.9 on a stronger one), `llm_num_ctx=2560`,
`llm_num_predict=448` (raised from 1280/384 in v0.72.3 once GPU offload
was confirmed working, re-lowered from an initial 4096/640 in v0.72.4
once the user's live `htop` reading showed only ~6.5GB usable RAM rather
than the full 8GB nominal, then re-lowered twice more — 3072/512 in
v0.78.1, current values in the same pass — once a real long-running-
game diagnostic (301 population, 13k ticks) showed 2GB of llama-server
swap even at the v0.72.4 numbers; see `Config.llm_num_ctx`'s docstring
for the full lineage. Lower back to 1280/384 for CPU-only 8GB hardware,
see README), `llm_keep_alive="3m"`, `llm_use_mmap=True`,
`llm_num_thread=None` (`server.py` CLI defaults `--llm-num-thread` to
every CPU core — see below), `llm_num_gpu=None` for the Ollama backend
(GPU offload for the default llama.cpp backend is `--n-gpu-layers`, a
`llama-server` launch flag — confirmed working via `scripts/run.sh`,
default `auto` + `--fit on` as of v0.75.0 so llama.cpp sizes the offload
to VRAM dynamically instead of the old hardcoded 999, see README's AMD
iGPU section and the iGPU investigation in docs/DECISIONS.md).

**`llm_max_concurrent=2`** (history: 4 (E2) -> 2 (v0.43.0) -> 1
(v0.43.1) -> 2 (v0.44.0, "permanent floor") -> 1 (v0.78.5, "make
concurrent task = 1 if it reduces memory pressure" — it did, at the
time: `scripts/run.sh` hardcoded llama-server's own `--parallel 1`, so
a second Python-side in-flight request was dead weight, and the
measured swap crisis then genuinely justified it) -> **2 again
(v0.81.0)**, once a fresh live diagnostic showed that swap pressure
resolved (`mem_available` 3321MB of 7045MB, ~0 swap) and the live
symptom had shifted to single-lane queueing instead (`calls_dropped_
backpressure` 616 vs. 100 attempted, latency p50/p95/max 31.8s/69.8s/
101.9s). `scripts/run.sh`'s `--parallel` is now `LLAMA_PARALLEL`
(default 2) instead of hardcoded, with `LLAMA_CTX_SIZE` doubled in step
(llama-server divides one shared `--ctx-size` across its `--parallel`
slots — raising parallel alone would silently halve each slot's
context). This is not a floor either direction holds regardless of
measurement — re-lower to 1 if a future `system_memory` reading shows
pressure again. Full lineage in `Config.llm_max_concurrent`'s
docstring. As of v0.63.0 every `server.py` CLI default references its
`Config` attribute — the audit found `--llm-max-concurrent` had
silently stayed at a hardcoded 4 for several releases, doubling real
Ollama concurrency on plain launches.

LLM is on by default (`Config.llm_enabled=True`) — prefer giving the LLM
more genuine decision points over deterministic/RNG-driven ones where it
plausibly improves emergence, subject to the liveness rule below. **But
LLM call *volume* IS budget-constrained** as of v0.70.0 (the swap-after-
hours fix): a new decision point that fires *per agent* or *per pair*
must be gated to the LLM core cast (`Population.core_agent_ids`, see
"Current state (v0.70.0)") and counts against
`Config.llm_max_calls_per_day` — otherwise it re-creates the
population-scaled throughput that drove Ollama into swap. Settlement-
scoped ("once per town per month/season") decision points stay
round-robin bounded and need no per-agent gating; give those to the LLM
freely.

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
reason not to. Don't replace LLM reasoning with a large deterministic
rule system just because it's easier to implement. The deterministic
engine provides reality; the LLM provides meaning.

**Physical substrate = a C++ cellular-automata engine (R7, added
v0.72.6, explicit user directive).** The objective-physical-reality
layer above — agriculture, ecology/wildlife, weather, environment
effects, disasters, terrain evolution — is explicitly framed as a
cellular-automata-style substrate (grid/tile-local state, per-tick local
rules; this was already the shape of these systems, R7 formalizes it)
and **any new code in this domain is written directly in C++ from the
start**, not Python-first-then-ported — pybind11 binding + pure-Python
fallback + randomized-equivalence/hash-soak verification from the first
commit, same discipline as every R5/R6 module. Existing not-yet-ported
Python in this domain (`world/weather.py`, `world/terrain_evolution.py`,
`world/disasters.py`, `world/hydrology.py`, `economy/farms.py`, most of
`settlement/buildings.py`'s decay math) keeps moving over incrementally
under R6's queue — R7 governs new code, it doesn't force an immediate
rewrite of the backlog. See docs/REFACTOR-2026-07.md, "R7." **This does
not change the LLM/deterministic split above** — town-brain, chronicle,
dialogue, culture, beliefs, dispute resolution, founding, omens/Phase G
stay exactly as documented; R7 only sharpens how the physical half gets
built going forward. NPCs are imperfect:
they misunderstand, forget, reinterpret memories, procrastinate, become
biased, gossip, forgive, hold grudges, invent explanations, and change
over time. Objective reality and subjective belief are separate —
important entities (including the town itself) maintain beliefs that
evolve through experience, not ground-truth readouts, and are allowed
to be wrong, one-sided, or mutually contradictory (nothing forces two
NPCs' beliefs about the same subject to reconcile — that's correct, not
a gap). History should become physically visible; NPC activity should
reshape the world over the long run. Prefer systems interacting with
existing systems over isolated mechanics. Implement the smallest
coherent milestone at a time. Before calling something done, ask: does
this increase the chance Hearthmind creates believable stories nobody
explicitly programmed?

**Conflict flagged, not silently resolved:** this framing was given
with "run the full test suite, don't claim completion until tests
pass," which contradicts the explicit workflow rule below that the
automated suite is deemed unreliable and isn't run. That workflow rule
stays in force until the user says otherwise.

**Continuous cognition, not stateless.** The LLM's weights never
change; its understanding of *this* world accumulates through
`Settlement.beliefs` (`llm/beliefs.py`) — persistent, revisable
theories fed back into future town-brain/chronicle prompts, plus
per-agent `Agent.beliefs` (monthly personal-belief job) and mirrored
copies on FAMILY/COUNCIL/GUILD institutions. A belief is not guaranteed
correct and can be revised or superseded. The supernatural/
ambiguous-consciousness framing stays implicit everywhere.

## Long-term design vision (2026-07, standing — full text in docs/VISION-2026-07.md)

Explicit user directive (2026-07-16): Hearthmind's objective is a
**living civilization simulator** whose guiding rule is **"maximize
emergence per LLM call"** — never maximize call count. Two layers,
sharpening (not replacing) the existing split: deterministic simulation
owns all continuous physical systems (long-term: data-oriented C++/SoA —
this is R6/R7/R8, already in motion); the LLM owns intelligence only, at
**multiple hierarchy levels operating at different frequencies**:
individual minds (core cast, persistent layered identity:
permanent/slow/fast state, specialized narrow cognitive tasks —
Reflect/Dream/InterpretRumor/etc. — never giant prompts) → collective
psychology (settlement mood vector) → culture (emergent, from lived
history) → civilization → **Town Consciousness** (persistent hidden
intelligence with memories/personality/objectives/player-model, nudging
through deniable channels) → **Narrative Direction** (names emerging
themes, biases the consciousness — never scripts quests). Knowledge is
local and imperfect: rumors distort through retelling → folklore →
myth; history is interpreted, not logged; dreams are symbolic, not
predictive; religions emerge from ritual, never predefined. NPCs may
lie, panic, procrastinate, hold false memories. Horror register:
FROM/Higurashi — fear from uncertainty, coincidence, never explicit
(Phase G ambiguity discipline is the mechanism, unchanged). Mandatory
audit-before-feature; extend existing systems before adding parallel
ones; every mechanic must interact with multiple others; design test:
"will this make the world feel more alive even if the player never
interacts with it?" Roadmap = phases I–N (Inner Life → Deeper Minds →
Knowledge & Story → Society & Power → Faith & Meaning → The Town
Awake) — see docs/VISION-2026-07.md for the full audit (≈60% of the
vision already exists in v1 form), budget arithmetic (whole roadmap ≈
+4.6 LLM calls/day, 5% of the ceiling), and two flagged conflicts
(core cast 14 vs "~11"; "directly causes events" reconciled to
deniable-channels-only pending user override). **Nothing from this
vision is implemented yet** (explicit instruction: design only).

## LLM as the town's brain

The LLM isn't a flavor-text generator bolted onto deterministic
mechanics — route genuinely significant town-level decisions through it
wherever a deterministic fallback can keep the tick loop live.
`settlement.current_priority` (monthly town-brain job) measurably
steers building-kind selection and settle chance. Player intervention
is deliberately subtle: `/intervene/town-brain` queues a short text
"whisper" folded into the *next* town-brain prompt as one input among
the real stats — not a command. Whispers are retained (not consumed)
when the call falls back, so a flaky-LLM stretch never silently eats
one.

## Phase G: temperament, omens, player standing (subtle, never explained)

`Settlement.temperament` (-1..1): a real deterministic bounded random
walk, nudged monthly by the balance of good/ill fortune plus noise.
Applies small, never-dominant nudges to invention chance,
predator/disease lethality, migrant arrival, wildlife recolonization,
and belief confidence (H8). `Settlement.player_standing` (-1..1): same
shape, nudged by recent `/intervene/*` volume, mean-reverting; folded
quietly into the town-brain prompt only when notably warm/cold.
`llm/omens.py` is the only place a "more than physics" reading enters:
rare, LLM-authored (or fallback-pool) sentences that always have a
mundane explanation available. Omens can center on a specific
still-living belief subject or "the council of elders";
`Settlement.omen_history` (capped) lets a new omen read as an echo of
a past one — optional texture, never a required thread. A standing
SHRINE raises omen chance 1.3x — the one player-visible Phase G lever.
`Config.phase_g_intensity` scales temperament steps and omen chance
together; 0.0 is a genuine off switch (works on resumed worlds too as
of the v0.63.0 `from_dict` fix). **Permanent rules:** nothing in the
UI labels any of this "mood"/"supernatural" — plumbed through
`summary()`/`/state` like any other number, visible to anyone who goes
looking, never narrated as such. Extend incrementally; never escalate
toward anything explicit. "Keep this ambiguous" is permanent, not a
launch condition.

## Per-person beliefs, trust, gossip

`Settlement.beliefs` entries resolve to living inhabitants
(`subject_agent_id` via name match; ambiguous names refuse to resolve)
and widen to living family (`resolve_family_agent_ids` via
`Agent.parents`); consumed by dialogue and cognition prompts
(`beliefs_about`) — "the village believes Mira is reckless" shapes what
Mira and her interlocutors actually say and choose. Deliberately reuses
the settlement-wide list + institution mirroring (`sync_family_/
council_/guild_beliefs`) rather than parallel stores — extend these
mechanics before reaching for new state. `Agent.trust` (-1..1 per
source) is a separate axis from `relationships` (fondness): nudged on
dialogue (asymmetric — easier to lose than earn), consumed on rumor
arrival (below `TRUST_SKEPTICISM_THRESHOLD` the listener remembers it
with visible skepticism, which then reaches their own future cognition
prompts). Gossip contagion: a rumor naming a living third party pulls
listeners' opinion of them toward the speaker's (skipped for skeptical
listeners).

## Observatory UI direction (explicit user directive)

**The map is the primary interface**, read at a glance like an
observatory instrument, not a dashboard. Prefer overlays,
hover-inspection, and subtle animation on the map over sidebar panels.
Prefer plain-language *consequences* ("the village is aging") over raw
stats — the raw stat stays reachable (hover, details toggle, dev
console), just not first. Two audiences, two surfaces, kept separate:
the **normal UI** optimizes for understanding the world (curated
history, relationship graph, mind-first NPC inspector, surfaced
conversations, town-brain monologue); the **developer observatory**
(`⚙ dev`, `/diagnostics`) owns prompt inspection, timing, and internals
— deepen it rather than leaking detail into the normal UI. The entire
original backlog for this direction is shipped (relationship graph with
family-tree edges, unified hover, NPC inspector incl. personality/
skills/institutions/health, surfaced-vs-routine dialogue, monologue,
documentary mode, consequences overlay, details toggle, timeline
scrub v1, sim-speed controls, sick/immune rings) — see docs/DECISIONS.md
for each item's entry. Sim-speed pause/resume deliberately bypasses the
queued-intervention seam (a paused sim never drains the queue — would
deadlock); speed bounded [0.25x, 8x].

## Calendar, climate, eras, genesis

Real 365-day/12-month calendar (`time_system.py`); `season` stays a
4-value concept derived via UK meteorological convention. Weather
models a temperate UK maritime climate at monthly granularity. Worlds
start March 1 (spring) with founders clustered near the best wild-food
site — the fix for the measured early-winter starvation funnel. An
existing world's calendar shape is creation-only; legacy pre-calendar
snapshots deliberately unsupported (explicit user instruction, no
migration path). Terrain evolution runs on fixed week/month cadences,
deliberately decoupled from season/year boundaries — if the map
"doesn't seem to be evolving" live, shorten cadences or boost roll
chances; don't revert to season/year triggers. Eras advance purely from
`tech_level` (industrial -> electrical -> modern -> digital), each a
real unlock (FACTORY/POWER_PLANT past industrial, AUTOMOBILE past
modern); carts/mounts stay foundable at every era. A new world's seed
comes from a one-time genesis LLM call when `--seed` is omitted
(explicit `--seed` skips it; resumed worlds never re-run it).
Settlement naming: instant deterministic placeholder inside
`World.tick()`, LLM proposes a better name in the background and
silently replaces it.

**Weather/disaster threshold lesson (standing):** `compute_weather`'s
EMA smoothing produces a much narrower realized range than the raw
jitter suggests. If a threshold-gated event "never seems to happen,"
first verify the threshold is *reachable* against measured smoothed
output (snow, sky bands, wind bands, storms, heatwave, frost were all
this bug class) — don't just raise the roll chance.

## Workflow rules

- Batch commits: multiple systems per session/commit unless the user
  asks for a narrow fix. No half-finished pieces within a batch — every
  landed system must be mechanically real, not a stub.
- **Every new feature gets a browser-UI surfacing pass in the same
  batch it lands in** (explicit standing user instruction, 2026-07):
  expose it however fits the existing Observatory style — an NPC
  inspector section, a map overlay, a dev-console row — not just
  `to_dict()`/`summary()` reachability. Plain per-agent state (traits,
  skills, emotions) gets a labeled section in the main UI; anything
  under the Phase G ambiguity discipline (temperament, mood, omens)
  stays dev-console/raw-JSON only, same as its siblings. Retrofit an
  older un-surfaced feature opportunistically when touching nearby UI
  code, but don't treat that as required scope for unrelated work.
- Audit before continuing; fix regressions before new features.
- Preserve existing behavior unless explicitly changing it.
- Update README/CHANGELOG/docs/DECISIONS.md as part of the work.
- **Do not run the automated test suite or add new unit tests** —
  deemed unreliable. Verification is the user's live diagnostic reports
  (real Ollama, real hardware — the actual source of truth) plus
  manual/ad-hoc scripts run in this environment. Still reason through
  logic/edge cases carefully; just don't claim "tested" via `unittest`.
- External libraries allowed; track in `requirements.txt` +
  `pyproject.toml`. Prefer stdlib when it's a close call.
- **Determinism/reproducibility is NOT a requirement** (explicit user
  instruction). The namespaced-RNG pattern stays fine where natural;
  new work should favor whatever produces the most interesting
  emergence.
- Tick loop (`World.tick`) is fully synchronous; LLM calls are
  fire-and-forget async and must never block a tick. Every LLM call
  needs *some* non-blocking fallback (liveness, not determinism).
- Settlement-level LLM jobs share `_schedule_llm_job` and are all
  backpressure-gated (`_settlement_job_backpressured`); per-agent
  cognition/dialogue have their own gates. Caravan's economic exchange
  stays unconditional (objective reality; only narration is gated);
  one-time naming stays exempt.
- **CLI defaults in `server.py` must reference `Config` attributes**,
  never hardcode a copy (v0.63.0 audit: a stale hardcoded default ran
  double the tuned LLM concurrency for several releases).
- Constants live as module-level values near the dataclass they govern,
  with a one-line docstring explaining *why* the number. Behavioral
  fixes/features get a `docs/DECISIONS.md` entry: root cause (for
  fixes), rationale, and verification data.

## Preserve absolutely (from the July 2026 architecture review)

Single-writer tick loop + queued interventions; fallback-on-every-LLM-
call liveness; objective/subjective state split; Phase G ambiguity
discipline; constants-with-rationale + decision log; the two-surface UI
split.

## Current state (v0.81.0)

Direct response to a live `/diagnostics` report at population 231/
13,006 ticks: `calls_dropped_backpressure` at 616 against only 100
`calls_attempted`, `backlog` reaching 11, and latency p50/p95/max of
31.8s/69.8s/101.9s — a single-lane queue (`llm_max_concurrent=1`)
serializing every job behind whatever's already running, while
`system_memory` showed the v0.78.x swap crisis this floor had responded
to was resolved (`mem_available` 3321MB of 7045MB, `swap_used_mb: 1`).
Five parts, plus a scheduler root-cause fix and a real movement bug
found while investigating the "queued jobs go stale" report.

**Config raised back up** (`Config.llm_max_concurrent` 1 -> 2,
`llm_timeout_seconds` 60 -> 120): both docstrings carry the full
reasoning/history. `scripts/run.sh` gained `LLAMA_PARALLEL` (default 2,
replacing a hardcoded `--parallel 1`) with `LLAMA_CTX_SIZE` doubled to
5120 in step — llama-server divides one shared `--ctx-size` across its
`--parallel` slots, so raising parallel alone would have silently halved
each concurrent request's context instead of adding real throughput.
`LLAMA_FIT_TARGET` 2560 -> 2048 (frees a bit more general system RAM for
the second slot's KV cache, now that headroom is real rather than
scarce). **Critical compatibility fix while updating these**: the
README's 8GB CPU-only recipe (`LLAMA_CTX_SIZE=1280`) did NOT set
`--parallel`, so it would have silently inherited the new default of 2
and halved to 640 tokens/slot — fixed to pin `LLAMA_PARALLEL=1
--llm-max-concurrent 1` explicitly. See README's "Running the LLM
(llama.cpp)" and "Running on 8GB RAM" sections, updated throughout.

**Backpressure reservation gap fixed** (the actual root cause of stale
queued jobs): `CognitionRunner.backlog` only increments once a scheduled
task's coroutine body actually starts running, which can't happen until
`_tick_once` (fully synchronous) returns and the event loop gets a
turn. Every `_maybe_schedule_*`/cognition/dialogue call site checking
backlog for backpressure was therefore reading the same stale pre-tick
value all tick long, even after several jobs had already been scheduled
moments earlier in that same tick — on a tick where many jobs are
eligible at once (the documented month-end settlement-job cluster, a
cognition+dialogue burst), more jobs got through than the concurrency-
derived limit intended, which is exactly why backlog could reach 11
against a max_concurrent=1-derived limit of 3. Fix: `SimulationEngine.
_reserved_this_tick`, incremented the instant any call site actually
creates a task (`_schedule_llm_job`, `_schedule_due_cognition`,
`_schedule_due_dialogue`, `_maybe_interpret_rumor`), reset to 0 at the
top of every `_tick_once`; every backpressure check now reads `_effective_
backlog()` (real backlog + this-tick reservations) instead of the raw
counter. Closes the staleness window to zero within a tick — a job
scheduled two calls ago this same tick is now visible to the next
check. This is what actually addresses "queued jobs become irrelevant
before they execute": the existing staleness/dedup machinery (`STALE_
GOAL_RESULT_TICKS`/`STALE_DIALOGUE_RESULT_TICKS` discarding overly-old
results, `apply_goal`/`apply_dialogue` no-oping for a dead agent,
`dialogue_cooldowns` marked synchronously at selection time so the same
pair can't double-queue, `_inflight_cognition_agent_ids` doing the same
for cognition, and Phase J's personal_belief job already merging belief
+ semantic-memory + secret into one call) was already sound — the
backlog was simply growing past what that machinery was tuned to
expect. Audited for genuine gaps beyond this and found none: per-agent/
per-pair jobs are all single-candidate-per-cadence-slot by construction
(one dispute pair/tick, one faction candidate/month, one personal_belief
target/month), so there is no duplicate-scheduling case those job types
could hit in the first place.

**Adaptive load control**: `SimulationEngine._current_backpressure_limit`
scales the static, concurrency-derived limit down using `CognitionRunner.
stats()`'s existing rolling p95 latency (no new state) — halves the
tolerated backlog once p95 crosses `ADAPTIVE_LATENCY_ELEVATED_MS`
(45s), quarters it past `ADAPTIVE_LATENCY_SEVERE_MS` (80s), never below
`llm_max_concurrent`, and recovers automatically once latency drops
(the rolling window is a fixed-size deque of the most recent calls, so
this always reflects current conditions). Proactively tightens before
the hardware is provably struggling, rather than only reacting once the
static limit is already blown.

**Diagnostics additions**: `llm_backlog_effective`, `llm_backlog_
reserved_this_tick`, `llm_backpressure_limit`, `llm_backpressure_limit_
effective` (watch the adaptive mechanism live), `agents_movement_stuck`
(agents currently mid-way through the new stuck-tick counter, see
below), `oldest_pending_goal_ticks`/`oldest_pending_dialogue_ticks`
(age of the oldest buffered-but-unapplied result — a distinct symptom
from `llm_stats.backlog`, since results normally drain the very next
tick).

**Movement bug found and fixed**: `Population._step_toward`'s greedy
step only ever tries the 1-2 cardinal directions that reduce Manhattan
distance (worst case: exactly ONE candidate when dy=0, i.e. a
straight-line target with zero vertical offset) — a concave water/
mountain pocket (or, in the worst case, simply a wall directly ahead
with no vertical component to the target) left the agent with zero
alternative candidates every single tick, silently degrading to the
pure random walk indefinitely for as long as that goal held, even
though the target was genuinely reachable by a longer route.
`travel_target` journeys already had a BFS escape for this; routine
goal-directed movement (FORAGE/SOCIALIZE/GATHER/WANDER) — which runs
for every awake agent every tick — never did. Fix: new `Agent.
stuck_ticks` (plain int, not native-store-backed, round-trips through
to_dict/from_dict) counts consecutive blocked-not-arrived greedy
attempts; at `MOVEMENT_STUCK_TICKS_THRESHOLD` (4) ticks, `_dispatch_
movement` spends one bounded `_bfs_step` (`MOVEMENT_STUCK_BFS_NODE_CAP`
= 600, smaller than travel_target's 4096 since this can fire for many
ordinary agents at once) to escape the pocket, resetting the counter
either way so a genuinely unreachable target costs one modest flood-
fill every 4 ticks, not every tick.

Verified: direct scratchpad tests — Agent.stuck_ticks round-trip +
legacy-snapshot default; a synthetic concave-water-wall grid confirming
an agent reaches a target unreachable by pure greedy stepping within a
few ticks by detouring through an open row, and a fully-enclosed
(genuinely unreachable) target never crosses the wall with stuck_ticks
staying bounded rather than growing; direct backpressure-limit tests
confirming the adaptive tiers (healthy/elevated/severe latency) and
confirming a same-tick reservation is visible to the very next
backpressure check (the exact gap being fixed); a 1500-tick engine soak
with a fake slow LLM client (50ms/call, `llm_max_concurrent=2`,
30 agents, 10-agent core cast) — 101 calls attempted/succeeded, 0
errors, backlog/reservation counters bounded and resetting correctly
tick to tick, no crash; `scripts/verify_native_soak.py` (2 seeds, 1500
ticks) byte-identical — this batch touches no native module.

## Current state (v0.80.0)

Phase L (docs/VISION-2026-07.md, "Society & Power"), all three pieces —
the vision doc's own call-volume analysis already resolved every fork
in this phase's favor (Reputation and Economy depth are zero-LLM-cost;
Factions spends a call only once per detected cluster, ever), so this
landed as one batch rather than needing a scoping question first.

**Reputation**: `Population.reputation(agent_id)` — mean trust every
living agent holds toward that agent, cached monthly (`_refresh_
reputation`, called from the existing month_end temperament tick, no
new job). Wired into `_prominence` (core-cast ranking, per the vision
doc's explicit "extend this ranking's inputs" instruction) and into
`llm/dispute.py`'s prompt/fallback (a lopsided reputation nudges
reconciliation odds and gets a context line when notably one-sided).

**Factions**: new `InstitutionKind.FACTION` — a cluster of living
agents bound by genuinely mutual trust (`Population._detect_faction_
candidate`: union-find over trust-graph edges clearing FACTION_TRUST_
EDGE_THRESHOLD both directions, cohesion-gated). Detection is free,
deterministic, monthly; only once a real candidate clears FACTION_MIN_
SIZE/FACTION_MIN_COHESION does the engine spend one LLM call
(`llm/faction.py`, `_maybe_schedule_faction`) to name/frame it — same
"detect cheaply, spend the call to name it" split as deliberate guild
founding. Membership is fixed at formation (like FAMILY, unlike GUILD).
Biases three existing mechanics rather than sitting inert: dispute
framing/fallback (rival-faction membership pushes toward feud),
fission-party assembly (a leader's faction-mates follow after family,
before mere fondness), and — implicitly — `_prominence` via reputation.
Bounded storage: generalized `_prune_extinct_families` into `_prune_
extinct_institutions(settlement, living_ids, kind, cap)`, reused for
both FAMILY and the new FACTION_MAX_STORED=20 cap.

**Economy depth**: scoped to the one piece that rides cleanly on
existing state — a bounded per-pair debt ledger (`Agent.debts`,
`_record_debt`, `decay_debts`) that the existing food/tools/medicine
barter mechanic writes to (a recipient owes the giver half the traded
amount; a reversed trade nets the ledger down first). Decays slowly
every tick (same prune-small-entries discipline as trust/relationships/
emotions) so an old debt eventually reads as forgiven. Feeds dispute
framing/fallback the same way reputation/factions do. **Scope cuts,
explicit**: the vision doc's "scarcity-driven specialization pressure"
piece was already noted as "mostly exists" via the skills system — no
new work needed; "black-market flag on trades when a council price-
nudge exists to defy" was dropped because this codebase's trade
mechanic is presence-driven barter, not price-driven exchange — there
is no existing "council price-nudge" an agent-to-agent trade could
defy, and inventing one to hang a flag off felt like the wrong kind of
scope creep for what's meant to be a lightweight extension of existing
state.

**UI**: NPC inspector gained "Debts" (mirrors the Relationships
section) and a faction line in "Institutions"; the Institutions stat
tile now includes a faction count; new `faction_formed` event
icon/group, same UI-surfacing-in-the-same-batch discipline as every
prior phase.

Verified: direct union-find/cohesion tests against synthetic trust
graphs (candidate detection, formation, faction_of lookup, exclusion of
already-affiliated agents); `_record_debt`/`decay_debts`/round-trip
tests (settlement, decay-to-prune, to_dict/from_dict exact); a live
8000-tick engine run (LLM disabled) confirms no crash and a populated
reputation cache; `scripts/verify_native_soak.py` (multi-seed)
byte-identical — this batch touches no native module. Next milestone:
Phase M (Faith & Meaning) or Phase N (Town Consciousness v2), per the
user's "continue with L-N" direction — not yet started.

## Current state (v0.79.1)

Closes Phase K's two deferred pieces (InterpretRumor + Dream), per
explicit "continue" direction — both implemented at their most
budget-conscious viable scope, not the vision doc's fuller version,
consistent with the standing memory-pressure directive; scope-downs
documented inline rather than silently decided.

**InterpretRumor()**: when a core-cast agent hears a rumor in dialogue,
they may retell it coloured by their own nature (bias/exaggeration/a
misremembered detail) — `llm/rumor_interpret.py`, wired into
`_apply_pending_dialogue_results`. Scoped down from the vision's `hops`/
`mutated`-field rumor-object model (no such structure exists in this
codebase) to land as a new memory via the existing `_remember`
mechanism instead — functionally equivalent emergence (different NPCs
remember the same rumor differently, and their own distorted version is
what propagates through future dialogue's "recent memories" context),
lighter plumbing. New `INTERPRET_RUMOR_MAX_PER_DAY=3` — this fires per
listening event, not once a month, so it needs its own ceiling on top
of the shared daily LLM budget.

**Dream()**: monthly, symbolic, never predictive (Phase G/omens'
ambiguity discipline applies) — `llm/dream.py`, new `SimulationEngine.
_maybe_schedule_dream`, own `MONTHLY_JOB_DAY["dream"]=23` slot. Reads
emotions + `goal_reason` + the settlement's newest folklore, writes one
dream memory via `_remember`. **Explicit scope cut**: rotates through
the core cast round-robin (one agent/month, same shape as `_maybe_
schedule_personal_belief`), not "all core-cast agents monthly" as the
vision doc describes — the fuller version is ~14x the call volume for a
14-agent cast, which the standing memory-pressure directive argues
against defaulting to. Schema also kept to one field (just the dream
text, no separate belief/trust nudge) for the usual "fewer fields per
call, more reliable small-model output" reason.

Both ride the existing `Agent.memories`/NPC-inspector "Recent memories"
UI surface for free — no new UI code needed.

Verified: fake-client test confirms InterpretRumor() plants a distorted
memory and respects its daily cap; Dream() picks exactly one core-cast
agent and plants a tagged dream memory; round-trip exact (both reuse
existing `memories` serialization, no new fields). `scripts/verify_
native_soak.py` (2 seeds, 1500 ticks): byte-identical — this batch
touches no native module.

## Current state (v0.79.0)

Phase K start (docs/VISION-2026-07.md, "Knowledge & Story"), scoped to
two of its four pieces per an explicit scoping question — Folklore
condensation + Historian v2 — with rumor distortion (InterpretRumor())
and Dream() deferred pending their own call-volume budget discussion
(both would add real new recurring per-agent volume; these two don't).

**Folklore condensation**: new `Settlement.folklore` (`settlement/
buildings.py`, cap `FOLKLORE_MAX_STORED=24`) — monthly, settlement-
scoped, same call-volume shape as tradition/invention/festival (one
bounded job in the existing `MONTHLY_JOB_DAY` rotation, day 20, not a
new per-agent gate). `llm/folklore.py` reads the settlement's own
recent rumor-category events (new `events_by_category` helper,
`persistence/snapshot.py` — deliberately the literal rumor stream, not
the diversity-adjusted digest, since rumors are never routine) and
condenses them into one short tale, or — the honest, expected common
case — says there's nothing worth telling yet; a folklore entry doesn't
form every month just because the job ran. Scoped down from the vision
doc's fuller per-rumor hops/mutation tracking, which doesn't exist in
this codebase yet — this closes only the "condensation" half of Phase
K's rumor→folklore→myth pipeline.

**Historian v2**: `llm/chronicle.py`'s system prompt now explicitly
asks the model to *interpret* the season, not just summarize it
("the winter the forest seemed to close in again"), and its prompt
gains the settlement's newest folklore as an optional interpretive lens
(used only "if it fits," per the same discipline `past_omens` already
follows). Folklore also feeds `llm/omens.py`'s existing "echo of
something noticed before" mechanism, the same texture-not-thread
treatment. Dialogue consumption deferred (not essential to "Historian
v2," kept scope tight).

**UI**: new "Folklore" panel (index.html/app.js) alongside Traditions/
Inventions/Festivals, showing tales newest-first.

Verified: direct `_maybe_schedule_folklore` call against a fake client
with a real rumor-category event logged — a folklore entry lands on
the settlement, correctly appears in a subsequently-built chronicle
prompt; `folklore` round-trips exactly through to_dict/from_dict;
`scripts/verify_native_soak.py` (2 seeds, 1500 ticks) byte-identical —
this batch touches no native module.

## Current state (v0.78.5)

Direct explicit config-tuning instructions, all implemented as asked:
"make concurrent task = 1 (default) if it reduces memory pressure,
default LLAMA_FIT_TARGET=2560, tune ubatch/batch size defaults for a
long stable run on 6.88GB available RAM, tune other flag defaults too."

- **`Config.llm_max_concurrent` 2 -> 1**, explicitly superseding the
  v0.44.0 "permanent floor of 2" (see "Hardware target" above and the
  field's own docstring for the full reasoning/history). `--parallel 1`
  in `scripts/run.sh` already meant a second Python-side in-flight
  request only ever queued behind a server that could serve one at a
  time — reducing to 1 removes that dead weight and, for the Ollama
  backend (which does allocate a real second KV cache per concurrent
  request), directly halves worst-case concurrent memory.
- **`scripts/run.sh` defaults tuned together** rather than piecemeal:
  `LLAMA_CTX_SIZE` 1280 -> 2560 (now synced with `Config.llm_num_ctx`
  instead of silently drifting from it — a footgun flagged but not
  fixed in v0.78.1), `LLAMA_FIT_TARGET` unset -> 2560 (was llama.cpp's
  own 1024 MiB default), `LLAMA_BATCH_SIZE`/`LLAMA_UBATCH_SIZE` unset ->
  512/128 (down from llama.cpp's own 2048/512 — sized for the
  single-lane `--parallel 1` workload this project actually runs, not a
  multi-user server), new `LLAMA_DEFRAG_THOLD` (default 0.1) —
  `--defrag-thold`, a KV-cache defragmentation trigger aimed squarely at
  the "runs stably for years" case: many different prompt lengths
  reusing the same cache over a long session fragments it, periodic
  defrag keeps that from compounding. README's manual command examples
  and flag-explanation bullets updated to match every default above.
- **CPU-only/8GB override path unchanged** — the documented
  `LLAMA_CTX_SIZE=1280 LLAMA_N_GPU_LAYERS=0` recipe still works exactly
  the same, now just an explicit override of a higher bare default
  rather than the bare default itself.

No code logic changed, only config defaults — verified via `Config()`
instantiation and `server.py --help`/`bash -n scripts/run.sh`, no
soak needed (nothing simulation-affecting moved).

## Current state (v0.78.4)

Closes out both Phase J pieces deferred from v0.78.3, per explicit
"do both, ask when in doubt" direction — one clarifying question asked
first (`AskUserQuestion`) on the `Agent.mind` schema's scope, since it
had genuine, different-call-volume-cost forks; user chose "permanent
tier only." See `MAX_MIND_TEXT_CHARS`'s docstring (agents/agent.py) for
the full scope decision this answer produced.

**Agent.mind (permanent tier)**: one-time-authored durable identity
paragraph (values/fears/ambitions/worldview), core cast only, never
revised after authoring. Written the instant an agent enters the core
cast (`Population.maintain_core_cast` now returns the newly-added
agents; `SimulationEngine._author_minds` sets a deterministic template
synchronously — `describe_mind_fallback`, agents/agent.py — then
schedules one optional background LLM call per new agent, new
`llm/mind.py`, same "instant placeholder, LLM silently improves it"
shape as settlement naming). Backpressure-gated like `_maybe_schedule_
dispute` so a genesis-time burst (the initial cast filling all
`llm_core_cast_size` seats in one tick) doesn't compete with routine
cognition/dialogue for the concurrency semaphore; a dropped-under-
pressure agent simply keeps its deterministic placeholder forever (this
job never retries). Fed into `llm/cognition.py`/`llm/dialogue.py`
prompts as "at your core: ..." for core-cast agents. **Explicit scope
cut** (user-approved): the vision's "slow"/"fast" tiers are declared
aliases of already-existing state — `traits`' own slow bounded-random-
walk drift, and `goal_reason`/`working_memory` — not new fields, since
building them would either duplicate existing mechanisms or (for
"slow") require a new recurring LLM job, i.e. real added call volume.
Surfaced in the NPC inspector as "At their core" (core-cast agents
only) — not ambiguity-gated like secrets/mood, since it's closer to a
character bio than a spoiler.

**Secrets via Reflect()**: `llm/beliefs.py`'s `PERSONAL_SYSTEM_PROMPT`/
`build_personal_prompt` gained a sixth, optional `"secret"` field
(left blank almost every call — no deterministic-fallback secret is
ever invented, `parse_secret` has no fallback path) alongside the
existing belief+semantic-memory output — same one monthly call slot,
zero added volume. Planted only when `used_fallback` is false and the
target is core cast, same restriction the v0.78.3 dispute-planted path
already uses (`MAX_SECRETS` stays a small, load-bearing set either way).

Verified: direct fake-client test confirms every core-cast agent gets
*some* mind text immediately (deterministic placeholder) and the
LLM-authored version lands when the call succeeds; a forced Reflect()
call with a fake client returning a `"secret"` field plants it on the
target core-cast agent; `mind`/`secrets` round-trip exactly through
to_dict/from_dict; `scripts/verify_native_soak.py` (2 seeds, 1500
ticks) byte-identical — `maintain_core_cast`'s new return value touches
no native module.

## Current state (v0.78.3)

Continuing Phase J's roadmap per explicit direction, with a standing
constraint attached: "always keep llama memory pressure in mind, and
optimize whenever/wherever you feel the need in existing as well as old
code." Two things follow from that constraint directly, not just the
new feature.

**Secrets & lies (Phase J piece, scoped down)**: `Agent.secrets`
(`agents/agent.py`, cap `MAX_SECRETS=2`, FIFO) — planted only by a
hardened "feud" dispute outcome (`SimulationEngine._maybe_schedule_
dispute`'s existing `apply()` closure calls the new `push_secret`
helper), core-cast only. Deliberately **not** a new LLM output field —
a deterministic derivation from the outcome the model already returns,
so this adds zero call volume and zero JSON-schema risk for the model
to get wrong, in keeping with the memory-pressure directive (more
schema fields per call risk more retries/garbled-output fallbacks, not
just more tokens). `llm/dialogue.py`'s prompt surfaces a speaker's
secret only when it's actually about the other person in that exchange
(matched by name), and its system prompt now explicitly instructs the
model to let it surface as tension/deflection rather than stating it
outright. Reachable only via the dev console/raw `/state` JSON, same as
`Settlement.mood`/`temperament` — a "secret" spelled out in the main
NPC inspector would defeat the point. **Deferred**: Reflect() planting
secrets of its own, and the full permanent/slow/fast `Agent.mind`
schema — both real Phase J pieces still open, held back pending their
own budget discussion (mind schema in particular implies a genesis-
style one-time LLM call per core-cast entry, which is a real, if small,
addition to call volume).

**Memory-pressure pass over existing code**: `PROMPT_RECENT_EVENTS`
lowered 50 -> 40 (`simulation/engine.py`) — now that v0.78.0's
`recent_events_diverse` feeds every settlement-level prompt, 40 diverse
rows carry comparable narrative signal to 50 undiverse ones did, for
~20% less prompt-token cost on the largest prompts in the codebase (a
smaller prompt shortens how long a request holds its KV-cache slot, one
of the "reducing swap" levers documented in v0.78.1/.2). Also did a
fresh audit for unbounded Python-side growth in older modules
(`memorials`/`omen_history`/institution belief lists in `settlement/
buildings.py`) per the "old code too" instruction — all confirmed
already capped from prior passes; no new fix needed there, recorded so
a future session doesn't re-check the same ground.

Verified: direct `_maybe_schedule_dispute` call against a fake client
forcing a "feud" outcome plants a secret on both core-cast parties,
confirmed present in `llm/dialogue.py`'s built prompt; `Agent.secrets`
to_dict/from_dict round trip exact; `scripts/verify_native_soak.py` (2
seeds, 1200 ticks) byte-identical — this batch touches no native
module.

## Current state (v0.78.2)

Direct follow-up: "meant to run stably for years... how do I reduce or
eliminate swapping... is population growth to 301 healthy?" Three parts.

**Population growth is healthy, not a memory lever**: reassured and
documented explicitly (new README section) — `POPULATION_CAP=400` is
the project's own designed equilibrium (see the "Post-rework
equilibrium note" diagnostic-history entry), the LLM core cast is
fixed-size regardless of population (`llm_core_cast_size`), and the KV
cache is a startup-time allocation that never scales with population or
session length. 301 is expected, on-track, and unrelated to the swap
symptom.

**Closed a documented gap**: `Config.metrics_log_retention` (new,
default 20,000 rows ≈ 55 years of daily metrics) + `_prune_metrics`
(`persistence/snapshot.py`, same shape as `_prune_events`), wired into
`save_snapshot`'s existing prune transaction and a new `--metrics-log-
retention` CLI flag. `metrics` was the one table v0.71.0's "runs
forever" audit explicitly left unpruned, deferred with "revisit only
for multi-year sim runs" — a live request for exactly that made the
deferred condition true. Verified: a 2000-tick soak with retention=5
confirms the table stays capped and `recent_metrics`/`/metrics` keep
working.

**Eliminating (not just reducing) swap**: added `LLAMA_MLOCK=1` (`scripts/
run.sh`, opt-in, `--mlock`) — pins llama-server's memory resident,
converting silent swap-degradation into a loud startup failure/OOM-kill
if undersized. Documented as a "size first, then lock" two-step, not a
default, since locking an undersized allocation just moves the failure
earlier (which is the point, for unattended years-long operation) but
still requires correct sizing first. New README section ("Running
stably for years") consolidates this with the v0.78.1 config pull-back,
`--cache-type q4_0` as a further KV-cache lever, and operational
guidance (process supervisor + restart-on-crash, periodic diagnostics
checks, zram-over-disk-swap) — matching CLAUDE.md's standing "config,
not code" pattern for this class of problem.

## Current state (v0.78.1)

Direct response to a live `/diagnostics` report ("still a lot of memory
pressure in long term game with local LLM") — the first live diagnostic
this project has gotten with the actual numbers, not just a symptom
description. Confirms the standing lesson definitively rather than
re-guessing at it: at population 301 / 13,094 ticks, `system_memory`
shows this Python process at a flat, clean **57.9MB RSS / 11.1MB swap**
(consistent with every prior soak — no leak here, again), while
`llama-server` itself sits at only **121MB RSS but 2048MB (2GB) in
swap**, with system `mem_available` down to 174MB of 7046MB total. Low
RSS + huge swap on the LLM server is the signature of its fixed
up-front KV-cache/compute-buffer allocation (`--ctx-size × --parallel`)
sitting mostly cold and getting paged out as system-wide pressure
mounts over a long session — not a Python-side leak to chase further.

**Response**: pulled `Config.llm_num_ctx` back 3072 -> 2560 and
`Config.llm_num_predict` back 512 -> 448 (both now sit two corrections
below the original v0.72.3 GPU-offload-optimistic numbers — see their
docstrings in `config.py` for the full lineage), updated every README
example command to match. Added two new zero-risk `scripts/run.sh`
levers, omitted unless set: `LLAMA_BATCH_SIZE`/`LLAMA_UBATCH_SIZE`
(`--batch-size`/`--ubatch-size` — shrink the compute-buffer allocation
independently of the KV cache). Documented the shared-memory-iGPU angle
explicitly in the README's Radeon 740M/780M section: on that hardware
"VRAM" is drawn from the same system-RAM pool `--ctx-size` reserves
against, so `--fit-target`/`LLAMA_FIT_TARGET` (already existed, now
better-documented as a memory lever, not just a VRAM one) trades a
little offload for headroom.

**Also checked and ruled out** (not the cause, but worth recording so a
future session doesn't re-chase them): `dialogue_cooldown_entries`
(11,746) and `relationship_entries` (23,382, avg 77.7/agent) both read
high in isolation, but both are pruned by existing, working mechanisms
(`due_for_dialogue`'s staleness prune at `cooldown_ticks * 8`;
relationships decay-to-zero + death) — genuinely bounded by population²
and session length within that pruning horizon, not literally
unbounded, and this process's own flat 57.9MB RSS proves neither is
actually costing real memory. Left unchanged.

**Not fixed, because it isn't a code bug**: this is real hardware
running tighter than its previously-"confirmed working" settings
assumed, now with a much larger population (301, vs. the smaller scale
earlier tuning passes were sanity-checked against) sustaining that
pressure over a much longer session than earlier soaks covered. The fix
is config, same as every prior memory-pressure fix in this project's
history — report back what a fresh `/diagnostics.system_memory` reading
shows after adopting 2560/448, and if it's still swapping, the next
levers in order are: `LLAMA_BATCH_SIZE`/`LLAMA_UBATCH_SIZE`, raising
`LLAMA_FIT_TARGET`, dropping `--cache-type-k/-v` to `q4_0`, or sizing
the model down to `qwen3:1.7b` (already documented in the 8GB section).

## Current state (v0.78.0)

Phase J start (docs/VISION-2026-07.md, "Deeper Minds"), scoped down to
one coherent, zero-added-call-volume slice per explicit user direction
to keep optimizing LLM memory pressure while extending psychological
depth — three asks: event-triggered psychological updates, memory
abstraction, and event diversity.

**Semantic memory + event-triggered Reflect()**: `Agent.semantic_
memories` (new, `agents/agent.py`, cap `MAX_SEMANTIC_MEMORIES=3`,
strictly FIFO) is the vision's third memory layer — a condensed lasting
self-theory ("I've learned to keep something in reserve"), distinct
from episodic `memories` (individual events) and `beliefs` (settlement-
scale-shaped theories). Written by extending the existing monthly
per-agent `_maybe_schedule_personal_belief` job (`simulation/engine.py`)
rather than adding a parallel job — same one LLM call/month now returns
both a belief revision AND a distilled semantic memory
(`llm/beliefs.py`'s `PERSONAL_SYSTEM_PROMPT`/`build_personal_prompt`
gained the second field; `parse_semantic_memory`/`push_semantic_memory`
are new). **Candidate selection is now significance-first**: prefers a
core-cast agent with a notable emotion or active feud
(`_is_significant_moment`, reused from v0.77.0's cognition gate) over
the old uniform "any agent with memories" pool, falling back to the old
pool when nothing stands out — this is the "psychological update after
important events" ask; goal updates (already LLM-gated on significance
since v0.77.0) and emotion updates (already deterministic/event-driven
since Phase I) needed no new mechanism, only this reflection layer was
missing. Semantic memories feed back into `llm/cognition.py`'s and
`llm/dialogue.py`'s prompts (one line each, freshest entry only, kept
small deliberately) alongside `working_memory`'s "Just now" line.
Verified: `_maybe_schedule_personal_belief` called directly against a
fake client with an emotionally significant core-cast agent present —
that agent (not a random one) receives both the belief and the semantic
memory; a to_dict/from_dict round trip is exact (additive-only
serialization, legacy snapshots default to `[]`).

**Event diversity**: `persistence/snapshot.py`'s new `ROUTINE_EVENT_
CATEGORIES` (calendar ticks, farm-planted, construction-started/
completed, recovery, wildlife-recolonized) + `recent_events_diverse`
cap how many routine rows can occupy an LLM prompt's event window —
root cause of the live "chronicles/conversations are dominated by
weather and farming" complaint (there's no literal weather-event
category; the actual culprits are routine physical/calendar events
outnumbering social ones many-to-one). Swapped into the 9 genuine
LLM-prompt call sites in `simulation/engine.py` (chronicle, tradition,
invention, festival, caravan, town_brain, beliefs, personal_belief/
reflection, institution_belief, omen); deliberately left the plain
`recent_events` at the temperament/mood-tracking call site (needs the
literal stream to count real fortune, not a diversity-adjusted sample)
and at the public `/events`/`/history` API (nothing is ever hidden from
a reader, only resampled for what a prompt happens to draw from).
Measured on a 6000-tick soak: routine share of a 200-row raw window
70% -> 32% of a diversity-adjusted 50-row window.

**LLM memory pressure**: this batch adds zero new LLM call volume (the
Reflect() extension reuses personal_belief's existing monthly call
slot) while widening what one call produces — the "maximize emergence
per LLM call" mantra (docs/VISION-2026-07.md) applied concretely rather
than restated.

**UI**: NPC inspector gained a "Their own reflections" section
(`interface/static/app.js`) showing `semantic_memories` + the agent's
own private `beliefs` (previously written but never surfaced anywhere,
retrofit opportunistically per the standing UI-surfacing rule) —
distinct from the existing "What the village believes about them"
section (settlement-wide theory about the agent, not their own).

**Not done this slice** (Phase J's fuller scope, deferred): the
permanent/slow/fast `Agent.mind` schema, `Agent.secrets`, and a true
weekly Reflect() cadence independent of the monthly personal_belief
slot — this version deliberately reused the existing monthly job to
keep the "zero added call volume" property; a higher-frequency Reflect()
would need its own budget discussion first. "Greater event diversity"
above addresses the *prompt-sampling* half of that ask; broadening which
event *kinds* get generated in the first place (more social/dramatic
event sources, not just less routine-event crowding) is a separate,
larger piece not attempted here.

## Current state (v0.77.0)

Batch response to a live report: `calls_dropped_backpressure` climbing
to ~400 after 2800 ticks, plus a request to redesign the cognition
scheduler around "maximize emergence per LLM call" rather than routine
daily cadence, disable llama.cpp's reasoning/thinking output, add
memory-reduction flags, and audit for real memory growth. Four parts.

**Cognition significance gate** (`simulation/engine.py`): the root
cause of the backpressure climb — every core-cast agent's *routine*
once-per-sim-day goal reevaluation (`due_for_cognition`) unconditionally
spent an LLM call, on top of genuine emergencies
(`due_for_triggered_cognition`: critical hunger, fresh grief). A
routine "should I gather or socialize today" day is exactly what the
trait+emotion-aware deterministic `fallback_goal` (Phase I) already
handles well — new `SimulationEngine._is_significant_moment` (notable
emotion present, or an active feud) now gates whether a *routine* slot
is worth the model's discretion at all; triggered emergencies bypass
the gate entirely (already significant by construction). Measured with
a fake always-succeeding LLM client over 2800 ticks/30 agents/14-core
cast: `calls_dropped_backpressure` 0 (was ~400), `calls_attempted` 265
against ~406 routine-slot opportunities — most routine days now cost
nothing, LLM richness concentrates on real drama. `llm_max_concurrent`
(the permanent floor) is untouched — this is a volume fix, not a
concurrency one. Same significance signal (`_is_significant_pair`,
`agents/population.py`) now stably sorts `due_for_dialogue`'s core-core
candidates so a feuding or emotional pair wins the limited
`MAX_LLM_DIALOGUES_PER_TICK` slots over an ordinary chat, without
changing that cap.

**llama.cpp reasoning off + flash attention** (`scripts/run.sh`,
README): `--reasoning off --reasoning-budget 0` (confirmed working,
new default) — every prompt here wants one short strict-JSON answer,
never a `<think>` block a hybrid-thinking model (Qwen3 and similar)
would otherwise burn tokens/latency/memory on. `--flash-attn on` (new
default) — lower attention memory, faster inference on supported
backends. Both are env-var-gated (`LLAMA_REASONING`/`LLAMA_FLASH_ATTN`)
and omit-the-flag-if-empty for an older llama-server build.

**Memory audit — no Python-side leak found**: a clean 12,000-tick real
`SimulationEngine` soak (LLM disabled, 30 agents, full event churn —
births/deaths/disputes/trade/disease) showed RSS flat at 37.7→37.8MB
and GC object count stable (~22,100 ± 150, pure noise) the entire run.
Separately audited every prompt-building call site (cognition/
dialogue) for unbounded growth: `PROMPT_RECENT_EVENTS=50`, `agent.
memories`/`beliefs_about_agent` both capped (`MAX_AGENT_MEMORIES=8`,
`MAX_BELIEFS=12`/`MAX_PERSONAL_BELIEFS=4`), `colocated_names` sliced to
4 — nothing grows with tick count. Conclusion: the reported growth is
not this codebase's Python process — it matches this file's own
standing lesson ("swap pressure has always been Ollama-side call
volume/config," not this process, verified repeatedly since v0.43.0).
Next step for the user: read `/diagnostics.system_memory` during a
live growing-memory episode (it already attributes RSS to self vs. each
Ollama/llama-server process) to confirm which process is actually
growing; the reasoning-off + flash-attn flags above are the concrete
levers if it's the LLM server. Not something reproducible in this
environment (no GPU/LLM here) — report back what `system_memory` shows.

**UI**: per-agent `Agent.emotions` (Phase I, v0.76.1) is now surfaced
in the NPC inspector — a new "Feeling" section, same `npc-stats-row`
styling as traits/skills, emoji + label + magnitude for each notable
emotion (or "calm" when none clear the threshold). `Settlement.mood`
stays dev-console/raw-JSON-reachable only, same as `temperament` —
Phase G ambiguity discipline applies to the settlement-level number,
not the plain per-agent one. New standing rule (see "Workflow rules"):
every future feature gets a UI-surfacing pass in the same batch, not a
deferred follow-up.

Verified: the fake-client cognition-volume measurement above; the
12,000-tick RSS soak; `scripts/verify_native_soak.py` (3 seeds, 1500
ticks, byte-identical — this batch touches no native module).

## Current state (v0.76.3)

Closes out Phase I: **layered memory v1**, the third piece the roadmap
scoped and v0.76.1 deliberately deferred. `agents/agent.py`: `Agent.
memories` (episodic, unchanged name/shape for backward compat) is no
longer strict FIFO — a new index-aligned `Agent.memory_salience` list
(maintained solely by `agents/population.py`'s `_remember`, the only
mutator of `memories`) scores each memory at write time from the
agent's *current* `emotions` (baseline 0.2, up to 1.0 under real
fear/grief/joy/anger); eviction at `MAX_AGENT_MEMORIES` now drops the
lowest-salience entry (ties toward oldest) instead of always the
oldest, so a memorable experience genuinely outlives a mundane one —
verified directly (fill to cap with mundane memories, inject one
high-salience memory, push 8 more mundane ones through: the memorable
one survives). A second new field, `Agent.working_memory` (cap 2,
strictly FIFO, written at the same `_remember` call), is the vision's
distinct "fast" layer: once salience-weighted eviction can drop a
recent-but-mundane memory, `memories[-1]` is no longer guaranteed to be
"the literal last thing that happened" — `working_memory` is.
`llm/cognition.py`/`llm/dialogue.py` prompts gained a "Just now: ..."
line sourced from `working_memory`'s freshest entry, shown only when
it isn't already present in the episodic slice being read (a shared
`just_now_text` helper avoids duplicating the sentence in the common
case). Both new fields are additive-only serialization; `from_dict`
defensively pads/truncates `memory_salience` to match `memories`'
length rather than trusting a legacy or hand-edited snapshot raw.

**Not native-ported, deliberately**: the eviction scan is a `min()`
over at most `MAX_AGENT_MEMORIES=8` entries, firing only inside
`_remember` — an event-driven call (births, deaths, dialogue,
disputes, trades…), not something that runs every tick for every
agent the way `decay_emotions`/`_update_needs` do. This is exactly the
distinguishing question v0.72.13's correction sharpened ("not 'does
this loop', but 'does it run routinely at scale'") — an 8-element scan
on a rare event is nowhere near a hotpath, so this stays pure Python
per the standing "escalate only with a measured need" rule.

Verified via a direct eviction test (documented above), a 6000-tick
real `SimulationEngine` soak (LLM disabled) confirming `memory_
salience` always stays index-aligned with `memories`, `working_memory`
never exceeds its cap, salience stays in [0.2, 1.0], and a to_dict/
from_dict round trip is exact; plus `scripts/verify_native_soak.py`'s
full-state hash soak (3 seeds, 1500 ticks), unaffected since this
slice touches no native module, byte-identical throughout. **Phase I is
now fully shipped** (emotions, mood, layered memory); next milestone
is Phase J (Deeper Minds) per docs/VISION-2026-07.md, on explicit
go-ahead.

## Current state (v0.76.2)

Direct follow-up to v0.76.1, per explicit user instruction to write new
Phase I code in C++ from the start where it fits — applying R6's
"pure math over already-resolved primitives" discipline to the new
emotion system rather than leaving it Python-only and revisiting later.
**New native module**: `decay_emotions`'s per-tick multiply
(`agents/agent.py`) → `cpp/src/emotion_decay.cpp` — same "runs
unconditionally every tick, for every agent" shape module 6
(`_update_needs`) established as the highest-value native-port
category. Takes the four emotion axes as plain doubles (a missing key
reads 0.0 in, decays to a no-op 0.0 out) since `Agent.emotions` is a
sparse dict, not a fixed-slot struct — pybind11's STL-copy-not-
reference gotcha (v0.72.0's standing note) means the dict itself can't
cross the boundary usefully anyway; the <0.005 prune-vs-keep decision
and sparse-key bookkeeping stay in Python, same split as `_update_
needs`' own object-lookup/arithmetic division. `tick_mood` (settlement-
level, monthly) was evaluated and deliberately left Python — it already
reuses the native `bounded_random_walk_step` module for its own bounded
step, and the aggregation loop over a settlement's agents runs once a
month, not hot enough to justify a second native call per this
project's "escalate only with a measured need" rule (the same
reasoning v0.72.2 applied to `_nearest_material_tile`). Verified via
20,000 randomized native-vs-Python-fallback trials (0 mismatches), a
500-tick direct `decay_emotions()` A/B sequence with bump events mixed
in (0 mismatches), and `scripts/verify_native_soak.py`'s full-state
hash soak with two new toggles added, every native module on vs. off,
byte-identical.

## Current state (v0.76.1)

First implementation slice of the long-term vision: **Phase I, Inner
Life** (docs/VISION-2026-07.md) — deterministic, near-zero-LLM-cost,
feeds every later prompt. Two pieces landed; layered memory (working/
episodic split) is deliberately deferred to its own slice (see below).

**Per-agent emotions** (`agents/agent.py`): `Agent.emotions` — a new
0..1 dict (fear/joy/grief/anger, missing key reads 0.0, same convention
as `traits`) — distinct from `traits`' -1..1 near-permanent disposition:
this is the vision's "rapidly changing" layer. `decay_emotions` runs
every tick right after `_update_needs` (small entries pruned below
0.005, same discipline as the relationship/trust dicts); `bump_emotion`
fires at real lived events already wired into `agents/population.py`:
predator attack survived (fear), sustained critical hunger (fear,
scaled per tick), illness onset — both outbreak index case and
transmission (fear), birth (joy, both parents), festival attendance
(joy, every colocated pair), dispute reconciliation (joy) vs. hardened
feud (anger), and a death that lands real grief today — parent/child or
close-bond (grief). Consumed in three places: `llm/cognition.py`'s
prompt ("Right now you feel afraid"), `llm/dialogue.py`'s prompt (same
pattern as its existing `personality_bits`), and — the "even the
fallback path is real" rule — `fallback_goal` now takes an `emotions`
dict and a notable fear/grief overrides the personality/id%3 split
toward REST ("wants to feel safe") or WANDER ("wants to be alone")
respectively, so this is live even with the LLM disabled.

**Settlement mood** (`settlement/buildings.py`): `Settlement.mood` — a
new -1..1 dict (hope/fear/grief/suspicion) living on the existing
`SettlementDisposition` component alongside `temperament`, but a
different mechanism: `tick_mood` (called monthly from
`_maybe_tick_temperament`, alongside `tick_temperament`) tracks each
axis toward the *live aggregate* of that settlement's own agents'
emotions (joy->hope, fear->fear, grief->grief, anger->suspicion — the
literal "individual minds aggregate into collective psychology" layer
the vision's hierarchy diagram calls for), blended with mean-reversion
and jitter via the existing `bounded_random_walk_step` native module
(module 12) — same call shape as `tick_temperament`, `extra=0.0`
folded into `step`. `MOOD_TRACKING_WEIGHT=0.3` means a sustained shift
closes most of the gap over 3-4 months, not an instant snap.
`Config.phase_g_intensity=0.0` holds mood flat exactly like temperament.
Reachable via `summary()`/`to_dict()` like every other Phase G number,
never labeled "mood" in the UI (ambiguity discipline unchanged).

Both pieces are additive-only serialization (`to_dict`/`from_dict`,
legacy snapshots missing `emotions`/`mood` default to `{}`) — verified
via a 9000-tick real `SimulationEngine` soak (LLM disabled, crosses 3
month boundaries) confirming emotions stay bounded [0,1], mood stays
bounded [-1,1], mood visibly moves in response to real in-run events,
and a to_dict->from_dict->to_dict round trip is stable; plus the
existing `scripts/verify_native_soak.py` full-state hash soak (native
vs. Python-fallback `bounded_random_walk_step`, byte-identical) since
`tick_mood` reuses that native module. **Deferred to its own slice**:
layered memory v1 (`Agent.memories` split into working/episodic with
salience-weighted eviction) — the third Phase I piece the roadmap
scoped, held back so this slice stays reviewable and each piece gets
its own verification pass, same staging discipline as v0.74.3's
storage-only AgentTable before v0.75.0 wired it in. Phases J-N remain
fully unstarted.

## Current state (v0.76.0)

Design-only pass, per explicit user instruction ("Do not implement
anything yet"): the long-term design vision delivered in chat was
audited against the codebase and turned into a standing section above
plus the full roadmap in **docs/VISION-2026-07.md** — audit tables
(exists / partial / missing per vision item), the
extend-don't-duplicate map (new jobs → the `_maybe_schedule_*` registry
+ `MONTHLY_JOB_DAY`; religion/ideology/factions → the beliefs +
institution machinery; mood → the temperament/`bounded_random_walk_
step` pattern; Town Consciousness v2 → Phase G extended), LLM budget
arithmetic (full roadmap ≈ +4.6 calls/day against the 320 ceiling),
two flagged rule conflicts (§2), and phases I–N with per-phase
verification approach. Key audit finding: the vision is the codebase's
own trajectory — the deterministic layer + C++ track need no new plan,
and the real work is the cognition hierarchy (layered memory, emotions,
rumor distortion, dreams, factions, religion, narrative themes,
consciousness v2). No code changed; v0.75.2's three live-report fixes
(weather rain floor, dialogue temperature/garble filter, llama.cpp
`--fit`) remain the latest behavior changes. Next milestone when
implementation is green-lit: **Phase I — Inner Life** (deterministic
emotions + settlement mood + layered memory v1, near-zero LLM cost,
feeds every later prompt).

## Current state (v0.75.0)

Explicit user directive: pursue the "full C++ engine, don't break the
game at all" goal. Those two constraints together fix the method —
incremental slices, each verified byte-identical against the current
Python as ground truth *before* the Python is removed, extension always
optional so a failed build falls back cleanly. Big-bang rewrite is off
the table (no per-slice ground truth); storage-only is the first leg,
not the destination. This version ships the first slice of the
object-graph track that the v0.74.3 `AgentTable` primitive was built
for: **`AgentTable` is now wired into live `Population.agents`.**

Design (the compatibility-shim pattern `TerrainGrid`/`TerrainRow`
established, applied to the agent object graph): new
`agents/agent_store.py` `AgentStore` — an **id-keyed** structure-of-
arrays store over the native `AgentTable`; `Agent` (converted from a
`@dataclass` to a hand-written class) exposes its 12 dense scalar
fields (`x`/`y`/`hunger`/`energy`/`state`/`age_ticks`/`max_age_ticks`/
`starving_ticks`/`sick_ticks`/`immune_ticks`/`goal`/`settlement_id`) as
`@property` accessors that route through the store once `Population`
adopts the agent. The six variable-size per-agent dicts/lists
(relationships/trust/inventory/memories/skills/traits, plus beliefs/
parents/travel_target/goal_reason/name) stay ordinary Python
attributes — they never flattened into a fixed schema and don't move.
The store's public API is keyed by agent **id, never slot**: it
resolves id→slot internally on every access and absorbs the native
table's swap-with-last slot churn into that one map, so no Python-side
Agent handle can ever point at a stale slot — the entire staleness bug
class the v0.74.2 scoping flagged is eliminated at the API boundary
rather than guarded at ~700 call sites. `self.agents` stays an ordered
`list[Agent]`, so iteration order is fully decoupled from slot order.

**Zero of the ~700 scalar touch sites needed editing** — the property
shim makes `agent.hunger`/`agent.x = …` work unchanged. The only edits
were the enum↔int code maps (agent.py, next to the enums; must match
cpp/src/agent_table.cpp's header — never renumber an existing code or a
resumed native world misreads saved scalars), `Population.__post_init__`
(builds the store when native, adopts every agent — covers both
`spawn_initial` and `from_dict`), and three one-line adoption/removal
hooks at the only three list-mutation points (birth `extend`, migrant
`append`, death `self.agents = survivors` → remove `dying_ids` from the
store). **Fallback stays byte-identical to the old dataclass**: no
native extension → no store → scalars live in `_x`/… locals exactly as
before.

Verified: (1) full-`World.to_dict()`-per-tick soak
(`scripts/verify_native_soak.py`, new `agent_store` toggle), native
(AgentTable) vs fallback (detached) byte-identical every tick across
multiple seeds at 2,000 ticks and a 12,000-tick/3-seed run long enough
to span births (agents mature at 4,000 ticks); (2) a direct death +
swap-with-last test confirming survivors stay correctly id-mapped after
the dead are removed and reindexed (native ≡ fallback); (3) a
save→`from_dict`→reload round-trip proving the store rebuilds
identically on load and is live afterward. **Not yet ported: the agent
tick LOGIC** — `population.py`'s methods still run in Python, now
reading/writing scalars through the C++ store. Porting those method
bodies to run in C++ over the table is the next leg toward the full
engine, one method-group at a time, each verified against the Python it
replaces before that Python is deleted. See docs/REFACTOR-2026-07.md's
"R8 slice 3 wire-in."

## Current state (v0.74.3)

Explicit user directive: pursue the Agent/Settlement/Population port
despite v0.74.2's finding of no measured performance need — for
architectural completeness, not a performance response. Scoped the
real risk before writing code: `Agent`'s scalar fields are touched
~700 times in `agents/population.py` alone, almost always interleaved
with the six variable-size per-agent dicts/lists (`relationships`,
`trust`, `inventory`, `memories`, `skills`, `traits`) that can't
flatten into a struct-of-arrays — a much larger, riskier surface than
terrain's ~60 clean indexing sites. Also confirmed: agent ids are
monotonic/never reused, nothing holds a raw `Agent` reference across a
tick boundary (everything re-resolves via `.id`), and
`POPULATION_CAP=400` makes a naive swap-with-last removal cheap.
**Shipped only the storage primitive this version**: `AgentTable`
(`cpp/src/agent_table.cpp`) — a true structure-of-arrays for the 12
scalar fields, verified via a 20,000-operation randomized fuzz test
against a parallel Python reference (0 mismatches) plus explicit
bounds-check tests. **Deliberately NOT wired into `Population.agents`
this version** — that needs a compatibility-shim `Agent` wrapper class
(same idea as `TerrainRow`) plus the ~700-site verification pass,
staged as its own follow-up rather than rushed alongside the storage
primitive, the same discipline the terrain port's own research pass
established. See docs/REFACTOR-2026-07.md's "R8 slice 3" for the full
scoping writeup and the concrete next-session plan.

## Current state (v0.74.2)

Design-only pass (no code moved), in response to a generic "continue"
after v0.74.1's terrain-grid port. Investigated whether `Agent`/
`Settlement`/`Population` (the queued-next R8 item) or anything else
in the codebase is a genuine next native-port target. Findings: `Agent`
doesn't fit the `TerrainGrid` storage-port pattern (many variable-size
per-agent dicts, not two dense scalars) — its applicable pattern is
what module 6 already does (extract primitives, compute in C++, write
back, no storage change). Re-checked every O(N)/O(N²)-flagged comment
in the tick loop; both previously-flagged quadratic spots are already
resolved. **No measured-need candidate remains anywhere in the
codebase for further native porting** — R6/R7's queues are closed,
R8's two safe storage slices (`SimClock`, terrain grid) are shipped.
Per this project's own standing "escalate only with a measured need"
rule (the same discipline that's governed every module since v0.72.0),
recommend treating the native-port track as complete for now, not
permanently closed. See docs/REFACTOR-2026-07.md's R8 section for the
full three-part writeup. Asked the user how they'd like to proceed
given this finding.

## Current state (v0.74.1)

R8 slice 2, per explicit user directive to "start" the terrain-grid
port the v0.74.0 scoping had queued next. `World.terrain` is now a
`TerrainGrid` (`world/terrain.py`) — the first R8 module porting
object-graph STORAGE, not an isolated pure function. Design: `Terrain
Grid`/`TerrainRow` are a drop-in compatibility shim implementing the
exact same `terrain[y][x]`/`terrain[y][x] = Tile(...)`/`len(terrain)`/
`for row in terrain: for tile in row` protocol a plain
`list[list[Tile]]` already had, backed by a compiled flat-array store
(`cpp/src/terrain_grid.cpp`, elevation as `vector<double>`, biome as a
plain int index into `tuple(Biome)` — the full 9-member enum including
RIVER, unlike `terrain_evolution.py`'s RIVER-excluding `BIOME_ORDER`)
when the native extension is built, else a genuine nested list. Tiles
are materialized on demand from the flat arrays, never cached, so no
call site can hold a stale reference across a mutation. This is why
**zero of the ~60+ existing call sites needed to change** — the whole
point of the "compatibility shim" reading the v0.73.1/74.0 scoping
docs flagged as the safe way to do this. Wired into `World.create_new`/
`from_dict` via `TerrainGrid.from_nested(...)`; `to_dict` needed no
change since iteration already produces the same nested structure.
Verified via randomized read/iteration/mutation equivalence (native vs
fallback, 500 mutations, 0 mismatches), a full engine test (creation →
3000 ticks → snapshot save → reload → full terrain diff, 0
mismatches), a live-server + browser-screenshot smoke test confirming
the map renders identically, and the full-state verification harness
(`scripts/verify_native_soak.py`, now including this toggle) — all
nineteen native modules match byte-for-byte across every tick, 4
seeds, 6000 ticks each. Remaining object-graph pieces (`Agent`/
`Settlement`/`Population` themselves) are unstarted — those have real
cross-references to each other (unlike `SimClock` or the terrain grid,
both fully isolated) and need their own design pass per the R8 doc's
own risk framing.

## Current state (v0.74.0)

Two items: bridges (a real gameplay feature closing the "True water
transport" gap in "Known architectural gaps" below), and continued R8
progress. **Bridges**: new `BuildingKind.BRIDGE` — unlike RAFT (passive
fishing bonus only), a STANDING bridge's `bridge_span` water tiles
actually become walkable via `Population._is_walkable`'s new
`bridge_tiles` parameter (same threading shape as the existing
`mountain_unlocked` era-gate, through `_step_toward`/`_bfs_step`/
`_reachable_tiles`/`_dispatch_movement`). Founded like a vehicle — a
colocated group on a water-adjacent shore tile rolls `BRIDGE_CHANCE_
PER_TICK`, then `_find_bridge_span` (bounded multi-source BFS through
water, capped at `BRIDGE_MAX_SPAN=6`) searches for the nearest
not-already-reachable opposite shore. `Building.x/y` stays the land
anchor so existing agent-pathed construction/repair/decay need zero
special-casing; `bridge_span` is fixed at founding. Bridges pool across
every settlement into one shared passability set
(`_bridge_tiles_from_settlements`), same "anyone can use it" shape as
roads. Verified via synthetic-terrain unit tests of `_find_bridge_span`
(narrow strait found, over-wide gap correctly rejected, already-
connected shores correctly rejected), a direct engine test confirming
an agent's `travel_target` actually routes across a STANDING bridge
through a real `_tick_once()` loop, `Building.to_dict`/`from_dict`
round-trip + legacy-snapshot backward compat, and a 6000-tick/3-seed
regression soak confirming zero behavior change when no bridge exists
(the common case). **R8**: new `scripts/verify_native_soak.py` — the
"heavier full-state-diffing verification harness" the v0.73.1 scoping
doc called for building before the terrain-grid slice. Hashes the
complete `World.to_dict()` every tick (not just the event-hash soak's
narrated consequences) across every native module's toggle in one
pass; sanity-checked to actually detect divergence before trusting a
"no divergence" result. All eighteen native modules pass full per-tick
state equality across a 6000-tick, 4-seed run. Terrain-grid porting
itself has not started — this is the prerequisite tooling, per the R8
doc's own ordering.

## Current state (v0.73.3)

Two small items. **Build flags**: `setup.py`'s native extension now
builds with `-O3 -march=native -mtune=native` (non-Windows). User asked
for `-O4`, which doesn't exist in GCC/Clang (both cap at `-O3`) —
substituted the real max standard optimization level; `-Ofast` was
considered and declined since it changes float semantics in ways that
could affect the byte-identical-vs-Python verification every module
here depends on. `-march=native` is safe only because this extension is
always built locally on the machine that runs it, never shipped as a
prebuilt wheel — flagged explicitly in setup.py's comment so a future
change toward wheel distribution catches this. Re-ran the 4-seed/6000-
tick soak after rebuilding: identical hashes to every prior `-O2` run.
**`world/hydrology.py` fully traced**: `generate_rivers`/`identify_
lakes` are world-creation-only (never called per-tick), so they're
correctly out of scope for the native-port queue regardless of RNG
shape — `tick_lakes` (the only per-tick function in that file) was
already ported in module 12. This closes the R7 opportunistic queue
completely: every function originally flagged has been ported,
individually confirmed not worth porting, or confirmed one-time/
creation-only. Remaining native-port work is entirely R8 (object-graph
+ engine-tick-loop track) — see v0.73.2's entry and docs/REFACTOR-2026-
07.md for the terrain-grid slice queued next.

## Current state (v0.73.2)

Direct response to explicit user confirmation of the R8 question posed
at the end of v0.73.1: both "finish R6/R7" and "port the object graph
plus the engine running world ticks" — pursuing both together. **Module
17**: `maybe_reclaim`'s scan/roll loop → `cpp/src/reclaim.cpp` — the
first callback-into-Python-RNG native module (rather than pre-drawing),
since `maybe_reclaim` has a genuine same-pass dependency (confirmed
unportable via pre-drawing since v0.72.11: an earlier tile's reclaim in
the same pass changes a later tile's forest-neighbor count). The C++
loop calls back into `rng.random` per conditional roll, preserving
exact order/count while still moving the neighbor-scan/branching to
C++. This closes out the R7 opportunistic queue's last individually-
portable item (`tick_flood`/`world/hydrology.py`'s remainder stay
correctly-scoped-as-not-worth-it / not-yet-traced, unchanged from
v0.72.14's assessment). **Module 18**: `SimClock.advance()` →
`cpp/src/sim_clock.cpp` — the first R8 slice, and the first native
module that IS the engine advancing a world tick (runs unconditionally
every tick, the highest call-frequency function in the codebase) rather
than a system running on one. Deliberately tiny scope per the R8 design
doc's own recommendation: pure calendar arithmetic only, `SimClock`
the dataclass/its other properties/persistence untouched. Both modules
verified via direct wrapper-function checks (500-trial terrain A/B for
module 17, a 200,000-tick sequential lockstep A/B spanning years/every
calendar boundary for module 18) plus a 5-seed, 8000-tick cumulative-
event-hash engine soak, all eighteen native modules on vs. off,
byte-identical; live-server smoke test confirmed `terrain_reclaimed`
fires correctly through the browser event feed. Object-graph work
beyond `SimClock`'s pure calendar math (`Agent`/`Settlement`/
`Population`/terrain grid themselves) has not started — the R8 doc's
"reading 2" is confirmed as direction, next slice needs its own design
pass (candidate: the terrain grid, per R8's "least entangled" call).

## Current state (v0.73.1)

Two items, both direct follow-ups to explicit user directives from
v0.73.0. **Native port module 16**: `apply_climate_drift`'s biome-step
mutation (world/terrain_evolution.py) → `cpp/src/climate_drift.cpp` —
unblocks the item v0.72.14 had flagged as needing `classify_with_bias`/
`BIOME_ORDER` exposed to C++. First module where a `Biome` enum value
crosses the pybind11 boundary (as a plain `int` `BIOME_ORDER` index,
converted both ways in Python — no precedent existed for the enum
itself crossing). Caught a real same-pass-dependency bug during
verification: `rng.randrange` sampling is with-replacement, so a
duplicate tile draw's second occurrence must see the first's
already-stepped biome — fixed by calling native per-sample (reading
live terrain state each time) instead of batching all samples into one
call. Verified via 50,000 randomized inputs, 500 direct wrapper-
function A/B runs (0 mismatches post-fix), and the cumulative-event-
hash soak across four seeds at 6000 ticks, all sixteen native modules
on vs. off, byte-identical. Remaining R7 queue: `maybe_reclaim`
(genuine same-pass dependency, not portable this way), `tick_flood`
(too little batchable content), rest of `world/hydrology.py` (untraced).
**R8 scoping**: the "full engine rewrite" directive got a design-first
pass (docs/REFACTOR-2026-07.md, "R8") rather than code — three readings
laid out (finish the opportunistic R6/R7 queue; port the object graph
itself — `Agent`/`Settlement`/`Population`/terrain grid — behind
Python handles; rewrite everything but SQLite/asyncio/FastAPI). No
object-graph porting has started pending user confirmation of scope —
every module shipped so far ports an isolated pure function verified
against the existing Python object graph as ground truth, which is a
categorically different (and much lower-risk) kind of change than
porting the object graph itself, especially with no automated test
suite as a safety net.

## Current state (v0.73.0)

Two explicit user directives, plus a note on the third ("full engine
rewrite in C++") staying on the existing R6/R7 incremental track — see
"Preserve absolutely" and the R6 scoping in docs/REFACTOR-2026-07.md;
this version didn't add a new native module, R6/R7 continue from
v0.72.14's queue next session. **(1) Event feed now LLM-conversation-
only**: `/events`/`/history`/the main UI's Recent Events feed no longer
show deterministic fallback dialogue — only genuine core-cast
LLM-authored exchanges reach the narrative log (`SimulationEngine.
_pending_dialogue_results` gained an `is_llm` flag; `_apply_pending_
dialogue_results` only calls `_log` when it's true). The underlying
mechanic (relationships/trust/gossip, `dialogue_total`) is unchanged
and still runs for every pair — this only trims what reaches the
narrative feed, not what's simulated. Rumor events stay unconditional.
**(2) On-demand simulation summary tab**: new "🧭 summary" panel with a
"Generate summary" button — `POST /summary/request` queues a
`request_summary` intervention, applied via the existing settlement-
job machinery (`SimulationEngine._schedule_summary`, new `llm/
summary.py`). Deliberately NOT gated by `_settlement_job_backpressured`
(that gate smooths the monthly-boundary job cluster; a single
user-triggered request isn't part of it) but still subject to the
daily LLM call ceiling like every other job. Result persists on
`World.sim_summary_text`/`sim_summary_tick` (serialized across
restarts); `sim_summary_pending` is deliberately NOT persisted so a
generation in flight at shutdown loads back as done, not stuck. `GET
/summary` reads off the existing broadcast payload rather than a new
engine call. See CHANGELOG.md for verification detail.

## Current state (v0.72.14)

`tick_wildfire`'s spread step (world/disasters.py) now reuses module
15's `roll_passes_tick` — no new C++ file needed. Re-traced the spread
loop (previously grouped with `maybe_reclaim` as "hard" without
individual verification) and confirmed each (active tile, neighbor)
pair's spread eligibility depends only on pre-loop state
(`active_wildfire_tiles` snapshot + terrain biomes), never on another
pair's outcome within the same pass — own-tile conversion draws no RNG
at all, so it's a plain Python pass; only the neighbor-spread rolls get
batched and handed to the native comparison. Verified via 300 direct
`tick_wildfire()` A/B runs on synthetic fire/terrain state plus the
cumulative-event-hash soak across five seeds at 6000 ticks each,
byte-identical. Correctly-scoped remainder: `maybe_reclaim` (confirmed
genuine same-pass dependency), `apply_climate_drift` (fixed draw count
but needs biome-classification logic exposed to C++), `tick_flood`
(too little batchable content — single-event trigger, not a sweep),
rest of `world/hydrology.py`.

## Current state (v0.72.13)

Native port module 15: `apply_local_activity`'s deforestation roll
(world/terrain_evolution.py) → `roll_passes_tick`
(`cpp/src/roll_batch.cpp`). **Correction to the v0.72.11/12 "RNG-in-
loop is hard" assessment**: re-traced this specific loop and found its
per-tile eligibility depends only on pre-loop state (heat value +
current biome), never on another tile's outcome within the same pass —
unlike `maybe_reclaim` (a forest-neighbor count that changes as earlier
same-pass tiles convert), which genuinely doesn't fit and stays pure
Python. The real disqualifying shape is narrower than "this loop rolls
dice a variable number of times" — it's specifically whether a later
roll's eligibility depends on an earlier roll's outcome within the same
pass. `roll_passes_tick` is a small generic "which pre-drawn rolls beat
their chance" utility, reusable by future R7 code with the same shape.
Verified via 20,000 randomized inputs, 300 direct `apply_local_
activity()` A/B runs on synthetic terrain, and the cumulative-event-
hash soak across four seeds, all fifteen native modules on vs. off,
byte-identical. `maybe_reclaim`/`apply_climate_drift`/`tick_flood`/
`tick_wildfire`/the rest of `hydrology.py` remain queued — each needs
individual re-checking against the actual disqualifying question
rather than assumed hard by association.

## Current state (v0.72.12)

Native port module 14: the flat-damage sweep inside `tick_storm`
(world/disasters.py) → `flat_damage_tick` (`cpp/src/flat_damage.cpp`).
Checked `tick_flood`/`tick_wildfire` too — both roll a data-dependent
number of RNG draws (candidate-tile/fire-spread counts vary), same
hard shape as terrain_evolution.py's loops, so they stay queued.
`tick_storm` qualifies: at most one RNG draw total, and that draw's
own trigger condition is knowable before any loop runs — once decided,
the rest is unconditional `max(0, condition - damage)` across every
building/vehicle, no randomness left. Deliberately does NOT add a
RUINED/BROKEN stage transition at zero condition even though modules
9-10 do — the pure-Python original doesn't either, and a port's job is
to mirror the source, not "fix" it. Verified via 10,000 randomized
inputs plus the cumulative-event-hash soak across four seeds, all
fourteen native modules on vs. off, byte-identical. Remaining
disasters/terrain-evolution/hydrology functions need a callback-into-
Python-RNG pattern to port safely — deliberately not attempted without
a measured need, per this project's standing evaluation discipline.

## Current state (v0.72.11)

Native port module 13: `_wilt_farms` (world/disasters.py, shared by
`tick_heatwave`/`tick_frost`) → `wilt_farms_tick`
(`cpp/src/wilt_farms.cpp`) — solves the RNG-in-loop design question
flagged at the end of v0.72.10 by finding a function that actually
fits: `_wilt_farms` rolls exactly one `rng.random()` per farm plot,
unconditionally, so the draw count is fixed and Python can pre-draw
the whole batch (preserving stream order) before handing it to the
native call. `world/terrain_evolution.py`'s activity/reclaim loops
still don't fit this pattern (their draw count is data-dependent — how
many tiles clear a threshold first) and remain queued, needing their
own design. Verified via 20,000 randomized inputs (0 mismatches), 500
direct `_wilt_farms()` A/B runs on cloned farm grids (0 mismatches),
and the cumulative-event-hash soak across four seeds, all thirteen
native modules on vs. off, byte-identical.

## Current state (v0.72.10)

Native port module 12: a shared `bounded_random_walk_step`
(`cpp/src/bounded_random_walk.cpp`) — noticed while porting `world/
terrain_evolution.py`'s `tick_climate` and `world/hydrology.py`'s
`tick_lakes` level nudge that both share an identical `value =
clamp(value*mean_reversion + jitter [+ extra], -1, 1)` shape with three
existing functions in `settlement/buildings.py`
(`tick_temperament`/`tick_player_standing`/`tick_relation`). Ported once,
wired into all five call sites, rather than writing near-duplicate
functions — same instinct as `util.py`'s `clamp`/`namespaced_rng` dedup
(v0.69.0). RNG draws stay in Python at every call site. Verified via
30,000 randomized inputs against the pure function, direct multi-call
sequences at each of the five call sites, and the cumulative-event-hash
soak across four seeds at 6000 ticks (long enough to span several
months, since these are all monthly-cadence functions), all twelve
native modules on vs. off, byte-identical. Note:
`tick_temperament`/`tick_player_standing`/`tick_relation` are Phase G/
institution mechanics, not physical substrate — R6 rather than R7 — but
the shared function serves both tracks.

## Current state (v0.72.9)

Native port module 11: `compute_weather`'s blend/threshold math →
`compute_weather_blend` (`cpp/src/weather.cpp`) — the first module
whose Python original draws from a seeded `random.Random` stream. RNG
draws stay in Python (reproducing CPython's Mersenne Twister in C++
isn't required — this project's "determinism is not a requirement"
rule, plus the native-port discipline only needs native-vs-Python
parity, not cross-implementation RNG parity); only the baseline+jitter/
clamp/EMA-blend/snow-threshold arithmetic crosses into C++. Verified via
30,000 randomized inputs (0 mismatches), a 20,000-tick direct
`compute_weather()` A/B sequence across all twelve months (0
mismatches — this one matters because the EMA blend makes each tick
depend on the last, so drift would compound), and the cumulative-
event-hash soak across four seeds, all eleven native modules on vs.
off, byte-identical. Queued next: `world/terrain_evolution.py`,
`world/disasters.py`, `world/hydrology.py`.

## Current state (v0.72.8)

Native port modules 9-10, closing out the "building decay/repair math"
R7-queue item: `Settlement.tick`'s building decay/ruin/reclaim pass →
`building_decay_tick`, and its READY-vehicle decay pass →
`vehicle_decay_tick` (`cpp/src/settlement_decay.cpp`). Same per-cell
local-rule shape as `farm_grid_tick` (module 8); x/y/kind (needed only
for event text) stay in Python, native calls return small result-flag
tuples (`just_ruined`/`removed`/`just_broke`) so Python's event-logging
reads a flag instead of re-deriving it. Verified via 20,000 (buildings)
and 10,000 (vehicles) randomized inputs (0 mismatches) plus a
5000-tick, four-seed cumulative-event-hash soak (deliberately longer
than prior soaks to give the comparatively rare ruin/reclaim/breakdown
events more chances to fire), all ten native modules on vs. off,
byte-identical. Queued next: `world/weather.py`, `world/terrain_
evolution.py`, `world/disasters.py`, `world/hydrology.py`.

## Current state (v0.72.7)

Native port module 8: `FarmGrid.tick` → `farm_grid_tick`
(`cpp/src/farm_grid.cpp`) — the first module shipped under R7, and the
cleanest "cellular automata" fit yet: a fixed grid of independent farm
plots, each updated purely from its own prior state plus tick-level
inputs (season multiplier, irrigation adjacency), no cross-cell
interaction — structurally near-identical to `resource_grid_tick`
(module 1). Irrigation adjacency (`is_adjacent_to_water`, a `Tile`-
object lookup) stays Python-resolved, passed in as a plain boolean.
Verified three ways given the extra risk surface of two return
channels (updated plots + a separate rotted-positions list): 20,000
randomized inputs against a reference Python port (0 mismatches), 500
direct `FarmGrid.tick()` A/B runs on cloned grids (0 mismatches), and
the cumulative-event-hash engine soak across four seeds, all eight
native modules on vs. off, byte-identical. Queued next: building
decay/repair math, then weather/terrain-evolution/disasters/hydrology.

## Current state (v0.72.6)

Two items: native port module 7, and a new standing architectural
scope (R7). **Module 7**: `Population._maybe_predator_attack`'s
kill-chance math → `predator_kill_chance` (`cpp/src/predator_kill_
chance.cpp`) — pure arithmetic, no RNG; both `rng.random()` rolls stay
in Python in original order. Verified via 50,000 randomized inputs (0
mismatches) plus a four-seed cumulative-event-hash soak, all seven
native modules on vs. off, byte-identical. **R7 (new)**: explicit user
directive to frame the deterministic physical-reality layer (CLAUDE.md
design priorities: weather/ecology/agriculture/disasters/terrain
evolution) as a cellular-automata-style substrate, and — the actual new
rule — any *new* code in that domain is written directly in C++ from
the start (pybind11 + pure-Python fallback + verification pass from the
first commit), not Python-first-then-ported. Existing not-yet-ported
Python in this domain (weather.py, terrain_evolution.py, disasters.py,
hydrology.py, economy/farms.py, most of buildings.py's decay math)
keeps moving over incrementally under R6's existing queue — R7 doesn't
force an immediate rewrite of the backlog, it governs new code. The
LLM/deterministic split itself (town consciousness, supernatural
ambiguity, everything judgment/social/psychological) is explicitly
unchanged — R7 only reaches the physical half. See
docs/REFACTOR-2026-07.md, "R7," for the full scoping.

## Current state (v0.72.5)

Explicit user directive: "port all remaining code to C++" then "do a
full engine rewrite as well." Flagged the conflict with the v0.63.0
audit's "full C++ port: evaluated, recommended against" finding via
`AskUserQuestion` before proceeding — user chose to continue the
incremental track first, then start a full engine-core rewrite, with
SQLite/asyncio/FastAPI explicitly staying Python. New standing track:
**R6** (docs/REFACTOR-2026-07.md) — only pure, deterministic, no-I/O
math/branching over already-resolved primitives moves to C++; anything
touching the `Agent`/`Settlement`/`Building` object graph, SQLite,
asyncio, or the LLM client stays Python. Same byte-identical-fallback +
hash-soak discipline as every native module since v0.72.0, not relaxed
for R6's larger eventual scope. **Module 5**: `WildlifeGrid.
nearest_grazer_herd` → `GrazerHerdIndex` — caught and fixed a real bug
during verification (an `unordered_map`'s iteration order doesn't match
Python dict insertion order, so tied-distance queries could resolve to
a different herd; switched to an insertion-order vector). **Module 6**
(first R6 module): `Population._update_needs` → `update_needs` — the
first ported function that runs unconditionally every tick for every
agent, not goal-gated like modules 1-5. Both verified via randomized
equivalence checks (20,000 and 50,000 respectively, 0 mismatches after
the module-5 fix) plus the cumulative-event-hash soak across multiple
seeds, all six native modules on vs. off, byte-identical. Queued next:
`_maybe_predator_attack`'s kill-chance math, farm growth-tick math,
building decay/repair math — R6 is explicitly open-ended and
multi-session, not a single-turn deliverable.

## Current state (v0.72.4)

Follow-up correction to v0.72.3, plus a fourth native module, three
parts. **RAM correction**: live `htop` report shows only ~6.5GB usable
RAM, not the full 8GB v0.72.3 assumed when raising LLM config on the
strength of confirmed GPU offload — `llm_num_ctx` 4096→3072,
`llm_num_predict` 640→512, `llm_core_cast_size` 18→14,
`llm_max_calls_per_day` 400→320 (still real headroom over the original
CPU-only-tuned 1280/384/11/200 — GPU offload remains a genuine win,
just not an unlimited-RAM one). **`scripts/run.sh` simplified**: no
longer builds or clones `llama.cpp`/`llama-server` (removed
`AUTO_CLONE_LLAMA_CPP`/`LLAMA_CPP_DIR`/`USE_VULKAN`) — build it
yourself and point `LLAMA_SERVER_BIN` at the binary, or have it on
`PATH`; still builds `hearthmind._native` automatically. Switched
`python3`→`python` throughout. Added `pybind11>=2.11` to
`requirements.txt` as a declared build-time dependency. **Native port
module 4**: `Population._nearest_other_agent` (SOCIALIZE's no-radius-
cap search, see D4) → `AgentPositionIndex`
(`cpp/src/agent_position_index.cpp`) — the first ported function whose
cost genuinely scales with population rather than a fixed map-shaped
cost, so the highest-value port so far, not just directive-driven.
Verified via 20,000 randomized queries + cumulative-event-hash soak at
two population scales, byte-identical. See docs/DECISIONS.md for a
verification-harness false-alarm writeup (an `importlib.reload()`
artifact, not a real mismatch) worth reading before reusing that A/B
pattern.

## Current state (v0.72.3)

Live confirmation: GPU offload via llama.cpp works and is "much much
better than expected" on real hardware. Response, three parts.
**Run script**: `scripts/run.sh` now builds `hearthmind._native`
automatically and builds `llama-server` itself if missing (cloning
`llama.cpp` only with explicit `AUTO_CLONE_LLAMA_CPP=1`); defaults now
match the confirmed command (`--n-gpu-layers 999`, `--cache-type-k/-v
q8_0`). **LLM config raised**: every setting tuned down in v0.71.1/
v0.72.1 for CPU-only-Ollama KV-cache pressure was revisited together
since GPU offload removes that shared constraint at the root —
`llm_num_ctx` 1280→4096, `llm_num_predict` 384→640,
`PROMPT_RECENT_EVENTS` 30→50, `DIALOGUE_MEMORY_IN_PROMPT` 1→2,
`llm_core_cast_size` 11→18, `llm_max_calls_per_day` 200→400,
`MAX_LLM_DIALOGUES_PER_TICK` 2→4, `MAX_DIALOGUES_PER_TICK` 3→6,
dialogue line budget "under 10 words"→"under 14" (the last one wasn't
actually memory-driven originally — corrected the docstring rather than
misattribute it). CPU-only 8GB stays fully supported as a documented
non-default override, never deleted. **Native port module 3**:
`Population._nearest_material_tile` — explicit user directive to keep
porting, not fresh profiling (flagged as such); simpler than
`ResourceIndex` since MATERIAL_BIOMES tiles never deplete, so no
live-patch needed, just a per-`Population.tick()` rebuild. Verified via
20,000 randomized queries + the standard cumulative-event-hash soak,
byte-identical.

## Current state (v0.72.2)

Three items: `pyproject.toml` license fix, one-command run script,
native port module 2. **License**: `project.license` moved from the
deprecated `{ text = "MIT" }` table to the SPDX string `license =
"MIT"` — needs `setuptools>=77`/`packaging>=24.2` (bumped in
`build-system.requires`; `pip install -e .` resolves this via build
isolation regardless of the host's installed versions). **Run script**:
`scripts/run.sh` starts `llama-server` (tuned flags) + `hearthmind.
server` together, waits for `/health`, forwards Ctrl+C to both — see
README step 4 under "Running the LLM (llama.cpp)". **Native port
module 2**: `Population._nearest_resource` (the v0.67.0-profiled top
hotspot) is now a compiled `ResourceIndex` (`cpp/src/resource_grid.
cpp`), rebuilt once per `ResourceGrid.tick()` and live-patched at each
depletion site via the existing `mark_regenerating` hook (R4) so
same-tick multi-agent ordering matches the pure-Python scan exactly —
verified via 20,000 randomized queries (0 mismatches) plus the standard
engine-soak hash check. **Correction**: the "queued next" list from
v0.72.0/.1 wrongly named `world/weather.py` (actually O(1)/tick, not a
grid pass) and `world/terrain_evolution.py` (weekly/monthly cadence,
cross-module state) as native-port candidates — corrected in
`docs/REFACTOR-2026-07.md`. `Population._nearest_material_tile` has the
same shape as `_nearest_resource` but no measured-hotspot evidence —
deliberately left unported, not an oversight (escalate only with a
measured need, per this file's standing rule).

## Current state (v0.72.1)

Closed both items deferred from v0.72.0. **Map**: agent broadcast
payload gained `is_core` (`Population.is_core`, computed in
`_maybe_broadcast`); the frontend renders core-cast agents as a blue
triangle (`drawAgentTriangle`, shared with the predator-pack marker)
instead of the plain dot, with a "▲ core" badge in both the hover
tooltip and the NPC inspector header — Observatory UI direction: this
reads at a glance on the map itself, not only in a stat. **Dialogue**:
`llm/dialogue.py`'s `build_prompt` now grounds each speaker's activity
in `goal_reason` when cognition set one (measured worst case ~786
tokens incl. system prompt, still under the 1280 `llm_num_ctx` budget —
re-measure before adding more prompt content); `SYSTEM_PROMPT` now
explicitly permits disagreement/deflection instead of implicitly
steering toward tidy agreement. `fallback_dialogue` (the deterministic
path) now splices in a memory-grounded opener ~1/3 of non-tense
exchanges instead of being 100% static pools with zero connection to
world events — same "ground it in what happened" fix the LLM path
already had, applied to the fallback too. Pools widened 5→8 entries/
band. Verified via a 6000-tick `llm_enabled=False` soak.

## Current state (v0.72.0)

Explicit user directive: port hot engine code to C++, switch the
default LLM backend to llama.cpp, tune for AMD Ryzen iGPU (Radeon
740M) offload. This pushes directly against two standing findings
recorded elsewhere in this file (C/C++ port "evaluated, recommended
against"; llama.cpp migration "evaluated, recommended against" — both
still true on their own narrow terms) — flagged explicitly to the user
before starting, since this project has no automated test suite and a
full-engine C++ rewrite in one pass has no equivalence-proof net the
existing SHA-256 event-hash harness gives a scoped change. User chose
to proceed with the full-port direction anyway; execution is scoped as
a sequence of provably-equivalent increments, same discipline as every
other behavior-preserving change here (R2/R4), not a single rewrite.

**LLM backend:** `Config.llm_backend` — `"llamacpp"` (new default) or
`"ollama"` (unchanged, still fully supported). `LlamaCppClient` talks to
`llama-server`'s OpenAI-compatible endpoint with grammar-constrained
JSON output (`response_format: json_object` — structurally stronger
than Ollama's `"format": "json"` hint). `build_llm_client(config)` is
now the single factory both call sites (`engine.py`, `server.py`) use,
closing off the "two call sites drift on which fields a client
consumes" bug class the v0.63.0 audit already found once. Default model
tag/GGUF unchanged (`qwen3:4b-instruct`); `--llm-num-ctx`/`--ctx-size`
1280, `--parallel 1`/`llm_max_concurrent=2`, `q8_0` KV cache — same
tuned values, now expressed as `llama-server` launch flags in the
README instead of `OLLAMA_*` env vars. **AMD iGPU Vulkan instructions
are written but NOT verified against real Radeon 740M/780M hardware**
(this execution environment has no GPU) — report back what you observe.

**Native C++ port:** `hearthmind._native` (pybind11, `cpp/src/`,
optional — every ported function has a pure-Python fallback, `pip
install -e .` / the extension failing to build never breaks anything).
Module 1 shipped: `world/resources.py`'s `ResourceGrid.tick`, verified
byte-identical via a 3000-tick standalone hash-equivalence script plus
a 4000-tick engine soak. **Standing gotcha for the next module:**
pybind11's default STL casters copy Python containers rather than bind
them by reference — "mutate this dict in place from C++" silently
no-ops; return the updated value instead. `population.py`/`engine.py`/
`buildings.py` (the orchestration layer) are explicitly NOT ported and
are not simple mechanical translations — see `docs/REFACTOR-2026-07.md`
R5 for the full scoping and what's queued next (weather grid pass,
`_nearest_resource`). **Do not treat this as a completed full port** —
it is module 1 of an open-ended incremental effort.

**Deferred from this batch** (explicit user ask): LLM-authored-NPC
blue-triangle map markers + hover/click surfacing; NPC-NPC dialogue
quality improvements (both LLM and deterministic) — both closed in
v0.72.1 immediately after, see below.

## Current state (v0.71.0)

Unbounded-growth re-audit (follow-up to the v0.70.0 swap fix). **RAM
side is clean** — every per-agent/per-pair collection is capped/pruned
(memories, beliefs, relationships/trust, cooldowns, culture lists,
records, memorials, omen/priority history, institutions, core cast,
engine pending/debug dicts, broadcast + snapshot-payload caches);
`place_names` is bounded by the map's fixed lake count. Two real
unbounded vectors found + fixed, both on the persistence/interface
boundary: **(1) the `events` table had no retention** — the one
table that grew forever on a perpetual run (snapshots already
keyframe-prune; metrics grow ~1 row/day) — now pruned to
`Config.event_log_retention` (default 200k, `--event-log-retention`, 0
disables) on the snapshot cadence, lossless for every reader; **(2)
unclamped query `limit`** on `/events`/`/history`/`/metrics` clamped to
`QUERY_LIMIT_MAX=5000` in the query funcs themselves (a huge limit
against a big table was a client-triggered RAM spike). Plus a defensive
`INTERVENTION_QUEUE_MAX=256` cap. **Standing rule:** any new persisted
table that grows per-tick/per-event needs a retention window like
`events`; anything read into a prompt must stay bounded (prompts read
only the newest ~50 events). `metrics` left unpruned for now (slow;
revisit only for multi-year sim runs). **Refactor status:** R2 ✅
(tick-job dispatch table), R3 ✅ (clamp migration), R4 ✅
(`resources.tick` below-cap working set, pure-Python ~2.1x — numpy
declined as a poor fit for the sparse-dict hot loops). **R1** (mixin
split of the three big files) is the one item left, held for a
dedicated session — see `docs/REFACTOR-2026-07.md`.

## Current state (v0.70.0)

**Swap-after-hours fix + R3.** Live report: swap climbs after a few
hours. Root cause (re-audited: no Python-side leak) — total LLM call
throughput scaled linearly with population (one cognition call per agent
per sim-day + up to 3 dialogues/tick), so a growing town drove Ollama
from lightly loaded to continuously saturated for hours, and sustained
saturation accumulates Ollama's own per-call memory growth into swap on
8GB. **Fix = decouple LLM volume from population** via an **LLM core
cast**: `Config.llm_core_cast_size` (default 11, CLI
`--llm-core-cast-size`) — only a fixed, sticky, founders-seeded cast of
~11 agents (`Population.core_agent_ids`, maintained by
`maintain_core_cast`/`_prominence`, refilled on death, persisted) gets
LLM cognition, and only a core–core pair gets LLM dialogue
(`due_for_dialogue` now returns `(llm_pairs, fallback_pairs)`,
`MAX_LLM_DIALOGUES_PER_TICK=2`); everyone else and every crowd pair uses
the deterministic fallback inline (no Ollama call). Measured ~11.5 LLM
calls/sim-day at population 120 (was ~120/day). Plus a belt-and-braces
**daily ceiling** `Config.llm_max_calls_per_day` (default 200, CLI
`--llm-max-calls-per-day`, `_consume_llm_budget`, reset at day_end) that
hard-bounds *all* Ollama calls (cognition+dialogue+settlement jobs) so no
future per-agent job can recreate the runaway. Surfaced in
`/diagnostics` (`llm_calls_today`, `llm_core_cast_current`, …).
**Standing rule going forward:** any *per-agent* or *per-pair* LLM
decision MUST be core-cast-gated (and counts against the daily ceiling)
— settlement-scoped jobs stay round-robin bounded as before. Trades
crowd LLM richness for stability at explicit user direction; tune the
cast size to the hardware, diagnose via `/diagnostics.system_memory`
first. **Deferred (paused for this fix):** R1 (mixin split), R2 (engine
scheduler registry), R4 (numpy grid passes, user-approved) from
`docs/REFACTOR-2026-07.md` — R3 (finish `clamp`) shipped here.

## Current state (v0.69.0)

Full codebase audit + a safe, behavior-preserving dedup refactor (detail
in `docs/REFACTOR-2026-07.md`; audit confirmed the codebase is clean —
one dead import, no wasteful hotspots, tick loop uses ~4ms of 1000ms).
**New `hearthmind/util.py`** is now the stdlib-only, cycle-safe home for
cross-cutting helpers: `clamp(value, low, high)` (use it for new bounded
math instead of hand-rolling `max(lo, min(hi, x))`) and
`namespaced_rng`/`namespaced_roll` (previously copy-pasted into three
modules; now single-sourced, with each module keeping its private
`_namespaced_rng` alias so call sites are unchanged). Proven equivalent
by a 7000-tick event-stream hash match before/after. **Deferred and
documented, not done** (`docs/REFACTOR-2026-07.md`): R1 splitting the
three oversized files (`population.py` ~3930, `buildings.py` ~2140,
`engine.py` ~2090) into packages via mixins — the real maintainability
win, held back because there's no test net so it must be done one
method-group at a time behind the event-hash check; R2 an engine
scheduler registry to collapse the ~20 near-identical `_maybe_schedule_*`
methods; R3 finishing the `clamp` migration; R4 numpy grid passes,
explicitly declined (unspent tick budget). When adding a new
cross-cutting helper, put it in `util.py`; when adding a new LLM job,
know that R2 wants to make that a registry entry eventually.

## Current state (v0.68.0)

Four live-report bug fixes, root-caused before fixing (see
docs/DECISIONS.md for full detail). **Births**: `CAMP_TOLERANCE` raised
12 -> 18 — it was exactly equal to `initial_population`, and founders'
`age_ticks=0` start makes `carrying_capacity`'s labor term negative
until maturity, so a founding party had zero real reproduction
headroom until a HUT stood; verified 216 births / 12->227 population
over a 20k-tick engine run. **Settlement naming**: added persisted
`Settlement.llm_named` — the background naming job used to key
entirely off `not stl.name`, which only fires the one tick the
placeholder is first set, so any resumed world (name already
persisted) never re-queued it and stayed on its placeholder forever.
**Disease**: added `OUTBREAK_MIN_CHANCE_PER_TICK` floor — the
population-scaled outbreak chance alone gave an expected first case
around sim-year 24 at founding population, reading as "no disease" for
the entire early game even though the system (and its UI) was fully
real; larger/crowded settlements are unaffected (their scaled chance
already clears the floor). **Mountain geography x tech**: added
`ERA_UNLOCKS_MOUNTAIN_BUILDING` (`electrical` onward, mining/tunneling
tech) — MOUNTAIN was a hard barrier at every era with zero tech
interaction; `_choose_build_site` and `_dispatch_movement`'s pathing
(`_step_toward`/`_bfs_step`) now open it per-settlement once unlocked,
so agents can actually reach and build on a staked mountain site, not
just stake one unreachably. SNOWCAP stays impassable at every era.

## Current state (v0.67.0)

Closes both items deferred from v0.66.0, plus two direct follow-ups.
**Cross-settlement relationships**: `Settlement.relations` (id ->
affinity, seeded warm at fission via `seed_relation`, mean-reverts
monthly via `tick_relation` alongside temperament), wired into two
real mechanics — a small market-price nudge from average standing with
sister settlements (`market_relation_factor`), and a nudge from
cross-settlement dialogue sentiment (rare but real: the map is
shared). Dialogue prompts also read the pair's relation as ambient
context. **Further supernatural emergence**: omens have a 30% chance
to blend in a past omen from a *different* named settlement's history
into the existing in-settlement "echo" pool — no settlement is ever
named in the prompt/output, so the only way this is visible is a
player noticing the same phrase across two villages' histories
themselves; same ambiguity discipline as everything else in Phase G.
**Dialogue turn-taking fixed**: `SYSTEM_PROMPT` now explicitly requires
line_b to respond to line_a rather than allowing two independently-
plausible statements. **Performance pass**: profiled (not guessed)
a 60-agent/64x64 run — `Population._nearest_resource` (touched by the
v0.65.2 fishing fix) was the clear top hotspot, scanning every
resource node on the map per call; now scans a fixed-size bounded box
via dict lookups instead, ~7x less self-time in the profiled run, no
behavior change. Tick throughput: 1.42ms/tick at population 60 — the
tick loop remains nowhere near CPU-bound, this was a genuine measured
win, not evidence of a real bottleneck.

## Current state (v0.66.0)

Batch response to numbered live feedback. **Dialogue grounding fixed**:
`llm/dialogue.py`'s prompt now includes each speaker's current
activity and most recent memory (previously stats/weather/relationship/
culture/beliefs/personality only, never what actually happened to
either of them) — root cause of "conversations are very off." Also
fixed a real bug where post-fission dialogue used the founding
settlement's name/traditions/beliefs regardless of the pair's actual
home. **Fishing made visible**: `Settlement.fish_caught` counter
(Wild Resources tile, `inspect_world`) plus **RAFT** vehicles — a
settlement-wide passive bonus to fish-catch yield (same shape as CART,
water-adjacent build sites only; does not grant water-crossing
pathing, see "Known architectural gaps"). **Personality steers
profession**: `cognition.fallback_goal` (the deterministic path used
on every LLM miss) previously split content agents by `agent_id % 3`
with zero trait influence; a standout ambition/sociability trait now
overrides that split, and the live-LLM prompt explicitly asks for the
same tie-break. **Era progression and model choice re-investigated**,
no code change beyond the personality/dialogue items above — see
docs/DECISIONS.md for the full arithmetic (era: ~85 real hours to
`modern` at default pacing, legitimately long-run, plus a documented
multi-settlement dilution caveat; model: `qwen3:4b-instruct` stays the
recommendation even under a 6GB ceiling). Cross-settlement
relationships and further supernatural emergence were requested in the
same batch and deliberately deferred — see "Known architectural gaps."

## Current state (v0.65.2)

v0.65.2: two live-report-driven fixes. **Default model changed to
`qwen3:4b-instruct`** (was `qwen3.5:2b`) — a live user report showed
`qwen3.5:2b` leaking/swapping while the larger, official
`qwen3:4b-instruct` tag stayed under 4.5GB with no swap; `qwen3.5:2b`
was never a real released Qwen tag, so the leak is attributed to that
specific local blob, not to small models generally (see
docs/DECISIONS.md). **Fishing targeting fixed**: `_nearest_resource`
now prefers a FISH node over a nearer FOOD node within
`FORAGE_SEARCH_RADIUS` (previously plain nearest-wins, and FISH nodes
are far sparser than FOOD nodes map-wide, so they essentially never won
the tie-break) — root cause of the "NPCs never fish" report; the
fishing mechanic itself (richer/faster-regen catch) was already real.
Evaluated and declined a llama.cpp migration (Ollama's runner already
is llama.cpp; the memory is weights/KV-cache either way, not Ollama's
own ~100-300MB daemon overhead) — see docs/DECISIONS.md. v0.65.1 added
`Config.llm_num_thread`/`--llm-num-thread` (default every CPU core):
Ollama's per-call thread count was an untouched free lever — more
threads finishes a call faster, shrinking the window its KV-cache
allocation holds memory, without adding a second call's worth of
concurrent KV cache the way raising `llm_max_concurrent` would (that
floor stays 2).

## v0.65.0 and earlier

All original phases (A–F), Phase G, and the full Phase H program are
shipped at least a v1: optional-determinism physical substrate
(terrain/weather/hydrology/disasters/ecology/roads/vehicles/terrain
evolution), LLM cognition/dialogue/culture/chronicle/documentary/
beliefs/omens/town-brain/caravans/genesis/naming, settlements with real
material costs and eras, farming with rot/irrigation, dynamic carrying
capacity (H1), institutions — FAMILY/COUNCIL/GUILD — with belief
mirroring and real mechanical output (H3), evolving world models at
settlement/family/personal scale (H2), skills + teaching (H5, three
axes), supply chains and personal property (H4: tools/medicine, HUT
ownership), inheritance (H7), four-axis psychology traits consumed by
real mechanics (H6), temperament/belief crossover (H8), observatory
surfacing (H9), disease with immunity, rumor instrumentation, a live
browser UI with dev diagnostics, snapshot pruning/keyframes + timeline
scrub v1, and a headless experiment CLI. The v0.63.0 audit fixed six
bugs (CLI concurrency default, runtime-config loss on resume, floods
never submerging, wildfire farm damage dead, starvation-death
misclassification, uncapped medicine inheritance) and added idle
broadcast skipping, biome-count caching, a teaching membership index,
a predator-attack early-out, and `synchronous=NORMAL`.

v0.65.0 closed the last three architectural gaps (explicit user
directive "perform the remaining additions") plus the residual memory
issue: **multiple named settlements** — LLM-decided fission from a
crowded settlement (`llm/fission.py`, `Population.fission_candidate/
fission_party`, `Agent.settlement_id`/`travel_target` with greedy+BFS
journey pathing, reachability-filtered site choice, per-community
ownership on one shared physical map, `MAX_SETTLEMENTS=3`, round-robin
monthly LLM jobs via `_job_target` so LLM volume stays flat, legacy
snapshots load fine, UI name labels + settlement switcher; whispers/
documentary/geography/player-standing stay with the founding
settlement); **fully agent-pathed construction** (site staked out by
score within radius 3, builders drawn by the WANDER work attractor);
**true frame-by-frame replay** (timeline ▶ plays real past maps,
server-side frame cache). Memory: the monthly LLM cluster is now
STAGGERED across days of the month (`MONTHLY_JOB_DAY` — the month-end
~10-call burst was the remaining swap-spike source; volume unchanged,
coincident load now 1 routine job/day), `/diagnostics` gained a
`system_memory` attribution section (self + per-Ollama-process RSS/
swap + meminfo), and README documents the remaining Ollama levers
(flash attention + q8_0 KV cache, NUM_PARALLEL=1 trade) and the
size-down model path (`qwen3:1.7b`) — default model unchanged;
diagnose via `system_memory` before changing anything.

v0.64.0 shipped the audit's ENTIRE suggested backlog (explicit user
directive): Stage 3 institution own-belief formation (`origin: "own"`,
mirroring untouched), deliberate guild founding via LLM decision
(`llm/founding.py`), LLM-mediated dispute resolution
(`llm/dispute.py`, mutual ≤-0.6 festering, three outcomes with real
effects), named geography (`llm/geography.py`,
`Settlement.place_names`), written artifacts (`llm/artifacts.py`,
`Settlement.records`, fed to documentary + heir memory), seasonal
wildlife migration (leave-in-winter/return-in-spring), multi-good
market pricing (`tick_market_prices`, deterministic, 0.5-2.0x), map
memorials (`Settlement.memorials`), building/tile click-inspectors,
event filter chips, zoom/pan + minimap, follow-agent camera + trails,
and timeline v2 (renders the real past map from snapshots). `tests/`
deleted per user decision; idle `/state` staleness approved by user.
WS delta payloads remain deliberately unbuilt (own only-if-measured
condition unmet).

## Full audit (v0.63.0): recorded evaluations

**C/C++ (or Rust/Cython) port: evaluated, recommended against.** The
engine runs ~0.9ms/tick against a 1000ms budget; the bottleneck is
17-20s Ollama calls, not Python. A native port buys <0.1% of the tick
budget and costs the plain-Python hackability the whole workflow
depends on. If per-tick cost ever matters (10x population, much larger
maps), escalate in order: (1) spatial buckets for nearest-X scans,
(2) numpy for terrain/weather grid passes, (3) PyPy — all before any
C/C++. Don't re-litigate from scratch; revisit only with a measured
tick-time problem.

**User decisions resolved (v0.64.0):** `tests/` deleted; idle `/state`
staleness (rebuild every 10th tick with no clients) approved; the
entire UI + emergence backlog was ordered built and shipped in v0.64.0
(see "Current state") — the only surviving deferral is WebSocket delta
payloads, whose own only-if-bandwidth-measured condition is unmet.

**Ollama levers (user-side, recorded):** `OLLAMA_MAX_LOADED_MODELS=1`,
`OLLAMA_NUM_PARALLEL=2`, `OLLAMA_KEEP_ALIVE=3m` (README section);
`HSA_OVERRIDE_GFX_VERSION=11.0.0` for the gfx1103 iGPU experiment;
consider Ollama structured outputs (`format: <json schema>`) for
stricter small-model JSON once their server version supports it well.

## Diagnostic history index (details in docs/DECISIONS.md / CHANGELOG.md)

Standing lessons distilled from live incidents — the entries themselves
remain in the decision log:

- **Memory-leak pattern to audit first:** any dict/list keyed by agent
  id or appended per event without a cap. Fixed instances:
  relationships/trust (v0.42.0, pruned on decay-to-zero + death;
  `avg_relationships_per_agent` in `/diagnostics` is the live regression
  signal), traditions/inventions/festivals (v0.44.1, capped 300 with
  persistent ordinal counters), institutions (v0.54.0, extinction-aware
  prune at 300), dialogue/cognition cooldowns (pruned). v0.63.0
  re-audit: no unbounded structure remains.
- **Bursts, not just leaks:** the v0.65.0 residual-pressure fix — every
  monthly LLM job used to schedule on the same `month_end` tick (~10
  coincident calls after v0.64.0), a per-month *burst* no steady-state
  leak audit could see. Jobs are now staggered one-per-day
  (`MONTHLY_JOB_DAY`); if a new periodic LLM job is ever added, give it
  its own day there, never `month_end`. `/diagnostics.system_memory`
  now attributes memory (self vs. each Ollama process vs. system)
  live — read it during an episode before tuning anything.
- **Swap pressure has always been Ollama-side call volume/config**, not
  this process (RSS-probed clean repeatedly): concurrency (v0.43.0/1),
  keep_alive, num_ctx/num_predict, `use_mmap: true` (v0.55.0 — the
  `--no-mmap` runner at 5.1GB RSS), the monthly settlement-job cluster
  (v0.58.0 backpressure gate), and the CLI default drift (v0.63.0). A
  live symptom traced to one cause is not necessarily fully explained
  by it — re-verify after each fix; check every process the symptom
  could implicate. Also: a coarse `--sim-minutes-per-tick` (e.g. 120)
  multiplies how often calendar-gated LLM jobs fire per real hour —
  covered in chat, worth remembering when a launch command changes.
- **A first fix that only delays a collapse signals a second cause**
  (v0.43.2 HUT decay: upkeep bleeding into hut decay AND zero-variance
  decay + no repair attraction — both needed fixing; watch
  `huts_standing` vs population if starvation reports recur).
- **Unreachable-threshold bug class** (see the weather lesson above).
- **Era progression, town-brain "food" lock, early-winter funnel,
  UI flicker, duplicate names, whisper loss on fallback**: all fixed —
  see docs/DECISIONS.md (v0.44.0 and the v0.40.0–v0.41.0
  review-implementation passes).
- **Post-rework equilibrium note:** abundant maps reach the
  POPULATION_CAP=400 safety valve by ~tick 30k with hunger ~0.4 — a
  legitimate Malthusian equilibrium; if live runs feel too grim, tighten
  `REPRODUCTION_WELLFED_HUNGER` or scale birth chance by hunger rather
  than lowering the cap.
- **True extinction (0 population) is a legitimate permanent ending** —
  migrants only arrive while 1-3 people remain; never auto-revive an
  empty world.
- The full architecture review lives in `docs/REVIEW-2026-07.md`; its
  recommendations were implemented across v0.40.0–v0.41.0.

## Known architectural gaps (not yet built)

**WebSocket delta payloads**: deliberate deferral, own condition (only
if bandwidth is ever *measured* as a problem) remains unmet.

**True water transport: closed (v0.74.0).** RAFT (v0.66.0) remains a
settlement-wide fishing-yield bonus only, never crossing pathing —
but `BuildingKind.BRIDGE` (v0.74.0) now provides the real pathing-
system pass this gap called for: a STANDING bridge's spanned water
tiles are genuinely walkable (`Population._is_walkable`'s `bridge_
tiles` parameter), founded via a colocation+span-search mechanism
(`_find_bridge_span`), reachable by goal-directed movement, travel-
target journeys, and fission-site reachability alike. See "Current
state (v0.74.0)."
