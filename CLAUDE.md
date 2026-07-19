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

**`docs/CONSTITUTION.md` is the canonical priority/architecture guide**
(user-uploaded, v0.86.0) and supersedes prior audit reports where they
conflict. Priority order when trade-offs arise: **Emergence > Memory
efficiency > Performance > Simplicity > Backward compatibility** (save-
compat is explicitly lowest; the save format may change freely). Prefer
C++ for performance-critical systems, Python only where mature libraries
(SQLite/networking/orchestration) give real leverage. Crucial cognition
is never faked to keep throughput — slow/pause instead (see the tick-
loop workflow rule below; mechanism shipped v0.86.0, see "Consolidated
history" below).

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
Awake) — see docs/VISION-2026-07.md (now trimmed to a status pointer)
for the phase-by-phase shipping record and the two flagged conflicts'
resolutions. **All six phases (I-N) are fully shipped** (v0.76.1
through v0.84.4) — this is no longer a design-only document, it
describes the shape the engine actually has.

**`docs/IDEAS-2026-07-EMERGENCE.md`** (filed v0.87.6, an externally-
submitted "what's still missing" audit, extended with original ideas
§1-§9 across later batches): **also fully resolved** as of v0.87.31 —
every checklist item across §0-§9 is either shipped, confirmed
already-shipped under another name, or (§8's LoRA fine-tuning item
only) explicitly and correctly left as data-collection-only pending a
real training-pipeline effort outside `SimulationEngine`'s scope. Kept
as a historical decision record (like docs/DECISIONS.md); work from it
again only on future explicit direction naming a specific item.

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
  needs *some* non-blocking resolution (liveness, not determinism) —
  but as of v0.86.0 (Engineering Constitution §3/§7, docs/CONSTITUTION.
  md) that resolution is **not always a fabricated fallback**. A
  *crucial-cognition* job (individual-mind goals, belief revision, the
  town brain, dreams, the consciousness) DEFERS instead: on a spent
  daily budget or a timed-out/errored call it leaves state unchanged and
  re-attempts on its natural cadence, never substituting rule-based
  output for genuine cognition. Liveness there is guaranteed by the
  deterministic *physical* layer (critical-hunger movement override,
  etc.) plus the existing backlog pacing that slows/pauses ticking to
  let inference catch up — not by faking the thought. `_schedule_llm_
  job(..., critical=True)` marks these; per-agent cognition defers in
  `_schedule_due_cognition`/`_run_cognition`. Ambient/narrative jobs
  (chronicle, tradition, folklore, omens, caravan, naming, ...) keep the
  real deterministic fallback — those have a sensible objective answer
  and are texture, not cognition. When adding a new LLM job, decide
  which kind it is and pass `critical` accordingly.
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

## Current state (v0.88.0) — v1 batch, Phase 1

First phase of a large multi-part v1 batch (explicit user request: deep
audit incl. convergence/bugs/emergence, CA/deterministic-system fixes,
prompt audit incl. genesis, C++ porting, era-progression rework with a
full historical ladder and LLM-steered branching — "this will be the
first v1 bump"). Four parallel research passes preceded this phase
(CA systems, LLM prompts, era/invention math, convergence/emergence);
this phase lands the bugs with clean, contained fixes. Full detail:
CHANGELOG.md.

Fixed: flood pressure saturation (`FLOOD_HEAVY_RAIN_PRECIPITATION`
0.4->0.65, gain/decay rebalanced — was ratcheting to its cap under a
realistic rain duty cycle, the "unreachable threshold" bug class
inverted); surveyor agents wasting a core-cast LLM cognition call every
due-slot on a goal decision unconditionally discarded in favor of a
forced `AgentGoal.EXPLORE` (now skip cognition entirely, write the goal
directly); `TRAIT_SOCIABILITY`/`TRAIT_AMBITION`/`TRAIT_OPENNESS` having
zero negative event-nudge sources anywhere (only resilience was
bidirectional) — real long-run population-psychology homogenization
risk, fixed with negative sociability triggers (feud hardening,
ostracism, theft-victimization) and faster mean-reversion for ambition/
openness specifically.

Two native-port gaps closed: `FarmGrid._tick_soil_fertility` and
`apply_mining_scars`/`decay_mining_scars` were genuine per-tick hot
loops sitting unported next to already-native siblings with zero
in-source R7-deviation justification (CLAUDE.md previously claimed
mining scars were "flagged" — the flag never existed in the file).
Ported to `cpp/src/soil_fertility.cpp`/`cpp/src/mining_scars.cpp`, both
new toggles added to `scripts/verify_native_soak.py`'s `_NATIVE_
TOGGLES` list (a fixed enumeration — a new native function needs an
explicit entry to actually be exercised native-vs-fallback by the
soak, not just built). Verified via `scripts/verify_native_soak.py`
with the native extension actually compiled this session (2 seeds x
800 ticks, byte-identical) — this is the first session in this
environment where the extension was built at all, so this run also
re-verified every pre-existing already-toggled native module against
its Python fallback for the first time under a real compiled binary,
not just this phase's two new ones; no divergence found.

## Current state (v0.87.46)

Phase 6, final, of the multi-part live-report batch (see v0.87.41):
"audit the whole code for unnecessary convergence," extended to
folklore and rumor/gossip propagation per the explicit request.
Audited, no bug found — each already has a real bound: folklore logs
its own tales under a `"folklore"` event category (never `"rumor"`),
so a tale can never become next month's own raw material; `spread_
rumor` samples uniformly; gossip contagion (`_apply_gossip_contagion`)
is a clamped, capped, proportional relaxation toward the speaker's
view, gated by trust and unambiguous single-subject naming;
InterpretRumor's distorted retelling lands only in the listener's own
memory, never re-injected settlement-wide, and is capped per day;
every deterministic pattern-signal counter (ritual/family-feud/
dispute/law) resets to zero on crossing its promotion threshold rather
than accumulating indefinitely. This closes the six-phase batch
(v0.87.41-.46): food-storage/repair fixes, water infrastructure,
era-scaled infrastructure, occupations, exploration/surveyor, and this
audit.

## Current state (v0.87.45)

Phase 5 of the multi-part live-report batch (see v0.87.41's plan):
exploration/surveyor role. New 11th occupation SURVEYOR + new
`AgentGoal.EXPLORE` (goal-code 6, native `agent_table.cpp` comment
updated, no functional change needed — codes are unvalidated int32s).
A surveyor's goal is forced to EXPLORE every tick. New `Settlement.
explored_tiles`/`exploration_findings` (capped 60): a surveyor reveals
a small radius around themself each tick, recording findings for
mineral veins/rich wild-food sites/other settlements — scoped to
surveyors only (not O(population)). Target selection is bounded random
sampling, never a full-map flood fill, feeding `Agent.travel_target`
so the existing journey machinery carries them there. The "feed back
to town" payoff: fission site search now prefers a surveyor-discovered
good site over blind local search. UI: new "Exploration" stat tile
(tile count + latest finding) — deliberately no full map overlay
(broadcast-bandwidth cost judged not worth it, same caution as the
standing WebSocket-delta deferral). Verified via direct smoke tests, a
12,000-tick soak, `scripts/verify_native_soak.py` byte-identical.

## Current state (v0.87.44)

Phase 4 of the multi-part live-report batch (see v0.87.41's plan): a
real jobs/occupations system, deep per explicit user decision
(occupation gates mechanical behavior, not a label). New `agents/
occupations.py`: `Agent.occupation` (plain string field, not native-
store-backed) plus ten named occupations (baker/builder/banker/
teacher/priest/mayor/fisherman/farmer/shopkeeper/businessman).
Deterministic assignment (`Population._maybe_assign_occupations`) —
every mature, healthy, occupationless agent gets whichever occupation
the settlement has fewest of, MAYOR capped at one — not LLM-authored
(would blow the per-agent LLM-volume budget). Each occupation reuses
an existing presence-driven building mechanic: staff-weighted
production bonus at a matching building (baker/teacher/fisherman/
businessman), a new MARKET currency-income job (banker) and caravan-
trade bonus (shopkeeper), a direct work-rate bonus (builder) or yield
bonus (farmer/fisherman), a festival-boost stack (priest), and a
`carrying_capacity` coordination nudge (mayor). Full UI pass: NPC
inspector subtitle + new "Occupations" stat tile. Verified via a
direct smoke test, a 12,000-tick soak, `scripts/verify_native_soak.py`
byte-identical.

## Current state (v0.87.43)

Phase 3 of the multi-part live-report batch (see v0.87.41's plan):
era-scaled infrastructure. Confirmed gap: only FACTORY/POWER_PLANT/
AUTOMOBILE were era-gated; roads and every other building kind never
changed with era. New paved-road tier in `world/roads.py`
(`ROAD_PAVED_WEAR=0.85`, better speed multiplier throughout, unlocked
world-wide once any settlement reaches `modern`+ — roads are shared
infrastructure, not settlement-private) and `buildings.hut_capacity_
multiplier` (each HUT houses 1.3x/1.6x more at modern/digital,
computed live from era, no new schema field). Full UI pass: paved
tiles get a distinct map color, stat tiles/inspector report paved
status. Verified via direct smoke tests, a 12,000-tick soak, and
`scripts/verify_native_soak.py` byte-identical.

## Current state (v0.87.42)

Phase 2 of the multi-part live-report batch (see v0.87.41's plan):
water infrastructure. `RAFT`'s own docstring already flagged the gap
("doesn't grant actual water crossing/pathing"). New `VehicleKind.
BOAT` (personal, claim/ride like MOUNT/AUTOMOBILE, water-adjacent
founding like RAFT) grants its rider real water-crossing capability —
`Population._is_walkable` gained a `water_capable` parameter opening
SHALLOW_WATER/DEEP_WATER/RIVER tiles, threaded through `_step_toward`
(deliberate goal-directed movement) via a flag computed once per agent
per tick. Deliberately not threaded into `_bfs_step`/`_reachable_tiles`
(stuck-escape and settlement-wide reachability scans) — flagged scope
trim. New `BuildingKind.DOCK` (water-adjacent trade port, WORKSHOP-
shaped currency income, where boats are founded) and `BuildingKind.
OIL_RIG` (water-adjacent + era past `industrial`, FACTORY-shaped
income at double DOCK's rate). Full UI surfacing pass in the same
batch (map markers, stat tile, building colors) per the standing
workflow rule. Verified via direct smoke tests, a 12,000-tick soak,
`scripts/verify_native_soak.py` byte-identical.

## Current state (v0.87.41)

Live report batch, explicit multi-part request: NPCs not storing food
in granaries, decay outrunning repair, water as an untapped resource
(no boats/oil rigs), no exploration/surveyor role, no real jobs/
occupations system driving the economy, plus "audit the whole code for
unnecessary convergence" and (mid-batch addition) "improve building/
road/infrastructure types with era." Scoped into six phases, each its
own commit batch: (1) food-storage/repair bug fixes — this version,
(2) water infrastructure (boats, oil rigs, docks), (3) era-scaled
building/road types, (4) deep occupations system (`Agent.occupation`
gates real behavior — baker/builder/banker/teacher/priest/mayor/
fisherman/farmer/shopkeeper/businessman), (5) exploration/surveyor
role feeding collective map knowledge, (6) convergence audit on
`folklore.py`/rumor-gossip propagation (town_brain's granary-fill
food-priority loop and dialogue topic selection were already fixed in
earlier passes — this extends that same audit).

This version: the two reported bugs. Granary stocking was always real
(`_maybe_stock_granaries`) but had no WANDER-goal attractor pulling
idle well-fed agents toward it — `husbandry_positions` (v0.87.25) gave
PASTURE/HATCHERY this exact treatment but GRANARY itself never got it.
New `Population.granary_positions` closes the gap; verified via a
12,000-tick soak, granary food rose from 0 to ~78/90 and held there as
population grew to 79 (was permanently empty before). Repair-labor
piled onto the single nearest damaged building past `MAX_WORKERS`
(extra workers there don't speed repair) while other damaged buildings
sat untouched — `damaged_building_positions` now excludes overstaffed
buildings and sorts worst-condition-first among the rest.

Era answer (also asked this batch): settlements start at `industrial`
(no tribal stage), advance through `electrical` (tech_level 3) ->
`modern` (7) -> `digital` (12) one step at a time, gated by both an
invention-driven tech_level AND real infrastructure minimums per era.
Invention rolls once per season (~91 days) at a 20% base chance
(modified by prosperity/education/infra-progress/skill/temperament) —
expect roughly 1 invention per ~5 seasons once prosperous, so `digital`
is a genuine multi-year milestone, not a fast unlock. Confirmed gap:
today only `FACTORY`/`POWER_PLANT` (electrical+) and the `AUTOMOBILE`
vehicle (modern+) are era-gated — every other building kind and the
entire road system are identical from tick 1 through `digital`. Phase 3
addresses this directly.

## Current state (v0.87.40)

Follow-up: "extend the audit to caravan and letters call sites too and
every other prompt that was missed." Re-confirmed all 33 `llm/build_
prompt` modules were already read (cross-checked against every
`SYSTEM_PROMPT =` in the package — none missed); this pass looked at
how the engine actually calls each one, not just each module's own
content.

`llm/letters.py` had a real gap: `SYSTEM_PROMPT` says to ground the
letter in "what you actually know and feel right now," but `build_
prompt` read a blind `sender.memories[-2:]` slice instead of the
adaptive relevance-scored retrieval cognition/personal_belief already
use (v0.87.36) — fixed with the same `retrieve_relevant_memories`/
`faded_memory_text` pattern, same 2-slot budget.

`_maybe_schedule_caravan`'s call site had a bare, undocumented `20`
where sibling jobs reference a named constant — added `caravan.
CARAVAN_RECENT_EVENTS = 20` with a docstring (value unchanged, now
named per the project's own constants-need-a-docstring rule).

Verified: direct smoke test (high-salience memory now survives into a
letter over mundane-but-recent ones), a 3000-tick LLM-disabled engine
soak, `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical.

## Current state (v0.87.39)

Explicit request: "extend the audit to all prompts in the code." Read
every remaining `build_prompt` in `hearthmind/llm/` not already
covered (25 modules — artifacts through world_genesis; see
CHANGELOG.md for the full list). 24 were already sound (every optional
field threshold-gated, no duplication, every `SYSTEM_PROMPT` claim
matched what `build_prompt` actually supplied).

One real gap, same class as diplomacy's (v0.87.38): `llm/summary.py`'s
`SYSTEM_PROMPT` has always promised "the town's current mood" but
`build_prompt` never had a `mood` parameter — `Settlement.mood` sat
unused. Fixed with an optional `mood` param (formatted like narrative_
direction/consciousness already do), wired via `SimulationEngine.
_schedule_summary`.

Verified: direct smoke test (mood line present/absent),
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

This closes the context-selection audit across every LLM prompt in the
codebase — the four-part v0.87.35 request plus its five follow-ups
(cognition/personal_belief, town_brain/chronicle/world_genesis,
dispute/diplomacy, and now everything else) is complete.

## Current state (v0.87.38)

Follow-up request: extend the context-selection audit to dispute and
diplomacy. Full detail: CHANGELOG.md.

`llm/dispute.py`: audited, no change — every optional grounding line
(reputation gap, faction rivalry, debt, family feud, council leaning,
local law) is already threshold-gated and carries genuinely distinct
information.

`llm/diplomacy.py`: found a real gap. `SYSTEM_PROMPT` asks the model to
reason from "what each [settlement] has recently lived through," but
`build_prompt` only ever supplied the bare `current_priority` label —
never anything a settlement had actually lived through. Fixed by
threading each settlement's `priority_rationale` (town-brain's own
one-sentence grounded reason, already-computed state) through
`diplomacy.build_prompt`'s new `rationale_a`/`rationale_b` params, via
`_maybe_schedule_diplomacy`. Falls back to the bare label when a
settlement has no town-brain decision yet.

Verified: direct smoke tests (rationale present/absent), a 3000-tick
LLM-disabled engine soak, `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical.

## Current state (v0.87.37)

Follow-up request: extend the context-selection audit to town_brain/
chronicle, improve world-genesis prompting, surface the seed in the
dev console. Full detail: CHANGELOG.md.

town_brain/chronicle: audited, no change — both pair a full-belief-set
digest with a couple of freshest specific theories, which looked like
v0.87.36's cognition redundancy at first glance but isn't: the digest
condenses everything, the specifics add concrete detail the digest
can't carry. Complementary, not duplicative, already deliberately
documented from an earlier pass. The shared `PROMPT_RECENT_EVENTS`
event window (`recent_events_diverse`, used by 10 call sites) was
re-checked too — already dedupes repeated rumor text and caps routine-
category crowding, a real curated selection, not a raw dump. Left
unchanged.

`world_genesis.build_prompt` was the actual gap: previously zero-
argument, byte-identical on every call — every brand-new world's
founding-scenario variety came from sampling temperature alone, while
real per-world entropy (`_resolve_genesis_seed`'s `fallback_hint`) sat
unused except for the fallback pool/seed XOR. Now takes an optional
`flavor_hint` that leans the prompt toward one of ten terrain flavors
("a river valley", "highland moor", ...) as a loose starting point;
`server.py` passes its own `fallback_hint` through. Old zero-arg call
shape still works unchanged.

`_diagnostics_snapshot()` gained a `seed` field — the dev console
already dumps the full diagnostics payload as raw JSON, so this reaches
the UI with zero frontend changes.

Verified: direct smoke tests (hint-driven prompt variety, an end-to-
end `_resolve_genesis_seed` test with a fake LLM client confirming the
real entropy reaches the prompt, `_diagnostics_snapshot()['seed']`
matching `Config.seed`). `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical.

## Current state (v0.87.36)

Follow-up to v0.87.35's item 3: extends the context-selection audit to
cognition and personal_belief. Full detail: CHANGELOG.md.

`cognition.build_prompt` no longer shows `own_belief`/`semantic_
memory` alongside `life_digest` once a real digest exists — the digest
is itself authored FROM those two fields (see its docstring), so
showing all three was redundant, not merely low-relevance; falls back
to the two specific fields only while no digest has formed yet.
`_maybe_schedule_personal_belief` (engine.py) now selects its `recent`
memories via the same adaptive `retrieve_relevant_memories`/`faded_
memory_text` cognition already uses, replacing a blind `memories
[-3:]` slice — the one job whose purpose is judging "what matters"
about an agent's life previously used the least relevance-aware
selection of any LLM task in the codebase. `beliefs.build_personal_
prompt`'s other fields (semantic/core memories, existing beliefs) were
left as deliberate whole-picture context per their own docstrings —
Reflect() is meant to weigh an agent's WHOLE recent self-theory, not
just the freshest slice.

Verified: direct smoke tests for both changes (digest supersession,
adaptive-retrieval memory selection); a 3000-tick LLM-disabled engine
soak (prompt-building code runs on every call regardless of LLM
enablement); `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical.

## Current state (v0.87.35)

Explicit four-part live request: review-pack diagnostics, prompt-
content relevance audit, smarter context selection, and diversified
conversation opportunities (the "spring rhythm keeps coming up"
complaint). Full detail: CHANGELOG.md.

Root cause of the dominant-narrative complaint: `Settlement.
top_topics()` was fed into every dialogue prompt as an unconditional
"the village has been talking about X" invitation, and the model's own
resulting topic output fed back into `top_topics()`'s own ranking —
whichever topic became dominant first got reinforced every exchange,
a feedback loop introduced by an earlier §9 session's own work.

New `dialogue.build_opportunity_candidates`/`select_opportunities`
(`llm/dialogue.py`): a weighted-random-without-replacement selector
(`OPPORTUNITY_MAX_PICKS=2`) over seven steering categories —
`pair_history` (3.0, highest), `family` (2.5), `future_plan` (2.5, new
— reads `Agent.plan`), `village_event` (1.8), `place` (1.5), `weather`
(1.3), `settlement_topic` (0.8, lowest, reworded from an invitation to
"common knowledge" framing) — replacing the old unconditional
concatenation of all four steering fields every call.
`SimulationEngine._schedule_due_dialogue` builds the candidates and
selects once via a namespaced RNG (`dialogue_opportunity_{a.id}_
{b.id}`), feeding the same result into both the prompt and
`structured_input` (for the new diagnostics below) — one selection,
never double-consumed. Verified via a 2000-iteration distribution
test: `pair_history` 933/2000 vs. `settlement_topic` 310/2000 with all
seven categories present every call. This addresses items 3 and 4 of
the request together — dynamic context selection IS the diversity
mechanism here, not two separate systems. Item 2 (broader prompt-
content audit) found nothing further worth trimming this pass — every
remaining unconditional dialogue field already earns its slot.

New `llm/review_diagnostics.py` (`compute_diagnostics`/`diagnostics_
to_markdown`): stdlib-only, operates on the same `raw_examples` list
`review_pack.py` already collects, no second archive scan. Reports
task distribution, prompt/completion length, latency, fallback/parse-
repair rates, prompt/structured-input duplicate rates, per-task
context-usage rates (new `structured_input["context_available"]`
field), dialogue topic diversity (dominant-topic share — the direct
regression signal for the "spring rhythm" class of bug), dialogue
opportunity-category balance, NPC/personality diversity, and a
day-by-day historical-trends table. `review_pack.export_review_pack`/
`export_random_subset` now always write `diagnostics.json` +
`diagnostics.md` into every exported ZIP — `scripts/recorder_tools.py`
and `POST /recorder/export-review-pack` pick this up automatically,
zero changes needed there.

Verified: direct smoke tests for `review_diagnostics` (synthetic
multi-task/mixed-vintage examples, empty-input degradation) and a real
end-to-end test building an on-disk archive and calling the actual
export functions, confirming the ZIP's `diagnostics.json`/`.md`
content. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — no native module touched.

## Current state (v0.87.34)

Batch of live-report fixes, no single theme. Full detail: CHANGELOG.md.

Mineral veins (v0.87.26) never actually drew on the map — the tile
inspector could show one on click but nothing painted a marker; fixed.
Idle wandering visibly paced back and forth (`_maybe_move` only has 4
cardinal candidates, so a uniform random walk reverses its own last
step 1-in-4 times) — new `Agent.last_move_dx`/`last_move_dy`
deprioritize stepping straight back, verified 0% reversal in open
terrain (was ~25%). Hover tooltips on the details stat tiles had
silently broken — `setInnerHTMLIfChanged` replaces the whole grid's
DOM on nearly every broadcast, resetting a native `title` attribute's
hover timer before it could ever fire; replaced with `data-tooltip` +
a delegated `mousemove` listener on the stable container. Header
buttons visibly jumped position whenever the weather/wind text changed
width, since everything shared one `flex-wrap` row — split into
`.header-info`/`.header-controls`, two independent wrap contexts.
Ambient sound was effectively inaudible (buried in a nested dropdown,
too quiet, first-enable used the same slow ramp as routine updates) —
promoted to a first-class header button, gain raised, fast first-enable
fade-in.

Non-core NPCs now occasionally take up real economic work:
`noncore_nudge`'s existing one-call-a-month job may also set a short
`Agent.plan` (reusing §7's bounded-episodic-planning machinery
unchanged) grounded in the settlement's own real shortfall (new
`SimulationEngine._settlement_economic_need`) — `cognition.
fallback_goal`, the only goal source a non-core agent ever gets, every
day, already reads `plan_intent` and biases toward GATHER/FORAGE/
SOCIALIZE by keyword, so one grounded LLM sentence steers several real
days of an ordinary villager's deterministic behavior. Highlights log
widened (era_advance + first_invention) after a live report it "has
only highlighted population growth."

## Current state (v0.87.33)

Docs cleanup per explicit user request ("Clean up stale docs and
stale items and clean all documents") — no code/behavior changes.
Full detail: CHANGELOG.md.

Found and fixed genuinely stale (not just verbose) status claims:
`docs/VISION-2026-07.md`'s "nothing implemented yet" header and this
file's own "Nothing from this vision is implemented yet" (both false —
Phases I-N have been fully shipped since v0.84.4) and the §8 summary
below ("not-yet-scoped... work from it only on future explicit
direction" — false, two of three items shipped). Trimmed docs/
VISION-2026-07.md and docs/VISION-2026-07-LEARNING.md to status
pointers, same treatment docs/ROADMAP.md already had. Consolidated
this file's own "Current state" history (v0.82.0-v0.87.26 folded into
the existing "Consolidated history" section, which now spans v0.65.2-
v0.87.26 as one themed block) — 3013 -> ~1040 lines, same periodic
maintenance as the v0.63.0/v0.85.0 passes. docs/IDEAS-2026-07-
EMERGENCE.md/docs/REFACTOR-2026-07.md/docs/REVIEW-2026-07.md/docs/
DECISIONS.md audited and left as-is — all confirmed accurate,
genuinely still-referenced records, not stale backlogs.

## Current state (v0.87.32)

Direct fix for a live report: mineral-vein tiles (iron/gold, v0.87.26)
showed nothing when clicked. Root cause: `World.minerals` was ticked
and persisted from the start but never included in the engine's live
broadcast payload — `resources`/`farms`/`wildlife` all reach the
frontend every tick, `minerals` never did. Fixed by adding a
`minerals` key to the broadcast (same `to_dict()`-per-deposit shape
as `resources`) and a "Mineral vein" section in the bare-tile click
inspector. Full detail: CHANGELOG.md.

## Current state (v0.87.31)

Explicit user request ("Complete all the items of 9") — implements
every remaining unchecked item in docs/IDEAS-2026-07-EMERGENCE.md §9
(9 of 12; the other 3 were already shipped/confirmed under other
names). Full detail: CHANGELOG.md.

Two items shared one new mechanism each rather than four separate
ones, since the doc's own text showed they named the same underlying
gap: (1) "diversify cultural topics" + "competing narratives" ->
`SettlementCulture.recent_topics`/`top_topics()`, a settlement-wide
generalization of the existing per-pair `Population.dialogue_topics`
ring, zero added LLM call volume (reuses dialogue's existing `topic`
field), consumed as a `dialogue.build_prompt` steering line and the
new "Village storylines" stat tile. (2) "institutions get their own
persistent memory" + "multi-layer culture" -> new `Institution.
culture_digest` + `llm/institution_culture.py`, a quarterly round-robin
job (`SimulationEngine._institution_job_target`, flat call volume
regardless of institution count) that independently authors one
institution's own character — distinct from `Institution.beliefs`
(a filtered mirror of settlement-wide beliefs).

Reputation now survives death: `Population._deceased_reputation_
legacy` snapshots a dying agent's last reputation reading instead of
dropping it, fades it monthly, prunes past a floor (same decay-to-
zero-then-delete discipline the relationship-leak fix established);
new `family_legacy_reputation()` aggregates a FAMILY institution's
standing across every member it ever had, living or dead. One new
concrete cross-system cascade: a standing family feud now measurably
lowers festival chance (`FAMILY_FEUD_FESTIVAL_PENALTY`). `dialogue.
build_prompt` gained `place_names`/`grounded_event` parameters closing
the "geography as culture" and "conversation grounded in simulation
events" gaps. "Long-term societal evolution across generations" closed
as an audit conclusion (no further gap found beyond what earlier
passes already shipped) rather than new code.

Verified: direct production-path tests for every mechanism (including
a real label-casing bug caught and fixed in `institution_culture.
build_prompt`); a real end-to-end engine test drives the new
institution job through actual production scheduling with a fake LLM
client; an 18,000-tick organic soak (fake instant-responding LLM
client) confirms topics/institution digests form organically with zero
crashes; a 20,000-tick LLM-disabled soak confirms no regression.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
no native module touched.

## Current state (v0.87.30)

§9's last item (docs/IDEAS-2026-07-EMERGENCE.md, "stalled era
progression"), explicit user request. Confirmed root cause: era
advanced purely from `tech_level`, itself incremented only by a rare
seasonal invention roll — a settlement could sit at `industrial`
forever regardless of built infrastructure, zero correlation between
visible development and progression. Full detail: CHANGELOG.md.

New `ERA_INFRASTRUCTURE_REQUIREMENTS` (`settlement/buildings.py`,
per-era huts/roads/schools/carts) backs two complementary fixes:
`_maybe_advance_era` now uses `era_for_tech_level_gated` (walks
`ERA_ORDER` one legible step at a time, never skips an era whose own
infra isn't built, never demotes an existing save); `_maybe_schedule_
invention`'s chance calc gained an `era_infrastructure_progress`-based
bonus (new `INFRASTRUCTURE_INVENTION_BONUS_WEIGHT`) — building toward
the next era's requirement now measurably raises invention odds, so
infra investment is a real lever, not window dressing. New
`Settlement.summary()`'s `era_infrastructure` key surfaces this as a
plain-language suffix on the existing "Era" stat tile.

Verified: direct tests for the gated-era-advance function (zero-infra
cap, single/multi-step advance, never-demotes) and progress math; a
real engine test drives `_maybe_advance_era` through actual
`start_construction`/`start_vehicle`/`world.roads.wear` calls; live
Playwright verification of the rendered stat tile.
`scripts/verify_native_soak.py` (2 seeds x 1500 ticks) byte-identical.

## Current state (v0.87.29)

Backward-compatible enhancement pass on v0.87.28's training recorder
per explicit user spec ("not a redesign... only extend it"). Full
detail: docs/TRAINING_RECORDER.md's "v1.1.0 Recorder Enhancement Pass"
section. `SCHEMA_VERSION` stays 1; `RECORDER_VERSION` -> 1.1.0.

New per-example fields, all additive: `generation_config` (temperature/
max_tokens/context_length/backend knobs, from `SimulationEngine.
_generation_config_snapshot`), `prompt_metadata` (`template_name`
defaults to task, `system_prompt_version` auto-derived as a hash of the
system prompt text), `prompt_hash`/`structured_input_hash` (SHA-256,
for duplicate detection), `session` (`{name, tags}` — tags settable at
`/recorder/start` and in the dev-console panel's new tags input),
`outcome` (`{status, apply_failed}` — executed/fallback_used/
deferred_critical/queued_pending_apply/target_gone, derived from
information already at hand synchronously, no new instrumentation),
`dataset` (`{schema_version, simulation_version, archive_version}`).

Recorder statistics are now genuinely incremental per the spec's "do
not scan the archive on every request": `status()` gained
`examples_per_task`/`total_examples`/`oldest_example_ts`/
`newest_example_ts`, seeded by ONE real scan at `start()` time, then
maintained O(1) per write — `status()` itself does zero filesystem I/O
now (the old per-call directory walk is gone). Review-pack
`manifest.json` gained `task_distribution`/`model`/`prompt_versions`/
`recording_session`/`date_range`, computed from the already-collected
export list.

Verified: a mixed-archive smoke test (a hand-seeded v1.0.0-shaped line
alongside new v1.1.0 lines) confirms the stats-seeding scan, validate/
stats/export all handle old lines without error, and old examples'
new fields read `None` rather than crashing; a real 400-tick engine
run confirms the new fields land through the actual production path
with zero write errors; a 1000-tick OFF-default run confirms zero
overhead unchanged; live Playwright verification of the new tags
input. `scripts/verify_native_soak.py` (2 seeds x 1500 ticks)
byte-identical — no native module or persisted field touched.

## Current state (v0.87.28)

§8's third item (LoRA/QLoRA fine-tuning, docs/IDEAS-2026-07-
EMERGENCE.md) per explicit user request, implementing a user-supplied
"Permanent LLM Training Recorder & Dataset Pipeline Specification" —
the data-collection prerequisite only; **no fine-tuning run itself is
implemented**. Full detail: docs/TRAINING_RECORDER.md.

New `hearthmind/llm/recorder.py` (`TrainingRecorder`): OFF by default,
plain `queue.Queue` + daemon writer thread (never asyncio-integrated —
recording can't stall a tick). Every LLM task already funnels through
`SimulationEngine._record_llm_debug`, now the recorder's one call
site, so prompt/parsed-output/metadata are captured for every task,
present and future, with zero per-task code. Raw completion text
(Layer 3) needed real plumbing: `generate_json` (both clients) gained
an optional per-call `capture` dict; `CognitionRunner.run` now returns
a 3-tuple including raw text. Structured input (Layer 1) is fully
wired for every task the spec names (cognition, dialogue, beliefs,
dreams, chronicles, diplomacy, consciousness, naming, folklore,
caravans, town brain) plus `rumor_interpret`; other jobs default to
`{}` — flagged scope trim, one-line extension per job via
`_schedule_llm_job`'s new `structured_input` kwarg.

Storage: `<archive_dir>/<task>/<date>.jsonl`, daily + ~100MB rotation,
flush+fsync'd. New `llm/review_pack.py` (self-contained ZIP export,
`/recorder/export-review-pack` + `/recorder/download`) and
`scripts/recorder_tools.py` (validate/stats/export CLI, same
standalone-script convention as `verify_native_soak.py`). Control via
`/recorder/start`/`/stop` (routed through the existing `/intervene/*`
queued seam) + `/recorder/status`; new "⚙ dev" console panel.

Verified: recorder-module smoke test (off-by-default no-op, full
record/write/validate/export lifecycle); a real 400-tick engine run
(LLM disabled) confirms fallback jobs recorded through the actual
production scheduling path with zero write errors; a separate 1000-
tick run at the OFF default confirms 0 examples collected.
`scripts/verify_native_soak.py` (2 seeds x 1500 ticks) byte-identical
— no native module or persisted field touched.

## Current state (v0.87.27)

§8's geography-reshaping idea, per the same explicit sequencing as
v0.87.26 ("minerals first, then geography reshaping, LoRA left
recorded-only"). Scoped to mining scars this pass — riverbank erosion,
quarrying-as-distinct-from-mining, and disaster/climate interaction
with scarring are flagged follow-ups, not attempted. New `World.
mining_scars` (`world/terrain_evolution.py` `apply_mining_scars`/
`decay_mining_scars`): sustained GATHER-goal mining on a HILLS tile
accumulates visible scar intensity, weathering back to nothing over
weeks if abandoned — deliberately cosmetic-only (no biome change,
HILLS stays HILLS/walkable/re-minable). A flagged R7 deviation
(Python not C++, same shape as v0.87.23's spatial weather — low-
density tile lookups don't justify a native port yet). Reuses the
EXISTING terrain-resync broadcast (`WorldBroadcaster.set_terrain`,
previously biome-only) rather than a new channel — a tile crossing
`MINING_SCAR_VISIBLE_THRESHOLD` fires a `mining_scarred` event, added
to `TERRAIN_CHANGING_CATEGORIES` on both the Python and JS sides.
Rendered as a real map overlay (the Observatory UI direction's stated
preference over a sidebar panel) plus a "Mining scars" stat tile.

## Consolidated history (v0.65.2 – v0.87.26)

Full narrative/verification detail for every entry below lives in
CHANGELOG.md and docs/DECISIONS.md (and, for anything under an
IDEAS-doc section number, docs/IDEAS-2026-07-EMERGENCE.md's own
per-item writeup) — this section keeps only durable facts (mechanisms
still active, constants still in force) so CLAUDE.md stays a working
reference, not an archive. Consolidated/extended 2026-07 per explicit
user requests ("trim all the docs..." then later "clean up stale docs
and stale items").

**"The LLM learns like a human" (v0.87.0–.4)**: fully shipped, see
docs/VISION-2026-07-LEARNING.md (trimmed to a status pointer) for the
complete mechanism list — `Agent.lessons`, memory drift, salience
fade, cross-generational lesson inheritance, LLM-narrated skill
mastery, settlement pattern-beliefs, consciousness player-theory
revision, trait-consequence nudges.

**docs/IDEAS-2026-07-EMERGENCE.md §1-§9 implementation (v0.87.7–.31,
spanning most of this range)**: every checklist item across all nine
original-idea sections is shipped — see that document itself (kept as
a historical decision record, like docs/DECISIONS.md) for the full
per-item mechanism writeup. Headline mechanisms still active: heritable
trait mutation + deathbed secret release (§1); SEEK_PERSON directed
social intent; funerals/weddings with real map-visible gatherings;
generational FAMILY feuds (`Institution.feuds`, promoted from repeated
dispute outcomes) biasing dispute framing and a reproduction affinity
gate; season/year LLM job retry windows (`SEASON_YEAR_JOBS_WITH_RETRY`,
mirroring the monthly retry-window fix); letters carried by caravans
with real multi-day transit latency; migration by individual choice
(bonded partner elsewhere, ostracism, feud pressure, comparative
starvation) alongside the older whole-party fission migration; crime &
theft, inter-settlement diplomacy narration, and laws/customs/taboos
(§7's remaining gaps, all deterministic-first with one narrow LLM call
each); self-fulfilling prophecies (deterministic resolution against
`last_life_events`, never LLM-judged twice); the Chronicler (on-demand
Q&A strictly from folklore/records, honestly-wrong-capable); observer
attention feeding the Town Consciousness's favorite-agent pick and a
persistent grudge ledger about player interventions (§4); the "while
you were away" digest, anomaly/highlight log, year-reel export, ruins-
mode successor worlds, and era-styled cartography (§5); spatial weather
regions, soil fertility depletion/recovery, and ambient audio (§6);
queue-wait-per-job diagnostics (§7's last gap); adaptive memory
retrieval, causal memory links, bounded episodic planning, emergent
COUNCIL leadership contests, per-agent voice, knowledge lifecycle
(diffusion/loss/rediscovery), dialogue novelty memory (§7's earlier
items, v0.87.14–.15); the aggressive starvation-collapse fix (five
demand-side constants tuned together against real multi-seed soaks,
see `carrying_capacity`/`REPRODUCTION_SETTLEMENT_HUNGER_CEILING` in
`agents/population.py`) plus header/stat-panel UI decluttering (v0.87.
24); husbandry-seeking movement (stocked PASTURE/HATCHERY as real
FORAGE/WANDER attractors, v0.87.25); the mineral economy (`world/
minerals.py`, IRON/GOLD veins on HILLS, §8, v0.87.26) and mining scars
(`world/terrain_evolution.py`, §8, v0.87.27 — kept in this file's
"Current state" section above as the most recent §8 work); settlement-
wide topic tracking/institution culture digests/reputation-survives-
death/family-feud-festival-penalty/geography-and-events-grounded-
dialogue (§9, v0.87.31, kept in full above).

**Phase M — Faith & Meaning (v0.83.0)**: deterministic ritual detection
(`_detect_ritual_signals`, two patterns: communal feast, shrine
mourning) promotes into `Settlement.rituals` once a real pattern
repeats; religion crystallization spends one real LLM call only once a
ritual exists (`llm/religion.py`, genuine "not yet" fallback, never
fabricated); schism-on-fission lets a departing party reform an
existing religion independently; Narrative Direction (quarterly, one
short ambient-bias sentence folded into town_brain/omens/chronicle/
Dream, never an event trigger on its own).

**Phase N — The Town Awake / Town Consciousness v2 (v0.84.0–.4)**:
persistent world-scoped inner state (`World.consciousness_memory`/
`_personality`/`_objectives`/`_player_model`/`_intervention_log`),
genesis-seeded personality, monthly LLM job choosing at most one
deniable intervention from `llm.consciousness.ALLOWED_INTERVENTIONS`
(weather nudge, temperament nudge, false memory with emotional
contagion, omen/dream phrasing seeds, misplaced-object inventory
transfer — the full vision-doc menu). Fallback is a genuine no-op
("no call -> no intervention that month"), the one deliberate departure
from every other Phase L/M job's fallback shape. Surfaced in the dev
console/`full_diagnostics()` only, matching Phase G's ambiguity
discipline.

**LLM-pressure-aware tick pacing + "the town is alive" UI cues
(v0.82.0)**: `llm_pressure_ratio()`/`llm_pressure_paused()` stretch (or
pause) the real-time gap between ticks as the LLM backlog climbs past
the adaptive backpressure limit — fewer new ticks means fewer agents
becoming cognition-eligible per unit real time, giving already-in-
flight calls a real chance to resolve as genuine answers instead of
guaranteed drops. Header "the town is thinking…" indicator and a brief
map-position pulse on a genuine LLM-authored dialogue exchange, both
reading real backend state.

**Engineering Constitution pass (v0.86.0, docs/CONSTITUTION.md)**:
reordered priorities (Emergent cognition > world behaviour > learning >
memory > performance > code quality > deterministic physics > save
compatibility) and reversed prior architecture — crucial cognition
(beliefs/town_brain/personal_belief/dream/consciousness/per-agent
goals) now DEFERS on budget-exhaustion or failure instead of resolving
to a fabricated deterministic substitute; ambient/narrative jobs keep
their real deterministic fallback unchanged. `_schedule_llm_job`'s
`critical` flag and `CognitionRunner.calls_deferred_critical` counter
are the mechanism — see the "Tick loop" workflow rule above, which
this pass established.

**Durable memory to disk (v0.86.1–.9, Constitution §6)**: `World.
consciousness_*` state, then per-agent `Agent.memories`/
`semantic_memories`/`beliefs`/`secrets`, all gained a durable disk-
backed log (`consciousness_log`/`agent_memory_log` SQLite tables,
capped retention, pruned on snapshot cadence) so content evicted past
its small in-RAM cap is still retrievable — reachable via `GET
/agents/{id}/memory_log` and the NPC inspector's "Full life history."
`Agent.life_digest` (personal counterpart to `Settlement.belief_
digest`/`culture_digest`) closes the loop at individual scale.
`LLAMA_RESTART_HOURS` (`scripts/run.sh`) periodically restarts
llama-server to reclaim general heap fragmentation a KV-cache-only
defrag can't touch, now pausing the simulation (not just individual
LLM calls) with UI/diagnostics visibility across the restart window.

**Husbandry, repairs, invention scope (v0.86.7)**: `BuildingKind.
PASTURE`/`HATCHERY` (deliberate animal/fish food production, distinct
from wild foraging/hunting); `Settlement.buildings_repaired`/
`vehicles_repaired` completed-repair counters; `llm/invention.py`'s
prompt widened beyond a fixed build/farm category list.

**Native C++ port continues (R6 opportunistic-port queue,
docs/REFACTOR-2026-07.md)**: `relationship_step.cpp` (module 20,
v0.85.6), `road_wear.cpp` (module 21, v0.86.1), `wildlife_step.cpp`'s
grazer branch (module 22, v0.86.5) — same pattern as every other
module: optional extension, pure-Python fallback always correct,
randomized-equivalence + byte-identical full-state soak verified. R7
("new physical-substrate code is C++-first") deviations flagged and
documented at each site rather than silently ignored (spatial weather,
soil fertility, mining scars, minerals — all low-density tile lookups
judged not yet worth the native-port cost).

**Bug fixes and tuning (scattered across this range)**: settlement
naming/GATHER-goal materials starvation fixed via a reachability-
filtered global tile scan (v0.84.4); repopulation extended to true
extinction, count==0, reversing the prior "true extinction is a
legitimate ending" stance per explicit user request (v0.85.1); default
model `qwen3:4b-instruct` -> `gemma-4-e2b-it` (v0.85.0), per a live
"performing best" report; snow-probability threshold retuned against
measured realized frequency, then the whole 4-band sky model widened
to 6 bands with rain-share reduced (v0.85.0, v0.87.12); a routine-vs-
distinctive memory salience split fixed dialogue over-converging on
food-sharing chatter (v0.85.0); the `/intervene/town-brain` whisper-
routing bug (always wrote to the founding settlement regardless of UI
selection) fixed (v0.85.6); decay/weather-wear retuned via four
additive weather catalysts replacing one binary harsh-weather gate,
baseline rates halved (v0.87.13); g++ build parallelism actually fixed
twice — first via `os.cpu_count()`, then made cgroup/taskset-aware via
`os.sched_getaffinity(0)` once the first fix proved insufficient on a
constrained host (v0.85.6, v0.87.3); `_maybe_schedule_folklore` skips
its LLM call entirely on a month with zero rumor material (v0.86.6).

**UI polish passes**: v0.86.8 gave the `life_digest`/`culture_digest`/
"Repairs & upkeep"/"Husbandry" panels a dedicated visual pass (flat
divider-list styling, NPC memory-log scroll container) after they'd
landed functionally but never gotten one.

**LLM backend & tuning.** Switched from Ollama to `llama-server`
(llama.cpp's own HTTP server) as the default backend in v0.72.0
(`Config.llm_backend="llamacpp"`; `ollama` stays fully supported).
GPU offload (`--n-gpu-layers`, now `auto --fit on`) confirmed working
on real AMD iGPU hardware in v0.72.3, which prompted raising
`llm_num_ctx`/`llm_num_predict`/`llm_core_cast_size`/`llm_max_calls_
per_day` — then correcting them back down twice (v0.72.4: live `htop`
showed only ~6.5GB usable RAM, not the full 8GB assumed; v0.78.1: a
population-301/13k-tick diagnostic showed 2GB of llama-server swap even
at the corrected numbers). `llm_max_concurrent` has moved several times
as live diagnostics warranted (4→2→1→2→1→2 across v0.43.0–v0.81.0) —
see its docstring in config.py for the full lineage; treat neither
direction as a permanent floor, re-tune from a fresh `/diagnostics.
system_memory`/`llm_stats` reading. `scripts/run.sh` consolidated every
launch-flag tuning pass (`LLAMA_PARALLEL`/`LLAMA_CTX_SIZE`/`LLAMA_FIT_
TARGET`/`LLAMA_BATCH_SIZE`/`LLAMA_UBATCH_SIZE`/`LLAMA_DEFRAG_THOLD`/
`--reasoning off --reasoning-budget 0`/`--flash-attn on`/`LLAMA_MLOCK`)
— see README's "Running the LLM"/"Running stably for years" sections
for current defaults, not this file.

**Swap-after-hours root cause + LLM core cast (v0.70.0).** Diagnosed:
LLM call volume scaled linearly with population (one cognition call/
agent/day + per-pair dialogue), driving sustained Ollama saturation on
8GB hardware. Fixed by decoupling LLM richness from population size:
`Population.core_agent_ids` (`Config.llm_core_cast_size`, default 14) —
only this fixed, sticky, founders-seeded cast gets LLM cognition, and
only a core-core pair gets LLM dialogue; everyone/every other pair uses
the deterministic fallback. Plus a hard daily ceiling (`Config.llm_max_
calls_per_day`). **Standing rule**: any new per-agent/per-pair LLM
decision must be core-cast-gated and count against the daily ceiling;
settlement-scoped jobs stay round-robin bounded and are exempt.

**Backpressure/scheduling correctness (v0.81.0/.1).** Fixed a same-tick
backlog-reservation gap (`SimulationEngine._reserved_this_tick`, reset
each `_tick_once`) that let more concurrent jobs through than the
concurrency-derived limit intended during a burst tick. Added adaptive
load control (`_current_backpressure_limit`, tightens as rolling p95
latency crosses `ADAPTIVE_LATENCY_ELEVATED_MS`/`_SEVERE_MS`, recovers
automatically). Gave every settlement-level monthly job except
festival/caravan/omen a `MONTHLY_JOB_RETRY_WINDOW_DAYS=3` retry window
(`MONTHLY_JOBS_WITH_RETRY`) — previously a job got exactly one tick's
chance per month, so one unlucky backpressured tick meant a full month
of silence (root cause of a live "town-brain/beliefs never fire" bug).
Movement: `Agent.stuck_ticks` + a bounded `_bfs_step` escape
(`MOVEMENT_STUCK_TICKS_THRESHOLD=4`) fixes routine goal-directed
movement (FORAGE/SOCIALIZE/GATHER/WANDER) getting stuck in concave
water/mountain pockets the way travel_target journeys already handled.

**Memory/unbounded-growth audits (v0.71.0, v0.77.0, v0.78.1/.2, and
every prior pass since v0.42.0).** Repeatedly re-confirmed clean on the
Python side (flat RSS across 6,000–20,000-tick soaks every time) — the
recurring live "memory pressure" symptom has always traced to Ollama/
llama-server call volume or config, never a Python leak; diagnose via
`/diagnostics.system_memory` (attributes RSS/swap per-process) before
changing anything. Two real unbounded structures were found and fixed
on the persistence boundary: `events` table retention (`Config.event_
log_retention`, default 200k rows) and `metrics` table retention
(`Config.metrics_log_retention`, default 20k rows) — both pruned on the
snapshot cadence. Every other per-agent/per-pair collection (memories,
beliefs, relationships/trust, cooldowns, culture lists, institutions,
debts) is capped/pruned and was re-verified clean each pass.

**Native C++ port (R5–R8, docs/REFACTOR-2026-07.md).** 18 optional
native modules shipped under `hearthmind._native` (pybind11, always
paired with a pure-Python fallback and verified via randomized
equivalence + the cumulative-event-hash/full-state soak harnesses):
resource/terrain-material/agent-position/wildlife-herd spatial indexes;
`_update_needs`; predator kill-chance; farm-grid tick; building/vehicle
decay; weather blend; the shared `bounded_random_walk_step` primitive
(now backing temperament/mood/player_standing/relation ticks); wilt/
flat-damage/roll-batch (deforestation + wildfire spread) sweeps;
climate drift; `maybe_reclaim`; `SimClock.advance`; `TerrainGrid`
(object-graph storage, not just a pure function); and `AgentTable`/
`AgentStore`, wired live into `Population.agents` in v0.75.0 via an
id-keyed compatibility-shim `Agent` class — zero of the ~700 scalar
touch sites needed editing. Agent tick *logic* (population.py's
methods) remains Python, reading/writing through the C++ store; this is
the still-open next leg (R8) if native porting resumes. Every module:
optional extension, pure-Python fallback always correct, byte-identical
verified every time.

**Phase I — Inner Life (v0.76.1–.3).** `Agent.emotions` (fear/joy/
grief/anger, 0–1, decays every tick, bumped at real lived events) and
`Settlement.mood` (hope/fear/grief/suspicion, -1..1, monthly-tracked
toward the settlement's own aggregate agent emotions) — the "individual
minds aggregate into collective psychology" layer. Layered memory v1:
`Agent.memories` evicts by salience (computed from emotions at write
time) not strict FIFO, so a memorable experience outlasts a mundane
one; `Agent.working_memory` (cap 2, strict FIFO) is the separate "what
just happened" layer feeding cognition/dialogue's "just now" line.

**Phase J — Deeper Minds (v0.78.0–.4).** `Agent.semantic_memories`
(condensed lasting self-theory, written by extending the existing
monthly personal-belief call — zero added LLM volume) plus
significance-first candidate selection for that job. Event diversity
(`recent_events_diverse`/`ROUTINE_EVENT_CATEGORIES`) caps how many
routine rows can crowd an LLM prompt's event window. `Agent.secrets`
(planted by hardened dispute outcomes and, later, Reflect()) and
`Agent.mind` (one-time-authored permanent-identity paragraph, core cast
only) — both core-cast-only, reachable via the dev console.

**Phase K — Knowledge & Story (v0.79.0–.1).** `Settlement.folklore`
(monthly condensation of rumor-category events into short tales, or
correctly nothing most months). Historian v2: chronicle prompts now
interpret the season, not just summarize it. `InterpretRumor()`
(core-cast agents may retell a heard rumor distorted by their own
nature) and `Dream()` (monthly, one core-cast agent, symbolic — Phase G
ambiguity discipline applies).

**Phase L — Society & Power (v0.80.0).** `Population.reputation`
(cached monthly mean trust). `InstitutionKind.FACTION` (detected free/
deterministic via a trust-graph union-find, named via one LLM call only
once a real candidate clears the threshold). Per-pair debt ledger
(`Agent.debts`, feeds dispute framing). All three bias dispute/fission
mechanics, not just cosmetic state.

**UI/observatory milestones**: core-cast blue-triangle map markers;
dialogue grounded in `goal_reason`/memories (both LLM and fallback
paths); event feed narrowed to genuine LLM-authored dialogue only
(`is_llm` flag, v0.73.0); on-demand simulation summary tab; per-agent
Feeling/Reflections/Debts NPC-inspector sections; Faith & Rituals panel;
per-batch UI-surfacing became a standing workflow rule (see "Workflow
rules" above) starting v0.77.0.

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
- **Reversed in v0.85.1**: 0 population is no longer a permanent dead
  end — a live 60,000-tick report showed a world stuck at 0 population
  with no path back, which the user asked to be fixed rather than kept
  as a "legitimate ending." `_maybe_welcome_migrant` now also fires at
  count==0 (`Population._center_walkable_tile` supplies a neutral
  resettlement anchor once a settlement's buildings have also fully
  decayed away — see "Consolidated history" above). Historical note: the
  old rule ("migrants only arrive while 1-3 people remain, never
  auto-revive an empty world") stood from early in the project through
  v0.85.0; do not reintroduce it without a similarly explicit
  instruction.
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
